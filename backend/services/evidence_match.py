"""Deterministic evidence matching (target architecture §3.3, Stage 4).

Classifies case documents against OPEN evidence requirements so an upload's
effect is visible before the agent resumes. The match decision is owned by the
application (master rule: the LLM never controls state); the verifying dossier
still judges the actual evidence — a MATCHED row stays OPEN until its owner
transaction completes, which the requirements lifecycle turns into SATISFIED.

Decision inputs per requirement are its `document_type` + `reason` tokens
against each document's classification (`document_type`) + `filename` tokens:

- identifier tokens (containing a digit — case/registration numbers) are the
  strongest evidence, since they come from real case references;
- an exact normalized classification match is strong;
- otherwise >=2 shared generic tokens is a weak candidate.

Unique strong candidate -> MATCHED; several -> AMBIGUOUS (user decides); a
unique weak candidate -> PARTIALLY_MATCHED (candidate recorded); weak ties ->
AMBIGUOUS; nothing -> NOT_MATCHED.
"""

from __future__ import annotations

import re

from backend.logger import get_logger
from backend.schemas.analysis import MatchStatus

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"a", "an", "and", "for", "of", "the", "with"}


def _tokens(text: object) -> set[str]:
    """Normalized word tokens; single characters carry no meaning."""
    return {
        token
        for token in _TOKEN_RE.findall(str(text or "").casefold())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _identifiers(tokens: set[str]) -> set[str]:
    """Identifier-like tokens: those containing a digit (e.g. 1329, cr, 2009)."""
    return {token for token in tokens if any(ch.isdigit() for ch in token)}


def _doc_tokens(document: dict) -> set[str]:
    return _tokens(document.get("document_type")) | _tokens(document.get("filename"))


def _match_one(requirement: dict, documents: list[dict]) -> dict:
    def _decision(status: MatchStatus, doc_id: str | None = None) -> dict:
        return {
            "requirement_id": str(requirement.get("requirement_id") or ""),
            "document_type": str(requirement.get("document_type") or ""),
            "status": status.value,
            "doc_id": doc_id,
        }

    if not str(requirement.get("requirement_id") or "").strip():
        raise ValueError("a requirement needs its requirement_id to be matched")

    req_type_tokens = _tokens(requirement.get("document_type"))
    req_tokens = req_type_tokens | _tokens(requirement.get("reason"))
    identifiers = _identifiers(req_tokens)
    if not req_tokens:
        return _decision(MatchStatus.NOT_MATCHED)

    strong: list[dict] = []
    weak: list[tuple[int, dict]] = []
    for document in documents:
        doc_tokens = _doc_tokens(document)
        if not doc_tokens:
            continue
        if identifiers & _identifiers(doc_tokens):
            strong.append(document)
        elif req_type_tokens and req_type_tokens == _tokens(document.get("document_type")):
            strong.append(document)
        else:
            overlap = len(req_tokens & doc_tokens)
            if overlap >= 2:
                weak.append((overlap, document))

    if len(strong) == 1:
        return _decision(MatchStatus.MATCHED, strong[0].get("doc_id"))
    if len(strong) > 1:
        return _decision(MatchStatus.AMBIGUOUS)
    if weak:
        best_score = max(score for score, _ in weak)
        best = [document for score, document in weak if score == best_score]
        if len(best) == 1:
            return _decision(MatchStatus.PARTIALLY_MATCHED, best[0].get("doc_id"))
        return _decision(MatchStatus.AMBIGUOUS)
    return _decision(MatchStatus.NOT_MATCHED)


def match_requirements(requirements: list[dict], documents: list[dict]) -> list[dict]:
    """Pure match-decision pass: one decision per requirement, in input order."""
    return [_match_one(requirement, documents) for requirement in requirements or []]


def refresh_requirement_matches(case_id: str) -> list[dict]:
    """Match-and-record for one case; returns only decisions that changed.

    All OPEN rows are re-decided (deterministic and idempotent), every OPEN row's
    recorded match is refreshed through the ledger update, and only decisions
    that differ from the stored ones are returned so callers log upload effects.
    """
    from backend.database.repositories import agent_repo as repo
    from backend.services.agent_tools import _is_phase_a_only_document

    rows = {row["requirement_id"]: row for row in repo.list_requirements(case_id, status="OPEN")}
    if not rows:
        return []
    documents = [
        document for document in repo.get_agent_documents(case_id)
        if not _is_phase_a_only_document(document)
    ]
    decisions = match_requirements(list(rows.values()), documents)
    changed = [
        decision for decision in decisions
        if (decision["status"], decision["doc_id"])
        != (rows[decision["requirement_id"]].get("match_status"), rows[decision["requirement_id"]].get("matched_doc_id"))
    ]
    repo.apply_requirement_matches(case_id, decisions)
    return changed
