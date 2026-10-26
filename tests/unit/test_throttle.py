"""The wait after failed sign-ins: per account, per address, doubling, forgotten."""

from datetime import UTC, datetime, timedelta

from archiwista.auth.throttle import (
    FORGET_AFTER,
    FREE_FAILURES,
    MAX_WAIT,
    LoginThrottle,
    throttle_keys,
)

START = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
ANNA_HERE = throttle_keys("anna", "10.0.0.5")


class Clock:
    """Settable time source."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        """Return the current test time."""
        return self.now


def fail_after_each_wait(
    throttle: LoginThrottle, clock: Clock, times: int
) -> list[int]:
    """Fail ``times`` times, each once the wait before it is over; return the waits."""
    waits = []
    for _ in range(times):
        clock.now += timedelta(seconds=throttle.wait(ANNA_HERE) or 0)
        throttle.failed(ANNA_HERE)
        waits.append(throttle.wait(ANNA_HERE) or 0)
    return waits


def test_five_failures_start_a_wait_that_doubles_up_to_fifteen_minutes() -> None:
    """Four failures cost nothing; from the fifth on 1 s, 2 s, 4 s ... up to 15 min."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)

    waits = fail_after_each_wait(throttle, clock, FREE_FAILURES + 12)

    assert waits[: FREE_FAILURES - 1] == [0] * (FREE_FAILURES - 1)
    doubling = [2**step for step in range(10)]
    assert waits[FREE_FAILURES - 1 : FREE_FAILURES + 9] == doubling
    assert waits[FREE_FAILURES + 9 :] == [int(MAX_WAIT.total_seconds())] * 3


def test_the_wait_counts_down_and_ends() -> None:
    """Retry-After is the whole seconds left, never 0 while the wait lasts."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    fail_after_each_wait(throttle, clock, FREE_FAILURES + 2)  # a wait of 4 s

    clock.now += timedelta(seconds=2.5)
    left = throttle.wait(ANNA_HERE)
    clock.now += timedelta(seconds=1.5)
    over = throttle.wait(ANNA_HERE)

    assert (left, over) == (2, None)


def test_the_failure_that_starts_a_wait_names_its_end() -> None:
    """``failed`` answers the end of the wait it starts, else nothing."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)

    ends = [throttle.failed(ANNA_HERE) for _ in range(FREE_FAILURES)]

    assert ends == [None] * (FREE_FAILURES - 1) + [START + timedelta(seconds=1)]


def test_an_account_waits_from_any_address_and_an_address_for_any_account() -> None:
    """The two keys count apart: either one waiting stops an attempt."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    for _ in range(FREE_FAILURES):
        throttle.failed(ANNA_HERE)

    elsewhere = throttle.wait(throttle_keys("anna", "10.0.0.9"))
    other_account = throttle.wait(throttle_keys("kasia", "10.0.0.5"))
    unrelated = throttle.wait(throttle_keys("kasia", "10.0.0.9"))

    assert (elsewhere, other_account, unrelated) == (1, 1, None)


def test_a_success_forgets_both_keys() -> None:
    """After signing in, the account and the address start from no failure."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    for _ in range(FREE_FAILURES - 1):
        throttle.failed(ANNA_HERE)

    throttle.succeeded(ANNA_HERE)
    ends = [throttle.failed(ANNA_HERE) for _ in range(FREE_FAILURES - 1)]

    assert ends == [None] * (FREE_FAILURES - 1)
    assert throttle.wait(ANNA_HERE) is None


def test_a_key_idle_for_a_day_is_forgotten() -> None:
    """Failures a day old no longer count toward a wait."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    for _ in range(FREE_FAILURES - 1):
        throttle.failed(ANNA_HERE)

    clock.now += FORGET_AFTER
    after_a_day = throttle.failed(ANNA_HERE)

    assert after_a_day is None
    assert throttle.wait(ANNA_HERE) is None
