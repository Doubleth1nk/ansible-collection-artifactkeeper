# Copyright: (c) 2026, Tuxthepirate (@Doubleth1nk)
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations


class ModuleExit(Exception):
    def __init__(self, result):
        self.result = result


class ModuleFail(Exception):
    def __init__(self, result):
        self.result = result


class FakeModule:
    def __init__(self, params, check_mode=False, diff=False):
        self.params = params
        self.check_mode = check_mode
        self._diff = diff

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleFail(kwargs)


class RecordingClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def _call(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))

        if self.responses:
            response = self.responses.pop(0)

            if isinstance(response, Exception):
                raise response

            return response

        return None

    def get(self, path, **kwargs):
        return self._call("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self._call("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self._call("PUT", path, **kwargs)

    def patch(self, path, **kwargs):
        return self._call("PATCH", path, **kwargs)

    def delete(self, path, **kwargs):
        return self._call("DELETE", path, **kwargs)

    def paginate(self, path, **kwargs):
        return self._call("PAGINATE", path, **kwargs)
