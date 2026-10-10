# SPDX-License-Identifier: GPL-3.0-or-later
"""Virtual, non-mesh wall opening controls (stage 01).

Openings remain records on their host wall. This module builds only short-lived
world-space outlines and hotspots for viewport overlays/picking; it does not
create invisible Mesh/Group cutters or edit the scene during mouse movement.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from .model import (_offset_path, _path_cumulative, _point_on_path_distance,
                    _side_point_at_reference_distance, path_world,
                    profile_at_fraction, wall_offsets, wall_opening_intervals)


def _context(wall, values):
    path = path_world(wall)
    points, cumulative = _path_cumulative(path)
    low, high = wall_offsets(values)
    origin_z = wall.xform.map(QVector3D(0, 0, 0)).z()
    return points, cumulative, _offset_path(points, low), _offset_path(points, high), origin_z


def _vertex(station, rise, side, cumulative, values, origin_z):
    length = cumulative[-1]
    s = max(0.0, min(length, float(station)))
    base, _, _ = profile_at_fraction(values, s / length)
    p = _side_point_at_reference_distance(side, cumulative, s)
    return QVector3D(p.x(), p.y(), origin_z + base + float(rise))


def opening_wire(wall, values, opening, *, context=None):
    """Return (line segments, screen-independent hotspots).

    Hotspot IDs encode physical position. Bottom handles allow width/position;
    top handles allow width/height. Polygon vertices use the existing vertex
    editor and never masquerade as rectangular grips.
    """
    if context is None:
        context = _context(wall, values)
    points, cumulative, low, high, origin_z = context
    if opening.get("kind") == "polygon":
        polygon = list(opening.get("polygon") or ())
        if len(polygon) < 3:
            return [], []
        near = [_vertex(s, z, low, cumulative, values, origin_z) for s, z in polygon]
        far = [_vertex(s, z, high, cumulative, values, origin_z) for s, z in polygon]
        lines = []
        for loop in (near, far):
            lines.extend((loop[i], loop[(i + 1) % len(loop)])
                         for i in range(len(loop)))
        lines.extend(zip(near, far))
        grips = [(f"vertex-{i}", p) for i, p in enumerate(near)]
        return lines, grips

    intervals = wall_opening_intervals(dict(values, openings=[opening]), points)
    if not intervals:
        return [], []
    item = intervals[0]
    s0, s1 = float(item["s0"]), float(item["s1"])
    sill, height = float(item["sill"]), float(item["height"])
    stations = (s0, s1)
    near_bottom = [_vertex(s, sill, low, cumulative, values, origin_z) for s in stations]
    far_bottom = [_vertex(s, sill, high, cumulative, values, origin_z) for s in stations]
    near_top = [_vertex(s, sill + height, low, cumulative, values, origin_z) for s in stations]
    far_top = [_vertex(s, sill + height, high, cumulative, values, origin_z) for s in stations]
    bottom = [near_bottom[0], near_bottom[1], far_bottom[1], far_bottom[0]]
    top = [near_top[0], near_top[1], far_top[1], far_top[0]]
    lines = []
    for loop in (bottom, top):
        lines.extend((loop[i], loop[(i + 1) % 4]) for i in range(4))
    lines.extend((bottom[i], top[i]) for i in range(4))
    # Mid-thickness controls are unambiguous in both directions of view.
    grips = []
    for row, rise in (("bottom", sill), ("top", sill + height)):
        for label, s in (("left", s0), ("center", (s0+s1)/2), ("right", s1)):
            a = _vertex(s, rise, low, cumulative, values, origin_z)
            b = _vertex(s, rise, high, cumulative, values, origin_z)
            grips.append((f"{row}-{label}", (a+b)*0.5))
    return lines, grips


def all_opening_wires(wall, values):
    """Build overlay data without rebuilding/meshing any physical wall."""
    if not values.get("openings"):
        return []
    context = _context(wall, values)
    result = []
    for opening in values["openings"]:
        try:
            lines, grips = opening_wire(wall, values, opening, context=context)
            result.append((str(opening["id"]), lines, grips))
        except (ValueError, KeyError, TypeError, ZeroDivisionError):
            # Legacy/malformed openings should never break the host viewport.
            continue
    return result


def _dist_segment(x, y, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    den = dx*dx+dy*dy
    u = 0.0 if den < 1e-10 else max(0.0, min(1.0,
          ((x-a[0])*dx+(y-a[1])*dy)/den))
    return ((x-a[0]-u*dx)**2+(y-a[1]-u*dy)**2)**0.5


def _inside_loop(x, y, loop):
    """Even/odd hit test on the visible wall-side outline in screen space."""
    n=len(loop)
    if n<3:
        return False
    inside=False
    for i in range(n):
        ax,ay=loop[i]
        bx,by=loop[(i+1)%n]
        if (ay>y)!=(by>y):
            cross=ax+(y-ay)*(bx-ax)/(by-ay)
            if x<cross:
                inside=not inside
    return inside


def _contains_visible_face(viewport, lines, x, y):
    """A click IN an empty opening is a valid pick, not only its perimeter."""
    if len(lines)<9 or len(lines)%3:
        return False
    n=len(lines)//3
    if n==4:
        # Rectangles use bottom/top thickness loops: reconstruct the
        # projected near and far wall faces rather than those thin quads.
        faces=(
            (lines[0][0],lines[0][1],lines[4][1],lines[4][0]),
            (lines[2][1],lines[2][0],lines[6][0],lines[6][1]),
        )
    else:
        # Polygon cutter first draws the near/far elevation perimeters.
        faces=(
            tuple(lines[i][0] for i in range(n)),
            tuple(lines[n+i][0] for i in range(n)),
        )
    for face in faces:
        screen=[viewport._world_to_pixel(v) for v in face]
        if None not in screen and _inside_loop(x,y,screen):
            return True
    return False


def hit_test(viewport, wires, x, y, *, active_id=None, threshold=9.0,
             allow_interior=False):
    """Pick the outline/hotspots and optionally the empty visible hole.

    Interior selection is restricted by the caller to EMPTY openings so a
    real Door/Window Group can still be selected by clicking its leaf/glass.
    """
    best=None
    for opening_id,lines,grips in wires:
        if opening_id==active_id:
            for handle_id,p in grips:
                q=viewport._world_to_pixel(p)
                if q is None:
                    continue
                d=((x-q[0])**2+(y-q[1])**2)**0.5
                if d<=threshold and (best is None or d<best[0]):
                    best=(d,opening_id,handle_id)
        for a,b in lines:
            pa,pb=viewport._world_to_pixel(a),viewport._world_to_pixel(b)
            if pa is None or pb is None:
                continue
            d=_dist_segment(x,y,pa,pb)
            if d<=threshold and (best is None or d<best[0]):
                best=(d,opening_id,None)
    if best is not None:
        return best[1],best[2]
    if allow_interior:
        for opening_id,lines,_grips in wires:
            if _contains_visible_face(viewport,lines,x,y):
                return opening_id,None
    return None
