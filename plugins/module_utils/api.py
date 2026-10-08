# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared Artifact Keeper HTTP client for the artifactkeeper.core collection."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from ansible.module_utils.urls import open_url


SENSITIVE_KEYS = {
    "authorization",
    "password",
    "new_password",
    "current_password",
    "generated_password",
    "temporary_password",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "upstream_password",
    "client_secret",
    "secret",
}


class ArtifactKeeperError(Exception):
    """Base client error."""


class ArtifactKeeperHTTPError(ArtifactKeeperError):
    """Artifact Keeper returned an unsuccessful response."""

    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__("Artifact Keeper API returned HTTP %s: %s" % (status, message))


class ArtifactKeeperNotFound(ArtifactKeeperHTTPError):
    """Requested resource was not found."""


def _redact_value(value, secret_values=()):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                result[key] = "VALUE_SPECIFIED_IN_NO_LOG_PARAMETER"
            else:
                result[key] = _redact_value(item, secret_values)
        return result
    if isinstance(value, list):
        return [_redact_value(item, secret_values) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, secret_values) for item in value)
    if isinstance(value, str):
        redacted = value
        for secret in secret_values:
            if secret:
                redacted = redacted.replace(str(secret), "VALUE_SPECIFIED_IN_NO_LOG_PARAMETER")
        return redacted
    return value


def redact(value, secret_values=()):
    """Redact credential-shaped keys and concrete secret strings."""
    return _redact_value(value, tuple(v for v in secret_values if v))


def _secret_values_from_payload(value, sensitive=False):
    """Collect concrete secret strings from credential-shaped request fields."""
    values = []
    if isinstance(value, dict):
        for key, item in value.items():
            values.extend(_secret_values_from_payload(item, sensitive=str(key).lower() in SENSITIVE_KEYS))
    elif isinstance(value, (list, tuple)):
        for item in value:
            values.extend(_secret_values_from_payload(item, sensitive=sensitive))
    elif sensitive and value not in (None, ""):
        values.append(str(value))
    return values


class ArtifactKeeperClient:
    """Minimal JSON client using Ansible's URL helpers."""

    def __init__(
        self,
        api_url,
        token=None,
        username=None,
        password=None,
        validate_certs=True,
        ca_path=None,
        timeout=30,
        opener=None,
    ):
        self.base_url = self.normalize_api_url(api_url)
        self.token = token
        self.username = username
        self.password = password
        self.validate_certs = validate_certs
        self.ca_path = ca_path
        self.timeout = timeout
        self._opener = opener or open_url
        self._login_complete = bool(token)

    @staticmethod
    def normalize_api_url(api_url):
        if not api_url or not str(api_url).strip():
            raise ArtifactKeeperError("api_url must not be empty")
        url = str(api_url).strip().rstrip("/")
        if url.endswith("/api/v1"):
            return url
        return url + "/api/v1"

    @property
    def secret_values(self):
        return tuple(v for v in (self.token, self.password) if v)

    def _headers(self, include_auth=True):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "artifactkeeper.core/0.4.0",
        }
        if include_auth and self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        return headers

    def login(self):
        """Authenticate a username/password pair and retain the returned JWT."""
        if self._login_complete:
            return self.token
        if not self.username or self.password is None:
            raise ArtifactKeeperError("username/password authentication is incomplete")
        response = self.request(
            "POST",
            "/auth/login",
            data={"username": self.username, "password": self.password},
            expected=(200,),
            include_auth=False,
            _skip_login=True,
        )
        access_token = response.get("access_token") if isinstance(response, dict) else None
        if not access_token:
            raise ArtifactKeeperError("login response did not contain access_token")
        self.token = access_token
        self._login_complete = True
        return access_token

    def _url(self, path, params=None):
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = self.base_url + "/" + path.lstrip("/")
        if params:
            cleaned = {key: value for key, value in params.items() if value is not None}
            if cleaned:
                url += ("&" if "?" in url else "?") + urlencode(cleaned, doseq=True)
        return url

    @staticmethod
    def _decode_response(response):
        raw = response.read()
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    def _error_message(self, error, extra_secret_values=()):
        body = None
        try:
            body = error.read()
        except Exception:  # pragma: no cover - defensive for unusual urllib handlers
            body = None
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        if body:
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    message = parsed.get("message") or parsed.get("error") or parsed.get("detail") or parsed
                else:
                    message = parsed
            except (TypeError, ValueError):
                message = body
        else:
            message = getattr(error, "reason", None) or str(error)
        safe = redact(message, self.secret_values + tuple(extra_secret_values))
        if isinstance(safe, (dict, list)):
            return json.dumps(safe, sort_keys=True)
        return str(safe)

    def request(
        self,
        method,
        path,
        data=None,
        params=None,
        expected=(200,),
        allow_404=False,
        include_auth=True,
        _skip_login=False,
    ):
        if include_auth and not self.token and self.username and not _skip_login:
            self.login()
        url = self._url(path, params=params)
        request_secret_values = tuple(_secret_values_from_payload(data))
        all_secret_values = self.secret_values + request_secret_values
        encoded = None if data is None else json.dumps(data).encode("utf-8")
        kwargs = dict(
            method=method,
            headers=self._headers(include_auth=include_auth),
            data=encoded,
            validate_certs=self.validate_certs,
            timeout=self.timeout,
            follow_redirects="safe",
            unredirected_headers=["Authorization"],
            use_netrc=False,
        )
        if self.ca_path:
            kwargs["ca_path"] = self.ca_path
        try:
            response = self._opener(url, **kwargs)
            status = response.getcode()
            payload = self._decode_response(response)
        except HTTPError as exc:
            status = exc.code
            if status == 404 and allow_404:
                return None
            message = self._error_message(exc, request_secret_values)
            if status == 404:
                raise ArtifactKeeperNotFound(status, message)
            raise ArtifactKeeperHTTPError(status, message)
        except URLError as exc:
            raise ArtifactKeeperError("Artifact Keeper API connection failed: %s" % redact(str(exc.reason), all_secret_values))
        except (OSError, ValueError) as exc:
            raise ArtifactKeeperError("Artifact Keeper API request failed: %s" % redact(str(exc), all_secret_values))

        if status not in expected:
            safe = redact(payload, all_secret_values)
            raise ArtifactKeeperHTTPError(status, json.dumps(safe, sort_keys=True) if isinstance(safe, (dict, list)) else str(safe))
        return payload

    def get(self, path, params=None, allow_404=False):
        return self.request("GET", path, params=params, expected=(200,), allow_404=allow_404)

    def post(self, path, data=None, expected=(200, 201)):
        return self.request("POST", path, data=data, expected=expected)

    def put(self, path, data=None, expected=(200, 204)):
        return self.request("PUT", path, data=data, expected=expected)

    def patch(self, path, data=None, expected=(200, 204)):
        return self.request("PATCH", path, data=data, expected=expected)

    def delete(self, path, data=None, expected=(200, 204), allow_404=False):
        return self.request("DELETE", path, data=data, expected=expected, allow_404=allow_404)

    def paginate(self, path, params=None, items_key="items", per_page=200):
        """Collect item-list responses that expose Artifact Keeper Pagination metadata."""
        page = 1
        items = []
        while True:
            query = dict(params or {})
            query.update({"page": page, "per_page": per_page})
            response = self.get(path, params=query)
            if not isinstance(response, dict):
                raise ArtifactKeeperError("paginated endpoint returned a non-object response")
            batch = response.get(items_key, [])
            if not isinstance(batch, list):
                raise ArtifactKeeperError("paginated endpoint returned non-list '%s'" % items_key)
            items.extend(batch)
            pagination = response.get("pagination") or {}
            total_pages = pagination.get("total_pages")
            if total_pages is not None:
                if page >= int(total_pages):
                    break
            elif len(batch) < per_page:
                break
            page += 1
            if page > 10000:
                raise ArtifactKeeperError("pagination exceeded 10000 pages; refusing an unbounded loop")
        return items
