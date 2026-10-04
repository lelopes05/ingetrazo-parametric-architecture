# SPDX-License-Identifier: GPL-3.0-or-later
"""Named IngeTrazo material integration for parametric architecture objects.

IngeTrazo 0.5.7 has a native named-material registry (``scene.materials``), but
its BIM module does not yet export IfcMaterial associations.  These helpers use
that native registry without modifying the host program.  Faces are stamped
with ``attrs['mat']`` plus the material's baked render attributes, so native
material edits and takeoffs keep working.
"""
from __future__ import annotations

import copy

_MATERIAL_KEYS = ("mat", "color", "texture", "opacity")


def material_names(scene):
    registry = getattr(scene, "materials", None) or {}
    return sorted(str(name) for name in registry.keys())


def material_face_attrs(scene, name):
    if not name:
        return None
    mat = (getattr(scene, "materials", None) or {}).get(name)
    if mat is None:
        return None
    if hasattr(mat, "face_attrs"):
        return dict(mat.face_attrs())
    return {"mat": str(name)}


def infer_material_name(group):
    """Return a stable named material already worn by an object, if any."""
    ext = getattr(group, "ext", None) or {}
    for rec in ext.values() if isinstance(ext, dict) else ():
        if isinstance(rec, dict) and rec.get("material_name"):
            return str(rec["material_name"])
    for child in getattr(group, "children", ()) or ():
        for face in getattr(getattr(child, "mesh", None), "faces", ()) or ():
            name = (getattr(face, "attrs", None) or {}).get("mat")
            if name:
                return str(name)
    return None


def stamp_named_material(group, scene, name, *, clear=False):
    """Stamp *name* on every generated face.

    We intentionally leave the container paint alone: the parametric material
    is face-owned, which matches IngeTrazo's material takeoff/update machinery
    and avoids overriding a separately painted group container.
    """
    attrs = material_face_attrs(scene, name)
    if attrs is None and not clear:
        return
    targets=[]
    children=getattr(group,"children",None) or ()
    if children: targets.extend(children)
    elif getattr(group,"mesh",None) is not None: targets.append(group)
    for child in targets:
        for face in getattr(getattr(child,"mesh",None),"faces",()) or ():
            fattrs=face.attrs
            for key in _MATERIAL_KEYS:fattrs.pop(key,None)
            if attrs is not None:fattrs.update(copy.deepcopy(attrs))


def stamp_structured_materials(group, scene, values, *, clear=False):
    """Apply per-layer materials to composite children, or one material to simple objects."""
    layers = values.get("layers") if isinstance(values, dict) else None
    structure = values.get("structure", "simple") if isinstance(values, dict) else "simple"
    if structure == "composite" and layers:
        children=list(getattr(group,"children",()) or ())
        for child, layer in zip(children, layers):
            stamp_named_material(child, scene, layer.get("material_name"), clear=True)
        return
    stamp_named_material(group, scene, values.get("material_name") if isinstance(values,dict) else None, clear=clear)