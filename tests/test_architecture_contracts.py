# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-Python contract tests; no IngeTrazo or Qt installation needed."""
import json
import unittest

from OpenTrace_BIM.architecture_contracts import (
    ContractError, normalize_architectural_view, normalize_hatch_pattern,
    normalize_opening_descriptor,
)


class ViewTests(unittest.TestCase):
    def test_ordinary_3d_cut_does_not_automatically_enable_graphics(self):
        view = normalize_architectural_view({"kind": "3d", "section_uid": "cut1"})
        self.assertEqual(view["representation"], "simple")
        self.assertFalse(view["show_hatches"])
        self.assertFalse(view["show_symbols"])

    def test_saved_plan_is_architectural_without_locking_zoom(self):
        view = normalize_architectural_view({"kind": "plan", "scale": 50, "level_name": "Térreo"})
        self.assertTrue(view["show_hatches"])
        self.assertEqual(view["scale"], 50)
        self.assertNotIn("zoom", view)
        self.assertEqual(json.loads(json.dumps(view))["level_name"], "Térreo")

    def test_section_can_be_simple_and_isometric_can_be_documented(self):
        self.assertFalse(normalize_architectural_view({"kind": "section", "representation": "simple"})["show_hatches"])
        self.assertTrue(normalize_architectural_view({"kind": "axonometric", "representation": "architectural"})["show_hatches"])

    def test_nonfinite_scale_and_cut_rejected(self):
        for item in ({"scale": 0}, {"scale": float("nan")}, {"cut_height": float("inf")}):
            with self.subTest(item=item), self.assertRaises(ContractError):
                normalize_architectural_view(item)


class OpeningTests(unittest.TestCase):
    def test_doorway_can_reach_wall_base(self):
        item = normalize_opening_descriptor({"host": "wall", "shape": "rect", "position": 2, "width": 0.9, "height": 2.1, "sill": 0, "source_id": "door-1"})
        self.assertEqual(item["sill"], 0)
        self.assertEqual(item["source_id"], "door-1")

    def test_free_wall_polygon_preserves_curve_spec(self):
        item = normalize_opening_descriptor({"host": "wall", "shape": "polygon", "polygon": [[0, 0.2], [1, 0.2], [1, 2]], "edges": [{"type": "line"}, {"type": "arc", "bulge": 0.5}, {"type": "line"}]})
        self.assertIsNone(item["source_id"])
        self.assertEqual(item["edges"][1]["bulge"], 0.5)
        self.assertEqual(json.loads(json.dumps(item))["polygon"][2], [1, 2])

    def test_mismatched_edges_rejected(self):
        with self.assertRaises(ContractError):
            normalize_opening_descriptor({"shape": "polygon", "polygon": [[0, 0], [1, 0], [1, 1]], "edges": [{}]})


class HatchTests(unittest.TestCase):
    def test_paper_hatch_is_vector_parameters(self):
        item = normalize_hatch_pattern({"name": "Concreto", "scale_mode": "paper", "lines": [{"angle": 45, "spacing": 1.5}]})
        self.assertEqual(item["lines"][0]["spacing"], 1.5)
        self.assertNotIn("image", item)
        self.assertEqual(json.loads(json.dumps(item))["name"], "Concreto")

    def test_model_spacing(self):
        item = normalize_hatch_pattern({"name": "Blocos", "scale_mode": "model", "lines": [{"angle": 0, "spacing": 0.19}]})
        self.assertEqual(item["scale_mode"], "model")

    def test_bad_spacing_rejected(self):
        with self.assertRaises(ContractError):
            normalize_hatch_pattern({"lines": [{"spacing": 0}]})


if __name__ == "__main__":
    unittest.main()
