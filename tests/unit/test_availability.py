"""Whether a store directory can be read now, and why not (``store_unreachable``)."""

from pathlib import Path

from archiwista.jobs.availability import store_unreachable
from archiwista.sources import SourceState

AVAILABLE = SourceState(producer="kartograf", status="available")


def test_store_unreachable_is_none_for_a_store_that_can_be_read(tmp_path: Path) -> None:
    """A probed, non-empty directory is reachable, indexed or not."""
    (tmp_path / "nmt").mkdir()

    assert store_unreachable(AVAILABLE, tmp_path, indexed=True) is None
    assert store_unreachable(AVAILABLE, tmp_path, indexed=False) is None


def test_store_unreachable_gives_the_reason_and_hint_of_a_refused_store(
    tmp_path: Path,
) -> None:
    """What the producer says about a directory it refuses is the job's error."""
    refused = SourceState(
        producer="kartograf",
        status="incompatible",
        detail="no marker here",
        reason="no_marker",
        hint="run the init command",
    )

    error = store_unreachable(refused, tmp_path, indexed=False)

    assert error is not None
    assert (error.code, error.details["reason"], error.hint) == (
        "store_unavailable",
        "no_marker",
        "run the init command",
    )
    assert str(tmp_path) in str(error)
    assert "no marker here" in str(error)


def test_store_unreachable_without_a_reason_is_store_unreadable(tmp_path: Path) -> None:
    """A probe that has nothing to add behaves as it did before the reason."""
    failed = SourceState(producer="kartograf", status="error", detail="boom")

    error = store_unreachable(failed, tmp_path, indexed=False)

    assert error is not None
    assert (error.code, error.details["reason"], error.hint) == (
        "store_unavailable",
        "store_unreadable",
        None,
    )


def test_store_unreachable_empty_directory_counts_only_for_an_indexed_store(
    tmp_path: Path,
) -> None:
    """An empty mount point of a known store is unavailable, a new store may be."""
    error = store_unreachable(AVAILABLE, tmp_path, indexed=True)

    assert error is not None
    assert error.details["reason"] == "store_unreadable"
    assert str(tmp_path) in str(error)
    assert store_unreachable(AVAILABLE, tmp_path, indexed=False) is None
