# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenTrace BIM project metadata and IFC export UI."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .bim import (ensure_spatial_ids, ifc_identity_data, load_document_data,
                  prepare_scene_identities, save_document_data, scan_scene,
                  set_ifc_metadata)
from .ifc_export import EXPORT_PROFILES, IfcExportError, export_ifc
from .ifc_import import IfcImportError, import_ifc


class BimController:
    def __init__(self, app):
        self.app = app
        self.action = None
        self.data = load_document_data(app)
        self._refresh_queued = False
        self.panel = self._build_panel()
        try:
            app.viewport.sceneVersionChanged.connect(self.schedule_refresh)
        except Exception:
            pass
        try:
            app.on_document_changed(self._document_changed)
        except Exception:
            pass
        self.refresh()

    def _build_panel(self):
        w = QWidget()
        root = QVBoxLayout(w); root.setContentsMargins(8, 8, 8, 8); root.setSpacing(9)
        title = QLabel("<b style='font-size:14pt'>BIM / IFC</b><br><span style='color:#777'>Semântica openBIM sobre a geometria paramétrica do OpenTrace.</span>")
        title.setWordWrap(True); root.addWidget(title)

        project_box = QFrame(); project_box.setFrameShape(QFrame.StyledPanel)
        form = QFormLayout(project_box); form.setContentsMargins(8, 8, 8, 8); form.setSpacing(6)
        self.project_name = QLineEdit(); self.site_name = QLineEdit(); self.building_name = QLineEdit()
        self.author = QLineEdit(); self.organization = QLineEdit(); self.description = QLineEdit()
        form.addRow("Projeto", self.project_name); form.addRow("Terreno", self.site_name)
        form.addRow("Edifício", self.building_name); form.addRow("Autor", self.author)
        form.addRow("Organização", self.organization); form.addRow("Descrição", self.description)
        root.addWidget(project_box)

        options = QFrame(); options.setFrameShape(QFrame.StyledPanel)
        opt = QVBoxLayout(options); opt.setContentsMargins(8, 8, 8, 8); opt.setSpacing(5)
        opt.addWidget(QLabel("<b>Conteúdo IFC4</b>"))
        profile_row=QHBoxLayout();profile_row.addWidget(QLabel("Perfil de exportação"))
        self.export_profile=QComboBox()
        for key,cfg in EXPORT_PROFILES.items():self.export_profile.addItem(cfg["label"],key)
        profile_row.addWidget(self.export_profile,1);opt.addLayout(profile_row)
        self.profile_hint=QLabel();self.profile_hint.setWordWrap(True);self.profile_hint.setStyleSheet("color:#777;");opt.addWidget(self.profile_hint)

        # Keep file I/O immediately next to the active export profile: the user
        # can always see which compatibility strategy will be used before
        # pressing Export. Open/Import/Link live here too so all IFC ingress /
        # egress is one compact block.
        io_row=QHBoxLayout()
        self.open_btn=QPushButton("Abrir IFC…");self.import_btn=QPushButton("Importar IFC…");self.link_btn=QPushButton("Vincular IFC…")
        io_row.addWidget(self.open_btn);io_row.addWidget(self.import_btn);io_row.addWidget(self.link_btn);opt.addLayout(io_row)
        export_row=QHBoxLayout()
        self.identify_btn=QPushButton("Preparar identidades IFC")
        self.export_btn=QPushButton("Exportar IFC…")
        export_row.addWidget(self.identify_btn);export_row.addWidget(self.export_btn);opt.addLayout(export_row)
        self.advanced_btn=QPushButton("BIM avançado · Psets · bibliotecas · relações · georreferenciamento…")
        opt.addWidget(self.advanced_btn)

        self.psets = QCheckBox("Property Sets IFC + paramétricos OpenTrace")
        self.layers = QCheckBox("Materiais e composições por IfcMaterialLayerSet")
        self.openings = QCheckBox("Aberturas como IfcOpeningElement + relação de vazio")
        self.quantities = QCheckBox("Quantidades IFC (Qto_*) + quantidades preservadas de importação")
        self.styles = QCheckBox("Aparências IFC de materiais (cor / transparência)")
        self.roundtrip = QCheckBox("Round-trip OpenTrace paramétrico dentro do IFC")
        self.repmaps = QCheckBox("RepresentationMap para instâncias/componentes repetidos")
        opt.addWidget(self.psets); opt.addWidget(self.layers); opt.addWidget(self.openings); opt.addWidget(self.quantities);opt.addWidget(self.styles);opt.addWidget(self.roundtrip);opt.addWidget(self.repmaps)
        root.addWidget(options)

        self.summary = QLabel(); self.summary.setWordWrap(True); self.summary.setStyleSheet("color:#555;")
        root.addWidget(self.summary)

        element_box = QFrame(); element_box.setFrameShape(QFrame.StyledPanel)
        element_form = QFormLayout(element_box); element_form.setContentsMargins(8, 8, 8, 8); element_form.setSpacing(6)
        element_form.addRow(QLabel("<b>Elemento selecionado</b>"))
        self.element_class = QLabel("—"); self.element_guid = QLabel("—")
        self.element_name = QLineEdit(); self.element_type = QLineEdit(); self.element_predefined = QComboBox()
        self.classification_system = QLineEdit(); self.classification_code = QLineEdit()
        self.common_reference = QLineEdit(); self.common_status = QComboBox()
        self.common_status.addItem("Não definido", None)
        for code, label in (("NEW", "Novo"), ("EXISTING", "Existente"), ("DEMOLISH", "Demolir"), ("TEMPORARY", "Temporário")):
            self.common_status.addItem(label, code)
        self.common_external = QComboBox(); self.common_loadbearing = QComboBox()
        for combo in (self.common_external, self.common_loadbearing):
            combo.addItem("Não definido", None); combo.addItem("Sim", True); combo.addItem("Não", False)
        self.common_fire = QLineEdit()
        element_form.addRow("Classe IFC", self.element_class); element_form.addRow("GlobalId", self.element_guid)
        element_form.addRow("Nome IFC", self.element_name); element_form.addRow("Tipo", self.element_type)
        element_form.addRow("PredefinedType", self.element_predefined)
        element_form.addRow("Classificação", self.classification_system); element_form.addRow("Código", self.classification_code)
        element_form.addRow(QLabel("<b>Propriedades IFC comuns</b>"))
        element_form.addRow("Reference", self.common_reference); element_form.addRow("Status", self.common_status)
        element_form.addRow("Externo", self.common_external); element_form.addRow("Load bearing", self.common_loadbearing)
        element_form.addRow("Fire rating", self.common_fire)
        self.apply_element_btn = QPushButton("Aplicar dados BIM ao selecionado")
        element_form.addRow(self.apply_element_btn); root.addWidget(element_box)
        info = QLabel(
            "As formas são exportadas a partir da geometria OpenTrace já resolvida. "
            "Curvas, inclinações, perfis, furos e junções não são reconstruídos pelo modelador de parede do Bonsai."
        )
        info.setWordWrap(True); info.setStyleSheet("color:#777;"); root.addWidget(info)

        self.status = QLabel("IFC4 · exportação por perfil · Open/Import/Link sem alterar o core")
        self.status.setWordWrap(True); self.status.setStyleSheet("color:#666;"); root.addWidget(self.status)
        root.addStretch(1)

        for edit in (self.project_name, self.site_name, self.building_name, self.author, self.organization, self.description):
            edit.editingFinished.connect(self.save)
        for check in (self.psets, self.layers, self.openings, self.quantities, self.styles, self.roundtrip, self.repmaps):
            check.toggled.connect(self.save)
        self.export_profile.currentIndexChanged.connect(self.profile_changed)
        self.open_btn.clicked.connect(lambda:self._choose_ifc("open",False))
        self.import_btn.clicked.connect(lambda:self._choose_ifc("import",False))
        self.link_btn.clicked.connect(lambda:self._choose_ifc("import",True))
        self.identify_btn.clicked.connect(self.prepare_identities)
        self.export_btn.clicked.connect(self.export)
        self.advanced_btn.clicked.connect(self.open_advanced)
        self.apply_element_btn.clicked.connect(self.apply_selected_metadata)
        return w

    def open_advanced(self):
        try:
            from .bim_advanced_ui import BimAdvancedDialog
            dlg=BimAdvancedDialog(self,self.panel);dlg.exec();self.data=load_document_data(self.app);self.refresh()
        except Exception as exc:
            QMessageBox.critical(self.panel,"OpenTrace BIM",f"Could not open the advanced BIM editor:\n{type(exc).__name__}: {exc}")

    def _document_changed(self):
        self.data = load_document_data(self.app)
        self.refresh()

    def schedule_refresh(self, *_):
        if self._refresh_queued:
            return
        self._refresh_queued = True
        QTimer.singleShot(0, self._run_refresh)

    def _run_refresh(self):
        self._refresh_queued = False
        self.refresh_counts()

    def refresh(self):
        project = self.data.get("project", {})
        export = self.data.get("export", {})
        mapping = (
            (self.project_name, project.get("name", "")), (self.site_name, project.get("site", "")),
            (self.building_name, project.get("building", "")), (self.author, project.get("author", "")),
            (self.organization, project.get("organization", "")), (self.description, project.get("description", "")),
        )
        for widget, value in mapping:
            old = widget.blockSignals(True); widget.setText(str(value or "")); widget.blockSignals(old)
        old=self.export_profile.blockSignals(True);idx=self.export_profile.findData(str(export.get("profile") or "bonsai"));self.export_profile.setCurrentIndex(idx if idx>=0 else 0);self.export_profile.blockSignals(old)
        for widget, key in ((self.psets, "include_property_sets"), (self.layers, "include_material_layers"), (self.openings, "include_opening_relations"), (self.quantities, "include_quantities"), (self.styles,"include_styles"),(self.roundtrip,"include_parametric_roundtrip"),(self.repmaps,"use_representation_maps")):
            old = widget.blockSignals(True); widget.setChecked(bool(export.get(key, True))); widget.blockSignals(old)
        self._update_profile_ui()
        self.refresh_counts()
        self.refresh_selected()

    def _selected_group(self):
        scene = self.app.scene
        if getattr(scene, "edit_group", None) is not None:
            return None
        found = []
        from .bim import element_kind
        for item in list(getattr(scene, "selection", ()) or ()):
            group = getattr(item, "owner", None) or item
            if group in getattr(scene, "groups", ()) and element_kind(group) and group not in found:
                found.append(group)
        return found[0] if len(found) == 1 else None

    def refresh_selected(self):
        group = self._selected_group()
        if group is None:
            self.element_class.setText("—"); self.element_guid.setText("—")
            for widget in (self.element_name, self.element_type, self.classification_system, self.classification_code, self.common_reference, self.common_fire):
                old = widget.blockSignals(True); widget.clear(); widget.setEnabled(False); widget.blockSignals(old)
            old = self.element_predefined.blockSignals(True); self.element_predefined.clear(); self.element_predefined.setEnabled(False); self.element_predefined.blockSignals(old)
            for combo in (self.common_status, self.common_external, self.common_loadbearing):
                old = combo.blockSignals(True); combo.setCurrentIndex(0); combo.setEnabled(False); combo.blockSignals(old)
            self.apply_element_btn.setEnabled(False); return
        from .bim import KIND_TO_CLASS, element_kind
        raw_meta = getattr(group, "ifc", None)
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        ifc_class = str(meta.get("class") or KIND_TO_CLASS.get(element_kind(group)) or "IfcBuildingElementProxy")
        self.element_class.setText(ifc_class); self.element_guid.setText(str(meta.get("global_id") or "Pendente — use Preparar identidades IFC"))
        from .ifc_catalog import predefined_types
        values = predefined_types(ifc_class)
        old = self.element_predefined.blockSignals(True); self.element_predefined.clear(); self.element_predefined.addItems(values)
        current = str(meta.get("predefined_type") or "NOTDEFINED").upper()
        idx = self.element_predefined.findText(current); self.element_predefined.setCurrentIndex(idx if idx >= 0 else self.element_predefined.findText("NOTDEFINED")); self.element_predefined.setEnabled(True); self.element_predefined.blockSignals(old)
        for widget, value in ((self.element_name, meta.get("name", "")), (self.element_type, meta.get("type_name", "")), (self.classification_system, meta.get("classification_system", "")), (self.classification_code, meta.get("classification_code", ""))):
            old = widget.blockSignals(True); widget.setText(str(value or "")); widget.setEnabled(True); widget.blockSignals(old)
        common = meta.get("common") if isinstance(meta.get("common"), dict) else {}
        old = self.common_reference.blockSignals(True); self.common_reference.setText(str(common.get("Reference") or "")); self.common_reference.setEnabled(True); self.common_reference.blockSignals(old)
        old = self.common_fire.blockSignals(True); self.common_fire.setText(str(common.get("FireRating") or "")); self.common_fire.setEnabled(True); self.common_fire.blockSignals(old)
        for combo, key in ((self.common_status, "Status"), (self.common_external, "IsExternal"), (self.common_loadbearing, "LoadBearing")):
            old = combo.blockSignals(True); combo.setEnabled(True)
            wanted = common.get(key, None); idx = combo.findData(wanted); combo.setCurrentIndex(idx if idx >= 0 else 0); combo.blockSignals(old)
        self.apply_element_btn.setEnabled(True)

    def apply_selected_metadata(self):
        group = self._selected_group()
        if group is None:
            return
        meta = ifc_identity_data(group)
        meta["name"] = self.element_name.text().strip() or getattr(group, "name", None) or meta.get("class")
        meta["type_name"] = self.element_type.text().strip() or meta.get("type_name")
        meta["predefined_type"] = self.element_predefined.currentText().strip().upper() or "NOTDEFINED"
        meta["classification_system"] = self.classification_system.text().strip()
        meta["classification_code"] = self.classification_code.text().strip()
        common = {
            "Reference": self.common_reference.text().strip() or None,
            "Status": self.common_status.currentData(),
            "IsExternal": self.common_external.currentData(),
            "LoadBearing": self.common_loadbearing.currentData(),
            "FireRating": self.common_fire.text().strip() or None,
        }
        meta["common"] = {k: v for k, v in common.items() if v is not None}
        set_ifc_metadata(self.app, group, meta)
        self.status.setText("Element BIM data updated.")
        self.refresh_selected()

    def refresh_counts(self):
        stats = scan_scene(self.app.scene)
        c = stats["counts"]
        self.summary.setText(
            f"BIM elements in document: <b>{stats['total']}</b> · "
            f"{c.get('wall',0)} walls · {c.get('slab',0)} slabs · {c.get('beam',0)} beams · {c.get('column',0)} columns · "
            f"{c.get('space',0)} spaces · {c.get('roof',0)} roofs · {c.get('door',0)} doors · {c.get('window',0)} windows. "
            f"Composites: {stats['composite']} · parametric openings: {stats['openings']} · "
            f"imported/reference IFC: {stats.get('imported',0)} (linked: {stats.get('linked',0)})."
        )
        self.export_btn.setEnabled(stats["total"] > 0)
        self.refresh_selected()

    def save(self, *_):
        self.data["project"] = {
            "name": self.project_name.text().strip(), "site": self.site_name.text().strip(),
            "building": self.building_name.text().strip(), "author": self.author.text().strip(),
            "organization": self.organization.text().strip(), "description": self.description.text().strip(),
        }
        self.data["export"] = {
            "schema": "IFC4", "profile": self.export_profile.currentData() or "bonsai", "include_property_sets": self.psets.isChecked(),
            "include_material_layers": self.layers.isChecked(),
            "include_opening_relations": self.openings.isChecked(),
            "include_quantities": self.quantities.isChecked(),
            "include_styles": self.styles.isChecked(),
            "include_parametric_roundtrip": self.roundtrip.isChecked(),
            "use_representation_maps": self.repmaps.isChecked(),
        }
        try:
            try:
                from .levels import available_levels
                levels = available_levels(self.app)
                names = [str(x.get("name") or "") for x in levels if isinstance(x, dict)]
            except Exception:
                names = ["Pavimento 0"]
            ensure_spatial_ids(self.data, names or ["Pavimento 0"])
            self.data = save_document_data(self.app, self.data)
        except Exception as exc:
            self.status.setText(f"Could not save BIM data: {type(exc).__name__}: {exc}")

    def _update_profile_ui(self):
        key=self.export_profile.currentData() or "bonsai"
        cfg=EXPORT_PROFILES.get(key,EXPORT_PROFILES["bonsai"])
        compat=key!="opentrace"
        self.openings.setEnabled(not compat)
        if compat:
            old=self.openings.blockSignals(True);self.openings.setChecked(False);self.openings.blockSignals(old)
            if key=="bonsai":
                self.profile_hint.setText("Bonsai / Blender: complete Body + Axis contexts, native solids when safe, and BRep for the remainder. OpenTrace walls are not advertised as Bonsai-editable DumbLayer2 elements.")
            elif key=="archicad":
                self.profile_hint.setText("Archicad: prioritizes SweptSolid, IFC axes and native compositions for architectural conversion; advanced shapes preserve geometry as BRep.")
            else:
                self.profile_hint.setText("Revit: prioritizes SweptSolid, IFC axes and standard types/materials; shapes that cannot be represented as an extrusion remain BRep to preserve form.")
        else:
            self.profile_hint.setText("OpenTrace fidelity: IFC4 PolygonalFaceSet with optional IfcOpeningElement relations. Useful for openBIM inspection and future round-trip workflows.")

    def profile_changed(self,*_):
        self._update_profile_ui();self.save()

    def _choose_ifc(self,mode,linked):
        title="Open IFC as project" if mode=="open" else ("Link IFC" if linked else "Import IFC")
        filename,_=QFileDialog.getOpenFileName(self.panel,title,"","Industry Foundation Classes (*.ifc)")
        if not filename:return
        if mode=="open" and list(getattr(self.app.scene,"groups",()) or ()):
            answer=QMessageBox.question(self.panel,"OpenTrace BIM","Opening this IFC will replace the elements in the current document (the operation is undoable). Continue?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer!=QMessageBox.Yes:return
        try:
            result=import_ifc(self.app,Path(filename),mode=mode,linked=linked)
            if linked:
                links=list(self.data.get("links",[]) or []);links.append({"path":str(filename),"mode":"linked"});self.data["links"]=links
            if mode=="open":
                proj=result.get("project",{})
                for widget,key in ((self.project_name,"name"),(self.site_name,"site"),(self.building_name,"building")):
                    if proj.get(key):widget.setText(str(proj[key]))
            self.save();self.refresh_counts()
            skipped=int(result.get("unsupported",0) or 0)
            kind="linked" if linked else ("opened" if mode=="open" else "imported")
            unit=float(result.get("unit_scale",1.0) or 1.0);reader=str(result.get("reader") or "")
            unit_msg=(f" · file units converted to metres (×{unit:g})" if abs(unit-1.0)>1e-12 else "")
            self.status.setText(f"IFC {kind}: {len(result['groups'])} element(s) with compatible geometry"+(f" · {skipped} unsupported representation(s)" if skipped else "")+unit_msg+(f" · reader {reader}" if reader else "")+".")
        except IfcImportError as exc:QMessageBox.warning(self.panel,"OpenTrace BIM",str(exc))
        except Exception as exc:QMessageBox.critical(self.panel,"OpenTrace BIM",f"Could not read IFC:\n{type(exc).__name__}: {exc}")

    def prepare_identities(self):
        try:
            changed = prepare_scene_identities(self.app)
            self.status.setText(f"IFC identities prepared. {changed} element(s) received or migrated BIM metadata.")
        except Exception as exc:
            QMessageBox.critical(self.panel, "OpenTrace BIM", f"Could not prepare IFC identities:\n{type(exc).__name__}: {exc}")

    def export(self):
        self.save()
        default_name = (self.project_name.text().strip() or "OpenTrace_BIM").replace("/", "-").replace("\\", "-") + ".ifc"
        filename, _ = QFileDialog.getSaveFileName(self.panel, "Export OpenTrace BIM", default_name, "Industry Foundation Classes (*.ifc)")
        if not filename:
            return
        if not filename.lower().endswith(".ifc"):
            filename += ".ifc"
        try:
            changed = prepare_scene_identities(self.app)
            result = export_ifc(self.app, Path(filename), data=self.data)
            reps=result.get("representations",{})
            self.status.setText(
                f"IFC exported ({result.get('profile','')}): {result['elements']} elements · {result['openings']} semantic openings · "
                f"{result['storeys']} storeys · {result['types']} types · "
                f"{reps.get('SweptSolid',0)} SweptSolid / {reps.get('Brep',0)} BRep / {reps.get('Tessellation',0)} Tessellation."
            )
            QMessageBox.information(self.panel, "OpenTrace BIM", f"IFC4 exported successfully.\n\n{filename}")
        except IfcExportError as exc:
            QMessageBox.warning(self.panel, "OpenTrace BIM", str(exc))
        except Exception as exc:
            QMessageBox.critical(self.panel, "OpenTrace BIM", f"Could not export IFC:\n{type(exc).__name__}: {exc}")
