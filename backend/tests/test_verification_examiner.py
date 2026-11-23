"""The Document Examiner: one call with the full text, real quotes only, cached report."""

import asyncio
from types import SimpleNamespace

from pydantic_ai import models

from backend.services.verification import case_file as cf
from backend.services.verification import examiner
from backend.services.verification.deps import VerifyDeps
from backend.services.verification.events import ListSink
from backend.tests.verification_fixtures import TEXTS, new_case_file, scripted_model

models.ALLOW_MODEL_REQUESTS = False


def report(quote="partition of 2005", page=2, **extra):
    return {
        "doc_id": "WRONG-ID",
        "summary": "Sale deed of 2010 from Basavaraj and minor Bhimesh to Chandrashekar.",
        "parties": [
            {
                "name": "Bhimesh",
                "role": "vendor",
                "capacity": "guardian_of_minor",
                "represented_by": "Basavaraj",
                "page": 1,
                "quote": "Bhimesh (minor",
            }
        ],
        "recitals": [
            {"topic": "acquisition", "text": "2005 partition", "page": page, "quote": quote}
        ],
        "unexpected": [
            {"topic": "minor", "text": "A minor's share is sold.", "page": 1, "quote": "minor"}
        ],
        **extra,
    }


def make_ctx(model):
    sink = ListSink()
    deps = VerifyDeps(
        case=new_case_file(), text_of=lambda doc_id: TEXTS[doc_id], emit=sink, examiner_model=model
    )
    return SimpleNamespace(deps=deps), sink


def examine(ctx, doc_id="D2010"):
    return asyncio.run(examiner.examine_document(ctx, doc_id, ["Who were the vendors?"]))


def test_one_call_with_the_full_text_returns_a_cited_report():
    model = scripted_model([("result", report())])  # a second call would fail: none scripted
    ctx, sink = make_ctx(model)
    text = examine(ctx)
    prompt = str(model.last_messages[0].parts[-1].content)
    assert "THE WHOLE DOCUMENT FOLLOWS" in prompt
    assert "--- Page 1 ---" in prompt and "--- Page 2 ---" in prompt
    entry = ctx.deps.case.documents["D2010"]
    assert entry.examined and entry.report.doc_id == "D2010"  # id comes from the app
    assert "RECITALS" in text and "2005 partition [F2 p.2]" in text and "UNEXPECTED" in text
    assert "partition of 2005" not in text  # long OCR quotes stay out of the Lead's context
    assert entry.text_hash
    assert any("Examined deed-2010.pdf" in line for line in sink.texts("examine"))


def test_facts_with_quotes_not_in_the_text_are_dropped_without_another_call():
    bad = report(quote="court permission obtained")
    bad["unexpected"][0]["quote"] = "invented text"
    model = scripted_model([("result", bad)])
    ctx, _ = make_ctx(model)
    examine(ctx)
    saved = ctx.deps.case.documents["D2010"].report
    assert saved.recitals == [] and saved.unexpected == []
    assert len(saved.parties) == 1  # the real quote is kept
    assert "2 facts dropped" in saved.summary


def test_quote_on_the_wrong_page_is_kept_with_its_page_corrected():
    model = scripted_model([("result", report(page=1))])  # quote is really on page 2
    ctx, _ = make_ctx(model)
    examine(ctx)
    assert ctx.deps.case.documents["D2010"].report.recitals[0].page == 2


def test_saved_report_is_reused_until_the_text_changes():
    model = scripted_model([("result", report())])
    ctx, _ = make_ctx(model)
    examine(ctx)
    again = examine(ctx)  # no model steps left: a second model call would fail
    assert again.startswith("Already examined")
    ctx.deps.case.documents["D2010"].text_hash = "stale"
    model.pending.extend([[("result", report())]])
    assert not examine(ctx).startswith("Already examined")


def test_repeated_failure_becomes_a_limitation():
    def broken(messages, info):
        return [("result", {"summary": "missing doc_id"})]  # invalid for the schema

    model = scripted_model(*[broken] * 8)
    ctx, _ = make_ctx(model)
    assert "may try once more" in examine(ctx)
    assert "recorded as a limitation" in examine(ctx)
    entry = ctx.deps.case.documents["D2010"]
    assert not entry.examined and entry.examination_error
    assert "cannot be examined" in examine(ctx)


def test_examining_a_document_reopens_stale_records_that_rest_on_it():
    model = scripted_model([("result", report())])
    ctx, _ = make_ctx(model)
    case = ctx.deps.case
    for transfer_id in ("PA-TC-0002", "PA-TC-0003"):  # sources EC + D2010, EC + D2018
        transfer = case.transfer(transfer_id)
        transfer.property = cf.Property(type="agricultural_land")
        transfer.documents = [
            cf.ProofDocument(name="Sale deed", proves="The sale.", status="missing")
        ]
        transfer.summary = "Deed unreadable."
    text = examine(ctx)
    assert not case.transfer("PA-TC-0002").recorded
    assert case.transfer("PA-TC-0003").recorded  # its own sources were not re-read
    assert "VERIFY AGAIN" in text and "PA-TC-0002" in text
