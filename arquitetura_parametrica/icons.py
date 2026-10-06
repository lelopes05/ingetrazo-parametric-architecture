# SPDX-License-Identifier: GPL-3.0-or-later
"""Small vector icon family for the Parametric Architecture UI.

The icons are painted at runtime with Qt so the plugin stays self contained and
can carry the same visual language to other hosts later without shipping a pile
of bitmap assets.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

BLUE = QColor("#42658d")
BLUE_LIGHT = QColor("#a9bfd7")
BLUE_MID = QColor("#7e9fbe")
ORANGE = QColor("#c46b2d")
SAND = QColor("#d8c49e")
GREEN = QColor("#6e9872")
INK = QColor("#34404b")


def _pm(size=32):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    return pm


def _painter(pm):
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    return p


def _pen(color=BLUE, width=2.0):
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def icon(name: str, size: int = 32) -> QIcon:
    name = str(name or "").lower()
    pm = _pm(size)
    p = _painter(pm)
    s = float(size) / 32.0
    def q(v): return v * s
    p.setPen(_pen(BLUE, q(2.0)))
    p.setBrush(Qt.NoBrush)

    if name in ("home", "architecture", "plugin"):
        roof = QPolygonF([QPointF(q(5),q(15)), QPointF(q(16),q(6)), QPointF(q(27),q(15))])
        p.drawPolyline(roof)
        p.drawRect(QRectF(q(8),q(14),q(16),q(12)))
        p.setBrush(BLUE_LIGHT); p.drawRect(QRectF(q(13),q(18),q(6),q(8)))
    elif name == "wall":
        p.setBrush(BLUE_LIGHT); p.drawRoundedRect(QRectF(q(4),q(8),q(24),q(16)),q(1.5),q(1.5))
        p.drawLine(QPointF(q(4),q(16)),QPointF(q(28),q(16)))
        p.drawLine(QPointF(q(12),q(8)),QPointF(q(12),q(16)))
        p.drawLine(QPointF(q(20),q(16)),QPointF(q(20),q(24)))
    elif name == "wall_composite":
        for y, col in ((7,BLUE_LIGHT),(13,BLUE_MID),(19,SAND)):
            p.setBrush(col); p.drawRect(QRectF(q(4),q(y),q(24),q(6)))
    elif name == "wall_curve":
        p.setBrush(Qt.NoBrush); p.setPen(_pen(BLUE,q(3)))
        p.drawArc(QRectF(q(5),q(5),q(22),q(22)), 25*16, 130*16)
        p.drawArc(QRectF(q(9),q(9),q(14),q(14)), 25*16, 130*16)
    elif name == "slab":
        p.setBrush(BLUE_LIGHT); p.drawPolygon(QPolygonF([
            QPointF(q(5),q(11)),QPointF(q(22),q(7)),QPointF(q(28),q(12)),QPointF(q(11),q(17))]))
        p.setBrush(BLUE_MID); p.drawPolygon(QPolygonF([
            QPointF(q(5),q(11)),QPointF(q(11),q(17)),QPointF(q(11),q(22)),QPointF(q(5),q(16))]))
        p.drawPolygon(QPolygonF([QPointF(q(11),q(17)),QPointF(q(28),q(12)),QPointF(q(28),q(17)),QPointF(q(11),q(22))]))
    elif name == "slab_composite":
        for y, col in ((8,BLUE_LIGHT),(14,BLUE_MID),(20,SAND)):
            p.setBrush(col); p.drawRect(QRectF(q(5),q(y),q(22),q(5)))
    elif name == "column":
        p.setBrush(BLUE_LIGHT); p.drawRect(QRectF(q(10),q(5),q(11),q(22)))
        p.setBrush(BLUE_MID); p.drawPolygon(QPolygonF([
            QPointF(q(21),q(5)),QPointF(q(26),q(9)),QPointF(q(26),q(27)),QPointF(q(21),q(27))]))
        p.drawLine(QPointF(q(10),q(5)),QPointF(q(15),q(9)))
    elif name == "beam":
        p.setBrush(BLUE_LIGHT); p.drawRect(QRectF(q(4),q(11),q(24),q(10)))
        p.setBrush(BLUE_MID); p.drawRect(QRectF(q(7),q(8),q(18),q(3))); p.drawRect(QRectF(q(7),q(21),q(18),q(3)))
    elif name in ("profile", "profiles"):
        p.setBrush(Qt.NoBrush); p.setPen(_pen(BLUE,q(2.2)))
        pts=[(6,25),(6,7),(20,7),(26,12),(20,17),(13,17),(13,25),(6,25)]
        for a,b in zip(pts,pts[1:]): p.drawLine(QPointF(q(a[0]),q(a[1])),QPointF(q(b[0]),q(b[1])))
        p.setPen(_pen(ORANGE,q(1.8))); p.drawEllipse(QRectF(q(17),q(10),q(4),q(4)))
    elif name in ("library", "presets"):
        p.setBrush(BLUE_LIGHT); p.drawRoundedRect(QRectF(q(6),q(6),q(20),q(20)),q(2),q(2))
        p.setBrush(Qt.NoBrush); p.drawLine(QPointF(q(11),q(11)),QPointF(q(22),q(11)))
        p.drawLine(QPointF(q(11),q(16)),QPointF(q(22),q(16))); p.drawLine(QPointF(q(11),q(21)),QPointF(q(19),q(21)))
        p.setPen(_pen(ORANGE,q(2))); p.drawEllipse(QRectF(q(7),q(9),q(2),q(2))); p.drawEllipse(QRectF(q(7),q(14),q(2),q(2))); p.drawEllipse(QRectF(q(7),q(19),q(2),q(2)))
    elif name == "layers":
        p.setBrush(BLUE_LIGHT); p.drawPolygon(QPolygonF([QPointF(q(5),q(11)),QPointF(q(16),q(5)),QPointF(q(27),q(11)),QPointF(q(16),q(17))]))
        p.setBrush(Qt.NoBrush); p.drawPolyline(QPolygonF([QPointF(q(5),q(16)),QPointF(q(16),q(22)),QPointF(q(27),q(16))]))
        p.drawPolyline(QPolygonF([QPointF(q(5),q(21)),QPointF(q(16),q(27)),QPointF(q(27),q(21))]))
    elif name == "add_vertex":
        p.drawLine(QPointF(q(7),q(16)),QPointF(q(25),q(16))); p.setPen(_pen(ORANGE,q(2.5)))
        p.drawLine(QPointF(q(16),q(9)),QPointF(q(16),q(23))); p.drawLine(QPointF(q(9),q(16)),QPointF(q(23),q(16)))
    elif name == "move":
        p.setPen(_pen(BLUE,q(2.2))); p.drawLine(QPointF(q(6),q(16)),QPointF(q(26),q(16))); p.drawLine(QPointF(q(6),q(16)),QPointF(q(11),q(11))); p.drawLine(QPointF(q(6),q(16)),QPointF(q(11),q(21))); p.drawLine(QPointF(q(26),q(16)),QPointF(q(21),q(11))); p.drawLine(QPointF(q(26),q(16)),QPointF(q(21),q(21)))
    elif name == "vertical":
        p.drawLine(QPointF(q(16),q(5)),QPointF(q(16),q(27))); p.drawLine(QPointF(q(16),q(5)),QPointF(q(11),q(10))); p.drawLine(QPointF(q(16),q(5)),QPointF(q(21),q(10))); p.drawLine(QPointF(q(16),q(27)),QPointF(q(11),q(22))); p.drawLine(QPointF(q(16),q(27)),QPointF(q(21),q(22)))
    elif name in ("curve", "curve_h"):
        path=QPainterPath(QPointF(q(5),q(22))); path.cubicTo(QPointF(q(9),q(6)),QPointF(q(23),q(6)),QPointF(q(27),q(22))); p.drawPath(path)
        p.setBrush(ORANGE); p.setPen(Qt.NoPen); p.drawEllipse(QRectF(q(14),q(8),q(4),q(4)))
    elif name == "curve_v":
        path=QPainterPath(QPointF(q(5),q(10))); path.cubicTo(QPointF(q(9),q(26)),QPointF(q(23),q(26)),QPointF(q(27),q(10))); p.drawPath(path)
    elif name == "opening":
        p.setBrush(BLUE_LIGHT); p.drawRect(QRectF(q(5),q(7),q(22),q(18))); p.setBrush(Qt.transparent); p.setPen(_pen(ORANGE,q(2.2))); p.drawRect(QRectF(q(11),q(12),q(10),q(13)))
    elif name == "delete":
        p.setPen(_pen(ORANGE,q(2.4))); p.drawLine(QPointF(q(9),q(9)),QPointF(q(23),q(23))); p.drawLine(QPointF(q(23),q(9)),QPointF(q(9),q(23)))
    elif name == "extend":
        p.drawLine(QPointF(q(5),q(16)),QPointF(q(25),q(16))); p.drawLine(QPointF(q(25),q(16)),QPointF(q(19),q(10))); p.drawLine(QPointF(q(25),q(16)),QPointF(q(19),q(22))); p.setPen(_pen(ORANGE,q(2))); p.drawLine(QPointF(q(10),q(9)),QPointF(q(10),q(23)))
    elif name == "height":
        p.drawLine(QPointF(q(8),q(24)),QPointF(q(24),q(24))); p.drawLine(QPointF(q(16),q(24)),QPointF(q(16),q(6))); p.drawLine(QPointF(q(16),q(6)),QPointF(q(11),q(12))); p.drawLine(QPointF(q(16),q(6)),QPointF(q(21),q(12)))
    elif name == "incline":
        p.drawLine(QPointF(q(7),q(25)),QPointF(q(25),q(25))); p.drawLine(QPointF(q(9),q(24)),QPointF(q(23),q(8))); p.setPen(_pen(ORANGE,q(1.6))); p.drawArc(QRectF(q(8),q(15),q(13),q(13)),0,58*16)
    elif name == "offset":
        p.drawRect(QRectF(q(5),q(7),q(16),q(16))); p.setPen(_pen(ORANGE,q(2))); p.drawRect(QRectF(q(11),q(13),q(16),q(14)))
    elif name == "stretch":
        p.drawRect(QRectF(q(6),q(12),q(12),q(10))); p.setPen(_pen(ORANGE,q(2))); p.drawLine(QPointF(q(18),q(17)),QPointF(q(27),q(8))); p.drawLine(QPointF(q(27),q(8)),QPointF(q(21),q(9))); p.drawLine(QPointF(q(27),q(8)),QPointF(q(26),q(14)))
    elif name == "chamfer":
        poly=QPolygonF([QPointF(q(6),q(24)),QPointF(q(6),q(8)),QPointF(q(20),q(8)),QPointF(q(26),q(14)),QPointF(q(26),q(24))]); p.drawPolyline(poly); p.setPen(_pen(ORANGE,q(2))); p.drawLine(QPointF(q(20),q(8)),QPointF(q(26),q(14)))
    elif name == "fillet":
        p.drawLine(QPointF(q(7),q(25)),QPointF(q(7),q(13))); p.drawLine(QPointF(q(19),q(7)),QPointF(q(25),q(7))); p.setPen(_pen(ORANGE,q(2.4))); p.drawArc(QRectF(q(7),q(7),q(24),q(24)),90*16,90*16)
    elif name == "rect":
        p.setBrush(BLUE_LIGHT); p.drawRect(QRectF(q(6),q(8),q(20),q(16)))
    elif name == "polygon":
        p.setBrush(BLUE_LIGHT); p.drawPolygon(QPolygonF([QPointF(q(7),q(21)),QPointF(q(10),q(8)),QPointF(q(22),q(6)),QPointF(q(27),q(17)),QPointF(q(18),q(26))]))
    elif name == "center_arc":
        p.drawEllipse(QRectF(q(14),q(14),q(4),q(4))); p.drawArc(QRectF(q(6),q(6),q(20),q(20)),20*16,120*16)
        p.setPen(_pen(ORANGE,q(1.5))); p.drawLine(QPointF(q(16),q(16)),QPointF(q(24),q(10)))
    elif name == "three_points":
        path=QPainterPath(QPointF(q(5),q(22))); path.quadTo(QPointF(q(16),q(5)),QPointF(q(27),q(22))); p.drawPath(path); p.setBrush(ORANGE);p.setPen(Qt.NoPen)
        for x,y in ((5,22),(16,10),(27,22)):p.drawEllipse(QRectF(q(x-2),q(y-2),q(4),q(4)))
    elif name == "join":
        p.drawLine(QPointF(q(6),q(8)),QPointF(q(16),q(16))); p.drawLine(QPointF(q(6),q(24)),QPointF(q(16),q(16))); p.drawLine(QPointF(q(16),q(16)),QPointF(q(27),q(16))); p.setBrush(ORANGE);p.setPen(Qt.NoPen);p.drawEllipse(QRectF(q(13.5),q(13.5),q(5),q(5)))
    else:
        p.setPen(_pen(INK,q(2))); p.drawEllipse(QRectF(q(7),q(7),q(18),q(18)))
        p.drawLine(QPointF(q(16),q(11)),QPointF(q(16),q(18))); p.drawEllipse(QRectF(q(15),q(21),q(2),q(2)))
    p.end()
    return QIcon(pm)


_SYMBOL_MAP = {
    "＋": "add_vertex", "+": "add_vertex", "✥": "move", "↔": "move",
    "↕": "vertical", "⌒": "curve_h", "∪": "curve_v", "▣": "opening",
    "□": "opening", "⊘": "delete", "⌫": "delete", "→": "extend",
    "⇧": "height", "∠": "incline", "⤢": "offset", "⇱": "stretch",
    "◩": "chamfer", "◜": "fillet", "▱": "rect", "⬠": "polygon",
    "⊥": "rect", "／": "wall", "⊙": "center_arc", "∴": "three_points",
    "⋈": "join", "": "curve_v",
}


def set_symbol_icon(button, symbol: str, size=22):
    """Replace legacy glyph buttons with consistent vector icons.

    Unknown symbols keep their text, so experimental commands remain usable.
    """
    key = _SYMBOL_MAP.get(str(symbol))
    if key is None:
        button.setText(str(symbol))
        return button
    button.setText("")
    button.setIcon(icon(key, 32))
    button.setIconSize(QSize(size, size))
    return button
