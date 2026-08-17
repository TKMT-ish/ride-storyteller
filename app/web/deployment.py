"""Fail-closed runtime mode for local development and a safe public demo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from app.config import load_local_environment


class WebDeploymentMode(StrEnum):
    LOCAL = "local"
    PUBLIC_DEMO = "public_demo"


@dataclass(frozen=True)
class WebDeploymentSettings:
    mode: WebDeploymentMode
    host: str
    port: int

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
        return cls(mode=mode, host=host, port=port)

    def __post_init__(self) -> None:
        loopback_hosts = {"127.0.0.1", "localhost", "::1"}
        public_bind_hosts = loopback_hosts | {"0.0.0.0", "::"}
        if self.host not in public_bind_hosts:
            raise ValueError("RIDE_WEB_HOST must be a loopback or wildcard bind address")
        if self.mode is WebDeploymentMode.LOCAL and self.host not in loopback_hosts:
            raise ValueError("local mode must bind to a loopback address")
        if not 1 <= self.port <= 65_535:
            raise ValueError("web port must be between 1 and 65535")

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
        }
