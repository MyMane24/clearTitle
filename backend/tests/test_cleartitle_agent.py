import unittest

from backend.services.agent_rules import rules_for
from backend.services.agent_schemas import normalize_status
from backend.services.cleartitle_agent import _collect_missing, _merged_transactions


class TestAgentRules(unittest.TestCase):
    def test_common_rules_always_apply(self):
        for tx in ({"type": "SALE"}, {"type": "MORTGAGE"}, {"type": "WHATEVER"}):
            ids = {r["id"] for r in rules_for(tx)}
            self.assertIn("COMMON-1", ids)

    def test_type_specific_rules(self):
        self.assertIn("MORT-2", {r["id"] for r in rules_for({"type": "MORTGAGE"})})
        self.assertIn("SALE-1", {r["id"] for r in rules_for({"type": "sale"})})

    def test_unknown_type_falls_back(self):
        self.assertIn("OTHER-1", {r["id"] for r in rules_for({"type": "not-a-type"})})


class TestStatusNormalization(unittest.TestCase):
    def test_normalizes_known(self):
        self.assertEqual(normalize_status("verified_with_available_evidence"), "VERIFIED_WITH_AVAILABLE_EVIDENCE")
        self.assertEqual(normalize_status("issues_identified"), "ISSUES_IDENTIFIED")
        self.assertEqual(normalize_status("inconclusive"), "INCONCLUSIVE")
        self.assertEqual(normalize_status("pending_not_verified"), "PENDING_NOT_VERIFIED")

    def test_unknown_falls_back(self):
        self.assertEqual(normalize_status("nonsense"), "PENDING")


class TestMemoryMerge(unittest.TestCase):
    def test_findings_overlay_chain(self):
        chain = {"transactions": [
            {"tx_id": "TX001", "sequence": 1, "transaction_type": "SALE"},
            {"tx_id": "TX002", "sequence": 2, "transaction_type": "GIFT"},
        ]}
        findings = [
            {"tx_id": "TX002", "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE", "conclusion": "ok"}
        ]
        merged = _merged_transactions(chain, findings)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[1]["status"], "VERIFIED_WITH_AVAILABLE_EVIDENCE")
        self.assertEqual(merged[1]["conclusion"], "ok")
        self.assertNotIn("conclusion", merged[0])

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
