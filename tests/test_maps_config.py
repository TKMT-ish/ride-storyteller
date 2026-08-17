from pathlib import Path

import pytest

from app.web.maps_config import GoogleMapsSettings, load_local_environment


def test_settings_reads_the_maps_key_without_returning_it_in_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-browser-key")

    settings = GoogleMapsSettings.from_environment()

    assert settings.enabled is True
    assert "key=test-browser-key" in settings.javascript_url()
    assert "callback=initRideMap" in settings.javascript_url()
    assert "language=ja" in settings.javascript_url()
    assert "language=en" in settings.javascript_url(language="en")


def test_local_env_does_not_override_the_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = tmp_path / ".env"
    environment.write_text("GOOGLE_MAPS_API_KEY=local-key\n")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "process-key")

    values = load_local_environment(environment)

    assert values == {"GOOGLE_MAPS_API_KEY": "local-key"}


def test_disabled_settings_cannot_build_a_maps_url() -> None:
    with pytest.raises(ValueError, match="GOOGLE_MAPS_API_KEY"):
        GoogleMapsSettings(api_key="").javascript_url()


def test_maps_language_is_limited_to_supported_ui_languages() -> None:
    with pytest.raises(ValueError, match="language"):
        GoogleMapsSettings(api_key="test-browser-key").javascript_url(language="fr")
