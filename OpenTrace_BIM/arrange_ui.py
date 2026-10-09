# SPDX-License-Identifier: GPL-3.0-or-later
"""Dockable model-object alignment and equal-gap distribution.

Only complete top-level groups/components are moved. Loose faces/edges and
nested group-edit contexts intentionally require a different future workflow.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from .arrange_core import align_offsets, distribute_offsets

AXES = (("X — horizontal (vermelho)", 0),
        ("Y — horizontal (verde)", 1),
        ("Z — vertical (azul)", 2))


def _selected_groups(scene):
    from core.group import Group
    if getattr(scene, "edit_group", None) is not None:
        raise ValueError("Saia da edição interna do grupo antes de alinhar objetos.")
    selection = list(getattr(scene, "selection", ()) or ())
    if not selection:
        raise ValueError("Selecione ao menos dois objetos completos.")
    groups = []
    for selected in selection:
        group = getattr(selected, "owner", None) or selected
        if not isinstance(group, Group) or group not in scene.groups:
            raise ValueError("Esta versão alinha grupos/componentes completos, não faces ou arestas soltas.")
        if group not in groups:
            groups.append(group)
    return groups


def _bounds(group):
    from core.group import iter_placements
    lo = [float("inf")]*3
    hi = [float("-inf")]*3
    found = False
    for placed, matrix in iter_placements(group):
        for vertex in placed.mesh.vertices:
            pos = matrix.map(vertex.position) if matrix is not None else vertex.position
            for i, value in enumerate((pos.x(), pos.y(), pos.z())):
                lo[i] = min(lo[i], value)
                hi[i] = max(hi[i], value)
            found = True
    if not found:
        raise ValueError(f"O objeto {group.name!r} não contém geometria alinhável.")
    return tuple((lo[i], hi[i]) for i in range(3))


class ArrangePanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(9)
        layout.addWidget(QLabel("<b>Alinhar e distribuir</b>"))
        instructions = QLabel("Usa os limites geométricos dos objetos selecionados. "
                              "Eixos globais X, Y e Z.")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        top = QFrame(self)
        form = QFormLayout(top)
        self.axis = QComboBox(self)
        for name, index in AXES:
            self.axis.addItem(name, index)
        form.addRow("Eixo", self.axis)
        layout.addWidget(top)

        layout.addWidget(QLabel("<b>Alinhar</b>"))
        buttons = QHBoxLayout()
        for title, side, tip in (
            ("Início", "min", "Pelo menor limite do eixo"),
            ("Centro", "center", "Pelo centro geométrico"),
            ("Fim", "max", "Pelo maior limite do eixo"),
        ):
            button = QPushButton(title, self)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, s=side: self.apply("align", s))
            buttons.addWidget(button)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("<b>Distribuir</b>"))
        distribute = QPushButton("Espaços iguais", self)
        distribute.setToolTip("Mantém os extremos e iguala espaços livres entre as faces")
        distribute.clicked.connect(lambda: self.apply("distribute"))
        layout.addWidget(distribute)

        hint = QLabel("Distribuição requer 3+ objetos; extremos permanecem fixos. "
                      "Use Ctrl+Z para desfazer a operação inteira.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)
        try:
            app.viewport.sceneVersionChanged.connect(self.refresh)
        except Exception:
            pass
        self.refresh()

    def refresh(self, *_):
        count = len(getattr(self.app.scene, "selection", ()) or ())
        self.status.setText(f"Seleção: {count} item(ns).")

    def apply(self, operation, side="center"):
        from core.history import CompoundCommand, MoveGroupCommand
        viewport = self.app.viewport
        try:
            groups = _selected_groups(self.app.scene)
            box = [_bounds(g) for g in groups]
            axis = self.axis.currentData()
            if operation == "align":
                deltas = align_offsets(box, axis, side)
            elif operation == "distribute":
                deltas = distribute_offsets(box, axis)
            else:
                raise ValueError("Operação de alinhamento desconhecida.")
            commands = []
            for group, delta in zip(groups, deltas):
                if abs(delta) < 1.e-9:
                    continue
                xyz = [0.0, 0.0, 0.0]
                xyz[axis] = delta
                commands.append(MoveGroupCommand(group, QVector3D(*xyz)))
            if not commands:
                self.status.setText("Os objetos já estão alinhados/distribuídos.")
                return
            viewport.history.execute(CompoundCommand(commands))
            if viewport.history.last_error:
                raise RuntimeError(viewport.history.last_error)
            viewport.notify_scene_changed()
            viewport.update()
            self.status.setText(f"{len(commands)} objeto(s) reposicionado(s). Ctrl+Z desfaz.")
        except ValueError as exc:
            QMessageBox.information(self, "Alinhar e distribuir", str(exc))
        except Exception as exc:
            QMessageBox.warning(self, "Alinhar e distribuir",
                                f"Falha ao alinhar: {type(exc).__name__}: {exc}")
