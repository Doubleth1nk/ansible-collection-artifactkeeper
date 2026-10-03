# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import service_account


def params(**overrides):
    data = {"name": "ci", "description": None, "is_active": None, "state": "present"}
    data.update(overrides)
    return data


def test_create(monkeypatch, invoke):
    monkeypatch.setattr(service_account, "service_account_by_name", lambda client, name: None)
    client = RecordingClient([{"id": "s1", "username": "svc-ci", "display_name": None, "is_active": True}])
    result = invoke(service_account.run_module, FakeModule(params()), client)
    assert result["changed"] is True
    assert client.calls[0][0] == "POST"


def test_no_change(monkeypatch, invoke):
    current = {"id": "s1", "username": "svc-ci", "display_name": "CI", "is_active": True}
    monkeypatch.setattr(service_account, "service_account_by_name", lambda client, name: current)
    result = invoke(service_account.run_module, FakeModule(params(description="CI", is_active=True)), RecordingClient())
    assert result["changed"] is False


def test_update(monkeypatch, invoke):
    current = {"id": "s1", "username": "svc-ci", "display_name": "Old", "is_active": True}
    monkeypatch.setattr(service_account, "service_account_by_name", lambda client, name: current)
    client = RecordingClient([{"id": "s1", "username": "svc-ci", "display_name": "CI", "is_active": False}])
    result = invoke(service_account.run_module, FakeModule(params(description="CI", is_active=False), diff=True), client)
    assert result["changed"] is True
    assert client.calls[0][0] == "PATCH"
    assert "diff" in result


def test_delete(monkeypatch, invoke):
    current = {"id": "s1", "username": "svc-ci", "is_active": True}
    monkeypatch.setattr(service_account, "service_account_by_name", lambda client, name: current)
    client = RecordingClient([None])
    result = invoke(service_account.run_module, FakeModule(params(state="absent")), client)
    assert result["service_account"] is None
    assert client.calls[0][0] == "DELETE"


def test_already_absent(monkeypatch, invoke):
    monkeypatch.setattr(service_account, "service_account_by_name", lambda client, name: None)
    result = invoke(service_account.run_module, FakeModule(params(state="absent")), RecordingClient())
    assert result["changed"] is False


def test_check_mode(monkeypatch, invoke):
    monkeypatch.setattr(service_account, "service_account_by_name", lambda client, name: None)
    client = RecordingClient()
    result = invoke(service_account.run_module, FakeModule(params(description="CI"), check_mode=True), client)
    assert result["changed"] is True
    assert client.calls == []


def test_api_failure(monkeypatch):
    monkeypatch.setattr(service_account, "service_account_by_name", lambda client, name: None)
    client = RecordingClient([ArtifactKeeperError("boom")])
    with pytest.raises(ArtifactKeeperError):
        service_account.run_module(FakeModule(params()), client)


def test_prefixed_name_is_not_double_prefixed(monkeypatch, invoke):
    monkeypatch.setattr(service_account, "service_account_by_name", lambda client, name: None)
    client = RecordingClient([{"id": "s1", "username": "svc-ci", "display_name": None, "is_active": True}])
    result = invoke(service_account.run_module, FakeModule(params(name="svc-ci")), client)
    assert result["changed"] is True
    assert client.calls[0][2]["data"]["name"] == "ci"


def test_check_mode_canonicalizes_service_account_username(monkeypatch, invoke):
    monkeypatch.setattr(service_account, "service_account_by_name", lambda client, name: None)
    result = invoke(
        service_account.run_module,
        FakeModule(params(name="Build Agent"), check_mode=True),
        RecordingClient(),
    )
    assert result["service_account"]["username"] == "svc-build-agent"
