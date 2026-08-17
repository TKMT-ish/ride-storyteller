"""The minimal agentic loop, deliberately driven by the Story Agent's decision."""

from app.contracts import GpsEvent, StoryDecision
from app.mcp import MediaSearchTool
from app.video import GeminiVideoAnalysisError, VideoAnalyzer

from .story_agent import RuleBasedStoryAgent, StoryEvidenceFailure


class PrototypeOrchestrator:
    def __init__(
        self,
        story_agent: RuleBasedStoryAgent,
        media_search: MediaSearchTool,
        video_analyzer: VideoAnalyzer,
    ) -> None:
        self.story_agent = story_agent
        self.media_search = media_search
        self.video_analyzer = video_analyzer

    def run(self, event: GpsEvent) -> StoryDecision:
        decision = self.story_agent.decide_from_event(event)
        if not decision.needs_video_evidence:
            return decision

        asset = self.media_search.find_asset(name_hint=event.video_query.asset_name_hint)
        if asset is None:
            return self.story_agent.needs_human_review(
                event,
                StoryEvidenceFailure.MISSING_ASSET,
            )

        try:
            analysis = self.video_analyzer.analyze(
                asset,
                start_s=event.video_query.clip_start_offset_s,
                end_s=event.video_query.clip_end_offset_s,
            )
        except GeminiVideoAnalysisError:
            return self.story_agent.needs_human_review(
                event,
                StoryEvidenceFailure.ANALYSIS_UNAVAILABLE,
            )
        return self.story_agent.update_with_video(decision, analysis)
