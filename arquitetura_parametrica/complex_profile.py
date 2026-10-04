# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers for reusable complex-profile geometry.

Saved profiles are 2D loops relative to their chosen origin.  These helpers
normalise winding/nesting and build closed swept solids without turning the
favourite library into a runtime dependency: callers should embed a snapshot of
the profile in their parametric record.
"""
from __future__ import annotations

import math
from PySide6.QtGui import QVector3D

_EPS = 1.0e-10


def signed_area(points):
    return 0.5 * sum(
        points[i][0] * points[(i + 1) % len(points)][1]
        - points[(i + 1) % len(points)][0] * points[i][1]
        for i in range(len(points))
    )


def point_in_polygon(point, polygon):
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)):
            den = (yj - yi)
            xx = (xj - xi) * (y - yi) / (den if abs(den) > _EPS else _EPS) + xi
            if x < xx:
                inside = not inside
        j = i
    return inside


def profile_loops(profile, rotation_deg=0.0, scale=1.0):
    """Return winding-normalised 2D loops from an embedded profile snapshot.

    Outer loops are CCW, holes CW.  Coordinates stay relative to the saved
    profile origin, which is the insertion/reference point of the BIM element.
    """
    if not isinstance(profile, dict):
        return []
    a = math.radians(float(rotation_deg or 0.0))
    ca, sa = math.cos(a), math.sin(a)
    s = float(scale)
    out = []
    for raw in profile.get("loops", ()):
        pts = raw.get("points") if isinstance(raw, dict) else None
        if not isinstance(pts, list) or len(pts) < 3:
            continue
        clean = []
        for p in pts:
            x, y = float(p[0]) * s, float(p[1]) * s
            clean.append((x * ca - y * sa, x * sa + y * ca))
        hole = bool(raw.get("hole", False))
        area = signed_area(clean)
        if (not hole and area < 0.0) or (hole and area > 0.0):
            clean.reverse()
            flags = list(reversed(list(raw.get("edges", ()) or ())))
        else:
            flags = list(raw.get("edges", ()) or ())
        out.append({"points": clean, "hole": hole, "edges": flags})
    return out


def grouped_loops(loops):
    """Group each hole under the smallest containing outer loop."""
    outers = [L for L in loops if not L.get("hole")]
    holes = [L for L in loops if L.get("hole")]
    groups = [{"outer": o, "holes": []} for o in outers]
    for hole in holes:
        hp = hole["points"][0]
        choices = []
        for idx, outer in enumerate(outers):
            if point_in_polygon(hp, outer["points"]):
                choices.append((abs(signed_area(outer["points"])), idx))
        if choices:
            groups[min(choices)[1]]["holes"].append(hole)
    return groups


def has_curved_edges(profile):
    for loop in (profile or {}).get("loops", ()):
        for edge in loop.get("edges", ()) if isinstance(loop, dict) else ():
            if isinstance(edge, dict) and (edge.get("curve") is not None or edge.get("soft")):
                return True
    return False


def map_loop(loop, center, axis_u, axis_v):
    return [center + axis_u * float(x) + axis_v * float(y)
            for x, y in loop["points"]]


def add_caps_and_sides(mesh, frames, loops, face_key, old_attrs=None, default_attrs=None):
    """Sweep 2D loops through frames and create a watertight mesh.

    ``frames`` is ``[(center, axis_u, axis_v), ...]`` where ``axis_u × axis_v``
    points along the sweep direction.  Profiles may contain multiple islands
    and holes.  Returns the generated ring coordinates for callers that need
    them for diagnostics.
    """
    old_attrs = old_attrs or {}
    default_attrs = default_attrs or {}
    if len(frames) < 2 or not loops:
        return []
    rings = []
    for center, u, v in frames:
        rings.append([map_loop(loop, center, u, v) for loop in loops])

    groups = grouped_loops(loops)
    index_of = {id(loop): i for i, loop in enumerate(loops)}
    # Start cap points opposite the first tangent: reverse outer and holes.
    for grp in groups:
        oi = index_of[id(grp["outer"])]
        hs = [index_of[id(h)] for h in grp["holes"]]
        outer0 = list(reversed(rings[0][oi]))
        holes0 = [list(reversed(rings[0][hi])) for hi in hs]
        f = mesh.add_face(outer0, holes0 or None)
        f.attrs.update(old_attrs.get("start", default_attrs)); f.attrs[face_key] = "start"
        outer1 = rings[-1][oi]
        holes1 = [rings[-1][hi] for hi in hs]
        f = mesh.add_face(outer1, holes1 or None)
        f.attrs.update(old_attrs.get("end", default_attrs)); f.attrs[face_key] = "end"

    # Side walls. Hole loops run opposite to outers, so this same quad order
    # naturally points their normals into the void.
    for k in range(len(rings) - 1):
        for li, loop in enumerate(loops):
            a, b = rings[k][li], rings[k + 1][li]
            n = len(a)
            for i in range(n):
                j = (i + 1) % n
                f = mesh.add_face([a[i], a[j], b[j], b[i]])
                f.attrs.update(old_attrs.get("side", default_attrs)); f.attrs[face_key] = "side"
    return rings