"""Lead tools: each writes the Case File only when its gates pass."""

from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from backend.services.verification import case_file as cf
from backend.services.verification import gates, tools
from backend.services.verification.deps import VerifyDeps
from backend.services.verification.events import ListSink
from backend.tests.verification_fixtures import TEXTS, new_case_file


def make_ctx(examined=True):
    case = new_case_file()
    for entry in case.documents.values():
        entry.examined = examined
    sink = ListSink()
    deps = VerifyDeps(case=case, text_of=lambda doc_id: TEXTS.get(doc_id, ""), emit=sink)
    return SimpleNamespace(deps=deps), sink


def cite(doc_id, page, quote):
    return cf.Citation(doc_id=doc_id, page=page, quote=quote)


def found(doc_id, page, quote, name="Registered sale deed"):
    return cf.ProofDocument(
        name=name,
        proves="The transfer itself.",
        status="found",
        citations=[cite(doc_id, page, quote)],
    )


def missing(name, proves="Proves what is needed.", request_id=None):
    return cf.ProofDocument(name=name, proves=proves, status="missing", request_id=request_id)


LAND = cf.Property(survey="Sy.No.45", extent="2 acres 10 guntas", type="agricultural_land")
OK = cf.Connection(ok=True)
DEED = {
    "PA-TC-0001": found("D1998", 1, "Purchaser: Basavaraj"),
    "PA-TC-0002": found("D2010", 1, "Purchaser: Chandrashekar"),
    "PA-TC-0003": found("D2018", 1, "Purchaser: Deepa"),
}


def record(
    ctx, transfer_id, documents=None, concerns=None, connects=OK, summary="Clean sale.", **kw
):
    return tools.record_transfer(
        ctx,
        transfer_id,
        LAND,
        [DEED[transfer_id]] if documents is None else documents,
        summary,
        connects=None if transfer_id == "PA-TC-0001" else connects,
        concerns=concerns,
        **kw,
    )


def recorded(ctx, *transfer_ids):
    for transfer_id in transfer_ids:
        record(ctx, transfer_id)


def result(ctx, transfer_id):
    return cf.transfer_result(ctx.deps.case.transfer(transfer_id))


# -- record_transfer -------------------------------------------------------------


def test_a_proven_transfer_is_verified():
    ctx, sink = make_ctx()
    reply = record(ctx, "PA-TC-0001")
    assert reply.startswith("Recorded PA-TC-0001: verified.")
    transfer = ctx.deps.case.transfer("PA-TC-0001")
    assert transfer.property.type == "agricultural_land" and transfer.connects is None
    assert sink.texts("verdict") == ["The sale of 1998: verified. Clean sale."]


def test_the_result_is_worked_out_from_the_record():
    ctx, _ = make_ctx()
    record(
        ctx, "PA-TC-0001", concerns=[cf.Concern(severity="low", text="Stamp duty receipt faint.")]
    )
    assert result(ctx, "PA-TC-0001") == "verified_with_concerns"
    record(ctx, "PA-TC-0001", concerns=[cf.Concern(severity="high", text="Vendor was a minor.")])
    assert result(ctx, "PA-TC-0001") == "defective"
    record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], missing("Khata extract of 1998")])
    assert result(ctx, "PA-TC-0001") == "documents_missing"


def test_found_document_without_citation_is_refused():
    ctx, _ = make_ctx()
    uncited = cf.ProofDocument(name="Sale deed of 1998", proves="The sale.", status="found")
    with pytest.raises(ModelRetry, match="cites nothing"):
        record(ctx, "PA-TC-0001", documents=[uncited])
    with pytest.raises(ModelRetry, match="List the documents"):
        record(ctx, "PA-TC-0001", documents=[])
    assert not ctx.deps.case.transfer("PA-TC-0001").recorded


def test_ec_cannot_prove_a_transfer():
    ctx, _ = make_ctx()
    recorded(ctx, "PA-TC-0001")
    ec = found("EC", 2, "Partition deed among Basavaraj", "Encumbrance certificate")
    with pytest.raises(ModelRetry, match="encumbrance certificate"):
        record(ctx, "PA-TC-0002", documents=[ec])


def test_citing_a_fact_by_number_or_wording_cites_its_verified_quote():
    ctx, _ = make_ctx()
    ctx.deps.case.documents["D1998"].report = cf.ExaminerReport(
        doc_id="D1998",
        summary="1998 sale deed.",
        instrument=[cf.Fact(topic="number", text="No. 1234/1998", page=1, quote="No. 1234/1998")],
        parties=[
            cf.Party(name="Basavaraj", role="purchaser", page=1, quote="Purchaser: Basavaraj")
        ],
        recitals=[
            cf.Fact(
                topic="purchase",
                text="Basavaraj bought the land from Anand Rao in 1998",
                page=1,
                quote="Purchaser: Basavaraj",
            )
        ],
    )
    record(ctx, "PA-TC-0001", documents=[found("D1998", 3, "F2")])
    saved = ctx.deps.case.transfer("PA-TC-0001").documents[0].citations[0]
    assert (saved.quote, saved.page) == ("Purchaser: Basavaraj", 1)  # F1 instrument, F2 party
    record(ctx, "PA-TC-0001", documents=[found("D1998", 3, "Basavaraj bought the land from Anand")])
    assert ctx.deps.case.transfer("PA-TC-0001").documents[0].citations[0].page == 1
    with pytest.raises(ModelRetry, match="not in D1998"):
        record(ctx, "PA-TC-0001", documents=[found("D1998", 1, "F9")])


@pytest.mark.parametrize(
    "quote", ["F2", "[F2] Purchaser: Basavaraj bought it", "F2: the purchaser"]
)
def test_fact_number_citation_forms(quote):
    report = cf.ExaminerReport(
        doc_id="D1998",
        summary="1998 sale deed.",
        instrument=[cf.Fact(topic="number", text="No. 1234/1998", page=1, quote="No. 1234/1998")],
        parties=[
            cf.Party(name="Basavaraj", role="purchaser", page=1, quote="Purchaser: Basavaraj")
        ],
    )
    assert gates.examiner_fact(report, quote).quote == "Purchaser: Basavaraj"


def test_transfers_are_verified_oldest_first_from_the_root():
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="earlier transfers first, oldest first: PA-TC-0001"):
        record(ctx, "PA-TC-0002")
    case = new_case_file()
    assert case.window_start(this_year=2026) == 0  # nothing that old: the earliest is the root
    assert case.window_start(this_year=2045) == 1  # 1998 and 2010 are old enough; 2010 is root
    assert [t.id for t in case.window(this_year=2045)] == ["PA-TC-0002", "PA-TC-0003"]


# -- connection --------------------------------------------------------------------


def test_a_transfer_after_the_root_must_say_how_it_connects():
    ctx, _ = make_ctx()
    recorded(ctx, "PA-TC-0001")
    with pytest.raises(ModelRetry, match="connects"):
        record(ctx, "PA-TC-0002", connects=None)


def test_connects_ok_needs_the_previous_acquirers_as_sellers():
    ctx, _ = make_ctx()
    recorded(ctx, "PA-TC-0001")
    ctx.deps.case.transfer("PA-TC-0002").transaction.transferors = ["Ramesh"]
    with pytest.raises(ModelRetry, match="are not the previous transfer's acquirers"):
        record(ctx, "PA-TC-0002")
    with pytest.raises(ModelRetry, match="A break needs a note"):
        record(ctx, "PA-TC-0002", connects=cf.Connection(ok=False))


def test_a_break_is_defective_unless_a_missing_document_could_close_it():
    ctx, _ = make_ctx()
    recorded(ctx, "PA-TC-0001")
    gap = cf.Connection(ok=False, note="Nothing shows how Ramesh got the land from Basavaraj.")
    record(ctx, "PA-TC-0002", connects=gap)
    assert result(ctx, "PA-TC-0002") == "defective"
    heirs = missing("Legal-heir certificate of Basavaraj", "Shows Ramesh is Basavaraj's heir.")
    record(ctx, "PA-TC-0002", documents=[DEED["PA-TC-0002"], heirs], connects=gap)
    assert result(ctx, "PA-TC-0002") == "documents_missing"


def test_a_correction_fixes_the_chain_details():
    ctx, sink = make_ctx()
    recorded(ctx, "PA-TC-0001")
    deed = found("D2010", 1, "Vendors: Basavaraj and Bhimesh")
    record(
        ctx,
        "PA-TC-0002",
        documents=[deed],
        correction=tools.TransferCorrection(transferors=["Basavaraj", "Bhimesh"]),
    )
    assert ctx.deps.case.transfer("PA-TC-0002").transaction.transferors == ["Basavaraj", "Bhimesh"]
    assert any(text.startswith("Corrected the details") for text in sink.texts("chain"))
    with pytest.raises(ModelRetry, match="must rest on a found document"):
        record(
            ctx,
            "PA-TC-0002",
            documents=[missing("Sale deed of 2010")],
            correction=tools.TransferCorrection(transferors=["Basavaraj"]),
        )


# -- requests ----------------------------------------------------------------------


def test_a_missing_document_becomes_a_request():
    ctx, sink = make_ctx()
    reply = record(
        ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], missing("Khata extract of 1998")]
    )
    assert "Requests: R1." in reply
    request = ctx.deps.case.request("R1")
    assert (request.document, request.needed_for, request.status) == (
        "Khata extract of 1998",
        ["PA-TC-0001"],
        "open",
    )
    assert ctx.deps.case.transfer("PA-TC-0001").documents[1].request_id == "R1"
    assert sink.texts("requisition") == ["Document needed: Khata extract of 1998"]


def test_the_same_document_for_two_transfers_is_one_request():
    ctx, _ = make_ctx()
    will = "Certified copy of the 1996 Will of Parvatibai"
    record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], missing(will, "Proves her share.")])
    record(
        ctx,
        "PA-TC-0002",
        documents=[DEED["PA-TC-0002"], missing("The 1996 Will of Parvatibai with probate")],
    )
    record(
        ctx, "PA-TC-0003", documents=[DEED["PA-TC-0003"], missing("Any document", request_id="R1")]
    )
    assert [r.id for r in ctx.deps.case.requests] == ["R1"]
    assert ctx.deps.case.request("R1").needed_for == ["PA-TC-0001", "PA-TC-0002", "PA-TC-0003"]


def test_the_duplicates_from_case_8a14d132_merge():
    ctx, _ = make_ctx()
    record(
        ctx,
        "PA-TC-0001",
        documents=[
            DEED["PA-TC-0001"],
            missing(
                "Approved layout plan for Site 9 and khata showing the site within the layout",
                "Proves Site 9 was approved within the layout.",
            ),
            missing(
                "Conversion correction or survey linkage order for R.S. 699-A/14 and 699A/15",
                "Confirms the parcels are the same.",
            ),
        ],
    )
    record(
        ctx,
        "PA-TC-0002",
        documents=[
            DEED["PA-TC-0002"],
            missing(
                "Approved layout plan and khata for Plot 9 showing it within the approved layout",
                "Proves the site conveyed in the 2010 sale was approved.",
            ),
            missing(
                "Survey sketch or correction order linking R.S. 699-A/14, R.S. 699A/15 and "
                "CTS 1360B/9",
                "Establishes that the partitioned land and converted site are the same parcel.",
            ),
        ],
    )
    assert [r.id for r in ctx.deps.case.requests] == ["R1", "R2"]


@pytest.mark.parametrize(
    "name",
    [
        "Complete Gundappa succession set: death, legal-heir certificate and heirs' mutation",
        "Court case and settlement records, plus the agreement of sale recited in the 2007 deed",
        "Municipal completion certificate and occupancy certificate for the house",
    ],
)
def test_bundled_documents_are_refused(name):
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="names several documents"):
        record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], missing(name)])


def test_a_request_no_record_needs_is_dropped():
    ctx, _ = make_ctx()
    record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], missing("Khata extract of 1998")])
    record(ctx, "PA-TC-0001")
    assert ctx.deps.case.requests == []


def test_an_uploaded_document_settles_its_request_when_it_proves_what_was_needed():
    ctx, sink = make_ctx()
    record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], missing("Khata extract of 1998")])
    request = ctx.deps.case.request("R1")
    request.status, request.doc_id = "received", "D2018"
    record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], found("D2018", 1, "Purchaser: Deepa")])
    assert request.status == "settled"
    assert "Requested document accepted: Khata extract of 1998" in sink.texts("requisition")


def test_an_uploaded_document_that_does_not_prove_it_reopens_the_request():
    ctx, _ = make_ctx()
    record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], missing("Khata extract of 1998")])
    request = ctx.deps.case.request("R1")
    request.status, request.doc_id = "received", "D2018"
    ctx.deps.case.documents["D2018"].examined = False
    still_missing = missing("Khata extract of 1998", request_id="R1")
    with pytest.raises(ModelRetry, match="Examine it before"):
        record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], still_missing])
    ctx.deps.case.documents["D2018"].examined = True
    record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], still_missing])
    assert (request.status, request.doc_id) == ("open", None)


# -- property today ------------------------------------------------------------------


def test_the_property_today_comes_after_the_transfers_and_may_cite_the_ec():
    ctx, _ = make_ctx()
    ec = found("EC", 2, "Mortgage by Chandrashekar to Canara Bank", "Encumbrance certificate")
    mortgage = cf.Concern(severity="high", text="The 2012 Canara Bank mortgage has no release.")
    with pytest.raises(ModelRetry, match="Verify every transfer first"):
        tools.record_property_today(ctx, "encumbrances", "One open mortgage.", [ec], [mortgage])
    recorded(ctx, "PA-TC-0001", "PA-TC-0002", "PA-TC-0003")
    reply = tools.record_property_today(ctx, "encumbrances", "One open mortgage.", [ec], [mortgage])
    assert "record the property today: revenue_records, tax_and_approvals" in reply
    assert cf.section_ok(ctx.deps.case.section("encumbrances")) is False


# -- chain changes -------------------------------------------------------------------

PARTITION = tools.NewTransfer(
    transaction_type="Partition",
    executed_date="01-01-2005",
    transferors=["Basavaraj", "Bhimappa", "Bharathi"],
    transferees=["Basavaraj"],
    summary_points=["Schedule B allotted to Basavaraj."],
    evidence_status="recital_reported",
)


def test_an_inserted_transfer_says_why_and_reopens_the_next_one():
    ctx, sink = make_ctx()
    recorded(ctx, "PA-TC-0001", "PA-TC-0002")
    reason = "The 2010 deed recites the 2005 partition."
    reply = tools.insert_transfer(
        ctx, "PA-TC-0001", PARTITION, reason, [cite("D2010", 2, "under the partition of 2005")]
    )
    case = ctx.deps.case
    assert reply.startswith("Inserted VL-1.")
    assert [t.id for t in case.transfers] == ["PA-TC-0001", "VL-1", "PA-TC-0002", "PA-TC-0003"]
    inserted = case.transfer("VL-1")
    assert inserted.origin == "verification" and inserted.added_because.note == reason
    assert inserted.transaction.source_refs[0].filename == "deed-2010.pdf"
    assert not case.transfer("PA-TC-0002").recorded  # it now follows the partition
    assert any(text.startswith("Re-checking the sale of 2010") for text in sink.texts("chain"))


def test_insert_needs_citations_from_examined_documents():
    ctx, _ = make_ctx(examined=False)
    with pytest.raises(ModelRetry, match="not been examined"):
        tools.insert_transfer(ctx, "PA-TC-0001", PARTITION, "x", [cite("D2010", 2, "partition")])


def test_removing_a_transfer_drops_its_requests():
    ctx, _ = make_ctx()
    recorded(ctx, "PA-TC-0001", "PA-TC-0002")
    record(ctx, "PA-TC-0003", documents=[DEED["PA-TC-0003"], missing("Khata extract of 2018")])
    tools.remove_transfer(
        ctx, "PA-TC-0003", "A duplicate entry.", [cite("D2018", 1, "No. 777/2018")]
    )
    assert [t.id for t in ctx.deps.case.transfers] == ["PA-TC-0001", "PA-TC-0002"]
    assert ctx.deps.case.requests == []


# -- unexpected findings ------------------------------------------------------------


def with_unexpected(ctx):
    ctx.deps.case.documents["EC"].report = cf.ExaminerReport(
        doc_id="EC",
        summary="EC 1995-2024.",
        unexpected=[
            cf.Fact(
                topic="mortgage",
                text="2012 mortgage to Canara Bank",
                page=2,
                quote="Mortgage by Chandrashekar to Canara Bank",
            ),
            cf.Fact(topic="village", text="Village name spelt two ways", page=1, quote="Hosahalli"),
        ],
    )


def test_unexpected_findings_are_cited_or_set_aside():
    ctx, _ = make_ctx()
    with_unexpected(ctx)
    assert "unexpected FOLLOW UP F1 p.2: 2012 mortgage" in tools.view_case_file(ctx)
    recorded(ctx, "PA-TC-0001", "PA-TC-0002", "PA-TC-0003")
    mortgage = cf.Concern(severity="high", text="The 2012 Canara Bank mortgage has no release.")
    ec = found("EC", 2, "F1", "Encumbrance certificate")
    reply = tools.record_property_today(ctx, "encumbrances", "One open mortgage.", [ec], [mortgage])
    assert "unexpected findings to follow up: EC F2" in reply
    with pytest.raises(ModelRetry, match="EC F1 is not an unexpected finding still to follow up"):
        tools.set_aside(ctx, [tools.SetAsideItem(doc_id="EC", fact="F1", reason="Cited.")])
    tools.set_aside(ctx, [tools.SetAsideItem(doc_id="EC", fact="f2", reason="Only a spelling.")])
    assert gates.unused_unexpected(ctx.deps.case) == []


# -- buyer text, digest, reading --------------------------------------------------------


def test_buyer_facing_text_refuses_internal_ids_and_long_lines():
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="mentions internal ids"):
        record(ctx, "PA-TC-0001", summary="Same as PA-TC-0002.")
    with pytest.raises(ModelRetry, match="mentions internal ids"):
        record(ctx, "PA-TC-0001", concerns=[cf.Concern(severity="low", text="See DOC_018.")])
    with pytest.raises(ModelRetry, match="keep it to 220"):
        record(ctx, "PA-TC-0001", concerns=[cf.Concern(severity="low", text="y" * 221)])
    with pytest.raises(ModelRetry, match="keep it to 160"):
        record(ctx, "PA-TC-0001", documents=[DEED["PA-TC-0001"], missing("Khata", "z" * 161)])


def test_every_change_replies_with_what_is_still_to_do():
    ctx, _ = make_ctx()
    reply = record(ctx, "PA-TC-0001")
    assert "Still to do:" in reply and "next transfer to verify: PA-TC-0002 (then 1 more)" in reply


def test_view_case_file_lists_what_is_left_and_is_short_when_nothing_changed():
    ctx, _ = make_ctx()
    text = tools.view_case_file(ctx)
    assert "PA-TC-0002" in text and "STILL TO DO BEFORE CLOSING" in text
    assert "is not verified yet" in text
    assert tools.view_case_file(ctx).startswith("Nothing changed since your last view_case_file")
    record(ctx, "PA-TC-0001")
    assert "CASE FILE" in tools.view_case_file(ctx)


def test_read_pages():
    ctx, _ = make_ctx()
    text = tools.read_pages(ctx, "D2010", 2, 2)
    assert "--- Page 2 ---" in text and "partition of 2005" in text
