"""Final-report feature tests: readiness gating, staleness, failure paths,
lock uniqueness, download-without-regeneration, and finding consolidation."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from backend.integrations.llm.agent_llm import AgentLLMError
from backend.services import final_report as fr


def make_tx(tx_id="PA-TC-0001", seq=1, status="VERIFIED_WITH_AVAILABLE_EVIDENCE",
            docs=None, findings=None):
    return {
        "tx_id": tx_id,
        "sequence": seq,
        "status": status,
        "transaction_metadata": {"transaction_type": "Sale deed"},
        "required_documents": docs or [],
        "findings": findings or [],
        "report": "## Verification\nSale deed records check out for this link.",
        "reviewed_document_ids": ["DOC_001"],
    }


AGENT_STATE_NO_CHAIN = {"status": "done", "memory": {}, "result": {}, "case_result": []}


def agent_state_with_chain(*tx_ids):
    chain = []
    for position, tx_id in enumerate(tx_ids, start=1):
        chain.append({
            "tx_id": tx_id,
            "chain_position": position,
            "documented_transaction": {
                "transaction_type": "Sale deed",
                "executed_date": "2011-03-12",
                "vendors": [{"name": "Vendor One"}],
                "purchasers": [{"name": "Purchaser One"}],
                "property_location": "Village X",
                "survey_number": "123/1",
            },
        })
    return {
        "status": "done", "memory": {},
        "result": {
            "property_identity": {"details": [{"label": "Survey number", "value": "123/1"}]},
            "title_chain_chain": None,
            "title_chain": chain,
        },
    }


NARRATIVE = {
    "executive_summary": "The recorded chain of ownership is verifiable from the supplied documents.",
    "overall_position": "Title is verified for the available evidence with one outstanding item.",
    "consolidated_findings": [],
    "implications": ["Any unpaid mortgage would bind the property."],
    "recommended_actions": ["Obtain the encumbrance certificate for 2005-2010."],
    "scope_limitations": ["This report reflects only evidence recorded in this case."],
}


class FakeLock:
    held = True

    def __init__(self, key, ttl_ms=None):
        self.key = key

    def acquire(self):
        return FakeLock.held

    def release(self):
        pass


def patch_case(case_result, agent_state=AGENT_STATE_NO_CHAIN, **extra):
    return patch.multiple(
        fr,
        _case_result=Mock(return_value=case_result),
        get_agent_state=Mock(return_value=agent_state),
        get_case_dir=extra.get("get_case_dir", Mock(return_value=Path(".") / "outputs-unused")),
        # Stage 6 defaults: the Phase C container read and the prior report row
        # become part of the locked generation path.
        _load_findings_container=extra.get("_load_findings_container", Mock(return_value=None)),
        _load_report_row=extra.get("_load_report_row", Mock(return_value=None)),
        **{k: v for k, v in extra.items() if k not in ("get_case_dir", "_load_findings_container", "_load_report_row")},
    )


# -- 1. completed, no outstanding evidence -> allowed --------------------------


def test_all_completed_verifications_allow_generation():
    case_result = [
        make_tx("PA-TC-0001", 1, "VERIFIED_WITH_AVAILABLE_EVIDENCE"),
        make_tx("PA-TC-0002", 2, "VERIFIED_WITH_AVAILABLE_EVIDENCE"),
    ]
    with patch_case(case_result):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["ready"] is True
    assert readiness["blockers"] == []


# -- 4. findings do not block ---------------------------------------------------


def test_issues_identified_without_outstanding_evidence_is_reportable():
    finding = {"title": "Unregistered prior deed", "description": "Prior transfer never registered.",
               "affected_transactions": ["PA-TC-0001"]}
    case_result = [make_tx(findings=[finding], docs=[])]
    with patch_case(case_result):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["ready"] is True
    assert readiness["blockers"] == []


# -- 2. one transaction needs documents -> blocked with exact details -----------


def test_pending_transaction_with_requested_documents_blocks_with_details():
    blocked = make_tx(
        "PA-TC-0002", 2, status="PENDING_NOT_VERIFIED",
        docs=[{"document_type": "Encumbrance certificate", "reason": "Confirm no pending charges"},
              {"document_type": "Family settlement deed", "reason": "Trace inheritance"}],
    )
    case_result = [make_tx(), blocked]
    with patch_case(case_result):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["ready"] is False
    assert len(readiness["blockers"]) == 1
    blocker = readiness["blockers"][0]
    assert blocker["tx_id"] == "PA-TC-0002"
    assert blocker["sequence"] == 2
    assert blocker["status"] == "PENDING_NOT_VERIFIED"
    assert [req["document_type"] for req in blocker["required_documents"]] == [
        "Encumbrance certificate", "Family settlement deed"
    ]
    assert blocker["required_documents"][0]["reason"] == "Confirm no pending charges"
    assert blocker["required_documents"][0]["for_transaction"] == "PA-TC-0002"


# -- 3. multiple transactions need documents -> all reported ---------------------


def test_multiple_blocking_transactions_are_all_reported():
    first = make_tx("PA-TC-0001", 1, "VERIFIED_WITH_AVAILABLE_EVIDENCE",
                    docs=[{"document_type": "Mutation record"}])
    second = make_tx("PA-TC-0002", 2, status="PENDING",
                     docs=[{"document_type": "EC certified copy"}])
    with patch_case([first, second]):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["ready"] is False
    assert [b["tx_id"] for b in readiness["blockers"]] == ["PA-TC-0001", "PA-TC-0002"]
    assert {b["required_documents"][0]["document_type"] for b in readiness["blockers"]} == {
        "Mutation record", "EC certified copy"
    }


# -- skipped user transaction keeps required documents outstanding ---------------


def test_user_skipped_transaction_with_outstanding_evidence_still_blocks():
    # skip_transaction stores the transaction as PENDING_NOT_VERIFIED and keeps
    # the requested documents required — so it cannot be reported past.
    skipped = make_tx(
        "PA-TC-0002", 2, status="PENDING_NOT_VERIFIED",
        docs=[{"document_type": "Succession certificate", "reason": "requested documents remain required"}],
    )
    with patch_case([make_tx(), skipped]):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["ready"] is False
    assert readiness["blockers"][0]["tx_id"] == "PA-TC-0002"


# -- unverified chain transaction (no persisted result) blocks -------------------


def test_chain_transaction_without_persisted_result_blocks():
    state = agent_state_with_chain("PA-TC-0001", "PA-TC-0002")
    with patch_case([make_tx("PA-TC-0001", 1)], agent_state=state):
        readiness = fr.assess_report_readiness("CASE1")
    assert readiness["ready"] is False
    blocker = readiness["blockers"][0]
    assert blocker["tx_id"] == "PA-TC-0002"
    assert "No verification result" in blocker["note"]
    assert blocker["transaction_type"] == "Sale deed"  # from the chain entry


# -- 5. staleness ----------------------------------------------------------------


def test_state_reports_stale_only_after_case_result_changes():
    generated = [make_tx("PA-TC-0001", 1)]
    report_json = {
        "generated_at": "2026-11-01T10:00:00+00:00",
        "source_case_result_hash": fr._hash_case_result(generated),
    }
    with patch_case(generated), patch.object(
        fr, "_load_report_row", Mock(return_value=report_json)
    ):
        fresh = fr.get_report_state("CASE1")
    assert fresh["report"]["stale"] is False
    assert fresh["ready"] is True

    changed = generated + [make_tx("PA-TC-0002", 2, status="PENDING_NOT_VERIFIED")]
    with patch_case(changed), patch.object(
        fr, "_load_report_row", Mock(return_value=report_json)
    ):
        now_stale = fr.get_report_state("CASE1")
    assert now_stale["report"]["stale"] is True


# -- 7. blocked generation never touches the agent or persistence -----------------


def test_generate_returns_structured_blockers_without_generating():
    blocked = make_tx("PA-TC-0002", 2, status="PENDING_NOT_VERIFIED",
                      docs=[{"document_type": "Encumbrance certificate"}])
    persist = Mock()
    with patch_case([make_tx(), blocked]), patch.object(
        fr, "_persist_final_report", persist
    ), patch.object(fr, "complete_json", Mock(side_effect=AssertionError("must not call LLM"))), \
       patch.object(fr, "RedisLock", FakeLock):
        outcome = fr.generate_final_report("CASE1")
    assert outcome == {
        "case_id": "CASE1",
        "status": "blocked",
        "ready": False,
        "blockers": [outcome["blockers"][0]],
    }
    assert outcome["blockers"][0]["required_documents"][0]["document_type"] == "Encumbrance certificate"
    persist.assert_not_called()


# -- 6. agent failure -> no false success, nothing persisted ---------------------


def test_agent_failure_is_surfaced_and_nothing_is_persisted():
    persist = Mock()
    with patch_case([make_tx()]), patch.object(
        fr, "_persist_final_report", persist
    ), patch.object(fr, "complete_json", Mock(side_effect=AgentLLMError("provider down"))), \
       patch.object(fr, "RedisLock", FakeLock):
        with pytest.raises(AgentLLMError):
            fr.generate_final_report("CASE1")
    persist.assert_not_called()


def test_malformed_synthesis_is_surfaced_and_nothing_is_persisted():
    persist = Mock()
    with patch_case([make_tx()]), patch.object(
        fr, "_persist_final_report", persist
    ), patch.object(fr, "complete_json", Mock(return_value={"executive_summary": ""})), \
       patch.object(fr, "RedisLock", FakeLock):
        with pytest.raises(fr.ReportSynthesisError):
            fr.generate_final_report("CASE1")
    persist.assert_not_called()


# -- 7. rendering failure -> no false success -------------------------------------


def test_render_failure_persists_nothing():
    persist = Mock()
    with patch_case([make_tx()]), patch.object(
        fr, "_persist_final_report", persist
    ), patch.object(fr, "complete_json", Mock(return_value=dict(NARRATIVE))), \
       patch.object(fr, "render_final_report_pdf", Mock(side_effect=RuntimeError("font exploded"))), \
       patch.object(fr, "RedisLock", FakeLock):
        with pytest.raises(RuntimeError):
            fr.generate_final_report("CASE1")
    persist.assert_not_called()


# -- 8. persistence failure -> no false success -----------------------------------


def test_persist_failure_raises_instead_of_success(tmp_path):
    with patch_case([make_tx()], get_case_dir=Mock(return_value=tmp_path)), patch.object(
        fr, "_persist_final_report", Mock(side_effect=RuntimeError("db write refused"))
    ), patch.object(fr, "complete_json", Mock(return_value=dict(NARRATIVE))), \
       patch.object(fr, "RedisLock", FakeLock):
        with pytest.raises(RuntimeError):
            fr.generate_final_report("CASE1")


# -- successful generation persists traceable report ------------------------------


def test_successful_generation_persists_report_and_returns_metadata(tmp_path):
    persist = Mock()
    with patch_case([make_tx()], get_case_dir=Mock(return_value=tmp_path)), patch.object(
        fr, "_persist_final_report", persist
    ), patch.object(fr, "complete_json", Mock(return_value=dict(NARRATIVE))), \
       patch.object(fr, "RedisLock", FakeLock):
        outcome = fr.generate_final_report("CASE1")
    assert outcome["status"] == "generated"
    assert outcome["generated_at"]
    assert outcome["report"]["pdf_available"] is True
    pdf = tmp_path / "final_report" / "final-title-audit-report.pdf"
    assert pdf.is_file()
    document = persist.call_args[0][1]
    assert document["case_id"] == "CASE1"
    assert document["source_case_result_hash"] == fr._hash_case_result([make_tx()])
    assert document["narrative"]["executive_summary"].startswith("The recorded chain")
    assert document["transactions"][0]["status"] == "VERIFIED_WITH_AVAILABLE_EVIDENCE"
    assert "case_result" not in document  # verification text stays in case_result


# -- duplicate findings consolidated, transaction links preserved -----------------


def test_consolidation_prompt_contains_all_findings_and_links_are_preserved(tmp_path):
    shared = {"title": "Land never passes to vendor",
              "description": "The 1995 sale deed was never registered."}
    case_result = [
        make_tx("PA-TC-0001", 1, findings=[dict(shared)]),
        make_tx("PA-TC-0002", 2, findings=[dict(shared)]),
    ]
    captured = {}

    def fake_synthesis(prompt, **kwargs):
        captured["prompt"] = prompt
        assert '"PA-TC-0001"' in prompt and '"PA-TC-0002"' in prompt
        assert "1995 sale deed was never registered" in prompt
        return {
            "executive_summary": "One underlying event, reported once.",
            "consolidated_findings": [{
                "title": "Unregistered 1995 sale deed",
                "description": "The same unregistered transfer affects both links.",
                "evidence_basis": "supported_by_inspected_documents",
                "affected_transactions": ["PA-TC-0001", "PA-TC-0002"],
            }],
        }

    persist = Mock()
    with patch_case(case_result, get_case_dir=Mock(return_value=tmp_path)), patch.object(
        fr, "_persist_final_report", persist
    ), patch.object(fr, "complete_json", fake_synthesis), patch.object(fr, "RedisLock", FakeLock):
        outcome = fr.generate_final_report("CASE1")
    assert outcome["status"] == "generated"
    narrative = persist.call_args[0][1]["narrative"]
    findings = narrative["consolidated_findings"]
    assert len(findings) == 1
    assert findings[0]["affected_transactions"] == ["PA-TC-0001", "PA-TC-0002"]


# -- 9. concurrent generation -> busy, never duplicate work ------------------------


def test_concurrent_generation_returns_busy_without_generating():
    class BusyLock:
        def __init__(self, key, ttl_ms=None):
            pass

        def acquire(self):
            return False

        def release(self):
            pass

    with patch_case([make_tx()]), patch.object(
        fr, "complete_json", Mock(side_effect=AssertionError("must not call LLM"))
    ), patch.object(fr, "RedisLock", BusyLock):
        outcome = fr.generate_final_report("CASE1")
    assert outcome == {"case_id": "CASE1", "status": "busy"}


# -- 10. download serves the saved PDF without regenerating ------------------------


def test_download_serves_saved_pdf_without_regenerating(tmp_path):
    (tmp_path / "final_report").mkdir()
    (tmp_path / "final_report" / "final-title-audit-report.pdf").write_bytes(b"%PDF-1.4 stored")
    with patch_case([make_tx()], get_case_dir=Mock(return_value=tmp_path)), patch.object(
        fr, "_load_report_row", Mock(return_value={"generated_at": "x"})
    ), patch.object(fr, "complete_json", Mock(side_effect=AssertionError("must not regenerate"))):
        path = fr.stored_pdf_path("CASE1")
    assert path == tmp_path / "final_report" / "final-title-audit-report.pdf"
    assert path.read_bytes().startswith(b"%PDF-1.4")


def test_download_without_report_raises_clearly():
    with patch_case([make_tx()]):
        with patch.object(fr, "_load_report_row", Mock(return_value=None)):
            with pytest.raises(fr.FinalReportMissing):
                fr.stored_pdf_path("CASE1")


# -- missing case result is rejected ------------------------------------------------


def test_missing_case_result_is_rejected():
    with patch_case([]):
        with pytest.raises(fr.NoCaseResult):
            fr.get_report_state("CASE1")
        with pytest.raises(fr.NoCaseResult), patch.object(fr, "RedisLock", FakeLock):
            fr.generate_final_report("CASE1")
