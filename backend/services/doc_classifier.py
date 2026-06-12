"""
Document Classifier
Infers document type from filename + first 500 chars of OCR text.
Supports both English and Kannada keywords.
"""

DOC_TYPE_KEYWORDS = {
    "E_PAYMENT_RECEIPT": [
        "e-payment receipt details",
        "payment receipt details",
        "e-payment receipt details for pid",
        "city corporation belagavi",
        "consumer details",
        "transaction details",
        "service details",
        "payment ref no",
        "receipt date",
        "amount paid",
        "sas no",
    ],
    "PROPERTY_TAX_ASSESSMENT": [
        "belagavi mahanagara palike",
        "property type: assessed",
        "property type",
        "old assessment no",
        "new assessment no",
        "assessment year",
        "hdfc online payment",
        "form2 issued by",
        "valid for the month",
        "swm service charges",
        "plinth factor",
        "total payable",
        "pid",
    ],
    "PROPERTY_REGISTER_CARD": [
        "extract from the property register card",
        "property register card",
        "city survey office",
        "city survey no",
        "city survey number",
        "p.t. sheet no",
        "pt sheet no",
        "name of the holder",
        "new holder",
        "lessee",
        "copy applied by",
    ],
    "SALE_DEED": [
        "deed of sale", "sale deed", "seller", "purchaser", "consideration",
        "vendors", "builder", "developers",
        "ಮಾರಾಟ ಪತ್ರ", "ಮಾರಾಟದ ದಾಖಲೆ",
    ],
    "ENCUMBRANCE_CERTIFICATE": [
        "encumbrance", "encumbrances", "form 15", "form no.15",
        "ec certificate", "historical ledger",
        "ಋಣಭಾರ", "ನಮೂನೆ ೧೫", "ನಮೂನೆ 15", "ಸಮನ್ವಯ",
    ],
    "RTC_PAHANI": [
        "rtc", "pahani", "hissa", "cultivator", "kharab",
        "ಆರ್.ಟಿ.ಸಿ", "ಪಹಣಿ", "ಹಿಸ್ಸಾ", "ಆರ್‌ಟಿಸಿ",
    ],
    "KHATA": [
        "khata", "katha", "khatha", "a-khata", "b-khata",
        "ಖಾತಾ", "ಖಾತೆ",
    ],
    "MUTATION": [
        "mutation", "name change", "transfer of ownership",
        "ಮ್ಯುಟೇಶನ್", "ನಾಮಾಂತರ",
    ],
    "TAX_RECEIPT": [
        "property tax", "tax receipt", "cess", "municipal tax",
        "ಆಸ್ತಿ ತೆರಿಗೆ",
    ],
    "LEGAL_HEIR_CERTIFICATE": [
        "legal heir", "succession", "heirship certificate",
        "ಕಾನೂನು ವಾರಸುದಾರ",
    ],
    "PARTITION_DEED": [
        "partition deed", "partition", "ಪಾಲು ಪತ್ರ",
    ],
    "GIFT_DEED": [
        "gift deed", "gifted", "ದಾನ ಪತ್ರ",
    ],
    "COURT_ORDER": [
        "court order", "decree", "hon'ble court", "ನ್ಯಾಯಾಲಯ",
    ],
    "POSSESSION_CERTIFICATE": [
        "possession certificate", "actual possession",
    ],
    "CONVERSION_ORDER": [
        "conversion order", "non-agricultural", "non agri",
        "converted to na", "rb.lna",
    ],
}

# Filename-level quick matches (checked before content)
FILENAME_PATTERNS = {
    "propertyregistercard": "PROPERTY_REGISTER_CARD",
    "prcard":        "PROPERTY_REGISTER_CARD",
    "citysurvey":    "PROPERTY_REGISTER_CARD",
    "paymentreceipt": "E_PAYMENT_RECEIPT",
    "receipt":       "E_PAYMENT_RECEIPT",
    "epayment":      "E_PAYMENT_RECEIPT",
    "propertytaxassessment": "PROPERTY_TAX_ASSESSMENT",
    "taxassessment": "PROPERTY_TAX_ASSESSMENT",
    "assessment":    "PROPERTY_TAX_ASSESSMENT",
    "tax":           "TAX_RECEIPT",
    "ec":            "ENCUMBRANCE_CERTIFICATE",
    "encumbrance":   "ENCUMBRANCE_CERTIFICATE",
    "sale":          "SALE_DEED",
    "deed":          "SALE_DEED",
    "saledeed":      "SALE_DEED",
    "rtc":           "RTC_PAHANI",
    "pahani":        "RTC_PAHANI",
    "khata":         "KHATA",
    "mutation":      "MUTATION",
    "legalheir":     "LEGAL_HEIR_CERTIFICATE",
    "heir":          "LEGAL_HEIR_CERTIFICATE",
    "partition":     "PARTITION_DEED",
    "gift":          "GIFT_DEED",
    "court":         "COURT_ORDER",
    "possession":    "POSSESSION_CERTIFICATE",
    "conversion":    "CONVERSION_ORDER",
}


def classify_document(filename: str, sample_text: str = "") -> str:
    """
    Returns a document type string like 'SALE_DEED', 'ENCUMBRANCE_CERTIFICATE', etc.
    Falls back to 'UNKNOWN' if no match found.
    """
    fname_lower = filename.lower().replace(" ", "").replace("_", "").replace("-", "")

    # 1. Filename quick check
    for pattern, doc_type in FILENAME_PATTERNS.items():
        if pattern in fname_lower:
            return doc_type

    # 2. Content keyword check
    combined = (filename + " " + sample_text).lower()
    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        if any(kw.lower() in combined for kw in keywords):
            return doc_type

    return "UNKNOWN"
