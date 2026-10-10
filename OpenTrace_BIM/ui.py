# SPDX-License-Identifier: GPL-3.0-or-later
"""Contextual architecture palette with straight and curved wall tools."""
from __future__ import annotations

import logging
import copy
import uuid

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QVector3D
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QMenu, QInputDialog,
    QToolBar, QToolButton, QVBoxLayout, QWidget, QSizeGrip,
)

from . import __version__
from .commands import EditWall, MeetWalls, root_edit_allowed
from .host import (ARC_TOOL_KEY, CURVED_WALL_TOOL_KEY, HEIGHT_TOOL_KEY, WALL_TOTAL_HEIGHT_TOOL_KEY, MOVE_XY_TOOL_KEY,
                   MOVE_Z_TOOL_KEY, MOVE_VERTEX_CONTINUE_TOOL_KEY, MOVE_VERTEX_FREE_TOOL_KEY,
                   WALL_STATION_Z_TOOL_KEY, WALL_LEAN_TOOL_KEY, WALL_OPENING_TOOL_KEY, WALL_POLYGON_TOOL_KEY,
                   VERTEX_TOOL_KEY, activate_arc, activate_curved_wall, activate_height, activate_wall_total_height,
                   activate_move_vertex_continue, activate_move_vertex_free, activate_move_xy,
                   activate_move_z, activate_wall_station_z, activate_wall_lean, activate_wall_opening, activate_wall_polygon,
                   activate_select, activate_vertex_insert, activate_wall, register_tool, host_tool)
from .levels import available_levels, level_by_name, sync_bound_wall_tops
from .junctions import sync_wall_junctions
from .layer_intersections import intersection_group as wall_intersection_group
from .palette import RadialPalette
from .layer_ui import LayerEditor
from .materials import material_names

from .model import (DEFAULTS, MAX_DIM, MIN_DIM, WallError, arc_center_world, path_world,
                    base_path_world, top_path_world, base_reference_vertices_world,
                    top_reference_vertices_world, read_wall, reference_vertices_world, validate, wall_path,
                    wall_path_kind, wall_record, nearest_path_distance_world)
from .wall_tool import CurvedWallTool, WallTool
from .snaprefs import snap_to_wall_references, snap_to_wall_top_references, snap_to_structure_reference_endpoints
from .path_edit import (ArcWallTool, ChangeWallHeightTool, ConstrainedMoveWallTool,
                        InsertVertexTool, MoveWallVertexTool, MoveWallStationZTool, LeanWallTopTool, ChangeWholeWallHeightTool)
from .wall_opening_tool import WallOpeningTool
from .wall_polygon_tool import WallPolygonTool
from .opening_controller import all_opening_wires, hit_test
from .door_window_commands import EditHostedFill, DeleteHostedOpening, _fill_record
from .door_window_core import edit_from_hotspot, normalize_fill
from .widgets import FlexibleDoubleSpinBox as QDoubleSpinBox
from .i18n import t, ui_locale
from .icons import icon as pa_icon, set_symbol_icon
from .bim import ensure_ifc_identity, ifc_identity_data, set_ifc_metadata
from .ifc_catalog import predefined_types


log = logging.getLogger("ingetrazo.plugins.arquitetura_parametrica")


def wall_icon():
    return pa_icon("wall")


def composite_wall_icon():
    return pa_icon("wall_composite")


def curved_wall_icon():
    return pa_icon("wall_curve")




def _freeze_junction_value(value):
    """Hashable, deterministic form of wall inputs relevant to junctions."""
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze_junction_value(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_junction_value(v) for v in value)
    if isinstance(value, float):
        return round(value, 9)
    return value


def _wall_transform_signature(group):
    xf = getattr(group, "xform", None)
    if xf is None:
        return None
    try:
        pts = [xf.map(QVector3D(0, 0, 0)), xf.map(QVector3D(1, 0, 0)),
               xf.map(QVector3D(0, 1, 0)), xf.map(QVector3D(0, 0, 1))]
        return tuple(round(float(v), 9) for p in pts for v in (p.x(), p.y(), p.z()))
    except Exception:
        return repr(xf)


def wall_junction_input_key(scene):
    """Return a key that changes only when a wall can affect a junction.

    The previous 0.11 build keyed the resolver to ``scene.version``. That made
    an expensive curved-wall junction pass run after *any* scene edit (slab,
    column, beam, selection-derived changes, etc.). Once an arc existed this
    was visible as intermittent stalls. Derived ``caps`` are intentionally
    excluded so the resolver's own cleanup does not invalidate its cache.
    """
    items = []
    for group in list(getattr(scene, "groups", ())):
        rec = wall_record(group)
        if rec is None:
            continue
        raw = {k: v for k, v in rec.items() if k != "caps"}
        try:
            ig = int(wall_intersection_group(group))
        except Exception:
            ig = 1
        items.append((id(group), _freeze_junction_value(raw),
                      _wall_transform_signature(group), ig))
    return tuple(items)


def selected_walls(scene):
    if getattr(scene, "edit_group", None) is not None:
        return []
    found = []
    for item in scene.selection:
        parent = getattr(item, "owner", None) or item
        if parent in scene.groups and wall_record(parent) is not None and parent not in found:
            found.append(parent)
            continue
        # Selecting the independent leaf/frame also exposes its host opening
        # controls. The scene selection itself still belongs to the fill.
        rec=_fill_record(parent)
        if rec:
            wall=next((w for w in scene.groups
                       if getattr(w,"uid",None)==rec.get("host_id")
                       and wall_record(w) is not None),None)
            if wall is not None and wall not in found:
                found.append(wall)
    return found


class WallController(QObject):
    def __init__(self, app):
        super().__init__(app.window)
        self.app = app
        self.defaults = copy.deepcopy(DEFAULTS)
        self.default_wall_predefined = "SOLIDWALL"
        self.default_wall_status = None
        self.tool = WallTool(self)
        self.curve_create_tool = CurvedWallTool(self)
        self.vertex_tool = InsertVertexTool(self)
        self.move_xy_tool = ConstrainedMoveWallTool(self, "xy")
        self.move_z_tool = ConstrainedMoveWallTool(self, "z")
        self.height_tool = ChangeWallHeightTool(self)
        self.total_height_tool = ChangeWholeWallHeightTool(self)
        self.station_z_tool = MoveWallStationZTool(self)
        self.lean_tool = LeanWallTopTool(self)
        self.opening_tool = WallOpeningTool(self)
        self.polygon_tool = WallPolygonTool(self)
        self.arc_tool = ArcWallTool(self)
        self.move_vertex_free_tool = MoveWallVertexTool(self, "free")
        self.move_vertex_continue_tool = MoveWallVertexTool(self, "continue")
        self.target = None
        self.target_scene = None
        self._document = app.scene
        self._loading = False
        self._queued = False
        self._state_key = None
        self._loaded_key = None
        self._context = None
        self._junction_key = None
        self._path_palette_wall = None
        self._path_palette_anchor = None
        self._path_palette_kind = None
        self._active_opening_id = None
        self._opening_wire_key = None
        self._opening_wire_data = []
        self._make_panel()
        self._make_actions()
        self._make_path_palette()
        self._make_straight_mode_palette()
        self._make_curve_mode_palette()
        app.add_overlay(self.draw_reference_overlay)
        app.add_snap_provider(self._snap_provider)
        app.viewport.installEventFilter(self)
        # Selection/model changes emit sceneVersionChanged. Tool activation and
        # deactivation schedule their own refreshes; do not bind the heavy panel
        # refresh to measurementChanged because that signal also fires during
        # live cursor measurement and would rebuild all architecture panels on
        # every mouse move.
        app.viewport.sceneVersionChanged.connect(self.schedule_refresh)
        self.schedule_refresh()

    def _snap_provider(self, viewport, snap, px, py):
        # Height editing gets a dedicated architectural reference: the whole
        # top path of another wall can be acquired, not only its mesh corners.
        # Native named snaps still outrank extension providers in IngeTrazo.
        if viewport.active_tool in (self.height_tool, self.total_height_tool):
            return snap_to_wall_top_references(self.app, viewport, snap, px, py)
        wall = snap_to_wall_references(self.app, viewport, snap, px, py)
        if wall is not None:
            return wall
        return snap_to_structure_reference_endpoints(self.app, viewport, snap, px, py)

    def _make_panel(self):
        self.panel = QWidget()
        layout = QVBoxLayout(self.panel)
        self.heading = QLabel(t("Parede"))
        layout.addWidget(self.heading)
        self.form_widget = QWidget()
        form = QFormLayout(self.form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.fields = {}
        self.base_level = QComboBox()
        self.base_level.setToolTip(
            "Usa os níveis criados pela extensão Níveis. "
            "Cota livre mantém uma cota absoluta independente.")
        self.base_level.currentIndexChanged.connect(self.base_level_changed)
        form.addRow(t("Nível base"), self.base_level)

        self.top_level = QComboBox()
        self.top_level.setToolTip(
            "Livre mantém uma altura independente. Ao escolher um nível, o topo "
            "da parede acompanha esse nível mais o offset do topo.")
        self.top_level.currentIndexChanged.connect(self.top_level_changed)
        form.addRow(t("Nível topo"), self.top_level)

        self.top_offset = QDoubleSpinBox()
        self.top_offset.setLocale(ui_locale())
        self.top_offset.setDecimals(4)
        self.top_offset.setRange(-MAX_DIM, MAX_DIM)
        self.top_offset.setSingleStep(0.05)
        self.top_offset.setSuffix(" m")
        self.top_offset.setKeyboardTracking(False)
        self.top_offset.setToolTip(
            "Deslocamento do topo em relação ao nível vinculado. "
            "Ex.: -0,15 m deixa a parede 15 cm abaixo do nível.")
        self.top_offset.valueChanged.connect(self.top_binding_changed)
        form.addRow(t("Offset topo"), self.top_offset)

        self.refresh_level_options()
        for key, title in (("length", t("Comprimento")), ("thickness", t("Espessura")),
                           ("height", t("Altura")), ("base", t("Cota de base"))):
            field = QDoubleSpinBox()
            field.setLocale(ui_locale())
            field.setDecimals(4)
            field.setRange(-MAX_DIM if key == "base" else MIN_DIM, MAX_DIM)
            field.setSingleStep(0.01 if key == "thickness" else 0.10)
            field.setSuffix(" m")
            field.setKeyboardTracking(False)
            field.valueChanged.connect(self.defaults_changed)
            self.fields[key] = field
            form.addRow(title, field)
        self.alignment = QComboBox()
        for title, key in ((t("Externo"), "left"), (t("Meio"), "center"), (t("Interno"), "right")):
            self.alignment.addItem(title, key)
        self.alignment.setToolTip("Posição da parede em relação à linha de referência. Externo é o padrão para novas paredes.")
        self.alignment.currentIndexChanged.connect(self.defaults_changed)
        form.addRow(t("Alinhamento"), self.alignment)
        self.material = QComboBox()
        self.material.setToolTip("Material da parede simples. Em paredes compostas cada camada pode ter seu próprio material.")
        self.material.currentIndexChanged.connect(self.defaults_changed)
        form.addRow(t("Material"), self.material)
        self.structure=QComboBox();self.structure.addItem(t("Simples"),"simple");self.structure.addItem(t("Composta / camadas"),"composite");self.structure.currentIndexChanged.connect(self.structure_changed);form.addRow(t("Estrutura"),self.structure)
        self.ifc_predefined=QComboBox()
        for code in predefined_types("IfcWall") or ["NOTDEFINED"]: self.ifc_predefined.addItem(code,code)
        idx=self.ifc_predefined.findData("SOLIDWALL"); self.ifc_predefined.setCurrentIndex(idx if idx>=0 else 0)
        self.ifc_predefined.setToolTip("Tipo semântico IFC da parede. SOLIDWALL = parede contínua/por camadas; ELEMENTEDWALL = parede montada por elementos, painéis ou montantes.")
        self.ifc_predefined.currentIndexChanged.connect(self._bim_defaults_changed)
        form.addRow("Tipo IFC",self.ifc_predefined)
        self.phase_status=QComboBox();self.phase_status.addItem("Não definido",None)
        for code,label in (("NEW","Novo"),("EXISTING","Existente"),("DEMOLISH","A demolir"),("TEMPORARY","Temporário")): self.phase_status.addItem(label,code)
        self.phase_status.setToolTip("Estado de construção IFC. Depois poderá dirigir filtros gráficos e combinações de documentação.")
        self.phase_status.currentIndexChanged.connect(self._bim_defaults_changed)
        form.addRow("Fase / estado",self.phase_status)
        self.refresh_material_options()
        layout.addWidget(self.form_widget)
        self.layer_editor=LayerEditor(self.panel,before_label="Exterior",after_label="Interior");self.layer_editor.changed.connect(self.layers_changed);layout.addWidget(self.layer_editor);self.layer_editor.hide()

        self.opening_widget=QWidget(self.panel);oform=QFormLayout(self.opening_widget);oform.setContentsMargins(0,0,0,0);self.opening_fields={}
        self.opening_selector=QComboBox(self.opening_widget)
        self.opening_selector.setToolTip("Selecione qualquer abertura desta parede.")
        self.opening_selector.currentIndexChanged.connect(self._select_opening_from_list)
        oform.addRow("Vão selecionado",self.opening_selector)
        opening_rows=(("position",t("Posição ao longo da parede"),0.10),("width",t("Largura Livre no menor Vão"),0.10),("sill",t("Peitoril"),0.10),("height",t("Altura da abertura"),0.10))
        for key,label,step in opening_rows:
            f=QDoubleSpinBox();f.setLocale(ui_locale());f.setDecimals(4);f.setRange(0.0,MAX_DIM);f.setSingleStep(step);f.setSuffix(" m");f.setKeyboardTracking(False);f.valueChanged.connect(self.opening_changed);self.opening_fields[key]=f;oform.addRow(label,f)
        self.opening_fields["width"].setToolTip(t("Largura livre mínima da abertura. Em paredes curvas, as faces interna e externa podem ter larguras projetadas diferentes; o valor informado é garantido no menor vão, para representar a passagem realmente disponível."))
        self.opening_fields["position"].setToolTip(t("Distância da abertura medida ao longo da linha de referência da parede."))
        self.opening_fill=QComboBox(self.opening_widget);self.opening_fill.addItem("Somente abertura",None);self.opening_fill.addItem("Porta IFC","IfcDoor");self.opening_fill.addItem("Janela IFC","IfcWindow")
        self.opening_fill.setToolTip("Opcional: preenche a abertura semanticamente com IfcDoor ou IfcWindow e exporta IfcRelFillsElement.")
        self.opening_fill.currentIndexChanged.connect(self.opening_changed);oform.addRow("Preenchimento IFC",self.opening_fill)
        self.polygon_label=QLabel("Abertura livre: edição por vértices",self.opening_widget)
        oform.addRow(self.polygon_label)
        self.polygon_tools=QWidget(self.opening_widget)
        polygon_row=QHBoxLayout(self.polygon_tools)
        polygon_row.setContentsMargins(0,0,0,0)
        polygon_row.setSpacing(4)
        for symbol,description,operation in (
            ("✥","Mover vértice","move_vertex"),
            ("＋","Inserir vértice","insert_vertex"),
            ("↔","Mover aresta","move_edge"),
            ("−","Excluir vértice","delete_vertex"),
        ):
            btn=QToolButton(self.polygon_tools)
            btn.setText(symbol)
            btn.setToolTip(description + " da abertura livre")
            btn.setFixedSize(32,32)
            btn.clicked.connect(lambda _checked=False, mode=operation: self.edit_wall_polygon(mode))
            polygon_row.addWidget(btn)
        oform.addRow(self.polygon_tools)
        self.delete_opening_btn=QToolButton(self.opening_widget);set_symbol_icon(self.delete_opening_btn,"⊘",20);self.delete_opening_btn.setToolTip(t("Excluir esta abertura da parede."));self.delete_opening_btn.clicked.connect(self.delete_wall_opening);oform.addRow(t("Abertura hospedada"),self.delete_opening_btn)
        layout.addWidget(self.opening_widget);self.opening_widget.hide()

        self.pair_widget = QWidget()
        pair_row = QHBoxLayout(self.pair_widget)
        pair_row.setContentsMargins(0, 0, 0, 0)
        self.meet_btn = QToolButton(self.pair_widget)
        set_symbol_icon(self.meet_btn,"⋈",22)
        self.meet_btn.setToolTip(
            "Encontrar as duas paredes: prolonga ou apara as pontas mais próximas "
            "até a interseção das linhas de referência.")
        self.meet_btn.setFixedSize(38, 38)
        meet_font = self.meet_btn.font(); meet_font.setPointSize(18); self.meet_btn.setFont(meet_font)
        self.meet_btn.clicked.connect(self.meet_selected_walls)
        pair_row.addWidget(self.meet_btn)
        pair_row.addStretch()
        self.pair_widget.hide()
        layout.addWidget(self.pair_widget)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.feedback)
        layout.addStretch()
        self.version_label = QLabel(f"{t('Paredes paramétricas')} · v{__version__}")
        self.version_label.setStyleSheet("color: #777; font-size: 9pt;")
        self.version_label.setToolTip(t("Versão instalada deste plugin."))
        layout.addWidget(self.version_label)
        self.dock = getattr(self.app.window, "_arquitetura_parametrica_master_dock", None)
        if self.dock is None:
            self.dock = self.app.add_panel(t("Arquitetura"), self.panel)
            self.dock.hide()

    def _make_actions(self):
        self.action = QAction(wall_icon(), t("Parede paramétrica"), self.app.window)
        self.action.setCheckable(True)
        self.action.setToolTip(t("Parede paramétrica\nDois pontos ou início, direção e comprimento."))
        self.action.setStatusTip("Criar parede reta com espessura, altura e alinhamento editáveis.")
        register_tool(self.app, self.tool, self.action)
        self.curve_action = QAction(curved_wall_icon(), t("Parede curva"), self.app.window)
        self.curve_action.setCheckable(True)
        self.curve_action.setToolTip(t("Parede curva\nArco padrão, pelo centro ou por 3 pontos."))
        self.curve_action.setStatusTip("Criar parede curva paramétrica com três métodos de arco.")
        register_tool(self.app, self.curve_create_tool, self.curve_action, key=CURVED_WALL_TOOL_KEY)
        register_tool(self.app, self.vertex_tool, key=VERTEX_TOOL_KEY)
        register_tool(self.app, self.move_xy_tool, key=MOVE_XY_TOOL_KEY)
        register_tool(self.app, self.move_z_tool, key=MOVE_Z_TOOL_KEY)
        register_tool(self.app, self.height_tool, key=HEIGHT_TOOL_KEY)
        register_tool(self.app, self.total_height_tool, key=WALL_TOTAL_HEIGHT_TOOL_KEY)
        register_tool(self.app, self.station_z_tool, key=WALL_STATION_Z_TOOL_KEY)
        register_tool(self.app, self.lean_tool, key=WALL_LEAN_TOOL_KEY)
        register_tool(self.app, self.opening_tool, key=WALL_OPENING_TOOL_KEY)
        register_tool(self.app, self.polygon_tool, key=WALL_POLYGON_TOOL_KEY)
        register_tool(self.app, self.arc_tool, key=ARC_TOOL_KEY)
        register_tool(self.app, self.move_vertex_free_tool, key=MOVE_VERTEX_FREE_TOOL_KEY)
        register_tool(self.app, self.move_vertex_continue_tool, key=MOVE_VERTEX_CONTINUE_TOOL_KEY)
        self.action.triggered.connect(self.start_drawing)
        self.curve_action.triggered.connect(self.start_curve_drawing)
        self.toolbar = QToolBar(t("Arquitetura"), self.app.window)
        self.toolbar.setObjectName("arquitetura_parametrica_toolbar")
        self._toolbar_grip = None
        self.toolbar.setIconSize(QSize(24, 24))
        self.toolbar.setMovable(True)
        self.toolbar.setFloatable(True)
        self.toolbar.setAllowedAreas(Qt.AllToolBarAreas)
        self.toolbar.topLevelChanged.connect(lambda _floating: self.fit_toolbar())
        self.toolbar.installEventFilter(self)
        self.simple_wall_action=QAction(wall_icon(),t("Parede simples"),self.app.window);self.simple_wall_action.triggered.connect(lambda:self.start_structure("simple"))
        self.composite_wall_action=QAction(composite_wall_icon(),t("Parede composta"),self.app.window);self.composite_wall_action.triggered.connect(lambda:self.start_structure("composite"))
        self.wall_type_menu=QMenu(self.app.window);self.wall_type_menu.addAction(self.simple_wall_action);self.wall_type_menu.addAction(self.composite_wall_action);self.wall_type_menu.addSeparator();self.wall_type_menu.addAction(self.curve_action)
        self.wall_menu_button=QToolButton(self.app.window);self.wall_menu_button.setDefaultAction(self.action);self.wall_menu_button.setMenu(self.wall_type_menu);self.wall_menu_button.setPopupMode(QToolButton.MenuButtonPopup);self.wall_menu_button.setToolTip(t("Parede — use a seta para escolher simples, composta ou curva."))
        self.toolbar.addWidget(self.wall_menu_button)
        for kind,title in (("door","Porta"),("window","Janela")):
            menu=QMenu(self.app.window)
            for anchor,label in (("left","Âncora esquerda"),("center","Âncora central"),
                                 ("right","Âncora direita")):
                menu.addAction(label,lambda checked=False,k=kind,a=anchor:self.begin_hosted_fill(k,a))
            btn=QToolButton(self.app.window)
            btn.setText(title)
            btn.setToolTip("Selecione uma parede, escolha a âncora e clique para inserir a esquadria.")
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.InstantPopup)
            self.toolbar.addWidget(btn)
        self.app.window.addToolBar(Qt.TopToolBarArea, self.toolbar)
        self.fit_toolbar()
        menu = self.app.add_menu(t("Ferramentas arquitetônicas"))
        self.arch_menu = menu
        if menu is not None:
            sub=menu.addMenu(t("Parede"));sub.addAction(self.simple_wall_action);sub.addAction(self.composite_wall_action);sub.addSeparator();sub.addAction(self.curve_action)
            menu.addSeparator()
            menu.addAction(self.toolbar.toggleViewAction())
        self.app.add_context_menu(self.context_menu)

    def _position_toolbar_grip(self):
        if not hasattr(self, "toolbar"):
            return
        floating = self.toolbar.isFloating()
        if self._toolbar_grip is None:
            self._toolbar_grip = QSizeGrip(self.toolbar)
            self._toolbar_grip.setToolTip(t("Redimensionar a barra flutuante."))
            self._toolbar_grip.setFixedSize(16, 16)
        self._toolbar_grip.setVisible(floating)
        if floating:
            self._toolbar_grip.move(max(0, self.toolbar.width()-self._toolbar_grip.width()-2),
                                    max(0, self.toolbar.height()-self._toolbar_grip.height()-2))
            self._toolbar_grip.raise_()

    def fit_toolbar(self):
        """Fit only a FLOATING toolbar.

        When docked, QMainWindow owns its geometry. Scheduling adjustSize()
        several times while the application is restoring its saved/maximized
        window caused Windows to visibly re-layout the top-level window during
        startup.
        """
        if not hasattr(self, "toolbar"):
            return
        if not self.toolbar.isFloating():
            self._position_toolbar_grip()
            return

        def _fit():
            try:
                if not self.toolbar.isFloating():
                    self._position_toolbar_grip()
                    return
                self.toolbar.adjustSize()
                hint = self.toolbar.sizeHint()
                self.toolbar.resize(max(self.toolbar.width(), hint.width()),
                                    max(self.toolbar.height(), hint.height()))
                self._position_toolbar_grip()
            except RuntimeError:
                pass

        QTimer.singleShot(0, _fit)

    def _make_path_palette(self):
        self.path_palette = RadialPalette(self.app.window, popup=False, role="edit")
        self.path_palette.setObjectName("arquitetura_parametrica_path_palette")
        row = self.path_palette.row

        def button(symbol, tooltip, slot):
            b = QToolButton(self.path_palette)
            set_symbol_icon(b, symbol)
            b.setToolTip(tooltip)
            b.setAutoRaise(True)
            b.setFixedSize(34, 34)
            font = b.font()
            font.setPointSize(16)
            b.setFont(font)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        # Line-context operations. The symbols keep the palette compact; the
        # complete description lives only in the mouse-over tooltip.
        self.insert_btn = button(
            "＋",
            "Inserir vértice: depois clique no ponto exato da linha e mova a junção em XY.",
            self.begin_insert_vertex)
        self.move_xy_btn = button(
            "↔",
            "Mover parede no plano horizontal, mantendo a mesma cota.",
            self.begin_move_wall_xy)
        self.move_z_btn = button(
            "↕",
            "Mover parede na vertical, mantendo a mesma altura.",
            self.begin_move_wall_z)
        self.total_height_btn = button(
            "H",
            "Altura total: move os dois topos juntos e preserva o ângulo de inclinação atual da parede.",
            self.begin_total_height)
        self.arc_btn = button(
            "⌒",
            "Curvar/editar arco: mantém os extremos e puxa a flecha no plano horizontal.",
            self.begin_curve_arc)
        self.opening_btn = button(
            "▣",
            t("Criar abertura retangular hospedada nesta parede."),
            self.begin_wall_opening)
        self.door_btn = button("D", "Porta paramétrica com vão automático.", lambda:self.begin_hosted_fill("door"))
        self.window_btn = button("J", "Janela paramétrica com vão automático.", lambda:self.begin_hosted_fill("window"))
        self.polygon_btn = button(
            "⬡",
            "Desenhar abertura livre por vértices na face da parede.",
            self.begin_wall_polygon)

        # Vertex-context operations.  The first is always free XY movement;
        # the second extends/trims along the current straight direction or
        # along the same circle for an arc.
        self.move_vertex_free_btn = button(
            "✥",
            "Mover vértice livremente no plano horizontal.",
            self.begin_move_vertex_free)
        self.move_vertex_continue_btn = button(
            "→",
            "Continuar a parede a partir deste vértice, preservando sua direção.",
            self.begin_move_vertex_continue)
        self.height_btn = button(
            "⇧",
            "Alterar somente a altura deste topo. Snap ou valor digitado definem a altura local do extremo.",
            self.begin_change_height)
        self.station_z_btn = button(
            "↕",
            "Subir/descer esta extremidade da base; o topo correspondente acompanha e a altura local é preservada.",
            self.begin_station_z)
        self.lean_btn = button(
            "∠",
            "Inclinar a parede: desloca somente este topo no plano horizontal. Valor digitado = ângulo em relação à vertical.",
            self.begin_lean_top)

    def _make_straight_mode_palette(self):
        # First-click construction selector for the straight-wall tool.  It is
        # the same radial component used by edit palettes; popup=False keeps the
        # following viewport click available after a mode is chosen.
        self.straight_mode_palette = RadialPalette(self.app.window, popup=False, role="draw")
        self.straight_mode_palette.setObjectName("arquitetura_parametrica_straight_mode_palette")
        row = self.straight_mode_palette.row
        self.straight_mode_buttons = {}

        def add(symbol, tooltip, mode):
            b = QToolButton(self.straight_mode_palette)
            set_symbol_icon(b, symbol)
            b.setToolTip(tooltip)
            b.setAutoRaise(True)
            b.setCheckable(True)
            b.setFixedSize(36, 36)
            font = b.font(); font.setPointSize(17); b.setFont(font)
            b.clicked.connect(lambda _checked=False, m=mode: self.choose_straight_mode(m))
            row.addWidget(b)
            self.straight_mode_buttons[mode] = b

        add("／", t("Parede reta simples: primeiro ponto e ponto final."), "single")
        add("▱", t("Bloco de 4 paredes por diagonal: primeiro canto e canto oposto."), "rect_diagonal")
        add("⊥", t("Bloco de 4 paredes por base + profundidade: início, fim da base e profundidade perpendicular."), "rect_base_width")
        self.straight_mode_palette.hide()

    def show_straight_mode_palette(self, screen_pos):
        for mode, btn in self.straight_mode_buttons.items():
            btn.setChecked(mode == self.tool.mode)
        pos = self.app.viewport.mapToGlobal(
            QPoint(int(screen_pos.x()), int(screen_pos.y())))
        self.straight_mode_palette.show_at(pos)

    def hide_straight_mode_palette(self):
        if hasattr(self, "straight_mode_palette"):
            self.straight_mode_palette.hide()

    def choose_straight_mode(self, mode):
        self.tool.set_mode(mode)
        self.hide_straight_mode_palette()
        self.app.viewport.setFocus()

    def _make_curve_mode_palette(self):
        # The creation-method selector now uses the same radial visual language
        # as contextual edit palettes.  It opens on the first point and keeps
        # that point while the user switches between the three arc methods.
        self.curve_mode_palette = RadialPalette(self.app.window, popup=False, role="draw")
        self.curve_mode_palette.setObjectName("arquitetura_parametrica_curve_mode_palette")
        row = self.curve_mode_palette.row
        self.curve_mode_buttons = {}

        def add(symbol, tooltip, mode):
            b = QToolButton(self.curve_mode_palette)
            set_symbol_icon(b, symbol)
            b.setToolTip(tooltip)
            b.setAutoRaise(True)
            b.setCheckable(True)
            b.setFixedSize(36, 36)
            font = b.font(); font.setPointSize(17); b.setFont(font)
            b.clicked.connect(lambda _checked=False, m=mode: self.choose_curve_mode(m))
            row.addWidget(b)
            self.curve_mode_buttons[mode] = b

        add("⌒", t("Arco padrão: início, fim e depois puxe a flecha para qualquer lado."), "normal")
        add("⊙", t("Arco pelo centro: centro, início da parede e fim do arco."), "center")
        add("∴", t("Arco por 3 pontos: início, ponto intermediário e fim."), "three")
        self.curve_mode_palette.hide()

    def show_curve_mode_palette(self, screen_pos):
        for mode, btn in self.curve_mode_buttons.items():
            btn.setChecked(mode == self.curve_create_tool.mode)
        pos = self.app.viewport.mapToGlobal(
            QPoint(int(screen_pos.x()), int(screen_pos.y())))
        self.curve_mode_palette.show_at(pos)

    def hide_curve_mode_palette(self):
        if hasattr(self, "curve_mode_palette"):
            self.curve_mode_palette.hide()

    def choose_curve_mode(self, mode):
        self.curve_create_tool.set_mode(mode)
        self.hide_curve_mode_palette()
        self.app.viewport.setFocus()

    def hide_path_palette(self):
        if hasattr(self, "path_palette"):
            self.path_palette.hide()
        self._path_palette_wall = None
        self._path_palette_anchor = None
        self._path_palette_kind = None

    def show_path_palette(self, global_pos, wall, kind, anchor):
        self._path_palette_wall = wall
        self._path_palette_anchor = QVector3D(anchor)
        self._path_palette_kind = kind
        line = kind == "segment"
        try:
            path_kind = wall_path_kind(wall)
        except WallError:
            path_kind = None
        self.insert_btn.setVisible(line and path_kind in ("line", "arc"))
        self.move_xy_btn.setVisible(line)
        self.move_z_btn.setVisible(line)
        self.total_height_btn.setVisible(kind == "height")
        self.arc_btn.setVisible(line and path_kind in ("line", "arc"))
        self.opening_btn.setVisible(line and path_kind in ("line", "arc"))
        self.polygon_btn.setVisible(line and path_kind in ("line", "arc"))
        vertex = kind == "vertex" and path_kind in ("line", "arc")
        self.move_vertex_free_btn.setVisible(vertex)
        self.move_vertex_continue_btn.setVisible(vertex)
        self.station_z_btn.setVisible(vertex)
        # Upper endpoint controls are independent: vertical edit changes only
        # the crown height; lean moves only the upper point in XY.
        self.height_btn.setVisible(kind == "height")
        self.lean_btn.setVisible(kind == "height")
        if path_kind == "arc":
            self.move_vertex_continue_btn.setToolTip(
                "Continuar o mesmo arco: move este vértice ao longo do círculo atual.")
        else:
            self.move_vertex_continue_btn.setToolTip(
                "Continuar na mesma direção: prolonga ou encurta a parede reta sem mudar seu eixo.")
        self.path_palette.show_at(global_pos)

    def _palette_target(self):
        wall, anchor = self._path_palette_wall, self._path_palette_anchor
        if wall is None or wall not in self.app.scene.groups or anchor is None:
            self.hide_path_palette()
            self.message("Selecione novamente a parede.", error=True)
            return None, None
        return wall, QVector3D(anchor)

    def begin_insert_vertex(self):
        wall, _anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.vertex_tool.prepare(wall)
        activate_vertex_insert(self.app)
        self.app.viewport.setFocus()

    def begin_move_wall_xy(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.move_xy_tool.prepare(wall, anchor)
        activate_move_xy(self.app)
        self.app.viewport.setFocus()

    def begin_move_wall_z(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.move_z_tool.prepare(wall, anchor)
        activate_move_z(self.app)
        self.app.viewport.setFocus()

    def begin_move_vertex_free(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.move_vertex_free_tool.prepare(wall, anchor)
        activate_move_vertex_free(self.app)
        self.app.viewport.setFocus()

    def begin_move_vertex_continue(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.move_vertex_continue_tool.prepare(wall, anchor)
        activate_move_vertex_continue(self.app)
        self.app.viewport.setFocus()

    def begin_total_height(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.total_height_tool.prepare(wall, anchor)
        activate_wall_total_height(self.app)
        self.app.viewport.setFocus()

    def begin_change_height(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.height_tool.prepare(wall, anchor)
        activate_height(self.app)
        self.app.viewport.setFocus()

    def begin_station_z(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.station_z_tool.prepare(wall, anchor)
        activate_wall_station_z(self.app)
        self.app.viewport.setFocus()

    def begin_lean_top(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.lean_tool.prepare(wall, anchor)
        activate_wall_lean(self.app)
        self.app.viewport.setFocus()

    def begin_hosted_fill(self, kind, anchor="center"):
        wall,point=self._palette_target()
        if wall is None:
            walls=selected_walls(self.app.scene)
            wall=walls[0] if len(walls)==1 else None
            if wall is not None:
                point=path_world(wall)[0]
        self.hide_path_palette()
        if wall is None:
            self.message("Selecione uma parede para inserir a porta ou janela.",error=True)
            return
        try:
            self.opening_tool.prepare(wall,point,kind=kind,fill_anchor=anchor)
            activate_wall_opening(self.app)
            self.app.viewport.setFocus()
        except WallError as exc:
            self.message(str(exc),error=True)

    def begin_wall_opening(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.opening_tool.prepare(wall, anchor)
        activate_wall_opening(self.app)
        self.app.viewport.setFocus()

    def begin_wall_polygon(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        self.polygon_tool.prepare(wall, anchor)
        activate_wall_polygon(self.app)
        self.app.viewport.setFocus()

    def edit_wall_polygon(self, operation="move_vertex"):
        if self.target is None or not self._active_opening_id:
            return
        try:
            values = read_wall(self.target)
            opening = next((x for x in values.get("openings", ())
                            if x.get("id") == self._active_opening_id), None)
            if not opening or opening.get("kind") != "polygon":
                raise WallError("Selecione uma abertura livre para editar.")
            origin = path_world(self.target)[0]
            self.polygon_tool.prepare(self.target, origin,
                                      opening_id=self._active_opening_id,
                                      operation=operation)
            activate_wall_polygon(self.app)
            self.app.viewport.setFocus()
        except WallError as exc:
            self.message(str(exc), error=True)

    def _load_opening_fields(self, openings):
        ops=list(openings or [])
        if not ops:
            self._active_opening_id=None;self.opening_widget.hide();return
        item=next((x for x in ops if x.get("id")==self._active_opening_id),ops[0]);self._active_opening_id=item.get("id")
        self.opening_widget.show();blocked=[]
        selector_block=self.opening_selector.blockSignals(True)
        try:
            self.opening_selector.clear()
            for i,op in enumerate(ops):
                kind=("Vão livre" if op.get("kind")=="polygon" else
                      "Porta" if (op.get("fill") or {}).get("class")=="IfcDoor" else
                      "Janela" if (op.get("fill") or {}).get("class")=="IfcWindow" else "Vão")
                self.opening_selector.addItem(f"{i+1} · {kind}",op.get("id"))
            self.opening_selector.setCurrentIndex(self.opening_selector.findData(self._active_opening_id))
        finally:
            self.opening_selector.blockSignals(selector_block)
        polygon = item.get("kind") == "polygon"
        for f in self.opening_fields.values():
            f.setVisible(not polygon)
            label = self.opening_widget.layout().labelForField(f)
            if label is not None:
                label.setVisible(not polygon)
        self.polygon_label.setVisible(polygon)
        self.polygon_tools.setVisible(polygon)
        self.opening_fill.setEnabled(not polygon and self._find_linked_fill(item) is None)
        try:
            for key,f in self.opening_fields.items():blocked.append((f,f.blockSignals(True)));f.setValue(float(item.get(key,0.0)))
            oldb=self.opening_fill.blockSignals(True);fill=item.get("fill") if isinstance(item.get("fill"),dict) else {};cls=fill.get("class") or item.get("fill_class") or item.get("ifc_fill_class");idx=self.opening_fill.findData(cls);self.opening_fill.setCurrentIndex(idx if idx>=0 else 0);self.opening_fill.blockSignals(oldb)
        finally:
            for f,b in blocked:f.blockSignals(b)

    def _find_linked_fill(self, opening):
        if self.target is None or not opening.get("source_id"):
            return None
        for group in getattr(self.app.scene, "groups", ()):
            rec=_fill_record(group)
            if (rec and rec.get("host_id")==getattr(self.target,"uid",None)
                    and rec.get("opening_id")==opening.get("id")
                    and rec.get("source_id")==opening.get("source_id")):
                return group
        return None

    def _select_opening_from_list(self,*_):
        if self._loading or self.target is None:
            return
        oid=self.opening_selector.currentData()
        if oid:
            self._active_opening_id=oid
            self._load_opening_fields(read_wall(self.target).get("openings",[]))
            self.app.viewport.update()

    def _opening_wires_for(self,wall):
        key=(id(self.app.scene),self.app.scene.version,id(wall))
        if self._opening_wire_key!=key:
            try:
                self._opening_wire_data=all_opening_wires(wall,read_wall(wall))
            except (WallError,ValueError,TypeError):
                self._opening_wire_data=[]
            self._opening_wire_key=key
        return self._opening_wire_data

    def _change_opening_handle(self,oid,handle_id,action):
        if self.target is None:
            return
        try:
            values=read_wall(self.target)
            opening=next(o for o in values["openings"] if o["id"]==oid)
            if opening.get("kind")=="polygon":
                self.edit_wall_polygon("move_vertex")
                return
            linked=self._find_linked_fill(opening)
            old_spec=normalize_fill(_fill_record(linked)["params"]) if linked else None
            nominal=float(opening.get(action,0))
            side=handle_id.split("-")[-1]
            if action=="position":
                if old_spec:
                    from .door_window_core import station_span
                    s0,s1=station_span(old_spec)
                else:
                    s0=float(opening["position"])-float(opening["width"])/2
                    s1=float(opening["position"])+float(opening["width"])/2
                nominal={"left":s0,"center":(s0+s1)/2,"right":s1}[side]
            label={"width":"Largura livre (m)","height":"Altura da abertura (m)",
                   "position":"Posição do ponto de controle (m)"}[action]
            value,ok=QInputDialog.getDouble(self.app.window,label,label,nominal,
                                           0.0 if action=="position" else MIN_DIM,
                                           MAX_DIM,4)
            if not ok or abs(value-nominal)<1.e-8:
                return
            if linked:
                edited=edit_from_hotspot(old_spec,handle_id,action,value)
                changes={k:edited[k] for k in ("position","width","height")
                         if edited[k]!=old_spec[k]}
                cmd=EditHostedFill(self.app.scene,self.target,linked,changes)
            else:
                if action=="position":
                    opening["position"]+=value-nominal
                else:
                    opening[action]=value
                cmd=EditWall(self.app.scene,self.target,values)
            self.app.viewport.history.execute(cmd)
            if self.app.viewport.history.last_error:
                raise WallError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed()
            self._state_key=None
            self.refresh()
        except (WallError,ValueError,StopIteration) as exc:
            self.message(str(exc),error=True)

    def _show_opening_handle_menu(self,oid,handle_id,point):
        menu=QMenu(self.app.window)
        if handle_id.startswith("vertex-"):
            for title,operation in (("Mover vértice","move_vertex"),
                                    ("Inserir vértice","insert_vertex"),
                                    ("Mover aresta","move_edge"),
                                    ("Excluir vértice","delete_vertex")):
                menu.addAction(title,lambda checked=False,op=operation:self.edit_wall_polygon(op))
        else:
            actions=("width","position") if handle_id.startswith("bottom-") else ("width","height")
            for action in actions:
                title={"width":"Alterar largura","position":"Mover posição","height":"Alterar altura"}[action]
                menu.addAction(title,lambda checked=False,a=action:
                               self._change_opening_handle(oid,handle_id,a))
        menu.popup(point)

    def opening_changed(self,*_):
        if self._loading or self.target is None or not self._active_opening_id:return
        try:
            vals=read_wall(self.target);ops=copy.deepcopy(vals.get("openings",[]));item=next((x for x in ops if x.get("id")==self._active_opening_id),None)
            if item is None:return
            if item.get("kind") == "polygon":
                return  # Free cuts are edited by polygon vertices, not rectangular controls.
            for key,f in self.opening_fields.items():f.interpretText();item[key]=float(f.value())
            linked=self._find_linked_fill(item)
            if linked is not None:
                old=normalize_fill(_fill_record(linked)["params"])
                new_position=old["position"]+item["position"]-float(
                    next(o for o in read_wall(self.target)["openings"]
                         if o["id"]==item["id"])["position"])
                changes={"width":item["width"],"height":item["height"],
                         "sill":item["sill"],"position":new_position}
                self.app.viewport.history.execute(
                    EditHostedFill(self.app.scene,self.target,linked,changes))
                if self.app.viewport.history.last_error:
                    raise WallError(self.app.viewport.history.last_error)
                self.app.viewport.notify_scene_changed();self._state_key=None
                self.schedule_refresh()
                return
            cls=self.opening_fill.currentData()
            if cls:
                oldfill=item.get("fill") if isinstance(item.get("fill"),dict) else {};fill=copy.deepcopy(oldfill);fill["class"]=str(cls);fill.setdefault("name","Porta" if cls=="IfcDoor" else "Janela");fill.setdefault("predefined_type","DOOR" if cls=="IfcDoor" else "WINDOW");item["fill"]=fill
            else:item.pop("fill",None);item.pop("fill_class",None);item.pop("ifc_fill_class",None)
            vals["openings"]=ops;self.app.viewport.history.execute(EditWall(self.app.scene,self.target,vals))
            if self.app.viewport.history.last_error:raise WallError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed();self._state_key=None;self.schedule_refresh()
        except WallError as exc:self.message(str(exc),error=True)

    def delete_wall_opening(self):
        if self.target is None or not self._active_opening_id:return
        try:
            vals=read_wall(self.target)
            target_id=self._active_opening_id
            item=next((x for x in vals["openings"] if x.get("id")==target_id),None)
            if item is None:return
            linked=self._find_linked_fill(item)
            vals["openings"]=[x for x in vals["openings"] if x.get("id")!=target_id]
            self._active_opening_id=None
            cmd=DeleteHostedOpening(self.app.scene,self.target,target_id) if linked else EditWall(self.app.scene,self.target,vals)
            self.app.viewport.history.execute(cmd)
            if self.app.viewport.history.last_error:raise WallError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed();self._state_key=None;self.refresh();self.message("Abertura excluída.")
        except WallError as exc:self.message(str(exc),error=True)

    def begin_curve_arc(self):
        wall, anchor = self._palette_target()
        self.hide_path_palette()
        if wall is None:
            return
        try:
            if wall_path_kind(wall) not in ("line", "arc"):
                raise WallError("Curvar em arco aceita, por enquanto, uma parede reta ou um arco existente.")
            self.arc_tool.prepare(wall, anchor)
            activate_arc(self.app)
            self.app.viewport.setFocus()
        except WallError as exc:
            self.message(str(exc), error=True)

    @staticmethod
    def _pixel_segment_nearest(px, py, a, b):
        ax, ay = a; bx, by = b
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        if den <= 1e-9:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5, 0.0
        t = ((px - ax) * dx + (py - ay) * dy) / den
        t = max(0.0, min(1.0, t))
        qx, qy = ax + t * dx, ay + t * dy
        return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5, t

    def _reference_context(self, px, py, wall, line_threshold=8.0, vertex_threshold=9.0):
        try:
            world = base_path_world(wall)
        except WallError:
            return None
        screen = [self.app.viewport._world_to_pixel(p) for p in world]
        try:
            ref_vertices = base_reference_vertices_world(wall)
        except WallError:
            ref_vertices = world
        vertex_screen = [self.app.viewport._world_to_pixel(p) for p in ref_vertices]

        # Height handles live at the TOP of both true wall endpoints.  They are
        # separate from the base/reference vertices so clicking a base vertex is
        # reserved for path editing.  In a top view the two project to the same
        # pixel; in that case the height handle is intentionally ignored so the
        # endpoint remains usable.
        try:
            top_vertices = top_reference_vertices_world(wall)
        except (WallError, KeyError, TypeError):
            top_vertices = []
        top_screen = [self.app.viewport._world_to_pixel(p) for p in top_vertices]
        best_top = None
        for i, pt in enumerate(top_screen):
            if pt is None:
                continue
            base_pt = vertex_screen[i] if i < len(vertex_screen) else None
            if base_pt is not None:
                separation = ((pt[0] - base_pt[0]) ** 2 + (pt[1] - base_pt[1]) ** 2) ** 0.5
                if separation < 7.0:
                    continue
            d = ((px - pt[0]) ** 2 + (py - pt[1]) ** 2) ** 0.5
            if d <= vertex_threshold and (best_top is None or d < best_top[0]):
                best_top = (d, i)
        if best_top is not None:
            return "height", QVector3D(top_vertices[best_top[1]])

        # Only true editable BASE vertices win over the curve/segment beneath
        # them; sampled arc points are display geometry, not user vertices.
        best_vertex = None
        for i, pt in enumerate(vertex_screen):
            if pt is None:
                continue
            d = ((px - pt[0]) ** 2 + (py - pt[1]) ** 2) ** 0.5
            if d <= vertex_threshold and (best_vertex is None or d < best_vertex[0]):
                best_vertex = (d, i)
        if best_vertex is not None:
            i = best_vertex[1]
            return "vertex", QVector3D(ref_vertices[i])

        best = None
        for i, (a, b) in enumerate(zip(screen, screen[1:])):
            if a is None or b is None:
                continue
            dist, t = self._pixel_segment_nearest(px, py, a, b)
            if dist <= line_threshold and (best is None or dist < best[0]):
                anchor = world[i] + (world[i + 1] - world[i]) * t
                best = (dist, anchor)
        return None if best is None else ("segment", QVector3D(best[1]))

    def eventFilter(self, obj, event):
        if obj is getattr(self, "toolbar", None) and event.type() in (QEvent.Resize, QEvent.Show, QEvent.Move):
            QTimer.singleShot(0, self._position_toolbar_grip)
            return False
        # The native Select tool uses press→release for box selection. Intercept
        # only hits on the visible parametric reference, leaving normal
        # selection untouched everywhere else.
        if obj is self.app.viewport and event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                if hasattr(self, "path_palette") and self.path_palette.isVisible():
                    self.hide_path_palette()
                vp = self.app.viewport
                select_tool = host_tool(self.app, "select")
                walls = selected_walls(self.app.scene)
                if (vp.active_tool is select_tool and len(walls) == 1
                        and event.modifiers() == Qt.NoModifier):
                    opening_hit=hit_test(vp,self._opening_wires_for(walls[0]),
                                         event.position().x(),event.position().y(),
                                         active_id=self._active_opening_id)
                    if opening_hit is not None:
                        opening_id,handle_id=opening_hit
                        self._active_opening_id=opening_id
                        self._state_key=None
                        self.refresh()
                        vp.update()
                        if handle_id:
                            point=event.globalPosition().toPoint()
                            QTimer.singleShot(0,lambda oid=opening_id,h=handle_id,p=point:
                                               self._show_opening_handle_menu(oid,h,p))
                        return True
                    hit = self._reference_context(
                        event.position().x(), event.position().y(), walls[0])
                    if hit is not None:
                        kind, anchor = hit
                        self.show_path_palette(
                            event.globalPosition().toPoint(), walls[0], kind, anchor)
                        return True
        return super().eventFilter(obj, event)

    def draw_reference_overlay(self, viewport, painter):
        # Centre-radius construction guide for the curved-wall centre method.
        # It is intentionally independent of selection because no wall exists yet.
        if (viewport.active_tool is self.curve_create_tool
                and self.curve_create_tool.mode == self.curve_create_tool.MODE_CENTER
                and self.curve_create_tool.first_point is not None
                and self.curve_create_tool.hover_point is not None):
            centre = QVector3D(self.curve_create_tool.first_point)
            target = QVector3D(self.curve_create_tool.hover_point)
            if self.curve_create_tool.second_point is not None:
                try:
                    spec = self.curve_create_tool._center_spec(self.curve_create_tool.hover_point)
                except WallError:
                    spec = None
                if spec is not None:
                    target = QVector3D(spec[1])
            pc = viewport._world_to_pixel(centre)
            pt = viewport._world_to_pixel(target)
            if pc is not None and pt is not None:
                painter.setPen(QPen(QColor("#e64646"), 1.8, Qt.SolidLine))
                painter.drawLine(QPointF(pc[0], pc[1]), QPointF(pt[0], pt[1]))
                painter.setBrush(QColor("#e64646"))
                painter.drawEllipse(QRectF(pc[0] - 3.0, pc[1] - 3.0, 6.0, 6.0))

        # When an arc endpoint is being continued along its existing circle,
        # bring the radius construction line back: centre -> active endpoint.
        # It makes the constraint explicit while the user stretches the wall.
        if (viewport.active_tool is self.move_vertex_continue_tool
                and self.move_vertex_continue_tool.kind == "arc"
                and self.move_vertex_continue_tool.arc_center is not None
                and self.move_vertex_continue_tool.hover is not None):
            centre = QVector3D(self.move_vertex_continue_tool.arc_center)
            target = QVector3D(self.move_vertex_continue_tool.hover)
            pc = viewport._world_to_pixel(centre)
            pt = viewport._world_to_pixel(target)
            if pc is not None and pt is not None:
                painter.setPen(QPen(QColor("#e64646"), 1.8, Qt.SolidLine))
                painter.drawLine(QPointF(pc[0], pc[1]), QPointF(pt[0], pt[1]))
                painter.setBrush(QColor("#e64646"))
                painter.drawEllipse(QRectF(pc[0] - 3.0, pc[1] - 3.0, 6.0, 6.0))

        walls = selected_walls(self.app.scene)
        if not walls:
            return
        pen = QPen(QColor("#1f83d6"), 2.0, Qt.DashLine)
        vertex_pen = QPen(QColor("#1f83d6"), 1.5)
        height_pen = QPen(QColor("#f0a33b"), 1.6)
        center_pen = QPen(QColor("#e64646"), 1.4)
        for wall in walls:
            try:
                pts = base_path_world(wall)
            except WallError:
                continue
            pixels = [viewport._world_to_pixel(p) for p in pts]
            painter.setPen(pen)
            for a, b in zip(pixels, pixels[1:]):
                if a is not None and b is not None:
                    painter.drawLine(QPointF(a[0], a[1]), QPointF(b[0], b[1]))
            try:
                vertex_pixels = [viewport._world_to_pixel(p) for p in base_reference_vertices_world(wall)]
            except WallError:
                vertex_pixels = pixels
            painter.setPen(vertex_pen)
            painter.setBrush(QColor("white"))
            for pt in vertex_pixels:
                if pt is not None:
                    painter.drawEllipse(QRectF(pt[0] - 3.5, pt[1] - 3.5, 7.0, 7.0))

            # Two dedicated height hotspots at the top endpoints.  Do not draw
            # them in a view where top/base collapse to the same screen point;
            # there the base path vertex must remain the unambiguous control.
            try:
                top_vertices = top_reference_vertices_world(wall)
                top_pixels = [viewport._world_to_pixel(p) for p in top_vertices]
                top_curve = top_path_world(wall)
                top_curve_pixels = [viewport._world_to_pixel(p) for p in top_curve]
                painter.setPen(QPen(QColor("#f0a33b"), 1.4, Qt.DashLine))
                for a,b in zip(top_curve_pixels, top_curve_pixels[1:]):
                    if a is not None and b is not None:
                        painter.drawLine(QPointF(a[0],a[1]),QPointF(b[0],b[1]))
            except (WallError, KeyError, TypeError):
                top_pixels = []
            painter.setPen(height_pen)
            painter.setBrush(QColor("white"))
            for i, pt in enumerate(top_pixels):
                if pt is None:
                    continue
                base_pt = vertex_pixels[i] if i < len(vertex_pixels) else None
                if base_pt is not None:
                    separation = ((pt[0] - base_pt[0]) ** 2 + (pt[1] - base_pt[1]) ** 2) ** 0.5
                    if separation < 7.0:
                        continue
                painter.drawEllipse(QRectF(pt[0] - 4.0, pt[1] - 4.0, 8.0, 8.0))
                painter.drawLine(QPointF(pt[0] - 5.5, pt[1]), QPointF(pt[0] + 5.5, pt[1]))

            # Virtual controllers are overlays, never editable hidden solids.
            if wall is self.target:
                for oid,segments,grips in self._opening_wires_for(wall):
                    active=(oid==self._active_opening_id)
                    painter.setPen(QPen(QColor("#e78b24") if active else QColor("#6997b0"),
                                        2.0 if active else 1.0,
                                        Qt.SolidLine if active else Qt.DashLine))
                    for a,b in segments:
                        pa,pb=viewport._world_to_pixel(a),viewport._world_to_pixel(b)
                        if pa is not None and pb is not None:
                            painter.drawLine(QPointF(pa[0],pa[1]),QPointF(pb[0],pb[1]))
                    if active:
                        painter.setPen(QPen(QColor("#e78b24"),1.5))
                        painter.setBrush(QColor("white"))
                        for handle_id,p in grips:
                            px=viewport._world_to_pixel(p)
                            if px is not None:
                                painter.drawRect(QRectF(px[0]-4,px[1]-4,8,8))

            # ArchiCAD-like hotspot at the mathematical centre of a selected arc.
            try:
                centre = arc_center_world(wall) if wall_path_kind(wall) == "arc" else None
            except WallError:
                centre = None
            if centre is not None:
                cp = viewport._world_to_pixel(centre)
                if cp is not None:
                    painter.setPen(center_pen)
                    painter.setBrush(QColor("white"))
                    painter.drawEllipse(QRectF(cp[0] - 4.0, cp[1] - 4.0, 8.0, 8.0))
                    painter.drawLine(QPointF(cp[0] - 6.0, cp[1]), QPointF(cp[0] + 6.0, cp[1]))
                    painter.drawLine(QPointF(cp[0], cp[1] - 6.0), QPointF(cp[0], cp[1] + 6.0))

    def context_menu(self, menu, selection):
        walls = selected_walls(self.app.scene)
        if len(walls) == 1:
            menu.addAction("Editar parede paramétrica…",
                           lambda: QTimer.singleShot(0, self.show_selected))
        elif len(walls) == 2:
            menu.addAction("Encontrar paredes (prolongar/aparar)",
                           lambda: QTimer.singleShot(0, self.meet_selected_walls))

    def meet_selected_walls(self):
        try:
            walls = selected_walls(self.app.scene)
            if len(walls) != 2:
                raise WallError("Selecione exatamente duas paredes paramétricas.")
            cmd = MeetWalls(self.app.scene, walls[0], walls[1])
            self.app.viewport.history.execute(cmd)
            if self.app.viewport.history.last_error:
                raise WallError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed()
            self._state_key = None
            self.message("Paredes encontradas pela interseção das linhas de referência.")
            self.schedule_refresh()
        except WallError as exc:
            self.message(str(exc), error=True)
        except Exception:
            log.exception("Wall meet failed")
            self.message("Não foi possível encontrar as paredes. Consulte o registro do IngeTrazo.",
                         error=True)

    def show_selected(self):
        self.stop_drawing()
        self._state_key = None
        self.refresh()
        if self.target is not None:
            self.app.show_panel(self.dock)

    def start_drawing(self, *_):
        try:
            root_edit_allowed(self.app.scene)
            if self.app.workspace() is not None:
                raise WallError("Volte ao modelo para desenhar paredes.")
        except WallError as exc:
            self.action.setChecked(False)
            self.app.viewport.flash_status(t(str(exc)), 6000)
            return
        self.app.scene.clear_selection()
        activate_wall(self.app)
        self._state_key = None
        self.refresh()
        self.message("Clique no início da parede. A cota de base define o plano horizontal.")
        self.app.viewport.setFocus()

    def start_curve_drawing(self, *_):
        try:
            root_edit_allowed(self.app.scene)
            if self.app.workspace() is not None:
                raise WallError("Volte ao modelo para desenhar paredes.")
        except WallError as exc:
            self.curve_action.setChecked(False)
            self.app.viewport.flash_status(t(str(exc)), 6000)
            return
        self.app.scene.clear_selection()
        self.curve_create_tool.reset()
        activate_curved_wall(self.app)
        self._state_key = None
        self.refresh()
        self.message("Clique no primeiro ponto. O arco padrão é o método inicial.")
        self.app.viewport.setFocus()

    def stop_drawing(self):
        if self.app.viewport.active_tool in (self.tool, self.curve_create_tool):
            activate_select(self.app)
        self.hide_straight_mode_palette()
        self.hide_curve_mode_palette()
        self.schedule_refresh()

    def schedule_refresh(self, *_):
        if not self._queued:
            self._queued = True
            QTimer.singleShot(0, self.refresh)

    def refresh(self):
        self._queued = False
        scene, vp = self.app.scene, self.app.viewport
        if scene is not self._document:
            self._document = scene
            self.tool.reset()
            self.curve_create_tool.reset()
            self.defaults = copy.deepcopy(DEFAULTS)
            self.default_wall_predefined = "SOLIDWALL"
            self.default_wall_status = None
            self._loaded_key = None
            self._junction_key = None

        # Tops intentionally linked to the Níveis extension are derived from
        # that level + offset.  Regenerate them before junction cleanup so a
        # level edit updates the wall bodies in the same refresh, without a
        # separate undo step for every affected wall.
        try:
            level_changed = sync_bound_wall_tops(self.app)
        except Exception:
            level_changed = 0
            log.exception("Falha ao atualizar topos vinculados a níveis")
        if level_changed:
            self._state_key = None
            vp.notify_scene_changed()

        # Junction cleanup is derived from the current reference endpoints and
        # wall parameters.  Recompute once per document version so creation,
        # split, live parameter edits, native undo/redo and even the generic
        # Move tool all converge to the same geometry without adding a second
        # history step.
        junction_key = (id(scene), wall_junction_input_key(scene))
        if junction_key != self._junction_key:
            changed = 0
            try:
                changed = sync_wall_junctions(scene)
            except Exception:
                log.exception("Falha ao atualizar junções paramétricas")
            # Cache the *input* signature before notifying the host. Derived
            # caps do not belong to this key, so the follow-up scene signal
            # does not immediately run the expensive resolver a second time.
            self._junction_key = junction_key
            if changed:
                # The resolver changes only derived meshes/endpoint metadata.
                # Give the host one fresh version so render/pick/section caches
                # see those new meshes; this is not an extra undoable command.
                scene.version += 1
                vp.notify_scene_changed()

        walls = selected_walls(scene)
        selection_key = tuple(sorted(id(w) for w in walls))
        key = (id(scene), scene.version, id(vp.active_tool), id(scene.edit_group),
               selection_key)
        if key == self._state_key:
            return
        self._state_key = key
        straight_drawing = vp.active_tool is self.tool
        curve_drawing = vp.active_tool is self.curve_create_tool
        drawing = straight_drawing or curve_drawing
        context = ("create" if drawing else
                   "edit" if len(walls) == 1 else
                   "pair" if len(walls) == 2 else None)
        if scene.edit_group is not None or self.app.workspace() is not None:
            context = None
        context_id = (id(walls[0]) if context == "edit" else
                      tuple(sorted(id(w) for w in walls)) if context == "pair" else None)
        changed_context = (context, context_id) != self._context
        self._context = (context, context_id)
        self.target = walls[0] if context == "edit" else None
        self.target_scene = scene if self.target is not None else None
        self.form_widget.setVisible(context in ("create", "edit"))
        self.pair_widget.setVisible(context == "pair")
        if context is None:
            if getattr(self.app.window, "_arquitetura_parametrica_suite_panel", None) is None:
                self.dock.hide()
            self._loaded_key = None
            return
        if context == "pair":
            self.heading.setText("2 paredes selecionadas")
            self.hint.setText(
                "Use ⋈ para prolongar ou aparar as duas pontas mais próximas até a "
                "interseção das linhas de referência. A operação funciona como um "
                "Extend/Trim simultâneo e mantém as paredes independentes.")
            self._loaded_key = None
            if changed_context:
                self.feedback.clear()
                self.app.show_panel(self.dock)
            return
        self.heading.setText(("Nova parede curva" if curve_drawing else "Nova parede") if drawing else "Parede selecionada")
        # A change made by the Níveis extension increments scene.version, so
        # refresh the combos even when the selected wall parameters did not change.
        self.refresh_level_options(); self.refresh_material_options()
        if drawing:
            self._update_bound_height_field()
            top_name = self.top_level.currentData()
            if top_name is not None:
                level = level_by_name(self.app, top_name)
                if level is not None:
                    self.defaults["top_mode"] = "level"
                    self.defaults["top_level"] = top_name
                    self.defaults["top_offset"] = float(self.top_offset.value())
                    self.defaults["height"] = max(
                        MIN_DIM, float(level["z"]) + self.defaults["top_offset"]
                        - float(self.fields["base"].value()))
        # Switching between create/edit changes the allowed minimum for length.
        # QDoubleSpinBox clamps its current value when setMinimum() is called and
        # emits valueChanged.  After drawing, the preview field may still be 0;
        # entering edit mode would therefore clamp it to MIN_DIM and, because
        # edits are live, accidentally resize the selected wall to 0.001 m
        # before its real parameters are loaded.  Treat this as an internal UI
        # state change and suppress signals while configuring the field.
        length_field = self.fields["length"]
        blocked = length_field.blockSignals(True)
        try:
            length_field.setMinimum(0.0 if drawing else MIN_DIM)
            length_field.setSpecialValueText("Aguardando pontos" if drawing else "")
            length_field.setReadOnly(drawing)
            length_field.setToolTip(
                "Definido pelos pontos ou digitando no desenho." if drawing
                else "O início permanece fixo; o fim se desloca.")
        finally:
            length_field.blockSignals(blocked)
        if not drawing and self.target is not None:
            try:
                kind = wall_path_kind(self.target)
                multi_vertex = kind == "polyline"
                curved = kind == "arc"
            except WallError:
                multi_vertex = curved = False
            length_field.setReadOnly(multi_vertex or curved)
            if curved:
                length_field.setToolTip(
                    "Comprimento do arco. Use o botão ⌒ na linha de referência para alterar a curvatura.")
            elif multi_vertex:
                length_field.setToolTip(
                    "Comprimento total da trajetória. Edite os vértices para alterar uma parede segmentada.")
        self.form_widget.setEnabled(True)
        if straight_drawing:
            hint = ("Clique no início, aponte a direção e digite a medida com Enter, ou clique no fim. "
                    "Esc cancela o trecho; em repouso, sai da ferramenta.")
        elif curve_drawing:
            hint = ("Parede curva: após o primeiro clique escolha ⌒ arco padrão, ⊙ pelo centro ou ∴ por 3 pontos. "
                    "O arco padrão já fica ativo se você não escolher outro método.")
        else:
            hint = ("As alterações são aplicadas imediatamente. Clique na linha azul para operações "
                    "do trecho; clique em um círculo de vértice para operações daquele ponto.")
        self.hint.setText(hint)
        try:
            values = self.defaults if drawing else read_wall(self.target)
            if self.target is not None and not scene.entity_selectable(self.target):
                raise WallError("A parede está bloqueada ou indisponível.")
            loaded_key = (context, id(self.target), tuple(sorted(values.items())))
            if loaded_key != self._loaded_key:
                self.load_fields(values, preserve_layer_editor=self.layer_editor.user_is_editing())
                self._loaded_key = loaded_key
                self.feedback.clear()
            if straight_drawing:
                length = ((self.tool.hover_point - self.tool.start_point).length()
                          if self.tool.start_point is not None and self.tool.hover_point is not None
                          else 0.0)
                self.preview_length(length)
            elif curve_drawing:
                # The curve tool updates this field from its live sampled arc.
                pass
        except WallError as exc:
            self._loaded_key = None
            self.form_widget.setEnabled(False)
            self.message(str(exc), error=True)
        if changed_context:
            self.app.show_panel(self.dock)

    def refresh_level_options(self):
        current_base = self.base_level.currentData() if self.base_level.count() else None
        current_top = self.top_level.currentData() if self.top_level.count() else None
        base_blocked = self.base_level.blockSignals(True)
        top_blocked = self.top_level.blockSignals(True)
        try:
            levels = available_levels(self.app)
            self.base_level.clear()
            self.base_level.addItem(t("Cota livre"), None)
            self.top_level.clear()
            self.top_level.addItem(t("Livre (altura)"), None)
            for level in levels:
                try:
                    name = str(level["name"])
                    z = float(level["z"])
                except (KeyError, TypeError, ValueError):
                    continue
                label = f"{name}  ({z:+.2f} m)"
                self.base_level.addItem(label, name)
                self.top_level.addItem(label, name)
            index = self.base_level.findData(current_base)
            self.base_level.setCurrentIndex(index if index >= 0 else 0)
            index = self.top_level.findData(current_top)
            self.top_level.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.base_level.blockSignals(base_blocked)
            self.top_level.blockSignals(top_blocked)
        self._update_top_binding_ui()

    def refresh_material_options(self):
        current=self.material.currentData() if hasattr(self,"material") and self.material.count() else self.defaults.get("material_name")
        if not hasattr(self,"material"):return
        names=material_names(self.app.scene);key=tuple(names)
        if getattr(self,"_material_options_key",None)!=key:
            blocked=self.material.blockSignals(True)
            try:
                self.material.clear();self.material.addItem(t("Padrão"),None)
                for name in names:self.material.addItem(name,name)
                i=self.material.findData(current);self.material.setCurrentIndex(i if i>=0 else 0)
            finally:self.material.blockSignals(blocked)
            self._material_options_key=key
        if hasattr(self,"layer_editor"):self.layer_editor.set_material_names(names)

    def _update_top_binding_ui(self):
        linked = self.top_level.currentData() is not None
        self.top_offset.setEnabled(linked)
        if "height" in self.fields:
            self.fields["height"].setReadOnly(linked)
            self.fields["height"].setToolTip(
                "Calculada pelo nível de topo + offset." if linked
                else "Altura livre da parede.")

    def _update_bound_height_field(self):
        name = self.top_level.currentData()
        if not name or "height" not in self.fields or "base" not in self.fields:
            self._update_top_binding_ui()
            return
        level = level_by_name(self.app, name)
        if level is None:
            self._update_top_binding_ui()
            return
        height = float(level["z"]) + float(self.top_offset.value()) - float(self.fields["base"].value())
        if height < MIN_DIM:
            # Keep the current valid field value; values() will report the
            # invalid binding clearly if the user tries to commit it.
            self._update_top_binding_ui()
            return
        blocked = self.fields["height"].blockSignals(True)
        try:
            self.fields["height"].setValue(height)
        finally:
            self.fields["height"].blockSignals(blocked)
        self._update_top_binding_ui()

    def base_level_changed(self, *_):
        if self._loading:
            return
        name = self.base_level.currentData()
        level = level_by_name(self.app, name)
        if level is not None:
            blocked = self.fields["base"].blockSignals(True)
            try:
                self.fields["base"].setValue(float(level["z"]))
            finally:
                self.fields["base"].blockSignals(blocked)
        self._update_bound_height_field()
        self.defaults_changed()

    def top_level_changed(self, *_):
        if self._loading:
            return
        self._update_bound_height_field()
        self.defaults_changed()

    def top_binding_changed(self, *_):
        if self._loading:
            return
        self._update_bound_height_field()
        self.defaults_changed()

    def load_fields(self, values, preserve_layer_editor=False):
        self._loading = True
        try:
            for key, field in self.fields.items():
                field.setValue(values[key])
            self.alignment.setCurrentIndex(self.alignment.findData(values["alignment"]))
            mi=self.material.findData(values.get("material_name"));self.material.setCurrentIndex(mi if mi>=0 else 0)
            si=self.structure.findData(values.get("structure","simple"));self.structure.setCurrentIndex(si if si>=0 else 0)
            if not preserve_layer_editor:
                self.layer_editor.set_layers(values.get("layers",[]),values.get("thickness",0.10),values.get("material_name"))
            self._load_opening_fields(values.get("openings",[]))
            level_index = self.base_level.findData(values.get("base_level"))
            self.base_level.setCurrentIndex(level_index if level_index >= 0 else 0)
            top_name = values.get("top_level") if values.get("top_mode") == "level" else None
            top_index = self.top_level.findData(top_name)
            self.top_level.setCurrentIndex(top_index if top_index >= 0 else 0)
            self.top_offset.setValue(float(values.get("top_offset", 0.0)))
            if self.target is not None:
                meta=getattr(self.target,"ifc",None) if isinstance(getattr(self.target,"ifc",None),dict) else {}
                pre=str(meta.get("predefined_type") or "NOTDEFINED").upper(); pi=self.ifc_predefined.findData(pre); self.ifc_predefined.setCurrentIndex(pi if pi>=0 else self.ifc_predefined.findData("NOTDEFINED"))
                common=meta.get("common") if isinstance(meta.get("common"),dict) else {}; st=common.get("Status"); si=self.phase_status.findData(st); self.phase_status.setCurrentIndex(si if si>=0 else 0)
            else:
                pi=self.ifc_predefined.findData(self.default_wall_predefined); self.ifc_predefined.setCurrentIndex(pi if pi>=0 else 0)
                si=self.phase_status.findData(self.default_wall_status); self.phase_status.setCurrentIndex(si if si>=0 else 0)
        finally:
            self._loading = False
        self._update_top_binding_ui();self._update_structure_ui()

    def _update_structure_ui(self):
        composite=self.structure.currentData()=="composite"
        self.layer_editor.setVisible(composite);self.fields["thickness"].setEnabled(not composite);self.material.setEnabled(not composite)
        if composite:self.fields["thickness"].setToolTip("Espessura total calculada pela soma das camadas.")

    def _bim_defaults_changed(self,*_):
        if self._loading:return
        pre=str(self.ifc_predefined.currentData() or "NOTDEFINED")
        status=self.phase_status.currentData()
        if self.target is None:
            self.default_wall_predefined=pre;self.default_wall_status=status;return
        try:
            meta=ifc_identity_data(self.target,"IfcWall")
            meta["predefined_type"]=pre
            common=meta.setdefault("common",{})
            if status is None:common.pop("Status",None)
            else:common["Status"]=status
            set_ifc_metadata(self.app,self.target,meta);self.message("Dados IFC da parede atualizados.")
        except Exception as exc:self.message(str(exc),error=True)

    def apply_bim_defaults(self,group):
        """Stamp BIM defaults on a newly created wall before it enters history."""
        meta=ensure_ifc_identity(group,"IfcWall")
        meta["predefined_type"]=str(self.default_wall_predefined or "SOLIDWALL")
        common=meta.setdefault("common",{})
        if self.default_wall_status is None:common.pop("Status",None)
        else:common["Status"]=self.default_wall_status
        group.ifc=meta
        return group

    def structure_changed(self,*_):
        if self._loading:return
        kind=self.structure.currentData() or "simple"
        if kind=="composite" and not self.defaults.get("layers"):
            self.layer_editor.set_layers([],float(self.fields["thickness"].value()),self.material.currentData())
        self.defaults["structure"]=kind;self.defaults["layers"]=self.layer_editor.layers() if kind=="composite" else []
        if kind=="composite":
            total=sum(float(x["thickness"]) for x in self.defaults["layers"]);self.defaults["thickness"]=total
            b=self.fields["thickness"].blockSignals(True);self.fields["thickness"].setValue(total);self.fields["thickness"].blockSignals(b)
        self.action.setIcon(composite_wall_icon() if kind=="composite" else wall_icon())
        self._update_structure_ui();self.defaults_changed()

    def layers_changed(self):
        if self._loading or self.structure.currentData()!="composite":return
        self.defaults["layers"]=self.layer_editor.layers();total=sum(float(x["thickness"]) for x in self.defaults["layers"]);self.defaults["thickness"]=total
        b=self.fields["thickness"].blockSignals(True);self.fields["thickness"].setValue(total);self.fields["thickness"].blockSignals(b)
        self.defaults_changed()

    def start_structure(self,kind):
        self._loading=True
        try:
            i=self.structure.findData(kind);self.structure.setCurrentIndex(i if i>=0 else 0)
            if kind=="composite" and not self.defaults.get("layers"):self.layer_editor.set_layers([],float(self.fields["thickness"].value()),self.material.currentData())
            self.defaults["structure"]=kind;self.defaults["layers"]=self.layer_editor.layers() if kind=="composite" else []
            if kind=="composite":self.defaults["thickness"]=sum(float(x["thickness"]) for x in self.defaults["layers"])
        finally:self._loading=False
        self.action.setIcon(composite_wall_icon() if kind=="composite" else wall_icon())
        self._update_structure_ui()
        # If the straight-wall tool is already active, changing simple/composite
        # must not reactivate/toggle the same host tool.  Reactivating an active
        # tool made the first click merely leave the previous mode; the second
        # click was then required to start the requested structure.
        if self.app.viewport.active_tool is self.tool:
            self._state_key = None
            self.refresh()
            self.message("Clique no início da parede. A cota de base define o plano horizontal.")
            self.app.viewport.setFocus()
        else:
            self.start_drawing()

    def values(self):
        for field in self.fields.values():
            field.interpretText()
        self.top_offset.interpretText()
        out = {key: field.value() for key, field in self.fields.items()}
        out["alignment"] = self.alignment.currentData()
        out["material_name"] = self.material.currentData()
        out["structure"] = self.structure.currentData() or "simple"
        out["layers"] = self.layer_editor.layers() if out["structure"]=="composite" else []
        if out["structure"]=="composite":out["thickness"]=sum(float(x["thickness"]) for x in out["layers"])
        current = read_wall(self.target) if self.target is not None else None
        out["openings"] = copy.deepcopy((current.get("openings",[]) if current is not None else self.defaults.get("openings",[])))
        if current is not None:
            out["base_profile"] = copy.deepcopy(current.get("base_profile", [0.0,0.0]))
            out["top_profile"] = copy.deepcopy(current.get("top_profile", [out["height"],out["height"]]))
            out["top_xy"] = copy.deepcopy(current.get("top_xy", [[0.0,0.0],[0.0,0.0]]))
        else:
            out["base_profile"] = [0.0,0.0]
            out["top_profile"] = [float(out["height"]),float(out["height"])]
            out["top_xy"] = [[0.0,0.0],[0.0,0.0]]
        out["base_level"] = self.base_level.currentData()
        top_name = self.top_level.currentData()
        if top_name is None:
            out["top_mode"] = "height"
            out["top_level"] = None
            out["top_offset"] = 0.0
        else:
            level = level_by_name(self.app, top_name)
            if level is None:
                raise WallError("O nível de topo selecionado não está mais disponível.")
            offset = float(self.top_offset.value())
            height = float(level["z"]) + offset - float(out["base"])
            if height < MIN_DIM:
                raise WallError("O nível de topo precisa ficar acima da base da parede.")
            out["height"] = height
            out["top_mode"] = "level"
            out["top_level"] = top_name
            out["top_offset"] = offset
        if current is None:
            out["base_profile"]=[0.0,0.0];out["top_profile"]=[float(out["height"]),float(out["height"])];out["top_xy"]=[[0.0,0.0],[0.0,0.0]]
        return validate(out)

    def defaults_changed(self, *_):
        if self._loading:
            return
        self._update_bound_height_field()
        if self.app.viewport.active_tool in (self.tool, self.curve_create_tool):
            # Creation mode: controls define the next wall / live preview.
            # Do not call interpretText from valueChanged (would recurse).
            self.defaults.update({key: field.value() for key, field in self.fields.items()
                                  if key != "length"})
            self.defaults["alignment"] = self.alignment.currentData()
            self.defaults["material_name"] = self.material.currentData()
            self.defaults["structure"] = self.structure.currentData() or "simple"
            self.defaults["layers"] = self.layer_editor.layers() if self.defaults["structure"]=="composite" else []
            if self.defaults["structure"]=="composite":self.defaults["thickness"]=sum(float(x["thickness"]) for x in self.defaults["layers"])
            self.defaults["openings"] = []
            self.defaults["base_profile"]=[0.0,0.0]
            self.defaults["top_profile"]=[float(self.defaults["height"]),float(self.defaults["height"])]
            self.defaults["top_xy"]=[[0.0,0.0],[0.0,0.0]]
            self.defaults["base_level"] = self.base_level.currentData()
            top_name = self.top_level.currentData()
            if top_name is None:
                self.defaults["top_mode"] = "height"
                self.defaults["top_level"] = None
                self.defaults["top_offset"] = 0.0
            else:
                level = level_by_name(self.app, top_name)
                if level is not None:
                    self.defaults["top_mode"] = "level"
                    self.defaults["top_level"] = top_name
                    self.defaults["top_offset"] = float(self.top_offset.value())
                    self.defaults["height"] = max(
                        MIN_DIM, float(level["z"]) + self.defaults["top_offset"] - self.defaults["base"])
                    self.defaults["top_profile"]=[float(self.defaults["height"]),float(self.defaults["height"])]
            if self.app.viewport.active_tool is self.tool:
                if self.tool.start_point is not None:
                    self.tool.start_point.setZ(self.defaults["base"])
                if self.tool.hover_point is not None:
                    self.tool.hover_point.setZ(self.defaults["base"])
            else:
                for name in ("first_point", "second_point", "hover_point"):
                    point = getattr(self.curve_create_tool, name, None)
                    if point is not None:
                        point.setZ(self.defaults["base"])
            self._loaded_key = ("create", id(None), tuple(sorted(self.defaults.items())))
            self.app.viewport.update()
            return

        # Edit mode: every committed spin-box/combo change edits the selected
        # wall immediately. QDoubleSpinBox keyboardTracking=False means typed
        # text commits on Enter/focus change, while arrow clicks commit at once.
        if self.target is not None:
            self.apply_changes()

    def preview_length(self, length):
        if self.app.viewport.active_tool not in (self.tool, self.curve_create_tool):
            return
        field = self.fields["length"]
        blocked = field.blockSignals(True)
        try:
            field.setValue(length)
        finally:
            field.blockSignals(blocked)

    def apply_changes(self):
        if self._loading:
            return
        try:
            scene = self.app.scene
            if self.target_scene is not scene or self.target is None:
                raise WallError("Selecione novamente a parede que deseja editar.")
            if selected_walls(scene) != [self.target]:
                raise WallError("A seleção mudou. Selecione uma única parede.")
            values = self.values()
            if values == read_wall(self.target):
                return
            cmd = EditWall(scene, self.target, values)
            self.app.viewport.history.execute(cmd)
            if self.app.viewport.history.last_error:
                raise WallError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed()
            self._state_key = None
            self.refresh()
            self.message("Parede atualizada.")
        except WallError as exc:
            self.message(str(exc), error=True)
        except Exception:
            log.exception("Wall update failed")
            self.message("Não foi possível atualizar a parede. Consulte o registro do IngeTrazo.", error=True)

    def message(self, text, error=False):
        shown = t(text)
        self.feedback.setText(shown)
        self.feedback.setStyleSheet("color: #c34a36;" if error else "")
        if text:
            # Interactive guidance belongs in the host status line as well as
            # the palette.  Tools already call controller.message() whenever
            # their stage changes, so this keeps creation/edit flows legible
            # without duplicating instructions in every mouse handler.
            self.app.viewport.flash_status(shown, 8000 if error else 15000)
