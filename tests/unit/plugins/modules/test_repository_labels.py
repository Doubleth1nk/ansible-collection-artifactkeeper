# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    ModuleExit,
    ModuleFail,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import repository_labels


PATH = "/repositories/python-local/labels"


def params(**overrides):
    data = {"repository": "python-local", "labels": None, "labels_mode": "exact", "remove_labels": None}
    data.update(overrides)
    return data


def listed(labels):
    items = [
        {"id": "l-" + key, "repository_id": "r1", "key": key, "value": value, "created_at": "2026-10-01T00:00:00Z"}
        for key, value in sorted(labels.items())
    ]
    return {"items": items, "total": len(items)}


def writes(client):
    return [call for call in client.calls if call[0] in ("POST", "PUT", "PATCH", "DELETE")]


# --- exact mode ---------------------------------------------------------------


def test_exact_sets_labels_on_empty_repository(invoke):
    client = RecordingClient([listed({}), listed({"team": "core", "tier": "gold"})])

    result = invoke(repository_labels.run_module, FakeModule(params(labels={"tier": "gold", "team": "core"})), client)

    assert result["changed"] is True
    assert result["added"] == ["team", "tier"]
    assert result["updated"] == [] and result["removed"] == []
    assert result["changed_fields"] == ["labels"]
    assert client.calls[0] == ("GET", PATH, {"allow_404": True})
    assert client.calls[1] == (
        "PUT",
        PATH,
        {"data": {"labels": [{"key": "team", "value": "core"}, {"key": "tier", "value": "gold"}]}, "expected": (200,)},
    )
    assert result["labels"] == {"team": "core", "tier": "gold"}


def test_exact_no_op(invoke):
    client = RecordingClient([listed({"tier": "gold", "team": "core"})])

    result = invoke(repository_labels.run_module, FakeModule(params(labels={"team": "core", "tier": "gold"})), client)

    assert result["changed"] is False
    assert result["changed_fields"] == []
    assert result["labels"] == {"team": "core", "tier": "gold"}
    assert [call[0] for call in client.calls] == ["GET"]


def test_exact_updates_and_removes_with_one_put(invoke):
    client = RecordingClient([listed({"tier": "silver", "team": "core", "old": "x"}), listed({"tier": "gold", "team": "core"})])

    result = invoke(repository_labels.run_module, FakeModule(params(labels={"tier": "gold", "team": "core"})), client)

    assert result["updated"] == ["tier"]
    assert result["removed"] == ["old"]
    assert result["added"] == []
    assert [call[0] for call in writes(client)] == ["PUT"]
    assert writes(client)[0][2]["data"] == {"labels": [{"key": "team", "value": "core"}, {"key": "tier", "value": "gold"}]}


def test_exact_empty_dict_clears_all(invoke):
    client = RecordingClient([listed({"tier": "gold", "team": "core"}), listed({})])

    result = invoke(repository_labels.run_module, FakeModule(params(labels={})), client)

    assert result["removed"] == ["team", "tier"]
    assert result["labels"] == {}
    assert writes(client) == [("PUT", PATH, {"data": {"labels": []}, "expected": (200,)})]


def test_exact_empty_dict_on_empty_repository_is_no_op(invoke):
    client = RecordingClient([listed({})])

    result = invoke(repository_labels.run_module, FakeModule(params(labels={})), client)

    assert result["changed"] is False
    assert writes(client) == []


@pytest.mark.parametrize("check_mode", [False, True])
def test_exact_with_labels_omitted_fails_and_never_clears(check_mode):
    client = RecordingClient([listed({"tier": "gold"})])

    with pytest.raises(ModuleFail) as exc:
        repository_labels.run_module(FakeModule(params(labels=None), check_mode=check_mode), client)

    assert "labels is required with labels_mode=exact" in exc.value.result["msg"]
    assert "labels: {}" in exc.value.result["msg"]
    assert client.calls == []


def test_key_only_label_is_empty_string(invoke):
    client = RecordingClient([listed({"pci": ""})])

    result = invoke(repository_labels.run_module, FakeModule(params(labels={"pci": ""})), client)

    assert result["changed"] is False
    assert result["labels"] == {"pci": ""}


def test_server_value_defaults_to_empty_string(invoke):
    response = {"items": [{"id": "l1", "repository_id": "r1", "key": "pci", "created_at": "t"}], "total": 1}
    client = RecordingClient([response])

    result = invoke(repository_labels.run_module, FakeModule(params(labels={"pci": ""})), client)

    assert result["changed"] is False


def test_matching_is_case_sensitive(invoke):
    client = RecordingClient([listed({"Tier": "gold"}), listed({"tier": "gold"})])

    result = invoke(repository_labels.run_module, FakeModule(params(labels={"tier": "gold"})), client)

    assert result["added"] == ["tier"]
    assert result["removed"] == ["Tier"]


# --- merge mode ---------------------------------------------------------------


def test_merge_adds_and_updates_only_changed_keys(invoke):
    client = RecordingClient([listed({"tier": "silver", "team": "core"}), {}, {}])

    result = invoke(
        repository_labels.run_module,
        FakeModule(params(labels_mode="merge", labels={"tier": "gold", "team": "core", "owner": "ci"})),
        client,
    )

    assert result["added"] == ["owner"]
    assert result["updated"] == ["tier"]
    assert result["removed"] == []
    assert writes(client) == [
        ("POST", PATH + "/owner", {"data": {"value": "ci"}, "expected": (200,)}),
        ("POST", PATH + "/tier", {"data": {"value": "gold"}, "expected": (200,)}),
    ]
    assert result["labels"] == {"owner": "ci", "team": "core", "tier": "gold"}


def test_merge_removes_only_present_keys(invoke):
    client = RecordingClient([listed({"tier": "gold", "team": "core"}), None])

    result = invoke(
        repository_labels.run_module,
        FakeModule(params(labels_mode="merge", remove_labels=["team", "absent"])),
        client,
    )

    assert result["removed"] == ["team"]
    assert writes(client) == [("DELETE", PATH + "/team", {"expected": (204,)})]
    assert result["labels"] == {"tier": "gold"}


def test_merge_no_op(invoke):
    client = RecordingClient([listed({"tier": "gold", "team": "core"})])

    result = invoke(
        repository_labels.run_module,
        FakeModule(params(labels_mode="merge", labels={"tier": "gold"}, remove_labels=["absent"])),
        client,
    )

    assert result["changed"] is False
    assert [call[0] for call in client.calls] == ["GET"]


def test_merge_never_uses_put(invoke):
    client = RecordingClient([listed({"a": "1"}), {}, None])

    invoke(
        repository_labels.run_module,
        FakeModule(params(labels_mode="merge", labels={"b": "2"}, remove_labels=["a"])),
        client,
    )

    assert "PUT" not in [call[0] for call in client.calls]


def test_merge_order_is_deterministic(invoke):
    current = {"zeta": "old", "alpha": "old", "mid": "keep", "gone2": "x", "gone1": "x"}
    client = RecordingClient([listed(current)] + [{}] * 4 + [None] * 2)

    invoke(
        repository_labels.run_module,
        FakeModule(params(
            labels_mode="merge",
            labels={"zeta": "new", "new2": "v", "alpha": "new", "new1": "v"},
            remove_labels=["gone2", "gone1"],
        )),
        client,
    )

    assert [(call[0], call[1]) for call in client.calls] == [
        ("GET", PATH),
        ("POST", PATH + "/alpha"),
        ("POST", PATH + "/new1"),
        ("POST", PATH + "/new2"),
        ("POST", PATH + "/zeta"),
        ("DELETE", PATH + "/gone1"),
        ("DELETE", PATH + "/gone2"),
    ]


def test_merge_remove_only_with_labels_omitted(invoke):
    client = RecordingClient([listed({"a": "1", "b": "2"}), None])

    result = invoke(
        repository_labels.run_module,
        FakeModule(params(labels_mode="merge", labels=None, remove_labels=["b"])),
        client,
    )

    assert [call[0] for call in writes(client)] == ["DELETE"]
    assert result["labels"] == {"a": "1"}


def test_merge_empty_labels_with_remove_labels(invoke):
    client = RecordingClient([listed({"a": "1"}), None])

    result = invoke(
        repository_labels.run_module,
        FakeModule(params(labels_mode="merge", labels={}, remove_labels=["a"])),
        client,
    )

    assert [call[0] for call in writes(client)] == ["DELETE"]
    assert result["labels"] == {}


@pytest.mark.parametrize("check_mode", [False, True])
def test_merge_without_any_operation_fails(check_mode):
    client = RecordingClient([listed({"a": "1"})])

    with pytest.raises(ModuleFail) as exc:
        repository_labels.run_module(FakeModule(params(labels_mode="merge"), check_mode=check_mode), client)

    assert "no label operation requested" in exc.value.result["msg"]
    assert client.calls == []


def test_merge_partial_failure_then_next_run_converges():
    first = RecordingClient([listed({"a": "old", "c": "x"}), {}, ArtifactKeeperError("boom")])
    request = params(labels_mode="merge", labels={"a": "new", "b": "new"}, remove_labels=["c"])

    with pytest.raises(ArtifactKeeperError, match="boom"):
        repository_labels.run_module(FakeModule(request), first)
    assert [(call[0], call[1]) for call in first.calls] == [
        ("GET", PATH),
        ("POST", PATH + "/a"),
        ("POST", PATH + "/b"),
    ]

    # The first POST was applied; the next run re-reads and sends only what is left.
    second = RecordingClient([listed({"a": "new", "c": "x"}), {}, None])
    with pytest.raises(ModuleExit) as exc:
        repository_labels.run_module(FakeModule(request), second)
    result = exc.value.result
    assert [(call[0], call[1]) for call in second.calls] == [
        ("GET", PATH),
        ("POST", PATH + "/b"),
        ("DELETE", PATH + "/c"),
    ]
    assert result["added"] == ["b"] and result["updated"] == [] and result["removed"] == ["c"]
    assert result["labels"] == {"a": "new", "b": "new"}


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"labels": {"tier": 1}}, "label 'tier' value must be a string"),
        ({"labels": {"tier": None}}, "label 'tier' value must be a string"),
        ({"labels": {"": "x"}}, "label keys must be non-empty strings"),
        ({"labels": {"k" * 129: "x"}}, "longer than 128 characters"),
        ({"labels": {"tier": "v" * 257}}, "longer than 256 characters"),
        ({"labels": {"tier": "gold"}, "remove_labels": ["tier"]}, "labels and remove_labels both name: tier"),
        ({"labels": {}, "remove_labels": [""]}, "label keys must be non-empty strings"),
        ({"labels_mode": "exact", "labels": {"a": "1"}, "remove_labels": ["b"]}, "remove_labels can only be used with labels_mode=merge"),
    ],
    ids=["int-value", "null-value", "empty-key", "long-key", "long-value", "overlap", "empty-remove-key", "remove-with-exact"],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_invalid_requests_fail_before_any_call(overrides, message, check_mode):
    # remove_labels cases run in merge mode unless the case is about exact mode.
    data = dict(overrides)
    data.setdefault("labels_mode", "merge" if "remove_labels" in overrides else "exact")
    client = RecordingClient([listed({"tier": "gold"})])

    with pytest.raises(ModuleFail) as exc:
        repository_labels.run_module(FakeModule(params(**data), check_mode=check_mode), client)

    assert message in exc.value.result["msg"]
    assert client.calls == []


def test_limits_are_inclusive(invoke):
    key, value = "k" * 128, "v" * 256
    client = RecordingClient([listed({key: value})])

    result = invoke(repository_labels.run_module, FakeModule(params(labels={key: value})), client)

    assert result["changed"] is False


def test_missing_repository_fails():
    client = RecordingClient([None])

    with pytest.raises(ModuleFail) as exc:
        repository_labels.run_module(FakeModule(params(labels={"a": "1"})), client)

    assert "repository 'python-local' was not found" in exc.value.result["msg"]
    assert writes(client) == []


# --- check mode, diff, encoding, errors ------------------------------------------


@pytest.mark.parametrize(
    "overrides, expected_labels",
    [
        ({"labels": {"tier": "gold", "new": "x"}}, {"new": "x", "tier": "gold"}),
        ({"labels_mode": "merge", "labels": {"new": "x"}, "remove_labels": ["team"]}, {"new": "x", "tier": "silver"}),
    ],
    ids=["exact", "merge"],
)
def test_check_mode_predicts_without_writes(invoke, overrides, expected_labels):
    client = RecordingClient([listed({"tier": "silver", "team": "core"})])

    result = invoke(repository_labels.run_module, FakeModule(params(**overrides), check_mode=True), client)

    assert result["changed"] is True
    assert result["labels"] == expected_labels
    assert [call[0] for call in client.calls] == ["GET"]


def test_diff_only_when_requested_and_adds_no_calls(invoke):
    request = params(labels={"tier": "gold"})
    responses = [listed({"tier": "silver", "team": "core"}), listed({"tier": "gold"})]

    plain_client = RecordingClient(list(responses))
    plain = invoke(repository_labels.run_module, FakeModule(request), plain_client)
    diff_client = RecordingClient(list(responses))
    with_diff = invoke(repository_labels.run_module, FakeModule(request, diff=True), diff_client)

    assert "diff" not in plain
    assert with_diff["diff"] == {"before": {"team": "core", "tier": "silver"}, "after": {"tier": "gold"}}
    assert diff_client.calls == plain_client.calls


def test_keys_and_repository_are_url_encoded(invoke):
    client = RecordingClient([listed({}), {}])

    invoke(
        repository_labels.run_module,
        FakeModule(params(repository="team/repo", labels_mode="merge", labels={"team/a b": "x"})),
        client,
    )

    assert client.calls[0][1] == "/repositories/team%2Frepo/labels"
    assert client.calls[1][1] == "/repositories/team%2Frepo/labels/team%2Fa%20b"


def test_api_failure_propagates():
    with pytest.raises(ArtifactKeeperError, match="boom"):
        repository_labels.run_module(FakeModule(params(labels={"a": "1"})), RecordingClient([ArtifactKeeperError("boom")]))
