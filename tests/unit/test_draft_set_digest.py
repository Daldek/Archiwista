r"""The digest of a set's pins, ``pins_sha256`` (A-ADR-049 erratum 6).

The test vector is shared with Hydrograf, which checks a closed set's
``pins_sha256`` by the same rule: the SHA-256 of the lines
``<producer>\t<version>\t<sha256>\n`` sorted by producer, then version, by
code point.
"""

import hashlib
import itertools

from archiwista.projects.document import pins_digest, seal_group, unseal_group

VECTOR = "e7319a8d77a126fc2eb12f46b92ef5ac98a5b2132808474eebbb222fd5c691fe"
NMT = ("kartograf", "nmt/pl_1992_5m_evrf2007/versions/b.asc", "b" * 64)
HSG = ("kartograf", "hsg/a.tif", "a" * 64)


def test_the_shared_vector_in_every_order() -> None:
    """Both orders of the vector's two pins give the vector."""
    # Act
    digests = {pins_digest(order) for order in itertools.permutations([NMT, HSG])}

    # Assert
    assert digests == {VECTOR}


def test_pins_sort_by_producer_then_version_by_code_point() -> None:
    """Upper case sorts before lower case and the producer before the version."""
    # Arrange
    pins = [
        ("kartograf", "b.tif", "1" * 64),
        ("imgw", "z.csv", "2" * 64),
        ("kartograf", "B.tif", "3" * 64),
        ("kartograf", "a.tif", "4" * 64),
    ]
    lines = [
        "imgw\tz.csv\t" + "2" * 64,
        "kartograf\tB.tif\t" + "3" * 64,
        "kartograf\ta.tif\t" + "4" * 64,
        "kartograf\tb.tif\t" + "1" * 64,
    ]
    expected = hashlib.sha256(
        "".join(f"{line}\n" for line in lines).encode()
    ).hexdigest()

    # Act
    digests = {pins_digest(order) for order in itertools.permutations(pins)}

    # Assert
    assert digests == {expected}


def test_closing_a_group_seals_only_the_pins_identity() -> None:
    """Calls, times and labels leave the digest; reopening drops the closing."""

    # Arrange
    def pin(
        producer: str, version: str, sha256: str, calls: list[int]
    ) -> dict[str, object]:
        return {
            "producer": producer,
            "version": version,
            "sha256": sha256,
            "size_bytes": 7,
            "unit": "u",
            "label": "etykieta",
            "pinned_at": "2026-11-02T10:00:00Z",
            "pinned_by": "olga",
            "calls": calls,
        }

    group: dict[str, object] = {
        "name": "Zestaw",
        "state": "open",
        "origin": {
            "kind": "plan",
            "producer": "kartograf",
            "calls": [{"command": "elevation download", "options": {"year": 2022}}],
        },
        "pins": [pin(*NMT, [0]), pin(*HSG, [])],
    }

    # Act
    digest = seal_group(group, closed_at="2026-11-02T10:05:00Z", closed_by="olga")
    sealed = dict(group)
    ended = unseal_group(group)

    # Assert
    assert digest == VECTOR
    assert list(sealed)[:5] == [
        "name",
        "state",
        "closed_at",
        "closed_by",
        "pins_sha256",
    ]
    assert (sealed["state"], sealed["pins_sha256"]) == ("closed", VECTOR)
    assert ended == {
        "closed_at": "2026-11-02T10:05:00Z",
        "closed_by": "olga",
        "pins_sha256": VECTOR,
    }
    assert group["state"] == "open"
    assert not {"closed_at", "closed_by", "pins_sha256"} & set(group)
