=================================
artifactkeeper.core Release Notes
=================================

.. contents:: Topics

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
