# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from ansible_collections.artifactkeeper.core.tests.unit.helpers import (
    FakeModule,
    RecordingClient,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.modules import group_info


def test_list_all(invoke):
    groups = [{"id": "g1", "name": "engineers"}, {"id": "g2", "name": "security"}]
    result = invoke(group_info.run_module, FakeModule({"name": None}), RecordingClient([groups]))
    assert result["changed"] is False
    assert result["groups"] == groups
    assert result["group"] is None


def test_exact_filter(invoke):
    groups = [{"id": "g1", "name": "engineers"}, {"id": "g2", "name": "engineers-old"}]
    client = RecordingClient([groups])
    result = invoke(group_info.run_module, FakeModule({"name": "engineers"}), client)
    assert result["groups"] == [groups[0]]
    assert result["group"] == groups[0]
    assert client.calls[0][2]["params"] == {"search": "engineers"}


def test_api_failure():
    with pytest.raises(ArtifactKeeperError):
        group_info.run_module(FakeModule({"name": None}), RecordingClient([ArtifactKeeperError("boom")]))
