#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: group_info
short_description: Gather Artifact Keeper group information
version_added: "0.1.0"
description:
  - Returns Artifact Keeper groups, optionally filtered to an exact group name.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  name:
    description: Exact group name. The server-side search is used first, followed by exact matching.
    type: str
'''

EXAMPLES = r'''
- name: Look up engineers group
  artifactkeeper.core.group_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: engineers
  register: engineers
'''

RETURN = r'''
groups:
  description: Matching groups.
  returned: always
  type: list
  elements: dict
group:
  description: Exact group when O(name) was supplied, otherwise C(null).
  returned: always
  type: dict
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
)


def run_module(module, client):
    name = module.params.get("name")
    params = {"search": name} if name else None
    groups = client.paginate("/groups", params=params)
    if name:
        groups = [group for group in groups if group.get("name") == name]
    module.exit_json(changed=False, groups=groups, group=groups[0] if len(groups) == 1 else None)


def main():
    module = make_module({"name": {"type": "str"}})
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
