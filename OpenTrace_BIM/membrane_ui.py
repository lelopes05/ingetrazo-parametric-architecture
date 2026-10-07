# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenTrace Membrane workspace: a compact architectural control-surface UI."""
from __future__ import annotations

import copy
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QBrush, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QSpinBox, QToolButton,
    QVBoxLayout, QWidget,
)

from .membrane_model import (
    EditMembrane, MembraneError, read_membrane, selected_boundary,
    make_membrane, CreateMembrane, boundary_edge_polyline,
)
from .membrane_tool import MembraneDrawTool, MembraneEditTool
from .host import (
    MEMBRANE_DRAW_TOOL_KEY, MEMBRANE_EDIT_TOOL_KEY, activate_membrane_draw,
    activate_membrane_edit, activate_select, register_tool,
)
from .palette import RadialPalette
from .icons import set_symbol_icon
from .layer_ui import LayerEditor
from .materials import material_names
from .widgets import FlexibleDoubleSpinBox as QDoubleSpinBox


class MembraneController:
    def __init__(self, app, wall_controller=None):
        self.app = app
        self.wall_controller = wall_controller
        self.target = None
        self._loading = False
        self._auto_timer = QTimer()
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(90)
        self._auto_timer.timeout.connect(self.update_selected)
        self.dock = getattr(app.window, "_arquitetura_parametrica_master_dock", None)
        self.draw_tool = MembraneDrawTool(self)
        self.edit_tool = MembraneEditTool(self)
        register_tool(app, self.draw_tool, key=MEMBRANE_DRAW_TOOL_KEY)
        register_tool(app, self.edit_tool, key=MEMBRANE_EDIT_TOOL_KEY)
        self.panel = self._make_panel()
        self._make_context_palette()
        app.add_overlay(self._draw_overlay)
        try:
            app.viewport.sceneVersionChanged.connect(self._scene_changed)
        except Exception:
            pass
        self.refresh()

    def _scene_changed(self, *_):
        # History may swap the whole membrane mesh. Never keep obsolete overlay
        # coordinates after undo/redo.
        try:
            if self.app.viewport.active_tool is self.edit_tool:
                self.edit_tool.sync_from_group()
        except Exception:
            pass
        self.refresh()

    # ------------------------------------------------------------------
    # Overlay: the authoritative cage, not the triangulation
    # ------------------------------------------------------------------
    def _overlay_data(self, viewport):
        if viewport.active_tool is self.edit_tool and self.edit_tool.boundary:
            return list(self.edit_tool.boundary), self.edit_tool.values or {}
        g = self._selected_membrane()
        if g is not None:
            try:
                return read_membrane(g)
            except Exception:
                pass
        return None, None

    def _draw_overlay(self, viewport, painter):
        pts, vals = self._overlay_data(viewport)
        if not pts:
            return
        modes = list((vals or {}).get("edge_modes", ()))
        painter.setRenderHint(QPainter.Antialiasing, True)
        # Draw the actual sampled H/V curve, so a curved border never appears
        # as a straight editing chord.
        for i in range(len(pts)):
            try:
                poly = boundary_edge_polyline(pts, vals, i)
            except Exception:
                poly = [pts[i], pts[(i + 1) % len(pts)]]
            pp = [viewport._world_to_pixel(q) for q in poly]
            painter.setPen(QPen(QColor(45, 125, 235), 2.2, Qt.SolidLine, Qt.RoundCap))
            for a, b in zip(pp, pp[1:]):
                if a is not None and b is not None:
                    painter.drawLine(QPointF(*a), QPointF(*b))
        pixels = [viewport._world_to_pixel(p) for p in pts]
        painter.setPen(QPen(QColor(20, 20, 20), 1))
        painter.setBrush(QBrush(QColor(245, 245, 245)))
        for q in pixels:
            if q is not None:
                painter.drawEllipse(QPointF(*q), 4.5, 4.5)
        # Explicit user mesh controls are magenta. Generated smoothing vertices
        # remain invisible; the user edits the cage, not implementation detail.
        mp = list((vals or {}).get("mesh_points", ()) or ())
        painter.setPen(QPen(QColor(120, 20, 120), 1.4))
        painter.setBrush(QBrush(QColor(235, 85, 205)))
        for q in [viewport._world_to_pixel(x) for x in mp]:
            if q is not None:
                painter.drawEllipse(QPointF(*q), 5.0, 5.0)
        # Anchor loops (0.12.7 editor) are rendered already when present in an
        # imported/round-tripped file, even before their drawing tool is used.
        painter.setPen(QPen(QColor(245, 145, 20), 2.0, Qt.SolidLine, Qt.RoundCap))
        for loop in list((vals or {}).get("anchor_loops", ()) or ()):
            pp = [viewport._world_to_pixel(q) for q in loop]
            for a, b in zip(pp, pp[1:] + pp[:1]):
                if a is not None and b is not None:
                    painter.drawLine(QPointF(*a), QPointF(*b))

    # ------------------------------------------------------------------
    # Compact panel
    # ------------------------------------------------------------------
    def _tool_button(self, symbol, tip, callback, size=34):
        b = QToolButton()
        set_symbol_icon(b, symbol, 20)
        b.setToolTip(tip)
        b.setAutoRaise(False)
        b.setFixedSize(size, size)
        b.clicked.connect(callback)
        return b

    def _make_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        title = QLabel(
            "<b style='font-size:14pt'>Membrana</b><br>"
            "<span style='color:#777'>Superfície arquitetônica deformável; o contorno é a geometria de controle.</span>"
        )
        title.setWordWrap(True)
        lay.addWidget(title)

        draw = QHBoxLayout()
        draw.setSpacing(5)
        self.poly_btn = self._tool_button("◇", "Polígono: clique vértices e feche no primeiro.", lambda: self.start_draw("polygon"))
        self.rect_btn = self._tool_button("▭", "Retângulo por dois cantos.", lambda: self.start_draw("rectangle"))
        self.ellipse_btn = self._tool_button("◯", "Elipse: centro e caixa envolvente.", lambda: self.start_draw("ellipse"))
        self.from_edges_btn = self._tool_button("⌁", "Criar membrana do contorno de arestas selecionado.", self.create_from_edges)
        self.edit_btn = self._tool_button("✥", "Editar contorno, curvas e pontos da malha da membrana selecionada.", self.start_edit)
        for b in (self.poly_btn, self.rect_btn, self.ellipse_btn, self.from_edges_btn, self.edit_btn):
            draw.addWidget(b)
        draw.addStretch(1)
        lay.addLayout(draw)

        form = QFormLayout()
        lay.addLayout(form)
        self.mode = QComboBox()
        self.mode.addItem("Malha / smooth", "relaxed")
        self.mode.setToolTip("Superfície de controle: as bordas definem a forma e a pele interpola entre elas.")
        form.addRow("Comportamento", self.mode)
        self.div = QSpinBox()
        self.div.setRange(2, 20)
        self.div.setValue(5)
        self.div.setToolTip("Densidade/suavidade da pele gerada entre os controles.")
        form.addRow("Suavidade", self.div)
        self.tension = QDoubleSpinBox()
        self.tension.setDecimals(0); self.tension.setRange(0.0, 100.0); self.tension.setValue(0.0)
        self.tension.hide()  # compatibility field for old records; no solver in 0.12.7
        self.structure = QComboBox()
        self.structure.addItem("Superfície simples", "simple")
        self.structure.addItem("Composta / camadas", "composite")
        form.addRow("Estrutura", self.structure)
        self.thickness = QDoubleSpinBox()
        self.thickness.setDecimals(4)
        self.thickness.setRange(0.0, 100.0)
        self.thickness.setSingleStep(.01)
        self.thickness.setSuffix(" m")
        self.thickness.setValue(0.0)
        form.addRow("Espessura", self.thickness)

        self.layer_editor = LayerEditor(w, before_label="Lado A", after_label="Lado B")
        lay.addWidget(self.layer_editor)
        self.hint = QLabel(
            "A membrana nasce ao fechar o contorno. Selecione-a para ver a gaiola; ✥ entra na edição. "
            "As bordas azuis são a geometria de controle. Curvas H/V pertencem à própria borda e a pele permanece colada nelas."
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#666;")
        lay.addWidget(self.hint)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        lay.addWidget(self.feedback)
        lay.addStretch(1)

        self.mode.currentIndexChanged.connect(self._parameter_changed)
        self.div.valueChanged.connect(self._parameter_changed)
        self.tension.editingFinished.connect(self._parameter_changed)
        self.structure.currentIndexChanged.connect(self._structure_changed)
        self.thickness.editingFinished.connect(self._parameter_changed)
        self.layer_editor.changed.connect(self._parameter_changed)
        self._structure_changed()
        return w

    # ------------------------------------------------------------------
    # Context palette
    # ------------------------------------------------------------------
    def _make_context_palette(self):
        self.context_palette = RadialPalette(self.app.window, popup=False, role="edit")
        self.context_palette.setObjectName("opentrace_membrane_context_palette")
        self.context_kind = None
        self.context_index = None
        def btn(symbol, tip, cb):
            b = QToolButton(self.context_palette)
            set_symbol_icon(b, symbol, 20)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setFixedSize(36, 36)
            b.clicked.connect(cb)
            self.context_palette.row.addWidget(b)
            return b
        self.mv_vertex_btn = btn("✥", "Mover vértice livremente; Shift trava a inferência ativa.", lambda: self.edit_tool.choose_action("move_vertex"))
        self.chamfer_btn = btn("⌿", "Chanfrar o vértice.", lambda: self.edit_tool.chamfer(False))
        self.fillet_btn = btn("⌒", "Arredondar/fillet do vértice.", lambda: self.edit_tool.chamfer(True))
        self.mv_edge_btn = btn("↔", "Mover a aresta como um todo.", lambda: self.edit_tool.choose_action("move_edge"))
        self.curve_h_btn = btn("⌒", "Curvar a borda na horizontal/planta.", lambda: self.edit_tool.curve_action("h"))
        self.curve_v_btn = btn("∿", "Curvar a borda na vertical/elevação.", lambda: self.edit_tool.curve_action("v"))
        self.insert_edge_btn = btn("＋", "Adicionar vértice exatamente neste ponto da borda.", self.edit_tool.insert_edge_vertex)
        self.edge_state_btn = btn("◆", "Estado de borda reservado para uma futura membrana estrutural.", self.edit_tool.toggle_edge_state)
        self.edge_state_btn.hide()
        self.add_mesh_btn = btn("＋", "Adicionar um ponto de controle interno à pele.", self.edit_tool.add_surface_vertex)
        self.mv_mesh_btn = btn("✥", "Mover este ponto interno.", lambda: self.edit_tool.choose_action("move_mesh_vertex"))
        self.del_mesh_btn = btn("×", "Excluir este ponto interno.", self.edit_tool.delete_mesh_vertex)
        self.context_palette.hide()

    def show_context_palette(self, screen, kind, index):
        self.context_kind, self.context_index = kind, index
        isv, ise, ism, iss = kind == "vertex", kind == "edge", kind == "mesh_vertex", kind == "surface"
        for b in (self.mv_vertex_btn, self.chamfer_btn, self.fillet_btn): b.setVisible(isv)
        for b in (self.mv_edge_btn, self.curve_h_btn, self.curve_v_btn, self.insert_edge_btn): b.setVisible(ise)
        self.edge_state_btn.setVisible(False)
        self.add_mesh_btn.setVisible(iss)
        self.mv_mesh_btn.setVisible(ism); self.del_mesh_btn.setVisible(ism)
        if ise:
            try:
                state = self.edit_tool.values["edge_modes"][index]
                set_symbol_icon(self.edge_state_btn, "⌁" if state == "tensioned" else "◆", 20)
                self.edge_state_btn.setToolTip(
                    "Borda Tensionada — clique para tornar Rígida." if state == "tensioned"
                    else "Borda Rígida — clique para tornar Tensionada."
                )
            except Exception:
                pass
        pos = self.app.viewport.mapToGlobal(QPoint(int(screen.x()), int(screen.y())))
        self.context_palette.show_at(pos)

    def hide_context_palette(self):
        self.context_palette.hide()

    # ------------------------------------------------------------------
    # Parameters / selection
    # ------------------------------------------------------------------
    def _structure_changed(self, *_):
        composite = self.structure.currentData() == "composite"
        self.layer_editor.setVisible(composite)
        self.thickness.setEnabled(not composite)
        self.tension.setEnabled(False)
        self._parameter_changed()

    def _parameter_changed(self, *_):
        if self._loading:
            return
        self.tension.setEnabled(False)
        if self._selected_membrane() is not None:
            self._auto_timer.start()

    def values(self):
        structure = self.structure.currentData() or "simple"
        layers = self.layer_editor.layers() if structure == "composite" else []
        thickness = (sum(float(x.get("thickness", 0.0)) for x in layers)
                     if structure == "composite" else float(self.thickness.value()))
        return {
            "mode": self.mode.currentData() or "relaxed",
            "divisions": int(self.div.value()),
            "tension_strength": 0.0,
            "structure": structure,
            "thickness": thickness,
            "layers": layers,
        }

    def reference_z(self):
        try: return float(self.wall_controller.current_base_z())
        except Exception: return 0.0

    def return_to_select(self):
        activate_select(self.app)

    def message(self, text, error=False):
        self.feedback.setText(str(text))
        self.feedback.setStyleSheet("color:#b00020;" if error else "")
        try: self.app.viewport.flash_status(str(text), 8000 if error else 15000)
        except Exception: pass

    def _selected_membrane(self):
        found = []
        for item in list(getattr(self.app.scene, "selection", ()) or ()):
            g = getattr(item, "owner", None) or item
            if g in getattr(self.app.scene, "groups", ()) and g not in found:
                try: read_membrane(g); found.append(g)
                except Exception: pass
        return found[0] if len(found) == 1 else None

    def start_draw(self, mode):
        self.draw_tool.set_mode(mode)
        activate_membrane_draw(self.app)
        self.app.viewport.setFocus()

    def start_edit(self):
        g = self._selected_membrane()
        if g is None:
            self.message("Selecione uma única membrana OpenTrace para editar.", True)
            return
        self.edit_tool.prepare(g)
        activate_membrane_edit(self.app)
        self.app.viewport.setFocus()

    def create_from_edges(self):
        try:
            boundary = selected_boundary(self.app.scene)
            group = make_membrane(boundary, self.values())
            from .bim import ensure_ifc_identity
            ensure_ifc_identity(group, "IfcBuildingElementProxy", name="Membrana")
            self.app.viewport.history.execute(CreateMembrane(group))
            if self.app.viewport.history.last_error:
                raise MembraneError(self.app.viewport.history.last_error)
            self.app.scene.clear_selection(); self.app.scene.selection.add(group)
            self.app.viewport.notify_scene_changed()
            self.message("Membrana criada do contorno selecionado.")
        except Exception as exc:
            self.message(str(exc), True)

    def update_selected(self):
        if self._loading:
            return
        g = self._selected_membrane()
        if g is None:
            return
        try:
            boundary, old = read_membrane(g)
            vals = self.values()
            for k in ("edge_modes", "edge_curve_h", "edge_curve_v", "mesh_points", "mesh_uvs", "material_name"):
                vals[k] = copy.deepcopy(old.get(k))
            self.app.viewport.history.execute(EditMembrane(g, vals, boundary=boundary))
            if self.app.viewport.history.last_error:
                raise MembraneError(self.app.viewport.history.last_error)
            self.app.viewport.notify_scene_changed()
            self.message("Membrana atualizada.")
        except Exception as exc:
            self.message(str(exc), True)

    def refresh(self, *_):
        g = self._selected_membrane()
        self.target = g
        self.edit_btn.setEnabled(g is not None)
        try:
            self.layer_editor.set_material_names(material_names(self.app.scene))
        except Exception:
            pass
        if g is None:
            return
        try:
            _boundary, p = read_membrane(g)
            self._loading = True
            idx = self.mode.findData(p["mode"]); self.mode.setCurrentIndex(idx if idx >= 0 else 0)
            self.div.setValue(int(p["divisions"]))
            self.tension.setValue(float(p.get("tension_strength", .55)) * 100.0)
            si = self.structure.findData(p.get("structure", "simple")); self.structure.setCurrentIndex(si if si >= 0 else 0)
            self.thickness.setValue(float(p.get("thickness", 0.0)))
            self.layer_editor.set_layers(p.get("layers", []), max(.001, float(p.get("thickness", .01))), p.get("material_name"))
            composite = self.structure.currentData() == "composite"
            self.layer_editor.setVisible(composite); self.thickness.setEnabled(not composite)
            self.tension.setEnabled(False)
        except Exception:
            pass
        finally:
            self._loading = False
