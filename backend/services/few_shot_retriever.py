"""
Few-shot retriever — retrieves similar past human corrections from Qdrant
and injects them as examples in verification prompts so the system learns
from past corrections without retraining.
"""

from __future__ import annotations

from backend.logger import get_logger
from backend.services import vector_store as vs

logger = get_logger(__name__)

MAX_FEW_SHOT_EXAMPLES = 3


def retrieve_corrections(doc_type: str, finding_type: str | None = None) -> list[dict]:
    """
    Retrieve similar past human corrections from Qdrant for the given
    doc_type and optional finding_type.
    """
    query = f"correction feedback {doc_type}"
    if finding_type:
        query = f"correction feedback {doc_type} {finding_type}"

    try:
        results = vs.search(query, top_k=MAX_FEW_SHOT_EXAMPLES + 2)
    except Exception as e:
        logger.warning("Few-shot retrieval failed: %s", e)
        return []

    corrections = []
    for r in results:
        if not isinstance(r, dict):
            continue
        text = r.get("text", "")
        metadata = {k: v for k, v in r.items() if k != "text"}
        finding_type_in_result = metadata.get("finding_type", "")
        accepted = metadata.get("accepted", True)

        # Prefer accepted corrections matching the same doc_type/finding_type
        if finding_type and finding_type_in_result == finding_type and accepted:
            corrections.insert(0, {"text": text, "metadata": metadata})
        elif accepted:
            corrections.append({"text": text, "metadata": metadata})

    return corrections[:MAX_FEW_SHOT_EXAMPLES]


def format_few_shot_examples(corrections: list[dict]) -> str:
    """Format retrieved corrections into a prompt-ready context block."""
    if not corrections:
        return ""
    lines = ["## PAST HUMAN CORRECTIONS (Apply the same standard here)"]
    for i, corr in enumerate(corrections, 1):
        text = corr.get("text", "")
        meta = corr.get("metadata", {})
        lines.append(f"\n### Past Correction {i}:")
        lines.append(f"Context: {text}")
        if meta.get("reason"):
            lines.append(f"Reason: {meta['reason']}")
        if meta.get("corrected_severity"):
            lines.append(f"Corrected Severity: {meta['corrected_severity']}")
    return "\n".join(lines)
