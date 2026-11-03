from backend.integrations.ocr.sarvam_client import _is_insufficient_credits
from backend.workers.stages import OcrInsufficientCredits
from backend.workers.tasks import TASK_RETRY_CONFIG


def test_insufficient_credits_is_detected_case_insensitively():
    assert _is_insufficient_credits(RuntimeError("Insufficient credits. Please add more credits."))
    assert not _is_insufficient_credits(RuntimeError("Temporary network timeout"))


def test_insufficient_credits_is_excluded_from_celery_autoretry():
    assert OcrInsufficientCredits in TASK_RETRY_CONFIG["exclude_from_autoretry"]
