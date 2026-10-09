# SPDX-License-Identifier: GPL-3.0-or-later
"""Non-Qt checks for backward-compatible project metadata."""
import unittest

from OpenTrace_BIM.bim import default_document_data, normalize_document_data


class ProjectInfoRecordTests(unittest.TestCase):
    def test_client_location_are_in_document_defaults(self):
        data = default_document_data()
        self.assertEqual(data["project"]["client"], "")
        self.assertEqual(data["project"]["location"], "")

    def test_legacy_project_migrates_without_losing_fields(self):
        legacy = {"project": {"name": "Antigo", "site": "Terreno A", "organization": "Escritório"}}
        result = normalize_document_data(legacy)
        self.assertEqual(result["project"]["name"], "Antigo")
        self.assertEqual(result["project"]["site"], "Terreno A")
        self.assertEqual(result["project"]["client"], "")
        self.assertEqual(result["project"]["location"], "")

    def test_new_and_future_project_data_are_preserved(self):
        original = {"project": {
            "name": "Renovação", "client": "Cliente", "location": "Cidade",
            "future_field": "value",
        }}
        result = normalize_document_data(original)
        self.assertEqual(result["project"]["client"], "Cliente")
        self.assertEqual(result["project"]["location"], "Cidade")
        self.assertEqual(result["project"]["future_field"], "value")


if __name__ == "__main__":
    unittest.main()
