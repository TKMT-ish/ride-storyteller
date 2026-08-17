from typing import TYPE_CHECKING, Any

from .orchestrator import PrototypeOrchestrator
from .story_agent import RuleBasedStoryAgent, StoryEvidenceFailure
from .story_copy import (
    GeminiStoryCopyError,
    GeminiStoryCopyGenerator,
    StoryChapterCopy,
    StoryCopy,
)
from .story_planner import RuleBasedStoryPlanner, StoryOutputLanguage

if TYPE_CHECKING:
    from .vertex_story_copy import VertexAIGeminiStoryCopyTransport


def __getattr__(name: str) -> Any:
    """Load the optional Google transport only when explicitly requested."""
    if name == "VertexAIGeminiStoryCopyTransport":
        from .vertex_story_copy import VertexAIGeminiStoryCopyTransport

        return VertexAIGeminiStoryCopyTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "GeminiStoryCopyError",
    "GeminiStoryCopyGenerator",
    "PrototypeOrchestrator",
    "RuleBasedStoryAgent",
    "RuleBasedStoryPlanner",
    "StoryChapterCopy",
    "StoryCopy",
    "StoryEvidenceFailure",
    "StoryOutputLanguage",
    "VertexAIGeminiStoryCopyTransport",
]
