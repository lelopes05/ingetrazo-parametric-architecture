# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive editing tools for slab reference polygons."""
from __future__ import annotations

import math
from PySide6.QtCore import QTimer
from PySide6.QtGui import QMatrix4x4, QVector3D
from tools.base import AxisMagnet, Tool
from core.history import MoveGroupCommand

from .commands import root_edit_allowed
from .slab_commands import EditSlab
from .slab_model import (MIN_DIM, MAX_DIM, ARC_EPS, SlabError, edge_outward_normal,
                         edge_length, edge_point, line_edge, normalize_edge_specs,
                         offset_boundary, sample_boundary, slab_edge_specs,
                         slab_polygon_world, solve_corner_fillet, split_arc_edge,
                         trim_edge_spec, validate_edge_geometry, validate_polygon, read_slab)
from .levels import level_by_name
from .path_edit import _vertical_view_plane


def _project_to_segment(p, a, b):
    d = b - a; d.setZ(0)
    den = d.x() * d.x() + d.y() * d.y()
    if den <= 1e-12:
        return QVector3D(a), 0.0
    t = ((p.x() - a.x()) * d.x() + (p.y() - a.y()) * d.y()) / den
    t = max(0.0, min(1.0, t))
    return a + d * t, t


def _preview_lines(points, specs):
    try:
        sampled = sample_boundary(points, specs)
    except SlabError:
        return []
    z = points[0].z() if points else 0.0
    ring = [QVector3D(p.x(), p.y(), z) for p in sampled]
    return [(a, b) for a, b in zip(ring, ring[1:] + ring[:1])]


def _distance_xy(a, b):
    return math.hypot(a.x() - b.x(), a.y() - b.y())


class _SlabEditBase(AxisMagnet, Tool):
    wireframe_color = (0.15, 0.45, 0.85, 1.0)
    def __init__(self, controller):
        self.controller = controller
        self.slab = None
        self.index = None
        self.anchor = None
        self.hover = None

    architecture_angle_snap = True
    def arm(self, slab, index, anchor):
        self.slab = slab; self.index = int(index); self.anchor = QVector3D(anchor); self.hover = QVector3D(anchor); self.start_point=QVector3D(anchor)

    def reset(self):
        self.slab = None; self.index = None; self.anchor = None; self.hover = None; self.start_point=None

    def drag_plane(self, viewport):
        z = self.anchor.z() if self.anchor is not None else 0.0
        return QVector3D(0, 0, z), QVector3D(0, 0, 1)

    def point(self, ctx):
        z = self.anchor.z() if self.anchor is not None else ctx.world.z()
        return QVector3D(ctx.world.x(), ctx.world.y(), z)

    def on_activate(self, viewport):
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset(); viewport.update()

    def on_cancel(self, viewport):
        self.reset(); QTimer.singleShot(0, self.controller.return_to_select)

    def _commit(self, viewport, points, specs, message):
        validate_polygon(points); validate_edge_geometry(points, specs)
        viewport.history.execute(EditSlab(viewport.scene, self.slab,
                                          world_polygon=points,
                                          edge_specs=specs))
        if viewport.history.last_error:
            raise SlabError(viewport.history.last_error)
        viewport.notify_scene_changed(); self.controller.message(message)
        self.reset(); QTimer.singleShot(0, self.controller.return_to_select)


class InsertSlabVertexTool(_SlabEditBase):
    name = "Inserir vértice na laje"
    description = "Inserir um vértice na aresta selecionada."

    def on_click(self, ctx):
        try:
            root_edit_allowed(ctx.viewport.scene)
            if self.slab is None:
                raise SlabError("Escolha primeiro uma aresta da laje.")
            pts = slab_polygon_world(self.slab, reference=True); specs = slab_edge_specs(self.slab)
            i = self.index % len(pts); j = (i + 1) % len(pts)
            if specs[i].get("type") == "arc":
                q, s1, s2, t = split_arc_edge(pts[i], pts[j], specs[i].get("sagitta", 0.0), self.point(ctx))
                if (q - pts[i]).length() < MIN_DIM or (q - pts[j]).length() < MIN_DIM:
                    raise SlabError("Insira o vértice afastado das extremidades da aresta.")
                new = list(pts); new.insert(i + 1, q)
                new_specs = list(specs); new_specs[i:i+1] = [s1, s2]
            else:
                q, t = _project_to_segment(self.point(ctx), pts[i], pts[j])
                if t <= 0.01 or t >= 0.99 or (q - pts[i]).length() < MIN_DIM or (q - pts[j]).length() < MIN_DIM:
                    raise SlabError("Insira o vértice afastado das extremidades da aresta.")
                new = list(pts); new.insert(i + 1, q)
                new_specs = list(specs); new_specs[i:i+1] = [line_edge(), line_edge()]
            self._commit(ctx.viewport, new, new_specs, "Vértice inserido.")
        except SlabError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_hover(self, ctx):
        self.hover = self.point(ctx); ctx.viewport.update()


class StretchSlabEdgeTool(_SlabEditBase):
    name = "Estender aresta da laje"
    description = "Extrudar uma aresta perpendicularmente, preservando os vértices originais como ancoragens."

    def __init__(self, controller):
        super().__init__(controller); self.original = None; self.specs = None; self.normal = None

    def arm(self, slab, index, anchor):
        super().arm(slab, index, anchor)
        pts = slab_polygon_world(slab, reference=True); specs=slab_edge_specs(slab)
        i = self.index % len(pts); j = (i + 1) % len(pts)
        d = pts[j] - pts[i]; d.setZ(0)
        length = math.hypot(d.x(), d.y())
        if length < MIN_DIM:
            raise SlabError("A aresta é curta demais para ser estendida.")
        self.original = pts; self.specs = specs
        self.normal = QVector3D(-d.y() / length, d.x() / length, 0.0)

    def reset(self):
        super().reset(); self.original = None; self.specs = None; self.normal = None

    def _candidate(self, p):
        if self.original is None or self.normal is None:
            return None
        delta = QVector3D.dotProduct(p - self.anchor, self.normal)
        pts = [QVector3D(v) for v in self.original]
        specs = [dict(s) for s in self.specs]
        n = len(pts); i = self.index % n; j = (i + 1) % n
        a = QVector3D(pts[i]); b = QVector3D(pts[j])
        a2 = a + self.normal * delta; b2 = b + self.normal * delta
        old_spec = dict(specs[i])
        # Rotate the polygon so the selected edge is first. Rotation does not
        # change the slab shape, and makes the cyclic closing-edge case identical
        # to every other edge. The old endpoints stay in place as anchors.
        tail_vertices = [QVector3D(pts[(i + k) % n]) for k in range(2, n)]
        new_pts = [a, a2, b2, b] + tail_vertices
        tail_specs = [dict(specs[(i + k) % n]) for k in range(1, n)]
        new_specs = [line_edge(), old_spec, line_edge()] + tail_specs
        return new_pts, normalize_edge_specs(new_specs, len(new_pts))

    def on_hover(self, ctx):
        self.hover = self.point(ctx); ctx.viewport.update()

    def on_click(self, ctx):
        try:
            cand = self._candidate(self.point(ctx))
            if cand is None:
                raise SlabError("Escolha primeiro uma aresta da laje.")
            pts,specs=cand
            self._commit(ctx.viewport, pts, specs, "Aresta da laje estendida com vértices de ancoragem.")
        except SlabError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def rubber_band_lines(self):
        if self.hover is None: return []
        cand=self._candidate(self.hover)
        return [] if cand is None else _preview_lines(*cand)


class MoveSlabVertexTool(_SlabEditBase):
    name = "Mover vértice da laje"
    description = "Mover um vértice da laje livremente no plano horizontal; sobre um vizinho, os dois são fundidos."
    MERGE_TOL = 1.0e-4

    def __init__(self, controller):
        super().__init__(controller); self.original = None; self.specs=None; self._merge=False

    def arm(self, slab, index, anchor):
        super().arm(slab, index, anchor); self.original = slab_polygon_world(slab, reference=True); self.specs=slab_edge_specs(slab); self._merge=False

    def reset(self):
        super().reset(); self.original = None; self.specs=None; self._merge=False

    def _ctx_point(self,ctx):
        snap=getattr(ctx,"snap",None)
        if snap is not None and getattr(snap,"point",None) is not None:
            q=snap.point; return QVector3D(q.x(),q.y(),self.original[0].z() if self.original else q.z())
        return self.point(ctx)

    def _merge_candidate(self,target_index):
        n=len(self.original); i=self.index%n; j=target_index%n
        if j not in ((i-1)%n,(i+1)%n):
            raise SlabError("Por enquanto, só é possível unir vértices vizinhos da laje.")
        prev_i=(i-1)%n; next_i=(i+1)%n
        keep=[k for k in range(n) if k!=i]
        pts=[QVector3D(self.original[k]) for k in keep]
        specs=[]
        for pos,a_idx in enumerate(keep):
            b_idx=keep[(pos+1)%len(keep)]
            if a_idx==prev_i and b_idx==next_i:
                spec_idx=prev_i if j==next_i else i
            else:
                spec_idx=a_idx
            specs.append(dict(self.specs[spec_idx]))
        self._merge=True
        return pts,normalize_edge_specs(specs,len(pts))

    def _candidate(self, p):
        if self.original is None: return None
        n=len(self.original); i=self.index%n; q=QVector3D(p.x(),p.y(),self.original[0].z()); self._merge=False
        nearest=None
        for j,v in enumerate(self.original):
            if j==i: continue
            d=_distance_xy(q,v)
            if d<=self.MERGE_TOL and (nearest is None or d<nearest[0]): nearest=(d,j)
        if nearest is not None:
            return self._merge_candidate(nearest[1])
        pts=[QVector3D(v) for v in self.original]; pts[i]=q
        return pts,[dict(s) for s in self.specs]

    def on_hover(self, ctx): self.hover=self._ctx_point(ctx); ctx.viewport.update()

    def on_click(self, ctx):
        try:
            cand=self._candidate(self._ctx_point(ctx))
            if cand is None: raise SlabError("Escolha primeiro um vértice da laje.")
            self._commit(ctx.viewport,*cand,"Vértices unidos." if self._merge else "Vértice da laje movido.")
        except SlabError as exc: self.controller.message(str(exc),error=True)
        ctx.viewport.update()

    def rubber_band_lines(self):
        if self.hover is None:return []
        try:
            cand=self._candidate(self.hover); return [] if cand is None else _preview_lines(*cand)
        except SlabError:return []


class CurveSlabEdgeTool(_SlabEditBase):
    name="Curvar aresta da laje"
    description="Curvar a aresta mantendo suas duas extremidades."
    def __init__(self,controller):
        super().__init__(controller); self.original=None; self.specs=None; self.mid=None; self.normal=None
    def arm(self,slab,index,anchor):
        super().arm(slab,index,anchor); self.original=slab_polygon_world(slab,reference=True); self.specs=slab_edge_specs(slab)
        i=self.index%len(self.original); a=self.original[i]; b=self.original[(i+1)%len(self.original)]; d=b-a; d.setZ(0); L=math.hypot(d.x(),d.y())
        if L<MIN_DIM: raise SlabError("A aresta é curta demais para ser curvada.")
        self.mid=(a+b)*0.5; self.normal=QVector3D(-d.y()/L,d.x()/L,0.0)
    def reset(self): super().reset(); self.original=None; self.specs=None; self.mid=None; self.normal=None
    def _candidate(self,p):
        if self.original is None:return None
        h=QVector3D.dotProduct(p-self.mid,self.normal); specs=[dict(s) for s in self.specs]; specs[self.index%len(specs)] = line_edge() if abs(h)<ARC_EPS else {"type":"arc","sagitta":float(h)}
        return [QVector3D(v) for v in self.original],specs
    def on_hover(self,ctx): self.hover=self.point(ctx);ctx.viewport.update()
    def on_click(self,ctx):
        try:
            cand=self._candidate(self.point(ctx)); self._commit(ctx.viewport,*cand,"Curvatura da aresta atualizada.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def rubber_band_lines(self):
        if self.hover is None:return []
        cand=self._candidate(self.hover);return [] if cand is None else _preview_lines(*cand)


class _CornerEditBase(_SlabEditBase):
    def __init__(self,controller):
        super().__init__(controller); self.original=None; self.specs=None; self.prev=None; self.vertex=None; self.next=None; self.prev_len=None; self.next_len=None; self.max_t=None
    def arm(self,slab,index,anchor):
        super().arm(slab,index,anchor); self.original=slab_polygon_world(slab,reference=True); self.specs=slab_edge_specs(slab)
        n=len(self.original);i=self.index%n;pi=(i-1)%n
        self.prev=QVector3D(self.original[pi]);self.vertex=QVector3D(self.original[i]);self.next=QVector3D(self.original[(i+1)%n])
        self.prev_len=edge_length(self.prev,self.vertex,self.specs[pi]);self.next_len=edge_length(self.vertex,self.next,self.specs[i])
        if self.prev_len<2*MIN_DIM or self.next_len<2*MIN_DIM:raise SlabError("As arestas ao redor deste vértice são curtas demais.")
        # The gesture is limited only by the next logical vertices. Curved edges
        # keep their exact circular geometry while being trimmed.
        self.max_t=max(MIN_DIM,min(self.prev_len,self.next_len)-MIN_DIM)
    def reset(self):
        super().reset();self.original=None;self.specs=None;self.prev=self.vertex=self.next=None;self.prev_len=self.next_len=self.max_t=None
    def _size(self,p):return max(MIN_DIM,min(self.max_t,_distance_xy(p,self.vertex)))
    def _build_replacement(self,p1,p2,prev_fraction,next_fraction,bridge_spec):
        """Replace one corner by two trim points, preserving curved neighbours."""
        n=len(self.original);i=self.index%n;pi=(i-1)%n
        prev_spec=trim_edge_spec(self.prev,self.vertex,self.specs[pi],0.0,prev_fraction)
        next_spec=trim_edge_spec(self.vertex,self.next,self.specs[i],next_fraction,1.0)
        segs=[(QVector3D(p1),QVector3D(p2),dict(bridge_spec)),
              (QVector3D(p2),QVector3D(self.next),dict(next_spec))]
        k=(i+1)%n
        while k!=pi:
            a=QVector3D(self.original[k]);b=QVector3D(self.original[(k+1)%n]);segs.append((a,b,dict(self.specs[k])));k=(k+1)%n
        segs.append((QVector3D(self.prev),QVector3D(p1),dict(prev_spec)))
        pts=[QVector3D(a) for a,_b,_spec in segs]; specs=[dict(spec) for _a,_b,spec in segs]
        return pts,normalize_edge_specs(specs,len(pts))
    def _trim_by_distance(self,t):
        tp=max(0.0,min(1.0,1.0-t/self.prev_len));tn=max(0.0,min(1.0,t/self.next_len))
        p1=edge_point(self.prev,self.vertex,self.specs[(self.index-1)%len(self.original)],tp)
        p2=edge_point(self.vertex,self.next,self.specs[self.index%len(self.original)],tn)
        return p1,p2,tp,tn


class ChamferSlabVertexTool(_CornerEditBase):
    name="Chanfrar vértice da laje"; description="Criar um chanfro reto, inclusive entre arestas curvas."
    def _candidate(self,p):
        p1,p2,tp,tn=self._trim_by_distance(self._size(p));return self._build_replacement(p1,p2,tp,tn,line_edge())
    def on_hover(self,ctx):self.hover=self.point(ctx);ctx.viewport.update()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,*self._candidate(self.point(ctx)),"Chanfro criado.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def rubber_band_lines(self):return [] if self.hover is None else _preview_lines(*self._candidate(self.hover))


class FilletSlabVertexTool(_CornerEditBase):
    name="Arredondar vértice da laje"; description="Criar um fillet circular tangente a arestas retas ou curvas."
    def _candidate(self,p):
        # Mouse distance controls the requested radius. The exact solver clamps
        # it only if a tangency would pass the next logical vertex.
        req=max(MIN_DIM,_distance_xy(p,self.vertex))
        sol=solve_corner_fillet(self.original,self.specs,self.index,req)
        return self._build_replacement(sol["p1"],sol["p2"],sol["prev_fraction"],sol["next_fraction"],sol["spec"])
    def on_hover(self,ctx):self.hover=self.point(ctx);ctx.viewport.update()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,*self._candidate(self.point(ctx)),"Fillet criado.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def rubber_band_lines(self):
        if self.hover is None:return []
        try:return _preview_lines(*self._candidate(self.hover))
        except SlabError:return []


class MoveSlabTool(AxisMagnet, Tool):
    """Move a whole slab only in XY or only in Z."""
    uses_snap = True
    wireframe_color = (0.55, 0.36, 0.84, 1.0)

    def __init__(self, controller, mode):
        self.controller=controller; self.mode=mode; self.architecture_angle_snap=(mode=="xy")
        self.name = "Mover laje no plano" if mode=="xy" else "Mover laje na vertical"
        self.description=self.name; self.reset()

    def arm(self, slab, _index, anchor):
        self.slab=slab; self.anchor=QVector3D(anchor); self.scene=self.controller.app.scene
        self.start_point=QVector3D(anchor); self.cursor_origin=None; self.delta=QVector3D(0,0,0)

    def reset(self):
        self.slab=None; self.anchor=None; self.scene=None; self.cursor_origin=None; self.start_point=None
        self.delta=QVector3D(0,0,0); self.preview=False

    def on_activate(self, viewport):
        if self.slab is None or self.anchor is None:
            QTimer.singleShot(0,self.controller.return_to_select);return
        try:
            if self.slab not in viewport.scene.groups: raise SlabError("A laje não está mais disponível.")
            viewport.begin_groups_preview([self.slab]);self.preview=True
            self.controller.message("Mova a laje no plano horizontal e clique." if self.mode=="xy" else "Mova a laje somente em Z e clique.")
        except SlabError as exc:self.controller.message(str(exc),error=True);QTimer.singleShot(0,self.controller.return_to_select)

    def on_deactivate(self,viewport):
        if self.preview:viewport.end_groups_preview()
        self.reset();viewport.update()

    def drag_plane(self,viewport):
        if self.anchor is None:return None
        return (QVector3D(0,0,self.anchor.z()),QVector3D(0,0,1)) if self.mode=="xy" else _vertical_view_plane(viewport,self.anchor)

    def _delta(self,p):
        o=self.cursor_origin or p
        return QVector3D(p.x()-o.x(),p.y()-o.y(),0) if self.mode=="xy" else QVector3D(0,0,p.z()-o.z())

    def on_hover(self,ctx):
        if self.slab is None:return
        if self.cursor_origin is None:
            self.cursor_origin=QVector3D(ctx.world); self.start_point=QVector3D(ctx.world)
        self.delta=self._delta(ctx.world)
        if self.preview:ctx.viewport.set_groups_preview_offset(self.delta)
        ctx.viewport.update()

    def on_click(self,ctx):
        try:
            if self.cursor_origin is None:self.cursor_origin=QVector3D(ctx.world)
            self.delta=self._delta(ctx.world)
            if self.preview:ctx.viewport.end_groups_preview();self.preview=False
            if self.delta.length()>1e-9:
                if self.mode=="xy":
                    ctx.viewport.history.execute(MoveGroupCommand(self.slab,self.delta))
                else:
                    vals=read_slab(self.slab); vals["base_z"]+=self.delta.z()
                    if vals.get("base_level"):
                        lv=level_by_name(self.controller.app,vals.get("base_level"))
                        if lv is not None: vals["base_offset"]=vals["base_z"]-float(lv["z"])
                    ctx.viewport.history.execute(EditSlab(ctx.viewport.scene,self.slab,values=vals))
                if ctx.viewport.history.last_error:raise SlabError(ctx.viewport.history.last_error)
                ctx.viewport.notify_scene_changed()
            self.controller.message("Laje movida no plano horizontal." if self.mode=="xy" else "Laje movida na vertical.")
            self.reset();self.controller.return_to_select()
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()

    def on_cancel(self,viewport):
        if self.preview:viewport.end_groups_preview();self.preview=False
        self.reset();self.controller.return_to_select();self.controller.message("Movimento cancelado.");viewport.update()


class ChangeSlabThicknessTool(Tool):
    """Change slab thickness from a physical-top vertex, base kept fixed."""
    name="Alterar espessura da laje";description="Arrastar a face superior mantendo a base da laje fixa."
    uses_snap=True;wireframe_color=(0.95,0.62,0.18,1.0);vcb_label="Espessura"

    def __init__(self,controller):self.controller=controller;self.reset()
    def arm(self,slab,_index,anchor):
        self.slab=slab;self.anchor=QVector3D(anchor);self.scene=self.controller.app.scene
        # Use the physical top handle as the drag origin.  The previous tool
        # initialized the origin on the first hover event, which could already
        # be displaced/snapped and made upward thickening feel locked.
        self.origin_z=float(self.anchor.z())
    def reset(self):self.slab=None;self.anchor=None;self.scene=None;self.values=None;self.origin_z=None;self.new_thickness=None;self.preview=False
    def drag_plane(self,viewport):return _vertical_view_plane(viewport,self.anchor) if self.anchor is not None else None

    def on_activate(self,viewport):
        if self.slab is None or self.anchor is None:QTimer.singleShot(0,self.controller.return_to_select);return
        try:
            self.values=read_slab(self.slab);self.new_thickness=self.values["thickness"]
            viewport.begin_groups_preview([self.slab]);self.preview=True
            self.controller.message("Mova o topo em Z e clique; o valor aparece junto ao controle e também pode ser digitado.")
        except SlabError as exc:self.controller.message(str(exc),error=True);QTimer.singleShot(0,self.controller.return_to_select)

    def on_deactivate(self,viewport):
        if self.preview:viewport.end_groups_preview()
        self.reset();viewport.update()

    def _thickness(self,ctx):
        if ctx.snap is not None and getattr(ctx.snap,"kind",None) in {"endpoint","midpoint","arc_midpoint","center","origin","component_origin","intersection","close","reference"}:
            t=float(ctx.snap.point.z())-float(self.values["base_z"])
            if MIN_DIM<=t<=MAX_DIM:return t
        if self.origin_z is None:self.origin_z=float(self.anchor.z()) if self.anchor is not None else ctx.world.z()
        return max(MIN_DIM,min(MAX_DIM,self.values["thickness"]+ctx.world.z()-self.origin_z))

    def _preview(self,viewport,t):
        t=max(MIN_DIM,min(MAX_DIM,float(t)));self.new_thickness=t
        factor=t/self.values["thickness"];base=self.values["base_z"]
        m=QMatrix4x4();m.translate(0,0,base);m.scale(1,1,factor);m.translate(0,0,-base)
        if self.preview:viewport.set_groups_preview_matrix(m)

    def on_hover(self,ctx):
        if self.values:self._preview(ctx.viewport,self._thickness(ctx));ctx.viewport.update()

    def _commit(self,viewport,t):
        if self.preview:viewport.end_groups_preview();self.preview=False
        vals=dict(self.values);vals["thickness"]=max(MIN_DIM,min(MAX_DIM,float(t)))
        viewport.history.execute(EditSlab(viewport.scene,self.slab,values=vals))
        if viewport.history.last_error:raise SlabError(viewport.history.last_error)
        viewport.notify_scene_changed();self.controller.return_to_select();self.controller.message("Espessura da laje atualizada.")

    def on_click(self,ctx):
        try:self._commit(ctx.viewport,self._thickness(ctx))
        except SlabError as exc:self.controller.message(str(exc),error=True)

    def on_value(self,viewport,value):
        try:
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<MIN_DIM:raise SlabError("Digite uma espessura positiva, por exemplo 0,15 m.")
            self._commit(viewport,float(value));return True
        except SlabError as exc:self.controller.message(str(exc),error=True);return False

    def value_label(self):
        if self.new_thickness is None or self.anchor is None or self.values is None:return None
        p=QVector3D(self.anchor.x(),self.anchor.y(),self.values["base_z"]+self.new_thickness)
        return (f"{self.new_thickness:.4f} m".replace(".",","),p)

    def on_cancel(self,viewport):
        if self.preview:viewport.end_groups_preview();self.preview=False
        self.controller.return_to_select();self.controller.message("Alteração de espessura cancelada.");viewport.update()


class OffsetSlabBoundaryTool(_SlabEditBase):
    """Offset all reference edges together, preserving logical circular arcs."""
    name="Offset do contorno da laje";description="Deslocar todo o perímetro para dentro ou para fora.";uses_snap=False;vcb_label="Offset"

    def __init__(self,controller):
        super().__init__(controller);self.original=None;self.specs=None;self.normal=None;self.distance=0.0

    def arm(self,slab,index,anchor):
        super().arm(slab,index,anchor);self.original=slab_polygon_world(slab,reference=True);self.specs=slab_edge_specs(slab)
        self.normal=edge_outward_normal(self.original,self.specs,self.index,self.anchor);self.distance=0.0

    def reset(self):super().reset();self.original=None;self.specs=None;self.normal=None;self.distance=0.0

    def _candidate(self,p=None,distance=None):
        if self.original is None:return None
        d=float(distance if distance is not None else QVector3D.dotProduct(p-self.anchor,self.normal))
        self.distance=d
        return offset_boundary(self.original,self.specs,d)

    def on_hover(self,ctx):
        try:self.hover=self.point(ctx);self._candidate(self.hover);ctx.viewport.update()
        except SlabError:self.hover=self.point(ctx);ctx.viewport.update()

    def on_click(self,ctx):
        try:self._commit(ctx.viewport,*self._candidate(self.point(ctx)),"Offset da laje aplicado.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()

    def on_value(self,viewport,value):
        try:
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise SlabError("Digite uma distância positiva de offset.")
            sign=-1.0 if self.distance<0 else 1.0
            self._commit(viewport,*self._candidate(distance=sign*float(value)),"Offset da laje aplicado.");return True
        except SlabError as exc:self.controller.message(str(exc),error=True);return False

    def value_label(self):
        if self.anchor is None or self.normal is None:return None
        p=self.anchor+self.normal*self.distance
        return (f"{self.distance:+.4f} m".replace(".",","),p)

    def rubber_band_lines(self):
        if self.original is None:return []
        try:return _preview_lines(*offset_boundary(self.original,self.specs,self.distance))
        except SlabError:return []