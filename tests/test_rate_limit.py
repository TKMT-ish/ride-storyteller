import pytest

from app.web.rate_limit import FixedWindowRateLimiter


def test_fixed_window_rate_limiter_resets_at_the_window_boundary() -> None:
    now = [10.0]
    limiter = FixedWindowRateLimiter(
        max_requests=2,
        window_seconds=5,
        clock=lambda: now[0],
    )

    assert limiter.allow() == (True, 0)
    assert limiter.allow() == (True, 0)
    assert limiter.allow() == (False, 5)

    now[0] = 14.2
    assert limiter.allow() == (False, 1)
    now[0] = 15.0
    assert limiter.allow() == (True, 0)


@pytest.mark.parametrize(
    ("max_requests", "window_seconds"),
    ((0, 60), (1, 0), (1, -1)),
)
def test_fixed_window_rate_limiter_rejects_invalid_limits(
    max_requests: int, window_seconds: float
) -> None:
    with pytest.raises(ValueError):
        FixedWindowRateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
