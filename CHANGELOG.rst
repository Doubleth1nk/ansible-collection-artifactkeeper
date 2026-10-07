=================================
artifactkeeper.core Release Notes
=================================

.. contents:: Topics

v0.3.0
======

Release Summary
---------------

Adds group management and repository-scoped service-account tokens, and moves the documented Artifact Keeper baseline to 1.10.2. The new ``group`` module manages local groups and their membership. ``service_account_token`` can restrict tokens to repositories by key or selector and now rotates tokens safely by creating the replacement before revoking the old token. 0.3.0 targets the Artifact Keeper 1.10.2 API contract.

Minor Changes
-------------

- The documented Artifact Keeper API baseline is now 1.10.2. All endpoints used by the collection are unchanged from 1.10.1 except service-account token creation, which 1.10.2 validates more strictly; the payload sent by ``service_account_token`` already complies. The documentation now covers the 1.10.2 token-creation rules, the repository scopes accepted by API tokens, and repository visibility for scoped admin tokens.
- ``service_account_token`` - add the ``repositories`` (repository keys) and ``repo_selector`` options for repository-scoped tokens, report managed differences through ``changed_fields``, and refresh ``token_info`` after creation so the effective repository restriction is visible. Restrictions are compared only when managed; when neither option is supplied, the restriction is unmanaged, as before.
- ``service_account_token`` - rotations now create the replacement token before revoking the old one, so a failed creation leaves the existing token in place. If revoking the old token fails, the replacement is revoked again, and a failed rotation never returns the new plaintext token.

New Modules
-----------

- group - Manage Artifact Keeper groups and their membership

v0.2.0
======

Release Summary
---------------

Adds user management and repository-level access control. New modules manage local users and direct repository permission grants, and look up users and repositories. Password-related values are now redacted from API error messages.

Security Fixes
--------------

- Redact ``new_password``, ``current_password``, ``generated_password``, and ``temporary_password`` values from Artifact Keeper API error messages.

New Modules
-----------

- repository_info - Gather Artifact Keeper repository information
- repository_permission - Manage Artifact Keeper repository permission grants
- user - Manage Artifact Keeper users
- user_info - Gather Artifact Keeper user information

v0.1.0
======

Release Summary
---------------

Initial development release.

Minor Changes
-------------

- Add a shared Artifact Keeper API client using ``ansible.module_utils.urls``.
- Add idempotent project, project-info, repository, service-account, service-account-token, project-member, virtual-repository-members, and group-info modules; repository age-gate policy is managed as nested repository configuration.
- Add unit-test, sanity-test, lint, release, changelog, and integration-test scaffolding.
