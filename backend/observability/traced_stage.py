import time
import functools
from contextlib import contextmanager
from opentelemetry import trace
from backend.observability.metrics import STAGE_LATENCY, STAGE_FAILURES
from backend.observability.logging import get_structured_logger
from backend.services.mysql_store import _get_conn

logger = get_structured_logger("pipeline.observability")

@contextmanager
def traced_stage_ctx(stage_name: str, case_id: str, doc_id: str):
    tracer = trace.get_tracer("cleartitle")
    start_time = time.time()
    status = "success"
    error_msg = ""
    trace_id = None
    
    with tracer.start_as_current_span(
        f"pipeline.{stage_name}",
        attributes={"case_id": case_id, "doc_id": doc_id}
    ) as span:
        try:
            span_context = span.get_span_context()
            if span_context and span_context.is_valid:
                trace_id = format(span_context.trace_id, '032x')
                if trace_id:
                    with _get_conn() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE documents SET trace_id = %s WHERE case_id = %s AND doc_id = %s",
                            (trace_id, case_id, doc_id)
                        )
                        conn.commit()
        except Exception:
            pass
            
        try:
            yield span
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            STAGE_FAILURES.labels(stage=stage_name).inc()
            raise e
        finally:
            duration = time.time() - start_time
            STAGE_LATENCY.labels(stage=stage_name).observe(duration)
            
            # JSON Log output
            logger.info(
                f"Completed stage {stage_name} for case {case_id}, doc {doc_id}",
                extra={
                    "case_id": case_id,
                    "doc_id": doc_id,
                    "stage": stage_name,
                    "duration_ms": int(duration * 1000),
                    "status": status,
                    "error": error_msg,
                    "trace_id": trace_id
                }
            )

def traced_stage(stage_name: str):
    """
    Decorator to wrap a function inside a traced stage context.
    The function signature must start with (case_id: str, doc_id: str).
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(case_id: str, doc_id: str, *args, **kwargs):
            with traced_stage_ctx(stage_name, case_id, doc_id):
                return func(case_id, doc_id, *args, **kwargs)
        return wrapper
    return decorator
