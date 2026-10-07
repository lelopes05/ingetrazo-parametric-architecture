# SPDX-License-Identifier: GPL-3.0-or-later
"""Named IngeTrazo material integration for parametric architecture objects.

The parametric tools expose the *whole* native IngeTrazo material library,
not only materials already stamped into the current scene.  Library recipes
are loaded lazily from the host resources and registered into ``scene.materials``
only when a parametric object actually uses them.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

_MATERIAL_KEYS = ("mat", "color", "texture", "opacity")


def _unique_name(catalog, base, suffix=None):
    """Return a readable unique material name for duplicate library labels."""
    base = str(base or "Material").strip() or "Material"
    if base not in catalog:
        return base
    if suffix:
        candidate = f"{base} · {suffix}"
        if candidate not in catalog:
            return candidate
    n = 2
    while f"{base} ({n})" in catalog:
        n += 1
    return f"{base} ({n})"


@lru_cache(maxsize=4)
def _host_library_catalog(language=""):
    """name -> recipe dict for the native bundled IngeTrazo material library.

    Reading the manifests once is important: controller refreshes are frequent,
    while the bundled library itself is static for the life of the process.
    """
    catalog = {}
    try:
        from core.paths import app_root
        from core.i18n import tr
        root = Path(app_root())
    except Exception:
        return catalog

    # RAL Classic colours.  Match the native Materials tray naming convention.
    ral_file = root / "resources" / "colors" / "ral.json"
    try:
        raw = json.loads(ral_file.read_text(encoding="utf-8"))
        for family in raw.get("families", []):
            for item in family.get("colors", []):
                if str(language).startswith("es") and item.get("name_es"):
                    human = item.get("name_es")
                else:
                    human = item.get("name") or ""
                name = _unique_name(catalog, f"{item.get('code', '').strip()} {human}".strip())
                rgb = item.get("rgb")
                if rgb is None:
                    continue
                catalog[name] = {
                    "name": name,
                    "color": tuple(float(x) for x in rgb[:3]),
                    "texture": None,
                    "opacity": None,
                }
    except Exception:
        pass

    # Bundled texture library.  Keep the same real-world tile dimensions used
    # by the native Materials tray so BIM layers and direct painting agree.
    tex_root = root / "resources" / "textures"
    manifest = tex_root / "library.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        for category in raw.get("categories", []):
            cat_id = str(category.get("id") or "library")
            for item in category.get("items", []):
                rel = item.get("file")
                if not rel:
                    continue
                raw_name = item.get("name") or Path(rel).stem
                try:
                    display = str(tr(raw_name))
                except Exception:
                    display = str(raw_name)
                name = _unique_name(catalog, display, cat_id)
                tex = {
                    "path": str(tex_root / "library" / rel),
                    "sw": float(item.get("sw", 1.0) or 1.0),
                    "sh": float(item.get("sh", item.get("sw", 1.0)) or 1.0),
                    "rot": 0.0,
                }
                catalog[name] = {
                    "name": name,
                    "color": None,
                    "texture": tex,
                    "opacity": (float(item["opacity"])
                                if item.get("opacity") is not None else None),
                }
    except Exception:
        pass

    # Loose user/bundled textures visible in the host tray's "Other" section.
    try:
        for path in sorted(tex_root.glob("*.png")):
            name = _unique_name(catalog, path.stem, "other")
            catalog[name] = {
                "name": name,
                "color": None,
                "texture": {"path": str(path), "sw": 1.0, "sh": 1.0, "rot": 0.0},
                "opacity": None,
            }
    except Exception:
        pass
    return catalog


def _language_key():
    try:
        from core.i18n import current_language
        return str(current_language() or "")
    except Exception:
        return ""


def material_catalog(scene=None):
    """Return native-library recipes merged with materials in this document."""
    catalog = dict(_host_library_catalog(_language_key()))
    registry = getattr(scene, "materials", None) if scene is not None else None
    if registry:
        for name, mat in registry.items():
            # Existing document identity wins over a same-named library recipe.
            recipe = {"name": str(name), "color": None, "texture": None, "opacity": None}
            if hasattr(mat, "color"):
                recipe["color"] = tuple(mat.color) if mat.color is not None else None
                recipe["texture"] = copy.deepcopy(mat.texture) if mat.texture is not None else None
                recipe["opacity"] = mat.opacity
            catalog[str(name)] = recipe
    return catalog


def material_names(scene):
    """All selectable material identities: document + complete host library."""
    names = set(_host_library_catalog(_language_key()).keys())
    registry = getattr(scene, "materials", None) or {}
    names.update(str(name) for name in registry.keys())
    return sorted(names, key=str.casefold)


def _material_from_recipe(name, recipe):
    from core.materials import Material
    return Material(
        str(name),
        color=copy.deepcopy(recipe.get("color")),
        texture=copy.deepcopy(recipe.get("texture")),
        opacity=recipe.get("opacity"),
    )


def ensure_material(scene, name):
    """Resolve *name* and lazily register a library material in the document."""
    if not name:
        return None
    registry = getattr(scene, "materials", None)
    if registry is None:
        return None
    mat = registry.get(name)
    if mat is not None:
        return mat
    recipe = _host_library_catalog(_language_key()).get(str(name))
    if recipe is None:
        return None
    mat = _material_from_recipe(name, recipe)
    try:
        from core.materials import register
        final = register(registry, mat)
        return registry.get(final)
    except Exception:
        registry[str(name)] = mat
        return mat


def material_face_attrs(scene, name):
    if not name:
        return None
    mat = ensure_material(scene, name)
    if mat is None:
        return None
    if hasattr(mat, "face_attrs"):
        return dict(mat.face_attrs())
    return {"mat": str(name)}


def _fit_affine_uvw(points, uvs):
    """Fit IngeTrazo's 3D affine world->UV map to corresponding points.

    Unlike ``core.texture.fit_uv_affine`` this also handles a four-corner wall
    face that became slightly non-planar after a lean/twist edit.  The renderer's
    ``uvw`` format is a full 3D affine map, so fitting all coordinates avoids the
    old workaround of triangulating the wall solely to obtain texture mapping.
    """
    if len(points) < 3 or len(points) != len(uvs):
        return None
    try:
        import numpy as np
        rows = []
        for point in points:
            if hasattr(point, "x"):
                rows.append([float(point.x()), float(point.y()), float(point.z()), 1.0])
            else:
                rows.append([float(point[0]), float(point[1]), float(point[2]), 1.0])
        a = np.asarray(rows, dtype=np.float64)
        b = np.asarray(uvs, dtype=np.float64)
        if b.ndim != 2 or b.shape[1] != 2:
            return None
        coeff, _residuals, rank, _singular = np.linalg.lstsq(a, b, rcond=None)
        # A planar face has rank 3 and a non-planar quad may have rank 4.  Rank
        # below three means the face is degenerate and should use planar mapping.
        if int(rank) < 3:
            return None
        predicted = a @ coeff
        if float(np.max(np.abs(predicted - b))) > 1.0e-5:
            return None
        return [float(coeff[0, 0]), float(coeff[1, 0]), float(coeff[2, 0]), float(coeff[3, 0]),
                float(coeff[0, 1]), float(coeff[1, 1]), float(coeff[2, 1]), float(coeff[3, 1])]
    except Exception:
        return None


def transferable_face_attrs(face, target_points=None):
    """Copy face appearance safely across a parametric geometry rebuild.

    When a regenerated face has the same ordered corners as its source face,
    explicit UV coordinates are carried to those new corners and re-fitted as
    a fresh world->UV affine map.  This preserves a user's positioned texture
    through wall height/lean edits without tying it to the old plane and without
    triangulating the wall.  If the topology no longer corresponds, only the
    visual tile size/rotation is retained and the host performs a new planar
    projection.
    """
    attrs = copy.deepcopy(getattr(face, "attrs", None) or {})
    tex = attrs.get("texture")
    if not (isinstance(tex, dict) and tex.get("uvw")):
        return attrs

    source_points = list(getattr(face, "vertices", ()) or ())
    target_points = list(target_points or ())
    if len(source_points) == len(target_points) and len(source_points) >= 3:
        try:
            from core.texture import affine_uv
            source_uvs = affine_uv(tex["uvw"], source_points)
            mapped = _fit_affine_uvw(target_points, source_uvs)
            if mapped is not None:
                attrs["texture"] = {**copy.deepcopy(tex), "uvw": mapped}
                return attrs
        except Exception:
            pass

    try:
        from core.texture import flattened_texture
        attrs["texture"] = flattened_texture(tex, face.normal())
    except Exception:
        # Better to fall back to a fresh planar projection than retain an
        # affine map whose source plane/topology no longer exists.
        clean = dict(tex)
        clean.pop("uvw", None)
        attrs["texture"] = clean
    return attrs


def transfer_semantic_face_appearance(previous_mesh, new_mesh, semantic_key, *,
                                      fallback_key=None, drop_keys=()):
    """Transfer appearance between regenerated faces by semantic family/order.

    Parametric generators already tag cap/top/bottom/side faces.  Pairing each
    source face with the corresponding regenerated face fixes the old pattern of
    storing only the *first* ``side`` appearance and stamping it on both wall
    sides.  If a topology-changing edit changes the number of faces in a family,
    appearance still transfers, but explicit UVW is flattened instead of being
    guessed against unrelated corners.
    """
    if previous_mesh is None or new_mesh is None:
        return 0
    old_buckets = {}
    old_default = None
    for face in list(getattr(previous_mesh, "faces", ()) or ()):
        key = (getattr(face, "attrs", None) or {}).get(semantic_key)
        if key is not None:
            old_buckets.setdefault(key, []).append(face)
        if old_default is None:
            old_default = face
    new_buckets = {}
    for face in list(getattr(new_mesh, "faces", ()) or ()):
        key = (getattr(face, "attrs", None) or {}).get(semantic_key)
        if key is not None:
            new_buckets.setdefault(key, []).append(face)

    changed = 0
    for key, targets in new_buckets.items():
        sources = old_buckets.get(key) or (old_buckets.get(fallback_key) if fallback_key else None) or []
        exact = len(sources) == len(targets) and bool(sources)
        for index, target in enumerate(targets):
            source = sources[index] if exact else (sources[0] if sources else old_default)
            if source is None:
                continue
            semantic = (getattr(target, "attrs", None) or {}).get(semantic_key)
            attrs = transferable_face_attrs(
                source, list(getattr(target, "vertices", ()) or ()) if exact else None)
            for drop in drop_keys:
                attrs.pop(drop, None)
            target.attrs.update(attrs)
            target.attrs[semantic_key] = semantic
            changed += 1
    return changed


def infer_material_name(group):
    """Return a stable named material already worn by an object, if any."""
    ext = getattr(group, "ext", None) or {}
    for rec in ext.values() if isinstance(ext, dict) else ():
        if isinstance(rec, dict) and rec.get("material_name"):
            return str(rec["material_name"])
    for child in getattr(group, "children", ()) or ():
        for face in getattr(getattr(child, "mesh", None), "faces", ()) or ():
            name = (getattr(face, "attrs", None) or {}).get("mat")
            if name:
                return str(name)
    return None


def stamp_named_material(group, scene, name, *, clear=False):
    """Stamp *name* on every generated face.

    Parametric materials are face-owned and therefore survive native render,
    save/export and takeoff paths.  A bundled-library material is registered
    lazily the first time it is selected here.
    """
    attrs = material_face_attrs(scene, name)
    if attrs is None and not clear:
        return
    targets = []
    children = getattr(group, "children", None) or ()
    if children:
        targets.extend(children)
    elif getattr(group, "mesh", None) is not None:
        targets.append(group)
    for child in targets:
        for face in getattr(getattr(child, "mesh", None), "faces", ()) or ():
            fattrs = face.attrs
            for key in _MATERIAL_KEYS:
                fattrs.pop(key, None)
            if attrs is not None:
                fattrs.update(copy.deepcopy(attrs))


def stamp_structured_materials(group, scene, values, *, clear=False):
    """Apply per-layer materials to composite children, or one material to simple objects."""
    layers = values.get("layers") if isinstance(values, dict) else None
    structure = values.get("structure", "simple") if isinstance(values, dict) else "simple"
    if structure == "composite" and layers:
        children = list(getattr(group, "children", ()) or ())
        for child, layer in zip(children, layers):
            stamp_named_material(child, scene, layer.get("material_name"), clear=True)
        return
    stamp_named_material(
        group, scene,
        values.get("material_name") if isinstance(values, dict) else None,
        clear=clear,
    )
