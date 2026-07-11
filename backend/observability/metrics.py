from prometheus_client import Counter, Histogram

# Stage latency histogram
STAGE_LATENCY = Histogram(
    "cleartitle_stage_latency_seconds",
    "Latency of a pipeline stage in seconds",
    labelnames=["stage"]
)

# Stage execution failure counter
STAGE_FAILURES = Counter(
    "cleartitle_stage_failures_total",
    "Total number of stage execution failures",
    labelnames=["stage"]
)

# Documents processed successfully counter
DOCS_PROCESSED = Counter(
    "cleartitle_documents_processed_total",
    "Total number of processed documents",
    labelnames=["doc_type"]
)

# Celery queue waiting time histogram
QUEUE_WAIT = Histogram(
    "cleartitle_queue_wait_seconds",
    "Time spent in Celery queue before execution in seconds",
    labelnames=["stage"]
)
