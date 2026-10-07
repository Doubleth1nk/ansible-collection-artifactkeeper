# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    canonical_service_account_username,
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
