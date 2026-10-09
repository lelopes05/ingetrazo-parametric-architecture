# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-Python wall opening geometry planning tests (no Qt required)."""
import unittest

from OpenTrace_BIM.opening_profile import opening_slice, profile_crossings


class WallCutLayoutTests(unittest.TestCase):
    def test_existing_window_keeps_wall_above_and_below(self):
        self.assertEqual(opening_slice(3.0, 0.9, 1.2),
                         {"cut": True, "below": True, "above": True})

    def test_floor_door_has_no_bottom_skin(self):
        self.assertEqual(opening_slice(3.0, 0.0, 2.1),
                         {"cut": True, "below": False, "above": True})

    def test_door_taller_than_wall_does_not_remove_outside_wall(self):
        self.assertEqual(opening_slice(1.8, 0.0, 2.1),
                         {"cut": True, "below": False, "above": False})

    def test_window_outside_wall_does_not_cut(self):
        self.assertFalse(opening_slice(1.0, 1.1, 1.2)["cut"])

    def test_sloped_profile_splits_at_head_crossing(self):
        positions = profile_crossings(
            4.0, [0.0, 0.0], [3.0, 2.0],
            [{"s0": 0.5, "s1": 3.5, "sill": 0.0, "height": 2.5}],
        )
        self.assertEqual(positions, [2.0])

    def test_no_unnecessary_crossings_on_level_top(self):
        positions = profile_crossings(
            4.0, [0.0, 0.0], [3.0, 3.0],
            [{"s0": 0.5, "s1": 3.5, "sill": 0.0, "height": 2.5}],
        )
        self.assertEqual(positions, [])


if __name__ == "__main__":
    unittest.main()
