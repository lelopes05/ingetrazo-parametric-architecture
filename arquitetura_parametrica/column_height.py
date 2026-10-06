# SPDX-License-Identifier: GPL-3.0-or-later
"""Graphical top-height handle for columns."""
from __future__ import annotations
import math
from PySide6.QtCore import QTimer
from PySide6.QtGui import QMatrix4x4,QVector3D
from tools.base import Tool
from .column_commands import EditColumn
from .column_model import ColumnError,MIN_DIM,MAX_DIM,read_column
from .levels import level_by_name
from .path_edit import _vertical_view_plane

class ChangeColumnHeightTool(Tool):
    name="Alterar altura do pilar"; description="Arrastar topo do pilar em Z."; uses_snap=True; wireframe_color=(0.9,0.45,0.1,1.0); vcb_label="Altura"
    def __init__(self,controller): self.controller=controller; self.reset()
    def prepare(self,group,anchor): self.group=group; self.anchor=QVector3D(anchor); self.scene=self.controller.app.scene
    def reset(self): self.group=None; self.anchor=None; self.scene=None; self.values=None; self.origin_z=None; self.preview=False; self.new_height=None
    def drag_plane(self,viewport): return _vertical_view_plane(viewport,self.anchor) if self.anchor is not None else None
    def on_activate(self,viewport):
        if self.group is None: QTimer.singleShot(0,self.controller.return_to_select); return
        try:
            self.values=read_column(self.group); self.new_height=self.values["height"]; viewport.begin_groups_preview([self.group]); self.preview=True
            self.controller.message("Mova o topo em Z e clique; snaps copiam apenas a cota.")
        except ColumnError as exc:self.controller.message(str(exc),error=True);QTimer.singleShot(0,self.controller.return_to_select)
    def on_deactivate(self,viewport):
        if self.preview:viewport.end_groups_preview()
        self.reset();viewport.update()
    def _height(self,ctx):
        if ctx.snap is not None and getattr(ctx.snap,"kind",None) in {"endpoint","midpoint","arc_midpoint","center","origin","intersection","close","reference"}:
            h=float(ctx.snap.point.z())-self.values["base_z"]
            if MIN_DIM<=h<=MAX_DIM:return h
        if self.origin_z is None:self.origin_z=ctx.world.z()
        return max(MIN_DIM,min(MAX_DIM,self.values["height"]+ctx.world.z()-self.origin_z))
    def _preview(self,viewport,h):
        self.new_height=float(h); factor=h/self.values["height"]; base=self.values["base_z"]; m=QMatrix4x4();m.translate(0,0,base);m.scale(1,1,factor);m.translate(0,0,-base);viewport.set_groups_preview_matrix(m)
    def on_hover(self,ctx):
        if self.values:self._preview(ctx.viewport,self._height(ctx));ctx.viewport.update()
    def _commit(self,viewport,h):
        if self.preview:viewport.end_groups_preview();self.preview=False
        vals=dict(self.values);vals["height"]=float(h)
        if vals.get("top_mode")=="level" and vals.get("top_level"):
            lv=level_by_name(self.controller.app,vals["top_level"])
            if lv is not None: vals["top_offset"]=vals["base_z"]+h-float(lv["z"])
            else: vals.update(top_mode="height",top_level=None,top_offset=0.0)
        viewport.history.execute(EditColumn(viewport.scene,self.group,vals))
        if viewport.history.last_error:raise ColumnError(viewport.history.last_error)
        viewport.notify_scene_changed();self.controller.return_to_select();self.controller.message("Altura do pilar atualizada.")
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,self._height(ctx))
        except ColumnError as exc:self.controller.message(str(exc),error=True)
    def on_value(self,viewport,value):
        try:
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<MIN_DIM:raise ColumnError("Digite uma altura positiva.")
            self._commit(viewport,float(value));return True
        except ColumnError as exc:self.controller.message(str(exc),error=True);return False
    def value_label(self):
        if self.new_height is None or self.anchor is None or self.values is None:return None
        p=QVector3D(self.anchor.x(),self.anchor.y(),self.values["base_z"]+self.new_height)
        return (f"{self.new_height:.4f} m".replace(".",","),p)
    def on_cancel(self,viewport):
        if self.preview:viewport.end_groups_preview();self.preview=False
        self.controller.return_to_select();self.controller.message("Alteração de altura cancelada.")
