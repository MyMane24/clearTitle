"""Adding documents to an existing case and starting their pipeline.

Shared by the "upload more documents" endpoint and requisition uploads, so a
document from any source goes through exactly the same path.
"""

from __future__ import annotations

from backend.config import PIPELINE_LOCK_ENABLED
from backend.database.repositories.document_repo import init_document
from backend.integrations.document_sources.base import ObtainedFile
from backend.integrations.redis.state_store import (
    add_files_to_case,
    append_log,
    get_case_job,
    set_case_status,
)
from backend.logger import get_logger
from backend.services.orchestrator import start_case_pipeline
from backend.shared.constants import STATUS_FAILED, STATUS_PROCESSING

logger = get_logger(__name__)


class PipelineBusyError(RuntimeError):
    """The case's document pipeline is already processing."""


class PipelineStartError(RuntimeError):
    """The pipeline for the new documents could not be started."""


def reserve_pipeline(case_id: str):
    """Take the case's pipeline lock. ``finalize_case_task`` releases it when done.

    Returns:
        The held lock, or None when locking is disabled.

    Raises:
        PipelineBusyError: Documents are already being processed.
    """
    lock = None
    if PIPELINE_LOCK_ENABLED:
        from backend.integrations.redis.lock import RedisLock

        lock = RedisLock(f"case:{case_id}:pipeline_lock")
        if not lock.acquire():
            raise PipelineBusyError("Document pipeline is already processing")
    if get_case_job(case_id).get("status") == STATUS_PROCESSING:
        release_pipeline(lock)
        raise PipelineBusyError("Document pipeline is already processing")
    return lock


def release_pipeline(lock) -> None:
    if lock is not None:
        lock.release()


def add_files(case_id: str, files: list[ObtainedFile], lock) -> dict:
    """Register saved files as new case documents and start their pipeline.

    Returns:
        ``{case_id, files, total_docs, status}`` where ``files`` lists each new
        document's ``doc_id``, ``original_name``, ``saved_path`` and ``size_kb``.

    Raises:
        PipelineStartError: The pipeline could not be started; the lock is released.
    """
    existing_files = get_case_job(case_id).get("files", [])
    # Next doc_id follows the highest existing number, not the list length:
    # gaps from removed documents must never collide with surviving doc_ids.
    start_idx = max(
        (int(str(f.get("doc_id", "DOC_000")).split("_")[1]) for f in existing_files),
        default=0,
    )
    saved = [
        {
            "doc_id": f"DOC_{str(start_idx + i + 1).zfill(3)}",
            "original_name": item.original_name,
            "saved_path": str(item.path),
            "size_kb": round(item.path.stat().st_size / 1024, 1),
        }
        for i, item in enumerate(files)
    ]
    new_total = start_idx + len(saved)

    try:
        from backend.database.repositories.case_repo import upload_docs_reset

        upload_docs_reset(case_id=case_id, new_total=new_total)
    except Exception as e:
        logger.warning("Failed to update cases total_docs: %s", e)

    try:
        for s in saved:
            init_document(
                case_id=case_id,
                doc_id=s["doc_id"],
                doc_index=int(s["doc_id"].split("_")[1]),
                filename=s["original_name"],
                file_paths={"raw": s["saved_path"]},
            )
    except Exception as e:
        logger.warning("Failed to init documents in MySQL: %s", e)

    add_files_to_case(case_id, saved)
    append_log(case_id, f"Uploaded {len(saved)} additional file(s) — total docs is now {new_total}")

    set_case_status(case_id, STATUS_PROCESSING)
    try:
        start_case_pipeline(case_id)
    except Exception as e:
        release_pipeline(lock)
        set_case_status(case_id, STATUS_FAILED)
        append_log(case_id, f"FATAL: Failed to start uploaded-document pipeline — {e}")
        raise PipelineStartError("Could not process the uploaded document") from e

    return {
        "case_id": case_id,
        "files": saved,
        "total_docs": new_total,
        "status": STATUS_PROCESSING,
    }
