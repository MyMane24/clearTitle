import unittest

from backend.services.agent_schemas import normalize_status
from backend.services.cleartitle_agent import _collect_missing, _overall_transaction_status


class TestStatusNormalization(unittest.TestCase):
    def test_normalizes_known(self):
        self.assertEqual(normalize_status("verified_with_available_evidence"), "VERIFIED_WITH_AVAILABLE_EVIDENCE")
        self.assertEqual(normalize_status("issues_identified"), "ISSUES_IDENTIFIED")
        self.assertEqual(normalize_status("inconclusive"), "INCONCLUSIVE")
        self.assertEqual(normalize_status("pending_not_verified"), "PENDING_NOT_VERIFIED")

    def test_unknown_falls_back(self):
        self.assertEqual(normalize_status("nonsense"), "PENDING")

    def test_missing_evidence_is_pending_not_issues(self):
        self.assertEqual(normalize_status("missing_evidence"), "PENDING_NOT_VERIFIED")


class TestTransactionSummary(unittest.TestCase):
    def test_overall_status_comes_from_transaction_statuses(self):
        self.assertEqual(_overall_transaction_status([
            {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"},
        ]), "VERIFIED_WITH_AVAILABLE_EVIDENCE")
        self.assertEqual(_overall_transaction_status([
            {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"}, {"status": "PENDING_NOT_VERIFIED"},
        ]), "INCONCLUSIVE")
        self.assertEqual(_overall_transaction_status([
            {"status": "ISSUES_IDENTIFIED"},
        ]), "ISSUES_IDENTIFIED")

    def test_collect_missing_aggregates_across_transactions(self):
        transactions = [
            {"tx_id": "TX001", "missing_documents": [{"document_type": "EC", "reason": "prove ownership"}]},
            {"tx_id": "TX002", "missing_documents": []},
            {"tx_id": "TX003", "missing_documents": [{"document_type": "Khata", "reason": "ownership"}]},
        ]
        collected = _collect_missing(transactions)
        self.assertEqual(len(collected), 2)
        self.assertEqual(collected[0]["document_type"], "EC")
        self.assertEqual(collected[0]["for_transaction"], "TX001")
        self.assertEqual(collected[1]["document_type"], "Khata")
        self.assertEqual(collected[1]["for_transaction"], "TX003")


if __name__ == "__main__":
    unittest.main()
