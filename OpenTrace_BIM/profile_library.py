# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable complex-profile library with folders and built-in catalogues.

Personal profiles stay in QSettings and are available in every project.
Built-in profiles are read-only resources shipped by the plugin. Parametric
objects still embed the actual loops, so reopening a model never depends on the
local favourites/catalogue being present.
"""
from __future__ import annotations

import copy
import json
import uuid
from PySide6.QtCore import QSettings

SETTINGS_KEY = "arquitetura_parametrica/complex_profiles_v1"
SCHEMA_VERSION = 1
DEFAULT_FOLDER = "Meus Perfis"
_BUILTIN_CACHE = None


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
    folder = " / ".join(x.strip() for x in str(raw.get("folder") or DEFAULT_FOLDER).replace("\\","/").split("/") if x.strip()) or DEFAULT_FOLDER
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "name": name,
        "schema_version": SCHEMA_VERSION,
        "loops": out_loops,
        "bounds": {
            "width": float(bounds.get("width", 0.0) or 0.0),
            "height": float(bounds.get("height", 0.0) or 0.0),
        },
        "folder": folder,
        "category": str(raw.get("category") or "profile"),
        "source": (str(raw.get("source")).strip() if raw.get("source") not in (None, "") else None),
        "catalog": (str(raw.get("catalog")).strip() if raw.get("catalog") not in (None, "") else None),
        "code": (str(raw.get("code")).strip() if raw.get("code") not in (None, "") else None),
        "readonly": bool(raw.get("readonly", False)),
        "builtin": bool(raw.get("builtin", False)),
        "metadata": copy.deepcopy(metadata),
    }


def builtin_profiles():
    global _BUILTIN_CACHE
    if _BUILTIN_CACHE is None:
        from .builtin_profiles import builtin_profiles as _builtins
        result=[]
        for raw in _builtins():
            item=_clean_profile(raw)
            if item is not None:
                item["readonly"]=True;item["builtin"]=True
                result.append(item)
        _BUILTIN_CACHE=result
    return copy.deepcopy(_BUILTIN_CACHE)


def load_profiles(include_builtin=True):
    raw = QSettings().value(SETTINGS_KEY, "[]")
    try:
        data = json.loads(str(raw or "[]"))
    except Exception:
        data = []
    out = []
    if include_builtin:
        out.extend(builtin_profiles())
    if isinstance(data, list):
        for item in data:
            clean = _clean_profile(item)
            if clean is not None:
                clean["builtin"]=False;clean["readonly"]=False
                if str(clean.get("id","")).startswith("builtin:"):
                    clean["id"]=uuid.uuid4().hex
                out.append(clean)
    return out


def load_personal_profiles():
    return load_profiles(include_builtin=False)


def save_profiles(profiles):
    clean = []
    for p in profiles or []:
        item = _clean_profile(p)
        if item is not None and not item.get("builtin") and not str(item.get("id","")).startswith("builtin:"):
            item["readonly"]=False;item["builtin"]=False
            clean.append(item)
    QSettings().setValue(SETTINGS_KEY, json.dumps(clean, ensure_ascii=False,
                                                  separators=(",", ":")))
    return clean


def upsert_profile(profile):
    item = _clean_profile(profile)
    if item is None:
        raise ValueError("Perfil inválido.")
    if item.get("builtin") or str(item.get("id","")).startswith("builtin:"):
        item["id"]=uuid.uuid4().hex
        item["name"] += " — personalizado"
    item["builtin"]=False;item["readonly"]=False
    profiles = load_personal_profiles()
    for i, existing in enumerate(profiles):
        if existing["id"] == item["id"]:
            profiles[i] = item
            break
    else:
        profiles.append(item)
    save_profiles(profiles)
    return copy.deepcopy(item)


def delete_profile(profile_id):
    pid=str(profile_id)
    if pid.startswith("builtin:"):
        return load_profiles()
    profiles = [p for p in load_personal_profiles() if p.get("id") != pid]
    save_profiles(profiles)
    return load_profiles()


def duplicate_profile(profile_id):
    for p in load_profiles():
        if p.get("id") == profile_id:
            q = copy.deepcopy(p)
            q["id"] = uuid.uuid4().hex
            q["name"] = f"{p['name']} — cópia"
            q["folder"] = DEFAULT_FOLDER
            q["builtin"] = False; q["readonly"] = False
            q["source"] = q.get("source") or ("Catálogo incluído" if p.get("builtin") else None)
            return upsert_profile(q)
    return None


def profile_by_id(profile_id):
    """Return a detached profile by id, including built-in catalogues."""
    if profile_id in (None, ""):
        return None
    pid = str(profile_id)
    for profile in load_profiles():
        if profile.get("id") == pid:
            return copy.deepcopy(profile)
    return None


def resolve_profile(profile_id=None, embedded=None):
    """Resolve an embedded snapshot first, then fall back to the library."""
    item = _clean_profile(embedded) if isinstance(embedded, dict) else None
    if item is not None:
        if profile_id not in (None, ""):
            item["id"] = str(profile_id)
        return copy.deepcopy(item)
    return profile_by_id(profile_id)
