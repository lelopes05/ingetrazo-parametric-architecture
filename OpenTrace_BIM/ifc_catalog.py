# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline IFC4 catalogue for OpenTrace BIM.

The compact catalogue is generated from IfcOpenShell 0.9.0 schema metadata and
property-set templates.  It is data-only: no IfcOpenShell binary is bundled,
so OpenTrace keeps working on whatever Python version IngeTrazo ships.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).with_name("ifc_schema")

_FALLBACK_PREDEFINED = {
    "IfcWall": ("STANDARD", "SOLIDWALL", "PARTITIONING", "SHEAR", "PARAPET", "PLUMBINGWALL", "MOVABLE", "ELEMENTEDWALL", "USERDEFINED", "NOTDEFINED"),
    "IfcSlab": ("FLOOR", "ROOF", "LANDING", "BASESLAB", "USERDEFINED", "NOTDEFINED"),
    "IfcBeam": ("BEAM", "JOIST", "LINTEL", "SPANDREL", "T_BEAM", "HOLLOWCORE", "USERDEFINED", "NOTDEFINED"),
    "IfcColumn": ("COLUMN", "PILASTER", "USERDEFINED", "NOTDEFINED"),
    "IfcOpeningElement": ("OPENING", "RECESS", "USERDEFINED", "NOTDEFINED"),
    "IfcRoof": ("FLAT_ROOF", "SHED_ROOF", "GABLE_ROOF", "HIP_ROOF", "HIPPED_GABLE_ROOF", "GAMBREL_ROOF", "MANSARD_ROOF", "BARREL_ROOF", "RAINBOW_ROOF", "BUTTERFLY_ROOF", "PAVILION_ROOF", "DOME_ROOF", "FREEFORM", "USERDEFINED", "NOTDEFINED"),
    "IfcSpace": ("SPACE", "INTERNAL", "EXTERNAL", "GFA", "PARKING", "USERDEFINED", "NOTDEFINED"),
    "IfcDoor": ("DOOR", "GATE", "TRAPDOOR", "USERDEFINED", "NOTDEFINED"),
    "IfcWindow": ("WINDOW", "SKYLIGHT", "LIGHTDOME", "USERDEFINED", "NOTDEFINED"),
    "IfcStair": ("STRAIGHT_RUN_STAIR", "TWO_STRAIGHT_RUN_STAIR", "QUARTER_WINDING_STAIR", "QUARTER_TURN_STAIR", "HALF_WINDING_STAIR", "HALF_TURN_STAIR", "TWO_QUARTER_WINDING_STAIR", "TWO_QUARTER_TURN_STAIR", "THREE_QUARTER_WINDING_STAIR", "THREE_QUARTER_TURN_STAIR", "SPIRAL_STAIR", "DOUBLE_RETURN_STAIR", "CURVED_RUN_STAIR", "TWO_CURVED_RUN_STAIR", "USERDEFINED", "NOTDEFINED"),
    "IfcRamp": ("STRAIGHT_RUN_RAMP", "TWO_STRAIGHT_RUN_RAMP", "QUARTER_TURN_RAMP", "TWO_QUARTER_TURN_RAMP", "HALF_TURN_RAMP", "SPIRAL_RAMP", "USERDEFINED", "NOTDEFINED"),
    "IfcRailing": ("HANDRAIL", "GUARDRAIL", "BALUSTRADE", "USERDEFINED", "NOTDEFINED"),
}

ENTITY_LABELS = {
    "IfcWall": "Parede", "IfcSlab": "Laje", "IfcBeam": "Viga", "IfcColumn": "Pilar",
    "IfcOpeningElement": "Abertura", "IfcRoof": "Cobertura", "IfcSpace": "Espaço",
    "IfcZone": "Zona", "IfcDoor": "Porta", "IfcWindow": "Janela", "IfcStair": "Escada",
    "IfcRamp": "Rampa", "IfcRailing": "Guarda-corpo", "IfcBuildingElementProxy": "Objeto BIM",
}

STATUS_VALUES = ("NEW", "EXISTING", "DEMOLISH", "TEMPORARY")

@lru_cache(maxsize=1)
def _entities():
    try:
        return json.loads((_DATA / "ifc4_entities.json").read_text(encoding="utf-8"))
    except Exception:
        return {}

@lru_cache(maxsize=1)
def _templates():
    try:
        return json.loads((_DATA / "ifc4_pset_templates.json").read_text(encoding="utf-8"))
    except Exception:
        return {}

@lru_cache(maxsize=1)
def _domains():
    try:
        return json.loads((_DATA / "ifc4_property_sets_site_domains.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def entity_info(ifc_class: str) -> dict:
    return dict(_entities().get(str(ifc_class), {}) or {})


def entity_description(ifc_class: str) -> str:
    return str(entity_info(ifc_class).get("description") or "")


def predefined_types(ifc_class):
    info = entity_info(str(ifc_class))
    values = info.get("predefined_types") if isinstance(info, dict) else None
    if isinstance(values, dict) and values:
        ordered = list(values)
        # Keep the two escape values at the end, matching authoring UIs.
        normal = [x for x in ordered if x not in ("USERDEFINED", "NOTDEFINED")]
        return tuple(normal + [x for x in ("USERDEFINED", "NOTDEFINED") if x in ordered])
    return _FALLBACK_PREDEFINED.get(str(ifc_class), ("USERDEFINED", "NOTDEFINED"))


def _applies(expr: str, ifc_class: str) -> bool:
    """Conservative match for IFC template ApplicableEntity expressions."""
    expr = str(expr or "")
    cls = str(ifc_class or "")
    if not expr or not cls:
        return False
    # IFC4 templates use forms such as IfcWall, IfcWall/USERDEFINED and
    # comma-separated alternatives.  Type templates often say IfcWallType.
    for part in expr.replace(";", ",").split(","):
        base = part.strip().split("/")[0].strip()
        if base in (cls, cls + "Type"):
            return True
        # A few templates target a broad superclass.  Cover the architectural
        # families we author without pretending to implement full inheritance.
        if base == "IfcBuildingElement" and cls in {
            "IfcWall", "IfcSlab", "IfcBeam", "IfcColumn", "IfcRoof", "IfcDoor",
            "IfcWindow", "IfcStair", "IfcRamp", "IfcRailing", "IfcBuildingElementProxy",
        }:
            return True
        if base == "IfcSpatialElement" and cls in {"IfcSpace", "IfcZone"}:
            return True
    return False


def property_set_templates(ifc_class: str | None = None, *, quantities: bool | None = None) -> dict:
    out = {}
    for name, data in _templates().items():
        is_qto = str(name).startswith("Qto_")
        if quantities is True and not is_qto:
            continue
        if quantities is False and is_qto:
            continue
        if ifc_class and not _applies(data.get("applicable_entity", ""), ifc_class):
            continue
        item = dict(data)
        item["domain"] = _domains().get(str(name).lower(), "")
        out[name] = item
    return out


def pset_names(ifc_class: str, *, include_qto: bool = False) -> tuple[str, ...]:
    data = property_set_templates(ifc_class, quantities=None if include_qto else False)
    return tuple(sorted(data, key=lambda x: (not x.endswith("Common"), x.lower())))


def property_template(pset_name: str, prop_name: str) -> dict:
    pset = _templates().get(str(pset_name), {})
    for item in pset.get("properties", ()) or ():
        if item.get("name") == prop_name:
            return dict(item)
    return {}


def common_pset(ifc_class):
    candidate = "Pset_" + str(ifc_class).removeprefix("Ifc") + "Common"
    return candidate if candidate in _templates() else {
        "IfcWall": "Pset_WallCommon", "IfcSlab": "Pset_SlabCommon",
        "IfcBeam": "Pset_BeamCommon", "IfcColumn": "Pset_ColumnCommon",
        "IfcRoof": "Pset_RoofCommon", "IfcDoor": "Pset_DoorCommon",
        "IfcWindow": "Pset_WindowCommon", "IfcRailing": "Pset_RailingCommon",
        "IfcRamp": "Pset_RampCommon", "IfcStair": "Pset_StairCommon",
        "IfcSpace": "Pset_SpaceCommon",
    }.get(str(ifc_class))


def catalogue_stats() -> dict:
    t = _templates()
    return {
        "entities": len(_entities()),
        "templates": len(t),
        "psets": sum(1 for n in t if n.startswith("Pset_")),
        "qtos": sum(1 for n in t if n.startswith("Qto_")),
    }
