"""Stage 6: final report v2 — FINAL/PRELIMINARY/SUPERSEDED semantics, source
hashes, M4 history, Phase C consumption."""
from unittest.mock import MagicMock, Mock, patch
import pytest
from backend.services import final_report as fr
from test_final_report import NARRATIVE, FakeLock, make_tx, patch_case
# -- FINAL gate --------------------------------------------------------------------
def test_final_requires_terminal_links_even_without_requested_documents():
    pending = make_tx("PA-TC-0002", 2, status="PENDING_NOT_VERIFIED", docs=[])
    with patch_case([make_tx(), pending]):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["final_ready"] is False
    blocked = [b for b in readiness["blockers"] if b["tx_id"] == "PA-TC-0002"]
    assert blocked and blocked[0]["required_documents"] == []
def test_final_blocked_by_user_skipped_pending_link():
    pending = make_tx("PA-TC-0002", 2, status="PENDING_NOT_VERIFIED", docs=[])
    state = {"status": "done", "memory": {"skipped_tx_ids": ["PA-TC-0002"]}, "result": {}}
    with patch_case([make_tx(), pending], agent_state=state):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["skipped_tx_ids"] == ["PA-TC-0002"]
    blocker = next(b for b in readiness["blockers"] if b["tx_id"] == "PA-TC-0002")
    assert blocker["skipped"] is True
    assert readiness["final_ready"] is False
def test_freshly_verified_link_supersedes_its_skip_marker():
    state = {"status": "done", "memory": {"skipped_tx_ids": ["PA-TC-0001"]}, "result": {}}
    with patch_case([make_tx()], agent_state=state):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["final_ready"] is True
    assert readiness["skipped_tx_ids"] == []
def test_unverified_chain_transaction_blocks_final_with_labeled_outcome():
    from test_final_report import agent_state_with_chain
    state = agent_state_with_chain("PA-TC-0001", "PA-TC-0002")
    with patch_case([make_tx("PA-TC-0001", 1)], agent_state=state):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["unverified_tx_ids"] == ["PA-TC-0002"]
def test_final_blocked_outcome_covers_final_gate_and_ready_blockers():
    pending_docs = make_tx("PA-TC-0002", 2, status="PENDING_NOT_VERIFIED",
                           docs=[{"document_type": "EC"}])
    pending_silent = make_tx("PA-TC-0003", 3, status="PENDING_NOT_VERIFIED", docs=[])
    persist = Mock()
    with patch_case([make_tx(), pending_docs, pending_silent]), \
        patch.object(fr, "_persist_final_report", persist), \
        patch.object(fr, "complete_json", Mock(side_effect=AssertionError("must not run"))), \
        patch.object(fr, "RedisLock", FakeLock):
        outcome = fr.generate_final_report("CASE1")
    assert outcome["status"] == "blocked"
    assert {b["tx_id"] for b in outcome["blockers"]} == {"PA-TC-0002", "PA-TC-0003"}
    persist.assert_not_called()
# -- PRELIMINARY ---------------------------------------------------------------------
def test_preliminary_generates_from_blocked_case_and_discloses_outstanding(tmp_path):
    pending = make_tx("PA-TC-0002", 2, status="PENDING_NOT_VERIFIED",
                      docs=[{"document_type": "Encumbrance certificate"}])
    state = {"status": "done", "memory": {"skipped_tx_ids": ["PA-TC-0002"]}, "result": {}}
    open_rows = [{
        "requirement_id": "REQ-0001", "owner_tx_id": "PA-TC-0002",
        "document_type": "Encumbrance certificate", "match_status": None,
    }]
    persist = Mock()
    with patch_case(
        [make_tx(), pending],
        agent_state=state,
        get_case_dir=Mock(return_value=tmp_path),
        _open_requirements=Mock(return_value=open_rows),
    ), patch.object(fr, "_persist_final_report", persist), \
        patch.object(fr, "complete_json", Mock(return_value=dict(NARRATIVE))), \
        patch.object(fr, "RedisLock", FakeLock):
        outcome = fr.generate_final_report("CASE1", report_type="PRELIMINARY")
    assert outcome["status"] == "generated"
    assert outcome["report_type"] == "PRELIMINARY"
    document = persist.call_args[0][1]
    assert document["report_type"] == "PRELIMINARY"
    outstanding = document["outstanding"]
    assert outstanding["requirement_ids"] == ["REQ-0001"]
    assert outstanding["skipped_tx_ids"] == ["PA-TC-0002"]
    entry = next(e for e in outstanding["pending"] if e["tx_id"] == "PA-TC-0002")
    assert entry["requirement_ids"] == ["REQ-0001"]
    assert entry["skipped"] is True
    assert document["narrative"]["executive_summary"].startswith("The recorded chain")
def test_preliminary_available_even_when_ready():
    from backend.schemas.analysis import OpinionType
    persist = Mock()
    with patch_case([make_tx()]), patch.object(fr, "_persist_final_report", persist), \
        patch.object(fr, "complete_json", Mock(return_value=dict(NARRATIVE))), \
        patch.object(fr, "RedisLock", FakeLock):
        outcome = fr.generate_final_report("CASE1", report_type=OpinionType.PRELIMINARY.value)
    assert outcome["status"] == "generated"
    assert outcome["report_type"] == "PRELIMINARY"
def test_unsupported_report_type_is_refused_without_lock():
    with patch_case([make_tx()]), patch.object(
        fr, "RedisLock", Mock(side_effect=AssertionError("unsupported type must fail fast"))
    ):
        with pytest.raises(ValueError, match="unsupported report type"):
            fr._generate_locked("CASE1", "DRAFT")
# -- versioning + M4 history + traceability ------------------------------------------
def test_versions_increment_across_generations():
    persist = Mock()
    prior_rows = [None, {"version": 1, "report_type": "FINAL"}]
    with patch_case([make_tx()], _load_report_row=Mock(side_effect=lambda case_id: prior_rows.pop(0))), \
        patch.object(fr, "_persist_final_report", persist), \
        patch.object(fr, "complete_json", Mock(return_value=dict(NARRATIVE))), \
        patch.object(fr, "RedisLock", FakeLock):
        first = fr.generate_final_report("CASE1")
        second = fr.generate_final_report("CASE1", report_type="PRELIMINARY")
    assert first["version"] == 1 and second["version"] == 2
def test_persist_appends_history_and_marks_previous_entries_superseded():
    prior_history = [{
        "version": 1, "report_type": "FINAL", "generated_at": "T1",
        "source_case_result_hash": "h1", "superseded": False,
    }]
    document = {
        "version": 2, "report_type": "PRELIMINARY", "generated_at": "T2",
        "source_case_result_hash": "h2",
    }
    with patch.object(fr, "_get_conn", Mock(return_value=MagicMock())), \
        patch.object(fr.agent_repo, "get_final_reports", return_value=prior_history), \
        patch.object(fr.agent_repo, "replace_final_reports") as replace:
        fr._persist_final_report("CASE1", document)
    history = replace.call_args[0][1]
    assert history[0]["superseded"] is True
    assert history[0]["superseded_at"] == "T2"
    assert history[-1] == {
        "version": 2, "report_type": "PRELIMINARY", "generated_at": "T2",
        "source_case_result_hash": "h2", "superseded": False,
    }
def test_document_carries_source_hashes_and_metadata():
    persist = Mock()
    with patch_case([make_tx()]), patch.object(fr, "_persist_final_report", persist), \
        patch.object(fr, "complete_json", Mock(return_value=dict(NARRATIVE))), \
        patch.object(fr, "RedisLock", FakeLock):
        fr.generate_final_report("CASE1")
    document = persist.call_args[0][1]
    assert document["schema_version"] == "1.1"
    assert document["report_type"] == "FINAL"
    assert document["version"] == 1
    assert document["superseded"] is False
    assert set(document["source_hashes"]) == {"phase_a", "findings"}
    assert document["source_hashes"]["findings"] is None  # no Phase C container
    assert document["source_case_result_hash"] == fr._hash_case_result([make_tx()])
def test_container_input_hash_is_recorded_when_phase_c_ran():
    container = {"container_version": "1.0", "input_hash": "pf-hash", "result": {"findings": []}}
    persist = Mock()
    with patch_case([make_tx()], _load_findings_container=Mock(return_value=container)), \
        patch.object(fr, "_persist_final_report", persist), \
        patch.object(fr, "complete_json", Mock(return_value=dict(NARRATIVE))), \
        patch.object(fr, "RedisLock", FakeLock):
        fr.generate_final_report("CASE1")
    document = persist.call_args[0][1]
    assert document["source_hashes"]["findings"] == "pf-hash"
# -- Phase C consumption ----------------------------------------------------------------
def test_synthesis_prompt_carries_typed_container_and_narrative_links_ids():
    container = {
        "container_version": "1.0", "input_hash": "pf-hash",
        "result": {
            "findings": [{
                "finding_id": "PF-001", "category": "ENCUMBRANCE",
                "title": "Undischarged mortgage on the parent parcel",
                "description": "A recorded memorandum stands undischarged.",
                "severity": "CRITICAL", "confidence": "HIGH",
                "affected_tx_ids": ["PA-TC-0007"],
                "documents": [{"doc_id": "DOC14", "pages": "2-3"}],
            }],
            "contradictions": [], "unresolved_dependencies": ["REQ-0002"],
        },
    }
    captured = {}
    def fake_synthesis(prompt, **kwargs):
        captured["prompt"] = prompt
        assert "consolidated_findings_container" in prompt
        assert "PF-001" in prompt and "Undischarged mortgage on the parent parcel" in prompt
        return {
            "executive_summary": "One typed finding, referenced by ID.",
            "consolidated_findings": [{
                "finding_id": "PF-001",
                "title": "Undischarged mortgage on the parent parcel",
                "description": "The recorded memoranda stays undischarged.",
                "evidence_basis": "supported_by_inspected_documents",
                "affected_transactions": ["PA-TC-0007"],
            }],
        }
    persist = Mock()
    with patch_case([make_tx()], _load_findings_container=Mock(return_value=container)), \
        patch.object(fr, "_persist_final_report", persist), \
        patch.object(fr, "complete_json", fake_synthesis), \
        patch.object(fr, "RedisLock", FakeLock):
        outcome = fr.generate_final_report("CASE1")
    assert outcome["status"] == "generated"
    narrative = persist.call_args[0][1]["narrative"]["consolidated_findings"]
    assert narrative[0]["finding_id"] == "PF-001"
def test_invalid_finding_ids_stripped_from_persisted_document(tmp_path):
    content = dict(NARRATIVE)
    content["consolidated_findings"] = [{
        "title": "Lands", "description": "d", "finding_id": "PF-9XX9",
    }]
    persist = Mock()
    with patch_case([make_tx()], get_case_dir=Mock(return_value=tmp_path)), \
        patch.object(fr, "_persist_final_report", persist), \
        patch.object(fr, "complete_json", Mock(return_value=content)), \
        patch.object(fr, "RedisLock", FakeLock):
        fr.generate_final_report("CASE1")
    findings = persist.call_args[0][1]["narrative"]["consolidated_findings"]
    assert findings[0].get("finding_id") is None  # invalid reference dropped, finding kept
# -- SUPERSEDED -------------------------------------------------------------------------
def test_state_marks_report_superseded_when_inputs_change():
    generated = [make_tx("PA-TC-0001", 1)]
    report_json = {
        "generated_at": "2026-11-01T10:00:00+00:00",
        "report_type": "FINAL",
        "version": 1,
        "source_case_result_hash": fr._hash_case_result(generated),
    }
    with patch_case(generated), patch.object(
        fr, "_load_report_row", Mock(return_value=report_json)
    ):
        fresh = fr.get_report_state("CASE1")
    assert fresh["report"]["superseded"] is False
    assert fresh["report"]["report_type"] == "FINAL"
    assert fresh["report"]["version"] == 1
    changed = generated + [make_tx("PA-TC-0002", 2, status="PENDING_NOT_VERIFIED")]
    with patch_case(changed), patch.object(
        fr, "_load_report_row", Mock(return_value=report_json)
    ):
        superseded = fr.get_report_state("CASE1")
    assert superseded["report"]["superseded"] is True
# -- PDF ----------------------------------------------------------------------------------
def test_preliminary_pdf_renders_with_banner_and_outstanding_section():
    outstanding = {
        "requirement_ids": ["REQ-0001"],
        "skipped_tx_ids": ["PA-TC-0002"],
        "unverified_tx_ids": ["PA-TC-0009"],
        "pending": [{
            "tx_id": "PA-TC-0002", "transaction_type": "Sale deed",
            "status": "PENDING_NOT_VERIFIED", "skipped": True,
            "required_documents": [{"document_type": "Encumbrance certificate"}],
            "requirement_ids": ["REQ-0001"],
        }],
    }
    document = {
        "case_id": "CASE1", "report_type": "PRELIMINARY", "version": 2,
        "generated_at": "2026-11-05T00:00:00+00:00",
        "property_identity": ["Survey number: 123/1"],
        "ownership_history": [], "transactions": [{
            "sequence": 1, "transaction_type": "Sale deed",
            "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
            "reviewed_documents": 1, "required_documents": 0,
        }],
        "narrative": dict(NARRATIVE), "outstanding": outstanding,
    }
    pdf = fr.render_final_report_pdf(document)
    assert pdf.startswith(b"%PDF")
