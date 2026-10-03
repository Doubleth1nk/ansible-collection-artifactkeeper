# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from ansible_collections.artifactkeeper.core.tests.unit.helpers import ModuleExit

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Local pytest can exercise collection logic even when ansible-core is unavailable
# in the development shell. ansible-test in CI uses the real packages instead.
try:
    import ansible.module_utils.basic  # noqa: F401
    import ansible.module_utils.urls  # noqa: F401
    _HAS_ANSIBLE = True
except ImportError:
    _HAS_ANSIBLE = False

if not _HAS_ANSIBLE:
    ansible = types.ModuleType("ansible")
    ansible.__path__ = []
    module_utils = types.ModuleType("ansible.module_utils")
    module_utils.__path__ = []
    urls = types.ModuleType("ansible.module_utils.urls")
    basic = types.ModuleType("ansible.module_utils.basic")

    def unavailable_open_url(*args, **kwargs):  # pragma: no cover - client tests inject opener
        raise RuntimeError("test open_url stub was unexpectedly called")

    class StubAnsibleModule:
        def __init__(self, *args, **kwargs):  # pragma: no cover - mains are tested by ansible-test
            raise RuntimeError("real AnsibleModule is required to execute module main()")

    urls.open_url = unavailable_open_url
    basic.AnsibleModule = StubAnsibleModule
    sys.modules.update(
        {
            "ansible": ansible,
            "ansible.module_utils": module_utils,
            "ansible.module_utils.urls": urls,
            "ansible.module_utils.basic": basic,
        }
    )

# Expose the checkout as the canonical collection namespace for plain pytest.
package_paths = {
    "ansible_collections": ROOT,
    "ansible_collections.artifactkeeper": ROOT,
    "ansible_collections.artifactkeeper.core": ROOT,
    "ansible_collections.artifactkeeper.core.plugins": ROOT / "plugins",
    "ansible_collections.artifactkeeper.core.plugins.module_utils": ROOT / "plugins" / "module_utils",
    "ansible_collections.artifactkeeper.core.plugins.modules": ROOT / "plugins" / "modules",
}
for name, path in package_paths.items():
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package


@pytest.fixture
def invoke():
    def _invoke(run_module, module, client):
        with pytest.raises(ModuleExit) as exc:
            run_module(module, client)
        return exc.value.result

    return _invoke
