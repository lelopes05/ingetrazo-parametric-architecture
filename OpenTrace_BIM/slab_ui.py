# SPDX-License-Identifier: GPL-3.0-or-later
"""UI/controller for the parametric slab tool."""
from __future__ import annotations

import logging
import math

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QVector3D
from PySide6.QtWidgets import (QComboBox, QFormLayout, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget)
from core.snap import SnapResult, COLOR_ENDPOINT, COLOR_ON_EDGE

from . import __version__
from .commands import root_edit_allowed
from .host import (SLAB_CHAMFER_VERTEX_TOOL_KEY, SLAB_CURVE_EDGE_TOOL_KEY,
                   SLAB_FILLET_VERTEX_TOOL_KEY, SLAB_INSERT_VERTEX_TOOL_KEY,
                   SLAB_MOVE_VERTEX_TOOL_KEY, SLAB_STRETCH_EDGE_TOOL_KEY,
                   SLAB_MOVE_XY_TOOL_KEY, SLAB_MOVE_Z_TOOL_KEY, SLAB_THICKNESS_TOOL_KEY,
                   SLAB_OFFSET_TOOL_KEY, SLAB_OPENING_TOOL_KEY, SLAB_TOOL_KEY, activate_select, activate_slab,
                   activate_slab_chamfer_vertex, activate_slab_curve_edge,
                   activate_slab_fillet_vertex, activate_slab_insert_vertex,
                   activate_slab_move_vertex, activate_slab_stretch_edge,
                   activate_slab_move_xy, activate_slab_move_z, activate_slab_thickness,
                   activate_slab_offset, activate_slab_opening,
                   SLAB_OPENING_INSERT_VERTEX_TOOL_KEY, SLAB_OPENING_STRETCH_EDGE_TOOL_KEY,
                   SLAB_OPENING_MOVE_VERTEX_TOOL_KEY, SLAB_OPENING_CURVE_EDGE_TOOL_KEY,
                   SLAB_OPENING_CHAMFER_VERTEX_TOOL_KEY, SLAB_OPENING_FILLET_VERTEX_TOOL_KEY,
                   SLAB_OPENING_OFFSET_TOOL_KEY, SLAB_OPENING_MOVE_TOOL_KEY,
                   activate_slab_opening_insert_vertex, activate_slab_opening_stretch_edge,
                   activate_slab_opening_move_vertex, activate_slab_opening_curve_edge,
                   activate_slab_opening_chamfer_vertex, activate_slab_opening_fillet_vertex,
                   activate_slab_opening_offset, activate_slab_opening_move, register_tool, host_tool)
from .levels import available_levels, level_by_name
from .materials import material_names
from .palette import RadialPalette
from .layer_ui import LayerEditor
from .slab_opening import SlabOpeningTool
from .slab_opening_edit import (InsertOpeningVertexTool, StretchOpeningEdgeTool,
                                MoveOpeningVertexTool, CurveOpeningEdgeTool,
                                ChamferOpeningVertexTool, FilletOpeningVertexTool,
                                OffsetOpeningTool, MoveOpeningTool)
from .slab_commands import EditSlab
from .slab_edit import (ChamferSlabVertexTool, CurveSlabEdgeTool,
                        FilletSlabVertexTool, InsertSlabVertexTool,
                        MoveSlabVertexTool, StretchSlabEdgeTool, MoveSlabTool,
                        ChangeSlabThicknessTool, OffsetSlabBoundaryTool)
from .slab_model import (DEFAULTS, MAX_DIM, SlabError, line_edge, read_slab,
                         slab_edge_specs, slab_path_world, slab_polygon_world, slab_openings_world,
                         slab_record, sample_boundary, normalize_edge_specs)
from .slab_tool import SlabTool
from .widgets import FlexibleDoubleSpinBox as QDoubleSpinBox
from .i18n import t, ui_locale
from .snap_utils import angular_snap_result
from .icons import icon as pa_icon, set_symbol_icon

log = logging.getLogger("ingetrazo.plugins.arquitetura_parametrica.slab")
SLAB_SNAP_COLOR = (0.55, 0.36, 0.84)


def slab_icon():
    return pa_icon("slab")


def composite_slab_icon():
    return pa_icon("slab_composite")


def selected_slabs(scene):
    if getattr(scene, "edit_group", None) is not None:
        return []
    found = []
    for item in scene.selection:
        parent = getattr(item, "owner", None) or item
        if parent in scene.groups and slab_record(parent) is not None and parent not in found:
            found.append(parent)
    return found


class SlabController(QObject):
    def __init__(self, app, wall_controller=None):
        super().__init__(app.window)
        self.app = app; self.wall_controller = wall_controller; self.defaults = dict(DEFAULTS)
        self.tool = SlabTool(self)
        self.insert_tool = InsertSlabVertexTool(self)
        self.stretch_tool = StretchSlabEdgeTool(self)
        self.move_vertex_tool = MoveSlabVertexTool(self)
        self.curve_edge_tool = CurveSlabEdgeTool(self)
        self.chamfer_vertex_tool = ChamferSlabVertexTool(self)
        self.fillet_vertex_tool = FilletSlabVertexTool(self)
        self.move_xy_tool = MoveSlabTool(self, "xy")
        self.move_z_tool = MoveSlabTool(self, "z")
        self.thickness_tool = ChangeSlabThicknessTool(self)
        self.offset_tool = OffsetSlabBoundaryTool(self)
        self.opening_tool = SlabOpeningTool(self)
        self.opening_insert_tool = InsertOpeningVertexTool(self)
        self.opening_stretch_tool = StretchOpeningEdgeTool(self)
        self.opening_move_vertex_tool = MoveOpeningVertexTool(self)
        self.opening_curve_tool = CurveOpeningEdgeTool(self)
        self.opening_chamfer_tool = ChamferOpeningVertexTool(self)
        self.opening_fillet_tool = FilletOpeningVertexTool(self)
        self.opening_offset_tool = OffsetOpeningTool(self)
        self.opening_move_tool = MoveOpeningTool(self)
        self.target = None; self._loading = False; self._queued = False
        self._ui_ready = False; self._init_error = None
        self._make_action()
        try:
            self._make_panel(); self._make_mode_palette(); self._make_edit_palette()
            app.add_overlay(self.draw_reference_overlay)
            app.add_snap_provider(self._snap_provider)
            app.viewport.installEventFilter(self)
            app.viewport.sceneVersionChanged.connect(self.schedule_refresh)
            self._ui_ready = True; self.schedule_refresh()
        except Exception as exc:
            self._init_error = f"{type(exc).__name__}: {exc}"
            log.exception("slab UI setup failed after action registration")
            self.action.setToolTip("Laje paramétrica — erro de inicialização: " + self._init_error)

    def _make_panel(self):
        self.panel = QWidget(); lay = QVBoxLayout(self.panel); lay.addWidget(QLabel(t("Laje")))
        form = QFormLayout(); lay.addLayout(form)
        self.level = QComboBox(); self.level.currentIndexChanged.connect(self.level_changed); form.addRow(t("Nível"), self.level)
        self.offset = QDoubleSpinBox(); self.offset.setLocale(ui_locale()); self.offset.setDecimals(4); self.offset.setRange(-MAX_DIM, MAX_DIM); self.offset.setSingleStep(0.05); self.offset.setSuffix(" m"); self.offset.setKeyboardTracking(False); self.offset.valueChanged.connect(self.values_changed)
        self.offset.setToolTip("Com Cota livre, este valor é a cota absoluta da referência. Com nível, é o deslocamento em relação ao nível."); form.addRow(t("Cota / offset"), self.offset)
        self.thickness = QDoubleSpinBox(); self.thickness.setLocale(ui_locale()); self.thickness.setDecimals(4); self.thickness.setRange(0.001, MAX_DIM); self.thickness.setSingleStep(0.01); self.thickness.setSuffix(" m"); self.thickness.setKeyboardTracking(False); self.thickness.valueChanged.connect(self.values_changed); form.addRow(t("Espessura"), self.thickness)
        self.reference_plane = QComboBox(); self.reference_plane.addItem(t("Inferior"), "bottom"); self.reference_plane.addItem(t("Superior"), "top"); self.reference_plane.currentIndexChanged.connect(self.values_changed); self.reference_plane.setToolTip("A linha de referência da laje fica na face inferior ou superior; não existe referência central."); form.addRow(t("Referência"), self.reference_plane)
        self.material=QComboBox();self.material.currentIndexChanged.connect(self.values_changed);self.material.setToolTip("Material nomeado do IngeTrazo aplicado às faces da laje simples. Na laje composta cada camada pode ter seu material.");form.addRow(t("Material"),self.material)
        self.structure=QComboBox();self.structure.addItem(t("Simples"),"simple");self.structure.addItem(t("Composta / camadas"),"composite");self.structure.currentIndexChanged.connect(self.structure_changed);form.addRow(t("Estrutura"),self.structure)
        self.layer_editor=LayerEditor(self.panel,before_label="Abaixo",after_label="Acima");self.layer_editor.changed.connect(self.layers_changed);lay.addWidget(self.layer_editor);self.layer_editor.hide()
        self.hint = QLabel(); self.hint.setWordWrap(True); lay.addWidget(self.hint)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); lay.addWidget(self.feedback); lay.addStretch()
        ver = QLabel(f"{t('Lajes paramétricas')} · v{__version__}"); ver.setStyleSheet("color:#777; font-size:9pt;"); lay.addWidget(ver)
        self.dock = getattr(self.app.window, "_arquitetura_parametrica_master_dock", None)
        if self.dock is None:
            self.dock = self.app.add_panel(t("Laje"), self.panel, name="slab"); self.dock.hide()
        self.refresh_level_options(); self._load_defaults()

    def _make_action(self):
        self.action = QAction(slab_icon(), t("Laje paramétrica"), self.app.window); self.action.setObjectName("arquitetura_parametrica_slab_action"); self.action.setCheckable(True); self.action.setVisible(True); self.action.setToolTip(t("Laje paramétrica\nRetângulo por diagonal, base+largura ou polígono livre."))
        register_tool(self.app, self.tool, self.action, key=SLAB_TOOL_KEY)
        register_tool(self.app, self.insert_tool, key=SLAB_INSERT_VERTEX_TOOL_KEY)
        register_tool(self.app, self.stretch_tool, key=SLAB_STRETCH_EDGE_TOOL_KEY)
        register_tool(self.app, self.move_vertex_tool, key=SLAB_MOVE_VERTEX_TOOL_KEY)
        register_tool(self.app, self.curve_edge_tool, key=SLAB_CURVE_EDGE_TOOL_KEY)
        register_tool(self.app, self.chamfer_vertex_tool, key=SLAB_CHAMFER_VERTEX_TOOL_KEY)
        register_tool(self.app, self.fillet_vertex_tool, key=SLAB_FILLET_VERTEX_TOOL_KEY)
        register_tool(self.app, self.move_xy_tool, key=SLAB_MOVE_XY_TOOL_KEY)
        register_tool(self.app, self.move_z_tool, key=SLAB_MOVE_Z_TOOL_KEY)
        register_tool(self.app, self.thickness_tool, key=SLAB_THICKNESS_TOOL_KEY)
        register_tool(self.app, self.offset_tool, key=SLAB_OFFSET_TOOL_KEY)
        register_tool(self.app, self.opening_tool, key=SLAB_OPENING_TOOL_KEY)
        register_tool(self.app, self.opening_insert_tool, key=SLAB_OPENING_INSERT_VERTEX_TOOL_KEY)
        register_tool(self.app, self.opening_stretch_tool, key=SLAB_OPENING_STRETCH_EDGE_TOOL_KEY)
        register_tool(self.app, self.opening_move_vertex_tool, key=SLAB_OPENING_MOVE_VERTEX_TOOL_KEY)
        register_tool(self.app, self.opening_curve_tool, key=SLAB_OPENING_CURVE_EDGE_TOOL_KEY)
        register_tool(self.app, self.opening_chamfer_tool, key=SLAB_OPENING_CHAMFER_VERTEX_TOOL_KEY)
        register_tool(self.app, self.opening_fillet_tool, key=SLAB_OPENING_FILLET_VERTEX_TOOL_KEY)
        register_tool(self.app, self.opening_offset_tool, key=SLAB_OPENING_OFFSET_TOOL_KEY)
        register_tool(self.app, self.opening_move_tool, key=SLAB_OPENING_MOVE_TOOL_KEY)
        self.action.triggered.connect(self.start_drawing)
        self.simple_action=QAction(slab_icon(),t("Laje simples"),self.app.window);self.simple_action.triggered.connect(lambda:self.start_structure("simple"))
        self.composite_action=QAction(composite_slab_icon(),t("Laje composta"),self.app.window);self.composite_action.triggered.connect(lambda:self.start_structure("composite"))
        self.type_menu=QMenu(self.app.window);self.type_menu.addAction(self.simple_action);self.type_menu.addAction(self.composite_action)
        self.menu_button=QToolButton(self.app.window);self.menu_button.setDefaultAction(self.action);self.menu_button.setMenu(self.type_menu);self.menu_button.setPopupMode(QToolButton.MenuButtonPopup);self.menu_button.setToolTip(t("Laje — use a seta para escolher simples ou composta."))
        if self.wall_controller is not None and hasattr(self.wall_controller, "toolbar"):
            self.wall_controller.toolbar.addWidget(self.menu_button)
            if hasattr(self.wall_controller,"fit_toolbar"): self.wall_controller.fit_toolbar()
            menu = getattr(self.wall_controller, "arch_menu", None)
            if menu is not None:
                sub=menu.addMenu(t("Laje"));sub.addAction(self.simple_action);sub.addAction(self.composite_action)
        else:
            menu = self.app.add_menu(t("Ferramentas arquitetônicas"))
            if menu is not None:
                sub=menu.addMenu(t("Laje"));sub.addAction(self.simple_action);sub.addAction(self.composite_action)

    def _make_mode_palette(self):
        # Creation-method palette: now radial too, matching the edit palettes.
        # popup=False is important so choosing a method does not consume the
        # next click that belongs to the slab construction itself.
        self.mode_palette = RadialPalette(self.app.window, popup=False, role="draw")
        self.mode_palette.setObjectName("ap_slab_mode_palette")
        row = self.mode_palette.row
        self.mode_buttons = {}

        def add(symbol, tip, mode):
            b = QToolButton(self.mode_palette)
            set_symbol_icon(b, symbol)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setFixedSize(36, 36)
            f = b.font(); f.setPointSize(16); b.setFont(f)
            b.clicked.connect(lambda _c=False, m=mode: self.choose_mode(m))
            row.addWidget(b)
            self.mode_buttons[mode] = b

        add("▱", t("Retângulo por diagonal: primeiro e último clique são cantos opostos."), "diagonal")
        add("⊥", t("Retângulo por base + largura: início, fim da base e largura perpendicular."), "base_width")
        add("⬠", t("Polígono livre: clique os vértices e finalize clicando novamente no primeiro."), "polygon")
        self.mode_palette.hide()

    def _make_edit_palette(self):
        self.edit_palette = RadialPalette(self.app.window, popup=False, role="edit"); self.edit_palette.setObjectName("ap_slab_edit_palette"); row=self.edit_palette.row
        def add(symbol, tip, slot):
            b=QToolButton(self.edit_palette); set_symbol_icon(b, symbol); b.setToolTip(tip); b.setAutoRaise(True); b.setFixedSize(34,34); f=b.font(); f.setPointSize(16); b.setFont(f); b.clicked.connect(slot); row.addWidget(b); return b
        self.insert_btn=add("＋", t("Inserir vértice nesta aresta."), self.begin_insert_vertex)
        self.stretch_btn=add("⇱", t("Estender/extrudar esta aresta perpendicularmente, preservando os dois vértices atuais como ancoragens."), self.begin_stretch_edge)
        self.curve_btn=add("⌒", t("Curvar esta aresta mantendo suas extremidades."), self.begin_curve_edge)
        self.offset_btn=add("⤢", t("Offset de todo o contorno: arraste para fora ou para dentro."), self.begin_offset)
        self.opening_btn=add("□", t("Criar uma abertura poligonal interna nesta laje."), self.begin_opening)
        self.delete_opening_btn=add("⊘", t("Excluir esta abertura da laje."), self.delete_opening)
        self.move_xy_btn=add("↔", t("Mover a laje inteira no plano horizontal."), self.begin_move_xy)
        self.move_z_btn=add("↕", t("Mover a laje inteira somente na vertical."), self.begin_move_z)
        self.move_vertex_btn=add("✥", t("Mover este vértice livremente no plano horizontal."), self.begin_move_vertex)
        self.delete_vertex_btn=add("⌫", t("Excluir este vértice e ligar os dois vizinhos por uma aresta reta."), self.delete_vertex)
        self.chamfer_btn=add("◩", t("Chanfrar este vértice. Mova o mouse para definir o tamanho e clique."), self.begin_chamfer_vertex)
        self.fillet_btn=add("◜", t("Arredondar este vértice (fillet). O limite é o próximo vértice das arestas adjacentes."), self.begin_fillet_vertex)
        self.thickness_btn=add("⇧", t("Alterar somente a espessura da laje pela face superior."), self.begin_thickness)
        self.edit_palette.hide(); self._edit_slab=None; self._edit_kind=None; self._edit_index=None; self._edit_anchor=None

    def show_mode_palette(self, screen_pos):
        for mode,b in self.mode_buttons.items(): b.setChecked(mode==self.tool.mode)
        pos=self.app.viewport.mapToGlobal(QPoint(int(screen_pos.x()),int(screen_pos.y())))
        self.mode_palette.show_at(pos)

    def hide_mode_palette(self): self.mode_palette.hide()
    def choose_mode(self, mode): self.tool.set_mode(mode); self.hide_mode_palette(); self.app.viewport.setFocus()

    def current_reference_z(self):
        base=float(self.defaults.get("base_z",0.0))
        if self.defaults.get("base_level"):
            lv=level_by_name(self.app,self.defaults["base_level"])
            if lv is not None: base=float(lv["z"])+float(self.defaults.get("base_offset",0.0))
        return base + (float(self.defaults.get("thickness",0.0)) if self.defaults.get("reference_plane")=="top" else 0.0)

    def _load_defaults(self):
        self._loading=True
        try:
            self.thickness.setValue(self.defaults["thickness"]); self.offset.setValue(self.defaults["base_z"]); idx=self.reference_plane.findData(self.defaults["reference_plane"]); self.reference_plane.setCurrentIndex(max(0,idx));self.refresh_material_options();mi=self.material.findData(self.defaults.get("material_name"));self.material.setCurrentIndex(mi if mi>=0 else 0);si=self.structure.findData(self.defaults.get("structure","simple"));self.structure.setCurrentIndex(si if si>=0 else 0);self.layer_editor.set_layers(self.defaults.get("layers",[]),self.defaults["thickness"],self.defaults.get("material_name"));self._update_structure_ui()
        finally:self._loading=False

    def refresh_level_options(self):
        current=self.level.currentData() if self.level.count() else None; self.level.blockSignals(True); self.level.clear(); self.level.addItem(t("Cota livre"),None)
        for lv in available_levels(self.app): self.level.addItem(f"{lv['name']}  ({lv['z']:+.2f} m)",lv['name'])
        i=self.level.findData(current); self.level.setCurrentIndex(i if i>=0 else 0); self.level.blockSignals(False)

    def refresh_material_options(self):
        current=self.material.currentData() if self.material.count() else self.defaults.get("material_name")
        names=material_names(self.app.scene);key=tuple(names)
        if getattr(self,"_material_options_key",None)!=key:
            self.material.blockSignals(True);self.material.clear();self.material.addItem(t("Padrão"),None)
            for name in names:self.material.addItem(name,name)
            i=self.material.findData(current);self.material.setCurrentIndex(i if i>=0 else 0);self.material.blockSignals(False)
            self._material_options_key=key
        if hasattr(self,"layer_editor"):self.layer_editor.set_material_names(names)

    def level_changed(self,*_):
        if self._loading:return
        old_ref=float(self.defaults.get("base_z",0.0)); name=self.level.currentData(); self._loading=True
        try:
            if name:
                lv=level_by_name(self.app,name); off=old_ref-float(lv["z"]) if lv is not None else 0.0; self.offset.setValue(off); self.defaults["base_level"]=name; self.defaults["base_offset"]=off; self.defaults["base_z"]=(float(lv["z"])+off) if lv is not None else old_ref
            else:
                self.offset.setValue(old_ref); self.defaults["base_level"]=None; self.defaults["base_offset"]=0.0; self.defaults["base_z"]=old_ref
        finally:self._loading=False
        self.apply_current_values()

    def values_changed(self,*_):
        if self._loading:return
        self.defaults["structure"]=self.structure.currentData() or "simple";self.defaults["layers"]=self.layer_editor.layers() if self.defaults["structure"]=="composite" else [];self.defaults["thickness"]=(sum(float(x["thickness"]) for x in self.defaults["layers"]) if self.defaults["structure"]=="composite" else float(self.thickness.value())); self.defaults["reference_plane"]=self.reference_plane.currentData();self.defaults["material_name"]=self.material.currentData(); name=self.level.currentData(); self.defaults["base_level"]=name
        if name:
            self.defaults["base_offset"]=float(self.offset.value()); lv=level_by_name(self.app,name)
            if lv is not None:self.defaults["base_z"]=float(lv["z"])+self.defaults["base_offset"]
        else:self.defaults["base_offset"]=0.0; self.defaults["base_z"]=float(self.offset.value())
        self.apply_current_values()

    def _update_structure_ui(self):
        composite=(self.structure.currentData()=="composite")
        self.layer_editor.setVisible(composite);self.thickness.setEnabled(not composite);self.material.setEnabled(not composite)
        if composite:self.hint.setText("Laje composta: a espessura total é a soma das camadas; o hotspot de espessura fica desativado.")

    def structure_changed(self,*_):
        if self._loading:return
        kind=self.structure.currentData() or "simple"
        if kind=="composite" and not self.defaults.get("layers"):
            self.layer_editor.set_layers([],float(self.thickness.value()),self.material.currentData())
        self.defaults["structure"]=kind;self.defaults["layers"]=self.layer_editor.layers() if kind=="composite" else []
        if kind=="composite":self.defaults["thickness"]=sum(float(x["thickness"]) for x in self.defaults["layers"])
        self.action.setIcon(composite_slab_icon() if kind=="composite" else slab_icon())
        self._update_structure_ui();self.apply_current_values()

    def layers_changed(self):
        if self._loading or self.structure.currentData()!="composite":return
        self.defaults["layers"]=self.layer_editor.layers();self.defaults["thickness"]=sum(float(x["thickness"]) for x in self.defaults["layers"]);self.apply_current_values()

    def start_structure(self,kind):
        self._loading=True
        try:
            i=self.structure.findData(kind);self.structure.setCurrentIndex(i if i>=0 else 0)
            if kind=="composite" and not self.defaults.get("layers"):self.layer_editor.set_layers([],float(self.thickness.value()),self.material.currentData())
            self.defaults["structure"]=kind;self.defaults["layers"]=self.layer_editor.layers() if kind=="composite" else []
            if kind=="composite":self.defaults["thickness"]=sum(float(x["thickness"]) for x in self.defaults["layers"])
        finally:self._loading=False
        self.action.setIcon(composite_slab_icon() if kind=="composite" else slab_icon())
        self._update_structure_ui()
        # Do not reactivate/toggle the same slab tool just to change the
        # simple/composite structure.  One click must be enough to switch.
        if self.app.viewport.active_tool is self.tool:
            self.schedule_refresh()
            self.message("Clique no primeiro ponto da laje. Retângulo por diagonal é o modo padrão.")
            self.app.viewport.setFocus()
        else:
            self.start_drawing()

    def slab_reference_z(self,slab):
        vals=read_slab(slab);return vals["base_z"]+(vals["thickness"] if vals.get("reference_plane")=="top" else 0.0)

    def apply_current_values(self):
        if self.target is None or self._loading:return
        try:
            self.app.viewport.history.execute(EditSlab(self.app.scene,self.target,values=dict(self.defaults)))
            if self.app.viewport.history.last_error:raise SlabError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed()
        except SlabError as exc:self.message(str(exc),error=True)

    def _sync_level_bound_slabs(self):
        changed=0
        for g in list(self.app.scene.groups):
            rec=slab_record(g)
            if rec is None or not rec.get("base_level"):continue
            lv=level_by_name(self.app,rec.get("base_level"))
            if lv is None:continue
            try:
                old=read_slab(g);desired=float(lv["z"])+float(rec.get("base_offset",0.0))
                if abs(desired-old["base_z"])<=1e-7:continue
                EditSlab(self.app.scene,g,values=dict(old,base_z=desired)).do(self.app.scene);changed+=1
            except SlabError:continue
        return changed

    def schedule_refresh(self,*_):
        if not getattr(self,"_ui_ready",False) or self._queued:return
        self._queued=True;QTimer.singleShot(0,self.refresh)

    def refresh(self):
        self._queued=False
        try:self._sync_level_bound_slabs()
        except Exception:log.exception("slab level sync failed")
        self.refresh_level_options();self.refresh_material_options();slabs=selected_slabs(self.app.scene);self.target=slabs[0] if len(slabs)==1 else None
        if self.target is not None:
            try:
                vals=read_slab(self.target);self.defaults.update({k:v for k,v in vals.items() if k!="openings"});self.defaults["openings"]=[];self._loading=True;name=vals.get("base_level");idx=self.level.findData(name);self.level.setCurrentIndex(idx if idx>=0 else 0);self.offset.setValue(vals["base_offset"] if name else vals["base_z"]);self.thickness.setValue(vals["thickness"]);self.reference_plane.setCurrentIndex(max(0,self.reference_plane.findData(vals["reference_plane"])));mi=self.material.findData(vals.get("material_name"));self.material.setCurrentIndex(mi if mi>=0 else 0);si=self.structure.findData(vals.get("structure","simple"));self.structure.setCurrentIndex(si if si>=0 else 0);
                if not self.layer_editor.user_is_editing():
                    self.layer_editor.set_layers(vals.get("layers",[]),vals["thickness"],vals.get("material_name"))
                self._loading=False;self._update_structure_ui()
                self.hint.setText("Clique na referência: aresta = inserir/estender/curvar/offset/mover laje; vértice = mover/excluir/chanfrar/fillet; hotspot superior = espessura.");self.app.show_panel(self.dock)
            except SlabError as exc:self._loading=False;self.message(str(exc),error=True)
        elif self.app.viewport.active_tool is self.tool:
            self.hint.setText("Desenhe no plano horizontal. O modo padrão é retângulo por diagonal.");self.app.show_panel(self.dock)
        self.app.viewport.update()

    def start_drawing(self,*_):
        if not getattr(self,"_ui_ready",False):
            self.action.setChecked(False);msg="Laje indisponível nesta sessão"+((": "+self._init_error) if self._init_error else ".");self.app.viewport.flash_status(msg,8000);return
        try:
            root_edit_allowed(self.app.scene)
            if self.app.workspace() is not None:raise SlabError("Volte ao modelo para desenhar lajes.")
        except SlabError as exc:self.action.setChecked(False);self.app.viewport.flash_status(t(str(exc)),6000);return
        self.app.scene.clear_selection();self.defaults["openings"]=[];self.tool.reset();activate_slab(self.app);self.schedule_refresh();self.message("Clique no primeiro ponto da laje. Retângulo por diagonal é o modo padrão.");self.app.viewport.setFocus()

    def stop_drawing(self):self.hide_mode_palette();activate_select(self.app);self.action.setChecked(False);self.schedule_refresh()
    def return_to_select(self):activate_select(self.app);self.schedule_refresh();self.app.viewport.setFocus()
    def message(self,text,error=False):
        shown=t(text)
        if hasattr(self,"feedback"):
            self.feedback.setText(shown);self.feedback.setStyleSheet("color:#b00020;" if error else "")
        if text:self.app.viewport.flash_status(shown,8000 if error else 15000)

    @staticmethod
    def _pixel_segment_nearest(px,py,a,b):
        ax,ay=a;bx,by=b;dx,dy=bx-ax,by-ay;den=dx*dx+dy*dy
        if den<=1e-12:return math.hypot(px-ax,py-ay),0.0
        t=max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/den));x=ax+t*dx;y=ay+t*dy;return math.hypot(px-x,py-y),t

    def _reference_context(self,px,py,slab):
        try:
            logical=slab_polygon_world(slab,reference=True);path,mapping=slab_path_world(slab,reference=True,with_map=True)
            vals=read_slab(slab)
            ref_z=logical[0].z() if logical else vals["base_z"]
            top=[] if vals.get("structure")=="composite" else [QVector3D(p.x(),p.y(),vals["base_z"]+vals["thickness"]) for p in logical]
        except SlabError:return None
        threshold=max(7.0,float(getattr(self.app.viewport,"snap_threshold_px",10.0)));best=None
        # Hosted openings expose the same logical vertices/edges as the outer
        # slab contour. Curved edges are sampled only for hit-testing; the
        # returned index is always the logical edge/vertex, never a tessellation
        # point.
        try:
            for oi,op in enumerate(slab_openings_world(slab,reference=True)):
                pts=[QVector3D(*raw) for raw in op.get("polygon",[])]
                specs=normalize_edge_specs(op.get("edges"),len(pts))
                scr=[self.app.viewport._world_to_pixel(p) for p in pts]
                vbest=None
                for vi,(p,scrp) in enumerate(zip(pts,scr)):
                    if scrp is None: continue
                    d=math.hypot(px-scrp[0],py-scrp[1])
                    if d<=threshold and (vbest is None or d<vbest[0]): vbest=(d,vi,p)
                if vbest is not None and (best is None or vbest[0]<best[0]):
                    best=(vbest[0],"opening_vertex",(oi,vbest[1]),QVector3D(vbest[2]))
                sampled,opening_mapping=sample_boundary(pts,specs,with_map=True)
                if pts: sampled=[QVector3D(p.x(),p.y(),pts[0].z()) for p in sampled]
                ps=[self.app.viewport._world_to_pixel(p) for p in sampled]
                for k in range(len(sampled)):
                    a=ps[k];b=ps[(k+1)%len(sampled)]
                    if a is None or b is None:continue
                    d,tt=self._pixel_segment_nearest(px,py,a,b)
                    if d<=threshold and (best is None or d<best[0]):
                        anchor=sampled[k]+(sampled[(k+1)%len(sampled)]-sampled[k])*tt
                        best=(d,"opening_edge",(oi,opening_mapping[k]),anchor)
            if best is not None:return best[1:]
        except SlabError:pass
        # Dedicated physical-top thickness handles.  When the reference itself is
        # the top plane (or a top view collapses Z), shift the handle 12 pixels up
        # so both path editing and thickness editing remain reachable.
        ref_screen=[self.app.viewport._world_to_pixel(p) for p in logical]
        top_screen=[self.app.viewport._world_to_pixel(p) for p in top]
        for i,(ts,rs) in enumerate(zip(top_screen,ref_screen)):
            if ts is None:continue
            hx,hy=ts
            if rs is not None and math.hypot(ts[0]-rs[0],ts[1]-rs[1])<7.0:hy-=12.0
            d=math.hypot(px-hx,py-hy)
            if d<=threshold and (best is None or d<best[0]):best=(d,"thickness",i,top[i])
        if best is not None:return best[1:]
        best=None
        for i,(p,scr) in enumerate(zip(logical,ref_screen)):
            if scr is None:continue
            d=math.hypot(px-scr[0],py-scr[1])
            if d<=threshold and (best is None or d<best[0]):best=(d,"vertex",i,p)
        if best is not None:return best[1:]
        screen=[self.app.viewport._world_to_pixel(p) for p in path]
        for k in range(len(path)):
            a=screen[k];b=screen[(k+1)%len(path)]
            if a is None or b is None:continue
            d,t=self._pixel_segment_nearest(px,py,a,b)
            if d<=threshold and (best is None or d<best[0]):
                anchor=path[k]+(path[(k+1)%len(path)]-path[k])*t;best=(d,"edge",mapping[k],anchor)
        return None if best is None else best[1:]

    def _snap_provider(self,viewport,snap,px,py):
        # Logical slab/opening references get native-looking endpoint/on-edge
        # markers even when the reference plane is not a physical mesh edge.
        threshold=float(getattr(viewport,"snap_threshold_px",12.0));best=None
        for slab in list(viewport.scene.groups):
            if slab_record(slab) is None:continue
            try:
                logical=slab_polygon_world(slab,reference=True);path,_=slab_path_world(slab,reference=True,with_map=True)
            except SlabError:continue
            for p in logical:
                sp=viewport._world_to_pixel(p)
                if sp is None:continue
                d=math.hypot(px-sp[0],py-sp[1])
                if d<=threshold and (best is None or d<best[0]):best=(d,QVector3D(p),"endpoint",t("Vértice da laje"))
            try:
                for op in slab_openings_world(slab,reference=True):
                    opts=[QVector3D(*raw) for raw in op.get("polygon",[])];specs=normalize_edge_specs(op.get("edges"),len(opts))
                    for p in opts:
                        sp=viewport._world_to_pixel(p)
                        if sp is None:continue
                        d=math.hypot(px-sp[0],py-sp[1])
                        if d<=threshold and (best is None or d<best[0]):best=(d,p,"endpoint",t("Vértice da abertura"))
                    sampled=sample_boundary(opts,specs)
                    if opts: sampled=[QVector3D(p.x(),p.y(),opts[0].z()) for p in sampled]
                    pixels=[viewport._world_to_pixel(p) for p in sampled]
                    for i in range(len(sampled)):
                        a=pixels[i];b=pixels[(i+1)%len(sampled)]
                        if a is None or b is None:continue
                        d,tt=self._pixel_segment_nearest(px,py,a,b)
                        if d<=threshold and (best is None or d<best[0]):
                            q=sampled[i]+(sampled[(i+1)%len(sampled)]-sampled[i])*tt;best=(d,q,"on_edge",t("Referência da abertura"))
            except SlabError:pass
            pixels=[viewport._world_to_pixel(p) for p in path]
            for i in range(len(path)):
                a=pixels[i];b=pixels[(i+1)%len(path)]
                if a is None or b is None:continue
                d,tt=self._pixel_segment_nearest(px,py,a,b)
                if d<=threshold and (best is None or d<best[0]):
                    q=path[i]+(path[(i+1)%len(path)]-path[i])*tt;best=(d,q,"on_edge",t("Referência da laje"))
        if best is not None:
            _d,q,kind,label=best
            return SnapResult(q,kind,COLOR_ENDPOINT if kind=="endpoint" else COLOR_ON_EDGE,label=label)
        return angular_snap_result(viewport,snap,px,py)

    def eventFilter(self,obj,event):
        if obj is self.app.viewport and event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
            if self.edit_palette.isVisible():
                self.edit_palette.hide();self._edit_slab=None;self._edit_kind=None;self._edit_index=None;self._edit_anchor=None
            if event.modifiers()==Qt.NoModifier:
                vp=self.app.viewport;select_tool=host_tool(self.app, "select");slabs=selected_slabs(self.app.scene)
                if vp.active_tool is select_tool and len(slabs)==1:
                    hit=self._reference_context(event.position().x(),event.position().y(),slabs[0])
                    if hit is not None:
                        kind,index,anchor=hit;self.show_edit_palette(event.globalPosition().toPoint(),slabs[0],kind,index,anchor);return True
        return super().eventFilter(obj,event)

    def show_edit_palette(self,global_pos,slab,kind,index,anchor):
        self._edit_slab=slab;self._edit_kind=kind;self._edit_index=index;self._edit_anchor=QVector3D(anchor)
        edge=kind=="edge";vertex=kind=="vertex";thickness=kind=="thickness"
        opening_edge=kind=="opening_edge";opening_vertex=kind=="opening_vertex";opening=opening_edge or opening_vertex
        self.insert_btn.setVisible(edge or opening_edge)
        self.stretch_btn.setVisible(edge or opening_edge)
        self.curve_btn.setVisible(edge or opening_edge)
        self.offset_btn.setVisible(edge or opening_edge)
        self.opening_btn.setVisible(edge or vertex)
        self.delete_opening_btn.setVisible(opening)
        self.move_xy_btn.setVisible(edge or vertex or opening)
        self.move_z_btn.setVisible(edge or vertex)
        self.move_vertex_btn.setVisible(vertex or opening_vertex)
        self.delete_vertex_btn.setVisible(vertex or opening_vertex)
        self.chamfer_btn.setVisible(vertex or opening_vertex)
        self.fillet_btn.setVisible(vertex or opening_vertex)
        self.thickness_btn.setVisible(thickness)
        if opening:
            self.insert_btn.setToolTip(t("Inserir vértice nesta aresta da abertura."))
            self.stretch_btn.setToolTip(t("Estender/extrudar esta aresta da abertura perpendicularmente."))
            self.curve_btn.setToolTip(t("Curvar esta aresta da abertura mantendo suas extremidades."))
            self.offset_btn.setToolTip(t("Offset de todo o contorno desta abertura."))
            self.move_xy_btn.setToolTip(t("Mover a abertura inteira no plano horizontal."))
            self.move_vertex_btn.setToolTip(t("Mover este vértice da abertura no plano horizontal."))
            self.delete_vertex_btn.setToolTip(t("Excluir este vértice da abertura."))
            self.chamfer_btn.setToolTip(t("Chanfrar este vértice da abertura."))
            self.fillet_btn.setToolTip(t("Arredondar este vértice da abertura (fillet)."))
        else:
            self.insert_btn.setToolTip(t("Inserir vértice nesta aresta."))
            self.stretch_btn.setToolTip(t("Estender/extrudar esta aresta perpendicularmente, preservando os dois vértices atuais como ancoragens."))
            self.curve_btn.setToolTip(t("Curvar esta aresta mantendo suas extremidades."))
            self.offset_btn.setToolTip(t("Offset de todo o contorno: arraste para fora ou para dentro."))
            self.move_xy_btn.setToolTip(t("Mover a laje inteira no plano horizontal."))
            self.move_vertex_btn.setToolTip(t("Mover este vértice livremente no plano horizontal."))
            self.delete_vertex_btn.setToolTip(t("Excluir este vértice e ligar os dois vizinhos por uma aresta reta."))
            self.chamfer_btn.setToolTip(t("Chanfrar este vértice. Mova o mouse para definir o tamanho e clique."))
            self.fillet_btn.setToolTip(t("Arredondar este vértice (fillet). O limite é o próximo vértice das arestas adjacentes."))
        self.edit_palette.show_at(global_pos)

    def _arm(self,tool,activator):
        self.edit_palette.hide()
        try:tool.arm(self._edit_slab,self._edit_index,self._edit_anchor);activator(self.app);self.app.viewport.setFocus()
        except SlabError as exc:self.message(str(exc),error=True)

    def begin_insert_vertex(self):
        if self._edit_kind=="opening_edge": self._arm(self.opening_insert_tool,activate_slab_opening_insert_vertex)
        else: self._arm(self.insert_tool,activate_slab_insert_vertex)
    def begin_stretch_edge(self):
        if self._edit_kind=="opening_edge": self._arm(self.opening_stretch_tool,activate_slab_opening_stretch_edge)
        else: self._arm(self.stretch_tool,activate_slab_stretch_edge)
    def begin_move_vertex(self):
        if self._edit_kind=="opening_vertex": self._arm(self.opening_move_vertex_tool,activate_slab_opening_move_vertex)
        else: self._arm(self.move_vertex_tool,activate_slab_move_vertex)
    def begin_curve_edge(self):
        if self._edit_kind=="opening_edge": self._arm(self.opening_curve_tool,activate_slab_opening_curve_edge)
        else: self._arm(self.curve_edge_tool,activate_slab_curve_edge)
    def begin_chamfer_vertex(self):
        if self._edit_kind=="opening_vertex": self._arm(self.opening_chamfer_tool,activate_slab_opening_chamfer_vertex)
        else: self._arm(self.chamfer_vertex_tool,activate_slab_chamfer_vertex)
    def begin_fillet_vertex(self):
        if self._edit_kind=="opening_vertex": self._arm(self.opening_fillet_tool,activate_slab_opening_fillet_vertex)
        else: self._arm(self.fillet_vertex_tool,activate_slab_fillet_vertex)
    def begin_move_xy(self):
        if self._edit_kind in ("opening_edge","opening_vertex"): self._arm(self.opening_move_tool,activate_slab_opening_move)
        else: self._arm(self.move_xy_tool,activate_slab_move_xy)
    def begin_move_z(self):self._arm(self.move_z_tool,activate_slab_move_z)
    def begin_thickness(self):self._arm(self.thickness_tool,activate_slab_thickness)
    def begin_offset(self):
        if self._edit_kind=="opening_edge": self._arm(self.opening_offset_tool,activate_slab_opening_offset)
        else: self._arm(self.offset_tool,activate_slab_offset)
    def begin_opening(self):self._arm(self.opening_tool,activate_slab_opening)

    def delete_opening(self):
        self.edit_palette.hide()
        try:
            slab=self._edit_slab;ops=slab_openings_world(slab,reference=True)
            token=self._edit_index;i=int(token[0] if isinstance(token,(tuple,list)) else token)
            if i<0 or i>=len(ops):raise SlabError("A abertura não está mais disponível.")
            del ops[i];self.app.viewport.history.execute(EditSlab(self.app.scene,slab,openings=ops))
            if self.app.viewport.history.last_error:raise SlabError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed();self.message("Abertura excluída.")
        except SlabError as exc:self.message(str(exc),error=True)
        self.app.viewport.setFocus()

    def delete_vertex(self):
        self.edit_palette.hide()
        try:
            slab=self._edit_slab
            if self._edit_kind=="opening_vertex":
                token=self._edit_index;oi,vi=int(token[0]),int(token[1]);ops=slab_openings_world(slab,reference=True)
                if oi<0 or oi>=len(ops):raise SlabError("A abertura não está mais disponível.")
                item=ops[oi];pts=[QVector3D(*raw) for raw in item.get("polygon",[])];specs=normalize_edge_specs(item.get("edges"),len(pts));n=len(pts);i=vi%n
                if n<=3:raise SlabError("Uma abertura precisa manter pelo menos três vértices.")
                old_indices=[k for k in range(n) if k!=i];new_pts=[QVector3D(pts[k]) for k in old_indices];new_specs=[]
                for k,aidx in enumerate(old_indices):
                    bidx=old_indices[(k+1)%len(old_indices)];new_specs.append(dict(specs[aidx]) if bidx==(aidx+1)%n else line_edge())
                item=dict(item);item["polygon"]=[[p.x(),p.y(),p.z()] for p in new_pts];item["edges"]=new_specs;ops[oi]=item
                self.app.viewport.history.execute(EditSlab(self.app.scene,slab,openings=ops))
                msg="Vértice da abertura excluído."
            else:
                pts=slab_polygon_world(slab,reference=True);specs=slab_edge_specs(slab);n=len(pts);i=int(self._edit_index)%n
                if n<=3:raise SlabError("Uma laje precisa manter pelo menos três vértices.")
                old_indices=[k for k in range(n) if k!=i];new_pts=[QVector3D(pts[k]) for k in old_indices];new_specs=[]
                for k,aidx in enumerate(old_indices):
                    bidx=old_indices[(k+1)%len(old_indices)];new_specs.append(dict(specs[aidx]) if bidx==(aidx+1)%n else line_edge())
                self.app.viewport.history.execute(EditSlab(self.app.scene,slab,world_polygon=new_pts,edge_specs=new_specs));msg="Vértice excluído."
            if self.app.viewport.history.last_error:raise SlabError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed();self.message(msg)
        except SlabError as exc:self.message(str(exc),error=True)
        self.app.viewport.setFocus()

    def draw_reference_overlay(self,viewport,painter):
        slabs=selected_slabs(self.app.scene)
        if not slabs:return
        pen=QPen(QColor("#8a5bd6"),2.0,Qt.DashLine);vp=QPen(QColor("#8a5bd6"),1.5);hp=QPen(QColor("#f0a33b"),1.6)
        for slab in slabs:
            try:
                path=slab_path_world(slab,reference=True);logical=slab_polygon_world(slab,reference=True);vals=read_slab(slab)
            except SlabError:continue
            pix=[viewport._world_to_pixel(p) for p in path];painter.setPen(pen)
            for a,b in zip(pix,pix[1:]+pix[:1]):
                if a is not None and b is not None:painter.drawLine(QPointF(a[0],a[1]),QPointF(b[0],b[1]))
            # Embedded openings are reference polygons owned by the slab host.
            try:
                for op in slab_openings_world(slab,reference=True):
                    opts=[QVector3D(*raw) for raw in op.get("polygon",[])];specs=normalize_edge_specs(op.get("edges"),len(opts));sampled=sample_boundary(opts,specs)
                    if opts: sampled=[QVector3D(p.x(),p.y(),opts[0].z()) for p in sampled]
                    os=[viewport._world_to_pixel(p) for p in sampled];painter.setPen(QPen(QColor("#d8644d"),1.8,Qt.DashLine))
                    for a,b in zip(os,os[1:]+os[:1]):
                        if a is not None and b is not None:painter.drawLine(QPointF(a[0],a[1]),QPointF(b[0],b[1]))
                    painter.setPen(QPen(QColor("#d8644d"),1.3));painter.setBrush(QColor("white"))
                    for p in opts:
                        q=viewport._world_to_pixel(p)
                        if q is not None:painter.drawEllipse(QRectF(q[0]-3.2,q[1]-3.2,6.4,6.4))
            except SlabError:pass
            logical_pix=[viewport._world_to_pixel(p) for p in logical]
            painter.setPen(vp);painter.setBrush(QColor("white"))
            for q in logical_pix:
                if q is not None:painter.drawEllipse(QRectF(q[0]-3.5,q[1]-3.5,7,7))
            # Physical-top thickness hotspots at every logical vertex.  If top
            # and reference overlap in screen space, show the handle 12 px above
            # with a short leader instead of sacrificing either control.
            top=[] if vals.get("structure")=="composite" else [QVector3D(p.x(),p.y(),vals["base_z"]+vals["thickness"]) for p in logical]
            top_pix=[viewport._world_to_pixel(p) for p in top]
            painter.setPen(hp);painter.setBrush(QColor("white"))
            for i,q in enumerate(top_pix):
                if q is None:continue
                hx,hy=q;rp=logical_pix[i] if i<len(logical_pix) else None
                shifted=False
                if rp is not None and math.hypot(q[0]-rp[0],q[1]-rp[1])<7.0:
                    hy-=12.0;shifted=True
                if shifted:painter.drawLine(QPointF(q[0],q[1]),QPointF(hx,hy+4))
                painter.drawEllipse(QRectF(hx-4,hy-4,8,8));painter.drawLine(QPointF(hx-5.5,hy),QPointF(hx+5.5,hy))

