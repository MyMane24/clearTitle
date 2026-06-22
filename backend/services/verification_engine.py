"""
Verification Engine — LangGraph with one main Gemini agent + deterministic tool functions.
Agent decides which checks to run, runs Python tools, reviews results, records findings.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from backend.logger import get_logger
from backend.services import vector_store as vs
from backend.services.mysql_store import (
    get_case_bundle,
    create_verification_report,
    update_verification_report,
    get_verification_report,
    store_feedback,
    create_training_record,
    update_training_record_with_feedback,
    mark_feedback_embedded,
)
from backend.services.verification_tools import (
    verify_sale_deed,
    verify_gift_deed,
    verify_encumbrance_certificate,
    verify_property_register_card,
    verify_tax_receipt,
    verify_property_identity,
    verify_ownership_chain,
    check_red_flags,
)

load_dotenv()

logger = get_logger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_AGENT_STEPS = 40


# ── Types ───────────────────────────────────────────────────────────────

class GraphState(TypedDict):
    case_id: str
    documents: dict[str, dict]
    doc_type_map: dict[str, str]
    doc_list: list[dict]
    docs_json: str
    docs_summary: str
    findings: list[dict]
    messages: list[Any]
    verdict: str
    final_report: str
    step_count: int
    called_tools: list[str]


# ── Tool declarations ───────────────────────────────────────────────────

TOOL_DECLARATIONS = [
    # ── Layer 1: Per-document verification ──
    {
        "name": "verify_sale_deed",
        "description": "Verify SALE_DEED: registration details, parties, property schedule, financials (stamp duty %, registration fees), statutory valuation.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "verify_gift_deed",
        "description": "Verify GIFT_DEED: donors, donees, execution/registration dates, property schedule.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "verify_encumbrance_certificate",
        "description": "Verify ENCUMBRANCE_CERTIFICATE: application details, search period, transaction chain, gaps >3 years, pending mortgages.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "verify_property_register_card",
        "description": "Verify PROPERTY_REGISTER_CARD: city survey number, area, tenure, holders, guidance value, mutation entries.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "verify_tax_receipt",
        "description": "Verify E_PAYMENT_RECEIPT: owner name, PID, transaction status, receipt date, assessment year, amount.",
        "parameters": {"type": "object", "properties": {}},
    },
    # ── Layer 2: Cross-document verification ──
    {
        "name": "verify_property_identity",
        "description": "Cross-check Survey No, CTS No, PID across ALL documents for consistency.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "verify_ownership_chain",
        "description": "Cross-check ownership chain: EC last transaction → deed transferor/transferee → PRC holder.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "check_red_flags",
        "description": "Cross-check red flags: missing critical docs, agricultural conversion, missing Khata, deed date after EC coverage.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "query_past_learnings",
        "description": "Search vector DB for how similar issues were resolved before.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Describe the situation you want to look up"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "add_finding",
        "description": "Record a finding returned by a verification tool. You MUST call this for EVERY finding — do not skip, do not filter.",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [
                        "PROPERTY_MISMATCH", "OWNERSHIP_GAP", "OWNERSHIP_MISMATCH",
                        "DATE_INCONSISTENCY", "FINANCIAL_MISMATCH", "PENDING_MORTGAGE",
                        "EC_GAP", "MUTATION_PENDING", "CONVERSION_MISSING",
                        "TAX_DEFAULT", "GUIDANCE_VALUE_ISSUE", "MISSING_DOCUMENT",
                        "SUSPICIOUS_PATTERN", "TOOL_ERROR",
                    ],
                },
                "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                "doc_ids": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
                "suggestion": {"type": "string"},
            },
            "required": ["type", "severity", "doc_ids", "summary"],
        },
    },
    {
        "name": "finalize_report",
        "description": "Complete verification with verdict and detailed narrative report with reasoning.",
        "parameters": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string", "enum": ["PASS", "FLAGGED"],
                    "description": "PASS = no high-severity issues, FLAGGED = action needed",
                },
                "final_report": {
                    "type": "string",
                    "description": "Detailed narrative: docs reviewed, each finding with legal reasoning, overall assessment, recommendations",
                },
            },
            "required": ["verdict", "final_report"],
        },
    },
]

GEMINI_TOOLS = [types.Tool(function_declarations=TOOL_DECLARATIONS)]


# ── Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the SENIOR VERIFICATION OFFICER — 20 years experience in Karnataka property law.

DOCUMENTS IN THIS CASE:
{docs_json}

YOUR ROLE IS STRICTLY LIMITED:
1. Call EVERY applicable verification tool (listed below) — do NOT skip any.
2. For EVERY finding returned by a tool, call add_finding() — do NOT skip, filter, or judge any finding as "not relevant."
3. Call query_past_learnings if you need additional context.
4. After ALL tools are called and ALL findings are recorded, write the narrative report via finalize_report().
5. You do NOT decide the verdict — it is auto-derived from findings.

MANDATORY TOOLS — call EVERY tool that applies to the document types present:

LAYER 1 — Per-document (call for each matching document type):
  verify_sale_deed()             — required if SALE_DEED is present
  verify_gift_deed()             — required if GIFT_DEED is present
  verify_encumbrance_certificate() — required if ENCUMBRANCE_CERTIFICATE is present
  verify_property_register_card() — required if PROPERTY_REGISTER_CARD is present
  verify_tax_receipt()           — required if E_PAYMENT_RECEIPT / TAX_RECEIPT is present

LAYER 2 — Cross-document (call after Layer 1):
  verify_property_identity()     — required if 2+ documents exist
  verify_ownership_chain()       — required if deed + EC/PRC exist
  check_red_flags()              — always required

STRICT RULES — violation will cause verification failure:
- You MUST call add_finding(type, severity, doc_ids, summary, suggestion) for EVERY finding in every tool result.
- Do NOT skip add_finding() — even if you think a finding is minor or incorrect. Record it.
- Do NOT decide a tool result is "not applicable." The tool knows what fields to check.
- Do NOT call finalize_report() until ALL mandatory tools have been called and ALL findings recorded.
- The verdict parameter in finalize_report() is IGNORED — it will be auto-derived. Write an empty string or "AUTO".
- The final_report must be a detailed narrative covering: documents reviewed, each finding with legal context, overall assessment, and recommendations.

WORKFLOW SUMMARY:
  Layer 1 tools → add_finding for each result → Layer 2 tools → add_finding for each result → finalize_report()
  You must complete ALL steps before calling finalize_report()."""


# ── Tool execution (deterministic Python) ───────────────────────────────

TOOL_FUNCTIONS = {
    "verify_sale_deed": lambda s: verify_sale_deed(s["documents"], s["doc_type_map"]),
    "verify_gift_deed": lambda s: verify_gift_deed(s["documents"], s["doc_type_map"]),
    "verify_encumbrance_certificate": lambda s: verify_encumbrance_certificate(s["documents"], s["doc_type_map"]),
    "verify_property_register_card": lambda s: verify_property_register_card(s["documents"], s["doc_type_map"]),
    "verify_tax_receipt": lambda s: verify_tax_receipt(s["documents"], s["doc_type_map"]),
    "verify_property_identity": lambda s: verify_property_identity(s["documents"], s["doc_type_map"]),
    "verify_ownership_chain": lambda s: verify_ownership_chain(s["documents"], s["doc_type_map"]),
    "check_red_flags": lambda s: check_red_flags(s["documents"], s["doc_type_map"]),
}


# ── LangGraph nodes ─────────────────────────────────────────────────────

def _call_agent(state: GraphState) -> dict:
    """Call Gemini with current conversation. Returns next action or final."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=state["messages"],
                config=types.GenerateContentConfig(
                    tools=GEMINI_TOOLS,
                    system_instruction=SYSTEM_PROMPT.format(docs_json=state["docs_json"]),
                    temperature=0.1,
                ),
            )
            break
        except Exception as e:
            if attempt < 2:
                import time
                e_str = str(e)
                retry_after = None
                m = re.search(r'retryDelay["\']:\s*["\']?(\d+)', e_str)
                if m:
                    retry_after = int(m.group(1))
                time.sleep(retry_after or (2 ** attempt))
            else:
                return {
                    "messages": state["messages"] + [types.Content(
                        role="user",
                        parts=[types.Part(text=f"[System: API error after 3 retries: {e}]")]
                    )],
                    "verdict": "FLAGGED",
                    "final_report": f"Verification failed due to API error: {e}",
                }

    candidate = response.candidates[0] if response.candidates else None
    if not candidate:
        return {"verdict": "UNKNOWN", "final_report": "No response from model"}

    content = candidate.content
    return {"messages": state["messages"] + [content]}


def _route_agent(state: GraphState) -> Literal["tools", "__end__"]:
    """After agent responds, route to tools or end."""
    if state.get("step_count", 0) >= MAX_AGENT_STEPS:
        return "__end__"

    last_msg = state["messages"][-1] if state["messages"] else None
    if not last_msg:
        return "__end__"

    for part in last_msg.parts:
        if part.function_call and part.function_call.name == "finalize_report":
            return "__end__"

    return "tools"


def _run_tools(state: GraphState) -> dict:
    """Execute the tool the agent requested, return results to messages."""
    last_msg = state["messages"][-1]
    updates = {"step_count": state.get("step_count", 0) + 1}
    messages = list(state["messages"])
    findings = list(state.get("findings", []))
    called_tools = set(state.get("called_tools", []))

    for part in last_msg.parts:
        if not part.function_call:
            continue

        fc = part.function_call
        args = {k: v for k, v in fc.args.items()}

        if fc.name in TOOL_FUNCTIONS:
            called_tools.add(fc.name)
            try:
                tool_results = TOOL_FUNCTIONS[fc.name](state)
            except Exception as e:
                tool_results = [{
                    "type": "TOOL_ERROR", "severity": "low",
                    "doc_ids": [], "summary": f"{fc.name} crashed: {e}",
                    "suggestion": "Re-run verification",
                }]

            messages.append(types.Content(
                role="user",
                parts=[types.Part(function_response=types.FunctionResponse(
                    name=fc.name,
                    response={"findings": tool_results},
                ))],
            ))

        elif fc.name == "add_finding":
            finding = {
                "type": args.get("type", "UNKNOWN"),
                "severity": args.get("severity", "medium"),
                "doc_ids": args.get("doc_ids", []),
                "summary": args.get("summary", ""),
                "suggestion": args.get("suggestion", ""),
                "source_agent": "senior",
            }
            findings.append(finding)
            messages.append(types.Content(
                role="user",
                parts=[types.Part(function_response=types.FunctionResponse(
                    name="add_finding",
                    response={"status": "recorded", "total": len(findings)},
                ))],
            ))

        elif fc.name == "query_past_learnings":
            try:
                vs.initialize()
                results = vs.search(args.get("query", ""), top_k=3)
                learning_texts = [r.get("text", "") for r in results if r.get("text")]
                response_data = {"learnings": learning_texts or ["No relevant past learnings found"]}
            except Exception as e:
                response_data = {"learnings": [], "error": str(e)}

            messages.append(types.Content(
                role="user",
                parts=[types.Part(function_response=types.FunctionResponse(
                    name="query_past_learnings",
                    response=response_data,
                ))],
            ))

        elif fc.name == "finalize_report":
            updates["verdict"] = args.get("verdict", "UNKNOWN")
            updates["final_report"] = args.get("final_report", "")

    updates["messages"] = messages
    updates["findings"] = findings
    updates["called_tools"] = sorted(called_tools)
    return updates


def _finalize(state: GraphState) -> dict:
    """Extract verdict from the agent's finalize_report call."""
    last_msg = state["messages"][-1]
    for part in last_msg.parts:
        if part.function_call and part.function_call.name == "finalize_report":
            args = {k: v for k, v in part.function_call.args.items()}
            return {
                "verdict": args.get("verdict", "UNKNOWN"),
                "final_report": args.get("final_report", ""),
            }
    return {"verdict": "UNKNOWN", "final_report": ""}


# ── Build graph ─────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    graph = StateGraph(GraphState)

    graph.add_node("agent", _call_agent)
    graph.add_node("tools", _run_tools)
    graph.add_node("finalize", _finalize)

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        _route_agent,
        {"tools": "tools", "__end__": "finalize"},
    )

    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)

    return graph.compile()


_compiled_graph = None


def _get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph()
    return _compiled_graph


# ── Public API ──────────────────────────────────────────────────────────

def run_verification(case_id: str) -> dict:
    """
    Run verification via LangGraph.
    Returns the final report dict with verdict, findings, summary.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set")

    docs = get_case_bundle(case_id)
    documents = {}
    doc_type_map = {}
    doc_list = []

    for d in docs:
        doc_id = d["doc_id"]
        doc_type = d.get("document_type", "UNKNOWN")
        structured = d.get("structured_json", {})
        if isinstance(structured, str):
            structured = json.loads(structured)
        if not isinstance(structured, dict):
            structured = {}
        documents[doc_id] = structured
        doc_type_map[doc_id] = doc_type
        doc_list.append({
            "doc_id": doc_id,
            "filename": d.get("filename", ""),
            "document_type": doc_type,
        })

    # Build docs JSON (for system prompt)
    input_documents = {
        "documents": documents,
        "document_types": doc_type_map,
        "doc_list": doc_list,
    }
    docs_json = json.dumps(input_documents, indent=2, ensure_ascii=False)

    doc_lines = [f"  - {d['doc_id']}: {d['document_type']} ({d['filename']})" for d in doc_list]
    docs_summary = "\n".join(doc_lines)

    # Initial message
    messages = [types.Content(
        role="user",
        parts=[types.Part(text="Begin verification. Run all relevant checks and produce a final report.")]
    )]

    state: GraphState = {
        "case_id": case_id,
        "documents": documents,
        "doc_type_map": doc_type_map,
        "doc_list": doc_list,
        "docs_json": docs_json,
        "docs_summary": docs_summary,
        "findings": [],
        "messages": messages,
        "verdict": "UNKNOWN",
        "final_report": "",
        "step_count": 0,
        "called_tools": [],
    }

    # Quick API availability check
    api_available = True
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        client.models.generate_content(
            model=GEMINI_MODEL, contents=["ok"],
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=10),
        )
    except Exception as e:
        logger.warning("Gemini API availability check failed: %s", e)
        api_available = False

    if api_available:
        graph = _get_graph()
        try:
            result = graph.invoke(state, {"recursion_limit": MAX_AGENT_STEPS + 5})
        except Exception as e:
            result = {**state, "verdict": "FLAGGED", "final_report": f"Verification error: {e}"}
    else:
        # Fallback: run all deterministic tools directly
        from backend.services.verification_tools import (
            verify_sale_deed, verify_gift_deed, verify_encumbrance_certificate,
            verify_property_register_card, verify_tax_receipt,
            verify_property_identity, verify_ownership_chain, check_red_flags,
        )
        tool_fns = [
            ("verify_sale_deed", verify_sale_deed),
            ("verify_gift_deed", verify_gift_deed),
            ("verify_encumbrance_certificate", verify_encumbrance_certificate),
            ("verify_property_register_card", verify_property_register_card),
            ("verify_tax_receipt", verify_tax_receipt),
            ("verify_property_identity", verify_property_identity),
            ("verify_ownership_chain", verify_ownership_chain),
            ("check_red_flags", check_red_flags),
        ]
        fallback_findings = []
        for fn_name, fn in tool_fns:
            try:
                results = fn(documents, doc_type_map)
                fallback_findings.extend(results)
            except Exception as e:
                logger.warning("Fallback tool %s failed: %s", fn_name, e)

        # Auto-derive verdict
        has_high = any(f.get("severity") == "high" for f in fallback_findings)
        fallback_verdict = "FLAGGED" if has_high else "PASS"

        # Build report lines
        lines = [f"Verification run in offline mode (Gemini API unavailable)."]
        lines.append(f"Reviewed {len(doc_list)} documents via deterministic tools.")
        if fallback_findings:
            lines.append("")
            lines.append("Findings:")
            for f in fallback_findings:
                sev = f.get("severity", "?").upper()
                lines.append(f"- [{sev}] {f.get('type', '?')}: {f.get('summary', '')}")
                if f.get("suggestion"):
                    lines.append(f"  Suggestion: {f['suggestion']}")
        else:
            lines.append("No issues found across all documents.")

        result = {
            **state,
            "findings": fallback_findings,
            "verdict": fallback_verdict,
            "final_report": "\n".join(lines),
            "called_tools": sorted(TOOL_FUNCTIONS.keys()),
        }

    # ── Safety net: run any verification tools the agent didn't call ──
    called = set(result.get("called_tools", []))
    all_tool_names = set(TOOL_FUNCTIONS.keys())
    uncalled = all_tool_names - called
    safety_net_findings = []
    if uncalled:
        for tool_name in sorted(uncalled):
            try:
                extra = TOOL_FUNCTIONS[tool_name](result)
                safety_net_findings.extend(extra)
            except Exception as e:
                logger.warning("Safety-net tool %s failed: %s", tool_name, e)

    # Merge safety net findings into main findings (deduplicate by type+severity+summary)
    existing_keys = set()
    merged = []
    for f in result.get("findings", []):
        key = (f.get("type"), f.get("severity"), f.get("summary"))
        existing_keys.add(key)
        merged.append(f)
    for f in safety_net_findings:
        key = (f.get("type"), f.get("severity"), f.get("summary"))
        if key not in existing_keys:
            existing_keys.add(key)
            merged.append(f)

    findings = merged

    # ── Auto-derive verdict (always overrides agent-set verdict) ──
    has_high = any(f.get("severity") == "high" for f in findings)
    final_verdict = "FLAGGED" if has_high else "PASS"
    final_report_text = result.get("final_report", "")

    high_count = sum(1 for f in findings if f.get("severity") == "high")
    med_count = sum(1 for f in findings if f.get("severity") == "medium")
    low_count = sum(1 for f in findings if f.get("severity") == "low")

    report = {
        "case_id": case_id,
        "verdict": final_verdict,
        "summary": {
            "total_documents": len(doc_list),
            "document_types": sorted(set(doc_type_map.values())),
            "documents": doc_list,
            "total_findings": len(findings),
            "high_severity": high_count,
            "medium_severity": med_count,
            "low_severity": low_count,
        },
        "findings": findings,
        "final_report": final_report_text,
        "metadata": {
            "model": GEMINI_MODEL,
            "tools_available": list(TOOL_FUNCTIONS.keys()),
            "tools_called_by_agent": sorted(called),
            "tools_auto_run_safety_net": sorted(uncalled),
        },
    }

    # Save report to MySQL
    try:
        create_verification_report(case_id=case_id, report_json=report)
    except Exception as e:
        report["save_error"] = str(e)

    # Training record
    try:
        create_training_record(
            case_id=case_id,
            input_documents=input_documents,
            agent_report=report,
        )
    except Exception as e:
        logger.warning("Failed to create training record for %s: %s", case_id, e)

    return report


def submit_human_feedback(case_id: str, feedback_data: list[dict]) -> None:
    """Process human feedback: store in vector DB + update training record."""
    vs.initialize()

    for fb in feedback_data:
        text_parts = []
        if fb.get("finding_type"):
            text_parts.append(f"Type: {fb['finding_type']}")
        if fb.get("original_flag"):
            text_parts.append(f"Flag: {fb['original_flag']}")
        if fb.get("human_correction"):
            text_parts.append(f"Correction: {fb['human_correction']}")
        if fb.get("reason"):
            text_parts.append(f"Reason: {fb['reason']}")

        text = " | ".join(text_parts)
        metadata = {
            "case_id": case_id,
            "finding_type": fb.get("finding_type", ""),
            "accepted": fb.get("accepted", True),
        }
        try:
            vs.add_learning(text, metadata)
        except Exception as e:
            logger.warning("Failed to store learning in vector DB: %s", e)

    try:
        for fb in feedback_data:
            if fb.get("id"):
                mark_feedback_embedded(fb["id"])
    except Exception as e:
        logger.warning("Failed to mark feedback as embedded: %s", e)

    # Build corrected report from feedback
    try:
        report = get_verification_report(case_id)
        if not report:
            return
        existing = report.get("report_json", {})
        if isinstance(existing, str):
            existing = json.loads(existing)

        corrected_findings = []
        feedback_map = {}
        for fb in feedback_data:
            key = fb.get("original_flag", "")
            feedback_map[key] = fb

        for finding in existing.get("findings", []):
            key = finding.get("summary", "")
            if key in feedback_map:
                fb = feedback_map[key]
                if fb.get("accepted", True):
                    corrected_findings.append(finding)
            else:
                corrected_findings.append(finding)

        corrected_verdict = "PASS" if all(
            f.get("severity") != "high" for f in corrected_findings
        ) else "FLAGGED"

        corrected_report = {**existing, "findings": corrected_findings, "verdict": corrected_verdict}

        existing["summary"]["verdict"] = "REVIEWED"
        existing["human_feedback"] = feedback_data
        update_verification_report(case_id, existing, status="reviewed")

        update_training_record_with_feedback(
            case_id=case_id,
            human_feedback=feedback_data,
            corrected_report=corrected_report,
        )
    except Exception as e:
        logger.warning("Failed to update training record with feedback: %s", e)
