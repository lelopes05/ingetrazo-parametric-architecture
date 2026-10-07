# SPDX-License-Identifier: GPL-3.0-or-later
"""IFC4 exporter for OpenTrace BIM.

The exporter is intentionally independent from Bonsai internals.  It mirrors
openBIM patterns used there (types, layer sets, spatial containment, property
sets) while keeping OpenTrace as the authority for geometry.  Geometry export is profile-driven. OpenTrace Fidelity uses IFC4 polygonal face
sets; compatibility profiles use faceted BRep and native swept solids where the
parametric record maps cleanly. Curved/sloped/custom elements always retain the
actual OpenTrace body instead of being flattened to a generic straight wall.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import math
from pathlib import Path

from . import __version__
from .bim import (deterministic_ifc_guid, ensure_spatial_ids, ifc_identity_data,
                  element_kind, is_bim_group, load_document_data, new_ifc_guid, record_for)
from .layers import function_category, wall_overall_offsets


class IfcExportError(RuntimeError):
    pass


EXPORT_PROFILES = {
    "opentrace": {"label": "OpenTrace / fidelidade IFC4", "geometry": "tessellation", "native_slabs": False, "native_walls": True, "native_profiles": False, "opening_relations": True},
    "bonsai": {"label": "Bonsai / Blender", "geometry": "brep", "native_slabs": True, "native_walls": True, "native_profiles": True, "opening_relations": False},
    "archicad": {"label": "Archicad", "geometry": "brep", "native_slabs": True, "native_walls": True, "native_profiles": True, "opening_relations": False},
    "revit": {"label": "Revit", "geometry": "brep", "native_slabs": True, "native_walls": True, "native_profiles": True, "opening_relations": False},
}

def export_profile(name):
    key=str(name or "opentrace").lower()
    return key, EXPORT_PROFILES.get(key, EXPORT_PROFILES["opentrace"])


def _s(value):
    if value is None:
        return "$"
    text = str(value).replace("'", "''").replace("\\", "\\\\")
    return "'" + text + "'"


def _enum(value, fallback="NOTDEFINED"):
    raw = str(value or fallback).upper().replace(" ", "_")
    clean = "".join(c for c in raw if c.isalnum() or c == "_") or fallback
    return f".{clean}."


def _real(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    if not math.isfinite(v):
        v = 0.0
    text = f"{v:.12g}"
    if "e" not in text.lower() and "." not in text:
        text += "."
    return text.upper()


def _typed(value, measure_type=None):
    if value is None:
        return "$"
    mt = str(measure_type or "").strip()
    if isinstance(value, bool):
        return f"IFCBOOLEAN({'.T.' if value else '.F.'})"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"IFCINTEGER({value})"
    if isinstance(value, float):
        if mt.startswith("Ifc") and mt.endswith("Measure"):
            return f"{mt.upper()}({_real(value)})"
        return f"IFCREAL({_real(value)})"
    text = str(value)
    if mt in ("IfcText", "IfcLabel", "IfcIdentifier", "IfcURIReference"):
        return f"{mt.upper()}({_s(text)})"
    return f"{'IFCTEXT' if len(text) > 240 else 'IFCLABEL'}({_s(text)})"


def _list(values):
    return "(" + ",".join(str(v) for v in values) + ")"


class _Step:
    def __init__(self, view_definition="ReferenceView_V1.2"):
        self.rows = []
        self.view_definition = str(view_definition or "ReferenceView_V1.2")

    def add(self, entity, args):
        idx = len(self.rows) + 1
        self.rows.append(f"#{idx}={entity.upper()}({args});")
        return f"#{idx}"

    def render(self, filename, author="", organization=""):
        stamp = _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
        name = Path(filename).name
        header = [
            "ISO-10303-21;",
            "HEADER;",
            f"FILE_DESCRIPTION(('ViewDefinition [{self.view_definition}]'),'2;1');",
            f"FILE_NAME({_s(name)},{_s(stamp)},({_s(author)}),({_s(organization)}),"
            f"{_s('OpenTrace BIM ' + __version__)},{_s('OpenTrace BIM')},'');",
            "FILE_SCHEMA(('IFC4'));",
            "ENDSEC;",
            "DATA;",
        ]
        return "\n".join(header + self.rows + ["ENDSEC;", "END-ISO-10303-21;", ""])


def _xyz(point):
    try:
        return float(point.x()), float(point.y()), float(point.z())
    except Exception:
        try:
            return float(point[0]), float(point[1]), float(point[2])
        except Exception as exc:
            raise IfcExportError("Vértice 3D inválido durante a exportação IFC.") from exc


def _map_point(group, child, point):
    p = point
    cx = getattr(child, "xform", None)
    if cx is not None:
        p = cx.map(p)
    gx = getattr(group, "xform", None)
    if gx is not None:
        p = gx.map(p)
    return _xyz(p)


def _mesh_polygonal_face_set(step, group, child):
    mesh = getattr(child, "mesh", None)
    faces = list(getattr(mesh, "faces", ()) or ())
    if not faces:
        return None

    coords = []
    index = {}

    def vertex_index(vertex):
        p = _map_point(group, child, vertex.position)
        key = tuple(round(v, 9) for v in p)
        if key not in index:
            index[key] = len(coords) + 1
            coords.append(p)
        return index[key]

    face_defs = []
    for face in faces:
        outer = [vertex_index(v) for v in list(getattr(face, "loop", ()) or ())]
        if len(outer) < 3:
            continue
        holes = []
        for raw in list(getattr(face, "hole_loops", ()) or ()):
            loop = [vertex_index(v) for v in list(raw or ())]
            if len(loop) >= 3:
                holes.append(loop)
        if holes:
            face_defs.append(("voids", outer, holes))
        else:
            face_defs.append(("plain", outer, ()))
    if not face_defs:
        return None

    point_rows = ["(" + ",".join(_real(v) for v in p) + ")" for p in coords]
    point_list = step.add("IfcCartesianPointList3D", f"{_list(point_rows)}")
    face_refs = []
    for kind, outer, holes in face_defs:
        if kind == "voids":
            inner = _list([_list(loop) for loop in holes])
            face_refs.append(step.add("IfcIndexedPolygonalFaceWithVoids", f"{_list(outer)},{inner}"))
        else:
            face_refs.append(step.add("IfcIndexedPolygonalFace", _list(outer)))
    return step.add("IfcPolygonalFaceSet", f"{point_list},.T.,{_list(face_refs)},$")



def _mesh_faceted_brep(step, group, child):
    """Compatibility geometry using the broadly-supported IFC FacetedBrep."""
    mesh = getattr(child, "mesh", None)
    faces = list(getattr(mesh, "faces", ()) or ())
    if not faces:
        return None
    point_cache = {}
    def point_ref(vertex):
        xyz = tuple(round(v, 10) for v in _map_point(group, child, vertex.position))
        ref = point_cache.get(xyz)
        if ref is None:
            ref = step.add("IfcCartesianPoint", _list([_real(v) for v in xyz]))
            point_cache[xyz] = ref
        return ref
    face_refs=[]
    for face in faces:
        outer=[point_ref(v) for v in list(getattr(face,"loop",()) or ())]
        if len(outer)<3: continue
        holes=[[point_ref(v) for v in list(raw or ())] for raw in list(getattr(face,"hole_loops",()) or ())]
        holes=[h for h in holes if len(h)>=3]
        # Faces with holes are planar in OpenTrace (slab caps / profile caps),
        # so preserve their inner bounds. Other n-gons are triangulated to
        # guarantee planar IFC facets even on twisted/sloped wall sides.
        if holes:
            bounds=[]
            loop=step.add("IfcPolyLoop",_list(outer));bounds.append(step.add("IfcFaceOuterBound",f"{loop},.T."))
            for h in holes:
                hloop=step.add("IfcPolyLoop",_list(h));bounds.append(step.add("IfcFaceBound",f"{hloop},.T."))
            face_refs.append(step.add("IfcFace",_list(bounds)))
        elif len(outer)==3:
            loop=step.add("IfcPolyLoop",_list(outer));bound=step.add("IfcFaceOuterBound",f"{loop},.T.")
            face_refs.append(step.add("IfcFace",_list([bound])))
        else:
            for i in range(1,len(outer)-1):
                tri=[outer[0],outer[i],outer[i+1]]
                loop=step.add("IfcPolyLoop",_list(tri));bound=step.add("IfcFaceOuterBound",f"{loop},.T.")
                face_refs.append(step.add("IfcFace",_list([bound])))
    if not face_refs:return None
    shell=step.add("IfcClosedShell",_list(face_refs))
    return step.add("IfcFacetedBrep",shell)


def _polyline2(step, points):
    refs=[]
    for x,y in points:
        refs.append(step.add("IfcCartesianPoint",f"({_real(x)},{_real(y)})"))
    if refs and refs[0]!=refs[-1]:
        # Reuse the first point ref to explicitly close IfcPolyline.
        refs.append(refs[0])
    return step.add("IfcPolyline",_list(refs))


def _extruded_profile_solid(step, outer, holes, z0, depth, name="OpenTrace Profile"):
    if len(outer)<3 or float(depth)<=1e-9:return None
    outer_curve=_polyline2(step,outer)
    if holes:
        inners=[_polyline2(step,h) for h in holes if len(h)>=3]
        profile=step.add("IfcArbitraryProfileDefWithVoids",f".AREA.,{_s(name)},{outer_curve},{_list(inners)}")
    else:
        profile=step.add("IfcArbitraryClosedProfileDef",f".AREA.,{_s(name)},{outer_curve}")
    loc=step.add("IfcCartesianPoint",f"(0.,0.,{_real(z0)})")
    zdir=step.add("IfcDirection","(0.,0.,1.)");xdir=step.add("IfcDirection","(1.,0.,0.)")
    pos=step.add("IfcAxis2Placement3D",f"{loc},{zdir},{xdir}")
    edir=step.add("IfcDirection","(0.,0.,1.)")
    return step.add("IfcExtrudedAreaSolid",f"{profile},{pos},{edir},{_real(depth)}")


def _native_slab_solid(step, group, rec):
    try:
        from PySide6.QtGui import QVector3D
        from .slab_model import sample_boundary, normalize_openings
        raw=rec.get("polygon") or []
        logical=[QVector3D(float(p[0]),float(p[1]),0.0) for p in raw]
        sampled=sample_boundary(logical,rec.get("edges"))
        def world2(p):
            q=group.xform.map(QVector3D(p.x(),p.y(),0.0));return (float(q.x()),float(q.y()))
        outer=[world2(p) for p in sampled]
        holes=[]
        for op in normalize_openings(rec.get("openings",[])):
            pts=[QVector3D(float(p[0]),float(p[1]),0.0) for p in op.get("polygon",[])]
            holes.append([world2(p) for p in sample_boundary(pts,op.get("edges"))])
        zvals=[]
        for child in list(getattr(group,"children",()) or ()):
            for face in list(getattr(getattr(child,"mesh",None),"faces",()) or ()):
                for v in list(getattr(face,"loop",()) or ()):
                    zvals.append(_map_point(group,child,v.position)[2])
        if not zvals:return None
        return _extruded_profile_solid(step,outer,holes,min(zvals),max(zvals)-min(zvals),"Laje OpenTrace")
    except Exception:
        return None


def _native_wall_solid(step, group, rec):
    """Native swept solid for any constant-height, vertical OpenTrace wall.

    The profile is the *actual OpenTrace footprint*, so straight, curved and
    polyline walls can remain standard SweptSolid IFC walls when they do not
    require variable top/base, leaning, hosted openings or junction cap
    overrides.  Complex cases still fall back to the resolved OpenTrace BRep.
    """
    try:
        if rec.get("openings") or rec.get("caps"):
            return None
        bases=[float(v) for v in rec.get("base_profile",[0.0,0.0])]
        tops=[float(v) for v in rec.get("top_profile",[rec.get("height",0.0)]*2)]
        topxy=rec.get("top_xy",[[0.0,0.0],[0.0,0.0]])
        if len(bases)!=2 or len(tops)!=2:
            return None
        if abs(bases[0]-bases[1])>1e-8 or abs((tops[0]-bases[0])-(tops[1]-bases[1]))>1e-8:
            return None
        if any(abs(float(c))>1e-9 for pair in topxy for c in pair):
            return None
        height=tops[0]-bases[0]
        if height<=1e-9:
            return None
        from PySide6.QtGui import QVector3D
        from .model import path_points_from_record, footprint, wall_offsets
        path=path_points_from_record(rec)
        poly=footprint(path,float(rec.get("thickness") or 0.1),str(rec.get("alignment") or "left"),offsets=wall_offsets(rec))
        outer=[]
        zvals=[]
        for q in poly:
            w=group.xform.map(QVector3D(q.x(),q.y(),bases[0]))
            outer.append((float(w.x()),float(w.y())))
            zvals.append(float(w.z()))
        if len(outer)<3 or not zvals or max(zvals)-min(zvals)>1e-7:
            return None
        return _extruded_profile_solid(step,outer,[],sum(zvals)/len(zvals),height,"Parede OpenTrace")
    except Exception:
        return None


def _vsub(a,b): return (a[0]-b[0],a[1]-b[1],a[2]-b[2])
def _vadd(a,b): return (a[0]+b[0],a[1]+b[1],a[2]+b[2])
def _vscale(a,k): return (a[0]*k,a[1]*k,a[2]*k)
def _vdot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def _vcross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def _vlen(a): return math.sqrt(max(0.0,_vdot(a,a)))
def _vnorm(a):
    n=_vlen(a)
    return None if n<=1e-12 else (a[0]/n,a[1]/n,a[2]/n)


def _face_world_loops(group, child, face):
    outer=[_map_point(group,child,v.position) for v in list(getattr(face,"loop",()) or ())]
    holes=[[_map_point(group,child,v.position) for v in list(raw or ())] for raw in list(getattr(face,"hole_loops",()) or ())]
    return outer,[h for h in holes if len(h)>=3]


def _face_with_key(child, key):
    for face in list(getattr(getattr(child,"mesh",None),"faces",()) or ()):
        attrs=getattr(face,"attrs",None) or {}
        if attrs.get("ap_beam_face")==key or attrs.get("ap_column_face")==key:
            return face
    return None


def _same_translated_loop(start, end, delta, tol=2e-5):
    if len(start)!=len(end): return False
    remaining=list(end)
    for p in start:
        target=_vadd(p,delta)
        hit=None
        for i,q in enumerate(remaining):
            if _vlen(_vsub(q,target))<=tol:
                hit=i;break
        if hit is None:return False
        remaining.pop(hit)
    return True


def _native_linear_profile_solid(step, group, rec):
    """Recover a standard IfcExtrudedAreaSolid from an actual OpenTrace body.

    This recognises a true translated profile rather than assuming that every
    beam/column is straight.  Inclined beams and sheared inclined columns are
    supported; curved/tapered/multisegment bodies fail the translation test and
    retain their exact BRep representation.
    """
    kind=rec.get("kind")
    if kind not in ("beam","column"): return None
    children=list(getattr(group,"children",()) or ())
    if len(children)!=1:return None
    child=children[0]
    akey,bkey=("start","end") if kind=="beam" else ("bottom","top")
    fa,fb=_face_with_key(child,akey),_face_with_key(child,bkey)
    if fa is None or fb is None:return None
    outer,holes=_face_world_loops(group,child,fa)
    outer2,holes2=_face_world_loops(group,child,fb)
    if len(outer)<3 or len(outer)!=len(outer2) or len(holes)!=len(holes2):return None
    # Average paired centroids gives the translation even when cap winding is reversed.
    ca=tuple(sum(p[i] for p in outer)/len(outer) for i in range(3))
    cb=tuple(sum(p[i] for p in outer2)/len(outer2) for i in range(3))
    delta=_vsub(cb,ca);depth=_vlen(delta)
    if depth<=1e-8 or not _same_translated_loop(outer,outer2,delta):return None
    for h in holes:
        target=[q for hh in holes2 for q in hh]
        if not any(_same_translated_loop(h,hh,delta) for hh in holes2):return None
    # Stable plane basis from the start cap.  Extrusion direction is expressed
    # in that basis, so a column with horizontal section and inclined axis is
    # represented as a legitimate oblique extrusion rather than being rotated.
    origin=outer[0]
    x=None;normal=None
    for i in range(1,len(outer)):
        e=_vsub(outer[i],origin); en=_vnorm(e)
        if en is None:continue
        for j in range(i+1,len(outer)):
            e2=_vsub(outer[j],origin); n=_vnorm(_vcross(e,e2))
            if n is not None:
                x=en;normal=n;break
        if normal is not None:break
    if x is None or normal is None:return None
    y=_vnorm(_vcross(normal,x))
    if y is None:return None
    # Re-orthogonalise X in case the first edge carried tiny numeric noise.
    x=_vnorm(_vcross(y,normal)) or x
    def xy(p):
        d=_vsub(p,origin);return (_vdot(d,x),_vdot(d,y))
    outer2d=[xy(q) for q in outer]
    holes2d=[[xy(q) for q in h] for h in holes]
    curve=_polyline2(step,outer2d)
    if holes2d:
        inners=[_polyline2(step,h) for h in holes2d]
        prof=step.add("IfcArbitraryProfileDefWithVoids",f".AREA.,{_s('Perfil OpenTrace')},{curve},{_list(inners)}")
    else:
        prof=step.add("IfcArbitraryClosedProfileDef",f".AREA.,{_s('Perfil OpenTrace')},{curve}")
    loc=step.add("IfcCartesianPoint",_list([_real(v) for v in origin]))
    ndir=step.add("IfcDirection",_list([_real(v) for v in normal]))
    xdir=step.add("IfcDirection",_list([_real(v) for v in x]))
    pos=step.add("IfcAxis2Placement3D",f"{loc},{ndir},{xdir}")
    dnorm=_vnorm(delta)
    local_dir=(_vdot(dnorm,x),_vdot(dnorm,y),_vdot(dnorm,normal))
    edir=step.add("IfcDirection",_list([_real(v) for v in local_dir]))
    return step.add("IfcExtrudedAreaSolid",f"{prof},{pos},{edir},{_real(depth)}")


def _open_polyline2(step, points):
    refs=[step.add("IfcCartesianPoint",f"({_real(x)},{_real(y)})") for x,y in points]
    return step.add("IfcPolyline",_list(refs)) if len(refs)>=2 else None


def _open_polyline3(step, points):
    refs=[step.add("IfcCartesianPoint",_list([_real(v) for v in p])) for p in points]
    return step.add("IfcPolyline",_list(refs)) if len(refs)>=2 else None


def _reference_path_world(group, rec):
    try:
        kind=rec.get("kind")
        if kind=="wall":
            from .model import path_points_from_record
            return [_xyz(group.xform.map(q)) for q in path_points_from_record(rec)]
        if kind=="beam":
            from .beam_model import reference_path_world
            return [_xyz(q) for q in reference_path_world(group)]
        if kind=="column":
            from .column_model import reference_path_world
            return [_xyz(q) for q in reference_path_world(group)]
    except Exception:
        return []
    return []


def _axis_representation(step, contexts, group, rec):
    points=_reference_path_world(group,rec)
    if len(points)<2:return None
    if rec.get("kind")=="wall":
        item=_open_polyline2(step,[(p[0],p[1]) for p in points])
        return step.add("IfcShapeRepresentation",f"{contexts['plan_axis']},'Axis','Curve2D',{_list([item])}") if item else None
    if rec.get("kind") in ("beam","column"):
        item=_open_polyline3(step,points)
        return step.add("IfcShapeRepresentation",f"{contexts['model_axis']},'Axis','Curve3D',{_list([item])}") if item else None
    return None


def _component_prototype_key(group):
    try:
        if not group.is_component():return None
    except Exception:return None
    own=getattr(group,"mesh",None);children=list(getattr(group,"children",()) or ())
    return (id(own),tuple(id(getattr(c,"mesh",None)) for c in children))


def _mapping_target(step, group):
    """IfcCartesianTransformationOperator matching a true IngeTrazo component placement."""
    from PySide6.QtGui import QVector3D
    m=getattr(group,"xform",None)
    if m is None:return None
    o=m.map(QVector3D(0,0,0));vx=m.mapVector(QVector3D(1,0,0));vy=m.mapVector(QVector3D(0,1,0));vz=m.mapVector(QVector3D(0,0,1))
    sx,sy,sz=vx.length(),vy.length(),vz.length()
    if min(sx,sy,sz)<1e-12:return None
    x,y,z=vx/sx,vy/sy,vz/sz
    op=step.add("IfcCartesianPoint",f"({_real(o.x())},{_real(o.y())},{_real(o.z())})")
    xr=step.add("IfcDirection",f"({_real(x.x())},{_real(x.y())},{_real(x.z())})")
    yr=step.add("IfcDirection",f"({_real(y.x())},{_real(y.y())},{_real(y.z())})")
    zr=step.add("IfcDirection",f"({_real(z.x())},{_real(z.y())},{_real(z.z())})")
    if abs(sx-sy)<1e-9 and abs(sx-sz)<1e-9:
        return step.add("IfcCartesianTransformationOperator3D",f"{xr},{yr},{op},{_real(sx)},{zr}")
    return step.add("IfcCartesianTransformationOperator3DnonUniform",f"{xr},{yr},{op},{_real(sx)},{zr},{_real(sy)},{_real(sz)}")


def _component_representation_map(step,contexts,group,profile_name="opentrace"):
    """One local Body representation for a true shared component prototype."""
    profile_key,profile=export_profile(profile_name)
    local_group=type("_LocalPrototype",(),{})();local_group.xform=None
    children=list(getattr(group,"children",()) or ())
    if not children:
        local_child=type("_LocalChild",(),{})();local_child.mesh=getattr(group,"mesh",None);local_child.xform=None
        children=[local_child]
    items=[]
    for child in children:
        item=(_mesh_polygonal_face_set(step,local_group,child) if profile.get("geometry")=="tessellation"
              else _mesh_faceted_brep(step,local_group,child))
        if item:items.append(item)
    if not items:return None,None
    rep_type="Tessellation" if profile.get("geometry")=="tessellation" else "Brep"
    source=step.add("IfcShapeRepresentation",f"{contexts['body']},'Body',{_s(rep_type)},{_list(items)}")
    p=step.add("IfcCartesianPoint","(0.,0.,0.)");z=step.add("IfcDirection","(0.,0.,1.)");x=step.add("IfcDirection","(1.,0.,0.)")
    origin=step.add("IfcAxis2Placement3D",f"{p},{z},{x}")
    repmap=step.add("IfcRepresentationMap",f"{origin},{source}")
    return repmap,rep_type


def _mapped_shape(step,contexts,repmap,group):
    target=_mapping_target(step,group)
    if not target:return None
    item=step.add("IfcMappedItem",f"{repmap},{target}")
    rep=step.add("IfcShapeRepresentation",f"{contexts['body']},'Body','MappedRepresentation',{_list([item])}")
    return step.add("IfcProductDefinitionShape",f"$,$,{_list([rep])}")

def _shape_representation(step, contexts, group, rec=None, profile_name="opentrace"):
    key, profile=export_profile(profile_name)
    rec=rec or {}
    native=None
    if profile.get("native_slabs") and rec.get("kind")=="slab": native=_native_slab_solid(step,group,rec)
    elif profile.get("native_walls") and rec.get("kind")=="wall": native=_native_wall_solid(step,group,rec)
    elif profile.get("native_profiles") and rec.get("kind") in ("beam","column"): native=_native_linear_profile_solid(step,group,rec)
    reps=[]
    axis_rep=_axis_representation(step,contexts,group,rec)
    if axis_rep:reps.append(axis_rep)
    if native:
        reps.append(step.add("IfcShapeRepresentation",f"{contexts['body']},'Body','SweptSolid',{_list([native])}"))
        return step.add("IfcProductDefinitionShape",f"$,$,{_list(reps)}"),"SweptSolid"
    items=[]
    children=list(getattr(group,"children",()) or ())
    if children:
        for child in children:
            item=_mesh_polygonal_face_set(step,group,child) if profile.get("geometry")=="tessellation" else _mesh_faceted_brep(step,group,child)
            if item:items.append(item)
    elif getattr(group,"mesh",None) is not None:
        item=_mesh_polygonal_face_set(step,group,group) if profile.get("geometry")=="tessellation" else _mesh_faceted_brep(step,group,group)
        if item:items.append(item)
    if not items:return None,None
    rep_type="Tessellation" if profile.get("geometry")=="tessellation" else "Brep"
    reps.append(step.add("IfcShapeRepresentation",f"{contexts['body']},'Body',{_s(rep_type)},{_list(items)}"))
    return step.add("IfcProductDefinitionShape",f"$,$,{_list(reps)}"),rep_type

def _material_name(layer, fallback="Material OpenTrace"):
    if not isinstance(layer, dict):
        return fallback
    return str(layer.get("material_name") or layer.get("name") or fallback)


def _record_layers(rec):
    raw = rec.get("layers") if isinstance(rec, dict) else None
    return [copy.deepcopy(x) for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


def _element_z(group):
    xform = getattr(group, "xform", None)
    if xform is not None:
        try:
            return _xyz(xform.map(type("P", (), {})()))[2]
        except Exception:
            pass
        try:
            from PySide6.QtGui import QVector3D
            return float(xform.map(QVector3D(0, 0, 0)).z())
        except Exception:
            pass
    # Fallback to first mesh vertex.
    for child in list(getattr(group, "children", ()) or ()):
        faces = list(getattr(getattr(child, "mesh", None), "faces", ()) or ())
        if faces and getattr(faces[0], "loop", None):
            return _map_point(group, child, faces[0].loop[0].position)[2]
    return 0.0


def _storeys(app):
    try:
        from .levels import available_levels
        levels = available_levels(app)
    except Exception:
        levels = []
    if not levels:
        return [{"name": "Pavimento 0", "z": 0.0}]
    return levels


def _best_storey_name(group, rec, storeys):
    preferred = rec.get("base_level") if isinstance(rec, dict) else None
    if preferred and any(x["name"] == preferred for x in storeys):
        return preferred
    z = _element_z(group)
    below = [lv for lv in storeys if float(lv["z"]) <= z + 1e-6]
    if below:
        return max(below, key=lambda x: float(x["z"]))["name"]
    return min(storeys, key=lambda x: abs(float(x["z"]) - z))["name"]


def _type_entity_name(ifc_class):
    return {
        "IfcWall": "IfcWallType", "IfcSlab": "IfcSlabType", "IfcBeam": "IfcBeamType",
        "IfcColumn": "IfcColumnType", "IfcRoof": "IfcRoofType", "IfcDoor": "IfcDoorType",
        "IfcWindow": "IfcWindowType", "IfcStair": "IfcStairType", "IfcRamp": "IfcRampType",
        "IfcRailing": "IfcRailingType", "IfcSpace": "IfcSpaceType",
        "IfcBuildingElementProxy": "IfcBuildingElementProxyType",
    }.get(ifc_class)


def _make_type(step, ifc_class, type_name, predefined, global_id=None, representation_maps=None):
    entity = _type_entity_name(ifc_class)
    if not entity:
        return None
    gid = _s(global_id or new_ifc_guid())
    element_type = _s(type_name) if str(predefined).upper() == "USERDEFINED" else "$"
    repmaps=_list(list(representation_maps)) if representation_maps else "$"
    common = f"{gid},$,{_s(type_name)},$,$,$,{repmaps},$,{element_type}"
    if ifc_class == "IfcDoor":
        return step.add(entity, common + f",{_enum(predefined)},.NOTDEFINED.,.F.,$")
    if ifc_class == "IfcWindow":
        return step.add(entity, common + f",{_enum(predefined)},.NOTDEFINED.,.F.,$")
    return step.add(entity, common + f",{_enum(predefined)}")


def _make_product(step, ifc_class, gid, name, object_type, placement, shape, predefined, meta=None):
    """Create common architectural IFC products with schema-correct tails."""
    meta = meta or {}
    base = f"{_s(gid)},$,{_s(name)},$,{object_type},{placement},{shape}"
    if ifc_class == "IfcSpace":
        long_name = _s(meta.get("long_name") or name)
        return step.add("IfcSpace", base + f",{long_name},.ELEMENT.,{_enum(predefined)},$")
    if ifc_class == "IfcDoor":
        h = _real(meta.get("overall_height", 0.0)) if meta.get("overall_height") else "$"
        w = _real(meta.get("overall_width", 0.0)) if meta.get("overall_width") else "$"
        op = _enum(meta.get("operation_type", "NOTDEFINED"))
        return step.add("IfcDoor", base + f",$,{h},{w},{_enum(predefined)},{op},$")
    if ifc_class == "IfcWindow":
        h = _real(meta.get("overall_height", 0.0)) if meta.get("overall_height") else "$"
        w = _real(meta.get("overall_width", 0.0)) if meta.get("overall_width") else "$"
        part = _enum(meta.get("partitioning_type", "NOTDEFINED"))
        return step.add("IfcWindow", base + f",$,{h},{w},{_enum(predefined)},{part},$")
    # IfcBuildingElement / IfcElement-derived classes used here share Tag + PredefinedType.
    return step.add(ifc_class, base + f",$,{_enum(predefined)}")


def _parametric_payload(group, rec):
    """JSON-safe OpenTrace state for lossless OpenTrace→IFC→OpenTrace round-trip."""
    payload = {"record": copy.deepcopy(rec or {})}
    m = getattr(group, "xform", None)
    if m is not None:
        try:
            payload["xform"] = [[float(m(r, c)) for c in range(4)] for r in range(4)]
        except Exception:
            pass
    return payload


def _add_named_property_set(step, product_ref, pset_name, properties):
    prop_refs = []
    try:
        from .ifc_catalog import property_template
    except Exception:
        property_template = lambda _a, _b: {}
    for name, value in (properties or {}).items():
        if value is None or value == "":
            continue
        tmpl = property_template(str(pset_name), str(name)) or {}
        measure = tmpl.get("primary_measure_type")
        prop_refs.append(step.add("IfcPropertySingleValue", f"{_s(name)},$,{_typed(value, measure)},$"))
    if not prop_refs:
        return None
    pset = step.add("IfcPropertySet", f"{_s(new_ifc_guid())},$,{_s(pset_name)},$,{_list(prop_refs)}")
    step.add("IfcRelDefinesByProperties", f"{_s(new_ifc_guid())},$,$,$,{_list([product_ref])},{pset}")
    return pset


def _add_property_set(step, product_ref, properties):
    return _add_named_property_set(step, product_ref, "Pset_OpenTraceParametric", properties)


def _style_values(style):
    if not isinstance(style, dict): return None
    raw = style.get("color") or style.get("rgb")
    if not isinstance(raw, (list, tuple)) or len(raw) < 3: return None
    try:
        rgb = [max(0.0, min(1.0, float(x))) for x in raw[:3]]
        transparency = max(0.0, min(1.0, float(style.get("transparency", 1.0-float(style.get("opacity", 1.0))))))
    except Exception:
        return None
    return rgb, transparency


def _add_material_style(step, material_ref, style, contexts, cache, name="Material OpenTrace"):
    vals = _style_values(style)
    if not vals or not contexts: return None
    rgb, transparency = vals
    sig = (round(rgb[0],5), round(rgb[1],5), round(rgb[2],5), round(transparency,5))
    style_ref = cache.get(("surface_style", sig))
    if style_ref is None:
        colour = step.add("IfcColourRgb", f"$,{_real(rgb[0])},{_real(rgb[1])},{_real(rgb[2])}")
        shading = step.add("IfcSurfaceStyleShading", f"{colour},{_real(transparency)}")
        style_ref = step.add("IfcSurfaceStyle", f"{_s(name)},.BOTH.,{_list([shading])}")
        cache[("surface_style", sig)] = style_ref
    styled = step.add("IfcStyledItem", f"$,{_list([style_ref])},$")
    rep = step.add("IfcStyledRepresentation", f"{contexts['model']},'Style','Style',{_list([styled])}")
    return step.add("IfcMaterialDefinitionRepresentation", f"$,$,{_list([rep])},{material_ref}")


def _material(step, name, cache, *, category=None, style=None, contexts=None):
    key = ("material", str(name))
    mat = cache.get(key)
    if mat is None:
        mat = step.add("IfcMaterial", f"{_s(name)},$,{_s(category) if category else '$'}")
        cache[key] = mat
        if style:
            _add_material_style(step, mat, style, contexts, cache, str(name))
    return mat


def _add_material(step, product_ref, type_ref, ifc_class, rec, cache, *, meta=None,
                  contexts=None, occurrence_layer_usage=True):
    meta = meta or {}
    layers = _record_layers(rec)
    if not layers and isinstance(meta.get("material_layers"), list):
        layers=[]
        for item in meta.get("material_layers") or ():
            if not isinstance(item,dict):continue
            q=copy.deepcopy(item)
            if "material_name" not in q and q.get("material"):q["material_name"]=q.get("material")
            layers.append(q)
    structure = "composite" if layers else rec.get("structure", "simple")
    if structure == "composite" and layers:
        signature = tuple((str(x.get("material_name") or x.get("name") or ""),
                           round(float(x.get("thickness", 0.0)), 9),
                           function_category(x.get("function"))) for x in layers)
        key = ("layerset", signature)
        layer_set = cache.get(key)
        if layer_set is None:
            layer_refs = []
            for layer in layers:
                lname = _material_name(layer)
                style = layer.get("style") if isinstance(layer, dict) else None
                mat = _material(step, lname, cache, category=function_category(layer.get("function")),
                                style=style, contexts=contexts)
                layer_refs.append(step.add(
                    "IfcMaterialLayer",
                    f"{mat},{_real(layer.get('thickness', 0.0))},$,{_s(layer.get('name') or lname)},$,{_s(function_category(layer.get('function')))},$",
                ))
            layer_set = step.add("IfcMaterialLayerSet", f"{_list(layer_refs)},{_s(rec.get('type_name') or meta.get('type_name') or 'Composição OpenTrace')},$")
            cache[key] = layer_set
        if type_ref:
            step.add("IfcRelAssociatesMaterial", f"{_s(new_ifc_guid())},$,$,$,{_list([type_ref])},{layer_set}")
        direction = "AXIS3" if ifc_class in ("IfcSlab", "IfcRoof") else "AXIS2"
        offset = 0.0
        if ifc_class == "IfcWall":
            try: offset = wall_overall_offsets(layers, rec.get("alignment", "left"))[0]
            except Exception: offset = 0.0
        if occurrence_layer_usage:
            usage = step.add("IfcMaterialLayerSetUsage", f"{layer_set},.{direction}.,.POSITIVE.,{_real(offset)},$")
            step.add("IfcRelAssociatesMaterial", f"{_s(new_ifc_guid())},$,$,$,{_list([product_ref])},{usage}")
        return

    # Constituents model materially distinct parts that are not ordered layers
    # (e.g. frame + glass, membrane skin + cable, composite assemblies).
    constituents = meta.get("material_constituents")
    if isinstance(constituents, list) and constituents:
        sig = tuple((str(x.get("name") or x.get("material") or ""), str(x.get("category") or ""))
                    for x in constituents if isinstance(x, dict))
        ckey = ("constituentset", sig)
        cset = cache.get(ckey)
        if cset is None:
            refs = []
            for item in constituents:
                if not isinstance(item, dict): continue
                mname = str(item.get("material") or item.get("name") or "Material")
                mat = _material(step, mname, cache, category=item.get("category"),
                                style=item.get("style"), contexts=contexts)
                refs.append(step.add("IfcMaterialConstituent",
                    f"{_s(item.get('name') or mname)},{_s(item.get('description'))},{mat},{_real(item.get('fraction',0.0)) if item.get('fraction') not in (None,'') else '$'},{_s(item.get('category'))}"))
            if refs:
                cset = step.add("IfcMaterialConstituentSet", f"{_s(meta.get('type_name') or 'Constituintes OpenTrace')},$,{_list(refs)}")
                cache[ckey] = cset
        if cset:
            targets = [product_ref] + ([type_ref] if type_ref else [])
            step.add("IfcRelAssociatesMaterial", f"{_s(new_ifc_guid())},$,$,$,{_list(targets)},{cset}")
            return

    material_name = str(rec.get("material_name") or meta.get("material_name") or "").strip()
    if material_name and ifc_class in ("IfcBeam", "IfcColumn", "IfcMember") and type_ref and str(rec.get("section_type") or "simple") == "simple":
        profile_kind = str(rec.get("profile") or "rect")
        try:
            if profile_kind == "circle":
                diameter = float(rec.get("diameter") or 0.0)
                signature = ("circle", round(diameter, 9), material_name)
                profile_args = f".AREA.,{_s(rec.get('type_name') or meta.get('type_name') or 'Perfil OpenTrace')},$,{_real(diameter / 2.0)}"
                profile_entity = "IfcCircleProfileDef"
            else:
                width = float(rec.get("width") or 0.0)
                height = float((rec.get("depth") if ifc_class == "IfcColumn" else rec.get("height", rec.get("depth"))) or 0.0)
                signature = ("rect", round(width, 9), round(height, 9), material_name)
                profile_args = f".AREA.,{_s(rec.get('type_name') or meta.get('type_name') or 'Perfil OpenTrace')},$,{_real(width)},{_real(height)}"
                profile_entity = "IfcRectangleProfileDef"
        except (TypeError, ValueError): signature = None
        if signature and all(float(v) > 0 for v in signature[1:-1] if isinstance(v, (int, float))):
            key = ("profileset", signature)
            profile_set = cache.get(key)
            if profile_set is None:
                mat = _material(step, material_name, cache, style=meta.get("material_style"), contexts=contexts)
                profile_def = step.add(profile_entity, profile_args)
                material_profile = step.add("IfcMaterialProfile", f"{_s(rec.get('type_name') or meta.get('type_name') or 'Perfil OpenTrace')},$,{mat},{profile_def},$,$")
                profile_set = step.add("IfcMaterialProfileSet", f"{_s(rec.get('type_name') or meta.get('type_name') or 'Perfil OpenTrace')},$,{_list([material_profile])},$")
                cache[key] = profile_set
            step.add("IfcRelAssociatesMaterial", f"{_s(new_ifc_guid())},$,$,$,{_list([type_ref])},{profile_set}")
            # Occurrence usage is the IFC-native way to say that this member
            # actually uses the profile set assigned to its type.
            usage = step.add("IfcMaterialProfileSetUsage", f"{profile_set},$,$")
            step.add("IfcRelAssociatesMaterial", f"{_s(new_ifc_guid())},$,$,$,{_list([product_ref])},{usage}")
            return

    if material_name:
        mat = _material(step, material_name, cache, style=meta.get("material_style"), contexts=contexts)
        targets = [product_ref] + ([type_ref] if type_ref else [])
        step.add("IfcRelAssociatesMaterial", f"{_s(new_ifc_guid())},$,$,$,{_list(targets)},{mat}")


def _arc_length(chord, sagitta):
    chord = abs(float(chord or 0.0)); h = abs(float(sagitta or 0.0))
    if chord <= 1.0e-12 or h <= 1.0e-12:
        return chord
    radius = chord * chord / (8.0 * h) + h / 2.0
    theta = 4.0 * math.atan2(2.0 * h, chord)
    return abs(radius * theta)


def _xy(raw):
    try:
        return float(raw[0]), float(raw[1])
    except Exception:
        return None


def _wall_length(rec):
    path = rec.get("path") if isinstance(rec, dict) else None
    if not isinstance(path, dict):
        return None
    kind = path.get("type")
    if kind in ("line", "arc"):
        a, b = _xy(path.get("start")), _xy(path.get("end"))
        if a is None or b is None:
            return None
        chord = math.hypot(b[0] - a[0], b[1] - a[1])
        return _arc_length(chord, path.get("sagitta", 0.0)) if kind == "arc" else chord
    if kind == "polyline":
        pts = [_xy(x) for x in (path.get("points") or [])]
        if len(pts) < 2 or any(x is None for x in pts):
            return None
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    return None


def _constant_wall_height(rec):
    bases = rec.get("base_profile") if isinstance(rec, dict) else None
    tops = rec.get("top_profile") if isinstance(rec, dict) else None
    if isinstance(bases, list) and isinstance(tops, list) and bases and len(bases) == len(tops):
        try:
            heights = [float(t) - float(b) for b, t in zip(bases, tops)]
        except (TypeError, ValueError):
            heights = []
        if heights and max(heights) - min(heights) <= 1.0e-7:
            return sum(heights) / len(heights)
        return None
    try:
        return float(rec.get("height"))
    except (TypeError, ValueError):
        return None


def _sample_arc2(a, b, sagitta, max_step_deg=7.5):
    ax, ay = a; bx, by = b; h = float(sagitta or 0.0)
    dx, dy = bx - ax, by - ay; chord = math.hypot(dx, dy)
    if chord <= 1.0e-12 or abs(h) <= 1.0e-10:
        return [a, b]
    ux, uy = dx / chord, dy / chord
    nx, ny = -uy, ux
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    px, py = mx + nx * h, my + ny * h
    d = 2.0 * (ax * (py - by) + px * (by - ay) + bx * (ay - py))
    if abs(d) <= 1.0e-14:
        return [a, b]
    aa = ax * ax + ay * ay; pp = px * px + py * py; bb = bx * bx + by * by
    cx = (aa * (py - by) + pp * (by - ay) + bb * (ay - py)) / d
    cy = (aa * (bx - px) + pp * (ax - bx) + bb * (px - ax)) / d
    radius = math.hypot(ax - cx, ay - cy)
    a0 = math.atan2(ay - cy, ax - cx); a1 = math.atan2(by - cy, bx - cx); am = math.atan2(py - cy, px - cx)
    def wrap(v):
        while v <= -math.pi: v += 2.0 * math.pi
        while v > math.pi: v -= 2.0 * math.pi
        return v
    sweep = wrap(a1 - a0); through = wrap(am - a0)
    if sweep >= 0.0 and not (0.0 <= through <= sweep): sweep -= 2.0 * math.pi
    elif sweep < 0.0 and not (sweep <= through <= 0.0): sweep += 2.0 * math.pi
    spans = max(2, int(math.ceil(abs(math.degrees(sweep)) / max_step_deg)))
    return [(cx + radius * math.cos(a0 + sweep * i / spans), cy + radius * math.sin(a0 + sweep * i / spans)) for i in range(spans + 1)]


def _slab_outline(rec):
    raw = rec.get("polygon") if isinstance(rec, dict) else None
    if not isinstance(raw, list) or len(raw) < 3:
        return []
    pts = [_xy(x) for x in raw]
    if any(x is None for x in pts):
        return []
    specs = rec.get("edges") if isinstance(rec.get("edges"), list) else []
    out = []
    for i, (a, b) in enumerate(zip(pts, pts[1:] + pts[:1])):
        spec = specs[i] if i < len(specs) and isinstance(specs[i], dict) else {}
        seg = _sample_arc2(a, b, spec.get("sagitta", 0.0)) if spec.get("type") == "arc" else [a, b]
        if out and seg:
            seg = seg[1:]
        out.extend(seg)
    return out


def _polygon_area_perimeter(points):
    if len(points) < 3:
        return None, None
    area = 0.5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])))
    perim = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:] + points[:1]))
    return area, perim


def _simple_section(rec):
    if str(rec.get("section_type") or "simple") != "simple":
        return None
    profile = str(rec.get("profile") or "rect")
    try:
        if profile == "circle":
            d = float(rec.get("diameter") or 0.0)
            return (math.pi * d * d / 4.0, math.pi * d) if d > 0 else None
        w = float(rec.get("width") or 0.0); h = float((rec.get("depth") if rec.get("kind") == "column" else rec.get("height", rec.get("depth"))) or 0.0)
        return (w * h, 2.0 * (w + h)) if w > 0 and h > 0 else None
    except (TypeError, ValueError):
        return None


def _column_length(rec):
    try:
        height = float(rec.get("height") or 0.0)
    except (TypeError, ValueError):
        return None
    if height <= 0:
        return None
    stations = rec.get("stations") if isinstance(rec.get("stations"), list) else None
    if not stations or len(stations) < 2:
        angle = math.radians(float(rec.get("inclination") or 0.0))
        chord = height / max(math.cos(angle), 1.0e-9)
        return _arc_length(chord, rec.get("curvature", 0.0))
    total = 0.0
    for a, b in zip(stations, stations[1:]):
        try:
            dz = height * (float(b.get("t")) - float(a.get("t")))
            angle = math.radians(float(a.get("inclination", rec.get("inclination", 0.0)) or 0.0))
            chord = dz / max(math.cos(angle), 1.0e-9)
            total += _arc_length(chord, a.get("curvature", 0.0))
        except (TypeError, ValueError):
            return None
    return total


def _constant_column_section(rec):
    stations = rec.get("stations") if isinstance(rec.get("stations"), list) else []
    if stations:
        keys = ("diameter",) if str(rec.get("profile") or "rect") == "circle" else ("width", "depth")
        try:
            first = tuple(round(float(stations[0].get(k) or 0.0), 9) for k in keys)
            if any(tuple(round(float(st.get(k) or 0.0), 9) for k in keys) != first for st in stations[1:]):
                return None
        except (TypeError, ValueError):
            return None
    return _simple_section(rec)


def _quantity_values(ifc_class, rec):
    q = {}
    if ifc_class == "IfcWall":
        length = _wall_length(rec); height = _constant_wall_height(rec)
        try: width = float(rec.get("thickness") or 0.0)
        except (TypeError, ValueError): width = 0.0
        if length and length > 0: q["Length"] = ("length", length)
        if width > 0: q["Width"] = ("length", width)
        if height and height > 0: q["Height"] = ("length", height)
        if length and width > 0: q["GrossFootprintArea"] = ("area", length * width)
        if length and height and height > 0: q["GrossSideArea"] = ("area", length * height)
        if length and height and width > 0 and height > 0: q["GrossVolume"] = ("volume", length * height * width)
    elif ifc_class == "IfcSlab":
        outline = _slab_outline(rec); area, perim = _polygon_area_perimeter(outline)
        try: thickness = float(rec.get("thickness") or 0.0)
        except (TypeError, ValueError): thickness = 0.0
        if thickness > 0: q["Width"] = ("length", thickness)
        if area and area > 0: q["GrossArea"] = ("area", area)
        if perim and perim > 0: q["Perimeter"] = ("length", perim)
        if area and thickness > 0: q["GrossVolume"] = ("volume", area * thickness)
    elif ifc_class == "IfcBeam":
        try: length = float(rec.get("length") or 0.0)
        except (TypeError, ValueError): length = 0.0
        section = _simple_section(rec)
        if length > 0: q["Length"] = ("length", length)
        if section:
            area, perimeter = section; q["CrossSectionArea"] = ("area", area)
            if length > 0:
                q["OuterSurfaceArea"] = ("area", perimeter * length)
                q["GrossVolume"] = ("volume", area * length)
    elif ifc_class == "IfcColumn":
        length = _column_length(rec); section = _constant_column_section(rec)
        if length and length > 0: q["Length"] = ("length", length)
        if section:
            area, perimeter = section; q["CrossSectionArea"] = ("area", area)
            if length and length > 0:
                q["OuterSurfaceArea"] = ("area", perimeter * length)
                q["GrossVolume"] = ("volume", area * length)
    return q


_QUANTITY_SET = {
    "IfcWall": "Qto_WallBaseQuantities", "IfcSlab": "Qto_SlabBaseQuantities",
    "IfcBeam": "Qto_BeamBaseQuantities", "IfcColumn": "Qto_ColumnBaseQuantities",
    "IfcRoof": "Qto_RoofBaseQuantities", "IfcSpace": "Qto_SpaceBaseQuantities",
    "IfcDoor": "Qto_DoorBaseQuantities", "IfcWindow": "Qto_WindowBaseQuantities",
    "IfcStair": "Qto_StairBaseQuantities", "IfcRamp": "Qto_RampBaseQuantities",
    "IfcRailing": "Qto_RailingBaseQuantities",
}


def _add_quantities(step, product_ref, ifc_class, rec):
    values = _quantity_values(ifc_class, rec)
    if not values:
        return None
    refs = []
    entity = {"length": "IfcQuantityLength", "area": "IfcQuantityArea", "volume": "IfcQuantityVolume"}
    for name, (kind, value) in values.items():
        refs.append(step.add(entity[kind], f"{_s(name)},$,$,{_real(value)},$"))
    qset = step.add("IfcElementQuantity", f"{_s(new_ifc_guid())},$,{_s(_QUANTITY_SET.get(ifc_class, 'BaseQuantities'))},$,{_s('OpenTrace parametric nominal')},{_list(refs)}")
    step.add("IfcRelDefinesByProperties", f"{_s(new_ifc_guid())},$,$,$,{_list([product_ref])},{qset}")
    return qset


def _add_preserved_quantities(step, product_ref, quantities):
    """Re-emit imported/custom Qto dictionaries without throwing data away."""
    if not isinstance(quantities, dict): return 0
    count = 0
    for qname, values in quantities.items():
        if not isinstance(values, dict): continue
        refs = []
        for name, value in values.items():
            if name in ("id", "Name") or value is None: continue
            try: fv = float(value)
            except Exception: continue
            lname = str(name).lower()
            if "volume" in lname: ent = "IfcQuantityVolume"
            elif "area" in lname: ent = "IfcQuantityArea"
            elif any(x in lname for x in ("count", "number")): ent = "IfcQuantityCount"
            else: ent = "IfcQuantityLength"
            refs.append(step.add(ent, f"{_s(name)},$,$,{_real(fv)},$"))
        if refs:
            qset = step.add("IfcElementQuantity", f"{_s(new_ifc_guid())},$,{_s(qname)},$,$,{_list(refs)}")
            step.add("IfcRelDefinesByProperties", f"{_s(new_ifc_guid())},$,$,$,{_list([product_ref])},{qset}")
            count += 1
    return count


def _classification_entries(meta):
    out = []
    raw = meta.get("classifications") if isinstance(meta, dict) else None
    if isinstance(raw, list):
        out.extend(x for x in raw if isinstance(x, dict) and x.get("system") and x.get("code"))
    system = str(meta.get("classification_system") or "").strip() if isinstance(meta, dict) else ""
    code = str(meta.get("classification_code") or "").strip() if isinstance(meta, dict) else ""
    if system and code and not any(x.get("system")==system and x.get("code")==code for x in out):
        out.append({"system":system,"code":code})
    return out

def _add_classification(step, project_ref, product_ref, meta, cache):
    made = []
    for item in _classification_entries(meta):
        system = str(item.get("system") or "").strip(); code = str(item.get("code") or "").strip()
        if not system or not code: continue
        classification = cache.get(("system", system))
        if classification is None:
            classification = step.add("IfcClassification", f"{_s(item.get('source'))},$,$,{_s(system)},{_s(item.get('description'))},{_s(item.get('location'))}")
            step.add("IfcRelAssociatesClassification", f"{_s(new_ifc_guid())},$,$,$,{_list([project_ref])},{classification}")
            cache[("system", system)] = classification
        reference = cache.get(("reference", system, code))
        if reference is None:
            reference = step.add("IfcClassificationReference", f"{_s(item.get('location'))},{_s(code)},{_s(item.get('name') or code)},{classification},{_s(item.get('description'))},$")
            cache[("reference", system, code)] = reference
        step.add("IfcRelAssociatesClassification", f"{_s(new_ifc_guid())},$,$,$,{_list([product_ref])},{reference}")
        made.append(reference)
    return made


def _opening_properties(rec, item, index):
    out = {
        "Engine": "OpenTrace.Opening",
        "HostKind": rec.get("kind"),
        "Index": index + 1,
    }
    for key in ("width", "height", "sill", "station", "side", "id"):
        if key in item:
            out[key[:1].upper() + key[1:]] = item.get(key)
    return out


def _add_opening_relations(step, host_ref, rec, storey_ref, placement_ref, context,
                           include_psets=True, *, type_cache=None, project_gid=""):
    raw = rec.get("openings") if isinstance(rec, dict) else None
    if not isinstance(raw, list): return {"openings": [], "fills": []}
    out, fills = [], []
    for i, item in enumerate(raw):
        if not isinstance(item, dict): continue
        name = str(item.get("name") or f"Abertura {i + 1}")
        opening_gid = str(item.get("ifc_global_id") or new_ifc_guid())
        opening = step.add("IfcOpeningElement", f"{_s(opening_gid)},$,{_s(name)},$,$,{placement_ref},$,$,.OPENING.")
        step.add("IfcRelVoidsElement", f"{_s(new_ifc_guid())},$,$,$,{host_ref},{opening}")
        if storey_ref:
            step.add("IfcRelContainedInSpatialStructure", f"{_s(new_ifc_guid())},$,$,$,{_list([opening])},{storey_ref}")
        if include_psets: _add_property_set(step, opening, _opening_properties(rec, item, i))
        out.append(opening)

        fill = item.get("fill")
        if not isinstance(fill, dict):
            # Backwards-compatible shorthand accepted by future door/window tools.
            cls = item.get("fill_class") or item.get("ifc_fill_class")
            fill = {"class": cls} if cls else None
        if isinstance(fill, dict) and str(fill.get("class") or "") in ("IfcDoor", "IfcWindow"):
            cls = str(fill.get("class")); fgid = str(fill.get("global_id") or new_ifc_guid())
            fname = str(fill.get("name") or ("Porta" if cls == "IfcDoor" else "Janela"))
            fmeta = dict(fill)
            fmeta.setdefault("overall_width", item.get("width")); fmeta.setdefault("overall_height", item.get("height"))
            fpre = str(fill.get("predefined_type") or ("DOOR" if cls == "IfcDoor" else "WINDOW"))
            product = _make_product(step, cls, fgid, fname, "$", placement_ref, "$", fpre, fmeta)
            step.add("IfcRelFillsElement", f"{_s(new_ifc_guid())},$,$,$,{opening},{product}")
            if storey_ref:
                step.add("IfcRelContainedInSpatialStructure", f"{_s(new_ifc_guid())},$,$,$,{_list([product])},{storey_ref}")
            if include_psets and isinstance(fill.get("property_sets"), dict):
                for pn, pv in fill["property_sets"].items(): _add_named_property_set(step, product, pn, pv)
            if type_cache is not None:
                tname = str(fill.get("type_name") or fname)
                tkey = (cls, tname, fpre)
                tref = type_cache.get(tkey)
                if tkey not in type_cache:
                    tref = _make_type(step, cls, tname, fpre,
                        deterministic_ifc_guid(project_gid or "OpenTrace", f"type|{cls}|{tname}|{fpre}"))
                    type_cache[tkey] = tref
                if tref: step.add("IfcRelDefinesByType", f"{_s(new_ifc_guid())},$,$,$,{_list([product])},{tref}")
            fills.append((fgid, product, cls))
    return {"openings": out, "fills": fills}


def _add_georeferencing(step, model_context, config):
    geo = config.get("georeference", {}) if isinstance(config, dict) else {}
    crs_name = str(geo.get("crs_name") or geo.get("epsg") or "").strip()
    if not crs_name: return None
    epsg = str(geo.get("epsg") or "").strip()
    if epsg and not crs_name.upper().startswith("EPSG"):
        crs_name = f"{crs_name} ({epsg})"
    crs = step.add("IfcProjectedCRS",
        f"{_s(crs_name)},{_s(geo.get('description'))},{_s(geo.get('geodetic_datum'))},{_s(geo.get('vertical_datum'))},{_s(geo.get('map_projection'))},{_s(geo.get('map_zone'))},$")
    conv = step.add("IfcMapConversion",
        f"{model_context},{crs},{_real(geo.get('eastings',0.0))},{_real(geo.get('northings',0.0))},{_real(geo.get('orthogonal_height',0.0))},{_real(geo.get('x_axis_abscissa',1.0))},{_real(geo.get('x_axis_ordinate',0.0))},{_real(geo.get('scale',1.0))}")
    return {"crs": crs, "conversion": conv}


def _relation_memberships(step, config, product_by_gid, project_ref, building_ref):
    """Export Zones, IfcSystem and generic IfcGroup relationships."""
    result = {"zones": 0, "systems": 0, "groups": 0}
    for key, entity, object_type in (("zones", "IfcZone", "Zone"), ("systems", "IfcSystem", "System"), ("groups", "IfcGroup", "Group")):
        for item in config.get(key, ()) or ():
            if not isinstance(item, dict): continue
            name = str(item.get("name") or "").strip()
            if not name: continue
            gid = str(item.get("global_id") or deterministic_ifc_guid(str(config.get('spatial_ids',{}).get('project') or 'OpenTrace'), f"{key}|{name}"))
            if entity == "IfcZone": ref = step.add(entity, f"{_s(gid)},$,{_s(name)},{_s(item.get('description'))},{_s(object_type)},{_s(item.get('long_name') or name)}")
            else: ref = step.add(entity, f"{_s(gid)},$,{_s(name)},{_s(item.get('description'))},{_s(item.get('object_type') or object_type)}")
            members = [product_by_gid[g] for g in item.get("members", item.get("spaces", ())) if g in product_by_gid]
            if members:
                step.add("IfcRelAssignsToGroup", f"{_s(new_ifc_guid())},$,$,$,{_list(members)},$,{ref}")
            if entity == "IfcSystem":
                # A project-level system services the building even when it has
                # no members yet; this is useful for later MEP assignment.
                try: step.add("IfcRelServicesBuildings", f"{_s(new_ifc_guid())},$,$,$,{ref},{_list([building_ref])}")
                except Exception: pass
            result[key] += 1
    return result


def export_ifc(app, path, *, data=None):
    """Export OpenTrace parametric objects from ``app.scene`` to IFC4.

    Returns a summary dictionary.  The exporter uses only public OpenTrace/IngeTrazo
    state and writes STEP directly, so the build remains usable even when the
    host Python cannot load Bonsai's platform-specific IfcOpenShell binary.
    """
    scene = getattr(app, "scene", None)
    if scene is None:
        raise IfcExportError("Não há documento ativo para exportar.")
    groups = [g for g in list(getattr(scene, "groups", ()) or ()) if is_bim_group(g)]
    if not groups:
        raise IfcExportError("O documento não contém elementos OpenTrace BIM para exportar.")

    config = copy.deepcopy(data or load_document_data(app))
    project = config.get("project", {})
    options = config.get("export", {})
    include_psets = bool(options.get("include_property_sets", True))
    include_layers = bool(options.get("include_material_layers", True))
    include_openings = bool(options.get("include_opening_relations", True))
    include_quantities = bool(options.get("include_quantities", True))
    include_styles = bool(options.get("include_styles", True))
    include_roundtrip = bool(options.get("include_parametric_roundtrip", True))
    profile_key, profile_cfg = export_profile(options.get("profile", "bonsai"))
    if profile_key != "opentrace":
        include_openings = False
    # Compatibility presets bake openings in the host geometry. Exporting an
    # additional representation-less IfcOpeningElement makes some viewers try
    # to cut the same void again; only the fidelity profile enables it by default.
    if "include_opening_relations" not in options:
        include_openings = bool(profile_cfg.get("opening_relations", False))

    step = _Step("ReferenceView_V1.2" if profile_key == "opentrace" else "DesignTransferView_V1.0")
    # Shared geometry / units.  Author both the 3D Model and 2D Plan context
    # tree used by standard IFC authoring tools.  Bonsai's native wall editor,
    # for example, asks explicitly for Plan/Axis/GRAPH_VIEW; omitting that
    # context made an otherwise valid OpenTrace IfcWall crash on edit.
    origin = step.add("IfcCartesianPoint", "(0.,0.,0.)")
    zdir = step.add("IfcDirection", "(0.,0.,1.)")
    xdir = step.add("IfcDirection", "(1.,0.,0.)")
    axis = step.add("IfcAxis2Placement3D", f"{origin},{zdir},{xdir}")
    model_context = step.add("IfcGeometricRepresentationContext", f"$,'Model',3,1.E-05,{axis},$")
    origin2 = step.add("IfcCartesianPoint", "(0.,0.)")
    xdir2 = step.add("IfcDirection", "(1.,0.)")
    axis2 = step.add("IfcAxis2Placement2D", f"{origin2},{xdir2}")
    plan_context = step.add("IfcGeometricRepresentationContext", f"$,'Plan',2,1.E-05,{axis2},$")
    body_context = step.add("IfcGeometricRepresentationSubContext", f"'Body','Model',*,*,*,*,{model_context},$,.MODEL_VIEW.,$")
    plan_axis_context = step.add("IfcGeometricRepresentationSubContext", f"'Axis','Plan',*,*,*,*,{plan_context},$,.GRAPH_VIEW.,$")
    model_axis_context = step.add("IfcGeometricRepresentationSubContext", f"'Axis','Model',*,*,*,*,{model_context},$,.GRAPH_VIEW.,$")
    contexts = {"model": model_context, "plan": plan_context, "body": body_context,
                "plan_axis": plan_axis_context, "model_axis": model_axis_context}
    georef = _add_georeferencing(step, model_context, config)
    length_unit = step.add("IfcSIUnit", "*,.LENGTHUNIT.,$,.METRE.")
    area_unit = step.add("IfcSIUnit", "*,.AREAUNIT.,$,.SQUARE_METRE.")
    volume_unit = step.add("IfcSIUnit", "*,.VOLUMEUNIT.,$,.CUBIC_METRE.")
    angle_unit = step.add("IfcSIUnit", "*,.PLANEANGLEUNIT.,$,.RADIAN.")
    units = step.add("IfcUnitAssignment", f"{_list([length_unit, area_unit, volume_unit, angle_unit])}")
    global_place = step.add("IfcLocalPlacement", f"$,{axis}")

    storeys = _storeys(app)
    ensure_spatial_ids(config, [lv["name"] for lv in storeys],
                       [str(x.get("name") or "") for x in config.get("zones", ()) if isinstance(x, dict)])
    spatial_ids = config.get("spatial_ids", {})
    project_gid = spatial_ids.get("project") or new_ifc_guid()
    project_ref = step.add("IfcProject", f"{_s(project_gid)},$,{_s(project.get('name') or 'Projeto OpenTrace')},{_s(project.get('description') or '')},$,$,$,{_list([model_context, plan_context])},{units}")
    site_ref = step.add("IfcSite", f"{_s(spatial_ids.get('site') or new_ifc_guid())},$,{_s(project.get('site') or 'Terreno')},$,$,{global_place},$,$,.ELEMENT.,$,$,$,$,$")
    building_ref = step.add("IfcBuilding", f"{_s(spatial_ids.get('building') or new_ifc_guid())},$,{_s(project.get('building') or 'Edifício')},$,$,{global_place},$,$,.ELEMENT.,$,$,$")
    step.add("IfcRelAggregates", f"{_s(new_ifc_guid())},$,$,$,{project_ref},{_list([site_ref])}")
    step.add("IfcRelAggregates", f"{_s(new_ifc_guid())},$,$,$,{site_ref},{_list([building_ref])}")

    storey_refs = {}
    spatial_children = []
    storey_ids = spatial_ids.get("storeys", {})
    for lv in storeys:
        ref = step.add("IfcBuildingStorey", f"{_s(storey_ids.get(lv['name']) or new_ifc_guid())},$,{_s(lv['name'])},$,$,{global_place},$,$,.ELEMENT.,{_real(lv['z'])}")
        storey_refs[lv["name"]] = ref
        spatial_children.append(ref)
    step.add("IfcRelAggregates", f"{_s(new_ifc_guid())},$,$,$,{building_ref},{_list(spatial_children)}")

    type_cache = {}
    representation_map_cache = {}
    material_cache = {}
    classification_cache = {}
    by_storey = {name: [] for name in storey_refs}
    exported = []
    product_by_gid = {}
    opening_count = 0
    representation_counts = {"SweptSolid": 0, "Brep": 0, "Tessellation": 0, "MappedRepresentation": 0}

    for group in groups:
        meta = ifc_identity_data(group)
        rec = record_for(group)
        ifc_class = str(meta.get("class") or "IfcBuildingElementProxy")
        repmap_ref=None; prototype_key=None; source_rep_kind=None
        if bool(options.get("use_representation_maps",True)):
            prototype_key=_component_prototype_key(group)
        if prototype_key is not None:
            cache_key=(ifc_class,profile_key,prototype_key)
            cached=representation_map_cache.get(cache_key)
            if cached is None:
                cached=_component_representation_map(step,contexts,group,profile_key);representation_map_cache[cache_key]=cached
            repmap_ref,source_rep_kind=cached
            shape=_mapped_shape(step,contexts,repmap_ref,group) if repmap_ref else None
            representation_kind="MappedRepresentation" if shape else None
        else:
            shape, representation_kind = _shape_representation(step, contexts, group, rec, profile_key)
        if shape is None:
            continue
        gid = str(meta.get("global_id") or new_ifc_guid())
        meta["global_id"] = gid
        name = str(meta.get("name") or getattr(group, "name", None) or ifc_class)
        predefined = str(meta.get("predefined_type") or "NOTDEFINED")
        type_name = str(meta.get("type_name") or "OpenTrace Type")
        raw_object_type = meta.get("object_type") or (type_name if str(predefined).upper() == "USERDEFINED" else None)
        object_type = _s(raw_object_type) if raw_object_type else "$"
        product = _make_product(step, ifc_class, gid, name, object_type, global_place, shape, predefined, meta)
        exported.append(product)
        product_by_gid[gid] = product
        representation_counts[representation_kind] = representation_counts.get(representation_kind, 0) + 1

        rec["type_name"] = type_name
        tkey = (ifc_class, type_name, predefined, prototype_key if repmap_ref else None)
        type_ref = type_cache.get(tkey)
        if tkey not in type_cache:
            type_gid = deterministic_ifc_guid(project_gid, f"type|{ifc_class}|{type_name}|{predefined}|{prototype_key if repmap_ref else ''}")
            type_ref = _make_type(step, ifc_class, type_name, predefined, type_gid, [repmap_ref] if repmap_ref else None)
            type_cache[tkey] = type_ref
        if type_ref:
            step.add("IfcRelDefinesByType", f"{_s(new_ifc_guid())},$,$,$,{_list([product])},{type_ref}")

        if include_layers:
            occurrence_layer_usage=True
            # Bonsai treats every occurrence carrying AXIS2 LayerSetUsage as a
            # natively editable straight wall.  Keep that behaviour only for
            # the subset its wall generator can safely regenerate; complex
            # OpenTrace walls keep their LayerSet on the type, but are not
            # advertised as Bonsai DumbLayer2 occurrences.
            if profile_key=="bonsai" and ifc_class=="IfcWall":
                # Keep the composition on IfcWallType, but do not attach an
                # occurrence LayerSetUsage in the exchange-safe Bonsai preset.
                # Bonsai 0.9 interprets *any* IfcWall with own AXIS2 usage as
                # its editable DumbLayer2 wall and exposes destructive native
                # gizmos even when OpenTrace owns a curved/profiled body.
                occurrence_layer_usage=False
            _add_material(step, product, type_ref, ifc_class, rec, material_cache, meta=meta,
                          contexts=contexts if include_styles else None,
                          occurrence_layer_usage=occurrence_layer_usage)

        if include_psets:
            path_rec = rec.get("path") if isinstance(rec.get("path"), dict) else {}
            props = {
                "Engine": meta.get("engine") or "OpenTrace.Parametric",
                "Kind": rec.get("kind"),
                "ParametricSchema": int(rec.get("schema", 0) or 0),
                "Structure": rec.get("structure", "simple"),
                "BaseLevel": rec.get("base_level"),
                "TopLevel": rec.get("top_level"),
                "PathType": path_rec.get("type") if isinstance(path_rec, dict) else None,
                "Curved": bool((isinstance(path_rec, dict) and path_rec.get("type") == "arc") or abs(float(rec.get("curvature", 0.0) or 0.0)) > 1e-9),
                "ClassificationSystem": meta.get("classification_system"),
                "ClassificationCode": meta.get("classification_code"),
            }
            _add_property_set(step, product, props)
            _add_named_property_set(step, product, "EPset_Parametric", {
                "Engine": f"OpenTrace.{str(rec.get('kind') or 'Element').title()}",
                "LayerSetDirection": ("AXIS3" if ifc_class=="IfcSlab" else "AXIS2" if ifc_class=="IfcWall" else None),
            })
            common = meta.get("common") if isinstance(meta.get("common"), dict) else {}
            if common:
                from .ifc_catalog import common_pset
                pset_name = common_pset(ifc_class)
                if pset_name:
                    _add_named_property_set(step, product, pset_name, common)
            # Full official/custom property-set payload imported or authored in
            # the advanced BIM editor. Names are preserved exactly.
            authored_psets = meta.get("property_sets") if isinstance(meta.get("property_sets"), dict) else {}
            for pset_name, values in authored_psets.items():
                if pset_name in ("Pset_OpenTraceParametric", "EPset_Parametric") or not isinstance(values, dict):
                    continue
                _add_named_property_set(step, product, pset_name, values)
            if include_roundtrip and rec.get("schema"):
                payload = json.dumps(_parametric_payload(group, rec), ensure_ascii=False, separators=(",", ":"))
                _add_named_property_set(step, product, "EPset_OpenTraceRoundTrip", {
                    "Engine": meta.get("engine") or "OpenTrace.Parametric",
                    "PluginVersion": __version__, "PayloadJSON": payload,
                })

        if include_quantities:
            _add_quantities(step, product, ifc_class, rec)
            _add_preserved_quantities(step, product, meta.get("quantities"))

        _add_classification(step, project_ref, product, meta, classification_cache)

        storey_name = _best_storey_name(group, rec, storeys)
        by_storey.setdefault(storey_name, []).append(product)
        if include_openings:
            ops = _add_opening_relations(step, product, rec, storey_refs.get(storey_name), global_place,
                                         body_context, include_psets, type_cache=type_cache,
                                         project_gid=project_gid)
            opening_count += len(ops.get("openings", ()))
            for fgid, fref, _fcls in ops.get("fills", ()):
                product_by_gid[fgid] = fref

    for name, refs in by_storey.items():
        if refs:
            step.add("IfcRelContainedInSpatialStructure", f"{_s(new_ifc_guid())},$,$,$,{_list(refs)},{storey_refs[name]}")

    relations = _relation_memberships(step, config, product_by_gid, project_ref, building_ref)

    if not exported:
        raise IfcExportError("Nenhuma geometria OpenTrace pôde ser convertida para IFC.")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(step.render(target.name, project.get("author", ""), project.get("organization", "")), encoding="utf-8", newline="\n")
    return {
        "path": str(target),
        "elements": len(exported),
        "openings": opening_count,
        "storeys": len(storey_refs),
        "types": sum(1 for x in type_cache.values() if x),
        "schema": "IFC4",
        "profile": profile_key,
        "representations": representation_counts,
        "georeferenced": bool(georef),
        "relations": relations,
        "representation_maps": len(representation_map_cache),
        "catalogue": "IFC4 Add2 TC1 / IfcOpenShell 0.9.0 data",
    }
