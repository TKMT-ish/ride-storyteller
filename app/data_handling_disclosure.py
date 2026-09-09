"""What a viewer is told before anything leaves the device.

Gate 7.6 named two things as still missing: a consent-style disclosure and
the ability to delete. `app.retention` closed the second half; this closes
the first. `docs/cloud-architecture-ja.md` §5 puts it plainly: a walking
tour films strangers who agreed to nothing, and the only honest way to spend
their footage is to say, before the money is spent, what leaves the device,
who receives it, and for how long it is kept.

This module answers those questions with the same constants the modules
that actually send and retain data already use (`app.analysis_proxy`,
`app.footage_candidates`, `app.analysis_record`, `app.retention`), so the
disclosure cannot silently drift from what the pipeline does. It reads no
package and no ride: every value here is the same for every viewer, every
day, because what the product sends and keeps does not depend on whose ride
it is. A ride's own facts -- whether *this* package has been judged yet --
are the console's other stages' business (`app.web.private_journey_console`),
each already behind its own gate.

Nothing here asks for a choice. The product's rule stands: showing what
would happen is allowed, asking the viewer to decide anything beyond the
existing spending approval is not.
"""

from __future__ import annotations

from app.analysis_proxy import DEFAULT_PROXY_FPS, DEFAULT_PROXY_HEIGHT
from app.analysis_record import BOUGHT_ANALYSIS_PROVIDERS
from app.footage_candidates import DEFAULT_WINDOW_S
from app.retention import DEFAULT_RETENTION_DAYS, MAX_RETENTION_DAYS

DATA_HANDLING_DISCLOSURE_SCHEMA_VERSION = "data-handling-disclosure-v1"


def data_handling_disclosure() -> dict[str, object]:
    """The fixed facts: what is sent, to whom, and for how long it is kept.

    Returns the same dict regardless of package, ride, or how far a package
    has progressed -- this describes the product's own rule, not one ride's
    history against it.
    """
    return {
        "schema_version": DATA_HANDLING_DISCLOSURE_SCHEMA_VERSION,
        # Nothing is sent by making or reading a plan; only approving and
        # buying a judgement uploads anything (app.web.private_journey_console).
        "sent_only_if_judging_is_approved": True,
        "sent_per_window": {
            "what": "a short, silent, low-resolution copy of the candidate window",
            "fps": DEFAULT_PROXY_FPS,
            "height_px": DEFAULT_PROXY_HEIGHT,
            "seconds": DEFAULT_WINDOW_S,
            "has_audio": False,
        },
        "never_sent": (
            "the original recording",
            "file names or file paths",
            "GPS coordinates or place names as text",
        ),
        # Who receives the copies once judging is approved. Nobody else.
        "recipients": sorted(BOUGHT_ANALYSIS_PROVIDERS),
        "retention": {
            "default_days": DEFAULT_RETENTION_DAYS,
            "maximum_days": MAX_RETENTION_DAYS,
            "deletion_available": True,
            # Deletion exists (app.retention) but runs from the operator's
            # own tooling, not a button in this console yet.
            "deletion_self_service": False,
        },
    }
