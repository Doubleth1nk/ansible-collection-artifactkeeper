# Artifact Keeper API compatibility

`artifactkeeper.core` 0.3.0 (the current source) targets the Artifact Keeper API **1.10.2** contract. The 0.2.0 collection release was implemented against the 1.10.1 OpenAPI contract and backend behavior reviewed on 2026-10-03.

The current API, not an older playbook or role, is authoritative for endpoint paths, schemas, authentication, status codes, and mutation semantics. The implementation intentionally keeps API-specific behavior in `plugins/module_utils/api.py` and resource normalization/reconciliation in the modules.

## API baseline and provenance

Artifact Keeper 1.10.2 is a security patch release. Upstream did not publish a 1.10.2 OpenAPI document: the `artifact-keeper-api` repository stops at `v1.10.1`, and the release job that exports and publishes the spec timed out for the `v1.10.2` tag. The 1.10.2 document used for this compatibility review was therefore regenerated from the signed `v1.10.2` release tag (commit `8e9f533`) with upstream's own export procedure (`cargo test --lib export_openapi_spec -- --ignored` with `SQLX_OFFLINE=true` and `EXPORT_OPENAPI_SPEC=1`). The procedure was validated by regenerating 1.10.1 the same way, which reproduced the published 1.10.1 `openapi.json` semantically.

Compared with 1.10.1, the 1.10.2 contract has the same 471 operations and 505 schemas. Every operation and transitively referenced schema used by the collection is unchanged, except `POST /api/v1/service-accounts/{id}/tokens`, whose `CreateTokenRequest` now sets `additionalProperties: false` and which documents new `400` and `403` responses. The payload sent by `artifactkeeper.core.service_account_token` already complies (see "Service-account tokens"). Behavior changes that the OpenAPI document does not express, such as token scope requirements and listing visibility, are described in "API token scopes" below.

## Authentication

Management endpoints under `/api/v1` use Bearer authentication. The collection supports either an existing Artifact Keeper bearer token or administrator username/password credentials; username/password mode logs in at `/api/v1/auth/login` and uses the returned JWT for subsequent requests.

The OpenAPI security schemes (unchanged in 1.10.2) expose `basic_auth` and `bearer_auth`. Basic authentication is documented for package-manager endpoints, not management endpoints. No management `X-API-Key` security scheme is present in the current OpenAPI contract, so the collection does not expose an `api_key` module parameter.

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

Named token metadata is reconciled idempotently. Scopes and repository restrictions are immutable token metadata, so a difference in either rotates the matching token. The original relative `expires_in_days` value and token creation description cannot be reconstructed reliably from later list responses, so the collection does not claim idempotent comparison for those creation-only inputs.

Artifact Keeper 1.10.2 made token creation stricter on every token-mint endpoint:

- Unknown request fields are rejected with HTTP 400 instead of being ignored, and malformed bodies return 400 instead of 422. The module sends only `name`, `scopes`, and, when supplied, `description`, `expires_in_days`, and one of `repository_ids` or `repo_selector`. Unit tests pin this payload against the 1.10.2 `CreateTokenRequest`.
- `repository_ids: []` is rejected with HTTP 400, because an empty list would otherwise store no restriction and produce an unrestricted token. A `repo_selector` that does not restrict is rejected the same way.
- A repository-restricted calling credential imposes a repository ceiling: the new token inherits the caller's repository restriction, the caller may not name its own `repository_ids` or `repo_selector` for it (HTTP 403), and a restricted caller whose restriction matches no repository cannot mint at all (HTTP 403).

### Repository restrictions

`repositories` takes repository keys. The module resolves each key with `GET /repositories/{key}` and sends the IDs as `repository_ids`. An unknown key, an empty list, or an empty key fails before anything is changed, including in check mode. `repo_selector` is sent as the API's `repo_selector` with `match_labels`, `match_formats`, and `match_pattern`; `match_repos` is not offered, because `repositories` covers explicit repositories by key. The two options are mutually exclusive, as in the API. When neither is supplied, the restriction is unmanaged: it is neither sent nor compared, which keeps tokens that inherited a restriction from a restricted credential from being rotated on every run.

The selector rules mirror the 1.10.2 backend exactly (`validate_token_repo_selector`: a strict parse followed by an emptiness check), without adding stronger ones. A selector is rejected when it has no effective criterion (`match_labels` empty or missing, `match_formats` empty or missing, and `match_pattern` missing or null) or a non-string label value. `match_pattern` is sent whenever it is set, including an empty string, which is a valid pattern that matches no repository; `*` matches every repository, and patterns are not trimmed. Empty `match_labels` or `match_formats` are left out, which the server treats identically.

The token-list response exposes `repository_ids` (rows in the server's join table) and the stored `repo_selector`, so a managed restriction is compared against them. Explicit IDs are compared as sets and require no stored selector. A selector is compared after normalizing only what the server treats as equivalent (order and duplicates in `match_formats`, and empty versus missing criteria), and a stored selector with `match_repos` or an unknown key never compares equal. The server's `repository_restricted` marker is not exposed. A token pinned to repositories that have all since been deleted therefore lists as `repository_ids: []` with no selector, which looks unrestricted although the server denies it everything. Because a managed `repositories` list is never empty, that state always compares as different and is rotated to the desired restriction; it is never reported as unchanged.

The module cannot tell whether the credential it authenticates with is repository-restricted, because no API exposes that. If it is, Artifact Keeper rejects a supplied `repositories` or `repo_selector` with HTTP 403 before creating anything, and the module reports that error. Check mode cannot predict this 403.

### Rotation

A rotation creates the replacement token first and revokes the old token afterwards. The API allows tokens with the same name, so a failed creation, for example the 403 above, leaves the existing token untouched. If revoking the old token then fails, the module revokes the replacement again and fails, leaving the original token in place. If that rollback also fails, the module fails with both token IDs (`previous_token_id`, `replacement_token_id`) and warns that two live tokens may now exist. In either case the new plaintext token is not returned. Diffs show repositories by key; existing repository IDs whose key is not already known from resolving the requested keys are shown as `<unresolved repository #N>` placeholders instead of IDs, and diff mode makes no additional API requests.

The upstream 1.10.2 security advisory ([GHSA-qh2h-m7hp-27pc](https://github.com/artifact-keeper/artifact-keeper/security/advisories/GHSA-qh2h-m7hp-27pc)) notes that tokens minted through a repository-restricted credential before 1.10.2 may be unrestricted, and that this is not recorded anywhere. When the restriction is unmanaged, the module treats an existing token with the same name and scopes as up to date and does not detect such tokens. The advisory recommends reviewing and rotating them: manage the intended restriction with `repositories` or `repo_selector`, or rotate the token by running the module with `state: absent` and then `state: present`.

## API token scopes

Scopes on the credential the collection authenticates with limit what the modules can do. Username/password sessions are not limited by scopes. In 1.10.2, repository management (create and update, upstream authentication, virtual members, cache, routing, and similar settings) requires the `write:repositories` scope, and deleting a repository requires `delete:repositories`. A bare `write`/`delete` scope and `admin`/`*` tokens still satisfy these. Before 1.10.2, these calls were accepted only from sessions and `admin`/`*` tokens, so nothing that worked before is refused.

From 1.10.2, an administrator presenting a token restricted to some repositories is confined to those repositories in the repository listing as well. `artifactkeeper.core.repository_info` listings therefore return only those repositories. Exact repository lookups by key were already confined in 1.10.1. Use an unrestricted credential for instance-wide management.

## Repository age gates

Artifact Keeper exposes age-gate configuration through `GET`/`PUT /api/v1/repositories/{key}/age-gate`, but the Ansible collection intentionally models that configuration as the nested `age_gate` option of `artifactkeeper.core.repository` rather than as a separate public module. This keeps one-to-one repository policy with the repository resource while still using the dedicated API endpoint internally.

The current request requires `enabled` and `min_age_days`; `mode` is optional and omission preserves the repository's current mode. The endpoint applies only to remote repositories. Artifact Keeper validates supported format/mode combinations when the gate is enabled, and the current backend requires administrator privileges to read or update age-gate policy. Omitting `age_gate` in Ansible leaves existing policy unmanaged; setting `age_gate.enabled: false` explicitly manages it as disabled.

## Project members

Project membership is resolved from human-readable project/principal identifiers to UUIDs. The current API represents principal types as user, service account, or group and provides an upsert-style project membership endpoint. The module reads current membership before writing so an unchanged grant reports `changed: false`.

## Repository permissions

Fine-grained repository grants are rows in the `/api/v1/permissions` collection with `target_type = repository`. The API documents that these rows, together with project grants, are what repository authorization resolves; role assignments made through `/api/v1/users/{id}/roles` do not grant repository access. Project grants are the same kind of row with `target_type = project` and remain owned by `artifactkeeper.core.project_member`, so `artifactkeeper.core.repository_permission` only ever reads or writes `target_type = repository` rows.

A grant is identified by repository, principal type, and principal. The module lists `/permissions` filtered by all four identity fields, re-checks those fields client-side, and fails if more than one row matches. `POST /permissions` returns HTTP 409 for an existing grant rather than upserting, so the module always looks up first, then creates with `POST` or updates with `PUT /permissions/{id}`. In the contract (1.10.1 and 1.10.2), the `PUT` body is the same `CreatePermissionRequest` schema as `POST`, so updates send all five required fields (`principal_type`, `principal_id`, `target_type`, `target_id`, `actions`).

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

## Repository labels

`artifactkeeper.core.repository_labels` manages `/api/v1/repositories/{key}/labels`. `GET` returns every label of the repository (unpaginated, ordered by key), so the module always compares against the complete current state. Keys are compared exactly and case-sensitively, and a missing `value` reads back as an empty string.

With `labels_mode: exact`, the module sends one `PUT` with the full desired set; the server replaces the labels in a single transaction, so the change is atomic. `labels` must be supplied explicitly in this mode, so omitting it can never clear the labels; `labels: {}` is the explicit way to remove them all. With `labels_mode: merge`, the module computes the whole change set first, then sends `POST /labels/{label_key}` (an upsert) for each addition and update in key order, followed by `DELETE /labels/{label_key}` for each removal in key order. These requests are not atomic: if one fails, the earlier ones remain applied, and the next run re-reads the labels and sends only what is left. Merge mode never uses `PUT`, so labels added by others between the read and the write are not dropped.

The server does not validate label requests; its `repository_labels` table limits keys to 128 and values to 256 characters and allows each key only once per repository, and violations surface as database errors. The module therefore rejects over-long keys or values, non-string values, and duplicate or overlapping keys before any request. It also rejects empty keys, which the table would accept but which cannot be addressed through the `{label_key}` path for merge updates or removals. Reads require visibility of the repository and writes require write access to it. Every label change makes the server re-evaluate sync policies.

## Repository scan configuration

`artifactkeeper.core.repository_scan_config` manages `GET` and `PUT /api/v1/repositories/{key}/security`. The `GET` returns `RepoSecurityResponse`, whose `config` is the stored `ScanConfigResponse` or `null` and whose `score` is a computed security score. Only the six settings in `config` are managed (`scan_enabled`, `scan_on_upload`, `scan_on_proxy`, `block_on_policy_violation`, `severity_threshold`, `proxy_scan_action`); the score, IDs, and timestamps are never compared.

A repository has no stored scan configuration until the first `PUT`; repository creation does not create one. Every enforcement path in the 1.10.2 backend treats a missing configuration exactly like one with the defaults (all four flags `false`, `severity_threshold: high`, `proxy_scan_action: fail_open`), which are also the values a first `PUT` fills in for omitted fields. The module therefore compares against these defaults when `config` is `null`, and a request that only names default values sends nothing, so no configuration is created and `configured` stays `false`. There is no `DELETE`: once stored, a configuration can be reset to the defaults but not removed, so the module has no `state` option.

`UpsertScanConfigRequest` makes every field optional, and the server merges the request over the stored configuration (or the defaults). An omitted field and an explicit `null` both keep the current value, so `null` cannot reset a field. The module sends exactly the managed fields that differ and never an empty body: a `PUT {}` is accepted, but it would create a configuration that changes no behavior, and every `PUT` updates `updated_at`. The server's read-merge-write is not atomic, so concurrent writers can overwrite each other's changes; the next run re-reads and converges.

The OpenAPI document gives both string fields as free text. The 1.10.2 backend accepts `severity_threshold` case-insensitively with aliases (`moderate`, `informational`, `none`), stores the canonical lowercase value, and rejects other values with HTTP 400. It does not reject an unknown `proxy_scan_action`: the value is trimmed and lowercased, and anything other than `fail_closed` is stored as `fail_open`. The module accepts only the canonical stored values (`critical`, `high`, `medium`, `low`, `info` and `fail_open`, `fail_closed`), so runs converge and a mistyped action cannot silently weaken the gate.

Reading the configuration requires visibility of the repository; a missing repository, one the credential cannot see, and one outside a repository-scoped token's restriction all return 404, so the module's error does not claim which applies. Changing it requires tenant access to the repository and then the repository `admin` action (a `permissions` grant on the repository or its project, to the principal directly or through a group) or a global administrator; a `write` grant is not sufficient. The 1.10.2 handler does not additionally check a token scope such as `write:repositories`; the module does not depend on that and documents the repository `admin` requirement only.

The settings are stored for every repository type and format, without a backend guard. `scan_enabled` gates scanning, and `scan_on_upload` takes effect only together with it. The proxy settings apply on proxy serve paths: remote repositories directly, and virtual repositories by combining their own settings with each member's, the stricter winning. `severity_threshold` only takes effect with `block_on_policy_violation: true`. A change only writes the configuration: it does not trigger scans or rescan existing artifacts, but the serve-time gates read it on every request, so it applies from the next upload or pull, including pulls of already cached content.

The configuration is managed by a standalone module rather than a nested `repository` option like `age_gate`, because it applies to every repository type, has its own authorization and "not configured" state, and is often owned separately from the repository definition, so it should be manageable without restating the repository's creation fields.

## Security policies

`artifactkeeper.core.security_policy` manages `GET` and `POST /api/v1/security/policies` and `GET`, `PUT`, and `DELETE /api/v1/security/policies/{id}`. These are the only policy routes in 1.10.2; there is no separate enable, disable, or toggle endpoint. The OpenAPI paths and schemas are identical in 1.10.1 and 1.10.2. Behavior the OpenAPI document does not express was read from the backend at the `v1.10.2` tag, commit `8e9f53346d4ec4929a19a06392c06562c2dfaa75` (`backend/src/api/handlers/security.rs`, `backend/src/services/policy_service.rs`, and migrations `022`, `055`, and `121`).

The list endpoint returns a bare array of `PolicyResponse` with no pagination or filters, ordered by creation time and including disabled policies. Policies are identified by UUID only: the `scan_policies` table has no unique constraint on `name`, so the server accepts several policies with the same name. The module treats `name` as its identity and fails as ambiguous, for `state: present` and `state: absent` alike, when more than one policy carries the requested name; it never chooses one.

`repository_id` is set when a policy is created and cannot be changed: `UpdatePolicyRequest` has no `repository_id` field and the update statement does not touch the column. A policy with `repository_id: null` is global. The module takes a repository key, resolves it to the UUID, and fails when the named policy exists with a different scope (global versus a repository, or another repository), explaining that Artifact Keeper 1.10.2 cannot change the scope. Moving a policy requires the user to remove it and create it again; the module never creates a second policy or deletes and recreates one on its own. The foreign key uses `ON DELETE CASCADE`, so deleting a repository deletes the policies scoped to it rather than turning them into global policies.

`CreatePolicyRequest` requires `name`, `max_severity`, and `block_on_fail`. When omitted, `block_unscanned` defaults to `true` and `require_signature` to `false`, and `min_staging_hours` and `max_artifact_age_days` stay `null`. Creation does not accept `is_enabled`: every new policy is enabled. `UpdatePolicyRequest` makes every field optional and the server applies `COALESCE` per column, so an omitted field and an explicit `null` both keep the stored value. `is_enabled` is set through this `PUT`; for `enabled: false` on a new policy the module therefore creates the policy and disables it with a second request, and the policy is enforced for the short time between the two. If that second request fails, the module fails with `changed: true`, names the created policy's ID, and states that the policy remains enabled; it does not delete the policy again. Because `null` cannot clear `min_staging_hours` or `max_artifact_age_days`, a value once set can only be removed by deleting and recreating the policy. The module manages these fields only when they are supplied and never sends, predicts, or diffs a clear. Every `PUT` updates `updated_at`, even an empty one, so the module sends only the supplied settings that differ and nothing when none do.

The backend trims and lowercases `max_severity` and accepts only `critical`, `high`, `medium`, and `low` on create and update (anything else, including `info`, is HTTP 400); the stored value is always lowercase. The module offers exactly these values. `name` is a `VARCHAR(255)` that the server does not validate: an empty name is accepted and an over-long one fails as a database error, so the module rejects an empty name and names over 255 characters before any request; it does not trim names. The integer fields are 32-bit and have no range check, so the module accepts any 32-bit value, including zero and negative values, and rejects only values outside that range, which the server would reject when parsing the request.

Any authenticated principal can list and read every policy, including repository-scoped ones. Creating, updating, and deleting require an administrator; for an API token, the user must be an administrator and the token must carry the `admin` or `*` scope. Other callers receive HTTP 403.

Policies are enforced in two places. The download and quarantine gate evaluates every enabled policy scoped to the artifact's repository and every enabled global policy, and any violation blocks; it uses `block_unscanned`, `block_on_fail`, and `max_severity`. The promotion gate uses a single enabled policy, preferring one scoped to the source repository over global ones, and uses `block_unscanned`, `max_severity` (where `low` counts the same findings as `medium`), `require_signature`, `min_staging_hours`, and `max_artifact_age_days`; without a matching policy it blocks critical findings. A disabled policy is ignored by both gates. These policies are independent of the repository scan configuration's `block_on_policy_violation` setting.

## Virtual repository members

The API's virtual-members `PUT` operation replaces the complete member set. `artifactkeeper.core.virtual_repository_members` therefore treats `members` as desired state: omitted existing members are removed, missing members are added, and priority changes are applied.

## Compatibility policy

Collection 0.3.0 claims compatibility with the Artifact Keeper 1.10.2 contract reviewed above; the 0.2.0 release claimed compatibility with 1.10.1. No older Artifact Keeper release range is claimed until integration coverage establishes one. Future collection releases should re-review the current `artifact-keeper/artifact-keeper-api` OpenAPI contract and backend implementation before changing behavior.
