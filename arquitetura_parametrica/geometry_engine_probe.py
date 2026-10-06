# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated probe: IngeTrazo's native solid boolean engine vs OpenTrace walls.

This module is intentionally NOT imported by the plugin. It exists only to test
whether core.solids (currently backed by manifold3d in IngeTrazo) can cut
real OpenTrace straight and curved wall bodies robustly before that approach is
considered for hosted doors/windows.

Run from IngeTrazo's Python console:

    from arquitetura_parametrica.geometry_engine_probe import run_probe
    print(run_probe())

No scene objects are created or modified. core.solids.run is called directly
and only its returned result groups are inspected.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.group import Group, world_mesh
from core.mesh import Mesh
from core.solids import SUBTRACT, run as run_solid_op, solid_volume

from .model import DEFAULTS, make_arc_wall, make_wall_segment


def _box(name: str, xmin: float, xmax: float, ymin: float, ymax: float,
         zmin: float, zmax: float) -> Group:
    """Closed axis-aligned cutter box."""
    p000 = QVector3D(xmin, ymin, zmin)
    p100 = QVector3D(xmax, ymin, zmin)
    p110 = QVector3D(xmax, ymax, zmin)
    p010 = QVector3D(xmin, ymax, zmin)
    p001 = QVector3D(xmin, ymin, zmax)
    p101 = QVector3D(xmax, ymin, zmax)
    p111 = QVector3D(xmax, ymax, zmax)
    p011 = QVector3D(xmin, ymax, zmax)

    mesh = Mesh()
    # Winding is outward; core.solids also normalizes orientation when converting
    # the mesh to manifold3d.
    for loop in (
        (p000, p010, p110, p100),  # bottom
        (p001, p101, p111, p011),  # top
        (p000, p100, p101, p001),  # -Y
        (p100, p110, p111, p101),  # +X
        (p110, p010, p011, p111),  # +Y
        (p010, p000, p001, p011),  # -X
    ):
        mesh.add_face(list(loop))
    group = Group(mesh, name=name)
    group.component = False
    return group


def _metrics(group: Group) -> dict:
    mesh = world_mesh(group)
    vol = solid_volume(group)
    return {
        "solid": vol is not None,
        "volume_m3": None if vol is None else round(float(vol), 9),
        "faces": len(mesh.faces),
        "edges": len(mesh.edges),
        "soft_edges": sum(1 for e in mesh.edges if getattr(e, "soft", False)),
    }


def _cut(target: Group, cutter: Group) -> dict:
    before = _metrics(target)
    cutter_stats = _metrics(cutter)
    removed, created = run_solid_op(SUBTRACT, [cutter, target])
    if len(created) != 1:
        raise RuntimeError(f"Subtract returned {len(created)} result groups.")
    result = created[0]
    after = _metrics(result)
    return {
        "ok": bool(before["solid"] and cutter_stats["solid"] and after["solid"]),
        "target_before": before,
        "cutter": cutter_stats,
        "result": after,
        "removed_count": len(removed),
        "created_count": len(created),
    }


def _wall_values() -> dict:
    values = dict(DEFAULTS)
    values.update({
        "thickness": 0.20,
        "height": 3.00,
        "base": 0.00,
        "alignment": "center",
        "openings": [],
    })
    return values


def probe_straight() -> dict:
    """Cut a 0.90 x 1.20 m through-opening in an actual OpenTrace straight wall."""
    wall = make_wall_segment(
        QVector3D(0.0, 0.0, 0.0),
        QVector3D(4.0, 0.0, 0.0),
        _wall_values(),
    )
    cutter = _box(
        "Probe cutter straight",
        1.55, 2.45,   # 0.90 m clear width
        -1.00, 1.00,  # guaranteed to cross the whole wall thickness
        0.90, 2.10,   # 1.20 m high, sill 0.90 m
    )
    return _cut(wall, cutter)


def probe_curved() -> dict:
    """Cut through the apex of an actual sampled OpenTrace circular wall."""
    wall = make_arc_wall(
        QVector3D(0.0, 0.0, 0.0),
        QVector3D(4.0, 0.0, 0.0),
        1.00,  # positive sagitta; apex is around (2, 1)
        _wall_values(),
    )
    cutter = _box(
        "Probe cutter curved",
        1.55, 2.45,
        -0.50, 1.75,  # crosses both curved wall faces at the apex
        0.90, 2.10,
    )
    return _cut(wall, cutter)


def run_probe() -> dict:
    """Run both cases and return a compact diagnostic instead of touching the scene."""
    report = {
        "engine": "core.solids / manifold3d",
        "straight": None,
        "curved": None,
    }
    for label, fn in (("straight", probe_straight), ("curved", probe_curved)):
        try:
            report[label] = fn()
        except Exception as exc:  # probe should report failure, not kill the console
            report[label] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
    report["ok"] = bool(
        report["straight"].get("ok") and report["curved"].get("ok")
    )
    return report
