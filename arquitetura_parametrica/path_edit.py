# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive editing of a wall reference path and constrained placement."""
from __future__ import annotations

import math
import copy

from PySide6.QtCore import QTimer
from PySide6.QtGui import QMatrix4x4, QVector3D
from tools.base import AxisMagnet, Tool

from core.geometry import Face as PreviewFace
from core.history import MoveGroupCommand

from .commands import EditWall, ReplaceWallWithSegments, ReplaceArcWallWithArcs, ReshapeWall, SetWallArc
from .host import activate_select
from .levels import level_by_name
from .model import (ARC_EPS, MAX_DIM, MIN_DIM, WallError, arc_points,
                    arc_center_world, arc_sagitta_from_record, build_body, build_children, make_arc_wall,
                    make_wall_segment, path_world, read_wall, reference_vertices_world,
                    base_reference_vertices_world, top_reference_vertices_world,
                    wall_path_kind, wall_record, wall_reference_vertices, split_arc_at_point)


def _nearest_on_segment(p, a, b):
    d = b - a
    denom = QVector3D.dotProduct(d, d)
    if denom <= 1e-12:
        return QVector3D(a), 0.0, (p - a).length()
    t = QVector3D.dotProduct(p - a, d) / denom
    t = max(0.0, min(1.0, t))
    q = a + d * t
    return q, t, (p - q).length()


def nearest_on_path(p, points):
    best = None
    for i, (a, b) in enumerate(zip(points, points[1:])):
        q, t, dist = _nearest_on_segment(p, a, b)
        if best is None or dist < best[3]:
            best = (i, q, t, dist)
    return best


def _vertical_view_plane(viewport, origin):
    """A vertical plane facing the camera, stable for Z-only drags."""
    yaw = getattr(viewport.camera, "yaw", 0.0)
    normal = QVector3D(math.cos(yaw), math.sin(yaw), 0.0)
    if normal.length() < 1e-9:
        normal = QVector3D(1, 0, 0)
    return QVector3D(origin), normal.normalized()


def _preview_faces_for_segment(start, end, values, template):
    """Build shaded world-space faces for a temporary straight wall."""
    if (end - start).length() < MIN_DIM:
        return []
    g = make_wall_segment(start, end, values, template=template)
    out = []
    for body in g.children:
        for face in body.mesh.faces:
            loop = [g.xform.map(v.position) for v in face.loop]
            attrs = dict(getattr(face, "attrs", {}) or {})
            if not (attrs.get("color") or attrs.get("texture")):
                attrs.update(dict(getattr(template, "material", None) or {}))
            out.append(PreviewFace(loop, attrs=attrs))
    return out




def _preview_faces_for_arc(start, end, sagitta, values, template):
    """Build shaded world-space faces for a temporary curved wall."""
    try:
        g = make_arc_wall(start, end, sagitta, values, template=template)
    except WallError:
        return []
    out = []
    for body in g.children:
        for face in body.mesh.faces:
            loop = [g.xform.map(v.position) for v in face.loop]
            attrs = dict(getattr(face, "attrs", {}) or {})
            if not (attrs.get("color") or attrs.get("texture")):
                attrs.update(dict(getattr(template, "material", None) or {}))
            out.append(PreviewFace(loop, attrs=attrs))
    return out

class InsertVertexTool(AxisMagnet, Tool):
    architecture_angle_snap = True
    """Insert a point, drag it in XY, then split the path into wall objects."""
    name = "Inserir vértice da parede"
    description = "Insere um vértice e transforma cada trecho em uma parede independente."
    uses_snap = True
    wireframe_color = (0.12, 0.55, 0.95, 1.0)

    def __init__(self, controller):
        self.controller = controller
        self.group = None
        self.scene = None
        self.insert_index = None
        self.anchor_world = None
        self.hover_world = None
        self.start_point = None
        self.values = None

    def prepare(self, group):
        self.group = group
        self.scene = self.controller.app.scene
        self.insert_index = None
        self.anchor_world = None
        self.hover_world = None
        self.values = None

    def reset(self):
        self.group = None
        self.scene = None
        self.insert_index = None
        self.anchor_world = None
        self.hover_world = None
        self.values = None

    def on_activate(self, viewport):
        self.controller.hide_path_palette()
        if self.group is None:
            QTimer.singleShot(0, lambda: activate_select(self.controller.app))
            return
        self.controller.message("Clique no ponto da linha de referência onde deseja inserir o vértice.")
        viewport.update()

    def on_deactivate(self, viewport):
        self.insert_index = None
        self.anchor_world = None
        self.hover_world = None
        self.start_point = None
        self.values = None
        viewport.update()

    def drag_plane(self, viewport):
        if self.group is None:
            return None
        try:
            base = read_wall(self.group)["base"]
        except WallError:
            base = self.group.xform.map(QVector3D(0, 0, 0)).z()
        return QVector3D(0, 0, base), QVector3D(0, 0, 1)

    def _valid(self, viewport):
        if (self.group is None or self.scene is not viewport.scene
                or self.group not in viewport.scene.groups):
            raise WallError("A parede não está mais disponível. Selecione-a novamente.")

    def _flat(self, p):
        base = self.values["base"] if self.values is not None else p.z()
        return QVector3D(p.x(), p.y(), base)

    def on_click(self, ctx):
        try:
            self._valid(ctx.viewport)
            if self.insert_index is None:
                self.values = read_wall(self.group)
                point = self._flat(ctx.world)
                if wall_path_kind(self.group) == "arc":
                    refs = reference_vertices_world(self.group); rec = wall_record(self.group); h = arc_sagitta_from_record(rec)
                    if len(refs) != 2 or h is None:
                        raise WallError("Não foi possível ler a parede curva.")
                    q,h1,h2,_t = split_arc_at_point(refs[0],refs[1],h,point)
                    cmd=ReplaceArcWallWithArcs(ctx.viewport.scene,self.group,q,h1,h2)
                    ctx.viewport.history.execute(cmd)
                    if ctx.viewport.history.last_error:raise WallError(ctx.viewport.history.last_error)
                    ctx.viewport.notify_scene_changed();self.controller.message("Vértice inserido: o arco foi dividido em duas paredes curvas independentes.")
                    self.reset();activate_select(self.controller.app);ctx.viewport.update();return
                path = path_world(self.group)
                nearest = nearest_on_path(point, path)
                if nearest is None:
                    raise WallError("Não foi possível localizar a trajetória da parede.")
                seg, point, t, _dist = nearest
                seg_len = max((path[seg + 1] - path[seg]).length(), MIN_DIM)
                if t <= MIN_DIM / seg_len or (1.0 - t) <= MIN_DIM / seg_len:
                    raise WallError("O ponto está muito próximo de um vértice existente.")
                self.insert_index = seg + 1
                self.anchor_world = QVector3D(point)
                self.hover_world = QVector3D(point)
                self.start_point = QVector3D(point)
                self.controller.message(
                    "Vértice inserido. Mova-o no plano horizontal e clique para confirmar; "
                    "clique sem mover para apenas dividir a parede.")
            else:
                self.hover_world = self._flat(ctx.world)
                self.commit(ctx.viewport)
        except WallError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_hover(self, ctx):
        if self.group is None or self.insert_index is None:
            return
        try:
            self._valid(ctx.viewport)
            self.hover_world = self._flat(ctx.world)
        except WallError:
            return
        ctx.viewport.update()

    def _preview_path(self):
        if self.group is None or self.insert_index is None or self.hover_world is None:
            return None
        path = path_world(self.group)
        return path[:self.insert_index] + [QVector3D(self.hover_world)] + path[self.insert_index:]

    def commit(self, viewport):
        self._valid(viewport)
        new_path = self._preview_path()
        if new_path is None:
            raise WallError("Nenhum vértice em edição.")
        if ((new_path[self.insert_index] - new_path[self.insert_index - 1]).length() < MIN_DIM
                or (new_path[self.insert_index + 1] - new_path[self.insert_index]).length() < MIN_DIM):
            raise WallError("O vértice ficaria muito próximo de outro ponto.")
        cmd = ReplaceWallWithSegments(viewport.scene, self.group, new_path)
        viewport.history.execute(cmd)
        if viewport.history.last_error:
            raise WallError(viewport.history.last_error)
        viewport.notify_scene_changed()
        self.controller.message("Vértice criado. Cada trecho agora é uma parede independente.")
        self.reset()
        activate_select(self.controller.app)

    def on_cancel(self, viewport):
        self.reset()
        activate_select(self.controller.app)
        self.controller.message("Inserção de vértice cancelada.")
        viewport.update()

    def rubber_band_lines(self):
        preview = self._preview_path()
        if preview is None:
            return []
        return list(zip(preview, preview[1:]))

    def preview_faces(self):
        preview = self._preview_path()
        if preview is None or self.values is None or self.group is None:
            return []
        faces = []
        for a, b in zip(preview, preview[1:]):
            faces.extend(_preview_faces_for_segment(a, b, self.values, self.group))
        return faces


class ArcWallTool(Tool):
    """Pull a straight wall into a circular arc while keeping both ends fixed."""
    name = "Curvar parede em arco"
    description = "Mantém os extremos e define a flecha do arco no plano horizontal."
    uses_snap = True
    wireframe_color = (0.12, 0.55, 0.95, 1.0)
    vcb_label = "Flecha"

    def __init__(self, controller):
        self.controller = controller
        self.group = None
        self.scene = None
        self.anchor = None
        self.values = None
        self.sagitta = 0.0
        self.start_world = None
        self.end_world = None

    def prepare(self, group, anchor):
        self.group = group
        self.scene = self.controller.app.scene
        self.anchor = QVector3D(anchor)
        self.values = None
        self.sagitta = 0.0
        self.start_world = None
        self.end_world = None

    def reset(self):
        self.group = None
        self.scene = None
        self.anchor = None
        self.values = None
        self.sagitta = 0.0
        self.start_world = None
        self.end_world = None

    def _valid(self, viewport):
        if (self.group is None or self.scene is not viewport.scene
                or self.group not in viewport.scene.groups):
            raise WallError("A parede não está mais disponível. Selecione-a novamente.")
        if wall_path_kind(self.group) not in ("line", "arc"):
            raise WallError("Curvar em arco aceita, por enquanto, uma parede reta ou um arco existente.")

    def on_activate(self, viewport):
        self.controller.hide_path_palette()
        if self.group is None:
            QTimer.singleShot(0, lambda: activate_select(self.controller.app))
            return
        try:
            self._valid(viewport)
            self.values = read_wall(self.group)
            refs = reference_vertices_world(self.group)
            if len(refs) != 2:
                raise WallError("A parede precisa ter dois extremos para virar arco.")
            self.start_world, self.end_world = QVector3D(refs[0]), QVector3D(refs[1])
            rec = wall_record(self.group)
            self.sagitta = float(arc_sagitta_from_record(rec) or 0.0)
            self.controller.message(
                "Mova o mouse para um lado da linha e clique para definir a flecha do arco. "
                "Digite uma medida para precisão; flecha zero volta a parede para reta.")
        except WallError as exc:
            self.controller.message(str(exc), error=True)
            QTimer.singleShot(0, lambda: activate_select(self.controller.app))
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset()
        viewport.update()

    def drag_plane(self, viewport):
        if self.values is None:
            return None
        return QVector3D(0, 0, self.values["base"]), QVector3D(0, 0, 1)

    def _sagitta_from_world(self, world):
        a, b = self.start_world, self.end_world
        if a is None or b is None:
            return 0.0
        d = b - a
        length = math.hypot(d.x(), d.y())
        if length < MIN_DIM:
            return 0.0
        nx, ny = -d.y() / length, d.x() / length
        mid = (a + b) * 0.5
        return (world.x() - mid.x()) * nx + (world.y() - mid.y()) * ny

    def on_hover(self, ctx):
        if self.values is None:
            return
        try:
            self._valid(ctx.viewport)
            self.sagitta = self._sagitta_from_world(ctx.world)
        except WallError:
            return
        ctx.viewport.update()

    def _commit(self, viewport, sagitta):
        self._valid(viewport)
        cmd = SetWallArc(viewport.scene, self.group, float(sagitta))
        viewport.history.execute(cmd)
        if viewport.history.last_error:
            raise WallError(viewport.history.last_error)
        viewport.notify_scene_changed()
        if abs(float(sagitta)) < ARC_EPS:
            self.controller.message("Parede convertida novamente em reta.")
        else:
            self.controller.message("Parede curvada em arco.")
        self.reset()
        activate_select(self.controller.app)

    def on_click(self, ctx):
        try:
            self.sagitta = self._sagitta_from_world(ctx.world)
            self._commit(ctx.viewport, self.sagitta)
        except WallError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_value(self, viewport, value):
        try:
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise WallError("Digite uma flecha válida, por exemplo 0,50m.")
            h = float(value)
            # A positive typed value follows the side currently indicated by
            # the mouse, mirroring the ordinary CAD arc workflow. A negative
            # value explicitly chooses the opposite sign.
            if h >= 0.0 and self.sagitta < 0.0:
                h = -h
            self._commit(viewport, h)
            return True
        except WallError as exc:
            self.controller.message(str(exc), error=True)
            return False

    def on_cancel(self, viewport):
        self.reset()
        activate_select(self.controller.app)
        self.controller.message("Curvatura cancelada.")
        viewport.update()

    def _world_samples(self):
        if self.group is None or self.values is None:
            return []
        refs = wall_reference_vertices(self.group)
        if len(refs) != 2:
            return []
        try:
            local = arc_points(refs[0], refs[1], self.sagitta)
        except WallError:
            return []
        return [self.group.xform.map(p) for p in local]

    def rubber_band_lines(self):
        pts = self._world_samples()
        return list(zip(pts, pts[1:]))

    def preview_faces(self):
        if self.group is None or self.values is None:
            return []
        refs = wall_reference_vertices(self.group)
        if len(refs) != 2:
            return []
        try:
            local = arc_points(refs[0], refs[1], self.sagitta)
            bodies = build_children(self.values, previous_children=self.group.children, path=local,
                                    smooth_path=(len(local) > 2))
        except (WallError, ValueError):
            return []
        out = []
        for body in bodies:
            for face in body.mesh.faces:
                loop = [self.group.xform.map(v.position) for v in face.loop]
                attrs = dict(getattr(face, "attrs", {}) or {})
                if not (attrs.get("color") or attrs.get("texture")):
                    attrs.update(dict(getattr(self.group, "material", None) or {}))
                out.append(PreviewFace(loop, attrs=attrs))
        return out

    def value_label(self):
        return (f"{self.sagitta:.4f} m".replace(".", ","),)


class MoveWallVertexTool(AxisMagnet, Tool):
    """Move one endpoint freely in XY or extend/trim it along its current direction."""
    uses_snap = True
    wireframe_color = (0.12, 0.55, 0.95, 1.0)

    def __init__(self, controller, mode):
        self.controller = controller
        self.mode = mode  # "free" or "continue"
        self.architecture_angle_snap = (mode == "free")
        self.name = ("Mover vértice livremente" if mode == "free"
                     else "Continuar parede pelo vértice")
        self.description = ("Move o extremo no plano horizontal." if mode == "free"
                            else "Mantém a direção da reta ou continua o mesmo círculo do arco.")
        self.group = None
        self.scene = None
        self.anchor = None
        self.values = None
        self.kind = None
        self.endpoint = None
        self.refs = None
        self.hover = None
        self.original_sagitta = 0.0
        self.arc_center = None
        self.arc_radius = None
        self.arc_sign = 1.0
        self.move_reference = None

    def prepare(self, group, anchor):
        self.group = group
        self.scene = self.controller.app.scene
        self.anchor = QVector3D(anchor)
        self.start_point = None if self.mode == "free" else QVector3D(anchor)
        self.move_reference = None
        self.values = None
        self.kind = None
        self.endpoint = None
        self.refs = None
        self.hover = None
        self.original_sagitta = 0.0
        self.arc_center = None
        self.arc_radius = None
        self.arc_sign = 1.0

    def reset(self):
        self.group = self.scene = self.anchor = None
        self.start_point = None
        self.values = self.kind = self.endpoint = self.refs = self.hover = None
        self.original_sagitta = 0.0
        self.arc_center = None
        self.arc_radius = None
        self.arc_sign = 1.0
        self.move_reference = None

    def _valid(self, viewport):
        if (self.group is None or self.scene is not viewport.scene
                or self.group not in viewport.scene.groups):
            raise WallError("A parede não está mais disponível. Selecione-a novamente.")
        if wall_path_kind(self.group) not in ("line", "arc"):
            raise WallError("Mover vértice aceita, por enquanto, paredes retas ou curvas simples.")

    def on_activate(self, viewport):
        self.controller.hide_path_palette()
        if self.group is None or self.anchor is None:
            QTimer.singleShot(0, lambda: activate_select(self.controller.app))
            return
        try:
            self._valid(viewport)
            self.values = read_wall(self.group)
            self.kind = wall_path_kind(self.group)
            refs = reference_vertices_world(self.group)
            if len(refs) != 2:
                raise WallError("A parede precisa ter exatamente dois extremos para esta edição.")
            self.refs = [QVector3D(refs[0]), QVector3D(refs[1])]
            self.endpoint = 0 if (self.anchor - self.refs[0]).length() <= (self.anchor - self.refs[1]).length() else 1
            self.hover = QVector3D(self.refs[self.endpoint])
            if self.kind == "arc":
                rec = wall_record(self.group)
                self.original_sagitta = float(arc_sagitta_from_record(rec) or 0.0)
                self.arc_center = arc_center_world(self.group)
                if self.arc_center is None:
                    raise WallError("Não foi possível localizar o centro deste arco.")
                radial = self.refs[self.endpoint] - self.arc_center
                radial.setZ(0.0)
                self.arc_radius = radial.length()
                samples = path_world(self.group)
                if len(samples) >= 2:
                    r0 = samples[0] - self.arc_center
                    r1 = samples[1] - self.arc_center
                    cross = r0.x() * r1.y() - r0.y() * r1.x()
                    self.arc_sign = 1.0 if cross >= 0.0 else -1.0
            if self.mode == "free":
                self.controller.message(
                    "Clique no ponto de referência do movimento do vértice. "
                    "Depois escolha o destino; em arcos, a proporção da curvatura é preservada.")
            elif self.kind == "arc":
                self.controller.message(
                    "Mova o vértice ao longo do mesmo arco e clique para prolongar ou encurtar a parede.")
            else:
                self.controller.message(
                    "Mova o vértice ao longo da mesma direção e clique para prolongar ou encurtar a parede.")
        except WallError as exc:
            self.controller.message(str(exc), error=True)
            QTimer.singleShot(0, lambda: activate_select(self.controller.app))
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset()
        viewport.update()

    def drag_plane(self, viewport):
        if self.values is None:
            return None
        return QVector3D(0, 0, self.values["base"]), QVector3D(0, 0, 1)

    def _flat(self, p):
        z = self.values["base"] if self.values is not None else p.z()
        return QVector3D(p.x(), p.y(), z)

    def _candidate(self, cursor):
        p = self._flat(cursor)
        if self.refs is None or self.endpoint is None:
            return p
        if self.mode == "free":
            current = self.refs[self.endpoint]
            if self.move_reference is None:
                return QVector3D(current)
            ref = self._flat(self.move_reference)
            return QVector3D(current.x() + p.x() - ref.x(),
                             current.y() + p.y() - ref.y(),
                             current.z())
        if self.kind == "line":
            fixed = self.refs[1 - self.endpoint]
            current = self.refs[self.endpoint]
            direction = current - fixed
            length = math.hypot(direction.x(), direction.y())
            if length < MIN_DIM:
                return current
            u = QVector3D(direction.x() / length, direction.y() / length, 0.0)
            t = QVector3D.dotProduct(p - fixed, u)
            t = max(MIN_DIM, t)
            return fixed + u * t
        if self.arc_center is not None and self.arc_radius:
            radial = p - self.arc_center
            length = math.hypot(radial.x(), radial.y())
            if length < 1e-9:
                return QVector3D(self.refs[self.endpoint])
            return QVector3D(self.arc_center.x() + self.arc_radius * radial.x() / length,
                             self.arc_center.y() + self.arc_radius * radial.y() / length,
                             self.values["base"])
        return p

    @staticmethod
    def _sagitta_from_arc_mid(start, end, midarc):
        d = end - start
        length = math.hypot(d.x(), d.y())
        if length < MIN_DIM:
            raise WallError("O vértice ficaria muito próximo do outro extremo.")
        nx, ny = -d.y() / length, d.x() / length
        mid = (start + end) * 0.5
        return (midarc.x() - mid.x()) * nx + (midarc.y() - mid.y()) * ny

    def _continued_arc_sagitta(self, start, end):
        c = self.arc_center
        if c is None or self.arc_radius is None:
            raise WallError("Centro do arco indisponível.")
        a0 = math.atan2(start.y() - c.y(), start.x() - c.x())
        a1 = math.atan2(end.y() - c.y(), end.x() - c.x())
        if self.arc_sign >= 0.0:
            sweep = (a1 - a0) % (2.0 * math.pi)
        else:
            sweep = -((a0 - a1) % (2.0 * math.pi))
        if abs(sweep) < 1e-5 or abs(abs(sweep) - 2.0 * math.pi) < 1e-5:
            raise WallError("O arco resultante seria degenerado.")
        amid = a0 + sweep * 0.5
        midarc = QVector3D(c.x() + self.arc_radius * math.cos(amid),
                           c.y() + self.arc_radius * math.sin(amid), self.values["base"])
        return self._sagitta_from_arc_mid(start, end, midarc)

    def _spec(self, cursor=None):
        if self.refs is None or self.endpoint is None:
            return None
        candidate = self._candidate(cursor if cursor is not None else self.hover)
        start, end = QVector3D(self.refs[0]), QVector3D(self.refs[1])
        if self.endpoint == 0:
            start = candidate
        else:
            end = candidate
        chord = math.hypot(end.x() - start.x(), end.y() - start.y())
        if chord < MIN_DIM:
            return None
        if self.kind == "line":
            return start, end, None
        if self.mode == "continue":
            h = self._continued_arc_sagitta(start, end)
        else:
            old_chord = math.hypot(self.refs[1].x() - self.refs[0].x(),
                                   self.refs[1].y() - self.refs[0].y())
            if old_chord < MIN_DIM:
                return None
            h = self.original_sagitta * (chord / old_chord)
        if abs(h) < ARC_EPS:
            return None
        return start, end, h

    def on_hover(self, ctx):
        if self.values is None:
            return
        if self.mode == "free" and self.move_reference is None:
            return
        try:
            self._valid(ctx.viewport)
            self.hover = self._candidate(ctx.world)
        except WallError:
            return
        ctx.viewport.update()

    def on_click(self, ctx):
        try:
            self._valid(ctx.viewport)
            if self.mode == "free" and self.move_reference is None:
                self.move_reference = self._flat(ctx.world)
                self.start_point = QVector3D(self.move_reference)
                self.controller.message("Agora clique no ponto de destino do vértice.")
                ctx.viewport.update()
                return
            self.hover = self._candidate(ctx.world)
            spec = self._spec(self.hover)
            if spec is None:
                raise WallError("A nova posição não produz uma parede válida.")
            start, end, h = spec
            ctx.viewport.history.execute(ReshapeWall(ctx.viewport.scene, self.group, start, end, h))
            if ctx.viewport.history.last_error:
                raise WallError(ctx.viewport.history.last_error)
            ctx.viewport.notify_scene_changed()
            self.controller.message("Vértice movido.")
            self.reset()
            activate_select(self.controller.app)
        except WallError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_cancel(self, viewport):
        self.reset()
        activate_select(self.controller.app)
        self.controller.message("Movimento do vértice cancelado.")
        viewport.update()

    def rubber_band_lines(self):
        try:
            spec = self._spec()
        except WallError:
            return []
        if spec is None:
            return []
        start, end, h = spec
        if h is None:
            return [(start, end)]
        try:
            pts = arc_points(start, end, h)
        except WallError:
            return []
        return list(zip(pts, pts[1:]))

    def preview_faces(self):
        try:
            spec = self._spec()
        except WallError:
            return []
        if spec is None or self.values is None or self.group is None:
            return []
        start, end, h = spec
        if h is None:
            return _preview_faces_for_segment(start, end, self.values, self.group)
        return _preview_faces_for_arc(start, end, h, self.values, self.group)


class ConstrainedMoveWallTool(AxisMagnet, Tool):
    """Move one selected wall only in XY or only in Z."""
    uses_snap = True
    wireframe_color = (0.12, 0.55, 0.95, 1.0)

    def __init__(self, controller, mode):
        self.controller = controller
        self.mode = mode
        self.architecture_angle_snap = (mode == "xy")
        self.name = "Mover parede no plano" if mode == "xy" else "Mover parede na vertical"
        self.description = self.name
        self.group = None
        self.scene = None
        self.anchor = None
        self.start_point = None
        self.cursor_origin = None
        self.delta = QVector3D(0, 0, 0)
        self._previewing = False

    def prepare(self, group, anchor):
        self.group = group
        self.scene = self.controller.app.scene
        self.anchor = QVector3D(anchor)
        # Move is a two-click CAD gesture: first click picks the reference
        # point, second click picks the destination.  The selected wall
        # anchor only defines the editing plane; it is not the move origin.
        self.start_point = None
        self.cursor_origin = None
        self.delta = QVector3D(0, 0, 0)

    def reset(self):
        self.group = None
        self.scene = None
        self.anchor = None
        self.start_point = None
        self.cursor_origin = None
        self.delta = QVector3D(0, 0, 0)
        self._previewing = False

    def _valid(self, viewport):
        if (self.group is None or self.scene is not viewport.scene
                or self.group not in viewport.scene.groups):
            raise WallError("A parede não está mais disponível. Selecione-a novamente.")

    def on_activate(self, viewport):
        self.controller.hide_path_palette()
        if self.group is None or self.anchor is None:
            QTimer.singleShot(0, lambda: activate_select(self.controller.app))
            return
        try:
            self._valid(viewport)
            viewport.begin_groups_preview([self.group])
            self._previewing = True
            if self.mode == "xy":
                self.controller.message("Clique no ponto de referência para mover a parede no plano horizontal.")
            else:
                self.controller.message("Clique no ponto de referência para mover a parede na vertical.")
        except WallError as exc:
            self.controller.message(str(exc), error=True)
            QTimer.singleShot(0, lambda: activate_select(self.controller.app))

    def on_deactivate(self, viewport):
        if self._previewing:
            viewport.end_groups_preview()
        self.reset()
        viewport.update()

    def drag_plane(self, viewport):
        if self.anchor is None:
            return None
        if self.mode == "xy":
            return QVector3D(0, 0, self.anchor.z()), QVector3D(0, 0, 1)
        return _vertical_view_plane(viewport, self.anchor)

    def _delta_from(self, p):
        origin = self.cursor_origin if self.cursor_origin is not None else p
        if self.mode == "xy":
            return QVector3D(p.x() - origin.x(), p.y() - origin.y(), 0.0)
        return QVector3D(0.0, 0.0, p.z() - origin.z())

    def on_hover(self, ctx):
        if self.group is None or self.anchor is None:
            return
        try:
            self._valid(ctx.viewport)
            if self.cursor_origin is None:
                return
            self.delta = self._delta_from(ctx.world)
            if self._previewing:
                ctx.viewport.set_groups_preview_offset(self.delta)
        except WallError:
            return
        ctx.viewport.update()

    def on_click(self, ctx):
        try:
            self._valid(ctx.viewport)
            if self.cursor_origin is None:
                self.cursor_origin = QVector3D(ctx.world)
                self.start_point = QVector3D(ctx.world)
                self.controller.message("Agora clique no ponto de destino da parede.")
                ctx.viewport.update()
                return
            self.delta = self._delta_from(ctx.world)
            if self._previewing:
                ctx.viewport.end_groups_preview()
                self._previewing = False
            if self.delta.length() > 1e-9:
                if self.mode == "xy":
                    ctx.viewport.history.execute(MoveGroupCommand(self.group, self.delta))
                else:
                    # Vertical placement is a parametric base-cota edit, not a
                    # generic transform. Moving away from a named level turns
                    # the wall into a free absolute cota until level offsets
                    # are implemented.
                    values = read_wall(self.group)
                    values["base"] += self.delta.z()
                    values["base_level"] = None
                    ctx.viewport.history.execute(EditWall(ctx.viewport.scene, self.group, values))
                if ctx.viewport.history.last_error:
                    raise WallError(ctx.viewport.history.last_error)
                ctx.viewport.notify_scene_changed()
            self.controller.message(
                "Parede movida no plano horizontal." if self.mode == "xy"
                else "Parede movida na vertical; a cota passou a ser livre.")
            self.reset()
            activate_select(self.controller.app)
        except WallError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_cancel(self, viewport):
        if self._previewing:
            viewport.end_groups_preview()
            self._previewing = False
        self.reset()
        activate_select(self.controller.app)
        self.controller.message("Movimento cancelado.")
        viewport.update()


class ChangeWallHeightTool(Tool):
    """Edit only the selected upper endpoint of a wall.

    Typing a value sets the clear height at that endpoint (top minus local base),
    matching the architectural mental model used for stepped/sloped walls.
    """
    name = "Alterar altura do topo da parede"
    description = "Altera somente o topo da extremidade selecionada."
    uses_snap = True
    wireframe_color = (0.95, 0.62, 0.18, 1.0)
    vcb_label = "Altura do topo"

    def __init__(self, controller):
        self.controller = controller
        self.reset()

    def prepare(self, group, anchor):
        self.group = group; self.scene = self.controller.app.scene
        self.anchor = QVector3D(anchor); self.start_point = QVector3D(anchor)

    def reset(self):
        self.group=self.scene=self.anchor=self.start_point=None
        self.values=None; self.endpoint=None; self.base_refs=None; self.top_refs=None
        self.original_top=None; self.new_top=None; self.cursor_origin_z=None

    def _valid(self, viewport):
        if self.group is None or self.scene is not viewport.scene or self.group not in viewport.scene.groups:
            raise WallError("A parede não está mais disponível. Selecione-a novamente.")

    def on_activate(self, viewport):
        self.controller.hide_path_palette()
        if self.group is None or self.anchor is None:
            QTimer.singleShot(0, lambda: activate_select(self.controller.app)); return
        try:
            self._valid(viewport)
            self.values=read_wall(self.group)
            self.base_refs=base_reference_vertices_world(self.group)
            self.top_refs=top_reference_vertices_world(self.group)
            if len(self.top_refs)!=2: raise WallError("A parede precisa ter dois extremos para editar o topo.")
            self.endpoint=0 if (self.anchor-self.top_refs[0]).length() <= (self.anchor-self.top_refs[1]).length() else 1
            self.original_top=float(self.values["top_profile"][self.endpoint])
            self.new_top=self.original_top
            self.cursor_origin_z=self.anchor.z()
            self.controller.message("Mova este topo para cima/baixo e clique. Snap ajusta a cota; digitando, informe a altura local deste extremo.")
        except WallError as exc:
            self.controller.message(str(exc),error=True);QTimer.singleShot(0,lambda:activate_select(self.controller.app))
        viewport.update()

    def on_deactivate(self,viewport): self.reset(); viewport.update()
    def drag_plane(self,viewport): return _vertical_view_plane(viewport,self.anchor) if self.anchor is not None else None

    def _snap_top_local(self,ctx):
        if self.values is None or ctx.snap is None:return None
        kinds={"endpoint","midpoint","arc_midpoint","center","origin","component_origin","intersection","close","reference"}
        if getattr(ctx.snap,"kind",None) not in kinds:return None
        z=float(ctx.snap.point.z())-float(self.values["base"])
        if self.endpoint is None:return None
        if z-float(self.values["base_profile"][self.endpoint]) < MIN_DIM:return None
        return z

    def _candidate(self,ctx):
        snapped=self._snap_top_local(ctx)
        if snapped is not None:return snapped
        if self.cursor_origin_z is None:self.cursor_origin_z=ctx.world.z()
        return self.original_top + (ctx.world.z()-self.cursor_origin_z)

    def on_hover(self,ctx):
        if self.values is None:return
        z=self._candidate(ctx)
        minimum=float(self.values["base_profile"][self.endpoint])+MIN_DIM
        self.new_top=max(minimum,min(MAX_DIM,z));ctx.viewport.update()

    def _commit_top(self,viewport,top_local):
        self._valid(viewport)
        values=read_wall(self.group); ep=self.endpoint
        minimum=float(values["base_profile"][ep])+MIN_DIM
        top_local=max(minimum,min(MAX_DIM,float(top_local)))
        values["top_profile"]=list(values["top_profile"]);values["top_profile"][ep]=top_local
        values["height"]=max(float(values["top_profile"][i])-float(values["base_profile"][i]) for i in (0,1))
        # An individually edited top is no longer a single level-bound plane.
        values["top_mode"]="height";values["top_level"]=None;values["top_offset"]=0.0
        viewport.history.execute(EditWall(viewport.scene,self.group,values))
        if viewport.history.last_error:raise WallError(viewport.history.last_error)
        viewport.notify_scene_changed();self.controller.message("Altura desta extremidade atualizada.")
        self.reset();activate_select(self.controller.app)

    def on_click(self,ctx):
        try:self._commit_top(ctx.viewport,self._candidate(ctx))
        except WallError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()

    def on_value(self,viewport,value):
        try:
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<MIN_DIM:raise WallError("Digite uma altura positiva, por exemplo 2,70 m.")
            values=read_wall(self.group);ep=self.endpoint
            self._commit_top(viewport,float(values["base_profile"][ep])+float(value));return True
        except WallError as exc:self.controller.message(str(exc),error=True);return False

    def value_label(self):
        if self.new_top is None or self.values is None or self.endpoint is None:return None
        h=self.new_top-float(self.values["base_profile"][self.endpoint])
        p=QVector3D(self.anchor.x(),self.anchor.y(),float(self.values["base"])+self.new_top)
        return (f"{h:.4f} m".replace(".",","),p)

    def on_cancel(self,viewport): self.reset();activate_select(self.controller.app);self.controller.message("Alteração do topo cancelada.");viewport.update()


class MoveWallStationZTool(Tool):
    """Move one lower endpoint vertically while keeping its local wall height."""
    name="Mover extremidade da base na vertical"
    description="Sobe/desce a base e o topo correspondentes, preservando a altura local."
    uses_snap=True;wireframe_color=(0.12,0.55,0.95,1.0);vcb_label="Cota base"

    def __init__(self,controller):self.controller=controller;self.reset()
    def prepare(self,group,anchor):self.group=group;self.scene=self.controller.app.scene;self.anchor=QVector3D(anchor);self.start_point=None
    def reset(self):self.group=self.scene=self.anchor=self.start_point=None;self.values=None;self.endpoint=None;self.original_base=None;self.original_top=None;self.new_base=None;self.cursor_origin_z=None
    def _valid(self,viewport):
        if self.group is None or self.scene is not viewport.scene or self.group not in viewport.scene.groups:raise WallError("A parede não está mais disponível. Selecione-a novamente.")
    def on_activate(self,viewport):
        self.controller.hide_path_palette()
        if self.group is None or self.anchor is None:QTimer.singleShot(0,lambda:activate_select(self.controller.app));return
        try:
            self._valid(viewport);self.values=read_wall(self.group);refs=base_reference_vertices_world(self.group)
            self.endpoint=0 if (self.anchor-refs[0]).length()<=(self.anchor-refs[1]).length() else 1
            self.original_base=float(self.values["base_profile"][self.endpoint]);self.original_top=float(self.values["top_profile"][self.endpoint]);self.new_base=self.original_base;self.cursor_origin_z=None
            self.controller.message("Clique no ponto de referência do movimento vertical. Depois clique no destino; também pode digitar a cota absoluta.")
        except WallError as exc:self.controller.message(str(exc),error=True);QTimer.singleShot(0,lambda:activate_select(self.controller.app))
        viewport.update()
    def on_deactivate(self,viewport):self.reset();viewport.update()
    def drag_plane(self,viewport):return _vertical_view_plane(viewport,self.anchor) if self.anchor is not None else None
    def _raw_world_z(self,ctx):
        if ctx.snap is not None and getattr(ctx.snap,"kind",None) in {"endpoint","midpoint","arc_midpoint","center","origin","component_origin","intersection","close","reference"}:return float(ctx.snap.point.z())
        return float(ctx.world.z())
    def _candidate_world_z(self,ctx):
        if self.cursor_origin_z is None:return float(self.anchor.z())
        return float(self.anchor.z())+(self._raw_world_z(ctx)-self.cursor_origin_z)
    def on_hover(self,ctx):
        if self.values is None or self.cursor_origin_z is None:return
        self.new_base=self._candidate_world_z(ctx)-float(self.values["base"]);ctx.viewport.update()
    def _commit(self,viewport,world_z):
        self._valid(viewport);values=read_wall(self.group);ep=self.endpoint
        new_local=float(world_z)-float(values["base"]);delta=new_local-float(values["base_profile"][ep])
        values["base_profile"]=list(values["base_profile"]);values["top_profile"]=list(values["top_profile"])
        values["base_profile"][ep]+=delta;values["top_profile"][ep]+=delta
        values["base_level"]=None
        values["height"]=max(float(values["top_profile"][i])-float(values["base_profile"][i]) for i in (0,1))
        viewport.history.execute(EditWall(viewport.scene,self.group,values))
        if viewport.history.last_error:raise WallError(viewport.history.last_error)
        viewport.notify_scene_changed();self.controller.message("Cota da extremidade da base atualizada.");self.reset();activate_select(self.controller.app)
    def on_click(self,ctx):
        try:
            if self.cursor_origin_z is None:
                self.cursor_origin_z=self._raw_world_z(ctx);self.start_point=QVector3D(ctx.world)
                self.controller.message("Agora clique no ponto de destino da extremidade da base.");ctx.viewport.update();return
            self._commit(ctx.viewport,self._candidate_world_z(ctx))
        except WallError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_value(self,viewport,value):
        try:
            if not isinstance(value,(int,float)) or not math.isfinite(value):raise WallError("Digite uma cota válida.")
            self._commit(viewport,float(value));return True
        except WallError as exc:self.controller.message(str(exc),error=True);return False
    def value_label(self):
        if self.new_base is None or self.values is None:return None
        world_z=float(self.values["base"])+self.new_base
        return (f"{world_z:.4f} m".replace(".",","),QVector3D(self.anchor.x(),self.anchor.y(),world_z))
    def on_cancel(self,viewport):self.reset();activate_select(self.controller.app);self.controller.message("Movimento da base cancelado.");viewport.update()


class LeanWallTopTool(AxisMagnet, Tool):
    """Move only one upper endpoint in XY, creating wall lean/twist."""
    name="Inclinar parede pela extremidade superior"
    description="Desloca horizontalmente somente o topo selecionado."
    uses_snap=True;architecture_angle_snap=True;wireframe_color=(0.70,0.42,0.88,1.0);vcb_label="Inclinação"

    def __init__(self,controller):self.controller=controller;self.reset()
    def prepare(self,group,anchor):self.group=group;self.scene=self.controller.app.scene;self.anchor=QVector3D(anchor);self.start_point=QVector3D(anchor)
    def reset(self):self.group=self.scene=self.anchor=self.start_point=None;self.values=None;self.endpoint=None;self.base_ref=None;self.top_ref=None;self.hover=None;self.last_dir=None
    def _valid(self,viewport):
        if self.group is None or self.scene is not viewport.scene or self.group not in viewport.scene.groups:raise WallError("A parede não está mais disponível. Selecione-a novamente.")
    def on_activate(self,viewport):
        self.controller.hide_path_palette()
        if self.group is None or self.anchor is None:QTimer.singleShot(0,lambda:activate_select(self.controller.app));return
        try:
            self._valid(viewport);self.values=read_wall(self.group);bases=base_reference_vertices_world(self.group);tops=top_reference_vertices_world(self.group)
            self.endpoint=0 if (self.anchor-tops[0]).length()<=(self.anchor-tops[1]).length() else 1;self.base_ref=QVector3D(bases[self.endpoint]);self.top_ref=QVector3D(tops[self.endpoint]);self.hover=QVector3D(self.top_ref)
            off=self.top_ref-self.base_ref;off.setZ(0)
            if off.length()>1e-8:self.last_dir=off.normalized()
            self.controller.message("Mova somente o topo no plano horizontal para inclinar a parede. Digitar um valor define o ângulo em graus em relação à vertical.")
        except WallError as exc:self.controller.message(str(exc),error=True);QTimer.singleShot(0,lambda:activate_select(self.controller.app))
        viewport.update()
    def on_deactivate(self,viewport):self.reset();viewport.update()
    def drag_plane(self,viewport):return (QVector3D(0,0,self.top_ref.z()),QVector3D(0,0,1)) if self.top_ref is not None else None
    def _candidate(self,p):
        q=QVector3D(p.x(),p.y(),self.top_ref.z())
        d=q-self.base_ref;d.setZ(0)
        if d.length()>1e-8:self.last_dir=d.normalized()
        return q
    def on_hover(self,ctx):self.hover=self._candidate(ctx.world);ctx.viewport.update()
    def _values_for(self,world_top):
        values=read_wall(self.group);ep=self.endpoint
        inv,ok=self.group.xform.inverted()
        if not ok:raise WallError("Não foi possível converter a inclinação para a parede.")
        q=inv.map(QVector3D(world_top));refs=wall_reference_vertices(self.group);ref=refs[ep]
        values["top_xy"]=copy.deepcopy(values["top_xy"]);values["top_xy"][ep]=[q.x()-ref.x(),q.y()-ref.y()]
        return values
    def _commit(self,viewport,world_top):
        values=self._values_for(world_top);viewport.history.execute(EditWall(viewport.scene,self.group,values))
        if viewport.history.last_error:raise WallError(viewport.history.last_error)
        viewport.notify_scene_changed();self.controller.message("Inclinação da parede atualizada.");self.reset();activate_select(self.controller.app)
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,self._candidate(ctx.world))
        except WallError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_value(self,viewport,value):
        try:
            if not isinstance(value,(int,float)) or not math.isfinite(value) or abs(float(value))>=89.9:raise WallError("Digite uma inclinação entre -89° e 89°.")
            values=read_wall(self.group);ep=self.endpoint;height=float(values["top_profile"][ep])-float(values["base_profile"][ep])
            direction=self.last_dir
            if direction is None:
                # Default lean direction is perpendicular to the wall chord.
                bases=base_reference_vertices_world(self.group);d=bases[1]-bases[0];d.setZ(0)
                if d.length()<1e-9:direction=QVector3D(1,0,0)
                else:
                    d.normalize();direction=QVector3D(-d.y(),d.x(),0)
            offset=math.tan(math.radians(float(value)))*height
            q=QVector3D(self.base_ref.x()+direction.x()*offset,self.base_ref.y()+direction.y()*offset,self.top_ref.z())
            self._commit(viewport,q);return True
        except WallError as exc:self.controller.message(str(exc),error=True);return False
    def value_label(self):
        if self.hover is None or self.base_ref is None:return None
        horizontal=self.hover-self.base_ref;horizontal.setZ(0);vertical=abs(self.top_ref.z()-self.base_ref.z())
        angle=math.degrees(math.atan2(horizontal.length(),max(vertical,1e-9)))
        return (f"{angle:.2f}°".replace(".",","),self.hover)
    def on_cancel(self,viewport):self.reset();activate_select(self.controller.app);self.controller.message("Inclinação cancelada.");viewport.update()
    def rubber_band_lines(self):return [] if self.base_ref is None or self.hover is None else [(self.base_ref,self.hover)]

