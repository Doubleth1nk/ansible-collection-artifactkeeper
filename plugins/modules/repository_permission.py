#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: repository_permission
short_description: Manage Artifact Keeper repository permission grants
version_added: "0.2.0"
description:
  - Manages a fine-grained permission grant for a user, service account, or group on one Artifact Keeper repository.
  - The grant is identified by the repository, the principal type, and the principal. Human-readable identifiers are resolved to API UUIDs internally.
  - Grants on projects are managed by M(artifactkeeper.core.project_member), not by this module.
  - Role assignments made through the user roles API do not grant repository access.
  - Repository access is granted by permission rows such as the ones managed here.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  repository:
    description: Repository key.
    type: str
    required: true
  principal_type:
    description: Kind of principal that receives the grant.
    type: str
    choices: [user, service_account, group]
    required: true
  principal:
    description:
      - Group name, service-account name (with or without the C(svc-) prefix), user name, or user email.
    type: str
    required: true
  actions:
    description:
      - Complete desired action set for the grant, for example C([read, write]).
      - Compared as a set, so order and duplicates do not matter.
      - Action names are not validated by this module because the Artifact Keeper API does not publish an enumeration.
      - Required and must not be empty when O(state=present).
    type: list
    elements: str
  state:
    description: Whether the grant should exist.
    type: str
    choices: [present, absent]
    default: present
notes:
  - If more than one permission row matches the repository and principal, the module fails instead of choosing one.
'''

EXAMPLES = r'''
- name: Grant engineers read and write access to a repository
  artifactkeeper.core.repository_permission:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: python-local
    principal_type: group
    principal: engineers
    actions: [read, write]

- name: Grant the CI service account read access
  artifactkeeper.core.repository_permission:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: pypi-remote
    principal_type: service_account
    principal: ci
    actions: [read]

- name: Remove a user's direct grant
  artifactkeeper.core.repository_permission:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: python-local
    principal_type: user
    principal: alice
    state: absent
'''

RETURN = r'''
permission:
  description:
    - Permission row after the change, or C(null) when the grant is absent.
    - In check mode this is the predicted row.
  returned: always
  type: dict
  contains:
    id:
      description: Permission UUID.
      type: str
      returned: when the grant exists on the server
    principal_type:
      description: Principal kind.
      type: str
      returned: always
    principal_id:
      description: Principal UUID.
      type: str
      returned: always
    target_type:
      description: Always C(repository) for this module.
      type: str
      returned: always
    target_id:
      description: Repository UUID.
      type: str
      returned: always
    actions:
      description: Granted actions.
      type: list
      elements: str
      returned: always
changed_fields:
  description: Managed fields that differed from the server state.
  returned: always
  type: list
  elements: str
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    group_by_name,
    make_module,
    q,
    repository_by_key,
    safe_diff,
    service_account_by_name,
)

TARGET_TYPE = "repository"


def _user_by_identifier(client, identifier):
    # Filter service accounts client-side instead of sending a boolean query
    # parameter: the API does not document how booleans are serialized.
    items = client.paginate("/users", params={"search": identifier})
    matches = [
        item
        for item in items
        if not item.get("is_service_account")
        and (item.get("username") == identifier or item.get("email") == identifier)
    ]
    if len(matches) > 1:
        raise ArtifactKeeperError("user identifier '%s' is ambiguous" % identifier)
    return matches[0] if matches else None


def _principal(client, principal_type, identifier):
    if principal_type == "group":
        return group_by_name(client, identifier)
    if principal_type == "service_account":
        return service_account_by_name(client, identifier)
    return _user_by_identifier(client, identifier)


def _existing_permission(client, identity):
    rows = client.paginate("/permissions", params=identity)
    matches = [
        row
        for row in rows
        if all(row.get(field) == value for field, value in identity.items())
    ]
    if len(matches) > 1:
        raise ArtifactKeeperError(
            "multiple permission rows match %s '%s' on repository target '%s'"
            % (identity["principal_type"], identity["principal_id"], identity["target_id"])
        )
    return matches[0] if matches else None


def _diff_view(p, actions):
    return {
        "repository": p["repository"],
        "principal_type": p["principal_type"],
        "principal": p["principal"],
        "actions": actions,
    }


def run_module(module, client):
    p = module.params
    repository = repository_by_key(client, p["repository"])
    if not repository:
        module.fail_json(msg="repository '%s' was not found" % p["repository"])
    principal = _principal(client, p["principal_type"], p["principal"])
    if not principal:
        module.fail_json(msg="%s principal '%s' was not found" % (p["principal_type"], p["principal"]))

    identity = {
        "principal_type": p["principal_type"],
        "principal_id": principal["id"],
        "target_type": TARGET_TYPE,
        "target_id": repository["id"],
    }
    existing = _existing_permission(client, identity)
    current_actions = sorted(set(existing.get("actions") or [])) if existing else None

    if p["state"] == "absent":
        if not existing:
            module.exit_json(changed=False, permission=None, changed_fields=[])
        result = {"changed": True, "permission": existing, "changed_fields": ["actions"]}
        if getattr(module, "_diff", False):
            result["diff"] = safe_diff(_diff_view(p, current_actions), {})
        if module.check_mode:
            module.exit_json(**result)
        client.delete("/permissions/%s" % q(existing["id"]), expected=(200,))
        result["permission"] = None
        module.exit_json(**result)

    desired_actions = sorted(set(p["actions"] or []))
    if not desired_actions:
        module.fail_json(msg="actions must contain at least one action when state=present; use state=absent to remove the grant")

    if existing and current_actions == desired_actions:
        module.exit_json(changed=False, permission=existing, changed_fields=[])

    # PUT /permissions/{id} takes the same full CreatePermissionRequest as POST.
    payload = dict(identity, actions=desired_actions)
    result = {"changed": True, "changed_fields": ["actions"]}
    if getattr(module, "_diff", False):
        before = _diff_view(p, current_actions) if existing else {}
        result["diff"] = safe_diff(before, _diff_view(p, desired_actions))
    if module.check_mode:
        result["permission"] = {**existing, "actions": desired_actions} if existing else payload
        module.exit_json(**result)

    if existing:
        result["permission"] = client.put("/permissions/%s" % q(existing["id"]), data=payload, expected=(200,))
    else:
        result["permission"] = client.post("/permissions", data=payload, expected=(200,))
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "repository": {"type": "str", "required": True, "no_log": False},
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
