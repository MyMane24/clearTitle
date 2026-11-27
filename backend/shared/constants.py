"""Central constants for document types and pipeline statuses.

Extracted verbatim from `backend/constants.py`.
"""

# -- Document types ----------------------------------------------------------

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
PARTITION_DEED = "PARTITION_DEED"
CONVERSION_ORDER = "CONVERSION_ORDER"
CDP_PLAN = "CDP_PLAN"
RERA_CERTIFICATE = "RERA_CERTIFICATE"
LITIGATION_AFFIDAVIT = "LITIGATION_AFFIDAVIT"
ALLOTMENT_LETTER = "ALLOTMENT_LETTER"
BUILDING_LICENSE = "BUILDING_LICENSE"
COMPLETION_CERTIFICATE = "COMPLETION_CERTIFICATE"

# History documents: records that list a property's past transfers. They give
# the backbone of the title chain. Property register cards are left out on
# purpose: their OCR is unreliable, and the deeds supply what they would add.
CHAIN_HISTORY_DOC_TYPES = frozenset({
    ENCUMBRANCE_CERTIFICATE,
    MUTATION,
    RTC_PAHANI,
})

# Title deeds: the instruments that transfer ownership. The chain builder opens
# one only to extend the chain backward or to confirm a link. Any type ending in
# "_DEED" counts, plus these.
CHAIN_DEED_DOC_TYPES = frozenset({"WILL", "COURT_DECREE"})

# -- Pipeline statuses -------------------------------------------------------

STATUS_PROCESSING = "processing"
STATUS_PREPROCESSED = "preprocessed"
STATUS_OCR_DONE = "ocr_done"
STATUS_MERGED = "merged"
STATUS_CLASSIFICATION_FAILED = "classification_failed"
STATUS_STRUCTURED = "structured"
STATUS_FAILED = "failed"
STATUS_PENDING_RETRY = "pending_retry"
