# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure 2D geometry for free polygon openings in parametric wall elevations.

Coordinates are (station along host reference path, elevation above the
local base profile), in metres.  No Qt/scene imports or side effects.
Only straight polygon edges are implemented; unsupported curved edges must
be rejected by the caller rather than silently approximated.
"""
from __future__ import annotations

import math

EPS = 1.0e-8


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _intersect(a, b, c, d):
    """True if closed segments intersect (including collinear overlap)."""
    def between(p, q, r):
        return min(p, r)-EPS <= q <= max(p, r)+EPS
    p = _cross(a, b, c)
    q = _cross(a, b, d)
    r = _cross(c, d, a)
    t = _cross(c, d, b)
    if (p > EPS and q < -EPS or p < -EPS and q > EPS) and (
            r > EPS and t < -EPS or r < -EPS and t > EPS):
        return True
    for value, x, y, z in ((p, a, c, b), (q, a, d, b),
                           (r, c, a, d), (t, c, b, d)):
        if abs(value) <= EPS and between(x[0], y[0], z[0]) and between(x[1], y[1], z[1]):
            return True
    return False


def normalize_polygon(raw, length, margin=0.02, *, allow_outside=False):
    """Validate an authored polygon, without silently resizing its vertices.

    The creation tool still requires points inside the wall. Existing cutters
    may extend beyond a host after the user recedes that host: these continue
    to be valid authored geometry and are clipped only during meshing.
    """
    if not isinstance(raw, (tuple, list)) or len(raw) < 3:
        raise ValueError("A abertura precisa de ao menos três vértices.")
    if not math.isfinite(float(length)) or length <= 2*margin:
        raise ValueError("Comprimento da parede insuficiente.")
    pts = []
    for raw_point in raw:
        if not isinstance(raw_point, (tuple, list)) or len(raw_point) != 2:
            raise ValueError("Vértice inválido na abertura.")
        try:
            x, z = float(raw_point[0]), float(raw_point[1])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Coordenadas inválidas na abertura.") from exc
        if not math.isfinite(x) or not math.isfinite(z):
            raise ValueError("Coordenadas não finitas na abertura.")
        if not allow_outside and (x <= margin or x >= length-margin):
            raise ValueError("A abertura deve respeitar os extremos da parede.")
        if z < 0:
            raise ValueError("A altura da abertura não pode ficar abaixo da base.")
        pts.append((x, z))
    if pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        raise ValueError("Abertura poligonal degenerada.")
    n = len(pts)
    area = sum(pts[i][0]*pts[(i+1)%n][1] -
               pts[(i+1)%n][0]*pts[i][1] for i in range(n))/2.0
    if abs(area) <= EPS:
        raise ValueError("A abertura precisa delimitar uma área.")
    for i in range(n):
        if math.dist(pts[i], pts[(i+1)%n]) < 0.001:
            raise ValueError("A abertura precisa de arestas com pelo menos 1 mm.")
        before, current, after = pts[(i-1)%n], pts[i], pts[(i+1)%n]
        ux, uz = current[0]-before[0], current[1]-before[1]
        vx, vz = after[0]-current[0], after[1]-current[1]
        if abs(_cross(before, current, after)) <= EPS and ux*vx+uz*vz < -EPS:
            raise ValueError("Arestas adjacentes não podem voltar sobre o mesmo trecho.")
        for j in range(i+1, n):
            if j == i+1 or (i == 0 and j == n-1):
                continue
            if _intersect(pts[i], pts[(i+1)%n], pts[j], pts[(j+1)%n]):
                raise ValueError("A abertura não pode cruzar suas próprias arestas.")
    return [[x, z] for x, z in pts]



def clip_polygon_stations(points, length):
    """Effective intersection of a persistent 2D cutter and [0, host_length].

    Clipped boundary edges are VIRTUAL, not reveal faces: wall endpoint caps
    remain open where the cutter intersects them. The authored points never
    change, and a fully external opening returns no physical polygon.
    """
    polygon=[list(map(float,pt)) for pt in points]
    for bound,keep_above in ((0.0,True),(float(length),False)):
        if not polygon:
            break
        result=[]
        previous=polygon[-1]
        for current in polygon:
            inside_prev=(previous[0]>=bound-EPS if keep_above
                         else previous[0]<=bound+EPS)
            inside_cur=(current[0]>=bound-EPS if keep_above
                        else current[0]<=bound+EPS)
            if inside_prev != inside_cur:
                dx=current[0]-previous[0]
                if abs(dx)>EPS:
                    t=(bound-previous[0])/dx
                    result.append([bound,previous[1]+t*(current[1]-previous[1])])
            if inside_cur:
                result.append(list(current))
            previous=current
        polygon=[]
        for point in result:
            if not polygon or math.dist(polygon[-1],point)>EPS:
                polygon.append(point)
        if len(polygon)>1 and math.dist(polygon[0],polygon[-1])<=EPS:
            polygon.pop()
    if len(polygon)<3:
        return []
    area=sum(polygon[i][0]*polygon[(i+1)%len(polygon)][1]-
             polygon[(i+1)%len(polygon)][0]*polygon[i][1]
             for i in range(len(polygon)))*.5
    return polygon if abs(area)>EPS else []


def edge_height(points, index, station):
    a, b = points[index], points[(index+1) % len(points)]
    if abs(b[0]-a[0]) <= EPS:
        return (a[1]+b[1])*0.5
    return a[1] + (b[1]-a[1])*(station-a[0])/(b[0]-a[0])


def scan_edges(points, station):
    """Crossings for a station strictly between polygon vertex stations."""
    hits = []
    for i, (a, b) in enumerate(zip(points, points[1:]+points[:1])):
        lo, hi = sorted((a[0], b[0]))
        if lo < station < hi:
            hits.append((edge_height(points, i, station), i))
    return sorted(hits)


def contains(points, station, elevation):
    intersections = scan_edges(points, station)
    return sum(z > elevation for z, _ in intersections) % 2 == 1


def cut_stations(points, length, base_profile, top_profile):
    """Stations for polygon corners and crossings with the sloping wall head."""
    heights = [float(top_profile[i])-float(base_profile[i]) for i in range(2)]
    if not all(math.isfinite(v) and v > 0 for v in heights):
        raise ValueError("Perfil de parede inválido.")
    h0, h1 = heights
    stations = [p[0] for p in points]
    for a, b in zip(points, points[1:]+points[:1]):
        dx, dz = b[0]-a[0], b[1]-a[1]
        if abs(dx) < EPS:
            continue
        slope = (h1-h0)/length
        den = dz-slope*dx
        if abs(den) <= EPS:
            continue
        t = (h0+slope*a[0]-a[1])/den
        if EPS < t < 1-EPS:
            stations.append(a[0]+t*dx)
    return sorted(set(round(x, 10) for x in stations))


def clip_to_wall(a, b, length, base_profile, top_profile):
    """Clip a polygon edge to 0 <= elevation <= local wall height.

    Returns None for an edge outside the host.  Segment end coordinates
    are in local (station, elevation) coordinates.
    """
    h0 = float(top_profile[0])-float(base_profile[0])
    h1 = float(top_profile[1])-float(base_profile[1])
    slope = (h1-h0)/length
    a = tuple(map(float, a))
    b = tuple(map(float, b))
    dx, dz = b[0]-a[0], b[1]-a[1]
    lower, upper = 0.0, 1.0
    # Affine inequalities g(t) >= 0 for base and top clearance.
    for v0, dv in ((a[1], dz),
                   (h0+slope*a[0]-a[1], slope*dx-dz)):
        if abs(dv) <= EPS:
            if v0 < -EPS:
                return None
        else:
            limit = -v0/dv
            if dv > 0:
                lower = max(lower, limit)
            else:
                upper = min(upper, limit)
    if upper-lower <= EPS:
        return None
    return ((a[0]+dx*lower, a[1]+dz*lower),
            (a[0]+dx*upper, a[1]+dz*upper))


def project_to_edge(points, edge_index, point):
    """Nearest point on a straight polygon edge and its interpolation factor."""
    a = points[edge_index % len(points)]
    b = points[(edge_index+1) % len(points)]
    dx, dz = b[0]-a[0], b[1]-a[1]
    size2 = dx*dx+dz*dz
    if size2 <= EPS*EPS:
        raise ValueError("Aresta degenerada.")
    u = max(0.0, min(1.0,
        ((point[0]-a[0])*dx+(point[1]-a[1])*dz)/size2))
    return [a[0]+u*dx, a[1]+u*dz], u


def insert_vertex(points, edge_index, point, length, *, allow_outside=False):
    """Split a polygon edge at the projected location."""
    n = len(points)
    if n < 3:
        raise ValueError("Abertura sem polígono válido.")
    index = edge_index % n
    projected, u = project_to_edge(points, index, point)
    if not 0.01 < u < 0.99:
        raise ValueError("Insira o vértice afastado das extremidades da aresta.")
    updated = [list(p) for p in points]
    updated.insert(index+1, projected)
    return normalize_polygon(updated, length, allow_outside=allow_outside)


def move_vertex(points, vertex_index, point, length, *, allow_outside=False):
    """Move exactly one local vertex and revalidate the boundary."""
    updated = [list(p) for p in points]
    updated[vertex_index % len(updated)] = list(point)
    return normalize_polygon(updated, length, allow_outside=allow_outside)


def move_edge(points, edge_index, delta, length, *, allow_outside=False):
    """Translate one edge perpendicular to itself, moving both endpoints."""
    n = len(points)
    index = edge_index % n
    a, b = points[index], points[(index+1) % n]
    dx, dz = b[0]-a[0], b[1]-a[1]
    edge_length = math.hypot(dx, dz)
    if edge_length <= EPS:
        raise ValueError("Aresta degenerada.")
    normal = (-dz/edge_length, dx/edge_length)
    magnitude = delta[0]*normal[0]+delta[1]*normal[1]
    updated = [list(p) for p in points]
    for i in (index, (index+1) % n):
        updated[i] = [points[i][0]+normal[0]*magnitude,
                      points[i][1]+normal[1]*magnitude]
    return normalize_polygon(updated, length, allow_outside=allow_outside)



def rectangle_to_polygon(opening, length):
    """Editable wall-elevation corners for a free rectangular void.

    Converting at the FIRST real vertex/edge commit is atomic with the edit.
    It never converts live IfcDoor/IfcWindow fills, which need their own
    parametric width/sill/height controls to stay hosted.
    """
    if opening.get("source_id") or opening.get("fill"):
        raise ValueError("Esquadria hospedada não pode ser convertida em vão livre.")
    position=float(opening["position"])
    half=float(opening["width"])*.5
    sill=float(opening["sill"])
    top=sill+float(opening["height"])
    return normalize_polygon([
        [position-half,sill],[position+half,sill],
        [position+half,top],[position-half,top]],
        length,allow_outside=True)


def translate_polygon(points, delta, length, *, allow_outside=True):
    """Move the whole authored opening in wall station/elevation coordinates."""
    dx,dz=map(float,delta)
    return normalize_polygon([[float(x)+dx,float(z)+dz] for x,z in points],
                             length,allow_outside=allow_outside)


def stretch_edge(points, edge_index, delta, length, *, allow_outside=True):
    """Slab-style extrude: preserve the old edge as anchoring vertices.

    Adds exactly two corners and a displaced copy of the selected edge.
    """
    n=len(points);i=int(edge_index)%n;j=(i+1)%n
    ax,az=map(float,points[i]);bx,bz=map(float,points[j])
    dx,dz=bx-ax,bz-az
    norm=math.hypot(dx,dz)
    if norm<0.001:
        raise ValueError("A aresta precisa ter pelo menos 1 mm.")
    nx,nz=-dz/norm,dx/norm
    distance=float(delta[0])*nx+float(delta[1])*nz
    if abs(distance)<0.001:
        raise ValueError("Arraste a aresta ao menos 1 mm.")
    shifted_a=[ax+nx*distance,az+nz*distance]
    shifted_b=[bx+nx*distance,bz+nz*distance]
    rotated=[list(points[(i+k)%n]) for k in range(n)]
    expanded=[rotated[0],shifted_a,shifted_b,rotated[1]]+rotated[2:]
    return normalize_polygon(expanded,length,allow_outside=allow_outside)


def delete_vertex(points, index, length, *, allow_outside=False):
    """Remove one vertex, never reducing an opening below three vertices."""
    if len(points) <= 3:
        raise ValueError("A abertura deve conservar pelo menos três vértices.")
    updated = [list(p) for p in points]
    del updated[index % len(updated)]
    return normalize_polygon(updated, length, allow_outside=allow_outside)
