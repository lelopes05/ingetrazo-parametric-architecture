# SPDX-License-Identifier: GPL-3.0-or-later
"""Advanced BIM editor kept out of the compact side palette."""
from __future__ import annotations

import copy
import math
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QInputDialog,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .bim import (ifc_identity_data, new_ifc_guid, record_for,
                  set_ifc_metadata)
from .bim_library import (merged_library, put_classification,
                          put_material_style, put_type, type_definition, type_metadata)
from .ifc_catalog import catalogue_stats, property_set_templates, predefined_types, entity_description
from .i18n import translate_widget


def _parse_value(text):
    s = str(text or "").strip()
    if not s: return None
    if s.lower() in ("true", "sim", "yes"): return True
    if s.lower() in ("false", "não", "nao", "no"): return False
    try:
        return float(s.replace(",", ".")) if any(c in s for c in ",.Ee") else int(s)
    except Exception:
        return s


class BimAdvancedDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent or controller.panel)
        self.controller = controller; self.app = controller.app
        self.setWindowTitle("OpenTrace BIM · Dados avançados")
        self.resize(860, 650)
        root = QVBoxLayout(self)
        stats = catalogue_stats()
        info = QLabel(f"Catálogo offline IFC4: {stats['entities']} entidades · {stats['psets']} Property Sets · {stats['qtos']} Quantity Sets.")
        info.setWordWrap(True); root.addWidget(info)
        self.tabs = QTabWidget(); root.addWidget(self.tabs, 1)
        self._build_semantics(); self._build_psets(); self._build_layerset(); self._build_library(); self._build_relations(); self._build_georef(); self._build_material()
        row = QHBoxLayout(); row.addStretch(1); close = QPushButton("Fechar"); close.clicked.connect(self.accept); row.addWidget(close); root.addLayout(row)
        self.refresh()
        translate_widget(self)

    def group(self): return self.controller._selected_group()
    def meta(self):
        g = self.group(); return ifc_identity_data(g) if g is not None else None
    def changed(self, message="Dados BIM atualizados."):
        self.controller.save(); self.controller.refresh_counts(); self.status.setText(message)

    def commit_meta(self, group, meta, message="Dados BIM atualizados."):
        set_ifc_metadata(self.app, group, meta)
        self.changed(message)


    def _build_semantics(self):
        w=QWidget(); form=QFormLayout(w); self.tabs.addTab(w,"Semântica IFC")
        self.class_combo=QComboBox()
        classes=("IfcWall","IfcSlab","IfcBeam","IfcColumn","IfcRoof","IfcSpace",
                 "IfcDoor","IfcWindow","IfcStair","IfcRamp","IfcRailing",
                 "IfcBuildingElementProxy")
        for cls in classes:self.class_combo.addItem(cls,cls)
        self.predef_combo=QComboBox();self.predef_combo.setEditable(True)
        self.long_name=QLineEdit();self.object_type=QLineEdit()
        self.semantic_hint=QLabel();self.semantic_hint.setWordWrap(True);self.semantic_hint.setStyleSheet("color:#666")
        self.semantic_apply=QPushButton("Aplicar classe / tipo semântico")
        form.addRow("Classe IFC",self.class_combo);form.addRow("PredefinedType",self.predef_combo)
        form.addRow("Long name / ambiente",self.long_name);form.addRow("ObjectType",self.object_type)
        form.addRow(self.semantic_hint);form.addRow(self.semantic_apply)
        self.class_combo.currentIndexChanged.connect(self._semantic_class_changed)
        self.semantic_apply.clicked.connect(self.apply_semantics)

    def _semantic_class_changed(self,*_):
        cls=self.class_combo.currentData() or "IfcBuildingElementProxy"
        current=self.predef_combo.currentText().strip()
        self.predef_combo.blockSignals(True);self.predef_combo.clear()
        vals=predefined_types(cls) or ["NOTDEFINED"]
        self.predef_combo.addItems(vals)
        i=self.predef_combo.findText(current);self.predef_combo.setCurrentIndex(i if i>=0 else 0)
        self.predef_combo.blockSignals(False)
        desc=entity_description(cls) or ""
        extra=("Room é exportado como IfcSpace; agrupe ambientes em IfcZone na aba Zonas/Sistemas/Grupos." if cls=="IfcSpace" else
               "Esta classe altera a semântica BIM, não transforma automaticamente a geometria numa ferramenta paramétrica OpenTrace." )
        self.semantic_hint.setText((desc[:420]+("…" if len(desc)>420 else "")+"\n"+extra).strip())

    def apply_semantics(self):
        g=self.group()
        if g is None:return
        meta=ifc_identity_data(g)
        cls=str(self.class_combo.currentData() or "IfcBuildingElementProxy")
        meta["class"]=cls;meta["predefined_type"]=self.predef_combo.currentText().strip() or "NOTDEFINED"
        if self.long_name.text().strip():meta["long_name"]=self.long_name.text().strip()
        if self.object_type.text().strip():meta["object_type"]=self.object_type.text().strip()
        # Match the exporter/round-trip engine label to the semantic class only
        # for generic objects. Native OpenTrace wall/slab/etc. keep their own
        # engine, which is what allows later parametric reconstruction.
        if not str(meta.get("engine") or "").startswith("OpenTrace."):
            meta["engine"]="OpenTrace.Generic"
        self.commit_meta(g,meta,f"{cls} aplicado ao elemento.")
    def _build_psets(self):
        w=QWidget(); lay=QVBoxLayout(w); self.tabs.addTab(w,"Property Sets / Qto")
        top=QHBoxLayout(); self.pset_combo=QComboBox(); self.pset_combo.setEditable(True); top.addWidget(self.pset_combo,1)
        self.pset_load=QPushButton("Carregar"); self.pset_save=QPushButton("Aplicar ao elemento"); self.pset_remove=QPushButton("Remover")
        for b in (self.pset_load,self.pset_save,self.pset_remove): top.addWidget(b)
        lay.addLayout(top)
        self.pset_desc=QLabel(); self.pset_desc.setWordWrap(True); self.pset_desc.setStyleSheet("color:#777"); lay.addWidget(self.pset_desc)
        self.pset_table=QTableWidget(0,3); self.pset_table.setHorizontalHeaderLabels(["Propriedade","Tipo IFC","Valor"]); self.pset_table.horizontalHeader().setStretchLastSection(True); lay.addWidget(self.pset_table,1)
        self.pset_load.clicked.connect(self.load_pset); self.pset_save.clicked.connect(self.save_pset); self.pset_remove.clicked.connect(self.remove_pset)
        self.pset_combo.currentTextChanged.connect(self._pset_hint)

    def _build_layerset(self):
        w=QWidget(); lay=QVBoxLayout(w); self.tabs.addTab(w,"Materiais / LayerSet")
        self.layer_kind=QLabel(); self.layer_kind.setWordWrap(True)
        self.layer_kind.setStyleSheet("font-weight:600")
        lay.addWidget(self.layer_kind)
        self.layer_help=QLabel(
            "Esta aba mostra a associação IFC que o exportador criará para o elemento selecionado. "
            "No perfil Bonsai, paredes OpenTrace mantêm o IfcMaterialLayerSet no Tipo, mas não recebem "
            "IfcMaterialLayerSetUsage na ocorrência para impedir que o Bonsai tente regenerá-las com o modelador dele.")
        self.layer_help.setWordWrap(True); self.layer_help.setStyleSheet("color:#777")
        lay.addWidget(self.layer_help)
        self.layer_table=QTableWidget(0,4)
        self.layer_table.setHorizontalHeaderLabels(["Camada / constituinte","Função","Material","Espessura"]); self.layer_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.layer_table,1)
        self.layer_detail=QLabel(); self.layer_detail.setWordWrap(True); self.layer_detail.setStyleSheet("color:#777")
        lay.addWidget(self.layer_detail)

    def _build_library(self):
        w=QWidget(); lay=QVBoxLayout(w); self.tabs.addTab(w,"Bibliotecas BIM")
        help_=QLabel("Biblioteca BIM = definições reutilizáveis. Um Tipo pode guardar classe IFC, PredefinedType, Psets, classificação e dados de material para reaplicar em outros elementos; a biblioteca pessoal fica disponível também em outros projetos.")
        help_.setWordWrap(True);help_.setStyleSheet("color:#777");lay.addWidget(help_)
        lay.addWidget(QLabel("<b>Tipos BIM reutilizáveis</b>"))
        r=QHBoxLayout(); self.type_combo=QComboBox(); self.type_combo.setEditable(True); r.addWidget(self.type_combo,1)
        self.type_save=QPushButton("Salvar selecionado"); self.type_apply=QPushButton("Aplicar metadados"); r.addWidget(self.type_save); r.addWidget(self.type_apply); lay.addLayout(r)
        self.personal_type=QCheckBox("Salvar na biblioteca pessoal (outros projetos)"); lay.addWidget(self.personal_type)
        lay.addWidget(QLabel("<b>Classificações externas / biblioteca</b>"))
        form=QFormLayout(); self.class_name=QLineEdit(); self.class_system=QLineEdit(); self.class_code=QLineEdit(); self.class_location=QLineEdit()
        form.addRow("Nome",self.class_name); form.addRow("Sistema",self.class_system); form.addRow("Código",self.class_code); form.addRow("URI/localização",self.class_location); lay.addLayout(form)
        rr=QHBoxLayout(); self.class_personal=QCheckBox("Biblioteca pessoal"); self.class_save=QPushButton("Salvar classificação"); self.class_apply=QPushButton("Associar ao selecionado"); rr.addWidget(self.class_personal);rr.addStretch(1);rr.addWidget(self.class_save);rr.addWidget(self.class_apply);lay.addLayout(rr); lay.addStretch(1)
        self.type_save.clicked.connect(self.save_type);self.type_apply.clicked.connect(self.apply_type);self.class_save.clicked.connect(self.save_classification);self.class_apply.clicked.connect(self.apply_classification)

    def _build_relations(self):
        w=QWidget(); lay=QVBoxLayout(w); self.tabs.addTab(w,"Zonas / Sistemas / Grupos")
        hint=QLabel("Escolha uma definição existente ou use + para criar uma nova. Depois associe o elemento selecionado. As definições ficam disponíveis para qualquer objeto do projeto.")
        hint.setWordWrap(True); hint.setStyleSheet("color:#777"); lay.addWidget(hint)
        self.rel_fields={}
        for key,label in (("zones","Zona / Room group"),("systems","Sistema"),("groups","Grupo BIM")):
            box=QHBoxLayout(); combo=QComboBox(); combo.setEditable(False); combo.setMinimumWidth(220)
            add=QPushButton("+"); add.setFixedWidth(32); add.setToolTip(f"Criar novo {label.lower()}")
            btn=QPushButton("Associar selecionado")
            box.addWidget(QLabel(label)); box.addWidget(combo,1); box.addWidget(add); box.addWidget(btn); lay.addLayout(box)
            self.rel_fields[key]=combo
            add.clicked.connect(lambda _=False,k=key:self._new_relation(k))
            btn.clicked.connect(lambda _=False,k=key:self.add_relation(k))
        self.relations_summary=QLabel();self.relations_summary.setWordWrap(True);self.relations_summary.setStyleSheet("color:#666");lay.addWidget(self.relations_summary);lay.addStretch(1)

    def _build_georef(self):
        w=QWidget(); lay=QVBoxLayout(w); self.tabs.addTab(w,"Georreferenciamento")
        intro=QLabel("Choose the coordinate system used by the survey/site. If you do not know its EPSG code, use ‘Find coordinate system…’ and search by place or CRS name. Origin coordinates and rotation are optional for local models.")
        intro.setWordWrap(True); intro.setStyleSheet("color:#777"); lay.addWidget(intro)
        basic=QFormLayout(); lay.addLayout(basic); self.geo={}
        self.geo["epsg"]=QLineEdit(); self.geo["epsg"].setPlaceholderText("e.g. 31983 or EPSG:31983")
        basic.addRow("Coordinate system",self.geo["epsg"])
        coord=QWidget(); cr=QHBoxLayout(coord); cr.setContentsMargins(0,0,0,0)
        for key,lab in (("eastings","E"),("northings","N"),("orthogonal_height","Z")):
            sp=QDoubleSpinBox();sp.setDecimals(4);sp.setRange(-1e12,1e12);sp.setSingleStep(1.0);sp.setSuffix(" m");self.geo[key]=sp;cr.addWidget(QLabel(lab));cr.addWidget(sp,1)
        basic.addRow("Survey / model origin",coord)
        self.geo_rotation=QDoubleSpinBox();self.geo_rotation.setDecimals(6);self.geo_rotation.setRange(-360.0,360.0);self.geo_rotation.setSuffix("°");self.geo_rotation.setToolTip("Rotation of the local X axis relative to CRS east.")
        basic.addRow("Rotation",self.geo_rotation)
        row=QHBoxLayout(); self.geo_lookup=QPushButton("Find coordinate system…"); self.geo_lookup.setToolTip("Open EPSG.io, where you can search by place, projection or CRS name."); self.geo_more=QPushButton("Advanced details ▾"); row.addWidget(self.geo_lookup);row.addWidget(self.geo_more);row.addStretch(1);lay.addLayout(row)
        self.geo_advanced=QWidget(); adv=QFormLayout(self.geo_advanced)
        for key,label in (("crs_name","Nome do CRS"),("geodetic_datum","Datum geodésico"),("vertical_datum","Datum vertical"),("map_projection","Projeção"),("map_zone","Zona")):
            e=QLineEdit();self.geo[key]=e;adv.addRow(label,e)
        self.geo["scale"]=QDoubleSpinBox();self.geo["scale"].setDecimals(10);self.geo["scale"].setRange(1e-12,1e12);self.geo["scale"].setValue(1.0);adv.addRow("Escala MapConversion",self.geo["scale"])
        self.geo_advanced.setVisible(False);lay.addWidget(self.geo_advanced)
        self.geo_save=QPushButton("Save IFC georeferencing");lay.addWidget(self.geo_save);lay.addStretch(1)
        self.geo_save.clicked.connect(self.save_geo); self.geo_lookup.clicked.connect(self.open_epsg); self.geo_more.clicked.connect(self.toggle_geo_advanced)

    def _build_material(self):
        w=QWidget(); form=QFormLayout(w); self.tabs.addTab(w,"Aparência IFC")
        self.style_name=QLineEdit(); self.style_color=[0.75,0.75,0.75]
        self.color_btn=QPushButton("Escolher cor…"); self.opacity=QDoubleSpinBox();self.opacity.setRange(0,1);self.opacity.setSingleStep(.05);self.opacity.setValue(1.0)
        self.style_personal=QCheckBox("Salvar na biblioteca pessoal")
        self.style_apply=QPushButton("Aplicar aparência IFC ao selecionado");self.style_save=QPushButton("Salvar estilo")
        form.addRow("Nome",self.style_name);form.addRow("Cor",self.color_btn);form.addRow("Opacidade",self.opacity);form.addRow(self.style_personal);form.addRow(self.style_apply,self.style_save)
        self.color_btn.clicked.connect(self.choose_color);self.style_apply.clicked.connect(self.apply_style);self.style_save.clicked.connect(self.save_style)
        self.status=QLabel();self.status.setWordWrap(True);form.addRow(self.status)

    def refresh(self):
        g=self.group(); meta=self.meta() if g else None; cls=str((meta or {}).get("class") or "IfcBuildingElementProxy")
        ci=self.class_combo.findData(cls);self.class_combo.setCurrentIndex(ci if ci>=0 else self.class_combo.findData("IfcBuildingElementProxy"))
        self._semantic_class_changed()
        if meta:
            pi=self.predef_combo.findText(str(meta.get("predefined_type") or "NOTDEFINED"));
            if pi>=0:self.predef_combo.setCurrentIndex(pi)
            self.long_name.setText(str(meta.get("long_name") or ""));self.object_type.setText(str(meta.get("object_type") or ""))
        self.pset_combo.clear(); templates=property_set_templates(cls,quantities=None); self.pset_combo.addItems(sorted(templates,key=lambda n:(n.startswith("Qto_"),not n.endswith("Common"),n)))
        lib=merged_library(self.controller.data);self.type_combo.clear();self.type_combo.addItems(sorted(lib.get("types",{})))
        geo=self.controller.data.get("georeference",{})
        for k,w in self.geo.items():
            if isinstance(w,QLineEdit): w.setText(str(geo.get(k,"") or ""))
            else:
                default=1.0 if k=="scale" else 0.0
                w.setValue(float(geo.get(k,default) if geo.get(k,default) is not None else default))
        try:
            self.geo_rotation.setValue(math.degrees(math.atan2(float(geo.get("x_axis_ordinate",0.0) or 0.0),float(geo.get("x_axis_abscissa",1.0) or 1.0))))
        except Exception: self.geo_rotation.setValue(0.0)
        self._refresh_relations(); self._refresh_layerset()
        if meta and isinstance(meta.get("material_style"),dict):
            st=meta["material_style"];self.style_color=list(st.get("color",self.style_color));self.opacity.setValue(float(st.get("opacity",1.0)))
        self._pset_hint(self.pset_combo.currentText())

    def _pset_hint(self,name):
        data=property_set_templates(None,quantities=None).get(str(name),{});self.pset_desc.setText(str(data.get("description") or data.get("applicable_entity") or ""))

    def load_pset(self):
        name=self.pset_combo.currentText().strip(); g=self.group()
        if not name or g is None:return
        data=property_set_templates(None,quantities=None).get(name,{})
        existing=(ifc_identity_data(g).get("property_sets") or {}).get(name,{})
        self.pset_table.setRowCount(0)
        for prop in data.get("properties",()) or ():
            row=self.pset_table.rowCount();self.pset_table.insertRow(row)
            n=str(prop.get("name") or "");t=str(prop.get("primary_measure_type") or prop.get("template_type") or "")
            a=QTableWidgetItem(n);a.setFlags(a.flags() & ~Qt.ItemIsEditable);b=QTableWidgetItem(t);b.setFlags(b.flags() & ~Qt.ItemIsEditable);c=QTableWidgetItem("" if existing.get(n) is None else str(existing.get(n)))
            self.pset_table.setItem(row,0,a);self.pset_table.setItem(row,1,b);self.pset_table.setItem(row,2,c)
        # Unknown/imported properties remain editable instead of being lost.
        known={str(x.get("name")) for x in data.get("properties",()) or ()}
        for n,v in existing.items():
            if n in known:continue
            row=self.pset_table.rowCount();self.pset_table.insertRow(row);self.pset_table.setItem(row,0,QTableWidgetItem(str(n)));self.pset_table.setItem(row,1,QTableWidgetItem("importado"));self.pset_table.setItem(row,2,QTableWidgetItem(str(v)))

    def save_pset(self):
        g=self.group();name=self.pset_combo.currentText().strip()
        if g is None or not name:return
        vals={}
        for r in range(self.pset_table.rowCount()):
            n=self.pset_table.item(r,0);v=self.pset_table.item(r,2)
            if n and v:
                parsed=_parse_value(v.text())
                if parsed is not None:vals[n.text()]=parsed
        meta=ifc_identity_data(g);meta.setdefault("property_sets",{})[name]=vals;self.commit_meta(g,meta,f"{name} aplicado ao elemento.")

    def remove_pset(self):
        g=self.group();name=self.pset_combo.currentText().strip()
        if g is None:return
        meta=ifc_identity_data(g);meta.setdefault("property_sets",{}).pop(name,None);self.pset_table.setRowCount(0);self.commit_meta(g,meta,f"{name} removido.")

    def save_type(self):
        g=self.group()
        if g is None:return
        name=self.type_combo.currentText().strip() or ifc_identity_data(g).get("type_name")
        try:put_type(self.controller.data,name,type_definition(g),personal=self.personal_type.isChecked());self.controller.save();self.refresh();self.status.setText("BIM type saved.")
        except Exception as exc:QMessageBox.warning(self,"OpenTrace BIM",str(exc))

    def apply_type(self):
        g=self.group();name=self.type_combo.currentText().strip();lib=merged_library(self.controller.data)
        if g is None or name not in lib.get("types",{}):return
        self.commit_meta(g,type_metadata(g,lib["types"][name]),"Metadados do tipo BIM aplicados. A geometria não foi alterada.")

    def save_classification(self):
        try:put_classification(self.controller.data,self.class_name.text(),self.class_system.text(),self.class_code.text(),location=self.class_location.text(),personal=self.class_personal.isChecked());self.controller.save();self.status.setText("Classification saved to the library.")
        except Exception as exc:QMessageBox.warning(self,"OpenTrace BIM",str(exc))

    def apply_classification(self):
        g=self.group()
        if g is None:return
        item={"system":self.class_system.text().strip(),"code":self.class_code.text().strip(),"name":self.class_name.text().strip(),"location":self.class_location.text().strip()}
        if not item["system"] or not item["code"]:return
        meta=ifc_identity_data(g);arr=meta.setdefault("classifications",[])
        if not any(x.get("system")==item["system"] and x.get("code")==item["code"] for x in arr):arr.append(item)
        self.commit_meta(g,meta,"Classificação associada ao elemento.")

    def _refresh_layerset(self):
        self.layer_table.setRowCount(0)
        g=self.group()
        if g is None:
            self.layer_kind.setText("Nenhum elemento selecionado")
            self.layer_detail.setText("")
            return
        rec=record_for(g); meta=ifc_identity_data(g); cls=str(meta.get("class") or "")
        layers=[x for x in (rec.get("layers") or meta.get("material_layers") or []) if isinstance(x,dict)]
        constituents=[x for x in (meta.get("material_constituents") or []) if isinstance(x,dict)]
        if layers:
            direction="AXIS3" if cls in ("IfcSlab","IfcRoof") else "AXIS2"
            self.layer_kind.setText(f"IfcMaterialLayerSet · {len(layers)} camadas · direção {direction}")
            for item in layers:
                row=self.layer_table.rowCount();self.layer_table.insertRow(row)
                vals=(item.get("name") or "Camada",item.get("function") or "",item.get("material") or item.get("material_name") or "Padrão",f"{float(item.get('thickness',0.0) or 0.0):.4f} m")
                for col,val in enumerate(vals): self.layer_table.setItem(row,col,QTableWidgetItem(str(val)))
            profile=str(self.controller.data.get("export",{}).get("profile") or "bonsai")
            if cls=="IfcWall" and profile=="bonsai":
                self.layer_detail.setText("Perfil Bonsai: o LayerSet fica associado ao IfcWallType; a ocorrência não recebe LayerSetUsage para não ser confundida com uma parede paramétrica LAYER2 do Bonsai.")
            else:
                self.layer_detail.setText(f"Na exportação, a ocorrência recebe IfcMaterialLayerSetUsage quando compatível ({direction}).")
            return
        if constituents:
            self.layer_kind.setText("IfcMaterialConstituentSet")
            for item in constituents:
                row=self.layer_table.rowCount();self.layer_table.insertRow(row)
                vals=(item.get("name") or "Constituinte",item.get("category") or item.get("function") or "",item.get("material") or item.get("material_name") or "Padrão","")
                for col,val in enumerate(vals): self.layer_table.setItem(row,col,QTableWidgetItem(str(val)))
            self.layer_detail.setText("Constituintes descrevem partes/materializações sem uma espessura em camadas obrigatória.")
            return
        if cls in ("IfcBeam","IfcColumn"):
            self.layer_kind.setText("IfcMaterialProfileSetUsage")
            prof=rec.get("profile") or {}
            shape=str(prof.get("shape") or rec.get("shape") or "retangular")
            mat=str(rec.get("material_name") or "Padrão")
            row=self.layer_table.rowCount();self.layer_table.insertRow(row)
            for col,val in enumerate((shape,"Perfil",mat,"")): self.layer_table.setItem(row,col,QTableWidgetItem(str(val)))
            self.layer_detail.setText("Vigas e pilares simples usam perfil + material; perfis complexos preservam a geometria OpenTrace e a semântica IFC disponível.")
            return
        mat=str(rec.get("material_name") or meta.get("material_name") or "Padrão")
        self.layer_kind.setText("IfcMaterial")
        row=self.layer_table.rowCount();self.layer_table.insertRow(row)
        for col,val in enumerate(("Material","Simples",mat,"")): self.layer_table.setItem(row,col,QTableWidgetItem(str(val)))
        self.layer_detail.setText("Elemento sem composição em camadas ou perfil material associado.")

    def _new_relation(self,key):
        labels={"zones":"zona / room group","systems":"sistema","groups":"grupo BIM"}
        name,ok=QInputDialog.getText(self,"OpenTrace BIM",f"Name of the new {labels.get(key,key)}:")
        name=str(name or "").strip()
        if not ok or not name:return
        arr=self.controller.data.setdefault(key,[])
        item=next((x for x in arr if isinstance(x,dict) and str(x.get("name") or "")==name),None)
        if item is None:
            item={"name":name,"global_id":new_ifc_guid(),"members":[]};arr.append(item);self.controller.save()
        self._refresh_relations()
        combo=self.rel_fields.get(key);i=combo.findText(name) if combo is not None else -1
        if combo is not None and i>=0: combo.setCurrentIndex(i)
        self.status.setText(f"{name} created. You can now assign the required elements.")

    def add_relation(self,key):
        g=self.group();combo=self.rel_fields[key];name=combo.currentText().strip()
        if g is None or not name:return
        gid=ifc_identity_data(g)["global_id"];arr=self.controller.data.setdefault(key,[]);item=next((x for x in arr if isinstance(x,dict) and x.get("name")==name),None)
        if item is None:item={"name":name,"global_id":new_ifc_guid(),"members":[]};arr.append(item)
        members=item.setdefault("members",[])
        if gid not in members:members.append(gid)
        meta=ifc_identity_data(g);meta.setdefault(key,[])
        if name not in meta[key]:meta[key].append(name)
        self.controller.save();self._refresh_relations();self.commit_meta(g,meta,f"Elemento associado a {name}.")

    def _refresh_relations(self):
        parts=[]
        for k,label in (("zones","Zonas"),("systems","Sistemas"),("groups","Grupos")):
            arr=[x for x in (self.controller.data.get(k,[]) or []) if isinstance(x,dict) and str(x.get("name") or "").strip()]
            parts.append(f"{label}: {len(arr)}")
            combo=self.rel_fields.get(k)
            if combo is not None:
                current=combo.currentText(); combo.blockSignals(True); combo.clear()
                combo.addItems([str(x.get("name")) for x in arr])
                i=combo.findText(current);combo.setCurrentIndex(i if i>=0 else (0 if combo.count() else -1));combo.blockSignals(False)
        self.relations_summary.setText(" · ".join(parts))

    def toggle_geo_advanced(self):
        show=not self.geo_advanced.isVisible();self.geo_advanced.setVisible(show);self.geo_more.setText("Advanced details ▴" if show else "Advanced details ▾")

    def open_epsg(self):
        code=self.geo["epsg"].text().strip().upper().replace("EPSG:","").strip()
        url=f"https://epsg.io/{code}" if code else "https://epsg.io/"
        QDesktopServices.openUrl(QUrl(url))

    def save_geo(self):
        geo=self.controller.data.setdefault("georeference",{})
        for k,w in self.geo.items():geo[k]=w.text().strip() if isinstance(w,QLineEdit) else w.value()
        a=math.radians(float(self.geo_rotation.value()))
        geo["x_axis_abscissa"]=math.cos(a);geo["x_axis_ordinate"]=math.sin(a)
        epsg=str(geo.get("epsg") or "").strip()
        if epsg and not str(geo.get("crs_name") or "").strip(): geo["crs_name"]="EPSG:"+epsg.upper().replace("EPSG:","")
        self.controller.save();self.status.setText("Georeferencing saved. The exporter will use IfcProjectedCRS + IfcMapConversion.")

    def choose_color(self):
        c=QColor.fromRgbF(*self.style_color);chosen=QColorDialog.getColor(c,self,"Cor IFC")
        if chosen.isValid():self.style_color=[chosen.redF(),chosen.greenF(),chosen.blueF()]

    def _style(self):return {"color":list(self.style_color),"opacity":float(self.opacity.value())}
    def apply_style(self):
        g=self.group()
        if g is None:return
        meta=ifc_identity_data(g);meta["material_style"]=self._style();self.commit_meta(g,meta,"Aparência IFC aplicada ao material do elemento.")
    def save_style(self):
        try:put_material_style(self.controller.data,self.style_name.text(),self._style(),personal=self.style_personal.isChecked());self.controller.save();self.status.setText("Material style saved.")
        except Exception as exc:QMessageBox.warning(self,"OpenTrace BIM",str(exc))
