"""Lead tools: each writes the Case File only when its gates pass."""

from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from backend.services.verification import case_file as cf
from backend.services.verification import tools
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


PARTITION = tools.NewTransfer(
    transaction_type="Partition",
    executed_date=None,
    transferors=["Basavaraj", "Bhimappa", "Bharathi"],
    transferees=["Basavaraj"],
    summary_points=["Schedule B allotted to Basavaraj."],
    evidence_status="recital_reported",
    continues_previous=True,
)


def test_view_case_file_lists_what_is_left():
    ctx, _ = make_ctx()
    text = tools.view_case_file(ctx)
    assert "PA-TC-0002" in text
    assert "STILL TO DO BEFORE CLOSING" in text
    assert "has no verdict" in text


def found(doc_id, page, quote, document="Registered sale deed"):
    return cf.NeededDocument(
        document=document,
        proves="The transfer itself.",
        status="found",
        citations=[cite(doc_id, page, quote)],
    )


def judged(ctx, *link_ids):
    """Give earlier links a verdict, so a later one may be judged (oldest first)."""
    for link_id in link_ids:
        ctx.deps.case.link(link_id).verdict = cf.LinkVerdict(
            verdict="verified",
            summary="Earlier transfer.",
            checks=[cf.CheckResult(check="vendor title", status="ok", note="ok")],
        )


def record(ctx, link_id, verdict, summary, checks, needed):
    return tools.record_link_verdict(
        ctx, link_id, verdict, summary, checks, "agricultural_land", "2 acres 10 guntas", needed
    )


SALE_1998 = found("D1998", 1, "Purchaser: Basavaraj")


def test_verdict_is_recorded_with_valid_evidence():
    ctx, sink = make_ctx()
    check = cf.CheckResult(
        check="vendor title",
        status="ok",
        note="Vendor bought in 1998.",
        citations=[cite("D1998", 1, "Purchaser: Basavaraj")],
    )
    record(ctx, "PA-TC-0001", "verified", "Clean sale.", [check], [SALE_1998])
    verdict = ctx.deps.case.link("PA-TC-0001").verdict
    assert verdict.verdict == "verified" and verdict.property_type == "agricultural_land"
    assert verdict.needed_documents[0].status == "found"
    assert sink.texts("verdict")


def test_ok_check_without_citation_is_refused():
    ctx, _ = make_ctx()
    check = cf.CheckResult(check="vendor title", status="ok", note="Looks fine.")
    with pytest.raises(ModelRetry, match="cites nothing"):
        record(ctx, "PA-TC-0001", "verified", "Clean.", [check], [SALE_1998])
    assert ctx.deps.case.link("PA-TC-0001").verdict is None


def test_ec_cannot_prove_a_transfer():
    ctx, _ = make_ctx()
    judged(ctx, "PA-TC-0001")
    check = cf.CheckResult(
        check="registration",
        status="ok",
        note="EC shows it.",
        citations=[cite("EC", 2, "Partition deed among Basavaraj")],
    )
    with pytest.raises(ModelRetry, match="encumbrance certificate"):
        record(ctx, "PA-TC-0002", "verified", "x", [check], [SALE_1998])
    ec_as_document = found("EC", 2, "Partition deed among Basavaraj", "Encumbrance certificate")
    good = cf.CheckResult(
        check="vendor title", status="ok", note="ok", citations=SALE_1998.citations
    )
    with pytest.raises(ModelRetry, match="encumbrance certificate"):
        record(ctx, "PA-TC-0002", "verified", "x", [good], [ec_as_document])


def test_verdict_must_match_its_checks():
    ctx, _ = make_ctx()
    judged(ctx, "PA-TC-0001")
    check = cf.CheckResult(
        check="court permission",
        status="failed",
        note="None for minor.",
        citations=[cite("D2010", 1, "Bhimesh (minor")],
    )
    deed = found("D2010", 1, "Bhimesh (minor")
    with pytest.raises(ModelRetry, match="verified needs every check ok"):
        record(ctx, "PA-TC-0002", "verified", "x", [check], [deed])
    record(ctx, "PA-TC-0002", "defective", "Minor's share.", [check], [deed])


def test_evidence_free_verdict_is_refused():
    ctx, _ = make_ctx()
    judged(ctx, "PA-TC-0001", "PA-TC-0002")
    check = cf.CheckResult(check="vendor title", status="concern", note="Upstream gap.")
    with pytest.raises(ModelRetry, match="must cite evidence"):
        record(ctx, "PA-TC-0003", "verified_with_concerns", "x", [check], [SALE_1998])


def test_examined_deed_can_still_miss_a_supporting_document():
    ctx, _ = make_ctx()
    judged(ctx, "PA-TC-0001")
    tools.add_requisition(ctx, "Court permission for the minor", "Minor's share.", ["PA-TC-0001"])
    missing = cf.CheckResult(check="court permission", status="not_verifiable", note="Not seen.")
    deed = found("D2010", 1, "Bhimesh (minor")
    permission = cf.NeededDocument(
        document="Court permission", proves="Minor's share.", status="missing", requisition_id="R1"
    )
    record(ctx, "PA-TC-0002", "unverified_missing_document", "x", [missing], [deed, permission])
    # The requisition is now linked to the transfer that needs it.
    assert "PA-TC-0002" in ctx.deps.case.requisition("R1").affects


def test_citing_the_examiners_wording_cites_the_verified_quote():
    ctx, _ = make_ctx()
    ctx.deps.case.documents["D1998"].report = cf.ExaminerReport(
        doc_id="D1998",
        summary="1998 sale deed.",
        parties=[],
        instrument=[
            cf.Fact(
                topic="purchaser",
                text="Basavaraj bought the land from Anand Rao in 1998",
                page=1,
                quote="Purchaser: Basavaraj",
            )
        ],
    )
    check = cf.CheckResult(
        check="vendor title",
        status="ok",
        note="ok",
        citations=[cite("D1998", 3, "Basavaraj bought the land from Anand Rao")],
    )
    record(ctx, "PA-TC-0001", "verified", "Clean sale.", [check], [SALE_1998])
    saved = ctx.deps.case.link("PA-TC-0001").verdict.checks[0].citations[0]
    assert (saved.quote, saved.page) == ("Purchaser: Basavaraj", 1)


def test_transfers_are_verified_oldest_first():
    ctx, _ = make_ctx()
    check = cf.CheckResult(
        check="vendor title", status="ok", note="ok", citations=SALE_1998.citations
    )
    with pytest.raises(ModelRetry, match="earlier transfers first, oldest first: PA-TC-0001"):
        record(ctx, "PA-TC-0002", "verified", "x", [check], [SALE_1998])


def test_a_missing_needed_document_needs_its_requisition():
    ctx, _ = make_ctx()
    missing = cf.CheckResult(check="instrument", status="not_verifiable", note="Not seen.")
    deed = cf.NeededDocument(document="Sale deed of 1998", proves="The sale.", status="missing")
    with pytest.raises(ModelRetry, match="add it with add_requisition first"):
        record(ctx, "PA-TC-0001", "unverified_missing_document", "x", [missing], [deed])
    with pytest.raises(ModelRetry, match="List the documents"):
        record(ctx, "PA-TC-0001", "unverified_missing_document", "x", [missing], [])


def test_a_break_must_be_settled_before_judging_the_next_transfer():
    ctx, _ = make_ctx()
    judged(ctx, "PA-TC-0001")
    ctx.deps.case.link("PA-TC-0002").continues_previous = False
    check = cf.CheckResult(
        check="vendor title", status="ok", note="ok", citations=SALE_1998.citations
    )
    with pytest.raises(ModelRetry, match="Settle how ownership reached"):
        record(ctx, "PA-TC-0002", "verified", "x", [check], [SALE_1998])


def test_links_older_than_thirty_years_are_outside_the_window():
    case = new_case_file()
    assert case.window_start(this_year=2026) == 0  # nothing that old: the earliest link is root
    assert case.window_start(this_year=2045) == 1  # 1998 and 2010 are old enough; 2010 is root
    assert [link.link_id for link in case.window(this_year=2045)] == ["PA-TC-0002", "PA-TC-0003"]


def test_insert_link_keeps_the_chain_continuous():
    ctx, sink = make_ctx()
    message = tools.insert_link(
        ctx,
        "PA-TC-0001",
        PARTITION,
        "2010 deed recites the 2005 partition.",
        [cite("D2010", 2, "under the partition of 2005")],
    )
    chain = ctx.deps.case.chain
    assert message.startswith("Inserted VL-1.")
    assert [link.link_id for link in chain] == ["PA-TC-0001", "VL-1", "PA-TC-0002", "PA-TC-0003"]
    assert chain[1].origin == "verification"
    assert chain[1].transaction.source_refs[0].filename == "deed-2010.pdf"
    assert sink.texts("chain")


def test_insert_that_breaks_continuity_is_rolled_back():
    ctx, _ = make_ctx()
    stranger = PARTITION.model_copy(update={"transferors": ["Stranger"], "transferees": ["Other"]})
    with pytest.raises(ModelRetry, match="claims to continue"):
        tools.insert_link(ctx, "PA-TC-0001", stranger, "x", [cite("D2010", 2, "partition of 2005")])
    assert len(ctx.deps.case.chain) == 3


def test_insert_needs_citations_from_examined_documents():
    ctx, _ = make_ctx(examined=False)
    with pytest.raises(ModelRetry, match="not been examined"):
        tools.insert_link(ctx, "PA-TC-0001", PARTITION, "x", [cite("D2010", 2, "partition")])


def test_correct_link_and_mark_break():
    ctx, _ = make_ctx()
    tools.correct_link(
        ctx,
        "PA-TC-0002",
        tools.LinkCorrection(transferors=["Basavaraj", "Bhimesh"]),
        "Minor co-vendor omitted.",
        [cite("D2010", 1, "Vendors: Basavaraj and Bhimesh")],
    )
    link = ctx.deps.case.link("PA-TC-0002")
    assert link.transaction.transferors == ["Basavaraj", "Bhimesh"]
    tools.mark_break(ctx, "PA-TC-0003", "No deed from Chandrashekar.")
    assert ctx.deps.case.link("PA-TC-0003").break_note


def test_leads_and_requisitions():
    ctx, sink = make_ctx()
    assert tools.open_lead(ctx, "2005 partition", "EC p.2").startswith("Opened L1.")
    with pytest.raises(ModelRetry, match="Name the requisition that covers L1"):
        tools.resolve_lead(ctx, "L1", "requisition", "Deed needed.")
    added = tools.add_requisition(ctx, "Partition deed of 2005", "B's title", ["PA-TC-0002", "L1"])
    assert added.startswith("Added R1.")
    duplicate = tools.add_requisition(ctx, "partition deed of  2005", "x", ["PA-TC-0001"])
    assert "Already requested as R1" in duplicate
    assert ctx.deps.case.requisition("R1").affects == ["L1", "PA-TC-0001", "PA-TC-0002"]
    tools.resolve_lead(ctx, "L1", "requisition", "Deed needed.", requisition_id="R1")
    assert ctx.deps.case.lead("L1").status == "resolved"
    assert sink.texts("requisition") == ["Document needed: Partition deed of 2005"]


def test_requisition_must_affect_known_ids():
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="Unknown ids"):
        tools.add_requisition(ctx, "Deed", "x", ["NOPE"])


def test_requisition_names_the_transfer_it_is_for():
    ctx, _ = make_ctx()
    tools.open_lead(ctx, "2005 partition", "EC p.2")
    with pytest.raises(ModelRetry, match="transfer"):
        tools.add_requisition(ctx, "Partition deed of 2005", "Proves the split.", ["L1"])


def test_one_document_per_requisition():
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="one document per call"):
        tools.add_requisition(
            ctx, "The 1985 sale deed; the 1996 Will", "Proves the title.", ["PA-TC-0001"]
        )
    tools.add_requisition(ctx, "Sale deed of 1985", "Proves A's title.", ["PA-TC-0001"])
    tools.add_requisition(ctx, "Will of Parvatibai of 1996", "Proves the share.", ["PA-TC-0001"])
    assert [item.id for item in ctx.deps.case.requisitions] == ["R1", "R2"]


def test_similar_requisition_is_not_added_twice():
    ctx, _ = make_ctx()
    tools.add_requisition(
        ctx, "Certified copy of the 1996 Will of Parvatibai", "Proves her share.", ["PA-TC-0001"]
    )
    reply = tools.add_requisition(
        ctx, "The 1996 Will of Parvatibai with probate", "Proves Manohar's share.", ["PA-TC-0002"]
    )
    assert reply.startswith("Already requested as R1")
    assert len(ctx.deps.case.requisitions) == 1
    assert ctx.deps.case.requisition("R1").affects == ["PA-TC-0001", "PA-TC-0002"]


def test_the_duplicates_from_case_8a14d132_merge():
    ctx, _ = make_ctx()
    tools.add_requisition(
        ctx,
        "Approved layout plan for Site 9 and khata showing the site within the layout",
        "Proves Site 9 was approved within the layout.",
        ["PA-TC-0002"],
    )
    tools.add_requisition(
        ctx,
        "Approved layout plan and khata for Plot 9 showing it within the approved layout",
        "Proves the site conveyed in the 2010 sale was approved.",
        ["PA-TC-0002"],
    )
    tools.add_requisition(
        ctx,
        "Conversion correction or survey linkage order for R.S. 699-A/14 and 699A/15",
        "Confirms the parcels are the same.",
        ["PA-TC-0001"],
    )
    tools.add_requisition(
        ctx,
        "Survey sketch or correction order linking R.S. 699-A/14, R.S. 699A/15 and CTS 1360B/9",
        "Establishes that the partitioned land and converted site are the same parcel.",
        ["PA-TC-0001"],
    )
    assert [item.id for item in ctx.deps.case.requisitions] == ["R1", "R2"]


@pytest.mark.parametrize(
    "document",
    [
        "Complete Gundappa succession set: death, legal-heir certificate and heirs' mutation",
        "Court case and settlement records, plus the agreement of sale recited in the 2007 deed",
        "Municipal completion certificate and occupancy certificate for the house",
    ],
)
def test_bundled_documents_are_refused(document):
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="one document per call"):
        tools.add_requisition(ctx, document, "Proves it.", ["PA-TC-0003"])


def test_withdrawing_a_duplicate_moves_it_to_the_one_kept():
    ctx, _ = make_ctx()
    case = ctx.deps.case
    case.requisitions += [
        cf.Requisition(
            id="R1", document="Legal-heir certificate", reason="Heirs.", affects=["PA-TC-0002"]
        ),
        cf.Requisition(
            id="R2",
            document="Legal heir certificate of Gundappa",
            reason="Heirs.",
            affects=["PA-TC-0003"],
        ),
    ]
    from backend.services.verification import gates

    assert any(
        "ask for the same document" in p for p in gates.closure_problems(ctx.deps.gate_context)
    )
    tools.withdraw_requisition(ctx, "R2", "Same document as the other request.", replaced_by="R1")
    assert case.requisition("R2").status == "withdrawn"
    assert case.requisition("R1").affects == ["PA-TC-0002", "PA-TC-0003"]
    assert not any("same document" in p for p in gates.closure_problems(ctx.deps.gate_context))


def test_record_issue():
    ctx, _ = make_ctx()
    tools.record_issue(
        ctx,
        "high",
        "Mortgage not released",
        "Canara Bank 2012 mortgage has no release.",
        citations=[cite("EC", 2, "Mortgage by Chandrashekar to Canara Bank")],
    )
    assert ctx.deps.case.issues[0].id == "I1"


def test_buyer_facing_text_refuses_internal_ids():
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="mentions internal ids"):
        tools.record_issue(ctx, "high", "See PA-TC-0002", "The 2019 sale is defective.")
    with pytest.raises(ModelRetry, match="mentions internal ids"):
        tools.open_lead(ctx, "Check DOC_018", "EC p.2")
    tools.open_lead(ctx, "Heirs of Gundappa", "Death certificate")
    with pytest.raises(ModelRetry, match="mentions internal ids"):
        tools.resolve_lead(ctx, "L1", "not_material", "Covered by R1.")


def test_read_pages():
    ctx, _ = make_ctx()
    text = tools.read_pages(ctx, "D2010", 2, 2)
    assert "--- Page 2 ---" in text and "partition of 2005" in text


def test_one_requisition_closes_its_leads_in_the_same_call():
    ctx, sink = make_ctx()
    tools.open_lead(ctx, "Heirs of Gundappa", "Death certificate")
    tools.open_lead(ctx, "Heirship shares", "Family certificate")
    reply = tools.add_requisition(
        ctx, "Legal heir certificate", "Heirship", ["PA-TC-0003"], closes_leads=["L1", "L2"]
    )
    assert reply.startswith("Added R1.")
    assert all(lead.status == "resolved" for lead in ctx.deps.case.leads)
    assert ctx.deps.case.requisition("R1").affects == ["PA-TC-0003", "L1", "L2"]
    with pytest.raises(ModelRetry, match="L9 is not an open lead"):
        tools.add_requisition(ctx, "Other", "x", ["PA-TC-0001"], closes_leads=["L9"])


def test_every_change_replies_with_what_is_still_to_do():
    ctx, _ = make_ctx()
    reply = tools.open_lead(ctx, "2005 partition", "EC p.2")
    assert "Still to do:" in reply
    assert "next transfer to verify: PA-TC-0001 (then 2 more)" in reply
    assert "open leads: L1" in reply


def test_resolving_a_lead_by_requisition_links_it_automatically():
    ctx, _ = make_ctx()
    tools.open_lead(ctx, "Heirs of Gundappa", "Death certificate")
    tools.add_requisition(ctx, "Legal heir certificate", "Heirship", ["PA-TC-0003"])
    tools.resolve_lead(ctx, "L1", "requisition", "Covered by the request.", requisition_id="R1")
    assert ctx.deps.case.requisition("R1").affects == ["PA-TC-0003", "L1"]
    with pytest.raises(ModelRetry, match="open: R1"):
        tools.open_lead(ctx, "Another", "x") and tools.resolve_lead(ctx, "L2", "requisition", "x")


def test_duplicate_issue_is_pointed_out_and_can_be_updated():
    ctx, _ = make_ctx()
    tools.record_issue(ctx, "medium", "Outstanding mortgage to Canara Bank", "Not released.")
    reply = tools.record_issue(ctx, "high", "Unreleased Canara Bank mortgage", "No release deed.")
    assert reply.startswith("Not recorded: this looks like I1")
    assert len(ctx.deps.case.issues) == 1
    tools.update_issue(ctx, "I1", severity="high")
    assert ctx.deps.case.issues[0].severity == "high"
    tools.record_issue(ctx, "low", "Unreleased Canara Bank mortgage", "Second loan.", distinct=True)
    assert len(ctx.deps.case.issues) == 2


def test_buyer_text_is_kept_short():
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="keep it to 70"):
        tools.record_issue(ctx, "high", "x" * 71, "Short detail.")
    with pytest.raises(ModelRetry, match="keep it to 220"):
        tools.record_issue(ctx, "high", "Mortgage not released", "y" * 221)
    with pytest.raises(ModelRetry, match="keep it to 160"):
        tools.add_requisition(ctx, "Release deed", "z" * 161, ["PA-TC-0003"])


def test_clear_check_needs_evidence_and_is_recorded_once():
    ctx, sink = make_ctx()
    with pytest.raises(ModelRetry, match="Cite the passages"):
        tools.record_clear_check(ctx, "Owner name matches", "Same name in deed and RTC.", [])
    proof = [cite("D2018", 1, "Purchaser: Deepa")]
    reply = tools.record_clear_check(ctx, "Owner name matches", "Deepa in the 2018 deed.", proof)
    assert reply.startswith("Recorded C1.")
    again = tools.record_clear_check(ctx, "Owner name matches", "Deepa in the deed.", proof)
    assert again.startswith("Not recorded")
    assert sink.texts("clear") == ["Clear: Owner name matches"]


def test_citing_a_fact_by_its_number_cites_its_verified_quote():
    ctx, _ = make_ctx()
    ctx.deps.case.documents["D1998"].report = cf.ExaminerReport(
        doc_id="D1998",
        summary="1998 sale deed.",
        instrument=[cf.Fact(topic="number", text="No. 1234/1998", page=1, quote="No. 1234/1998")],
        parties=[
            cf.Party(name="Basavaraj", role="purchaser", page=1, quote="Purchaser: Basavaraj")
        ],
    )
    check = cf.CheckResult(
        check="vendor title", status="ok", note="ok", citations=[cite("D1998", 1, "F2")]
    )
    record(ctx, "PA-TC-0001", "verified", "Clean sale.", [check], [SALE_1998])
    saved = ctx.deps.case.link("PA-TC-0001").verdict.checks[0].citations[0]
    assert saved.quote == "Purchaser: Basavaraj"  # F1 instrument, F2 the party
    bad = cf.CheckResult(check="x", status="ok", note="ok", citations=[cite("D1998", 1, "F9")])
    ctx.deps.case.link("PA-TC-0001").verdict = None
    with pytest.raises(ModelRetry, match="not in D1998"):
        record(ctx, "PA-TC-0001", "verified", "Clean.", [bad], [SALE_1998])


def test_view_case_file_is_short_when_nothing_changed():
    ctx, _ = make_ctx()
    assert "CASE FILE" in tools.view_case_file(ctx)
    assert tools.view_case_file(ctx).startswith("Nothing changed since your last view_case_file")
    tools.open_lead(ctx, "2005 partition", "EC p.2")
    assert "CASE FILE" in tools.view_case_file(ctx)


@pytest.mark.parametrize(
    "quote", ["F2", "[F2] Purchaser: Basavaraj bought it", "F2: the purchaser"]
)
def test_fact_number_citation_forms(quote):
    from backend.services.verification.gates import examiner_fact

    report = cf.ExaminerReport(
        doc_id="D1998",
        summary="1998 sale deed.",
        instrument=[cf.Fact(topic="number", text="No. 1234/1998", page=1, quote="No. 1234/1998")],
        parties=[
            cf.Party(name="Basavaraj", role="purchaser", page=1, quote="Purchaser: Basavaraj")
        ],
    )
    assert examiner_fact(report, quote).quote == "Purchaser: Basavaraj"


def test_an_issue_is_one_problem_not_a_summary_of_the_chain():
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="at most 3 transfers"):
        tools.record_issue(
            ctx,
            "high",
            "Title chain remains unverified",
            "Several transfers are unproven.",
            link_ids=["PA-TC-0001", "PA-TC-0002", "PA-TC-0003", "PA-TC-0001"],
        )
