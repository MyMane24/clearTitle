import unittest
from unittest.mock import patch

from backend.services.report import (
    _build_subject,
    _owner_blocks,
    _parties_effect,
    _property_identity_lines,
    _required_document_entries,
    _required_document_status_label,
    render_required_documents_pdf,
)


class ReportPartiesTest(unittest.TestCase):
    """The extractor emits parties as plain strings; dict entries still supported."""

    def test_parties_effect_accepts_strings(self):
        tx = {
            "parties": {
                "vendors": ["M/s Sapthagiri Associates", "Ravindra Shivaputra Chobari"],
                "purchasers": ["Chandrashekhar S. Hadimani"],
            }
        }
        self.assertEqual(
            _parties_effect(tx),
            "M/s Sapthagiri Associates → Ravindra Shivaputra Chobari → Chandrashekhar S. Hadimani",
        )

    def test_parties_effect_accepts_dicts_and_dedupes(self):
        tx = {
            "parties": {
                "vendors": [
                    {"entity_name": "K.U.D.C. Belagavi"},
                    {"entity_name": "Basavaraj Hiremath"},
                ],
                "purchasers": [{"entity_name": "Basavaraj Hiremath"}],
            }
        }
        self.assertEqual(_parties_effect(tx), "K.U.D.C. Belagavi → Basavaraj Hiremath")

    def test_parties_effect_empty_purchasers(self):
        tx = {"parties": {"vendors": ["Sri.Prerana Shirodkar"], "purchasers": []}}
        self.assertEqual(_parties_effect(tx), "Sri.Prerana Shirodkar")

    def test_owner_blocks_from_strings(self):
        sd = {
            "parties": {
                "purchasers": ["Smt.Prerana Praveen Shirodkar", "Sri.Praveen Bhausaheb Shirodkar"]
            }
        }
        blocks = _owner_blocks(sd)
        self.assertEqual([b["label"] for b in blocks], ["Current Owner", "Co-Owner 2"])
        self.assertEqual(blocks[0]["name"], "Smt.Prerana Praveen Shirodkar")
        self.assertEqual(blocks[1]["address"], "")

    def test_owner_blocks_from_dicts(self):
        sd = {
            "parties": {
                "purchasers": [
                    {
                        "entity_name": "Anusuya",
                        "represented_by": "Basavaraj Hiremath",
                        "address": "Belagavi",
                    }
                ]
            }
        }
        block = _owner_blocks(sd)[0]
        self.assertEqual(block["name"], "Anusuya (Rep. by Basavaraj Hiremath)")
        self.assertEqual(block["address"], "Belagavi")

    def test_build_subject_from_strings(self):
        sd = {
            "property_schedule": {"survey_number": "699A/15"},
            "parties": {"purchasers": ["Basavaraj Hiremath"]},
        }
        self.assertEqual(
            _build_subject(sd), "Legal opinion in respect of 699A/15 held by Basavaraj Hiremath."
        )

    def test_required_document_entries_keep_requests_scoped_to_their_transaction(self):
        entries = _required_document_entries({"transactions": [
            {
                "tx_id": "PA-TC-0002", "sequence": 2, "status": "PENDING_NOT_VERIFIED",
                "transaction_metadata": {"transaction_type": "Sale deed"},
                "required_documents": [{"document_type": "Registered deed dated 2009", "reason": "Confirm transfer."}],
            },
            {"tx_id": "PA-TC-0003", "sequence": 3, "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE", "required_documents": []},
        ]})
        self.assertEqual(len(entries), 1)
        self.assertNotIn("tx_id", entries[0])
        self.assertEqual(entries[0]["document_type"], "Registered deed dated 2009")
        self.assertEqual(entries[0]["reason"], "Confirm transfer.")

    def test_checklist_property_identity_and_pending_label(self):
        self.assertEqual(
            _property_identity_lines({"title_chain": {"property_identity": {
                "details": [{"label": "Survey number", "value": "699A/15"}],
            }}}),
            ["Survey number: 699A/15"],
        )
        self.assertEqual(_required_document_status_label("PENDING_NOT_VERIFIED"), "Pending")

    def test_property_identity_lookup_handles_legacy_list_title_chain(self):
        self.assertEqual(
            _property_identity_lines({
                "title_chain": [{"tx_id": "PA-TC-0001"}],
                "property_identity": {"details": [{"label": "Survey", "value": "88/2"}]},
            }),
            ["Survey: 88/2"],
        )

    def test_required_documents_pdf_renders_even_when_no_requests_are_outstanding(self):
        with patch("backend.services.report.build_case_results", return_value={"agent": {"transactions": []}}):
            pdf = render_required_documents_pdf("CASE1234")
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
