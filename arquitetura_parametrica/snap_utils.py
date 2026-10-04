# SPDX-License-Identifier: GPL-3.0-or-later
"""Architecture-specific inference helpers layered on IngeTrazo's snap engine."""
from __future__ import annotations
import math
from PySide6.QtGui import QVector3D
from core.snap import SnapResult, COLOR_REFERENCE


def angular_snap_result(viewport, snap, _px, _py):
    """Offer 45-degree XY inferences for architecture tools.

    Native X/Y/Z axis inference remains authoritative.  This provider only adds
    the missing diagonal families (45/135/225/315 degrees).  Because the result
    uses the host's ``reference`` snap kind, pressing Shift captures the active
    direction with IngeTrazo's native sticky-inference lock.
    """
    tool = getattr(viewport, "active_tool", None)
    if tool is None or not getattr(tool, "architecture_angle_snap", False):
        return None
    start = getattr(tool, "start_point", None)
    if start is None or snap is None:
        return None
    # A concrete native point/edge snap always wins before extension providers,
    # and a native principal-axis inference is better than our duplicate.
    if getattr(snap, "kind", None) in ("axis", "axis_inference"):
        return None
    p = QVector3D(snap.point)
    s = QVector3D(start)
    dx, dy = p.x() - s.x(), p.y() - s.y()
    radius = math.hypot(dx, dy)
    if radius < 1.0e-7:
        return None
    ang = math.atan2(dy, dx)
    step = math.pi / 4.0
    k = int(round(ang / step))
    # Principal axes are already provided by the core snap system.
    if k % 2 == 0:
        return None
    target = k * step
    diff = abs((ang - target + math.pi) % (2.0 * math.pi) - math.pi)
    tolerance = math.radians(float(getattr(tool, "architecture_angle_snap_deg", 5.0)))
    if diff > tolerance:
        return None
    q = QVector3D(s.x() + radius * math.cos(target),
                  s.y() + radius * math.sin(target), p.z())
    deg = int(round((math.degrees(target) % 180.0)))
    if deg == 0:
        deg = 180
    return SnapResult(q, "reference", COLOR_REFERENCE,
                      label=f"{deg}°", guide=(s, q), guide_color=COLOR_REFERENCE)