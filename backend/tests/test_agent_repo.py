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
            {"tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED", "summary": "Old", "required_documents": []},
            {"tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED", "summary": "Duplicate old row", "required_documents": []},
            {"tx_id": "PA-TC-0002", "sequence": 2, "status": "INCONCLUSIVE", "summary": "Keep", "required_documents": []},
        ])
        connection = FakeConnection(cursor)
        update = {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
            "summary": "Updated", "required_documents": [],
        }
        with patch.object(agent_repo, "_get_conn", return_value=connection):
            agent_repo.save_transaction_result(case_id="CASE1", tx_id="PA-TC-0001", verification=update)
        saved = json.loads(cursor.calls[-1][1][1])
        self.assertEqual([item["tx_id"] for item in saved], ["PA-TC-0001", "PA-TC-0002"])
        self.assertEqual(saved[0]["summary"], "Updated")
        self.assertEqual(saved[1]["summary"], "Keep")
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
            })
        checkpoint = json.loads(cursor.calls[0][1][1])
        self.assertEqual(set(checkpoint), {
            "case_id", "current_tx_id", "current_stage", "status", "result_ref", "next_action",
        })
        self.assertNotIn("findings", checkpoint)
        self.assertNotIn("missing_documents", checkpoint)


if __name__ == "__main__":
    unittest.main()
