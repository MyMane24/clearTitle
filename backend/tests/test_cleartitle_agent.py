import unittest
from unittest.mock import patch
from backend.services.agent_schemas import normalize_status
from backend.services.cleartitle_agent import (
    _collect_missing,
    _is_terminal_transaction_result,
    _overall_transaction_status,
    _verify_transaction,
)


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
    def test_saved_bounded_fallback_clears_stale_validation_error(self):
        phase_a = {"title_chain": [{
            "tx_id": "PA-TC-0001", "chain_position": 1,
            "documented_transaction": {"transaction_type": "Sale deed"},
        }]}

        def stop_after_invalid_result(ctx, **_kwargs):
            ctx.stop_reason = "model_call_budget_exhausted"
            ctx.result_error = "last attempted result failed validation"

        with (
            patch("backend.services.cleartitle_agent.run_tool_loop", side_effect=stop_after_invalid_result),
            patch("backend.services.cleartitle_agent.repo.get_transaction_result", return_value=None),
            patch("backend.services.cleartitle_agent.repo.save_transaction_result") as save,
        ):
            ctx = _verify_transaction(
                "CASE1", [], phase_a,
                {"tx_id": "PA-TC-0001", "sequence": 1, "transaction_type": "Sale deed"},
            )

        save.assert_called_once()
        self.assertIsNone(ctx.result_error)
        self.assertEqual(ctx.stop_reason, "bounded_stop_inconclusive_saved")
        self.assertEqual(ctx.saved_results[0]["status"], "INCONCLUSIVE")

    def test_bounded_inconclusive_checkpoint_is_retryable_but_normal_inconclusive_is_terminal(self):
        self.assertFalse(_is_terminal_transaction_result({
            "status": "INCONCLUSIVE",
            "transaction_metadata": {"_verification_checkpoint": "bounded_stop"},
        }))
        self.assertFalse(_is_terminal_transaction_result({
            "status": "INCONCLUSIVE",
            "transaction_metadata": {"_verification_checkpoint": "repeated_tool_call"},
        }))
        self.assertTrue(_is_terminal_transaction_result({"status": "INCONCLUSIVE"}))

    def test_inconclusive_result_reopens_only_when_document_manifest_changes(self):
        prior = {
            "status": "INCONCLUSIVE",
            "transaction_metadata": {"_document_manifest": {"DOC1": "complete"}},
        }
        self.assertTrue(_is_terminal_transaction_result(prior, [{"doc_id": "DOC1", "status": "complete"}]))
        self.assertFalse(_is_terminal_transaction_result(prior, [
            {"doc_id": "DOC1", "status": "complete"},
            {"doc_id": "DOC2", "status": "complete"},
        ]))

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
