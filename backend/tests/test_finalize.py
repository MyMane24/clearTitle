from backend.workers.finalize import _should_build_chain


def test_finalizer_builds_chain_after_any_document_is_structured():
    assert _should_build_chain([{"doc_id": "DOC_001", "status": "structured"}])


def test_finalizer_skips_chain_without_structured_documents():
    assert not _should_build_chain([{"doc_id": "DOC_001", "status": "classification_failed"}])
