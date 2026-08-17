import subprocess
import sys
import tomllib
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
    pyproject = tomllib.loads(_text("pyproject.toml"))

    assert pyproject["project"]["dependencies"] == []
    assert pyproject["project"]["optional-dependencies"]["deploy"] == [
        "gunicorn>=26.0.0,<27.0.0"
    ]
    cloud = pyproject["project"]["optional-dependencies"]["cloud"]
    assert any(requirement.startswith("google-adk") for requirement in cloud)
    assert any(requirement.startswith("google-cloud-aiplatform") for requirement in cloud)
    assert any(requirement.startswith("google-genai") for requirement in cloud)


def test_public_web_import_and_demo_do_not_load_google_modules() -> None:
    script = """
import builtins
import json
import os
import sys

original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'google' or name.startswith('google.'):
        raise AssertionError(f'unexpected Google import: {name}')
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
os.environ['RIDE_WEB_MODE'] = 'public_demo'
google_modules_before = {
    name for name in sys.modules if name == 'google' or name.startswith('google.')
}
from app.web.server import application

def request(path):
    captured = {}
    def start_response(status, headers):
        captured['status'] = status
    body = b''.join(application({'PATH_INFO': path, 'QUERY_STRING': 'lang=en'}, start_response))
    return captured['status'], json.loads(body)

health_status, health = request('/healthz')
demo_status, demo = request('/api/demo')
assert health_status == '200 OK'
assert health['mode'] == 'public_demo'
assert demo_status == '200 OK'
assert demo['demo_mode'] is True
google_modules_after = {
    name for name in sys.modules if name == 'google' or name.startswith('google.')
}
assert google_modules_after == google_modules_before
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_local_web_returns_safe_503_when_cloud_extra_is_absent() -> None:
    script = """
import builtins
import os

original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'app.agent_runtime' or name.startswith('app.agent_runtime.'):
        raise ModuleNotFoundError('optional cloud support is absent')
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
os.environ['RIDE_WEB_MODE'] = 'local'
from app.web.server import application

def request(path, method='GET'):
    captured = {}
    def start_response(status, headers):
        captured['status'] = status
    body = b''.join(application({
        'PATH_INFO': path,
        'QUERY_STRING': '',
        'REQUEST_METHOD': method,
    }, start_response))
    return captured['status'], body.decode()

for path, method in (
    ('/api/google-runtime', 'GET'),
    ('/api/agent-platform-preflight', 'GET'),
    ('/api/adk-synthetic-demo', 'POST'),
    ('/api/agent-platform-synthetic-demo', 'POST'),
):
    status, body = request(path, method)
    assert status == '503 Service Unavailable', (path, status, body)
    assert 'error' in body
    assert 'optional cloud support is absent' not in body
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
