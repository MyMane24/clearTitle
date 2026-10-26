from backend.workers.finalize import _should_start_agent


def test_finalizer_starts_agent_after_any_document_is_structured():
    assert _should_start_agent(
        [{"doc_id": "DOC_001", "status": "structured"}],
        {},
    )


def test_finalizer_resumes_a_pending_verification_after_document_processing():
    assert _should_start_agent(
        [{"doc_id": "DOC_001", "status": "failed"}],
        {"paused_transaction": "PA-TC-0001"},
    )


def test_finalizer_does_not_start_agent_without_structured_or_pending_work():
    assert not _should_start_agent(
        [{"doc_id": "DOC_001", "status": "classification_failed"}],
        {},
    )
