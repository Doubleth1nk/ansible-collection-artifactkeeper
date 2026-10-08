# Integration tests

The `artifactkeeper_smoke` ansible-test target is deliberately marked destructive/live because it requires a real Artifact Keeper instance. It is not part of normal PR unit/sanity CI.

Example from a correctly installed collection checkout (add `artifactkeeper_test_permission_repository=<key> artifactkeeper_test_permission_group=<name>` to also exercise a repository grant on a disposable repository and group, and `artifactkeeper_test_user_username=<name> artifactkeeper_test_user_email=<email>` to also create, update, and delete a disposable user, and `artifactkeeper_test_group_name=<name> artifactkeeper_test_group_member=<existing username>` to also create, update, and delete a disposable group, and `artifactkeeper_test_token_service_account=<name> artifactkeeper_test_token_repository=<key>` to also create, rotate, and revoke a repository-restricted service-account token, and `artifactkeeper_test_label_repository=<key>` to also set, merge, and clear labels on a disposable repository, and `artifactkeeper_test_scan_repository=<key>` to also change the scan configuration of a disposable repository; it is reset to the defaults afterwards, but the stored configuration cannot be deleted, and `artifactkeeper_test_policy_repository=<key>` to also create, update, and delete a security policy scoped to a disposable repository, which needs an administrator token with the `admin` or `*` scope):

```bash
ansible-test integration artifactkeeper_smoke \
  --allow-destructive \
  --extra-vars 'artifactkeeper_test_url=https://artifacts.example.com artifactkeeper_test_token=REDACTED'
```

Use a disposable test instance and non-production credentials. Expand this target with create/update/delete/idempotency exercises when an official Artifact Keeper integration fixture becomes available.
