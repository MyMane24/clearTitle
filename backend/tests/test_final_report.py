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
    "schedule": [
        {"label": "Survey number(s)", "value": "45/2B"},
        {"label": "Extent / area", "value": "6070 square metres"},
        {"label": "Village / town and taluk", "value": "Honaga Village, Belagavi Taluk"},
        {"label": "Classification / current land use", "value": "Converted residential"},
    ],
    "findings": [
        {"severity": "CRITICAL", "title": "Original deed missing", "detail": "The 1996 conveyance is only recited."},
        {"severity": "CAUTION", "title": "No encumbrance evidence", "detail": "No encumbrance certificate was examined."},
        {"severity": "CLEAR", "title": "Parcel identity matches", "detail": "All deeds describe the same parcel."},
        {"severity": "CLEAR", "title": "Registration confirmed", "detail": "Registration particulars are recorded."},
    ],
    "cannot_verify": ["possession was not inspected", "no encumbrance search"],
    "opinion": {
        "verdict_line": "Chain is verified; one item needs your attention",
        "summary": "The recorded transfers connect the current owner to the earliest supported root.",
        "conditions": ["Obtain an encumbrance certificate before you commit."],
    },
}

DOCUMENTS = [
    {"doc_id": "DOC-SD-1996", "filename": "KUDA_SaleDeed_1996.pdf", "document_type": "sale_deed", "status": "structured"},
    {"doc_id": "DOC-SD-2004", "filename": "SaleDeed_2004.pdf", "document_type": "sale_deed", "status": "structured"},
]


class ReportNarrativeModelTest(unittest.TestCase):
    def test_valid_narrative_parses(self):
        narrative = fr.ReportNarrative.model_validate(NARRATIVE)
        self.assertEqual(narrative.findings[0].severity, "CRITICAL")
        self.assertEqual(len(narrative.schedule), 4)
        self.assertEqual(narrative.opinion.verdict_line, NARRATIVE["opinion"]["verdict_line"])

    def test_invalid_severity_rejected(self):
        bad = {**NARRATIVE, "findings": [{"severity": "MAYBE", "title": "x", "detail": "y"}]}
        with self.assertRaises(ValidationError):
            fr.ReportNarrative.model_validate(bad)

    def test_missing_opinion_rejected(self):
        bad = {key: value for key, value in NARRATIVE.items() if key != "opinion"}
        with self.assertRaises(ValidationError):
            fr.ReportNarrative.model_validate(bad)

    def test_markdown_bolding_is_stripped_before_validation(self):
        bolded = {
            **NARRATIVE,
            "opinion": {**NARRATIVE["opinion"], "verdict_line": "**Chain is verified**"},
        }
        cleaned = fr._strip_markdown(bolded)
        self.assertEqual(cleaned["opinion"]["verdict_line"], "Chain is verified")


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
        self.assertEqual(document["report_type"], "FINAL")
        self.assertEqual(document["counts"], {"critical": 1, "caution": 1, "clear": 2})
        self.assertEqual(len(document["schedule"]), 4)
        self.assertEqual(document["documents_examined"][0]["filename"], "KUDA_SaleDeed_1996.pdf")
        self.assertTrue(document["source_case_result_hash"])
        pdf = Path(self.tmp.name, "final_report", fr.REPORT_FILENAME).read_bytes()
        self.assertTrue(pdf.startswith(b"%PDF"), "rendered PDF must start with the %PDF magic")

    def test_preliminary_generation_discloses_pending(self):
        self.case_result.append(_tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0003", sequence=3))
        self.state["result"]["title_chain"].append(
            {"tx_id": "PA-TC-0003", "chain_position": 3, "documented_transaction": {"transaction_type": "Sale deed"}})
        result = fr.generate_final_report("CASE1", "PRELIMINARY")
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["report_type"], "PRELIMINARY")

    def test_final_blocked_when_a_transaction_is_pending(self):
        self.case_result.append(_tx(status="PENDING_NOT_VERIFIED", tx_id="PA-TC-0003", sequence=3))
        self.state["result"]["title_chain"].append(
            {"tx_id": "PA-TC-0003", "chain_position": 3, "documented_transaction": {"transaction_type": "Sale deed"}})
        result = fr.generate_final_report("CASE1", "FINAL")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual([blocker["tx_id"] for blocker in result["blockers"]], ["PA-TC-0003"])

    def test_unusable_llm_output_raises(self):
        with patch.object(fr, "complete_json", return_value={"nonsense": True}):
            with self.assertRaises(fr.ReportSynthesisError):
                fr.generate_final_report("CASE1", "FINAL")

    def test_unsupported_report_type_rejected(self):
        with self.assertRaises(ValueError):
            fr.generate_final_report("CASE1", "DRAFT")

    def test_placeholder_schedule_rows_are_dropped(self):
        with_placeholder = {
            **NARRATIVE,
            "schedule": NARRATIVE["schedule"] + [
                {"label": "Village / town and taluk", "value": "village and taluk are Not stated in the verified documents"},
            ],
        }
        with patch.object(fr, "complete_json", return_value=with_placeholder):
            fr.generate_final_report("CASE1", "FINAL")
        schedule = self.persisted[-1]["schedule"]
        self.assertEqual([row["label"] for row in schedule], [row["label"] for row in NARRATIVE["schedule"]])


class PdfRenderTest(unittest.TestCase):
    def test_render_smoke(self):
        document = {
            "report_type": "FINAL",
            "generated_at": "2026-11-12T10:00:00+00:00",
            "property_line": "Survey No. 45/2B, Honaga Village, Belagavi.",
            "schedule": NARRATIVE["schedule"],
            "documents_examined": [{"filename": "KUDA_SaleDeed_1996.pdf", "document_type": "sale deed"}],
            "findings": NARRATIVE["findings"],
            "counts": {"critical": 1, "caution": 1, "clear": 2},
            "cannot_verify": NARRATIVE["cannot_verify"],
            "opinion": NARRATIVE["opinion"],
        }
        pdf = fr.render_final_report_pdf(document)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 5000)


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
