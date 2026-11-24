"""Whole verification runs with scripted models: a worked example, end to end.

Full run: a partition recited in the 2010 deed is added to the chain, each
transfer is recorded in one call, a missing deed becomes a request without
stopping the run, a minor's share is a high concern that makes its transfer
defective, the Lead cannot close early, and the report's opinion must agree with
the Case File. Then an incremental run examines only the uploaded document,
settles its request and writes report v2 with its changes.
"""

import asyncio
import re

from pydantic_ai import ModelResponse, ToolCallPart, models
from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from backend.services.verification import case_file as cf
from backend.services.verification import runner
from backend.services.verification.pages import split_pages
from backend.services.verification.store import MemoryStore
from backend.tests.verification_fixtures import (
    DOCUMENTS,
    TEXTS,
    phase_a_result,
    retry_prompts,
    scripted_model,
)

models.ALLOW_MODEL_REQUESTS = False

INTERNAL_ID = re.compile(r"\b(?:PA-TC-\d+|VL-\d+|DOC_\d+|[RLI]\d{1,3})\b")

PARTITION_TEXT = (
    "--- Page 1 ---\nPartition deed 2005 among Basavaraj, Bhimappa and Bharathi.\n"
    "Schedule B allotted to Basavaraj: Sy.No.45, 2 acres 10 guntas.\n"
)


def fake_examiner(seen):
    """Examines any document in one call: reports a quote from its first page."""

    def respond(messages, info):
        brief = next(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        doc_id = brief.split("Document: ")[1].split(" |")[0]
        seen.append(doc_id)
        first_line = split_pages(ALL_TEXTS[doc_id])[1].splitlines()[0][:30]
        report = {
            "doc_id": doc_id,
            "summary": f"Document {doc_id}.",
            "instrument": [
                {"topic": "opening", "text": first_line, "page": 1, "quote": first_line}
            ],
        }
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, report)])

    return FunctionModel(respond)


ALL_TEXTS = {**TEXTS, "PD2005": PARTITION_TEXT}


def cite(doc_id, page, quote):
    return {"doc_id": doc_id, "page": page, "quote": quote}


def found(doc_id, page, quote, name="Registered instrument of this transfer"):
    return {
        "name": name,
        "proves": "The transfer itself.",
        "status": "found",
        "citations": [cite(doc_id, page, quote)],
    }


def missing(name, request_id=None):
    item = {"name": name, "proves": "The transfer itself.", "status": "missing"}
    return {**item, "request_id": request_id} if request_id else item


LAND = {"survey": "Sy.No.45", "extent": "2 acres 10 guntas", "type": "agricultural_land"}


def transfer(transfer_id, summary, documents, concerns=(), connects=True):
    args = {
        "transfer_id": transfer_id,
        "property": LAND,
        "documents": documents,
        "summary": summary,
        "concerns": list(concerns),
    }
    if connects is not None:
        args["connects"] = {"ok": connects}
    return ("record_transfer", args)


def today(section, note, documents=()):
    return (
        "record_property_today",
        {"section": section, "note": note, "documents": list(documents)},
    )


PARTITION = {
    "after_transfer_id": "PA-TC-0001",
    "transfer": {
        "transaction_type": "Partition",
        "executed_date": None,
        "transferors": ["Basavaraj", "Bhimappa", "Bharathi"],
        "transferees": ["Basavaraj"],
        "summary_points": ["Schedule B allotted to Basavaraj (recital in the 2010 deed)."],
        "evidence_status": "recital_reported",
    },
    "reason": "The 2010 deed recites the 2005 partition, which the chain lacked.",
    "citations": [cite("D2010", 2, "under the partition of 2005")],
}
MINOR = {
    "severity": "high",
    "text": "Bhimesh, a minor, joined the 2010 sale through his guardian without court permission.",
    "citations": [cite("D2010", 1, "Bhimesh (minor")],
}

FULL_RUN_STEPS = [
    [("view_case_file", {})],
    [
        ("examine_document", {"doc_id": doc, "focus_questions": ["Parties and recitals?"]})
        for doc in ("EC", "D1998", "D2010", "D2018")
    ],
    [("result", {"summary": "Trying to close early."})],  # refused: nothing verified yet
    [("insert_transfer", PARTITION)],
    # One transfer at a time, oldest first, each in one call.
    [
        transfer(
            "PA-TC-0001",
            "Registered sale by Anand Rao.",
            [found("D1998", 1, "Purchaser: Basavaraj")],
            connects=None,
        )
    ],
    [transfer("VL-1", "Known only from a recital.", [missing("Partition deed of 2005")])],
    [
        transfer(
            "PA-TC-0002",
            "Registered sale, but a minor's share was sold without permission.",
            [found("D2010", 1, "Bhimesh (minor")],
            [MINOR],
        )
    ],
    [
        transfer(
            "PA-TC-0003", "Registered sale to Deepa.", [found("D2018", 1, "Vendor: Chandrashekar")]
        )
    ],
    [
        today(
            "encumbrances",
            "The EC to date shows no open charge after 2012.",
            [found("EC", 1, "Encumbrance Certificate", "Encumbrance certificate")],
        ),
        today("revenue_records", "No RTC was uploaded.", [missing("Current RTC extract")]),
        today("tax_and_approvals", "Agricultural land; no approvals needed."),
    ],
    [("result", {"summary": "Chain verified with one defect and two documents requested."})],
]


def written_report(opinion, documents=("EC", "D1998", "D2010", "D2018")):
    """The writer's report: one row and one paragraph per examined document."""
    return {
        "opinion": opinion,
        "reasons": ["Minor's share sold without permission."],
        "title_holders": ["Smt. Deepa"],
        "property_description": "All that piece and parcel of land bearing Sy. No. 45, Hosahalli.",
        "documents": [
            {"doc_id": doc, "date": "01.01.2010", "nature": "Registered document"}
            for doc in documents
        ],
        "document_details": [
            {"doc_id": doc, "text": f"The document at Sl. No. {n} is a registered document."}
            for n, doc in enumerate(documents, start=1)
        ],
        "history": ["Originally Shri. Anand Rao owned the land.", "Thereafter it passed to Deepa."],
        "certificate": "The title is not clear: a minor's share was sold without permission.",
    }


def full_run():
    seen = []
    store = MemoryStore(phase_a_result(), list(DOCUMENTS), dict(ALL_TEXTS))
    lead = scripted_model(*FULL_RUN_STEPS)
    report = scripted_model(
        [("result", written_report("CLEAR"))],  # refused: contradicts the Case File
        [("result", written_report("NOT_CLEAR"))],
    )
    models_ = runner.Models(lead=lead, examiner=fake_examiner(seen), report=report)
    outcome = asyncio.run(runner.run("CASE1", store=store, models=models_))
    return store, outcome, seen, (lead.last_messages, report.last_messages)


def test_full_run_closes_the_chain_and_writes_report_v1():
    store, outcome, seen, messages = full_run()
    assert outcome["status"] == "done", outcome
    assert sorted(seen) == ["D1998", "D2010", "D2018", "EC"]

    case = runner.prepare_case_file(store, "CASE1")[0]
    assert [t.id for t in case.transfers] == ["PA-TC-0001", "VL-1", "PA-TC-0002", "PA-TC-0003"]
    results = [cf.transfer_result(t) for t in case.transfers]
    assert results == ["verified", "documents_missing", "defective", "verified"]
    assert [(r.id, r.document, r.status) for r in case.requests] == [
        ("R1", "Partition deed of 2005", "open"),  # noted; the run did not stop
        ("R2", "Current RTC extract", "open"),
    ]

    report = store.reports[-1]
    assert report.version == 1 and report.opinion == "NOT_CLEAR"
    assert report.reasons == ["Minor's share sold without permission."]
    assert [d.document for d in report.documents_required] == [
        "Partition deed of 2005",
        "Current RTC extract",
    ]
    assert report.changes == []  # nothing to compare with in version 1

    lead_messages, report_messages = messages
    refused_closes = [
        part
        for message in lead_messages
        for part in message.parts
        if getattr(part, "tool_name", None) == "final_result"
        and getattr(part, "outcome", None) == "retried"
    ]
    assert len(refused_closes) == 1  # the early close was refused by the closure gate
    assert any("must be NOT_CLEAR" in p for p in retry_prompts(report_messages))  # CLEAR refused

    refused = store.events.texts("rejected")
    assert len(refused) == 1 and refused[0].startswith("Step refused (closing)")
    # Refusals are diagnostics (gate wording, ids included); the buyer's feed is everything else.
    feed = [text for kind, text, _ in store.events.events if kind != "rejected"]
    assert any("Added a transfer to the chain: the partition." in line for line in feed)
    assert "Document needed: Partition deed of 2005" in feed
    assert any("Report v1: NOT CLEAR" in line for line in feed)
    assert not any(INTERNAL_ID.search(line) for line in feed)
    assert store.runs[outcome["run_id"]]["status"] == "done"


def test_incremental_run_examines_only_the_uploaded_document():
    store, _, _, _ = full_run()
    case, version, _ = runner.prepare_case_file(store, "CASE1")
    request = case.request("R1")
    request.status, request.doc_id = "received", "PD2005"
    store.save_case_file(case, version)
    store._documents.append(
        {
            "doc_id": "PD2005",
            "filename": "partition-2005.pdf",
            "document_type": "PARTITION_DEED",
            "status": "structured",
            "summary": "Partition deed.",
        }
    )
    seen = []
    lead = scripted_model(
        [("examine_document", {"doc_id": "PD2005", "focus_questions": ["Who got Schedule B?"]})],
        [
            transfer(
                "VL-1",
                "Registered partition allotting Schedule B to Basavaraj.",
                [found("PD2005", 1, "Partition deed 2005 among", "Partition deed of 2005")],
            )
        ],
        [("result", {"summary": "Partition verified."})],
    )
    every = ("EC", "D1998", "D2010", "D2018", "PD2005")
    report = scripted_model([("result", written_report("NOT_CLEAR", every))])
    models_ = runner.Models(lead=lead, examiner=fake_examiner(seen), report=report)
    outcome = asyncio.run(runner.run("CASE1", store=store, models=models_, kind="incremental"))

    assert outcome["status"] == "done", outcome
    assert seen == ["PD2005"]  # nothing else re-examined
    v2 = store.reports[-1]
    assert v2.version == 2
    assert "The partition: now verified (before: waiting for documents)." in v2.changes
    assert "Received and accepted: Partition deed of 2005." in v2.changes
    assert not any(INTERNAL_ID.search(line) for line in v2.changes)
    case = runner.prepare_case_file(store, "CASE1")[0]
    assert case.request("R1").status == "settled"
    assert cf.transfer_result(case.transfer("PA-TC-0002")) == "defective"  # kept from v1


def test_crashed_run_resumes_from_the_case_file():
    seen = []
    store = MemoryStore(phase_a_result(), list(DOCUMENTS), dict(ALL_TEXTS))

    def crash(messages, info):
        raise RuntimeError("worker died")

    lead = scripted_model(FULL_RUN_STEPS[1], crash)
    models_ = runner.Models(lead=lead, examiner=fake_examiner(seen), report=None)
    outcome = asyncio.run(runner.run("CASE1", store=store, models=models_))
    assert outcome["status"] == "error"
    assert len(seen) == 4

    resumed = scripted_model(FULL_RUN_STEPS[1], [("result", {"summary": "x"})])
    models_ = runner.Models(lead=resumed, examiner=fake_examiner(seen), report=None)
    asyncio.run(runner.run("CASE1", store=store, models=models_))
    assert len(seen) == 4  # saved examiner reports were reused, not re-read
    returns = [
        part.content
        for message in resumed.last_messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "examine_document"
    ]
    assert returns and all(str(content).startswith("Already examined") for content in returns)


def test_budget_exhaustion_is_incomplete_not_success(monkeypatch):
    monkeypatch.setattr(runner, "VERIFY_LEAD_CALL_BUDGET", 2)
    store = MemoryStore(phase_a_result(), list(DOCUMENTS), dict(ALL_TEXTS))
    lead = scripted_model(*[[("view_case_file", {})]] * 5)
    models_ = runner.Models(lead=lead, examiner=None, report=None)
    outcome = asyncio.run(runner.run("CASE1", store=store, models=models_))
    assert outcome["status"] == "incomplete"
    assert store.reports == []
    assert any("budget was reached" in line for line in store.events.texts())


def test_no_title_chain_means_no_run():
    store = MemoryStore(None, list(DOCUMENTS), {})
    outcome = asyncio.run(runner.run("CASE1", store=store, models=None))
    assert outcome["status"] == "error" and "title chain" in outcome["reason"]


def test_cost_cap_stops_the_run_as_incomplete(monkeypatch):
    monkeypatch.setattr(runner, "VERIFY_RUN_COST_LIMIT_USD", 0.05)
    monkeypatch.setattr(runner, "estimate_cost", lambda usage, model: 0.03)  # 0.06 > 0.05
    store = MemoryStore(phase_a_result(), list(DOCUMENTS), dict(ALL_TEXTS))
    lead = scripted_model(*[[("view_case_file", {})]] * 5)
    models_ = runner.Models(lead=lead, examiner=None, report=None)
    outcome = asyncio.run(runner.run("CASE1", store=store, models=models_))
    assert outcome["status"] == "incomplete" and "cap" in outcome["error"]
    assert store.reports == []
    assert store.case_file is not None  # progress saved
