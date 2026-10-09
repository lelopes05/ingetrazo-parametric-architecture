# SPDX-License-Identifier: GPL-3.0-or-later
"""Real but unregistered IngeTrazo meshes for basic parametric door/window.

The wall owns the cut. This module builds a *separate* leaf/frame/glass Group
and stores a link to the wall's opening; it does not mutate the host, register
UI, or invoke IFC export. Geometry is local to opening-left, wall midplane,
opening-bottom. A future placement command anchors the parent to the wall.
"""
from __future__ import annotations

import copy
import math

from PySide6.QtGui import QVector3D
from core.group import Group
from core.mesh import Mesh

from .door_window_core import normalize_fill, FillError


def _prism(x0, x1, y0, y1, z0, z1, *, pivot=None, angle=0.0):
    """Closed rectangular solid, optionally rotated around a hinge in plan."""
    if not (x1 > x0 and y1 > y0 and z1 > z0):
        raise FillError("Sólido de esquadria com medidas inválidas.")
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def p(x, y, z):
        if pivot is not None:
            xx, yy = x-pivot[0], y-pivot[1]
            x, y = pivot[0]+c*xx-s*yy, pivot[1]+s*xx+c*yy
        return QVector3D(x, y, z)

    corners = [
        p(x0,y0,z0), p(x1,y0,z0), p(x1,y1,z0), p(x0,y1,z0),
        p(x0,y0,z1), p(x1,y0,z1), p(x1,y1,z1), p(x0,y1,z1),
    ]
    mesh = Mesh()
    for loop in ((3,2,1,0), (4,5,6,7), (0,1,5,4),
                 (1,2,6,5), (2,3,7,6), (3,0,4,7)):
        mesh.add_face([corners[i] for i in loop])
    return mesh


def _part(name, *size, **kwargs):
    part = Group(_prism(*size, **kwargs), name=name)
    part.component = False
    return part


def build_fill_parts(raw, *, wall_thickness=0.10):
    """Build one opening-filling object as named parametric geometric parts.

    A door has three frame parts plus one swinging leaf. A window has a
    four-sided frame, optional mullions, and glass units. All geometry is
    real manifold host Mesh data; the fill remains separate from its wall.
    """
    spec = normalize_fill(raw)
    thickness = float(wall_thickness)
    if not math.isfinite(thickness) or thickness <= 0.002:
        raise FillError("Espessura da parede inválida.")
    w, h, f = spec["width"], spec["height"], spec["frame_thickness"]
    depth = max(thickness, f)
    y0, y1 = -depth/2, depth/2
    parts = [
        _part("Marco esquerdo", 0, f, y0, y1, 0, h),
        _part("Marco direito", w-f, w, y0, y1, 0, h),
        _part("Verga do marco", f, w-f, y0, y1, h-f, h),
    ]
    if spec["kind"] == "door":
        leaf = spec["leaf_thickness"]
        if leaf >= thickness:
            raise FillError("A folha deve ser menos espessa que a parede.")
        hinge = f if spec["hinge"] == "left" else w-f
        sign = 1 if spec["hinge"] == "left" else -1
        rotation = sign * spec["swing"] * spec["open_angle"]
        parts.append(_part(
            "Folha de abrir", f, w-f, -leaf/2, leaf/2, 0, h-f,
            pivot=(hinge, 0.0), angle=rotation,
        ))
    else:
        parts.append(_part("Marco inferior", f, w-f, y0, y1, 0, f))
        panels = spec["panes"]
        panel_width = (w-2*f)/panels
        if panel_width <= 2*f:
            raise FillError("Largura insuficiente para a quantidade de folhas.")
        for i in range(1, panels):
            x = f+panel_width*i
            parts.append(_part(f"Montante {i}", x-f/2, x+f/2,
                               y0, y1, f, h-f))
        glass_thickness = min(.006, thickness/3)
        for i in range(panels):
            a = f+panel_width*i + (f/2 if i else 0)
            b = f+panel_width*(i+1) - (f/2 if i+1 < panels else 0)
            parts.append(_part(f"Vidro {i+1}", a, b,
                               -glass_thickness/2, glass_thickness/2, f, h-f))
    return parts


def make_fill_group(raw, *, wall_thickness=0.10):
    """A free, unplaced fill assembly ready for hosted placement.

    No global ID is generated here: the caller chooses persistent identifiers
    before build and stores the same fill ID in the wall opening source_id.
    """
    spec = normalize_fill(raw)
    group = Group(name=spec["name"])
    group.adopt(build_fill_parts(spec, wall_thickness=wall_thickness))
    group.component = False
    group.ext = {
        "arquitetura_parametrica": {
            "schema": 1,
            "kind": spec["kind"],
            "host_id": spec["host_id"],
            "opening_id": spec["opening_id"],
            "source_id": spec["id"],
            "params": copy.deepcopy(spec),
        }
    }
    group.ifc = {"class": "IfcDoor" if spec["kind"] == "door"
                 else "IfcWindow", "name": spec["name"]}
    return group
