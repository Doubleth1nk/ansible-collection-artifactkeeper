#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: security_policy
short_description: Manage Artifact Keeper security policies
version_added: "0.4.0"
description:
  - Creates, updates, and deletes Artifact Keeper security (scan) policies through C(/security/policies).
  - >-
    A policy is identified by its O(name). Artifact Keeper itself allows several policies with the same name; when more than one
    policy carries the requested name, the module fails as ambiguous and never picks one.
  - >-
    A policy is either global (O(repository) omitted) or scoped to one repository. Artifact Keeper 1.10.2 cannot change the scope
    of an existing policy, so when the named policy exists with a different scope the module fails. Moving a policy between scopes
    requires removing it explicitly (O(state=absent) with its current scope) and creating it again; the module never deletes and
    recreates a policy on its own.
  - Only the settings that are supplied are managed. An omitted setting is neither compared nor sent, and the server keeps its current value.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  name:
    description:
      - Name of the policy. Matched exactly, without trimming or case folding.
      - Must not be empty and must be at most 255 characters long.
    type: str
    required: true
  repository:
    description:
      - Key of the repository the policy is scoped to. When omitted, the policy is global and applies to every repository.
      - The scope is fixed when the policy is created; see the module description.
    type: str
  max_severity:
    description:
      - Lowest unacknowledged finding severity that violates the policy.
      - Required when the policy is created. On an existing policy it is managed only when supplied.
    type: str
    choices: [critical, high, medium, low]
  block_on_fail:
    description:
      - Whether an artifact whose latest scan failed violates the policy on the download gate.
      - Required when the policy is created. On an existing policy it is managed only when supplied.
    type: bool
  block_unscanned:
    description:
      - Whether an artifact without a completed scan violates the policy.
      - When omitted on creation, Artifact Keeper uses its default V(true). On an existing policy it is managed only when supplied.
    type: bool
  require_signature:
    description:
      - Whether promotion requires the artifact to be signed.
      - When omitted on creation, Artifact Keeper uses its default V(false). On an existing policy it is managed only when supplied.
    type: bool
  min_staging_hours:
    description:
      - Minimum artifact age in hours before promotion is allowed.
      - Managed only when supplied. When omitted on creation the policy has no minimum staging time.
      - Artifact Keeper 1.10.2 cannot clear this value once it is set; removing the option leaves the stored value in place.
        To clear it, remove the policy with O(state=absent) and create it again.
    type: int
  max_artifact_age_days:
    description:
      - Maximum artifact age in days for promotion to be allowed.
      - Managed only when supplied. When omitted on creation the policy has no maximum age.
      - Artifact Keeper 1.10.2 cannot clear this value once it is set; removing the option leaves the stored value in place.
        To clear it, remove the policy with O(state=absent) and create it again.
    type: int
  enabled:
    description:
      - Whether the policy is enforced. Managed only when supplied.
      - >-
        Artifact Keeper 1.10.2 always creates policies enabled. With O(enabled=false) on creation, the module creates the policy
        and disables it with a second request, so the new policy is enforced for the short time between the two requests.
    type: bool
  state:
    description: Whether the policy should exist.
    type: str
    choices: [present, absent]
    default: present
notes:
  - >-
    Creating, changing, and deleting policies requires an administrator. An API token must belong to an administrator and carry the
    C(admin) or C(*) scope. Any authenticated user can read policies, so check mode works without administrator rights.
  - >-
    Artifact Keeper applies policies in two places. The download gate applies every enabled global policy and every enabled policy of
    the repository, and any violation blocks; it uses O(block_unscanned), O(block_on_fail), and O(max_severity). The promotion gate uses
    a single enabled policy, preferring one scoped to the repository over global ones, and uses O(block_unscanned), O(max_severity),
    O(require_signature), O(min_staging_hours), and O(max_artifact_age_days).
  - Deleting a repository deletes the policies scoped to it.
  - Setting an option to V(null) is the same as omitting it, which leaves that setting unmanaged.
'''

EXAMPLES = r'''
- name: Block critical findings and failed scans on every repository
  artifactkeeper.core.security_policy:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: baseline
    max_severity: critical
    block_on_fail: true

- name: Gate promotion out of a staging repository
  artifactkeeper.core.security_policy:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: pypi-staging-promotion
    repository: pypi-staging
    max_severity: high
    block_on_fail: true
    require_signature: true
    min_staging_hours: 24

- name: Temporarily disable a policy without changing its settings
  artifactkeeper.core.security_policy:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: pypi-staging-promotion
    repository: pypi-staging
    enabled: false

- name: Remove a repository-scoped policy
  artifactkeeper.core.security_policy:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: pypi-staging-promotion
    repository: pypi-staging
    state: absent
'''

RETURN = r'''
policy:
  description:
    - The policy as returned by Artifact Keeper. In check mode this is the predicted policy.
    - V(null) when the policy does not exist after the task.
  returned: always
  type: dict
  contains:
    id:
      description: Policy UUID. Missing from a check-mode prediction of a new policy.
      type: str
      returned: when the policy exists
    name:
      description: Policy name.
      type: str
      returned: when the policy exists
    repository_id:
      description: UUID of the repository the policy is scoped to, or V(null) for a global policy.
      type: str
      returned: when the policy exists
    max_severity:
      description: Severity threshold, in lowercase.
      type: str
      returned: when the policy exists
    block_on_fail:
      description: Whether failed scans violate the policy.
      type: bool
      returned: when the policy exists
    block_unscanned:
      description: Whether unscanned artifacts violate the policy.
      type: bool
      returned: when the policy exists
    require_signature:
      description: Whether promotion requires a signature.
      type: bool
      returned: when the policy exists
    min_staging_hours:
      description: Minimum staging time in hours, or V(null).
      type: int
      returned: when the policy exists
    max_artifact_age_days:
      description: Maximum artifact age in days, or V(null).
      type: int
      returned: when the policy exists
    is_enabled:
      description: Whether the policy is enforced.
      type: bool
      returned: when the policy exists
changed_fields:
  description: Sorted names of the options that were set or differed from the server state, or V([policy]) when the policy is deleted.
  returned: always
  type: list
  elements: str
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    managed_diff,
    q,
    repository_by_key,
)

# Module option -> PolicyResponse / UpdatePolicyRequest field.
API_FIELDS = {
    "block_on_fail": "block_on_fail",
    "block_unscanned": "block_unscanned",
    "enabled": "is_enabled",
    "max_artifact_age_days": "max_artifact_age_days",
    "max_severity": "max_severity",
    "min_staging_hours": "min_staging_hours",
    "require_signature": "require_signature",
}
SETTINGS = sorted(API_FIELDS)
INTEGER_SETTINGS = ("max_artifact_age_days", "min_staging_hours")
CREATE_REQUIRED = ("block_on_fail", "max_severity")
# Values Artifact Keeper 1.10.2 stores for options a create request omits.
CREATE_DEFAULTS = {
    "block_unscanned": True,
    "require_signature": False,
    "is_enabled": True,
    "min_staging_hours": None,
    "max_artifact_age_days": None,
}
NAME_MAX_LENGTH = 255
INT32_MIN = -(2 ** 31)
INT32_MAX = 2 ** 31 - 1
POLICIES = "/security/policies"


def _validate(module, p, desired):
    if p["name"] == "":
        module.fail_json(msg="name must not be empty")
    if len(p["name"]) > NAME_MAX_LENGTH:
        module.fail_json(msg="name must be at most %d characters long" % NAME_MAX_LENGTH)
    for option in INTEGER_SETTINGS:
        value = desired.get(option)
        if value is not None and not INT32_MIN <= value <= INT32_MAX:
            module.fail_json(msg="%s must be between %d and %d" % (option, INT32_MIN, INT32_MAX))


def _current(policy):
    return {option: policy.get(field) for option, field in API_FIELDS.items()}


def _scope_label(repository_id, repository_key=None):
    if repository_id is None:
        return "global"
    if repository_key is not None:
        return "repository '%s'" % repository_key
    return "repository ID %s" % repository_id


def _desired_repository_id(module, client, key):
    if key is None:
        return None
    repository = repository_by_key(client, key)
    if not repository:
        module.fail_json(msg="repository '%s' was not found or is not visible to the current credential" % key)
    return repository["id"]


def _find(module, client, name):
    policies = client.get(POLICIES)
    matches = [policy for policy in policies or [] if isinstance(policy, dict) and policy.get("name") == name]
    if len(matches) > 1:
        module.fail_json(
            msg="security policy name '%s' is ambiguous: %d policies carry it (IDs %s); rename or remove the duplicates "
            "so that exactly one remains" % (name, len(matches), ", ".join(sorted(str(policy.get("id")) for policy in matches)))
        )
    return matches[0] if matches else None


def _check_scope(module, p, existing, repository_id):
    if existing.get("repository_id") == repository_id:
        return
    existing_scope = _scope_label(existing.get("repository_id"))
    requested_scope = _scope_label(repository_id, p.get("repository"))
    if p["state"] == "absent":
        action = "Set repository to the policy's current scope to remove it."
    else:
        action = (
            "Remove the existing policy explicitly (state: absent with its current scope) and create it again with the new scope."
        )
    module.fail_json(
        msg="security policy '%s' exists as a %s policy, but %s was requested. Artifact Keeper 1.10.2 cannot change the "
        "scope of a policy after creation. %s" % (p["name"], existing_scope, requested_scope, action)
    )


def _identity(p):
    return {"name": p["name"], "repository": p.get("repository")}


def _create(module, client, p, desired):
    missing = [option for option in CREATE_REQUIRED if option not in desired]
    if missing:
        module.fail_json(
            msg="security policy '%s' does not exist and cannot be created without %s; Artifact Keeper requires "
            "max_severity and block_on_fail when a policy is created" % (p["name"], " and ".join(missing))
        )
    repository_id = _desired_repository_id(module, client, p.get("repository"))

    payload = {"name": p["name"], "repository_id": repository_id}
    payload.update({API_FIELDS[option]: value for option, value in desired.items() if option != "enabled"})
    predicted = dict(CREATE_DEFAULTS, **payload)
    if "enabled" in desired:
        predicted["is_enabled"] = desired["enabled"]

    changed_fields = sorted(["name"] + (["repository"] if p.get("repository") is not None else []) + list(desired))
    result = {"changed": True, "policy": predicted, "changed_fields": changed_fields}
    if getattr(module, "_diff", False):
        result["diff"] = {"before": {}, "after": dict(_identity(p), **desired)}
    if module.check_mode:
        module.exit_json(**result)

    policy = client.post(POLICIES, data=payload, expected=(200,))
    result["policy"] = policy
    if desired.get("enabled") is False:
        # 1.10.2 ignores is_enabled on create, so a disabled policy needs a follow-up update.
        policy_id = policy.get("id") if isinstance(policy, dict) else None
        try:
            result["policy"] = client.put("%s/%s" % (POLICIES, q(policy_id)), data={"is_enabled": False}, expected=(200,))
        except ArtifactKeeperError as error:
            # The policy now exists, so the task changed the server; it is deliberately not deleted again.
            module.fail_json(
                msg="security policy '%s' was created with ID %s, but disabling it failed (%s). The policy exists and remains "
                "enabled; disable it with enabled: false or remove it." % (p["name"], policy_id, error),
                changed=True,
                policy=policy,
                policy_id=policy_id,
                changed_fields=changed_fields,
            )
    module.exit_json(**result)


def _delete(module, client, p, existing):
    if existing is None:
        module.exit_json(changed=False, policy=None, changed_fields=[])
    _check_scope(module, p, existing, _desired_repository_id(module, client, p.get("repository")))

    result = {"changed": True, "policy": existing, "changed_fields": ["policy"]}
    if getattr(module, "_diff", False):
        result["diff"] = {"before": dict(_identity(p), **_current(existing)), "after": {}}
    if module.check_mode:
        module.exit_json(**result)
    client.delete("%s/%s" % (POLICIES, q(existing["id"])), expected=(200,))
    result["policy"] = None
    module.exit_json(**result)


def run_module(module, client):
    p = module.params
    desired = {option: p[option] for option in SETTINGS if p.get(option) is not None}
    _validate(module, p, desired)

    existing = _find(module, client, p["name"])
    if p["state"] == "absent":
        _delete(module, client, p, existing)

    if existing is None:
        _create(module, client, p, desired)
    _check_scope(module, p, existing, _desired_repository_id(module, client, p.get("repository")))

    changed_fields, before, after = managed_diff(_current(existing), desired, SETTINGS)
    if not changed_fields:
        module.exit_json(changed=False, policy=existing, changed_fields=[])

    # The server merges the request over the stored policy and bumps updated_at on every PUT, so only differences are sent.
    payload = {API_FIELDS[option]: desired[option] for option in changed_fields}
    result = {"changed": True, "policy": dict(existing, **payload), "changed_fields": changed_fields}
    if getattr(module, "_diff", False):
        result["diff"] = {"before": dict(_identity(p), **before), "after": dict(_identity(p), **after)}
    if module.check_mode:
        module.exit_json(**result)
    result["policy"] = client.put("%s/%s" % (POLICIES, q(existing["id"])), data=payload, expected=(200,))
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "name": {"type": "str", "required": True},
            "repository": {"type": "str", "no_log": False},
            "max_severity": {"type": "str", "choices": ["critical", "high", "medium", "low"]},
            "block_on_fail": {"type": "bool"},
            "block_unscanned": {"type": "bool"},
            "require_signature": {"type": "bool"},
            "min_staging_hours": {"type": "int"},
            "max_artifact_age_days": {"type": "int"},
            "enabled": {"type": "bool"},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        }
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
