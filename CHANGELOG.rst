==============================
artifactkeeper.core Changelog
==============================

v0.1.0
======

Initial development release.

Minor Changes
-------------

* Add idempotent project, project-info, repository, service-account, service-account-token, project-member, virtual-repository-members, and group-info modules; repository age-gate policy is managed as nested repository configuration.
* Add a shared Artifact Keeper API client using ``ansible.module_utils.urls``.
* Add unit-test, sanity-test, lint, release, changelog, and integration-test scaffolding.
