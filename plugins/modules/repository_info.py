#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: repository_info
short_description: Gather Artifact Keeper repository information
version_added: "0.2.0"
description:
  - Returns Artifact Keeper repositories without changing server state.
  - When O(key) is supplied, the repository with that exact stable key is returned.
  - Otherwise the repository listing is returned, optionally filtered by format, type, search text, or project.
  - Repositories are only returned when the authenticated principal is allowed to see them.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  key:
    description:
      - Exact stable repository key to look up.
      - Mutually exclusive with O(format), O(repo_type), O(search), and O(project).
    type: str
  format:
    description:
      - Only return repositories of this package format, for example C(pypi) or C(docker).
    type: str
  repo_type:
    description:
      - Only return repositories of this type.
    type: str
    choices: [local, remote, virtual, staging]
  search:
    description:
      - Server-side search text applied to the repository listing.
    type: str
  project:
    description:
      - Only return repositories assigned to the project with this key.
      - The key is resolved to the project UUID expected by the API.
    type: str
'''

EXAMPLES = r'''
- name: Look up one repository
  artifactkeeper.core.repository_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: pypi-remote
  register: pypi_remote

- name: List remote PyPI repositories in the engineering project
  artifactkeeper.core.repository_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    format: pypi
    repo_type: remote
    project: engineering
  register: engineering_pypi_remotes
'''

RETURN = r'''
repositories:
  description:
    - Matching repositories.
    - When O(key) is supplied this contains at most one repository.
  returned: always
  type: list
  elements: dict
  contains:
    id:
      description: Artifact Keeper repository UUID.
      type: str
      returned: always
    key:
      description: Stable repository key.
      type: str
      returned: always
    name:
      description: Repository display name.
      type: str
      returned: always
    format:
      description: Repository package format.
      type: str
      returned: always
    repo_type:
      description: Repository type.
      type: str
      returned: always
    is_public:
      description: Whether anonymous downloads are allowed.
      type: bool
      returned: always
    project_id:
      description: UUID of the project the repository is assigned to.
      type: str
      returned: when set
    upstream_url:
      description: Upstream URL of a remote repository.
      type: str
      returned: when set
repository:
  description:
    - Exact repository when O(key) was supplied and exists.
    - C(null) when O(key) was omitted or no repository with that key exists.
  returned: always
  type: dict
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    project_by_key,
    repository_by_key,
)


def run_module(module, client):
    p = module.params

    if p.get("key") is not None:
        repository = repository_by_key(client, p["key"])
        module.exit_json(
            changed=False,
            repositories=[repository] if repository else [],
            repository=repository,
        )

    project_id = None
    if p.get("project") is not None:
        project = project_by_key(client, p["project"])
        if not project:
            module.fail_json(msg="project '%s' was not found" % p["project"])
        project_id = project["id"]

    params = {
        "format": p.get("format"),
        "type": p.get("repo_type"),
        "q": p.get("search"),
        "project": project_id,
    }
    params = {name: value for name, value in params.items() if value is not None}
    repositories = client.paginate("/repositories", params=params or None)
    module.exit_json(changed=False, repositories=repositories, repository=None)


def main():
    module = make_module(
        {
            "key": {"type": "str", "no_log": False},
            "format": {"type": "str"},
            "repo_type": {"type": "str", "choices": ["local", "remote", "virtual", "staging"]},
            "search": {"type": "str"},
            "project": {"type": "str", "no_log": False},
        },
        mutually_exclusive=[
            ["key", "format"],
            ["key", "repo_type"],
            ["key", "search"],
            ["key", "project"],
        ],
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
