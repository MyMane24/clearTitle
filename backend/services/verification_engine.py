"""
Verification Engine (V2 Enhanced) — orchestration layer.
Per-doc verification happens during structuring.
Cross-doc verification runs with:
- Extended deterministic checks (B2)
- Composite risk scoring (B3)
- Self-critique pass (B4)
- Few-shot retrieval from human feedback (B5)
- Legal-opinion format final report (B6)
"""

from __future__ import annotations

from backend.logger import get_logger
from backend.services.cross_doc_verifier import run_cross_doc_verification
from backend.services.self_critique import run_critique
from backend.services.risk_scorer import compute_risk_score
from backend.services.mysql_store_v2 import (
    get_case_bundle,
    save_cross_doc_verification,
)
from backend.services import vector_store as vs
from backend.services.few_shot_retriever import retrieve_corrections, format_few_shot_examples

logger = get_logger(__name__)


def run_verification(case_id: str) -> dict:
    """
    Run cross-document verification with full enhancement suite.
    Per-doc verification already done during structuring.

    Pipeline:
    1. Load all structured docs from V2 DB
    2. Collect per-doc verification_notes
    3. Retrieve few-shot corrections from human feedback
    4. Run cross-doc LLM check (extended checks + deterministic)
    5. Run self-critique pass on findings
    6. Compute composite risk score
    7. Build legal-opinion-format final report
    8. Save results to V2 DB
    """
    docs = get_case_bundle(case_id)
    if not docs:
        raise ValueError(f"No structured documents found for case {case_id}")

    # Collect per-doc verification notes
    per_doc_findings = []
    for doc in docs:
        vn = doc.get("verification_notes", []) or []
        for note in vn:
            note["source_doc_id"] = doc.get("doc_id")
            note["source_doc_type"] = doc.get("document_type")
            note["category"] = "PER_DOC"
        per_doc_findings.extend(vn)

    # ── B5: Few-shot retrieval from human feedback ────────────────────
    doc_types_in_bundle = {d.get("document_type") for d in docs if d.get("document_type")}
    few_shot_prompt = ""
    for dt in doc_types_in_bundle:
        corrections = retrieve_corrections(dt)
        if corrections:
            few_shot_prompt += format_few_shot_examples(corrections) + "\n"

    # Pass few-shot context as part of verification (stored for audit)
    # The actual injection happens inside cross_doc_verifier now

    # Run cross-document verification
    cross_doc_result = run_cross_doc_verification(docs)
    cross_doc_findings = cross_doc_result.get("findings", [])
    cross_doc_analytics = cross_doc_result.get("_analytics", {})

    # Tag cross-doc findings
    for f in cross_doc_findings:
        if "category" not in f:
            f["category"] = "CROSS_DOC"

    # Merge findings (per-doc + cross-doc)
    all_findings = per_doc_findings + cross_doc_findings

    # ── B4: Self-critique pass on all findings ─────────────────────────
    all_findings = run_critique(all_findings)

    # ── B3: Compute composite risk score ───────────────────────────────
    risk_result = compute_risk_score(all_findings)
    verdict = risk_result["verdict"]

    # Build final report in legal opinion format
    final_report = cross_doc_result.get("final_report", "")
    # If the cross-doc verifier already produced a structured report, use it;
    # otherwise build one

    # Summary counts
    high_count = sum(1 for f in all_findings if f.get("severity") in ("critical", "high"))
    med_count = sum(1 for f in all_findings if f.get("severity") == "medium")
    low_count = sum(1 for f in all_findings if f.get("severity") == "low")

    report = {
        "case_id": case_id,
        "verdict": verdict,
        "risk_score": risk_result,
        "summary": {
            "total_documents": len(docs),
            "document_types": sorted(set(d.get("document_type") for d in docs)),
            "documents": [{
                "doc_id": d["doc_id"],
                "filename": d.get("filename", ""),
                "document_type": d.get("document_type"),
                "verification_notes_count": len(d.get("verification_notes", []) or []),
            } for d in docs],
            "total_findings": len(all_findings),
            "per_doc_findings": len(per_doc_findings),
            "cross_doc_findings": len(cross_doc_findings),
            "critical_severity": sum(1 for f in all_findings if f.get("severity") == "critical"),
            "high_severity": high_count,
            "medium_severity": med_count,
            "low_severity": low_count,
            "risk_score": risk_result.get("risk_score", 0),
            "risk_verdict": risk_result.get("verdict", "PASS"),
        },
        "findings": all_findings,
        "final_report": final_report,
        "metadata": {
            "per_doc_model": docs[0].get("model_used", "gemini-2.5-flash") if docs else "unknown",
            "cross_doc_model": cross_doc_analytics.get("model", "groq-llama-3.3-70b"),
            "total_input_tokens": sum(d.get("input_tokens", 0) for d in docs) + cross_doc_analytics.get("input_tokens", 0),
            "total_output_tokens": sum(d.get("output_tokens", 0) for d in docs) + cross_doc_analytics.get("output_tokens", 0),
            "total_cost_usd": round(sum(float(d.get("cost_usd", 0) or 0) for d in docs) + float(cross_doc_analytics.get("cost_usd", 0) or 0), 6),
            "few_shot_corrections_used": len(few_shot_prompt.split("Past Correction")) - 1 if few_shot_prompt else 0,
            "critique_pass_applied": True,
        },
    }

    # Save cross-doc verification to V2 DB
    try:
        save_cross_doc_verification(
            case_id=case_id,
            verdict=verdict,
            findings=all_findings,
            final_report=final_report,
            input_tokens=cross_doc_analytics.get("input_tokens", 0),
            output_tokens=cross_doc_analytics.get("output_tokens", 0),
            latency_ms=cross_doc_analytics.get("latency_ms", 0),
            cost_usd=cross_doc_analytics.get("cost_usd", 0),
            model_used=cross_doc_analytics.get("model", ""),
        )
    except Exception as e:
        logger.warning("Failed to save cross-doc verification for %s: %s", case_id, e)

    return report


def submit_human_feedback(case_id: str, feedback_data: list[dict]) -> None:
    """Store human feedback in vector DB for future learning."""
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
