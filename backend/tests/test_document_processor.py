import json
from types import SimpleNamespace

import pytest

from backend.services import document_processor
from backend.services.orchestrator import _resume_stage


def _mock_client(monkeypatch, results, captures=None):
    class FakeCompletions:
        def __init__(self):
            self.index = 0

        def create(self, **kwargs):
            if captures is not None:
                captures.append(kwargs)
            result = results[self.index]
            self.index += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))],
                usage=SimpleNamespace(prompt_tokens=123, completion_tokens=45),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(document_processor, "_client", lambda: client)


def test_classification_uses_truncated_prefix_then_extracts_with_one_schema(monkeypatch):
    ocr = "first part " * 7000
    schema_type = "SALE_DEED"
    schema = document_processor.SCHEMA_MAP[schema_type]
    captures = []
    _mock_client(monkeypatch, [
        {"document_type": schema_type, "is_property_related": True, "needs_user_action": False},
        {"structured_data": schema, "summary": "A sale deed records the transfer of a Bengaluru property from the named sellers to the buyer. It states the sale consideration and registration details."},
    ], captures)

    result = document_processor.classify_and_structure(ocr, 80)

    first_text = captures[0]["messages"][1]["content"]
    second_text = captures[1]["messages"][1]["content"]
    assert len(captures) == 2
    assert "RETRIEVED SCHEMA" not in first_text
    assert ocr[:document_processor.DOCUMENT_CLASSIFICATION_TOKEN_BUDGET * 4] in first_text
    assert len(first_text.split("<document_ocr>\n", 1)[1].split("\n</document_ocr>", 1)[0]) < len(ocr)
    assert "RETRIEVED SCHEMA" in captures[1]["messages"][0]["content"]
    assert json.dumps(schema, ensure_ascii=False) in captures[1]["messages"][0]["content"]
    assert "KNOWN DOCUMENT TYPES" not in second_text
    assert ocr in second_text
    assert result["document_type"] == schema_type
    assert "sale deed" in result["summary"].lower()
    assert result["analytics"]["input_tokens"] == 246


def test_new_property_type_extracts_without_sending_any_schema(monkeypatch):
    monkeypatch.setattr(document_processor, "SCHEMA_MAP", {})
    captures = []
    _mock_client(monkeypatch, [
        {"document_type": "MEMORANDUM_OF_DEPOSIT_OF_TITLE_DEEDS", "is_property_related": True, "needs_user_action": False},
        {"all_information": {"sections": [{"section_name": "details", "fields": [{"label": "bank", "value": "Example Bank"}, {"label": "date", "value": "2025-01-02"}], "records": [], "text_as_written": ""}]}, "summary": "A memorandum records a deposit of property title deeds in favour of Example Bank. It identifies the date and the property-related security."},
    ], captures)

    result = document_processor.classify_and_structure("complete OCR", 1)

    assert result["structured_data"]["all_information"]["sections"][0]["fields"][0]["value"] == "Example Bank"
    assert "RETRIEVED SCHEMA" not in captures[1]["messages"][0]["content"]
    assert "FULL MERGED OCR TEXT" in captures[1]["messages"][1]["content"]
    assert "Exhaustively capture every explicit information item" in captures[1]["messages"][0]["content"]
    assert "do NOT select only facts you consider useful" in captures[1]["messages"][0]["content"]


def test_karnataka_rdpr_form9_is_rule_classified_as_e_swattu(monkeypatch):
    monkeypatch.setattr(document_processor, "_client", lambda: pytest.fail("Form 9 rule should bypass model classification"))

    result = document_processor.classify_document(
        "ಕರ್ನಾಟಕ ಸರ್ಕಾರ ಗ್ರಾಮೀಣ ಅಭಿವೃದ್ಧಿ ಮತ್ತು ಪಂಚಾಯತ್ ರಾಜ್ ಇಲಾಖೆ ನಮೂನೆ - 9 (ನಿಯಮ 28(1)) "
        "ರಶೀದಿ ನಮೂನೆ 3"
    )

    assert result["document_type"] == "E_SWATTU"
    assert result["schema"] == document_processor.SCHEMA_MAP["E_SWATTU"]
    assert result["analytics"]["classification_rule"] == "karnataka_rdpr_form_9"


def test_e_swattu_prompt_extracts_all_form9_data_and_excludes_receipt_form3(monkeypatch):
    captures = []
    schema = document_processor.SCHEMA_MAP["E_SWATTU"]
    _mock_client(monkeypatch, [{
        "structured_data": schema,
        "summary": "This e-Swattu Form 9 records the property and owner details. It includes certificate and jurisdiction information.",
    }], captures)
    document_processor.extract_document(
        "ನಮೂನೆ - 9 owner details ... ರಶೀದಿ ನಮೂನೆ 3 tax receipt ...",
        "E_SWATTU",
        schema,
    )

    prompt = captures[0]["messages"][0]["content"]
    assert "extract every explicit field and every owner/record occurrence" in prompt
    assert "ignore that entire receipt section" in prompt
    assert "Do retain tax-demand/status fields that are actually printed within a Form 9 section" in prompt
    assert "preserve each occurrence under its own form9_records item" in prompt


@pytest.mark.parametrize(("header", "body", "expected"), [
    (
        "ANIL Y. JOSHILKAR Architects Civil Engineers & Contractors\nCOMPLETION CERTIFICATE",
        "Owners Mr A and Mr B. CTS 997, survey 191/4. Fit for Occupancy.",
        "COMPLETION_CERTIFICATE_BY_ARCHITECT",
    ),
    (
        "Gram Panchayat Hindalaga\nCERTIFICATE",
        "This relies on completion certificate issued by Anil Joshilkar. Building is ready for occupation.",
        "COMPLETION_CERTIFICATE_BY_GRAM_PANCHAYAT",
    ),
])
def test_completion_certificate_subtype_uses_issuer_header(monkeypatch, header, body, expected):
    captures = []
    _mock_client(monkeypatch, [{
        "document_type": "COMPLETION_CERTIFICATE",
        "is_property_related": True,
        "needs_user_action": False,
    }], captures)

    result = document_processor.classify_document(header + "\n" + body)

    assert result["document_type"] == expected
    assert result["schema"] == document_processor.SCHEMA_MAP[expected]


@pytest.mark.parametrize("doc_type", [
    "COMPLETION_CERTIFICATE_BY_ARCHITECT",
    "COMPLETION_CERTIFICATE_BY_GRAM_PANCHAYAT",
])
def test_completion_certificate_prompt_extracts_verification_details(monkeypatch, doc_type):
    captures = []
    schema = document_processor.SCHEMA_MAP[doc_type]
    _mock_client(monkeypatch, [{
        "structured_data": schema,
        "summary": "This completion certificate identifies the property and certifies that the building is fit for occupation.",
    }], captures)

    document_processor.extract_document("completion certificate OCR", doc_type, schema)

    prompt = captures[0]["messages"][0]["content"]
    assert "Put the heading's Ref. No./reference number in certificate_details.reference_number" in prompt
    assert "Extract each owner/applicant name and GPA/representative role" in prompt
    assert "all CTS/survey/panchayat/house identifiers" in prompt
    assert "Preserve the complete certificate body as full paragraphs" in prompt
    assert "do not split it into many short paraphrased compliance fragments" in prompt
    assert "do not repeat the same architect as a separate signatory" in prompt
    assert "Use clear schema field names such as name, date, reference_number, and place" in prompt


def test_semantic_schema_lookup_matches_alias_when_present(monkeypatch):
    monkeypatch.setattr(document_processor, "SCHEMA_MAP", {
        "MEMORANDUM_OF_DEPOSIT": {"bank": None, "date": None},
    })
    canonical, schema = document_processor.retrieve_schema("MEMORANDUM_OF_DEPOSIT_OF_TITLE_DEEDS")
    assert canonical == "MEMORANDUM_OF_DEPOSIT"
    assert schema == {"bank": None, "date": None}


def test_ec_extraction_prompt_handles_page_continuations_and_forbids_invention(monkeypatch):
    captures = []
    _mock_client(monkeypatch, [{
        "structured_data": document_processor.SCHEMA_MAP["ENCUMBRANCE_CERTIFICATE"],
        "summary": "The certificate lists registered transactions affecting the described property. It records the transaction parties, dates, and property details where available.",
    }], captures)
    ocr = (
        "Transaction 2 Registration BEL-1-11405-2023-24. "
        "Next page unnumbered continuation: Flat G04, 964 sq.ft.; Vendor Shivaputra Chobari."
    )

    document_processor.extract_document(
        ocr,
        "ENCUMBRANCE_CERTIFICATE",
        document_processor.SCHEMA_MAP["ENCUMBRANCE_CERTIFICATE"],
    )

    system_prompt = captures[0]["messages"][0]["content"]
    user_prompt = captures[0]["messages"][1]["content"]
    assert "A row with an explicit execution date always starts a new transaction" in system_prompt
    assert "A row or fragment with a blank date is not a new transaction" in system_prompt
    assert "append its nonblank cell values to the matching columns of the most recent dated transaction" in system_prompt
    assert "do not overwrite already populated values with blanks" in system_prompt
    assert "Never split a dated transaction into multiple entries" in system_prompt
    assert "read each row across its table columns" in system_prompt
    assert "Do not mistake table header numbers, volume/page numbers, page labels, or a stated entry count" in system_prompt
    assert "including records whose property differs from the certificate's search target" in system_prompt
    assert "populate financial fields only from values explicitly labeled as consideration or market value" in system_prompt
    assert "never repair a suspected OCR error or infer a missing digit" in system_prompt
    assert "Do not invent, infer, complete, correct, normalize, reconcile, or add facts" in system_prompt
    assert "summary as a separate top-level string" in system_prompt
    assert "2-3 concise sentences" in system_prompt
    assert ocr in user_prompt


def test_extraction_requires_a_document_summary(monkeypatch):
    _mock_client(monkeypatch, [{"structured_data": {"document_type": "SALE_DEED"}}])
    with pytest.raises(document_processor.DocumentProcessingError, match="required document summary"):
        document_processor.extract_document(
            "sale deed OCR", "SALE_DEED", document_processor.SCHEMA_MAP["SALE_DEED"]
        )


def test_unrelated_document_requests_user_action_without_extraction(monkeypatch):
    captures = []
    _mock_client(monkeypatch, [{
        "document_type": "RESTAURANT_MENU",
        "is_property_related": False,
        "needs_user_action": True,
        "user_message": "This appears to be a restaurant menu.",
    }], captures)

    with pytest.raises(document_processor.UnsupportedDocumentError, match="restaurant menu") as exc:
        document_processor.classify_and_structure("menu OCR", 1)
    assert exc.value.document_type == "RESTAURANT_MENU"
    assert len(captures) == 1


def test_empty_ocr_fails_without_calling_model(monkeypatch):
    monkeypatch.setattr(document_processor, "_client", lambda: pytest.fail("model client must not be created"))
    with pytest.raises(document_processor.DocumentProcessingError, match="OCR text is empty"):
        document_processor.classify_and_structure(" \n", 0)


@pytest.mark.parametrize(("checkpoint", "expected"), [
    ({"file_paths": {"merged_ocr": "merged.json"}}, "classify"),
    ({"document_type": "SALE_DEED", "file_paths": {"merged_ocr": "merged.json"}}, "structure"),
    ({"document_type": "SALE_DEED", "structured_data": {"x": 1}}, "persist"),
    ({"file_paths": {"raw": "document.pdf"}}, "preprocess"),
])
def test_retry_resumes_from_latest_persisted_checkpoint(checkpoint, expected):
    assert _resume_stage(checkpoint) == expected
