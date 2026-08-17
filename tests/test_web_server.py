import json
from io import BytesIO
from pathlib import Path

import pytest

from app.agent_runtime import AdkSyntheticRun, SyntheticAgentRuntimeVerification
from app.web.server import _page, application


def _request(
    path: str, query_string: str = "", body: bytes = b"", method: str = "GET"
) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(
        application(
            {
                "PATH_INFO": path,
                "QUERY_STRING": query_string,
                "REQUEST_METHOD": method,
                "CONTENT_LENGTH": str(len(body)),
                "wsgi.input": BytesIO(body),
            },
            start_response,
        )
    )
    return captured["status"], captured["headers"], body  # type: ignore[return-value]


def test_demo_api_returns_synthetic_agent_decision() -> None:
    status, headers, body = _request("/api/demo")

    assert status == "200 OK"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert '"demo_mode": true' in body.decode()
    assert '"needs_video_evidence": true' in body.decode()
    assert '"decision_status": "accepted"' in body.decode()


def test_demo_api_generates_selected_language_without_changing_status() -> None:
    japanese_status, _, japanese_body = _request("/api/demo", "scenario=accepted")
    english_status, _, english_body = _request("/api/demo", "scenario=accepted&lang=en")

    japanese = japanese_body.decode()
    english = english_body.decode()
    assert japanese_status == english_status == "200 OK"
    assert '"language": "ja"' in japanese
    assert '"language": "en"' in english
    assert '"decision_status": "accepted"' in japanese
    assert '"decision_status": "accepted"' in english
    assert "映像解析がGPSイベントの物語上の重要性を裏付けた。" in japanese
    assert "The video analysis supports this GPS event's importance" in english
    assert "映像解析がGPSイベント" not in english


def test_web_page_and_unknown_route_have_expected_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    status, _, body = _request("/")
    assert status == "200 OK"
    assert "判断デモを実行" in body.decode()
    assert "Story Planを見る" in body.decode()
    assert "候補クリップ計画を見る" in body.decode()
    assert "ADK合成デモを実行" in body.decode()
    assert "クラウドRuntime合成テストを実行" in body.decode()
    assert "Google Cloudの利用料金が発生する可能性があります" in body.decode()
    assert "設定状態を確認" in body.decode()
    assert "動画フォルダ棚卸しを開く" in body.decode()
    assert "ルート地図" in body.decode()
    assert "GOOGLE_MAPS_API_KEY" in body.decode()

    missing_status, _, _ = _request("/unknown")
    assert missing_status == "404 Not Found"


def test_local_media_inventory_page_is_client_only_and_external_script_free() -> None:
    status, headers, body = _request("/local-media-inventory")

    decoded = body.decode()
    assert status == "200 OK"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert "ローカル動画棚卸し" in decoded
    assert "webkitdirectory" in decoded
    assert "buildBrowserMediaInventory" in decoded
    assert "local-video-inventory-v1" in decoded
    assert "maps.googleapis.com" not in decoded
    assert "fetch(" not in decoded
    assert "XMLHttpRequest" not in decoded
    assert "FileReader" not in decoded
    assert ".arrayBuffer(" not in decoded


def test_demo_api_exposes_safe_failure_scenarios() -> None:
    rejected_status, _, rejected_body = _request("/api/demo", "scenario=rejected")
    missing_status, _, missing_body = _request("/api/demo", "scenario=missing_asset")
    unavailable_status, _, unavailable_body = _request("/api/demo", "scenario=gemini_unavailable")

    assert rejected_status == missing_status == unavailable_status == "200 OK"
    assert '"decision_status": "rejected"' in rejected_body.decode()
    assert '"decision_status": "needs_human_review"' in missing_body.decode()
    assert '"decision_status": "needs_human_review"' in unavailable_body.decode()


def test_story_plan_and_invalid_scenario_are_exposed() -> None:
    plan_status, _, plan_body = _request("/api/story-plan")
    english_status, _, english_body = _request("/api/story-plan", "lang=en")
    invalid_status, _, invalid_body = _request("/api/demo", "scenario=not-real")

    assert plan_status == "200 OK"
    assert '"planning_provider": "rule_based_mock"' in plan_body.decode()
    assert '"language": "ja"' in plan_body.decode()
    assert "123.4kmをたどる旅" in plan_body.decode()
    assert english_status == "200 OK"
    assert '"language": "en"' in english_body.decode()
    assert "A 123.4 km journey" in english_body.decode()
    assert "Changing scenery" in english_body.decode()
    assert "123.4kmをたどる旅" not in english_body.decode()
    assert invalid_status == "400 Bad Request"
    assert '"error":"unknown demo scenario"' in invalid_body.decode()


def test_story_plan_page_requests_the_selected_language() -> None:
    _, _, english_page = _request("/", "lang=en")
    decoded = english_page.decode()

    assert "fetch('/api/story-plan?lang='+uiLanguage)" in decoded
    assert "storyTitle" not in decoded
    assert "d.story_plan.title" in decoded
    assert "&lang='+uiLanguage" in decoded
    assert "d.decision.reason" in decoded
    assert "fetch('/api/candidate-edit-plan?lang='+uiLanguage)" in decoded
    assert "q.reasons.map" in decoded
    assert "fetch('/api/private-gpx-summary?lang='+uiLanguage" in decoded
    assert "c.reasons.map" in decoded


def test_candidate_edit_plan_is_explicitly_not_ready_without_video_evidence() -> None:
    status, _, body = _request("/api/candidate-edit-plan")

    decoded = body.decode()
    assert status == "200 OK"
    assert '"status": "needs_more_evidence"' in decoded
    assert '"is_ready_for_edit": false' in decoded
    assert '"private_data_used"' not in decoded


def test_candidate_plan_api_localizes_prose_without_changing_plan_structure() -> None:
    japanese_status, _, japanese_body = _request("/api/candidate-edit-plan")
    english_status, _, english_body = _request("/api/candidate-edit-plan", "lang=en")

    japanese = json.loads(japanese_body)
    english = json.loads(english_body)
    assert japanese_status == english_status == "200 OK"
    assert japanese["language"] == "ja"
    assert english["language"] == "en"
    assert japanese["candidate_edit_plan"]["story_title"] == "123.4kmをたどる旅"
    assert english["candidate_edit_plan"]["story_title"] == "A 123.4 km journey"

    japanese_plan = dict(japanese["candidate_edit_plan"])
    english_plan = dict(english["candidate_edit_plan"])
    japanese_plan.pop("story_title")
    english_plan.pop("story_title")
    assert english_plan == japanese_plan

    japanese_review = dict(japanese["quality_review"])
    english_review = dict(english["quality_review"])
    japanese_reasons = japanese_review.pop("reasons")
    english_reasons = english_review.pop("reasons")
    assert english_review == japanese_review
    assert "候補クリップの映像証拠が未確認です。" in japanese_reasons
    assert "Candidate clips still require visual evidence." in english_reasons


def test_private_gpx_summary_parses_in_memory_without_returning_coordinates() -> None:
    body = Path("tests/fixtures/sample_route.xml").read_bytes()
    status, _, response_body = _request("/api/private-gpx-summary", body=body)

    decoded = response_body.decode()
    assert status == "200 OK"
    assert '"local_only": true' in decoded
    assert '"point_count": 3' in decoded
    assert '"missing_duration_s"' in decoded
    assert '"awaiting_evidence_count"' in decoded
    assert '"rejected_evidence_count"' in decoded
    assert "latitude" not in decoded
    assert "longitude" not in decoded


def test_private_gpx_summary_localizes_prose_without_exposing_coordinates() -> None:
    body = Path("tests/fixtures/sample_route.xml").read_bytes()
    japanese_status, _, japanese_body = _request("/api/private-gpx-summary", body=body)
    english_status, _, english_body = _request("/api/private-gpx-summary", "lang=en", body=body)

    japanese = json.loads(japanese_body)
    english = json.loads(english_body)
    assert japanese_status == english_status == "200 OK"
    assert japanese["language"] == "ja"
    assert english["language"] == "en"
    assert japanese["story_plan"]["title"].endswith("kmをたどる旅")
    assert english["story_plan"]["title"].startswith("A ")
    assert "候補クリップの映像証拠が未確認です。" in (japanese["candidate_edit_plan"]["reasons"])
    assert (
        "Candidate clips still require visual evidence."
        in (english["candidate_edit_plan"]["reasons"])
    )

    assert english["route_summary"] == japanese["route_summary"]
    assert english["event_counts"] == japanese["event_counts"]
    assert english["story_plan"]["chapter_roles"] == (japanese["story_plan"]["chapter_roles"])
    for response_body in (japanese_body.decode(), english_body.decode()):
        assert "latitude" not in response_body
        assert "longitude" not in response_body


def test_private_gpx_summary_rejects_malformed_and_oversized_uploads() -> None:
    malformed_status, _, _ = _request("/api/private-gpx-summary", body=b"not a GPX file")
    oversized_status, _, _ = _request(
        "/api/private-gpx-summary",
        body=b"x" * (20 * 1024 * 1024 + 1),
    )

    assert malformed_status == "400 Bad Request"
    assert oversized_status == "400 Bad Request"


def test_google_runtime_status_never_includes_private_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    status, _, body = _request("/api/google-runtime")

    decoded = body.decode()
    assert status == "200 OK"
    assert '"private_data_used": false' in decoded
    assert "latitude" not in decoded
    assert "longitude" not in decoded
    assert "GOOGLE_MAPS_API_KEY" not in decoded


def test_agent_platform_preflight_exposes_only_safe_local_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    status, _, body = _request("/api/agent-platform-preflight")

    decoded = body.decode()
    assert status == "200 OK"
    assert '"deployment_executed": false' in decoded
    assert '"private_data_used": false' in decoded
    assert "latitude" not in decoded
    assert "longitude" not in decoded
    assert "GOOGLE_MAPS_API_KEY" not in decoded


def test_adk_synthetic_endpoint_refuses_data_and_uses_only_post() -> None:
    get_status, _, _ = _request("/api/adk-synthetic-demo")
    data_status, _, _ = _request("/api/adk-synthetic-demo", body=b"not allowed", method="POST")

    assert get_status == "405 Method Not Allowed"
    assert data_status == "400 Bad Request"


def test_adk_synthetic_endpoint_returns_safe_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_adk_run(_: object) -> AdkSyntheticRun:
        return AdkSyntheticRun(
            model="gemini-2.5-flash",
            final_response_received=True,
            tool_called=True,
        )

    monkeypatch.setattr("app.agent_runtime.run_synthetic_adk_demo", fake_adk_run)
    status, _, body = _request("/api/adk-synthetic-demo", method="POST")

    decoded = body.decode()
    assert status == "200 OK"
    assert '"private_data_used": false' in decoded
    assert '"tool_called": true' in decoded
    assert "latitude" not in decoded
    assert "longitude" not in decoded


def test_agent_platform_synthetic_endpoint_refuses_data_and_uses_only_post() -> None:
    get_status, _, _ = _request("/api/agent-platform-synthetic-demo")
    data_status, _, _ = _request(
        "/api/agent-platform-synthetic-demo", body=b"not allowed", method="POST"
    )

    assert get_status == "405 Method Not Allowed"
    assert data_status == "400 Bad Request"


def test_agent_platform_synthetic_endpoint_returns_safe_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_hosted_run(_: object) -> SyntheticAgentRuntimeVerification:
        return SyntheticAgentRuntimeVerification(
            final_response_received=True,
            tool_called=True,
        )

    monkeypatch.setattr(
        "app.agent_runtime.run_hosted_synthetic_agent_runtime",
        fake_hosted_run,
    )
    status, _, body = _request("/api/agent-platform-synthetic-demo", method="POST")

    decoded = body.decode()
    assert status == "200 OK"
    assert '"external_service_called": true' in decoded
    assert '"billing_may_apply": true' in decoded
    assert '"private_data_used": false' in decoded
    assert '"tool_called": true' in decoded
    assert '"final_response_received": true' in decoded
    assert "reasoningEngines" not in decoded
    assert "latitude" not in decoded
    assert "longitude" not in decoded


def test_page_loads_maps_only_when_the_local_key_is_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-browser-key")

    page = _page()

    assert "maps.googleapis.com/maps/api/js?" in page
    assert "key=test-browser-key" in page
    assert page.index("window.initRideMap") < page.index("maps.googleapis.com/maps/api/js?")


def test_public_demo_disables_private_and_billable_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")
    for path in (
        "/api/adk-synthetic-demo",
        "/api/agent-platform-preflight",
        "/api/agent-platform-synthetic-demo",
        "/api/google-runtime",
        "/api/private-gpx-summary",
    ):
        status, _, body = _request(path, method="POST")
        assert status == "403 Forbidden"
        assert body == b'{"error":"disabled in public demo mode"}'


def test_public_demo_page_disables_controls_and_never_loads_maps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-browser-key")

    status, _, body = _request("/", "lang=en")
    page = body.decode()

    assert status == "200 OK"
    assert "Public safe-demo mode" in page
    assert 'id="adkRun" disabled' in page
    assert 'id="platformRun" disabled' in page
    assert 'id="platformPreflight" disabled' in page
    assert 'id="gpx" type="file" accept=".gpx,application/gpx+xml" disabled' in page
    assert 'id="gpxRun" disabled' in page
    assert "maps.googleapis.com" not in page
    assert "test-browser-key" not in page


def test_public_demo_keeps_deterministic_views_and_health_check_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIDE_WEB_MODE", "public_demo")

    demo_status, _, demo_body = _request("/api/demo")
    health_status, health_headers, health_body = _request("/healthz")

    assert demo_status == "200 OK"
    assert '"demo_mode": true' in demo_body.decode()
    assert health_status == "200 OK"
    assert health_body.decode() == (
        '{"status": "ok", "mode": "public_demo", '
        '"external_actions_enabled": false, "private_gpx_enabled": false}'
    )
    assert health_headers["Cache-Control"] == "no-store"
    assert health_headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert health_headers["Referrer-Policy"] == "no-referrer"
    assert health_headers["X-Content-Type-Options"] == "nosniff"
    assert health_headers["X-Frame-Options"] == "DENY"
