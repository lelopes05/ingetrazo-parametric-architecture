# SPDX-License-Identifier: GPL-3.0-or-later
"""Move a virtual opening hotspot with the pointer; commit one undoable edit.

After choosing a grip operation, move the cursor and click to accept; Esc
cancels. No host mesh changes while hovering. All real changes use EditWall
or EditHostedFill and keep IFC/source IDs intact.
"""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import Tool

from .commands import EditWall
from .door_window_commands import EditHostedFill, _fill_record
from .door_window_core import normalize_fill
from .model import (MIN_DIM, MAX_DIM, WallError, path_world, read_wall,
                    nearest_path_distance_world, _path_cumulative,
                    _point_on_path_distance, wall_opening_intervals)
from .opening_controller import opening_wire


class OpeningHandleDragTool(Tool):
    name = "Arrastar hotspot de abertura"
    description = "Mova o ponteiro para editar a abertura e clique para confirmar; Esc cancela."
    uses_snap = False
    wireframe_color = (0.95, 0.52, 0.12, 1.0)
    vcb_label = "Abertura"

    def __init__(self, controller):
        self.controller = controller
        self.reset()

    def reset(self):
        self.wall = None
        self.opening_id = None
        self.handle_id = None
        self.action = None
        self.scene = None
        self.values = None
        self.original = None
        self.fill = None
        self.spec = None
        self.grip = None
        self.station = None
        self.preview_opening = None
        self.preview_value = None

    def prepare(self, wall, opening_id, handle_id, action):
        permitted = ("width", "position") if handle_id.startswith("bottom-") else ("width", "height")
        if action not in permitted:
            raise WallError("Operação não permitida neste hotspot.")
        self.reset()
        self.wall = wall
        self.opening_id = opening_id
        self.handle_id = handle_id
        self.action = action

    def on_activate(self, viewport):
        try:
            self.scene = viewport.scene
            if self.wall not in self.scene.groups or self.scene.edit_group is not None:
                raise WallError("Saia da edição da malha antes de editar o vão.")
            self.values = read_wall(self.wall)
            self.original = next(copy.deepcopy(o) for o in self.values["openings"]
                                 if o["id"] == self.opening_id)
            if self.original.get("kind") == "polygon":
                raise WallError("Use os controles de vértices para vãos poligonais.")
            self.fill = self.controller._find_linked_fill(self.original)
            self.spec = normalize_fill(_fill_record(self.fill)["params"]) if self.fill else None
            lines, grips = opening_wire(self.wall,self.values,self.original)
            self.grip = next(QVector3D(p) for name,p in grips if name == self.handle_id)
            self.station = self._station(self.grip)
            self.preview_opening = copy.deepcopy(self.original)
            self.preview_value = None
            self.controller.message(
                "Puxe o hotspot com o mouse e clique para aplicar. Esc cancela; Ctrl+Z desfaz.")
        except (WallError, StopIteration, ValueError) as exc:
            self.controller.message(str(exc), error=True)
            QTimer.singleShot(0,self.controller.return_to_select)
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset()
        viewport.update()

    def drag_plane(self, viewport):
        if self.wall is None or self.grip is None:
            return None
        path,cum=_path_cumulative(path_world(self.wall))
        station=max(0.0,min(cum[-1],self.station))
        idx=next((i for i in range(len(cum)-1) if cum[i+1]>=station-1e-9),len(cum)-2)
        tangent=path[idx+1]-path[idx]
        tangent.setZ(0)
        if tangent.length()<1e-8:
            return None
        tangent.normalize()
        normal=QVector3D(-tangent.y(),tangent.x(),0.0)
        return QVector3D(self.grip),normal

    def _station(self,world):
        path=path_world(self.wall)
        if len(path)==2:
            axis=path[1]-path[0]
            dist=axis.length()
            if dist>MIN_DIM:
                return QVector3D.dotProduct(QVector3D(world)-path[0],axis)/dist
        return nearest_path_distance_world(self.wall,world)

    def _candidate(self,world):
        """An independent logical opening; never mutate the source record."""
        s=self._station(world)
        original=self.original
        old_width=float(original["width"])
        width=old_width
        position=float(original["position"])
        height=float(original["height"])
        if self.action=="position":
            position=max(0.0,position+s-self.station)
        elif self.action=="width":
            side=self.handle_id.rsplit("-",1)[-1]
            factor={"left":-1.0,"right":1.0,"center":2.0}[side]
            width=max(MIN_DIM,min(MAX_DIM,old_width+(s-self.station)*factor))
        elif self.action=="height":
            height=max(MIN_DIM,min(MAX_DIM,
                height+float(world.z()-self.grip.z())))
        result=copy.deepcopy(original)
        result.update(position=position,width=width,height=height)
        raw=copy.deepcopy(self.values)
        raw["openings"]=[result if o["id"]==self.opening_id else o
                         for o in raw["openings"]]
        wall_opening_intervals(raw,path_world(self.wall))
        return result,{"position":position,"width":width,"height":height}

    def on_hover(self,ctx):
        if self.wall is None or ctx.viewport.scene is not self.scene:
            return
        try:
            opening,values=self._candidate(ctx.world)
        except (WallError,ValueError,KeyError):
            return
        self.preview_opening=opening
        self.preview_value=values
        ctx.viewport.update()

    def on_click(self,ctx):
        if self.preview_value is None:
            self.on_hover(ctx)
        if self.preview_value is None or self.wall is None:
            return
        try:
            if self.fill is not None:
                old=self.spec
                changes={key:value for key,value in self.preview_value.items()
                         if abs(value-float(old[key]))>1.e-8}
                if not changes:
                    self.controller.return_to_select()
                    return
                cmd=EditHostedFill(self.scene,self.wall,self.fill,changes)
            else:
                values=copy.deepcopy(self.values)
                values["openings"]=[
                    copy.deepcopy(self.preview_opening) if o["id"]==self.opening_id else o
                    for o in values["openings"]]
                cmd=EditWall(self.scene,self.wall,values)
            ctx.viewport.history.execute(cmd)
            if ctx.viewport.history.last_error:
                raise WallError(ctx.viewport.history.last_error)
            ctx.viewport.notify_scene_changed()
            self.controller._active_opening_wall=self.wall
            self.controller._active_opening_id=self.opening_id
            self.controller._loaded_key=None
            self.controller._state_key=None
            self.controller.message("Hotspot atualizado; Ctrl+Z para desfazer.")
            self.controller.return_to_select()
        except (WallError,ValueError,KeyError) as exc:
            self.controller.message(str(exc),error=True)
        ctx.viewport.update()

    def on_cancel(self,viewport):
        self.controller.return_to_select()
        viewport.update()

    def rubber_band_lines(self):
        if self.wall is None or self.preview_opening is None:
            return []
        try:
            lines,_grips=opening_wire(self.wall,self.values,self.preview_opening)
            return lines
        except (WallError,ValueError,KeyError,ZeroDivisionError):
            return []
