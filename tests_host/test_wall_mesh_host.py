# SPDX-License-Identifier: GPL-3.0-or-later
"""Integration regression using IngeTrazo's real Mesh and PySide6 classes.

This module is intentionally separate from pure unit tests. CI adds a clean
IngeTrazo checkout to PYTHONPATH; user-visible runtime is still validated
inside the application by a maintainer, not claimed by this test.
"""
import math
import unittest

from PySide6.QtGui import QVector3D
from OpenTrace_BIM.model import (
    DEFAULTS, FACE_KEY, build_body, build_children, wall_opening_intervals,
)


def wall(openings, **params):
    values = dict(DEFAULTS, openings=openings)
    values.update(params)
    return values


def face_area(mesh, side_name):
    return sum(f.area() for f in mesh.faces if f.attrs.get(FACE_KEY) == side_name)


def nonmanifold_edges(mesh):
    return [edge for edge in mesh.edges if len(edge.faces) != 2]


class WallMeshRuntimeTests(unittest.TestCase):
    def test_rectangular_window_preserves_volume_and_clean_cut(self):
        op = {"id": "window-1", "position": 2, "width": 1,
              "sill": 1, "height": 1}
        p = wall([op], length=4, height=3)
        child = build_body(p)
        self.assertGreater(len(child.mesh.faces), 8)
        self.assertAlmostEqual(face_area(child.mesh, "side"), 2*(4*3-1), places=2)
        self.assertEqual(nonmanifold_edges(child.mesh), [])

    def test_taller_door_keeps_walls_on_both_sides(self):
        op = {"id": "door-1", "position": 2, "width": .9,
              "sill": 0, "height": 2.2}
        p = wall([op], length=4, height=1.8, top_profile=[1.8, 1.8])
        child = build_body(p)
        self.assertGreater(face_area(child.mesh, "side"), 2*(4-.9)*1.8-0.02)
        self.assertAlmostEqual(face_area(child.mesh, "bottom"),
                               .1*(4-.9), places=2)
        self.assertEqual(nonmanifold_edges(child.mesh), [])

    def test_polygon_window_clean_opening_through_both_faces(self):
        op = {"id": "free-window", "kind": "polygon",
              "polygon": [[1, 1], [2, 1], [2, 2], [1, 2]]}
        p = wall([op], length=4)
        child = build_body(p)
        self.assertAlmostEqual(face_area(child.mesh, "side"), 22, places=2)
        self.assertEqual(nonmanifold_edges(child.mesh), [])

    def test_concave_polygon_does_not_fill_inner_notch(self):
        op = {"id": "concave", "kind": "polygon",
              "polygon": [[1, .4], [3, .4], [3, .9], [2, .9],
                          [2, 1.5], [3, 1.5], [3, 2], [1, 2]]}
        child = build_body(wall([op], length=4))
        self.assertGreater(len(child.mesh.faces), 10)
        self.assertEqual(nonmanifold_edges(child.mesh), [])

    def test_curved_path_opening_with_compound_layers(self):
        # Faceted path exercises reference-length offsets, both wall faces,
        # and two independently rebuilt physical material layers.
        path = [QVector3D(0, 0, 0), QVector3D(1, .20, 0),
                QVector3D(2, .25, 0), QVector3D(3, .1, 0),
                QVector3D(4, 0, 0)]
        length = sum((b-a).length() for a,b in zip(path, path[1:]))
        opening = {"id": "curved-poly", "kind": "polygon",
                   "polygon": [[.8, .5], [1.8, .5], [1.8, 2], [.8, 2]]}
        p = wall([opening], length=length)
        mesh = build_body(p, path=path).mesh
        self.assertGreater(len(mesh.faces), 10)
        self.assertEqual(nonmanifold_edges(mesh), [])

    def test_sloping_wall_polygon_clips_to_local_top(self):
        opening = {"id": "top", "kind": "polygon",
                   "polygon": [[1, 0], [2.5, 0], [2.5, 3.5], [1, 3.5]]}
        p = wall([opening], length=4, top_profile=[2.7, 1.6])
        mesh = build_body(p).mesh
        self.assertGreater(len(mesh.faces), 7)
        self.assertEqual(nonmanifold_edges(mesh), [])


if __name__ == "__main__":
    unittest.main()
