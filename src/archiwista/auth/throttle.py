"""The wait after failed sign-ins (ADR-046 decision 6, OWASP ASVS 6.3.1).

``LoginThrottle`` counts failures in memory under two keys of every attempt:
``account:<name>`` (the account name as signed in with, trimmed and
lower-cased) and ``address:<client>`` (the client address), so guessing is
slowed for one account from many addresses and from one address across many
accounts. From its ``FREE_FAILURES``-th failure on, each failure makes a key
wait ``2 ** (failures - FREE_FAILURES)`` seconds, at most ``MAX_WAIT``: after
five failures one second, then two, four and so on.

An attempt is admitted (``admit``) before its password is verified, under
the lock of the counts, and stays under way until it ends. It is refused
(``LoginWaitError``), counting nothing, while one of its keys waits, and
while the attempts of a key under way would start a wait if they all failed
(for one second, about the time a verification takes): attempts sent at
once pass no more than the free failures before the first wait, and one at
a time after a wait. The admitted ``LoginAttempt`` ends as it ended:
``failed`` counts a failure under both keys, ``succeeded`` forgets both
keys, and an attempt left otherwise (a refused new password, an error)
counts nothing. A key without a failure for ``FORGET_AFTER`` is forgotten.
A server restart forgets every key, as it ends every session.
"""

import math
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Literal, Self

FREE_FAILURES = 5
MAX_WAIT = timedelta(minutes=15)
FORGET_AFTER = timedelta(days=1)
# 2 ** 10 seconds is over MAX_WAIT: no longer wait needs computing.
_MAX_EXPONENT = 10


def _utc_now() -> datetime:
    return datetime.now(UTC)


def throttle_keys(account: str, client: str | None) -> tuple[str, str]:
    """Return the keys of an attempt: its account name and its client address."""
    return f"account:{account}", f"address:{client or '-'}"


class LoginWaitError(Exception):
    """An attempt refused before its password is verified (``LoginThrottle.admit``).

    Parameters
    ----------
    seconds : int
        Whole seconds to wait (``Retry-After``), at least 1.
    """

    def __init__(self, seconds: int) -> None:
        super().__init__(f"wait {seconds} s")
        self.seconds = seconds


@dataclass(slots=True)
class _Failures:
    count: int
    last_at: datetime
    until: datetime | None = None
    under_way: int = 0


class LoginAttempt:
    """An attempt ``LoginThrottle.admit`` let verify its password, until it ends.

    Use it as a context manager: leaving the block without ``failed`` or
    ``succeeded`` ends it counting nothing.
    """

    def __init__(self, throttle: "LoginThrottle", keys: tuple[str, ...]) -> None:
        self._throttle = throttle
        self._keys = keys
        self._open = True

    def __enter__(self) -> Self:
        """Return the attempt."""
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        """End the attempt unless it ended already, counting nothing."""
        self._end(None)

    def failed(self) -> datetime | None:
        """End the attempt as a failure, counted under each key.

        Returns
        -------
        datetime or None
            The end of the wait this failure starts or lengthens (the
            longest of its keys); ``None`` when it starts none.
        """
        return self._end("failed")

    def succeeded(self) -> None:
        """End the attempt as a sign-in: the failures of each key are forgotten."""
        self._end("succeeded")

    def _end(self, outcome: Literal["failed", "succeeded"] | None) -> datetime | None:
        if not self._open:
            return None
        self._open = False
        return self._throttle._end(self._keys, outcome)


class LoginThrottle:
    """Failed sign-ins per key and the waits they impose; thread-safe.

    Parameters
    ----------
    clock : Callable[[], datetime], optional
        Source of the current time (aware).
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._keys: dict[str, _Failures] = {}
        self._lock = threading.Lock()

    def admit(self, keys: Iterable[str]) -> LoginAttempt:
        """Let an attempt with ``keys`` verify its password, or refuse it.

        Raises
        ------
        LoginWaitError
            One of the keys waits (the seconds left of the longest wait), or
            its attempts under way would start a wait if they all failed (1
            second).
        """
        wanted = tuple(keys)
        now = self._clock()
        with self._lock:
            self._forget(now)
            found = [self._keys.get(key) for key in wanted]
            ends = [
                failures.until
                for failures in found
                if failures is not None
                and failures.until is not None
                and failures.until > now
            ]
            if ends:
                waited = math.ceil((max(ends) - now).total_seconds())
                raise LoginWaitError(max(1, waited))
            if any(
                failures is not None
                and failures.under_way > 0
                and failures.count + failures.under_way >= FREE_FAILURES
                for failures in found
            ):
                raise LoginWaitError(1)
            for key in wanted:
                failures = self._keys.get(key)
                if failures is None:
                    failures = self._keys[key] = _Failures(0, now)
                failures.under_way += 1
        return LoginAttempt(self, wanted)

    def _end(
        self, keys: tuple[str, ...], outcome: Literal["failed", "succeeded"] | None
    ) -> datetime | None:
        """End an admitted attempt under each of its keys (``LoginAttempt``)."""
        now = self._clock()
        longest: datetime | None = None
        with self._lock:
            for key in keys:
                failures = self._keys.setdefault(key, _Failures(0, now, under_way=1))
                failures.under_way -= 1
                if outcome == "succeeded":
                    failures.count, failures.until = 0, None
                elif outcome == "failed":
                    failures.count += 1
                    failures.last_at = now
                    if failures.count >= FREE_FAILURES:
                        exponent = min(failures.count - FREE_FAILURES, _MAX_EXPONENT)
                        wait = min(timedelta(seconds=2**exponent), MAX_WAIT)
                        failures.until = now + wait
                        if longest is None or failures.until > longest:
                            longest = failures.until
                if failures.count == 0 and failures.under_way == 0:
                    del self._keys[key]
        return longest

    def _forget(self, now: datetime) -> None:
        idle = [
            key
            for key, failures in self._keys.items()
            if failures.under_way == 0 and now - failures.last_at >= FORGET_AFTER
        ]
        for key in idle:
            del self._keys[key]
