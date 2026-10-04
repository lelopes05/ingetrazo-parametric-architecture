# SPDX-License-Identifier: GPL-3.0-or-later
"""Parametric straight/curved beams with a spatial editable reference axis."""
from __future__ import annotations

import copy
import math
from PySide6.QtGui import QVector3D
from core.group import Group
from core.mesh import Mesh

from .curve_utils import soften_curve_facets
from .complex_profile import add_caps_and_sides, has_curved_edges, profile_loops
from .profile_library import resolve_profile

KEY = "arquitetura_parametrica"
SCHEMA = 1
MIN_DIM = 0.001
MAX_DIM = 10000.0
CIRCLE_SEGMENTS = 32
GEOMETRY_VERSION = 3
DEFAULTS = {
    "section_type": "simple", "profile_ref": None, "profile_data": None, "profile": "rect",
    "width": 0.10, "height": 0.10, "diameter": 0.10,
    "rotation": 0.0, "anchor": "mc",
    "base_level": None, "base_offset": 0.0, "base_z": 2.60,
    "material_name": None, "length": 1.0,
    "inclination": 0.0,
    # Horizontal (plan) sagitta; kept under the old key for file compatibility.
    "curvature": 0.0,
    # Vertical sagitta measured at mid-run relative to the straight slope chord.
    "vertical_curvature": 0.0,
}
FACE_KEY = "ap_beam_face"
ANCHOR_FACTORS = {
    "tl": (-0.5, 0.5), "tc": (0.0, 0.5), "tr": (0.5, 0.5),
    "ml": (-0.5, 0.0), "mc": (0.0, 0.0), "mr": (0.5, 0.0),
    "bl": (-0.5, -0.5), "bc": (0.0, -0.5), "br": (0.5, -0.5),
}


class BeamError(ValueError):
    pass


def validate(values):
    raw = dict(values or {})
    out = dict(DEFAULTS)
    out.update(raw)
    # 0.7.x stored the vertical section dimension as ``depth``.  Accept it and
    # expose both names while new UI/code uses the architectural term height.
    if "height" not in raw and "depth" in raw:
        out["height"] = raw.get("depth")
    try:
        for key in ("width", "height", "diameter", "rotation", "base_offset",
                    "base_z", "length", "inclination", "curvature",
                    "vertical_curvature"):
            out[key] = float(out.get(key, 0.0))
    except (TypeError, ValueError) as exc:
        raise BeamError("Preencha as medidas da viga com números válidos.") from exc
    if not all(math.isfinite(out[k]) for k in (
            "width", "height", "diameter", "rotation", "base_offset", "base_z",
            "length", "inclination", "curvature", "vertical_curvature")):
        raise BeamError("As medidas da viga devem ser números finitos.")
    if out.get("section_type") not in ("simple", "complex"):
        out["section_type"] = "simple"
    pr = out.get("profile_ref")
    out["profile_ref"] = str(pr).strip() if pr not in (None, "") else None
    if out["section_type"] == "complex":
        profile = resolve_profile(out.get("profile_ref"), out.get("profile_data"))
        if profile is None:
            raise BeamError("Perfil complexo não encontrado. Escolha um perfil salvo ou volte para Seção simples.")
        out["profile_ref"] = profile["id"]
        out["profile_data"] = profile
    else:
        out["profile_data"] = None
    if out.get("profile") not in ("rect", "circle"):
        raise BeamError("Forma simples de viga ainda não suportada.")
    for key in ("width", "height", "diameter", "length"):
        if not MIN_DIM <= out[key] <= MAX_DIM:
            raise BeamError("As dimensões da viga devem ficar entre 0,001 e 10.000 m.")
    if not -85.0 <= out["inclination"] <= 85.0:
        raise BeamError("A inclinação da viga deve ficar entre -85° e 85°.")
    if abs(out["curvature"]) > MAX_DIM or abs(out["vertical_curvature"]) > MAX_DIM:
        raise BeamError("A flecha da viga está fora do intervalo permitido.")
    if out.get("anchor") not in ANCHOR_FACTORS:
        out["anchor"] = "mc"
    lv = out.get("base_level")
    out["base_level"] = str(lv).strip() if lv not in (None, "") else None
    mat = out.get("material_name")
    out["material_name"] = str(mat).strip() if mat not in (None, "") else None
    # Compatibility alias only.  New records also write height explicitly.
    out["depth"] = out["height"]
    return out


def beam_record(group):
    ext = getattr(group, "ext", None)
    rec = ext.get(KEY) if isinstance(ext, dict) else None
    return rec if isinstance(rec, dict) and rec.get("kind") == "beam" else None


def _profile_yz(values):
    p = validate(values)
    ax, az = ANCHOR_FACTORS[p["anchor"]]
    if p["profile"] == "rect":
        cy = -ax * p["width"]
        cz = -az * p["height"]
        hw, hh = p["width"] / 2.0, p["height"] / 2.0
        raw = [(cy - hw, cz - hh), (cy + hw, cz - hh),
               (cy + hw, cz + hh), (cy - hw, cz + hh)]
    else:
        r = p["diameter"] / 2.0
        cy = -ax * p["diameter"]
        cz = -az * p["diameter"]
        raw = [(cy + r * math.cos(2 * math.pi * i / CIRCLE_SEGMENTS),
                cz + r * math.sin(2 * math.pi * i / CIRCLE_SEGMENTS))
               for i in range(CIRCLE_SEGMENTS)]
    a = math.radians(p["rotation"])
    ca, sa = math.cos(a), math.sin(a)
    return [(y * ca - z * sa, y * sa + z * ca) for y, z in raw]


def _complex_profile_loops_yz(values):
    p = validate(values)
    loops = profile_loops(p.get("profile_data"), rotation_deg=p.get("rotation", 0.0))
    if not loops:
        raise BeamError("O Perfil Complexo selecionado não contém contornos válidos.")
    return loops


def _plan_arc_points(chord, sagitta):
    chord, h = float(chord), float(sagitta)
    if chord < MIN_DIM:
        raise BeamError("A viga precisa ter comprimento em planta maior que 0,001 m.")
    if abs(h) > chord * 5.0:
        raise BeamError("A curvatura horizontal é fechada demais para esta viga.")
    try:
        from .model import arc_points
        return arc_points(QVector3D(0, 0, 0), QVector3D(chord, 0, 0), h)
    except Exception as exc:
        raise BeamError(str(exc)) from exc


def _circumcenter2(a, b, c):
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1.0e-12:
        return None
    aa = ax * ax + ay * ay
    bb = bx * bx + by * by
    cc = cx * cx + cy * cy
    ux = (aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / d
    uy = (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / d
    return ux, uy


def _vertical_z_values(run_positions, run_length, rise, sagitta):
    """Circular vertical profile z(s) over plan-path arclength ``s``.

    The sagitta is a vertical midpoint offset from the straight chord.  This
    keeps the projection in plan untouched while providing a true circular
    profile in the run/Z plane for ordinary architectural beam curvatures.
    """
    L = float(run_length)
    h = float(sagitta)
    rise = float(rise)
    if L < MIN_DIM:
        return [0.0 for _ in run_positions]
    if abs(h) < 1.0e-9:
        return [rise * (float(s) / L) for s in run_positions]
    if abs(h) > L * 5.0:
        raise BeamError("A curvatura vertical é fechada demais para esta viga.")
    mid = (L * 0.5, rise * 0.5 + h)
    centre = _circumcenter2((0.0, 0.0), mid, (L, rise))
    if centre is None:
        return [rise * (float(s) / L) for s in run_positions]
    cx, cz = centre
    radius = math.hypot(cx, cz)
    sign = 1.0 if mid[1] >= cz else -1.0
    vals = []
    for s in run_positions:
        rad = radius * radius - (float(s) - cx) ** 2
        if rad < -1.0e-7:
            raise BeamError("A curvatura vertical gera retorno sobre si mesma; reduza a flecha.")
        z = cz + sign * math.sqrt(max(0.0, rad))
        vals.append(z)
    # Numerical circle branch selection can be off by a constant epsilon;
    # pin exact endpoints to the model's semantic values.
    if vals:
        vals[0] = 0.0
        vals[-1] = rise
    return vals


def _resample_plan(plan, min_segments=20):
    """Resample a plan polyline by arclength.

    A straight plan path normally contains only its two endpoints.  Vertical
    curvature needs intermediate stations too, otherwise there is nothing for
    the vertical circle to bend.
    """
    if len(plan) < 2:
        return list(plan)
    cumulative = [0.0]
    for a, b in zip(plan, plan[1:]):
        cumulative.append(cumulative[-1] + math.hypot(b.x() - a.x(), b.y() - a.y()))
    total = cumulative[-1]
    if total < MIN_DIM:
        return list(plan)
    n = max(int(min_segments), len(plan) - 1)
    out = []
    seg = 0
    for i in range(n + 1):
        target = total * i / n
        while seg < len(cumulative) - 2 and target > cumulative[seg + 1]:
            seg += 1
        a, b = plan[seg], plan[seg + 1]
        lo, hi = cumulative[seg], cumulative[seg + 1]
        u = 0.0 if hi <= lo else (target - lo) / (hi - lo)
        out.append(a + (b - a) * u)
    return out


def _centerline_local(chord, values):
    p = validate(values)
    plan = _plan_arc_points(chord, p.get("curvature", 0.0))
    # A vertical arc must have tessellation even when the plan path is perfectly
    # straight.  Keep horizontal-curve samples, but densify when necessary.
    if abs(p.get("vertical_curvature", 0.0)) > 1.0e-9:
        plan = _resample_plan(plan, 24)
    cumulative = [0.0]
    for a, b in zip(plan, plan[1:]):
        cumulative.append(cumulative[-1] + math.hypot(b.x() - a.x(), b.y() - a.y()))
    plan_len = cumulative[-1]
    rise = plan_len * math.tan(math.radians(p.get("inclination", 0.0)))
    zvals = _vertical_z_values(cumulative, plan_len, rise,
                               p.get("vertical_curvature", 0.0))
    pts = [QVector3D(q.x(), q.y(), z) for q, z in zip(plan, zvals)]
    spatial_len = sum((b - a).length() for a, b in zip(pts, pts[1:]))
    return pts, spatial_len, plan_len


def _ring_frames(points):
    frames = []
    n = len(points)
    for i, c in enumerate(points):
        if i == 0:
            d = points[1] - points[0]
        elif i == n - 1:
            d = points[-1] - points[-2]
        else:
            d = points[i + 1] - points[i - 1]
        if d.length() < 1e-9:
            d = QVector3D(1, 0, 0)
        t = d.normalized()
        plan = QVector3D(t.x(), t.y(), 0)
        if plan.length() < 1e-9:
            plan = QVector3D(1, 0, 0)
        plan.normalize()
        width_axis = QVector3D(-plan.y(), plan.x(), 0)
        height_axis = QVector3D.crossProduct(t, width_axis)
        if height_axis.length() < 1e-9:
            height_axis = QVector3D(0, 0, 1)
        height_axis.normalize()
        frames.append((c, width_axis, height_axis))
    return frames


def build_body(chord, values, previous=None):
    p = validate(values)
    centers, spatial_len, _plan_len = _centerline_local(chord, p)
    mesh = Mesh()
    old, default = {}, None
    if previous is not None:
        for face in previous.mesh.faces:
            attrs = copy.deepcopy(face.attrs)
            key = attrs.get(FACE_KEY)
            if key is not None:
                old.setdefault(key, attrs)
            if default is None:
                default = copy.deepcopy(attrs)

    if p.get("section_type") == "complex":
        loops = _complex_profile_loops_yz(p)
        frames = _ring_frames(centers)
        add_caps_and_sides(mesh, frames, loops, FACE_KEY, old, default or {})
        if (abs(p.get("curvature", 0.0)) > 1e-9
                or abs(p.get("vertical_curvature", 0.0)) > 1e-9
                or has_curved_edges(p.get("profile_data"))):
            soften_curve_facets(mesh)
    else:
        prof = _profile_yz(p)
        rings = []
        for c, w, h in _ring_frames(centers):
            rings.append([c + w * y + h * z for y, z in prof])
        face = mesh.add_face(list(reversed(rings[0])))
        face.attrs.update(old.get("start", default or {})); face.attrs[FACE_KEY] = "start"
        face = mesh.add_face(rings[-1])
        face.attrs.update(old.get("end", default or {})); face.attrs[FACE_KEY] = "end"
        m = len(prof)
        for k in range(len(rings) - 1):
            a, b = rings[k], rings[k + 1]
            for i in range(m):
                j = (i + 1) % m
                face = mesh.add_face([a[i], a[j], b[j], b[i]])
                face.attrs.update(old.get("side", default or {})); face.attrs[FACE_KEY] = "side"
        if (abs(p.get("curvature", 0.0)) > 1e-9
                or abs(p.get("vertical_curvature", 0.0)) > 1e-9
                or p.get("profile") == "circle"):
            soften_curve_facets(mesh)
    group = Group(mesh, name="Corpo da viga")
    group.component = False
    if previous is not None:
        group.material = copy.deepcopy(previous.material)
        group.layer = previous.layer
    return group, spatial_len


def _record(p, length, chord):
    p = validate(dict(p, length=length))
    return {
        "schema": SCHEMA, "kind": "beam", "geometry_version": GEOMETRY_VERSION,
        "length": float(length), "chord": float(chord),
        "curvature": p.get("curvature", 0.0),
        "vertical_curvature": p.get("vertical_curvature", 0.0),
        "section_type": p["section_type"], "profile_ref": p.get("profile_ref"),
        "profile_data": copy.deepcopy(p.get("profile_data")),
        "profile": p["profile"], "width": p["width"],
        "height": p["height"], "depth": p["height"],
        "diameter": p["diameter"], "rotation": p["rotation"],
        "anchor": p["anchor"], "base_level": p.get("base_level"),
        "base_offset": p.get("base_offset", 0.0), "base_z": p["base_z"],
        "material_name": p.get("material_name"),
        "inclination": p.get("inclination", 0.0),
    }


def make_beam(start, end, values, template=None):
    p = validate(values)
    s, e = QVector3D(start), QVector3D(end)
    s.setZ(p["base_z"])
    dx, dy = e.x() - s.x(), e.y() - s.y()
    chord = math.hypot(dx, dy)
    if chord < MIN_DIM:
        raise BeamError("Indique dois pontos diferentes para a viga.")
    previous = template.children[0] if template is not None and getattr(template, "children", None) else None
    body, length = build_body(chord, p, previous)
    if length < MIN_DIM or length > MAX_DIM:
        raise BeamError("O comprimento resultante da viga está fora do intervalo permitido.")
    parent = Group(name=getattr(template, "name", None) or "Viga")
    parent.adopt([body]); parent.component = False
    parent.xform.translate(s.x(), s.y(), p["base_z"])
    parent.xform.rotate(math.degrees(math.atan2(dy, dx)), 0, 0, 1)
    parent.ext = {KEY: _record(p, length, chord)}
    if template is not None:
        parent.layer = getattr(template, "layer", None)
        parent.material = copy.deepcopy(getattr(template, "material", None))
        parent.ifc = copy.deepcopy(getattr(template, "ifc", None))
    if parent.ifc is None:
        parent.ifc = {"class": "IfcBeam", "name": parent.name}
    return parent


def read_beam(group):
    rec = beam_record(group)
    if rec is None or rec.get("schema") != SCHEMA:
        raise BeamError("Versão dos parâmetros da viga não reconhecida.")
    if len(getattr(group, "children", ())) != 1:
        raise BeamError("A estrutura da viga foi alterada. Desfaça para editar.")
    origin = group.xform.map(QVector3D(0, 0, 0))
    raw = dict(rec)
    if "height" not in raw and "depth" in raw:
        raw["height"] = raw.get("depth")
    raw.update(length=rec.get("length", 1.0),
               inclination=rec.get("inclination", 0.0),
               curvature=rec.get("curvature", 0.0),
               vertical_curvature=rec.get("vertical_curvature", 0.0),
               base_z=origin.z())
    p = validate(raw)
    p["length"] = float(rec.get("length", p["length"]))
    p["chord"] = float(rec.get("chord", max(MIN_DIM, p["length"] * abs(math.cos(math.radians(p["inclination"]))))))
    return p


def _legacy(group):
    rec = beam_record(group) or {}
    return int(rec.get("geometry_version", 0) or 0) < 2


def endpoints_world(group):
    p = read_beam(group)
    if _legacy(group):
        # Legacy geometry has no reliable spatial-axis record; preserve old
        # behaviour until its first parametric edit migrates the body.
        return (group.xform.map(QVector3D(0, 0, 0)),
                group.xform.map(QVector3D(p["length"], 0, 0)))
    pts, _length, _plan = _centerline_local(p.get("chord", MIN_DIM), p)
    return group.xform.map(pts[0]), group.xform.map(pts[-1])


def reference_path_world(group):
    p = read_beam(group)
    if _legacy(group):
        return list(endpoints_world(group))
    pts, _length, _plan = _centerline_local(p.get("chord", MIN_DIM), p)
    return [group.xform.map(q) for q in pts]


def reference_path_world_for(group, values):
    """Preview path in world coordinates, independent of legacy transforms."""
    a, b = endpoints_world(group)
    p = validate(values)
    dx, dy = b.x() - a.x(), b.y() - a.y()
    chord = math.hypot(dx, dy)
    if chord < MIN_DIM:
        return [a, b]
    local, _length, _plan = _centerline_local(chord, p)
    ang = math.atan2(dy, dx)
    ca, sa = math.cos(ang), math.sin(ang)
    return [QVector3D(a.x() + q.x() * ca - q.y() * sa,
                      a.y() + q.x() * sa + q.y() * ca,
                      a.z() + q.z()) for q in local]


def midpoint_world(group):
    pts = reference_path_world(group)
    if not pts:
        return endpoints_world(group)[0]
    return pts[len(pts) // 2]