"""Test-wide guards: no test may reach a paid service by accident."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_google_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty key in the environment shadows any key in a local .env.

    The map background and the place names both read GOOGLE_MAPS_API_KEY;
    a developer's own key must never let a test send a coordinate to
    Google. Tests that need a key pass one explicitly.
    """
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "")
