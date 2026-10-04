# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only bridge to IngeTrazo's Niveles extension.

IngeTrazo stores one JSON-safe value per extension in ``scene.plugin_data``.
The public ``ExtensionApp.document_data()`` only exposes the current
extension's own entry, but ``ExtensionApp.scene`` is public and the Levels
worked example is persisted under the extension key ``niveles``.

This module deliberately READS that foreign entry only. It never mutates the
Niveles data; additions/edits/deletions continue to be owned by niveles.py.
"""
from __future__ import annotations

LEVELS_PLUGIN_KEY = "niveles"


def available_levels(app):
    """Return validated levels from the installed Niveles extension.

    Returned items are copies with the stable shape::

        [{"name": "Térreo", "z": 0.0}, ...]

    Missing/malformed data simply behaves as no levels.  Sorting by height
    mirrors the Levels extension itself.
    """
    scene = getattr(app, "scene", None)
    data = getattr(scene, "plugin_data", {}) if scene is not None else {}
    if not isinstance(data, dict):
        return []
    raw = data.get(LEVELS_PLUGIN_KEY, {})
    if not isinstance(raw, dict):
        return []

    levels = []
    for lv in raw.get("levels", []):
        if not isinstance(lv, dict):
            continue
        try:
            name = str(lv["name"]).strip()
            z = float(lv["z"])
        except (KeyError, TypeError, ValueError):
            continue
        if name:
            levels.append({"name": name, "z": z})
    levels.sort(key=lambda lv: lv["z"])
    return levels


def level_by_name(app, name):
    """Return one available level by name, or ``None``."""
    if not name:
        return None
    for level in available_levels(app):
        if level["name"] == name:
            return level
    return None


def sync_bound_wall_tops(app):
    """Regenerate walls whose top is intentionally bound to a Níveis level.

    This is derived parametric state, like junction cleanup: changing a level is
    the user's one undoable action, while wall bodies follow that level without
    creating a second history entry.  The stored ``height`` is kept as the
    current geometric cache so old files/readers remain compatible.

    Returns the number of walls whose geometry was refreshed.
    """
    scene = getattr(app, "scene", None)
    if scene is None:
        return 0
    by_name = {lv["name"]: lv for lv in available_levels(app)}
    if not by_name:
        return 0

    # Local imports avoid a module cycle during extension start-up.
    from .commands import EditWall
    from .model import MIN_DIM, WallError, read_wall, wall_record

    changed = 0
    for group in list(getattr(scene, "groups", ())):
        rec = wall_record(group)
        if rec is None or rec.get("top_mode") != "level":
            continue
        name = rec.get("top_level")
        level = by_name.get(name)
        if level is None:
            # Niveles has no stable IDs yet.  If a level was removed/renamed,
            # preserve the wall exactly as it is rather than guessing a target.
            continue
        try:
            values = read_wall(group)
            offset = float(rec.get("top_offset", 0.0))
            desired = float(level["z"]) + offset - float(values["base"])
            if desired < MIN_DIM:
                continue
            if abs(desired - float(values["height"])) <= 1.0e-7:
                continue
            values["height"] = desired
            values["top_mode"] = "level"
            values["top_level"] = name
            values["top_offset"] = offset
            cmd = EditWall(scene, group, values)
            # Deliberately derived, not another history entry. Undoing the
            # level edit causes this function to derive the old wall heights.
            cmd.do(scene)
            changed += 1
        except (WallError, TypeError, ValueError):
            continue
    return changed