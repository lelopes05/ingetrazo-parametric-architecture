# SPDX-License-Identifier: GPL-3.0-or-later
"""Compact reusable editor for parametric composite layers."""
from __future__ import annotations

import copy
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from .layers import finish_layer, normalize_layers, core_index, total_thickness
from .widgets import FlexibleDoubleSpinBox as QDoubleSpinBox
from .i18n import t, ui_locale


class LayerEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None, *, before_label="Exterior", after_label="Interior"):
        super().__init__(parent)
        self._loading=False; self._material_names=[]; self._selection_hint=None
        self.before_label=before_label; self.after_label=after_label
        lay=QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        self.list=QListWidget(); self.list.setMaximumHeight(130); self.list.currentRowChanged.connect(self._selection_changed); lay.addWidget(self.list)
        row=QHBoxLayout(); row.setContentsMargins(0,0,0,0)
        self.before=QPushButton(f"+ {t(before_label)}"); self.after=QPushButton(f"+ {t(after_label)}"); self.remove=QToolButton(); self.remove.setText("⌫"); self.remove.setToolTip(t("Excluir a camada selecionada. O núcleo não pode ser excluído."))
        self.before.clicked.connect(lambda:self._add(False)); self.after.clicked.connect(lambda:self._add(True)); self.remove.clicked.connect(self._remove)
        row.addWidget(self.before); row.addWidget(self.after); row.addWidget(self.remove); lay.addLayout(row)
        form=QFormLayout(); form.setContentsMargins(0,0,0,0)
        self.name=QLineEdit(); self.name.editingFinished.connect(self._field_changed); form.addRow(t("Nome"),self.name)
        self.thickness=QDoubleSpinBox(); self.thickness.setLocale(ui_locale()); self.thickness.setDecimals(4); self.thickness.setRange(0.001,10000.0); self.thickness.setSingleStep(0.01); self.thickness.setSuffix(" m"); self.thickness.setKeyboardTracking(False); self.thickness.valueChanged.connect(self._field_changed); form.addRow(t("Espessura"),self.thickness)
        self.material=QComboBox(); self.material.currentIndexChanged.connect(self._field_changed); form.addRow(t("Material"),self.material)
        lay.addLayout(form)
        self.total=QLabel(); self.total.setStyleSheet("color:#666;"); lay.addWidget(self.total)
        self._layers=normalize_layers(None)
        self._refresh()

    def set_material_names(self,names):
        self._material_names=list(names or [])
        current=self.material.currentData() if self.material.count() else None
        self.material.blockSignals(True); self.material.clear(); self.material.addItem(t("Padrão"),None)
        for name in self._material_names:self.material.addItem(name,name)
        i=self.material.findData(current); self.material.setCurrentIndex(i if i>=0 else 0); self.material.blockSignals(False)

    def user_is_editing(self):
        """True while keyboard/mouse focus is inside this editor.

        Parent controllers rebuild parametric geometry immediately after a layer
        edit.  That increments the scene version and causes their normal refresh
        pass.  Treating that refresh like a new selection used to recreate this
        whole widget while the spin box/combo still had focus, which made finish
        layers appear to refuse edits.
        """
        focus=QApplication.focusWidget()
        return focus is not None and (focus is self or self.isAncestorOf(focus))

    def set_layers(self,layers,core_thickness=0.10,material_name=None):
        previous=self._selection_hint
        incoming=normalize_layers(copy.deepcopy(layers),core_thickness,material_name)
        # A live scene rebuild may echo the very values the user has just
        # committed.  When it is the same layer stack and focus remains inside
        # the editor, update the model copy and labels in-place instead of
        # clearing/recreating QListWidget and resetting the active field.
        same_ids=([x.get("id") for x in incoming] == [x.get("id") for x in self._layers])
        if same_ids and self.user_is_editing():
            self._layers=incoming
            self._loading=True
            try:
                for i,x in enumerate(self._layers):
                    item=self.list.item(i)
                    if item is not None:item.setText(self._label(i,x))
                total=ui_locale().toString(total_thickness(self._layers), "f", 4)
                self.total.setText(f"{t('Espessura total')}: {total} m")
            finally:
                self._loading=False
            return
        self._layers=incoming
        if previous is None or previous < 0:
            previous=core_index(self._layers)
        self._refresh(select=min(previous,max(0,len(self._layers)-1)))

    def layers(self): return copy.deepcopy(self._layers)

    def _label(self,i,x):
        ci=core_index(self._layers)
        side=t(self.before_label if i<ci else self.after_label if i>ci else "Núcleo")
        mat=x.get("material_name") or t("Padrão")
        name=x.get("name","Camada")
        if name in ("Núcleo","Camada"): name=t(name)
        dim=ui_locale().toString(float(x["thickness"]), "f", 4)
        return f"{side} · {name} · {dim} m · {mat}"

    def _refresh(self,select=None):
        self._loading=True
        row=self.list.currentRow() if select is None else select
        self.list.clear()
        for i,x in enumerate(self._layers):self.list.addItem(self._label(i,x))
        if self._layers:self.list.setCurrentRow(max(0,min(row if row>=0 else core_index(self._layers),len(self._layers)-1)))
        total=ui_locale().toString(total_thickness(self._layers), "f", 4)
        self.total.setText(f"{t('Espessura total')}: {total} m")
        self._loading=False; self._selection_changed(self.list.currentRow())

    def _selection_changed(self,row):
        if row<0 or row>=len(self._layers):return
        self._selection_hint=row
        x=self._layers[row]; self._loading=True
        self.name.setText(x.get("name", "")); self.thickness.setValue(float(x["thickness"])); i=self.material.findData(x.get("material_name")); self.material.setCurrentIndex(i if i>=0 else 0); self.remove.setEnabled(x.get("role")!="core")
        self._loading=False

    def _field_changed(self,*_):
        if self._loading:return
        row=self.list.currentRow()
        if row<0 or row>=len(self._layers):return
        x=self._layers[row]
        x["name"]=self.name.text().strip() or (t("Núcleo") if x.get("role")=="core" else t("Camada"))
        x["thickness"]=float(self.thickness.value())
        x["material_name"]=self.material.currentData()
        # Do not rebuild the QListWidget while the user is editing a layer.
        # Recreating the list on every committed spin/combo change could move
        # focus/selection just as the parent controller rebuilt the wall/slab,
        # making freshly-added finish layers feel impossible to edit.  Update
        # only the selected row and total; the external scene refresh may later
        # call set_layers(), which preserves _selection_hint.
        item=self.list.item(row)
        if item is not None:item.setText(self._label(row,x))
        total=ui_locale().toString(total_thickness(self._layers), "f", 4)
        self.total.setText(f"{t('Espessura total')}: {total} m")
        self.changed.emit()

    def _add(self,after):
        ci=core_index(self._layers)
        # New layers are inserted next to the core on the chosen side. Existing
        # finish layers keep their physical order farther from the core.
        idx=ci+1 if after else ci
        name=t(self.after_label if after else self.before_label)+" 1"
        self._layers.insert(idx,finish_layer(0.02,None,name))
        self._refresh(select=idx); self.changed.emit()

    def _remove(self):
        row=self.list.currentRow()
        if row<0 or row>=len(self._layers) or self._layers[row].get("role")=="core":return
        del self._layers[row]; self._refresh(select=min(row,len(self._layers)-1)); self.changed.emit()