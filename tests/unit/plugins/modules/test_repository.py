# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    ModuleFail,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import repository


def params(**overrides):
    data = {
        "key": "python-local", "name": "Python Local", "description": None,
        "format": "pypi", "repo_type": "local", "upstream_url": None,
        "upstream_auth_type": None, "upstream_username": None, "upstream_password": None,
        "upstream_aws": None, "force_upstream_auth_update": False, "project_key": None,
        "is_public": None, "quota_bytes": None, "age_gate": None, "state": "present",
    }
    data.update(overrides)
    return data


def test_create(monkeypatch, invoke):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: None)
    client = RecordingClient([{"id": "r1", "key": "python-local", "format": "pypi", "repo_type": "local"}])
    result = invoke(repository.run_module, FakeModule(params()), client)
    assert result["changed"] is True
    assert client.calls[0][0] == "POST"


def test_no_change(monkeypatch, invoke):
    current = {"id": "r1", "key": "python-local", "name": "Python Local", "format": "pypi", "repo_type": "local"}
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: current)
    result = invoke(repository.run_module, FakeModule(params()), RecordingClient())
    assert result["changed"] is False


def test_update(monkeypatch, invoke):
    states = [
        {"id": "r1", "key": "python-local", "name": "Old", "format": "pypi", "repo_type": "local"},
        {"id": "r1", "key": "python-local", "name": "Python Local", "format": "pypi", "repo_type": "local"},
    ]
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: states.pop(0))
    client = RecordingClient([{}])
    result = invoke(repository.run_module, FakeModule(params(), diff=True), client)
    assert result["changed"] is True
    assert client.calls[0][0] == "PATCH"
    assert "diff" in result


def test_delete(monkeypatch, invoke):
    current = {"id": "r1", "key": "python-local", "format": "pypi", "repo_type": "local"}
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: current)
    client = RecordingClient([None])
    result = invoke(repository.run_module, FakeModule(params(state="absent", name=None, format=None, repo_type=None)), client)
    assert result["repository"] is None
    assert client.calls[0][0] == "DELETE"


def test_already_absent(monkeypatch, invoke):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: None)
    result = invoke(repository.run_module, FakeModule(params(state="absent", name=None, format=None, repo_type=None)), RecordingClient())
    assert result["changed"] is False


def test_check_mode_create(monkeypatch, invoke):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: None)
    client = RecordingClient()
    result = invoke(repository.run_module, FakeModule(params(), check_mode=True), client)
    assert result["changed"] is True
    assert client.calls == []


def test_remote_auth_is_not_rewritten_when_visible_state_matches(monkeypatch, invoke):
    current = {
        "id": "r1", "key": "remote", "name": "Remote", "format": "pypi", "repo_type": "remote",
        "upstream_url": "https://pypi.org", "upstream_auth_configured": True, "upstream_auth_type": "bearer",
    }
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: current)
    p = params(key="remote", name="Remote", repo_type="remote", upstream_url="https://pypi.org", upstream_auth_type="bearer", upstream_password="secret")
    result = invoke(repository.run_module, FakeModule(p), RecordingClient())
    assert result["changed"] is False


def test_upstream_url_change_fails(monkeypatch):
    current = {"id": "r1", "key": "remote", "name": "Remote", "format": "pypi", "repo_type": "remote", "upstream_url": "https://old"}
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: current)
    with pytest.raises(ModuleFail):
        repository.run_module(FakeModule(params(key="remote", name="Remote", repo_type="remote", upstream_url="https://new")), RecordingClient())


def test_api_failure(monkeypatch):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: None)
    client = RecordingClient([ArtifactKeeperError("boom")])
    with pytest.raises(ArtifactKeeperError):
        repository.run_module(FakeModule(params()), client)


def test_repository_create_uses_current_200_status(monkeypatch, invoke):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: None)
    client = RecordingClient([{"id": "r1", "key": "python-local"}])
    invoke(repository.run_module, FakeModule(params()), client)
    assert client.calls[0][2]["expected"] == (200,)


def test_aws_codeartifact_auth_is_configured_after_create(monkeypatch, invoke):
    states = iter([None, {"id": "r1", "key": "remote", "repo_type": "remote", "upstream_auth_type": "aws_codeartifact"}])
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: next(states))
    p = params(
        key="remote",
        name="Remote",
        repo_type="remote",
        upstream_url="https://example.invalid/npm/repo/",
        upstream_auth_type="aws_codeartifact",
        upstream_aws={"region": "eu-west-1", "domain": "packages"},
    )
    client = RecordingClient([{"id": "r1", "key": "remote"}, None])
    result = invoke(repository.run_module, FakeModule(p), client)
    assert result["changed"] is True
    assert [call[0] for call in client.calls] == ["POST", "PUT"]
    assert client.calls[1][2]["data"] == {
        "auth_type": "aws_codeartifact",
        "aws": {"region": "eu-west-1", "domain": "packages"},
    }


def test_aws_auth_requires_region(monkeypatch):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: None)
    p = params(
        key="remote",
        name="Remote",
        repo_type="remote",
        upstream_auth_type="aws_ecr",
        upstream_aws={},
    )
    with pytest.raises(ModuleFail):
        repository.run_module(FakeModule(p), RecordingClient())


def test_create_diff_never_contains_upstream_password(monkeypatch, invoke):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: None)
    p = params(
        key="remote",
        name="Remote",
        repo_type="remote",
        upstream_url="https://example.invalid/simple",
        upstream_auth_type="basic",
        upstream_username="mirror",
        upstream_password="super-secret-upstream-password",
    )
    client = RecordingClient([{"id": "r1", "key": "remote", "repo_type": "remote"}])
    result = invoke(repository.run_module, FakeModule(p, diff=True), client)
    assert "super-secret-upstream-password" not in str(result["diff"])


def remote_repo():
    return {
        "id": "r1",
        "key": "pypi-remote",
        "name": "PyPI Remote",
        "format": "pypi",
        "repo_type": "remote",
        "upstream_url": "https://pypi.org/simple",
    }


def age_gate_params(**overrides):
    value = {"enabled": True, "min_age_days": 7, "mode": "upstream_publish_time"}
    value.update(overrides)
    return value


def test_age_gate_no_change_is_part_of_repository_state(monkeypatch, invoke):
    current_repo = remote_repo()
    current_age_gate = {
        "repository_key": "pypi-remote",
        "enabled": True,
        "min_age_days": 7,
        "mode": "upstream_publish_time",
    }
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: current_repo)
    client = RecordingClient([current_age_gate])
    result = invoke(
        repository.run_module,
        FakeModule(params(
            key="pypi-remote",
            name="PyPI Remote",
            repo_type="remote",
            upstream_url="https://pypi.org/simple",
            age_gate=age_gate_params(),
        )),
        client,
    )
    assert result["changed"] is False
    assert result["repository"]["age_gate"] == current_age_gate
    assert [call[0] for call in client.calls] == ["GET"]


def test_age_gate_update_uses_dedicated_api_but_repository_module_owns_state(monkeypatch, invoke):
    states = [remote_repo(), remote_repo()]
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: states.pop(0))
    current_age_gate = {
        "repository_key": "pypi-remote",
        "enabled": False,
        "min_age_days": 0,
        "mode": "upstream_publish_time",
    }
    updated_age_gate = {**current_age_gate, "enabled": True, "min_age_days": 7}
    client = RecordingClient([current_age_gate, updated_age_gate])
    result = invoke(
        repository.run_module,
        FakeModule(params(
            key="pypi-remote",
            name="PyPI Remote",
            repo_type="remote",
            upstream_url="https://pypi.org/simple",
            age_gate=age_gate_params(),
        ), diff=True),
        client,
    )
    assert result["changed"] is True
    assert result["changed_fields"] == ["age_gate"]
    assert [call[0] for call in client.calls] == ["GET", "PUT"]
    assert client.calls[1][1] == "/repositories/pypi-remote/age-gate"
    assert result["repository"]["age_gate"] == updated_age_gate
    assert "diff" in result


def test_age_gate_check_mode_only_reads_current_state(monkeypatch, invoke):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: remote_repo())
    current_age_gate = {
        "repository_key": "pypi-remote",
        "enabled": False,
        "min_age_days": 0,
        "mode": "upstream_publish_time",
    }
    client = RecordingClient([current_age_gate])
    result = invoke(
        repository.run_module,
        FakeModule(params(
            key="pypi-remote",
            name="PyPI Remote",
            repo_type="remote",
            upstream_url="https://pypi.org/simple",
            age_gate=age_gate_params(),
        ), check_mode=True),
        client,
    )
    assert result["changed"] is True
    assert result["repository"]["age_gate"]["enabled"] is True
    assert [call[0] for call in client.calls] == ["GET"]


def test_age_gate_is_unmanaged_when_omitted(monkeypatch, invoke):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: remote_repo())
    client = RecordingClient()
    result = invoke(
        repository.run_module,
        FakeModule(params(
            key="pypi-remote",
            name="PyPI Remote",
            repo_type="remote",
            upstream_url="https://pypi.org/simple",
        )),
        client,
    )
    assert result["changed"] is False
    assert "age_gate" not in result["repository"]
    assert client.calls == []


def test_age_gate_on_non_remote_repository_fails(monkeypatch):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: None)
    with pytest.raises(ModuleFail):
        repository.run_module(
            FakeModule(params(age_gate=age_gate_params())),
            RecordingClient(),
        )


def test_age_gate_range_is_validated(monkeypatch):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: remote_repo())
    with pytest.raises(ModuleFail):
        repository.run_module(
            FakeModule(params(
                key="pypi-remote",
                name="PyPI Remote",
                repo_type="remote",
                upstream_url="https://pypi.org/simple",
                age_gate=age_gate_params(min_age_days=3651),
            )),
            RecordingClient(),
        )


def test_age_gate_mode_is_preserved_when_omitted(monkeypatch, invoke):
    states = [remote_repo(), remote_repo()]
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: states.pop(0))
    current_age_gate = {
        "repository_key": "pypi-remote",
        "enabled": False,
        "min_age_days": 0,
        "mode": "first_seen",
    }
    updated_age_gate = {**current_age_gate, "enabled": True, "min_age_days": 7}
    client = RecordingClient([current_age_gate, updated_age_gate])
    result = invoke(
        repository.run_module,
        FakeModule(params(
            key="pypi-remote",
            name="PyPI Remote",
            repo_type="remote",
            upstream_url="https://pypi.org/simple",
            age_gate={"enabled": True, "min_age_days": 7},
        )),
        client,
    )
    assert result["changed"] is True
    assert "mode" not in client.calls[1][2]["data"]
    assert result["repository"]["age_gate"]["mode"] == "first_seen"


def test_age_gate_is_applied_after_repository_creation(monkeypatch, invoke):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: None)
    created = {
        "id": "r1",
        "key": "pypi-remote",
        "name": "PyPI Remote",
        "format": "pypi",
        "repo_type": "remote",
    }
    default_age_gate = {
        "repository_key": "pypi-remote",
        "enabled": False,
        "min_age_days": 0,
        "mode": "upstream_publish_time",
    }
    updated_age_gate = {**default_age_gate, "enabled": True, "min_age_days": 7}
    client = RecordingClient([created, default_age_gate, updated_age_gate])
    result = invoke(
        repository.run_module,
        FakeModule(params(
            key="pypi-remote",
            name="PyPI Remote",
            repo_type="remote",
            upstream_url="https://pypi.org/simple",
            age_gate=age_gate_params(),
        )),
        client,
    )
    assert result["changed"] is True
    assert [call[0] for call in client.calls] == ["POST", "GET", "PUT"]
    assert result["repository"]["age_gate"] == updated_age_gate


def test_age_gate_api_failure_propagates(monkeypatch):
    monkeypatch.setattr(repository, "repository_by_key", lambda client, key: remote_repo())
    client = RecordingClient([ArtifactKeeperError("boom")])
    with pytest.raises(ArtifactKeeperError):
        repository.run_module(
            FakeModule(params(
                key="pypi-remote",
                name="PyPI Remote",
                repo_type="remote",
                upstream_url="https://pypi.org/simple",
                age_gate=age_gate_params(),
            )),
            client,
        )
