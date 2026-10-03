#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: service_account
short_description: Manage Artifact Keeper service accounts
version_added: "0.1.0"
description:
  - Creates, updates, and deletes service accounts.
  - Artifact Keeper prefixes created service-account usernames with C(svc-).
  - The create API calls the optional display text C(description), while the response/update API calls it C(display_name).
  - This module presents that field consistently as O(description).
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  name:
    description: Service-account name, with or without the server-added C(svc-) prefix.
    type: str
    required: true
  description:
    description: Human-readable service-account display text.
    type: str
  is_active:
    description: Whether the account is active. Managed on existing accounts when specified.
    type: bool
  state:
    description: Desired service-account lifecycle state.
    type: str
    choices: [present, absent]
    default: present
'''

EXAMPLES = r'''
- name: Create CI service account
  artifactkeeper.core.service_account:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: ci
    description: Continuous integration
    is_active: true
    state: present
'''

RETURN = r'''
service_account:
  description: Current service-account representation, or C(null) after deletion.
  returned: always
  type: dict
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    canonical_service_account_username,
    make_module,
    q,
    safe_diff,
    service_account_by_name,
    service_account_create_name,
)


def run_module(module, client):
    p = module.params
    existing = service_account_by_name(client, p["name"])
    if p["state"] == "absent":
        if not existing:
            module.exit_json(changed=False, service_account=None)
        result = {"changed": True, "service_account": existing}
        if getattr(module, "_diff", False):
            result["diff"] = {"before": existing, "after": {}}
        if module.check_mode:
            module.exit_json(**result)
        client.delete("/service-accounts/%s" % q(existing["id"]))
        result["service_account"] = None
        module.exit_json(**result)

    if not existing:
        payload = {"name": service_account_create_name(p["name"])}
        if p.get("description") is not None:
            payload["description"] = p["description"]
        if module.check_mode:
            preview = {"username": canonical_service_account_username(p["name"]), "display_name": p.get("description"), "is_active": True}
            if p.get("is_active") is not None:
                preview["is_active"] = p["is_active"]
            result = {"changed": True, "service_account": preview}
            if getattr(module, "_diff", False):
                result["diff"] = {"before": {}, "after": preview}
            module.exit_json(**result)
        account = client.post("/service-accounts", data=payload, expected=(201,))
        if p.get("is_active") is False:
            account = client.patch("/service-accounts/%s" % q(account["id"]), data={"is_active": False})
        result = {"changed": True, "service_account": account}
        if getattr(module, "_diff", False):
            preview = {"username": canonical_service_account_username(p["name"]), "display_name": p.get("description"), "is_active": True}
            if p.get("is_active") is not None:
                preview["is_active"] = p["is_active"]
            result["diff"] = {"before": {}, "after": preview}
        module.exit_json(**result)

    desired = {}
    if p.get("description") is not None:
        desired["display_name"] = p["description"]
    if p.get("is_active") is not None:
        desired["is_active"] = p["is_active"]
    changed = {field: value for field, value in desired.items() if existing.get(field) != value}
    if not changed:
        module.exit_json(changed=False, service_account=existing)
    result = {"changed": True, "service_account": {**existing, **changed}}
    if getattr(module, "_diff", False):
        result["diff"] = safe_diff(
            {field: existing.get(field) for field in changed},
            changed,
        )
    if module.check_mode:
        module.exit_json(**result)
    result["service_account"] = client.patch("/service-accounts/%s" % q(existing["id"]), data=changed)
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "name": {"type": "str", "required": True},
            "description": {"type": "str"},
            "is_active": {"type": "bool"},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        }
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
