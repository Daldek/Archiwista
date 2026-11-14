"""The records of the server's logs (Nogat ``nogat-log/1``) read back by a test.

``records`` reads the JSON Lines of one kind from a directory of logs
(``AppPaths.logs_dir``), ``printed`` those of a standard error; both check each
record against the copy of Nogat's schema, ``schemas/nogat/record-1.schema.json``.
"""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA = (
    Path(__file__).resolve().parents[2] / "schemas" / "nogat" / "record-1.schema.json"
)
_RECORD = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def records(directory: Path, kind: str) -> list[dict[str, Any]]:
    """Return the records of ``kind`` in ``directory``, file by file in date order."""
    return [
        record
        for path in sorted(directory.glob(f"{kind}-*.jsonl"))
        for record in printed(path.read_text(encoding="utf-8"))
    ]


def printed(text: str) -> list[dict[str, Any]]:
    """Return the records of ``text``, one per line, each valid against the schema."""
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        record = json.loads(line)
        errors = [error.message for error in _RECORD.iter_errors(record)]
        assert errors == [], (record, errors)
        found.append(record)
    return found
