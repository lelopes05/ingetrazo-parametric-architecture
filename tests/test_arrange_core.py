# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent XYZ object-arrangement arithmetic tests (no Qt)."""
import unittest

from OpenTrace_BIM.arrange_core import align_offsets, distribute_offsets


def boxes(axis, pairs):
    result = []
    for a,b in pairs:
        box = [(0.0, 1.0), (0.0, 1.0), (0.0, 1.0)]
        box[axis] = (a, b)
        result.append(tuple(box))
    return result


class AlignTests(unittest.TestCase):
    def test_left_edges_align(self):
        self.assertEqual(align_offsets(boxes(0, [(0, 1), (5, 7)]), 0, "min"), [0.0, -5.0])

    def test_centres_align_in_vertical_axis(self):
        self.assertEqual(align_offsets(boxes(2, [(0, 2), (5, 6)]), 2, "center"), [2.0, -2.5])

    def test_maxima_align(self):
        self.assertEqual(align_offsets(boxes(1, [(0, 1), (6, 9)]), 1, "max"), [8.0, 0.0])

    def test_rejects_nonfinite_bounds(self):
        with self.assertRaises(ValueError):
            align_offsets(boxes(0, [(0, 1), (float("nan"), 2)]), 0, "min")


class DistributeTests(unittest.TestCase):
    def test_equal_clear_spaces_with_different_sizes(self):
        result = distribute_offsets(boxes(0, [(0, 1), (1.5, 3.5), (8, 9)]), 0)
        self.assertEqual(result, [0.0, 1.0, 0.0])

    def test_works_regardless_of_selection_order(self):
        result = distribute_offsets(boxes(2, [(8, 9), (0, 1), (1.5, 3.5)]), 2)
        self.assertEqual(result, [0.0, 0.0, 1.0])

    def test_rejects_overlap_when_objects_cannot_fit(self):
        with self.assertRaises(ValueError):
            distribute_offsets(boxes(0, [(0, 4), (2, 8), (5, 9)]), 0)

    def test_requires_three_objects(self):
        with self.assertRaises(ValueError):
            distribute_offsets(boxes(1, [(0, 1), (4, 5)]), 1)


if __name__ == "__main__":
    unittest.main()
