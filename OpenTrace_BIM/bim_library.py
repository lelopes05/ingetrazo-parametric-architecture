# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable BIM definitions shared across OpenTrace documents."""
from __future__ import annotations
import copy, json

SETTINGS_KEY = "opentrace/bim_library_v1"


def _defaults():
    return {"types": {}, "classifications": {}, "material_styles": {}}


def load_personal_library():
    out = _defaults()
    try:
        from PySide6.QtCore import QSettings
        raw = QSettings().value(SETTINGS_KEY, "")
        data = json.loads(raw) if raw else {}
        if isinstance(data, dict):
            for k in out:
                if isinstance(data.get(k), dict): out[k] = copy.deepcopy(data[k])
    except Exception:
        pass
    return out


def save_personal_library(data):
    lib = _defaults()
    if isinstance(data, dict):
        for k in lib:
            if isinstance(data.get(k), dict): lib[k] = copy.deepcopy(data[k])
    try:
        from PySide6.QtCore import QSettings
        QSettings().setValue(SETTINGS_KEY, json.dumps(lib, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        pass
    return lib


def merged_library(document_data):
    personal = load_personal_library()
    local = document_data.get("libraries", {}) if isinstance(document_data, dict) else {}
    out = _defaults()
    for k in out:
        out[k].update(personal.get(k, {}))
        if isinstance(local, dict) and isinstance(local.get(k), dict): out[k].update(copy.deepcopy(local[k]))
    return out


def type_definition(group):
    from .bim import ifc_identity_data, record_for
    meta = ifc_identity_data(group)
    rec = record_for(group)
    return {
        "ifc_class": meta.get("class"), "type_name": meta.get("type_name"),
        "predefined_type": meta.get("predefined_type", "NOTDEFINED"),
        "common": copy.deepcopy(meta.get("common", {})),
        "property_sets": copy.deepcopy(meta.get("property_sets", {})),
        "classifications": copy.deepcopy(meta.get("classifications", [])),
        "classification_system": meta.get("classification_system", ""),
        "classification_code": meta.get("classification_code", ""),
        "material_name": rec.get("material_name") or meta.get("material_name"),
        "structure": rec.get("structure", "simple"),
        "layers": copy.deepcopy(rec.get("layers", [])),
        "material_constituents": copy.deepcopy(meta.get("material_constituents", [])),
        "material_style": copy.deepcopy(meta.get("material_style", {})),
    }


def put_type(document_data, name, definition, *, personal=False):
    name = str(name or "").strip()
    if not name: raise ValueError("Dê um nome ao tipo BIM.")
    if personal:
        lib = load_personal_library(); lib["types"][name] = copy.deepcopy(definition); save_personal_library(lib)
    else:
        document_data.setdefault("libraries", {}).setdefault("types", {})[name] = copy.deepcopy(definition)
    return name


def type_metadata(group, definition):
    """Return semantic type metadata without mutating the selected object."""
    from .bim import ifc_identity_data
    meta = ifc_identity_data(group)
    d = definition if isinstance(definition, dict) else {}
    for key in ("ifc_class", "type_name", "predefined_type"):
        if key in d and d[key] not in (None, ""):
            meta["class" if key == "ifc_class" else key] = copy.deepcopy(d[key])
    for key in ("common", "property_sets", "classifications", "material_constituents", "material_style"):
        if key in d: meta[key] = copy.deepcopy(d[key])
    for key in ("classification_system", "classification_code", "material_name"):
        if key in d: meta[key] = copy.deepcopy(d[key])
    return meta


def apply_type_metadata(group, definition):
    """Compatibility wrapper for non-UI creation/import paths."""
    meta = type_metadata(group, definition)
    group.ifc = meta
    return meta


def put_classification(document_data, name, system, code, *, location="", description="", personal=False):
    name = str(name or code or "").strip()
    item = {"system": str(system or "").strip(), "code": str(code or "").strip(),
            "location": str(location or "").strip(), "description": str(description or "").strip()}
    if not name or not item["system"] or not item["code"]: raise ValueError("Classificação precisa de sistema e código.")
    target = load_personal_library() if personal else document_data.setdefault("libraries", {})
    target.setdefault("classifications", {})[name] = item
    if personal: save_personal_library(target)
    return name


def put_material_style(document_data, name, style, *, personal=False):
    name = str(name or "").strip()
    if not name: raise ValueError("Dê um nome ao estilo de material.")
    target = load_personal_library() if personal else document_data.setdefault("libraries", {})
    target.setdefault("material_styles", {})[name] = copy.deepcopy(style or {})
    if personal: save_personal_library(target)
    return name
