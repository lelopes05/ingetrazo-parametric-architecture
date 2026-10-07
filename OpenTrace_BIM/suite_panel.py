# SPDX-License-Identifier: GPL-3.0-or-later
"""Single sidebar home for all Parametric Architecture tools."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from . import __version__
from .icons import icon
from .preset_catalog import builtins
from .profile_library import load_profiles


class ArchitectureSuitePanel:
    PAGE_INFO=(
        ("home","Home","home"),("wall","Wall","wall"),("slab","Slab","slab"),
        ("column","Column","column"),("beam","Beam","beam"),("membrane","Membrane","slab"),("profiles","Profiles","profile"),
        ("bim","BIM","bim"),
    )
    def __init__(self,app,wall=None,slab=None,column=None,beam=None,profiles=None,bim=None,membrane=None,master_dock=None):
        self.app=app;self.controllers={"wall":wall,"slab":slab,"column":column,"beam":beam,"membrane":membrane,"profiles":profiles,"bim":bim}
        self._sync_queued=False;self._last_active_tool_id=id(getattr(self.app.viewport,"active_tool",None))
        self._mode_buttons={}
        self.panel=QWidget();self.panel.setMinimumSize(0,0)
        root=QVBoxLayout(self.panel);root.setContentsMargins(4,4,4,4);root.setSpacing(4)
        self.nav=QFrame();navlay=QHBoxLayout(self.nav);navlay.setContentsMargins(0,0,0,0);navlay.setSpacing(2)
        self.group=QButtonGroup(self.panel);self.group.setExclusive(True);self.buttons={}
        for key,label,ico in self.PAGE_INFO:
            b=QToolButton();b.setCheckable(True);b.setAutoRaise(True);b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon);b.setIcon(icon(ico));b.setIconSize(QSize(26,26));b.setText(label);b.setToolTip(label)
            b.clicked.connect(lambda _=False,k=key:self.user_show_page(k))
            navlay.addWidget(b);self.group.addButton(b);self.buttons[key]=b
        root.addWidget(self.nav)
        self.stack=QStackedWidget();self.stack.setMinimumSize(0,0);root.addWidget(self.stack,1);self.pages={}
        self.home=self._make_home();self._add_page("home",self.home)
        # Membrane stays visible in the roadmap without loading any membrane
        # controller/tool code.  This page is informational only.
        self._add_page("membrane", self._make_membrane_notice())
        self.master_dock = master_dock or getattr(
            self.app.window, "_arquitetura_parametrica_master_dock", None)
        if self.master_dock is None:
            self.master_dock=self.app.add_panel(
                "Parametric Architecture",self.panel,name="parametric_architecture")
        else:
            # The host already registered this dock before restoreState.  Only
            # swap its contents; do not remove/re-add/re-tabify docks after the
            # main window is shown.
            self.master_dock.setWidget(self.panel)
        self.master_dock.hide()
        for key in ("wall","slab","column","beam","profiles","bim"):
            ctrl=self.controllers.get(key)
            if ctrl is None or not hasattr(ctrl,"panel"):continue
            page=ctrl.panel
            wrapped=self._wrap_controller_page(key,ctrl,page)
            self._add_page(key,wrapped)
            ctrl.dock=self.master_dock
        self.show_page("home",show_dock=False);self._wire();self.refresh_home();self.sync_mode_buttons()
        QTimer.singleShot(1800,self._auto_check_updates_on_startup)

    def _add_page(self,key,widget):
        self.pages[key]=widget;self.stack.addWidget(widget)

    def _make_membrane_notice(self):
        w=QWidget();lay=QVBoxLayout(w);lay.setContentsMargins(12,12,12,12);lay.setSpacing(8)
        title=QLabel("<b style='font-size:14pt'>Membrane — Under evaluation</b>")
        title.setWordWrap(True);lay.addWidget(title)
        body=QLabel("Temporarily disabled while its modeling workflow is being reviewed.")
        body.setWordWrap(True);body.setStyleSheet("color:#666;");lay.addWidget(body)
        note=QLabel("The experimental membrane tools are not loaded in OpenTrace BIM 0.12.9.")
        note.setWordWrap(True);lay.addWidget(note);lay.addStretch(1)
        return w

    def _make_home(self):
        w=QWidget();lay=QVBoxLayout(w);lay.setContentsMargins(10,10,10,10);lay.setSpacing(10)
        title=QLabel("<b style='font-size:15pt'>Parametric Architecture</b><br><span style='color:#777'>Parametric architectural modeling and reusable libraries.</span>");title.setWordWrap(True);lay.addWidget(title)
        grid=QGridLayout();grid.setSpacing(8)
        cards=(("wall","Wall","wall"),("slab","Slab","slab"),("column","Column","column"),("beam","Beam","beam"),("membrane","Membrane","slab"),("profiles","Complex Profiles","profile"),("bim","BIM / IFC","bim"))
        for i,(key,label,ico) in enumerate(cards):
            b=QToolButton();b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon);b.setIcon(icon(ico));b.setIconSize(QSize(42,42));b.setText(label);b.setMinimumHeight(78)
            b.clicked.connect(lambda _=False,k=key:self.user_show_page(k));grid.addWidget(b,i//2,i%2)
        lay.addLayout(grid)
        self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setStyleSheet("color:#666;");lay.addWidget(self.summary)
        self.intersections=QLabel();self.intersections.setWordWrap(True);lay.addWidget(self.intersections)

        update_box=QFrame();update_box.setFrameShape(QFrame.StyledPanel)
        update_lay=QVBoxLayout(update_box);update_lay.setContentsMargins(8,8,8,8);update_lay.setSpacing(6)
        update_lay.addWidget(QLabel(f"<b>OpenTrace BIM {__version__}</b>"))
        self.update_status=QLabel(
            "Automatic update checks query only the official catalogue. "
            "Nothing is downloaded without confirmation."
        )
        self.update_status.setWordWrap(True);self.update_status.setStyleSheet("color:#666;")
        update_lay.addWidget(self.update_status)

        self.auto_update_check=QCheckBox("Check for updates automatically")
        self.update_button=QPushButton("Check for updates")
        update_lay.addWidget(self.auto_update_check);update_lay.addWidget(self.update_button)
        lay.addWidget(update_box)

        self.update_manager=None
        try:
            from .updater import (
                UpdateManager, auto_check_enabled, set_auto_check_enabled,
            )
            self.update_manager=UpdateManager(w)
            self.auto_update_check.setChecked(auto_check_enabled())
            self.auto_update_check.toggled.connect(set_auto_check_enabled)
            self.auto_update_check.toggled.connect(self._auto_update_toggled)
            self.update_button.clicked.connect(
                lambda: self.update_manager.check(manual=True)
            )
        except Exception as exc:
            self.auto_update_check.setEnabled(False)
            self.update_button.setEnabled(False)
            self.update_status.setText(
                f"Updates are unavailable in this installation: {type(exc).__name__}: {exc}"
            )

        lay.addStretch(1);return w

    def _actions_for(self,key,ctrl):
        names={
            "wall":("simple_wall_action","composite_wall_action","curve_action"),
            "slab":("simple_action","composite_action"),
            "column":("action",),"beam":("action",),"profiles":("action",),
        }.get(key,("action",))
        out=[]
        for name in names:
            action=getattr(ctrl,name,None)
            if action is not None and action not in out:out.append(action)
        return out

    def _wrap_controller_page(self,key,ctrl,page):
        wrapper=QWidget();wrapper.setMinimumSize(0,0)
        lay=QVBoxLayout(wrapper);lay.setContentsMargins(0,0,0,0);lay.setSpacing(4)
        actions=self._actions_for(key,ctrl)
        if actions:
            bar=QFrame();row=QHBoxLayout(bar);row.setContentsMargins(4,4,4,2);row.setSpacing(4);buttons=[]
            for idx,action in enumerate(actions):
                b=QToolButton();b.setCheckable(key in ("wall","slab","column","beam"));b.setAutoExclusive(False)
                b.setIcon(action.icon());b.setText(action.text());b.setToolTip(action.toolTip());b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon);b.setIconSize(QSize(22,22))
                b.clicked.connect(lambda _=False,k=key,a=action,i=idx:self._trigger_mode(k,a,i))
                row.addWidget(b);buttons.append(b)
            self._mode_buttons[key]=buttons
            row.addStretch(1);lay.addWidget(bar)
        # Controller forms can be tall. A scroll container prevents their size
        # hints from forcing the top-level window away from its restored size.
        page.setMinimumSize(0,0)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame);scroll.setMinimumSize(0,0);scroll.setWidget(page)
        lay.addWidget(scroll,1);return wrapper

    def _trigger_mode(self,key,action,index):
        self._set_mode_button(key,index)
        action.trigger()
        QTimer.singleShot(0,self.sync_mode_buttons)

    def _set_mode_button(self,key,index):
        for i,b in enumerate(self._mode_buttons.get(key,())):
            blocked=b.blockSignals(True);b.setChecked(i==index);b.blockSignals(blocked)

    def _activate_default(self,key):
        ctrl=self.controllers.get(key)
        if ctrl is None:return
        if key=="wall":
            self._set_mode_button(key,0);ctrl.start_structure("simple")
        elif key=="slab":
            self._set_mode_button(key,0);ctrl.start_structure("simple")
        elif key in ("column","beam"):
            self._set_mode_button(key,0);ctrl.start_drawing()

    def user_show_page(self,key):
        self.show_page(key)
        # Choosing a modelling category is itself a tool choice. Start with the
        # obvious default instead of making the user click a second control.
        if key in ("wall","slab","column","beam"):
            self._activate_default(key)

    def _auto_update_toggled(self, enabled):
        if enabled and self.update_manager is not None:
            # The checkbox itself is the user's consent to perform automatic
            # catalog checks. Still, no package is downloaded without another
            # explicit confirmation.
            QTimer.singleShot(0, lambda: self.update_manager.check(manual=False))

    def _auto_check_updates_on_startup(self):
        if (
            self.update_manager is not None
            and self.auto_update_check.isChecked()
        ):
            self.update_manager.check(manual=False)

    def _wire(self):
        for key,ctrl in self.controllers.items():
            if ctrl is None:continue
            for action in self._actions_for(key,ctrl):
                try:action.triggered.connect(lambda _=False,k=key:self.show_page(k))
                except Exception:pass
        self.app.viewport.sceneVersionChanged.connect(self.schedule_sync_context)
        self.app.viewport.measurementChanged.connect(self.schedule_tool_sync_context)

    def schedule_sync_context(self,*_):
        if self._sync_queued:return
        self._sync_queued=True;QTimer.singleShot(0,self._run_sync_context)

    def schedule_tool_sync_context(self,*_):
        active_id=id(getattr(self.app.viewport,"active_tool",None))
        if active_id==self._last_active_tool_id:return
        self._last_active_tool_id=active_id;self.schedule_sync_context()

    def _run_sync_context(self):
        self._sync_queued=False;self._last_active_tool_id=id(getattr(self.app.viewport,"active_tool",None));self.sync_context();self.sync_mode_buttons()

    def show_page(self,key,show_dock=True):
        if key not in self.pages:key="home"
        self.stack.setCurrentWidget(self.pages[key]);b=self.buttons.get(key)
        if b is not None:b.setChecked(True)
        if show_dock:
            try:self.app.show_panel(self.master_dock)
            except Exception:self.master_dock.show()
        if key=="home":self.refresh_home()
        self.sync_mode_buttons()

    def sync_mode_buttons(self):
        active=getattr(self.app.viewport,"active_tool",None)
        wall=self.controllers.get("wall")
        if wall is not None and self._mode_buttons.get("wall"):
            if active is getattr(wall,"curve_create_tool",None):idx=2
            else:
                kind=(getattr(getattr(wall,"structure",None),"currentData",lambda:None)() or getattr(wall,"defaults",{}).get("structure","simple"))
                idx=1 if kind=="composite" else 0
            self._set_mode_button("wall",idx)
        slab=self.controllers.get("slab")
        if slab is not None and self._mode_buttons.get("slab"):
            kind=(getattr(getattr(slab,"structure",None),"currentData",lambda:None)() or getattr(slab,"defaults",{}).get("structure","simple"))
            self._set_mode_button("slab",1 if kind=="composite" else 0)
        for key in ("column","beam"):
            if self._mode_buttons.get(key):self._set_mode_button(key,0)

    def sync_context(self):
        # BIM is an inspector/export workspace. Keep it open while selection or
        # metadata changes; otherwise selecting a wall would immediately throw
        # the user back to the modelling page.
        if self.pages.get("bim") is not None and self.stack.currentWidget() is self.pages.get("bim"):
            return
        active=getattr(self.app.viewport,"active_tool",None)
        for key in ("wall","slab","column","beam"):
            ctrl=self.controllers.get(key)
            if ctrl is None:continue
            tool=getattr(ctrl,"tool",None);curve_tool=getattr(ctrl,"curve_create_tool",None)
            if (tool is not None and active is tool) or (curve_tool is not None and active is curve_tool):
                self.show_page(key);return
        for key in ("beam","column","slab","wall"):
            ctrl=self.controllers.get(key)
            if ctrl is not None and getattr(ctrl,"target",None) is not None:
                self.show_page(key);return

    def refresh_home(self):
        cat=builtins();counts={k:len(v) for k,v in cat.items()};profiles=load_profiles()
        built=sum(1 for p in profiles if p.get("builtin"));personal=sum(1 for p in profiles if not p.get("builtin"))
        self.summary.setText(
            f"Built-in library: {counts.get('wall',0)} walls · {counts.get('slab',0)} slabs · "
            f"{counts.get('beam',0)} beams · {counts.get('column',0)} columns · {built} catalogue profiles. "
            f"Personal profiles: {personal}."
        )
        service=getattr(self.app.window,"_layer_combinations_service",None)
        if service is None:
            self.intersections.setText("Layer Combinations: integration is available when the companion service is loaded.")
        else:
            name=service.applied_combination_name() or "current state"
            self.intersections.setText(f"Layer Combinations connected · {name}. Intersection groups control automatic wall junctions.")
