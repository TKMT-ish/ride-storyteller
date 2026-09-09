"""The fixed facts a viewer is told before approving a judgement.

Every value here must come from the same constants the modules that
actually send and retain data use, and none of it may depend on a
particular ride: the same dict is what every package sees.
"""

from __future__ import annotations

from app.analysis_proxy import DEFAULT_PROXY_FPS, DEFAULT_PROXY_HEIGHT
from app.analysis_record import BOUGHT_ANALYSIS_PROVIDERS
from app.data_handling_disclosure import (
    DATA_HANDLING_DISCLOSURE_SCHEMA_VERSION,
    data_handling_disclosure,
)
from app.footage_candidates import DEFAULT_WINDOW_S
from app.retention import DEFAULT_RETENTION_DAYS, MAX_RETENTION_DAYS


def test_it_matches_the_constants_the_sending_and_retention_modules_use() -> None:
    disclosure = data_handling_disclosure()

    assert disclosure["schema_version"] == DATA_HANDLING_DISCLOSURE_SCHEMA_VERSION
    sent = disclosure["sent_per_window"]
    assert sent["fps"] == DEFAULT_PROXY_FPS
    assert sent["height_px"] == DEFAULT_PROXY_HEIGHT
    assert sent["seconds"] == DEFAULT_WINDOW_S
    assert sent["has_audio"] is False
    assert disclosure["recipients"] == sorted(BOUGHT_ANALYSIS_PROVIDERS)
    retention = disclosure["retention"]
    assert retention["default_days"] == DEFAULT_RETENTION_DAYS
    assert retention["maximum_days"] == MAX_RETENTION_DAYS


def test_nothing_is_sent_by_planning_or_reading() -> None:
    disclosure = data_handling_disclosure()

    assert disclosure["sent_only_if_judging_is_approved"] is True


def test_deletion_exists_but_is_not_yet_a_console_button() -> None:
    disclosure = data_handling_disclosure()

    retention = disclosure["retention"]
    assert retention["deletion_available"] is True
    assert retention["deletion_self_service"] is False


def test_the_never_sent_list_names_what_a_ride_would_otherwise_leak() -> None:
    disclosure = data_handling_disclosure()

    never_sent = disclosure["never_sent"]
    assert "the original recording" in never_sent
    assert any("file name" in item or "path" in item for item in never_sent)
    assert any("GPS" in item for item in never_sent)


def test_it_is_identical_across_calls_because_no_ride_or_package_is_read() -> None:
    assert data_handling_disclosure() == data_handling_disclosure()


def test_it_takes_no_arguments_naming_a_ride_or_package() -> None:
    import inspect

    signature = inspect.signature(data_handling_disclosure)
    assert not signature.parameters
