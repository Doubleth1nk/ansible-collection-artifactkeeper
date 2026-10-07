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
  - Existing token scopes are idempotently compared. A managed repository restriction (O(repositories) or O(repo_selector)) is compared too.
  - Scopes and repository restrictions cannot be changed on an existing token, so a difference rotates the token
    by creating a replacement first and then revoking the old token.
  - The current list API does not return the creation-time description, so description is not used to force rotation.
  - O(expires_in_days) is used when creating a token.
  - The list API returns only an absolute C(expires_at), so the original relative duration cannot always be reconstructed after policy shaping.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
notes:
  - When neither O(repositories) nor O(repo_selector) is supplied, the repository restriction is unmanaged; it is neither sent nor compared.
    A token created that way is unrestricted when the module authenticates with an unrestricted credential.
    When it authenticates with a repository-restricted token, Artifact Keeper 1.10.2 and later restrict the new token to that credential's repositories.
  - A repository-restricted credential may not choose a restriction for the tokens it creates;
    Artifact Keeper rejects O(repositories) or O(repo_selector) with HTTP 403.
    The module cannot detect this in advance, so check mode reports a change that the real run then fails with that error, leaving any existing token untouched.
  - If revoking the old token fails during a rotation, the module revokes the replacement again and fails, leaving the original token in place.
    If that also fails, the failure names both token IDs for manual cleanup. A failed rotation never returns the new plaintext token.
  - Artifact Keeper 1.10.2 advises reviewing and rotating tokens minted through a repository-restricted credential before upgrading;
    rotate a token by running this module with O(state=absent) and then O(state=present).
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
  repositories:
    description:
      - Repository keys the token is restricted to.
      - The keys are resolved to repository IDs; an unknown key fails before anything is changed.
      - Duplicates are ignored. An empty list is rejected, because Artifact Keeper would treat it as no restriction.
      - When omitted, the repository restriction is unmanaged.
      - Mutually exclusive with O(repo_selector).
    type: list
    elements: str
    version_added: "0.3.0"
  repo_selector:
    description:
      - Dynamic repository selector the token is restricted to, resolved by Artifact Keeper at authentication time,
        so repositories created later that match are included.
      - At least one of O(repo_selector.match_labels), O(repo_selector.match_formats), or O(repo_selector.match_pattern) must be set.
      - When omitted, the repository restriction is unmanaged.
      - Mutually exclusive with O(repositories).
    type: dict
    version_added: "0.3.0"
    suboptions:
      match_labels:
        description: Repository labels that must all match. Values must be strings.
        type: dict
      match_formats:
        description: Repository formats, any of which matches.
        type: list
        elements: str
      match_pattern:
        description:
          - Repository key pattern; only the C(*) wildcard is supported.
          - Sent exactly as given. An empty string is a valid pattern that matches no repository, and C(*) matches every repository.
        type: str
  state:
    description: Whether the named token metadata should exist.
    type: str
    choices: [present, absent]
    default: present
'''

EXAMPLES = r'''
- name: Create a service-account token restricted to two repositories
  artifactkeeper.core.service_account_token:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_admin_token }}"
    service_account: ci
    name: automation
    description: CI automation token
    scopes: [read, write]
    repositories:
      - python-local
      - pypi-remote
    expires_in_days: 90
    state: present
  no_log: true
  register: ci_token

- name: Create a token restricted to every Docker repository named libs-*
  artifactkeeper.core.service_account_token:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_admin_token }}"
    service_account: ci
    name: images
    scopes: [read]
    repo_selector:
      match_formats: [docker]
      match_pattern: "libs-*"
  no_log: true
  register: images_token

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
  contains:
    id:
      description: Token UUID.
      type: str
      returned: when the token exists
    scopes:
      description: Token scopes.
      type: list
      elements: str
      returned: when the token exists
    repository_ids:
      description: Repository UUIDs the token is explicitly restricted to, as returned by Artifact Keeper.
      type: list
      elements: str
      returned: when the token exists
    repo_selector:
      description: Repository selector the token is restricted to, as returned by Artifact Keeper, or C(null).
      type: dict
      returned: when the token exists
changed_fields:
  description: Fields that differed from the existing token, or that were set on a new token.
  returned: when O(state=present)
  type: list
  elements: str
token:
  description: Newly generated plaintext token. This is sensitive and is only returned on successful creation.
  returned: only when Artifact Keeper creates a token and the task succeeds
  type: str
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError, redact
from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    q,
    repository_by_key,
    service_account_by_name,
)

SELECTOR_KEYS = ("match_labels", "match_formats", "match_pattern")


def _list_tokens(client, account_id):
    response = client.get("/service-accounts/%s/tokens" % q(account_id))
    return response.get("items", []) if isinstance(response, dict) else []


def _desired_repositories(module, client, p):
    """Resolve O(repositories) keys to IDs. Returns (ids, key_by_id) or (None, {})."""
    keys = p.get("repositories")
    if keys is None:
        return None, {}
    if not keys:
        module.fail_json(msg="repositories must list at least one repository key; omit it to leave the repository restriction unmanaged")
    if any(not key or not key.strip() for key in keys):
        module.fail_json(msg="repositories must not contain empty repository keys")
    key_by_id = {}
    for key in sorted(set(keys)):
        repository = repository_by_key(client, key)
        if not repository:
            module.fail_json(msg="repository '%s' was not found" % key)
        key_by_id[repository["id"]] = key
    return sorted(key_by_id), key_by_id


def _desired_selector(module, p):
    """Mirror Artifact Keeper 1.10.2's token repo_selector validation and build the payload."""
    raw = p.get("repo_selector")
    if raw is None:
        return None
    labels = raw.get("match_labels") or {}
    formats = raw.get("match_formats") or []
    pattern = raw.get("match_pattern")
    for label, value in labels.items():
        if not isinstance(value, str):
            module.fail_json(msg="repo_selector.match_labels value for '%s' must be a string" % label)
    if not labels and not formats and pattern is None:
        module.fail_json(
            msg="repo_selector names no repositories; set match_labels, match_formats, or match_pattern, "
            "or omit repo_selector to leave the repository restriction unmanaged"
        )
    selector = {}
    if labels:
        selector["match_labels"] = dict(labels)
    if formats:
        selector["match_formats"] = list(dict.fromkeys(formats))
    if pattern is not None:
        # Sent verbatim: "" is a valid, restricting pattern and must not be dropped.
        selector["match_pattern"] = pattern
    return selector


def _canonical_selector(selector):
    """Return a comparable form of a stored selector, or None if it is not one this module can manage."""
    if not isinstance(selector, dict):
        return None
    if selector.get("match_repos"):
        return None
    if any(key not in SELECTOR_KEYS + ("match_repos",) for key in selector):
        return None
    labels = selector.get("match_labels") or {}
    formats = selector.get("match_formats") or []
    pattern = selector.get("match_pattern")
    if not isinstance(labels, dict) or not isinstance(formats, list) or (pattern is not None and not isinstance(pattern, str)):
        return None
    return {"match_labels": dict(labels), "match_formats": sorted(set(formats)), "match_pattern": pattern}


def _restriction_differs(existing, desired_ids, desired_selector):
    if desired_ids is not None:
        return existing.get("repo_selector") is not None or set(existing.get("repository_ids") or []) != set(desired_ids)
    if desired_selector is not None:
        if existing.get("repository_ids"):
            return True
        return _canonical_selector(existing.get("repo_selector")) != _canonical_selector(desired_selector)
    return False


def _placeholders(ids):
    """Display-only names for repository IDs without a known key; the IDs themselves are not shown."""
    return ["<unresolved repository #%d>" % index for index, dummy in enumerate(sorted(ids), start=1)]


def _display_repositories(ids, key_by_id):
    known = sorted(key_by_id[repository_id] for repository_id in ids if repository_id in key_by_id)
    return known + _placeholders([repository_id for repository_id in ids if repository_id not in key_by_id])


def _display_selector(selector):
    """Diff form of a selector: effective criteria only, with any match_repos IDs replaced by placeholders."""
    if not isinstance(selector, dict):
        return selector
    display = {}
    if selector.get("match_labels"):
        display["match_labels"] = selector["match_labels"]
    if selector.get("match_formats"):
        display["match_formats"] = sorted(set(selector["match_formats"]))
    if selector.get("match_pattern") is not None:
        display["match_pattern"] = selector["match_pattern"]
    if selector.get("match_repos"):
        display["match_repos"] = _placeholders(selector["match_repos"])
    for key in selector:
        if key not in SELECTOR_KEYS + ("match_repos",):
            display[key] = selector[key]
    return display


def _diff(p, existing, desired_scopes, desired_ids, desired_selector, key_by_id):
    """User-facing diff: repository keys, never repository IDs; restriction only when it is managed."""
    after = {"name": p["name"], "scopes": desired_scopes}
    if desired_ids is not None:
        after["repositories"] = _display_repositories(desired_ids, key_by_id)
    if desired_selector is not None:
        after["repo_selector"] = _display_selector(desired_selector)
    if not existing:
        return {"before": {}, "after": after}
    before = {"name": p["name"], "scopes": sorted(set(existing.get("scopes") or []))}
    if desired_ids is not None or desired_selector is not None:
        # Show whichever restriction the existing token has, since that is what is being replaced.
        existing_ids = existing.get("repository_ids") or []
        existing_selector = existing.get("repo_selector")
        if desired_ids is not None or existing_ids:
            before["repositories"] = _display_repositories(existing_ids, key_by_id)
        if desired_selector is not None or existing_selector is not None:
            before["repo_selector"] = _display_selector(existing_selector)
    return {"before": before, "after": after}


def _created_token_info(client, account_id, created):
    """Prefer the listed token (it shows the effective restriction) over the bare create response."""
    listed = next((item for item in _list_tokens(client, account_id) if item.get("id") == created.get("id")), None)
    info = dict(listed) if listed else {}
    for key, value in created.items():
        if key != "token" and (key not in info or key == "policy_applied"):
            info[key] = value
    info.pop("token", None)
    return info


def _rotate_cleanup_failure(module, client, account_id, old_id, new_id, secret, error):
    """Revoking the old token failed after its replacement was created: roll the replacement back."""
    reason = redact(str(error), (secret,))
    try:
        client.delete("/service-accounts/%s/tokens/%s" % (q(account_id), q(new_id)))
    except ArtifactKeeperError as rollback_error:
        module.fail_json(
            msg=(
                "token rotation failed: the replacement token %s was created, revoking the previous token %s failed (%s), "
                "and revoking the replacement also failed (%s); two live tokens with this name may now exist, "
                "revoke them manually" % (new_id, old_id, reason, redact(str(rollback_error), (secret,)))
            ),
            changed=True,
            previous_token_id=old_id,
            replacement_token_id=new_id,
        )
    module.fail_json(
        msg=(
            "token rotation failed: the replacement token was created but revoking the previous token %s failed (%s); "
            "the replacement was revoked again and the previous token is unchanged" % (old_id, reason)
        ),
        changed=False,
    )


def run_module(module, client):
    p = module.params
    if p.get("repositories") is not None and p.get("repo_selector") is not None:
        module.fail_json(msg="parameters are mutually exclusive: repositories|repo_selector")
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
    desired_ids, key_by_id = _desired_repositories(module, client, p)
    desired_selector = _desired_selector(module, p)
    restriction_field = "repositories" if desired_ids is not None else "repo_selector" if desired_selector is not None else None

    if existing:
        current_scopes = sorted(set(existing.get("scopes") or []))
        changed_fields = []
        if current_scopes != desired_scopes:
            changed_fields.append("scopes")
        if _restriction_differs(existing, desired_ids, desired_selector):
            changed_fields.append(restriction_field)
        if not changed_fields:
            module.exit_json(changed=False, token_info=existing, changed_fields=[])
    else:
        changed_fields = ["name", "scopes"] + [
            field for field in ("description", "expires_in_days") if p.get(field) is not None
        ] + ([restriction_field] if restriction_field else [])

    payload = {"name": p["name"], "scopes": desired_scopes}
    if p.get("description") is not None:
        payload["description"] = p["description"]
    if p.get("expires_in_days") is not None:
        payload["expires_in_days"] = p["expires_in_days"]
    if desired_ids is not None:
        payload["repository_ids"] = desired_ids
    if desired_selector is not None:
        payload["repo_selector"] = desired_selector

    result = {"changed": True, "changed_fields": changed_fields}
    if getattr(module, "_diff", False):
        result["diff"] = _diff(p, existing, desired_scopes, desired_ids, desired_selector, key_by_id)
    if module.check_mode:
        preview = {"name": p["name"], "scopes": desired_scopes}
        if desired_ids is not None:
            preview.update(repository_ids=desired_ids, repo_selector=None)
        if desired_selector is not None:
            preview.update(repository_ids=[], repo_selector=desired_selector)
        result["token_info"] = {**existing, **preview} if existing else preview
        module.exit_json(**result)

    # Create the replacement before revoking the old token, so a failed create
    # (for example a 403 from a repository-restricted credential) changes nothing.
    created = client.post("/service-accounts/%s/tokens" % q(account["id"]), data=payload, expected=(200,))
    secret = created.get("token")
    if existing:
        try:
            client.delete("/service-accounts/%s/tokens/%s" % (q(account["id"]), q(existing["id"])))
        except ArtifactKeeperError as error:
            _rotate_cleanup_failure(module, client, account["id"], existing["id"], created.get("id"), secret, error)
    result["token_info"] = _created_token_info(client, account["id"], created)
    result["token"] = secret
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "service_account": {"type": "str", "required": True},
            "name": {"type": "str", "required": True},
            "description": {"type": "str"},
            "scopes": {"type": "list", "elements": "str"},
            "expires_in_days": {"type": "int"},
            "repositories": {"type": "list", "elements": "str"},
            "repo_selector": {
                "type": "dict",
                "options": {
                    "match_labels": {"type": "dict"},
                    "match_formats": {"type": "list", "elements": "str"},
                    "match_pattern": {"type": "str"},
                },
            },
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        },
        required_if=[["state", "present", ["scopes"]]],
        mutually_exclusive=[["repositories", "repo_selector"]],
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
