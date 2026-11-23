"""The Case File: built from Phase A, stored as JSON, migrated forward."""

import pytest

from backend.services.verification import case_file as cf
from backend.tests.verification_fixtures import new_case_file


def test_built_from_phase_a_chain_and_structured_documents():
    case = new_case_file()
    assert [t.id for t in case.transfers] == ["PA-TC-0001", "PA-TC-0002", "PA-TC-0003"]
    assert not any(t.recorded for t in case.transfers)
    assert case.phase_a_hash == "hash-1"
    assert set(case.documents) == {"EC", "D1998", "D2010", "D2018"}  # failed doc left out
    assert not any(entry.examined for entry in case.documents.values())


def test_json_round_trip_keeps_everything():
    case = new_case_file()
    case.transfers[0].property = cf.Property(type="house", extent="30x40 ft")
    case.transfers[0].summary = "Clean sale."
    case.requests.append(cf.Request(id=case.next_id("R"), document="Khata", reason="Owner."))
    restored = cf.load(case.model_dump(mode="json"))
    assert restored == case


def test_ids_are_never_reused():
    case = new_case_file()
    assert [case.next_id("R"), case.next_id("R"), case.next_id("VL-")] == ["R1", "R2", "VL-1"]


def test_newer_schema_is_rejected():
    data = new_case_file().model_dump(mode="json")
    data["schema_version"] = cf.SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="newer"):
        cf.load(data)


def test_older_schema_without_version_loads():
    data = schema_4()
    del data["schema_version"]
    assert cf.load(data).schema_version == cf.SCHEMA_VERSION


def test_saved_transactions_with_the_old_property_type_still_load():
    data = new_case_file().model_dump(mode="json")
    data["transfers"][0]["transaction"]["property_type"] = "Residential plot"
    case = cf.load(data)
    assert "property_type" not in case.transfers[0].transaction.model_dump()


# -- schema 4 (links with verdicts, issues, leads, requisitions) ------------------------


def schema_4():
    """A schema 4 Case File, as saved before one record per transfer."""
    case = new_case_file().model_dump(mode="json")
    chain = [
        {
            "link_id": t["id"],
            "origin": "phase_a",
            "continues_previous": index > 0,
            "break_note": None,
            "transaction": t["transaction"],
            "verdict": None,
        }
        for index, t in enumerate(case.pop("transfers"))
    ]
    case.pop("property_today"), case.pop("requests"), case.pop("set_aside")
    return {
        **case,
        "schema_version": 4,
        "chain": chain,
        "leads": [],
        "issues": [],
        "requisitions": [],
    }


def test_schema_4_verdicts_issues_and_requisitions_become_transfer_records():
    data = schema_4()
    data["chain"][1]["verdict"] = {
        "verdict": "unverified_missing_document",
        "summary": "Partition deed not on file.",
        "property_type": "agricultural_land",
        "extent": "2 acres",
        "needed_documents": [
            {"document": "Partition deed", "proves": "Title.", "status": "missing", "citations": [],
             "requisition_id": "R1"},
        ],
    }  # fmt: skip
    data["chain"][2].update(continues_previous=False, break_note="No deed from Chandrashekar.")
    data["chain"][2]["verdict"] = {"verdict": "defective", "summary": "Sellers' title not shown."}
    data["issues"] = [
        {"id": "I1", "severity": "medium", "title": "Patta", "detail": "Old name.",
         "link_ids": ["PA-TC-0002"], "citations": []},
        {"id": "I2", "severity": "high", "title": "Mortgage", "detail": "Open.", "link_ids": []},
        {"id": "I3", "severity": "high", "title": "Chain unverified", "detail": "A summary.",
         "link_ids": ["PA-TC-0001", "PA-TC-0002", "PA-TC-0003", "PA-TC-0001"]},
    ]  # fmt: skip
    data["requisitions"] = [
        {"id": "R1", "document": "Partition deed", "reason": "Title.",
         "affects": ["PA-TC-0002", "L1"], "status": "fulfilled", "doc_id": "D9"},
        {"id": "R2", "document": "Old", "reason": "x", "affects": ["PA-TC-0001"],
         "status": "withdrawn"},
    ]  # fmt: skip
    case = cf.load(data)
    second, third = case.transfers[1], case.transfers[2]
    assert cf.transfer_result(second) == "documents_missing"
    assert second.documents[0].request_id == "R1"
    assert [c.text for c in second.concerns] == ["Patta: Old name."]
    assert cf.transfer_result(third) == "defective"
    assert third.connects == cf.Connection(ok=False, note="No deed from Chandrashekar.")
    assert not case.transfers[0].recorded
    assert [(r.id, r.status, r.needed_for) for r in case.requests] == [
        ("R1", "received", ["PA-TC-0002"])
    ]


def test_older_schemas_still_reach_the_current_one():
    data = schema_4()
    data.update(schema_version=1, tasks=[], property_identity={"details": []}, clear_checks=[])
    for link in data["chain"]:
        link.update(amendments=["Corrected: x"], related_events=[])
    data["chain"][0]["verdict"] = {
        "verdict": "verified",
        "summary": "Clean sale.",
        "checks": [{"check": "vendor title", "status": "ok", "note": "ok", "citations": []}],
    }
    case = cf.load(data)
    assert case.schema_version == cf.SCHEMA_VERSION
    assert cf.transfer_result(case.transfers[0]) == "verified"


def test_text_hash_changes_with_text():
    assert cf.text_hash("a") != cf.text_hash("b")
