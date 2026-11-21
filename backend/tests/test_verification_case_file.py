"""The Case File: built from Phase A, stored as JSON, migrated forward."""

import pytest

from backend.services.verification import case_file as cf
from backend.tests.verification_fixtures import new_case_file


def test_built_from_phase_a_chain_and_structured_documents():
    case = new_case_file()
    assert [link.link_id for link in case.chain] == ["PA-TC-0001", "PA-TC-0002", "PA-TC-0003"]
    assert case.chain[0].continues_previous is False
    assert case.chain[1].continues_previous is True
    assert case.phase_a_hash == "hash-1"
    assert set(case.documents) == {"EC", "D1998", "D2010", "D2018"}  # failed doc left out
    assert not any(entry.examined for entry in case.documents.values())


def test_json_round_trip_keeps_everything():
    case = new_case_file()
    lead_id = case.next_id("L")
    case.leads.append(cf.Lead(id=lead_id, text="2005 partition", source="EC p.2"))
    restored = cf.load(case.model_dump(mode="json"))
    assert restored == case


def test_ids_are_never_reused():
    case = new_case_file()
    assert [case.next_id("R"), case.next_id("R"), case.next_id("L")] == ["R1", "R2", "L1"]


def test_newer_schema_is_rejected():
    data = new_case_file().model_dump(mode="json")
    data["schema_version"] = cf.SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="newer"):
        cf.load(data)


def test_older_schema_without_version_loads():
    data = new_case_file().model_dump(mode="json")
    del data["schema_version"]
    assert cf.load(data).schema_version == cf.SCHEMA_VERSION


def test_version_1_case_file_drops_the_unused_fields():
    data = new_case_file().model_dump(mode="json")
    data.update(schema_version=1, tasks=[], property_identity={"details": []})
    for link in data["chain"]:
        link.update(amendments=["Corrected: x"], related_events=[])
    case = cf.load(data)
    assert case.schema_version == 2
    assert case.model_dump(mode="json")["chain"][0].keys() >= {"link_id", "transaction"}
    assert "amendments" not in case.model_dump(mode="json")["chain"][0]


def test_saved_transactions_with_the_old_property_type_still_load():
    data = new_case_file().model_dump(mode="json")
    data["chain"][0]["transaction"]["property_type"] = "Residential plot"
    case = cf.load(data)
    assert "property_type" not in case.chain[0].transaction.model_dump()


def test_text_hash_changes_with_text():
    assert cf.text_hash("a") != cf.text_hash("b")
