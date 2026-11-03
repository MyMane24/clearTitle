import unittest
from unittest.mock import patch

from backend.services.report import (
    _property_identity_lines,
    _required_document_entries,
    _required_document_status_label,
    render_required_documents_pdf,
)


class ReportPartiesTest(unittest.TestCase):
    """The checklist surfaces property identity, pending labels, and outstanding requests."""

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
