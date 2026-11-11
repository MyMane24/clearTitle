"""Implementation 1: Phase B typed verification findings (task §5, §6, §9).
Covers the VerificationFinding contract, save-boundary validation
(evidence-or-gap rule, invalid-finding exclusion with report), app-stamped
stable finding ids, transaction association, and empty-findings validity.
"""
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from backend.schemas.analysis import (
    DocumentEvidenceReference,
    VerificationFinding,
)
from backend.database.repositories import agent_repo
from backend.services.agent_tools import (
    ToolContext,
    dispatch,
)
from backend.services.cleartitle_agent import _phase_a_transactions
def _finding(**overrides):
    base = {
        "significance": "ESTABLISHED",
        "title": "Execution clause defect",
        "text": "The execution page names a different grantee than the body of the deed.",
        "evidence": [{"doc_id": "DOC1", "pages": "2", "relation": "supports"}],
        "severity": "CAUTION",
        "confidence": "HIGH",
        "legal_or_property_implication": "The executed deed may not bind the named grantee.",
        "recommended_action": "Verify the corrected grantee against the registrar's copy.",
        "affected_parties": ["Vendor A", "Purchaser C"],
    }
    base.update(overrides)
    return base
class TestVerificationFindingSchema(unittest.TestCase):
    def test_valid_stamped_finding_round_trips(self):
        finding = VerificationFinding(**_finding(finding_id="TF-001", transaction_id="PA-TC-0001"))
        self.assertEqual(finding.status, "OPEN")
        self.assertEqual(finding.severity, "CAUTION")
        self.assertEqual(finding.confidence, "HIGH")
    def test_defaults_keep_legacy_findings_loadable(self):
        minimal = VerificationFinding(significance="UNRESOLVED", title="T", text="Body")
        self.assertEqual(minimal.severity, "INFORMATION")
        self.assertEqual(minimal.status, "OPEN")
        self.assertEqual(minimal.finding_id, "")
        self.assertEqual(minimal.transaction_id, "")
        self.assertEqual(minimal.evidence_gaps, [])
    def test_invalid_finding_id_shape_rejected(self):
        with self.assertRaises(ValidationError):
            VerificationFinding(**_finding(finding_id="F-1"))
        with self.assertRaises(ValidationError):
            VerificationFinding(**_finding(transaction_id="tx1"))
    def test_critical_requires_evidence_and_implication(self):
        with self.assertRaises(ValidationError):
            VerificationFinding(**_finding(severity="CRITICAL", legal_or_property_implication=None))
        with self.assertRaises(ValidationError):
            VerificationFinding(**_finding(severity="CRITICAL", evidence=[]))
        finding = VerificationFinding(**_finding(severity="CRITICAL"))
        self.assertEqual(finding.severity, "CRITICAL")
        self.assertTrue(finding.legal_or_property_implication)
    def test_resolved_requires_resolution_evidence(self):
        with self.assertRaises(ValidationError):
            VerificationFinding(**_finding(status="RESOLVED"))
        finding = VerificationFinding(**_finding(status="RESOLVED", resolution_evidence=[{"doc_id": "DOC1"}]))
        self.assertEqual(finding.resolution_evidence[0].doc_id, "DOC1")
    def test_partial_resolution_status_exists_and_needs_no_resolution_evidence(self):
        finding = VerificationFinding(**_finding(status="PARTIALLY_RESOLVED"))
        self.assertEqual(finding.status, "PARTIALLY_RESOLVED")
    def test_evidence_reference_relation_is_controlled(self):
        with self.assertRaises(ValidationError):
            DocumentEvidenceReference(doc_id="DOC1", relation="invents")
        reference = DocumentEvidenceReference(doc_id="DOC1", relation="contradicts", evidence_type="register_extract")
        self.assertEqual(reference.relation, "contradicts")
class TestFindingIdAssignment(unittest.TestCase):
    def test_registry_maps_content_keys_to_app_ids_only(self):
        from backend.services import chain_identity as CI
        rows = [
            {"tx_id": "PA-TC-0001", "findings": [
                _finding(title="Same observation", severity="CAUTION", finding_id="TF-001"),
                {"garbage": True, "finding_id": "TF-002"},
            ]},
            {"tx_id": "PA-TC-0002", "findings": [
                _finding(title="Same observation", severity="CAUTION", finding_id="TF-002"),
            ]},
        ]
        registry, used = CI.finding_registry(rows)
        self.assertEqual(used, {1, 2})
        finding = _finding(title="Same observation", severity="CAUTION")
        CI.assign_finding_ids("PA-TC-0001", [finding], registry, used)
        self.assertEqual(finding["finding_id"], "TF-001")  # same content, same id
        changed = _finding(title="Different observation", severity="CAUTION")
        CI.assign_finding_ids("PA-TC-0001", [changed], registry, used)
        self.assertEqual(changed["finding_id"], "TF-003")  # changed content, next id
    def test_duplicate_content_in_one_batch_gets_distinct_ids(self):
        from backend.services import chain_identity as CI
        registry, used = CI.finding_registry([])
        first = _finding()
        second = dict(_finding())
        CI.assign_finding_ids("PA-TC-0001", [first, second], registry, used)
        self.assertEqual(first["finding_id"], "TF-001")
        self.assertEqual(second["finding_id"], "TF-002")
class TestSaveBoundaryFindings(unittest.TestCase):
    def setUp(self):
        self.phase_a = {
            "property_identity": {"details": []},
            "title_chain_graph": "Owner A -> Owner B",
            "title_chain": [
                {
                    "chain_position": 1,
                    "documented_transaction": {
                        "transaction_type": "Sale deed",
                        "transaction_number": "REG-1",
                        "summary_points": ["Sale from A to B"],
                        "source_refs": [{"doc_id": "DOC1"}],
                    },
                    "related_events": [],
                },
            ],
        }
        self.tx = _phase_a_transactions(self.phase_a)[0]
        self.ctx = ToolContext(
            "CASE1", [{"doc_id": "DOC1"}], chain={"transactions": [self.tx]},
            current_tx_id=self.tx["tx_id"], phase_a_chain=self.phase_a["title_chain"],
        )
        for doc_id in self.ctx.by_id:
            self.ctx.selected_document_ids.add(doc_id)
    def _dispatch(self, **payload):
        with patch("backend.services.agent_tools._has_read_full_text", return_value=True), \
             patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results", return_value=[]), \
             patch("backend.services.agent_tools.repo.save_transaction_result") as save:
            response = dispatch(self.ctx, "save_transaction_result", {
                "tx_id": self.tx["tx_id"], "sequence": self.tx["sequence"],
                "status": "ISSUES_IDENTIFIED",
                "report": "A discrepancy is documented [DOC1 p.2].",
                "cited_documents": [{"doc_id": "DOC1", "pages": "2"}],
                **payload,
            })
        saved = save.call_args.kwargs["verification"] if save.call_args else None
        return response, saved
    def test_valid_finding_is_stamped_and_saved_with_transaction_association(self):
        response, saved = self._dispatch(findings=[dict(_finding(), severity="CAUTION")])
        self.assertTrue(response["saved"])
        self.assertNotIn("rejected_findings", response)
        self.assertEqual(saved["findings"][0]["finding_id"], "TF-001")
        self.assertEqual(saved["findings"][0]["transaction_id"], "PA-TC-0001")
        self.assertEqual(saved["findings"][0]["severity"], "CAUTION")
        self.assertEqual(len(saved["findings"]), 1)
    def test_findings_without_evidence_and_without_gaps_are_excluded_and_reported(self):
        response, saved = self._dispatch(findings=[
            _finding(),
            _finding(title="Untracked assertion", text="The seller act jointly.",
                     evidence=[], severity="INFORMATION", significance="UNRESOLVED"),
        ])
        self.assertTrue(response["saved"])
        self.assertEqual(response["rejected_findings"][0]["index"], 1)
        self.assertEqual(len(saved["findings"]), 1)  # the valid one persisted
    def test_evidence_gap_findings_are_accepted_when_declared(self):
        gap_finding = _finding(
            significance="UNRESOLVED", severity="CAUTION",
            text="Mutation entry referenced in the deed is not on record.",
            evidence=[], evidence_gaps=["Mutation Entry 4930 for the 1988 partition"],
        )
        response, saved = self._dispatch(findings=[gap_finding])
        self.assertTrue(response["saved"])
        self.assertEqual(len(saved["findings"]), 1)
        self.assertEqual(saved["findings"][0]["evidence_gaps"], ["Mutation Entry 4930 for the 1988 partition"])
    def test_multiple_findings_persist_in_order_with_unique_ids(self):
        findings = [
            _finding(title="First observation", severity="INFORMATION"),
            _finding(title="Second observation", severity="CAUTION"),
        ]
        response, saved = self._dispatch(findings=findings)
        self.assertEqual([f["finding_id"] for f in saved["findings"]], ["TF-001", "TF-002"])
    def test_contested_finding_cites_conflicting_documents_with_relations(self):
        contested = _finding(
            significance="CONTESTED", severity="CAUTION",
            text="The deed's conveyance clause conflicts with the EC entry.",
            evidence=[
                {"doc_id": "DOC1", "relation": "supports"},
                {"doc_id": "DOC1", "relation": "contradicts", "pages": "3"},
            ],
        )
        response, saved = self._dispatch(findings=[contested])
        self.assertEqual(len(saved["findings"]), 1)
        self.assertEqual(saved["findings"][0]["evidence"][1]["relation"], "contradicts")
    def test_empty_findings_are_valid_for_a_clean_dossier(self):
        with patch("backend.services.agent_tools._has_read_full_text", return_value=True), \
             patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results", return_value=[]), \
             patch("backend.services.agent_tools.repo.save_transaction_result") as save:
            response = dispatch(self.ctx, "save_transaction_result", {
                "tx_id": self.tx["tx_id"], "sequence": self.tx["sequence"],
                "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
                "report": "The transaction is supported by the examined deed.",
                "cited_documents": [{"doc_id": "DOC1", "pages": "1"}],
                "executive_summary": "The sale deed is proven by the examined registered deed.",
                "verified_facts": ["Registered sale deed exists"],
                "unverified_facts": ["Original possession"],
                "limitations": ["No mutation entry supplied"],
                "findings": [],
            })
        self.assertTrue(response["saved"])
        saved = save.call_args.kwargs["verification"]
        self.assertEqual(saved["findings"], [])
        self.assertEqual(saved["executive_summary"], "The sale deed is proven by the examined registered deed.")
    def test_stable_ids_across_updates_using_the_persisted_registry(self):
        prior_row = {"schema_version": "3.0", "tx_id": self.tx["tx_id"], "findings": [
            dict(_finding(), finding_id="TF-001", transaction_id=self.tx["tx_id"]),
        ]}
        with patch("backend.services.agent_tools._has_read_full_text", return_value=True), \
             patch("backend.services.agent_tools.repo.get_transaction_result", return_value=prior_row), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results", return_value=[prior_row]), \
             patch("backend.services.agent_tools.repo.save_transaction_result") as save:
            response = dispatch(self.ctx, "save_transaction_result", {
                "tx_id": self.tx["tx_id"], "sequence": self.tx["sequence"],
                "status": "ISSUES_IDENTIFIED",
                "report": "A discrepancy is documented [DOC1 p.2].",
                "cited_documents": [{"doc_id": "DOC1", "pages": "2"}],
                "findings": [dict(_finding())],
            })
        saved = save.call_args.kwargs["verification"]
        self.assertTrue(response["saved"])
        self.assertEqual(saved["findings"][0]["finding_id"], "TF-001")
    def test_omitted_findings_inherit_the_prior_completed_dossier(self):
        prior_row = {"schema_version": "3.0", "tx_id": self.tx["tx_id"], "findings": [
            dict(_finding(), finding_id="TF-001", transaction_id=self.tx["tx_id"]),
        ], "executive_summary": "Restored verdict."}
        with patch("backend.services.agent_tools._has_read_full_text", return_value=True), \
             patch("backend.services.agent_tools.repo.get_transaction_result", return_value=prior_row), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results", return_value=[prior_row]), \
             patch("backend.services.agent_tools.repo.save_transaction_result") as save:
            dispatch(self.ctx, "save_transaction_result", {
                "tx_id": self.tx["tx_id"], "sequence": self.tx["sequence"],
                "status": "ISSUES_IDENTIFIED",
                "report": "A discrepancy is documented [DOC1 p.2].",
                "cited_documents": [{"doc_id": "DOC1", "pages": "2"}],
            })
        saved = save.call_args.kwargs["verification"]
        self.assertEqual([f["finding_id"] for f in saved["findings"]], ["TF-001"])
        self.assertEqual(saved["executive_summary"], "Restored verdict.")
    def test_model_supplied_finding_ids_are_ignored(self):
        response, saved = self._dispatch(findings=[dict(_finding(), finding_id="TF-999")])
        self.assertTrue(response["saved"])
        self.assertEqual(saved["findings"][0]["finding_id"], "TF-001")
    def test_pending_checkpoint_never_carries_findings(self):
        # A persisted dossier with findings exists; pausing on an evidence
        # request must not carry those findings (or inherited content) into
        # the pending checkpoint result.
        prior_row = {
            "schema_version": "3.0", "tx_id": self.tx["tx_id"],
            "executive_summary": "Restored verdict.",
            "findings": [dict(_finding(), finding_id="TF-001", transaction_id=self.tx["tx_id"])],
        }
        with patch("backend.services.agent_tools.repo.get_transaction_result", return_value=prior_row), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results", return_value=[prior_row]), \
             patch("backend.services.agent_tools.repo.save_transaction_result") as save:
            dispatch(self.ctx, "record_evidence_requirements", {"requirements": [{
                "document_type": "Mutation entry 4930", "reason": "Establish the 1988 partition effect.",
            }]})
            dispatch(self.ctx, "list_documents", {})
            response = dispatch(self.ctx, "save_transaction_result", {
                "tx_id": self.tx["tx_id"], "sequence": self.tx["sequence"],
                "status": "PENDING_NOT_VERIFIED",
                "report": "The mutation entry is not on record, so this transfer stays pending.",
                "required_documents": [{
                    "document_type": "Mutation entry 4930", "reason": "Establish the 1988 partition effect.",
                }],
            })
        self.assertTrue(response["paused"])
        saved = save.call_args.kwargs["verification"]
        self.assertEqual(saved["findings"], [])
        self.assertEqual(saved["executive_summary"], "")
        self.assertEqual(saved["status"], "PENDING_NOT_VERIFIED")
    def test_findings_are_not_a_tool_schema_property_below_result_level_only(self):
        # The save tool schema continues to expose findings; ids never appear
        # as schema-required inputs the model must fill.
        from backend.services.agent_tools import _verification_props
        schema_props = _verification_props()["properties"]
        self.assertIn("findings", schema_props)
        self.assertNotIn("scope", schema_props)
        self.assertNotIn("revision", schema_props)
class TestContradictoryEvidence(unittest.TestCase):
    """Review defect 2: case-membership validation + completed-update inheritance
    for ``contradictory_evidence``. A reference outside the case is rejected
    hard (validation error, nothing persisted) — never silently kept."""
    def setUp(self):
        self.phase_a = {
            "property_identity": {"details": []},
            "title_chain_graph": "Owner A -> Owner B",
            "title_chain": [
                {
                    "chain_position": 1,
                    "documented_transaction": {
                        "transaction_type": "Sale deed",
                        "transaction_number": "REG-1",
                        "summary_points": ["Sale from A to B"],
                        "source_refs": [{"doc_id": "DOC1"}],
                    },
                    "related_events": [],
                },
            ],
        }
        self.tx = _phase_a_transactions(self.phase_a)[0]
        self.ctx = ToolContext(
            "CASE1", [{"doc_id": "DOC1"}], chain={"transactions": [self.tx]},
            current_tx_id=self.tx["tx_id"], phase_a_chain=self.phase_a["title_chain"],
        )
        for doc_id in self.ctx.by_id:
            self.ctx.selected_document_ids.add(doc_id)
    def _dispatch(self, *, prior_row=None, **payload):
        with patch("backend.services.agent_tools._has_read_full_text", return_value=True), \
             patch("backend.services.agent_tools.repo.get_transaction_result", return_value=prior_row), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results", return_value=[prior_row] if prior_row else []), \
             patch("backend.services.agent_tools.repo.save_transaction_result") as save:
            response = dispatch(self.ctx, "save_transaction_result", {
                "tx_id": self.tx["tx_id"], "sequence": self.tx["sequence"],
                "status": "ISSUES_IDENTIFIED",
                "report": "A discrepancy is documented [DOC1 p.2].",
                "cited_documents": [{"doc_id": "DOC1", "pages": "2"}],
                **payload,
            })
        saved = save.call_args.kwargs["verification"] if save.call_args else None
        return response, saved
    def _prior_row(self, **extra):
        row = {"schema_version": "3.0", "tx_id": self.tx["tx_id"]}
        row.update(extra)
        return row
    def test_valid_in_case_references_persist(self):
        response, saved = self._dispatch(contradictory_evidence=[
            {"doc_id": "DOC1", "pages": "2", "relation": "contradicts"},
        ])
        self.assertTrue(response["saved"])
        self.assertEqual([ref["doc_id"] for ref in saved["contradictory_evidence"]], ["DOC1"])
        self.assertEqual(saved["contradictory_evidence"][0]["relation"], "contradicts")
    def test_foreign_and_unknown_document_references_are_rejected_and_nothing_persists(self):
        for doc_id in ("DOC-FOREIGN", "DOC999"):
            with self.subTest(doc_id=doc_id):
                response, saved = self._dispatch(contradictory_evidence=[
                    {"doc_id": doc_id, "pages": "9", "relation": "contradicts"},
                ])
                self.assertNotIn("saved", response)
                self.assertIn("contradictory_evidence cites documents outside this case", response["error"])
                self.assertIn(doc_id, response["error"])
                self.assertIsNone(saved)  # repo.save_transaction_result never called
    def test_inherited_references_are_validated_against_the_case_too(self):
        prior_row = self._prior_row(contradictory_evidence=[
            {"doc_id": "DOC1", "relation": "contradicts"},
        ])
        response, saved = self._dispatch(prior_row=prior_row)  # field omitted on update
        self.assertTrue(response["saved"])
        self.assertEqual([ref["doc_id"] for ref in saved["contradictory_evidence"]], ["DOC1"])
    def test_inherited_foreign_references_fail_hard_with_a_clearing_hint(self):
        prior_row = self._prior_row(contradictory_evidence=[
            {"doc_id": "DOC-BAD", "relation": "contradicts"},
        ])
        response, saved = self._dispatch(prior_row=prior_row)  # omitted → inherited → rejected
        self.assertNotIn("saved", response)
        self.assertIn("DOC-BAD", response["error"])
        self.assertIn("set contradictory_evidence to []", response["error"])
        self.assertIsNone(saved)
    def test_explicit_empty_array_clears_inherited_references(self):
        prior_row = self._prior_row(contradictory_evidence=[
            {"doc_id": "DOC1", "relation": "contradicts"},
        ])
        response, saved = self._dispatch(prior_row=prior_row, contradictory_evidence=[])
        self.assertTrue(response["saved"])
        self.assertEqual(saved["contradictory_evidence"], [])
    def test_structurally_invalid_reference_is_rejected_by_the_contract(self):
        response, saved = self._dispatch(contradictory_evidence=[
            {"doc_id": "   ", "relation": "contradicts"},
        ])
        self.assertNotIn("saved", response)
        self.assertIsNone(saved)
    def test_pending_checkpoint_does_not_inherit_contradictory_evidence(self):
        prior_row = self._prior_row(
            contradictory_evidence=[{"doc_id": "DOC1", "relation": "contradicts"}],
            executive_summary="Restored verdict.",
        )
        with patch("backend.services.agent_tools.repo.get_transaction_result", return_value=prior_row), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results", return_value=[prior_row]), \
             patch("backend.services.agent_tools.repo.save_transaction_result") as save:
            dispatch(self.ctx, "record_evidence_requirements", {"requirements": [{
                "document_type": "Mutation entry 4930", "reason": "Establish the 1988 partition effect.",
            }]})
            dispatch(self.ctx, "list_documents", {})
            response = dispatch(self.ctx, "save_transaction_result", {
                "tx_id": self.tx["tx_id"], "sequence": self.tx["sequence"],
                "status": "PENDING_NOT_VERIFIED",
                "report": "The mutation entry is not on record, so this transfer stays pending.",
                "required_documents": [{
                    "document_type": "Mutation entry 4930", "reason": "Establish the 1988 partition effect.",
                }],
            })
        self.assertTrue(response["paused"])
        saved = save.call_args.kwargs["verification"]
        self.assertEqual(saved["status"], "PENDING_NOT_VERIFIED")
        self.assertEqual(saved["contradictory_evidence"], [])
        self.assertEqual(saved["findings"], [])
class TestFindingLifecycle(unittest.TestCase):
    """Review §5: the documented content-key lifecycle. A finding's identity key
    is (transaction, category, title, cited document ids). Enriching evidence
    rotates the id; status-only changes (OPEN → RESOLVED → SUPERSEDED) and refs
    moved into resolution_evidence keep it. Retired ids are never reissued, so
    historical revisions' ids stand untouched (see test_dossier_versioning)."""
    def setUp(self):
        self.phase_a = {
            "property_identity": {"details": []},
            "title_chain_graph": "Owner A -> Owner B",
            "title_chain": [
                {
                    "chain_position": 1,
                    "documented_transaction": {
                        "transaction_type": "Sale deed",
                        "transaction_number": "REG-1",
                        "summary_points": ["Sale from A to B"],
                        "source_refs": [{"doc_id": "DOC1"}],
                    },
                    "related_events": [],
                },
            ],
        }
        self.tx = _phase_a_transactions(self.phase_a)[0]
        self.ctx = ToolContext(
            "CASE1",
            [
                {"doc_id": "DOC1", "summary": "Sale deed", "filename": "deed.pdf", "document_type": "SALE_DEED"},
                {"doc_id": "DOC2", "summary": "Mutation entry", "filename": "mutation.pdf", "document_type": "EC"},
            ],
            chain={"transactions": [self.tx]},
            current_tx_id=self.tx["tx_id"], phase_a_chain=self.phase_a["title_chain"],
        )
        for doc_id in self.ctx.by_id:
            self.ctx.selected_document_ids.add(doc_id)
    def _dispatch(self, *, prior_rows=None, ctx=None, **payload):
        with patch("backend.services.agent_tools._has_read_full_text", return_value=True), \
             patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results", return_value=prior_rows or []), \
             patch("backend.services.agent_tools.repo.save_transaction_result") as save:
            response = dispatch(ctx or self.ctx, "save_transaction_result", {
                "tx_id": self.tx["tx_id"], "sequence": self.tx["sequence"],
                "status": "ISSUES_IDENTIFIED",
                "report": "A discrepancy is documented [DOC1 p.2].",
                "cited_documents": [{"doc_id": "DOC1", "pages": "2"}],
                **payload,
            })
        saved = save.call_args.kwargs["verification"] if save.call_args else None
        return response, saved
    def _prior_rows(self, **finding_overrides):
        return [{"schema_version": "3.0", "tx_id": self.tx["tx_id"], "findings": [
            dict(_finding(), finding_id="TF-001", transaction_id=self.tx["tx_id"], **finding_overrides),
        ]}]
    def test_status_only_changes_retain_the_finding_id(self):
        variants = [
            ("OPEN", {}),
            ("RESOLVED", {"resolution_evidence": [{"doc_id": "DOC1"}]}),
            ("SUPERSEDED", {}),
        ]
        for status, extra in variants:
            # A completed save is terminal for its context, so each status step
            # runs against a fresh ToolContext like a real rerun.
            self.setUp()
            with self.subTest(status=status):
                response, saved = self._dispatch(
                    prior_rows=self._prior_rows(), findings=[dict(_finding(status=status), **extra)])
                self.assertTrue(response["saved"])
                self.assertEqual(saved["findings"][0]["status"], status)
                self.assertEqual(saved["findings"][0]["finding_id"], "TF-001")
    def test_resolution_evidence_only_refs_map_to_the_same_identity(self):
        # Save-boundary rule: a newly supplied finding must cite evidence or
        # declare gaps, so refs can only land in resolution_evidence via a
        # previously persisted dossier. The content key reads
        # `evidence or resolution_evidence`, so such a historical row keeps its
        # TF id for unchanged content.
        prior_rows = [{"schema_version": "3.0", "tx_id": self.tx["tx_id"], "findings": [
            dict(_finding(), finding_id="TF-001", transaction_id=self.tx["tx_id"],
                 significance="UNRESOLVED", legal_or_property_implication=None,
                 evidence=[], resolution_evidence=[{"doc_id": "DOC1"}]),
        ]}]
        response, saved = self._dispatch(prior_rows=prior_rows, findings=[_finding()])
        self.assertTrue(response["saved"])
        self.assertEqual([f["finding_id"] for f in saved["findings"]], ["TF-001"])
    def test_evidence_enrichment_rotates_to_a_new_never_reused_id(self):
        # Citing an additional in-case document changes the content key, so the
        # finding rotates to a fresh id; the retired number is not reissued.
        response, saved = self._dispatch(
            prior_rows=self._prior_rows(),
            findings=[_finding(evidence=[
                {"doc_id": "DOC1", "pages": "2", "relation": "supports"},
                {"doc_id": "DOC2", "pages": "5", "relation": "supports"},
            ])],
        )
        self.assertTrue(response["saved"])
        self.assertEqual([f["finding_id"] for f in saved["findings"]], ["TF-002"])
    def test_overflow_ids_round_trip_through_the_schema_and_registry(self):
        from backend.services import chain_identity as CI
        finding = VerificationFinding(**_finding(finding_id="TF-1000", transaction_id="PA-TC-0001"))
        self.assertEqual(finding.finding_id, "TF-1000")
        rows = [{"tx_id": self.tx["tx_id"], "findings": [
            dict(_finding(), finding_id="TF-1000"),
            {"garbage": True, "finding_id": "TF-9999x"},
        ]}]
        registry, used = CI.finding_registry(rows)
        self.assertEqual(used, {1000})
        unchanged = _finding()
        CI.assign_finding_ids(self.tx["tx_id"], [unchanged], registry, used)
        self.assertEqual(unchanged["finding_id"], "TF-1000")
        changed = _finding(title="Different observation")
        CI.assign_finding_ids(self.tx["tx_id"], [changed], registry, used)
        # Numbers 1-999 were never claimed in this case, so a new content key
        # starts from TF-001; TF-1000 itself is preserved for its own content.
        self.assertEqual(changed["finding_id"], "TF-001")
class TestStrictRegistryReader(unittest.TestCase):
    """The strict Phase B registry read distinguishes empty, populated, failed
    and corrupt states — the tolerant `_case_result` degrades corrupt payloads
    to [], which is safe for readers but not for finding-id allocation."""
    def _cursor(self, raw):
        with patch("backend.database.repositories.agent_repo._get_conn") as get_conn:
            cursor = get_conn.return_value.__enter__.return_value.cursor.return_value
            cursor.fetchone.return_value = None if raw is None else (raw,)
            yield get_conn
    def _read_with(self, raw):
        for get_conn in self._cursor(raw):
            with get_conn:
                return agent_repo.list_persisted_transaction_results("CASE1")
    def test_healthy_shapes_read_strictly(self):
        import json as jsonlib
        self.assertEqual(self._read_with(None), [])  # row absent
        self.assertEqual(self._read_with("null"), [])  # persisted JSON null
        rows = [{"tx_id": "PA-TC-0001"}]
        self.assertEqual(self._read_with(jsonlib.dumps(rows)), rows)
        self.assertEqual(
            self._read_with(jsonlib.dumps({"transactions": rows})), rows)  # legacy dict
        self.assertEqual(self._read_with({"transactions": rows}), rows)  # dict-typed value
    def test_corrupt_and_unexpected_payloads_raise(self):
        for raw in ("{broken json", '"a bare string"', "7", '{"transactions": 7}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    self._read_with(raw)
class TestRegistryStrictSave(unittest.TestCase):
    """Part 1 (reliability review): finding-id allocation must never proceed
    against an unknown registry state; failure aborts the save before any
    persistence or context mutation, with a retryable structured error."""
    def setUp(self):
        self.phase_a = {
            "property_identity": {"details": []},
            "title_chain_graph": "Owner A -> Owner B",
            "title_chain": [
                {
                    "chain_position": 1,
                    "documented_transaction": {
                        "transaction_type": "Sale deed",
                        "transaction_number": "REG-1",
                        "summary_points": ["Sale from A to B"],
                        "source_refs": [{"doc_id": "DOC1"}],
                    },
                    "related_events": [],
                },
            ],
        }
        self.tx = _phase_a_transactions(self.phase_a)[0]
        self.ctx = ToolContext(
            "CASE1",
            [
                {"doc_id": "DOC1", "summary": "Sale deed", "filename": "deed.pdf", "document_type": "SALE_DEED"},
                {"doc_id": "DOC2", "summary": "Mutation entry", "filename": "mutation.pdf", "document_type": "EC"},
            ],
            chain={"transactions": [self.tx]},
            current_tx_id=self.tx["tx_id"], phase_a_chain=self.phase_a["title_chain"],
        )
        for doc_id in self.ctx.by_id:
            self.ctx.selected_document_ids.add(doc_id)
    def _dispatch(self, *, read_error=None, prior_rows=None, **payload):
        with patch("backend.services.agent_tools._has_read_full_text", return_value=True), \
             patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None), \
             patch("backend.services.agent_tools.repo.list_persisted_transaction_results",
                   side_effect=read_error, return_value=prior_rows or []), \
             patch("backend.services.agent_tools.repo.save_transaction_result") as save:
            response = dispatch(self.ctx, "save_transaction_result", {
                "tx_id": self.tx["tx_id"], "sequence": self.tx["sequence"],
                "status": "ISSUES_IDENTIFIED",
                "report": "A discrepancy is documented [DOC1 p.2].",
                "cited_documents": [{"doc_id": "DOC1", "pages": "2"}],
                **payload,
            })
        saved = save.call_args.kwargs["verification"] if save.call_args else None
        return response, saved
    def _finding(self):
        return dict(_finding(), title="Registry probe defect")
    def _assert_retryable_abort(self, response, saved):
        self.assertNotIn("saved", response)
        self.assertIn("cannot safely assign transaction finding ids", response["error"])
        self.assertIn("Nothing was saved", response["error"])
        self.assertIn("reconciled against the persisted history", response["error"])
        self.assertTrue(response["retryable"])
        self.assertIsNone(saved)  # repo.save_transaction_result never called
        # No partial mutation of evidence-requirement or completion state.
        self.assertEqual(self.ctx.saved_results, [])
        self.assertFalse(self.ctx.finished)
        self.assertEqual(self.ctx.missing_requests, [])
    def test_read_failure_aborts_save_before_persistence(self):
        response, saved = self._dispatch(
            findings=[self._finding()], read_error=RuntimeError("db down on case_results"))
        self._assert_retryable_abort(response, saved)
    def test_corrupt_registry_data_aborts_the_save(self):
        # The tolerant read would report [] and mint duplicate TF ids; the
        # strict read makes the unknown state an abort instead.
        response, saved = self._dispatch(
            findings=[self._finding()],
            read_error=ValueError("case transaction results for case CASE1 are unreadable: ..."))
        self._assert_retryable_abort(response, saved)
    def test_no_finding_ids_are_allocated_against_an_incomplete_registry(self):
        # Success response absent ⇒ payload with allocations was never built;
        # the pre-allocation entries in this context keep their original state.
        baseline = ToolContext(
            "CASE1", [{"doc_id": "DOC1"}], chain={"transactions": [self.tx]},
            current_tx_id=self.tx["tx_id"], phase_a_chain=self.phase_a["title_chain"],
        )
        with self.subTest(context_fields="rejected_findings"):
            self.assertEqual(self.ctx.rejected_findings, baseline.rejected_findings)
    def test_empty_registry_still_means_genuinely_empty_history(self):
        response, saved = self._dispatch(findings=[self._finding()])
        self.assertTrue(response["saved"])
        self.assertEqual([f["finding_id"] for f in saved["findings"]], ["TF-001"])
    def test_populated_registry_reconciles_ids(self):
        prior_row = {"schema_version": "3.0", "tx_id": self.tx["tx_id"], "findings": [
            dict(_finding(), finding_id="TF-001", transaction_id=self.tx["tx_id"]),
        ]}
        response, saved = self._dispatch(prior_rows=[prior_row], findings=[dict(_finding())])
        self.assertTrue(response["saved"])
        self.assertEqual([f["finding_id"] for f in saved["findings"]], ["TF-001"])
        self.setUp()  # the first completed save is terminal for its context
        changed = _finding(title="Registry probe defect")
        response, saved = self._dispatch(prior_rows=[prior_row], findings=[changed])
        self.assertEqual([f["finding_id"] for f in saved["findings"]], ["TF-002"])
    def test_retry_after_recovery_reconciles_ids_against_persisted_history(self):
        # Attempt 1: the registry read fails → nothing persists.
        first, saved_first = self._dispatch(
            findings=[self._finding()], read_error=RuntimeError("db down"))
        self.assertFalse(first.get("saved"))
        self.assertIsNone(saved_first)
        # Attempt 2 (fresh context, as a recovered runtime supplies): the same
        # unchanged content reuses the persisted TF-001, not a fresh number.
        self.setUp()
        prior_row = {"schema_version": "3.0", "tx_id": self.tx["tx_id"], "findings": [
            dict(_finding(), finding_id="TF-001", transaction_id=self.tx["tx_id"]),
        ]}
        response, saved = self._dispatch(prior_rows=[prior_row], findings=[dict(_finding())])
        self.assertTrue(response["saved"])
        self.assertEqual([f["finding_id"] for f in saved["findings"]], ["TF-001"])
if __name__ == "__main__":  # pragma: no cover
    unittest.main()
