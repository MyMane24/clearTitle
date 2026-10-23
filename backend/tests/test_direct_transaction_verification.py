import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

from backend.services.agent_tools import ToolContext, _canonical_verification, _current_transaction_metadata, dispatch, tools_for
from backend.services.cleartitle_agent import (
    _phase_a_transactions,
    _resolve_tx_ref,
    _run,
    _run_with_lock,
    _skip_transaction_locked,
    _verify_instruction,
)


class TestDirectTransactionVerification(unittest.TestCase):
    def setUp(self):
        self.phase_a = {
            "property_identity": {"details": []},
            "title_chain_graph": "Owner A -> Owner B",
            "title_chain": [
                {
                    "chain_position": 1,
                    "documented_transaction": {
                        "transaction_type": "Gift deed",
                        "transaction_number": "REG-1",
                        "summary_points": ["Gift from A to B"],
                        "source_refs": [{"doc_id": "DOC1"}],
                    },
                    "related_events": [],
                },
                {
                    "chain_position": 2,
                    "documented_transaction": {
                        "transaction_type": "Sale deed",
                        "transaction_number": "REG-2",
                        "summary_points": ["Sale from B to C"],
                        "source_refs": [{"doc_id": "DOC2"}],
                    },
                    "related_events": [{"type": "Mortgage", "summary_points": ["Mortgage recorded"]}],
                },
            ],
        }

    def test_phase_a_entries_become_stable_verification_transactions(self):
        transactions = _phase_a_transactions(self.phase_a)
        self.assertEqual([tx["tx_id"] for tx in transactions], ["PA-TC-0001", "PA-TC-0002"])
        self.assertEqual(transactions[0]["transaction_type"], "Gift deed")
        self.assertEqual(transactions[1]["related_events"][0]["type"], "Mortgage")
        self.assertFalse(transactions[0]["is_current_owner_transaction"])
        self.assertTrue(transactions[1]["is_current_owner_transaction"])
        self.assertEqual(_resolve_tx_ref({"transactions": transactions}, "PA-TC-0002"), "PA-TC-0002")
        self.assertEqual(_resolve_tx_ref({"transactions": transactions}, "2"), "PA-TC-0002")

    def test_phase_a_preserves_previously_assigned_transaction_ids(self):
        chain = {"title_chain": [{
            "tx_id": "T01",
            "chain_position": 1,
            "documented_transaction": {"transaction_type": "Sale"},
        }]}
        self.assertEqual(_phase_a_transactions(chain)[0]["tx_id"], "T01")

    def test_legacy_transaction_id_uses_its_chain_entry_and_sequence(self):
        from backend.services.agent_tools import _canonical_verification, _phase_a_entry_for_id

        entry = {
            "tx_id": "T01", "chain_position": 1,
            "documented_transaction": {"transaction_type": "Sale"},
        }
        ctx = ToolContext("CASE1", [], current_tx_id="T01", phase_a_chain=[entry])
        self.assertIs(_phase_a_entry_for_id(ctx, "T01"), entry)
        with patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None):
            payload = _canonical_verification(ctx, {
                "tx_id": "T01", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
                "summary": "Original deed is outstanding.", "findings": [],
                "required_documents": [{"document_type": "Original deed", "reason": "Verify transfer."}],
            }, force_pending=True)
        self.assertEqual(payload["tx_id"], "T01")
        self.assertEqual(payload["sequence"], 1)

    def test_succession_death_date_is_not_emitted_as_instrument_execution_date(self):
        chain = {"title_chain": [{
            "chain_position": 1,
            "documented_transaction": {
                "transaction_type": "Succession on death",
                "executed_date": "13 January 1981",
                "summary_points": ["Vijayabai died on 13 January 1981."],
            },
        }]}
        transaction = _phase_a_transactions(chain)[0]
        ctx = ToolContext("CASE1", [], phase_a_chain=chain["title_chain"], current_tx_id=transaction["tx_id"])
        self.assertIsNone(transaction["executed_date"])
        self.assertNotIn("executed_date", _current_transaction_metadata(ctx, transaction["tx_id"]))

    def test_succession_and_later_partition_remain_separate_transactions(self):
        chain = {"title_chain": [
            {"chain_position": 1, "documented_transaction": {
                "transaction_type": "Succession on death",
                "executed_date": "13 January 1981",
                "summary_points": ["The recital reports Vijayabai's death and succession."],
            }},
            {"chain_position": 2, "documented_transaction": {
                "transaction_type": "Partition",
                "executed_date": None,
                "summary_points": ["The recital reports partition and Mutation Entry 4930 in 1988."],
            }},
        ]}
        transactions = _phase_a_transactions(chain)
        self.assertEqual([item["tx_id"] for item in transactions], ["PA-TC-0001", "PA-TC-0002"])
        self.assertIn("Succession", transactions[0]["transaction_type"])
        self.assertEqual(transactions[0]["executed_date"], None)
        self.assertEqual(transactions[1]["transaction_type"], "Partition")
        self.assertIsNone(transactions[1]["executed_date"])

    def test_verification_instruction_includes_skill_and_applicable_rules(self):
        instruction = _verify_instruction(_phase_a_transactions(self.phase_a)[0])
        self.assertIn("MANDATORY TRANSACTION-VERIFICATION SKILL", instruction)
        self.assertIn("Gift deed", instruction)
        self.assertNotIn("persisted TODO", instruction)

    def test_verification_tools_have_no_plan_or_todo_tools(self):
        names = {tool["name"] for tool in tools_for("verify")}
        self.assertNotIn("save_verification_plan", names)
        self.assertNotIn("update_todo_step", names)
        self.assertIn("request_missing_documents", names)
        self.assertIn("save_transaction_result", names)
        self.assertIn("record_evidence_requirements", names)
        self.assertIn("select_documents", names)

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="Full deed OCR")
    def test_verification_requires_requirements_then_summary_selection_before_ocr(self, get_text):
        docs = [{
            "doc_id": "DOC1", "filename": "gift.pdf", "document_type": "GIFT_DEED",
            "status": "structured", "summary": "Registered gift deed from A to B.",
        }]
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", docs, chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])

        self.assertIn("record evidence requirements", dispatch(ctx, "list_documents", {})["error"])
        self.assertIn("non-empty", dispatch(ctx, "record_evidence_requirements", {"requirements": []})["error"])
        dispatch(ctx, "record_evidence_requirements", {"requirements": [
            {"document_type": "Gift deed", "reason": "Confirm transfer instrument"},
        ]})
        listed = dispatch(ctx, "list_documents", {})
        self.assertEqual(listed["documents"][0]["doc_id"], "DOC1")
        self.assertIn("select this document", dispatch(ctx, "get_document_text", {"doc_id": "DOC1"})["error"])
        dispatch(ctx, "select_documents", {"doc_ids": ["DOC1"]})
        self.assertEqual(dispatch(ctx, "get_document_text", {"doc_id": "DOC1"})["text"], "Full deed OCR")
        get_text.assert_called_once_with("CASE1", "DOC1")

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_pending_saved_result_with_missing_documents_pauses_transaction(self, get_result, save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])

        result = dispatch(ctx, "save_transaction_result", {
            "tx_id": "PA-TC-0001",
            "sequence": 1,
            "status": "PENDING_NOT_VERIFIED",
            "summary": "The primary deed is unavailable, so this transfer remains unverified.",
            "required_documents": [{
                "document_type": "Certified sale deed",
                "reason": "Verify the transferor's interest.",
            }],
        })

        self.assertTrue(result["paused"])
        self.assertEqual(ctx.missing_requests[0]["tx_id"], "PA-TC-0001")
        self.assertEqual(ctx.missing_requests[0]["documents"][0]["document_type"], "Certified sale deed")
        saved = save_result.call_args.kwargs["verification"]
        self.assertIn("required_documents", saved)
        self.assertNotIn("missing_documents", saved)
        self.assertNotIn("conclusion", saved)
        save_result.assert_called_once()

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_invalid_output_is_rejected_without_persistence(self, get_result, save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        response = dispatch(ctx, "save_transaction_result", {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "MADE_UP",
            "summary": "Unsupported status", "conclusion": "legacy alias",
        })
        self.assertIn("error", response)
        save_result.assert_not_called()

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_nested_finding_aliases_are_rejected_by_canonical_contract(self, get_result, save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        response = dispatch(ctx, "save_transaction_result", {
            "tx_id": "PA-TC-0001", "sequence": 1,
            "status": "ISSUES_IDENTIFIED", "summary": "A discrepancy is documented.",
            "findings": [{"description": "Descriptions differ", "evidence": [{"doc_id": "DOC1"}]}],
        })
        self.assertIn("error", response)
        save_result.assert_not_called()

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_tool_schema_is_derived_from_canonical_result_contract(self, get_result, save_result):
        schema = next(tool for tool in tools_for("verify") if tool["name"] == "save_transaction_result")["parameters"]
        self.assertEqual(set(schema["properties"]), set(__import__(
            "backend.services.agent_schemas", fromlist=["TransactionVerification"]
        ).TransactionVerification.model_fields))
        self.assertTrue({"tx_id", "sequence", "status", "summary"}.issubset(set(schema["required"])))
        self.assertNotIn("missing_documents", schema["properties"])
        self.assertNotIn("conclusion", schema["properties"])

    @patch("backend.services.agent_tools.repo.save_transaction_result")
    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_duplicate_outstanding_requirements_are_collapsed(self, get_result, save_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        requirement = {"document_type": "Sale deed", "reason": "Verify transfer"}
        dispatch(ctx, "save_transaction_result", {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
            "summary": "The transfer remains unverified.",
            "required_documents": [requirement, dict(requirement)],
        })
        self.assertEqual(len(save_result.call_args.kwargs["verification"]["required_documents"]), 1)

    @patch("backend.services.agent_tools.repo.get_transaction_result")
    def test_resume_preserves_prior_findings_evidence_and_reviewed_ids(self, get_result):
        tx = _phase_a_transactions(self.phase_a)[0]
        prior = {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
            "summary": "Still awaiting primary evidence.",
            "findings": [{"description": "Later deed recites this transfer.", "source_refs": [{"doc_id": "DOC1", "page": "2"}]}],
            "supporting_evidence": [{"doc_id": "DOC1", "page": "2"}],
            "contradictory_evidence": [{"doc_id": "DOC2", "page": "4"}],
            "required_documents": [{"document_type": "Original deed", "reason": "Verify conveyance"}],
            "reviewed_document_ids": ["DOC1"],
        }
        get_result.return_value = prior
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id=tx["tx_id"])
        ctx.selected_document_ids.add("DOC3")

        result = _canonical_verification(ctx, {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "INCONCLUSIVE",
            "summary": "The records remain inconclusive after reviewing an additional record.",
            "required_documents": [],
        })

        self.assertEqual(result["findings"][0]["title"], "Evidence finding")
        self.assertIn("Later deed recites this transfer.", result["findings"][0]["details"])
        self.assertEqual(result["findings"][0]["evidence"][0]["pages"], "2")
        self.assertEqual(result["findings"][-1]["evidence"][0]["doc_id"], "DOC2")
        self.assertEqual(result["required_documents"], [])
        self.assertEqual(result["reviewed_document_ids"], ["DOC1", "DOC3"])
        self.assertIsNotNone(result["verified_at"])

    @patch("backend.services.cleartitle_agent._sync_case_verdict")
    @patch("backend.services.cleartitle_agent._verify_transaction")
    @patch("backend.services.cleartitle_agent.ensure_summaries")
    @patch("backend.services.cleartitle_agent.repo")
    def test_run_verifies_pending_phase_a_entries_and_skips_completed(self, repo, ensure, verify, sync_verdict):
        repo.get_agent_documents.return_value = [{"doc_id": "DOC1"}]
        repo.get_agent_memory.return_value = {}
        repo.get_agent_result.return_value = self.phase_a
        repo.get_transaction_result.side_effect = [
            {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"},
            {"status": "PENDING_NOT_VERIFIED"},
            {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"},
        ]
        repo.list_transaction_results.return_value = [{"tx_id": "PA-TC-0002", "status": "PENDING_NOT_VERIFIED"}]
        verify.return_value = SimpleNamespace(missing_requests=[], saved_results=[{"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"}])

        outcome = _run("CASE1")

        self.assertEqual(outcome["status"], "done")
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(verify.call_args.args[3]["tx_id"], "PA-TC-0002")
        self.assertEqual(verify.call_args.args[2], self.phase_a)
        repo.get_title_chain.assert_not_called()
        repo.save_agent_result.assert_not_called()

    @patch("backend.services.cleartitle_agent._sync_case_verdict")
    @patch("backend.services.cleartitle_agent._verify_transaction")
    @patch("backend.services.cleartitle_agent.ensure_summaries")
    @patch("backend.services.cleartitle_agent.repo")
    def test_run_pauses_current_transaction_when_verifier_requests_missing_evidence(self, repo, ensure, verify, sync_verdict):
        repo.get_agent_documents.return_value = [{"doc_id": "DOC1"}]
        repo.get_agent_memory.return_value = {}
        repo.get_agent_result.return_value = self.phase_a
        repo.get_transaction_result.return_value = None
        verify.return_value = SimpleNamespace(missing_requests=[{
            "tx_id": "PA-TC-0001",
            "documents": [{"document_type": "Certified gift deed", "reason": "Confirm registered gift instrument"}],
        }])

        outcome = _run("CASE1")

        self.assertEqual(outcome["status"], "paused")
        self.assertEqual(outcome["paused_transaction"], "PA-TC-0001")
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(outcome["missing_documents"][0]["document_type"], "Certified gift deed")

    @patch("backend.services.cleartitle_agent._run", return_value={"status": "done"})
    @patch("backend.services.cleartitle_agent.repo")
    def test_skipping_paused_transaction_preserves_result_and_continues(self, repo, run):
        repo.get_agent_result.return_value = self.phase_a
        repo.get_agent_memory.return_value = {
            "paused_transaction": "PA-TC-0002",
            "skipped_tx_ids": ["PA-TC-0001"],
            "pending_tx_ids": ["PA-TC-0001"],
        }
        prior = {
            "tx_id": "PA-TC-0002", "sequence": 2,
            "status": "PENDING_NOT_VERIFIED", "summary": "Succession is recital-reported.",
            "transaction_metadata": {"transaction_type": "Succession"},
            "required_documents": [{"document_type": "Death record", "reason": "Verify succession"}],
            "findings": [{"description": "Succession is recital-reported"}],
        }
        repo.get_transaction_result.return_value = prior

        outcome = _skip_transaction_locked("CASE1", "PA-TC-0002")

        self.assertEqual(outcome["status"], "done")
        repo.save_transaction_result.assert_not_called()
        self.assertEqual(repo.get_transaction_result.return_value, prior)
        saved_memory = repo.save_agent_memory.call_args.kwargs["memory"]
        self.assertEqual(saved_memory["skipped_tx_ids"], ["PA-TC-0001", "PA-TC-0002"])
        run.assert_called_once_with("CASE1", skip_tx_ids={"PA-TC-0001", "PA-TC-0002"})

    @patch("backend.services.cleartitle_agent.repo")
    def test_only_currently_paused_transaction_can_be_skipped(self, repo):
        repo.get_agent_result.return_value = self.phase_a
        repo.get_agent_memory.return_value = {"paused_transaction": "PA-TC-0002"}

        outcome = _skip_transaction_locked("CASE1", "PA-TC-0001")

        self.assertEqual(outcome["status"], "error")
        repo.save_transaction_result.assert_not_called()

    @patch("backend.services.cleartitle_agent.PIPELINE_LOCK_ENABLED", False)
    @patch("backend.services.cleartitle_agent._run", return_value={"status": "paused"})
    @patch("backend.services.cleartitle_agent.repo")
    def test_new_analysis_resume_retries_persistently_skipped_transactions(self, repo, run):
        repo.get_agent_memory.return_value = {"skipped_tx_ids": ["PA-TC-0001"]}

        _run_with_lock("CASE1")

        saved_memory = repo.save_agent_memory.call_args.kwargs["memory"]
        self.assertEqual(saved_memory["skipped_tx_ids"], [])
        run.assert_called_once_with("CASE1", skip_tx_ids=set())


if __name__ == "__main__":
    unittest.main()
