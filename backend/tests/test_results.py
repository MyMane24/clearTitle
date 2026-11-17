from unittest.mock import patch

from backend.services.results import _agent_block, classification_action_message

REPO = "backend.database.repositories.agent_repo"


def test_paused_without_a_chain_asks_for_the_encumbrance_certificate():
    with patch(f"{REPO}.get_agent_status", return_value="paused"), \
            patch(f"{REPO}.get_agent_result", return_value=None):
        agent = _agent_block("CASE1")

    assert agent["status"] == "paused"
    assert "Encumbrance Certificate" in agent["next_action"]
    assert agent["title_chain"] == []


def test_built_chain_is_returned_without_a_next_action():
    chain = [{"tx_id": "PA-TC-0001", "documented_transaction": {"transaction_type": "Sale"}}]
    with patch(f"{REPO}.get_agent_status", return_value="done"), \
            patch(f"{REPO}.get_agent_result",
                  return_value={"title_chain": chain, "property_identity": {"details": []}}):
        agent = _agent_block("CASE1")

    assert agent["status"] == "done"
    assert agent["next_action"] is None
    assert agent["title_chain"] == chain


def test_chain_is_exposed_even_before_a_status_is_recorded():
    chain = [{"tx_id": "PA-TC-0001", "documented_transaction": {"transaction_type": "Sale"}}]
    with patch(f"{REPO}.get_agent_status", return_value=None), \
            patch(f"{REPO}.get_agent_result", return_value={"title_chain": chain}):
        agent = _agent_block("CASE1")

    assert agent["status"] == "done"
    assert agent["next_action"] is None


def test_classification_action_message_explains_why_and_offers_next_step():
    message = classification_action_message({
        "document_type": "FIRM_REGISTRATION_CERTIFICATE",
        "error": "This document registers a business, not property or title information.",
    })

    assert "registers a business" in message
    assert "property or title information" in message
    assert "Replace it with a property document" in message
    assert "continue without it" in message


def test_classification_action_message_has_clear_fallback():
    message = classification_action_message({"document_type": "UNRELATED_RECORD"})

    assert "unrelated record" in message
    assert "not a property or title document" in message
