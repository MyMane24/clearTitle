"""Stage 8a: GET /results/{case_id}/findings — flattened Phase C container."""

import asyncio
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from backend.routers import results as router_module

CONTAINER = {
    "container_version": "1.0",
    "input_hash": "abc123",
    "result": {
        "findings": [{
            "finding_id": "PF-001",
            "category": "ENCUMBRANCE",
            "title": "Undischarged mortgage",
            "description": "Recorded memoranda stays undischarged.",
            "severity": "CRITICAL",
        }],
        "contradictions": [],
        "unresolved_dependencies": ["REQ-0001"],
        "provenance": {"contract_version": "1.0", "phase_a_hash": "pa"},
    },
}


def call(case_id="CASE1", user=None):
    # Direct call: the Depends default is a marker, pass the dependency result.
    return asyncio.run(router_module.get_case_findings(case_id, user=user or {"id": "owner"}))


def patch_container(mock):
    # The handler imports agent_repo lazily inside the function body.
    return patch("backend.database.repositories.agent_repo.get_property_findings", mock)


def test_container_is_flattened_with_provenance():
    with patch_container(Mock(return_value=CONTAINER)), \
        patch("backend.routers.results.case_exists", Mock(return_value=True)):
        payload = call()
    assert payload["container_version"] == "1.0"
    assert payload["input_hash"] == "abc123"
    assert payload["findings"][0]["finding_id"] == "PF-001"
    assert payload["unresolved_dependencies"] == ["REQ-0001"]
    assert payload["provenance"]["phase_a_hash"] == "pa"


def test_case_without_container_is_an_honest_empty_state():
    with patch_container(Mock(return_value=None)), \
        patch("backend.routers.results.case_exists", Mock(return_value=True)):
        payload = call()
    assert payload["container_version"] is None
    assert payload["findings"] == []
    assert payload["contradictions"] == []
    assert payload["unresolved_dependencies"] == []
    assert payload["provenance"] is None


def test_unknown_case_is_404():
    with patch("backend.routers.results.case_exists", Mock(return_value=False)):
        with pytest.raises(HTTPException) as excinfo:
            call("NOPE")
    assert excinfo.value.status_code == 404


def test_unowned_but_existing_case_is_reachable():
    # get_case_owner is None for both unowned and missing cases; only the
    # missing case may 404. An existing unowned demo case answers normally.
    with patch_container(Mock(return_value=None)), \
        patch("backend.routers.results.case_exists", Mock(return_value=True)), \
        patch("backend.routers.results.get_case_owner", Mock(return_value=None)):
        payload = call()
    assert payload["case_id"] == "CASE1"
    assert payload["findings"] == []


def test_not_owned_case_is_403():
    # Anonymous caller (no token) on an owned case must be refused.
    with patch("backend.routers.results.case_exists", Mock(return_value=True)), \
        patch("backend.routers.results.get_case_owner", Mock(return_value="someone")):
        with pytest.raises(HTTPException) as excinfo:
            call(user=None)
    assert excinfo.value.status_code == 403


def test_repo_failure_is_502_not_a_fake_empty_state():
    with patch_container(Mock(side_effect=RuntimeError("db down"))), \
        patch("backend.routers.results.case_exists", Mock(return_value=True)):
        with pytest.raises(HTTPException) as excinfo:
            call()
    assert excinfo.value.status_code == 502
