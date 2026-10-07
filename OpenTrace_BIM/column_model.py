# SPDX-License-Identifier: GPL-3.0-or-later
"""Parametric straight/inclined/curved and tapered multi-segment columns."""
from __future__ import annotations

import copy
import math
from PySide6.QtGui import QVector3D
from core.group import Group
from core.mesh import Mesh

from .curve_utils import soften_curve_facets
from .complex_profile import grouped_loops, has_curved_edges, profile_loops
from .profile_library import resolve_profile
from .materials import transferable_face_attrs

KEY = "arquitetura_parametrica"
SCHEMA = 1
MIN_DIM = 0.001
MAX_DIM = 10000.0
CIRCLE_SEGMENTS = 32
DEFAULTS = {
    "section_type": "simple", "profile_ref": None, "profile_data": None, "profile": "rect",
    "width": 0.30, "depth": 0.30, "diameter": 0.30,
    "rotation": 0.0, "anchor": "mc",
    "base_level": None, "base_offset": 0.0, "base_z": 0.0,
    "top_mode": "height", "top_level": None, "top_offset": 0.0,
    "height": 3.00, "inclination": 0.0, "inclination_azimuth": 0.0,
    "curvature": 0.0, "material_name": None,
    # Section stations along the axis. None means a single untapered segment.
    "stations": None,
}
FACE_KEY = "ap_column_face"
ANCHOR_FACTORS = {
    "tl": (-0.5, 0.5), "tc": (0.0, 0.5), "tr": (0.5, 0.5),
    "ml": (-0.5, 0.0), "mc": (0.0, 0.0), "mr": (0.5, 0.0),
    "bl": (-0.5, -0.5), "bc": (0.0, -0.5), "br": (0.5, -0.5),
}


class ColumnError(ValueError):
    pass


def _station(raw, fallback, t):
    src = raw if isinstance(raw, dict) else {}
    try:
        pos = float(src.get("t", t))
        width = float(src.get("width", fallback["width"]))
        depth = float(src.get("depth", fallback["depth"]))
        diameter = float(src.get("diameter", fallback["diameter"]))
        inclination = float(src.get("inclination", fallback.get("inclination", 0.0)))
        azimuth = float(src.get("inclination_azimuth", fallback.get("inclination_azimuth", 0.0)))
        # Curvature belongs to the outgoing segment. Legacy columns stored one
        # global value; migrate that value only to the first segment so a
        # multi-segment pillar never corrugates all segments together.
        curvature = float(src.get("curvature", fallback.get("curvature", 0.0) if t <= 1.0e-9 else 0.0))
    except (TypeError, ValueError) as exc:
        raise ColumnError("As dimensões dos segmentos do pilar são inválidas.") from exc
    if not all(math.isfinite(v) for v in (pos, width, depth, diameter, inclination, azimuth, curvature)):
        raise ColumnError("Os parâmetros dos segmentos do pilar devem ser finitos.")
    if not 0.0 <= pos <= 1.0:
        raise ColumnError("A posição de um vértice do pilar deve ficar entre base e topo.")
    for dim in (width, depth, diameter):
        if not MIN_DIM <= dim <= MAX_DIM:
            raise ColumnError("As dimensões dos segmentos do pilar devem ficar entre 0,001 e 10.000 m.")
    if not 0.0 <= inclination <= 85.0:
        raise ColumnError("A inclinação de cada segmento deve ficar entre 0° e 85°.")
    if not -360.0 <= azimuth <= 360.0:
        raise ColumnError("A direção de cada segmento deve ficar entre -360° e 360°.")
    if abs(curvature) > MAX_DIM:
        raise ColumnError("A flecha de cada segmento do pilar está fora do intervalo permitido.")
    return {"t": pos, "width": width, "depth": depth, "diameter": diameter,
            "inclination": inclination, "inclination_azimuth": azimuth,
            "curvature": curvature}


def normalize_stations(raw, fallback):
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return [_station({}, fallback, 0.0), _station({}, fallback, 1.0)]
    stations = [_station(item, fallback, i / max(1, len(raw) - 1))
                for i, item in enumerate(raw)]
    stations.sort(key=lambda s: s["t"])
    # Endpoint stations are semantic; clamp near-end values and add missing ends.
    if stations[0]["t"] > 1.0e-7:
        first = dict(stations[0]); first["t"] = 0.0; stations.insert(0, first)
    else:
        stations[0]["t"] = 0.0
    if stations[-1]["t"] < 1.0 - 1.0e-7:
        last = dict(stations[-1]); last["t"] = 1.0; stations.append(last)
    else:
        stations[-1]["t"] = 1.0
    out = [stations[0]]
    for st in stations[1:]:
        if st["t"] - out[-1]["t"] < 1.0e-5:
            out[-1] = st
        else:
            out.append(st)
    if len(out) < 2:
        second = dict(out[0]); second["t"] = 1.0; out.append(second)
    return out


def validate(values):
    out = dict(DEFAULTS); out.update(values or {})
    try:
        for key in ("width", "depth", "diameter", "height", "inclination",
                    "inclination_azimuth", "curvature"):
            out[key] = float(out[key])
        for key in ("rotation", "base_offset", "base_z", "top_offset"):
            out[key] = float(out.get(key, 0.0))
    except (TypeError, ValueError) as exc:
        raise ColumnError("Preencha as medidas do pilar com números válidos.") from exc
    if not all(math.isfinite(out[k]) for k in (
            "width", "depth", "diameter", "height", "inclination",
            "inclination_azimuth", "curvature", "rotation", "base_offset",
            "base_z", "top_offset")):
        raise ColumnError("As medidas do pilar devem ser números finitos.")
    if out.get("section_type") not in ("simple", "complex"):
        out["section_type"] = "simple"
    pref = out.get("profile_ref")
    out["profile_ref"] = str(pref).strip() if pref not in (None, "") else None
    if out["section_type"] == "complex":
        profile = resolve_profile(out.get("profile_ref"), out.get("profile_data"))
        if profile is None:
            raise ColumnError("Perfil complexo não encontrado. Escolha um perfil salvo ou volte para Seção simples.")
        out["profile_ref"] = profile["id"]
        out["profile_data"] = profile
    else:
        out["profile_data"] = None
    if out["profile"] not in ("rect", "circle"):
        raise ColumnError("Forma simples de pilar ainda não suportada.")
    for key in ("width", "depth", "diameter", "height"):
        if not MIN_DIM <= out[key] <= MAX_DIM:
            raise ColumnError("As dimensões do pilar devem ficar entre 0,001 e 10.000 m.")
    if not 0.0 <= out["inclination"] <= 85.0:
        raise ColumnError("A inclinação do pilar deve ficar entre 0° e 85°.")
    if not -360.0 <= out["inclination_azimuth"] <= 360.0:
        raise ColumnError("A direção da inclinação deve ficar entre -360° e 360°.")
    if abs(out["curvature"]) > MAX_DIM:
        raise ColumnError("A flecha do pilar está fora do intervalo permitido.")
    if out.get("anchor") not in ANCHOR_FACTORS:
        out["anchor"] = "mc"
    if out.get("top_mode") not in ("height", "level"):
        out["top_mode"] = "height"
    for key in ("base_level", "top_level"):
        val = out.get(key)
        out[key] = str(val).strip() if val not in (None, "") else None
    if abs(out["base_z"]) > MAX_DIM or abs(out["base_offset"]) > MAX_DIM or abs(out["top_offset"]) > MAX_DIM:
        raise ColumnError("Cota ou offset do pilar fora do intervalo permitido.")
    mat = out.get("material_name")
    out["material_name"] = str(mat).strip() if mat not in (None, "") else None
    out["stations"] = normalize_stations(out.get("stations"), out)
    # Keep legacy broad dimensions aligned with the first station.
    out["width"] = out["stations"][0]["width"]
    out["depth"] = out["stations"][0]["depth"]
    out["diameter"] = out["stations"][0]["diameter"]
    return out


def column_record(group):
    ext = getattr(group, "ext", None)
    rec = ext.get(KEY) if isinstance(ext, dict) else None
    return rec if isinstance(rec, dict) and rec.get("kind") == "column" else None


def _profile_polygon(values, dims=None):
    p = validate(values)
    if p.get("section_type") == "complex":
        loops = profile_loops(p.get("profile_data"))
        outers = [L for L in loops if not L.get("hole")]
        if not outers:
            raise ColumnError("O Perfil Complexo selecionado não contém contorno externo válido.")
        def _area2(L):
            pts=L["points"];n=len(pts)
            return sum(pts[i][0]*pts[(i+1)%n][1]-pts[(i+1)%n][0]*pts[i][1] for i in range(n))
        outer = max(outers, key=lambda L: abs(_area2(L)))
        return [QVector3D(float(x), float(y), 0.0) for x,y in outer["points"]]
    dims = dims or p["stations"][0]
    ax, ay = ANCHOR_FACTORS[p["anchor"]]
    if p["profile"] == "rect":
        width, depth = float(dims["width"]), float(dims["depth"])
        cx, cy = -ax * width, -ay * depth
        hw, hd = width / 2.0, depth / 2.0
        return [QVector3D(cx - hw, cy - hd, 0), QVector3D(cx + hw, cy - hd, 0),
                QVector3D(cx + hw, cy + hd, 0), QVector3D(cx - hw, cy + hd, 0)]
    diameter = float(dims["diameter"])
    r = diameter / 2.0; cx, cy = -ax * diameter, -ay * diameter
    return [QVector3D(cx + r * math.cos(2 * math.pi * i / CIRCLE_SEGMENTS),
                      cy + r * math.sin(2 * math.pi * i / CIRCLE_SEGMENTS), 0)
            for i in range(CIRCLE_SEGMENTS)]


def _segment_centerline(values):
    """Build a piecewise spatial axis and carry semantic station fractions.

    Each station owns the inclination/direction of the segment that starts at
    it.  Intermediate station ``t`` values are vertical fractions of the total
    height, so moving one station vertically changes the segments above/below
    without changing the total pillar height.
    """
    p = validate(values)
    stations = p["stations"]
    points = [QVector3D(0, 0, 0)]
    ts = [0.0]
    current = QVector3D(0, 0, 0)
    total_h = float(p["height"])
    for i, (a, b) in enumerate(zip(stations, stations[1:])):
        dt = float(b["t"] - a["t"])
        dz = total_h * dt
        if dz < MIN_DIM * 0.25:
            continue
        angle = math.radians(float(a.get("inclination", p.get("inclination", 0.0))))
        az = math.radians(float(a.get("inclination_azimuth", p.get("inclination_azimuth", 0.0))) - p.get("rotation", 0.0))
        direction = QVector3D(math.cos(az), math.sin(az), 0)
        run = dz * math.tan(angle)
        # Each semantic segment owns its own flecha. Curving one segment must
        # not alter the neighbouring segments.
        sag = float(a.get("curvature", 0.0))
        chord = math.hypot(run, dz)
        if abs(sag) > chord * 5.0:
            raise ColumnError("A curvatura é fechada demais para este segmento do pilar.")
        if abs(sag) > 1.0e-9:
            try:
                from .model import arc_points
                raw = arc_points(QVector3D(0, 0, 0), QVector3D(run, dz, 0), -sag)
            except Exception as exc:
                raise ColumnError(str(exc)) from exc
        else:
            raw = [QVector3D(0,0,0), QVector3D(run,dz,0)]
        # Skip duplicated first point between adjacent segments.
        count = max(1, len(raw) - 1)
        for j, q in enumerate(raw[1:], 1):
            frac = float(a["t"]) + dt * (j / count)
            points.append(current + direction * q.x() + QVector3D(0,0,q.y()))
            ts.append(frac)
        current = QVector3D(points[-1])
        ts[-1] = float(b["t"])
    if len(points) == 1:
        points.append(QVector3D(0,0,total_h)); ts.append(1.0)
    return points, ts


def _raw_centerline(values):
    return _segment_centerline(values)[0]

def _polyline_lengths(points):
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + (b - a).length())
    return cumulative


def _point_at_fraction(points, cumulative, t):
    if not points:
        return QVector3D()
    if len(points) == 1 or cumulative[-1] <= 1.0e-12:
        return QVector3D(points[0])
    target = max(0.0, min(1.0, float(t))) * cumulative[-1]
    for i in range(len(cumulative) - 1):
        a, b = cumulative[i], cumulative[i + 1]
        if target <= b + 1.0e-12:
            u = 0.0 if b <= a else (target - a) / (b - a)
            return points[i] + (points[i + 1] - points[i]) * u
    return QVector3D(points[-1])


def _centerline_local(values):
    return _segment_centerline(values)

def _dims_at(stations, t):
    t = max(0.0, min(1.0, float(t)))
    for a, b in zip(stations, stations[1:]):
        if t <= b["t"] + 1.0e-12:
            span = b["t"] - a["t"]
            u = 0.0 if span <= 1.0e-12 else (t - a["t"]) / span
            return {
                "width": a["width"] + (b["width"] - a["width"]) * u,
                "depth": a["depth"] + (b["depth"] - a["depth"]) * u,
                "diameter": a["diameter"] + (b["diameter"] - a["diameter"]) * u,
            }
    return dict(stations[-1])


def insert_station(values, t):
    p = validate(values)
    t = max(0.0, min(1.0, float(t)))
    if t <= 1.0e-4 or t >= 1.0 - 1.0e-4:
        raise ColumnError("Insira o vértice entre a base e o topo do pilar.")
    stations = [dict(s) for s in p["stations"]]
    if any(abs(s["t"] - t) < 1.0e-4 for s in stations):
        raise ColumnError("Já existe um vértice praticamente nessa posição.")
    owner = stations[0]
    for a,b in zip(stations,stations[1:]):
        if t <= b["t"] + 1.0e-12:
            owner = a; break
    dims = _dims_at(stations, t); dims["t"] = t
    dims["inclination"] = float(owner.get("inclination", p.get("inclination",0.0)))
    dims["inclination_azimuth"] = float(owner.get("inclination_azimuth", p.get("inclination_azimuth",0.0)))
    # New stations start straight; curvature can then be assigned independently
    # to either resulting segment from the contextual radial palette.
    dims["curvature"] = 0.0
    stations.append(dims); stations.sort(key=lambda s: s["t"])
    out = dict(p); out["stations"] = stations
    return validate(out)


def move_station_vertical(values, index, world_z, base_z=None):
    """Move an intermediate semantic station vertically.

    The neighbours keep their positions; therefore the vertical heights of the
    segment below and above change together.
    """
    p = validate(values)
    stations = [dict(s) for s in p["stations"]]
    i = int(index)
    if i <= 0 or i >= len(stations)-1:
        raise ColumnError("Use os controles de base/topo para os extremos do pilar.")
    base = float(p.get("base_z",0.0) if base_z is None else base_z)
    t = (float(world_z) - base) / max(MIN_DIM, float(p["height"]))
    lo = float(stations[i-1]["t"]) + max(1.0e-4, MIN_DIM/max(MIN_DIM,p["height"]))
    hi = float(stations[i+1]["t"]) - max(1.0e-4, MIN_DIM/max(MIN_DIM,p["height"]))
    if lo >= hi:
        raise ColumnError("Não há espaço vertical suficiente entre os vértices vizinhos.")
    stations[i]["t"] = max(lo, min(hi, t))
    out = dict(p); out["stations"] = stations
    return validate(out)


def segment_index_at_fraction(values, t):
    p=validate(values); t=max(0.0,min(1.0,float(t)))
    for i,b in enumerate(p["stations"][1:]):
        if t <= float(b["t"]) + 1.0e-9:return i
    return max(0,len(p["stations"])-2)

def _curve_section_scale(values, centers, fractions, index):
    """Scale generated curve rings so an oblique curve does not inflate section.

    The numeric segment section remains authoritative.  Because the current
    column body uses horizontal rings, an oblique tangent would otherwise make
    the effective section normal to the curve larger than the value entered by
    the user.  Multiplying by cos(tangent-from-vertical) keeps that effective
    section at or below the numeric value.  A 50% floor is the agreed anchorage
    limit; tighter bends require an explicit transition/narrower neighbouring
    segment instead of silently collapsing the connection.
    """
    p=values;stations=p["stations"];t=float(fractions[index])
    # Apply the rule only where a curved semantic segment touches this ring.
    curved=False
    for si,(a,b) in enumerate(zip(stations,stations[1:])):
        if abs(float(a.get("curvature",0.0)))<=1.0e-9:continue
        if float(a["t"])-1.0e-8 <= t <= float(b["t"])+1.0e-8:
            curved=True;break
    if not curved:return 1.0
    if len(centers)<2:return 1.0
    if index<=0:tangent=centers[1]-centers[0]
    elif index>=len(centers)-1:tangent=centers[-1]-centers[-2]
    else:tangent=centers[index+1]-centers[index-1]
    length=tangent.length()
    if length<=1.0e-12:return 1.0
    factor=abs(float(tangent.z()))/length
    factor=min(1.0,max(0.0,factor))
    if factor < 0.5-1.0e-7:
        raise ColumnError("Esta curvatura reduziria a seção de ancoragem para menos de 50% da medida definida. Reduza a curva, afine explicitamente a seção de contato ou crie um segmento de transição.")
    return max(0.5,factor)

def build_body(values, previous=None):
    p = validate(values)
    centers, fractions = _centerline_local(p)
    mesh = Mesh()
    old_attrs, old_default = {}, None
    if previous is not None:
        for face in previous.mesh.faces:
            attrs = transferable_face_attrs(face); key = attrs.get(FACE_KEY)
            if key is not None: old_attrs.setdefault(key, attrs)
            if old_default is None: old_default = copy.deepcopy(attrs)

    if p.get("section_type") == "complex":
        base_loops = profile_loops(p.get("profile_data"))
        if not base_loops:
            raise ColumnError("O Perfil Complexo selecionado não contém contornos válidos.")
        ring_loops=[]
        for idx,(center,t) in enumerate(zip(centers,fractions)):
            scale=_curve_section_scale(p,centers,fractions,idx)
            ring=[]
            for L in base_loops:
                ring.append([QVector3D(center.x()+float(x)*scale,
                                       center.y()+float(y)*scale,
                                       center.z()) for x,y in L["points"]])
            ring_loops.append(ring)
        groups=grouped_loops(base_loops);index_of={id(L):i for i,L in enumerate(base_loops)}
        for grp in groups:
            oi=index_of[id(grp["outer"])];his=[index_of[id(h)] for h in grp["holes"]]
            f=mesh.add_face(list(reversed(ring_loops[0][oi])),
                            [list(reversed(ring_loops[0][hi])) for hi in his] or None)
            f.attrs.update(old_attrs.get("bottom",old_default or {}));f.attrs[FACE_KEY]="bottom"
            f=mesh.add_face(ring_loops[-1][oi],[ring_loops[-1][hi] for hi in his] or None)
            f.attrs.update(old_attrs.get("top",old_default or {}));f.attrs[FACE_KEY]="top"
        for k in range(len(ring_loops)-1):
            for li,L in enumerate(base_loops):
                a,b=ring_loops[k][li],ring_loops[k+1][li];n=len(a)
                for i in range(n):
                    j=(i+1)%n
                    f=mesh.add_face([a[i],a[j],b[j],b[i]])
                    f.attrs.update(old_attrs.get("side",old_default or {}));f.attrs[FACE_KEY]="side"
        if any(abs(float(st.get("curvature",0.0)))>1e-9 for st in p.get("stations",())) or has_curved_edges(p.get("profile_data")):
            soften_curve_facets(mesh)
    else:
        rings = []
        for idx,(center, t) in enumerate(zip(centers, fractions)):
            dims=_dims_at(p["stations"], t)
            scale=_curve_section_scale(p,centers,fractions,idx)
            if scale < 1.0-1.0e-9:
                dims=dict(dims)
                dims["width"]*=scale;dims["depth"]*=scale;dims["diameter"]*=scale
            poly = _profile_polygon(p, dims)
            rings.append([QVector3D(v.x() + center.x(), v.y() + center.y(), center.z()) for v in poly])
        face = mesh.add_face(list(reversed(rings[0])))
        face.attrs.update(old_attrs.get("bottom", old_default or {})); face.attrs[FACE_KEY] = "bottom"
        face = mesh.add_face(rings[-1])
        face.attrs.update(old_attrs.get("top", old_default or {})); face.attrs[FACE_KEY] = "top"
        n = len(rings[0])
        for k in range(len(rings) - 1):
            a, b = rings[k], rings[k + 1]
            for i in range(n):
                j = (i + 1) % n
                face = mesh.add_face([a[i], a[j], b[j], b[i]])
                face.attrs.update(old_attrs.get("side", old_default or {})); face.attrs[FACE_KEY] = "side"
        if any(abs(float(st.get("curvature", 0.0))) > 1.0e-9 for st in p.get("stations", ())) or p.get("profile") == "circle":
            soften_curve_facets(mesh)
    body = Group(mesh, name="Corpo do pilar"); body.component = False
    if previous is not None:
        body.material = copy.deepcopy(previous.material); body.layer = previous.layer
    return body


def _record(values):
    p = validate(values)
    return {
        "schema": SCHEMA, "kind": "column", "section_type": p.get("section_type", "simple"),
        "profile_ref": p.get("profile_ref"), "profile_data": copy.deepcopy(p.get("profile_data")), "profile": p["profile"],
        "width": p["width"], "depth": p["depth"], "diameter": p["diameter"],
        "stations": copy.deepcopy(p["stations"]),
        "rotation": p["rotation"], "anchor": p["anchor"],
        "base_level": p.get("base_level"), "base_offset": p.get("base_offset", 0.0),
        "base_z": p["base_z"], "top_mode": p["top_mode"],
        "top_level": p.get("top_level"), "top_offset": p.get("top_offset", 0.0),
        "height": p["height"], "inclination": p.get("inclination", 0.0),
        "inclination_azimuth": p.get("inclination_azimuth", 0.0),
        "curvature": p.get("curvature", 0.0), "material_name": p.get("material_name"),
    }


def make_column(point, values, template=None):
    p = validate(values); point = QVector3D(point)
    previous = template.children[0] if template is not None and getattr(template, "children", None) else None
    parent = Group(name=getattr(template, "name", None) or "Pilar")
    parent.adopt([build_body(p, previous=previous)]); parent.component = False
    parent.xform.translate(point.x(), point.y(), p["base_z"])
    parent.xform.rotate(p["rotation"], 0, 0, 1)
    parent.ext = {KEY: _record(p)}
    if template is not None:
        parent.layer = getattr(template, "layer", None)
        parent.material = copy.deepcopy(getattr(template, "material", None))
        parent.ifc = copy.deepcopy(getattr(template, "ifc", None))
    if parent.ifc is None:
        parent.ifc = {"class": "IfcColumn", "name": parent.name}
    from .bim import ensure_ifc_identity
    ensure_ifc_identity(parent, "IfcColumn")
    return parent


def read_column(group):
    rec = column_record(group)
    if rec is None or rec.get("schema") != SCHEMA:
        raise ColumnError("Versão dos parâmetros do pilar não reconhecida.")
    if len(getattr(group, "children", ())) != 1:
        raise ColumnError("A estrutura do pilar foi alterada. Desfaça para editar.")
    origin = group.xform.map(QVector3D(0, 0, 0))
    return validate(dict(rec, base_z=origin.z(), curvature=rec.get("curvature", 0.0),
                         stations=rec.get("stations")))


def insertion_world(group):
    return group.xform.map(QVector3D(0, 0, 0))


def reference_path_world_for(group, values):
    pts, _fractions = _centerline_local(values)
    return [group.xform.map(q) for q in pts]


def reference_path_world(group):
    return reference_path_world_for(group, read_column(group))


def top_world(group):
    return reference_path_world(group)[-1]


def midpoint_world(group):
    pts = reference_path_world(group)
    return pts[len(pts) // 2]


def station_points_world(group):
    p = read_column(group)
    pts, ts = _centerline_local(p)
    out=[]
    for st in p["stations"]:
        t=float(st["t"]);best=min(range(len(ts)),key=lambda i:abs(ts[i]-t))
        if abs(ts[best]-t)<1.0e-7: q=pts[best]
        else:
            # Fallback interpolation for a future sampler that does not emit
            # exact semantic station points.
            k=max(0,min(len(ts)-2,next((i for i in range(len(ts)-1) if ts[i]<=t<=ts[i+1]),len(ts)-2)))
            span=ts[k+1]-ts[k];u=0.0 if span<=1e-12 else (t-ts[k])/span;q=pts[k]+(pts[k+1]-pts[k])*u
        out.append(group.xform.map(q))
    return out


def nearest_path_fraction(group, world_point):
    """Semantic vertical fraction nearest to a world-space axis click."""
    p=read_column(group);local,ts=_centerline_local(p);path=[group.xform.map(q) for q in local]
    if len(path)<2:return 0.5
    q=QVector3D(world_point);best=None
    for i,(a,b) in enumerate(zip(path,path[1:])):
        d=b-a;den=QVector3D.dotProduct(d,d);u=0.0 if den<=1e-12 else QVector3D.dotProduct(q-a,d)/den;u=max(0.0,min(1.0,u))
        pnt=a+d*u;dist=(q-pnt).lengthSquared();frac=ts[i]+(ts[i+1]-ts[i])*u
        if best is None or dist<best[0]:best=(dist,frac)
    return float(best[1] if best is not None else 0.5)


def profile_world(group, top=False):
    p = read_column(group)
    points = station_points_world(group)
    st = p["stations"][-1] if top else p["stations"][0]
    local_poly = _profile_polygon(p, st)
    # Preserve historical API: profile at semantic base/top station.
    centre_local = _raw_centerline(p)[-1] if top else _raw_centerline(p)[0]
    return [group.xform.map(QVector3D(v.x() + centre_local.x(),
                                      v.y() + centre_local.y(), centre_local.z()))
            for v in local_poly]
