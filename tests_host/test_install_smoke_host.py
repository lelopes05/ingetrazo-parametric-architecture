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


if __name__ == "__main__":
    unittest.main()
