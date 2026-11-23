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


def closable(ctx):
    """Every transfer recorded and the property today recorded."""
    for transfer in ctx.case.transfers:
        transfer.property = cf.Property(type="agricultural_land")
        transfer.summary = "Checked."
    for name in cf.SECTIONS:
        setattr(ctx.case.property_today, name, cf.Section(note="In order."))
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


def test_quotes_match_through_ocr_markup():
    page = "<table><tr><td>Survey No.</td><td>**45/2**</td></tr></table>\n## SALE DEED"
    assert quote_on_page("Survey No. 45/2", page)
    assert quote_on_page("SALE DEED", page)


# -- citations --------------------------------------------------------------------


def test_citation_passes_when_quote_is_on_the_page():
    citation = cf.Citation(doc_id="D2010", page=2, quote="partition of 2005")
    assert gates.citation_problems(context(), [citation]) == []


def test_citation_with_fabricated_quote_fails():
    citation = cf.Citation(doc_id="D2010", page=2, quote="court permission obtained")
    assert "is not in D2010" in gates.citation_problems(context(), [citation])[0]


def test_real_quote_on_the_wrong_page_is_kept_with_its_page_corrected():
    citation = cf.Citation(doc_id="D2010", page=1, quote="partition of 2005")
    assert gates.citation_problems(context(), [citation]) == []
    assert citation.page == 2


def test_citation_of_unexamined_or_unknown_document_fails():
    citation = cf.Citation(doc_id="D2010", page=2, quote="partition of 2005")
    assert "not been examined" in gates.citation_problems(context(examined=False), [citation])[0]
    unknown = cf.Citation(doc_id="NOPE", page=1, quote="x")
    assert "not a document of this case" in gates.citation_problems(context(), [unknown])[0]


def test_encumbrance_certificate_never_proves_a_transfer():
    ctx = context()
    ec = cf.Citation(doc_id="EC", page=2, quote="Partition deed")
    deed = cf.Citation(doc_id="D2010", page=1, quote="Sale deed No. 555/2010")
    assert gates.proof_problems(ctx, [deed]) == []
    assert "encumbrance certificate" in gates.proof_problems(ctx, [ec])[0]


def test_a_connection_needs_the_previous_acquirers_as_sellers():
    ctx = context()
    first, second, _ = ctx.case.transfers
    assert gates.connection_problems(ctx, first, second) == []
    second.transaction.transferors = ["Someone Else"]
    assert (
        "are not the previous transfer's acquirers"
        in gates.connection_problems(ctx, first, second)[0]
    )


# -- chain integrity ----------------------------------------------------------------


def test_phase_a_chain_passes_chain_gates():
    assert gates.chain_problems(context()) == []


def test_dates_out_of_order_are_caught():
    ctx = context()
    ctx.case.transfers[2].transaction.executed_date = "01-01-1990"
    assert any("dated before" in p for p in gates.chain_problems(ctx))


def test_non_transfer_is_caught():
    ctx = context()
    ctx.case.transfers[1].transaction.transaction_type = "Mortgage"
    assert any("not an ownership transfer" in p for p in gates.chain_problems(ctx))


def test_evidence_status_must_match_sources():
    ctx = context()
    transaction = ctx.case.transfers[0].transaction
    transaction.evidence_status = "recital_reported"
    transaction.source_refs = transaction.source_refs[:1]
    assert any("needs a title deed" in p for p in gates.chain_problems(ctx))


# -- closure ------------------------------------------------------------------------


def test_complete_case_closes():
    assert gates.closure_problems(closable(context())) == []


def test_an_unverified_transfer_blocks_closure():
    ctx = closable(context())
    ctx.case.transfers[1].clear_record()
    assert any("PA-TC-0002 is not verified yet" in p for p in gates.closure_problems(ctx))


def test_the_property_today_must_be_recorded():
    ctx = closable(context())
    ctx.case.property_today.revenue_records = None
    assert any("not recorded for: revenue_records" in p for p in gates.closure_problems(ctx))


def test_every_uploaded_document_is_examined_before_closing():
    ctx = closable(context())
    ctx.case.documents["TAX"] = cf.DocumentEntry(
        doc_id="TAX", filename="tax.pdf", document_type="TAX_RECEIPT"
    )
    assert any("not yet examined: TAX" in p for p in gates.closure_problems(ctx))
    ctx.case.documents["TAX"].examination_error = "no OCR text"  # unreadable: a limitation
    assert gates.closure_problems(ctx) == []


def test_an_arrived_document_must_be_used_before_closing():
    ctx = closable(context())
    ctx.case.requests.append(
        cf.Request(
            id="R1",
            document="Khata extract",
            reason="Owner.",
            needed_for=["PA-TC-0003"],
            status="received",
            doc_id="D2018",
        )
    )
    assert any("record again: PA-TC-0003" in p for p in gates.closure_problems(ctx))


def test_duplicate_requests_block_closure():
    ctx = closable(context())
    ctx.case.requests += [
        cf.Request(id="R1", document="Legal-heir certificate", reason="Heirs.", needed_for=["A"]),
        cf.Request(
            id="R2",
            document="Legal heir certificate of Gundappa",
            reason="Heirs.",
            needed_for=["B"],
        ),
    ]
    assert any("ask for the same document" in p for p in gates.closure_problems(ctx))


def test_an_unexpected_finding_must_be_followed_up():
    ctx = closable(context())
    ctx.case.documents["EC"].report = cf.ExaminerReport(
        doc_id="EC",
        summary="EC.",
        unexpected=[cf.Fact(topic="mortgage", text="2012 mortgage", page=2, quote="Mortgage by")],
    )
    assert any("Unexpected finding EC F1" in p for p in gates.closure_problems(ctx))
    ctx.case.set_aside.append(cf.SetAside(doc_id="EC", fact="F1", reason="Released in 2015."))
    assert gates.closure_problems(ctx) == []
