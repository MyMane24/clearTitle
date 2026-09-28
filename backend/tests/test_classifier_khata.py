"""Self-check for the document classifier khata-extract fixes.

Runs with stdlib unittest only:
    python -m unittest backend.tests.test_classifier_khata -v
"""

from __future__ import annotations

import unittest

from backend.services.classifier import KHATA, PROPERTY_TAX_ASSESSMENT, classify_document

# OCR of the real Belagavi Nomune-2 (Form 2) Khata Extract that was
# previously misclassified as PROPERTY_TAX_ASSESSMENT via the generic 'pid'.
NOMUNE_2_SAMPLE = (
    "ನಮೂನೆ-2\n"
    "Acknowledgement/Extract\n"
    "(See rule II)\n"
    "ಕರ್ನಾಟಕ ಸರ್ಕಾರ ಪೌರಾಡಳಿತ ನಿರ್ದೇಶನಾಲಯ\n"
    "ಮಹಾನಗರ ಪಾಲಿಕೆ, ಬೆಳಗಾವಿ ನಮೂನೆ-2 (ನಿಯಮ 20)\n"
    "ಸ್ವತ್ತಿನ ಸಂಖ್ಯೆ 5047089563 ವಾರ್ಡ್ 2 PID NO 116057\n"
    "ಸ್ವತ್ತಿನ ವರ್ಗಿಕರಣ (as per A Register) ಅಧಿಕೃತ\n"
    "PLOT NO. 09,CTS NO. 1360B/9 RS NO. 699A/15,RANI CHENNAMMA NAGAR\n"
    "ಮಾಲೀಕರ ಹೆಸರು ನಾರಾಯಣ ಅವಚಾರಿ ಬಿನ್ S/O: ರಾಮು ಅವಚಾರಿ\n"
    "ಪೂಜಾ ಅವಚಾರಿ ಕೊಂ W/O: ನಾರಾಯಣ ಅವಚಾರಿ"
)


class ClassifierKhataTest(unittest.TestCase):
    def test_nomune_2_extract_classifies_as_khata(self):
        self.assertEqual(
            classify_document("5047089563.pdf", NOMUNE_2_SAMPLE), KHATA
        )

    def test_plain_tax_assessment_still_classifies_as_tax(self):
        # A real property-tax dues page (no Nomune heading) must not become KHATA.
        tax_sample = (
            "Property Type: Assessed\n"
            "Assessment Year: 2026-27\n"
            "SAS NO: 12345 New Assessment No: PID NO 116057\n"
            "Total Payable: Rs. 5000 SWM Service Charges: Rs. 100\n"
            "Valid for the month: July"
        )
        self.assertEqual(
            classify_document("assessment.pdf", tax_sample),
            PROPERTY_TAX_ASSESSMENT,
        )


if __name__ == "__main__":
    unittest.main()
