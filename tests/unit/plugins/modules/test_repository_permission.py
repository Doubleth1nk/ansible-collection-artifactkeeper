# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    ModuleFail,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import repository_permission


IDENTITY = {
    "principal_type": "group",
    "principal_id": "g1",
    "target_type": "repository",
    "target_id": "r1",
}


def params(**overrides):
    data = {
        "repository": "python-local",
        "principal_type": "group",
        "principal": "engineers",
        "actions": ["read"],
        "state": "present",
    }
    data.update(overrides)
    return data


def row(**overrides):
    data = dict(IDENTITY, id="perm1", actions=["read"])
    data.update(overrides)
    return data


def setup_lookups(monkeypatch, repository=True, group=True):
    monkeypatch.setattr(
        repository_permission,
        "repository_by_key",
        lambda client, key: {"id": "r1", "key": key} if repository else None,
    )
    monkeypatch.setattr(
        repository_permission,
        "group_by_name",
        lambda client, name: {"id": "g1", "name": name} if group else None,
    )


def methods(client):
    return [call[0] for call in client.calls]


def test_create(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    created = row(actions=["read", "write"])
    client = RecordingClient([[], created])

    result = invoke(
        repository_permission.run_module,
        FakeModule(params(actions=["write", "read", "write"])),
        client,
    )

    assert result["changed"] is True
    assert result["changed_fields"] == ["actions"]
    assert result["permission"] == created
    assert "diff" not in result
    method, path, kwargs = client.calls[-1]
    assert (method, path) == ("POST", "/permissions")
    assert kwargs["data"] == dict(IDENTITY, actions=["read", "write"])
    assert kwargs["expected"] == (200,)


def test_lookup_query_params(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    client = RecordingClient([[row()]])

    invoke(repository_permission.run_module, FakeModule(params()), client)

    assert client.calls[0] == ("PAGINATE", "/permissions", {"params": IDENTITY})


def test_no_change_ignores_order_and_duplicates(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    client = RecordingClient([[row(actions=["write", "read"])]])

    result = invoke(
        repository_permission.run_module,
        FakeModule(params(actions=["read", "write", "read"])),
        client,
    )

    assert result["changed"] is False
    assert result["changed_fields"] == []
    assert methods(client) == ["PAGINATE"]


def test_update_actions_sends_full_request(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    updated = row(actions=["read", "write"])
    client = RecordingClient([[row()], updated])

    result = invoke(
        repository_permission.run_module,
        FakeModule(params(actions=["write", "read"]), diff=True),
        client,
    )

    assert result["changed"] is True
    assert result["changed_fields"] == ["actions"]
    assert result["permission"] == updated
    method, path, kwargs = client.calls[-1]
    assert (method, path) == ("PUT", "/permissions/perm1")
    assert kwargs["data"] == {
        "principal_type": "group",
        "principal_id": "g1",
        "target_type": "repository",
        "target_id": "r1",
        "actions": ["read", "write"],
    }
    assert result["diff"]["before"]["actions"] == ["read"]
    assert result["diff"]["after"]["actions"] == ["read", "write"]


def test_delete(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    client = RecordingClient([[row()], None])

    result = invoke(
        repository_permission.run_module,
        FakeModule(params(state="absent", actions=None)),
        client,
    )

    assert result["changed"] is True
    assert result["permission"] is None
    assert client.calls[-1][:2] == ("DELETE", "/permissions/perm1")


def test_absent_no_op(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    client = RecordingClient([[]])

    result = invoke(
        repository_permission.run_module,
        FakeModule(params(state="absent", actions=None)),
        client,
    )

    assert result == {"changed": False, "permission": None, "changed_fields": []}
    assert methods(client) == ["PAGINATE"]


@pytest.mark.parametrize(
    "existing, overrides, expected_actions",
    [
        ([], {}, ["read"]),
        ([row()], {"actions": ["read", "write"]}, ["read", "write"]),
        ([row()], {"state": "absent", "actions": None}, ["read"]),
    ],
    ids=["create", "update", "delete"],
)
def test_check_mode_never_writes(monkeypatch, invoke, existing, overrides, expected_actions):
    setup_lookups(monkeypatch)
    client = RecordingClient([existing])

    result = invoke(
        repository_permission.run_module,
        FakeModule(params(**overrides), check_mode=True),
        client,
    )

    assert result["changed"] is True
    assert result["permission"]["actions"] == expected_actions
    assert methods(client) == ["PAGINATE"]


def test_diff_only_when_requested(monkeypatch, invoke):
    setup_lookups(monkeypatch)

    plain = invoke(repository_permission.run_module, FakeModule(params()), RecordingClient([[], row()]))
    with_diff = invoke(
        repository_permission.run_module,
        FakeModule(params(), diff=True),
        RecordingClient([[], row()]),
    )

    assert "diff" not in plain
    assert with_diff["diff"]["before"] == {}
    assert with_diff["diff"]["after"]["actions"] == ["read"]


def test_missing_repository_fails(monkeypatch):
    setup_lookups(monkeypatch, repository=False)
    client = RecordingClient()

    with pytest.raises(ModuleFail) as exc:
        repository_permission.run_module(FakeModule(params()), client)

    assert "repository 'python-local' was not found" in exc.value.result["msg"]
    assert client.calls == []


def test_missing_group_fails(monkeypatch):
    setup_lookups(monkeypatch, group=False)

    with pytest.raises(ModuleFail) as exc:
        repository_permission.run_module(FakeModule(params()), RecordingClient())

    assert "group principal 'engineers' was not found" in exc.value.result["msg"]


def test_missing_service_account_fails(monkeypatch):
    setup_lookups(monkeypatch)
    monkeypatch.setattr(repository_permission, "service_account_by_name", lambda client, name: None)

    with pytest.raises(ModuleFail) as exc:
        repository_permission.run_module(
            FakeModule(params(principal_type="service_account", principal="ci")),
            RecordingClient(),
        )

    assert "service_account principal 'ci' was not found" in exc.value.result["msg"]


def test_missing_user_fails(monkeypatch):
    setup_lookups(monkeypatch)

    with pytest.raises(ModuleFail) as exc:
        repository_permission.run_module(
            FakeModule(params(principal_type="user", principal="alice")),
            RecordingClient([[]]),
        )

    assert "user principal 'alice' was not found" in exc.value.result["msg"]


def test_ambiguous_permission_rows_fail(monkeypatch):
    setup_lookups(monkeypatch)
    client = RecordingClient([[row(id="perm1"), row(id="perm2", actions=["write"])]])

    with pytest.raises(ArtifactKeeperError, match="multiple permission rows match"):
        repository_permission.run_module(FakeModule(params()), client)

    assert methods(client) == ["PAGINATE"]


def test_rows_for_other_identities_are_ignored(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    unrelated = [
        row(id="other-target", target_id="r2", actions=["admin"]),
        row(id="project-grant", target_type="project", actions=["admin"]),
        row(id="other-principal", principal_id="g2", actions=["admin"]),
    ]
    client = RecordingClient([unrelated, row(id="new")])

    result = invoke(repository_permission.run_module, FakeModule(params()), client)

    assert result["changed"] is True
    assert client.calls[-1][:2] == ("POST", "/permissions")


def test_service_account_principal_lookup(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    seen = []

    def lookup(client, name):
        seen.append(name)
        return {"id": "sa1", "username": "svc-ci"}

    monkeypatch.setattr(repository_permission, "service_account_by_name", lookup)
    client = RecordingClient([[], {"id": "perm1"}])

    invoke(
        repository_permission.run_module,
        FakeModule(params(principal_type="service_account", principal="svc-ci")),
        client,
    )

    assert seen == ["svc-ci"]
    assert client.calls[0][2]["params"]["principal_type"] == "service_account"
    assert client.calls[0][2]["params"]["principal_id"] == "sa1"
    assert client.calls[-1][2]["data"]["principal_id"] == "sa1"


def test_user_lookup_excludes_service_accounts_without_boolean_query(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    users = [
        {"id": "sa-row", "username": "alice", "email": "a@example.com", "is_service_account": True},
        {"id": "u1", "username": "alice", "email": "alice@example.com", "is_service_account": False},
    ]
    client = RecordingClient([users, [], {"id": "perm1"}])

    invoke(
        repository_permission.run_module,
        FakeModule(params(principal_type="user", principal="alice")),
        client,
    )

    assert client.calls[0] == ("PAGINATE", "/users", {"params": {"search": "alice"}})
    assert client.calls[1][2]["params"]["principal_id"] == "u1"


def test_user_lookup_by_email(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    users = [{"id": "u1", "username": "alice", "email": "alice@example.com", "is_service_account": False}]
    client = RecordingClient([users, [], {"id": "perm1"}])

    invoke(
        repository_permission.run_module,
        FakeModule(params(principal_type="user", principal="alice@example.com")),
        client,
    )

    assert client.calls[1][2]["params"]["principal_id"] == "u1"


def test_ambiguous_user_fails(monkeypatch):
    setup_lookups(monkeypatch)
    users = [
        {"id": "u1", "username": "alice", "email": "x@example.com", "is_service_account": False},
        {"id": "u2", "username": "bob", "email": "alice", "is_service_account": False},
    ]

    with pytest.raises(ArtifactKeeperError, match="ambiguous"):
        repository_permission.run_module(
            FakeModule(params(principal_type="user", principal="alice")),
            RecordingClient([users]),
        )


def test_empty_actions_fail(monkeypatch):
    setup_lookups(monkeypatch)
    client = RecordingClient([[]])

    with pytest.raises(ModuleFail) as exc:
        repository_permission.run_module(FakeModule(params(actions=[])), client)

    assert "at least one action" in exc.value.result["msg"]
    assert methods(client) == ["PAGINATE"]


def test_api_failure_propagates(monkeypatch):
    setup_lookups(monkeypatch)

    with pytest.raises(ArtifactKeeperError, match="boom"):
        repository_permission.run_module(FakeModule(params()), RecordingClient([ArtifactKeeperError("boom")]))
