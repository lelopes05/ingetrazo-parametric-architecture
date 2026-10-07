# SPDX-License-Identifier: GPL-3.0-or-later
"""Direct table editor for parametric composite layers.

The physical stack is shown in order from ``before_label`` to ``after_label``
(Exterior -> Interior for walls, Abaixo -> Acima for slabs).  Each row is one
physical layer and can be edited directly.

``role`` remains the geometric/reference-core flag used by the existing wall
and slab geometry.  ``function`` is independent semantic BIM metadata.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox, QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QInputDialog,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .layers import (
    FUNCTION_CHOICES,
    core_index,
    finish_layer,
    normalize_layers,
    total_thickness,
)
from .widgets import FlexibleDoubleSpinBox as QDoubleSpinBox
from .i18n import t, ui_locale


class LayerEditor(QWidget):
    """Reusable composite-layer editor used by walls and slabs."""

    changed = Signal()

    COL_NAME = 0
    COL_FUNCTION = 1
    COL_MATERIAL = 2
    COL_THICKNESS = 3
    COL_CORE = 4

    def __init__(self, parent=None, *, before_label="Exterior", after_label="Interior"):
        super().__init__(parent)
        self._loading = False
        self._material_names = []
        self._selection_hint = None
        self.before_label = before_label
        self.after_label = after_label
        self._layers = normalize_layers(None)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)

        library_row = QHBoxLayout()
        library_row.setContentsMargins(0, 0, 0, 0)
        library_row.setSpacing(4)
        self.composition_combo = QComboBox(self)
        self.composition_combo.setToolTip(t("Composições reutilizáveis entre paredes, lajes e futuras coberturas."))
        self.composition_combo.addItem(t("Composição…"), "")
        self.composition_save_btn = QPushButton(t("Salvar"))
        self.composition_delete_btn = QPushButton(t("Excluir"))
        self.expand_btn = QToolButton(self)
        self.expand_btn.setText("⛶")
        self.expand_btn.setFixedSize(28, 26)
        self.composition_save_btn.setToolTip(t("Salva a pilha atual como composição reutilizável."))
        self.composition_delete_btn.setToolTip(t("Exclui a composição selecionada da biblioteca pessoal."))
        self.expand_btn.setToolTip(t("Abre o compositor de camadas em uma janela maior e redimensionável."))
        # Expansion is first and fixed-width so it cannot disappear when the
        # narrow architecture sidebar clips the right side of this row.
        library_row.addWidget(self.expand_btn)
        library_row.addWidget(self.composition_combo, 1)
        library_row.addWidget(self.composition_save_btn)
        library_row.addWidget(self.composition_delete_btn)
        root.addLayout(library_row)
        self.composition_combo.activated.connect(self._apply_composition)
        self.composition_save_btn.clicked.connect(self._save_composition)
        self.composition_delete_btn.clicked.connect(self._delete_composition)
        self.expand_btn.clicked.connect(self._open_floating_editor)
        self._refresh_compositions()

        self.before_marker = QLabel(f"▼  {t(before_label).upper()}")
        self.before_marker.setToolTip(
            t("A ordem da tabela representa a ordem física da composição.")
        )
        root.addWidget(self.before_marker)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels([
            t("Nome"),
            t("Função"),
            t("Material"),
            t("Esp."),
            t("Núcleo"),
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
        )
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(250)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.Interactive)
        header.setSectionResizeMode(self.COL_FUNCTION, QHeaderView.Interactive)
        header.setSectionResizeMode(self.COL_MATERIAL, QHeaderView.Interactive)
        # Every column is user-resizable.  Thickness/Core used to be
        # ResizeToContents, so Qt immediately overruled attempts to make them
        # narrower with the mouse.
        header.setSectionResizeMode(self.COL_THICKNESS, QHeaderView.Interactive)
        header.setSectionResizeMode(self.COL_CORE, QHeaderView.Interactive)
        header.setMinimumSectionSize(34)
        self.table.setColumnWidth(self.COL_NAME, 145)
        self.table.setColumnWidth(self.COL_FUNCTION, 185)
        self.table.setColumnWidth(self.COL_MATERIAL, 135)
        self.table.setColumnWidth(self.COL_THICKNESS, 92)
        self.table.setColumnWidth(self.COL_CORE, 62)

        self.table.horizontalHeaderItem(self.COL_NAME).setToolTip(
            t("Nome livre da camada, por exemplo: Reboco externo.")
        )
        self.table.horizontalHeaderItem(self.COL_FUNCTION).setToolTip(
            t("Função construtiva/BIM da camada.")
        )
        self.table.horizontalHeaderItem(self.COL_MATERIAL).setToolTip(
            t("Material físico associado à camada.")
        )
        self.table.horizontalHeaderItem(self.COL_THICKNESS).setToolTip(
            t("Espessura física da camada.")
        )
        self.table.horizontalHeaderItem(self.COL_CORE).setToolTip(
            t("Camada que pertence ao núcleo geométrico/de referência. Apenas uma por composição.")
        )

        self.table.itemChanged.connect(self._item_changed)
        self.table.currentCellChanged.connect(self._current_cell_changed)
        root.addWidget(self.table)

        self.after_marker = QLabel(f"▼  {t(after_label).upper()}")
        root.addWidget(self.after_marker)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(3)

        self.add_btn = QPushButton(t("+ Camada"))
        self.add_btn.setToolTip(
            t("Insere uma nova camada logo abaixo da camada selecionada.")
        )

        self.duplicate_btn = QPushButton(t("Duplicar"))
        self.duplicate_btn.setToolTip(t("Duplica a camada selecionada."))

        self.remove_btn = QPushButton(t("Excluir"))
        self.remove_btn.setToolTip(
            t("Exclui a camada selecionada. A camada núcleo não pode ser excluída.")
        )

        self.up_btn = QToolButton()
        self.up_btn.setText("↑")
        self.up_btn.setToolTip(t("Move a camada para cima na composição."))

        self.down_btn = QToolButton()
        self.down_btn.setText("↓")
        self.down_btn.setToolTip(t("Move a camada para baixo na composição."))

        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.duplicate_btn)
        toolbar.addWidget(self.remove_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self.up_btn)
        toolbar.addWidget(self.down_btn)
        root.addLayout(toolbar)

        self.total = QLabel()
        self.total.setStyleSheet("color:#666;")
        root.addWidget(self.total)

        self.add_btn.clicked.connect(self._add)
        self.duplicate_btn.clicked.connect(self._duplicate)
        self.remove_btn.clicked.connect(self._remove)
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(1))

        self._refresh(select=core_index(self._layers))

    def _open_floating_editor(self):
        """Open a roomy live-linked copy of this editor.

        Reparenting the sidebar widget itself would disturb Qt's dock layout,
        so the floating window uses a second editor and mirrors every change
        back immediately.  Closing it leaves the sidebar exactly where it was.
        """
        dlg = QDialog(self.window())
        dlg.setWindowTitle(t("Compositor de camadas"))
        dlg.resize(920, 520)
        lay = QVBoxLayout(dlg)
        ed = LayerEditor(dlg, before_label=self.before_label, after_label=self.after_label)
        ed.table.setMaximumHeight(16777215)
        ed.table.setMinimumHeight(330)
        ed.set_material_names(self._material_names)
        ed.set_layers(self.layers())
        syncing = {"busy": False}
        def from_float():
            if syncing["busy"]:
                return
            syncing["busy"] = True
            try:
                self.set_layers(ed.layers())
                self.changed.emit()
            finally:
                syncing["busy"] = False
        ed.changed.connect(from_float)
        lay.addWidget(ed)
        close = QPushButton(t("Fechar"), dlg)
        close.clicked.connect(dlg.close)
        lay.addWidget(close)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        # Keep a Python reference until Qt destroys the dialog.
        self._floating_editor = dlg

    def _refresh_compositions(self, selected=None):
        try:
            from .composition_library import load_compositions
            data = load_compositions()
        except Exception:
            data = {}
        old = self.composition_combo.blockSignals(True)
        self.composition_combo.clear()
        self.composition_combo.addItem(t("Composição…"), "")
        for name in sorted(data, key=str.casefold):
            self.composition_combo.addItem(name, name)
        if selected:
            idx = self.composition_combo.findData(selected)
            if idx >= 0:
                self.composition_combo.setCurrentIndex(idx)
        self.composition_combo.blockSignals(old)
        try:
            from .composition_library import is_personal_composition
            self.composition_delete_btn.setEnabled(is_personal_composition(self.composition_combo.currentData()))
        except Exception:
            self.composition_delete_btn.setEnabled(bool(self.composition_combo.currentData()))

    def _apply_composition(self, _index):
        name = self.composition_combo.currentData()
        try:
            from .composition_library import is_personal_composition
            self.composition_delete_btn.setEnabled(is_personal_composition(name))
        except Exception:
            self.composition_delete_btn.setEnabled(bool(name))
        if not name:
            return
        try:
            from .composition_library import load_compositions
            layers = load_compositions().get(str(name))
            if not layers:
                return
            self._layers = normalize_layers(copy.deepcopy(layers))
            self._refresh(select=core_index(self._layers))
            self.changed.emit()
        except Exception as exc:
            QMessageBox.warning(self, t("Composições"), str(exc))

    def _save_composition(self):
        default = str(self.composition_combo.currentData() or "")
        name, ok = QInputDialog.getText(self, t("Salvar composição"),
                                        t("Nome da composição:"), text=default)
        if not ok or not str(name).strip():
            return
        try:
            from .composition_library import put_composition
            final = put_composition(str(name).strip(), self.layers())
            self._refresh_compositions(final)
        except Exception as exc:
            QMessageBox.warning(self, t("Composições"), str(exc))

    def _delete_composition(self):
        name = self.composition_combo.currentData()
        if not name:
            return
        answer = QMessageBox.question(
            self, t("Excluir composição"),
            t(f"Excluir a composição '{name}' da biblioteca pessoal?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            from .composition_library import remove_composition
            remove_composition(str(name))
            self._refresh_compositions()
        except Exception as exc:
            QMessageBox.warning(self, t("Composições"), str(exc))

    # ------------------------------------------------------------------
    # Public API consumed by WallController / SlabController
    # ------------------------------------------------------------------
    def set_material_names(self, names):
        clean = []
        seen = set()
        for raw in names or []:
            name = str(raw).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            clean.append(name)
        # Scene refreshes are frequent. Rebuilding every cell widget when the
        # available library did not change could both stutter and reset a combo
        # while the user was choosing a different layer material.
        if clean == self._material_names:
            return
        self._material_names = clean
        self._refresh(select=self._current_row())

    def user_is_editing(self):
        """True while focus is inside this editor.

        Parent controllers rebuild geometry after a layer edit.  This guard
        prevents that echo refresh from destroying the active table editor.
        """
        focus = QApplication.focusWidget()
        return focus is not None and (focus is self or self.isAncestorOf(focus))

    def set_layers(self, layers, core_thickness=0.10, material_name=None):
        previous = self._selection_hint
        incoming = normalize_layers(
            copy.deepcopy(layers), core_thickness, material_name
        )
        same_ids = (
            [x.get("id") for x in incoming]
            == [x.get("id") for x in self._layers]
        )

        if same_ids and self.user_is_editing():
            # Keep active cell widgets/focus alive while accepting the scene
            # rebuild's authoritative normalized copy.
            self._layers = incoming
            self._update_total()
            self._update_toolbar()
            return

        self._layers = incoming
        if previous is None or previous < 0:
            previous = core_index(self._layers)
        self._refresh(
            select=min(previous, max(0, len(self._layers) - 1))
        )

    def layers(self):
        return copy.deepcopy(self._layers)

    # ------------------------------------------------------------------
    # Table creation / synchronization
    # ------------------------------------------------------------------
    def _current_row(self):
        row = self.table.currentRow()
        return row if 0 <= row < len(self._layers) else -1

    def _index_for_id(self, layer_id):
        sid = str(layer_id)
        for i, layer in enumerate(self._layers):
            if str(layer.get("id")) == sid:
                return i
        return -1

    def _function_combo(self, layer):
        combo = QComboBox(self.table)
        for code, label in FUNCTION_CHOICES:
            combo.addItem(t(label), code)
        idx = combo.findData(layer.get("function"))
        combo.setCurrentIndex(idx if idx >= 0 else combo.findData("other"))
        combo.setToolTip(t("Função construtiva/BIM desta camada."))
        layer_id = str(layer["id"])
        combo.currentIndexChanged.connect(
            lambda _i, lid=layer_id, w=combo: self._function_changed(lid, w)
        )
        return combo

    def _material_combo(self, layer):
        combo = QComboBox(self.table)
        combo.addItem(t("Padrão"), None)

        current = layer.get("material_name")
        names = list(self._material_names)

        # Imported presets may reference a material not currently loaded in
        # the scene. Preserve that reference instead of silently replacing it.
        if current not in (None, "") and current not in names:
            combo.addItem(f"{current} ({t('não encontrado')})", current)

        for name in names:
            combo.addItem(name, name)

        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.setToolTip(t("Material físico associado à camada."))
        layer_id = str(layer["id"])
        combo.currentIndexChanged.connect(
            lambda _i, lid=layer_id, w=combo: self._material_changed(lid, w)
        )
        return combo

    def _thickness_spin(self, layer):
        spin = QDoubleSpinBox(self.table)
        spin.setLocale(ui_locale())
        spin.setDecimals(4)
        spin.setRange(0.001, 10000.0)
        spin.setSingleStep(0.005)
        spin.setSuffix(" m")
        spin.setKeyboardTracking(False)
        spin.setValue(float(layer["thickness"]))
        spin.setToolTip(t("Espessura física da camada."))
        layer_id = str(layer["id"])
        spin.valueChanged.connect(
            lambda value, lid=layer_id: self._thickness_changed(lid, value)
        )
        return spin

    def _core_button(self, layer):
        button = QToolButton(self.table)
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setChecked(layer.get("role") == "core")
        button.setText("●" if button.isChecked() else "○")
        button.setToolTip(
            t(
                "Define esta camada como núcleo geométrico/de referência. "
                "Selecionar outra transfere o núcleo para ela."
            )
        )
        layer_id = str(layer["id"])
        button.clicked.connect(
            lambda _checked, lid=layer_id: self._set_core(lid)
        )
        return button

    def _refresh(self, select=None):
        self._loading = True
        try:
            if select is None:
                select = self._current_row()
            if select is None or select < 0:
                select = core_index(self._layers)

            self.table.clearContents()
            self.table.setRowCount(len(self._layers))

            for row, layer in enumerate(self._layers):
                name = QTableWidgetItem(
                    str(layer.get("name") or t("Camada"))
                )
                name.setData(Qt.UserRole, str(layer["id"]))
                name.setToolTip(
                    t("Nome livre. Ex.: Reboco externo, Bloco cerâmico, Manta.")
                )
                self.table.setItem(row, self.COL_NAME, name)
                self.table.setCellWidget(
                    row, self.COL_FUNCTION, self._function_combo(layer)
                )
                self.table.setCellWidget(
                    row, self.COL_MATERIAL, self._material_combo(layer)
                )
                self.table.setCellWidget(
                    row, self.COL_THICKNESS, self._thickness_spin(layer)
                )
                self.table.setCellWidget(
                    row, self.COL_CORE, self._core_button(layer)
                )

            if self._layers:
                row = max(0, min(int(select), len(self._layers) - 1))
                self.table.setCurrentCell(row, self.COL_NAME)
                self._selection_hint = row

            self._update_total()
            self._update_toolbar()
        finally:
            self._loading = False

    def _update_total(self):
        total = ui_locale().toString(
            total_thickness(self._layers), "f", 4
        )
        count = len(self._layers)
        noun = t("camada") if count == 1 else t("camadas")
        self.total.setText(
            f"{t('Espessura total')}: {total} m  ·  {count} {noun}"
        )

    def _update_toolbar(self):
        row = self._current_row()
        valid = 0 <= row < len(self._layers)
        is_core = valid and self._layers[row].get("role") == "core"

        self.duplicate_btn.setEnabled(valid)
        self.remove_btn.setEnabled(valid and not is_core)
        self.up_btn.setEnabled(valid and row > 0)
        self.down_btn.setEnabled(valid and row < len(self._layers) - 1)

    # ------------------------------------------------------------------
    # Direct cell edits
    # ------------------------------------------------------------------
    def _current_cell_changed(self, row, _col, _previous_row, _previous_col):
        if self._loading:
            return
        if 0 <= row < len(self._layers):
            self._selection_hint = row
        self._update_toolbar()

    def _item_changed(self, item):
        if self._loading or item.column() != self.COL_NAME:
            return
        layer_id = item.data(Qt.UserRole)
        row = self._index_for_id(layer_id)
        if row < 0:
            return

        name = " ".join(str(item.text() or "").split())
        if not name:
            name = t("Núcleo") if self._layers[row].get("role") == "core" else t("Camada")

        if item.text() != name:
            self._loading = True
            try:
                item.setText(name)
            finally:
                self._loading = False

        if self._layers[row].get("name") == name:
            return
        self._layers[row]["name"] = name
        self.changed.emit()

    def _function_changed(self, layer_id, combo):
        if self._loading:
            return
        row = self._index_for_id(layer_id)
        if row < 0:
            return
        value = combo.currentData() or "other"
        if self._layers[row].get("function") == value:
            return
        self._layers[row]["function"] = value
        self.changed.emit()

    def _material_changed(self, layer_id, combo):
        if self._loading:
            return
        row = self._index_for_id(layer_id)
        if row < 0:
            return
        value = combo.currentData()
        if self._layers[row].get("material_name") == value:
            return
        self._layers[row]["material_name"] = value
        self.changed.emit()

    def _thickness_changed(self, layer_id, value):
        if self._loading:
            return
        row = self._index_for_id(layer_id)
        if row < 0:
            return
        value = float(value)
        if abs(float(self._layers[row]["thickness"]) - value) <= 1e-12:
            return
        self._layers[row]["thickness"] = value
        self._update_total()
        self.changed.emit()

    def _set_core(self, layer_id):
        if self._loading:
            return
        row = self._index_for_id(layer_id)
        if row < 0:
            return
        if self._layers[row].get("role") == "core":
            # One core must always exist; clicking the current core does not
            # turn it off.
            self._refresh(select=row)
            return

        for i, layer in enumerate(self._layers):
            layer["role"] = "core" if i == row else "finish"
        self._refresh(select=row)
        self.changed.emit()

    # ------------------------------------------------------------------
    # Stack operations
    # ------------------------------------------------------------------
    def _add(self):
        row = self._current_row()
        if row < 0:
            row = core_index(self._layers)

        idx = min(len(self._layers), row + 1)
        layer = finish_layer(
            0.02,
            None,
            t("Nova camada"),
            function="finish",
        )
        self._layers.insert(idx, layer)
        self._refresh(select=idx)
        self.changed.emit()

    def _duplicate(self):
        row = self._current_row()
        if row < 0:
            return

        source = self._layers[row]
        layer = finish_layer(
            float(source["thickness"]),
            source.get("material_name"),
            f"{source.get('name') or t('Camada')} ({t('cópia')})",
            function=source.get("function") or "other",
        )
        idx = row + 1
        self._layers.insert(idx, layer)
        self._refresh(select=idx)
        self.changed.emit()

    def _remove(self):
        row = self._current_row()
        if row < 0 or row >= len(self._layers):
            return
        if self._layers[row].get("role") == "core":
            return

        del self._layers[row]
        self._refresh(select=min(row, len(self._layers) - 1))
        self.changed.emit()

    def _move(self, delta):
        row = self._current_row()
        if row < 0:
            return
        target = row + int(delta)
        if target < 0 or target >= len(self._layers):
            return

        self._layers[row], self._layers[target] = (
            self._layers[target],
            self._layers[row],
        )
        self._refresh(select=target)
        self.changed.emit()
