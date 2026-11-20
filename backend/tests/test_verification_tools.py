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


def test_verdict_is_recorded_with_valid_evidence():
    ctx, sink = make_ctx()
    check = cf.CheckResult(
        check="vendor title",
        status="ok",
        note="Vendor bought in 1998.",
        citations=[cite("D1998", 1, "Purchaser: Basavaraj")],
    )
    tools.record_link_verdict(ctx, "PA-TC-0001", "verified", "Clean sale.", [check])
    assert ctx.deps.case.link("PA-TC-0001").verdict.verdict == "verified"
    assert sink.texts("verdict")


def test_ok_check_without_citation_is_refused():
    ctx, _ = make_ctx()
    check = cf.CheckResult(check="vendor title", status="ok", note="Looks fine.")
    with pytest.raises(ModelRetry, match="cites nothing"):
        tools.record_link_verdict(ctx, "PA-TC-0001", "verified", "Clean.", [check])
    assert ctx.deps.case.link("PA-TC-0001").verdict is None


def test_ec_cannot_prove_a_transfer():
    ctx, _ = make_ctx()
    check = cf.CheckResult(
        check="registration",
        status="ok",
        note="EC shows it.",
        citations=[cite("EC", 2, "Partition deed among Basavaraj")],
    )
    with pytest.raises(ModelRetry, match="encumbrance certificate"):
        tools.record_link_verdict(ctx, "PA-TC-0002", "verified", "x", [check])


def test_verdict_must_match_its_checks():
    ctx, _ = make_ctx()
    check = cf.CheckResult(
        check="court permission",
        status="failed",
        note="None for minor.",
        citations=[cite("D2010", 1, "Bhimesh (minor")],
    )
    with pytest.raises(ModelRetry, match="verified needs every check ok"):
        tools.record_link_verdict(ctx, "PA-TC-0002", "verified", "x", [check])
    tools.record_link_verdict(ctx, "PA-TC-0002", "defective", "Minor's share.", [check])


def test_evidence_free_verdict_is_refused():
    ctx, _ = make_ctx()
    check = cf.CheckResult(check="vendor title", status="concern", note="Upstream gap.")
    with pytest.raises(ModelRetry, match="must cite evidence"):
        tools.record_link_verdict(ctx, "PA-TC-0003", "verified_with_concerns", "x", [check])


def test_examined_own_instrument_is_never_missing():
    ctx, _ = make_ctx()
    ctx.deps.case.documents["D2010"].report = cf.ExaminerReport(
        doc_id="D2010",
        summary="2010 sale deed.",
        instrument=[
            cf.Fact(topic="registration", text="No. 555/2010", page=1, quote="Sale deed No. 555/2010")
        ],
    )
    missing = cf.CheckResult(check="instrument", status="not_verifiable", note="Not seen.")
    with pytest.raises(ModelRetry, match="has been examined"):
        tools.record_link_verdict(
            ctx, "PA-TC-0002", "unverified_missing_document", "x", [missing]
        )
    # A link known only from another deed's recital may still be missing its instrument.
    tools.record_link_verdict(ctx, "PA-TC-0001", "unverified_missing_document", "x", [missing])


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
        tools.insert_link(
            ctx, "PA-TC-0001", stranger, "x", [cite("D2010", 2, "partition of 2005")]
        )
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
    added = tools.add_requisition(ctx, "Partition deed of 2005", "B's title", ["L1"])
    assert added.startswith("Added R1.")
    duplicate = tools.add_requisition(ctx, "partition deed of  2005", "x", ["PA-TC-0001"])
    assert "Already requested as R1" in duplicate
    assert ctx.deps.case.requisition("R1").affects == ["L1", "PA-TC-0001"]
    tools.resolve_lead(ctx, "L1", "requisition", "Deed needed.", requisition_id="R1")
    assert ctx.deps.case.lead("L1").status == "resolved"
    assert sink.texts("requisition") == ["Document needed: Partition deed of 2005"]


def test_requisition_must_affect_known_ids():
    ctx, _ = make_ctx()
    with pytest.raises(ModelRetry, match="Unknown ids"):
        tools.add_requisition(ctx, "Deed", "x", ["NOPE"])


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
    assert "no verdict: PA-TC-0001, PA-TC-0002, PA-TC-0003" in reply
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
