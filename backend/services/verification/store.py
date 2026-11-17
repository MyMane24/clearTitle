"""Where the runner reads and writes: the database in production, memory in tests.

The runner talks only to this interface, so storage can change without
touching the agent.
"""

from __future__ import annotations

from typing import Protocol

from backend.schemas.due_diligence import DueDiligenceReport
from backend.services.verification import case_file as cf
from backend.services.verification.deps import EventSink


class Store(Protocol):
    def phase_a(self, case_id: str) -> dict | None: ...
    def documents(self, case_id: str) -> list[dict]: ...
    def text(self, case_id: str, doc_id: str) -> str: ...
    def load_case_file(self, case_id: str) -> tuple[cf.CaseFile, int] | None: ...
    def save_case_file(self, case: cf.CaseFile, expected_version: int) -> int: ...
    def create_run(self, run_id: str, case_id: str, kind: str) -> None: ...
    def finish_run(self, run_id: str, status: str, usage: dict, error: str | None) -> None: ...
    def latest_report(self, case_id: str) -> DueDiligenceReport | None: ...
    def save_report(self, case_id: str, report: DueDiligenceReport) -> None: ...
    def sink(self, case_id: str, run_id: str) -> EventSink: ...


class DbStore:
    """The production store, backed by MySQL through the repositories."""

    def phase_a(self, case_id: str) -> dict | None:
        from backend.database.repositories import agent_repo

        return agent_repo.get_agent_result(case_id)

    def documents(self, case_id: str) -> list[dict]:
        from backend.database.repositories import agent_repo

        return agent_repo.get_agent_documents(case_id)

    def text(self, case_id: str, doc_id: str) -> str:
        from backend.database.repositories import agent_repo

        return agent_repo.get_document_raw_text(case_id, doc_id)

    def load_case_file(self, case_id: str) -> tuple[cf.CaseFile, int] | None:
        from backend.database.repositories import verification_repo

        stored = verification_repo.get_case_file(case_id)
        return (cf.load(stored[0]), stored[1]) if stored else None

    def save_case_file(self, case: cf.CaseFile, expected_version: int) -> int:
        from backend.database.repositories import verification_repo

        case.version = expected_version + 1
        return verification_repo.save_case_file(
            case.case_id, case.model_dump(mode="json"), expected_version
        )

    def create_run(self, run_id: str, case_id: str, kind: str) -> None:
        from backend.database.repositories import verification_repo

        verification_repo.create_run(run_id, case_id, kind)

    def finish_run(self, run_id: str, status: str, usage: dict, error: str | None) -> None:
        from backend.database.repositories import verification_repo

        verification_repo.finish_run(run_id, status, usage, error)

    def latest_report(self, case_id: str) -> DueDiligenceReport | None:
        from backend.database.repositories import verification_repo

        stored = verification_repo.get_latest_report(case_id)
        return DueDiligenceReport.model_validate(stored["report"]) if stored else None

    def save_report(self, case_id: str, report: DueDiligenceReport) -> None:
        from backend.database.repositories import verification_repo

        verification_repo.save_report(
            case_id, report.version, report.opinion, report.model_dump(mode="json")
        )

    def sink(self, case_id: str, run_id: str) -> EventSink:
        from backend.services.verification.events import db_sink

        return db_sink(case_id, run_id)


class MemoryStore:
    """An in-memory store for tests and offline experiments."""

    def __init__(self, phase_a: dict | None, documents: list[dict], texts: dict[str, str]):
        from backend.services.verification.events import ListSink

        self._phase_a = phase_a
        self._documents = documents
        self.texts = texts
        self.case_file: dict | None = None
        self.version = 0
        self.runs: dict[str, dict] = {}
        self.reports: list[DueDiligenceReport] = []
        self.events = ListSink()
        self.text_reads: list[str] = []

    def phase_a(self, case_id: str) -> dict | None:
        return self._phase_a

    def documents(self, case_id: str) -> list[dict]:
        return self._documents

    def text(self, case_id: str, doc_id: str) -> str:
        self.text_reads.append(doc_id)
        return self.texts.get(doc_id, "")

    def load_case_file(self, case_id: str) -> tuple[cf.CaseFile, int] | None:
        return (cf.load(self.case_file), self.version) if self.case_file else None

    def save_case_file(self, case: cf.CaseFile, expected_version: int) -> int:
        if expected_version != self.version:
            raise RuntimeError("stale case file")
        self.version += 1
        case.version = self.version
        self.case_file = case.model_dump(mode="json")
        return self.version

    def create_run(self, run_id: str, case_id: str, kind: str) -> None:
        self.runs[run_id] = {"kind": kind, "status": "running"}

    def finish_run(self, run_id: str, status: str, usage: dict, error: str | None) -> None:
        self.runs[run_id].update(status=status, usage=usage, error=error)

    def latest_report(self, case_id: str) -> DueDiligenceReport | None:
        return self.reports[-1] if self.reports else None

    def save_report(self, case_id: str, report: DueDiligenceReport) -> None:
        self.reports.append(report)

    def sink(self, case_id: str, run_id: str) -> EventSink:
        return self.events
