"""The wait after failed sign-ins (ADR-046 decision 8, OWASP ASVS 6.3.1).

``LoginThrottle`` counts failures in memory under two keys of every attempt:
``account:<name>`` (the account name as signed in with, trimmed and
lower-cased) and ``address:<client>`` (the client address), so guessing is
slowed for one account from many addresses and from one address across many
accounts. From its ``FREE_FAILURES``-th failure on, each failure makes a key
wait ``2 ** (failures - FREE_FAILURES)`` seconds, at most ``MAX_WAIT``: after
five failures one second, then two, four and so on. An attempt while one of
its keys waits is refused before any password is verified and counts
nothing. A success forgets both keys; a key without a failure for
``FORGET_AFTER`` is forgotten. A server restart forgets every key, as it
ends every session.
"""

import math
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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


@dataclass(slots=True)
class _Failures:
    count: int
    last_at: datetime
    until: datetime | None = None


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

    def wait(self, keys: Iterable[str]) -> int | None:
        """Return how many whole seconds an attempt with ``keys`` must wait.

        Returns
        -------
        int or None
            At least 1 while one of the keys waits (``Retry-After``); ``None``
            when the attempt may go ahead.
        """
        now = self._clock()
        with self._lock:
            ends = [
                failures.until
                for key in keys
                if (failures := self._keys.get(key)) is not None
                and failures.until is not None
                and failures.until > now
            ]
        if not ends:
            return None
        return max(1, math.ceil((max(ends) - now).total_seconds()))

    def failed(self, keys: Iterable[str]) -> datetime | None:
        """Count a failure under each key.

        Returns
        -------
        datetime or None
            The end of the wait this failure starts or lengthens (the
            longest of its keys); ``None`` when it starts none.
        """
        now = self._clock()
        longest: datetime | None = None
        with self._lock:
            self._forget(now)
            for key in keys:
                failures = self._keys.get(key)
                if failures is None:
                    failures = self._keys[key] = _Failures(0, now)
                failures.count += 1
                failures.last_at = now
                if failures.count < FREE_FAILURES:
                    continue
                exponent = min(failures.count - FREE_FAILURES, _MAX_EXPONENT)
                failures.until = now + min(timedelta(seconds=2**exponent), MAX_WAIT)
                if longest is None or failures.until > longest:
                    longest = failures.until
        return longest

    def succeeded(self, keys: Iterable[str]) -> None:
        """Forget the failures of each key: the attempt signed in."""
        with self._lock:
            for key in keys:
                self._keys.pop(key, None)

    def _forget(self, now: datetime) -> None:
        idle = [
            key
            for key, failures in self._keys.items()
            if now - failures.last_at >= FORGET_AFTER
        ]
        for key in idle:
            del self._keys[key]
