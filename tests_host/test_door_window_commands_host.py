# SPDX-License-Identifier: GPL-3.0-or-later
"""Real Scene + Mesh integration tests for atomic stage-02 commands.

This suite intentionally does not import the GUI or register toolbar actions.
Floor-level door cutouts are still gated on Stage 01's wall engine.
"""
import unittest

from PySide6.QtGui import QVector3D
from core.scene import Scene

from OpenTrace_BIM.door_window_commands import (
    CreateHostedFill, EditHostedFill, reverse_hosted_door,
)
from OpenTrace_BIM.door_window_core import FillError
from OpenTrace_BIM.model import DEFAULTS, WallError, make_wall_segment, read_wall


def fixture(kind="window", **changes):
    wall = make_wall_segment(
        QVector3D(0, 0, 0), QVector3D(5, 0, 0),
        dict(DEFAULTS, length=5))
    scene = Scene()
    scene.groups.append(wall)
    spec = {
        "id": kind + "-fixed-id", "kind": kind,
        "host_id": wall.uid, "opening_id": "opening-fixed-id",
        "position": 2.5, "anchor": "center",
    }
    if kind == "door":
        # The stage-02 branch is based on foundation #3, not the stage-01
        # generator: a bottom strip is required until the branches meet.
        spec.update({"sill": 0.20, "height": 2.10})
    spec.update(changes)
    return scene, wall, spec


class HostedFillCommandTests(unittest.TestCase):
    def test_create_undo_redo_preserves_both_identities(self):
        scene, wall, spec = fixture()
        original = read_wall(wall)
        command = CreateHostedFill(scene, wall, spec)
        command.do(scene)
        fill = command.group
        self.assertIn(fill, scene.groups)
        self.assertEqual(len(read_wall(wall)["openings"]), 1)
        opening = read_wall(wall)["openings"][0]
        self.assertEqual(opening["id"], spec["opening_id"])
        self.assertEqual(opening["source_id"], spec["id"])
        self.assertEqual(opening["fill"]["global_id"], fill.ifc["global_id"])
        first_uid, first_guid = fill.uid, fill.ifc["global_id"]
        self.assertEqual(len(fill.children), 5)
        command.undo(scene)
        self.assertNotIn(fill, scene.groups)
        self.assertEqual(read_wall(wall)["openings"], original["openings"])
        command.do(scene)
        self.assertIs(command.group, fill)
        self.assertEqual(fill.uid, first_uid)
        self.assertEqual(fill.ifc["global_id"], first_guid)
        self.assertEqual(len(scene.groups), 2)

    def test_reject_occupied_opening_and_duplicate_fill_identity(self):
        scene, wall, spec = fixture()
        create = CreateHostedFill(scene, wall, spec)
        create.do(scene)
        with self.assertRaises(FillError):
            CreateHostedFill(scene, wall, dict(spec, id="another-id"))
        with self.assertRaises(FillError):
            CreateHostedFill(scene, wall, dict(spec, opening_id="other-opening"))
        self.assertEqual(len(scene.groups), 2)

    def test_edit_rebuilds_wall_and_fill_in_one_history_object(self):
        scene, wall, spec = fixture()
        create = CreateHostedFill(scene, wall, spec)
        create.do(scene)
        fill = create.group
        old_xform = fill.xform.map(QVector3D(0, 0, 0))
        initial_uid = fill.uid
        initial_guid = fill.ifc["global_id"]
        initial_opening_guid = read_wall(wall)["openings"][0]["ifc_global_id"]
        edit = EditHostedFill(scene, wall, fill, {
            "position": 3.0, "width": 1.6, "anchor": "right",
            "name": "Janela modificada",
        })
        edit.do(scene)
        changed = read_wall(wall)["openings"][0]
        self.assertAlmostEqual(changed["position"], 2.2)
        self.assertAlmostEqual(changed["width"], 1.6)
        self.assertEqual(changed["source_id"], spec["id"])
        self.assertEqual(changed["ifc_global_id"], initial_opening_guid)
        self.assertEqual(fill.ext["arquitetura_parametrica"]["params"]["width"], 1.6)
        self.assertEqual(fill.name, "Janela modificada")
        new_xform = fill.xform.map(QVector3D(0, 0, 0))
        self.assertNotAlmostEqual(old_xform.x(), new_xform.x())
        edit.undo(scene)
        self.assertAlmostEqual(read_wall(wall)["openings"][0]["width"], 1.2)
        self.assertAlmostEqual(fill.ext["arquitetura_parametrica"]["params"]["width"], 1.2)
        edit.do(scene)
        self.assertEqual(fill.uid, initial_uid)
        self.assertEqual(fill.ifc["global_id"], initial_guid)
        self.assertEqual(len(scene.groups), 2)

    def test_reverse_swing_is_one_undoable_operation(self):
        scene, wall, spec = fixture("door")
        create = CreateHostedFill(scene, wall, spec)
        create.do(scene)
        fill = create.group
        reverse = reverse_hosted_door(scene, wall, fill)
        reverse.do(scene)
        self.assertEqual(fill.ext["arquitetura_parametrica"]["params"]["swing"], -1)
        self.assertEqual(read_wall(wall)["openings"][0]["source_id"], spec["id"])
        reverse.undo(scene)
        self.assertEqual(fill.ext["arquitetura_parametrica"]["params"]["swing"], 1)
        reverse.do(scene)
        self.assertEqual(fill.ext["arquitetura_parametrica"]["params"]["swing"], -1)

    def test_invalid_placement_rolls_back_wall_and_scene(self):
        scene, wall, spec = fixture(position=0.01, anchor="left")
        before = read_wall(wall)
        # The wall generator is allowed to reject it at command planning
        # time, before anything touches the live document.
        with self.assertRaises((FillError, WallError)):
            command = CreateHostedFill(scene, wall, spec)
            command.do(scene)
        self.assertEqual(read_wall(wall), before)
        self.assertEqual(scene.groups, [wall])

    def test_edit_cannot_change_host_opening_or_object_identity(self):
        scene, wall, spec = fixture()
        create = CreateHostedFill(scene, wall, spec)
        create.do(scene)
        with self.assertRaises(FillError):
            EditHostedFill(scene, wall, create.group, {"opening_id": "foreign-id"})
        with self.assertRaises(FillError):
            EditHostedFill(scene, wall, create.group, {"id": "foreign-fill"})
        self.assertEqual(len(scene.groups), 2)


if __name__ == "__main__":
    unittest.main()
