# SPDX-License-Identifier: GPL-3.0-or-later
"""Installed-package discovery smoke test on the actual IngeTrazo host."""
from pathlib import Path
import shutil
import tempfile
import unittest


class InstallationSmokeTests(unittest.TestCase):
    def test_host_discovers_extracted_opentrace_bim_folder(self):
        from core.extensions import discover_plugins

        root = Path(__file__).resolve().parents[1] / "OpenTrace_BIM"
        self.assertTrue((root / "__init__.py").is_file())
        with tempfile.TemporaryDirectory() as td:
            archive_root = Path(td)
            shutil.copytree(root, archive_root / "OpenTrace_BIM",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            # This is precisely the directory IngeTrazo reads once the
            # single artifact ZIP is extracted into its plugin directory.
            plugins, errors = discover_plugins([archive_root])
            self.assertEqual(errors, [])
            named = [p for p in plugins if p.stem == "OpenTrace_BIM"]
            self.assertEqual(len(named), 1)
            self.assertTrue(callable(named[0].setup))


    def test_real_main_window_initializes_opentrace_toolbar_and_opening_editor(self):
        """Catch the 'all default plugin buttons disappeared' startup regression.

        Discovery/import alone is NOT enough: the actual setup(app) must
        construct its Qt palette and dock using a real IngeTrazo MainWindow.
        """
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from views.main_window import MainWindow
        from views.extension_api import ExtensionApp
        from OpenTrace_BIM import setup

        qt=QApplication.instance() or QApplication([])
        window=MainWindow()
        try:
            setup(ExtensionApp(window,"OpenTrace_BIM"))
            ctl=getattr(window,"_arquitetura_parametrica_controller",None)
            self.assertIsNotNone(ctl,"setup did not create wall controller")
            self.assertIsNotNone(getattr(ctl,"toolbar",None))
            button=ctl.opening_toolbar_button
            self.assertEqual(button.objectName(),"opentrace_opening_toolbar_button")
            self.assertIs(button.parent(),ctl.toolbar)
            self.assertEqual(button.defaultAction().text(),"Abertura")
            self.assertEqual(len(button.menu().actions()),2)
            self.assertTrue(getattr(ctl,"opening_btn",None))
            self.assertTrue(getattr(ctl,"door_btn",None))
            self.assertTrue(getattr(ctl,"window_btn",None))
            self.assertTrue(getattr(ctl,"opening_selector",None))
            self.assertTrue(getattr(ctl,"opening_fields",None))
            self.assertIsNotNone(getattr(window,"_arquitetura_parametrica_suite_panel",None))
        finally:
            window.deleteLater()
            qt.processEvents()


    def test_live_qt_opening_editor_updates_correct_wall_void(self):
        """Real Qt signal: selecting B and editing width must not modify A."""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtGui import QVector3D
        from PySide6.QtWidgets import QApplication
        from views.main_window import MainWindow
        from views.extension_api import ExtensionApp
        from OpenTrace_BIM import setup
        from OpenTrace_BIM.model import DEFAULTS, make_wall_segment, read_wall

        qt=QApplication.instance() or QApplication([])
        window=MainWindow()
        try:
            setup(ExtensionApp(window,"OpenTrace_BIM"))
            ctl=window._arquitetura_parametrica_controller
            scene=window.viewport.scene
            wall=make_wall_segment(QVector3D(0,0,0),QVector3D(5,0,0),
                dict(DEFAULTS,length=5.0,openings=[
                    {"id":"edit-A","position":1.0,"width":.7,
                     "sill":.7,"height":1.2},
                    {"id":"edit-B","position":3.5,"width":.7,
                     "sill":.8,"height":1.1}]))
            scene.groups.append(wall)
            scene.selection.add(wall)
            scene.version+=1
            ctl._state_key=None
            ctl.refresh()
            self.assertIs(ctl.target,wall)
            self.assertEqual(ctl.opening_selector.count(),2)
            self.assertEqual(ctl._fields_opening_id,"edit-A")
            ctl.opening_selector.setCurrentIndex(1)
            self.assertEqual(ctl._fields_opening_id,"edit-B")
            self.assertAlmostEqual(ctl.opening_fields["width"].value(),.7)
            ctl.opening_fields["width"].setValue(.9)
            model=read_wall(wall)
            self.assertAlmostEqual(model["openings"][0]["width"],.7)
            self.assertAlmostEqual(model["openings"][1]["width"],.9)
            self.assertAlmostEqual(model["openings"][1]["sill"],.8)
            self.assertAlmostEqual(model["openings"][1]["height"],1.1)
        finally:
            window.deleteLater()
            qt.processEvents()


if __name__ == "__main__":
    unittest.main()
