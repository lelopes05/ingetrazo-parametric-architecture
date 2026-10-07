# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive drawing and architectural control editing for OpenTrace membranes."""
from __future__ import annotations

import copy
import math
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from tools.base import AxisMagnet, Tool

from .membrane_model import (
    CreateMembrane, EditMembrane, MembraneError, chamfer_boundary,
    insert_boundary_vertex, make_membrane, read_membrane, boundary_edge_polyline, surface_uv,
)
from .preview_utils import group_faces_world, hide_original_for_preview, restore_original_after_preview


def _screen_segment_projection(px, py, a, b):
    ax, ay = a; bx, by = b
    dx, dy = bx-ax, by-ay
    den = dx*dx + dy*dy
    if den <= 1e-12:
        return math.hypot(px-ax, py-ay), 0.0
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / den))
    qx, qy = ax + dx*t, ay + dy*t
    return math.hypot(px-qx, py-qy), t


class MembraneDrawTool(AxisMagnet, Tool):
    name = "Desenhar membrana"
    description = "Desenhar contorno de membrana."
    uses_snap = True
    architecture_angle_snap = True
    wireframe_color = (0.18, 0.55, 0.90, 1.0)

    def __init__(self, controller):
        self.controller = controller
        self.mode = "polygon"
        self.reset()

    def reset(self):
        self.points = []
        self.hover = None
        self.start_point = None
        self.chain_first_point = None

    def set_mode(self, mode):
        self.mode = mode if mode in ("polygon", "rectangle", "ellipse") else "polygon"
        self.reset()

    def on_activate(self, viewport):
        self.reset()
        self.controller.message({
            "polygon": "Polígono: clique os vértices e clique no primeiro para fechar.",
            "rectangle": "Retângulo: clique dois cantos opostos.",
            "ellipse": "Elipse: clique o centro e depois um canto da caixa envolvente.",
        }[self.mode])
        viewport.update()

    def on_deactivate(self, viewport):
        self.reset(); viewport.update()

    def drag_plane(self, viewport):
        z = self.controller.reference_z()
        return QVector3D(0, 0, z), QVector3D(0, 0, 1)

    def _point(self, ctx):
        return QVector3D(ctx.world.x(), ctx.world.y(), self.controller.reference_z())

    def _near_first(self, viewport, screen):
        if len(self.points) < 3:
            return False
        p = viewport._world_to_pixel(self.points[0])
        if p is None:
            return False
        th = max(8.0, float(getattr(viewport, "snap_threshold_px", 10.0)))
        return ((float(screen.x())-p[0])**2 + (float(screen.y())-p[1])**2 <= th*th)

    def _shape(self, hover=None):
        q = QVector3D(hover if hover is not None else self.hover) if (hover is not None or self.hover is not None) else None
        if self.mode == "rectangle" and self.points and q is not None:
            a = self.points[0]
            return [QVector3D(a.x(), a.y(), a.z()), QVector3D(q.x(), a.y(), a.z()),
                    QVector3D(q.x(), q.y(), a.z()), QVector3D(a.x(), q.y(), a.z())]
        if self.mode == "ellipse" and self.points and q is not None:
            c = self.points[0]
            rx, ry = abs(q.x()-c.x()), abs(q.y()-c.y())
            if max(rx, ry) < 1e-6:
                return None
            return [QVector3D(c.x()+rx*math.cos(2*math.pi*i/32),
                              c.y()+ry*math.sin(2*math.pi*i/32), c.z()) for i in range(32)]
        if self.mode == "polygon" and len(self.points) >= 3:
            return list(self.points)
        return None

    def on_hover(self, ctx):
        self.hover = self._point(ctx)
        self.start_point = QVector3D(self.points[-1]) if self.points else None
        self.chain_first_point = QVector3D(self.points[0]) if len(self.points) > 1 else None
        ctx.viewport.update()

    def on_click(self, ctx):
        p = self._point(ctx)
        try:
            if not self.points:
                self.points = [p]
                self.start_point = QVector3D(p)
                self.hover = p
                self.controller.message("Defina o próximo ponto.")
                ctx.viewport.update(); return
            if self.mode in ("rectangle", "ellipse"):
                shape = self._shape(p)
                if not shape:
                    raise MembraneError("Indique um segundo ponto diferente do primeiro.")
                self._commit(ctx.viewport, shape); return
            if ((ctx.snap is not None and getattr(ctx.snap, "kind", None) == "close")
                    or self._near_first(ctx.viewport, ctx.screen)):
                self._commit(ctx.viewport, self.points); return
            if (p-self.points[-1]).length() < 1e-6:
                raise MembraneError("Indique um vértice diferente do anterior.")
            self.points.append(p)
            self.start_point = QVector3D(p)
            self.chain_first_point = QVector3D(self.points[0])
            self.controller.message("Continue o polígono ou clique no primeiro vértice para fechar.")
        except Exception as exc:
            self.controller.message(str(exc), True)
        ctx.viewport.update()

    def _commit(self, viewport, boundary):
        group = make_membrane(boundary, self.controller.values())
        from .bim import ensure_ifc_identity
        ensure_ifc_identity(group, "IfcBuildingElementProxy", name="Membrana")
        viewport.history.execute(CreateMembrane(group))
        if viewport.history.last_error:
            raise MembraneError(viewport.history.last_error)
        viewport.scene.clear_selection(); viewport.scene.selection.add(group)
        viewport.notify_scene_changed(); self.reset()
        self.controller.message("Membrana criada. Clique para iniciar outra ou Esc para sair.")

    def on_cancel(self, viewport):
        if self.points:
            self.reset(); viewport.update()
            self.controller.message("Desenho cancelado. Clique para iniciar outra membrana.")
        else:
            self.controller.return_to_select()

    def rubber_band_lines(self):
        shape = self._shape()
        if shape is not None and self.mode in ("rectangle", "ellipse"):
            return list(zip(shape, shape[1:] + shape[:1]))
        pts = list(self.points)
        if self.hover is not None:
            pts.append(self.hover)
        return list(zip(pts, pts[1:]))

    def preview_faces(self):
        shape = self._shape()
        if shape is None:
            return []
        try:
            return group_faces_world(make_membrane(shape, self.controller.values()))
        except Exception:
            return []


class MembraneEditTool(AxisMagnet, Tool):
    name = "Editar membrana"
    description = "Editar vértices, arestas e pontos internos da membrana."
    uses_snap = True
    architecture_angle_snap = True
    wireframe_color = (0.18, 0.55, 0.90, 1.0)

    def __init__(self, controller):
        self.controller = controller
        self.reset()

    def reset(self):
        self.group = None
        self.boundary = []
        self.values = None
        self.kind = None
        self.index = None
        self.action = None
        self.anchor = None
        self.start_point = None
        self.hover = None
        self._preview_hidden = None
        self._candidate_boundary = None
        self._candidate_values = None
        self.edge_t = None

    def prepare(self, group):
        self.reset(); self.group = group

    def sync_from_group(self):
        """Refresh control overlays after external undo/redo while editing."""
        if self.group is None or self.action is not None:
            return
        try:
            self.boundary, self.values = read_membrane(self.group)
        except Exception:
            return

    def on_activate(self, viewport):
        if self.group is None or self.group not in viewport.scene.groups:
            QTimer.singleShot(0, self.controller.return_to_select); return
        try:
            self.boundary, self.values = read_membrane(self.group)
            self.controller.message("Clique em um vértice, aresta, ponto interno ou na pele para abrir a paleta contextual.")
        except Exception as exc:
            self.controller.message(str(exc), True)
            QTimer.singleShot(0, self.controller.return_to_select)
        viewport.update()

    def on_deactivate(self, viewport):
        self._show_original(); self.controller.hide_context_palette(); self.reset(); viewport.update()

    def _show_original(self):
        if self.group is not None and self._preview_hidden is not None:
            restore_original_after_preview(self.group, self._preview_hidden)
        self._preview_hidden = None

    def _hide_original(self):
        if self.group is not None and self._preview_hidden is None:
            self._preview_hidden = hide_original_for_preview(self.group)

    def _mesh_points(self):
        return list((self.values or {}).get("mesh_points", ()) or ())

    def _pick(self, viewport, screen):
        px, py = float(screen.x()), float(screen.y())
        th = max(10.0, float(getattr(viewport, "snap_threshold_px", 10.0))*1.15)

        # User-created internal control vertices win over the skin beneath.
        mpts = self._mesh_points()
        mpix = [viewport._world_to_pixel(p) for p in mpts]
        bestm = None
        for i, q in enumerate(mpix):
            if q is None: continue
            d = math.hypot(px-q[0], py-q[1])
            if d <= th and (bestm is None or d < bestm[0]): bestm = (d, i)
        if bestm:
            i = bestm[1]
            return "mesh_vertex", i, QVector3D(mpts[i]), None

        pixels = [viewport._world_to_pixel(p) for p in self.boundary]
        bestv = None
        for i, q in enumerate(pixels):
            if q is None: continue
            d = math.hypot(px-q[0], py-q[1])
            if d <= th and (bestv is None or d < bestv[0]): bestv = (d, i)
        if bestv:
            return "vertex", bestv[1], QVector3D(self.boundary[bestv[1]]), None

        # Pick the *actual curved border*, not the straight chord between
        # control vertices.  Besides feeling correct, this gives insertion the
        # real curve parameter so adding a vertex does not flatten the edge.
        beste = None
        for i in range(len(self.boundary)):
            poly = boundary_edge_polyline(self.boundary, self.values, i)
            pp = [viewport._world_to_pixel(q) for q in poly]
            segs = max(1, len(poly)-1)
            for j in range(segs):
                a,b=pp[j],pp[j+1]
                if a is None or b is None: continue
                d, lt = _screen_segment_projection(px, py, a, b)
                if d <= th and (beste is None or d < beste[0]):
                    t=(j+lt)/float(segs)
                    anchor=poly[j]*(1.0-lt)+poly[j+1]*lt
                    beste=(d,i,t,QVector3D(anchor))
        if beste:
            _,i,t,anchor=beste
            return "edge", i, anchor, t
        return None

    def _picked_own_surface(self, viewport, screen):
        try:
            face, grp = viewport.pick_face_placement(float(screen.x()), float(screen.y()))
            if face is None:
                return False
            owner = getattr(grp, "owner", None) or grp
            return owner is self.group or grp is self.group
        except Exception:
            return False

    def choose_action(self, action):
        self.controller.hide_context_palette()
        self.action = action
        self._candidate_boundary = [QVector3D(q) for q in self.boundary]
        self._candidate_values = copy.deepcopy(self.values)
        if self.kind == "vertex":
            self.anchor = QVector3D(self.boundary[self.index])
        elif self.kind == "edge":
            # Preserve the exact clicked point on the edge, not its midpoint.
            self.anchor = QVector3D(self.anchor)
        elif self.kind == "mesh_vertex":
            self.anchor = QVector3D(self._mesh_points()[self.index])
        self.start_point = QVector3D(self.anchor)
        self.hover = QVector3D(self.anchor)
        self._hide_original()
        self.controller.message({
            "move_vertex": "Mova o vértice e clique. Shift trava a inferência ativa.",
            "move_mesh_vertex": "Mova o ponto da malha e clique. Shift trava a inferência ativa.",
            "move_edge": "Mova a aresta e clique. Shift trava a inferência ativa.",
            "curve_h": "Puxe a aresta horizontalmente e clique.",
            "curve_v": "Puxe a aresta na vertical e clique.",
        }.get(action, "Edite e clique para confirmar."))
        self.controller.app.viewport.update()

    def drag_plane(self, viewport):
        if self.anchor is None:
            return None
        if self.action == "curve_h":
            return QVector3D(0, 0, self.anchor.z()), QVector3D(0, 0, 1)
        # Free 3D edit on a camera-facing plane; host X/Y/Z inference and Shift
        # can still project/lock the motion to a detected axis.
        return QVector3D(self.anchor), QVector3D(viewport.camera.forward())

    def _update_candidate(self, world):
        if self.action is None:
            return
        q = QVector3D(world)
        b = [QVector3D(x) for x in self.boundary]
        v = copy.deepcopy(self.values)
        n, i = len(b), self.index
        if self.action == "move_vertex":
            b[i] = q
        elif self.action == "move_mesh_vertex":
            pts = [QVector3D(x) for x in v.get("mesh_points", ())]
            if 0 <= i < len(pts):
                pts[i] = q
            v["mesh_points"] = pts
        elif self.action == "move_edge":
            d = q - self.anchor
            b[i] += d; b[(i+1) % n] += d
        elif self.action == "curve_h":
            a, c = b[i], b[(i+1) % n]
            d = c-a; L = math.hypot(d.x(), d.y()); mid = (a+c)*.5
            sag = 0.0 if L < 1e-9 else ((q.x()-mid.x())*(-d.y()/L) + (q.y()-mid.y())*(d.x()/L))
            v["edge_curve_h"][i] = float(sag)
        elif self.action == "curve_v":
            v["edge_curve_v"][i] = float(q.z()-self.anchor.z())
        self._candidate_boundary, self._candidate_values = b, v

    def on_hover(self, ctx):
        if self.action is not None:
            self.hover = QVector3D(ctx.world)
            self._update_candidate(ctx.world)
            ctx.viewport.update()

    def preview_faces(self):
        if self.action is None or self._candidate_boundary is None:
            return []
        try:
            return group_faces_world(make_membrane(self._candidate_boundary, self._candidate_values, template=self.group))
        except Exception:
            return []

    def on_click(self, ctx):
        if self.action is None:
            hit = self._pick(ctx.viewport, ctx.screen)
            if hit is not None:
                self.kind, self.index, self.anchor, self.edge_t = hit
                self.controller.show_context_palette(ctx.screen, self.kind, self.index)
                return
            if self._picked_own_surface(ctx.viewport, ctx.screen):
                self.kind, self.index, self.anchor, self.edge_t = "surface", None, QVector3D(ctx.world), None
                self.controller.show_context_palette(ctx.screen, self.kind, self.index)
                return
            self.controller.message("Clique mais perto de um controle ou diretamente sobre a pele.", True)
            return
        try:
            self._update_candidate(ctx.world)
            self._commit(ctx.viewport, self._candidate_boundary, self._candidate_values)
        except Exception as exc:
            self.controller.message(str(exc), True)

    def _commit(self, viewport, boundary, values):
        self._show_original()
        viewport.history.execute(EditMembrane(self.group, values, boundary=boundary))
        if viewport.history.last_error:
            raise MembraneError(viewport.history.last_error)
        viewport.notify_scene_changed()
        self.boundary, self.values = read_membrane(self.group)
        self.action = self.kind = self.index = self.anchor = self.start_point = None
        self.edge_t = None
        self._candidate_boundary = self._candidate_values = None
        self.controller.message("Membrana atualizada. Clique em outro controle.")
        viewport.update()

    def toggle_edge_state(self):
        if self.kind != "edge":
            return
        vals = copy.deepcopy(self.values)
        i = self.index
        vals["edge_modes"][i] = "tensioned" if vals["edge_modes"][i] == "rigid" else "rigid"
        # Manual edge curves belong to rigid edges. When it becomes tensioned,
        # the cable shape is generated by the tension model instead.
        if vals["edge_modes"][i] == "tensioned":
            vals["edge_curve_h"][i] = 0.0
            vals["edge_curve_v"][i] = 0.0
        try:
            self.controller.hide_context_palette()
            self._commit(self.controller.app.viewport, self.boundary, vals)
        except Exception as exc:
            self.controller.message(str(exc), True)

    def curve_action(self, axis):
        if self.kind != "edge":
            return
        if self.values.get("mode") == "tensioned" and self.values["edge_modes"][self.index] != "rigid":
            self.controller.hide_context_palette()
            self.controller.message("Para curvar manualmente esta borda, marque-a primeiro como Rígida; bordas Tensionadas assumem a forma da pele.", True)
            return
        self.choose_action("curve_h" if axis == "h" else "curve_v")

    def insert_edge_vertex(self):
        if self.kind != "edge":
            return
        try:
            b, vals = insert_boundary_vertex(self.boundary, self.values, self.index, self.anchor, t=self.edge_t)
            self.controller.hide_context_palette()
            self._commit(self.controller.app.viewport, b, vals)
        except Exception as exc:
            self.controller.message(str(exc), True)

    def add_surface_vertex(self):
        if self.kind != "surface" or self.anchor is None:
            return
        try:
            vals = copy.deepcopy(self.values)
            pts = [QVector3D(q) for q in vals.get("mesh_points", ())]
            uvs = [list(x) for x in vals.get("mesh_uvs", ())]
            uv = surface_uv(self.boundary, vals, self.anchor)
            if uv is None:
                raise MembraneError("Pontos internos editáveis estão disponíveis em membranas de quatro bordas nesta versão.")
            pts.append(QVector3D(self.anchor)); uvs.append(list(uv))
            vals["mesh_points"] = pts; vals["mesh_uvs"] = uvs
            self.controller.hide_context_palette()
            self._commit(self.controller.app.viewport, self.boundary, vals)
        except Exception as exc:
            self.controller.message(str(exc), True)

    def delete_mesh_vertex(self):
        if self.kind != "mesh_vertex":
            return
        try:
            vals = copy.deepcopy(self.values)
            pts = [QVector3D(q) for q in vals.get("mesh_points", ())]
            uvs = [list(x) for x in vals.get("mesh_uvs", ())]
            if 0 <= self.index < len(pts):
                pts.pop(self.index)
                if self.index < len(uvs): uvs.pop(self.index)
            vals["mesh_points"] = pts; vals["mesh_uvs"] = uvs
            self.controller.hide_context_palette()
            self._commit(self.controller.app.viewport, self.boundary, vals)
        except Exception as exc:
            self.controller.message(str(exc), True)

    def chamfer(self, fillet=False):
        if self.kind != "vertex":
            return
        try:
            b = chamfer_boundary(self.boundary, self.index, .16, fillet=fillet)
            vals = copy.deepcopy(self.values)
            # Reconcile edge arrays after a topology change. Newly created
            # chamfer/fillet segments start rigid and neutral; existing mesh
            # control points are preserved.
            vals["edge_modes"] = ["rigid"] * len(b)
            vals["edge_curve_h"] = [0.0] * len(b)
            vals["edge_curve_v"] = [0.0] * len(b)
            self.controller.hide_context_palette()
            self._commit(self.controller.app.viewport, b, vals)
        except Exception as exc:
            self.controller.message(str(exc), True)

    def on_cancel(self, viewport):
        if self.action is not None:
            self._show_original()
            self.action = None
            self._candidate_boundary = self._candidate_values = None
            self.controller.message("Edição cancelada. Clique em outro controle.")
            viewport.update(); return
        self.controller.return_to_select()
