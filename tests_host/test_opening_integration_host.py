# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-stage opening, fill and virtual-controller regression on real host."""
import unittest

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
