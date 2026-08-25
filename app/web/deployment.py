"""Fail-closed runtime mode for local development and a safe public demo."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from app.config import load_local_environment


class WebDeploymentMode(StrEnum):
    LOCAL = "local"
    PUBLIC_DEMO = "public_demo"


_SOURCE_REPOSITORY_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
_SOURCE_REPOSITORY_PATH = re.compile(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def validate_source_repository_url(raw_url: str) -> str:
    """Return a canonical public repository URL or fail closed.

    Submission source links must point to a repository root, not an arbitrary
    page, credential-bearing URL, branch, issue, query, or fragment.
    """

    url = raw_url.strip()
    parsed = urlsplit(url)
    path_segments = parsed.path.removeprefix("/").split("/")
    if (
        not url
        or url != raw_url
        or parsed.scheme != "https"
        or parsed.hostname not in _SOURCE_REPOSITORY_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or "?" in url
        or "#" in url
        or parsed.query
        or parsed.fragment
        or not _SOURCE_REPOSITORY_PATH.fullmatch(parsed.path)
        or any(segment in {".", ".."} for segment in path_segments)
    ):
        raise ValueError(
            "RIDE_SOURCE_REPOSITORY_URL must be an HTTPS GitHub, GitLab, or "
            "Bitbucket repository-root URL"
        )
    return url


@dataclass(frozen=True)
class WebDeploymentSettings:
    mode: WebDeploymentMode
    host: str
    port: int
    source_repository_url: str | None = None

    @classmethod
    def from_environment(cls) -> "WebDeploymentSettings":
        local_values = load_local_environment()

        def value(name: str, default: str = "") -> str:
            return os.environ.get(name, local_values.get(name, default)).strip()

        raw_mode = value("RIDE_WEB_MODE", WebDeploymentMode.LOCAL.value)
        try:
            mode = WebDeploymentMode(raw_mode)
        except ValueError as error:
            raise ValueError("RIDE_WEB_MODE must be local or public_demo") from error
        default_host = "127.0.0.1" if mode is WebDeploymentMode.LOCAL else "0.0.0.0"
        host = value("RIDE_WEB_HOST", default_host)
        raw_port = value("RIDE_WEB_PORT", value("PORT", "8765"))
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ValueError("RIDE_WEB_PORT or PORT must be an integer") from error
        raw_source_repository_url = value("RIDE_SOURCE_REPOSITORY_URL")
        source_repository_url = (
            validate_source_repository_url(raw_source_repository_url)
            if raw_source_repository_url
            else None
        )
        return cls(
            mode=mode,
            host=host,
            port=port,
            source_repository_url=source_repository_url,
        )

    def __post_init__(self) -> None:
        loopback_hosts = {"127.0.0.1", "localhost", "::1"}
        public_bind_hosts = loopback_hosts | {"0.0.0.0", "::"}
        if self.host not in public_bind_hosts:
            raise ValueError("RIDE_WEB_HOST must be a loopback or wildcard bind address")
        if self.mode is WebDeploymentMode.LOCAL and self.host not in loopback_hosts:
            raise ValueError("local mode must bind to a loopback address")
        if not 1 <= self.port <= 65_535:
            raise ValueError("web port must be between 1 and 65535")
        if self.source_repository_url is not None:
            validate_source_repository_url(self.source_repository_url)

    @property
    def public_demo(self) -> bool:
        return self.mode is WebDeploymentMode.PUBLIC_DEMO

    @property
    def external_actions_enabled(self) -> bool:
        return not self.public_demo

    @property
    def private_gpx_enabled(self) -> bool:
        return not self.public_demo

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "external_actions_enabled": self.external_actions_enabled,
            "private_gpx_enabled": self.private_gpx_enabled,
            "source_repository_configured": self.source_repository_url is not None,
        }
