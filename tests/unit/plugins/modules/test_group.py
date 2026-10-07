# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    ModuleFail,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import group


USER_IDS = {"alice": "u-alice", "bob": "u-bob", "carol": "u-carol", "svc-ci": "u-svc-ci"}


def params(**overrides):
    data = {
        "name": "engineers",
        "description": None,
        "members": None,
        "members_mode": "exact",
        "state": "present",
    }
    data.update(overrides)
    return data


def server_group(**overrides):
    data = {
        "id": "g1",
        "name": "engineers",
        "description": "Engineering",
        "external_source": None,
        "member_count": 2,
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-01T00:00:00Z",
    }
    data.update(overrides)
    return data


def member(username):
    return {"user_id": USER_IDS.get(username, "u-" + username), "username": username, "joined_at": "2026-10-01T00:00:00Z"}


def detail(**overrides):
    data = dict(server_group(**overrides), members=[member("alice")], members_total=7)
    return data


def setup(monkeypatch, existing=None, current=None, users=None):
    """Patch lookups; record which usernames were resolved."""
    resolved = []
    known = USER_IDS if users is None else users

    def lookup_users(client, username):
        resolved.append(username)
        if username not in known:
            return []
        return [{"id": known[username], "username": username}]

    monkeypatch.setattr(group, "group_by_name", lambda client, name: existing)
    monkeypatch.setattr(group, "group_members", lambda client, group_id: [member(name) for name in (current or [])])
    monkeypatch.setattr(group, "users_by_username", lookup_users)
    return resolved


def methods(client):
    return [call[0] for call in client.calls]


def writes(client):
    return [call for call in client.calls if call[0] in ("POST", "PUT", "PATCH", "DELETE")]


# --- create -----------------------------------------------------------------


def test_create_name_only(monkeypatch, invoke):
    setup(monkeypatch)
    client = RecordingClient([server_group(description=None, member_count=0)])

    result = invoke(group.run_module, FakeModule(params()), client)

    assert result["changed"] is True
    assert result["changed_fields"] == ["name"]
    assert client.calls == [("POST", "/groups", {"data": {"name": "engineers"}, "expected": (200,)})]
    assert "members" not in result


def test_create_with_description(monkeypatch, invoke):
    setup(monkeypatch)
    client = RecordingClient([server_group()])

    result = invoke(group.run_module, FakeModule(params(description="Engineering")), client)

    assert client.calls[0][2]["data"] == {"name": "engineers", "description": "Engineering"}
    assert result["changed_fields"] == ["name", "description"]


@pytest.mark.parametrize("mode", ["exact", "append"])
def test_create_with_members(monkeypatch, invoke, mode):
    setup(monkeypatch)
    client = RecordingClient([server_group(member_count=0), None, detail(member_count=2)])

    result = invoke(group.run_module, FakeModule(params(members=["bob", "alice"], members_mode=mode)), client)

    assert methods(client) == ["POST", "POST", "GET"]
    assert client.calls[1] == ("POST", "/groups/g1/members", {"data": {"user_ids": ["u-alice", "u-bob"]}, "expected": (200,)})
    assert result["members_added"] == ["alice", "bob"]
    assert result["members"] == ["alice", "bob"]
    assert result["changed_fields"] == ["name", "members"]
    assert result["group"]["member_count"] == 2


def test_create_with_remove_mode_adds_nobody(monkeypatch, invoke):
    resolved = setup(monkeypatch)
    client = RecordingClient([server_group(member_count=0)])

    result = invoke(group.run_module, FakeModule(params(members=["alice"], members_mode="remove")), client)

    assert methods(client) == ["POST"]
    assert resolved == []
    assert result["members"] == []


def test_create_unknown_member_fails_before_any_write(monkeypatch):
    setup(monkeypatch)
    client = RecordingClient()

    with pytest.raises(ModuleFail) as exc:
        group.run_module(FakeModule(params(members=["alice", "nobody"])), client)

    assert "user 'nobody' was not found" in exc.value.result["msg"]
    assert writes(client) == []


def test_create_check_mode(monkeypatch, invoke):
    setup(monkeypatch)
    client = RecordingClient()

    result = invoke(
        group.run_module,
        FakeModule(params(description="Engineering", members=["alice"]), check_mode=True, diff=True),
        client,
    )

    assert result["changed"] is True
    assert result["group"] == {"name": "engineers", "description": "Engineering"}
    assert result["members_added"] == ["alice"]
    assert result["diff"] == {"before": {}, "after": {"name": "engineers", "description": "Engineering", "members": ["alice"]}}
    assert writes(client) == []


# --- existing group ---------------------------------------------------------


def test_no_op(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(), current=["alice", "bob"])
    client = RecordingClient()

    result = invoke(
        group.run_module,
        FakeModule(params(description="Engineering", members=["bob", "alice"])),
        client,
    )

    assert result["changed"] is False
    assert result["changed_fields"] == []
    assert result["members"] == ["alice", "bob"]
    assert client.calls == []


def test_description_omitted_is_unmanaged(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(description="Old"))
    client = RecordingClient()

    result = invoke(group.run_module, FakeModule(params()), client)

    assert result["changed"] is False
    assert client.calls == []


def test_description_update_echoes_current_name(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(description="Old"))
    updated = server_group(description="New")
    client = RecordingClient([updated])

    result = invoke(group.run_module, FakeModule(params(description="New")), client)

    assert result["changed_fields"] == ["description"]
    assert client.calls == [("PUT", "/groups/g1", {"data": {"name": "engineers", "description": "New"}, "expected": (200,)})]
    assert result["group"] == updated


def test_empty_and_missing_description_are_equal(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(description=None))
    client = RecordingClient()

    result = invoke(group.run_module, FakeModule(params(description="")), client)

    assert result["changed"] is False
    assert client.calls == []


# --- membership -------------------------------------------------------------


def test_exact_adds_and_removes(monkeypatch, invoke):
    resolved = setup(monkeypatch, existing=server_group(), current=["alice", "bob"])
    client = RecordingClient([None, None, detail(member_count=2)])

    result = invoke(group.run_module, FakeModule(params(members=["alice", "carol"])), client)

    assert result["members_added"] == ["carol"]
    assert result["members_removed"] == ["bob"]
    assert result["members"] == ["alice", "carol"]
    assert resolved == ["carol"]
    assert writes(client) == [
        ("POST", "/groups/g1/members", {"data": {"user_ids": ["u-carol"]}, "expected": (200,)}),
        ("DELETE", "/groups/g1/members", {"data": {"user_ids": ["u-bob"]}, "expected": (200,)}),
    ]


def test_exact_empty_list_removes_everyone(monkeypatch, invoke):
    resolved = setup(monkeypatch, existing=server_group(), current=["alice", "bob"])
    client = RecordingClient([None, detail(member_count=0)])

    result = invoke(group.run_module, FakeModule(params(members=[])), client)

    assert result["members_removed"] == ["alice", "bob"]
    assert result["members"] == []
    assert resolved == []
    assert writes(client) == [("DELETE", "/groups/g1/members", {"data": {"user_ids": ["u-alice", "u-bob"]}, "expected": (200,)})]


def test_append_never_removes(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(), current=["alice", "bob"])
    client = RecordingClient([None, detail(member_count=3)])

    result = invoke(group.run_module, FakeModule(params(members=["carol", "alice"], members_mode="append")), client)

    assert result["members_added"] == ["carol"]
    assert result["members_removed"] == []
    assert result["members"] == ["alice", "bob", "carol"]
    assert [call[0] for call in writes(client)] == ["POST"]


def test_remove_only_removes_current_members_without_lookups(monkeypatch, invoke):
    resolved = setup(monkeypatch, existing=server_group(), current=["alice", "bob"])
    client = RecordingClient([None, detail(member_count=1)])

    result = invoke(
        group.run_module,
        FakeModule(params(members=["bob", "nobody", "carol"], members_mode="remove")),
        client,
    )

    assert result["members_removed"] == ["bob"]
    assert result["members"] == ["alice"]
    assert resolved == []
    assert writes(client) == [("DELETE", "/groups/g1/members", {"data": {"user_ids": ["u-bob"]}, "expected": (200,)})]


def test_remove_absent_members_is_no_op(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(), current=["alice"])
    client = RecordingClient()

    result = invoke(group.run_module, FakeModule(params(members=["nobody"], members_mode="remove")), client)

    assert result["changed"] is False
    assert client.calls == []


def test_duplicate_members_are_deduplicated(monkeypatch, invoke):
    resolved = setup(monkeypatch, existing=server_group(), current=[])
    client = RecordingClient([None, detail(member_count=1)])

    result = invoke(group.run_module, FakeModule(params(members=["alice", "alice"])), client)

    assert resolved == ["alice"]
    assert writes(client)[0][2]["data"] == {"user_ids": ["u-alice"]}
    assert result["members"] == ["alice"]


def test_empty_username_fails(monkeypatch):
    setup(monkeypatch, existing=server_group(), current=[])

    with pytest.raises(ModuleFail) as exc:
        group.run_module(FakeModule(params(members=["alice", ""])), RecordingClient())

    assert "must not contain empty usernames" in exc.value.result["msg"]


def test_members_omitted_reads_no_membership(monkeypatch, invoke):
    def no_members(client, group_id):
        raise AssertionError("membership must not be read when members is omitted")

    setup(monkeypatch, existing=server_group())
    monkeypatch.setattr(group, "group_members", no_members)

    result = invoke(group.run_module, FakeModule(params(description="Engineering")), RecordingClient())

    assert result["changed"] is False
    assert "members" not in result


def test_email_is_not_a_username(monkeypatch, invoke):
    monkeypatch.setattr(group, "group_by_name", lambda client, name: server_group())
    monkeypatch.setattr(group, "group_members", lambda client, group_id: [])
    other = {"id": "u-bob", "username": "bob", "email": "alice", "is_service_account": False}
    client = RecordingClient([[other]])

    with pytest.raises(ModuleFail) as exc:
        group.run_module(FakeModule(params(members=["alice"])), client)

    assert "user 'alice' was not found" in exc.value.result["msg"]
    assert client.calls == [("PAGINATE", "/users", {"params": {"search": "alice"}})]


def test_service_account_member_by_full_username(monkeypatch, invoke):
    monkeypatch.setattr(group, "group_by_name", lambda client, name: server_group())
    monkeypatch.setattr(group, "group_members", lambda client, group_id: [])
    account = {"id": "u-svc-ci", "username": "svc-ci", "is_service_account": True}
    client = RecordingClient([[account], None, detail(member_count=1)])

    result = invoke(group.run_module, FakeModule(params(members=["svc-ci"])), client)

    assert result["members_added"] == ["svc-ci"]
    assert writes(client)[0] == ("POST", "/groups/g1/members", {"data": {"user_ids": ["u-svc-ci"]}, "expected": (200,)})


def test_ambiguous_username_fails(monkeypatch):
    monkeypatch.setattr(group, "group_by_name", lambda client, name: server_group())
    monkeypatch.setattr(group, "group_members", lambda client, group_id: [])
    rows = [{"id": "u1", "username": "alice"}, {"id": "u2", "username": "alice"}]
    client = RecordingClient([rows])

    with pytest.raises(ModuleFail) as exc:
        group.run_module(FakeModule(params(members=["alice"])), client)

    assert "username 'alice' is ambiguous" in exc.value.result["msg"]
    assert writes(client) == []


def test_check_mode_membership_changes(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(description="Old"), current=["alice", "bob"])
    client = RecordingClient()

    result = invoke(
        group.run_module,
        FakeModule(params(description="New", members=["alice", "carol"]), check_mode=True),
        client,
    )

    assert result["changed"] is True
    assert result["changed_fields"] == ["description", "members"]
    assert result["members_added"] == ["carol"]
    assert result["members_removed"] == ["bob"]
    assert result["group"]["description"] == "New"
    assert writes(client) == []


def test_refresh_after_membership_writes(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(member_count=2), current=["alice", "bob"])
    client = RecordingClient([None, detail(member_count=3)])

    result = invoke(group.run_module, FakeModule(params(members=["carol"], members_mode="append")), client)

    assert client.calls[-1] == ("GET", "/groups/g1", {"params": {"member_limit": 1, "member_offset": 0}})
    assert result["group"]["member_count"] == 3
    assert "members" not in result["group"]
    assert "members_total" not in result["group"]


# --- externally managed groups ---------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"members": ["alice"]},
        {"members": []},
        {"members": ["alice"], "members_mode": "append"},
        {"members": ["alice"], "members_mode": "remove"},
        {"members": ["alice"], "description": "New"},
    ],
    ids=["exact-matching", "exact-empty", "append", "remove", "with-description-change"],
)
def test_external_group_rejects_members(monkeypatch, overrides):
    setup(monkeypatch, existing=server_group(external_source="oidc"), current=["alice"])
    client = RecordingClient()

    with pytest.raises(ModuleFail) as exc:
        group.run_module(FakeModule(params(**overrides)), client)

    assert "managed by 'oidc'" in exc.value.result["msg"]
    assert client.calls == []


def test_external_group_allows_description_change(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(external_source="ldap", description="Old"))
    client = RecordingClient([server_group(external_source="ldap", description="New")])

    result = invoke(group.run_module, FakeModule(params(description="New")), client)

    assert result["changed_fields"] == ["description"]
    assert [call[0] for call in writes(client)] == ["PUT"]


def test_external_group_can_be_deleted(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(external_source="saml"))
    client = RecordingClient([None])

    result = invoke(group.run_module, FakeModule(params(state="absent")), client)

    assert result["changed"] is True
    assert client.calls == [("DELETE", "/groups/g1", {"expected": (200,)})]


# --- absent -----------------------------------------------------------------


def test_delete(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group())
    client = RecordingClient([None])

    result = invoke(group.run_module, FakeModule(params(state="absent", members=["alice"])), client)

    assert result["group"] is None
    assert result["changed_fields"] == ["group"]
    assert client.calls == [("DELETE", "/groups/g1", {"expected": (200,)})]


def test_absent_no_op(monkeypatch, invoke):
    setup(monkeypatch)
    client = RecordingClient()

    result = invoke(group.run_module, FakeModule(params(state="absent")), client)

    assert result == {"changed": False, "group": None, "changed_fields": []}
    assert client.calls == []


def test_check_mode_delete(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group())
    client = RecordingClient()

    result = invoke(group.run_module, FakeModule(params(state="absent"), check_mode=True, diff=True), client)

    assert result["changed"] is True
    assert result["diff"] == {"before": {"name": "engineers", "description": "Engineering"}, "after": {}}
    assert client.calls == []


# --- diff and errors --------------------------------------------------------


def test_diff_only_when_requested_and_only_managed_fields(monkeypatch, invoke):
    setup(monkeypatch, existing=server_group(description="Old"), current=["alice"])

    plain = invoke(
        group.run_module,
        FakeModule(params(description="New", members=["bob"])),
        RecordingClient([server_group(description="New"), None, None, detail()]),
    )
    with_diff = invoke(
        group.run_module,
        FakeModule(params(description="New", members=["bob"]), diff=True),
        RecordingClient([server_group(description="New"), None, None, detail()]),
    )

    assert "diff" not in plain
    assert with_diff["diff"] == {
        "before": {"description": "Old", "members": ["alice"]},
        "after": {"description": "New", "members": ["bob"]},
    }


def test_api_failure_propagates(monkeypatch):
    def failing_lookup(client, name):
        raise ArtifactKeeperError("boom")

    monkeypatch.setattr(group, "group_by_name", failing_lookup)

    with pytest.raises(ArtifactKeeperError, match="boom"):
        group.run_module(FakeModule(params()), RecordingClient())
