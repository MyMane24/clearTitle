"""Title-chain storage and its exposure to verification and the results API.

Chain building itself is covered by ``test_chain_builder.py``.
"""

import json
import unittest
from unittest.mock import patch

from backend.database.repositories import agent_repo
from backend.services.agent_tools import ToolContext, dispatch
from backend.services.results import _agent_block


class TestDocumentTools(unittest.TestCase):
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

    @patch("backend.services.agent_tools.repo.get_document_raw_text", return_value="0123456789")
    def test_ocr_tool_reads_database_text_in_chunks(self, read_text):
        result = dispatch(self.ctx, "get_document_text", {
            "doc_id": "DOC_001", "start_char": 4, "max_chars": 3,
        })
        self.assertEqual(result["text"], "456")
        self.assertEqual(result["next_start_char"], 7)
        self.assertTrue(result["has_more"])
        read_text.assert_called_once_with("CASE1", "DOC_001")

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


class TestPhaseAStorage(unittest.TestCase):
    @patch("backend.database.repositories.agent_repo._get_conn")
    def test_saves_the_chain_its_requests_and_its_source_documents(self, get_conn):
        conn = get_conn.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        result = {
            "property_identity": {"details": [{"label": "Flat", "value": "G-04"}]},
            "title_chain_graph": "Root -> Owner",
            "title_chain": [{"chain_position": 1, "documented_transaction": {"transaction_type": "Sale"}}],
            "missing_documents": [{"document": "EC for 1994 to 2010", "reason": "Earlier links."}],
        }

        agent_repo.save_phase_a_result(case_id="CASE1", result=result, chain_doc_ids=["DOC_002"])

        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO title_chains", sql)
        self.assertIn("property_identity", sql)
        self.assertIn("title_chain_graph", sql)
        self.assertIn("detailed_chain", sql)
        self.assertIn("chain_doc_ids", sql)
        self.assertIn("missing_documents", sql)
        self.assertNotIn("cases.agent_result", sql)
        self.assertEqual(params[0:2], ("CASE1", "complete"))
        self.assertEqual(json.loads(params[-2]), ["DOC_002"])
        self.assertEqual(json.loads(params[-1]), result["missing_documents"])
        self.assertEqual(conn.commit.call_count, 1)

    @patch("backend.database.repositories.agent_repo._get_conn")
    def test_reads_phase_a_result_only_from_title_chains(self, get_conn):
        conn = get_conn.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        identity = {"details": [{"label": "Flat", "value": "G-04"}]}
        chain = [{"chain_position": 1, "documented_transaction": {"transaction_type": "Sale"}}]
        cursor.fetchone.return_value = (
            json.dumps(identity), "Root -> Owner", json.dumps(chain), None, None,
            json.dumps(["DOC_002"]), None,
        )

        result = agent_repo.get_agent_result("CASE1")

        self.assertEqual(result, {
            "property_identity": identity,
            "title_chain_graph": "Root -> Owner",
            "title_chain": chain,
            "phase_a_hash": None,
            "chain_doc_ids": ["DOC_002"],
            "missing_documents": [],
        })
        self.assertIn("FROM title_chains", cursor.execute.call_args.args[0])

    @patch("backend.database.repositories.agent_repo._get_conn")
    def test_resequence_moves_saved_results_to_their_new_chain_positions(self, get_conn):
        conn = get_conn.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        cursor.fetchone.return_value = (json.dumps([
            {"tx_id": "PA-TC-0001", "sequence": 1},
            {"tx_id": "PA-TC-0009", "sequence": 5},
        ]),)

        agent_repo.resequence_transaction_results(case_id="CASE1", sequences={"PA-TC-0001": 2})

        sql, params = cursor.execute.call_args.args
        self.assertIn("UPDATE case_results", sql)
        self.assertEqual(json.loads(params[0]), [
            {"tx_id": "PA-TC-0001", "sequence": 2},
            {"tx_id": "PA-TC-0009", "sequence": 5},
        ])
        self.assertEqual(conn.commit.call_count, 1)


if __name__ == "__main__":
    unittest.main()
