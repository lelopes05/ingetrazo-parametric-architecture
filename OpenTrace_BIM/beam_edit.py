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
        self._preview_hidden = None

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
            from .preview_utils import hide_original_for_preview
            self._preview_hidden = hide_original_for_preview(self.group)
            if self.mode == "vertical":
                self.start_point = QVector3D(self.refs[self.endpoint])
                self.controller.message("Mova o mouse: o extremo da viga acompanha a cota indicada. Clique para confirmar; Shift trava a inferência ativa.")
            elif self.mode == "free":
                self.start_point = QVector3D(self.refs[self.endpoint])
                self.controller.message("Mova o mouse: o extremo da viga acompanha o cursor. Clique para confirmar; Shift trava a inferência ativa.")
            else:
                self.controller.message("Prolongue/encurte a viga no mesmo eixo e clique.")
            from .preview_utils import pointer_world_on_plane
            q = pointer_world_on_plane(viewport, self.drag_plane(viewport))
            if q is not None:
                self.hover = self._candidate(q)
        except BeamError as exc:
            self.controller.message(str(exc), True); QTimer.singleShot(0, lambda: activate_select(self.controller.app))
        viewport.update()

    def _show_original(self):
        if self.group is not None and self._preview_hidden is not None:
            from .preview_utils import restore_original_after_preview
            restore_original_after_preview(self.group,self._preview_hidden)
        self._preview_hidden=None

    def on_deactivate(self, viewport):
        self._show_original(); self.reset(); viewport.update()

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
            return QVector3D(cur.x(), cur.y(), p.z())
        z = cur.z()
        if self.mode == "free":
            return QVector3D(p.x(), p.y(), z)
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
        self.hover = self._candidate(ctx.world); ctx.viewport.update()

    def on_click(self, ctx):
        try:
            ends=self._ends(ctx.world)
            if ends is None: raise BeamError("O comprimento resultante da viga é pequeno demais.")
            self._show_original()
            ctx.viewport.history.execute(ReshapeBeam(ctx.viewport.scene,self.group,*ends))
            if ctx.viewport.history.last_error: raise BeamError(ctx.viewport.history.last_error)
            ctx.viewport.notify_scene_changed(); self.controller.message("Extremo da viga movido.")
            self.reset(); activate_select(self.controller.app)
        except BeamError as exc:self.controller.message(str(exc),True)
        ctx.viewport.update()

    def on_cancel(self, viewport):
        self._show_original(); self.reset(); activate_select(self.controller.app); viewport.update()

    def on_value(self, viewport, value):
        try:
            if not isinstance(value, (int, float)) or not self.refs:
                return False
            if self.mode == "vertical":
                q = QVector3D(self.refs[self.endpoint])
                q.setZ(float(value))
                a, b = QVector3D(self.refs[0]), QVector3D(self.refs[1])
                if self.endpoint == 0:
                    a = q
                else:
                    b = q
                self._show_original()
                viewport.history.execute(ReshapeBeam(viewport.scene, self.group, a, b))
                if viewport.history.last_error:
                    raise BeamError(viewport.history.last_error)
                viewport.notify_scene_changed()
                self.reset()
                activate_select(self.controller.app)
                return True
            if float(value) < MIN_DIM:
                return False
            if abs(float((self.values or {}).get("curvature", 0.0))) > 1e-8:
                raise BeamError(
                    "Em viga curva, mova o extremo com o mouse; "
                    "o comprimento do arco é derivado da flecha."
                )
            fixed = self.refs[1-self.endpoint]
            cur = self.refs[self.endpoint]
            d = cur - fixed
            d.setZ(0)
            length = math.hypot(d.x(), d.y())
            if length < MIN_DIM:
                return False
            u = QVector3D(d.x()/length, d.y()/length, 0)
            plan = float(value) * abs(math.cos(math.radians(
                float(self.values.get("inclination", 0.0)))))
            q = fixed + u * plan
            a, b = (q, fixed) if self.endpoint == 0 else (fixed, q)
            self._show_original()
            viewport.history.execute(ReshapeBeam(viewport.scene, self.group, a, b))
            if viewport.history.last_error:
                raise BeamError(viewport.history.last_error)
            viewport.notify_scene_changed()
            self.reset()
            activate_select(self.controller.app)
            return True
        except BeamError as exc:
            self.controller.message(str(exc), True)
            return False

    def preview_faces(self):
        ends=self._ends()
        if ends is None or self.values is None:return []
        try:
            from .beam_model import make_beam
            from .preview_utils import group_faces_world
            return group_faces_world(make_beam(ends[0],ends[1],self.values,template=self.group))
        except Exception:return []

    def rubber_band_lines(self):
        ends=self._ends()
        return [] if ends is None else [ends]
