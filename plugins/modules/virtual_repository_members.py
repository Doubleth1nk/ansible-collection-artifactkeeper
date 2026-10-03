#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: virtual_repository_members
short_description: Manage the complete member set of an Artifact Keeper virtual repository
version_added: "0.1.0"
description:
  - Treats O(members) as the complete desired virtual-repository member set.
  - Uses the current API's PUT replace semantics, so missing, removed, and reprioritized members converge idempotently.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  repository:
    description: Virtual repository key.
    type: str
    required: true
  members:
    description: Complete desired member set.
    type: list
    required: true
    elements: dict
    suboptions:
      key:
        description: Member repository key.
        type: str
        required: true
      priority:
        description: Search priority; lower values are searched first.
        type: int
        required: true
'''

EXAMPLES = r'''
- name: Configure Python virtual repository members
  artifactkeeper.core.virtual_repository_members:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: python
    members:
      - key: python-local
        priority: 10
      - key: pypi-remote
        priority: 20
'''

RETURN = r'''
members:
  description: Normalized current member list.
  returned: always
  type: list
  elements: dict
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    q,
    repository_by_key,
    safe_diff,
)


def _normalize_current(items):
    normalized = []
    for item in items:
        normalized.append({
            "key": item.get("member_repo_key") or item.get("member_key") or item.get("key"),
            "priority": item.get("priority"),
        })
    return sorted(normalized, key=lambda x: (x["priority"], x["key"]))


def _normalize_desired(items):
    return sorted(
        [{"key": item["key"], "priority": item["priority"]} for item in items],
        key=lambda x: (x["priority"], x["key"]),
    )


def run_module(module, client):
    p = module.params
    repository = repository_by_key(client, p["repository"])
    if not repository:
        module.fail_json(msg="repository '%s' was not found" % p["repository"])
    if repository.get("repo_type") != "virtual":
        module.fail_json(msg="repository '%s' is not virtual" % p["repository"])
    keys = [item["key"] for item in p["members"]]
    if len(keys) != len(set(keys)):
        module.fail_json(msg="members contains duplicate repository keys")
    response = client.get("/repositories/%s/members" % q(p["repository"]))
    current_items = response.get("members", response.get("items", [])) if isinstance(response, dict) else response or []
    current = _normalize_current(current_items)
    desired = _normalize_desired(p["members"])
    if current == desired:
        module.exit_json(changed=False, members=current)
    result = {"changed": True, "members": desired}
    if getattr(module, "_diff", False):
        result["diff"] = safe_diff(current, desired)
    if module.check_mode:
        module.exit_json(**result)
    payload = {"members": [{"member_key": item["key"], "priority": item["priority"]} for item in desired]}
    client.put("/repositories/%s/members" % q(p["repository"]), data=payload)
    result["members"] = desired
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "repository": {"type": "str", "required": True},
            "members": {
                "type": "list",
                "elements": "dict",
                "required": True,
                "options": {
                    "key": {"type": "str", "required": True, "no_log": False},
                    "priority": {"type": "int", "required": True},
                },
            },
        }
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
