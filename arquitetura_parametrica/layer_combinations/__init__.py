# SPDX-License-Identifier: GPL-3.0-or-later
"""Layer combinations for IngeTrazo.

Extension-owned manager for named layer states and virtual layer folders.
The host still owns the actual layers; this plugin stores only:
- layer combinations (visible / locked / intersection group);
- virtual folder organisation;
- the last applied combination.

Intersection groups are intentionally extension data for now.  Other
extensions can query ``window._layer_combinations_service`` without the
IngeTrazo core needing to know architectural join semantics.
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QToolBar,
    QToolButton,
    QWidget,
)

SCHEMA_VERSION = 1
PLUGIN_VERSION = "0.3.0"


def _uid() -> str:
    return str(uuid.uuid4())


def _clean_name(value: str) -> str:
    return " ".join(str(value or "").split())


def _state(visible=True, locked=False, intersection_group=1):
    return {
        "visible": bool(visible),
        "locked": bool(locked),
        "intersection_group": max(0, int(intersection_group)),
    }


TEMPLATE_FORMAT = "ingetrazo-layer-template"
TEMPLATE_VERSION = 1
PERSONAL_TEMPLATES_KEY = "layer_combinations/personal_templates_v1"


def _folder_data(paths):
    """Build deterministic virtual-folder records from slash paths."""
    records = []
    ids = {}
    for path in paths:
        parent = None
        current = []
        for bit in [p.strip() for p in path.split("/") if p.strip()]:
            current.append(bit)
            full = " / ".join(current)
            if full not in ids:
                fid = "tpl-folder-" + str(len(ids) + 1)
                ids[full] = fid
                records.append({"id": fid, "name": bit, "parent": parent})
            parent = ids[full]
    return records, ids


def _complete_template():
    """A broad architectural office template: model, documentation and MEP."""
    layer_defs = [
        # name, folder path, default intersection group
        ("Layer 0", "00 Geral / Auxiliares", 1),
        ("GER - Eixos", "00 Geral / Referências", 0),
        ("GER - Origem & Norte", "00 Geral / Referências", 0),
        ("GER - Limites do Terreno", "00 Geral / Referências", 0),
        ("GER - Referências 2D", "00 Geral / Referências", 0),
        ("GER - Referências 3D", "00 Geral / Referências", 0),
        ("GER - XREF / Importados", "00 Geral / Referências", 0),
        ("GER - Nuvem de Pontos", "00 Geral / Referências", 0),
        ("GER - Imagens / PDF", "00 Geral / Referências", 0),

        ("ARQ - Parede", "01 Arquitetura / Envoltória", 1),
        ("ARQ - Parede Drywall", "01 Arquitetura / Interiores", 1),
        ("ARQ - Parede Cortina", "01 Arquitetura / Envoltória", 1),
        ("ARQ - Muro & Gradil", "01 Arquitetura / Envoltória", 1),
        ("ARQ - Pilar Arquitetônico", "01 Arquitetura / Interiores", 1),
        ("ARQ - Porta", "01 Arquitetura / Aberturas", 1),
        ("ARQ - Janela", "01 Arquitetura / Aberturas", 1),
        ("ARQ - Esquadria Especial", "01 Arquitetura / Aberturas", 1),
        ("ARQ - Vidro", "01 Arquitetura / Aberturas", 1),
        ("ARQ - Escada", "01 Arquitetura / Circulação", 1),
        ("ARQ - Rampa", "01 Arquitetura / Circulação", 1),
        ("ARQ - Guarda-Corpo & Corrimão", "01 Arquitetura / Circulação", 0),
        ("ARQ - Laje / Piso Base", "01 Arquitetura / Pisos", 1),
        ("ARQ - Piso Acabamento", "01 Arquitetura / Acabamentos", 0),
        ("ARQ - Rodapé", "01 Arquitetura / Acabamentos", 0),
        ("ARQ - Forro", "01 Arquitetura / Forros", 0),
        ("ARQ - Sanca / Tabica", "01 Arquitetura / Forros", 0),
        ("ARQ - Cobertura", "01 Arquitetura / Cobertura", 1),
        ("ARQ - Rufos / Calhas", "01 Arquitetura / Cobertura", 0),
        ("ARQ - Impermeabilização", "01 Arquitetura / Acabamentos", 0),
        ("ARQ - Revestimento Parede", "01 Arquitetura / Acabamentos", 0),
        ("ARQ - Soleira / Peitoril", "01 Arquitetura / Acabamentos", 0),
        ("ARQ - Louças & Metais", "01 Arquitetura / Equipamentos", 0),
        ("ARQ - Equipamentos Fixos", "01 Arquitetura / Equipamentos", 0),
        ("ARQ - Shafts", "01 Arquitetura / Interiores", 1),
        ("ARQ - Reserva Técnica", "01 Arquitetura / Interiores", 0),

        ("EST - Fundação", "02 Estrutura / Concreto", 2),
        ("EST - Pilar", "02 Estrutura / Concreto", 2),
        ("EST - Viga", "02 Estrutura / Concreto", 2),
        ("EST - Laje", "02 Estrutura / Concreto", 2),
        ("EST - Parede Estrutural", "02 Estrutura / Concreto", 2),
        ("EST - Escada", "02 Estrutura / Concreto", 2),
        ("EST - Estrutura Metálica", "02 Estrutura / Metálica", 2),
        ("EST - Pré-Moldado", "02 Estrutura / Pré-Moldado", 2),
        ("EST - Reforço", "02 Estrutura / Reforços", 2),

        ("INT - Marcenaria", "03 Interiores / Marcenaria", 0),
        ("INT - Mobiliário", "03 Interiores / Mobiliário", 0),
        ("INT - Eletrodomésticos", "03 Interiores / Equipamentos", 0),
        ("INT - Decoração", "03 Interiores / Decoração", 0),
        ("INT - Cortinas & Persianas", "03 Interiores / Decoração", 0),
        ("INT - Espelhos", "03 Interiores / Decoração", 0),
        ("INT - Luminárias Decorativas", "03 Interiores / Iluminação", 0),
        ("INT - Equipamentos Soltos", "03 Interiores / Equipamentos", 0),

        ("ELE - Eletrodutos", "04 Instalações / Elétrica", 3),
        ("ELE - Pontos", "04 Instalações / Elétrica", 0),
        ("ELE - Quadros", "04 Instalações / Elétrica", 0),
        ("ELE - Iluminação Técnica", "04 Instalações / Elétrica", 0),
        ("ELE - Tomadas & Interruptores", "04 Instalações / Elétrica", 0),
        ("ELE - SPDA", "04 Instalações / Elétrica", 3),

        ("HID - Água Fria", "04 Instalações / Hidrossanitária", 4),
        ("HID - Água Quente", "04 Instalações / Hidrossanitária", 4),
        ("HID - Esgoto", "04 Instalações / Hidrossanitária", 4),
        ("HID - Pluvial", "04 Instalações / Hidrossanitária", 4),
        ("HID - Gás", "04 Instalações / Hidrossanitária", 4),
        ("HID - Aparelhos", "04 Instalações / Hidrossanitária", 0),

        ("CLI - Dutos", "04 Instalações / Climatização", 5),
        ("CLI - Equipamentos", "04 Instalações / Climatização", 0),
        ("CLI - Grelhas & Difusores", "04 Instalações / Climatização", 0),
        ("CLI - Drenagem", "04 Instalações / Climatização", 5),

        ("INC - Sprinklers", "04 Instalações / Incêndio", 6),
        ("INC - Hidrantes", "04 Instalações / Incêndio", 6),
        ("INC - Extintores & Sinalização", "04 Instalações / Incêndio", 0),
        ("INC - Detecção / Alarme", "04 Instalações / Incêndio", 0),

        ("DAT - Dados & Telefonia", "04 Instalações / Dados & Segurança", 7),
        ("DAT - CFTV & Segurança", "04 Instalações / Dados & Segurança", 7),
        ("AUT - Automação", "04 Instalações / Dados & Segurança", 7),

        ("TER - Terreno", "05 Terreno & Paisagismo / Terreno", 8),
        ("TER - Curvas de Nível", "05 Terreno & Paisagismo / Terreno", 0),
        ("TER - Edificações Existentes", "05 Terreno & Paisagismo / Contexto", 8),
        ("TER - Muros / Divisas", "05 Terreno & Paisagismo / Contexto", 8),
        ("PAI - Pavimentação", "05 Terreno & Paisagismo / Paisagismo", 0),
        ("PAI - Vegetação", "05 Terreno & Paisagismo / Paisagismo", 0),
        ("PAI - Mobiliário Externo", "05 Terreno & Paisagismo / Paisagismo", 0),
        ("PAI - Água / Espelhos d'Água", "05 Terreno & Paisagismo / Paisagismo", 0),
        ("PAI - Iluminação Externa", "05 Terreno & Paisagismo / Paisagismo", 0),

        ("DOC - Cotas", "06 Documentação / Anotação", 0),
        ("DOC - Textos", "06 Documentação / Anotação", 0),
        ("DOC - Eixos", "06 Documentação / Anotação", 0),
        ("DOC - Níveis", "06 Documentação / Anotação", 0),
        ("DOC - Símbolos", "06 Documentação / Anotação", 0),
        ("DOC - Chamadas / Detalhes", "06 Documentação / Anotação", 0),
        ("DOC - Hachuras 2D", "06 Documentação / 2D", 0),
        ("DOC - Selos / Carimbos", "06 Documentação / Pranchas", 0),
        ("DOC - Áreas / Zonas", "06 Documentação / Anotação", 0),
        ("DOC - Revisões", "06 Documentação / Pranchas", 0),
        ("DOC - Não Imprimir", "06 Documentação / Auxiliares", 0),

        ("FAS - Existente", "07 Fases", 9),
        ("FAS - Demolir", "07 Fases", 10),
        ("FAS - Construir", "07 Fases", 11),
        ("FAS - Temporário", "07 Fases", 0),

        ("APR - Pessoas", "08 Apresentação / Entourage", 0),
        ("APR - Veículos", "08 Apresentação / Entourage", 0),
        ("APR - Vegetação 3D", "08 Apresentação / Entourage", 0),
        ("APR - Entourage", "08 Apresentação / Entourage", 0),
        ("APR - Fundos / Contexto", "08 Apresentação / Contexto", 0),

        ("AUX - Estudos", "09 Auxiliares", 0),
        ("AUX - Guias", "09 Auxiliares", 0),
        ("AUX - Volumes de Estudo", "09 Auxiliares", 0),
        ("AUX - Checagem", "09 Auxiliares", 0),
        ("AUX - Importação Temporária", "09 Auxiliares", 0),
        ("AUX - Não Imprimir", "09 Auxiliares", 0),
    ]

    folder_paths = sorted({folder for _name, folder, _group in layer_defs})
    folders, folder_ids = _folder_data(folder_paths)
    layer_names = [name for name, _folder, _group in layer_defs]
    groups = {name: group for name, _folder, group in layer_defs}
    layer_folders = {
        name: folder_ids.get(" / ".join(
            p.strip() for p in folder.split("/") if p.strip()
        ))
        for name, folder, _group in layer_defs
    }

    def pref(name):
        return name.split(" - ", 1)[0] if " - " in name else name

    def make_combo(name, show_prefixes=(), show_exact=(), lock_prefixes=(),
                   lock_exact=(), hide_exact=(), group_overrides=None):
        show_prefixes = set(show_prefixes)
        show_exact = set(show_exact)
        lock_prefixes = set(lock_prefixes)
        lock_exact = set(lock_exact)
        hide_exact = set(hide_exact)
        group_overrides = dict(group_overrides or {})
        states = {}
        for lname in layer_names:
            p = pref(lname)
            visible = (
                lname in show_exact
                or p in show_prefixes
                or lname == "Layer 0"
            )
            if lname in hide_exact:
                visible = False
            locked = visible and (
                lname in lock_exact or p in lock_prefixes
            )
            states[lname] = _state(
                visible, locked,
                group_overrides.get(lname, groups.get(lname, 0))
            )
        return {"id": _uid(), "name": name, "layers": states}

    ARQ = ("ARQ",)
    DOC = ("DOC",)
    combos = [
        make_combo(
            "00 Modelo 3D",
            ("ARQ", "EST", "INT", "ELE", "HID", "CLI", "INC", "DAT", "AUT",
             "TER", "PAI", "FAS"),
            hide_exact=("FAS - Demolir", "FAS - Temporário"),
        ),
        make_combo(
            "01 Estudo - Planta",
            ("ARQ", "INT", "TER", "PAI", "DOC", "AUX"),
            hide_exact=("DOC - Selos / Carimbos", "DOC - Revisões",
                        "DOC - Não Imprimir", "AUX - Importação Temporária"),
        ),
        make_combo(
            "01 Estudo - Corte & Elevação",
            ("ARQ", "INT", "TER", "PAI", "DOC"),
            hide_exact=("DOC - Selos / Carimbos", "DOC - Revisões"),
        ),
        make_combo(
            "02 Projeto Legal - Implantação",
            ("ARQ", "TER", "PAI", "DOC"),
            lock_prefixes=("TER",),
            hide_exact=("ARQ - Forro", "ARQ - Sanca / Tabica",
                        "DOC - Hachuras 2D", "DOC - Revisões"),
        ),
        make_combo(
            "02 Projeto Legal - Planta",
            ("ARQ", "DOC"),
            hide_exact=("ARQ - Forro", "ARQ - Sanca / Tabica",
                        "ARQ - Piso Acabamento", "DOC - Revisões"),
        ),
        make_combo(
            "02 Projeto Legal - Corte & Elevação",
            ("ARQ", "TER", "DOC"),
            lock_prefixes=("TER",),
            hide_exact=("DOC - Revisões",),
        ),
        make_combo(
            "03 Executivo - Planta",
            ("ARQ", "INT", "DOC"),
            hide_exact=("ARQ - Forro", "ARQ - Sanca / Tabica",
                        "INT - Luminárias Decorativas"),
        ),
        make_combo(
            "03 Executivo - Corte & Elevação",
            ("ARQ", "INT", "DOC"),
        ),
        make_combo(
            "03 Executivo - Forro",
            ("ARQ", "INT", "ELE", "CLI", "INC", "DOC"),
            hide_exact=(
                "ARQ - Piso Acabamento", "ARQ - Rodapé",
                "INT - Eletrodomésticos", "INT - Equipamentos Soltos",
                "ELE - Eletrodutos", "ELE - SPDA",
                "CLI - Drenagem", "INC - Hidrantes",
            ),
            lock_prefixes=("ARQ",),
        ),
        make_combo(
            "03 Executivo - Piso",
            ("ARQ", "INT", "DOC"),
            hide_exact=("ARQ - Forro", "ARQ - Sanca / Tabica"),
            lock_prefixes=("INT",),
        ),
        make_combo(
            "03 Executivo - Marcenaria",
            ("ARQ", "INT", "ELE", "HID", "DOC"),
            lock_prefixes=("ARQ", "ELE", "HID"),
            hide_exact=("ARQ - Forro", "ARQ - Cobertura",
                        "INT - Decoração", "INT - Equipamentos Soltos"),
        ),
        make_combo(
            "03 Executivo - Esquadrias",
            ("ARQ", "DOC"),
            hide_exact=("ARQ - Piso Acabamento", "ARQ - Rodapé",
                        "ARQ - Forro", "ARQ - Sanca / Tabica",
                        "ARQ - Louças & Metais", "ARQ - Equipamentos Fixos"),
        ),
        make_combo(
            "03 Executivo - Detalhes",
            ("ARQ", "INT", "DOC"),
        ),
        make_combo(
            "04 Estrutural - Planta",
            ("EST", "ARQ", "DOC"),
            lock_prefixes=("ARQ",),
            hide_exact=("ARQ - Piso Acabamento", "ARQ - Rodapé",
                        "ARQ - Forro", "ARQ - Sanca / Tabica",
                        "ARQ - Revestimento Parede"),
        ),
        make_combo(
            "04 Estrutural - Corte",
            ("EST", "ARQ", "DOC"),
            lock_prefixes=("ARQ",),
        ),
        make_combo(
            "05 Instalações - Elétrica",
            ("ELE", "ARQ", "INT", "DOC"),
            lock_prefixes=("ARQ", "INT"),
            hide_exact=("ARQ - Forro", "ARQ - Cobertura"),
        ),
        make_combo(
            "05 Instalações - Hidrossanitária",
            ("HID", "ARQ", "INT", "DOC"),
            lock_prefixes=("ARQ", "INT"),
            hide_exact=("ARQ - Forro", "ARQ - Cobertura"),
        ),
        make_combo(
            "05 Instalações - Climatização",
            ("CLI", "ARQ", "INT", "DOC"),
            lock_prefixes=("ARQ", "INT"),
        ),
        make_combo(
            "05 Instalações - Incêndio",
            ("INC", "ARQ", "INT", "DOC"),
            lock_prefixes=("ARQ", "INT"),
        ),
        make_combo(
            "05 Instalações - Dados & Segurança",
            ("DAT", "AUT", "ARQ", "INT", "DOC"),
            lock_prefixes=("ARQ", "INT"),
        ),
        make_combo(
            "06 Compatibilização - Geral",
            ("ARQ", "EST", "INT", "ELE", "HID", "CLI", "INC", "DAT", "AUT",
             "TER"),
        ),
        make_combo(
            "06 Compatibilização - Arquitetura x Estrutura",
            ("ARQ", "EST", "DOC"),
        ),
        make_combo(
            "06 Compatibilização - Arquitetura x Instalações",
            ("ARQ", "ELE", "HID", "CLI", "INC", "DAT", "AUT", "DOC"),
            lock_prefixes=("ARQ",),
        ),
        make_combo(
            "07 Situação Existente",
            ("ARQ", "INT", "TER", "DOC", "FAS"),
            hide_exact=("FAS - Demolir", "FAS - Construir", "FAS - Temporário"),
        ),
        make_combo(
            "07 Demolir & Construir",
            ("ARQ", "INT", "TER", "DOC", "FAS"),
            hide_exact=("FAS - Temporário",),
        ),
        make_combo(
            "08 Paisagismo & Implantação",
            ("ARQ", "TER", "PAI", "DOC", "APR"),
            lock_prefixes=("ARQ",),
            hide_exact=("ARQ - Forro", "ARQ - Sanca / Tabica"),
        ),
        make_combo(
            "09 Apresentação 3D",
            ("ARQ", "EST", "INT", "TER", "PAI", "APR"),
            hide_exact=("FAS - Demolir",),
        ),
        make_combo(
            "10 Quantitativos - Arquitetura",
            ("ARQ",),
            hide_exact=("ARQ - Forro", "ARQ - Sanca / Tabica",
                        "ARQ - Revestimento Parede"),
        ),
    ]

    return {
        "format": TEMPLATE_FORMAT,
        "version": TEMPLATE_VERSION,
        "name": "Arquitetura Completa",
        "description": (
            "Template amplo para projeto arquitetônico completo: estudo, legal, "
            "executivo, estrutura, interiores, instalações, paisagismo, fases, "
            "compatibilização, apresentação e quantitativos."
        ),
        "layer_names": layer_names,
        "folders": folders,
        "layer_folders": layer_folders,
        "combinations": combos,
        "default_combination": "00 Modelo 3D",
    }


def _essential_template():
    full = _complete_template()
    keep_prefixes = {"ARQ", "INT", "DOC", "TER", "PAI", "GER", "AUX"}
    keep_names = [
        n for n in full["layer_names"]
        if n == "Layer 0" or (
            " - " in n and n.split(" - ", 1)[0] in keep_prefixes
        )
    ]
    keep = set(keep_names)
    combos = []
    allowed = {
        "00 Modelo 3D", "01 Estudo - Planta", "01 Estudo - Corte & Elevação",
        "02 Projeto Legal - Implantação", "02 Projeto Legal - Planta",
        "03 Executivo - Planta", "03 Executivo - Corte & Elevação",
        "03 Executivo - Forro", "03 Executivo - Piso",
        "03 Executivo - Marcenaria", "08 Paisagismo & Implantação",
        "09 Apresentação 3D",
    }
    for combo in full["combinations"]:
        if combo["name"] in allowed:
            c = copy.deepcopy(combo)
            c["id"] = _uid()
            c["layers"] = {k: v for k, v in c["layers"].items() if k in keep}
            combos.append(c)

    used_folder_ids = {
        full["layer_folders"].get(n) for n in keep_names
        if full["layer_folders"].get(n)
    }
    # Include ancestors.
    changed = True
    while changed:
        changed = False
        for f in full["folders"]:
            if f["id"] in used_folder_ids and f.get("parent") \
                    and f["parent"] not in used_folder_ids:
                used_folder_ids.add(f["parent"])
                changed = True

    return {
        "format": TEMPLATE_FORMAT,
        "version": TEMPLATE_VERSION,
        "name": "Arquitetura Essencial",
        "description": (
            "Versão enxuta para estudos e projetos arquitetônicos sem as "
            "disciplinas completas de engenharia."
        ),
        "layer_names": keep_names,
        "folders": [
            copy.deepcopy(f) for f in full["folders"]
            if f["id"] in used_folder_ids
        ],
        "layer_folders": {
            k: v for k, v in full["layer_folders"].items() if k in keep
        },
        "combinations": combos,
        "default_combination": "00 Modelo 3D",
    }


def builtin_templates():
    return {
        "Arquitetura Completa": _complete_template(),
        "Arquitetura Essencial": _essential_template(),
    }


class TemplateDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent or controller.app.window)
        self.controller = controller
        self.setWindowTitle("Templates de Camadas e Combinações")
        self.resize(760, 470)
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addWidget(QLabel(
            "<b>Templates de Camadas e Combinações</b><br>"
            "<span style='color:gray'>Os templates pessoais ficam disponíveis "
            "em todos os projetos deste computador e também podem ser "
            "exportados para arquivo.</span>"
        ))

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selection_changed)
        root.addWidget(self.list, 1)

        self.description = QLabel("")
        self.description.setWordWrap(True)
        self.description.setStyleSheet("color: gray;")
        root.addWidget(self.description)

        row1 = QHBoxLayout()
        self.apply_btn = QPushButton("Aplicar ao projeto")
        self.save_btn = QPushButton("Salvar projeto como template…")
        self.export_btn = QPushButton("Exportar…")
        self.import_btn = QPushButton("Importar…")
        for b in (self.apply_btn, self.save_btn, self.export_btn, self.import_btn):
            row1.addWidget(b)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        self.delete_btn = QPushButton("Excluir template pessoal")
        row2.addWidget(self.delete_btn)
        row2.addStretch(1)
        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        row2.addWidget(close)
        root.addLayout(row2)

        self.apply_btn.clicked.connect(self._apply)
        self.save_btn.clicked.connect(self._save_current)
        self.export_btn.clicked.connect(self._export)
        self.import_btn.clicked.connect(self._import)
        self.delete_btn.clicked.connect(self._delete)

    def refresh(self, select_name=None):
        self.list.clear()
        for name, tpl in builtin_templates().items():
            item = QListWidgetItem(f"{name}  [incluído]")
            item.setData(Qt.UserRole, ("builtin", name))
            self.list.addItem(item)
            if name == select_name:
                self.list.setCurrentItem(item)

        for name in sorted(self.controller.personal_templates(),
                           key=str.casefold):
            item = QListWidgetItem(f"{name}  [pessoal]")
            item.setData(Qt.UserRole, ("personal", name))
            self.list.addItem(item)
            if name == select_name:
                self.list.setCurrentItem(item)

        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def _selected(self):
        item = self.list.currentItem()
        if not item:
            return None, None, None
        kind, name = item.data(Qt.UserRole)
        if kind == "builtin":
            tpl = builtin_templates().get(name)
        else:
            tpl = self.controller.personal_templates().get(name)
        return kind, name, copy.deepcopy(tpl) if tpl else None

    def _selection_changed(self, *_):
        kind, name, tpl = self._selected()
        self.delete_btn.setEnabled(kind == "personal")
        if not tpl:
            self.description.setText("")
            return
        self.description.setText(
            f"{tpl.get('description', '')}\n\n"
            f"{len(tpl.get('layer_names', []))} camadas • "
            f"{len(tpl.get('combinations', []))} combinações"
        )

    def _apply(self):
        _kind, _name, tpl = self._selected()
        if not tpl:
            return
        answer = QMessageBox.question(
            self, "Aplicar template",
            "O template criará as camadas que ainda não existem e substituirá "
            "a organização de pastas e as combinações deste plugin.\n\n"
            "Camadas já existentes e geometria do projeto não serão apagadas.\n\n"
            "Aplicar?"
        )
        if answer != QMessageBox.Yes:
            return
        self.controller.apply_template(tpl)
        QMessageBox.information(
            self, "Template aplicado",
            "Template aplicado ao projeto."
        )

    def _save_current(self):
        name, ok = QInputDialog.getText(
            self, "Salvar template pessoal", "Nome do template:"
        )
        name = _clean_name(name)
        if not ok or not name:
            return
        existing = self.controller.personal_templates()
        if name in existing:
            if QMessageBox.question(
                self, "Substituir template",
                f"Já existe um template pessoal chamado '{name}'. Substituir?"
            ) != QMessageBox.Yes:
                return
        tpl = self.controller.project_template(name)
        self.controller.save_personal_template(name, tpl)
        self.refresh(select_name=name)

    def _export(self):
        _kind, name, tpl = self._selected()
        if not tpl:
            return
        suggested = (name or "template").replace("/", "-") + ".iglayer"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar template", suggested,
            "Template de Camadas do IngeTrazo (*.iglayer);;JSON (*.json)"
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".iglayer"
        Path(path).write_text(
            json.dumps(tpl, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar template", "",
            "Template de Camadas do IngeTrazo (*.iglayer *.json)"
        )
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            tpl = self.controller.validate_template(raw)
        except Exception as exc:
            QMessageBox.critical(
                self, "Importar template", f"Arquivo inválido:\n{exc}"
            )
            return
        name = _clean_name(tpl.get("name")) or Path(path).stem
        existing = self.controller.personal_templates()
        if name in existing and QMessageBox.question(
            self, "Importar template",
            f"Já existe um template pessoal chamado '{name}'. Substituir?"
        ) != QMessageBox.Yes:
            return
        self.controller.save_personal_template(name, tpl)
        self.refresh(select_name=name)

    def _delete(self):
        kind, name, _tpl = self._selected()
        if kind != "personal" or not name:
            return
        if QMessageBox.question(
            self, "Excluir template pessoal",
            f"Excluir o template pessoal '{name}'?"
        ) != QMessageBox.Yes:
            return
        self.controller.delete_personal_template(name)
        self.refresh()


class LayerCombinationsService:
    """Small plugin-owned API for architectural extensions."""

    def __init__(self, controller):
        self._controller = controller

    def applied_combination_id(self):
        return self._controller.data.get("applied_id")

    def applied_combination_name(self):
        combo = self._controller._combo_by_id(self.applied_combination_id())
        return combo.get("name") if combo else None

    def intersection_group(self, layer_name: str, combo_id=None) -> int:
        if combo_id is None:
            combo_id = self.applied_combination_id()
        combo = self._controller._combo_by_id(combo_id)
        if not combo:
            return 1
        raw = combo.get("layers", {}).get(str(layer_name), {})
        try:
            return max(0, int(raw.get("intersection_group", 1)))
        except Exception:
            return 1

    def can_intersect(self, layer_a: str, layer_b: str, combo_id=None) -> bool:
        a = self.intersection_group(layer_a, combo_id)
        b = self.intersection_group(layer_b, combo_id)
        return a != 0 and a == b

    def combinations(self):
        return copy.deepcopy(self._controller.data.get("combinations", []))


class ViewportCombinationBar:
    """Native bottom toolbar, immediately above Model / Sheet tabs."""

    def __init__(self, controller):
        self.controller = controller
        self._updating = False

        win = controller.app.window

        # A real QMainWindow toolbar: unlike a child of QOpenGLWidget it cannot
        # be overpainted by the viewport. BottomToolBarArea places it directly
        # above IngeTrazo's status bar, which contains Model | Sheet 1 | ...
        old = win.findChild(QToolBar, "layerCombinationsBottomBar")
        if old is not None:
            win.removeToolBar(old)
            old.deleteLater()

        self.toolbar = QToolBar("Combinação de Camadas", win)
        self.toolbar.setObjectName("layerCombinationsBottomBar")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setAllowedAreas(Qt.BottomToolBarArea)
        self.toolbar.setStyleSheet("""
            QToolBar {
                spacing: 5px;
                padding: 2px 6px;
                border-top: 1px solid rgba(127, 127, 127, 80);
            }
            QComboBox {
                min-height: 23px;
                padding-left: 6px;
                padding-right: 22px;
            }
            QToolButton {
                min-width: 27px;
                min-height: 24px;
                padding: 0px;
            }
        """)

        self.label = QLabel("Combinação de Camadas:")
        self.toolbar.addWidget(self.label)

        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        self.combo.setMaximumWidth(430)
        self.combo.currentIndexChanged.connect(self._selected)
        self.toolbar.addWidget(self.combo)

        self.manage = QToolButton()
        self.manage.setText("⚙")
        self.manage.setToolTip("Gerenciar combinações de camadas")
        self.manage.clicked.connect(controller.show)
        self.toolbar.addWidget(self.manage)

        win.addToolBar(Qt.BottomToolBarArea, self.toolbar)
        self.toolbar.show()
        self.refresh()

    def refresh(self):
        applied = self.controller.data.get("applied_id")
        combos = self.controller.data.get("combinations", [])

        self._updating = True
        try:
            self.combo.clear()
            selected_index = -1
            for i, combo in enumerate(combos):
                text = combo.get("name", "Combinação")
                if combo.get("id") == applied:
                    if not self.controller.combo_matches_scene(combo):
                        text += "  • modificada"
                    selected_index = i
                self.combo.addItem(text, combo.get("id"))

            if selected_index >= 0:
                self.combo.setCurrentIndex(selected_index)
            elif self.combo.count():
                self.combo.setCurrentIndex(-1)
                self.combo.setPlaceholderText("Estado atual")
        finally:
            self._updating = False

    def _selected(self, index):
        if self._updating or index < 0:
            return
        combo_id = self.combo.itemData(index)
        if combo_id:
            self.controller.apply_combo(combo_id)


class InitialTemplateDialog(QDialog):
    """First-run choice for a document that has no layer-combination data."""

    def __init__(self, controller):
        super().__init__(controller.app.window)
        self.controller = controller
        self.choice = None
        self.setWindowTitle("Escolher Template de Camadas")
        self.setModal(True)
        self.resize(520, 330)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel(
            "<b>Como este projeto deve começar?</b><br>"
            "<span style='color:gray'>Escolha um template de camadas e "
            "combinações. Esta escolha vale apenas para este projeto.</span>"
        )
        title.setWordWrap(True)
        root.addWidget(title)

        self.list = QListWidget()
        root.addWidget(self.list, 1)

        self.description = QLabel("")
        self.description.setWordWrap(True)
        self.description.setStyleSheet("color: gray;")
        root.addWidget(self.description)

        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("Começar vazio")
        self.apply_btn = QPushButton("Usar template")
        self.apply_btn.setDefault(True)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.apply_btn)
        root.addLayout(row)

        self.list.currentItemChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(lambda *_: self._accept_template())
        self.apply_btn.clicked.connect(self._accept_template)
        self.cancel_btn.clicked.connect(self._empty)

        self._populate()

    def _populate(self):
        for name, tpl in builtin_templates().items():
            item = QListWidgetItem(f"{name}  [incluído]")
            item.setData(Qt.UserRole, ("builtin", name))
            self.list.addItem(item)

        for name in sorted(self.controller.personal_templates(), key=str.casefold):
            item = QListWidgetItem(f"{name}  [pessoal]")
            item.setData(Qt.UserRole, ("personal", name))
            self.list.addItem(item)

        if self.list.count():
            self.list.setCurrentRow(0)

    def _selected_template(self):
        item = self.list.currentItem()
        if not item:
            return None
        kind, name = item.data(Qt.UserRole)
        if kind == "builtin":
            return copy.deepcopy(builtin_templates().get(name))
        return copy.deepcopy(self.controller.personal_templates().get(name))

    def _selection_changed(self, *_):
        tpl = self._selected_template()
        if not tpl:
            self.description.setText("")
            return
        self.description.setText(
            f"{tpl.get('description', '')}\n\n"
            f"{len(tpl.get('layer_names', []))} camadas • "
            f"{len(tpl.get('combinations', []))} combinações"
        )

    def _accept_template(self):
        tpl = self._selected_template()
        if tpl:
            self.choice = tpl
            self.accept()

    def _empty(self):
        self.choice = None
        self.accept()


class ManagerDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.app.window)
        self.controller = controller
        self.setWindowTitle("Combinação de Camadas")
        self.setModal(False)
        self.resize(1080, 680)
        self.setMinimumSize(820, 520)
        self._updating = False
        self._layer_items = {}
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel(
            "<b>Combinação de Camadas</b> — visibilidade, bloqueio e grupo "
            "de interseção por combinação"
        )
        root.addWidget(title)

        main = QSplitter(Qt.Horizontal)
        root.addWidget(main, 1)

        # Left: combinations
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        ll.addWidget(QLabel("<b>Combinações</b>"))

        self.combo_list = QListWidget()
        self.combo_list.currentItemChanged.connect(self._combo_selected)
        ll.addWidget(self.combo_list, 1)

        combo_buttons = QHBoxLayout()
        self.combo_new = QPushButton("Novo")
        self.combo_dup = QPushButton("Duplicar")
        self.combo_ren = QPushButton("Renomear")
        self.combo_del = QPushButton("Excluir")
        for b in (self.combo_new, self.combo_dup, self.combo_ren, self.combo_del):
            combo_buttons.addWidget(b)
        ll.addLayout(combo_buttons)

        self.combo_apply = QPushButton("Aplicar combinação")
        self.combo_update = QPushButton("Atualizar pelo estado atual")
        self.templates_btn = QPushButton("Templates…")
        ll.addWidget(self.combo_apply)
        ll.addWidget(self.combo_update)
        ll.addWidget(self.templates_btn)

        self.combo_new.clicked.connect(self._new_combo)
        self.combo_dup.clicked.connect(self._duplicate_combo)
        self.combo_ren.clicked.connect(self._rename_combo)
        self.combo_del.clicked.connect(self._delete_combo)
        self.combo_apply.clicked.connect(self._apply_combo)
        self.combo_update.clicked.connect(self._capture_combo)
        self.templates_btn.clicked.connect(self.controller.show_templates)

        main.addWidget(left)

        # Right: virtual folders over the layer table
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        rl.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Camadas</b>"))
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Procurar camadas")
        self.search.textChanged.connect(self._refresh_layers)
        head.addWidget(self.search, 1)
        rl.addLayout(head)

        vertical = QSplitter(Qt.Vertical)
        rl.addWidget(vertical, 1)

        folders_box = QWidget()