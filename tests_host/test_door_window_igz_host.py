# SPDX-License-Identifier: GPL-3.0-or-later
"""Real native .igz round-trip of separate hosted 3D fills."""
import tempfile
import unittest
from pathlib import Path

from PySide6.QtGui import QVector3D
from core.scene import Scene
from formats.igz import load_into, save_scene

from OpenTrace_BIM.door_window_commands import CreateHostedFill, EditHostedFill
from OpenTrace_BIM.model import DEFAULTS, make_wall_segment, read_wall


class HostedFillIgzTests(unittest.TestCase):
    def test_window_group_opening_and_guid_survive_save_open_and_edit(self):
        original = Scene()
        wall = make_wall_segment(
            QVector3D(0, 0, 0), QVector3D(5, 0, 0),
            dict(DEFAULTS, length=5))
        original.groups.append(wall)
        raw = {"kind": "window", "id": "window-stable-id",
               "host_id": wall.uid, "opening_id": "opening-stable-id",
               "position": 2.5, "anchor": "center", "panes": 2}
        create = CreateHostedFill(original, wall, raw)
        create.do(original)
        fill = create.group
        fill_uid, ifc_guid = fill.uid, fill.ifc["global_id"]
        opening_guid = read_wall(wall)["openings"][0]["ifc_global_id"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage02.igz"
            save_scene(original, path)
            reopened = Scene()
            load_into(reopened, path)

        self.assertEqual(len(reopened.groups), 2)
        wall_again = next(g for g in reopened.groups if g.uid == wall.uid)
        fill_again = next(g for g in reopened.groups if g.uid == fill_uid)
        record = fill_again.ext["arquitetura_parametrica"]
        self.assertEqual(record["params"]["id"], "window-stable-id")
        self.assertEqual(record["params"]["panes"], 2)
        self.assertEqual(record["opening_id"], "opening-stable-id")
        self.assertEqual(fill_again.ifc["global_id"], ifc_guid)
        self.assertEqual(len(fill_again.children), len(fill.children))
        opening = read_wall(wall_again)["openings"][0]
        self.assertEqual(opening["ifc_global_id"], opening_guid)
        self.assertEqual(opening["source_id"], "window-stable-id")
        self.assertEqual(opening["fill"]["global_id"], ifc_guid)

        edit = EditHostedFill(reopened, wall_again, fill_again, {"width": 1.5})
        edit.do(reopened)
        self.assertAlmostEqual(read_wall(wall_again)["openings"][0]["width"], 1.5)
        self.assertEqual(fill_again.uid, fill_uid)
        edit.undo(reopened)
        self.assertAlmostEqual(read_wall(wall_again)["openings"][0]["width"], 1.2)


if __name__ == "__main__":
    unittest.main()
