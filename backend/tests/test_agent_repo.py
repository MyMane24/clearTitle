import json
import unittest
from unittest.mock import patch

from backend.database.repositories import agent_repo


class FakeCursor:
    def __init__(self, initial=None):
        self.initial = initial
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchone(self):
        return (json.dumps(self.initial),) if self.initial is not None else None


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self, **_kwargs):
        return self._cursor

    def commit(self):
        self.committed = True


class TestAgentRepository(unittest.TestCase):
    def test_upsert_validates_canonical_result_and_preserves_other_transactions(self):
        cursor = FakeCursor(initial=[
            {"tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED", "report": "Old", "required_documents": []},
            {"tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED", "report": "Duplicate old row", "required_documents": []},
            {"tx_id": "PA-TC-0002", "sequence": 2, "status": "INCONCLUSIVE", "report": "Keep", "required_documents": []},
        ])
        connection = FakeConnection(cursor)
        update = {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
            "report": "Updated", "required_documents": [],
        }
        with patch.object(agent_repo, "_get_conn", return_value=connection), \
                patch.object(agent_repo, "sync_case_requirements"):  # ledger covered elsewhere
            agent_repo.save_transaction_result(case_id="CASE1", tx_id="PA-TC-0001", verification=update)
        saved = json.loads(cursor.calls[-1][1][1])
        self.assertEqual([item["tx_id"] for item in saved], ["PA-TC-0001", "PA-TC-0002"])
        self.assertEqual(saved[0]["report"], "Updated")
        self.assertEqual(saved[1]["report"], "Keep")
        self.assertTrue(connection.committed)

    def test_result_reference_resolves_from_persisted_result_array(self):
        cursor = FakeCursor(initial=[
            {"tx_id": "PA-TC-0001", "sequence": 1, "status": "INCONCLUSIVE", "summary": "Saved"},
        ])
        with patch.object(agent_repo, "_get_conn", return_value=FakeConnection(cursor)):
            result = agent_repo.get_transaction_result("CASE1", "PA-TC-0001")
        self.assertEqual(result["summary"], "Saved")

    def test_memory_serializes_only_resume_checkpoint_fields(self):
        cursor = FakeCursor()
        with patch.object(agent_repo, "_get_conn", return_value=FakeConnection(cursor)):
            agent_repo.save_agent_memory(case_id="CASE1", memory={
                "current_tx_id": "PA-TC-0001", "stage": "paused",
                "status": "PENDING_NOT_VERIFIED", "result_ref": "PA-TC-0001",
                "next_action": "Upload evidence", "findings": ["must not be copied"],
                "missing_documents": [{"document_type": "Deed"}],
                "evidence_retry_tx_id": "PA-TC-0002",
            })
        checkpoint = json.loads(cursor.calls[0][1][1])
        self.assertEqual(set(checkpoint), {
            "case_id", "current_tx_id", "current_stage", "status", "result_ref", "next_action",
            "paused_transaction", "evidence_retry_tx_id",
        })
        self.assertEqual(checkpoint["paused_transaction"], "PA-TC-0001")
        self.assertEqual(checkpoint["evidence_retry_tx_id"], "PA-TC-0002")
        self.assertNotIn("findings", checkpoint)
        self.assertNotIn("missing_documents", checkpoint)

    def test_old_json_pause_checkpoint_recovers_paused_transaction_from_current_stage(self):
        cursor = FakeCursor(initial={
            "case_id": "CASE1", "current_tx_id": "PA-TC-0004",
            "current_stage": "paused", "status": "PENDING_NOT_VERIFIED",
        })
        with patch.object(agent_repo, "_get_conn", return_value=FakeConnection(cursor)):
            memory = agent_repo.get_agent_memory("CASE1")
        self.assertEqual(memory["paused_transaction"], "PA-TC-0004")


if __name__ == "__main__":
    unittest.main()
