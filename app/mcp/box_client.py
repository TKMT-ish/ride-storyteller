"""Read-only media search boundary. No Box connection is made on Day 1."""

from typing import Protocol

from app.contracts import MediaAsset


class MediaSearchTool(Protocol):
    def find_asset(self, *, name_hint: str) -> MediaAsset | None: ...


class MockMediaSearchTool:
    def __init__(self, asset: MediaAsset | None) -> None:
        self.asset = asset
        self.calls = 0

    def find_asset(self, *, name_hint: str) -> MediaAsset | None:
        self.calls += 1
        if self.asset and self.asset.name == name_hint:
            return self.asset
        return None
