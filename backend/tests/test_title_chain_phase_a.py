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

    def test_document_manifest_includes_filename_only_for_citation(self):
        result = dispatch(self.ctx, "list_documents", {})
        self.assertEqual(result, {
            "documents": [{"doc_id": "DOC_001", "filename": "private-filename.pdf", "summary": "Latest sale deed for Flat G-04"}]
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
    def test_results_api_block_passes_agent_output_through_without_mapping(self, get_state):
        identity = {"details": [{"label": "Flat", "value": "G-04"}]}
        graph = "Owner A -> Owner B"
        get_state.return_value = {
            "status": "done",
            "memory": {"stage": "phase_a_complete"},
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
        })
        self.assertIn("FROM title_chains", cursor.execute.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
