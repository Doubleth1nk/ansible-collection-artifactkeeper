#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: repository
short_description: Manage Artifact Keeper repositories
version_added: "0.1.0"
description:
  - Manages general local, remote, virtual, and staging repository properties.
  - Remote-repository age-gate policy can be managed as nested repository configuration with O(age_gate).
  - Project keys are resolved to Artifact Keeper UUIDs internally.
  - Write-only upstream credentials are not re-sent on every run; use O(force_upstream_auth_update=true) for intentional rotation.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  key:
    description: Repository key and stable lookup identifier.
    type: str
    required: true
  name:
    description: Repository display name. Required for creation.
    type: str
  description:
    description: Repository description.
    type: str
  format:
    description: Artifact format understood by Artifact Keeper, for example C(pypi), C(npm), or C(maven).
    type: str
  repo_type:
    description: Repository type. The current API supports C(local), C(remote), C(virtual), and C(staging).
    type: str
    choices: [local, remote, virtual, staging]
  upstream_url:
    description:
      - Upstream URL for remote repositories.
      - Artifact Keeper 1.10.1 does not expose this field in the general repository PATCH schema.
      - Changing an existing upstream URL therefore fails rather than silently recreating the repository.
    type: str
  upstream_auth_type:
    description: Upstream authentication type managed through the upstream-auth API.
    type: str
    choices: [basic, bearer, aws_ecr, aws_codeartifact, none]
  upstream_username:
    description: Username for basic upstream authentication.
    type: str
  upstream_password:
    description: Password for basic auth or token for bearer auth. This value is write-only in Artifact Keeper.
    type: str
  upstream_aws:
    description:
      - Non-secret AWS provider settings for C(aws_ecr) or C(aws_codeartifact) authentication.
      - Artifact Keeper obtains AWS credentials server-side; this collection does not accept or store AWS secret keys.
    type: dict
    suboptions:
      region:
        description: AWS region.
        type: str
      registry_id:
        description: Optional AWS ECR registry/account ID.
        type: str
      domain:
        description: AWS CodeArtifact domain.
        type: str
      domain_owner:
        description: Optional AWS CodeArtifact domain owner/account ID.
        type: str
      duration_seconds:
        description: Requested CodeArtifact authorization-token lifetime.
        type: int
  force_upstream_auth_update:
    description: Re-send write-only upstream credentials even when the visible auth type is already configured.
    type: bool
    default: false
  project_key:
    aliases: [project]
    description: Project key to assign. The collection resolves it to the API project UUID.
    type: str
  is_public:
    description: Whether the repository permits public access according to Artifact Keeper policy.
    type: bool
  quota_bytes:
    description: Optional repository quota in bytes.
    type: int
  age_gate:
    description:
      - Desired age-gate configuration for this repository.
      - Omit this option to leave the repository's existing age-gate configuration unmanaged.
      - Set C(enabled=false) explicitly to disable a managed age gate.
      - The age-gate API applies only to remote repositories.
      - When enabling it, Artifact Keeper validates whether the repository format supports the selected mode.
      - Reading and changing age-gate policy currently requires Artifact Keeper administrator privileges.
    type: dict
    suboptions:
      enabled:
        description: Whether the age gate is enabled.
        type: bool
        required: true
      min_age_days:
        description: Minimum package age in days, from 0 through 3650.
        type: int
        required: true
      mode:
        description:
          - Age source used by the gate.
          - When omitted for an existing repository, the current mode is preserved.
          - Go repositories currently support only C(first_seen).
        type: str
        choices: [upstream_publish_time, first_seen]
  state:
    description: Desired repository lifecycle state.
    type: str
    choices: [present, absent]
    default: present
'''

EXAMPLES = r'''
- name: Create a local PyPI repository
  artifactkeeper.core.repository:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: python-local
    name: Python Local
    format: pypi
    repo_type: local
    project_key: engineering
    is_public: false

- name: Create a remote PyPI cache with an age gate
  artifactkeeper.core.repository:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: pypi-remote
    name: PyPI Remote
    format: pypi
    repo_type: remote
    upstream_url: https://pypi.org
    upstream_auth_type: none
    age_gate:
      enabled: true
      min_age_days: 7
      mode: upstream_publish_time

- name: Configure an AWS CodeArtifact remote repository
  artifactkeeper.core.repository:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: codeartifact-remote
    name: CodeArtifact Remote
    format: npm
    repo_type: remote
    upstream_url: https://example.d.codeartifact.eu-west-1.amazonaws.com/npm/example/
    upstream_auth_type: aws_codeartifact
    upstream_aws:
      region: eu-west-1
      domain: example
'''

RETURN = r'''
repository:
  description:
    - Current repository representation, or C(null) after deletion.
    - When O(age_gate) is managed, the result includes the effective configuration under C(repository.age_gate).
  returned: always
  type: dict
changed_fields:
  description: Visible repository fields that required change.
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
    repository_by_key,
    safe_diff,
)


def _clean_dict(value):
    return {key: item for key, item in (value or {}).items() if item is not None}


def _upstream_auth_payload(module, params):
    auth_type = params.get("upstream_auth_type")
    username = params.get("upstream_username")
    password = params.get("upstream_password")
    aws = _clean_dict(params.get("upstream_aws"))
    if auth_type is None:
        if username is not None or password is not None or aws:
            module.fail_json(msg="upstream_auth_type is required when upstream authentication settings are supplied")
        return None

    payload = {"auth_type": auth_type}
    if auth_type == "basic":
        if username is None or password is None:
            module.fail_json(msg="basic upstream authentication requires upstream_username and upstream_password")
        if aws:
            module.fail_json(msg="upstream_aws is only valid with aws_ecr or aws_codeartifact")
        payload.update({"username": username, "password": password})
    elif auth_type == "bearer":
        if password is None:
            module.fail_json(msg="bearer upstream authentication requires upstream_password containing the bearer token")
        if username is not None or aws:
            module.fail_json(msg="upstream_username/upstream_aws are not valid with bearer authentication")
        payload["password"] = password
    elif auth_type in ("aws_ecr", "aws_codeartifact"):
        if username is not None or password is not None:
            module.fail_json(msg="AWS upstream authentication does not use upstream_username or upstream_password")
        if not aws.get("region"):
            module.fail_json(msg="AWS upstream authentication requires upstream_aws.region")
        if auth_type == "aws_codeartifact" and not aws.get("domain"):
            module.fail_json(msg="aws_codeartifact authentication requires upstream_aws.domain")
        if auth_type == "aws_ecr" and any(aws.get(key) is not None for key in ("domain", "domain_owner", "duration_seconds")):
            module.fail_json(msg="CodeArtifact-only upstream_aws fields are not valid with aws_ecr")
        if auth_type == "aws_codeartifact" and aws.get("registry_id") is not None:
            module.fail_json(msg="upstream_aws.registry_id is only valid with aws_ecr")
        duration = aws.get("duration_seconds")
        if duration is not None and duration != 0 and not 900 <= duration <= 43200:
            module.fail_json(msg="upstream_aws.duration_seconds must be 0 or between 900 and 43200")
        payload["aws"] = aws
    else:  # none
        if username is not None or password is not None or aws:
            module.fail_json(msg="upstream authentication credentials/settings are not valid with upstream_auth_type=none")
    return payload


def _age_gate_payload(module, params):
    raw = params.get("age_gate")
    if raw is None:
        return None
    if raw.get("enabled") is None:
        module.fail_json(msg="age_gate.enabled is required when age_gate is supplied")
    if raw.get("min_age_days") is None:
        module.fail_json(msg="age_gate.min_age_days is required when age_gate is supplied")
    if raw["min_age_days"] < 0 or raw["min_age_days"] > 3650:
        module.fail_json(msg="age_gate.min_age_days must be between 0 and 3650")
    desired = {"enabled": raw["enabled"], "min_age_days": raw["min_age_days"]}
    if raw.get("mode") is not None:
        desired["mode"] = raw["mode"]
    return desired


def _age_gate_differs(current, desired):
    return any(current.get(field) != value for field, value in desired.items())


def _repository_with_age_gate(repository, age_gate):
    if repository is None or age_gate is None:
        return repository
    result = dict(repository)
    result["age_gate"] = age_gate
    return result


def run_module(module, client):
    p = module.params
    existing = repository_by_key(client, p["key"])

    if p["state"] == "absent":
        if not existing:
            module.exit_json(changed=False, repository=None)
        result = {"changed": True, "repository": existing}
        if getattr(module, "_diff", False):
            result["diff"] = {"before": existing, "after": {}}
        if module.check_mode:
            module.exit_json(**result)
        client.delete("/repositories/%s" % q(p["key"]))
        result["repository"] = None
        module.exit_json(**result)

    age_gate_base = _age_gate_payload(module, p)
    if age_gate_base is not None and p["repo_type"] != "remote":
        module.fail_json(msg="age_gate is only valid for repo_type=remote")

    project_id = None
    if p.get("project_key") is not None:
        project = project_by_key(client, p["project_key"])
        if not project:
            module.fail_json(msg="project '%s' was not found" % p["project_key"])
        project_id = project["id"]

    if p["repo_type"] != "remote" and (
        any(p.get(name) is not None for name in ("upstream_url", "upstream_auth_type", "upstream_username", "upstream_password"))
        or _clean_dict(p.get("upstream_aws"))
    ):
        module.fail_json(msg="upstream_* parameters are only valid for repo_type=remote")

    desired = {"name": p["name"]}
    for field in ("description", "is_public", "quota_bytes"):
        if p.get(field) is not None:
            desired[field] = p[field]
    if project_id is not None:
        desired["project_id"] = project_id

    auth_payload = _upstream_auth_payload(module, p)

    if not existing:
        payload = {
            "key": p["key"],
            "name": p["name"],
            "format": p["format"],
            "repo_type": p["repo_type"],
        }
        payload.update({field: value for field, value in desired.items() if value is not None})
        if p.get("upstream_url") is not None:
            payload["upstream_url"] = p["upstream_url"]
        # Basic/bearer credentials are accepted by the create schema. AWS provider
        # settings are configured through the dedicated upstream-auth endpoint.
        needs_auth_put = bool(auth_payload and auth_payload["auth_type"] in ("aws_ecr", "aws_codeartifact"))
        if auth_payload and auth_payload["auth_type"] in ("basic", "bearer"):
            payload["upstream_auth_type"] = auth_payload["auth_type"]
            if "username" in auth_payload:
                payload["upstream_username"] = auth_payload["username"]
            if "password" in auth_payload:
                payload["upstream_password"] = auth_payload["password"]
        preview = {k: v for k, v in payload.items() if k not in ("upstream_password",)}
        if auth_payload and auth_payload["auth_type"] not in ("none",):
            preview["upstream_auth_type"] = auth_payload["auth_type"]
        if age_gate_base is not None:
            preview["age_gate"] = dict(age_gate_base)
        if module.check_mode:
            result = {"changed": True, "repository": preview, "changed_fields": sorted(preview)}
            if getattr(module, "_diff", False):
                result["diff"] = {"before": {}, "after": preview}
            module.exit_json(**result)
        created = client.post("/repositories", data=payload, expected=(200,))
        if needs_auth_put:
            client.put("/repositories/%s/upstream-auth" % q(p["key"]), data=auth_payload)
            created = repository_by_key(client, p["key"]) or created
        effective_age_gate = None
        if age_gate_base is not None:
            current_age_gate = client.get("/repositories/%s/age-gate" % q(p["key"]))
            desired_age_gate = dict(age_gate_base)
            if _age_gate_differs(current_age_gate, desired_age_gate):
                effective_age_gate = client.put(
                    "/repositories/%s/age-gate" % q(p["key"]),
                    data=desired_age_gate,
                )
            else:
                effective_age_gate = current_age_gate
        result = {
            "changed": True,
            "repository": _repository_with_age_gate(created, effective_age_gate),
            "changed_fields": sorted(preview),
        }
        if getattr(module, "_diff", False):
            after_preview = dict(preview)
            if effective_age_gate is not None:
                after_preview["age_gate"] = effective_age_gate
            result["diff"] = {"before": {}, "after": after_preview}
        module.exit_json(**result)

    for immutable in ("format", "repo_type"):
        if p.get(immutable) is not None and existing.get(immutable) != p[immutable]:
            module.fail_json(
                msg="repository %s is immutable in Artifact Keeper 1.10.1: current=%r desired=%r" % (
                    immutable,
                    existing.get(immutable),
                    p[immutable],
                )
            )

    if p.get("upstream_url") is not None and existing.get("upstream_url") != p["upstream_url"]:
        module.fail_json(
            msg=(
                "Artifact Keeper 1.10.1 does not expose upstream_url in "
                "UpdateRepositoryRequest; create a new remote repository or "
                "change it outside this module"
            )
        )

    changed_fields, before, after = managed_diff(existing, desired, desired.keys())
    auth_change = False
    if auth_payload is not None:
        desired_type = None if auth_payload["auth_type"] == "none" else auth_payload["auth_type"]
        configured = bool(existing.get("upstream_auth_configured"))
        current_type = existing.get("upstream_auth_type")
        if auth_payload["auth_type"] == "none":
            auth_change = configured or current_type is not None
        else:
            auth_change = (not configured) or current_type != desired_type or p.get("force_upstream_auth_update", False)
        if auth_change:
            changed_fields.append("upstream_auth")

    current_age_gate = None
    desired_age_gate = None
    age_gate_change = False
    if age_gate_base is not None:
        current_age_gate = client.get("/repositories/%s/age-gate" % q(p["key"]))
        desired_age_gate = dict(age_gate_base)
        age_gate_change = _age_gate_differs(current_age_gate, desired_age_gate)
        if age_gate_change:
            changed_fields.append("age_gate")

    if not changed_fields:
        module.exit_json(
            changed=False,
            repository=_repository_with_age_gate(existing, current_age_gate),
            changed_fields=[],
        )

    result = {
        "changed": True,
        "repository": _repository_with_age_gate(existing, current_age_gate),
        "changed_fields": changed_fields,
    }
    if getattr(module, "_diff", False):
        visible_before = dict(before)
        visible_after = dict(after)
        if auth_change:
            visible_before["upstream_auth_type"] = existing.get("upstream_auth_type")
            visible_after["upstream_auth_type"] = None if auth_payload["auth_type"] == "none" else auth_payload["auth_type"]
        if age_gate_change:
            visible_before["age_gate"] = {
                field: current_age_gate.get(field) for field in desired_age_gate
            }
            visible_after["age_gate"] = desired_age_gate
        result["diff"] = safe_diff(visible_before, visible_after, secrets=(p.get("upstream_password"),))
    if module.check_mode:
        predicted = {**existing, **desired}
        if age_gate_base is not None:
            predicted = _repository_with_age_gate(predicted, {**current_age_gate, **desired_age_gate})
        result["repository"] = predicted
        module.exit_json(**result)

    visible_changes = [field for field in changed_fields if field not in ("upstream_auth", "age_gate")]
    if visible_changes:
        patch = {field: desired[field] for field in visible_changes}
        client.patch("/repositories/%s" % q(p["key"]), data=patch)
    if auth_change:
        client.put("/repositories/%s/upstream-auth" % q(p["key"]), data=auth_payload)
    effective_age_gate = current_age_gate
    if age_gate_change:
        effective_age_gate = client.put(
            "/repositories/%s/age-gate" % q(p["key"]),
            data=desired_age_gate,
        )
    refreshed = repository_by_key(client, p["key"])
    result["repository"] = _repository_with_age_gate(refreshed, effective_age_gate)
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "key": {"type": "str", "required": True, "no_log": False},
            "name": {"type": "str"},
            "description": {"type": "str"},
            "format": {"type": "str"},
            "repo_type": {"type": "str", "choices": ["local", "remote", "virtual", "staging"]},
            "upstream_url": {"type": "str"},
            "upstream_auth_type": {"type": "str", "choices": ["basic", "bearer", "aws_ecr", "aws_codeartifact", "none"]},
            "upstream_username": {"type": "str"},
            "upstream_password": {"type": "str", "no_log": True},
            "upstream_aws": {
                "type": "dict",
                "options": {
                    "region": {"type": "str"},
                    "registry_id": {"type": "str"},
                    "domain": {"type": "str"},
                    "domain_owner": {"type": "str"},
                    "duration_seconds": {"type": "int"},
                },
            },
            "force_upstream_auth_update": {"type": "bool", "default": False},
            "project_key": {"type": "str", "aliases": ["project"], "no_log": False},
            "is_public": {"type": "bool"},
            "quota_bytes": {"type": "int"},
            "age_gate": {
                "type": "dict",
                "options": {
                    "enabled": {"type": "bool", "required": True},
                    "min_age_days": {"type": "int", "required": True},
                    "mode": {"type": "str", "choices": ["upstream_publish_time", "first_seen"]},
                },
            },
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        },
        required_if=[["state", "present", ["name", "format", "repo_type"]]],
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
