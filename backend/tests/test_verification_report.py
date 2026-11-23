"""The one-page report: short opinion, findings including what checked out."""

from backend.schemas.due_diligence import DueDiligenceReport, WrittenReport
from backend.services.verification import case_file as cf
from backend.services.verification.report import case_issues, length_problems, report_input
from backend.tests.verification_fixtures import new_case_file


def verified(case):
    for link in case.chain:
        link.verdict = cf.LinkVerdict(
            verdict="verified",
            summary="ok",
        )
    return case


def written(reasons):
    return WrittenReport(opinion="CLEAR", reasons=reasons)


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


def test_writer_gets_verdicts_issues_and_needs_in_words_only():
    case = verified(new_case_file())
    case.chain[1].verdict.summary = "Registered sale, vendor title shown."
    case.issues.append(cf.Issue(id="I1", severity="medium", title="Patta in old name", detail="x"))
    case.requisitions.append(
        cf.Requisition(id="R1", document="Release deed", reason="Mortgage.", affects=["PA-TC-0002"])
    )
    text = report_input(case)
    assert "Registered sale, vendor title shown." in text
    assert "[medium] Patta in old name" in text
    assert "Release deed: Mortgage." in text
    assert "PA-TC-" not in text and "citations" not in text
    assert len(text) < 2000


def test_report_text_limits():
    assert length_problems(written(["One.", "Two."])) == []
    assert any("at most 2" in p for p in length_problems(written(["a", "b", "c"])))
    assert any("keep it to 140" in p for p in length_problems(written(["x" * 141])))


def test_older_saved_reports_still_load():
    old = {
        "version": 4,
        "opinion": "NOT_CLEAR",
        "property_summary": "Plot 9.",
        "opinion_reasons": [{"text": "A bank charge is not discharged.", "refs": ["I1"]}],
        "sections": [
            {
                "id": "issues",
                "title": "Issues identified",
                "blocks": [
                    {
                        "type": "findings",
                        "items": [
                            {"title": "Bank charge", "text": "x", "severity": "high"}
                        ],
                    }
                ],
            },
            {"id": "limitations", "title": "Limitations", "blocks": []},
        ],
        "changes_since_previous": ["The sale of 2019: now defective."],
        "basis": {"opinion": "NOT_CLEAR"},
    }
    report = DueDiligenceReport.model_validate(old)
    assert report.reasons == ["A bank charge is not discharged."]
    assert [(f.title, f.severity) for f in report.findings] == [("Bank charge", "high")]
    assert report.changes == ["The sale of 2019: now defective."]
    assert set(report.model_dump()) == {"version", "opinion", "reasons", "findings", "changes"}


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
