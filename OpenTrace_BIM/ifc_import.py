# SPDX-License-Identifier: GPL-3.0-or-later
"""Small IFC geometry reader for OpenTrace BIM.

This is intentionally not a replacement for IfcOpenShell.  It gives the
extension useful Open/Import/Link commands without modifying IngeTrazo core and
without making the plugin fail when a platform-specific IfcOpenShell wheel is
unavailable.  It supports the geometry families emitted by OpenTrace itself
(IFC4 PolygonalFaceSet, FacetedBrep and its native ExtrudedAreaSolid profiles).
When IfcOpenShell becomes a packaged dependency this module remains the safe
fallback and the scene-insertion layer.
"""
from __future__ import annotations

import ast
import copy
import json
import math
import re
from pathlib import Path

from PySide6.QtGui import QVector3D, QVector4D, QMatrix4x4
from core.group import Group
from core.mesh import Mesh
from core.history import Command
from .ifc_catalog import common_pset


class IfcImportError(RuntimeError):
    pass


def _matrix_from_payload(raw):
    if not isinstance(raw,list) or len(raw)!=4:return None
    try:
        m=QMatrix4x4()
        for r in range(4):
            row=list(raw[r])
            if len(row)!=4:return None
            m.setRow(r,QVector4D(*[float(x) for x in row]))
        return m
    except Exception:return None


def _restore_opentrace_roundtrip(group,psets):
    """Reattach OpenTrace parametric state carried in EPset_OpenTraceRoundTrip.

    IFC geometry is already imported in world/IFC placement coordinates.  The
    payload also carries the original OpenTrace group matrix, so localise the
    mesh beneath that matrix before attaching the parametric record. This makes
    an OpenTrace-exported IFC editable again instead of only looking correct.
    """
    if not isinstance(psets,dict):return False
    rt=psets.get("EPset_OpenTraceRoundTrip")
    if not isinstance(rt,dict):return False
    raw=rt.get("PayloadJSON")
    if not isinstance(raw,str) or not raw.strip():return False
    try:payload=json.loads(raw);rec=payload.get("record")
    except Exception:return False
    if not isinstance(rec,dict) or not rec.get("kind"):return False
    desired=_matrix_from_payload(payload.get("xform")) or QMatrix4x4()
    inv,ok=desired.inverted()
    if not ok:return False
    parent=QMatrix4x4(getattr(group,"xform",None) or QMatrix4x4())
    try:
        from core.group import transformed_mesh
        children=list(getattr(group,"children",()) or ())
        if children:
            for child in children:
                cm=QMatrix4x4(getattr(child,"xform",None) or QMatrix4x4())
                child.mesh=transformed_mesh(child.mesh,inv*parent*cm);child.xform=None
        elif getattr(group,"mesh",None) is not None:
            group.mesh=transformed_mesh(group.mesh,inv*parent)
        group.xform=desired
    except Exception:
        # State is still valuable, but do not attach it if localising the mesh
        # failed; otherwise the first parametric edit would jump the object.
        return False
    ext=copy.deepcopy(getattr(group,"ext",None) or {})
    ext["arquitetura_parametrica"]=copy.deepcopy(rec)
    ext.setdefault("opentrace_ifc_import",{})["roundtrip_restored"]=True
    group.ext=ext
    meta=getattr(group,"ifc",None)
    if isinstance(meta,dict):meta["engine"]="OpenTrace."+str(rec.get("kind") or "Parametric").title()
    return True


def _rows(text):
    start=text.upper().find("DATA;")
    end=text.upper().find("ENDSEC;",start+5)
    data=text[start+5:end if end>=0 else None]
    out={};i=0;n=len(data)
    while i<n:
        h=data.find("#",i)
        if h<0:break
        eq=data.find("=",h)
        if eq<0:break
        ident=data[h+1:eq].strip()
        if not ident.isdigit():i=eq+1;continue
        lp=data.find("(",eq)
        if lp<0:break
        entity=data[eq+1:lp].strip().upper();depth=0;quote=False;j=lp
        while j<n:
            c=data[j]
            if c=="'":
                if quote and j+1<n and data[j+1]=="'":j+=2;continue
                quote=not quote
            elif not quote:
                if c=="(":depth+=1
                elif c==")":
                    depth-=1
                    if depth==0:
                        semi=data.find(";",j)
                        out[int(ident)]=(entity,data[lp+1:j])
                        i=(semi+1 if semi>=0 else j+1);break
            j+=1
        else:break
    return out


def _split(raw):
    parts=[];start=0;depth=0;quote=False;i=0
    while i<len(raw):
        c=raw[i]
        if c=="'":
            if quote and i+1<len(raw) and raw[i+1]=="'":i+=2;continue
            quote=not quote
        elif not quote:
            if c=="(":depth+=1
            elif c==")":depth-=1
            elif c=="," and depth==0:
                parts.append(raw[start:i].strip());start=i+1
        i+=1
    parts.append(raw[start:].strip())
    return parts


def _ref(raw):
    m=re.fullmatch(r"#(\d+)",str(raw).strip());return int(m.group(1)) if m else None


def _refs(raw):return [int(x) for x in re.findall(r"#(\d+)",str(raw))]

def _text(raw):
    raw=str(raw).strip()
    if raw=="$":return ""
    if len(raw)>=2 and raw[0]==raw[-1]=="'":return raw[1:-1].replace("''", "'")
    return raw.strip(".")

def _literal(raw):
    try:return ast.literal_eval(raw)
    except Exception:raise IfcImportError("Não foi possível interpretar uma lista geométrica do IFC.")


def _typed_value(raw):
    raw=str(raw).strip()
    if raw in ("$","*"):return None
    m=re.match(r"IFC[A-Z0-9_]+\((.*)\)$",raw,re.I|re.S)
    inner=m.group(1).strip() if m else raw
    if inner in (".T.",".TRUE."):return True
    if inner in (".F.",".FALSE."):return False
    if len(inner)>=2 and inner[0]==inner[-1]=="'":return _text(inner)
    try:return float(inner) if any(c in inner for c in ".Ee") else int(inner)
    except Exception:return _text(inner)


def _pset_maps(rows):
    props={}
    for rid,(ent,args) in rows.items():
        if ent=="IFCPROPERTYSINGLEVALUE":
            a=_split(args);props[rid]=(_text(a[0]) if a else "",_typed_value(a[2]) if len(a)>2 else None)
    psets={}
    for rid,(ent,args) in rows.items():
        if ent=="IFCPROPERTYSET":
            a=_split(args);name=_text(a[2]) if len(a)>2 else "PropertySet"
            psets[rid]=(name,{props[r][0]:props[r][1] for r in _refs(a[4]) if r in props}) if len(a)>4 else (name,{})
    by_product={}
    for _rid,(ent,args) in rows.items():
        if ent!="IFCRELDEFINESBYPROPERTIES":continue
        a=_split(args)
        if len(a)<6:continue
        pr=_ref(a[5])
        if pr not in psets:continue
        name,vals=psets[pr]
        for obj in _refs(a[4]):by_product.setdefault(obj,{})[name]=vals
    return by_product


def _type_maps(rows):
    out={}
    for _rid,(ent,args) in rows.items():
        if ent!="IFCRELDEFINESBYTYPE":continue
        a=_split(args)
        if len(a)<6:continue
        tref=_ref(a[5]);tent,targs=rows.get(tref,(None,None));ta=_split(targs or "")
        if not tent or not tent.endswith("TYPE"):continue
        info={"class":"Ifc"+tent[3:].title(),"name":_text(ta[2]) if len(ta)>2 else ""}
        if ta:info["predefined_type"]=_text(ta[-1])
        for obj in _refs(a[4]):out[obj]=info
    return out


def _type_ref_maps(rows):
    out={}
    for _rid,(ent,args) in rows.items():
        if ent!="IFCRELDEFINESBYTYPE":continue
        a=_split(args)
        if len(a)<6:continue
        tref=_ref(a[5])
        if tref:
            for obj in _refs(a[4]):out[obj]=tref
    return out


def _classification_maps(rows):
    systems={}
    for rid,(ent,args) in rows.items():
        if ent=="IFCCLASSIFICATION":
            a=_split(args);systems[rid]=_text(a[3]) if len(a)>3 else ""
    refs={}
    for rid,(ent,args) in rows.items():
        if ent=="IFCCLASSIFICATIONREFERENCE":
            a=_split(args);source=_ref(a[3]) if len(a)>3 else None
            refs[rid]={"system":systems.get(source,""),"code":_text(a[1]) if len(a)>1 else ""}
    out={}
    for _rid,(ent,args) in rows.items():
        if ent!="IFCRELASSOCIATESCLASSIFICATION":continue
        a=_split(args)
        if len(a)<6:continue
        rr=_ref(a[5]);info=refs.get(rr)
        if info:
            for obj in _refs(a[4]):out[obj]=info
    return out


def _material_name_from(rows,ref):
    ent,args=rows.get(ref,(None,None));a=_split(args or "")
    if ent=="IFCMATERIAL":return _text(a[0]) if a else ""
    if ent=="IFCMATERIALLAYERSETUSAGE":return _material_name_from(rows,_ref(a[0])) if a else ""
    if ent=="IFCMATERIALLAYERSET":return _text(a[1]) if len(a)>1 else "Composição"
    if ent=="IFCMATERIALPROFILESET":return _text(a[0]) if a else "Perfil"
    return ""

def _material_maps(rows):
    out={}
    for _rid,(ent,args) in rows.items():
        if ent!="IFCRELASSOCIATESMATERIAL":continue
        a=_split(args)
        if len(a)<6:continue
        name=_material_name_from(rows,_ref(a[5]))
        if name:
            for obj in _refs(a[4]):out[obj]=name
    return out


def _material_detail(rows,ref,scale=1.0,seen=None):
    seen=set(seen or ())
    if not ref or ref in seen:return {}
    seen.add(ref);ent,args=rows.get(ref,(None,None));a=_split(args or "")
    if ent=="IFCMATERIAL":return {"kind":"material","name":_text(a[0]) if a else ""}
    if ent=="IFCMATERIALLAYERSETUSAGE" and a:
        out=_material_detail(rows,_ref(a[0]),scale,seen);out["usage"]="IfcMaterialLayerSetUsage"
        if len(a)>1:out["direction"]=_enum(a[1])
        return out
    if ent=="IFCMATERIALLAYERSET":
        layers=[]
        for lr in _refs(a[0]) if a else ():
            lent,largs=rows.get(lr,(None,None));la=_split(largs or "")
            if lent!="IFCMATERIALLAYER" or len(la)<2:continue
            mat=_material_detail(rows,_ref(la[0]),scale,seen.copy())
            try:th=float(la[1])*scale
            except Exception:th=0.0
            layers.append({"name":_text(la[3]) if len(la)>3 else (mat.get("name") or "Camada"),
                           "material":mat.get("name") or "Padrão","thickness":th,
                           "function":_text(la[5]) if len(la)>5 else ""})
        return {"kind":"layerset","name":_text(a[1]) if len(a)>1 else "Composição","layers":layers}
    if ent=="IFCMATERIALPROFILESETUSAGE" and a:
        out=_material_detail(rows,_ref(a[0]),scale,seen);out["usage"]="IfcMaterialProfileSetUsage";return out
    if ent=="IFCMATERIALPROFILESET":
        profiles=[]
        for pr in _refs(a[2]) if len(a)>2 else (_refs(a[0]) if a else []):
            pent,pargs=rows.get(pr,(None,None));pa=_split(pargs or "")
            if pent!="IFCMATERIALPROFILE":continue
            mat=_material_detail(rows,_ref(pa[2]) if len(pa)>2 else None,scale,seen.copy())
            profiles.append({"name":_text(pa[0]) if pa else "Perfil","material":mat.get("name") or "Padrão","category":_text(pa[5]) if len(pa)>5 else ""})
        return {"kind":"profileset","name":_text(a[0]) if a else "Perfil","profiles":profiles}
    if ent=="IFCMATERIALCONSTITUENTSET":
        refs=_refs(a[2]) if len(a)>2 else [] ; items=[]
        for cr in refs:
            cent,cargs=rows.get(cr,(None,None));ca=_split(cargs or "")
            if cent!="IFCMATERIALCONSTITUENT":continue
            mat=_material_detail(rows,_ref(ca[2]) if len(ca)>2 else None,scale,seen.copy())
            items.append({"name":_text(ca[0]) if ca else (mat.get("name") or "Constituinte"),"material":mat.get("name") or "Padrão","category":_text(ca[4]) if len(ca)>4 else ""})
        return {"kind":"constituentset","name":_text(a[0]) if a else "Constituintes","constituents":items}
    return {}


def _material_detail_maps(rows,scale=1.0):
    out={}
    for _rid,(ent,args) in rows.items():
        if ent!="IFCRELASSOCIATESMATERIAL":continue
        a=_split(args)
        if len(a)<6:continue
        detail=_material_detail(rows,_ref(a[5]),scale)
        if detail:
            for obj in _refs(a[4]):out[obj]=copy.deepcopy(detail)
    return out

_SI_PREFIX = {
    "EXA":1e18,"PETA":1e15,"TERA":1e12,"GIGA":1e9,"MEGA":1e6,"KILO":1e3,
    "HECTO":1e2,"DECA":1e1,"DECI":1e-1,"CENTI":1e-2,"MILLI":1e-3,
    "MICRO":1e-6,"NANO":1e-9,"PICO":1e-12,"FEMTO":1e-15,"ATTO":1e-18,
}


def _enum(raw):
    return str(raw or "").strip().strip(".").upper()


def _length_scale(rows):
    """Metres per IFC length unit for the fallback STEP reader."""
    # Ordinary SI projects (metre, millimetre, centimetre...).
    for _rid,(ent,args) in rows.items():
        if ent!="IFCSIUNIT": continue
        a=_split(args)
        if len(a)<4 or _enum(a[1])!="LENGTHUNIT": continue
        prefix=_enum(a[2]) if a[2] not in ("$","*") else ""
        name=_enum(a[3])
        if name=="METRE": return float(_SI_PREFIX.get(prefix,1.0))
    # Conversion-based units, e.g. feet / inches. Their conversion factor is
    # an IfcMeasureWithUnit whose value is expressed in another unit.
    def unit_factor(ref,seen=None):
        if not ref:return None
        seen=set(seen or ())
        if ref in seen:return None
        seen.add(ref)
        ent,args=rows.get(ref,(None,None));a=_split(args or "")
        if ent=="IFCSIUNIT" and len(a)>=4 and _enum(a[1])=="LENGTHUNIT":
            return float(_SI_PREFIX.get(_enum(a[2]) if a[2] not in ("$","*") else "",1.0)) if _enum(a[3])=="METRE" else None
        if ent=="IFCCONVERSIONBASEDUNIT" and len(a)>=4 and _enum(a[1])=="LENGTHUNIT":
            cf=_ref(a[3]);cent,cargs=rows.get(cf,(None,None));ca=_split(cargs or "")
            if cent=="IFCMEASUREWITHUNIT" and len(ca)>=2:
                value=_typed_value(ca[0]);base=unit_factor(_ref(ca[1]),seen)
                if isinstance(value,(int,float)) and base is not None:return float(value)*base
        return None
    for rid,(ent,args) in rows.items():
        if ent=="IFCCONVERSIONBASEDUNIT":
            a=_split(args)
            if len(a)>=2 and _enum(a[1])=="LENGTHUNIT":
                f=unit_factor(rid)
                if f is not None:return f
    return 1.0


def _direction(rows,ref,default):
    ent,args=rows.get(ref,(None,None))
    if ent!="IFCDIRECTION":return QVector3D(*default)
    try:vals=_literal(args)
    except Exception:return QVector3D(*default)
    vals=list(vals) if isinstance(vals,(list,tuple)) else [vals]
    vals=(vals+[0.0,0.0,0.0])[:3]
    v=QVector3D(float(vals[0]),float(vals[1]),float(vals[2]))
    return v.normalized() if v.lengthSquared()>1e-18 else QVector3D(*default)


def _matrix_from_axes(origin,x,y,z):
    m=QMatrix4x4()
    m.setColumn(0,QVector4D(x.x(),x.y(),x.z(),0.0))
    m.setColumn(1,QVector4D(y.x(),y.y(),y.z(),0.0))
    m.setColumn(2,QVector4D(z.x(),z.y(),z.z(),0.0))
    m.setColumn(3,QVector4D(origin.x(),origin.y(),origin.z(),1.0))
    return m


def _axis2placement_matrix(rows,ref,scale=1.0):
    ent,args=rows.get(ref,(None,None));a=_split(args or "")
    if ent=="IFCAXIS2PLACEMENT3D":
        o=_point(rows,_ref(a[0]),scale) if a and _ref(a[0]) else QVector3D()
        z=_direction(rows,_ref(a[1]) if len(a)>1 else None,(0,0,1))
        x0=_direction(rows,_ref(a[2]) if len(a)>2 else None,(1,0,0))
        x=x0-z*QVector3D.dotProduct(x0,z)
        if x.lengthSquared()<1e-18:
            alt=QVector3D(0,1,0) if abs(z.y())<0.9 else QVector3D(1,0,0)
            x=alt-z*QVector3D.dotProduct(alt,z)
        x.normalize();y=QVector3D.crossProduct(z,x).normalized()
        return _matrix_from_axes(o,x,y,z)
    if ent=="IFCAXIS2PLACEMENT2D":
        o=_point(rows,_ref(a[0]),scale) if a and _ref(a[0]) else QVector3D()
        x=_direction(rows,_ref(a[1]) if len(a)>1 else None,(1,0,0));x.setZ(0.0)
        if x.lengthSquared()<1e-18:x=QVector3D(1,0,0)
        x.normalize();y=QVector3D(-x.y(),x.x(),0.0);z=QVector3D(0,0,1)
        return _matrix_from_axes(o,x,y,z)
    return QMatrix4x4()


def _local_placement_matrix(rows,ref,scale=1.0,cache=None,seen=None):
    if not ref:return QMatrix4x4()
    cache=cache if cache is not None else {}
    if ref in cache:return QMatrix4x4(cache[ref])
    seen=set(seen or ())
    if ref in seen:return QMatrix4x4()
    seen.add(ref)
    ent,args=rows.get(ref,(None,None));a=_split(args or "")
    if ent!="IFCLOCALPLACEMENT" or len(a)<2:return QMatrix4x4()
    parent=_local_placement_matrix(rows,_ref(a[0]),scale,cache,seen) if a[0] not in ("$","*") else QMatrix4x4()
    local=_axis2placement_matrix(rows,_ref(a[1]),scale)
    result=parent*local;cache[ref]=QMatrix4x4(result);return result


def _cartesian_transform_matrix(rows,ref,scale=1.0):
    ent,args=rows.get(ref,(None,None));a=_split(args or "")
    if ent not in ("IFCCARTESIANTRANSFORMATIONOPERATOR3D","IFCCARTESIANTRANSFORMATIONOPERATOR3DNONUNIFORM"):
        return QMatrix4x4()
    x=_direction(rows,_ref(a[0]) if len(a)>0 else None,(1,0,0))
    y0=_direction(rows,_ref(a[1]) if len(a)>1 else None,(0,1,0))
    o=_point(rows,_ref(a[2]),scale) if len(a)>2 and _ref(a[2]) else QVector3D()
    sf=float(a[3]) if len(a)>3 and a[3] not in ("$","*") else 1.0
    z=_direction(rows,_ref(a[4]) if len(a)>4 else None,(0,0,1))
    x=x-z*QVector3D.dotProduct(x,z)
    if x.lengthSquared()<1e-18:x=QVector3D(1,0,0)
    x.normalize();y=QVector3D.crossProduct(z,x).normalized()
    # If a valid second axis is supplied preserve its handedness.
    if QVector3D.dotProduct(y,y0)<0:y=-y
    sx=sf;sy=sf;sz=sf
    if ent.endswith("NONUNIFORM"):
        try:
            if len(a)>5 and a[5] not in ("$","*"):sy=float(a[5])
            if len(a)>6 and a[6] not in ("$","*"):sz=float(a[6])
        except Exception:pass
    return _matrix_from_axes(o,x*sx,y*sy,z*sz)

def _point(rows, ref, scale=1.0):
    ent,args=rows[ref]
    if ent!="IFCCARTESIANPOINT":raise IfcImportError("Ponto IFC inválido.")
    vals=_literal(args)
    vals=list(vals) if isinstance(vals,(list,tuple)) else [vals]
    vals=(vals+[0.0,0.0,0.0])[:3]
    return QVector3D(float(vals[0])*scale,float(vals[1])*scale,float(vals[2])*scale)


def _mesh_from_polygonal(rows, ref, scale=1.0):
    ent,args=rows[ref];a=_split(args)
    if ent!="IFCPOLYGONALFACESET" or len(a)<3:return None
    pl=_ref(a[0]);pent,pargs=rows.get(pl,(None,None))
    if pent!="IFCCARTESIANPOINTLIST3D":return None
    coords=_literal(pargs)
    pts=[QVector3D(float(v[0])*scale,float(v[1])*scale,float(v[2])*scale) for v in coords]
    mesh=Mesh()
    for fref in _refs(a[2]):
        fent,fargs=rows.get(fref,(None,None));fa=_split(fargs or "")
        if fent=="IFCINDEXEDPOLYGONALFACE":
            idx=_literal(fa[0]);mesh.add_face([pts[int(i)-1] for i in idx])
        elif fent=="IFCINDEXEDPOLYGONALFACEWITHVOIDS":
            outer=_literal(fa[0]);holes=_literal(fa[1]) if len(fa)>1 else []
            mesh.add_face([pts[int(i)-1] for i in outer],[[pts[int(i)-1] for i in h] for h in holes])
    return mesh if list(getattr(mesh,"faces",()) or ()) else None


def _mesh_from_triangulated(rows,ref,scale=1.0):
    ent,args=rows[ref];a=_split(args)
    if ent!="IFCTRIANGULATEDFACESET" or len(a)<4:return None
    pl=_ref(a[0]);pent,pargs=rows.get(pl,(None,None))
    if pent!="IFCCARTESIANPOINTLIST3D":return None
    try:coords=_literal(pargs);indices=_literal(a[3])
    except Exception:return None
    pts=[QVector3D(float(v[0])*scale,float(v[1])*scale,float(v[2])*scale) for v in coords]
    mesh=Mesh()
    for tri in indices or ():
        try:
            ids=[int(i)-1 for i in tri]
            if len(ids)>=3:mesh.add_face([pts[ids[0]],pts[ids[1]],pts[ids[2]]])
        except Exception:continue
    return mesh if list(getattr(mesh,"faces",()) or ()) else None


def _mesh_from_brep(rows, ref, scale=1.0):
    ent,args=rows[ref]
    if ent!="IFCFACETEDBREP":return None
    shell=_ref(_split(args)[0]);sent,sargs=rows.get(shell,(None,None))
    if sent!="IFCCLOSEDSHELL":return None
    mesh=Mesh()
    for fref in _refs(sargs):
        fent,fargs=rows.get(fref,(None,None))
        if fent!="IFCFACE":continue
        outer=None;holes=[]
        for bref in _refs(fargs):
            bent,bargs=rows.get(bref,(None,None));ba=_split(bargs or "")
            if bent not in ("IFCFACEOUTERBOUND","IFCFACEBOUND") or not ba:continue
            lref=_ref(ba[0]);lent,largs=rows.get(lref,(None,None))
            if lent!="IFCPOLYLOOP":continue
            loop=[_point(rows,r,scale) for r in _refs(largs)]
            if bent=="IFCFACEOUTERBOUND":outer=loop
            else:holes.append(loop)
        if outer and len(outer)>=3:mesh.add_face(outer,holes or None)
    return mesh if list(getattr(mesh,"faces",()) or ()) else None


def _polyline_points(rows, ref, scale=1.0):
    ent,args=rows.get(ref,(None,None))
    if ent!="IFCPOLYLINE":return []
    pts=[_point(rows,r,scale) for r in _refs(args)]
    if len(pts)>1 and (pts[0]-pts[-1]).length()<1e-9:pts=pts[:-1]
    return pts


def _mesh_from_extrusion(rows, ref, scale=1.0):
    ent,args=rows[ref]
    if ent!="IFCEXTRUDEDAREASOLID":return None
    a=_split(args)
    if len(a)<4:return None
    pref=_ref(a[0]);pos=_ref(a[1]);dref=_ref(a[2])
    try:depth=float(a[3])*scale
    except Exception:return None
    pent,pargs=rows.get(pref,(None,None));pa=_split(pargs or "")
    if pent=="IFCARBITRARYCLOSEDPROFILEDEF":outer=_polyline_points(rows,_ref(pa[2]),scale);holes=[]
    elif pent=="IFCARBITRARYPROFILEDEFWITHVOIDS":
        outer=_polyline_points(rows,_ref(pa[2]),scale);holes=[_polyline_points(rows,r,scale) for r in _refs(pa[3])]
    elif pent=="IFCRECTANGLEPROFILEDEF":
        # Profile axes are local to its Position. XDim/YDim are in project units.
        try:
            ppos=_ref(pa[2]) if len(pa)>2 else None;x=float(pa[3])*scale;y=float(pa[4])*scale
        except Exception:return None
        hx,hy=x/2.0,y/2.0;outer=[QVector3D(-hx,-hy,0),QVector3D(hx,-hy,0),QVector3D(hx,hy,0),QVector3D(-hx,hy,0)];holes=[]
        if ppos:
            pm=_axis2placement_matrix(rows,ppos,scale);outer=[pm.map(q) for q in outer]
    elif pent=="IFCCIRCLEPROFILEDEF":
        try:
            ppos=_ref(pa[2]) if len(pa)>2 else None;r=float(pa[3])*scale
        except Exception:return None
        n=32;outer=[QVector3D(math.cos(2*math.pi*i/n)*r,math.sin(2*math.pi*i/n)*r,0) for i in range(n)];holes=[]
        if ppos:
            pm=_axis2placement_matrix(rows,ppos,scale);outer=[pm.map(q) for q in outer]
    else:return None
    if len(outer)<3:return None
    sm=_axis2placement_matrix(rows,pos,scale) if pos else QMatrix4x4()
    direction=_direction(rows,dref,(0,0,1));delta=direction*depth
    bottom=[sm.map(p) for p in outer];top=[p+delta for p in bottom]
    bh=[[sm.map(p) for p in h] for h in holes];th=[[p+delta for p in h] for h in bh]
    mesh=Mesh();mesh.add_face(list(reversed(bottom)),[list(reversed(h)) for h in bh] or None);mesh.add_face(top,th or None)
    loops=[(bottom,top)]+list(zip(bh,th))
    for lo,hi in loops:
        for i in range(len(lo)):
            j=(i+1)%len(lo);mesh.add_face([lo[i],lo[j],hi[j],hi[i]])
    return mesh

def _item_children(rows,item,scale=1.0,depth=0):
    if depth>12:return []
    ient=rows.get(item,(None,None))[0];mesh=None
    if ient=="IFCPOLYGONALFACESET":mesh=_mesh_from_polygonal(rows,item,scale)
    elif ient=="IFCTRIANGULATEDFACESET":mesh=_mesh_from_triangulated(rows,item,scale)
    elif ient=="IFCFACETEDBREP":mesh=_mesh_from_brep(rows,item,scale)
    elif ient=="IFCEXTRUDEDAREASOLID":mesh=_mesh_from_extrusion(rows,item,scale)
    if mesh is not None:
        child=Group(mesh,name="Corpo IFC");child.component=False;return [child]
    if ient=="IFCMAPPEDITEM":
        a=_split(rows[item][1]);source=_ref(a[0]) if a else None;target=_ref(a[1]) if len(a)>1 else None
        sent,sargs=rows.get(source,(None,None));sa=_split(sargs or "")
        if sent!="IFCREPRESENTATIONMAP" or len(sa)<2:return []
        origin=_axis2placement_matrix(rows,_ref(sa[0]),scale) if _ref(sa[0]) else QMatrix4x4()
        inv,ok=origin.inverted(); inv=inv if ok else QMatrix4x4()
        mapped=_ref(sa[1]);ment,margs=rows.get(mapped,(None,None));ma=_split(margs or "")
        subitems=_refs(ma[3]) if ment=="IFCSHAPEREPRESENTATION" and len(ma)>3 else []
        transform=_cartesian_transform_matrix(rows,target,scale)*inv
        out=[]
        for sub in subitems:
            for child in _item_children(rows,sub,scale,depth+1):
                old=getattr(child,"xform",None)
                child.xform=QMatrix4x4(transform if old is None else transform*old)
                child.component=False;out.append(child)
        return out
    return []

def _shape_items(rows, pds_ref):
    ent,args=rows.get(pds_ref,(None,None))
    if ent!="IFCPRODUCTDEFINITIONSHAPE":return []
    a=_split(args)
    reps=_refs(a[2]) if len(a)>2 else []
    out=[]
    for rr in reps:
        rent,rargs=rows.get(rr,(None,None))
        if rent!="IFCSHAPEREPRESENTATION":continue
        ra=_split(rargs or "")
        if len(ra)>3:out.extend(_refs(ra[3]))
    return out



def _parse_with_ifcopenshell(target):
    """Use IfcOpenShell when the host already provides a compatible build."""
    import ifcopenshell
    import ifcopenshell.geom
    model=ifcopenshell.open(str(target))
    try:
        import ifcopenshell.util.unit as util_unit
        unit_scale=float(util_unit.calculate_unit_scale(model))
    except Exception:unit_scale=1.0
    settings=ifcopenshell.geom.settings()
    try:settings.set(settings.USE_WORLD_COORDS,True)
    except Exception:pass
    groups=[];unsupported=0
    try:
        import ifcopenshell.util.element as util_element
    except Exception:
        util_element=None
    for product in model.by_type("IfcProduct"):
        if not getattr(product,"Representation",None):continue
        cls=product.is_a()
        if cls in ("IfcSite","IfcBuilding","IfcBuildingStorey","IfcProject","IfcAnnotation"):continue
        try:
            shape=ifcopenshell.geom.create_shape(settings,product);geom=shape.geometry
            verts=list(getattr(geom,"verts",()) or ());faces=list(getattr(geom,"faces",()) or ())
            if not verts or not faces:unsupported+=1;continue
            pts=[QVector3D(float(verts[i]),float(verts[i+1]),float(verts[i+2])) for i in range(0,len(verts),3)]
            mesh=Mesh()
            for i in range(0,len(faces),3):
                tri=faces[i:i+3]
                if len(tri)==3:mesh.add_face([pts[int(j)] for j in tri])
            if not list(getattr(mesh,"faces",()) or ()):unsupported+=1;continue
            child=Group(mesh,name="Corpo IFC");child.component=False
            g=Group(name=str(getattr(product,"Name",None) or cls));g.adopt([child]);g.component=False
            meta={"class":cls,"name":g.name,"global_id":str(getattr(product,"GlobalId","") or ""),"predefined_type":str(getattr(product,"PredefinedType",None) or "NOTDEFINED"),"engine":"IFC.IfcOpenShell"}
            if util_element is not None:
                try:
                    typ=util_element.get_type(product)
                    if typ is not None and getattr(typ,"Name",None):meta["type_name"]=str(typ.Name)
                except Exception:pass
                try:
                    psets=util_element.get_psets(product,psets_only=False,qtos_only=False)
                    if psets:meta["property_sets"]=psets
                except Exception:pass
                try:
                    mat=util_element.get_material(product,should_skip_usage=True)
                    if mat is not None and getattr(mat,"Name",None):meta["material_name"]=str(mat.Name)
                except Exception:pass
            g.ifc=meta;g.ext={"opentrace_ifc_import":{"source":str(target),"entity_id":int(product.id()),"class":cls,"reader":"IfcOpenShell","property_sets":meta.get("property_sets",{})}}
            _restore_opentrace_roundtrip(g,meta.get("property_sets",{}))
            groups.append(g)
        except Exception:
            unsupported+=1
    if not groups:raise IfcImportError("IfcOpenShell abriu o arquivo, mas nenhuma geometria de produto pôde ser convertida.")
    project={}
    for cls,key in (("IfcProject","name"),("IfcSite","site"),("IfcBuilding","building")):
        arr=model.by_type(cls)
        if arr and getattr(arr[0],"Name",None):project[key]=str(arr[0].Name)
    return {"groups":groups,"project":project,"unsupported":unsupported,"path":str(target),"reader":"IfcOpenShell","unit_scale":unit_scale}


def parse_ifc(path):
    target=Path(path)
    try:
        return _parse_with_ifcopenshell(target)
    except (ImportError,ModuleNotFoundError):
        pass
    except IfcImportError:
        # Fall back to the small STEP reader: it may understand an OpenTrace
        # representation even when the host's IfcOpenShell geometry backend is incomplete.
        pass
    except Exception:
        pass
    text=target.read_text(encoding="utf-8",errors="replace");rows=_rows(text)
    if not rows:raise IfcImportError("O arquivo não contém uma seção DATA IFC legível.")
    psets_by_product=_pset_maps(rows);types_by_product=_type_maps(rows);type_ref_by_product=_type_ref_maps(rows);class_by_product=_classification_maps(rows);materials_by_product=_material_maps(rows)
    scale=_length_scale(rows); placement_cache={}; material_details_by_product=_material_detail_maps(rows,scale)
    classes={"IFCWALL","IFCWALLSTANDARDCASE","IFCSLAB","IFCBEAM","IFCCOLUMN","IFCROOF","IFCSPACE","IFCBUILDINGELEMENTPROXY","IFCPLATE","IFCMEMBER","IFCFOOTING","IFCDOOR","IFCWINDOW","IFCSTAIR","IFCRAMP","IFCRAILING"}
    groups=[];unsupported=0
    for rid,(ent,args) in rows.items():
        if ent not in classes:continue
        a=_split(args)
        if len(a)<7:continue
        gid=_text(a[0]);name=_text(a[2]) or ent.title();placement=_ref(a[5]);shape=_ref(a[6])
        children=[]
        if shape:
            for item in _shape_items(rows,shape):children.extend(_item_children(rows,item,scale))
        if not children:
            unsupported+=1;continue
        g=Group(name=name);g.adopt(children);g.component=False
        if placement:g.xform=_local_placement_matrix(rows,placement,scale,placement_cache)
        cls="Ifc"+ent[3:].title().replace("Standardcase","StandardCase") if ent.startswith("IFC") else ent
        # Canonical names for the common building elements.
        cls={"IFCWALL":"IfcWall","IFCWALLSTANDARDCASE":"IfcWall","IFCSLAB":"IfcSlab","IFCBEAM":"IfcBeam","IFCCOLUMN":"IfcColumn","IFCROOF":"IfcRoof","IFCSPACE":"IfcSpace","IFCBUILDINGELEMENTPROXY":"IfcBuildingElementProxy","IFCDOOR":"IfcDoor","IFCWINDOW":"IfcWindow","IFCSTAIR":"IfcStair","IFCRAMP":"IfcRamp","IFCRAILING":"IfcRailing"}.get(ent,cls)
        predefined=_text(a[-1]) if a else "NOTDEFINED"
        meta={"class":cls,"name":name,"global_id":gid,"predefined_type":predefined or "NOTDEFINED","engine":"IFC.Imported"}
        tinfo=types_by_product.get(rid) or {}
        if tinfo.get("name"):meta["type_name"]=tinfo["name"]
        cinfo=class_by_product.get(rid) or {}
        if cinfo.get("system"):meta["classification_system"]=cinfo["system"]
        if cinfo.get("code"):meta["classification_code"]=cinfo["code"]
        tref=type_ref_by_product.get(rid)
        matname=materials_by_product.get(rid) or (materials_by_product.get(tref) if tref else None)
        if matname:meta["material_name"]=matname
        detail=material_details_by_product.get(rid) or (material_details_by_product.get(tref) if tref else None) or {}
        if detail.get("kind")=="layerset":
            meta["material_layers"]=copy.deepcopy(detail.get("layers") or []);meta["material_set_name"]=detail.get("name")
        elif detail.get("kind")=="constituentset":meta["material_constituents"]=copy.deepcopy(detail.get("constituents") or [])
        elif detail.get("kind")=="profileset":meta["material_profiles"]=copy.deepcopy(detail.get("profiles") or [])
        merged_psets={}
        if tref and isinstance(psets_by_product.get(tref),dict):merged_psets.update(copy.deepcopy(psets_by_product[tref]))
        if isinstance(psets_by_product.get(rid),dict):merged_psets.update(copy.deepcopy(psets_by_product[rid]))
        if merged_psets:
            meta["property_sets"]=merged_psets
            cp=common_pset(cls)
            if cp and isinstance(merged_psets.get(cp),dict):meta["common"]=copy.deepcopy(merged_psets[cp])
        g.ifc=meta
        g.ext={"opentrace_ifc_import":{"source":str(target),"entity_id":rid,"class":cls,"property_sets":merged_psets,"unit_scale":scale}}
        _restore_opentrace_roundtrip(g,merged_psets)
        groups.append(g)
    project={}
    for _rid,(ent,args) in rows.items():
        if ent in ("IFCPROJECT","IFCSITE","IFCBUILDING"):
            a=_split(args);name=_text(a[2]) if len(a)>2 else ""
            project[{"IFCPROJECT":"name","IFCSITE":"site","IFCBUILDING":"building"}[ent]]=name
    if not groups:
        raise IfcImportError("Nenhum elemento com geometria PolygonalFaceSet, FacetedBrep ou ExtrudedAreaSolid compatível foi encontrado.")
    return {"groups":groups,"project":project,"unsupported":unsupported,"path":str(target),"reader":"OpenTrace STEP","unit_scale":scale}


class AddIfcGroups(Command):
    def __init__(self,groups):self.groups=list(groups);self.index=None
    def do(self,scene):
        if self.index is None:self.index=len(scene.groups)
        at=min(self.index,len(scene.groups))
        for i,g in enumerate(self.groups):
            if g not in scene.groups:scene.groups.insert(at+i,g)
        scene.version+=1
    def undo(self,scene):
        for g in self.groups:
            if g in scene.groups:scene.groups.remove(g)
            scene.selection.discard(g)
        scene.version+=1


class ReplaceWithIfcGroups(Command):
    def __init__(self,groups):self.groups=list(groups);self.before=None
    def do(self,scene):
        if self.before is None:self.before=list(scene.groups)
        scene.groups[:]=list(self.groups);scene.selection.clear();scene.version+=1
    def undo(self,scene):scene.groups[:]=list(self.before or []);scene.selection.clear();scene.version+=1


def import_ifc(app,path,*,mode="import",linked=False):
    result=parse_ifc(path)
    for g in result["groups"]:
        meta=g.ext.setdefault("opentrace_ifc_import",{});meta["linked"]=bool(linked);meta["mode"]=mode
    cmd=ReplaceWithIfcGroups(result["groups"]) if mode=="open" else AddIfcGroups(result["groups"])
    app.viewport.history.execute(cmd)
    if app.viewport.history.last_error:raise IfcImportError(app.viewport.history.last_error)
    app.viewport.notify_scene_changed()
    return result
