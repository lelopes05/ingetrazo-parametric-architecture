# SPDX-License-Identifier: GPL-3.0-or-later
"""Embedded polygon openings hosted by a parametric slab."""
from __future__ import annotations
import math, uuid
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import AxisMagnet, Tool

from .slab_commands import EditSlab
from .slab_model import MIN_DIM, SlabError, slab_openings_world


class SlabOpeningTool(AxisMagnet, Tool):
    name="Abertura na laje"; description="Desenhar um polígono interno que atravessa a laje."; uses_snap=True
    wireframe_color=(0.92,0.28,0.20,1.0); vcb_label="Abertura"
    architecture_angle_snap=True
    def __init__(self,controller): self.controller=controller; self.reset()
    def reset(self): self.slab=None; self.points=[]; self.hover=None; self.scene=None; self.start_point=None; self.chain_first_point=None
    def arm(self,slab,_index=None,_anchor=None): self.reset(); self.slab=slab; self.scene=self.controller.app.scene
    def on_activate(self,viewport):
        if self.slab is None: QTimer.singleShot(0,self.controller.return_to_select);return
        self.controller.message("Abertura: clique os vértices dentro da laje e finalize clicando novamente no primeiro.")
    def on_deactivate(self,viewport): self.reset(); viewport.update()
    def drag_plane(self,viewport):
        z=self.controller.current_reference_z() if self.slab is None else self.controller.slab_reference_z(self.slab)
        return QVector3D(0,0,z),QVector3D(0,0,1)
    def _point(self,ctx):
        z=self.controller.slab_reference_z(self.slab); return QVector3D(ctx.world.x(),ctx.world.y(),z)
    def _near_first(self,viewport,screen):
        if len(self.points)<3:return False
        q=viewport._world_to_pixel(self.points[0])
        if q is None:return False
        return math.hypot(float(screen.x())-q[0],float(screen.y())-q[1])<=max(8.0,float(getattr(viewport,"snap_threshold_px",10.0)))
    def on_hover(self,ctx):
        self.hover=self._point(ctx)
        if self.points:
            self.start_point=QVector3D(self.points[-1]); self.chain_first_point=QVector3D(self.points[0]) if len(self.points)>=2 else None
        ctx.viewport.update()
    def on_click(self,ctx):
        try:
            p=self._point(ctx)
            if self.points and ((ctx.snap is not None and getattr(ctx.snap,"kind",None)=="close") or self._near_first(ctx.viewport,ctx.screen)):
                if len(self.points)<3:raise SlabError("A abertura precisa ter pelo menos três vértices.")
                existing=slab_openings_world(self.slab,reference=True)
                op={"id":uuid.uuid4().hex,"kind":"embedded","polygon":[[q.x(),q.y(),q.z()] for q in self.points],"edges":[{"type":"line"} for _ in self.points],"source_id":None}
                ctx.viewport.history.execute(EditSlab(ctx.viewport.scene,self.slab,openings=existing+[op]))
                if ctx.viewport.history.last_error:raise SlabError(ctx.viewport.history.last_error)
                ctx.viewport.notify_scene_changed();self.controller.message("Abertura criada na laje.");self.reset();self.controller.return_to_select();return
            if self.points and (p-self.points[-1]).length()<MIN_DIM:raise SlabError("Indique um vértice diferente do anterior.")
            self.points.append(p);self.hover=p
            self.start_point=QVector3D(p);self.chain_first_point=QVector3D(self.points[0]) if len(self.points)>=2 else None
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_cancel(self,viewport): self.reset();self.controller.return_to_select();self.controller.message("Abertura cancelada.");viewport.update()
    def rubber_band_lines(self):
        if not self.points:return []
        pts=list(self.points)
        if self.hover is not None:pts.append(self.hover)
        return list(zip(pts,pts[1:]))