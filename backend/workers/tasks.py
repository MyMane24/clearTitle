"""6 per-document pipeline stage tasks.

Tasks are thin Celery wrappers: retry/idempotency decorators plus a `run_stage`
adapter call. Stage logic lives in `backend.workers.stages`.
"""

from __future__ import annotations

from backend.celery_app import celery_app
from backend.domain.state_machine import Stage
from backend.logger import get_logger
from backend.workers.idempotency import idempotent_stage
from backend.workers.stage_adapter import run_stage
from backend.workers.stages import (
    ClassificationFailed,
    ClassifyStage,
    MergeStage,
    OcrStage,
    PersistStage,
    PreprocessStage,
    StructureStage,
)

logger = get_logger(__name__)


# Autoretry config for tasks
TASK_RETRY_CONFIG = {
    "autoretry_for": (Exception,),
    "exclude_from_autoretry": (ClassificationFailed,),
    "retry_backoff": True,
    "retry_backoff_max": 120,
    "retry_jitter": True,
    "max_retries": 5,
    "acks_late": True,
}


@celery_app.task(**TASK_RETRY_CONFIG)
@idempotent_stage(Stage.PREPROCESSING, Stage.PREPROCESSED)
def preprocess_document_task(case_id: str, doc_id: str):
    return run_stage(PreprocessStage(), task_name="preprocess", case_id=case_id, doc_id=doc_id)


@celery_app.task(**TASK_RETRY_CONFIG)
@idempotent_stage(Stage.OCR_IN_PROGRESS, Stage.OCR_DONE)
def ocr_document_task(case_id: str, doc_id: str):
    return run_stage(OcrStage(), task_name="ocr", case_id=case_id, doc_id=doc_id)


@celery_app.task(**TASK_RETRY_CONFIG)
@idempotent_stage(Stage.MERGING, Stage.MERGED)
def merge_ocr_task(case_id: str, doc_id: str):
    return run_stage(MergeStage(), task_name="merge", case_id=case_id, doc_id=doc_id)


@celery_app.task(**TASK_RETRY_CONFIG)
@idempotent_stage(Stage.CLASSIFYING, Stage.CLASSIFIED)
def classify_document_task(case_id: str, doc_id: str):
    return run_stage(ClassifyStage(), task_name="classify", case_id=case_id, doc_id=doc_id)


@celery_app.task(**TASK_RETRY_CONFIG)
@idempotent_stage(Stage.STRUCTURING, Stage.STRUCTURING_DONE)
def structure_document_task(case_id: str, doc_id: str):
    return run_stage(StructureStage(), task_name="structure", case_id=case_id, doc_id=doc_id)


@celery_app.task(**TASK_RETRY_CONFIG)
@idempotent_stage(Stage.PERSISTING, Stage.STRUCTURED)
def persist_document_task(case_id: str, doc_id: str):
    return run_stage(PersistStage(), task_name="persist", case_id=case_id, doc_id=doc_id)
