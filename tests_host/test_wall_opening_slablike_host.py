# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression for wall-opening editing patterned on slab vertex/edge palette."""
import copy
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from OpenTrace_BIM.model import DEFAULTS, make_wall_segment, read_wall
from OpenTrace_BIM.wall_polygon_tool import WallPolygonTool
from OpenTrace_BIM.opening_handle_drag import OpeningHandleDragTool
from OpenTrace_BIM.opening_controller import all_opening_wires, hit_test
from OpenTrace_BIM.wall_polygon import (insert_vertex,move_vertex,move_edge,
                                       delete_vertex,translate_polygon,stretch_edge)
from core.scene import Scene


def make_scene():
    poly={"id":"polygon-one","kind":"polygon",
          "polygon":[[1.0,.5],[2.0,.5],[2.0,2.0],[1.0,2.0]],
          "ifc_global_id":"persisted-poly-guid"}
    rect={"id":"rect-two","kind":"rect","position":4.1,"width":.5,
          "sill":.5,"height":1.4,"ifc_global_id":"rect-guid"}
    scene=Scene()
    wall=make_wall_segment(QVector3D(),QVector3D(5,0,0),
                           dict(DEFAULTS,length=5.0,openings=[poly,rect]))
    scene.groups.append(wall)
    return scene,wall


class View:
    def __init__(self,scene):
        self.scene=scene
        self.history=History(scene)
        self.notifications=0
    def update(self):pass
    def notify_scene_changed(self):self.notifications+=1
    def _world_to_pixel(self,p):return (p.x()*100,-p.z()*100)


class History:
    last_error=None
    def __init__(self,scene):self.scene=scene;self.commands=[]
    def execute(self,cmd):
        cmd.do(self.scene)
        self.commands.append(cmd)


def controller(scene):
    ctl=SimpleNamespace(app=SimpleNamespace(scene=scene),
                        _state_key=None,_loaded_key=None,
                        _active_opening_id=None,_active_opening_wall=None,
                        _find_linked_fill=lambda op:None,
                        message=lambda *a,**kw:None,return_to_select=lambda:None)
    return ctl


def ctx(vp,x,z):
    return SimpleNamespace(viewport=vp,world=QVector3D(x,0,z),
                           screen=QPointF(x*100,-z*100))


def opening(wall,name="polygon-one"):
    return next(o for o in read_wall(wall)["openings"] if o["id"]==name)


class SlabLikeOpeningEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp=QApplication.instance() or QApplication([])

    def test_polygon_hit_reports_exact_logical_vertex_or_edge_without_wall_preselection(self):
        scene,wall=make_scene()
        vp=View(scene)
        wires=all_opening_wires(wall,read_wall(wall))
        self.assertEqual(hit_test(vp,wires,100,-50),("polygon-one","vertex-0"))
        self.assertEqual(hit_test(vp,wires,150,-50),("polygon-one","edge-0"))
        self.assertEqual(hit_test(vp,wires,150,-130,allow_interior=True),
                         ("polygon-one",None))
        self.assertEqual(hit_test(vp,wires,200,-120),("polygon-one","edge-1"))

    def test_indexed_polygon_vertex_move_and_undo_do_not_touch_other_opening(self):
        scene,wall=make_scene();vp=View(scene);ctl=controller(scene)
        tool=WallPolygonTool(ctl)
        before=copy.deepcopy(read_wall(wall)["openings"])
        anchor=QVector3D(2,0,2)
        tool.prepare(wall,anchor,opening_id="polygon-one",
                     operation="move_vertex",index=2)
        tool.on_activate(vp)
        self.assertEqual(tool.vertex_index,2)
        self.assertIsNotNone(tool.pick_anchor)
        tool.on_hover(ctx(vp,2.3,2.1))
        self.assertEqual(len(vp.history.commands),0)
        self.assertTrue(tool.rubber_band_lines())
        tool.on_click(ctx(vp,2.3,2.1))
        self.assertEqual(len(vp.history.commands),1)
        self.assertAlmostEqual(opening(wall)["polygon"][2][0],2.3,places=5)
        self.assertAlmostEqual(opening(wall)["polygon"][2][1],2.1,places=5)
        self.assertEqual(opening(wall)["ifc_global_id"],"persisted-poly-guid")
        self.assertEqual(opening(wall,"rect-two"),before[1])
        vp.history.commands[0].undo(scene)
        self.assertEqual(read_wall(wall)["openings"],before)

    def test_indexed_edge_move_insert_stretch_and_whole_opening_move(self):
        scene,wall=make_scene();vp=View(scene);ctl=controller(scene)
        def run(operation,index,anchor,target):
            tool=WallPolygonTool(ctl)
            tool.prepare(wall,QVector3D(*anchor),opening_id="polygon-one",
                         operation=operation,index=index)
            tool.on_activate(vp)
            tool.on_hover(ctx(vp,*target))
            self.assertTrue(tool.rubber_band_lines())
            tool.on_click(ctx(vp,*target))
            self.assertIsNone(vp.history.last_error)
        # Move upper horizontal edge (index 2) by +20 cm in elevation.
        run("move_edge",2,(1.5,0,2.0),(1.5,2.2))
        self.assertAlmostEqual(opening(wall)["polygon"][2][1],2.2,places=5)
        self.assertAlmostEqual(opening(wall)["polygon"][3][1],2.2,places=5)
        # Split first edge at the hovered midpoint: selected edge index
        # is not rediscovered by another click.
        run("insert_vertex",0,(1.5,0,.5),(1.5,.5))
        self.assertEqual(len(opening(wall)["polygon"]),5)
        # Extrude right edge (index 2 after insert) outwards.
        run("stretch_edge",2,(2,0,1.25),(2.2,1.25))
        self.assertEqual(len(opening(wall)["polygon"]),7)
        original=copy.deepcopy(opening(wall)["polygon"])
        move=WallPolygonTool(ctl)
        move.prepare(wall,QVector3D(1.5,0,1.0),opening_id="polygon-one",
                     operation="move_opening")
        move.on_activate(vp)
        move.on_click(ctx(vp,1.5,1.0))
        move.on_hover(ctx(vp,1.7,1.3))
        self.assertTrue(move.rubber_band_lines())
        move.on_click(ctx(vp,1.7,1.3))
        after=opening(wall)["polygon"]
        for a,b in zip(original,after):
            self.assertAlmostEqual(b[0]-a[0],.2,places=5)
            self.assertAlmostEqual(b[1]-a[1],.3,places=5)
        self.assertEqual(len(vp.history.commands),4)

    def test_delete_polygon_vertex_via_palette_keeps_valid_edge_metadata_and_undo(self):
        from OpenTrace_BIM.ui import WallController
        scene,wall=make_scene()
        vp=View(scene)
        ctl=SimpleNamespace(
            app=SimpleNamespace(scene=scene,viewport=vp),
            opening_edit_palette=SimpleNamespace(hide=lambda:None),
            _opening_edit_wall=wall,
            _opening_edit_id="polygon-one",
            _opening_edit_handle="vertex-2",
            _opening_edit_anchor=None,
            _active_opening_wall=wall,
            _active_opening_id="polygon-one",
            target=wall,target_scene=scene,
            _state_key=None,schedule_refresh=lambda:None,
            message=lambda *a,**kw:None)
        before=copy.deepcopy(read_wall(wall)["openings"])
        WallController._run_opening_edit_action(ctl,"delete_vertex")
        poly=opening(wall)
        self.assertEqual(len(poly["polygon"]),3)
        self.assertEqual(len(poly["edges"]),3)
        self.assertEqual(poly["ifc_global_id"],"persisted-poly-guid")
        self.assertEqual(opening(wall,"rect-two"),before[1])
        self.assertEqual(len(vp.history.commands),1)
        vp.history.commands[0].undo(scene)
        self.assertEqual(read_wall(wall)["openings"],before)

    def test_real_qt_radial_palette_arms_selected_polygon_edge_without_repick(self):
        from views.main_window import MainWindow
        from views.extension_api import ExtensionApp
        from OpenTrace_BIM import setup
        window=MainWindow()
        try:
            setup(ExtensionApp(window,"OpenTrace_BIM"))
            ctl=window._arquitetura_parametrica_controller
            _old,wall=make_scene()
            scene=window.viewport.scene
            scene.groups.append(wall)
            scene.version+=1
            ctl._active_opening_wall=wall
            ctl._active_opening_id="polygon-one"
            ctl.target=wall
            ctl._show_opening_edit_palette("polygon-one","edge-2",QPoint(130,160))
            self.assertTrue(ctl.opening_edit_palette.isVisible())
            self.assertTrue(ctl.opening_edit_buttons["move_edge"].isVisible())
            self.assertTrue(ctl.opening_edit_buttons["insert_vertex"].isVisible())
            self.assertFalse(ctl.opening_edit_buttons["move_vertex"].isVisible())
            ctl._run_opening_edit_action("move_edge")
            self.assertIs(window.viewport.active_tool,ctl.polygon_tool)
            self.assertEqual(ctl.polygon_tool.edge_index,2)
            self.assertIsNotNone(ctl.polygon_tool.pick_anchor)
        finally:
            window.deleteLater()
            self.qapp.processEvents()

    def test_free_rectangle_corner_and_edge_pick_promote_only_when_edited(self):
        scene,wall=make_scene();vp=View(scene)
        wires=all_opening_wires(wall,read_wall(wall))
        # The existing rectangle is not converted by highlighting/picking.
        opts={"rect-two"}
        self.assertEqual(hit_test(vp,wires,385,-50,
                                  editable_rect_ids=opts),
                         ("rect-two","vertex-0"))
        self.assertEqual(hit_test(vp,wires,410,-50,
                                  editable_rect_ids=opts),
                         ("rect-two","edge-0"))
        self.assertEqual(opening(wall,"rect-two")["kind"],"rect")
        tool=WallPolygonTool(controller(scene))
        tool.prepare(wall,QVector3D(4.1,0,1.9),
                     opening_id="rect-two",operation="move_edge",
                     index=2,convert_rect=True)
        tool.on_activate(vp)
        self.assertEqual(tool.edge_index,2)
        tool.on_hover(ctx(vp,4.1,2.1))
        self.assertEqual(len(vp.history.commands),0)
        tool.on_click(ctx(vp,4.1,2.1))
        self.assertEqual(len(vp.history.commands),1)
        converted=opening(wall,"rect-two")
        self.assertEqual(converted["kind"],"polygon")
        self.assertEqual(len(converted["polygon"]),4)
        self.assertAlmostEqual(converted["polygon"][2][1],2.1,places=5)
        self.assertEqual(converted["ifc_global_id"],"rect-guid")
        vp.history.commands[0].undo(scene)
        self.assertEqual(opening(wall,"rect-two")["kind"],"rect")
        self.assertAlmostEqual(opening(wall,"rect-two")["height"],1.4)

    def test_same_polygon_opening_can_edit_two_distinct_edges_consecutively(self):
        """Regression: first EditWall invalidates native pick, second must work."""
        from OpenTrace_BIM.ui import WallController
        from OpenTrace_BIM.host import activate_select
        scene,wall=make_scene()
        vp=View(scene)
        ctl=controller(scene)
        scene.selection.add(wall)
        ctl._active_opening_wall=wall
        ctl._active_opening_id="polygon-one"
        ctl.app.viewport=vp
        for index,dz in ((2,.15),(0,-.10)):
            wires=all_opening_wires(wall,read_wall(wall))
            # Midpoint of a logical edge, rather than a mesh thickness edge.
            mid=(wires[0][1][index][0]+wires[0][1][index][1])*.5
            selected=hit_test(vp,wires,mid.x()*100,-mid.z()*100,
                              active_id="polygon-one")
            self.assertEqual(selected,("polygon-one",f"edge-{index}"))
            tool=WallPolygonTool(ctl)
            tool.prepare(wall,mid,opening_id="polygon-one",
                         operation="move_edge",index=index)
            tool.on_activate(vp)
            before=len(vp.history.commands)
            tool.on_hover(ctx(vp,mid.x(),mid.z()+dz))
            tool.on_click(ctx(vp,mid.x(),mid.z()+dz))
            self.assertEqual(len(vp.history.commands),before+1)
            self.assertIn(wall,scene.selection)
            self.assertEqual(ctl._active_opening_id,"polygon-one")
            self.assertIs(ctl._active_opening_wall,wall)
        self.assertEqual(len(vp.history.commands),2)
        vp.history.commands[-1].undo(scene)
        self.assertEqual(len(read_wall(wall)["openings"]),2)
        self.assertEqual(opening(wall)["ifc_global_id"],"persisted-poly-guid")

    def test_virtual_pick_cleared_after_wall_edit_retains_parametric_target(self):
        from OpenTrace_BIM.ui import WallController
        scene,wall=make_scene()
        scene.selection.add(wall)
        calls=[]
        ctl=SimpleNamespace(app=SimpleNamespace(scene=scene),
                            _active_opening_wall=wall,
                            _active_opening_id="polygon-one",
                            _state_key=("old",),
                            schedule_refresh=lambda:calls.append("refresh"))
        WallController._select_virtual_opening(ctl,None)
        self.assertEqual(ctl._active_opening_id,"polygon-one")
        self.assertIs(ctl._active_opening_wall,wall)
        self.assertEqual(calls,["refresh"])
        scene.selection.clear()
        WallController._select_virtual_opening(ctl,None)
        self.assertIsNone(ctl._active_opening_wall)
        self.assertIsNone(ctl._active_opening_id)

    def test_toolbar_opening_can_pick_host_without_preselect(self):
        from OpenTrace_BIM.wall_opening_tool import WallOpeningTool
        scene,wall=make_scene()
        vp=View(scene)
        vp.pick_group=lambda x,y:wall
        vp.scene.entity_visible=lambda entity:True
        vp.scene.entity_selectable=lambda entity:True
        ctl=controller(scene)
        tool=WallOpeningTool(ctl)
        tool.prepare(None,None,kind="opening")
        tool.on_activate(vp)
        self.assertIsNone(tool.group)
        self.assertEqual(len(vp.history.commands),0)
        tool.on_hover(ctx(vp,3.1,1.2))
        self.assertIs(tool.group,wall)
        self.assertIsNotNone(tool.item)
        tool.on_click(ctx(vp,3.1,1.2))
        self.assertEqual(len(vp.history.commands),1)
        self.assertEqual(len(read_wall(wall)["openings"]),3)
        self.assertIn(wall,scene.selection)
        self.assertIs(ctl._active_opening_wall,wall)
        vp.history.commands[0].undo(scene)
        self.assertEqual(len(read_wall(wall)["openings"]),2)

    def test_toolbar_polygon_acquires_wall_and_click_starts_first_vertex(self):
        scene,wall=make_scene()
        vp=View(scene)
        vp.pick_group=lambda x,y:wall
        ctl=controller(scene)
        tool=WallPolygonTool(ctl)
        tool.prepare(None,None)
        tool.on_activate(vp)
        self.assertIsNone(tool.wall)
        tool.on_click(ctx(vp,2.6,0.4))
        self.assertIs(tool.wall,wall)
        self.assertEqual(len(tool.points),1)
        self.assertAlmostEqual(tool.points[0][0],2.6,places=5)

    def test_clicking_same_opening_edge_twice_reopens_palette_after_edit(self):
        """The active opening must be repeatedly editable after scene changes."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from OpenTrace_BIM.ui import WallController
        from types import SimpleNamespace
        scene,wall=make_scene()
        scene.selection.add(wall)
        select=object()
        called=[]
        vp=SimpleNamespace(scene=scene,active_tool=select,extension_pick=None)
        window=SimpleNamespace(_tools={"select":select})
        ctl=SimpleNamespace(app=SimpleNamespace(scene=scene,viewport=vp,window=window),
            _active_opening_wall=wall,_active_opening_id="polygon-one",
            _pointer_opening_grip=None,
            path_palette=SimpleNamespace(isVisible=lambda:False),
            _pick_virtual_opening=lambda *args:(wall.uid,"polygon-one","edge-0"),
            _show_opening_edit_palette=lambda oid,handle,p:called.append((oid,handle)),
            hide_path_palette=lambda:None)
        event=SimpleNamespace(type=lambda:QEvent.MouseButtonPress,
            button=lambda:Qt.LeftButton,modifiers=lambda:Qt.NoModifier,
            position=lambda:QPointF(150,-50),
            globalPosition=lambda:QPointF(150,150))
        for _ in range(2):
            self.assertTrue(WallController.eventFilter(ctl,vp,event))
            self.qapp.processEvents()
            scene.version+=1  # Every EditWall/Undo invalidates native pick
        self.assertEqual(called,[("polygon-one","edge-0")]*2)

    def test_move_rectangular_opening_on_wall_plane_with_single_undo(self):
        scene,wall=make_scene();vp=View(scene);ctl=controller(scene)
        tool=OpeningHandleDragTool(ctl)
        tool.prepare(wall,"rect-two","bottom-center","move")
        tool.on_activate(vp)
        self.assertIsNotNone(tool.grip)
        center=tool.grip
        tool.on_hover(ctx(vp,center.x()-.2,center.z()+.3))
        self.assertEqual(len(vp.history.commands),0)
        tool.on_click(ctx(vp,center.x()-.2,center.z()+.3))
        self.assertEqual(len(vp.history.commands),1)
        self.assertAlmostEqual(opening(wall,"rect-two")["position"],3.9,places=5)
        self.assertAlmostEqual(opening(wall,"rect-two")["sill"],.8,places=5)
        vp.history.commands[0].undo(scene)
        self.assertAlmostEqual(opening(wall,"rect-two")["position"],4.1,places=5)


if __name__=="__main__":
    unittest.main()
