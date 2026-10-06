# SPDX-License-Identifier: GPL-3.0-or-later
"""Graphical endpoint editing for parametric beams."""
from __future__ import annotations
import math
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import AxisMagnet, Tool

from .beam_commands import ReshapeBeam
from .beam_model import BeamError, MIN_DIM, endpoints_world, read_beam
from .host import activate_select


class MoveBeamEndpointTool(AxisMagnet, Tool):
    """Move one beam endpoint freely in XY or continue it along its current axis."""
    uses_snap = True
    wireframe_color = (0.70, 0.42, 0.18, 1.0)

    def __init__(self, controller, mode):
        self.controller = controller
        self.mode = mode  # free | continue | vertical
        self.architecture_angle_snap = (mode == "free")
        if mode == "vertical":
            self.name = "Mover extremo da viga na vertical"
        elif mode == "free":
            self.name = "Mover extremo da viga"
        else:
            self.name = "Continuar viga"
        self.description = self.name
        self.reset()

    def reset(self):
        self.group = None
        self.anchor = None
        self.refs = None
        self.endpoint = None
        self.values = None
        self.hover = None
        self.start_point = None
        self.move_reference = None

    def prepare(self, group, anchor):
        self.group = group
        self.anchor = QVector3D(anchor)
        self.start_point = QVector3D(anchor) if self.mode == "continue" else None
        self.move_reference = None

    def on_activate(self, viewport):
        self.controller.hide_endpoint_palette()
        if self.group is None or self.group not in viewport.scene.groups:
            QTimer.singleShot(0, lambda: activate_select(self.controller.app)); return
        try:
            self.values = read_beam(self.group)
            a,b = endpoints_world(self.group)
            self.refs = [QVector3D(a), QVector3D(b)]
            self.endpoint = 0 if (self.anchor-self.refs[0]).length() <= (self.anchor-self.refs[1]).length() else 1
            self.hover = QVector3D(self.refs[self.endpoint])
            if self.mode == "vertical":
                self.controller.message("Clique no ponto de referência do movimento vertical deste extremo da viga.")
            elif self.mode == "free":
                self.controller.message("Clique no ponto de referência para mover este extremo da viga.")
            else:
                self.controller.message("Prolongue/encurte a viga no mesmo eixo e clique.")
        except BeamError as exc:
            self.controller.message(str(exc), True); QTimer.singleShot(0, lambda: activate_select(self.controller.app))
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset(); viewport.update()

    def drag_plane(self, viewport):
        if self.refs and self.mode == "vertical":
            # Camera-facing vertical plane: X/Y remain the semantic endpoint,
            # only Z is consumed by _candidate.
            q = self.refs[self.endpoint if self.endpoint is not None else 0]
            yaw = getattr(viewport.camera, "yaw", 0.0)
            normal = QVector3D(math.cos(yaw), math.sin(yaw), 0.0)
            if normal.length() < 1.0e-9: normal = QVector3D(1,0,0)
            return QVector3D(q), normal.normalized()
        z = self.refs[0].z() if self.refs else self.controller.current_base_z()
        return QVector3D(0,0,z), QVector3D(0,0,1)

    def _candidate(self, p):
        if not self.refs or self.endpoint is None: return QVector3D(p)
        cur = self.refs[self.endpoint]
        if self.mode == "vertical":
            if self.move_reference is None:return QVector3D(cur)
            return QVector3D(cur.x(), cur.y(), cur.z() + p.z() - self.move_reference.z())
        z = cur.z()
        if self.mode == "free":
            if self.move_reference is None:return QVector3D(cur)
            return QVector3D(cur.x() + p.x() - self.move_reference.x(),
                             cur.y() + p.y() - self.move_reference.y(), z)
        q = QVector3D(p.x(), p.y(), z)
        fixed = self.refs[1-self.endpoint]
        cur = self.refs[self.endpoint]
        d = cur-fixed; d.setZ(0)
        L = math.hypot(d.x(),d.y())
        if L < MIN_DIM: return cur
        u = QVector3D(d.x()/L,d.y()/L,0)
        t = QVector3D.dotProduct(q-fixed,u)
        t = max(MIN_DIM,t)
        return fixed + u*t

    def _ends(self, p=None):
        if not self.refs or self.endpoint is None: return None
        q = self._candidate(p if p is not None else self.hover)
        a,b = QVector3D(self.refs[0]),QVector3D(self.refs[1])
        if self.endpoint==0:a=q
        else:b=q
        if math.hypot((b-a).x(),(b-a).y()) < MIN_DIM:return None
        return a,b

    def on_hover(self, ctx):
        if self.mode in ("free","vertical") and self.move_reference is None:return
        self.hover = self._candidate(ctx.world); ctx.viewport.update()

    def on_click(self, ctx):
        try:
            if self.mode in ("free","vertical") and self.move_reference is None:
                self.move_reference=QVector3D(ctx.world);self.start_point=QVector3D(ctx.world)
                self.controller.message("Agora clique no ponto de destino do extremo da viga.");ctx.viewport.update();return
            ends=self._ends(ctx.world)
            if ends is None: raise BeamError("O comprimento resultante da viga é pequeno demais.")
            ctx.viewport.history.execute(ReshapeBeam(ctx.viewport.scene,self.group,*ends))
            if ctx.viewport.history.last_error: raise BeamError(ctx.viewport.history.last_error)
            ctx.viewport.notify_scene_changed(); self.controller.message("Extremo da viga movido.")
            self.reset(); activate_select(self.controller.app)
        except BeamError as exc:self.controller.message(str(exc),True)
        ctx.viewport.update()

    def on_cancel(self, viewport):
        self.reset(); activate_select(self.controller.app); viewport.update()

    def on_value(self, viewport, value):
        try:
            if not isinstance(value,(int,float)) or not self.refs:return False
            if self.mode == "vertical":
                q=QVector3D(self.refs[self.endpoint]);q.setZ(float(value))
                a,b=QVector3D(self.refs[0]),QVector3D(self.refs[1])
                if self.endpoint==0:a=q
                else:b=q
                viewport.history.execute(ReshapeBeam(viewport.scene,self.group,a,b))
                if viewport.history.last_error:raise BeamError(viewport.history.last_error)
                viewport.notify_scene_changed();self.reset();activate_select(self.controller.app);return True
            if float(value)<MIN_DIM:return False
            if abs(float((self.values or {}).get("curvature",0.0)))>1e-8:
                raise BeamError("Em viga curva, mova o extremo com o mouse; o comprimento do arco é derivado da flecha.")
            fixed=self.refs[1-self.endpoint]; cur=self.refs[self.endpoint]; d=cur-fixed;d.setZ(0);L=math.hypot(d.x(),d.y())
            if L<MIN_DIM:return False
            u=QVector3D(d.x()/L,d.y()/L,0);plan=float(value)*abs(math.cos(math.radians(float(self.values.get("inclination",0.0)))))
            q=fixed+u*plan; a,b=(q,fixed) if self.endpoint==0 else (fixed,q)
            viewport.history.execute(ReshapeBeam(viewport.scene,self.group,a,b))
            if viewport.history.last_error:raise BeamError(viewport.history.last_error)
            viewport.notify_scene_changed();self.reset();activate_select(self.controller.app);return True
        except BeamError as exc:self.controller.message(str(exc),True);return False

    def rubber_band_lines(self):
        ends=self._ends()
        return [] if ends is None else [ends]
