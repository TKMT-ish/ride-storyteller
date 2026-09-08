"""What kind of place a stop was, from the model's answers and its words.

The owner's rule (2026-09-07): a fuel stop or a toilet stop is a short
break; lunch and sightseeing are stopovers, and matter more. The track
says how long the ride stood and where; what the place *was* is in the
picture, and the model saw it. Judgements bought from 2026-09-08 answer
`place_kind` and `place_name` outright; the rides judged before that are
read for the words the model used -- "gas station", "museum exhibit",
"viewing platform", "ferry terminal" -- which on the real rides name the
place plainly.

Two more readings live here because they are the same kind of reading:
whether a window is indoors (a museum hall is not a picture of the road),
and whether it shows a private residence -- the owner's correction
(2026-09-07): a car park is fine, a scene that could identify someone's
home is not.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from enum import StrEnum

from app.contracts import VideoAnalysis
from app.contracts.models import PLACE_KIND_VALUES

__all__ = ["PLACE_KIND_VALUES", "StopKind"]
# Lunch is a meal at these local hours.
LUNCH_FROM_H = 11.0
LUNCH_UNTIL_H = 14.5
# A stop this long with nothing to say what it was is a stopover, not a break.
STOPOVER_S = 30 * 60.0


class StopKind(StrEnum):
    REST = "rest"
    STOPOVER = "stopover"
    FUEL = "fuel"
    MEAL = "meal"
    LUNCH = "lunch"
    ATTRACTION = "attraction"
    LOOKOUT = "lookout"
    SHOP = "shop"
    FERRY = "ferry"
    LODGING = "lodging"
    RESIDENCE = "residence"


# The model's `place_kind` answers, and the words it used before it was asked.
_KIND_OF_ANSWER: dict[str, StopKind] = {
    "fuel": StopKind.FUEL,
    "eatery": StopKind.MEAL,
    "lodging": StopKind.LODGING,
    "attraction": StopKind.ATTRACTION,
    "lookout": StopKind.LOOKOUT,
    "shop": StopKind.SHOP,
    "ferry": StopKind.FERRY,
    "residential": StopKind.RESIDENCE,
}
_WORDS: tuple[tuple[StopKind, re.Pattern[str]], ...] = (
    (
        StopKind.FERRY,
        _AT_A_FERRY := re.compile(
            r"\bferry (?:terminal|dock|ramp|queue|building|berth)\b|\bwharf\b"
            r"|\b(?:vehicle|car|passenger|ship'?s?|upper|lower) deck\b"
            r"|\bdeck of (?:a|the) (?:ferry|ship)\b|\bpassenger (?:vessel|ferry)\b"
            r"|\b(?:onto|aboard|board(?:ing|ed)?|inside|interior of) (?:a |the )?(?:large )?ferry\b"
            r"|\b(?:on|from) (?:a|the) ferry\b|\bbow of the (?:ferry|ship)\b|\bferry is docked\b",
            re.IGNORECASE,
        ),
    ),
    (
        StopKind.FUEL,
        re.compile(
            r"\b(?:gas|petrol|fuel|service) stations?\b|\bforecourt\b|\b(?:fuel|petrol) pumps?\b",
            re.IGNORECASE,
        ),
    ),
    (
        StopKind.LODGING,
        re.compile(
            r"\bhotels?\b|\bmotels?\b|\bmotor ?(?:lodge|inn)\b|\blodge\b|\breception\b"
            r"|\baccommodation\b|\bholiday park\b|\bhostel\b|\bbackpackers?\b|\bkitchenette\b"
            r"|\bguest ?house\b|\bb&b\b",
            re.IGNORECASE,
        ),
    ),
    (
        StopKind.ATTRACTION,
        re.compile(
            r"\bmuseums?\b|\bgaller(?:y|ies)\b|\bexhibits?\b|\bexhibitions?\b|\bmemorial\b"
            r"|\bmonument\b|\bvisitor (?:centre|center)\b|\bi-?site\b|\bhistoric (?:site|village)\b"
            r"|\bwaterfalls?\b|\bhot ?springs?\b|\bdisplay cases?\b|\bartifacts?\b|\bexhibit\b",
            re.IGNORECASE,
        ),
    ),
    (
        StopKind.LOOKOUT,
        re.compile(
            r"\blookout\b|\bviewing platform\b|\bviewpoint\b|\bvantage point\b|\bscenic reserve\b"
            r"|\bpanoramic view\b|\bobservation (?:deck|point)\b|\boverlook\b",
            re.IGNORECASE,
        ),
    ),
    (
        StopKind.MEAL,
        re.compile(
            r"\bcaf[eé]s?\b|\brestaurants?\b|\bbaker(?:y|ies)\b|\btakeaways?\b|\bfish and chips\b"
            r"|\bpub\b|\bdiner\b|\beater(?:y|ies)\b|\blunch\b|\bmeal\b|\bmenu\b|\bcoffee\b"
            r"|\bmcdonald'?s\b|\bkfc\b|\bburger\b|\bpizza\b|\bpicnic\b|\bfood court\b",
            re.IGNORECASE,
        ),
    ),
    (
        StopKind.SHOP,
        re.compile(
            r"\bsupermarkets?\b|\bmotorcycle shop\b|\bdealership\b|\bconvenience store\b"
            r"|\bshopping (?:centre|center|mall)\b",
            re.IGNORECASE,
        ),
    ),
)
# Kinds listed first win a tie; a ferry terminal has cafés in it and a
# museum has a shop.
_PRIORITY: tuple[StopKind, ...] = (
    StopKind.FERRY,
    StopKind.FUEL,
    StopKind.ATTRACTION,
    StopKind.LOOKOUT,
    StopKind.MEAL,
    StopKind.LODGING,
    StopKind.SHOP,
    StopKind.RESIDENCE,
)
# A window the model placed indoors: a museum hall, a room, a cafeteria.
_INDOORS = re.compile(
    r"\bindoors?\b|\binterior\b|\binside\b|\bexhibition\b|\bdisplay cases?\b|\bceiling\b"
    r"|\bhallway\b|\bcorridor\b|\bkitchenette\b|\blobby\b|\bcafeteria\b|\blounge area\b"
    r"|\bstaircase\b|\bhotel room\b",
    re.IGNORECASE,
)
# A window that could say whose house this is.
_RESIDENCE = re.compile(
    r"\bdriveway\b|\bcarport\b|\bprivate residence\b|\bresidential property\b"
    r"|\b(?:front|back) ?yard\b|\btownhouse\b|\bapartment (?:building|complex|block)\b"
    r"|\b(?:home|house)'?s? (?:garage|driveway|car ?park)\b|\bgarage\b(?! door)",
    re.IGNORECASE,
)
# Names the model read off signs: quoted, or introduced as a sign for something.
_QUOTED = re.compile(r"[\'‘’\"“”]([^\'‘’\"“”]{3,40})[\'‘’\"“”]")
_SIGN_FOR = re.compile(
    r"\bsign(?:s|age)?\s+(?:for|reading|that reads|saying|says|indicating)\s+(?:the\s+)?"
    r"((?:[A-Z][\w'’&-]*)(?:\s+(?:of|the|and|&|de|[A-Z][\w'’&-]*))*)"
)
_NOT_A_NAME = re.compile(
    r"^(?:stop|give way|slow|one way|no exit|exit|entry|open|closed|keep left|keep right"
    r"|pay here|welcome|caution|danger|bus stop|no parking|parking|toilets?|wc|\d+)$",
    re.IGNORECASE,
)
_CODE = re.compile(r"^[A-Z0-9 .-]{1,8}$")
# A road is not the name of a place to stop at.
_ROAD_NAME = re.compile(
    r"\b(?:road|route|highway|street|avenue|drive|lane|way|parade|terrace|crescent)$",
    re.IGNORECASE,
)


def place_kind_of(analysis: VideoAnalysis) -> StopKind | None:
    """What the model said the place was, or what its words say; None when neither says."""
    answer = getattr(analysis, "place_kind", "unknown")
    if answer in _KIND_OF_ANSWER:
        return _KIND_OF_ANSWER[answer]
    if answer in ("none", "other"):
        return None
    text = f"{analysis.road_type} {analysis.visual_description} {' '.join(analysis.scenery_tags)}"
    for kind, pattern in _WORDS:
        if pattern.search(text):
            return kind
    return None


def stop_kind(
    analyses: Sequence[VideoAnalysis],
    *,
    duration_s: float,
    local_hour: float | None = None,
) -> StopKind:
    """What a stop was, from every window the camera saw inside it.

    The kinds the windows vote for decide, the most frequent first and the
    priority order on a tie; a meal in the lunch hours is lunch. Windows
    that say nothing leave a long stop a stopover and a short one a rest.
    """
    if duration_s < 0:
        raise ValueError("a stop's duration cannot be negative")
    votes: Counter[StopKind] = Counter()
    for analysis in analyses:
        kind = place_kind_of(analysis)
        if kind is not None:
            votes[kind] += 1
    if votes:
        best = max(votes.values())
        kind = min(
            (k for k, v in votes.items() if v == best),
            key=lambda k: _PRIORITY.index(k) if k in _PRIORITY else len(_PRIORITY),
        )
        if kind is StopKind.MEAL and local_hour is not None:
            if LUNCH_FROM_H <= local_hour < LUNCH_UNTIL_H:
                return StopKind.LUNCH
        return kind
    return StopKind.STOPOVER if duration_s >= STOPOVER_S else StopKind.REST


# Being carried by the ferry, rather than standing at its terminal.
_ABOARD = re.compile(
    r"\b(?:vehicle|car|passenger|ship'?s?|upper|lower) deck\b"
    r"|\bdeck of (?:a|the) (?:ferry|ship)\b|\bpassenger vessel\b"
    r"|\b(?:onto|aboard|inside|interior of) (?:a |the )?(?:large )?ferry\b"
    r"|\b(?:on|from) (?:a|the) ferry\b|\bbow of the (?:ferry|ship)\b",
    re.IGNORECASE,
)


# The act itself: the bike riding up the ramp and onto the ship.
_BOARDING = re.compile(
    r"\b(?:riding|rides|driving|drives|moving|rolls?|rolling) onto (?:a |the )?(?:large )?"
    r"(?:ferry|ship|vessel)\b|\bboarding (?:a |the )?(?:ferry|ship|vessel)\b|\bferry ramp\b"
    r"|\bonto the (?:ferry|ship)\b|\bup the ramp\b",
    re.IGNORECASE,
)


def riding_aboard(analysis: VideoAnalysis) -> bool:
    """Whether the picture is the boarding itself, rather than the terminal or the deck."""
    return _BOARDING.search(f"{analysis.road_type} {analysis.visual_description}") is not None


def at_a_ferry(analysis: VideoAnalysis) -> bool:
    """Whether the model saw the ferry itself -- its deck, its terminal, its ramp.

    A road sign pointing at a ferry is not a ferry: the bare word matched
    a highway on day 3 and a town's main street on day 7.
    """
    if getattr(analysis, "place_kind", "unknown") == "ferry":
        return True
    return _AT_A_FERRY.search(f"{analysis.road_type} {analysis.visual_description}") is not None


def aboard_a_ferry(analysis: VideoAnalysis) -> bool:
    """Whether the model saw the ride being carried: a deck, a bow, the vessel's inside."""
    return _ABOARD.search(f"{analysis.road_type} {analysis.visual_description}") is not None


def indoors(analysis: VideoAnalysis) -> bool:
    """Whether the model placed the window inside a building or a vessel."""
    return _INDOORS.search(f"{analysis.road_type} {analysis.visual_description}") is not None


def at_a_private_residence(analysis: VideoAnalysis) -> bool:
    """Whether the window could identify a home: a driveway, a garage, a house's car park."""
    if getattr(analysis, "place_kind", "unknown") == "residential":
        return True
    return _RESIDENCE.search(f"{analysis.road_type} {analysis.visual_description}") is not None


def sign_names(description: str) -> tuple[str, ...]:
    """The names the model read off signs in this window, in the order it gave them."""
    found: list[str] = []
    for match in _SIGN_FOR.finditer(description):
        _keep(found, match.group(1))
    for match in _QUOTED.finditer(description):
        _keep(found, match.group(1))
    return tuple(found)


def _keep(found: list[str], text: str) -> None:
    """Add a sign's text to the names found, if it reads like a name at all.

    The model's descriptions carry quoted fragments that are not names --
    "s a large blue sign for" came out of one on the real rides -- so a
    name must begin like one, stay short, and not be a road.
    """
    name = " ".join(text.split()).strip(" .,;:")
    if not name or _NOT_A_NAME.match(name) or _CODE.match(name) or _ROAD_NAME.search(name):
        return
    words = name.split()
    if not (name[0].isupper() or name[0].isdigit()) or len(words) > 5:
        return
    if len(words) == 1 and (name.isupper() or not any(ch.isalpha() for ch in name)):
        return
    if name.isupper() and len(words) > 2:
        # Shouted signs on the real rides were shop windows, not place names.
        return
    if sum(ch.isdigit() for ch in name) > 2:
        return
    if name not in found:
        found.append(name)


def place_name_of(analysis: VideoAnalysis) -> str | None:
    """The place's name as the model gave it, or the first name it read off a sign."""
    answer = getattr(analysis, "place_name", None)
    if isinstance(answer, str) and answer.strip() and answer.strip().lower() != "unknown":
        return answer.strip()
    names = sign_names(analysis.visual_description)
    return names[0] if names else None


def spot_name(analyses: Sequence[VideoAnalysis]) -> str | None:
    """The name most of a stop's windows agree on, or the longest among equals."""
    votes: Counter[str] = Counter()
    for analysis in analyses:
        name = place_name_of(analysis)
        if name:
            votes[name] += 1
    if not votes:
        return None
    best = max(votes.values())
    return max((n for n, v in votes.items() if v == best), key=len)
