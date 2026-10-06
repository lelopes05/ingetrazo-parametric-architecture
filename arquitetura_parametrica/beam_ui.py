# SPDX-License-Identifier: GPL-3.0-or-later
"""Beam toolbar action, side palette and graphical axis handles."""
from __future__ import annotations
import logging, math
from PySide6.QtCore import QEvent,QPoint,QPointF,QRectF,QTimer,Qt
from PySide6.QtGui import QAction,QColor,QIcon,QPainter,QPen,QPixmap,QVector3D
from PySide6.QtWidgets import QComboBox,QFormLayout,QGridLayout,QLabel,QToolButton,QVBoxLayout,QWidget
from . import __version__
from .beam_commands import EditBeam
from .beam_edit import MoveBeamEndpointTool
from .beam_model import (ANCHOR_FACTORS,DEFAULTS,MAX_DIM,MIN_DIM,BeamError,beam_record,read_beam,
                         endpoints_world,reference_path_world,midpoint_world)
from .beam_tool import BeamTool
from .structure_edit import (MoveWholeStructureTool,BeamCurveTool,BeamVerticalCurveTool,
                             BeamInclineTool)
from .commands import root_edit_allowed
from .host import (BEAM_TOOL_KEY,BEAM_MOVE_FREE_TOOL_KEY,BEAM_MOVE_CONTINUE_TOOL_KEY,BEAM_MOVE_VERTICAL_TOOL_KEY,
                   BEAM_MOVE_TOOL_KEY,BEAM_CURVE_TOOL_KEY,BEAM_VERTICAL_CURVE_TOOL_KEY,
                   BEAM_INCLINE_TOOL_KEY,activate_beam,activate_select,
                   activate_beam_move_free,activate_beam_move_continue,activate_beam_move_vertical,activate_beam_move,
                   activate_beam_curve,activate_beam_vertical_curve,activate_beam_incline,
                   register_tool)
from .levels import available_levels,level_by_name
from .materials import material_names
from .profile_library import load_profiles, profile_by_id
from .i18n import t,ui_locale
from .widgets import FlexibleDoubleSpinBox as QDoubleSpinBox
from .icons import icon as pa_icon, set_symbol_icon
from .palette import RadialPalette

log=logging.getLogger("ingetrazo.plugins.arquitetura_parametrica.beam")

def beam_icon():
    return pa_icon("beam")


def selected_beams(scene):
    if getattr(scene,"edit_group",None) is not None:return []
    out=[]
    for item in scene.selection:
        g=getattr(item,"owner",None) or item
        if g in scene.groups and beam_record(g) is not None and g not in out:out.append(g)
    return out

class BeamController(QWidget):
    def __init__(self,app,wall_controller=None):
        super().__init__(app.window);self.app=app;self.wall_controller=wall_controller;self.defaults=dict(DEFAULTS)
        self.tool=BeamTool(self);self.move_free_tool=MoveBeamEndpointTool(self,"free");self.move_continue_tool=MoveBeamEndpointTool(self,"continue");self.move_vertical_tool=MoveBeamEndpointTool(self,"vertical")
        self.move_tool=MoveWholeStructureTool(self,"viga");self.curve_tool=BeamCurveTool(self);self.vertical_curve_tool=BeamVerticalCurveTool(self);self.incline_tool=BeamInclineTool(self)
        self.target=None;self._loading=False;self._queued=False;self._endpoint_group=None;self._endpoint_anchor=None;self._endpoint_is_endpoint=False
        self._make_panel();self._make_action();self._make_endpoint_palette();app.add_overlay(self.draw_overlay);app.viewport.installEventFilter(self)
        app.viewport.sceneVersionChanged.connect(self.schedule_refresh);self.schedule_refresh()
    def _spin(self,step=.01,minv=MIN_DIM,maxv=MAX_DIM):
        w=QDoubleSpinBox();w.setLocale(ui_locale());w.setDecimals(4);w.setRange(minv,maxv);w.setSingleStep(step);w.setSuffix(" m");w.setKeyboardTracking(False);w.valueChanged.connect(self.values_changed);return w
    def _make_panel(self):
        self.panel=QWidget();lay=QVBoxLayout(self.panel);lay.addWidget(QLabel(t("Viga")));form=QFormLayout();self.form=form;lay.addLayout(form)
        self.level=QComboBox();self.level.currentIndexChanged.connect(self.level_changed);form.addRow(t("Nível"),self.level)
        self.offset=self._spin(.05,-MAX_DIM,MAX_DIM);form.addRow(t("Cota / offset"),self.offset)
        self.section_type=QComboBox();self.section_type.addItem(t("Simples"),"simple");self.section_type.addItem(t("Perfil complexo"),"complex");self.section_type.currentIndexChanged.connect(self.section_type_changed);form.addRow(t("Seção"),self.section_type)
        self.profile=QComboBox();self.profile.addItem(t("Retangular"),"rect");self.profile.addItem(t("Circular"),"circle");self.profile.currentIndexChanged.connect(self.values_changed);form.addRow(t("Forma"),self.profile)
        self.complex_profile=QComboBox();self.complex_profile.currentIndexChanged.connect(self.values_changed);form.addRow(t("Perfil complexo"),self.complex_profile)
        self.length=self._spin(.10);form.addRow(t("Comprimento"),self.length)
        self.width=self._spin();form.addRow(t("Largura"),self.width);self.height=self._spin();form.addRow(t("Altura"),self.height);self.diameter=self._spin();form.addRow(t("Diâmetro"),self.diameter)
        self.inclination=QDoubleSpinBox();self.inclination.setLocale(ui_locale());self.inclination.setDecimals(2);self.inclination.setRange(-85,85);self.inclination.setSingleStep(1);self.inclination.setSuffix("°");self.inclination.setKeyboardTracking(False);self.inclination.valueChanged.connect(self.values_changed);form.addRow(t("Inclinação"),self.inclination)
        self.curvature=self._spin(.05,-MAX_DIM,MAX_DIM);form.addRow(t("Flecha horizontal"),self.curvature)
        self.vertical_curvature=self._spin(.05,-MAX_DIM,MAX_DIM);form.addRow(t("Flecha vertical"),self.vertical_curvature)
        self.rotation=QDoubleSpinBox();self.rotation.setLocale(ui_locale());self.rotation.setDecimals(2);self.rotation.setRange(-360,360);self.rotation.setSingleStep(5);self.rotation.setSuffix("°");self.rotation.setKeyboardTracking(False);self.rotation.valueChanged.connect(self.values_changed);form.addRow(t("Rotação"),self.rotation)
        self.material=QComboBox();self.material.currentIndexChanged.connect(self.values_changed);form.addRow(t("Material"),self.material)
        box=QWidget();grid=QGridLayout(box);grid.setContentsMargins(0,0,0,0);grid.setSpacing(2);self.anchor_buttons={}
        for r,row in enumerate((["tl","tc","tr"],["ml","mc","mr"],["bl","bc","br"])):
            for c,key in enumerate(row):
                b=QToolButton(box);b.setText("●");b.setCheckable(True);b.setAutoExclusive(True);b.setFixedSize(27,27);b.clicked.connect(lambda _=False,k=key:self.anchor_changed(k));grid.addWidget(b,r,c);self.anchor_buttons[key]=b
        form.addRow(t("Eixo de referência"),box)
        self.hint=QLabel();self.hint.setWordWrap(True);lay.addWidget(self.hint);self.feedback=QLabel();self.feedback.setWordWrap(True);lay.addWidget(self.feedback);lay.addStretch();ver=QLabel(f"{t('Vigas paramétricas')} · v{__version__}");ver.setStyleSheet("color:#777;font-size:9pt;");lay.addWidget(ver)
        self.dock=getattr(self.app.window,"_arquitetura_parametrica_master_dock",None)
        if self.dock is None:
            self.dock=self.app.add_panel(t("Viga"),self.panel,name="beam");self.dock.hide()
        self.refresh_level_options();self.refresh_material_options();self.refresh_complex_profile_options();self._load_fields(self.defaults)
    def _make_action(self):
        self.action=QAction(beam_icon(),t("Viga paramétrica"),self.app.window);self.action.setCheckable(True);self.action.setToolTip(t("Viga paramétrica\nComprimento, largura, altura, inclinação e curvaturas horizontal/vertical."));register_tool(self.app,self.tool,self.action,key=BEAM_TOOL_KEY);self.action.triggered.connect(self.start_drawing)
        register_tool(self.app,self.move_free_tool,key=BEAM_MOVE_FREE_TOOL_KEY);register_tool(self.app,self.move_continue_tool,key=BEAM_MOVE_CONTINUE_TOOL_KEY);register_tool(self.app,self.move_vertical_tool,key=BEAM_MOVE_VERTICAL_TOOL_KEY)
        register_tool(self.app,self.move_tool,key=BEAM_MOVE_TOOL_KEY);register_tool(self.app,self.curve_tool,key=BEAM_CURVE_TOOL_KEY);register_tool(self.app,self.vertical_curve_tool,key=BEAM_VERTICAL_CURVE_TOOL_KEY);register_tool(self.app,self.incline_tool,key=BEAM_INCLINE_TOOL_KEY)
        if self.wall_controller is not None and hasattr(self.wall_controller,"toolbar"):
            self.wall_controller.toolbar.addAction(self.action);self.wall_controller.fit_toolbar();m=getattr(self.wall_controller,"arch_menu",None)
            if m is not None:m.addAction(self.action)
        else:
            m=self.app.add_menu(t("Ferramentas arquitetônicas"));m.addAction(self.action) if m is not None else None
    def _make_endpoint_palette(self):
        self.endpoint_palette=RadialPalette(self.app.window,popup=False,role="edit");row=self.endpoint_palette.row
        def add(sym,tip,slot):
            b=QToolButton(self.endpoint_palette);set_symbol_icon(b, sym);b.setToolTip(t(tip));b.setFixedSize(34,34);f=b.font();f.setPointSize(16);b.setFont(f);b.clicked.connect(slot);row.addWidget(b);return b
        self.endpoint_free_btn=add("✥","Mover extremo livremente no plano horizontal.",self.begin_endpoint_free)
        self.endpoint_continue_btn=add("→","Prolongar ou encurtar a viga no mesmo eixo.",self.begin_endpoint_continue)
        self.endpoint_vertical_btn=add("↕","Mover este extremo na vertical e definir a inclinação a partir dele.",self.begin_endpoint_vertical)
        self.endpoint_move_btn=add("↔","Mover a viga inteira no plano horizontal.",self.begin_move_whole)
        self.endpoint_curve_btn=add("⌒","Curvar/endireitar a viga no plano horizontal.",self.begin_curve)
        self.endpoint_vcurve_btn=add("∪","Curvar/endireitar a viga no plano vertical.",self.begin_vertical_curve)
        self.endpoint_incline_btn=add("∠","Alterar graficamente a inclinação da viga.",self.begin_incline)
        self.endpoint_palette.hide()
    def hide_endpoint_palette(self):
        self.endpoint_palette.hide();self._endpoint_group=None;self._endpoint_anchor=None;self._endpoint_is_endpoint=False
    def show_endpoint_palette(self,pos,group,anchor,is_endpoint=True):
        self._endpoint_group=group;self._endpoint_anchor=QVector3D(anchor);self._endpoint_is_endpoint=bool(is_endpoint)
        self.endpoint_free_btn.setEnabled(self._endpoint_is_endpoint);self.endpoint_continue_btn.setEnabled(self._endpoint_is_endpoint);self.endpoint_vertical_btn.setEnabled(self._endpoint_is_endpoint)
        self.endpoint_palette.show_at(pos)
    def begin_endpoint_free(self):
        if self._endpoint_group is None:return
        g,a=self._endpoint_group,QVector3D(self._endpoint_anchor);self.hide_endpoint_palette();self.move_free_tool.prepare(g,a);activate_beam_move_free(self.app);self.app.viewport.setFocus()
    def begin_endpoint_continue(self):
        if self._endpoint_group is None:return
        g,a=self._endpoint_group,QVector3D(self._endpoint_anchor);self.hide_endpoint_palette();self.move_continue_tool.prepare(g,a);activate_beam_move_continue(self.app);self.app.viewport.setFocus()
    def begin_endpoint_vertical(self):
        if self._endpoint_group is None:return
        g,a=self._endpoint_group,QVector3D(self._endpoint_anchor);self.hide_endpoint_palette();self.move_vertical_tool.prepare(g,a);activate_beam_move_vertical(self.app);self.app.viewport.setFocus()
    def begin_move_whole(self):
        if self._endpoint_group is None:return
        g,a=self._endpoint_group,QVector3D(self._endpoint_anchor);self.hide_endpoint_palette();self.move_tool.prepare(g,a);activate_beam_move(self.app);self.app.viewport.setFocus()
    def begin_curve(self):
        if self._endpoint_group is None:return
        g=self._endpoint_group;self.hide_endpoint_palette();self.curve_tool.prepare(g);activate_beam_curve(self.app);self.app.viewport.setFocus()
    def begin_vertical_curve(self):
        if self._endpoint_group is None:return
        g=self._endpoint_group;self.hide_endpoint_palette();self.vertical_curve_tool.prepare(g);activate_beam_vertical_curve(self.app);self.app.viewport.setFocus()
    def begin_incline(self):
        if self._endpoint_group is None:return
        g=self._endpoint_group;a=QVector3D(self._endpoint_anchor);self.hide_endpoint_palette();self.incline_tool.prepare(g,a);activate_beam_incline(self.app);self.app.viewport.setFocus()
    def refresh_level_options(self):
        cur=self.level.currentData() if self.level.count() else None;self.level.blockSignals(True);self.level.clear();self.level.addItem(t("Cota livre"),None)
        for lv in available_levels(self.app):self.level.addItem(f"{lv['name']}  ({lv['z']:+.2f} m)",lv['name'])
        i=self.level.findData(cur);self.level.setCurrentIndex(i if i>=0 else 0);self.level.blockSignals(False)
    def refresh_material_options(self):
        cur=self.material.currentData() if self.material.count() else self.defaults.get("material_name");names=material_names(self.app.scene);key=tuple(names)
        if getattr(self,"_material_options_key",None)==key:return
        self.material.blockSignals(True);self.material.clear();self.material.addItem(t("Padrão"),None)
        for name in names:self.material.addItem(name,name)
        i=self.material.findData(cur);self.material.setCurrentIndex(i if i>=0 else 0);self.material.blockSignals(False);self._material_options_key=key
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

    def resolved_defaults(self):
        p=dict(self.defaults)
        if p.get("base_level"):
            lv=level_by_name(self.app,p["base_level"])
            if lv is not None:p["base_z"]=float(lv["z"])+float(p.get("base_offset",0))
        return p
    def current_base_z(self):return float(self.resolved_defaults()["base_z"])
    def _load_fields(self,p):
        self._loading=True
        try:
            self.defaults.update(p);name=p.get("base_level");i=self.level.findData(name);self.level.setCurrentIndex(i if i>=0 else 0);self.offset.setValue(p.get("base_offset",0) if name else p.get("base_z",0));self.refresh_complex_profile_options(p.get("profile_ref"),p.get("profile_data"));self.section_type.setCurrentIndex(max(0,self.section_type.findData(p.get("section_type","simple"))));self.profile.setCurrentIndex(max(0,self.profile.findData(p.get("profile","rect"))));ci=self.complex_profile.findData(p.get("profile_ref"));self.complex_profile.setCurrentIndex(ci if ci>=0 else 0);self.length.setValue(p.get("length",1.0));self.width.setValue(p.get("width",.2));self.height.setValue(p.get("height",p.get("depth",.4)));self.diameter.setValue(p.get("diameter",.2));self.inclination.setValue(p.get("inclination",0.0));self.curvature.setValue(p.get("curvature",0.0));self.vertical_curvature.setValue(p.get("vertical_curvature",0.0));self.rotation.setValue(p.get("rotation",0));mi=self.material.findData(p.get("material_name"));self.material.setCurrentIndex(mi if mi>=0 else 0)
            for k,b in self.anchor_buttons.items():b.setChecked(k==p.get("anchor","mc"))
            self._update_section_widgets(p);curved=abs(float(p.get("curvature",0.0)))>1e-8 or abs(float(p.get("vertical_curvature",0.0)))>1e-8;self.length.setReadOnly(curved);self.length.setToolTip(t("Comprimento do eixo curvo; edite extremos/flechas.") if curved else t("O início permanece fixo ao editar numericamente."))
        finally:self._loading=False
    def _set_form_field_visible(self, widget, visible):
        visible=bool(visible);widget.setVisible(visible)
        try:
            label=self.form.labelForField(widget)
            if label is not None:label.setVisible(visible)
        except Exception:pass
    def _update_section_widgets(self,p=None):
        p=p or self.defaults;simple=p.get("section_type","simple")=="simple";shape=p.get("profile","rect")
        self._set_form_field_visible(self.profile,simple)
        self._set_form_field_visible(self.complex_profile,not simple)
        self._set_form_field_visible(self.width,simple and shape=="rect")
        self._set_form_field_visible(self.height,simple and shape=="rect")
        self._set_form_field_visible(self.diameter,simple and shape=="circle")
    def level_changed(self,*_):
        if self._loading:return
        old=self.resolved_defaults();z=float(old["base_z"]);name=self.level.currentData();self.defaults["base_level"]=name
        if name:
            lv=level_by_name(self.app,name);self.defaults["base_offset"]=z-float(lv["z"]) if lv else 0;self.offset.setValue(self.defaults["base_offset"])
        else:self.defaults["base_z"]=z;self.defaults["base_offset"]=0;self.offset.setValue(z)
        self._apply()
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
    def anchor_changed(self,key):
        if self._loading:return
        self.defaults["anchor"]=key;self._apply()
    def values_changed(self,*_):
        if self._loading:return
        ref=self.complex_profile.currentData() if (self.section_type.currentData() or "simple")=="complex" else None
        embedded=self.defaults.get("profile_data") if ref and self.defaults.get("profile_ref")==ref else profile_by_id(ref)
        self.defaults.update(section_type=self.section_type.currentData() or "simple",profile_ref=ref,profile_data=embedded,profile=self.profile.currentData(),length=float(self.length.value()),width=float(self.width.value()),height=float(self.height.value()),depth=float(self.height.value()),diameter=float(self.diameter.value()),inclination=float(self.inclination.value()),curvature=float(self.curvature.value()),vertical_curvature=float(self.vertical_curvature.value()),rotation=float(self.rotation.value()),material_name=self.material.currentData())
        if self.defaults.get("base_level"):self.defaults["base_offset"]=float(self.offset.value())
        else:self.defaults["base_z"]=float(self.offset.value())
        self._update_section_widgets(self.defaults);self._apply()
    def _apply(self):
        if self.target is None or self._loading:return
        try:
            self.app.viewport.history.execute(EditBeam(self.app.scene,self.target,self.resolved_defaults()))
            if self.app.viewport.history.last_error:raise BeamError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed()
        except BeamError as exc:self.message(str(exc),True)
    def _sync_levels(self):
        changed=0
        for g in list(self.app.scene.groups):
            rec=beam_record(g)
            if rec is None or not rec.get("base_level"):continue
            lv=level_by_name(self.app,rec.get("base_level"))
            if lv is None:continue
            try:
                old=read_beam(g);z=float(lv["z"])+float(rec.get("base_offset",0.0))
                if abs(z-old["base_z"])<=1e-7:continue
                EditBeam(self.app.scene,g,dict(old,base_z=z)).do(self.app.scene);changed+=1
            except BeamError:continue
        return changed
    def schedule_refresh(self,*_):
        if self._queued:return
        self._queued=True;QTimer.singleShot(0,self.refresh)
    def refresh(self):
        self._queued=False
        try:self._sync_levels()
        except Exception:log.exception("beam level sync failed")
        self.refresh_level_options();self.refresh_material_options();self.refresh_complex_profile_options();bs=selected_beams(self.app.scene);self.target=bs[0] if len(bs)==1 else None
        if self.target is not None:
            try:self._load_fields(read_beam(self.target));self.hint.setText(t("Clique no eixo para mover, inclinar ou curvar a viga horizontal/verticalmente; nas pontas também é possível mover/prolongar. Inclinação e flechas aceitam valor numérico."));self.app.show_panel(self.dock)
            except BeamError as exc:self.message(str(exc),True)
        elif self.app.viewport.active_tool is self.tool:self._load_fields(self.resolved_defaults());self.hint.setText(t("Clique no início e no fim da viga. A inclinação e as curvaturas usam os valores da paleta."));self.app.show_panel(self.dock)
        self.app.viewport.update()
    def start_drawing(self,*_):
        try:
            root_edit_allowed(self.app.scene)
            if self.defaults.get("section_type")=="complex" and not self.defaults.get("profile_ref"):raise BeamError("Escolha um Perfil Complexo antes de inserir a viga.")
            if self.app.workspace() is not None:raise BeamError("Volte ao modelo para inserir vigas.")
        except Exception as exc:self.action.setChecked(False);self.app.viewport.flash_status(str(exc),6000);return
        self.app.scene.clear_selection();activate_beam(self.app);self.schedule_refresh();self.message("Clique no início da viga.");self.app.viewport.setFocus()
    def stop_drawing(self):activate_select(self.app);self.action.setChecked(False);self.schedule_refresh()
    def return_to_select(self):activate_select(self.app);self.schedule_refresh();self.app.viewport.setFocus()
    def message(self,text,error=False):self.feedback.setText(t(text));self.feedback.setStyleSheet("color:#b00020;" if error else "")
    @staticmethod
    def _seg_distance(px,py,a,b):
        ax,ay=a;bx,by=b;dx,dy=bx-ax,by-ay;den=dx*dx+dy*dy
        if den<=1e-9:return math.hypot(px-ax,py-ay)
        u=max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/den));x=ax+u*dx;y=ay+u*dy
        return math.hypot(px-x,py-y)
    def eventFilter(self,obj,event):
        if obj is self.app.viewport and event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
            # Any viewport click dismisses the old radial first. If the click is
            # another reference hit, a new context is shown below; otherwise the
            # native Select tool can clear/change selection normally.
            if self.endpoint_palette.isVisible():self.hide_endpoint_palette()
            if event.modifiers()==Qt.NoModifier:
                vp=self.app.viewport;bs=selected_beams(self.app.scene);select_tool=self.app.window._tools.get("select")
                if vp.active_tool is select_tool and len(bs)==1:
                    try:a,b=endpoints_world(bs[0]);path=reference_path_world(bs[0])
                    except BeamError:return super().eventFilter(obj,event)
                    px,py=event.position().x(),event.position().y();threshold=max(9.0,float(getattr(vp,"snap_threshold_px",10.0)));best=None
                    for q in (a,b):
                        sp=vp._world_to_pixel(q)
                        if sp is None:continue
                        d=math.hypot(px-sp[0],py-sp[1])
                        if d<=threshold and (best is None or d<best[0]):best=(d,q)
                    gp=vp.mapToGlobal(QPoint(int(px),int(py)))
                    if best is not None:self.show_endpoint_palette(gp,bs[0],best[1],True);return True
                    pixels=[vp._world_to_pixel(q) for q in path];pixels=[q for q in pixels if q is not None]
                    if len(pixels)>=2 and min(self._seg_distance(px,py,x,y) for x,y in zip(pixels,pixels[1:]))<=threshold:
                        self.show_endpoint_palette(gp,bs[0],midpoint_world(bs[0]),False);return True
        return super().eventFilter(obj,event)
    def draw_overlay(self,viewport,painter):
        bs=selected_beams(self.app.scene)
        if not bs:return
        painter.setPen(QPen(QColor("#d07a28"),1.8,Qt.DashLine));painter.setBrush(QColor("white"))
        for g in bs:
            try:path=reference_path_world(g);a,b=endpoints_world(g)
            except BeamError:continue
            pix=[viewport._world_to_pixel(q) for q in path]
            for x,y in zip(pix,pix[1:]):
                if x is not None and y is not None:painter.drawLine(QPointF(x[0],x[1]),QPointF(y[0],y[1]))
            for q in (viewport._world_to_pixel(a),viewport._world_to_pixel(b)):
                if q is not None:painter.drawEllipse(QRectF(q[0]-4,q[1]-4,8,8))
