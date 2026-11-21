"""The live step feed shown in the dashboard while the agent works."""

from __future__ import annotations

from collections import Counter

from pydantic_ai import Agent
from pydantic_ai.messages import BaseToolReturnPart, RetryPromptPart, TextPart, ToolCallPart

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


def _refused(part: object) -> bool:
    """A tool call or closing attempt the gates sent back to the model."""
    if isinstance(part, RetryPromptPart):
        return True
    return isinstance(part, BaseToolReturnPart) and part.outcome in ("retried", "failed")


def rejection_text(part: RetryPromptPart | BaseToolReturnPart) -> str:
    """One readable line for a refused tool call or closing attempt."""
    if isinstance(part.content, str):
        reason = part.content
    elif isinstance(part, RetryPromptPart):
        reason = part.model_response()
    else:
        reason = part.model_response_str(wrap_if_error=False)
    lines = [line.strip(" -") for line in reason.splitlines() if line.strip(" -")]
    if lines and lines[0].lower().startswith(("not saved", "the case cannot close", "fix")):
        lines = lines[1:] or lines
    what = "closing" if part.tool_name in (None, "final_result") else part.tool_name
    return f"Step refused ({what}): {' '.join(lines)[:_MAX_TEXT]}"


def record_node(node: object, emit: EventSink) -> None:
    """Turn an ``agent.iter()`` node into feed lines.

    The model's own words become "thinking" lines. Every tool call or closing
    attempt the gates refused becomes a "rejected" line, so wasted calls are
    visible. Successful tool calls describe themselves from inside each tool.
    """
    if Agent.is_call_tools_node(node):
        calls = Counter(
            part.tool_name for part in node.model_response.parts if isinstance(part, ToolCallPart)
        )
        if calls:
            emit("calls", ", ".join(f"{name} x{n}" for name, n in calls.items()), None)
        for part in node.model_response.parts:
            if isinstance(part, TextPart) and part.content.strip():
                emit("thinking", " ".join(part.content.split())[:_MAX_TEXT], None)
    elif Agent.is_model_request_node(node):
        for part in node.request.parts:
            if _refused(part):
                text = rejection_text(part)
                logger.info("verification_step_refused %s", text)
                emit("rejected", text, None)
