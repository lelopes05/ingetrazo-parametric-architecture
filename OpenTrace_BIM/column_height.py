# SPDX-License-Identifier: GPL-3.0-or-later
"""Graphical top-height handle for columns with exact live geometry preview."""
from __future__ import annotations
import math
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import Tool
from .column_commands import EditColumn
from .column_model import ColumnError,MIN_DIM,MAX_DIM,read_column,insertion_world,top_world,make_column
from .levels import level_by_name
from .path_edit import _vertical_view_plane
from .preview_utils import group_faces_world

class ChangeColumnHeightTool(Tool):
    name="Alterar altura do pilar"; description="Arrastar topo do pilar em Z."; uses_snap=True; wireframe_color=(0.9,0.45,0.1,1.0); vcb_label="Altura"
    def __init__(self,controller): self.controller=controller; self.reset()
    def prepare(self,group,anchor): self.group=group; self.anchor=QVector3D(anchor); self.scene=self.controller.app.scene
    def reset(self): self.group=None; self.anchor=None; self.scene=None; self.values=None; self.origin_z=None; self.new_height=None; self._preview_hidden=None
    def drag_plane(self,viewport):
        if self.group is None or self.anchor is None:
            return None
        try:
            base=QVector3D(insertion_world(self.group));top=QVector3D(top_world(self.group));axis=top-base
            if axis.length()<1e-9:
                return _vertical_view_plane(viewport,self.anchor)
            axis.normalize();forward=QVector3D(viewport.camera.forward())
            normal=forward-axis*QVector3D.dotProduct(forward,axis)
            if normal.length()<1e-6:
                normal=QVector3D.crossProduct(axis,QVector3D(0,0,1))
            if normal.length()<1e-6:
                return _vertical_view_plane(viewport,self.anchor)
            return base,normal.normalized()
        except Exception:
            return _vertical_view_plane(viewport,self.anchor) if self.anchor is not None else None
    def on_activate(self,viewport):
        if self.group is None: QTimer.singleShot(0,self.controller.return_to_select); return
        try:
            self.values=read_column(self.group); self.new_height=self.values["height"]
            from .preview_utils import hide_original_for_preview
            self._preview_hidden=hide_original_for_preview(self.group)
            self.controller.message("Mova o mouse: o topo do pilar acompanha a cota indicada e o pilar inteiro é projetado antes do clique. Snaps copiam apenas a cota.")
            from .preview_utils import pointer_world_on_plane
            q=pointer_world_on_plane(viewport,self.drag_plane(viewport))
            if q is not None:
                base=QVector3D(insertion_world(self.group));top=QVector3D(top_world(self.group));axis=top-base;den=QVector3D.dotProduct(axis,axis)
                if den>1e-12:self.new_height=max(MIN_DIM,min(MAX_DIM,float(self.values["height"])*QVector3D.dotProduct(q-base,axis)/den))
        except ColumnError as exc:self.controller.message(str(exc),error=True);QTimer.singleShot(0,self.controller.return_to_select)
        viewport.update()
    def _show_original(self):
        if self.group is not None and self._preview_hidden is not None:
            from .preview_utils import restore_original_after_preview
            restore_original_after_preview(self.group,self._preview_hidden)
        self._preview_hidden=None
    def on_deactivate(self,viewport): self._show_original();self.reset();viewport.update()
    def _height(self,ctx):
        if ctx.snap is not None and getattr(ctx.snap,"kind",None) in {"endpoint","midpoint","arc_midpoint","center","origin","intersection","close","reference"}:
            h=float(ctx.snap.point.z())-self.values["base_z"]
            if MIN_DIM<=h<=MAX_DIM:return h
        # For an inclined pillar, changing height moves the visible top along
        # its existing axis, not straight up. Project the cursor onto that ray
        # so the preview handle stays visually under the mouse instead of
        # appearing laterally displaced.
        try:
            base=QVector3D(insertion_world(self.group));top=QVector3D(top_world(self.group));axis=top-base
            den=QVector3D.dotProduct(axis,axis)
            if den>1e-12:
                scale=QVector3D.dotProduct(QVector3D(ctx.world)-base,axis)/den
                return max(MIN_DIM,min(MAX_DIM,float(self.values["height"])*scale))
        except Exception:
            pass
        return max(MIN_DIM,min(MAX_DIM,float(ctx.world.z())-float(self.values["base_z"])))
    def on_hover(self,ctx):
        if self.values:self.new_height=float(self._height(ctx));ctx.viewport.update()
    def _candidate_values(self,h):
        vals=dict(self.values);vals["height"]=float(h)
        if vals.get("top_mode")=="level" and vals.get("top_level"):
            lv=level_by_name(self.controller.app,vals["top_level"])
            if lv is not None: vals["top_offset"]=vals["base_z"]+float(h)-float(lv["z"])
            else: vals.update(top_mode="height",top_level=None,top_offset=0.0)
        return vals
    def preview_faces(self):
        if self.group is None or self.values is None or self.new_height is None:return []
        try:return group_faces_world(make_column(insertion_world(self.group),self._candidate_values(self.new_height),template=self.group))
        except Exception:return []
    def _commit(self,viewport,h):
        vals=self._candidate_values(h)
        self._show_original()
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
    def on_cancel(self,viewport):self._show_original();self.controller.return_to_select();self.controller.message("Alteração de altura cancelada.");viewport.update()
