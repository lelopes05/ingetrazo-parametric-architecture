# SPDX-License-Identifier: GPL-3.0-or-later
"""Native-history wall commands; parent identity and BIM data are preserved."""
import copy

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.history import Command
from .materials import stamp_named_material, stamp_structured_materials
from .model import (ARC_EPS, DERIVED_KEY, KEY, MIN_DIM, MAX_DIM, WallError,
                    arc_points, arc_record, build_body, build_children, edit_placement,
                    make_arc_wall, make_wall_segment, path_length, path_length_from_record,
                    path_world, read_wall, record, validate, wall_path,
                    wall_path_kind, wall_record, wall_reference_vertices, reference_vertices_world, wall_has_custom_profile, profile_at_fraction,
                    finalize_wall_surface_maps)


def root_edit_allowed(scene):
    if scene.edit_group is not None:
        raise WallError("Saia da edição do grupo antes de criar ou alterar paredes.")


class CreateWall(Command):
    def __init__(self, group):
        self.group = group
        self.index = None

    def do(self, scene):
        if self.group in scene.groups:
            raise WallError("A parede já está no documento.")
        from .bim import ensure_ifc_identity
        ensure_ifc_identity(self.group, "IfcWall")
        rec=wall_record(self.group) or {}
        stamp_structured_materials(self.group, scene, rec)
        try:
            finalize_wall_surface_maps(self.group.children, rec, wall_path(self.group),
                                       smooth_path=(wall_path_kind(self.group) == "arc"))
        except Exception:
            pass
        if self.index is None:
            self.index = len(scene.groups)
        scene.groups.insert(min(self.index, len(scene.groups)), self.group)
        scene.version += 1

    def undo(self, scene):
        scene.groups.remove(self.group)
        scene.selection.discard(self.group)
        scene.version += 1


class CreateWalls(Command):
    """Create several independent walls as one history operation.

    Used by the rectangular wall-block creation modes so a four-wall rectangle
    is undone/redone atomically even though each side remains an independent
    parametric wall object.
    """
    def __init__(self, groups):
        self.groups = list(groups)
        self.index = None

    def do(self, scene):
        if not self.groups:
            raise WallError("Nenhuma parede foi criada.")
        if any(group in scene.groups for group in self.groups):
            raise WallError("Uma das paredes já está no documento.")
        if self.index is None:
            self.index = len(scene.groups)
        at = min(self.index, len(scene.groups))
        inserted = []
        try:
            from .bim import ensure_ifc_identity
            for i, group in enumerate(self.groups):
                ensure_ifc_identity(group, "IfcWall")
                rec = wall_record(group) or {}
                stamp_structured_materials(group, scene, rec)
                try:
                    finalize_wall_surface_maps(group.children, rec, wall_path(group),
                                               smooth_path=(wall_path_kind(group) == "arc"))
                except Exception:
                    pass
                scene.groups.insert(at + i, group)
                inserted.append(group)
        except Exception:
            for group in inserted:
                if group in scene.groups:
                    scene.groups.remove(group)
            raise
        scene.version += 1

    def undo(self, scene):
        for group in self.groups:
            if group in scene.groups:
                scene.groups.remove(group)
            scene.selection.discard(group)
        scene.version += 1


class EditWall(Command):
    def __init__(self, scene, group, values):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group):
            raise WallError("A parede está indisponível ou bloqueada.")
        old = read_wall(group)
        raw_values = dict(values)
        explicit_profiles = bool(raw_values.pop("_explicit_profiles", False))
        p = validate(raw_values)
        # The familiar scalar Height field is a deliberate "make both ends this
        # high" operation.  Endpoint tools edit the profile arrays directly;
        # if only the scalar changed, flatten the top to that height above each
        # local base endpoint instead of silently ignoring the field.
        try:
            requested_height = float(raw_values.get("height", old["height"]))
        except (TypeError, ValueError):
            requested_height = old["height"]
        profile_unchanged = (raw_values.get("base_profile", old.get("base_profile")) == old.get("base_profile")
                             and raw_values.get("top_profile", old.get("top_profile")) == old.get("top_profile")
                             and raw_values.get("top_xy", old.get("top_xy")) == old.get("top_xy"))
        if (not explicit_profiles and
                abs(requested_height - float(old["height"])) > 1.0e-9 and profile_unchanged):
            p["base_profile"] = list(old.get("base_profile", [0.0, 0.0]))
            p["top_profile"] = [b + requested_height for b in p["base_profile"]]
            p["height"] = requested_height
            p = validate(p)
        rec = wall_record(group)
        kind = wall_path_kind(group)
        path = wall_path(group)
        # Length editing remains meaningful only for a simple straight wall.
        # Arc length is derived from its chord + sagitta and is edited through
        # the arc handle, not by silently changing an endpoint here.
        if kind == "line" and abs(p["length"] - old["length"]) > 1e-9:
            d = path[1] - path[0]
            if d.length() < 1e-9:
                raise WallError("Trajetória da parede inválida.")
            path[1] = path[0] + d.normalized() * p["length"]
            path_record = None
            p["length"] = path_length(path)
        else:
            path_record = copy.deepcopy(rec.get("path")) if rec else None
            p["length"] = path_length_from_record(rec) if rec else path_length(path)
        children = build_children(p, previous_children=group.children, path=path,
                                  smooth_path=(kind == "arc"))
        temp = type("_LayerHolder", (), {})(); temp.children=children
        stamp_structured_materials(temp, scene, p, clear=True)
        # Material stamping is intentionally followed by the surface-map pass:
        # otherwise a twisted straight wall previews correctly but loses its
        # continuous UV map when the command is committed.
        finalize_wall_surface_maps(children, p, path, smooth_path=(kind == "arc"))
        ext = copy.deepcopy(group.ext)
        ext[KEY] = record(p, path, path_record=path_record)
        ext.pop(DERIVED_KEY, None)
        self.group = group
        self.before = (list(group.children), copy.deepcopy(group.ext), QMatrix4x4(group.xform))
        self.after = (children, ext, edit_placement(group, p["base"]))

    def _apply(self, scene, state):
        if self.group not in scene.groups:
            raise WallError("A parede não está mais neste documento.")
        children, ext, transform = state
        self.group.children = list(children)
        self.group.ext = copy.deepcopy(ext)
        self.group.xform = QMatrix4x4(transform)
        scene.version += 1

    def do(self, scene):
        self._apply(scene, self.after)

    def undo(self, scene):
        self._apply(scene, self.before)


class EditWallPath(Command):
    """Replace only the reference path, in one undo step."""
    def __init__(self, scene, group, path):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group):
            raise WallError("A parede está indisponível ou bloqueada.")
        p = read_wall(group)
        path = list(path)
        p["length"] = path_length(path)
        p = validate(p)
        children = build_children(p, previous_children=group.children, path=path)
        ext = copy.deepcopy(group.ext)
        ext[KEY] = record(p, path)
        ext.pop(DERIVED_KEY, None)
        self.group = group
        self.before = (list(group.children), copy.deepcopy(group.ext))
        self.after = (children, ext)

    def _apply(self, scene, state):
        if self.group not in scene.groups:
            raise WallError("A parede não está mais neste documento.")
        children, ext = state
        self.group.children = list(children)
        self.group.ext = copy.deepcopy(ext)
        scene.version += 1

    def do(self, scene):
        self._apply(scene, self.after)

    def undo(self, scene):
        self._apply(scene, self.before)


class SetWallArc(Command):
    """Convert/edit one straight wall as a circular arc with fixed endpoints."""
    def __init__(self, scene, group, sagitta):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group):
            raise WallError("A parede está indisponível ou bloqueada.")
        kind = wall_path_kind(group)
        if kind not in ("line", "arc"):
            raise WallError("Curvar em arco aceita, por enquanto, uma parede reta ou um arco existente.")
        values = read_wall(group)
        refs = wall_reference_vertices(group)
        if len(refs) != 2:
            raise WallError("A parede precisa ter exatamente dois extremos para virar arco.")
        start, end = QVector3D(refs[0]), QVector3D(refs[1])
        chord = (end - start).length()
        if chord < MIN_DIM:
            raise WallError("A parede é curta demais para ser curvada.")
        h = float(sagitta)
        if abs(h) > chord * 5.0:
            raise WallError("A flecha está excessiva para esta parede.")

        # Avoid an offset side collapsing through the circle centre.
        if abs(h) >= ARC_EPS:
            radius = chord * chord / (8.0 * abs(h)) + abs(h) / 2.0
            from .model import wall_offsets
            low, high = wall_offsets(values)
            nearest_radius = (radius + min(low, high) if h > 0.0
                              else radius - max(low, high))
            if nearest_radius <= max(MIN_DIM, abs(high-low) * 0.02):
                raise WallError("A curvatura é fechada demais para esta espessura/alinhamento.")

        path_rec = arc_record(start, end, h)
        samples = arc_points(start, end, h)
        values["length"] = path_length_from_record({"path": path_rec})
        children = build_children(values, previous_children=group.children, path=samples,
                                  smooth_path=(path_rec.get("type") == "arc"))
        ext = copy.deepcopy(group.ext)
        ext[KEY] = record(values, samples, path_record=path_rec)
        ext.pop(DERIVED_KEY, None)
        self.group = group
        self.before = (list(group.children), copy.deepcopy(group.ext))
        self.after = (children, ext)

    def _apply(self, scene, state):
        if self.group not in scene.groups:
            raise WallError("A parede não está mais neste documento.")
        children, ext = state
        self.group.children = list(children)
        self.group.ext = copy.deepcopy(ext)
        scene.version += 1

    def do(self, scene):
        self._apply(scene, self.after)

    def undo(self, scene):
        self._apply(scene, self.before)




class ReshapeWall(Command):
    """Move wall endpoints while preserving the wall object identity and metadata."""
    def __init__(self, scene, group, start_world, end_world, sagitta=None):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group):
            raise WallError("A parede está indisponível ou bloqueada.")
        values = read_wall(group)
        start = QVector3D(start_world)
        end = QVector3D(end_world)
        if (end - start).length() < MIN_DIM:
            raise WallError("A parede precisa ter ao menos 1 mm de comprimento.")
        if sagitta is None or abs(float(sagitta)) < ARC_EPS:
            fresh = make_wall_segment(start, end, values, template=group)
        else:
            fresh = make_arc_wall(start, end, float(sagitta), values, template=group)
        self.group = group
        self.before = (list(group.children), copy.deepcopy(group.ext), QMatrix4x4(group.xform))
        self.after = (list(fresh.children), copy.deepcopy(fresh.ext), QMatrix4x4(fresh.xform))

    def _apply(self, scene, state):
        if self.group not in scene.groups:
            raise WallError("A parede não está mais neste documento.")
        children, ext, transform = state
        self.group.children = list(children)
        self.group.ext = copy.deepcopy(ext)
        self.group.xform = QMatrix4x4(transform)
        scene.version += 1

    def do(self, scene):
        self._apply(scene, self.after)

    def undo(self, scene):
        self._apply(scene, self.before)




def _segment_profile_values(group, values, fraction0, fraction1, start_world, end_world):
    """Map a parent wall endpoint profile into a newly split segment frame."""
    v = copy.deepcopy(values)
    b0,t0,o0 = profile_at_fraction(values, fraction0)
    b1,t1,o1 = profile_at_fraction(values, fraction1)
    # Original top offsets are local vectors.  Convert to world, then express
    # them in the new segment's local chord frame.
    wo0 = group.xform.mapVector(o0); wo1 = group.xform.mapVector(o1)
    d = QVector3D(end_world.x()-start_world.x(), end_world.y()-start_world.y(), 0.0)
    L = d.length()
    if L < MIN_DIM:
        raise WallError("Um dos novos trechos ficaria menor que 1 mm.")
    ux = QVector3D(d.x()/L, d.y()/L, 0.0)
    uy = QVector3D(-ux.y(), ux.x(), 0.0)
    def local_off(w):
        return [QVector3D.dotProduct(w, ux), QVector3D.dotProduct(w, uy)]
    v["base_profile"] = [b0, b1]
    v["top_profile"] = [t0, t1]
    v["top_xy"] = [local_off(wo0), local_off(wo1)]
    v["height"] = max(t0-b0, t1-b1)
    return v

class ReplaceWallWithSegments(Command):
    """Replace one parametric path wall by independent straight wall segments.

    The operation is atomic in history. It also migrates a legacy polyline wall
    from the 0.2.0 development build when a new vertex is inserted into it.
    """
    def __init__(self, scene, group, world_points):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group):
            raise WallError("A parede está indisponível ou bloqueada.")
        values = read_wall(group)
        pts = list(world_points)
        if len(pts) < 2:
            raise WallError("A parede precisa ter ao menos dois pontos.")
        for a, b in zip(pts, pts[1:]):
            if (b - a).length() < MIN_DIM:
                raise WallError("Um dos novos trechos ficaria menor que 1 mm.")
        self.group = group
        self.index = scene.groups.index(group)
        lengths=[0.0]
        for a,b in zip(pts,pts[1:]): lengths.append(lengths[-1]+(b-a).length())
        total=max(lengths[-1],MIN_DIM)
        self.segments=[]
        for i,(a,b) in enumerate(zip(pts,pts[1:])):
            sv=_segment_profile_values(group,values,lengths[i]/total,lengths[i+1]/total,a,b)
            self.segments.append(make_wall_segment(a,b,sv,template=group))

    def do(self, scene):
        if self.group in scene.groups:
            scene.groups.remove(self.group)
        for g in self.segments:
            if g in scene.groups:
                scene.groups.remove(g)
        at = min(self.index, len(scene.groups))
        for i, g in enumerate(self.segments):
            scene.groups.insert(at + i, g)
        scene.selection.clear()
        if self.segments:
            # Keep one segment selected so the reference-line workflow remains
            # immediately available; every other segment is already independent.
            scene.selection.add(self.segments[0])
        scene.version += 1

    def undo(self, scene):
        for g in self.segments:
            if g in scene.groups:
                scene.groups.remove(g)
        if self.group not in scene.groups:
            scene.groups.insert(min(self.index, len(scene.groups)), self.group)
        scene.selection.clear()
        scene.selection.add(self.group)
        scene.version += 1


def _cross2(a, b):
    return a.x() * b.y() - a.y() * b.x()


def _infinite_line_intersection(a0, a1, b0, b1):
    ra = a1 - a0
    rb = b1 - b0
    den = _cross2(ra, rb)
    if abs(den) < 1.0e-9:
        return None
    q = b0 - a0
    t = _cross2(q, rb) / den
    return a0 + ra * t


class MeetWalls(Command):
    """Extend/trim the nearest ends of two straight walls to their intersection.

    This is the architectural equivalent of CAD extend/trim in one operation:
    the infinite reference lines define the meeting point; for each wall, the
    endpoint nearest that point is replaced by the intersection.  The junction
    resolver then derives the physical miter from the shared reference node.
    """
    def __init__(self, scene, first, second):
        root_edit_allowed(scene)
        if first is second:
            raise WallError("Selecione duas paredes diferentes.")
        for group in (first, second):
            if group not in scene.groups or not scene.entity_selectable(group):
                raise WallError("Uma das paredes está indisponível ou bloqueada.")
            if wall_path_kind(group) != "line":
                raise WallError("Encontrar paredes aceita, por enquanto, apenas paredes retas.")

        values_a, values_b = read_wall(first), read_wall(second)
        if abs(values_a["base"] - values_b["base"]) > 1.0e-4:
            raise WallError("As paredes estão em cotas diferentes e não podem formar a mesma junção.")

        pa = path_world(first)
        pb = path_world(second)
        hit = _infinite_line_intersection(pa[0], pa[1], pb[0], pb[1])
        if hit is None:
            raise WallError("As linhas de referência são paralelas; não há um encontro único.")
        hit.setZ(values_a["base"])

        self.groups = (first, second)
        self.before = [self._snapshot(first), self._snapshot(second)]
        self.after = []
        for group, values, pts in ((first, values_a, pa), (second, values_b, pb)):
            d0 = (pts[0] - hit).length()
            d1 = (pts[1] - hit).length()
            new_pts = [QVector3D(pts[0]), QVector3D(pts[1])]
            new_pts[0 if d0 <= d1 else 1] = QVector3D(hit.x(), hit.y(), values["base"])
            length = (new_pts[1] - new_pts[0]).length()
            if length < MIN_DIM:
                raise WallError("O encontro deixaria uma das paredes menor que 1 mm.")
            if length > MAX_DIM:
                raise WallError("O encontro deixaria uma das paredes maior que 10.000 m.")
            temp = make_wall_segment(new_pts[0], new_pts[1], values, template=group)
            self.after.append((list(temp.children), copy.deepcopy(temp.ext),
                               QMatrix4x4(temp.xform)))

    @staticmethod
    def _snapshot(group):
        return (list(group.children), copy.deepcopy(group.ext), QMatrix4x4(group.xform))

    def _apply(self, scene, states):
        for group, state in zip(self.groups, states):
            if group not in scene.groups:
                raise WallError("Uma das paredes não está mais neste documento.")
            children, ext, transform = state
            group.children = list(children)
            group.ext = copy.deepcopy(ext)
            group.xform = QMatrix4x4(transform)
        scene.selection.clear()
        scene.selection.update(self.groups)
        scene.version += 1

    def do(self, scene):
        self._apply(scene, self.after)

    def undo(self, scene):
        self._apply(scene, self.before)

class ReplaceArcWallWithArcs(Command):
    """Split one circular wall into two independent circular walls."""
    def __init__(self, scene, group, split_world, sagitta_a, sagitta_b):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group):
            raise WallError("A parede está indisponível ou bloqueada.")
        if wall_path_kind(group) != "arc":
            raise WallError("Esta operação requer uma parede curva.")
        values=read_wall(group);refs=reference_vertices_world(group)
        if len(refs)!=2:raise WallError("A parede curva precisa ter dois extremos.")
        self.group=group;self.index=scene.groups.index(group)
        l0=path_length_from_record({"path":arc_record(refs[0],split_world,float(sagitta_a))})
        l1=path_length_from_record({"path":arc_record(split_world,refs[1],float(sagitta_b))})
        f=0.5 if l0+l1<=1.0e-12 else l0/(l0+l1)
        va=_segment_profile_values(group,values,0.0,f,refs[0],split_world)
        vb=_segment_profile_values(group,values,f,1.0,split_world,refs[1])
        self.segments=[make_arc_wall(refs[0],split_world,float(sagitta_a),va,template=group),
                       make_arc_wall(split_world,refs[1],float(sagitta_b),vb,template=group)]

    def do(self, scene):
        if self.group in scene.groups:scene.groups.remove(self.group)
        for g in self.segments:
            if g in scene.groups:scene.groups.remove(g)
        at=min(self.index,len(scene.groups))
        for i,g in enumerate(self.segments):scene.groups.insert(at+i,g)
        scene.selection.clear()
        for g in self.segments:scene.selection.add(g)
        scene.version+=1

    def undo(self, scene):
        for g in self.segments:
            if g in scene.groups:scene.groups.remove(g)
        if self.group not in scene.groups:scene.groups.insert(min(self.index,len(scene.groups)),self.group)
        scene.selection.clear();scene.selection.add(self.group);scene.version+=1
