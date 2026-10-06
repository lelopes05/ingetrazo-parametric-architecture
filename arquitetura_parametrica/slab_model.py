# SPDX-License-Identifier: GPL-3.0-or-later
"""Parametric horizontal slabs: data, validation and generated solid geometry."""
from __future__ import annotations

import copy
import math

from PySide6.QtGui import QVector3D
from core.group import Group
from core.mesh import Mesh

from .layers import clone_layers, normalize_layers, total_thickness

KEY = "arquitetura_parametrica"
SCHEMA = 3
MIN_DIM = 0.001
MAX_DIM = 10000.0
ARC_EPS = 1.0e-7
ARC_MAX_STEP_DEG = 7.5
ARC_MAX_SEGMENT = 0.25
ARC_MAX_SAMPLES = 256
DEFAULTS = {
    "thickness": 0.15,
    "reference_plane": "bottom",  # bottom | top
    "base_level": None,
    "base_offset": 0.0,
    "base_z": 0.0,
    "material_name": None,
    "structure": "simple",
    "layers": [],
    "openings": [],
}
FACE_KEY = "ap_slab_side"


class SlabError(ValueError):
    pass


def _xy(raw):
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        raise SlabError("Polígono da laje inválido.")
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError) as exc:
        raise SlabError("Polígono da laje inválido.") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise SlabError("Polígono da laje inválido.")
    return QVector3D(x, y, 0.0)


def validate(values):
    out = dict(values)
    try:
        out["thickness"] = float(out.get("thickness", DEFAULTS["thickness"]))
        out["base_offset"] = float(out.get("base_offset", 0.0))
        out["base_z"] = float(out.get("base_z", out.get("reference_z", 0.0)))
    except (TypeError, ValueError) as exc:
        raise SlabError("Preencha as medidas da laje com números válidos.") from exc
    if not MIN_DIM <= out["thickness"] <= MAX_DIM:
        raise SlabError("A espessura da laje deve ficar entre 0,001 e 10.000 m.")
    if abs(out["base_offset"]) > MAX_DIM or abs(out["base_z"]) > MAX_DIM:
        raise SlabError("A cota/deslocamento da laje está fora do intervalo permitido.")
    if out.get("reference_plane") not in ("bottom", "top"):
        raise SlabError("Escolha referência inferior ou superior para a laje.")
    level = out.get("base_level")
    out["base_level"] = str(level).strip() if level not in (None, "") else None
    mat=out.get("material_name")
    out["material_name"] = str(mat).strip() if mat not in (None, "") else None
    structure=out.get("structure") if out.get("structure") in ("simple","composite") else "simple"
    out["structure"]=structure
    if structure=="composite":
        layers=normalize_layers(out.get("layers"),out["thickness"],out["material_name"])
        out["layers"]=layers; out["thickness"]=total_thickness(layers)
    else:
        out["layers"]=[]
    out["openings"]=normalize_openings(out.get("openings",[])) if "normalize_openings" in globals() else list(out.get("openings",[]) or [])
    return out


def slab_record(group):
    ext = getattr(group, "ext", None)
    rec = ext.get(KEY) if isinstance(ext, dict) else None
    return rec if isinstance(rec, dict) and rec.get("kind") == "slab" else None


def _cross(a, b, c):
    return ((b.x() - a.x()) * (c.y() - a.y())
            - (b.y() - a.y()) * (c.x() - a.x()))


def _on_segment(a, b, p, tol=1e-9):
    if abs(_cross(a, b, p)) > tol:
        return False
    return (min(a.x(), b.x()) - tol <= p.x() <= max(a.x(), b.x()) + tol
            and min(a.y(), b.y()) - tol <= p.y() <= max(a.y(), b.y()) + tol)


def _segments_intersect(a, b, c, d, tol=1e-9):
    c1, c2 = _cross(a, b, c), _cross(a, b, d)
    c3, c4 = _cross(c, d, a), _cross(c, d, b)
    if ((c1 > tol and c2 < -tol) or (c1 < -tol and c2 > tol)) and \
       ((c3 > tol and c4 < -tol) or (c3 < -tol and c4 > tol)):
        return True
    return ((abs(c1) <= tol and _on_segment(a, b, c, tol))
            or (abs(c2) <= tol and _on_segment(a, b, d, tol))
            or (abs(c3) <= tol and _on_segment(c, d, a, tol))
            or (abs(c4) <= tol and _on_segment(c, d, b, tol)))


def polygon_area(points):
    pts = [QVector3D(p) for p in points]
    return 0.5 * sum(a.x() * b.y() - b.x() * a.y()
                     for a, b in zip(pts, pts[1:] + pts[:1]))


def validate_polygon(points):
    pts = [QVector3D(p.x(), p.y(), 0.0) for p in points]
    if len(pts) < 3:
        raise SlabError("A laje precisa ter pelo menos três vértices.")
    for a, b in zip(pts, pts[1:] + pts[:1]):
        if (b - a).length() < MIN_DIM:
            raise SlabError("Dois vértices da laje estão próximos demais.")
    if abs(polygon_area(pts)) < MIN_DIM * MIN_DIM:
        raise SlabError("O polígono da laje não possui área suficiente.")
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or j == (i + 1) % n or (i == 0 and j == n - 1):
                continue
            c, d = pts[j], pts[(j + 1) % n]
            if _segments_intersect(a, b, c, d):
                raise SlabError("O contorno da laje não pode se cruzar.")
    return pts


def line_edge():
    return {"type": "line"}


def normalize_edge_specs(specs, count):
    if not isinstance(specs, list) or len(specs) != count:
        return [line_edge() for _ in range(count)]
    out = []
    for spec in specs:
        if not isinstance(spec, dict) or spec.get("type") != "arc":
            out.append(line_edge()); continue
        try:
            h = float(spec.get("sagitta", 0.0))
        except (TypeError, ValueError):
            h = 0.0
        if not math.isfinite(h) or abs(h) < ARC_EPS:
            out.append(line_edge())
        else:
            out.append({"type": "arc", "sagitta": h})
    return out


def _circumcenter2(a, b, c):
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    aa = ax * ax + ay * ay; bb = bx * bx + by * by; cc = cx * cx + cy * cy
    ux = (aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / d
    uy = (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / d
    return ux, uy


def _wrap_angle(value):
    while value <= -math.pi: value += 2.0 * math.pi
    while value > math.pi: value -= 2.0 * math.pi
    return value


def arc_points(start, end, sagitta):
    """Sample a circular XY edge from endpoints and signed midpoint sagitta."""
    a = QVector3D(start.x(), start.y(), 0.0); b = QVector3D(end.x(), end.y(), 0.0)
    chord = b - a; length = math.hypot(chord.x(), chord.y())
    if length < MIN_DIM:
        raise SlabError("A aresta da laje é curta demais para ser curvada.")
    h = float(sagitta)
    if abs(h) < ARC_EPS:
        return [a, b]
    u = QVector3D(chord.x()/length, chord.y()/length, 0.0)
    n = QVector3D(-u.y(), u.x(), 0.0)
    mid = (a + b) * 0.5; apex = mid + n * h
    center = _circumcenter2((a.x(),a.y()), (apex.x(),apex.y()), (b.x(),b.y()))
    if center is None:
        return [a,b]
    cx,cy=center; radius=math.hypot(a.x()-cx,a.y()-cy)
    a0=math.atan2(a.y()-cy,a.x()-cx); a1=math.atan2(b.y()-cy,b.x()-cx); am=math.atan2(apex.y()-cy,apex.x()-cx)
    sweep=_wrap_angle(a1-a0); through=_wrap_angle(am-a0)
    if sweep >= 0 and not (0 <= through <= sweep): sweep -= 2*math.pi
    elif sweep < 0 and not (sweep <= through <= 0): sweep += 2*math.pi
    arc_len=abs(sweep)*radius
    spans=max(4,int(math.ceil(abs(math.degrees(sweep))/ARC_MAX_STEP_DEG)),int(math.ceil(arc_len/ARC_MAX_SEGMENT)))
    spans=min(ARC_MAX_SAMPLES,spans)
    return [QVector3D(cx+radius*math.cos(a0+sweep*(i/spans)),cy+radius*math.sin(a0+sweep*(i/spans)),0.0) for i in range(spans+1)]


def sample_boundary(points, edge_specs=None, *, with_map=False):
    logical = validate_polygon(points)
    specs = normalize_edge_specs(edge_specs, len(logical))
    sampled=[]; outgoing=[]
    for i,a in enumerate(logical):
        b=logical[(i+1)%len(logical)]; spec=specs[i]
        seg=arc_points(a,b,spec.get("sagitta",0.0)) if spec.get("type")=="arc" else [a,b]
        # Exclude the edge endpoint; it becomes the start of the next edge.
        for p in seg[:-1]:
            sampled.append(QVector3D(p)); outgoing.append(i)
    if len(sampled) < 3:
        raise SlabError("Contorno derivado da laje inválido.")
    return (sampled,outgoing) if with_map else sampled



def validate_edge_geometry(points, edge_specs=None):
    sampled = sample_boundary(points, edge_specs)
    if abs(polygon_area(sampled)) < MIN_DIM * MIN_DIM:
        raise SlabError("O contorno curvo da laje não possui área suficiente.")
    n = len(sampled)
    for i in range(n):
        a, b = sampled[i], sampled[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or j == (i + 1) % n or (i == 0 and j == n - 1):
                continue
            c, d = sampled[j], sampled[(j + 1) % n]
            if _segments_intersect(a, b, c, d, tol=1e-8):
                raise SlabError("O contorno curvo da laje não pode se cruzar.")
    return sampled

def _point_in_polygon_xy(point, poly):
    x,y=point.x(),point.y(); inside=False
    n=len(poly)
    for i in range(n):
        a,b=poly[i],poly[(i+1)%n]
        if ((a.y()>y)!=(b.y()>y)):
            xin=(b.x()-a.x())*(y-a.y())/((b.y()-a.y()) or 1e-30)+a.x()
            if x < xin: inside=not inside
    return inside


def normalize_openings(raw):
    out=[]
    if not isinstance(raw,(list,tuple)): return out
    for i,item in enumerate(raw):
        if not isinstance(item,dict): continue
        pts_raw=item.get("polygon")
        if not isinstance(pts_raw,list) or len(pts_raw)<3: continue
        try: pts=validate_polygon([_xy(v) for v in pts_raw])
        except SlabError: continue
        specs=normalize_edge_specs(item.get("edges"),len(pts))
        try: validate_edge_geometry(pts,specs)
        except SlabError: continue
        out.append({"id":str(item.get("id") or f"opening-{i+1}"),
                    "kind":str(item.get("kind") or "embedded"),
                    "polygon":[[p.x(),p.y(),0.0] for p in pts],
                    "edges":copy.deepcopy(specs),
                    "source_id":item.get("source_id")})
    return out


def validate_openings(outer_points, outer_specs, openings):
    outer=validate_edge_geometry(outer_points,outer_specs)
    result=[]
    for item in normalize_openings(openings):
        pts=[_xy(v) for v in item["polygon"]]; specs=normalize_edge_specs(item.get("edges"),len(pts)); sampled=validate_edge_geometry(pts,specs)
        if not all(_point_in_polygon_xy(p,outer) for p in sampled):
            raise SlabError("A abertura precisa ficar inteiramente dentro do contorno da laje.")
        # Hole boundary must not touch/cross outer boundary.
        for a,b in zip(sampled,sampled[1:]+sampled[:1]):
            for c,d in zip(outer,outer[1:]+outer[:1]):
                if _segments_intersect(a,b,c,d,tol=1e-8):
                    raise SlabError("A abertura não pode tocar ou cruzar a borda da laje.")
        for old in result:
            op=[_xy(v) for v in old["polygon"]]; os=sample_boundary(op,old.get("edges"))
            if any(_point_in_polygon_xy(p,os) for p in sampled) or any(_point_in_polygon_xy(p,sampled) for p in os):
                raise SlabError("Duas aberturas da laje não podem se sobrepor.")
            for a,b in zip(sampled,sampled[1:]+sampled[:1]):
                for c,d in zip(os,os[1:]+os[:1]):
                    if _segments_intersect(a,b,c,d,tol=1e-8):
                        raise SlabError("Duas aberturas da laje não podem se cruzar.")
        result.append(item)
    return result


def _opening_samples(openings):
    holes=[]
    for item in openings:
        pts=[_xy(v) for v in item["polygon"]]
        holes.append(sample_boundary(pts,item.get("edges")))
    return holes


def _record(values, local_polygon, edge_specs=None, openings=None):
    p=validate(values); pts=validate_polygon(local_polygon); specs=normalize_edge_specs(edge_specs,len(pts))
    ops=validate_openings(pts,specs, openings if openings is not None else p.get("openings",[]))
    return {
        "schema": SCHEMA, "kind": "slab",
        "polygon": [[v.x(),v.y(),0.0] for v in pts], "edges": copy.deepcopy(specs),
        "thickness": p["thickness"], "reference_plane": p["reference_plane"],
        "base_level": p.get("base_level"), "base_offset": p.get("base_offset",0.0),
        "base_z": p.get("base_z",0.0), "material_name": p.get("material_name"),
        "structure": p.get("structure","simple"), "layers": clone_layers(p.get("layers",[])),
        "openings": copy.deepcopy(ops),
    }


def actual_bottom(values):
    return validate(values)["base_z"]


def build_body(values, local_polygon, edge_specs=None, previous=None, *, openings=None, z0=0.0, z1=None, body_name="Corpo da laje"):
    p=validate(values); logical=validate_polygon(local_polygon); specs=normalize_edge_specs(edge_specs,len(logical))
    poly=validate_edge_geometry(logical,specs)
    ops=validate_openings(logical,specs, openings if openings is not None else p.get("openings",[])); holes=_opening_samples(ops)
    if polygon_area(poly)<0: poly=list(reversed(poly))
    # hole orientation is made opposite to the outer ring for top; opposite again on bottom.
    holes=[list(reversed(h)) if polygon_area(h)>0 else list(h) for h in holes]
    if z1 is None:z1=float(p["thickness"])
    bottom=[QVector3D(v.x(),v.y(),z0) for v in poly]; top=[QVector3D(v.x(),v.y(),z1) for v in poly]
    hb=[[QVector3D(v.x(),v.y(),z0) for v in h] for h in holes]; ht=[[QVector3D(v.x(),v.y(),z1) for v in h] for h in holes]
    mesh=Mesh(); old_attrs={}; old_default=None
    if previous is not None:
        for face in previous.mesh.faces:
            attrs=copy.deepcopy(face.attrs); key=attrs.get(FACE_KEY)
            if key is not None:old_attrs.setdefault(key,attrs)
            if old_default is None:old_default=copy.deepcopy(attrs)
    f=mesh.add_face(list(reversed(bottom)),hole_loops=[list(reversed(h)) for h in hb]);f.attrs.update(old_attrs.get("bottom",old_default or {}));f.attrs[FACE_KEY]="bottom"
    f=mesh.add_face(top,hole_loops=ht);f.attrs.update(old_attrs.get("top",old_default or {}));f.attrs[FACE_KEY]="top"
    n=len(poly)
    for i in range(n):
        j=(i+1)%n;f=mesh.add_face([bottom[i],bottom[j],top[j],top[i]]);f.attrs.update(old_attrs.get("side",old_default or {}));f.attrs[FACE_KEY]="side"
    for hole_b,hole_t in zip(hb,ht):
        n=len(hole_b)
        for i in range(n):
            j=(i+1)%n;f=mesh.add_face([hole_b[i],hole_t[i],hole_t[j],hole_b[j]]);f.attrs.update(old_attrs.get("opening",old_default or {}));f.attrs[FACE_KEY]="opening"
    body=Group(mesh,name=body_name);body.component=False
    if previous is not None:body.material=copy.deepcopy(previous.material);body.layer=previous.layer
    return body


def build_children(values, local_polygon, edge_specs=None, previous_children=None, *, openings=None):
    p=validate(values); previous_children=list(previous_children or []); children=[]
    if p.get("structure")!="composite":
        previous=previous_children[0] if previous_children else None
        return [build_body(p,local_polygon,edge_specs,previous=previous,openings=openings,body_name="Corpo da laje")]
    z=0.0
    for i,layer in enumerate(p.get("layers",[])):
        z1=z+float(layer["thickness"]); name=f"Camada laje · {layer.get('name','Camada')}"
        previous=next((c for c in previous_children if getattr(c,"name","")==name), previous_children[i] if i<len(previous_children) else None)
        children.append(build_body(p,local_polygon,edge_specs,previous=previous,openings=openings,z0=z,z1=z1,body_name=name));z=z1
    return children


def make_slab(world_polygon, values, template=None, edge_specs=None, openings=None):
    p=validate(values);pts=validate_polygon(world_polygon);specs=normalize_edge_specs(edge_specs,len(pts));validate_edge_geometry(pts,specs)
    origin=QVector3D(pts[0].x(),pts[0].y(),0.0);local=[QVector3D(v.x()-origin.x(),v.y()-origin.y(),0.0) for v in pts]
    # Incoming opening coordinates are world XY; persist them slab-local.
    raw_ops=openings if openings is not None else p.get("openings",[]); local_ops=[]
    for item in normalize_openings(raw_ops):
        q=copy.deepcopy(item);q["polygon"]=[[v[0]-origin.x(),v[1]-origin.y(),0.0] for v in item["polygon"]];local_ops.append(q)
    validate_openings(local,specs,local_ops)
    previous_children=list(getattr(template,"children",None) or []) if template is not None else []
    parent=Group(name=getattr(template,"name",None) or "Laje");parent.adopt(build_children(p,local,specs,previous_children,openings=local_ops));parent.component=False
    parent.xform.translate(origin.x(),origin.y(),actual_bottom(p));parent.ext={KEY:_record(p,local,specs,local_ops)}
    if template is not None:
        parent.layer=getattr(template,"layer",None);parent.material=copy.deepcopy(getattr(template,"material",None));parent.ifc=copy.deepcopy(getattr(template,"ifc",None))
    if parent.ifc is None:parent.ifc={"class":"IfcSlab","name":parent.name}
    return parent


def slab_polygon_local(group):
    rec=slab_record(group)
    if rec is None or rec.get("schema") not in (1,2,SCHEMA):
        raise SlabError("Versão dos parâmetros da laje não reconhecida.")
    raw=rec.get("polygon")
    if not isinstance(raw,list): raise SlabError("Polígono da laje inválido.")
    return validate_polygon([_xy(v) for v in raw])


def slab_edge_specs(group):
    rec=slab_record(group)
    if rec is None or rec.get("schema") not in (1,2,SCHEMA):
        raise SlabError("Versão dos parâmetros da laje não reconhecida.")
    pts=slab_polygon_local(group)
    return normalize_edge_specs(rec.get("edges"),len(pts))


def slab_openings_local(group):
    rec=slab_record(group)
    if rec is None:return []
    return normalize_openings(rec.get("openings",[]))


def slab_openings_world(group, reference=True):
    z=_world_z(group,reference); out=[]
    for item in slab_openings_local(group):
        q=copy.deepcopy(item); pts=[]
        for raw in item["polygon"]:
            w=group.xform.map(_xy(raw));pts.append([w.x(),w.y(),z])
        q["polygon"]=pts;out.append(q)
    return out


def _world_z(group, reference):
    values=read_slab(group)
    return (values["base_z"] + (values["thickness"] if values["reference_plane"]=="top" else 0.0)) if reference else values["base_z"]


def slab_polygon_world(group, reference=True):
    pts=slab_polygon_local(group); z=_world_z(group,reference); out=[]
    for p in pts:
        w=group.xform.map(QVector3D(p.x(),p.y(),0.0)); out.append(QVector3D(w.x(),w.y(),z))
    return out


def slab_path_world(group, reference=True, *, with_map=False):
    logical=slab_polygon_local(group); specs=slab_edge_specs(group)
    sampled,mapping=sample_boundary(logical,specs,with_map=True); z=_world_z(group,reference); out=[]
    for p in sampled:
        w=group.xform.map(QVector3D(p.x(),p.y(),0.0)); out.append(QVector3D(w.x(),w.y(),z))
    return (out,mapping) if with_map else out


def read_slab(group):
    rec=slab_record(group)
    if rec is None or rec.get("schema") not in (1,2,SCHEMA):
        raise SlabError("Versão dos parâmetros da laje não reconhecida.")
    p=validate({"thickness":rec.get("thickness"),"reference_plane":rec.get("reference_plane","bottom"),"base_level":rec.get("base_level"),"base_offset":rec.get("base_offset",0.0),"base_z":rec.get("base_z",rec.get("reference_z",0.0)),"material_name":rec.get("material_name"),"structure":rec.get("structure","simple"),"layers":rec.get("layers",[]),"openings":rec.get("openings",[])})
    expected=len(p.get("layers",[])) if p.get("structure")=="composite" else 1
    if len(getattr(group,"children",())) != expected:
        raise SlabError("A estrutura da laje foi alterada. Desfaça para continuar editando.")
    slab_polygon_local(group);slab_edge_specs(group);validate_openings(slab_polygon_local(group),slab_edge_specs(group),slab_openings_local(group))
    return p


def rebuild_slab(group, values=None, world_polygon=None, edge_specs=None, openings=None):
    old=read_slab(group);p=validate(dict(old,**(values or {})))
    pts=slab_polygon_world(group,reference=True) if world_polygon is None else validate_polygon(world_polygon)
    specs=slab_edge_specs(group) if edge_specs is None else normalize_edge_specs(edge_specs,len(pts))
    ops=slab_openings_world(group,reference=True) if openings is None else openings
    return make_slab(pts,p,template=group,edge_specs=specs,openings=ops)


def rectangle_diagonal(a,b):
    a,b=QVector3D(a),QVector3D(b)
    if abs(b.x()-a.x())<MIN_DIM or abs(b.y()-a.y())<MIN_DIM:
        raise SlabError("A diagonal precisa definir largura e comprimento maiores que 1 mm.")
    return [QVector3D(a.x(),a.y(),a.z()),QVector3D(b.x(),a.y(),a.z()),QVector3D(b.x(),b.y(),a.z()),QVector3D(a.x(),b.y(),a.z())]


def rectangle_base_width(a,b,c):
    a,b,c=QVector3D(a),QVector3D(b),QVector3D(c); d=b-a; d.setZ(0); length=math.hypot(d.x(),d.y())
    if length<MIN_DIM: raise SlabError("A base do retângulo precisa ter ao menos 1 mm.")
    u=QVector3D(d.x()/length,d.y()/length,0.0); n=QVector3D(-u.y(),u.x(),0.0); width=QVector3D.dotProduct(c-b,n)
    if abs(width)<MIN_DIM: raise SlabError("A largura do retângulo precisa ter ao menos 1 mm.")
    offset=n*width; return [a,b,b+offset,a+offset]

# ---- Exact circular-edge helpers used by edit/offset tools -----------------

def arc_geometry(start, end, sagitta):
    """Return ``(center, radius, start_angle, sweep)`` for one slab arc."""
    a = QVector3D(start.x(), start.y(), 0.0); b = QVector3D(end.x(), end.y(), 0.0)
    chord = b - a; length = math.hypot(chord.x(), chord.y()); h = float(sagitta)
    if length < MIN_DIM or abs(h) < ARC_EPS:
        return None
    u = QVector3D(chord.x()/length, chord.y()/length, 0.0)
    n = QVector3D(-u.y(), u.x(), 0.0); mid = (a+b)*0.5; apex = mid+n*h
    raw = _circumcenter2((a.x(),a.y()),(apex.x(),apex.y()),(b.x(),b.y()))
    if raw is None:
        return None
    c = QVector3D(raw[0],raw[1],0.0); r = _distance_xy(a,c)
    a0=math.atan2(a.y()-c.y(),a.x()-c.x()); a1=math.atan2(b.y()-c.y(),b.x()-c.x()); am=math.atan2(apex.y()-c.y(),apex.x()-c.x())
    sweep=_wrap_angle(a1-a0); through=_wrap_angle(am-a0)
    if sweep>=0 and not (0<=through<=sweep): sweep-=2*math.pi
    elif sweep<0 and not (sweep<=through<=0): sweep+=2*math.pi
    return c,r,a0,sweep


def _directed_sweep(a0, a1, sign, major=False):
    # For a fixed orientation there is exactly one sweep in (-2π,2π): CCW
    # or CW.  A previously-major arc naturally remains major after a small
    # concentric offset because the endpoint angular order is preserved.
    if sign >= 0:
        d=(a1-a0)%(2*math.pi)
        return d if d>1e-12 else 2*math.pi
    d=-((a0-a1)%(2*math.pi))
    return d if abs(d)>1e-12 else -2*math.pi


def _sagitta_from_center_sweep(start, end, center, sweep):
    a=QVector3D(start); b=QVector3D(end); c=QVector3D(center)
    r=_distance_xy(a,c); a0=math.atan2(a.y()-c.y(),a.x()-c.x())
    am=a0+sweep*0.5; apex=QVector3D(c.x()+r*math.cos(am),c.y()+r*math.sin(am),0.0)
    chord=b-a; L=math.hypot(chord.x(),chord.y())
    if L<MIN_DIM:return 0.0
    n=QVector3D(-chord.y()/L,chord.x()/L,0.0); mid=(a+b)*0.5
    return QVector3D.dotProduct(apex-mid,n)


def split_arc_edge(start, end, sagitta, point):
    """Split one logical circular edge at the nearest point on its true arc.

    Returns ``(split_point, spec_a, spec_b, fraction)``.  Both new specs remain
    exact arcs on the same original circle rather than becoming sampled lines.
    """
    geom=arc_geometry(start,end,sagitta)
    if geom is None:
        raise SlabError("A aresta curva não pôde ser interpretada.")
    c,r,a0,sweep=geom; p=QVector3D(point.x(),point.y(),0.0)
    ang=math.atan2(p.y()-c.y(),p.x()-c.x())
    if sweep>0:
        delta=(ang-a0)%(2*math.pi)
    else:
        delta=-((a0-ang)%(2*math.pi))
    t=max(0.0,min(1.0,delta/sweep if abs(sweep)>1e-12 else 0.0))
    if t <= 1e-4 or t >= 1-1e-4:
        raise SlabError("Insira o vértice afastado das extremidades da aresta.")
    am=a0+sweep*t; q=QVector3D(c.x()+r*math.cos(am),c.y()+r*math.sin(am),start.z())
    s1=_sagitta_from_center_sweep(start,q,c,sweep*t)
    s2=_sagitta_from_center_sweep(q,end,c,sweep*(1-t))
    return q,{"type":"arc","sagitta":float(s1)},{"type":"arc","sagitta":float(s2)},t



def edge_length(start, end, spec):
    """Exact XY length of one logical slab edge."""
    a=QVector3D(start); b=QVector3D(end)
    if not isinstance(spec,dict) or spec.get("type")!="arc":
        return _distance_xy(a,b)
    geom=arc_geometry(a,b,spec.get("sagitta",0.0))
    if geom is None:return _distance_xy(a,b)
    _c,r,_a0,sweep=geom
    return abs(sweep)*r


def edge_point(start, end, spec, fraction):
    """Point at a 0..1 fraction along a logical line/circular edge."""
    a=QVector3D(start); b=QVector3D(end); t=max(0.0,min(1.0,float(fraction)))
    if not isinstance(spec,dict) or spec.get("type")!="arc":
        return a+(b-a)*t
    geom=arc_geometry(a,b,spec.get("sagitta",0.0))
    if geom is None:return a+(b-a)*t
    c,r,a0,sweep=geom; ang=a0+sweep*t
    return QVector3D(c.x()+r*math.cos(ang),c.y()+r*math.sin(ang),a.z()+(b.z()-a.z())*t)


def edge_tangent(start, end, spec, fraction=0.0):
    """Unit tangent following the logical edge traversal."""
    a=QVector3D(start); b=QVector3D(end); t=max(0.0,min(1.0,float(fraction)))
    if not isinstance(spec,dict) or spec.get("type")!="arc":
        d=b-a; d.setZ(0); L=math.hypot(d.x(),d.y())
        if L<MIN_DIM:raise SlabError("Aresta curta demais.")
        return QVector3D(d.x()/L,d.y()/L,0.0)
    geom=arc_geometry(a,b,spec.get("sagitta",0.0))
    if geom is None:return edge_tangent(a,b,line_edge(),t)
    _c,_r,a0,sweep=geom; ang=a0+sweep*t; sign=1.0 if sweep>=0 else -1.0
    return QVector3D(-math.sin(ang)*sign,math.cos(ang)*sign,0.0)


def edge_fraction(start, end, spec, point):
    """Fraction of *point* projected onto a logical edge's underlying primitive."""
    a=QVector3D(start); b=QVector3D(end); p=QVector3D(point)
    if not isinstance(spec,dict) or spec.get("type")!="arc":
        d=b-a; d.setZ(0); den=d.x()*d.x()+d.y()*d.y()
        return 0.0 if den<1e-12 else ((p.x()-a.x())*d.x()+(p.y()-a.y())*d.y())/den
    geom=arc_geometry(a,b,spec.get("sagitta",0.0))
    if geom is None:return edge_fraction(a,b,line_edge(),p)
    c,_r,a0,sweep=geom; ang=math.atan2(p.y()-c.y(),p.x()-c.x())
    delta=(ang-a0)%(2*math.pi) if sweep>0 else -((a0-ang)%(2*math.pi))
    return delta/sweep if abs(sweep)>1e-12 else 0.0


def trim_edge_spec(start, end, spec, t0, t1):
    """Spec for the sub-edge between fractions *t0* and *t1*."""
    if not isinstance(spec,dict) or spec.get("type")!="arc":return line_edge()
    geom=arc_geometry(start,end,spec.get("sagitta",0.0))
    if geom is None:return line_edge()
    c,_r,a0,sweep=geom; ns=edge_point(start,end,spec,t0); ne=edge_point(start,end,spec,t1)
    sub=sweep*(float(t1)-float(t0)); h=_sagitta_from_center_sweep(ns,ne,c,sub)
    return line_edge() if abs(h)<ARC_EPS else {"type":"arc","sagitta":float(h)}


def _fillet_offset_primitive(start,end,spec,radius,ccw,side=1.0,fraction=0.5):
    """Locus of fillet centres at *radius* from one logical edge.

    ``side=+1`` uses the polygon-interior side of the edge and ``side=-1``
    the exterior side.  Concave corners need the latter; using the interior
    side unconditionally is why some perfectly valid curve/line fillets used
    to report that no tangent solution existed.
    """
    a=QVector3D(start); b=QVector3D(end); R=float(radius); t=max(0.0,min(1.0,float(fraction)))
    tangent=edge_tangent(a,b,spec,t)
    interior=QVector3D(-tangent.y(),tangent.x(),0.0) if ccw else QVector3D(tangent.y(),-tangent.x(),0.0)
    normal=interior*float(side)
    if not isinstance(spec,dict) or spec.get("type")!="arc":
        q=edge_point(a,b,line_edge(),t)
        return {"type":"line","p":q+normal*R,"d":tangent}
    geom=arc_geometry(a,b,spec.get("sagitta",0.0))
    if geom is None:return _fillet_offset_primitive(a,b,line_edge(),R,ccw,side,t)
    c,r,_a0,_sweep=geom; q=edge_point(a,b,spec,t); radial=q-c; L=math.hypot(radial.x(),radial.y())
    if L<1e-12:return None
    radial=QVector3D(radial.x()/L,radial.y()/L,0.0)
    nr=r+R*QVector3D.dotProduct(normal,radial)
    if nr<=MIN_DIM:return None
    return {"type":"arc","c":c,"r":nr}


def _primitive_intersections(a,b):
    if a is None or b is None:return []
    if a["type"]=="line" and b["type"]=="line":return _line_intersection_inf(a["p"],a["d"],b["p"],b["d"])
    if a["type"]=="line" and b["type"]=="arc":return _line_circle_intersections(a["p"],a["d"],b["c"],b["r"])
    if a["type"]=="arc" and b["type"]=="line":return _line_circle_intersections(b["p"],b["d"],a["c"],a["r"])
    return _circle_circle_intersections(a["c"],a["r"],b["c"],b["r"])


def _tangent_point_to_edge(center,start,end,spec):
    c0=QVector3D(center); a=QVector3D(start); b=QVector3D(end)
    if not isinstance(spec,dict) or spec.get("type")!="arc":
        u=edge_tangent(a,b,line_edge(),0.0); return a+u*QVector3D.dotProduct(c0-a,u)
    geom=arc_geometry(a,b,spec.get("sagitta",0.0))
    if geom is None:return _tangent_point_to_edge(c0,a,b,line_edge())
    c,r,_a0,_sw=geom; v=c0-c; L=math.hypot(v.x(),v.y())
    if L<1e-10:return None
    return c+QVector3D(v.x()/L,v.y()/L,0.0)*r


def solve_corner_fillet(points, specs, index, requested_radius):
    """Return an exact tangent fillet for line/arc neighbours at one vertex.

    The returned dict contains trim fractions/points and a fillet edge spec.
    Radius is clamped only when a tangency would pass an adjacent vertex.
    """
    pts=validate_polygon(points); sp=normalize_edge_specs(specs,len(pts)); n=len(pts); i=index%n; pi=(i-1)%n
    prev_a,vertex,next_b=pts[pi],pts[i],pts[(i+1)%n]
    prev_spec,next_spec=sp[pi],sp[i]
    ccw=polygon_area(sample_boundary(pts,sp))>0
    # A convex corner is rounded toward the polygon interior; a concave one
    # needs the centre on the exterior side.  Work from the true local
    # tangents, so line/arc and arc/arc transitions behave the same way.
    tprev_v=edge_tangent(prev_a,vertex,prev_spec,1.0)
    tnext_v=edge_tangent(vertex,next_b,next_spec,0.0)
    turn=tprev_v.x()*tnext_v.y()-tprev_v.y()*tnext_v.x()
    orient=1.0 if ccw else -1.0
    side=1.0 if turn*orient>=-1e-10 else -1.0

    def solve(R):
        if R<MIN_DIM:return None
        p0=_fillet_offset_primitive(prev_a,vertex,prev_spec,R,ccw,side,1.0)
        p1=_fillet_offset_primitive(vertex,next_b,next_spec,R,ccw,side,0.0)
        cands=_primitive_intersections(p0,p1); best=None
        for center in cands:
            tprev_pt=_tangent_point_to_edge(center,prev_a,vertex,prev_spec)
            tnext_pt=_tangent_point_to_edge(center,vertex,next_b,next_spec)
            if tprev_pt is None or tnext_pt is None:continue
            fp=edge_fraction(prev_a,vertex,prev_spec,tprev_pt); fn=edge_fraction(vertex,next_b,next_spec,tnext_pt)
            if fp < -1e-6 or fp > 1+1e-6 or fn < -1e-6 or fn > 1+1e-6:continue
            # Tangency must lie on the portions immediately adjacent to the vertex.
            lp=edge_length(prev_a,vertex,prev_spec); ln=edge_length(vertex,next_b,next_spec)
            dp=max(0.0,(1.0-fp)*lp); dn=max(0.0,fn*ln)
            if dp>lp-MIN_DIM+1e-7 or dn>ln-MIN_DIM+1e-7:continue
            score=_distance_xy(center,vertex)
            if best is None or score<best[0]:best=(score,center,tprev_pt,tnext_pt,fp,fn)
        return best

    requested=max(MIN_DIM,float(requested_radius)); sol=solve(requested)
    if sol is None:
        # Find the largest radius not crossing the next logical vertices.
        lo=MIN_DIM; hi=requested; good=solve(lo)
        if good is None:raise SlabError("Não foi possível criar um fillet tangente neste vértice.")
        for _ in range(36):
            mid=(lo+hi)*0.5; cur=solve(mid)
            if cur is None:hi=mid
            else:lo=mid;good=cur
        sol=good;requested=lo
    _score,center,p1,p2,fp,fn=sol
    # Pick the circular traversal whose endpoint tangents best continue the two
    # neighbouring logical edges.  This is more reliable than assuming the
    # polygon orientation, especially at concave line/arc corners.
    a1=math.atan2(p1.y()-center.y(),p1.x()-center.x()); a2=math.atan2(p2.y()-center.y(),p2.x()-center.x())
    prev_t=edge_tangent(prev_a,vertex,prev_spec,fp); next_t=edge_tangent(vertex,next_b,next_spec,fn)
    choices=[]
    for sign in (1,-1):
        sw=_directed_sweep(a1,a2,sign)
        if abs(sw)>math.pi: sw=sw-(2*math.pi if sw>0 else -2*math.pi)
        ts=QVector3D(-math.sin(a1),math.cos(a1),0.0)*sign
        te=QVector3D(-math.sin(a2),math.cos(a2),0.0)*sign
        score=QVector3D.dotProduct(ts,prev_t)+QVector3D.dotProduct(te,next_t)-0.02*abs(sw)
        choices.append((score,sw))
    sweep=max(choices,key=lambda it:it[0])[1]
    h=_sagitta_from_center_sweep(p1,p2,center,sweep)
    return {"p1":QVector3D(p1),"p2":QVector3D(p2),"prev_fraction":float(fp),"next_fraction":float(fn),
            "spec":line_edge() if abs(h)<ARC_EPS else {"type":"arc","sagitta":float(h)},"radius":requested}

def _line_intersection_inf(a, d, b, e):
    den=d.x()*e.y()-d.y()*e.x()
    if abs(den)<1e-10:return []
    q=b-a; t=(q.x()*e.y()-q.y()*e.x())/den
    return [a+d*t]


def _line_circle_intersections(a,d,c,r):
    # |a + t d - c|^2 = r^2 ; d is normalized but formula is generic.
    fx=a.x()-c.x(); fy=a.y()-c.y(); A=d.x()*d.x()+d.y()*d.y()
    B=2*(fx*d.x()+fy*d.y()); C=fx*fx+fy*fy-r*r; disc=B*B-4*A*C
    if disc < -1e-9:return []
    disc=max(0.0,disc); root=math.sqrt(disc); out=[]
    for t in ((-B-root)/(2*A),(-B+root)/(2*A)):
        p=a+d*t
        if not out or _distance_xy(out[0],p)>1e-8:out.append(p)
    return out


def _circle_circle_intersections(c0,r0,c1,r1):
    d=_distance_xy(c0,c1)
    if d<1e-10 or d>r0+r1+1e-9 or d<abs(r0-r1)-1e-9:return []
    a=(r0*r0-r1*r1+d*d)/(2*d); h2=max(0.0,r0*r0-a*a); h=math.sqrt(h2)
    ux=(c1.x()-c0.x())/d; uy=(c1.y()-c0.y())/d; x=c0.x()+a*ux; y=c0.y()+a*uy
    p0=QVector3D(x-h*uy,y+h*ux,0.0);p1=QVector3D(x+h*uy,y-h*ux,0.0)
    return [p0] if _distance_xy(p0,p1)<1e-8 else [p0,p1]


def _offset_edge_geometries(points, specs, distance):
    # Orientation is based on the true sampled boundary so a large curved bulge
    # does not fool the inside/outside classification.
    area=polygon_area(sample_boundary(points,specs)); ccw=area>0
    edges=[]; npts=len(points)
    for i,a in enumerate(points):
        b=points[(i+1)%npts]; spec=specs[i]
        if spec.get("type")!="arc":
            d=b-a;L=math.hypot(d.x(),d.y())
            if L<MIN_DIM:raise SlabError("Aresta curta demais para offset.")
            u=QVector3D(d.x()/L,d.y()/L,0.0)
            outward=QVector3D(u.y(),-u.x(),0.0) if ccw else QVector3D(-u.y(),u.x(),0.0)
            edges.append({"type":"line","p":QVector3D(a)+outward*distance,"d":u,"outward":outward,"distance":distance})
        else:
            geom=arc_geometry(a,b,spec.get("sagitta",0.0))
            if geom is None:raise SlabError("Aresta curva inválida para offset.")
            c,r,a0,sweep=geom; am=a0+sweep*0.5
            radial=QVector3D(math.cos(am),math.sin(am),0.0)
            tangent=QVector3D(-math.sin(am),math.cos(am),0.0)*(1.0 if sweep>0 else -1.0)
            outward=QVector3D(tangent.y(),-tangent.x(),0.0) if ccw else QVector3D(-tangent.y(),tangent.x(),0.0)
            dr=distance*QVector3D.dotProduct(outward,radial); nr=r+dr
            if nr<MIN_DIM:raise SlabError("Este offset colapsa uma das arestas curvas.")
            edges.append({"type":"arc","c":c,"r":nr,"sign":1 if sweep>0 else -1,"major":abs(sweep)>math.pi,"orig_sweep":sweep,"outward":outward,"distance":distance})
    return edges



def _offset_point_at_vertex(edge_geom, vertex):
    """Point on an offset primitive corresponding to one original vertex."""
    v=QVector3D(vertex)
    if edge_geom["type"]=="line":
        return v+edge_geom["outward"]*edge_geom.get("distance",0.0)
    c=edge_geom["c"]; vec=v-c; L=math.hypot(vec.x(),vec.y())
    if L<1e-12:raise SlabError("Offset inválido junto a uma aresta curva.")
    return c+QVector3D(vec.x()/L,vec.y()/L,0.0)*edge_geom["r"]

def _edge_intersections(e0,e1):
    if e0["type"]=="line" and e1["type"]=="line":return _line_intersection_inf(e0["p"],e0["d"],e1["p"],e1["d"])
    if e0["type"]=="line" and e1["type"]=="arc":return _line_circle_intersections(e0["p"],e0["d"],e1["c"],e1["r"])
    if e0["type"]=="arc" and e1["type"]=="line":return _line_circle_intersections(e1["p"],e1["d"],e0["c"],e0["r"])
    return _circle_circle_intersections(e0["c"],e0["r"],e1["c"],e1["r"])


def offset_boundary(points, edge_specs, distance):
    """Offset the whole mixed line/arc slab reference contour.

    Positive distance is outward, negative inward. Circular edges remain
    circular and concentric; straight edges remain straight. For outward
    offsets, a corner whose neighbouring offset primitives no longer meet is
    closed with an exact round join centred on the original vertex instead of
    failing. Inward offsets still fail when the contour genuinely collapses or
    self-intersects.
    """
    logical=validate_polygon(points);specs=normalize_edge_specs(edge_specs,len(logical));dist=float(distance)
    if abs(dist)<1e-9:return [QVector3D(p) for p in logical],[dict(s) for s in specs]
    geoms=_offset_edge_geometries(logical,specs,dist);n=len(logical);ccw=polygon_area(sample_boundary(logical,specs))>0
    corners=[]
    for i in range(n):
        prev=geoms[(i-1)%n];cur=geoms[i]
        # Expected constant-distance endpoints at this logical vertex.  They are
        # a better locality reference than the original vertex when arcs are
        # involved (line/circle math often has a second, remote intersection).
        pprev=_offset_point_at_vertex(prev,logical[i]);pcur=_offset_point_at_vertex(cur,logical[i])
        cands=_edge_intersections(prev,cur)
        q=min(cands,key=lambda p:_distance_xy(p,pprev)+_distance_xy(p,pcur)) if cands else None
        prev_len=edge_length(logical[(i-1)%n],logical[i],specs[(i-1)%n])
        cur_len=edge_length(logical[i],logical[(i+1)%n],specs[i])
        # Accept a true local meeting; reject the remote branch that creates the
        # occasional giant spike seen in mixed line/arc offsets.
        local_limit=max(0.05,abs(dist)*30.0,0.75*min(prev_len,cur_len))
        if q is not None and (_distance_xy(q,pprev)+_distance_xy(q,pcur))<=2.0*local_limit:
            corners.append({"kind":"miter","prev":QVector3D(q),"cur":QVector3D(q)})
            continue
        # Missing local intersections are not automatically a collapse.  An
        # outward convex corner *and* an inward concave corner need the same
        # constant-distance circular join.  Genuine inward collapse is caught
        # later by radius/self-intersection validation.
        corners.append({"kind":"round","prev":pprev,"cur":pcur,"center":QVector3D(logical[i])})

    def edge_spec_for_geom(g,a,b):
        if g["type"]=="line":return line_edge()
        aa=math.atan2(a.y()-g["c"].y(),a.x()-g["c"].x());bb=math.atan2(b.y()-g["c"].y(),b.x()-g["c"].x())
        sw=_directed_sweep(aa,bb,g["sign"],g.get("major",False));h=_sagitta_from_center_sweep(a,b,g["c"],sw)
        return line_edge() if abs(h)<ARC_EPS else {"type":"arc","sagitta":float(h)}

    segments=[]
    for i,g in enumerate(geoms):
        a=QVector3D(corners[i]["cur"]);b=QVector3D(corners[(i+1)%n]["prev"])
        if _distance_xy(a,b)>=MIN_DIM:
            segments.append((a,b,edge_spec_for_geom(g,a,b)))
        nxt=corners[(i+1)%n]
        if nxt["kind"]=="round":
            ja=QVector3D(nxt["prev"]);jb=QVector3D(nxt["cur"]);center=nxt["center"]
            if _distance_xy(ja,jb)>=MIN_DIM:
                a0=math.atan2(ja.y()-center.y(),ja.x()-center.x());a1=math.atan2(jb.y()-center.y(),jb.x()-center.x())
                join_sign=(1 if ccw else -1) * (1 if dist>0 else -1)
                sw=_directed_sweep(a0,a1,join_sign)
                # A local constant-distance join should not loop around the whole corner.
                if abs(sw)>math.pi:sw=sw-(2*math.pi if sw>0 else -2*math.pi)
                h=_sagitta_from_center_sweep(ja,jb,center,sw)
                segments.append((ja,jb,line_edge() if abs(h)<ARC_EPS else {"type":"arc","sagitta":float(h)}))
    if len(segments)<3:raise SlabError("O offset não gerou um contorno válido.")
    new=[QVector3D(a) for a,_b,_sp in segments];new_specs=[dict(sp) for _a,_b,sp in segments]
    validate_polygon(new);validate_edge_geometry(new,new_specs)
    return new,new_specs


def edge_outward_normal(points, edge_specs, index, anchor=None):
    """Outward XY unit normal of a logical edge, evaluated near *anchor*."""
    pts=validate_polygon(points);specs=normalize_edge_specs(edge_specs,len(pts));i=index%len(pts);a=pts[i];b=pts[(i+1)%len(pts)]
    ccw=polygon_area(sample_boundary(pts,specs))>0
    spec=specs[i]
    if spec.get("type")!="arc":
        d=b-a;L=math.hypot(d.x(),d.y());u=QVector3D(d.x()/L,d.y()/L,0.0)
    else:
        geom=arc_geometry(a,b,spec.get("sagitta",0.0))
        if geom is None:raise SlabError("Aresta curva inválida para offset.")
        c,r,a0,sweep=geom;p=QVector3D(anchor) if anchor is not None else (a+b)*0.5;ang=math.atan2(p.y()-c.y(),p.x()-c.x());u=QVector3D(-math.sin(ang),math.cos(ang),0.0)*(1 if sweep>0 else -1)
    return (QVector3D(u.y(),-u.x(),0.0) if ccw else QVector3D(-u.y(),u.x(),0.0)).normalized()

# Local XY distance helper kept at module level so the exact-arc utilities above
# stay independent from the interactive editing module.
def _distance_xy(a, b):
    return math.hypot(a.x()-b.x(), a.y()-b.y())
