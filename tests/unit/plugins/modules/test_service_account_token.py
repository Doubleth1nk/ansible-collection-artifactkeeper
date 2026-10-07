# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import service_account_token


def params(**overrides):
    data = {"service_account": "ci", "name": "automation", "description": None, "scopes": ["read"], "expires_in_days": None, "state": "present"}
    data.update(overrides)
    return data


def account():
    return {"id": "s1", "username": "svc-ci"}


def test_create_returns_plaintext_once(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    client = RecordingClient([
        {"items": []},
        {"id": "t1", "name": "automation", "token": "plaintext-secret", "policy_applied": False, "expires_at": None},
    ])
    result = invoke(service_account_token.run_module, FakeModule(params()), client)
    assert result["changed"] is True
    assert result["token"] == "plaintext-secret"
    assert "token" not in result["token_info"]


def test_existing_same_scopes_no_change(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    existing = {"id": "t1", "name": "automation", "scopes": ["write", "read"], "is_expired": False}
    client = RecordingClient([{"items": [existing]}])
    result = invoke(service_account_token.run_module, FakeModule(params(scopes=["read", "write"])), client)
    assert result["changed"] is False
    assert len(client.calls) == 1


def test_scope_update_rotates_token(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    existing = {"id": "t1", "name": "automation", "scopes": ["read"], "is_expired": False}
    client = RecordingClient([
        {"items": [existing]},
        None,
        {"id": "t2", "name": "automation", "token": "new-secret", "policy_applied": False, "expires_at": None},
    ])
    result = invoke(service_account_token.run_module, FakeModule(params(scopes=["read", "write"])), client)
    assert result["changed"] is True
    assert [call[0] for call in client.calls] == ["GET", "DELETE", "POST"]


def test_delete(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    existing = {"id": "t1", "name": "automation", "scopes": ["read"], "is_expired": False}
    client = RecordingClient([{"items": [existing]}, None])
    result = invoke(service_account_token.run_module, FakeModule(params(state="absent", scopes=None)), client)
    assert result["token_info"] is None
    assert client.calls[-1][0] == "DELETE"


def test_already_absent(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    client = RecordingClient([{"items": []}])
    result = invoke(service_account_token.run_module, FakeModule(params(state="absent", scopes=None)), client)
    assert result["changed"] is False


def test_check_mode_scope_change_does_not_rotate(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    existing = {"id": "t1", "name": "automation", "scopes": ["read"], "is_expired": False}
    client = RecordingClient([{"items": [existing]}])
    result = invoke(service_account_token.run_module, FakeModule(params(scopes=["write"]), check_mode=True), client)
    assert result["changed"] is True
    assert [call[0] for call in client.calls] == ["GET"]


def test_api_failure(monkeypatch):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    client = RecordingClient([ArtifactKeeperError("boom")])
    with pytest.raises(ArtifactKeeperError):
        service_account_token.run_module(FakeModule(params()), client)


def test_absent_revokes_expired_named_token(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    expired = {"id": "t-old", "name": "automation", "scopes": ["read"], "is_expired": True}
    client = RecordingClient([{"items": [expired]}, None])
    result = invoke(
        service_account_token.run_module,
        FakeModule(params(state="absent", scopes=None)),
        client,
    )
    assert result["changed"] is True
    assert [call[0] for call in client.calls] == ["GET", "DELETE"]


def test_creation_diff_contains_metadata_but_not_plaintext_token(monkeypatch, invoke):
    account = {"id": "sa1", "username": "svc-ci"}
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account)
    client = RecordingClient([
        {"items": []},
        {"id": "tok1", "name": "automation", "scopes": ["read"], "token": "plaintext-secret"},
    ])
    result = invoke(
        service_account_token.run_module,
        FakeModule(params(), diff=True),
        client,
    )
    assert result["token"] == "plaintext-secret"
    assert "plaintext-secret" not in str(result["diff"])


# Contract regression for Artifact Keeper 1.10.2, whose CreateTokenRequest sets
# additionalProperties: false: unknown fields are rejected with HTTP 400, and
# repository_ids: [] is rejected because it would mean an unrestricted token.
# The module manages no repository restriction, so it must only ever send these
# keys, and must never send repository_ids or repo_selector.
SUPPORTED_CREATE_KEYS = {"name", "scopes", "description", "expires_in_days"}


@pytest.mark.parametrize("description", [None, "CI automation"])
@pytest.mark.parametrize("expires_in_days", [None, 90])
@pytest.mark.parametrize("scopes", [["read"], ["write", "read", "read"]])
@pytest.mark.parametrize("existing_scopes", [None, ["admin"]], ids=["create", "rotate"])
def test_create_payload_contains_only_supported_keys(monkeypatch, invoke, description, expires_in_days, scopes, existing_scopes):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    responses = [{"items": []}]
    if existing_scopes is not None:
        responses = [{"items": [{"id": "t1", "name": "automation", "scopes": existing_scopes, "is_expired": False}]}, None]
    responses.append({"id": "t2", "name": "automation", "token": "new-secret", "policy_applied": False, "expires_at": None})
    client = RecordingClient(responses)

    invoke(
        service_account_token.run_module,
        FakeModule(params(description=description, expires_in_days=expires_in_days, scopes=scopes)),
        client,
    )

    creates = [call for call in client.calls if call[0] == "POST"]
    assert len(creates) == 1
    method, path, kwargs = creates[0]
    assert path == "/service-accounts/s1/tokens"
    payload = kwargs["data"]
    assert set(payload) <= SUPPORTED_CREATE_KEYS
    assert "repository_ids" not in payload
    assert "repo_selector" not in payload
    expected = {"name": "automation", "scopes": sorted(set(scopes))}
    if description is not None:
        expected["description"] = description
    if expires_in_days is not None:
        expected["expires_in_days"] = expires_in_days
    assert payload == expected
