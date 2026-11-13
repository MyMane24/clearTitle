"""Tests for the lean title verification report service."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from backend.services import final_report as fr


def _tx(status: str = "VERIFIED_WITH_AVAILABLE_EVIDENCE", tx_id: str = "PA-TC-0001",
        sequence: int = 1, required: list | None = None, findings: list | None = None) -> dict:
    return {
        "tx_id": tx_id,
        "sequence": sequence,
        "status": status,
        "report": "## Conclusion\n\nThe inspected deed supports the transfer.",
        "required_documents": required or [],
        "reviewed_document_ids": ["DOC-SD-1996"],
        "cited_documents": [{"doc_id": "DOC-SD-1996", "pages": "1-3"}],
        "findings": findings or [{
            "finding_id": "TF-001",
            "title": "Parcel identity matches",
            "text": "The schedules of both deeds describe Survey No. 45/2B.",
            "severity": "POSITIVE",
            "significance": "ESTABLISHED",
            "is_legal_defect": False,
            "recommended_action": None,
            "evidence_gaps": [],
        }],
        "transaction_metadata": {"transaction_type": "Sale deed"},
    }


def _agent_state(chain_ids: list[str] | None = None, skipped: list[str] | None = None) -> dict:
    chain = [
        {
            "tx_id": tx_id,
            "chain_position": position,
            "documented_transaction": {
                "transaction_type": "Sale deed",
                "executed_date": "08-03-1996",
                "transferors": ["K.U.D.A."],
                "transferees": ["Ningappa Kulkarni"],
                "survey_number": "45/2B",
            },
        }
        for position, tx_id in enumerate(chain_ids or ["PA-TC-0001", "PA-TC-0002"], start=1)
    ]
    return {
        "status": "done",
        "memory": {"skipped_tx_ids": skipped or []},
        "result": {
            "title_chain": chain,
            "property_identity": {
                "details": [
                    {"label": "Property", "value": "Survey No. 45/2B, Honaga Village, Belagavi."},
                ],
            },
        },
    }


NARRATIVE = {
    "verdict": {"level": "CAUTION", "headline": "Do not pay yet: the 1996 conveyance is only recited."},
    "property_type": "Agricultural land",
    "markdown": (
        "## Bottom line\n\nThe recorded transfers connect the current owner to the earliest supported root, "
        "but the 1996 deed itself was not examined.\n\n"
        "## What matters most\n\n- **Missing deed** — The 1996 conveyance is only recited.\n"
        "- **No encumbrance search** — No encumbrance certificate was examined.\n\n"
        "| Deed | Extent |\n| --- | --- |\n| 1996 | 6070 sq m |\n| 2004 | 6070 sq m |\n\n"
        "## Next steps\n\n1. Obtain the 1996 deed.\n2. Obtain an encumbrance certificate."
    ),
}

DOCUMENTS = [
    {"doc_id": "DOC-SD-1996", "filename": "KUDA_SaleDeed_1996.pdf", "document_type": "sale_deed", "status": "structured"},
    {"doc_id": "DOC-SD-2004", "filename": "SaleDeed_2004.pdf", "document_type": "sale_deed", "status": "structured"},
]


class ReportNarrativeModelTest(unittest.TestCase):
    def test_valid_narrative_parses(self):
        narrative = fr.ReportNarrative.model_validate(NARRATIVE)
        self.assertEqual(narrative.verdict.level, "CAUTION")
        self.assertIn("## Next steps", narrative.markdown)

    def test_invalid_level_rejected(self):
        bad = {**NARRATIVE, "verdict": {"level": "MAYBE", "headline": "x"}}
        with self.assertRaises(ValidationError):
            fr.ReportNarrative.model_validate(bad)

    def test_missing_markdown_rejected(self):
        bad = {key: value for key, value in NARRATIVE.items() if key != "markdown"}
        with self.assertRaises(ValidationError):
            fr.ReportNarrative.model_validate(bad)

    def test_markdown_bolding_is_stripped_from_short_values(self):
        self.assertEqual(fr._strip_markdown("**Chain is verified**"), "Chain is verified")


class FactsTest(unittest.TestCase):
    def _facts(self, case_result, state=None):
        state = state or _agent_state()
        readiness = fr._readiness_from(case_result, state)
        return fr._assemble_facts(case_result, state, readiness), readiness

    def test_chain_rows_use_customer_labels_not_internal_ids(self):
        facts, _ = self._facts([_tx(tx_id="PA-TC-0001", sequence=1), _tx(tx_id="PA-TC-0002", sequence=2)])
        self.assertEqual(facts["rows"][0]["label"], "the 1996 sale deed")
        self.assertEqual(facts["rows"][0]["result"], {"level": "CLEAR", "label": "Verified", "state": "verified"})
        self.assertNotIn("PA-TC", json.dumps(facts["rows"]))

    def test_floor_is_clear_only_when_everything_is_verified(self):
        facts, _ = self._facts([_tx(tx_id="PA-TC-0001", sequence=1), _tx(tx_id="PA-TC-0002", sequence=2)])
        self.assertEqual(facts["floor"], "CLEAR")
        self.assertEqual(facts["counts"], {"verified": 2, "issues": 0, "awaiting": 0})

    def test_pending_link_raises_the_floor_and_lists_its_documents_once(self):
        required = [{"document_type": "Sale deed 1985", "reason": "Root title"}]
        facts, _ = self._facts([
            _tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0001", sequence=1, required=required),
            _tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0002", sequence=2, required=required),
        ])
        self.assertEqual(facts["floor"], "CAUTION")
        self.assertEqual(facts["counts"]["awaiting"], 2)
        self.assertEqual([d["document"] for d in facts["documents_needed"]], ["Sale deed 1985"])
        self.assertEqual(facts["documents_needed"][0]["for"], "the 1996 sale deed")

    def test_a_critical_finding_forces_critical(self):
        critical = [{"title": "Forged signature", "text": "x", "severity": "CRITICAL", "is_legal_defect": True,
                     "significance": "ESTABLISHED", "evidence_gaps": []}]
        facts, _ = self._facts([_tx(tx_id="PA-TC-0001", sequence=1, findings=critical),
                                _tx(tx_id="PA-TC-0002", sequence=2)])
        self.assertEqual(facts["floor"], "CRITICAL")

    def test_skipped_link_is_reported_as_skipped(self):
        facts, _ = self._facts(
            [_tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0001", sequence=1), _tx(tx_id="PA-TC-0002", sequence=2)],
            _agent_state(skipped=["PA-TC-0001"]),
        )
        self.assertEqual(facts["rows"][0]["result"]["label"], "Skipped")

    def test_skipped_link_with_open_requests_says_documents_are_needed(self):
        facts, _ = self._facts(
            [_tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0001", sequence=1,
                 required=[{"document_type": "Will 1996", "reason": "Devolution"}]),
             _tx(tx_id="PA-TC-0002", sequence=2)],
            _agent_state(skipped=["PA-TC-0001"]),
        )
        self.assertEqual(facts["rows"][0]["result"]["label"], "Skipped (documents needed)")
        self.assertEqual(facts["counts"], {"verified": 1, "issues": 0, "awaiting": 1})

    def test_counts_cover_transfers_only_but_an_open_endpoint_check_still_raises_the_floor(self):
        state = _agent_state()
        state["result"]["title_chain"].append({"tx_id": "PA-TC-0003", "chain_position": 3, "documented_transaction": {
            "transaction_type": "No ownership transfer supported after latest sale", "transferors": [], "transferees": []}})
        facts, _ = self._facts([_tx(), _tx(tx_id="PA-TC-0002", sequence=2),
                                _tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0003", sequence=3)], state)
        self.assertEqual(facts["counts"], {"verified": 2, "issues": 0, "awaiting": 0})
        self.assertEqual(facts["floor"], "CAUTION")

    def test_property_snapshot_comes_from_the_latest_real_transfer(self):
        state = _agent_state()
        state["result"]["title_chain"][-1]["documented_transaction"].update(
            {"property_type": "Open plot", "property_schedule": "Plot 9, CTS 1360B/9", "transaction_number": "BEL-1"})
        state["result"]["title_chain"].append({"tx_id": "PA-TC-0003", "chain_position": 3, "documented_transaction": {
            "transaction_type": "No ownership transfer supported after latest sale", "transferors": [], "transferees": []}})
        facts, _ = self._facts([_tx(), _tx(tx_id="PA-TC-0002", sequence=2), _tx(tx_id="PA-TC-0003", sequence=3)], state)
        snapshot = fr._property_snapshot(facts, "fallback")
        self.assertEqual(snapshot["type"], "Open plot")
        labels = {row["label"]: row["value"] for row in snapshot["rows"]}
        self.assertEqual(labels["Schedule"], "Plot 9, CTS 1360B/9")
        self.assertEqual(labels["Recorded owner(s)"], "Ningappa Kulkarni")
        self.assertIn("BEL-1", labels["Latest deed"])
        # The endpoint check is not a transfer: it never becomes the recorded owner.
        self.assertTrue(facts["rows"][-1]["endpoint_check"])

    def test_digest_carries_outcomes_without_internal_ids(self):
        facts, readiness = self._facts([_tx(tx_id="PA-TC-0001", sequence=1), _tx(tx_id="PA-TC-0002", sequence=2)])
        digest = fr._digest(facts, [_tx(), _tx(tx_id="PA-TC-0002", sequence=2)], _agent_state(), readiness, "FINAL")
        text = json.dumps(digest)
        self.assertNotIn("PA-TC", text)
        self.assertNotIn("DOC-SD", text)
        self.assertEqual(digest["transactions"][0]["label"], "the 1996 sale deed")
        self.assertEqual(digest["transactions"][0]["findings"][0]["title"], "Parcel identity matches")


class ReadinessTest(unittest.TestCase):
    def _readiness(self, case_result, agent_state):
        with patch.object(fr, "_load_case_results", return_value=case_result), \
                patch.object(fr, "get_agent_state", return_value=agent_state):
            return fr.assess_readiness("CASE1")

    def test_all_terminal_and_no_requests_is_final_ready(self):
        readiness = self._readiness(
            [_tx(tx_id="PA-TC-0001", sequence=1), _tx(tx_id="PA-TC-0002", sequence=2)],
            _agent_state(),
        )
        self.assertTrue(readiness["final_ready"])
        self.assertEqual(readiness["blockers"], [])

    def test_pending_transaction_blocks(self):
        readiness = self._readiness(
            [_tx(tx_id="PA-TC-0001", sequence=1), _tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0002", sequence=2)],
            _agent_state(),
        )
        self.assertFalse(readiness["final_ready"])
        self.assertEqual(readiness["blockers"][0]["tx_id"], "PA-TC-0002")

    def test_outstanding_documents_block_a_terminal_result(self):
        readiness = self._readiness(
            [_tx(tx_id="PA-TC-0001", sequence=1),
             _tx(tx_id="PA-TC-0002", sequence=2, required=[{"document_type": "Encumbrance certificate"}])],
            _agent_state(),
        )
        self.assertFalse(readiness["final_ready"])
        self.assertEqual(readiness["blockers"][0]["required_documents"], ["Encumbrance certificate"])

    def test_chain_link_without_a_result_blocks(self):
        readiness = self._readiness(
            [_tx(tx_id="PA-TC-0001", sequence=1)],
            _agent_state(chain_ids=["PA-TC-0001", "PA-TC-0002"]),
        )
        self.assertFalse(readiness["final_ready"])
        self.assertEqual(readiness["blockers"][0]["tx_id"], "PA-TC-0002")
        self.assertEqual(readiness["blockers"][0]["status"], "PENDING_NOT_VERIFIED")

    def test_skipped_transaction_blocks(self):
        readiness = self._readiness(
            [_tx(tx_id="PA-TC-0001", sequence=1), _tx(tx_id="PA-TC-0002", sequence=2)],
            _agent_state(skipped=["PA-TC-0002"]),
        )
        self.assertFalse(readiness["final_ready"])


class DocumentsExaminedTest(unittest.TestCase):
    def test_reviewed_ids_and_citations_map_to_filenames(self):
        entries = fr._documents_examined(
            [_tx(tx_id="PA-TC-0001", sequence=1)],
            DOCUMENTS,
        )
        self.assertEqual(entries, [{"filename": "KUDA_SaleDeed_1996.pdf", "document_type": "sale deed"}])

    def test_falls_back_to_classified_documents(self):
        entries = fr._documents_examined([], DOCUMENTS)
        self.assertEqual([entry["filename"] for entry in entries], ["KUDA_SaleDeed_1996.pdf", "SaleDeed_2004.pdf"])


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.persisted = []
        self.state = _agent_state()
        self.case_result = [_tx(tx_id="PA-TC-0001", sequence=1), _tx(tx_id="PA-TC-0002", sequence=2)]
        patches = [
            patch.object(fr, "_load_case_results", return_value=self.case_result),
            patch.object(fr, "get_agent_state", return_value=self.state),
            patch.object(fr, "get_case_documents", return_value=DOCUMENTS),
            patch.object(fr, "complete_json", return_value=NARRATIVE),
            patch.object(fr, "_persist_final_report", side_effect=lambda case_id, doc: self.persisted.append(doc)),
            patch.object(fr, "get_case_dir", return_value=Path(self.tmp.name)),
            patch.object(fr, "RedisLock", self._fake_lock()),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def _fake_lock():
        class _Lock:
            def __init__(self, *_args, **_kwargs):
                pass

            def acquire(self):
                return True

            def release(self):
                return None

        return _Lock

    def test_final_generation_persists_document_and_pdf(self):
        result = fr.generate_final_report("CASE1", "FINAL")
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["report_type"], "FINAL")
        document = self.persisted[-1]
        self.assertEqual(document["schema_version"], "3.0")
        self.assertEqual(document["verdict"], {"level": "CAUTION", "headline": NARRATIVE["verdict"]["headline"]})
        self.assertEqual(document["property"]["type"], "Agricultural land")
        self.assertEqual(len(document["chain"]), 2)
        self.assertEqual(document["narrative_markdown"], NARRATIVE["markdown"])
        self.assertEqual(document["counts"], {"verified": 2, "issues": 0, "awaiting": 0})
        self.assertEqual(document["documents_examined"][0]["filename"], "KUDA_SaleDeed_1996.pdf")
        self.assertTrue(document["source_case_result_hash"])
        self.assertNotIn("findings", document)
        pdf = Path(self.tmp.name, "final_report", fr.REPORT_FILENAME).read_bytes()
        self.assertTrue(pdf.startswith(b"%PDF"), "rendered PDF must start with the %PDF magic")

    def test_preliminary_generation_discloses_pending(self):
        self.case_result.append(_tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0003", sequence=3,
                                    required=[{"document_type": "Will 1996", "reason": "Devolution"}]))
        self.state["result"]["title_chain"].append(
            {"tx_id": "PA-TC-0003", "chain_position": 3, "documented_transaction": {"transaction_type": "Sale deed"}})
        result = fr.generate_final_report("CASE1", "PRELIMINARY")
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["report_type"], "PRELIMINARY")
        self.assertEqual(self.persisted[-1]["documents_needed"][0]["document"], "Will 1996")

    def test_verdict_is_never_lower_than_the_data_supports(self):
        optimistic = {**NARRATIVE, "verdict": {"level": "CLEAR", "headline": "All good."}}
        self.case_result.append(_tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0003", sequence=3))
        self.state["result"]["title_chain"].append(
            {"tx_id": "PA-TC-0003", "chain_position": 3, "documented_transaction": {"transaction_type": "Sale deed"}})
        with patch.object(fr, "complete_json", return_value=optimistic):
            fr.generate_final_report("CASE1", "PRELIMINARY")
        self.assertEqual(self.persisted[-1]["verdict"]["level"], "CAUTION")

    def test_final_blocked_when_a_transaction_is_pending(self):
        self.case_result.append(_tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0003", sequence=3))
        self.state["result"]["title_chain"].append(
            {"tx_id": "PA-TC-0003", "chain_position": 3, "documented_transaction": {"transaction_type": "Sale deed"}})
        result = fr.generate_final_report("CASE1", "FINAL")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual([blocker["tx_id"] for blocker in result["blockers"]], ["PA-TC-0003"])

    def test_unusable_llm_output_raises_after_one_retry(self):
        with patch.object(fr, "complete_json", return_value={"nonsense": True}) as model:
            with self.assertRaises(fr.ReportSynthesisError):
                fr.generate_final_report("CASE1", "FINAL")
        self.assertEqual(model.call_count, 2)

    def test_internal_identifiers_trigger_one_rewrite(self):
        leaky = {**NARRATIVE, "markdown": NARRATIVE["markdown"] + "\n\nSee PA-TC-0002 and DOC_019."}
        with patch.object(fr, "complete_json", side_effect=[leaky, NARRATIVE]) as model:
            fr.generate_final_report("CASE1", "FINAL")
        self.assertEqual(model.call_count, 2)
        self.assertIn("internal identifiers", model.call_args_list[1].args[0])
        self.assertNotIn("PA-TC", self.persisted[-1]["narrative_markdown"])

    def test_identifiers_that_survive_the_rewrite_are_scrubbed(self):
        leaky = {**NARRATIVE, "markdown": NARRATIVE["markdown"] + "\n\nSee PA-TC-0002 (PENDING_NOT_VERIFIED).",
                 "verdict": {"level": "CAUTION", "headline": "Check REQ-0004 first."}}
        with patch.object(fr, "complete_json", return_value=leaky):
            fr.generate_final_report("CASE1", "FINAL")
        stored = self.persisted[-1]
        self.assertNotRegex(stored["narrative_markdown"] + stored["verdict"]["headline"],
                            r"PA-TC|PENDING_NOT_VERIFIED|REQ-")

    def test_unsupported_report_type_rejected(self):
        with self.assertRaises(ValueError):
            fr.generate_final_report("CASE1", "DRAFT")


class PdfRenderTest(unittest.TestCase):
    DOCUMENT = {
        "schema_version": "3.0",
        "report_type": "PRELIMINARY",
        "generated_at": "2026-11-12T10:00:00+00:00",
        "verdict": {"level": "CAUTION", "headline": "Do not pay yet: the chain before 2019 is unverified."},
        "property": {"type": "Open plot", "rows": [{"label": "Property type", "value": "Open plot"},
                                                   {"label": "Schedule", "value": "Plot 9, CTS 1360B/9"}]},
        "chain": [{"sequence": 1, "label": "the 2007 sale", "transaction_type": "Sale", "date": "06 December 2007",
                   "registration": "BEL-1", "from": ["A"], "to": ["B", "C"], "property_type": "Agricultural land",
                   "result": {"level": "CAUTION", "label": "Awaiting documents"}}],
        "narrative_markdown": NARRATIVE["markdown"] + "\n\n> A short <quoted> clause & more.\n\nSome *italic* and `code`.",
        "documents_needed": [{"document": "Sale deed 1985", "reason": "Root title", "for": "the 2007 sale"}],
        "documents_examined": [{"filename": "KUDA_SaleDeed_1996.pdf", "document_type": "sale deed"}],
    }

    def test_render_smoke(self):
        pdf = fr.render_final_report_pdf(self.DOCUMENT)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 5000)

    def test_property_column_is_dropped_when_no_link_has_a_type(self):
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        document = {**self.DOCUMENT, "chain": [{**self.DOCUMENT["chain"][0], "property_type": None}]}
        with fitz.open(stream=fr.render_final_report_pdf(document), filetype="pdf") as pdf:
            text = " ".join(" ".join(page.get_text().split()) for page in pdf)
        self.assertNotIn("Property Result", text)
        self.assertIn("Transfer Result", text)

    def test_a_long_chain_table_does_not_force_a_blank_page(self):
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        row = self.DOCUMENT["chain"][0]
        document = {**self.DOCUMENT, "chain": [{**row, "sequence": n} for n in range(1, 15)]}
        with fitz.open(stream=fr.render_final_report_pdf(document), filetype="pdf") as pdf:
            first_page = " ".join(pdf[0].get_text().split())
        self.assertIn("TITLE CHAIN AT A GLANCE", first_page)  # starts on page 1, not pushed to page 2

    def test_render_tolerates_a_minimal_document(self):
        pdf = fr.render_final_report_pdf({"report_type": "FINAL", "verdict": {"level": "CLEAR", "headline": "ok"},
                                          "narrative_markdown": "Only a paragraph of narrative text here."})
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_pdf_text_contains_the_report(self):
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        with fitz.open(stream=fr.render_final_report_pdf(self.DOCUMENT), filetype="pdf") as pdf:
            text = " ".join(" ".join(page.get_text().split()) for page in pdf)
        for expected in ("Do not pay yet", "TITLE CHAIN AT A GLANCE", "Awaiting documents", "Next steps",
                         "Sale deed 1985", "6070 sq m", "KUDA_SaleDeed_1996.pdf", "A short <quoted> clause & more."):
            self.assertIn(expected, text)


class ReportStateTest(unittest.TestCase):
    def test_no_results_raises(self):
        with patch.object(fr, "_load_case_results", return_value=[]), \
                patch.object(fr, "get_agent_state", return_value={}):
            with self.assertRaises(fr.NoCaseResult):
                fr.get_report_state("CASE1")

    def test_state_reports_readiness_and_stored_report(self):
        stored = {"report_type": "FINAL", "generated_at": "2026-11-12T10:00:00+00:00",
                  "source_case_result_hash": "stale-hash"}
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.fetchone.return_value = (json.dumps(stored),)
        with patch.object(fr, "_load_case_results", return_value=[_tx(), _tx(tx_id="PA-TC-0002", sequence=2)]), \
                patch.object(fr, "get_agent_state", return_value=_agent_state()), \
                patch.object(fr, "_get_conn", return_value=conn), \
                patch.object(fr, "get_case_dir", return_value=Path(tempfile.gettempdir())), \
                patch.object(fr, "RedisLock", GenerateTest._fake_lock()):
            state = fr.get_report_state("CASE1")
        self.assertTrue(state["final_ready"])
        self.assertEqual(state["blockers"], [])
        self.assertTrue(state["report"]["stale"], "a different source hash must mark the stored report stale")

    def test_persist_round_trip_through_fake_conn(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        with patch.object(fr, "_get_conn", return_value=conn):
            fr._persist_final_report("CASE1", {"report_type": "FINAL"})
        sql, args = conn.cursor.return_value.execute.call_args[0]
        self.assertIn("ON DUPLICATE KEY UPDATE final_report", sql)
        self.assertEqual(args[0], "CASE1")
        self.assertEqual(json.loads(args[1])["report_type"], "FINAL")


if __name__ == "__main__":
    unittest.main()
