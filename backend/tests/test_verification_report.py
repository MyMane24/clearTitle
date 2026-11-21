"""The one-page report: short opinion, findings including what checked out."""

from backend.schemas.due_diligence import OpinionReason, ParagraphBlock, Section, WrittenReport
from backend.services.verification import case_file as cf
from backend.services.verification.report import case_issues, length_problems
from backend.tests.verification_fixtures import new_case_file


def verified(case):
    for link in case.chain:
        link.verdict = cf.LinkVerdict(
            verdict="verified",
            summary="ok",
            checks=[cf.CheckResult(check="vendor title", status="ok", note="ok")],
        )
    return case


def written(reasons, limitation="Rests only on the documents provided."):
    return WrittenReport(
        property_summary="Sy.No.45, Hosahalli, owned by Deepa.",
        opinion="CLEAR",
        opinion_reasons=[OpinionReason(text=text) for text in reasons],
        sections=[
            Section(id="limitations", title="Limitations", blocks=[ParagraphBlock(text=limitation)])
        ],
    )


def test_unbroken_verified_chain_is_a_clear_finding():
    findings = case_issues(verified(new_case_file()))
    assert [f.title for f in findings] == ["Chain of title is unbroken"]
    assert findings[0].severity == "clear" and "from 1998 through 3 transfers" in findings[0].text


def test_no_clear_chain_finding_with_a_break_or_an_unjudged_transfer():
    case = verified(new_case_file())
    case.chain[1].verdict = None
    assert not [f for f in case_issues(case) if f.severity == "clear"]
    case = verified(new_case_file())
    case.chain[2].continues_previous, case.chain[2].break_note = False, "No deed."
    titles = [f.title for f in case_issues(case)]
    assert "Chain of title is unbroken" not in titles
    assert any(title.startswith("Break in the title chain") for title in titles)


def test_problems_come_before_clear_findings():
    case = verified(new_case_file())
    case.issues.append(cf.Issue(id="I1", severity="medium", title="Patta in old name", detail="x"))
    assert [f.severity for f in case_issues(case)] == ["medium", "clear"]


def test_report_text_limits():
    assert length_problems(written(["One.", "Two."])) == []
    assert any("at most 2" in p for p in length_problems(written(["a", "b", "c"])))
    assert any("keep it to 140" in p for p in length_problems(written(["x" * 141])))
    assert any("one sentence" in p for p in length_problems(written(["a"], "y" * 241)))


def test_a_summary_issue_does_not_hide_a_break():
    case = verified(new_case_file())
    case.chain[2].continues_previous, case.chain[2].break_note = False, "No deed."
    case.issues.append(
        cf.Issue(
            id="I1",
            severity="high",
            title="Title chain remains unverified",
            detail="x",
            link_ids=[link.link_id for link in case.chain] + ["PA-TC-0001"],
        )
    )
    titles = [f.title for f in case_issues(case)]
    assert any(title.startswith("Break in the title chain") for title in titles)
