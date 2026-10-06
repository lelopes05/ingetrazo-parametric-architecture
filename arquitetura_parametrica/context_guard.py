# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep parametric BIM objects out of the host's raw group-edit context."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt


def _parametric_root(scene, item):
    g = getattr(item, "owner", None) or item
    if g not in getattr(scene, "groups", ()):
        return None
    ext = getattr(g, "ext", None)
    rec = ext.get("arquitetura_parametrica") if isinstance(ext, dict) else None
    if isinstance(rec, dict) and rec.get("kind") in {"wall", "slab", "column", "beam"}:
        return g
    return None


def has_parametric_selection(scene):
    return any(_parametric_root(scene, item) is not None for item in scene.selection)


class ParametricContextGuard(QObject):
    """Consume double-clicks that would enter the generated body group.

    Parametric elements are edited from their own controls. Hiding overlays
    while a native edit context is active also avoids mixing root/world and
    nested/local coordinates if an old document or another command enters one.
    """
    def __init__(self, app, controllers):
        super().__init__(app.window)
        self.app = app
        self.controllers = [c for c in controllers if c is not None]
        app.viewport.installEventFilter(self)

    def _refresh_all(self):
        for c in self.controllers:
            for name in ("hide_endpoint_palette", "hide_context_palette", "hide_path_palette", "hide_reference_palette", "hide_straight_mode_palette", "hide_curve_mode_palette", "hide_mode_palette"):
                fn = getattr(c, name, None)
                if callable(fn):
                    try: fn()
                    except Exception: pass
            fn = getattr(c, "schedule_refresh", None)
            if callable(fn):
                try: fn()
                except Exception: pass
        self.app.viewport.update()

    def eventFilter(self, obj, event):
        if obj is not self.app.viewport:
            return False
        if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            if has_parametric_selection(self.app.scene):
                self._refresh_all()
                try:
                    self.app.viewport.flash_status("Objeto paramétrico: use os controles do IngeTraço para editar.", 2500)
                except Exception:
                    pass
                event.accept()
                return True
        if event.type() in (QEvent.KeyPress, QEvent.KeyRelease) and event.key() == Qt.Key_Escape:
            # Let the host finish leaving any native context, then rebuild all
            # contextual controls from the root/world parametric data.
            QTimer.singleShot(0, self._refresh_all)
        return False
