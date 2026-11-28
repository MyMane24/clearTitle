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


def test_classification_reads_only_a_prefix_and_returns_a_summary_in_one_call(monkeypatch):
    ocr = "first part " * 7000
    captures = []
    _mock_client(monkeypatch, [{
        "document_type": "SALE_DEED",
        "is_property_related": True,
        "needs_user_action": False,
        "summary": "A sale deed transfers a Belagavi plot from the sellers to the buyer.",
    }], captures)

    result = document_processor.classify_document(ocr)

    assert len(captures) == 1  # no second, full-document call
    prompt = captures[0]["messages"][1]["content"]
    assert ocr[:document_processor.DOCUMENT_CLASSIFICATION_TOKEN_BUDGET * 4] in prompt
    assert len(prompt.split("<document_ocr>\n", 1)[1].split("\n</document_ocr>", 1)[0]) < len(ocr)
    assert "summary" in captures[0]["messages"][0]["content"]
    assert result["document_type"] == "SALE_DEED"
    assert result["summary"].startswith("A sale deed transfers")
    assert result["analytics"]["input_tokens"] == 123


def test_missing_summary_does_not_fail_classification(monkeypatch):
    _mock_client(monkeypatch, [{
        "document_type": "SALE_DEED", "is_property_related": True, "needs_user_action": False,
    }])
    assert document_processor.classify_document("sale deed OCR")["summary"] is None


def test_karnataka_rdpr_form9_is_rule_classified_as_e_swattu(monkeypatch):
    monkeypatch.setattr(document_processor, "_client", lambda: pytest.fail("Form 9 rule should bypass model classification"))

    result = document_processor.classify_document(
        "ಕರ್ನಾಟಕ ಸರ್ಕಾರ ಗ್ರಾಮೀಣ ಅಭಿವೃದ್ಧಿ ಮತ್ತು ಪಂಚಾಯತ್ ರಾಜ್ ಇಲಾಖೆ ನಮೂನೆ - 9 (ನಿಯಮ 28(1)) "
        "ರಶೀದಿ ನಮೂನೆ 3"
    )

    assert result["document_type"] == "E_SWATTU"
    assert result["summary"] is None  # filled later from the text when the chain needs it
    assert result["analytics"]["classification_rule"] == "karnataka_rdpr_form_9"


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
    _mock_client(monkeypatch, [{
        "document_type": "COMPLETION_CERTIFICATE",
        "is_property_related": True,
        "needs_user_action": False,
    }])

    result = document_processor.classify_document(header + "\n" + body)

    assert result["document_type"] == expected


def test_canonical_type_matches_a_longer_alias(monkeypatch):
    monkeypatch.setattr(document_processor, "DOCUMENT_TYPES", frozenset({"MEMORANDUM_OF_DEPOSIT"}))
    canonical = document_processor.canonical_document_type("MEMORANDUM_OF_DEPOSIT_OF_TITLE_DEEDS")
    assert canonical == "MEMORANDUM_OF_DEPOSIT"


def test_unrelated_document_requests_user_action(monkeypatch):
    captures = []
    _mock_client(monkeypatch, [{
        "document_type": "RESTAURANT_MENU",
        "is_property_related": False,
        "needs_user_action": True,
        "user_message": "This appears to be a restaurant menu.",
    }], captures)

    with pytest.raises(document_processor.UnsupportedDocumentError, match="restaurant menu") as exc:
        document_processor.classify_document("menu OCR")
    assert exc.value.document_type == "RESTAURANT_MENU"
    assert len(captures) == 1


def test_model_call_failure_names_the_provider(monkeypatch):
    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("Error code: 401 - Your API key has expired.")

    monkeypatch.setattr(
        document_processor,
        "_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions())),
    )
    with pytest.raises(document_processor.DocumentProcessingError, match="OpenAI: Error code: 401"):
        document_processor.classify_document("sale deed OCR")


def test_empty_ocr_fails_without_calling_model(monkeypatch):
    monkeypatch.setattr(document_processor, "_client", lambda: pytest.fail("model client must not be created"))
    with pytest.raises(document_processor.DocumentProcessingError, match="OCR text is empty"):
        document_processor.classify_document(" \n")


@pytest.mark.parametrize(("checkpoint", "expected"), [
    ({"file_paths": {"merged_ocr": "merged.json"}}, "classify"),
    ({"document_type": "SALE_DEED", "file_paths": {"merged_ocr": "merged.json"}}, "persist"),
    ({"document_type": "SALE_DEED", "merged_ocr_text": "text"}, "persist"),
    ({"file_paths": {"raw": "document.pdf"}}, "preprocess"),
])
def test_retry_resumes_from_latest_persisted_checkpoint(checkpoint, expected):
    assert _resume_stage(checkpoint) == expected
