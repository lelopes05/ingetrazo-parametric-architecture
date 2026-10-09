# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 02 real IngeTrazo mesh tests; no GUI/host event loop needed."""
import unittest

from OpenTrace_BIM.door_window_geometry import build_fill_parts, make_fill_group


def element(kind, **kwargs):
    obj = {"kind": kind, "id": f"{kind}-001", "opening_id": "opening001",
           "host_id": "wall001", "position": 2}
    obj.update(kwargs)
    return obj


class FillMeshTests(unittest.TestCase):
    def assert_closed_mesh(self, group):
        self.assertEqual(len(group.mesh.faces), 6)
        self.assertEqual(len([e for e in group.mesh.edges if len(e.faces) != 2]), 0)

    def test_one_swing_door_has_jambs_head_and_leaf(self):
        parts = build_fill_parts(element("door"))
        self.assertEqual(len(parts), 4)
        for part in parts:
            self.assert_closed_mesh(part)

    def test_reverse_swing_repositions_leaf_not_frame(self):
        positive = build_fill_parts(element("door", swing=1))
        negative = build_fill_parts(element("door", swing=-1))
        self.assertEqual(
            sorted(p.toTuple() for p in positive[0].mesh.vertices), 
            sorted(p.toTuple() for p in negative[0].mesh.vertices))
        one_y = [v.position.y() for v in positive[-1].mesh.vertices]
        other_y = [v.position.y() for v in negative[-1].mesh.vertices]
        self.assertGreater(max(one_y), 0)
        self.assertLess(min(other_y), 0)

    def test_window_three_glass_units_has_compatible_frame(self):
        parts = build_fill_parts(element("window", panes=3))
        self.assertEqual(len(parts), 9)
        self.assertEqual(sum(p.name.startswith("Vidro") for p in parts), 3)
        for part in parts:
            self.assert_closed_mesh(part)

    def test_group_preserves_identity_and_host_reference(self):
        spec = element("door", anchor="right", position=3.0)
        obj = make_fill_group(spec)
        rec = obj.ext["arquitetura_parametrica"]
        self.assertEqual(rec["kind"], "door")
        self.assertEqual(rec["host_id"], "wall001")
        self.assertEqual(rec["opening_id"], "opening001")
        self.assertEqual(rec["source_id"], "door-001")
        self.assertEqual(rec["params"]["anchor"], "right")
        self.assertEqual(obj.ifc["class"], "IfcDoor")
        self.assertEqual(len(obj.children), 4)


if __name__ == "__main__":
    unittest.main()
