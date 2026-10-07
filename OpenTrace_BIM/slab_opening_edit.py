# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive editing of embedded slab openings.

Openings intentionally reuse the same logical edge model as the slab's outer
reference polygon: straight/circular edges, vertex merge, chamfer, fillet and
offset.  Only the host slab owns geometry; these tools update the hosted
opening record and let :class:`EditSlab` regenerate the solid.
"""
from __future__ import annotations

import copy
import math
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import AxisMagnet, Tool

from .commands import root_edit_allowed
from .slab_commands import EditSlab
from .slab_edit import _distance_xy, _preview_lines, _project_to_segment
from .slab_model import (
    ARC_EPS, MIN_DIM, SlabError, edge_length, edge_outward_normal, edge_point,
    line_edge, normalize_edge_specs, offset_boundary, sample_boundary,
    slab_openings_world, solve_corner_fillet, split_arc_edge, trim_edge_spec,
    validate_edge_geometry, validate_polygon,
)


def _opening_data(slab, opening_index):
    ops = slab_openings_world(slab, reference=True)
    oi = int(opening_index)
    if oi < 0 or oi >= len(ops):
        raise SlabError("A abertura não está mais disponível.")
    item = copy.deepcopy(ops[oi])
    pts = [QVector3D(*raw) for raw in item.get("polygon", [])]
    specs = normalize_edge_specs(item.get("edges"), len(pts))
    if len(pts) < 3:
        raise SlabError("A abertura precisa manter pelo menos três vértices.")
    return ops, oi, item, pts, specs


def _store_opening(ops, oi, item, pts, specs):
    item = copy.deepcopy(item)
    item["polygon"] = [[p.x(), p.y(), p.z()] for p in pts]
    item["edges"] = [dict(s) for s in normalize_edge_specs(specs, len(pts))]
    ops = copy.deepcopy(ops)
    ops[oi] = item
    return ops


class _OpeningEditBase(AxisMagnet, Tool):
    wireframe_color = (0.88, 0.30, 0.22, 1.0)
    architecture_angle_snap = True

    def __init__(self, controller):
        self.controller = controller
        self.slab = None
        self.opening_index = None
        self.index = None
        self.anchor = None
        self.hover = None

    def arm(self, slab, token, anchor):
        if not isinstance(token, (tuple, list)) or len(token) != 2:
            raise SlabError("Selecione novamente uma aresta ou vértice da abertura.")
        self.slab = slab
        self.opening_index, self.index = int(token[0]), int(token[1])
        self.anchor = QVector3D(anchor)
        self.hover = QVector3D(anchor)
        self.start_point = QVector3D(anchor)

    def reset(self):
        self.slab = None; self.opening_index = None; self.index = None
        self.anchor = None; self.hover = None; self.start_point=None

    def drag_plane(self, viewport):
        z = self.anchor.z() if self.anchor is not None else 0.0
        return QVector3D(0, 0, z), QVector3D(0, 0, 1)

    def point(self, ctx):
        z = self.anchor.z() if self.anchor is not None else ctx.world.z()
        snap = getattr(ctx, "snap", None)
        if snap is not None and getattr(snap, "point", None) is not None:
            q = snap.point
            return QVector3D(q.x(), q.y(), z)
        return QVector3D(ctx.world.x(), ctx.world.y(), z)

    def on_activate(self, viewport): viewport.update()
    def on_deactivate(self, viewport): self.reset(); viewport.update()
    def on_cancel(self, viewport): self.reset(); QTimer.singleShot(0, self.controller.return_to_select)

    def _data(self):
        if self.slab is None or self.opening_index is None:
            raise SlabError("Selecione novamente a abertura.")
        return _opening_data(self.slab, self.opening_index)

    def _commit(self, viewport, pts, specs, message):
        validate_polygon(pts); validate_edge_geometry(pts, specs)
        ops, oi, item, _old, _old_specs = self._data()
        new_ops = _store_opening(ops, oi, item, pts, specs)
        viewport.history.execute(EditSlab(viewport.scene, self.slab, openings=new_ops))
        if viewport.history.last_error:
            raise SlabError(viewport.history.last_error)
        viewport.notify_scene_changed(); self.controller.message(message)
        self.reset(); QTimer.singleShot(0, self.controller.return_to_select)


class InsertOpeningVertexTool(_OpeningEditBase):
    name = "Inserir vértice na abertura"
    description = "Inserir um vértice numa aresta reta ou curva da abertura."

    def on_hover(self, ctx): self.hover = self.point(ctx); ctx.viewport.update()
    def on_click(self, ctx):
        try:
            root_edit_allowed(ctx.viewport.scene)
            _ops, _oi, _item, pts, specs = self._data()
            i = self.index % len(pts); j = (i + 1) % len(pts)
            if specs[i].get("type") == "arc":
                q, s1, s2, _t = split_arc_edge(pts[i], pts[j], specs[i].get("sagitta", 0.0), self.point(ctx))
                if (q-pts[i]).length() < MIN_DIM or (q-pts[j]).length() < MIN_DIM:
                    raise SlabError("Insira o vértice afastado das extremidades da abertura.")
                new = list(pts); new.insert(i+1, q)
                new_specs = list(specs); new_specs[i:i+1] = [s1, s2]
            else:
                q, t = _project_to_segment(self.point(ctx), pts[i], pts[j])
                if t <= .01 or t >= .99 or (q-pts[i]).length() < MIN_DIM or (q-pts[j]).length() < MIN_DIM:
                    raise SlabError("Insira o vértice afastado das extremidades da abertura.")
                new = list(pts); new.insert(i+1, q)
                new_specs = list(specs); new_specs[i:i+1] = [line_edge(), line_edge()]
            self._commit(ctx.viewport, new, new_specs, "Vértice inserido na abertura.")
        except SlabError as exc: self.controller.message(str(exc), error=True)
        ctx.viewport.update()


class StretchOpeningEdgeTool(_OpeningEditBase):
    name = "Estender aresta da abertura"
    description = "Extrudar uma aresta da abertura perpendicularmente."
    def __init__(self, controller): super().__init__(controller); self.original=None; self.specs=None; self.normal=None
    def arm(self, slab, token, anchor):
        super().arm(slab, token, anchor)
        _o,_oi,_it,pts,specs=self._data(); self.original=pts;self.specs=specs
        i=self.index%len(pts);j=(i+1)%len(pts);d=pts[j]-pts[i];d.setZ(0);L=math.hypot(d.x(),d.y())
        if L<MIN_DIM: raise SlabError("A aresta da abertura é curta demais.")
        self.normal=QVector3D(-d.y()/L,d.x()/L,0)
    def reset(self): super().reset();self.original=None;self.specs=None;self.normal=None
    def _candidate(self,p):
        if self.original is None:return None
        delta=QVector3D.dotProduct(p-self.anchor,self.normal);pts=[QVector3D(v) for v in self.original];specs=[dict(s) for s in self.specs]
        n=len(pts);i=self.index%n;j=(i+1)%n;a=QVector3D(pts[i]);b=QVector3D(pts[j]);a2=a+self.normal*delta;b2=b+self.normal*delta;old=dict(specs[i])
        tail=[QVector3D(pts[(i+k)%n]) for k in range(2,n)];new_pts=[a,a2,b2,b]+tail
        tail_specs=[dict(specs[(i+k)%n]) for k in range(1,n)];new_specs=[line_edge(),old,line_edge()]+tail_specs
        return new_pts,normalize_edge_specs(new_specs,len(new_pts))
    def on_hover(self,ctx):self.hover=self.point(ctx);ctx.viewport.update()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,*self._candidate(self.point(ctx)),"Aresta da abertura estendida.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def rubber_band_lines(self):
        if self.hover is None:return []
        c=self._candidate(self.hover);return [] if c is None else _preview_lines(*c)


class MoveOpeningVertexTool(_OpeningEditBase):
    name="Mover vértice da abertura";description="Mover ou fundir um vértice da abertura no plano horizontal.";MERGE_TOL=1e-4
    def __init__(self,controller):super().__init__(controller);self.original=None;self.specs=None;self._merge=False;self.move_reference=None
    def arm(self,slab,token,anchor):super().arm(slab,token,anchor);_o,_oi,_it,self.original,self.specs=self._data();self._merge=False;self.move_reference=None;self.start_point=None;self.hover=None
    def reset(self):super().reset();self.original=None;self.specs=None;self._merge=False;self.move_reference=None
    def _merge_candidate(self,j):
        n=len(self.original);i=self.index%n;j%=n
        if j not in ((i-1)%n,(i+1)%n):raise SlabError("Só é possível unir vértices vizinhos da abertura.")
        prev_i=(i-1)%n;next_i=(i+1)%n;keep=[k for k in range(n) if k!=i];pts=[QVector3D(self.original[k]) for k in keep];specs=[]
        for pos,aidx in enumerate(keep):
            bidx=keep[(pos+1)%len(keep)]
            spec_idx=(prev_i if j==next_i else i) if aidx==prev_i and bidx==next_i else aidx
            specs.append(dict(self.specs[spec_idx]))
        self._merge=True;return pts,normalize_edge_specs(specs,len(pts))
    def _candidate(self,p):
        n=len(self.original);i=self.index%n;current=QVector3D(self.original[i])
        q=QVector3D(p.x(),p.y(),self.original[0].z());self._merge=False
        nearest=None
        for j,v in enumerate(self.original):
            if j==i:continue
            d=_distance_xy(q,v)
            if d<=self.MERGE_TOL and (nearest is None or d<nearest[0]):nearest=(d,j)
        if nearest is not None:return self._merge_candidate(nearest[1])
        pts=[QVector3D(v) for v in self.original];pts[i]=q;return pts,[dict(s) for s in self.specs]
    def on_hover(self,ctx):
        self.hover=self.point(ctx);self.start_point=QVector3D(self.original[self.index%len(self.original)]) if self.original else None;ctx.viewport.update()
    def on_click(self,ctx):
        try:
            p=self.point(ctx)
            self._commit(ctx.viewport,*self._candidate(p),"Vértices da abertura unidos." if self._merge else "Vértice da abertura movido.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def rubber_band_lines(self):
        if self.hover is None:return []
        try:return _preview_lines(*self._candidate(self.hover))
        except SlabError:return []


class CurveOpeningEdgeTool(_OpeningEditBase):
    name="Curvar aresta da abertura";description="Curvar uma aresta da abertura mantendo os extremos."
    def __init__(self,controller):super().__init__(controller);self.original=None;self.specs=None;self.mid=None;self.normal=None
    def arm(self,slab,token,anchor):
        super().arm(slab,token,anchor);_o,_oi,_it,self.original,self.specs=self._data();i=self.index%len(self.original);a=self.original[i];b=self.original[(i+1)%len(self.original)];d=b-a;d.setZ(0);L=math.hypot(d.x(),d.y())
        if L<MIN_DIM:raise SlabError("A aresta da abertura é curta demais para ser curvada.")
        self.mid=(a+b)*.5;self.normal=QVector3D(-d.y()/L,d.x()/L,0)
    def reset(self):super().reset();self.original=None;self.specs=None;self.mid=None;self.normal=None
    def _candidate(self,p):
        h=QVector3D.dotProduct(p-self.mid,self.normal);specs=[dict(s) for s in self.specs];specs[self.index%len(specs)]=line_edge() if abs(h)<ARC_EPS else {"type":"arc","sagitta":float(h)}
        return [QVector3D(v) for v in self.original],specs
    def on_hover(self,ctx):self.hover=self.point(ctx);ctx.viewport.update()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,*self._candidate(self.point(ctx)),"Curvatura da abertura atualizada.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def rubber_band_lines(self):return [] if self.hover is None else _preview_lines(*self._candidate(self.hover))


class _OpeningCornerBase(_OpeningEditBase):
    def __init__(self,controller):super().__init__(controller);self.original=None;self.specs=None;self.prev=self.vertex=self.next=None;self.prev_len=self.next_len=self.max_t=None
    def arm(self,slab,token,anchor):
        super().arm(slab,token,anchor);_o,_oi,_it,self.original,self.specs=self._data();n=len(self.original);i=self.index%n;pi=(i-1)%n
        self.prev=QVector3D(self.original[pi]);self.vertex=QVector3D(self.original[i]);self.next=QVector3D(self.original[(i+1)%n]);self.prev_len=edge_length(self.prev,self.vertex,self.specs[pi]);self.next_len=edge_length(self.vertex,self.next,self.specs[i])
        if self.prev_len<2*MIN_DIM or self.next_len<2*MIN_DIM:raise SlabError("As arestas ao redor deste vértice são curtas demais.")
        self.max_t=max(MIN_DIM,min(self.prev_len,self.next_len)-MIN_DIM)
    def reset(self):super().reset();self.original=None;self.specs=None;self.prev=self.vertex=self.next=None;self.prev_len=self.next_len=self.max_t=None
    def _size(self,p):return max(MIN_DIM,min(self.max_t,_distance_xy(p,self.vertex)))
    def _trim(self,t):
        tp=max(0,min(1,1-t/self.prev_len));tn=max(0,min(1,t/self.next_len));n=len(self.original);i=self.index%n;pi=(i-1)%n
        return edge_point(self.prev,self.vertex,self.specs[pi],tp),edge_point(self.vertex,self.next,self.specs[i],tn),tp,tn
    def _build(self,p1,p2,tp,tn,bridge):
        n=len(self.original);i=self.index%n;pi=(i-1)%n;prev_spec=trim_edge_spec(self.prev,self.vertex,self.specs[pi],0,tp);next_spec=trim_edge_spec(self.vertex,self.next,self.specs[i],tn,1)
        segs=[(QVector3D(p1),QVector3D(p2),dict(bridge)),(QVector3D(p2),QVector3D(self.next),dict(next_spec))];k=(i+1)%n
        while k!=pi:
            segs.append((QVector3D(self.original[k]),QVector3D(self.original[(k+1)%n]),dict(self.specs[k])));k=(k+1)%n
        segs.append((QVector3D(self.prev),QVector3D(p1),dict(prev_spec)))
        return [a for a,_b,_s in segs],normalize_edge_specs([s for _a,_b,s in segs],len(segs))


class ChamferOpeningVertexTool(_OpeningCornerBase):
    name="Chanfrar vértice da abertura";description="Criar um chanfro no contorno da abertura."
    def _candidate(self,p):p1,p2,tp,tn=self._trim(self._size(p));return self._build(p1,p2,tp,tn,line_edge())
    def on_hover(self,ctx):self.hover=self.point(ctx);ctx.viewport.update()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,*self._candidate(self.point(ctx)),"Chanfro criado na abertura.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def rubber_band_lines(self):return [] if self.hover is None else _preview_lines(*self._candidate(self.hover))


class FilletOpeningVertexTool(_OpeningCornerBase):
    name="Arredondar vértice da abertura";description="Criar um fillet tangente no contorno da abertura."
    def _candidate(self,p):
        req=max(MIN_DIM,_distance_xy(p,self.vertex));sol=solve_corner_fillet(self.original,self.specs,self.index,req)
        return self._build(sol["p1"],sol["p2"],sol["prev_fraction"],sol["next_fraction"],sol["spec"])
    def on_hover(self,ctx):self.hover=self.point(ctx);ctx.viewport.update()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,*self._candidate(self.point(ctx)),"Fillet criado na abertura.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def rubber_band_lines(self):
        if self.hover is None:return []
        try:return _preview_lines(*self._candidate(self.hover))
        except SlabError:return []


class OffsetOpeningTool(_OpeningEditBase):
    name="Offset da abertura";description="Offset de todo o contorno da abertura.";uses_snap=False;vcb_label="Offset"
    def __init__(self,controller):super().__init__(controller);self.original=None;self.specs=None;self.normal=None;self.distance=0.0
    def arm(self,slab,token,anchor):
        super().arm(slab,token,anchor);_o,_oi,_it,self.original,self.specs=self._data();self.normal=edge_outward_normal(self.original,self.specs,self.index,self.anchor);self.distance=0.0
    def reset(self):super().reset();self.original=None;self.specs=None;self.normal=None;self.distance=0.0
    def _candidate(self,p=None,distance=None):
        d=float(distance if distance is not None else QVector3D.dotProduct(p-self.anchor,self.normal));self.distance=d;return offset_boundary(self.original,self.specs,d)
    def on_hover(self,ctx):
        try:self.hover=self.point(ctx);self._candidate(self.hover);ctx.viewport.update()
        except SlabError:self.hover=self.point(ctx);ctx.viewport.update()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,*self._candidate(self.point(ctx)),"Offset da abertura aplicado.")
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_value(self,viewport,value):
        try:
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise SlabError("Digite uma distância positiva de offset.")
            sign=-1 if self.distance<0 else 1;self._commit(viewport,*self._candidate(distance=sign*float(value)),"Offset da abertura aplicado.");return True
        except SlabError as exc:self.controller.message(str(exc),error=True);return False
    def value_label(self):
        if self.anchor is None or self.normal is None:return None
        return (f"{self.distance:+.4f} m".replace(".",","),self.anchor+self.normal*self.distance)
    def rubber_band_lines(self):
        if self.original is None:return []
        try:return _preview_lines(*offset_boundary(self.original,self.specs,self.distance))
        except SlabError:return []


class MoveOpeningTool(AxisMagnet, Tool):
    name="Mover abertura";description="Mover a abertura inteira no plano horizontal.";uses_snap=True;wireframe_color=(0.88,0.30,0.22,1.0);architecture_angle_snap=True
    def __init__(self,controller):self.controller=controller;self.reset()
    def arm(self,slab,token,anchor):
        if not isinstance(token,(tuple,list)) or len(token)!=2:raise SlabError("Selecione novamente a abertura.")
        self.slab=slab;self.opening_index=int(token[0]);self.anchor=QVector3D(anchor);self.origin=None;self.start_point=None;self.hover=None
        _o,_oi,_it,self.points,self.specs=_opening_data(slab,self.opening_index)
    def reset(self):self.slab=None;self.opening_index=None;self.anchor=None;self.origin=None;self.start_point=None;self.hover=None;self.points=None;self.specs=None
    def drag_plane(self,viewport):return (QVector3D(0,0,self.anchor.z()),QVector3D(0,0,1)) if self.anchor is not None else None
    def on_activate(self,viewport):
        if self.slab is None:QTimer.singleShot(0,self.controller.return_to_select)
        else:self.controller.message("Clique no ponto de referência para mover a abertura.")
    def on_deactivate(self,viewport):self.reset();viewport.update()
    def _delta(self,p):
        if self.origin is None:return QVector3D(0,0,0)
        return QVector3D(p.x()-self.origin.x(),p.y()-self.origin.y(),0)
    def _candidate(self,p):
        d=self._delta(p);return [QVector3D(v)+d for v in self.points],[dict(s) for s in self.specs]
    def on_hover(self,ctx):
        if self.origin is None:return
        self.hover=QVector3D(ctx.world);ctx.viewport.update()
    def on_click(self,ctx):
        try:
            if self.origin is None:
                self.origin=QVector3D(ctx.world);self.start_point=QVector3D(ctx.world);self.hover=None;self.controller.message("Agora clique no ponto de destino da abertura.");ctx.viewport.update();return
            pts,specs=self._candidate(ctx.world);ops,oi,item,_p,_s=_opening_data(self.slab,self.opening_index);new_ops=_store_opening(ops,oi,item,pts,specs)
            ctx.viewport.history.execute(EditSlab(ctx.viewport.scene,self.slab,openings=new_ops))
            if ctx.viewport.history.last_error:raise SlabError(ctx.viewport.history.last_error)
            ctx.viewport.notify_scene_changed();self.controller.message("Abertura movida.");self.reset();self.controller.return_to_select()
        except SlabError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_cancel(self,viewport):self.reset();self.controller.return_to_select();viewport.update()
    def rubber_band_lines(self):
        if self.hover is None or self.points is None or self.origin is None:return []
        return _preview_lines(*self._candidate(self.hover))
