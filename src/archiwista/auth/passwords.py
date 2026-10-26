"""Passwords of accounts: the policy, Argon2id hashes, verification (ADR-046).

A password is normalised to NFKC and has ``MIN_LENGTH`` to ``MAX_LENGTH``
characters of any composition; it may not equal the account's id or name,
nor one of the common passwords of ``common-passwords.txt`` (OWASP ASVS
6.2.4), ignoring case (``policy_problem``). Nothing forces a periodic change.

A password is kept as an Argon2id hash of ``HASHER``, argon2-cffi with its
defaults (RFC 9106's second recommended option: 64 MiB, three passes, four
lanes); at most ``HASH_SLOTS`` hashes or verifications run at once, so that
many sign-ins cannot exhaust the server's memory. ``verify`` verifies one
hash on every path, a stand-in hash when the account has no password, so
that no answer tells by its work whether an account exists (ASVS 6.3.8).
An administrator gives a person a temporary password that the server
generates (``generate_temporary``: about 93 bits), valid ``TEMPORARY_TTL``
and changed at the next sign-in (ASVS 6.4.1).

This module alone reads and writes the password table of the state database
(``StateStore.password_record``, ``StateStore.set_password``); the hash never
leaves it but into a backup. A test may lower the cost by replacing
``HASHER``, never the defaults of the code.
"""

import functools
import secrets
import threading
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Literal

import argon2
from argon2.exceptions import InvalidHashError, VerificationError

from archiwista.auth.authorize import ADMIN
from archiwista.auth.principal import Principal
from archiwista.errors import InvalidChangeError, NotFoundError
from archiwista.messages import Message, message
from archiwista.state import PasswordRecord, StateStore, UserRecord

type PolicyRule = Literal["too_short", "too_long", "account_name", "common"]

MIN_LENGTH = 12
MAX_LENGTH = 1024
TEMPORARY_TTL = timedelta(hours=72)
HASH_SLOTS = 2
HASHER = argon2.PasswordHasher()
# Package data of ``archiwista.auth`` (scripts/build_common_passwords.py).
COMMON_PASSWORDS = "common-passwords.txt"
COMMON_PASSWORDS_MANIFEST = "common-passwords.json"
# Letters and digits without look-alikes (0, O, o, 1, l, I): 56 symbols, of
# which 16 carry about 93 bits, in four groups of four joined by "-".
TEMPORARY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
TEMPORARY_GROUPS = 4
TEMPORARY_GROUP_LENGTH = 4

_SLOTS = threading.BoundedSemaphore(HASH_SLOTS)
_STAND_IN_LOCK = threading.Lock()
_stand_in: tuple[argon2.PasswordHasher, str] | None = None


@dataclass(frozen=True, slots=True)
class Verified:
    """The outcome of ``verify``.

    Attributes
    ----------
    matches : bool
        The password is the account's.
    expired : bool
        It matches a temporary password past its end.
    temporary : bool
        It matches a temporary password, which must be changed now.
    needs_rehash : bool
        It matches a hash of other parameters than ``HASHER``'s; hash it
        again.
    """

    matches: bool
    expired: bool = False
    temporary: bool = False
    needs_rehash: bool = False


@dataclass(frozen=True, slots=True)
class TemporaryPassword:
    """A temporary password the server generated, to be shown once.

    Attributes
    ----------
    password : str
        The password; never shown by ``repr``.
    expires_at : datetime
        Its end (UTC).
    user : UserRecord
        The account after the change.
    """

    password: str = field(repr=False)
    expires_at: datetime
    user: UserRecord


def normalize(password: str) -> str:
    """Return a password as Archiwista hashes and measures it: NFKC."""
    return unicodedata.normalize("NFKC", password)


def fold(password: str) -> str:
    """Return a password as the policy compares it: NFKC, then case-folded."""
    return normalize(password).casefold()


def policy_problem(password: str, *, account: str, name: str) -> PolicyRule | None:
    """Return the rule a new password breaks, or ``None`` when it is acceptable.

    Parameters
    ----------
    password : str
        The password as received.
    account, name : str
        The id and the display name of its account.

    Returns
    -------
    PolicyRule or None
        ``too_short`` or ``too_long`` (characters after NFKC, so a ligature
        counts as two letters), ``account_name`` (equal to the account's id
        or name, ignoring case), ``common`` (in the list of common
        passwords, ignoring case), or ``None``.
    """
    length = len(normalize(password))
    if length < MIN_LENGTH:
        return "too_short"
    if length > MAX_LENGTH:
        return "too_long"
    folded = fold(password)
    if folded in (fold(account), fold(name)):
        return "account_name"
    if folded in common_passwords():
        return "common"
    return None


def policy_text(rule: PolicyRule) -> Message:
    """Return what a person must change for ``rule``."""
    if rule == "too_short":
        return message("auth.password_too_short", minimum=MIN_LENGTH)
    if rule == "too_long":
        return message("auth.password_too_long", maximum=MAX_LENGTH)
    if rule == "account_name":
        return message("auth.password_account_name")
    return message("auth.password_common")


@functools.cache
def common_passwords() -> frozenset[str]:
    """Return the common passwords of the package, each folded (``fold``)."""
    text = (
        resources.files("archiwista.auth")
        .joinpath(COMMON_PASSWORDS)
        .read_text(encoding="utf-8")
    )
    return frozenset(line for line in text.split("\n") if line)


def hash_password(password: str) -> str:
    """Return the Argon2id hash (PHC string) of a password after NFKC."""
    with _SLOTS:
        return HASHER.hash(normalize(password))


def verify(
    record: PasswordRecord | None, password: str, *, now: datetime | None = None
) -> Verified:
    """Check a password against an account's, with one verification on every path.

    Parameters
    ----------
    record : PasswordRecord or None
        The account's password; ``None`` for an unknown account or one
        without a password: a stand-in hash is verified then, so the work
        is the same.
    password : str
        The password as received.
    now : datetime or None, optional
        The time that ends a temporary password; the current time when
        omitted.
    """
    hasher = HASHER
    target = _stand_in_hash(hasher) if record is None else record.hash
    with _SLOTS:
        try:
            hasher.verify(target, normalize(password))
        except (VerificationError, InvalidHashError):
            return Verified(matches=False)
    if record is None:  # pragma: no cover - the stand-in's password is random
        return Verified(matches=False)
    moment = now or datetime.now(UTC)
    ends = record.expires_at
    return Verified(
        matches=True,
        expired=record.temporary and (ends is None or ends <= moment),
        temporary=record.temporary,
        needs_rehash=hasher.check_needs_rehash(record.hash),
    )


def generate_temporary() -> str:
    """Return a new temporary password: 16 random symbols in four groups."""
    symbols = "".join(
        secrets.choice(TEMPORARY_ALPHABET)
        for _ in range(TEMPORARY_GROUPS * TEMPORARY_GROUP_LENGTH)
    )
    return "-".join(
        symbols[start : start + TEMPORARY_GROUP_LENGTH]
        for start in range(0, len(symbols), TEMPORARY_GROUP_LENGTH)
    )


def can_sign_in(user: UserRecord, *, proxy: bool) -> bool:
    """Return whether an account can sign in now.

    Parameters
    ----------
    user : UserRecord
        The account.
    proxy : bool
        Whether the reverse proxy names people (``proxy_user_header``): an
        enabled account then signs in through it without a password.

    Returns
    -------
    bool
        Enabled, and with a password that has not expired (``set`` or
        ``temporary``) or through the proxy.
    """
    return not user.disabled and (proxy or user.password in ("set", "temporary"))


def sign_in_administrators(
    users: Iterable[UserRecord], *, proxy: bool
) -> tuple[str, ...]:
    """Return the ids of the accounts with the role ``admin`` that can sign in.

    Team mode does not start without one (ADR-046 decision 2); see
    ``can_sign_in`` for ``proxy``.
    """
    return tuple(
        user.id
        for user in users
        if ADMIN in user.roles and can_sign_in(user, proxy=proxy)
    )


def set_password(
    state: StateStore,
    user_id: str,
    password: str,
    *,
    temporary: bool,
    actor: Principal,
    now: datetime | None = None,
) -> UserRecord:
    """Check a new password against the policy, then keep its hash.

    Every session of the account ends (its revocation time) and the action
    log gets ``user.password_reset``, in one transaction.

    Parameters
    ----------
    state : StateStore
        The state database.
    user_id : str
        The account.
    password : str
        The password as received.
    temporary : bool
        Valid ``TEMPORARY_TTL`` and to be changed at the next sign-in.
    actor : Principal
        Who sets it.
    now : datetime or None, optional
        The start of a temporary password's validity; the current time when
        omitted.

    Raises
    ------
    NotFoundError
        Unknown account.
    InvalidChangeError
        The password breaks the policy: reason ``password_policy``,
        ``details.rule`` names the rule.
    """
    user = state.user(user_id)
    if user is None:
        raise NotFoundError(message("state.user_not_found", id=user_id))
    rule = policy_problem(password, account=user.id, name=user.name)
    if rule is not None:
        raise InvalidChangeError(
            policy_text(rule), reason="password_policy", details={"rule": rule}
        )
    ends = None
    if temporary:
        ends = (now or datetime.now(UTC)).replace(microsecond=0) + TEMPORARY_TTL
    return state.set_password(
        user_id, hash_password(password), expires_at=ends, actor=actor
    )


def set_temporary_password(
    state: StateStore,
    user_id: str,
    *,
    actor: Principal,
    now: datetime | None = None,
) -> TemporaryPassword:
    """Generate a temporary password for an account and keep its hash.

    Raises
    ------
    NotFoundError
        Unknown account.
    """
    password = generate_temporary()
    user = set_password(state, user_id, password, temporary=True, actor=actor, now=now)
    if user.password_expires_at is None:  # pragma: no cover - set just now
        raise NotFoundError(message("state.user_not_found", id=user_id))
    return TemporaryPassword(password, user.password_expires_at, user)


def _stand_in_hash(hasher: argon2.PasswordHasher) -> str:
    """Return a hash of a random password made by ``hasher``, computed once."""
    global _stand_in
    with _STAND_IN_LOCK:
        if _stand_in is None or _stand_in[0] is not hasher:
            with _SLOTS:
                _stand_in = (hasher, hasher.hash(secrets.token_urlsafe(32)))
        return _stand_in[1]
