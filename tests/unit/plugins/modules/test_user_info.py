# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import user_info


def params(**overrides):
    data = {
        "username": None,
        "search": None,
        "is_admin": None,
        "is_active": None,
        "include_service_accounts": False,
    }
    data.update(overrides)
    return data


def user_row(username, is_admin=False, is_active=True, is_service_account=False, email=None):
    return {
        "id": "id-" + username,
        "username": username,
        "email": email or "%s@example.com" % username,
        "is_admin": is_admin,
        "is_active": is_active,
        "is_service_account": is_service_account,
    }


ALICE = user_row("alice", is_admin=True)
BOB = user_row("bob", is_active=False)
CAROL = user_row("carol")
SVC = user_row("svc-ci", is_service_account=True)


def test_exact_username_hit(invoke):
    client = RecordingClient([[ALICE, user_row("alice2")]])

    result = invoke(user_info.run_module, FakeModule(params(username="alice")), client)

    assert result == {"changed": False, "users": [ALICE], "user": ALICE}
    assert client.calls == [("PAGINATE", "/users", {"params": {"search": "alice"}})]


def test_exact_username_miss(invoke):
    result = invoke(
        user_info.run_module,
        FakeModule(params(username="alice")),
        RecordingClient([[user_row("alice2")]]),
    )

    assert result == {"changed": False, "users": [], "user": None}


def test_email_does_not_match_username(invoke):
    result = invoke(
        user_info.run_module,
        FakeModule(params(username="alice")),
        RecordingClient([[user_row("bob", email="alice")]]),
    )

    assert result["users"] == []
    assert result["user"] is None


def test_list_all_users(invoke):
    client = RecordingClient([[ALICE, BOB, CAROL]])

    result = invoke(user_info.run_module, FakeModule(params()), client)

    assert result == {"changed": False, "users": [ALICE, BOB, CAROL], "user": None}
    assert client.calls == [("PAGINATE", "/users", {"params": None})]


def test_search_is_passed_to_api(invoke):
    client = RecordingClient([[ALICE]])

    invoke(user_info.run_module, FakeModule(params(search="ali")), client)

    assert client.calls == [("PAGINATE", "/users", {"params": {"search": "ali"}})]


@pytest.mark.parametrize(
    "filters, expected",
    [
        ({"is_admin": True}, [ALICE]),
        ({"is_admin": False}, [BOB, CAROL]),
        ({"is_active": False}, [BOB]),
        ({"is_active": True, "is_admin": False}, [CAROL]),
    ],
)
def test_boolean_filters_are_applied_client_side(invoke, filters, expected):
    client = RecordingClient([[ALICE, BOB, CAROL]])

    result = invoke(user_info.run_module, FakeModule(params(**filters)), client)

    assert result["users"] == expected
    assert client.calls == [("PAGINATE", "/users", {"params": None})]


def test_paginated_results_are_returned_in_full(invoke):
    many = [user_row("user%03d" % index) for index in range(250)]

    result = invoke(user_info.run_module, FakeModule(params()), RecordingClient([many]))

    assert result["users"] == many


def test_service_accounts_excluded_by_default(invoke):
    result = invoke(user_info.run_module, FakeModule(params()), RecordingClient([[ALICE, SVC]]))

    assert result["users"] == [ALICE]


def test_service_accounts_included_on_request(invoke):
    result = invoke(
        user_info.run_module,
        FakeModule(params(include_service_accounts=True)),
        RecordingClient([[ALICE, SVC]]),
    )

    assert result["users"] == [ALICE, SVC]


def test_exact_username_of_service_account(invoke):
    excluded = invoke(
        user_info.run_module,
        FakeModule(params(username="svc-ci")),
        RecordingClient([[SVC]]),
    )
    included = invoke(
        user_info.run_module,
        FakeModule(params(username="svc-ci", include_service_accounts=True)),
        RecordingClient([[SVC]]),
    )

    assert excluded["user"] is None
    assert included["user"] == SVC


def test_check_mode_is_read_only(invoke):
    client = RecordingClient([[ALICE]])

    result = invoke(user_info.run_module, FakeModule(params(), check_mode=True), client)

    assert result["changed"] is False
    assert [call[0] for call in client.calls] == ["PAGINATE"]


def test_api_failure_propagates():
    with pytest.raises(ArtifactKeeperError, match="boom"):
        user_info.run_module(FakeModule(params()), RecordingClient([ArtifactKeeperError("boom")]))
