"""Gates: each rule passes on good state and catches the bad state it exists for."""

from backend.services.verification import case_file as cf
from backend.services.verification import gates
from backend.services.verification.pages import quote_on_page, split_pages
from backend.tests.verification_fixtures import TEXTS, new_case_file


def context(case=None, examined=True):
    case = case or new_case_file()
    if examined:
        for entry in case.documents.values():
            entry.examined = True
    return gates.GateContext(case=case, text_of=lambda doc_id: TEXTS.get(doc_id, ""))


def verdict(kind="verified"):
    return cf.LinkVerdict(
        verdict=kind,
        summary="Checked.",
    )


def closable(ctx):
    for link in ctx.case.chain:
        link.verdict = verdict()
    return ctx


# -- pages ----------------------------------------------------------------------


def test_pages_split_on_markers():
    pages = split_pages(TEXTS["D2010"])
    assert set(pages) == {1, 2}
    assert "partition of 2005" in pages[2]


def test_quote_matching_ignores_spacing_case_and_allows_ellipsis():
    page = "The vendor acquired the property under the partition of 2005,\nSchedule B."
    assert quote_on_page("the  VENDOR acquired ... partition of 2005", page)
    assert not quote_on_page("partition of 2006", page)
    assert quote_on_page("ಬಸವರಾಜ ಅವರು", "ಮಾರಾಟಗಾರ ಬಸವರಾಜ  ಅವರು ಸಹಿ")


# -- citations --------------------------------------------------------------------


def test_citation_passes_when_quote_is_on_the_page():
    ctx = context()
    citation = cf.Citation(doc_id="D2010", page=2, quote="partition of 2005")
    assert gates.citation_problems(ctx, [citation]) == []


def test_citation_with_fabricated_quote_fails():
    ctx = context()
    citation = cf.Citation(doc_id="D2010", page=2, quote="court permission obtained")
    assert "is not in D2010" in gates.citation_problems(ctx, [citation])[0]


def test_real_quote_on_the_wrong_page_is_kept_with_its_page_corrected():
    ctx = context()
    citation = cf.Citation(doc_id="D2010", page=1, quote="partition of 2005")
    assert gates.citation_problems(ctx, [citation]) == []
    assert citation.page == 2


def test_citation_of_unexamined_document_fails():
    ctx = context(examined=False)
    citation = cf.Citation(doc_id="D2010", page=2, quote="partition of 2005")
    assert "not been examined" in gates.citation_problems(ctx, [citation])[0]


def test_citation_of_unknown_document_fails():
    ctx = context()
    problems = gates.citation_problems(ctx, [cf.Citation(doc_id="NOPE", page=1, quote="x")])
    assert "not a document of this case" in problems[0]


def test_quotes_match_through_ocr_markup():
    page = "<table><tr><td>Survey No.</td><td>**45/2**</td></tr></table>\n## SALE DEED"
    assert quote_on_page("Survey No. 45/2", page)
    assert quote_on_page("SALE DEED", page)


def test_encumbrance_certificate_never_verifies_a_transfer():
    ctx = context()
    ec = cf.Citation(doc_id="EC", page=2, quote="Partition deed")
    deed = cf.Citation(doc_id="D2010", page=1, quote="Sale deed No. 555/2010")
    assert gates.link_evidence_problems(ctx, [deed]) == []
    assert "encumbrance certificate" in gates.link_evidence_problems(ctx, [ec])[0]


# -- chain integrity ----------------------------------------------------------------


def test_phase_a_chain_passes_chain_gates():
    assert gates.chain_problems(context()) == []


def test_continuity_break_is_caught():
    ctx = context()
    ctx.case.chain[2].transaction.transferors = ["Someone Else"]
    assert any("claims to continue" in p for p in gates.chain_problems(ctx))


def test_first_link_cannot_continue():
    ctx = context()
    ctx.case.chain[0].continues_previous = True
    assert any("earliest link" in p for p in gates.chain_problems(ctx))


def test_dates_out_of_order_are_caught():
    ctx = context()
    ctx.case.chain[2].transaction.executed_date = "01-01-1990"
    assert any("dated before" in p for p in gates.chain_problems(ctx))


def test_non_transfer_link_is_caught():
    ctx = context()
    ctx.case.chain[1].transaction.transaction_type = "Mortgage"
    assert any("not an ownership transfer" in p for p in gates.chain_problems(ctx))


def test_evidence_status_must_match_sources():
    ctx = context()
    ctx.case.chain[0].transaction.evidence_status = "recital_reported"
    ctx.case.chain[0].transaction.source_refs = ctx.case.chain[0].transaction.source_refs[:1]
    assert any("needs a title deed" in p for p in gates.chain_problems(ctx))


# -- closure ------------------------------------------------------------------------


def test_complete_case_closes():
    assert gates.closure_problems(closable(context())) == []


def test_missing_verdict_blocks_closure():
    ctx = context()
    assert any("has no verdict" in p for p in gates.closure_problems(ctx))


def test_open_lead_blocks_closure():
    ctx = closable(context())
    ctx.case.leads.append(cf.Lead(id="L1", text="2005 partition", source="EC p.2"))
    assert any("Lead L1 is open" in p for p in gates.closure_problems(ctx))


def test_unexamined_source_of_a_transaction_blocks_closure():
    ctx = closable(context())
    ctx.case.documents["D2018"].examined = False  # source of PA-TC-0003
    problems = gates.closure_problems(ctx)
    assert any("not yet examined: D2018" in p for p in problems)


def test_every_uploaded_document_is_examined_before_closing():
    ctx = closable(context())
    ctx.case.documents["TAX"] = cf.DocumentEntry(
        doc_id="TAX", filename="tax.pdf", document_type="TAX_RECEIPT"
    )
    assert any("not yet examined: TAX" in p for p in gates.closure_problems(ctx))
    ctx.case.documents["TAX"].examination_error = "no OCR text"  # unreadable: a limitation
    assert gates.closure_problems(ctx) == []


def test_unrecorded_break_blocks_closure():
    ctx = closable(context())
    ctx.case.chain[2].continues_previous = False
    assert any("no break is recorded" in p for p in gates.closure_problems(ctx))
    ctx.case.chain[2].break_note = "No deed connects Chandrashekar to Deepa."
    assert gates.closure_problems(ctx) == []


def test_requisition_must_name_known_ids():
    ctx = closable(context())
    ctx.case.requisitions.append(
        cf.Requisition(id="R1", document="Partition deed", reason="Title", affects=["ZZ"])
    )
    assert any("unknown ids: ZZ" in p for p in gates.closure_problems(ctx))


def test_missing_document_verdict_needs_an_open_requisition():
    ctx = closable(context())
    ctx.case.chain[1].verdict = verdict("unverified_missing_document")
    assert any("no open requisition" in p for p in gates.closure_problems(ctx))
    ctx.case.requisitions.append(
        cf.Requisition(id="R1", document="Deed", reason="Title", affects=["PA-TC-0002"])
    )
    assert gates.closure_problems(ctx) == []


def test_a_bundled_request_left_from_an_older_run_blocks_closure():
    ctx = closable(context())
    ctx.case.requisitions.append(
        cf.Requisition(
            id="R1",
            document="Complete succession set: death, legal-heir certificate and mutation",
            reason="Heirs.",
            affects=["PA-TC-0003"],
        )
    )
    assert any("asks for several documents" in p for p in gates.closure_problems(ctx))
