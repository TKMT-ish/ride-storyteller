"""Safe, connection-free configuration checks for the remote Box MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import load_local_environment


@dataclass(frozen=True)
class BoxMcpSettings:
    endpoint: str
    server_name: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str

    @classmethod
    def from_environment(cls) -> "BoxMcpSettings":
        local_values = load_local_environment()

        def value(name: str, default: str = "") -> str:
            return os.environ.get(name, local_values.get(name, default)).strip()

        return cls(
            endpoint=value("BOX_MCP_URL", "https://mcp.box.com"),
            server_name=value("BOX_MCP_NAME", "box-remote-mcp"),
            client_id=value("BOX_CLIENT_ID"),
            client_secret=value("BOX_CLIENT_SECRET"),
            redirect_uri=value("BOX_OAUTH_REDIRECT_URI"),
            scopes=value("BOX_OAUTH_SCOPES", "Content Actions"),
        )


@dataclass(frozen=True)
class BoxMcpPreflight:
    ready: bool
    missing: tuple[str, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "missing": list(self.missing),
            "errors": list(self.errors),
        }


def preflight_box_mcp(settings: BoxMcpSettings) -> BoxMcpPreflight:
    """Check local configuration without connecting to Box or revealing secrets."""
    missing = tuple(
        name
        for name, value in (
            ("BOX_CLIENT_ID", settings.client_id),
            ("BOX_CLIENT_SECRET", settings.client_secret),
            ("BOX_OAUTH_REDIRECT_URI", settings.redirect_uri),
        )
        if not value
    )
    errors: list[str] = []
    endpoint = urlparse(settings.endpoint)
    if settings.endpoint != "https://mcp.box.com" or endpoint.scheme != "https":
        errors.append("BOX_MCP_URL must be the hosted HTTPS endpoint: https://mcp.box.com")
    if settings.server_name != "box-remote-mcp":
        errors.append("BOX_MCP_NAME must be box-remote-mcp")
    redirect = urlparse(settings.redirect_uri)
    local_redirect_hosts = {"localhost", "127.0.0.1", "::1"}
    is_local_http_redirect = (
        redirect.scheme == "http" and redirect.hostname in local_redirect_hosts
    )
    if settings.redirect_uri and redirect.scheme != "https" and not is_local_http_redirect:
        errors.append(
            "BOX_OAUTH_REDIRECT_URI must use HTTPS, except for localhost or loopback HTTP "
            "during local development"
        )
    if not settings.scopes.strip():
        errors.append("BOX_OAUTH_SCOPES must be configured in Box before a live connection")
    return BoxMcpPreflight(ready=not missing and not errors, missing=missing, errors=tuple(errors))
