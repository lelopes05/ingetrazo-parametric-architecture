# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-neutral BIM metadata for OpenTrace parametric and imported elements.

OpenTrace owns geometry and interaction.  This module owns stable IFC identity,
reusable BIM semantics and project-level relationships.  It deliberately has no
hard dependency on Bonsai or a platform-specific IfcOpenShell build.
"""
from __future__ import annotations

import copy
import math
import uuid

DOC_SCHEMA = 5

ENGINE_BY_CLASS = {
    "IfcWall": "OpenTrace.Wall", "IfcSlab": "OpenTrace.Slab",
    "IfcBeam": "OpenTrace.Beam", "IfcColumn": "OpenTrace.Column",
    "IfcRoof": "OpenTrace.Roof", "IfcSpace": "OpenTrace.Space",
    "IfcDoor": "OpenTrace.Door", "IfcWindow": "OpenTrace.Window",
    "IfcStair": "OpenTrace.Stair", "IfcRamp": "OpenTrace.Ramp",
    "IfcRailing": "OpenTrace.Railing", "IfcBuildingElementProxy": "OpenTrace.Membrane",
}
KIND_TO_CLASS = {
    "wall": "IfcWall", "slab": "IfcSlab", "beam": "IfcBeam", "column": "IfcColumn",
    "roof": "IfcRoof", "space": "IfcSpace", "door": "IfcDoor", "window": "IfcWindow",
    "stair": "IfcStair", "ramp": "IfcRamp", "railing": "IfcRailing",
    "membrane": "IfcBuildingElementProxy", "proxy": "IfcBuildingElementProxy",
}
CLASS_TO_KIND = {v: k for k, v in KIND_TO_CLASS.items()}
CLASS_TO_KIND["IfcWallStandardCase"] = "wall"
CLASS_TO_KIND.update({"IfcPlate": "proxy", "IfcMember": "proxy", "IfcFooting": "proxy"})
DEFAULT_PREDEFINED = {
    "IfcWall": "SOLIDWALL", "IfcSlab": "FLOOR", "IfcBeam": "BEAM",
    "IfcColumn": "COLUMN", "IfcRoof": "NOTDEFINED", "IfcSpace": "NOTDEFINED",
    "IfcDoor": "DOOR", "IfcWindow": "WINDOW", "IfcStair": "NOTDEFINED",
    "IfcRamp": "NOTDEFINED", "IfcRailing": "NOTDEFINED",
    "IfcBuildingElementProxy": "USERDEFINED",
}
_GUID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def _compress_uuid(value: uuid.UUID) -> str:
    h = value.hex
    nums = [int(h[0:2], 16)] + [int(h[i:i + 6], 16) for i in range(2, 32, 6)]
    def enc(number, width):
        out = ["0"] * width
        for i in range(width - 1, -1, -1):
            out[i] = _GUID_CHARS[number % 64]; number //= 64
        return "".join(out)
    return enc(nums[0], 2) + "".join(enc(n, 4) for n in nums[1:])


def new_ifc_guid() -> str:
    return _compress_uuid(uuid.uuid4())


def deterministic_ifc_guid(namespace: str, key: str) -> str:
    ns = uuid.uuid5(uuid.NAMESPACE_URL, "opentrace://" + str(namespace or "OpenTrace"))
    return _compress_uuid(uuid.uuid5(ns, str(key)))


def default_document_data():
    return {
        "schema_version": DOC_SCHEMA,
        "project": {
            "name": "Projeto OpenTrace", "site": "Terreno", "building": "Edifício",
            "author": "", "organization": "", "description": "",
        },
        "spatial_ids": {
            "project": new_ifc_guid(), "site": new_ifc_guid(), "building": new_ifc_guid(),
            "storeys": {}, "zones": {},
        },
        "export": {
            "schema": "IFC4", "profile": "bonsai", "include_property_sets": True,
            "include_material_layers": True, "include_opening_relations": False,
            "include_quantities": True, "include_styles": True,
            "include_parametric_roundtrip": True, "use_representation_maps": True,
        },
        "georeference": {
            "crs_name": "", "epsg": "", "description": "", "geodetic_datum": "",
            "vertical_datum": "", "map_projection": "", "map_zone": "",
            "eastings": 0.0, "northings": 0.0, "orthogonal_height": 0.0,
            "x_axis_abscissa": 1.0, "x_axis_ordinate": 0.0, "scale": 1.0,
        },
        # Project relations. Element membership is stored by stable IFC GlobalId.
        "zones": [], "systems": [], "groups": [],
        # Document-local reusable definitions. The personal cross-document library
        # is handled by bim_library.py, but these travel with the .igz.
        "libraries": {"types": {}, "classifications": {}, "material_styles": {}},
        "links": [],
    }


def _deep_merge_known(base, raw):
    """Merge compatible user data while preserving future extension keys."""
    if not isinstance(raw, dict):
        return copy.deepcopy(base)
    out = copy.deepcopy(base)
    for key, value in raw.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge_known(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def normalize_document_data(raw):
    out = _deep_merge_known(default_document_data(), raw if isinstance(raw, dict) else {})
    out["schema_version"] = DOC_SCHEMA
    # Keep only known profile ids; old files otherwise migrate losslessly.
    profile = str(out.get("export", {}).get("profile") or "bonsai").lower()
    if profile not in ("opentrace", "bonsai", "archicad", "revit"):
        profile = "bonsai"
    out["export"]["profile"] = profile
    for key in ("include_property_sets", "include_material_layers", "include_opening_relations",
                "include_quantities", "include_styles", "include_parametric_roundtrip",
                "use_representation_maps"):
        out["export"][key] = bool(out["export"].get(key, True))
    spatial = out.setdefault("spatial_ids", {})
    for key in ("project", "site", "building"):
        if not isinstance(spatial.get(key), str) or len(spatial.get(key, "")) != 22:
            spatial[key] = new_ifc_guid()
    for key in ("storeys", "zones"):
        if not isinstance(spatial.get(key), dict):
            spatial[key] = {}
    for collection in ("zones", "systems", "groups", "links"):
        if not isinstance(out.get(collection), list):
            out[collection] = []
    if not isinstance(out.get("libraries"), dict):
        out["libraries"] = {"types": {}, "classifications": {}, "material_styles": {}}
    for key in ("types", "classifications", "material_styles"):
        if not isinstance(out["libraries"].get(key), dict): out["libraries"][key] = {}
    geo = out.setdefault("georeference", {})
    for key in ("eastings", "northings", "orthogonal_height", "x_axis_abscissa", "x_axis_ordinate", "scale"):
        try: geo[key] = float(geo.get(key, default_document_data()["georeference"][key]))
        except Exception: geo[key] = default_document_data()["georeference"][key]
    return out


def ensure_spatial_ids(data, storey_names=(), zone_names=()):
    data = normalize_document_data(data)
    spatial = data.setdefault("spatial_ids", {})
    for name in storey_names or ():
        name = str(name or "").strip()
        if name and (not isinstance(spatial["storeys"].get(name), str) or len(spatial["storeys"].get(name, "")) != 22):
            spatial["storeys"][name] = new_ifc_guid()
    for name in zone_names or ():
        name = str(name or "").strip()
        if name and (not isinstance(spatial["zones"].get(name), str) or len(spatial["zones"].get(name, "")) != 22):
            spatial["zones"][name] = new_ifc_guid()
    return data


def load_document_data(app):
    try: return normalize_document_data(app.document_data(default=None))
    except Exception: return default_document_data()


def save_document_data(app, data):
    value = normalize_document_data(data)
    app.set_document_data(copy.deepcopy(value))
    return value


def _record(group):
    ext = getattr(group, "ext", None)
    if not isinstance(ext, dict): return None
    rec = ext.get("arquitetura_parametrica")
    return rec if isinstance(rec, dict) else None


def element_kind(group):
    rec = _record(group)
    kind = str((rec or {}).get("kind") or "").strip().lower()
    if kind in KIND_TO_CLASS: return kind
    meta = getattr(group, "ifc", None)
    if isinstance(meta, dict):
        cls = str(meta.get("class") or "")
        return CLASS_TO_KIND.get(cls)
    return None


def is_bim_group(group) -> bool:
    if element_kind(group): return True
    meta = getattr(group, "ifc", None)
    return isinstance(meta, dict) and str(meta.get("class") or "").startswith("Ifc")


def ifc_identity_data(group, ifc_class=None, *, name=None):
    """Return complete IFC metadata for *group* without mutating the document."""
    kind = element_kind(group)
    existing = getattr(group, "ifc", None)
    current = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    cls = str(ifc_class or current.get("class") or KIND_TO_CLASS.get(kind) or "IfcBuildingElementProxy")
    current.setdefault("class", cls)
    current.setdefault("name", str(name or getattr(group, "name", None) or cls))
    current.setdefault("global_id", new_ifc_guid())
    current.setdefault("predefined_type", DEFAULT_PREDEFINED.get(cls, "NOTDEFINED"))
    current.setdefault("engine", ENGINE_BY_CLASS.get(cls, "OpenTrace.Parametric" if _record(group) else "IFC.Generic"))
    if not current.get("type_name"): current["type_name"] = suggested_type_name(group, cls)
    current.setdefault("property_sets", {})
    current.setdefault("classifications", [])
    current.setdefault("systems", [])
    current.setdefault("groups", [])
    return current


def ensure_ifc_identity(group, ifc_class=None, *, name=None):
    """Ensure identity on geometry creation/import paths.

    UI editors should prefer :func:`set_ifc_metadata` so changes participate in
    IngeTrazo undo/redo instead of mutating ``group.ifc`` behind history.
    """
    current = ifc_identity_data(group, ifc_class, name=name)
    group.ifc = current
    return current


class SetIfcMetadata:
    """Undoable replacement of one group's IFC metadata."""
    def __init__(self, group, metadata):
        self.group = group
        self.new = copy.deepcopy(metadata) if isinstance(metadata, dict) else None
        self.old = copy.deepcopy(getattr(group, "ifc", None))

    def do(self, scene):
        self.group.ifc = copy.deepcopy(self.new)
        scene.version += 1

    def undo(self, scene):
        self.group.ifc = copy.deepcopy(self.old)
        scene.version += 1


def set_ifc_metadata(app, group, metadata):
    """Commit IFC metadata through native history and notify the viewport."""
    app.viewport.history.execute(SetIfcMetadata(group, metadata))
    error = getattr(app.viewport.history, "last_error", None)
    if error:
        raise RuntimeError(str(error))
    app.viewport.notify_scene_changed()
    return copy.deepcopy(metadata)


def suggested_type_name(group, ifc_class=None):
    rec = _record(group) or {}
    cls = str(ifc_class or KIND_TO_CLASS.get(rec.get("kind")) or "IfcBuildingElementProxy")
    human = {
        "IfcWall": "Parede", "IfcSlab": "Laje", "IfcBeam": "Viga", "IfcColumn": "Pilar",
        "IfcRoof": "Cobertura", "IfcSpace": "Espaço", "IfcDoor": "Porta", "IfcWindow": "Janela",
        "IfcStair": "Escada", "IfcRamp": "Rampa", "IfcRailing": "Guarda-corpo",
        "IfcBuildingElementProxy": "Membrana",
    }.get(cls, cls)
    if rec.get("structure") == "composite" and rec.get("layers"):
        total = sum(float(x.get("thickness", 0.0)) for x in rec.get("layers", []) if isinstance(x, dict))
        if total > 0: return f"{human} composta {round(total * 1000):d} mm"
    for key in ("thickness", "width", "diameter"):
        try: value = float(rec.get(key))
        except (TypeError, ValueError): continue
        if math.isfinite(value) and value > 0: return f"{human} {round(value * 1000):d} mm"
    return f"{human} OpenTrace"


def _identity_migration_plan(scene):
    """Return BIM identity replacements without touching the live document."""
    plan = []
    for group in list(getattr(scene, "groups", ()) or ()):
        if not is_bim_group(group):
            continue
        old_ifc = copy.deepcopy(getattr(group, "ifc", None))
        old_ext = copy.deepcopy(getattr(group, "ext", None))
        new_ifc = ifc_identity_data(group)
        new_ext = copy.deepcopy(old_ext)
        ext_changed = False
        if isinstance(new_ext, dict):
            rec = new_ext.get("arquitetura_parametrica")
            if isinstance(rec, dict):
                raw_openings = rec.get("openings")
                if isinstance(raw_openings, list):
                    for item in raw_openings:
                        if not isinstance(item, dict):
                            continue
                        if not item.get("ifc_global_id"):
                            item["ifc_global_id"] = new_ifc_guid()
                            ext_changed = True
                        fill = item.get("fill")
                        if isinstance(fill, dict) and not fill.get("global_id"):
                            fill["global_id"] = new_ifc_guid()
                            ext_changed = True
        if old_ifc != new_ifc or ext_changed:
            plan.append((group, old_ifc, old_ext, new_ifc, new_ext))
    return plan


class PrepareIfcIdentities:
    """Undoable migration of element/opening IFC identities."""
    def __init__(self, plan):
        self.plan = list(plan)

    def _apply(self, scene, use_new):
        for group, old_ifc, old_ext, new_ifc, new_ext in self.plan:
            group.ifc = copy.deepcopy(new_ifc if use_new else old_ifc)
            group.ext = copy.deepcopy(new_ext if use_new else old_ext)
        if self.plan:
            scene.version += 1

    def do(self, scene):
        self._apply(scene, True)

    def undo(self, scene):
        self._apply(scene, False)


def prepare_scene_identities(app):
    """Prepare stable IFC IDs through the host history layer."""
    plan = _identity_migration_plan(app.scene)
    if not plan:
        return 0
    app.viewport.history.execute(PrepareIfcIdentities(plan))
    error = getattr(app.viewport.history, "last_error", None)
    if error:
        raise RuntimeError(str(error))
    app.viewport.notify_scene_changed()
    return len(plan)


def migrate_scene_identities(scene):
    """Compatibility helper for non-UI callers; prefer prepare_scene_identities."""
    plan = _identity_migration_plan(scene)
    for group, _old_ifc, _old_ext, new_ifc, new_ext in plan:
        group.ifc = copy.deepcopy(new_ifc)
        group.ext = copy.deepcopy(new_ext)
    return len(plan)


def scan_scene(scene):
    counts = {k: 0 for k in KIND_TO_CLASS}
    composite = openings = imported = linked = 0
    for group in list(getattr(scene, "groups", ()) or ()):
        ext = getattr(group, "ext", None)
        imported_meta = ext.get("opentrace_ifc_import") if isinstance(ext, dict) else None
        if isinstance(imported_meta, dict):
            imported += 1
            if imported_meta.get("linked"): linked += 1
        kind = element_kind(group)
        if kind: counts[kind] = counts.get(kind, 0) + 1
        rec = _record(group) or {}
        if rec.get("structure") == "composite": composite += 1
        if isinstance(rec.get("openings"), list): openings += len(rec["openings"])
    total = sum(counts.values())
    return {"total": total, "counts": counts, "composite": composite, "openings": openings,
            "imported": imported, "linked": linked}


def record_for(group):
    rec = copy.deepcopy(_record(group) or {})
    if rec: return rec
    meta = getattr(group, "ifc", None)
    cls = str(meta.get("class") or "IfcBuildingElementProxy") if isinstance(meta, dict) else "IfcBuildingElementProxy"
    return {"kind": CLASS_TO_KIND.get(cls, "proxy"), "schema": 0, "structure": "simple",
            "material_name": (meta or {}).get("material_name") if isinstance(meta, dict) else None}
