# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure polygon opening regression tests, independent of PySide6/IngeTrazo."""
import unittest

from OpenTrace_BIM.wall_polygon import (
    clip_to_wall, contains, cut_stations, normalize_polygon, scan_edges,
    insert_vertex, move_edge, move_vertex, delete_vertex,
)


class WallPolygonTests(unittest.TestCase):
    def test_free_rectangular_cut(self):
        pts = normalize_polygon([[1, 0], [2, 0], [2, 2.1], [1, 2.1]], 4)
        self.assertEqual(len(scan_edges(pts, 1.5)), 2)
        self.assertTrue(contains(pts, 1.5, 1.0))
        self.assertFalse(contains(pts, 0.5, 1.0))

    def test_concave_polygon_has_two_separate_voids_in_a_strip(self):
        pts = normalize_polygon([[1, 0.4], [3, 0.4], [3, 0.9], [2, 0.9],
                                 [2, 1.5], [3, 1.5], [3, 2.0], [1, 2.0]], 4)
        self.assertEqual(len(scan_edges(pts, 2.5)), 4)
        self.assertTrue(contains(pts, 2.5, 0.7))
        self.assertFalse(contains(pts, 2.5, 1.2))
        self.assertTrue(contains(pts, 2.5, 1.7))

    def test_self_intersection_rejected(self):
        with self.assertRaises(ValueError):
            normalize_polygon([[1, 0], [3, 2], [1, 2], [3, 0]], 4)

    def test_end_margin_rejected(self):
        with self.assertRaises(ValueError):
            normalize_polygon([[0, 0], [2, 0], [1, 2]], 4)

    def test_non_finite_rejected(self):
        with self.assertRaises(ValueError):
            normalize_polygon([[1, 0], [2, float("nan")], [1.5, 2]], 4)

    def test_profile_head_crossing(self):
        points = [[1, 1.5], [3, 2.5], [3, 3.5], [1, 3.5]]
        stations = cut_stations(points, 4, [0, 0], [3, 2])
        self.assertTrue(any(1 < x < 3 for x in stations))

    def test_clip_tall_opening_to_wall(self):
        ends = clip_to_wall([1, 2], [3, 4], 4, [0, 0], [3, 3])
        self.assertIsNotNone(ends)
        self.assertAlmostEqual(ends[1][1], 3)

    def test_outside_opening_edge_has_no_reveal(self):
        self.assertIsNone(clip_to_wall([1, 4], [2, 4], 4, [0, 0], [3, 3]))

    def test_insert_and_delete_vertex_round_trip(self):
        rect = [[1, 0.3], [3, 0.3], [3, 2], [1, 2]]
        expanded = insert_vertex(rect, 0, [2, 0.9], 5)
        self.assertEqual(len(expanded), 5)
        self.assertAlmostEqual(expanded[1][1], 0.3)
        self.assertEqual(delete_vertex(expanded, 1, 5), rect)

    def test_vertex_edit_preserves_valid_simple_polygon(self):
        rect = [[1, 0.3], [3, 0.3], [3, 2], [1, 2]]
        new = move_vertex(rect, 2, [2.8, 2.2], 5)
        self.assertEqual(new[2], [2.8, 2.2])
        self.assertEqual(len(new), 4)

    def test_edge_stretch_moves_both_endpoints_perpendicular(self):
        rect = [[1, 0.3], [3, 0.3], [3, 2], [1, 2]]
        new = move_edge(rect, 0, [0, 0.2], 5)
        self.assertAlmostEqual(new[0][1], 0.5)
        self.assertAlmostEqual(new[1][1], 0.5)
        self.assertEqual(new[2:], rect[2:])

    def test_reject_collapse_and_removal_below_three(self):
        tri = [[1, 0.3], [3, 0.3], [2, 2]]
        with self.assertRaises(ValueError):
            delete_vertex(tri, 0, 5)
        with self.assertRaises(ValueError):
            insert_vertex(tri, 0, [1, 0.3], 5)
        with self.assertRaises(ValueError):
            move_vertex(tri, 2, [2, 0.3], 5)

    def test_door_floor_edge_is_coplanar(self):
        ends = clip_to_wall([1, 0], [2, 0], 4, [0, 0], [3, 3])
        self.assertEqual(ends, ((1.0, 0.0), (2.0, 0.0)))


if __name__ == "__main__":
    unittest.main()
