"""Stage 5: findings consolidation — dedup collapse, assembly, container, done-path hook."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pydantic import ValidationError
from backend.database.repositories import agent_repo
from backend.schemas.analysis import ConsolidationDraftResult, FindingDraft
from backend.services.consolidation import (
    _assemble,
    _collect_candidates,
    _dedup_key_text,
    _D7_DISCLOSURE,
    consolidate_findings,
    validate_draft,
)
def _finding(title="Undischarged mortgage on the parent parcel", category="ENCUMBRANCE",
             text="A memorandum of deposit remains recorded.", evidence=None,
             defect=True, significance="ESTABLISHED", finding_id="TF-001"):
    return {
        "finding_id": finding_id,
        "significance": significance,
        "category": category,
        "title": title,
        "text": text,
        "evidence": evidence if evidence is not None else [{"doc_id": "DOC14", "pages": "2-3"}],
        "is_legal_defect": defect,
    }
def _dossier(tx_id, sequence, status="VERIFIED_WITH_AVAILABLE_EVIDENCE", findings=None):
    return {
        "tx_id": tx_id, "sequence": sequence, "status": status,
        "findings": findings if findings is not None else [],
    }
OPEN_REQ = {"requirement_id": "REQ-0002", "owner_tx_id": "PA-TC-0008",
            "document_type": "Encumbrance certificate for subsisting charge"}
GAP_LABEL = "[REQ-0002] Encumbrance certificate for subsisting charge"
class TestDeterministicCollapse(unittest.TestCase):
    """Fixture 7/8: the mortgage seen in several dossiers collapses to one."""
    def test_identical_observation_across_two_dossiers_merges(self):
        transactions = [
            _dossier("PA-TC-0007", 7, findings=[_finding()]),
            _dossier("PA-TC-0008", 8, findings=[_finding()]),
        ]
        candidates = _collect_candidates(transactions)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["tx_ids"], ["PA-TC-0007", "PA-TC-0008"])
        self.assertEqual(
            [source["tx_id"] for source in candidates[0]["sources"]],
            ["PA-TC-0007", "PA-TC-0008"],
        )
        self.assertEqual(candidates[0]["evidence"], [{"doc_id": "DOC14", "pages": "2-3"}])
    def test_different_cited_documents_stay_separate(self):
        transactions = [
            _dossier("PA-TC-0007", 7, findings=[_finding()]),
            _dossier("PA-TC-0008", 8, findings=[_finding(
                evidence=[{"doc_id": "DOC15", "pages": "5"}, {"doc_id": "DOC14", "pages": "2-3"}],
            )]),
        ]
        candidates = _collect_candidates(transactions)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[1]["evidence"][0], {"doc_id": "DOC15", "pages": "5"})
    def test_same_words_under_different_categories_do_not_merge(self):
        transactions = [
            _dossier("PA-TC-0007", 7, findings=[_finding(category="ENCUMBRANCE")]),
            _dossier("PA-TC-0008", 8, findings=[_finding(category="LIABILITY")]),
        ]
        candidates = _collect_candidates(transactions)
        self.assertEqual(len(candidates), 2)
    def test_candidate_order_follows_transaction_order(self):
        transactions = [
            _dossier("PA-TC-0009", 9, findings=[_finding(title="Survey conflict")]),
            _dossier("PA-TC-0007", 7, findings=[_finding(title="A mortgage")]),
        ]
        candidates = _collect_candidates(transactions)
        self.assertEqual(
            [candidate["title"] for candidate in candidates],
            ["Survey conflict", "A mortgage"],
        )
    def test_dossiers_without_findings_carry_no_candidates(self):
        transactions = [_dossier("PA-TC-0004", 4, status="PENDING_NOT_VERIFIED")]
        self.assertEqual(_collect_candidates(transactions), [])
class TestSeverityGate(unittest.TestCase):
    """CRITICAL sits behind an app gate: sourced documents + implication."""
    def _assemble_critical(self):
        candidates = _collect_candidates([_dossier("PA-TC-0007", 7, findings=[
            _finding(evidence=[], significance="UNRESOLVED"),
        ])])
        drafts = ConsolidationDraftResult.model_validate({
            "findings": [{
                "members": [0], "title": "Undischarged mortgage", "description": "d",
                "severity": "CRITICAL",
            }],
        })
        return lambda: _assemble(
            candidates, drafts, [], phase_a_hash=None, run_id=None,
            input_hash="hash", prior_container=None,
        )
    def test_critical_without_evidence_or_implication_is_refused(self):
        self.assertRaises(ValidationError, self._assemble_critical())
    def test_critical_with_sourced_documents_and_implication_is_allowed(self):
        candidates = _collect_candidates([_dossier("PA-TC-0007", 7, findings=[_finding()])])
        drafts = ConsolidationDraftResult.model_validate({
            "findings": [{
                "members": [0], "title": "Undischarged mortgage", "description": "d",
                "severity": "CRITICAL", "implication": "The parcel remains encumbered.",
            }],
        })
        result = _assemble(
            candidates, drafts, [], phase_a_hash=None, run_id=None,
            input_hash="hash", prior_container=None,
        )
        self.assertEqual(result.findings[0].severity.value, "CRITICAL")
    def test_caution_gap_only_is_allowed_without_documents(self):
        draft = FindingDraft.model_validate({
            "members": [0], "title": "Mortgage", "description": "desc", "severity": "CAUTION",
        })
        self.assertEqual(draft.severity.value, "CAUTION")
class TestAssembly(unittest.TestCase):
    def _assemble(self, drafts, candidates, prior=None, open_requirements=(OPEN_REQ,)):
        return _assemble(
            candidates, drafts, list(open_requirements),
            phase_a_hash="a-hash", run_id="r-1", input_hash="in-hash", prior_container=prior,
        )
    def test_app_owns_identity_and_coverage(self):
        candidates = _collect_candidates([
            _dossier("PA-TC-0007", 7, findings=[_finding()]),
            _dossier("PA-TC-0008", 8, findings=[_finding()]),
        ])
        drafts = ConsolidationDraftResult.model_validate({
            "findings": [{
                "members": [0], "title": "Undischarged mortgage on the parent parcel",
                "description": "A recorded memorandum of deposit stands undischarged.",
                "severity": "CRITICAL", "confidence": "HIGH",
                "implication": "The parcel remains encumbered.",
                "required_customer_action": "Obtain the discharge entry.",
            }],
        })
        result = self._assemble(drafts, candidates)
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.finding_id, "PF-001")
        self.assertEqual(finding.status.value, "OPEN")
        self.assertEqual(finding.affected_tx_ids, ["PA-TC-0007", "PA-TC-0008"])
        self.assertEqual(finding.documents[0].doc_id, "DOC14")
        self.assertEqual(finding.documents[0].pages, "2-3")
        self.assertEqual(finding.evidence_gaps, [GAP_LABEL])
        self.assertEqual(
            [ref.tx_id for ref in finding.consolidation.dossier_refs],
            ["PA-TC-0007", "PA-TC-0008"],
        )
        self.assertEqual(
            finding.consolidation.dedup_keys, [_dedup_key_text(candidates[0]["key"])],
        )
        self.assertEqual(result.provenance.source_hashes.findings, "in-hash")
    def test_unaffected_transactions_do_not_gain_gap_labels(self):
        candidates = _collect_candidates([_dossier("PA-TC-0007", 7, findings=[_finding()])])
        drafts = ConsolidationDraftResult.model_validate({
            "findings": [{"members": [0], "title": "Mortgage", "description": "d"}],
        })
        result = self._assemble(drafts, candidates)
        self.assertEqual(result.findings[0].evidence_gaps, [])
    def test_finding_ids_carry_forward_when_content_keys_survive(self):
        prior = {"result": {"findings": [{
            "finding_id": "PF-001",
            "consolidation": {"dedup_keys": ["encumbrance|undischarged mortgage on the parent parcel|DOC14"]},
        }]}}
        transactions = [
            _dossier("PA-TC-0007", 7, findings=[_finding()]),
            _dossier("PA-TC-0008", 8, findings=[
                _finding(evidence=[{"doc_id": "DOC15", "pages": "5"}]),
            ]),
        ]
        candidates = _collect_candidates(transactions)
        drafts = ConsolidationDraftResult.model_validate({
            "findings": [
                {"members": [0], "title": "Undischarged mortgage on the parent parcel",
                 "description": "The parent-parcel memorandum stands undischarged."},
                {"members": [1], "title": "Mortgage intake record",
                 "description": "The intake record shows the same charge."},
            ],
        })
        result = self._assemble(drafts, candidates, prior=prior)
        # Surviving content identity keeps PF-001; the new group takes the next id.
        self.assertEqual([f.finding_id for f in result.findings], ["PF-001", "PF-002"])
    def test_contradiction_sides_come_from_candidate_sources(self):
        candidates = _collect_candidates([
            _dossier("PA-TC-0001", 1, findings=[
                _finding(title="Survey 699-A/14", category="CHAIN_GAP",
                         evidence=[{"doc_id": "D1", "pages": ""}]),
            ]),
            _dossier("PA-TC-0002", 2, findings=[
                _finding(title="Survey 699-B/14", category="CHAIN_GAP",
                         evidence=[{"doc_id": "D2", "pages": ""}]),
            ]),
        ])
        drafts = ConsolidationDraftResult.model_validate({
            "findings": [
                {"members": [0], "title": "Survey 699-A/14",
                 "description": "Parent deed cites 699-A/14."},
                {"members": [1], "title": "Survey 699-B/14",
                 "description": "Conversion order cites 699-B/14."},
            ],
            "contradictions": [{
                "members": [0, 1], "description": "The measured survey number conflicts.",
                "resolution_guidance": "Recheck the parent deed page.",
            }],
        })
        result = self._assemble(drafts, candidates)
        self.assertEqual(len(result.contradictions), 1)
        contradiction = result.contradictions[0]
        self.assertEqual([side.tx_id for side in contradiction.sides], ["PA-TC-0001", "PA-TC-0002"])
        self.assertEqual(contradiction.resolution_guidance, "Recheck the parent deed page.")
    def test_unresolved_dependencies_reference_open_requirements_only(self):
        candidates = _collect_candidates([_dossier("PA-TC-0007", 7, findings=[_finding()])])
        drafts = ConsolidationDraftResult.model_validate({
            "findings": [{"members": [0], "title": "Mortgage", "description": "d"}],
            "unresolved_dependencies": ["REQ-0002", "REQ-4040"],
        })
        result = self._assemble(drafts, candidates)
        self.assertEqual(result.unresolved_dependencies, ["REQ-0002"])
class TestEndpoint(unittest.TestCase):
    """consolidate_findings end-to-end with the DB and the model faked."""
    def _patch_repos(self, container=None, requirements=(), results=(), chain=(),
                     docs=({"doc_id": "DOC14"},), phase_a=None):
        return patch.multiple(
            agent_repo,
            list_persisted_transaction_results=lambda case_id: list(results),
            get_persisted_title_chain_entries=lambda case_id: list(chain),
            get_agent_documents=lambda case_id: list(docs),
            list_requirements=lambda case_id, status=None: list(requirements),
            get_property_findings=lambda case_id: container,
            get_property_findings_raw=lambda case_id: container,
            get_agent_result=lambda case_id: phase_a or {},
        )
    def test_pending_results_consolidate_in_partial_mode(self):
        # C4 / D2 / §3.2 row PENDING: the skip is retired. Terminal dossiers
        # consolidate (`ok`); the pending tx contributes no content but is
        # reported; the gate defers id-retiring transitions (row 43).
        saved = []
        def fake_save(case_id, container):
            saved.append(container)
        with patch.object(agent_repo, "save_property_findings",
                          side_effect=fake_save), \
                self._patch_repos(results=[
                    _dossier("PA-TC-0007", 7, findings=[_finding()]),
                    _dossier("PA-TC-0004", 4, status="PENDING_NOT_VERIFIED",
                             findings=[_finding()]),
                ]), \
                patch("backend.services.consolidation.complete_json",
                      return_value={"findings": [
                          {"members": [0], "title": "Mortgage", "description": "d"}]}) \
                    as complete:
            outcome = consolidate_findings("CASE1")
        self.assertEqual(outcome["status"], "ok")
        complete.assert_called_once()
        result = saved[0]["result"]
        self.assertEqual(result["integrity"]["input_state"], "PENDING")
        self.assertEqual(result["readiness"]["state"], "PARTIAL")
        self.assertEqual(result["readiness"]["pending_tx_ids"], ["PA-TC-0004"])
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["affected_tx_ids"], ["PA-TC-0007"])
        coverage = {d["tx_id"]: d["terminal"] for d in result["coverage"]["dossiers"]}
        self.assertEqual(coverage, {"PA-TC-0007": True, "PA-TC-0004": False})
    def test_no_candidates_persist_an_honest_empty_container(self):
        saved = {}
        def fake_save(case_id, container):
            saved[case_id] = container
        with patch.object(agent_repo, "save_property_findings", side_effect=fake_save), \
                self._patch_repos(results=[_dossier("PA-TC-0001", 1)]), \
                patch("backend.services.consolidation.complete_json") as complete:
            outcome = consolidate_findings("CASE1")
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(outcome["container"]["result"]["findings"], [])
        self.assertEqual(outcome["container"]["container_version"], "2.0")
        complete.assert_not_called()
        self.assertIn("input_hash", saved["CASE1"])
    def test_identical_inputs_return_cached_container_without_model_call(self):
        store = {}
        results = [_dossier("PA-TC-0007", 7, findings=[_finding()])]
        def fake_get(case_id):
            return store.get("container")
        def fake_save(case_id, container):
            store["container"] = container
        draft = {"findings": [{"members": [0], "title": "Mortgage", "description": "d"}]}
        with patch.object(agent_repo, "get_property_findings", side_effect=fake_get), \
                patch.object(agent_repo, "get_property_findings_raw",
                             return_value=None), \
                patch.object(agent_repo, "save_property_findings", side_effect=fake_save), \
                patch.object(agent_repo, "list_persisted_transaction_results",
                             return_value=results), \
                patch.object(agent_repo, "get_persisted_title_chain_entries",
                             return_value=[]), \
                patch.object(agent_repo, "get_agent_documents",
                             return_value=[{"doc_id": "DOC14"}]), \
                patch.object(agent_repo, "list_requirements", return_value=[]), \
                patch.object(agent_repo, "get_agent_result", return_value={}), \
                patch("backend.services.consolidation.complete_json",
                      return_value=draft) as complete:
            first = consolidate_findings("CASE1")
            second = consolidate_findings("CASE1")
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["container"], first["container"])
        complete.assert_called_once()  # one model pass; replay came from the cache
        self.assertEqual(store["container"]["result"]["findings"][0]["finding_id"], "PF-001")
    def test_model_pass_failure_is_a_non_fatal_outcome(self):
        with patch.object(agent_repo, "save_property_findings") as save, \
                self._patch_repos(results=[_dossier("PA-TC-0007", 7, findings=[_finding()])]), \
                patch("backend.services.consolidation.complete_json",
                      side_effect=Exception("provider down")):
            outcome = consolidate_findings("CASE1")
        self.assertEqual(outcome["status"], "error")
        self.assertIn("consolidation failed", outcome["reason"])
        save.assert_not_called()
    def test_bad_draft_indexes_are_refused_before_persistence(self):
        with patch.object(agent_repo, "save_property_findings") as save, \
                self._patch_repos(results=[_dossier("PA-TC-0007", 7, findings=[_finding()])]), \
                patch("backend.services.consolidation.complete_json",
                      return_value={"findings": [{
                          "members": [7], "title": "X", "description": "y",
                      }]}):
            outcome = consolidate_findings("CASE1")
        self.assertEqual(outcome["status"], "error")
        save.assert_not_called()
class TestStrictInputHardening(unittest.TestCase):
    """C1 (§13): strict reads, two-level row/finding validation, roster-owned
    evidence, run-scoped registration, v1-only persistence."""
    def _run_case(self, *, results=(), chain=(), container=None,
                 documents=({"doc_id": "DOC14"},), draft=None, requirements=()):
        """End-to-end service run with faked DB + pinned model draft."""
        draft = draft if draft is not None else {"findings": []}
        saved = []
        with patch.object(agent_repo, "save_property_findings",
                          side_effect=lambda case_id, c: saved.append(c)) as save, \
                self._repos(results=results, chain=chain, container=container,
                            documents=documents, requirements=requirements), \
                patch("backend.services.consolidation.complete_json",
                      return_value=draft) as complete:
            outcome = consolidate_findings("CASE1")
        return {"outcome": outcome, "save": save, "complete": complete, "saved": saved}
    def _repos(self, *, results=(), chain=(), container=None,
               documents=({"doc_id": "DOC14"},), requirements=()):
        return patch.multiple(
            agent_repo,
            list_persisted_transaction_results=lambda case_id: list(results),
            get_persisted_title_chain_entries=lambda case_id: list(chain),
            get_agent_documents=lambda case_id: list(documents),
            list_requirements=lambda case_id, status=None: list(requirements),
            get_property_findings=lambda case_id: container,
            get_property_findings_raw=lambda case_id: container,
            get_agent_result=lambda case_id: {},
        )
    # -- 1. strict reader: valid empty vs corrupt vs unavailable --------------
    def test_strict_reader_distinguishes_valid_empty_from_unavailable(self):
        # Valid empty: no rows + no chain txs → honest EMPTY, ok run.
        run = self._run_case(results=[], chain=[])
        self.assertEqual(run["outcome"]["status"], "ok")
        self.assertEqual(run["outcome"]["registration"]["input_state"], "EMPTY")
        self.assertEqual(len(run["saved"]), 1)  # honest empty container, v1 path
        self.assertEqual(run["save"].call_count, 1)
        # Unavailable: a database failure is never "an empty transaction list".
        run = self._reader_fails(ConnectionError("db unavailable"))
        self.assertEqual(run["outcome"]["status"], "blocked")
        self.assertEqual(run["outcome"]["retryable"], True)
        self.assertEqual(run["outcome"]["registration"]["input_state"], "UNAVAILABLE")
        self.assertEqual(run["save"].call_count, 0)
    def _reader_fails(self, error):
        with patch.object(agent_repo, "save_property_findings") as save, \
                patch.object(agent_repo, "list_persisted_transaction_results",
                             side_effect=error), \
                patch.object(agent_repo, "get_persisted_title_chain_entries",
                             return_value=[]), \
                patch.object(agent_repo, "get_agent_documents",
                             return_value=[{"doc_id": "DOC14"}]), \
                patch.object(agent_repo, "list_requirements", return_value=[]), \
                patch.object(agent_repo, "get_agent_result", return_value={}), \
                patch.object(agent_repo, "get_property_findings", return_value=None), \
                patch.object(agent_repo, "get_property_findings_raw", return_value=None), \
                patch("backend.services.consolidation.complete_json") as complete:
            outcome = consolidate_findings("CASE1")
        return {"outcome": outcome, "save": save, "complete": complete}
    # -- 2. corrupt JSON / unexpected top-level shape blocks ------------------
    def test_corrupt_read_blocks_consolidation(self):
        run = self._reader_fails(ValueError("unexpected top-level shape: int"))
        self.assertEqual(run["outcome"]["status"], "blocked")
        self.assertTrue(run["outcome"]["retryable"])
        self.assertEqual(run["outcome"]["registration"]["input_state"], "CORRUPT")
        self.assertIn("strictly", run["outcome"]["reason"])
        run["save"].assert_not_called()
        run["complete"].assert_not_called()
    # -- 3./4. structurally invalid rows block the whole run, no salvage ------
    def test_structurally_invalid_row_blocks_the_run(self):
        good = _dossier("PA-TC-0007", 7, findings=[_finding()])
        run = self._run_case(results=[good, "a scalar row"],
                            draft={"findings": [{"members": [0], "title": "M", "description": "d"}]})
        self.assertEqual(run["outcome"]["status"], "blocked")
        self.assertEqual(run["outcome"]["registration"]["input_state"], "CORRUPT")
        self.assertIn("not an object", run["outcome"]["reason"])
        self.assertEqual(run["outcome"]["registration"]["malformed_observations"], [])
        run["save"].assert_not_called()
        run["complete"].assert_not_called()
    def test_unreadable_result_structure_blocks_without_partial_persistence(self):
        good = _dossier("PA-TC-0008", 8, findings=[_finding()])
        broken = dict(_dossier("PA-TC-0007", 7), findings={"tx_id": "not-a-list"})
        for bad in (
            broken,
            dict(_dossier("PA-TC-0006", 6, findings=[_finding()]), tx_id=None),
            dict(_dossier("PA-TC-0005", 5, findings=[_finding()]), status=7),
        ):
            run = self._run_case(results=[good, bad], draft={"findings": []})
            self.assertEqual(run["outcome"]["status"], "blocked", bad["tx_id"])
            self.assertEqual(run["save"].call_count, 0, bad["tx_id"])
    # -- 5./6. malformed findings inside a valid row: exclude + register ------
    # --     valid siblings keep consolidating through the normal path --------
    def test_malformed_finding_excluded_and_registered_siblings_continue(self):
        row = _dossier("PA-TC-0007", 7, findings=[
            "not-an-object",                                # position 0
            _finding(),                                     # position 1 — valid TF-001
            {key: value for key, value in _finding(title="Second entry").items()
             if key != "finding_id"},                       # position 2 — malformed
        ])
        run = self._run_case(
            results=[row, _dossier("PA-TC-0008", 8, findings=[_finding(title="Second entry", finding_id="TF-002")])],
            draft={"findings": [
                {"members": [0], "title": "Mortgage", "description": "d"},
                {"members": [1], "title": "Second entry", "description": "e"},
            ]})
        self.assertEqual(run["outcome"]["status"], "ok")
        registration = run["outcome"]["registration"]
        self.assertEqual(registration["malformed_observations"], [
            {"tx_id": "PA-TC-0007", "position": 0, "issue": "not an object"},
            {"tx_id": "PA-TC-0007", "position": 2, "issue": "missing or invalid finding_id"},
        ])
        findings = run["saved"][0]["result"]["findings"]
        self.assertEqual(len(findings), 2)  # valid siblings still consolidate
        self.assertEqual(findings[0]["finding_id"], "PF-001")
        self.assertEqual(
            [ref["finding_index"] for ref in findings[0]["consolidation"]["dossier_refs"]], [1],
        )  # persisted position, not renumbered after the excluded entry
        self.assertEqual(
            [(side["tx_id"], side["finding_index"])
             for side in findings[1]["consolidation"]["dossier_refs"]],
            [("PA-TC-0008", 0)],
        )  # the sibling row's valid finding kept its own persisted position
        run["save"].assert_called_once()
    # -- 7./8. evidence-reference ownership -----------------------------------
    def test_foreign_evidence_ref_dropped_registered_and_gap_noted(self):
        row = _dossier("PA-TC-0007", 7, findings=[_finding(evidence=[
            {"doc_id": "DOC14", "pages": "2-3"}, {"doc_id": "DOC99", "pages": "9"},
        ])])
        run = self._run_case(
            results=[row],
            draft={"findings": [{"members": [0], "title": "Mortgage", "description": "d"}]})
        self.assertEqual(run["outcome"]["status"], "ok")
        self.assertEqual(run["outcome"]["registration"]["excluded_evidence_refs"],
                         [{"doc_id": "DOC99", "reason": "not owned by the case"}])
        finding = run["saved"][0]["result"]["findings"][0]
        self.assertEqual([(ref["doc_id"], ref["pages"]) for ref in finding["documents"]],
                         [("DOC14", "2-3")])
        self.assertIn("[excluded evidence ref DOC99: not owned by the case]",
                      finding["evidence_gaps"])
    def test_owned_evidence_refs_stay_available(self):
        docs = ({"doc_id": "DOC14"}, {"doc_id": "DOC15"})
        row = _dossier("PA-TC-0007", 7, findings=[_finding(evidence=[
            {"doc_id": "DOC14", "pages": "2-3"}, {"doc_id": "DOC15", "pages": "5"},
        ])])
        run = self._run_case(
            results=[row], documents=docs,
            draft={"findings": [{"members": [0], "title": "Mortgage", "description": "d"}]})
        self.assertEqual(run["outcome"]["status"], "ok")
        self.assertEqual(run["outcome"]["registration"]["excluded_evidence_refs"], [])
        finding = run["saved"][0]["result"]["findings"][0]
        self.assertEqual([(ref["doc_id"], ref["pages"]) for ref in finding["documents"]],
                         [("DOC14", "2-3"), ("DOC15", "5")])
        self.assertFalse(any("excluded evidence ref" in gap
                             for gap in finding["evidence_gaps"]))
    # -- 9./10. run-scoped registration; D7 disclosure ------------------------
    def test_registration_returned_by_service_and_stored_in_memory(self):
        run = self._run_case(
            results=[_dossier("PA-TC-0007", 7, findings=[_finding()])],
            draft={"findings": [{"members": [0], "title": "Mortgage", "description": "d"}]})
        outcome = run["outcome"]
        self.assertEqual(outcome["status"], "ok")
        registration = outcome["registration"]
        self.assertEqual(set(registration), {
            "input_state", "malformed_observations", "excluded_evidence_refs", "disclosures",
        })
        self.assertEqual(registration["input_state"], "READY")
        self.assertEqual(registration["malformed_observations"], [])
        self.assertEqual(registration["excluded_evidence_refs"], [])
        # The done path stores it verbatim (orchestration propagation).
        done_outcome, _containers, saved_states = TestDonePathPhaseC()._run_done_path(
            results=[_dossier("PA-TC-0001", 1)], chain=[_dossier("PA-TC-0001", 1)])
        memory, _status = saved_states[-1]
        self.assertEqual(memory["phase_c"]["registration"]["input_state"], "READY")
    def test_d7_disclosure_is_registered(self):
        run = self._run_case(results=[])
        self.assertEqual(run["outcome"]["registration"]["disclosures"], [_D7_DISCLOSURE])
    # -- 11. C3 persists the v2 container shape with the materialized blocks --
    def test_persisted_container_is_v2_shape_with_integrity_blocks(self):
        run = self._run_case(
            results=[_dossier("PA-TC-0007", 7, findings=[_finding()])],
            draft={"findings": [{"members": [0], "title": "Mortgage", "description": "d"}]})
        container = run["saved"][0]
        self.assertEqual(set(container), {"container_version", "input_hash", "result"})
        self.assertEqual(container["container_version"], "2.0")
        self.assertEqual(
            set(container["result"]), {"findings", "contradictions", "unresolved_dependencies",
                                       "provenance", "coverage", "integrity", "readiness",
                                       "correlations"})
        readiness = container["result"]["readiness"]
        self.assertEqual(readiness["state"], "COMPLETE")
        self.assertEqual(container["result"]["correlations"], [])
        self.assertEqual(container["result"]["coverage"]["dossiers"][0]["tx_id"], "PA-TC-0007")
        self.assertTrue(container["result"]["coverage"]["dossiers"][0]["terminal"])
    # -- 12. blocked/error preserve the prior known-good container ------------
    def test_blocked_and_error_never_overwrite_the_prior_container(self):
        prior = {"container_version": "1.0", "input_hash": "old", "result": {"findings": []}}
        with patch.object(agent_repo, "save_property_findings") as save, \
                patch.object(agent_repo, "list_persisted_transaction_results",
                             side_effect=ValueError("unreadable")), \
                patch.object(agent_repo, "get_agent_documents", return_value=[]), \
                patch.object(agent_repo, "get_property_findings", return_value=prior):
            outcome = consolidate_findings("CASE1")
        self.assertEqual(outcome["status"], "blocked")
        save.assert_not_called()
        with patch.object(agent_repo, "save_property_findings") as save, \
                self._repos(results=[_dossier("PA-TC-0007", 7,
                                               findings=[_finding()])],
                            container=prior), \
                patch("backend.services.consolidation.complete_json",
                      side_effect=Exception("provider exploded")):
            outcome = consolidate_findings("CASE1")
        self.assertEqual(outcome["status"], "error")
        self.assertEqual(outcome["registration"]["input_state"], "READY")
        save.assert_not_called()
    # -- 15. D4 exhaustion message; D6 draft-key stripping --------------------
    def test_d4_id_exhaustion_reports_a_clear_error(self):
        prior = {"result": {"findings": [{
            "finding_id": "PF-999",
            "consolidation": {"dedup_keys": ["encumbrance|surviving group|DOC14"]},
        }]}}
        candidates = _collect_candidates([
            _dossier("PA-TC-0007", 7, findings=[_finding()]),
        ])
        drafts = ConsolidationDraftResult.model_validate({
            "findings": [{"members": [0], "title": "New group", "description": "d"}],
        })
        with self.assertRaisesRegex(ValueError, "PF id space exhausted"):
            _assemble(candidates, drafts, [], phase_a_hash=None, run_id=None,
                      input_hash="h", prior_container=prior)
    def test_d6_draft_id_bookkeeping_keys_are_stripped(self):
        draft = validate_draft({"findings": [{
            "members": [0], "title": "Mortgage", "description": "d",
            "status": "draft", "finding_id": "TF-001", "id": "PF-999", "pf_id": "x",
        }], "contradictions": [{
            "members": [0, 1], "description": "c", "status": "draft",
        }]})
        # The stripped keys never reach the validated model; drafts are intact.
        self.assertEqual(len(draft.findings), 1)
        self.assertEqual(draft.findings[0].members, [0])
        self.assertEqual(len(draft.contradictions), 1)
    def test_d6_junk_payloads_fail_as_before(self):
        with self.assertRaisesRegex(ValueError, "consolidation draft failed schema validation"):
            validate_draft({"findings": [{"members": [0], "title": "M", "description": "d",
                                          "unknown_key": 1}]})
class TestDonePathPhaseC(unittest.TestCase):
    """The _run done path truly runs consolidation (repo faked, model not needed)."""
    def _run_done_path(self, results, chain=(), reader_error=None):
        """Drive the agent done path with faked repos; returns
        (outcome, saved_containers, saved_states)."""
        from backend.services import cleartitle_agent
        self.cleartitle_agent = cleartitle_agent
        def fake_build_phase_a(case_id, docs):
            return {"title_chain": [{
                "chain_position": 1,
                "documented_transaction": {"transaction_type": "Sale"},
            }]}
        saved_result = {
            "tx_id": "PA-TC-0001", "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
            "report": "done",
        }
        saved_containers = []
        saved_states = []
        reader = patch.object(
            agent_repo, "list_persisted_transaction_results",
            side_effect=reader_error if reader_error is not None else None,
            return_value=[] if reader_error is not None else list(results),
        )
        with patch.object(agent_repo, "get_agent_documents",
                          return_value=[{"doc_id": "DOC1"}]), \
                patch.object(agent_repo, "get_agent_memory", return_value={}), \
                patch.object(agent_repo, "get_agent_result", return_value={}), \
                reader, \
                patch.object(agent_repo, "get_persisted_title_chain_entries",
                             return_value=list(chain)), \
                patch.object(agent_repo, "list_requirements", return_value=[]), \
                patch.object(agent_repo, "get_property_findings", return_value=None), \
                patch.object(agent_repo, "get_property_findings_raw", return_value=None), \
                patch.object(agent_repo, "save_property_findings",
                             side_effect=lambda case_id, c: saved_containers.append(c)), \
                patch.object(agent_repo, "set_agent_status"), \
                patch.object(agent_repo, "get_transaction_result",
                             side_effect=[None, saved_result]), \
                patch.object(cleartitle_agent, "ensure_summaries"), \
                patch.object(cleartitle_agent, "_build_phase_a",
                             side_effect=fake_build_phase_a), \
                patch.object(cleartitle_agent, "_save_state",
                             side_effect=lambda case_id, memory, status: saved_states.append(
                                 (memory, status))), \
                patch.object(cleartitle_agent, "_sync_case_verdict"), \
                patch.object(cleartitle_agent, "_verify_transaction",
                             return_value=SimpleNamespace(
                                 missing_requests=[],
                                 saved_results=[{"tx_id": "PA-TC-0001"}],
                                 selected_document_ids=set(),
                             )):
            outcome = cleartitle_agent._run("CASE1")
        return outcome, saved_containers, saved_states
    def test_run_done_path_consolidates_and_records_phase_c(self):
        outcome, saved_containers, saved_states = self._run_done_path(results=[])
        self.assertEqual(outcome["status"], self.cleartitle_agent.STATUS_DONE)
        self.assertEqual(outcome["consolidation"], "ok")
        self.assertEqual(len(saved_containers), 1)
        self.assertEqual(saved_containers[0]["result"]["findings"], [])
        memory, status = saved_states[-1]
        self.assertEqual(status, self.cleartitle_agent.STATUS_DONE)
        self.assertEqual(memory["stage"], "done")
        self.assertEqual(memory["phase_c"]["status"], "ok")
        self.assertEqual(memory["phase_c"]["findings"], 0)
        registration = memory["phase_c"]["registration"]
        self.assertEqual(registration["input_state"], "EMPTY")
        self.assertEqual(registration["disclosures"], [_D7_DISCLOSURE])
        self.assertIsNone(memory["paused_transaction"])
    def test_done_path_contains_blocked_consolidation_without_writes(self):
        # A blocked Phase C never sinks the run (failure containment) and the
        # orchestration stores the run-scoped registration, not a container.
        outcome, saved_containers, saved_states = self._run_done_path(
            results=[], reader_error=ValueError("unexpected top-level shape"))
        self.assertEqual(outcome["status"], self.cleartitle_agent.STATUS_DONE)
        self.assertEqual(outcome["consolidation"], "blocked")
        self.assertEqual(saved_containers, [])
        memory, _status = saved_states[-1]
        self.assertEqual(memory["phase_c"]["status"], "blocked")
        self.assertEqual(memory["phase_c"]["registration"]["input_state"], "CORRUPT")
        self.assertEqual(memory["phase_c"]["findings"], 0)
    def test_done_path_records_a_pending_partial_consolidation(self):
        # Partial mode flows through the agent done path end to end: a
        # checkpointed PENDING tx hides its dossier content while the
        # consolidation stays `ok` in PENDING state, and the hook records
        # the outcome verbatim (run PF machinery aside, no special casing).
        from unittest.mock import patch
        rows = [
            _dossier("PA-TC-0004", 4, status="PENDING_NOT_VERIFIED",
                     findings=[_finding("A pending checkpoint finding")]),
            _dossier("PA-TC-0007", 7, findings=[_finding()]),
        ]
        chain = [
            {"tx_id": "PA-TC-0004", "chain_position": 4,
             "documented_transaction": {"sequence": 4}},
            {"tx_id": "PA-TC-0007", "chain_position": 7,
             "documented_transaction": {"sequence": 7}},
        ]
        draft = {"findings": [{"members": [0], "title": "Sale issue",
                               "description": "terminal dossier content"}]}
        with patch("backend.services.consolidation.complete_json",
                   return_value=draft):
            outcome, saved_containers, saved_states = self._run_done_path(
                results=rows, chain=chain)
        self.assertEqual(outcome["status"], self.cleartitle_agent.STATUS_DONE)
        self.assertEqual(outcome["consolidation"], "ok")
        result = saved_containers[0]["result"]
        self.assertEqual(result["integrity"]["input_state"], "PENDING")
        self.assertEqual(result["readiness"]["pending_tx_ids"], ["PA-TC-0004"])
        # only the terminal dossier's finding is consolidated; the pending
        # one surfaces as transport state (no content absorbed)
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["affected_tx_ids"], ["PA-TC-0007"])
        memory, _status = saved_states[-1]
        self.assertEqual(memory["phase_c"]["status"], "ok")
        self.assertEqual(memory["phase_c"]["findings"], 1)
if __name__ == "__main__":
    unittest.main()
