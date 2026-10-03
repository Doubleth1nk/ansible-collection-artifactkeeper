# Integration tests

The `artifactkeeper_smoke` ansible-test target is deliberately marked destructive/live because it requires a real Artifact Keeper instance. It is not part of normal PR unit/sanity CI.

Example from a correctly installed collection checkout:

```bash
ansible-test integration artifactkeeper_smoke \
  --allow-destructive \
  --extra-vars 'artifactkeeper_test_url=https://artifacts.example.com artifactkeeper_test_token=REDACTED'
```

Use a disposable test instance and non-production credentials. Expand this target with create/update/delete/idempotency exercises when an official Artifact Keeper integration fixture becomes available.
