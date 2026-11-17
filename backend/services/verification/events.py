"""The live step feed shown in the dashboard while the agent works."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.messages import TextPart

from backend.database.repositories import verification_repo as repo
from backend.logger import get_logger
from backend.services.verification.deps import EventSink

logger = get_logger(__name__)

_MAX_TEXT = 600


def db_sink(case_id: str, run_id: str) -> EventSink:
    """An event sink that writes to ``verification_events``; never fails the run."""

    def emit(kind: str, text: str, ref: str | None = None) -> None:
        try:
            repo.append_event(case_id, run_id, kind, text[:_MAX_TEXT], ref)
        except Exception:
            logger.exception("verification_event_failed case_id=%s kind=%s", case_id, kind)

    return emit


class ListSink:
    """Collects events in memory (tests, and runs without a database)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, str | None]] = []

    def __call__(self, kind: str, text: str, ref: str | None = None) -> None:
        self.events.append((kind, text, ref))

    def texts(self, kind: str | None = None) -> list[str]:
        return [text for event_kind, text, _ in self.events if kind in (None, event_kind)]


def record_node(node: object, emit: EventSink) -> None:
    """Turn an ``agent.iter()`` node into feed lines: the model's own words, if any.

    Tool calls describe themselves from inside each tool, so they are not
    repeated here.
    """
    if Agent.is_call_tools_node(node):
        for part in node.model_response.parts:
            if isinstance(part, TextPart) and part.content.strip():
                emit("thinking", " ".join(part.content.split())[:_MAX_TEXT], None)
