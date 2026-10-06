# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
import copy
from PySide6.QtGui import QMatrix4x4, QVector3D
from core.history import Command
from .commands import root_edit_allowed
from .materials import stamp_named_material
from .beam_model import BeamError,make_beam,read_beam,endpoints_world,beam_record

class CreateBeam(Command):
    def __init__(self,group):self.group=group;self.index=None
    def do(self,scene):
        if self.group in scene.groups:raise BeamError("A viga já está no documento.")
        rec=beam_record(self.group) or {};name=rec.get("material_name")
        if name:stamp_named_material(self.group,scene,name)
        if self.index is None:self.index=len(scene.groups)
        scene.groups.insert(min(self.index,len(scene.groups)),self.group);scene.version+=1
    def undo(self,scene):
        if self.group in scene.groups:scene.groups.remove(self.group)
        scene.selection.discard(self.group);scene.version+=1

class EditBeam(Command):
    def __init__(self,scene,group,values):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group):raise BeamError("A viga está indisponível ou bloqueada.")
        old=read_beam(group);merged=dict(old);merged.update(values or {});a,b=endpoints_world(group)
        # Numeric length editing keeps the start fixed for straight beams. Curved
        # beams derive their length from chord + sagitta, like curved walls.
        requested=float(merged.get("length",old["length"]))
        if abs(requested-float(old["length"]))>1e-8:
            if (abs(float(old.get("curvature",0.0)))>1e-8 or abs(float(merged.get("curvature",0.0)))>1e-8 or abs(float(old.get("vertical_curvature",0.0)))>1e-8 or abs(float(merged.get("vertical_curvature",0.0)))>1e-8):
                raise BeamError("Em vigas curvas, altere os extremos ou as flechas; o comprimento do eixo é derivado.")
            import math
            dx,dy=b.x()-a.x(),b.y()-a.y();plan=math.hypot(dx,dy)
            if plan<0.001:raise BeamError("A direção da viga está indefinida.")
            target_plan=requested*abs(math.cos(math.radians(float(merged.get("inclination",0.0)))))
            u=QVector3D(dx/plan,dy/plan,0);b=QVector3D(a.x()+u.x()*target_plan,a.y()+u.y()*target_plan,b.z())
        fresh=make_beam(a,b,merged,template=group)
        if merged.get("material_name")!=old.get("material_name"):stamp_named_material(fresh,scene,merged.get("material_name"),clear=True)
        self.group=group;self.before=(list(group.children),copy.deepcopy(group.ext),QMatrix4x4(group.xform));self.after=(list(fresh.children),copy.deepcopy(fresh.ext),QMatrix4x4(fresh.xform))
    def _apply(self,scene,state):
        children,ext,xform=state;self.group.children=list(children);self.group.ext=copy.deepcopy(ext);self.group.xform=QMatrix4x4(xform);scene.version+=1
    def do(self,scene):self._apply(scene,self.after)
    def undo(self,scene):self._apply(scene,self.before)


class ReshapeBeam(Command):
    """Move one or both beam endpoints while preserving section parameters."""
    def __init__(self,scene,group,start,end):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group):raise BeamError("A viga está indisponível ou bloqueada.")
        old=read_beam(group);a=QVector3D(start);b=QVector3D(end)
        dx,dy=b.x()-a.x(),b.y()-a.y();chord=(dx*dx+dy*dy)**0.5
        if chord<0.001:raise BeamError("A viga precisa ter comprimento maior que 0,001 m.")
        import math
        # Endpoint Z is semantic.  Recompute the end-to-end inclination instead
        # of preserving the old angle; this lets either endpoint act as a true
        # vertical inclination handle.  Horizontal curvature uses its plan
        # arclength, matching beam_model._centerline_local.
        try:
            from .beam_model import _plan_arc_points
            plan_pts=_plan_arc_points(chord,float(old.get("curvature",0.0)))
            plan_len=sum(math.hypot(q1.x()-q0.x(),q1.y()-q0.y()) for q0,q1 in zip(plan_pts,plan_pts[1:]))
        except Exception:
            plan_len=chord
        if plan_len<0.001:raise BeamError("A projeção da viga é pequena demais.")
        angle=math.degrees(math.atan2(b.z()-a.z(),plan_len))
        if not -85.0<=angle<=85.0:raise BeamError("A inclinação resultante deve ficar entre -85° e 85°.")
        # The beam floor/base elevation is always the lower endpoint. If the
        # semantic direction must reverse, negate the plan sagitta so the
        # horizontal arc remains on the same world side.
        if a.z() <= b.z():
            low,high=QVector3D(a),QVector3D(b);vals=dict(old,base_z=a.z(),inclination=abs(angle))
        else:
            low,high=QVector3D(b),QVector3D(a);vals=dict(old,base_z=b.z(),inclination=abs(angle),curvature=-float(old.get("curvature",0.0)))
        # make_beam derives the actual spatial length from the rebuilt path.
        fresh=make_beam(low,high,vals,template=group)
        self.group=group;self.before=(list(group.children),copy.deepcopy(group.ext),QMatrix4x4(group.xform));self.after=(list(fresh.children),copy.deepcopy(fresh.ext),QMatrix4x4(fresh.xform))
    def _apply(self,scene,state):
        children,ext,xform=state;self.group.children=list(children);self.group.ext=copy.deepcopy(ext);self.group.xform=QMatrix4x4(xform);scene.version+=1
    def do(self,scene):self._apply(scene,self.after)
    def undo(self,scene):self._apply(scene,self.before)
