# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-independent parameter contracts for doors and windows (stage 02).

A fill is a SEPARATE parametric object, identified by a stable id and linked
to a wall opening by opening_id/source_id. No Qt, scene writes, meshes, IFC
exports, UI hooks or release side effects occur when this module is imported.

All distances are metres. The station is the location of the chosen anchor
(left, centre, right) on the wall reference line; changing width keeps this
anchor fixed. One swing switch flips the *direction*, not the host opening.
"""
from __future__ import annotations

import math
import copy

SCHEMA = 1
ANCHORS = ("left", "center", "right")
KINDS = ("door", "window")
HINGES = ("left", "right")


class FillError(ValueError):
    pass


def _number(value, label, *, positive=False, minimum=None):
    if isinstance(value, bool):
        raise FillError(f"{label}: número inválido.")
    try:
        result = float(value.replace(",", ".").strip() if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FillError(f"{label}: número inválido.") from exc
    if not math.isfinite(result):
        raise FillError(f"{label}: número não finito.")
    if positive and result <= 0:
        raise FillError(f"{label}: medida deve ser positiva.")
    if minimum is not None and result < minimum:
        raise FillError(f"{label}: medida abaixo do mínimo.")
    return result


def normalize_fill(raw):
    """Validate a door/window object while preserving stable references."""
    if not isinstance(raw, dict):
        raise FillError("Porta ou janela precisa ser um registro.")
    kind = str(raw.get("kind", "")).lower()
    if kind not in KINDS:
        raise FillError("Tipo de esquadria inválido.")
    uid = str(raw.get("id") or "").strip()
    host_id = str(raw.get("host_id") or "").strip()
    opening_id = str(raw.get("opening_id") or "").strip()
    if not uid or not host_id or not opening_id:
        raise FillError("Objeto, parede e abertura precisam de IDs persistentes.")
    anchor = str(raw.get("anchor", "left")).lower()
    if anchor not in ANCHORS:
        raise FillError("Âncora inválida.")
    defaults = {"door": (0.90, 2.10, 0.0), "window": (1.20, 1.20, 0.90)}
    dw, dh, ds = defaults[kind]
    width = _number(raw.get("width", dw), "Largura", positive=True)
    height = _number(raw.get("height", dh), "Altura", positive=True)
    sill = _number(raw.get("sill", ds), "Peitoril", minimum=0.0)
    position = _number(raw.get("position"), "Posição")
    if width < 0.05 or height < 0.05 or width > 100 or height > 100:
        raise FillError("Dimensões fora dos limites de projeto.")
    frame = _number(raw.get("frame_thickness", 0.04), "Espessura do marco", positive=True)
    if frame >= min(width, height)/2:
        raise FillError("Marco muito grande para o vão.")
    out = {
        "schema": SCHEMA,
        "id": uid, "kind": kind,
        "host_id": host_id, "opening_id": opening_id,
        "anchor": anchor, "position": position,
        "width": width, "height": height, "sill": sill,
        "frame_thickness": frame,
        "name": str(raw.get("name") or ("Porta" if kind == "door" else "Janela")),
    }
    if kind == "door":
        hinge = str(raw.get("hinge", "left")).lower()
        if hinge not in HINGES:
            raise FillError("Lado da dobradiça inválido.")
        swing = raw.get("swing", 1)
        if swing not in (-1, 1) or isinstance(swing, bool):
            raise FillError("Giro precisa ser +1 ou -1.")
        out.update({
            "hinge": hinge, "swing": swing,
            "leaf_thickness": _number(raw.get("leaf_thickness", 0.035),
                                      "Espessura da folha", positive=True),
            "open_angle": _number(raw.get("open_angle", 90), "Ângulo de abertura"),
        })
        if not 0 <= out["open_angle"] <= 180:
            raise FillError("Ângulo de abertura fora do intervalo de 0 a 180°.")
    else:
        out["panes"] = int(raw.get("panes", 1))
        if not 1 <= out["panes"] <= 16:
            raise FillError("Quantidade de folhas inválida.")
    for key in ("ifc_global_id", "type_name", "material_name"):
        if raw.get(key):
            out[key] = str(raw[key])
    return out


def station_span(raw):
    """Return the left and right opening stations for the selected anchor."""
    spec = normalize_fill(raw)
    shift = {"left": 0.0, "center": 0.5, "right": 1.0}[spec["anchor"]]
    start = spec["position"]-shift*spec["width"]
    return start, start+spec["width"]


def center_station(raw):
    a, b = station_span(raw)
    return (a+b)/2


def reverse_swing(raw):
    """Invert door clockwise/counterclockwise in exactly one operation."""
    spec = normalize_fill(raw)
    if spec["kind"] != "door":
        raise FillError("Somente portas de abrir possuem inversão de giro.")
    spec["swing"] *= -1
    return spec


def opening_request(raw, *, opening_guid=None):
    """Host opening request, with fill linked to independent object by source_id.

    Does NOT create a 3D element and does NOT call the host or IFC writer.
    Geometry generation belongs to the wall; this record tells it which void
    corresponds to the parametric fill.
    """
    spec = normalize_fill(raw)
    return {
        "id": spec["opening_id"], "kind": "rect",
        "position": center_station(spec),
        "width": spec["width"], "sill": spec["sill"],
        "height": spec["height"], "source_id": spec["id"],
        "ifc_global_id": opening_guid,
        "fill": {
            "class": "IfcDoor" if spec["kind"] == "door" else "IfcWindow",
            "global_id": spec.get("ifc_global_id"),
            "name": spec["name"],
            "overall_width": spec["width"],
            "overall_height": spec["height"],
        },
    }


def hotspots(raw):
    """Architectural edit permissions tied to the physical corners.

    Each point can change width; ONLY the top three can edit height and
    ONLY bottom three can edit position (via the radial choice UI).
    """
    spec = normalize_fill(raw)
    left, right = station_span(spec)
    z0 = spec["sill"]
    z1 = z0 + spec["height"]
    out = []
    for row, z in (("bottom", z0), ("top", z1)):
        for at, x in (("left", left), ("center", (left+right)/2), ("right", right)):
            out.append({
                "id": f"{row}-{at}",
                "station": x,
                "elevation": z,
                "controls": ("width", "position") if row == "bottom"
                            else ("width", "height"),
            })
    return out


def door_leaf_plan(raw):
    """Simple exact 2D leaf at the requested opening angle, not a scene mesh.

    Returns hinge, leaf tip and sampled arc (in local station/depth plane).
    +1/-1 switches swing direction. In plan, closed leaf lies on the wall.
    """
    spec = normalize_fill(raw)
    if spec["kind"] != "door":
        raise FillError("Apenas portas possuem folha de giro.")
    left, right = station_span(spec)
    hinge = left if spec["hinge"] == "left" else right
    direction = 1 if spec["hinge"] == "left" else -1
    angle = math.radians(spec["open_angle"])*spec["swing"]
    def at(radians):
        return [hinge + direction*spec["width"]*math.cos(radians),
                direction*spec["width"]*math.sin(radians)]
    arc = [at(angle*i/16) for i in range(17)]
    return {"hinge": [hinge, 0.0], "tip": at(angle), "arc": arc}


def window_mullions(raw):
    """Model-plane station/elevation dividers for a simple fixed-glazing window."""
    spec = normalize_fill(raw)
    if spec["kind"] != "window":
        raise FillError("Somente janelas possuem montantes de vidro.")
    left, right = station_span(spec)
    return [
        {"station": left+(right-left)*i/spec["panes"],
         "bottom": spec["sill"], "top": spec["sill"]+spec["height"]}
        for i in range(1, spec["panes"])
    ]


def reanchor_fill(raw, anchor):
    """Select left/center/right anchor without physically moving the fill.

    Only the representation of the station changes, never the two endpoints.
    """
    spec = normalize_fill(raw)
    target = str(anchor).lower()
    if target not in ANCHORS:
        raise FillError("Âncora inválida.")
    left, right = station_span(spec)
    spec["anchor"] = target
    spec["position"] = {"left": left, "center": (left+right)/2,
                        "right": right}[target]
    return normalize_fill(spec)


def edit_from_hotspot(raw, point_id, action, value):
    """Apply a radial-handle operation, preserving all stable IDs.

    Width/height values are full dimensions in metres; position is the NEW
    station of the selected lower hotspot in the wall's reference frame.
    Permission checks live here, not just in the presentation layer.
    """
    spec = normalize_fill(raw)
    hit = next((p for p in hotspots(spec) if p["id"] == point_id), None)
    if hit is None or action not in hit["controls"]:
        raise FillError("Operação não permitida neste hotspot.")
    measure = _number(value, str(action))
    if action == "position":
        spec["position"] += measure-hit["station"]
    elif action == "width":
        spec["width"] = measure
    elif action == "height":
        spec["height"] = measure
    return normalize_fill(spec)
