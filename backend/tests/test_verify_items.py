"""Self-check for the verification items normalization.

Runs with stdlib unittest only:
    python -m unittest backend.tests.test_verify_items -v
"""

from __future__ import annotations

import unittest

from backend.services.verify import _normalize_items


class VerifyItemsTest(unittest.TestCase):
    def test_khata_value_passthrough(self):
        raw = [
            {
                "field": "Khata holder (SD purchaser)",
                "sd_value": "Puneet G Kousik",
                "ec_value": "Not found in EC",
                "khata_value": "Puneet G Kousik",
                "status": "VERIFIED",
                "notes": "Khata holder matches SD purchaser",
            },
            {"field": "Khata type", "status": "NEEDS_REVIEW", "notes": "B-Khata flagged"},
        ]
        items = _normalize_items(raw)
        self.assertEqual(items[0]["khata_value"], "Puneet G Kousik")
        self.assertEqual(items[0]["status"], "VERIFIED")
        self.assertEqual(items[1]["status"], "NEEDS_REVIEW")
        self.assertIsNone(items[1]["khata_value"])

    def test_invalid_status_falls_back_to_na(self):
        items = _normalize_items([{"field": "x", "status": "VERFIFIED"}, "skip-me"])
        self.assertEqual(items[0]["status"], "N/A")
        self.assertEqual(len(items), 1)

    def test_empty_input(self):
        self.assertEqual(_normalize_items(None), [])
        self.assertEqual(_normalize_items([]), [])


if __name__ == "__main__":
    unittest.main()
