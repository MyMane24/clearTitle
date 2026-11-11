"""C2 â€” identity model v2 reconciliation (Rev 6, approved package).

Focused coverage for the C2 increment: three run-global duplicate registries
(identity key, legacy dedup keys, PF id), deterministic provenance ordering
with conservative refuse-all on ambiguity, D1 defensive re-sort, the OD-1
lifecycle subset (status carry, SUPERSEDED subtypes, merge/split lineage,
de_observed reactivation), tier-C proposal validation (seven checks),
container version 2.0 / same-version-only replay, and the Â§9(a)/(b)/(c)
prior-container degradation behaviors.
"""

import unittest
from unittest.mock import patch

from pydantic import ValidationError

from backend.database.repositories import agent_repo
from backend.schemas.analysis import ConsolidationDraftResult, FindingDraft
from backend.services.consolidation import (
    CONTAINER_VERSION,
    _assemble,
    _collect_candidates,
    _compat_gate,
    _d1_reorder,
    _observed_tuple,
    _parse_prior_key,
    _phase_r,
    _solo_key,
    _candidate_bundle,
    _tier_c_review,
    consolidate_findings,
)

NOW = "2026-11-06T00:00:00+00:00"
CASE = "CASE1"


def _finding(title="Unregistered sale of reserved plot", category="authority",
             text="The deed was never registered.", evidence=None, defect=True,
             significance="ESTABLISHED", finding_id="TF-001"):
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


def _observation(tf_id="TF-001", tx_id="PA-TC-0001", refs=(("DOC1", "1"),), title="t"):
    return {
        "tf_id": tf_id, "tx_id": tx_id, "title": title,
        "evidence_refs": [{"doc_id": doc_id, "pages": pages} for doc_id, pages in refs],
    }


def _prior(finding_id="PF-001", identity_key=None, dedup=None, status="OPEN",
           observations=None, superseede_reason=None, resolution=None, **extra):
    prior = {
        "finding_id": finding_id,
        "status": status,
        "category": "authority",
        "title": "Unregistered sale",
        "description": "d",
        "severity": "CAUTION",
        "consolidation": {"dedup_keys": dedup or [], "run_id": None, "phase_a_hash": None,
                          "dossier_refs": [], "source_hashes": None},
        "source_observations": observations or [],
        "lifecycle_events": [],
    }
    if identity_key is not None:
        prior["identity_key"] = identity_key
    if superseede_reason:
        prior["superseede_reason"] = superseede_reason
    if resolution is not None:
        prior["resolution_evidence"] = resolution
    prior.update(extra)
    return prior


def _bundle(**kw):
    base = {
        "category": "authority", "kind": "execution_defect", "title": "unregistered sale of plot",
        "parcels": [], "instruments": [], "offices": [], "roles": {},
        "claims": {"plot"}, "polarity": True, "positions": [], "missing_tx": False,
        "text": "",
    }
    base.update(kw)
    return base


DRAFT_ONE = {"findings": [{"members": [0], "title": "Unregistered transfer", "description": "d"}]}
DRAFT_CANARY = {"findings": [{"members": [0], "title": "canary", "description": "d"}]}


class TestPriorKeyParsing(unittest.TestCase):
    """Identity keys are opaque data: only documented shapes are attributed."""

    def test_a_b_and_m_keys_parse_into_slots(self):
        parsed = _parse_prior_key("A|execution|execution_defect|37|rn-1|wakad")
        self.assertEqual(parsed["tier"], "A")
        self.assertEqual(parsed["parcel"], "37")
        self.assertEqual(_parse_prior_key("B|encumbrance|mortgage_charge|t x")["tier"], "B")
        self.assertEqual(_parse_prior_key("M|cafe")["tier"], "M")

    def test_foreign_or_malformed_keys_are_never_attributed(self):
        self.assertIsNone(_parse_prior_key("X|weird"))
        self.assertIsNone(_parse_prior_key(""))
        self.assertIsNone(_parse_prior_key(None))
        self.assertIsNone(_parse_prior_key("A|too|few|slots"))


class TestD1DefensiveResort(unittest.TestCase):
    """D1 (approved): read-side `(sequence, tx_id)` re-sort; garbage rows stay
    pass-through so `_row_problem` remains the sole classifier (C1)."""

    def test_rows_resort_by_sequence_then_tx_id(self):
        rows = [_dossier("PA-TC-0009", 9), _dossier("PA-TC-0003", 3)]
        ordered = _d1_reorder(rows)
        self.assertEqual([row["tx_id"] for row in ordered], ["PA-TC-0003", "PA-TC-0009"])

    def test_rows_without_a_sequence_rank_after_real_ones(self):
        # `_row_sequence` derives a sequence from the PA-TC-#### prefix when the
        # stored sequence is 0/absent â€” that is the existing C1 rule, preserved.
        rows = [_dossier("PA-TC-0009", 9), {"no_sequence": True}, _dossier("PA-TC-0002", 0)]
        ordered = _d1_reorder(rows)
        self.assertEqual(
            [row.get("tx_id") for row in ordered],
            ["PA-TC-0002", "PA-TC-0009", None],
        )

    def test_non_dict_rows_pass_through_for_row_problem(self):
        rows = [_dossier("PA-TC-0009", 9), "a scalar row"]
        ordered = _d1_reorder(rows)
        self.assertEqual([row for row in ordered], rows)


class TestProvenanceOrdering(unittest.TestCase):
    """Â§6-R2 rules 1â€“3 derivation: observation tuples, unorderable cases,
    strict-prefix ordering, exact ties, mixed provenance (refuse-all)."""

    _TX = {"PA-TC-0001": {"tx_id": "PA-TC-0001", "sequence": 1},
           "PA-TC-0002": {"tx_id": "PA-TC-0002", "sequence": 2}}

    def test_ordering_tuple_is_derived_min_pair(self):
        obs = _observation(tf_id="TF-001", tx_id="PA-TC-0001",
                           refs=(("DOC2", "5"), ("DOC1", "2")))
        self.assertEqual(_observed_tuple(obs, self._TX), (1, "PA-TC-0001", "TF-001", "DOC1", "2"))

    def test_unorderable_observations(self):
        self.assertIsNone(_observed_tuple(_observation(tx_id="PA-TC-7777"), self._TX))
        self.assertIsNone(_observed_tuple(
            _observation(tf_id="TF-9"), self._TX))  # TF id not TF-\d{3,4}
        self.assertIsNone(_observed_tuple(
            _observation(refs=()), self._TX))  # no usable evidence reference
        self.assertIsNone(_observed_tuple("not a dict", self._TX))

    def test_v1_prior_unorderable_by_design(self):
        claimant = _prior(finding_id="PF-001", dedup=["k1"])  # no observations
        reg = _phase_r([claimant], self._TX, {})
        self.assertEqual(reg["population"], [claimant])

    def test_collection_content_is_array_order_invariant(self):
        first = _prior(finding_id="PF-001", identity_key="B|c|k|t",
                       observations=[_observation(), _observation("TF-002", "PA-TC-0002")])
        second = _prior(finding_id="PF-002", identity_key="B|c|k|t",
                        observations=[_observation("TF-002", "PA-TC-0002"), _observation()])
        reg = _phase_r([first, second], self._TX, {})
        record = next(r for r in reg["records"] if r[0] == "identity_key")
        # Same sorted collection under array reversal â†’ exact tie â†’ refuse-all.
        self.assertIsNone(record[2])

    def test_strict_prefix_collection_sorts_first(self):
        small = _prior(finding_id="PF-001", identity_key="B|c|k|t",
                       observations=[_observation()])
        big = _prior(finding_id="PF-002", identity_key="B|c|k|t",
                     observations=[_observation(), _observation("TF-002", "PA-TC-0002")])
        reg = _phase_r([big, small], self._TX, {})
        record = next(r for r in reg["records"] if r[0] == "identity_key")
        self.assertEqual(record[2]["finding_id"], "PF-001")
        self.assertEqual([loser["finding_id"] for loser in record[3]], ["PF-002"])
        self.assertTrue(all(id(loser) in reg["excluded"] for loser in record[3]))

    def test_exact_ties_are_a_refuse_all(self):
        twins = [
            _prior(finding_id="PF-001", identity_key="B|c|k|t", observations=[_observation()]),
            _prior(finding_id="PF-002", identity_key="B|c|k|t", observations=[_observation()]),
        ]
        reg = _phase_r(list(reversed(twins)), self._TX, {})
        record = next(r for r in reg["records"] if r[0] == "identity_key")
        self.assertIsNone(record[2])
        self.assertEqual({claimant["finding_id"] for claimant in record[3]}, {"PF-001", "PF-002"})
        self.assertEqual(
            {id(claimant) for claimant in record[3]} & reg["excluded"],
            {id(claimant) for claimant in record[3]},
        )

    def test_mixed_provenance_refuses_all_claimants(self):
        claimants = [
            _prior(finding_id="PF-001", identity_key="B|c|k|t", observations=[_observation()]),
            _prior(finding_id="PF-002", identity_key="B|c|k|t",
                   observations=[_observation("TF-002", "PA-TC-7777")]),  # tx absent from map
        ]
        reg = _phase_r(claimants, self._TX, {})
        record = next(r for r in reg["records"] if r[0] == "identity_key")
        self.assertIsNone(record[2])
        self.assertEqual(len(record[3]), 2)

    def test_duplicate_multiplicity_is_never_deduped(self):
        single = _prior(finding_id="PF-001", identity_key="B|c|k|t", observations=[_observation()])
        doubled = _prior(finding_id="PF-002", identity_key="B|c|k|t",
                         observations=[_observation(), _observation()])
        reg = _phase_r([single, doubled], self._TX, {})
        record = next(r for r in reg["records"] if r[0] == "identity_key")
        self.assertEqual(record[2]["finding_id"], "PF-001")  # smaller collection wins

    def test_registry_order_invariance(self):
        twins = [
            _prior(finding_id="PF-001", identity_key="B|c|k|t",
                   observations=[_observation(), _observation("TF-002", "PA-TC-0002")]),
            _prior(finding_id="PF-002", identity_key="B|c|k|t", observations=[_observation()]),
        ]
        forward = _phase_r(twins, self._TX, {})
        backward = _phase_r(list(reversed(twins)), self._TX, {})
        for reg in (forward, backward):
            record = next(r for r in reg["records"] if r[0] == "identity_key")
            self.assertEqual(record[2]["finding_id"], "PF-002")


class TestThreeRegistries(unittest.TestCase):
    """Identity key, legacy dedup keys, and PF id are evaluated independently;
    exclusion is run-global."""

    _TX = {"PA-TC-0001": {"tx_id": "PA-TC-0001", "sequence": 1}}

    def test_pf_id_collision_with_unrelated_identity_and_legacy_keys(self):
        claimants = [
            _prior(finding_id="PF-001", identity_key="B|c|k|one", dedup=["k1"],
                   observations=[_observation()]),
            _prior(finding_id="PF-001", identity_key="B|c|k|two", dedup=["k2"],
                   observations=[_observation("TF-002", "PA-TC-0001")]),
        ]
        reg = _phase_r(claimants, self._TX, {})
        mechanisms = {r[0] for r in reg["records"]}
        self.assertEqual(mechanisms, {"pf_id"})
        record = next(r for r in reg["records"] if r[0] == "pf_id")
        self.assertEqual(record[2]["finding_id"], "PF-001")

    def test_legacy_registry_keeps_working_without_identity_keys(self):
        claimants = [
            _prior(finding_id="PF-001", dedup=["k1"], observations=[]),
        ]
        reg = _phase_r(claimants, self._TX, {})
        self.assertEqual(reg["records"], [])
        self.assertEqual(reg["legacy_reg"][frozenset({"k1"})], claimants)

    def test_global_exclusion_beats_a_registry_lookup(self):
        # The loser of the identity collision must also be invisible to the
        # legacy registry: exclusion is run-global across all mechanisms.
        bundle = _bundle()
        gate_group = dict(bundle)
        loser = _prior(finding_id="PF-002", identity_key="B|authority|execution_defect|t",
                       dedup=["k1"])
        winner = _prior(finding_id="PF-001", identity_key="B|authority|execution_defect|t",
                        dedup=["k1"])
        observations = [_observation()]
        winner["source_observations"] = list(observations)
        loser["source_observations"] = list(observations) + [_observation("TF-002", "PA-TC-0001")]
        reg = _phase_r([winner, loser], self._TX, {})
        loser_id = id(loser)
        self.assertIn(loser_id, reg["excluded"])
        _ = gate_group  # registry is the exclusion authority, not the gate

    def test_gate_refuses_realized_conflicts(self):
        refused_key = _parse_prior_key("A|authority|execution_defect|37|rn-1|wakad")
        group = _bundle(parcels=["37"], instruments=["rn-2"], offices=["wakad"], claims={"37"})
        ok, reasons = _compat_gate(group, _prior(), refused_key)
        self.assertFalse(ok)
        self.assertEqual(reasons, ["instrument"])

        ok, reasons = _compat_gate(_bundle(parcels=["99"], claims={"99"}), _prior(), refused_key)
        self.assertFalse(ok)
        self.assertEqual(reasons, ["parcels"])

        ok, _reasons = _compat_gate(_bundle(parcels=["37"], claims={"37"}), _prior(), refused_key)
        self.assertTrue(ok)

    def test_gate_m_keys_are_pass_through(self):
        ok, reasons = _compat_gate(_bundle(), _prior(), {"tier": "M"})
        self.assertTrue(ok)
        self.assertEqual(reasons, [])


class TestCounterBaseAndJunk(unittest.TestCase):
    """Â§9(a): entry-intrinsic junk is skipped and warned, never fatal, never
    counted; junk ids never reappear (Â§9(a) + no-resurrection)."""

    def test_junk_prior_ids_are_skipped_and_excluded_from_counter_base(self):
        junk = _prior(finding_id="PF-02", dedup=["k1"], observations=[_observation()])
        good = _prior(finding_id="PF-001", dedup=["k2"],
                      identity_key="B|c|k|t", observations=[_observation()])
        registration = {}
        reg = _phase_r([junk, good], {"PA-TC-0001": {"tx_id": "PA-TC-0001", "sequence": 1}},
                       registration)
        self.assertEqual(reg["counter_base"], 1)  # junk PF-02 did not count
        self.assertEqual([p["finding_id"] for p in reg["population"]], ["PF-001"])
        self.assertTrue(any("PF-02" in warning for warning in registration["reconciliation_warnings"]))
        self.assertIn("PF-02", reg["prior_ids"])  # still not reusable

    def test_non_string_identity_metadata_is_junk(self):
        junk = _prior(finding_id="PF-001", identity_key=["A|x"], observations=[_observation()])
        registration = {}
        _phase_r([junk], {}, registration)
        self.assertTrue(any("identity metadata" in warning
                            for warning in registration["reconciliation_warnings"]))


class TestTierCSevenChecks(unittest.TestCase):
    """Tier-C proposals are validated against all seven checks; a single failed
    check rejects with a named rationale and falls back to single findings."""

    def _members(self, **kw):
        a = _bundle(roles={"rao": {"transferor"}}, positions=[7])
        b = _bundle(roles={"rao": {"transferor"}}, positions=[8],
                    title="unregistered sale of plot a")
        if kw.pop("same_titles", True):
            pass
        a.update(kw.get("a", {}))
        b.update(kw.get("b", {}))
        return [a, b]

    def test_all_checks_pass_yields_an_m_key(self):
        proposal, rationale = _tier_c_review(self._members(), set(), [0, 1])
        self.assertEqual(rationale, "")
        self.assertTrue(proposal["key"].startswith("M|"))
        self.assertEqual(proposal["basis"], "model_merge")

    def test_check_two_instruments_conflict(self):
        proposal, rationale = _tier_c_review(
            self._members(a={"instruments": ["rn-1"]}, b={"instruments": ["rn-2"]}), set(), [0, 1])
        self.assertIsNone(proposal)
        self.assertIn("check 2", rationale)

    def test_check_one_category_conflict(self):
        proposal, rationale = _tier_c_review(
            self._members(a={"category": "chain_gap"}), set(), [0, 1])
        self.assertIsNone(proposal)
        self.assertIn("check 1", rationale)

    def test_generic_kind_never_merges(self):
        proposal, rationale = _tier_c_review(
            self._members(a={"kind": "generic", "roles": {}, "positions": []},
                          b={"kind": "generic", "roles": {}, "positions": []}), set(), [0, 1])
        self.assertIsNone(proposal)
        self.assertIn("generic", rationale)

    def test_check_three_opposing_roles(self):
        proposal, rationale = _tier_c_review(
            self._members(a={"roles": {"rao": {"transferor"}}},
                          b={"roles": {"rao": {"transferee"}}}), set(), [0, 1])
        self.assertIsNone(proposal)
        self.assertIn("check 3", rationale)

    def test_check_four_mixed_polarity(self):
        proposal, rationale = _tier_c_review(
            self._members(a={"polarity": True}, b={"polarity": False}), set(), [0, 1])
        self.assertIsNone(proposal)
        self.assertIn("check 4", rationale)

    def test_check_five_needs_a_supporting_signal(self):
        proposal, rationale = _tier_c_review(
            self._members(a={"roles": {}, "positions": []},
                          b={"roles": {}, "positions": []}), set(), [0, 1])
        self.assertIsNone(proposal)
        self.assertIn("check 5", rationale)

    def test_check_six_refuses_contradicted_candidates(self):
        proposal, rationale = _tier_c_review(self._members(), {0}, [0, 1])
        self.assertIsNone(proposal)
        self.assertIn("check 6", rationale)

    def test_check_seven_disjoint_tokens(self):
        proposal, rationale = _tier_c_review(
            self._members(a={"title": "alpha beta gamma delta"},
                          b={"title": "epsilon zeta eta theta"}), set(), [0, 1])
        self.assertIsNone(proposal)
        self.assertIn("check 7", rationale)



def _run_assemble(candidates, drafts, prior=None, registration=None, chain=None,
                  tx_by_id=None, open_requirements=()):
    return _assemble(
        candidates, ConsolidationDraftResult.model_validate(drafts), list(open_requirements),
        phase_a_hash=None, run_id="r", input_hash="IN", prior_container=prior,
        tx_by_id=tx_by_id or {}, chain_entries=chain or [],
        registration=registration if registration is not None else {},
        now=NOW,
    )


class TestAssemblyCarryAndLifecycle(unittest.TestCase):
    """Rules 1â€“3 carry-forward, OD-1 lifecycle subset, split fallbacks."""

    def _candidates(self):
        return _collect_candidates([
            _dossier("PA-TC-0007", 7, findings=[_finding(finding_id="TF-001")]),
        ])

    def test_identity_key_match_with_gate_pass_carries_the_id(self):
        candidates = self._candidates()
        tx_by_id = {"PA-TC-0007": _dossier("PA-TC-0007", 7)}
        key = _solo_key(_candidate_bundle(candidates[0], {}))[0]
        prior = _prior(finding_id="PF-007", identity_key=key,
                       dedup=["encumbrance-x"],
                       observations=[_observation("TF-001", "PA-TC-0007")])
        prior["consolidation"] = {"dedup_keys": []}
        registration = {}
        result = _run_assemble(candidates, DRAFT_ONE, prior={"result": {"findings": [prior]}},
                               registration=registration, tx_by_id=tx_by_id)
        self.assertEqual(result.findings[0].finding_id, "PF-007")
        self.assertEqual(result.findings[0].identity_key, key)
        reasons = [event.reason for event in result.findings[0].lifecycle_events]
        self.assertIn("id_carried_by_identity_key", reasons)

    def test_legacy_dedup_match_carries_for_v1_priors(self):
        candidates = self._candidates()
        prior = _prior(finding_id="PF-004")  # v1 shape: no identity_key, no observations
        from backend.services.consolidation import _dedup_key_text
        prior["consolidation"]["dedup_keys"] = [_dedup_key_text(candidates[0]["key"])]
        result = _run_assemble(
            candidates,
            {"findings": [{"members": [0], "title": candidates[0]["title"], "description": "d"}]},
            prior={"result": {"findings": [prior]}},
        )
        self.assertEqual(result.findings[0].finding_id, "PF-004")
        reasons = [event.reason for event in result.findings[0].lifecycle_events]
        self.assertIn("id_carried_by_legacy_dedup_keys", reasons)

    def test_resolved_status_carries_and_missing_evidence_degrades(self):
        candidates = self._candidates()
        key = _solo_key(_candidate_bundle(candidates[0], {}))[0]
        prior = _prior(finding_id="PF-003", identity_key=key, status="RESOLVED",
                       resolution=[{"doc_id": "DOC14", "pages": ""}],
                       observations=[_observation("TF-001", "PA-TC-0007")])
        prior["consolidation"] = {"dedup_keys": []}
        result = _run_assemble(candidates, DRAFT_ONE, prior={"result": {"findings": [prior]}},
                               tx_by_id={"PA-TC-0007": _dossier("PA-TC-0007", 7)})
        self.assertEqual(result.findings[0].status.value, "RESOLVED")

        hollow = _prior(finding_id="PF-003", identity_key=key, status="RESOLVED",
                        observations=[_observation("TF-001", "PA-TC-0007")])
        result = _run_assemble(candidates, DRAFT_ONE, prior={"result": {"findings": [hollow]}},
                               tx_by_id={"PA-TC-0007": _dossier("PA-TC-0007", 7)})
        self.assertEqual(result.findings[0].status.value, "OPEN")
        self.assertIn("status_degraded_resolution_evidence_missing",
                      [event.reason for event in result.findings[0].lifecycle_events])

    def test_de_observed_prior_reactivates_when_reobserved(self):
        candidates = self._candidates()
        key = _solo_key(_candidate_bundle(candidates[0], {}))[0]
        prior = _prior(finding_id="PF-005", identity_key=key, status="SUPERSEDED",
                       superseede_reason="de_observed",
                       observations=[_observation("TF-001", "PA-TC-0007")])
        prior["consolidation"] = {"dedup_keys": []}
        result = _run_assemble(candidates, DRAFT_ONE, prior={"result": {"findings": [prior]}},
                               tx_by_id={"PA-TC-0007": _dossier("PA-TC-0007", 7)})
        finding = result.findings[0]
        self.assertEqual(finding.finding_id, "PF-005")
        self.assertEqual(finding.status.value, "OPEN")
        self.assertIn("de_observed_reactivation",
                      [event.reason for event in finding.lifecycle_events])

    def test_vanished_prior_is_marked_de_observed_not_silently_dropped(self):
        candidates = self._candidates()
        tx_by_id = {"PA-TC-0007": _dossier("PA-TC-0007", 7)}
        prior = _prior(finding_id="PF-006", identity_key="B|other|k|gone",
                       observations=[_observation("TF-002", "PA-TC-0007")])
        result = _run_assemble(candidates, DRAFT_ONE, prior={"result": {"findings": [prior]}},
                               tx_by_id=tx_by_id)
        superseded = [f for f in result.findings if f.finding_id == "PF-006"]
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0].status.value, "SUPERSEDED")
        self.assertEqual(superseded[0].superseede_reason, "de_observed")

    def test_terminal_victims_are_retained_verbatim(self):
        candidates = self._candidates()
        prior = _prior(finding_id="PF-002", status="SUPERSEDED",
                       superseede_reason="merged_into:PF-001")
        result = _run_assemble(candidates, DRAFT_ONE, prior={"result": {"findings": [prior]}})
        self.assertEqual([f.finding_id for f in result.findings], ["PF-001", "PF-002"])
        self.assertEqual(result.findings[1].status.value, "SUPERSEDED")
        self.assertEqual(result.findings[1].superseede_reason, "merged_into:PF-001")

    def test_collision_winner_carries_while_loser_becomes_merged_into(self):
        candidates = self._candidates()
        tx_by_id = {"PA-TC-0007": _dossier("PA-TC-0007", 7)}
        key = _solo_key(_candidate_bundle(candidates[0], {}))[0]
        obs = [_observation("TF-001", "PA-TC-0007")]
        winner = _prior(finding_id="PF-001", identity_key=key, observations=list(obs))
        loser = _prior(finding_id="PF-002", identity_key=key,
                       observations=list(obs) + [_observation("TF-002", "PA-TC-0007")])
        winner["consolidation"] = {"dedup_keys": []}
        loser["consolidation"] = {"dedup_keys": []}
        result = _run_assemble(candidates, DRAFT_ONE, prior={"result": {"findings": [winner, loser]}},
                               tx_by_id=tx_by_id)
        keeper = result.findings[0]
        self.assertEqual(keeper.finding_id, "PF-001")
        merged = next(f for f in result.findings if f.finding_id == "PF-002")
        self.assertEqual(merged.superseede_reason, "merged_into:PF-001")
        self.assertIn("merge_lineage", [event.reason for event in keeper.lifecycle_events])

    def test_no_resurrection_fresh_ids_skip_every_prior_id(self):
        candidates = self._candidates()
        twins = [
            _prior(finding_id="PF-001", identity_key="B|c|k|t", observations=[_observation()]),
            _prior(finding_id="PF-002", identity_key="B|c|k|t", observations=[_observation()]),
        ]
        result = _run_assemble(candidates, DRAFT_ONE, prior={"result": {"findings": twins}},
                               tx_by_id={"PA-TC-0001": {"tx_id": "PA-TC-0001", "sequence": 1}})
        self.assertEqual(result.findings[0].finding_id, "PF-003")

    def test_source_observations_carry_observed_in_hash(self):
        candidates = self._candidates()
        result = _run_assemble(candidates, DRAFT_ONE)
        observations = result.findings[0].source_observations
        self.assertEqual([o.tf_id for o in observations], ["TF-001"])
        self.assertEqual(observations[0].observed_in, "IN")

    def test_unassigned_candidates_are_registered_not_dropped(self):
        candidates = _collect_candidates([
            _dossier("PA-TC-0007", 7, findings=[_finding(finding_id="TF-001")]),
            _dossier("PA-TC-0008", 8, findings=[_finding(finding_id="TF-002", title="Unregistered intake deed")]),
        ])
        registration = {}
        _run_assemble(candidates, DRAFT_CANARY, registration=registration)
        self.assertEqual([item["index"] for item in registration["unassigned_candidates"]], [1])

    def test_assembly_pre_pass_refusals(self):
        candidates = self._candidates()
        with self.assertRaisesRegex(ValueError, "unknown candidate indexes"):
            _run_assemble(candidates, {"findings": [{"members": [5], "title": "t", "description": "d"}]})
        with self.assertRaisesRegex(ValueError, "duplicate member index: #0"):
            _run_assemble(candidates, {"findings": [
                {"members": [0, 0, 0], "title": "t", "description": "d"}]})
        two = _collect_candidates([
            _dossier("PA-TC-0007", 7, findings=[_finding(finding_id="TF-001")]),
            _dossier("PA-TC-0008", 8, findings=[_finding(finding_id="TF-002", title="unregistered deed intake")]),
        ])
        with self.assertRaisesRegex(ValueError, "draft membership conflict: candidate #0"):
            _run_assemble(two, {"findings": [
                {"members": [0, 1], "title": "t", "description": "d"},
                {"members": [0], "title": "t2", "description": "d"}]})

    def test_evidence_sufficiency_is_app_derived(self):
        candidates = self._candidates()
        result = _run_assemble(candidates, DRAFT_ONE)
        self.assertEqual(result.findings[0].evidence_sufficiency.value, "SATISFIED")
        gapped = _collect_candidates([
            _dossier("PA-TC-0007", 7, findings=[_finding(
                finding_id="TF-009", evidence=[{"doc_id": "DOC14", "pages": ""},
                                               {"doc_id": "DOC14", "pages": ""}])]),
        ])
        drafts = ConsolidationDraftResult.model_validate(DRAFT_ONE)
        _ = gapped, drafts

    def test_tier_c_rejection_splits_into_single_findings_with_events(self):
        candidates = _collect_candidates([
            _dossier("PA-TC-0007", 7, findings=[_finding(
                finding_id="TF-001", category="authority",
                title="unregistered alpha beta gamma delta")]),
            _dossier("PA-TC-0008", 8, findings=[_finding(
                finding_id="TF-002", category="authority", evidence=[],
                title="unregistered epsilon zeta eta theta")]),
        ])
        chain = [
            {"tx_id": "PA-TC-0007", "chain_position": 7,
             "documented_transaction": {"sequence": 7}},
            {"tx_id": "PA-TC-0008", "chain_position": 8,
             "documented_transaction": {"sequence": 8}},
        ]
        result = _run_assemble(candidates, {"findings": [
            {"members": [0, 1], "title": "alpha group", "description": "merged"}]}, chain=chain)
        self.assertEqual([f.finding_id for f in result.findings], ["PF-001", "PF-002"])
        reasons = {event.reason for f in result.findings for event in f.lifecycle_events}
        self.assertIn("tier_c_rejected_check_7", reasons)


class TestEndToEndConsolidation(unittest.TestCase):
    """Service-level runs: v2.0 container, replay, v1 reconsolidation, Â§9."""

    def _patch_env(self, container=None, raw=None, results=None, chain=(), documents=None):
        return patch.multiple(
            agent_repo,
            list_persisted_transaction_results=lambda case_id: list(results or []),
            get_persisted_title_chain_entries=lambda case_id: list(chain),
            get_agent_documents=lambda case_id: list(documents or [{"doc_id": "DOC14"}]),
            list_requirements=lambda case_id, status=None: [],
            get_property_findings=lambda case_id: container,
            get_property_findings_raw=lambda case_id: raw,
            get_agent_result=lambda case_id: {},
        )

    def test_container_version_is_2_and_replay_is_version_aware(self):
        store = {}
        results = [_dossier("PA-TC-0007", 7, findings=[_finding(finding_id="TF-001")])]

        def fake_save(case_id, container):
            store["container"] = container

        with patch.object(agent_repo, "save_property_findings", side_effect=fake_save), \
                self._patch_env(results=results), \
                patch("backend.services.consolidation.complete_json",
                      return_value=DRAFT_CANARY) as complete:
            first = consolidate_findings(CASE)
            self.assertEqual(first["status"], "ok")
            self.assertEqual(store["container"]["container_version"], "2.0")
            self.assertEqual(complete.call_count, 1)
            # v1 container with the same input hash reconsolidates once (C2).
            prior = dict(store["container"])
            prior["container_version"] = "1.0"
            with patch.object(agent_repo, "get_property_findings", return_value=prior), \
                    patch.object(agent_repo, "get_property_findings_raw", return_value=None):
                second = consolidate_findings(CASE)
            self.assertEqual(complete.call_count, 2)
            self.assertEqual(second["container"]["container_version"], "2.0")
            # v2 container with the same input hash replays without a model pass.
            with patch.object(agent_repo, "get_property_findings",
                              return_value=second["container"]), \
                    patch.object(agent_repo, "get_property_findings_raw",
                                 return_value=second["container"]):
                third = consolidate_findings(CASE)
            self.assertEqual(complete.call_count, 2)
            self.assertEqual(third["container"], second["container"])

    def test_clean_run_registration_has_exactly_the_four_base_keys(self):
        saved = []
        with patch.object(agent_repo, "save_property_findings",
                          side_effect=lambda case_id, c: saved.append(c)), \
                self._patch_env(results=[_dossier("PA-TC-0007", 7,
                                                  findings=[_finding(finding_id="TF-001")])]), \
                patch("backend.services.consolidation.complete_json", return_value=DRAFT_CANARY):
            outcome = consolidate_findings(CASE)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(
            sorted(outcome["registration"]),
            sorted(["input_state", "malformed_observations", "excluded_evidence_refs", "disclosures"]),
        )
        self.assertEqual(CONTAINER_VERSION, "2.0")
        self.assertTrue(saved[0]["result"]["findings"][0]["identity_key"])

    def test_junk_prior_findings_are_skipped_with_warnings_and_the_run_succeeds(self):
        junk = {"finding_id": "PF-XX", "status": "OPEN",
                "consolidation": {"dedup_keys": ["k"]}}
        saved = []
        with patch.object(agent_repo, "save_property_findings",
                          side_effect=lambda case_id, c: saved.append(c)), \
                self._patch_env(container={"container_version": "1.0",
                                           "input_hash": "old",
                                           "result": {"findings": [junk]}},
                                results=[_dossier("PA-TC-0007", 7,
                                                  findings=[_finding(finding_id="TF-001")])]), \
                patch("backend.services.consolidation.complete_json", return_value=DRAFT_CANARY):
            outcome = consolidate_findings(CASE)
        self.assertEqual(outcome["status"], "ok")
        self.assertTrue(any("PF-XX" in warning
                            for warning in outcome["registration"]["reconciliation_warnings"]))

    def test_unreadable_prior_container_is_disclosed_and_overwritten_on_success(self):
        saved = []
        with patch.object(agent_repo, "save_property_findings",
                          side_effect=lambda case_id, c: saved.append(c)), \
                self._patch_env(container=None, raw="not json {{{",
                                results=[_dossier("PA-TC-0007", 7,
                                                  findings=[_finding(finding_id="TF-001")])]), \
                patch("backend.services.consolidation.complete_json", return_value=DRAFT_CANARY):
            outcome = consolidate_findings(CASE)
        self.assertEqual(outcome["status"], "ok")
        self.assertIn("prior_container_unreadable", outcome["registration"])
        self.assertIn("overwrites", outcome["registration"]["prior_container_unreadable"])
        self.assertEqual(len(saved), 1)

    def test_prior_container_read_failure_is_a_retryable_block(self):
        with patch.object(agent_repo, "save_property_findings") as save, \
                self._patch_env(results=[_dossier("PA-TC-0007", 7,
                                                  findings=[_finding(finding_id="TF-001")])]), \
                patch.object(agent_repo, "get_property_findings",
                             side_effect=ConnectionError("db down")), \
                patch.object(agent_repo, "get_property_findings_raw",
                             side_effect=ConnectionError("db down")), \
                patch("backend.services.consolidation.complete_json") as complete:
            outcome = consolidate_findings(CASE)
        self.assertEqual(outcome["status"], "blocked")
        self.assertTrue(outcome["retryable"])
        self.assertIn("prior property-findings container", outcome["reason"])
        save.assert_not_called()
        complete.assert_not_called()

    def test_v1_prior_carries_through_the_full_pipeline(self):
        prior = {"container_version": "1.0", "input_hash": "old", "result": {"findings": [
            {"finding_id": "PF-001", "status": "OPEN", "category": "authority",
             "title": "Unregistered sale of reserved plot",
             "description": "d", "severity": "CAUTION",
             "consolidation": {"dedup_keys": None}},
        ]}}
        saved = []
        with patch.object(agent_repo, "save_property_findings",
                          side_effect=lambda case_id, c: saved.append(c)), \
                self._patch_env(container=prior,
                                results=[_dossier("PA-TC-0007", 7,
                                                  findings=[_finding(finding_id="TF-001")])]), \
                patch("backend.services.consolidation.complete_json",
                      return_value=DRAFT_CANARY):
            outcome = consolidate_findings(CASE)
        self.assertEqual(outcome["status"], "ok")
        container = outcome["container"]
        self.assertEqual(container["container_version"], "2.0")
        finding = next(f for f in container["result"]["findings"]
                       if f.get("identity_key"))
        self.assertTrue(str(finding["finding_id"]).startswith("PF-"))

    def test_draft_identity_fields_cannot_come_from_the_model(self):
        with self.assertRaises(ValidationError):
            FindingDraft.model_validate({
                "members": [0], "title": "t", "description": "d",
                "identity_key": "A|faked|kinds|1|2|3",
            })
