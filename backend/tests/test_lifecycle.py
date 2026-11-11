"""C3 — §6.2 lifecycle wiring, container blocks, correlations, endpoint keys.

Focused coverage for the C3 increment: the deterministic status ladder
(PENDING_EVIDENCE / PARTIALLY_RESOLVED / RESOLVED / DISPUTED, derived from the
requirement-ledger ask review — satisfaction alone never resolves), the
partial-run gate deferrals, coverage_gap retention for uncovered
disappearances, source_withdrawn/source_corrected bookkeeping, contradiction
content keys with refresh dedup, deterministic correlation edges (§9), the
coverage/integrity/readiness blocks (§8.1), and the D8 additive endpoint keys.
"""

import asyncio
import unittest
from unittest.mock import Mock, patch

from backend.database.repositories import agent_repo
from backend.schemas.analysis import ConsolidationDraftResult
from backend.services.consolidation import (
    _assemble,
    _candidate_bundle,
    _collect_candidates,
    _od3,
    _solo_key,
    content_hash,
    consolidate_findings,
)
from backend.routers import results as router_module

NOW = "2026-11-06T00:00:00+00:00"
CASE = "CASE1"


def _finding(title="Unregistered sale of reserved plot", category="authority",
             text="The deed was never registered.", evidence=None,
             finding_id="TF-001"):
    return {
        "finding_id": finding_id,
        "significance": "ESTABLISHED",
        "category": category,
        "title": title,
        "text": text,
        "evidence": evidence if evidence is not None else [{"doc_id": "DOC1", "pages": "2"}],
        "is_legal_defect": True,
    }


def _dossier(tx_id, sequence, status="VERIFIED_WITH_AVAILABLE_EVIDENCE",
             findings=None, evidence_status=None, transaction_metadata=None):
    row = {
        "tx_id": tx_id, "sequence": sequence, "status": status,
        "findings": findings if findings is not None else [],
    }
    if evidence_status is not None:
        row["evidence_status"] = evidence_status
    if transaction_metadata is not None:
        row["transaction_metadata"] = transaction_metadata
    return row


def _obs(tf_id="TF-001", tx_id="PA-TC-0007", title="t", text_excerpt=""):
    return {
        "tf_id": tf_id, "tx_id": tx_id, "title": title, "text_excerpt": text_excerpt,
        "evidence_refs": [{"doc_id": "DOC1", "pages": "2"}],
    }


def _prior(finding_id="PF-001", status="OPEN"):
    return {
        "finding_id": finding_id, "status": status, "category": "authority",
        "title": "Unregistered sale", "description": "d", "severity": "CAUTION",
        "consolidation": {"dedup_keys": [], "run_id": None, "phase_a_hash": None,
                          "dossier_refs": [], "source_hashes": None},
        "source_observations": [], "lifecycle_events": [],
    }


def _req(rid="REQ-0001", owner="PA-TC-0007", status="OPEN", matched=None):
    return {
        "requirement_id": rid, "owner_tx_id": owner, "document_type": "X",
        "reason": "r", "status": status, "match_status": "MATCHED" if matched else None,
        "matched_doc_id": matched,
    }


DRAFT_ONE = {"findings": [{"members": [0], "title": "Unregistered transfer",
                           "description": "d"}]}
DRAFT_TWO = {"findings": [
    {"members": [0], "title": "First", "description": "d"},
    {"members": [1], "title": "Second", "description": "e"},
]}


def _simple_candidates(title="Unregistered sale of reserved plot", count=1,
                       finding_id_base="01"):
    rows = [
        _dossier(f"PA-TC-000{7 + i}", 7 + i, findings=[
            _finding(title=title if i == 0 else f"{title} variant {i}",
                     evidence=[{"doc_id": f"DOC{i + 2}", "pages": "2"}],
                     finding_id=f"TF-{finding_id_base}{i}"),
            ])
        for i in range(count)
    ]
    return rows, _collect_candidates(rows)


def _identity_of(candidate):
    key, _missing, _conflicts = _solo_key(_candidate_bundle(candidate, {}))
    return key


def _run_assemble(candidates, drafts, *, prior=None, registration=None, chain=(),
                  tx_by_id=None, open_requirements=(), all_requirements=None,
                  owned_doc_ids=None):
    return _assemble(
        candidates, ConsolidationDraftResult.model_validate(drafts), list(open_requirements),
        phase_a_hash=None, run_id="r", input_hash="IN", prior_container=prior,
        tx_by_id=tx_by_id or {}, chain_entries=list(chain),
        registration=registration if registration is not None else {},
        now=NOW, all_requirements=all_requirements, owned_doc_ids=owned_doc_ids,
        documents=[])


class TestLifecycleLadder(unittest.TestCase):
    """§6.2 derivation from the ask review; the model never sets status."""

    def _carried_result(self, status="OPEN", requirements=(), registration=None,
                        owned=("DOC1",), resolution_evidence=None):
        rows, candidates = _simple_candidates()
        prior = _prior()
        prior["identity_key"] = _identity_of(candidates[0])
        prior["status"] = status
        if resolution_evidence is not None:
            prior["resolution_evidence"] = resolution_evidence
        result = _run_assemble(
            candidates, DRAFT_ONE, prior={"result": {"findings": [prior]}},
            tx_by_id={"PA-TC-0007": rows[0]}, registration=registration,
            all_requirements=list(requirements) or None, owned_doc_ids=set(owned) if owned else None)
        return result.findings[0]

    def test_carried_open_becomes_pending_evidence_with_open_ask(self):
        finding = self._carried_result(requirements=[_req()])
        self.assertEqual(finding.status.value, "PENDING_EVIDENCE")
        pending_event = next(e for e in finding.lifecycle_events if e.reason == "pending_evidence")
        self.assertEqual(pending_event.refs, ["REQ-0001"])
        self.assertEqual(pending_event.decided_by, "app_rule:pending_evidence")

    def test_birth_stays_open_never_pending(self):
        rows, candidates = _simple_candidates()
        requirements = [_req()]
        result = _run_assemble(candidates, DRAFT_ONE, open_requirements=requirements,
                           all_requirements=requirements)
        self.assertEqual(result.findings[0].status.value, "OPEN")

    def test_partially_resolved_with_a_validated_match(self):
        finding = self._carried_result(
            requirements=[_req("REQ-0001", status="SATISFIED", matched="DOC1"),
                          _req("REQ-0002")])
        self.assertEqual(finding.status.value, "PARTIALLY_RESOLVED")
        self.assertTrue(all(e.doc_id == "DOC1" for e in finding.resolution_evidence))
        resolved_event = next(e for e in finding.lifecycle_events
                              if e.reason == "partially_resolved")
        self.assertEqual(resolved_event.refs, ["REQ-0001"])
        self.assertEqual(resolved_event.decided_by, "app_rule:partial_resolution")

    def test_satisfaction_alone_never_resolves(self):
        # SATISFIED without a roster-validated matched_doc_id stays unmet.
        finding = self._carried_result(
            requirements=[_req("REQ-0001", status="SATISFIED", matched=None)])
        self.assertEqual(finding.status.value, "PENDING_EVIDENCE")

    def test_direct_resolved_in_one_step_when_all_asks_covered(self):
        finding = self._carried_result(
            requirements=[_req("REQ-0001", status="SATISFIED", matched="DOC1"),
                          _req("REQ-0002", status="SATISFIED", matched="DOC1")])
        self.assertEqual(finding.status.value, "RESOLVED")
        self.assertTrue(finding.resolution_evidence)
        resolved = next(e for e in finding.lifecycle_events if e.reason == "resolved")
        self.assertEqual(resolved.refs, ["REQ-0001", "REQ-0002"])
        self.assertEqual(resolved.decided_by, "app_rule:resolution")
        self.assertEqual(resolved.from_status, "OPEN")

    def test_resolved_carries_with_zero_asks_and_only_one_carry_event(self):
        rows, candidates = _simple_candidates()
        prior = _prior(status="RESOLVED")
        prior["identity_key"] = _identity_of(candidates[0])
        prior["resolution_evidence"] = [{"doc_id": "DOC1"}]
        result = _run_assemble(
            candidates, DRAFT_ONE, prior={"result": {"findings": [prior]}},
            tx_by_id={"PA-TC-0007": rows[0]})
        finding = next(f for f in result.findings if f.finding_id == "PF-001")
        self.assertEqual(finding.status.value, "RESOLVED")
        reasons = [e.reason for e in finding.lifecycle_events]
        self.assertEqual(reasons, ["id_carried_by_identity_key"])

    def test_resolved_reopens_when_a_resolution_requirement_returns(self):
        finding = self._carried_result(
            status="RESOLVED", requirements=[_req("REQ-0001")], owned=("DOC1",),
            resolution_evidence=[{"doc_id": "DOC1"}])
        self.assertEqual(finding.status.value, "OPEN")
        reopened = next(e for e in finding.lifecycle_events
                        if e.reason == "resolution_requirement_reopened")
        self.assertEqual(reopened.decided_by, "app_rule:resolution_reopened")
        self.assertEqual(reopened.refs, ["REQ-0001"])

    def test_disputed_at_birth_and_released_when_contradiction_clears(self):
        rows, candidates = _simple_candidates(count=2)
        drafts = {"findings": list(DRAFT_TWO["findings"]),
                  "contradictions": [{"members": [0, 1],
                                      "description": "The survey extents conflict."}]}
        result = _run_assemble(candidates, drafts)
        for finding in result.findings:
            self.assertEqual(finding.status.value, "DISPUTED")
            disputed = next(e for e in finding.lifecycle_events if e.reason == "disputed")
            self.assertEqual(disputed.decided_by, "app_rule:contradiction")

        # carried DISPUTED with the contradiction gone reopens to OPEN
        rows, candidates = _simple_candidates()
        prior = _prior(status="DISPUTED")
        prior["identity_key"] = _identity_of(candidates[0])
        result = _run_assemble(candidates, DRAFT_ONE,
                           prior={"result": {"findings": [prior]}},
                           tx_by_id={"PA-TC-0007": rows[0]})
        finding = result.findings[0]
        self.assertEqual(finding.status.value, "OPEN")
        self.assertIn("contradiction_cleared",
                      [e.reason for e in finding.lifecycle_events])

    def test_partial_run_gate_defers_resolution(self):
        rows, candidates = _simple_candidates()
        prior = _prior()
        prior["identity_key"] = _identity_of(candidates[0])
        registration = {
            "malformed_observations": [{"tx_id": "PA-TC-0009", "position": 0,
                                        "issue": "not an object"}],
            "excluded_evidence_refs": [], "disclosures": [],
        }
        result = _run_assemble(
            candidates, DRAFT_ONE, prior={"result": {"findings": [prior]}},
            tx_by_id={"PA-TC-0007": rows[0]}, registration=registration,
            all_requirements=[_req("REQ-0001", matched="DOC1", status="SATISFIED")],
            owned_doc_ids={"DOC1"})
        finding = result.findings[0]
        self.assertEqual(finding.status.value, "OPEN")  # RESOLVED was deferred
        deferred = [e for e in finding.lifecycle_events
                    if e.reason == "transition_deferred"]
        self.assertEqual(len(deferred), 1)
        self.assertEqual(deferred[0].decided_by, "app_rule:partial_run_gate")
        self.assertEqual(deferred[0].from_status, "OPEN")
        self.assertEqual(deferred[0].to_status, "OPEN")
        self.assertNotIn("resolved", [e.reason for e in finding.lifecycle_events])

    def test_unverifiable_sufficiency_from_explicit_recital_basis(self):
        rows = [_dossier("PA-TC-0007", 7, findings=[_finding()], evidence_status="RECITAL")]
        candidates = _collect_candidates(rows)
        result = _run_assemble(candidates, DRAFT_ONE, tx_by_id={"PA-TC-0007": rows[0]})
        self.assertEqual(result.findings[0].evidence_sufficiency.value, "UNVERIFIABLE")


class TestDisappearances(unittest.TestCase):
    """§6.3-1 coverage_gap retention, the §6.2 guard, and §6.3-4 events."""

    def test_vanished_prior_is_retained_with_a_coverage_gap(self):
        prior = _prior()
        prior["source_observations"] = [_obs(tx_id="PA-TC-0001")]
        rows, candidates = _simple_candidates()  # only PA-TC-0007 observed this run
        result = _run_assemble(candidates, DRAFT_ONE,
                           prior={"result": {"findings": [prior]}},
                           tx_by_id={})  # the observing tx is missing → uncovered
        finding = next(f for f in result.findings if f.finding_id == "PF-001")
        self.assertEqual(finding.status.value, "OPEN")  # retained at current status
        gap = next(e for e in finding.lifecycle_events if e.reason == "coverage_gap")
        self.assertEqual(gap.refs, ["PA-TC-0001/TF-001"])
        self.assertEqual(gap.decided_by, "app_rule:coverage_gap")

    def test_covered_disappearance_still_supersedes(self):
        prior = _prior()
        prior["source_observations"] = [_obs()]
        rows, candidates = _simple_candidates()  # TF-002 observed: identity vanished
        candidates = _collect_candidates([
            _dossier("PA-TC-0007", 7, findings=[
                _finding(title="Re-observed different issue", finding_id="TF-002")])])
        result = _run_assemble(candidates, DRAFT_ONE,
                           prior={"result": {"findings": [prior]}},
                           tx_by_id={"PA-TC-0007": _dossier("PA-TC-0007", 7)})
        finding = next(f for f in result.findings if f.finding_id == "PF-001")
        self.assertEqual(finding.status.value, "SUPERSEDED")
        self.assertEqual(finding.superseede_reason, "de_observed")

    def test_partial_run_defers_de_observation(self):
        prior = _prior()
        prior["source_observations"] = [_obs()]
        rows, candidates = _simple_candidates()
        registration = {
            "malformed_observations": [],
            "excluded_evidence_refs": [{"doc_id": "DOC99", "reason": "not owned"}],
            "disclosures": [],
        }
        result = _run_assemble(candidates, DRAFT_ONE,
                           prior={"result": {"findings": [prior]}},
                           tx_by_id={"PA-TC-0007": rows[0]}, registration=registration)
        finding = next(f for f in result.findings if f.finding_id == "PF-001")
        self.assertEqual(finding.status.value, "OPEN")
        deferred = [e for e in finding.lifecycle_events
                    if e.reason == "transition_deferred"]
        self.assertEqual(len(deferred), 1)
        self.assertEqual(deferred[0].decided_by, "app_rule:partial_run_gate")

    def test_source_withdrawn_is_recorded_when_the_observation_vanishes(self):
        candidates = _collect_candidates([
            _dossier("PA-TC-0007", 7, findings=[
                _finding(title="Unregistered sale of reserved plot",
                         finding_id="TF-002")])])
        prior = _prior()
        prior["identity_key"] = _identity_of(candidates[0])
        prior["source_observations"] = [_obs(tf_id="TF-001", title=candidates[0]["title"])]
        result = _run_assemble(candidates, DRAFT_ONE,
                           prior={"result": {"findings": [prior]}},
                           tx_by_id={"PA-TC-0007": _dossier("PA-TC-0007", 7)})
        finding = next(f for f in result.findings if f.finding_id == "PF-001")
        withdrawn = next(e for e in finding.lifecycle_events if e.reason == "source_withdrawn")
        self.assertEqual(withdrawn.refs, ["PA-TC-0007/TF-001"])
        self.assertEqual(withdrawn.decided_by, "app_rule:source_withdrawn")

    def test_source_correction_is_recorded_when_the_observation_changes(self):
        rows, candidates = _simple_candidates()
        prior = _prior()
        prior["identity_key"] = _identity_of(candidates[0])
        prior["source_observations"] = [
            _obs(title="old title", text_excerpt=candidates[0]["text"],
                 tf_id=candidates[0]["sources"][0]["tf_id"])]
        result = _run_assemble(candidates, DRAFT_ONE,
                           prior={"result": {"findings": [prior]}},
                           tx_by_id={"PA-TC-0007": rows[0]})
        finding = next(f for f in result.findings if f.finding_id == "PF-001")
        corrected = next(e for e in finding.lifecycle_events if e.reason == "source_corrected")
        expected_ref = f"PA-TC-0007/{candidates[0]['sources'][0]['tf_id']}"
        self.assertEqual(corrected.refs, [expected_ref])
        self.assertEqual(corrected.decided_by, "app_rule:source_corrected")


class TestCorrelationsAndRecords(unittest.TestCase):
    """§9 deterministic edges and §5.1-5 contradiction keys."""

    def test_contradiction_content_keys_and_refresh_dedup(self):
        rows, candidates = _simple_candidates(count=2)
        contradiction = {"members": [0, 1], "description": "The survey extents conflict.",
                         "resolution_guidance": "Recheck."}
        drafts = {"findings": list(DRAFT_TWO["findings"]),
                  "contradictions": [dict(contradiction)]}
        result = _run_assemble(candidates, drafts)
        self.assertEqual(len(result.contradictions), 1)
        record = result.contradictions[0]
        sides = sorted((side.tx_id, side.finding_index) for side in record.sides)
        self.assertEqual(
            record.contradiction_key,
            content_hash({"description": _od3(contradiction["description"]),
                          "sides": sides}))
        self.assertEqual(set(record.related_pf_ids), {"PF-001", "PF-002"})
        # same content key twice → members refresh, never duplicate (matrix 9)
        drafts["contradictions"] = [dict(contradiction), dict(contradiction)]
        result = _run_assemble(candidates, drafts)
        self.assertEqual(len(result.contradictions), 1)

    def test_conflicts_with_edges_alias_the_record(self):
        rows, candidates = _simple_candidates(count=2)
        drafts = {"findings": list(DRAFT_TWO["findings"]),
                  "contradictions": [{"members": [0, 1], "description": "conflict"}]}
        result = _run_assemble(candidates, drafts)
        conflicts = [edge for edge in result.correlations if edge.type == "CONFLICTS_WITH"]
        self.assertEqual(sorted((e.from_pf, e.to_pf) for e in conflicts),
                         [("PF-001", "PF-002")])
        self.assertTrue(all(edge.determined_by == "deterministic" for edge in conflicts))

    def test_merge_produces_a_merged_into_edge(self):
        rows, candidates = _simple_candidates()
        key = _identity_of(candidates[0])
        winner = _prior("PF-001")
        winner["identity_key"] = key
        winner["source_observations"] = [_obs()]
        loser = _prior("PF-002")
        loser["identity_key"] = key
        loser["source_observations"] = [_obs(), _obs("TF-002", "PA-TC-0007")]
        result = _run_assemble(candidates, DRAFT_ONE,
                           prior={"result": {"findings": [winner, loser]}},
                           tx_by_id={"PA-TC-0007": rows[0]})
        edges = [edge for edge in result.correlations if edge.type == "MERGED_INTO"]
        self.assertEqual([(edge.from_pf, edge.to_pf) for edge in edges], [("PF-002", "PF-001")])

    def test_split_produces_a_split_from_edge(self):
        # two candidates with identical identity (same title, different docs);
        # each group claims the carry and the second becomes a split child.
        tx_rows = [
            _dossier("PA-TC-0007", 7, findings=[
                _finding(title="split ident text", evidence=[{"doc_id": "DOC1", "pages": ""}])]),
            _dossier("PA-TC-0008", 8, findings=[
                _finding(title="split ident text", evidence=[{"doc_id": "DOC2", "pages": ""}],
                         finding_id="TF-002")]),
        ]
        candidates = _collect_candidates(tx_rows)
        self.assertEqual(_identity_of(candidates[0]), _identity_of(candidates[1]))
        prior = _prior("PF-001")
        prior["identity_key"] = _identity_of(candidates[0])
        result = _run_assemble(candidates, {"findings": [
            {"members": [0], "title": "First", "description": "d"},
            {"members": [1], "title": "Second", "description": "e"},
        ]}, prior={"result": {"findings": [prior]}},
            tx_by_id={"PA-TC-0007": tx_rows[0], "PA-TC-0008": tx_rows[1]})
        splits = [edge for edge in result.correlations if edge.type == "SPLIT_FROM"]
        self.assertEqual([(edge.from_pf, edge.to_pf) for edge in splits],
                         [("PF-002", "PF-001")])

    def test_unverified_predecessors_label_findings_and_create_depends_on(self):
        rows, candidates = _simple_candidates()
        chain = [{
            "tx_id": "PA-TC-0007", "chain_position": 7,
            "documented_transaction": {"sequence": 7, "upstream_tx_ids": ["PA-TC-0001"]},
        }, {
            "tx_id": "PA-TC-0001", "chain_position": 1, "documented_transaction": {"sequence": 1},
        }]
        result = _run_assemble(candidates, DRAFT_ONE, chain=chain,
                           tx_by_id={"PA-TC-0007": rows[0]})
        finding = result.findings[0]
        self.assertIn("[unverified predecessor PA-TC-0001]", finding.evidence_gaps)
        depends = [edge for edge in result.correlations if edge.type == "DEPENDS_ON"]
        self.assertEqual(len(depends), 1)
        self.assertEqual(depends[0].from_pf, finding.finding_id)
        self.assertIsNone(depends[0].to_pf)
        self.assertIn("PA-TC-0001", depends[0].rationale)
        self.assertEqual(result.readiness.skipped_tx_ids, ["PA-TC-0001"])
        self.assertEqual(result.readiness.state, "PARTIAL")


class TestRelatedPairProposals(unittest.TestCase):
    """OD-4 addendum: the draft pass may propose RELATED pairs; the
    application re-validates each against its own output map — proposals
    never merge, rewire identity, or move statuses (§9, advisory only)."""

    def test_valid_pair_becomes_an_llm_related_edge(self):
        rows, candidates = _simple_candidates(count=2)
        drafts = {**DRAFT_TWO, "related_pairs": [[0, 1]]}
        result = _run_assemble(candidates, drafts)
        related = [edge for edge in result.correlations if edge.type == "RELATED"]
        self.assertEqual([(edge.from_pf, edge.to_pf) for edge in related],
                         [("PF-001", "PF-002")])
        self.assertTrue(all(edge.determined_by == "llm" for edge in related))

    def test_self_pair_and_unknown_index_drop_with_warnings(self):
        rows, candidates = _simple_candidates(count=2)
        registration = {}
        drafts = {**DRAFT_TWO, "related_pairs": [[0, 0], [0, 99]]}
        result = _run_assemble(candidates, drafts, registration=registration)
        self.assertEqual(
            [edge for edge in result.correlations if edge.type == "RELATED"], [])
        warnings = registration.get("reconciliation_warnings", [])
        self.assertTrue(any("self pair" in warning for warning in warnings))
        self.assertTrue(any("unknown candidate index" in warning
                            for warning in warnings))

    def test_pair_colliding_with_a_deterministic_edge_keeps_deterministic(self):
        # Tier C refuses the proposed merge (check 5), so both candidates stay
        # separate findings and the deterministic refusal RELATED edge covers
        # the same pair — the LLM proposal is a silent no-op on that key.
        rows, candidates = _simple_candidates(count=2)
        drafts = {
            "findings": [{"members": [0, 1], "title": "alpha group",
                          "description": "merged"}],
            "related_pairs": [[0, 1]],
        }
        result = _run_assemble(candidates, drafts)
        related = [edge for edge in result.correlations if edge.type == "RELATED"]
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0].determined_by, "deterministic")
        self.assertIn("tier-C merge refused", related[0].rationale)

    def test_pair_collapsing_into_one_output_finding_drops(self):
        # Same title+category, distinct docs: content keys differ so the
        # candidates stay separate, but the tier-B textual merge (no chain
        # anchors) collects both into one finding — the pair has no two
        # distinct ends left.
        rows = [
            _dossier("PA-TC-0007", 7, findings=[_finding(finding_id="TF-001")]),
            _dossier("PA-TC-0008", 8, findings=[_finding(
                finding_id="TF-002", evidence=[{"doc_id": "DOC2", "pages": "2"}])]),
        ]
        candidates = _collect_candidates(rows)
        registration = {}
        drafts = {
            "findings": [{"members": [0, 1], "title": "One defect",
                          "description": "merged"}],
            "related_pairs": [[0, 1]],
        }
        result = _run_assemble(candidates, drafts, registration=registration)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(
            [edge for edge in result.correlations if edge.type == "RELATED"], [])
        self.assertTrue(any(
            "collected into PF-001" in warning for warning in
            registration.get("reconciliation_warnings", [])))

    def test_absent_pairs_are_the_default(self):
        rows, candidates = _simple_candidates(count=2)
        result = _run_assemble(candidates, DRAFT_TWO)
        self.assertEqual(
            [edge for edge in result.correlations if edge.type == "RELATED"], [])


class TestSplitReplacedRetirement(unittest.TestCase):
    """§4.7-4b (matrix 45): when a prior's sources are re-observed under
    different identities (§6.3-1 guard passes) and no subgroup carries it,
    the original id cannot honestly continue — it retires
    ``SUPERSEDED/split_replaced`` while every re-observing output mints fresh
    with a ``SPLIT_FROM`` edge and an ``identity_change`` event. The victim
    is terminal like a merge victim."""

    def _prior(self):
        prior = _prior("PF-001")
        prior["consolidation"]["dedup_keys"] = [
            "authority|unregistered sale of reserved plot|doc1"]
        prior["source_observations"] = [_obs()]
        return prior

    def test_corrected_identity_retires_the_original_split_replaced(self):
        # The source observation was corrected under the same (tx, tf): the
        # content now reads a different defect, so the prior's identity is
        # unreclaimable — its content survives under a fresh PF id instead.
        tx_rows = [
            _dossier("PA-TC-0007", 7, findings=[
                _finding(title="Corrected sale import",
                         evidence=[{"doc_id": "DOC2", "pages": "2"}])]),
        ]
        candidates = _collect_candidates(tx_rows)
        prior = self._prior()
        result = _run_assemble(candidates, {
            "findings": [{"members": [0], "title": "Corrected sale",
                          "description": "corrected"}],
        }, prior={"result": {"findings": [prior]}},
            tx_by_id={"PA-TC-0007": tx_rows[0]})
        original = next(item for item in result.findings
                        if item.finding_id == "PF-001")
        self.assertEqual(original.status.value, "SUPERSEDED")
        self.assertEqual(original.superseede_reason, "split_replaced")
        reasons = [(event.reason, event.refs) for event in original.lifecycle_events]
        self.assertIn(("split_replaced", ["PF-002"]), reasons)
        splits = [edge for edge in result.correlations if edge.type == "SPLIT_FROM"]
        self.assertEqual([(edge.from_pf, edge.to_pf) for edge in splits],
                         [("PF-002", "PF-001")])
        child = next(item for item in result.findings
                     if item.finding_id == "PF-002")
        self.assertIn(("identity_change", ["PF-001"]),
                      [(event.reason, event.refs) for event in child.lifecycle_events])

    def test_two_descendants_split_from_the_retired_original(self):
        tx_rows = [
            _dossier("PA-TC-0007", 7, findings=[
                _finding(title="unregistered alpha beta gamma delta")]),
            _dossier("PA-TC-0008", 8, findings=[
                _finding(title="unregistered epsilon zeta eta theta",
                         finding_id="TF-002")]),
        ]
        candidates = _collect_candidates(tx_rows)
        prior = self._prior()
        prior["source_observations"] = [
            _obs(), _obs("TF-002", "PA-TC-0008")]
        result = _run_assemble(candidates, {
            "findings": [{"members": [0, 1], "title": "alpha group",
                          "description": "merged"}],
        }, prior={"result": {"findings": [prior]}},
            tx_by_id={"PA-TC-0007": tx_rows[0], "PA-TC-0008": tx_rows[1]})
        original = next(item for item in result.findings
                        if item.finding_id == "PF-001")
        self.assertEqual(original.superseede_reason, "split_replaced")
        self.assertIn(("split_replaced", ["PF-002", "PF-003"]),
                      [(event.reason, event.refs) for event in original.lifecycle_events])
        splits = [edge for edge in result.correlations if edge.type == "SPLIT_FROM"]
        self.assertEqual(sorted(
            (edge.from_pf, edge.to_pf) for edge in splits),
            [("PF-002", "PF-001"), ("PF-003", "PF-001")])
        for child_id in ("PF-002", "PF-003"):
            child = next(item for item in result.findings
                         if item.finding_id == child_id)
            self.assertIn(("identity_change", ["PF-001"]),
                          [(event.reason, event.refs) for event in child.lifecycle_events])

    def test_carried_prior_is_never_split_replaced(self):
        # §4.7-4a vs 4b: when the identity still carries, the original is
        # claimed verbatim and no retirement happens at all.
        tx_rows = _simple_candidates()[1]
        prior = _prior("PF-001")
        prior["identity_key"] = _identity_of(tx_rows[0])
        prior["source_observations"] = [_obs()]
        result = _run_assemble(tx_rows, DRAFT_ONE,
                           prior={"result": {"findings": [prior]}},
                           tx_by_id={"PA-TC-0007": _simple_candidates()[0][0]})
        original = next(item for item in result.findings
                        if item.finding_id == "PF-001")
        self.assertNotEqual(str(original.status), "SUPERSEDED")
        self.assertFalse(any(
            event.reason == "split_replaced"
            for item in result.findings for event in item.lifecycle_events))
        self.assertFalse(any(
            edge.type == "SPLIT_FROM" and edge.to_pf == "PF-001"
            for edge in result.correlations))

    def test_partial_run_defers_the_split_replacement(self):
        # §6.3-7/§6.2 partial-run gate: a PARTIAL run (tx8 missing from the
        # chain) defers the id-retiring reorganization — the original keeps
        # its id/status, the fresh descendant still mints (4a-class rule).
        tx_rows = [
            _dossier("PA-TC-0007", 7, findings=[
                _finding(title="Corrected sale import",
                         evidence=[{"doc_id": "DOC2", "pages": "2"}])]),
        ]
        candidates = _collect_candidates(tx_rows)
        prior = self._prior()
        chain = [
            {"tx_id": "PA-TC-0007", "chain_position": 7,
             "documented_transaction": {"sequence": 7}},
            {"tx_id": "PA-TC-0008", "chain_position": 8,
             "documented_transaction": {"sequence": 8}},
        ]
        result = _run_assemble(candidates, {
            "findings": [{"members": [0], "title": "Corrected sale",
                          "description": "corrected"}],
        }, prior={"result": {"findings": [prior]}}, chain=chain,
            tx_by_id={"PA-TC-0007": tx_rows[0]})
        self.assertEqual(result.readiness.state, "PARTIAL")
        original = next(item for item in result.findings
                        if item.finding_id == "PF-001")
        self.assertEqual(original.status.value, "OPEN")
        self.assertFalse(original.superseede_reason)
        self.assertIn("transition_deferred",
                      [event.reason for event in original.lifecycle_events])
        self.assertFalse(any(
            edge.type == "SPLIT_FROM" for edge in result.correlations))
        self.assertIn("PF-002", [item.finding_id for item in result.findings])

    def test_split_replaced_victim_is_terminal_on_a_rerun(self):
        # matrix 44/45: a retired split_replaced id is terminal — a later run
        # never carries it back; the re-observation mints a fresh id instead.
        tx_rows = [
            _dossier("PA-TC-0007", 7, findings=[
                _finding(title="unregistered alpha beta gamma delta")]),
        ]
        candidates = _collect_candidates(tx_rows)
        prior = self._prior()
        prior["status"] = "SUPERSEDED"
        prior["superseede_reason"] = "split_replaced"
        result = _run_assemble(candidates, DRAFT_ONE,
                           prior={"result": {"findings": [prior]}},
                           tx_by_id={"PA-TC-0007": tx_rows[0]})
        ids = [item.finding_id for item in result.findings]
        self.assertEqual(ids, ["PF-002", "PF-001"])  # output first, then retained verbatim
        victim = result.findings[1]
        self.assertEqual(victim.status.value, "SUPERSEDED")
        self.assertEqual(victim.superseede_reason, "split_replaced")
        fresh = result.findings[0]
        self.assertEqual(fresh.status.value, "OPEN")


class TestPartialRunIntegration(unittest.TestCase):
    """C4 (matrix 12–14, row 43): partial mode end-to-end via consolidate_findings."""

    def _patch_env(self, results=(), chain=(), requirements=(), prior=None):
        return patch.multiple(
            agent_repo,
            list_persisted_transaction_results=lambda case_id: list(results),
            get_persisted_title_chain_entries=lambda case_id: list(chain),
            get_agent_documents=lambda case_id: [{"doc_id": "DOC1"}],
            list_requirements=lambda case_id, status=None: list(requirements),
            get_property_findings=lambda case_id: prior,
            get_property_findings_raw=lambda case_id: prior,
            get_agent_result=lambda case_id: {},
        )

    def _run(self, results=(), chain=(), requirements=(), prior=None):
        saved = []
        with patch.object(agent_repo, "save_property_findings",
                          side_effect=lambda case_id, c: saved.append(c)), \
                self._patch_env(results=results, chain=chain,
                                requirements=requirements, prior=prior), \
                patch("backend.services.consolidation.complete_json",
                      return_value=DRAFT_ONE):
            outcome = consolidate_findings(CASE)
        return outcome, saved[0] if saved else None

    # -- matrix 12: chain positions with no persisted row at all --------------

    def test_skipped_tx_proceeds_in_incomplete_state(self):
        rows = [_dossier("PA-TC-0007", 7, findings=[_finding()])]
        chain = [
            {"tx_id": "PA-TC-0007", "chain_position": 7,
             "documented_transaction": {"sequence": 7}},
            {"tx_id": "PA-TC-0008", "chain_position": 8,
             "documented_transaction": {"sequence": 8}},
        ]
        outcome, container = self._run(results=rows, chain=chain)
        self.assertEqual(outcome["status"], "ok")
        result = container["result"]
        self.assertEqual(result["integrity"]["input_state"], "INCOMPLETE")
        self.assertEqual(result["readiness"]["state"], "PARTIAL")
        # the missing tx surfaces via its chain position's tx id
        self.assertEqual(result["readiness"]["skipped_tx_ids"], ["PA-TC-0008"])
        # content consolidated from present rows only
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["affected_tx_ids"], ["PA-TC-0007"])

    # -- matrix 13: pending tx present (checkpointed) --------------------------

    def test_pending_tx_hides_content_and_prior_surfaces_transport_note(self):
        rows = [
            _dossier("PA-TC-0007", 7, findings=[_finding()]),
            _dossier("PA-TC-0004", 4, status="PENDING_NOT_VERIFIED",
                     findings=[_finding("A pending checkpoint finding")]),
        ]
        candidates = _collect_candidates([rows[0]])
        prior_obs_by_pending = _prior("PF-002")
        # a real tier-shaped key that this run does not re-derive (different id)
        base = _identity_of(candidates[0])
        prior_obs_by_pending["identity_key"] = base.rsplit("|", 1)[0] + "|absent initial"
        prior_obs_by_pending["source_observations"] = [
            _obs("TF-020", "PA-TC-0004")]
        carried = _prior("PF-001")
        carried["identity_key"] = _identity_of(candidates[0])
        prior_container = {
            "container_version": "2.0", "input_hash": "OLD-HASH",
            "result": {"findings": [prior_obs_by_pending, carried]},
        }
        requirements = [_req("REQ-0004", owner="PA-TC-0004")]
        outcome, container = self._run(
            results=rows, requirements=requirements, prior=prior_container)
        result = container["result"]
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(result["integrity"]["input_state"], "PENDING")
        self.assertEqual(result["readiness"]["pending_tx_ids"], ["PA-TC-0004"])
        self.assertEqual(result["readiness"]["open_requirement_ids"], ["REQ-0004"])
        # only the terminal dossier's finding is consolidated; the prior
        # observed by the pending tx is retention-only (no content absorbed)
        outputs = {f["finding_id"]: f for f in result["findings"]}
        self.assertEqual(outputs["PF-001"]["affected_tx_ids"], ["PA-TC-0007"])
        # §6.2: the de-observation guard sits behind the gate — the prior
        # observed by the pending tx is deferred, not superseded (§6.3-2).
        self.assertEqual(outputs["PF-002"]["status"], "OPEN")
        self.assertTrue(any(
            e["reason"] == "transition_deferred"
            for e in outputs["PF-002"]["lifecycle_events"]))

    def test_pending_run_defers_resolution_under_the_gate(self):
        # row-43 at integration level: a carried OPEN finding would resolve
        # (asks SATISFIED with validated matched doc) but the run is PENDING.
        rows = [
            _dossier("PA-TC-0007", 7, findings=[_finding()]),
            _dossier("PA-TC-0004", 4, status="PENDING_NOT_VERIFIED", findings=[]),
        ]
        candidates = _collect_candidates([rows[0]])
        carried = _prior("PF-001")
        carried["identity_key"] = _identity_of(candidates[0])
        prior_container = {
            "container_version": "2.0", "input_hash": "OLD-HASH",
            "result": {"findings": [carried]},
        }
        requirements = [_req("REQ-0007", owner="PA-TC-0007",
                             status="SATISFIED", matched="DOC1")]
        outcome, container = self._run(
            results=rows, requirements=requirements, prior=prior_container)
        result = container["result"]
        self.assertEqual(outcome["status"], "ok")
        finding = result["findings"][0]
        # the gate defers the ladder's RESOLVED target: status unchanged
        self.assertEqual(finding["status"], "OPEN")
        deferred = [e for e in finding["lifecycle_events"]
                    if e["reason"] == "transition_deferred"]
        self.assertEqual(len(deferred), 1)
        self.assertEqual(deferred[0]["decided_by"], "app_rule:partial_run_gate")
        self.assertEqual(deferred[0]["from_status"], "OPEN")
        self.assertEqual(deferred[0]["to_status"], "OPEN")
        self.assertNotIn("resolved", [e["reason"] for e in finding["lifecycle_events"]])

    # -- matrix 14: INCONCLUSIVE + changed document manifest --------------------

    def test_inconclusive_with_changed_manifest_is_unverified_only(self):
        rows = [
            _dossier("PA-TC-0007", 7, findings=[_finding()]),
            _dossier("PA-TC-0001", 1, status="INCONCLUSIVE",
                     findings=[_finding("Stale-document finding",
                                        finding_id="TF-011")],
                     transaction_metadata={
                         "_document_manifest": {"DOC99": "processed"},
                     }),
        ]
        chain = [
            {"tx_id": "PA-TC-0007", "chain_position": 7,
             "documented_transaction": {"sequence": 7}},
            {"tx_id": "PA-TC-0001", "chain_position": 1,
             "documented_transaction": {"sequence": 1}},
        ]
        outcome, container = self._run(results=rows, chain=chain)
        self.assertEqual(outcome["status"], "ok")
        result = container["result"]
        self.assertEqual(result["integrity"]["input_state"], "PENDING")
        self.assertEqual(result["readiness"]["state"], "PARTIAL")
        # not a checkpoint-pending tx: unverified only, not pending
        self.assertEqual(result["readiness"]["pending_tx_ids"], [])
        self.assertEqual(result["readiness"]["unverified_tx_ids"], ["PA-TC-0001"])
        # the stale-manifest tx contributes no finding content
        self.assertEqual([f["affected_tx_ids"] for f in result["findings"]],
                         [["PA-TC-0007"]])
        coverage = {d["tx_id"]: d["terminal"] for d in result["coverage"]["dossiers"]}
        self.assertEqual(coverage, {"PA-TC-0007": True, "PA-TC-0001": False})


class TestBlocksAndEndpoint(unittest.TestCase):
    """§8.1 blocks on ok runs and the D8 additive endpoint keys."""

    def _patch_env(self, results=(), chain=(), requirements=()):
        return patch.multiple(
            agent_repo,
            list_persisted_transaction_results=lambda case_id: list(results),
            get_persisted_title_chain_entries=lambda case_id: list(chain),
            get_agent_documents=lambda case_id: [{"doc_id": "DOC1"}],
            list_requirements=lambda case_id, status=None: list(requirements),
            get_property_findings=lambda case_id: None,
            get_property_findings_raw=lambda case_id: None,
            get_agent_result=lambda case_id: {},
        )

    def _run(self, *, results=(), chain=(), requirements=()):
        saved = []
        with patch.object(agent_repo, "save_property_findings",
                          side_effect=lambda case_id, c: saved.append(c)), \
                self._patch_env(results=results, chain=chain, requirements=requirements), \
                patch("backend.services.consolidation.complete_json",
                      return_value=DRAFT_ONE):
            outcome = consolidate_findings(CASE)
        return outcome, saved

    def test_empty_case_blocks(self):
        outcome, saved = self._run(results=[], chain=[])
        self.assertEqual(outcome["status"], "ok")
        result = saved[0]["result"]
        self.assertEqual(result["readiness"]["state"], "COMPLETE")
        self.assertEqual(result["integrity"]["input_state"], "EMPTY")
        self.assertEqual(result["coverage"]["dossiers"], [])
        self.assertEqual(result["correlations"], [])

    def test_verified_tx_without_findings_is_complete_with_terminal_coverage(self):
        outcome, saved = self._run(results=[_dossier("PA-TC-0007", 7, findings=[])])
        result = saved[0]["result"]
        self.assertEqual(result["readiness"]["state"], "COMPLETE")
        dossier = result["coverage"]["dossiers"][0]
        self.assertEqual(dossier["tx_id"], "PA-TC-0007")
        self.assertTrue(dossier["terminal"])
        self.assertEqual(result["integrity"]["input_state"], "READY")

    def test_open_requirement_makes_readiness_partial(self):
        outcome, saved = self._run(
            results=[_dossier("PA-TC-0007", 7, findings=[])],
            requirements=[_req()])
        result = saved[0]["result"]
        self.assertEqual(result["readiness"]["state"], "PARTIAL")
        self.assertEqual(result["readiness"]["open_requirement_ids"], ["REQ-0001"])
        self.assertEqual(result["coverage"]["requirements"]["open"], 1)

    def test_endpoint_additive_keys_and_v1_shape(self):
        payload_container = {
            "container_version": "2.0", "input_hash": "h",
            "result": {"findings": [], "correlations": [
                {"type": "MERGED_INTO", "from_pf": "PF-002", "to_pf": "PF-001",
                 "rationale": "merged", "determined_by": "deterministic"}],
                "coverage": {"dossiers": []},
                "integrity": {"disclosures": []},
                "readiness": {"state": "COMPLETE"},
                "contradictions": [], "unresolved_dependencies": [],
                "provenance": {},
            }}
        # The handler imports agent_repo lazily inside the function body.
        with patch("backend.database.repositories.agent_repo.get_property_findings",
                   Mock(return_value=payload_container)), \
                patch("backend.routers.results.case_exists", Mock(return_value=True)):
            payload = asyncio.run(router_module.get_case_findings(
                CASE, user={"id": "owner"}))
        self.assertEqual([e["type"] for e in payload["correlations"]], ["MERGED_INTO"])
        self.assertEqual(payload["readiness"]["state"], "COMPLETE")
        self.assertEqual(payload["coverage"], {"dossiers": []})
        self.assertEqual(payload["integrity"], {"disclosures": []})

        # a v1 container leaves the new keys None (additive, nothing invented)
        v1 = {"container_version": "1.0", "input_hash": "h", "result": {}}
        with patch("backend.database.repositories.agent_repo.get_property_findings",
                   Mock(return_value=v1)), \
                patch("backend.routers.results.case_exists", Mock(return_value=True)):
            payload = asyncio.run(router_module.get_case_findings(
                CASE, user={"id": "owner"}))
        self.assertIsNone(payload["readiness"])
        self.assertIsNone(payload["coverage"])
        self.assertIsNone(payload["integrity"])
        self.assertIsNone(payload["correlations"])
        self.assertEqual(payload["findings"], [])


if __name__ == "__main__":
    unittest.main()
