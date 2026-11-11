"""C5 — currentness cross-checks on the Phase C side (exposure only).
The container must expose a hashable currentness statement: any change to the
§8.2 external input groups (I0–I7, I9) moves ``input_hash`` and reconsolidates;
the I8 carry set and everything derived never participates (the unchanged
rerun stays a verbatim cache hit — pinned in test_consolidation.py). These
tests verify exposure only: whether the report consumer *compares* the hash
remains the open Phase D dependency (§1.7/§7.3 — no enforcement claim here).
"""
import unittest
from unittest.mock import patch
from backend.database.repositories import agent_repo
CASE = "CASE1"
DRAFT = {"findings": [{"members": [0], "title": "Mortgage", "description": "d"}]}
def _finding(title="Unregistered sale", finding_id="TF-001"):
    return {
        "finding_id": finding_id,
        "significance": "ESTABLISHED",
        "category": "ENCUMBRANCE",
        "title": title,
        "text": "A memorandum of deposit remains recorded.",
        "evidence": [{"doc_id": "DOC1", "pages": "2"}],
        "is_legal_defect": True,
    }
def _row(tx_id="PA-TC-0007", seq=7, findings=None, revision=1):
    return {
        "tx_id": tx_id, "sequence": seq, "revision": revision,
        "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
        "findings": findings if findings is not None else [_finding()],
    }
def _chain():
    return [{
        "tx_id": "PA-TC-0007", "chain_position": 7,
        "documented_transaction": {"sequence": 7,
                                   "documented_transferors": ["Old Owner"]},
    }]
class InputState:
    """Mutable inputs shared by the mocked repos between the two runs."""
    def __init__(self, *, results=(), chain=(), requirements=(), documents=(),
                 phase_a=None):
        self.results = list(results)
        self.chain = list(chain)
        self.requirements = list(requirements)
        self.documents = list(documents)
        self.phase_a = phase_a or {}
def _run_twice(*, state, mutate=lambda state: None):
    """Run consolidate_findings twice; mutate the inputs between the runs.
    The second run carries I8 honestly: its prior container is the first
    run's persisted output — never hashed (§8.2).
    """
    saved = []
    calls = []
    def fake_save(_case_id, container):
        saved.append(container)
    def fake_complete(*_args, **_kwargs):
        calls.append(1)
        return DRAFT
    def fake_prompt(_candidates, _reqs):
        return "PROMPT"
    def env():
        return patch.multiple(
            agent_repo,
            list_persisted_transaction_results=lambda _case: list(state.results),
            get_persisted_title_chain_entries=lambda _case: list(state.chain),
            get_agent_documents=lambda _case: list(state.documents),
            list_requirements=lambda _case, status=None: list(state.requirements),
            get_property_findings=lambda _case: (saved[-1] if saved else None),
            get_property_findings_raw=lambda _case: None,
            get_agent_result=lambda _case: state.phase_a,
            save_property_findings=fake_save,
        )
    import backend.services.consolidation as consolidation
    with env(), patch.object(consolidation, "complete_json", fake_complete), \
            patch.object(consolidation, "_build_prompt", fake_prompt):
        first = consolidation.consolidate_findings(CASE)
    mutate(state)
    with env(), patch.object(consolidation, "complete_json", fake_complete), \
            patch.object(consolidation, "_build_prompt", fake_prompt):
        second = consolidation.consolidate_findings(CASE)
    return first, second, len(calls), saved
class TestCurrentnessExposure(unittest.TestCase):
    """§8.2 I-group invalidation, matrix 27/29/30 (Phase C side)."""
    def _state(self):
        return InputState(
            results=[_row()],
            chain=_chain(),
            documents=[{"doc_id": "DOC1", "status": "processed"}],
        )
    # -- baseline: no change at all → verbatim cache replay, one model pass ---
    def test_unchanged_inputs_replay_verbatim(self):
        first, second, calls, saved = _run_twice(state=self._state())
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        # cache hit: one model pass total; the replay is not re-persisted
        self.assertEqual(calls, 1)
        self.assertEqual(len(saved), 1)
        self.assertEqual(second["container"], first["container"])
    # -- matrix 29 (I6-only): roster status change with stable doc_id ---------
    def test_roster_status_change_alone_reconsolidates(self):
        state = self._state()
        def mutate(current):
            current.documents = [{"doc_id": "DOC1", "status": "failed"}]
        first, second, calls, _saved = _run_twice(state=state, mutate=mutate)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(calls, 2)
        self.assertNotEqual(
            first["container"]["input_hash"],
            second["container"]["input_hash"])
    # -- I5-only: requirement state moves without any transaction change ------
    def test_requirement_state_change_alone_reconsolidates(self):
        state = self._state()
        state.requirements = [{
            "requirement_id": "REQ-0007", "owner_tx_id": "PA-TC-0007",
            "document_type": "EC", "reason": "confirm no charge",
        }]
        def mutate(current):
            current.requirements = [{
                "requirement_id": "REQ-0007", "owner_tx_id": "PA-TC-0007",
                "document_type": "EC", "reason": "confirm no charge",
                "status": "SATISFIED", "matched_doc_id": "DOC1",
                "match_status": "MATCHED",
            }]
        first, second, calls, _saved = _run_twice(state=state, mutate=mutate)
        self.assertEqual(calls, 2)
        self.assertNotEqual(
            first["container"]["input_hash"],
            second["container"]["input_hash"])
    # -- matrix 27/28/30 Phase C side: Phase B rerun moves the chain hash ------
    def test_phase_b_rerun_moves_phase_a_hash_and_reconsolidates(self):
        state = self._state()
        state.phase_a = {"phase_a_hash": "PHASE-A-V1"}
        def mutate(current):
            current.phase_a = {"phase_a_hash": "PHASE-A-V2"}
        first, second, calls, _saved = _run_twice(state=state, mutate=mutate)
        self.assertEqual(calls, 2)
        self.assertNotEqual(
            first["container"]["input_hash"],
            second["container"]["input_hash"])
        # exposure for the consumer: the container records exactly what moved
        self.assertEqual(
            second["container"]["result"]["coverage"]["phase_a_hash"],
            "PHASE-A-V2")
    # -- I2-only: same content, metadata-only row change -----------------------
    def test_row_revision_bump_alone_reconsolidates(self):
        state = self._state()
        def mutate(current):
            current.results = [_row(revision=2)]
        first, second, calls, _saved = _run_twice(state=state, mutate=mutate)
        self.assertEqual(calls, 2)
        self.assertNotEqual(
            first["container"]["input_hash"],
            second["container"]["input_hash"])
    # -- I3-only: content change (new finding) ---------------------------------
    def test_new_finding_content_reconsolidates(self):
        state = self._state()
        def mutate(current):
            current.results = [_row(findings=[
                _finding(), _finding("Second defect", "TF-002")])]
        first, second, calls, _saved = _run_twice(state=state, mutate=mutate)
        self.assertEqual(calls, 2)
        self.assertNotEqual(
            first["container"]["input_hash"],
            second["container"]["input_hash"])
if __name__ == "__main__":
    unittest.main()
