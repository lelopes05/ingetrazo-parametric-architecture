# SPDX-License-Identifier: GPL-3.0-or-later
"""Single-click vertical parametric column placement."""
from __future__ import annotations
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import AxisMagnet, Tool
from .commands import root_edit_allowed
from .column_commands import CreateColumn
from .column_model import ColumnError, make_column, profile_world

class ColumnTool(AxisMagnet,Tool):
    name="Pilar paramétrico"; description="Inserir pilar vertical paramétrico."; wireframe_color=(0.82,0.48,0.12,1.0); vcb_label="Pilar"
    def __init__(self,controller): self.controller=controller; self.hover=None
    def reset(self): self.hover=None
    def drag_plane(self,viewport):
        z=self.controller.current_base_z(); return QVector3D(0,0,z),QVector3D(0,0,1)
    def point(self,ctx): return QVector3D(ctx.world.x(),ctx.world.y(),self.controller.current_base_z())
    def on_activate(self,viewport): self.reset(); self.controller.schedule_refresh()
    def on_deactivate(self,viewport): self.reset(); self.controller.schedule_refresh()
    def on_hover(self,ctx): self.hover=self.point(ctx); ctx.viewport.update()
    def on_click(self,ctx):
        try:
            root_edit_allowed(ctx.viewport.scene); p=self.point(ctx)
            g=make_column(p,self.controller.resolved_defaults())
            ctx.viewport.history.execute(CreateColumn(g))
            if ctx.viewport.history.last_error: raise ColumnError(ctx.viewport.history.last_error)
            ctx.viewport.notify_scene_changed(); self.controller.message("Pilar criado. Clique para inserir outro; Esc para sair.")
        except Exception as exc:
            self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_cancel(self,viewport): QTimer.singleShot(0,self.controller.stop_drawing)
    def rubber_band_lines(self):
        if self.hover is None:return []
        try:
            g=make_column(self.hover,self.controller.resolved_defaults())
            b=profile_world(g,False); t=profile_world(g,True); lines=[]
            lines += [(a,c) for a,c in zip(b,b[1:]+b[:1])]; lines += [(a,c) for a,c in zip(t,t[1:]+t[:1])]
            step=max(1,len(b)//8); lines += [(b[i],t[i]) for i in range(0,len(b),step)]
            return lines
        except Exception:return []