# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import service_account_token


def params(**overrides):
    data = {"service_account": "ci", "name": "automation", "description": None, "scopes": ["read"], "expires_in_days": None, "state": "present"}
    data.update(overrides)
    return data


def account():
    return {"id": "s1", "username": "svc-ci"}


def test_create_returns_plaintext_once(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    client = RecordingClient([
        {"items": []},
        {"id": "t1", "name": "automation", "token": "plaintext-secret", "policy_applied": False, "expires_at": None},
    ])
    result = invoke(service_account_token.run_module, FakeModule(params()), client)
    assert result["changed"] is True
    assert result["token"] == "plaintext-secret"
    assert "token" not in result["token_info"]


def test_existing_same_scopes_no_change(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    existing = {"id": "t1", "name": "automation", "scopes": ["write", "read"], "is_expired": False}
    client = RecordingClient([{"items": [existing]}])
    result = invoke(service_account_token.run_module, FakeModule(params(scopes=["read", "write"])), client)
    assert result["changed"] is False
    assert len(client.calls) == 1


def test_scope_update_rotates_token(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    existing = {"id": "t1", "name": "automation", "scopes": ["read"], "is_expired": False}
    client = RecordingClient([
        {"items": [existing]},
        {"id": "t2", "name": "automation", "token": "new-secret", "policy_applied": False, "expires_at": None},
        None,
    ])
    result = invoke(service_account_token.run_module, FakeModule(params(scopes=["read", "write"])), client)
    assert result["changed"] is True
    # The replacement is created before the old token is revoked, then re-read.
    assert [call[0] for call in client.calls] == ["GET", "POST", "DELETE", "GET"]
    assert client.calls[2][1] == "/service-accounts/s1/tokens/t1"


def test_delete(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    existing = {"id": "t1", "name": "automation", "scopes": ["read"], "is_expired": False}
    client = RecordingClient([{"items": [existing]}, None])
    result = invoke(service_account_token.run_module, FakeModule(params(state="absent", scopes=None)), client)
    assert result["token_info"] is None
    assert client.calls[-1][0] == "DELETE"


def test_already_absent(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    client = RecordingClient([{"items": []}])
    result = invoke(service_account_token.run_module, FakeModule(params(state="absent", scopes=None)), client)
    assert result["changed"] is False


def test_check_mode_scope_change_does_not_rotate(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    existing = {"id": "t1", "name": "automation", "scopes": ["read"], "is_expired": False}
    client = RecordingClient([{"items": [existing]}])
    result = invoke(service_account_token.run_module, FakeModule(params(scopes=["write"]), check_mode=True), client)
    assert result["changed"] is True
    assert [call[0] for call in client.calls] == ["GET"]


def test_api_failure(monkeypatch):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    client = RecordingClient([ArtifactKeeperError("boom")])
    with pytest.raises(ArtifactKeeperError):
        service_account_token.run_module(FakeModule(params()), client)


def test_absent_revokes_expired_named_token(monkeypatch, invoke):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    expired = {"id": "t-old", "name": "automation", "scopes": ["read"], "is_expired": True}
    client = RecordingClient([{"items": [expired]}, None])
    result = invoke(
        service_account_token.run_module,
        FakeModule(params(state="absent", scopes=None)),
        client,
    )
    assert result["changed"] is True
    assert [call[0] for call in client.calls] == ["GET", "DELETE"]


def test_creation_diff_contains_metadata_but_not_plaintext_token(monkeypatch, invoke):
    account = {"id": "sa1", "username": "svc-ci"}
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account)
    client = RecordingClient([
        {"items": []},
        {"id": "tok1", "name": "automation", "scopes": ["read"], "token": "plaintext-secret"},
    ])
    result = invoke(
        service_account_token.run_module,
        FakeModule(params(), diff=True),
        client,
    )
    assert result["token"] == "plaintext-secret"
    assert "plaintext-secret" not in str(result["diff"])


# Contract regression for Artifact Keeper 1.10.2, whose CreateTokenRequest sets
# additionalProperties: false: unknown fields are rejected with HTTP 400, and
# repository_ids: [] is rejected because it would mean an unrestricted token.
# When neither repositories nor repo_selector is supplied, the restriction is
# unmanaged: the module must only send these keys, and never repository_ids or
# repo_selector.
SUPPORTED_CREATE_KEYS = {"name", "scopes", "description", "expires_in_days"}


@pytest.mark.parametrize("description", [None, "CI automation"])
@pytest.mark.parametrize("expires_in_days", [None, 90])
@pytest.mark.parametrize("scopes", [["read"], ["write", "read", "read"]])
@pytest.mark.parametrize("existing_scopes", [None, ["admin"]], ids=["create", "rotate"])
def test_create_payload_contains_only_supported_keys(monkeypatch, invoke, description, expires_in_days, scopes, existing_scopes):
    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    responses = [{"items": []}]
    if existing_scopes is not None:
        responses = [{"items": [{"id": "t1", "name": "automation", "scopes": existing_scopes, "is_expired": False}]}]
    responses.append({"id": "t2", "name": "automation", "token": "new-secret", "policy_applied": False, "expires_at": None})
    client = RecordingClient(responses)

    invoke(
        service_account_token.run_module,
        FakeModule(params(description=description, expires_in_days=expires_in_days, scopes=scopes)),
        client,
    )

    creates = [call for call in client.calls if call[0] == "POST"]
    assert len(creates) == 1
    method, path, kwargs = creates[0]
    assert path == "/service-accounts/s1/tokens"
    payload = kwargs["data"]
    assert set(payload) <= SUPPORTED_CREATE_KEYS
    assert "repository_ids" not in payload
    assert "repo_selector" not in payload
    expected = {"name": "automation", "scopes": sorted(set(scopes))}
    if description is not None:
        expected["description"] = description
    if expires_in_days is not None:
        expected["expires_in_days"] = expires_in_days
    assert payload == expected


# --- repository restriction (Artifact Keeper 1.10.2) -------------------------

from ansible_collections.artifactkeeper.core.tests.unit.helpers import ModuleFail  # noqa: E402
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperHTTPError  # noqa: E402

REPOS = {
    "python-local": "11111111-1111-1111-1111-111111111111",
    "pypi-remote": "22222222-2222-2222-2222-222222222222",
    "npm-local": "33333333-3333-3333-3333-333333333333",
}
UNKNOWN_A = "aaaaaaaa-0000-0000-0000-000000000000"
UNKNOWN_B = "bbbbbbbb-0000-0000-0000-000000000000"
SECRET = "plaintext-secret-value"
CREATE_REQUEST_PROPERTIES = {"name", "scopes", "description", "expires_in_days", "repository_ids", "repo_selector"}


def scoped(**overrides):
    data = params(scopes=["read"])
    data.update({"repositories": None, "repo_selector": None})
    data.update(overrides)
    return data


def selector(match_labels=None, match_formats=None, match_pattern=None):
    # Ansible fills every declared suboption, so missing ones arrive as None.
    return {"match_labels": match_labels, "match_formats": match_formats, "match_pattern": match_pattern}


def listed(token_id="t1", scopes=None, repository_ids=None, repo_selector=None, **extra):
    data = {
        "id": token_id,
        "name": "automation",
        "scopes": scopes or ["read"],
        "is_expired": False,
        "repository_ids": repository_ids or [],
        "repo_selector": repo_selector,
    }
    data.update(extra)
    return data


def created(token_id="t2"):
    return {"id": token_id, "name": "automation", "token": SECRET, "policy_applied": False, "expires_at": None}


def setup_lookups(monkeypatch):
    resolved = []

    def lookup(client, key):
        resolved.append(key)
        return {"id": REPOS[key], "key": key} if key in REPOS else None

    monkeypatch.setattr(service_account_token, "service_account_by_name", lambda client, name: account())
    monkeypatch.setattr(service_account_token, "repository_by_key", lookup)
    return resolved


def calls_of(client, method):
    return [call for call in client.calls if call[0] == method]


def create_payload(client):
    posts = calls_of(client, "POST")
    assert len(posts) == 1
    return posts[0][2]["data"]


def test_create_unrestricted_sends_no_restriction(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": []}, created(), {"items": [listed("t2")]}])

    result = invoke(service_account_token.run_module, FakeModule(scoped()), client)

    payload = create_payload(client)
    assert set(payload) == {"name", "scopes"}
    assert result["changed_fields"] == ["name", "scopes"]


@pytest.mark.parametrize(
    "keys, expected_ids",
    [
        (["python-local"], [REPOS["python-local"]]),
        (["pypi-remote", "python-local"], sorted([REPOS["python-local"], REPOS["pypi-remote"]])),
        (["python-local", "python-local", "pypi-remote"], sorted([REPOS["python-local"], REPOS["pypi-remote"]])),
    ],
    ids=["one", "multiple", "duplicates"],
)
def test_create_with_repositories(monkeypatch, invoke, keys, expected_ids):
    resolved = setup_lookups(monkeypatch)
    client = RecordingClient([{"items": []}, created(), {"items": [listed("t2", repository_ids=expected_ids)]}])

    result = invoke(service_account_token.run_module, FakeModule(scoped(repositories=keys)), client)

    payload = create_payload(client)
    assert payload["repository_ids"] == expected_ids
    assert "repo_selector" not in payload
    assert resolved == sorted(set(keys))
    assert result["changed_fields"] == ["name", "scopes", "repositories"]
    assert result["token"] == SECRET
    assert result["token_info"]["repository_ids"] == expected_ids


@pytest.mark.parametrize(
    "keys, message",
    [
        (["python-local", "missing"], "repository 'missing' was not found"),
        ([], "repositories must list at least one repository key"),
        (["python-local", ""], "must not contain empty repository keys"),
        (["  "], "must not contain empty repository keys"),
    ],
    ids=["unknown", "empty-list", "empty-key", "blank-key"],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_invalid_repositories_fail_before_writes(monkeypatch, keys, message, check_mode):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": [listed()]}])

    with pytest.raises(ModuleFail) as exc:
        service_account_token.run_module(FakeModule(scoped(repositories=keys), check_mode=check_mode), client)

    assert message in exc.value.result["msg"]
    assert calls_of(client, "POST") == [] and calls_of(client, "DELETE") == []


def test_repositories_and_selector_are_mutually_exclusive(monkeypatch):
    setup_lookups(monkeypatch)
    client = RecordingClient()

    with pytest.raises(ModuleFail) as exc:
        service_account_token.run_module(
            FakeModule(scoped(repositories=["python-local"], repo_selector=selector(match_pattern="libs-*"))),
            client,
        )

    assert "mutually exclusive" in exc.value.result["msg"]
    assert client.calls == []


@pytest.mark.parametrize(
    "given, expected",
    [
        (selector(match_pattern=""), {"match_pattern": ""}),
        (selector(match_pattern="*"), {"match_pattern": "*"}),
        (selector(match_pattern="  "), {"match_pattern": "  "}),
        (selector(match_formats=[], match_pattern="libs-*"), {"match_pattern": "libs-*"}),
        (selector(match_labels={}, match_formats=["docker"]), {"match_formats": ["docker"]}),
        (selector(match_formats=["docker"], match_pattern=""), {"match_formats": ["docker"], "match_pattern": ""}),
        (selector(match_formats=["npm", "docker", "npm"]), {"match_formats": ["npm", "docker"]}),
        (selector(match_labels={"team": "core"}), {"match_labels": {"team": "core"}}),
    ],
    ids=["empty-pattern", "star", "whitespace", "empty-formats-plus-pattern", "empty-labels-plus-formats",
         "formats-plus-empty-pattern", "formats-deduplicated", "labels"],
)
def test_selector_payload_mirrors_server_validation(monkeypatch, invoke, given, expected):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": []}, created(), {"items": []}])

    result = invoke(service_account_token.run_module, FakeModule(scoped(repo_selector=given)), client)

    payload = create_payload(client)
    assert payload["repo_selector"] == expected
    assert "repository_ids" not in payload
    assert "match_repos" not in payload["repo_selector"]
    assert result["changed_fields"] == ["name", "scopes", "repo_selector"]


@pytest.mark.parametrize(
    "given, message",
    [
        (selector(), "repo_selector names no repositories"),
        (selector(match_formats=[]), "repo_selector names no repositories"),
        (selector(match_labels={}), "repo_selector names no repositories"),
        (selector(match_formats=[], match_labels={}), "repo_selector names no repositories"),
        (selector(match_labels={"tier": 1}), "match_labels value for 'tier' must be a string"),
    ],
    ids=["all-null", "empty-formats", "empty-labels", "empty-both", "non-string-label"],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_non_restricting_selector_fails_before_writes(monkeypatch, given, message, check_mode):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": []}])

    with pytest.raises(ModuleFail) as exc:
        service_account_token.run_module(FakeModule(scoped(repo_selector=given), check_mode=check_mode), client)

    assert message in exc.value.result["msg"]
    assert calls_of(client, "POST") == []


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"repositories": ["python-local", "pypi-remote"]},
        {"repo_selector": selector(match_formats=["docker"], match_pattern="")},
        {"description": "d", "expires_in_days": 30, "repositories": ["npm-local"]},
        {"description": "d", "repo_selector": selector(match_labels={"a": "b"})},
    ],
)
def test_create_payload_valid_under_additional_properties_false(monkeypatch, invoke, overrides):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": []}, created(), {"items": []}])

    invoke(service_account_token.run_module, FakeModule(scoped(**overrides)), client)

    payload = create_payload(client)
    assert set(payload) <= CREATE_REQUEST_PROPERTIES
    assert not ({"repository_ids", "repo_selector"} <= set(payload))


def test_existing_matching_repositories_is_no_op(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    existing = listed(repository_ids=[REPOS["pypi-remote"], REPOS["python-local"]])
    client = RecordingClient([{"items": [existing]}])

    result = invoke(
        service_account_token.run_module,
        FakeModule(scoped(repositories=["python-local", "pypi-remote"])),
        client,
    )

    assert result["changed"] is False
    assert result["changed_fields"] == []
    assert [call[0] for call in client.calls] == ["GET"]


@pytest.mark.parametrize(
    "stored",
    [
        {"match_formats": ["npm", "docker", "docker"]},
        {"match_formats": ["docker", "npm"], "match_labels": {}, "match_pattern": None, "match_repos": []},
    ],
    ids=["reordered-duplicated", "explicit-defaults"],
)
def test_existing_matching_selector_is_no_op(monkeypatch, invoke, stored):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": [listed(repo_selector=stored)]}])

    result = invoke(
        service_account_token.run_module,
        FakeModule(scoped(repo_selector=selector(match_formats=["docker", "npm"]))),
        client,
    )

    assert result["changed"] is False
    assert [call[0] for call in client.calls] == ["GET"]


@pytest.mark.parametrize(
    "existing, overrides, field",
    [
        (listed(repository_ids=[REPOS["python-local"]]), {"repositories": ["pypi-remote"]}, "repositories"),
        (listed(repository_ids=[]), {"repositories": ["python-local"]}, "repositories"),
        (listed(repo_selector={"match_pattern": "libs-*"}), {"repositories": ["python-local"]}, "repositories"),
        (listed(repo_selector={"match_pattern": "a-*"}), {"repo_selector": selector(match_pattern="b-*")}, "repo_selector"),
        (listed(repo_selector={"match_repos": [UNKNOWN_A]}), {"repo_selector": selector(match_pattern="*")}, "repo_selector"),
        (listed(repo_selector={"match_formats": ["docker"], "match_pattern": ""}),
         {"repo_selector": selector(match_formats=["docker"])}, "repo_selector"),
        (listed(repository_ids=[REPOS["python-local"]]), {"repo_selector": selector(match_pattern="*")}, "repo_selector"),
        (listed(repo_selector={"match_formt": ["docker"]}), {"repo_selector": selector(match_formats=["docker"])}, "repo_selector"),
    ],
    ids=["different-ids", "deleted-pins-ambiguity", "selector-to-ids", "different-selector", "inherited-match-repos",
         "empty-pattern-vs-none", "ids-to-selector", "unknown-stored-key"],
)
def test_restriction_difference_rotates_create_then_revoke(monkeypatch, invoke, existing, overrides, field):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": [existing]}, created(), None, {"items": [listed("t2")]}])

    result = invoke(service_account_token.run_module, FakeModule(scoped(**overrides)), client)

    assert result["changed"] is True
    assert result["changed_fields"] == [field]
    assert [call[0] for call in client.calls] == ["GET", "POST", "DELETE", "GET"]
    assert client.calls[2][1] == "/service-accounts/s1/tokens/t1"
    assert result["token"] == SECRET


def test_scope_and_restriction_change_rotate_once(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    existing = listed(scopes=["read"], repository_ids=[REPOS["python-local"]])
    client = RecordingClient([{"items": [existing]}, created(), None, {"items": []}])

    result = invoke(
        service_account_token.run_module,
        FakeModule(scoped(scopes=["write"], repositories=["pypi-remote"])),
        client,
    )

    assert result["changed_fields"] == ["scopes", "repositories"]
    assert len(calls_of(client, "POST")) == 1 and len(calls_of(client, "DELETE")) == 1


def test_unmanaged_restriction_never_rotates(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    inherited = listed(repo_selector={"match_repos": [UNKNOWN_A]})
    client = RecordingClient([{"items": [inherited]}])

    result = invoke(service_account_token.run_module, FakeModule(scoped()), client)

    assert result["changed"] is False
    assert [call[0] for call in client.calls] == ["GET"]


def test_check_mode_create_predicts_restriction(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": []}])

    result = invoke(
        service_account_token.run_module,
        FakeModule(scoped(repositories=["python-local"]), check_mode=True),
        client,
    )

    assert result["changed"] is True
    assert result["token_info"]["repository_ids"] == [REPOS["python-local"]]
    assert "token" not in result
    assert [call[0] for call in client.calls] == ["GET"]


def test_check_mode_rotation_makes_no_writes(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    client = RecordingClient([{"items": [listed(repository_ids=[REPOS["python-local"]])]}])

    result = invoke(
        service_account_token.run_module,
        FakeModule(scoped(repo_selector=selector(match_pattern="libs-*")), check_mode=True),
        client,
    )

    assert result["changed"] is True
    assert result["token_info"]["repo_selector"] == {"match_pattern": "libs-*"}
    assert result["token_info"]["repository_ids"] == []
    assert [call[0] for call in client.calls] == ["GET"]


def test_create_failure_during_rotation_keeps_old_token(monkeypatch):
    setup_lookups(monkeypatch)
    denied = ArtifactKeeperHTTPError(403, "A repository-restricted credential cannot set a repository restriction")
    client = RecordingClient([{"items": [listed(repository_ids=[REPOS["python-local"]])]}, denied])

    with pytest.raises(ArtifactKeeperHTTPError):
        service_account_token.run_module(FakeModule(scoped(repositories=["pypi-remote"])), client)

    assert calls_of(client, "DELETE") == []


def test_revoke_failure_rolls_back_replacement(monkeypatch):
    setup_lookups(monkeypatch)
    client = RecordingClient([
        {"items": [listed(repository_ids=[REPOS["python-local"]])]},
        created(),
        ArtifactKeeperError("revoke refused"),
        None,
    ])

    with pytest.raises(ModuleFail) as exc:
        service_account_token.run_module(FakeModule(scoped(repositories=["pypi-remote"])), client)

    result = exc.value.result
    assert [call[1] for call in calls_of(client, "DELETE")] == [
        "/service-accounts/s1/tokens/t1",
        "/service-accounts/s1/tokens/t2",
    ]
    assert "replacement was revoked again and the previous token is unchanged" in result["msg"]
    assert result["changed"] is False
    assert "token" not in result
    assert SECRET not in str(result)


def test_revoke_and_rollback_failure_reports_ids_without_plaintext(monkeypatch):
    setup_lookups(monkeypatch)
    client = RecordingClient([
        {"items": [listed(repository_ids=[REPOS["python-local"]])]},
        created(),
        ArtifactKeeperError("revoke refused"),
        ArtifactKeeperError("rollback refused"),
    ])

    with pytest.raises(ModuleFail) as exc:
        service_account_token.run_module(FakeModule(scoped(repositories=["pypi-remote"]), diff=True), client)

    result = exc.value.result
    assert result["previous_token_id"] == "t1"
    assert result["replacement_token_id"] == "t2"
    assert "two live tokens" in result["msg"]
    assert result["changed"] is True
    assert "token" not in result
    assert SECRET not in str(result)


def test_refresh_after_create_returns_listed_restriction(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    inherited = listed("t2", repo_selector={"match_repos": [UNKNOWN_A]}, token_prefix="ak_")
    client = RecordingClient([{"items": []}, dict(created(), policy_applied=True), {"items": [inherited]}])

    result = invoke(service_account_token.run_module, FakeModule(scoped()), client)

    assert result["token_info"]["repo_selector"] == {"match_repos": [UNKNOWN_A]}
    assert result["token_info"]["policy_applied"] is True
    assert "token" not in result["token_info"]
    assert result["token"] == SECRET


def test_diff_uses_repository_keys_and_numbered_placeholders(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    existing = listed(repository_ids=[UNKNOWN_B, REPOS["python-local"], UNKNOWN_A])
    responses = [{"items": [existing]}, created(), None, {"items": []}]

    without = RecordingClient(list(responses))
    invoke(service_account_token.run_module, FakeModule(scoped(repositories=["python-local", "pypi-remote"])), without)
    with_diff = RecordingClient(list(responses))
    result = invoke(
        service_account_token.run_module,
        FakeModule(scoped(repositories=["python-local", "pypi-remote"]), diff=True),
        with_diff,
    )

    diff = result["diff"]
    assert diff["after"]["repositories"] == ["pypi-remote", "python-local"]
    assert diff["before"]["repositories"] == [
        "python-local",
        "<unresolved repository #1>",
        "<unresolved repository #2>",
    ]
    rendered = str(diff)
    for repository_id in [UNKNOWN_A, UNKNOWN_B] + list(REPOS.values()):
        assert repository_id not in rendered
    assert SECRET not in rendered
    # Diff mode adds no request, in particular no repository listing.
    assert with_diff.calls == without.calls
    assert not any(call[1] == "/repositories" for call in with_diff.calls)


def test_diff_selector_hides_inherited_match_repos_ids(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    existing = listed(repo_selector={"match_repos": [UNKNOWN_B, UNKNOWN_A]})
    client = RecordingClient([{"items": [existing]}])

    result = invoke(
        service_account_token.run_module,
        FakeModule(scoped(repo_selector=selector(match_formats=["npm", "docker"])), diff=True, check_mode=True),
        client,
    )

    assert result["diff"]["before"]["repo_selector"] == {
        "match_repos": ["<unresolved repository #1>", "<unresolved repository #2>"],
    }
    assert result["diff"]["after"]["repo_selector"] == {"match_formats": ["docker", "npm"]}
    assert UNKNOWN_A not in str(result["diff"]) and UNKNOWN_B not in str(result["diff"])


def test_diff_omits_unmanaged_restriction(monkeypatch, invoke):
    setup_lookups(monkeypatch)
    existing = listed(scopes=["read"], repository_ids=[UNKNOWN_A])
    client = RecordingClient([{"items": [existing]}])

    result = invoke(
        service_account_token.run_module,
        FakeModule(scoped(scopes=["write"]), diff=True, check_mode=True),
        client,
    )

    assert result["diff"] == {
        "before": {"name": "automation", "scopes": ["read"]},
        "after": {"name": "automation", "scopes": ["write"]},
    }
