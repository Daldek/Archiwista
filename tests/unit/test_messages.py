"""Message catalog: both languages of every entry, every call site, no stray Polish."""

import ast
import copy
import json
import pickle
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import archiwista
from archiwista.auth.authorize import ACTIONS
from archiwista.error_document import describe
from archiwista.errors import PreviewUnavailableError
from archiwista.messages import (
    LANGS,
    STORED_LANG,
    Message,
    Text,
    catalogs,
    current_language,
    dump,
    entry,
    join,
    label,
    language,
    load,
    localize,
    localize_json,
    lookup,
    message,
    placeholders,
    valid_key,
    with_detail,
)

SRC = Path(archiwista.__file__).parent
# Polish diacritics or words that no English text uses (also for Polish text that
# has no diacritics, such as "Nieczytelny znacznik").
POLISH = re.compile(
    "[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]"
    r"|\b(?:nie|brak|albo|lub|oraz|jest|dla|musi|gdy|tylko|przez|bez|przy|czy"
    r"|plik\w*|katalog\w*|magazyn\w*|zapis\w*|opcj\w+|wymag\w+|zmienn\w+"
    r"|nieznan\w+|niepoprawn\w+|nieczytel\w+|pobier\w+|odczyt\w*|podaj|uzyj|blad\w*"
    r"|obszar\w*|projekt\w*|zadani\w+|podgl\w+)\b",
    re.IGNORECASE,
)
SCOPES = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
# Last segment of a dotted literal that is a file name, not a message key.
_FILE_SUFFIXES = frozenset({"json", "geojson", "gpkg", "html", "sqlite", "toml", "zip"})
# Dotted literals of the project that no catalog owns: permission actions and the
# name of an audit entity.
_NOT_KEYS = frozenset({*ACTIONS, "project.access"})
# Entries whose two languages read alike: a loan word, a code or a bare composition.
_SAME_WORDS = frozenset(
    {
        "cli.own_problem",
        "cli.problem_line",
        "cli.version_title",
        "compare.field_sha256",
        "doctor.level_ok",
        "preview.kind_raster",
        "role.admin",
    }
)
# Modules whose Polish is a table of names, not a message: the catalog of the
# registry page (generated from the Nogat registry), and the legend names of the
# class tables of previews (the interface is Polish; the producers' codes stay).
_NAME_TABLES = frozenset(
    {
        "_errors.py",
        "previews/classes.py",
        "previews/renderers/points.py",
    }
)
# Polish that is data: a name, a stored key, a letter of the search folding or an
# example value of the OpenAPI document. Each entry must still occur in its module.
_DATA = frozenset(
    {
        ("api/admin.py", "Dział hydrologii"),
        ("api/jobs.py", "/mnt/nas/projekty/archiwum"),
        ("api/models.py", "/mnt/nas/projekty"),
        ("api/models.py", "Główny Urząd Geodezji i Kartografii"),
        ("api/models.py", "Zespół"),
        ("api/models.py", "Sheet code (godło)."),
        ("api/models_layers.py", "Kraków"),
        ("api/models_layers.py", "po odbiorze przyłączy"),
        ("config.py", "OSM GUGiK szary (tylko Polska)"),
        ("index/queries.py", "ł"),
        ("index/queries.py", "Ł"),
        ("index/writer.py", "ł"),
        ("index/writer.py", "Ł"),
        ("index/writer.py", "projekt"),
    }
)


def sources() -> Iterator[tuple[str, ast.Module]]:
    """Yield every module of the package outside the area catalogs, parsed."""
    for path in sorted(SRC.rglob("*.py")):
        name = path.relative_to(SRC).as_posix()
        if not name.startswith("messages/") or name == "messages/__init__.py":
            yield name, ast.parse(path.read_text(encoding="utf-8"))


def entries() -> list[tuple[str, Text]]:
    """Return every catalog entry with its key."""
    return [
        (f"{area}.{name}", text)
        for area, catalog in catalogs().items()
        for name, text in catalog.items()
    ]


def string_values(tree: ast.AST) -> Iterator[str]:
    """Yield the string constants that are neither docstrings nor f-string parts."""
    skipped = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, SCOPES) and node.body and isinstance(node.body[0], ast.Expr)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            skipped |= {id(part) for part in node.values}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skipped
        ):
            yield node.value


def key_pattern(node: ast.expr) -> re.Pattern[str] | None:
    """Return the keys that an f-string such as ``f"job.state_{x}"`` can name."""
    if not isinstance(node, ast.JoinedStr):
        return None
    first = node.values[0] if node.values else None
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return None
    parts = [
        re.escape(str(part.value))
        if isinstance(part, ast.Constant)
        else "[a-z][a-z0-9_]*"
        for part in node.values
    ]
    return re.compile("".join(parts))


def calls(*names: str) -> Iterator[tuple[str, ast.Call]]:
    """Yield every call of a function with one of these names."""
    for source, tree in sources():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in names
            ):
                yield source, node


def label_prefixes() -> set[str]:
    """Return the literal prefixes that ``label`` calls name."""
    return {
        call.args[0].value
        for _, call in calls("label")
        if isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }


def used_keys(known: set[str]) -> set[str]:
    """Return the entries named by a literal, an f-string pattern or a label prefix."""
    used: set[str] = set()
    for _, tree in sources():
        used.update(string_values(tree))
        for node in ast.walk(tree):
            pattern = key_pattern(node) if isinstance(node, ast.JoinedStr) else None
            if pattern is not None:
                used |= {key for key in known if pattern.fullmatch(key)}
    for prefix in label_prefixes():
        used |= {key for key in known if key.startswith(f"{prefix}_")}
    return used & known


# --------------------------------------------------------------------------
# The catalogs
# --------------------------------------------------------------------------


def test_every_entry_has_both_languages_with_the_same_placeholders() -> None:
    """A text and its translation take the same values and differ unless they must."""
    problems = []
    for key, text in entries():
        if not valid_key(key):
            problems.append(f"{key}: not <area>.<name> in snake_case")
        for lang in LANGS:
            if not getattr(text, lang).strip():
                problems.append(f"{key}: empty {lang} text")
        try:
            english, polish = placeholders(text.en), placeholders(text.pl)
        except ValueError as error:
            problems.append(f"{key}: {error}")
            continue
        if english != polish:
            problems.append(
                f"{key}: placeholders {sorted(english)} != {sorted(polish)}"
            )
        if "lang" in english:
            problems.append(f"{key}: a placeholder is called lang")
        if text.en == text.pl and key not in _SAME_WORDS:
            words = re.sub(r"\{[^}]*\}", " ", text.en)
            if re.search(r"[^\W\d_]", words):
                problems.append(f"{key}: the Polish text is the English one")
    assert not problems, "\n".join(problems)


def test_every_call_names_an_entry_and_gives_exactly_its_placeholders() -> None:
    """A call with a literal key names an entry and passes one value per placeholder."""
    known = {key: placeholders(text.en) for key, text in entries()}
    problems = []
    for source, call in calls("message"):
        where = f"{source}:{call.lineno}"
        first = call.args[0]
        if len(call.args) > 2:
            problems.append(f"{where}: positional arguments after the language")
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if first.value not in known:
                problems.append(f"{where}: unknown key {first.value!r}")
            elif all(keyword.arg for keyword in call.keywords):
                given = {keyword.arg for keyword in call.keywords}
                if given != known[first.value]:
                    wants = sorted(known[first.value])
                    problems.append(f"{where}: {first.value} wants {wants}")
            continue
        pattern = key_pattern(first)
        if pattern is not None and not any(pattern.fullmatch(key) for key in known):
            problems.append(f"{where}: no entry matches {pattern.pattern}")
        # Any other key is chosen at run time, e.g. from a table.
    assert not problems, "\n".join(problems)


def test_no_entry_is_unused_and_no_key_like_literal_is_misspelled() -> None:
    """Every entry has a user, and a literal that looks like a key names an entry."""
    known = {key for key, _ in entries()}
    areas = set(catalogs())
    prefixes = {f"{prefix}_" for prefix in label_prefixes()}
    literals = {
        value
        for _, tree in sources()
        for value in string_values(tree)
        if valid_key(value)
    }
    misspelled = sorted(
        value
        for value in literals - known
        if value.split(".")[0] in areas
        and value.rsplit(".", 1)[-1] not in _FILE_SUFFIXES
        and value not in _NOT_KEYS
        and f"{value}_" not in prefixes
        and not any(key.startswith(f"{value}_") for key in known)
    )
    unused = sorted(known - used_keys(known))
    assert not unused, f"entries nobody uses: {unused}"
    assert not misspelled, f"literals that look like keys of a catalog: {misspelled}"


def test_entries_that_are_read_without_values_have_no_placeholders() -> None:
    """A help text, a label and a looked-up name are rendered without any value."""
    known = {key: placeholders(text.en) for key, text in entries()}
    plain = {key for key in known if key.endswith("_help")}
    for prefix in label_prefixes():
        plain |= {key for key in known if key.startswith(f"{prefix}_")}
    for _, call in calls("lookup"):
        pattern = key_pattern(call.args[0])
        if pattern is not None:
            plain |= {key for key in known if pattern.fullmatch(key)}
    assert sorted(key for key in plain if known[key]) == []


def test_polish_literals_stay_only_in_the_catalog() -> None:
    """No text for a person is written outside the catalog; names are listed."""
    found = {
        (name, value)
        for name, tree in sources()
        if name not in _NAME_TABLES
        for value in string_values(tree)
        if POLISH.search(value)
    }
    assert sorted(found - _DATA) == [], "a Polish text belongs in archiwista.messages"
    assert sorted(_DATA - found) == [], "a name that is no longer in its module"


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def test_a_message_remembers_its_key_and_values() -> None:
    """A message is its text, and also its key, language and placeholder values."""
    text = message("job.state_queued", "en")

    assert isinstance(text, str)
    assert text == "queued"
    assert (text.key, text.lang, dict(text.params)) == ("job.state_queued", "en", {})
    values = message("api.version_unknown", "en", version="2024", store="main")
    assert dict(values.params) == {"version": "2024", "store": "main"}
    assert values == 'The index does not know version "2024" in store "main".'


def test_localized_renders_the_same_key_and_values_in_the_other_language() -> None:
    """The same message in another language needs no parsing of its text."""
    text = message("api.version_unknown", "en", version="2024", store="main")

    polish = text.localized("pl")

    assert polish == "Indeks nie zna wersji „2024” w magazynie „main”."
    assert polish.lang == "pl"
    assert polish.localized("en") == text
    assert text.localized("en") is text


def test_a_message_among_the_values_is_rendered_in_the_language_of_its_parent() -> None:
    """A text built from fragments stays translatable."""
    nested = message("job.state_queued", "en")
    text = message("cli.store_job", "en", kind="scan", state=nested)

    assert text == " Job: scan, queued."
    assert text.localized("pl") == " Zadanie: scan, w kolejce."


def test_operations_on_a_message_give_plain_text_but_copies_keep_it_translatable() -> (
    None
):
    """Joining makes a plain string; copying and pickling keep the message."""
    text = message("job.state_queued", "en")

    assert type(f"{text}!") is str
    assert type(text + "!") is str
    for clone in (
        copy.deepcopy(text),
        pickle.loads(pickle.dumps(text)),
        pickle.loads(pickle.dumps(text.localized("pl"))),
    ):
        assert isinstance(clone, Message)
        assert clone.key == text.key
        assert clone.localized("pl") == "w kolejce"


def test_localize_changes_only_catalog_messages() -> None:
    """A foreign text or a name passes unchanged; a message becomes a plain string."""
    text = message("job.state_queued", "en")

    assert localize(text, "pl") == "w kolejce"
    assert type(localize(text, "pl")) is str
    assert localize("Nie znaleziono", "en") == "Nie znaleziono"
    assert localize("plain text", "pl") == "plain text"


def test_a_message_outside_any_language_context_is_english() -> None:
    """English is the language of the API without a header and of ``--json``."""
    assert message("job.state_queued") == "queued"
    assert STORED_LANG == "pl"


def test_localize_json_renders_every_message_inside_a_json_value() -> None:
    """The details of a problem hold messages among names and numbers."""
    queued = message("job.state_queued", "en")
    value: dict[str, Any] = {
        "reason": "x",
        "items": [
            {"message": queued, "count": 2},
            (message("job.state_running", "en"), None),
        ],
    }

    shown = localize_json(value, "pl")

    assert shown == {
        "reason": "x",
        "items": [{"message": "w kolejce", "count": 2}, ["trwa", None]],
    }
    assert type(shown["items"][0]["message"]) is str
    assert value["items"][0]["message"] is queued  # the argument is not changed


def test_dump_and_load_keep_a_message_translatable_through_json() -> None:
    """A job's error keeps key and values, nested messages and a path included."""
    text = message(
        "cli.store_job", "en", kind="scan", state=message("job.state_queued", "en")
    )
    dumped = dump(text)
    assert dumped is not None
    key, values = dumped

    stored = json.loads(json.dumps({"key": key, "values": values}))
    restored = load(stored["key"], stored["values"], str(text))

    assert key == "cli.store_job"
    assert values == {
        "kind": "scan",
        "state": {"key": "job.state_queued", "values": {}},
    }
    assert isinstance(restored, Message) and restored == text
    assert restored.localized("pl") == " Zadanie: scan, w kolejce."
    unreadable = dump(message("store.unreadable", "en", path=Path("/mnt/nas")))
    assert unreadable is not None and unreadable[1] == {"path": "/mnt/nas"}
    assert dump("plain text") is None


def test_load_gives_the_stored_text_back_when_the_catalog_forgot_the_message() -> None:
    """A message of an older version or a damaged row never raises."""
    assert load("job.no_such_message", {}, "Stary tekst.") == "Stary tekst."
    assert load("api.version_unknown", {"version": "1"}, "Stary.") == "Stary."
    assert load(None, None, "Stary tekst.") == "Stary tekst."
    assert load("job.state_queued", ["a", "list"], "Stary tekst.") == "Stary tekst."


def test_join_keeps_messages_translatable_and_plain_texts_as_they_are() -> None:
    """Several texts become one, rendered together in one language."""
    queued = message("job.state_queued", "en")

    text = join([queued, "plain", message("job.state_running", "en")])

    assert (join([]), join(["alone"])) == ("", "alone")
    assert text == "queued; plain; running"
    assert isinstance(text, Message)
    assert text.localized("pl") == "w kolejce; plain; trwa"


def test_the_language_of_a_call_is_its_argument_else_its_context() -> None:
    """``language`` sets the default of a block; an argument overrides it."""
    outside = current_language()

    with language("pl"):
        assert current_language() == "pl"
        assert message("job.state_queued").lang == "pl"
        assert message("job.state_queued", "en").lang == "en"
        with language("en"):
            assert message("job.state_queued") == "queued"
        assert current_language() == "pl"

    assert current_language() == outside
    with pytest.raises(ValueError, match="allowed"), language("de"):  # type: ignore[arg-type]
        pass


def test_a_wrong_key_or_language_is_a_program_error() -> None:
    """A key that is no entry, a missing value and an unknown language raise."""
    with pytest.raises(KeyError):
        message("job.no_such_message")
    with pytest.raises(KeyError):
        message("no_such_area.title")
    with pytest.raises(KeyError):
        message("job")
    with pytest.raises(KeyError):
        message("api.version_unknown", "en", version="1")  # a value is missing
    with pytest.raises(ValueError, match="allowed"):
        message("job.state_queued", "de")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        placeholders("{0}")
    with pytest.raises(ValueError):
        placeholders("{value.name}")
    assert placeholders("{a} {b!r:>5} {c:sentence} {{literal}}") == {"a", "b", "c"}
    assert entry("job.state_queued") == Text("queued", "w kolejce")


def test_lookup_and_label_name_a_value_by_its_entry_else_by_itself() -> None:
    """A value without an entry is its own name."""
    assert lookup("job.state_queued", "x", "en") == "queued"
    assert lookup("job.state_no_such_state", "x") == "x"
    assert lookup("no_such_area.state_queued", "x") == "x"
    with language("en"):
        assert label("job.state", "queued") == "queued"
        assert label("job.state", "no_such_state") == "no_such_state"


@pytest.mark.parametrize(
    ("text", "detail", "expected"),
    [
        (
            "Cannot read the store /data",
            "no access",
            "Cannot read the store /data: no access",
        ),
        # A whole sentence stays one: its full stop moves after the detail.
        (
            "Cannot read the file.",
            "not a TIFF file",
            "Cannot read the file: not a TIFF file.",
        ),
        # A detail ending its own sentence gets no second full stop.
        (
            "Cannot read the file.",
            "TIFFReadDirectory failed.",
            "Cannot read the file: TIFFReadDirectory failed.",
        ),
        ("Cannot read the file.", None, "Cannot read the file."),
        ("Cannot read the file.", "", "Cannot read the file."),
    ],
)
def test_with_detail_never_puts_colon_after_full_stop(
    text: str, detail: str | None, expected: str
) -> None:
    """The detail follows a colon, never ``….: …``."""
    assert with_detail(text, detail) == expected


def test_with_detail_keeps_a_message_translatable() -> None:
    """A message with a detail renders in another language as a whole."""
    sentence = message("preview.reason_unreadable", "en")

    text = with_detail(sentence, "not a TIFF file")

    assert text == "The file cannot be read: not a TIFF file."
    assert isinstance(text, Message)
    assert text.localized("pl") == "Nie można odczytać pliku: not a TIFF file."


def test_preview_problem_detail_explains_reason_before_fix() -> None:
    """A file without a preview: reason, the library's detail, then the fix."""
    problem = describe(PreviewUnavailableError("unreadable", "not a TIFF file"))

    reason = message("preview.reason_unreadable").removesuffix(".")
    assert problem.detail == (
        f"{reason}: not a TIFF file. {message('preview.fix_unreadable')}"
    )
