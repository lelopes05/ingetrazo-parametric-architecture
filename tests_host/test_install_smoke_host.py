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
            self.assertTrue(getattr(ctl,"opening_btn",None))
            self.assertTrue(getattr(ctl,"door_btn",None))
            self.assertTrue(getattr(ctl,"window_btn",None))
            self.assertTrue(getattr(ctl,"opening_selector",None))
            self.assertTrue(getattr(ctl,"opening_fields",None))
            self.assertIsNotNone(getattr(window,"_arquitetura_parametrica_suite_panel",None))
        finally:
            window.deleteLater()
            qt.processEvents()


if __name__ == "__main__":
    unittest.main()
