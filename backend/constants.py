"""Central constants for document types, pipeline statuses, and step names."""

# ── Document types ──────────────────────────────────────────────────────────

SALE_DEED = "SALE_DEED"
GIFT_DEED = "GIFT_DEED"
ENCUMBRANCE_CERTIFICATE = "ENCUMBRANCE_CERTIFICATE"
RTC_PAHANI = "RTC_PAHANI"
KHATA = "KHATA"
MUTATION = "MUTATION"
PROPERTY_REGISTER_CARD = "PROPERTY_REGISTER_CARD"
PROPERTY_TAX_ASSESSMENT = "PROPERTY_TAX_ASSESSMENT"
E_PAYMENT_RECEIPT = "E_PAYMENT_RECEIPT"
TAX_RECEIPT = "TAX_RECEIPT"
LEGAL_HEIR_CERTIFICATE = "LEGAL_HEIR_CERTIFICATE"
PARTITION_DEED = "PARTITION_DEED"
COURT_ORDER = "COURT_ORDER"
POSSESSION_CERTIFICATE = "POSSESSION_CERTIFICATE"
CONVERSION_ORDER = "CONVERSION_ORDER"
UNKNOWN_DOC = "UNKNOWN"

# ── Pipeline statuses ───────────────────────────────────────────────────────

STATUS_PROCESSING = "processing"
STATUS_PREPROCESSING = "preprocessing"
STATUS_PREPROCESSED = "preprocessed"
STATUS_OCR_IN_PROGRESS = "ocr_in_progress"
STATUS_OCR_DONE = "ocr_done"
STATUS_MERGING = "merging"
STATUS_MERGED = "merged"
STATUS_CLASSIFYING = "classifying"
STATUS_CLASSIFICATION_FAILED = "classification_failed"
STATUS_STRUCTURING = "structuring"
STATUS_STRUCTURED = "structured"
STATUS_FAILED = "failed"
STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_PENDING_RETRY = "pending_retry"

# ── Pipeline step names ─────────────────────────────────────────────────────

STEP_PIPELINE = "pipeline"
STEP_PREPROCESSING = "preprocessing"
STEP_OCR = "ocr"
STEP_MERGE = "merge"
STEP_CLASSIFY = "classify"
STEP_STRUCTURE = "structure"
STEP_DONE = "done"
