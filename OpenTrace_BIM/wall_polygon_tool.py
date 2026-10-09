# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw/edit a free wall opening in wall-local station/elevation coordinates.

This tool never edits the host's mesh directly.  Each confirmation is one
undoable EditWall command, preserving the wall and opening identities.
"""
from __future__ import annotations

import copy
import math
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import Tool

from .commands import EditWall
from .model import (
    WallError, _path_cumulative, _point_on_path_distance,
    nearest_path_distance_world, path_world, profile_at_fraction,
    read_wall, wall_opening_intervals, wall_path_kind,
)
from .wall_polygon import normalize_polygon


class WallPolygonTool(Tool):
    name = "Abertura livre na parede"
    description = "Desenhar uma abertura por vértices na elevação da parede."
    uses_snap = True
    wireframe_color = (0.93, 0.35, 0.16, 1.0)
    vcb_label = "Vértice"

    def __init__(self, controller):
        self.controller = controller
        self.reset()

    def reset(self):
        self.wall = None
        self.anchor = None
        self.points = []
        self.hover = None
        self.start_point = None
        self.chain_first_point = None
        self.mode = "create"
        self.opening_id = None
        self.vertex_index = None
        self.reference_path = []
        self.cumulative = []
        self.values = None
        self.plane_station = 0.0

    def prepare(self, wall, anchor, opening_id=None):
        self.reset()
        self.wall = wall
        self.anchor = QVector3D(anchor)
        self.mode = "edit" if opening_id else "create"
        self.opening_id = opening_id
        self.start_point = QVector3D(anchor)

    def on_activate(self, viewport):
        try:
            if self.wall is None or self.wall not in viewport.scene.groups:
                raise WallError("Selecione uma parede válida.")
            if wall_path_kind(self.wall) not in ("line", "arc"):
                raise WallError("Selecione uma parede reta ou curva circular.")
            self.values = read_wall(self.wall)
            self.reference_path, self.cumulative = _path_cumulative(path_world(self.wall))
            if self.cumulative[-1] <= 0.05:
                raise WallError("A parede é curta demais para essa abertura.")
            self.plane_station = nearest_path_distance_world(self.wall, self.anchor)
            if self.mode == "edit":
                opening = next((o for o in self.values.get("openings", [])
                                if o.get("id") == self.opening_id), None)
                if opening is None or opening.get("kind") != "polygon":
                    raise WallError("A abertura poligonal selecionada não está disponível.")
                self.points = [list(p) for p in opening["polygon"]]
                self.controller.message(
                    "Editar abertura: clique num vértice e depois na nova posição. "
                    "Esc cancela a ferramenta; cada movimento tem Undo/Redo.")
            else:
                self.controller.message(
                    "Abertura livre: clique os vértices na face da parede e "
                    "feche clicando no primeiro ponto. Esc cancela.")
        except (WallError, ValueError) as exc:
            self.controller.message(str(exc), error=True)
            QTimer.singleShot(0, self.controller.return_to_select)
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset()
        viewport.update()

    def _path_tangent(self, s):
        cum = self.cumulative
        pts = self.reference_path
        for i in range(len(pts)-1):
            if s <= cum[i+1]+1.0e-8:
                d = pts[i+1]-pts[i]
                d.setZ(0)
                if d.length() > 1.0e-9:
                    return d.normalized()
        d = pts[-1]-pts[-2]
        d.setZ(0)
        return d.normalized()

    def drag_plane(self, viewport):
        if not self.reference_path:
            if self.anchor is None:
                return None
            return QVector3D(self.anchor), QVector3D(0, 1, 0)
        s = max(0, min(self.cumulative[-1], self.plane_station))
        q = _point_on_path_distance(self.reference_path, self.cumulative, s)
        direction = self._path_tangent(s)
        normal = QVector3D(-direction.y(), direction.x(), 0)
        return QVector3D(q.x(), q.y(), self.anchor.z()), normal

    def _local(self, world):
        s = nearest_path_distance_world(self.wall, world)
        length = self.cumulative[-1]
        base, _top, _offset = profile_at_fraction(self.values, s/length)
        origin = self.wall.xform.map(QVector3D(0, 0, 0))
        return [float(s), float(world.z()-origin.z()-base)]

    def _world(self, point):
        s, z = point
        length = self.cumulative[-1]
        q = _point_on_path_distance(self.reference_path, self.cumulative, s)
        base, _top, _offset = profile_at_fraction(self.values, s/length)
        return QVector3D(q.x(), q.y(),
                         self.wall.xform.map(QVector3D(0, 0, 0)).z()+base+z)

    def _near_vertex(self, viewport, screen, point):
        projected = viewport._world_to_pixel(self._world(point))
        if projected is None:
            return False
        return math.hypot(float(screen.x())-projected[0],
                          float(screen.y())-projected[1]) <= max(
                              8.0, float(getattr(viewport, "snap_threshold_px", 10.0)))

    def _candidate(self, points, *, replace=False):
        polygon = normalize_polygon(points, self.values["length"])
        vals = copy.deepcopy(self.values)
        op = {"id": self.opening_id or uuid.uuid4().hex,
              "kind": "polygon", "polygon": polygon,
              "edges": [{"type": "line"} for _ in polygon],
              "source_id": None}
        if replace:
            for i, existing in enumerate(vals["openings"]):
                if existing.get("id") == self.opening_id:
                    op = dict(existing, polygon=polygon,
                              edges=[{"type": "line"} for _ in polygon])
                    vals["openings"][i] = op
                    break
            else:
                raise WallError("A abertura selecionada não existe mais.")
        else:
            vals["openings"].append(op)
        wall_opening_intervals(vals, path_world(self.wall))
        return vals, op["id"]

    def _commit(self, viewport, points, *, replace=False):
        try:
            vals, uid = self._candidate(points, replace=replace)
            viewport.history.execute(EditWall(viewport.scene, self.wall, vals))
            if viewport.history.last_error:
                raise WallError(viewport.history.last_error)
        except (ValueError, WallError) as exc:
            self.controller.message(str(exc), error=True)
            return False
        self.values = vals
        self.opening_id = uid
        self.controller._active_opening_id = uid
        self.controller._state_key = None
        viewport.notify_scene_changed()
        self.controller.message("Abertura poligonal atualizada." if replace else
                                "Abertura livre criada na parede.")
        return True

    def on_hover(self, ctx):
        if self.values is None:
            return
        self.plane_station = nearest_path_distance_world(self.wall, ctx.world)
        self.hover = self._local(ctx.world)
        if self.mode == "create" and self.points:
            self.start_point = self._world(self.points[-1])
            self.chain_first_point = self._world(self.points[0])
        ctx.viewport.update()

    def on_click(self, ctx):
        if self.values is None:
            return
        local = self._local(ctx.world)
        self.plane_station = local[0]
        if self.mode == "edit":
            if self.vertex_index is None:
                for i, p in enumerate(self.points):
                    if self._near_vertex(ctx.viewport, ctx.screen, p):
                        self.vertex_index = i
                        self.controller.message("Clique na nova posição deste vértice.")
                        break
                else:
                    self.controller.message("Clique num vértice da abertura para editá-lo.", error=True)
            else:
                candidate = copy.deepcopy(self.points)
                candidate[self.vertex_index] = local
                if self._commit(ctx.viewport, candidate, replace=True):
                    self.points = candidate
                    self.vertex_index = None
                    self.controller.message("Vértice movido. Selecione outro ou pressione Esc.")
        else:
            if len(self.points) >= 3 and self._near_vertex(
                    ctx.viewport, ctx.screen, self.points[0]):
                if self._commit(ctx.viewport, self.points):
                    self.reset()
                    self.controller.return_to_select()
            elif self.points and math.dist(self.points[-1], local) <= 1.0e-4:
                self.controller.message("Indique outro vértice.", error=True)
            else:
                self.points.append(local)
                self.hover = local
                self.start_point = self._world(local)
                self.chain_first_point = self._world(self.points[0]) if len(
                    self.points) >= 2 else None
        ctx.viewport.update()

    def rubber_band_lines(self):
        if self.wall is None or self.values is None:
            return []
        points = list(self.points)
        lines = list(zip(points, points[1:]))
        if self.mode == "edit" and len(points) >= 3:
            lines.append((points[-1], points[0]))
        if self.hover is not None and self.mode == "create" and points:
            lines.append((points[-1], self.hover))
        if self.mode == "edit" and self.vertex_index is not None and self.hover is not None:
            n = len(points)
            i = self.vertex_index
            lines.append((points[(i-1)%n], self.hover))
            lines.append((self.hover, points[(i+1)%n]))
        return [(self._world(a), self._world(b)) for a, b in lines]

    def on_cancel(self, viewport):
        self.reset()
        self.controller.return_to_select()
        self.controller.message("Ferramenta de abertura encerrada.")
        viewport.update()
