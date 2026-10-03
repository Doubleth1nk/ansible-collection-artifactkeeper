#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: project
short_description: Manage Artifact Keeper projects
version_added: "0.1.0"
description:
  - Creates, updates, and deletes Artifact Keeper projects by stable project key.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  key:
    description: Stable project key used for lookup.
    type: str
    required: true
  name:
    description: Project display name. Required when O(state=present).
    type: str
  description:
    description: Project description. An omitted value is left unmanaged on existing projects.
    type: str
  quota_bytes:
    description: Optional project quota metadata in bytes. Artifact Keeper 1.10.1 stores this value but does not enforce it.
    type: int
  state:
    description: Desired project lifecycle state.
    type: str
    choices: [present, absent]
    default: present
'''

EXAMPLES = r'''
- name: Create engineering project
  artifactkeeper.core.project:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: engineering
    name: Engineering
    description: Engineering artifacts
    quota_bytes: 107374182400
    state: present

- name: Remove a project
  artifactkeeper.core.project:
    api_url: https://artifacts.example.com
    username: admin
    password: "{{ artifactkeeper_admin_password }}"
    key: obsolete
    state: absent
'''

RETURN = r'''
project:
  description: Project returned by Artifact Keeper, or C(null) after deletion.
  returned: always
  type: dict
changed_fields:
  description: Managed fields that required an update.
  returned: when state=present
  type: list
  elements: str
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    managed_diff,
    project_by_key,
    q,
    safe_diff,
)


def run_module(module, client):
    p = module.params
    existing = project_by_key(client, p["key"])

    if p["state"] == "absent":
        if not existing:
            module.exit_json(changed=False, project=None)
        result = {"changed": True, "project": existing}
        if getattr(module, "_diff", False):
            result["diff"] = {"before": existing, "after": {}}
        if module.check_mode:
            module.exit_json(**result)
        client.delete("/projects/%s" % q(existing["id"]))
        result["project"] = None
        module.exit_json(**result)

    desired = {"name": p["name"]}
    for field in ("description", "quota_bytes"):
        if p.get(field) is not None:
            desired[field] = p[field]

    if not existing:
        payload = {"key": p["key"], **desired}
        if module.check_mode:
            result = {"changed": True, "project": {"key": p["key"], **desired}, "changed_fields": list(desired)}
            if getattr(module, "_diff", False):
                result["diff"] = {"before": {}, "after": result["project"]}
            module.exit_json(**result)
        created = client.post("/projects", data=payload, expected=(200,))
        result = {"changed": True, "project": created, "changed_fields": list(desired)}
        if getattr(module, "_diff", False):
            result["diff"] = {"before": {}, "after": {"key": p["key"], **desired}}
        module.exit_json(**result)

    changed_fields, before, after = managed_diff(existing, desired, desired.keys())
    if not changed_fields:
        module.exit_json(changed=False, project=existing, changed_fields=[])

    result = {"changed": True, "project": existing, "changed_fields": changed_fields}
    if getattr(module, "_diff", False):
        result["diff"] = safe_diff(before, after)
    if module.check_mode:
        result["project"] = {**existing, **desired}
        module.exit_json(**result)

    update = {field: desired[field] for field in changed_fields}
    project = client.put("/projects/%s" % q(existing["id"]), data=update)
    result["project"] = project
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "key": {"type": "str", "required": True, "no_log": False},
            "name": {"type": "str"},
            "description": {"type": "str"},
            "quota_bytes": {"type": "int"},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        },
        required_if=[["state", "present", ["name"]]],
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
