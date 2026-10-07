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


try:
    from ..i18n import translate_widget as _translate_opentrace_widget
except Exception:
    def _translate_opentrace_widget(_widget):
        return None


class TemplateDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent or controller.app.window)
        self.controller = controller
        self.setWindowTitle("Templates de Camadas e Combinações")
        self.resize(760, 470)
        self._build()
        self.refresh()
        _translate_opentrace_widget(self)

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
        self.refresh()
        _translate_opentrace_widget(self.toolbar)
        self.toolbar.show()

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
        _translate_opentrace_widget(self)

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
        _translate_opentrace_widget(self)

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
        fl = QVBoxLayout(folders_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(4)

        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setRootIsDecorated(True)
        self.folder_tree.currentItemChanged.connect(
            lambda *_: self._refresh_layers()
        )
        fl.addWidget(self.folder_tree, 1)

        fbuttons = QHBoxLayout()
        self.folder_new = QPushButton("+ Pasta")
        self.folder_ren = QPushButton("Renomear")
        self.folder_del = QPushButton("Excluir")
        for b in (self.folder_new, self.folder_ren, self.folder_del):
            fbuttons.addWidget(b)
        fbuttons.addStretch(1)
        fl.addLayout(fbuttons)

        self.folder_new.clicked.connect(self._new_folder)
        self.folder_ren.clicked.connect(self._rename_folder)
        self.folder_del.clicked.connect(self._delete_folder)
        vertical.addWidget(folders_box)

        layers_box = QWidget()
        tbl = QVBoxLayout(layers_box)
        tbl.setContentsMargins(0, 0, 0, 0)
        tbl.setSpacing(4)

        self.layers = QTreeWidget()
        self.layers.setColumnCount(4)
        self.layers.setHeaderLabels(
            ["Nome", "Visível", "Bloqueada", "Interseção"]
        )
        self.layers.setRootIsDecorated(False)
        self.layers.setAlternatingRowColors(True)
        self.layers.setSelectionMode(QAbstractItemView.SingleSelection)
        self.layers.itemChanged.connect(self._layer_item_changed)
        header = self.layers.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        tbl.addWidget(self.layers, 1)

        lbuttons = QHBoxLayout()
        self.layer_new = QPushButton("+ Camada")
        self.layer_ren = QPushButton("Renomear")
        self.layer_del = QPushButton("Excluir")
        self.layer_move = QPushButton("Mover para pasta…")
        for b in (self.layer_new, self.layer_ren, self.layer_del, self.layer_move):
            lbuttons.addWidget(b)
        lbuttons.addStretch(1)
        tbl.addLayout(lbuttons)

        self.layer_new.clicked.connect(self._new_layer)
        self.layer_ren.clicked.connect(self._rename_layer)
        self.layer_del.clicked.connect(self._delete_layer)
        self.layer_move.clicked.connect(self._move_layer)

        vertical.addWidget(layers_box)
        vertical.setSizes([180, 390])

        main.addWidget(right)
        main.setSizes([330, 730])

        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setStyleSheet("color: gray;")
        foot.addWidget(self.status, 1)
        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        foot.addWidget(close)
        root.addLayout(foot)

    # --------------------------------------------------------------- refresh
    def refresh(self, keep_combo=True):
        selected = self.current_combo_id() if keep_combo else None
        self._updating = True
        try:
            self.controller.sync_with_scene(save=False)
            self.combo_list.clear()
            applied = self.controller.data.get("applied_id")
            for combo in self.controller.data.get("combinations", []):
                text = combo["name"]
                if combo["id"] == applied:
                    text += "  ✓"
                    if not self.controller.combo_matches_scene(combo):
                        text += "  • Modificado"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, combo["id"])
                self.combo_list.addItem(item)
                if combo["id"] == selected:
                    self.combo_list.setCurrentItem(item)
            if self.combo_list.currentItem() is None and self.combo_list.count():
                self.combo_list.setCurrentRow(0)
            self._refresh_folders()
            self._refresh_layers()
            self._refresh_status()
        finally:
            self._updating = False

    def _refresh_status(self):
        applied = self.controller._combo_by_id(
            self.controller.data.get("applied_id")
        )
        if not applied:
            self.status.setText("Nenhuma combinação aplicada.")
            return
        suffix = (
            " — modificado no modelo"
            if not self.controller.combo_matches_scene(applied)
            else ""
        )
        self.status.setText(f"Aplicada: {applied['name']}{suffix}")

    def _refresh_folders(self):
        selected_id = self.current_folder_id()
        self.folder_tree.clear()

        all_item = QTreeWidgetItem(["Todas as camadas"])
        all_item.setData(0, Qt.UserRole, "__all__")
        self.folder_tree.addTopLevelItem(all_item)

        no_item = QTreeWidgetItem(["Sem pasta"])
        no_item.setData(0, Qt.UserRole, None)
        self.folder_tree.addTopLevelItem(no_item)

        by_parent = {}
        for f in self.controller.data.get("folders", []):
            by_parent.setdefault(f.get("parent"), []).append(f)
        for lst in by_parent.values():
            lst.sort(key=lambda x: x["name"].casefold())

        def add_children(parent_item, parent_id):
            for f in by_parent.get(parent_id, []):
                it = QTreeWidgetItem([f["name"]])
                it.setData(0, Qt.UserRole, f["id"])
                parent_item.addChild(it)
                add_children(it, f["id"])

        for f in by_parent.get(None, []):
            it = QTreeWidgetItem([f["name"]])
            it.setData(0, Qt.UserRole, f["id"])
            self.folder_tree.addTopLevelItem(it)
            add_children(it, f["id"])

        self.folder_tree.expandAll()

        target = self._find_folder_item(selected_id)
        self.folder_tree.setCurrentItem(target or all_item)

    def _find_folder_item(self, folder_id):
        def walk(item):
            if item.data(0, Qt.UserRole) == folder_id:
                return item
            for i in range(item.childCount()):
                got = walk(item.child(i))
                if got:
                    return got
            return None
        for i in range(self.folder_tree.topLevelItemCount()):
            got = walk(self.folder_tree.topLevelItem(i))
            if got:
                return got
        return None

    def _refresh_layers(self):
        if not hasattr(self, "layers"):
            return
        combo = self.current_combo()
        folder_id = self.current_folder_id()
        query = self.search.text().strip().casefold() if hasattr(self, "search") else ""

        self._updating = True
        try:
            self.layers.clear()
            self._layer_items.clear()
            if not combo:
                return
            mapping = self.controller.data.get("layer_folders", {})
            scene_layers = sorted(
                self.controller.scene.layers,
                key=lambda ly: ly.name.casefold()
            )
            for ly in scene_layers:
                if folder_id != "__all__" and mapping.get(ly.name) != folder_id:
                    continue
                if query and query not in ly.name.casefold():
                    continue

                st = combo.setdefault("layers", {}).setdefault(
                    ly.name, _state(ly.visible, ly.locked, 1)
                )
                item = QTreeWidgetItem([ly.name, "", "", ""])
                item.setData(0, Qt.UserRole, ly.name)
                item.setFlags(
                    item.flags()
                    | Qt.ItemIsUserCheckable
                    | Qt.ItemIsSelectable
                    | Qt.ItemIsEnabled
                )
                item.setCheckState(
                    1, Qt.Checked if st.get("visible", True) else Qt.Unchecked
                )
                item.setCheckState(
                    2, Qt.Checked if st.get("locked", False) else Qt.Unchecked
                )
                self.layers.addTopLevelItem(item)

                spin = QSpinBox(self.layers)
                spin.setRange(0, 999)
                spin.setValue(int(st.get("intersection_group", 1)))
                spin.setToolTip(
                    "0 = não participa de interseções automáticas.\n"
                    "Elementos em camadas com o mesmo número podem interagir."
                )
                spin.valueChanged.connect(
                    lambda value, name=ly.name: self._intersection_changed(
                        name, value
                    )
                )
                self.layers.setItemWidget(item, 3, spin)
                self._layer_items[ly.name] = item
        finally:
            self._updating = False

    # ---------------------------------------------------------- combo helpers
    def current_combo_id(self):
        item = self.combo_list.currentItem() if hasattr(self, "combo_list") else None
        return item.data(Qt.UserRole) if item else None

    def current_combo(self):
        return self.controller._combo_by_id(self.current_combo_id())

    def current_folder_id(self):
        item = (
            self.folder_tree.currentItem()
            if hasattr(self, "folder_tree") else None
        )
        return item.data(0, Qt.UserRole) if item else "__all__"

    def _combo_selected(self, *_):
        if not self._updating:
            self._refresh_layers()

    # ---------------------------------------------------------- combinations
    def _new_combo(self):
        name, ok = QInputDialog.getText(
            self, "Nova combinação", "Nome da combinação:"
        )
        name = _clean_name(name)
        if not ok or not name:
            return
        if self.controller.combo_name_exists(name):
            QMessageBox.warning(self, "Combinações", "Esse nome já existe.")
            return
        combo = self.controller.snapshot_combo(name)
        self.controller.data["combinations"].append(combo)
        self.controller.save_data()
        self.refresh(False)
        self._select_combo(combo["id"])

    def _duplicate_combo(self):
        src = self.current_combo()
        if not src:
            return
        name, ok = QInputDialog.getText(
            self, "Duplicar combinação", "Nome:", text=f"{src['name']} - Cópia"
        )
        name = _clean_name(name)
        if not ok or not name:
            return
        if self.controller.combo_name_exists(name):
            QMessageBox.warning(self, "Combinações", "Esse nome já existe.")
            return
        dup = copy.deepcopy(src)
        dup["id"] = _uid()
        dup["name"] = name
        self.controller.data["combinations"].append(dup)
        self.controller.save_data()
        self.refresh(False)
        self._select_combo(dup["id"])

    def _rename_combo(self):
        combo = self.current_combo()
        if not combo:
            return
        name, ok = QInputDialog.getText(
            self, "Renomear combinação", "Nome:", text=combo["name"]
        )
        name = _clean_name(name)
        if not ok or not name or name == combo["name"]:
            return
        if self.controller.combo_name_exists(name, except_id=combo["id"]):
            QMessageBox.warning(self, "Combinações", "Esse nome já existe.")
            return
        combo["name"] = name
        self.controller.save_data()
        self.refresh()

    def _delete_combo(self):
        combo = self.current_combo()
        if not combo:
            return
        if len(self.controller.data["combinations"]) <= 1:
            QMessageBox.information(
                self, "Combinações", "Mantenha pelo menos uma combinação."
            )
            return
        if QMessageBox.question(
            self, "Excluir combinação",
            f"Excluir '{combo['name']}'?"
        ) != QMessageBox.Yes:
            return
        self.controller.data["combinations"] = [
            c for c in self.controller.data["combinations"]
            if c["id"] != combo["id"]
        ]
        if self.controller.data.get("applied_id") == combo["id"]:
            self.controller.data["applied_id"] = None
        self.controller.save_data()
        self.refresh(False)

    def _apply_combo(self):
        combo = self.current_combo()
        if combo:
            self.controller.apply_combo(combo["id"])
            self.refresh()

    def _capture_combo(self):
        combo = self.current_combo()
        if not combo:
            return
        combo["layers"] = self.controller.snapshot_layer_states(
            keep_groups_from=combo
        )
        self.controller.save_data()
        self.refresh()

    def _select_combo(self, combo_id):
        for i in range(self.combo_list.count()):
            item = self.combo_list.item(i)
            if item.data(Qt.UserRole) == combo_id:
                self.combo_list.setCurrentItem(item)
                return

    # --------------------------------------------------------------- folders
    def _new_folder(self):
        parent = self.current_folder_id()
        if parent in ("__all__", None):
            parent = None
        name, ok = QInputDialog.getText(self, "Nova pasta", "Nome da pasta:")
        name = _clean_name(name)
        if not ok or not name:
            return
        if self.controller.folder_name_exists(name, parent):
            QMessageBox.warning(
                self, "Pastas", "Já existe uma pasta com esse nome aqui."
            )
            return
        folder = {"id": _uid(), "name": name, "parent": parent}
        self.controller.data["folders"].append(folder)
        self.controller.save_data()
        self._refresh_folders()
        self.folder_tree.setCurrentItem(self._find_folder_item(folder["id"]))

    def _rename_folder(self):
        fid = self.current_folder_id()
        folder = self.controller._folder_by_id(fid)
        if not folder:
            return
        name, ok = QInputDialog.getText(
            self, "Renomear pasta", "Nome:", text=folder["name"]
        )
        name = _clean_name(name)
        if not ok or not name or name == folder["name"]:
            return
        if self.controller.folder_name_exists(
            name, folder.get("parent"), except_id=fid
        ):
            QMessageBox.warning(
                self, "Pastas", "Já existe uma pasta com esse nome aqui."
            )
            return
        folder["name"] = name
        self.controller.save_data()
        self._refresh_folders()

    def _delete_folder(self):
        fid = self.current_folder_id()
        folder = self.controller._folder_by_id(fid)
        if not folder:
            return
        if QMessageBox.question(
            self, "Excluir pasta",
            "A pasta será removida. As camadas nela ficarão sem pasta.\n"
            "Subpastas também serão removidas. Continuar?"
        ) != QMessageBox.Yes:
            return
        doomed = self.controller.descendant_folder_ids(fid) | {fid}
        self.controller.data["folders"] = [
            f for f in self.controller.data["folders"]
            if f["id"] not in doomed
        ]
        mapping = self.controller.data["layer_folders"]
        for name, assigned in list(mapping.items()):
            if assigned in doomed:
                mapping[name] = None
        self.controller.save_data()
        self._refresh_folders()
        self._refresh_layers()

    # ---------------------------------------------------------------- layers
    def selected_layer_name(self):
        item = self.layers.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def _layer_item_changed(self, item, column):
        if self._updating or column not in (1, 2):
            return
        combo = self.current_combo()
        if not combo:
            return
        name = item.data(0, Qt.UserRole)
        st = combo["layers"].setdefault(name, _state())
        st["visible"] = item.checkState(1) == Qt.Checked
        st["locked"] = item.checkState(2) == Qt.Checked
        self.controller.save_data()
        self._refresh_status()

    def _intersection_changed(self, name, value):
        if self._updating:
            return
        combo = self.current_combo()
        if not combo:
            return
        combo["layers"].setdefault(name, _state())["intersection_group"] = int(value)
        self.controller.save_data()

    def _new_layer(self):
        name, ok = QInputDialog.getText(self, "Nova camada", "Nome da camada:")
        name = _clean_name(name)
        if not ok or not name:
            return
        if self.controller.scene.layer(name) is not None:
            QMessageBox.warning(self, "Camadas", "Essa camada já existe.")
            return
        self.controller.add_layer(name, self.current_folder_id())
        self.refresh()

    def _rename_layer(self):
        old = self.selected_layer_name()
        if not old:
            return
        from core.layers import DEFAULT_LAYER
        if old == DEFAULT_LAYER:
            QMessageBox.information(
                self, "Camadas", "A camada padrão não pode ser renomeada."
            )
            return
        name, ok = QInputDialog.getText(
            self, "Renomear camada", "Nome:", text=old
        )
        name = _clean_name(name)
        if not ok or not name or name == old:
            return
        if self.controller.scene.layer(name) is not None:
            QMessageBox.warning(self, "Camadas", "Essa camada já existe.")
            return
        self.controller.rename_layer(old, name)
        self.refresh()

    def _delete_layer(self):
        name = self.selected_layer_name()
        if not name:
            return
        from core.layers import DEFAULT_LAYER
        if name == DEFAULT_LAYER:
            QMessageBox.information(
                self, "Camadas", "A camada padrão não pode ser excluída."
            )
            return
        if QMessageBox.question(
            self, "Excluir camada",
            f"Excluir '{name}'?\n\nOs elementos serão movidos para "
            f"'{DEFAULT_LAYER}'."
        ) != QMessageBox.Yes:
            return
        self.controller.delete_layer(name)
        self.refresh()

    def _move_layer(self):
        name = self.selected_layer_name()
        if not name:
            return
        folders = self.controller.flat_folder_paths()
        labels = ["Sem pasta"] + [path for _id, path in folders]
        choice, ok = QInputDialog.getItem(
            self, "Mover camada", f"Pasta para '{name}':",
            labels, editable=False
        )
        if not ok:
            return
        fid = None
        if choice != "Sem pasta":
            for folder_id, path in folders:
                if path == choice:
                    fid = folder_id
                    break
        self.controller.data["layer_folders"][name] = fid
        self.controller.save_data()
        self._refresh_layers()


class Controller:
    def __init__(self, app):
        self.app = app
        self.scene = app.scene
        self.dialog = None
        self.template_dialog = None
        self._saving = False
        self._initial_prompt_pending = False
        self._initial_prompt_running = False
        self.data = self._load_data()
        # IMPORTANT: when this is a brand-new document, do NOT persist the
        # temporary "Modelo 3D" placeholder before the template chooser runs.
        # Doing so makes the subsequent document-changed callback believe the
        # project was already configured and suppresses the first-run prompt.
        self.sync_with_scene(save=not self._initial_prompt_pending)
        self.service = LayerCombinationsService(self)
        setattr(app.window, "_layer_combinations_service", self.service)
        self.bar = ViewportCombinationBar(self)
        app.on_document_changed(self._document_changed)
        if self._initial_prompt_pending:
            QTimer.singleShot(0, self._show_initial_template_prompt)

    # --------------------------------------------------------------- document
    def _load_data(self):
        raw = self.app.document_data(default=None)
        if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
            self._initial_prompt_pending = True
            combo = self.snapshot_combo("Modelo 3D")
            return {
                "schema_version": SCHEMA_VERSION,
                "folders": [],
                "layer_folders": {},
                "combinations": [combo],
                "applied_id": combo["id"],
            }

        self._initial_prompt_pending = False
        data = copy.deepcopy(raw)
        data.setdefault("folders", [])
        data.setdefault("layer_folders", {})
        data.setdefault("combinations", [])
        data.setdefault("applied_id", None)
        if not data["combinations"]:
            combo = self.snapshot_combo("Modelo 3D")
            data["combinations"] = [combo]
            data["applied_id"] = combo["id"]
        return data

    def save_data(self):
        if self._saving:
            return
        self._saving = True
        try:
            self.app.set_document_data(copy.deepcopy(self.data))
        finally:
            self._saving = False
        bar = getattr(self, "bar", None)
        if bar is not None:
            try:
                bar.refresh()
            except RuntimeError:
                self.bar = None

    def _document_changed(self):
        if self._saving:
            return
        # New/Open may replace plugin_data and the Scene behind the viewport.
        self.scene = self.app.scene
        self.data = self._load_data()
        self.sync_with_scene(save=False)
        if self._initial_prompt_pending and not self._initial_prompt_running:
            QTimer.singleShot(0, self._show_initial_template_prompt)
        if self.dialog is not None:
            try:
                self.dialog.refresh()
            except RuntimeError:
                self.dialog = None
        bar = getattr(self, "bar", None)
        if bar is not None:
            try:
                bar.refresh()
            except RuntimeError:
                self.bar = None

    def sync_with_scene(self, save=False):
        names = [ly.name for ly in self.scene.layers]
        changed = False
        mapping = self.data.setdefault("layer_folders", {})
        for name in names:
            if name not in mapping:
                mapping[name] = None
                changed = True

        # Keep missing layer metadata: it may become useful again after an
        # import or a layer recreated under the same name.
        for combo in self.data.setdefault("combinations", []):
            states = combo.setdefault("layers", {})
            for ly in self.scene.layers:
                if ly.name not in states:
                    states[ly.name] = _state(ly.visible, ly.locked, 1)
                    changed = True
        if changed and save:
            self.save_data()

    # -------------------------------------------------------------- utilities
    def _combo_by_id(self, combo_id):
        for combo in self.data.get("combinations", []):
            if combo.get("id") == combo_id:
                return combo
        return None

    def _folder_by_id(self, folder_id):
        for folder in self.data.get("folders", []):
            if folder.get("id") == folder_id:
                return folder
        return None

    def combo_name_exists(self, name, except_id=None):
        key = name.casefold()
        return any(
            c["id"] != except_id and c["name"].casefold() == key
            for c in self.data.get("combinations", [])
        )

    def folder_name_exists(self, name, parent, except_id=None):
        key = name.casefold()
        return any(
            f["id"] != except_id
            and f.get("parent") == parent
            and f["name"].casefold() == key
            for f in self.data.get("folders", [])
        )

    def descendant_folder_ids(self, folder_id):
        out = set()
        again = True
        while again:
            again = False
            for f in self.data.get("folders", []):
                if f["id"] not in out and (
                    f.get("parent") == folder_id or f.get("parent") in out
                ):
                    out.add(f["id"])
                    again = True
        return out

    def flat_folder_paths(self):
        out = []
        def path_for(folder):
            bits = [folder["name"]]
            seen = {folder["id"]}
            parent = folder.get("parent")
            while parent:
                p = self._folder_by_id(parent)
                if not p or p["id"] in seen:
                    break
                bits.append(p["name"])
                seen.add(p["id"])
                parent = p.get("parent")
            return " / ".join(reversed(bits))
        for f in self.data.get("folders", []):
            out.append((f["id"], path_for(f)))
        return sorted(out, key=lambda x: x[1].casefold())

    # --------------------------------------------------------- combinations
    def snapshot_layer_states(self, keep_groups_from=None):
        old = (keep_groups_from or {}).get("layers", {})
        result = {}
        for ly in self.scene.layers:
            group = old.get(ly.name, {}).get("intersection_group", 1)
            result[ly.name] = _state(ly.visible, ly.locked, group)
        return result

    def snapshot_combo(self, name):
        return {
            "id": _uid(),
            "name": name,
            "layers": self.snapshot_layer_states(),
        }

    def combo_matches_scene(self, combo):
        states = combo.get("layers", {})
        for ly in self.scene.layers:
            st = states.get(ly.name)
            if st is None:
                continue
            if bool(st.get("visible", True)) != bool(ly.visible):
                return False
            if bool(st.get("locked", False)) != bool(ly.locked):
                return False
        return True

    def apply_combo(self, combo_id):
        combo = self._combo_by_id(combo_id)
        if not combo:
            return
        states = combo.get("layers", {})
        for ly in self.scene.layers:
            st = states.get(ly.name)
            if st is None:
                continue
            ly.visible = bool(st.get("visible", True))
            ly.locked = bool(st.get("locked", False))

        # A hidden/locked object must leave the selection, matching the
        # native Layers panel.
        selectable = getattr(self.scene, "entity_selectable", None)
        if callable(selectable):
            for ent in list(self.scene.selection):
                try:
                    if not selectable(ent):
                        self.scene.selection.discard(ent)
                except Exception:
                    pass

        self.data["applied_id"] = combo_id
        self.save_data()
        self._touch_scene()
        self._refresh_native_layers()

    # -------------------------------------------------------------- layers
    def add_layer(self, name, folder_id=None):
        from core.layers import Layer
        if folder_id == "__all__":
            folder_id = None
        self.scene.layers.append(Layer(name))
        self.data["layer_folders"][name] = folder_id
        for combo in self.data["combinations"]:
            combo.setdefault("layers", {})[name] = _state(True, False, 1)
        self.save_data()
        self._touch_scene()
        self._refresh_native_layers()

    def _iter_layer_entities(self):
        from core.purge import iter_groups, iter_meshes
        seen = set()
        for mesh in iter_meshes(self.scene):
            for ent in list(mesh.faces) + list(mesh.edges):
                ident = id(ent)
                if ident not in seen:
                    seen.add(ident)
                    yield ent
        for ent in list(iter_groups(self.scene.groups)):
            ident = id(ent)
            if ident not in seen:
                seen.add(ident)
                yield ent
        for attr in (
            "dimensions", "text_labels", "image_planes", "section_planes",
            "guides",
        ):
            for ent in list(getattr(self.scene, attr, []) or []):
                ident = id(ent)
                if ident not in seen:
                    seen.add(ident)
                    yield ent

    def rename_layer(self, old, new):
        from core.layers import assign_layer, layer_of
        ly = self.scene.layer(old)
        if ly is None:
            return
        ly.name = new
        for ent in self._iter_layer_entities():
            try:
                if layer_of(ent) == old:
                    assign_layer(ent, new)
            except Exception:
                pass

        mapping = self.data["layer_folders"]
        mapping[new] = mapping.pop(old, None)
        for combo in self.data["combinations"]:
            states = combo.setdefault("layers", {})
            if old in states:
                states[new] = states.pop(old)
        self.save_data()
        self._touch_scene()
        self._refresh_native_layers()

    def delete_layer(self, name):
        from core.layers import DEFAULT_LAYER, assign_layer, layer_of
        ly = self.scene.layer(name)
        if ly is None or name == DEFAULT_LAYER:
            return
        for ent in self._iter_layer_entities():
            try:
                if layer_of(ent) == name:
                    assign_layer(ent, DEFAULT_LAYER)
            except Exception:
                pass
        self.scene.layers.remove(ly)
        self.data["layer_folders"].pop(name, None)
        for combo in self.data["combinations"]:
            combo.setdefault("layers", {}).pop(name, None)
        self.save_data()
        self._touch_scene()
        self._refresh_native_layers()

    def _show_initial_template_prompt(self):
        if not self._initial_prompt_pending or self._initial_prompt_running:
            return
        self._initial_prompt_running = True
        try:
            dlg = InitialTemplateDialog(self)
            dlg.exec()
            if dlg.choice is not None:
                self.apply_template(dlg.choice)
            else:
                # "Começar vazio" still writes the current simple setup into
                # the document so we do not ask again on the next refresh.
                self._initial_prompt_pending = False
                self.save_data()
            self._initial_prompt_pending = False
        finally:
            self._initial_prompt_running = False

    # ------------------------------------------------------------- templates
    def personal_templates(self):
        raw = QSettings().value(PERSONAL_TEMPLATES_KEY, "")
        if not raw:
            return {}
        try:
            data = json.loads(str(raw))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_personal_templates(self, templates):
        QSettings().setValue(
            PERSONAL_TEMPLATES_KEY,
            json.dumps(templates, ensure_ascii=False, separators=(",", ":"))
        )

    def save_personal_template(self, name, template):
        templates = self.personal_templates()
        template = self.validate_template(copy.deepcopy(template))
        template["name"] = name
        templates[name] = template
        self._write_personal_templates(templates)

    def delete_personal_template(self, name):
        templates = self.personal_templates()
        templates.pop(name, None)
        self._write_personal_templates(templates)

    def validate_template(self, raw):
        if not isinstance(raw, dict):
            raise ValueError("o template precisa ser um objeto JSON")
        if raw.get("format") != TEMPLATE_FORMAT:
            raise ValueError("formato de template não reconhecido")
        if int(raw.get("version", 0)) != TEMPLATE_VERSION:
            raise ValueError("versão de template não suportada")
        if not isinstance(raw.get("layer_names"), list):
            raise ValueError("lista de camadas ausente")
        if not isinstance(raw.get("folders"), list):
            raise ValueError("pastas ausentes")
        if not isinstance(raw.get("layer_folders"), dict):
            raise ValueError("organização das camadas ausente")
        if not isinstance(raw.get("combinations"), list) \
                or not raw["combinations"]:
            raise ValueError("combinações ausentes")
        return copy.deepcopy(raw)

    def project_template(self, name):
        return {
            "format": TEMPLATE_FORMAT,
            "version": TEMPLATE_VERSION,
            "name": name,
            "description": "Template pessoal salvo a partir de um projeto.",
            "layer_names": [ly.name for ly in self.scene.layers],
            "folders": copy.deepcopy(self.data.get("folders", [])),
            "layer_folders": copy.deepcopy(
                self.data.get("layer_folders", {})
            ),
            "combinations": copy.deepcopy(
                self.data.get("combinations", [])
            ),
            "default_combination": (
                self._combo_by_id(self.data.get("applied_id")) or {}
            ).get("name"),
        }

    def apply_template(self, template):
        from core.layers import Layer
        self._initial_prompt_pending = False
        tpl = self.validate_template(template)

        # Create only what is missing. Existing project layers and geometry
        # stay untouched.
        existing = {ly.name for ly in self.scene.layers}
        for name in tpl.get("layer_names", []):
            name = _clean_name(name)
            if name and name not in existing:
                self.scene.layers.append(Layer(name))
                existing.add(name)

        # Replace this plugin's organisation/combination definitions, but
        # never delete host layers that are not in the template.
        folders = copy.deepcopy(tpl.get("folders", []))
        layer_folders = copy.deepcopy(tpl.get("layer_folders", {}))
        combinations = copy.deepcopy(tpl.get("combinations", []))
        for combo in combinations:
            if not combo.get("id"):
                combo["id"] = _uid()

        default_name = tpl.get("default_combination")
        default_id = None
        for combo in combinations:
            if combo.get("name") == default_name:
                default_id = combo.get("id")
                break
        if default_id is None and combinations:
            default_id = combinations[0].get("id")

        self.data = {
            "schema_version": SCHEMA_VERSION,
            "folders": folders,
            "layer_folders": layer_folders,
            "combinations": combinations,
            "applied_id": default_id,
        }
        self.sync_with_scene(save=False)
        self.save_data()

        if default_id:
            self.apply_combo(default_id)
        else:
            self._touch_scene()
            self._refresh_native_layers()

        if self.dialog is not None:
            try:
                self.dialog.refresh(False)
            except RuntimeError:
                self.dialog = None

    def show_templates(self):
        if self.template_dialog is None:
            self.template_dialog = TemplateDialog(
                self, self.dialog or self.app.window
            )
        self.template_dialog.refresh()
        self.template_dialog.show()
        self.template_dialog.raise_()
        self.template_dialog.activateWindow()

    # --------------------------------------------------------------- host UI
    def _touch_scene(self):
        self.scene.version += 1
        notify = getattr(self.app.viewport, "notify_scene_changed", None)
        if callable(notify):
            notify()
        self.app.viewport.update()

    def _refresh_native_layers(self):
        try:
            self.app.window.tray.layers.refresh()
        except Exception:
            pass

    def show(self):
        if self.dialog is None:
            self.dialog = ManagerDialog(self)
        self.dialog.refresh()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        if self.bar is not None:
            self.bar.refresh()


def setup(app):
    controller = Controller(app)
    app.window._layer_combinations_controller = controller
    app.window._layer_combinations_version = PLUGIN_VERSION
    app.add_menu_action(
        "Combinação de Camadas…",
        controller.show,
        tip="Gerenciar combinações de camadas, pastas e grupos de interseção.",
    )
    print(
        f"[layer-combinations] v{PLUGIN_VERSION} carregado "
        f"({len(app.scene.layers)} camadas)"
    )
