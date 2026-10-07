# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared argument specs and resource lookup helpers."""

from __future__ import annotations

from urllib.parse import quote

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.artifactkeeper.core.plugins.module_utils.api import (
    ArtifactKeeperClient,
    ArtifactKeeperError,
    redact,
)


def common_argument_spec():
    return {
        "api_url": {"type": "str", "required": True},
        "token": {"type": "str", "no_log": True},
        "username": {"type": "str"},
        "password": {"type": "str", "no_log": True},
        "validate_certs": {"type": "bool", "default": True},
        "ca_path": {"type": "path"},
        "timeout": {"type": "int", "default": 30},
    }


def make_module(argument_spec, **kwargs):
    spec = common_argument_spec()
    spec.update(argument_spec)
    required_together = list(kwargs.pop("required_together", [])) + [["username", "password"]]
    mutually_exclusive = list(kwargs.pop("mutually_exclusive", [])) + [["token", "username"], ["token", "password"]]
    required_one_of = list(kwargs.pop("required_one_of", [])) + [["token", "username"]]
    return AnsibleModule(
        argument_spec=spec,
        supports_check_mode=True,
        required_together=required_together,
        mutually_exclusive=mutually_exclusive,
        required_one_of=required_one_of,
        **kwargs,
    )


def client_from_module(module):
    return ArtifactKeeperClient(
        api_url=module.params["api_url"],
        token=module.params.get("token"),
        username=module.params.get("username"),
        password=module.params.get("password"),
        validate_certs=module.params["validate_certs"],
        ca_path=module.params.get("ca_path"),
        timeout=module.params["timeout"],
    )


def fail_from_exception(module, exc):
    if isinstance(exc, ArtifactKeeperError):
        module.fail_json(msg=str(exc))
    raise exc


def q(value):
    return quote(str(value), safe="")


def project_by_key(client, key):
    response = client.get("/projects")
    projects = response.get("items", []) if isinstance(response, dict) else response or []
    matches = [project for project in projects if project.get("key") == key]
    if len(matches) > 1:
        raise ArtifactKeeperError("multiple projects returned with key '%s'" % key)
    return matches[0] if matches else None


def repository_by_key(client, key):
    return client.get("/repositories/%s" % q(key), allow_404=True)


def canonical_service_account_username(name):
    """Return the username Artifact Keeper derives from a service-account name."""
    value = str(name).strip()
    if value.lower().startswith("svc-"):
        value = value[4:]
    return "svc-%s" % value.lower().replace(" ", "-")


def service_account_create_name(name):
    """Return a create-API name that will not be double-prefixed by the server."""
    value = str(name).strip()
    return value[4:] if value.lower().startswith("svc-") else value


def service_account_by_name(client, name):
    response = client.get("/service-accounts")
    items = response.get("items", []) if isinstance(response, dict) else []
    canonical = canonical_service_account_username(name)
    matches = [item for item in items if item.get("username") == canonical]
    if len(matches) > 1:
        raise ArtifactKeeperError("service account name '%s' is ambiguous" % name)
    return matches[0] if matches else None


def group_by_name(client, name):
    items = client.paginate("/groups", params={"search": name})
    matches = [item for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise ArtifactKeeperError("multiple groups returned with name '%s'" % name)
    return matches[0] if matches else None


def user_by_identifier(client, identifier, service_account=False):
    items = client.paginate(
        "/users",
        params={"search": identifier, "is_service_account": service_account},
    )
    matches = [
        item
        for item in items
        if item.get("username") == identifier or item.get("email") == identifier
    ]
    if len(matches) > 1:
        raise ArtifactKeeperError("user identifier '%s' is ambiguous" % identifier)
    return matches[0] if matches else None


def users_by_username(client, username):
    """Return all /users rows, people and service accounts, whose username is exactly `username`."""
    items = client.paginate("/users", params={"search": username})
    return [item for item in items if item.get("username") == username]


def user_by_username(client, username):
    """Return the single non-service-account user with this exact username, or None."""
    matches = [item for item in users_by_username(client, username) if not item.get("is_service_account")]
    if len(matches) > 1:
        raise ArtifactKeeperError("multiple users returned with username '%s'" % username)
    return matches[0] if matches else None


def principal_by_identifier(client, principal_type, identifier):
    if principal_type == "group":
        return group_by_name(client, identifier)
    if principal_type == "service_account":
        return service_account_by_name(client, identifier)
    return user_by_identifier(client, identifier, service_account=False)


def managed_diff(current, desired, fields):
    before = {}
    after = {}
    changed_fields = []
    for field in fields:
        if field not in desired:
            continue
        old = current.get(field) if current else None
        new = desired[field]
        before[field] = old
        after[field] = new
        if old != new:
            changed_fields.append(field)
    return changed_fields, before, after


def safe_diff(before, after, secrets=()):
    return {"before": redact(before, secrets), "after": redact(after, secrets)}
