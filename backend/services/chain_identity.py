"""Application-owned identity for Phase A chain entries and Phase B findings.

Pure functions only — no database, LLM, or framework imports. The persistence
and tool layers import from here; the reverse never happens, so the identity
rules stay testable in isolation.

Phase A strategy (audit D2 / task §3): stable ``PA-TC-####`` ids are stamped at
save time. A rerun preserves an earlier id only when the entry can be matched
to exactly one previous entry by content (registration reference, or
transaction type + date + party continuity / source-document set). Array
position never dictates identity. Ambiguous matches are recorded and resolved
safely with a brand-new id; ids already used by any persisted transaction
result are never reassigned, so historical results stay associated with the
same transaction.

Phase B strategy: a dossier finding's stable ``TF-###`` id is derived from the
same content key Phase C uses to dedup observations — (transaction, category,
title, cited document ids) — so an unchanged finding keeps its id across
result updates while genuinely new observations get a fresh id.
"""

from __future__ import annotations

import re

from backend.schemas.analysis import TX_ID_RE, is_assigned_tx_id, new_tx_finding_id

_TX_ID = re.compile(TX_ID_RE)


def _norm(value) -> str:
    # Unwrap str-enums: persisted rows store the value, model dumps carry the
    # enum object — both sides of a content comparison must see the same text.
    raw = getattr(value, "value", value)
    return re.sub(r"\s+", " ", str(raw or "")).strip().casefold()


def _names(values) -> list[str]:
    """Normalized party-name strings, whatever the wire shape sent."""
    names = []
    for value in values if isinstance(values, list) else []:
        if isinstance(value, dict):
            value = value.get("name") or value.get("full_name")
        name = _norm(value)
        if name:
            names.append(name)
    return names


def _string_list_ok(value) -> bool:
    if not isinstance(value, list):
        return False
    return all(isinstance(item, str) and item.strip() for item in value)


def semantic_transaction(entry: dict) -> dict:
    """The content fields that define one chain entry's identity."""
    transaction = entry.get("documented_transaction") or {}
    return {
        "type": _norm(transaction.get("transaction_type")),
        "reg_number": _norm(transaction.get("transaction_number")),
        "reg_office": _norm(transaction.get("registration_office")),
        "executed_date": _norm(transaction.get("executed_date")),
        "transferors": _names(transaction.get("transferors")),
        "transferees": _names(transaction.get("transferees")),
        "source_docs": sorted(
            str(ref.get("doc_id") or "")
            for ref in (transaction.get("source_refs") or [])
            if isinstance(ref, dict) and ref.get("doc_id")
        ),
    }


def _match_reason(prev: dict, new: dict) -> str | None:
    """One confident content match, checked in decreasing specificity."""
    # Registration numbers are office-scoped: two STATED offices that disagree
    # prove different transactions even for an identical number. When office
    # data is missing on either side the number match keeps its historical
    # strength (cross-office reuse with no office recorded is a documented
    # limitation), and current behavior for office-less chains is preserved.
    if (
        new["reg_number"]
        and new["reg_number"] == prev["reg_number"]
        and not (prev["reg_office"] and new["reg_office"] and prev["reg_office"] != new["reg_office"])
    ):
        return "registration_reference"
    if new["type"] and new["type"] == prev["type"] and new["executed_date"] and new["executed_date"] == prev["executed_date"]:
        if set(new["transferors"]) & set(prev["transferees"]):
            return "type_date_party_continuity"
        if new["source_docs"] and new["source_docs"] == prev["source_docs"]:
            return "type_date_source_documents"
    return None


def assign_chain_tx_ids(
    chain: list[dict],
    prior_chain: list[dict] | None,
    taken_ids: set[str] | None = None,
) -> list[str]:
    """Stamp every chain entry with an app-owned transaction id, in place.

    ``prior_chain`` is the previously persisted chain; ``taken_ids`` are ids
    already claimed elsewhere in the case (persisted transaction-result keys).
    Returns human-readable notes documenting every assignment decision.
    """
    seen_ids: set[str] = {str(tx_id) for tx_id in (taken_ids or set())}
    # Prior chain entries hold their ids for the life of the case even when a
    # rerun fails to match them — a merged-in entry must never receive an id
    # another (possibly persisted-result-keyed) transaction still carries.
    for prior_entry in prior_chain or []:
        if isinstance(prior_entry, dict) and prior_entry.get("tx_id"):
            seen_ids.add(str(prior_entry["tx_id"]))
    claimed: set[int] = set()

    def next_free() -> str:
        number = 1
        while f"PA-TC-{number:04d}" in seen_ids:
            number += 1
        assigned = f"PA-TC-{number:04d}"
        seen_ids.add(assigned)
        return assigned

    notes: list[str] = []
    matches: dict[int, tuple[int, str]] = {}
    # Pass 1 — collect content matches so ambiguous cases are visible before
    # any id claim is made (a match seen on the fly could look unique).
    for index, entry in enumerate(chain):
        if not isinstance(entry, dict):
            continue
        candidates: list[tuple[int, str]] = []
        for prior_index, prior_entry in enumerate(prior_chain or []):
            if not isinstance(prior_entry, dict) or not is_assigned_tx_id(prior_entry.get("tx_id")):
                continue
            reason = _match_reason(
                semantic_transaction(prior_entry), semantic_transaction(entry)
            )
            if reason:
                candidates.append((prior_index, reason))
        if len(candidates) == 1:
            matches[index] = candidates[0]
        elif candidates:
            notes.append(
                f"chain item {index + 1}: ambiguous match against {len(candidates)} previous "
                "entries; assigning a new id rather than reusing one"
            )
    for index, entry in enumerate(chain):
        if not isinstance(entry, dict):
            continue
        transaction = entry.setdefault("documented_transaction", {})
        for holder in (entry, transaction):
            holder.pop("tx_id", None)
        transaction.pop("upstream_tx_ids", None)
        if index in matches:
            prior_index, reason = matches[index]
            if prior_index not in claimed:
                claimed.add(prior_index)
                tx_id = str((prior_chain or [])[prior_index].get("tx_id"))
                seen_ids.add(tx_id)
                notes.append(f"chain item {index + 1} keeps {tx_id} (matched on {reason})")
            else:
                notes.append(
                    f"chain item {index + 1}: matched previous item was already claimed; assigning a new id rather than reusing one"
                )
                tx_id = next_free()
        else:
            tx_id = next_free()
            notes.append(f"chain item {index + 1} assigned {tx_id} as a new content identity")
        entry["tx_id"] = tx_id
    return notes


_PARCEL_FIELDS = ("survey_number", "plot_number", "site_flat_number", "cts_number")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _parcel_fields(transaction: dict) -> dict[str, str]:
    return {
        field: _norm(transaction.get(field))
        for field in _PARCEL_FIELDS
        if _norm(transaction.get(field))
    }


def _transaction_doc_ids(transaction: dict) -> set[str]:
    return {
        str(ref.get("doc_id") or "")
        for ref in (transaction.get("source_refs") or [])
        if isinstance(ref, dict) and ref.get("doc_id")
    }


def _identifier_related(parent_value: str, child_value: str) -> bool:
    """True when one stated parcel identifier mentions the other.

    Word-boundary aware so `S-1` does not match `S-100`; both directions are
    accepted because a later instrument may widen a code into subdivisions
    (`S-50` → `S-50/1, S-50/2`) exactly as a consolidation deed does.
    """
    if parent_value == child_value:
        return True
    shorter, longer = (parent_value, child_value) if len(parent_value) <= len(child_value) else (child_value, parent_value)
    start = longer.find(shorter)
    while start >= 0:
        end = start + len(shorter)
        before_ok = start == 0 or not longer[start - 1].isalnum()
        after_ok = end == len(longer) or not longer[end].isalnum()
        if before_ok and after_ok:
            return True
        start = longer.find(shorter, start + 1)
    return False


def _dates_allow(parent_date, child_date) -> bool:
    """Refuse only a verifiable chronology violation (both dates ISO-dated).

    Non-ISO or missing dates cannot be compared safely and are never invented
    into a rejection; chain order already anchors sequence.
    """
    parent_date, child_date = _norm(parent_date), _norm(child_date)
    if (
        parent_date and child_date
        and _ISO_DATE.fullmatch(parent_date) and _ISO_DATE.fullmatch(child_date)
    ):
        return parent_date <= child_date
    return True


def attach_upstream_ids(chain: list[dict]) -> list[str]:
    """Stamp entry-level ``upstream_tx_ids`` — title-chain continuation links.

    Evidence-gated, not position-glob. The IMMEDIATELY earlier entry whose
    transferees overlap the entry's transferors is the ordinary conveyance-
    succession link (party evidence + chain adjacency — the established
    single-parent rule, unchanged). A NON-adjacent predecessor additionally
    requires corroboration already present in the transactions — a shared/
    subdivided parcel number (survey/plot/site-flat/CTS), the same instrument
    number (unless stated registration offices conflict), or an overlapping
    source document — because across a chain jump a party name alone cannot
    distinguish one person's second sale from an unrelated namesake. A
    predecessor whose stated parcel identifiers never match the entry's is
    refused, as is one executed AFTER the entry when both execution dates are
    ISO-formatted. Missing data is never invented; the uncertainty simply
    produces no link. Decision reasons are returned for the save response.
    """
    notes: list[str] = []
    for index, entry in enumerate(chain):
        transaction = entry.get("documented_transaction") or {}
        transferors = _names(transaction.get("transferors"))
        entry.pop("upstream_tx_ids", None)
        if not transferors:
            continue
        upstream: list[str] = []
        for prior_index in range(index):
            parent_tx_id = entry_chain_id(chain, prior_index)
            if not parent_tx_id:
                continue
            parent_transaction = chain[prior_index].get("documented_transaction") or {}
            if not (set(transferors) & set(_names(parent_transaction.get("transferees")))):
                continue
            label = f"chain item {index + 1}"
            if not _dates_allow(parent_transaction.get("executed_date"), transaction.get("executed_date")):
                notes.append(
                    f"{label}: refused upstream {parent_tx_id} (executed after this transaction)"
                )
                continue
            parent_parcels = _parcel_fields(parent_transaction)
            child_parcels = _parcel_fields(transaction)
            related = [
                field for field in parent_parcels
                if field in child_parcels and _identifier_related(parent_parcels[field], child_parcels[field])
            ]
            comparable = [field for field in parent_parcels if field in child_parcels]
            anchors: list[str] = []
            reason = ""
            if prior_index == index - 1:
                anchors.append("adjacent chain succession")
            if related:
                anchors.append(f"continuing parcel {related[0]}={child_parcels[related[0]]}")
            parent_number, child_number = (
                _norm(parent_transaction.get("transaction_number")),
                _norm(transaction.get("transaction_number")),
            )
            if (
                parent_number and parent_number == child_number
                and not (
                    _norm(parent_transaction.get("registration_office"))
                    and _norm(transaction.get("registration_office"))
                    and _norm(parent_transaction.get("registration_office")) != _norm(transaction.get("registration_office"))
                )
            ):
                anchors.append(f"same instrument number {parent_number}")
            if _transaction_doc_ids(parent_transaction) & _transaction_doc_ids(transaction):
                anchors.append("shared source documents")
            if comparable and not related:
                reason = "stated parcel identifiers differ"
            if anchors:
                upstream.append(parent_tx_id)
                notes.append(
                    f"{label}: upstream link {parent_tx_id} ({', '.join(anchors)})"
                    + (f"; but {reason}" if reason else "")
                )
            else:
                notes.append(
                    f"{label}: refused upstream {parent_tx_id} ({reason or 'party-name overlap across a chain jump needs a shared parcel, instrument number, or source document'})"
                )
        if upstream:
            entry["upstream_tx_ids"] = upstream
    return notes


def entry_chain_id(chain: list[dict], index: int) -> str:
    entry = chain[index] if 0 <= index < len(chain) else None
    tx_id = str((entry or {}).get("tx_id") or "")
    return tx_id if _TX_ID.fullmatch(tx_id) else ""


# -- Phase B finding content identity -------------------------------------------


def finding_content_key(tx_id: str, finding: dict) -> tuple[str, str, str, tuple[str, ...]]:
    """Phase C's dedup identity (category, title, cited docs), scoped to one transaction."""
    doc_ids = tuple(sorted({
        str(ref.get("doc_id") or "")
        for ref in (finding.get("evidence") or finding.get("resolution_evidence") or [])
        if isinstance(ref, dict) and ref.get("doc_id")
    }))
    return (str(tx_id), _norm(finding.get("category", "OTHER")), _norm(finding.get("title")), doc_ids)


def finding_registry(results: list[dict]) -> tuple[dict[tuple[str, str, str, tuple[str, ...]], str], set[int]]:
    """Per-case map of content key -> finding id, plus every number already used.

    ``results`` are persisted transaction-result rows (each with ``tx_id`` and
    ``findings``); ids the model may have invented are ignored here — the save
    path strips them before registry use.
    """
    registry: dict[tuple[str, str, str, tuple[str, ...]], str] = {}
    used: set[int] = set()
    for result in results or []:
        if not isinstance(result, dict):
            continue
        tx_id = str(result.get("tx_id") or "")
        for finding in (result.get("findings") or []):
            if not isinstance(finding, dict):
                continue
            finding_id = str(finding.get("finding_id") or "")
            if not _TX_FINDING.fullmatch(finding_id):
                continue
            registry[finding_content_key(tx_id, finding)] = finding_id
            used.add(_tx_finding_number(finding_id))
    return registry, used


_TX_FINDING = re.compile(r"TF-\d{3,4}")  # matches TF-### and overflow TF-#### ids


def _tx_finding_number(finding_id: str) -> int:
    try:
        return int(finding_id.removeprefix("TF-"))
    except ValueError:
        return 0


def _next_tx_finding_id(used_numbers: set[int]) -> str:
    number = 1
    while number in used_numbers:
        number += 1
    return new_tx_finding_id(number)


def assign_finding_ids(
    tx_id: str,
    findings: list[dict],
    registry: dict[tuple[str, str, str, tuple[str, ...]], str],
    used_numbers: set[int],
) -> list[dict]:
    """Stamp app-owned ``finding_id`` on each finding dict, in place.

    Same content identity (transaction + category + title + cited docs) keeps
    its existing id; anything else gets the next unused per-case number, so a
    batch with two identical content keys still gets distinct ids.
    """
    claimed_keys: set[tuple[str, str, str, tuple[str, ...]]] = set()
    claimed_ids: set[str] = set()
    for finding in findings:
        key = finding_content_key(tx_id, finding)
        finding_id = registry.get(key) if key not in claimed_keys else None
        if finding_id and finding_id in claimed_ids:
            finding_id = None
        if finding_id is None:
            finding_id = _next_tx_finding_id(used_numbers)
        used_numbers.add(_tx_finding_number(finding_id))
        claimed_keys.add(key)
        claimed_ids.add(finding_id)
        finding["finding_id"] = finding_id
    return findings
