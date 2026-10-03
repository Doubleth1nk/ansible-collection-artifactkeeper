# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from ansible_collections.artifactkeeper.core.plugins.module_utils.api import (
    ArtifactKeeperClient,
    ArtifactKeeperHTTPError,
    ArtifactKeeperNotFound,
    redact,
)
from ansible_collections.artifactkeeper.core.plugins.module_utils.common import (
    common_argument_spec,
    managed_diff,
)


class Response:
    def __init__(self, status, payload=None):
        self.status = status
        self.payload = payload

    def getcode(self):
        return self.status

    def read(self):
        if self.payload is None:
            return b""
        return json.dumps(self.payload).encode()


class QueueOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def http_error(status, payload):
    return HTTPError(
        "https://example.invalid/api/v1/x",
        status,
        "error",
        hdrs=None,
        fp=io.BytesIO(json.dumps(payload).encode()),
    )


def test_url_normalization():
    assert ArtifactKeeperClient.normalize_api_url("https://ak.example/") == "https://ak.example/api/v1"
    assert ArtifactKeeperClient.normalize_api_url("https://ak.example/api/v1/") == "https://ak.example/api/v1"


def test_token_auth_adds_bearer_header_without_login():
    opener = QueueOpener([Response(200, {"ok": True})])
    client = ArtifactKeeperClient("https://ak.example", token="secret-token", opener=opener)
    assert client.get("/projects") == {"ok": True}
    assert opener.calls[0][1]["headers"]["Authorization"] == "Bearer secret-token"
    assert len(opener.calls) == 1


def test_username_password_login_then_bearer():
    opener = QueueOpener([Response(200, {"access_token": "jwt-value"}), Response(200, {"items": []})])
    client = ArtifactKeeperClient("https://ak.example", username="admin", password="pw", opener=opener)
    client.get("/projects")
    login_call, resource_call = opener.calls
    assert login_call[0].endswith("/api/v1/auth/login")
    assert "Authorization" not in login_call[1]["headers"]
    assert json.loads(login_call[1]["data"]) == {"username": "admin", "password": "pw"}
    assert resource_call[1]["headers"]["Authorization"] == "Bearer jwt-value"


def test_common_auth_secrets_are_no_log():
    spec = common_argument_spec()
    assert spec["token"]["no_log"] is True
    assert spec["password"]["no_log"] is True
    assert "api_key" not in spec


def test_http_error_uses_server_message_and_redacts_secret():
    opener = QueueOpener([http_error(400, {"message": "bad secret-token", "token": "secret-token"})])
    client = ArtifactKeeperClient("https://ak.example", token="secret-token", opener=opener)
    with pytest.raises(ArtifactKeeperHTTPError) as exc:
        client.get("/projects")
    assert exc.value.status == 400
    assert "secret-token" not in str(exc.value)


def test_404_handling():
    opener = QueueOpener([http_error(404, {"message": "missing"}), http_error(404, {"message": "missing"})])
    client = ArtifactKeeperClient("https://ak.example", token="t", opener=opener)
    assert client.get("/repositories/missing", allow_404=True) is None
    with pytest.raises(ArtifactKeeperNotFound):
        client.get("/repositories/missing")


def test_pagination_collects_all_pages():
    opener = QueueOpener(
        [
            Response(200, {"items": [{"id": 1}], "pagination": {"total_pages": 2}}),
            Response(200, {"items": [{"id": 2}], "pagination": {"total_pages": 2}}),
        ]
    )
    client = ArtifactKeeperClient("https://ak.example", token="t", opener=opener)
    assert client.paginate("/groups", per_page=1) == [{"id": 1}, {"id": 2}]
    assert "page=1" in opener.calls[0][0]
    assert "page=2" in opener.calls[1][0]


def test_redaction_is_recursive_and_replaces_concrete_values():
    value = {"password": "pw", "nested": {"message": "Bearer top-secret"}, "safe": "ok"}
    redacted = redact(value, ("top-secret",))
    assert redacted["password"] != "pw"
    assert "top-secret" not in redacted["nested"]["message"]
    assert redacted["safe"] == "ok"


def test_current_state_comparison_manages_only_requested_fields():
    changed, before, after = managed_diff(
        {"name": "Old", "description": "untouched", "server_field": 7},
        {"name": "New"},
        ["name"],
    )
    assert changed == ["name"]
    assert before == {"name": "Old"}
    assert after == {"name": "New"}


def test_ca_path_and_timeout_are_forwarded():
    opener = QueueOpener([Response(200, {})])
    client = ArtifactKeeperClient(
        "https://ak.example",
        token="t",
        ca_path="/tmp/ca.pem",
        timeout=42,
        opener=opener,
    )
    client.get("/projects")
    kwargs = opener.calls[0][1]
    assert kwargs["ca_path"] == "/tmp/ca.pem"
    assert kwargs["timeout"] == 42
    assert kwargs["validate_certs"] is True


def test_authorization_header_is_not_forwarded_on_redirects():
    opener = QueueOpener([Response(200, {})])
    client = ArtifactKeeperClient("https://ak.example", token="t", opener=opener)
    client.get("/projects")
    assert opener.calls[0][1]["unredirected_headers"] == ["Authorization"]


def test_request_payload_secret_is_redacted_from_plaintext_error():
    body = b"upstream rejected password super-upstream-secret"
    error = HTTPError("https://ak/api/v1/repositories", 400, "bad request", {}, io.BytesIO(body))
    opener = QueueOpener([error])
    client = ArtifactKeeperClient("https://ak", token="admin-token", opener=opener)

    with pytest.raises(ArtifactKeeperHTTPError) as exc:
        client.post("/repositories", data={"upstream_password": "super-upstream-secret"})

    assert "super-upstream-secret" not in str(exc.value)
    assert "VALUE_SPECIFIED_IN_NO_LOG_PARAMETER" in str(exc.value)
