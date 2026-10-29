import unittest

from backend.services.agent_schemas import (
    SCHEMA_VERSION,
    SchemaValidationError,
    normalize_transaction_verification,
    validate_transaction_verification,
)


class TestTransactionVerificationSchema(unittest.TestCase):
    def test_v30_requires_report_and_citation_fields(self):
        self.assertEqual(SCHEMA_VERSION, "3.0")
        valid = {
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "ISSUES_IDENTIFIED",
            "report": "## Problems and gaps\n\nThe deed and later recital name different purchasers [DOC_001 p.2-3].",
            "cited_documents": [{"doc_id": "DOC_001", "pages": "2-3"}],
        }
        result = validate_transaction_verification(valid)
        self.assertEqual(result.cited_documents[0].pages, "2-3")
        self.assertIsNone(result.verified_at)
        with self.assertRaises(SchemaValidationError):
            validate_transaction_verification({
                **valid,
                "findings": [{"description": "Old shape", "source_refs": [{"doc_id": "DOC_001"}]}],
            })
        with self.assertRaises(SchemaValidationError):
            validate_transaction_verification({**valid, "summary": "Old summary field."})
        with self.assertRaises(SchemaValidationError):
            validate_transaction_verification({**valid, "report": "   "})

    def test_dependency_fields_are_rejected_and_legacy_values_are_not_canonicalized(self):
        with self.assertRaises(SchemaValidationError):
            validate_transaction_verification({
                "tx_id": "PA-TC-0002", "sequence": 2, "status": "INCONCLUSIVE",
                "report": "No dependency fields are part of the result contract.",
                "historical_dependencies": [{"origin_tx_id": "PA-TC-0001", "relevance": "Legacy"}],
            })
        legacy = normalize_transaction_verification({
            "tx_id": "PA-TC-0002", "sequence": 2, "status": "INCONCLUSIVE",
            "summary": "Active transaction assessed independently.", "findings": [],
            "historical_dependencies": [{"origin_tx_id": "PA-TC-0001", "relevance": "Legacy"}],
        })
        self.assertNotIn("historical_dependencies", legacy)

    def test_status_timestamp_and_issue_citation_constraints_are_enforced(self):
        with self.assertRaises(SchemaValidationError):
            validate_transaction_verification({
                "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
                "report": "Evidence is outstanding.", "verified_at": "2026-10-22T10:00:00Z",
            })

        with self.assertRaises(SchemaValidationError):
            validate_transaction_verification({
                "tx_id": "PA-TC-0001", "sequence": 1, "status": "ISSUES_IDENTIFIED",
                "report": "A discrepancy exists.", "cited_documents": [],
            })

    def test_duplicate_citations_and_requirements_are_rejected(self):
        with self.assertRaises(SchemaValidationError):
            validate_transaction_verification({
                "tx_id": "PA-TC-0001", "sequence": 1, "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
                "report": "The deed supports the transfer [DOC_001 p.2].",
                "cited_documents": [
                    {"doc_id": "DOC_001", "pages": "2"},
                    {"doc_id": "DOC_001", "pages": "2"},
                ],
                "verified_at": "2026-10-22T10:00:00Z",
            })
        with self.assertRaises(SchemaValidationError):
            validate_transaction_verification({
                "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
                "report": "Evidence is outstanding.",
                "required_documents": [
                    {"document_type": "Original deed", "reason": "Inspect conveyance."},
                    {"document_type": " original deed ", "reason": "Inspect conveyance."},
                ],
            })

    def test_legacy_normalization_preserves_citations_requirements_and_distinct_qualifications(self):
        normalized = normalize_transaction_verification({
            "tx_id": "PA-TC-0001", "sequence": 1, "status": "PENDING_NOT_VERIFIED",
            "schema_version": "2.0", "summary": "The deed recites a transfer.",
            "impact": "The claimed transfer remains unverified.",
            "findings": [{
                "description": "The deed recites the transfer from A to B.",
                "significance": "This is a recital, not inspection of the original deed.",
                "source_refs": [{"doc_id": "DOC_017", "page": "2-3"}],
            }],
            "supporting_evidence": [{"doc_id": "DOC_017", "page": "2-3"}],
            "contradictory_evidence": [{"doc_id": "DOC_018", "page": "1", "passage": "Different purchaser named."}],
            "required_documents": [{"document_type": "Original deed", "reason": "Inspect conveyance."}],
            "missing_documents": [{"document_type": "Original deed", "reason": "Inspect conveyance."}],
            "reviewed_document_ids": ["DOC_017", "DOC_018"],
            "transaction_metadata": {
                "transaction_type": "Sale (EC entry; instrument not supplied)",
                "summary_points": ["duplicate narrative"],
            },
            "unresolved": ["The original instrument was not reviewed."],
            "limitations": ["OCR may contain errors."],
            "verified_at": "2026-10-22T10:00:00Z",
        })
        self.assertEqual(normalized["schema_version"], "3.0")
        self.assertIsNone(normalized["verified_at"])
        self.assertIn("## Conclusion", normalized["report"])
        self.assertIn("The deed recites the transfer from A to B.", normalized["report"])
        self.assertIn("[DOC_017 p.2-3]", normalized["report"])
        self.assertIn("## Material qualifications", normalized["report"])
        self.assertIn("Different purchaser named", normalized["report"])
        self.assertEqual(normalized["cited_documents"], [
            {"doc_id": "DOC_017", "pages": "2-3"},
            {"doc_id": "DOC_018", "pages": "1"},
        ])
        self.assertEqual(normalized["required_documents"], [{
            "document_type": "Original deed", "reason": "Inspect conveyance.", "for_transaction": "PA-TC-0001",
        }])
        self.assertNotIn("summary_points", normalized["transaction_metadata"])
        self.assertEqual(normalized["transaction_metadata"]["transaction_type"], "Sale")

    def test_legacy_issues_identified_without_citations_becomes_inconclusive(self):
        normalized = normalize_transaction_verification({
            "tx_id": "PA-TC-0003", "sequence": 3, "status": "ISSUES_IDENTIFIED",
            "summary": "A discrepancy exists but no citation was retained.",
        })
        self.assertEqual(normalized["status"], "INCONCLUSIVE")
        self.assertIn("schema 3.0", normalized["report"])

    def test_fully_supported_result_may_have_no_citations_or_requirements(self):
        result = validate_transaction_verification({
            "tx_id": "PA-TC-0002", "sequence": 2,
            "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
            "report": "## Conclusion\n\nThe inspected records support this transaction within scope.",
            "cited_documents": [], "required_documents": [],
            "verified_at": "2026-10-22T10:00:00Z",
        })
        self.assertEqual(result.cited_documents, [])
        self.assertEqual(result.required_documents, [])
