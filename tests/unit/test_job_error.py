"""The error of a job: a registry code with the job's own cause as the reason."""

import json

import pytest

from archiwista._errors import BY_CODE
from archiwista.error_document import describe
from archiwista.errors import (
    NotFoundError,
    OfflineModeError,
    ProducerError,
    SnapshotBlockedError,
    SnapshotFailedError,
    SourceUnavailableError,
)
from archiwista.jobs import JobError
from archiwista.messages import language, message
from archiwista.sources.types import SourceState


@pytest.mark.parametrize(
    ("stored", "code", "details"),
    [
        (
            {"code": "store_unavailable"},
            "store_unavailable",
            {"reason": "store_unreadable"},
        ),
        (
            {"code": "source_unavailable"},
            "missing_dependency",
            {"reason": "source_unavailable"},
        ),
        (
            {"code": "source_incompatible"},
            "missing_dependency",
            {"reason": "source_incompatible"},
        ),
        (
            {"code": "own_reader_failed"},
            "missing_dependency",
            {"reason": "own_reader_failed"},
        ),
        ({"code": "offline_mode"}, "conflict", {"reason": "offline_mode"}),
        (
            {"code": "snapshot_blocked", "reason": "read_only_folder"},
            "conflict",
            {"reason": "snapshot_blocked", "blocked_by": "read_only_folder"},
        ),
        ({"code": "inconsistent_copy"}, "conflict", {"reason": "inconsistent_copy"}),
        ({"code": "target_exists"}, "conflict", {"reason": "target_exists"}),
        ({"code": "checksum_mismatch"}, "data_error", {"reason": "checksum_mismatch"}),
        ({"code": "integrity_failed"}, "data_error", {"reason": "integrity_failed"}),
        ({"code": "kartograf_error"}, "data_error", {"reason": "kartograf_error"}),
        ({"code": "imgwtools_error"}, "data_error", {"reason": "imgwtools_error"}),
        ({"code": "path_outside_root"}, "forbidden", {"reason": "path_outside_root"}),
        ({"code": "worker_crashed"}, "internal_error", {"reason": "worker_crashed"}),
        ({"code": "protocol_error"}, "internal_error", {"reason": "protocol_error"}),
        ({"code": "interrupted"}, "cancelled", {"reason": "interrupted"}),
        ({"code": "not_found"}, "not_found", {}),
        ({"code": "unsupported"}, "unsupported", {}),
        ({"code": "cancelled"}, "cancelled", {}),
        ({"code": "internal_error"}, "internal_error", {}),
        (
            {"code": "a_code_nobody_knows"},
            "internal_error",
            {"reason": "a_code_nobody_knows"},
        ),
    ],
)
def test_error_of_an_earlier_version_reads_as_a_registry_code(
    stored: dict[str, str], code: str, details: dict[str, str]
) -> None:
    """A row of 0.2.x has no ``details``: its job code becomes code and reason."""
    error = JobError.from_json({**stored, "detail": "Opis."})

    assert error.code == code and code in BY_CODE
    assert dict(error.details) == details
    assert error.detail == "Opis."
    assert error.hint is None
    # What is sent from then on has the current members.
    assert error.to_json() == {"code": code, "detail": "Opis.", "details": details}


def test_current_error_is_read_as_it_was_written() -> None:
    """A current error keeps its code: ``source_unavailable`` is a remote failure."""
    written = JobError(
        "source_unavailable",
        "Odpowiedź serwera: 503.",
        {"reason": "http_error", "status": 503},
        "Spróbuj później.",
    )

    read = JobError.from_json(written.to_json())

    assert read == written
    assert read.reason == "http_error"
    assert written.to_json()["hint"] == "Spróbuj później."


def test_current_error_without_a_reason_has_no_reason() -> None:
    """``details`` is kept even when empty, and the reason is then ``None``."""
    error = JobError("cancelled", "Zadanie anulowano.")

    assert error.to_json() == {
        "code": "cancelled",
        "detail": "Zadanie anulowano.",
        "details": {},
    }
    assert JobError.from_json(error.to_json()) == error
    assert error.reason is None


def test_error_of_the_worker_has_the_problem_of_the_same_exception() -> None:
    """The error of a job and the problem of a request agree on the cause."""
    state = SourceState(producer="kartograf", status="not_installed")
    errors = [
        OfflineModeError("Offline."),
        SnapshotBlockedError("folder_invalid", "Folder."),
        SnapshotFailedError("integrity_failed", "Kopia."),
        ProducerError("kartograf", "ValidationError", "Zła skala."),
        SourceUnavailableError("Brak magazynu."),
        SourceUnavailableError("Brak wtyczki.", state=state),
    ]

    for error in errors:
        problem = describe(error)
        job = JobError.of(error)
        assert (job.code, job.detail, job.hint) == (
            problem.code,
            problem.detail,
            problem.hint,
        )
        assert dict(job.details) == dict(problem.details)
        assert job.reason == problem.details["reason"]


def test_message_of_the_worker_becomes_an_error_whatever_its_code() -> None:
    """A message is no 0.2.x row: its ``source_unavailable`` is the registry's."""
    error = JobError.from_message(
        {"code": "source_unavailable", "detail": "Zły.", "exception": "OSError"}
    )

    assert error == JobError("source_unavailable", "Zły.")
    assert error.hint is None


def test_error_keeps_the_keys_of_its_texts_beside_the_stored_polish_text() -> None:
    """A job ends in another process and is read in another language."""
    written = JobError(
        "not_found",
        message("job.store_unknown", "en", store="alfa"),
        hint=message("fix.install", "en", requirement="kartograf"),
    )

    stored = written.to_json()
    with language("en"):
        read = JobError.from_json(json.loads(json.dumps(stored)))

    assert stored == {
        "code": "not_found",
        "detail": "Magazyn „alfa” nie jest skonfigurowany.",
        "key": "job.store_unknown",
        "values": {"store": "alfa"},
        "hint": 'zainstaluj zgodną wersję: pip install "kartograf"',
        "hint_key": "fix.install",
        "hint_values": {"requirement": "kartograf"},
        "details": {},
    }
    assert read == written
    assert read.public_json("pl") == {
        "code": "not_found",
        "detail": "Magazyn „alfa” nie jest skonfigurowany.",
        "hint": 'zainstaluj zgodną wersję: pip install "kartograf"',
        "details": {},
    }
    assert read.public_json("en") == {
        "code": "not_found",
        "detail": 'Store "alfa" is not configured.',
        "hint": 'install a compatible version: pip install "kartograf"',
        "details": {},
    }


def test_error_whose_message_the_catalog_forgot_is_read_as_it_was_stored() -> None:
    """A text of an older version stays what it was, in the language it had."""
    stored = JobError(
        "not_found", message("job.store_unknown", "en", store="alfa")
    ).to_json()
    stored["key"] = "job.no_such_message"

    with language("en"):
        read = JobError.from_json(stored)

    assert read.detail == "Magazyn „alfa” nie jest skonfigurowany."
    assert read.localized("en").detail == "Magazyn „alfa” nie jest skonfigurowany."


def test_error_a_worker_sends_is_the_stored_error_and_its_exception() -> None:
    """The supervisor reads the worker's message with the texts still translatable."""
    error = JobError.of(NotFoundError(message("job.store_unknown", "en", store="alfa")))

    sent = {**error.to_json(), "exception": "NotFoundError"}
    with language("en"):
        received = JobError.from_message(json.loads(json.dumps(sent)))

    assert received == error
    assert received.localized("pl").detail == "Magazyn „alfa” nie jest skonfigurowany."
