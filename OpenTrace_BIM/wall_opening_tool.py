# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive hosted wall-opening placement with pre-confirmation preview."""
from __future__ import annotations

import copy
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import Tool

from .commands import EditWall
from .door_window_commands import CreateHostedFill
from .door_window_core import normalize_fill
from .model import (
    MIN_DIM, WallError, _offset_path, _path_cumulative,
    _point_on_path_distance, _side_point_at_reference_distance,
    nearest_path_distance_world, path_world, profile_at_fraction,
    read_wall, wall_opening_intervals, wall_offsets, wall_path_kind,
)


class WallOpeningTool(Tool):
    """Place a rectangular hosted opening only after the user confirms it.

    The old palette button immediately cut a default opening.  This tool keeps
    the same parametric opening record but first projects a wire volume at the
    cursor.  A click commits exactly the candidate shown on screen.
    """
    name = "Criar abertura na parede"
    description = "Posicionar e pré-visualizar uma abertura hospedada antes de confirmar."
    uses_snap = True
    wireframe_color = (0.95, 0.38, 0.15, 1.0)
    vcb_label = "Posição"

    def __init__(self, controller):
        self.controller = controller
        self.reset()

    def reset(self):
        self.group = None
        self.anchor = None
        self.values = None
        self.length = 0.0
        self.position = 0.0
        self.item = None
        self.start_point = None
        self.kind = "opening"
        self.fill_anchor = "center"

    def prepare(self, group, anchor, *, kind="opening", fill_anchor="center"):
        if kind not in ("opening", "door", "window"):
            raise WallError("Ferramenta de vão desconhecida.")
        self.kind = kind
        self.fill_anchor = fill_anchor
        self.group = group
        self.anchor = QVector3D(anchor)
        self.start_point = QVector3D(anchor)

    def on_activate(self, viewport):
        if self.group is None or self.group not in viewport.scene.groups:
            QTimer.singleShot(0, self.controller.return_to_select)
            return
        try:
            if wall_path_kind(self.group) not in ("line", "arc"):
                raise WallError("Aberturas hospedadas estão disponíveis em paredes retas e curvas circulares.")
            self.values = read_wall(self.group)
            self.length = float(self.values["length"])
            h = min(float(t) - float(b) for b, t in zip(
                self.values.get("base_profile", [0, 0]),
                self.values.get("top_profile", [self.values["height"], self.values["height"]]),
            ))
            if self.length < 0.30 or h < 0.40:
                raise WallError("A parede é pequena demais para receber a abertura padrão.")
            if self.kind == "door":
                width, oh, sill = min(0.90, self.length * 0.50), 2.10, 0.0
            elif self.kind == "window":
                width, oh, sill = min(1.20, self.length * 0.50), 1.20, min(0.90, h*0.30)
            else:
                width = min(1.00, max(0.20, self.length * 0.30))
                oh = min(1.20, max(0.20, h * 0.45))
                sill = min(0.90, max(0.05, h - oh - 0.10))
                if sill + oh >= h - 0.05:
                    oh = max(0.10, h - sill - 0.10)
            self.position = nearest_path_distance_world(self.group, self.anchor)
            self.item = {
                "id": uuid.uuid4().hex, "kind": "rect", "position": self.position,
                "width": width, "sill": sill, "height": oh, "source_id": None,
            }
            self._clamp_position()
            self.controller.message(
                "Mova a abertura pela parede. O volume projetado é apenas uma prévia; clique para confirmar. "
                "Depois, largura, peitoril e altura continuam editáveis na paleta."
            )
        except WallError as exc:
            self.controller.message(str(exc), error=True)
            QTimer.singleShot(0, self.controller.return_to_select)
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset(); viewport.update()

    def drag_plane(self, viewport):
        if self.anchor is None:
            return None
        return QVector3D(0, 0, self.anchor.z()), QVector3D(0, 0, 1)

    def _clamp_position(self):
        if self.item is None:
            return
        margin = max(0.05, MIN_DIM * 5)
        half = min(self.length / 2 - margin, float(self.item.get("width", 0.0)) / 2 + margin)
        self.position = max(half, min(max(half, self.length - half), float(self.position)))
        self.item["position"] = self.position

    def _candidate_values(self):
        vals = copy.deepcopy(self.values)
        ops = list(vals.get("openings", [])); ops.append(copy.deepcopy(self.item))
        vals["openings"] = ops
        # Validation solves the actual host span (including curved-wall minimum
        # free width) and catches overlap / end-clearance before confirmation.
        wall_opening_intervals(vals, path_world(self.group))
        return vals

    def on_hover(self, ctx):
        if self.values is None:
            return
        try:
            self.position = nearest_path_distance_world(self.group, ctx.world)
            self._clamp_position()
            self._candidate_values()
        except WallError:
            # Keep the last visible candidate; commit will show the precise error.
            pass
        ctx.viewport.update()

    def _command(self, scene, values):
        if self.kind == "opening":
            return EditWall(scene, self.group, values)
        anchor_shift = {"left": -0.5, "center": 0.0, "right": 0.5}[self.fill_anchor]
        spec = normalize_fill({
            "id": uuid.uuid4().hex, "host_id": str(self.group.uid),
            "opening_id": self.item["id"], "kind": self.kind,
            "anchor": self.fill_anchor, "position": self.position + anchor_shift*self.item["width"],
            "width": self.item["width"], "height": self.item["height"],
            "sill": self.item["sill"],
        })
        return CreateHostedFill(scene, self.group, spec)

    def on_click(self, ctx):
        try:
            vals = self._candidate_values()
            ctx.viewport.history.execute(self._command(ctx.viewport.scene, vals))
            if ctx.viewport.history.last_error:
                raise WallError(ctx.viewport.history.last_error)
            self.controller._active_opening_id = self.item["id"]
            ctx.viewport.notify_scene_changed()
            self.controller._state_key = None
            self.controller.message("Vão e esquadria criados." if self.kind != "opening" else "Abertura hospedada criada.")
            self.reset(); self.controller.return_to_select()
        except WallError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_value(self, viewport, value):
        try:
            self.position = float(value)
            self._clamp_position()
            vals = self._candidate_values()
            viewport.history.execute(self._command(viewport.scene, vals))
            if viewport.history.last_error:
                raise WallError(viewport.history.last_error)
            self.controller._active_opening_id = self.item["id"]
            viewport.notify_scene_changed(); self.controller._state_key = None
            self.controller.message("Abertura hospedada criada.")
            self.reset(); self.controller.return_to_select(); return True
        except Exception as exc:
            self.controller.message(str(exc), error=True); return False

    def _wire(self):
        if self.group is None or self.item is None or self.values is None:
            return []
        path = path_world(self.group)
        try:
            interval = wall_opening_intervals(self._candidate_values(), path)[-1]
        except Exception:
            return []
        pts, cum = _path_cumulative(path)
        low_off, high_off = wall_offsets(self.values)
        low = _offset_path(pts, low_off); high = _offset_path(pts, high_off)
        s0, s1 = float(interval["s0"]), float(interval["s1"])
        L = max(cum[-1], MIN_DIM)
        f0, f1 = s0 / L, s1 / L
        b0, _t0, _ = profile_at_fraction(self.values, f0)
        b1, _t1, _ = profile_at_fraction(self.values, f1)
        z0a = float(self.values["base"]) + b0 + float(self.item["sill"])
        z0b = float(self.values["base"]) + b1 + float(self.item["sill"])
        z1a = z0a + float(self.item["height"]); z1b = z0b + float(self.item["height"])
        a0 = _side_point_at_reference_distance(low, cum, s0); a1 = _side_point_at_reference_distance(low, cum, s1)
        b0p = _side_point_at_reference_distance(high, cum, s0); b1p = _side_point_at_reference_distance(high, cum, s1)
        bottom = [QVector3D(a0.x(), a0.y(), z0a), QVector3D(a1.x(), a1.y(), z0b),
                  QVector3D(b1p.x(), b1p.y(), z0b), QVector3D(b0p.x(), b0p.y(), z0a)]
        top = [QVector3D(a0.x(), a0.y(), z1a), QVector3D(a1.x(), a1.y(), z1b),
               QVector3D(b1p.x(), b1p.y(), z1b), QVector3D(b0p.x(), b0p.y(), z1a)]
        lines = []
        for loop in (bottom, top):
            lines.extend((loop[i], loop[(i + 1) % 4]) for i in range(4))
        lines.extend((bottom[i], top[i]) for i in range(4))
        return lines

    def rubber_band_lines(self):
        return self._wire()

    def value_label(self):
        if self.item is None:
            return None
        return (f"{self.position:.4f} m".replace(".", ","),)

    def on_cancel(self, viewport):
        self.reset(); self.controller.return_to_select(); self.controller.message("Criação de abertura cancelada."); viewport.update()
