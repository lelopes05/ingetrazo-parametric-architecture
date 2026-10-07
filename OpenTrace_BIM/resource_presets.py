# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable wall presets and complex-profile resources."""
from __future__ import annotations

import copy
import json
import unicodedata
import uuid

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QMessageBox, QPushButton, QVBoxLayout,
)

from core.resource_library import LibraryInfo, ResourceInfo
from .model import read_wall
from .profile_library import load_profiles, load_personal_profiles, profile_by_id, upsert_profile

WALL_PRESETS_KEY = "arquitetura_parametrica/wall_presets_v1"
WALL_PRESET_SCHEMA = 1


def _display_name(value):
    """Trim and collapse whitespace while preserving the user's capitalization."""
    return " ".join(str(value or "").split())


def _name_key(value):
    """Case-insensitive logical identity for a preset name."""
    display = _display_name(value)
    return unicodedata.normalize("NFKC", display).casefold()


def _clean_config(raw):
    if not isinstance(raw, dict):
        raise ValueError("Preset de parede inválido.")
    try:
        thickness = float(raw.get("thickness", 0.10))
        height = float(raw.get("height", 3.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Preset com medidas inválidas.") from exc

    alignment = str(raw.get("alignment", "left"))
    if alignment not in ("left", "center", "right"):
        alignment = "left"

    structure = str(raw.get("structure", "simple"))
    if structure not in ("simple", "composite"):
        structure = "simple"

    material = raw.get("material_name")
    material = str(material).strip() if material not in (None, "") else None
    layers = copy.deepcopy(raw.get("layers", []))
    if not isinstance(layers, list):
        layers = []

    return {
        "thickness": thickness,
        "height": height,
        "alignment": alignment,
        "material_name": material,
        "structure": structure,
        "layers": layers if structure == "composite" else [],
    }


def _clean_preset(raw):
    if not isinstance(raw, dict):
        return None
    try:
        config = _clean_config(raw.get("config", raw))
        revision = max(1, int(raw.get("revision", 1) or 1))
    except (ValueError, TypeError):
        return None

    name = _display_name(raw.get("name") or "Preset de parede")
    if not name:
        name = "Preset de parede"

    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "name": name,
        "schema_version": WALL_PRESET_SCHEMA,
        "revision": revision,
        "config": config,
    }


def load_wall_presets():
    raw = QSettings().value(WALL_PRESETS_KEY, "[]")
    try:
        data = json.loads(str(raw or "[]"))
    except Exception:
        data = []
    result = []
    if isinstance(data, list):
        for item in data:
            clean = _clean_preset(item)
            if clean is not None:
                result.append(clean)
    return result


def save_wall_presets(presets):
    clean = []
    for item in presets or []:
        item = _clean_preset(item)
        if item is not None:
            clean.append(item)
    settings = QSettings()
    settings.setValue(
        WALL_PRESETS_KEY,
        json.dumps(clean, ensure_ascii=False, separators=(",", ":")),
    )
    settings.sync()
    return clean


def preset_by_id(preset_id):
    pid = str(preset_id)
    for item in load_wall_presets():
        if item["id"] == pid:
            return copy.deepcopy(item)
    return None


def preset_by_name(name, exclude_id=None):
    key = _name_key(name)
    if not key:
        return None
    excluded = None if exclude_id is None else str(exclude_id)
    for item in load_wall_presets():
        if excluded is not None and item["id"] == excluded:
            continue
        if _name_key(item["name"]) == key:
            return copy.deepcopy(item)
    return None


def upsert_wall_preset(preset):
    item = _clean_preset(preset)
    if item is None:
        raise ValueError("Preset de parede inválido.")
    presets = load_wall_presets()
    for i, old in enumerate(presets):
        if old["id"] == item["id"]:
            presets[i] = item
            break
    else:
        presets.append(item)
    save_wall_presets(presets)
    return copy.deepcopy(item)


def delete_wall_preset(preset_id):
    pid = str(preset_id)
    save_wall_presets([x for x in load_wall_presets() if x["id"] != pid])


def wall_config_from_controller(controller):
    source = (
        read_wall(controller.target)
        if getattr(controller, "target", None) is not None
        else controller.defaults
    )
    return _clean_config(source)


def apply_wall_preset(controller, preset):
    item = _clean_preset(preset)
    if item is None:
        raise ValueError("Preset de parede inválido.")
    base = (
        read_wall(controller.target)
        if getattr(controller, "target", None) is not None
        else copy.deepcopy(controller.defaults)
    )
    base.update(copy.deepcopy(item["config"]))
    controller.load_fields(base)
    controller.defaults_changed()
    return item


class WallPresetProvider:
    def list_libraries(self):
        return [
            LibraryInfo(
                "personal", "Biblioteca pessoal",
                "Presets de parede do usuário.", scope="user"
            )
        ]

    def list_resources(self):
        return [
            ResourceInfo(
                id=x["id"],
                name=x["name"],
                description="Preset paramétrico de parede",
                version=str(x["revision"]),
                tags=("wall", "preset", x["config"]["structure"]),
                library_id="personal",
            )
            for x in load_wall_presets()
        ]

    def get_resource(self, resource_id):
        item = preset_by_id(resource_id)
        if item is None:
            raise KeyError(resource_id)
        return item

    def get_dependencies(self, resource_id):
        self.get_resource(resource_id)
        return ()

    def export_resource(self, resource_id):
        return json.dumps(
            self.get_resource(resource_id),
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")

    def import_resource(self, payload):
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        incoming = _clean_preset(json.loads(payload))
        if incoming is None:
            raise ValueError("Preset importado inválido.")

        # Do not silently create a second human-visible preset with a name that
        # differs only by capitalization/spacing. Import conflicts should be
        # explicit because changing UUIDs silently would break stable refs.
        same_name = preset_by_name(incoming["name"], exclude_id=incoming["id"])
        if same_name is not None:
            raise ValueError(
                f"Já existe um preset chamado '{same_name['name']}'. "
                "Renomeie um deles antes de importar."
            )

        saved = upsert_wall_preset(incoming)
        return ResourceInfo(
            id=saved["id"],
            name=saved["name"],
            description="Preset paramétrico de parede",
            version=str(saved["revision"]),
            tags=("wall", "preset", saved["config"]["structure"]),
            library_id="personal",
        )


class ComplexProfileProvider:
    def list_libraries(self):
        return [
            LibraryInfo(
                "personal", "Biblioteca pessoal",
                "Perfis complexos do usuário.", scope="user"
            )
        ]

    def list_resources(self):
        return [
            ResourceInfo(
                id=x["id"],
                name=x["name"],
                description="Perfil complexo paramétrico",
                version=str(x.get("schema_version", 1)),
                tags=("profile", "complex"),
                library_id="personal",
            )
            for x in load_personal_profiles()
        ]

    def get_resource(self, resource_id):
        item = profile_by_id(resource_id)
        if item is None:
            raise KeyError(resource_id)
        return item

    def get_dependencies(self, resource_id):
        self.get_resource(resource_id)
        return ()

    def export_resource(self, resource_id):
        return json.dumps(
            self.get_resource(resource_id),
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")

    def import_resource(self, payload):
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        saved = upsert_profile(json.loads(payload))
        return ResourceInfo(
            id=saved["id"],
            name=saved["name"],
            description="Perfil complexo paramétrico",
            version=str(saved.get("schema_version", 1)),
            tags=("profile", "complex"),
            library_id="personal",
        )


class WallPresetPanel(QFrame):
    def __init__(self, app, controller):
        super().__init__(controller.panel)
        self.app = app
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)

        title = QLabel("Presets de parede")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._sync_buttons)
        layout.addWidget(self.combo)

        row = QHBoxLayout()
        self.apply_btn = QPushButton("Aplicar")
        self.save_btn = QPushButton("Salvar")
        self.rename_btn = QPushButton("Renomear")
        row.addWidget(self.apply_btn)
        row.addWidget(self.save_btn)
        row.addWidget(self.rename_btn)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self.delete_btn = QPushButton("Excluir")
        self.export_btn = QPushButton("Exportar…")
        self.import_btn = QPushButton("Importar…")
        row2.addWidget(self.delete_btn)
        row2.addWidget(self.export_btn)
        row2.addWidget(self.import_btn)
        layout.addLayout(row2)

        self.apply_btn.clicked.connect(self.apply_selected)
        self.save_btn.clicked.connect(self.save_current)
        self.rename_btn.clicked.connect(self.rename_selected)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.export_btn.clicked.connect(self.export_selected)
        self.import_btn.clicked.connect(self.import_bundle)
        self.refresh()

    def _sync_buttons(self, *_):
        has = self.combo.currentData() is not None
        self.apply_btn.setEnabled(has)
        self.rename_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)
        self.export_btn.setEnabled(has)

    def refresh(self, select_id=None):
        current_id = select_id
        if current_id is None:
            current_id = self.combo.currentData()

        self.combo.blockSignals(True)
        try:
            self.combo.clear()
            self.combo.addItem("— escolha um preset —", None)
            index = 0
            for item in load_wall_presets():
                self.combo.addItem(item["name"], item["id"])
                if item["id"] == current_id:
                    index = self.combo.count() - 1
            self.combo.setCurrentIndex(index)
        finally:
            self.combo.blockSignals(False)
        self._sync_buttons()

    def _selected(self):
        pid = self.combo.currentData()
        return None if pid is None else preset_by_id(pid)

    def apply_selected(self):
        preset = self._selected()
        if preset is None:
            return
        try:
            apply_wall_preset(self.controller, preset)
            self.controller.message(f"Preset '{preset['name']}' aplicado.")
        except Exception as exc:
            self.controller.message(str(exc), error=True)

    def save_current(self):
        name, ok = QInputDialog.getText(
            self, "Salvar preset de parede", "Nome do preset:"
        )
        if not ok:
            return

        name = _display_name(name)
        if not name:
            return

        try:
            config = wall_config_from_controller(self.controller)
            existing = preset_by_name(name)

            if existing is not None:
                if existing["config"] == config:
                    self.refresh(existing["id"])
                    self.controller.message(
                        f"O preset '{existing['name']}' já existe com essa configuração."
                    )
                    return

                answer = QMessageBox.question(
                    self,
                    "Atualizar preset",
                    (
                        f"Já existe um preset chamado '{existing['name']}'.\n\n"
                        "Deseja atualizar esse preset com a configuração atual?"
                    ),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if answer != QMessageBox.Yes:
                    return

                existing["config"] = config
                existing["revision"] = int(existing.get("revision", 1)) + 1
                item = upsert_wall_preset(existing)
                self.refresh(item["id"])
                self.controller.message(
                    f"Preset '{item['name']}' atualizado (revisão {item['revision']})."
                )
                return

            item = upsert_wall_preset({
                "id": uuid.uuid4().hex,
                "name": name,
                "revision": 1,
                "config": config,
            })
            self.refresh(item["id"])
            self.controller.message(
                f"Preset '{item['name']}' salvo na biblioteca pessoal."
            )
        except Exception as exc:
            self.controller.message(str(exc), error=True)

    def rename_selected(self):
        preset = self._selected()
        if preset is None:
            return

        name, ok = QInputDialog.getText(
            self,
            "Renomear preset",
            "Novo nome:",
            text=preset["name"],
        )
        if not ok:
            return

        name = _display_name(name)
        if not name:
            return

        collision = preset_by_name(name, exclude_id=preset["id"])
        if collision is not None:
            QMessageBox.warning(
                self,
                "Nome já utilizado",
                f"Já existe um preset chamado '{collision['name']}'.",
            )
            return

        if name == preset["name"]:
            return

        preset["name"] = name
        preset["revision"] = int(preset.get("revision", 1)) + 1
        item = upsert_wall_preset(preset)
        self.refresh(item["id"])
        self.controller.message(
            f"Preset renomeado para '{item['name']}' (revisão {item['revision']})."
        )

    def delete_selected(self):
        preset = self._selected()
        if preset is None:
            return
        answer = QMessageBox.question(
            self,
            "Excluir preset",
            f"Excluir '{preset['name']}' da biblioteca pessoal?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        delete_wall_preset(preset["id"])
        self.refresh()
        self.controller.message("Preset excluído.")

    def export_selected(self):
        preset = self._selected()
        if preset is None:
            return
        suggested = preset["name"].replace("/", "-").replace(chr(92), "-")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar preset",
            f"{suggested}.iglib",
            "Biblioteca IngeTrazo (*.iglib)",
        )
        if not path:
            return
        if not path.lower().endswith(".iglib"):
            path += ".iglib"
        try:
            self.app.export_resource_bundle(
                "wall_preset", preset["id"], path,
                include_dependencies=True,
            )
            self.controller.message(f"Preset exportado para {path}.")
        except Exception as exc:
            self.controller.message(str(exc), error=True)

    def import_bundle(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar recurso", "",
            "Biblioteca IngeTrazo (*.iglib)",
        )
        if not path:
            return
        try:
            result = self.app.import_resource_bundle(
                path, conflict="replace"
            )
            selected = (
                result.root.resource_id
                if result.root.type_key.endswith(":wall_preset")
                else None
            )
            self.refresh(selected)
            self.controller.message(
                f"Importação concluída: {len(result.imported)} recurso(s), "
                f"{len(result.skipped)} já existente(s)."
            )
        except Exception as exc:
            self.controller.message(str(exc), error=True)


class ParametricResourceLibrary:
    def __init__(self, app, controller):
        self.wall_provider = WallPresetProvider()
        self.profile_provider = ComplexProfileProvider()
        self.wall_type = app.register_resource_type(
            "wall_preset", self.wall_provider,
            label="Presets de parede",
        )
        self.profile_type = app.register_resource_type(
            "complex_profile", self.profile_provider,
            label="Perfis complexos",
        )
        # The visible preset UI is supplied by preset_catalog.py for walls,
        # slabs, beams and columns.  This object only exposes portable resource
        # providers to Extension API 4, preserving .iglib interoperability.
        self.wall_panel = None


def install_resource_library(app, controller):
    if getattr(app, "api_version", 0) < 4:
        raise RuntimeError(
            "Presets reutilizáveis requerem IngeTrazo Extension API 4."
        )
    return ParametricResourceLibrary(app, controller)
