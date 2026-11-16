"""Build the common-password list of the password policy from SecLists (ADR-046).

The policy refuses the most common passwords (OWASP ASVS 6.2.4). The list comes
from SecLists (MIT), ``Passwords/Common-Credentials/
10-million-password-list-top-1000000.txt``, ordered from the most frequent, at
``COMMIT``: the last commit that holds the file (``4ff3ff8e`` removed it on
2025-05-08 as a duplicate of the xato-net list). Only entries the length rule
could accept are kept: of the source's lines that are UTF-8, the first ``COUNT``
distinct ones of ``MIN_LENGTH`` to ``MAX_LENGTH`` characters after NFKC, each
written as the policy compares a password (``archiwista.auth.passwords.fold``:
NFKC, then case-folded), one per line.

The script writes, into ``src/archiwista/auth/``, ``common-passwords.txt`` (the
list), ``common-passwords.LICENSE`` (the licence of SecLists at that commit,
byte for byte) and ``common-passwords.json`` (the source, the commit, the
licence, the rule, the SHA-256 of the source, of the licence and of the list,
and the count). It downloads into memory and leaves no other file. It needs the
network, so the tests never run it; they check the list against its manifest.

Usage::

    uv run python scripts/build_common_passwords.py           # at COMMIT
    uv run python scripts/build_common_passwords.py OTHER     # another commit
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from archiwista.auth.passwords import (
    COMMON_PASSWORDS,
    COMMON_PASSWORDS_MANIFEST,
    MAX_LENGTH,
    MIN_LENGTH,
    fold,
    normalize,
)

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "src" / "archiwista" / "auth"
REPOSITORY = "danielmiessler/SecLists"
SOURCE_PATH = "Passwords/Common-Credentials/10-million-password-list-top-1000000.txt"
COMMIT = "2d5dc7504a40962c53f932a6d9d5ece4b213dfc6"
LICENCE = "MIT"
LICENCE_FILE = "common-passwords.LICENSE"
COUNT = 3000
TIMEOUT_S = 60
RULE = (
    f"the first {COUNT} distinct entries, in the source's order (most frequent"
    f" first), of {MIN_LENGTH} to {MAX_LENGTH} characters after NFKC, each"
    " NFKC-normalised and case-folded; lines that are not UTF-8 are skipped"
)


def select(lines: Iterable[bytes], count: int = COUNT) -> list[str]:
    """Return the first ``count`` distinct folded entries the length rule accepts.

    Parameters
    ----------
    lines : Iterable[bytes]
        The source's lines without their line endings, most frequent first.
    count : int, optional
        How many entries to keep.
    """
    chosen: list[str] = []
    seen: set[str] = set()
    for line in lines:
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not MIN_LENGTH <= len(normalize(text)) <= MAX_LENGTH:
            continue
        folded = fold(text)
        if folded in seen or "\n" in folded:
            continue
        seen.add(folded)
        chosen.append(folded)
        if len(chosen) == count:
            break
    return chosen


def main(argv: list[str] | None = None) -> int:
    """Download the source at a commit and write the list, its licence and manifest.

    Returns
    -------
    int
        ``0`` on success, ``1`` when the source holds fewer than ``COUNT``
        entries the rule accepts.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "commit",
        nargs="?",
        help=f"commit of SecLists that holds the file (default: {COMMIT})",
    )
    args = parser.parse_args(argv)
    commit = args.commit or COMMIT
    raw = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}"
    source = _fetch(f"{raw}/{SOURCE_PATH}")
    licence = _fetch(f"{raw}/LICENSE")
    entries = select(source.splitlines())
    if len(entries) < COUNT:
        print(f"only {len(entries)} entries of {COUNT} pass the rule", file=sys.stderr)
        return 1
    text = ("\n".join(entries) + "\n").encode("utf-8")
    manifest = {
        "source": f"https://github.com/{REPOSITORY}/blob/{commit}/{SOURCE_PATH}",
        "commit": commit,
        "licence": LICENCE,
        "licence_file": LICENCE_FILE,
        "rule": RULE,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "licence_sha256": hashlib.sha256(licence).hexdigest(),
        "count": len(entries),
        "sha256": hashlib.sha256(text).hexdigest(),
    }
    (TARGET / COMMON_PASSWORDS).write_bytes(text)
    (TARGET / LICENCE_FILE).write_bytes(licence)
    (TARGET / COMMON_PASSWORDS_MANIFEST).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"{len(entries)} entries of {REPOSITORY}@{commit}, sha256 {manifest['sha256']}"
    )
    return 0


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "archiwista-build-common-passwords"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        body: bytes = response.read()
    return body


if __name__ == "__main__":
    sys.exit(main())
