# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
import math
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import AxisMagnet,Tool
from .commands import root_edit_allowed
from .beam_commands import CreateBeam
from .beam_model import BeamError,MIN_DIM,make_beam,endpoints_world,reference_path_world

class BeamTool(AxisMagnet,Tool):
    name="Viga paramétrica";description="Desenhar uma viga paramétrica por dois pontos; inclinação e curvaturas vêm da paleta.";wireframe_color=(0.70,0.42,0.18,1.0);vcb_label="Comprimento";architecture_angle_snap=True
    def __init__(self,controller):self.controller=controller;self.reset()
    def reset(self):self.first=None;self.hover=None;self.start_point=None
    def drag_plane(self,viewport):z=self.controller.current_base_z();return QVector3D(0,0,z),QVector3D(0,0,1)
    def point(self,ctx):z=self.controller.current_base_z();return QVector3D(ctx.world.x(),ctx.world.y(),z)
    def on_activate(self,viewport):self.reset();self.controller.schedule_refresh()
    def on_deactivate(self,viewport):self.reset();self.controller.schedule_refresh();viewport.update()
    def on_hover(self,ctx):self.hover=self.point(ctx);ctx.viewport.update()
    def on_click(self,ctx):
        try:
            root_edit_allowed(ctx.viewport.scene);p=self.point(ctx)
            if self.first is None:
                self.first=QVector3D(p);self.start_point=QVector3D(p);self.hover=QVector3D(p);self.controller.message("Indique o ponto final da viga; Shift trava a inferência ativa.")
            else:self._commit(ctx.viewport,p)
        except BeamError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def _commit(self,viewport,end):
        if self.first is None:return
        g=make_beam(self.first,end,self.controller.resolved_defaults());viewport.history.execute(CreateBeam(g))
        if viewport.history.last_error:raise BeamError(viewport.history.last_error)
        viewport.notify_scene_changed();self.controller.message("Viga criada. Clique para iniciar outra; Esc para sair.");self.reset()
    def on_value(self,viewport,value):
        try:
            if self.first is None or self.hover is None or not isinstance(value,(int,float)) or float(value)<MIN_DIM:return False
            d=self.hover-self.first;d.setZ(0);L=math.hypot(d.x(),d.y())
            if L<MIN_DIM:return False
            end=self.first+QVector3D(d.x()/L,d.y()/L,0)*float(value);self._commit(viewport,end);return True
        except BeamError as exc:self.controller.message(str(exc),error=True);return False
    def on_cancel(self,viewport):
        if self.first is not None:self.reset();viewport.update();self.controller.message("Viga cancelada. Clique para iniciar outra; Esc para sair.")
        else:QTimer.singleShot(0,self.controller.stop_drawing)
    def rubber_band_lines(self):
        if self.first is None or self.hover is None:return []
        try:
            g=make_beam(self.first,self.hover,self.controller.resolved_defaults());pts=reference_path_world(g);return list(zip(pts,pts[1:]))
        except Exception:return [(self.first,self.hover)]
