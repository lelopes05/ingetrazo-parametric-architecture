# SPDX-License-Identifier: GPL-3.0-or-later
"""Horizontal parametric slab creation in three CAD-style modes."""
from __future__ import annotations

import math
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import AxisMagnet, Tool

from .commands import root_edit_allowed
from .slab_commands import CreateSlab
from .slab_model import (MIN_DIM, SlabError, actual_bottom, make_slab,
                         rectangle_base_width, rectangle_diagonal, validate_polygon)


class SlabTool(AxisMagnet, Tool):
    architecture_angle_snap = True
    name = "Laje paramétrica"
    description = "Desenhar laje horizontal por retângulo ou polígono."
    wireframe_color = (0.15, 0.45, 0.85, 1.0)
    vcb_label = "Laje"

    MODE_DIAGONAL = "diagonal"
    MODE_BASE_WIDTH = "base_width"
    MODE_POLYGON = "polygon"

    def __init__(self, controller):
        self.controller = controller
        self.mode = self.MODE_DIAGONAL
        self.points = []
        self.hover = None
        self.scene_at_start = None
        self.start_point = None
        self.chain_first_point = None

    def reset(self):
        self.mode = self.MODE_DIAGONAL
        self.points = []
        self.hover = None
        self.scene_at_start = None
        self.start_point = None
        self.chain_first_point = None
        self.controller.hide_mode_palette()

    def on_activate(self, viewport):
        self.reset(); self.controller.schedule_refresh()

    def on_deactivate(self, viewport):
        self.reset(); self.controller.schedule_refresh()

    def set_mode(self, mode):
        if mode not in (self.MODE_DIAGONAL, self.MODE_BASE_WIDTH, self.MODE_POLYGON):
            return
        self.mode = mode
        # The first point remains valid when changing construction method.
        if len(self.points) > 1:
            self.points = self.points[:1]
        self.chain_first_point = QVector3D(self.points[0]) if (mode == self.MODE_POLYGON and self.points) else None
        self.start_point = QVector3D(self.points[-1]) if self.points else None
        self.controller.message({
            self.MODE_DIAGONAL: "Retângulo por diagonal: indique o canto oposto.",
            self.MODE_BASE_WIDTH: "Retângulo por base: indique o fim da base e depois a largura.",
            self.MODE_POLYGON: "Polígono: indique os vértices e clique no primeiro para fechar.",
        }[mode])
        self.controller.app.viewport.update()

    def drag_plane(self, viewport):
        z = self.controller.current_reference_z()
        return QVector3D(0, 0, z), QVector3D(0, 0, 1)

    def point(self, ctx):
        z = self.controller.current_reference_z()
        return QVector3D(ctx.world.x(), ctx.world.y(), z)

    def _check_scene(self, viewport):
        if self.scene_at_start is not None and self.scene_at_start is not viewport.scene:
            self.reset()
        root_edit_allowed(viewport.scene)

    def _near_first(self, viewport, screen):
        if len(self.points) < 3:
            return False
        p = viewport._world_to_pixel(self.points[0])
        if p is None:
            return False
        dx, dy = float(screen.x()) - p[0], float(screen.y()) - p[1]
        threshold = max(8.0, float(getattr(viewport, "snap_threshold_px", 10.0)))
        return dx * dx + dy * dy <= threshold * threshold

    def on_click(self, ctx):
        try:
            self._check_scene(ctx.viewport)
            p = self.point(ctx)
            if not self.points:
                self.points = [p]
                self.hover = p
                self.start_point = QVector3D(p)
                self.chain_first_point = None
                self.scene_at_start = ctx.viewport.scene
                self.mode = self.MODE_DIAGONAL
                self.controller.show_mode_palette(ctx.screen)
                self.controller.message("Retângulo por diagonal ativo. Escolha outro método na paleta se quiser.")
            elif self.mode == self.MODE_DIAGONAL:
                self._commit(ctx.viewport, rectangle_diagonal(self.points[0], p))
            elif self.mode == self.MODE_BASE_WIDTH:
                if len(self.points) == 1:
                    if (p - self.points[0]).length() < MIN_DIM:
                        raise SlabError("Indique um segundo ponto diferente do primeiro.")
                    self.points.append(p)
                    self.hover = p
                    self.start_point = QVector3D(p)
                    self.controller.hide_mode_palette()
                    self.controller.message("Indique a largura para qualquer lado da base.")
                else:
                    self._commit(ctx.viewport, rectangle_base_width(self.points[0], self.points[1], p))
            else:
                self.controller.hide_mode_palette()
                if ((ctx.snap is not None and ctx.snap.kind == "close")
                        or self._near_first(ctx.viewport, ctx.screen)):
                    self._commit(ctx.viewport, self.points)
                else:
                    if (p - self.points[-1]).length() < MIN_DIM:
                        raise SlabError("Indique um vértice diferente do anterior.")
                    self.points.append(p)
                    self.hover = p
                    self.start_point = QVector3D(p)
                    self.chain_first_point = QVector3D(self.points[0]) if len(self.points) >= 2 else None
                    self.controller.message("Continue o polígono ou clique no primeiro vértice para fechar.")
        except SlabError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_hover(self, ctx):
        if self.scene_at_start is not None and self.scene_at_start is not ctx.viewport.scene:
            self.reset()
        self.hover = self.point(ctx)
        if self.mode == self.MODE_POLYGON and self.points:
            self.chain_first_point = QVector3D(self.points[0])
            self.start_point = QVector3D(self.points[-1])
        ctx.viewport.update()

    def _commit(self, viewport, polygon):
        poly = validate_polygon(polygon)
        group = make_slab(poly, self.controller.defaults)
        viewport.history.execute(CreateSlab(group))
        if viewport.history.last_error:
            raise SlabError(viewport.history.last_error)
        self.reset()
        viewport.notify_scene_changed()
        self.controller.message("Laje criada. Clique para iniciar outra; Esc para sair.")

    def on_cancel(self, viewport):
        if self.points:
            self.reset(); viewport.update()
            self.controller.message("Laje cancelada. Clique para iniciar outra; Esc para sair.")
        else:
            QTimer.singleShot(0, self.controller.stop_drawing)

    def _preview_polygon(self):
        if not self.points or self.hover is None:
            return None
        try:
            if self.mode == self.MODE_DIAGONAL and len(self.points) == 1:
                return rectangle_diagonal(self.points[0], self.hover)
            if self.mode == self.MODE_BASE_WIDTH and len(self.points) >= 2:
                return rectangle_base_width(self.points[0], self.points[1], self.hover)
        except SlabError:
            return None
        return None

    def rubber_band_lines(self):
        poly = self._preview_polygon()
        if poly is not None:
            z0 = actual_bottom(self.controller.defaults)
            z1 = z0 + self.controller.defaults["thickness"]
            bottom = [QVector3D(p.x(), p.y(), z0) for p in poly]
            top = [QVector3D(p.x(), p.y(), z1) for p in poly]
            lines = []
            for ring in (bottom, top):
                lines.extend((a, b) for a, b in zip(ring, ring[1:] + ring[:1]))
            lines.extend((bottom[i], top[i]) for i in range(len(poly)))
            return lines
        if self.mode == self.MODE_POLYGON and self.points:
            pts = list(self.points)
            if self.hover is not None:
                pts.append(self.hover)
            return [(a, b) for a, b in zip(pts, pts[1:])]
        if self.points and self.hover is not None:
            return [(self.points[-1], self.hover)]
        return []
