# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import project_member


def params(**overrides):
    data = {"project": "engineering", "principal_type": "group", "principal": "engineers", "actions": ["read"], "state": "present"}
    data.update(overrides)
    return data


def setup_lookups(monkeypatch):
    monkeypatch.setattr(project_member, "project_by_key", lambda client, key: {"id": "p1", "key": key})
    monkeypatch.setattr(project_member, "principal_by_identifier", lambda client, ptype, ident: {"id": "g1", "name": ident})


def test_create(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    desired = {"principal_type": "group", "principal_id": "g1", "actions": ["read"]}
    client = RecordingClient([{"items": []}, desired])
    result = invoke(project_member.run_module, FakeModule(params()), client)
    assert result["changed"] is True
    assert client.calls[-1][0] == "POST"


def test_no_change(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    current = {"principal_type": "group", "principal_id": "g1", "actions": ["read"]}
    result = invoke(project_member.run_module, FakeModule(params()), RecordingClient([{"items": [current]}]))
    assert result["changed"] is False


def test_update_actions(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    current = {"principal_type": "group", "principal_id": "g1", "actions": ["read"]}
    desired = {"principal_type": "group", "principal_id": "g1", "actions": ["read", "write"]}
    client = RecordingClient([{"items": [current]}, desired])
    result = invoke(project_member.run_module, FakeModule(params(actions=["write", "read"]), diff=True), client)
    assert result["changed"] is True
    assert result["member"]["actions"] == ["read", "write"]
    assert client.calls[-1][0] == "POST"


def test_delete(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    current = {"principal_type": "group", "principal_id": "g1", "actions": ["read"]}
    client = RecordingClient([{"items": [current]}, None])
    result = invoke(project_member.run_module, FakeModule(params(state="absent", actions=None)), client)
    assert result["member"] is None
    assert client.calls[-1][0] == "DELETE"


def test_already_absent(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    result = invoke(project_member.run_module, FakeModule(params(state="absent", actions=None)), RecordingClient([{"items": []}]))
    assert result["changed"] is False


def test_check_mode(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": []}])
    result = invoke(project_member.run_module, FakeModule(params(), check_mode=True), client)
    assert result["changed"] is True
    assert [call[0] for call in client.calls] == ["GET"]


def test_api_failure(monkeypatch):
    setup_lookups(monkeypatch)
    with pytest.raises(ArtifactKeeperError):
        project_member.run_module(FakeModule(params()), RecordingClient([ArtifactKeeperError("boom")]))
