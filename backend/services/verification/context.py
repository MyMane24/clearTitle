"""Context engineering for the Lead Examiner.

Two jobs:

* ``render_case_file`` turns the Case File into a compact text snapshot. The
  Lead gets it from the ``view_case_file`` tool and in its first prompt. It is
  delivered as tool output, never as instructions, because it contains text
  taken from documents.
* ``trim_tool_results`` is a history processor. It keeps the newest raw tool
  results and replaces older ones with a one-line reference. Nothing is lost:
  what the agent established is in the Case File.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart

from backend.config import VERIFY_KEEP_TOOL_CHARS, VERIFY_KEEP_TOOL_RESULTS
from backend.services.verification.case_file import CaseFile
from backend.services.verification.gates import GateContext, closure_problems

CLEARED = (
    "[Older result cleared to save context. What you recorded is in view_case_file; a saved "
    "examiner report reopens at no cost with examine_document.]"
)


def render_case_file(case: CaseFile, ctx: GateContext | None = None) -> str:
    """A compact, readable snapshot of the Case File for the model."""
    lines = [
        f"CASE FILE (case {case.case_id})",
        "",
        f"CHAIN ({len(case.chain)} links, earliest first)",
    ]
    for link in case.chain:
        transaction = link.transaction
        date = transaction.executed_date or transaction.registration_date or "undated"
        verdict = link.verdict.verdict if link.verdict else "NO VERDICT"
        origin = " [added during verification]" if link.origin == "verification" else ""
        lines.append(
            f"- {link.link_id}{origin} | {transaction.transaction_type} | {date} | "
            f"{transaction.transaction_number or 'no number'} | "
            f"{', '.join(transaction.transferors) or '?'} -> {', '.join(transaction.transferees)} | "
            f"{transaction.evidence_status} | sources: "
            f"{', '.join(ref.doc_id for ref in transaction.source_refs)} | {verdict}"
        )
        if not link.continues_previous and link is not case.chain[0]:
            lines.append(f"    BREAK: {link.break_note or 'not yet recorded'}")
    lines += ["", "DOCUMENTS (recitals R and unexpected findings U from each examiner report)"]
    for entry in case.documents.values():
        state = "examined" if entry.examined else "NOT EXAMINED"
        if entry.examination_error:
            state = f"NOT EXAMINABLE ({entry.examination_error})"
        lines.append(
            f"- {entry.doc_id} | {entry.document_type} | {entry.filename} | {state} | "
            f"{(entry.report.summary if entry.report else entry.summary) or ''}"[:300]
        )
        if entry.report:
            lines += [f"    R p.{fact.page}: {fact.text}"[:180] for fact in entry.report.recitals]
            lines += [f"    U p.{fact.page}: {fact.text}"[:180] for fact in entry.report.unexpected]
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
    lines += _section("TASKS", [f"{task.id} [{task.status}] {task.text}" for task in case.tasks])
    if ctx is not None:
        remaining = closure_problems(ctx)
        lines += _section("STILL TO DO BEFORE CLOSING", remaining or ["Nothing: you may close."])
    return "\n".join(lines)


def _section(title: str, items: list[str]) -> list[str]:
    return ["", title, *(f"- {item}" for item in items or ["none"])]


def trim_tool_results(ctx: RunContext, messages: list[ModelMessage]) -> list[ModelMessage]:
    """Keep only the newest tool results, within a count and a size budget.

    The newest batch of results is always kept whole, because the model has not
    read it yet. Older results are kept only while there are at most
    ``VERIFY_KEEP_TOOL_RESULTS`` of them within ``VERIFY_KEEP_TOOL_CHARS``
    characters; the rest become a one-line reference, so large examiner reports
    do not inflate every later model call.
    """
    positions = [
        (message_index, part_index, len(str(part.content)))
        for message_index, message in enumerate(messages)
        if isinstance(message, ModelRequest)
        for part_index, part in enumerate(message.parts)
        if isinstance(part, ToolReturnPart) and part.content != CLEARED
    ]
    latest = positions[-1][0] if positions else -1
    kept, used = 0, 0
    stale: set[tuple[int, int]] = set()
    for message_index, part_index, size in reversed(positions):
        # The newest batch is always kept whole: the model has not read it yet.
        within = message_index == latest or (
            kept < VERIFY_KEEP_TOOL_RESULTS and used + size <= VERIFY_KEEP_TOOL_CHARS
        )
        if within:
            kept, used = kept + 1, used + size
        else:
            stale.add((message_index, part_index))
    if not stale:
        return messages
    trimmed: list[ModelMessage] = []
    for message_index, message in enumerate(messages):
        if not any(index == message_index for index, _ in stale):
            trimmed.append(message)
            continue
        parts = [
            replace(part, content=CLEARED) if (message_index, part_index) in stale else part
            for part_index, part in enumerate(message.parts)
        ]
        trimmed.append(replace(message, parts=parts))
    return trimmed
