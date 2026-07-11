import logging
import sys
from pythonjsonlogger import jsonlogger

def configure_json_logging():
    # Configure root logger to output JSON structured logs
    logHandler = logging.StreamHandler(sys.stdout)
    # Log format with all required metadata fields
    formatter = jsonlogger.JsonFormatter(
        fmt='%(asctime)s %(levelname)s %(name)s %(message)s %(case_id)s %(doc_id)s %(task_name)s %(stage)s %(worker)s %(duration_ms)s %(status)s %(error)s %(retry_count)s',
        rename_fields={"levelname": "severity", "asctime": "timestamp"}
    )
    logHandler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    # remove existing handlers
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(logHandler)
    root_logger.setLevel(logging.INFO)

def get_structured_logger(name: str):
    return logging.getLogger(name)
