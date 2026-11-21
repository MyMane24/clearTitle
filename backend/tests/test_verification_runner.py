"""Whole verification runs with scripted models: the PLAN.md worked example, end to end.

Full run: a partition found in the EC and a recital is added to the chain, a
missing deed becomes a requisition without stopping the run, a minor's share
becomes a high issue, the Lead cannot close while a lead is open, and the
report's opinion must agree with the Case File. Then an incremental run
examines only the uploaded document and writes report v2 with its changes.
"""

import asyncio
import re

from pydantic_ai import ModelResponse, ToolCallPart, models
from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

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


def check(name, status, citations=()):
    return {
        "check": name,
        "status": status,
        "note": f"{name}: {status}.",
        "citations": list(citations),
    }


def found(doc_id, page, quote):
    return {
        "document": "Registered instrument of this transfer",
        "proves": "The transfer itself.",
        "status": "found",
        "citations": [cite(doc_id, page, quote)],
    }


def missing(document, requisition_id):
    return {
        "document": document,
        "proves": "The transfer itself.",
        "status": "missing",
        "requisition_id": requisition_id,
    }


def verdict(link_id, kind, summary, checks, needed):
    return (
        "record_link_verdict",
        {
            "link_id": link_id,
            "verdict": kind,
            "summary": summary,
            "checks": checks,
            "property_type": "agricultural_land",
            "extent": "2 acres 10 guntas",
            "needed_documents": needed,
        },
    )


PARTITION_LINK = {
    "after_link_id": "PA-TC-0001",
    "transfer": {
        "transaction_type": "Partition",
        "executed_date": None,
        "transferors": ["Basavaraj", "Bhimappa", "Bharathi"],
        "transferees": ["Basavaraj"],
        "summary_points": ["Schedule B allotted to Basavaraj (recital in the 2010 deed)."],
        "evidence_status": "recital_reported",
        "continues_previous": True,
    },
    "reason": "The 2010 deed recites the 2005 partition, which the chain lacked.",
    "citations": [cite("D2010", 2, "under the partition of 2005")],
}

FULL_RUN_STEPS = [
    [("view_case_file", {})],
    [
        ("examine_document", {"doc_id": doc, "focus_questions": ["Parties and recitals?"]})
        for doc in ("EC", "D1998", "D2010", "D2018")
    ],
    [("open_lead", {"text": "2005 partition among Basavaraj and siblings", "source": "EC p.2"})],
    [("result", {"summary": "Trying to close early."})],  # refused: lead open, no verdicts
    [("insert_link", PARTITION_LINK)],
    [
        (
            "add_requisition",
            {
                "document": "Partition deed of 2005",
                "reason": "Shows Basavaraj was allotted the target parcel.",
                "affects": ["VL-1", "L1"],
            },
        )
    ],
    [
        (
            "resolve_lead",
            {
                "lead_id": "L1",
                "outcome": "requisition",
                "resolution": "Added to the chain; deed requested.",
                "requisition_id": "R1",
            },
        ),
        (
            "record_issue",
            {
                "severity": "high",
                "title": "Minor's share sold without court permission",
                "detail": "Bhimesh, a minor, joined the 2010 sale through his guardian.",
                "link_ids": ["PA-TC-0002"],
                "citations": [cite("D2010", 1, "Bhimesh (minor")],
            },
        ),
    ],
    # One transfer at a time, oldest first.
    [
        verdict(
            "PA-TC-0001",
            "verified",
            "Registered sale by Anand Rao.",
            [check("vendor title", "ok", [cite("D1998", 1, "Purchaser: Basavaraj")])],
            [found("D1998", 1, "Purchaser: Basavaraj")],
        )
    ],
    [
        verdict(
            "VL-1",
            "unverified_missing_document",
            "Known only from a recital.",
            [check("partition instrument", "not_verifiable")],
            [missing("Partition deed of 2005", "R1")],
        )
    ],
    [
        verdict(
            "PA-TC-0002",
            "defective",
            "Minor's share sold without court permission.",
            [check("parties and capacity", "failed", [cite("D2010", 1, "Bhimesh (minor")])],
            [found("D2010", 1, "Bhimesh (minor")],
        )
    ],
    [
        verdict(
            "PA-TC-0003",
            "verified",
            "Registered sale to Deepa.",
            [check("vendor title", "ok", [cite("D2018", 1, "Vendor: Chandrashekar")])],
            [found("D2018", 1, "Vendor: Chandrashekar")],
        )
    ],
    [("result", {"summary": "Chain verified with one defect and one requisition."})],
]


def written_report(opinion):
    return {
        "property_summary": "Sy.No.45, Hosahalli, owned by Deepa.",
        "opinion": opinion,
        "opinion_reasons": [{"text": "Minor's share sold without permission.", "refs": ["I1"]}],
        "sections": [
            {
                "id": "limitations",
                "title": "Limitations",
                "blocks": [{"type": "paragraph", "text": "Rests on these documents.", "refs": []}],
            }
        ],
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
    assert [link.link_id for link in case.chain] == [
        "PA-TC-0001",
        "VL-1",
        "PA-TC-0002",
        "PA-TC-0003",
    ]
    assert case.requisition("R1").status == "open"  # noted, run did not stop
    assert case.lead("L1").status == "resolved"

    report = store.reports[-1]
    assert report.version == 1 and report.opinion == "NOT_CLEAR"
    assert [section.id for section in report.sections] == ["issues", "requisitions", "limitations"]
    issues = report.sections[0].blocks[0].items
    assert issues[0].severity == "high"  # the minor's-share issue, most serious first

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
    assert "lead" in refused[0].lower()
    # Refusals are diagnostics (gate wording, ids included); the buyer's feed is everything else.
    feed = [text for kind, text, _ in store.events.events if kind != "rejected"]
    assert any("Found something to follow up" in line for line in feed)
    assert any("Added a transfer to the chain: the partition." in line for line in feed)
    assert any("Report v1: NOT CLEAR" in line for line in feed)
    assert not any(INTERNAL_ID.search(line) for line in feed)
    assert store.runs[outcome["run_id"]]["status"] == "done"


def test_incremental_run_examines_only_the_uploaded_document():
    store, _, _, _ = full_run()
    case, version, _ = runner.prepare_case_file(store, "CASE1")
    requisition = case.requisition("R1")
    requisition.status, requisition.doc_id = "fulfilled", "PD2005"
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
            (
                "review_requisition",
                {"requisition_id": "R1", "settled": True, "note": "Schedule B to Basavaraj."},
            ),
            (
                "correct_link",
                {
                    "link_id": "VL-1",
                    "changes": {"evidence_status": "corroborated"},
                    "reason": "The partition deed itself is now on file.",
                    "citations": [cite("PD2005", 1, "Schedule B allotted to Basavaraj")],
                },
            ),
            verdict(
                "VL-1",
                "verified",
                "Registered partition allotting Schedule B to Basavaraj.",
                [check("allotment", "ok", [cite("PD2005", 1, "Schedule B allotted")])],
                [found("PD2005", 1, "Schedule B allotted")],
            ),
        ],
        [("result", {"summary": "Partition verified."})],
    )
    report = scripted_model([("result", written_report("NOT_CLEAR"))])
    models_ = runner.Models(lead=lead, examiner=fake_examiner(seen), report=report)
    outcome = asyncio.run(runner.run("CASE1", store=store, models=models_, kind="incremental"))

    assert outcome["status"] == "done", outcome
    assert seen == ["PD2005"]  # nothing else re-examined
    v2 = store.reports[-1]
    assert v2.version == 2
    assert (
        "The partition: now verified (before: cannot be verified until a document is provided)."
        in v2.changes_since_previous
    )
    assert "Received and accepted: Partition deed of 2005." in v2.changes_since_previous
    assert not any(INTERNAL_ID.search(line) for line in v2.changes_since_previous)
    case = runner.prepare_case_file(store, "CASE1")[0]
    assert case.link("PA-TC-0002").verdict.verdict == "defective"  # kept from v1


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
