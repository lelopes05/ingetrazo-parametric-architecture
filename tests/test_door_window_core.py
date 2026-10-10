# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 02 pure geometry and stable object/host linking contracts."""
import unittest

from OpenTrace_BIM.door_window_core import (
    FillError, normalize_fill, station_span, reverse_swing,
    opening_request, hotspots, door_leaf_plan, window_mullions,
    reanchor_fill, edit_from_hotspot,
)


def door(**kwargs):
    return dict({"id": "door01", "host_id": "wall01", "opening_id": "void01",
                 "kind": "door", "position": 2.0}, **kwargs)


def window(**kwargs):
    return dict({"id": "window01", "host_id": "wall01", "opening_id": "void02",
                 "kind": "window", "position": 2.0}, **kwargs)


class DoorWindowCoreTests(unittest.TestCase):
    def test_three_anchor_positions_are_pinned(self):
        self.assertEqual(station_span(door(anchor="left", width=1)), (2, 3))
        self.assertEqual(station_span(door(anchor="center", width=1)), (1.5, 2.5))
        self.assertEqual(station_span(door(anchor="right", width=1)), (1, 2))

    def test_width_change_does_not_move_user_anchor(self):
        a = station_span(door(anchor="right", width=.9))
        b = station_span(door(anchor="right", width=1.2))
        self.assertEqual(a[1], b[1])
        self.assertEqual(b[0], 0.8)

    def test_swing_single_toggle_reverses_and_returns(self):
        orig = normalize_fill(door(swing=1))
        one = reverse_swing(orig)
        two = reverse_swing(one)
        self.assertEqual(one["swing"], -1)
        self.assertEqual(two["swing"], 1)
        self.assertEqual(one["id"], orig["id"])

    def test_door_in_walled_opening_uses_floor_and_stable_source(self):
        request = opening_request(door(width=1, height="2,10"), opening_guid="ifc1")
        self.assertEqual(request["sill"], 0)
        self.assertEqual(request["source_id"], "door01")
        self.assertEqual(request["id"], "void01")
        self.assertEqual(request["ifc_global_id"], "ifc1")
        self.assertEqual(request["fill"]["class"], "IfcDoor")

    def test_hotspot_controls_respect_upper_lower_permissions(self):
        arr = hotspots(door())
        self.assertEqual(len(arr), 6)
        self.assertEqual({v["id"] for v in arr}, {
            "bottom-left", "bottom-center", "bottom-right",
            "top-left", "top-center", "top-right"})
        for v in arr:
            self.assertIn("width", v["controls"])
            if v["id"].startswith("bottom"):
                self.assertIn("position", v["controls"])
                self.assertNotIn("height", v["controls"])
            else:
                self.assertIn("height", v["controls"])
                self.assertNotIn("position", v["controls"])

    def test_door_leaf_exact_90_degree_tips(self):
        a = door_leaf_plan(door(anchor="left", width=1, open_angle=90))
        self.assertAlmostEqual(a["tip"][0], 2, places=6)
        self.assertAlmostEqual(a["tip"][1], 1, places=6)
        b = door_leaf_plan(door(anchor="left", width=1, open_angle=90, swing=-1))
        self.assertAlmostEqual(b["tip"][1], -1, places=6)

    def test_fixed_window_and_mullions(self):
        a = window_mullions(window(width=1.2, height=1.4, sill=.9, panes=3))
        self.assertEqual(len(a), 2)
        self.assertAlmostEqual(a[0]["station"], 2.4, places=6)
        self.assertAlmostEqual(a[0]["bottom"], .9)
        self.assertAlmostEqual(a[1]["top"], 2.3)

    def test_window_is_not_swing_door(self):
        with self.assertRaises(FillError):
            reverse_swing(window())
        with self.assertRaises(FillError):
            door_leaf_plan(window())

    def test_invalid_stable_ids_or_dimensions_rejected(self):
        for item in (
            door(id=""),
            door(width=-1),
            door(anchor="middle"),
            door(height=float("nan")),
            door(swing=0),
            window(panes=0),
            window(sill=-.1),
        ):
            with self.subTest(item=item), self.assertRaises(FillError):
                normalize_fill(item)

    def test_separate_host_record_not_mutated(self):
        spec = door(swing=1)
        result = opening_request(spec)
        flipped = reverse_swing(spec)
        self.assertEqual(spec["swing"], 1)
        self.assertEqual(flipped["swing"], -1)
        self.assertEqual(result["source_id"], spec["id"])
        self.assertEqual(result["position"], 2.45)

    def test_reanchor_keeps_physical_opening_station_range(self):
        start = normalize_fill(window(anchor="left", width=1.2))
        for anchor in ("center", "right", "left"):
            updated = reanchor_fill(start, anchor)
            self.assertEqual(station_span(updated), station_span(start))
            self.assertEqual(updated["anchor"], anchor)
            self.assertEqual(updated["id"], start["id"])

    def test_radial_hotspot_permission_is_validated_in_engine(self):
        spec = door(anchor="center", width=.9, height=2.1)
        moved = edit_from_hotspot(spec, "bottom-left", "position", "3,0")
        self.assertAlmostEqual(station_span(moved)[0], 3.0)
        wider = edit_from_hotspot(spec, "top-center", "width", "1,20")
        self.assertAlmostEqual(wider["width"], 1.2)
        taller = edit_from_hotspot(spec, "top-right", "height", 2.4)
        self.assertAlmostEqual(taller["height"], 2.4)
        self.assertAlmostEqual(taller["sill"], spec.get("sill", 0.0))
        for point, action in (
                ("top-left", "position"),
                ("bottom-right", "height"),
                ("not-a-hotspot", "width")):
            with self.subTest(point=point, action=action):
                with self.assertRaises(FillError):
                    edit_from_hotspot(spec, point, action, 1.0)



if __name__ == "__main__":
    unittest.main()
