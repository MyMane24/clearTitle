"""Deterministic helpers for the case memory handed from one transaction to the next.

The verification agent works one transaction at a time in a fresh message list.
What it knows about the transactions already completed comes from here: a
compact progress ledger, the holders entering the active transaction, and the
previous link's saved handoff. Everything is derived from persisted state, so a
paused/resumed run rebuilds exactly the same memory.

This module is pure (no repository access) so it can be shared by the tool
layer and the orchestrator without import cycles.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_HONORIFICS = frozenset(
    "shri sri shree smt srimati mr mrs ms miss dr late kum kumari sri. m/s messrs "
    "s/o d/o w/o c/o son daughter wife of".split()
)


def party_tokens(name: object) -> frozenset[str]:
    """Order-insensitive, honorific-free token set for a party name."""
    text = re.sub(r"[^a-z0-9\s]", " ", str(name or "").casefold())
    return frozenset(t for t in text.split() if t and t not in _HONORIFICS)


def parties_match(left: object, right: object) -> bool:
    """True when two names plausibly denote the same party (OCR/spelling tolerant)."""
    a, b = party_tokens(left), party_tokens(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 2 and len(b) >= 2 and (a <= b or b <= a):
        return True
    return SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio() >= 0.88


def phase_a_parties(entry: dict | None) -> tuple[list[str], list[str]]:
    """(transferors, transferees) of a Phase A title-chain entry, tolerant of legacy keys."""
    transaction = (entry or {}).get("documented_transaction") or entry or {}

    def names(*keys: str) -> list[str]:
        for key in keys:
            value = transaction.get(key)
            if isinstance(value, list):
                cleaned = [str(v).strip() for v in value if str(v or "").strip()]
                if cleaned:
                    return cleaned
        return []

    return names("transferors", "vendors"), names("transferees", "purchasers")


def continuity_hint(previous_holders: list[str], transferors: list[str]) -> dict:
    """Compare the holders entering a transaction with its deed's transferors.

    ``state`` is SAME (every transferor is a prior holder), PARTIAL, DIFFERENT
    or UNKNOWN (one side has no names). It is a hint the model confirms or
    contests against the documents - never a legal conclusion.
    """
    if not previous_holders or not transferors:
        return {"state": "UNKNOWN", "matched": [], "unmatched": list(transferors or [])}
    matched = [t for t in transferors if any(parties_match(t, h) for h in previous_holders)]
    unmatched = [t for t in transferors if t not in matched]
    state = "SAME" if not unmatched else ("PARTIAL" if matched else "DIFFERENT")
    return {"state": state, "matched": matched, "unmatched": unmatched}


def holders_entering(previous_result: dict | None, previous_entry: dict | None) -> tuple[list[str], str]:
    """Holders entering the active transaction and where that came from.

    Prefers the previous link's saved handoff, then its Phase A transferees.
    """
    handoff = (previous_result or {}).get("handoff") or {}
    if isinstance(handoff, dict) and handoff.get("holders_after"):
        return list(handoff["holders_after"]), "previous_handoff"
    _, transferees = phase_a_parties(previous_entry)
    if transferees:
        return transferees, "phase_a_transferees"
    return [], "unknown"


def derive_handoff(
    handoff: dict | None, *, sequence: int, entry: dict | None,
    previous_result: dict | None, previous_entry: dict | None,
) -> dict:
    """Fill what the model left out of a completed result's handoff, deterministically.

    The model-authored fields (established facts, open issues, note) are kept
    verbatim. Only holders_after and an unambiguous continuity label are derived.
    """
    out = dict(handoff or {})
    if not out.get("holders_after"):
        _, transferees = phase_a_parties(entry)
        out["holders_after"] = transferees[:12]
    if sequence <= 1:
        out["continuity"] = "ROOT"
    elif (out.get("continuity") or "UNKNOWN") in {"UNKNOWN", "ROOT"}:
        transferors, _ = phase_a_parties(entry)
        prior, _ = holders_entering(previous_result, previous_entry)
        out["continuity"] = (
            "CONFIRMED" if continuity_hint(prior, transferors)["state"] == "SAME" else "UNKNOWN"
        )
    return out


def ledger_line(sequence: int, result: dict | None, entry: dict | None) -> str:
    """One compact progress line for an earlier link."""
    transaction = (entry or {}).get("documented_transaction") or {}
    kind = str(transaction.get("transaction_type") or "transaction").strip()
    date = str(transaction.get("executed_date") or transaction.get("registration_date") or "").strip()
    status = str((result or {}).get("status") or "PENDING")
    summary = " ".join(str((result or {}).get("executive_summary") or "").split())
    head = f"{sequence}. {kind}{' (' + date + ')' if date else ''} — {status}"
    return f"{head}: {summary[:240]}" if summary else head


def compact_handoff(handoff: dict | None, *, lite: bool) -> dict:
    """Prompt-sized view of a handoff; ``lite`` drops established facts."""
    handoff = handoff or {}
    out = {
        "continuity": handoff.get("continuity"),
        "holders_after": handoff.get("holders_after") or [],
        "open_issues": handoff.get("open_issues") or [],
        "note_for_next": handoff.get("note_for_next") or "",
        "stale": bool(handoff.get("stale")),
    }
    if not lite:
        out["property_after"] = handoff.get("property_after") or ""
        out["established"] = handoff.get("established") or []
        out["relies_on_requirements"] = handoff.get("relies_on_requirements") or []
    return {k: v for k, v in out.items() if v not in (None, "", [], False)}
