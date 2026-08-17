"""Deterministic Story Agent used until an LLM adapter is verified."""

from enum import StrEnum

from app.contracts import DecisionStatus, GpsEvent, StoryDecision, VideoAnalysis

from .story_planner import StoryOutputLanguage


class StoryEvidenceFailure(StrEnum):
    """Reasons why the evidence loop must stop for human review."""

    MISSING_ASSET = "missing_asset"
    ANALYSIS_UNAVAILABLE = "analysis_unavailable"


class RuleBasedStoryAgent:
    evidence_events = {"scenery_change", "arrival_candidate", "elevation_change"}
    text = {
        StoryOutputLanguage.JAPANESE: {
            "awaiting": "GPS上の変化だけでは物語上の重要性を確定できない。",
            "below_threshold": "このイベントは映像証拠を必要とする重要度に達していない。",
            "accepted": "映像解析がGPSイベントの物語上の重要性を裏付けた。",
            "accepted_role": "旅の転換点として採用する。",
            "rejected": "映像解析では物語上の重要性を十分に裏付けられなかった。",
            StoryEvidenceFailure.MISSING_ASSET.value: (
                "映像証拠が必要だが、対応する素材が見つからない。"
            ),
            StoryEvidenceFailure.ANALYSIS_UNAVAILABLE.value: (
                "映像解析を完了できないため、人手確認が必要。"
            ),
        },
        StoryOutputLanguage.ENGLISH: {
            "awaiting": ("GPS changes alone cannot confirm this event's importance to the story."),
            "below_threshold": (
                "This event does not meet the importance threshold for video evidence."
            ),
            "accepted": ("The video analysis supports this GPS event's importance to the story."),
            "accepted_role": "Use this as a turning point in the journey.",
            "rejected": (
                "The video analysis did not provide enough support for this event's "
                "importance to the story."
            ),
            StoryEvidenceFailure.MISSING_ASSET.value: (
                "Video evidence is required, but no matching media asset was found."
            ),
            StoryEvidenceFailure.ANALYSIS_UNAVAILABLE.value: (
                "Video analysis could not be completed, so human review is required."
            ),
        },
    }

    def __init__(
        self,
        output_language: StoryOutputLanguage = StoryOutputLanguage.JAPANESE,
    ) -> None:
        self.output_language = StoryOutputLanguage(output_language)

    def _text(self, key: str) -> str:
        return self.text[self.output_language][key]

    def decide_from_event(self, event: GpsEvent) -> StoryDecision:
        needs_evidence = event.importance_hint >= 0.60 and event.event_type in self.evidence_events
        if needs_evidence:
            return StoryDecision(
                event_id=event.event_id,
                needs_video_evidence=True,
                reason=self._text("awaiting"),
                asset_name_hint=event.video_query.asset_name_hint,
                decision_status=DecisionStatus.AWAITING_VIDEO_EVIDENCE,
            )
        return StoryDecision(
            event_id=event.event_id,
            needs_video_evidence=False,
            reason=self._text("below_threshold"),
            asset_name_hint=None,
            decision_status=DecisionStatus.REJECTED,
        )

    def update_with_video(self, decision: StoryDecision, analysis: VideoAnalysis) -> StoryDecision:
        if analysis.story_relevance_score >= 0.60:
            return StoryDecision(
                event_id=decision.event_id,
                needs_video_evidence=True,
                reason=self._text("accepted"),
                asset_name_hint=decision.asset_name_hint,
                decision_status=DecisionStatus.ACCEPTED,
                updated_story_role=self._text("accepted_role"),
            )
        return StoryDecision(
            event_id=decision.event_id,
            needs_video_evidence=True,
            reason=self._text("rejected"),
            asset_name_hint=decision.asset_name_hint,
            decision_status=DecisionStatus.REJECTED,
        )

    def needs_human_review(
        self,
        event: GpsEvent,
        failure: StoryEvidenceFailure,
    ) -> StoryDecision:
        failure = StoryEvidenceFailure(failure)
        return StoryDecision(
            event_id=event.event_id,
            needs_video_evidence=True,
            reason=self._text(failure.value),
            asset_name_hint=event.video_query.asset_name_hint,
            decision_status=DecisionStatus.NEEDS_HUMAN_REVIEW,
        )
