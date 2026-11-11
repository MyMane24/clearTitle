"""Implementation 1: Phase A stable transaction identity (task §3, §9).
Covers app-controlled PA-TC id assignment, position-independent content
matching across reruns, ambiguity handling, and per-case id uniqueness against
persisted transaction results — all against the pure chain_identity module.
"""
import unittest
from backend.services import chain_identity as CI
def _entry(position, transaction_type="Sale deed", *, reg_number=None, executed_date=None,
           transferors=None, transferees=None, source_refs=(), registration_office=None,
           survey_number=None):
    return {
        "chain_position": position,
        "documented_transaction": {
            "transaction_type": transaction_type,
            "transaction_number": reg_number,
            "registration_office": registration_office,
            "executed_date": executed_date,
            "transferors": transferors or [],
            "transferees": transferees or [],
            "survey_number": survey_number,
            "summary_points": ["The deed transfers the described property."],
            "source_refs": [{"doc_id": doc_id} for doc_id in source_refs],
        },
    }
class TestChainIdAssignment(unittest.TestCase):
    def test_fresh_chain_gets_sequential_ids(self):
        chain = [_entry(1), _entry(2)]
        CI.assign_chain_tx_ids(chain, [], set())
        self.assertEqual([entry["tx_id"] for entry in chain], ["PA-TC-0001", "PA-TC-0002"])
    def test_model_supplied_ids_are_stripped_before_assignment(self):
        chain = [_entry(1, reg_number="REG-1")]
        chain[0]["tx_id"] = "INVENTED-1"
        chain[0]["documented_transaction"]["tx_id"] = "INVENTED-2"
        notes = CI.assign_chain_tx_ids(chain, [], set())
        self.assertEqual(chain[0]["tx_id"], "PA-TC-0001")
        self.assertNotIn("tx_id", chain[0]["documented_transaction"])
        self.assertTrue(all("keep" not in note for note in notes))
    def test_ids_are_preserved_by_content_not_position(self):
        first = [_entry(1, "Sale deed", reg_number="REG-1"), _entry(2, "Gift deed", reg_number="REG-2")]
        CI.attach_upstream_ids(first)
        first[0]["documented_transaction"]["executed_date"] = "2012-04-05"
        CI.assign_chain_tx_ids(first, [], set())
        # Rerun: the same two transactions arrive in REVERSED order.
        rerun = [
            _entry(1, "Gift deed", reg_number="REG-2"),
            _entry(2, "Sale deed", reg_number="REG-1", executed_date="2012-04-05"),
        ]
        notes = CI.assign_chain_tx_ids(rerun, first, set())
        self.assertEqual([entry["tx_id"] for entry in rerun], ["PA-TC-0002", "PA-TC-0001"])
        self.assertTrue(any("keeps PA-TC-0002" in note for note in notes))
    def test_position_only_overlap_does_not_preserve_ids(self):
        # Same type/date/parties but a DIFFERENT transaction (different reg
        # numbers, different docs): no content rule matches → new ids.
        first = [
            _entry(1, "Sale deed", reg_number="REG-1", executed_date="2012-04-05",
                   transferors=["A"], transferees=["B"], source_refs=("DOC1",)),
        ]
        CI.assign_chain_tx_ids(first, [], set())
        rerun = [
            _entry(1, "Sale deed", reg_number="REG-9", executed_date="2021-08-08",
                   transferors=["C"], transferees=["D"], source_refs=("DOC2",)),
        ]
        CI.assign_chain_tx_ids(rerun, first, set())
        self.assertEqual(rerun[0]["tx_id"], "PA-TC-0002")
    def test_party_continuity_matches_when_no_registration_number(self):
        prior = [
            _entry(1, "Sale deed", executed_date="2001-01-30", transferors=["A"], transferees=["B"],
                   source_refs=("DOC1",)),
        ]
        CI.assign_chain_tx_ids(prior, [], set())
        rerun = [
            _entry(1, "Sale deed", executed_date="2001-01-30", transferors=["B"], transferees=["C"],
                   source_refs=("DOC9",)),
        ]
        CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], prior[0]["tx_id"])
    def test_source_document_match_keeps_dated_recital_links(self):
        # Historical/recital-reported link WITH a stated date: the identical
        # source-document set proves it is the same reported link.
        prior = [_entry(1, "Succession", executed_date="1985-03-27", source_refs=("DOC1",))]
        CI.assign_chain_tx_ids(prior, [], set())
        rerun = [_entry(1, "Succession", executed_date="1985-03-27", source_refs=("DOC1",))]
        CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], prior[0]["tx_id"])
    def test_recital_only_link_without_an_identity_anchor_gets_a_recorded_new_id(self):
        # Design limit: without registration reference, date, or party
        # continuity, a recital-reported link cannot be safely re-identified on
        # rerun — it receives a fresh id and the decision is noted.
        prior = [_entry(1, "Succession", source_refs=("DOC1",))]
        CI.assign_chain_tx_ids(prior, [], set())
        rerun = [_entry(1, "Succession", source_refs=("DOC1",))]
        notes = CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], "PA-TC-0002")  # prior ids never reused
        self.assertTrue(any("assigned" in note for note in notes))
    def test_ambiguous_match_gets_fresh_id_and_recorded_note(self):
        # Two previous entries both match on type + date + identical source
        # documents (the same deed narrates two reported steps) — no safe reuse.
        prior = [
            _entry(1, "Sale deed", executed_date="2001-01-30", source_refs=("DOC1",)),
            _entry(2, "Sale deed", executed_date="2001-01-30", source_refs=("DOC1",)),
        ]
        CI.assign_chain_tx_ids(prior, [], set())
        self.assertEqual(prior[0]["tx_id"], "PA-TC-0001")
        self.assertEqual(prior[1]["tx_id"], "PA-TC-0002")
        rerun = [_entry(1, "Sale deed", executed_date="2001-01-30", source_refs=("DOC1",))]
        notes = CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], "PA-TC-0003")
        self.assertTrue(any("ambiguous" in note for note in notes))
    def test_next_free_id_skips_ids_taken_by_persisted_results(self):
        chain = [_entry(1), _entry(2), _entry(3)]
        CI.assign_chain_tx_ids(chain, [], {"PA-TC-0002", "PA-TC-0007"})
        # 0001 free, 0002 taken by a previous transaction's result row.
        self.assertEqual(
            [entry["tx_id"] for entry in chain],
            ["PA-TC-0001", "PA-TC-0003", "PA-TC-0004"],
        )
    def test_unmatched_prior_id_is_never_reassigned(self):
        prior = [_entry(1, "Sale deed", reg_number="REG-1"), _entry(2, "Gift deed", reg_number="REG-2")]
        CI.assign_chain_tx_ids(prior, [], set())
        # The Gift link disappeared from the rerun chain (merged into another entry).
        rerun = [_entry(1, "Sale deed", reg_number="REG-1")]
        CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], "PA-TC-0001")
    def test_upstream_links_follow_party_continuity(self):
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"]),
            _entry(2, "Sale deed", transferors=["B"], transferees=["C"]),
            _entry(3, "Gift deed", transferors=["X"], transferees=["Y"]),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        CI.attach_upstream_ids(chain)
        self.assertIsNone(chain[0].get("upstream_tx_ids"))
        self.assertEqual(chain[1].get("upstream_tx_ids"), ["PA-TC-0001"])
        self.assertIsNone(chain[2].get("upstream_tx_ids"))
class TestRegistrationOfficeIdentity(unittest.TestCase):
    """Corrective patch (review finding §1.3): registration numbers are
    office-scoped, so the stated office participates in the
    registration-reference match. Missing office data keeps the historical
    number-match strength — documented limitation."""
    def test_same_number_and_same_office_keeps_the_id(self):
        prior = [_entry(1, "Sale deed", reg_number="REG-77", registration_office="Sub-Registrar Bangalore",
                        executed_date="2012-04-05", transferors=["A"], transferees=["B"],
                        source_refs=("DOC1",))]
        CI.assign_chain_tx_ids(prior, [], set())
        rerun = [_entry(1, "Sale deed", reg_number="REG-77", registration_office="Sub-Registrar Bangalore",
                        executed_date="2012-04-05", transferors=["A"], transferees=["B"],
                        source_refs=("DOC1",))]
        notes = CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], "PA-TC-0001")
        self.assertTrue(any("keeps PA-TC-0001" in note for note in notes))
    def test_same_number_from_a_different_office_is_a_different_transaction(self):
        # The review's demonstrated false match: another office reusing the
        # instrument number must not claim the prior transaction's id, even
        # though the number alone would match.
        prior = [_entry(1, "Sale deed", reg_number="REG-77", registration_office="Sub-Registrar Bangalore",
                        transferors=["A"], transferees=["B"], source_refs=("DOC1",))]
        CI.assign_chain_tx_ids(prior, [], set())
        rerun = [_entry(1, "Gift deed", reg_number="REG-77", registration_office="Sub-Registrar Mysuru",
                        transferors=["X"], transferees=["Y"], source_refs=("DOC9",))]
        notes = CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], "PA-TC-0002")
        self.assertTrue(any("assigned" in note for note in notes))
    def test_office_missing_on_rerun_keeps_historical_number_match(self):
        # Documented limitation: unrecorded office data cannot contradict the
        # number match, so the historical match strength is preserved.
        prior = [_entry(1, "Sale deed", reg_number="REG-77", registration_office="Sub-Registrar Bangalore",
                        transferors=["A"], transferees=["B"], source_refs=("DOC1",))]
        CI.assign_chain_tx_ids(prior, [], set())
        rerun = [_entry(1, "Sale deed", reg_number="REG-77", transferors=["A"], transferees=["B"],
                        source_refs=("DOC1",))]
        CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], "PA-TC-0001")
    def test_ambiguous_number_match_across_offices_is_refused(self):
        # Two priors share the number (duplicate legacy records from different
        # offices, offices stated). An office-less rerun content matches both →
        # no safe reuse; the ambiguity refusal is unchanged.
        prior = [
            _entry(1, "Sale deed", reg_number="REG-5", registration_office="Office A",
                   executed_date="2001-01-30", source_refs=("DOC1",)),
            _entry(2, "Sale deed", reg_number="REG-5", registration_office="Office B",
                   executed_date="2001-01-30", source_refs=("DOC2",)),
        ]
        CI.assign_chain_tx_ids(prior, [], set())
        rerun = [_entry(1, "Sale deed", reg_number="REG-5", executed_date="2001-01-30", source_refs=("DOC3",))]
        notes = CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], "PA-TC-0003")
        self.assertTrue(any("ambiguous" in note for note in notes))
    def test_stated_office_disambiguates_a_reused_number(self):
        # Providing the office resolves the number-match ambiguity: only the
        # matching-office prior is a candidate, so its id is kept. Source
        # documents differ between the priors so the doc-set rule cannot fire.
        prior = [
            _entry(1, "Sale deed", reg_number="REG-5", registration_office="Office A",
                   executed_date="2001-01-30", source_refs=("DOC1",)),
            _entry(2, "Sale deed", reg_number="REG-5", registration_office="Office B",
                   executed_date="2001-01-30", source_refs=("DOC2",)),
        ]
        CI.assign_chain_tx_ids(prior, [], set())
        rerun = [_entry(1, "Sale deed", reg_number="REG-5", registration_office="Office B",
                        executed_date="2001-01-30", source_refs=("DOC2",))]
        CI.assign_chain_tx_ids(rerun, prior, set())
        self.assertEqual(rerun[0]["tx_id"], "PA-TC-0002")
class TestMultiParentUpstream(unittest.TestCase):
    """Corrective patch (review finding §7): a consolidated conveyance can
    legitimately depend on multiple predecessors."""
    def test_consolidated_conveyance_records_all_valid_predecessors(self):
        # Two independent branch conveyances; the third transferor holds under
        # both branches (partition/settlement consolidating them). The
        # non-adjacent branch parent is corroborated by the partition deed
        # recording the parent's parcel code (subdivided); the adjacent one is
        # the ordinary succession link.
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"], survey_number="S-50"),
            _entry(2, "Sale deed", transferors=["C"], transferees=["D"], survey_number="S-77"),
            _entry(3, "Partition deed", transferors=["B", "D"], transferees=["E"],
                   survey_number="S-50/1, S-50/2"),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        notes = CI.attach_upstream_ids(chain)
        self.assertEqual(chain[2]["upstream_tx_ids"], ["PA-TC-0001", "PA-TC-0002"])
        self.assertTrue(any("continuing parcel" in note for note in notes))
    def test_adjacent_continuity_relationship_is_unchanged(self):
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"]),
            _entry(2, "Sale deed", transferors=["B"], transferees=["C"]),
            _entry(3, "Gift deed", transferors=["X"], transferees=["Y"]),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        CI.attach_upstream_ids(chain)
        self.assertIsNone(chain[0].get("upstream_tx_ids"))
        self.assertEqual(chain[1].get("upstream_tx_ids"), ["PA-TC-0001"])
        self.assertIsNone(chain[2].get("upstream_tx_ids"))
class TestTxFindingIdAllocationOverflow(unittest.TestCase):
    """Corrective patch (review finding §6): exhausting the three-digit counter
    must not fail the save; ids widen to TF-1000+ without changing TF-### ids."""
    def test_allocation_beyond_tf_999_continues_at_tf_1000(self):
        finding = {"title": "Thousandth observation", "category": "CHAIN_GAP", "evidence": []}
        CI.assign_finding_ids("PA-TC-0001", [finding], {}, set(range(1, 1000)))
        self.assertEqual(finding["finding_id"], "TF-1000")
    def test_four_digit_ids_round_trip_through_the_registry(self):
        content = {"title": "Same observation", "category": "CHAIN_GAP",
                   "evidence": [{"doc_id": "DOC1"}]}
        rows = [{"tx_id": "PA-TC-0001", "findings": [dict(content, finding_id="TF-1000")]}]
        registry, used = CI.finding_registry(rows)
        self.assertEqual(used, {1000})
        assigned = dict(content)
        CI.assign_finding_ids("PA-TC-0001", [assigned], registry, used)
        self.assertEqual(assigned["finding_id"], "TF-1000")
class TestUpstreamMatchingSafety(unittest.TestCase):
    """Part 2 (reliability review): party-name overlap alone is trusted only
    for the adjacent chain link; non-adjacent predecessors need corroborating
    evidence inside the transaction records, or they stay unlinked."""
    def test_common_name_across_a_chain_jump_does_not_link(self):
        # "Ram" is a transferee at item 1 and a transferor at item 3 — nothing
        # older-but-unreadable distinguishes him from a namesake, so the
        # uncertainty is preserved: no speculative link, decision recorded.
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["Ram"]),
            _entry(2, "Sale deed", transferors=["X"], transferees=["Y"]),
            _entry(3, "Sale deed", transferors=["Ram"], transferees=["Z"]),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        notes = CI.attach_upstream_ids(chain)
        self.assertIsNone(chain[2].get("upstream_tx_ids"))
        self.assertTrue(any("refused upstream PA-TC-0001" in note for note in notes))
    def test_partial_name_overlap_is_not_continuity(self):
        # Names are matched on normalized full equality: "Sri Ram" and "Ram"
        # are different record identities and do not even become candidates.
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["Sri Ram"]),
            _entry(2, "Sale deed", transferors=["Ram"], transferees=["B"]),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        CI.attach_upstream_ids(chain)
        self.assertIsNone(chain[1].get("upstream_tx_ids"))
    def test_same_party_with_conflicting_parcels_is_rejected(self):
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"], survey_number="S-50"),
            _entry(2, "Sale deed", transferors=["C"], transferees=["D"], survey_number="S-77"),
            _entry(3, "Sale deed", transferors=["B"], transferees=["E"], survey_number="S-90"),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        notes = CI.attach_upstream_ids(chain)
        self.assertIsNone(chain[2].get("upstream_tx_ids"))
        self.assertTrue(any("parcel identifiers differ" in note for note in notes))
    def test_chronologically_impossible_link_is_rejected_even_adjacent(self):
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"], executed_date="2021-06-01"),
            _entry(2, "Sale deed", transferors=["B"], transferees=["C"], executed_date="2020-01-01"),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        notes = CI.attach_upstream_ids(chain)
        self.assertIsNone(chain[1].get("upstream_tx_ids"))
        self.assertTrue(any("executed after this transaction" in note for note in notes))
    def test_uncomparable_dates_are_never_invented_into_rejections(self):
        # Prose dates ("13 January 1981") cannot be ordered safely; the
        # adjacency rule still applies and no false refusal is manufactured.
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"], executed_date="13 January 1981"),
            _entry(2, "Sale deed", transferors=["B"], transferees=["C"]),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        CI.attach_upstream_ids(chain)
        self.assertEqual(chain[1].get("upstream_tx_ids"), ["PA-TC-0001"])
    def test_subdivided_parcel_corroborates_a_jumped_parent(self):
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"], survey_number="S-50"),
            _entry(2, "Sale deed", transferors=["C"], transferees=["D"], survey_number="S-77"),
            _entry(3, "Partition deed", transferors=["B", "D"], transferees=["E"],
                   survey_number="S-50/1, S-50/2"),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        notes = CI.attach_upstream_ids(chain)
        self.assertEqual(chain[2]["upstream_tx_ids"], ["PA-TC-0001", "PA-TC-0002"])
        self.assertTrue(any("continuing parcel" in note for note in notes))
        self.assertTrue(any("adjacent chain succession" in note for note in notes))
    def test_word_boundary_guards_partial_surveys(self):
        # S-1 must not match S-100: both sides state parcels, they never
        # relate, so the jumped link is refused as a conflicting match.
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"], survey_number="S-1"),
            _entry(2, "Sale deed", transferors=["C"], transferees=["D"], survey_number="S-60"),
            _entry(3, "Sale deed", transferors=["B"], transferees=["E"], survey_number="S-100"),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        CI.attach_upstream_ids(chain)
        self.assertIsNone(chain[2].get("upstream_tx_ids"))
    def test_shared_source_document_corroborates_a_jumped_parent(self):
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"], source_refs=("DOC_BUNDLE",)),
            _entry(2, "Sale deed", transferors=["C"], transferees=["D"], source_refs=("DOC2",)),
            _entry(3, "Family settlement", transferors=["B"], transferees=["E"],
                   source_refs=("DOC_BUNDLE", "DOC9")),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        notes = CI.attach_upstream_ids(chain)
        self.assertEqual(chain[2].get("upstream_tx_ids"), ["PA-TC-0001"])
        self.assertTrue(any(
            "shared source documents" in note and "PA-TC-0001" in note for note in notes),
            notes)
    def test_same_instrument_number_across_offices_does_not_link(self):
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"],
                   reg_number="REG-9", registration_office="Office A"),
            _entry(2, "Sale deed", transferors=["X"], transferees=["Y"]),
            _entry(3, "Sale deed", transferors=["B"], transferees=["D"],
                   reg_number="REG-9", registration_office="Office B"),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        CI.attach_upstream_ids(chain)
        self.assertIsNone(chain[2].get("upstream_tx_ids"))
    def test_same_instrument_number_corroborates_when_offices_agree(self):
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"],
                   reg_number="REG-9", registration_office="Office A"),
            _entry(2, "Sale deed", transferors=["X"], transferees=["Y"]),
            _entry(3, "Correction deed", transferors=["B"], transferees=["D"],
                   reg_number="REG-9", registration_office="Office A"),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        CI.attach_upstream_ids(chain)
        self.assertEqual(chain[2].get("upstream_tx_ids"), ["PA-TC-0001"])
    def test_missing_identifiers_without_adjacency_stay_unlinked(self):
        # Both sides lack parcel/instrument/data — no anchors, no invented link.
        chain = [
            _entry(1, "Sale deed", transferors=["A"], transferees=["B"]),
            _entry(2, "Sale deed", transferors=["C"], transferees=["D"]),
            _entry(3, "Sale deed", transferors=["B"], transferees=["E"]),
        ]
        CI.assign_chain_tx_ids(chain, [], set())
        CI.attach_upstream_ids(chain)
        self.assertIsNone(chain[2].get("upstream_tx_ids"))
if __name__ == "__main__":  # pragma: no cover
    unittest.main()
