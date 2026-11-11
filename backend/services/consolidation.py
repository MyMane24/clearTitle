r"""Phase C — findings consolidation (target architecture §3.1).

Input is every persisted dossier's typed findings; a deterministic dedup pass
collapses identical observations across transactions, then one scoped LLM pass
drafts consolidated property findings and cross-link contradictions from those
candidates only (never from full reports — cost rule R4). The application owns
identity, coverage, document references, gaps, and provenance: the model may
not re-investigate, assign IDs, or invent evidence.

The persisted container records the exact input hash (all dossier findings,
the evidence ledger's open requirements, and the phase-A hash) so re-runs are
idempotent: identical inputs return the cached container without an LLM call,
and only truly changed inputs reconsolidate (doc §3.5: dossier revision ->
Phase C/D invalidation handled by content instead of explicit wiring).

C1 — strict-input hardening (§13): inputs are read strictly via
``list_persisted_transaction_results``; a structurally invalid transaction row
is a run-blocking integrity failure (outcome ``blocked``, nothing persisted,
no partial salvage), while a malformed individual finding inside a valid row
is excluded + registered and the row's valid findings keep consolidating.
Evidence refs not owned by the case are dropped from unions + registered.
Every run registers, run-scoped (return value + log; never persisted into the
container — the container fields land in C3): ``input_state`` classification,
``malformed_observations``, ``excluded_evidence_refs``, and the D7 disclosure.

C2 — identity model v2 (Rev 6, approved package): every finding carries an
app-derived identity key (tier A anchored / tier B textual / tier C
model-merged, propose-only and validated), stable ``PF-\d{3}`` carry-forward
through three run-global duplicate registries (identity key, legacy content
key, PF id) with deterministic provenance ordering and conservative refuse-all
on ambiguity, the approved OD-1 lifecycle subset (status carry, the three
SUPERSEDED subtypes, merge/split lineage, ``de_observed`` reactivation), and
additive per-finding provenance (``source_observations``, ``lifecycle_events``).
The LLM stays proposal-only: it may merge candidate indexes, never touch ids,
statuses, or identity.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from backend.database.repositories import agent_repo as repo
from backend.integrations.llm.agent_llm import AgentLLMError, complete_json
from backend.logger import get_logger
from backend.prompts.loader import load_prompt
from backend.schemas.analysis import (
    ConsolidationDraftResult,
    ConsolidationProvenance,
    Correlation,
    Coverage,
    CoverageDossier,
    FindingLink,
    Integrity,
    PropertyConsolidationResult,
    PropertyEvidenceSufficiency,
    PropertyFinding,
    PropertyFindingStatus,
    Readiness,
    RequirementsDigest,
    SourceHashes,
    SourceObservation,
    TransitionEvent,
    TX_FINDING_ID_RE,
    content_hash,
    new_finding_id,
)
from backend.schemas.analysis import phase_a_hash as compute_phase_a_hash
from backend.services.agent_schemas import normalize_status
from backend.services.chain_identity import _identifier_related, _names, _parcel_fields

logger = get_logger(__name__)

CONTAINER_VERSION = "2.0"
# R4 alert bound for the Phase C prompt payload (findings/citations only).
_PROMPT_BUDGET_CHARS = 80_000
# D6: the model may echo id-like bookkeeping keys it saw in the dossier rows;
# they are never draft content and are stripped before validation.
_DRAFT_STRIP_KEYS = ("status", "finding_id", "id", "pf_id")
# D7: Phase A identity_notes are response-only; Phase C derives state from
# persisted upstream_tx_ids and must disclose that the rationale is unseen.
_D7_DISCLOSURE = (
    "phase_a_identity_notes_not_persisted: upstream link rationale "
    "unavailable to Phase C (D7)"
)


def _normalize(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _dedup_key(finding: dict) -> tuple[str, str, tuple[str, ...]]:
    """Content identity of one dossier observation: category, title, cited docs."""
    doc_ids = tuple(sorted({
        str(ref.get("doc_id") or "")
        for ref in (finding.get("evidence") or [])
        if isinstance(ref, dict) and ref.get("doc_id")
    }))
    return (_normalize(finding.get("category")), _normalize(finding.get("title")), doc_ids)


def _dedup_key_text(key: tuple[str, str, tuple[str, ...]]) -> str:
    category, title, docs = key
    return f"{category}|{title}|{';'.join(docs) if docs else '-'}"


def _raw_findings(transactions: list[dict]) -> list[tuple[str, int, dict]]:
    items: list[tuple[str, int, dict]] = []
    for result in transactions:
        tx_id = str(result.get("tx_id") or "")
        if not tx_id:
            continue
        for index, finding in enumerate(result.get("findings") or []):
            if isinstance(finding, dict):
                items.append((tx_id, index, finding))
    return items


# -- C1: input-state classification and two-level row/finding validation ------


def _new_registration() -> dict:
    """Run-scoped register (Option B, Revision 2.3): returned, logged, never
    persisted at C1 — C3 materializes it into ``integrity``."""
    return {
        "input_state": "UNKNOWN",
        "malformed_observations": [],
        "excluded_evidence_refs": [],
        "disclosures": [_D7_DISCLOSURE],
    }


def _read_state(error: BaseException) -> str:
    """CORRUPT for unreadable payloads, UNAVAILABLE for database/lock errors."""
    return "CORRUPT" if isinstance(error, ValueError) else "UNAVAILABLE"


def _row_problem(row: object) -> str | None:
    """Structurally invalid transaction row ⇒ run-blocking integrity failure."""
    if not isinstance(row, dict):
        return "row is not an object"
    if not isinstance(row.get("tx_id"), str) or not row["tx_id"].strip():
        return "transaction identity (tx_id) is missing or not a usable string"
    if not isinstance(row.get("status"), str):
        return "status is missing or not a string"
    if row.get("findings") is not None and not isinstance(row.get("findings"), list):
        return "findings is present but not a list (unreadable result structure)"
    return None


def _row_sequence(row: dict) -> int:
    sequence = row.get("sequence")
    if isinstance(sequence, bool) or not (isinstance(sequence, int) and sequence > 0):
        tx_id = str(row.get("tx_id") or "")
        try:
            sequence = int(tx_id.removeprefix("PA-TC-")) if tx_id.startswith("PA-TC-") else 0
        except ValueError:
            sequence = 0
    return sequence


def _chain_sequences(chain_entries: list[dict]) -> set[int]:
    positions: set[int] = set()
    for entry in chain_entries or []:
        value = entry.get("chain_position") if isinstance(entry, dict) else None
        if not isinstance(value, int) or isinstance(value, bool):
            value = entry.get("sequence") if isinstance(entry, dict) else None
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            positions.add(value)
    return positions


def _scan_findings(
    transactions: list[dict],
    owned_doc_ids: set[str] | None,
    registration: dict,
) -> list[dict]:
    """Finding-level pass over structurally valid rows.

    Malformed findings (non-dict entry; missing/invalid ``finding_id``) are
    excluded + registered with tx_id/position/issue and never salvage — the
    row's valid findings continue. Returns sanitized rows: identical layout
    with each excluded finding replaced by ``None`` so persisted positions
    stay honest for dedup links and the input hash. Evidence refs not owned
    by the case are dropped + registered (row 17).
    """
    sanitized: list[dict] = []
    for row in transactions:
        findings: list[dict | None] = []
        for position, finding in enumerate(row.get("findings") or []):
            if not isinstance(finding, dict):
                registration["malformed_observations"].append({
                    "tx_id": row["tx_id"], "position": position, "issue": "not an object",
                })
                findings.append(None)
                continue
            finding_id = str(finding.get("finding_id") or "")
            if not re.fullmatch(TX_FINDING_ID_RE, finding_id):
                registration["malformed_observations"].append({
                    "tx_id": row["tx_id"], "position": position,
                    "issue": "missing or invalid finding_id",
                })
                findings.append(None)
                continue
            for ref in finding.get("evidence") or []:
                doc_id = str((isinstance(ref, dict) and ref.get("doc_id")) or "")
                # C3 empty-roster correction (C1-deviation): an empty roster
                # means nothing is owned — `None` only means no roster.
                if doc_id and owned_doc_ids is not None and doc_id not in owned_doc_ids:
                    if not any(item["doc_id"] == doc_id
                               for item in registration["excluded_evidence_refs"]):
                        registration["excluded_evidence_refs"].append({
                            "doc_id": doc_id, "reason": "not owned by the case",
                        })
            findings.append(finding)
        sanitized.append({**row, "findings": findings})
    return sanitized


def _candidate_view(finding: dict, owned_doc_ids: set[str] | None) -> dict:
    """Dedupe/union view of a finding with refs not owned by the case dropped.

    `None` (no roster) keeps every ref; an empty set (C3 empty-roster
    correction) drops them all — §5.1-9 owns the distinction."""
    kept, dropped = [], []
    for ref in finding.get("evidence") or []:
        doc_id = str((isinstance(ref, dict) and ref.get("doc_id")) or "")
        if doc_id and owned_doc_ids is not None and doc_id not in owned_doc_ids:
            dropped.append(doc_id)
        else:
            kept.append(ref)
    if not dropped:
        return finding
    return {**finding, "evidence": kept, "excluded_refs": dropped}


def _collect_candidates(
    transactions: list[dict],
    owned_doc_ids: set[str] | None = None,
    excluded_refs: list[dict] | None = None,
) -> list[dict]:
    """One candidate per dedup key across all dossiers (first-seen order).

    The deterministic dedup pass: identical observations from different
    transactions collapse into one candidate carrying every source link, so
    the model sees one mortgage entry — with both tx7 and tx8 attached —
    instead of two near-identical rows (fixture: mortgage-in-3-dossiers => 1).
    Per-candidate ``excluded_refs`` record which cited docs were dropped
    roster-wide (the run-level register is filled by ``_scan_findings``).
    """
    groups: dict[tuple, list[tuple[str, int, dict]]] = {}
    for item in _raw_findings(transactions):
        view = _candidate_view(item[2], owned_doc_ids)
        groups.setdefault(_dedup_key(view), []).append((item[0], item[1], view))
    candidates: list[dict] = []
    for key, members in groups.items():
        first = members[0][2]
        evidence, seen = [], set()
        for _tx_id, _index, finding in members:
            for ref in (finding.get("evidence") or []):
                if not isinstance(ref, dict) or not ref.get("doc_id"):
                    continue
                identity = (str(ref.get("doc_id")), str(ref.get("pages") or ""))
                if identity in seen:
                    continue
                seen.add(identity)
                evidence.append({"doc_id": str(ref.get("doc_id")), "pages": str(ref.get("pages") or "")})
        candidates.append({
            "key": key,
            "significance": first.get("significance"),
            "category": first.get("category"),
            "title": first.get("title"),
            "text": first.get("text"),
            "is_legal_defect": any(bool(member[2].get("is_legal_defect")) for member in members),
            "evidence": evidence,
            "sources": [
                {
                    "tx_id": tx_id,
                    "finding_index": index,
                    "tf_id": str(view.get("finding_id") or ""),
                    "title": str(view.get("title") or ""),
                    "text_excerpt": str(view.get("text") or "")[:240],
                    "evidence_refs": [
                        {"doc_id": str(ref.get("doc_id")), "pages": str(ref.get("pages") or "")}
                        for ref in (view.get("evidence") or [])
                        if isinstance(ref, dict) and ref.get("doc_id")
                    ],
                }
                for tx_id, index, view in members
            ],
            "tx_ids": sorted({tx_id for tx_id, _index, _finding in members}),
            "excluded_refs": sorted({
                doc_id
                for member in members
                for doc_id in (member[2].get("excluded_refs") or [])
            }),
        })
    return candidates


# -- C2 identity machinery (Rev 6 §5/§5.1; application-owned, model-free) -------


_PARCEL_FIELDS = ("survey_number", "plot_number", "site_flat_number", "cts_number")
_PUNCT_STRIP = "\"'`’‘“”,;:.!?()[]{}<>|*_~^\\"
# Seed table per design §4.2.2 (fixed order; first hit wins; `generic` fallback).
# Row 5: the DO's `title_intent / execution` label has no matching value in the
# shipped FindingCategory enum; `authority` is the enum category whose findings
# express unregistered / improperly-stamped execution defects.
_KIND_SEED: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("encumbrance",), ("mortgage", "charge", "lien", "deposit", "subsisting"), "mortgage_charge"),
    (("encumbrance",), ("discharge", "release", "satisfaction entry not recorded"), "discharge_record"),
    (("chain_gap",), ("missing link", "no registered instrument between"), "missing_link"),
    (("litigation",), ("suit", "lis pendens", "pending case"), "litigation_pending"),
    (("title_intent", "execution", "authority"), ("unregistered", "improperly stamped", "unsigned"), "execution_defect"),
)


def _od3(value) -> str:
    """OD-3 shared normalizer: casefold + whitespace collapse + surrounding
    punctuation strip, preserving ``/`` and ``-`` inside identifiers."""
    raw = getattr(value, "value", value)
    text = " ".join(str(raw or "").split()).casefold()
    return text.strip(_PUNCT_STRIP + " ")


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^0-9a-z]+", value) if token}


def _defect_kind(category: str, title: str, text: str) -> str:
    """Deterministic `defect_kind` over (category, title+text) — no LLM input."""
    normalized_category = _od3(category)
    content = f"{_od3(title)} {_od3(text)}"
    for categories, phrases, kind in _KIND_SEED:
        if normalized_category in categories:
            if any(phrase in content for phrase in phrases):
                return kind
    return "generic"


def _chain_by_tx(chain_entries: list[dict] | None) -> dict[str, dict]:
    """tx_id -> chain entry facts the identity keys may attribute-project."""
    chain: dict[str, dict] = {}
    for entry in chain_entries or []:
        if not isinstance(entry, dict):
            continue
        tx_id = entry.get("tx_id") or (entry.get("documented_transaction") or {}).get("tx_id")
        if not isinstance(tx_id, str) or not tx_id:
            continue
        transaction = entry.get("documented_transaction") or {}
        position = entry.get("chain_position")
        if isinstance(position, bool) or not isinstance(position, int):
            position = transaction.get("sequence")
        chain[tx_id] = {
            "transaction": transaction if isinstance(transaction, dict) else {},
            "position": position if isinstance(position, int) and not isinstance(position, bool) else None,
        }
    return chain


def _candidate_bundle(candidate: dict, chain_by_tx: dict[str, dict]) -> dict:
    """Attribute projection of one candidate over its source transactions.

    Missing transactions mean missing attributes (honest data absence, never a
    fallback) — the bundle records the gap via ``missing_tx``. Values are
    pooled over every source transaction; aggregates collapse only when every
    observed value agrees (compound evidence is a conflict, not a pick).
    """
    roles: dict[str, set[str]] = {}
    claims: set[str] = set()
    positions: set[int] = set()
    instruments: set[str] = set()
    offices: set[str] = set()
    missing_tx = False
    tx_ids = sorted({str(source.get("tx_id") or "") for source in candidate.get("sources") or []})
    for tx_id in tx_ids:
        facts = chain_by_tx.get(tx_id)
        if facts is None:
            missing_tx = True
            continue
        transaction = facts.get("transaction") or {}
        position = facts.get("position")
        if isinstance(position, int):
            positions.add(position)
        for name in (transaction.get("transferors") or []):
            value = _od3(name if not isinstance(name, dict) else name.get("name"))
            if value:
                roles.setdefault(value, set()).add("transferor")
        for name in (transaction.get("transferees") or []):
            value = _od3(name if not isinstance(name, dict) else name.get("name"))
            if value:
                roles.setdefault(value, set()).add("transferee")
        parent = _od3(transaction.get("parent_survey_number"))
        if parent:
            claims.add(parent)
        for up_id in (transaction.get("upstream_tx_ids") or []):
            parent_facts = chain_by_tx.get(str(up_id))
            if parent_facts:
                for field in _PARCEL_FIELDS:
                    token = _od3(parent_facts["transaction"].get(field))
                    if token:
                        claims.add(token)
        for field in _PARCEL_FIELDS:
            token = _od3(transaction.get(field))
            if token:
                claims.add(token)
                if "/" in token:
                    claims.add(token.rsplit("/", 1)[0])
        instrument = _od3(transaction.get("transaction_number"))
        if instrument:
            instruments.add(instrument)
        office = _od3(transaction.get("registration_office"))
        if office:
            offices.add(office)
    return {
        "category": _od3(candidate.get("category")),
        "kind": _defect_kind(candidate.get("category") or "", candidate.get("title") or "",
                             candidate.get("text") or ""),
        "title": _od3(candidate.get("title")),
        "text": _od3(candidate.get("text")),
        "parcels": sorted({token for tx_id in tx_ids
                           if (facts := chain_by_tx.get(tx_id))
                           for field in _PARCEL_FIELDS
                           if (token := _od3(facts["transaction"].get(field)))}),
        "instruments": sorted(instruments),
        "offices": sorted(offices),
        "roles": roles,
        "claims": claims,
        "polarity": bool(candidate.get("is_legal_defect")),
        "positions": sorted(positions),
        "missing_tx": missing_tx,
    }


def _single(values: set[str] | list[str]) -> str:
    """The pooled slot value: one observed value, or empty when absent."""
    unique = sorted(set(values))
    return unique[0] if len(unique) == 1 else ""


def _components(tokens: list[str]) -> list[list[str]]:
    """Identifier-related connected components over a token list."""
    remaining = list(tokens)
    parts: list[list[str]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        rest = []
        for token in remaining:
            (group if _identifier_related(seed, token) else rest).append(token)
        remaining = rest
        parts.append(group)
    return parts


def _role_review(models: list[dict]) -> tuple[bool, list[str], list[str], bool]:
    """(conflicting, humanized, supporting, missing) over pooled party roles.

    Agreeing roles across two or more members are supporting evidence; opposing
    roles for one party are an exclusionary conflict; no role data at all is a
    missing attribute, never positive evidence.
    """
    conflicts: list[str] = []
    supporting: list[str] = []
    names: dict[str, dict[str, set[int]]] = {}
    missing = False
    for member_index, member in enumerate(models):
        if not member["roles"]:
            missing = True
        for name, role_values in member["roles"].items():
            for role in role_values:
                names.setdefault(name, {}).setdefault(role, set()).add(member_index)
    for name, role_map in names.items():
        if "transferor" in role_map and "transferee" in role_map:
            conflicts.append(f"party {name} opposes transferor/transferee")
        else:
            role = next(iter(role_map))
            if len(role_map[role]) >= 2:
                supporting.append(f"party_roles:{name}:{role}")
    return bool(conflicts), conflicts, supporting, missing


def _parse_prior_key(value) -> dict | None:
    """Split a persisted identity key into its slots (A/B structured; M opaque)."""
    if not isinstance(value, str) or not value:
        return None
    spots = value.split("|")
    if spots[0] == "A" and len(spots) == 6:
        return {"tier": "A", "category": spots[1], "kind": spots[2],
                "parcel": spots[3], "instrument": spots[4], "office": spots[5]}
    if spots[0] == "B" and len(spots) == 4:
        return {"tier": "B", "category": spots[1], "kind": spots[2], "title": spots[3]}
    if spots[0] == "M" and len(spots) == 2:
        return {"tier": "M", "hash": spots[1]}
    return None  # foreign or malformed key text — never attributed meaning


def _solo_key(model: dict) -> tuple[str, list[str], list[str]]:
    """One member's own tier key (A anchored / B textual), with missing slots
    and single-member conflicts. Root election over the member's OWN parcel
    tokens and embedded parent paths only (§5.1 R3 for one member's key)."""
    category, kind = model["category"], model["kind"]
    missing: list[str] = []
    conflicts: list[str] = []
    if model["parcels"] or model["instruments"] or model["offices"]:
        parts = _components(model["parcels"])
        roots = {token for token in model["parcels"]}
        for token in model["parcels"]:
            if "/" in token:
                roots.add(token.rsplit("/", 1)[0])
        root = ""
        if len(parts) > 1:
            conflicts.append("parcels")  # unrelated clusters inside one member
        elif roots:
            root = min(roots)
        if not root:
            missing.append("parcel_anchor")
        instrument = _single(model["instruments"])
        office = _single(model["offices"])
        if len(model["instruments"]) > 1:
            conflicts.append("instrument")
        elif not instrument:
            missing.append("instrument_number")
        if len(model["offices"]) > 1:
            conflicts.append("office")
        elif not office:
            missing.append("registration_office")
        key = f"A|{category}|{kind}|{root or '-'}|{instrument or '-'}|{office or '-'}"
        return key, missing, conflicts
    # No anchor at all: textual key, even for generic kinds (W7 — never merged on it).
    missing = ["parcel_anchor", "instrument_number"]
    return f"B|{category}|{kind}|{model['title']}", missing, conflicts


def _notch(base: str, steps: int) -> str:
    ladder = ["HIGH", "MEDIUM", "LOW"]
    try:
        index = ladder.index(base)
    except ValueError:
        return "LOW"
    return ladder[min(len(ladder) - 1, index + max(0, steps))]


def _merge_verdict(members: list[dict]) -> dict:
    """Per-draft group identity: single implementation of the §4 compatibility
    floor plus the ordered tier evaluation (A-Parcel root evidence §5.1 →
    A-Instrument → B-Textual). A refused tier falls to the next; exclusionary
    conflicts block every tier, so they also block every tier-C proposal."""
    verdict = {"merge": False, "tier": "", "key": "", "basis": "",
               "confidence": "LOW", "missing": [], "supporting": [],
               "conflicts": [], "lineage": None, "detail": ""}
    if len(members) < 2:
        return verdict
    verdict["group"] = {
        "category": members[0]["category"],
        "kind": members[0]["kind"],
        "parcels": sorted({token for member in members for token in member["parcels"]}),
        "instruments": sorted({value for member in members for value in member["instruments"]}),
        "offices": sorted({value for member in members for value in member["offices"]}),
        "roles": {},
    }
    for member in members:
        for name, role_values in member["roles"].items():
            verdict["group"]["roles"].setdefault(name, set()).update(role_values)

    def flag(reason: str, text: str = "") -> None:
        if reason not in verdict["conflicts"]:
            verdict["conflicts"].append(reason)
        if text and text not in verdict["detail"]:
            verdict["detail"] = (verdict["detail"] + ("; " if verdict["detail"] else "") + text)

    categories = {member["category"] for member in members}
    kinds = {member["kind"] for member in members}
    if len(categories) > 1:
        flag("category", "different categories")
    if len(kinds) > 1:
        flag("kind", "different defect kinds")
    if kinds == {"generic"}:
        flag("generic", "generic kind never merges")
    if len({member["polarity"] for member in members}) > 1:
        flag("polarity", "mixed is_legal_defect polarity")
    role_conflicting, role_text, supporting, roles_missing = _role_review(members)
    if role_conflicting:
        flag("roles", "; ".join(role_text))
    for member in members:
        if len(member["instruments"]) > 1:
            flag("instrument", f"multiple instruments observed for one member ({member['instruments']})")
        if len(member["offices"]) > 1:
            flag("office", f"multiple offices observed for one member ({member['offices']})")
    if verdict["conflicts"]:
        return verdict

    pooled_parcels: list[str] = []
    for member in members:
        for token in member["parcels"]:
            if token not in pooled_parcels:
                pooled_parcels.append(token)
    pooled_instruments: set[str] = set()
    pooled_offices: set[str] = set()
    for member in members:
        pooled_instruments.update(member["instruments"])
        pooled_offices.update(member["offices"])
    complete_instrument = len(pooled_instruments) == 1 and all(len(m["instruments"]) == 1 for m in members)
    complete_office = len(pooled_offices) == 1 and all(len(m["offices"]) == 1 for m in members)
    if len(pooled_instruments) > 1:
        flag("instrument", "different instruments both present")
    elif len(pooled_offices) > 1 and complete_instrument:
        flag("office", "equal instrument at different offices")
    if verdict["conflicts"]:
        return verdict

    def one_sided_tags() -> tuple[list[str], int]:
        """(missing flags, notch count) — pooled absence is flagged, one-sided
        absence is flagged and lowers the tier-A notch (§4.4)."""
        tags: list[str] = []
        steps = 0
        instrument = _single(pooled_instruments)
        office = _single(pooled_offices)
        for value, pool, tag in ((instrument, pooled_instruments, "instrument_number"),
                                 (office, pooled_offices, "registration_office")):
            if not value:
                if pool:
                    steps += 1
                tags.append(tag)
        if roles_missing:
            tags.append("party_roles")
            steps += 1
        return tags, steps

    if pooled_parcels:
        if len(_components(pooled_parcels)) > 1:
            flag("parcels", "unrelated parcel clusters present on both sides")
            return verdict
        claims_overlap: set[str] | None = None
        any_claims = False
        for member in members:
            claims = set(member["claims"])
            claims_overlap = claims if claims_overlap is None else (claims_overlap & claims)
            any_claims = any_claims or bool(claims)
        root = min(claims_overlap) if claims_overlap else ""
        if root:
            verdict["lineage"] = None
            tags, steps = one_sided_tags()
            verdict["merge"] = True
            verdict["tier"] = "A"
            verdict["basis"] = "anchors"
            verdict["key"] = (f"A|{members[0]['category']}|{members[0]['kind']}|{root}"
                              f"|{_single(pooled_instruments) or '-'}|{_single(pooled_offices) or '-'}")
            verdict["missing"] = tags
            verdict["confidence"] = _notch("HIGH", steps)
            verdict["supporting"] = supporting
            return verdict
        verdict["lineage"] = ("parcel_root_conflict" if any_claims
                              else "parcel_lineage_unresolved")
        verdict["detail"] = verdict["lineage"]

    if complete_instrument and complete_office:
        tags, steps = one_sided_tags()
        if not pooled_parcels:
            tags.append("parcel_anchor")
        verdict["merge"] = True
        verdict["tier"] = "A"
        verdict["basis"] = "anchors"
        verdict["key"] = (f"A|{members[0]['category']}|{members[0]['kind']}|-"
                          f"|{_single(pooled_instruments)}|{_single(pooled_offices)}")
        verdict["missing"] = sorted(set(tags))
        verdict["confidence"] = _notch("HIGH", steps)
        verdict["supporting"] = supporting
        return verdict

    if not pooled_parcels and not pooled_instruments and members[0]["kind"] != "generic":
        titles = {member["title"] for member in members}
        if len(titles) == 1:
            verdict["merge"] = True
            verdict["tier"] = "B"
            verdict["basis"] = "textual"
            verdict["key"] = f"B|{members[0]['category']}|{members[0]['kind']}|{members[0]['title']}"
            verdict["missing"] = (["party_roles"] if roles_missing else [])
            verdict["confidence"] = _notch("MEDIUM", 1 if roles_missing else 0)
            verdict["supporting"] = supporting
            return verdict
        verdict["detail"] = (verdict["detail"] + ("; " if verdict["detail"] else "")
                             + "titles drift beyond exact-normalized equality")
    elif not verdict["detail"]:
        verdict["detail"] = "no establishing anchor"
    return verdict


# -- C2 §6: D1 re-sort, prior validation, provenance ordering, phase R ----------


def _d1_reorder(results: list[dict]) -> list[dict]:
    """D1 (approved): a defensive ``(sequence, tx_id)`` re-sort right after the
    strict persisted read — the stored list order is not a repository
    guarantee. Real positive sequences first (ascending, then tx_id), rows
    without a derivable sequence next, any non-dict row keeps its relative
    order at the end so `_row_problem` stays the sole classifier (C1)."""
    def key(pair):
        index, row = pair
        if not isinstance(row, dict):
            return (2, 0, "", index)
        sequence = _row_sequence(row)
        tx_id = str(row.get("tx_id") or "")
        if sequence > 0:
            return (0, sequence, tx_id, index)
        return (1, 0, tx_id, index)

    return [row for _index, row in sorted(enumerate(results), key=key)]


def _observed_tuple(observation: object, tx_by_id: dict[str, dict]) -> tuple | None:
    """§6-R2 ordering tuple for one persisted observation: (tx_sequence, tx_id,
    tf_id, doc_id, pages) — tx_sequence join-derived, references in persisted
    string form; any undervivable component makes the observation unorderable."""
    if not isinstance(observation, dict):
        return None
    tf_id = str(observation.get("tf_id") or "")
    if not tf_id or not re.fullmatch(TX_FINDING_ID_RE, tf_id):
        return None
    tx_id = str(observation.get("tx_id") or "")
    row = tx_by_id.get(tx_id)
    if row is None:
        return None  # (a) transaction row absent from the dossier map
    sequence = _row_sequence(row)
    if sequence <= 0:
        return None  # (d) tuple component not derivable/validatable
    pairs = []
    for ref in observation.get("evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        doc_id = str(ref.get("doc_id") or "")
        if not doc_id:
            continue
        pairs.append((doc_id, str(ref.get("pages") or "")))
    if not pairs:
        return None  # (b) no usable evidence reference
    doc_id, pages = min(pairs)
    return (sequence, tx_id, tf_id, doc_id, pages)


def _prior_ordering(prior: dict, tx_by_id: dict[str, dict]) -> list | None:
    """Sorted observation-tuple collection, invariant to stored array order;
    None when the claimant has no derivable canonical ordering tuple."""
    observations = prior.get("source_observations")
    if not isinstance(observations, list) or not observations:
        return None  # v1 / pre-provenance prior: unorderable by design
    tuples: list[tuple] = []
    for observation in observations:
        component = _observed_tuple(observation, tx_by_id)
        if component is None:
            return None  # any unorderable observation ⇒ claimant unorderable
        tuples.append(component)
    return sorted(tuples)


def _prior_dedup_keys(prior: dict) -> list[str] | None:
    keys = (prior.get("consolidation") or {}).get("dedup_keys") if isinstance(prior.get("consolidation"), dict) else None
    if isinstance(keys, list) and keys and all(isinstance(item, str) for item in keys):
        return keys
    return None


def _prior_entry_problem(prior: dict) -> str | None:
    """Entry-intrinsic invalidity (§9 readable-invalid + Rev 6/F8): a junk PF id
    or non-string identity metadata never enters any registry and never counts."""
    finding_id = prior.get("finding_id")
    if not isinstance(finding_id, str) or not re.fullmatch(r"PF-\d{3}", finding_id):
        return f"prior finding id missing or malformed ({finding_id!r})"
    identity_key = prior.get("identity_key")
    if identity_key is not None and not isinstance(identity_key, str):
        return "prior identity metadata is not a usable string"
    if identity_key is not None and _parse_prior_key(identity_key) is None:
        return f"prior identity key {identity_key!r} does not match any documented tier shape"
    if _prior_dedup_keys(prior) is None:
        keys = (prior.get("consolidation") or {}).get("dedup_keys")
        if isinstance(keys, list) and keys and not all(isinstance(item, str) for item in keys):
            return "prior dedup_keys carry non-string entries"  # unreadable identity metadata
    return None


def _prior_terminal(prior: dict) -> bool:
    if str(prior.get("status") or "") != "SUPERSEDED":
        return False
    return str(prior.get("superseede_reason") or "").startswith(("merged_into:", "split_replaced"))


def _phase_r(prior_findings: list[dict], tx_by_id: dict[str, dict], registration: dict) -> dict:
    """Run-global duplicate registries (§6 phase R), built exactly once before
    candidate-group processing. Returns population, exclusion set, terminal
    victims retained verbatim, per-mechanism collision records, and the fresh
    counter base. Warns with the reconciliation orientation (skip+warn, F4)."""
    identity_reg: dict[str, list[dict]] = {}
    legacy_reg: dict[frozenset[str], list[dict]] = {}
    pf_id_reg: dict[str, list[dict]] = {}
    population: list[dict] = []
    terminal: list[dict] = []
    counter_base = 0
    prior_ids: set[str] = set()
    for index, prior in enumerate(prior_findings):
        if not isinstance(prior, dict):
            registration.setdefault("reconciliation_warnings", []).append(
                f"prior entry #{index} skipped: not an object"
            )
            continue
        finding_id = str(prior.get("finding_id") or "")
        prior_ids.add(finding_id)
        if _prior_terminal(prior):
            terminal.append(prior)
            continue  # terminal victims are retained verbatim, never carried
        issue = _prior_entry_problem(prior)
        if issue:
            registration.setdefault("reconciliation_warnings", []).append(
                f"prior finding #{index} ({finding_id or 'no id'}) skipped: {issue}"
            )
            continue
        population.append(prior)
        number = int(finding_id.removeprefix("PF-"))
        counter_base = max(counter_base, number)
        identity_key = prior.get("identity_key")
        if identity_key:
            identity_reg.setdefault(str(identity_key), []).append(prior)
        dedup_keys = _prior_dedup_keys(prior)
        if dedup_keys:
            legacy_reg.setdefault(frozenset(dedup_keys), []).append(prior)
        pf_id_reg.setdefault(finding_id, []).append(prior)

    excluded: set[int] = set()  # object ids of run-globally excluded priors
    records: list[tuple[str, str, dict | None, list[dict]]] = []
    for mechanism, registry, key_text in (
        ("identity_key", identity_reg, lambda key: str(key)),
        ("legacy_dedup_keys", legacy_reg, lambda key: "|".join(sorted(key))),
        ("pf_id", pf_id_reg, lambda key: str(key)),
    ):
        for key, claimants in sorted(registry.items(), key=lambda item: str(item[0])):
            if len(claimants) < 2:
                continue
            collections = [_prior_ordering(claimant, tx_by_id) for claimant in claimants]
            if any(collection is None for collection in collections) or len({tuple(map(str, item)) for item in collections if item}) < len(claimants):
                for claimant in claimants:
                    excluded.add(id(claimant))
                records.append((mechanism, key_text(key), None, list(claimants)))
                continue
            ordered = sorted(zip(claimants, collections), key=lambda pair: pair[1])
            winner, losers = ordered[0][0], ordered[1:]
            for loser in losers:
                excluded.add(id(loser[0]))
            records.append((mechanism, key_text(key), winner, [loser[0] for loser in losers]))
    return {
        "population": population,
        "excluded": excluded,
        "terminal": terminal,
        "records": records,
        "counter_base": counter_base,
        "prior_ids": prior_ids,
        "identity_reg": identity_reg,
        "legacy_reg": legacy_reg,
        "pf_id_reg": pf_id_reg,
    }


def _compat_gate(group: dict, prior: dict, prior_key: dict) -> tuple[bool, list[str]]:
    """The §6 step-0 compatibility floor, evaluated per (group, prior) pair on
    realized attributes only — key equality is a signal, never an override."""
    reasons: list[str] = []

    def refuse(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if prior_key is None:
        return False, ["unreadable_identity"]
    if prior_key["tier"] == "M":
        return True, []  # model-merge identity: only exact key equality decides
    if prior_key["tier"] == "A":
        prior_parcels = [prior_key["parcel"]] if prior_key["parcel"] and prior_key["parcel"] != "-" else []
        prior_instruments = [prior_key["instrument"]] if prior_key["instrument"] and prior_key["instrument"] != "-" else []
        prior_offices = [prior_key["office"]] if prior_key["office"] and prior_key["office"] != "-" else []
    else:  # B: no anchoring slots are realized
        prior_parcels, prior_instruments, prior_offices = [], [], []
    if prior_key["category"] and group["category"] and prior_key["category"] != group["category"]:
        refuse("category")
    if prior_key["kind"] and group["kind"] and prior_key["kind"] != group["kind"]:
        refuse("kind")
    # No separate generic clause here: rule 1 exact identity-key equality is not
    # a fuzzy merge, so a prior whose realized kind is generic still carries;
    # `generic` refusal applies to merges and tier-C proposals (W7).
    group_parcels = [slot for slot in group["parcels"] if slot]
    group_instruments = [slot for slot in group["instruments"] if slot]
    group_offices = [slot for slot in group["offices"] if slot]
    if prior_parcels and group_parcels and not (
        any(_identifier_related(a, b) for a in prior_parcels for b in group_parcels)
    ):
        refuse("parcels")
    if prior_instruments and group_instruments and set(prior_instruments) != set(group_instruments):
        refuse("instrument")
    if (prior_instruments and group_instruments and set(prior_instruments) == set(group_instruments)
            and prior_offices and group_offices and set(prior_offices) != set(group_offices)):
        refuse("office")
    group_roles = group.get("roles") or {}
    prior_roles: dict[str, str] = {}
    for entry in prior.get("identity_supporting") or []:
        parts = str(entry).split(":")
        if len(parts) == 3 and parts[0] == "party_roles":
            prior_roles[parts[1]] = parts[2]
    for name, role_values in group_roles.items():
        prior_role = prior_roles.get(name)
        if prior_role and role_values:
            if "transferor" in prior_role and "transferee" in role_values:
                refuse("roles")
            elif "transferee" in prior_role and "transferor" in role_values:
                refuse("roles")
    return not reasons, reasons




def _token_overlap_ok(models: list[dict]) -> bool:
    """Tier-C check 7: every member's title tokens share at least one third of
    themselves with the other members' normalized title+text tokens."""
    full_tokens = [(_tokens(model["title"] or ""), _tokens(model["title"] or "") | _tokens(model["text"] or ""))
                   for model in models]
    for index, (title_tokens, own_content) in enumerate(full_tokens):
        baseline = title_tokens or (_tokens(models[index]["text"] or ""))
        others: set[str] = set()
        for other_index, (_t, content) in enumerate(full_tokens):
            if other_index != index:
                others |= content
        if not baseline:
            return False
        if len(baseline & others) * 3 < len(baseline):
            return False
    return True


def _tier_c_review(members: list[dict], contradicted_indexes: set[int],
                   candidate_indexes: list[int]) -> tuple[dict | None, str]:
    """§4.6: validate one model proposal against the seven checks. Returns
    (accepted dict | None, failed-check rationale). None of the checks is
    waivable; LLM output is proposal-only."""
    base = _merge_verdict(members)
    if base["conflicts"]:
        mapping = {"category": "check 1 (same category)", "kind": "check 2 (no exclusionary conflict)",
                   "generic": "check 2 (no exclusionary conflict; generic never merges)",
                   "polarity": "check 4 (consistent legal polarity)",
                   "roles": "check 3 (party-role compatibility)",
                   "instrument": "check 2 (no exclusionary conflict: instruments)",
                   "office": "check 2 (no exclusionary conflict: equal instrument/different office)",
                   "parcels": "check 2 (no exclusionary conflict: unrelated parcel clusters)"}
        conflict = base["conflicts"][0]
        return None, f"tier-C proposal rejected: {mapping.get(conflict, conflict)} ({base['detail'] or conflict})"
    supporting = list(base["supporting"])
    all_positions = sorted({p for member in members for p in member["positions"]})
    if any(b == a + 1 for a, b in zip(all_positions, all_positions[1:])):
        supporting.append("chain adjacency")
    if not supporting:
        return None, "tier-C proposal rejected: check 5 (no supporting-agreement signal: no party-role agreement, no chain adjacency, no affected_parties overlap)"
    overlap = set(candidate_indexes) & contradicted_indexes
    if overlap:
        return None, (f"tier-C proposal rejected: check 6 (a contradiction record involves the proposed candidates "
                      f"{sorted(overlap)}; a contradicted pair is never silently unified)")
    if not _token_overlap_ok(members):
        return None, "tier-C proposal rejected: check 7 (normalized title/text token overlap below one third)"
    key = "M|" + content_hash(sorted(_solo_key(member)[0] for member in members))
    return {
        "key": key,
        "basis": "model_merge",
        "confidence": "LOW",
        "missing": base["missing"],
        "supporting": supporting,
        "conflicts": [],
        "lineage": base["lineage"],
        "detail": "",
        "group": base.get("group"),
    }, ""


def _open_requirements(case_id: str) -> list[dict]:
    rows = repo.list_requirements(case_id, status="OPEN")
    return [
        {
            "requirement_id": row.get("requirement_id"),
            "owner_tx_id": row.get("owner_tx_id"),
            "document_type": row.get("document_type"),
        }
        for row in rows
    ]


def _phase_a_state(case_id: str) -> str | None:
    phase_a = repo.get_agent_result(case_id) or {}
    return str(phase_a.get("phase_a_hash") or "") or compute_phase_a_hash(phase_a) or None


def _ask_review(
    affected_tx_ids, all_requirements: list[dict], owned_doc_ids: set[str] | None,
) -> tuple[list[str], list[str], list[str]]:
    """§6.2 ask review over one finding's affected transactions.

    Asks are the ledger rows owned by an affected transaction (WITHDRAWN rows
    are dropped); a resolved ask is SATISFIED **with** a roster-validated
    ``matched_doc_id`` — satisfaction alone never resolves (§6.3-5). Returns
    ``(resolved ids, outstanding ids, validated matched doc ids)``."""
    tx_ids = {str(tx) for tx in affected_tx_ids}
    resolved: list[str] = []
    outstanding: list[str] = []
    matched_docs: set[str] = set()
    for row in all_requirements or []:
        owner = str(row.get("owner_tx_id") or "")
        requirement_id = str(row.get("requirement_id") or "")
        status = str(row.get("status") or "OPEN")  # legacy rows may omit status
        if owner not in tx_ids or status == "WITHDRAWN":
            continue
        matched = str(row.get("matched_doc_id") or "")
        validated = bool(matched) and (owned_doc_ids is None or matched in owned_doc_ids)
        if status == "SATISFIED" and validated:
            resolved.append(requirement_id)
            matched_docs.add(matched)
        else:
            outstanding.append(requirement_id)
    return (sorted(i for i in resolved if i),
            sorted(i for i in outstanding if i),
            sorted(i for i in matched_docs if i))


def _is_terminal(row: dict, documents: list[dict] | None = None) -> bool:
    """The one shared terminal-state rule (agent_repo); never guessed locally."""
    return repo.is_terminal_transaction_result(row, documents)


def _unverified_predecessors(
    chain_by_tx: dict[str, dict], tx_map: dict[str, dict], documents=None,
) -> set[str]:
    """§5.1-8/§7.2: upstream tx ids referenced by chain transactions that are
    not resident-and-terminal in this run's inputs."""
    unverified: set[str] = set()
    for facts in chain_by_tx.values():
        for up in (facts.get("transaction") or {}).get("upstream_tx_ids") or []:
            up_id = str(up)
            row = tx_map.get(up_id)
            if row is None or not _is_terminal(row, documents):
                unverified.add(up_id)
    return unverified


def _readiness_fields(
    rows: list[dict], chain_entries: list[dict], open_requirement_ids,
    registration: dict, documents=None,
) -> dict:
    """§7.2 readiness collectors over the strict read + chain cross-reference.

    ``pending`` = rows whose normalized status is PENDING_NOT_VERIFIED, ``skipped``
    = chain positions not covered by row sequences, ``unverified`` = non-terminal
    rows via the shared terminal rule; any hit — or OPEN requirement ids,
    malformed observations, or excluded evidence refs — makes the state
    PARTIAL. Since C4, partial mode is real: a PENDING/INCOMPLETE run always
    reports PARTIAL and the gate defers id-retiring transitions."""
    tx_map = {str(row.get("tx_id")): row for row in rows if row.get("tx_id")}
    pending = sorted({
        tx for tx, row in tx_map.items()
        if normalize_status(row.get("status")) == "PENDING_NOT_VERIFIED"
    })
    covered = {seq for seq in (_row_sequence(row) for row in rows) if seq > 0}
    chain = _chain_by_tx(chain_entries)
    skipped = sorted({
        tx_id for tx_id, facts in chain.items()
        if isinstance(facts.get("position"), int)
        and facts["position"] not in covered
    })
    unverified = sorted({
        tx for tx, row in tx_map.items() if not _is_terminal(row, documents)
    })
    open_ids = sorted({str(rid) for rid in (open_requirement_ids or []) if str(rid)})
    partial = any((pending, skipped, unverified, open_ids,
                   registration.get("malformed_observations") or [],
                   registration.get("excluded_evidence_refs") or []))
    return {
        "state": "PARTIAL" if partial else "COMPLETE",
        "pending_tx_ids": pending,
        "skipped_tx_ids": skipped,
        "unverified_tx_ids": unverified,
        "open_requirement_ids": open_ids,
    }


def _container_blocks(
    *,
    rows: list[dict],
    chain_entries: list[dict],
    registration: dict,
    all_requirements: list[dict],
    phase_a_hash: str | None,
    input_hash: str,
    readiness: dict,
    documents=None,
) -> dict:
    """§8.1 coverage/integrity/readiness blocks, materialized on every ok run."""
    chain_length = len(chain_entries or [])
    digest = RequirementsDigest(
        open=sum(1 for r in all_requirements if str(r.get("status") or "OPEN") == "OPEN"),
        satisfied=sum(1 for r in all_requirements if r.get("status") == "SATISFIED"),
        withdrawn=sum(1 for r in all_requirements if r.get("status") == "WITHDRAWN"),
    )
    disclosures = list(registration.get("disclosures") or [])
    if registration.get("prior_container_unreadable"):
        disclosures.append(
            f"prior_container_unreadable: {registration['prior_container_unreadable']}")
    if registration.get("unassigned_candidates"):
        disclosures.append(
            f"unassigned_candidates: {json.dumps(registration['unassigned_candidates'], ensure_ascii=False, default=str)} left unassigned by the model pass")
    return {
        "coverage": Coverage(
            phase_a_hash=phase_a_hash,
            dossiers=[
                CoverageDossier(
                    tx_id=str(row.get("tx_id")),
                    revision=int(row.get("revision") or 0),
                    status=normalize_status(row.get("status")),
                    terminal=_is_terminal(row, documents),
                )
                for row in rows if row.get("tx_id")
            ],
            requirements=digest,
            input_snapshot={"input_hash": input_hash, "chain_length": chain_length},
            chain_length=chain_length,
        ),
        "integrity": Integrity(
            input_state=registration.get("input_state"),
            malformed_observations=registration.get("malformed_observations") or [],
            excluded_evidence_refs=registration.get("excluded_evidence_refs") or [],
            disclosures=disclosures,
        ),
        "readiness": Readiness(**readiness),
    }


# -- §8.2 currentness hash: the I0–I7/I9 external input groups -----------------
# I8 (prior lifecycle carry set) is deliberately never hashed: hashing it
# would make the first rerun after an ok run miss the cache (§8.2 I8).

INPUT_HASH_VERSION = 3  # I0: bump to invalidate semantics deliberately
_CORRELATION_TYPES = sorted(("RELATED", "DEPENDS_ON", "CONFLICTS_WITH",
                             "MERGED_INTO", "SPLIT_FROM"))


def _i0_bundle() -> dict:
    """Contract identity: versions and the literal enum member lists."""
    return {
        "contract": "PHASE_C_PROPERTY_FINDING_CONSOLIDATION_REVISION_6",
        "container_version": CONTAINER_VERSION,
        "input_hash_version": INPUT_HASH_VERSION,
        "enums": {
            "finding_statuses": sorted(
                item.value for item in PropertyFindingStatus),
            "evidence_sufficiency": sorted(
                item.value for item in PropertyEvidenceSufficiency),
            "input_states": ["EMPTY", "INCOMPLETE", "PENDING", "READY"],
            "readiness_states": ["COMPLETE", "PARTIAL"],
            "correlation_types": _CORRELATION_TYPES,
        },
    }


def _i1_bundle(chain_by_tx: dict[str, dict], phase_a_hash: str | None) -> dict:
    """Phase A chain content: phase_a_hash plus per-entry attributes."""
    entries = []
    for tx_id, facts in chain_by_tx.items():
        transaction = facts.get("transaction") or {}
        entries.append({
            "tx_id": str(tx_id),
            "chain_position": facts.get("position"),
            "parcel_ids": sorted(
                str(value) for value in _parcel_fields(transaction).values()
                if str(value or "").strip()),
            "transaction_number": _od3(transaction.get("transaction_number")),
            "transferors": sorted(_names(transaction.get("transferors"))),
            "transferees": sorted(_names(transaction.get("transferees"))),
            "upstream_tx_ids": sorted(
                str(item) for item in transaction.get("upstream_tx_ids") or []),
        })
    entries.sort(key=lambda item: (
        item["chain_position"] if isinstance(item["chain_position"], int) else -1,
        item["tx_id"]))
    return {"phase_a_hash": phase_a_hash, "entries": entries}


def _i2_bundle(rows: list[dict]) -> list[dict]:
    """Transaction roster and rows (sorted by tx_id)."""
    return [
        {
            "tx_id": str(row.get("tx_id")),
            "status": normalize_status(row.get("status")),
            "revision": int(row.get("revision") or 0),
            "verified_at": str(row.get("verified_at") or ""),
            "effectivity_status": str(row.get("effectivity_status") or ""),
            "evidence_status": str(row.get("evidence_status") or ""),
            "checkpoint": str(
                ((row.get("transaction_metadata") or {})
                 .get("_verification_checkpoint")) or ""),
            "upstream_dependencies": sorted(
                str(item) for item in row.get("upstream_dependencies") or []),
        }
        for row in sorted(
            (row for row in rows if row.get("tx_id")),
            key=lambda item: str(item.get("tx_id")))
    ]


def _i3_bundle(rows: list[dict]) -> list[dict]:
    """Structured findings per tx (sorted by (tx_id, finding_id)) — the
    sanitized view only: excluded junk is not consolidation input."""
    items = []
    for row in rows:
        for finding in row.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            items.append({
                "tx_id": str(row.get("tx_id") or ""),
                "finding_id": str(finding.get("finding_id") or ""),
                "category": str(finding.get("category") or ""),
                "title": str(finding.get("title") or ""),
                "text": str(finding.get("text") or ""),
                "significance": str(finding.get("significance") or ""),
                "severity": str(finding.get("severity") or ""),
                "confidence": str(finding.get("confidence") or ""),
                "is_legal_defect": bool(finding.get("is_legal_defect")),
                "affected_parties": sorted(
                    str(item) for item in finding.get("affected_parties") or []),
                "evidence_refs": sorted(
                    (str(ref.get("doc_id") or ""), str(ref.get("pages") or ""),
                     str(ref.get("passage") or ""), str(ref.get("evidence_type") or ""))
                    for ref in finding.get("evidence") or []
                    if isinstance(ref, dict)),
                "evidence_gaps": sorted(
                    str(item) for item in finding.get("evidence_gaps") or []),
                "resolution_refs": sorted(
                    (str(ref.get("doc_id") or ""), str(ref.get("pages") or ""))
                    for ref in finding.get("resolution_evidence") or []
                    if isinstance(ref, dict)),
            })
    return sorted(
        items,
        key=lambda item: (item["tx_id"], item["finding_id"], item["title"]))


def _i4_bundle(rows: list[dict]) -> list[dict]:
    """Contradictory evidence per tx: refs as (doc_id, pages, evidence_type)."""
    return sorted(
        (
            {
                "tx_id": str(row.get("tx_id") or ""),
                "refs": sorted(
                    (str(ref.get("doc_id") or ""), str(ref.get("pages") or ""),
                     str(ref.get("evidence_type") or ""))
                    for ref in row.get("contradictory_evidence") or []
                    if isinstance(ref, dict)),
            }
            for row in rows
            if row.get("tx_id") and row.get("contradictory_evidence") is not None
        ),
        key=lambda item: item["tx_id"])


def _i5_bundle(all_requirements: list[dict]) -> list[dict]:
    """Requirements ledger, all states (sorted by requirement_id)."""
    return sorted(
        (
            {
                "requirement_id": str(row.get("requirement_id") or ""),
                "status": str(row.get("status") or ""),
                "owner_tx_id": str(row.get("owner_tx_id") or ""),
                "document_type": str(row.get("document_type") or ""),
                "content_key": list(repo.requirement_content_key(
                    row.get("owner_tx_id"), row.get("document_type"),
                    row.get("reason"))),
            }
            for row in (all_requirements or [])
        ),
        key=lambda item: item["requirement_id"])


def _i6_bundle(documents: list[dict]) -> list[list[str]]:
    """Document roster: sorted (doc_id, status) pairs."""
    return sorted(
        [str(doc.get("doc_id") or ""), str(doc.get("status") or "")]
        for doc in (documents or []) if doc.get("doc_id"))


def _i7_bundle() -> dict:
    """LLM stage identity: task, backed model/provider, prompt-file hash."""
    return {
        "task": "agent_consolidation",
        "model": str(os.environ.get("CLEARTITLE_AGENT_MODEL", "")),
        "provider": str(os.environ.get("CLEARTITLE_AGENT_PROVIDER", "")),
        "prompt_hash": content_hash(load_prompt("findings_consolidation")),
    }


def _external_input_hash(
    *,
    case_id: str,
    chain_by_tx: dict[str, dict],
    phase_a_hash: str | None,
    rows: list[dict],
    documents: list[dict],
    all_requirements: list[dict],
) -> str:
    """content hash over I0–I7 + I9 exactly; nothing derived, no I8 carry (§8.2)."""
    return content_hash({
        "I0": _i0_bundle(),
        "I1": _i1_bundle(chain_by_tx, phase_a_hash),
        "I2": _i2_bundle(rows),
        "I3": _i3_bundle(rows),
        "I4": _i4_bundle(rows),
        "I5": _i5_bundle(all_requirements),
        "I6": _i6_bundle(documents),
        "I7": _i7_bundle(),
        "I9": case_id,
    })


def _candidate_block(candidates: list[dict]) -> str:
    compact = [
        {
            "index": index,
            "tx_ids": candidate["tx_ids"],
            "sources": candidate["sources"],
            "significance": candidate["significance"],
            "category": candidate["category"],
            "title": candidate["title"],
            "text": candidate["text"],
            "is_legal_defect": candidate["is_legal_defect"],
            "evidence": candidate["evidence"],
        }
        for index, candidate in enumerate(candidates)
    ]
    block = json.dumps(compact, ensure_ascii=False, default=str, indent=2)
    if len(block) > _PROMPT_BUDGET_CHARS:
        logger.warning(
            "phase C prompt budget exceeded: %s chars (limit %s) — findings-only "
            "payload as designed, but the model window may truncate",
            len(block), _PROMPT_BUDGET_CHARS,
        )
    return block


def _build_prompt(candidates: list[dict], open_requirements: list[dict]) -> str:
    return (
        load_prompt("findings_consolidation")
        + "\n\nCANDIDATE FINDINGS (indexes are stable for this call):\n"
        + _candidate_block(candidates)
        + "\n\nOPEN EVIDENCE REQUIREMENTS (pending evidence asks):\n"
        + json.dumps(open_requirements, ensure_ascii=False, default=str)
    )


def _gap_labels(members: list[dict], open_requirements: list[dict], draft,
                upstream_unverified: dict[str, list[str]] | None = None) -> list[str]:
    """Deterministic evidence gaps: model entries plus the affected
    transactions' own OPEN requirement labels and unverified-predecessor
    labels (§5.1-8) — missing evidence is labeled, never a defect."""
    labels = {str(item or "").strip() for item in (draft.evidence_gaps or [])}
    tx_ids = {tx for member in members for tx in member["tx_ids"]}
    for requirement in open_requirements:
        if str(requirement.get("owner_tx_id")) in tx_ids:
            labels.add(f"[{requirement.get('requirement_id')}] {requirement.get('document_type')}")
    for member in members:
        for doc_id in member.get("excluded_refs") or []:
            labels.add(f"[excluded evidence ref {doc_id}: not owned by the case]")
        for tx in member["tx_ids"]:
            for upstream in (upstream_unverified or {}).get(tx) or []:
                labels.add(f"[unverified predecessor {upstream}]")
    return sorted(item for item in labels if item)


def _assemble(
    candidates: list[dict],
    drafts: ConsolidationDraftResult,
    open_requirements: list[dict],
    *,
    phase_a_hash: str | None,
    run_id: str | None,
    input_hash: str,
    prior_container: dict | None,
    tx_by_id: dict[str, dict] | None = None,
    chain_entries: list[dict] | None = None,
    registration: dict | None = None,
    now: str = "",
    all_requirements: list[dict] | None = None,
    owned_doc_ids: set[str] | None = None,
    documents: list[dict] | None = None,
    readiness_fields: dict | None = None,
) -> PropertyConsolidationResult:
    """Application assembly: identity, reconciliation, coverage, provenance.

    Revision 6 §6: phase R builds the three run-global duplicate registries
    before any candidate group is processed; drafts then go through §6-A
    validation, D5 ordering, the compatibility-gated rules 1–3 carry-forward,
    tier-C proposal validation for unverifiable merges, and conservative
    fallbacks (split on tier-C rejection, de_observed marking for vanished
    priors, refuse-all on ambiguity). The model never touches ids, statuses,
    identity, or ordering.

    C3 (§6.2/§6.3, §8.1): the lifecycle engine derives PENDING_EVIDENCE /
    PARTIALLY_RESOLVED / RESOLVED / DISPUTED from the requirement-ledger ask
    review and contradiction records (satisfaction alone never resolves),
    defers RESOLVED/SUPERSEDED and id-retiring reorganizations under the
    partial-run gate, keeps coverage_gap retention for unwarranted
    disappearances, records source_withdrawn/source_corrected, and attaches
    the coverage/integrity/readiness blocks plus the deterministic
    correlation edges (§9) to the result.

    C4 (§3.2, D2): the gate is load-bearing — partial runs are real — and no
    statuses other than the derived ones ever reach the container."""
    registration = registration if registration is not None else {}
    chain_by_tx = _chain_by_tx(chain_entries)
    tx_map = dict(tx_by_id or {})
    prior_container = prior_container or {}
    open_ids = {
        str(item.get("requirement_id")) for item in open_requirements if item.get("requirement_id")
    }
    # Full ledger rows for the ask review and digest; defaulting to the
    # (possibly missing-status) OPEN rows keeps unit calls working.
    all_rows = list(all_requirements) if all_requirements is not None else list(open_requirements)
    readiness = readiness_fields if readiness_fields is not None else _readiness_fields(
        list(tx_map.values()), chain_entries or [], open_ids, registration, documents)
    readiness_partial = readiness["state"] == "PARTIAL"
    unverified_set = set(readiness["unverified_tx_ids"]) | _unverified_predecessors(
        chain_by_tx, tx_map, documents)
    upstream_unverified: dict[str, list[str]] = {}
    for tx_id, facts in chain_by_tx.items():
        ups = sorted({str(u) for u in (facts.get("transaction") or {}).get("upstream_tx_ids") or []
                      if str(u) in unverified_set})
        if ups:
            upstream_unverified[tx_id] = ups

    phase_r = _phase_r(
        (prior_container.get("result") or {}).get("findings") or [], tx_map, registration,
    )
    excluded = phase_r["excluded"]

    def register_warning(message: str) -> None:
        registration.setdefault("reconciliation_warnings", []).append(message)

    def register_event(entry: dict) -> None:
        registration.setdefault("identity_events", []).append(entry)

    # -- §6-A pre-pass: draft integrity, at-most-once assignment -------------
    claimed_by: dict[int, int] = {}
    for draft in drafts.findings:
        if any(not (0 <= index < len(candidates)) for index in draft.members):
            raise ValueError(f"draft references unknown candidate indexes: {draft.members}")
        if len(set(draft.members)) != len(draft.members):
            duplicate = next(index for index in draft.members
                             if list(draft.members).count(index) > 1)
            raise ValueError(f"duplicate member index: #{duplicate}")
        for index in draft.members:
            if index in claimed_by:
                raise ValueError(f"draft membership conflict: candidate #{index}")
            claimed_by[index] = 1
    contradicted_indexes: set[int] = set()
    for item in drafts.contradictions:
        if any(not (0 <= index < len(candidates)) for index in item.members):
            raise ValueError(f"contradiction references unknown candidate indexes: {item.members}")
        if len([source for index in item.members for source in candidates[index]["sources"]]) < 2:
            raise ValueError("a contradiction needs at least two source sides")
        contradicted_indexes.update(item.members)
    unassigned = [index for index in range(len(candidates)) if index not in claimed_by]
    if unassigned:
        registration["unassigned_candidates"] = [
            {
                "index": index,
                "category": candidates[index].get("category"),
                "title": candidates[index].get("title"),
            }
            for index in unassigned
        ]
        logger.warning(
            "phase C candidates left unassigned by the model pass: %s",
            [item["index"] for item in registration["unassigned_candidates"]],
        )
    contradicted_indexes = {index for item in drafts.contradictions for index in item.members}

    # -- source_observations, built once per candidate (§4.8) ----------------
    def build_observations(index: int) -> list[SourceObservation]:
        items: list[SourceObservation] = []
        for source in candidates[index].get("sources") or []:
            tf_id = str(source.get("tf_id") or "")
            if not re.fullmatch(TX_FINDING_ID_RE, tf_id):
                register_warning(
                    f"candidate #{index} source {source.get('tx_id')!r} skipped from "
                    f"source_observations: TF id missing or malformed ({tf_id!r})"
                )
                continue  # never invent an identifier
            items.append(SourceObservation(
                tf_id=tf_id,
                tx_id=str(source.get("tx_id") or ""),
                title=str(source.get("title") or ""),
                text_excerpt=(str(source.get("text_excerpt") or "") or None),
                evidence_refs=[
                    {"doc_id": str(ref.get("doc_id")), "pages": str(ref.get("pages") or "")}
                    for ref in source.get("evidence_refs") or []
                    if isinstance(ref, dict) and ref.get("doc_id")
                ],
                observed_in=input_hash,
            ))
        return items

    # -- identity verdicts: solo, tier verdict, or 7-check tier-C ------------
    plans: list[dict] = []  # each plan yields exactly one future finding
    for draft in sorted(drafts.findings, key=lambda item: min(item.members)):  # D5
        indexes = sorted(draft.members)
        bundles = [_candidate_bundle(candidates[index], chain_by_tx) for index in indexes]
        if len(bundles) == 1:
            key, missing, conflicts = _solo_key(bundles[0])
            tier = "A" if key.startswith("A|") else "B"
            plans.append({
                "indexes": indexes, "key": key, "draft": draft,
                "basis": "anchors" if tier == "A" else "textual",
                "confidence": _notch("HIGH", len(missing)) if tier == "A" else "MEDIUM",
                "missing": missing, "supporting": [], "tier": tier,
                "lineage": None, "group": bundles[0], "events": [],
                "tier_c_rationale": "",
            })
            continue
        verdict = _merge_verdict(bundles)
        if verdict["merge"]:
            plans.append({
                "indexes": indexes, "key": verdict["key"], "draft": draft,
                "basis": verdict["basis"], "confidence": verdict["confidence"],
                "missing": verdict["missing"], "supporting": verdict["supporting"],
                "tier": verdict["tier"], "lineage": verdict["lineage"],
                "group": verdict["group"], "events": [], "tier_c_rationale": "",
            })
            continue
        proposal, rationale = _tier_c_review(bundles, contradicted_indexes, indexes)
        if proposal is not None:
            plans.append({
                "indexes": indexes, "key": proposal["key"], "draft": draft,
                "basis": proposal["basis"], "confidence": proposal["confidence"],
                "missing": proposal["missing"], "supporting": proposal["supporting"],
                "tier": "C", "lineage": proposal["lineage"],
                "group": proposal["group"], "events": [], "tier_c_rationale": "",
            })
            continue
        check = re.search(r"check (\d+)", rationale)
        reason = f"tier_c_rejected_check_{check.group(1)}" if check else "tier_c_rejected"
        register_warning(f"tier-C proposal rejected: {rationale}")
        for index in indexes:  # conservative split: one finding per member
            bundle = _candidate_bundle(candidates[index], chain_by_tx)
            key, missing, conflicts = _solo_key(bundle)
            plans.append({
                "indexes": [index], "key": key, "draft": draft,
                "basis": "anchors" if key.startswith("A|") else "textual",
                "confidence": _notch("HIGH", len(missing)) if key.startswith("A|") else "MEDIUM",
                "missing": missing, "supporting": [], "tier": "A" if key.startswith("A|") else "B",
                "lineage": None, "group": bundle, "events": [],
                "tier_c_rationale": rationale, "reject_reason": reason,
            })

    # -- rules 1–3: compatibility-gated carry-forward, then allocation -------
    used_ids: set[str] = set()
    claimed_prior_ids: set[str] = set()
    fresh_counter = phase_r["counter_base"]
    findings: list[PropertyFinding] = []
    all_members: list[FindingLink] = []
    owner_of_index: dict[int, str] = {}
    correlation_edges: list[tuple[str, str, str | None, str]] = []  # §9 edges
    rejected_groups: dict[int, list[str]] = {}  # refused tier-C members
    # Global current sources keyed (tx_id, tf_id) for §6.3-4 bookkeeping.
    current_sources: dict[tuple[str, str], dict] = {}
    for _index in range(len(candidates)):
        for _source in candidates[_index].get("sources") or []:
            current_sources[(str(_source.get("tx_id") or ""), str(_source.get("tf_id") or ""))] = _source

    for plan in plans:
        draft = plan["draft"]
        events: list[TransitionEvent] = []
        dedup_keys = [_dedup_key_text(candidates[index]["key"]) for index in plan["indexes"]]
        all_members.extend(
            FindingLink(tx_id=str(source["tx_id"]), finding_index=int(source["finding_index"]))
            for index in plan["indexes"]
            for source in candidates[index]["sources"]
        )
        carry = None
        carry_path = ""
        identity_claimants = phase_r["identity_reg"].get(plan["key"], [])
        alive = [claimant for claimant in identity_claimants if id(claimant) not in excluded]
        if alive:
            claimant = alive[0]
            gate_ok, reasons = _compat_gate(plan["group"], claimant, _parse_prior_key(plan["key"]))
            if gate_ok:
                carry, carry_path = claimant, "identity_key"
            else:
                register_event({
                    "kind": "carry_refused", "mechanism": "identity_key", "key": plan["key"],
                    "reason": f"key_match_rejected_by_{reasons[0]}", "refs": [claimant.get("finding_id")],
                })
                events.append(TransitionEvent(
                    at=now, from_status=None, to_status="OPEN",
                    reason=f"key_match_rejected_by_{reasons[0]}",
                    refs=[str(claimant.get("finding_id"))], decided_by="application",
                ))
        elif identity_claimants:
            register_event({
                "kind": "carry_refused_ambiguity", "mechanism": "identity_key", "key": plan["key"],
                "reason": "identity_ambiguous_refused_carry",
                "refs": [str(claimant.get("finding_id")) for claimant in identity_claimants],
            })
            events.append(TransitionEvent(
                at=now, from_status=None, to_status="OPEN",
                reason="identity_ambiguous_refused_carry", refs=[
                    str(claimant.get("finding_id")) for claimant in identity_claimants
                ], decided_by="application",
            ))
        if carry is None:
            legacy_claimants = phase_r["legacy_reg"].get(frozenset(dedup_keys), [])
            alive = [claimant for claimant in legacy_claimants if id(claimant) not in excluded]
            if alive:
                claimant = alive[0]
                gate_ok, reasons = _compat_gate(plan["group"], claimant, _parse_prior_key(
                    claimant.get("identity_key") if isinstance(claimant.get("identity_key"), str) else ""
                ) or _parse_prior_key(plan["key"]))
                if gate_ok:
                    carry, carry_path = claimant, "legacy_dedup_keys"
                else:
                    register_event({
                        "kind": "carry_refused", "mechanism": "legacy_dedup_keys",
                        "key": plan["key"], "reason": f"legacy_match_rejected_by_{reasons[0]}",
                        "refs": [claimant.get("finding_id")],
                    })
                    events.append(TransitionEvent(
                        at=now, from_status=None, to_status="OPEN",
                        reason=f"legacy_match_rejected_by_{reasons[0]}",
                        refs=[str(claimant.get("finding_id"))], decided_by="application",
                    ))
            elif legacy_claimants:
                register_event({
                    "kind": "carry_refused_ambiguity", "mechanism": "legacy_dedup_keys",
                    "key": plan["key"], "reason": "legacy_ambiguous_refused_carry",
                    "refs": [str(claimant.get("finding_id")) for claimant in legacy_claimants],
                })
        split_origin = ""
        if carry is not None and str(carry.get("finding_id")) in used_ids:
            split_origin = str(carry.get("finding_id"))
            events.append(TransitionEvent(
                at=now, from_status=None, to_status="OPEN", reason="split_lineage",
                refs=[str(carry.get("finding_id"), )], decided_by="application",
            ))
            register_event({
                "kind": "split", "mechanism": carry_path, "key": plan["key"],
            })
            carry = None

        # -- allocation (never reuses a prior id: no resurrection) -----------
        if carry is not None:
            finding_id = str(carry.get("finding_id"))
            claimed_prior_ids.add(finding_id)
        else:
            while True:
                fresh_counter += 1
                if fresh_counter > 999:
                    raise ValueError("PF id space exhausted (999); investigate before continuing")
                finding_id = new_finding_id(fresh_counter)
                if finding_id not in used_ids and finding_id not in phase_r["prior_ids"]:
                    break
        used_ids.add(finding_id)
        plan["finding_id"] = finding_id  # §4.7-4b: source→output ownership map

        # -- C3 lifecycle derivation (§6.2) — statuses are never model output --
        affected = sorted({
            tx for index in plan["indexes"] for tx in candidates[index]["tx_ids"]})
        resolved_asks, outstanding_asks, matched_docs = _ask_review(
            affected, all_rows, owned_doc_ids)
        disputed = bool(contradicted_indexes & set(plan["indexes"]))
        final_status = "OPEN"
        resolution_evidence: list[dict] = []
        prior_id_ref = [finding_id] if carry is not None else []
        ladder_done = False
        if carry is not None:
            prior_status = str(carry.get("status") or "OPEN")
            prior_reason = str(carry.get("superseede_reason") or "")
            if prior_reason == "de_observed":
                final_status = "OPEN"
                events.append(TransitionEvent(
                    at=now, from_status="SUPERSEDED", to_status="OPEN",
                    reason="de_observed_reactivation", refs=prior_id_ref,
                    decided_by="application",
                ))
                ladder_done = True  # the reactivation is the run's status story
            elif prior_status in {"OPEN", "PARTIALLY_RESOLVED", "RESOLVED", "PENDING_EVIDENCE", "DISPUTED"}:
                final_status = prior_status
                events.append(TransitionEvent(
                    at=now, from_status=None, to_status=final_status,
                    reason=f"id_carried_by_{carry_path}", refs=prior_id_ref,
                    decided_by="application",
                ))
                if final_status == "RESOLVED":
                    resolution_evidence = [dict(ref) for ref in carry.get("resolution_evidence") or []]
                    if not resolution_evidence:
                        final_status = "OPEN"
                        ladder_done = True
                        events.append(TransitionEvent(
                            at=now, from_status="RESOLVED", to_status="OPEN",
                            reason="status_degraded_resolution_evidence_missing",
                            refs=prior_id_ref, decided_by="application",
                        ))
                    elif outstanding_asks:
                        final_status = "OPEN"
                        ladder_done = True
                        events.append(TransitionEvent(
                            at=now, from_status="RESOLVED", to_status="OPEN",
                            reason="resolution_requirement_reopened",
                            refs=outstanding_asks, decided_by="app_rule:resolution_reopened",
                        ))
                    # else: validated evidence with zero outstanding asks — the
                    # RESOLVED state is retained verbatim (matrix row 10).
                    ladder_done = True
        if plan.get("reject_reason"):
            events.append(TransitionEvent(
                at=now, from_status=None, to_status="OPEN",
                reason=plan["reject_reason"],
                refs=[str(index) for index in plan["indexes"]],
                decided_by="application",
            ))
            rejected_groups.setdefault(id(draft), {"reason": plan["reject_reason"], "ids": []})["ids"].append(finding_id)

        # -- ladder run on active/fresh carriers (one status story per run) ---
        if not ladder_done:
            base = final_status  # "OPEN" at birth, the carried status otherwise
            carried = base if carry is not None else None
            target = None
            if resolved_asks and not outstanding_asks:
                target = "RESOLVED"  # every ask covered by a validated matched doc
            elif resolved_asks:
                target = "PARTIALLY_RESOLVED"
            elif carried == "DISPUTED" and not disputed:
                target = "OPEN"  # §6.1 definition release: contradiction is gone
            elif disputed:
                target = "DISPUTED"
            elif outstanding_asks and carried is not None:
                target = "PENDING_EVIDENCE"  # never applied at birth (row 1)
            elif carried in {"PENDING_EVIDENCE", "PARTIALLY_RESOLVED"}:
                target = "OPEN"  # asks all gone/withdrawn: the state is stale
            if target == "RESOLVED" and readiness_partial:
                # partial-run gate (§6.2/row 43): the transition is deferred
                # with a no-op entry; the finding keeps its current status.
                events.append(TransitionEvent(
                    at=now, from_status=base, to_status=base,
                    reason="transition_deferred", refs=[],
                    decided_by="app_rule:partial_run_gate",
                ))
            elif target and target != base:
                if target == "RESOLVED":
                    final_status = "RESOLVED"
                    resolution_evidence = [{"doc_id": doc} for doc in matched_docs]
                    events.append(TransitionEvent(
                        at=now, from_status=base, to_status="RESOLVED",
                        reason="resolved", refs=resolved_asks,
                        decided_by="app_rule:resolution",
                    ))
                elif target == "PARTIALLY_RESOLVED":
                    final_status = "PARTIALLY_RESOLVED"
                    resolution_evidence = [{"doc_id": doc} for doc in matched_docs]
                    events.append(TransitionEvent(
                        at=now, from_status=base, to_status="PARTIALLY_RESOLVED",
                        reason="partially_resolved", refs=resolved_asks,
                        decided_by="app_rule:partial_resolution",
                    ))
                elif target == "DISPUTED":
                    final_status = "DISPUTED"
                    events.append(TransitionEvent(
                        at=now, from_status=base, to_status="DISPUTED",
                        reason="disputed", refs=[],
                        decided_by="app_rule:contradiction",
                    ))
                elif target == "PENDING_EVIDENCE":
                    final_status = "PENDING_EVIDENCE"
                    events.append(TransitionEvent(
                        at=now, from_status=base, to_status="PENDING_EVIDENCE",
                        reason="pending_evidence", refs=outstanding_asks,
                        decided_by="app_rule:pending_evidence",
                    ))
                else:  # OPEN release from a stale carried PENDING/PARTIAL/DISPUTED
                    final_status = "OPEN"
                    reason = {
                        "DISPUTED": "contradiction_cleared",
                        "PENDING_EVIDENCE": "pending_released",
                        "PARTIALLY_RESOLVED": "partial_released",
                    }.get(base, "lifecycle_rebaseline")
                    events.append(TransitionEvent(
                        at=now, from_status=base, to_status="OPEN", reason=reason,
                        refs=[], decided_by="app_rule:lifecycle_rebaseline",
                    ))

        plan_candidates = [candidates[index] for index in plan["indexes"]]
        finding_documents = [dict(ref) for index in plan["indexes"] for ref in candidates[index]["evidence"]]
        for index in plan["indexes"]:
            owner_of_index[index] = finding_id

        probe = PropertyFinding(
            finding_id=finding_id,
            category=draft.category,
            title=draft.title,
            description=draft.description,
            severity=draft.severity,
            status=final_status,
            confidence=draft.confidence,
            affected_tx_ids=affected,
            documents=finding_documents,
            evidence_gaps=_gap_labels(plan_candidates, open_requirements, draft, upstream_unverified),
            implication=draft.implication,
            required_customer_action=draft.required_customer_action,
            resolution_evidence=resolution_evidence,
            consolidation=ConsolidationProvenance(
                run_id=run_id,
                phase_a_hash=phase_a_hash,
                dossier_refs=[
                    FindingLink(tx_id=str(source["tx_id"]), finding_index=int(source["finding_index"]))
                    for index in plan["indexes"]
                    for source in candidates[index]["sources"]
                ],
                source_hashes=SourceHashes(findings=input_hash),
                dedup_keys=dedup_keys,
            ),
            identity_key=plan["key"],
            identity_basis=plan["basis"],
            identity_confidence=plan["confidence"],
            identity_missing_attributes=plan["missing"],
            identity_supporting=plan["supporting"],
            source_observations=[
                observation for index in plan["indexes"] for observation in build_observations(index)
            ],
            lifecycle_events=events,
            evidence_sufficiency=None,
        )
        sufficiency = (
            "SATISFIED" if not probe.evidence_gaps else ("PARTIAL" if finding_documents else "NONE")
        )
        if (not outstanding_asks and finding_documents and affected
                and all(
                    isinstance(tx_map.get(tx), dict)
                    and tx_map[tx].get("evidence_status") in {"RECITAL", "UNDETERMINED"}
                    for tx in affected
                )):
            # §6.1 evidence dimension: the issue rests only on recital-basis or
            # unresolved-basis sources; a validated ask review left nothing
            # outstanding. Explicit basis only — an absent `evidence_status`
            # never invents UNVERIFIABLE.
            sufficiency = "UNVERIFIABLE"
        probe = probe.model_copy(update={"evidence_sufficiency": PropertyEvidenceSufficiency(sufficiency)})
        if split_origin:
            correlation_edges.append(("SPLIT_FROM", finding_id, split_origin,
                                      "split lineage: this finding was separated from the original carry"))
        if carry is not None:
            for observation in carry.get("source_observations") or []:
                if not isinstance(observation, dict):
                    continue
                tx = str(observation.get("tx_id") or "")
                tf = str(observation.get("tf_id") or "")
                if not tx or not tf:
                    continue
                current = current_sources.get((tx, tf))
                if current is None:
                    row = tx_map.get(tx)
                    if row is not None and _is_terminal(row, documents):
                        probe.lifecycle_events.append(TransitionEvent(
                            at=now, from_status=None, to_status=None,
                            reason="source_withdrawn", refs=[f"{tx}/{tf}"],
                            decided_by="app_rule:source_withdrawn",
                        ))
                    else:  # the observing tx is not re-evaluating here
                        probe.lifecycle_events.append(TransitionEvent(
                            at=now, from_status=None, to_status=None,
                            reason="coverage_gap", refs=[f"{tx}/{tf}"],
                            decided_by="app_rule:coverage_gap",
                        ))
                elif (str(observation.get("title") or "") != str(current.get("title") or "")
                      or str(observation.get("text_excerpt") or "") != str(current.get("text_excerpt") or "")):
                    probe.lifecycle_events.append(TransitionEvent(
                        at=now, from_status=None, to_status=None,
                        reason="source_corrected", refs=[f"{tx}/{tf}"],
                        decided_by="app_rule:source_corrected",
                    ))
                current = None
        findings.append(probe)

    # -- final-union lifecycle bookkeeping over priors (§9 discipline) -------
    retained: dict[str, PropertyFinding] = {}
    identity_keys_now = {plan["key"] for plan in plans}
    for mechanism, key, winner, losers in phase_r["records"]:
        if winner is None:
            register_event({
                "kind": "refuse_all", "mechanism": mechanism, "key": str(key),
                "reason": "ambiguous_or_unorderable_provenance_refuse_all",
                "refs": [str(claimant.get("finding_id")) for claimant in losers],
            })
            for claimant in losers:
                register_warning(
                    f"prior finding {claimant.get('finding_id')!r} excluded by refuse-all "
                    f"({mechanism} collision, no orderable provenance); carry-forward lost"
                )
            continue
        winner_id = str(winner.get("finding_id"))
        if winner_id in claimed_prior_ids and not readiness_partial:
            finding = next(item for item in findings if item.finding_id == winner_id)
            finding.lifecycle_events.append(TransitionEvent(
                at=now, from_status=None, to_status=None, reason="merge_lineage",
                refs=[str(loser.get("finding_id")) for loser in losers],
                decided_by="application",
            ))
        for loser in losers:
            loser_id = str(loser.get("finding_id"))
            loser_status = str(loser.get("status") or "OPEN")
            payload = dict(loser)
            payload["lifecycle_events"] = list(payload.get("lifecycle_events") or [])
            if readiness_partial:
                # partial-run gate (§6.2/§6.3-7): §4.7-3 retirements are
                # deferred with transition_deferred entries; ids and statuses
                # stay verbatim.
                payload["lifecycle_events"].append(TransitionEvent(
                    at=now, from_status=loser_status, to_status=loser_status,
                    reason="transition_deferred", refs=[],
                    decided_by="app_rule:partial_run_gate",
                ).model_dump(mode="json"))
                try:
                    retained[loser_id] = PropertyFinding.model_validate(payload)
                except ValidationError:
                    register_warning(
                        f"prior finding {loser_id!r} dropped: no longer "
                        f"conforms to the container contract"
                    )
                continue
            payload.update({
                "status": "SUPERSEDED",
                "superseede_reason": f"merged_into:{winner_id}",
            })
            payload["lifecycle_events"].append(TransitionEvent(
                at=now, from_status=loser_status,
                to_status="SUPERSEDED", reason=f"merged_into:{winner_id}",
                refs=[winner_id], decided_by="application",
            ).model_dump(mode="json"))
            correlation_edges.append((
                "MERGED_INTO", loser_id, winner_id,
                "tier grouping absorbed this member; the victim is retained in "
                "history and never auto-reactivates",
            ))
            try:
                retained[loser_id] = PropertyFinding.model_validate(payload)
            except ValidationError:
                register_warning(
                    f"prior finding {loser_id!r} dropped: no longer "
                    f"conforms to the container contract"
                )

    # Output ownership of every persisted source (§4.7-4b): which current
    # finding re-observes each prior (tx_id, tf_id) — candidates left
    # unassigned by the drafts own no output and never count as descendants.
    source_owner: dict[tuple[str, str], str] = {}
    for plan in plans:
        if not plan.get("finding_id"):
            continue
        for index in plan["indexes"]:
            for source in candidates[index]["sources"] or []:
                pair = (str(source.get("tx_id") or ""),
                        str(source.get("tf_id") or ""))
                if pair[0] and pair[1]:
                    source_owner[pair] = str(plan["finding_id"])

    for prior in phase_r["population"]:
        if id(prior) in excluded or str(prior.get("finding_id")) in claimed_prior_ids:
            continue
        if str(prior.get("status") or "") == "SUPERSEDED":
            continue  # already retired (de_observed from an earlier run)
        prior_id = str(prior.get("finding_id"))
        prior_status = str(prior.get("status") or "OPEN")
        prior_obs = [
            (str(o.get("tx_id") or ""), str(o.get("tf_id") or ""))
            for o in prior.get("source_observations") or [] if isinstance(o, dict)
        ]
        prior_obs = [(tx, tf) for tx, tf in prior_obs if tx and tf]
        uncovered = [
            f"{tx}/{tf}" for tx, tf in prior_obs
            if tx_map.get(tx) is None or not _is_terminal(tx_map.get(tx), documents)
        ]
        # §6.2 de_observed eligibility: every observing tx terminal + validated
        # here, the identity not re-derived under the same key, and no source
        # re-observed under another group. Otherwise: coverage_gap retention.
        eligible = (
            not uncovered
            and str(prior.get("identity_key") or "") not in identity_keys_now
            and not any((tx, tf) in current_sources for tx, tf in prior_obs)
        )
        payload = dict(prior)
        payload["lifecycle_events"] = list(payload.get("lifecycle_events") or [])
        if readiness_partial:
            # partial-run gate (§6.3-2): de_observation is deferred with a
            # transition_deferred entry; the finding keeps id and status.
            payload["lifecycle_events"].append(TransitionEvent(
                at=now, from_status=prior_status, to_status=prior_status,
                reason="transition_deferred", refs=[],
                decided_by="app_rule:partial_run_gate",
            ).model_dump(mode="json"))
            try:
                retained[prior_id] = PropertyFinding.model_validate(payload)
            except ValidationError:
                register_warning(
                    f"prior finding {prior_id!r} dropped: no longer "
                    f"conforms to the container contract"
                )
            continue
        if eligible:
            payload.update({"status": "SUPERSEDED", "superseede_reason": "de_observed"})
            payload["lifecycle_events"].append(TransitionEvent(
                at=now, from_status=prior_status,
                to_status="SUPERSEDED", reason="de_observed",
                refs=[prior_id], decided_by="application",
            ).model_dump(mode="json"))
        else:
            # §4.7-4b split_replaced: the §6.3-1 guard passes (every prior
            # observing tx terminal + validated) and the prior's sources are
            # re-observed in this run's inputs under different identities that
            # no longer carry this finding — the id cannot honestly continue.
            # Every re-observing output is a recorded descendent; the original
            # retires terminal (never reactivates) with its history intact.
            # Without an owning output there is no derivation rationale: the
            # finding is retained with its coverage_gap event instead.
            descendants = sorted({
                source_owner[(tx, tf)] for tx, tf in prior_obs
                if (tx, tf) in source_owner
            })
            if not uncovered and descendants:
                payload.update({
                    "status": "SUPERSEDED", "superseede_reason": "split_replaced",
                })
                payload["lifecycle_events"].append(TransitionEvent(
                    at=now, from_status=prior_status,
                    to_status="SUPERSEDED", reason="split_replaced",
                    refs=descendants, decided_by="application",
                ).model_dump(mode="json"))
                for child_id in descendants:
                    correlation_edges.append((
                        "SPLIT_FROM", child_id, prior_id,
                        "split_replaced lineage: the original identity retired "
                        "and this finding re-observes its sources as its "
                        "replacement record; the victim never auto-reactivates",
                    ))
                    child = next(
                        (item for item in findings if item.finding_id == child_id),
                        None)
                    if child is not None:
                        child.lifecycle_events.append(TransitionEvent(
                            at=now, from_status=None, to_status=None,
                            reason="identity_change", refs=[prior_id],
                            decided_by="application",
                        ))
                register_event({
                    "kind": "split_replaced", "mechanism": "identity",
                    "key": str(prior.get("identity_key") or "-"),
                    "reason": "sources_reobserved_under_other_identities",
                    "refs": [prior_id, *descendants],
                })
            else:
                # §6.3-1: re-evaluation not covered — retained at the current
                # status with a coverage_gap listing the uncovered sources.
                payload["lifecycle_events"].append(TransitionEvent(
                    at=now, from_status=prior_status, to_status=prior_status,
                    reason="coverage_gap", refs=[f"{tx}/{tf}" for tx, tf in prior_obs],
                    decided_by="app_rule:coverage_gap",
                ).model_dump(mode="json"))
        try:
            retained[prior_id] = PropertyFinding.model_validate(payload)
        except ValidationError:
            register_warning(
                f"prior finding {prior_id!r} dropped: no longer "
                f"conforms to the container contract"
            )

    for terminal in phase_r["terminal"]:  # retained verbatim, never carried
        try:
            retained[str(terminal.get("finding_id"))] = PropertyFinding.model_validate(terminal)
        except ValidationError:
            register_warning(
                f"prior finding {terminal.get('finding_id')!r} dropped: no longer "
                f"conforms to the container contract"
            )

    findings.extend(retained[key] for key in sorted(retained))

    # -- §9 correlations: deterministic edges only (LLM proposals: C4+) ------
    for group in rejected_groups.values():
        for i in range(len(group["ids"])):
            for j in range(i + 1, len(group["ids"])):
                correlation_edges.append((
                    "RELATED", group["ids"][i], group["ids"][j],
                    f"same issue family; tier-C merge refused ({group['reason']}) "
                    f"— deliberately separate",
                ))
    for finding in findings:  # includes retained priors: container-level view
        for tx in finding.affected_tx_ids:
            for upstream in upstream_unverified.get(tx) or []:
                correlation_edges.append((
                    "DEPENDS_ON", finding.finding_id, None,
                    f"assessment depends on unverified predecessor {upstream}",
                ))

    # -- persisted contradictions: content keys, dedup, related ids (§5.1-5) --
    contradiction_records: dict[str, dict] = {}
    for item in drafts.contradictions:
        sides = [
            {"tx_id": str(source["tx_id"]), "finding_index": int(source["finding_index"])}
            for index in item.members
            for source in candidates[index]["sources"]
        ]
        key = content_hash({
            "description": _od3(item.description),
            "sides": sorted((side["tx_id"], side["finding_index"]) for side in sides),
        })
        related = sorted({owner_of_index[index] for index in item.members if index in owner_of_index})
        record = contradiction_records.get(key)
        if record is None:
            contradiction_records[key] = {
                "description": item.description,
                "severity": item.severity.value,
                "resolution_guidance": item.resolution_guidance,
                "sides": sides,
                "contradiction_key": key,
                "related_pf_ids": related,
            }
        else:  # matrix row 9: same content key → members refresh, never duplicate
            seen = {(side["tx_id"], side["finding_index"]) for side in record["sides"]}
            record["sides"].extend(
                side for side in sides
                if (side["tx_id"], side["finding_index"]) not in seen)
            record["related_pf_ids"] = sorted(set(record["related_pf_ids"]) | set(related))
        related_all = sorted(set(related))
        for i in range(len(related_all)):
            for j in range(i + 1, len(related_all)):
                correlation_edges.append((
                    "CONFLICTS_WITH", related_all[i], related_all[j],
                    f"contradiction record: {item.description[:80]}",
                ))

    deduped_edges: dict[tuple[str, str, str | None], Correlation] = {}
    for edge_type, from_pf, to_pf, rationale in correlation_edges:
        key = (edge_type, from_pf, to_pf)
        if key not in deduped_edges:
            deduped_edges[key] = Correlation(
                type=edge_type, from_pf=from_pf, to_pf=to_pf, rationale=rationale)

    # -- §9 (OD-4 additive): RELATED edges proposed by the draft pass ----------
    # Advisory only: every pair is re-validated against the app-owned output
    # map; drops are registered. A pair whose key a deterministic edge already
    # covers stays deterministic (first appended wins); further duplicate
    # proposals are silent no-ops. A proposal never merges findings, rewires
    # identity, or moves statuses — even when accepted.
    llm_count = 0
    for pair in drafts.related_pairs:
        a, b = pair
        if a == b:
            register_warning(f"RELATED proposal dropped: self pair ({a})")
            continue
        if a not in owner_of_index or b not in owner_of_index:
            register_warning(
                f"RELATED proposal dropped: unknown candidate index {pair!r}")
            continue
        from_pf, to_pf = owner_of_index[a], owner_of_index[b]
        if from_pf == to_pf:
            register_warning(
                f"RELATED proposal dropped: ({a},{b}) collected into {from_pf}")
            continue
        key = ("RELATED", from_pf, to_pf)
        if key in deduped_edges:
            continue  # an earlier (deterministic) edge already covers this pair
        if llm_count >= 64:
            register_warning(
                "RELATED proposals capped at 64 per run; further pairs dropped")
            break
        deduped_edges[key] = Correlation(
            type="RELATED", from_pf=from_pf, to_pf=to_pf,
            rationale="model-proposed related issue: distinct findings about "
            "the same subject that keep separate identities (advisory; "
            "re-validated)",
            determined_by="llm")
        llm_count += 1

    blocks = _container_blocks(
        rows=list(tx_map.values()), chain_entries=chain_entries or [],
        registration=registration, all_requirements=all_rows,
        phase_a_hash=phase_a_hash, input_hash=input_hash,
        readiness=readiness, documents=documents)

    return PropertyConsolidationResult(
        findings=findings,
        contradictions=[contradiction_records[k] for k in sorted(contradiction_records)],
        unresolved_dependencies=[
            str(item) for item in drafts.unresolved_dependencies if str(item) in open_ids
        ],
        provenance=ConsolidationProvenance(
            run_id=run_id,
            phase_a_hash=phase_a_hash,
            dossier_refs=all_members,
            source_hashes=SourceHashes(findings=input_hash),
        ),
        coverage=blocks["coverage"],
        integrity=blocks["integrity"],
        readiness=blocks["readiness"],
        correlations=list(deduped_edges.values()),
    )


def _strip_draft_keys(payload):
    if not isinstance(payload, dict):
        return payload
    return {key: value for key, value in payload.items() if key not in _DRAFT_STRIP_KEYS}


def validate_draft(payload) -> ConsolidationDraftResult:
    data = payload
    if isinstance(data, dict):
        data = dict(data)
        if isinstance(data.get("findings"), list):
            data["findings"] = [_strip_draft_keys(item) for item in data["findings"]]
        if isinstance(data.get("contradictions"), list):
            data["contradictions"] = [_strip_draft_keys(item) for item in data["contradictions"]]
    try:
        return ConsolidationDraftResult.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"consolidation draft failed schema validation: {e}") from e


def _container(result: PropertyConsolidationResult, input_hash: str) -> dict:
    return {
        "container_version": CONTAINER_VERSION,
        "input_hash": input_hash,
        # mode="json": _dump is plain json.dumps with no enum fallback, so the
        # persisted container must already be JSON primitives.
        "result": result.model_dump(mode="json"),
    }


def _registered(case_id: str, result: dict, registration: dict) -> dict:
    """Attach the run-scoped registration to every outcome and log it; on ok
    runs the same registers are materialized into ``integrity`` (§8.1)."""
    result["registration"] = registration
    flagged = bool(registration["malformed_observations"] or registration["excluded_evidence_refs"])
    status = result.get("status")
    if status == "blocked":
        level = logging.ERROR
    elif status == "ok" and not flagged:
        level = logging.INFO
    else:
        level = logging.WARNING
    logger.log(
        level,
        "phase_c_registration case=%s outcome=%s reason=%s register=%s",
        case_id, status, result.get("reason") or "-", 
        json.dumps(registration, ensure_ascii=False, default=str),
    )
    return result


def consolidate_findings(case_id: str, run_id: str | None = None) -> dict:
    """Run Phase C for a case; never raises. Outcomes (`ok|blocked|error`):
    - {"status": "ok", "container": {...}, "registration": {...}}
    - {"status": "blocked", "retryable": True, "reason": ..., "registration": {...}}
    - {"status": "error", "reason": ..., "registration": {...}}

    ``blocked`` (CORRUPT input / read failure): nothing consolidated or
    persisted; the prior known-good container stays untouched and stays the
    last known-good result. Since C4 (D2) pending/incomplete inputs are *not*
    skipped: the run proceeds in partial mode over terminal dossiers, reports
    the state in the readiness/integrity blocks, and defers the RESOLVED --
    SUPERSEDED / id-retiring transitions under the §6.2 partial-run gate.
    ``registration`` is run-scoped (Option B): the input-state classification,
    malformed-observation and excluded-evidence-ref registers, and the D7
    disclosure - returned and logged, materialized into ``integrity`` on ok.
    """
    registration = _new_registration()
    try:
        # -- step 1: strict Phase B input reads (§8.4) -----------------------
        try:
            transactions = _d1_reorder(repo.list_persisted_transaction_results(case_id))
        except Exception as error:
            registration["input_state"] = _read_state(error)
            return _registered(case_id, {
                "status": "blocked", "retryable": True,
                "reason": f"persisted transaction results could not be read "
                          f"strictly: {error}",
            }, registration)
        try:
            documents = repo.get_agent_documents(case_id)
            owned_doc_ids = {str(doc.get("doc_id")) for doc in documents if doc.get("doc_id")}
        except Exception as error:
            registration["input_state"] = _read_state(error)
            return _registered(case_id, {
                "status": "blocked", "retryable": True,
                "reason": f"case document roster could not be read: {error}",
            }, registration)

        # -- step 2: two-level row/finding validation ------------------------
        # A structurally invalid row blocks the whole run — never salvaged
        # into a partially usable one (row 15).
        for position, row in enumerate(transactions):
            problem = _row_problem(row)
            if problem:
                registration["input_state"] = "CORRUPT"
                return _registered(case_id, {
                    "status": "blocked", "retryable": True,
                    "reason": f"transaction result row #{position}: {problem}",
                }, registration)
        try:
            sanitized = _scan_findings(transactions, owned_doc_ids, registration)
        except Exception as error:
            registration["input_state"] = "CORRUPT"
            return _registered(case_id, {
                "status": "blocked", "retryable": True,
                "reason": f"transaction results could not be validated: {error}",
            }, registration)

        # C4 partial mode (D2, §3.2): the whole-run skip is retired. A pending
        # input makes the run PENDING (`ok`), consolidating terminal dossiers
        # only — the pending tx contributes no finding content, its OPEN
        # requirements surface in the readiness block, and the partial-run
        # transition gate (§6.2) becomes load-bearing.
        try:
            chain_entries = repo.get_persisted_title_chain_entries(case_id)
        except Exception as error:
            registration["input_state"] = _read_state(error)
            return _registered(case_id, {
                "status": "blocked", "retryable": True,
                "reason": f"persisted title chain could not be read strictly: {error}",
            }, registration)
        row_sequences = {seq for seq in (_row_sequence(row) for row in sanitized) if seq > 0}
        chain_positions = _chain_sequences(chain_entries)
        if not transactions and not chain_positions:
            registration["input_state"] = "EMPTY"
        elif chain_positions - row_sequences:
            registration["input_state"] = "INCOMPLETE"
        elif any(not _is_terminal(row, documents) for row in sanitized):
            registration["input_state"] = "PENDING"
        else:
            registration["input_state"] = "READY"

        try:
            open_requirements = _open_requirements(case_id)
            all_requirements = repo.list_requirements(case_id) or []
            phase_a_hash = _phase_a_state(case_id)
        except Exception as error:
            registration["input_state"] = _read_state(error)
            return _registered(case_id, {
                "status": "blocked", "retryable": True,
                "reason": f"requirements or phase-A state could not be read: {error}",
            }, registration)

        input_hash = _external_input_hash(
            case_id=case_id,
            chain_by_tx=_chain_by_tx(chain_entries),
            phase_a_hash=phase_a_hash,
            rows=sanitized,
            documents=documents,
            all_requirements=all_requirements,
        )

        prior_container = None
        try:
            prior_container = repo.get_property_findings(case_id)
            prior_raw = repo.get_property_findings_raw(case_id)
        except Exception as error:
            registration["input_state"] = _read_state(error)
            return _registered(case_id, {
                "status": "blocked", "retryable": True,
                "reason": f"prior property-findings container could not be read: {error}",
            }, registration)
        if prior_container is None and prior_raw is not None:
            registration["prior_container_unreadable"] = (
                "the persisted property-findings value could not be parsed as a "
                "container; proceeding with no prior state — the next successful "
                "consolidation overwrites it (§9(b))"
            )
            logger.warning(
                "carry_forward_degraded case=%s: unreadable prior container discarded on success",
                case_id,
            )
        if prior_container and prior_container.get("input_hash") == input_hash:
            # Same-version-only replay: a v1 container with an identical input
            # hash reconsolidates once to gain C2 identity/provenance fields.
            if prior_container.get("container_version") == CONTAINER_VERSION:
                return _registered(case_id, {
                    "status": "ok", "container": prior_container,
                }, registration)

        # C4 partial mode (§3.2 PENDING row): only terminal dossiers contribute
        # content. All strict-read rows stay in the map — disappearance
        # bookkeeping (§6.3-1/§6.3-4) must distinguish a row that exists but is
        # non-terminal from a row that is missing entirely.
        solid_rows = [row for row in sanitized if _is_terminal(row, documents)]
        candidates = _collect_candidates(solid_rows, owned_doc_ids=owned_doc_ids)

        readiness = _readiness_fields(
            sanitized, chain_entries or [],
            [item.get("requirement_id") for item in open_requirements],
            registration, documents)

        # No candidates: an honest empty container (no LLM call needed).
        if not candidates:
            blocks = _container_blocks(
                rows=sanitized, chain_entries=chain_entries or [],
                registration=registration, all_requirements=all_requirements,
                phase_a_hash=phase_a_hash, input_hash=input_hash,
                readiness=readiness, documents=documents)
            result = PropertyConsolidationResult(
                findings=[],
                contradictions=[],
                unresolved_dependencies=[],
                provenance=ConsolidationProvenance(
                    run_id=run_id,
                    phase_a_hash=phase_a_hash,
                    dossier_refs=[],
                    source_hashes=SourceHashes(findings=input_hash),
                ),
                coverage=blocks["coverage"],
                integrity=blocks["integrity"],
                readiness=blocks["readiness"],
                correlations=[],
            )
            container = _container(result, input_hash)
            repo.save_property_findings(case_id, container)
            return _registered(case_id, {"status": "ok", "container": container}, registration)

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        prompt = _build_prompt(candidates, open_requirements)
        drafts = validate_draft(complete_json(prompt, task="agent_consolidation"))
        result = _assemble(
            candidates, drafts, open_requirements,
            phase_a_hash=phase_a_hash, run_id=run_id, input_hash=input_hash,
            prior_container=prior_container,
            tx_by_id={str(row.get("tx_id")): row for row in sanitized if row.get("tx_id")},
            chain_entries=chain_entries,
            registration=registration,
            now=now,
            all_requirements=all_requirements,
            owned_doc_ids=owned_doc_ids,
            documents=documents,
            readiness_fields=readiness,
        )
        container = _container(result, input_hash)
        repo.save_property_findings(case_id, container)
        logger.info(
            "phase C consolidated case=%s candidates=%s findings=%s contradictions=%s",
            case_id, len(candidates), len(result.findings), len(result.contradictions),
        )
        return _registered(case_id, {"status": "ok", "container": container}, registration)
    except AgentLLMError as e:
        logger.error("phase C model pass failed for %s: %s", case_id, e)
        return _registered(case_id, {
            "status": "error", "reason": f"consolidation model pass failed: {e}",
        }, registration)
    except Exception as e:  # noqa: BLE001 — consolidation never kills the pipeline
        logger.exception("phase C failed for %s", case_id)
        return _registered(case_id, {
            "status": "error", "reason": f"consolidation failed: {e}",
        }, registration)
