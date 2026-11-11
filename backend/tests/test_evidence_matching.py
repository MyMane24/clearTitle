"""Stage 4: evidence-requirement lifecycle + deterministic matching."""

import unittest
from unittest.mock import patch

from backend.database.repositories import agent_repo
from backend.services import agent_tools
from backend.services.cleartitle_agent import _build_upstream_context
from backend.services.evidence_match import match_requirements, refresh_requirement_matches


class FakeCursor:
    """House fake (test_stage1_migration style) with scripted fetch queues."""

    def __init__(self, initial=None, fetch_results=None, fetch_rows=None):
        self.initial = initial
        self.calls = []
        self.executemany_calls = []
        self._fetch_results = list(fetch_results or [])
        self._fetch_rows = list(fetch_rows or [])

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, rows))
        self.calls.append((sql, rows))

    def fetchone(self):
        return self._fetch_results.pop(0) if self._fetch_results else None

    def fetchall(self):
        rows, self._fetch_rows = self._fetch_rows, []
        return rows


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self, **_kwargs):
        return self._cursor

    def commit(self):
        self.committed = True


DOC = {"doc_id": "D3", "filename": "sale deed 4966.pdf", "document_type": "Sale deed"}


class TestMatcherDecisions(unittest.TestCase):
    def test_exact_classification_match(self):
        requirement = {"requirement_id": "REQ-0001", "document_type": "sale deed"}
        decisions = match_requirements([requirement], [DOC])
        self.assertEqual(decisions[0]["status"], "MATCHED")
        self.assertEqual(decisions[0]["doc_id"], "D3")

    def test_identifier_in_filename_is_strong(self):
        requirement = {
            "requirement_id": "REQ-0002",
            "document_type": "Survey map R.S. 699-A/14 to 699A/15",
            "reason": "Confirm subdivision of the parent parcel",
        }
        documents = [
            {"doc_id": "D9", "filename": "RS 699-A-14 699A-15 survey.pdf", "document_type": ""},
        ]
        decisions = match_requirements([requirement], documents)
        self.assertEqual(decisions[0]["status"], "MATCHED")
        self.assertEqual(decisions[0]["doc_id"], "D9")

    def test_weak_unique_overlap_is_partially_matched(self):
        requirement = {"requirement_id": "REQ-0003", "document_type": "Society NOC"}
        documents = [{
            "doc_id": "D5", "filename": "NOC letter welfare society.pdf",
            "document_type": "Letter",
        }]
        decisions = match_requirements([requirement], documents)
        self.assertEqual(decisions[0]["status"], "PARTIALLY_MATCHED")
        self.assertEqual(decisions[0]["doc_id"], "D5")

    def test_multiple_strong_candidates_are_ambiguous(self):
        requirement = {"requirement_id": "REQ-0004", "document_type": "Approval 1329"}
        documents = [
            {"doc_id": "D6", "filename": "approval 1329 of 2009-10.pdf", "document_type": "X"},
            {"doc_id": "D7", "filename": "approval-1329 true copy.pdf", "document_type": "Y"},
        ]
        decisions = match_requirements([requirement], documents)
        self.assertEqual(decisions[0]["status"], "AMBIGUOUS")
        self.assertIsNone(decisions[0]["doc_id"])

    def test_weak_ties_are_ambiguous(self):
        requirement = {"requirement_id": "REQ-0005", "document_type": "Property extract"}
        documents = [
            {"doc_id": "D1", "filename": "property extract page 1.pdf", "document_type": "A"},
            {"doc_id": "D2", "filename": "property extract page 2.pdf", "document_type": "B"},
        ]
        decisions = match_requirements([requirement], documents)
        self.assertEqual(decisions[0]["status"], "AMBIGUOUS")

    def test_no_overlap_is_not_matched(self):
        requirement = {"requirement_id": "REQ-0006", "document_type": "Mortgage release"}
        decisions = match_requirements([requirement], [DOC])
        self.assertEqual(decisions[0]["status"], "NOT_MATCHED")
        self.assertIsNone(decisions[0]["doc_id"])

    def test_requirement_without_id_is_refused(self):
        with self.assertRaises(ValueError):
            match_requirements([{"document_type": "Sale deed"}], [DOC])


def _result(tx_id, sequence, status, required, checkpoint=None):
    result = {
        "tx_id": tx_id, "sequence": sequence, "status": status,
        "report": "Report", "cited_documents": [], "schema_version": "3.0",
    }
    if required is not None:
        result["required_documents"] = required
    result["transaction_metadata"] = (
        {"_verification_checkpoint": checkpoint} if checkpoint else {}
    )
    return result


ASK_A = {"document_type": "Original conveyance to first vendor"}
ASK_B = {"document_type": "Index II extract for 1985-1990"}
ASK_C = {"document_type": "Property card / 7/12 extract"}


def _row(requirement_id, tx_id, ask):
    return (requirement_id, tx_id, ask["document_type"], None, "OPEN")


class TestLifecycleSync(unittest.TestCase):
    """sync_case_requirements evolves idempotently; identity is content-based."""

    def _sync(self, cursor, results, documents=None):
        with patch.object(agent_repo, "list_transaction_results", return_value=results), \
                patch.object(agent_repo, "get_agent_documents", return_value=documents or []), \
                patch.object(agent_repo, "_get_conn", return_value=FakeConnection(cursor)):
            return agent_repo.sync_case_requirements("CASE1")

    def _call_updates(self, cursor):
        return [
            list(rows) or []
            for sql, rows in cursor.executemany_calls
            if "UPDATE evidence_requirements SET status" in sql and "status = 'OPEN'" in sql
        ]

    def test_new_ask_gets_next_unused_number_not_a_vacated_position(self):
        cursor = FakeCursor(fetch_rows=[_row("REQ-0001", "PA-TC-0001", ASK_A)])
        results = [
            _result("PA-TC-0001", 1, "PENDING_NOT_VERIFIED", [ASK_A, ASK_B]),
        ]
        inserted = self._sync(cursor, results)
        self.assertEqual(inserted, 1)
        inserts = [rows for sql, rows in cursor.executemany_calls
                   if "INSERT IGNORE" in sql][0]
        # B is the second ask positionally, but REQ-0001 is occupied: it must
        # take REQ-0002, never collide onto an existing id with other content.
        self.assertEqual(inserts, [("CASE1", "REQ-0002", "PA-TC-0001",
                                    ASK_B["document_type"], None)])

    def test_disappeared_ask_renumbers_without_losing_later_asks(self):
        # Live-hazard regression: previously a vanished mid-sequence ask let a
        # later ask renumber onto an existing id and INSERT IGNORE silently
        # dropped it from the ledger.
        cursor = FakeCursor(fetch_rows=[
            _row("REQ-0001", "PA-TC-0001", ASK_A),
            _row("REQ-0002", "PA-TC-0002", ASK_B),
            _row("REQ-0003", "PA-TC-0002", ASK_C),
        ])
        results = [
            _result("PA-TC-0001", 1, "PENDING_NOT_VERIFIED", [ASK_A]),
            _result("PA-TC-0002", 2, "PENDING_NOT_VERIFIED", [ASK_C]),
        ]
        inserted = self._sync(cursor, results)
        self.assertEqual(inserted, 0)
        inserts = [rows for sql, rows in cursor.executemany_calls if "INSERT IGNORE" in sql]
        self.assertEqual(inserts, [])  # C reused its stable REQ-0003
        updates = self._call_updates(cursor)
        self.assertEqual(updates, [[("WITHDRAWN", "CASE1", "REQ-0002")]])

    def test_terminal_owner_satisfies_its_open_requirements(self):
        cursor = FakeCursor(fetch_rows=[
            _row("REQ-0001", "PA-TC-0001", ASK_A),
            _row("REQ-0002", "PA-TC-0002", ASK_B),
        ])
        results = [
            _result("PA-TC-0001", 1, "VERIFIED_WITH_AVAILABLE_EVIDENCE", [ASK_A]),
            _result("PA-TC-0002", 2, "PENDING_NOT_VERIFIED", [ASK_B]),
        ]
        self._sync(cursor, results)
        updates = self._call_updates(cursor)
        self.assertEqual(updates, [[("SATISFIED", "CASE1", "REQ-0001")]])

    def test_checkpointed_result_does_not_satisfy(self):
        cursor = FakeCursor(fetch_rows=[_row("REQ-0001", "PA-TC-0001", ASK_A)])
        results = [
            _result("PA-TC-0001", 1, "VERIFIED_WITH_AVAILABLE_EVIDENCE", [ASK_A],
                    checkpoint="bounded_stop"),
        ]
        self._sync(cursor, results)
        self.assertEqual(self._call_updates(cursor), [])

    def test_withdrawn_ask_returning_verbatim_reopens(self):
        cursor = FakeCursor(fetch_rows=[
            ("REQ-0001", "PA-TC-0001", ASK_A["document_type"], None, "WITHDRAWN"),
        ])
        results = [
            _result("PA-TC-0001", 1, "PENDING_NOT_VERIFIED", [ASK_A]),
        ]
        inserted = self._sync(cursor, results)
        self.assertEqual(inserted, 0)
        reopens = [list(rows) for sql, rows in cursor.executemany_calls
                   if "status = 'WITHDRAWN'" in sql and "SET status = 'OPEN'" in sql]
        self.assertEqual(reopens, [[("CASE1", "REQ-0001")]])

    def test_replay_changes_nothing(self):
        existing = [
            _row("REQ-0001", "PA-TC-0001", ASK_A),
            _row("REQ-0002", "PA-TC-0002", ASK_B),
        ]
        cursor = FakeCursor(fetch_rows=existing)
        results = [
            _result("PA-TC-0001", 1, "PENDING_NOT_VERIFIED", [ASK_A]),
            _result("PA-TC-0002", 2, "PENDING_NOT_VERIFIED", [ASK_B]),
        ]
        self.assertEqual(self._sync(cursor, results), 0)
        self.assertEqual(cursor.executemany_calls, [])


class TestApplyMatches(unittest.TestCase):
    def test_writes_target_open_rows_only(self):
        cursor = FakeCursor()
        with patch.object(agent_repo, "_get_conn", return_value=FakeConnection(cursor)):
            written = agent_repo.apply_requirement_matches("CASE1", [
                {"requirement_id": "REQ-0001", "status": "MATCHED", "doc_id": "D3"},
                {"requirement_id": "REQ-0002", "status": "AMBIGUOUS", "doc_id": None},
            ])
        self.assertEqual(written, 2)
        sql, rows = cursor.executemany_calls[0]
        self.assertIn("match_status", sql)
        self.assertIn("status = 'OPEN'", sql)
        self.assertEqual(rows, [
            ("MATCHED", "D3", "CASE1", "REQ-0001"),
            ("AMBIGUOUS", None, "CASE1", "REQ-0002"),
        ])

    def test_empty_matches_write_nothing(self):
        with patch.object(agent_repo, "_get_conn") as conn:
            self.assertEqual(agent_repo.apply_requirement_matches("CASE1", []), 0)
        conn.assert_not_called()


class TestRefreshMatches(unittest.TestCase):
    def _rows(self, *rows):
        base = {"case_id": "CASE1", "reason": None, "what_it_establishes": None,
                "status": "OPEN", "match_status": None, "matched_doc_id": None,
                "created_at": "t", "updated_at": "t"}
        return [{**base, **row} for row in rows]

    def test_changed_decisions_only(self):
        rows = self._rows(
            {"requirement_id": "REQ-0001", "owner_tx_id": "PA-TC-0001",
             "document_type": "Sale deed"},
        )
        docs = [DOC, {"doc_id": "D8", "filename": "EC.pdf", "document_type": "EC"}]
        with patch.object(agent_repo, "list_requirements", return_value=rows), \
                patch.object(agent_repo, "get_agent_documents", return_value=docs, ), \
                patch.object(agent_repo, "apply_requirement_matches") as apply_matches:
            changed = refresh_requirement_matches("CASE1")
        self.assertEqual(changed, [{
            "requirement_id": "REQ-0001", "document_type": "Sale deed",
            "status": "MATCHED", "doc_id": "D3",
        }])
        apply_matches.assert_called_once_with("CASE1", [
            {"requirement_id": "REQ-0001", "document_type": "Sale deed",
             "status": "MATCHED", "doc_id": "D3"},
        ])

    def test_identical_state_changes_nothing(self):
        rows = self._rows(
            {"requirement_id": "REQ-0001", "owner_tx_id": "PA-TC-0001",
             "document_type": "Sale deed", "match_status": "MATCHED",
             "matched_doc_id": "D3"},
        )
        with patch.object(agent_repo, "list_requirements", return_value=rows), \
                patch.object(agent_repo, "get_agent_documents", return_value=[DOC]), \
                patch.object(agent_repo, "apply_requirement_matches") as apply_matches:
            changed = refresh_requirement_matches("CASE1")
        self.assertEqual(changed, [])
        self.assertEqual(apply_matches.call_count, 1)

    def test_phase_a_only_documents_are_not_candidates(self):
        rows = self._rows(
            {"requirement_id": "REQ-0001", "owner_tx_id": "PA-TC-0001",
             "document_type": "EC"},
        )
        with patch.object(agent_repo, "list_requirements", return_value=rows), \
                patch.object(agent_repo, "get_agent_documents", return_value=[DOC]), \
                patch.object(agent_repo, "apply_requirement_matches"):
            changed = refresh_requirement_matches("CASE1")
        self.assertEqual(changed, [{
            "requirement_id": "REQ-0001", "document_type": "EC",
            "status": "NOT_MATCHED", "doc_id": None,
        }])


class TestRequirementIdEnrichment(unittest.TestCase):
    PHASE_A = {
        "title_chain": [
            {"tx_id": "PA-TC-0001", "chain_position": 1,
             "documented_transaction": {"transaction_type": "Sale"}},
            {"tx_id": "PA-TC-0002", "chain_position": 2,
             "documented_transaction": {"transaction_type": "Gift"}},
        ],
    }

    def _pending(self):
        return _result("PA-TC-0001", 1, "PENDING_NOT_VERIFIED", [ASK_B])

    def test_upstream_outstanding_entries_carry_the_ledger_id(self):
        index_key = agent_repo.requirement_content_key(
            "PA-TC-0001", ASK_B["document_type"], None
        )
        context = None
        with patch.object(agent_repo, "get_transaction_result", return_value=self._pending()), \
                patch.object(agent_repo, "requirement_ids_index",
                             return_value={index_key: "REQ-0007"}):
            context = _build_upstream_context("CA1", self.PHASE_A, 2)
        outstanding = [entry for entry in context
                       if entry.get("outstanding_required_documents")][0]
        self.assertEqual(outstanding["outstanding_required_documents"][0]["requirement_id"],
                         "REQ-0007")

    def test_request_register_lines_name_the_requirement(self):
        from backend.services.cleartitle_agent import _already_requested_block

        block = _already_requested_block([{
            "tx_id": "PA-TC-0001",
            "outstanding_required_documents": [
                {"document_type": ASK_B["document_type"], "reason": None,
                 "requirement_id": "REQ-0007"},
            ],
        }])
        self.assertIn("[REQ-0007]", block)

    def test_empty_ledger_degrades_to_no_tag(self):
        with patch.object(agent_repo, "get_transaction_result", return_value=self._pending()), \
                patch.object(agent_repo, "requirement_ids_index", return_value={}):
            context = _build_upstream_context("CA1", self.PHASE_A, 2)
        outstanding = [entry for entry in context
                       if entry.get("outstanding_required_documents")][0]
        self.assertNotIn("requirement_id",
                         outstanding["outstanding_required_documents"][0])

    def test_chain_context_record_also_carries_the_id(self):
        index_key = agent_repo.requirement_content_key(
            "PA-TC-0001", ASK_B["document_type"], None
        )
        with patch.object(agent_tools.repo, "get_transaction_result",
                          return_value=self._pending()), \
                patch.object(agent_tools.repo, "requirement_ids_index",
                             return_value={index_key: "REQ-0007"}):
            record = agent_tools._upstream_chain_context("CA1", self.PHASE_A["title_chain"], 2)
        self.assertEqual(
            record["upstream_unverified"][0]["missing"][0]["requirement_id"], "REQ-0007"
        )


if __name__ == "__main__":
    unittest.main()
