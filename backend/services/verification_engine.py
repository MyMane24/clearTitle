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
from backend.services.mysql_store import (
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

    # ── Counts ─────────────────────────────────────────────────────────
    critical_count = sum(1 for f in all_findings if f.get("severity") in ("critical", "high"))
    med_count = sum(1 for f in all_findings if f.get("severity") == "medium")
    low_count = sum(1 for f in all_findings if f.get("severity") == "low")

    per_doc_count = sum(1 for f in all_findings if f.get("category") == "PER_DOC")
    cross_doc_count = sum(1 for f in all_findings if f.get("category") == "CROSS_DOC")

    # ── Reshape findings into UI-ready format ──────────────────────────
    metadata = {
        "per_doc_model": docs[0].get("model_used", "gemini-2.5-flash") if docs else "unknown",
        "cross_doc_model": cross_doc_analytics.get("model", "groq-llama-3.3-70b"),
        "total_input_tokens": sum(d.get("input_tokens", 0) for d in docs) + cross_doc_analytics.get("input_tokens", 0),
        "total_output_tokens": sum(d.get("output_tokens", 0) for d in docs) + cross_doc_analytics.get("output_tokens", 0),
        "total_cost_usd": round(sum(float(d.get("cost_usd", 0) or 0) for d in docs) + float(cross_doc_analytics.get("cost_usd", 0) or 0), 6),
        "few_shot_corrections_used": len(few_shot_prompt.split("Past Correction")) - 1 if few_shot_prompt else 0,
        "critique_pass_applied": True,
    }

    report = generate_verification_report_payload(
        case_id=case_id,
        all_findings=all_findings,
        verdict=verdict,
        final_report=final_report,
        metadata=metadata,
    )

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


def generate_verification_report_payload(
    case_id: str,
    all_findings: list,
    verdict: str,
    final_report: str,
    metadata: dict | None = None
) -> dict:
    """Transform raw findings list into UI-ready premium dashboard structure."""
    docs = get_case_bundle(case_id) or []

    # ── Compute composite risk score ───────────────────────────────
    risk_result = compute_risk_score(all_findings)
    risk_score = risk_result.get("risk_score", 0)

    # ── Counts ─────────────────────────────────────────────────────────
    critical_count = sum(1 for f in all_findings if f.get("severity") in ("critical", "high"))
    med_count = sum(1 for f in all_findings if f.get("severity") == "medium")
    low_count = sum(1 for f in all_findings if f.get("severity") == "low")

    per_doc_count = sum(1 for f in all_findings if f.get("category") == "PER_DOC")
    cross_doc_count = sum(1 for f in all_findings if f.get("category") == "CROSS_DOC")

    # ── Reshape helper ────────────────────────────────────────────────
    def _reshape_finding(f):
        sev = (f.get("severity") or "low").lower()
        sev_icon = {"critical": "🔴", "high": "🔴", "medium": "🟠", "low": "🔵"}.get(sev, "🔵")

        # Build documents_involved
        doc_ids = f.get("doc_ids") or f.get("doc_ids_involved") or []
        if not doc_ids and f.get("source_doc_type"):
            doc_ids = [f["source_doc_type"]]
        docs_involved = [d.replace("_", " ").title() for d in doc_ids]

        # Factual mismatch / what was detected
        what_was_detected = f.get("what_was_detected") or f.get("summary") or ""

        # Evidence: parse from evidence list or string
        evidence_raw = f.get("evidence") or f.get("source_document_ref") or ""
        evidence_list = []
        if isinstance(evidence_raw, list):
            evidence_list = evidence_raw
        elif evidence_raw:
            if "|" in str(evidence_raw) and ":" in str(evidence_raw):
                for part in str(evidence_raw).split("|"):
                    if ":" in part:
                        src, det = part.split(":", 1)
                        evidence_list.append({"source": src.strip(), "detail": det.strip()})
            if not evidence_list:
                evidence_list.append({"source": docs_involved[0] if docs_involved else "Evidence", "detail": str(evidence_raw)})

        # Checklist from verification_steps or suggestion
        verification_steps = f.get("verification_steps") or []
        if isinstance(verification_steps, str):
            verification_steps = [verification_steps]
        checklist = []
        if verification_steps:
            checklist = [step.strip() for step in verification_steps if step.strip()]
        else:
            suggestion = f.get("suggestion") or ""
            if suggestion:
                for item in suggestion.replace("; ", "\n").split("\n"):
                    item = item.strip().lstrip("0123456789.-) ")
                    if item:
                        checklist.append(item)
                if not checklist:
                    checklist = [suggestion]

        # Legal references from legal_reference, statute_reference, etc.
        legal_refs = []
        legal_ref_val = f.get("legal_reference") or f.get("statute_reference") or ""
        if legal_ref_val:
            legal_refs.append(legal_ref_val)

        # Possible causes list
        possible_causes = f.get("possible_causes") or []
        if isinstance(possible_causes, str):
            possible_causes = [possible_causes]

        # Why flagged
        why_flagged = f.get("reason") or f.get("legal_detail") or f.get("details") or ""

        # Impact
        impact = f.get("impact") or f.get("legal_detail") or ""

        return {
            "title": f.get("title") or f.get("summary") or f.get("type", "Finding"),
            "type": f.get("type") or "UNKNOWN",
            "severity": sev,
            "severity_icon": sev_icon,
            "category": f.get("category", "PER_DOC"),
            "documents_involved": docs_involved,
            "what_was_found": what_was_detected,
            "evidence": evidence_list,
            "why_flagged": why_flagged,
            "impact": impact,
            "possible_causes": possible_causes,
            "checklist": checklist,
            "confidence": f.get("confidence", 0.8),
            "legal_references": legal_refs,
            "source_doc_id": f.get("source_doc_id"),
            "source_doc_type": f.get("source_doc_type"),
        }

    shaped_findings = [_reshape_finding(f) for f in all_findings]

    # ── Split into cross-doc and per-doc ───────────────────────────────
    shaped_cross = [f for f in shaped_findings if f["category"] == "CROSS_DOC"]
    shaped_per_doc = [f for f in shaped_findings if f["category"] == "PER_DOC"]

    # Group per-doc by document type
    per_doc_grouped = {}
    for f in shaped_per_doc:
        dt = f.get("source_doc_type") or "UNKNOWN"
        if dt not in per_doc_grouped:
            doc_meta = next((d for d in docs if d.get("document_type") == dt), {})
            per_doc_grouped[dt] = {
                "doc_type": dt,
                "doc_id": doc_meta.get("doc_id", ""),
                "filename": doc_meta.get("filename", ""),
                "issues": [],
            }
        per_doc_grouped[dt]["issues"].append(f)

    # ── Missing documents ──────────────────────────────────────────────
    missing_docs = []
    for f in all_findings:
        ftype = (f.get("type") or "").upper()
        if ftype in ("MISSING_DOCUMENT", "EXPECTED_MISSING_DOCS"):
            summary = f.get("summary") or ""
            if summary and summary not in missing_docs:
                missing_docs.append(summary)

    # ── Determine recommended action ───────────────────────────────────
    if risk_score >= 70:
        risk_label = "High Risk"
        recommended_action = "Do NOT proceed until critical issues are resolved."
    elif risk_score >= 40:
        risk_label = "Medium Risk"
        recommended_action = "Proceed with caution. Address medium-severity issues."
    else:
        risk_label = "Low Risk"
        recommended_action = "Property appears safe. Verify any remaining low-severity items."

    # ── Major risks for final opinion ──────────────────────────────────
    major_risks = []
    for f in shaped_findings:
        if f["severity"] in ("critical", "high"):
            entry = f"{f['severity_icon']} {f['title']}"
            if entry not in major_risks:
                major_risks.append(entry)

    # ── Recommended actions for final opinion ──────────────────────────
    rec_actions = []
    for f in shaped_findings:
        for item in f.get("checklist", []):
            if item not in rec_actions:
                rec_actions.append(item)
            if len(rec_actions) >= 10:
                break

    # ── Final recommendation ───────────────────────────────────────────
    if verdict == "PASS":
        final_rec = "SAFE TO PROCEED"
        final_reason = "No critical issues found. Standard due diligence complete."
    else:
        final_rec = "NOT SAFE TO PROCEED"
        final_reason = (
            "Clear ownership cannot be established due to unresolved findings. "
            "Address all critical and high-severity issues before proceeding."
        )

    return {
        "case_id": case_id,
        "status": "completed",
        "verdict": verdict,
        "dashboard": {
            "overall_status": "PASS" if verdict == "PASS" else "FLAGGED",
            "risk_score": risk_score,
            "risk_label": risk_label,
            "documents_processed": len(docs),
            "cross_doc_issues": cross_doc_count,
            "per_doc_issues": per_doc_count,
            "critical_findings": critical_count,
            "medium_findings": med_count,
            "low_findings": low_count,
            "missing_documents_count": len(missing_docs),
            "recommended_action": recommended_action,
        },
        "cross_doc_findings": shaped_cross,
        "per_doc_findings": per_doc_grouped,
        "missing_documents": missing_docs,
        "final_opinion": {
            "executive_summary": f"Property verification completed. {len(docs)} documents reviewed.",
            "documents_reviewed": len(docs),
            "total_findings": len(all_findings),
            "critical": critical_count,
            "medium": med_count,
            "low": low_count,
            "major_risks": major_risks,
            "missing_documents": missing_docs,
            "recommended_actions": rec_actions[:10],
            "final_recommendation": final_rec,
            "final_reason": final_reason,
        },
        "findings": all_findings,
        "metadata": metadata or {},
    }


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
