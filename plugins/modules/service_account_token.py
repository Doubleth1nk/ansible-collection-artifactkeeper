#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: service_account_token
short_description: Manage Artifact Keeper service-account tokens
version_added: "0.1.0"
description:
  - Creates or revokes named service-account tokens separately from service-account lifecycle.
  - Plaintext token material is returned only by Artifact Keeper at creation and is therefore returned by this module only on creation.
  - Existing token scopes are idempotently compared.
  - The current list API does not return the creation-time description, so description is not used to force rotation.
  - O(expires_in_days) is used when creating a token.
  - The list API returns only an absolute C(expires_at), so the original relative duration cannot always be reconstructed after policy shaping.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  service_account:
    description: Service-account name or server-prefixed username.
    type: str
    required: true
  name:
    description: Token name used as the stable metadata identifier.
    type: str
    required: true
  description:
    description: Optional token description used at creation time.
    type: str
  scopes:
    description: Token scopes. Required when O(state=present).
    type: list
    elements: str
  expires_in_days:
    description: Optional relative token lifetime at creation time.
    type: int
  state:
    description: Whether the named token metadata should exist.
    type: str
    choices: [present, absent]
    default: present
'''

EXAMPLES = r'''
- name: Create a service-account token
  artifactkeeper.core.service_account_token:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_admin_token }}"
    service_account: ci
    name: automation
    description: CI automation token
    scopes: [read, write]
    expires_in_days: 90
    state: present
  no_log: true
  register: ci_token

- name: Remove a token by name
  artifactkeeper.core.service_account_token:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_admin_token }}"
    service_account: ci
    name: automation
    state: absent
'''

RETURN = r'''
token_info:
  description: Token metadata. Secret material is never included here.
  returned: always
  type: dict
token:
  description: Newly generated plaintext token. This is sensitive and is only returned on creation.
  returned: only when Artifact Keeper creates a token
  type: str
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    q,
    service_account_by_name,
)


def _list_tokens(client, account_id):
    response = client.get("/service-accounts/%s/tokens" % q(account_id))
    return response.get("items", []) if isinstance(response, dict) else []


def run_module(module, client):
    p = module.params
    account = service_account_by_name(client, p["service_account"])
    if not account:
        module.fail_json(msg="service account '%s' was not found" % p["service_account"])
    named = [item for item in _list_tokens(client, account["id"]) if item.get("name") == p["name"]]

    if p["state"] == "absent":
        if not named:
            module.exit_json(changed=False, token_info=None)
        result = {"changed": True, "token_info": named[0] if len(named) == 1 else {"matches": len(named)}}
        if getattr(module, "_diff", False):
            result["diff"] = {"before": result["token_info"], "after": {}}
        if module.check_mode:
            module.exit_json(**result)
        for token_info in named:
            client.delete("/service-accounts/%s/tokens/%s" % (q(account["id"]), q(token_info["id"])))
        result["token_info"] = None
        module.exit_json(**result)

    matches = [item for item in named if not item.get("is_expired", False)]
    if len(matches) > 1:
        raise ArtifactKeeperError("multiple live tokens named '%s' exist for the service account" % p["name"])
    existing = matches[0] if matches else None

    desired_scopes = sorted(set(p["scopes"]))
    if existing:
        current_scopes = sorted(set(existing.get("scopes") or []))
        if current_scopes == desired_scopes:
            module.exit_json(changed=False, token_info=existing)
        # Token scopes are immutable in the current API. Revoke and recreate to converge.
        if module.check_mode:
            result = {"changed": True, "token_info": {**existing, "scopes": desired_scopes}}
            if getattr(module, "_diff", False):
                result["diff"] = {
                    "before": {"name": p["name"], "scopes": current_scopes},
                    "after": {"name": p["name"], "scopes": desired_scopes},
                }
            module.exit_json(**result)
        client.delete("/service-accounts/%s/tokens/%s" % (q(account["id"]), q(existing["id"])))

    payload = {"name": p["name"], "scopes": desired_scopes}
    if p.get("description") is not None:
        payload["description"] = p["description"]
    if p.get("expires_in_days") is not None:
        payload["expires_in_days"] = p["expires_in_days"]
    preview = {"name": p["name"], "scopes": desired_scopes}
    if module.check_mode:
        result = {"changed": True, "token_info": preview}
        if getattr(module, "_diff", False):
            result["diff"] = {
                "before": {"name": p["name"], "scopes": current_scopes} if existing else {},
                "after": preview,
            }
        module.exit_json(**result)
    created = client.post("/service-accounts/%s/tokens" % q(account["id"]), data=payload, expected=(200,))
    secret = created.get("token")
    token_info = {key: value for key, value in created.items() if key != "token"}
    result = {"changed": True, "token_info": token_info, "token": secret}
    if getattr(module, "_diff", False):
        result["diff"] = {
            "before": {"name": p["name"], "scopes": current_scopes} if existing else {},
            "after": preview,
        }
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "service_account": {"type": "str", "required": True},
            "name": {"type": "str", "required": True},
            "description": {"type": "str"},
            "scopes": {"type": "list", "elements": "str"},
            "expires_in_days": {"type": "int"},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        },
        required_if=[["state", "present", ["scopes"]]],
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
