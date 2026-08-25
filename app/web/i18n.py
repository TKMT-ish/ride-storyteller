"""Small, dependency-free localization boundary for the local web UI."""

from __future__ import annotations

import os
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from app.config import load_local_environment


class UiLanguage(StrEnum):
    JAPANESE = "ja"
    ENGLISH = "en"


DEFAULT_UI_LANGUAGE = UiLanguage.JAPANESE
UI_LANGUAGE_ENV = "RIDE_UI_DEFAULT_LANGUAGE"


_COPY: dict[UiLanguage, dict[str, str]] = {
    UiLanguage.JAPANESE: {
        "language.switch_label": "表示言語",
        "language.japanese": "日本語",
        "language.english": "English",
        "common.back_to_demo": "← デモ画面へ戻る",
        "common.success": "成功",
        "common.failure": "失敗",
        "common.yes": "はい",
        "common.no": "いいえ",
        "main.title": "Ride Storyteller",
        "main.notice": (
            "ローカル・モックデモ。通常の操作では実動画、GPS、Box、"
            "Gemini認証情報は使用しません。"
        ),
        "deployment.public_notice": (
            "公開安全デモモード：私用GPX入力、Google Maps、ローカル／クラウドADK実行、"
            "Runtime設定確認は無効です。合成モック表示だけを利用できます。"
        ),
        "source.link": "ソースコード（AGPL-3.0）",
        "source.pending": (
            "Sourceリンクが未設定です。公開リポジトリを設定するまで一般公開を有効にできません。"
        ),
        "main.intro": "GPSの出来事を起点に、映像証拠が必要かをAgentが判断する流れを確認できます。",
        "demo.scenario": "デモシナリオ",
        "scenario.accepted": "映像証拠により採用",
        "scenario.rejected": "映像証拠により不採用",
        "scenario.missing_asset": "対応する素材が見つからない",
        "scenario.gemini_unavailable": "Gemini映像解析が利用できない",
        "demo.run": "判断デモを実行",
        "demo.story_plan": "Story Planを見る",
        "demo.candidate_plan": "候補クリップ計画を見る",
        "demo.download": "判断記録を保存",
        "demo.synthetic_notice": "合成GPSイベントとモック映像解析のみを使用しています。",
        "demo.gps_event": "GPSイベント",
        "demo.importance": "重要度",
        "demo.video_evidence": "映像証拠",
        "demo.required": "必要",
        "demo.not_required": "不要",
        "demo.final_status": "最終状態",
        "demo.reason": "理由",
        "demo.agent_flow": "Agentの流れ",
        "demo.step.1": "GPSイベントを受信",
        "demo.step.2": "Story Agentが映像証拠の要否を判断",
        "demo.step.3": "素材検索",
        "demo.step.4": "映像解析または人手確認への切替",
        "demo.step.5": "Story Agentが最終判断",
        "demo.reason.accepted": "映像解析がGPSイベントの物語上の重要性を裏付けました。",
        "demo.reason.rejected": "映像解析では物語上の重要性を十分に裏付けられませんでした。",
        "demo.reason.missing_asset": "対応する素材がないため、人による確認が必要です。",
        "demo.reason.gemini_unavailable": "映像解析を利用できないため、人による確認が必要です。",
        "story.heading": "仮Story Plan",
        "story.notice": "合成GPSイベントだけから作成した仮Story Planです。",
        "story.synthetic_title": "合成ルートのストーリー案",
        "candidate.heading": "候補クリップ計画",
        "candidate.notice": "編集指示ではなく、実映像の確認前に作る候補クリップ計画です。",
        "candidate.target_duration": "目標尺 / 候補尺",
        "candidate.coverage": "充足率",
        "candidate.status": "状態",
        "candidate.edit_ready": "編集可能か",
        "candidate.ready": "人手確認へ進めます",
        "candidate.not_ready": "まだ進めません",
        "candidate.review_reasons": "確認が必要な理由",
        "candidate.clips": "候補クリップ",
        "candidate.reason.duration": "目標尺を満たす候補クリップが不足しています。",
        "candidate.reason.awaiting": "候補クリップの映像証拠が未確認です。",
        "candidate.reason.rejected": "映像証拠が不適切な候補があります。差し替えが必要です。",
        "ibm.heading": "IBM Bobによる開発レビュー",
        "ibm.description": (
            "IBM Bobが開発中のコード構成とAgentの流れをレビューし、優先課題を特定しました。"
        ),
        "ibm.finding.1": "Google ADKのAgent・ツール接続を追加",
        "ibm.finding.2": "映像証拠の確認・却下状態と安全停止を追加",
        "ibm.finding.3": "Gemini映像境界と不足していた境界テストを追加",
        "ibm.limit": "開発工程の証跡です。実映像解析や公開完了を示すものではありません。",
        "adk.heading": "Google ADK 合成デモ",
        "adk.description": (
            "固定の合成イベントだけをGoogle ADK / Geminiへ送信し、Agentがツールを使うことを"
            "確認します。GPX・映像・座標・入力文章は送信しません。"
        ),
        "adk.run": "ADK合成デモを実行",
        "platform.heading": "Agent Platform クラウド合成デモ",
        "platform.description": (
            "作成済みの東京Runtimeへ固定の合成イベントだけを送ります。GPX・映像・座標・"
            "入力文章は送信しません。この操作は外部通信を行い、Google Cloudの利用料金が"
            "発生する可能性があります。"
        ),
        "platform.run": "クラウドRuntime合成テストを実行",
        "platform.preflight": "設定状態を確認",
        "platform.runtime": "Runtime",
        "platform.model": "モデル",
        "platform.tool": "固定ツールの呼び出し",
        "platform.response": "最終応答の受信",
        "platform.private_data": "私用データ",
        "platform.used": "使用",
        "platform.not_used": "未使用",
        "platform.external_notice": "この操作はGoogle Cloudへの外部呼び出しです。",
        "platform.preflight_heading": "Agent Platform デプロイ準備",
        "platform.deployment": "デプロイ実行",
        "platform.executed": "実行済み",
        "platform.not_executed": "未実行",
        "platform.framework": "Agentフレームワーク",
        "platform.missing": "ローカル設定で不足している項目",
        "platform.none": "なし（ただし外部確認と承認が必要です）",
        "platform.external_checks": "デプロイ前の外部確認",
        "inventory.heading": "ローカル動画棚卸し",
        "inventory.main_description": (
            "動画を開かず、ファイル名・相対パス・サイズ・更新時刻だけで非公開JSONを作成します。"
            "外部送信のない専用ページを使用します。"
        ),
        "inventory.open": "動画フォルダ棚卸しを開く",
        "inventory.description": (
            "GoPro動画のフォルダを選び、ファイルシステムのメタデータだけで非公開JSONを"
            "作成します。"
        ),
        "inventory.targets": "対象",
        "inventory.used": "使用：相対パス、ファイル名、サイズ、更新時刻",
        "inventory.not_used": "不使用：動画フレーム、音声、GPS、座標、絶対パス",
        "inventory.no_upload": "外部送信なし：",
        "inventory.no_upload_detail": (
            "このページはGoogle Mapsを含む外部スクリプトを読み込まず、選択情報を"
            "ローカルサーバーにも送信しません。"
        ),
        "inventory.build": "棚卸しJSONを作成",
        "inventory.select": "動画フォルダを選択してください。",
        "inventory.selected": (
            "{count}件の対応動画を選択しました。動画内容はまだ読み取っていません。"
        ),
        "inventory.none_found": "対応する動画ファイルが見つかりません。",
        "inventory.completed": (
            "棚卸しJSONを作成しました。\n動画：{count}件\n合計：{bytes}バイト\n"
            "動画本体は読み取り・送信していません。"
        ),
        "inventory.failed": "棚卸しJSONを作成できませんでした。フォルダを確認してください。",
        "gpx.heading": "私用GPXのローカル検証",
        "gpx.description": (
            "ファイルはこのブラウザとローカルサーバーのメモリ上でだけ解析し、"
            "保存・外部送信しません。"
        ),
        "gpx.run": "GPXを検証",
        "gpx.select": "GPXファイルを選択してください。",
        "gpx.result": "ローカルGPX検証結果",
        "gpx.distance_duration": "距離 / 走行時間",
        "gpx.elevation": "標高差（上昇 / 下降）",
        "gpx.events": "イベント（元 / 統合後）",
        "gpx.candidate": "候補尺 / 編集可能か",
        "map.heading": "ルート地図",
        "map.enabled": "Google Mapsを利用できます。GPXを選択すると、ルート線を地図へ表示します。",
        "map.disabled": (
            "地図を表示するには、ローカルの `.env` に GOOGLE_MAPS_API_KEY を設定してください。"
        ),
        "map.privacy": (
            "地図を表示すると、選択したGPXの座標はブラウザからGoogle Mapsへ送られます。"
            "GPXファイル自体は保存・アップロードしません。"
        ),
        "map.aria": "選択したGPXのルート地図",
        "map.waiting": "Google Mapsの読み込み待ち、またはAPIキーが未設定です。",
        "map.points": "{count}点のGPXルートを表示しています。",
        "error.demo": "デモの実行に失敗しました。",
        "error.story": "Story Planの取得に失敗しました。",
        "error.candidate": "候補クリップ計画の取得に失敗しました。",
        "error.adk": "Google ADK合成デモを実行できませんでした。",
        "error.platform": "クラウドRuntime合成テストを実行できませんでした。",
        "error.preflight": "デプロイ前提を確認できませんでした。",
        "error.gpx": "GPXを解析できませんでした。",
    },
    UiLanguage.ENGLISH: {
        "language.switch_label": "Display language",
        "language.japanese": "日本語",
        "language.english": "English",
        "common.back_to_demo": "← Back to demo",
        "common.success": "Succeeded",
        "common.failure": "Failed",
        "common.yes": "Yes",
        "common.no": "No",
        "main.title": "Ride Storyteller",
        "main.notice": (
            "Local mock demo. Normal operation does not use private video, GPS, Box, "
            "or Gemini credentials."
        ),
        "deployment.public_notice": (
            "Public safe-demo mode: private GPX input, Google Maps, local/cloud ADK execution, "
            "and Runtime configuration checks are disabled. Only synthetic mock views are enabled."
        ),
        "source.link": "Source code (AGPL-3.0)",
        "source.pending": (
            "The Source link is not configured. Public access must remain disabled until the "
            "public repository is set."
        ),
        "main.intro": (
            "See how the agent starts from a GPS event and decides whether "
            "visual evidence is needed."
        ),
        "demo.scenario": "Demo scenario",
        "scenario.accepted": "Accepted with visual evidence",
        "scenario.rejected": "Rejected after visual review",
        "scenario.missing_asset": "Matching media is unavailable",
        "scenario.gemini_unavailable": "Gemini video analysis is unavailable",
        "demo.run": "Run decision demo",
        "demo.story_plan": "View Story Plan",
        "demo.candidate_plan": "View candidate clip plan",
        "demo.download": "Save decision record",
        "demo.synthetic_notice": "Uses synthetic GPS events and mock video analysis only.",
        "demo.gps_event": "GPS event",
        "demo.importance": "importance",
        "demo.video_evidence": "Visual evidence",
        "demo.required": "Required",
        "demo.not_required": "Not required",
        "demo.final_status": "Final status",
        "demo.reason": "Reason",
        "demo.agent_flow": "Agent flow",
        "demo.step.1": "Receive a GPS event",
        "demo.step.2": "Story Agent decides whether visual evidence is required",
        "demo.step.3": "Search for matching media",
        "demo.step.4": "Analyze video or fail safely to human review",
        "demo.step.5": "Story Agent makes the final decision",
        "demo.reason.accepted": "Video analysis supports the GPS event's story relevance.",
        "demo.reason.rejected": "Video analysis did not sufficiently support story relevance.",
        "demo.reason.missing_asset": "Matching media is missing, so human review is required.",
        "demo.reason.gemini_unavailable": (
            "Video analysis is unavailable, so human review is required."
        ),
        "story.heading": "Draft Story Plan",
        "story.notice": "A draft plan created from synthetic GPS events only.",
        "story.synthetic_title": "Synthetic route story draft",
        "candidate.heading": "Candidate clip plan",
        "candidate.notice": "A pre-review clip proposal, not a final edit instruction.",
        "candidate.target_duration": "Target / candidate duration",
        "candidate.coverage": "Coverage",
        "candidate.status": "Status",
        "candidate.edit_ready": "Ready for editing",
        "candidate.ready": "Ready for human review",
        "candidate.not_ready": "Not ready",
        "candidate.review_reasons": "Reasons requiring review",
        "candidate.clips": "Candidate clips",
        "candidate.reason.duration": (
            "There is not enough candidate footage for the target duration."
        ),
        "candidate.reason.awaiting": "Candidate clips still require visual evidence.",
        "candidate.reason.rejected": "Rejected visual evidence must be replaced.",
        "ibm.heading": "Built with IBM Bob review",
        "ibm.description": (
            "IBM Bob reviewed the code architecture and agent flow during development, "
            "then identified priority gaps."
        ),
        "ibm.finding.1": "Added Google ADK agent and tool wiring",
        "ibm.finding.2": "Added attributed evidence confirmation, rejection, and safe blocking",
        "ibm.finding.3": "Added a Gemini video boundary and missing edge-case tests",
        "ibm.limit": (
            "This is development-process evidence; it does not claim real-media analysis or "
            "public-submission completion."
        ),
        "adk.heading": "Google ADK synthetic demo",
        "adk.description": (
            "Sends only a fixed synthetic event to Google ADK / Gemini and verifies tool use. "
            "No GPX, video, coordinates, or user text is sent."
        ),
        "adk.run": "Run ADK synthetic demo",
        "platform.heading": "Agent Platform cloud synthetic demo",
        "platform.description": (
            "Sends only a fixed synthetic event to the existing Tokyo runtime. No GPX, video, "
            "coordinates, or user text is sent. This makes an external request and may incur "
            "Google Cloud charges."
        ),
        "platform.run": "Run cloud Runtime test",
        "platform.preflight": "Check configuration",
        "platform.runtime": "Runtime",
        "platform.model": "Model",
        "platform.tool": "Fixed tool call",
        "platform.response": "Final response received",
        "platform.private_data": "Private data",
        "platform.used": "Used",
        "platform.not_used": "Not used",
        "platform.external_notice": "This action calls Google Cloud.",
        "platform.preflight_heading": "Agent Platform deployment readiness",
        "platform.deployment": "Deployment",
        "platform.executed": "Executed",
        "platform.not_executed": "Not executed",
        "platform.framework": "Agent framework",
        "platform.missing": "Missing local configuration",
        "platform.none": "None (external verification and approval are still required)",
        "platform.external_checks": "External checks before deployment",
        "inventory.heading": "Local video inventory",
        "inventory.main_description": (
            "Create a private JSON inventory from file names, relative paths, sizes, and modified "
            "times without opening video content. Uses a dedicated page with no external transfer."
        ),
        "inventory.open": "Open video folder inventory",
        "inventory.description": (
            "Select a GoPro folder and create a private JSON inventory from "
            "filesystem metadata only."
        ),
        "inventory.targets": "Included",
        "inventory.used": "Used: relative path, file name, size, modified time",
        "inventory.not_used": "Not used: video frames, audio, GPS, coordinates, absolute paths",
        "inventory.no_upload": "No external transfer: ",
        "inventory.no_upload_detail": (
            "This page loads no third-party scripts, including Google Maps, and does not send "
            "selected information to the local server."
        ),
        "inventory.build": "Create inventory JSON",
        "inventory.select": "Select a video folder.",
        "inventory.selected": (
            "Selected {count} supported video files. Video content has not been read."
        ),
        "inventory.none_found": "No supported video files were found.",
        "inventory.completed": (
            "Inventory JSON created.\nVideos: {count}\nTotal: {bytes} bytes\n"
            "Video content was not read or transferred."
        ),
        "inventory.failed": "Could not create the inventory JSON. Check the selected folder.",
        "gpx.heading": "Local private GPX verification",
        "gpx.description": (
            "The file is parsed only in this browser and local server memory. It is not saved or "
            "sent externally."
        ),
        "gpx.run": "Verify GPX",
        "gpx.select": "Select a GPX file.",
        "gpx.result": "Local GPX verification result",
        "gpx.distance_duration": "Distance / ride time",
        "gpx.elevation": "Elevation gain / loss",
        "gpx.events": "Events before / after consolidation",
        "gpx.candidate": "Candidate duration / ready for editing",
        "map.heading": "Route map",
        "map.enabled": "Google Maps is available. Select a GPX file to draw its route.",
        "map.disabled": "Set GOOGLE_MAPS_API_KEY in the local `.env` file to display the map.",
        "map.privacy": (
            "Displaying the map sends selected GPX coordinates from the browser to Google Maps. "
            "The GPX file itself is not saved or uploaded."
        ),
        "map.aria": "Map of the selected GPX route",
        "map.waiting": "Waiting for Google Maps, or the API key is not configured.",
        "map.points": "Displaying {count} GPX route points.",
        "error.demo": "Could not run the demo.",
        "error.story": "Could not load the Story Plan.",
        "error.candidate": "Could not load the candidate clip plan.",
        "error.adk": "Could not run the Google ADK synthetic demo.",
        "error.platform": "Could not run the cloud Runtime synthetic test.",
        "error.preflight": "Could not check deployment readiness.",
        "error.gpx": "Could not parse the GPX file.",
    },
}


def _validate_copy() -> None:
    japanese_keys = set(_COPY[UiLanguage.JAPANESE])
    english_keys = set(_COPY[UiLanguage.ENGLISH])
    if japanese_keys != english_keys:
        missing_ja = sorted(english_keys - japanese_keys)
        missing_en = sorted(japanese_keys - english_keys)
        raise RuntimeError(
            f"UI translation keys do not match: missing_ja={missing_ja}, missing_en={missing_en}"
        )
    for language, values in _COPY.items():
        empty = sorted(key for key, value in values.items() if not value.strip())
        if empty:
            raise RuntimeError(f"empty UI translations for {language.value}: {empty}")


_validate_copy()


def configured_default_language() -> UiLanguage:
    """Return a validated local default without exposing environment contents."""
    local_values = load_local_environment()
    raw = os.environ.get(UI_LANGUAGE_ENV, local_values.get(UI_LANGUAGE_ENV, ""))
    return _parse_language(raw) or DEFAULT_UI_LANGUAGE


def resolve_language(requested: str | None) -> UiLanguage:
    """Resolve a query-string language, safely falling back to the local default."""
    return _parse_language(requested) or configured_default_language()


def copy_for(language: UiLanguage) -> Mapping[str, str]:
    """Return read-only copy for one supported language."""
    return MappingProxyType(_COPY[language])


def translation_keys() -> frozenset[str]:
    """Expose the validated key set for tests and documentation checks."""
    return frozenset(_COPY[UiLanguage.JAPANESE])


def _parse_language(raw: str | None) -> UiLanguage | None:
    if not raw:
        return None
    normalized = raw.strip().lower().replace("_", "-").split("-", 1)[0]
    try:
        return UiLanguage(normalized)
    except ValueError:
        return None
