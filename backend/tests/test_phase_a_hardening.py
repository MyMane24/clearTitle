"""Stage 2: Phase A hardening — phase_a_hash integrity and persistence."""

import unittest
from unittest.mock import patch

from backend.schemas.analysis import phase_a_hash


def _sale():
    return {"chain_position": 1, "documented_transaction": {"transaction_type": "Sale"}}


class TestPhaseAHash(unittest.TestCase):
    def _phase_a(self):
        return {
            "property_identity": {"details": [{"label": "L", "value": "V"}]},
            "title_chain": [_sale()],
            "title_chain_graph": "A -> B",
        }

    def test_stable_across_key_order_and_extra_keys(self):
        reordered = {
            "title_chain_graph": "A -> B",
            "title_chain": [_sale()],
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
            }, chain_doc_ids=[])
        sql, params = cursor.calls[-1]
        self.assertIn("phase_a_hash", sql)
        expected = phase_a_hash({
            "property_identity": {"details": []}, "title_chain": [{"chain_position": 1}],
        })
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
