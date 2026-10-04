# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable complex-profile library stored in the user's IngeTrazo settings.

Profiles are user favourites, not document state: once saved they are available
in every project.  Future profile-by-path elements should embed the geometry they
use in group.ext, while keeping the library id as provenance only; that way a
model never depends on another machine's favourites.
"""
from __future__ import annotations

import copy
import json
import uuid
from PySide6.QtCore import QSettings

SETTINGS_KEY = "arquitetura_parametrica/complex_profiles_v1"
SCHEMA_VERSION = 1


def _clean_profile(raw):
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "Perfil").strip() or "Perfil"
    loops = raw.get("loops")
    if not isinstance(loops, list) or not loops:
        return None
    out_loops = []
    for loop in loops:
        if not isinstance(loop, dict):
            continue
        pts = loop.get("points")
        flags = loop.get("edges")
        if not isinstance(pts, list) or len(pts) < 3:
            continue
        clean_pts = []
        ok = True
        for p in pts:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                ok = False; break
            try:
                clean_pts.append([float(p[0]), float(p[1])])
            except (TypeError, ValueError):
                ok = False; break
        if not ok:
            continue
        if not isinstance(flags, list) or len(flags) != len(clean_pts):
            flags = [{} for _ in clean_pts]
        clean_flags = []
        for f in flags:
            f = f if isinstance(f, dict) else {}
            clean_flags.append({
                "curve": int(f["curve"]) if f.get("curve") is not None else None,
                "soft": bool(f.get("soft", False)),
            })
        out_loops.append({
            "points": clean_pts,
            "edges": clean_flags,
            "hole": bool(loop.get("hole", False)),
        })
    if not out_loops:
        return None
    bounds = raw.get("bounds") if isinstance(raw.get("bounds"), dict) else {}
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "name": name,
        "schema_version": SCHEMA_VERSION,
        "loops": out_loops,
        "bounds": {
            "width": float(bounds.get("width", 0.0) or 0.0),
            "height": float(bounds.get("height", 0.0) or 0.0),
        },
    }


def load_profiles():
    raw = QSettings().value(SETTINGS_KEY, "[]")
    try:
        data = json.loads(str(raw or "[]"))
    except Exception:
        data = []
    out = []
    if isinstance(data, list):
        for item in data:
            clean = _clean_profile(item)
            if clean is not None:
                out.append(clean)
    return out


def save_profiles(profiles):
    clean = []
    for p in profiles or []:
        item = _clean_profile(p)
        if item is not None:
            clean.append(item)
    QSettings().setValue(SETTINGS_KEY, json.dumps(clean, ensure_ascii=False,
                                                  separators=(",", ":")))
    return clean


def upsert_profile(profile):
    item = _clean_profile(profile)
    if item is None:
        raise ValueError("Perfil inválido.")
    profiles = load_profiles()
    for i, existing in enumerate(profiles):
        if existing["id"] == item["id"]:
            profiles[i] = item
            break
    else:
        profiles.append(item)
    save_profiles(profiles)
    return copy.deepcopy(item)


def delete_profile(profile_id):
    profiles = [p for p in load_profiles() if p.get("id") != profile_id]
    save_profiles(profiles)
    return profiles


def duplicate_profile(profile_id):
    for p in load_profiles():
        if p.get("id") == profile_id:
            q = copy.deepcopy(p)
            q["id"] = uuid.uuid4().hex
            q["name"] = f"{p['name']} — cópia"
            return upsert_profile(q)
    return None


def profile_by_id(profile_id):
    """Return a detached favourite profile by id, or ``None``."""
    if profile_id in (None, ""):
        return None
    pid = str(profile_id)
    for profile in load_profiles():
        if profile.get("id") == pid:
            return copy.deepcopy(profile)
    return None


def resolve_profile(profile_id=None, embedded=None):
    """Resolve an embedded snapshot first, then fall back to user favourites.

    Parametric objects embed the actual loops so reopening an .igz never
    depends on the favourite library existing on that machine.
    """
    item = _clean_profile(embedded) if isinstance(embedded, dict) else None
    if item is not None:
        if profile_id not in (None, ""):
            item["id"] = str(profile_id)
        return copy.deepcopy(item)
    return profile_by_id(profile_id)