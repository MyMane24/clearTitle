"""The advocate-style report: what the writer gets, the gates on what it writes, the
saved report and its PDF."""

import fitz

from backend.schemas.due_diligence import DueDiligenceReport, WrittenReport
from backend.services.verification import case_file as cf
from backend.services.verification.report import (
    assemble,
    length_problems,
    report_input,
    report_problems,
)
from backend.services.verification.report_pdf import render_pdf
from backend.tests.verification_fixtures import new_case_file

DEEDS = {
    "D1998": ("No. 1234/1998", "Basavaraj"),
    "D2010": ("No. 555/2010", "Chandrashekar"),
    "D2018": ("No. 777/2018", "Deepa"),
}


def verified(case):
    """Every transfer verified, the property today in order, every document examined."""
    for transfer in case.transfers:
        transfer.property = cf.Property(type="agricultural_land")
        transfer.summary = "Registered sale."
    for name in cf.SECTIONS:
        setattr(case.property_today, name, cf.Section(note="In order."))
    for doc_id, entry in case.documents.items():
        number, buyer = DEEDS.get(doc_id, ("", ""))
        entry.examined = True
        entry.report = cf.ExaminerReport(
            doc_id=doc_id,
            summary=f"{entry.document_type} {doc_id}.",
            instrument=[cf.Fact(topic="number", text=number or "EC", page=1, quote=number or "EC")],
            parties=[cf.Party(name=buyer or "Office", role="purchaser", page=1, quote="q")],
        )
    return case


def written(case, **changes):
    order = ["EC", "D1998", "D2010", "D2018"]
    fields = {
        "opinion": "CLEAR",
        "reasons": ["Every transfer is proved and the property is free of charges."],
        "title_holders": ["Smt. Deepa"],
        "property_description": "All that piece and parcel of land bearing Sy. No. 45, Hosahalli.",
        "boundaries": {"east": "Road", "west": "Sy. No. 46"},
        "documents": [
            {"doc_id": d, "date": "01.01.2018", "nature": f"Registered document {d[-4:]}"}
            for d in order
        ],
        "document_details": [
            {
                "doc_id": d,
                "text": f"The document at Sl. No. {n} is the document {DEEDS.get(d, ('',))[0]}.",
            }
            for n, d in enumerate(order, start=1)
        ],
        "history": ["Originally Shri. Anand Rao owned the land.", "Thereafter it was sold."],
        "certificate": "It is observed that Smt. Deepa holds clear and marketable title.",
    }
    return WrittenReport.model_validate({**fields, **changes})


def test_a_faithful_report_passes_every_gate():
    case = verified(new_case_file())
    assert report_problems(case, written(case)) == []


def test_every_examined_document_is_covered_once_in_order():
    case = verified(new_case_file())
    report = written(case)
    short = written(case, documents=[r.model_dump() for r in report.documents[1:]])
    problems = report_problems(case, short)
    assert any("missing: EC" in p for p in problems)
    assert any("same order as documents" in p for p in problems)


def test_an_invented_document_number_is_refused():
    case = verified(new_case_file())
    details = [d.model_dump() for d in written(case).document_details]
    details[1]["text"] = (
        "The document at Sl. No. 2 is the Sale Deed bearing No. BEL-1-99999-1998-99."
    )
    problems = report_problems(case, written(case, document_details=details))
    assert any("'BEL-1-99999-1998-99' in the paragraph on D1998" in p for p in problems)


def test_internal_ids_and_wrong_owners_are_refused():
    case = verified(new_case_file())
    problems = report_problems(
        case, written(case, history=["See PA-TC-0002."], title_holders=["Shri. Anand Rao"])
    )
    assert any("mentions internal ids" in p for p in problems)
    assert any("present owners from the last transfer: Deepa" in p for p in problems)


def test_the_opinion_must_agree_with_the_records():
    case = verified(new_case_file())
    case.transfers[2].concerns = [cf.Concern(severity="high", text="Vendor was a minor.")]
    assert any("must be NOT_CLEAR" in p for p in report_problems(case, written(case)))


def test_report_text_limits():
    case = verified(new_case_file())
    assert length_problems(written(case, reasons=["One.", "Two."])) == []
    assert any("at most 2" in p for p in length_problems(written(case, reasons=["a", "b", "c"])))
    assert any("keep it to 140" in p for p in length_problems(written(case, reasons=["x" * 141])))


def test_writer_gets_the_records_and_each_documents_facts():
    case = verified(new_case_file())
    case.transfers[1].concerns = [cf.Concern(severity="medium", text="Patta in old name.")]
    case.requests.append(
        cf.Request(id="R1", document="Release deed", reason="Mortgage.", needed_for=["PA-TC-0002"])
    )
    text = report_input(case)
    assert "Present owners (last transfer): Deepa" in text
    assert "The sale of 2010 (01-01-2010, no. 555/2010): Basavaraj -> Chandrashekar." in text
    assert "[medium] Patta in old name." in text
    assert "Release deed: Mortgage." in text
    assert (
        "[D2010] SALE_DEED | deed-2010.pdf" in text and "instrument - number: No. 555/2010" in text
    )
    assert "PA-TC-" not in text


def test_the_saved_report_adds_the_annexure_date_and_changes():
    case = verified(new_case_file())
    case.requests.append(
        cf.Request(id="R1", document="Release deed", reason="Mortgage.", needed_for=["PA-TC-0003"])
    )
    report = assemble(
        case, written(case), 2, {"opinion": "NOT_CLEAR", "links": {}, "requisitions": {}}
    )
    assert [(d.document, d.reason) for d in report.documents_required] == [
        ("Release deed", "Mortgage.")
    ]
    assert report.prepared_on is not None
    assert report.changes[0] == "The opinion changed from not clear to clear."


def test_the_pdf_has_every_part_of_the_report():
    case = verified(new_case_file())
    case.requests.append(
        cf.Request(id="R1", document="Release deed", reason="Mortgage.", needed_for=["PA-TC-0003"])
    )
    pdf = render_pdf(assemble(case, written(case), 1, None))
    text = " ".join(page.get_text() for page in fitz.open(stream=pdf, filetype="pdf"))
    text = " ".join(text.split())
    for heading in (
        "Report of Investigation of Title in respect of Immovable Property",
        "I. Particulars of the title holder",
        "II. Particulars of the documents scrutinised",
        "III. DETAILS OF DOCUMENTS SCRUTINISED",
        "IV. HISTORY OF TITLE",
        "V. CERTIFICATE",
        "ANNEXURE: DOCUMENTS STILL REQUIRED",
    ):
        assert heading in text
    assert "Smt. Deepa" in text and "East : Road" in text and "Scanned copy" in text
    assert "1. Release deed: Mortgage." in text
    assert "To be reviewed and signed by an advocate." in text and "1 | Page" in text


def test_older_saved_reports_still_load_and_print():
    old = {
        "version": 4,
        "opinion": "NOT_CLEAR",
        "property_summary": "Plot 9.",
        "opinion_reasons": [{"text": "A bank charge is not discharged.", "refs": ["I1"]}],
        "sections": [{"id": "limitations", "title": "Limitations", "blocks": []}],
        "changes_since_previous": ["The sale of 2019: now defective."],
    }
    report = DueDiligenceReport.model_validate(old)
    assert report.reasons == ["A bank charge is not discharged."] and report.documents == []
    v5 = DueDiligenceReport.model_validate(
        {"version": 5, "opinion": "NOT_CLEAR", "reasons": ["x"], "findings": [{"title": "t"}]}
    )
    assert v5.reasons == ["x"]
    text = " ".join(
        page.get_text() for page in fitz.open(stream=render_pdf(report), filetype="pdf")
    )
    assert "older format" in " ".join(text.split())


def test_characters_the_pdf_font_lacks_never_print_as_boxes():
    from backend.services.verification.report_pdf import printable

    assert printable("typed line states “21 Ⅲ 2010”") == "typed line states “21 III 2010”"
    assert printable("ಬಸವರಾಜ") == "??????"
    assert printable("₹48,80,000") == "Rs. 48,80,000"


def test_undated_documents_have_an_empty_date_and_the_logo_is_on_page_one_only():
    case = verified(new_case_file())
    rows = [r.model_dump() for r in written(case).documents]
    rows[0]["date"] = "date not stated"
    report = assemble(case, written(case, documents=rows), 1, None)
    assert report.documents[0].date == ""
    report.history = ["Thereafter the land was sold."] * 40  # long enough for a second page
    pages = list(fitz.open(stream=render_pdf(report), filetype="pdf"))
    assert len(pages) > 1
    assert len(pages[0].get_images()) == 1
    assert all(not page.get_images() for page in pages[1:])
    assert "date not stated" not in " ".join(page.get_text() for page in pages)


def test_kannada_script_and_talk_of_ocr_are_refused():
    case = verified(new_case_file())
    details = [d.model_dump() for d in written(case).document_details]
    details[0]["text"] = "The local area is stated as ರಾಣಿ ಚನ್ನಮ್ಮ ನಗರ; the holder entry is garbled."
    problems = report_problems(case, written(case, document_details=details))
    assert any("contains Kannada script" in p for p in problems)
    assert any("mentions OCR or garbled text" in p for p in problems)
