"""Show one private ride's progress from input to finished film.

Gate 4 of docs/completion-roadmap-ja.md. Everything the pipeline knows is
already written into the package as JSON, but reading it means opening files
in a terminal. This turns the same facts into one page a local user can look
at: what was checked, what the film will be, what has been made, and what to
do next.

It reads and never writes. Rendering is slow, costly and irreversible enough
that starting it belongs to a deliberate command, not to loading a page.

The browser gets aggregates and the words that are already on screen in the
film. It never gets an event ID, asset ID, source file name, path, coordinate
or capture time -- the same boundary every other private view in this project
holds. Chapter titles and bodies are the exception that proves it: they are
safe precisely because they were built from what the GPS track proves and are
shown to any viewer of the film anyway.

The next step is named, not spelled out. A command line would have to carry
the package's path, and the path is exactly what must not reach a browser.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.config import load_local_environment
from app.private_package_health import (
    PrivatePackageHealthError,
    check_private_package_health,
)
from app.story_package import (
    JOURNEY_STORY_PLAN_FILE_NAME,
    JourneyStoryPlanError,
    load_journey_story_plan,
)
from app.story_timeline import StoryBeatKind

PRIVATE_JOURNEY_STATUS_SCHEMA_VERSION = "private-journey-status-v1"

PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV = "RIDE_PRIVATE_JOURNEY_PACKAGE_DIRECTORY"

_FILM_FILE_NAME = "ride-storyteller-story-film.mp4"
_SCORED_FILM_FILE_NAME = "ride-storyteller-story-film-scored.mp4"
_SUBTITLE_FILE_NAMES = (
    "ride-storyteller-story-film.srt",
    "ride-storyteller-story-film.vtt",
)

# Fixed, non-identifying vocabulary. The page turns these into instructions;
# the payload never carries a path for one to be built from.
STAGE_INPUTS = "inputs_checked"
STAGE_PLAN = "story_planned"
STAGE_FILM = "film_cut"
STAGE_MUSIC = "film_scored"

STATE_DONE = "done"
STATE_BLOCKED = "blocked"
STATE_PENDING = "pending"

ACTION_FIX_INPUTS = "resolve_blocking_reasons"
ACTION_MAKE_FILM = "make_the_film"
ACTION_SCORE_FILM = "choose_music"
ACTION_NOTHING_LEFT = "watch_the_film"


class PrivateJourneyStatusError(RuntimeError):
    """Raised when the configured package cannot be shown safely."""


@dataclass(frozen=True)
class PrivateJourneyStatus:
    """A read-only view of one private package, safe to put in a browser."""

    package_directory: Path

    @classmethod
    def from_environment(cls) -> "PrivateJourneyStatus":
        local_values = load_local_environment()
        raw_path = os.environ.get(
            PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV,
            local_values.get(PRIVATE_JOURNEY_PACKAGE_DIRECTORY_ENV, ""),
        ).strip()
        if not raw_path:
            raise PrivateJourneyStatusError("private journey package is not configured")
        return cls.from_directory(Path(raw_path).expanduser())

    @classmethod
    def from_directory(cls, package_directory: Path) -> "PrivateJourneyStatus":
        if package_directory.is_symlink() or not package_directory.is_dir():
            raise PrivateJourneyStatusError("private journey package is unavailable")
        return cls(package_directory=package_directory.resolve())

    def payload(self) -> dict[str, object]:
        """Every stage of this ride, with only browser-safe facts in it."""
        stages = [self._inputs_stage()]
        plan_stage, plan = self._plan_stage(blocked=stages[0]["state"] == STATE_BLOCKED)
        stages.append(plan_stage)
        stages.append(self._film_stage(plan_ready=plan is not None))
        stages.append(self._music_stage())
        return {
            "schema_version": PRIVATE_JOURNEY_STATUS_SCHEMA_VERSION,
            "local_only": True,
            "external_data_sent": False,
            "stages": stages,
            "chapters": self._chapters(plan),
            "next_action": _next_action(stages),
        }

    def _inputs_stage(self) -> dict[str, object]:
        try:
            health = check_private_package_health(self.package_directory)
        except JourneyStoryPlanError as error:
            # The health check measures the film against the written plan, so
            # a plan it cannot trust surfaces here first. Say that, because
            # a corrupt plan is deleted and rebuilt while a broken package is
            # not, and the two are otherwise indistinguishable to a reader.
            raise PrivateJourneyStatusError("the story plan cannot be trusted") from error
        except (PrivatePackageHealthError, ValueError) as error:
            # A missing export raises the health check's own error; an invalid
            # inputs manifest raises a plain ValueError. Either way the page
            # says the package cannot be read rather than showing a traceback.
            raise PrivateJourneyStatusError("private journey package cannot be read") from error
        summary = health.to_dict()
        return {
            "key": STAGE_INPUTS,
            "state": STATE_DONE if health.is_ready else STATE_BLOCKED,
            "clock_offset_confirmed": health.clock_offset_confirmed,
            "counts": summary["counts"],
            "duration": summary["duration"],
            "blocking_reasons": list(health.blocking_reasons),
        }

    def _plan_stage(self, *, blocked: bool) -> tuple[dict[str, object], object]:
        path = self.package_directory / JOURNEY_STORY_PLAN_FILE_NAME
        if not path.exists():
            return (
                {
                    "key": STAGE_PLAN,
                    "state": STATE_BLOCKED if blocked else STATE_PENDING,
                    "beat_count": 0,
                },
                None,
            )
        try:
            plan = load_journey_story_plan(path)
        except JourneyStoryPlanError as error:
            raise PrivateJourneyStatusError("the story plan cannot be trusted") from error
        return (
            {
                "key": STAGE_PLAN,
                "state": STATE_DONE,
                "beat_count": len(plan.beats),
                "footage_beat_count": len(plan.footage_beats),
                "card_beat_count": len(plan.card_beats),
                "total_screen_duration_s": round(plan.total_screen_duration_s, 3),
                "output_language": plan.output_language.value,
            },
            plan,
        )

    def _film_stage(self, *, plan_ready: bool) -> dict[str, object]:
        film = self.package_directory / _FILM_FILE_NAME
        subtitles = [
            name for name in _SUBTITLE_FILE_NAMES if _is_real_file(self.package_directory / name)
        ]
        if not _is_real_file(film):
            return {
                "key": STAGE_FILM,
                "state": STATE_PENDING if plan_ready else STATE_BLOCKED,
                "subtitle_count": len(subtitles),
            }
        return {
            "key": STAGE_FILM,
            "state": STATE_DONE,
            "megabytes": _megabytes(film),
            "subtitle_count": len(subtitles),
        }

    def _music_stage(self) -> dict[str, object]:
        """Music is a choice, not a step: a silent film is a finished film."""
        scored = self.package_directory / _SCORED_FILM_FILE_NAME
        if _is_real_file(scored):
            return {
                "key": STAGE_MUSIC,
                "state": STATE_DONE,
                "scored": True,
                "megabytes": _megabytes(scored),
            }
        if _is_real_file(self.package_directory / _FILM_FILE_NAME):
            return {"key": STAGE_MUSIC, "state": STATE_DONE, "scored": False}
        return {"key": STAGE_MUSIC, "state": STATE_PENDING}

    def _chapters(self, plan: object) -> list[dict[str, object]]:
        """The words already shown on screen, in the order the film shows them."""
        if plan is None:
            return []
        chapters: list[dict[str, object]] = []
        for beat in plan.beats:  # type: ignore[attr-defined]
            if beat.kind is not StoryBeatKind.GAP_CARD or beat.card is None:
                continue
            chapters.append(
                {
                    "character": beat.card.character.value,
                    "title": beat.card.title,
                    "body": beat.card.body,
                    "screen_duration_s": round(beat.screen_duration_s, 3),
                }
            )
        return chapters


def _next_action(stages: list[dict[str, object]]) -> str:
    by_key = {str(stage["key"]): stage for stage in stages}
    if by_key[STAGE_INPUTS]["state"] == STATE_BLOCKED:
        return ACTION_FIX_INPUTS
    if by_key[STAGE_FILM]["state"] != STATE_DONE:
        return ACTION_MAKE_FILM
    if by_key[STAGE_MUSIC]["state"] != STATE_DONE:
        return ACTION_SCORE_FILM
    return ACTION_NOTHING_LEFT


def _is_real_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _megabytes(path: Path) -> float:
    return round(path.stat().st_size / 1_000_000, 1)


def render_private_journey_status_json(status: PrivateJourneyStatus) -> str:
    return json.dumps(status.payload(), ensure_ascii=False, indent=2)
