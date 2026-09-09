"""A dependency-free local UI for the synthetic Ride Storyteller demo."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import base64
import hmac
import json
from collections.abc import Callable, Iterable
from html import escape
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from wsgiref.simple_server import make_server
from xml.etree import ElementTree

from app.agents import RuleBasedStoryPlanner, StoryOutputLanguage
from app.demo import (
    build_demo_candidate_edit_plan,
    build_demo_event,
    build_demo_story_plan,
    build_synthetic_director_events,
    run_demo,
)
from app.edit import (
    CandidateEditReview,
    CandidateEvidenceStatus,
    build_candidate_edit_plan,
    review_candidate_edit_plan,
)
from app.gps import consolidate_events, extract_events, parse_gpx_bytes
from app.video.highlight_review import HighlightReviewReason, HighlightReviewStatus
from app.web.deployment import WebDeploymentSettings
from app.web.i18n import UiLanguage, copy_for, resolve_language
from app.web.journey_workflow_frontend import render_journey_workflow_page
from app.web.maps_config import GoogleMapsSettings
from app.web.private_director_preview import (
    PrivateDirectorPreview,
    PrivateDirectorPreviewError,
)
from app.web.private_evidence_review import (
    PrivateEvidenceReviewError,
    PrivateEvidenceReviewSession,
)
from app.web.private_highlight_reinforcement_review import (
    PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY_ENV,
    PrivateHighlightReinforcementReviewError,
    PrivateHighlightReinforcementReviewSession,
)
from app.web.private_highlight_review import (
    PrivateHighlightReviewError,
    PrivateHighlightReviewSession,
)
from app.web.private_journey_actions import (
    DEFAULT_MUSIC_TRACK_ID,
    MUSIC_TRACK_IDS,
    NO_MUSIC_TRACK_ID,
    REASON_ANOTHER_JOB_RUNNING,
    JobRefused,
    PrivateJourneyJobs,
)
from app.web.private_journey_console import (
    PrivateJourneyConsole,
    PrivateJourneyConsoleError,
)
from app.web.private_journey_intake import (
    IntakeRefused,
    IntakeRoots,
    list_packages,
    select_package,
)
from app.web.private_journey_intake import (
    propose as propose_intake,
)
from app.web.private_journey_status import (
    PrivateJourneyStatus,
    PrivateJourneyStatusError,
)
from app.web.private_journey_story import PrivateJourneyStoryError, StoryView
from app.web.rate_limit import FixedWindowRateLimiter

StartResponse = Callable[[str, list[tuple[str, str]]], Callable[[bytes], object]]
_PUBLIC_DEMO_DISABLED_PATHS = {
    "/api/adk-synthetic-demo",
    "/api/agent-platform-preflight",
    "/api/agent-platform-synthetic-demo",
    "/api/gemini-director-synthetic-demo",
    "/api/google-runtime",
    "/api/private-gpx-summary",
    "/private-highlight-review",
    "/api/private-highlight-review",
    "/api/private-highlight-review/asset",
    "/private-highlight-reinforcement-review",
    "/api/private-highlight-reinforcement-review",
    "/api/private-highlight-reinforcement-review/asset",
    "/private-evidence-review",
    "/api/private-evidence-review",
    "/api/private-evidence-review/asset",
    "/private-director-preview",
    "/api/private-director-preview",
    "/private-journey-status",
    "/api/private-journey-status",
    "/private-journey",
    "/workflow",
    "/api/private-journey",
    "/api/private-journey/preflight",
    "/api/private-journey/judge",
    "/api/private-journey/film",
    "/api/private-journey/intake/propose",
    "/api/private-journey/intake/create",
    "/api/private-journey/select",
    "/api/private-journey/story",
    "/private-journey/film",
}
_HEALTH_PATHS = {"/health", "/healthz"}
# One job at a time for this process; the console polls it.
_PRIVATE_JOURNEY_JOBS = PrivateJourneyJobs()
# The package the console is looking at. Set by intake and by selection;
# the environment's package is the starting point.
_CURRENT_PACKAGE: Path | None = None


def _console() -> PrivateJourneyConsole:
    if _CURRENT_PACKAGE is not None:
        return PrivateJourneyConsole.from_directory(_CURRENT_PACKAGE)
    return PrivateJourneyConsole.from_environment()


def _set_current_package(package: Path) -> None:
    global _CURRENT_PACKAGE
    _CURRENT_PACKAGE = package


_PUBLIC_DEMO_RATE_LIMITER = FixedWindowRateLimiter(
    max_requests=60,
    window_seconds=60,
)


class _ExternalRuntimeUnavailable(RuntimeError):
    """A safe local boundary for an unavailable optional cloud dependency."""


def application(environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
    path = environ.get("PATH_INFO", "/")
    query = parse_qs(str(environ.get("QUERY_STRING", "")))
    deployment = WebDeploymentSettings.from_environment()
    if deployment.public_demo and path not in _HEALTH_PATHS:
        allowed, retry_after = _PUBLIC_DEMO_RATE_LIMITER.allow()
        if not allowed:
            return _respond(
                start_response,
                "429 Too Many Requests",
                "application/json; charset=utf-8",
                b'{"error":"public demo request limit exceeded"}',
                extra_headers=(("Retry-After", str(retry_after)),),
            )
    if path not in _HEALTH_PATHS:
        auth_error = _public_demo_auth_error(environ, deployment)
        if auth_error is not None:
            status, body = auth_error
            return _respond(
                start_response,
                status,
                "application/json; charset=utf-8",
                body,
                extra_headers=(
                    ("WWW-Authenticate", 'Basic realm="Ride Storyteller judging", charset="UTF-8"'),
                ),
            )
    if deployment.public_demo and path not in _PUBLIC_DEMO_DISABLED_PATHS:
        request_error = _public_demo_request_error(environ)
        if request_error is not None:
            status, body = request_error
            return _respond(
                start_response,
                status,
                "application/json; charset=utf-8",
                body,
            )
    if path in _HEALTH_PATHS:
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(
                {"status": "ok", **deployment.to_dict()},
                ensure_ascii=False,
            ).encode(),
        )
    if deployment.public_demo and path in _PUBLIC_DEMO_DISABLED_PATHS:
        return _respond(
            start_response,
            "403 Forbidden",
            "application/json; charset=utf-8",
            b'{"error":"disabled in public demo mode"}',
        )
    if path == "/":
        language = resolve_language(query.get("lang", [None])[0])
        return _respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            _page(language, deployment=deployment).encode(),
        )
    if path == "/local-media-inventory":
        language = resolve_language(query.get("lang", [None])[0])
        return _respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            _media_inventory_page(language).encode(),
        )
    if path == "/private-highlight-review":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        try:
            PrivateHighlightReviewSession.from_environment()
        except PrivateHighlightReviewError:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"private highlight review is unavailable"}',
            )
        language = resolve_language(query.get("lang", [None])[0])
        return _respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            _private_highlight_review_page(language).encode(),
        )
    if path == "/api/private-highlight-review":
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        try:
            session = PrivateHighlightReviewSession.from_environment()
            if method == "GET":
                payload = session.payload()
            elif method == "POST":
                payload = _update_private_highlight_review(session, environ)
            else:
                return _respond(
                    start_response,
                    "405 Method Not Allowed",
                    "application/json; charset=utf-8",
                    '{"error":"GETまたはPOSTを使用してください。"}'.encode(),
                )
        except (PrivateHighlightReviewError, ValueError, TypeError, json.JSONDecodeError):
            return _respond(
                start_response,
                "400 Bad Request",
                "application/json; charset=utf-8",
                b'{"error":"private highlight review request is invalid"}',
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/private-highlight-review/asset":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        candidate_id = query.get("candidate_id", [""])[0]
        kind = query.get("kind", [""])[0]
        try:
            asset = PrivateHighlightReviewSession.from_environment().asset(candidate_id, kind)
            body = asset.read_bytes()
        except (OSError, PrivateHighlightReviewError):
            return _respond(
                start_response,
                "404 Not Found",
                "application/json; charset=utf-8",
                b'{"error":"private highlight review asset is unavailable"}',
            )
        content_type = "image/jpeg" if kind == "thumbnail" else "video/mp4"
        return _respond(start_response, "200 OK", content_type, body)
    if path == "/private-highlight-reinforcement-review":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        language = resolve_language(query.get("lang", [None])[0])
        try:
            PrivateHighlightReinforcementReviewSession.from_environment()
        except PrivateHighlightReinforcementReviewError:
            return _respond(
                start_response,
                "200 OK",
                "text/html; charset=utf-8",
                _private_highlight_reinforcement_review_setup_page(language).encode(),
            )
        return _respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            _private_highlight_reinforcement_review_page(language).encode(),
        )
    if path == "/api/private-highlight-reinforcement-review":
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        try:
            session = PrivateHighlightReinforcementReviewSession.from_environment()
            if method == "GET":
                payload = session.payload()
            elif method == "POST":
                payload = _update_private_highlight_reinforcement_review(session, environ)
            else:
                return _respond(
                    start_response,
                    "405 Method Not Allowed",
                    "application/json; charset=utf-8",
                    '{"error":"GETまたはPOSTを使用してください。"}'.encode(),
                )
        except (
            PrivateHighlightReinforcementReviewError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ):
            return _respond(
                start_response,
                "400 Bad Request",
                "application/json; charset=utf-8",
                b'{"error":"private highlight reinforcement review request is invalid"}',
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/private-highlight-reinforcement-review/asset":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        review_token = query.get("review_token", [""])[0]
        kind = query.get("kind", [""])[0]
        try:
            asset = PrivateHighlightReinforcementReviewSession.from_environment().asset(
                review_token, kind
            )
            body = asset.read_bytes()
        except (OSError, PrivateHighlightReinforcementReviewError):
            return _respond(
                start_response,
                "404 Not Found",
                "application/json; charset=utf-8",
                b'{"error":"private highlight reinforcement review asset is unavailable"}',
            )
        content_type = "image/jpeg" if kind == "thumbnail" else "video/mp4"
        return _respond(start_response, "200 OK", content_type, body)
    if path == "/private-evidence-review":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        language = resolve_language(query.get("lang", [None])[0])
        try:
            PrivateEvidenceReviewSession.from_environment()
        except PrivateEvidenceReviewError:
            return _respond(
                start_response,
                "200 OK",
                "text/html; charset=utf-8",
                _private_evidence_review_setup_page(language).encode(),
            )
        return _respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            _private_evidence_review_page(language).encode(),
        )
    if path == "/api/private-evidence-review":
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        try:
            session = PrivateEvidenceReviewSession.from_environment()
            if method == "GET":
                payload = session.payload()
            elif method == "POST":
                payload = _update_private_evidence_review(session, environ)
            else:
                return _respond(
                    start_response,
                    "405 Method Not Allowed",
                    "application/json; charset=utf-8",
                    '{"error":"GETまたはPOSTを使用してください。"}'.encode(),
                )
        except (PrivateEvidenceReviewError, ValueError, TypeError, json.JSONDecodeError):
            return _respond(
                start_response,
                "400 Bad Request",
                "application/json; charset=utf-8",
                b'{"error":"private evidence review request is invalid"}',
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/private-evidence-review/asset":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        review_id = query.get("review_id", [""])[0]
        try:
            asset = PrivateEvidenceReviewSession.from_environment().asset(review_id)
            body = asset.read_bytes()
        except (OSError, PrivateEvidenceReviewError):
            return _respond(
                start_response,
                "404 Not Found",
                "application/json; charset=utf-8",
                b'{"error":"private evidence review asset is unavailable"}',
            )
        return _respond(start_response, "200 OK", "video/mp4", body)
    if path == "/private-director-preview":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        try:
            PrivateDirectorPreview.from_environment()
        except PrivateDirectorPreviewError:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"private DirectorScript preview is unavailable"}',
            )
        language = resolve_language(query.get("lang", [None])[0])
        return _respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            _private_director_preview_page(language).encode(),
        )
    if path == "/api/private-director-preview":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        try:
            payload = PrivateDirectorPreview.from_environment().payload()
        except PrivateDirectorPreviewError:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"private DirectorScript preview is unavailable"}',
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path in (
        "/api/private-journey/preflight",
        "/api/private-journey/judge",
        "/api/private-journey/film",
    ):
        return _private_journey_action(environ, start_response, path.rsplit("/", 1)[1])
    if path in (
        "/api/private-journey/intake/propose",
        "/api/private-journey/intake/create",
        "/api/private-journey/select",
    ):
        return _private_journey_intake(environ, start_response, path.rsplit("/", 1)[1])
    if path == "/api/private-journey/story":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        try:
            console = _console()
            payload = StoryView(console.package_directory).payload()
        except PrivateJourneyConsoleError:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"private journey console is unavailable"}',
            )
        except PrivateJourneyStoryError as error:
            return _respond(
                start_response,
                "404 Not Found",
                "application/json; charset=utf-8",
                json.dumps({"error": str(error)}).encode(),
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/private-journey/film":
        return _private_journey_film(environ, start_response)
    if path == "/workflow":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        language = resolve_language(query.get("lang", [None])[0])
        return _respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            _journey_workflow_page(language).encode(),
        )
    if path == "/private-journey":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        try:
            _console()
        except PrivateJourneyConsoleError:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"private journey console is unavailable"}',
            )
        language = resolve_language(query.get("lang", [None])[0])
        return _respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            _private_journey_console_page(language).encode(),
        )
    if path == "/api/private-journey":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        try:
            console = _console()
            payload = console.payload()
        except PrivateJourneyConsoleError:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"private journey console is unavailable"}',
            )
        payload["job"] = _PRIVATE_JOURNEY_JOBS.snapshot()
        payload["package"] = console.package_directory.name
        payload["packages"] = list_packages(IntakeRoots.from_environment())
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/private-journey-status":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        try:
            PrivateJourneyStatus.from_environment()
        except PrivateJourneyStatusError:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"private journey status is unavailable"}',
            )
        language = resolve_language(query.get("lang", [None])[0])
        return _respond(
            start_response,
            "200 OK",
            "text/html; charset=utf-8",
            _private_journey_status_page(language).encode(),
        )
    if path == "/api/private-journey-status":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        try:
            payload = PrivateJourneyStatus.from_environment().payload()
        except PrivateJourneyStatusError:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"private journey status is unavailable"}',
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/demo":
        language = resolve_language(query.get("lang", [None])[0])
        scenario = query.get("scenario", ["accepted"])[0]
        try:
            payload = _demo_payload(scenario, language)
        except ValueError:
            return _respond(
                start_response,
                "400 Bad Request",
                "application/json; charset=utf-8",
                b'{"error":"unknown demo scenario"}',
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/story-plan":
        language = resolve_language(query.get("lang", [None])[0])
        plan = build_demo_story_plan(StoryOutputLanguage(language.value))
        notice = (
            "A provisional Story Plan generated only from synthetic GPS events."
            if language is UiLanguage.ENGLISH
            else "合成GPSイベントだけから作成した仮Story Planです。"
        )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(
                {
                    "demo_mode": True,
                    "language": language.value,
                    "notice": notice,
                    "story_plan": plan.to_dict(),
                },
                ensure_ascii=False,
            ).encode(),
        )
    if path == "/api/candidate-edit-plan":
        language = resolve_language(query.get("lang", [None])[0])
        plan, review = build_demo_candidate_edit_plan(StoryOutputLanguage(language.value))
        localized_review = _candidate_review_payload(review, language)
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(
                {
                    "demo_mode": True,
                    "language": language.value,
                    "notice": copy_for(language)["candidate.notice"],
                    "candidate_edit_plan": plan.to_dict(),
                    "quality_review": localized_review,
                },
                ensure_ascii=False,
            ).encode(),
        )
    if path == "/api/google-runtime":
        try:
            payload = _google_runtime_payload()
        except _ExternalRuntimeUnavailable:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"Google Cloud support is not installed."}',
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/agent-platform-preflight":
        try:
            payload = _agent_platform_preflight_payload()
        except _ExternalRuntimeUnavailable:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"Agent Platform support is not installed."}',
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/adk-synthetic-demo":
        if environ.get("REQUEST_METHOD", "GET") != "POST":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"POSTを使用してください。"}'.encode(),
            )
        if int(str(environ.get("CONTENT_LENGTH", "0")) or "0") != 0:
            return _respond(
                start_response,
                "400 Bad Request",
                "application/json; charset=utf-8",
                '{"error":"この確認には入力データを送れません。"}'.encode(),
            )
        try:
            payload = _adk_synthetic_demo_payload()
        except _ExternalRuntimeUnavailable:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                '{"error":"Google ADK合成デモを実行できませんでした。"}'.encode(),
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/agent-platform-synthetic-demo":
        if environ.get("REQUEST_METHOD", "GET") != "POST":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"POSTを使用してください。"}'.encode(),
            )
        if int(str(environ.get("CONTENT_LENGTH", "0")) or "0") != 0:
            return _respond(
                start_response,
                "400 Bad Request",
                "application/json; charset=utf-8",
                '{"error":"クラウドRuntime確認には入力データを送れません。"}'.encode(),
            )
        try:
            payload = _agent_platform_synthetic_demo_payload()
        except _ExternalRuntimeUnavailable:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                '{"error":"クラウドRuntime合成テストを実行できませんでした。"}'.encode(),
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/gemini-director-synthetic-demo":
        if environ.get("REQUEST_METHOD", "GET") != "POST":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"POSTを使用してください。"}'.encode(),
            )
        if int(str(environ.get("CONTENT_LENGTH", "0")) or "0") != 0:
            return _respond(
                start_response,
                "400 Bad Request",
                "application/json; charset=utf-8",
                '{"error":"この確認には入力データを送れません。"}'.encode(),
            )
        try:
            payload = _gemini_director_synthetic_payload()
        except _ExternalRuntimeUnavailable:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                '{"error":"Gemini Director合成デモを実行できませんでした。"}'.encode(),
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    if path == "/api/private-gpx-summary":
        language = resolve_language(query.get("lang", [None])[0])
        try:
            payload = _private_gpx_payload(environ, language)
        except (ElementTree.ParseError, KeyError, OSError, TypeError, ValueError):
            error = (
                "The GPX file could not be analyzed."
                if language is UiLanguage.ENGLISH
                else "GPXを解析できませんでした。"
            )
            return _respond(
                start_response,
                "400 Bad Request",
                "application/json; charset=utf-8",
                json.dumps({"error": error}, ensure_ascii=False).encode(),
            )
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )
    return _respond(
        start_response,
        "404 Not Found",
        "application/json; charset=utf-8",
        b'{"error":"not found"}',
    )


def _private_journey_film(
    environ: dict[str, object], start_response: StartResponse
) -> Iterable[bytes]:
    """Stream the finished film to the owner's browser, with byte ranges.

    A film is hundreds of megabytes, so it is never read whole: the range
    the player asks for is sent from the file in chunks. Only the scored or
    silent film of the current package is ever served -- never a path from
    the request -- and never in the public demo.
    """
    if str(environ.get("REQUEST_METHOD", "GET")).upper() != "GET":
        return _respond(
            start_response,
            "405 Method Not Allowed",
            "application/json; charset=utf-8",
            '{"error":"GETを使用してください。"}'.encode(),
        )
    try:
        film = StoryView(_console().package_directory).film_path()
    except PrivateJourneyConsoleError:
        film = None
    if film is None:
        return _respond(
            start_response,
            "404 Not Found",
            "application/json; charset=utf-8",
            b'{"error":"no film to play yet"}',
        )
    size = film.stat().st_size
    start, end = 0, size - 1
    status = "200 OK"
    header = str(environ.get("HTTP_RANGE", "") or "").strip()
    if header.startswith("bytes="):
        first, _, last = header[6:].partition("-")
        try:
            if first:
                start = int(first)
                end = int(last) if last else size - 1
            elif last:
                start = max(0, size - int(last))
        except ValueError:
            start, end = 0, size - 1
        if start > end or start >= size:
            start_response(
                "416 Range Not Satisfiable",
                [("Content-Range", f"bytes */{size}"), ("Content-Length", "0")],
            )
            return [b""]
        end = min(end, size - 1)
        status = "206 Partial Content"
    length = end - start + 1
    headers = [
        ("Content-Type", "video/mp4"),
        ("Content-Length", str(length)),
        ("Accept-Ranges", "bytes"),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
    ]
    if status.startswith("206"):
        headers.append(("Content-Range", f"bytes {start}-{end}/{size}"))
    start_response(status, headers)

    def chunks() -> Iterable[bytes]:
        remaining = length
        with film.open("rb") as handle:
            handle.seek(start)
            while remaining > 0:
                piece = handle.read(min(1 << 20, remaining))
                if not piece:
                    break
                remaining -= len(piece)
                yield piece

    return chunks()


def _private_journey_intake(
    environ: dict[str, object], start_response: StartResponse, action: str
) -> Iterable[bytes]:
    """Propose a clock offset, build a new day's package, or switch package.

    Paths in the body are accepted only inside the intake root; the offset
    confirmed must be one that was proposed. Both are checked by the intake
    layer with fixed reasons, and nothing here needs the console to exist
    yet -- a machine with no package at all starts here.
    """

    def answer(status: str, payload: dict[str, object]) -> Iterable[bytes]:
        return _respond(
            start_response,
            status,
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )

    if str(environ.get("REQUEST_METHOD", "GET")).upper() != "POST":
        return answer("405 Method Not Allowed", {"error": "POSTを使用してください。"})
    body = _read_small_json_body(environ)
    if body is None:
        return answer("400 Bad Request", {"error": "invalid_request_body"})
    roots = IntakeRoots.from_environment()
    try:
        if action == "propose":
            return answer(
                "200 OK",
                propose_intake(roots, gpx=body.get("gpx"), video_root=body.get("video_root")),
            )
        if action == "select":
            _set_current_package(select_package(roots, body.get("name")))
            return answer("200 OK", {"package": _CURRENT_PACKAGE.name if _CURRENT_PACKAGE else ""})
        job = _PRIVATE_JOURNEY_JOBS.start_intake(
            roots,
            gpx=body.get("gpx"),
            video_root=body.get("video_root"),
            name=body.get("name"),
            offset_s=body.get("offset_s"),
            target_duration_s=body.get("target_duration_s", 300.0),
            on_created=_set_current_package,
        )
    except IntakeRefused as refused:
        return answer("400 Bad Request", {"error": refused.reason})
    except JobRefused as refused:
        status = (
            "409 Conflict" if refused.reason == REASON_ANOTHER_JOB_RUNNING else "400 Bad Request"
        )
        return answer(status, {"error": refused.reason})
    return answer("202 Accepted", {"job": job.to_dict()})


def _private_journey_action(
    environ: dict[str, object], start_response: StartResponse, action: str
) -> Iterable[bytes]:
    """Start one job for the configured package, or say why not.

    POST only, with a small JSON body. Buying a judgement must carry the
    figure the console showed, to the yen, and a bucket; anything else is
    refused here, before the job -- and any Google import -- exists.
    """

    def answer(status: str, payload: dict[str, object]) -> Iterable[bytes]:
        return _respond(
            start_response,
            status,
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False).encode(),
        )

    if str(environ.get("REQUEST_METHOD", "GET")).upper() != "POST":
        return answer("405 Method Not Allowed", {"error": "POSTを使用してください。"})
    try:
        console = _console()
    except PrivateJourneyConsoleError:
        return answer(
            "503 Service Unavailable", {"error": "private journey console is unavailable"}
        )
    body = _read_small_json_body(environ)
    if body is None:
        return answer("400 Bad Request", {"error": "invalid_request_body"})
    package = console.package_directory
    try:
        if action == "preflight":
            job = _PRIVATE_JOURNEY_JOBS.start_preflight(package)
        elif action == "judge":
            planned = next(
                (s for s in console.payload()["stages"] if s.get("key") == "footage_planned"),
                None,
            )
            if planned is None or planned.get("state") != "done":
                return answer("409 Conflict", {"error": "footage_cannot_be_planned"})
            job = _PRIVATE_JOURNEY_JOBS.start_judge(
                package,
                figure_jpy=float(planned["cost_jpy"]),
                approve_jpy=body.get("approve_jpy"),
                bucket=body.get("bucket"),
            )
        else:
            job = _PRIVATE_JOURNEY_JOBS.start_film(package, music_track_id=body.get("music"))
    except JobRefused as refused:
        status = (
            "409 Conflict" if refused.reason == REASON_ANOTHER_JOB_RUNNING else "400 Bad Request"
        )
        return answer(status, {"error": refused.reason})
    return answer("202 Accepted", {"job": job.to_dict()})


def _read_small_json_body(environ: dict[str, object], *, limit: int = 4096) -> dict | None:
    """A JSON object of at most a few kilobytes, or None if it is not one."""
    try:
        length = int(str(environ.get("CONTENT_LENGTH", "") or "0"))
    except ValueError:
        return None
    if length < 0 or length > limit:
        return None
    stream = environ.get("wsgi.input")
    raw = stream.read(length) if length and hasattr(stream, "read") else b""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _respond(
    start_response: StartResponse,
    status: str,
    content_type: str,
    body: bytes,
    *,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> Iterable[bytes]:
    start_response(
        status,
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            *extra_headers,
        ],
    )
    return [body]


def _public_demo_auth_error(
    environ: dict[str, object], deployment: WebDeploymentSettings
) -> tuple[str, bytes] | None:
    """Require the shared judge credential, only when one has been configured.

    Comparing with `hmac.compare_digest` keeps a wrong guess from being
    distinguishable by response timing. A missing header, a malformed header,
    and a wrong password all fail the identical way -- there is no separate
    "you forgot to log in" response that would help guess the credential.
    """

    if not deployment.basic_auth_required:
        return None
    header = str(environ.get("HTTP_AUTHORIZATION", "") or "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return "401 Unauthorized", b'{"error":"authentication required"}'
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return "401 Unauthorized", b'{"error":"authentication required"}'
    username, separator, password = decoded.partition(":")
    valid_username = hmac.compare_digest(username, deployment.basic_auth_username or "")
    valid_password = hmac.compare_digest(password, deployment.basic_auth_password or "")
    if separator and valid_username and valid_password:
        return None
    return "401 Unauthorized", b'{"error":"authentication required"}'


def _public_demo_request_error(
    environ: dict[str, object],
) -> tuple[str, bytes] | None:
    raw_content_length = str(environ.get("CONTENT_LENGTH", "") or "").strip()
    transfer_encoding = str(environ.get("HTTP_TRANSFER_ENCODING", "") or "").strip()
    try:
        content_length = int(raw_content_length or "0")
    except ValueError:
        return "400 Bad Request", b'{"error":"invalid content length"}'
    if content_length < 0:
        return "400 Bad Request", b'{"error":"invalid content length"}'
    if content_length > 0 or transfer_encoding:
        return "413 Payload Too Large", b'{"error":"request body disabled in public demo"}'
    if str(environ.get("REQUEST_METHOD", "GET")).upper() != "GET":
        return "405 Method Not Allowed", b'{"error":"GET required in public demo"}'
    return None


def _demo_payload(scenario: str, language: UiLanguage) -> dict[str, object]:
    event = build_demo_event()
    run = run_demo(scenario, StoryOutputLanguage(language.value))
    return {
        "demo_mode": True,
        "language": language.value,
        "notice": (
            "This uses only a synthetic GPS event and mock video analysis."
            if language is UiLanguage.ENGLISH
            else "合成GPSイベントとモック映像解析のみを使用しています。"
        ),
        "scenario": {"id": run.scenario, "label": run.label},
        "event": {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "importance_hint": event.importance_hint,
            "evidence": list(event.evidence),
            "clip_seconds": [
                event.video_query.clip_start_offset_s,
                event.video_query.clip_end_offset_s,
            ],
        },
        "decision": run.decision.to_dict(),
        "steps": list(run.steps),
        "evidence_record": {
            "schema_version": "demo-v1",
            "private_data_used": False,
            "external_services_called": [],
            "scenario": run.scenario,
        },
    }


def _candidate_review_payload(
    review: CandidateEditReview,
    language: UiLanguage,
) -> dict[str, object]:
    """Translate review prose from structural fields without changing the review."""
    localized = review.to_dict()
    copy = copy_for(language)
    reasons: list[str] = []
    if review.missing_duration_s > 0:
        reasons.append(copy["candidate.reason.duration"])
    if review.event_ids_requiring_evidence:
        reasons.append(copy["candidate.reason.awaiting"])
    if review.rejected_event_ids:
        reasons.append(copy["candidate.reason.rejected"])
    localized["reasons"] = reasons
    return localized


def _google_runtime_payload() -> dict[str, object]:
    try:
        from app.agent_runtime import GoogleCloudRuntimeSettings
    except (ImportError, ModuleNotFoundError) as error:
        raise _ExternalRuntimeUnavailable("Google Cloud support is not installed") from error
    settings = GoogleCloudRuntimeSettings.from_environment()
    return {
        "private_data_used": False,
        "notice": "設定状態のみを表示します。GPX・映像・認証情報は使用しません。",
        "google_cloud_configuration": settings.to_dict(),
        "synthetic_adk_demo_available": settings.status == "configuration_present",
    }


def _agent_platform_preflight_payload() -> dict[str, object]:
    try:
        from app.agent_runtime import AgentPlatformDeploymentSettings
    except (ImportError, ModuleNotFoundError) as error:
        raise _ExternalRuntimeUnavailable("Agent Platform support is not installed") from error
    settings = AgentPlatformDeploymentSettings.from_environment()
    return {
        "private_data_used": False,
        "notice": (
            "設定状態だけを確認します。クラウドリソースの作成、ソースのアップロード、"
            "実GPS・映像の送信は行いません。"
        ),
        "agent_platform_preflight": settings.to_dict(),
    }


def _adk_synthetic_demo_payload() -> dict[str, object]:
    try:
        from app.agent_runtime import (
            AdkSyntheticRunError,
            GoogleCloudRuntimeSettings,
            run_synthetic_adk_demo,
        )
    except (ImportError, ModuleNotFoundError) as error:
        raise _ExternalRuntimeUnavailable("Google ADK support is not installed") from error
    try:
        result = asyncio.run(run_synthetic_adk_demo(GoogleCloudRuntimeSettings.from_environment()))
    except AdkSyntheticRunError as error:
        raise _ExternalRuntimeUnavailable("Google ADK synthetic demo is unavailable") from error
    return {
        "private_data_used": False,
        "notice": "固定の合成イベントだけをGoogle ADK / Geminiへ送信しました。",
        "adk_synthetic_demo": result.to_dict(),
    }


def _agent_platform_synthetic_demo_payload() -> dict[str, object]:
    try:
        from app.agent_runtime import (
            AgentPlatformDeploymentError,
            AgentPlatformDeploymentSettings,
            AgentPlatformPreparationError,
            GoogleCloudRuntimeSettings,
            run_hosted_synthetic_agent_runtime,
        )
    except (ImportError, ModuleNotFoundError) as error:
        raise _ExternalRuntimeUnavailable("Agent Platform support is not installed") from error
    try:
        runtime = GoogleCloudRuntimeSettings.from_environment()
        deployment = AgentPlatformDeploymentSettings.from_environment(runtime)
        result = run_hosted_synthetic_agent_runtime(deployment)
    except (
        AgentPlatformDeploymentError,
        AgentPlatformPreparationError,
    ) as error:
        raise _ExternalRuntimeUnavailable("Hosted Agent Runtime is unavailable") from error
    return {
        "private_data_used": False,
        "external_service_called": True,
        "billing_may_apply": True,
        "notice": ("作成済みの合成専用Agent Runtimeへ固定の合成イベントだけを送信しました。"),
        "agent_platform_synthetic_demo": {
            "model": runtime.model,
            "runtime_location": deployment.location,
            **result.to_dict(),
        },
    }


def _gemini_director_synthetic_payload() -> dict[str, object]:
    """Run the Director through Gemini using only fixed synthetic events.

    The request body is forbidden by the HTTP handler, and the event fixture
    is built locally in ``app.demo``.  This is deliberately separate from the
    private-media Director pipeline: it proves the cloud Director contract
    without sending route, video, coordinate, or source-identity data.
    """
    try:
        from app.agents.vertex_director import VertexAIGeminiDirectorTransport
    except (ImportError, ModuleNotFoundError) as error:
        raise _ExternalRuntimeUnavailable("Gemini Director support is not installed") from error

    try:
        transport = VertexAIGeminiDirectorTransport.from_environment()
    except ValueError as error:
        raise _ExternalRuntimeUnavailable("Gemini Director is not configured") from error

    return _synthetic_director_payload_from_transport(transport)


def _synthetic_director_payload_from_transport(transport: object) -> dict[str, object]:
    """Compose only the fixed fixture and make fallback observable in tests.

    The helper accepts a transport boundary rather than a Vertex client so unit
    tests can exercise Gemini failure and the RuleBased fallback without a
    credential, network, or billable request.
    """
    from app.director import (
        FallbackDirector,
        GeminiDirector,
        RuleBasedDirector,
        browser_safe_script_view,
    )

    script = FallbackDirector(
        GeminiDirector(transport),  # type: ignore[arg-type]
        RuleBasedDirector(),
    ).compose(build_synthetic_director_events())

    return {
        "demo_mode": True,
        "private_data_used": False,
        "external_service_called": True,
        "billing_may_apply": True,
        "notice": "固定の合成イベントだけをGemini Directorへ送信しました。",
        "director_script": browser_safe_script_view(
            script,
            fallback_used=script.metadata.composer == "rule_based",
        ),
    }


def _private_gpx_payload(
    environ: dict[str, object],
    language: UiLanguage,
) -> dict[str, object]:
    """Parse a browser-supplied GPX in memory and return no route coordinates."""
    content_length = int(str(environ.get("CONTENT_LENGTH", "0")) or "0")
    if not 0 < content_length <= 20 * 1024 * 1024:
        raise ValueError("GPX upload must be between 1 byte and 20 MiB")
    stream = environ.get("wsgi.input", BytesIO())
    contents = stream.read(content_length)  # type: ignore[union-attr]
    route = parse_gpx_bytes(contents)
    raw_events = extract_events(route, asset_name_hint="unmatched_source.mp4")
    events = consolidate_events(raw_events)
    story_plan = RuleBasedStoryPlanner().plan(
        route.summary,
        events,
        target_duration_s=480,
        output_language=StoryOutputLanguage(language.value),
    )
    candidate_plan = build_candidate_edit_plan(story_plan, events)
    review = review_candidate_edit_plan(candidate_plan)
    localized_review = _candidate_review_payload(review, language)
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1
    return {
        "local_only": True,
        "language": language.value,
        "notice": (
            "The GPX was analyzed in memory and was not stored or sent externally."
            if language is UiLanguage.ENGLISH
            else "GPXはメモリ上で解析し、保存・外部送信していません。"
        ),
        "route_summary": {
            "point_count": route.summary.point_count,
            "distance_km": round(route.summary.total_distance_m / 1_000, 1),
            "duration_minutes": round(route.summary.duration_s / 60, 1),
            "elevation_gain_m": round(route.summary.elevation_gain_m),
            "elevation_loss_m": round(route.summary.elevation_loss_m),
        },
        "event_counts": event_counts,
        "raw_event_count": len(raw_events),
        "consolidated_event_count": len(events),
        "story_plan": {
            "title": story_plan.title,
            "chapter_roles": [chapter.narrative_role for chapter in story_plan.chapters],
        },
        "candidate_edit_plan": {
            "candidate_duration_s": candidate_plan.candidate_duration_s,
            "coverage_ratio": candidate_plan.coverage_ratio,
            "is_ready_for_edit": review.is_ready_for_edit,
            "reasons": localized_review["reasons"],
            "missing_duration_s": review.missing_duration_s,
            "awaiting_evidence_count": len(review.event_ids_requiring_evidence),
            "rejected_evidence_count": len(review.rejected_event_ids),
        },
    }


def _update_private_highlight_review(
    session: PrivateHighlightReviewSession,
    environ: dict[str, object],
) -> dict[str, object]:
    """Accept one bounded, fixed-vocabulary local review decision."""
    if not _private_review_origin_is_local(environ):
        raise ValueError("private review update must come from a loopback origin")
    content_length = int(str(environ.get("CONTENT_LENGTH", "0")) or "0")
    if not 0 < content_length <= 8 * 1024:
        raise ValueError("private review request must be between 1 byte and 8 KiB")
    stream = environ.get("wsgi.input", BytesIO())
    raw_payload = stream.read(content_length)  # type: ignore[union-attr]
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict) or set(payload) != {"candidate_id", "status", "reasons"}:
        raise ValueError("private review request shape is invalid")
    candidate_id = payload["candidate_id"]
    raw_status = payload["status"]
    raw_reasons = payload["reasons"]
    if (
        not isinstance(candidate_id, str)
        or not isinstance(raw_status, str)
        or not isinstance(raw_reasons, list)
        or not all(isinstance(reason, str) for reason in raw_reasons)
    ):
        raise ValueError("private review request values are invalid")
    return session.update(
        candidate_id=candidate_id,
        status=HighlightReviewStatus(raw_status),
        reasons=tuple(HighlightReviewReason(reason) for reason in raw_reasons),
    )


def _update_private_highlight_reinforcement_review(
    session: PrivateHighlightReinforcementReviewSession,
    environ: dict[str, object],
) -> dict[str, object]:
    """Accept exactly one opaque review token naming a candidate to use.

    Never accepts a raw event_id or candidate_id: the token is the only
    input, and it is resolved and re-validated entirely server-side.
    """
    if not _private_review_origin_is_local(environ):
        raise ValueError("private review update must come from a loopback origin")
    content_length = int(str(environ.get("CONTENT_LENGTH", "0")) or "0")
    if not 0 < content_length <= 1024:
        raise ValueError("private review request must be between 1 byte and 1 KiB")
    stream = environ.get("wsgi.input", BytesIO())
    raw_payload = stream.read(content_length)  # type: ignore[union-attr]
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict) or set(payload) != {"review_token"}:
        raise ValueError("private review request shape is invalid")
    review_token = payload["review_token"]
    if not isinstance(review_token, str):
        raise ValueError("private review request values are invalid")
    return session.update(review_token=review_token)


def _update_private_evidence_review(
    session: PrivateEvidenceReviewSession,
    environ: dict[str, object],
) -> dict[str, object]:
    """Accept one bounded local visual-evidence decision."""
    if not _private_review_origin_is_local(environ):
        raise ValueError("private review update must come from a loopback origin")
    content_length = int(str(environ.get("CONTENT_LENGTH", "0")) or "0")
    if not 0 < content_length <= 2 * 1024:
        raise ValueError("private review request must be between 1 byte and 2 KiB")
    stream = environ.get("wsgi.input", BytesIO())
    raw_payload = stream.read(content_length)  # type: ignore[union-attr]
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict) or set(payload) != {"review_id", "status"}:
        raise ValueError("private review request shape is invalid")
    review_id = payload["review_id"]
    raw_status = payload["status"]
    if not isinstance(review_id, str) or not isinstance(raw_status, str):
        raise ValueError("private review request values are invalid")
    return session.update(
        review_id=review_id,
        status=CandidateEvidenceStatus(raw_status),
    )


def _private_review_origin_is_local(environ: dict[str, object]) -> bool:
    """Reject browser-originated writes from another site while allowing local tooling."""
    raw_origin = str(environ.get("HTTP_ORIGIN", "") or "").strip()
    if not raw_origin:
        return True
    parsed = urlsplit(raw_origin)
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and not parsed.username
        and not parsed.password
        and not parsed.path.rstrip("/")
        and not parsed.query
        and not parsed.fragment
    )


def _private_highlight_review_page(language: UiLanguage) -> str:
    """Render a local-only review page with no source identifiers or external scripts."""
    english = language is UiLanguage.ENGLISH
    strings = {
        "title": "Private highlight review" if english else "私用ハイライト確認",
        "intro": (
            "This page reads and writes only the explicitly configured local review package. "
            "No media or GPS data is uploaded."
            if english
            else "この画面は、明示設定したローカル確認パッケージだけを読み書きします。映像・GPSはアップロードしません。"
        ),
        "loading": "Loading local candidates…" if english else "ローカル候補を読み込み中…",
        "approved": "Approve" if english else "採用",
        "rejected": "Reject" if english else "却下",
        "awaiting": "Awaiting" if english else "未判断",
        "save": "Save decision" if english else "判断を保存",
        "saved": "Saved locally." if english else "ローカルに保存しました。",
        "failed": "The local review could not be updated."
        if english
        else "ローカルreviewを更新できませんでした。",
        "status": "Decision" if english else "判断",
        "reason": "Reason" if english else "理由",
        "summary": "Approved {approved} / Rejected {rejected} / Awaiting {awaiting}"
        if english
        else "採用 {approved} / 却下 {rejected} / 未判断 {awaiting}",
        "back": "Back to demo" if english else "デモへ戻る",
    }
    reason_labels = (
        {
            "clear_turn": "clear turn",
            "temporal_event": "temporal event",
            "scenic_context": "scenic context",
            "story_useful": "story useful",
            "too_straight": "too straight",
            "stopped_or_slow": "stopped or slow",
            "low_visual_change": "low visual change",
            "poor_road_context": "poor road context",
            "duplicate": "duplicate",
            "other": "other",
        }
        if english
        else {
            "clear_turn": "明確な旋回",
            "temporal_event": "時間的な映像変化",
            "scenic_context": "景観・道路文脈",
            "story_useful": "物語に有用",
            "too_straight": "直線走行が多い",
            "stopped_or_slow": "停止または低速",
            "low_visual_change": "映像変化が少ない",
            "poor_road_context": "道路文脈が不十分",
            "duplicate": "重複",
            "other": "その他",
        }
    )
    text = {key: escape(value) for key, value in strings.items()}
    strings_json = json.dumps(strings, ensure_ascii=False).replace("<", "\\u003c")
    reason_labels_json = json.dumps(reason_labels, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="{language.value}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ride Storyteller — {text["title"]}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}}article{{border:1px solid #d7dde5;border-radius:12px;padding:14px}}img,video{{display:block;width:100%;border-radius:8px;background:#17212b;margin:8px 0}}select,button{{font:inherit;padding:8px;margin:5px 0}}button{{background:#1264d6;color:#fff;border:0;border-radius:7px;cursor:pointer}}.status{{font-weight:700}}#notice{{padding:12px;background:#f2f7ff;border-radius:8px}}.reason-wrap[hidden]{{display:none}}small{{color:#53606d}}</style>
</head><body><main><p><a href="/?lang={language.value}">{text["back"]}</a></p><h1>{text["title"]}</h1><p>{text["intro"]}</p><p id="notice" aria-live="polite">{text["loading"]}</p><section id="cards" class="grid"></section>
<script>
const text={strings_json};
const reasonLabels={reason_labels_json};
const reasons={{approved:['clear_turn','temporal_event','scenic_context','story_useful'],rejected:['too_straight','stopped_or_slow','low_visual_change','poor_road_context','duplicate','other']}};
const notice=document.querySelector('#notice'),cards=document.querySelector('#cards');
function summary(counts){{return text.summary.replace('{{approved}}',counts.approved).replace('{{rejected}}',counts.rejected).replace('{{awaiting}}',counts.awaiting)}}
function reasonOptions(status,current){{if(status==='awaiting')return [];return reasons[status].map(value=>[value,reasonLabels[value],current===value])}}
function setReasonOptions(select,status,current){{select.replaceChildren();for(const [value,label,selected] of reasonOptions(status,current)){{const option=document.createElement('option');option.value=value;option.textContent=label;option.selected=selected;select.append(option)}}}}
function card(candidate){{const article=document.createElement('article'),title=document.createElement('h2'),image=document.createElement('img'),video=document.createElement('video'),statusLabel=document.createElement('label'),status=document.createElement('select'),reasonWrap=document.createElement('label'),reason=document.createElement('select'),save=document.createElement('button');title.textContent=`${{candidate.method}} / #${{candidate.rank}}`;image.src=candidate.thumbnail_url;image.loading='lazy';image.alt='review thumbnail';video.src=candidate.media_url;video.controls=true;video.preload='none';for(const [value,label] of [['approved',text.approved],['rejected',text.rejected],['awaiting',text.awaiting]]){{const option=document.createElement('option');option.value=value;option.textContent=label;option.selected=candidate.status===value;status.append(option)}}statusLabel.textContent=text.status+' ';statusLabel.append(status);reasonWrap.textContent=text.reason+' ';reasonWrap.className='reason-wrap';reasonWrap.append(reason);setReasonOptions(reason,candidate.status,candidate.reasons[0]);reasonWrap.hidden=candidate.status==='awaiting';status.addEventListener('change',()=>{{setReasonOptions(reason,status.value,'');reasonWrap.hidden=status.value==='awaiting'}});save.textContent=text.save;save.addEventListener('click',async()=>{{save.disabled=true;try{{const response=await fetch('/api/private-highlight-review',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{candidate_id:candidate.candidate_id,status:status.value,reasons:status.value==='awaiting'?[]:[reason.value]}})}});if(!response.ok)throw Error();const payload=await response.json(),updatedCandidate=payload.review.candidates.find(item=>item.candidate_id===candidate.candidate_id);if(!updatedCandidate)throw Error();candidate.status=updatedCandidate.status;candidate.reasons=updatedCandidate.reasons;notice.textContent=`${{text.saved}} ${{summary(payload.review.status_counts)}}`}}catch(error){{notice.textContent=text.failed}}finally{{save.disabled=false}}}});article.append(title,image,video,statusLabel,reasonWrap,save);return article}}
function render(payload){{cards.replaceChildren(...payload.review.candidates.map(card));notice.textContent=summary(payload.review.status_counts)}}
fetch('/api/private-highlight-review').then(response=>{{if(!response.ok)throw Error();return response.json()}}).then(render).catch(()=>{{notice.textContent=text.failed}});
</script></main></body></html>"""


def _private_highlight_reinforcement_review_page(language: UiLanguage) -> str:
    """Render a local-only conflict review page with no event/candidate identifiers."""
    english = language is UiLanguage.ENGLISH
    strings = {
        "title": "Private highlight reinforcement review"
        if english
        else "私用ハイライト補強の確認",
        "intro": (
            "This page reads and writes only the explicitly configured local review package. "
            "No media or GPS data is uploaded."
            if english
            else "この画面は、明示設定したローカル確認パッケージだけを読み書きします。映像・GPSはアップロードしません。"
        ),
        "loading": "Loading local conflicts…" if english else "ローカルの競合を読み込み中…",
        "empty": "No unresolved conflicts." if english else "未解決の競合はありません。",
        "loaded": "{count} unresolved conflict(s)." if english else "未解決の競合 {count} 件。",
        "conflict": "Conflict" if english else "競合",
        "save": "Use this candidate" if english else "この候補を使う",
        "saved": "Saved locally." if english else "ローカルに保存しました。",
        "failed": "The local reinforcement review could not be updated."
        if english
        else "ローカルの補強確認を更新できませんでした。",
        "back": "Back to demo" if english else "デモへ戻る",
    }
    text = {key: escape(value) for key, value in strings.items()}
    strings_json = json.dumps(strings, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="{language.value}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ride Storyteller — {text["title"]}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin:10px 0 22px}}article{{border:1px solid #d7dde5;border-radius:12px;padding:12px}}img,video{{display:block;width:100%;border-radius:8px;background:#17212b;margin:8px 0}}button{{font:inherit;padding:8px;margin:5px 0;background:#1264d6;color:#fff;border:0;border-radius:7px;cursor:pointer}}#notice{{padding:12px;background:#f2f7ff;border-radius:8px}}</style>
</head><body><main><p><a href="/?lang={language.value}">{text["back"]}</a></p><h1>{text["title"]}</h1><p>{text["intro"]}</p><p id="notice" aria-live="polite">{text["loading"]}</p><section id="groups"></section>
<script>
const text={strings_json};
const notice=document.querySelector('#notice'),groupsEl=document.querySelector('#groups');
function option(item){{const article=document.createElement('article'),title=document.createElement('h3'),image=document.createElement('img'),video=document.createElement('video'),save=document.createElement('button');title.textContent=`${{item.method}} / #${{item.rank}}`;image.src=item.thumbnail_url;image.loading='lazy';image.alt='review thumbnail';video.src=item.media_url;video.controls=true;video.preload='none';save.textContent=text.save;save.addEventListener('click',async()=>{{save.disabled=true;try{{const response=await fetch('/api/private-highlight-reinforcement-review',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{review_token:item.review_token}})}});if(!response.ok)throw Error();notice.textContent=text.saved}}catch(error){{notice.textContent=text.failed}}finally{{save.disabled=false}}}});article.append(title,image,video,save);return article}}
function group(conflict,index){{const section=document.createElement('section'),heading=document.createElement('h2'),grid=document.createElement('div');heading.textContent=`${{text.conflict}} ${{index+1}}`;grid.className='grid';grid.append(...conflict.options.map(option));section.append(heading,grid);return section}}
function render(payload){{groupsEl.replaceChildren(...payload.review.conflicts.map(group));notice.textContent=payload.review.conflict_count>0?text.loaded.replace('{{count}}',payload.review.conflict_count):text.empty}}
fetch('/api/private-highlight-reinforcement-review').then(response=>{{if(!response.ok)throw Error();return response.json()}}).then(render).catch(()=>{{notice.textContent=text.failed}});
</script></main></body></html>"""


def _private_highlight_reinforcement_review_setup_page(language: UiLanguage) -> str:
    """Show local-only setup guidance without exposing a path or configuration value."""
    english = language is UiLanguage.ENGLISH
    title = "Private highlight reinforcement review" if english else "私用ハイライト補強の確認"
    explanation = (
        "This private review is not configured on this device yet."
        if english
        else "この端末では、私用のハイライト補強確認がまだ設定されていません。"
    )
    steps = (
        (
            "Set the local package directory using the environment setting below. "
            "Do not enter that directory in a public service."
        )
        if english
        else "下記の環境設定に、ローカルの確認パッケージdirectoryを指定します。公開サービスへ入力しません。"
    )
    restart = (
        "Restart the local Ride Storyteller server, then reopen this page."
        if english
        else "Ride Storytellerのローカルサーバーを再起動してから、この画面を開き直します。"
    )
    return f"""<!doctype html>
<html lang=\"{language.value}\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>Ride Storyteller — {escape(title)}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,\"Hiragino Sans\",sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}code{{background:#e9edf2;padding:2px 4px;border-radius:4px;overflow-wrap:anywhere}}li{{margin:12px 0}}</style>
</head><body><main><p><a href=\"/?lang={language.value}\">{escape("Back to demo" if english else "デモへ戻る")}</a></p><h1>{escape(title)}</h1><p>{escape(explanation)}</p><ol><li>{escape(steps)}<br><code>{PRIVATE_HIGHLIGHT_REINFORCEMENT_REVIEW_DIRECTORY_ENV}</code></li><li>{escape(restart)}</li></ol></main></body></html>"""


def _private_evidence_review_page(language: UiLanguage) -> str:
    """Render a local-only human visual-evidence review page."""
    english = language is UiLanguage.ENGLISH
    strings = {
        "title": "Private visual-evidence review" if english else "私用の映像証拠確認",
        "intro": (
            "Confirm only whether each private review clip is valid visual evidence. "
            "This is separate from highlight quality labels, and no media or GPS data is uploaded."
            if english
            else "各確認用クリップが映像証拠として使えるかだけを判断します。ハイライト品質の採用とは別で、映像・GPSはアップロードしません。"
        ),
        "loading": "Loading local review clips…"
        if english
        else "ローカル確認用クリップを読み込み中…",
        "confirmed": "Confirm evidence" if english else "証拠として確認",
        "rejected": "Reject evidence" if english else "証拠として却下",
        "awaiting": "Undecided" if english else "未判断へ戻す",
        "save": "Save decision" if english else "判断を保存",
        "saved": "Saved locally." if english else "ローカルに保存しました。",
        "failed": "The local evidence review could not be updated."
        if english
        else "ローカル証拠確認を更新できませんでした。",
        "status": "Visual evidence" if english else "映像証拠",
        "summary": "Confirmed {confirmed} / Rejected {rejected} / Awaiting {awaiting}"
        if english
        else "確認 {confirmed} / 却下 {rejected} / 未判断 {awaiting}",
        "next": "Next local step" if english else "次のローカル手順",
        "back": "Back to demo" if english else "デモへ戻る",
    }
    gate_labels = {
        "human_visual_evidence_review": (
            "Review every clip before creating the story."
            if english
            else "物語を作る前に、すべてのクリップを確認します。"
        ),
        "replace_rejected_candidate_clips": (
            "Replace rejected evidence before creating the story."
            if english
            else "物語を作る前に、却下した映像証拠を差し替えます。"
        ),
        "revalidate_local_pipeline": (
            "Revalidate the local pipeline before creating the story."
            if english
            else "物語を作る前に、ローカルpipelineを再検証します。"
        ),
    }
    text = {key: escape(value) for key, value in strings.items()}
    strings_json = json.dumps(strings, ensure_ascii=False).replace("<", "\\u003c")
    gate_labels_json = json.dumps(gate_labels, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="{language.value}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ride Storyteller — {text["title"]}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}}article{{border:1px solid #d7dde5;border-radius:12px;padding:14px}}video{{display:block;width:100%;border-radius:8px;background:#17212b;margin:8px 0}}select,button{{font:inherit;padding:8px;margin:5px 0}}button{{background:#1264d6;color:#fff;border:0;border-radius:7px;cursor:pointer}}#notice{{padding:12px;background:#f2f7ff;border-radius:8px}}</style>
</head><body><main><p><a href="/?lang={language.value}">{text["back"]}</a></p><h1>{text["title"]}</h1><p>{text["intro"]}</p><p id="notice" aria-live="polite">{text["loading"]}</p><section id="cards" class="grid"></section>
<script>
const text={strings_json},gateLabels={gate_labels_json};
const notice=document.querySelector('#notice'),cards=document.querySelector('#cards');
function summary(counts,nextGate){{return text.summary.replace('{{confirmed}}',counts.confirmed).replace('{{rejected}}',counts.rejected).replace('{{awaiting}}',counts.awaiting_video_evidence)+' / '+text.next+': '+(gateLabels[nextGate]||text.failed)}}
function card(candidate){{const article=document.createElement('article'),title=document.createElement('h2'),video=document.createElement('video'),statusLabel=document.createElement('label'),status=document.createElement('select'),save=document.createElement('button');title.textContent=candidate.review_id;video.src=candidate.media_url;video.controls=true;video.preload='metadata';for(const [value,label] of [['confirmed',text.confirmed],['rejected',text.rejected],['awaiting_video_evidence',text.awaiting]]){{const option=document.createElement('option');option.value=value;option.textContent=label;option.selected=candidate.status===value;status.append(option)}}statusLabel.textContent=text.status+' ';statusLabel.append(status);save.textContent=text.save;save.addEventListener('click',async()=>{{save.disabled=true;try{{const response=await fetch('/api/private-evidence-review',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{review_id:candidate.review_id,status:status.value}})}});if(!response.ok)throw Error();const payload=await response.json(),updatedCandidate=payload.review.candidates.find(item=>item.review_id===candidate.review_id);if(!updatedCandidate)throw Error();candidate.status=updatedCandidate.status;notice.textContent=`${{text.saved}} ${{summary(payload.review.status_counts,payload.next_gate)}}`}}catch(error){{notice.textContent=text.failed}}finally{{save.disabled=false}}}});article.append(title,video,statusLabel,save);return article}}
function render(payload){{cards.replaceChildren(...payload.review.candidates.map(card));notice.textContent=summary(payload.review.status_counts,payload.next_gate)}}
fetch('/api/private-evidence-review').then(response=>{{if(!response.ok)throw Error();return response.json()}}).then(render).catch(()=>{{notice.textContent=text.failed}});
</script></main></body></html>"""


def _private_evidence_review_setup_page(language: UiLanguage) -> str:
    """Show local-only setup guidance without exposing a path or configuration value."""
    english = language is UiLanguage.ENGLISH
    title = "Private visual-evidence review" if english else "私用の映像証拠確認"
    explanation = (
        "This private review is not configured on this device yet."
        if english
        else "この端末では、私用の映像証拠確認がまだ設定されていません。"
    )
    steps = (
        (
            "Set the local package directory using the environment setting below. "
            "Do not enter that directory in a public service."
        )
        if english
        else "下記の環境設定に、ローカルの確認パッケージdirectoryを指定します。公開サービスへ入力しません。"
    )
    restart = (
        "Restart the local Ride Storyteller server, then reopen this page."
        if english
        else "Ride Storytellerのローカルサーバーを再起動してから、この画面を開き直します。"
    )
    return f"""<!doctype html>
<html lang=\"{language.value}\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>Ride Storyteller — {escape(title)}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,\"Hiragino Sans\",sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}code{{background:#e9edf2;padding:2px 4px;border-radius:4px;overflow-wrap:anywhere}}li{{margin:12px 0}}</style>
</head><body><main><p><a href=\"/?lang={language.value}\">{escape("Back to demo" if english else "デモへ戻る")}</a></p><h1>{escape(title)}</h1><p>{escape(explanation)}</p><ol><li>{escape(steps)}<br><code>RIDE_PRIVATE_EVIDENCE_REVIEW_DIRECTORY</code></li><li>{escape(restart)}</li></ol></main></body></html>"""


def _journey_workflow_page(language: UiLanguage) -> str:
    """The product-facing page: one path from intake to the finished film.

    It renders without a configured package on purpose -- the page itself
    asks `/api/private-journey` and shows the intake form when that answers
    503 -- and it offers exactly the music the actions module will accept.
    Every private route it calls is already refused in the public demo, and
    so is this page.
    """
    return render_journey_workflow_page(language, track_ids=MUSIC_TRACK_IDS)


def _private_journey_console_page(language: UiLanguage) -> str:
    """One page from "what would judging cost" to "watch the film".

    Read-only for now: it shows the figure a person needs before spending,
    how far the copies and the judgement have got, and what the film is.
    It starts nothing. While a stage is in progress it re-reads every few
    seconds, so a judgement being bought can be watched arriving.
    """
    english = language is UiLanguage.ENGLISH
    strings = {
        "title": "This ride, judged" if english else "この旅の判定と作品",
        "intro": (
            "From what judging this footage would send and cost, through the copies "
            "made and the judgement bought, to the film. Making copies and cutting the "
            "film are local and free. Buying the judgement uploads the copies and bills "
            "for it, and starts only when the figure shown is typed back and approved."
            if english
            else "この映像を判定すると何を送りいくら掛かるかから、縮小コピーの準備、"
            "判定の購入、作品の生成まで。コピー作成と作品生成はローカルで無料です。"
            "判定の購入はコピーを送信して課金します——表示された金額を入力して"
            "承認したときだけ始まります。"
        ),
        "stages": "Stages" if english else "進行",
        "chapters": "Chapters the film will show" if english else "作品に出る章",
        "next": "Next step" if english else "次の操作",
        "loading": "Loading…" if english else "読み込み中…",
        "unavailable": (
            'No day has been brought in on this machine yet. Start with "Bring in a new day" below.'
            if english
            else "この端末にはまだ取り込んだ日がありません。下の「別の日のクリップを取り込む」から始めてください。"
        ),
        "candidates": "windows" if english else "候補",
        "watched": "to be judged" if english else "判定対象",
        "upload": "to send" if english else "送信",
        "cost": "cost" if english else "費用",
        "budget": "ceiling" if english else "上限",
        "prepared": "copies made" if english else "コピー作成",
        "judged": "judged" if english else "判定済み",
        "beats": "scenes" if english else "場面",
        "duration": "duration" if english else "尺",
        "footage_total": "of judged footage" if english else "判定映像の合計",
        "size": "size" if english else "容量",
        "subtitles": "subtitle files" if english else "字幕",
        "yen": "¥",
        "do_preflight": "Make the copies (free, local)"
        if english
        else "縮小コピーを作る（無料・ローカル）",
        "approve_label": (
            "Type the figure shown to approve it" if english else "承認する金額を、表示どおりに入力"
        ),
        "bucket_label": "Where to send it (cloud storage location name)"
        if english
        else "送り先（クラウドの保管場所の名前）",
        "do_judge": "Approve and judge (this spends money)"
        if english
        else "承認して判定させる（課金）",
        "music_label": "Music" if english else "音楽",
        "do_film": "Make the film (free, local)" if english else "作品を生成する（無料・ローカル）",
        "job_running": "Running" if english else "実行中",
        "job_done": "Finished" if english else "完了",
        "job_failed": "Failed" if english else "失敗",
        "refused": "Refused" if english else "拒否",
        "package": "Day being viewed" if english else "見ている日",
        "switch": "Switch" if english else "切替",
        "intake": "Bring in a new day" if english else "別の日のクリップを取り込む",
        "intake_help": (
            "Paths are read only inside the intake folder on this machine. Propose the clock "
            "offset first; the day is brought in only with a proposed number."
            if english
            else "パスはこの端末の取り込みフォルダ内だけ読みます。まず時計のズレを提案させ、"
            "提案された数字でだけ、その日を取り込めます。"
        ),
        "gpx": "GPX file (inside the intake folder)"
        if english
        else "GPXファイル（取り込みフォルダ内）",
        "video_root": "Footage folder (inside the intake folder)"
        if english
        else "動画フォルダ（取り込みフォルダ内）",
        "propose": "Propose the clock offset" if english else "時計のズレを提案させる",
        "proposal": "Proposal" if english else "提案",
        "unambiguous": "unambiguous" if english else "曖昧さなし",
        "ambiguous": "ambiguous: choose one" if english else "拮抗: 人が選ぶ",
        "inside": "recordings inside the ride" if english else "本が旅の中",
        "hours": "h" if english else "時間",
        "name": "Name for this day (letters, digits, - _)"
        if english
        else "この日の名前（英数字・-・_）",
        "target": "Target length (s)" if english else "目標尺（秒）",
        "create": "Bring in this day with this offset" if english else "この数字でこの日を取り込む",
        "offset_label": "Confirmed offset (s), as proposed"
        if english
        else "確定するズレ（秒）、提案どおりに",
        "story": "The film, chapter by chapter" if english else "作品の構成",
        "cold_open": "Opens on" if english else "冒頭",
        "rank": "rank" if english else "順位",
        "no_story": "No story plan yet." if english else "まだ構成がありません。",
        "play": "Play the film" if english else "作品を再生",
        "film_file": "File (open it in QuickTime from here)"
        if english
        else "ファイルの場所（QuickTime で開くならここ）",
        "film_silent": "silent version: music is a separate step"
        if english
        else "無音版（音楽は別工程）",
        "dh_heading": "Before you approve" if english else "承認する前に",
        "dh_sends": "sends" if english else "送信",
        "dh_silent": "silent" if english else "無音",
        "dh_to": "to" if english else "送り先",
        "dh_only_if_approved": "only if approved" if english else "承認したときだけ",
        "dh_kept": "kept up to" if english else "保持上限",
        "dh_days": "d" if english else "日",
        "dh_max": "max" if english else "上限",
        "dh_never": (
            "never sent: the original recording, file names or paths, GPS as text"
            if english
            else "送らない: 原本・ファイル名やパス・文字としてのGPS"
        ),
        "dh_deletable": (
            "deletable on request (not self-service here yet)"
            if english
            else "依頼により削除可（この画面からはまだ不可）"
        ),
    }
    track_ids = [NO_MUSIC_TRACK_ID, *MUSIC_TRACK_IDS]
    stage_names = {
        "footage_planned": "What judging would send" if english else "判定の計画",
        "copies_prepared": "Copies made to send" if english else "縮小コピーの準備",
        "footage_judged": "Judgement bought" if english else "Geminiの判定",
        "inputs_checked": "Inputs checked" if english else "入力の確認",
        "story_planned": "Story planned" if english else "物語の計画",
        "film_cut": "Film cut" if english else "作品の生成",
        "film_scored": "Music added" if english else "音楽の追加",
        "film_status": "Film status" if english else "作品の状態",
    }
    state_names = {
        "done": "done" if english else "完了",
        "pending": "not yet" if english else "未実施",
        "in_progress": "in progress" if english else "進行中",
        "blocked": "blocked" if english else "進めない",
    }
    action_names = {
        "resolve_blocking_reasons": (
            "Resolve what is blocking, then check again."
            if english
            else "止めている理由を解消してから、再度確認してください。"
        ),
        "prepare_the_copies": (
            "Make the copies to send (on this machine, free)."
            if english
            else "送る縮小コピーを作ってください（この端末内・無料）。"
        ),
        "approve_and_judge": (
            "Approve the cost shown and have the footage judged."
            if english
            else "表示された費用を承認し、映像を判定させてください。"
        ),
        "wait_for_the_judgement": (
            "The judgement is being bought. This page re-reads itself."
            if english
            else "判定を購入中です。この画面は自動で更新されます。"
        ),
        "make_the_film": (
            "Make the film for this day." if english else "この日の作品を生成してください。"
        ),
        "choose_music": (
            "Choose a track and score the film."
            if english
            else "曲を選んで作品に音楽を付けてください。"
        ),
        "watch_the_film": (
            "Nothing left to do. Watch the film."
            if english
            else "残作業はありません。作品を再生してください。"
        ),
    }
    return f"""<!doctype html>
<html lang="{"en" if english else "ja"}">
<head><meta charset="utf-8"><title>{strings["title"]}</title>
<style>
body{{margin:0;padding:2rem;background:#11131a;color:#f4f4f2;
font-family:"Hiragino Sans","Noto Sans CJK JP",system-ui,sans-serif;line-height:1.6}}
h1{{font-size:1.6rem;margin:0 0 .4rem}}
h2{{font-size:1.05rem;margin:2rem 0 .6rem;color:#a8b0c0;font-weight:600}}
p.intro{{color:#a8b0c0;margin:0 0 1rem;max-width:60ch}}
table{{border-collapse:collapse;width:100%;max-width:60rem}}
th,td{{text-align:left;padding:.5rem .8rem;border-bottom:1px solid #232733;vertical-align:top}}
th{{color:#a8b0c0;font-weight:600}}
.done{{color:#7ddc9a}} .pending{{color:#a8b0c0}} .blocked{{color:#e6875a}} .in_progress{{color:#f0c674}}
.facts{{color:#c8cdd8;font-size:.92rem}}
.money{{font-weight:700;color:#f4f4f2}}
.next{{margin-top:1.4rem;padding:.9rem 1.1rem;background:#1a1e28;border-radius:.4rem;max-width:60rem}}
.reasons{{color:#e6875a;font-size:.9rem}}
input,select{{font:inherit;padding:.35rem .5rem;background:#0d0f15;color:#f4f4f2;border:1px solid #343a4a;border-radius:.3rem}}
button{{font:inherit;padding:.45rem .9rem;background:#2b5cff;color:#fff;border:0;border-radius:.3rem;cursor:pointer}}
button[data-action=judge]{{background:#c0392b}}
button:disabled{{opacity:.5;cursor:default}}
</style></head>
<body>
<h1>{strings["title"]}</h1>
<p class="intro">{strings["intro"]}</p>
<div id="content">{strings["loading"]}</div>
<script>
const STAGE_NAMES = {json.dumps(stage_names, ensure_ascii=False)};
const STATE_NAMES = {json.dumps(state_names, ensure_ascii=False)};
const ACTION_NAMES = {json.dumps(action_names, ensure_ascii=False)};
const LABEL = {json.dumps(strings, ensure_ascii=False)};
const TRACKS = {json.dumps(track_ids)};
const DEFAULT_TRACK = {json.dumps(DEFAULT_MUSIC_TRACK_ID)};
function esc(value) {{
  return String(value).replace(/[&<>"']/g, function (c) {{
    return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];
  }});
}}
function seconds(value) {{
  const total = Math.round(Number(value) || 0);
  return Math.floor(total / 60) + "m " + String(total % 60).padStart(2, "0") + "s";
}}
function facts(stage) {{
  const f = [];
  if (stage.key === "footage_planned" && stage.state === "done") {{
    f.push(esc(stage.candidate_count) + " " + LABEL.candidates);
    if (stage.watched_count !== stage.candidate_count) {{
      f.push(esc(stage.watched_count) + " " + LABEL.watched);
    }}
    f.push(esc(stage.upload_megabytes) + " MB " + LABEL.upload);
    f.push('<span class="money">' + LABEL.yen + esc(stage.cost_jpy) + "</span> " + LABEL.cost
      + " (" + LABEL.budget + " " + LABEL.yen + esc(stage.budget_jpy) + ")");
  }}
  if (stage.key === "copies_prepared" && "wanted_count" in stage) {{
    f.push(esc(stage.prepared_count) + " / " + esc(stage.wanted_count) + " " + LABEL.prepared
      + (stage.measured_megabytes ? " (" + esc(stage.measured_megabytes) + " MB)" : ""));
  }}
  if (stage.key === "footage_judged" && "wanted_count" in stage) {{
    f.push(esc(stage.judged_count) + " / " + esc(stage.wanted_count) + " " + LABEL.judged);
  }}
  if (stage.key === "story_planned" && stage.state === "done") {{
    f.push(esc(stage.beat_count) + " " + LABEL.beats + ", " + seconds(stage.total_screen_duration_s));
  }}
  if ((stage.key === "film_cut" || stage.key === "film_scored") && stage.state === "done") {{
    if (stage.megabytes !== undefined) {{ f.push(esc(stage.megabytes) + " MB"); }}
  }}
  if (stage.key === "inputs_checked" && stage.duration) {{
    // Before a plan exists the figure is the footage on offer, not a film's length.
    const label = stage.duration.includes_chapter_cards ? LABEL.duration : LABEL.footage_total;
    f.push(seconds(stage.duration.film_s) + " " + label);
  }}
  if (stage.blocking_reasons && stage.blocking_reasons.length) {{
    f.push('<span class="reasons">' + stage.blocking_reasons.map(esc).join(", ") + "</span>");
  }}
  return f.join(" · ");
}}
function render(payload) {{
  let html = "";
  if (payload.package) {{
    let options = "";
    (payload.packages || []).forEach(function (n) {{
      options += '<option value="' + esc(n) + '"' + (n === payload.package ? " selected" : "") + ">" + esc(n) + "</option>";
    }});
    html += '<p class="facts">' + LABEL.package + ': <select id="pkg">' + options + '</select> '
      + '<button data-action="select">' + LABEL.switch + "</button></p>";
  }}
  html += "<h2>" + LABEL.stages + "</h2><table><tbody>";
  payload.stages.forEach(function (stage) {{
    html += "<tr><th>" + esc(STAGE_NAMES[stage.key] || stage.key) + "</th>"
      + '<td class="' + esc(stage.state) + '">' + esc(STATE_NAMES[stage.state] || stage.state) + "</td>"
      + '<td class="facts">' + facts(stage) + "</td></tr>";
  }});
  html += "</tbody></table>";
  if (payload.chapters && payload.chapters.length) {{
    html += "<h2>" + LABEL.chapters + "</h2><table><tbody>";
    payload.chapters.forEach(function (chapter) {{
      html += "<tr><th>" + esc(chapter.title) + "</th><td>" + esc(chapter.body) + "</td></tr>";
    }});
    html += "</tbody></table>";
  }}
  html += '<div class="next"><strong>' + LABEL.next + "</strong><br>"
    + esc(ACTION_NAMES[payload.next_action] || payload.next_action)
    + controls(payload) + jobLine(payload.job) + "</div>";
  html += intakeSection();
  document.getElementById("content").innerHTML = html;
  wire();
  loadStory();
  const running = payload.job && payload.job.state === "running";
  const busy = payload.stages.some(function (s) {{ return s.state === "in_progress"; }});
  if (busy || running) {{ setTimeout(load, 5000); }}
}}
function dataHandlingLine(dh) {{
  if (!dh) {{ return ""; }}
  const w = dh.sent_per_window;
  const parts = [
    LABEL.dh_sends + ": " + esc(w.seconds) + "s, " + esc(w.height_px) + "p, " + esc(w.fps) + "fps, "
      + LABEL.dh_silent + " (" + LABEL.dh_only_if_approved + ")",
    LABEL.dh_to + ": " + esc(dh.recipients.join(", ")),
    LABEL.dh_kept + " " + esc(dh.retention.default_days) + LABEL.dh_days
      + " (" + LABEL.dh_max + " " + esc(dh.retention.maximum_days) + LABEL.dh_days + "), " + LABEL.dh_deletable,
    LABEL.dh_never,
  ];
  return '<p class="facts"><strong>' + LABEL.dh_heading + "</strong><br>" + parts.join(" · ") + "</p>";
}}
function controls(payload) {{
  if (payload.job && payload.job.state === "running") {{ return ""; }}
  const planned = payload.stages.find(function (s) {{ return s.key === "footage_planned"; }});
  if (payload.next_action === "prepare_the_copies") {{
    return '<p><button data-action="preflight">' + LABEL.do_preflight + "</button></p>";
  }}
  if (payload.next_action === "approve_and_judge" && planned) {{
    return dataHandlingLine(payload.data_handling)
      + '<p><label>' + LABEL.approve_label + ' <span class="money">' + LABEL.yen + esc(planned.cost_jpy)
      + '</span><br><input id="approve" inputmode="decimal" placeholder="' + esc(planned.cost_jpy) + '"></label></p>'
      + '<p><label>' + LABEL.bucket_label + '<br><input id="bucket"></label></p>'
      + '<p><button data-action="judge">' + LABEL.do_judge + "</button></p>";
  }}
  if (payload.next_action === "make_the_film" || payload.next_action === "choose_music") {{
    let options = "";
    TRACKS.forEach(function (id) {{
      options += '<option value="' + esc(id) + '"' + (id === DEFAULT_TRACK ? " selected" : "") + ">" + esc(id) + "</option>";
    }});
    return '<p><label>' + LABEL.music_label + ' <select id="music">' + options + "</select></label> "
      + '<button data-action="film">' + LABEL.do_film + "</button></p>";
  }}
  return "";
}}
function windowLine(w) {{
  let s = '<div class="facts">' + esc(w.at_s) + "s · " + esc(w.screen_duration_s) + "s";
  if (w.judged) {{
    if (w.rank) {{ s += " · " + LABEL.rank + " " + esc(w.rank); }}
    s += " · " + esc(w.interest) + " / " + esc(w.story) + " · " + esc(w.road) + "<br><span>" + esc(w.description) + "</span>";
  }}
  return s + "</div>";
}}
function renderStory(story) {{
  let html = "<h2>" + LABEL.story + "</h2>";
  if (story.film && story.film.available) {{
    html += '<video id="film" controls preload="metadata" style="width:100%;max-width:60rem;background:#000"><source src="/private-journey/film" type="video/mp4"></video>';
    html += '<p class="facts">' + LABEL.film_file + ': <code>private-media/work/' + esc(story.package) + '/' + esc(story.film.file_name) + '</code>' + (story.film.variant === 'silent' ? ' · ' + LABEL.film_silent : '') + '</p>';
  }}
  if (story.cold_open) {{
    html += "<p><strong>" + LABEL.cold_open + "</strong>" + windowLine(story.cold_open) + "</p>";
  }}
  story.chapters.forEach(function (c) {{
    html += '<div class="next"><strong>' + esc(c.title) + '</strong> <span class="facts">' + esc(c.body) + " · " + esc(c.at_s) + "s</span>";
    c.windows.forEach(function (w) {{ html += windowLine(w); }});
    html += "</div>";
  }});
  const holder = document.getElementById("story");
  if (holder) {{ holder.innerHTML = html; }}
}}
function loadStory() {{
  if (!document.getElementById("story")) {{
    const div = document.createElement("div"); div.id = "story";
    document.getElementById("content").appendChild(div);
  }}
  fetch("/api/private-journey/story").then(function (r) {{
    if (!r.ok) {{ throw new Error("none"); }}
    return r.json();
  }}).then(renderStory).catch(function () {{
    document.getElementById("story").innerHTML = "<h2>" + LABEL.story + '</h2><p class="facts">' + LABEL.no_story + "</p>";
  }});
}}
function intakeSection() {{
  return "<h2>" + LABEL.intake + '</h2><p class="intro">' + LABEL.intake_help + "</p>"
    + '<p><label>' + LABEL.gpx + '<br><input id="in_gpx" size="48"></label></p>'
    + '<p><label>' + LABEL.video_root + '<br><input id="in_videos" size="48"></label></p>'
    + '<p><button data-action="propose">' + LABEL.propose + "</button></p>"
    + '<div id="proposal"></div>';
}}
function renderProposal(p) {{
  const c = p.proposed;
  let html = "<p><strong>" + LABEL.proposal + "</strong>: " + esc(c.offset_hours) + LABEL.hours
    + " (" + esc(c.offset_s) + "s) · " + esc(c.recordings_inside) + " / " + esc(c.recordings_total) + " " + LABEL.inside
    + " · " + (p.is_unambiguous ? '<span class="done">' + LABEL.unambiguous + "</span>" : '<span class="blocked">' + LABEL.ambiguous + "</span>") + "</p>";
  if (p.runners_up && p.runners_up.length) {{
    html += "<ul>";
    p.runners_up.forEach(function (r) {{
      html += "<li>" + esc(r.offset_hours) + LABEL.hours + " (" + esc(r.offset_s) + "s) · " + esc(r.recordings_inside) + " / " + esc(r.recordings_total) + "</li>";
    }});
    html += "</ul>";
  }}
  html += '<p><label>' + LABEL.offset_label + '<br><input id="in_offset" value="' + esc(c.offset_s) + '"></label></p>'
    + '<p><label>' + LABEL.name + '<br><input id="in_name"></label> '
    + '<label>' + LABEL.target + ' <input id="in_target" value="300" size="5"></label></p>'
    + '<p><button data-action="create">' + LABEL.create + "</button></p>";
  document.getElementById("proposal").innerHTML = html;
  wire();
}}
function jobLine(job) {{
  if (!job || job.state === "idle") {{ return ""; }}
  const name = {{running: LABEL.job_running, done: LABEL.job_done, failed: LABEL.job_failed}}[job.state] || job.state;
  let text = '<p class="' + esc(job.state === "failed" ? "blocked" : job.state === "done" ? "done" : "in_progress") + '">'
    + esc(job.kind) + ": " + esc(name) + " (" + esc(job.elapsed_s) + "s)";
  if (job.reason) {{ text += " · " + esc(job.reason); }}
  return text + "</p>";
}}
function wire() {{
  document.querySelectorAll("button[data-action]").forEach(function (button) {{
    button.addEventListener("click", function () {{
      const action = button.getAttribute("data-action");
      const body = {{}};
      if (action === "judge") {{
        body.approve_jpy = (document.getElementById("approve") || {{}}).value;
        body.bucket = (document.getElementById("bucket") || {{}}).value;
      }}
      if (action === "film") {{ body.music = (document.getElementById("music") || {{}}).value; }}
      let url = "/api/private-journey/" + action;
      if (action === "select") {{ body.name = (document.getElementById("pkg") || {{}}).value; }}
      if (action === "propose" || action === "create") {{
        body.gpx = (document.getElementById("in_gpx") || {{}}).value;
        body.video_root = (document.getElementById("in_videos") || {{}}).value;
        url = "/api/private-journey/intake/" + action;
      }}
      if (action === "create") {{
        body.name = (document.getElementById("in_name") || {{}}).value;
        body.offset_s = (document.getElementById("in_offset") || {{}}).value;
        body.target_duration_s = (document.getElementById("in_target") || {{}}).value;
      }}
      button.disabled = true;
      fetch(url, {{
        method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify(body)
      }}).then(function (response) {{ return response.json().then(function (j) {{ return [response.ok, j]; }}); }})
        .then(function (pair) {{
          if (!pair[0]) {{ alert(LABEL.refused + ": " + (pair[1].error || "")); button.disabled = false; return; }}
          if (action === "propose") {{ renderProposal(pair[1]); return; }}
          load();
        }}).catch(function () {{ button.disabled = false; }});
    }});
  }});
}}
function load() {{
  fetch("/api/private-journey").then(function (response) {{
    if (!response.ok) {{ throw new Error("unavailable"); }}
    return response.json();
  }}).then(render).catch(function () {{
    document.getElementById("content").textContent = LABEL.unavailable;
  }});
}}
load();
</script>
</body>
</html>"""


def _private_journey_status_page(language: UiLanguage) -> str:
    """One page showing where this ride is, from checked inputs to a film."""
    english = language is UiLanguage.ENGLISH
    strings = {
        "title": "This ride" if english else "この旅の状態",
        "intro": (
            "Read-only. This page shows what was checked, what the film will be, and "
            "what has been made. It starts nothing: rendering is a deliberate command."
            if english
            else "読み取り専用の画面です。何が確認され、作品がどうなるか、何ができているかを表示します。"
            "処理は開始しません。レンダーは明示的なコマンドで行います。"
        ),
        "stages": "Stages" if english else "進行",
        "chapters": "Chapters the film will show" if english else "作品に出る章",
        "next": "Next step" if english else "次の操作",
        "loading": "Loading…" if english else "読み込み中…",
        # This page is read-only and has no intake control of its own — the
        # earlier wording said "below" as if one were here. Bringing in a
        # day happens on the console page, so this links there instead.
        "unavailable": (
            "No day has been brought in on this machine yet. Start on the "
            f'<a href="/private-journey?lang={language.value}">ride console</a>.'
            if english
            else f'この端末にはまだ取り込んだ日がありません。<a href="/private-journey?lang={language.value}">'
            "この旅の操作卓</a>で別の日のクリップを取り込んでください。"
        ),
    }
    stage_names = {
        "inputs_checked": "Inputs checked" if english else "入力の確認",
        "story_planned": "Story planned" if english else "物語の計画",
        "film_cut": "Film cut" if english else "作品の生成",
        "film_scored": "Music added" if english else "音楽の追加",
    }
    state_names = {
        "done": "done" if english else "完了",
        "pending": "not yet" if english else "未実施",
        "blocked": "blocked" if english else "進めない",
    }
    action_names = {
        "resolve_blocking_reasons": (
            "Resolve what is blocking the inputs, then check again."
            if english
            else "入力を止めている理由を解消してから、再度確認してください。"
        ),
        "make_the_film": (
            "Make the film for this day." if english else "この日の作品を生成してください。"
        ),
        "choose_music": (
            "Choose a track and score the film."
            if english
            else "曲を選んで作品に音楽を付けてください。"
        ),
        "watch_the_film": (
            "Nothing left to do. Watch the film."
            if english
            else "残作業はありません。作品を再生してください。"
        ),
    }
    # The "unavailable" string carries an <a> link; escape "<" outside the
    # f-string, since Python 3.11 rejects a backslash escape inside one.
    label_json = json.dumps(strings, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="{"en" if english else "ja"}">
<head><meta charset="utf-8"><title>{strings["title"]}</title>
<style>
body{{margin:0;padding:2rem;background:#11131a;color:#f4f4f2;
font-family:"Hiragino Sans","Noto Sans CJK JP",system-ui,sans-serif;line-height:1.6}}
h1{{font-size:1.6rem;margin:0 0 .4rem}}
h2{{font-size:1.05rem;margin:2rem 0 .6rem;color:#a8b0c0;font-weight:600}}
p.intro{{color:#a8b0c0;margin:0 0 1rem;max-width:60ch}}
table{{border-collapse:collapse;width:100%;max-width:60rem}}
th,td{{text-align:left;padding:.5rem .8rem;border-bottom:1px solid #232733}}
th{{color:#a8b0c0;font-weight:600}}
.done{{color:#7ddc9a}} .pending{{color:#a8b0c0}} .blocked{{color:#e6875a}}
.next{{margin-top:1.4rem;padding:.9rem 1.1rem;background:#1a1e28;border-radius:.4rem;
max-width:60rem}}
.reasons{{color:#e6875a;font-size:.9rem}}
</style></head>
<body>
<h1>{strings["title"]}</h1>
<p class="intro">{strings["intro"]}</p>
<div id="content">{strings["loading"]}</div>
<script>
const STAGE_NAMES = {json.dumps(stage_names, ensure_ascii=False)};
const STATE_NAMES = {json.dumps(state_names, ensure_ascii=False)};
const ACTION_NAMES = {json.dumps(action_names, ensure_ascii=False)};
const LABEL = {label_json};
function esc(value) {{
  return String(value).replace(/[&<>"']/g, function (c) {{
    return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];
  }});
}}
function seconds(value) {{
  const total = Math.round(Number(value) || 0);
  return Math.floor(total / 60) + "m " + String(total % 60).padStart(2, "0") + "s";
}}
fetch("/api/private-journey-status").then(function (response) {{
  if (!response.ok) {{ throw new Error("unavailable"); }}
  return response.json();
}}).then(function (data) {{
  const rows = data.stages.map(function (stage) {{
    const detail = [];
    if (stage.key === "inputs_checked") {{
      detail.push(seconds(stage.duration.film_s) + " / " + seconds(stage.duration.target_s));
      if (stage.blocking_reasons.length) {{
        detail.push('<span class="reasons">' + esc(stage.blocking_reasons.join(", ")) + "</span>");
      }}
    }} else if (stage.key === "story_planned" && stage.state === "done") {{
      detail.push(stage.beat_count + " beats, " + stage.card_beat_count + " cards");
      detail.push(seconds(stage.total_screen_duration_s));
    }} else if (stage.state === "done" && stage.megabytes) {{
      detail.push(stage.megabytes + " MB");
    }}
    return "<tr><td>" + esc(STAGE_NAMES[stage.key] || stage.key) + "</td>" +
      '<td class="' + esc(stage.state) + '">' + esc(STATE_NAMES[stage.state]) + "</td>" +
      "<td>" + detail.join(" · ") + "</td></tr>";
  }}).join("");
  const chapters = (data.chapters || []).map(function (chapter) {{
    return "<tr><td>" + esc(chapter.title) + "</td><td>" + esc(chapter.body) + "</td>" +
      "<td>" + seconds(chapter.screen_duration_s) + "</td></tr>";
  }}).join("");
  document.getElementById("content").innerHTML =
    "<h2>" + esc(LABEL.stages) + "</h2><table>" + rows + "</table>" +
    (chapters ? "<h2>" + esc(LABEL.chapters) + "</h2><table>" + chapters + "</table>" : "") +
    '<div class="next"><strong>' + esc(LABEL.next) + "</strong><br>" +
    esc(ACTION_NAMES[data.next_action] || data.next_action) + "</div>";
}}).catch(function () {{
  document.getElementById("content").innerHTML = LABEL.unavailable;
}});
</script>
</body></html>
"""


def _private_director_preview_page(language: UiLanguage) -> str:
    """Render a read-only local view with no source identifiers."""
    english = language is UiLanguage.ENGLISH
    strings = {
        "title": "Private story structure" if english else "私用の物語構成",
        "intro": (
            "This page reads the explicitly configured local DirectorScript and shows only "
            "its narrative structure. It does not upload media or route data."
            if english
            else "この画面は明示設定したローカルDirectorScriptから、物語構成だけを表示します。映像・経路データはアップロードしません。"
        ),
        "loading": "Loading local story structure…"
        if english
        else "ローカルの物語構成を読み込み中…",
        "failed": "The local story structure is unavailable."
        if english
        else "ローカルの物語構成を読み込めませんでした。",
        "composer": "Script composer" if english else "脚本の作成者",
        "events": "Events used / available" if english else "使用イベント数 / 入力イベント数",
        "coverage": "Journey coverage" if english else "旅の根拠範囲",
        "clips": "clips" if english else "クリップ",
        "back": "Back to demo" if english else "デモへ戻る",
    }
    coverage_labels = {
        "departure_to_arrival": (
            "Confirmed departure and arrival" if english else "出発と到着を確認済み"
        ),
        "departure_without_arrival": (
            "Confirmed departure; arrival is not confirmed"
            if english
            else "出発を確認済み。到着は未確認"
        ),
        "arrival_without_departure": (
            "Confirmed arrival; departure is not confirmed"
            if english
            else "到着を確認済み。出発は未確認"
        ),
        "middle_of_journey_only": (
            "Middle of journey only; endpoints are not confirmed"
            if english
            else "旅の途中のみ。出発・到着は未確認"
        ),
    }
    text = {key: escape(value) for key, value in strings.items()}
    strings_json = json.dumps(strings, ensure_ascii=False).replace("<", "\\u003c")
    coverage_labels_json = json.dumps(coverage_labels, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="{language.value}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ride Storyteller — {text["title"]}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}#notice{{padding:12px;background:#f2f7ff;border-radius:8px}}li{{margin:10px 0}}code{{background:#e9edf2;padding:2px 4px;border-radius:4px}}</style>
</head><body><main><p><a href="/?lang={language.value}">{text["back"]}</a></p><h1>{text["title"]}</h1><p>{text["intro"]}</p><p id="notice" aria-live="polite">{text["loading"]}</p><section id="script" hidden></section>
<script>
const text={strings_json},coverageLabels={coverage_labels_json},notice=document.querySelector('#notice'),section=document.querySelector('#script');
function safe(value){{return String(value).replace(/[&<>"']/g,char=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char]))}}
fetch('/api/private-director-preview').then(response=>{{if(!response.ok)throw Error();return response.json()}}).then(payload=>{{const script=payload.director_script;notice.textContent='';section.hidden=false;section.innerHTML=`<dl><dt>${{text.composer}}</dt><dd><code>${{safe(script.composer)}}</code></dd><dt>${{text.events}}</dt><dd>${{script.event_count_used}} / ${{script.event_count_in}}</dd><dt>${{text.coverage}}</dt><dd>${{safe(coverageLabels[script.journey_coverage]||text.failed)}}</dd></dl><ol>${{script.scenes.map(scene=>`<li><strong>${{safe(scene.role)}}</strong>: ${{scene.event_count}} ${{text.clips}} (${{safe(scene.transition_type)}})${{scene.overlay_text?' — '+safe(scene.overlay_text):''}}</li>`).join('')}}</ol>`}}).catch(()=>{{notice.textContent=text.failed}});
</script></main></body></html>"""


def _language_switch(language: UiLanguage, path: str) -> str:
    copy = copy_for(language)
    japanese_current = ' aria-current="page"' if language is UiLanguage.JAPANESE else ""
    english_current = ' aria-current="page"' if language is UiLanguage.ENGLISH else ""
    return (
        f'<nav class="language-switch" aria-label="{escape(copy["language.switch_label"])}">'
        f'<a href="{path}?lang=ja"{japanese_current}>'
        f"{escape(copy['language.japanese'])}</a> · "
        f'<a href="{path}?lang=en"{english_current}>'
        f"{escape(copy['language.english'])}</a></nav>"
    )


def _copy_json(language: UiLanguage) -> str:
    return json.dumps(dict(copy_for(language)), ensure_ascii=False).replace("<", "\\u003c")


def _media_inventory_page(language: UiLanguage = UiLanguage.JAPANESE) -> str:
    """Return a client-only inventory page with no third-party scripts or uploads."""
    copy = copy_for(language)

    def text(key: str) -> str:
        return escape(copy[key])

    return f"""<!doctype html>
<html lang="{language.value}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ride Storyteller — {text("inventory.heading")}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:white;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}button{{background:#1264d6;color:white;border:0;border-radius:8px;padding:12px 18px;font-size:16px;cursor:pointer}}button:disabled{{background:#8892a0}}#status{{margin-top:20px;padding:16px;background:#f2f7ff;border-radius:10px;white-space:pre-line}}code{{background:#e9edf2;padding:2px 4px;border-radius:4px}}.warning{{color:#8a4b08}}li{{margin:8px 0}}.language-switch{{text-align:right;margin-bottom:18px}}.language-switch [aria-current="page"]{{font-weight:700;text-decoration:none}}
</style></head><body><main>
{_language_switch(language, "/local-media-inventory")}
<p><a href="/?lang={language.value}">{text("common.back_to_demo")}</a></p>
<h1>{text("inventory.heading")}</h1>
<p>{text("inventory.description")}</p>
<ul><li>{text("inventory.targets")}：<code>.mp4</code>、<code>.mov</code>、<code>.lrv</code></li><li>{text("inventory.used")}</li><li>{text("inventory.not_used")}</li></ul>
<p class="warning"><strong>{text("inventory.no_upload")}</strong>{text("inventory.no_upload_detail")}</p>
<p><input id="videoFolder" type="file" webkitdirectory directory multiple accept=".mp4,.mov,.lrv,video/mp4,video/quicktime"></p>
<p><button id="buildInventory" disabled>{text("inventory.build")}</button></p>
<section id="status" aria-live="polite">{text("inventory.select")}</section>
<script>
const uiCopy={_copy_json(language)};
function formatCopy(key,values={{}}){{return Object.entries(values).reduce((value,[name,replacement])=>value.replaceAll(`{{${{name}}}}`,String(replacement)),uiCopy[key])}}
const SCHEMA_VERSION='local-video-inventory-v1';
const SUPPORTED_EXTENSIONS=new Set(['.lrv','.mov','.mp4']);
const folderInput=document.querySelector('#videoFolder'),buildButton=document.querySelector('#buildInventory'),statusBox=document.querySelector('#status');
function safeBrowserPath(file){{const source=(file.webkitRelativePath||file.name).replaceAll('\\\\','/'),parts=source.split('/').filter(Boolean);if(!parts.length||parts.includes('..'))throw Error('安全でない相対パスです。');return parts}}
function extensionOf(name){{const index=name.lastIndexOf('.');return index<0?'':name.slice(index).toLowerCase()}}
async function assetId(relativePath){{const bytes=new TextEncoder().encode(relativePath),digest=await crypto.subtle.digest('SHA-256',bytes),hex=[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('');return 'local-video-'+hex.slice(0,16)}}
async function buildBrowserMediaInventory(files){{const candidates=[],roots=new Set();for(const file of files){{const parts=safeBrowserPath(file),rootLabel=parts.length>1?parts[0]:'selected-folder',relativeParts=parts.length>1?parts.slice(1):parts,relativePath=relativeParts.join('/'),extension=extensionOf(file.name);if(!SUPPORTED_EXTENSIONS.has(extension))continue;if(relativeParts.at(-1)!==file.name)throw Error('相対パスとファイル名が一致しません。');roots.add(rootLabel);candidates.push({{file,relativePath,extension}})}}if(!candidates.length)throw Error('対応する動画ファイルが見つかりません。');if(roots.size!==1)throw Error('一度に1つの動画フォルダを選択してください。');candidates.sort((left,right)=>left.relativePath.localeCompare(right.relativePath));const entries=await Promise.all(candidates.map(async item=>({{asset_id:await assetId(item.relativePath),relative_path:item.relativePath,file_name:item.file.name,file_size_bytes:item.file.size,modified_time:new Date(item.file.lastModified).toISOString(),extension:item.extension}})));const counts={{}};for(const entry of entries)counts[entry.extension]=(counts[entry.extension]||0)+1;return {{schema_version:SCHEMA_VERSION,root_label:[...roots][0],summary:{{video_file_count:entries.length,total_size_bytes:entries.reduce((total,entry)=>total+entry.file_size_bytes,0),count_by_extension:Object.fromEntries(Object.entries(counts).sort())}},entries}}}}
folderInput.addEventListener('change',()=>{{const count=[...folderInput.files].filter(file=>SUPPORTED_EXTENSIONS.has(extensionOf(file.name))).length;buildButton.disabled=count===0;statusBox.textContent=count?formatCopy('inventory.selected',{{count}}):uiCopy['inventory.none_found']}});
buildButton.addEventListener('click',async()=>{{buildButton.disabled=true;try{{const inventory=await buildBrowserMediaInventory([...folderInput.files]),json=JSON.stringify(inventory,null,2)+'\\n',blob=new Blob([json],{{type:'application/json'}}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='ride-storyteller-local-video-inventory.json';link.click();URL.revokeObjectURL(link.href);statusBox.textContent=formatCopy('inventory.completed',{{count:inventory.summary.video_file_count,bytes:inventory.summary.total_size_bytes.toLocaleString()}})}}catch(error){{statusBox.textContent=uiCopy['inventory.failed']}}finally{{buildButton.disabled=folderInput.files.length===0}}}});
</script></main></body></html>"""


def _page(
    language: UiLanguage = UiLanguage.JAPANESE,
    *,
    deployment: WebDeploymentSettings | None = None,
) -> str:
    deployment = deployment or WebDeploymentSettings.from_environment()
    maps = GoogleMapsSettings.from_environment()
    copy = copy_for(language)

    def text(key: str) -> str:
        return escape(copy[key])

    maps_enabled = maps.enabled and not deployment.public_demo
    maps_script = (
        f'<script async src="{maps.javascript_url(language=language.value)}"></script>'
        if maps_enabled
        else ""
    )
    maps_status = text("map.enabled" if maps_enabled else "map.disabled")
    external_disabled = ' disabled aria-disabled="true"' if deployment.public_demo else ""
    private_disabled = ' disabled aria-disabled="true"' if deployment.public_demo else ""
    public_notice = (
        f'<p class="warning"><strong>{text("deployment.public_notice")}</strong></p>'
        if deployment.public_demo
        else ""
    )
    private_director_preview_link = (
        ""
        if deployment.public_demo
        else (
            f'<p><a href="/private-director-preview?lang={language.value}">'
            f"{text('director.preview.open')}</a></p>"
        )
    )
    private_evidence_review_link = (
        ""
        if deployment.public_demo
        else (
            f'<p><a href="/private-evidence-review?lang={language.value}">'
            f"{'映像証拠を確認' if language is UiLanguage.JAPANESE else 'Review visual evidence'}</a></p>"
        )
    )
    if deployment.source_repository_url is not None:
        source_footer = (
            '<footer id="source"><hr><p>'
            f'<a id="source-link" href="{escape(deployment.source_repository_url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{text("source.link")}</a>'
            "</p></footer>"
        )
    elif deployment.public_demo:
        source_footer = (
            '<footer id="source"><hr><p id="source-link-missing" class="warning">'
            f"{text('source.pending')}</p></footer>"
        )
    else:
        source_footer = ""
    return f"""<!doctype html>
<html lang="{language.value}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ride Storyteller — Demo</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:white;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}button{{background:#1264d6;color:white;border:0;border-radius:8px;padding:12px 18px;font-size:16px;cursor:pointer}}button:disabled{{background:#8892a0}}#notice{{color:#53606d}}#result{{display:none;margin-top:24px;padding:18px;background:#f2f7ff;border-radius:10px}}#map{{height:360px;margin-top:16px;border-radius:10px;background:#e9edf2}}dt{{font-weight:600;margin-top:10px}}dd{{margin:4px 0}}ol{{padding-left:22px}}code{{background:#e9edf2;padding:2px 4px;border-radius:4px}}.warning{{color:#8a3b12;background:#fff3e8;padding:12px;border-radius:8px}}.language-switch{{text-align:right;margin-bottom:18px}}.language-switch [aria-current="page"]{{font-weight:700;text-decoration:none}}</style>
</head><body><main>{_language_switch(language, "/")}{public_notice}
<p id="notice">{text("main.notice")}</p>
<h1>{text("main.title")}</h1><p>{text("main.intro")}</p>
<label>{text("demo.scenario")} <select id="scenario"><option value="accepted">{text("scenario.accepted")}</option><option value="rejected">{text("scenario.rejected")}</option><option value="missing_asset">{text("scenario.missing_asset")}</option><option value="gemini_unavailable">{text("scenario.gemini_unavailable")}</option></select></label>
<p><button id="run">{text("demo.run")}</button> <button id="plan">{text("demo.story_plan")}</button> <button id="candidate">{text("demo.candidate_plan")}</button> <button id="download" disabled>{text("demo.download")}</button></p><hr><section id="ibm-evidence"><h2>{text("ibm.heading")}</h2><p>{text("ibm.description")}</p><ul><li>{text("ibm.finding.1")}</li><li>{text("ibm.finding.2")}</li><li>{text("ibm.finding.3")}</li></ul><p><small>{text("ibm.limit")}</small></p></section><hr><h2>{text("adk.heading")}</h2><p>{text("adk.description")}</p><p><button id="adkRun"{external_disabled}>{text("adk.run")}</button></p><hr><h2>{text("platform.heading")}</h2><p>{text("platform.description")}</p><p><button id="platformRun"{external_disabled}>{text("platform.run")}</button> <button id="platformPreflight"{external_disabled}>{text("platform.preflight")}</button></p><hr><h2>{text("director.heading")}</h2><p>{text("director.description")}</p><p><button id="directorRun"{external_disabled}>{text("director.run")}</button></p>{private_director_preview_link}{private_evidence_review_link}<hr><h2>{text("inventory.heading")}</h2><p>{text("inventory.main_description")}</p><p><a href="/local-media-inventory?lang={language.value}">{text("inventory.open")}</a></p><hr><h2>{text("gpx.heading")}</h2><p>{text("gpx.description")}</p><input id="gpx" type="file" accept=".gpx,application/gpx+xml"{private_disabled}><button id="gpxRun"{private_disabled}>{text("gpx.run")}</button><section id="result" aria-live="polite"></section>
<h2>{text("map.heading")}</h2><p id="mapStatus">{maps_status}</p><p>{text("map.privacy")}</p><div id="map" aria-label="{text("map.aria")}"></div>
<script>
const uiCopy={_copy_json(language)}, uiLanguage='{language.value}';
function formatCopy(key,values={{}}){{return Object.entries(values).reduce((value,[name,replacement])=>value.replaceAll(`{{${{name}}}}`,String(replacement)),uiCopy[key])}}
function escapeHtml(value){{return String(value).replace(/[&<>"']/g,character=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[character]))}}
function reviewReasons(review){{const values=[];if((review.missing_duration_s||0)>0)values.push(uiCopy['candidate.reason.duration']);const awaiting=review.event_ids_requiring_evidence?.length??review.awaiting_evidence_count??0,rejected=review.rejected_event_ids?.length??review.rejected_evidence_count??0;if(awaiting)values.push(uiCopy['candidate.reason.awaiting']);if(rejected)values.push(uiCopy['candidate.reason.rejected']);return values}}
function storyChapter(chapter){{return chapter.title+': '+chapter.selection_rationale+` (${{chapter.target_duration_s}}s)`}}
const runButton=document.querySelector('#run'), planButton=document.querySelector('#plan'), candidateButton=document.querySelector('#candidate'), downloadButton=document.querySelector('#download'), adkButton=document.querySelector('#adkRun'), platformRunButton=document.querySelector('#platformRun'), platformPreflightButton=document.querySelector('#platformPreflight'), directorButton=document.querySelector('#directorRun'), gpxButton=document.querySelector('#gpxRun'), gpxInput=document.querySelector('#gpx'), scenario=document.querySelector('#scenario'), result=document.querySelector('#result');let latestRecord=null;
let map,routeLine;
function show(html){{result.innerHTML=html;result.style.display='block'}}
window.initRideMap=()=>{{map=new google.maps.Map(document.querySelector('#map'),{{center:{{lat:-41.2865,lng:174.7762}},zoom:5,mapTypeControl:false,streetViewControl:false}})}};
function routePoints(gpxText){{const documentRoot=new DOMParser().parseFromString(gpxText,'application/xml');if(documentRoot.querySelector('parsererror'))throw Error();const points=[];for(const point of documentRoot.getElementsByTagNameNS('*','trkpt')){{const lat=Number(point.getAttribute('lat')),lng=Number(point.getAttribute('lon'));if(!Number.isFinite(lat)||!Number.isFinite(lng)||lat < -90||lat > 90||lng < -180||lng > 180)throw Error();points.push({{lat,lng}})}}if(points.length<2)throw Error();const step=Math.max(1,Math.ceil(points.length/10000));return points.filter((_,index)=>index%step===0||index===points.length-1)}}
function drawRoute(points){{if(!map){{document.querySelector('#mapStatus').textContent=uiCopy['map.waiting'];return}}if(routeLine)routeLine.setMap(null);routeLine=new google.maps.Polyline({{path:points,geodesic:true,strokeColor:'#1264d6',strokeOpacity:0.9,strokeWeight:4}});routeLine.setMap(map);const bounds=new google.maps.LatLngBounds();points.forEach(point=>bounds.extend(point));map.fitBounds(bounds);document.querySelector('#mapStatus').textContent=formatCopy('map.points',{{count:points.length}})}}
runButton.addEventListener('click',async()=>{{runButton.disabled=true;try{{const r=await fetch('/api/demo?scenario='+encodeURIComponent(scenario.value)+'&lang='+uiLanguage);const d=await r.json();if(!r.ok)throw Error();latestRecord=d;downloadButton.disabled=false;show(`<h2>${{d.scenario.label}}</h2><p>${{d.notice}}</p><dl><dt>${{uiCopy['demo.gps_event']}}</dt><dd><code>${{d.event.event_type}}</code> (${{uiCopy['demo.importance']}} ${{d.event.importance_hint}})</dd><dt>${{uiCopy['demo.video_evidence']}}</dt><dd>${{d.decision.needs_video_evidence?uiCopy['demo.required']:uiCopy['demo.not_required']}}</dd><dt>${{uiCopy['demo.final_status']}}</dt><dd><code>${{d.decision.decision_status}}</code></dd><dt>${{uiCopy['demo.reason']}}</dt><dd>${{d.decision.reason}}</dd></dl><h3>${{uiCopy['demo.agent_flow']}}</h3><ol>${{d.steps.map(step=>`<li>${{step}}</li>`).join('')}}</ol>`)}}catch(e){{show(uiCopy['error.demo'])}}finally{{runButton.disabled=false}}}});
planButton.addEventListener('click',async()=>{{try{{const r=await fetch('/api/story-plan?lang='+uiLanguage);const d=await r.json();if(!r.ok)throw Error();show(`<h2>${{uiCopy['story.heading']}}</h2><p>${{d.notice}}</p><p><strong>${{d.story_plan.title}}</strong> — ${{d.story_plan.target_duration_s}}s</p><ol>${{d.story_plan.chapters.map(chapter=>`<li>${{storyChapter(chapter)}}</li>`).join('')}}</ol>`)}}catch(e){{show(uiCopy['error.story'])}}}});
candidateButton.addEventListener('click',async()=>{{try{{const r=await fetch('/api/candidate-edit-plan?lang='+uiLanguage);const d=await r.json(),p=d.candidate_edit_plan,q=d.quality_review;if(!r.ok)throw Error();show(`<h2>${{uiCopy['candidate.heading']}}</h2><p>${{d.notice}}</p><dl><dt>${{uiCopy['candidate.target_duration']}}</dt><dd>${{p.target_duration_s}}s / ${{p.candidate_duration_s}}s</dd><dt>${{uiCopy['candidate.coverage']}}</dt><dd>${{(p.coverage_ratio*100).toFixed(1)}}%</dd><dt>${{uiCopy['candidate.status']}}</dt><dd><code>${{p.status}}</code></dd><dt>${{uiCopy['candidate.edit_ready']}}</dt><dd>${{q.is_ready_for_edit?uiCopy['candidate.ready']:uiCopy['candidate.not_ready']}}</dd></dl><h3>${{uiCopy['candidate.review_reasons']}}</h3><ul>${{q.reasons.map(reason=>`<li>${{reason}}</li>`).join('')}}</ul><h3>${{uiCopy['candidate.clips']}}</h3><ol>${{p.clips.map(clip=>`<li>${{clip.chapter_id}}: <code>${{clip.asset_name_hint}}</code> ${{clip.start_offset_s}}–${{clip.end_offset_s}}s (${{clip.evidence_status}})</li>`).join('')}}</ol>`)}}catch(e){{show(uiCopy['error.candidate'])}}}});
adkButton.addEventListener('click',async()=>{{adkButton.disabled=true;try{{const r=await fetch('/api/adk-synthetic-demo',{{method:'POST'}});const d=await r.json();if(!r.ok)throw Error();const a=d.adk_synthetic_demo;show(`<h2>${{uiCopy['adk.heading']}}</h2><p>${{uiCopy['adk.description']}}</p><dl><dt>${{uiCopy['platform.model']}}</dt><dd><code>${{a.model}}</code></dd><dt>${{uiCopy['platform.tool']}}</dt><dd>${{a.tool_called?uiCopy['common.success']:uiCopy['common.failure']}}</dd><dt>${{uiCopy['platform.response']}}</dt><dd>${{a.final_response_received?uiCopy['common.success']:uiCopy['common.failure']}}</dd></dl>`)}}catch(e){{show(uiCopy['error.adk'])}}finally{{adkButton.disabled=false}}}});
platformRunButton.addEventListener('click',async()=>{{platformRunButton.disabled=true;try{{const r=await fetch('/api/agent-platform-synthetic-demo',{{method:'POST'}});const d=await r.json();if(!r.ok)throw Error();const a=d.agent_platform_synthetic_demo;show(`<h2>${{uiCopy['platform.heading']}}</h2><p>${{uiCopy['platform.description']}}</p><dl><dt>${{uiCopy['platform.runtime']}}</dt><dd><code>${{a.runtime_location}}</code></dd><dt>${{uiCopy['platform.model']}}</dt><dd><code>${{a.model}}</code></dd><dt>${{uiCopy['platform.tool']}}</dt><dd>${{a.tool_called?uiCopy['common.success']:uiCopy['common.failure']}}</dd><dt>${{uiCopy['platform.response']}}</dt><dd>${{a.final_response_received?uiCopy['common.success']:uiCopy['common.failure']}}</dd><dt>${{uiCopy['platform.private_data']}}</dt><dd>${{a.private_data_used?uiCopy['platform.used']:uiCopy['platform.not_used']}}</dd></dl><p>${{uiCopy['platform.external_notice']}}</p>`)}}catch(e){{show(uiCopy['error.platform'])}}finally{{platformRunButton.disabled=false}}}});
platformPreflightButton.addEventListener('click',async()=>{{platformPreflightButton.disabled=true;try{{const r=await fetch('/api/agent-platform-preflight');const d=await r.json();if(!r.ok)throw Error();const p=d.agent_platform_preflight;show(`<h2>${{uiCopy['platform.preflight_heading']}}</h2><dl><dt>${{uiCopy['candidate.status']}}</dt><dd><code>${{p.status}}</code></dd><dt>${{uiCopy['platform.deployment']}}</dt><dd>${{p.deployment_executed?uiCopy['platform.executed']:uiCopy['platform.not_executed']}}</dd><dt>${{uiCopy['platform.framework']}}</dt><dd><code>${{p.agent_framework}}</code></dd></dl><h3>${{uiCopy['platform.missing']}}</h3><ul>${{p.missing_configuration.length?p.missing_configuration.map(value=>`<li>${{value}}</li>`).join(''):'<li>'+uiCopy['platform.none']+'</li>'}}</ul><h3>${{uiCopy['platform.external_checks']}}</h3><ul>${{p.external_verification_required.map(value=>`<li>${{value}}</li>`).join('')}}</ul>`)}}catch(e){{show(uiCopy['error.preflight'])}}finally{{platformPreflightButton.disabled=false}}}});
directorButton.addEventListener('click',async()=>{{directorButton.disabled=true;try{{const r=await fetch('/api/gemini-director-synthetic-demo',{{method:'POST'}});const d=await r.json();if(!r.ok)throw Error();const script=d.director_script,scenes=script.scenes.map(scene=>`<li><strong>${{escapeHtml(scene.role)}}</strong>: ${{scene.event_count}} (${{escapeHtml(scene.transition_type)}})${{scene.overlay_text?' — '+escapeHtml(scene.overlay_text):''}}</li>`).join('');show(`<h2>${{uiCopy['director.heading']}}</h2><p>${{d.notice}}</p><dl><dt>${{uiCopy['director.composer']}}</dt><dd><code>${{escapeHtml(script.composer)}}</code></dd><dt>${{uiCopy['director.fallback']}}</dt><dd>${{script.fallback_used?uiCopy['common.yes']:uiCopy['common.no']}}</dd><dt>${{uiCopy['director.scene_count']}}</dt><dd>${{script.scenes.length}}</dd></dl><ol>${{scenes}}</ol><p>${{uiCopy['director.external_notice']}}</p>`)}}catch(e){{show(uiCopy['error.director'])}}finally{{directorButton.disabled=false}}}});
gpxButton.addEventListener('click',async()=>{{const file=gpxInput.files[0];if(!file){{show(uiCopy['gpx.select']);return}}gpxButton.disabled=true;try{{const contents=await file.text();drawRoute(routePoints(contents));const r=await fetch('/api/private-gpx-summary?lang='+uiLanguage,{{method:'POST',headers:{{'Content-Type':'application/gpx+xml'}},body:contents}});const d=await r.json();if(!r.ok)throw Error();const s=d.route_summary,c=d.candidate_edit_plan;show(`<h2>${{uiCopy['gpx.result']}}</h2><p>${{d.notice}}</p><dl><dt>${{uiCopy['gpx.distance_duration']}}</dt><dd>${{s.distance_km}}km / ${{s.duration_minutes}}min</dd><dt>${{uiCopy['gpx.elevation']}}</dt><dd>${{s.elevation_gain_m}}m / ${{s.elevation_loss_m}}m</dd><dt>${{uiCopy['gpx.events']}}</dt><dd>${{d.raw_event_count}} / ${{d.consolidated_event_count}}</dd><dt>Story Plan</dt><dd>${{d.story_plan.chapter_roles.join(' → ')}}</dd><dt>${{uiCopy['gpx.candidate']}}</dt><dd>${{c.candidate_duration_s}}s / ${{c.is_ready_for_edit?uiCopy['common.yes']:uiCopy['common.no']}}</dd></dl><h3>${{uiCopy['candidate.review_reasons']}}</h3><ul>${{c.reasons.map(reason=>`<li>${{reason}}</li>`).join('')}}</ul>`)}}catch(e){{show(uiCopy['error.gpx'])}}finally{{gpxButton.disabled=false}}}});
downloadButton.addEventListener('click',()=>{{const blob=new Blob([JSON.stringify(latestRecord,null,2)],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='ride-storyteller-demo-record.json';a.click();URL.revokeObjectURL(a.href)}});
</script>{maps_script}{source_footer}</main></body></html>"""


def main() -> None:
    deployment = WebDeploymentSettings.from_environment()
    with make_server(deployment.host, deployment.port, application) as server:
        print(
            f"Ride Storyteller demo ({deployment.mode.value}): "
            f"http://{deployment.host}:{deployment.port}"
        )
        server.serve_forever()


if __name__ == "__main__":
    main()
