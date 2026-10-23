from unittest.mock import patch

from backend.services.results import _agent_block, _transaction_for_api, classification_action_message


def test_paused_checkpoint_exposes_transaction_id_and_canonical_requirements():
    with patch("backend.database.repositories.agent_repo.get_agent_state", return_value={
        "status": "paused",
        "memory": {
            "case_id": "CASE1", "current_tx_id": "PA-TC-0001",
            "current_stage": "paused", "status": "PENDING_NOT_VERIFIED",
            "result_ref": "PA-TC-0001",
        },
        "result": {"title_chain": []},
        "case_result": [{
            "tx_id": "PA-TC-0001", "sequence": 1,
            "status": "PENDING_NOT_VERIFIED",
            "required_documents": [{"document_type": "Sale deed", "reason": "Verify conveyance"}],
        }],
    }):
        agent = _agent_block("CASE1")

    assert agent["paused_transaction"] == "PA-TC-0001"
    assert agent["stage"] == "paused"
    assert "missing_documents" not in agent
    assert agent["transactions"][0]["required_documents"][0]["document_type"] == "Sale deed"


def test_legacy_transaction_result_is_normalized_without_losing_distinct_values():
    adapted = _transaction_for_api({
        "tx_id": "PA-TC-0001", "status": "PENDING_NOT_VERIFIED",
        "conclusion": "Legacy summary A", "summary": "Legacy summary B",
        "missing_documents": [{"document_type": "Deed", "reason": "Verify transfer"}],
        "required_documents": [], "findings": [], "reviewed_document_ids": ["DOC_001"],
    })
    assert "Legacy summary A" in adapted["summary"]
    assert "Legacy summary B" in adapted["summary"]
    assert adapted["required_documents"][0]["document_type"] == "Deed"
    assert adapted["schema_version"] == "2.1"
    assert adapted["reviewed_document_ids"] == ["DOC_001"]


def test_paused_requirements_are_derived_from_the_paused_persisted_transaction():
    with patch("backend.database.repositories.agent_repo.get_agent_state", return_value={
        "status": "paused",
        "memory": {"current_tx_id": "PA-TC-0002", "current_stage": "paused", "status": "PENDING_NOT_VERIFIED"},
        "result": {},
        "case_result": [
            {"tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED", "summary": "One", "required_documents": [{"document_type": "Deed 1"}]},
            {"tx_id": "PA-TC-0002", "sequence": 2, "status": "PENDING_NOT_VERIFIED", "summary": "Two", "required_documents": [{"document_type": "Death record"}]},
        ],
    }):
        agent = _agent_block("CASE1")

    assert agent["paused_transaction"] == "PA-TC-0002"
    assert "missing_documents" not in agent
    paused = next(tx for tx in agent["transactions"] if tx["tx_id"] == agent["paused_transaction"])
    assert [item["document_type"] for item in paused["required_documents"]] == ["Death record"]


def test_one_verified_transaction_does_not_mark_the_entire_chain_verified():
    with patch("backend.database.repositories.agent_repo.get_agent_state", return_value={
        "status": "done", "memory": {}, "result": {},
        "case_result": [
            {"tx_id": "PA-TC-0001", "sequence": 1, "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE", "summary": "First link supported."},
            {"tx_id": "PA-TC-0002", "sequence": 2, "status": "PENDING_NOT_VERIFIED", "summary": "Second link remains open."},
        ],
    }):
        agent = _agent_block("CASE1")

    assert agent["transactions"][0]["status"] == "VERIFIED_WITH_AVAILABLE_EVIDENCE"
    assert agent["transactions"][1]["status"] == "PENDING_NOT_VERIFIED"
    assert agent["overall_status"] != "VERIFIED_WITH_AVAILABLE_EVIDENCE"


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
