# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`artifactkeeper.core`: an Ansible collection (modules only, no roles or other plugin types) that idempotently manages an Artifact Keeper artifact registry through its `/api/v1` REST API. It targets ansible-core >= 2.20 and has no third-party Python dependencies.

## Collection path requirement

Imports use the `ansible_collections.artifactkeeper.core.*` namespace, so tooling only works when the checkout sits at `.../ansible_collections/artifactkeeper/core/`. CI does this with `actions/checkout` `path:`. If the working copy is elsewhere, symlink it into such a path and run commands from there. `tests/unit/conftest.py` imports `helpers` through the namespace before its own namespace shim runs, so plain pytest from a non-canonical path fails with `No module named 'ansible_collections'`.

## Commands

Run these from the canonical collection path (Python 3.13 in CI):

```bash
pip install -r requirements-dev.txt
python -m compileall -q plugins tests
ansible-test sanity --python 3.13
ansible-test units --venv --python 3.13
ansible-test units --venv --python 3.13 tests/unit/plugins/modules/test_project.py   # one file
ansible-lint
ansible-galaxy collection build --force
```

Fast single-test loop with plain pytest. This works even without ansible-core installed, because `conftest.py` stubs `ansible.module_utils`:

```bash
PYTHONPATH=<dir containing ansible_collections> python -m pytest tests/unit/plugins/modules/test_project.py::test_update
```

CI also builds and installs the tarball, then runs `ansible-doc -t module artifactkeeper.core.<name>` for every module. **A new module must be added to the module loops in both `.github/workflows/ansible-test.yml` and `release.yml`.**

The live integration target (`tests/integration/targets/artifactkeeper_smoke`, marked `destructive`) needs a real instance:
`ansible-test integration artifactkeeper_smoke --allow-destructive --extra-vars 'artifactkeeper_test_url=... artifactkeeper_test_token=...'`

## Architecture

There are three layers. New modules must reuse the bottom two rather than reimplementing auth, TLS, pagination, errors or lookups.

- **`plugins/module_utils/api.py`**: `ArtifactKeeperClient`, a JSON client over `ansible.module_utils.urls.open_url`. Do not add `requests`. The client:
  - appends `/api/v1` to `api_url`
  - with username/password, logs in lazily via `POST /auth/login` and uses the returned JWT as a Bearer token
  - drops `Authorization` on redirects
  - provides `paginate()` (`items` and `pagination.total_pages`)
  - raises `ArtifactKeeperError` / `ArtifactKeeperHTTPError` / `ArtifactKeeperNotFound`
  - redacts secret values and `SENSITIVE_KEYS` from all error text

  The constructor takes an `opener` so tests can inject a fake HTTP layer.
- **`plugins/module_utils/common.py`**:
  - `make_module()` merges the shared connection argspec. It always sets `supports_check_mode=True` and enforces `token` XOR `username`+`password`.
  - `client_from_module()` and `fail_from_exception()`
  - Name→object lookups (`project_by_key`, `repository_by_key`, `service_account_by_name`, `group_by_name`, `user_by_identifier`, `principal_by_identifier`)
  - `managed_diff()` / `safe_diff()`
- **`plugins/doc_fragments/artifactkeeper.py`**: shared connection-option docs. Modules use `extends_documentation_fragment: artifactkeeper.core.artifactkeeper`.

### Module pattern

Every module splits into `run_module(module, client)` (all logic) and a thin `main()` (`make_module` → `run_module(module, client_from_module(module))` → `fail_from_exception`). Unit tests call `run_module` directly with `tests/unit/helpers.py`:
- `FakeModule` makes `exit_json`/`fail_json` raise `ModuleExit`/`ModuleFail`.
- `RecordingClient` replays queued responses and records `(method, path, kwargs)` in `.calls`.
- Lookup helpers are monkeypatched on the module object.
- The `invoke` fixture in `conftest.py` returns the `exit_json` kwargs.

Idempotency contract for stateful modules:
1. Read current state by a stable key or UUID.
2. Normalise list- and set-like values.
3. Compare only fields the module manages *and* the API returns.
4. Skip writes when nothing differs.
5. In check mode, do reads only and report the would-be result.
6. Emit `diff` only when `module._diff` is set.
7. Return `changed_fields`.

### API-driven design decisions

These are non-obvious; see `docs/api-compatibility.md`.

- The OpenAPI contract (Artifact Keeper **1.10.1**) is authoritative over older roles and READMEs. There is deliberately no `api_key` / `X-API-Key` parameter. When the API changes, update behaviour against the current `artifact-keeper/artifact-keeper-api` `openapi.yaml` and do not preserve stale behaviour. A local copy of the spec may exist at the repo root as `artifact-keeper-1.10.1-openapi.json`. It is untracked and not in `build_ignore`; don't commit it or let it into a build.
- **Write-only secrets** (upstream passwords and tokens, token plaintext) are never compared or resent each run. `repository` re-sends them only with `force_upstream_auth_update: true`. `service_account_token` returns `token` only on creation, and a scope change revokes and recreates the token because no update endpoint exists. Mark secret-returning params `no_log` and exclude secrets from diffs.
- **Immutable fields:** `repository` `format`/`repo_type`/`upstream_url` mismatches fail clearly. Never delete and recreate.
- **`age_gate`** is a nested option of `repository` but uses the dedicated `/repositories/{key}/age-gate` endpoint. If the option is omitted, the policy stays unmanaged; `enabled: false` disables it explicitly.
- **Service accounts:** the server prefixes usernames with `svc-`. The module accepts either form. Its `description` param maps to `description` on create and to `display_name` on read and update.
- `virtual_repository_members` treats `members` as the complete desired set because the API `PUT` replaces the whole set.
- `project_member` resolves names to UUIDs and reads the existing grant before the API's upsert.

## Conventions

- Every Python file carries `# SPDX-License-Identifier: GPL-3.0-or-later`. Modules include `version_added` in `DOCUMENTATION` along with `EXAMPLES` and `RETURN`.
- Add a changelog fragment under `changelogs/fragments/` (antsibull-changelog sections in `changelogs/config.yaml`) for user-visible changes.
- Modules stay free of secret-store coupling (no Vault/1Password lookups).
- Releases: bump `galaxy.yml` `version` (the `v*` tag must match it, and `release.yml` checks this). Also update the hardcoded `User-Agent` version in `api.py`.
