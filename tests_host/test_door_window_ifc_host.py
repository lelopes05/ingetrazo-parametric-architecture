# SPDX-License-Identifier: GPL-3.0-or-later
"""IFC4 regression: a physical fill must never be exported twice."""
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QVector3D
from core.scene import Scene

from OpenTrace_BIM.door_window_commands import CreateHostedFill, EditHostedFill
from OpenTrace_BIM.door_window_core import opening_request
from OpenTrace_BIM.ifc_export import export_ifc
from OpenTrace_BIM.model import DEFAULTS, make_wall_segment


def make_scene(kind="window", *, with_fill=True):
    wall = make_wall_segment(
        QVector3D(0, 0, 0), QVector3D(5, 0, 0),
        dict(DEFAULTS, length=5))
    scene = Scene()
    scene.groups.append(wall)
    spec = {"kind": kind, "id": "linked-fill-001", "host_id": wall.uid,
            "opening_id": "host-opening-001", "position": 2.50,
            "anchor": "center"}
    if kind == "door":
        # PR #7 is based on foundation; sill=0 cut requires the PR #5
        # wall motor and its independent runtime validation gate.
        spec.update({"sill": .20, "height": 2.10})
    if with_fill:
        command = CreateHostedFill(scene, wall, spec)
        command.do(scene)
        return scene, wall, command.group
    else:
        from OpenTrace_BIM.commands import EditWall
        from OpenTrace_BIM.model import read_wall
        values = read_wall(wall)
        values["openings"] = [opening_request(spec)]
        EditWall(scene, wall, values).do(scene)
        return scene, wall, None


def export_lines(scene, profile="opentrace"):
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "test.ifc"
        summary = export_ifc(
            SimpleNamespace(scene=scene), target,
            data={"project": {"name": "Stage 02 regression"},
                  "export": {"profile": profile,
                             "include_opening_relations": True,
                             "include_material_layers": False,
                             "include_quantities": False,
                             "include_styles": False}})
        return target.read_text(encoding="utf-8").splitlines(), summary


def entries(lines, entity):
    pattern = re.compile(r"^#\\d+=" + re.escape(entity.upper()) + r"\\(")
    return [line for line in lines if pattern.search(line)]


class HostedIfcTests(unittest.TestCase):
    def test_window_has_one_real_ifc_product_and_one_fill_relation(self):
        scene, wall, fill = make_scene()
        lines, summary = export_lines(scene)
        windows = entries(lines, "IfcWindow")
        self.assertEqual(len(windows), 1)
        self.assertEqual(len(entries(lines, "IfcOpeningElement")), 1)
        self.assertEqual(len(entries(lines, "IfcRelFillsElement")), 1)
        self.assertEqual(summary["openings"], 1)
        self.assertIn(fill.ifc["global_id"], windows[0])
        self.assertIn("1.2", windows[0])
        self.assertEqual(summary["elements"], 2)

    def test_door_has_one_ifc_product_and_survives_swing_edit(self):
        scene, wall, fill = make_scene("door")
        edit = EditHostedFill(scene, wall, fill, {"swing": -1, "width": 1.0})
        edit.do(scene)
        lines, summary = export_lines(scene)
        self.assertEqual(len(entries(lines, "IfcDoor")), 1)
        self.assertEqual(len(entries(lines, "IfcRelFillsElement")), 1)
        self.assertEqual(summary["elements"], 2)
        self.assertIn(fill.ifc["global_id"], entries(lines, "IfcDoor")[0])

    def test_unfilled_legacy_window_keeps_backward_compatible_stub(self):
        scene, wall, fill = make_scene(with_fill=False)
        lines, summary = export_lines(scene)
        self.assertEqual(len(entries(lines, "IfcWindow")), 1)
        self.assertEqual(len(entries(lines, "IfcRelFillsElement")), 1)
        self.assertEqual(summary["elements"], 1)

    def test_compatibility_profile_exports_body_but_no_cut_relation(self):
        scene, wall, fill = make_scene()
        lines, summary = export_lines(scene, profile="bonsai")
        self.assertEqual(len(entries(lines, "IfcWindow")), 1)
        self.assertEqual(len(entries(lines, "IfcRelFillsElement")), 0)
        self.assertEqual(summary["elements"], 2)


if __name__ == "__main__":
    unittest.main()
