# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared graphical editing tools for beams and columns."""
from __future__ import annotations

import math
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import AxisMagnet, Tool
from core.history import MoveGroupCommand


class MoveWholeStructureTool(AxisMagnet, Tool):
    """Move one parametric structural element as a whole in XY."""
    uses_snap = True
    architecture_angle_snap = True
    wireframe_color = (0.78, 0.43, 0.16, 1.0)

    def __init__(self, controller, label):
        self.controller = controller
        self.label = label
        self.name = f"Mover {label}"
        self.description = self.name
        self.reset()

    def reset(self):
        self.group = None
        self.anchor = None
        self.cursor_origin = None
        self.start_point = None
        self.delta = QVector3D(0, 0, 0)
        self.preview = False

    def prepare(self, group, anchor):
        self.group = group
        self.anchor = QVector3D(anchor)
        self.start_point = QVector3D(anchor)

    def on_activate(self, viewport):
        if self.group is None or self.group not in viewport.scene.groups:
            QTimer.singleShot(0, self.controller.return_to_select)
            return
        viewport.begin_groups_preview([self.group])
        self.preview = True
        self.controller.message(f"Mova {self.label} inteira no plano horizontal e clique.")
        viewport.update()

    def on_deactivate(self, viewport):
        if self.preview:
            viewport.end_groups_preview()
        self.reset()
        viewport.update()

    def drag_plane(self, viewport):
        if self.anchor is None:
            return None
        return QVector3D(0, 0, self.anchor.z()), QVector3D(0, 0, 1)

    def _delta(self, p):
        origin = self.cursor_origin if self.cursor_origin is not None else p
        return QVector3D(p.x() - origin.x(), p.y() - origin.y(), 0.0)

    def on_hover(self, ctx):
        if self.group is None:
            return
        if self.cursor_origin is None:
            self.cursor_origin = QVector3D(ctx.world)
            self.start_point = QVector3D(ctx.world)
        self.delta = self._delta(ctx.world)
        if self.preview:
            ctx.viewport.set_groups_preview_offset(self.delta)
        ctx.viewport.update()

    def on_click(self, ctx):
        try:
            if self.cursor_origin is None:
                self.cursor_origin = QVector3D(ctx.world)
            self.delta = self._delta(ctx.world)
            if self.preview:
                ctx.viewport.end_groups_preview()
                self.preview = False
            if self.delta.length() > 1.0e-9:
                ctx.viewport.history.execute(MoveGroupCommand(self.group, self.delta))
                if ctx.viewport.history.last_error:
                    raise ValueError(ctx.viewport.history.last_error)
                ctx.viewport.notify_scene_changed()
            self.controller.message(f"{self.label.capitalize()} inteira movida.")
            self.reset()
            self.controller.return_to_select()
        except Exception as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_cancel(self, viewport):
        if self.preview:
            viewport.end_groups_preview()
            self.preview = False
        self.reset()
        self.controller.return_to_select()
        self.controller.message("Movimento cancelado.")
        viewport.update()


class BeamCurveTool(Tool):
    """Edit a beam's signed plan sagitta, keeping both endpoints fixed."""
    name = "Curvar viga"
    description = "Curvar a linha de referência da viga em arco."
    uses_snap = False
    wireframe_color = (0.78, 0.43, 0.16, 1.0)
    vcb_label = "Flecha"

    def __init__(self, controller):
        self.controller = controller
        self.reset()

    def reset(self):
        self.group = None
        self.values = None
        self.start = None
        self.end = None
        self.sagitta = 0.0

    def prepare(self, group):
        self.group = group

    def on_activate(self, viewport):
        from .beam_model import BeamError, endpoints_world, read_beam
        if self.group is None or self.group not in viewport.scene.groups:
            QTimer.singleShot(0, self.controller.return_to_select)
            return
        try:
            self.values = read_beam(self.group)
            self.start, self.end = (QVector3D(p) for p in endpoints_world(self.group))
            self.sagitta = float(self.values.get("curvature", 0.0))
            self.controller.message("Mova para um lado do eixo e clique para definir a flecha. Digite 0 para endireitar.")
        except BeamError as exc:
            self.controller.message(str(exc), error=True)
            QTimer.singleShot(0, self.controller.return_to_select)
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset()
        viewport.update()

    def drag_plane(self, viewport):
        if self.start is None:
            return None
        return QVector3D(0, 0, self.start.z()), QVector3D(0, 0, 1)

    def _sagitta_from_world(self, world):
        d = self.end - self.start
        L = math.hypot(d.x(), d.y())
        if L < 1.0e-9:
            return 0.0
        nx, ny = -d.y() / L, d.x() / L
        mid = (self.start + self.end) * 0.5
        return (world.x() - mid.x()) * nx + (world.y() - mid.y()) * ny

    def on_hover(self, ctx):
        if self.values is None:
            return
        self.sagitta = self._sagitta_from_world(ctx.world)
        ctx.viewport.update()

    def _commit(self, viewport, sagitta):
        from .beam_commands import EditBeam
        from .beam_model import BeamError
        vals = dict(self.values)
        vals["curvature"] = float(sagitta)
        viewport.history.execute(EditBeam(viewport.scene, self.group, vals))
        if viewport.history.last_error:
            raise BeamError(viewport.history.last_error)
        viewport.notify_scene_changed()
        self.controller.message("Viga endireitada." if abs(float(sagitta)) < 1.0e-7 else "Viga curvada em arco.")
        self.reset()
        self.controller.return_to_select()

    def on_click(self, ctx):
        from .beam_model import BeamError
        try:
            self.sagitta = self._sagitta_from_world(ctx.world)
            self._commit(ctx.viewport, self.sagitta)
        except BeamError as exc:
            self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_value(self, viewport, value):
        from .beam_model import BeamError
        try:
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise BeamError("Digite uma flecha válida.")
            h = float(value)
            if h >= 0.0 and self.sagitta < 0.0:
                h = -h
            self._commit(viewport, h)
            return True
        except BeamError as exc:
            self.controller.message(str(exc), error=True)
            return False

    def on_cancel(self, viewport):
        self.reset()
        self.controller.return_to_select()
        self.controller.message("Curvatura cancelada.")
        viewport.update()

    def rubber_band_lines(self):
        if self.group is None or self.values is None:
            return []
        from .beam_model import reference_path_world_for
        try:
            pts = reference_path_world_for(self.group, dict(self.values, curvature=self.sagitta))
        except Exception:
            return []
        return list(zip(pts, pts[1:]))

    def value_label(self):
        return (f"{self.sagitta:.4f} m".replace(".", ","),)


class ColumnCurveTool(Tool):
    """Edit only the selected column segment curvature."""
    name = "Curvar segmento do pilar"
    description = "Curvar somente o segmento selecionado do eixo do pilar."
    uses_snap = False
    wireframe_color = (0.78, 0.43, 0.16, 1.0)
    vcb_label = "Flecha"

    def __init__(self, controller):
        self.controller = controller
        self.reset()

    def reset(self):
        self.group=None; self.values=None; self.base=None; self.top=None; self.direction=None; self.sagitta=0.0; self.segment_index=0

    def prepare(self, group, segment_index=None):
        self.group=group
        self.segment_index=0 if segment_index is None else max(0,int(segment_index))

    def _preview_values(self, sagitta):
        vals=dict(self.values); stations=[dict(x) for x in vals.get("stations",())]
        i=max(0,min(self.segment_index,len(stations)-2))
        stations[i]["curvature"]=float(sagitta); vals["stations"]=stations
        vals["curvature"]=float(stations[0].get("curvature",0.0))
        return vals

    def on_activate(self, viewport):
        from .column_model import ColumnError, read_column, station_points_world
        if self.group is None or self.group not in viewport.scene.groups:
            QTimer.singleShot(0, self.controller.return_to_select); return
        try:
            self.values=read_column(self.group); stations=self.values.get("stations",[])
            self.segment_index=max(0,min(self.segment_index,len(stations)-2))
            pts=station_points_world(self.group); self.base=QVector3D(pts[self.segment_index]); self.top=QVector3D(pts[self.segment_index+1])
            a=stations[self.segment_index]
            az=math.radians(float(a.get("inclination_azimuth",self.values.get("inclination_azimuth",0.0))))
            self.direction=QVector3D(math.cos(az),math.sin(az),0.0)
            self.sagitta=float(a.get("curvature",0.0))
            self.controller.message(f"Curve somente o segmento {self.segment_index+1}. Mova no plano do segmento e clique; digite 0 para endireitar.")
        except ColumnError as exc:
            self.controller.message(str(exc),error=True); QTimer.singleShot(0,self.controller.return_to_select)
        viewport.update()

    def on_deactivate(self, viewport): self.reset(); viewport.update()
    def drag_plane(self, viewport):
        if self.base is None or self.direction is None:return None
        normal=QVector3D(-self.direction.y(),self.direction.x(),0.0)
        return (self.base+self.top)*0.5, normal
    def _coords(self, world):
        v=QVector3D(world)-self.base
        return QVector3D.dotProduct(v,self.direction),v.z()
    def _sagitta_from_world(self, world):
        s1,z1=self._coords(self.top);L=math.hypot(s1,z1)
        if L<1e-9:return 0.0
        ns,nz=z1/L,-s1/L;s,z=self._coords(world)
        return (s-s1*0.5)*ns+(z-z1*0.5)*nz
    def on_hover(self,ctx):
        if self.values is None:return
        self.sagitta=self._sagitta_from_world(ctx.world);ctx.viewport.update()
    def _commit(self,viewport,sagitta):
        from .column_commands import EditColumn
        from .column_model import ColumnError
        vals=self._preview_values(sagitta)
        viewport.history.execute(EditColumn(viewport.scene,self.group,vals))
        if viewport.history.last_error:raise ColumnError(viewport.history.last_error)
        viewport.notify_scene_changed();msg=(f"Segmento {self.segment_index+1} endireitado." if abs(float(sagitta))<1e-7 else f"Segmento {self.segment_index+1} curvado em arco.")
        self.controller.message(msg);self.reset();self.controller.return_to_select()
    def on_click(self,ctx):
        from .column_model import ColumnError
        try:self.sagitta=self._sagitta_from_world(ctx.world);self._commit(ctx.viewport,self.sagitta)
        except ColumnError as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_value(self,viewport,value):
        from .column_model import ColumnError
        try:
            if not isinstance(value,(int,float)) or not math.isfinite(value):raise ColumnError("Digite uma flecha válida.")
            h=float(value)
            if h>=0.0 and self.sagitta<0.0:h=-h
            self._commit(viewport,h);return True
        except ColumnError as exc:self.controller.message(str(exc),error=True);return False
    def on_cancel(self,viewport):self.reset();self.controller.return_to_select();self.controller.message("Curvatura cancelada.");viewport.update()
    def rubber_band_lines(self):
        if self.group is None or self.values is None:return []
        from .column_model import reference_path_world_for
        try:pts=reference_path_world_for(self.group,self._preview_values(self.sagitta))
        except Exception:return []
        return list(zip(pts,pts[1:]))
    def value_label(self):return (f"{self.sagitta:.4f} m".replace(".",","),)


class BeamVerticalCurveTool(Tool):
    """Edit vertical beam sagitta while keeping plan projection and ends fixed."""
    name = "Curvar viga verticalmente"
    description = "Curvar o eixo da viga no plano vertical."
    uses_snap = False
    wireframe_color = (0.20, 0.48, 0.84, 1.0)
    vcb_label = "Flecha vertical"

    def __init__(self, controller):
        self.controller = controller
        self.reset()

    def reset(self):
        self.group = None
        self.values = None
        self.start = None
        self.end = None
        self.sagitta = 0.0

    def prepare(self, group):
        self.group = group

    def on_activate(self, viewport):
        from .beam_model import BeamError, endpoints_world, read_beam
        if self.group is None or self.group not in viewport.scene.groups:
            QTimer.singleShot(0, self.controller.return_to_select)
            return
        try:
            self.values = read_beam(self.group)
            self.start, self.end = (QVector3D(p) for p in endpoints_world(self.group))
            self.sagitta = float(self.values.get("vertical_curvature", 0.0))
            self.controller.message("Mova para cima/baixo e clique para definir a curvatura vertical. Digite 0 para endireitar.")
        except BeamError as exc:
            self.controller.message(str(exc), error=True)
            QTimer.singleShot(0, self.controller.return_to_select)
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset(); viewport.update()

    def drag_plane(self, viewport):
        if self.start is None or self.end is None:
            return None
        d = self.end - self.start
        plan = QVector3D(d.x(), d.y(), 0.0)
        if plan.length() < 1.0e-9:
            return None
        plan.normalize()
        normal = QVector3D(-plan.y(), plan.x(), 0.0)
        return (self.start + self.end) * 0.5, normal

    def _sagitta_from_world(self, world):
        return float(world.z() - (self.start.z() + self.end.z()) * 0.5)

    def on_hover(self, ctx):
        if self.values is None: return
        self.sagitta = self._sagitta_from_world(ctx.world); ctx.viewport.update()

    def _commit(self, viewport, sagitta):
        from .beam_commands import EditBeam
        from .beam_model import BeamError
        vals = dict(self.values); vals["vertical_curvature"] = float(sagitta)
        viewport.history.execute(EditBeam(viewport.scene, self.group, vals))
        if viewport.history.last_error: raise BeamError(viewport.history.last_error)
        viewport.notify_scene_changed()
        self.controller.message("Curvatura vertical removida." if abs(float(sagitta)) < 1e-7 else "Curvatura vertical da viga atualizada.")
        self.reset(); self.controller.return_to_select()

    def on_click(self, ctx):
        from .beam_model import BeamError
        try:
            self.sagitta = self._sagitta_from_world(ctx.world); self._commit(ctx.viewport, self.sagitta)
        except BeamError as exc: self.controller.message(str(exc), error=True)
        ctx.viewport.update()

    def on_value(self, viewport, value):
        from .beam_model import BeamError
        try:
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise BeamError("Digite uma flecha vertical válida.")
            self._commit(viewport, float(value)); return True
        except BeamError as exc:
            self.controller.message(str(exc), error=True); return False

    def on_cancel(self, viewport):
        self.reset(); self.controller.return_to_select(); self.controller.message("Curvatura vertical cancelada."); viewport.update()

    def rubber_band_lines(self):
        if self.group is None or self.values is None: return []
        from .beam_model import reference_path_world_for
        try: pts = reference_path_world_for(self.group, dict(self.values, vertical_curvature=self.sagitta))
        except Exception: return []
        return list(zip(pts, pts[1:]))

    def value_label(self):
        return (f"{self.sagitta:.4f} m".replace(".", ","),)


class BeamInclineTool(Tool):
    """Incline a beam by moving whichever endpoint opened the palette."""
    name="Inclinar viga"
    description="Alterar a inclinação a partir do extremo selecionado."
    uses_snap=False
    wireframe_color=(0.20,0.48,0.84,1.0)
    vcb_label="Inclinação"
    def __init__(self,controller):self.controller=controller;self.reset()
    def reset(self):
        self.group=None;self.values=None;self.refs=None;self.endpoint=1;self.plan_len=0.0;self.angle=0.0;self.preview_z=None
    def prepare(self,group,anchor=None):self.group=group;self.anchor=QVector3D(anchor) if anchor is not None else None
    def on_activate(self,viewport):
        from .beam_model import endpoints_world,read_beam,reference_path_world
        if self.group is None or self.group not in viewport.scene.groups:QTimer.singleShot(0,self.controller.return_to_select);return
        try:
            self.values=read_beam(self.group);a,b=(QVector3D(p) for p in endpoints_world(self.group));self.refs=[a,b]
            if getattr(self,'anchor',None) is not None:self.endpoint=0 if (self.anchor-a).length()<=(self.anchor-b).length() else 1
            else:self.endpoint=1
            path=reference_path_world(self.group);self.plan_len=sum(math.hypot(q1.x()-q0.x(),q1.y()-q0.y()) for q0,q1 in zip(path,path[1:]))
            self.angle=float(self.values.get("inclination",0.0));self.preview_z=self.refs[self.endpoint].z()
            self.controller.message(f"Incline a viga pelo extremo {'inicial' if self.endpoint==0 else 'final'} selecionado; o outro permanece fixo.")
        except Exception as exc:self.controller.message(str(exc),error=True);QTimer.singleShot(0,self.controller.return_to_select)
        viewport.update()
    def on_deactivate(self,viewport):self.reset();viewport.update()
    def drag_plane(self,viewport):
        if not self.refs:return None
        moving=self.refs[self.endpoint];fixed=self.refs[1-self.endpoint];d=moving-fixed;plan=QVector3D(d.x(),d.y(),0)
        if plan.length()<1e-9:return None
        plan.normalize();return moving,QVector3D(-plan.y(),plan.x(),0)
    def _angle_for_z(self,z):
        if self.plan_len<1e-9:return 0.0
        a_z=self.refs[0].z();b_z=self.refs[1].z()
        if self.endpoint==0:a_z=float(z)
        else:b_z=float(z)
        return max(-85.0,min(85.0,math.degrees(math.atan2(b_z-a_z,self.plan_len))))
    def on_hover(self,ctx):self.preview_z=float(ctx.world.z());self.angle=self._angle_for_z(self.preview_z);ctx.viewport.update()
    def _ends_for_angle(self,angle):
        a,b=QVector3D(self.refs[0]),QVector3D(self.refs[1]);rise=self.plan_len*math.tan(math.radians(float(angle)))
        if self.endpoint==1:b.setZ(a.z()+rise)
        else:a.setZ(b.z()-rise)
        return a,b
    def _commit(self,viewport,angle):
        from .beam_commands import ReshapeBeam
        from .beam_model import BeamError
        a,b=self._ends_for_angle(angle);viewport.history.execute(ReshapeBeam(viewport.scene,self.group,a,b))
        if viewport.history.last_error:raise BeamError(viewport.history.last_error)
        viewport.notify_scene_changed();self.controller.message(f"Inclinação da viga: {float(angle):.2f}°");self.reset();self.controller.return_to_select()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,self._angle_for_z(ctx.world.z()))
        except Exception as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_value(self,viewport,value):
        try:
            a=float(value)
            if not math.isfinite(a) or not -85<=a<=85:raise ValueError("A inclinação deve ficar entre -85° e 85°.")
            self._commit(viewport,a);return True
        except Exception as exc:self.controller.message(str(exc),error=True);return False
    def on_cancel(self,viewport):self.reset();self.controller.return_to_select();self.controller.message("Inclinação cancelada.");viewport.update()
    def rubber_band_lines(self):
        if not self.refs:return []
        try:a,b=self._ends_for_angle(self.angle);return [(a,b)]
        except Exception:return []
    def value_label(self):return (f"{self.angle:.2f}°".replace(".",","),)


class ColumnInclineTool(Tool):
    """Graphically edit the inclination of one pillar segment."""
    name = "Inclinar segmento do pilar"
    description = "Alterar a inclinação do segmento selecionado na direção atual."
    uses_snap = False
    wireframe_color = (0.20, 0.48, 0.84, 1.0)
    vcb_label = "Inclinação"

    def __init__(self,controller):self.controller=controller;self.reset()
    def reset(self):self.group=None;self.values=None;self.base=None;self.direction=None;self.angle=0.0;self.segment_index=0;self.segment_height=0.0
    def prepare(self,group,segment_index=None):self.group=group;self.segment_index=0 if segment_index is None else max(0,int(segment_index))
    def on_activate(self,viewport):
        from .column_model import ColumnError,read_column,station_points_world
        if self.group is None or self.group not in viewport.scene.groups:
            QTimer.singleShot(0,self.controller.return_to_select);return
        try:
            self.values=read_column(self.group);stations=self.values.get("stations",[])
            self.segment_index=max(0,min(self.segment_index,len(stations)-2));a,b=stations[self.segment_index],stations[self.segment_index+1]
            pts=station_points_world(self.group);self.base=QVector3D(pts[self.segment_index])
            self.segment_height=max(1e-9,(float(b.get("t",1.0))-float(a.get("t",0.0)))*float(self.values.get("height",0.0)))
            az=math.radians(float(a.get("inclination_azimuth",self.values.get("inclination_azimuth",0.0))))
            self.direction=QVector3D(math.cos(az),math.sin(az),0);self.angle=float(a.get("inclination",self.values.get("inclination",0.0)))
            self.controller.message(f"Incline o segmento {self.segment_index+1} no plano da direção atual e clique. Digite o ângulo para precisão.")
        except ColumnError as exc:self.controller.message(str(exc),error=True);QTimer.singleShot(0,self.controller.return_to_select)
        viewport.update()
    def on_deactivate(self,viewport):self.reset();viewport.update()
    def drag_plane(self,viewport):
        if self.base is None or self.direction is None:return None
        return self.base,QVector3D(-self.direction.y(),self.direction.x(),0)
    def _angle(self,world):
        run=QVector3D.dotProduct(QVector3D(world)-self.base,self.direction)
        return max(0.0,min(85.0,math.degrees(math.atan2(abs(run),max(1e-9,self.segment_height)))))
    def on_hover(self,ctx):self.angle=self._angle(ctx.world);ctx.viewport.update()
    def _values_with_angle(self,angle):
        vals=dict(self.values);stations=[dict(x) for x in vals.get("stations",[])]
        if len(stations)<2:return vals
        i=max(0,min(self.segment_index,len(stations)-2));stations[i]["inclination"]=float(angle);vals["stations"]=stations
        if i==0:vals["inclination"]=float(angle)
        return vals
    def _commit(self,viewport,angle):
        from .column_commands import EditColumn
        from .column_model import ColumnError
        vals=self._values_with_angle(angle)
        viewport.history.execute(EditColumn(viewport.scene,self.group,vals))
        if viewport.history.last_error:raise ColumnError(viewport.history.last_error)
        viewport.notify_scene_changed();self.controller.message(f"Inclinação do segmento {self.segment_index+1}: {float(angle):.2f}°")
        self.reset();self.controller.return_to_select()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,self._angle(ctx.world))
        except Exception as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_value(self,viewport,value):
        try:
            a=float(value)
            if not math.isfinite(a) or not 0<=a<=85:raise ValueError("A inclinação deve ficar entre 0° e 85°.")
            self._commit(viewport,a);return True
        except Exception as exc:self.controller.message(str(exc),error=True);return False
    def on_cancel(self,viewport):self.reset();self.controller.return_to_select();self.controller.message("Inclinação cancelada.");viewport.update()
    def rubber_band_lines(self):
        if self.group is None or self.values is None:return []
        from .column_model import reference_path_world_for
        try:pts=reference_path_world_for(self.group,self._values_with_angle(self.angle))
        except Exception:return []
        return list(zip(pts,pts[1:]))
    def value_label(self):return (f"{self.angle:.2f}°".replace(".",","),)


class MoveColumnStationVerticalTool(Tool):
    """Move one intermediate pillar station only in Z."""
    name = "Mover vértice do pilar na vertical"
    description = "Altera as alturas dos segmentos imediatamente abaixo e acima."
    uses_snap = True
    wireframe_color = (0.20, 0.48, 0.84, 1.0)
    vcb_label = "Cota"

    def __init__(self,controller):self.controller=controller;self.reset()
    def reset(self):self.group=None;self.values=None;self.index=None;self.anchor=None;self.hover_z=None
    def prepare(self,group,index,anchor):self.group=group;self.index=int(index);self.anchor=QVector3D(anchor);self.hover_z=float(anchor.z())
    def on_activate(self,viewport):
        from .column_model import ColumnError,read_column
        if self.group is None or self.group not in viewport.scene.groups:
            QTimer.singleShot(0,self.controller.return_to_select);return
        try:
            self.values=read_column(self.group);n=len(self.values.get("stations",[]))
            if self.index is None or self.index<=0 or self.index>=n-1:raise ColumnError("Selecione um vértice intermediário do pilar.")
            self.controller.message("Mova o vértice para cima/baixo. As alturas dos segmentos vizinhos serão atualizadas.")
        except ColumnError as exc:self.controller.message(str(exc),error=True);QTimer.singleShot(0,self.controller.return_to_select)
        viewport.update()
    def on_deactivate(self,viewport):self.reset();viewport.update()
    def drag_plane(self,viewport):
        if self.anchor is None:return None
        yaw=getattr(viewport.camera,"yaw",0.0);normal=QVector3D(math.cos(yaw),math.sin(yaw),0)
        if normal.length()<1e-9:normal=QVector3D(1,0,0)
        return QVector3D(self.anchor),normal.normalized()
    def on_hover(self,ctx):self.hover_z=float(ctx.world.z());ctx.viewport.update()
    def _candidate_values(self,z):
        from .column_model import move_station_vertical,insertion_world
        base=insertion_world(self.group).z();return move_station_vertical(self.values,self.index,float(z),base)
    def _commit(self,viewport,z):
        from .column_commands import EditColumn
        from .column_model import ColumnError
        vals=self._candidate_values(z);viewport.history.execute(EditColumn(viewport.scene,self.group,vals))
        if viewport.history.last_error:raise ColumnError(viewport.history.last_error)
        viewport.notify_scene_changed();self.controller.message("Cota do vértice do pilar atualizada.");self.reset();self.controller.return_to_select()
    def on_click(self,ctx):
        try:self._commit(ctx.viewport,ctx.world.z())
        except Exception as exc:self.controller.message(str(exc),error=True)
        ctx.viewport.update()
    def on_value(self,viewport,value):
        try:self._commit(viewport,float(value));return True
        except Exception as exc:self.controller.message(str(exc),error=True);return False
    def on_cancel(self,viewport):self.reset();self.controller.return_to_select();self.controller.message("Movimento vertical cancelado.");viewport.update()
    def rubber_band_lines(self):
        if self.group is None or self.values is None or self.hover_z is None:return []
        from .column_model import reference_path_world_for
        try:pts=reference_path_world_for(self.group,self._candidate_values(self.hover_z))
        except Exception:return []
        return list(zip(pts,pts[1:]))
    def value_label(self):return ((f"{self.hover_z:.4f} m".replace(".",",")) if self.hover_z is not None else "",)