# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable composite build-ups shared by walls, slabs and future roofs.

The library intentionally stores only the physical layer stack, not an element
kind.  A 155 mm build-up can therefore be applied to a slab, wall or future
roof exactly like Bonsai's reusable material layer sets.  Orientation remains
the responsibility of the receiving editor (Exterior→Interior / Bottom→Top).
"""
from __future__ import annotations

import copy
import json

SETTINGS_KEY = "opentrace/composition_library_v1"


def _settings():
    from PySide6.QtCore import QSettings
    return QSettings()


def builtin_compositions() -> dict:
    """Composite stacks already shipped in the OpenTrace element presets.

    They are exposed here as a shared library too, so a useful wall/slab build-up
    does not have to be recreated just because the user is editing another kind
    of element.  Personal compositions with the same display name override the
    bundled copy without modifying the preset catalogue.
    """
    out = {}
    try:
        from .preset_catalog import builtins
        for kind in ("wall", "slab"):
            for item in builtins().get(kind, ()): 
                cfg = item.get("config", {}) if isinstance(item, dict) else {}
                layers = cfg.get("layers") if cfg.get("structure") == "composite" else None
                if isinstance(layers, list) and layers:
                    name = str(item.get("name") or "Composição").strip()
                    if name:
                        out[name] = copy.deepcopy(layers)
    except Exception:
        pass
    return out


def _load_personal_compositions() -> dict:
    try:
        raw = _settings().value(SETTINGS_KEY, "")
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for name, layers in data.items():
            if str(name).strip() and isinstance(layers, list) and layers:
                out[str(name).strip()] = copy.deepcopy(layers)
        return out
    except Exception:
        return {}


def is_personal_composition(name: str) -> bool:
    return str(name or "").strip() in _load_personal_compositions()


def load_compositions() -> dict:
    out = builtin_compositions()
    out.update(_load_personal_compositions())
    return out


def save_compositions(data: dict) -> None:
    clean = {}
    for name, layers in (data or {}).items():
        if str(name).strip() and isinstance(layers, list) and layers:
            clean[str(name).strip()] = copy.deepcopy(layers)
    _settings().setValue(SETTINGS_KEY, json.dumps(clean, ensure_ascii=False))


def put_composition(name: str, layers) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Dê um nome à composição.")
    data = _load_personal_compositions()
    data[name] = copy.deepcopy(list(layers or ()))
    save_compositions(data)
    return name


def remove_composition(name: str) -> None:
    data = _load_personal_compositions()
    data.pop(str(name or "").strip(), None)
    save_compositions(data)
