# SPDX-License-Identifier: GPL-3.0-or-later
"""Small helpers for full-geometry live previews in OpenTrace tools."""
from __future__ import annotations

import copy
from core.geometry import Face as PreviewFace


def group_faces_world(group):
    """Return renderable world-space preview faces for a temporary Group.

    The helper deliberately knows nothing about the parametric element type.
    Tools can regenerate a temporary wall/beam/column with the normal model
    functions and let the viewport draw the *real candidate geometry* before
    the history command is committed.
    """
    out = []
    children = list(getattr(group, "children", ()) or ())
    if not children and getattr(group, "mesh", None) is not None:
        children = [group]
    for child in children:
        mesh = getattr(child, "mesh", None)
        if mesh is None:
            continue
        cx = getattr(child, "xform", None)
        gx = getattr(group, "xform", None)
        for face in list(getattr(mesh, "faces", ()) or ()):
            loop = []
            for vertex in list(getattr(face, "loop", ()) or ()):
                p = vertex.position
                if cx is not None and child is not group:
                    p = cx.map(p)
                if gx is not None:
                    p = gx.map(p)
                loop.append(p)
            if len(loop) < 3:
                continue
            attrs = copy.deepcopy(dict(getattr(face, "attrs", {}) or {}))
            out.append(PreviewFace(loop, attrs=attrs))
    return out


def hide_original_for_preview(group):
    """Temporarily hide the source group while an exact candidate is drawn.

    Editing tools often regenerate a full shaded candidate.  Leaving the
    original visible makes beams/columns overlap with the preview and can make
    the edit look like two solids fighting each other.  ``Group.hidden`` is a
    runtime drawing flag, so toggling it here does not create history or mutate
    parametric data.  The previous state is returned for exact restoration.
    """
    if group is None or not hasattr(group, "hidden"):
        return None
    old = bool(group.hidden)
    group.hidden = True
    return old


def restore_original_after_preview(group, previous):
    """Restore a group hidden by :func:`hide_original_for_preview`."""
    if group is None or previous is None or not hasattr(group, "hidden"):
        return
    group.hidden = bool(previous)


def pointer_world_on_plane(viewport, plane):
    """World point below the *current* mouse cursor on ``plane``.

    Radial-palette actions are chosen with the mouse already somewhere over the
    model.  Waiting for the next mouse-move event makes a direct handle appear
    to pause at its old position.  This helper safely samples the cursor at tool
    activation so a direct edit can jump to it immediately.  It deliberately
    uses the viewport's own ray/plane conversion when available, keeping the
    exact same projection that subsequent hover events use.
    """
    if viewport is None or plane is None:
        return None
    try:
        from PySide6.QtGui import QCursor
        local = viewport.mapFromGlobal(QCursor.pos())
        # A floating radial palette can lie over the viewport.  Its global
        # cursor coordinate still maps to the model pixel underneath.
        if not viewport.rect().adjusted(-2, -2, 2, 2).contains(local):
            return None
        hit = getattr(viewport, "_ray_hit_plane", None)
        if callable(hit):
            return hit((float(local.x()), float(local.y())), plane)
    except Exception:
        pass
    return None
