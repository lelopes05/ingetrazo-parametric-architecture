# SPDX-License-Identifier: GPL-3.0-or-later
"""Architecture-specific inference helpers layered on IngeTrazo's snap engine."""
from __future__ import annotations
import math
from PySide6.QtGui import QVector3D
from core.snap import SnapResult, COLOR_REFERENCE

# Architectural inference families requested for OpenTrace.  0/90 are normally
# supplied by the host, but remain here as a fallback when the native provider
# has no active axis inference for the current tool/plane.
_ARCH_ANGLES_DEG = (0.0, 35.0, 45.0, 90.0, 135.0, 145.0, 180.0,
                    215.0, 225.0, 270.0, 315.0, 325.0, 360.0)


def _angular_diff(a, b):
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)


def angular_snap_result(viewport, snap, _px, _py):
    """Offer architectural XY direction inferences.

    The host remains authoritative for concrete geometry snaps and its native
    principal axes.  OpenTrace adds 35° and 45° families (and principal-axis
    fallbacks).  The result uses the host ``reference`` snap kind, so the
    existing Shift sticky-inference mechanism can lock the highlighted guide
    until Shift is released / the next point is accepted.
    """
    tool = getattr(viewport, "active_tool", None)
    if tool is None or not getattr(tool, "architecture_angle_snap", False):
        return None
    start = getattr(tool, "start_point", None)
    if start is None or snap is None:
        return None
    # If the core already resolved a principal-axis inference, keep it.  It has
    # better integration with the viewport's own guide/Shift lock.
    if getattr(snap, "kind", None) in ("axis", "axis_inference"):
        return None
    p = QVector3D(snap.point)
    s = QVector3D(start)
    dx, dy = p.x() - s.x(), p.y() - s.y()
    radius = math.hypot(dx, dy)
    if radius < 1.0e-7:
        return None
    ang = math.atan2(dy, dx)
    candidates = [math.radians(d) for d in _ARCH_ANGLES_DEG]
    target = min(candidates, key=lambda x: _angular_diff(ang, x))
    diff = _angular_diff(ang, target)
    tolerance = math.radians(float(getattr(tool, "architecture_angle_snap_deg", 5.0)))
    if diff > tolerance:
        return None
    q = QVector3D(s.x() + radius * math.cos(target),
                  s.y() + radius * math.sin(target), p.z())
    deg = int(round(math.degrees(target))) % 360
    # Human-readable 180 rather than 0 when travelling toward -X.
    if deg == 0 and dx < 0:
        deg = 180
    if deg > 180:
        deg -= 180
    if deg == 0:
        deg = 180 if dx < 0 else 0
    # Conventional modelling colours for principal axes; architectural
    # diagonals keep the host reference colour.
    if deg in (0, 180):
        guide_color = (0.90, 0.22, 0.22)   # X / red
    elif deg == 90:
        guide_color = (0.20, 0.72, 0.30)   # Y / green
    else:
        guide_color = COLOR_REFERENCE
    return SnapResult(q, "reference", guide_color,
                      label=f"{deg}° · Shift trava",
                      guide=(s, q), guide_color=guide_color)
