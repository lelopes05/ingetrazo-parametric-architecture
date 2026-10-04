# SPDX-License-Identifier: GPL-3.0-or-later
"""Undoable column creation and parametric edits."""
from __future__ import annotations
import copy
from PySide6.QtGui import QMatrix4x4
from core.history import Command
from .commands import root_edit_allowed
from .materials import stamp_named_material
from .column_model import ColumnError, make_column, read_column, insertion_world

class CreateColumn(Command):
    def __init__(self,group): self.group=group; self.index=None
    def do(self,scene):
        if self.group in scene.groups: raise ColumnError("O pilar já está no documento.")
        from .column_model import column_record
        rec=column_record(self.group) or {};name=rec.get("material_name")
        if name:stamp_named_material(self.group,scene,name)
        if self.index is None:self.index=len(scene.groups)
        scene.groups.insert(min(self.index,len(scene.groups)),self.group); scene.version+=1
    def undo(self,scene):
        if self.group in scene.groups: scene.groups.remove(self.group)
        scene.selection.discard(self.group); scene.version+=1

class EditColumn(Command):
    def __init__(self,scene,group,values):
        root_edit_allowed(scene)
        if group not in scene.groups or not scene.entity_selectable(group): raise ColumnError("O pilar está indisponível ou bloqueado.")
        old=read_column(group); merged=dict(old); merged.update(values or {})
        point=insertion_world(group); fresh=make_column(point,merged,template=group)
        if merged.get("material_name") != old.get("material_name"):
            stamp_named_material(fresh,scene,merged.get("material_name"),clear=True)
        self.group=group
        self.before=(list(group.children),copy.deepcopy(group.ext),QMatrix4x4(group.xform))
        self.after=(list(fresh.children),copy.deepcopy(fresh.ext),QMatrix4x4(fresh.xform))
    def _apply(self,scene,state):
        children,ext,xform=state; self.group.children=list(children); self.group.ext=copy.deepcopy(ext); self.group.xform=QMatrix4x4(xform); scene.version+=1
    def do(self,scene): self._apply(scene,self.after)
    def undo(self,scene): self._apply(scene,self.before)