import functools
from backend.logger import get_logger
from backend.pipeline.stages import Stage, already_past
from backend.services.mysql_store import get_document_status, set_document_stage

logger = get_logger(__name__)


def idempotent_stage(entry: Stage, complete: Stage):
    """
    Decorator to make a pipeline stage idempotent.
    Checks MySQL document status and skips execution if the target stage
    is already completed or passed.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(case_id: str, doc_id: str, *args, **kwargs):
            current_status = get_document_status(case_id, doc_id)
            
            # If the current status is already past or equal to the complete stage, skip
            if current_status and already_past(current_status, complete):
                logger.info(
                    "Skipping stage %s for case %s, doc %s (current status: %s is past complete: %s)",
                    func.__name__, case_id, doc_id, current_status, complete.name
                )
                return {"skipped": True}

            # Set the stage to the entry stage before executing
            logger.info("Entering stage %s for case %s, doc %s (setting stage to %s)",
                        func.__name__, case_id, doc_id, entry.name)
            set_document_stage(case_id, doc_id, entry)

            try:
                result = func(case_id, doc_id, *args, **kwargs)
            except Exception as e:
                logger.error("Exception in stage %s for case %s, doc %s: %s",
                             func.__name__, case_id, doc_id, str(e))
                # Note: We do not set the complete stage on failure.
                # The exception is re-raised so Celery or callers can handle retry.
                raise e

            # Set the stage to complete on success
            logger.info("Successfully completed stage %s for case %s, doc %s (setting stage to %s)",
                        func.__name__, case_id, doc_id, complete.name)
            set_document_stage(case_id, doc_id, complete)
            return result
        return wrapper
    return decorator
