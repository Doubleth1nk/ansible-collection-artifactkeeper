# Contributing

Contributions are welcome. Keep modules narrow, declarative, idempotent, and grounded in the current Artifact Keeper OpenAPI contract.

## Development setup

Clone this repository into an Ansible collection path:

```bash
mkdir -p ~/.ansible/collections/ansible_collections/artifactkeeper
git clone https://github.com/Doubleth1nk/ansible-collection-artifactkeeper.git \
  ~/.ansible/collections/ansible_collections/artifactkeeper/core
cd ~/.ansible/collections/ansible_collections/artifactkeeper/core
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

Run the fast checks before opening a pull request:

```bash
python -m compileall plugins tests
ansible-test sanity --python 3.13
ansible-test units --venv --python 3.13
ansible-lint
```

Do not add `requests` merely for convenience; use the shared client and Ansible URL utilities. Do not add secret-store coupling to resource modules. Add a changelog fragment for user-visible changes.

## API changes

When Artifact Keeper changes an endpoint or schema, update the client/module behavior against the current `artifact-keeper/artifact-keeper-api` `openapi.yaml`, add regression tests, and document any compatibility implication. Do not preserve stale behavior merely because an older role or playbook used it.
