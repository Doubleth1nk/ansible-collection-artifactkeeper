# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later

class ModuleDocFragment:
    DOCUMENTATION = r'''
options:
  api_url:
    description:
      - Base URL of the Artifact Keeper instance.
      - Either the server root (for example C(https://artifacts.example.com)) or a URL ending in C(/api/v1) is accepted.
    type: str
    required: true
  token:
    description:
      - Existing Artifact Keeper API token or service-account token.
      - "Sent as C(Authorization: Bearer ...), which is the canonical authentication scheme for management endpoints."
    type: str
  username:
    description:
      - Administrator username used with O(password) to authenticate through C(/api/v1/auth/login).
    type: str
  password:
    description:
      - Administrator password used with O(username).
    type: str
  validate_certs:
    description:
      - Whether to validate TLS certificates.
    type: bool
    default: true
  ca_path:
    description:
      - PEM-formatted CA bundle used for TLS verification.
    type: path
  timeout:
    description:
      - HTTP request timeout in seconds.
    type: int
    default: 30
notes:
  - "Exactly one authentication mode must be supplied: O(token), or O(username) plus O(password)."
  - The Artifact Keeper OpenAPI specification does not define an X-API-Key management authentication scheme, so this collection does not invent one.
'''
