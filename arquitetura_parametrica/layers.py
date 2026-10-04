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


def _uid():
    return uuid.uuid4().hex[:12]


def core_layer(thickness: float, material_name=None, name="Núcleo") -> dict:
    return {
        "id": _uid(), "name": str(name), "role": "core",
        "thickness": float(thickness), "material_name": material_name or None,
    }


def finish_layer(thickness: float = 0.02, material_name=None, name="Camada") -> dict:
    return {
        "id": _uid(), "name": str(name), "role": "finish",
        "thickness": float(thickness), "material_name": material_name or None,
    }


def normalize_layers(raw, core_thickness=0.10, material_name=None) -> list[dict]:
    out=[]
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                t=float(item.get("thickness", 0.0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(t) or t < MIN_LAYER or t > MAX_LAYER:
                continue
            role="core" if item.get("role")=="core" else "finish"
            mat=item.get("material_name")
            out.append({
                "id": str(item.get("id") or _uid()),
                "name": str(item.get("name") or ("Núcleo" if role=="core" else "Camada")),
                "role": role,
                "thickness": t,
                "material_name": str(mat).strip() if mat not in (None, "") else None,
            })
    cores=[i for i,x in enumerate(out) if x["role"]=="core"]
    if not cores:
        out.insert(len(out)//2, core_layer(core_thickness, material_name))
    elif len(cores)>1:
        keep=cores[0]
        for i,x in enumerate(out):
            if i!=keep and x["role"]=="core": x["role"]="finish"
    # Core inherits object material only when it has no explicit material.
    ci=next(i for i,x in enumerate(out) if x["role"]=="core")
    if out[ci].get("material_name") is None and material_name:
        out[ci]["material_name"]=material_name
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