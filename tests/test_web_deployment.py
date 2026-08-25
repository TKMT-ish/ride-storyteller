from pathlib import Path

import pytest

from app.web.deployment import WebDeploymentMode, WebDeploymentSettings


def test_web_deployment_defaults_to_loopback_local_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "PORT",
        "RIDE_SOURCE_REPOSITORY_URL",
        "RIDE_WEB_HOST",
        "RIDE_WEB_MODE",
        "RIDE_WEB_PORT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = WebDeploymentSettings.from_environment()

    assert settings.mode is WebDeploymentMode.LOCAL
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.external_actions_enabled is True
    assert settings.private_gpx_enabled is True


def test_public_demo_defaults_to_wildcard_and_disables_sensitive_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")
    monkeypatch.setenv("PORT", "8080")

    settings = WebDeploymentSettings.from_environment()

    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
    assert settings.to_dict() == {
        "mode": "public_demo",
        "external_actions_enabled": False,
        "private_gpx_enabled": False,
        "source_repository_configured": False,
    }


def test_local_mode_rejects_public_bind_address() -> None:
    with pytest.raises(ValueError, match="loopback"):
        WebDeploymentSettings(WebDeploymentMode.LOCAL, "0.0.0.0", 8765)


@pytest.mark.parametrize(
    ("mode", "host", "port"),
    (
        (WebDeploymentMode.PUBLIC_DEMO, "example.com", 8080),
        (WebDeploymentMode.PUBLIC_DEMO, "0.0.0.0", 0),
        (WebDeploymentMode.PUBLIC_DEMO, "0.0.0.0", 65_536),
    ),
)
def test_web_deployment_rejects_unsafe_bind_or_port(
    mode: WebDeploymentMode, host: str, port: int
) -> None:
    with pytest.raises(ValueError):
        WebDeploymentSettings(mode, host, port)


def test_invalid_environment_mode_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "production")

    with pytest.raises(ValueError, match="local or public_demo"):
        WebDeploymentSettings.from_environment()


def test_source_repository_url_is_validated_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "RIDE_SOURCE_REPOSITORY_URL",
        "https://github.com/ride-storyteller/ride-storyteller",
    )

    settings = WebDeploymentSettings.from_environment()

    assert settings.source_repository_url == (
        "https://github.com/ride-storyteller/ride-storyteller"
    )
    assert settings.to_dict()["source_repository_configured"] is True


@pytest.mark.parametrize(
    "url",
    (
        "http://github.com/owner/repository",
        "https://example.com/owner/repository",
        "https://user@github.com/owner/repository",
        "https://github.com/owner/repository?tab=readme",
        "https://github.com/owner/repository#readme",
        "https://github.com/owner/repository?",
        "https://github.com/owner/repository#",
        "https://github.com/owner/repository/issues",
        "https://github.com/owner/repository/",
        "https://github.com/./repository",
    ),
)
def test_source_repository_url_rejects_non_repository_roots(
    url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_SOURCE_REPOSITORY_URL", url)

    with pytest.raises(ValueError, match="repository-root URL"):
        WebDeploymentSettings.from_environment()


def test_direct_source_repository_url_rejects_surrounding_whitespace() -> None:
    with pytest.raises(ValueError, match="repository-root URL"):
        WebDeploymentSettings(
            WebDeploymentMode.LOCAL,
            "127.0.0.1",
            8765,
            " https://github.com/owner/repository",
        )
