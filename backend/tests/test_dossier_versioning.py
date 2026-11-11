"""Stage 3: dossier versioning — revisions, history, dossier dimensions, scope."""
import json
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from backend.database.repositories import agent_repo
from backend.schemas.analysis import content_hash
from backend.services.agent_schemas import (
    normalize_transaction_verification,
    TransactionVerification,
)
def _verification(tx_id="PA-TC-0001", status="VERIFIED_WITH_AVAILABLE_EVIDENCE",
                  report="Verdict: valid.", extra=None):
    payload = {
        "tx_id": tx_id,
        "sequence": int(str(tx_id).removeprefix("PA-TC-")) if tx_id.startswith("PA-TC-") else 1,
        "status": status,
        "report": report,
    }
    if extra:
        payload.update(extra)
    return payload
class FakeCursor:
    def __init__(self, case_result=None, dossier_meta=None):
        self.case_result = case_result
        self.dossier_meta = dossier_meta
        self.calls = []
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
    def fetchone(self):
        if self.case_result is None:
            return None
        return (json.dumps(self.case_result), json.dumps(self.dossier_meta or {}))
class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def cursor(self, **_kwargs):
        return self._cursor
    def commit(self):
        pass
class TestDossierDimensions(unittest.TestCase):
    def test_defaults_on_minimal_payload(self):
        model = TransactionVerification(**_verification())
        self.assertEqual(model.effectivity_status.value, "NOT_EXAMINED")
        self.assertEqual(model.evidence_status.value, "UNDETERMINED")
        self.assertEqual(model.revision, 1)
        self.assertIsNone(model.scope.phase_a_hash)
        self.assertEqual(model.findings, [])
    def test_invalid_dimension_values_are_rejected(self):
        with self.assertRaises(ValidationError):
            TransactionVerification(**_verification(extra={"effectivity_status": "MOSTLY_EXAMINED"}))
        with self.assertRaises(ValidationError):
            TransactionVerification(**_verification(extra={"evidence_status": "RECITALL"}))
    def test_findings_are_validated_through_the_canonical_contract(self):
        with self.assertRaises(ValidationError):
            # ESTABLISHED without evidence fails the canonical finding gate.
            TransactionVerification(**_verification(extra={
                "findings": [{"significance": "ESTABLISHED", "title": "t", "text": "b"}],
            }))
        ok = TransactionVerification(**_verification(extra={
            "findings": [{
                "significance": "ESTABLISHED", "title": "Undischarged mortgage",
                "text": "Memorandum of deposit remains recorded.",
                "evidence": [{"doc_id": "DOC1", "pages": "2-3"}],
            }],
        }))
        self.assertEqual(ok.findings[0].significance.value, "ESTABLISHED")
    def test_revision_must_be_positive(self):
        with self.assertRaises(ValidationError):
            TransactionVerification(**_verification(extra={"revision": 0}))
class TestRevisionPersistence(unittest.TestCase):
    def _save(self, cursor, verification, tx_id="PA-TC-0001"):
        with patch.object(agent_repo, "_get_conn", return_value=FakeConnection(cursor)):
            agent_repo.save_transaction_result(case_id="CASE1", tx_id=tx_id, verification=verification)
    def _last_write(self, cursor):
        sql, params = cursor.calls[-1]
        self.assertIn("dossier_meta", sql)
        return json.loads(params[1]), json.loads(params[2])
    def test_first_save_assigns_revision_one_and_creates_meta(self):
        cursor = FakeCursor(case_result=[])
        self._save(cursor, _verification())
        saved, meta = self._last_write(cursor)
        self.assertEqual(saved[0]["revision"], 1)
        self.assertEqual(meta["PA-TC-0001"], {"revision": 1, "history": []})
    def test_resave_appends_prior_snapshot_and_increments_revision(self):
        cursor = FakeCursor(
            case_result=[_verification()],
            dossier_meta={"PA-TC-0001": {"revision": 1, "history": []}},
        )
        self._save(cursor, _verification(report="Verdict: revised after new evidence."))
        saved, meta = self._last_write(cursor)
        self.assertEqual(saved[0]["revision"], 2)
        self.assertEqual(saved[0]["report"], "Verdict: revised after new evidence.")
        history = meta["PA-TC-0001"]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["report"], "Verdict: valid.")
        self.assertEqual(history[0]["revision"], 1)
        self.assertTrue(history[0]["superseded_at"])
    def test_history_is_append_only_and_uncapped(self):
        cursor = FakeCursor(
            case_result=[{**_verification(), "revision": 2, "report": "Verdict: v2."}],
            dossier_meta={"PA-TC-0001": {
                "revision": 2,
                "history": [{"revision": 1, "report": "Verdict: valid.", "superseded_at": "t1"}],
            }},
        )
        self._save(cursor, _verification(report="Verdict: v3."))
        saved, meta = self._last_write(cursor)
        self.assertEqual(saved[0]["revision"], 3)
        tx_meta = meta["PA-TC-0001"]
        self.assertEqual([item["revision"] for item in tx_meta["history"]], [1, 2])
        self.assertEqual(tx_meta["history"][-1]["report"], "Verdict: v2.")
    def test_pre_stage3_entry_without_revision_gets_coherent_numbering(self):
        cursor = FakeCursor(case_result=[_verification()])  # persisted before revisions existed
        self._save(cursor, _verification(report="Verdict: reposted."))
        saved, meta = self._last_write(cursor)
        self.assertEqual(saved[0]["revision"], 2)
        self.assertEqual(meta["PA-TC-0001"]["history"][0]["revision"], 1)
class TestScopeStamping(unittest.TestCase):
    def _ctx(self, tx_id="PA-TC-0001", phase_a_hash=None):
        from backend.services.agent_tools import ToolContext
        entries = []
        if tx_id == "PA-TC-0002":
            entries = [
                {"tx_id": "PA-TC-0001", "chain_position": 1,
                 "documented_transaction": {"transaction_type": "Sale"}},
                {"tx_id": "PA-TC-0002", "chain_position": 2,
                 "documented_transaction": {"transaction_type": "Gift"}},
            ]
        else:
            entries = [{"tx_id": "PA-TC-0001", "chain_position": 1,
                        "documented_transaction": {"transaction_type": "Sale"}}]
        with patch("backend.services.agent_tools.repo.get_transaction_result", return_value={}):
            return ToolContext(
                "CASE1", [], current_tx_id=tx_id, phase_a_chain=entries,
                phase_a_hash=phase_a_hash,
            )
    def test_scope_is_stamped_from_application_values(self):
        from backend.services.agent_tools import _canonical_verification
        ctx = self._ctx(phase_a_hash="abc123")
        payload = _canonical_verification(ctx, dict(
            _verification(status="PENDING_NOT_VERIFIED"),
            report="Waiting for the outstanding deed.",
        ))
        self.assertEqual(payload["scope"]["phase_a_hash"], "abc123")
        self.assertIsNone(payload["scope"]["chain_context_hash"])  # root transaction
    def test_chain_context_hash_covers_the_persisted_context(self):
        from backend.services.agent_tools import _canonical_verification
        chain_context = {"upstream_unverified": True, "unverified": ["PA-TC-0001"]}
        ctx = self._ctx(tx_id="PA-TC-0002", phase_a_hash="abc123")
        with patch("backend.services.agent_tools._upstream_chain_context",
                   return_value=chain_context):
            payload = _canonical_verification(ctx, dict(
                _verification(tx_id="PA-TC-0002", status="INCONCLUSIVE"),
                report="The attempt cannot support a reliable conclusion.\n\n## Earlier transactions\n"
                       "The 1985 sale has not been verified yet.",
            ))
        self.assertEqual(payload["scope"]["phase_a_hash"], "abc123")
        self.assertEqual(payload["scope"]["chain_context_hash"], content_hash(chain_context))
    def test_model_supplied_scope_is_always_overwritten(self):
        from backend.services.agent_tools import _canonical_verification
        ctx = self._ctx(phase_a_hash="app-hash")
        payload = _canonical_verification(ctx, dict(
            _verification(status="PENDING_NOT_VERIFIED"),
            report="Waiting for the outstanding deed.",
            scope={"phase_a_hash": "MODEL_INVENTED", "extra": "junk"},
        ))
        self.assertEqual(payload["scope"]["phase_a_hash"], "app-hash")
        self.assertNotIn("extra", payload["scope"])
class TestLegacyNormalizationPassThrough(unittest.TestCase):
    def test_v30_rows_keep_dossier_fields_through_the_read_adapter(self):
        saved = {
            **_verification(),
            "schema_version": "3.0",
            "effectivity_status": "FULLY_EXAMINED",
            "evidence_status": "DIRECT",
            "scope": {"phase_a_hash": "h", "chain_context_hash": "c"},
            "findings": [{"significance": "SUPPORTED", "title": "t", "text": "b",
                          "evidence": [{"doc_id": "DOC1"}]}],
        }
        normalized = normalize_transaction_verification(saved)
        self.assertEqual(normalized["effectivity_status"], "FULLY_EXAMINED")
        self.assertEqual(normalized["evidence_status"], "DIRECT")
        self.assertEqual(normalized["scope"], {"phase_a_hash": "h", "chain_context_hash": "c"})
        self.assertEqual(normalized["findings"][0]["title"], "t")
    def test_pre_v30_rows_receive_dimension_defaults(self):
        legacy = {
            "tx_id": "PA-TC-0003", "sequence": 3, "status": "ISSUES_IDENTIFIED",
            "report": "Old stored report (schema 2-era).", "cited_documents": [{"doc_id": "DOC9"}],
        }
        normalized = normalize_transaction_verification(legacy)
        self.assertEqual(normalized["effectivity_status"], "NOT_EXAMINED")
        self.assertEqual(normalized["evidence_status"], "UNDETERMINED")
        self.assertEqual(normalized["revision"], 1)
if __name__ == "__main__":
    unittest.main()
