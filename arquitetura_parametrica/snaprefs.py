# SPDX-License-Identifier: GPL-3.0-or-later
"""Snap provider for parametric wall reference lines."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D
from core.snap import SnapResult

from .model import (WallError, path_world, base_path_world, top_path_world, read_wall,
                    reference_vertices_world, base_reference_vertices_world, wall_record)
from .junctions import junction_snap_aliases

COLOR = (0.12, 0.55, 0.95)


def _nearest_on_screen(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    if den <= 1e-12:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / den
    t = max(0.0, min(1.0, t))
    qx, qy = ax + dx * t, ay + dy * t
    return math.hypot(px - qx, py - qy), t



def nearest_wall_reference_endpoint(viewport, px, py, *, base=None, exclude=None,
                                    threshold_px=None):
    """Return the nearest *reference* endpoint under the cursor.

    IngeTrazo deliberately protects its built-in named mesh snaps (endpoint,
    midpoint, intersection...) from extension providers.  For a wall this can
    mean that a visible physical corner wins over the architectural reference
    vertex beside it.  The wall drawing tool calls this helper explicitly so
    creating a wall on an existing wall end uses the exact reference vertex
    and therefore creates a real parametric junction.

    ``base`` limits candidates to the same horizontal wall plane.  This avoids
    accidentally joining floors that overlap on screen in a top view.
    """
    threshold = float(threshold_px if threshold_px is not None
                      else getattr(viewport, "snap_threshold_px", 12.0))
    best = None
    excluded = set(exclude or ())

    for group in list(viewport.scene.groups):
        if group in excluded or wall_record(group) is None:
            continue
        try:
            world = reference_vertices_world(group)
        except WallError:
            continue
        for point in world:
            if base is not None and abs(float(point.z()) - float(base)) > 1.0e-4:
                continue
            pixel = viewport._world_to_pixel(point)
            if pixel is None:
                continue
            d = math.hypot(float(px) - pixel[0], float(py) - pixel[1])
            if d <= threshold and (best is None or d < best[0]):
                best = (d, QVector3D(point))

    # A visible miter corner is an alias for its underlying reference node.
    # This is intentionally evaluated together with ordinary endpoints so the
    # candidate closest to the cursor wins.
    try:
        aliases = junction_snap_aliases(viewport.scene, base=base)
    except Exception:
        aliases = []
    for display, logical in aliases:
        pixel = viewport._world_to_pixel(display)
        if pixel is None:
            continue
        d = math.hypot(float(px) - pixel[0], float(py) - pixel[1])
        if d <= threshold and (best is None or d < best[0]):
            best = (d, QVector3D(logical))

    return None if best is None else best[1]

def snap_to_wall_references(app, viewport, snap, px, py):
    """Offer exact wall-axis endpoints and arbitrary points on wall axes.

    The reference line is an overlay, not native mesh geometry.  Without this
    provider, a visible architectural axis can look snappable while the host is
    actually snapping to one of the physical wall corners beside it.
    """
    threshold = float(getattr(viewport, "snap_threshold_px", 12.0))
    best_endpoint = None
    best_line = None

    for group in list(viewport.scene.groups):
        if wall_record(group) is None:
            continue
        try:
            world = base_path_world(group)
            endpoints = base_reference_vertices_world(group)
        except WallError:
            continue
        pixels = [viewport._world_to_pixel(p) for p in world]

        for point in endpoints:
            pixel = viewport._world_to_pixel(point)
            if pixel is None:
                continue
            d = math.hypot(px - pixel[0], py - pixel[1])
            if d <= threshold and (best_endpoint is None or d < best_endpoint[0]):
                best_endpoint = (d, QVector3D(point))

        for i, (a, b) in enumerate(zip(pixels, pixels[1:])):
            if a is None or b is None:
                continue
            d, t = _nearest_on_screen(px, py, a, b)
            if d <= threshold and (best_line is None or d < best_line[0]):
                point = world[i] + (world[i + 1] - world[i]) * t
                best_line = (d, QVector3D(point))

    # Visible miter corners also snap to the logical reference node.
    best_alias = None
    try:
        aliases = junction_snap_aliases(viewport.scene)
    except Exception:
        aliases = []
    for display, logical in aliases:
        pixel = viewport._world_to_pixel(display)
        if pixel is None:
            continue
        d = math.hypot(px - pixel[0], py - pixel[1])
        if d <= threshold and (best_alias is None or d < best_alias[0]):
            best_alias = (d, QVector3D(logical))

    # Pick the candidate physically nearest the cursor.  An alias often sits
    # exactly under a visible miter corner while the hidden reference node is
    # several pixels away, so it must be allowed to outrank the endpoint.
    candidates = []
    if best_endpoint is not None:
        candidates.append((best_endpoint[0], best_endpoint[1],
                           "Vértice de referência da parede"))
    if best_alias is not None:
        candidates.append((best_alias[0], best_alias[1],
                           "Junção da parede"))
    if candidates:
        _d, point, label = min(candidates, key=lambda item: item[0])
        return SnapResult(point, "reference", COLOR, label=label)
    if best_line is not None:
        return SnapResult(best_line[1], "reference", COLOR,
                          label="Linha de referência da parede")
    return None


def snap_to_wall_top_references(app, viewport, snap, px, py):
    """Offer the top path of every parametric wall as a height reference.

    Native named snaps (ordinary mesh vertices, endpoints, intersections, etc.)
    keep their priority in IngeTrazo.  This provider fills the architectural
    gap between those points: hovering anywhere along another wall's top lets
    the height handle acquire that wall's exact top Z, without creating a link.
    """
    threshold = float(getattr(viewport, "snap_threshold_px", 12.0))
    best = None
    for group in list(viewport.scene.groups):
        if wall_record(group) is None:
            continue
        try:
            top = top_path_world(group)
        except WallError:
            continue
        pixels = [viewport._world_to_pixel(p) for p in top]
        for i, (a, b) in enumerate(zip(pixels, pixels[1:])):
            if a is None or b is None:
                continue
            d, t = _nearest_on_screen(px, py, a, b)
            if d <= threshold and (best is None or d < best[0]):
                point = top[i] + (top[i + 1] - top[i]) * t
                best = (d, QVector3D(point), float(point.z()))
    if best is None:
        return None
    _d, point, z = best
    return SnapResult(point, "reference", COLOR,
                      label=f"Topo da parede · {z:+.3f} m")
