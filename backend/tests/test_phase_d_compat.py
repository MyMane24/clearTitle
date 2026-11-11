"""C5 — Phase C→Phase D compatibility pass (exposure only, no Phase D change).
Proves the §7.3 contract by construction against the live Phase D reader:
a fully v2-shaped container (all §4.9 fields, new statuses, engine blocks)
renders and is embedded with exactly the three flat keys Phase D consumes;
anything else v2 adds stays additive and unembedded; a container read
failure degrades to generation without the container (§7.3 fallback). The
open §1.7 gap — the report consumer does not *compare* ``input_hash`` to
enforce its own staleness — is documented, not claimed fixed.
"""
from unittest.mock import Mock, patch
from backend.services import final_report as fr
from test_final_report import FakeLock, NARRATIVE, make_tx, patch_case
INPUT_HASH = "v2-input-hash"
# -- §4.9 production-shaped v2 finding (engine output, not the flat v1 ids) --
def _v2_finding():
    return {
        "finding_id": "PF-001",
        "identity_key": "B|PARCEL-1|encumbrance|k1",
        "identity_basis": ["parcel_identifier", "defect_kind"],
        "identity_confidence": "MEDIUM",
        "identity_missing_attributes": [],
        "identity_supporting": [],
        "category": "ENCUMBRANCE",
        "title": "Undischarged mortgage on the parent parcel",
        "description": "A recorded memorandum stands undischarged.",
        "significance": "ESTABLISHED",
        "severity": "CRITICAL",
        "confidence": "HIGH",
        "is_legal_defect": True,
        "evidence_sufficiency": "PARTIAL",
        "affected_parties": ["Seller"],
        "affected_tx_ids": ["PA-TC-0001"],
        "documents": [{"doc_id": "DOC14", "pages": "2-3"}],
        "resolution_evidence": [],
        "resolution": None,
        "status": "PENDING_EVIDENCE",
        "superseede_reason": None,
        "source_observations": [{
            "finding_id": "TF-001", "tx_id": "PA-TC-0001",
            "observed_status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
        }],
        "lifecycle_events": [{
            "at": "2026-11-07T00:00:00+00:00",
            "from_status": "OPEN", "to_status": "OPEN",
            "reason": "transition_deferred", "refs": [],
            "decided_by": "app_rule:partial_run_gate",
        }],
        "correlations": [],
        "evidence_gaps": ["[REQ-0002] Encumbrance certificate"],
    }
def _v2_container():
    return {
        "container_version": "2.0",
        "input_hash": INPUT_HASH,
        "result": {
            "findings": [_v2_finding()],
            "contradictions": [],
            "unresolved_dependencies": ["REQ-0002"],
            "correlations": [{
                "from_finding_id": "PF-001", "to_finding_id": None,
                "to_requirement_id": "REQ-0002", "type": "DEPENDS_ON",
                "determined_by": "deterministic",
            }],
            "coverage": {"phase_a_hash": "PH-A", "dossiers": [],
                         "requirements": {}, "input_snapshot": {},
                         "chain_length": 1},
            "integrity": {"input_state": "READY",
                          "malformed_observations": [],
                          "excluded_evidence_refs": [],
                          "disclosures": []},
            "readiness": {"state": "COMPLETE", "pending_tx_ids": [],
                          "unverified_tx_ids": [], "skipped_tx_ids": [],
                          "open_requirement_ids": []},
        },
    }
def _generate(container, synthesis):
    persist = Mock()
    with patch_case([make_tx()], _load_findings_container=Mock(return_value=container)), \
            patch.object(fr, "_persist_final_report", persist), \
            patch.object(fr, "complete_json", Mock(return_value=dict(synthesis))), \
            patch.object(fr, "RedisLock", FakeLock):
        outcome = fr.generate_final_report("CASE1")
    assert outcome["status"] == "generated"
    return persist.call_args[0][1]
# -- the C5 claim: full v2 shape renders, embedded verbatim as 3 keys --------
def test_full_v2_container_renders_with_zero_phase_d_changes():
    document = _generate(_v2_container(), NARRATIVE)
    embedded = document["consolidated_findings_container"]
    # exactly the flat contract; nothing block-shaped leaks into the report
    assert set(embedded) == {"findings", "contradictions", "unresolved_dependencies"}
    # the typed finding survives verbatim — no re-modeling, no field stripping
    assert embedded["findings"] == [_v2_finding()]
    assert embedded["findings"][0]["identity_key"].startswith("B|")
    assert embedded["unresolved_dependencies"] == ["REQ-0002"]
def test_v2_engine_blocks_are_additive_and_unembedded():
    document = _generate(_v2_container(), NARRATIVE)
    container = document["consolidated_findings_container"]
    for block in ("correlations", "coverage", "integrity", "readiness",
                  "finding_id_index"):
        assert block not in container
    # traceability keeps the hash exposure for the future Phase D gate (§1.7)
    assert document["source_hashes"]["findings"] == INPUT_HASH
def test_new_statuses_and_provenance_reach_the_narrative_prompt():
    captured = {}
    def fake_synthesis(prompt, **_kwargs):
        captured["prompt"] = prompt
        return dict(NARRATIVE)
    with patch_case([make_tx()], _load_findings_container=Mock(return_value=_v2_container())), \
            patch.object(fr, "_persist_final_report", Mock()), \
            patch.object(fr, "complete_json", fake_synthesis), \
            patch.object(fr, "RedisLock", FakeLock):
        fr.generate_final_report("CASE1")
    prompt = captured["prompt"]
    assert "PENDING_EVIDENCE" in prompt
    assert "transition_deferred" in prompt
    assert '"identity_key"' in prompt  # typed provenance rides along intact
# -- tolerance surfaces (fallback, not enforcement) ---------------------------
def test_container_read_failure_generates_without_container():
    # exercise the REAL tolerant reader: install it, then inject the failure
    # one layer below it (the repo call it wraps)
    persist = Mock()
    with patch_case([make_tx()],
                    _load_findings_container=fr._load_findings_container), \
            patch.object(fr.agent_repo, "get_property_findings",
                         side_effect=RuntimeError("db down")), \
            patch.object(fr, "_persist_final_report", persist), \
            patch.object(fr, "complete_json", Mock(return_value=dict(NARRATIVE))), \
            patch.object(fr, "RedisLock", FakeLock):
        outcome = fr.generate_final_report("CASE1")
    assert outcome["status"] == "generated"
    document = persist.call_args[0][1]
    assert "consolidated_findings_container" not in document
    assert document["source_hashes"]["findings"] is None
def test_v1_container_missing_blocks_embeds_empty_lists():
    document = _generate(
        {"container_version": "1.0", "input_hash": "h1", "result": {}},
        NARRATIVE)
    embedded = document["consolidated_findings_container"]
    assert embedded == {
        "findings": [], "contradictions": [], "unresolved_dependencies": []}
def test_superseded_finding_with_reason_still_renders():
    container = _v2_container()
    retired = dict(_v2_finding())
    retired.update({
        "finding_id": "PF-002",
        "identity_key": "B|PARCEL-2|encumbrance|k2",
        "status": "SUPERSEDED",
        "superseede_reason": "merged_into:PF-001",
    })
    container["result"]["findings"].append(retired)
    document = _generate(container, NARRATIVE)
    embedded = document["consolidated_findings_container"]["findings"]
    assert [str(f["status"]) for f in embedded] == \
        ["PENDING_EVIDENCE", "SUPERSEDED"]
    assert embedded[1]["superseede_reason"] == "merged_into:PF-001"
# -- §1.7 closure: the currentness gate on the Phase D side ---------------------
# (changes final_report.py: get_report_state staleness now includes the
# container's input_hash movement — the DO's designated later Phase D change)
def _report_row(findings_hash):
    return {
        "generated_at": "2026-11-07T00:00:00+00:00",
        "report_type": "FINAL", "version": 1,
        "source_case_result_hash": fr._hash_case_result([make_tx()]),
        "source_hashes": {"phase_a": "PH", "findings": findings_hash},
    }
def _state(container=None, row=None):
    with patch_case([make_tx()],
                    _load_findings_container=Mock(return_value=container),
                    _load_report_row=Mock(return_value=row)):
        return fr.get_report_state("CASE1")
class TestCurrentnessStalenessGate:
    def test_current_container_matching_record_is_fresh(self):
        state = _state(_v2_container(), _report_row(INPUT_HASH))
        assert state["report"]["stale"] is False
        assert state["report"]["superseded"] is False
    def test_consolidation_after_generation_marks_the_report_stale(self):
        moved = _v2_container()
        moved["input_hash"] = "new-input-hash"
        state = _state(moved, _report_row(INPUT_HASH))
        assert state["report"]["stale"] is True
        assert state["report"]["superseded"] is True
    def test_no_container_now_is_not_findings_stale(self):
        state = _state(None, _report_row(INPUT_HASH))
        assert state["report"]["stale"] is False
    def test_report_generated_without_container_is_not_findings_stale(self):
        state = _state(_v2_container(), _report_row(None))
        assert state["report"]["stale"] is False
    def test_case_result_rerun_still_marks_stale_on_its_own(self):
        old_case = "older-case-result"
        row = _report_row(INPUT_HASH)
        row["source_case_result_hash"] = fr._hash_case_result([old_case])
        state = _state(None, row)
        assert state["report"]["stale"] is True
