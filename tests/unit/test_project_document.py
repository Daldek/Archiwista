"""The rules of the project file ``archiwista-project/1`` (A-ADR-049 decisions 1, 2).

Every rule refuses with the JSON pointer of the member and the rule's name;
a newer schema is refused apart; names are NFC without surrounding white
space and group names compared case-folded; a reader ignores members it
does not know and a change keeps them.
"""

import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from archiwista.errors import ProjectFileError
from archiwista.messages import localize
from archiwista.projects import (
    PROJECT_FILE,
    LocalOrigin,
    PlanOrigin,
    change_project_file,
    document_json,
    parse_document,
    read_project_file,
)

SHA = "a" * 64
OTHER_SHA = "b" * 64
VERSION = (
    "nmt/pl_1992_1m_evrf2007/versions/N-34/130/D/d/2/4/2023-05-02_80011_fdd30535/"
    "N-34-130-D-d-2-4.asc"
)
PIN: dict[str, Any] = {
    "producer": "kartograf",
    "version": VERSION,
    "sha256": SHA,
    "size_bytes": 37812345,
    "unit": "N-34-130-D-d-2-4",
    "label": "2023-05-02_80011",
    "pinned_at": "2026-10-31T12:20:03Z",
    "pinned_by": "kasia",
}
DOCUMENT: dict[str, Any] = {
    "schema": "archiwista-project/1",
    "name": "Raba",
    "description": "Zlewnia Raby do Dobczyc",
    "created_at": "2026-10-31T12:04:11Z",
    "created_by": "kasia",
    "area": {"path": "obszary/5f2b9c0e7d41a3b6.geojson", "sha256": SHA},
    "stores": [{"producer": "kartograf", "root": "../../dane/kartograf"}],
    "groups": [
        {
            "name": "NMT 2023",
            "origin": {
                "kind": "plan",
                "producer": "kartograf",
                "calls": [
                    {
                        "command": "elevation download",
                        "options": {"product": "nmt", "sheet": "N-34-130-D-d-2-4"},
                    }
                ],
            },
            "pins": [PIN],
        },
        {
            "name": "Archiwa hydro",
            "origin": {
                "kind": "local",
                "selections": [
                    {
                        "from": "catalog",
                        "query": {"store": "zespol", "product": "hydro"},
                    },
                    {"from": "file"},
                ],
            },
            "pins": [
                {**PIN, "version": "a/b.asc", "content_sha256": OTHER_SHA},
                {**PIN, "producer": "imgw", "version": "hydro/x.csv", "unit": None},
            ],
        },
    ],
}

type Change = Callable[[dict[str, Any]], object]


def _changed(change: Change) -> dict[str, Any]:
    data = copy.deepcopy(DOCUMENT)
    change(data)
    return data


def _plan(data: dict[str, Any]) -> dict[str, Any]:
    group: dict[str, Any] = data["groups"][0]
    return group


def _local(data: dict[str, Any]) -> dict[str, Any]:
    group: dict[str, Any] = data["groups"][1]
    return group


def _pin(data: dict[str, Any]) -> dict[str, Any]:
    pin: dict[str, Any] = _plan(data)["pins"][0]
    return pin


# (change of the valid document, pointer, rule)
BROKEN: list[tuple[Change, str, str]] = [
    (lambda d: d.pop("schema"), "/schema", "required"),
    (lambda d: d.update(schema="kartograf-store/1"), "/schema", "schema"),
    (lambda d: d.update(schema="archiwista-project/0"), "/schema", "schema"),
    (lambda d: d.pop("name"), "/name", "required"),
    (lambda d: d.update(name=" \t "), "/name", "name"),
    (lambda d: d.update(name="x" * 201), "/name", "name"),
    (lambda d: d.update(name="Ra\x07ba"), "/name", "name"),
    (lambda d: d.update(name=7), "/name", "name"),
    (lambda d: d.update(description="x" * 2001), "/description", "description"),
    (lambda d: d.update(description=None), "/description", "description"),
    (lambda d: d.update(created_at="2026-10-31 12:04:11"), "/created_at", "time"),
    (lambda d: d.update(created_at="2026-02-30T12:04:11Z"), "/created_at", "time"),
    (lambda d: d.update(created_at="2026-10-31T12:04:11+01:00"), "/created_at", "time"),
    (lambda d: d.update(created_by=""), "/created_by", "account"),
    (lambda d: d.update(area="obszary/x.geojson"), "/area", "object"),
    (lambda d: d["area"].update(path="dane/x.geojson"), "/area/path", "area_path"),
    (lambda d: d["area"].update(path="obszary/../x"), "/area/path", "area_path"),
    (lambda d: d["area"].update(path="obszary/"), "/area/path", "area_path"),
    (lambda d: d["area"].update(sha256=SHA.upper()), "/area/sha256", "sha256"),
    (lambda d: d.pop("stores"), "/stores", "required"),
    (lambda d: d.update(stores={}), "/stores", "array"),
    (
        lambda d: d["stores"].append(d["stores"][0]),
        "/stores/1/producer",
        "store_unique",
    ),
    (
        lambda d: d["stores"][0].update(producer="Kartograf"),
        "/stores/0/producer",
        "producer",
    ),
    (lambda d: d["stores"][0].update(root=""), "/stores/0/root", "root"),
    (lambda d: d.update(groups=[[]]), "/groups/0", "object"),
    (lambda d: _plan(d).update(name="NMT/2023"), "/groups/0/name", "group_name"),
    (lambda d: _plan(d).update(name="x" * 81), "/groups/0/name", "group_name"),
    (lambda d: _local(d).update(name="nmt 2023"), "/groups/1/name", "group_unique"),
    (
        lambda d: _plan(d)["origin"].update(kind="remote"),
        "/groups/0/origin/kind",
        "origin",
    ),
    (lambda d: _plan(d)["origin"].pop("kind"), "/groups/0/origin/kind", "required"),
    (lambda d: _plan(d)["origin"].update(calls=[]), "/groups/0/origin/calls", "calls"),
    (
        lambda d: _plan(d)["origin"].update(
            calls=[{"command": "elevation download", "options": {}}] * 1001
        ),
        "/groups/0/origin/calls",
        "calls",
    ),
    (
        lambda d: _plan(d)["origin"]["calls"][0].update(command=""),
        "/groups/0/origin/calls/0/command",
        "command",
    ),
    (
        lambda d: _plan(d)["origin"]["calls"][0].pop("options"),
        "/groups/0/origin/calls/0/options",
        "required",
    ),
    (
        lambda d: _local(d)["origin"]["selections"][0].update({"from": "map"}),
        "/groups/1/origin/selections/0/from",
        "selection",
    ),
    (
        lambda d: _local(d)["origin"]["selections"][0].pop("query"),
        "/groups/1/origin/selections/0/query",
        "query",
    ),
    (
        lambda d: _local(d)["origin"]["selections"][1].update(query={}),
        "/groups/1/origin/selections/1/query",
        "query",
    ),
    (lambda d: _plan(d).pop("pins"), "/groups/0/pins", "required"),
    (
        lambda d: _local(d).update(
            pins=[{**PIN, "version": f"v/{index}.asc"} for index in range(10_001)]
        ),
        "/groups/1/pins",
        "pins",
    ),
    (
        lambda d: _pin(d).update(version="/nmt/x.asc"),
        "/groups/0/pins/0/version",
        "version",
    ),
    (
        lambda d: _pin(d).update(version="nmt/../x.asc"),
        "/groups/0/pins/0/version",
        "version",
    ),
    (
        lambda d: _pin(d).update(version="nmt\\x.asc"),
        "/groups/0/pins/0/version",
        "version",
    ),
    (
        lambda d: _pin(d).update(version="nmt//x.asc"),
        "/groups/0/pins/0/version",
        "version",
    ),
    (
        lambda d: _pin(d).update(version="C:/nmt/x.asc"),
        "/groups/0/pins/0/version",
        "version",
    ),
    (
        lambda d: _pin(d).update(version="c:x.asc"),
        "/groups/0/pins/0/version",
        "version",
    ),
    (
        lambda d: _plan(d)["pins"].append(dict(PIN)),
        "/groups/0/pins/1/version",
        "pin_unique",
    ),
    (
        lambda d: _pin(d).update(producer="imgw"),
        "/groups/0/pins/0/producer",
        "plan_producer",
    ),
    (lambda d: _pin(d).update(sha256="x"), "/groups/0/pins/0/sha256", "sha256"),
    (
        lambda d: _pin(d).update(content_sha256="x"),
        "/groups/0/pins/0/content_sha256",
        "sha256",
    ),
    (lambda d: _pin(d).update(size_bytes=-1), "/groups/0/pins/0/size_bytes", "size"),
    (lambda d: _pin(d).update(size_bytes=True), "/groups/0/pins/0/size_bytes", "size"),
    (lambda d: _pin(d).update(size_bytes="1"), "/groups/0/pins/0/size_bytes", "size"),
    (lambda d: _pin(d).update(unit=5), "/groups/0/pins/0/unit", "text"),
    (lambda d: _pin(d).pop("label"), "/groups/0/pins/0/label", "required"),
    (
        lambda d: _pin(d).update(pinned_at="yesterday"),
        "/groups/0/pins/0/pinned_at",
        "time",
    ),
    (lambda d: _pin(d).update(pinned_by=None), "/groups/0/pins/0/pinned_by", "account"),
]


def test_project_document_parse_document_reads_every_member() -> None:
    """The example of A-ADR-049 is read with its origins, pins and times."""
    document = parse_document(DOCUMENT)

    assert document.name == "Raba"
    assert document.created_at == datetime(2026, 10, 31, 12, 4, 11, tzinfo=UTC)
    assert document.area is not None and document.area.sha256 == SHA
    assert [(store.producer, store.root) for store in document.stores] == [
        ("kartograf", "../../dane/kartograf")
    ]
    plan, local = document.groups
    assert isinstance(plan.origin, PlanOrigin)
    assert plan.origin.calls[0].options["sheet"] == "N-34-130-D-d-2-4"
    assert plan.pins[0].version == VERSION and plan.pins[0].content_sha256 is None
    assert isinstance(local.origin, LocalOrigin)
    assert [item.source for item in local.origin.selections] == ["catalog", "file"]
    assert local.origin.selections[1].query is None
    assert [(pin.producer, pin.unit) for pin in local.pins] == [
        ("kartograf", "N-34-130-D-d-2-4"),
        ("imgw", None),
    ]
    assert local.pins[0].content_sha256 == OTHER_SHA


@pytest.mark.parametrize(("change", "pointer", "rule"), BROKEN)
def test_project_document_parse_document_refuses_each_rule_at_its_pointer(
    change: Change, pointer: str, rule: str
) -> None:
    """A member outside its rule makes the file invalid, named by pointer and rule."""
    with pytest.raises(ProjectFileError) as raised:
        parse_document(_changed(change))

    assert raised.value.code == "conflict"
    assert raised.value.details == {
        "reason": "invalid_project_file",
        "pointer": pointer,
        "rule": rule,
    }
    assert pointer in localize(raised.value.message, "pl")


def test_project_document_parse_document_refuses_a_value_that_is_no_object() -> None:
    """A file holding a JSON array is invalid as a whole."""
    with pytest.raises(ProjectFileError) as raised:
        parse_document([DOCUMENT])

    assert raised.value.details["pointer"] == ""
    assert raised.value.details["rule"] == "object"


def test_project_document_parse_document_refuses_a_newer_schema_apart() -> None:
    """``archiwista-project/2`` is a newer format, with the hint to update."""
    with pytest.raises(ProjectFileError) as raised:
        parse_document({"schema": "archiwista-project/2", "name": "Raba"})

    assert raised.value.details == {
        "reason": "unsupported_project_schema",
        "schema": "archiwista-project/2",
    }
    assert raised.value.hint


def test_project_document_parse_document_keeps_names_nfc_and_trimmed() -> None:
    """Names are compared as NFC without surrounding white space."""
    data = _changed(lambda d: d.update(name="  Rab\u0061\u0301 \n"))
    _plan(data)["name"] = " Zlewnia\u0301 "

    document = parse_document(data)

    assert document.name == "Rab\u00e1"
    assert document.groups[0].name == "Zlewni\u00e1"


def test_project_document_parse_document_compares_group_names_case_folded() -> None:
    """Two group names that fold to one are one name taken twice."""
    data = _changed(lambda d: _plan(d).update(name="Straße"))
    _local(data)["name"] = "STRASSE"

    with pytest.raises(ProjectFileError) as raised:
        parse_document(data)

    assert raised.value.details["pointer"] == "/groups/1/name"
    assert raised.value.details["rule"] == "group_unique"


def test_project_document_parse_document_ignores_unknown_members() -> None:
    """Members a newer Archiwista added within ``/1`` do not stop the reader."""
    data = _changed(lambda d: d.update(colour="blue"))
    _plan(data)["note"] = {"text": "x"}
    _pin(data)["checked_at"] = 5

    assert parse_document(data) == parse_document(DOCUMENT)


def test_project_document_document_json_is_read_back_equal() -> None:
    """What a writer sets is what a reader reads."""
    document = parse_document(DOCUMENT)

    assert parse_document(document_json(document)) == document


def test_project_document_change_keeps_members_it_does_not_know(
    tmp_path: Path,
) -> None:
    """A change rewrites the file with every member it does not know."""
    data = _changed(lambda d: d.update(colour="blue"))
    _plan(data)["note"] = {"text": "x"}
    _pin(data)["checked_at"] = 5
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data), encoding="utf-8")

    changed = change_project_file(tmp_path, lambda raw: raw.update(name="Raba 2"))

    written = json.loads((tmp_path / PROJECT_FILE).read_text(encoding="utf-8"))
    assert changed.name == "Raba 2" == read_project_file(tmp_path).name
    assert written["colour"] == "blue"
    assert written["groups"][0]["note"] == {"text": "x"}
    assert written["groups"][0]["pins"][0]["checked_at"] == 5
