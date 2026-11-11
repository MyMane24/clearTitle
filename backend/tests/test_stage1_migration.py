"""Stage 1: evidence-requirements ledger tests (derive/sync/save hook)."""
import unittest
from unittest.mock import MagicMock, patch
from backend.database import migrations
from backend.database.repositories import agent_repo
class FakeCursor:
    """House fake (test_agent_repo style) + scripted fetchone queue.
    ``fetch_rows`` feeds the Stage 4 lifecycle sync's existing-rows SELECT
    (single fetchall), while scripted ``fetch_results`` stay fetchone-only.
    """
    def __init__(self, initial=None, fetch_results=None, fetch_rows=None):
        self.initial = initial
        self.calls = []
        self.executemany_calls = []
        self._fetch_results = list(fetch_results or [])
        self._fetch_rows = list(fetch_rows or [])
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, rows))
        self.calls.append((sql, rows))
    def fetchone(self):
        return self._fetch_results.pop(0) if self._fetch_results else None
    def fetchall(self):
        rows, self._fetch_rows = self._fetch_rows, []
        return rows
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
# Live case 8A14D132 reference shape: 10 outstanding document asks. List order
# deliberately unsorted (tx2 before tx1, tx8 last) — derivation must sort by
# sequence, so the first four IDs belong to PA-TC-0001 regardless.
LIVE_SHAPE = [
    {"tx_id": "PA-TC-0002", "sequence": 2, "required_documents": [
        {"document_type": "Survey map R.S. 699-A/14 to 699A/15",
         "reason": "Confirm subdivision of the parent parcel"},
    ]},
    {"tx_id": "PA-TC-0001", "sequence": 1, "required_documents": [
        {"document_type": "Index II extract for 1985-1990"},
        {"document_type": "Sale deed dated 27-03-1985 (Doc No. 4966)"},
        {"document_type": "Original conveyance to first vendor"},
        {"document_type": "Property card / 7/12 extract"},
    ]},
    {"tx_id": "PA-TC-0003", "sequence": 3, "required_documents": [
        {"document_type": "BUDA/PLN/LAY/CR-20/1329/2009-10 building permission",
         "reason": "Verify sanctioned layout conversion"},
        {"document_type": "Corrected conversion order RB/LNA/SR-1/125/08-09",
         "reason": "Confirm non-agricultural conversion"},
    ]},
    {"tx_id": "PA-TC-0005", "sequence": 5, "required_documents": [
        {"document_type": "Society NOC"},
    ]},
    {"tx_id": "PA-TC-0006", "sequence": 6, "required_documents": [
        {"document_type": "Encumbrance certificate 2007-2024"},
    ]},
    {"tx_id": "PA-TC-0008", "sequence": 8, "required_documents": [
        {"document_type": "Occupancy certificate", "for_transaction": "PA-TC-0003"},
    ]},
]
class TestDeriveEvidenceRequirements(unittest.TestCase):
    def test_live_case_shape_yields_ten_deterministic_rows(self):
        rows = migrations.derive_evidence_requirements("8A14D132", LIVE_SHAPE)
        self.assertEqual(len(rows), 10)
        self.assertEqual([row[1] for row in rows], [f"REQ-{n:04d}" for n in range(1, 11)])
        self.assertEqual([row[2] for row in rows], [
            "PA-TC-0001", "PA-TC-0001", "PA-TC-0001", "PA-TC-0001",
            "PA-TC-0002", "PA-TC-0003", "PA-TC-0003", "PA-TC-0005",
            "PA-TC-0006", "PA-TC-0003",  # explicit for_transaction wins
        ])
        self.assertEqual(rows[0], ("8A14D132", "REQ-0001", "PA-TC-0001",
                                   "Index II extract for 1985-1990", None))
        self.assertEqual(rows[4], ("8A14D132", "REQ-0005", "PA-TC-0002",
                                   "Survey map R.S. 699-A/14 to 699A/15",
                                   "Confirm subdivision of the parent parcel"))
        recalled = migrations.derive_evidence_requirements("8A14D132", LIVE_SHAPE)
        self.assertEqual(rows, recalled)
    def test_dedups_casefolded_owner_type_reason(self):
        transactions = [
            {"tx_id": "PA-TC-0001", "sequence": 1, "required_documents": [
                {"document_type": "Sale Deed", "reason": "Prove transfer"},
            ]},
            {"tx_id": "PA-TC-0002", "sequence": 2, "required_documents": [
                {"document_type": "sale deed ", "reason": "  Prove Transfer"},
                {"document_type": "Sale DEED", "reason": "Prove transfer"},
                {"document_type": "Sale deed", "reason": "Different question"},
            ]},
        ]
        # Same owner + folded (type, reason) collapses; a different owner keeps
        # its own row even for an identical ask, so ownership stays unambiguous.
        rows = migrations.derive_evidence_requirements("CASE1", transactions)
        self.assertEqual([row[1] for row in rows], ["REQ-0001", "REQ-0002", "REQ-0003"])
        self.assertEqual([row[2] for row in rows],
                         ["PA-TC-0001", "PA-TC-0002", "PA-TC-0002"])
        self.assertEqual(rows[1][3], "sale deed")  # first-seen casing kept
    def test_skips_malformed_items(self):
        transactions = [
            {"tx_id": "PA-TC-0001", "sequence": 1, "required_documents": [
                "not a dict",
                {"reason": "no document_type"},
                {"document_type": "   "},
                {"document_type": "Valid document", "reason": "x"},
            ]},
            "not a transaction",
            None,
        ]
        rows = migrations.derive_evidence_requirements("CASE1", transactions)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "REQ-0001")
        self.assertEqual(rows[0][3], "Valid document")
    def test_stops_at_requirement_id_exhaustion(self):
        transactions = [{
            "tx_id": "PA-TC-0001",
            "sequence": 1,
            "required_documents": [{"document_type": f"Doc kind {n}"} for n in range(10005)],
        }]
        rows = migrations.derive_evidence_requirements("CASE1", transactions)
        self.assertEqual(len(rows), 9999)
        self.assertEqual(rows[-1][1], "REQ-9999")
    def test_empty_payload_yields_no_rows(self):
        self.assertEqual(migrations.derive_evidence_requirements("CASE1", []), ())
        self.assertEqual(migrations.derive_evidence_requirements("CASE1", None), ())
class TestSyncCaseRequirements(unittest.TestCase):
    @staticmethod
    def _existing_rows():
        """The derive rows as already-persisted OPEN ledger rows."""
        return [
            (requirement_id, owner, document_type, reason, "OPEN")
            for (_case, requirement_id, owner, document_type, reason)
            in migrations.derive_evidence_requirements("8A14D132", LIVE_SHAPE)
        ]
    def test_sync_inserts_derived_rows(self):
        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        with patch.object(agent_repo, "list_transaction_results", return_value=LIVE_SHAPE), \
                patch.object(agent_repo, "get_agent_documents", return_value=[]), \
                patch.object(agent_repo, "_get_conn", return_value=connection):
            inserted = agent_repo.sync_case_requirements("8A14D132")
        self.assertEqual(inserted, 10)
        self.assertTrue(cursor.executemany_calls)
        sql, rows = cursor.executemany_calls[0]
        self.assertIn("INSERT IGNORE INTO evidence_requirements", sql)
        self.assertEqual(rows,
                         list(migrations.derive_evidence_requirements("8A14D132", LIVE_SHAPE)))
        self.assertTrue(connection.committed)
    def test_sync_is_idempotent_when_rows_already_exist(self):
        cursor = FakeCursor(fetch_rows=self._existing_rows())
        connection = FakeConnection(cursor)
        with patch.object(agent_repo, "list_transaction_results", return_value=LIVE_SHAPE), \
                patch.object(agent_repo, "get_agent_documents", return_value=[]), \
                patch.object(agent_repo, "_get_conn", return_value=connection):
            inserted = agent_repo.sync_case_requirements("8A14D132")
        self.assertEqual(inserted, 0)
        self.assertEqual(cursor.executemany_calls, [])
    def test_sync_noop_when_no_requirements(self):
        connection = MagicMock()
        with patch.object(agent_repo, "list_transaction_results", return_value=[]), \
                patch.object(agent_repo, "_get_conn", return_value=connection) as conn:
            inserted = agent_repo.sync_case_requirements("CASE1")
        self.assertEqual(inserted, 0)
        conn.assert_not_called()
class TestSaveTransactionResultHook(unittest.TestCase):
    def _save(self, required_documents, cursor):
        verification = {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
            "report": "Report", "required_documents": required_documents,
        }
        with patch.object(agent_repo, "sync_case_requirements") as sync, \
                patch.object(agent_repo, "_get_conn", return_value=FakeConnection(cursor)):
            agent_repo.save_transaction_result(
                case_id="CASE1", tx_id="PA-TC-0001", verification=verification
            )
        return sync
    def test_hook_fires_when_result_asks_for_evidence(self):
        sync = self._save([{"document_type": "Index II extract"}], FakeCursor(initial=[]))
        sync.assert_called_once_with("CASE1")
    def test_hook_skipped_for_results_without_asks(self):
        sync = self._save([], FakeCursor(initial=[]))
        sync.assert_not_called()
if __name__ == "__main__":
    unittest.main()
