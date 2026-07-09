"""
Self-critique pass (devil's-advocate review).
After the cross-doc verifier produces findings, a second LLM call is made
that is given ONLY the findings and asked to critique them:
"Is this finding actually supported by the evidence quoted?
 Is the severity appropriate? Could there be a benign explanation?"

Findings that fail critique are downgraded in confidence or removed.
"""

from __future__ import annotations

import json
import os
import time

import httpx
from dotenv import load_dotenv
from groq import Groq

from backend.logger import get_logger

load_dotenv()

logger = get_logger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
CRITIQUE_MODEL = "llama-3.3-70b-versatile"

# Module-level singleton — avoids creating a new connection pool per critique call
_critique_http_client: "httpx.Client | None" = None
_critique_groq_client: "Groq | None" = None


def _get_groq_client() -> "Groq":
    global _critique_http_client, _critique_groq_client
    if _critique_groq_client is None:
        _critique_http_client = httpx.Client(timeout=httpx.Timeout(60.0, connect=30.0))
        _critique_groq_client = Groq(api_key=GROQ_API_KEY, http_client=_critique_http_client)
    return _critique_groq_client

CRITIQUE_SYSTEM_PROMPT = """You are a SENIOR PARTNER at a law firm reviewing a junior associate's due diligence findings.
Your job is to play devil's advocate and critically evaluate each finding.

For each finding, determine:
1. Is the finding actually supported by the evidence quoted?
2. Is the severity appropriate, or is it over-claimed / under-claimed?
3. Could there be a benign explanation that the associate missed?
4. Does the finding cite its source document correctly?

Return a JSON array of critique results. Each element must have:
{
    "finding_index": <int>,        // index from the original array
    "critique_verdict": "UPHOLD | DOWNGRADE | REMOVE",
    "suggested_severity": "critical | high | medium | low | null",
    "severity_adjustment": <int>,  // positive = increase severity, negative = decrease, 0 = no change
    "confidence_adjustment": <float>, // -0.5 to +0.1. Negative means downgrade confidence.
    "reason": "Explanation of the critique verdict and reasoning"
}

Rules:
- Only use "REMOVE" for findings that are clearly false, hallucinated, or based on misread evidence.
- Only use "DOWNGRADE" for findings where the severity is over-claimed or evidence is weak.
- Be conservative in downgrading — the associate is usually correct.
- If the finding is well-supported and severity is appropriate, use "UPHOLD".
- Never remove a finding without a strong reason.
"""


def run_critique(findings: list[dict], doc_summary: str | None = None) -> list[dict]:
    """
    Given a list of findings (from cross-doc verifier), run a self-critique pass.
    Returns the same list with adjusted confidence/severity based on critique.
    """
    if not GROQ_API_KEY:
        logger.warning("No Groq API key for critique pass — skipping")
        return findings

    if not findings:
        return findings

    client = _get_groq_client()

    # Build a compact input with just the findings
    critique_input = []
    for i, f in enumerate(findings):
        critique_input.append({
            "index": i,
            "type": f.get("type"),
            "severity": f.get("severity"),
            "confidence": f.get("confidence"),
            "summary": f.get("summary"),
            "legal_detail": f.get("legal_detail"),
            "evidence": f.get("evidence"),
            "doc_ids": f.get("doc_ids", []),
        })

    input_text = json.dumps(critique_input, indent=2, ensure_ascii=False)
    user_prompt = (
        "Critique the following findings from a property due-diligence verification report.\n\n"
        f"FINDINGS:\n{input_text}\n\n"
        "Return ONLY valid JSON array of critique results."
    )

    start = time.time()
    try:
        response = client.chat.completions.create(
            model=CRITIQUE_MODEL,
            messages=[
                {"role": "system", "content": CRITIQUE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )
        latency = int((time.time() - start) * 1000)
        raw = response.choices[0].message.content.strip()
        try:
            critique_results = json.loads(raw)
            if isinstance(critique_results, dict) and "critique_results" in critique_results:
                critique_results = critique_results["critique_results"]
            if isinstance(critique_results, dict) and "findings" in critique_results:
                critique_results = critique_results["findings"]
        except json.JSONDecodeError:
            logger.warning("Failed to parse critique response JSON")
            return findings

        if not isinstance(critique_results, list):
            logger.warning("Critique results not a list, got %s", type(critique_results))
            return findings

        # Apply critique adjustments
        result_map = {}
        for cr in critique_results:
            idx = cr.get("finding_index")
            if idx is not None and 0 <= idx < len(findings):
                result_map[idx] = cr

        adjusted_findings = []
        for i, f in enumerate(findings):
            f = dict(f)
            if i in result_map:
                cr = result_map[i]
                verdict = cr.get("critique_verdict", "UPHOLD")
                if verdict == "REMOVE":
                    logger.info("Critique: removed finding %d (%s)", i, f.get("type"))
                    continue
                if verdict == "DOWNGRADE":
                    old_conf = f.get("confidence", 0.5)
                    adj = cr.get("confidence_adjustment", -0.2)
                    new_conf = max(0.1, min(1.0, old_conf + adj))
                    f["confidence"] = round(new_conf, 2)
                    f["critique_note"] = cr.get("reason", "Downgraded by self-critique")
                    new_sev = cr.get("suggested_severity")
                    if new_sev:
                        f["original_severity"] = f.get("severity")
                        f["severity"] = new_sev
                else:
                    f["critique_note"] = "Upheld by self-critique"
            else:
                f["critique_note"] = "Not reviewed by self-critique"
            adjusted_findings.append(f)

        logger.info(
            "Critique pass: %d input -> %d output (%d removed, %d adjusted)",
            len(findings), len(adjusted_findings),
            len(findings) - len(adjusted_findings),
            sum(1 for f in adjusted_findings if "Downgraded" in f.get("critique_note", "")),
        )

        return adjusted_findings

    except Exception as e:
        logger.error("Critique pass failed: %s", e)
        return findings
