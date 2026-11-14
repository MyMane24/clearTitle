"""Stage 2: Phase A hardening — app-assigned tx ids, phase_a_hash, rebuild guard."""

import unittest
from unittest.mock import patch

from backend.schemas.analysis import is_assigned_tx_id, phase_a_hash
from backend.services import cleartitle_agent


def _chain(entries):
    return {"title_chain": entries}


class TestAppAssignedTxIds(unittest.TestCase):
    def test_missing_ids_become_positional(self):
        phase_a = _chain([
            {"chain_position": 1, "documented_transaction": {"transaction_type": "Sale"}},
            {"chain_position": 2, "documented_transaction": {"transaction_type": "Gift"}},
        ])
        transactions = cleartitle_agent._phase_a_transactions(phase_a)
        self.assertEqual([tx["tx_id"] for tx in transactions], ["PA-TC-0001", "PA-TC-0002"])
        self.assertTrue(is_assigned_tx_id(transactions[0]["tx_id"]))

    def test_model_supplied_ids_never_reach_assignment(self):
        phase_a = _chain([
            {"tx_id": "T01", "chain_position": 1,
             "documented_transaction": {"transaction_type": "Sale"}},
            # Live-observed shape: the model echoed the whole case id into the
            # transaction-level tx_id (audit D2).
            {"chain_position": 2,
             "documented_transaction": {"transaction_type": "Gift", "tx_id": "0C3695AD"}},
        ])
        transactions = cleartitle_agent._phase_a_transactions(phase_a)
        self.assertEqual([tx["tx_id"] for tx in transactions], ["PA-TC-0001", "PA-TC-0002"])

    def test_previously_assigned_ids_survive_even_at_wrong_position(self):
        phase_a = _chain([
            {"tx_id": "PA-TC-0007", "chain_position": 1,
             "documented_transaction": {"transaction_type": "Sale"}},
            {"tx_id": "LEGACY-abc123", "chain_position": 2,
             "documented_transaction": {"transaction_type": "Gift"}},
        ])
        transactions = cleartitle_agent._phase_a_transactions(phase_a)
        self.assertEqual([tx["tx_id"] for tx in transactions], ["PA-TC-0007", "LEGACY-abc123"])

    def test_duplicate_claim_falls_back_to_positional(self):
        phase_a = _chain([
            {"tx_id": "PA-TC-0003", "chain_position": 1,
             "documented_transaction": {"transaction_type": "Sale"}},
            {"tx_id": "PA-TC-0003", "chain_position": 2,
             "documented_transaction": {"transaction_type": "Gift"}},
        ])
        transactions = cleartitle_agent._phase_a_transactions(phase_a)
        self.assertEqual([tx["tx_id"] for tx in transactions], ["PA-TC-0003", "PA-TC-0002"])

    def test_assignment_is_written_back_for_readers(self):
        chain = _chain([{"chain_position": 1,
                         "documented_transaction": {"transaction_type": "Sale"}}])
        cleartitle_agent._phase_a_transactions(chain)
        self.assertEqual(chain["title_chain"][0]["tx_id"], "PA-TC-0001")


class TestPhaseAHash(unittest.TestCase):
    def _phase_a(self):
        return {
            "property_identity": {"details": [{"label": "L", "value": "V"}]},
            "title_chain": [{"chain_position": 1, "documented_transaction": {"transaction_type": "Sale"}}],
            "title_chain_graph": "A -> B",
        }

    def test_stable_across_key_order_and_extra_keys(self):
        reordered = {
            "title_chain_graph": "A -> B",
            "title_chain": [{"chain_position": 1, "documented_transaction": {"transaction_type": "Sale"}}],
            "property_identity": {"details": [{"value": "V", "label": "L"}]},
        }
        self.assertEqual(phase_a_hash(self._phase_a()), phase_a_hash(reordered))
        self.assertEqual(
            phase_a_hash(self._phase_a()),
            phase_a_hash({**self._phase_a(), "phase_a_hash": "stored"}),
        )

    def test_sensitive_to_chain_changes_but_not_to_graph_prose(self):
        mutated = self._phase_a()
        mutated["title_chain"][0]["chain_position"] = 2
        self.assertNotEqual(phase_a_hash(self._phase_a()), phase_a_hash(mutated))
        graph_only = self._phase_a()
        graph_only["title_chain_graph"] = "B -> A"
        self.assertEqual(phase_a_hash(self._phase_a()), phase_a_hash(graph_only))

    def test_mismatch_helper_semantics(self):
        self.assertIsNone(cleartitle_agent._phase_a_hash_mismatch(self._phase_a()))
        phase_a = {**self._phase_a(), "phase_a_hash": "deadbeef"}
        self.assertEqual(cleartitle_agent._phase_a_hash_mismatch(phase_a), "deadbeef")
        correct = {**self._phase_a(), "phase_a_hash": phase_a_hash(self._phase_a())}
        self.assertIsNone(cleartitle_agent._phase_a_hash_mismatch(correct))


class TestRebuildGuard(unittest.TestCase):
    def test_refuses_rebuild_when_results_exist_without_chain(self):
        with patch.object(cleartitle_agent.repo, "get_agent_documents",
                          return_value=[{"doc_id": "D1"}]), \
                patch.object(cleartitle_agent.repo, "get_agent_memory", return_value={}), \
                patch.object(cleartitle_agent.repo, "get_agent_result", return_value={}), \
                patch.object(cleartitle_agent.repo, "set_agent_status") as set_status, \
                patch.object(cleartitle_agent.repo, "list_transaction_results",
                             return_value=[{"tx_id": "PA-TC-0001"}]) as results, \
                patch.object(cleartitle_agent, "_sync_case_verdict"):
            outcome = cleartitle_agent._run("CASE1")
        self.assertEqual(outcome["status"], cleartitle_agent.STATUS_ERROR)
        self.assertIn("refusing to rebuild", outcome["reason"])
        self.assertEqual(
            set_status.call_args[-1],
            {"case_id": "CASE1", "status": cleartitle_agent.STATUS_ERROR},
        )
        results.assert_called_once()

    def test_rebuild_proceeds_for_a_case_without_results(self):
        from types import SimpleNamespace

        ctx = SimpleNamespace(
            missing_requests=[],
            saved_results=[{"tx_id": "PA-TC-0001"}],
            selected_document_ids=set(),
        )
        saved_result = {"tx_id": "PA-TC-0001", "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE", "report": "done"}
        with patch.object(cleartitle_agent.repo, "get_agent_documents",
                          return_value=[{"doc_id": "D1"}]), \
                patch.object(cleartitle_agent.repo, "get_agent_memory", return_value={}), \
                patch.object(cleartitle_agent.repo, "get_agent_result", return_value={}), \
                patch.object(cleartitle_agent.repo, "list_transaction_results", return_value=[]), \
                patch.object(cleartitle_agent, "ensure_summaries"), \
                patch.object(cleartitle_agent, "_build_phase_a",
                             return_value={"title_chain": [{
                                 "chain_position": 1,
                                 "documented_transaction": {"transaction_type": "Sale"},
                             }]}), \
                patch.object(cleartitle_agent, "_save_state"), \
                patch.object(cleartitle_agent.repo, "get_transaction_result",
                             side_effect=[None, saved_result]), \
                patch.object(cleartitle_agent, "_sync_case_verdict"), \
                patch.object(cleartitle_agent, "_verify_transaction", return_value=ctx) as verify:
            outcome = cleartitle_agent._run("CASE1")
        verify.assert_called_once()
        self.assertNotIn("reason", outcome)
        self.assertEqual(outcome["status"], cleartitle_agent.STATUS_DONE)


class TestPhaseAHashPersistence(unittest.TestCase):
    def test_save_stamps_hash_into_title_chains_row(self):
        from backend.database.repositories import agent_repo

        class Cursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, params=None):
                self.calls.append((sql, params))

        cursor = Cursor()
        with patch.object(agent_repo, "_get_conn", return_value=type(
                "Conn", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: False,
                             "cursor": lambda s, **k: cursor, "commit": lambda s: None})()):
            agent_repo.save_phase_a_result(case_id="CASE1", result={
                "property_identity": {"details": []},
                "title_chain_graph": "A->B",
                "title_chain": [{"chain_position": 1}],
            })
        sql, params = cursor.calls[-1]
        self.assertIn("phase_a_hash", sql)
        expected = phase_a_hash({"property_identity": {"details": []}, "title_chain": [{"chain_position": 1}]})
        self.assertEqual(params[5], expected)

    def test_get_agent_result_returns_stored_hash(self):
        from backend.database.repositories import agent_repo

        stored = "a" * 64

        class Cursor:
            def execute(self, sql=None, params=None):
                self.sql = sql

            def fetchone(self):
                return ("{}", "A->B", "[]", None, stored)

        with patch.object(agent_repo, "_get_conn", return_value=type(
                "Conn", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: False,
                             "cursor": lambda s, **k: Cursor(), "commit": lambda s: None})()):
            result = agent_repo.get_agent_result("CASE1")
        self.assertEqual(result["phase_a_hash"], stored)
        self.assertEqual(result["title_chain"], [])


if __name__ == "__main__":
    unittest.main()
