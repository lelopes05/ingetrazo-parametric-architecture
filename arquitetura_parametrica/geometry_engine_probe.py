# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometry-engine laboratory for OpenTrace BIM.

This module is deliberately isolated from the extension runtime.  It compares
three ideas discovered while reviewing IngeTrazo, ArchXQ IT Lite and planArq:

* authoritative parametric paths (planArq / OpenTrace);
* analytic 2-D wall geometry until the final mesh (ArchXQ);
* native IngeTrazo manifold3d booleans for final 3-D cuts.

Run inside IngeTrazo's Python console:

    from arquitetura_parametrica.geometry_engine_probe import run_probe
    from pprint import pprint
    pprint(run_probe())

Nothing is inserted in or removed from the document.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.group import Group, world_mesh
from core.mesh import Mesh
from core.solids import SUBTRACT, run as run_solid_op, solid_volume

from .model import DEFAULTS, make_arc_wall, make_wall_segment


# ArchXQ's important architectural idea: keep line/circle geometry exact while
# resolving offsets, projections and intersections; tessellate only for output.
CHORD_ERROR = 0.002
MAX_STEP = math.radians(10.0)
EPS = 1.0e-9


def _box(name, xmin, xmax, ymin, ymax, zmin, zmax):
    pts = [
        QVector3D(xmin, ymin, zmin), QVector3D(xmax, ymin, zmin),
        QVector3D(xmax, ymax, zmin), QVector3D(xmin, ymax, zmin),
        QVector3D(xmin, ymin, zmax), QVector3D(xmax, ymin, zmax),
        QVector3D(xmax, ymax, zmax), QVector3D(xmin, ymax, zmax),
    ]
    mesh = Mesh()
    for ids in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([pts[i] for i in ids])
    group = Group(mesh, name=name)
    group.component = False
    return group


def _metrics(group):
    mesh = world_mesh(group)
    vol = solid_volume(group)
    return {
        "solid": vol is not None,
        "volume_m3": None if vol is None else round(float(vol), 9),
        "faces": len(mesh.faces),
        "edges": len(mesh.edges),
        "soft_edges": sum(bool(getattr(e, "soft", False)) for e in mesh.edges),
    }


def _cut(target, cutter):
    before = _metrics(target)
    cutter_stats = _metrics(cutter)
    removed, created = run_solid_op(SUBTRACT, [cutter, target])
    if len(created) != 1:
        raise RuntimeError(f"Subtract returned {len(created)} result groups.")
    result = created[0]
    after = _metrics(result)
    return {
        "ok": bool(before["solid"] and cutter_stats["solid"] and after["solid"]),
        "target_before": before, "cutter": cutter_stats, "result": after,
        "removed_count": len(removed), "created_count": len(created),
    }


def _wall_values():
    values = dict(DEFAULTS)
    values.update({"thickness": 0.20, "height": 3.00, "base": 0.00,
                   "alignment": "center", "openings": []})
    return values


# ---- analytic 2-D kernel ---------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, s):
    return (a[0] * s, a[1] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _length(a):
    return math.hypot(a[0], a[1])


def _unit(a):
    n = _length(a)
    return (a[0] / n, a[1] / n) if n > EPS else (0.0, 0.0)


class AnalyticSeg:
    """Straight line or circular arc used only as an exact construction object."""

    def __init__(self, kind, **kw):
        self.kind = kind
        if kind == "line":
            self.p0, self.p1 = tuple(kw["p0"]), tuple(kw["p1"])
            self.u = _unit(_sub(self.p1, self.p0))
            self.length = _length(_sub(self.p1, self.p0))
        else:
            self.center = tuple(kw["center"])
            self.radius = float(kw["radius"])
            self.a0 = float(kw["a0"])
            self.sweep = float(kw["sweep"])
            self.sign = 1.0 if self.sweep >= 0.0 else -1.0
            self.length = abs(self.sweep) * self.radius

    def at(self, f):
        if self.kind == "line":
            return _add(self.p0, _mul(_sub(self.p1, self.p0), f))
        a = self.a0 + self.sweep * f
        return (self.center[0] + self.radius * math.cos(a),
                self.center[1] + self.radius * math.sin(a))

    def tangent(self, f):
        if self.kind == "line":
            return self.u
        a = self.a0 + self.sweep * f
        return (-math.sin(a) * self.sign, math.cos(a) * self.sign)

    def offset(self, distance):
        if self.kind == "line":
            n = (-self.u[1] * distance, self.u[0] * distance)
            return AnalyticSeg("line", p0=_add(self.p0, n), p1=_add(self.p1, n))
        return AnalyticSeg("arc", center=self.center,
                           radius=self.radius - self.sign * distance,
                           a0=self.a0, sweep=self.sweep)

    def project(self, point):
        if self.kind == "line":
            v = _sub(point, self.p0)
            f = _dot(v, self.u) / self.length if self.length > EPS else 0.0
            return f, _cross(self.u, v)
        v = _sub(point, self.center)
        angle = math.atan2(v[1], v[0])
        rel = ((angle - self.a0 + math.pi) % (2.0 * math.pi) - math.pi) * self.sign
        if rel < -EPS:
            rel += 2.0 * math.pi
        f = rel / abs(self.sweep) if abs(self.sweep) > EPS else 0.0
        return f, (self.radius - _length(v)) * self.sign

    def sample(self):
        if self.kind == "line":
            return [self.p0, self.p1]
        if self.radius <= EPS:
            raise ValueError("Offset collapsed the arc radius.")
        # chord-error bound plus a maximum angular step, adapted from ArchXQ.
        cos_arg = max(-1.0, min(1.0, 1.0 - CHORD_ERROR / self.radius))
        chord_step = 2.0 * math.acos(cos_arg)
        step = min(MAX_STEP, chord_step if chord_step > EPS else MAX_STEP)
        n = max(2, int(math.ceil(abs(self.sweep) / step)))
        return [self.at(i / n) for i in range(n + 1)]


def _meet(a, b):
    """Exact intersections: line-line, line-circle and circle-circle."""
    if a.kind == "line" and b.kind == "line":
        den = _cross(a.u, b.u)
        if abs(den) < EPS:
            return []
        t = _cross(_sub(b.p0, a.p0), b.u) / den
        return [_add(a.p0, _mul(a.u, t))]
    if a.kind == "arc" and b.kind == "line":
        return _meet(b, a)
    if a.kind == "line":
        w = _sub(a.p0, b.center)
        bb = _dot(w, a.u)
        cc = _dot(w, w) - b.radius * b.radius
        disc = bb * bb - cc
        if disc < -EPS:
            return []
        root = math.sqrt(max(0.0, disc))
        return [_add(a.p0, _mul(a.u, -bb - root)),
                _add(a.p0, _mul(a.u, -bb + root))]
    dvec = _sub(b.center, a.center)
    d = _length(dvec)
    if d < EPS or d > a.radius + b.radius + EPS or d < abs(a.radius - b.radius) - EPS:
        return []
    x = (a.radius*a.radius - b.radius*b.radius + d*d) / (2.0*d)
    h = math.sqrt(max(0.0, a.radius*a.radius - x*x))
    e = _unit(dvec)
    mid = _add(a.center, _mul(e, x))
    n = (-e[1], e[0])
    return [_add(mid, _mul(n, h)), _add(mid, _mul(n, -h))]


def _arc_from_three(a, mid, b):
    ax, ay = a; mx, my = mid; bx, by = b
    d = 2.0 * (ax*(my-by) + mx*(by-ay) + bx*(ay-my))
    if abs(d) < EPS:
        return AnalyticSeg("line", p0=a, p1=b)
    aa=ax*ax+ay*ay; mm=mx*mx+my*my; bb=bx*bx+by*by
    cx=(aa*(my-by)+mm*(by-ay)+bb*(ay-my))/d
    cy=(aa*(bx-mx)+mm*(ax-bx)+bb*(mx-ax))/d
    r=math.hypot(ax-cx, ay-cy)
    a0=math.atan2(ay-cy, ax-cx); a1=math.atan2(by-cy, bx-cx)
    am=math.atan2(my-cy, mx-cx)
    ccw=((a1-a0)%(2*math.pi))
    through=((am-a0)%(2*math.pi))
    sweep=ccw if through <= ccw + EPS else -(2*math.pi-ccw)
    return AnalyticSeg("arc", center=(cx,cy), radius=r, a0=a0, sweep=sweep)


def probe_analytic_kernel():
    line = AnalyticSeg("line", p0=(0.0, 0.0), p1=(4.0, 0.0))
    arc = _arc_from_three((0.0, 0.0), (2.0, 1.0), (4.0, 0.0))
    other_arc = _arc_from_three((2.0, -1.0), (3.0, 0.0), (2.0, 1.0))
    half = 0.10
    line_faces = (line.offset(-half), line.offset(half))
    arc_faces = (arc.offset(-half), arc.offset(half))
    line_arc_hits = sum(len(_meet(x, y)) for x in line_faces for y in arc_faces)
    arc_arc_hits = sum(len(_meet(x, y)) for x in arc_faces
                       for y in (other_arc.offset(-half), other_arc.offset(half)))
    samples = arc.sample()
    return {
        "ok": line_arc_hits > 0 and arc_arc_hits > 0,
        "line_arc_face_intersections": line_arc_hits,
        "arc_arc_face_intersections": arc_arc_hits,
        "arc_radius_m": round(arc.radius, 9),
        "arc_length_m": round(arc.length, 9),
        "adaptive_output_segments": len(samples) - 1,
        "principle": "analytic-first, tessellate-last",
    }


# ---- native boolean probes -------------------------------------------------------

def probe_straight():
    wall = make_wall_segment(QVector3D(0, 0, 0), QVector3D(4, 0, 0),
                             _wall_values())
    cutter = _box("Probe cutter straight", 1.55, 2.45, -1, 1, 0.90, 2.10)
    return _cut(wall, cutter)


def probe_curved():
    wall = make_arc_wall(QVector3D(0, 0, 0), QVector3D(4, 0, 0), 1.0,
                         _wall_values())
    cutter = _box("Probe cutter curved", 1.55, 2.45, -0.50, 1.75, 0.90, 2.10)
    return _cut(wall, cutter)


def probe_multiple_openings():
    """Sequential cuts expose boolean stability and topology growth."""
    wall = make_wall_segment(QVector3D(0, 0, 0), QVector3D(6, 0, 0),
                             _wall_values())
    target = wall
    history = []
    for i, x in enumerate((1.5, 3.0, 4.5), 1):
        cutter = _box(f"Probe cutter {i}", x-0.40, x+0.40, -1, 1, 0.80, 2.20)
        before = _metrics(target)
        _removed, created = run_solid_op(SUBTRACT, [cutter, target])
        if len(created) != 1:
            raise RuntimeError(f"Cut {i} returned {len(created)} groups.")
        target = created[0]
        history.append({"cut": i, "before": before, "after": _metrics(target)})
    return {"ok": all(x["after"]["solid"] for x in history), "cuts": history}


def probe_curved_multiple_openings():
    wall = make_arc_wall(QVector3D(0, 0, 0), QVector3D(6, 0, 0), 1.2,
                         _wall_values())
    target = wall
    # Deliberately broad boxes: this is an engine stress test, not yet the
    # final hosted-opening shape/orientation policy.
    cutters = [
        _box("Curved cutter A", 0.9, 1.7, -0.5, 1.8, 0.7, 2.2),
        _box("Curved cutter B", 2.6, 3.4, -0.5, 2.2, 0.9, 2.4),
        _box("Curved cutter C", 4.3, 5.1, -0.5, 1.8, 0.7, 2.2),
    ]
    history = []
    for i, cutter in enumerate(cutters, 1):
        before = _metrics(target)
        _removed, created = run_solid_op(SUBTRACT, [cutter, target])
        if len(created) != 1:
            raise RuntimeError(f"Curved cut {i} returned {len(created)} groups.")
        target = created[0]
        history.append({"cut": i, "before": before, "after": _metrics(target)})
    return {"ok": all(x["after"]["solid"] for x in history), "cuts": history}


def run_probe():
    cases = (
        ("analytic_kernel", probe_analytic_kernel),
        ("straight_boolean", probe_straight),
        ("curved_boolean", probe_curved),
        ("multiple_openings", probe_multiple_openings),
        ("curved_multiple_openings", probe_curved_multiple_openings),
    )
    report = {"engine": "hybrid analytic-2D + core.solids/manifold3d"}
    for label, fn in cases:
        try:
            report[label] = fn()
        except Exception as exc:
            report[label] = {"ok": False, "error_type": type(exc).__name__,
                             "error": str(exc)}
    report["ok"] = all(report[name].get("ok", False) for name, _fn in cases)
    report["architecture"] = {
        "authoritative": "parametric path + hosted feature records",
        "construction": "analytic line/circle offsets and intersections",
        "output": "adaptive faceted mesh with soft technical seams",
        "cuts": "IngeTrazo native manifold3d booleans as derived geometry",
    }
    return report
