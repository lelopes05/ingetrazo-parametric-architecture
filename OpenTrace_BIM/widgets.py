# SPDX-License-Identifier: GPL-3.0-or-later
"""Small UI helpers shared by the parametric architecture tools."""
from __future__ import annotations

from PySide6.QtCore import QLocale
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox


class FlexibleDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that accepts both decimal comma and decimal point.

    The widget still *displays* according to its configured Qt locale, but typed
    input such as ``2,70`` and ``2.70`` is treated identically.  This is useful
    in architectural offices where the OS, numpad and copied dimensions often
    use different decimal separators.
    """

    @staticmethod
    def _normalize(text: str) -> str:
        return str(text).replace("\u00a0", " ").replace(",", ".")

    def valueFromText(self, text: str) -> float:  # noqa: N802 - Qt API
        raw = self._normalize(text).strip()
        suffix = self.suffix()
        prefix = self.prefix()
        if prefix and raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        if suffix and raw.endswith(suffix):
            raw = raw[:-len(suffix)].strip()
        # Keep QDoubleSpinBox's ordinary bounds/rounding behaviour after a
        # permissive decimal parse.  Locale group separators are intentionally
        # not accepted here because architectural dimensions do not need them.
        try:
            return float(raw)
        except ValueError:
            return super().valueFromText(text)

    def validate(self, text: str, pos: int):  # noqa: N802 - Qt API
        # Let Qt validate a copy using the locale's preferred decimal separator.
        dec = self.locale().decimalPoint()
        normalized = str(text).replace(",", dec).replace(".", dec)
        state, _text, _pos = super().validate(normalized, pos)
        return state, text, pos
