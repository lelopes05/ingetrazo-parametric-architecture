# SPDX-License-Identifier: GPL-3.0-or-later
"""2D complex-profile editor built on IngeTrazo's native drawing workspace.

No parallel CAD stack lives here: the extension parks the BIM model, presents a
normal IngeTrazo Scene in a top/parallel camera and lets Line/Arc/Circle/Curve
Tools/etc. build the section.  We only validate the resulting closed contours,
choose an insertion origin and keep reusable user favourites.
"""
from __future__ import annotations

import copy
import math
import uuid

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QVector3D
from PySide6.QtWidgets import (QAbstractItemView, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from core.history import History
from core.scene import Scene
from tools.base import Tool

from .i18n import t, ui_locale
from .profile_library import (delete_profile, duplicate_profile, load_profiles,
                              upsert_profile)
from .widgets import FlexibleDoubleSpinBox as QDoubleSpinBox
from .icons import icon as pa_icon, set_symbol_icon

PROFILE_ORIGIN_TOOL_KEY = "arquitetura_parametrica_profile_origin"
_EPS = 1.0e-7


def profile_icon():
    return pa_icon("profile")


def _doc_version(scene):
    return int(getattr(scene,"version",0))-int(getattr(scene,"view_version",0))


def _xy(p): return (float(p.x()),float(p.y()))


def _signed_area(points):
    return 0.5*sum(points[i][0]*points[(i+1)%len(points)][1]-
                   points[(i+1)%len(points)][0]*points[i][1]
                   for i in range(len(points)))


def _point_in_polygon(pt, poly):
    x,y=pt; inside=False
    j=len(poly)-1
    for i in range(len(poly)):
        xi,yi=poly[i]; xj,yj=poly[j]
        if ((yi>y)!=(yj>y)):
            den=(yj-yi)
            xhit=(xj-xi)*(y-yi)/(den if abs(den)>1e-20 else 1e-20)+xi
            if x < xhit: inside=not inside
        j=i
    return inside


def _orient(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _segment_intersection(a,b,c,d):
    # Proper crossing only. Shared adjacent vertices are checked separately by
    # topology and should not make a valid closed profile fail validation.
    o1=_orient(a,b,c);o2=_orient(a,b,d);o3=_orient(c,d,a);o4=_orient(c,d,b)
    return ((o1>_EPS and o2<-_EPS) or (o1<-_EPS and o2>_EPS)) and \
           ((o3>_EPS and o4<-_EPS) or (o3<-_EPS and o4>_EPS))


def _profile_loops(scene, anchor=(0.0,0.0)):
    """Extract closed loose-edge contours from a 2D profile workspace.

    Curves remain curve entities semantically: sampled IngeTrazo edges sharing a
    curve id get the same compact local curve number in the saved profile.  A
    future path-sweep can therefore keep them smooth without depending on a
    session-specific Mesh curve id.
    """
    if getattr(scene,"groups",None):
        raise ValueError("O perfil deve ser desenhado como geometria 2D solta; exploda/remova grupos antes de salvar.")
    mesh=getattr(scene,"loose_mesh",None) or scene.mesh
    edges=list(getattr(mesh,"edges",()) or ())
    if not edges:
        raise ValueError("Desenhe ao menos um contorno fechado antes de salvar o perfil.")
    vertices=set()
    adjacency={}
    for e in edges:
        if abs(float(e.a.z()))>1e-5 or abs(float(e.b.z()))>1e-5:
            raise ValueError("O Perfil Complexo precisa permanecer no plano 2D do editor.")
        vertices.update((e.v0,e.v1))
        adjacency.setdefault(e.v0,[]).append(e); adjacency.setdefault(e.v1,[]).append(e)
    bad=[v for v in vertices if len(adjacency.get(v,()))!=2]
    if bad:
        raise ValueError("Existem linhas abertas, ramificações ou encontros em T. Cada contorno do perfil deve ser fechado.")

    loops=[]; unvisited=set(edges); curve_map={}; next_curve=1
    while unvisited:
        first=next(iter(unvisited)); start=first.v0; cur=start; edge=first
        pts=[]; flags=[]; guard=0
        while True:
            guard+=1
            if guard>len(edges)+2: raise ValueError("Não foi possível ordenar um dos contornos do perfil.")
            pts.append(_xy(cur.position))
            cid=getattr(edge,"curve",None)
            if cid is not None and cid not in curve_map:
                curve_map[cid]=next_curve; next_curve+=1
            flags.append({"curve":curve_map.get(cid),"soft":bool(getattr(edge,"soft",False))})
            unvisited.discard(edge)
            nxt=edge.other(cur)
            if nxt is start: break
            candidates=[e for e in adjacency[nxt] if e is not edge]
            if len(candidates)!=1: raise ValueError("Contorno ambíguo no perfil.")
            cur,edge=nxt,candidates[0]
        if len(pts)<3 or abs(_signed_area(pts))<1e-10:
            raise ValueError("Há um contorno degenerado ou sem área no perfil.")
        loops.append({"points":pts,"edges":flags})

    # Reject sampled self-crossings. Curved entities arrive already tessellated,
    # so this also catches a self-crossing spline/arc approximation.
    all_segments=[]
    for li,L in enumerate(loops):
        P=L["points"]
        for i in range(len(P)):
            all_segments.append((li,i,P[i],P[(i+1)%len(P)]))
    for a in range(len(all_segments)):
        la,ia,p0,p1=all_segments[a]
        for b in range(a+1,len(all_segments)):
            lb,ib,q0,q1=all_segments[b]
            if la==lb:
                n=len(loops[la]["points"])
                if ib==ia or ib==(ia+1)%n or ia==(ib+1)%n: continue
            if _segment_intersection(p0,p1,q0,q1):
                raise ValueError("O perfil possui contornos que se cruzam.")

    # Nesting parity determines holes. Multiple separate outer islands remain
    # legal; profile-by-path may sweep each island into one body later.
    for i,L in enumerate(loops):
        test=L["points"][0]; depth=0; ai=abs(_signed_area(L["points"]))
        for j,O in enumerate(loops):
            if i==j or abs(_signed_area(O["points"]))<=ai: continue
            if _point_in_polygon(test,O["points"]): depth+=1
        L["hole"]=(depth%2)==1

    ax,ay=float(anchor[0]),float(anchor[1])
    xs=[];ys=[]
    for L in loops:
        rel=[]
        for x,y in L["points"]:
            rel.append([x-ax,y-ay]);xs.append(x-ax);ys.append(y-ay)
        L["points"]=rel
    return loops,{"width":max(xs)-min(xs),"height":max(ys)-min(ys)}


def _populate_scene(scene, profile):
    """Recreate a saved profile as native IngeTrazo edges for editing."""
    curve_ids={}
    mesh=scene.mesh
    for loop in profile.get("loops",[]):
        pts=loop.get("points",[]); flags=loop.get("edges",[])
        if len(pts)<3: continue
        for i,p in enumerate(pts):
            q=pts[(i+1)%len(pts)]
            e=mesh.add_edge(QVector3D(float(p[0]),float(p[1]),0.0),
                            QVector3D(float(q[0]),float(q[1]),0.0))
            f=flags[i] if i<len(flags) and isinstance(flags[i],dict) else {}
            local=f.get("curve")
            if local is not None:
                if local not in curve_ids:
                    curve_ids[local]=mesh.next_curve_id()
                e.curve=curve_ids[local]
            e.soft=bool(f.get("soft",False))
    if profile.get("loops"):
        scene.version+=1
        # Native tools normally rebuild planar faces as contours close. Saved
        # profiles are reconstructed before a tool runs, so ask the same core
        # command to derive their faces now. Failure is harmless for editing;
        # validation still uses the edges.
        try:
            from core.history import RebuildPlanarFacesCommand
            RebuildPlanarFacesCommand().do(scene)
        except Exception:
            pass


class ProfileOriginTool(Tool):
    name="Profile origin"
    description="Choose the insertion/origin point of the complex profile."
    shortcut=None
    uses_snap=True
    def __init__(self,controller): self.controller=controller
    def on_activate(self,viewport): viewport.flash_status("Clique no ponto de origem do perfil.",3500)
    def on_deactivate(self,viewport): pass
    def on_click(self,ctx):
        if not self.controller.is_profile_workspace(): return
        self.controller.set_anchor(float(ctx.world.x()),float(ctx.world.y()))
        self.controller.app.window._activate_tool("select")


class ProfileWorkspace:
    def __init__(self,controller,profile=None):
        self.controller=controller;self.profile_id=(profile or {}).get("id")
        self.profile_name=(profile or {}).get("name") or "Novo Perfil"
        self.profile_folder=(profile or {}).get("folder") or "Meus Perfis"
        self.scene=Scene()
        # Respect the project's unit/display choices while the model is parked.
        model=controller.app.scene
        self.scene.units=copy.deepcopy(getattr(model,"units",self.scene.units))
        self.scene.dimension_style=copy.deepcopy(getattr(model,"dimension_style",self.scene.dimension_style))
        if profile: _populate_scene(self.scene,profile)
        self.history=History(self.scene)
        self.anchor=[0.0,0.0]
        self.camera={"target":[0.0,0.0,0.0],"distance":1.5,
                     "yaw":math.radians(-90.0),"pitch":math.radians(90.0),
                     "fov_deg":45.0,"perspective":False,"two_point":False}
        # Keep all native/extension drawing helpers available. Architecture's
        # own 3D creators already refuse to run while a workspace is active.
        self.allowed_tools=None
        self._saved_version=_doc_version(self.scene);self._saved_anchor=list(self.anchor);self._saved_name=self.profile_name;self._saved_folder=self.profile_folder
        self._force_leave=False
    def title(self): return f"Perfil Complexo — {self.profile_name}"
    def is_dirty(self): return (_doc_version(self.scene)!=self._saved_version or
                                list(self.anchor)!=self._saved_anchor or
                                self.profile_name!=self._saved_name or self.profile_folder!=self._saved_folder)
    def mark_clean(self):
        self._saved_version=_doc_version(self.scene);self._saved_anchor=list(self.anchor);self._saved_name=self.profile_name;self._saved_folder=self.profile_folder
    def save(self): return bool(self.controller.save_workspace(leave=False))
    def save_as(self): return self.save()
    def confirm_leave(self):
        if self._force_leave or not self.is_dirty(): return True
        box=QMessageBox(self.controller.app.window);box.setWindowTitle(t("Perfil Complexo"))
        box.setText(t("Salvar as alterações deste perfil antes de sair?"))
        box.setStandardButtons(QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
        answer=box.exec()
        if answer==QMessageBox.Cancel:return False
        if answer==QMessageBox.Save:return bool(self.controller.save_workspace(leave=False))
        return True
    def new(self):
        if not self.confirm_leave():return
        self.scene.clear();self.history.clear();self.profile_id=None;self.profile_name="Novo Perfil";self.profile_folder="Meus Perfis";self.anchor=[0.0,0.0];self.mark_clean()
        self.controller.sync_workspace_ui();self.controller.app.viewport.notify_scene_changed()
    def left(self): self.controller.workspace_left(self)


class ComplexProfileController(QObject):
    def __init__(self,app,wall_controller=None):
        super().__init__(app.window);self.app=app;self.wall_controller=wall_controller
        self._ws=None;self.origin_tool=ProfileOriginTool(self)
        app.window._tools[PROFILE_ORIGIN_TOOL_KEY]=self.origin_tool
        self._make_panel();self._make_action();app.add_overlay(self.draw_origin_overlay)
        app.viewport.sceneVersionChanged.connect(lambda _v:self._workspace_scene_changed())
        self.refresh_library()

    def _make_panel(self):
        self.panel=QWidget();lay=QVBoxLayout(self.panel);lay.setContentsMargins(6,6,6,6)
        self.heading=QLabel(t("Perfis Complexos"));lay.addWidget(self.heading)
        self.library_widget=QWidget();lb=QVBoxLayout(self.library_widget);lb.setContentsMargins(0,0,0,0)
        self.list=QTreeWidget();self.list.setHeaderHidden(True);self.list.setSelectionMode(QAbstractItemView.SingleSelection);self.list.itemDoubleClicked.connect(lambda _i,_c=0:self.edit_selected());lb.addWidget(self.list)
        row=QHBoxLayout();self.new_btn=QPushButton(t("Novo"));self.edit_btn=QPushButton(t("Editar"));self.dup_btn=QToolButton();self.dup_btn.setText("⧉");self.dup_btn.setToolTip(t("Duplicar perfil"));self.del_btn=QToolButton();set_symbol_icon(self.del_btn,"⌫",18);self.del_btn.setToolTip(t("Excluir perfil"))
        self.new_btn.clicked.connect(self.new_profile);self.edit_btn.clicked.connect(self.edit_selected);self.dup_btn.clicked.connect(self.duplicate_selected);self.del_btn.clicked.connect(self.delete_selected)
        for w in (self.new_btn,self.edit_btn,self.dup_btn,self.del_btn):row.addWidget(w)
        lb.addLayout(row);self.library_help=QLabel(t("Perfis incluídos vêm organizados por catálogo. Perfis pessoais podem usar qualquer pasta e ficam disponíveis em todos os projetos."));self.library_help.setWordWrap(True);lb.addWidget(self.library_help);lay.addWidget(self.library_widget)

        self.editor_widget=QWidget();eb=QVBoxLayout(self.editor_widget);eb.setContentsMargins(0,0,0,0)
        form=QFormLayout();self.name=QLineEdit();self.name.textChanged.connect(self.name_changed);form.addRow(t("Nome"),self.name)
        self.folder=QLineEdit();self.folder.setPlaceholderText("Meus Perfis / Categoria");self.folder.textChanged.connect(self.folder_changed);form.addRow(t("Pasta"),self.folder)
        self.anchor_x=QDoubleSpinBox();self.anchor_y=QDoubleSpinBox()
        for f in (self.anchor_x,self.anchor_y):f.setLocale(ui_locale());f.setDecimals(4);f.setRange(-10000,10000);f.setSingleStep(.01);f.setSuffix(" m");f.setKeyboardTracking(False);f.valueChanged.connect(self.anchor_numeric_changed)
        form.addRow(t("Origem X"),self.anchor_x);form.addRow(t("Origem Y"),self.anchor_y);eb.addLayout(form)
        orow=QHBoxLayout();self.pick_origin=QPushButton(t("Definir origem no desenho"));self.pick_origin.clicked.connect(self.begin_pick_origin);orow.addWidget(self.pick_origin);eb.addLayout(orow)
        self.editor_hint=QLabel(t("Desenhe no plano 2D usando as ferramentas normais do IngeTrazo. Linhas, arcos, círculos e Curve Tools podem compor contornos fechados; contornos internos viram vazios."));self.editor_hint.setWordWrap(True);eb.addWidget(self.editor_hint)
        brow=QHBoxLayout();self.cancel_btn=QPushButton(t("Cancelar"));self.save_btn=QPushButton(t("Salvar Perfil"));self.cancel_btn.clicked.connect(self.cancel_workspace);self.save_btn.clicked.connect(lambda:self.save_workspace(leave=True));brow.addWidget(self.cancel_btn);brow.addWidget(self.save_btn);eb.addLayout(brow)
        self.feedback=QLabel();self.feedback.setWordWrap(True);eb.addWidget(self.feedback);lay.addWidget(self.editor_widget);self.editor_widget.hide();lay.addStretch()
        self.dock=getattr(self.app.window,"_arquitetura_parametrica_master_dock",None)
        if self.dock is None:
            self.dock=self.app.add_panel(t("Perfis"),self.panel,name="profiles");self.dock.hide()

    def _make_action(self):
        self.action=QAction(profile_icon(),t("Perfil Complexo"),self.app.window);self.action.setToolTip(t("Criar e editar perfis 2D reutilizáveis."));self.action.triggered.connect(self.show_library)
        if self.wall_controller is not None and hasattr(self.wall_controller,"toolbar"):
            self.wall_controller.toolbar.addAction(self.action);self.wall_controller.fit_toolbar()
            menu=getattr(self.wall_controller,"arch_menu",None)
            if menu is not None:
                menu.addSeparator();menu.addAction(self.action)
        else:
            self.app.add_menu_action(t("Perfil Complexo…"),self.show_library,tip=t("Criar e editar perfis 2D reutilizáveis."))

    def show_library(self,*_):
        if self.is_profile_workspace():self.sync_workspace_ui()
        else:self.refresh_library()
        self.app.show_panel(self.dock)

    def refresh_library(self):
        if self.is_profile_workspace():return
        profiles=load_profiles();selected=self.selected_id();self.list.clear();folders={}
        def folder_item(path):
            parent=None;key=""
            for part in [x.strip() for x in str(path or "Meus Perfis").split("/") if x.strip()]:
                key=(key+" / "+part).strip(" /")
                if key not in folders:
                    item=QTreeWidgetItem([part]);item.setData(0,Qt.UserRole,None)
                    font=item.font(0);font.setBold(True);item.setFont(0,font)
                    (parent.addChild(item) if parent is not None else self.list.addTopLevelItem(item));folders[key]=item
                parent=folders[key]
            return parent
        selected_item=None
        for p in sorted(profiles,key=lambda x:(str(x.get("folder") or "").casefold(),str(x.get("name") or "").casefold())):
            b=p.get("bounds",{});w=float(b.get("width",0));h=float(b.get("height",0));parent=folder_item(p.get("folder"))
            suffix="  · catálogo" if p.get("builtin") else ""
            label=f"{p['name']}   ·   {w:.3f} × {h:.3f} m{suffix}"
            item=QTreeWidgetItem([label]);item.setData(0,Qt.UserRole,p["id"]);item.setToolTip(0,(p.get("source") or "Perfil pessoal")+(f" · {p.get('catalog')}" if p.get("catalog") else ""))
            if parent is not None:parent.addChild(item)
            else:self.list.addTopLevelItem(item)
            if p["id"]==selected:selected_item=item
        self.list.expandToDepth(1)
        if selected_item is not None:self.list.setCurrentItem(selected_item);self.list.scrollToItem(selected_item)
        self.library_widget.show();self.editor_widget.hide();self.heading.setText(t("Perfis Complexos"));self._selection_state()
        try:self.list.currentItemChanged.disconnect(self._selection_state)
        except Exception:pass
        self.list.currentItemChanged.connect(self._selection_state)
    def _selection_state(self,*_):
        p=self.selected_profile();on=p is not None;self.edit_btn.setEnabled(on);self.dup_btn.setEnabled(on);self.del_btn.setEnabled(on and not p.get("readonly",False));self.edit_btn.setText(t("Personalizar") if on and p.get("readonly",False) else t("Editar"))
    def selected_id(self):
        item=self.list.currentItem() if hasattr(self,"list") else None
        return item.data(0,Qt.UserRole) if item is not None else None
    def selected_profile(self):
        pid=self.selected_id();return next((p for p in load_profiles() if p.get("id")==pid),None)

    def _notify_consumers(self):
        for attr in ("_arquitetura_parametrica_beam_controller","_arquitetura_parametrica_column_controller"):
            ctrl=getattr(self.app.window,attr,None)
            if ctrl is not None and hasattr(ctrl,"refresh_complex_profile_options"):
                try:ctrl.refresh_complex_profile_options();ctrl.schedule_refresh()
                except Exception:pass

    def new_profile(self): self._enter_profile(None)
    def edit_selected(self):
        p=self.selected_profile()
        if p is None:return
        if p.get("readonly",False):
            p=duplicate_profile(p["id"]);self.refresh_library()
            if p is None:return
        self._enter_profile(p)
    def duplicate_selected(self):
        pid=self.selected_id()
        if pid and duplicate_profile(pid):self.refresh_library();self._notify_consumers()
    def delete_selected(self):
        p=self.selected_profile()
        if p is None or p.get("readonly",False):return
        ans=QMessageBox.question(self.app.window,t("Excluir perfil"),t(f"Excluir ‘{p['name']}’?"),QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if ans==QMessageBox.Yes:delete_profile(p["id"]);self.refresh_library();self._notify_consumers()

    def _enter_profile(self,profile):
        if self.app.workspace() is not None:
            self.app.viewport.flash_status(t("Saia do workspace atual antes de editar um perfil."),5000);return
        ws=ProfileWorkspace(self,copy.deepcopy(profile) if profile else None)
        if not self.app.enter_workspace(ws):return
        self._ws=ws;self.sync_workspace_ui();self.app.show_panel(self.dock)
        self.app.window._activate_tool("select");self.app.viewport.flash_status(t("Perfil Complexo: desenhe contornos fechados no plano 2D."),5000)

    def is_profile_workspace(self): return self._ws is not None and self.app.workspace() is self._ws
    def sync_workspace_ui(self):
        if not self.is_profile_workspace():return
        ws=self._ws;self.library_widget.hide();self.editor_widget.show();self.heading.setText(t("Editor de Perfil Complexo"));self.name.setText(ws.profile_name);self.folder.setText(ws.profile_folder)
        for f,v in ((self.anchor_x,ws.anchor[0]),(self.anchor_y,ws.anchor[1])):
            b=f.blockSignals(True);f.setValue(float(v));f.blockSignals(b)
        self.feedback.setText(t("Plano ortográfico 2D ativo. A origem marcada será o ponto de inserção no futuro Perfil por Caminho."))

    def name_changed(self,text):
        if self.is_profile_workspace():self._ws.profile_name=str(text)
    def folder_changed(self,text):
        if self.is_profile_workspace():self._ws.profile_folder=" / ".join(x.strip() for x in str(text).replace("\\","/").split("/") if x.strip()) or "Meus Perfis"

    def anchor_numeric_changed(self,*_):
        if not self.is_profile_workspace():return
        self._ws.anchor=[float(self.anchor_x.value()),float(self.anchor_y.value())];self.app.viewport.update()
    def set_anchor(self,x,y):
        if not self.is_profile_workspace():return
        self._ws.anchor=[float(x),float(y)];self.sync_workspace_ui();self.app.viewport.update();self.feedback.setText(t("Origem do perfil atualizada."))
    def begin_pick_origin(self):
        if self.is_profile_workspace():self.app.window._activate_tool(PROFILE_ORIGIN_TOOL_KEY);self.app.viewport.setFocus()

    def save_workspace(self,leave=False):
        if not self.is_profile_workspace():return False
        ws=self._ws;name=self.name.text().strip() or t("Perfil sem nome")
        try:
            loops,bounds=_profile_loops(ws.scene,ws.anchor)
            profile={"id":ws.profile_id or uuid.uuid4().hex,"name":name,
                     "schema_version":1,"loops":loops,"bounds":bounds,
                     "folder":ws.profile_folder or "Meus Perfis"}
            saved=upsert_profile(profile);ws.profile_id=saved["id"];ws.profile_name=saved["name"];ws.mark_clean();self._notify_consumers()
            self.feedback.setText(t("Perfil salvo na biblioteca de favoritos."))
            if leave:
                if not self.app.leave_workspace():return False
            return True
        except ValueError as exc:
            self.feedback.setText(str(exc));self.feedback.setStyleSheet("color:#b00020;");self.app.viewport.flash_status(str(exc),6000);return False
        finally:
            if hasattr(self,"feedback") and not self.feedback.text().startswith(("Existem","Desenhe","O perfil","Não foi","Há um","Contorno")):
                self.feedback.setStyleSheet("")

    def cancel_workspace(self):
        if not self.is_profile_workspace():return
        self._ws._force_leave=True
        try:self.app.leave_workspace()
        finally:
            if self._ws is not None:self._ws._force_leave=False
    def workspace_left(self,ws):
        if self._ws is ws:self._ws=None
        self.library_widget.show();self.editor_widget.hide();self.refresh_library();self.app.show_panel(self.dock)
    def _workspace_scene_changed(self):
        if self.is_profile_workspace():self.app.viewport.update()

    def draw_origin_overlay(self,viewport,painter):
        if not self.is_profile_workspace():return
        try:
            import numpy as np
            arr=np.array([[self._ws.anchor[0],self._ws.anchor[1],0.0]],dtype=float)
            px,py,front=self.app.world_to_pixels(arr)
            if not bool(front[0]):return
            x=float(px[0]);y=float(py[0]);painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor("#d36b2c"),2));painter.drawLine(int(x-8),int(y),int(x+8),int(y));painter.drawLine(int(x),int(y-8),int(x),int(y+8));painter.drawEllipse(int(x-3),int(y-3),6,6)
        except Exception:
            return
