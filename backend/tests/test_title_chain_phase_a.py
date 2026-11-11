import json
import unittest
from unittest.mock import patch

from backend.services.agent_tools import ToolContext, dispatch
from backend.services.cleartitle_agent import _phase_a_instruction
from backend.services.results import _agent_block
from backend.database.repositories import agent_repo


class TestTitleChainPhaseATools(unittest.TestCase):
    def setUp(self):
        self.ctx = ToolContext("CASE1", [
            {
                "doc_id": "DOC_001",
                "summary": "Latest sale deed for Flat G-04",
                "filename": "private-filename.pdf",
                "document_type": "SALE_DEED",
            },
        ])

    def test_document_manifest_includes_summary_and_processing_metadata(self):
        result = dispatch(self.ctx, "list_documents", {})
        self.assertEqual(result, {
            "documents": [{"doc_id": "DOC_001", "filename": "private-filename.pdf", "document_type": "SALE_DEED", "status": "unknown", "summary": "Latest sale deed for Flat G-04"}],
        })

    def test_phase_a_instruction_always_embeds_title_chain_skill_and_all_summaries(self):
        instruction = _phase_a_instruction([
            {"doc_id": "DOC_001", "summary": "Latest deed"},
            {"doc_id": "DOC_002", "summary": "Encumbrance certificate"},
        ])
        self.assertIn("MANDATORY SKILL", instruction)
        self.assertIn("Filter EC entries", instruction)
        self.assertIn("DOC_001 | citation filename: (filename unavailable) | summary: Latest deed", instruction)
        self.assertIn("DOC_002 | citation filename: (filename unavailable) | summary: Encumbrance certificate", instruction)

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="0123456789")
    def test_ocr_tool_reads_database_text_in_chunks(self, read_text):
        result = dispatch(self.ctx, "get_document_text", {
            "doc_id": "DOC_001", "start_char": 4, "max_chars": 3,
        })
        self.assertEqual(result["text"], "456")
        self.assertEqual(result["next_start_char"], 7)
        self.assertTrue(result["has_more"])
        read_text.assert_called_once_with("CASE1", "DOC_001")

    @patch("backend.services.agent_tools.repo.save_phase_a_result")
    def test_phase_a_saves_result_without_rewriting_and_checks_source_ids(self, save):
        output = {
            "property_identity": {"details": [{"label": "Flat", "value": "G-04"}]},
            "title_chain_graph": "Owner A -> Owner B",
            "title_chain": [{
                "chain_position": 1,
                "documented_transaction": {
                    "transaction_number": "DOC-17", "transaction_type": "Sale deed",
                    "executed_date": "unknown", "summary_points": ["The deed transfers the described property."],
                    "source_refs": [{"doc_id": "DOC_001", "filename": "private-filename.pdf"}],
                    "arbitrary_document_specific_detail": "preserved",
                },
            }],
        }
        result = dispatch(self.ctx, "save_phase_a_result", {"result": output})
        self.assertTrue(result["saved"])
        self.assertIs(self.ctx.saved_phase_a_result, output)
        save.assert_called_once_with(case_id="CASE1", result=output)

    @patch("backend.services.agent_tools.repo.save_phase_a_result")
    def test_phase_a_rejects_unknown_document_references(self, save):
        output = {
            "property_identity": {"details": []},
            "title_chain_graph": "A -> B",
            "title_chain": [{
                "chain_position": 1,
                "documented_transaction": {
                    "transaction_number": None, "transaction_type": "Sale deed",
                    "executed_date": "unknown", "summary_points": ["The deed transfers the described property."],
                    "source_refs": [{"doc_id": "OTHER_CASE_DOC", "filename": "private-filename.pdf"}],
                },
            }],
        }
        result = dispatch(self.ctx, "save_phase_a_result", {"result": output})
        self.assertIn("outside this case", result["error"])
        save.assert_not_called()

    @patch("backend.services.agent_tools.repo.save_phase_a_result")
    def test_phase_a_rejects_duplicate_registration_numbers(self, save):
        transaction = {
            "transaction_number": "REG-2024-1",
            "transaction_type": "Sale deed",
            "executed_date": "2024-03-02",
            "summary_points": ["The owner conveyed the property to the purchasers."],
            "source_refs": [{"doc_id": "DOC_001", "filename": "private-filename.pdf"}],
        }
        output = {
            "property_identity": {"details": []},
            "title_chain_graph": "Owner -> Purchaser",
            "title_chain": [
                {"chain_position": 1, "documented_transaction": transaction},
                {"chain_position": 2, "documented_transaction": {**transaction}},
            ],
        }

        result = dispatch(self.ctx, "save_phase_a_result", {"result": output})

        self.assertIn("duplicate transaction_number", result["error"])
        save.assert_not_called()

    @patch("backend.database.repositories.agent_repo.get_agent_state")
    def test_results_api_block_passes_agent_output_without_plan(self, get_state):
        identity = {"details": [{"label": "Flat", "value": "G-04"}]}
        graph = "Owner A -> Owner B"
        get_state.return_value = {
            "status": "done",
            "memory": {"stage": "phase_a_complete"},
            "case_result": [{
                "tx_id": "PA-TC-0001", "status": "INCONCLUSIVE",
                "report": "## Findings\n\nThe prior link is recital-reported.",
            }],
            "result": {
                "property_identity": identity,
                "title_chain_graph": graph,
                "title_chain": [{"chain_position": 1, "documented_transaction": {}}],
            },
        }
        block = _agent_block("CASE1")
        self.assertIs(block["property_identity"], identity)
        self.assertEqual(block["title_chain_graph"], graph)
        self.assertEqual(block["title_chain"], [{"chain_position": 1, "documented_transaction": {}}])
        self.assertEqual(block["overall_status"], "INCONCLUSIVE")
        self.assertEqual(block["transactions"][0]["tx_id"], "PA-TC-0001")
        self.assertNotIn("findings", block)
        self.assertIn("The prior link is recital-reported.", block["transactions"][0]["report"])
        self.assertNotIn("verification_plan", block)


class TestPhaseAIdentityAssignment(unittest.TestCase):
    """Implementation 1: app-stamped stable transaction ids at the Phase A save boundary."""

    def setUp(self):
        self.ctx = self._context()

    def _context(self):
        return ToolContext("CASE1", [
            {"doc_id": "DOC_001", "summary": "Latest sale deed", "filename": "deed.pdf", "document_type": "SALE_DEED"},
            {"doc_id": "DOC_002", "summary": "Encumbrance certificate", "filename": "ec.pdf", "document_type": "EC"},
        ])

    def _entry(self, position, transaction_type, *, reg_number=None, executed_date=None,
               transferors=(), transferees=(), source_refs=("DOC_001",)):
        # Registered filenames per _context: citing DOC_002 as "deed.pdf" makes
        # the citation-preservation sweep reject the save.
        filenames = {"DOC_001": "deed.pdf", "DOC_002": "ec.pdf"}
        return {"chain_position": position, "documented_transaction": {
            "transaction_type": transaction_type, "transaction_number": reg_number,
            "executed_date": executed_date,
            "transferors": list(transferors), "transferees": list(transferees),
            "summary_points": ["The deed transfers the described property."],
            "source_refs": [{"doc_id": doc_id, "filename": filenames.get(doc_id, "deed.pdf")}
                            for doc_id in source_refs],
        }}

    def _run_save(self, chain, *, prior_chain=None, prior_results=None,
                  chain_error=None, results_error=None, ctx=None):
        result = {
            "property_identity": {"details": [{"label": "Flat", "value": "G-04"}]},
            "title_chain_graph": "Owner A -> Owner B",
            "title_chain": chain,
        }
        used = ctx or self.ctx
        with patch("backend.services.agent_tools.repo.save_phase_a_result") as save_phase_a, \
             patch("backend.services.agent_tools.repo.get_persisted_title_chain_entries",
                   side_effect=chain_error, return_value=prior_chain or []), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results",
                   side_effect=results_error, return_value=prior_results or []):
            response = dispatch(used, "save_phase_a_result", {"result": result})
        return response, used.saved_phase_a_result, save_phase_a

    def test_save_stamps_ids_and_upstream_links_and_reports_the_assignment(self):
        chain = [
            self._entry(1, "Sale deed", transferors=["A"], transferees=["B"]),
            self._entry(2, "Sale deed", transferors=["B"], transferees=["C"]),
        ]
        response, saved, _ = self._run_save(chain)
        self.assertTrue(response["saved"])
        self.assertEqual(response["transaction_ids"], ["PA-TC-0001", "PA-TC-0002"])
        self.assertEqual(saved["title_chain"][0]["tx_id"], "PA-TC-0001")
        self.assertEqual(saved["title_chain"][1]["tx_id"], "PA-TC-0002")
        self.assertIsNone(saved["title_chain"][0].get("upstream_tx_ids"))
        self.assertEqual(saved["title_chain"][1]["upstream_tx_ids"], ["PA-TC-0001"])
        self.assertTrue(response["identity_notes"])

    def test_rerun_with_reordered_matching_content_keeps_transaction_ids(self):
        prior = [
            {"chain_position": 1, "tx_id": "PA-TC-0001", "documented_transaction": {
                "transaction_type": "Sale deed", "transaction_number": "REG-1",
                "executed_date": "2012-04-05", "summary_points": ["At sale time."],
                "source_refs": [{"doc_id": "DOC_001"}]}},
            {"chain_position": 2, "tx_id": "PA-TC-0002", "documented_transaction": {
                "transaction_type": "Gift deed", "transaction_number": "REG-2",
                "summary_points": ["At gift time."],
                "source_refs": [{"doc_id": "DOC_001"}]}},
        ]
        chain = [
            self._entry(1, "Gift deed", reg_number="REG-2", source_refs=("DOC_001",)),
            self._entry(2, "Sale deed", reg_number="REG-1", executed_date="2012-04-05"),
        ]
        response, saved, _ = self._run_save(chain, prior_chain=prior)
        self.assertEqual(response["transaction_ids"], ["PA-TC-0002", "PA-TC-0001"])
        self.assertEqual([entry["tx_id"] for entry in saved["title_chain"]], ["PA-TC-0002", "PA-TC-0001"])
        self.assertTrue(any("keeps PA-TC-0002" in note for note in response["identity_notes"]))

    def _assert_retriable_abort(self, response, save_phase_a):
        self.assertFalse(response.get("saved"))
        self.assertIn("cannot safely assign transaction ids", response["error"])
        self.assertIn("Nothing was saved", response["error"])
        self.assertTrue(response["retryable"])
        save_phase_a.assert_not_called()
        self.assertIsNone(self.ctx.saved_phase_a_result)
        self.assertFalse(self.ctx.finished)

    def test_failed_prior_chain_read_aborts_the_save_without_persistence(self):
        # A failed historical read is an unknown identity state, never an empty
        # one: aborting keeps every persisted id exactly as it is.
        chain = [self._entry(1, "Sale deed"), self._entry(2, "Gift deed")]
        response, saved, save_phase_a = self._run_save(
            chain, chain_error=RuntimeError("db down on title_chains"))
        self._assert_retriable_abort(response, save_phase_a)
        self.assertIsNone(saved)
        self.assertEqual([entry.get("tx_id") for entry in chain], [None, None])

    def test_failed_transaction_results_read_aborts_the_save_without_persistence(self):
        response, _, save_phase_a = self._run_save(
            [self._entry(1, "Sale deed")], results_error=RuntimeError("db down on case_results"))
        self._assert_retriable_abort(response, save_phase_a)

    def test_both_historical_reads_failing_abort_the_save(self):
        response, _, save_phase_a = self._run_save(
            [self._entry(1, "Sale deed")],
            chain_error=RuntimeError("db down"), results_error=RuntimeError("db down"))
        self._assert_retriable_abort(response, save_phase_a)

    def test_retry_after_recovery_reconciles_ids_against_the_persisted_history(self):
        prior = [
            {"chain_position": 1, "tx_id": "PA-TC-0001", "documented_transaction": {
                "transaction_type": "Sale deed", "transaction_number": "REG-1",
                "executed_date": "2012-04-05", "source_refs": [{"doc_id": "DOC_001"}]}},
            {"chain_position": 2, "tx_id": "PA-TC-0002", "documented_transaction": {
                "transaction_type": "Gift deed", "transaction_number": "REG-2",
                "source_refs": [{"doc_id": "DOC_001"}]}},
        ]
        chain = [
            self._entry(1, "Gift deed", reg_number="REG-2", source_refs=("DOC_001",)),
            self._entry(2, "Sale deed", reg_number="REG-1", executed_date="2012-04-05"),
        ]
        response, _, _ = self._run_save(
            chain, prior_chain=prior, chain_error=RuntimeError("db down"))
        self.assertFalse(response.get("saved"))
        # After recovery, the SAME chain content saves cleanly and receives the
        # persisted ids through normal content matching.
        retry_ctx = self._context()
        response, saved, _ = self._run_save(chain, prior_chain=prior, ctx=retry_ctx)
        self.assertTrue(response["saved"])
        self.assertEqual(response["transaction_ids"], ["PA-TC-0002", "PA-TC-0001"])
        self.assertEqual([entry["tx_id"] for entry in saved["title_chain"]], ["PA-TC-0002", "PA-TC-0001"])

    def test_persisted_transaction_ids_are_never_assigned_to_different_transactions(self):
        # The prior chain holds PA-TC-0001 and a persisted result still carries
        # PA-TC-0002 despite no longer being in the chain. Unrelated rerun
        # content must not claim either id.
        prior = [
            {"chain_position": 1, "tx_id": "PA-TC-0001", "documented_transaction": {
                "transaction_type": "Sale deed", "transaction_number": "REG-1",
                "transferors": ["A"], "transferees": ["B"],
                "source_refs": [{"doc_id": "DOC_001"}]}},
        ]
        prior_results = [
            {"tx_id": "PA-TC-0002", "status": "ISSUES_IDENTIFIED"},
            {"tx_id": "PA-TC-0004", "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"},
        ]
        chain = [
            self._entry(1, "Gift deed", reg_number="REG-9", transferors=("X",), transferees=("Y",)),
            self._entry(2, "Partition deed", reg_number="REG-8", transferors=("P",), transferees=("Q",)),
        ]
        response, saved, _ = self._run_save(chain, prior_chain=prior, prior_results=prior_results)
        self.assertTrue(response["saved"])
        self.assertEqual(response["transaction_ids"], ["PA-TC-0003", "PA-TC-0005"])
        self.assertEqual(saved["title_chain"][0]["tx_id"], "PA-TC-0003")
        self.assertEqual(saved["title_chain"][1]["tx_id"], "PA-TC-0005")

    def test_upstream_link_decisions_are_reported_in_identity_notes(self):
        # The namesake refusal must be visible to the model in the save
        # response so a weak chain link is never silently fabricated. Each
        # entry cites its own source document so the shared-document anchor
        # cannot accidentally corroborate the jump.
        chain = [
            self._entry(1, "Sale deed", transferors=["A"], transferees=["Ram"]),
            self._entry(2, "Sale deed", transferors=["X"], transferees=["Y"], source_refs=("DOC_002",)),
            self._entry(3, "Sale deed", transferors=["Ram"], transferees=["Z"], source_refs=("DOC_002",)),
        ]
        response, saved, _ = self._run_save(chain)
        self.assertTrue(response["saved"])
        self.assertIsNone(saved["title_chain"][2].get("upstream_tx_ids"))
        self.assertTrue(any("refused upstream" in note for note in response["identity_notes"]))


class TestPhaseAStorage(unittest.TestCase):
    @patch("backend.database.repositories.agent_repo._get_conn")
    def test_saves_three_fields_only_to_title_chains(self, get_conn):
        conn = get_conn.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        result = {
            "property_identity": {"details": [{"label": "Flat", "value": "G-04"}]},
            "title_chain_graph": "Root -> Owner",
            "title_chain": [{"chain_position": 1, "documented_transaction": {"transaction_type": "Sale"}}],
        }

        agent_repo.save_phase_a_result(case_id="CASE1", result=result)

        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO title_chains", sql)
        self.assertIn("property_identity", sql)
        self.assertIn("title_chain_graph", sql)
        self.assertIn("detailed_chain", sql)
        self.assertNotIn("cases.agent_result", sql)
        self.assertEqual(params[0:2], ("CASE1", "complete"))
        self.assertEqual(conn.commit.call_count, 1)

    @patch("backend.database.repositories.agent_repo._get_conn")
    def test_reads_phase_a_result_only_from_title_chains(self, get_conn):
        conn = get_conn.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        identity = {"details": [{"label": "Flat", "value": "G-04"}]}
        chain = [{"chain_position": 1, "documented_transaction": {"transaction_type": "Sale"}}]
        cursor.fetchone.return_value = (json.dumps(identity), "Root -> Owner", json.dumps(chain))

        result = agent_repo.get_agent_result("CASE1")

        self.assertEqual(result, {
            "property_identity": identity,
            "title_chain_graph": "Root -> Owner",
            "title_chain": chain,
            "phase_a_hash": None,
        })
        self.assertIn("FROM title_chains", cursor.execute.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
