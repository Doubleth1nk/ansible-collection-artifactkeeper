#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: user_info
short_description: Gather Artifact Keeper user information
version_added: "0.2.0"
description:
  - Returns Artifact Keeper users without changing server state.
  - When O(username) is supplied, only the user with exactly that username is returned. An email address never matches O(username).
  - Service accounts are stored as users by Artifact Keeper. They are excluded unless O(include_service_accounts=true).
  - The O(is_admin), O(is_active), and O(include_service_accounts) filters are applied to the returned users by this module,
    so a filtered listing still reads every user visible to the caller.
  - Listing users is currently administrator-only in Artifact Keeper.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  username:
    description:
      - Exact username to look up.
      - Mutually exclusive with O(search).
    type: str
  search:
    description:
      - Server-side search text for the user listing. Matching semantics are defined by Artifact Keeper.
      - Mutually exclusive with O(username).
    type: str
  is_admin:
    description:
      - Only return users whose administrator flag equals this value.
    type: bool
  is_active:
    description:
      - Only return users whose active flag equals this value.
    type: bool
  include_service_accounts:
    description:
      - Whether service-account users are included in the results.
    type: bool
    default: false
'''

EXAMPLES = r'''
- name: Look up one user
  artifactkeeper.core.user_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    username: alice
  register: alice

- name: List active administrators
  artifactkeeper.core.user_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    is_admin: true
    is_active: true
  register: active_admins
'''

RETURN = r'''
users:
  description: Matching users.
  returned: always
  type: list
  elements: dict
  contains:
    id:
      description: Artifact Keeper user UUID.
      type: str
      returned: always
    username:
      description: Username.
      type: str
      returned: always
    email:
      description: Email address.
      type: str
      returned: always
    display_name:
      description: Display name.
      type: str
      returned: when set
    auth_provider:
      description: Authentication provider that owns the account.
      type: str
      returned: always
    is_active:
      description: Whether the account is active.
      type: bool
      returned: always
    is_admin:
      description: Whether the account is an administrator.
      type: bool
      returned: always
    is_service_account:
      description: Whether the row is a service account rather than a person.
      type: bool
      returned: always
    must_change_password:
      description: Whether the user must change their password at next login.
      type: bool
      returned: always
    last_login_at:
      description: Last login timestamp.
      type: str
      returned: when set
    created_at:
      description: Creation timestamp.
      type: str
      returned: always
user:
  description:
    - The matching user when O(username) was supplied and exactly one user matched.
    - C(null) otherwise.
  returned: always
  type: dict
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    make_module,
    users_by_username,
)


def run_module(module, client):
    p = module.params
    username = p.get("username")

    if username is not None:
        users = users_by_username(client, username)
    else:
        search = p.get("search")
        users = client.paginate("/users", params={"search": search} if search else None)

    # Boolean filters are applied here rather than sent as query parameters:
    # the API contract does not document how booleans are serialized.
    if not p.get("include_service_accounts"):
        users = [user for user in users if not user.get("is_service_account")]
    for field in ("is_admin", "is_active"):
        if p.get(field) is not None:
            users = [user for user in users if user.get(field) == p[field]]

    user = users[0] if username is not None and len(users) == 1 else None
    module.exit_json(changed=False, users=users, user=user)


def main():
    module = make_module(
        {
            "username": {"type": "str", "no_log": False},
            "search": {"type": "str"},
            "is_admin": {"type": "bool"},
            "is_active": {"type": "bool"},
            "include_service_accounts": {"type": "bool", "default": False},
        },
        mutually_exclusive=[["username", "search"]],
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
