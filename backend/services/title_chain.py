"""LLM-driven title-tree construction for a case (SALE_DEED + EC ledger).

One Gemini call reads the Sale Deed's property schedule and every EC ledger
entry's property description, classifies each matched entry's role in the title
tree (THE_SD / PREDECESSOR_TITLE / SUBSEQUENT_TRANSFER / DIVERGENT_BRANCH /
ENCUMBRANCE), and explains how the pieces connect. Deterministic code then
merges that enrichment onto the ledger entries and sorts them chronologically.
"""

from __future__ import annotations

import json
from datetime import datetime

from backend.database.repositories.document_repo import get_case_bundle
from backend.database.repositories.title_chain_repo import save_title_chain
from backend.integrations.llm.analysis_executor import run_analysis
from backend.logger import get_logger
from backend.prompts.loader import load_prompt, load_schema
from backend.shared.constants import (
    ENCUMBRANCE_CERTIFICATE,
    SALE_DEED,
    STATUS_NO_TRANSACTIONS,
)

logger = get_logger(__name__)

MATCH_RESPONSE_SCHEMA = load_schema("title_chain_schema")
_TITLE_CHAIN_PROMPT_TEMPLATE = load_prompt("title_chain")

NO_EC_TRANSACTIONS_MESSAGE = (
    "There are no transactions existing for this property in EC. "
    "Please upload a valid EC."
)

NO_MATCHING_PROPERTY_MESSAGE = (
    "No transactions registered related to this property details in the "
    "Encumbrance Certificate. The EC may belong to a different property."
)

CHAIN_ROLES = {
    "THE_SD",
    "PREDECESSOR_TITLE",
    "SUBSEQUENT_TRANSFER",
    "DIVERGENT_BRANCH",
    "ENCUMBRANCE",
    "UNRELATED",
}

ENCUMBRANCE_KEYWORDS = ("mortgage", "lease", "agreement", "cancellation", "dtd", "charge", "deposit")


def _is_ec(doc: dict) -> bool:
    return (doc.get("document_type") or "").upper() == ENCUMBRANCE_CERTIFICATE


def _is_sale_deed(doc: dict) -> bool:
    return (doc.get("document_type") or "").upper() == SALE_DEED


def _parse_date(value) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return value
    return str(value)


def _sd_identity(sd_data: dict) -> dict:
    """Deterministic projection of what the Sale Deed conveys."""
    fm = sd_data.get("file_metadata") or {}
    ps = sd_data.get("property_schedule") or {}
    return {
        "registration_reference": fm.get("registration_number"),
        "execution_date": fm.get("execution_date"),
        "survey_number": ps.get("survey_number"),
        "cts_number": ps.get("cts_number"),
        "plot_or_site_number": ps.get("apartment_or_shop_number"),
        "conveyed_interest": ps.get("full_schedule_description"),
    }


def _is_sale_deed_entry(entry: dict, sd_identity: dict) -> bool:
    reg = (entry.get("registration_reference") or "").strip().lower()
    sd_reg = (sd_identity.get("registration_reference") or "").strip().lower()
    if reg and sd_reg and reg == sd_reg:
        return True
    e_date = _parse_date(entry.get("execution_date"))
    sd_date = _parse_date(sd_identity.get("execution_date")) if sd_identity.get("execution_date") else None
    return bool(e_date and sd_date and e_date == sd_date)


def _is_encumbrance_type(transaction_type) -> bool:
    ttype = (transaction_type or "").lower()
    return any(k in ttype for k in ENCUMBRANCE_KEYWORDS)


def _fallback_role(entry: dict, sd_identity: dict) -> str:
    """Deterministic role when the LLM did not classify an entry."""
    if _is_sale_deed_entry(entry, sd_identity):
        return "THE_SD"
    if _is_encumbrance_type(entry.get("transaction_type")):
        return "ENCUMBRANCE"
    e_date = _parse_date(entry.get("execution_date"))
    sd_date = _parse_date(sd_identity.get("execution_date")) if sd_identity.get("execution_date") else None
    if e_date and sd_date and e_date > sd_date:
        return "SUBSEQUENT_TRANSFER"
    return "PREDECESSOR_TITLE"


BACKWARD_KEYWORDS = ("cancellation", "reconveyance", "revocation", "restitution", "surrender")


def _normalize_edge_type(raw) -> str | None:
    if not raw:
        return None
    v = str(raw).lower()
    if "backward" in v or "reverse" in v:
        return "backward"
    if "branch" in v or "side" in v:
        return "branch"
    if "forward" in v:
        return "forward"
    return None


def _fallback_edge_type(entry: dict) -> str:
    """Deterministic edge type when the LLM did not provide one."""
    role = str(entry.get("chain_role") or "").upper()
    if role in ("ENCUMBRANCE", "DIVERGENT_BRANCH"):
        return "branch"
    ttype = (entry.get("transaction_type") or "").lower()
    if any(k in ttype for k in BACKWARD_KEYWORDS):
        return "backward"
    return "forward"


def _normalize_graph_from(raw, last_main_idx: int | None) -> str | int | None:
    if raw is None:
        return last_main_idx if last_main_idx is not None else "root"
    if isinstance(raw, bool):
        return last_main_idx if last_main_idx is not None else "root"
    if isinstance(raw, int):
        return raw
    s = str(raw).strip()
    if s.lower() == "root":
        return "root"
    try:
        return int(s)
    except (TypeError, ValueError):
        return last_main_idx if last_main_idx is not None else "root"


def _default_identity(entry: dict) -> str:
    pd = entry.get("property_details") or {}
    parts = []
    if entry.get("parent_survey_number_raw"):
        parts.append(f"Survey: {entry['parent_survey_number_raw']}")
    if pd.get("plot_no"):
        parts.append(f"Plot: {pd['plot_no']}")
    if pd.get("cts_no"):
        parts.append(f"CTS: {pd['cts_no']}")
    if entry.get("locality_raw"):
        parts.append(str(entry["locality_raw"]))
    return "; ".join(parts)


def _default_portion(entry: dict) -> str:
    frac = entry.get("share_fraction")
    pd = entry.get("property_details") or {}
    desc = (pd.get("description") or "").strip()
    if frac:
        return f"{frac} share"
    if desc:
        return desc[:140]
    return "Whole property"


def _default_explanation(entry: dict, sd_identity: dict) -> str:
    pd = entry.get("property_details") or {}
    desc = (pd.get("description") or "").strip()
    role = entry.get("chain_role")
    if role == "THE_SD":
        return "This is the Sale Deed itself — the document being verified."
    if role == "ENCUMBRANCE":
        return "Non-title document (e.g. mortgage/lease/agreement) registered against the property."
    if role == "DIVERGENT_BRANCH":
        return "Transaction on the same property but a different share/portion than what the Sale Deed conveys."
    if role == "SUBSEQUENT_TRANSFER":
        return "Transfer of the same property/portion executed after the Sale Deed — review for title conflict."
    if desc:
        return f"Earlier transaction on the property: {desc[:160]}"
    return "Earlier transaction on the property."


def build_title_chain(case_id: str) -> dict:
    """Build + persist the title chain. Returns the saved chain record."""
    bundle = get_case_bundle(case_id)

    sale_deed = next((d for d in bundle if _is_sale_deed(d)), None)
    ec = next((d for d in bundle if _is_ec(d)), None)

    if not sale_deed:
        logger.warning("Title chain skipped for case %s: no SALE_DEED in bundle", case_id)
        save_title_chain(case_id=case_id, status="error", source={"bundle": [d.get("document_type") for d in bundle]})
        return {"case_id": case_id, "status": "error", "chain": []}

    if not ec:
        logger.warning("Title chain %s for case %s: no ENCUMBRANCE_CERTIFICATE in bundle", STATUS_NO_TRANSACTIONS, case_id)
        save_title_chain(
            case_id=case_id, status=STATUS_NO_TRANSACTIONS, chain=[],
            source={
                "sale_deed_doc_id": sale_deed["doc_id"], "ec_doc_id": None,
                "message": NO_EC_TRANSACTIONS_MESSAGE,
            },
        )
        return {
            "case_id": case_id,
            "status": STATUS_NO_TRANSACTIONS,
            "chain": [],
            "message": NO_EC_TRANSACTIONS_MESSAGE,
        }

    sd_data = sale_deed.get("structured_json") or {}
    ec_data = ec.get("structured_json") or {}
    ledger = ec_data.get("historical_ledger") or []

    if not ledger:
        logger.warning("Title chain %s for case %s: EC has no historical_ledger", STATUS_NO_TRANSACTIONS, case_id)
        save_title_chain(
            case_id=case_id, status=STATUS_NO_TRANSACTIONS, chain=[],
            source={
                "sale_deed_doc_id": sale_deed["doc_id"], "ec_doc_id": ec["doc_id"],
                "message": NO_EC_TRANSACTIONS_MESSAGE,
            },
        )
        return {
            "case_id": case_id,
            "status": STATUS_NO_TRANSACTIONS,
            "chain": [],
            "message": NO_EC_TRANSACTIONS_MESSAGE,
        }

    indexed_entries = [
        {**entry, "_idx": entry.get("transaction_index", i + 1)}
        for i, entry in enumerate(ledger)
    ]

    prompt = (
        _TITLE_CHAIN_PROMPT_TEMPLATE + "\n\n"
        "--- SALE DEED ---\n"
        f"{json.dumps(sd_data, ensure_ascii=False, default=str)}\n\n"
        "--- EC HISTORICAL LEDGER ---\n"
        f"{json.dumps(ledger, ensure_ascii=False, default=str)}"
    )

    try:
        response = run_analysis(prompt, task="title_chain", response_schema=MATCH_RESPONSE_SCHEMA)
    except Exception as e:
        logger.error("Title chain LLM call failed for case %s: %s", case_id, e)
        save_title_chain(
            case_id=case_id, status="error",
            source={"sale_deed_doc_id": sale_deed["doc_id"], "ec_doc_id": ec["doc_id"]},
        )
        return {"case_id": case_id, "status": "error", "chain": [], "error": str(e)}

    result = response.get("result", {})
    sd_identity = _sd_identity(sd_data)

    raw_entries = result.get("transactions") or []
    enrichment = {}
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        tx_idx = item.get("transaction_index")
        if tx_idx is None:
            continue
        try:
            idx = int(tx_idx)
        except (TypeError, ValueError):
            continue
        role = str(item.get("chain_role", "")).upper()
        if role not in CHAIN_ROLES:
            role = ""
        enrichment[idx] = {
            "chain_role": role,
            "edge_type": _normalize_edge_type(item.get("edge_type")),
            "graph_from": item.get("graph_from"),
            "portion": item.get("portion"),
            "share_fraction": item.get("share_fraction"),
            "property_identity": item.get("property_identity"),
            "explanation": item.get("explanation"),
        }

    raw_indexes = result.get("matched_transaction_indexes") or []
    matched_indexes = set()
    for idx in raw_indexes:
        try:
            matched_indexes.add(int(idx))
        except (TypeError, ValueError):
            continue
    matched_indexes.update(idx for idx, meta in enrichment.items() if meta["chain_role"] != "UNRELATED")

    matched_entries = [e for e in indexed_entries if e.get("_idx") in matched_indexes]

    if not matched_entries and not raw_entries:
        title_story = result.get("title_story") or NO_MATCHING_PROPERTY_MESSAGE
        save_title_chain(
            case_id=case_id, status="complete", chain=[],
            source={
                "sale_deed_doc_id": sale_deed["doc_id"], "ec_doc_id": ec["doc_id"],
                "sd_property": result.get("sd_property") or sd_identity,
                "title_story": title_story,
                "message": NO_MATCHING_PROPERTY_MESSAGE,
            },
        )
        return {
            "case_id": case_id,
            "status": "complete",
            "chain": [],
            "sd_property": result.get("sd_property") or sd_identity,
            "title_story": title_story,
        }

    if not matched_entries:
        matched_entries = list(indexed_entries)

    matched_entries.sort(
        key=lambda e: (_parse_date(e.get("execution_date")) or "", int(e.get("_idx") or 0))
    )

    chain = []
    last_main_idx: int | None = None
    for e in matched_entries:
        entry = {k: v for k, v in e.items() if k != "_idx"}
        idx = e.get("_idx")
        entry["transaction_index"] = idx
        meta = enrichment.get(idx) or {}
        if meta.get("chain_role") == "UNRELATED":
            continue
        entry["chain_role"] = meta.get("chain_role") or _fallback_role(e, sd_identity)
        entry["is_sale_deed_entry"] = entry["chain_role"] == "THE_SD"
        entry["is_title_transfer"] = entry["chain_role"] != "ENCUMBRANCE"
        entry["portion"] = meta.get("portion") or _default_portion(e)
        entry["share_fraction"] = meta.get("share_fraction") or e.get("share_fraction")
        entry["property_identity"] = meta.get("property_identity") or _default_identity(e)
        entry["explanation"] = meta.get("explanation") or _default_explanation(entry, sd_identity)
        edge_type = meta.get("edge_type") or _fallback_edge_type(entry)
        graph_from = _normalize_graph_from(meta.get("graph_from"), last_main_idx)
        entry["edge_type"] = edge_type
        entry["graph_from"] = graph_from
        chain.append(entry)
        if entry["chain_role"] != "ENCUMBRANCE":
            last_main_idx = idx

    save_title_chain(
        case_id=case_id, status="complete", chain=chain,
        source={
            "sale_deed_doc_id": sale_deed["doc_id"], "ec_doc_id": ec["doc_id"],
            "sd_property": result.get("sd_property") or sd_identity,
            "title_story": result.get("title_story"),
        },
    )

    logger.info("Title chain built for case %s: %d entries", case_id, len(chain))
    return {
        "case_id": case_id,
        "status": "complete",
        "chain": chain,
        "sd_property": result.get("sd_property") or sd_identity,
        "title_story": result.get("title_story"),
    }
