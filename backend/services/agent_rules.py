"""Predefined verification rules for the ClearTitle agent.

Rules say WHAT must be investigated for a transaction. They are deliberately
data (not code paths): the agent loads the applicable rules for a transaction and
passes them to the LLM. The rules are versioned and grouped by scope:

* CROSS_DOCUMENT_RULES — apply to every transaction.
* TRANSACTION_RULES   — keyed by the transaction ``type``.
Adding a rule = adding an entry here (and bumping ``RULES_VERSION``).
"""

from __future__ import annotations

RULES_VERSION = "1.0"


def _rule(rid: str, scope: str, text: str, evidence: str = "") -> dict:
    return {"id": rid, "version": RULES_VERSION, "scope": scope, "rule": text, "evidence": evidence}


# ── cross-document rules (always applied) ─────────────────────────────────────

CROSS_DOCUMENT_RULES: list[dict] = [
    _rule("COMMON-1", "cross", "The transaction must cite at least one case document as its source."),
    _rule("COMMON-2", "cross", "Dates and registration references must not contradict other transactions in the chain."),
    _rule("COMMON-3", "cross", "The property referred to must match the established target property identity."),
    _rule("COMMON-4", "cross", "A transaction named in a recital must be preserved even if its original deed is absent."),
]

# ── transaction rules (keyed by transaction type) ─────────────────────────────

TRANSACTION_RULES: dict[str, list[dict]] = {
    "SALE": [
        _rule("SALE-1", "transaction", "A sale/conveyance deed executed by the transferor in favour of the transferee must exist in the case."),
        _rule("SALE-2", "transaction", "The transferor must have held valid title — established by a prior transaction in the chain or a vesting document."),
        _rule("SALE-3", "transaction", "The property schedule in the deed must match the target property (survey/plot/flat/extent)."),
        _rule("SALE-4", "transaction", "Consideration and execution date must be stated and consistent with the registration reference."),
    ],
    "GIFT": [
        _rule("GIFT-1", "transaction", "A gift deed signed by the donor and accepted by the donee must exist in the case."),
        _rule("GIFT-2", "transaction", "The donor must have owned the property being gifted."),
        _rule("GIFT-3", "transaction", "The property schedule must match the target property."),
    ],
    "PARTITION": [
        _rule("PART-1", "transaction", "A partition deed allocating the target property among the co-owners must exist."),
        _rule("PART-2", "transaction", "All co-owners/share-holders named in the prior title must be parties, or their shares accounted for."),
        _rule("PART-3", "transaction", "The share allotted to the current owner must be identifiable."),
    ],
    "RELEASE": [
        _rule("REL-1", "transaction", "A release/relinquishment deed must exist, executed by the releasing co-owner."),
        _rule("REL-2", "transaction", "The releasing party must have held the share being released."),
    ],
    "MORTGAGE": [
        _rule("MORT-1", "transaction", "A mortgage/charge document against the property must exist."),
        _rule("MORT-2", "transaction", "A corresponding release/discharge (or an EC entry showing discharge) must exist for the mortgage to be closed."),
        _rule("MORT-3", "transaction", "If the mortgage is unreleased, flag it as an encumbrance on title."),
    ],
    "RELEASE_OF_MORTGAGE": [
        _rule("MORTREL-1", "transaction", "A release/discharge deed referencing the original mortgage must exist."),
        _rule("MORTREL-2", "transaction", "The mortgage it releases must be identifiable in the chain."),
    ],
    "MUTATION": [
        _rule("MUT-1", "transaction", "A mutation/name-transfer order matching the underlying transfer must exist."),
        _rule("MUT-2", "transaction", "The mutation must name the same parties as the underlying transaction."),
    ],
    "EC_ENTRY": [
        _rule("EC-1", "transaction", "An EC entry corroborates registration but does not by itself convey title; it must be supported by the instrument."),
    ],
    "OTHER": [
        _rule("OTHER-1", "transaction", "The document must be relevant to the target property and its effect on title must be explained."),
    ],
}

def transaction_rules_for(transaction: dict) -> list[dict]:
    """Cross-document + type-specific rules for a transaction."""
    ttype = str((transaction or {}).get("type") or "OTHER").upper()
    specific = TRANSACTION_RULES.get(ttype) or TRANSACTION_RULES["OTHER"]
    return [*CROSS_DOCUMENT_RULES, *specific]


# Backwards-compatible alias (older callers / tests).
def rules_for(transaction: dict) -> list[dict]:
    return transaction_rules_for(transaction)


def format_rules(rules: list[dict]) -> str:
    """Render rules for inclusion in a prompt."""
    lines = []
    for r in rules:
        line = f"- [{r['id']} v{r.get('version', RULES_VERSION)}] {r['rule']}"
        if r.get("evidence"):
            line += f" (evidence: {r['evidence']})"
        lines.append(line)
    return "\n".join(lines)
