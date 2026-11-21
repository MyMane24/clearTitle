"""Context engineering for the Lead Examiner.

Two jobs:

* ``render_case_file`` turns the Case File into a compact text snapshot. The
  Lead gets it from the ``view_case_file`` tool and in its first prompt. It is
  delivered as tool output, never as instructions, because it contains text
  taken from documents.
* ``compact_history`` is a history processor. History stays append-only, so the
  provider's prompt cache keeps re-sent context cheap, until it grows past
  ``VERIFY_COMPACT_AT_CHARS``. Then every older tool result and long tool-call
  argument is replaced at once by a one-line reference, and history is
  append-only again. Nothing is lost: what the agent established is in the Case
  File.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from backend.config import VERIFY_COMPACT_AT_CHARS
from backend.services.verification.case_file import CaseFile
from backend.services.verification.gates import GateContext, closure_problems

CLEARED = (
    "[Older result cleared to save context. What you recorded is in view_case_file; a saved "
    "examiner report reopens at no cost with examine_document.]"
)


def render_case_file(case: CaseFile, ctx: GateContext | None = None, lean: bool = False) -> str:
    """A compact, readable snapshot of the Case File for the model.

    ``lean`` leaves out each document's recitals and unexpected findings. The first
    prompt uses it: that prompt is never compacted, so it is re-sent on every call.
    """
    lines = [
        f"CASE FILE (case {case.case_id})",
        "",
        f"CHAIN ({len(case.chain)} links, earliest first; verify from the root, oldest first)",
    ]
    start = case.window_start()
    for index, link in enumerate(case.chain):
        transaction = link.transaction
        date = transaction.executed_date or transaction.registration_date or "undated"
        verdict = "NO VERDICT"
        if index < start:
            verdict = "before the 30-year window: not verified"
        elif link.verdict:
            verdict = f"{link.verdict.verdict} ({link.verdict.property_type or 'type not set'})"
        origin = " [added during verification]" if link.origin == "verification" else ""
        origin += " [ROOT]" if index == start else ""
        lines.append(
            f"- {link.link_id}{origin} | {transaction.transaction_type} | {date} | "
            f"{transaction.transaction_number or 'no number'} | "
            f"{', '.join(transaction.transferors) or '?'} -> {', '.join(transaction.transferees)} | "
            f"{transaction.evidence_status} | sources: "
            f"{', '.join(ref.doc_id for ref in transaction.source_refs)} | {verdict}"
        )
        if not link.continues_previous and index > start:
            lines.append(f"    BREAK: {link.break_note or 'not yet recorded'}")
    lines += [
        "",
        "DOCUMENTS (each examiner report's recitals and unexpected findings, with the fact "
        "number to cite, e.g. F3)",
    ]
    for entry in case.documents.values():
        state = "examined" if entry.examined else "NOT EXAMINED"
        if entry.examination_error:
            state = f"NOT EXAMINABLE ({entry.examination_error})"
        lines.append(
            f"- {entry.doc_id} | {entry.document_type} | {entry.filename} | {state} | "
            f"{(entry.report.summary if entry.report else entry.summary) or ''}"[:300]
        )
        if entry.report and not lean:
            number = {id(fact): n for n, fact in enumerate(entry.report.facts(), start=1)}
            lines += [
                f"    recital F{number[id(fact)]} p.{fact.page}: {fact.text}"[:190]
                for fact in entry.report.recitals
            ]
            lines += [
                f"    unexpected F{number[id(fact)]} p.{fact.page}: {fact.text}"[:190]
                for fact in entry.report.unexpected
            ]
    lines += _section("LEADS", [f"{lead.id} [{lead.status}] {lead.text}" for lead in case.leads])
    lines += _section(
        "ISSUES", [f"{issue.id} [{issue.severity}] {issue.title}" for issue in case.issues]
    )
    lines += _section(
        "REQUISITIONS",
        [
            f"{item.id} [{item.status}] {item.document} (affects {', '.join(item.affects)})"
            for item in case.requisitions
        ],
    )
    if ctx is not None:
        remaining = closure_problems(ctx)
        lines += _section("STILL TO DO BEFORE CLOSING", remaining or ["Nothing: you may close."])
    return "\n".join(lines)


def _section(title: str, items: list[str]) -> list[str]:
    return ["", title, *(f"- {item}" for item in items or ["none"])]


CLEARED_ARGS = {"note": "arguments cleared to save context; the outcome is in the Case File"}
_LONG_ARGS = 300


def _history_size(messages: list[ModelMessage]) -> int:
    size = 0
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and part.content != CLEARED:
                size += len(str(part.content))
            elif isinstance(part, ToolCallPart) and part.args != CLEARED_ARGS:
                size += len(str(part.args))
    return size


def compact_history(ctx: RunContext, messages: list[ModelMessage]) -> list[ModelMessage]:
    """Clear old tool results and long tool-call arguments, but only now and then.

    Below ``VERIFY_COMPACT_AT_CHARS`` the history is returned unchanged, so every
    call re-sends an identical prefix that the provider caches. Above it, all
    tool results except the newest batch (which the model has not read yet) and
    all long tool-call arguments before it are replaced in one go.
    """
    if _history_size(messages) <= VERIFY_COMPACT_AT_CHARS:
        return messages
    latest = max(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, ModelRequest)
            and any(isinstance(part, ToolReturnPart) for part in message.parts)
        ),
        default=-1,
    )
    compacted: list[ModelMessage] = []
    for index, message in enumerate(messages):
        if index >= latest - 1:  # the newest call batch and its results stay intact
            compacted.append(message)
            continue
        if isinstance(message, ModelRequest):
            parts = [
                replace(part, content=CLEARED) if isinstance(part, ToolReturnPart) else part
                for part in message.parts
            ]
        elif isinstance(message, ModelResponse):
            parts = [
                replace(part, args=CLEARED_ARGS)
                if isinstance(part, ToolCallPart) and len(str(part.args)) > _LONG_ARGS
                else part
                for part in message.parts
            ]
        else:
            parts = message.parts
        compacted.append(replace(message, parts=parts))
    return compacted
