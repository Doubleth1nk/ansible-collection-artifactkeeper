# artifactkeeper.core

`artifactkeeper.core` is an open-source Ansible collection for managing [Artifact Keeper](https://artifactkeeper.com/), the self-hosted artifact registry. It provides normal idempotent Ansible modules instead of requiring playbooks to hand-roll REST calls.

The collection manages projects, repositories (including repository age-gate policy), service accounts and their tokens, users, project and repository permission grants, and complete virtual-repository member sets, with read-only lookups for projects, repositories, users, and groups.

## API baseline

Version 0.2.0 is implemented against the **Artifact Keeper API 1.10.1 OpenAPI contract** as published by `artifact-keeper/artifact-keeper-api` on 2026-10-03. No older Artifact Keeper version range is claimed until integration coverage establishes one. See [docs/api-compatibility.md](docs/api-compatibility.md) for the API decisions that shape module behavior. The API evolves quickly, so CI and future collection releases should continue to validate against the current specification.

The current OpenAPI contract defines Bearer authentication for management endpoints. It does **not** define an `X-API-Key` management security scheme, even though an older/current repository README may mention that header. This collection follows the OpenAPI/backend contract and therefore does not expose an `api_key` parameter.

## Requirements

- `ansible-core >= 2.20.0`
- Python supported by the selected ansible-core release
- An Artifact Keeper deployment exposing the `/api/v1` management API
- No third-party Python HTTP library is required
- No HashiCorp Vault collection is required

The collection intentionally has no opinion about secret storage. Use Ansible Vault, HashiCorp Vault, 1Password, Kubernetes Secrets, GitHub Actions secrets, or another caller-managed mechanism as appropriate.

## Installation

```bash
ansible-galaxy collection install artifactkeeper.core
```

Or using [`examples/requirements.yml`](examples/requirements.yml):

```yaml
---
collections:
  - name: artifactkeeper.core
```

Then run:

```bash
ansible-galaxy collection install -r examples/requirements.yml
```

## Authentication

Every module accepts the same connection parameters:

- `api_url`
- `token`
- `username` + `password`
- `validate_certs` (default `true`)
- `ca_path`
- `timeout`

### Existing API/service-account token

```yaml
- name: Create project
  artifactkeeper.core.project:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: engineering
    name: Engineering
    state: present
```

### Administrator username/password

The shared client calls `/api/v1/auth/login`, receives the JWT, and uses it as a Bearer token for subsequent management requests.

```yaml
- name: Create project
  artifactkeeper.core.project:
    api_url: https://artifacts.example.com
    username: admin
    password: "{{ artifactkeeper_admin_password }}"
    key: engineering
    name: Engineering
    state: present
```

Credentials are declared with `no_log=True` in module argument specifications. For tasks that can return newly minted secrets, such as service-account tokens or a server-generated user password (`generated_password`), also use task-level `no_log: true`.

## TLS

Certificate verification is enabled by default. For an internal CA, prefer `ca_path` over disabling verification:

```yaml
- artifactkeeper.core.group_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    ca_path: /etc/pki/ca-trust/source/anchors/artifactkeeper-ca.pem
```

`validate_certs: false` is available for controlled development environments but is not recommended in production.

## Included modules

| Module | Purpose |
| --- | --- |
| `artifactkeeper.core.project` | Create/update/delete projects by key |
| `artifactkeeper.core.project_info` | Read-only exact/all project lookup |
| `artifactkeeper.core.repository` | Manage repository properties, upstream auth, and optional age-gate policy |
| `artifactkeeper.core.service_account` | Manage service-account lifecycle and active/display state |
| `artifactkeeper.core.service_account_token` | Create/revoke named service-account tokens; plaintext returned only on creation |
| `artifactkeeper.core.project_member` | Idempotently upsert/remove project grants for users, groups, or service accounts |
| `artifactkeeper.core.virtual_repository_members` | Replace the complete desired virtual member set, including priorities |
| `artifactkeeper.core.group_info` | Read-only exact/all group lookup |
| `artifactkeeper.core.repository_info` | Read-only exact or filtered repository lookup |
| `artifactkeeper.core.repository_permission` | Idempotently create/update/remove repository grants for users, groups, or service accounts |
| `artifactkeeper.core.user` | Create/update/delete users by exact username; password is create-only |
| `artifactkeeper.core.user_info` | Read-only exact or filtered user lookup |

All stateful modules support check mode. Modules with meaningful before/after state emit diff output when Ansible diff mode is enabled; secret fields are excluded from diffs.

## Examples

### Project

```yaml
- artifactkeeper.core.project:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: engineering
    name: Engineering
    description: Engineering artifacts
    quota_bytes: 107374182400
```

### Project lookup

```yaml
- artifactkeeper.core.project_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: engineering
  register: engineering_project
```

Omit `key` to return all projects. The module is read-only and always reports `changed: false`.

### Repository

```yaml
- artifactkeeper.core.repository:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    key: pypi-remote
    name: PyPI Remote
    format: pypi
    repo_type: remote
    upstream_url: https://pypi.org
    upstream_auth_type: none
    project_key: engineering
    is_public: false
    age_gate:
      enabled: true
      min_age_days: 7
      mode: upstream_publish_time
```

`format` and `repo_type` are not exposed as mutable fields by the current update API; a mismatch fails clearly instead of deleting/recreating data. The current general update schema also does not expose `upstream_url`, so changing that on an existing repository fails clearly. Upstream passwords/tokens are write-only. The module will not resend them on every run; set `force_upstream_auth_update: true` for intentional credential rotation.

`age_gate` is deliberately nested under the repository module even though Artifact Keeper exposes it through a dedicated endpoint. Omitting `age_gate` leaves any existing policy unmanaged; supplying `age_gate.enabled: false` explicitly disables the managed policy. The API requires `enabled` and `min_age_days`, while `mode` is optional and is preserved when omitted. Artifact Keeper restricts age-gate reads/updates to administrators and validates remote-repository format/mode compatibility server-side.

### Service account

```yaml
- artifactkeeper.core.service_account:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: ci
    description: Continuous integration
    is_active: true
```

Artifact Keeper creates usernames with a `svc-` prefix. The create schema calls the display text `description`, while the response/update schema calls it `display_name`; this module presents one `description` parameter and maps it appropriately.

### Service-account token

```yaml
- name: Create CI token
  artifactkeeper.core.service_account_token:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_admin_token }}"
    service_account: ci
    name: automation
    description: CI automation
    scopes:
      - read
      - write
    expires_in_days: 90
  no_log: true
  register: ci_token
```

The plaintext `token` return value exists only when the server mints a token. Store it immediately using your own secret-management workflow. Artifact Keeper's token-list response does not reveal plaintext and does not return the creation-time description; this collection does not falsely claim those values can be re-verified later. Scope changes rotate the named token because the current API has no token-update endpoint.

### Project member

```yaml
- artifactkeeper.core.project_member:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    project: engineering
    principal_type: group
    principal: engineers
    actions: [read, write]
    state: present
```

The module resolves project/group/user/service-account identifiers to UUIDs and reads the current grant before calling the API's upsert.

### Virtual repository members

```yaml
- artifactkeeper.core.virtual_repository_members:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: python
    members:
      - key: python-local
        priority: 10
      - key: pypi-remote
        priority: 20
```

The supplied list is the complete desired state. Removed members are removed and priority changes are detected.

### Group lookup

```yaml
- artifactkeeper.core.group_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    name: engineers
  register: engineers
```

### Repository permission

```yaml
- artifactkeeper.core.repository_permission:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    repository: python-local
    principal_type: group
    principal: engineers
    actions: [read, write]
    state: present
```

The grant is identified by repository, principal type, and principal; `actions` is the complete desired set. Grants on projects are managed by `project_member`. If more than one matching permission row exists, the module fails instead of choosing one.

### Repository lookup

```yaml
- artifactkeeper.core.repository_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    format: pypi
    repo_type: remote
    project: engineering
  register: engineering_pypi_remotes
```

Use `key` for an exact lookup, or any combination of `format`, `repo_type`, `search`, and `project` to filter the listing. The module is read-only and always reports `changed: false`.

### User

```yaml
- artifactkeeper.core.user:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    username: alice
    email: alice@example.com
    display_name: Alice
    password: "{{ alice_initial_password }}"
    state: present
  no_log: true
```

The user is identified by its exact `username`, which cannot be changed; an email address never matches it. Omitted optional fields are left unmanaged. `password` is only used when the user is created. For an existing user it is not sent or compared, and the module warns instead. Changing or resetting the password of an existing user is intentionally outside this module's scope. When `password` is omitted at creation, Artifact Keeper may generate one; it is returned once as `generated_password`, so use task-level `no_log: true`. Service accounts are managed by `service_account`.

### User lookup

```yaml
- artifactkeeper.core.user_info:
    api_url: https://artifacts.example.com
    token: "{{ artifactkeeper_token }}"
    is_admin: true
    is_active: true
  register: active_admins
```

Use `username` for an exact lookup or `search` for the server-side search. Service accounts are excluded unless `include_service_accounts: true`. The `is_admin`, `is_active`, and service-account filters are applied by the module to the returned users. The module is read-only and always reports `changed: false`.

## Idempotency model

Stateful modules follow the same pattern:

1. Read the existing server state using a stable key/UUID relationship.
2. Normalize list/set-like values where needed.
3. Compare only fields the module manages and can observe.
4. Skip POST/PUT/PATCH/DELETE when nothing differs.
5. In check mode, perform reads and report the change that would occur without modifying the server.

Write-only secrets are treated specially: the collection never fabricates an equality comparison for data the API does not return. Remote repositories also support the current AWS ECR and AWS CodeArtifact upstream-auth configuration; provider settings are sent to Artifact Keeper while AWS credentials remain a server-side concern.

A complete playbook exercising all twelve modules is available at [`examples/all-modules.yml`](examples/all-modules.yml).

## Development and testing

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m compileall plugins tests
ansible-test sanity --python 3.13
ansible-test units --venv --python 3.13
ansible-lint
ansible-galaxy collection build --force
```

CI tests ansible-core 2.20 and 2.21 on pull requests and pushes to `main`. A scheduled job also exercises ansible-core `devel` so upcoming breakage is visible before the next release.

Integration scaffolding lives under `tests/integration/targets/artifactkeeper_smoke` and is intentionally not part of normal unit/sanity CI because it needs a live Artifact Keeper instance and administrator credentials.

## Versioning and releases

This collection uses semantic versioning. Until 1.0, backwards-incompatible changes remain possible but should be documented prominently. Releases should be reproducible from the exact Git tag and the same source should be used for GitHub and Ansible Galaxy.

Release procedure:

1. Update `galaxy.yml` `version` and the `User-Agent` version in `plugins/module_utils/api.py`.
2. Add a `release_summary` fragment and run `antsibull-changelog release --version X.Y.Z` to generate `CHANGELOG.rst` from `changelogs/fragments/`.
3. Run all sanity/unit/lint checks.
4. `ansible-galaxy collection build`.
5. Install and inspect the built tarball locally.
6. Tag the exact source commit (`vX.Y.Z`).
7. Create the GitHub release and attach the tarball.
8. Publish that tarball to Galaxy using a GitHub Actions secret named `ANSIBLE_GALAXY_API_TOKEN`.

The release workflow only publishes from an intentional `v*` tag in the
official Artifact Keeper repository. No Galaxy token belongs in this repository.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). New resource modules should reuse `plugins/module_utils/api.py` and `plugins/module_utils/common.py` instead of copying authentication, TLS, pagination, errors, or lookup behavior.

## License

GPL-3.0-or-later. Python module/plugin files include SPDX identifiers.
