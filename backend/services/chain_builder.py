"""The title-chain builder.

Builds the ordered chain of ownership transfers for a case's property. It
works history-first: the history documents (encumbrance certificate, mutation,
RTC) are read in full and give the backbone. Title
deeds are opened only to extend the chain backward through their recitals or to
confirm a link the history shows. Nothing is verified here: each link is
verified later, on its own, by the verification agent.

Gates enforced in code before a chain is saved:

* every history document was read end to end in this run;
* every source reference points at a history document or title deed of this
  case, by its exact filename, and that document was read end to end;
* each link's evidence status agrees with the documents it cites;
* a link that claims continuity names the previous link's acquirers;
* a reported gap is challenged once with passages that may reconcile it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits
from pydantic_ai.exceptions import AgentRunError

from backend.config import CLEARTITLE_CHAIN_MODEL_CALL_BUDGET
from backend.database.repositories import agent_repo as repo
from backend.domain.chain_continuity import (
    ENTITY_DOC_TYPES,
    entity_continuity_supported,
    has_entity_party,
    name_words,
    names_connect,
)
from backend.integrations.llm.agent_models import build_agent_model
from backend.logger import get_logger
from backend.prompts.loader import load_prompt
from backend.schemas.chain import ChainLink, ChainResult, DocumentedTransaction
from backend.services import chain_identity
from backend.shared.constants import CHAIN_DEED_DOC_TYPES, CHAIN_HISTORY_DOC_TYPES

logger = get_logger(__name__)

_SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "title_chain" / "skill.md"
_CHUNK_CHARS = 80_000
_GAP_MARK = "        ┆"
_GAP_WINDOW_CHARS = 400
_GAP_IDENTITY_PASSAGES = 3
_GAP_PARTITION_PASSAGES = 2
_GAP_EVIDENCE_RETRIES = 1


class ChainBuildError(RuntimeError):
    """The chain could not be built or safely saved; nothing was persisted."""


@dataclass
class ChainDeps:
    """State of one chain-building run."""

    case_id: str
    history: dict[str, dict]
    deeds: dict[str, dict]
    texts: dict[str, str] = field(default_factory=dict)
    read_upto: dict[str, int] = field(default_factory=dict)
    gap_evidence_shown: set[tuple[str, str]] = field(default_factory=set)
    gap_evidence_retries: int = 0
    partition_evidence_shown: bool = False

    def document(self, doc_id: str) -> dict | None:
        """The history document or title deed with this id, if it is in scope."""
        return self.history.get(doc_id) or self.deeds.get(doc_id)

    def fully_read(self, doc_id: str) -> bool:
        """True when the document was read to its end in this run."""
        return doc_id in self.texts and self.read_upto[doc_id] >= len(self.texts[doc_id])


chain_agent = Agent(
    deps_type=ChainDeps,
    output_type=ChainResult,
    instructions=load_prompt("title_chain_system"),
    retries={"tools": 3, "output": 7},
)


@chain_agent.tool
def read_document(ctx: RunContext[ChainDeps], doc_id: str) -> dict:
    """Read the next unread part of a history document's or title deed's OCR text.

    Each call continues where the previous call for that document stopped.
    Call again for the same document while ``has_more`` is true.

    Args:
        doc_id: A document id from the history document list or the title deed list.
    """
    deps = ctx.deps
    if deps.document(doc_id) is None:
        raise ModelRetry(
            f"{doc_id!r} is not a history document or title deed of this case. "
            f"Read only: {', '.join([*deps.history, *deps.deeds])}."
        )
    if doc_id not in deps.texts:
        deps.texts[doc_id] = repo.get_document_raw_text(deps.case_id, doc_id)
    text = deps.texts[doc_id]
    start = deps.read_upto.get(doc_id, 0)
    end = min(start + _CHUNK_CHARS, len(text))
    deps.read_upto[doc_id] = end
    return {"doc_id": doc_id, "text": text[start:end], "has_more": end < len(text)}


@chain_agent.output_validator
def check_gates(ctx: RunContext[ChainDeps], result: ChainResult) -> ChainResult:
    """Reject a chain that skipped a history document or cites what it did not read."""
    deps = ctx.deps
    unread = [doc_id for doc_id in deps.history if not deps.fully_read(doc_id)]
    if unread:
        raise ModelRetry(
            "Read every history document to the end before saving the chain. "
            f"Not fully read: {', '.join(unread)}."
        )
    for ref in result.source_refs():
        document = deps.document(ref.doc_id)
        if document is None:
            raise ModelRetry(
                f"Source reference {ref.doc_id!r} is not a history document or title deed "
                "of this case."
            )
        if not deps.fully_read(ref.doc_id):
            raise ModelRetry(f"Read {ref.doc_id} to the end before citing it.")
        filename = document.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            raise ChainBuildError(f"Source document {ref.doc_id} has no valid stored filename.")
        # The validated document id determines the filename, not the model's wording.
        ref.filename = filename
    for link in result.title_chain:
        problem = _evidence_status_problem(deps, link.documented_transaction)
        if problem:
            raise ModelRetry(f"Link {link.chain_position}: {problem}")
    _check_continuity(deps, result.title_chain)
    _check_partition_evidence(deps, result.title_chain)
    _check_gap_evidence(deps, result.title_chain)
    return result


def _evidence_status_problem(deps: ChainDeps, transaction: DocumentedTransaction) -> str | None:
    """Why a link's evidence status disagrees with the documents it cites, if it does."""
    cited = {ref.doc_id for ref in transaction.source_refs}
    status = transaction.evidence_status
    if status == "corroborated" and len(cited) < 2:
        return "corroborated needs two or more source documents that agree."
    if status == "register_reported" and not cited & deps.history.keys():
        return "register_reported needs a history document as a source."
    if status in {"deed_reported", "recital_reported"} and not cited & deps.deeds.keys():
        return f"{status} needs a title deed as a source."
    return None


def _check_continuity(deps: ChainDeps, chain: list[ChainLink]) -> None:
    """Reject a link that claims continuity from owners it does not name.

    ``continues_previous`` is a factual claim that the transferors are the
    previous link's acquirers. Ordering is checked here too: a recital-supported
    transfer that precedes another cannot be placed after it. A model that
    cannot support continuity must mark the gap instead of asserting it.
    """
    for index, link in enumerate(chain):
        if index == 0:
            if link.continues_previous:
                logger.warning("chain_rejected case_id=%s gate=continuity link=1", deps.case_id)
                raise ModelRetry("Link 1 is the earliest transfer; set continues_previous false.")
            continue
        if not link.continues_previous:
            continue
        previous = chain[index - 1].documented_transaction
        current = link.documented_transaction
        if names_connect(previous.transferees, current.transferors):
            continue
        if entity_continuity_supported(
            previous.transferees, current.transferors, _constitution_texts(deps)
        ):
            continue
        logger.warning("chain_rejected case_id=%s gate=continuity link=%s", deps.case_id, index + 1)
        hint = (
            " A partition precedes the sale of the share it allots: keep it as its own "
            "link and place it before that sale."
            if "partition" in current.transaction_type.casefold()
            else ""
        )
        raise ModelRetry(
            f"Link {index + 1} says it continues link {index}, but its transferors "
            f"({', '.join(current.transferors)}) are not link {index}'s acquirers "
            f"({', '.join(previous.transferees)}). Order the links from earliest to "
            "latest, and set continues_previous true only when the transferors are "
            "the previous link's acquirers. If a recital-supported transfer such as "
            "a partition comes first, put it before the transfer it precedes. If no "
            "recorded transfer connects the owners, set continues_previous false and "
            f"explain the gap in summary_points.{hint}"
        )


def _constitution_texts(deps: ChainDeps) -> dict[str, str]:
    """Full text of each fully read partnership, LLP or trust deed, by document id."""
    return {
        doc_id: deps.texts.get(doc_id, "")
        for doc_id, document in deps.deeds.items()
        if document.get("document_type") in ENTITY_DOC_TYPES and deps.fully_read(doc_id)
    }


def _check_partition_evidence(deps: ChainDeps, chain: list[ChainLink]) -> None:
    """Challenge a partition reported in the chain's notes when it is not a link.

    Once per run: if the model still leaves the partition as a note after seeing
    the recital, that is its documented reading rather than a loop to retry.
    """
    if deps.partition_evidence_shown:
        return
    if any(
        link.documented_transaction.transaction_type.casefold() == "partition" for link in chain
    ):
        return
    if not any(
        "partition" in " ".join(link.documented_transaction.summary_points).casefold()
        for link in chain
    ):
        return
    earliest = chain[0].documented_transaction
    owners = name_words([*earliest.transferors, *earliest.transferees])
    if not owners:
        return
    passages = [
        (_doc_label(deps, doc_id), passage)
        for doc_id, text in deps.texts.items()
        if deps.fully_read(doc_id)
        for passage in _partition_passages(text, owners, _GAP_PARTITION_PASSAGES)
    ]
    if not passages:
        return
    deps.partition_evidence_shown = True
    logger.warning("chain_rejected case_id=%s gate=partition_recital", deps.case_id)
    raise ModelRetry(_partition_retry_message(passages))


def _partition_retry_message(passages: list[tuple[str, str]]) -> str:
    """The retry prompt: a reported partition must be a chain link."""
    quoted = "\n\n".join(f"{label}:\n...{passage}..." for label, passage in passages)
    return (
        "The chain reports a partition of this property in summary_points but has no "
        "Partition link. A recital-supported partition is an ownership transfer, not "
        "a note. Add it as its own link before the transfer it precedes, citing the "
        "deed that recites it; leave its date null when only the mutation entry date "
        "is stated. If these passages concern other property, remove the partition "
        "claim from the chain:\n\n"
        f"{quoted}"
    )


def _check_gap_evidence(deps: ChainDeps, chain: list[ChainLink]) -> None:
    """Send a reported gap back once with passages that may reconcile its owners.

    The model decides continuity, but a gap is where OCR corruption or an
    unnoticed recital most often hides a transfer. Showing the passages that
    mention the later transferor beside the earlier transfer's number, date or
    parties forces that comparison instead of accepting the first reading.
    """
    if deps.gap_evidence_retries >= _GAP_EVIDENCE_RETRIES:
        return
    for index in range(1, len(chain)):
        if chain[index].continues_previous:
            continue
        key = _gap_key(chain, index)
        if key in deps.gap_evidence_shown:
            continue
        passages = _gap_evidence(deps, chain, index)
        constitution = _unread_constitution_documents(deps, chain, index)
        if not passages and not constitution:
            continue
        deps.gap_evidence_shown.add(key)
        deps.gap_evidence_retries += 1
        logger.warning(
            "chain_rejected case_id=%s gate=gap_evidence link=%s", deps.case_id, index + 1
        )
        raise ModelRetry(_gap_retry_message(chain, index, passages, constitution))


def _gap_key(chain: list[ChainLink], index: int) -> tuple[str, str]:
    """Identify one gap so a resubmitted gap is accepted, not challenged twice."""
    previous = chain[index - 1].documented_transaction
    current = chain[index].documented_transaction
    return (
        "|".join([previous.transaction_number or "", *previous.transferees]).casefold(),
        "|".join([current.transaction_number or "", *current.transferors]).casefold(),
    )


def _gap_evidence(deps: ChainDeps, chain: list[ChainLink], index: int) -> list[tuple[str, str]]:
    """Passages in already-read documents that may explain the gap before ``index``."""
    previous = chain[index - 1].documented_transaction
    later = name_words(chain[index].documented_transaction.transferors)
    anchors = _transaction_anchors(previous)
    earliest = chain[0].documented_transaction
    partition_owners = (
        set()
        if "partition" in earliest.transaction_type.casefold()
        else name_words([*earliest.transferors, *earliest.transferees])
    )
    found: list[tuple[str, str]] = []
    partitions: list[tuple[str, str]] = []
    cited = {ref.doc_id for ref in previous.source_refs}
    for doc_id, text in deps.texts.items():
        if not deps.fully_read(doc_id):
            continue
        label = _doc_label(deps, doc_id)
        if doc_id in cited and later:
            found += [
                (label, passage)
                for passage in _name_passages(
                    text, later, min(2, _GAP_IDENTITY_PASSAGES - len(found))
                )
            ]
        if later and anchors:
            found += [
                (label, passage)
                for passage in _identity_passages(
                    text, later, anchors, _GAP_IDENTITY_PASSAGES - len(found)
                )
            ]
        if partition_owners and len(partitions) < _GAP_PARTITION_PASSAGES:
            partitions += [
                (label, passage)
                for passage in _partition_passages(
                    text, partition_owners, _GAP_PARTITION_PASSAGES - len(partitions)
                )
            ]
    return found + partitions


def _doc_label(deps: ChainDeps, doc_id: str) -> str:
    """A document id with its filename, for a retry prompt."""
    document = deps.document(doc_id) or {}
    return f"{doc_id} ({document.get('filename') or 'no filename'})"


def _transaction_anchors(transaction: DocumentedTransaction) -> set[str]:
    """Numbers and party words that tie an earlier transfer to a later recital."""
    stated = " ".join(
        part
        for part in (
            transaction.transaction_number,
            transaction.executed_date,
            transaction.registration_date,
        )
        if part
    )
    return set(re.findall(r"\d{3,}", stated)) | name_words(
        [*transaction.transferors, *transaction.transferees]
    )


def _identity_passages(text: str, names: set[str], anchors: set[str], limit: int) -> list[str]:
    """Text around a later transferor's name that also contains an earlier anchor."""
    if limit <= 0:
        return []
    words = [
        (match.group(), match.start(), match.end())
        for match in re.finditer(r"[a-z]+|\d{3,}", text.casefold())
    ]
    anchor_spans = [(start, end) for word, start, end in words if word in anchors]
    if not anchor_spans:
        return []
    spans: list[tuple[int, int]] = []
    for word, start, end in words:
        if word not in names:
            continue
        left = max(0, start - _GAP_WINDOW_CHARS)
        right = min(len(text), end + _GAP_WINDOW_CHARS)
        if not any(
            left <= anchor_start
            and anchor_end <= right
            and (anchor_end <= start or anchor_start >= end)
            for anchor_start, anchor_end in anchor_spans
        ):
            continue
        # One shared name word is a weak clue; require two in the same passage.
        present = set(re.findall(r"[a-z]+", text[left:right].casefold())) & names
        if len(present) < 2:
            continue
        if spans and left <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], right))
        else:
            spans.append((left, right))
        if len(spans) >= limit:
            break
    return [text[left:right].strip() for left, right in spans[:limit]]


def _name_passages(text: str, names: set[str], limit: int) -> list[str]:
    """Text around the later transferor's name in the earlier transfer's own deed."""
    if limit <= 0:
        return []
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"[a-z]+", text.casefold()):
        if match.group() not in names:
            continue
        left = max(0, match.start() - _GAP_WINDOW_CHARS)
        right = min(len(text), match.end() + _GAP_WINDOW_CHARS)
        if spans and left <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], right))
        else:
            spans.append((left, right))
        if len(spans) >= limit:
            break
    return [text[left:right].strip() for left, right in spans[:limit]]


def _partition_passages(text: str, names: set[str], limit: int) -> list[str]:
    """Text around the earliest owner's name where a partition is recited."""
    if limit <= 0:
        return []
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"[a-z]+", text.casefold()):
        if match.group() not in names:
            continue
        left = max(0, match.start() - _GAP_WINDOW_CHARS)
        right = min(len(text), match.end() + _GAP_WINDOW_CHARS)
        if not re.search(r"\bpartitions?\b", text[left:right], re.IGNORECASE):
            continue
        if spans and left <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], right))
        else:
            spans.append((left, right))
        if len(spans) >= limit:
            break
    return [text[left:right].strip() for left, right in spans[:limit]]


def _unread_constitution_documents(
    deps: ChainDeps, chain: list[ChainLink], index: int
) -> list[str]:
    """Constitution documents still unread when a gap party is a firm or trust."""
    parties = [
        *chain[index].documented_transaction.transferors,
        *chain[index - 1].documented_transaction.transferees,
    ]
    if not has_entity_party(parties):
        return []
    return [
        f"{doc_id} ({document.get('document_type')})"
        for doc_id, document in deps.deeds.items()
        if document.get("document_type") in ENTITY_DOC_TYPES and not deps.fully_read(doc_id)
    ]


def _gap_retry_message(
    chain: list[ChainLink],
    index: int,
    passages: list[tuple[str, str]],
    constitution: list[str],
) -> str:
    """The retry prompt: what the gap is, the entity to resolve, and the passages."""
    previous = chain[index - 1].documented_transaction
    current = chain[index].documented_transaction
    earlier = previous.transaction_number or previous.executed_date or "the earlier transfer"
    later = current.transaction_number or current.executed_date or "the later transfer"
    parts = [f"Link {index + 1} ({later}) reports a gap after link {index} ({earlier})."]
    if constitution:
        parts.append(
            "This gap involves an entity. Read its constitution document to the end "
            f"before keeping the gap: {', '.join(constitution)}. If the entity's "
            f"partners or trustees are the people who acquired the property in link "
            f"{index}, no transfer to the entity occurred: set continues_previous "
            "true and explain the entity's composition in summary_points. If they are "
            "different owners, keep the gap."
        )
    if passages:
        quoted = "\n\n".join(f"{label}:\n...{passage}..." for label, passage in passages)
        parts.append(
            "Reconcile these passages from documents you already read before keeping "
            f"it:\n\n{quoted}\n\n"
            "When the earlier deed's own endorsement, signature or power-of-attorney "
            "text names the later transferor under the same transaction, and a later "
            "deed's recital names that transferor for the same transaction, the "
            "supported reading is one acquisition by the later transferor. An isolated "
            "contradictory name in the opening paragraph is then an OCR discrepancy, "
            "not a second owner: use the supported identity and explain the conflict "
            "in summary_points. Likewise, a recital-supported transfer, including a "
            "partition, belongs in the chain as its own link citing the deed that "
            "recites it."
        )
    parts.append("If the owners genuinely differ, resubmit the same gap.")
    return " ".join(parts)


def history_documents(documents: list[dict]) -> list[dict]:
    """The fully processed history documents among a case's documents."""
    return [
        document
        for document in documents
        if document.get("document_type") in CHAIN_HISTORY_DOC_TYPES
        and document.get("status") == "structured"
    ]


def title_deeds(documents: list[dict]) -> list[dict]:
    """The fully processed title deeds among a case's documents."""
    return [
        document
        for document in documents
        if _is_deed_type(str(document.get("document_type") or ""))
        and document.get("status") == "structured"
    ]


def _is_deed_type(document_type: str) -> bool:
    return document_type.endswith("_DEED") or document_type in CHAIN_DEED_DOC_TYPES


def build_chain(case_id: str, documents: list[dict]) -> dict:
    """Build the title chain, stamp ids, and save it.

    Args:
        case_id: The case to build the chain for.
        documents: All of the case's documents. Only its history documents and
            title deeds are shown to the builder.

    Returns:
        The saved chain: ``property_identity``, ``title_chain_graph``,
        ``title_chain`` (each link carrying its application-assigned ``tx_id``)
        and ``missing_documents``.

    Raises:
        ChainBuildError: The case has no history document, the model did not
            produce a valid chain within its budget, or the saved identity
            state could not be read.
    """
    history, deeds = history_documents(documents), title_deeds(documents)
    if not history:
        raise ChainBuildError("the case has no history document to build a chain from")
    deps = ChainDeps(
        case_id,
        history={document["doc_id"]: document for document in history},
        deeds={document["doc_id"]: document for document in deeds},
    )
    try:
        run = chain_agent.run_sync(
            _task(history, deeds),
            deps=deps,
            model=build_agent_model(),
            usage_limits=UsageLimits(request_limit=CLEARTITLE_CHAIN_MODEL_CALL_BUDGET),
        )
    except AgentRunError as error:
        raise ChainBuildError(f"the title chain was not built: {error}") from error
    result = run.output.model_dump()
    result["title_chain_graph"] = chain_graph(result["title_chain"])
    notes = _assign_identity(case_id, result["title_chain"])
    repo.save_phase_a_result(
        case_id=case_id, result=result, chain_doc_ids=sorted([*deps.history, *deps.deeds])
    )
    logger.info(
        "chain_built case_id=%s links=%s model_calls=%s deeds_read=%s identity_notes=%s",
        case_id,
        len(result["title_chain"]),
        run.usage.requests,
        sorted(doc_id for doc_id in deps.deeds if doc_id in deps.texts),
        notes,
    )
    return result


def chain_graph(chain: list[dict]) -> str:
    """Draw the chain as text: earliest owner at the top, current owner at the bottom.

    A link that does not continue the one before it is drawn after a dotted
    break, so a gap in the records is visible instead of looking like a transfer.
    """
    lines: list[str] = []
    for index, link in enumerate(chain):
        transaction = link["documented_transaction"]
        continues = index > 0 and link["continues_previous"]
        if index > 0 and not continues:
            lines += [
                _GAP_MARK,
                f"{_GAP_MARK} No recorded transfer connects these owners",
                _GAP_MARK,
            ]
        if not continues:
            lines.append(", ".join(transaction["transferors"]) or "Earlier owner not recorded")
        reference = " / ".join(
            part
            for part in (
                transaction["executed_date"] or transaction["registration_date"],
                transaction["transaction_number"],
            )
            if part
        )
        label = transaction["transaction_type"] + (f" — {reference}" if reference else "")
        lines += ["        │", f"        │ {label}", "        ▼"]
        lines.append(", ".join(transaction["transferees"]))
    return "\n".join(lines)


def _task(history: list[dict], deeds: list[dict]) -> str:
    history_lines = [
        f"- {document['doc_id']} | {document.get('document_type')} | "
        f"filename: {document.get('filename')}"
        for document in history
    ]
    deed_lines = [
        f"- {document['doc_id']} | {document.get('document_type')} | "
        f"filename: {document.get('filename')} | "
        f"summary: {document.get('summary') or '(no summary)'}"
        for document in deeds
    ]
    return "\n".join(
        [
            _SKILL_PATH.read_text(encoding="utf-8"),
            "",
            load_prompt("title_chain_task"),
            "",
            "--- HISTORY DOCUMENTS (read every one to the end) ---",
            *history_lines,
            "",
            "--- TITLE DEEDS (open one only to extend or confirm a link) ---",
            *(deed_lines or ["None uploaded."]),
        ]
    )


def _assign_identity(case_id: str, chain: list[dict]) -> list[str]:
    """Stamp stable transaction ids and upstream links onto the chain, in place.

    A link that matches a previously saved link keeps its id, so a rebuilt chain
    keeps the same transaction identity. The saved state is read strictly: an
    unreadable history is unknown, not empty, and numbering from empty could
    hand a saved id to another transaction.
    """
    try:
        prior_chain = repo.get_persisted_title_chain_entries(case_id)
    except Exception as error:
        raise ChainBuildError(
            f"cannot safely assign transaction ids; nothing was saved: {error}"
        ) from error
    notes = chain_identity.assign_chain_tx_ids(chain, prior_chain, set())
    return notes + chain_identity.attach_upstream_ids(chain)
