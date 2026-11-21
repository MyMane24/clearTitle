"""Pure rules for whether one chain link continues the one before it.

Shared by the title-chain builder and the verification agent, so both judge
continuity the same way. Nothing here reads the database or calls a model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# Party names containing one of these words belong to an entity, whose members
# are named in its constitution document rather than in the sale records.
ENTITY_WORDS = frozenset(
    {
        "associates",
        "brothers",
        "builders",
        "company",
        "enterprises",
        "firm",
        "industries",
        "limited",
        "llp",
        "partnership",
        "properties",
        "traders",
        "trust",
    }
)
ENTITY_DOC_TYPES = frozenset({"PARTNERSHIP_DEED", "LLP_DEED", "TRUST_DEED"})
NAME_NOISE = frozenset(
    {
        "alias",
        "associates",
        "attorney",
        "company",
        "daughter",
        "enterprises",
        "firm",
        "heirs",
        "late",
        "legal",
        "limited",
        "mrs",
        "partnership",
        "private",
        "represented",
        "shri",
        "smt",
        "son",
        "through",
        "traders",
        "widow",
        "wife",
    }
)


def name_words(names: Iterable[str]) -> set[str]:
    """Lowercase name words long enough to identify a party in OCR text."""
    return {
        word
        for name in names
        for word in re.findall(r"[a-z]+", name.casefold())
        if len(word) >= 4 and word not in NAME_NOISE
    }


def has_entity_party(names: Iterable[str]) -> bool:
    """True when any of the names belongs to a firm, company or trust."""
    return any(ENTITY_WORDS & set(re.findall(r"[a-z]+", name.casefold())) for name in names)


def names_connect(acquirers: Iterable[str], transferors: Iterable[str]) -> bool:
    """True unless both name lists are readable and share no identifying word.

    An empty or unreadable name list cannot prove a break, so it connects.
    """
    acquirer_words = name_words(acquirers)
    transferor_words = name_words(transferors)
    return not acquirer_words or not transferor_words or bool(acquirer_words & transferor_words)


def entity_continuity_supported(
    acquirers: list[str], transferors: list[str], constitution_texts: Mapping[str, str]
) -> bool:
    """True when a fully read constitution document names two of the acquirers.

    A firm or trust is its members, so an entity name may continue a link only
    when its constitution names the people who acquired the property before it.

    Args:
        acquirers: The previous link's transferees.
        transferors: The current link's transferors.
        constitution_texts: Full text of each fully read partnership, LLP or
            trust deed, by document id.
    """
    if not has_entity_party([*transferors, *acquirers]):
        return False
    acquirer_words = name_words(acquirers)
    if len(acquirer_words) < 2:
        return False
    return any(
        len(set(re.findall(r"[a-z]+", text.casefold())) & acquirer_words) >= 2
        for text in constitution_texts.values()
    )
