# SPDX-License-Identifier: GPL-3.0-or-later
"""Built-in and personal architectural presets for model elements.

This library is deliberately host-light: presets are plain dictionaries and can
later be shared by the IngeTrazo, Blender/Bonsai and FreeCAD adapters.
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from .layers import normalize_layers, total_thickness
from .i18n import t

SETTINGS_KEY = "arquitetura_parametrica/element_presets_v2"
FILE_FORMAT = "parametric-architecture-preset"
FILE_VERSION = 1
_BUILTIN_PRESETS = None


def _layer(name, thickness, function="finish", role="finish", material=None):
    return {
        "id": uuid.uuid4().hex[:12], "name": name, "role": role,
        "function": function, "thickness": float(thickness),
        "material_name": material,
    }


def _composite(rows):
    layers=[]
    for row in rows:
        if len(row)==3:
            name,t,function=row; role="finish"
        else:
            name,t,function,role=row
        layers.append(_layer(name,t,function,role))
    layers=normalize_layers(layers)
    return {"structure":"composite", "layers":layers,
            "thickness":total_thickness(layers), "material_name":None}


def _p(pid, name, config, group, description=""):
    return {"id":f"builtin:{pid}","name":name,"kind":pid.split(":",1)[0],
            "group":group,"description":description,"builtin":True,
            "config":copy.deepcopy(config),"revision":1}


def builtins():
    global _BUILTIN_PRESETS
    if _BUILTIN_PRESETS is not None:
        return copy.deepcopy(_BUILTIN_PRESETS)
    wall=[]
    wall.append(_p("wall:generic10","Genérica · 10 cm",
                   {"structure":"simple","thickness":0.10,"material_name":None},
                   "Genéricas","Parede simples de partida."))
    for tag,core,name in (("cer9",.09,"Bloco cerâmico 9 + reboco"),
                          ("cer115",.115,"Bloco cerâmico 11,5 + reboco"),
                          ("cer14",.14,"Bloco cerâmico 14 + reboco"),
                          ("con9",.09,"Bloco de concreto 9 + reboco"),
                          ("con14",.14,"Bloco de concreto 14 + reboco")):
        wall.append(_p(f"wall:{tag}",name,_composite([
            ("Reboco externo",.015,"finish"),
            (("Bloco de concreto" if tag.startswith("con") else "Bloco cerâmico"),core,"structure","core"),
            ("Reboco interno",.015,"finish"),
        ]),"Alvenaria"))
    wall.append(_p("wall:cer9_tile1","Bloco cerâmico 9 + cerâmica em 1 face",_composite([
        ("Reboco externo",.015,"finish"),("Bloco cerâmico",.09,"structure","core"),
        ("Emboço interno",.015,"substrate"),("Argamassa colante",.005,"bonding"),
        ("Revestimento cerâmico",.009,"finish"),
    ]),"Alvenaria revestida"))
    wall.append(_p("wall:cer14_tile2","Bloco cerâmico 14 + cerâmica nas 2 faces",_composite([
        ("Revestimento cerâmico externo",.009,"finish"),("Argamassa colante externa",.005,"bonding"),
        ("Emboço externo",.015,"substrate"),("Bloco cerâmico",.14,"structure","core"),
        ("Emboço interno",.015,"substrate"),("Argamassa colante interna",.005,"bonding"),
        ("Revestimento cerâmico interno",.009,"finish"),
    ]),"Alvenaria revestida"))
    wall.append(_p("wall:dry95","Drywall 95 mm",_composite([
        ("Chapa de gesso externa",.0125,"finish"),("Montante 70 mm",.070,"technical","core"),
        ("Chapa de gesso interna",.0125,"finish"),
    ]),"Drywall"))
    wall.append(_p("wall:dry120","Drywall duplo 120 mm",_composite([
        ("Chapa de gesso 1 externa",.0125,"finish"),("Chapa de gesso 2 externa",.0125,"finish"),
        ("Montante 70 mm + lã",.070,"insulation","core"),
        ("Chapa de gesso 1 interna",.0125,"finish"),("Chapa de gesso 2 interna",.0125,"finish"),
    ]),"Drywall"))

    slab=[]
    slab.append(_p("slab:generic12","Genérica · 12 cm",
                   {"structure":"simple","thickness":.12,"material_name":None},"Genéricas"))
    slab.append(_p("slab:concrete12","Concreto armado aparente · 12 cm",
                   _composite([("Concreto armado",.12,"structure","core")]),"Estruturais"))
    slab.append(_p("slab:floor10","Concreto 10 + contrapiso + porcelanato",_composite([
        ("Concreto armado",.10,"structure","core"),("Contrapiso",.04,"substrate"),
        ("Argamassa colante",.005,"bonding"),("Porcelanato",.010,"finish"),
    ]),"Pisos"))
    slab.append(_p("slab:floor12","Concreto 12 + contrapiso + porcelanato",_composite([
        ("Concreto armado",.12,"structure","core"),("Contrapiso",.04,"substrate"),
        ("Argamassa colante",.005,"bonding"),("Porcelanato",.010,"finish"),
    ]),"Pisos"))
    slab.append(_p("slab:wood","Concreto 12 + acústica + madeira",_composite([
        ("Concreto armado",.12,"structure","core"),("Manta acústica",.005,"insulation"),
        ("Contrapiso",.04,"substrate"),("Piso de madeira",.015,"finish"),
    ]),"Pisos"))
    slab.append(_p("slab:wet","Área molhada impermeabilizada",_composite([
        ("Concreto armado",.12,"structure","core"),("Regularização / caimento",.03,"substrate"),
        ("Impermeabilização",.004,"waterproofing"),("Argamassa colante",.005,"bonding"),
        ("Revestimento cerâmico",.010,"finish"),
    ]),"Áreas molhadas"))
    slab.append(_p("slab:roof","Cobertura impermeabilizada",_composite([
        ("Concreto armado",.12,"structure","core"),("Regularização / caimento",.03,"substrate"),
        ("Impermeabilização",.004,"waterproofing"),("Proteção mecânica",.04,"substrate"),
    ]),"Coberturas"))
    slab.append(_p("slab:inverted","Cobertura invertida com isolamento",_composite([
        ("Concreto armado",.12,"structure","core"),("Regularização / caimento",.03,"substrate"),
        ("Impermeabilização",.004,"waterproofing"),("Isolamento térmico XPS",.05,"insulation"),
        ("Proteção mecânica",.04,"substrate"),
    ]),"Coberturas"))
    slab.append(_p("slab:green","Cobertura verde básica",_composite([
        ("Concreto armado",.12,"structure","core"),("Regularização / caimento",.03,"substrate"),
        ("Impermeabilização antirraiz",.005,"waterproofing"),("Camada drenante",.025,"technical"),
        ("Substrato vegetal",.15,"other"),
    ]),"Coberturas"))

    beam=[]
    for w,h in ((.15,.30),(.20,.40),(.20,.50),(.20,.60),(.25,.60),(.30,.60)):
        beam.append(_p(f"beam:concrete:{int(w*100)}x{int(h*100)}",
            f"Concreto armado · {int(w*100)} × {int(h*100)} cm",
            {"section_type":"simple","profile":"rect","width":w,"height":h,
             "diameter":min(w,h),"material_name":None},"Concreto armado"))
    for w,h in ((.05,.15),(.06,.20),(.08,.20),(.10,.30)):
        beam.append(_p(f"beam:wood:{int(w*100)}x{int(h*100)}",
            f"Madeira · {int(w*100)} × {int(h*100)} cm",
            {"section_type":"simple","profile":"rect","width":w,"height":h,
             "diameter":min(w,h),"material_name":None},"Madeira"))
    for code in ("W 150 x 13,0","W 200 x 19,3","W 250 x 22,3","W 310 x 28,3","W 360 x 32,9",
                 "IPE 160","IPE 200","IPE 240","HEA 200","HEB 200"):
        family="gerdau_w" if code.startswith("W ") else code.split()[0].lower()
        slug=code.lower().replace(" ","").replace(",",".").replace("/","-")
        beam.append(_p(f"beam:steel:{slug}",f"Aço · {code}",
            {"section_type":"complex","profile_ref":f"builtin:steel:{family}:{slug}","material_name":None},
            "Aço"))

    column=[]
    for w,d in ((.20,.20),(.20,.30),(.25,.25),(.30,.30),(.30,.40)):
        column.append(_p(f"column:concrete:{int(w*100)}x{int(d*100)}",
            f"Concreto · {int(w*100)} × {int(d*100)} cm",
            {"section_type":"simple","profile":"rect","width":w,"depth":d,
             "diameter":min(w,d),"material_name":None,"stations":None},"Concreto armado"))
    for side in (.15,.20):
        column.append(_p(f"column:wood:{int(side*100)}",
            f"Madeira · {int(side*100)} × {int(side*100)} cm",
            {"section_type":"simple","profile":"rect","width":side,"depth":side,
             "diameter":side,"material_name":None,"stations":None},"Madeira"))
    for code in ("HEA 160","HEA 200","HEB 200"):
        family=code.split()[0].lower(); slug=code.lower().replace(" ","")
        column.append(_p(f"column:steel:{slug}",f"Aço · {code}",
            {"section_type":"complex","profile_ref":f"builtin:steel:{family}:{slug}",
             "material_name":None,"stations":None},"Aço"))

    _BUILTIN_PRESETS={"wall":wall,"slab":slab,"beam":beam,"column":column}
    return copy.deepcopy(_BUILTIN_PRESETS)


def load_personal():
    raw=QSettings().value(SETTINGS_KEY,"{}")
    try:data=json.loads(str(raw or "{}"))
    except Exception:data={}
    if not isinstance(data,dict):data={}
    return {k:[x for x in v if isinstance(x,dict)] for k,v in data.items() if isinstance(v,list)}


def save_personal(data):
    QSettings().setValue(SETTINGS_KEY,json.dumps(data,ensure_ascii=False,separators=(",",":")))


def personal_for(kind): return copy.deepcopy(load_personal().get(kind,[]))


def all_for(kind): return copy.deepcopy(builtins().get(kind,[]))+personal_for(kind)


def _clean_name(value): return " ".join(str(value or "").split())


def upsert_personal(kind,preset):
    data=load_personal(); items=data.setdefault(kind,[]); item=copy.deepcopy(preset)
    item["id"]=str(item.get("id") or uuid.uuid4().hex); item["kind"]=kind;item["builtin"]=False
    item["name"]=_clean_name(item.get("name") or "Preset") or "Preset"
    item["revision"]=max(1,int(item.get("revision",1) or 1))
    for i,old in enumerate(items):
        if str(old.get("id"))==item["id"]:items[i]=item;break
    else:items.append(item)
    save_personal(data);return copy.deepcopy(item)


def delete_personal(kind,pid):
    data=load_personal();data[kind]=[x for x in data.get(kind,[]) if str(x.get("id"))!=str(pid)];save_personal(data)


def _source_values(kind, controller):
    if kind=="wall":
        from .model import read_wall
        src=read_wall(controller.target) if controller.target is not None else controller.defaults
        keys=("thickness","height","alignment","material_name","structure","layers")
    elif kind=="slab":
        from .slab_model import read_slab
        src=read_slab(controller.target) if controller.target is not None else controller.defaults
        keys=("thickness","reference_plane","material_name","structure","layers")
    elif kind=="beam":
        from .beam_model import read_beam
        src=read_beam(controller.target) if controller.target is not None else controller.defaults
        keys=("section_type","profile_ref","profile_data","profile","width","height","diameter","rotation","anchor","material_name")
    elif kind=="column":
        from .column_model import read_column
        src=read_column(controller.target) if controller.target is not None else controller.defaults
        keys=("section_type","profile_ref","profile_data","profile","width","depth","diameter","rotation","anchor","material_name","stations")
    else: return {}
    return {k:copy.deepcopy(src.get(k)) for k in keys if k in src}


def apply_preset(kind,controller,preset):
    config=copy.deepcopy(preset.get("config",{}))
    if kind=="wall":
        from .model import read_wall
        base=read_wall(controller.target) if controller.target is not None else copy.deepcopy(controller.defaults)
        base.update(config);controller.load_fields(base);controller.defaults_changed()
    elif kind=="slab":
        controller.defaults.update(config);controller._load_defaults();controller.apply_current_values()
    elif kind=="beam":
        from .beam_model import read_beam
        base=read_beam(controller.target) if controller.target is not None else copy.deepcopy(controller.defaults)
        base.update(config)
        if base.get("section_type")=="complex" and base.get("profile_ref"):
            from .profile_library import profile_by_id
            base["profile_data"]=profile_by_id(base["profile_ref"])
        controller._load_fields(base);controller.values_changed()
    elif kind=="column":
        from .column_model import read_column
        base=read_column(controller.target) if controller.target is not None else copy.deepcopy(controller.defaults)
        base.update(config)
        if base.get("section_type")=="complex" and base.get("profile_ref"):
            from .profile_library import profile_by_id
            base["profile_data"]=profile_by_id(base["profile_ref"])
        controller._load_fields(base);controller.values_changed()


class ElementPresetPanel(QWidget):
    LABELS={"wall":"Parede","slab":"Laje","beam":"Viga","column":"Pilar"}
    def __init__(self,kind,controller,parent=None):
        super().__init__(parent or controller.panel);self.kind=kind;self.controller=controller;self._rows=[]
        lay=QVBoxLayout(self);lay.setContentsMargins(0,4,0,5);lay.setSpacing(4)
        title=QLabel(f"<b>Biblioteca · {self.LABELS.get(kind,kind)}</b>");lay.addWidget(title)
        self.combo=QComboBox();self.combo.currentIndexChanged.connect(self._sync);lay.addWidget(self.combo)
        row=QHBoxLayout();self.apply_btn=QPushButton("Aplicar");self.save_btn=QPushButton("Salvar como…");self.rename_btn=QPushButton("Renomear");row.addWidget(self.apply_btn);row.addWidget(self.save_btn);row.addWidget(self.rename_btn);lay.addLayout(row)
        row2=QHBoxLayout();self.delete_btn=QPushButton("Excluir");self.export_btn=QPushButton("Exportar…");self.import_btn=QPushButton("Importar…");row2.addWidget(self.delete_btn);row2.addWidget(self.export_btn);row2.addWidget(self.import_btn);lay.addLayout(row2)
        self.info=QLabel();self.info.setWordWrap(True);self.info.setStyleSheet("color:#777;font-size:9pt;");lay.addWidget(self.info)
        self.apply_btn.clicked.connect(self.apply);self.save_btn.clicked.connect(self.save_current);self.rename_btn.clicked.connect(self.rename);self.delete_btn.clicked.connect(self.delete);self.export_btn.clicked.connect(self.export);self.import_btn.clicked.connect(self.import_file)
        self.refresh()
    def refresh(self,select_id=None):
        old=select_id if select_id is not None else self.combo.currentData();self.combo.blockSignals(True);self.combo.clear();self._rows=[]
        current_group=None;idx=-1;first_real=-1
        for item in all_for(self.kind):
            group=item.get("group") or "Outros"
            if group!=current_group:
                if self.combo.count():self.combo.insertSeparator(self.combo.count())
                self.combo.addItem(f"— {group} —",None);self.combo.model().item(self.combo.count()-1).setEnabled(False);current_group=group
            self.combo.addItem(item["name"],item["id"]);self._rows.append(item)
            if first_real<0:first_real=self.combo.count()-1
            if item["id"]==old:idx=self.combo.count()-1
        self.combo.setCurrentIndex(idx if idx>=0 else first_real);self.combo.blockSignals(False);self._sync()
    def selected(self):
        pid=self.combo.currentData()
        if pid is None:return None
        return next((x for x in all_for(self.kind) if x.get("id")==pid),None)
    def _sync(self,*_):
        p=self.selected();enabled=p is not None;personal=enabled and not p.get("builtin",False)
        self.apply_btn.setEnabled(enabled);self.rename_btn.setEnabled(personal);self.delete_btn.setEnabled(personal);self.export_btn.setEnabled(enabled)
        self.info.setText((p.get("description") or ("Preset incluído no plugin." if p and p.get("builtin") else "Preset pessoal.")) if p else "")
    def apply(self):
        p=self.selected()
        if not p:return
        try:apply_preset(self.kind,self.controller,p);self.controller.message(f"Preset '{p['name']}' aplicado.")
        except Exception as exc:self.controller.message(str(exc),error=True)
    def save_current(self):
        name,ok=QInputDialog.getText(self,t("Salvar preset"), t("Nome do preset:"))
        if not ok or not _clean_name(name):return
        item=upsert_personal(self.kind,{"name":_clean_name(name),"group":"Meus Presets","revision":1,"config":_source_values(self.kind,self.controller)})
        self.refresh(item["id"])
    def rename(self):
        p=self.selected()
        if not p or p.get("builtin"):return
        name,ok=QInputDialog.getText(self,t("Renomear preset"),t("Novo nome:"),text=p["name"])
        if not ok or not _clean_name(name):return
        p["name"]=_clean_name(name);p["revision"]=int(p.get("revision",1))+1;item=upsert_personal(self.kind,p);self.refresh(item["id"])
    def delete(self):
        p=self.selected()
        if not p or p.get("builtin"):return
        if QMessageBox.question(self,t("Excluir preset"),t(f"Excluir '{p['name']}'?"),QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        delete_personal(self.kind,p["id"]);self.refresh()
    def export(self):
        p=self.selected()
        if not p:return
        path,_=QFileDialog.getSaveFileName(self,t("Exportar preset"),f"{p['name'].replace('/','-')}.apreset","Preset Parametric Architecture (*.apreset);;JSON (*.json)")
        if not path:return
        if not Path(path).suffix:path += ".apreset"
        payload={"format":FILE_FORMAT,"version":FILE_VERSION,"preset":p}
        Path(path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    def import_file(self):
        path,_=QFileDialog.getOpenFileName(self,t("Importar preset"),"","Preset Parametric Architecture (*.apreset *.json)")
        if not path:return
        try:
            payload=json.loads(Path(path).read_text(encoding="utf-8"));p=payload.get("preset") if isinstance(payload,dict) else None
            if not isinstance(p,dict) or payload.get("format")!=FILE_FORMAT:raise ValueError("Unrecognized preset format.")
            kind=str(p.get("kind") or self.kind)
            if kind!=self.kind:raise ValueError(f"This file is a {kind} preset, not a {self.kind} preset.")
            p=copy.deepcopy(p);p["id"]=uuid.uuid4().hex;p["builtin"]=False;p["group"]="Importados";item=upsert_personal(self.kind,p);self.refresh(item["id"])
        except Exception as exc:QMessageBox.critical(self,t("Importar preset"),str(exc))


class PresetCatalogController:
    def __init__(self,controllers):
        self.panels={}
        for kind,ctrl in controllers.items():
            if ctrl is None or not hasattr(ctrl,"panel"):continue
            panel=ElementPresetPanel(kind,ctrl,ctrl.panel);ctrl.panel.layout().insertWidget(1,panel);ctrl._catalog_preset_panel=panel;self.panels[kind]=panel
