# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared composite-layer data for walls and slabs.

Layers are stored in physical order.  For walls that means low-side/exterior
through the core to high-side/interior.  For slabs it means bottom through the
core to top.  Exactly one layer is the core.
"""
from __future__ import annotations

import copy
import math
import uuid

MIN_LAYER = 0.001
MAX_LAYER = 10000.0


# Semantic BIM purpose of a physical layer.  This is independent from
# ``role``: role identifies the one geometric/reference core used by the
# existing wall/slab geometry, while function says what the layer does.
FUNCTION_CHOICES = (
    ("structure", "Estrutura / vedação"),
    ("substrate", "Substrato / base"),
    ("bonding", "Assentamento / colagem"),
    ("insulation", "Isolamento térmico/acústico"),
    ("waterproofing", "Impermeabilização"),
    ("membrane", "Membrana / barreira"),
    ("finish", "Revestimento / acabamento"),
    ("technical", "Camada técnica"),
    ("other", "Outro"),
)
FUNCTION_CODES = {code for code, _label in FUNCTION_CHOICES}
FUNCTION_LABELS = dict(FUNCTION_CHOICES)

# Stable export-friendly category names.  IFC MaterialLayer.Category is free
# text, so these codes can later be mapped directly without changing presets.
FUNCTION_CATEGORIES = {
    "structure": "Structure",
    "substrate": "Substrate",
    "bonding": "Bonding",
    "insulation": "Insulation",
    "waterproofing": "Waterproofing",
    "membrane": "Membrane",
    "finish": "Finish",
    "technical": "Technical",
    "other": "Other",
}


def normalize_function(value, role="finish"):
    code = str(value or "").strip()

    # Compatibility aliases from experimental builds / imported data.
    aliases = {
        "core": "structure",
        "structural": "structure",
        "thermal": "insulation",
        "thermal_air": "insulation",
        "air": "insulation",
        "waterproof": "waterproofing",
        "coating": "finish",
    }
    code = aliases.get(code, code)

    if code in FUNCTION_CODES:
        return code
    return "structure" if role == "core" else "finish"


def function_label(value):
    return FUNCTION_LABELS.get(
        normalize_function(value, "finish"),
        FUNCTION_LABELS["other"],
    )


def function_category(value):
    return FUNCTION_CATEGORIES.get(
        normalize_function(value, "finish"),
        FUNCTION_CATEGORIES["other"],
    )

def _uid():
    return uuid.uuid4().hex[:12]


def core_layer(thickness: float, material_name=None, name="Núcleo",
               function="structure") -> dict:
    return {
        "id": _uid(),
        "name": str(name),
        "role": "core",
        "function": normalize_function(function, "core"),
        "thickness": float(thickness),
        "material_name": material_name or None,
    }


def finish_layer(thickness: float = 0.02, material_name=None, name="Camada",
                 function="finish") -> dict:
    return {
        "id": _uid(),
        "name": str(name),
        "role": "finish",
        "function": normalize_function(function, "finish"),
        "thickness": float(thickness),
        "material_name": material_name or None,
    }


def normalize_layers(raw, core_thickness=0.10, material_name=None) -> list[dict]:
    """Normalize/migrate a physical composite stack.

    Legacy records did not have ``function``.  They remain fully readable:
    the old core migrates to ``structure`` and old non-core layers to
    ``finish``.  New semantic fields therefore do not invalidate existing
    walls, slabs or presets.
    """
    out = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                thickness = float(item.get("thickness", 0.0))
            except (TypeError, ValueError):
                continue
            if (
                not math.isfinite(thickness)
                or thickness < MIN_LAYER
                or thickness > MAX_LAYER
            ):
                continue

            role = "core" if item.get("role") == "core" else "finish"
            material = item.get("material_name")
            name = " ".join(
                str(
                    item.get("name")
                    or ("Núcleo" if role == "core" else "Camada")
                ).split()
            )
            if not name:
                name = "Núcleo" if role == "core" else "Camada"

            out.append({
                "id": str(item.get("id") or _uid()),
                "name": name,
                "role": role,
                "function": normalize_function(item.get("function"), role),
                "thickness": thickness,
                "material_name": (
                    str(material).strip()
                    if material not in (None, "")
                    else None
                ),
            })

    cores = [i for i, layer in enumerate(out) if layer["role"] == "core"]
    if not cores:
        out.insert(
            len(out) // 2,
            core_layer(core_thickness, material_name),
        )
    elif len(cores) > 1:
        keep = cores[0]
        for i, layer in enumerate(out):
            if i != keep and layer["role"] == "core":
                layer["role"] = "finish"

    ci = next(i for i, layer in enumerate(out) if layer["role"] == "core")
    if out[ci].get("material_name") is None and material_name:
        out[ci]["material_name"] = material_name

    return out

def default_composite(core_thickness=0.10, material_name=None) -> list[dict]:
    return [core_layer(core_thickness, material_name)]


def total_thickness(layers) -> float:
    return sum(float(x["thickness"]) for x in layers)


def core_index(layers) -> int:
    for i,x in enumerate(layers):
        if x.get("role")=="core": return i
    return 0


def core_thickness(layers, fallback=0.10) -> float:
    try: return float(layers[core_index(layers)]["thickness"])
    except Exception: return float(fallback)


def clone_layers(layers):
    return copy.deepcopy(list(layers or []))


def bands_about_core(layers, alignment="left"):
    """Return ``[(layer, low, high), ...]`` for a wall cross-section.

    The reference alignment is applied to the *core* layer.  Finish layers
    before the core extend toward the low/exterior side; layers after it extend
    toward the high/interior side.
    """
    layers=normalize_layers(layers)
    ci=core_index(layers); ct=float(layers[ci]["thickness"])
    core_low={"left":0.0,"center":-ct/2.0,"right":-ct}.get(alignment,0.0)
    core_high=core_low+ct
    result=[None]*len(layers)
    result[ci]=(layers[ci],core_low,core_high)
    pos=core_low
    for i in range(ci-1,-1,-1):
        t=float(layers[i]["thickness"]); result[i]=(layers[i],pos-t,pos); pos-=t
    pos=core_high
    for i in range(ci+1,len(layers)):
        t=float(layers[i]["thickness"]); result[i]=(layers[i],pos,pos+t); pos+=t
    return result


def wall_overall_offsets(layers, alignment="left"):
    bands=bands_about_core(layers, alignment)
    return min(x[1] for x in bands), max(x[2] for x in bands)
