#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: project_info
short_description: Gather Artifact Keeper project information
version_added: "0.1.0"
description:
  - Returns Artifact Keeper projects without changing server state.
  - When O(key) is supplied, results are filtered to the project with that exact stable key.
  - Project management endpoints are currently administrator-only in Artifact Keeper.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  key:
    description:
      - Exact stable project key to look up.
      - When omitted, all projects returned by the Artifact Keeper projects endpoint are returned.
    type: str
'''

EXAMPLES = r'''
- name: Look up engineering project
  artifactkeeper.core.project_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: engineering
  register: engineering_project

- name: List all projects
  artifactkeeper.core.project_info:
    api_url: https://artifacts.example.com
    username: admin
    password: "{{ artifactkeeper_admin_password }}"
  register: artifactkeeper_projects
'''

RETURN = r'''
projects:
  description:
    - Matching projects.
    - When O(key) is omitted, this contains all projects returned by Artifact Keeper.
  returned: always
  type: list
  elements: dict
  contains:
    id:
      description: Artifact Keeper project UUID.
      type: str
      returned: always
    key:
      description: Stable project key.
      type: str
      returned: always
    name:
      description: Project display name.
      type: str
      returned: always
    description:
      description: Project description.
      type: str
      returned: when set
    quota_bytes:
      description: Stored project quota metadata in bytes.
      type: int
      returned: when set
    created_at:
      description: Project creation timestamp.
      type: str
      returned: when supplied by the server
    updated_at:
      description: Project last-update timestamp.
      type: str
      returned: when supplied by the server
project:
  description:
    - Exact project when O(key) was supplied and matched exactly.
    - C(null) when O(key) was omitted or no matching project exists.
  returned: always
  type: dict
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.api import ArtifactKeeperError
from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    project_by_key,
)


def _projects_from_response(response):
    if isinstance(response, dict):
        projects = response.get("items", [])
    elif isinstance(response, list):
        projects = response
    else:
        raise ArtifactKeeperError("projects endpoint returned an unexpected response type")

    if not isinstance(projects, list):
        raise ArtifactKeeperError("projects endpoint returned non-list 'items'")
    return projects


def run_module(module, client):
    key = module.params.get("key")

    if key is not None:
        project = project_by_key(client, key)
        module.exit_json(
            changed=False,
            projects=[project] if project else [],
            project=project,
        )

    projects = _projects_from_response(client.get("/projects"))
    module.exit_json(changed=False, projects=projects, project=None)


def main():
    module = make_module({"key": {"type": "str", "no_log": False}})
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
