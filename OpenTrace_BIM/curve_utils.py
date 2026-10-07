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


def wrap_soft_surface_textures(mesh):
    """Carry one texture continuously across connected soft facets.

    A curved OpenTrace wall is intentionally faceted in the host mesh and its
    shallow seams are marked ``soft``.  A plain planar projection restarts on
    every facet, which makes bricks/tiles visibly rotate or jump around a curve.
    IngeTrazo already exposes the correct hinge-transport routine in
    ``core.texture.continuous_maps``; use it per semantic face family so the
    texture follows the curve while top/side/reveal materials remain separate.
    """
    try:
        import copy
        from core.texture import continuous_maps, flattened_texture
    except Exception:
        return 0
    faces = list(getattr(mesh, "faces", ()) or ())
    # Keep cap/top/bottom/side families independent.  Different generators use
    # their own semantic attribute names; the old helper only looked for
    # ``pa_face`` and therefore collapsed wall/slab/beam families into one
    # generic bucket.  The hinge walk only crosses soft edges, but preserving
    # the semantic split prevents unrelated surfaces/material mappings from
    # ever participating in the same transport pass.
    semantic_keys = ("ap_wall_side", "ap_slab_side", "ap_beam_face",
                     "ap_column_face", "pa_face")
    buckets = {}
    for face in faces:
        attrs = getattr(face, "attrs", None) or {}
        tex = attrs.get("texture")
        if not isinstance(tex, dict) or not tex.get("path"):
            continue
        family = next((attrs[k] for k in semantic_keys if k in attrs), "surface")
        # Texture identity is part of the family too: two adjoining faces can
        # share a semantic role while intentionally carrying different paint.
        texture_id = (tex.get("path"), attrs.get("mat"))
        buckets.setdefault((family, texture_id), []).append(face)
    changed = 0
    for family in buckets.values():
        pending = {id(f): f for f in family}
        while pending:
            seed = next(iter(pending.values()))
            tex = copy.deepcopy((getattr(seed, "attrs", None) or {}).get("texture") or {})
            try:
                tex = flattened_texture(tex, seed.normal())
                mapped = continuous_maps(mesh, family, seed, tex)
            except Exception:
                mapped = {}
            if not mapped:
                pending.pop(id(seed), None)
                continue
            for face in family:
                nt = mapped.get(id(face))
                if nt is None:
                    continue
                face.attrs["texture"] = nt
                pending.pop(id(face), None)
                changed += 1
    return changed
