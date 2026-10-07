# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    canonical_service_account_username,
    group_members,
    service_account_by_name,
    service_account_create_name,
    user_by_username,
    users_by_username,
)


class Client:
    def __init__(self, items):
        self.items = items

    def get(self, path):
        assert path == "/service-accounts"
        return {"items": self.items}


def test_service_account_name_normalization():
    assert canonical_service_account_username("CI Agent") == "svc-ci-agent"
    assert canonical_service_account_username("svc-CI Agent") == "svc-ci-agent"
    assert service_account_create_name("svc-ci") == "ci"
    assert service_account_create_name("CI") == "CI"


def test_service_account_lookup_uses_canonical_username():
    item = {"id": "1", "username": "svc-ci-agent"}
    assert service_account_by_name(Client([item]), "CI Agent") == item
    assert service_account_by_name(Client([item]), "svc-ci-agent") == item


class UsersClient:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def paginate(self, path, params=None):
        self.calls.append((path, params))
        return list(self.items)


def user_row(username, email=None, is_service_account=False, id=None):
    return {
        "id": id or username,
        "username": username,
        "email": email or "%s@example.com" % username,
        "is_service_account": is_service_account,
    }


def test_users_by_username_matches_username_exactly():
    alice = user_row("alice")
    client = UsersClient([alice, user_row("alice2"), user_row("Alice", id="upper")])

    assert users_by_username(client, "alice") == [alice]
    assert client.calls == [("/users", {"search": "alice"})]


def test_users_by_username_ignores_email_matches():
    client = UsersClient([user_row("bob", email="alice")])

    assert users_by_username(client, "alice") == []


def test_users_by_username_includes_service_accounts():
    account = user_row("svc-ci", is_service_account=True)

    assert users_by_username(UsersClient([account]), "svc-ci") == [account]


def test_user_by_username_excludes_service_accounts():
    person = user_row("alice")
    account = user_row("alice", is_service_account=True, id="sa")

    assert user_by_username(UsersClient([account, person]), "alice") == person
    assert user_by_username(UsersClient([account]), "alice") is None


def test_user_by_username_returns_none_when_missing():
    assert user_by_username(UsersClient([user_row("bob")]), "alice") is None


def test_user_by_username_ambiguous_fails():
    client = UsersClient([user_row("alice", id="u1"), user_row("alice", id="u2")])

    with pytest.raises(ArtifactKeeperError, match="multiple users returned with username 'alice'"):
        user_by_username(client, "alice")


class GroupDetailClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        return self.pages.pop(0)


def member(index):
    return {"user_id": "u%d" % index, "username": "user%d" % index}


def test_group_members_single_page():
    client = GroupDetailClient([{"members": [member(1), member(2)], "members_total": 2}])

    assert group_members(client, "g1") == [member(1), member(2)]
    assert client.calls == [("/groups/g1", {"member_limit": 200, "member_offset": 0})]


def test_group_members_follows_offsets_until_total():
    first = [member(index) for index in range(200)]
    second = [member(index) for index in range(200, 250)]
    client = GroupDetailClient([
        {"members": first, "members_total": 250},
        {"members": second, "members_total": 250},
    ])

    assert group_members(client, "g1") == first + second
    assert [params["member_offset"] for path, params in client.calls] == [0, 200]


def test_group_members_stops_on_empty_page():
    client = GroupDetailClient([
        {"members": [member(1)], "members_total": 5},
        {"members": [], "members_total": 5},
    ])

    assert group_members(client, "g1", page_size=1) == [member(1)]
    assert len(client.calls) == 2


def test_group_members_without_total_pages_until_empty():
    client = GroupDetailClient([
        {"members": [member(1)]},
        {"members": [member(2)]},
        {"members": []},
    ])

    assert group_members(client, "g1", page_size=1) == [member(1), member(2)]


def test_group_members_loop_guard():
    class Endless:
        def get(self, path, params=None):
            return {"members": [member(1)]}

    with pytest.raises(ArtifactKeeperError, match="refusing an unbounded loop"):
        group_members(Endless(), "g1", page_size=1)
