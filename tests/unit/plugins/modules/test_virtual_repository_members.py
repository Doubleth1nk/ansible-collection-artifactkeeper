# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    ModuleFail,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import virtual_repository_members


def params(**overrides):
    data = {"repository": "python", "members": [{"key": "python-local", "priority": 10}, {"key": "pypi-remote", "priority": 20}]}
    data.update(overrides)
    return data


def virtual_repo():
    return {"id": "v1", "key": "python", "repo_type": "virtual", "format": "pypi"}


def test_initial_member_set(monkeypatch, invoke):
    monkeypatch.setattr(virtual_repository_members, "repository_by_key", lambda client, key: virtual_repo())
    client = RecordingClient([{"members": []}, {}])
    result = invoke(virtual_repository_members.run_module, FakeModule(params()), client)
    assert result["changed"] is True
    assert client.calls[-1][0] == "PUT"


def test_no_change(monkeypatch, invoke):
    monkeypatch.setattr(virtual_repository_members, "repository_by_key", lambda client, key: virtual_repo())
    current = {"members": [{"member_repo_key": "pypi-remote", "priority": 20}, {"member_repo_key": "python-local", "priority": 10}]}
    result = invoke(virtual_repository_members.run_module, FakeModule(params()), RecordingClient([current]))
    assert result["changed"] is False


def test_removed_member_and_priority_change(monkeypatch, invoke):
    monkeypatch.setattr(virtual_repository_members, "repository_by_key", lambda client, key: virtual_repo())
    current = {"members": [{"member_repo_key": "python-local", "priority": 1}, {"member_repo_key": "old", "priority": 2}]}
    desired = [{"key": "python-local", "priority": 10}]
    client = RecordingClient([current, {}])
    result = invoke(virtual_repository_members.run_module, FakeModule(params(members=desired), diff=True), client)
    assert result["changed"] is True
    payload = client.calls[-1][2]["data"]
    assert payload == {"members": [{"member_key": "python-local", "priority": 10}]}
    assert "diff" in result


def test_empty_list_clears_members(monkeypatch, invoke):
    monkeypatch.setattr(virtual_repository_members, "repository_by_key", lambda client, key: virtual_repo())
    current = {"members": [{"member_repo_key": "python-local", "priority": 1}]}
    client = RecordingClient([current, {}])
    result = invoke(virtual_repository_members.run_module, FakeModule(params(members=[])), client)
    assert result["changed"] is True
    assert client.calls[-1][2]["data"] == {"members": []}


def test_check_mode(monkeypatch, invoke):
    monkeypatch.setattr(virtual_repository_members, "repository_by_key", lambda client, key: virtual_repo())
    client = RecordingClient([{"members": []}])
    result = invoke(virtual_repository_members.run_module, FakeModule(params(), check_mode=True), client)
    assert result["changed"] is True
    assert [call[0] for call in client.calls] == ["GET"]


def test_non_virtual_fails(monkeypatch):
    monkeypatch.setattr(virtual_repository_members, "repository_by_key", lambda client, key: {"repo_type": "local"})
    with pytest.raises(ModuleFail):
        virtual_repository_members.run_module(FakeModule(params()), RecordingClient())


def test_duplicate_member_fails(monkeypatch):
    monkeypatch.setattr(virtual_repository_members, "repository_by_key", lambda client, key: virtual_repo())
    dup = [{"key": "x", "priority": 1}, {"key": "x", "priority": 2}]
    with pytest.raises(ModuleFail):
        virtual_repository_members.run_module(FakeModule(params(members=dup)), RecordingClient())


def test_api_failure(monkeypatch):
    monkeypatch.setattr(virtual_repository_members, "repository_by_key", lambda client, key: virtual_repo())
    with pytest.raises(ArtifactKeeperError):
        virtual_repository_members.run_module(FakeModule(params()), RecordingClient([ArtifactKeeperError("boom")]))
