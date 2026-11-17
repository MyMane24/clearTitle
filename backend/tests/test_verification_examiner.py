"""The Document Examiner: reads every page, cites real quotes, caches its report."""

import asyncio
from types import SimpleNamespace

from pydantic_ai import capture_run_messages, models

from backend.services.verification import case_file as cf
from backend.services.verification import examiner
from backend.services.verification.deps import VerifyDeps
from backend.services.verification.events import ListSink
from backend.tests.verification_fixtures import TEXTS, new_case_file, retry_prompts, scripted_model

models.ALLOW_MODEL_REQUESTS = False

READ = [("read_next", {})]


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
        "recitals": [{"topic": "acquisition", "text": "2005 partition", "page": page, "quote": quote}],
        "unexpected": [
            {"topic": "minor", "text": "A minor's share is sold.", "page": 1, "quote": "minor"}
        ],
        **extra,
    }


def make_ctx(model):
    sink = ListSink()
    loads = []

    def text_of(doc_id):
        loads.append(doc_id)
        return TEXTS[doc_id]

    deps = VerifyDeps(case=new_case_file(), text_of=text_of, emit=sink, examiner_model=model)
    return SimpleNamespace(deps=deps), sink


def examine(ctx, doc_id="D2010"):
    return asyncio.run(examiner.examine_document(ctx, doc_id, ["Who were the vendors?"]))


def test_small_document_is_preloaded_so_one_call_suffices():
    model = scripted_model([("result", report())])
    ctx, _ = make_ctx(model)
    examine(ctx)
    assert ctx.deps.case.documents["D2010"].examined
    assert "THE WHOLE DOCUMENT FOLLOWS" in str(model.last_messages[0].parts[0].content) or any(
        "THE WHOLE DOCUMENT FOLLOWS" in str(part.content)
        for part in model.last_messages[0].parts
    )


def test_examiner_reads_everything_and_reports_with_citations():
    model = scripted_model(READ, [("result", report())])
    ctx, sink = make_ctx(model)
    text = examine(ctx)
    entry = ctx.deps.case.documents["D2010"]
    assert entry.examined and entry.report.doc_id == "D2010"  # id comes from the app
    assert "RECITALS" in text and "partition of 2005" in text
    assert "UNEXPECTED" in text
    assert entry.text_hash
    assert any("Examined deed-2010.pdf" in line for line in sink.texts("examine"))


def all_bad_report():
    bad = report(quote="court permission obtained")
    bad["parties"][0]["quote"] = "no such words here"
    bad["unexpected"][0]["quote"] = "invented text"
    return bad


def test_many_fabricated_quotes_are_sent_back_once_then_dropped():
    model = scripted_model([("result", all_bad_report())], [("result", all_bad_report())])
    ctx, _ = make_ctx(model)
    with capture_run_messages() as messages:
        examine(ctx)
    assert any("not in the document" in prompt for prompt in retry_prompts(messages))
    saved = ctx.deps.case.documents["D2010"].report
    assert saved.recitals == [] and saved.parties == [] and saved.unexpected == []
    assert "3 facts dropped" in saved.summary


def test_quote_on_the_wrong_page_is_corrected_not_rejected():
    model = scripted_model([("result", report(page=1))])  # quote is really on page 2
    ctx, _ = make_ctx(model)
    examine(ctx)
    assert ctx.deps.case.documents["D2010"].report.recitals[0].page == 2


def test_report_before_reading_every_page_is_sent_back(monkeypatch):
    monkeypatch.setattr(examiner, "VERIFY_READ_CHUNK_CHARS", 50)  # too big to preload
    model = scripted_model([("result", report())], READ, READ, READ, READ, [("result", report())])
    ctx, _ = make_ctx(model)
    with capture_run_messages() as messages:
        examine(ctx)
    assert any("Unread pages" in prompt for prompt in retry_prompts(messages))


def test_saved_report_is_reused_until_the_text_changes():
    model = scripted_model([("result", report())])
    ctx, _ = make_ctx(model)
    examine(ctx)
    again = examine(ctx)  # no model steps left: a second model call would fail
    assert again.startswith("Already examined")
    ctx.deps.case.documents["D2010"].text_hash = "stale"
    model.pending.extend([[("result", report())]])
    assert not examine(ctx).startswith("Already examined")


def test_repeated_failure_becomes_a_limitation(monkeypatch):
    monkeypatch.setattr(examiner, "VERIFY_EXAMINER_CALL_BUDGET", 2)
    model = scripted_model(*[READ] * 10)  # never reports, so the budget runs out
    ctx, _ = make_ctx(model)
    assert "may try once more" in examine(ctx)
    assert "recorded as a limitation" in examine(ctx)
    entry = ctx.deps.case.documents["D2010"]
    assert not entry.examined and entry.examination_error
    assert "cannot be examined" in examine(ctx)


def test_examining_a_document_reopens_stale_verdicts_that_rest_on_it():
    model = scripted_model([("result", report())])
    ctx, sink = make_ctx(model)
    case = ctx.deps.case
    stale = cf.LinkVerdict(
        verdict="unverified_missing_document",
        summary="Deed unreadable.",
        checks=[cf.CheckResult(check="instrument", status="not_verifiable", note="x")],
    )
    case.link("PA-TC-0002").verdict = stale  # sources EC + D2010
    case.link("PA-TC-0003").verdict = stale  # sources EC + D2018: untouched
    text = examine(ctx)
    assert case.link("PA-TC-0002").verdict is None
    assert case.link("PA-TC-0003").verdict is not None
    assert "NEEDS A NEW VERDICT" in text and "PA-TC-0002" in text


def test_one_bad_quote_is_dropped_without_a_costly_retry():
    model = scripted_model([("result", report(quote="court permission obtained"))])
    ctx, _ = make_ctx(model)
    examine(ctx)  # a second model call would fail: none is scripted
    saved = ctx.deps.case.documents["D2010"].report
    assert saved.recitals == [] and "1 facts dropped" in saved.summary
