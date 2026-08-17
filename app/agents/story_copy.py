"""Schema-validated, synthetic-only boundary for Gemini story copy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from app.contracts import StoryPlan

from .story_planner import StoryOutputLanguage


class GeminiStoryCopyTransport(Protocol):
    """A concrete Gemini adapter for a sanitized synthetic Story Plan."""

    def generate_story_copy(
        self,
        *,
        prompt: str,
        story_payload: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class GeminiStoryCopyError(RuntimeError):
    """A safe failure that must not reveal provider response content."""


@dataclass(frozen=True)
class StoryChapterCopy:
    chapter_id: str
    title: str
    selection_rationale: str

    def to_dict(self) -> dict[str, str]:
        return {
            "chapter_id": self.chapter_id,
            "title": self.title,
            "selection_rationale": self.selection_rationale,
        }


@dataclass(frozen=True)
class StoryCopy:
    language: StoryOutputLanguage
    title: str
    chapters: tuple[StoryChapterCopy, ...]
    generation_provider: str

    def to_dict(self) -> dict[str, object]:
        return {
            "language": self.language.value,
            "title": self.title,
            "chapters": [chapter.to_dict() for chapter in self.chapters],
            "generation_provider": self.generation_provider,
        }


class GeminiStoryCopyGenerator:
    """Generate prose without allowing the model to alter story structure.

    The current boundary accepts only explicitly labelled synthetic input. It
    sends no coordinates, event IDs, media references, paths, credentials, or
    video-analysis text. Real route-derived input remains a separate approval
    and privacy decision.
    """

    def __init__(self, transport: GeminiStoryCopyTransport) -> None:
        self.transport = transport

    def generate(
        self,
        story_plan: StoryPlan,
        *,
        output_language: StoryOutputLanguage,
        synthetic_input: bool,
    ) -> StoryCopy:
        output_language = StoryOutputLanguage(output_language)
        if synthetic_input is not True:
            raise ValueError("Gemini story copy currently accepts synthetic input only")

        payload = _sanitized_story_payload(story_plan)
        prompt = _story_copy_prompt(output_language)
        try:
            response = self.transport.generate_story_copy(
                prompt=prompt,
                story_payload=payload,
            )
            return _validated_story_copy(story_plan, output_language, response)
        except GeminiStoryCopyError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise GeminiStoryCopyError("Gemini returned invalid structured story copy") from error
        except Exception as error:
            raise GeminiStoryCopyError("Gemini story copy was unavailable") from error


def _sanitized_story_payload(story_plan: StoryPlan) -> dict[str, object]:
    return {
        "source_title": story_plan.title,
        "target_duration_s": story_plan.target_duration_s,
        "chapters": [
            {
                "chapter_id": chapter.chapter_id,
                "narrative_role": chapter.narrative_role,
                "source_title": chapter.title,
                "source_rationale": chapter.selection_rationale,
                "target_duration_s": chapter.target_duration_s,
            }
            for chapter in story_plan.chapters
        ],
    }


def _story_copy_prompt(output_language: StoryOutputLanguage) -> str:
    language_name = "English" if output_language is StoryOutputLanguage.ENGLISH else "Japanese"
    return (
        f"Write concise motorcycle travel-story copy in {language_name}. "
        "Return only the requested JSON structure. Preserve every chapter_id and "
        "chapter order exactly. Create a title, chapter title, and selection rationale "
        "without adding visual facts, locations, weather, people, or events not present "
        "in the supplied synthetic GPS-derived roles."
    )


def _validated_story_copy(
    story_plan: StoryPlan,
    output_language: StoryOutputLanguage,
    response: Mapping[str, object],
) -> StoryCopy:
    if set(response) != {"title", "chapters"}:
        raise ValueError("story copy response has unexpected fields")
    title = _required_text(response, "title")
    chapters_value = response["chapters"]
    if isinstance(chapters_value, (str, bytes)) or not isinstance(chapters_value, (list, tuple)):
        raise TypeError("chapters must be a list")
    if len(chapters_value) != len(story_plan.chapters):
        raise ValueError("story copy chapter count must match the Story Plan")

    chapters: list[StoryChapterCopy] = []
    for source, value in zip(story_plan.chapters, chapters_value, strict=True):
        if not isinstance(value, Mapping):
            raise TypeError("each story copy chapter must be an object")
        if set(value) != {"chapter_id", "title", "selection_rationale"}:
            raise ValueError("story copy chapter has unexpected fields")
        chapter_id = _required_text(value, "chapter_id")
        if chapter_id != source.chapter_id:
            raise ValueError("story copy chapter_id must match the Story Plan")
        chapters.append(
            StoryChapterCopy(
                chapter_id=chapter_id,
                title=_required_text(value, "title"),
                selection_rationale=_required_text(value, "selection_rationale"),
            )
        )
    return StoryCopy(
        language=output_language,
        title=title,
        chapters=tuple(chapters),
        generation_provider="gemini",
    )


def _required_text(response: Mapping[str, object], key: str) -> str:
    value = response[key]
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{key} must be non-empty text")
    return value.strip()
