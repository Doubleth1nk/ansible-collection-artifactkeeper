# SPDX-License-Identifier: GPL-3.0-or-later

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    canonical_service_account_username,
    service_account_by_name,
    service_account_create_name,
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
