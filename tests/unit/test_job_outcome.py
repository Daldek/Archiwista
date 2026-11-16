"""Exit statuses of commands that follow jobs (ERR §1: outcomes, not errors)."""

import pytest

from archiwista.jobs.foreground import exit_status
from archiwista.jobs.reindex import _overall
from archiwista.jobs.supervisor import JobState


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("succeeded", 0),
        ("failed", 11),
        ("cancelled", 130),
        ("interrupted", 130),
        ("running", 130),  # Ctrl+C stopped the waiting for another process's job
    ],
)
def test_exit_status_of_a_job_follows_its_outcome(
    state: JobState, expected: int
) -> None:
    """A job that is not done well ends the command with its outcome's status."""
    assert exit_status(state) == expected


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([0], 0),
        ([0, 0], 0),
        ([11], 11),
        ([4], 4),
        ([0, 11], 10),  # some stores scanned, one failed: partial
        ([4, 0], 10),
        ([11, 11], 11),
        ([4, 11], 11),
        ([0, 130], 130),  # Ctrl+C wins over everything
        ([11, 130], 130),
    ],
)
def test_reindex_of_several_stores_reports_partial_only_after_a_success(
    statuses: list[int], expected: int
) -> None:
    """Exit 10 means some stores were scanned; none scanned gives the worst status."""
    assert _overall(statuses) == expected
