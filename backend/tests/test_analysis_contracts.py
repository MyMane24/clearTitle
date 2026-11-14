"""Stage 1: canonical analysis-layer contract tests (backend/schemas/analysis.py)."""

import unittest

from pydantic import ValidationError

from backend.schemas import analysis as A


REF = {"doc_id": "DOC_001"}


class TestPrimitives(unittest.TestCase):
    def test_provenance_defaults_to_contract_version(self):
        self.assertEqual(A.Provenance().contract_version, "1.0")

    def test_evidence_reference_requires_doc_id(self):
        with self.assertRaises(ValidationError):
            A.DocumentEvidenceReference(doc_id="   ")

    def test_property_identity_requires_one_sourced_detail(self):
        with self.assertRaises(ValidationError):
            A.PropertyIdentity(details=[])
        with self.assertRaises(ValidationError):
            A.PropertyIdentity(details=[{"label": "L", "value": "V", "source_refs": []}])
        identity = A.PropertyIdentity(
            details=[{"label": "L", "value": "V", "source_refs": [REF]}],
            unresolved=["1985 deed not supplied"],
        )
        self.assertEqual(identity.unresolved, ["1985 deed not supplied"])


class TestTitleChainEntry(unittest.TestCase):
    def _entry(self, **overrides):
        base = {
            "tx_id": "PA-TC-0001",
            "sequence": 1,
            "transaction_type": "Sale",
            "source_doc_ids": ["DOC_018"],
        }
        base.update(overrides)
        return base

    def test_valid_minimal_entry(self):
        entry = A.TitleChainEntry(**self._entry())
        self.assertEqual(entry.source, A.EntrySourceKind.DOCUMENT)

    def test_recital_source_round_trips(self):
        entry = A.TitleChainEntry(**self._entry(
            source="RECITAL",
            recital_references=["Sale deed 27-03-1985, Document No. 4966"],
            unresolved=["prior vendors' acquisition unverified"],
        ))
        self.assertEqual(entry.source, A.EntrySourceKind.RECITAL)
        self.assertEqual(entry.recital_references[0][:10], "Sale deed ")

    def test_upstream_tx_ids_must_be_application_assigned(self):
        with self.assertRaises(ValidationError):
            A.TitleChainEntry(**self._entry(upstream_tx_ids=["T01"]))
        entry = A.TitleChainEntry(**self._entry(upstream_tx_ids=["PA-TC-0001"]))
        self.assertEqual(entry.upstream_tx_ids, ["PA-TC-0001"])

    def test_rejects_model_invented_tx_id_format(self):
        with self.assertRaises(ValidationError):
            A.TitleChainEntry(**self._entry(tx_id="T1"))

    def test_rejects_entry_without_sources(self):
        with self.assertRaises(ValidationError):
            A.TitleChainEntry(**self._entry(source_doc_ids=[]))


class TestVerificationFinding(unittest.TestCase):
    def test_established_requires_evidence(self):
        with self.assertRaises(ValidationError):
            A.VerificationFinding(significance="ESTABLISHED", title="T", text="Body")
        finding = A.VerificationFinding(
            significance="ESTABLISHED", title="T", text="Body", evidence=[REF]
        )
        self.assertFalse(finding.is_legal_defect)

    def test_unresolved_cannot_assert_legal_defect(self):
        with self.assertRaises(ValidationError):
            A.VerificationFinding(
                significance="UNRESOLVED", title="T", text="Body", is_legal_defect=True
            )

    def test_contested_needs_no_evidence_but_nonempty_text(self):
        with self.assertRaises(ValidationError):
            A.VerificationFinding(significance="CONTESTED", title="T", text="  ")


class TestRunMetadata(unittest.TestCase):
    def test_analysis_run_metadata(self):
        run = A.AnalysisRunMetadata(run_id="fra1n2u3-4", case_id="CASE1", started_at="t")
        self.assertEqual(run.phases, [])
        with self.assertRaises(ValidationError):
            A.AnalysisRunMetadata(run_id="short", case_id="CASE1", started_at="t")


if __name__ == "__main__":
    unittest.main()
