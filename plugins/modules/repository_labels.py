#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: repository_labels
short_description: Manage Artifact Keeper repository labels
version_added: "0.4.0"
description:
  - Manages the key/value labels of an existing Artifact Keeper repository.
  - Labels are matched by exact, case-sensitive key. Repository selectors, such as C(repo_selector.match_labels) of
    M(artifactkeeper.core.service_account_token) and sync policies, match repositories by these labels.
  - With O(labels_mode=exact), O(labels) is the complete set of labels and is applied in one atomic request.
  - With O(labels_mode=merge), the listed labels are added or updated and O(remove_labels) are deleted, leaving all other labels untouched.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  repository:
    description: Key of the repository whose labels are managed.
    type: str
    required: true
  labels:
    description:
      - Labels as a mapping of label key to value. Values must be strings; use an empty string for a key-only label.
      - Keys must be non-empty and at most 128 characters; values at most 256 characters.
      - Required with O(labels_mode=exact). To remove every label, set O(labels) explicitly to C({}).
      - With O(labels_mode=merge), may be omitted when O(remove_labels) is supplied.
    type: dict
  labels_mode:
    description:
      - V(exact) makes O(labels) the complete set of labels on the repository; labels not listed are removed.
      - V(merge) adds or updates the labels in O(labels), removes the keys in O(remove_labels), and leaves all other labels unchanged.
    type: str
    choices: [exact, merge]
    default: exact
  remove_labels:
    description:
      - Label keys to remove. Keys that are not present are ignored.
      - Only valid with O(labels_mode=merge); with O(labels_mode=exact), removal follows from O(labels).
    type: list
    elements: str
notes:
  - >-
    With O(labels_mode=merge), each changed label is a separate request, applied in a fixed order (additions and updates by key, then removals by key).
    The requests are not atomic: if one fails, the earlier ones stay applied, and the next run applies the rest.
  - Label values are returned to anyone who can see the repository, so do not store secrets in labels.
'''

EXAMPLES = r'''
- name: Set the complete label set of a repository
  artifactkeeper.core.repository_labels:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: python-local
    labels:
      tier: gold
      team: core
      pci: ""

- name: Add one label and remove another, leaving the rest unchanged
  artifactkeeper.core.repository_labels:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: python-local
    labels_mode: merge
    labels:
      owner: ci
    remove_labels:
      - team

- name: Remove every label from a repository
  artifactkeeper.core.repository_labels:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: python-local
    labels: {}
'''

RETURN = r'''
labels:
  description:
    - Labels on the repository after the change, as a mapping of key to value.
    - In check mode these are the predicted labels.
  returned: always
  type: dict
added:
  description: Sorted keys of labels that were (or in check mode would be) added.
  returned: always
  type: list
  elements: str
updated:
  description: Sorted keys of labels whose value was (or in check mode would be) changed.
  returned: always
  type: list
  elements: str
removed:
  description: Sorted keys of labels that were (or in check mode would be) removed.
  returned: always
  type: list
  elements: str
changed_fields:
  description: C([labels]) when the labels changed, otherwise an empty list.
  returned: always
  type: list
  elements: str
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    q,
)

# Column limits of the server's repository_labels table; longer values fail with a database error.
MAX_KEY_LENGTH = 128
MAX_VALUE_LENGTH = 256


def _validate_key(module, key):
    if not isinstance(key, str) or not key:
        module.fail_json(msg="label keys must be non-empty strings")
    if len(key) > MAX_KEY_LENGTH:
        module.fail_json(msg="label key '%s' is longer than %d characters" % (key, MAX_KEY_LENGTH))


def _requested(module, p):
    """Validate the request before any API call and return (labels, remove_labels)."""
    labels = p.get("labels")
    remove = p.get("remove_labels")
    if p["labels_mode"] == "exact":
        if remove is not None:
            module.fail_json(msg="remove_labels can only be used with labels_mode=merge; with labels_mode=exact, labels is the complete set")
        if labels is None:
            module.fail_json(msg="labels is required with labels_mode=exact; set labels: {} to remove every label")
    elif labels is None and remove is None:
        module.fail_json(msg="no label operation requested; supply labels, remove_labels, or both with labels_mode=merge")

    labels = labels or {}
    for key, value in labels.items():
        _validate_key(module, key)
        if not isinstance(value, str):
            module.fail_json(msg="label '%s' value must be a string" % key)
        if len(value) > MAX_VALUE_LENGTH:
            module.fail_json(msg="label '%s' value is longer than %d characters" % (key, MAX_VALUE_LENGTH))
    remove = remove or []
    for key in remove:
        _validate_key(module, key)
    both = sorted(set(labels) & set(remove))
    if both:
        module.fail_json(msg="labels and remove_labels both name: %s" % ", ".join(both))
    return labels, sorted(set(remove))


def _as_dict(response):
    items = response.get("items", []) if isinstance(response, dict) else []
    return {item["key"]: item.get("value", "") for item in items}


def _sorted(labels):
    return {key: labels[key] for key in sorted(labels)}


def run_module(module, client):
    p = module.params
    desired, remove = _requested(module, p)
    path = "/repositories/%s/labels" % q(p["repository"])

    response = client.get(path, allow_404=True)
    if response is None:
        module.fail_json(msg="repository '%s' was not found" % p["repository"])
    current = _as_dict(response)

    updated = sorted(key for key in desired if key in current and current[key] != desired[key])
    added = sorted(key for key in desired if key not in current)
    if p["labels_mode"] == "exact":
        removed = sorted(key for key in current if key not in desired)
        final = dict(desired)
    else:
        removed = sorted(key for key in remove if key in current)
        final = dict(current, **desired)
        for key in removed:
            del final[key]

    changed = bool(added or updated or removed)
    result = {
        "changed": changed,
        "labels": _sorted(final),
        "added": added,
        "updated": updated,
        "removed": removed,
        "changed_fields": ["labels"] if changed else [],
    }
    if not changed:
        module.exit_json(**result)
    if getattr(module, "_diff", False):
        result["diff"] = {"before": _sorted(current), "after": _sorted(final)}
    if module.check_mode:
        module.exit_json(**result)

    if p["labels_mode"] == "exact":
        # One atomic replacement of the whole set.
        payload = {"labels": [{"key": key, "value": final[key]} for key in sorted(final)]}
        response = client.put(path, data=payload, expected=(200,))
        if isinstance(response, dict) and "items" in response:
            result["labels"] = _sorted(_as_dict(response))
    else:
        # Fixed order: additions and updates by key, then removals by key.
        for key in sorted(added + updated):
            client.post("%s/%s" % (path, q(key)), data={"value": desired[key]}, expected=(200,))
        for key in removed:
            client.delete("%s/%s" % (path, q(key)), expected=(204,))
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "repository": {"type": "str", "required": True, "no_log": False},
            "labels": {"type": "dict"},
            "labels_mode": {"type": "str", "choices": ["exact", "merge"], "default": "exact"},
            "remove_labels": {"type": "list", "elements": "str"},
        }
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
