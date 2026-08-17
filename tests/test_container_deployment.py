from pathlib import Path

import pytest


def _text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_dockerfile_uses_public_demo_nonroot_and_whitelisted_copy() -> None:
    dockerfile = _text("Dockerfile")

    assert "FROM python:3.12-slim" in dockerfile
    assert "RIDE_WEB_MODE=public_demo" in dockerfile
    assert "RIDE_WEB_HOST=0.0.0.0" in dockerfile
    assert "RIDE_UI_DEFAULT_LANGUAGE=en" in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "COPY ." not in dockerfile
    assert "USER ride" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert '"gunicorn"' in dockerfile
    assert "app.web.server:application" in dockerfile


@pytest.mark.parametrize(
    "required",
    (
        ".env",
        ".venv",
        ".git",
        "data/private",
        "media/private",
        "private-media",
        "*.gpx",
        "*.fit",
        "*.mp4",
        "*.mov",
        "*.lrv",
        "tests",
        "docs",
    ),
)
def test_dockerignore_excludes_private_or_unneeded_build_context(required: str) -> None:
    assert required in _text(".dockerignore").splitlines()


def test_gunicorn_config_requires_public_mode_and_bounded_workers() -> None:
    config = _text("gunicorn.conf.py")

    assert "requires RIDE_WEB_MODE=public_demo" in config
    assert '"WEB_CONCURRENCY", 2, maximum=8' in config
    assert '"WEB_THREADS", 2, maximum=16' in config
    assert 'worker_class = "gthread"' in config
    assert 'accesslog = "-"' in config
    assert "control_socket_disable = True" in config
    assert "limit_request_fields = 50" in config


def test_deploy_extra_pins_current_major_gunicorn() -> None:
    pyproject = _text("pyproject.toml")

    assert 'deploy = ["gunicorn>=26.0.0,<27.0.0"]' in pyproject
