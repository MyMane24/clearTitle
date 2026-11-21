"""Verification service, routes and pipeline hooks, with storage and queues mocked."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.routers import verification as routes
from backend.services.verification import case_file as cf
from backend.services.verification import report as report_module
from backend.services.verification import runner, service
from backend.services.verification.store import MemoryStore
from backend.tests.verification_fixtures import DOCUMENTS, TEXTS, new_case_file, phase_a_result


def stored_case(requisition_status=None):
    case = new_case_file()
    if requisition_status:
        case.requisitions.append(
            cf.Requisition(
                id="R1",
                document="Partition deed",
                reason="Title",
                affects=["PA-TC-0001"],
                status=requisition_status,
                doc_id="DOC_009" if requisition_status == "fulfilled" else None,
            )
        )
    return case.model_dump(mode="json"), 3


# -- service ----------------------------------------------------------------------


def test_running_run_blocks_a_new_one_but_a_stale_one_does_not():
    fresh = {"status": "running", "started_at": datetime.now()}
    stale = {"status": "running", "started_at": datetime.now() - timedelta(hours=3)}
    with patch.object(service.repo, "get_latest_run", return_value=fresh):
        assert service.is_running("C1")
        with pytest.raises(service.VerificationBusyError):
            service.start("C1")
    with patch.object(service.repo, "get_latest_run", return_value=stale):
        assert not service.is_running("C1")


def test_start_queues_the_task():
    with (
        patch.object(service.repo, "get_latest_run", return_value=None),
        patch("backend.workers.verification_tasks.run_verification_task.apply_async") as queue,
    ):
        assert service.start("C1")["status"] == "queued"
    queue.assert_called_once_with(args=["C1"], kwargs={"kind": "full", "fresh": False})


def test_start_can_request_a_fresh_run():
    with (
        patch.object(service.repo, "get_latest_run", return_value=None),
        patch("backend.workers.verification_tasks.run_verification_task.apply_async") as queue,
    ):
        assert service.start("C1", fresh=True)["fresh"] is True
    queue.assert_called_once_with(args=["C1"], kwargs={"kind": "full", "fresh": True})


def test_incremental_run_is_queued_only_for_arrived_requisition_documents():
    with (
        patch.object(service.repo, "get_case_file", return_value=stored_case("open")),
        patch.object(service, "start") as start,
    ):
        assert not service.after_documents_processed("C1")
    start.assert_not_called()
    with (
        patch.object(service.repo, "get_case_file", return_value=stored_case("fulfilled")),
        patch.object(service, "start") as start,
    ):
        assert service.after_documents_processed("C1")
    start.assert_called_once_with("C1", kind="incremental")


def test_attach_marks_the_requisition_fulfilled():
    saved = {}
    with (
        patch.object(service, "is_running", return_value=False),
        patch.object(
            service.DbStore, "load_case_file", return_value=(cf.load(stored_case("open")[0]), 3)
        ),
        patch.object(
            service.DbStore,
            "save_case_file",
            side_effect=lambda case, v: saved.update(case=case, v=v),
        ),
    ):
        service.attach_requisition_document("C1", "R1", "DOC_009", "manual_upload")
    requisition = saved["case"].requisition("R1")
    assert (requisition.status, requisition.doc_id, requisition.source) == (
        "fulfilled",
        "DOC_009",
        "manual_upload",
    )
    assert saved["v"] == 3


def test_attach_refuses_a_closed_requisition():
    with (
        patch.object(service, "is_running", return_value=False),
        patch.object(
            service.DbStore, "load_case_file", return_value=(cf.load(stored_case("resolved")[0]), 3)
        ),
        pytest.raises(service.RequisitionError),
    ):
        service.attach_requisition_document("C1", "R1", "DOC_009", "manual_upload")


def test_state_hides_examiner_report_bodies():
    case = new_case_file()
    case.documents["EC"].examined = True
    case.documents["EC"].report = cf.ExaminerReport(doc_id="EC", summary="EC 2000-2024.")
    with (
        patch.object(service.repo, "get_case_file", return_value=(case.model_dump(mode="json"), 1)),
        patch.object(service.repo, "get_latest_run", return_value=None),
        patch.object(service.repo, "get_latest_report", return_value=None),
    ):
        state = service.get_state("C1")
    entry = state["case_file"]["documents"]["EC"]
    assert "report" not in entry and entry["examined_summary"] == "EC 2000-2024."


# -- pipeline hook ------------------------------------------------------------------


def test_finalize_skips_chain_rebuild_once_verification_owns_the_chain():
    from backend.workers import finalize

    with (
        patch("backend.database.repositories.case_repo.recompute_case_status"),
        patch(
            "backend.database.repositories.document_repo.get_case_documents",
            return_value=[{"status": "structured"}],
        ),
        patch("backend.database.repositories.verification_repo.append_pipeline_log"),
        patch("backend.integrations.redis.state_store.set_case_status"),
        patch("backend.integrations.redis.lock.RedisLock"),
        patch.object(service, "owns_chain", return_value=True),
        patch.object(service, "after_documents_processed", return_value=True) as incremental,
        patch("backend.workers.title_chain_tasks.run_case_analysis_task.delay") as chain_build,
    ):
        finalize.finalize_case_task([], "C1")
    incremental.assert_called_once_with("C1")
    chain_build.assert_not_called()


# -- routes ---------------------------------------------------------------------------


def test_start_route_maps_busy_to_409():
    with (
        patch.object(routes, "_enforce_access"),
        patch.object(service, "start", side_effect=service.VerificationBusyError("busy")),
        pytest.raises(HTTPException) as raised,
    ):
        asyncio.run(routes.start_verification("C1", None))
    assert raised.value.status_code == 409


def test_events_route_passes_the_cursor():
    with (
        patch.object(routes, "_enforce_access"),
        patch.object(service, "list_events", return_value=[{"id": 8}]) as events,
    ):
        result = asyncio.run(routes.get_verification_events("C1", 7, None))
    events.assert_called_once_with("C1", 7)
    assert result["events"] == [{"id": 8}]


def test_requisition_upload_rejects_unknown_requisition():
    class Upload:
        filename = "deed.pdf"

    with (
        patch.object(routes, "_enforce_access"),
        patch.object(
            service, "get_open_requisition", side_effect=service.RequisitionError("No R9")
        ),
        pytest.raises(HTTPException) as raised,
    ):
        asyncio.run(routes.upload_for_requisition("C1", "R9", Upload(), None))
    assert raised.value.status_code == 404


# -- runner reset ----------------------------------------------------------------------


def test_chain_rebuild_resets_the_case_file_but_keeps_unchanged_examinations():
    store = MemoryStore(phase_a_result(), list(DOCUMENTS), dict(TEXTS))
    case, version, _ = runner.prepare_case_file(store, "CASE1")
    for doc_id in ("EC", "D2010"):
        entry = case.documents[doc_id]
        entry.examined, entry.text_hash = True, cf.text_hash(TEXTS[doc_id])
        entry.report = cf.ExaminerReport(doc_id=doc_id, summary="saved")
    case.leads.append(cf.Lead(id="L1", text="old lead", source="x"))
    store.save_case_file(case, version)

    store._phase_a = {**phase_a_result(), "phase_a_hash": "hash-2"}  # chain rebuilt
    store.texts["D2010"] = TEXTS["D2010"] + "\n(rescanned)"
    reset, _, _ = runner.prepare_case_file(store, "CASE1")
    assert reset.phase_a_hash == "hash-2" and reset.leads == []
    assert reset.documents["EC"].examined  # unchanged text: report kept
    assert not reset.documents["D2010"].examined  # changed text: examined again


def test_a_fresh_run_examines_every_document_again():
    store = MemoryStore(phase_a_result(), list(DOCUMENTS), dict(TEXTS))
    case, version, _ = runner.prepare_case_file(store, "CASE1")
    for doc_id in ("EC", "D2010"):
        entry = case.documents[doc_id]
        entry.examined, entry.text_hash = True, cf.text_hash(TEXTS[doc_id])
        entry.report = cf.ExaminerReport(doc_id=doc_id, summary="saved")
    store.save_case_file(case, version)

    fresh, _, _ = runner.prepare_case_file(store, "CASE1", fresh=True)
    assert not any(entry.examined for entry in fresh.documents.values())
    assert all(entry.report is None for entry in fresh.documents.values())


# -- report rules ---------------------------------------------------------------------


def test_opinion_rules_follow_the_case_file():
    case = new_case_file()
    verdict = cf.LinkVerdict(
        verdict="verified",
        summary="ok",
        checks=[cf.CheckResult(check="title", status="ok", note="ok")],
    )
    for link in case.chain:
        link.verdict = verdict
    assert report_module.opinion_problems(case, "CLEAR") == []
    case.issues.append(cf.Issue(id="I1", severity="medium", title="Tax arrears", detail="x"))
    assert "cannot be CLEAR" in report_module.opinion_problems(case, "CLEAR")[0]
    assert report_module.opinion_problems(case, "CLEAR_SUBJECT_TO") == []
    case.chain[2].continues_previous = False
    assert "must be NOT_CLEAR" in report_module.opinion_problems(case, "CLEAR_SUBJECT_TO")[0]


def test_changes_between_report_versions():
    before = {
        "opinion": "NOT_CLEAR",
        "links": {"A": {"name": "the sale of 2010", "verdict": None}},
        "issues": {},
        "requisitions": {"R1": {"document": "Partition deed of 2005", "status": "open"}},
    }
    after = {
        "opinion": "CLEAR_SUBJECT_TO",
        "links": {
            "A": {"name": "the sale of 2010", "verdict": "verified"},
            "B": {"name": "the sale of 2012", "verdict": "verified"},
        },
        "issues": {"I1": "Mortgage not released"},
        "requisitions": {"R1": {"document": "Partition deed of 2005", "status": "resolved"}},
    }
    lines = report_module.changes(before, after)
    assert lines == [
        "The opinion changed from not clear to clear subject to conditions.",
        "The sale of 2010: now verified (before: not yet judged).",
        "The sale of 2012 was added to the title chain (verified).",
        "Received and accepted: Partition deed of 2005.",
        "New issue: Mortgage not released.",
    ]
    assert "R1" not in " ".join(lines) and "I1" not in " ".join(lines)
    assert report_module.changes({}, after) == []


def test_issues_section_adds_defects_and_breaks_no_issue_covers():
    case = new_case_file()
    defective = cf.LinkVerdict(
        verdict="defective",
        summary="Sellers' title not shown.",
        checks=[cf.CheckResult(check="title", status="failed", note="x")],
    )
    case.chain[2].verdict = defective  # PA-TC-0003, 2018 sale
    case.chain[1].continues_previous = False  # break before PA-TC-0002
    case.chain[1].break_note = "No deed from Basavaraj."
    case.issues.append(
        cf.Issue(id="I1", severity="medium", title="Mortgage not released", detail="Canara Bank.")
    )
    items = report_module.case_issues(case)
    assert [item.title for item in items] == [
        "Sale of 2018 is defective",
        "Break in the title chain before the sale of 2010",
        "Mortgage not released",
    ]
    case.issues.append(
        cf.Issue(
            id="I2", severity="high", title="Bad 2018 sale", detail="x", link_ids=["PA-TC-0003"]
        )
    )
    titles = [item.title for item in report_module.case_issues(case)]
    assert "Sale of 2018 is defective" not in titles  # covered by the recorded issue
