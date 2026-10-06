# SPDX-License-Identifier: GPL-3.0-or-later
"""Derived cleanup for junctions between independent straight walls.

The reference lines remain authoritative for editing, but physical contact can
also establish an architectural join.  Endpoint-to-endpoint nodes use a true
2-D miter for two walls.  Nodes with three or more walls deliberately use an
overlap-safe square-cap strategy: separate wall solids may overlap locally, but
they cannot leave the triangular/star-shaped void that a pairwise miter creates.

A second pass detects when the *raw wall footprints* touch or overlap even when
their reference endpoints do not coincide.  If an end cap physically reaches
another wall, the resolver derives a virtual junction from the infinite
reference-line intersection and extends/trims only the derived body cap.  The
stored reference path is not silently moved.  This gives BIM-like automatic
cleanup while preserving independent parametric walls and undo history.
"""
from __future__ import annotations

import copy
import math

from PySide6.QtGui import QVector3D

from .layer_intersections import can_intersect as layer_can_intersect
from .model import (DERIVED_KEY, KEY, MIN_DIM, WallError, _hide_joint_seam_edges,
                    arc_center_world, build_body, build_children, footprint, local_from_world, path_world,
                    read_wall, record, wall_caps, wall_offsets, wall_path, wall_path_kind, wall_record, wall_has_custom_profile)

# Exact reference endpoints really are the same architectural node.
JOIN_TOL = 1.0e-4            # 0.1 mm
# Physical bodies can establish a join without the axes touching exactly.
CONTACT_TOL = 5.0e-4         # 0.5 mm numerical/contact tolerance
NODE_CLUSTER_TOL = 2.0e-3    # virtual pairwise hits treated as one local node
PARALLEL_EPS = 1.0e-7
CAP_EPS = 2.0e-8
MITER_FACTOR = 20.0
MITER_MIN = 0.50             # metres; generous for ordinary architectural corners
CONTACT_EXTEND_FACTOR = 10.0
CONTACT_EXTEND_MIN = 0.50
DERIVED_REV = 5             # layer-intersection groups + curved junction cleanup


def _interaction_subclusters(cluster):
    """Partition endpoint records by the current layer intersection group."""
    buckets=[]
    for endpoint in cluster:
        group=endpoint.get("group")
        placed=False
        for bucket in buckets:
            if bucket and layer_can_intersect(group,bucket[0].get("group")):
                bucket.append(endpoint);placed=True;break
        if not placed:buckets.append([endpoint])
    return buckets


def _interaction_partitions(info):
    """Partition a group->data mapping into mutually interacting sets."""
    buckets=[]
    for group,data in info.items():
        placed=False
        for bucket in buckets:
            first=next(iter(bucket),None)
            if first is not None and layer_can_intersect(group,first):
                bucket[group]=data;placed=True;break
        if not placed:buckets.append({group:data})
    return buckets


def _cross2(a, b):
    return a.x() * b.y() - a.y() * b.x()


def _line_intersection(p, r, q, s):
    den = _cross2(r, s)
    if abs(den) < PARALLEL_EPS:
        return None
    qp = q - p
    t = _cross2(qp, s) / den
    return p + r * t


def _closest_on_line(point, origin, direction):
    """Closest point on an infinite XY line."""
    d = QVector3D(direction)
    den = QVector3D.dotProduct(d, d)
    if den < PARALLEL_EPS:
        return QVector3D(origin)
    t = QVector3D.dotProduct(QVector3D(point) - QVector3D(origin), d) / den
    return QVector3D(origin) + d * t


def _xy_unit(v):
    length = math.hypot(v.x(), v.y())
    if length < MIN_DIM:
        raise WallError("Trajetória da parede inválida para a junção.")
    return QVector3D(v.x() / length, v.y() / length, 0.0)


def _offsets(values):
    return wall_offsets(values)


def _endpoint_tangent(group, which, world_path):
    """Exact-ish start→end tangent in world XY for a line or circular arc.

    A curved wall is stored as a true parametric arc but displayed through
    sampled points.  For junctions we must not use the chord as the local wall
    direction: the miter is defined by the *tangent* at the endpoint.  The arc
    centre gives the exact tangent direction; the adjacent sample tells us which
    of the two tangent senses follows the stored start→end path.
    """
    if len(world_path) < 2:
        raise WallError("Trajetória da parede inválida para a junção.")
    if which == "start":
        actual = QVector3D(world_path[0])
        approx = QVector3D(world_path[1]) - actual
    else:
        actual = QVector3D(world_path[-1])
        approx = actual - QVector3D(world_path[-2])
    approx = _xy_unit(approx)

    if wall_path_kind(group) == "arc":
        centre = arc_center_world(group)
        if centre is not None:
            radius = actual - QVector3D(centre)
            candidate = _xy_unit(QVector3D(-radius.y(), radius.x(), 0.0))
            if QVector3D.dotProduct(candidate, approx) < 0.0:
                candidate = -candidate
            return candidate
    return approx


def _endpoint(group, which, values, world_path, vertex_override=None):
    """Description of a line/arc endpoint in world XY.

    ``vertex_override`` is used only for *derived* virtual joins of straight
    walls.  Exact line↔arc nodes keep the stored endpoint and use the circular
    arc tangent to derive the physical miter.
    """
    ref_dir = _endpoint_tangent(group, which, world_path)
    normal = QVector3D(-ref_dir.y(), ref_dir.x(), 0.0)
    actual = QVector3D(world_path[0] if which == "start" else world_path[-1])
    vertex = QVector3D(vertex_override) if vertex_override is not None else QVector3D(actual)
    outward = ref_dir if which == "start" else -ref_dir
    low, high = _offsets(values)

    low_point = vertex + normal * low
    high_point = vertex + normal * high
    boundaries = []
    for name, point in (("low", low_point), ("high", high_point)):
        # Signed side relative to the ray that leaves the junction and runs
        # into this wall. Sorting gives stable CW/CCW classification regardless
        # of the wall's own stored drawing direction.
        signed = _cross2(outward, point - vertex)
        boundaries.append({"name": name, "point": point,
                           "direction": ref_dir, "signed": signed})
    boundaries.sort(key=lambda item: item["signed"])
    return {
        "group": group,
        "which": which,
        "vertex": vertex,
        "actual_vertex": actual,
        "outward": outward,
        "ref_dir": ref_dir,
        "normal": normal,
        "thickness": values["thickness"],
        "low_distance": low,
        "high_distance": high,
        "low_point": low_point,
        "high_point": high_point,
        "right": boundaries[0],
        "left": boundaries[-1],
    }


def _cap_at(endpoint, centre):
    """Square end cap through ``centre`` on the endpoint's reference line."""
    centre = QVector3D(centre)
    normal = endpoint["normal"]
    low = centre + normal * endpoint["low_distance"]
    high = centre + normal * endpoint["high_distance"]
    return (local_from_world(endpoint["group"], low),
            local_from_world(endpoint["group"], high))


def _caps_close(a, b):
    if set(a) != set(b):
        return False
    for key in a:
        pa, pb = a[key], b[key]
        if len(pa) != 2 or len(pb) != 2:
            return False
        if any((QVector3D(x) - QVector3D(y)).length() > CAP_EPS
               for x, y in zip(pa, pb)):
            return False
    return True


def _node_caps(cluster):
    """Return local endpoint caps for one logical/virtual junction node.

    Two walls receive a true miter, preserving the clean architectural corner.
    Three or more walls use square cross-sections through the shared node.  The
    bodies therefore overlap in the tiny junction region instead of stopping at
    pairwise miter lines and leaving a central polygonal hole.  Overlap is a
    deliberate intermediate representation; later material priorities can
    decide which wall owns the region without changing the reference topology.
    """
    if len(cluster) < 2 or len({id(e["group"]) for e in cluster}) != len(cluster):
        return None

    centre = QVector3D(0, 0, 0)
    for endpoint in cluster:
        centre += endpoint["vertex"]
    centre /= float(len(cluster))

    if len(cluster) >= 3:
        return {
            endpoint["group"]: {endpoint["which"]: _cap_at(endpoint, centre)}
            for endpoint in cluster
        }

    # Exactly two walls: ordinary 2-D miter.
    ordered = sorted(cluster, key=lambda e: math.atan2(e["outward"].y(),
                                                        e["outward"].x()))
    first, second = ordered
    cross = _cross2(first["outward"], second["outward"])
    dot = QVector3D.dotProduct(first["outward"], second["outward"])

    if abs(cross) < PARALLEL_EPS:
        if dot > 0.0:
            # Same-direction overlapping rays need a future priority rule.
            return None
        # Straight continuation.  Each cap lies on the common cross-section.
        return {
            first["group"]: {first["which"]: _cap_at(first, centre)},
            second["group"]: {second["which"]: _cap_at(second, centre)},
        }

    assigned = {first["group"]: {}, second["group"]: {}}
    # Wedge first -> second.
    hit_a = _line_intersection(
        first["left"]["point"], first["left"]["direction"],
        second["right"]["point"], second["right"]["direction"])
    # Wedge second -> first (around the other side of the node).
    hit_b = _line_intersection(
        second["left"]["point"], second["left"]["direction"],
        first["right"]["point"], first["right"]["direction"])
    if hit_a is None or hit_b is None:
        return None

    limit = max(MITER_MIN, MITER_FACTOR * max(first["thickness"],
                                              second["thickness"]))
    if ((hit_a - centre).length() > limit
            or (hit_b - centre).length() > limit):
        return None
    hit_a.setZ(centre.z()); hit_b.setZ(centre.z())

    assigned[first["group"]][first["left"]["name"]] = QVector3D(hit_a)
    assigned[second["group"]][second["right"]["name"]] = QVector3D(hit_a)
    assigned[second["group"]][second["left"]["name"]] = QVector3D(hit_b)
    assigned[first["group"]][first["right"]["name"]] = QVector3D(hit_b)

    result = {}
    for endpoint in ordered:
        g = endpoint["group"]
        world = assigned[g]
        if "low" not in world or "high" not in world:
            return None
        result[g] = {
            endpoint["which"]: (
                local_from_world(g, world["low"]),
                local_from_world(g, world["high"]),
            )
        }
    return result


def _clusters(endpoints, tolerance=JOIN_TOL):
    """Union-find point clusters based on endpoint ``vertex``."""
    n = len(endpoints)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if (endpoints[i]["vertex"] - endpoints[j]["vertex"]).length() <= tolerance:
                union(i, j)

    out = {}
    for i, endpoint in enumerate(endpoints):
        out.setdefault(find(i), []).append(endpoint)
    return list(out.values())


# ---------------------------------------------------------------------------
# 2-D physical-contact helpers (raw wall footprints, before derived caps)
# ---------------------------------------------------------------------------

def _world_raw_footprint(group, values, local_path):
    poly = footprint(local_path, values["thickness"], values["alignment"], caps=None, offsets=wall_offsets(values))
    return [group.xform.map(QVector3D(p)) for p in poly]


def _orient(a, b, c):
    return _cross2(QVector3D(b) - QVector3D(a), QVector3D(c) - QVector3D(a))


def _point_segment_distance(p, a, b):
    p, a, b = QVector3D(p), QVector3D(a), QVector3D(b)
    d = b - a
    den = d.x() * d.x() + d.y() * d.y()
    if den <= 1e-18:
        return math.hypot(p.x() - a.x(), p.y() - a.y())
    t = ((p.x() - a.x()) * d.x() + (p.y() - a.y()) * d.y()) / den
    t = max(0.0, min(1.0, t))
    qx, qy = a.x() + d.x() * t, a.y() + d.y() * t
    return math.hypot(p.x() - qx, p.y() - qy)


def _segments_touch(a, b, c, d, tol=CONTACT_TOL):
    # Exact/proper intersection first.
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    if ((o1 > tol and o2 < -tol) or (o1 < -tol and o2 > tol)) and \
            ((o3 > tol and o4 < -tol) or (o3 < -tol and o4 > tol)):
        return True
    # Collinear/tangent/numerically-near contact.
    return min(_point_segment_distance(a, c, d),
               _point_segment_distance(b, c, d),
               _point_segment_distance(c, a, b),
               _point_segment_distance(d, a, b)) <= tol


def _point_in_polygon(point, poly):
    # Standard ray crossing; boundary is handled by distance checks elsewhere.
    x, y = point.x(), point.y()
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i].x(), poly[i].y()
        xj, yj = poly[j].x(), poly[j].y()
        crosses = ((yi > y) != (yj > y))
        if crosses:
            denom = (yj - yi)
            xhit = (xj - xi) * (y - yi) / (denom if abs(denom) > 1e-18 else 1e-18) + xi
            if x < xhit:
                inside = not inside
        j = i
    return inside


def _segment_touches_polygon(a, b, poly, tol=CONTACT_TOL):
    if _point_in_polygon(a, poly) or _point_in_polygon(b, poly):
        return True
    for c, d in zip(poly, poly[1:] + poly[:1]):
        if _segments_touch(a, b, c, d, tol):
            return True
    return False


def _polygons_touch(a, b, tol=CONTACT_TOL):
    if any(_point_in_polygon(p, b) for p in a):
        return True
    if any(_point_in_polygon(p, a) for p in b):
        return True
    for a0, a1 in zip(a, a[1:] + a[:1]):
        for b0, b1 in zip(b, b[1:] + b[:1]):
            if _segments_touch(a0, a1, b0, b1, tol):
                return True
    return False


def _line_segment_intersection(line_point, line_dir, a, b, tol=1e-8):
    """Intersection of an infinite XY line with one finite XY segment."""
    r = QVector3D(line_dir)
    s = QVector3D(b) - QVector3D(a)
    den = _cross2(r, s)
    if abs(den) <= PARALLEL_EPS:
        return None
    q = QVector3D(a) - QVector3D(line_point)
    t = _cross2(q, s) / den
    u = _cross2(q, r) / den
    if u < -tol or u > 1.0 + tol:
        return None
    hit = QVector3D(line_point) + r * t
    return QVector3D(hit.x(), hit.y(), QVector3D(line_point).z())


def _side_near_boundary(side_point, endpoint, poly, max_distance):
    """Nearest host-envelope crossing seen from the wall interior.

    A T branch may be drawn to the host centre line.  Its physical end should
    nevertheless stop on the *near face* of that host, not continue halfway
    through the host thickness.  Among all intersections of this wall-side line
    with the host polygon, the near face is the hit furthest in the endpoint's
    ``outward`` direction (which points back into this wall).
    """
    hits = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        hit = _line_segment_intersection(side_point, endpoint["ref_dir"], a, b)
        if hit is None:
            continue
        if (hit - QVector3D(side_point)).length() > max_distance + endpoint["thickness"] * 2.0:
            continue
        score = QVector3D.dotProduct(hit - QVector3D(side_point), endpoint["outward"])
        hits.append((score, hit))
    if not hits:
        return None
    hits.sort(key=lambda item: item[0], reverse=True)
    return QVector3D(hits[0][1])


def _contact_cap_against_polygon(endpoint, other_poly, max_distance):
    """World-space low/high cap trimmed to the contacted wall envelope."""
    low = _side_near_boundary(endpoint["low_point"], endpoint, other_poly,
                              max_distance)
    high = _side_near_boundary(endpoint["high_point"], endpoint, other_poly,
                               max_distance)
    if low is None or high is None or (high - low).length() < MIN_DIM:
        return None
    return (low, high)


def _contact_candidates(info, endpoints_by_group):
    """Return virtual-contact candidates keyed by (group, endpoint name).

    Besides the inferred reference-line intersection, each endpoint now carries
    an optional cap clipped to the *near physical face* of the contacted wall.
    A lone endpoint-to-side contact can therefore form a true T instead of
    penetrating to the host wall's centre line.
    """
    groups = list(info)
    candidates = {}
    for i, ga in enumerate(groups):
        va, path_a, world_a, poly_a = info[ga]
        for gb in groups[i + 1:]:
            vb, path_b, world_b, poly_b = info[gb]
            if abs(va["base"] - vb["base"]) > JOIN_TOL:
                continue
            if not _polygons_touch(poly_a, poly_b):
                continue

            da = _xy_unit(world_a[1] - world_a[0])
            db = _xy_unit(world_b[1] - world_b[0])
            hit = _line_intersection(world_a[0], da, world_b[0], db)
            if hit is None:
                # Parallel/collinear physical overlaps need a future priority
                # policy; do not silently shorten one wall here.
                continue
            hit.setZ(va["base"])
            max_extend = max(CONTACT_EXTEND_MIN,
                             CONTACT_EXTEND_FACTOR * max(va["thickness"], vb["thickness"]))

            for endpoint, other_poly, other_group in (
                    (endpoints_by_group[ga]["start"], poly_b, gb),
                    (endpoints_by_group[ga]["end"], poly_b, gb),
                    (endpoints_by_group[gb]["start"], poly_a, ga),
                    (endpoints_by_group[gb]["end"], poly_a, ga)):
                if not _segment_touches_polygon(endpoint["low_point"],
                                                endpoint["high_point"],
                                                other_poly):
                    continue
                distance = (endpoint["actual_vertex"] - hit).length()
                if distance > max_extend:
                    continue
                cap_world = _contact_cap_against_polygon(endpoint, other_poly,
                                                         max_extend)
                key = (endpoint["group"], endpoint["which"])
                old = candidates.get(key)
                # Exact/nearby axis intersection wins if an end touches more
                # than one wall in a crowded node.
                if old is None or distance < old["distance"]:
                    candidates[key] = {
                        "distance": distance,
                        "hit": QVector3D(hit),
                        "cap_world": cap_world,
                        "host": other_group,
                    }
    return candidates



def _curved_contact_candidates(all_info, endpoints_by_group):
    """Endpoint-to-side contact for any pair where at least one wall is curved.

    Straight/straight contact keeps the long-tested resolver above.  For curved
    hosts/branches we do not invent a line-line reference intersection: the end
    cap is clipped directly against the *physical sampled footprint* of the
    other wall, using the exact tangent at an arc endpoint.  The stored arc and
    reference endpoints remain untouched.
    """
    groups = list(all_info)
    out = {}
    for i, ga in enumerate(groups):
        va, _pa, _wa, poly_a = all_info[ga]
        ka = wall_path_kind(ga)
        for gb in groups[i + 1:]:
            vb, _pb, _wb, poly_b = all_info[gb]
            kb = wall_path_kind(gb)
            if ka == kb == "line":
                continue
            if abs(va["base"] - vb["base"]) > JOIN_TOL:
                continue
            if not _polygons_touch(poly_a, poly_b):
                continue
            max_extend = max(CONTACT_EXTEND_MIN,
                             CONTACT_EXTEND_FACTOR * max(va["thickness"], vb["thickness"]))
            for endpoint, other_poly, host in (
                    (endpoints_by_group[ga]["start"], poly_b, gb),
                    (endpoints_by_group[ga]["end"], poly_b, gb),
                    (endpoints_by_group[gb]["start"], poly_a, ga),
                    (endpoints_by_group[gb]["end"], poly_a, ga)):
                # Only an end face that physically reaches the other footprint
                # may create a T/side join.  Side-side crossings are a separate
                # future operation and must not rewrite both parametric paths.
                if not _segment_touches_polygon(endpoint["low_point"],
                                                endpoint["high_point"],
                                                other_poly):
                    continue
                cap_world = _contact_cap_against_polygon(endpoint, other_poly,
                                                         max_extend)
                if cap_world is None:
                    continue
                centre = (QVector3D(cap_world[0]) + QVector3D(cap_world[1])) * 0.5
                distance = (centre - endpoint["actual_vertex"]).length()
                if distance > max_extend + endpoint["thickness"] * 2.0:
                    continue
                key = (endpoint["group"], endpoint["which"])
                old = out.get(key)
                if old is None or distance < old["distance"]:
                    out[key] = {
                        "distance": distance,
                        "cap_world": tuple(QVector3D(p) for p in cap_world),
                        "host": host,
                    }
    return out


def _segment_polygon_overlap_intervals(a, b, poly, tol=CONTACT_TOL * 4.0):
    """Intervals of host boundary segment ``a-b`` covered by ``poly``.

    This works for sampled curved footprints too, so a curved host can lose only
    the small top/bottom border under a T branch rather than an entire facet.
    """
    a, b = QVector3D(a), QVector3D(b)
    d = b - a
    den = d.x() * d.x() + d.y() * d.y()
    if den <= 1e-18:
        return []
    ts = [0.0, 1.0]

    def add_t(point):
        t = ((point.x() - a.x()) * d.x() + (point.y() - a.y()) * d.y()) / den
        if -tol <= t <= 1.0 + tol:
            ts.append(max(0.0, min(1.0, t)))

    for c, e in zip(poly, poly[1:] + poly[:1]):
        hit = _segment_intersection_point(a, b, c, e)
        if hit is not None:
            add_t(hit)
            continue
        # Collinear overlap: add any polygon vertices that lie on this segment.
        if abs(_orient(a, b, c)) <= tol and abs(_orient(a, b, e)) <= tol:
            if _point_segment_distance(c, a, b) <= tol:
                add_t(c)
            if _point_segment_distance(e, a, b) <= tol:
                add_t(e)

    ts = sorted(set(round(t, 10) for t in ts))
    out = []
    for lo, hi in zip(ts, ts[1:]):
        if hi - lo <= 1e-9:
            continue
        mid = a + d * ((lo + hi) * 0.5)
        if _point_in_polygon(mid, poly) or _on_polygon_boundary(mid, poly, tol):
            out.append((float(lo), float(hi)))
    return out


def _derive_t_mouth_masks_general(t_mouths, info, final_polys):
    """Partial host-border gaps for straight *or curved* T hosts."""
    out = {g: [] for g in info}
    for item in t_mouths:
        host = item.get("host")
        branch = item.get("branch")
        if host not in info or branch not in final_polys:
            continue
        host_poly = final_polys.get(host) or []
        branch_poly = final_polys.get(branch) or []
        if len(host_poly) < 2 or len(branch_poly) < 3:
            continue
        for a, b in zip(host_poly, host_poly[1:] + host_poly[:1]):
            for lo, hi in _segment_polygon_overlap_intervals(a, b, branch_poly):
                gap0 = a + (b - a) * lo
                gap1 = a + (b - a) * hi
                out[host].append((
                    local_from_world(host, a), local_from_world(host, b),
                    local_from_world(host, gap0), local_from_world(host, gap1)))
    return out

def _cluster_virtual_endpoints(endpoints):
    return _clusters(endpoints, tolerance=NODE_CLUSTER_TOL)



# ---------------------------------------------------------------------------
# Technical crease / overlap cleanup
# ---------------------------------------------------------------------------

def _point_segment_distance(point, a, b):
    d = b - a
    den = d.x() * d.x() + d.y() * d.y()
    if den <= 1e-18:
        return math.hypot(point.x() - a.x(), point.y() - a.y())
    t = ((point.x() - a.x()) * d.x() + (point.y() - a.y()) * d.y()) / den
    t = max(0.0, min(1.0, t))
    qx, qy = a.x() + d.x() * t, a.y() + d.y() * t
    return math.hypot(point.x() - qx, point.y() - qy)


def _on_polygon_boundary(point, poly, tol=CONTACT_TOL * 2.0):
    return any(_point_segment_distance(point, a, b) <= tol
               for a, b in zip(poly, poly[1:] + poly[:1]))


def _strict_inside_polygon(point, poly):
    return _point_in_polygon(point, poly) and not _on_polygon_boundary(point, poly)


def _segment_intersection_point(a, b, c, d, tol=1e-8):
    """Single finite XY segment intersection; collinear overlap returns None."""
    r, s = b - a, d - c
    den = _cross2(r, s)
    if abs(den) <= PARALLEL_EPS:
        return None
    q = c - a
    t = _cross2(q, s) / den
    u = _cross2(q, r) / den
    if t < -tol or t > 1.0 + tol or u < -tol or u > 1.0 + tol:
        return None
    hit = a + r * max(0.0, min(1.0, t))
    return QVector3D(hit.x(), hit.y(), a.z())


def _final_world_poly(group, values, path, caps):
    local = footprint(path, values["thickness"], values["alignment"], caps=caps, offsets=wall_offsets(values))
    return [group.xform.map(QVector3D(p)) for p in local]


def _near_any_vertex(point, poly, tol=JOIN_TOL * 2.0):
    return any((QVector3D(point) - QVector3D(v)).length() <= tol for v in poly)


def _dedup_points(points, candidate, tol=JOIN_TOL * 2.0):
    if not any((QVector3D(candidate) - QVector3D(p)).length() <= tol for p in points):
        points.append(QVector3D(candidate))


def _derive_crease_edges(info, desired, final_polys):
    """Visible vertical creases where independent wall envelopes intersect.

    The solids intentionally remain independent.  A physical overlap can
    nevertheless create a real change of direction in the visible architectural
    envelope.  IngeTrazo cannot draw that line unless it exists as an edge, so
    we add a free vertical technical edge on each affected wall face.
    """
    points = {g: [] for g in info}
    groups = list(info)
    for i, ga in enumerate(groups):
        va, _pa, _wa, _rawa = info[ga]
        poly_a = final_polys[ga]
        for gb in groups[i + 1:]:
            vb, _pb, _wb, _rawb = info[gb]
            if abs(va["base"] - vb["base"]) > JOIN_TOL:
                continue
            poly_b = final_polys[gb]
            if not _polygons_touch(poly_a, poly_b):
                continue
            for a0, a1 in zip(poly_a, poly_a[1:] + poly_a[:1]):
                for b0, b1 in zip(poly_b, poly_b[1:] + poly_b[:1]):
                    hit = _segment_intersection_point(a0, a1, b0, b1)
                    if hit is None:
                        continue
                    # Existing polygon corners already own a hard vertical edge.
                    # Only create a free crease where the other wall cuts through
                    # the middle of a side face.
                    if not _near_any_vertex(hit, poly_a):
                        _dedup_points(points[ga], hit)
                    if not _near_any_vertex(hit, poly_b):
                        _dedup_points(points[gb], hit)

    result = {g: [] for g in info}
    for group, hits in points.items():
        values = info[group][0]
        for hit in hits:
            local = local_from_world(
                group, QVector3D(hit.x(), hit.y(), values["base"]))
            result[group].append((
                QVector3D(local.x(), local.y(), 0.0),
                QVector3D(local.x(), local.y(), values["height"]),
            ))
    return result


def _serialize_creases(creases):
    out = []
    for a, b in creases or ():
        out.append([[round(a.x(), 9), round(a.y(), 9), round(a.z(), 9)],
                    [round(b.x(), 9), round(b.y(), 9), round(b.z(), 9)]])
    return out


def _hide_overlap_interior_edges(info, final_polys):
    """Hide mesh seams wholly buried inside another joined wall solid."""
    groups = list(info)
    for group in groups:
        values = info[group][0]
        bodies = list(getattr(group, "children", None) or [])
        if not bodies:
            continue
        for body in bodies:
            for edge in body.mesh.edges:
                edge.hidden = False
            caps = wall_caps(group)
            _hide_joint_seam_edges(body.mesh, caps.get("start"), values["height"])
            _hide_joint_seam_edges(body.mesh, caps.get("end"), values["height"])
            for edge in body.mesh.edges:
                if not edge.faces:
                    edge.hidden = False
                    continue
                if edge.hidden:
                    continue
                wa = group.xform.map(edge.v0.position)
                wb = group.xform.map(edge.v1.position)
                mid = (wa + wb) * 0.5
                zlo, zhi = sorted((wa.z(), wb.z()))
                for other in groups:
                    if other is group:
                        continue
                    oval = info[other][0]
                    if abs(values["base"] - oval["base"]) > JOIN_TOL:
                        continue
                    other_top = oval["base"] + oval["height"]
                    if zlo < oval["base"] - JOIN_TOL or zhi > other_top + JOIN_TOL:
                        continue
                    if (_strict_inside_polygon(wa, final_polys[other])
                            and _strict_inside_polygon(wb, final_polys[other])
                            and _strict_inside_polygon(mid, final_polys[other])):
                        edge.hidden = True
                        break

# ---------------------------------------------------------------------------
# T-junction drawing cleanup: mask only the mouth in the host boundary
# ---------------------------------------------------------------------------

def _segment_parameter(point, a, b, tol=CONTACT_TOL * 4.0):
    """Return point parameter on finite XY segment, or ``None`` when off it."""
    point, a, b = QVector3D(point), QVector3D(a), QVector3D(b)
    d = b - a
    den = d.x() * d.x() + d.y() * d.y()
    if den <= 1e-18:
        return None
    t = ((point.x() - a.x()) * d.x() + (point.y() - a.y()) * d.y()) / den
    if t < -tol or t > 1.0 + tol:
        return None
    q = a + d * t
    if math.hypot(point.x() - q.x(), point.y() - q.y()) > tol:
        return None
    return max(0.0, min(1.0, t))


def _derive_t_mouth_masks(t_mouths, info, final_polys):
    """Partial host-edge gaps that make an endpoint-to-side join read as a T.

    A branch already has its derived end-cap top/bottom seam hidden by
    ``_hide_joint_seam_edges``.  The remaining drawing artifact is the host
    wall's long top/bottom boundary running *through* the branch mouth.  Mesh
    edges cannot be partly hidden, so we remember the exact sub-segment to mask
    and later replace the original long edge with two visible free pieces.
    """
    out = {g: [] for g in info}
    for item in t_mouths:
        host = item.get("host")
        pair = item.get("mouth_world")
        if host not in info or not pair or len(pair) != 2:
            continue
        m0, m1 = QVector3D(pair[0]), QVector3D(pair[1])
        poly = final_polys.get(host) or []
        if len(poly) < 2:
            continue
        best = None
        for a, b in zip(poly, poly[1:] + poly[:1]):
            t0 = _segment_parameter(m0, a, b)
            t1 = _segment_parameter(m1, a, b)
            if t0 is None or t1 is None:
                continue
            span = abs(t1 - t0)
            if span <= 1e-8:
                continue
            # Prefer the boundary edge on which both mouth corners fit most
            # comfortably.  Usually there is exactly one.
            score = span
            if best is None or score > best[0]:
                best = (score, QVector3D(a), QVector3D(b), t0, t1)
        if best is None:
            continue
        _score, a, b, t0, t1 = best
        lo, hi = sorted((t0, t1))
        gap0 = a + (b - a) * lo
        gap1 = a + (b - a) * hi
        local_a = local_from_world(host, a)
        local_b = local_from_world(host, b)
        local_g0 = local_from_world(host, gap0)
        local_g1 = local_from_world(host, gap1)
        out[host].append((local_a, local_b, local_g0, local_g1))
    return out


def _serialize_edge_masks(masks):
    def pt(p):
        return [round(p.x(), 9), round(p.y(), 9), 0.0]
    return [[pt(a), pt(b), pt(g0), pt(g1)] for a, b, g0, g1 in masks or ()]


def _same_point(a, b, tol=2.0e-6):
    return (QVector3D(a) - QVector3D(b)).length() <= tol


def _add_visible_free_edge(mesh, a, b):
    """Draw one visible replacement piece without changing face topology."""
    if (QVector3D(b) - QVector3D(a)).length() <= 1e-8:
        return
    try:
        edge = mesh.add_edge(QVector3D(a), QVector3D(b))
        edge.hidden = False
        edge.soft = False
    except ValueError:
        pass


def _parent_key_and_interval(a, b, g0, g1):
    """Canonical parent edge plus the gap interval on it.

    Masks can arrive with the same host edge in opposite directions.  A stable
    canonical direction lets several T mouths on one wall be merged before any
    drawing edge is touched.
    """
    a, b, g0, g1 = map(QVector3D, (a, b, g0, g1))
    ka = (round(a.x(), 8), round(a.y(), 8))
    kb = (round(b.x(), 8), round(b.y(), 8))
    if kb < ka:
        a, b = b, a
        ka, kb = kb, ka
    d = b - a
    den = d.x() * d.x() + d.y() * d.y()
    if den <= 1e-18:
        return None
    def param(p):
        return ((p.x() - a.x()) * d.x() + (p.y() - a.y()) * d.y()) / den
    t0, t1 = sorted((max(0.0, min(1.0, param(g0))),
                     max(0.0, min(1.0, param(g1)))))
    if t1 - t0 <= 1e-8:
        return None
    return (ka, kb), a, b, (t0, t1)


def _merge_intervals(intervals, tol=1e-7):
    intervals = sorted((max(0.0, a), min(1.0, b)) for a, b in intervals
                       if b - a > 1e-8)
    out = []
    for lo, hi in intervals:
        if not out or lo > out[-1][1] + tol:
            out.append([lo, hi])
        else:
            out[-1][1] = max(out[-1][1], hi)
    return [(a, b) for a, b in out]


def _find_parent_boundary_edge(mesh, a, b, z, tol=4.0e-6):
    """Find the real face-boundary edge spanning local ``a``-``b`` at z."""
    pa = QVector3D(a.x(), a.y(), z)
    pb = QVector3D(b.x(), b.y(), z)
    for edge in mesh.edges:
        if not edge.faces:                 # ignore technical/free drawing edges
            continue
        ea, eb = edge.v0.position, edge.v1.position
        if ((_same_point(ea, pa, tol) and _same_point(eb, pb, tol))
                or (_same_point(ea, pb, tol) and _same_point(eb, pa, tol))):
            return edge
    return None


def _apply_t_mouth_masks(info, masks_by_group):
    """Render T mouths deterministically on every generated layer body."""
    for group, masks in masks_by_group.items():
        if group not in info or not masks:
            continue
        bodies = list(getattr(group, "children", None) or [])
        if not bodies:
            continue
        height = info[group][0]["height"]
        parents = {}
        for a, b, g0, g1 in masks:
            parsed = _parent_key_and_interval(a, b, g0, g1)
            if parsed is None:
                continue
            key, ca, cb, interval = parsed
            slot = parents.setdefault(key, {"a": ca, "b": cb, "intervals": []})
            slot["intervals"].append(interval)
        for body in bodies:
            mesh = body.mesh
            for slot in parents.values():
                a, b = slot["a"], slot["b"]
                intervals = _merge_intervals(slot["intervals"])
                if not intervals:
                    continue
                d = b - a
                visible=[]; cursor=0.0
                for lo,hi in intervals:
                    if lo > cursor + 1e-8: visible.append((cursor,lo))
                    cursor=max(cursor,hi)
                if cursor < 1.0 - 1e-8: visible.append((cursor,1.0))
                for z in (0.0,height):
                    parent=_find_parent_boundary_edge(mesh,a,b,z)
                    if parent is None:
                        continue
                    parent.hidden=True
                    for lo,hi in visible:
                        p0=QVector3D(a.x()+d.x()*lo,a.y()+d.y()*lo,z)
                        p1=QVector3D(a.x()+d.x()*hi,a.y()+d.y()*hi,z)
                        _add_visible_free_edge(mesh,p0,p1)


# ---------------------------------------------------------------------------
# Visible-corner snap aliases
# ---------------------------------------------------------------------------

def junction_snap_aliases(scene, base=None):
    """Visible physical corner -> logical reference-node aliases.

    Supports the established straight-wall nodes plus the first curved-wall
    junction case: exactly one straight wall meeting one circular wall at their
    reference endpoints.  Arc↔arc and N-way curved nodes intentionally remain
    for later versions.
    """
    endpoints = []
    for group in list(scene.groups):
        if wall_record(group) is None:
            continue
        try:
            kind = wall_path_kind(group)
            if kind not in ("line", "arc"):
                continue
            values = read_wall(group)
            if base is not None and abs(values["base"] - float(base)) > JOIN_TOL:
                continue
            world = path_world(group)
            if len(world) < 2:
                continue
            endpoints.append(_endpoint(group, "start", values, world))
            endpoints.append(_endpoint(group, "end", values, world))
        except WallError:
            continue

    aliases = []
    for raw_cluster in _clusters(endpoints):
        for cluster in _interaction_subclusters(raw_cluster):
            if len(cluster) < 2:
                continue
            kinds = [wall_path_kind(e["group"]) for e in cluster]
            if not all(k in ("line", "arc") for k in kinds):
                continue
            caps = _node_caps(cluster)
            if caps is None:
                continue
            node = QVector3D(0, 0, 0)
            for endpoint in cluster:
                node += endpoint["vertex"]
            node /= float(len(cluster))

            for group, endpoint_caps in caps.items():
                for pair in endpoint_caps.values():
                    for local in pair:
                        display = group.xform.map(QVector3D(local))
                        if (display - node).length() <= JOIN_TOL:
                            continue
                        if not any((display - old_display).length() <= JOIN_TOL
                                   and (node - old_node).length() <= JOIN_TOL
                                   for old_display, old_node in aliases):
                            aliases.append((QVector3D(display), QVector3D(node)))
    return aliases


# ---------------------------------------------------------------------------
# Main derived resolver
# ---------------------------------------------------------------------------

def sync_wall_junctions(scene):
    """Synchronize straight and circular-wall junction cleanup.

    The established straight-wall resolver is kept intact.  Circular walls now
    participate in exact endpoint nodes (line↔arc, arc↔arc and N-way endpoint
    nodes) and in endpoint-to-side T contacts through their sampled physical
    footprint.  Arc parameters are never rewritten by cleanup: only derived end
    caps/display edges change.
    """
    straight_info = {}
    all_info = {}
    path_records = {}
    endpoints = []
    endpoints_by_group = {}

    for group in list(scene.groups):
        if wall_record(group) is None:
            continue
        try:
            kind = wall_path_kind(group)
            if kind not in ("line", "arc"):
                continue
            path = wall_path(group)
            world = path_world(group)
            if len(path) < 2 or len(world) < 2:
                continue
            values = read_wall(group)
            raw_poly = _world_raw_footprint(group, values, path)
            start_ep = _endpoint(group, "start", values, world)
            end_ep = _endpoint(group, "end", values, world)
            endpoints.extend((start_ep, end_ep))
            endpoints_by_group[group] = {"start": start_ep, "end": end_ep}
            all_info[group] = (values, path, world, raw_poly)
            if kind == "line":
                straight_info[group] = (values, path, world, raw_poly)
            else:
                rec = wall_record(group) or {}
                path_records[group] = copy.deepcopy(rec.get("path"))
        except WallError:
            continue

    desired = {group: {} for group in all_info}
    occupied = set()

    # 1) Exact reference-endpoint nodes.  Tangents make the same 2-D miter
    # solver valid for lines and true circular arcs.
    for raw_cluster in _clusters(endpoints):
        for cluster in _interaction_subclusters(raw_cluster):
            if len(cluster) < 2:
                continue
            kinds = [wall_path_kind(e["group"]) for e in cluster]
            if not all(k in ("line", "arc") for k in kinds):
                continue
            caps = _node_caps(cluster)
            if caps is None:
                continue
            for endpoint in cluster:
                occupied.add((endpoint["group"], endpoint["which"]))
            for group, endpoint_caps in caps.items():
                if group in desired:
                    desired[group].update(endpoint_caps)

    # 2a) Preserve the proven straight-wall physical-contact resolver.
    straight_endpoints = {g: endpoints_by_group[g] for g in straight_info}
    candidates = _contact_candidates(straight_info, straight_endpoints)

    # 2b) Add curved endpoint-to-side contacts without pretending an arc has a
    # straight reference line.  The end cap is clipped directly to the host
    # physical footprint using the endpoint tangent.
    curve_candidates = _curved_contact_candidates(all_info, endpoints_by_group)
    for key, cand in curve_candidates.items():
        old = candidates.get(key)
        if old is None or cand.get("distance", 1e99) < old.get("distance", 1e99):
            candidates[key] = cand

    # A candidate from another layer-intersection group is not a junction.
    for key, cand in list(candidates.items()):
        branch = key[0]
        host = cand.get("host")
        if host is not None and not layer_can_intersect(branch, host):
            candidates.pop(key, None)

    virtual = []
    t_mouths = []
    for (group, which), candidate in candidates.items():
        if (group, which) in occupied or group not in all_info:
            continue
        values, _path, world, _poly = all_info[group]
        # Straight candidates may carry a virtual axis hit; curved candidates
        # intentionally keep the true stored endpoint and only override the cap.
        vertex_override = candidate.get("hit") if wall_path_kind(group) == "line" else None
        endpoint = _endpoint(group, which, values, world, vertex_override=vertex_override)
        if candidate.get("cap_world") is not None:
            endpoint["contact_cap"] = tuple(
                local_from_world(group, p) for p in candidate["cap_world"])
            endpoint["contact_cap_world"] = tuple(QVector3D(p) for p in candidate["cap_world"])
            endpoint["contact_host"] = candidate.get("host")
        virtual.append(endpoint)

    for raw_cluster in _cluster_virtual_endpoints(virtual):
        for cluster in _interaction_subclusters(raw_cluster):
            if len(cluster) == 1:
                endpoint = cluster[0]
                desired[endpoint["group"]][endpoint["which"]] = (
                    endpoint.get("contact_cap") or _cap_at(endpoint, endpoint["vertex"]))
                if endpoint.get("contact_host") is not None and layer_can_intersect(endpoint["group"], endpoint["contact_host"]):
                    t_mouths.append({"branch": endpoint["group"],
                                     "host": endpoint["contact_host"]})
                continue
            if len({id(e["group"]) for e in cluster}) != len(cluster):
                for endpoint in cluster:
                    desired[endpoint["group"]][endpoint["which"]] = (
                        endpoint.get("contact_cap") or _cap_at(endpoint, endpoint["vertex"]))
                continue
            caps = _node_caps(cluster)
            if caps is None:
                for endpoint in cluster:
                    desired[endpoint["group"]][endpoint["which"]] = (
                        endpoint.get("contact_cap") or _cap_at(endpoint, endpoint["vertex"]))
                continue
            for group, endpoint_caps in caps.items():
                desired[group].update(endpoint_caps)

    final_polys = {
        group: _final_world_poly(group, values, path, desired.get(group, {}))
        for group, (values, path, _world, _poly) in all_info.items()
    }
    # Keep technical crease/overlap work inside each intersection group.
    straight_final = {g: final_polys[g] for g in straight_info}
    creases = {}
    for part in _interaction_partitions(straight_info):
        if not part:
            continue
        part_final={g:straight_final[g] for g in part}
        creases.update(_derive_crease_edges(
            part, {g:desired.get(g,{}) for g in part}, part_final))
    edge_masks = _derive_t_mouth_masks_general(t_mouths, all_info, final_polys)

    changed = 0
    for group, (values, path, _world, _poly) in all_info.items():
        wanted = desired.get(group, {})
        wanted_creases = creases.get(group, []) if group in straight_info else []
        current = wall_caps(group)
        ext_now = group.ext if isinstance(group.ext, dict) else {}
        derived_now = ext_now.get(DERIVED_KEY, {})
        crease_sig = _serialize_creases(wanted_creases)
        mask_sig = _serialize_edge_masks(edge_masks.get(group, []))
        if (_caps_close(current, wanted)
                and isinstance(derived_now, dict)
                and derived_now.get("rev") == DERIVED_REV
                and derived_now.get("creases", []) == crease_sig
                and derived_now.get("edge_masks", []) == mask_sig):
            continue
        previous_children = list(getattr(group, "children", None) or [])
        is_arc = wall_path_kind(group) == "arc"
        children = build_children(values, previous_children=previous_children, path=path, caps=wanted,
                                  crease_edges=wanted_creases,
                                  smooth_path=is_arc)
        ext = copy.deepcopy(group.ext) if isinstance(group.ext, dict) else {}
        ext[KEY] = record(values, path, caps=wanted,
                          path_record=path_records.get(group) if is_arc else None)
        ext[DERIVED_KEY] = {"rev": DERIVED_REV,
                            "creases": crease_sig,
                            "edge_masks": mask_sig}
        group.children = children
        group.ext = ext
        changed += 1

    # Legacy overlap masking assumes one horizontal base/top plane.  Keep it
    # away from profiled walls; their sloped/twisted surfaces already meet via
    # the plan caps and should not have edges hidden by a uniform-height test.
    maskable_straight = {g:info for g,info in straight_info.items()
                         if not wall_has_custom_profile(info[0])}
    for part in _interaction_partitions(maskable_straight):
        part_final={g:straight_final[g] for g in part}
        _hide_overlap_interior_edges(part, part_final)
    _apply_t_mouth_masks(all_info, edge_masks)
    return changed

