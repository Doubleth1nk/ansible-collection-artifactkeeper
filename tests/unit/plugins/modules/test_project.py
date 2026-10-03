# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import project


def params(**overrides):
    data = {"key": "engineering", "name": "Engineering", "description": None, "quota_bytes": None, "state": "present"}
    data.update(overrides)
    return data


def test_create(monkeypatch, invoke):
    monkeypatch.setattr(project, "project_by_key", lambda client, key: None)
    client = RecordingClient([{"id": "p1", "key": "engineering", "name": "Engineering"}])
    result = invoke(project.run_module, FakeModule(params()), client)
    assert result["changed"] is True
    assert client.calls[0][0] == "POST"


def test_no_change(monkeypatch, invoke):
    current = {"id": "p1", "key": "engineering", "name": "Engineering"}
    monkeypatch.setattr(project, "project_by_key", lambda client, key: current)
    result = invoke(project.run_module, FakeModule(params()), RecordingClient())
    assert result["changed"] is False


def test_update(monkeypatch, invoke):
    current = {"id": "p1", "key": "engineering", "name": "Old"}
    monkeypatch.setattr(project, "project_by_key", lambda client, key: current)
    client = RecordingClient([{"id": "p1", "key": "engineering", "name": "Engineering"}])
    result = invoke(project.run_module, FakeModule(params(), diff=True), client)
    assert result["changed_fields"] == ["name"]
    assert client.calls[0][0] == "PUT"
    assert "diff" in result


def test_delete(monkeypatch, invoke):
    current = {"id": "p1", "key": "engineering", "name": "Engineering"}
    monkeypatch.setattr(project, "project_by_key", lambda client, key: current)
    client = RecordingClient([None])
    result = invoke(project.run_module, FakeModule(params(state="absent", name=None)), client)
    assert result == {"changed": True, "project": None}
    assert client.calls[0][0] == "DELETE"


def test_already_absent(monkeypatch, invoke):
    monkeypatch.setattr(project, "project_by_key", lambda client, key: None)
    result = invoke(project.run_module, FakeModule(params(state="absent", name=None)), RecordingClient())
    assert result["changed"] is False


def test_check_mode_does_not_write(monkeypatch, invoke):
    monkeypatch.setattr(project, "project_by_key", lambda client, key: None)
    client = RecordingClient()
    result = invoke(project.run_module, FakeModule(params(), check_mode=True), client)
    assert result["changed"] is True
    assert client.calls == []


def test_api_failure(monkeypatch):
    monkeypatch.setattr(project, "project_by_key", lambda client, key: None)
    client = RecordingClient([ArtifactKeeperError("boom")])
    with pytest.raises(ArtifactKeeperError):
        project.run_module(FakeModule(params()), client)


def test_project_create_uses_current_200_status(monkeypatch, invoke):
    monkeypatch.setattr(project, "project_by_key", lambda client, key: None)
    client = RecordingClient([{"id": "p1", "key": "engineering", "name": "Engineering"}])
    invoke(project.run_module, FakeModule(params()), client)
    assert client.calls[0][2]["expected"] == (200,)
