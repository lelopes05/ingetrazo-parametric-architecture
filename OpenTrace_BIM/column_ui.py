# SPDX-License-Identifier: GPL-3.0-or-later
"""Column palette, toolbar action and graphical top handle."""
from __future__ import annotations
import logging, math
from PySide6.QtCore import QEvent,QPoint,QPointF,QRectF,QSize,Qt,QTimer
from PySide6.QtGui import QAction,QColor,QIcon,QPainter,QPen,QPixmap,QVector3D
from PySide6.QtWidgets import (QComboBox,QFormLayout,QGridLayout,QHBoxLayout,
                               QLabel,QToolButton,QVBoxLayout,QWidget)
from . import __version__
from .column_commands import EditColumn
from .column_height import ChangeColumnHeightTool
from .materials import material_names
from .profile_library import load_profiles, profile_by_id

from .column_model import (ANCHOR_FACTORS,DEFAULTS,MAX_DIM,MIN_DIM,ColumnError,column_record,
                           insertion_world,read_column,top_world,reference_path_world,midpoint_world,
                           station_points_world,nearest_path_fraction,insert_station,segment_index_at_fraction)
from .column_tool import ColumnTool
from .structure_edit import MoveWholeStructureTool, ColumnCurveTool, ColumnInclineTool, MoveColumnStationVerticalTool
from .palette import RadialPalette
from .commands import root_edit_allowed
from .host import (COLUMN_HEIGHT_TOOL_KEY,COLUMN_TOOL_KEY,COLUMN_MOVE_TOOL_KEY,COLUMN_CURVE_TOOL_KEY,
                   COLUMN_INCLINE_TOOL_KEY,COLUMN_STATION_Z_TOOL_KEY,activate_column,activate_column_height,activate_column_move,
                   activate_column_curve,activate_column_incline,activate_column_station_z,activate_select,register_tool, host_tool)
from .levels import available_levels,level_by_name
from .i18n import t, ui_locale
from .widgets import FlexibleDoubleSpinBox as QDoubleSpinBox
from .icons import icon as pa_icon, set_symbol_icon

log=logging.getLogger("ingetrazo.plugins.arquitetura_parametrica")

def column_icon():
    return pa_icon("column")


def selected_columns(scene):
    if getattr(scene,"edit_group",None) is not None:return []
    out=[]
    for item in scene.selection:
        g=getattr(item,"owner",None) or item
        if g in scene.groups and column_record(g) is not None and g not in out:out.append(g)
    return out

class ColumnController(QWidget):
    def __init__(self,app,wall_controller=None):
        super().__init__(app.window);self.app=app;self.wall_controller=wall_controller;self.defaults=dict(DEFAULTS)
        self.tool=ColumnTool(self);self.height_tool=ChangeColumnHeightTool(self);self.move_tool=MoveWholeStructureTool(self,"pilar");self.curve_tool=ColumnCurveTool(self);self.incline_tool=ColumnInclineTool(self);self.station_z_tool=MoveColumnStationVerticalTool(self)
        self._segment_index=0;self.target=None;self._loading=False;self._queued=False;self._context_group=None;self._context_anchor=None;self._context_segment_index=None;self._context_station_index=None
        self._make_panel();self._make_action();self._make_context_palette();app.add_overlay(self.draw_overlay);app.viewport.installEventFilter(self)
        app.viewport.sceneVersionChanged.connect(self.schedule_refresh);self.schedule_refresh()

    def _spin(self,step=0.01,minv=MIN_DIM,maxv=MAX_DIM):
        w=QDoubleSpinBox();w.setLocale(ui_locale());w.setDecimals(4);w.setRange(minv,maxv);w.setSingleStep(step);w.setSuffix(" m");w.setKeyboardTracking(False);w.valueChanged.connect(self.values_changed);return w

    def _make_panel(self):
        self.panel=QWidget();lay=QVBoxLayout(self.panel);lay.addWidget(QLabel(t("Pilar")));form=QFormLayout();self.form=form;lay.addLayout(form)
        self.base_level=QComboBox();self.base_level.currentIndexChanged.connect(self.base_level_changed);form.addRow(t("Nível base"),self.base_level)
        self.base_offset=self._spin(0.05,-MAX_DIM,MAX_DIM);self.base_offset.setToolTip("Cota absoluta quando livre; offset quando vinculado a um nível.");form.addRow(t("Cota / offset base"),self.base_offset)
        self.top_level=QComboBox();self.top_level.currentIndexChanged.connect(self.top_level_changed);form.addRow(t("Nível topo"),self.top_level)
        self.top_offset=self._spin(0.05,-MAX_DIM,MAX_DIM);self.top_offset.setToolTip("Offset do topo em relação ao nível superior vinculado.");form.addRow(t("Offset topo"),self.top_offset)
        self.height=self._spin(0.10);form.addRow(t("Altura"),self.height)
        self.section_type=QComboBox();self.section_type.addItem(t("Simples"),"simple");self.section_type.addItem(t("Perfil complexo"),"complex");self.section_type.currentIndexChanged.connect(self.section_type_changed);form.addRow(t("Seção"),self.section_type)
        self.profile=QComboBox();self.profile.addItem(t("Retangular"),"rect");self.profile.addItem(t("Circular"),"circle");self.profile.currentIndexChanged.connect(self.values_changed);form.addRow(t("Forma"),self.profile)
        self.complex_profile=QComboBox();self.complex_profile.currentIndexChanged.connect(self.values_changed);self.complex_profile.setToolTip("Perfil 2D salvo no Editor de Perfil Complexo. A origem do perfil define o eixo do pilar.");form.addRow(t("Perfil complexo"),self.complex_profile)
        self.segment=QComboBox();self.segment.currentIndexChanged.connect(self.segment_changed);form.addRow(t("Segmento"),self.segment)
        self.width=self._spin();form.addRow(t("Largura início"),self.width);self.width_end=self._spin();form.addRow(t("Largura fim"),self.width_end)
        self.depth=self._spin();form.addRow(t("Profundidade início"),self.depth);self.depth_end=self._spin();form.addRow(t("Profundidade fim"),self.depth_end)
        self.diameter=self._spin();form.addRow(t("Diâmetro início"),self.diameter);self.diameter_end=self._spin();form.addRow(t("Diâmetro fim"),self.diameter_end)
        self.inclination=QDoubleSpinBox();self.inclination.setLocale(ui_locale());self.inclination.setDecimals(2);self.inclination.setRange(0,85);self.inclination.setSingleStep(1);self.inclination.setSuffix("°");self.inclination.setKeyboardTracking(False);self.inclination.valueChanged.connect(self.values_changed);form.addRow(t("Inclinação segmento"),self.inclination)
        self.inclination_azimuth=QDoubleSpinBox();self.inclination_azimuth.setLocale(ui_locale());self.inclination_azimuth.setDecimals(2);self.inclination_azimuth.setRange(-360,360);self.inclination_azimuth.setSingleStep(5);self.inclination_azimuth.setSuffix("°");self.inclination_azimuth.setKeyboardTracking(False);self.inclination_azimuth.valueChanged.connect(self.values_changed);form.addRow(t("Direção segmento"),self.inclination_azimuth)
        self.curvature=self._spin(0.05,-MAX_DIM,MAX_DIM);form.addRow(t("Flecha / curvatura"),self.curvature)
        self.rotation=QDoubleSpinBox();self.rotation.setLocale(ui_locale());self.rotation.setDecimals(2);self.rotation.setRange(-360,360);self.rotation.setSingleStep(5);self.rotation.setSuffix("°");self.rotation.setKeyboardTracking(False);self.rotation.valueChanged.connect(self.values_changed);form.addRow(t("Rotação"),self.rotation)
        self.material=QComboBox();self.material.currentIndexChanged.connect(self.values_changed);self.material.setToolTip("Material nomeado do IngeTrazo aplicado às faces do pilar. IfcMaterial ainda depende do exportador do programa.");form.addRow(t("Material"),self.material)
        anchor_box=QWidget();grid=QGridLayout(anchor_box);grid.setContentsMargins(0,0,0,0);grid.setSpacing(2);self.anchor_buttons={}
        matrix=[["tl","tc","tr"],["ml","mc","mr"],["bl","bc","br"]]
        for r,row in enumerate(matrix):
            for c,key in enumerate(row):
                b=QToolButton(anchor_box);b.setText("●");b.setCheckable(True);b.setAutoExclusive(True);b.setFixedSize(27,27);b.setToolTip("Ponto de inserção do pilar");b.clicked.connect(lambda _=False,k=key:self.anchor_changed(k));grid.addWidget(b,r,c);self.anchor_buttons[key]=b
        form.addRow(t("Eixo de referência"),anchor_box)
        self.hint=QLabel();self.hint.setWordWrap(True);lay.addWidget(self.hint);self.feedback=QLabel();self.feedback.setWordWrap(True);lay.addWidget(self.feedback);lay.addStretch()
        ver=QLabel(f"{t('Pilares paramétricos')} · v{__version__}");ver.setStyleSheet("color:#777;font-size:9pt;");lay.addWidget(ver)
        self.dock=getattr(self.app.window,"_arquitetura_parametrica_master_dock",None)
        if self.dock is None:
            self.dock=self.app.add_panel(t("Pilar"),self.panel,name="column");self.dock.hide()
        self.refresh_level_options();self.refresh_material_options();self.refresh_complex_profile_options();self._load_fields(self.defaults)

    def _make_action(self):
        self.action=QAction(column_icon(),t("Pilar paramétrico"),self.app.window);self.action.setCheckable(True);self.action.setToolTip(t("Pilar paramétrico vertical\nSeção simples retangular/circular; estrutura preparada para perfil complexo; níveis e offsets."))
        register_tool(self.app,self.tool,self.action,key=COLUMN_TOOL_KEY);register_tool(self.app,self.height_tool,key=COLUMN_HEIGHT_TOOL_KEY)
        register_tool(self.app,self.move_tool,key=COLUMN_MOVE_TOOL_KEY);register_tool(self.app,self.curve_tool,key=COLUMN_CURVE_TOOL_KEY);register_tool(self.app,self.incline_tool,key=COLUMN_INCLINE_TOOL_KEY);register_tool(self.app,self.station_z_tool,key=COLUMN_STATION_Z_TOOL_KEY);self.action.triggered.connect(self.start_drawing)
        if self.wall_controller is not None and hasattr(self.wall_controller,"toolbar"):
            self.wall_controller.toolbar.addAction(self.action)
            if hasattr(self.wall_controller,"fit_toolbar"): self.wall_controller.fit_toolbar()
            m=getattr(self.wall_controller,"arch_menu",None)
            if m is not None:m.addAction(self.action)
        else:
            m=self.app.add_menu(t("Ferramentas arquitetônicas"))
            if m is not None:m.addAction(self.action)

    def _make_context_palette(self):
        self.context_palette=RadialPalette(self.app.window,popup=False,role="edit");row=self.context_palette.row
        def add(sym,tip,slot):
            b=QToolButton(self.context_palette);set_symbol_icon(b, sym);b.setToolTip(t(tip));b.setFixedSize(34,34);f=b.font();f.setPointSize(16);b.setFont(f);b.clicked.connect(slot);row.addWidget(b);return b
        self.context_move_btn=add("↔","Mover o pilar inteiro no plano horizontal.",self.begin_move_whole)
        self.context_insert_btn=add("＋","Inserir um vértice/estação neste ponto do eixo para criar novos segmentos.",self.begin_insert_station)
        self.context_station_z_btn=add("↕","Mover este vértice do pilar na vertical, alterando as alturas dos segmentos vizinhos.",self.begin_move_station_vertical)
        self.context_curve_btn=add("","Curvar ou endireitar somente o segmento selecionado do pilar.",self.begin_curve)
        # A vertical arc reads more naturally on a pillar than the horizontal
        # wall/beam glyph. Draw the same arc concept rotated 90 degrees.
        pm=QPixmap(26,26);pm.fill(Qt.transparent);qp=QPainter(pm);qp.setRenderHint(QPainter.Antialiasing);qp.setPen(QPen(QColor("#111111"),2.2));qp.drawArc(QRectF(5,3,16,20),90*16,180*16);qp.end();self.context_curve_btn.setIcon(QIcon(pm));self.context_curve_btn.setIconSize(QSize(24,24))
        self.context_incline_btn=add("∠","Alterar graficamente a inclinação do pilar.",self.begin_incline)
        self.context_palette.hide()
    def hide_context_palette(self):
        self.context_palette.hide();self._context_group=None;self._context_anchor=None;self._context_segment_index=None;self._context_station_index=None
    def show_context_palette(self,pos,group,anchor,segment_index=None,station_index=None):
        self._context_group=group;self._context_anchor=QVector3D(anchor);self._context_segment_index=segment_index;self._context_station_index=station_index
        self.context_insert_btn.setVisible(station_index is None)
        self.context_station_z_btn.setVisible(station_index is not None and station_index>0)
        self.context_palette.show_at(pos)
    def begin_move_whole(self):
        if self._context_group is None:return
        g,a=self._context_group,QVector3D(self._context_anchor);self.hide_context_palette();self.move_tool.prepare(g,a);activate_column_move(self.app);self.app.viewport.setFocus()
    def begin_curve(self):
        if self._context_group is None:return
        g=self._context_group;seg=self._context_segment_index;self.hide_context_palette();self.curve_tool.prepare(g,seg);activate_column_curve(self.app);self.app.viewport.setFocus()
    def begin_insert_station(self):
        if self._context_group is None:return
        g=self._context_group;anchor=QVector3D(self._context_anchor)
        try:
            vals=read_column(g);frac=nearest_path_fraction(g,anchor);vals=insert_station(vals,frac)
            self.app.viewport.history.execute(EditColumn(self.app.scene,g,vals))
            if self.app.viewport.history.last_error:raise ColumnError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed();self.message("Vértice inserido; o pilar agora possui mais um segmento.")
            sts=vals.get("stations",[]);self._segment_index=max(0,min(len(sts)-2,next((i for i,b in enumerate(sts[1:]) if frac<=b.get("t",1.0)+1e-7),len(sts)-2)))
        except ColumnError as exc:self.message(str(exc),error=True)
        self.hide_context_palette();self.schedule_refresh();self.app.viewport.setFocus()
    def begin_incline(self):
        if self._context_group is None:return
        g=self._context_group;seg=self._context_segment_index;self.hide_context_palette();self.incline_tool.prepare(g,seg);activate_column_incline(self.app);self.app.viewport.setFocus()
    def begin_move_station_vertical(self):
        if self._context_group is None or self._context_station_index is None:return
        g=self._context_group;i=int(self._context_station_index);anchor=QVector3D(self._context_anchor)
        try:n=len(read_column(g).get("stations",[]))
        except ColumnError:return
        self.hide_context_palette()
        if i>=max(1,n-1):
            self.height_tool.prepare(g,anchor);activate_column_height(self.app)
        else:
            self.station_z_tool.prepare(g,i,anchor);activate_column_station_z(self.app)
        self.app.viewport.setFocus()

    def refresh_material_options(self):
        current=self.material.currentData() if hasattr(self,"material") and self.material.count() else self.defaults.get("material_name")
        names=material_names(self.app.scene);key=tuple(names)
        if getattr(self,"_material_options_key",None)==key:return
        self.material.blockSignals(True);self.material.clear();self.material.addItem(t("Padrão"),None)
        for name in names:self.material.addItem(name,name)
        i=self.material.findData(current);self.material.setCurrentIndex(i if i>=0 else 0);self.material.blockSignals(False)
        self._material_options_key=key

    def refresh_complex_profile_options(self, preferred=None, embedded=None):
        cur = preferred if preferred is not None else (self.complex_profile.currentData() if self.complex_profile.count() else self.defaults.get("profile_ref"))
        profiles = sorted(load_profiles(), key=lambda p:(str(p.get("folder") or "").casefold(), str(p.get("name") or "").casefold()))
        blocked=self.complex_profile.blockSignals(True);self.complex_profile.clear();current_folder=None
        for prof in profiles:
            folder=str(prof.get("folder") or "Meus Perfis")
            if folder!=current_folder:
                if self.complex_profile.count():self.complex_profile.insertSeparator(self.complex_profile.count())
                self.complex_profile.addItem(f"— {folder} —",None)
                try:self.complex_profile.model().item(self.complex_profile.count()-1).setEnabled(False)
                except Exception:pass
                current_folder=folder
            self.complex_profile.addItem(prof.get("name") or t("Perfil"),prof.get("id"))
        ids=[self.complex_profile.itemData(i) for i in range(self.complex_profile.count())]
        if cur and cur not in ids and isinstance(embedded,dict):
            self.complex_profile.addItem(f"{embedded.get('name') or t('Perfil')}  ·  {t('incorporado')}",cur)
        if not any(self.complex_profile.itemData(i) is not None for i in range(self.complex_profile.count())):
            self.complex_profile.addItem(t("Nenhum perfil complexo disponível"),None)
        idx=self.complex_profile.findData(cur)
        if idx<0:
            idx=next((i for i in range(self.complex_profile.count()) if self.complex_profile.itemData(i) is not None),0)
        self.complex_profile.setCurrentIndex(idx)
        self.complex_profile.setEnabled(any(self.complex_profile.itemData(i) is not None for i in range(self.complex_profile.count())))
        self.complex_profile.blockSignals(blocked)

    def refresh_level_options(self):
        bc=self.base_level.currentData() if self.base_level.count() else None;tc=self.top_level.currentData() if self.top_level.count() else None
        for combo,free in ((self.base_level,t("Cota livre")),(self.top_level,t("Livre (altura)"))):
            combo.blockSignals(True);combo.clear();combo.addItem(free,None)
            for lv in available_levels(self.app):combo.addItem(f"{lv['name']}  ({lv['z']:+.2f} m)",lv['name'])
            combo.blockSignals(False)
        bi=self.base_level.findData(bc);self.base_level.setCurrentIndex(bi if bi>=0 else 0);ti=self.top_level.findData(tc);self.top_level.setCurrentIndex(ti if ti>=0 else 0)

    def resolved_defaults(self):
        p=dict(self.defaults)
        if p.get("base_level"):
            lv=level_by_name(self.app,p["base_level"])
            if lv is not None:p["base_z"]=float(lv["z"])+float(p.get("base_offset",0.0))
        if p.get("top_mode")=="level" and p.get("top_level"):
            lv=level_by_name(self.app,p["top_level"])
            if lv is not None:
                top=float(lv["z"])+float(p.get("top_offset",0.0));p["height"]=max(MIN_DIM,top-float(p["base_z"]))
        return p
    def current_base_z(self):return float(self.resolved_defaults()["base_z"])

    def _ui_stations(self,p):
        raw=p.get("stations") if isinstance(p,dict) else None
        if isinstance(raw,(list,tuple)) and len(raw)>=2:
            return [dict(x) for x in raw]
        w=float(p.get("width",0.30));d=float(p.get("depth",0.30));dia=float(p.get("diameter",0.30))
        return [{"t":0.0,"width":w,"depth":d,"diameter":dia},{"t":1.0,"width":w,"depth":d,"diameter":dia}]

    def _load_segment_fields(self,p):
        stations=self._ui_stations(p);count=max(1,len(stations)-1);self._segment_index=max(0,min(self._segment_index,count-1))
        self.segment.blockSignals(True);self.segment.clear()
        for i in range(count):
            a,b=stations[i],stations[i+1];self.segment.addItem(t(f"Segmento {i+1}  ({a.get('t',0)*100:.0f}–{b.get('t',1)*100:.0f}%)"),i)
        self.segment.setCurrentIndex(self._segment_index);self.segment.blockSignals(False)
        a,b=stations[self._segment_index],stations[self._segment_index+1]
        self.width.setValue(float(a.get("width",p.get("width",.3))));self.width_end.setValue(float(b.get("width",p.get("width",.3))) )
        self.depth.setValue(float(a.get("depth",p.get("depth",.3))));self.depth_end.setValue(float(b.get("depth",p.get("depth",.3))) )
        self.diameter.setValue(float(a.get("diameter",p.get("diameter",.3))));self.diameter_end.setValue(float(b.get("diameter",p.get("diameter",.3))) )
        self.inclination.setValue(float(a.get("inclination",p.get("inclination",0.0))))
        self.inclination_azimuth.setValue(float(a.get("inclination_azimuth",p.get("inclination_azimuth",0.0))))
        self.curvature.setValue(float(a.get("curvature", p.get("curvature",0.0) if self._segment_index == 0 else 0.0)))

    def _load_fields(self,p):
        self._loading=True
        try:
            self.defaults.update(p);name=p.get("base_level");i=self.base_level.findData(name);self.base_level.setCurrentIndex(i if i>=0 else 0);self.base_offset.setValue(p.get("base_offset",0.0) if name else p.get("base_z",0.0))
            tname=p.get("top_level") if p.get("top_mode")=="level" else None;i=self.top_level.findData(tname);self.top_level.setCurrentIndex(i if i>=0 else 0);self.top_offset.setValue(p.get("top_offset",0.0));self.height.setValue(p["height"])
            self.refresh_complex_profile_options(p.get("profile_ref"),p.get("profile_data"));self.section_type.setCurrentIndex(max(0,self.section_type.findData(p.get("section_type","simple"))));self.profile.setCurrentIndex(max(0,self.profile.findData(p["profile"])));ci=self.complex_profile.findData(p.get("profile_ref"));self.complex_profile.setCurrentIndex(ci if ci>=0 else 0);self._load_segment_fields(p);self.rotation.setValue(p["rotation"]);mi=self.material.findData(p.get("material_name"));self.material.setCurrentIndex(mi if mi>=0 else 0)
            for key,b in self.anchor_buttons.items():b.setChecked(key==p.get("anchor","mc"))
            linked=p.get("top_mode")=="level" and p.get("top_level");self.height.setEnabled(not linked);self.top_offset.setEnabled(bool(linked));self._update_section_widgets(p)
        finally:self._loading=False

    def _set_form_field_visible(self, widget, visible):
        visible=bool(visible);widget.setVisible(visible)
        try:
            label=self.form.labelForField(widget)
            if label is not None:label.setVisible(visible)
        except Exception:pass

    def _update_section_widgets(self,p=None):
        p=p or self.defaults
        simple=p.get("section_type","simple")=="simple";rect=p.get("profile")=="rect";circ=p.get("profile")=="circle"
        self._set_form_field_visible(self.profile,simple)
        self._set_form_field_visible(self.complex_profile,not simple)
        self.segment.setVisible(True)
        for w in (self.width,self.width_end,self.depth,self.depth_end):self._set_form_field_visible(w,simple and rect)
        for w in (self.diameter,self.diameter_end):self._set_form_field_visible(w,simple and circ)

    def segment_changed(self,*_):
        if self._loading:
            return
        self._segment_index=max(0,int(self.segment.currentData() or 0))
        try:
            src=read_column(self.target) if self.target is not None else self.defaults
        except ColumnError:
            return
        self._loading=True
        try:
            self._load_segment_fields(src)
            self._update_section_widgets(src)
        finally:
            self._loading=False

    def section_type_changed(self,*_):
        if self._loading:return
        kind=self.section_type.currentData() or "simple";self.defaults["section_type"]=kind
        if kind=="complex":
            self.refresh_complex_profile_options(self.defaults.get("profile_ref"),self.defaults.get("profile_data"))
            ref=self.complex_profile.currentData();self.defaults["profile_ref"]=ref;self.defaults["profile_data"]=profile_by_id(ref) if ref else None
            if not ref:self.message("Crie ou escolha um Perfil Complexo antes de usar esta seção.",True);self._update_section_widgets(self.defaults);return
        else:
            self.defaults["profile_ref"]=None;self.defaults["profile_data"]=None
        self.message("");self._update_section_widgets(self.defaults);self._apply()

    def base_level_changed(self,*_):
        if self._loading:return
        old=self.resolved_defaults();old_base=float(old["base_z"]);name=self.base_level.currentData();self.defaults["base_level"]=name
        if name:
            lv=level_by_name(self.app,name);off=old_base-float(lv["z"]) if lv else 0.0;self.defaults["base_offset"]=off;self.base_offset.setValue(off)
        else:self.defaults["base_offset"]=0.0;self.defaults["base_z"]=old_base;self.base_offset.setValue(old_base)
        self._apply()
    def top_level_changed(self,*_):
        if self._loading:return
        old=self.resolved_defaults();old_top=float(old["base_z"])+float(old["height"]);name=self.top_level.currentData()
        if name:
            lv=level_by_name(self.app,name);self.defaults["top_mode"]="level";self.defaults["top_level"]=name;self.defaults["top_offset"]=old_top-float(lv["z"]) if lv else 0.0
        else:self.defaults["top_mode"]="height";self.defaults["top_level"]=None;self.defaults["top_offset"]=0.0;self.defaults["height"]=old["height"]
        self._load_fields(self.resolved_defaults());self._apply()
    def anchor_changed(self,key):
        if self._loading:return
        self.defaults["anchor"]=key;self._apply()
    def values_changed(self,*_):
        if self._loading:return
        stations=self._ui_stations(self.defaults);i=max(0,min(self._segment_index,len(stations)-2));a,b=stations[i],stations[i+1]
        a.update(width=float(self.width.value()),depth=float(self.depth.value()),diameter=float(self.diameter.value()),inclination=float(self.inclination.value()),inclination_azimuth=float(self.inclination_azimuth.value()),curvature=float(self.curvature.value()))
        b.update(width=float(self.width_end.value()),depth=float(self.depth_end.value()),diameter=float(self.diameter_end.value()))
        ref=self.complex_profile.currentData() if (self.section_type.currentData() or "simple")=="complex" else None
        embedded=self.defaults.get("profile_data") if ref and self.defaults.get("profile_ref")==ref else profile_by_id(ref)
        self.defaults.update(section_type=self.section_type.currentData() or "simple",profile_ref=ref,profile_data=embedded,profile=self.profile.currentData(),stations=stations,width=float(stations[0]["width"]),depth=float(stations[0]["depth"]),diameter=float(stations[0]["diameter"]),inclination=float(stations[0].get("inclination",0.0)),inclination_azimuth=float(stations[0].get("inclination_azimuth",0.0)),curvature=float(stations[0].get("curvature",0.0)),rotation=float(self.rotation.value()),material_name=self.material.currentData())
        if self.defaults.get("base_level"):self.defaults["base_offset"]=float(self.base_offset.value())
        else:self.defaults["base_z"]=float(self.base_offset.value())
        if self.defaults.get("top_mode")=="level":self.defaults["top_offset"]=float(self.top_offset.value())
        else:self.defaults["height"]=float(self.height.value())
        self._update_section_widgets(self.defaults)
        if self.defaults.get("section_type")=="complex" and not self.defaults.get("profile_ref"):
            self.message("Escolha um Perfil Complexo antes de aplicar.",True);return
        self._apply()

    def _apply(self):
        vals=self.resolved_defaults();self.defaults.update(vals)
        if self.target is None or self._loading:return
        try:
            self.app.viewport.history.execute(EditColumn(self.app.scene,self.target,vals))
            if self.app.viewport.history.last_error:raise ColumnError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed()
        except ColumnError as exc:self.message(str(exc),error=True)

    def _sync_levels(self):
        changed=0
        for g in list(self.app.scene.groups):
            rec=column_record(g)
            if rec is None:continue
            try:
                old=read_column(g);vals=dict(old);dirty=False
                if rec.get("base_level"):
                    lv=level_by_name(self.app,rec["base_level"])
                    if lv is not None:
                        z=float(lv["z"])+float(rec.get("base_offset",0.0));dirty|=abs(z-old["base_z"])>1e-7;vals["base_z"]=z
                if rec.get("top_mode")=="level" and rec.get("top_level"):
                    lv=level_by_name(self.app,rec["top_level"])
                    if lv is not None:
                        h=float(lv["z"])+float(rec.get("top_offset",0.0))-float(vals["base_z"])
                        if h>=MIN_DIM:dirty|=abs(h-old["height"])>1e-7;vals["height"]=h
                if dirty:EditColumn(self.app.scene,g,vals).do(self.app.scene);changed+=1
            except ColumnError:continue
        return changed

    def schedule_refresh(self,*_):
        if self._queued:return
        self._queued=True;QTimer.singleShot(0,self.refresh)
    def refresh(self):
        self._queued=False
        try:self._sync_levels()
        except Exception:log.exception("column level sync failed")
        self.refresh_level_options();self.refresh_material_options();self.refresh_complex_profile_options();cols=selected_columns(self.app.scene);self.target=cols[0] if len(cols)==1 else None
        if self.target is not None:
            try:self._load_fields(read_column(self.target));self.hint.setText(t("Hotspot superior: alterar altura. Clique no eixo para mover, inserir vértice, inclinar ou curvar. Cada segmento pode ter seção inicial/final própria."));self.app.show_panel(self.dock)
            except ColumnError as exc:self.message(str(exc),error=True)
        elif self.app.viewport.active_tool is self.tool:self._load_fields(self.resolved_defaults());self.hint.setText("Clique no plano horizontal para inserir o pilar.");self.app.show_panel(self.dock)
        self.app.viewport.update()

    def start_drawing(self,*_):
        try:
            root_edit_allowed(self.app.scene)
            if self.defaults.get("section_type")=="complex" and not self.defaults.get("profile_ref"):raise ColumnError("Escolha um Perfil Complexo antes de inserir o pilar.")
            if self.app.workspace() is not None:raise ColumnError("Volte ao modelo para inserir pilares.")
        except Exception as exc:self.action.setChecked(False);self.app.viewport.flash_status(t(str(exc)),6000);return
        self.app.scene.clear_selection();activate_column(self.app);self.schedule_refresh();self.message("Clique no ponto de inserção do pilar.");self.app.viewport.setFocus()
    def stop_drawing(self):activate_select(self.app);self.action.setChecked(False);self.schedule_refresh()
    def return_to_select(self):activate_select(self.app);self.schedule_refresh();self.app.viewport.setFocus()
    def message(self,text,error=False):
        shown=t(text);self.feedback.setText(shown);self.feedback.setStyleSheet("color:#b00020;" if error else "")
        if text:self.app.viewport.flash_status(shown,8000 if error else 15000)

    @staticmethod
    def _seg_distance(px,py,a,b):
        ax,ay=a;bx,by=b;dx,dy=bx-ax,by-ay;den=dx*dx+dy*dy
        if den<=1e-9:return math.hypot(px-ax,py-ay)
        u=max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/den));x=ax+u*dx;y=ay+u*dy
        return math.hypot(px-x,py-y)
    def eventFilter(self,obj,event):
        if obj is self.app.viewport and event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
            if self.context_palette.isVisible():self.hide_context_palette()
            if event.modifiers()==Qt.NoModifier:
                vp=self.app.viewport;cols=selected_columns(self.app.scene);select_tool=host_tool(self.app, "select")
                if vp.active_tool is select_tool and len(cols)==1:
                    try:top=top_world(cols[0]);path=reference_path_world(cols[0])
                    except ColumnError:return super().eventFilter(obj,event)
                    px,py=event.position().x(),event.position().y();threshold=max(8.0,float(getattr(vp,"snap_threshold_px",10.0)))
                    # Every semantic station above the base is the TOP control
                    # of the segment immediately below it.  This makes pillar
                    # inclination behave like moving the upper endpoint of a
                    # segment horizontally while its lower endpoint stays fixed.
                    # The final top station uses the same radial palette; its ↕
                    # action delegates to the ordinary column-height tool.
                    try:stations=station_points_world(cols[0]);vals=read_column(cols[0])
                    except ColumnError:stations=[];vals=None
                    station_hit=None
                    for si,wp in enumerate(stations[1:],1):
                        sp=vp._world_to_pixel(wp)
                        if sp is None:continue
                        d=math.hypot(px-sp[0],py-sp[1])
                        if d<=threshold and (station_hit is None or d<station_hit[0]):station_hit=(d,si,wp)
                    if station_hit is not None:
                        gp=vp.mapToGlobal(QPoint(int(px),int(py)));si=station_hit[1]
                        self.show_context_palette(gp,cols[0],station_hit[2],segment_index=max(0,si-1),station_index=si);return True
                    pixels=[vp._world_to_pixel(q) for q in path]
                    best=None
                    for idx,(a,b) in enumerate(zip(pixels,pixels[1:])):
                        if a is None or b is None:continue
                        d=self._seg_distance(px,py,a,b)
                        if d<=threshold and (best is None or d<best[0]):
                            wa,wb=path[idx],path[idx+1];ax,ay=a;bx,by=b;den=(bx-ax)**2+(by-ay)**2;u=0.0 if den<=1e-9 else max(0.0,min(1.0,((px-ax)*(bx-ax)+(py-ay)*(by-ay))/den));best=(d,wa+(wb-wa)*u)
                    if best is not None:
                        anchor=best[1];frac=nearest_path_fraction(cols[0],anchor);seg=segment_index_at_fraction(vals,frac) if vals is not None else 0
                        gp=vp.mapToGlobal(QPoint(int(px),int(py)));self.show_context_palette(gp,cols[0],anchor,segment_index=seg);return True
        return super().eventFilter(obj,event)

    def draw_overlay(self,viewport,painter):
        cols=selected_columns(self.app.scene)
        if not cols:return
        painter.setPen(QPen(QColor("#1f8eea"),1.8,Qt.DashLine));painter.setBrush(QColor("white"))
        for g in cols:
            try:path=reference_path_world(g);b=insertion_world(g);t=top_world(g)
            except ColumnError:continue
            pix=[viewport._world_to_pixel(q) for q in path]
            for x,y in zip(pix,pix[1:]):
                if x is not None and y is not None:painter.drawLine(QPointF(x[0],x[1]),QPointF(y[0],y[1]))
            try:stations=station_points_world(g)
            except ColumnError:stations=[b,t]
            for idx,wp in enumerate(stations):
                q=viewport._world_to_pixel(wp)
                if q is not None:
                    r=4 if idx in (0,len(stations)-1) else 3
                    painter.drawEllipse(QRectF(q[0]-r,q[1]-r,2*r,2*r))
