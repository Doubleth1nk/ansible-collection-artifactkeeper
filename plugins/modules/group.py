#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r'''
---
module: group
short_description: Manage Artifact Keeper groups and their membership
version_added: "0.3.0"
description:
  - Creates, updates, and deletes local Artifact Keeper groups, and manages their membership.
  - The group is identified by its exact O(name). Groups are never renamed or recreated.
  - Omitted optional fields are left unmanaged. When O(members) is omitted, membership is not read or changed.
  - Membership changes are applied as the minimal set of additions and removals.
author:
  - Tuxthepirate (@Doubleth1nk)
extends_documentation_fragment:
  - artifactkeeper.core.artifactkeeper
options:
  name:
    description:
      - Exact group name. This is the stable identity of the group and is never changed.
    type: str
    required: true
  description:
    description:
      - Group description. Managed when supplied.
      - An empty string and no description are treated as equal.
    type: str
  members:
    description:
      - Usernames to manage according to O(members_mode).
      - Usernames are matched exactly. An email address never matches a username.
      - Service accounts can be members and are given by their full username, for example C(svc-ci).
      - When omitted, group membership is unmanaged.
      - Must not be supplied for groups managed by an identity provider, see the notes.
    type: list
    elements: str
  members_mode:
    description:
      - How O(members) is applied.
      - V(exact) makes O(members) the complete membership, adding missing users and removing all others. An empty list removes every member.
      - V(append) adds missing users and never removes members.
      - V(remove) removes the listed users if they are members. Listed users that are not members, or do not exist, are ignored.
    type: str
    choices: [exact, append, remove]
    default: exact
  state:
    description:
      - Whether the group should exist.
      - O(description) and O(members) are ignored when O(state=absent).
    type: str
    choices: [present, absent]
    default: present
notes:
  - Groups whose C(external_source) is set are owned by an SSO provider (OIDC, SAML, or LDAP), which owns their membership.
    Supplying O(members) for such a group fails without changing anything, even if the membership already matches.
    Their description can be changed and they can be deleted, but an identity provider that maps its groups may recreate a deleted group at the next login.
  - Groups created by this module are local groups. Externally managed groups cannot be created with this module.
'''

EXAMPLES = r'''
- name: Create a group with an exact membership
  artifactkeeper.core.group:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: engineers
    description: Engineering team
    members:
      - alice
      - bob
      - svc-ci

- name: Add a member without removing others
  artifactkeeper.core.group:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: engineers
    members: [carol]
    members_mode: append

- name: Remove a member
  artifactkeeper.core.group:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: engineers
    members: [bob]
    members_mode: remove

- name: Delete a group
  artifactkeeper.core.group:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: contractors
    state: absent
'''

RETURN = r'''
group:
  description:
    - Group after the change, or C(null) when the group is absent.
    - In check mode this is the predicted group.
  returned: always
  type: dict
  contains:
    id:
      description: Artifact Keeper group UUID.
      type: str
      returned: when the group exists on the server
    name:
      description: Group name.
      type: str
      returned: always
    description:
      description: Group description.
      type: str
      returned: when set
    external_source:
      description: Identity provider that owns the group membership, or C(null) for local groups.
      type: str
      returned: when the group exists on the server
    member_count:
      description: Number of members.
      type: int
      returned: when the group exists on the server
members:
  description: Sorted usernames of the resulting membership.
  returned: when O(members) is supplied and O(state=present)
  type: list
  elements: str
members_added:
  description: Sorted usernames that were (or in check mode would be) added.
  returned: when O(members) is supplied and O(state=present)
  type: list
  elements: str
members_removed:
  description: Sorted usernames that were (or in check mode would be) removed.
  returned: when O(members) is supplied and O(state=present)
  type: list
  elements: str
changed_fields:
  description: Managed fields that differed from the server state.
  returned: always
  type: list
  elements: str
'''

from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    client_from_module,
    fail_from_exception,
    group_by_name,
    group_members,
    make_module,
    q,
    users_by_username,
)


def _same_description(current, desired):
    return (current or None) == (desired or None)


def _desired_members(module, p):
    members = p.get("members")
    if members is None:
        return None
    if any(not member for member in members):
        module.fail_json(msg="members must not contain empty usernames")
    return set(members)


def _resolve_user_ids(module, client, usernames):
    """Map each username to its user UUID. Service accounts are users too."""
    ids = {}
    for username in usernames:
        rows = users_by_username(client, username)
        if not rows:
            module.fail_json(msg="user '%s' was not found" % username)
        if len(rows) > 1:
            module.fail_json(msg="username '%s' is ambiguous" % username)
        ids[username] = rows[0]["id"]
    return ids


def _membership_plan(mode, desired, current):
    if mode == "exact":
        return sorted(desired - current), sorted(current - desired)
    if mode == "append":
        return sorted(desired - current), []
    return [], sorted(desired & current)


def _refresh(client, group_id):
    # member_limit=1 keeps the read small; only the group summary is used.
    detail = client.get("/groups/%s" % q(group_id), params={"member_limit": 1, "member_offset": 0}) or {}
    return {key: value for key, value in detail.items() if key not in ("members", "members_total")}


def _add_members(client, group_id, user_ids):
    client.post("/groups/%s/members" % q(group_id), data={"user_ids": user_ids}, expected=(200,))


def _create(module, client, p, desired_members):
    to_add = sorted(desired_members) if desired_members and p["members_mode"] != "remove" else []
    ids = _resolve_user_ids(module, client, to_add)

    payload = {"name": p["name"]}
    if p.get("description") is not None:
        payload["description"] = p["description"]
    changed_fields = ["name"] + (["description"] if "description" in payload else []) + (["members"] if to_add else [])

    result = {"changed": True, "group": dict(payload), "changed_fields": changed_fields}
    if desired_members is not None:
        result.update(members=to_add, members_added=to_add, members_removed=[])
    if getattr(module, "_diff", False):
        after = dict(payload)
        if desired_members is not None:
            after["members"] = to_add
        result["diff"] = {"before": {}, "after": after}
    if module.check_mode:
        module.exit_json(**result)

    group = client.post("/groups", data=payload, expected=(200,))
    if to_add:
        _add_members(client, group["id"], [ids[username] for username in to_add])
        group = _refresh(client, group["id"])
    result["group"] = group
    module.exit_json(**result)


def run_module(module, client):
    p = module.params
    existing = group_by_name(client, p["name"])

    if p["state"] == "absent":
        if not existing:
            module.exit_json(changed=False, group=None, changed_fields=[])
        result = {"changed": True, "group": existing, "changed_fields": ["group"]}
        if getattr(module, "_diff", False):
            result["diff"] = {
                "before": {"name": existing.get("name"), "description": existing.get("description")},
                "after": {},
            }
        if module.check_mode:
            module.exit_json(**result)
        client.delete("/groups/%s" % q(existing["id"]), expected=(200,))
        result["group"] = None
        module.exit_json(**result)

    desired_members = _desired_members(module, p)
    if not existing:
        _create(module, client, p, desired_members)

    if desired_members is not None and existing.get("external_source"):
        module.fail_json(
            msg="group '%s' is managed by '%s'; its membership is owned by the identity provider "
            "and cannot be managed with members" % (p["name"], existing["external_source"])
        )

    changed_fields = []
    before = {}
    after = {}
    if p.get("description") is not None:
        before["description"] = existing.get("description")
        after["description"] = p["description"]
        if not _same_description(existing.get("description"), p["description"]):
            changed_fields.append("description")

    membership = {}
    to_add, to_remove, ids, current = [], [], {}, {}
    if desired_members is not None:
        current = {member["username"]: member for member in group_members(client, existing["id"])}
        to_add, to_remove = _membership_plan(p["members_mode"], desired_members, set(current))
        ids = _resolve_user_ids(module, client, to_add)
        final = sorted((set(current) | set(to_add)) - set(to_remove))
        before["members"] = sorted(current)
        after["members"] = final
        if to_add or to_remove:
            changed_fields.append("members")
        membership = {"members": final, "members_added": to_add, "members_removed": to_remove}

    if not changed_fields:
        module.exit_json(changed=False, group=existing, changed_fields=[], **membership)

    group = existing
    if "description" in changed_fields:
        group = {**existing, "description": p["description"]}
    result = {"changed": True, "group": group, "changed_fields": changed_fields}
    result.update(membership)
    if getattr(module, "_diff", False):
        result["diff"] = {"before": before, "after": after}
    if module.check_mode:
        module.exit_json(**result)

    if "description" in changed_fields:
        # PUT replaces the group, so the current name is always sent back unchanged.
        group = client.put(
            "/groups/%s" % q(existing["id"]),
            data={"name": existing["name"], "description": p["description"]},
            expected=(200,),
        )
    if to_add:
        _add_members(client, existing["id"], [ids[username] for username in to_add])
    if to_remove:
        client.delete(
            "/groups/%s/members" % q(existing["id"]),
            data={"user_ids": [current[username]["user_id"] for username in to_remove]},
            expected=(200,),
        )
    if to_add or to_remove:
        group = _refresh(client, existing["id"])
    result["group"] = group
    module.exit_json(**result)


def main():
    module = make_module(
        {
            "name": {"type": "str", "required": True},
            "description": {"type": "str"},
            "members": {"type": "list", "elements": "str"},
            "members_mode": {"type": "str", "choices": ["exact", "append", "remove"], "default": "exact"},
            "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
        }
    )
    try:
        run_module(module, client_from_module(module))
    except Exception as exc:
        fail_from_exception(module, exc)


if __name__ == "__main__":
    main()
