#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: repository_scan_config
short_description: Manage Artifact Keeper repository security scan configuration
version_added: "0.4.0"
description:
  - Manages the security scan configuration of an existing Artifact Keeper repository through C(/repositories/{key}/security).
  - Only the options that are supplied are managed. An omitted option is neither compared nor sent, and the server keeps its current value.
  - >-
    A repository that was never configured has no stored scan configuration, and Artifact Keeper then behaves as if every setting
    had its default value (scanning off, O(severity_threshold=high), O(proxy_scan_action=fail_open)). The module compares against
    those defaults, so a request that only names default values does not create a configuration.
  - Without any setting options, the module only reads and returns the effective configuration.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  repository:
    description: Key of the repository whose scan configuration is managed.
    type: str
    required: true
  scan_enabled:
    description:
      - Whether security scanning is enabled for the repository.
      - Artifact Keeper default when the repository has no scan configuration is V(false).
    type: bool
  scan_on_upload:
    description:
      - Whether artifacts uploaded to the repository are scanned. Only takes effect together with O(scan_enabled=true).
      - Artifact Keeper default when the repository has no scan configuration is V(false).
    type: bool
  scan_on_proxy:
    description:
      - Whether artifacts fetched through the repository's proxy path are scanned.
      - Artifact Keeper default when the repository has no scan configuration is V(false).
    type: bool
  block_on_policy_violation:
    description:
      - Whether the inline proxy scan gate blocks only findings at or above O(severity_threshold). When V(false), the gate blocks on any finding.
      - Artifact Keeper default when the repository has no scan configuration is V(false).
    type: bool
  severity_threshold:
    description:
      - Lowest finding severity that blocks a pull on the inline proxy scan gate. Only takes effect with O(block_on_policy_violation=true).
      - Artifact Keeper default when the repository has no scan configuration is V(high).
    type: str
    choices: [critical, high, medium, low, info]
  proxy_scan_action:
    description:
      - Action of the inline proxy scan on fetch. V(fail_closed) blocks rather than serving content that could not be scanned or was found vulnerable.
      - Artifact Keeper default when the repository has no scan configuration is V(fail_open).
    type: str
    choices: [fail_open, fail_closed]
notes:
  - >-
    Changing the configuration requires the repository C(admin) action (for example through
    M(artifactkeeper.core.repository_permission)) or an administrator account; a C(write) grant is not sufficient.
  - >-
    Artifact Keeper has no endpoint that deletes a scan configuration. Once one exists, setting every option to its default value
    restores the default behavior, but the configuration stays stored and RV(configured) remains V(true).
  - Settings are stored for every repository type; the proxy options only affect repositories that serve content through a proxy path.
  - Changes apply to subsequent uploads and pulls, including pulls of already cached content. Existing artifacts are not rescanned.
  - Setting an option to V(null) is the same as omitting it, which leaves that setting unmanaged.
'''

EXAMPLES = r'''
- name: Scan uploads and proxied artifacts, failing closed on the proxy path
  artifactkeeper.core.repository_scan_config:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: pypi-remote
    scan_enabled: true
    scan_on_upload: true
    scan_on_proxy: true
    proxy_scan_action: fail_closed

- name: Block proxied pulls only for critical findings
  artifactkeeper.core.repository_scan_config:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: pypi-remote
    block_on_policy_violation: true
    severity_threshold: critical

- name: Read the effective scan configuration without changing it
  artifactkeeper.core.repository_scan_config:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: pypi-remote
  register: pypi_remote_scan_config
'''

RETURN = r'''
scan_config:
  description:
    - Effective scan configuration after the change. In check mode this is the predicted configuration.
    - When the repository has no stored configuration, these are the Artifact Keeper defaults.
  returned: always
  type: dict
  contains:
    scan_enabled:
      description: Whether security scanning is enabled.
      type: bool
      returned: always
    scan_on_upload:
      description: Whether uploads are scanned.
      type: bool
      returned: always
    scan_on_proxy:
      description: Whether proxied artifacts are scanned.
      type: bool
      returned: always
    block_on_policy_violation:
      description: Whether the inline proxy scan gate uses O(severity_threshold).
      type: bool
      returned: always
    severity_threshold:
      description: Severity floor of the inline proxy scan gate.
      type: str
      returned: always
    proxy_scan_action:
      description: Inline proxy scan action.
      type: str
      returned: always
configured:
  description:
    - Whether Artifact Keeper stores a scan configuration for the repository after the change. In check mode this is the predicted state.
    - V(false) means the repository was never configured and the defaults apply.
  returned: always
  type: bool
changed_fields:
  description: Sorted names of the managed options that differed from the effective configuration.
  returned: always
  type: list
  elements: str
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    managed_diff,
    q,
)

# Values Artifact Keeper 1.10.2 applies when a repository has no scan_configs row, both when
# reading (every enforcement path falls back to them) and when the first PUT creates the row.
DEFAULTS = {
    "scan_enabled": False,
    "scan_on_upload": False,
    "scan_on_proxy": False,
    "block_on_policy_violation": False,
    "severity_threshold": "high",
    "proxy_scan_action": "fail_open",
}
FIELDS = sorted(DEFAULTS)


def _effective(config):
    if not isinstance(config, dict):
        return dict(DEFAULTS)
    return {field: config.get(field) for field in FIELDS}


def run_module(module, client):
    p = module.params
    desired = {field: p[field] for field in FIELDS if p.get(field) is not None}
    path = "/repositories/%s/security" % q(p["repository"])

    response = client.get(path, allow_404=True)
    if response is None:
        module.fail_json(msg="repository '%s' was not found or is not visible to the current credential" % p["repository"])
    config = response.get("config") if isinstance(response, dict) else None
    configured = isinstance(config, dict)
    current = _effective(config)

    changed_fields, before, after = managed_diff(current, desired, FIELDS)
    changed = bool(changed_fields)
    result = {
        "changed": changed,
        "scan_config": dict(current, **desired),
        # A PUT creates the row, so any change leaves the repository configured.
        "configured": configured or changed,
        "changed_fields": changed_fields,
    }
    if not changed:
        module.exit_json(**result)
    if getattr(module, "_diff", False):
        result["diff"] = {"before": before, "after": after}
    if module.check_mode:
        module.exit_json(**result)

    # The server merges the request over the stored row (or the defaults), so only the differences are sent.
    payload = {field: desired[field] for field in changed_fields}
    response = client.put(path, data=payload, expected=(200,))
    if isinstance(response, dict):
        result["scan_config"] = {field: response.get(field, result["scan_config"][field]) for field in FIELDS}
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "repository": {"type": "str", "required": True, "no_log": False},
            "scan_enabled": {"type": "bool"},
            "scan_on_upload": {"type": "bool"},
            "scan_on_proxy": {"type": "bool"},
            "block_on_policy_violation": {"type": "bool"},
            "severity_threshold": {"type": "str", "choices": ["critical", "high", "medium", "low", "info"]},
            "proxy_scan_action": {"type": "str", "choices": ["fail_open", "fail_closed"]},
        }
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
