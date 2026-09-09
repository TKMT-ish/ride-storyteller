"""Local-only preview server for the isolated journey workflow frontend."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from app.web.deployment import WebDeploymentMode, WebDeploymentSettings
from app.web.i18n import resolve_language
from app.web.journey_workflow_frontend import render_journey_workflow_page
from app.web.server import application as existing_application

StartResponse = Callable[[str, list[tuple[str, str]]], Callable[[bytes], object]]


def application(
    environ: dict[str, object], start_response: StartResponse
) -> Iterable[bytes]:
    """Serve the workflow locally and delegate existing API/media requests."""

    path = str(environ.get("PATH_INFO", "/"))
    if path not in {"/", "/workflow"}:
        return existing_application(environ, start_response)
    if str(environ.get("REQUEST_METHOD", "GET")).upper() != "GET":
        return _respond(start_response, "405 Method Not Allowed", b"GET required")
    settings = WebDeploymentSettings.from_environment()
    if settings.mode is not WebDeploymentMode.LOCAL:
        return _respond(start_response, "403 Forbidden", b"local workflow only")
    query = parse_qs(str(environ.get("QUERY_STRING", "")))
    language = resolve_language(query.get("lang", [None])[0])
    return _respond(
        start_response,
        "200 OK",
        render_journey_workflow_page(language).encode("utf-8"),
    )


def _respond(start_response: StartResponse, status: str, body: bytes) -> Iterable[bytes]:
    start_response(
        status,
        [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
        ],
    )
    return [body]


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview the local journey workflow UI")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    if not 1 <= args.port <= 65_535:
        parser.error("--port must be between 1 and 65535")
    with make_server("127.0.0.1", args.port, application) as server:
        print(f"Ride Storyteller workflow: http://127.0.0.1:{args.port}/workflow")
        server.serve_forever()


if __name__ == "__main__":
    main()
