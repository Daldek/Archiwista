"""The wait after failed sign-ins: per account, per address, doubling, forgotten."""

from datetime import UTC, datetime, timedelta

import pytest

from archiwista.auth.throttle import (
    FORGET_AFTER,
    FREE_FAILURES,
    MAX_WAIT,
    LoginThrottle,
    LoginWaitError,
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


def wait_of(throttle: LoginThrottle, keys: tuple[str, str] = ANNA_HERE) -> int | None:
    """Return the seconds an attempt with ``keys`` must wait; ``None`` if admitted."""
    try:
        with throttle.admit(keys):
            return None
    except LoginWaitError as wait:
        return wait.seconds


def fail(throttle: LoginThrottle, keys: tuple[str, str] = ANNA_HERE) -> datetime | None:
    """Admit an attempt and end it as a failure; return the end of its wait."""
    with throttle.admit(keys) as attempt:
        return attempt.failed()


def fail_after_each_wait(
    throttle: LoginThrottle, clock: Clock, times: int
) -> list[int]:
    """Fail ``times`` times, each once the wait before it is over; return the waits."""
    waits = []
    for _ in range(times):
        clock.now += timedelta(seconds=wait_of(throttle) or 0)
        fail(throttle)
        waits.append(wait_of(throttle) or 0)
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
    left = wait_of(throttle)
    clock.now += timedelta(seconds=1.5)
    over = wait_of(throttle)

    assert (left, over) == (2, None)


def test_the_failure_that_starts_a_wait_names_its_end() -> None:
    """``failed`` answers the end of the wait it starts, else nothing."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)

    ends = [fail(throttle) for _ in range(FREE_FAILURES)]

    assert ends == [None] * (FREE_FAILURES - 1) + [START + timedelta(seconds=1)]


def test_an_account_waits_from_any_address_and_an_address_for_any_account() -> None:
    """The two keys count apart: either one waiting stops an attempt."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    for _ in range(FREE_FAILURES):
        fail(throttle)

    elsewhere = wait_of(throttle, throttle_keys("anna", "10.0.0.9"))
    other_account = wait_of(throttle, throttle_keys("kasia", "10.0.0.5"))
    unrelated = wait_of(throttle, throttle_keys("kasia", "10.0.0.9"))

    assert (elsewhere, other_account, unrelated) == (1, 1, None)


def test_a_success_forgets_both_keys() -> None:
    """After signing in, the account and the address start from no failure."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    for _ in range(FREE_FAILURES - 1):
        fail(throttle)

    with throttle.admit(ANNA_HERE) as attempt:
        attempt.succeeded()
    ends = [fail(throttle) for _ in range(FREE_FAILURES - 1)]

    assert ends == [None] * (FREE_FAILURES - 1)
    assert wait_of(throttle) is None


def test_a_key_idle_for_a_day_is_forgotten() -> None:
    """Failures a day old no longer count toward a wait."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    for _ in range(FREE_FAILURES - 1):
        fail(throttle)

    clock.now += FORGET_AFTER
    after_a_day = fail(throttle)

    assert after_a_day is None
    assert wait_of(throttle) is None


def test_attempts_under_way_pass_no_more_than_the_free_failures() -> None:
    """Attempts at once: the free failures pass, the next waits, as one after another.

    Each admitted attempt counts as a failure that may come; the one that
    could not have started had they all failed already waits a second
    (review of v0.4, D1).
    """
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    attempts = [throttle.admit(ANNA_HERE) for _ in range(FREE_FAILURES)]

    with pytest.raises(LoginWaitError) as during:
        throttle.admit(ANNA_HERE)
    for attempt in attempts:
        attempt.failed()

    assert during.value.seconds == 1
    assert wait_of(throttle) == 1


def test_after_a_wait_one_attempt_at_a_time_goes_ahead() -> None:
    """A wait over admits one attempt; another waits until that one ends."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    fail_after_each_wait(throttle, clock, FREE_FAILURES)  # a wait of 1 s
    clock.now += timedelta(seconds=1)

    with throttle.admit(ANNA_HERE) as first:
        second = wait_of(throttle)
        first.failed()
    clock.now += timedelta(seconds=2)
    third = wait_of(throttle)

    assert (second, third) == (1, None)


def test_an_attempt_ended_otherwise_counts_nothing() -> None:
    """Leaving an attempt without an outcome (a refused new password) costs nothing."""
    clock = Clock()
    throttle = LoginThrottle(clock=clock)
    for _ in range(FREE_FAILURES - 1):
        fail(throttle)

    with pytest.raises(ValueError), throttle.admit(ANNA_HERE):
        raise ValueError("refused before its password was verified")
    fifth = fail(throttle)

    assert fifth == START + timedelta(seconds=1)
