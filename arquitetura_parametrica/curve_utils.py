# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers for generated curved solids.

IngeTrazo represents curves as faceted topology with ``Edge.soft`` marking
technical seams that should not render as hard edges.  These helpers mirror the
core sweep/push-pull behaviour without depending on private tool classes.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

# Same rule used by IngeTrazo's sweep/push-pull pipeline: shallow dihedrals are
# facets of one smooth curved surface; real corners stay hard.
CURVE_FACET_COS = 0.85


def soften_curve_facets(mesh, cos_threshold=CURVE_FACET_COS):
    """Mark shallow two-face seams as soft while preserving silhouettes.

    ``soft`` is intentionally used instead of ``hidden``: the edge disappears
    as a tessellation seam in normal display but IngeTrazo can still derive the
    profile/silhouette of the curved surface.
    """
    changed = 0
    for edge in getattr(mesh, "edges", ()):  # Mesh API is intentionally tiny.
        if getattr(edge, "hidden", False) or getattr(edge, "soft", False):
            continue
        faces = getattr(edge, "faces", ())
        if len(faces) != 2:
            continue
        try:
            n0 = faces[0].normal().normalized()
            n1 = faces[1].normal().normalized()
            dot = QVector3D.dotProduct(n0, n1)
        except Exception:
            continue
        # Curved sweeps can generate very shallow facets whose normals are
        # almost identical. Those are still tessellation seams and should be
        # soft; only genuine profile corners (larger dihedral) stay hard.
        if dot > cos_threshold:
            edge.soft = True
            changed += 1
    return changed
