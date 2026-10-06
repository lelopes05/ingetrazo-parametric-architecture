# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent straight walls: two clicks or start + direction + length."""
import math

from PySide6.QtCore import QTimer
from PySide6.QtGui import QMatrix4x4, QVector3D
from tools.base import AxisMagnet, Tool

from core.geometry import Face as PreviewFace

from .commands import CreateWall, CreateWalls, root_edit_allowed
from .model import (ARC_EPS, FACE_LOOPS, MIN_DIM, WallError, arc_points, build_body,
                    local_corners, make_arc_wall, make_wall, path_length, validate)
from .snaprefs import nearest_wall_reference_endpoint


class WallTool(AxisMagnet, Tool):
    architecture_angle_snap = True
    name = "Parede paramétrica"
    description = "Desenhar parede reta ou bloco retangular de quatro paredes."
    vcb_label = "Length"
    wireframe_color = (0.15, 0.45, 0.85, 1.0)

    MODE_SINGLE = "single"
    MODE_RECT_DIAGONAL = "rect_diagonal"
    MODE_RECT_BASE_WIDTH = "rect_base_width"

    def __init__(self, controller):
        self.controller = controller
        self.mode = self.MODE_SINGLE
        self.start_point = None
        self.second_point = None
        self.hover_point = None
        self.scene_at_start = None

    def reset(self):
        self.mode = self.MODE_SINGLE
        self.start_point = self.second_point = self.hover_point = self.scene_at_start = None
        if hasattr(self.controller, "hide_straight_mode_palette"):
            self.controller.hide_straight_mode_palette()
        if hasattr(self.controller, "fields"):
            self.controller.preview_length(0.0)

    def on_activate(self, viewport):
        self.reset()
        self.controller.schedule_refresh()

    def on_deactivate(self, viewport):
        self.reset()
        self.controller.schedule_refresh()

    def set_mode(self, mode):
        if mode not in (self.MODE_SINGLE, self.MODE_RECT_DIAGONAL, self.MODE_RECT_BASE_WIDTH):
            return
        self.mode = mode
        # The first click is always preserved.  Changing rectangular method
        # restarts only the post-first-click part of the construction.
        self.second_point = None
        self.hover_point = QVector3D(self.start_point) if self.start_point is not None else None
        labels = {
            self.MODE_SINGLE: "Parede reta: indique o ponto final.",
            self.MODE_RECT_DIAGONAL: "Bloco retangular por diagonal: indique o canto oposto.",
            self.MODE_RECT_BASE_WIDTH: "Bloco retangular por base + profundidade: indique o fim da base.",
        }
        self.controller.message(labels[mode])
        self.controller.app.viewport.update()

    def drag_plane(self, viewport):
        # Explicit even before the first click: face inference must not turn
        # a wall onto a vertical/sloping face or change the chosen elevation.
        base = self.controller.defaults["base"]
        return QVector3D(0, 0, base), QVector3D(0, 0, 1)

    def flatten(self, point):
        return QVector3D(point.x(), point.y(), self.controller.defaults["base"])

    def architectural_point(self, ctx):
        """Point used by the wall tool, prioritising wall reference vertices."""
        base = self.controller.defaults["base"]
        screen = ctx.screen
        hit = nearest_wall_reference_endpoint(
            ctx.viewport, screen.x(), screen.y(), base=base)
        return QVector3D(hit) if hit is not None else self.flatten(ctx.world)

    def _check_scene(self, viewport):
        if self.scene_at_start is not None and self.scene_at_start is not viewport.scene:
            self.reset()
        root_edit_allowed(viewport.scene)

    @staticmethod
    def _rectangle_diagonal(a, b):
        a, b = QVector3D(a), QVector3D(b)
        if abs(b.x() - a.x()) < MIN_DIM or abs(b.y() - a.y()) < MIN_DIM:
            raise WallError("A diagonal precisa definir largura e profundidade maiores que 1 mm.")
        return [QVector3D(a.x(), a.y(), a.z()),
                QVector3D(b.x(), a.y(), a.z()),
                QVector3D(b.x(), b.y(), a.z()),
                QVector3D(a.x(), b.y(), a.z())]

    @staticmethod
    def _rectangle_base_width(a, b, c):
        a, b, c = QVector3D(a), QVector3D(b), QVector3D(c)
        d = b - a
        d.setZ(0)
        length = math.hypot(d.x(), d.y())
        if length < MIN_DIM:
            raise WallError("A base do bloco precisa ter ao menos 1 mm.")
        u = QVector3D(d.x() / length, d.y() / length, 0.0)
        n = QVector3D(-u.y(), u.x(), 0.0)
        width = QVector3D.dotProduct(c - b, n)
        if abs(width) < MIN_DIM:
            raise WallError("A profundidade do bloco precisa ter ao menos 1 mm.")
        offset = n * width
        return [a, b, b + offset, a + offset]

    def on_click(self, ctx):
        try:
            self._check_scene(ctx.viewport)
            point = self.architectural_point(ctx)
            if self.start_point is None:
                self.start_point = point
                self.hover_point = point
                self.scene_at_start = ctx.viewport.scene
                self.mode = self.MODE_SINGLE
                self.controller.preview_length(0.0)
                if hasattr(self.controller, "show_straight_mode_palette"):
                    self.controller.show_straight_mode_palette(ctx.screen)
                self.controller.message(
                    "Parede reta ativa. Escolha na radial se quiser criar um bloco de quatro paredes.")
            elif self.mode == self.MODE_SINGLE:
                self.commit(ctx.viewport, point)
            elif self.mode == self.MODE_RECT_DIAGONAL:
                self.commit_rectangle(ctx.viewport, self._rectangle_diagonal(self.start_point, point))
            else:
                if self.second_point is None:
                    if (point - self.start_point).length() < MIN_DIM:
                        raise WallError("Indique um segundo ponto diferente do primeiro.")
                    self.second_point = point
                    self.hover_point = point
                    if hasattr(self.controller, "hide_straight_mode_palette"):
                        self.controller.hide_straight_mode_palette()
                    self.controller.message("Indique a profundidade para qualquer lado da base.")
                else:
                    self.commit_rectangle(
                        ctx.viewport,
                        self._rectangle_base_width(self.start_point, self.second_point, point))
        except WallError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_hover(self, ctx):
        if self.scene_at_start is not None and self.scene_at_start is not ctx.viewport.scene:
            self.reset()
        self.hover_point = self.architectural_point(ctx)
        if self.start_point is not None:
            origin = self.second_point if (self.mode == self.MODE_RECT_BASE_WIDTH and self.second_point is not None) else self.start_point
            self.controller.preview_length((self.hover_point - origin).length())
        ctx.viewport.update()

    def commit(self, viewport, end):
        self._check_scene(viewport)
        if self.start_point is None:
            raise WallError("Indique primeiro o início da parede.")
        group = make_wall(self.start_point, end, self.controller.defaults)
        viewport.history.execute(CreateWall(group))
        if viewport.history.last_error:
            raise WallError(viewport.history.last_error)
        self.reset()
        viewport.notify_scene_changed()
        self.controller.message("Parede criada. Clique para iniciar outra; Esc para sair.")

    def commit_rectangle(self, viewport, polygon):
        self._check_scene(viewport)
        if len(polygon) != 4:
            raise WallError("O bloco retangular precisa ter quatro lados.")
        groups = [make_wall(a, b, self.controller.defaults)
                  for a, b in zip(polygon, polygon[1:] + polygon[:1])]
        viewport.history.execute(CreateWalls(groups))
        if viewport.history.last_error:
            raise WallError(viewport.history.last_error)
        self.reset()
        viewport.notify_scene_changed()
        self.controller.message(
            "Bloco de quatro paredes criado. Cada lado permanece uma parede paramétrica independente.")

    def on_value(self, viewport, value):
        try:
            self._check_scene(viewport)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise WallError("Digite uma medida positiva, por exemplo 2,50m.")
            if self.start_point is None or self.hover_point is None:
                raise WallError("Clique no início e aponte uma direção antes de digitar.")

            # The classic single-wall workflow remains unchanged.
            if self.mode == self.MODE_SINGLE:
                direction = self.hover_point - self.start_point
                direction.setZ(0)
                if direction.length() < 1e-6:
                    raise WallError("Aponte a direção da parede com o mouse.")
                self.commit(viewport, self.start_point + direction.normalized() * value)
                return True

            # Base + depth accepts numeric entry for both stages, mirroring a
            # CAD rectangle: type the base length, then type the depth while
            # indicating which side of the base it should occupy.
            if self.mode == self.MODE_RECT_BASE_WIDTH:
                if self.second_point is None:
                    direction = self.hover_point - self.start_point
                    direction.setZ(0)
                    if direction.length() < 1e-6:
                        raise WallError("Aponte a direção da base com o mouse.")
                    self.second_point = self.start_point + direction.normalized() * value
                    self.hover_point = QVector3D(self.second_point)
                    if hasattr(self.controller, "hide_straight_mode_palette"):
                        self.controller.hide_straight_mode_palette()
                    self.controller.message("Base definida. Aponte o lado e digite/click a profundidade.")
                    viewport.update()
                    return True
                d = self.second_point - self.start_point
                d.setZ(0)
                length = math.hypot(d.x(), d.y())
                if length < MIN_DIM:
                    raise WallError("A base do bloco é inválida.")
                n = QVector3D(-d.y() / length, d.x() / length, 0.0)
                side = QVector3D.dotProduct(self.hover_point - self.second_point, n)
                if abs(side) < 1e-9:
                    side = 1.0
                probe = self.second_point + n * (value if side >= 0.0 else -value)
                self.commit_rectangle(
                    viewport,
                    self._rectangle_base_width(self.start_point, self.second_point, probe))
                return True

            raise WallError("No modo por diagonal, indique o canto oposto com o mouse.")
        except WallError as exc:
            self.controller.message(str(exc), error=True)
            return False

    def on_cancel(self, viewport):
        if self.start_point is not None:
            self.reset()
            viewport.update()
            self.controller.message("Trecho/bloco cancelado. Clique para iniciar; Esc para sair.")
        else:
            QTimer.singleShot(0, self.controller.stop_drawing)

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        origin = self.second_point if (self.mode == self.MODE_RECT_BASE_WIDTH and self.second_point is not None) else self.start_point
        distance = (self.hover_point - origin).length()
        return (
            f"{distance:.4f} m".replace(".", ","),
            QVector3D(self.hover_point),
        )

    def _preview_wall_lines(self, start, end):
        delta = end - start
        length = math.hypot(delta.x(), delta.y())
        if length < MIN_DIM:
            return []
        p = dict(self.controller.defaults, length=length)
        try:
            validate(p)
        except WallError:
            return []
        dx, dy = delta.x() / length, delta.y() / length
        points = [start + QVector3D(dx * v.x() - dy * v.y(),
                                    dy * v.x() + dx * v.y(), v.z())
                  for v in local_corners(p)]
        pairs = set()
        for _side, loop in FACE_LOOPS:
            for a, b in zip(loop, loop[1:] + loop[:1]):
                pairs.add(tuple(sorted((a, b))))
        return [(points[a], points[b]) for a, b in sorted(pairs)]

    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        if self.mode == self.MODE_SINGLE:
            return self._preview_wall_lines(self.start_point, self.hover_point)
        if self.mode == self.MODE_RECT_DIAGONAL:
            try:
                poly = self._rectangle_diagonal(self.start_point, self.hover_point)
            except WallError:
                return []
            return [line for a, b in zip(poly, poly[1:] + poly[:1])
                    for line in self._preview_wall_lines(a, b)]
        if self.second_point is None:
            return self._preview_wall_lines(self.start_point, self.hover_point)
        try:
            poly = self._rectangle_base_width(self.start_point, self.second_point, self.hover_point)
        except WallError:
            return self._preview_wall_lines(self.start_point, self.second_point)
        return [line for a, b in zip(poly, poly[1:] + poly[:1])
                for line in self._preview_wall_lines(a, b)]


class CurvedWallTool(WallTool):
    """Create a circular parametric wall using one of three CAD-style methods."""
    name = "Parede curva"
    description = "Desenhar parede curva por arco, centro ou três pontos."
    vcb_label = "Arc"

    MODE_NORMAL = "normal"
    MODE_CENTER = "center"
    MODE_THREE = "three"

    def __init__(self, controller):
        super().__init__(controller)
        self.mode = self.MODE_NORMAL
        self.first_point = None
        self.second_point = None
        self.hover_point = None
        self.scene_at_start = None

    def reset(self):
        self.first_point = self.second_point = self.hover_point = None
        self.scene_at_start = None
        self.mode = self.MODE_NORMAL
        if hasattr(self.controller, "hide_curve_mode_palette"):
            self.controller.hide_curve_mode_palette()
        if hasattr(self.controller, "fields"):
            self.controller.preview_length(0.0)

    def set_mode(self, mode):
        if mode not in (self.MODE_NORMAL, self.MODE_CENTER, self.MODE_THREE):
            return
        self.mode = mode
        # The first click is deliberately retained.  In centre mode that click
        # becomes the centre; in the other two it is the first wall point.
        self.second_point = None
        self.hover_point = self.first_point
        labels = {
            self.MODE_NORMAL: "Arco padrão: indique o segundo extremo e depois puxe a curva.",
            self.MODE_CENTER: "Arco pelo centro: o primeiro ponto é o centro. Indique agora o início da parede.",
            self.MODE_THREE: "Arco por 3 pontos: indique um ponto intermediário por onde o arco deve passar.",
        }
        self.controller.message(labels[mode])
        self.controller.app.viewport.update()

    def on_activate(self, viewport):
        self.reset()
        self.controller.schedule_refresh()

    def on_deactivate(self, viewport):
        self.reset()
        self.controller.schedule_refresh()

    def _check_scene(self, viewport):
        if self.scene_at_start is not None and self.scene_at_start is not viewport.scene:
            self.reset()
        root_edit_allowed(viewport.scene)

    @staticmethod
    def _cross2(a, b):
        return a.x() * b.y() - a.y() * b.x()

    @staticmethod
    def _wrap_pi(a):
        while a <= -math.pi:
            a += 2.0 * math.pi
        while a > math.pi:
            a -= 2.0 * math.pi
        return a

    def _sagitta_from_point(self, start, end, point):
        d = end - start
        length = math.hypot(d.x(), d.y())
        if length < MIN_DIM:
            raise WallError("Os dois extremos da parede curva estão muito próximos.")
        nx, ny = -d.y() / length, d.x() / length
        mid = (start + end) * 0.5
        return (point.x() - mid.x()) * nx + (point.y() - mid.y()) * ny

    def _center_spec(self, cursor):
        c, start = self.first_point, self.second_point
        if c is None or start is None:
            return None
        radius = math.hypot(start.x() - c.x(), start.y() - c.y())
        if radius < MIN_DIM:
            raise WallError("O raio precisa ter ao menos 1 mm.")
        vx, vy = cursor.x() - c.x(), cursor.y() - c.y()
        if math.hypot(vx, vy) < 1e-9:
            return None
        angle0 = math.atan2(start.y() - c.y(), start.x() - c.x())
        angle1 = math.atan2(vy, vx)
        sweep = self._wrap_pi(angle1 - angle0)
        if abs(sweep) < 1e-5:
            return None
        end = QVector3D(c.x() + radius * math.cos(angle0 + sweep),
                        c.y() + radius * math.sin(angle0 + sweep), start.z())
        amid = angle0 + sweep * 0.5
        arc_mid = QVector3D(c.x() + radius * math.cos(amid),
                            c.y() + radius * math.sin(amid), start.z())
        h = self._sagitta_from_point(start, end, arc_mid)
        return start, end, h

    @staticmethod
    def _circumcenter(a, b, c):
        ax, ay = a.x(), a.y(); bx, by = b.x(), b.y(); cx, cy = c.x(), c.y()
        d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-10:
            return None
        aa = ax * ax + ay * ay; bb = bx * bx + by * by; cc = cx * cx + cy * cy
        return QVector3D((aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / d,
                         (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / d,
                         a.z())

    def _three_spec(self, end):
        start, through = self.first_point, self.second_point
        if start is None or through is None:
            return None
        center = self._circumcenter(start, through, end)
        if center is None:
            return None
        a0 = math.atan2(start.y() - center.y(), start.x() - center.x())
        am = math.atan2(through.y() - center.y(), through.x() - center.x())
        a1 = math.atan2(end.y() - center.y(), end.x() - center.x())
        # Select the start→end sweep that actually passes through point 2.
        ccw = (a1 - a0) % (2.0 * math.pi)
        through_ccw = (am - a0) % (2.0 * math.pi)
        sweep = ccw if through_ccw <= ccw + 1e-9 else ccw - 2.0 * math.pi
        if abs(sweep) < 1e-5:
            return None
        r = math.hypot(start.x() - center.x(), start.y() - center.y())
        amid = a0 + sweep * 0.5
        arc_mid = QVector3D(center.x() + r * math.cos(amid),
                            center.y() + r * math.sin(amid), start.z())
        h = self._sagitta_from_point(start, end, arc_mid)
        return start, end, h

    def _current_spec(self):
        if self.first_point is None or self.second_point is None or self.hover_point is None:
            return None
        if self.mode == self.MODE_NORMAL:
            h = self._sagitta_from_point(self.first_point, self.second_point, self.hover_point)
            return self.first_point, self.second_point, h
        if self.mode == self.MODE_CENTER:
            return self._center_spec(self.hover_point)
        return self._three_spec(self.hover_point)

    def _valid_spec(self, spec):
        if spec is None:
            return None
        a, b, h = spec
        chord = math.hypot(b.x() - a.x(), b.y() - a.y())
        if chord < MIN_DIM or abs(h) < ARC_EPS:
            return None
        return a, b, h

    def on_click(self, ctx):
        try:
            self._check_scene(ctx.viewport)
            point = self.architectural_point(ctx)
            if self.first_point is None:
                self.first_point = self.hover_point = point
                self.scene_at_start = ctx.viewport.scene
                self.mode = self.MODE_NORMAL
                self.controller.show_curve_mode_palette(ctx.screen)
                self.controller.message(
                    "Arco padrão ativo. Indique o segundo extremo ou escolha outro método na paleta flutuante.")
            elif self.second_point is None:
                if (point - self.first_point).length() < MIN_DIM:
                    raise WallError("Indique um segundo ponto diferente do primeiro.")
                self.second_point = point
                self.hover_point = point
                self.controller.hide_curve_mode_palette()
                if self.mode == self.MODE_NORMAL:
                    self.controller.message("Puxe o arco para qualquer lado e clique para confirmar.")
                elif self.mode == self.MODE_CENTER:
                    self.controller.message("Indique o fim do arco; a distância ao centro define o raio.")
                else:
                    self.controller.message("Indique o terceiro ponto/fim da parede curva.")
            else:
                self.hover_point = point
                spec = self._valid_spec(self._current_spec())
                if spec is None:
                    raise WallError("Os pontos ainda não definem um arco válido.")
                self.commit(ctx.viewport, *spec)
        except WallError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_hover(self, ctx):
        if self.scene_at_start is not None and self.scene_at_start is not ctx.viewport.scene:
            self.reset()
        self.hover_point = self.architectural_point(ctx)
        spec = None
        try:
            spec = self._valid_spec(self._current_spec())
        except WallError:
            pass
        if spec is not None:
            a, b, h = spec
            try:
                pts = arc_points(QVector3D(0,0,0), QVector3D(math.hypot(b.x()-a.x(), b.y()-a.y()),0,0), h)
                self.controller.preview_length(path_length(pts))
            except WallError:
                pass
        ctx.viewport.update()

    def commit(self, viewport, start, end, sagitta):
        self._check_scene(viewport)
        group = make_arc_wall(start, end, sagitta, self.controller.defaults)
        viewport.history.execute(CreateWall(group))
        if viewport.history.last_error:
            raise WallError(viewport.history.last_error)
        self.reset()
        viewport.notify_scene_changed()
        self.controller.message("Parede curva criada. Clique para iniciar outra; Esc para sair.")

    def on_value(self, viewport, value):
        # Numeric sagitta is useful in the default endpoint method after point 2.
        try:
            if self.mode != self.MODE_NORMAL or self.first_point is None or self.second_point is None:
                raise WallError("A medida digitada está disponível após os dois extremos no arco padrão.")
            if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) < ARC_EPS:
                raise WallError("Digite uma flecha válida, por exemplo 0,50m.")
            h = float(value)
            try:
                current = self._sagitta_from_point(self.first_point, self.second_point, self.hover_point)
                if h >= 0.0 and current < 0.0:
                    h = -h
            except Exception:
                pass
            self.commit(viewport, self.first_point, self.second_point, h)
            return True
        except WallError as exc:
            self.controller.message(str(exc), error=True)
            return False

    def on_cancel(self, viewport):
        if self.first_point is not None:
            self.reset()
            viewport.update()
            self.controller.message("Arco cancelado. Clique para iniciar outro; Esc para sair.")
        else:
            QTimer.singleShot(0, self.controller.stop_drawing)

    def _preview_local(self, spec):
        a, b, h = spec
        chord = math.hypot(b.x()-a.x(), b.y()-a.y())
        angle = math.atan2(b.y()-a.y(), b.x()-a.x())
        samples = arc_points(QVector3D(0,0,0), QVector3D(chord,0,0), h)
        transform = QMatrix4x4()
        transform.translate(a.x(), a.y(), self.controller.defaults["base"])
        transform.rotate(math.degrees(angle), 0, 0, 1)
        return samples, transform

    def rubber_band_lines(self):
        if self.first_point is None or self.hover_point is None:
            return []
        if self.second_point is None:
            return [(self.first_point, self.hover_point)]
        try:
            spec = self._valid_spec(self._current_spec())
            if spec is None:
                return [(self.first_point, self.second_point), (self.second_point, self.hover_point)]
            samples, transform = self._preview_local(spec)
            world = [transform.map(p) for p in samples]
            return list(zip(world, world[1:]))
        except WallError:
            return [(self.first_point, self.second_point), (self.second_point, self.hover_point)]

    def preview_faces(self):
        if self.first_point is None or self.second_point is None or self.hover_point is None:
            return []
        try:
            spec = self._valid_spec(self._current_spec())
            if spec is None:
                return []
            samples, transform = self._preview_local(spec)
            vals = dict(self.controller.defaults)
            vals["length"] = path_length(samples)
            body = build_body(vals, path=samples, smooth_path=True)
        except (WallError, ValueError):
            return []
        out = []
        for face in body.mesh.faces:
            loop = [transform.map(v.position) for v in face.loop]
            out.append(PreviewFace(loop, attrs=dict(getattr(face, "attrs", {}) or {})))
        return out

    def value_label(self):
        if self.first_point is None or self.hover_point is None:
            return None
        if self.second_point is None:
            return ("Escolha o segundo ponto", QVector3D(self.hover_point))
        try:
            spec = self._valid_spec(self._current_spec())
        except WallError:
            spec = None
        if spec is None:
            return ("Definindo arco", QVector3D(self.hover_point))
        return (
            f"flecha {spec[2]:.4f} m".replace(".", ","),
            QVector3D(self.hover_point),
        )
