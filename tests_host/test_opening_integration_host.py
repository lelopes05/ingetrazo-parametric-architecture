# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-stage opening, fill and virtual-controller regression on real host."""
import unittest
from types import SimpleNamespace

from PySide6.QtGui import QVector3D
from core.scene import Scene

from OpenTrace_BIM.model import (DEFAULTS, make_wall_segment, make_arc_wall,
                                 read_wall, wall_opening_intervals)
from OpenTrace_BIM.opening_controller import (all_opening_wires, hit_test)
from OpenTrace_BIM.commands import EditWall, ReshapeWall
from OpenTrace_BIM.door_window_commands import (
    CreateHostedFill, DeleteHostedOpening, sync_hosted_fill_placements
)


class FakeViewport:
    def _world_to_pixel(self, point):
        return (point.x()*100, -point.z()*100)


def scene_wall(openings=(), length=5.0):
    wall = make_wall_segment(
        QVector3D(0, 0, 0), QVector3D(length, 0, 0),
        dict(DEFAULTS, length=length, openings=list(openings)))
    scene=Scene()
    scene.groups.append(wall)
    return scene, wall


class IntegratedOpeningRuntimeTests(unittest.TestCase):
    def test_selected_wall_overlay_clips_extreme_coordinates_before_qpainter(self):
        from PySide6.QtGui import QImage, QColor, QPainter
        from OpenTrace_BIM.ui import WallController
        from OpenTrace_BIM.overlay_safety import visible_segment
        scene,wall=scene_wall([{"id":"extreme-clipping",
            "kind":"rect","position":2.5,"width":1.0,
            "sill":0,"height":2.1}])
        scene.selection.add(wall)

        class ExtremeViewport:
            def width(self):return 800
            def height(self):return 600
            def _world_to_pixel(self,p):
                return (100.0 + p.x()*1e9, 120.0-p.z()*1e9)
            def _clip_segment_front(self,a,b):return (a,b)
            def _clip_pixel_line(self,p0,p1,margin=32.0):
                x0,y0=p0;x1,y1=p1
                dx,dy=x1-x0,y1-y0
                lo,hi=0.0,1.0
                for p,q in ((-dx,x0+margin),(dx,800+margin-x0),
                            (-dy,y0+margin),(dy,600+margin-y0)):
                    if abs(p)<1e-16:
                        if q<0:return None
                        continue
                    t=q/p
                    if p<0:lo=max(lo,t)
                    else:hi=min(hi,t)
                    if lo>hi:return None
                return ((x0+lo*dx,y0+lo*dy),(x0+hi*dx,y0+hi*dy))

        vp=ExtremeViewport()
        clipped=visible_segment(vp,QVector3D(0,0,0),QVector3D(5,0,0))
        self.assertIsNotNone(clipped)
        self.assertLessEqual(max(abs(v) for pt in clipped for v in pt),832)
        ctrl=SimpleNamespace(app=SimpleNamespace(scene=scene),
                             target=wall,_active_opening_wall=None,
                             _active_opening_id="extreme-clipping",
                             _opening_wires_for=lambda host:all_opening_wires(host,read_wall(host)),
                             curve_create_tool=None,move_vertex_continue_tool=None)
        vp.active_tool=object()
        vp.extension_pick=None
        image=QImage(800,600,QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter=QPainter(image)
        try:
            WallController.draw_reference_overlay(ctrl,vp,painter)
        finally:
            painter.end()
        self.assertTrue(any(image.pixelColor(x,120)!=QColor("white")
                            for x in range(100,700)))

    def test_native_opening_selection_without_selected_wall(self):
        from OpenTrace_BIM.ui import WallController
        scene,wall=scene_wall([{"id":"pick-without-wall",
             "kind":"rect","position":2.5,"width":1.0,
             "sill":0.0,"height":2.1}])
        self.assertFalse(scene.selection)
        vp=FakeViewport()
        vp.scene=scene
        pick_wires=lambda target:all_opening_wires(target,read_wall(target))
        ctrl=SimpleNamespace(_active_opening_id=None,_active_opening_wall=None,
                             _opening_wires_for=pick_wires)
        selection=WallController._pick_virtual_opening(ctrl,vp,200,-210)
        self.assertIsNotNone(selection)
        self.assertEqual(selection[0],wall.uid)
        self.assertEqual(selection[1],"pick-without-wall")
        self.assertIsNone(selection[2])
        self.assertIsNone(WallController._pick_virtual_opening(ctrl,vp,-1000,-1000))

    def test_native_pick_selection_without_mutating_wall_geometry(self):
        from OpenTrace_BIM.ui import WallController
        scene,wall=scene_wall([{"id":"pick-callback",
            "kind":"rect","position":2.5,"width":1.0,
            "sill":0,"height":2.1}])
        body=wall.children[0]
        changes=[]
        ctrl=SimpleNamespace(app=SimpleNamespace(scene=scene),
             _active_opening_id=None,_active_opening_wall=None,
             _state_key=None,schedule_refresh=lambda:changes.append("refresh"))
        WallController._select_virtual_opening(ctrl,(wall.uid,"pick-callback",None))
        self.assertIs(ctrl._active_opening_wall,wall)
        self.assertEqual(ctrl._active_opening_id,"pick-callback")
        self.assertIs(wall.children[0],body)
        self.assertEqual(changes,["refresh"])

    def test_independent_virtual_controller_and_six_handles(self):
        op={"id":"free-cut","kind":"rect","position":2.5,
            "width":1.0,"sill":0.0,"height":2.1}
        scene,wall=scene_wall([op])
        before=wall.children[0]
        wires=all_opening_wires(wall,read_wall(wall))
        self.assertEqual(len(wires),1)
        self.assertEqual(len(wires[0][1]),12)
        self.assertEqual(len(wires[0][2]),6)
        self.assertIs(wall.children[0],before)
        hit=hit_test(FakeViewport(),wires,200,-210,
                     active_id="free-cut")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0],"free-cut")

    def test_two_openings_can_be_picked_individually(self):
        ops=[{"id":name,"position":pos,"width":.7,
              "sill":.7,"height":1.0} for name,pos in
             (("A",1.2),("B",3.7))]
        _scene,wall=scene_wall(ops)
        wires=all_opening_wires(wall,read_wall(wall))
        self.assertEqual({oid for oid,_,_ in wires},{"A","B"})
        self.assertEqual(len(wall.children),1)

    def test_floor_level_door_creation_and_atomic_deletion(self):
        scene,wall=scene_wall()
        spec={"id":"door-test","host_id":wall.uid,
              "opening_id":"door-opening","kind":"door",
              "anchor":"center","position":2.5,
              "width":.9,"height":2.1,"sill":0.0}
        create=CreateHostedFill(scene,wall,spec)
        create.do(scene)
        fill=create.group
        self.assertEqual(read_wall(wall)["openings"][0]["sill"],0)
        self.assertIn(fill,scene.groups)
        delete=DeleteHostedOpening(scene,wall,"door-opening")
        delete.do(scene)
        self.assertNotIn(fill,scene.groups)
        self.assertEqual(read_wall(wall)["openings"],[])
        delete.undo(scene)
        self.assertIn(fill,scene.groups)
        self.assertEqual(read_wall(wall)["openings"][0]["source_id"],"door-test")
        self.assertIs(scene.groups[1],fill)

    def test_host_move_reattaches_fill_and_preserves_guid(self):
        scene,wall=scene_wall()
        spec={"id":"window-test","host_id":wall.uid,"opening_id":"window-op",
              "kind":"window","position":2.0,"anchor":"center"}
        create=CreateHostedFill(scene,wall,spec)
        create.do(scene)
        fill=create.group
        before=fill.xform.map(QVector3D(0,0,0))
        original_id=fill.uid
        original_guid=fill.ifc["global_id"]
        wall.xform.translate(1.25, .75, 0)
        self.assertEqual(sync_hosted_fill_placements(scene),1)
        after=fill.xform.map(QVector3D(0,0,0))
        self.assertAlmostEqual(after.x()-before.x(),1.25,places=5)
        self.assertAlmostEqual(after.y()-before.y(),.75,places=5)
        self.assertEqual(sync_hosted_fill_placements(scene),0)
        self.assertEqual(fill.uid,original_id)
        self.assertEqual(fill.ifc["global_id"],original_guid)

    def test_selected_wall_resize_retains_host_selection_and_closed_cut(self):
        scene,wall=scene_wall([{
            "id":"host-resize","position":2.5,"width":.95,
            "sill":0.0,"height":2.1}])
        scene.selection.add(wall)
        uid=wall.uid
        old_body=wall.children[0]
        values=read_wall(wall)
        values["length"]=6.0
        cmd=EditWall(scene,wall,values)
        cmd.do(scene)
        self.assertIn(wall,scene.selection)
        self.assertEqual(wall.uid,uid)
        self.assertIsNot(wall.children[0],old_body)
        self.assertEqual(read_wall(wall)["openings"][0]["id"],"host-resize")
        for child in wall.children:
            self.assertFalse([edge for edge in child.mesh.edges
                              if len(edge.faces)!=2])
        cmd.undo(scene)
        self.assertIn(wall,scene.selection)
        self.assertIs(wall.children[0],old_body)
        self.assertAlmostEqual(read_wall(wall)["length"],5.0)

    def test_selected_wall_vertex_reshape_preserves_opening_record(self):
        scene,wall=scene_wall([{
            "id":"vertex-cut","position":2.5,"width":.8,
            "sill":1.0,"height":1.0}])
        scene.selection.add(wall)
        uid=wall.uid
        cmd=ReshapeWall(scene,wall,QVector3D(0,0,0),QVector3D(6,0,0))
        cmd.do(scene)
        self.assertEqual(wall.uid,uid)
        self.assertIn(wall,scene.selection)
        self.assertEqual(read_wall(wall)["openings"][0]["id"],"vertex-cut")
        cmd.undo(scene)
        self.assertAlmostEqual(read_wall(wall)["length"],5.0)

    def test_shrinking_past_hosted_void_does_not_throw_during_vertex_preview(self):
        """Original bug 5→3/2 must now preview a clipped/free host, not fail."""
        from OpenTrace_BIM.path_edit import MoveWallVertexTool
        scene,wall=scene_wall([{
            "id":"shrink-opening","position":2.5,"width":1.0,
            "sill":.6,"height":1.2}])
        scene.selection.add(wall)
        values=read_wall(wall)
        original_children=wall.children[:]
        ctrl=SimpleNamespace(app=SimpleNamespace(scene=scene))
        tool=MoveWallVertexTool(ctrl,"continue")
        tool.group=wall
        tool.scene=scene
        tool.values=values
        tool.kind="line"
        tool.endpoint=1
        tool.refs=[QVector3D(0,0,0),QVector3D(5,0,0)]
        for length in (4.0,3.0,2.0,4.0):
            tool.hover=QVector3D(length,0,0)
            preview=tool.preview_faces()
            self.assertGreater(len(preview),0, f"preview should allow {length} m")
            self.assertIs(wall.children[0],original_children[0])
            self.assertEqual(read_wall(wall)["openings"][0]["id"],"shrink-opening")
            self.assertIn(wall,scene.selection)

    def test_selected_3d_fill_resolves_exact_opening_not_previous_one(self):
        from OpenTrace_BIM.ui import selected_hosted_opening
        scene,wall=scene_wall()
        fills=[]
        for name,pos in (("left",1.15),("right",3.75)):
            cmd=CreateHostedFill(scene,wall,{
                "id":f"window-{name}", "opening_id":f"cut-{name}",
                "host_id":wall.uid,"kind":"window",
                "position":pos,"width":.7,"height":1.2,
                "sill":.9,"anchor":"center"})
            cmd.do(scene)
            fills.append(cmd.group)
        scene.selection.clear()
        scene.selection.add(fills[1])
        selected=selected_hosted_opening(scene)
        self.assertIsNotNone(selected)
        self.assertIs(selected[0],wall)
        self.assertEqual(selected[1],"cut-right")
        scene.selection.clear()
        scene.selection.add(fills[0])
        self.assertEqual(selected_hosted_opening(scene)[1],"cut-left")
        scene.selection.add(fills[1])
        self.assertIsNone(selected_hosted_opening(scene))

    def test_switching_openings_never_applies_old_widget_values(self):
        from OpenTrace_BIM.ui import WallController
        scene,wall=scene_wall([
            {"id":"A","position":1.15,"width":.75,"sill":.5,"height":1.2},
            {"id":"B","position":3.75,"width":.75,"sill":.6,"height":1.2},
        ])
        class Field:
            def __init__(self,value):self.v=value
            def value(self):return self.v
            def interpretText(self):pass
        original=read_wall(wall)
        fields={k:Field(float(original["openings"][0][k]))
                for k in ("position","width","sill","height")}
        fields["width"].v=.95
        changed=[]
        class History:
            last_error=None
            def execute(self,command):
                changed.append(command)
                command.do(scene)
        vp=SimpleNamespace(history=History(),notify_scene_changed=lambda:None)
        ctl=SimpleNamespace(_loading=False,target=wall,_active_opening_id="B",
                _fields_opening_id="A",_loaded_key=("old",),
                _state_key=("old",), opening_fields=fields,
                opening_fill=object(),app=SimpleNamespace(scene=scene,viewport=vp),
                sender=lambda:fields["width"],_find_linked_fill=lambda _op:None,
                schedule_refresh=lambda:None,message=lambda *a,**kw:None)
        WallController.opening_changed(ctl)
        self.assertFalse(changed)
        self.assertEqual(read_wall(wall)["openings"],original["openings"])
        # After a switch synchronously reloads the correct opening, only
        # the edited width may commit; all OTHER stale fields are ignored.
        ctl._fields_opening_id="B"
        WallController.opening_changed(ctl)
        self.assertEqual(len(changed),1)
        updated=read_wall(wall)["openings"]
        self.assertEqual(updated[0],original["openings"][0])
        self.assertAlmostEqual(updated[1]["width"],.95)
        for key in ("position","sill","height"):
            self.assertEqual(updated[1][key],original["openings"][1][key])

    def test_polygon_opening_recedes_through_host_and_restores(self):
        from OpenTrace_BIM.model import path_world
        opening={"id":"poly-recede","kind":"polygon",
                 "polygon":[[2.0,.7],[3.0,.7],[3.0,1.9],[2.0,1.9]],
                 "ifc_global_id":"polygon-persistent-guid"}
        scene,wall=scene_wall([opening])
        authored=read_wall(wall)["openings"][0]["polygon"]
        for length, span in ((4.0,(2.0,3.0)),(3.0,(2.0,3.0)),
                             (2.5,(2.0,2.5)),(2.1,(2.0,2.1)),
                             (2.0,None),(1.5,None),(5.0,(2.0,3.0))):
            vals=read_wall(wall)
            vals["length"]=length
            EditWall(scene,wall,vals).do(scene)
            rec=read_wall(wall)["openings"][0]
            self.assertEqual(rec["polygon"],authored)
            self.assertEqual(rec["ifc_global_id"],"polygon-persistent-guid")
            iv=wall_opening_intervals(read_wall(wall),path_world(wall))
            if span is None:
                self.assertEqual(iv,[])
            else:
                self.assertEqual(len(iv),1)
                self.assertAlmostEqual(iv[0]["s0"],span[0],places=5)
                self.assertAlmostEqual(iv[0]["s1"],span[1],places=5)
            for child in wall.children:
                open_edges=[e for e in child.mesh.edges if len(e.faces)!=2]
                self.assertFalse(open_edges,f"Polygon {length} m produced open edges: {open_edges[:3]}")

    def test_slanted_polygon_cut_preserves_identity_after_trim(self):
        from OpenTrace_BIM.model import path_world
        opening={"id":"poly-slope","kind":"polygon",
                 "polygon":[[1.8,.5],[3.0,.6],[2.8,2.0],[1.9,1.8]]}
        scene,wall=scene_wall([opening])
        before=read_wall(wall)["openings"][0]["polygon"]
        vals=read_wall(wall)
        vals["length"]=2.4
        EditWall(scene,wall,vals).do(scene)
        self.assertEqual(read_wall(wall)["openings"][0]["polygon"],before)
        iv=wall_opening_intervals(read_wall(wall),path_world(wall))
        self.assertEqual(len(iv),1)
        self.assertTrue(iv[0]["cut_clipped"])
        for child in wall.children:
            self.assertFalse([e for e in child.mesh.edges if len(e.faces)!=2])

    def test_virtual_controller_persists_outside_receded_wall(self):
        scene,wall=scene_wall([{
            "id":"ghost-cut","position":2.5,"width":1.0,"sill":.8,
            "height":1.2}])
        data=read_wall(wall)
        data["length"]=1.5
        EditWall(scene,wall,data).do(scene)
        self.assertEqual(wall_opening_intervals(
            read_wall(wall),
            __import__("OpenTrace_BIM.model",fromlist=["path_world"]).path_world(wall)),[])
        wires=all_opening_wires(wall,read_wall(wall))
        self.assertEqual(len(wires),1)
        self.assertEqual(len(wires[0][1]),12)
        self.assertEqual(len(wires[0][2]),6)
        selected=hit_test(FakeViewport(),wires,250,-140,
                          allow_interior=True)
        self.assertEqual(selected,("ghost-cut",None))
        self.assertGreater(wires[0][2][0][1].x(),1.5)

    def test_wall_recedes_through_opening_and_reexpands_without_losing_params(self):
        from OpenTrace_BIM.model import wall_opening_intervals, path_world
        opening={"id":"recede","position":2.5,"width":1.0,"sill":.8,
                 "height":1.2,"source_id":None}
        scene,wall=scene_wall([opening])
        original=read_wall(wall)["openings"][0].copy()
        guid=original.get("ifc_global_id")
        for length, expected in (
            (4.0,(2.0,3.0)),(3.0,(2.0,3.0)),
            (2.5,(2.0,2.5)),(2.1,(2.0,2.1)),
            (2.0,None),(1.5,None),(5.0,(2.0,3.0))
        ):
            data=read_wall(wall)
            data["length"]=length
            cmd=EditWall(scene,wall,data)
            cmd.do(scene)
            self.assertAlmostEqual(read_wall(wall)["length"],length,places=5)
            record=read_wall(wall)["openings"][0]
            self.assertEqual(record["id"],"recede")
            self.assertAlmostEqual(record["position"],2.5)
            self.assertAlmostEqual(record["width"],1.0)
            self.assertEqual(record.get("ifc_global_id"),guid)
            intervals=wall_opening_intervals(read_wall(wall),path_world(wall))
            if expected is None:
                self.assertEqual(intervals,[])
            else:
                self.assertEqual(len(intervals),1)
                self.assertAlmostEqual(intervals[0]["s0"],expected[0],places=5)
                self.assertAlmostEqual(intervals[0]["s1"],expected[1],places=5)
            for child in wall.children:
                self.assertFalse([edge for edge in child.mesh.edges
                                  if len(edge.faces)!=2],
                                 f"nonmanifold receding to {length} m")

    def test_receded_hosted_door_keeps_object_uid_and_source_identity(self):
        scene,wall=scene_wall()
        spec={"id":"recede-door","host_id":wall.uid,"opening_id":"door-void",
              "kind":"door","width":.9,"height":2.1,
              "position":2.5,"sill":0.0,"anchor":"center"}
        cmd=CreateHostedFill(scene,wall,spec)
        cmd.do(scene)
        door=cmd.group
        before_uid=door.uid
        for length in (3.0,2.6,2.0,5.0):
            values=read_wall(wall)
            values["length"]=length
            EditWall(scene,wall,values).do(scene)
            self.assertEqual(door.uid,before_uid)
            self.assertIn(door,scene.groups)
            void=read_wall(wall)["openings"][0]
            self.assertEqual(void["id"],"door-void")
            self.assertEqual(void["source_id"],"recede-door")

    def test_pick_inside_free_opening_but_not_a_filled_leaf(self):
        from OpenTrace_BIM.ui import WallController
        wall_data=[
            {"id":"free","position":1.2,"width":.8,"sill":.6,"height":1.2},
            {"id":"door","position":3.5,"width":.8,"sill":.6,"height":1.2,
             "source_id":"some-fill"}]
        scene,wall=scene_wall(wall_data)
        vp=FakeViewport()
        vp.scene=scene
        ctl=SimpleNamespace(_active_opening_id=None,_active_opening_wall=None,
                            _opening_wires_for=lambda w:all_opening_wires(w,read_wall(w)))
        pick_free=WallController._pick_virtual_opening(ctl,vp,120,-120)
        self.assertEqual(pick_free[1],"free")
        pick_door=WallController._pick_virtual_opening(ctl,vp,350,-120)
        self.assertIsNone(pick_door)

    def test_curved_host_outline_keeps_mesh_independent(self):
        values=dict(DEFAULTS,length=4.0,openings=[
            {"id":"curved-cut","position":2.0,"width":.8,
             "sill":.8,"height":1.1}])
        wall=make_arc_wall(QVector3D(0,0,0),QVector3D(4,0,0),
                           .65,values)
        wires=all_opening_wires(wall,read_wall(wall))
        self.assertEqual(len(wires),1)
        self.assertEqual(len(wires[0][2]),6)
        interval=wall_opening_intervals(read_wall(wall),
                                       __import__("OpenTrace_BIM.model",fromlist=["path_world"]).path_world(wall))[0]
        self.assertGreater(interval["reference_span"],0.0)


if __name__=="__main__":
    unittest.main()
