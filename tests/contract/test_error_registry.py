"""The error module is generated from the vendored Nogat registry (ERR-3, ERR-1)."""

import importlib.util
import json
import re
from io import StringIO
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator

import archiwista.api.errors
import archiwista.config
import archiwista.index.schema
from archiwista import _errors
from archiwista.error_document import (
    Problem,
    describe,
    error_document,
    language_of,
    pointer,
    refuse,
    title_of,
)
from archiwista.errors import (
    ArchiwistaError,
    AreaUnreadableError,
    JobConflictError,
    PathOutsideRootError,
    PreviewBusyError,
    PreviewNotReadyError,
    PreviewParameterError,
    PreviewUnavailableError,
    ProducerError,
    SnapshotBlockedError,
    SnapshotFailedError,
    SourceIncompatibleError,
    SourceUnavailableError,
)
from archiwista.sources.types import SourceState, SourceStatus
from tests.contract import _nogat

REGISTRY = _nogat.SCHEMAS / "error_registry.json"
REASON = re.compile(r"^[a-z][a-z0-9_]*$")


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_errors", _nogat.ROOT / "scripts" / "generate_errors.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _subclasses(base: type[ArchiwistaError]) -> list[type[ArchiwistaError]]:
    found = []
    for kind in base.__subclasses__():
        found.append(kind)
        found.extend(_subclasses(kind))
    return found


def test_error_module_equals_the_generator_output() -> None:
    """Error module equals the generator output."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    generated = _generator().render(registry)

    module = _nogat.ROOT / "src" / "archiwista" / "_errors.py"
    assert module.read_text(encoding="utf-8") == generated


def test_error_module_carries_every_code_and_outcome_of_the_registry() -> None:
    """Error module carries every code and outcome of the registry."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    assert [c.code for c in _errors.CODES] == [e["code"] for e in registry["errors"]]
    assert {
        o["status"]: o["exit_code"] for o in registry["outcomes"]
    } == _errors.OUTCOMES


@pytest.mark.parametrize("name", _nogat.NAMES)
def test_vendored_schema_is_a_valid_json_schema(name: str) -> None:
    """Vendored schema is a valid json schema."""
    Draft202012Validator.check_schema(_nogat.load(name))


def test_vendored_error_schema_lists_the_registry_codes() -> None:
    """Vendored error schema lists the registry codes."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    schema = _nogat.load("error-1")

    assert schema["$defs"]["code"]["enum"] == [e["code"] for e in registry["errors"]]


def test_every_error_class_defaults_to_a_registry_code_and_a_snake_case_reason() -> (
    None
):
    """ERR-1: no code of its own; the finer cause is a ``reason``."""
    kinds: list[type[ArchiwistaError]] = [
        ArchiwistaError,
        *_subclasses(ArchiwistaError),
    ]

    assert len(kinds) > 25
    for kind in kinds:
        assert kind.default_code in _errors.BY_CODE, kind
        assert kind.default_reason is None or REASON.match(kind.default_reason), kind


def test_an_error_refuses_a_code_that_is_not_in_the_registry() -> None:
    """An error refuses a code that is not in the registry."""
    with pytest.raises(ValueError, match="unknown error code"):
        ArchiwistaError("x", code="preview_busy")


def test_reason_and_details_are_kept_in_the_details() -> None:
    """Reason and details are kept in the details."""
    error = ArchiwistaError(
        "x", code="conflict", reason="job_running", details={"job": {"id": "a"}}
    )

    assert error.details == {"reason": "job_running", "job": {"id": "a"}}
    assert error.exit_code == 4
    assert error.http_status == 409


def _plugin(status: SourceStatus) -> SourceState:
    return SourceState(producer="kartograf", status=status)


def _samples() -> list[ArchiwistaError]:
    return [
        ArchiwistaError("bug"),
        PathOutsideRootError("outside"),
        AreaUnreadableError("unreadable", layers=("a", "b")),
        JobConflictError("busy", job_id="j1", kind="scan", state="running"),
        PreviewBusyError("busy", retry_after_s=5),
        PreviewNotReadyError("wait", job_id="j1", kind="preview", state="running"),
        PreviewParameterError("query.style", "no such style"),
        PreviewUnavailableError("no_crs", "no CRS"),
        ProducerError("kartograf", "ValidationError", "bad scale"),
        SnapshotBlockedError("read_only_folder", "read only"),
        SnapshotFailedError("target_exists", "taken"),
        SourceUnavailableError("no store"),
        SourceUnavailableError("no plugin", state=_plugin("not_installed")),
        SourceIncompatibleError("old", state=_plugin("incompatible")),
        archiwista.config.SettingsValidationError(
            [archiwista.config.SettingsProblem("root_missing", "stores[0]", "no root")]
        ),
        archiwista.index.schema.IndexUnsupportedError("no FTS5"),
        archiwista.api.errors.ApiError(
            "unauthorized", "no session", reason="session_required"
        ),
    ]


@pytest.mark.parametrize("error", _samples(), ids=lambda error: type(error).__name__)
def test_error_documents_validate_against_the_error_schema(
    error: ArchiwistaError,
) -> None:
    """Error documents validate against the error schema."""
    document = error_document(describe(error), command="preview thumbnail")

    _nogat.validator("error-1").validate(document)
    assert document["schema"] == "archiwista-error/1"
    assert document["exit_code"] == _errors.BY_CODE[error.code].exit_code
    assert document["title"] == title_of(error.code)


@pytest.mark.parametrize("error", _samples(), ids=lambda error: type(error).__name__)
def test_problem_status_comes_from_the_registry(error: ArchiwistaError) -> None:
    """Problem status comes from the registry."""
    problem = describe(error)

    assert problem.code == error.code
    assert problem.status == _errors.BY_CODE[error.code].http_status


def test_refuse_ends_standard_error_with_the_document_and_returns_the_exit_code() -> (
    None
):
    """Refuse ends standard error with the document and returns the exit code."""
    err = StringIO()
    problem = describe(PathOutsideRootError("Ścieżka wychodzi poza magazyn."))

    status = refuse(problem, err, command="preview thumbnail")

    lines = err.getvalue().splitlines()
    document = json.loads(lines[-1])
    assert status == 12
    assert lines[0] == "Ścieżka wychodzi poza magazyn."
    assert document["details"]["reason"] == "path_outside_root"
    assert document["command"] == "preview thumbnail"
    _nogat.validator("error-1").validate(document)


def test_a_rest_only_code_exits_with_one_and_a_null_exit_code() -> None:
    """A rest only code exits with one and a null exit code."""
    err = StringIO()

    status = refuse(describe(PreviewBusyError("busy", retry_after_s=5)), err)

    assert status == 1
    assert json.loads(err.getvalue().splitlines()[-1])["exit_code"] is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "en"),
        ("", "en"),
        ("pl", "pl"),
        ("pl-PL,pl;q=0.9,en;q=0.8", "pl"),
        ("en-US,en;q=0.9,pl;q=0.8", "en"),
        ("en;q=0.2, pl;q=0.7", "pl"),
        ("pl;q=0", "en"),
        ("de, *;q=0.1", "en"),
    ],
)
def test_language_follows_the_highest_quality_tag(
    header: str | None, expected: str
) -> None:
    """Language follows the highest quality tag."""
    assert language_of(header) == expected


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("query.limit", "/query/limit"),
        (("body", "areas", 0, "name"), "/body/areas/0/name"),
        (("query", "a/b~c"), "/query/a~1b~0c"),
    ],
)
def test_pointer_is_a_json_pointer(
    location: str | tuple[object, ...], expected: str
) -> None:
    """Pointer is a json pointer."""
    assert pointer(location) == expected


def test_the_problem_of_a_plain_registry_code_has_no_details() -> None:
    """The problem of a plain registry code has no details."""
    problem = Problem("not_found", "Nie ma.")

    assert problem.details == {}
    assert (problem.status, problem.exit_code) == (404, 3)
