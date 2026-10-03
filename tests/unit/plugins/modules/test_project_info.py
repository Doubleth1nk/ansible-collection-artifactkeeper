# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import project_info


def test_list_all_projects(invoke):
    projects = [
        {"id": "p1", "key": "engineering", "name": "Engineering"},
        {"id": "p2", "key": "platform", "name": "Platform"},
    ]
    client = RecordingClient([{"items": projects}])

    result = invoke(project_info.run_module, FakeModule({"key": None}), client)

    assert result == {"changed": False, "projects": projects, "project": None}
    assert client.calls == [("GET", "/projects", {})]


def test_list_all_accepts_raw_list_response(invoke):
    projects = [{"id": "p1", "key": "engineering", "name": "Engineering"}]

    result = invoke(
        project_info.run_module,
        FakeModule({"key": None}),
        RecordingClient([projects]),
    )

    assert result["projects"] == projects
    assert result["project"] is None


def test_exact_key_filter(invoke):
    projects = [
        {"id": "p1", "key": "engineering", "name": "Engineering"},
        {"id": "p2", "key": "engineering-old", "name": "Engineering Old"},
    ]

    result = invoke(
        project_info.run_module,
        FakeModule({"key": "engineering"}),
        RecordingClient([{"items": projects}]),
    )

    assert result["changed"] is False
    assert result["projects"] == [projects[0]]
    assert result["project"] == projects[0]


def test_exact_key_not_found(invoke):
    projects = [{"id": "p1", "key": "platform", "name": "Platform"}]

    result = invoke(
        project_info.run_module,
        FakeModule({"key": "engineering"}),
        RecordingClient([{"items": projects}]),
    )

    assert result == {"changed": False, "projects": [], "project": None}


def test_check_mode_is_read_only(invoke):
    projects = [{"id": "p1", "key": "engineering", "name": "Engineering"}]
    client = RecordingClient([{"items": projects}])

    result = invoke(
        project_info.run_module,
        FakeModule({"key": "engineering"}, check_mode=True),
        client,
    )

    assert result["changed"] is False
    assert [call[0] for call in client.calls] == ["GET"]


def test_duplicate_key_is_rejected():
    projects = [
        {"id": "p1", "key": "engineering", "name": "Engineering"},
        {"id": "p2", "key": "engineering", "name": "Duplicate"},
    ]

    with pytest.raises(ArtifactKeeperError, match="multiple projects returned"):
        project_info.run_module(
            FakeModule({"key": "engineering"}),
            RecordingClient([{"items": projects}]),
        )


def test_unexpected_response_type_is_rejected():
    with pytest.raises(ArtifactKeeperError, match="unexpected response type"):
        project_info.run_module(
            FakeModule({"key": None}),
            RecordingClient(["not-a-project-list"]),
        )


def test_non_list_items_is_rejected():
    with pytest.raises(ArtifactKeeperError, match="non-list 'items'"):
        project_info.run_module(
            FakeModule({"key": None}),
            RecordingClient([{"items": {"key": "engineering"}}]),
        )


def test_api_failure():
    with pytest.raises(ArtifactKeeperError, match="boom"):
        project_info.run_module(
            FakeModule({"key": None}),
            RecordingClient([ArtifactKeeperError("boom")]),
        )
