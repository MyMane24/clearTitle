import json
import unittest
from unittest.mock import patch

from backend.services import case_memory
from backend.services.agent_schemas import TransactionVerification
from backend.services.agent_tools import ToolContext, _validate_handoff
from backend.services.cleartitle_agent import (
    _build_upstream_context,
    _case_memory_block,
    _fit_memory_budget,
    _verify_instruction,
)


def _entry(position, transferors, transferees, kind="Sale deed"):
    return {
        "chain_position": position,
        "documented_transaction": {
            "transaction_type": kind, "transaction_number": f"REG-{position}",
            "transferors": transferors, "transferees": transferees,
            "summary_points": ["fact"],
        },
        "related_events": [],
    }


def _chain():
    return {"title_chain": [
        _entry(1, ["Shri Ramesh Kumar"], ["Suresh Rao", "Lakshmi Rao"]),
        _entry(2, ["Suresh Rao", "Smt Lakshmi Rao"], ["Anil Shetty"]),
        _entry(3, ["Mohan Das"], ["Priya Nair"]),
    ]}


class TestPartyMatching(unittest.TestCase):
    def test_honorifics_order_and_spelling_do_not_break_a_match(self):
        self.assertTrue(case_memory.parties_match("Shri Suresh Rao", "Rao Suresh"))
        self.assertTrue(case_memory.parties_match("Smt Lakshmi Rao", "Lakshmi Rao"))
        self.assertFalse(case_memory.parties_match("Suresh Rao", "Anil Shetty"))
        self.assertFalse(case_memory.parties_match("", "Anil Shetty"))

    def test_continuity_hint_states(self):
        holders = ["Suresh Rao", "Lakshmi Rao"]
        self.assertEqual(case_memory.continuity_hint(holders, ["Suresh Rao"])["state"], "SAME")
        self.assertEqual(
            case_memory.continuity_hint(holders, ["Suresh Rao", "Other Person"])["state"], "PARTIAL"
        )
        different = case_memory.continuity_hint(holders, ["Mohan Das"])
        self.assertEqual(different["state"], "DIFFERENT")
        self.assertEqual(different["unmatched"], ["Mohan Das"])
        self.assertEqual(case_memory.continuity_hint([], ["Mohan Das"])["state"], "UNKNOWN")


class TestHandoffDerivation(unittest.TestCase):
    def test_root_transaction_is_marked_root_with_transferees_as_holders(self):
        entry = _chain()["title_chain"][0]
        out = case_memory.derive_handoff(
            {"note_for_next": "keep"}, sequence=1, entry=entry, previous_result=None, previous_entry=None
        )
        self.assertEqual(out["continuity"], "ROOT")
        self.assertEqual(out["holders_after"], ["Suresh Rao", "Lakshmi Rao"])
        self.assertEqual(out["note_for_next"], "keep")  # model-authored text is kept verbatim

    def test_same_parties_confirm_continuity_but_differences_stay_unknown(self):
        chain = _chain()["title_chain"]
        confirmed = case_memory.derive_handoff(
            {}, sequence=2, entry=chain[1], previous_result=None, previous_entry=chain[0]
        )
        self.assertEqual(confirmed["continuity"], "CONFIRMED")
        unresolved = case_memory.derive_handoff(
            {}, sequence=3, entry=chain[2], previous_result=None, previous_entry=chain[1]
        )
        # A name mismatch is not enough to call the chain broken - that is the model's call.
        self.assertEqual(unresolved["continuity"], "UNKNOWN")

    def test_model_supplied_continuity_and_holders_win(self):
        chain = _chain()["title_chain"]
        out = case_memory.derive_handoff(
            {"continuity": "NOT_DOCUMENTED", "holders_after": ["X"]},
            sequence=3, entry=chain[2], previous_result=None, previous_entry=chain[1],
        )
        self.assertEqual(out["continuity"], "NOT_DOCUMENTED")
        self.assertEqual(out["holders_after"], ["X"])

    def test_previous_saved_handoff_beats_phase_a_transferees(self):
        holders, source = case_memory.holders_entering(
            {"handoff": {"holders_after": ["Verified Holder"]}}, _chain()["title_chain"][0]
        )
        self.assertEqual((holders, source), (["Verified Holder"], "previous_handoff"))


class TestHandoffSaveValidation(unittest.TestCase):
    def _ctx(self):
        docs = [{"doc_id": "DOC1", "filename": "a.pdf", "status": "structured"}]
        ctx = ToolContext("CASE1", docs, current_tx_id="PA-TC-0002", phase_a_chain=_chain()["title_chain"])
        return ctx

    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_unread_document_in_established_facts_is_rejected(self, _prior):
        from backend.services.agent_schemas import SchemaValidationError

        payload = {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
                   "handoff": {"established": [{"fact": "A sold to B", "doc_id": "DOC1"}]}}
        with self.assertRaises(SchemaValidationError) as raised:
            _validate_handoff(self._ctx(), payload, {}, 2, force_pending=False)
        self.assertIn("complete OCR was not reviewed", str(raised.exception))

    @patch("backend.services.agent_tools.repo.get_transaction_result", return_value=None)
    def test_completed_result_gets_derived_holders_and_app_owned_stale_flag(self, _prior):
        ctx = self._ctx()
        ctx.selected_document_ids.add("DOC1")
        ctx.read_text_ranges["DOC1"] = [(0, 10, 10)]
        payload = {"status": "ISSUES_IDENTIFIED", "handoff": {
            "stale": True, "established": [{"fact": "A sold to B", "doc_id": "DOC1"}],
        }}
        _validate_handoff(ctx, payload, {}, 2, force_pending=False)
        self.assertEqual(payload["handoff"]["holders_after"], ["Anil Shetty"])
        self.assertEqual(payload["handoff"]["continuity"], "CONFIRMED")
        self.assertFalse(payload["handoff"]["stale"])

    def test_pending_checkpoint_carries_no_derived_memory(self):
        payload = {"status": "PENDING_NOT_VERIFIED"}
        _validate_handoff(self._ctx(), payload, {}, 2, force_pending=True)
        self.assertEqual(payload["handoff"], {"stale": False})

    def test_handoff_round_trips_through_the_result_schema(self):
        result = TransactionVerification(
            tx_id="PA-TC-0001", sequence=1, status="INCONCLUSIVE", report="## Conclusion\n\nx",
            handoff={"continuity": "ROOT", "holders_after": ["A"], "note_for_next": "n"},
        )
        self.assertEqual(result.model_dump()["handoff"]["holders_after"], ["A"])


class TestCaseMemoryBlock(unittest.TestCase):
    @patch("backend.services.cleartitle_agent.repo")
    def test_block_lists_ledger_holders_and_continuity_hint(self, repo):
        repo.get_transaction_result.side_effect = lambda case_id, tx_id: {
            "PA-TC-0001": {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
                           "executive_summary": "Root deed holds.",
                           "handoff": {"holders_after": ["Suresh Rao", "Lakshmi Rao"]}},
            "PA-TC-0002": {"status": "ISSUES_IDENTIFIED", "executive_summary": "Share mismatch.",
                           "handoff": {"holders_after": ["Anil Shetty"]}},
        }.get(tx_id)
        phase_a = _chain()
        from backend.services.cleartitle_agent import _phase_a_transactions

        third = _phase_a_transactions(phase_a)[2]
        block = _case_memory_block("CASE1", phase_a, third)

        self.assertIn("1. Sale deed — VERIFIED_WITH_AVAILABLE_EVIDENCE: Root deed holds.", block)
        self.assertIn("2. Sale deed — ISSUES_IDENTIFIED: Share mismatch.", block)
        self.assertIn("Anil Shetty", block)  # holders entering = previous link's handoff
        self.assertIn("CONTINUITY HINT", block)
        self.assertIn("DIFFERENT", block)  # Mohan Das is not Anil Shetty
        self.assertIn("Mohan Das", block)

    @patch("backend.services.cleartitle_agent.repo")
    def test_root_transaction_has_no_memory_block(self, _repo):
        from backend.services.cleartitle_agent import _phase_a_transactions

        phase_a = _chain()
        self.assertEqual(_case_memory_block("CASE1", phase_a, _phase_a_transactions(phase_a)[0]), "")

    @patch("backend.services.cleartitle_agent.repo")
    def test_previous_link_handoff_replaces_its_prose_report(self, repo):
        repo.get_transaction_result.side_effect = lambda case_id, tx_id: {
            "PA-TC-0001": {"status": "VERIFIED_WITH_AVAILABLE_EVIDENCE", "report": "LONG PROSE REPORT",
                           "handoff": {"holders_after": ["A"], "established": [{"fact": "f", "doc_id": "D"}],
                                       "note_for_next": "mind the share"}},
        }.get(tx_id)
        context = _build_upstream_context("CASE1", _chain(), 2)
        self.assertNotIn("report", context[0])
        self.assertEqual(context[0]["handoff"]["note_for_next"], "mind the share")
        self.assertIn("established", context[0]["handoff"])

    def test_budget_trims_oldest_links_first_and_keeps_the_previous_one(self):
        old = {"tx_id": "A", "handoff": {"established": [{"fact": "x" * 400}] * 8, "note_for_next": "keep"}}
        prev = {"tx_id": "B", "handoff": {"established": [{"fact": "y" * 400}] * 8}}
        context = [old, prev]
        _fit_memory_budget(context, 6000)
        self.assertNotIn("established", context[0]["handoff"])
        self.assertIn("established", context[1]["handoff"])  # the previous link is never trimmed
        self.assertEqual(context[0]["handoff"]["note_for_next"], "keep")

    def test_instruction_embeds_the_memory_block_before_the_context_json(self):
        from backend.services.cleartitle_agent import _phase_a_transactions

        tx = _phase_a_transactions(_chain())[2]
        ctx = [{"tx_id": "PA-TC-0001", "sequence": 1, "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE"}]
        text = _verify_instruction(tx, upstream_context=ctx, memory_block="\nPROGRESS LEDGER (x):\n1. y")
        self.assertIn("PROGRESS LEDGER", text)
        self.assertLess(text.index("PROGRESS LEDGER"), text.index(json.dumps("PA-TC-0001")))


if __name__ == "__main__":
    unittest.main()


class TestHandoffSurvivesTheReadAdapter(unittest.TestCase):
    def test_normalizing_a_saved_result_keeps_its_handoff(self):
        from backend.services.agent_schemas import normalize_transaction_verification

        saved = TransactionVerification(
            tx_id="PA-TC-0002", sequence=2, status="ISSUES_IDENTIFIED", report="**Verdict:** x",
            cited_documents=[{"doc_id": "DOC_001"}],
            handoff={"continuity": "CONFIRMED", "holders_after": ["Anil Shetty"], "note_for_next": "n"},
        ).model_dump()
        again = normalize_transaction_verification(saved)
        self.assertEqual(again["handoff"]["holders_after"], ["Anil Shetty"])
        self.assertEqual(again["handoff"]["continuity"], "CONFIRMED")


class TestPropertyTypeReachesTheSavedResult(unittest.TestCase):
    def test_metadata_carries_property_type_and_schedule(self):
        from backend.services.agent_tools import _current_transaction_metadata

        tx = {"tx_id": "PA-TC-0003", "sequence": 3, "transaction_type": "Sale",
              "property_type": "Converted open plot",
              "property_schedule": "Open Plot No.9, CTS 1360B/9, 30 ft x 40 ft",
              "plot_number": "9", "cts_number": "1360B/9"}
        ctx = ToolContext("CASE1", [], chain={"transactions": [tx]}, current_tx_id="PA-TC-0003")
        metadata = _current_transaction_metadata(ctx, "PA-TC-0003")
        self.assertEqual(metadata["property_type"], "Converted open plot")
        self.assertEqual(metadata["property_schedule"], "Open Plot No.9, CTS 1360B/9, 30 ft x 40 ft")
        self.assertEqual(metadata["cts_number"], "1360B/9")
