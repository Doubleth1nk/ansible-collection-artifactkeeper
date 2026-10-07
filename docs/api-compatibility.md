# Artifact Keeper API compatibility

`artifactkeeper.core` 0.2.0 is implemented against the Artifact Keeper API **1.10.1** OpenAPI contract and backend behavior reviewed on 2026-10-03.

The current API, not an older playbook or role, is authoritative for endpoint paths, schemas, authentication, status codes, and mutation semantics. The implementation intentionally keeps API-specific behavior in `plugins/module_utils/api.py` and resource normalization/reconciliation in the modules.

## Authentication

Management endpoints under `/api/v1` use Bearer authentication. The collection supports either an existing Artifact Keeper bearer token or administrator username/password credentials; username/password mode logs in at `/api/v1/auth/login` and uses the returned JWT for subsequent requests.

The 1.10.1 OpenAPI security schemes expose `basic_auth` and `bearer_auth`. Basic authentication is documented for package-manager endpoints, not management endpoints. No management `X-API-Key` security scheme is present in the current OpenAPI contract, so the collection does not expose an `api_key` module parameter.

## Projects

Projects are keyed resources. The collection looks them up by `key` and manages `name`, `description`, and `quota_bytes` where supplied. Current project create/update/delete responses are HTTP 200. `quota_bytes` is stored by the API; current API documentation states that enforcement is not yet implemented.

## Repositories

The current repository types are `local`, `remote`, `virtual`, and `staging`. Repository `format` and `repo_type` are treated as immutable after creation because the general repository update schema does not expose them. The general update API also does not expose `upstream_url`; changing it on an existing repository therefore fails with an actionable error rather than silently recreating data.

Remote upstream authentication supports `basic`, `bearer`, `aws_ecr`, `aws_codeartifact`, and `none`. AWS ECR/CodeArtifact settings are applied through the dedicated upstream-auth endpoint. Artifact Keeper uses its own runtime AWS credential provider chain; the collection does not accept AWS secret-access keys for this API operation.

Upstream passwords/tokens and some provider settings are write-only. They cannot be compared reliably after creation. The module avoids re-sending them on every run and provides `force_upstream_auth_update: true` for intentional rotation/reapplication.

## Service accounts

Artifact Keeper canonicalizes service-account usernames with a `svc-` prefix. The module accepts either `automation` or `svc-automation`, avoids double-prefixing, and resolves the canonical server username internally.

The API maps the creation-time service-account description to the account display name used by subsequent reads/updates. Service-account create currently returns HTTP 201.

## Service-account tokens

Token plaintext is returned only by the token-creation response. Subsequent token-list responses expose metadata such as token name/prefix, scopes, and timestamps, but not the secret value. The module therefore returns `token` only when a token is newly created.

Named token metadata is reconciled idempotently. Scopes are treated as immutable token metadata; changing them revokes and recreates the matching token. The original relative `expires_in_days` value and token creation description cannot be reconstructed reliably from later list responses, so the collection does not claim idempotent comparison for those creation-only inputs.

## Repository age gates

Artifact Keeper exposes age-gate configuration through `GET`/`PUT /api/v1/repositories/{key}/age-gate`, but the Ansible collection intentionally models that configuration as the nested `age_gate` option of `artifactkeeper.core.repository` rather than as a separate public module. This keeps one-to-one repository policy with the repository resource while still using the dedicated API endpoint internally.

The current request requires `enabled` and `min_age_days`; `mode` is optional and omission preserves the repository's current mode. The endpoint applies only to remote repositories. Artifact Keeper validates supported format/mode combinations when the gate is enabled, and the current backend requires administrator privileges to read or update age-gate policy. Omitting `age_gate` in Ansible leaves existing policy unmanaged; setting `age_gate.enabled: false` explicitly manages it as disabled.

## Project members

Project membership is resolved from human-readable project/principal identifiers to UUIDs. The current API represents principal types as user, service account, or group and provides an upsert-style project membership endpoint. The module reads current membership before writing so an unchanged grant reports `changed: false`.

## Repository permissions

Fine-grained repository grants are rows in the `/api/v1/permissions` collection with `target_type = repository`. The API documents that these rows, together with project grants, are what repository authorization resolves; role assignments made through `/api/v1/users/{id}/roles` do not grant repository access. Project grants are the same kind of row with `target_type = project` and remain owned by `artifactkeeper.core.project_member`, so `artifactkeeper.core.repository_permission` only ever reads or writes `target_type = repository` rows.

A grant is identified by repository, principal type, and principal. The module lists `/permissions` filtered by all four identity fields, re-checks those fields client-side, and fails if more than one row matches. `POST /permissions` returns HTTP 409 for an existing grant rather than upserting, so the module always looks up first, then creates with `POST` or updates with `PUT /permissions/{id}`. In the 1.10.1 contract, the `PUT` body is the same `CreatePermissionRequest` schema as `POST`, so updates send all five required fields (`principal_type`, `principal_id`, `target_type`, `target_id`, `actions`).

The contract gives no enumeration for `actions`, so action names are passed through unvalidated and compared as a set. User principals are resolved through `/users?search=` and service-account rows are excluded client-side using the `is_service_account` response field, because the contract does not document a wire format for boolean query parameters.

## Repository listing

`artifactkeeper.core.repository_info` uses `GET /repositories/{key}` for exact lookups and the paginated `GET /repositories` listing otherwise. The listing's `project` filter is typed as a project UUID, so the module resolves the supplied project key first. The module-facing `repo_type` and `search` options map to the API's `type` and `q` query parameters.

## Users

`artifactkeeper.core.user` identifies a user by its exact `username`. Lookups list `/users?search=<username>` and keep only rows whose `username` equals the input exactly, so an email address never matches. Service accounts are rows in `/users` as well; normal user lookups exclude rows with `is_service_account: true`. Creating a user whose username belongs to a service account fails with a pointer to `artifactkeeper.core.service_account`. More than one matching user fails instead of choosing one.

`UpdateUserRequest` has no username field, so usernames are immutable. The module never renames a user or recreates it under a new name. `CreateUserRequest` requires `email` and has no `is_active`, so `email` is required only on creation, and `is_active: false` on creation is applied with a follow-up `PATCH`. In `UpdateUserRequest`, `null` means unchanged, so `display_name` cannot be cleared once set. Managed fields are compared exactly as Artifact Keeper returns them, with no case folding.

`CreateUserRequest.password` is the only password operation the module uses. It is sent only when the user is created and is never compared, because no password material is returned. For an existing user, a supplied `password` is ignored with a warning. When no password is supplied, `CreateUserResponse.generated_password` may contain a server-generated password. The module returns it once as `generated_password`, so tasks should use `no_log: true`.

Changing or resetting the password of an existing user is intentionally out of scope. `POST /users/{id}/password` documents 401 (current password incorrect) and 403 (cannot change other users' passwords) responses. The contract does not state that an administrator can set another user's password through it, and `POST /users/{id}/password/reset` is a separate administrator operation that returns a temporary password and sets `must_change_password`. These need a dedicated, separately analysed module.

The client redacts the password fields of these schemas (`new_password`, `current_password`, `generated_password`, `temporary_password`) from API error text, alongside the existing credential keys.

`artifactkeeper.core.user_info` exposes the `search` query parameter. Its `is_admin`, `is_active`, and service-account filters are applied client-side to the returned rows, because the contract does not document how boolean query parameters are serialized.

## Groups

`artifactkeeper.core.group` identifies a group by its exact `name`, using `/groups?search=<name>` followed by exact matching. `POST /groups` returns HTTP 409 for an existing name, so the module always looks the group up first. `PUT /groups/{id}` takes the full `CreateGroupRequest`, in which `name` is required. The module only sends a PUT when `description` is supplied and differs, and always sends the current name back unchanged, so groups are never renamed and never deleted and recreated.

Membership is changed through `POST` and `DELETE /groups/{id}/members`, each with a batch of `user_ids`. There is no full-set replacement. The module reads the current members, computes the minimal additions and removals for `members_mode` (`exact`, `append`, or `remove`), and sends at most one add and one remove request. Members are read from `GET /groups/{id}` with `member_limit=200` (the documented maximum), following `member_offset` until `members_total` is reached or a page is empty. After membership writes, the group summary is re-read with `member_limit=1`, so the returned `member_count` is current. `member_limit=0` is avoided because its runtime meaning is undocumented.

Only usernames being added are resolved to user IDs, through exact username matching on `/users?search=`, so an email address never matches. Removals use the `user_id` values from the current membership. Service accounts are rows in `/users`, and the API describes the group member picker as using the listing that includes them, so the module accepts service accounts by their full `svc-` username.

`external_source` identifies groups owned by an SSO provider (`oidc`, `saml`, or `ldap`). The API states that the identity provider owns their membership, so supplying `members` for such a group fails before anything is changed, even when the membership already matches. The API does not restrict their description or deletion, so both are allowed. An identity provider that maps groups may recreate a deleted group at the next login. `CreateGroupRequest` has no `external_source`, so the module only creates local groups.

## Virtual repository members

The API's virtual-members `PUT` operation replaces the complete member set. `artifactkeeper.core.virtual_repository_members` therefore treats `members` as desired state: omitted existing members are removed, missing members are added, and priority changes are applied.

## Compatibility policy

0.2.0 claims compatibility with the API contract reviewed above. No older Artifact Keeper release range is claimed until integration coverage establishes one. Future collection releases should re-review the current `artifact-keeper/artifact-keeper-api` OpenAPI contract and backend implementation before changing behavior.
