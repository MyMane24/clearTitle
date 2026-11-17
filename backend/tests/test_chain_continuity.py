"""Pure continuity rules shared by the chain builder and the verification agent."""

from backend.domain.chain_continuity import (
    entity_continuity_supported,
    has_entity_party,
    name_words,
    names_connect,
)


def test_name_words_drops_honorifics_and_short_words():
    assert name_words(["Smt. Lakshmi w/o Late Ramaiah"]) == {"lakshmi", "ramaiah"}


def test_names_connect_when_a_name_word_is_shared():
    assert names_connect(["Ramesh Kumar"], ["R. Ramesh"])


def test_names_do_not_connect_when_owners_differ():
    assert not names_connect(["Ramesh Kumar"], ["Suresh Gowda"])


def test_unreadable_names_cannot_prove_a_break():
    assert names_connect([], ["Suresh Gowda"])
    assert names_connect(["Smt"], ["Suresh Gowda"])


def test_entity_party_detection():
    assert has_entity_party(["Sri Sai Builders"])
    assert not has_entity_party(["Ramesh Kumar"])


def test_entity_continuity_needs_a_constitution_naming_two_acquirer_words():
    acquirers = ["Ramesh Kumar", "Suresh Gowda"]
    firm = ["Sri Sai Builders"]
    deed = {"d1": "Partners: Ramesh Kumar and Suresh Gowda carry on business."}
    assert entity_continuity_supported(acquirers, firm, deed)
    assert not entity_continuity_supported(acquirers, firm, {"d1": "Managing partner: Ramesh"})
    assert not entity_continuity_supported(acquirers, ["Mahesh"], deed)
