# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    ModuleFail,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import repository_info


def params(**overrides):
    data = {"key": None, "format": None, "repo_type": None, "search": None, "project": None}
    data.update(overrides)
    return data


def test_exact_key_found(monkeypatch, invoke):
    repo = {"id": "r1", "key": "pypi-remote", "name": "PyPI Remote"}
    monkeypatch.setattr(repository_info, "repository_by_key", lambda client, key: repo if key == "pypi-remote" else None)
    client = RecordingClient()

    result = invoke(repository_info.run_module, FakeModule(params(key="pypi-remote")), client)

    assert result == {"changed": False, "repositories": [repo], "repository": repo}
    assert client.calls == []


def test_exact_key_not_found(monkeypatch, invoke):
    monkeypatch.setattr(repository_info, "repository_by_key", lambda client, key: None)

    result = invoke(repository_info.run_module, FakeModule(params(key="missing")), RecordingClient())

    assert result == {"changed": False, "repositories": [], "repository": None}


def test_list_all_without_filters(invoke):
    repos = [{"id": "r1", "key": "a"}, {"id": "r2", "key": "b"}]
    client = RecordingClient([repos])

    result = invoke(repository_info.run_module, FakeModule(params()), client)

    assert result == {"changed": False, "repositories": repos, "repository": None}
    assert client.calls == [("PAGINATE", "/repositories", {"params": None})]


def test_filters_are_mapped_to_api_query_names(invoke):
    client = RecordingClient([[]])

    invoke(
        repository_info.run_module,
        FakeModule(params(format="pypi", repo_type="remote", search="py")),
        client,
    )

    assert client.calls == [
        ("PAGINATE", "/repositories", {"params": {"format": "pypi", "type": "remote", "q": "py"}}),
    ]


def test_project_key_resolved_to_uuid(monkeypatch, invoke):
    monkeypatch.setattr(
        repository_info,
        "project_by_key",
        lambda client, key: {"id": "p-uuid", "key": key},
    )
    client = RecordingClient([[]])

    invoke(repository_info.run_module, FakeModule(params(project="engineering")), client)

    assert client.calls == [("PAGINATE", "/repositories", {"params": {"project": "p-uuid"}})]


def test_unknown_project_fails(monkeypatch):
    monkeypatch.setattr(repository_info, "project_by_key", lambda client, key: None)
    client = RecordingClient()

    with pytest.raises(ModuleFail) as exc:
        repository_info.run_module(FakeModule(params(project="nope")), client)

    assert "project 'nope' was not found" in exc.value.result["msg"]
    assert client.calls == []


def test_check_mode_is_read_only(invoke):
    client = RecordingClient([[]])

    result = invoke(repository_info.run_module, FakeModule(params(), check_mode=True), client)

    assert result["changed"] is False
    assert [call[0] for call in client.calls] == ["PAGINATE"]


def test_api_failure_propagates():
    with pytest.raises(ArtifactKeeperError, match="boom"):
        repository_info.run_module(FakeModule(params()), RecordingClient([ArtifactKeeperError("boom")]))
