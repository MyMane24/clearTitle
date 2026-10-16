from backend.services.results import classification_action_message


def test_classification_action_message_explains_why_and_offers_next_step():
    message = classification_action_message({
        "document_type": "FIRM_REGISTRATION_CERTIFICATE",
        "error": "This document registers a business and does not provide property or title information.",
    })

    assert "registers a business" in message
    assert "property or title information" in message
    assert "Replace it with a property document" in message
    assert "continue without it" in message


def test_classification_action_message_has_clear_fallback():
    message = classification_action_message({"document_type": "UNRELATED_RECORD"})

    assert "unrelated record" in message
    assert "not a property or title document" in message
