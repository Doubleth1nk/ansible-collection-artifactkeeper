# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    ModuleFail,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import user


SECRET = "S3cret-Initial-Pw!"


def params(**overrides):
    data = {
        "username": "alice",
        "email": "alice@example.com",
        "display_name": None,
        "is_admin": None,
        "is_active": None,
        "password": None,
        "state": "present",
    }
    data.update(overrides)
    return data


def server_user(**overrides):
    data = {
        "id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "display_name": "Alice",
        "auth_provider": "local",
        "is_admin": False,
        "is_active": True,
        "is_service_account": False,
        "must_change_password": False,
    }
    data.update(overrides)
    return data


def created(generated_password=None, **overrides):
    return {"user": server_user(**overrides), "generated_password": generated_password}


def methods(client):
    return [call[0] for call in client.calls]


def write_calls(client):
    return [call for call in client.calls if call[0] in ("POST", "PUT", "PATCH", "DELETE")]


def password_calls(client):
    return [call for call in client.calls if "/password" in call[1]]


# The real lookup helpers run against RecordingClient: user_by_username issues
# one PAGINATE, and the create path issues a second one for the service-account
# clash check.


def test_create_with_explicit_password(invoke):
    client = RecordingClient([[], [], created()])

    result = invoke(user.run_module, FakeModule(params(password=SECRET)), client)

    assert result["changed"] is True
    method, path, kwargs = client.calls[-1]
    assert (method, path) == ("POST", "/users")
    assert kwargs["data"] == {"username": "alice", "email": "alice@example.com", "password": SECRET}
    assert kwargs["expected"] == (200,)
    assert "password" not in result["changed_fields"]
    assert "generated_password" not in result
    assert result["user"]["id"] == "u1"


def test_create_without_password_returns_generated_password(invoke):
    client = RecordingClient([[], [], created(generated_password="gen-pw")])

    result = invoke(user.run_module, FakeModule(params()), client)

    assert "password" not in client.calls[-1][2]["data"]
    assert result["generated_password"] == "gen-pw"


def test_create_sends_supplied_fields(invoke):
    client = RecordingClient([[], [], created(is_admin=True)])

    result = invoke(
        user.run_module,
        FakeModule(params(display_name="Alice", is_admin=True)),
        client,
    )

    assert client.calls[-1][2]["data"] == {
        "username": "alice",
        "email": "alice@example.com",
        "display_name": "Alice",
        "is_admin": True,
    }
    assert result["changed_fields"] == ["display_name", "email", "is_admin"]


def test_create_inactive_patches_after_create(invoke):
    inactive = server_user(is_active=False)
    client = RecordingClient([[], [], created(), inactive])

    result = invoke(user.run_module, FakeModule(params(is_active=False)), client)

    assert methods(client) == ["PAGINATE", "PAGINATE", "POST", "PATCH"]
    assert "is_active" not in client.calls[2][2]["data"]
    assert client.calls[3][1:] == ("/users/u1", {"data": {"is_active": False}, "expected": (200,)})
    assert result["user"] == inactive


def test_create_without_email_fails(invoke):
    client = RecordingClient([[], []])

    with pytest.raises(ModuleFail) as exc:
        user.run_module(FakeModule(params(email=None, password=SECRET)), client)

    assert "email is required to create user 'alice'" in exc.value.result["msg"]
    assert SECRET not in str(exc.value.result)
    assert write_calls(client) == []


def test_service_account_username_clash_fails():
    account = server_user(id="sa1", username="svc-ci", is_service_account=True)
    client = RecordingClient([[account], [account]])

    with pytest.raises(ModuleFail) as exc:
        user.run_module(FakeModule(params(username="svc-ci")), client)

    assert "belongs to a service account" in exc.value.result["msg"]
    assert write_calls(client) == []


def test_existing_no_op(invoke):
    client = RecordingClient([[server_user()]])

    result = invoke(
        user.run_module,
        FakeModule(params(display_name="Alice", is_admin=False, is_active=True)),
        client,
    )

    assert result == {"changed": False, "user": server_user(), "changed_fields": []}
    assert methods(client) == ["PAGINATE"]


@pytest.mark.parametrize(
    "field, value",
    [
        ("email", "alice@new.example.com"),
        ("display_name", "Alice Liddell"),
        ("is_admin", True),
    ],
)
def test_update_single_field(invoke, field, value):
    updated = server_user(**{field: value})
    client = RecordingClient([[server_user()], updated])

    result = invoke(user.run_module, FakeModule(params(**{"email": None, field: value})), client)

    assert result["changed"] is True
    assert result["changed_fields"] == [field]
    assert client.calls[-1] == ("PATCH", "/users/u1", {"data": {field: value}, "expected": (200,)})
    assert result["user"] == updated


@pytest.mark.parametrize("current, desired", [(True, False), (False, True)])
def test_activate_and_deactivate(invoke, current, desired):
    client = RecordingClient([[server_user(is_active=current)], server_user(is_active=desired)])

    result = invoke(user.run_module, FakeModule(params(is_active=desired)), client)

    assert result["changed_fields"] == ["is_active"]
    assert client.calls[-1][2]["data"] == {"is_active": desired}


def test_omitted_fields_are_unmanaged(invoke):
    existing = server_user(email="other@example.com", display_name="Other", is_admin=True, is_active=False)
    client = RecordingClient([[existing]])

    result = invoke(user.run_module, FakeModule(params(email=None)), client)

    assert result["changed"] is False
    assert methods(client) == ["PAGINATE"]


def test_existing_user_password_is_ignored_with_warning(invoke):
    client = RecordingClient([[server_user()]])
    module = FakeModule(params(password=SECRET), diff=True)

    result = invoke(user.run_module, module, client)

    assert result["changed"] is False
    assert methods(client) == ["PAGINATE"]
    assert password_calls(client) == []
    assert len(module.warnings) == 1
    assert "password is only used when creating a user" in module.warnings[0]
    assert SECRET not in module.warnings[0]
    assert SECRET not in str(result)


def test_existing_user_password_with_field_change_only_patches_fields(invoke):
    client = RecordingClient([[server_user()], server_user(display_name="New")])
    module = FakeModule(params(display_name="New", password=SECRET), diff=True)

    result = invoke(user.run_module, module, client)

    assert result["changed_fields"] == ["display_name"]
    assert write_calls(client) == [("PATCH", "/users/u1", {"data": {"display_name": "New"}, "expected": (200,)})]
    assert password_calls(client) == []
    assert SECRET not in str(result)
    assert len(module.warnings) == 1


def test_delete(invoke):
    client = RecordingClient([[server_user()], None])

    result = invoke(user.run_module, FakeModule(params(state="absent", email=None)), client)

    assert result["changed"] is True
    assert result["user"] is None
    assert client.calls[-1] == ("DELETE", "/users/u1", {"expected": (200,)})


def test_absent_no_op(invoke):
    client = RecordingClient([[]])

    result = invoke(user.run_module, FakeModule(params(state="absent", email=None)), client)

    assert result == {"changed": False, "user": None, "changed_fields": []}
    assert methods(client) == ["PAGINATE"]


def test_check_mode_create(invoke):
    client = RecordingClient([[], []])

    result = invoke(
        user.run_module,
        FakeModule(params(password=SECRET, is_active=False), check_mode=True, diff=True),
        client,
    )

    assert result["changed"] is True
    assert result["user"]["username"] == "alice"
    assert result["user"]["is_active"] is False
    assert write_calls(client) == []
    assert "generated_password" not in result
    assert SECRET not in str(result)


def test_check_mode_update(invoke):
    client = RecordingClient([[server_user()]])

    result = invoke(user.run_module, FakeModule(params(is_admin=True), check_mode=True), client)

    assert result["changed"] is True
    assert result["user"]["is_admin"] is True
    assert write_calls(client) == []


def test_check_mode_delete(invoke):
    client = RecordingClient([[server_user()]])

    result = invoke(
        user.run_module,
        FakeModule(params(state="absent", email=None), check_mode=True),
        client,
    )

    assert result["changed"] is True
    assert write_calls(client) == []


def test_diff_only_when_requested(invoke):
    plain = invoke(
        user.run_module,
        FakeModule(params(is_admin=True)),
        RecordingClient([[server_user()], server_user(is_admin=True)]),
    )
    with_diff = invoke(
        user.run_module,
        FakeModule(params(is_admin=True), diff=True),
        RecordingClient([[server_user()], server_user(is_admin=True)]),
    )

    assert "diff" not in plain
    assert with_diff["diff"] == {"before": {"is_admin": False}, "after": {"is_admin": True}}


def test_create_result_and_diff_never_contain_password(invoke):
    client = RecordingClient([[], [], created()])

    result = invoke(user.run_module, FakeModule(params(password=SECRET), diff=True), client)

    assert SECRET not in str(result)
    assert "password" not in result["diff"]["after"]


def test_email_match_is_not_username_match(invoke):
    other = server_user(id="u2", username="bob", email="alice")
    client = RecordingClient([[other], [other], created()])

    result = invoke(user.run_module, FakeModule(params()), client)

    assert result["changed"] is True
    assert client.calls[-1][:2] == ("POST", "/users")


def test_service_account_rows_are_not_treated_as_users(invoke):
    account = server_user(id="sa1", is_service_account=True)
    client = RecordingClient([[account]])

    result = invoke(user.run_module, FakeModule(params(state="absent", email=None)), client)

    assert result["changed"] is False
    assert write_calls(client) == []


def test_ambiguous_username_fails():
    rows = [server_user(id="u1"), server_user(id="u2")]

    with pytest.raises(ArtifactKeeperError, match="multiple users returned with username 'alice'"):
        user.run_module(FakeModule(params()), RecordingClient([rows]))


def test_api_failure_propagates():
    with pytest.raises(ArtifactKeeperError, match="boom"):
        user.run_module(FakeModule(params()), RecordingClient([ArtifactKeeperError("boom")]))
