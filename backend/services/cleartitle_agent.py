"""Title-chain construction for a case (Phase A).

The chain is built from the property's history documents, extended through its
title deeds, and rebuilt when a history document or deed the saved chain did not
use arrives. Nothing after the chain is built runs here: transaction verification
and reports are not part of this application.
"""

from __future__ import annotations

from backend.config import PIPELINE_LOCK_ENABLED
from backend.database.repositories import agent_repo as repo
from backend.integrations.llm.agent_llm import complete_json
from backend.integrations.redis.lock import RedisLock
from backend.logger import get_logger
from backend.prompts.loader import load_prompt
from backend.services.chain_builder import build_chain, history_documents, title_deeds

logger = get_logger(__name__)

STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_DONE = "done"
STATUS_ERROR = "error"

HISTORY_DOCUMENT_REQUEST = (
    "Upload the Encumbrance Certificate for this property. The title chain is built "
    "from the property's history records (encumbrance certificate, mutation or RTC), "
    "and none has been uploaded yet."
)


# -- document summaries (cheap navigation aid, generated only when missing) ----


def ensure_summaries(case_id: str, docs: list[dict]) -> None:
    for doc in docs:
        if doc.get("summary"):
            continue
        text = repo.get_document_raw_text(case_id, doc["doc_id"])
        label = doc.get("document_type") or "UNKNOWN"
        if not text:
            summary = f"{label}: (no OCR text available)"
        else:
            prompt = (
                load_prompt("agent_summary")
                + f"\n\nDOCUMENT TYPE: {label}"
                + f"\nFILENAME: {doc.get('filename') or ''}"
                + f"\n\n--- DOCUMENT CONTENT ---\n{text[:6000]}"
            )
            try:
                out = complete_json(prompt, task="agent_summary")
                summary = str(out.get("summary") or "").strip()
            except Exception as e:  # a summary failure must not kill the run
                logger.warning("summary failed for %s/%s: %s", case_id, doc["doc_id"], e)
                summary = f"{label}: (summary unavailable)"
        if not summary:
            summary = f"{label}: (summary unavailable)"
        repo.set_document_summary(case_id=case_id, doc_id=doc["doc_id"], summary=summary)
        doc["summary"] = summary


def _has_new_chain_documents(phase_a: dict, docs: list[dict]) -> bool:
    """True when a history document or title deed arrived after the chain was built.

    A chain saved before its source documents were recorded carries ``None``
    and is never rebuilt automatically.
    """
    used = phase_a.get("chain_doc_ids")
    if used is None:
        return False
    return any(
        document["doc_id"] not in used
        for document in [*history_documents(docs), *title_deeds(docs)]
    )


# -- run -----------------------------------------------------------------------


def run_case_analysis(case_id: str, *, force: bool = False) -> dict:
    """Build or reuse the case's title chain under the case lock."""
    lock = None
    if PIPELINE_LOCK_ENABLED:
        try:
            lock = RedisLock(f"case:{case_id}:agent_lock")
            if not lock.acquire():
                logger.info("chain build already running for case %s", case_id)
                return {"case_id": case_id, "status": "busy"}
        except Exception as e:  # degrade to no-lock rather than fail
            logger.warning("agent lock unavailable for %s: %s", case_id, e)
            lock = None
    try:
        return _run(case_id, force=force)
    finally:
        if lock is not None:
            lock.release()


def _run(case_id: str, *, force: bool = False) -> dict:
    docs = repo.get_agent_documents(case_id)
    if not docs:
        repo.set_agent_status(case_id=case_id, status=STATUS_ERROR)
        return {"case_id": case_id, "status": STATUS_ERROR, "reason": "no documents"}
    try:
        repo.set_agent_status(case_id=case_id, status=STATUS_RUNNING)
        saved = repo.get_agent_result(case_id)
        if force or not saved or not saved.get("title_chain"):
            if not history_documents(docs):
                repo.set_agent_status(case_id=case_id, status=STATUS_PAUSED)
                logger.info("case %s paused: no history documents", case_id)
                return {
                    "case_id": case_id,
                    "status": STATUS_PAUSED,
                    "missing_documents": [{
                        "document_type": "Encumbrance Certificate",
                        "reason": "No history record of the property has been uploaded.",
                        "for_transaction": "",
                    }],
                }
            ensure_summaries(case_id, docs)
            saved = build_chain(case_id, docs)
        elif _has_new_chain_documents(saved, docs):
            ensure_summaries(case_id, docs)
            saved = build_chain(case_id, docs)
        repo.set_agent_status(case_id=case_id, status=STATUS_DONE)
        links = len(saved.get("title_chain") or [])
        logger.info("title chain ready for %s: %s links", case_id, links)
        return {"case_id": case_id, "status": STATUS_DONE, "links": links}
    except Exception as e:  # record failure, don't crash the worker
        logger.exception("title chain failed for %s: %s", case_id, e)
        repo.set_agent_status(case_id=case_id, status=STATUS_ERROR)
        return {"case_id": case_id, "status": STATUS_ERROR, "error": str(e)}
