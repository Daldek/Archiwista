"""Passwords: the policy, Argon2id hashes, verification and temporary ones (ADR-046)."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Literal

import argon2
import pytest

from archiwista.auth import passwords
from archiwista.auth.passwords import (
    COMMON_PASSWORDS,
    COMMON_PASSWORDS_MANIFEST,
    MAX_LENGTH,
    MIN_LENGTH,
    TEMPORARY_ALPHABET,
    PolicyRule,
    Verified,
    fold,
    generate_temporary,
    hash_password,
    normalize,
    policy_problem,
    verify,
)
from archiwista.state import PasswordRecord
from tests.fixtures.team_server import cheap_hasher

ACCOUNT = "katarzyna.nowak"
NAME = "Katarzyna Nowakowska"
# NFKC makes the ligature "ﬁ" two letters, "fi".
LIGATURE = "\ufb01"
# Letters that no list of common passwords holds, cut to the length a case needs.
PROSE = "kajak-po-Rabie-o-swicie-" * 50
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


class CountingHasher(argon2.PasswordHasher):
    """``cheap_hasher`` that remembers each hash it verified and counts hashes."""

    def __init__(self) -> None:
        cheap = cheap_hasher()
        super().__init__(
            time_cost=cheap.time_cost,
            memory_cost=cheap.memory_cost,
            parallelism=cheap.parallelism,
        )
        self.verified: list[str] = []
        self.hashed = 0

    def verify(self, hash: str | bytes, password: str | bytes) -> Literal[True]:
        """Verify as argon2-cffi does, and count it."""
        self.verified.append(hash if isinstance(hash, str) else hash.decode())
        return super().verify(hash, password)

    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str:
        """Hash as argon2-cffi does, and count it."""
        self.hashed += 1
        return super().hash(password, salt=salt)


@pytest.fixture
def hasher(monkeypatch: pytest.MonkeyPatch) -> CountingHasher:
    """Make ``passwords.HASHER`` a cheap hasher that counts verifications."""
    counting = CountingHasher()
    monkeypatch.setattr(passwords, "HASHER", counting)
    return counting


def record(
    password: str,
    *,
    hasher: argon2.PasswordHasher,
    expires_at: datetime | None = None,
) -> PasswordRecord:
    """Return the record of ``password`` hashed by ``hasher``; temporary with an end."""
    return PasswordRecord(
        user_id=ACCOUNT,
        hash=hasher.hash(normalize(password)),
        set_at=NOW,
        set_by="local",
        temporary=expires_at is not None,
        expires_at=expires_at,
    )


def package_file(name: str) -> bytes:
    """Return a file of the package ``archiwista.auth`` as bytes."""
    return resources.files("archiwista.auth").joinpath(name).read_bytes()


@pytest.mark.parametrize(
    ("password", "rule"),
    [
        (PROSE[: MIN_LENGTH - 1], "too_short"),
        (PROSE[:MIN_LENGTH], None),
        (LIGATURE + PROSE[: MIN_LENGTH - 3], "too_short"),
        (LIGATURE + PROSE[: MIN_LENGTH - 2], None),
        (PROSE[:MAX_LENGTH], None),
        (PROSE[: MAX_LENGTH + 1], "too_long"),
        (LIGATURE + PROSE[: MAX_LENGTH - 2], None),
        (LIGATURE + PROSE[: MAX_LENGTH - 1], "too_long"),
    ],
)
def test_policy_measures_characters_after_nfkc(
    password: str, rule: PolicyRule | None
) -> None:
    """11 and 1,025 characters after NFKC are refused, 12 and 1,024 accepted."""
    assert policy_problem(password, account=ACCOUNT, name=NAME) == rule


@pytest.mark.parametrize(
    "password",
    [
        "KATARZYNA.NOWAK",
        "Katarzyna.Nowak",
        "katarzyna nowakowska",
        "KATARZYNA NOWAKOWSKA",
    ],
)
def test_policy_refuses_the_account_id_and_name_in_any_case(password: str) -> None:
    """A password equal to the account's id or name, ignoring case, is refused."""
    assert policy_problem(password, account=ACCOUNT, name=NAME) == "account_name"


def test_policy_refuses_a_common_password_in_upper_case() -> None:
    """The list is compared case-folded: the most common entry in capitals fails."""
    most_common = package_file(COMMON_PASSWORDS).decode("utf-8").split("\n")[0]

    problem = policy_problem(most_common.upper(), account=ACCOUNT, name=NAME)

    assert problem == "common"


@pytest.mark.parametrize(
    "password",
    [
        "739104628351",
        "kajakporabie",
        "KAJAKPORABIE",
        "ala ma kota i psa",
        "zażółć gęślą jaźń",
        "\N{WATER WAVE}\N{WATER WAVE} wiosna nad Rabą",
    ],
)
def test_policy_accepts_any_composition(password: str) -> None:
    """Digits only, one case only, spaces, Polish letters or symbols: no rule."""
    assert policy_problem(password, account=ACCOUNT, name=NAME) is None


@pytest.mark.parametrize("case", ["no record", "wrong password", "right password"])
def test_verify_verifies_exactly_one_hash_on_every_path(
    hasher: CountingHasher, case: str
) -> None:
    """Without a record the stand-in hash is verified, so no path does less work."""
    kept = None if case == "no record" else record("kajak-po-Rabie", hasher=hasher)
    typed = "kajak-po-Rabie" if case == "right password" else "kajak-po-Wisle"

    result = verify(kept, typed, now=NOW)

    assert result.matches is (case == "right password")
    assert len(hasher.verified) == 1
    if kept is None:
        assert hasher.verified[0].startswith("$argon2id$")
    else:
        assert hasher.verified == [kept.hash]


def test_prepare_stand_in_leaves_an_unknown_account_one_verification(
    hasher: CountingHasher,
) -> None:
    """After the start's preparation an unknown account costs no hash besides.

    The stand-in hash used to be made at the first unknown account, which
    then cost a hash and a verification while every other failure costs one
    verification (review of v0.4, D10; ADR-046 decision 5).
    """
    passwords.prepare_stand_in()
    prepared = hasher.hashed

    result = verify(None, "kajak-po-Wisle", now=NOW)

    assert prepared == 1
    assert (result.matches, hasher.hashed, len(hasher.verified)) == (False, 1, 1)


def test_verify_asks_to_rehash_a_hash_of_other_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hash weaker than ``HASHER``'s matches and reports ``needs_rehash``."""
    weaker = cheap_hasher()
    current = argon2.PasswordHasher(
        time_cost=weaker.time_cost + 1,
        memory_cost=weaker.memory_cost,
        parallelism=weaker.parallelism,
    )
    monkeypatch.setattr(passwords, "HASHER", current)
    old = record("kajak-po-Rabie", hasher=weaker)
    new = record("kajak-po-Rabie", hasher=current)

    assert verify(old, "kajak-po-Rabie") == Verified(matches=True, needs_rehash=True)
    assert verify(new, "kajak-po-Rabie") == Verified(matches=True)


def test_verify_ends_a_temporary_password_at_its_end(hasher: CountingHasher) -> None:
    """A temporary password matches until its end and is ``expired`` from then on."""
    end = NOW + timedelta(hours=1)
    kept = record("Hk7m-Q2xa-9cPe-Rt4w", hasher=hasher, expires_at=end)

    before = verify(kept, "Hk7m-Q2xa-9cPe-Rt4w", now=end - timedelta(seconds=1))
    at_end = verify(kept, "Hk7m-Q2xa-9cPe-Rt4w", now=end)

    assert before == Verified(matches=True, temporary=True)
    assert at_end == Verified(matches=True, expired=True, temporary=True)


def test_password_matches_in_another_unicode_form(hasher: CountingHasher) -> None:
    """A password is hashed after NFKC: the ligature and its two letters match."""
    hashed = hash_password(LIGATURE + "ord-nad-Raba")
    kept = PasswordRecord(ACCOUNT, hashed, NOW, "local", False, None)

    assert hashed.startswith("$argon2id$")
    assert verify(kept, "fiord-nad-Raba").matches
    assert not verify(kept, "Fiord-nad-Raba").matches


def test_generated_temporary_passwords_pass_the_policy_and_differ() -> None:
    """1,000 temporary passwords: four groups of four symbols, all accepted, all new."""
    symbols = re.escape(TEMPORARY_ALPHABET)
    shape = re.compile(rf"[{symbols}]{{4}}(-[{symbols}]{{4}}){{3}}")

    generated = [generate_temporary() for _ in range(1000)]

    assert len(set(generated)) == len(generated)
    for password in generated:
        assert shape.fullmatch(password), password
        assert policy_problem(password, account=ACCOUNT, name=NAME) is None


def test_common_password_list_matches_its_manifest() -> None:
    """3,000 folded entries of 12 characters or more, as the manifest's SHA-256 says."""
    manifest = json.loads(package_file(COMMON_PASSWORDS_MANIFEST))
    listed = package_file(COMMON_PASSWORDS)
    licence = package_file(manifest["licence_file"])
    entries = listed.decode("utf-8").removesuffix("\n").split("\n")

    assert hashlib.sha256(listed).hexdigest() == manifest["sha256"]
    assert hashlib.sha256(licence).hexdigest() == manifest["licence_sha256"]
    assert len(entries) == manifest["count"] >= 3000
    assert len(set(entries)) == len(entries)
    for entry in entries:
        assert MIN_LENGTH <= len(normalize(entry)) <= MAX_LENGTH, entry
        assert fold(entry) == entry
    assert manifest["licence"] == "MIT"
    assert manifest["commit"] in manifest["source"]
