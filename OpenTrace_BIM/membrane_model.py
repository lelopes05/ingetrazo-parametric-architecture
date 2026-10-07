# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenTrace Membrane — a lightweight architectural control surface.

The boundary is authoritative. Curved edges are real boundary curves and the
skin is only an interpolation between them — it never solves a separate
"cloth" shape.  Four-sided membranes use a Coons patch (CAD-style surface
through four edge curves); other polygons use a conservative triangulated fill.
Internal edges are soft, so the object behaves like a simple architectural
control mesh rather than a structural membrane solver.
"""
from __future__ import annotations

import copy, math
from PySide6.QtGui import QVector3D
from core.group import Group
from core.mesh import Mesh, Edge
from core.history import Command

KEY = "arquitetura_parametrica"
SCHEMA = 5
MIN_EDGE = 1.0e-6

class MembraneError(ValueError): pass

def _key(p,tol=1e-6): return (round(float(p.x())/tol),round(float(p.y())/tol),round(float(p.z())/tol))

def _point(raw):
    return QVector3D(raw) if hasattr(raw,"x") else QVector3D(float(raw[0]),float(raw[1]),float(raw[2]))

def _points3(raw):
    out=[]
    for q in raw or ():
        try:p=_point(q)
        except Exception:continue
        if all(math.isfinite(v) for v in (p.x(),p.y(),p.z())):out.append(p)
    return out

def _world_edge_points(edge):
    a=getattr(edge,"v0",None) or getattr(edge,"a",None);b=getattr(edge,"v1",None) or getattr(edge,"b",None)
    if a is None or b is None:raise MembraneError("Aresta sem extremos válidos.")
    return QVector3D(getattr(a,"position",a)),QVector3D(getattr(b,"position",b))

def selected_boundary(scene):
    segments=[];seen=set()
    for item in list(getattr(scene,"selection",()) or ()):
        if isinstance(item,Edge):edges=[item]
        else:
            group=getattr(item,"owner",None) or item;mesh=getattr(group,"mesh",None)
            if mesh is None:continue
            try:
                from core.group import world_mesh
                mesh=world_mesh(group)
            except Exception:pass
            edges=list(getattr(mesh,"edges",()) or ())
        for e in edges:
            try:a,b=_world_edge_points(e)
            except Exception:continue
            if (b-a).length()<=MIN_EDGE:continue
            ka,kb=_key(a),_key(b);sig=tuple(sorted((ka,kb)))
            if sig in seen:continue
            seen.add(sig);segments.append((ka,kb,a,b))
    if len(segments)<3:raise MembraneError("Selecione pelo menos três arestas formando um contorno fechado.")
    adj,pos={},{}
    for ka,kb,a,b in segments:adj.setdefault(ka,[]).append(kb);adj.setdefault(kb,[]).append(ka);pos[ka],pos[kb]=a,b
    if any(len(v)!=2 for v in adj.values()):raise MembraneError("A seleção precisa formar um único contorno fechado sem ramificações.")
    start=next(iter(adj));loop=[start];prev=None;cur=start
    for _ in range(len(adj)+2):
        nxts=adj[cur];nxt=nxts[0] if nxts[0]!=prev else nxts[1]
        if nxt==start:break
        if nxt in loop:raise MembraneError("O contorno selecionado se cruza ou contém mais de um loop.")
        loop.append(nxt);prev,cur=cur,nxt
    if len(loop)!=len(adj):raise MembraneError("Selecione somente um contorno fechado por vez.")
    return [QVector3D(pos[k]) for k in loop]

def _normal(points):
    n=QVector3D()
    for a,b in zip(points,points[1:]+points[:1]):
        n+=QVector3D((a.y()-b.y())*(a.z()+b.z()),(a.z()-b.z())*(a.x()+b.x()),(a.x()-b.x())*(a.y()+b.y()))
    if n.length()<1e-9:
        # Non-planar/skin boundaries can have cancelling Newell terms. Use the
        # strongest triangle around the centroid instead of rejecting them.
        c=sum((QVector3D(q) for q in points),QVector3D())/float(len(points));best=QVector3D()
        for i,a in enumerate(points):
            v=QVector3D.crossProduct(a-c,points[(i+1)%len(points)]-c)
            if v.lengthSquared()>best.lengthSquared():best=v
        n=best
    if n.length()<1e-9:raise MembraneError("O contorno não define uma superfície válida.")
    n.normalize();return n if n.z()>=0 else -n

def _centre(points):return sum((QVector3D(q) for q in points),QVector3D())/float(len(points))

def validate(values,edge_count=None):
    src=values or {}
    # 0.12.7 deliberately retires the experimental tension solver.  Old files
    # that stored tensioned edges remain readable, but they reopen as the same
    # neutral smooth control surface instead of deforming unpredictably.
    mode="relaxed"
    div=max(2,min(32,int(src.get("divisions",src.get("smoothness",5)) or 5)))
    n=max(0,int(edge_count if edge_count is not None else len(src.get("edge_modes",()) or ())))
    ch=list(src.get("edge_curve_h",()) or ());cv=list(src.get("edge_curve_v",()) or ())
    if len(ch)!=n:ch=[0.0]*n
    if len(cv)!=n:cv=[0.0]*n
    ch=[float(x) if math.isfinite(float(x)) else 0.0 for x in ch]
    cv=[float(x) if math.isfinite(float(x)) else 0.0 for x in cv]
    try:th=max(0.0,float(src.get("thickness",0.0) or 0.0))
    except Exception:th=0.0
    structure=str(src.get("structure") or "simple")
    structure=structure if structure in ("simple","composite") else "simple"
    layers=copy.deepcopy(src.get("layers",[])) if isinstance(src.get("layers"),list) else []
    if structure=="composite" and layers:
        total=0.0;norm=[]
        for x in layers:
            if not isinstance(x,dict):continue
            try:t=max(0.0001,float(x.get("thickness",0.0)))
            except Exception:continue
            q=copy.deepcopy(x);q["thickness"]=t;norm.append(q);total+=t
        layers=norm
        if total>0:th=total
    return {
        "mode":mode,"divisions":div,"tension_strength":0.0,
        "edge_modes":["rigid"]*n,"edge_curve_h":ch,"edge_curve_v":cv,
        "mesh_points":_points3(src.get("mesh_points",())),
        "mesh_uvs":[list(x[:2]) for x in (src.get("mesh_uvs",()) or ()) if isinstance(x,(list,tuple)) and len(x)>=2],
        "anchor_loops":[],
        "thickness":th,"structure":structure,"layers":layers,
        "material_name":src.get("material_name")
    }


def _edge_frame(a,b):
    d=QVector3D(b)-QVector3D(a)
    plan=QVector3D(d.x(),d.y(),0.0)
    L=math.hypot(plan.x(),plan.y())
    perp=QVector3D(-plan.y()/L,plan.x()/L,0.0) if L>1e-9 else QVector3D()
    return d,perp


def edge_point(a,b,h=0.0,v=0.0,t=0.5):
    """Point on one OpenTrace membrane control edge.

    The curve is a lightweight sinusoidal bow whose ends remain *exactly* on
    the control vertices.  Horizontal and vertical bows are independent, so a
    single border may curve in plan, elevation, or both without creating a
    separate NURBS object.
    """
    a,b=QVector3D(a),QVector3D(b);t=max(0.0,min(1.0,float(t)))
    _d,perp=_edge_frame(a,b);q=a*(1.0-t)+b*t;s=math.sin(math.pi*t)
    q+=perp*(float(h)*s);q.setZ(q.z()+float(v)*s)
    return q


def boundary_edge_polyline(boundary,values,index,steps=None):
    """Actual displayed/picked polyline for one authoritative boundary edge."""
    control=[QVector3D(q) for q in boundary]
    p=validate(values,len(control));i=int(index)%len(control)
    h=float(p["edge_curve_h"][i]);v=float(p["edge_curve_v"][i])
    curved=abs(h)>1e-9 or abs(v)>1e-9
    n=(max(4,min(32,int(p["divisions"])*2)) if curved else 1) if steps is None else max(1,int(steps))
    return [edge_point(control[i],control[(i+1)%len(control)],h,v,j/float(n)) for j in range(n+1)]


def sampled_boundary_edges(points,p):
    """``[(edge_index, [sample...], rigid), ...]`` preserving true curves."""
    out=[]
    for i in range(len(points)):
        poly=boundary_edge_polyline(points,p,i)
        out.append((i,poly,p["edge_modes"][i]=="rigid"))
    return out


def _sample_boundary(points,p):
    """Sample every real boundary curve once, retaining constraints.

    Returns ``(vertices, edge_of_vertex, edge_polylines)``.  Consecutive edge
    polylines share the original corner vertex; the final repeated first point
    is omitted from the master ring.
    """
    ring=[];edge_of=[];polys=[]
    for i,poly,_rigid in sampled_boundary_edges(points,p):
        poly=[QVector3D(q) for q in poly]
        polys.append(poly)
        take=poly[:-1]
        ring.extend(take);edge_of.extend([i]*len(take))
    return ring,edge_of,polys

def _plane_basis(points):
    from core.triangulate import plane_axes
    n=_normal(points);u,v=plane_axes(n);o=_centre(points)
    def xy(q):
        d=QVector3D(q)-o;return QVector3D.dotProduct(d,u),QVector3D.dotProduct(d,v)
    return n,o,u,v,xy

def _inside_tri(pt,a,b,c,eps=1e-9):
    cr=lambda p,q,r:(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    x=(cr(a,b,pt),cr(b,c,pt),cr(c,a,pt));return not(any(v<-eps for v in x) and any(v>eps for v in x))

def _triangles(boundary,controls):
    """Triangulate in a stable 2D parameter plane while retaining 3D controls."""
    from core.triangulate import earcut
    _n,_o,_u,_v,xy=_plane_basis(boundary)
    pts=[QVector3D(q) for q in boundary];p2=[xy(q) for q in pts]
    idx_tris=earcut(p2)
    tris=[list(t) for t in idx_tris]
    for q in controls:
        q=QVector3D(q);q2=xy(q);hit=None
        for ti,t in enumerate(tris):
            if _inside_tri(q2,p2[t[0]],p2[t[1]],p2[t[2]]):hit=ti;break
        if hit is None:continue
        if min((q-pts[i]).length() for i in tris[hit])<MIN_EDGE*5:continue
        a,b,c=tris.pop(hit);k=len(pts);pts.append(q);p2.append(q2);tris.extend(([a,b,k],[b,c,k],[c,a,k]))
    return pts,[tuple(t) for t in tris]

def _subdivide(verts,tris,fixed,rounds,constraint_edges=None):
    """Triangle 1→4 subdivision while preserving only *real* constraints.

    Older builds marked a midpoint fixed whenever both of its end vertices were
    fixed.  That accidentally froze triangulation diagonals joining two border
    vertices and produced the folded/fan-like skins seen in 0.12.5.  Here only
    explicit boundary/anchor edges create fixed midpoints.
    """
    verts=[QVector3D(q) for q in verts];fixed=list(fixed);tris=list(tris)
    constraints={tuple(sorted(e)) for e in (constraint_edges or ())}
    for _ in range(max(0,int(rounds))):
        mids={};new=[];new_constraints=set()
        def mid(a,b):
            key=(min(a,b),max(a,b))
            if key in mids:return mids[key]
            idx=len(verts);verts.append((verts[a]+verts[b])*.5)
            is_constraint=key in constraints
            fixed.append(bool(is_constraint and fixed[a] and fixed[b]))
            mids[key]=idx
            if is_constraint:
                new_constraints.add(tuple(sorted((a,idx))))
                new_constraints.add(tuple(sorted((idx,b))))
            return idx
        for a,b,c in tris:
            ab,bc,ca=mid(a,b),mid(b,c),mid(c,a)
            new.extend(((a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)))
        tris=new;constraints=new_constraints
    return verts,tris,fixed,constraints

def _relax(verts,tris,fixed,strength,iterations):
    verts=[QVector3D(q) for q in verts];adj=[set() for _ in verts]
    for a,b,c in tris:
        adj[a].update((b,c));adj[b].update((a,c));adj[c].update((a,b))
    lam=max(0.0,min(.65,float(strength)))
    for _ in range(max(1,int(iterations))):
        nxt=[QVector3D(q) for q in verts]
        for i,q in enumerate(verts):
            if fixed[i] or not adj[i]:continue
            avg=sum((verts[j] for j in adj[i]),QVector3D())/float(len(adj[i]));nxt[i]=q+(avg-q)*lam
        verts=nxt
    return verts

def _coons_point(control,p,u,vv):
    p0,p1,p2,p3=[QVector3D(q) for q in control]
    h=p["edge_curve_h"];v=p["edge_curve_v"]
    c0=edge_point(p0,p1,h[0],v[0],u)
    c1=edge_point(p2,p3,h[2],v[2],1.0-u)  # p3 -> p2
    d0=edge_point(p3,p0,h[3],v[3],1.0-vv) # p0 -> p3
    d1=edge_point(p1,p2,h[1],v[1],vv)
    bil=(p0*((1-u)*(1-vv)) + p1*(u*(1-vv)) + p2*(u*vv) + p3*((1-u)*vv))
    return c0*(1-vv)+c1*vv+d0*(1-u)+d1*u-bil


def surface_uv(boundary,values,point):
    """Approximate the (u,v) on a four-sided membrane under a world point."""
    control=[QVector3D(q) for q in boundary]
    if len(control)!=4:return None
    p=validate(values,4);q=QVector3D(point);best=(float("inf"),.5,.5)
    # 33x33 is cheap for an editing click and stable enough to remember the
    # parametric location while the user later moves the control vertex.
    for j in range(33):
        vv=j/32.0
        for i in range(33):
            u=i/32.0;c=_coons_point(control,p,u,vv);d=(c-q).lengthSquared()
            if d<best[0]:best=(d,u,vv)
    return [best[1],best[2]]


def _smooth_control_displacements(us,vs,fixed_disp,iterations=48):
    """Harmonic displacement field with boundary + authored controls fixed."""
    nu,nv=len(us),len(vs);disp=[[QVector3D() for _ in range(nu)] for __ in range(nv)];fixed=set()
    for j in range(nv):
        fixed.add((j,0));fixed.add((j,nu-1))
    for i in range(nu):
        fixed.add((0,i));fixed.add((nv-1,i))
    for (j,i),d in fixed_disp.items():disp[j][i]=QVector3D(d);fixed.add((j,i))
    for _ in range(max(1,int(iterations))):
        nxt=[[QVector3D(q) for q in row] for row in disp]
        for j in range(1,nv-1):
            for i in range(1,nu-1):
                if (j,i) in fixed:continue
                nxt[j][i]=(disp[j-1][i]+disp[j+1][i]+disp[j][i-1]+disp[j][i+1])*.25
        disp=nxt
    return disp


def _coons_patch(control,p):
    """Structured surface through four authoritative boundary curves.

    Internal user points are ordinary mesh-control vertices, not anchors or a
    cloth solver. Their remembered (u,v) locations are inserted into the grid;
    moving one fixes that grid vertex and a harmonic displacement field deforms
    the surrounding skin while every border remains exactly on its control edge.
    """
    if len(control)!=4:return None
    n=max(2,min(32,int(p.get("divisions",5))))
    controls=list(p.get("mesh_points",()) or ());uvs=list(p.get("mesh_uvs",()) or ())
    # Migrate old point-only records by finding their parameter position on the
    # undeformed Coons surface. This is only needed once; the record later saves UVs.
    while len(uvs)<len(controls):
        uv=surface_uv(control,{**p,"mesh_points":[],"mesh_uvs":[]},controls[len(uvs)]) or [.5,.5]
        uvs.append(uv)
    base=[i/float(n) for i in range(n+1)]
    us=sorted(set(base+[max(0.0,min(1.0,float(uv[0]))) for uv in uvs]))
    vs=sorted(set(base+[max(0.0,min(1.0,float(uv[1]))) for uv in uvs]))
    def index_of(vals,x):return min(range(len(vals)),key=lambda i:abs(vals[i]-x))
    verts=[]
    for vv in vs:
        for u in us:verts.append(_coons_point(control,p,u,vv))
    fixed_disp={}
    for q,uv in zip(controls,uvs):
        u=max(0.0,min(1.0,float(uv[0])));vv=max(0.0,min(1.0,float(uv[1])))
        i=index_of(us,u);j=index_of(vs,vv);k=j*len(us)+i
        fixed_disp[(j,i)]=QVector3D(q)-verts[k]
    if fixed_disp:
        field=_smooth_control_displacements(us,vs,fixed_disp,iterations=max(24,n*5))
        for j in range(len(vs)):
            for i in range(len(us)):
                verts[j*len(us)+i]+=field[j][i]
    tris=[];row=len(us)
    for j in range(len(vs)-1):
        for i in range(len(us)-1):
            a=j*row+i;b=a+1;d=(j+1)*row+i;c=d+1
            if (i+j)&1:tris.extend(((a,b,d),(b,c,d)))
            else:tris.extend(((a,b,c),(a,c,d)))
    return verts,tris,uvs

def _copy_face_look(template):
    if template is None:return {}
    try:
        for child in list(getattr(template,"children",()) or ()) or [template]:
            for f in getattr(getattr(child,"mesh",None),"faces",()):return copy.deepcopy(dict(getattr(f,"attrs",{}) or {}))
    except Exception:pass
    return {}

def _vertex_normals(verts,tris):
    ns=[QVector3D() for _ in verts]
    for a,b,c in tris:
        n=QVector3D.crossProduct(verts[b]-verts[a],verts[c]-verts[a])
        if n.lengthSquared()<1e-18:continue
        for i in (a,b,c):ns[i]+=n
    fallback=_normal(verts[:min(len(verts),max(3,len(verts)))]) if len(verts)>=3 else QVector3D(0,0,1)
    return [n.normalized() if n.length()>1e-9 else QVector3D(fallback) for n in ns]

def _boundary_edges(tris):
    count={}
    for a,b,c in tris:
        for u,v in ((a,b),(b,c),(c,a)):
            k=(min(u,v),max(u,v));count[k]=count.get(k,0)+1
    return [k for k,n in count.items() if n==1]

def _add_skin(mesh,verts,tris,look,layer_index=0):
    for a,b,c in tris:
        try:f=mesh.add_face([verts[a],verts[b],verts[c]])
        except Exception:continue
        f.attrs.update(copy.deepcopy(look));f.attrs["pa_face"]="skin";f.attrs["pa_layer"]=layer_index

def _add_shell_layer(mesh,verts,tris,normals,z0,z1,look,layer_index):
    lo=[q+normals[i]*z0 for i,q in enumerate(verts)];hi=[q+normals[i]*z1 for i,q in enumerate(verts)]
    for a,b,c in tris:
        for face in ([lo[c],lo[b],lo[a]],[hi[a],hi[b],hi[c]]):
            try:f=mesh.add_face(face);f.attrs.update(copy.deepcopy(look));f.attrs["pa_face"]="skin";f.attrs["pa_layer"]=layer_index
            except Exception:pass
    for a,b in _boundary_edges(tris):
        try:f=mesh.add_face([lo[a],lo[b],hi[b],hi[a]]);f.attrs.update(copy.deepcopy(look));f.attrs["pa_face"]="edge";f.attrs["pa_layer"]=layer_index
        except Exception:pass

def make_membrane(boundary,values,template=None):
    """Build a deformable architectural surface from its control cage.

    No gravity/tension solver runs here. The boundary curves are immutable
    interpolation constraints. A four-edge cage gets a structured Coons patch;
    arbitrary polygons are filled conservatively and explicit internal points
    simply split that fill as user-authored mesh controls.
    """
    control=[QVector3D(q) for q in boundary]
    if len(control)<3:raise MembraneError("A membrana precisa de ao menos três vértices.")
    for a,b in zip(control,control[1:]+control[:1]):
        if (b-a).length()<=MIN_EDGE:raise MembraneError("Dois vértices da membrana estão próximos demais.")
    p=validate(values,len(control))
    patch=_coons_patch(control,p)
    if patch is not None:
        verts,tris,mesh_uvs=patch
        p["mesh_uvs"]=mesh_uvs
    else:
        sampled,_edge_of,_edge_polys=_sample_boundary(control,p)
        verts,tris=_triangles(sampled,list(p["mesh_points"]))
    if not tris:raise MembraneError("Não foi possível gerar a superfície da membrana.")

    mesh=Mesh();look=_copy_face_look(template)
    if p["thickness"]<=1e-8:
        _add_skin(mesh,verts,tris,look)
    else:
        normals=_vertex_normals(verts,tris)
        if p["structure"]=="composite" and p["layers"]:
            total=sum(float(x.get("thickness",0.0)) for x in p["layers"]);cursor=-total*.5
            for i,layer in enumerate(p["layers"]):
                t=float(layer.get("thickness",0.0));_add_shell_layer(mesh,verts,tris,normals,cursor,cursor+t,look,i);cursor+=t
        else:_add_shell_layer(mesh,verts,tris,normals,-p["thickness"]*.5,p["thickness"]*.5,look,0)
    for e in getattr(mesh,"edges",()):
        if len(getattr(e,"faces",()))==2:
            e.soft=True
            try:e.hidden=True
            except Exception:pass
    g=Group(mesh=mesh,name=getattr(template,"name",None) or "Membrana");g.component=False
    if template is not None:
        g.layer=getattr(template,"layer",None);g.material=copy.deepcopy(getattr(template,"material",None));g.ifc=copy.deepcopy(getattr(template,"ifc",None))
    g.ext=copy.deepcopy(getattr(template,"ext",None) or {})
    g.ext[KEY]={"kind":"membrane","schema":5,"mode":"relaxed","divisions":p["divisions"],"tension_strength":0.0,
                "boundary":[[q.x(),q.y(),q.z()] for q in control],"edge_modes":["rigid"]*len(control),"edge_curve_h":list(p["edge_curve_h"]),"edge_curve_v":list(p["edge_curve_v"]),
                "mesh_points":[[q.x(),q.y(),q.z()] for q in p["mesh_points"]],"mesh_uvs":copy.deepcopy(p.get("mesh_uvs",[])),"anchor_loops":[],
                "thickness":p["thickness"],"structure":p["structure"],"layers":copy.deepcopy(p["layers"]),"material_name":p.get("material_name")}
    return g

def read_membrane(group):
    ext=getattr(group,"ext",None) or {};rec=ext.get(KEY) if isinstance(ext,dict) else None
    if not isinstance(rec,dict) or rec.get("kind")!="membrane":raise MembraneError("O objeto selecionado não é uma membrana OpenTrace.")
    boundary=[QVector3D(*q) for q in rec.get("boundary",())];return boundary,validate(rec,len(boundary))

def with_boundary(group,boundary,**updates):
    _old,p=read_membrane(group);vals=copy.deepcopy(p);vals.update(updates);return make_membrane(boundary,vals,template=group)

def insert_boundary_vertex(boundary,values,edge_index,point,t=None):
    pts=[QVector3D(q) for q in boundary];p=validate(values,len(pts));i=int(edge_index)%len(pts)
    a,b=pts[i],pts[(i+1)%len(pts)];q=QVector3D(point)
    if t is None:
        # Approximate the curve parameter by a dense closest-point sample.
        best=(1e99,.5,q)
        for k in range(65):
            tt=k/64.0;qq=edge_point(a,b,p["edge_curve_h"][i],p["edge_curve_v"][i],tt);d=(qq-q).lengthSquared()
            if d<best[0]:best=(d,tt,qq)
        t=best[1];q=best[2]
    t=max(.001,min(.999,float(t)))
    if (q-a).length()<MIN_EDGE or (q-b).length()<MIN_EDGE:raise MembraneError("O novo vértice está muito perto de uma extremidade.")
    # Fit the same lightweight edge-curve model independently to each half at
    # its midpoint, so adding a vertex does not visibly flatten the old curve.
    old_h=float(p["edge_curve_h"][i]);old_v=float(p["edge_curve_v"][i])
    def half_params(x0,x1,ta,tb):
        tm=(ta+tb)*.5;orig=edge_point(a,b,old_h,old_v,tm);mid=(x0+x1)*.5
        _d,perp=_edge_frame(x0,x1);dh=orig-mid
        hh=QVector3D.dotProduct(dh,perp) if perp.lengthSquared()>1e-12 else 0.0
        vv=dh.z()
        return float(hh),float(vv)
    h0,v0=half_params(a,q,0.0,t);h1,v1=half_params(q,b,t,1.0)
    pts=pts[:i+1]+[q]+pts[i+1:];mode=p["edge_modes"][i]
    p["edge_modes"]=p["edge_modes"][:i]+[mode,mode]+p["edge_modes"][i+1:]
    p["edge_curve_h"]=p["edge_curve_h"][:i]+[h0,h1]+p["edge_curve_h"][i+1:]
    p["edge_curve_v"]=p["edge_curve_v"][:i]+[v0,v1]+p["edge_curve_v"][i+1:]
    return pts,p

def chamfer_boundary(boundary,index,ratio=.16,fillet=False):
    pts=[QVector3D(q) for q in boundary];n=len(pts);i=int(index)%n;prev,cur,nxt=pts[(i-1)%n],pts[i],pts[(i+1)%n];l0,l1=(cur-prev).length(),(nxt-cur).length();cut=max(MIN_EDGE,min(l0,l1)*max(.03,min(.40,float(ratio))))
    a=cur+(prev-cur)*(cut/max(l0,MIN_EDGE));b=cur+(nxt-cur)*(cut/max(l1,MIN_EDGE));repl=[a,b]
    if fillet:
        repl=[a*((1-t)*(1-t))+cur*(2*(1-t)*t)+b*(t*t) for t in (0,.25,.5,.75,1)]
    return pts[:i]+repl+pts[i+1:]

class CreateMembrane(Command):
    def __init__(self,group):self.group=group;self.index=None
    def do(self,scene):
        if self.group in scene.groups:raise MembraneError("A membrana já está no documento.")
        if self.index is None:self.index=len(scene.groups)
        scene.groups.insert(min(self.index,len(scene.groups)),self.group);scene.version+=1
    def undo(self,scene):
        if self.group in scene.groups:scene.groups.remove(self.group)
        scene.selection.discard(self.group);scene.version+=1

class EditMembrane(Command):
    """Swap full geometry + parameter record atomically; no residual topology."""
    def __init__(self,group,values,boundary=None):
        old_boundary,_old=read_membrane(group);self.group=group;self.before_mesh=group.mesh;self.before_children=list(getattr(group,"children",()) or ());self.before_ext=copy.deepcopy(group.ext);self.before_ifc=copy.deepcopy(getattr(group,"ifc",None));self.after_group=make_membrane(boundary or old_boundary,values,template=group)
    def _apply(self,scene,mesh,children,ext,ifc):
        self.group.mesh=mesh;self.group.children=list(children);self.group.ext=copy.deepcopy(ext);self.group.ifc=copy.deepcopy(ifc);scene.version+=1
    def do(self,scene):self._apply(scene,self.after_group.mesh,getattr(self.after_group,"children",()),self.after_group.ext,self.after_group.ifc)
    def undo(self,scene):self._apply(scene,self.before_mesh,self.before_children,self.before_ext,self.before_ifc)
