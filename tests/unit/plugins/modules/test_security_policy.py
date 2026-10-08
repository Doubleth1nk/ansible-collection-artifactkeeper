# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    ModuleFail,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperHTTPError
from ansible_collections.artifactkeeper.core.plugins.modules import security_policy


LIST = "/security/policies"
REPO_ID = "11111111-1111-1111-1111-111111111111"
OTHER_REPO_ID = "22222222-2222-2222-2222-222222222222"
SETTINGS = (
    "max_severity",
    "block_on_fail",
    "block_unscanned",
    "require_signature",
    "min_staging_hours",
    "max_artifact_age_days",
    "enabled",
)


def params(**overrides):
    data = {"name": "baseline", "repository": None, "state": "present"}
    data.update({setting: None for setting in SETTINGS})
    data.update(overrides)
    return data


def policy(**fields):
    row = {
        "id": "p1",
        "name": "baseline",
        "repository_id": None,
        "max_severity": "critical",
        "block_unscanned": True,
        "block_on_fail": False,
        "is_enabled": True,
        "require_signature": False,
        "min_staging_hours": None,
        "max_artifact_age_days": None,
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-01T00:00:00Z",
    }
    row.update(fields)
    return row


@pytest.fixture
def repositories(monkeypatch):
    """Resolve repository keys like Artifact Keeper would; records every lookup."""
    known = {"pypi-staging": {"id": REPO_ID, "key": "pypi-staging"}, "npm-staging": {"id": OTHER_REPO_ID, "key": "npm-staging"}}
    lookups = []

    def lookup(client, key):
        lookups.append(key)
        return known.get(key)

    monkeypatch.setattr(security_policy, "repository_by_key", lookup)
    return lookups


def writes(client):
    return [call for call in client.calls if call[0] != "GET"]


def fail(module, client):
    with pytest.raises(ModuleFail) as exc:
        security_policy.run_module(module, client)
    return exc.value.result


# --- create -------------------------------------------------------------------


def test_create_global_minimal(invoke, repositories):
    created = policy()
    client = RecordingClient([[], created])
    result = invoke(security_policy.run_module, FakeModule(params(max_severity="critical", block_on_fail=False)), client)

    assert result["changed"] is True
    assert result["policy"] == created
    assert result["changed_fields"] == ["block_on_fail", "max_severity", "name"]
    assert client.calls == [
        ("GET", LIST, {}),
        ("POST", LIST, {"data": {"name": "baseline", "repository_id": None, "max_severity": "critical", "block_on_fail": False}, "expected": (200,)}),
    ]
    assert repositories == []


def test_create_repository_scoped_resolves_key(invoke, repositories):
    client = RecordingClient([[], policy(repository_id=REPO_ID)])
    result = invoke(
        security_policy.run_module,
        FakeModule(params(repository="pypi-staging", max_severity="high", block_on_fail=True)),
        client,
    )

    assert repositories == ["pypi-staging"]
    assert writes(client)[0][2]["data"] == {
        "name": "baseline",
        "repository_id": REPO_ID,
        "max_severity": "high",
        "block_on_fail": True,
    }
    assert result["changed_fields"] == ["block_on_fail", "max_severity", "name", "repository"]


def test_create_with_every_option(invoke, repositories):
    client = RecordingClient([[], policy()])
    invoke(
        security_policy.run_module,
        FakeModule(
            params(
                max_severity="medium",
                block_on_fail=True,
                block_unscanned=False,
                require_signature=True,
                min_staging_hours=24,
                max_artifact_age_days=365,
                enabled=True,
            )
        ),
        client,
    )

    # enabled: true is the create default, so no follow-up update is needed.
    assert writes(client) == [
        (
            "POST",
            LIST,
            {
                "data": {
                    "name": "baseline",
                    "repository_id": None,
                    "max_severity": "medium",
                    "block_on_fail": True,
                    "block_unscanned": False,
                    "require_signature": True,
                    "min_staging_hours": 24,
                    "max_artifact_age_days": 365,
                },
                "expected": (200,),
            },
        )
    ]


def test_create_disabled_follows_up_with_update(invoke, repositories):
    disabled = policy(is_enabled=False)
    client = RecordingClient([[], policy(), disabled])
    result = invoke(
        security_policy.run_module, FakeModule(params(max_severity="critical", block_on_fail=False, enabled=False)), client
    )

    assert [call[0] for call in writes(client)] == ["POST", "PUT"]
    assert "is_enabled" not in writes(client)[0][2]["data"]
    assert writes(client)[1] == ("PUT", LIST + "/p1", {"data": {"is_enabled": False}, "expected": (200,)})
    assert result["policy"] == disabled
    assert result["changed_fields"] == ["block_on_fail", "enabled", "max_severity", "name"]


def test_create_disabled_follow_up_failure_reports_changed_without_rollback(repositories):
    created = policy(id="p-new")
    client = RecordingClient([[], created, ArtifactKeeperHTTPError(500, "boom")])
    result = fail(FakeModule(params(max_severity="critical", block_on_fail=False, enabled=False)), client)

    assert [call[0] for call in client.calls] == ["GET", "POST", "PUT"]
    assert result["changed"] is True
    assert result["policy_id"] == "p-new"
    assert result["policy"] == created
    assert "p-new" in result["msg"]
    assert "remains enabled" in result["msg"]
    assert "HTTP 500" in result["msg"]
    assert not any(call[0] == "DELETE" for call in client.calls)


@pytest.mark.parametrize(
    "overrides, missing",
    [
        ({"block_on_fail": True}, "max_severity"),
        ({"max_severity": "high"}, "block_on_fail"),
        ({}, "block_on_fail and max_severity"),
    ],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_create_requires_max_severity_and_block_on_fail(repositories, overrides, missing, check_mode):
    client = RecordingClient([[]])
    result = fail(FakeModule(params(repository="pypi-staging", **overrides), check_mode=check_mode), client)

    assert "cannot be created without %s" % missing in result["msg"]
    assert "changed" not in result
    assert writes(client) == []
    assert repositories == []


def test_create_unknown_repository_fails_before_write(repositories):
    client = RecordingClient([[]])
    result = fail(FakeModule(params(repository="missing", max_severity="high", block_on_fail=True)), client)

    assert "repository 'missing' was not found" in result["msg"]
    assert writes(client) == []


def test_create_check_mode_predicts_server_defaults(invoke, repositories):
    client = RecordingClient([[]])
    result = invoke(
        security_policy.run_module,
        FakeModule(params(repository="pypi-staging", max_severity="low", block_on_fail=True), check_mode=True),
        client,
    )

    assert result["changed"] is True
    assert result["policy"] == {
        "name": "baseline",
        "repository_id": REPO_ID,
        "max_severity": "low",
        "block_on_fail": True,
        "block_unscanned": True,
        "require_signature": False,
        "is_enabled": True,
        "min_staging_hours": None,
        "max_artifact_age_days": None,
    }
    assert writes(client) == []


def test_create_check_mode_predicts_disabled(invoke, repositories):
    client = RecordingClient([[]])
    result = invoke(
        security_policy.run_module,
        FakeModule(params(max_severity="low", block_on_fail=True, enabled=False), check_mode=True),
        client,
    )

    assert result["policy"]["is_enabled"] is False
    assert writes(client) == []


def test_create_diff(invoke, repositories):
    client = RecordingClient([[], policy(repository_id=REPO_ID, min_staging_hours=12)])
    result = invoke(
        security_policy.run_module,
        FakeModule(params(repository="pypi-staging", max_severity="high", block_on_fail=True, min_staging_hours=12), diff=True),
        client,
    )

    assert result["diff"] == {
        "before": {},
        "after": {
            "name": "baseline",
            "repository": "pypi-staging",
            "max_severity": "high",
            "block_on_fail": True,
            "min_staging_hours": 12,
        },
    }


# --- existing policy -----------------------------------------------------------


def test_no_op_sends_nothing(invoke, repositories):
    current = policy(max_severity="high", block_on_fail=True, min_staging_hours=24)
    client = RecordingClient([[current]])
    result = invoke(
        security_policy.run_module,
        FakeModule(params(max_severity="high", block_on_fail=True, block_unscanned=True, min_staging_hours=24, enabled=True)),
        client,
    )

    assert result == {"changed": False, "policy": current, "changed_fields": []}
    assert writes(client) == []


def test_name_only_on_existing_policy_manages_nothing(invoke, repositories):
    current = policy(require_signature=True, min_staging_hours=24, max_artifact_age_days=30, is_enabled=False)
    client = RecordingClient([[current]])
    result = invoke(security_policy.run_module, FakeModule(params()), client)

    # max_severity and block_on_fail are only required to create a policy.
    assert result["changed"] is False
    assert writes(client) == []


@pytest.mark.parametrize(
    "option, value, field",
    [
        ("max_severity", "low", "max_severity"),
        ("block_on_fail", True, "block_on_fail"),
        ("block_unscanned", False, "block_unscanned"),
        ("require_signature", True, "require_signature"),
        ("min_staging_hours", 48, "min_staging_hours"),
        ("max_artifact_age_days", 90, "max_artifact_age_days"),
        ("enabled", False, "is_enabled"),
    ],
)
def test_single_setting_update_sends_only_that_field(invoke, repositories, option, value, field):
    updated = policy(**{field: value})
    client = RecordingClient([[policy()], updated])
    result = invoke(security_policy.run_module, FakeModule(params(**{option: value})), client)

    assert result["changed"] is True
    assert result["changed_fields"] == [option]
    assert result["policy"] == updated
    assert writes(client) == [("PUT", LIST + "/p1", {"data": {field: value}, "expected": (200,)})]


def test_partial_update_sends_only_differences(invoke, repositories):
    client = RecordingClient([[policy()], policy(max_severity="high", is_enabled=False)])
    result = invoke(
        security_policy.run_module,
        FakeModule(params(max_severity="high", block_on_fail=False, block_unscanned=True, enabled=False)),
        client,
    )

    assert result["changed_fields"] == ["enabled", "max_severity"]
    assert writes(client)[0][2]["data"] == {"is_enabled": False, "max_severity": "high"}


def test_integer_changes_from_one_value_to_another(invoke, repositories):
    client = RecordingClient([[policy(max_artifact_age_days=30)], policy(max_artifact_age_days=60)])
    invoke(security_policy.run_module, FakeModule(params(max_artifact_age_days=60)), client)

    assert writes(client)[0][2]["data"] == {"max_artifact_age_days": 60}


def test_omitted_integer_keeps_stored_value_and_is_never_cleared(invoke, repositories):
    current = policy(min_staging_hours=24, max_artifact_age_days=30)
    client = RecordingClient([[current], policy(max_severity="low", min_staging_hours=24, max_artifact_age_days=30)])
    result = invoke(security_policy.run_module, FakeModule(params(max_severity="low"), diff=True), client)

    sent = writes(client)[0][2]["data"]
    assert sent == {"max_severity": "low"}
    assert None not in sent.values()
    assert "min_staging_hours" not in result["diff"]["after"]
    assert "max_artifact_age_days" not in result["diff"]["after"]


def test_negative_integer_is_accepted_and_sent(invoke, repositories):
    client = RecordingClient([[policy()], policy(min_staging_hours=-1)])
    invoke(security_policy.run_module, FakeModule(params(min_staging_hours=-1)), client)

    assert writes(client)[0][2]["data"] == {"min_staging_hours": -1}


def test_update_check_mode_predicts_without_writing(invoke, repositories):
    current = policy()
    client = RecordingClient([[current]])
    result = invoke(
        security_policy.run_module, FakeModule(params(max_severity="medium", enabled=False), check_mode=True), client
    )

    assert result["changed"] is True
    assert result["policy"] == dict(current, max_severity="medium", is_enabled=False)
    assert writes(client) == []


def test_update_of_scoped_policy_checks_scope(invoke, repositories):
    client = RecordingClient([[policy(repository_id=REPO_ID)], policy(repository_id=REPO_ID, block_on_fail=True)])
    invoke(security_policy.run_module, FakeModule(params(repository="pypi-staging", block_on_fail=True)), client)

    assert repositories == ["pypi-staging"]
    assert writes(client) == [("PUT", LIST + "/p1", {"data": {"block_on_fail": True}, "expected": (200,)})]


def test_update_diff_shows_repository_key_and_supplied_fields_only(invoke, repositories):
    current = policy(repository_id=REPO_ID, min_staging_hours=24)
    client = RecordingClient([[current], dict(current, max_severity="high")])
    result = invoke(
        security_policy.run_module,
        FakeModule(params(repository="pypi-staging", max_severity="high", block_on_fail=False), diff=True),
        client,
    )

    assert result["diff"] == {
        "before": {"name": "baseline", "repository": "pypi-staging", "max_severity": "critical", "block_on_fail": False},
        "after": {"name": "baseline", "repository": "pypi-staging", "max_severity": "high", "block_on_fail": False},
    }
    assert REPO_ID not in str(result["diff"])


def test_no_diff_unless_requested(invoke, repositories):
    client = RecordingClient([[policy()], policy(max_severity="high")])
    result = invoke(security_policy.run_module, FakeModule(params(max_severity="high")), client)

    assert "diff" not in result


def test_unchanged_run_has_no_diff(invoke, repositories):
    client = RecordingClient([[policy()]])
    result = invoke(security_policy.run_module, FakeModule(params(max_severity="critical"), diff=True), client)

    assert "diff" not in result


# --- identity -------------------------------------------------------------------


@pytest.mark.parametrize("state", ["present", "absent"])
def test_duplicate_names_fail_as_ambiguous(repositories, state):
    client = RecordingClient([[policy(id="p2"), policy(id="p1"), policy(id="p3", name="other")]])
    result = fail(FakeModule(params(state=state, max_severity="high", block_on_fail=True)), client)

    assert "ambiguous" in result["msg"]
    assert "p1, p2" in result["msg"]
    assert "p3" not in result["msg"]
    assert writes(client) == []


def test_similar_names_do_not_match(invoke, repositories):
    client = RecordingClient([[policy(name="Baseline"), policy(name="baseline-old"), policy(name=" baseline")], policy()])
    invoke(security_policy.run_module, FakeModule(params(max_severity="critical", block_on_fail=False)), client)

    assert [call[0] for call in writes(client)] == ["POST"]


@pytest.mark.parametrize(
    "existing_repository_id, requested, existing_scope, requested_scope",
    [
        (None, "pypi-staging", "global", "repository 'pypi-staging'"),
        (REPO_ID, None, "repository ID %s" % REPO_ID, "global"),
        (OTHER_REPO_ID, "pypi-staging", "repository ID %s" % OTHER_REPO_ID, "repository 'pypi-staging'"),
    ],
)
@pytest.mark.parametrize("state", ["present", "absent"])
def test_scope_mismatch_fails_without_writing(repositories, existing_repository_id, requested, existing_scope, requested_scope, state):
    client = RecordingClient([[policy(repository_id=existing_repository_id)]])
    result = fail(
        FakeModule(params(repository=requested, state=state, max_severity="high", block_on_fail=True)), client
    )

    assert "exists as a %s policy, but %s was requested" % (existing_scope, requested_scope) in result["msg"]
    assert "Artifact Keeper 1.10.2 cannot change the scope of a policy after creation" in result["msg"]
    assert "changed" not in result
    assert writes(client) == []


def test_scope_mismatch_message_explains_explicit_recreation(repositories):
    client = RecordingClient([[policy()]])
    result = fail(FakeModule(params(repository="pypi-staging", max_severity="high")), client)

    assert "Remove the existing policy explicitly" in result["msg"]


# --- absent ---------------------------------------------------------------------


def test_delete(invoke, repositories):
    current = policy(repository_id=REPO_ID)
    client = RecordingClient([[current], {"deleted": True}])
    result = invoke(security_policy.run_module, FakeModule(params(repository="pypi-staging", state="absent")), client)

    assert result == {"changed": True, "policy": None, "changed_fields": ["policy"]}
    assert writes(client) == [("DELETE", LIST + "/p1", {"expected": (200,)})]


def test_delete_global_needs_no_repository_lookup(invoke, repositories):
    client = RecordingClient([[policy()], {"deleted": True}])
    invoke(security_policy.run_module, FakeModule(params(state="absent")), client)

    assert repositories == []
    assert [call[0] for call in writes(client)] == ["DELETE"]


def test_absent_without_policy_is_no_op_without_repository_lookup(invoke, repositories):
    client = RecordingClient([[policy(name="other")]])
    result = invoke(security_policy.run_module, FakeModule(params(repository="gone", state="absent")), client)

    assert result == {"changed": False, "policy": None, "changed_fields": []}
    assert repositories == []
    assert writes(client) == []


def test_check_mode_delete(invoke, repositories):
    current = policy()
    client = RecordingClient([[current]])
    result = invoke(security_policy.run_module, FakeModule(params(state="absent"), check_mode=True), client)

    assert result["changed"] is True
    assert result["policy"] == current
    assert writes(client) == []


def test_delete_with_unknown_repository_fails(repositories):
    client = RecordingClient([[policy(repository_id=REPO_ID)]])
    result = fail(FakeModule(params(repository="missing", state="absent")), client)

    assert "repository 'missing' was not found" in result["msg"]
    assert writes(client) == []


def test_delete_diff(invoke, repositories):
    current = policy(repository_id=REPO_ID, min_staging_hours=24)
    client = RecordingClient([[current], {"deleted": True}])
    result = invoke(
        security_policy.run_module, FakeModule(params(repository="pypi-staging", state="absent"), diff=True), client
    )

    assert result["diff"] == {
        "before": {
            "name": "baseline",
            "repository": "pypi-staging",
            "max_severity": "critical",
            "block_on_fail": False,
            "block_unscanned": True,
            "require_signature": False,
            "min_staging_hours": 24,
            "max_artifact_age_days": None,
            "enabled": True,
        },
        "after": {},
    }


# --- validation -----------------------------------------------------------------


def test_empty_name_fails_before_any_request():
    client = RecordingClient()
    result = fail(FakeModule(params(name="")), client)

    assert result["msg"] == "name must not be empty"
    assert client.calls == []


def test_name_length_limit():
    client = RecordingClient()
    result = fail(FakeModule(params(name="x" * 256)), client)

    assert result["msg"] == "name must be at most 255 characters long"
    assert client.calls == []


def test_name_of_255_characters_is_accepted(invoke, repositories):
    name = "x" * 255
    client = RecordingClient([[], policy(name=name)])
    invoke(security_policy.run_module, FakeModule(params(name=name, max_severity="high", block_on_fail=True)), client)

    assert writes(client)[0][2]["data"]["name"] == name


def test_whitespace_name_is_not_trimmed(invoke, repositories):
    client = RecordingClient([[policy(name="baseline")], policy(name=" ")])
    invoke(security_policy.run_module, FakeModule(params(name=" ", max_severity="high", block_on_fail=True)), client)

    assert writes(client)[0][0] == "POST"
    assert writes(client)[0][2]["data"]["name"] == " "


@pytest.mark.parametrize("option", ["min_staging_hours", "max_artifact_age_days"])
@pytest.mark.parametrize("value", [-(2 ** 31) - 1, 2 ** 31])
def test_integers_outside_int32_fail(option, value):
    client = RecordingClient()
    result = fail(FakeModule(params(**{option: value})), client)

    assert result["msg"] == "%s must be between -2147483648 and 2147483647" % option
    assert client.calls == []


@pytest.mark.parametrize("value", [-(2 ** 31), 0, 2 ** 31 - 1])
def test_integers_at_int32_bounds_are_accepted(invoke, repositories, value):
    client = RecordingClient([[policy()], policy(max_artifact_age_days=value)])
    invoke(security_policy.run_module, FakeModule(params(max_artifact_age_days=value)), client)

    assert writes(client)[0][2]["data"] == {"max_artifact_age_days": value}


# --- errors ---------------------------------------------------------------------


def test_forbidden_write_propagates(repositories):
    client = RecordingClient([[policy()], ArtifactKeeperHTTPError(403, "Admin access required")])

    with pytest.raises(ArtifactKeeperHTTPError) as exc:
        security_policy.run_module(FakeModule(params(max_severity="high")), client)

    assert exc.value.status == 403


def test_create_failure_propagates_without_follow_up(repositories):
    client = RecordingClient([[], ArtifactKeeperHTTPError(403, "Admin access required")])

    with pytest.raises(ArtifactKeeperHTTPError):
        security_policy.run_module(FakeModule(params(max_severity="high", block_on_fail=True, enabled=False)), client)

    assert [call[0] for call in client.calls] == ["GET", "POST"]
