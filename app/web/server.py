"""A dependency-free local UI for the synthetic Ride Storyteller demo."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable
from html import escape
from io import BytesIO
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
from app.web.maps_config import GoogleMapsSettings
from app.web.private_director_preview import (
    PrivateDirectorPreview,
    PrivateDirectorPreviewError,
)
from app.web.private_evidence_review import (
    PrivateEvidenceReviewError,
    PrivateEvidenceReviewSession,
)
from app.web.private_highlight_review import (
    PrivateHighlightReviewError,
    PrivateHighlightReviewSession,
)
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
    "/private-evidence-review",
    "/api/private-evidence-review",
    "/api/private-evidence-review/asset",
    "/private-director-preview",
    "/api/private-director-preview",
}
_HEALTH_PATHS = {"/health", "/healthz"}
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
    if path == "/private-evidence-review":
        if environ.get("REQUEST_METHOD", "GET") != "GET":
            return _respond(
                start_response,
                "405 Method Not Allowed",
                "application/json; charset=utf-8",
                '{"error":"GETを使用してください。"}'.encode(),
            )
        try:
            PrivateEvidenceReviewSession.from_environment()
        except PrivateEvidenceReviewError:
            return _respond(
                start_response,
                "503 Service Unavailable",
                "application/json; charset=utf-8",
                b'{"error":"private evidence review is unavailable"}',
            )
        language = resolve_language(query.get("lang", [None])[0])
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
        result = asyncio.run(
            run_synthetic_adk_demo(GoogleCloudRuntimeSettings.from_environment())
        )
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
        "failed": "The local review could not be updated." if english else "ローカルreviewを更新できませんでした。",
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
<title>Ride Storyteller — {text['title']}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}}article{{border:1px solid #d7dde5;border-radius:12px;padding:14px}}img,video{{display:block;width:100%;border-radius:8px;background:#17212b;margin:8px 0}}select,button{{font:inherit;padding:8px;margin:5px 0}}button{{background:#1264d6;color:#fff;border:0;border-radius:7px;cursor:pointer}}.status{{font-weight:700}}#notice{{padding:12px;background:#f2f7ff;border-radius:8px}}.reason-wrap[hidden]{{display:none}}small{{color:#53606d}}</style>
</head><body><main><p><a href="/?lang={language.value}">{text['back']}</a></p><h1>{text['title']}</h1><p>{text['intro']}</p><p id="notice" aria-live="polite">{text['loading']}</p><section id="cards" class="grid"></section>
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
        "loading": "Loading local review clips…" if english else "ローカル確認用クリップを読み込み中…",
        "confirmed": "Confirm evidence" if english else "証拠として確認",
        "rejected": "Reject evidence" if english else "証拠として却下",
        "awaiting": "Undecided" if english else "未判断へ戻す",
        "save": "Save decision" if english else "判断を保存",
        "saved": "Saved locally." if english else "ローカルに保存しました。",
        "failed": "The local evidence review could not be updated." if english else "ローカル証拠確認を更新できませんでした。",
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
<title>Ride Storyteller — {text['title']}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}}article{{border:1px solid #d7dde5;border-radius:12px;padding:14px}}video{{display:block;width:100%;border-radius:8px;background:#17212b;margin:8px 0}}select,button{{font:inherit;padding:8px;margin:5px 0}}button{{background:#1264d6;color:#fff;border:0;border-radius:7px;cursor:pointer}}#notice{{padding:12px;background:#f2f7ff;border-radius:8px}}</style>
</head><body><main><p><a href="/?lang={language.value}">{text['back']}</a></p><h1>{text['title']}</h1><p>{text['intro']}</p><p id="notice" aria-live="polite">{text['loading']}</p><section id="cards" class="grid"></section>
<script>
const text={strings_json},gateLabels={gate_labels_json};
const notice=document.querySelector('#notice'),cards=document.querySelector('#cards');
function summary(counts,nextGate){{return text.summary.replace('{{confirmed}}',counts.confirmed).replace('{{rejected}}',counts.rejected).replace('{{awaiting}}',counts.awaiting_video_evidence)+' / '+text.next+': '+(gateLabels[nextGate]||text.failed)}}
function card(candidate){{const article=document.createElement('article'),title=document.createElement('h2'),video=document.createElement('video'),statusLabel=document.createElement('label'),status=document.createElement('select'),save=document.createElement('button');title.textContent=candidate.review_id;video.src=candidate.media_url;video.controls=true;video.preload='metadata';for(const [value,label] of [['confirmed',text.confirmed],['rejected',text.rejected],['awaiting_video_evidence',text.awaiting]]){{const option=document.createElement('option');option.value=value;option.textContent=label;option.selected=candidate.status===value;status.append(option)}}statusLabel.textContent=text.status+' ';statusLabel.append(status);save.textContent=text.save;save.addEventListener('click',async()=>{{save.disabled=true;try{{const response=await fetch('/api/private-evidence-review',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{review_id:candidate.review_id,status:status.value}})}});if(!response.ok)throw Error();const payload=await response.json(),updatedCandidate=payload.review.candidates.find(item=>item.review_id===candidate.review_id);if(!updatedCandidate)throw Error();candidate.status=updatedCandidate.status;notice.textContent=`${{text.saved}} ${{summary(payload.review.status_counts,payload.next_gate)}}`}}catch(error){{notice.textContent=text.failed}}finally{{save.disabled=false}}}});article.append(title,video,statusLabel,save);return article}}
function render(payload){{cards.replaceChildren(...payload.review.candidates.map(card));notice.textContent=summary(payload.review.status_counts,payload.next_gate)}}
fetch('/api/private-evidence-review').then(response=>{{if(!response.ok)throw Error();return response.json()}}).then(render).catch(()=>{{notice.textContent=text.failed}});
</script></main></body></html>"""


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
        "loading": "Loading local story structure…" if english else "ローカルの物語構成を読み込み中…",
        "failed": "The local story structure is unavailable." if english else "ローカルの物語構成を読み込めませんでした。",
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
    coverage_labels_json = json.dumps(coverage_labels, ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    return f"""<!doctype html>
<html lang="{language.value}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ride Storyteller — {text['title']}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:#fff;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}#notice{{padding:12px;background:#f2f7ff;border-radius:8px}}li{{margin:10px 0}}code{{background:#e9edf2;padding:2px 4px;border-radius:4px}}</style>
</head><body><main><p><a href="/?lang={language.value}">{text['back']}</a></p><h1>{text['title']}</h1><p>{text['intro']}</p><p id="notice" aria-live="polite">{text['loading']}</p><section id="script" hidden></section>
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
            f'{text("director.preview.open")}</a></p>'
        )
    )
    private_evidence_review_link = (
        ""
        if deployment.public_demo
        else (
            f'<p><a href="/private-evidence-review?lang={language.value}">'
            f'{"映像証拠を確認" if language is UiLanguage.JAPANESE else "Review visual evidence"}</a></p>'
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
            f'{text("source.pending")}</p></footer>'
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
