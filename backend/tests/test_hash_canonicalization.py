"""C6 — hash-canonicalization tests (§8.2 hardening).

Pins the byte-level determinism the currentness contract rests on: the
canonical-JSON primitive (sorted keys, no extra space, unicode-true), the
phase-A scope (only ``property_identity`` + ``title_chain`` hash), the I0
contract identity, and I-group ordering invariants. Pure unit tests — the
behavioral invalidation matrix lives in test_currentness.py.
"""

import hashlib
import unittest
from unittest import mock

from backend.schemas.analysis import content_hash, phase_a_hash
from backend.database.repositories import agent_repo
from backend.services.consolidation import (
    CONTAINER_VERSION,
    INPUT_HASH_VERSION,
    _external_input_hash,
    _i0_bundle,
    _i2_bundle,
    _phase_a_state,
)

CHAIN = [{
    "tx_id": "PA-TC-0007", "chain_position": 7,
    "documented_transaction": {
        "sequence": 7, "transaction_number": "REG-99",
        "transferors": ["Old Owner"], "transferees": ["New Owner"],
        "parcel_identifier": "PARCEL-1",
    },
}]
ROWS = [{
    "tx_id": "PA-TC-0007", "sequence": 7, "revision": 2,
    "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
    "findings": [{"finding_id": "TF-001", "title": "Mortgage",
                  "text": "memo", "category": "ENCUMBRANCE"}],
}]


class TestContentHashCanonicalization(unittest.TestCase):
    """The §8.2 premise: hashing is over canonical JSON, byte-stable."""

    def test_key_order_invariance(self):
        self.assertEqual(
            content_hash({"b": 1, "a": {"z": 2, "y": 3}}),
            content_hash({"a": {"y": 3, "z": 2}, "b": 1}))

    def test_list_order_is_semantic(self):
        # lists are content, not maps: order participates verbatim
        self.assertNotEqual(
            content_hash({"k": [1, 2]}), content_hash({"k": [2, 1]}))

    def test_unicode_is_not_escaped(self):
        payload = {"title": "mortgage-é日本"}
        expected = hashlib.sha256('{"title":"mortgage-é日本"}'.encode("utf-8")).hexdigest()
        self.assertEqual(content_hash(payload), expected)

    def test_no_extra_space_bytes(self):
        expected = hashlib.sha256(b'{"a":1,"b":[1,2]}').hexdigest()
        self.assertEqual(content_hash({"a": 1, "b": [1, 2]}), expected)


class TestPhaseAHashScope(unittest.TestCase):
    """I1's basis: only property_identity + title_chain participate."""

    def test_prose_and_unrelated_keys_are_excluded(self):
        base = {"property_identity": {"survey_number": "S/1"}, "title_chain": []}
        decorated = {
            **base,
            "title_chain_graph": "prose narrative moved this year",
            "status": "done", "case_result": [{"tx_id": "PA-TC-0001"}],
        }
        self.assertEqual(phase_a_hash(base), phase_a_hash(decorated))

    def test_content_in_scoped_keys_moves_the_hash(self):
        base = {"property_identity": {"survey_number": "S/1"}, "title_chain": []}
        moved = {
            "property_identity": {"survey_number": "S/1"},
            "title_chain": [{"chain_position": 7}],
        }
        self.assertNotEqual(phase_a_hash(base), phase_a_hash(moved))

    def test_persisted_literal_wins_over_derived(self):
        # _phase_a_state: a persisted phase_a_hash is the input when present
        carried = {"phase_a_hash": "PH-A-V1",
                   "property_identity": {"survey_number": "S/2"}}
        with mock.patch.object(agent_repo, "get_agent_result",
                               return_value=carried):
            self.assertEqual(_phase_a_state("CASE1"), "PH-A-V1")


class TestI0ContractIdentity(unittest.TestCase):
    def test_literal_members_and_version_pins(self):
        bundle = _i0_bundle()
        self.assertEqual(bundle["input_hash_version"], INPUT_HASH_VERSION)
        self.assertEqual(INPUT_HASH_VERSION, 3)
        self.assertEqual(bundle["container_version"], CONTAINER_VERSION)
        enums = bundle["enums"]
        self.assertEqual(enums["finding_statuses"], sorted(enums["finding_statuses"]))
        self.assertIn("PENDING_EVIDENCE", enums["finding_statuses"])
        self.assertIn("DISPUTED", enums["finding_statuses"])
        self.assertEqual(enums["readiness_states"], ["COMPLETE", "PARTIAL"])
        self.assertEqual(enums["correlation_types"],
                         ["CONFLICTS_WITH", "DEPENDS_ON", "MERGED_INTO",
                          "RELATED", "SPLIT_FROM"])


class TestExternalInputHash(unittest.TestCase):
    def _hash(self, *, chain=None, rows=(), documents=None, case_id="CASE1"):
        return _external_input_hash(
            case_id=case_id,
            chain_by_tx={entry["tx_id"]: {
                "transaction": entry["documented_transaction"],
                "position": entry["chain_position"],
            } for entry in (chain or CHAIN)},
            phase_a_hash="PH-A",
            rows=list(rows),
            documents=documents if documents is not None
            else [{"doc_id": "DOC1", "status": "processed"}],
            all_requirements=[],
        )

    def test_row_bundle_order_is_tx_sorted(self):
        second = dict(ROWS[0], tx_id="PA-TC-0002")
        self.assertEqual(_i2_bundle([second, ROWS[0]]), _i2_bundle([ROWS[0], second]))
        self.assertEqual(self._hash(rows=[ROWS[0], second]),
                         self._hash(rows=[second, ROWS[0]]))

    def test_hash_is_immediately_deterministic(self):
        self.assertEqual(self._hash(), self._hash())

    def test_i9_case_binding(self):
        self.assertNotEqual(self._hash(case_id="CASE1"),
                            self._hash(case_id="CASE2"))

    def test_i1_chain_entry_change_moves_the_hash(self):
        changed = [{
            "tx_id": CHAIN[0]["tx_id"], "chain_position": CHAIN[0]["chain_position"],
            "documented_transaction": {
                **CHAIN[0]["documented_transaction"],
                "transferors": ["Renamed Owner"]},
        }]
        self.assertNotEqual(self._hash(chain=changed), self._hash(chain=CHAIN))

    def test_junk_finding_entries_are_not_hashed(self):
        # I3 hashes the sanitized view: non-dict findings are excluded
        junky = dict(ROWS[0], findings=[ROWS[0]["findings"][0], "junk", None])
        self.assertEqual(self._hash(rows=[junky]), self._hash(rows=[ROWS[0]]))

    def test_i6_roster_status_moves_the_hash(self):
        self.assertNotEqual(
            self._hash(documents=[{"doc_id": "DOC1", "status": "processed"}]),
            self._hash(documents=[{"doc_id": "DOC1", "status": "failed"}]))


if __name__ == "__main__":
    unittest.main()
