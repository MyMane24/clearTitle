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


class TestRequirementIdsAndContracts(unittest.TestCase):
    def test_new_requirement_id_bounds(self):
        self.assertEqual(A.new_requirement_id(1), "REQ-0001")
        self.assertEqual(A.new_requirement_id(9999), "REQ-9999")
        with self.assertRaises(ValueError):
            A.new_requirement_id(0)
        with self.assertRaises(ValueError):
            A.new_requirement_id(10000)

    def test_open_requirement_needs_owner(self):
        with self.assertRaises(ValidationError):
            A.EvidenceRequirement(requirement_id="REQ-0001", document_type="Sale deed 1985")

    def test_satisfied_requirement_may_be_ownerless(self):
        req = A.EvidenceRequirement(
            requirement_id="REQ-0002",
            document_type="Sale deed 1985",
            status="SATISFIED",
            match={"status": "MATCHED", "doc_id": "DOC_030"},
        )
        self.assertEqual(req.match.status, A.MatchStatus.MATCHED)

    def test_rejects_foreign_requirement_id_shape(self):
        with self.assertRaises(ValidationError):
            A.EvidenceRequirement(
                requirement_id="REQ-1", owner_tx_id="PA-TC-0001", document_type="Map"
            )


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


class TestPropertyFinding(unittest.TestCase):
    def _finding(self, **overrides):
        base = {
            "finding_id": "PF-001",
            "category": "encumbrance",
            "title": "Mortgage not shown discharged",
            "description": "Memorandum of deposit cited by two transactions.",
            "severity": "CAUTION",
            "affected_tx_ids": ["PA-TC-0007", "PA-TC-0008"],
        }
        base.update(overrides)
        return base

    def test_valid_finding(self):
        self.assertEqual(A.PropertyFinding(**self._finding()).status, "OPEN")

    def test_invalid_finding_id_and_tx_refs(self):
        with self.assertRaises(ValidationError):
            A.PropertyFinding(**self._finding(finding_id="PF-1"))
        with self.assertRaises(ValidationError):
            A.PropertyFinding(**self._finding(affected_tx_ids=["tx1"]))

    def test_resolved_requires_resolution_evidence(self):
        with self.assertRaises(ValidationError):
            A.PropertyFinding(**self._finding(status="RESOLVED"))
        resolved = A.PropertyFinding(**self._finding(status="RESOLVED", resolution_evidence=[REF]))
        self.assertEqual(resolved.resolution_evidence[0].doc_id, "DOC_001")

    def test_new_finding_id_bounds(self):
        self.assertEqual(A.new_finding_id(1), "PF-001")
        with self.assertRaises(ValueError):
            A.new_finding_id(1000)


class TestConsolidation(unittest.TestCase):
    def test_duplicated_finding_ids_rejected(self):
        finding = {"finding_id": "PF-001", "category": "encumbrance", "title": "t",
                   "description": "d", "severity": "CAUTION"}
        with self.assertRaises(ValidationError):
            A.PropertyConsolidationResult(
                findings=[finding, finding],
                provenance={"phase_a_hash": "abc", "run_id": "r1", "created_at": "now"},
            )

    def test_contradiction_needs_two_sides(self):
        with self.assertRaises(ValidationError):
            A.Contradiction(
                description="Survey numbers conflict",
                sides=[{"tx_id": "PA-TC-0002"}],
            )
        ok = A.Contradiction(
            description="Survey numbers conflict",
            sides=[{"tx_id": "PA-TC-0002"}, {"tx_id": "PA-TC-0003"}],
        )
        self.assertEqual(ok.severity, A.Severity.CAUTION)


class TestOpinionContracts(unittest.TestCase):
    def _opinion(self, **overrides):
        base = {
            "verdict": "ATTENTION_REQUIRED",
            "report_type": "PRELIMINARY",
            "executive_assessment": "Concise property-level summary.",
            "property_identity": {"details": [{"label": "L", "value": "V", "source_refs": [REF]}]},
            "ownership_history_summary": "Chain from 2007 joint purchase to 2024 sale.",
            "overall_assessment": "Unverified links remain.",
            "final_opinion": "Attention required pending evidence.",
            "source_hashes": {"phase_a": "h1", "case_result": "h2"},
            "provenance": {"run_id": "run-1", "created_at": "now"},
        }
        base.update(overrides)
        return base

    def test_preliminary_may_carry_outstanding(self):
        opinion = A.FinalDueDiligenceOpinion(
            **self._opinion(outstanding={"requirement_ids": ["REQ-0005"], "skipped_tx_ids": ["PA-TC-0002"]})
        )
        self.assertEqual(opinion.outstanding.skipped_tx_ids, ["PA-TC-0002"])

    def test_final_must_not_carry_outstanding(self):
        with self.assertRaises(ValidationError):
            A.FinalDueDiligenceOpinion(
                **self._opinion(report_type="FINAL",
                               outstanding={"requirement_ids": ["REQ-0005"]})
            )

    def test_empty_core_sections_rejected(self):
        with self.assertRaises(ValidationError):
            A.FinalDueDiligenceOpinion(**self._opinion(final_opinion=" "))


class TestRunAndReportMetadata(unittest.TestCase):
    def test_final_report_metadata_versioning(self):
        meta = A.FinalReportMetadata(
            version=2, report_type="FINAL", generated_at="2026-11-05T00:00:00Z",
            source_hashes={"case_result": "h"},
        )
        self.assertEqual(meta.contract_version, "1.0")
        self.assertFalse(meta.superseded)
        with self.assertRaises(ValidationError):
            A.FinalReportMetadata(version=0, report_type="FINAL",
                                  generated_at="x", source_hashes={})

    def test_analysis_run_metadata(self):
        run = A.AnalysisRunMetadata(run_id="fra1n2u3-4", case_id="CASE1", started_at="t")
        self.assertEqual(run.phases, [])
        with self.assertRaises(ValidationError):
            A.AnalysisRunMetadata(run_id="short", case_id="CASE1", started_at="t")


if __name__ == "__main__":
    unittest.main()
