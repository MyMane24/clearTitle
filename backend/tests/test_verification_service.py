"""Verification service, routes and pipeline hooks, with storage and queues mocked."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.routers import verification as routes
from backend.services.verification import case_file as cf
from backend.services.verification import report as report_module
from backend.services.verification import runner, service
from backend.services.verification.store import MemoryStore
from backend.tests.verification_fixtures import DOCUMENTS, TEXTS, new_case_file, phase_a_result


def stored_case(request_status=None):
    case = new_case_file()
    if request_status:
        case.requests.append(
            cf.Request(
                id="R1",
                document="Partition deed",
                reason="Title",
                needed_for=["PA-TC-0001"],
                status=request_status,
                doc_id="DOC_009" if request_status == "received" else None,
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


def test_incremental_run_is_queued_only_for_arrived_request_documents():
    with (
        patch.object(service.repo, "get_case_file", return_value=stored_case("open")),
        patch.object(service, "start") as start,
    ):
        assert not service.after_documents_processed("C1")
    start.assert_not_called()
    with (
        patch.object(service.repo, "get_case_file", return_value=stored_case("received")),
        patch.object(service, "start") as start,
    ):
        assert service.after_documents_processed("C1")
    start.assert_called_once_with("C1", kind="incremental")


def test_attach_marks_the_request_received():
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
    request = saved["case"].request("R1")
    assert (request.status, request.doc_id, request.source) == (
        "received",
        "DOC_009",
        "manual_upload",
    )
    assert saved["v"] == 3


def test_attach_refuses_a_settled_request():
    with (
        patch.object(service, "is_running", return_value=False),
        patch.object(
            service.DbStore, "load_case_file", return_value=(cf.load(stored_case("settled")[0]), 3)
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
    first = state["case_file"]["transfers"][0]
    assert first["result"] is None and first["before_root"] is False


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


def test_report_pdf_route_is_404_without_a_report_and_a_pdf_with_one():
    with (
        patch.object(routes, "_enforce_access"),
        patch.object(service.repo, "get_latest_report", return_value=None),
        pytest.raises(HTTPException) as raised,
    ):
        asyncio.run(routes.download_report("C1", None))
    assert raised.value.status_code == 404
    saved = {"report": {"version": 1, "opinion": "NOT_CLEAR", "reasons": ["A charge is open."]}}
    with (
        patch.object(routes, "_enforce_access"),
        patch.object(service.repo, "get_latest_report", return_value=saved),
    ):
        response = asyncio.run(routes.download_report("C1", None))
    assert response.media_type == "application/pdf" and response.body.startswith(b"%PDF")
    assert "ClearTitle-report-C1.pdf" in response.headers["content-disposition"]


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


def test_batch_upload_attaches_each_file_to_its_request():
    class Upload:
        filename = "deed.pdf"

    files = [Upload(), Upload()]
    added = {"files": [{"doc_id": "DOC_010"}, {"doc_id": "DOC_011"}]}
    with (
        patch.object(routes, "_enforce_access"),
        patch.object(service, "is_running", return_value=False),
        patch.object(service, "get_open_requisition"),
        patch("backend.routers.cases.add_uploaded_files", new=AsyncMock(return_value=added)) as add,
        patch.object(service, "attach_requisition_document") as attach,
    ):
        result = asyncio.run(routes.upload_for_requisitions("C1", files, ["R1", "R2"], None))
    add.assert_awaited_once_with("C1", files)
    assert [call.args[:3] for call in attach.call_args_list] == [
        ("C1", "R1", "DOC_010"),
        ("C1", "R2", "DOC_011"),
    ]
    assert result["requisition_ids"] == ["R1", "R2"]


def test_batch_upload_rejects_an_unknown_request_before_saving():
    class Upload:
        filename = "deed.pdf"

    with (
        patch.object(routes, "_enforce_access"),
        patch.object(service, "is_running", return_value=False),
        patch.object(
            service, "get_open_requisition", side_effect=service.RequisitionError("No R9")
        ),
        patch("backend.routers.cases.add_uploaded_files", new=AsyncMock()) as add,
        pytest.raises(HTTPException) as raised,
    ):
        asyncio.run(routes.upload_for_requisitions("C1", [Upload()], ["R9"], None))
    assert raised.value.status_code == 404
    add.assert_not_awaited()


# -- runner reset ----------------------------------------------------------------------


def test_chain_rebuild_resets_the_case_file_but_keeps_unchanged_examinations():
    store = MemoryStore(phase_a_result(), list(DOCUMENTS), dict(TEXTS))
    case, version, _ = runner.prepare_case_file(store, "CASE1")
    for doc_id in ("EC", "D2010"):
        entry = case.documents[doc_id]
        entry.examined, entry.text_hash = True, cf.text_hash(TEXTS[doc_id])
        entry.report = cf.ExaminerReport(doc_id=doc_id, summary="saved")
    case.set_aside.append(cf.SetAside(doc_id="EC", fact="F1", reason="old"))
    store.save_case_file(case, version)

    store._phase_a = {**phase_a_result(), "phase_a_hash": "hash-2"}  # chain rebuilt
    store.texts["D2010"] = TEXTS["D2010"] + "\n(rescanned)"
    reset, _, _ = runner.prepare_case_file(store, "CASE1")
    assert reset.phase_a_hash == "hash-2" and reset.set_aside == []
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


def verified(case):
    for transfer in case.transfers:
        transfer.property = cf.Property(type="agricultural_land")
        transfer.summary = "ok"
    for name in cf.SECTIONS:
        setattr(case.property_today, name, cf.Section(note="In order."))
    return case


def test_opinion_rules_follow_the_case_file():
    case = verified(new_case_file())
    assert report_module.opinion_problems(case, "CLEAR") == []
    case.property_today.tax_and_approvals.concerns = [
        cf.Concern(severity="medium", text="Tax arrears.")
    ]
    assert "cannot be CLEAR" in report_module.opinion_problems(case, "CLEAR")[0]
    assert report_module.opinion_problems(case, "CLEAR_SUBJECT_TO") == []
    case.transfers[2].connects = cf.Connection(ok=False, note="No deed from Chandrashekar.")
    assert "must be NOT_CLEAR" in report_module.opinion_problems(case, "CLEAR_SUBJECT_TO")[0]


def test_changes_between_report_versions():
    before = {
        "opinion": "NOT_CLEAR",
        "links": {"A": {"name": "the sale of 2010", "verdict": "unverified_missing_document"}},
        "issues": {"I1": "Mortgage not released"},
        "requisitions": {
            "R1": {"document": "Partition deed of 2005", "status": "open"},
            "R2": {"document": "Khata extract", "status": "open"},
        },
    }
    after = {
        "opinion": "CLEAR_SUBJECT_TO",
        "links": {
            "A": {"name": "the sale of 2010", "verdict": "verified"},
            "B": {"name": "the sale of 2012", "verdict": "verified"},
        },
        "concerns": ["Mortgage not released", "Tax arrears."],
        "requisitions": {"R1": {"document": "Partition deed of 2005", "status": "settled"}},
    }
    lines = report_module.changes(before, after)
    assert lines == [
        "The opinion changed from not clear to clear subject to conditions.",
        "The sale of 2010: now verified (before: waiting for documents).",
        "The sale of 2012 was added to the title chain (verified).",
        "Received and accepted: Partition deed of 2005.",
        "No longer needed: Khata extract.",
        "New concern: Tax arrears.",
    ]
    assert "R1" not in " ".join(lines)
    assert report_module.changes({}, after) == []
