"""The error of a refused command, read as an agent reads it (AGI-3.2, AGI-3.3).

A refusal prints nothing on standard output; the last line of standard error
is the ``archiwista-error/1`` document and the exit status is the registry's
exit code of its ``code``.
"""

import json
from collections.abc import Mapping
from typing import Any

from archiwista._errors import BY_CODE
from tests.contract import _nogat


def refusal(out: str, err: str, status: int | None = None) -> dict[str, Any]:
    """Return the validated error document of a refused command.

    Parameters
    ----------
    out, err : str
        What the command wrote to standard output and standard error.
    status : int or None, optional
        The exit status the command returned, checked against the document.

    Returns
    -------
    dict[str, Any]
        The document on the last line of standard error.
    """
    assert out == ""
    lines = err.strip().splitlines()
    assert lines, "no error document on standard error"
    document: dict[str, Any] = json.loads(lines[-1])
    _nogat.validator("error-1").validate(document)
    assert document["exit_code"] == BY_CODE[document["code"]].exit_code
    if status is not None:
        assert status == document["exit_code"], err
    return document


def assert_same_error(document: Mapping[str, Any], problem: Mapping[str, Any]) -> None:
    """Check that a command's error document says what the API's problem says.

    Parameters
    ----------
    document : Mapping[str, Any]
        The ``archiwista-error/1`` document of the command.
    problem : Mapping[str, Any]
        The ``application/problem+json`` body of the route (AGI-1.2).
    """
    details = dict(problem.get("details", {}))
    if "errors" in problem:
        details["errors"] = problem["errors"]
    assert document["code"] == problem["code"]
    assert document["message"] == problem["detail"]
    assert document.get("hint") == problem.get("hint")
    assert document["details"] == details
