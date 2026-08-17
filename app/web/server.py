"""A dependency-free local UI for the synthetic Ride Storyteller demo."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable
from html import escape
from io import BytesIO
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server
from xml.etree import ElementTree

from app.agent_runtime import (
    AdkSyntheticRunError,
    AgentPlatformDeploymentError,
    AgentPlatformDeploymentSettings,
    AgentPlatformPreparationError,
    GoogleCloudRuntimeSettings,
    run_hosted_synthetic_agent_runtime,
    run_synthetic_adk_demo,
)
from app.agents import RuleBasedStoryPlanner, StoryOutputLanguage
from app.demo import (
    build_demo_candidate_edit_plan,
    build_demo_event,
    build_demo_story_plan,
    run_demo,
)
from app.edit import CandidateEditReview, build_candidate_edit_plan, review_candidate_edit_plan
from app.gps import consolidate_events, extract_events, parse_gpx_bytes
from app.web.deployment import WebDeploymentSettings
from app.web.i18n import UiLanguage, copy_for, resolve_language
from app.web.maps_config import GoogleMapsSettings

StartResponse = Callable[[str, list[tuple[str, str]]], Callable[[bytes], object]]
_PUBLIC_DEMO_DISABLED_PATHS = {
    "/api/adk-synthetic-demo",
    "/api/agent-platform-preflight",
    "/api/agent-platform-synthetic-demo",
    "/api/google-runtime",
    "/api/private-gpx-summary",
}


def application(environ: dict[str, object], start_response: StartResponse) -> Iterable[bytes]:
    path = environ.get("PATH_INFO", "/")
    query = parse_qs(str(environ.get("QUERY_STRING", "")))
    deployment = WebDeploymentSettings.from_environment()
    if path == "/healthz":
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
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(_google_runtime_payload(), ensure_ascii=False).encode(),
        )
    if path == "/api/agent-platform-preflight":
        return _respond(
            start_response,
            "200 OK",
            "application/json; charset=utf-8",
            json.dumps(_agent_platform_preflight_payload(), ensure_ascii=False).encode(),
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
        except AdkSyntheticRunError:
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
        except (AgentPlatformDeploymentError, AgentPlatformPreparationError):
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
    start_response: StartResponse, status: str, content_type: str, body: bytes
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
        ],
    )
    return [body]


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
    settings = GoogleCloudRuntimeSettings.from_environment()
    return {
        "private_data_used": False,
        "notice": "設定状態のみを表示します。GPX・映像・認証情報は使用しません。",
        "google_cloud_configuration": settings.to_dict(),
        "synthetic_adk_demo_available": settings.status == "configuration_present",
    }


def _agent_platform_preflight_payload() -> dict[str, object]:
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
    result = asyncio.run(run_synthetic_adk_demo(GoogleCloudRuntimeSettings.from_environment()))
    return {
        "private_data_used": False,
        "notice": "固定の合成イベントだけをGoogle ADK / Geminiへ送信しました。",
        "adk_synthetic_demo": result.to_dict(),
    }


def _agent_platform_synthetic_demo_payload() -> dict[str, object]:
    runtime = GoogleCloudRuntimeSettings.from_environment()
    deployment = AgentPlatformDeploymentSettings.from_environment(runtime)
    result = run_hosted_synthetic_agent_runtime(deployment)
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
    return f"""<!doctype html>
<html lang="{language.value}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ride Storyteller — Demo</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#17212b;background:#f7f8fa}}main{{background:white;border-radius:16px;padding:28px;box-shadow:0 2px 10px #0001}}button{{background:#1264d6;color:white;border:0;border-radius:8px;padding:12px 18px;font-size:16px;cursor:pointer}}button:disabled{{background:#8892a0}}#notice{{color:#53606d}}#result{{display:none;margin-top:24px;padding:18px;background:#f2f7ff;border-radius:10px}}#map{{height:360px;margin-top:16px;border-radius:10px;background:#e9edf2}}dt{{font-weight:600;margin-top:10px}}dd{{margin:4px 0}}ol{{padding-left:22px}}code{{background:#e9edf2;padding:2px 4px;border-radius:4px}}.warning{{color:#8a3b12;background:#fff3e8;padding:12px;border-radius:8px}}.language-switch{{text-align:right;margin-bottom:18px}}.language-switch [aria-current="page"]{{font-weight:700;text-decoration:none}}</style>
</head><body><main>{_language_switch(language, "/")}{public_notice}
<p id="notice">{text("main.notice")}</p>
<h1>{text("main.title")}</h1><p>{text("main.intro")}</p>
<label>{text("demo.scenario")} <select id="scenario"><option value="accepted">{text("scenario.accepted")}</option><option value="rejected">{text("scenario.rejected")}</option><option value="missing_asset">{text("scenario.missing_asset")}</option><option value="gemini_unavailable">{text("scenario.gemini_unavailable")}</option></select></label>
<p><button id="run">{text("demo.run")}</button> <button id="plan">{text("demo.story_plan")}</button> <button id="candidate">{text("demo.candidate_plan")}</button> <button id="download" disabled>{text("demo.download")}</button></p><hr><h2>{text("adk.heading")}</h2><p>{text("adk.description")}</p><p><button id="adkRun"{external_disabled}>{text("adk.run")}</button></p><hr><h2>{text("platform.heading")}</h2><p>{text("platform.description")}</p><p><button id="platformRun"{external_disabled}>{text("platform.run")}</button> <button id="platformPreflight"{external_disabled}>{text("platform.preflight")}</button></p><hr><h2>{text("inventory.heading")}</h2><p>{text("inventory.main_description")}</p><p><a href="/local-media-inventory?lang={language.value}">{text("inventory.open")}</a></p><hr><h2>{text("gpx.heading")}</h2><p>{text("gpx.description")}</p><input id="gpx" type="file" accept=".gpx,application/gpx+xml"{private_disabled}><button id="gpxRun"{private_disabled}>{text("gpx.run")}</button><section id="result" aria-live="polite"></section>
<h2>{text("map.heading")}</h2><p id="mapStatus">{maps_status}</p><p>{text("map.privacy")}</p><div id="map" aria-label="{text("map.aria")}"></div>
<script>
const uiCopy={_copy_json(language)}, uiLanguage='{language.value}';
function formatCopy(key,values={{}}){{return Object.entries(values).reduce((value,[name,replacement])=>value.replaceAll(`{{${{name}}}}`,String(replacement)),uiCopy[key])}}
function reviewReasons(review){{const values=[];if((review.missing_duration_s||0)>0)values.push(uiCopy['candidate.reason.duration']);const awaiting=review.event_ids_requiring_evidence?.length??review.awaiting_evidence_count??0,rejected=review.rejected_event_ids?.length??review.rejected_evidence_count??0;if(awaiting)values.push(uiCopy['candidate.reason.awaiting']);if(rejected)values.push(uiCopy['candidate.reason.rejected']);return values}}
function storyChapter(chapter){{return chapter.title+': '+chapter.selection_rationale+` (${{chapter.target_duration_s}}s)`}}
const runButton=document.querySelector('#run'), planButton=document.querySelector('#plan'), candidateButton=document.querySelector('#candidate'), downloadButton=document.querySelector('#download'), adkButton=document.querySelector('#adkRun'), platformRunButton=document.querySelector('#platformRun'), platformPreflightButton=document.querySelector('#platformPreflight'), gpxButton=document.querySelector('#gpxRun'), gpxInput=document.querySelector('#gpx'), scenario=document.querySelector('#scenario'), result=document.querySelector('#result');let latestRecord=null;
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
gpxButton.addEventListener('click',async()=>{{const file=gpxInput.files[0];if(!file){{show(uiCopy['gpx.select']);return}}gpxButton.disabled=true;try{{const contents=await file.text();drawRoute(routePoints(contents));const r=await fetch('/api/private-gpx-summary?lang='+uiLanguage,{{method:'POST',headers:{{'Content-Type':'application/gpx+xml'}},body:contents}});const d=await r.json();if(!r.ok)throw Error();const s=d.route_summary,c=d.candidate_edit_plan;show(`<h2>${{uiCopy['gpx.result']}}</h2><p>${{d.notice}}</p><dl><dt>${{uiCopy['gpx.distance_duration']}}</dt><dd>${{s.distance_km}}km / ${{s.duration_minutes}}min</dd><dt>${{uiCopy['gpx.elevation']}}</dt><dd>${{s.elevation_gain_m}}m / ${{s.elevation_loss_m}}m</dd><dt>${{uiCopy['gpx.events']}}</dt><dd>${{d.raw_event_count}} / ${{d.consolidated_event_count}}</dd><dt>Story Plan</dt><dd>${{d.story_plan.chapter_roles.join(' → ')}}</dd><dt>${{uiCopy['gpx.candidate']}}</dt><dd>${{c.candidate_duration_s}}s / ${{c.is_ready_for_edit?uiCopy['common.yes']:uiCopy['common.no']}}</dd></dl><h3>${{uiCopy['candidate.review_reasons']}}</h3><ul>${{c.reasons.map(reason=>`<li>${{reason}}</li>`).join('')}}</ul>`)}}catch(e){{show(uiCopy['error.gpx'])}}finally{{gpxButton.disabled=false}}}});
downloadButton.addEventListener('click',()=>{{const blob=new Blob([JSON.stringify(latestRecord,null,2)],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='ride-storyteller-demo-record.json';a.click();URL.revokeObjectURL(a.href)}});
</script>{maps_script}</main></body></html>"""


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
