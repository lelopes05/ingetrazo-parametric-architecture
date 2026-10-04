# SPDX-License-Identifier: GPL-3.0-or-later
"""Floating palettes used by the architecture tools."""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import (
    QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap,
    QPolygonF, QRegion,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolTip

from .i18n import t


class _DragHandle(QLabel):
    def __init__(self, palette):
        super().__init__("⠿", palette)
        self._palette = palette
        self._press_global = None
        self._press_pos = None
        self.setToolTip(t("Arraste para mover esta paleta, inclusive para outro monitor."))
        self.setCursor(QCursor(Qt.SizeAllCursor))
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(20, 30)
        self.setStyleSheet("color: rgba(255,255,255,170); padding:0; margin:0;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_pos = QPoint(self._palette.pos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_global is not None and (event.buttons() & Qt.LeftButton):
            delta = event.globalPosition().toPoint() - self._press_global
            self._palette.move(self._press_pos + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_global = None
            self._press_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DraggablePalette(QFrame):
    """Top-level frameless palette with a small explicit drag handle."""

    def __init__(self, owner_window, *, popup=False):
        flags = (Qt.Popup if popup else Qt.Tool) | Qt.FramelessWindowHint
        super().__init__(owner_window, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        if not popup:
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(5, 5, 5, 5)
        self._row.setSpacing(3)
        self.drag_handle = _DragHandle(self)
        self._row.addWidget(self.drag_handle)

    @property
    def row(self):
        return self._row


class _RadialDragHandle(QLabel):
    """Small draggable tab attached to the upper-right edge of a radial palette."""

    def __init__(self, palette):
        # Keep the reference palette's little attached corner tab, but make its
        # purpose explicit with a move glyph instead of an ``x``.
        super().__init__("↕↔", palette)
        self._palette = palette
        self._press_global = None
        self._press_pos = None
        self.setToolTip(t("Arraste para mover esta paleta, inclusive para outro monitor."))
        self.setCursor(QCursor(Qt.SizeAllCursor))
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(27, 22)
        self.setStyleSheet(
            "color: rgba(25,25,25,220);"
            "background: rgba(252,252,252,178);"
            "border: 1px solid rgba(0,0,0,38);"
            "border-radius: 5px; padding:0; margin:0;"
            "font-size: 12px; font-weight: 600;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_pos = QPoint(self._palette.pos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_global is not None and (event.buttons() & Qt.LeftButton):
            delta = event.globalPosition().toPoint() - self._press_global
            self._palette.move(self._press_pos + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._press_global is not None:
                self._palette.remember_current_position()
            self._press_global = None
            self._press_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _RadialRow:
    """Tiny layout-compatible proxy used by the existing palette builders."""

    def __init__(self, palette):
        self._palette = palette

    def addWidget(self, widget):  # noqa: N802 - Qt-compatible spelling
        self._palette.add_radial_widget(widget)


class RadialPalette(QFrame):
    """Floating palette arranged in one or more concentric rings.

    The centre is a real transparent hole.  Each annular sector is the hit
    target for its command, so the user does not need to aim at the glyph.
    The glyph itself is intentionally borderless and only communicates the
    command.  ``role='draw'`` uses the warm orange hover; ``role='edit'`` uses
    blue so drawing and modelling/editing remain distinguishable without
    forcing different icon shapes.
    """

    # 0.7.5: reduce the radial plate by another ~25% while keeping the
    # command glyph widgets at their existing size.  Ring centres/gaps and the
    # transparent core shrink; icons stay untouched.
    CORE_RADIUS = 45.0
    FIRST_RING_RADIUS = 63.0
    RING_GAP = 51.0
    BUTTON_EXTENT = 34.0
    OUTER_PADDING = 7.0
    CURSOR_OFFSET_RATIO = 0.75

    # One shared user position is used by every radial palette (wall, slab,
    # beam, column, draw/edit).  It is persisted so switching object/palette
    # -- and even restarting IngeTrazo -- keeps the user's chosen location.
    SETTINGS_ORG = "IngeTrazo"
    SETTINGS_APP = "ArquiteturaParametrica"
    SETTINGS_KEY = "radial_palette/user_center"
    _shared_position_loaded = False
    _shared_user_center = None

    DRAW_COLOR = QColor(232, 138, 62)
    EDIT_COLOR = QColor(57, 132, 219)

    def __init__(self, owner_window, *, popup=True, ring_capacity=8, role="edit"):
        flags = (Qt.Popup if popup else Qt.Tool) | Qt.FramelessWindowHint
        super().__init__(owner_window, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        if not popup:
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self._widgets = []
        self._row = _RadialRow(self)
        self._ring_capacity = max(3, int(ring_capacity))
        self._ring_counts = []
        self._ring_radii = []
        self._segment_meta = []
        self._core_radius = self.CORE_RADIUS
        self._button_extent = self.BUTTON_EXTENT
        self._outer_radius = self.FIRST_RING_RADIUS + self.BUTTON_EXTENT
        self._center = QPoint(int(self._outer_radius), int(self._outer_radius))
        self._background_cache = None
        self._background_key = None
        self._mask_key = None
        self._hover_widget = None
        self._pressed_widget = None
        self._role = "draw" if str(role).lower() == "draw" else "edit"
        self.drag_handle = _RadialDragHandle(self)
        self.drag_handle.hide()

        # Command glyphs are deliberately naked: no square/circular button
        # outline.  Interaction feedback belongs to the whole radial sector.
        self.setStyleSheet("""
            QToolButton {
                color: rgba(12,12,12,248);
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QToolButton:hover, QToolButton:pressed, QToolButton:checked {
                color: rgba(0,0,0,255);
                background: transparent;
                border: none;
            }
            QToolButton:disabled {
                color: rgba(0,0,0,70);
                background: transparent;
                border: none;
            }
        """)

    @property
    def row(self):
        return self._row

    @property
    def accent(self):
        return self.DRAW_COLOR if self._role == "draw" else self.EDIT_COLOR

    def add_radial_widget(self, widget):
        if widget not in self._widgets:
            self._widgets.append(widget)
        widget.setParent(self)
        # The annular sector owns input; the child only paints the glyph.
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._background_key = None

    def _shown_widgets(self):
        return [w for w in self._widgets if not w.isHidden()]

    @staticmethod
    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    @classmethod
    def _load_shared_position(cls):
        if cls._shared_position_loaded:
            return cls._shared_user_center
        cls._shared_position_loaded = True
        try:
            raw = QSettings(cls.SETTINGS_ORG, cls.SETTINGS_APP).value(cls.SETTINGS_KEY, "")
            if raw:
                xs, ys = str(raw).split(",", 1)
                cls._shared_user_center = QPoint(int(round(float(xs))), int(round(float(ys))))
        except Exception:
            cls._shared_user_center = None
        return cls._shared_user_center

    @classmethod
    def _save_shared_position(cls, center):
        cls._shared_position_loaded = True
        cls._shared_user_center = QPoint(center)
        try:
            QSettings(cls.SETTINGS_ORG, cls.SETTINGS_APP).setValue(
                cls.SETTINGS_KEY, f"{center.x()},{center.y()}"
            )
        except Exception:
            pass

    def remember_current_position(self):
        """Remember this palette centre for every radial palette."""
        if self.width() <= 1 or self.height() <= 1:
            return
        center = self.pos() + QPoint(self.width() // 2, self.height() // 2)
        type(self)._save_shared_position(center)

    def _top_left_for_center(self, center, fallback_point):
        """Place this palette around *center*, clamping to a visible screen."""
        center = QPoint(center)
        screen = QGuiApplication.screenAt(center)
        if screen is None:
            screen = QGuiApplication.screenAt(QPoint(fallback_point))
        area = screen.availableGeometry() if screen is not None else None
        x = int(round(center.x() - self.width() * 0.5))
        y = int(round(center.y() - self.height() * 0.5))
        if area is not None:
            x = self._clamp(x, area.left(), area.right() - self.width() + 1)
            y = self._clamp(y, area.top(), area.bottom() - self.height() + 1)
        return int(x), int(y)

    def _ring_boundaries(self):
        if not self._ring_radii:
            return [self._core_radius, self._outer_radius]
        boundaries = [self._core_radius]
        for a, b in zip(self._ring_radii, self._ring_radii[1:]):
            boundaries.append((a + b) * 0.5)
        boundaries.append(self._outer_radius - 3.0)
        return boundaries

    def _layout_radial(self):
        widgets = self._shown_widgets()
        if not widgets:
            self.resize(1, 1)
            self._background_cache = None
            self._background_key = None
            self._segment_meta = []
            self.drag_handle.hide()
            return

        chunks = [widgets[i:i + self._ring_capacity]
                  for i in range(0, len(widgets), self._ring_capacity)]
        rings = len(chunks)
        self._ring_radii = [self.FIRST_RING_RADIUS + i * self.RING_GAP
                            for i in range(rings)]
        self._ring_counts = [len(c) for c in chunks]

        max_half = max(float(max(w.width(), w.height())) * 0.5 for w in widgets)
        max_half = max(max_half, self._button_extent * 0.5)
        self._outer_radius = self._ring_radii[-1] + max_half + self.OUTER_PADDING
        diameter = int(math.ceil(self._outer_radius * 2.0))
        if self.size().width() != diameter or self.size().height() != diameter:
            self.resize(diameter, diameter)
        self._center = QPoint(diameter // 2, diameter // 2)

        self._segment_meta = []
        boundaries = self._ring_boundaries()
        for ring_index, chunk in enumerate(chunks):
            radius = self._ring_radii[ring_index]
            count = len(chunk)
            step = 360.0 / float(count)
            for i, w in enumerate(chunk):
                centre_angle = -90.0 + i * step
                angle = math.radians(centre_angle)
                cx = self._center.x() + math.cos(angle) * radius
                cy = self._center.y() + math.sin(angle) * radius
                ww, hh = w.width(), w.height()
                w.move(int(round(cx - ww * 0.5)), int(round(cy - hh * 0.5)))
                w.raise_()
                self._segment_meta.append({
                    "widget": w,
                    "ring": ring_index,
                    "index": i,
                    "count": count,
                    "rin": boundaries[ring_index],
                    "rout": boundaries[ring_index + 1],
                    "start": centre_angle - step * 0.5,
                    "span": step,
                })

        # Attach the drag tab directly to the upper-right circumference rather
        # than leaving it out near the square bounding-box corner.
        hw, hh = self.drag_handle.width(), self.drag_handle.height()
        handle_angle = math.radians(-45.0)
        handle_r = max(self._core_radius, self._outer_radius - 5.0)
        hcx = self._center.x() + math.cos(handle_angle) * handle_r
        hcy = self._center.y() + math.sin(handle_angle) * handle_r
        hx = int(round(hcx - hw * 0.5))
        hy = int(round(hcy - hh * 0.5))
        self.drag_handle.move(hx, hy)
        self.drag_handle.show()
        self.drag_handle.raise_()

        # The native window mask is a donut plus the attached drag tab.  The
        # centre hole therefore remains a real input hole through to viewport.
        outer_region = QRegion(0, 0, diameter, diameter, QRegion.Ellipse)
        handle_region = QRegion(int(hx), int(hy), int(hw), int(hh))
        outer_region = outer_region.united(handle_region)
        inner_d = int(round(self._core_radius * 2.0))
        inner_x = self._center.x() - inner_d // 2
        inner_y = self._center.y() - inner_d // 2
        mask_key = (diameter, inner_d, int(hx), int(hy), int(hw), int(hh))
        if self._mask_key != mask_key:
            inner_region = QRegion(inner_x, inner_y, inner_d, inner_d, QRegion.Ellipse)
            self.setMask(outer_region.subtracted(inner_region))
            self._mask_key = mask_key

        key = (
            diameter,
            tuple(self._ring_counts),
            tuple(round(r, 3) for r in self._ring_radii),
            round(self._core_radius, 3),
        )
        if key != self._background_key:
            self._background_key = key
            self._rebuild_background()
        self.update()

    def _rebuild_background(self):
        """Pre-render only the static translucent annulus and separators."""
        if self.width() <= 1:
            self._background_cache = None
            return
        pm = QPixmap(self.size())
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        c = self._center
        outer = self._outer_radius - 3.0
        inner = self._core_radius

        # 20% more transparent than 0.7.2 (222 -> ~178 alpha).  Glyphs remain
        # opaque black because they are independent child widgets.
        outer_path = QPainterPath()
        outer_path.addEllipse(QRectF(c.x() - outer, c.y() - outer,
                                     outer * 2.0, outer * 2.0))
        inner_path = QPainterPath()
        inner_path.addEllipse(QRectF(c.x() - inner, c.y() - inner,
                                     inner * 2.0, inner * 2.0))
        annulus = outer_path.subtracted(inner_path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(252, 252, 252, 178))
        painter.drawPath(annulus)

        # Subtle outlines and separators remain visible through the lighter plate.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 54), 1.0))
        painter.drawEllipse(QRectF(c.x() - outer, c.y() - outer,
                                   outer * 2.0, outer * 2.0))
        painter.drawEllipse(QRectF(c.x() - inner, c.y() - inner,
                                   inner * 2.0, inner * 2.0))

        boundaries = self._ring_boundaries()
        painter.setPen(QPen(QColor(0, 0, 0, 31), 1.0))
        for boundary in boundaries[1:-1]:
            painter.drawEllipse(QRectF(c.x() - boundary, c.y() - boundary,
                                       boundary * 2.0, boundary * 2.0))

        painter.setPen(QPen(QColor(0, 0, 0, 29), 1.0))
        for ring_index, count in enumerate(self._ring_counts):
            if count <= 1:
                continue
            rin = boundaries[ring_index]
            rout = boundaries[ring_index + 1]
            step = 360.0 / float(count)
            for i in range(count):
                angle = math.radians(-90.0 - step * 0.5 + i * step)
                ca, sa = math.cos(angle), math.sin(angle)
                x1, y1 = c.x() + ca * rin, c.y() + sa * rin
                x2, y2 = c.x() + ca * rout, c.y() + sa * rout
                painter.drawLine(int(round(x1)), int(round(y1)),
                                 int(round(x2)), int(round(y2)))
        painter.end()
        self._background_cache = pm

    def _sector_polygon(self, meta):
        c = self._center
        start = meta["start"]
        span = meta["span"]
        # Enough samples for smooth hover edges without turning mouse movement
        # into expensive geometry work.
        samples = max(8, int(abs(span) / 6.0) + 1)
        points = []
        for j in range(samples + 1):
            a = math.radians(start + span * j / samples)
            points.append(QPointF(c.x() + math.cos(a) * meta["rout"],
                                  c.y() + math.sin(a) * meta["rout"]))
        for j in range(samples, -1, -1):
            a = math.radians(start + span * j / samples)
            points.append(QPointF(c.x() + math.cos(a) * meta["rin"],
                                  c.y() + math.sin(a) * meta["rin"]))
        return QPolygonF(points)

    def _meta_for_widget(self, widget):
        for meta in self._segment_meta:
            if meta["widget"] is widget:
                return meta
        return None

    def _hit_widget_at(self, pos):
        dx = float(pos.x() - self._center.x())
        dy = float(pos.y() - self._center.y())
        radius = math.hypot(dx, dy)
        if radius < self._core_radius or radius > (self._outer_radius - 3.0):
            return None
        angle = math.degrees(math.atan2(dy, dx))
        for meta in self._segment_meta:
            if not (meta["rin"] <= radius <= meta["rout"]):
                continue
            centre = meta["start"] + meta["span"] * 0.5
            delta = ((angle - centre + 180.0) % 360.0) - 180.0
            if abs(delta) <= meta["span"] * 0.5 + 1e-6:
                w = meta["widget"]
                if w.isEnabled():
                    return w
                return None
        return None

    def adjustSize(self):  # noqa: N802 - Qt API
        self._layout_radial()

    def show_at(self, global_pos):
        """Show the radial palette clear of the clicked/cursor reference point.

        The palette centre is displaced by 75% of its own diameter.  We prefer
        the upper-left quadrant, then try the other diagonals before falling
        back to clamping inside the active screen.  That keeps the click target
        visible instead of burying it under the radial.
        """
        self._hover_widget = None
        self._pressed_widget = None
        self._layout_radial()
        if self.width() <= 1:
            return

        point = QPoint(global_pos)

        # Once the user drags any radial palette, every other radial palette
        # reuses that same remembered centre.  Until then, retain the 0.7.4
        # behaviour of opening clear of the cursor, now to its left.
        remembered = type(self)._load_shared_position()
        if remembered is not None:
            self.move(*self._top_left_for_center(remembered, point))
            self.show()
            self.repaint()
            self.raise_()
            self.drag_handle.raise_()
            return

        screen = QGuiApplication.screenAt(point)
        area = screen.availableGeometry() if screen is not None else None

        size_ref = float(max(self.width(), self.height()))
        distance = self.CURSOR_OFFSET_RATIO * size_ref
        component = distance / math.sqrt(2.0)
        offsets = (
            (-component, -component),  # preferred first appearance: upper-left
            (-component,  component),
            ( component, -component),
            ( component,  component),
        )

        chosen = None
        for dx, dy in offsets:
            cx = point.x() + dx
            cy = point.y() + dy
            x = int(round(cx - self.width() * 0.5))
            y = int(round(cy - self.height() * 0.5))
            if area is None:
                chosen = (x, y)
                break
            if (x >= area.left() and y >= area.top() and
                    x + self.width() - 1 <= area.right() and
                    y + self.height() - 1 <= area.bottom()):
                chosen = (x, y)
                break

        if chosen is None:
            # Keep the requested displacement direction as much as possible
            # even when the palette is close to an edge of the monitor.
            dx, dy = offsets[0]
            x = int(round(point.x() + dx - self.width() * 0.5))
            y = int(round(point.y() + dy - self.height() * 0.5))
            if area is not None:
                x = self._clamp(x, area.left(), area.right() - self.width() + 1)
                y = self._clamp(y, area.top(), area.bottom() - self.height() + 1)
            chosen = (int(x), int(y))

        self.move(*chosen)
        self.show()
        self.repaint()
        self.raise_()
        self.drag_handle.raise_()

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt API
        w = self._hit_widget_at(event.position())
        if w is not self._hover_widget:
            self._hover_widget = w
            self.update()
        self.setCursor(Qt.PointingHandCursor if w is not None else Qt.ArrowCursor)
        event.accept()

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            self._pressed_widget = self._hit_widget_at(event.position())
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            w = self._hit_widget_at(event.position())
            pressed = self._pressed_widget
            self._pressed_widget = None
            self.update()
            if w is not None and w is pressed:
                w.click()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt API
        self._hover_widget = None
        self._pressed_widget = None
        self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    def event(self, event):
        if event.type() == QEvent.ToolTip:
            w = self._hit_widget_at(event.pos())
            if w is not None and w.toolTip():
                QToolTip.showText(event.globalPos(), w.toolTip(), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    def paintEvent(self, event):  # noqa: N802 - Qt API
        if self._background_cache is None:
            self._rebuild_background()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._background_cache is not None:
            painter.drawPixmap(0, 0, self._background_cache)

        accent = self.accent
        # Checked creation methods get a faint persistent sector tint.
        for meta in self._segment_meta:
            w = meta["widget"]
            if hasattr(w, "isChecked") and w.isChecked():
                tint = QColor(accent)
                tint.setAlpha(42)
                painter.setPen(Qt.NoPen)
                painter.setBrush(tint)
                painter.drawPolygon(self._sector_polygon(meta))

        active = self._pressed_widget or self._hover_widget
        if active is not None:
            meta = self._meta_for_widget(active)
            if meta is not None:
                tint = QColor(accent)
                tint.setAlpha(125 if self._pressed_widget is not None else 82)
                painter.setPen(Qt.NoPen)
                painter.setBrush(tint)
                painter.drawPolygon(self._sector_polygon(meta))
        painter.end()