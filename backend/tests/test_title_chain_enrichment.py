"""Self-check for the deterministic title-chain enrichment fallbacks.

Runs with stdlib unittest only:
    python -m unittest backend.tests.test_title_chain_enrichment -v
"""

from __future__ import annotations

import unittest

from backend.services.title_chain import (
    _fallback_role,
    _is_encumbrance_type,
    _is_sale_deed_entry,
    _sd_identity,
)

SD_IDENTITY = {
    "registration_reference": "BEL-1-04646-2008-09",
    "execution_date": "2008-09-20",
    "survey_number": "663/1paiki",
    "cts_number": None,
    "plot_or_site_number": "58",
    "conveyed_interest": "1/2 undivided common share",
}


class TitleChainEnrichmentTest(unittest.TestCase):
    def test_sd_identity_projection(self):
        sd = {
            "file_metadata": {
                "registration_number": "BEL-1-04646-2008-09",
                "execution_date": "2008-09-20",
            },
            "property_schedule": {
                "survey_number": "663/1paiki",
                "apartment_or_shop_number": "58",
                "full_schedule_description": "1/2 undivided common share",
            },
        }
        self.assertEqual(_sd_identity(sd), SD_IDENTITY)

    def test_is_sale_deed_entry_by_registration(self):
        entry = {"registration_reference": "BEL-1-04646-2008-09", "execution_date": "2008-09-20"}
        self.assertTrue(_is_sale_deed_entry(entry, SD_IDENTITY))

    def test_is_sale_deed_entry_by_date_when_reg_missing(self):
        entry = {"registration_reference": None, "execution_date": "2008-09-20"}
        self.assertTrue(_is_sale_deed_entry(entry, SD_IDENTITY))

    def test_encumbrance_detection(self):
        self.assertTrue(_is_encumbrance_type("Mortgage without Possession"))
        self.assertTrue(_is_encumbrance_type("Agreement of Sale"))
        self.assertTrue(_is_encumbrance_type("DTD"))
        self.assertFalse(_is_encumbrance_type("Sale"))

    def test_fallback_role_sd(self):
        entry = {
            "registration_reference": "BEL-1-04646-2008-09",
            "execution_date": "2008-09-20",
            "transaction_type": "Sale",
        }
        self.assertEqual(_fallback_role(entry, SD_IDENTITY), "THE_SD")

    def test_fallback_role_predecessor(self):
        entry = {"execution_date": "2007-06-01", "transaction_type": "Sale"}
        self.assertEqual(_fallback_role(entry, SD_IDENTITY), "PREDECESSOR_TITLE")

    def test_fallback_role_subsequent(self):
        entry = {"execution_date": "2009-12-04", "transaction_type": "Sale"}
        self.assertEqual(_fallback_role(entry, SD_IDENTITY), "SUBSEQUENT_TRANSFER")

    def test_fallback_role_encumbrance(self):
        entry = {"execution_date": "2019-08-03", "transaction_type": "Mortgage without Possession"}
        self.assertEqual(_fallback_role(entry, SD_IDENTITY), "ENCUMBRANCE")


if __name__ == "__main__":
    unittest.main()
