"""C6 — failure-path persistence tests against the REAL database (§8.4 hardening).

Covers matrix rows 18/20 and §9(b)'s unreadable-prior/overwrite semantics at
the real MySQL layer (dev DB per the seed script: MYSQL_PORT 3307). Everything
runs through the real pooled ``agent_repo`` containers: prior containers are
genuinely persisted server state; every persistence assertion is verified by a
real read-back, never by the mock.

Outage simulation is surgical and documented: a cursor wrapper raises for one
named SQL statement only (the dossier strict read for matrix 18; the container
upsert for matrix 20). All other statements — reads, writes, commits — hit the
real server, so the "prior container is intact" guarantees are proven against
actual rows.

The suite self-cleans: every fixture row belongs to a unique ``C6DB…`` case id
and is deleted in teardown. It never mutates schema, never touches other
cases, never calls the LLM.

A strict JSON column cannot legally hold corrupt bytes, so matrix 19's
engine-side corrupt-JSON branch stays where C1 pinned it (unit suite); this
real-DB file exercises the reader boundary the column can actually reach: a
container value whose parse is honest but non-dict (§9(b)) and a JSON-encoded
``null`` prior.
"""

# Dev DB port per backend/scripts/seed_demo_clear_title.py. Probe 3307 FIRST
# with a direct read-only connection, WITHOUT touching global state: when the
# dev server is down this file skips cleanly and the rest of the suite keeps
# the machine's own configuration. The pin (os.environ + cached backend.config/
# backend.database.connection attributes — config freezes at first import, a
# machine-wide MYSQL_PORT=3306 would otherwise win) happens only once 3307 is
# proven alive, because every module imported later in the suite inherits it.
import os
import unittest
import uuid
from contextlib import contextmanager
from unittest import mock

# Freeze machine config BEFORE any pinning; never mutate it on the skip path.
import backend.config as _config
import backend.database.connection as _connection


def _probe_3307() -> bool:
    """True when the dev DB on 3307 is reachable AND the Phase C tables exist."""
    try:
        from mysql.connector import connect

        conn = connect(
            host=_config.MYSQL_HOST, port=3307,
            user=_config.MYSQL_USER, password=_config.MYSQL_PASSWORD,
            database=_config.MYSQL_DATABASE, connection_timeout=3,
        )
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() "
                "AND table_name IN ('case_results', 'evidence_requirements')")
            return cursor.fetchone()[0] == 2
        finally:
            conn.close()
    except Exception:
        return False


DB_AVAILABLE = _probe_3307()

if DB_AVAILABLE:
    os.environ["MYSQL_PORT"] = "3307"
    _config.MYSQL_PORT = 3307
    _connection.MYSQL_PORT = 3307

requires_db = unittest.skipUnless(
    DB_AVAILABLE, "dev MySQL DB (3307) is not reachable")

from backend.database.connection import _get_conn
from backend.database.repositories import agent_repo
from backend.services import consolidation
from backend.services.consolidation import consolidate_findings


# -- surgical outage wrappers -------------------------------------------------------

class _BlastingCursor:
    """Real cursor that raises for one named SQL statement, passes the rest."""

    def __init__(self, real, blast_sql: str):
        self._real = real
        self._blast = blast_sql

    def execute(self, sql, params=None):
        if self._blast in sql:
            raise RuntimeError(f"simulated outage at: {self._blast[:60]}")
        return self._real.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _BlastingConn:
    """Context manager around the REAL pooled connection with a blasting cursor."""

    def __init__(self, real_factory, blast_sql: str):
        self._real_factory = real_factory
        self._blast = blast_sql

    def __enter__(self):
        self._raw = self._real_factory().__enter__()
        return self

    def __exit__(self, *args):
        # the real ManagedConnection.__exit__ closes the pooled connection
        return type(self._raw).__exit__(self._raw, *args)

    def cursor(self, **kwargs):
        return _BlastingCursor(self._raw.cursor(**kwargs), self._blast)

    def commit(self):
        self._raw.commit()


READ_BLAST = "SELECT case_result FROM"    # the strict dossier read (matrix 18)
WRITE_BLAST = "INSERT INTO case_results"  # the container upsert (matrix 20)


@contextmanager
def _with_blast(blast_sql: str):
    real = agent_repo._get_conn
    with mock.patch.object(
            agent_repo, "_get_conn",
            lambda: _BlastingConn(real, blast_sql)):
        yield


@contextmanager
def _no_llm():
    with mock.patch.object(
            consolidation, "complete_json",
            side_effect=AssertionError("no LLM call in real-DB tests")):
        yield


# -- fixture helpers -----------------------------------------------------------------

def _insert_requirement(case_id: str, requirement_id: str = "REQ-C6DB-1"):
    """Raw ledger insert (the I5 mutation): real row, isolated by a unique case id."""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO evidence_requirements "
            "(case_id, requirement_id, owner_tx_id, document_type, reason, status) "
            "VALUES (%s, %s, NULL, 'Encumbrance certificate for subsisting charge', "
            "'C6DB fixture', 'OPEN')",
            (case_id, requirement_id),
        )
        conn.commit()


def _set_raw_prior(case_id: str, raw_sql_value: str):
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO case_results (case_id, property_findings) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE property_findings = VALUES(property_findings)",
            (case_id, raw_sql_value),
        )
        conn.commit()


class ConsolidationRealDBTest(unittest.TestCase):
    def setUp(self):
        self.case_id = ("C6DB" + uuid.uuid4().hex[:8].upper())[:32]
        self.addCleanup(self._cleanup_case, self.case_id)

    def _cleanup_case(self, case_id):
        """Delete ONLY this fixture's rows; never touch other data or schema."""
        with _get_conn() as conn:
            cursor = conn.cursor()
            for table in ("case_results", "evidence_requirements"):
                cursor.execute(f"DELETE FROM {table} WHERE case_id = %s", (case_id,))
            conn.commit()

    def _persist_empty_prior(self):
        """One real successful consolidation so a prior container exists."""
        with _no_llm():
            outcome = consolidate_findings(self.case_id)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(
            outcome["container"]["result"]["integrity"]["input_state"], "EMPTY")
        return outcome["container"]


class TestRealDBFailurePaths(ConsolidationRealDBTest):

    # -- matrix 1 + 21 through the real persistence layer ----------------------

    @requires_db
    def test_empty_case_persists_and_replays_verbatim_through_the_real_db(self):
        first = self._persist_empty_prior()

        # real read-back: the container really is stored server-side
        persisted = agent_repo.get_property_findings(self.case_id)
        self.assertEqual(persisted, first)

        # matrix 21: rerun over identical inputs → verbatim cache, no write,
        # no model — pinned against the REAL database
        with mock.patch.object(
                    agent_repo, "save_property_findings",
                    side_effect=AssertionError("matrix 21: replay must not write")), \
                _no_llm():
            second = consolidate_findings(self.case_id)
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["container"], first)

    # -- matrix 18: read failure on the dossier registry ------------------------

    @requires_db
    def test_dossier_read_failure_blocks_and_leaves_persisted_prior_intact(self):
        prior = self._persist_empty_prior()

        with _with_blast(READ_BLAST):
            outcome = consolidate_findings(self.case_id)
        self.assertEqual(outcome["status"], "blocked")
        self.assertTrue(outcome["retryable"])
        # real read-back: the prior container survived, byte-for-byte
        self.assertEqual(agent_repo.get_property_findings(self.case_id), prior)

    # -- matrix 20: write failure at save ----------------------------------------

    @requires_db
    def test_write_failure_is_an_error_with_prior_intact_and_retry_heals(self):
        prior = self._persist_empty_prior()

        # change I5 via a REAL ledger row so the unchanged-input replay misses
        _insert_requirement(self.case_id)

        with _with_blast(WRITE_BLAST):
            with _no_llm():
                outcome = consolidate_findings(self.case_id)
        # row 20: the run reports error; the persisted row is NEVER marked blocked
        self.assertEqual(outcome["status"], "error")
        self.assertEqual(agent_repo.get_property_findings(self.case_id), prior)

        # matrix 20's "retry works": a healthy run persists the new container
        with _no_llm():
            retried = consolidate_findings(self.case_id)
        self.assertEqual(retried["status"], "ok")
        healed = agent_repo.get_property_findings(self.case_id)
        self.assertIsNotNone(healed)
        self.assertNotEqual(healed, prior)
        self.assertEqual(
            healed["result"]["readiness"]["open_requirement_ids"],
            ["REQ-C6DB-1"])

    # -- §9(b) at the reader boundary ---------------------------------------------

    @requires_db
    def test_json_null_prior_is_disclosed_and_overwritten_on_success(self):
        # a JSON column can legally hold null; the raw value is present but
        # parses to None — the engine's "unreadable prior" branch (§9(b))
        _set_raw_prior(self.case_id, "null")
        self.assertIsNone(agent_repo.get_property_findings(self.case_id))
        self.assertIsNotNone(agent_repo.get_property_findings_raw(self.case_id))

        with _no_llm():
            outcome = consolidate_findings(self.case_id)
        self.assertEqual(outcome["status"], "ok")
        # §9(b)'s register language, pinned verbatim from the engine:
        self.assertIn(
            "could not be parsed as a container",
            outcome["registration"]["prior_container_unreadable"])
        # §9(b): the next successful run overwrote the value with a real container
        self.assertEqual(
            agent_repo.get_property_findings(self.case_id),
            outcome["container"])

    @requires_db
    def test_scalar_container_value_never_silently_overwrites(self):
        """Honest reader-boundary hardening: a JSON-encoded string scalar parses
        (json.loads succeeds) but is not a container. Whatever the engine does,
        it must never silently discard the prior value without the §9(b)
        disclosure — if it treats it as an error, the real column stays intact.
        """
        _set_raw_prior(self.case_id, '"just a string, not a container object"')

        with _no_llm():
            outcome = consolidate_findings(self.case_id)
        if outcome["status"] == "ok":
            disclosure = outcome["registration"].get("prior_container_unreadable")
            self.assertTrue(
                disclosure,
                "§9(b): an ok run silently overwrote an unreadable prior")
        else:
            self.assertEqual(outcome["status"], "error")
            self.assertEqual(
                agent_repo.get_property_findings_raw(self.case_id),
                '"just a string, not a container object"')

    # -- DO note (§13): v2 fields survive the real JSON column -------------------

    @requires_db
    def test_v2_container_round_trips_through_the_real_json_column(self):
        # one REAL persisted dossier row (save_transaction_result, real upsert)
        agent_repo.save_transaction_result(
            case_id=self.case_id, tx_id="PA-TC-0007",
            verification={
                "tx_id": "PA-TC-0007", "sequence": 7,
                "status": "VERIFIED_WITH_AVAILABLE_EVIDENCE",
                "report": "Verification completed; memorandum recorded.",
                "required_documents": [],
                "findings": [{
                    "finding_id": "TF-001", "significance": "ESTABLISHED",
                    "category": "encumbrance", "title": "Unregistered sale",
                    "text": "memorandum",
                    "evidence": [{"doc_id": "DOC1", "pages": "1"}],
                    "is_legal_defect": True,
                }],
            })
        draft = {"findings": [{"members": [0], "title": "Unregistered sale",
                               "description": "memorandum"}]}
        with mock.patch.object(consolidation, "complete_json",
                               return_value=draft):
            outcome = consolidate_findings(self.case_id)
        self.assertEqual(outcome["status"], "ok")

        persisted = agent_repo.get_property_findings(self.case_id)
        # strict equality over the whole container: every v2 field —
        # identity, source_observations, lifecycle_events, blocks, correlations —
        # must survive the real JSON column round trip unchanged
        self.assertEqual(persisted, outcome["container"])
        finding = persisted["result"]["findings"][0]
        self.assertEqual(finding["finding_id"], "PF-001")
        self.assertTrue(finding["identity_key"])
        # birth writes no events; the field survives the JSON column as a list
        self.assertIsInstance(finding["lifecycle_events"], list)
        # row 17 at the real layer: the unowned DOC1 ref was dropped + registered
        self.assertIn({"doc_id": "DOC1", "reason": "not owned by the case"},
                      outcome["registration"]["excluded_evidence_refs"])


if __name__ == "__main__":
    unittest.main()
