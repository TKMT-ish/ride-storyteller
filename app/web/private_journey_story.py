"""The film's story as the owner sees it: chapters, windows, and why each is there.

The console's payload is deliberately bare -- counts, sizes, money, fixed
reason codes -- because it is meant to be safe on any screen. This view is
the opposite, on purpose: it is the owner looking at their own film, and
the thing they need in order to judge it is exactly what the console
withholds. Which window opens the film. Which chapter each window sits in.
What the model said about it, how it scored it, where it ranked it. Without
that, "the second minute is monotonous" is a feeling; with it, it is a
list of windows the owner can point at.

So this reads the written plan and the bought judgement and lays the film
out beat by beat, in screen order, with the model's words beside each
window. It is served only from the private console, never in the public
demo, and it still names no file, path, coordinate or capture time: a
window is its screen position and its evidence, not its recording.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.analysis_ranking import AnalysisRankingError, ranks_for
from app.analysis_record import VIDEO_ANALYSIS_RECORD_FILE_NAME, load_video_analysis_record
from app.story_package import (
    JOURNEY_STORY_PLAN_FILE_NAME,
    JourneyStoryPlanError,
    load_journey_story_plan,
)
from app.story_timeline import StoryBeatKind

PRIVATE_JOURNEY_STORY_SCHEMA_VERSION = "private-journey-story-v1"

SCORED_FILM_FILE_NAME = "ride-storyteller-story-film-scored.mp4"
SILENT_FILM_FILE_NAME = "ride-storyteller-story-film.mp4"


class PrivateJourneyStoryError(RuntimeError):
    """Raised when the story cannot be laid out for this package."""


@dataclass(frozen=True)
class StoryView:
    package_directory: Path

    def payload(self) -> dict[str, object]:
        """Every beat in screen order, chapters grouping the windows under them."""
        plan_path = self.package_directory / JOURNEY_STORY_PLAN_FILE_NAME
        if not plan_path.is_file() or plan_path.is_symlink():
            raise PrivateJourneyStoryError("this package has no story plan yet")
        try:
            plan = load_journey_story_plan(plan_path)
        except JourneyStoryPlanError as error:
            raise PrivateJourneyStoryError("the story plan cannot be trusted") from error

        judgements = self._judgements()
        try:
            ranks = ranks_for(self.package_directory) or {}
        except AnalysisRankingError:
            ranks = {}

        chapters: list[dict[str, object]] = []
        cold_open: dict[str, object] | None = None
        at_s = 0.0
        for beat in plan.beats:
            if beat.card is not None:
                # A full-screen card, or the title laid over the window that
                # opens the chapter; either way the chapter starts here.
                chapters.append(
                    {
                        "title": beat.card.title,
                        "body": beat.card.body,
                        "character": beat.card.character.value,
                        "at_s": round(at_s, 1),
                        "screen_duration_s": round(beat.card.screen_duration_s, 1),
                        "over_footage": beat.is_titled_footage,
                        "windows": [],
                    }
                )
            if beat.kind is StoryBeatKind.FOOTAGE:
                window = self._window(beat.event_id, judgements, ranks)
                window["at_s"] = round(at_s, 1)
                window["screen_duration_s"] = round(beat.screen_duration_s, 1)
                if chapters:
                    chapters[-1]["windows"].append(window)  # type: ignore[union-attr]
                elif cold_open is None:
                    # The film opens on a window before any chapter card.
                    cold_open = window
                else:
                    chapters.append(
                        {
                            "title": "",
                            "body": "",
                            "character": "",
                            "at_s": round(at_s, 1),
                            "screen_duration_s": 0.0,
                            "windows": [window],
                        }
                    )
            at_s += beat.screen_duration_s

        return {
            "schema_version": PRIVATE_JOURNEY_STORY_SCHEMA_VERSION,
            "local_only": True,
            "package": self.package_directory.name,
            "external_data_sent": False,
            "total_screen_duration_s": round(plan.total_screen_duration_s, 1),
            "footage_screen_duration_s": round(plan.footage_screen_duration_s, 1),
            "window_count": sum(len(c["windows"]) for c in chapters)  # type: ignore[arg-type]
            + (1 if cold_open else 0),
            "chapter_count": len(chapters),
            "cold_open": cold_open,
            "chapters": chapters,
            "film": self._film(),
        }

    def _judgements(self) -> dict[str, object]:
        path = self.package_directory / VIDEO_ANALYSIS_RECORD_FILE_NAME
        if not path.is_file() or path.is_symlink():
            return {}
        try:
            record = load_video_analysis_record(path)
        except (OSError, ValueError, KeyError, TypeError):
            return {}
        return {item.event_id: item.analysis for item in record.analysed}

    @staticmethod
    def _window(
        event_id: str | None, judgements: dict[str, object], ranks: object
    ) -> dict[str, object]:
        analysis = judgements.get(event_id or "")
        if analysis is None:
            return {"judged": False, "rank": None}
        rank = ranks.get(event_id) if isinstance(ranks, dict) else None  # type: ignore[union-attr]
        return {
            "judged": True,
            "rank": rank,
            "interest": round(float(analysis.visual_interest_score), 2),  # type: ignore[attr-defined]
            "story": round(float(analysis.story_relevance_score), 2),  # type: ignore[attr-defined]
            "road": str(analysis.road_type),  # type: ignore[attr-defined]
            "scenery": list(analysis.scenery_tags),  # type: ignore[attr-defined]
            "description": str(analysis.visual_description),  # type: ignore[attr-defined]
        }

    def _film(self) -> dict[str, object]:
        scored = self.package_directory / SCORED_FILM_FILE_NAME
        silent = self.package_directory / SILENT_FILM_FILE_NAME
        for name, path in (("scored", scored), ("silent", silent)):
            if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                return {
                    "available": True,
                    "variant": name,
                    "megabytes": round(path.stat().st_size / 1_000_000, 1),
                    # The file's name, so the page can say where to find it
                    # for a player -- the package name is already shown; no
                    # absolute path ever enters the payload.
                    "file_name": path.name,
                }
        return {"available": False, "variant": None, "megabytes": 0.0, "file_name": None}

    def film_path(self) -> Path | None:
        """The file the page may stream, or None. Never a symlink."""
        for name in (SCORED_FILM_FILE_NAME, SILENT_FILM_FILE_NAME):
            path = self.package_directory / name
            if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                return path
        return None
