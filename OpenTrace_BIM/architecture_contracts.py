# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON-safe foundation contracts for architecture views, openings and hatches.

This module has NO Qt/host imports or side effects. All dimensions are metres
unless a field ends in _mm. Values only describe future features; they do not
activate geometry generation, scene cuts, exports or user-interface controls.
"""
from __future__ import annotations

import copy
import math

CONTRACT_VERSION = 1
VIEW_KINDS = frozenset(("3d", "plan", "section", "elevation", "axonometric"))
REPRESENTATION_MODES = frozenset(("simple", "architectural"))
HATCH_SCALES = frozenset(("paper", "model"))
OPENING_SHAPES = frozenset(("rect", "polygon"))


class ContractError(ValueError):
    """A malformed future design record; not a host/runtime error."""


def _finite(raw, name, *, minimum=None, positive=False):
    if isinstance(raw, bool):
        raise ContractError(f"{name}: valor numérico inválido.")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError(f"{name}: valor numérico inválido.") from exc
    if not math.isfinite(value) or (positive and value <= 0) or (minimum is not None and value < minimum):
        raise ContractError(f"{name}: valor fora do intervalo permitido.")
    return value


def _optional_text(raw):
    return str(raw).strip() if raw is not None and str(raw).strip() else None


def normalize_architectural_view(raw):
    """Normalize a saved-architecture-view descriptor, never a live camera.

    Scale is the paper denominator (50 means 1:50), not locked viewport zoom.
    Free 3D, even with a temporary cut, remains simple unless user opts in.
    """
    if not isinstance(raw, dict):
        raise ContractError("A vista precisa ser um registro.")
    kind = str(raw.get("kind", "3d")).strip().lower()
    if kind not in VIEW_KINDS:
        raise ContractError("Tipo de vista desconhecido.")
    default_mode = "architectural" if kind in ("plan", "section", "elevation") else "simple"
    representation = str(raw.get("representation", default_mode)).strip().lower()
    if representation not in REPRESENTATION_MODES:
        raise ContractError("Modo de representação desconhecido.")
    scale = _finite(raw.get("scale", 50), "Escala", positive=True)
    cut_height = raw.get("cut_height", None)
    if cut_height is not None:
        cut_height = _finite(cut_height, "Altura de corte")
    return {
        "schema": CONTRACT_VERSION,
        "id": _optional_text(raw.get("id")),
        "kind": kind,
        "name": str(raw.get("name") or "").strip(),
        "representation": representation,
        "scale": scale,
        "level_name": _optional_text(raw.get("level_name")),
        "section_uid": _optional_text(raw.get("section_uid")),
        "saved_view_name": _optional_text(raw.get("saved_view_name")),
        "cut_height": cut_height,
        "show_hatches": representation == "architectural" and bool(raw.get("show_hatches", True)),
        "show_symbols": representation == "architectural" and bool(raw.get("show_symbols", True)),
        "show_annotations": representation == "architectural" and bool(raw.get("show_annotations", True)),
    }


def normalize_opening_descriptor(raw):
    """Describe openings without changing host geometry.

    Wall polygon points are local (station, elevation) in metres; slab points
    are local (x, y). Geometry, intersection and topology are future work.
    A door/window fills a hosted cut through source_id; a free cut omits it.
    Existing rectangular walls use position/width/sill/height unchanged.
    """
    if not isinstance(raw, dict):
        raise ContractError("A abertura precisa ser um registro.")
    host = str(raw.get("host", "wall")).strip().lower()
    if host not in ("wall", "slab"):
        raise ContractError("Hospedeiro da abertura desconhecido.")
    shape = str(raw.get("shape", "rect" if host == "wall" else "polygon")).strip().lower()
    if shape not in OPENING_SHAPES:
        raise ContractError("Formato de abertura desconhecido.")
    if host == "slab" and shape == "rect":
        raise ContractError("Retângulos de laje devem ser fornecidos como polígono.")
    out = {
        "schema": CONTRACT_VERSION,
        "id": _optional_text(raw.get("id")),
        "host": host,
        "shape": shape,
        "source_id": _optional_text(raw.get("source_id")),
        "ifc_global_id": _optional_text(raw.get("ifc_global_id")),
    }
    if shape == "rect":
        out.update({
            "position": _finite(raw.get("position"), "Posição"),
            "width": _finite(raw.get("width"), "Largura", positive=True),
            "sill": _finite(raw.get("sill", 0), "Peitoril", minimum=0),
            "height": _finite(raw.get("height"), "Altura", positive=True),
        })
    else:
        pts = raw.get("polygon")
        if not isinstance(pts, (list, tuple)) or len(pts) < 3:
            raise ContractError("Abertura poligonal exige ao menos três vértices.")
        points = []
        for p in pts:
            if not isinstance(p, (tuple, list)) or len(p) < 2:
                raise ContractError("Vértice de abertura inválido.")
            points.append([_finite(p[0], "Coordenada 1"), _finite(p[1], "Coordenada 2")])
        edges = raw.get("edges")
        if edges is None:
            edges = [{"type": "line"} for _ in points]
        if not isinstance(edges, (list, tuple)) or len(edges) != len(points):
            raise ContractError("A quantidade de arestas deve igualar os vértices.")
        if not all(isinstance(e, dict) and e.get("type", "line") in ("line", "arc") for e in edges):
            raise ContractError("Aresta deve ser linha ou arco.")
        out["polygon"] = points
        out["edges"] = copy.deepcopy(list(edges))
    return out


def normalize_hatch_pattern(raw):
    """Validate parametric vector lines; never store a bitmap hatch.

    Paper spacing is mm on printed sheet, model spacing is metres in model.
    The future renderer will clip these line families to true cut contours.
    """
    if not isinstance(raw, dict):
        raise ContractError("Trama precisa ser um registro.")
    scale_mode = str(raw.get("scale_mode", "paper")).lower()
    if scale_mode not in HATCH_SCALES:
        raise ContractError("Escala da trama deve ser 'paper' ou 'model'.")
    lines = raw.get("lines", [])
    if not isinstance(lines, (list, tuple)) or not lines:
        raise ContractError("Trama exige ao menos uma família de linhas.")
    out_lines = []
    for spec in lines:
        if not isinstance(spec, dict):
            raise ContractError("Família de linhas inválida.")
        out_lines.append({
            "angle": _finite(spec.get("angle", 45), "Ângulo"),
            "spacing": _finite(spec.get("spacing"), "Espaçamento", positive=True),
            "offset": _finite(spec.get("offset", 0), "Deslocamento"),
            "pen_mm": _finite(spec.get("pen_mm", 0.18), "Espessura de pena", positive=True),
        })
    return {
        "schema": CONTRACT_VERSION,
        "id": _optional_text(raw.get("id")),
        "name": str(raw.get("name") or "").strip(),
        "scale_mode": scale_mode,
        "color": str(raw.get("color", "#333333")),
        "lines": out_lines,
    }
