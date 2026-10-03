#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: project_member
short_description: Manage Artifact Keeper project permission grants
version_added: "0.1.0"
description:
  - Manages a user, service-account, or group permission grant on an Artifact Keeper project.
  - Human-readable project/principal identifiers are resolved to API UUIDs internally.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  project:
    description: Project key.
    type: str
    required: true
  principal_type:
    description: Principal kind supported by the current membership API.
    type: str
    choices: [user, service_account, group]
    required: true
  principal:
    description: Group name, service-account name, user name, or user email.
    type: str
    required: true
  actions:
    description: Complete desired action set for the grant. Required when O(state=present).
    type: list
    elements: str
  state:
    description: Whether the grant should exist.
    type: str
    choices: [present, absent]
    default: present
'''

EXAMPLES = r'''
- name: Grant engineers read and write access to a project
  artifactkeeper.core.project_member:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    project: engineering
    principal_type: group
    principal: engineers
    actions: [read, write]
    state: present
'''

RETURN = r'''
member:
  description: Project membership row, or C(null) when absent.
  returned: always
  type: dict
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    principal_by_identifier,
    project_by_key,
    q,
    safe_diff,
)


def _members(client, project_id):
    response = client.get("/projects/%s/members" % q(project_id))
    if isinstance(response, dict):
        return response.get("items", response.get("members", []))
    return response or []


def run_module(module, client):
    p = module.params
    project = project_by_key(client, p["project"])
    if not project:
        module.fail_json(msg="project '%s' was not found" % p["project"])
    principal = principal_by_identifier(client, p["principal_type"], p["principal"])
    if not principal:
        module.fail_json(msg="%s principal '%s' was not found" % (p["principal_type"], p["principal"]))
    principal_id = principal["id"]
    current = None
    for member in _members(client, project["id"]):
        if member.get("principal_type") == p["principal_type"] and member.get("principal_id") == principal_id:
            current = member
            break

    endpoint = "/projects/%s/members" % q(project["id"])
    if p["state"] == "absent":
        if not current:
            module.exit_json(changed=False, member=None)
        payload = {"principal_type": p["principal_type"], "principal_id": principal_id}
        result = {"changed": True, "member": current}
        if getattr(module, "_diff", False):
            result["diff"] = {"before": current, "after": {}}
        if module.check_mode:
            module.exit_json(**result)
        client.delete(endpoint, data=payload, expected=(200,))
        result["member"] = None
        module.exit_json(**result)

    desired_actions = sorted(set(p["actions"]))
    if current and sorted(set(current.get("actions") or [])) == desired_actions:
        module.exit_json(changed=False, member=current)
    desired = {
        "principal_type": p["principal_type"],
        "principal_id": principal_id,
        "actions": desired_actions,
    }
    result = {"changed": True, "member": desired}
    if getattr(module, "_diff", False):
        result["diff"] = safe_diff(current or {}, desired)
    if module.check_mode:
        module.exit_json(**result)
    result["member"] = client.post(endpoint, data=desired, expected=(200,))
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "project": {"type": "str", "required": True},
            "principal_type": {"type": "str", "choices": ["user", "service_account", "group"], "required": True},
            "principal": {"type": "str", "required": True},
            "actions": {"type": "list", "elements": "str"},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        },
        required_if=[["state", "present", ["actions"]]],
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
