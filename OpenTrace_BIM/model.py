# SPDX-License-Identifier: GPL-3.0-or-later
"""Wall data and local geometry; no UI and no document mutations here.

A wall owns one reference path in its local XY plane. New walls are independent
straight segments. Polyline records from the 0.2.0 development build remain
readable so old test files can be opened and migrated by the split command.
"""
from __future__ import annotations

import bisect
import copy
import math

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.mesh import Mesh

from .layers import (bands_about_core, clone_layers, normalize_layers,
                     total_thickness, wall_overall_offsets)
from .curve_utils import soften_curve_facets, wrap_soft_surface_textures
from .materials import transfer_semantic_face_appearance

KEY = "arquitetura_parametrica"
DERIVED_KEY = "arquitetura_parametrica_derived"
SCHEMA = 1
MIN_DIM = 0.001
MAX_DIM = 10000.0
DEFAULTS = {"length": 1.0, "thickness": 0.10, "height": 3.0,
            "base": 0.0, "alignment": "left", "base_level": None,
            "top_mode": "height", "top_level": None, "top_offset": 0.0,
            "material_name": None, "structure": "simple", "layers": [], "openings": [],
            # Endpoint profiles are local to the wall group.  ``base_profile``
            # controls the lower edge at the two true endpoints; ``top_profile``
            # controls the upper edge.  ``top_xy`` offsets only the upper
            # endpoints in plan, allowing a wall to lean/twist while the base
            # reference path remains the modelling path.
            "base_profile": [0.0, 0.0], "top_profile": [3.0, 3.0],
            "top_xy": [[0.0, 0.0], [0.0, 0.0]]}
FACE_KEY = "ap_wall_side"
JOINT_FACE_KEY = "ap_wall_internal_joint"
# Kept for the straight-wall rubber-band preview.
FACE_LOOPS = (
    ("bottom", (3, 2, 1, 0)), ("top", (4, 5, 6, 7)),
    ("right", (0, 1, 5, 4)), ("end", (1, 2, 6, 5)),
    ("left", (2, 3, 7, 6)), ("start", (3, 0, 4, 7)),
)

ARC_MAX_STEP_DEG = 5.0
ARC_MAX_SEGMENT = 0.20
ARC_MAX_SAMPLES = 256
ARC_EPS = 1.0e-6


class WallError(ValueError):
    pass


def normalize_wall_openings(raw, length, height):
    """Normalize hosted openings.

    ``width`` is the architectural *largura livre no menor vão*.  On a straight
    wall this is identical to the distance along the reference line.  On a
    curved wall the actual hosted span is derived later from the two projected
    wall faces so the narrowest chord is exactly this value.
    """
    out=[]
    if not isinstance(raw,(list,tuple)):
        return out
    for i,item in enumerate(raw):
        if not isinstance(item,dict):
            continue
        if item.get("kind") in ("polygon", "embedded") or item.get("shape") == "polygon":
            from .wall_polygon import normalize_polygon
            edges = item.get("edges")
            pts_raw = item.get("polygon")
            if edges is not None and (not isinstance(edges, (list, tuple)) or
                    len(edges) != len(pts_raw or ()) or
                    any(not isinstance(e, dict) or e.get("type", "line") != "line"
                        for e in edges)):
                raise WallError("Arestas curvas da abertura poligonal ainda não são suportadas.")
            try:
                polygon = normalize_polygon(pts_raw, length, allow_outside=True)
            except (ValueError, TypeError, OverflowError) as exc:
                raise WallError(str(exc)) from exc
            # Wall clearance may be sloped. Test actual base/top profiles
            # when resolving the hosted span, never against the min height.
            item_copy = {
                "id": str(item.get("id") or f"wall-opening-{i+1}"),
                "kind": "polygon", "polygon": polygon,
                "edges": [{"type": "line"} for _ in polygon],
                "source_id": item.get("source_id"),
                "ifc_global_id": item.get("ifc_global_id"),
            }
            if isinstance(item.get("fill"), dict):
                item_copy["fill"] = copy.deepcopy(item["fill"])
            out.append(item_copy)
            continue
        try:
            pos=float(item.get("position", length*0.5)); width=float(item.get("width",1.0)); sill=float(item.get("sill",0.9)); oh=float(item.get("height",1.2))
        except (TypeError,ValueError) as exc:
            raise WallError("Abertura da parede contém medidas inválidas.") from exc
        if width < MIN_DIM or oh < MIN_DIM:
            raise WallError("Largura livre e altura da abertura devem ser positivas.")
        # Host edits may shorten a wall through an existing opening.
        # Preserve the opening's authored station/size and IFC identity even
        # when the host only partially intersects it (or not at all).
        # Placement tools enforce in-wall positions when creating NEW voids.
        if pos < 0.0:
            raise WallError("A posição da abertura não pode ser negativa.")
        # Doors may touch the wall base, and a nominal door taller than the
        # local wall must not delete the wall. The generator clips the head
        # at the available local top. Keep openings beginning above the
        # wall top invalid: they would not intersect this host at all.
        if not all(math.isfinite(v) for v in (pos, width, sill, oh)):
            raise WallError("Abertura da parede contém medidas não finitas.")
        if sill < 0 or sill >= height-MIN_DIM:
            raise WallError("O peitoril da abertura deve iniciar dentro da parede.")
        norm={"id":str(item.get("id") or f"wall-opening-{i+1}"),"kind":"rect","position":pos,"width":width,"sill":sill,"height":oh,"source_id":item.get("source_id"),"ifc_global_id":item.get("ifc_global_id")}
        if isinstance(item.get("fill"),dict): norm["fill"]=copy.deepcopy(item["fill"])
        elif item.get("fill_class") or item.get("ifc_fill_class"):
            norm["fill"]={"class":str(item.get("fill_class") or item.get("ifc_fill_class"))}
        out.append(norm)
    return out


def validate(values):
    out = dict(values)
    for key in ("length", "thickness", "height", "base"):
        try:
            out[key] = float(out[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise WallError("Preencha todas as medidas com números válidos.") from exc
        if not math.isfinite(out[key]):
            raise WallError("As medidas devem ser números finitos.")
    for key in ("length", "thickness", "height"):
        if not MIN_DIM <= out[key] <= MAX_DIM:
            raise WallError("Comprimento, espessura e altura: de 0,001 a 10.000 m.")
    if abs(out["base"]) > MAX_DIM:
        raise WallError("Cota de base fora do intervalo de ±10.000 m.")
    if out.get("alignment") not in ("left", "center", "right"):
        raise WallError("Escolha esquerda, centro ou direita.")

    # Top binding is optional and backwards-compatible.  Old walls simply
    # remain height-driven.  A level-bound top stores an intentional offset
    # from that level while ``height`` remains the current cached/effective
    # geometric height used to build the body.
    top_level = out.get("top_level")
    if top_level is not None:
        top_level = str(top_level).strip() or None
    top_mode = out.get("top_mode")
    if top_mode not in ("height", "level"):
        top_mode = "level" if top_level else "height"
    if top_mode == "level" and not top_level:
        top_mode = "height"
    try:
        top_offset = float(out.get("top_offset", 0.0))
    except (TypeError, ValueError) as exc:
        raise WallError("Offset do topo inválido.") from exc
    if not math.isfinite(top_offset) or abs(top_offset) > MAX_DIM:
        raise WallError("Offset do topo fora do intervalo de ±10.000 m.")
    out["top_mode"] = top_mode
    out["top_level"] = top_level
    out["top_offset"] = top_offset
    mat = out.get("material_name")
    out["material_name"] = str(mat).strip() if mat not in (None, "") else None
    structure = out.get("structure") if out.get("structure") in ("simple", "composite") else "simple"
    out["structure"] = structure
    if structure == "composite":
        layers = normalize_layers(out.get("layers"), out["thickness"], out["material_name"])
        out["layers"] = layers
        out["thickness"] = total_thickness(layers)
    else:
        out["layers"] = []
    # Endpoint height / lean profiles.  Old documents have no profile data and
    # therefore migrate to a vertical wall with a level base and top.
    def _pair_numbers(raw, fallback):
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raw = fallback
        try:
            vals = [float(raw[0]), float(raw[1])]
        except (TypeError, ValueError, IndexError) as exc:
            raise WallError("Perfil vertical da parede inválido.") from exc
        if not all(math.isfinite(v) and abs(v) <= MAX_DIM for v in vals):
            raise WallError("Perfil vertical da parede fora do intervalo permitido.")
        return vals

    base_profile = _pair_numbers(out.get("base_profile"), [0.0, 0.0])
    top_profile = _pair_numbers(out.get("top_profile"),
                                [base_profile[0] + out["height"],
                                 base_profile[1] + out["height"]])
    raw_top_xy = out.get("top_xy")
    if not isinstance(raw_top_xy, (list, tuple)) or len(raw_top_xy) != 2:
        raw_top_xy = [[0.0, 0.0], [0.0, 0.0]]
    top_xy = []
    for raw in raw_top_xy:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise WallError("Inclinação lateral da parede inválida.")
        try:
            x, y = float(raw[0]), float(raw[1])
        except (TypeError, ValueError) as exc:
            raise WallError("Inclinação lateral da parede inválida.") from exc
        if not math.isfinite(x) or not math.isfinite(y) or abs(x) > MAX_DIM or abs(y) > MAX_DIM:
            raise WallError("Inclinação lateral da parede fora do intervalo permitido.")
        top_xy.append([x, y])
    for b, t in zip(base_profile, top_profile):
        if t - b < MIN_DIM:
            raise WallError("O topo da parede precisa ficar acima da base em cada extremidade.")
    out["base_profile"] = base_profile
    out["top_profile"] = top_profile
    out["top_xy"] = top_xy
    # ``height`` remains the nominal side-panel height.  The effective envelope
    # is driven by the profiles; keep height large enough for hosted-opening
    # validation while preserving the familiar scalar field.
    effective_heights = [t - b for b, t in zip(base_profile, top_profile)]
    min_effective_height = min(effective_heights)
    out["openings"] = normalize_wall_openings(out.get("openings", []), out["length"], min_effective_height)
    return out


def wall_record(group):
    ext = getattr(group, "ext", None)
    rec = ext.get(KEY) if isinstance(ext, dict) else None
    return rec if isinstance(rec, dict) and rec.get("kind") == "wall" else None


def _xyz(raw):
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        raise WallError("Trajetória da parede inválida.")
    try:
        x, y, z = (float(v) for v in raw)
    except (TypeError, ValueError) as exc:
        raise WallError("Trajetória da parede inválida.") from exc
    if not all(math.isfinite(v) for v in (x, y, z)) or abs(z) > 1e-6:
        raise WallError("A trajetória da parede deve permanecer no plano horizontal.")
    return QVector3D(x, y, 0.0)


def path_kind_from_record(rec):
    path = rec.get("path", {}) if isinstance(rec, dict) else {}
    return path.get("type") if isinstance(path, dict) else None


def arc_sagitta_from_record(rec):
    path = rec.get("path", {}) if isinstance(rec, dict) else {}
    if path.get("type") != "arc":
        return None
    try:
        value = float(path.get("sagitta", 0.0))
    except (TypeError, ValueError):
        raise WallError("Curvatura da parede inválida.")
    if not math.isfinite(value):
        raise WallError("Curvatura da parede inválida.")
    return value


def _circumcenter2(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1.0e-12:
        return None
    aa = ax * ax + ay * ay
    bb = bx * bx + by * by
    cc = cx * cx + cy * cy
    ux = (aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / d
    uy = (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / d
    return ux, uy


def _wrap_angle(a):
    while a <= -math.pi:
        a += 2.0 * math.pi
    while a > math.pi:
        a -= 2.0 * math.pi
    return a




def arc_center_from_record(rec):
    """Return the local XY centre of a stored circular arc, or None for a line."""
    path = rec.get("path", {}) if isinstance(rec, dict) else {}
    if path.get("type") != "arc":
        return None
    a = _xyz(path.get("start"))
    b = _xyz(path.get("end"))
    h = arc_sagitta_from_record(rec)
    if h is None or abs(h) < ARC_EPS:
        return None
    chord = b - a
    length = math.hypot(chord.x(), chord.y())
    if length < MIN_DIM:
        return None
    u = QVector3D(chord.x() / length, chord.y() / length, 0.0)
    n = QVector3D(-u.y(), u.x(), 0.0)
    mid = (a + b) * 0.5
    apex = mid + n * h
    center = _circumcenter2((a.x(), a.y()), (apex.x(), apex.y()), (b.x(), b.y()))
    if center is None:
        return None
    return QVector3D(center[0], center[1], 0.0)


def arc_center_world(group):
    rec = wall_record(group)
    if rec is None:
        return None
    center = arc_center_from_record(rec)
    return None if center is None else group.xform.map(center)

def arc_points(start, end, sagitta):
    """Sample a circular arc in XY from endpoints and signed midpoint sagitta.

    Positive sagitta is to the left of start→end.  The endpoints remain exact;
    only the derived body is faceted.  Segment density is deliberately high
    enough that the reference overlay reads as a smooth architectural arc.
    """
    a = QVector3D(start.x(), start.y(), 0.0)
    b = QVector3D(end.x(), end.y(), 0.0)
    chord = b - a
    length = math.hypot(chord.x(), chord.y())
    if length < MIN_DIM:
        raise WallError("A parede precisa ter ao menos 1 mm de comprimento.")
    h = float(sagitta)
    if not math.isfinite(h):
        raise WallError("Curvatura da parede inválida.")
    if abs(h) < ARC_EPS:
        return [a, b]
    u = QVector3D(chord.x() / length, chord.y() / length, 0.0)
    n = QVector3D(-u.y(), u.x(), 0.0)
    mid = (a + b) * 0.5
    apex = mid + n * h
    center = _circumcenter2((a.x(), a.y()), (apex.x(), apex.y()), (b.x(), b.y()))
    if center is None:
        return [a, b]
    cx, cy = center
    radius = math.hypot(a.x() - cx, a.y() - cy)
    a0 = math.atan2(a.y() - cy, a.x() - cx)
    a1 = math.atan2(b.y() - cy, b.x() - cx)
    am = math.atan2(apex.y() - cy, apex.x() - cx)
    sweep = _wrap_angle(a1 - a0)
    through = _wrap_angle(am - a0)
    if sweep >= 0.0 and not (0.0 <= through <= sweep):
        sweep -= 2.0 * math.pi
    elif sweep < 0.0 and not (sweep <= through <= 0.0):
        sweep += 2.0 * math.pi
    arc_len = abs(sweep) * radius
    spans = max(4,
                int(math.ceil(abs(math.degrees(sweep)) / ARC_MAX_STEP_DEG)),
                int(math.ceil(arc_len / ARC_MAX_SEGMENT)))
    spans = min(ARC_MAX_SAMPLES, spans)
    return [QVector3D(cx + radius * math.cos(a0 + sweep * (i / spans)),
                      cy + radius * math.sin(a0 + sweep * (i / spans)), 0.0)
            for i in range(spans + 1)]


def arc_record(start, end, sagitta):
    a, b = QVector3D(start), QVector3D(end)
    if abs(float(sagitta)) < ARC_EPS:
        return {"type": "line",
                "start": [a.x(), a.y(), 0.0],
                "end": [b.x(), b.y(), 0.0]}
    return {"type": "arc",
            "start": [a.x(), a.y(), 0.0],
            "end": [b.x(), b.y(), 0.0],
            "sagitta": float(sagitta)}


def path_points_from_record(rec):
    """Derived reference samples in wall-local coordinates."""
    path = rec.get("path", {}) if isinstance(rec, dict) else {}
    kind = path.get("type")
    if kind == "line":
        pts = [_xyz(path.get("start")), _xyz(path.get("end"))]
    elif kind == "arc":
        start = _xyz(path.get("start"))
        end = _xyz(path.get("end"))
        try:
            sagitta = float(path.get("sagitta", 0.0))
        except (TypeError, ValueError) as exc:
            raise WallError("Curvatura da parede inválida.") from exc
        pts = arc_points(start, end, sagitta)
    elif kind == "polyline":
        raw = path.get("points")
        if not isinstance(raw, list) or len(raw) < 2:
            raise WallError("Trajetória da parede inválida.")
        pts = [_xyz(p) for p in raw]
    else:
        raise WallError("Esta trajetória ainda não é suportada.")
    for a, b in zip(pts, pts[1:]):
        if (b - a).length() < MIN_DIM:
            raise WallError("A trajetória contém um trecho menor que 1 mm.")
    return pts


def reference_vertices_from_record(rec):
    """User-editable reference vertices, excluding derived arc samples."""
    path = rec.get("path", {}) if isinstance(rec, dict) else {}
    kind = path.get("type")
    if kind in ("line", "arc"):
        return [_xyz(path.get("start")), _xyz(path.get("end"))]
    if kind == "polyline":
        raw = path.get("points")
        if not isinstance(raw, list) or len(raw) < 2:
            raise WallError("Trajetória da parede inválida.")
        return [_xyz(p) for p in raw]
    raise WallError("Esta trajetória ainda não é suportada.")


def wall_path(group):
    rec = wall_record(group)
    if rec is None or rec.get("schema") != SCHEMA:
        raise WallError("Versão dos parâmetros da parede não reconhecida.")
    return path_points_from_record(rec)


def wall_path_kind(group):
    rec = wall_record(group)
    if rec is None or rec.get("schema") != SCHEMA:
        raise WallError("Versão dos parâmetros da parede não reconhecida.")
    return path_kind_from_record(rec)


def wall_reference_vertices(group):
    rec = wall_record(group)
    if rec is None or rec.get("schema") != SCHEMA:
        raise WallError("Versão dos parâmetros da parede não reconhecida.")
    return reference_vertices_from_record(rec)


def path_length(points):
    return sum((b - a).length() for a, b in zip(points, points[1:]))


def path_length_from_record(rec):
    path = rec.get("path", {}) if isinstance(rec, dict) else {}
    if path.get("type") == "arc":
        a = _xyz(path.get("start"))
        b = _xyz(path.get("end"))
        h = arc_sagitta_from_record(rec) or 0.0
        c = (b - a).length()
        if abs(h) < ARC_EPS:
            return c
        radius = c * c / (8.0 * abs(h)) + abs(h) / 2.0
        theta = 4.0 * math.atan2(2.0 * abs(h), c)
        return radius * theta
    return path_length(path_points_from_record(rec))

def serialize_path(points):
    pts = [QVector3D(p) for p in points]
    if len(pts) < 2:
        raise WallError("A parede precisa ter ao menos dois pontos.")
    # Preserve the compact legacy form for a simple straight path.
    if len(pts) == 2 and abs(pts[0].x()) < 1e-9 and abs(pts[0].y()) < 1e-9:
        return {"type": "line", "start": [0.0, 0.0, 0.0],
                "end": [pts[1].x(), pts[1].y(), 0.0]}
    return {"type": "polyline",
            "points": [[p.x(), p.y(), 0.0] for p in pts]}


def caps_from_record(rec):
    """Optional local low/high corner overrides for straight-wall endpoints.

    ``caps["start"]`` and ``caps["end"]`` are pairs ``(low, high)``.  They
    are derived from neighbouring reference lines by the junction resolver;
    the reference path itself never moves.
    """
    raw = rec.get("caps") if isinstance(rec, dict) else None
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in ("start", "end"):
        pair = raw.get(key)
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        try:
            out[key] = (_xyz(pair[0]), _xyz(pair[1]))
        except WallError:
            continue
    return out


def serialize_caps(caps):
    out = {}
    for key in ("start", "end"):
        pair = (caps or {}).get(key)
        if pair is None or len(pair) != 2:
            continue
        low, high = (QVector3D(pair[0]), QVector3D(pair[1]))
        out[key] = ([low.x(), low.y(), 0.0], [high.x(), high.y(), 0.0])
    return out


def wall_caps(group):
    rec = wall_record(group)
    return caps_from_record(rec or {})


def record(values, path=None, caps=None, path_record=None):
    p = validate(values)
    if path is None:
        path = [QVector3D(0, 0, 0), QVector3D(p["length"], 0, 0)]
    out = {
        "schema": SCHEMA, "kind": "wall",
        "path": copy.deepcopy(path_record) if path_record is not None else serialize_path(path),
        "thickness": p["thickness"], "height": p["height"],
        "alignment": p["alignment"],
        "base_mode": "absolute", "base_level": p.get("base_level"),
        "top_mode": p.get("top_mode", "height"),
        "top_level": p.get("top_level"),
        "top_offset": p.get("top_offset", 0.0),
        "material_name": p.get("material_name"),
        "structure": p.get("structure", "simple"),
        "layers": clone_layers(p.get("layers", [])),
        "openings": copy.deepcopy(p.get("openings", [])),
        "base_profile": list(p.get("base_profile", [0.0, 0.0])),
        "top_profile": list(p.get("top_profile", [p["height"], p["height"]])),
        "top_xy": copy.deepcopy(p.get("top_xy", [[0.0, 0.0], [0.0, 0.0]])),
    }
    encoded = serialize_caps(caps)
    if encoded:
        out["caps"] = encoded
    return out


def local_corners(values):
    """Eight corners for the straight creation preview only."""
    p = validate(values)
    length, height = p["length"], p["height"]
    low, high = wall_offsets(p)
    return [QVector3D(x, y, z) for x, y, z in (
        (0, low, 0), (length, low, 0), (length, high, 0), (0, high, 0),
        (0, low, height), (length, low, height),
        (length, high, height), (0, high, height),
    )]


def _line_intersection(p, r, q, s):
    cross = r.x() * s.y() - r.y() * s.x()
    if abs(cross) < 1e-10:
        return None
    qp = q - p
    t = (qp.x() * s.y() - qp.y() * s.x()) / cross
    return p + r * t


def _offset_path(points, distance):
    """Mitered open-polyline offset in XY; endpoints stay square."""
    pts = [QVector3D(p.x(), p.y(), 0.0) for p in points]
    segs, normals = [], []
    for a, b in zip(pts, pts[1:]):
        d = b - a
        length = math.hypot(d.x(), d.y())
        if length < MIN_DIM:
            raise WallError("A trajetória contém um trecho menor que 1 mm.")
        u = QVector3D(d.x() / length, d.y() / length, 0)
        segs.append(u)
        normals.append(QVector3D(-u.y(), u.x(), 0))
    out = [pts[0] + normals[0] * distance]
    for i in range(1, len(pts) - 1):
        a = pts[i] + normals[i - 1] * distance
        b = pts[i] + normals[i] * distance
        hit = _line_intersection(a, segs[i - 1], b, segs[i])
        if hit is None:
            n = normals[i - 1] + normals[i]
            hit = pts[i] + (n.normalized() if n.length() > 1e-9 else normals[i]) * distance
        # Avoid pathological spikes at very acute reversals.
        max_miter = max(abs(distance) * 20.0, 0.25)
        delta = hit - pts[i]
        if delta.length() > max_miter:
            delta.normalize()
            hit = pts[i] + delta * max_miter
        out.append(hit)
    out.append(pts[-1] + normals[-1] * distance)
    return out


def wall_offsets(values):
    p = validate(values)
    if p.get("structure") == "composite":
        return wall_overall_offsets(p.get("layers", []), p["alignment"])
    t = p["thickness"]
    low = {"left": 0.0, "center": -t / 2.0, "right": -t}[p["alignment"]]
    return low, low + t


def wall_layer_bands(values):
    p = validate(values)
    if p.get("structure") != "composite":
        low, high = wall_offsets(p)
        return [({"id": "simple", "name": "Parede", "role": "core",
                  "thickness": p["thickness"], "material_name": p.get("material_name")},
                 low, high)]
    return bands_about_core(p.get("layers", []), p["alignment"])


def footprint(points, thickness, alignment, caps=None, offsets=None):
    if offsets is None:
        low = {"left": 0.0, "center": -thickness / 2.0, "right": -thickness}[alignment]
        high = low + thickness
    else:
        low, high = offsets
    side_low = _offset_path(points, low)
    side_high = _offset_path(points, high)

    # Endpoint caps are derived junction geometry.  They used to be applied only
    # to a two-point straight path; curved walls are sampled polylines, so the
    # same endpoint override must work independently of how many intermediate
    # samples the reference curve uses.
    if caps:
        start = caps.get("start")
        end = caps.get("end")
        if start is not None:
            side_low[0], side_high[0] = QVector3D(start[0]), QVector3D(start[1])
        if end is not None:
            side_low[-1], side_high[-1] = QVector3D(end[0]), QVector3D(end[1])

    return side_low + list(reversed(side_high))


def _hide_joint_seam_edges(mesh, pair, height):
    """Hide only the horizontal seam of an internal miter cap.

    The two vertical edges are real architectural corners and remain visible.
    The top/bottom diagonals are merely the boundary between two logical wall
    elements and should not draw as a crack across the joined surface.
    """
    if pair is None or len(pair) != 2:
        return
    low, high = QVector3D(pair[0]), QVector3D(pair[1])
    targets = (
        (QVector3D(low.x(), low.y(), 0.0), QVector3D(high.x(), high.y(), 0.0)),
        (QVector3D(low.x(), low.y(), height), QVector3D(high.x(), high.y(), height)),
    )

    def close(a, b):
        return (a - b).length() <= 1e-8

    for edge in mesh.edges:
        a, b = edge.v0.position, edge.v1.position
        for p0, p1 in targets:
            if ((close(a, p0) and close(b, p1))
                    or (close(a, p1) and close(b, p0))):
                edge.hidden = True
                break


def _soften_sampled_curve_verticals(mesh, poly, height, path_count):
    """Use IngeTrazo soft-edge semantics on sampled curved wall facets.

    The mesh remains faceted for topology, but shallow seams render as one
    smooth curved surface and still participate in silhouette/profile drawing.
    """
    if path_count <= 2:
        return
    soften_curve_facets(mesh)


def _path_cumulative(points):
    pts=[QVector3D(p) for p in points]
    cum=[0.0]
    for a,b in zip(pts,pts[1:]):
        cum.append(cum[-1]+(b-a).length())
    return pts,cum

def _point_on_path_distance(points, cumulative, distance):
    if not points:
        return QVector3D()
    if len(points)==1 or cumulative[-1] <= 1.0e-12:
        return QVector3D(points[0])
    d=max(0.0,min(cumulative[-1],float(distance)))
    i=max(0,min(len(points)-2,bisect.bisect_left(cumulative,d+1.0e-12)-1))
    a,b=cumulative[i],cumulative[i+1]
    u=0.0 if b<=a else max(0.0,min(1.0,(d-a)/(b-a)))
    return points[i]+(points[i+1]-points[i])*u

def _side_point_at_reference_distance(side, ref_cum, distance):
    """Interpolate an offset side using the reference-path parameterization."""
    d=max(0.0,min(ref_cum[-1],float(distance)))
    i=max(0,min(len(side)-2,bisect.bisect_left(ref_cum,d+1.0e-12)-1))
    a,b=ref_cum[i],ref_cum[i+1]
    u=0.0 if b<=a else max(0.0,min(1.0,(d-a)/(b-a)))
    return side[i]+(side[i+1]-side[i])*u

def wall_opening_intervals(values, path):
    """Return hosted opening spans along the reference path.

    The stored ``width`` is *Largura Livre no menor Vão*.  We solve a symmetric
    host span around ``position`` until the smaller straight chord between the
    two wall faces equals that width.  This makes 0.90 m mean at least 0.90 m
    of real free passage even on a curved wall; the opposite face may be wider.
    """
    p=validate(values);ops=p.get("openings",[])
    if not ops:return []
    pts,ref_cum=_path_cumulative(path);L=ref_cum[-1]
    if L < MIN_DIM:raise WallError("Parede curta demais para receber abertura.")
    low_off,high_off=wall_offsets(p)
    side_low=_offset_path(pts,low_off);side_high=_offset_path(pts,high_off)
    margin=max(0.02,MIN_DIM*5)
    result=[]
    for o in ops:
        if o.get("kind") == "polygon":
            from .wall_polygon import clip_polygon_stations, clip_to_wall
            polygon=clip_polygon_stations(o["polygon"],L)
            if not polygon:
                continue
            # A head-above-wall cutter is still a valid logical opening but
            # creates no physical mesh when it cannot intersect wall material.
            stations=[float(x) for x,_ in polygon]
            s0,s1=min(stations),max(stations)
            if s1-s0 <= 1.e-9:
                continue
            # Keep IFC/source identity and ORIGINAL polygon untouched.
            result.append(dict(o,s0=s0,s1=s1,reference_span=s1-s0,
                               cut_polygon=polygon,
                               cut_clipped=len(polygon)!=len(o["polygon"]) or
                               any(abs(float(a[0])-float(b[0]))>1e-7 or
                                   abs(float(a[1])-float(b[1]))>1e-7
                                   for a,b in zip(polygon,o["polygon"]))))
            continue
        pos=float(o["position"]);width=float(o["width"])
        # The logical cutter exists independently of the wall ends.
        # The *effective* cut is just the intersection with [0, L].
        # Never shrink/translate the stored cutter as a side effect of
        # changing the wall length; growing the wall restores the full void.
        lo=pos-width*0.5
        hi=pos+width*0.5
        if hi <= 1.0e-9 or lo >= L-1.0e-9:
            continue  # no physical cut; the opening remains in wall data
        if len(pts)==2:
            cut_a=max(0.0,lo)
            cut_b=min(L,hi)
            if cut_b-cut_a > 1.0e-9:
                result.append(dict(o,s0=cut_a,s1=cut_b,
                                   reference_span=width,
                                   cut_clipped=(cut_a>lo+1e-9 or cut_b<hi-1e-9)))
            continue
        # Curved openings retain free-width semantics whenever their entire
        # nominal span fits. At a boundary, use the remaining *visible*
        # reference arc; the authored width does not mutate.
        margin=max(0.02,MIN_DIM*5)
        if (pos-margin<=0 or L-pos-margin<=0 or
                width*0.5 > min(pos-margin,L-pos-margin)):
            cut_a=max(0.0,lo)
            cut_b=min(L,hi)
            if cut_b-cut_a > 1.0e-9:
                result.append(dict(o,s0=cut_a,s1=cut_b,
                                   reference_span=width,cut_clipped=True))
            continue
        max_half=min(pos-margin,L-pos-margin)
        def free_chord(half):
            a=pos-half;b=pos+half
            la=_side_point_at_reference_distance(side_low,ref_cum,a);lb=_side_point_at_reference_distance(side_low,ref_cum,b)
            ha=_side_point_at_reference_distance(side_high,ref_cum,a);hb=_side_point_at_reference_distance(side_high,ref_cum,b)
            return min((lb-la).length(),(hb-ha).length())
        lo_half=0.0
        hi_half=None
        prev=0.0
        for step in range(1,129):
            h=max_half*(step/128.0)
            if free_chord(h)>=width-1.0e-9:
                lo_half=prev
                hi_half=h
                break
            prev=h
        if hi_half is None:
            # The desired opening is wider than the remaining wall: clip
            # rather than blocking the host edit.
            cut_a=max(0.0,lo)
            cut_b=min(L,hi)
            if cut_b-cut_a > 1.0e-9:
                result.append(dict(o,s0=cut_a,s1=cut_b,
                                   reference_span=width,cut_clipped=True))
            continue
        for _ in range(36):
            if hi_half-lo_half<1e-9:
                break
            mid=(lo_half+hi_half)*0.5
            if free_chord(mid)<width:
                lo_half=mid
            else:
                hi_half=mid
        half=(lo_half+hi_half)*0.5
        result.append(dict(o,s0=pos-half,s1=pos+half,
                           reference_span=2.0*half,cut_clipped=False))
    result.sort(key=lambda x:x["s0"])
    for a,b in zip(result,result[1:]):
        if b["s0"] < a["s1"]-1.0e-8:
            raise WallError("As aberturas da parede não podem se sobrepor.")
    return result

def nearest_path_distance_world(group, world):
    """Distance along the wall reference path nearest to a world-space point."""
    pts=path_world(group)
    if len(pts)<2:return 0.0
    q=QVector3D(world);cum=[0.0];best=None
    for a,b in zip(pts,pts[1:]):cum.append(cum[-1]+(b-a).length())
    for i,(a,b) in enumerate(zip(pts,pts[1:])):
        d=b-a;den=QVector3D.dotProduct(d,d);u=0.0 if den<=1.0e-12 else QVector3D.dotProduct(q-a,d)/den;u=max(0.0,min(1.0,u))
        hit=a+d*u;dist=(q-hit).lengthSquared();s=cum[i]+(cum[i+1]-cum[i])*u
        if best is None or dist<best[0]:best=(dist,s)
    return float(best[1] if best is not None else 0.0)



def _profiled_sides(values, path, offsets=None, caps=None):
    """Create bottom/top low/high side samples for a possibly sloped/leaning wall."""
    p = validate(values)
    ref = [QVector3D(v.x(), v.y(), 0.0) for v in path]
    ref_pts, ref_cum = _path_cumulative(ref)
    total = ref_cum[-1] if ref_cum else 0.0
    if offsets is None:
        low_off, high_off = wall_offsets(p)
    else:
        low_off, high_off = offsets

    top_ref = []
    base_z = []
    top_z = []
    for i, q in enumerate(ref_pts):
        t = 0.0 if total <= 1.0e-12 else ref_cum[i] / total
        bz, tz, off = _profile_interp(p, t)
        base_z.append(bz); top_z.append(tz)
        top_ref.append(QVector3D(q.x() + off.x(), q.y() + off.y(), 0.0))

    low_bottom = _offset_path(ref_pts, low_off)
    high_bottom = _offset_path(ref_pts, high_off)
    low_top = _offset_path(top_ref, low_off)
    high_top = _offset_path(top_ref, high_off)

    if caps:
        start = caps.get("start")
        end = caps.get("end")
        if start is not None:
            low_bottom[0], high_bottom[0] = QVector3D(start[0]), QVector3D(start[1])
            ox, oy = p["top_xy"][0]
            low_top[0] = QVector3D(start[0].x()+ox, start[0].y()+oy, 0.0)
            high_top[0] = QVector3D(start[1].x()+ox, start[1].y()+oy, 0.0)
        if end is not None:
            low_bottom[-1], high_bottom[-1] = QVector3D(end[0]), QVector3D(end[1])
            ox, oy = p["top_xy"][1]
            low_top[-1] = QVector3D(end[0].x()+ox, end[0].y()+oy, 0.0)
            high_top[-1] = QVector3D(end[1].x()+ox, end[1].y()+oy, 0.0)
    return low_bottom, high_bottom, low_top, high_top, base_z, top_z, ref_cum


def _profile_z_at(values, distance, total):
    t = 0.0 if total <= 1.0e-12 else max(0.0, min(1.0, float(distance)/total))
    bz, tz, off = _profile_interp(values, t)
    return bz, tz, off


def _lerp_side_point(bottom_xy, top_xy, base_z, top_z, z):
    den = float(top_z) - float(base_z)
    f = 0.0 if abs(den) <= 1.0e-12 else (float(z) - float(base_z)) / den
    f = max(0.0, min(1.0, f))
    return QVector3D(bottom_xy.x() + (top_xy.x()-bottom_xy.x())*f,
                     bottom_xy.y() + (top_xy.y()-bottom_xy.y())*f,
                     float(z))


def _stitch_opening_mesh(mesh):
    """Resolve T-junctions at wall voids using the real IngeTrazo mesh API.

    Shared vertices at the middle of another face's long edge must split
    that edge, otherwise neighbouring faces are not topologically connected.
    """
    # IngeTrazo's interior_vertex_on linearly scans EVERY vertex per edge.
    # Curved multi-layer cuts contain thousands of edges, producing O(E*V)
    # rebuilds. Index once by x; a split only reuses existing vertices, so
    # the index stays valid. Keep the host's exact 0.0001 m tolerance/criterion.
    vertices = sorted(mesh.vertices, key=lambda v: v.position.x())
    xs = [v.position.x() for v in vertices]
    tol = 1.0e-4
    pending = list(mesh.edges)
    limit = max(256, 8 * len(pending))
    splits = 0
    while pending:
        edge = pending.pop()
        if edge not in mesh.edges:
            continue
        a, b = edge.v0.position, edge.v1.position
        ab = b-a
        length = ab.length()
        if length < tol:
            continue
        low = bisect.bisect_left(xs, min(a.x(), b.x())-tol)
        high = bisect.bisect_right(xs, max(a.x(), b.x())+tol)
        middle = None
        for vertex in vertices[low:high]:
            if vertex is edge.v0 or vertex is edge.v1:
                continue
            t = QVector3D.dotProduct(vertex.position-a, ab)/(length*length)
            if t <= tol/length or t >= 1.0-tol/length:
                continue
            if (vertex.position-(a+ab*t)).length() < tol:
                middle = vertex
                break
        if middle is None:
            continue
        if splits >= limit:
            raise WallError("Não foi possível conectar o contorno da abertura.")
        result = mesh.split_edge_at(edge, middle)
        pending.extend((result["e0"], result["e1"]))
        splits += 1


def _build_body_with_openings(values, previous, path, caps, offsets, body_name):
    """Build a profiled straight/curved wall with hosted openings.

    The lower and upper edges are independent linear profiles between the two
    true endpoints.  A top XY offset can also vary between endpoints, which
    makes the wall lean/twist.  Openings remain hosted by path station and are
    cut through the resulting sloped faces rather than through a vertical
    surrogate prism.
    """
    p = validate(values)
    ops = wall_opening_intervals(p, path)
    ref_pts, ref_cum = _path_cumulative(path)
    L = ref_cum[-1]
    cuts = {0.0, L}; cuts.update(ref_cum)
    for o in ops: cuts.update((o["s0"], o["s1"]))
    # Split additional stations where a sloped wall crosses an opening's
    # head or sill. Without them, a strip could be cut only on one side,
    # leaving dangling top/bottom polygons in the visible opening.
    from .opening_profile import opening_slice, profile_crossings
    cuts.update(profile_crossings(
        L, p["base_profile"], p["top_profile"], ops))
    ss = sorted(max(0.0, min(L, float(v))) for v in cuts)
    clean = []
    for v in ss:
        if not clean or abs(v-clean[-1]) > 1.0e-9: clean.append(v)
    ss = clean
    aug = [_point_on_path_distance(ref_pts, ref_cum, v) for v in ss]
    low_b, high_b, low_t, high_t, base_z, top_z, _ = _profiled_sides(
        p, aug, offsets=offsets, caps=caps)

    mesh = Mesh()

    def face(points, key):
        # At the exact meeting station of a sloped head/top profile,
        # an otherwise quadrilateral wall band degenerates to a triangle.
        # Remove coincident adjacent corners before handing it to the mesh.
        clean = []
        for pt in points:
            if not clean or (pt-clean[-1]).length() > 1.0e-8:
                clean.append(pt)
        if len(clean) > 1 and (clean[0]-clean[-1]).length() <= 1.0e-8:
            clean.pop()
        if len(clean) < 3:
            return None
        f = mesh.add_face(clean)
        f.attrs[FACE_KEY] = key
        return f

    def side_at(idx, which, z):
        if which == "low":
            return _lerp_side_point(low_b[idx], low_t[idx], base_z[idx], top_z[idx], z)
        return _lerp_side_point(high_b[idx], high_t[idx], base_z[idx], top_z[idx], z)

    # End caps must also be cut where a void crosses an endpoint. Keeping
    # the old FULL end face made receded walls falsely cover part of a doorway
    # and created a nonmanifold seam at the clipped opening boundary.
    def end_cap(idx, side):
        at=0.0 if idx==0 else L
        boundary=next((o for o in ops
                       if o["s0"]-1e-8<=at<=o["s1"]+1e-8),None)
        height=top_z[idx]-base_z[idx]
        if boundary is None:
            bands=[(base_z[idx],top_z[idx])]
        else:
            from .opening_profile import opening_slice
            aperture=opening_slice(height,boundary["sill"],boundary["height"])
            zlow=base_z[idx]+boundary["sill"]
            zhigh=min(top_z[idx],zlow+boundary["height"])
            bands=[]
            if not aperture["cut"]:
                bands=[(base_z[idx],top_z[idx])]
            else:
                if zlow-base_z[idx] > 1.e-9:
                    bands.append((base_z[idx],zlow))
                if top_z[idx]-zhigh > 1.e-9:
                    bands.append((zhigh,top_z[idx]))
        for bottom,top in bands:
            low0=side_at(idx,"low",bottom)
            high0=side_at(idx,"high",bottom)
            low1=side_at(idx,"low",top)
            high1=side_at(idx,"high",top)
            if side=="start":
                face([high0,low0,low1,high1],"start")
            else:
                face([low0,high0,high1,low1],"end")

    end_cap(0,"start")
    end_cap(-1,"end")

    for i, (sa, sb) in enumerate(zip(ss, ss[1:])):
        if sb-sa <= 1.0e-10:
            continue
        sm = (sa+sb)*0.5
        mb, mt, _ = _profile_z_at(p, sm, L)
        active = [
            o for o in ops
            if o["s0"] < sm < o["s1"]
            and opening_slice(mt-mb, o["sill"], o["height"])["cut"]
        ]
        # Opening spans do not overlap, so there is at most one active cut.
        opening = active[0] if active else None
        layout = opening_slice(mt-mb, opening["sill"], opening["height"]) if opening else None
        # A floor-to-ceiling cut must NOT retain a full-width bottom/top
        # skin crossing the opening: those created visible stray edges.
        if layout is None or layout["below"]:
            face([QVector3D(high_b[i].x(), high_b[i].y(), base_z[i]),
                  QVector3D(high_b[i+1].x(), high_b[i+1].y(), base_z[i+1]),
                  QVector3D(low_b[i+1].x(), low_b[i+1].y(), base_z[i+1]),
                  QVector3D(low_b[i].x(), low_b[i].y(), base_z[i])], "bottom")
        if layout is None or layout["above"]:
            face([QVector3D(low_t[i].x(), low_t[i].y(), top_z[i]),
                  QVector3D(low_t[i+1].x(), low_t[i+1].y(), top_z[i+1]),
                  QVector3D(high_t[i+1].x(), high_t[i+1].y(), top_z[i+1]),
                  QVector3D(high_t[i].x(), high_t[i].y(), top_z[i])], "top")

        if opening is None:
            face([QVector3D(low_b[i].x(), low_b[i].y(), base_z[i]),
                  QVector3D(low_b[i+1].x(), low_b[i+1].y(), base_z[i+1]),
                  QVector3D(low_t[i+1].x(), low_t[i+1].y(), top_z[i+1]),
                  QVector3D(low_t[i].x(), low_t[i].y(), top_z[i])], "side")
            face([QVector3D(high_b[i+1].x(), high_b[i+1].y(), base_z[i+1]),
                  QVector3D(high_b[i].x(), high_b[i].y(), base_z[i]),
                  QVector3D(high_t[i].x(), high_t[i].y(), top_z[i]),
                  QVector3D(high_t[i+1].x(), high_t[i+1].y(), top_z[i+1])], "side")
            continue

        z0a = base_z[i] + opening["sill"]
        z0b = base_z[i+1] + opening["sill"]
        z1a = min(top_z[i], z0a + opening["height"])
        z1b = min(top_z[i+1], z0b + opening["height"])
        if layout["below"]:
            face([QVector3D(low_b[i].x(), low_b[i].y(), base_z[i]),
                  QVector3D(low_b[i+1].x(), low_b[i+1].y(), base_z[i+1]),
                  side_at(i+1, "low", z0b), side_at(i, "low", z0a)], "side")
            face([QVector3D(high_b[i+1].x(), high_b[i+1].y(), base_z[i+1]),
                  QVector3D(high_b[i].x(), high_b[i].y(), base_z[i]),
                  side_at(i, "high", z0a), side_at(i+1, "high", z0b)], "side")
        if layout["above"]:
            face([side_at(i, "low", z1a), side_at(i+1, "low", z1b),
                  QVector3D(low_t[i+1].x(), low_t[i+1].y(), top_z[i+1]),
                  QVector3D(low_t[i].x(), low_t[i].y(), top_z[i])], "side")
            face([side_at(i+1, "high", z1b), side_at(i, "high", z1a),
                  QVector3D(high_t[i].x(), high_t[i].y(), top_z[i]),
                  QVector3D(high_t[i+1].x(), high_t[i+1].y(), top_z[i+1])], "side")

    # Jambs and horizontal reveals exist only on portions of the cut that
    # still intersect the host wall. A bottom-attached door has no sill
    # cover; an opening above the host has no head cover.
    index = {round(v, 10): i for i, v in enumerate(ss)}
    for o in ops:
        i0 = index.get(round(o["s0"], 10))
        i1 = index.get(round(o["s1"], 10))
        if i0 is None or i1 is None:
            continue
        for idx, rev in ((i0, False), (i1, True)):
            # At the wall boundary this edge is OPEN to the exterior,
            # not a jamb. Drawing a reveal here seals the cut on the
            # end and leaves nonmanifold edges after splitting its cap.
            if (idx == 0 and o["s0"] <= 1.e-8 or
                    idx == len(ss)-1 and o["s1"] >= L-1.e-8):
                continue
            span = opening_slice(top_z[idx]-base_z[idx], o["sill"], o["height"])
            if not span["cut"]:
                continue
            z0 = base_z[idx] + o["sill"]
            z1 = min(top_z[idx], z0 + o["height"])
            if z1-z0 <= 1.0e-8:
                continue
            pts = [side_at(idx, "low", z0), side_at(idx, "high", z0),
                   side_at(idx, "high", z1), side_at(idx, "low", z1)]
            face(list(reversed(pts)) if rev else pts, "opening")
        for i in range(i0, i1):
            sm = (ss[i]+ss[i+1])*0.5
            mb, mt, _ = _profile_z_at(p, sm, L)
            span = opening_slice(mt-mb, o["sill"], o["height"])
            if not span["cut"]:
                continue
            z0a = base_z[i] + o["sill"]
            z0b = base_z[i+1] + o["sill"]
            z1a = min(top_z[i], z0a + o["height"])
            z1b = min(top_z[i+1], z0b + o["height"])
            if span["below"]:
                face([side_at(i, "low", z0a), side_at(i+1, "low", z0b),
                      side_at(i+1, "high", z0b), side_at(i, "high", z0a)], "opening")
            if span["above"]:
                face([side_at(i, "high", z1a), side_at(i+1, "high", z1b),
                      side_at(i+1, "low", z1b), side_at(i, "low", z1a)], "opening")

    _stitch_opening_mesh(mesh)
    if previous is not None:
        transfer_semantic_face_appearance(previous.mesh, mesh, FACE_KEY,
                                          fallback_key="side",
                                          drop_keys=(JOINT_FACE_KEY,))
    if caps and not wall_has_custom_profile(p):
        _hide_joint_seam_edges(mesh,caps.get("start"),p["height"]);_hide_joint_seam_edges(mesh,caps.get("end"),p["height"])
    # Curved sampling and twisted profile strips are display seams, not user
    # edges.  IngeTrazo's soft-edge semantics keep silhouette/profile edges.
    soften_curve_facets(mesh)
    # Continuous UV transport is needed only when the wall path is genuinely
    # faceted/curved.  On a straight wall with a sloped/twisted top the host's
    # ordinary planar mapping is more stable and preserves the expected brick
    # orientation on the large side faces.
    if len(path) > 2:
        wrap_soft_surface_textures(mesh)
    body=Group(mesh,name=body_name);body.component=False
    if previous is not None:
        body.material=copy.deepcopy(previous.material);body.layer=previous.layer
    return body


def _build_body_with_polygon_openings(values, previous, path, caps, offsets, body_name):
    """Non-destructive elevation polygon cuts, including rectangular siblings.

    The reference path is sampled at every polygon corner, path facet and
    height-profile crossing. Each wall-side strip contains only the material
    bands outside the polygon(s). Reveals are separate perimeter faces, never
    a face across the void. Supports curved plan walls and composite layers.
    """
    from .wall_polygon import (clip_to_wall, contains, cut_stations,
                               edge_height, scan_edges)
    p = validate(values)
    ops = wall_opening_intervals(p, path)
    polygons = []
    for o in ops:
        if o.get("kind") == "polygon":
            polygons.append(o.get("cut_polygon",o["polygon"]))
        else:
            s0, s1 = o["s0"], o["s1"]
            z0, z1 = o["sill"], o["sill"] + o["height"]
            polygons.append([[s0, z0], [s1, z0], [s1, z1], [s0, z1]])
    original, cumul = _path_cumulative(path)
    L = cumul[-1]
    cuts = {0.0, L, *cumul}
    for poly in polygons:
        cuts.update(cut_stations(poly, L, p["base_profile"], p["top_profile"]))
    ss = []
    for s in sorted(max(0.0, min(L, float(x))) for x in cuts):
        if not ss or s-ss[-1] > 1.0e-9:
            ss.append(s)
    points = [_point_on_path_distance(original, cumul, s) for s in ss]
    low_b, high_b, low_t, high_t, base_z, top_z, _ = _profiled_sides(
        p, points, offsets=offsets, caps=caps)
    mesh = Mesh()
    def add(points, key):
        compact = []
        for v in points:
            if not compact or (v-compact[-1]).length() > 1.0e-8:
                compact.append(v)
        if len(compact) > 1 and (compact[0]-compact[-1]).length() <= 1.0e-8:
            compact.pop()
        if len(compact) < 3:
            return
        f = mesh.add_face(compact)
        f.attrs[FACE_KEY] = key

    def wall_height(s):
        bz, tz, _ = _profile_z_at(p, s, L)
        return tz-bz

    def side(index, which, local_z):
        z = base_z[index] + max(0.0, min(top_z[index]-base_z[index], local_z))
        if which == "low":
            return _lerp_side_point(low_b[index], low_t[index], base_z[index], top_z[index], z)
        return _lerp_side_point(high_b[index], high_t[index], base_z[index], top_z[index], z)

    def is_void(s, z):
        return any(contains(poly, s, z) for poly in polygons)

    def index_at(s):
        for i, x in enumerate(ss):
            if abs(x-s) <= 1.0e-7:
                return i
        raise WallError("Não foi possível associar o contorno à trajetória da parede.")

    # When a polygon reaches a trimmed wall endpoint its cut must OPEN to
    # the outside. A solid full-height cap would cover the doorway and leave
    # nonmanifold faces along the apparent cut at the wall boundary.
    def endpoint_cap(index, label):
        station=0.0 if index==0 else L
        near=max(1e-8,min(L/1e6,1e-6))
        scan=near if index==0 else L-near
        height=wall_height(station)
        elevations=[0.0,height]
        for poly in polygons:
            for z,_edge in scan_edges(poly,scan):
                if 1e-8<z<height-1e-8:
                    elevations.append(z)
        zlevels=[]
        for z in sorted(elevations):
            if not zlevels or z-zlevels[-1]>1.e-8:
                zlevels.append(z)
        for z0,z1 in zip(zlevels,zlevels[1:]):
            if z1-z0<=1e-8 or any(contains(poly,scan,(z0+z1)*.5)
                                   for poly in polygons):
                continue
            if label=="start":
                add([side(index,"high",z0),side(index,"low",z0),
                     side(index,"low",z1),side(index,"high",z1)],label)
            else:
                add([side(index,"low",z0),side(index,"high",z0),
                     side(index,"high",z1),side(index,"low",z1)],label)

    endpoint_cap(0,"start")
    endpoint_cap(-1,"end")

    for i, (sa, sb) in enumerate(zip(ss, ss[1:])):
        if sb-sa <= 1.0e-9:
            continue
        mid = (sa+sb)/2.0
        hm = wall_height(mid)
        if hm <= 1.0e-9:
            continue
        if not is_void(mid, max(1.0e-7, hm*1.0e-6)):
            add([side(i,"high",0), side(i+1,"high",0),
                 side(i+1,"low",0), side(i,"low",0)], "bottom")
        if not is_void(mid, hm-max(1.0e-7, hm*1.0e-6)):
            add([side(i,"low",wall_height(sa)), side(i+1,"low",wall_height(sb)),
                 side(i+1,"high",wall_height(sb)), side(i,"high",wall_height(sa))], "top")

        # Each sorted polygon crossing changes in/out parity.  Add only
        # material bands.  At polygon corners a quad may become a triangle.
        crossings = []
        for poly in polygons:
            crossings.extend((z, poly, edge) for z, edge in scan_edges(poly, mid)
                             if 1.0e-8 < z < hm-1.0e-8)
        crossings.sort(key=lambda item: item[0])
        boundaries = [(0.0, None, None)] + crossings + [(hm, None, None)]

        def band_z(boundary, s):
            z, poly, edge = boundary
            if poly is None:
                return 0.0 if z == 0.0 else wall_height(s)
            return max(0.0, min(wall_height(s), edge_height(poly, edge, s)))

        for lo, hi in zip(boundaries, boundaries[1:]):
            if hi[0]-lo[0] < 1.0e-8 or is_void(mid, (hi[0]+lo[0])/2.0):
                continue
            a0, a1 = band_z(lo, sa), band_z(lo, sb)
            b0, b1 = band_z(hi, sa), band_z(hi, sb)
            add([side(i,"low",a0), side(i+1,"low",a1),
                 side(i+1,"low",b1), side(i,"low",b0)], "side")
            add([side(i+1,"high",a1), side(i,"high",a0),
                 side(i,"high",b0), side(i+1,"high",b1)], "side")

    # Through-thickness reveals trace the polygon boundary itself, including
    # jambs and slanted heads, split at sampled curve facets.
    for poly in polygons:
        for a, b in zip(poly, poly[1:]+poly[:1]):
            clipped = clip_to_wall(a, b, L, p["base_profile"], p["top_profile"])
            if clipped is None:
                continue
            a, b = clipped
            # A polygon's clipping segment on x=0 or x=L is not a real
            # jamb: the opening is flush with (and open through) the end.
            if abs(a[0]-b[0])<1e-8 and (
                    abs(a[0])<1e-8 or abs(a[0]-L)<1e-8):
                continue
            mid = ((a[0]+b[0])/2.0, (a[1]+b[1])/2.0)
            if mid[1] <= 1.0e-8 or mid[1] >= wall_height(mid[0])-1.0e-8:
                continue  # a free boundary at the wall's floor or head
            points2 = [a]
            if abs(a[0]-b[0]) > 1.0e-9:
                between = [s for s in ss if min(a[0],b[0])+1.0e-8 < s <
                           max(a[0],b[0])-1.0e-8]
                if b[0] < a[0]:
                    between.reverse()
                points2.extend((s, a[1]+(b[1]-a[1])*(s-a[0])/(b[0]-a[0]))
                               for s in between)
            points2.append(b)
            for p0, p1 in zip(points2, points2[1:]):
                i0, i1 = index_at(p0[0]), index_at(p1[0])
                add([side(i0,"low",p0[1]), side(i1,"low",p1[1]),
                     side(i1,"high",p1[1]), side(i0,"high",p0[1])], "opening")

    _stitch_opening_mesh(mesh)
    if previous is not None:
        transfer_semantic_face_appearance(previous.mesh, mesh, FACE_KEY,
                                          fallback_key="side",
                                          drop_keys=(JOINT_FACE_KEY,))
    if caps and not wall_has_custom_profile(p):
        _hide_joint_seam_edges(mesh, caps.get("start"), p["height"])
        _hide_joint_seam_edges(mesh, caps.get("end"), p["height"])
    soften_curve_facets(mesh)
    if len(path) > 2:
        wrap_soft_surface_textures(mesh)
    body = Group(mesh, name=body_name)
    body.component = False
    if previous is not None:
        body.material = copy.deepcopy(previous.material)
        body.layer = previous.layer
    return body


def build_body(values, previous=None, path=None, caps=None, crease_edges=None,
               smooth_path=False, offsets=None, body_name="Corpo da parede"):
    p = validate(values)
    if path is None:
        path = [QVector3D(0,0,0), QVector3D(p["length"],0,0)]
    if any(op.get("kind") == "polygon" for op in p.get("openings", [])):
        return _build_body_with_polygon_openings(p, previous, path, caps,
                                                 offsets, body_name)
    if p.get("openings"):
        return _build_body_with_openings(p, previous, path, caps, offsets, body_name)

    low_b, high_b, low_t, high_t, base_z, top_z, _cum = _profiled_sides(
        p, path, offsets=offsets, caps=caps)
    if len(low_b) < 2:
        raise WallError("Não foi possível gerar o corpo da parede.")

    mesh=Mesh()
    def face(points,key):
        f=mesh.add_face(points);f.attrs[FACE_KEY]=key;return f

    face([QVector3D(high_b[0].x(),high_b[0].y(),base_z[0]),
          QVector3D(low_b[0].x(),low_b[0].y(),base_z[0]),
          QVector3D(low_t[0].x(),low_t[0].y(),top_z[0]),
          QVector3D(high_t[0].x(),high_t[0].y(),top_z[0])],"start")
    face([QVector3D(low_b[-1].x(),low_b[-1].y(),base_z[-1]),
          QVector3D(high_b[-1].x(),high_b[-1].y(),base_z[-1]),
          QVector3D(high_t[-1].x(),high_t[-1].y(),top_z[-1]),
          QVector3D(low_t[-1].x(),low_t[-1].y(),top_z[-1])],"end")
    for i in range(len(low_b)-1):
        face([QVector3D(high_b[i].x(),high_b[i].y(),base_z[i]),
              QVector3D(high_b[i+1].x(),high_b[i+1].y(),base_z[i+1]),
              QVector3D(low_b[i+1].x(),low_b[i+1].y(),base_z[i+1]),
              QVector3D(low_b[i].x(),low_b[i].y(),base_z[i])],"bottom")
        face([QVector3D(low_t[i].x(),low_t[i].y(),top_z[i]),
              QVector3D(low_t[i+1].x(),low_t[i+1].y(),top_z[i+1]),
              QVector3D(high_t[i+1].x(),high_t[i+1].y(),top_z[i+1]),
              QVector3D(high_t[i].x(),high_t[i].y(),top_z[i])],"top")
        face([QVector3D(low_b[i].x(),low_b[i].y(),base_z[i]),
              QVector3D(low_b[i+1].x(),low_b[i+1].y(),base_z[i+1]),
              QVector3D(low_t[i+1].x(),low_t[i+1].y(),top_z[i+1]),
              QVector3D(low_t[i].x(),low_t[i].y(),top_z[i])],"side")
        face([QVector3D(high_b[i+1].x(),high_b[i+1].y(),base_z[i+1]),
              QVector3D(high_b[i].x(),high_b[i].y(),base_z[i]),
              QVector3D(high_t[i].x(),high_t[i].y(),top_z[i]),
              QVector3D(high_t[i+1].x(),high_t[i+1].y(),top_z[i+1])],"side")

    if previous is not None:
        transfer_semantic_face_appearance(previous.mesh, mesh, FACE_KEY,
                                          fallback_key="side",
                                          drop_keys=(JOINT_FACE_KEY,))

    # Preserve optional technical crease edges only on legacy vertical walls;
    # on profiled walls those vertical assumptions are no longer valid.
    if not wall_has_custom_profile(p):
        for pair in crease_edges or ():
            if not isinstance(pair,(list,tuple)) or len(pair)!=2: continue
            a,b=QVector3D(pair[0]),QVector3D(pair[1])
            if (b-a).length()<=1e-9: continue
            try:
                e=mesh.add_edge(a,b);e.hidden=False;e.soft=False
            except ValueError: pass
    if caps and not wall_has_custom_profile(p):
        _hide_joint_seam_edges(mesh,caps.get("start"),p["height"]);_hide_joint_seam_edges(mesh,caps.get("end"),p["height"])
    if smooth_path or wall_has_custom_profile(p):
        soften_curve_facets(mesh)
    if smooth_path or len(path) > 2:
        wrap_soft_surface_textures(mesh)
    body=Group(mesh,name=body_name);body.component=False
    if previous is not None:
        body.material=copy.deepcopy(previous.material);body.layer=previous.layer
    return body

def finalize_wall_surface_maps(children, values, path, smooth_path=False):
    """Restore committed UV continuity only on genuinely curved wall skins.

    Straight/profiled walls deliberately keep the host planar face mapping.
    A previous experimental build triangulated twisted straight walls and
    transported UVs across that diagonal; the live preview looked plausible
    but the committed wall distorted textures.  Curved walls still need the
    hinge-walk map because their visible side is made of many soft facets.
    """
    try:
        pts = list(path or ())
        if not (smooth_path or len(pts) > 2):
            return
        for child in list(children or ()):
            mesh = getattr(child, "mesh", None)
            if mesh is not None:
                wrap_soft_surface_textures(mesh)
    except Exception:
        return


def build_children(values, previous_children=None, path=None, caps=None, crease_edges=None, smooth_path=False):
    """Build one body per composite layer; simple walls keep one body."""
    p = validate(values)
    previous_children = list(previous_children or [])
    by_name = {getattr(c, "name", ""): c for c in previous_children}
    children=[]
    for i,(layer,low,high) in enumerate(wall_layer_bands(p)):
        name = "Corpo da parede" if p.get("structure") != "composite" else f"Camada parede · {layer.get('name','Camada')}"
        previous = by_name.get(name)
        if previous is None and i < len(previous_children): previous = previous_children[i]
        children.append(build_body(p, previous=previous, path=path, caps=caps,
                                   crease_edges=crease_edges, smooth_path=smooth_path,
                                   offsets=(low,high), body_name=name))
    return children


def make_wall_segment(start, end, values, template=None):
    """Create one independent straight wall between two world XY points.

    ``template`` is optional and is used by the vertex/split workflow so each
    new segment inherits the original wall's layer, container material, BIM tag
    and painted face attributes while receiving its own fresh Group/UID.
    """
    p = dict(values)
    dx, dy = end.x() - start.x(), end.y() - start.y()
    p["length"] = math.hypot(dx, dy)
    p = validate(p)
    local_path = [QVector3D(0, 0, 0), QVector3D(p["length"], 0, 0)]

    previous_children = list(getattr(template, "children", None) or []) if template is not None else []
    parent = Group(name=getattr(template, "name", None) or "Parede")
    parent.adopt(build_children(p, previous_children=previous_children, path=local_path))
    parent.component = False
    parent.xform.translate(start.x(), start.y(), p["base"])
    parent.xform.rotate(math.degrees(math.atan2(dy, dx)), 0, 0, 1)
    parent.ext = {KEY: record(p, local_path)}
    if template is not None:
        parent.layer = getattr(template, "layer", None)
        parent.material = copy.deepcopy(getattr(template, "material", None))
        parent.ifc = copy.deepcopy(getattr(template, "ifc", None))
    if parent.ifc is None:
        parent.ifc = {"class": "IfcWall", "name": parent.name}
    from .bim import ensure_ifc_identity
    ensure_ifc_identity(parent, "IfcWall")
    return parent


def make_arc_wall(start, end, sagitta, values, template=None):
    """Create one independent circular wall from world endpoints + signed sagitta.

    The stored arc is canonical and local: start=(0,0), the chord lies on +X,
    and ``sagitta`` is positive to the left of start→end.  All three creation
    workflows (endpoint+sagitta, centre, 3 points) converge to this same record.
    """
    a, b = QVector3D(start), QVector3D(end)
    dx, dy = b.x() - a.x(), b.y() - a.y()
    chord = math.hypot(dx, dy)
    if chord < MIN_DIM:
        raise WallError("A parede curva precisa ter ao menos 1 mm entre os extremos.")
    h = float(sagitta)
    if not math.isfinite(h) or abs(h) < ARC_EPS:
        raise WallError("Defina uma curvatura diferente de zero para a parede curva.")
    if abs(h) > chord * 5.0:
        raise WallError("A flecha está excessiva para esta parede.")

    p = dict(values)
    low, high = wall_offsets(p)
    radius = chord * chord / (8.0 * abs(h)) + abs(h) / 2.0
    nearest_radius = (radius + min(low, high) if h > 0.0
                      else radius - max(low, high))
    if nearest_radius <= max(MIN_DIM, abs(high-low) * 0.02):
        raise WallError("A curvatura é fechada demais para esta espessura/alinhamento.")

    local_start = QVector3D(0.0, 0.0, 0.0)
    local_end = QVector3D(chord, 0.0, 0.0)
    path_rec = arc_record(local_start, local_end, h)
    samples = arc_points(local_start, local_end, h)
    p["length"] = path_length_from_record({"path": path_rec})
    p = validate(p)

    previous_children = list(getattr(template, "children", None) or []) if template is not None else []
    parent = Group(name=getattr(template, "name", None) or "Parede")
    parent.adopt(build_children(p, previous_children=previous_children, path=samples, smooth_path=True))
    parent.component = False
    parent.xform.translate(a.x(), a.y(), p["base"])
    parent.xform.rotate(math.degrees(math.atan2(dy, dx)), 0, 0, 1)
    parent.ext = {KEY: record(p, samples, path_record=path_rec)}
    if template is not None:
        parent.layer = getattr(template, "layer", None)
        parent.material = copy.deepcopy(getattr(template, "material", None))
        parent.ifc = copy.deepcopy(getattr(template, "ifc", None))
    if parent.ifc is None:
        parent.ifc = {"class": "IfcWall", "name": parent.name}
    from .bim import ensure_ifc_identity
    ensure_ifc_identity(parent, "IfcWall")
    return parent


def make_wall(start, end, values):
    return make_wall_segment(start, end, values)


def _check_transform(group):
    if group.xform is None or not group.children or group.mesh.faces:
        raise WallError("A estrutura da parede foi alterada. Desfaça a alteração para editá-la.")
    m = group.xform
    x, y, z = (m.mapVector(QVector3D(*v)) for v in
               ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    if (any(abs(v.length() - 1.0) > 1e-5 for v in (x, y, z))
            or abs(x.z()) > 1e-5 or abs(y.z()) > 1e-5
            or (z - QVector3D(0, 0, 1)).length() > 1e-5
            or abs(QVector3D.dotProduct(x, y)) > 1e-5
            or QVector3D.dotProduct(QVector3D.crossProduct(x, y), z) < 0.9999):
        raise WallError("Parede escalada, inclinada ou espelhada. Desfaça e use os campos da paleta.")


def read_wall(group):
    """Read parameters and verify that generated geometry is still intact."""
    rec = wall_record(group)
    if rec is None or rec.get("schema") != SCHEMA:
        raise WallError("Versão dos parâmetros da parede não reconhecida.")
    _check_transform(group)
    path = path_points_from_record(rec)
    origin = group.xform.map(QVector3D(0, 0, 0))
    p = validate({"length": path_length_from_record(rec), "height": rec.get("height"),
                  "thickness": rec.get("thickness"), "base": origin.z(),
                  "alignment": rec.get("alignment"),
                  "base_level": rec.get("base_level"),
                  "top_mode": rec.get("top_mode", "height"),
                  "top_level": rec.get("top_level"),
                  "top_offset": rec.get("top_offset", 0.0),
                  "material_name": rec.get("material_name"),
                  "structure": rec.get("structure", "simple"),
                  "layers": rec.get("layers", []),
                  "openings": rec.get("openings", []),
                  "base_profile": rec.get("base_profile", [0.0, 0.0]),
                  "top_profile": rec.get("top_profile", [rec.get("height", 3.0), rec.get("height", 3.0)]),
                  "top_xy": rec.get("top_xy", [[0.0, 0.0], [0.0, 0.0]])})
    for body in group.children:
        if body.children or body.xform is not None:
            raise WallError("O corpo da parede foi transformado separadamente. Desfaça a alteração.")
    # Composite walls and profiled/sloped walls contain generated topology that
    # is intentionally richer than the legacy vertical prism envelope.  Their
    # parameter record is authoritative; direct mesh edits are still rejected by
    # the child/xform checks above.
    if p.get("structure") == "composite" or wall_has_custom_profile(p):
        return p
    # Hosted openings add legitimate reveal vertices/faces inside the envelope;
    # the parameter record is authoritative for those derived cuts.
    if p.get("openings"):
        return p
    body = group.children[0]
    poly = footprint(path, p["thickness"], p["alignment"],
                     caps=caps_from_record(rec), offsets=wall_offsets(p))
    expected = ([QVector3D(v.x(), v.y(), 0) for v in poly]
                + [QVector3D(v.x(), v.y(), p["height"]) for v in poly])
    tolerance = max(p["length"], p["height"], p["thickness"], 1.0) * 2e-6

    # Validate the solid's face topology, not every vertex in the mesh.  The
    # junction resolver may add free technical crease edges on a face; their
    # endpoints are intentionally not part of the wall solid and must not make
    # the parametric wall look as if the user edited its geometry by hand.
    face_vertices = {}
    for face in body.mesh.faces:
        for loop in (face.loop, *face.hole_loops):
            for vertex in loop:
                face_vertices[id(vertex)] = vertex
    solid_vertices = list(face_vertices.values())
    # Derived junction cleanup in 0.2.10 briefly split real boundary edges.
    # Accept extra *collinear* face vertices so those documents can be opened
    # and regenerated by the current deterministic resolver.  Every canonical
    # prism corner must still exist and every extra vertex must lie on a real
    # boundary edge; moving geometry off the parametric envelope still fails.
    def on_segment(pt, a, b):
        d = b - a
        den = QVector3D.dotProduct(d, d)
        if den <= 1e-18:
            return (pt - a).length() <= tolerance
        t = QVector3D.dotProduct(pt - a, d) / den
        if t < -tolerance or t > 1.0 + tolerance:
            return False
        q = a + d * max(0.0, min(1.0, t))
        return (pt - q).length() <= tolerance

    boundary_segments = []
    n_poly = len(poly)
    for i in range(n_poly):
        j = (i + 1) % n_poly
        boundary_segments.append((expected[i], expected[j]))
        boundary_segments.append((expected[n_poly + i], expected[n_poly + j]))
        boundary_segments.append((expected[i], expected[n_poly + i]))

    missing_corner = any(
        not any((vertex.position - pt).length() <= tolerance for vertex in solid_vertices)
        for pt in expected)
    off_envelope = any(
        not any(on_segment(vertex.position, a, b) for a, b in boundary_segments)
        for vertex in solid_vertices)
    if missing_corner or off_envelope:
        raise WallError("A geometria foi editada diretamente. Desfaça para recuperar a edição paramétrica.")
    return p


def path_world(group):
    return [group.xform.map(p) for p in wall_path(group)]


def _profile_interp(values, fraction):
    p = validate(values)
    t = max(0.0, min(1.0, float(fraction)))
    bz = p["base_profile"][0] + (p["base_profile"][1] - p["base_profile"][0]) * t
    tz = p["top_profile"][0] + (p["top_profile"][1] - p["top_profile"][0]) * t
    a, b = p["top_xy"]
    ox = a[0] + (b[0] - a[0]) * t
    oy = a[1] + (b[1] - a[1]) * t
    return bz, tz, QVector3D(ox, oy, 0.0)


def profile_at_fraction(values, fraction):
    """Public endpoint-profile sampler used when a wall is split into segments."""
    return _profile_interp(values, fraction)


def wall_has_custom_profile(values):
    p = validate(values)
    eps = 1.0e-9
    return (any(abs(v) > eps for v in p.get("base_profile", (0.0, 0.0)))
            or any(abs(t - (b + p["height"])) > eps
                   for b, t in zip(p.get("base_profile", (0.0, 0.0)),
                                   p.get("top_profile", (p["height"], p["height"]))) )
            or any(abs(c) > eps for pair in p.get("top_xy", ((0.0, 0.0), (0.0, 0.0))) for c in pair))


def base_reference_vertices_local(group):
    values = read_wall(group)
    refs = wall_reference_vertices(group)
    out = []
    for i, ref in enumerate(refs[:2]):
        z = values["base_profile"][i if i < 2 else -1]
        out.append(QVector3D(ref.x(), ref.y(), z))
    return out


def top_reference_vertices_local(group):
    values = read_wall(group)
    refs = wall_reference_vertices(group)
    out = []
    for i, ref in enumerate(refs[:2]):
        ox, oy = values["top_xy"][i]
        out.append(QVector3D(ref.x() + ox, ref.y() + oy, values["top_profile"][i]))
    return out


def base_reference_vertices_world(group):
    return [group.xform.map(p) for p in base_reference_vertices_local(group)]


def top_reference_vertices_world(group):
    return [group.xform.map(p) for p in top_reference_vertices_local(group)]


def _profiled_sample_paths(values, path):
    """Return bottom/top reference samples and their local Z profiles."""
    p = validate(values)
    pts, cum = _path_cumulative(path)
    total = cum[-1] if cum else 0.0
    bottoms, tops = [], []
    for i, ref in enumerate(pts):
        t = 0.0 if total <= 1.0e-12 else cum[i] / total
        bz, tz, off = _profile_interp(p, t)
        bottoms.append(QVector3D(ref.x(), ref.y(), bz))
        tops.append(QVector3D(ref.x() + off.x(), ref.y() + off.y(), tz))
    return bottoms, tops, cum


def base_path_world(group):
    values = read_wall(group)
    path = wall_path(group)
    bottoms, _tops, _cum = _profiled_sample_paths(values, path)
    return [group.xform.map(p) for p in bottoms]


def top_path_world(group):
    values = read_wall(group)
    path = wall_path(group)
    _bottoms, tops, _cum = _profiled_sample_paths(values, path)
    return [group.xform.map(p) for p in tops]


def reference_vertices_world(group):
    # Backwards-compatible modelling reference: the lower endpoint stations.
    return base_reference_vertices_world(group)


def local_from_world(group, world):
    inv, ok = group.xform.inverted()
    if not ok:
        raise WallError("Não foi possível converter o ponto para a parede.")
    p = inv.map(world)
    return QVector3D(p.x(), p.y(), 0.0)


def edit_placement(group, base):
    old = group.xform.map(QVector3D(0, 0, 0))
    translate = QMatrix4x4()
    translate.translate(0, 0, base - old.z())
    return translate * group.xform


def split_arc_at_point(start, end, sagitta, point):
    """Split a circular wall arc at the nearest point on its true circle.

    Returns ``(point, sagitta_a, sagitta_b, fraction)``; both sub-arcs remain
    on the original circle. Inputs may be local or world XY coordinates.
    """
    a=QVector3D(start.x(),start.y(),0.0);b=QVector3D(end.x(),end.y(),0.0);p=QVector3D(point.x(),point.y(),0.0)
    h=float(sagitta);chord=b-a;L=math.hypot(chord.x(),chord.y())
    if L<MIN_DIM or abs(h)<ARC_EPS:raise WallError("A parede curva não pôde ser dividida.")
    u=QVector3D(chord.x()/L,chord.y()/L,0);n=QVector3D(-u.y(),u.x(),0);mid=(a+b)*0.5;apex=mid+n*h
    raw=_circumcenter2((a.x(),a.y()),(apex.x(),apex.y()),(b.x(),b.y()))
    if raw is None:raise WallError("A parede curva não pôde ser dividida.")
    c=QVector3D(raw[0],raw[1],0);r=math.hypot(a.x()-c.x(),a.y()-c.y())
    a0=math.atan2(a.y()-c.y(),a.x()-c.x());a1=math.atan2(b.y()-c.y(),b.x()-c.x());am=math.atan2(apex.y()-c.y(),apex.x()-c.x())
    sweep=_wrap_angle(a1-a0);through=_wrap_angle(am-a0)
    if sweep>=0 and not (0<=through<=sweep):sweep-=2*math.pi
    elif sweep<0 and not (sweep<=through<=0):sweep+=2*math.pi
    ang=math.atan2(p.y()-c.y(),p.x()-c.x())
    delta=(ang-a0)%(2*math.pi) if sweep>0 else -((a0-ang)%(2*math.pi))
    t=max(0.0,min(1.0,delta/sweep))
    if t<=1e-4 or t>=1-1e-4:raise WallError("O ponto está muito próximo de um extremo da parede.")
    aq=a0+sweep*t;q=QVector3D(c.x()+r*math.cos(aq),c.y()+r*math.sin(aq),start.z())
    def sag(x,y,sw):
        d=y-x;ll=math.hypot(d.x(),d.y());nn=QVector3D(-d.y()/ll,d.x()/ll,0);mm=(x+y)*0.5
        aa=math.atan2(x.y()-c.y(),x.x()-c.x());ap=QVector3D(c.x()+r*math.cos(aa+sw*0.5),c.y()+r*math.sin(aa+sw*0.5),0)
        return QVector3D.dotProduct(ap-mm,nn)
    return q,float(sag(a,q,sweep*t)),float(sag(q,b,sweep*(1-t))),t
