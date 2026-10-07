# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    ModuleFail,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import repository_scan_config


PATH = "/repositories/pypi-remote/security"
SETTINGS = (
    "scan_enabled",
    "scan_on_upload",
    "scan_on_proxy",
    "block_on_policy_violation",
    "severity_threshold",
    "proxy_scan_action",
)
DEFAULTS = {
    "scan_enabled": False,
    "scan_on_upload": False,
    "scan_on_proxy": False,
    "block_on_policy_violation": False,
    "severity_threshold": "high",
    "proxy_scan_action": "fail_open",
}
SCORE = {
    "id": "s1",
    "repository_id": "r1",
    "score": 72,
    "grade": "C",
    "total_findings": 4,
    "critical_count": 1,
    "high_count": 1,
    "medium_count": 1,
    "low_count": 1,
    "acknowledged_count": 0,
    "calculated_at": "2026-10-01T00:00:00Z",
    "has_failed_scan": False,
}


def params(**overrides):
    data = {"repository": "pypi-remote"}
    data.update({setting: None for setting in SETTINGS})
    data.update(overrides)
    return data


def config(**settings):
    row = {
        "id": "c1",
        "repository_id": "r1",
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-01T00:00:00Z",
    }
    row.update(DEFAULTS)
    row.update(settings)
    return row


def security(row=None, score=None):
    """A RepoSecurityResponse; both keys are always present, null when absent."""
    return {"config": row, "score": score}


def writes(client):
    return [call for call in client.calls if call[0] != "GET"]


# --- no stored configuration --------------------------------------------------


def test_default_constants_match_artifact_keeper_1_10_2():
    assert repository_scan_config.DEFAULTS == DEFAULTS
    assert repository_scan_config.FIELDS == sorted(SETTINGS)


def test_missing_row_with_default_values_is_no_op(invoke):
    client = RecordingClient([security()])

    result = invoke(repository_scan_config.run_module, FakeModule(params(**DEFAULTS)), client)

    assert result["changed"] is False
    assert result["configured"] is False
    assert result["changed_fields"] == []
    assert result["scan_config"] == DEFAULTS
    assert client.calls == [("GET", PATH, {"allow_404": True})]


def test_missing_row_with_explicit_false_is_no_op(invoke):
    client = RecordingClient([security()])

    result = invoke(repository_scan_config.run_module, FakeModule(params(scan_enabled=False)), client)

    assert result["changed"] is False
    assert result["configured"] is False
    assert writes(client) == []


def test_missing_row_with_non_default_creates_configuration(invoke):
    created = config(scan_enabled=True)
    client = RecordingClient([security(), created])

    result = invoke(
        repository_scan_config.run_module,
        FakeModule(params(scan_enabled=True, scan_on_upload=False, severity_threshold="high")),
        client,
    )

    assert result["changed"] is True
    assert result["configured"] is True
    assert result["changed_fields"] == ["scan_enabled"]
    assert client.calls[1] == ("PUT", PATH, {"data": {"scan_enabled": True}, "expected": (200,)})
    assert result["scan_config"] == dict(DEFAULTS, scan_enabled=True)


def test_check_mode_predicts_creation_when_row_is_missing(invoke):
    client = RecordingClient([security()])

    result = invoke(
        repository_scan_config.run_module,
        FakeModule(params(scan_on_proxy=True, proxy_scan_action="fail_closed"), check_mode=True),
        client,
    )

    assert result["changed"] is True
    assert result["configured"] is True
    assert result["changed_fields"] == ["proxy_scan_action", "scan_on_proxy"]
    assert result["scan_config"] == dict(DEFAULTS, scan_on_proxy=True, proxy_scan_action="fail_closed")
    assert writes(client) == []


def test_check_mode_default_request_on_missing_row_stays_unconfigured(invoke):
    client = RecordingClient([security()])

    result = invoke(
        repository_scan_config.run_module, FakeModule(params(proxy_scan_action="fail_open"), check_mode=True), client
    )

    assert result["changed"] is False
    assert result["configured"] is False
    assert writes(client) == []


# --- stored configuration -----------------------------------------------------


def test_exact_no_op(invoke):
    stored = config(scan_enabled=True, scan_on_upload=True, severity_threshold="critical")
    client = RecordingClient([security(stored, SCORE)])

    result = invoke(
        repository_scan_config.run_module,
        FakeModule(params(scan_enabled=True, scan_on_upload=True, severity_threshold="critical")),
        client,
    )

    assert result["changed"] is False
    assert result["configured"] is True
    assert result["changed_fields"] == []
    assert result["scan_config"] == dict(DEFAULTS, scan_enabled=True, scan_on_upload=True, severity_threshold="critical")
    assert writes(client) == []


def test_one_field_update_sends_only_that_field(invoke):
    stored = config(scan_enabled=True)
    client = RecordingClient([security(stored), config(scan_enabled=True, scan_on_upload=True)])

    result = invoke(
        repository_scan_config.run_module, FakeModule(params(scan_enabled=True, scan_on_upload=True)), client
    )

    assert result["changed"] is True
    assert result["configured"] is True
    assert result["changed_fields"] == ["scan_on_upload"]
    assert writes(client) == [("PUT", PATH, {"data": {"scan_on_upload": True}, "expected": (200,)})]


def test_multiple_field_update_sends_exactly_the_differences(invoke):
    stored = config(scan_enabled=True, severity_threshold="high")
    response = config(
        scan_enabled=True,
        scan_on_proxy=True,
        block_on_policy_violation=True,
        severity_threshold="critical",
        proxy_scan_action="fail_closed",
    )
    client = RecordingClient([security(stored), response])

    result = invoke(
        repository_scan_config.run_module,
        FakeModule(
            params(
                scan_enabled=True,
                scan_on_proxy=True,
                block_on_policy_violation=True,
                severity_threshold="critical",
                proxy_scan_action="fail_closed",
            )
        ),
        client,
    )

    assert result["changed_fields"] == [
        "block_on_policy_violation",
        "proxy_scan_action",
        "scan_on_proxy",
        "severity_threshold",
    ]
    assert writes(client) == [
        (
            "PUT",
            PATH,
            {
                "data": {
                    "block_on_policy_violation": True,
                    "proxy_scan_action": "fail_closed",
                    "scan_on_proxy": True,
                    "severity_threshold": "critical",
                },
                "expected": (200,),
            },
        )
    ]
    assert result["scan_config"] == {setting: response[setting] for setting in SETTINGS}


def test_partial_management_ignores_unrelated_differences(invoke):
    stored = config(scan_enabled=True, scan_on_upload=True, proxy_scan_action="fail_closed", severity_threshold="low")
    client = RecordingClient([security(stored), config(scan_enabled=True, scan_on_upload=True, scan_on_proxy=True)])

    result = invoke(repository_scan_config.run_module, FakeModule(params(scan_on_proxy=True)), client)

    assert result["changed_fields"] == ["scan_on_proxy"]
    assert writes(client)[0][2]["data"] == {"scan_on_proxy": True}


def test_explicit_false_is_managed_and_disables(invoke):
    client = RecordingClient([security(config(scan_enabled=True)), config(scan_enabled=False)])

    result = invoke(repository_scan_config.run_module, FakeModule(params(scan_enabled=False)), client)

    assert result["changed_fields"] == ["scan_enabled"]
    assert writes(client)[0][2]["data"] == {"scan_enabled": False}


def test_none_is_unmanaged_even_when_stored_value_is_not_default(invoke):
    client = RecordingClient([security(config(scan_enabled=True, block_on_policy_violation=True))])

    result = invoke(
        repository_scan_config.run_module,
        FakeModule(params(scan_enabled=None, block_on_policy_violation=None, scan_on_upload=False)),
        client,
    )

    assert result["changed"] is False
    assert result["scan_config"]["scan_enabled"] is True
    assert writes(client) == []


def test_resetting_to_defaults_keeps_row_configured(invoke):
    stored = config(scan_enabled=True, proxy_scan_action="fail_closed")
    client = RecordingClient([security(stored), config()])

    result = invoke(repository_scan_config.run_module, FakeModule(params(**DEFAULTS)), client)

    assert result["changed_fields"] == ["proxy_scan_action", "scan_enabled"]
    assert result["configured"] is True
    assert result["scan_config"] == DEFAULTS


def test_read_only_fields_never_affect_idempotency(invoke):
    stored = config(scan_enabled=True)
    stored.update({"id": "other", "repository_id": "other", "created_at": "2030-01-01T00:00:00Z", "updated_at": "2030-01-02T00:00:00Z"})
    score = dict(SCORE, score=0, grade="F", has_failed_scan=True)
    client = RecordingClient([security(stored, score)])

    result = invoke(repository_scan_config.run_module, FakeModule(params(scan_enabled=True), diff=True), client)

    assert result["changed"] is False
    assert set(result["scan_config"]) == set(SETTINGS)
    assert "diff" not in result
    assert writes(client) == []


# --- read-only use, PUT body guarantees --------------------------------------


@pytest.mark.parametrize("row", [None, config(scan_enabled=True, proxy_scan_action="fail_closed")])
def test_no_managed_settings_is_read_only(invoke, row):
    client = RecordingClient([security(row, SCORE)])

    result = invoke(repository_scan_config.run_module, FakeModule(params()), client)

    assert result["changed"] is False
    assert result["changed_fields"] == []
    assert result["configured"] is (row is not None)
    assert result["scan_config"] == (DEFAULTS if row is None else dict(DEFAULTS, scan_enabled=True, proxy_scan_action="fail_closed"))
    assert client.calls == [("GET", PATH, {"allow_404": True})]


@pytest.mark.parametrize("row", [None, config(), config(scan_enabled=True, severity_threshold="info")])
@pytest.mark.parametrize(
    "settings",
    [
        {},
        DEFAULTS,
        {"scan_enabled": True},
        {"scan_enabled": True, "severity_threshold": "info"},
        {"proxy_scan_action": "fail_closed", "scan_on_proxy": False},
    ],
)
def test_put_body_is_never_empty_and_contains_only_changes(invoke, row, settings):
    client = RecordingClient([security(row), config()])

    result = invoke(repository_scan_config.run_module, FakeModule(params(**settings)), client)

    puts = writes(client)
    assert len(puts) <= 1
    for method, path, kwargs in puts:
        assert method == "PUT" and path == PATH
        assert kwargs["data"]
        assert sorted(kwargs["data"]) == result["changed_fields"]
        assert all(kwargs["data"][field] == settings[field] for field in kwargs["data"])
    assert bool(puts) == result["changed"]


# --- check mode and diff ------------------------------------------------------


def test_check_mode_on_existing_row_never_writes(invoke):
    client = RecordingClient([security(config())])

    result = invoke(
        repository_scan_config.run_module, FakeModule(params(severity_threshold="medium"), check_mode=True), client
    )

    assert result["changed"] is True
    assert result["configured"] is True
    assert result["scan_config"]["severity_threshold"] == "medium"
    assert client.calls == [("GET", PATH, {"allow_404": True})]


@pytest.mark.parametrize("check_mode", [False, True])
def test_diff_shows_only_managed_fields_without_extra_calls(invoke, check_mode):
    client = RecordingClient([security(config(scan_enabled=True), SCORE), config(scan_enabled=True, scan_on_upload=True)])

    result = invoke(
        repository_scan_config.run_module,
        FakeModule(params(scan_enabled=True, scan_on_upload=True), check_mode=check_mode, diff=True),
        client,
    )

    assert result["diff"] == {
        "before": {"scan_enabled": True, "scan_on_upload": False},
        "after": {"scan_enabled": True, "scan_on_upload": True},
    }
    assert [call[0] for call in client.calls] == (["GET"] if check_mode else ["GET", "PUT"])


def test_diff_uses_defaults_as_before_state_for_missing_row(invoke):
    client = RecordingClient([security()])

    result = invoke(
        repository_scan_config.run_module,
        FakeModule(params(severity_threshold="critical"), check_mode=True, diff=True),
        client,
    )

    assert result["diff"] == {"before": {"severity_threshold": "high"}, "after": {"severity_threshold": "critical"}}


def test_no_diff_unless_requested(invoke):
    client = RecordingClient([security(), config(scan_enabled=True)])

    result = invoke(repository_scan_config.run_module, FakeModule(params(scan_enabled=True)), client)

    assert "diff" not in result


# --- errors and request details -----------------------------------------------


@pytest.mark.parametrize("check_mode", [False, True])
def test_missing_or_invisible_repository_fails_with_ambiguous_wording(check_mode):
    client = RecordingClient([None])

    with pytest.raises(ModuleFail) as exc:
        repository_scan_config.run_module(FakeModule(params(scan_enabled=True), check_mode=check_mode), client)

    assert exc.value.result["msg"] == (
        "repository 'pypi-remote' was not found or is not visible to the current credential"
    )
    assert writes(client) == []


def test_put_failure_propagates():
    client = RecordingClient([security(), ArtifactKeeperError("HTTP 403: Repository admin permission is required")])

    with pytest.raises(ArtifactKeeperError, match="403"):
        repository_scan_config.run_module(FakeModule(params(scan_enabled=True)), client)


def test_get_failure_propagates_before_any_write():
    client = RecordingClient([ArtifactKeeperError("boom")])

    with pytest.raises(ArtifactKeeperError, match="boom"):
        repository_scan_config.run_module(FakeModule(params(scan_enabled=True)), client)

    assert writes(client) == []


def test_repository_key_is_url_encoded(invoke):
    client = RecordingClient([security()])

    invoke(repository_scan_config.run_module, FakeModule(params(repository="team/pypi remote")), client)

    assert client.calls[0][1] == "/repositories/team%2Fpypi%20remote/security"


# --- argument spec ------------------------------------------------------------


class _Captured(Exception):
    pass


@pytest.fixture
def argument_spec(monkeypatch):
    captured = {}

    def fake_make_module(spec, **kwargs):
        captured.update(spec)
        raise _Captured()

    monkeypatch.setattr(repository_scan_config, "make_module", fake_make_module)
    with pytest.raises(_Captured):
        repository_scan_config.main()
    return captured


def test_argument_spec(argument_spec):
    assert argument_spec["repository"] == {"type": "str", "required": True, "no_log": False}
    for setting in ("scan_enabled", "scan_on_upload", "scan_on_proxy", "block_on_policy_violation"):
        assert argument_spec[setting] == {"type": "bool"}
    assert argument_spec["severity_threshold"] == {"type": "str", "choices": ["critical", "high", "medium", "low", "info"]}
    assert argument_spec["proxy_scan_action"] == {"type": "str", "choices": ["fail_open", "fail_closed"]}
    assert "state" not in argument_spec
    assert not any("default" in option for option in argument_spec.values())


@pytest.mark.parametrize(
    "option, value",
    [
        ("severity_threshold", "High"),
        ("severity_threshold", "moderate"),
        ("severity_threshold", "informational"),
        ("severity_threshold", "none"),
        ("proxy_scan_action", "fail-closed"),
        ("proxy_scan_action", "FAIL_CLOSED"),
        ("proxy_scan_action", "closed"),
    ],
)
def test_only_canonical_string_values_are_accepted(argument_spec, option, value):
    arg_spec = pytest.importorskip("ansible.module_utils.common.arg_spec")
    validator = arg_spec.ArgumentSpecValidator(argument_spec)

    assert validator.validate({"repository": "pypi-remote", option: value}).error_messages
    canonical = argument_spec[option]["choices"]
    for choice in canonical:
        assert validator.validate({"repository": "pypi-remote", option: choice}).error_messages == []
