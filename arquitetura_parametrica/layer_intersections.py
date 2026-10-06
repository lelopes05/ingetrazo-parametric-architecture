# SPDX-License-Identifier: GPL-3.0-or-later
"""Bridge Parametric Architecture to the optional Layer Combinations plugin."""
from __future__ import annotations

_window = None


def configure(app):
    global _window
    _window = getattr(app, "window", None)


def layer_name(entity):
    try:
        from core.layers import layer_of
        value = layer_of(entity)
    except Exception:
        value = getattr(entity, "layer", None)
    if value is None:
        return "Layer 0"
    if hasattr(value, "name"):
        value = value.name
    text = str(value).strip()
    return text or "Layer 0"


def intersection_group(entity):
    service = getattr(_window, "_layer_combinations_service", None) if _window is not None else None
    if service is None:
        return 1
    try:
        return max(0, int(service.intersection_group(layer_name(entity))))
    except Exception:
        return 1


def can_intersect(a, b):
    """Return whether two parametric entities may create automatic junctions.

    Without Layer Combinations the legacy behavior stays unchanged.  With the
    plugin loaded, only equal non-zero intersection groups interact.
    """
    service = getattr(_window, "_layer_combinations_service", None) if _window is not None else None
    if service is None:
        return True
    try:
        return bool(service.can_intersect(layer_name(a), layer_name(b)))
    except Exception:
        return True
