# SPDX-License-Identifier: GPL-3.0-or-later
"""Safe clipping of plugin overlay geometry before passing it to QPainter.

Qt's dashed-line stroke/rasterizer can generate screen-wide artifacts when
given a projected point millions of pixels outside a widget (for instance,
a wall endpoint near the camera plane). Keep all extension overlays within
the finite viewport; the 3D wall meshes remain untouched.
"""
from __future__ import annotations

import math


def visible_pixel(viewport, world, margin=32.0):
    """Visible clipped pixel suitable for a small square/circle hotspot."""
    p = viewport._world_to_pixel(world)
    if p is None or not all(math.isfinite(float(v)) for v in p):
        return None
    x, y = p
    if not (-margin <= x <= viewport.width()+margin and
            -margin <= y <= viewport.height()+margin):
        return None
    return float(x), float(y)


def visible_segment(viewport, a, b, margin=32.0):
    """3D near-plane + 2D widget clipping, always bounded before painting."""
    clip_3d = getattr(viewport, "_clip_segment_front", None)
    world_pair = clip_3d(a, b) if callable(clip_3d) else (a, b)
    if world_pair is None:
        return None
    p0 = viewport._world_to_pixel(world_pair[0])
    p1 = viewport._world_to_pixel(world_pair[1])
    if (p0 is None or p1 is None or
            any(not math.isfinite(float(v)) for v in (*p0, *p1))):
        return None
    clip_2d = getattr(viewport, "_clip_pixel_line", None)
    if callable(clip_2d):
        result = clip_2d(p0, p1, margin=margin)
        if result is None:
            return None
        return (tuple(map(float, result[0])), tuple(map(float, result[1])))
    # Compatibility fallback for older host builds: don't feed huge endpoints
    # to Qt even when the optional clip API is not available.
    x0, y0 = p0
    x1, y1 = p1
    left, right = -margin, viewport.width()+margin
    top, bottom = -margin, viewport.height()+margin
    dx, dy = x1-x0, y1-y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx,x0-left),(dx,right-x0),(-dy,y0-top),(dy,bottom-y0)):
        if abs(p)<1e-16:
            if q<0:return None
            continue
        t=q/p
        if p<0:t0=max(t0,t)
        else:t1=min(t1,t)
        if t0>t1:return None
    return ((x0+t0*dx,y0+t0*dy),(x0+t1*dx,y0+t1*dy))
