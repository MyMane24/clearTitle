"""Title-chain storage (Phase A).

Chain building itself is covered by ``test_chain_builder.py``.
"""

import json
import unittest
from unittest.mock import patch

from backend.database.repositories import agent_repo


class TestPhaseAStorage(unittest.TestCase):
    @patch("backend.database.repositories.agent_repo._get_conn")
    def test_saves_the_chain_its_requests_and_its_source_documents(self, get_conn):
        conn = get_conn.return_value.__enter__.return_value
        cursor = conn.cursor.return_value
        result = {
            "property_identity": {"details": [{"label": "Flat", "value": "G-04"}]},
            "title_chain_graph": "Root -> Owner",
            "title_chain": [{
                "chain_position": 1,
                "documented_transaction": {"transaction_type": "Sale"},
            }],
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


if __name__ == "__main__":
    unittest.main()
