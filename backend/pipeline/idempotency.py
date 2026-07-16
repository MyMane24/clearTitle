import functools
from celery import current_task
from backend.logger import get_logger
from backend.pipeline.stages import Stage, already_past, stage_from_status
from backend.services.mysql_store import get_document_status, set_document_stage, update_document_status
from backend.services.redis_store import append_log
from backend.constants import STATUS_FAILED, STATUS_CLASSIFICATION_FAILED

logger = get_logger(__name__)


def idempotent_stage(entry: Stage, complete: Stage):
    """
    Decorator to make a pipeline stage idempotent.
    Checks MySQL document status and skips execution if the target stage
    is already completed or passed, or if the document has failed.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(case_id: str, doc_id: str, *args, **kwargs):
            current_status = get_document_status(case_id, doc_id)
            
            # If the current status is failed or classification_failed, skip the rest of the chain
            curr_stage = stage_from_status(current_status)
            if curr_stage in (Stage.FAILED, Stage.CLASSIFICATION_FAILED):
                logger.info(
                    "Skipping stage %s for case %s, doc %s because it already failed (status: %s)",
                    func.__name__, case_id, doc_id, current_status
                )
                return {"skipped": True, "status": "failed"}

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
                
                # Check if we should fail permanently or retry
                if current_task:
                    retries = getattr(current_task.request, "retries", 0)
                    max_retries = getattr(current_task, "max_retries", 0)
                    
                    # Check if the exception class name is in exclude_from_autoretry
                    exclude_from_retry = False
                    exclude_list = getattr(current_task, "exclude_from_autoretry", ())
                    if exclude_list:
                        for exc_class in exclude_list:
                            if isinstance(e, exc_class) or e.__class__.__name__ == exc_class.__name__:
                                exclude_from_retry = True
                                break
                    
                    if retries >= max_retries or exclude_from_retry:
                        # Fail permanently!
                        logger.info("Permanent failure in stage %s for case %s, doc %s. Marking as failed.",
                                    func.__name__, case_id, doc_id)
                        
                        status_to_set = STATUS_CLASSIFICATION_FAILED if e.__class__.__name__ == "ClassificationFailed" else STATUS_FAILED
                        
                        try:
                            update_document_status(
                                case_id=case_id,
                                doc_id=doc_id,
                                status=status_to_set,
                                error=str(e)
                            )
                        except Exception as mysql_err:
                            logger.error("Failed to update document status to mysql: %s", mysql_err)
                            
                        try:
                            append_log(case_id, f"[{doc_id}] ✗ Stage {entry.name} failed permanently: {e}")
                        except Exception as redis_err:
                            logger.error("Failed to append log to redis: %s", redis_err)
                            
                        return {"status": "failed", "error": str(e)}
                
                # Re-raise to let Celery retry the task
                raise e

            # Set the stage to complete on success
            logger.info("Successfully completed stage %s for case %s, doc %s (setting stage to %s)",
                        func.__name__, case_id, doc_id, complete.name)
            set_document_stage(case_id, doc_id, complete)
            return result
        return wrapper
    return decorator

