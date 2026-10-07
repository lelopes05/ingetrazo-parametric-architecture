# SPDX-License-Identifier: GPL-3.0-or-later
"""Undoable slab creation and parametric edits."""
from __future__ import annotations

import copy
from PySide6.QtGui import QMatrix4x4
from core.history import Command

from .commands import root_edit_allowed
from .materials import stamp_named_material, stamp_structured_materials
from .slab_model import (SlabError, make_slab, read_slab, slab_edge_specs,
                         slab_polygon_world, slab_openings_world)


class CreateSlab(Command):
    def __init__(self, group):
        self.group = group
        self.index = None

    def do(self, scene):
        if self.group in scene.groups:
            raise SlabError("A laje já está no documento.")
        from .bim import ensure_ifc_identity
        ensure_ifc_identity(self.group, "IfcSlab")
        from .slab_model import slab_record
        rec=slab_record(self.group) or {}
        stamp_structured_materials(self.group,scene,rec)
        if self.index is None:
            self.index = len(scene.groups)
        scene.groups.insert(min(self.index, len(scene.groups)), self.group)
        scene.version += 1

    def undo(self, scene):
        if self.group in scene.groups:
            scene.groups.remove(self.group)
        scene.selection.discard(self.group)
        scene.version += 1


class EditSlab(Command):
    def __init__(self, scene, group, values=None, world_polygon=None, edge_specs=None, openings=None):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group):
            raise SlabError("A laje está indisponível ou bloqueada.")
        old_values = read_slab(group)
        polygon = slab_polygon_world(group, reference=True) if world_polygon is None else world_polygon
        specs = slab_edge_specs(group) if edge_specs is None else edge_specs
        ops = slab_openings_world(group, reference=True) if openings is None else openings
        merged = dict(old_values)
        if values:
            merged.update(values)
        fresh = make_slab(polygon, merged, template=group, edge_specs=specs, openings=ops)
        stamp_structured_materials(fresh, scene, merged, clear=True)
        self.group = group
        self.before = (list(group.children), copy.deepcopy(group.ext), QMatrix4x4(group.xform))
        self.after = (list(fresh.children), copy.deepcopy(fresh.ext), QMatrix4x4(fresh.xform))

    def _apply(self, scene, state):
        if self.group not in scene.groups:
            raise SlabError("A laje não está mais neste documento.")
        children, ext, transform = state
        self.group.children = list(children)
        self.group.ext = copy.deepcopy(ext)
        self.group.xform = QMatrix4x4(transform)
        scene.version += 1

    def do(self, scene):
        self._apply(scene, self.after)

    def undo(self, scene):
        self._apply(scene, self.before)
