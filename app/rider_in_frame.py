"""Windows where the rider, not the road, is the picture.

The owner's rule (2026-09-06, point 6): a clip in which the rider fills
the frame -- a face in the mirror, an arm across the picture, someone
standing in front of the camera at a stop -- is out of the film, however
well the model scored the view behind it. A glove at the edge of the
handlebar is not the rider filling the frame.

Judgements bought from 2026-09-06 carry the model's own answer in
``rider_visible`` (none / small / large). The twelve days judged before
that say "unknown", and for those the model's description is read for
the phrases it used when it saw the rider. Ninety of 3,657 windows on the
real rides describe the rider; nearly all are halts, where the mirror or
the rider's arm sits in a stationary shot.
"""

from __future__ import annotations

import re

from app.contracts import VideoAnalysis

RIDER_UNKNOWN = "unknown"
RIDER_NONE = "none"
RIDER_SMALL = "small"
RIDER_LARGE = "large"

# Phrases the model has used, on the real rides, when the rider was in
# the picture. The list is deliberately narrow: "first-person view" and
# "the right-hand side of the road" say nothing about the rider.
_RIDER_PHRASES: tuple[str, ...] = (
    r"rider'?s (?:own )?"
    r"(?:arms?|hands?|gloves?|helmet|reflection|jacket|shoulders?|legs?|body|face)",
    r"(?:person|man|woman)'s (?:arms?|hands?|gloves?)",
    r"reflect\w* (?:of )?(?:the |a )?rider",
    r"rider(?:'s reflection)? (?:is |are )?(?:clearly |partially )?"
    r"(?:visible|reflected|seen|shown)",
    r"(?:person|man|woman|rider) (?:in|wearing) (?:full )?(?:motorcycle|riding|motorbike) gear",
    r"\bhelmet\b",
    r"\bselfie\b",
    r"(?:person|man|woman|rider) (?:standing|walking|sitting|posing) "
    r"(?:near|next to|beside|in front of|by|behind) (?:the |a )?"
    r"(?:motorcycle|motorbike|bike|camera)",
)
_RIDER = re.compile("|".join(f"(?:{phrase})" for phrase in _RIDER_PHRASES), re.IGNORECASE)
# A helmet the camera is mounted on is not a helmet in the picture.
_CAMERA_MOUNT = re.compile(
    r"helmet[- ]?(?:mounted|camera|cam)\b|(?:mounted|camera) on (?:the |a |his |her )?helmet",
    re.IGNORECASE,
)


# A window the model placed in a car park, a forecourt or a driveway: the
# owner's rule (2026-09-06, point 9) keeps these out of the film. The day's
# own departure and arrival are the exception -- a lodging's car park is
# where the day begins and ends -- and the caller names them.
_PARKED = re.compile(
    r"parking (?:lot|area|garage|space|bay)|car ?park|forecourt|driveway|parking-lot",
    re.IGNORECASE,
)


def parked_in_a_car_park(analysis: VideoAnalysis) -> bool:
    """Whether the model placed the window in a car park rather than on a road."""
    return _PARKED.search(f"{analysis.road_type} {analysis.visual_description}") is not None


def describes_the_rider(description: str) -> bool:
    """Whether the model's words say the rider is in the picture."""
    text = _CAMERA_MOUNT.sub(" ", description)
    return _RIDER.search(text) is not None


def rider_fills_the_frame(analysis: VideoAnalysis) -> bool:
    """The model's answer where it gave one; its words where it was not asked."""
    if analysis.rider_visible == RIDER_LARGE:
        return True
    if analysis.rider_visible == RIDER_NONE:
        return False
    # "small" is the model's word; the owner saw the rider large in the
    # mirror on day 1. Where the words describe the rider, the words win.
    return describes_the_rider(analysis.visual_description)
