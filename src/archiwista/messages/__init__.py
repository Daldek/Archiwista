"""Message catalog: every text for a person has an English variant and a Polish one.

A catalog is the module ``archiwista.messages.<area>``; its mapping ``MESSAGES``
holds a `Text` per name, so a text and its translation are edited together
(DEV-2.3). The key of a message is ``<area>.<name>`` in snake_case
(``job.offline_mode``). `message` renders a key with the values of its
placeholders and returns a `Message`: the text as a ``str`` that also remembers
its key and values, so an adapter can render the same message again in the
language of its caller (`Message.localized`, `localize`) instead of parsing
text.

The language of a call is its ``lang`` argument, else the language of the
running context (`language`, `current_language`); it is English until a
context chooses another one. The API chooses the language of a request from
its ``Accept-Language`` (English without it), the command line Polish for the
person and English under ``--json`` (machine output, AGI-9.2). A text that is
stored (the status of a store, the notices and the error of a job) is written
in `STORED_LANG`, and a job keeps the key and values of its error beside it.

A template is ``str.format`` text with named placeholders; a brace that is text
is written ``{{`` or ``}}``, and the spec ``:sentence`` of a field drops a
closing full stop of its value (`with_detail`). A message among the values of
another one is rendered in the language of its parent, so a text built from
fragments stays translatable.

Raise sites, notices and output lines call `message` with the key as a literal
and one keyword per placeholder; ``tests/unit/test_messages.py`` checks every
call against its catalog entry (the key exists and the keywords are the
placeholders), both languages of every entry and the absence of Polish
literals outside this package. A key that is chosen at run time is built as
``f"<area>.<prefix>_{value}"`` (`label`, `lookup`).

Texts leave the process or the request in two ways that keep them
translatable: `localize` and `localize_json` render a `Message`, or every one
inside a JSON-like value, in the language of the receiver (an error document,
a problem), and `dump` and `load` write the key and values of a `Message` into
a JSON document and read them back (a job's error, a worker's answer).
"""

import importlib
import pkgutil
import re
import string
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache
from types import MappingProxyType
from typing import Any, Literal, NamedTuple, Self, cast

__all__ = [
    "DEFAULT_LANG",
    "LANGS",
    "Lang",
    "Message",
    "STORED_LANG",
    "Text",
    "catalogs",
    "current_language",
    "dump",
    "entry",
    "join",
    "label",
    "language",
    "load",
    "localize",
    "localize_json",
    "lookup",
    "message",
    "placeholders",
    "valid_key",
    "with_detail",
]

type Lang = Literal["en", "pl"]
LANGS: tuple[Lang, ...] = ("en", "pl")
"""The languages of the catalogs."""
DEFAULT_LANG: Lang = "en"
"""Language of a call that no context gave another one."""
STORED_LANG: Lang = "pl"
"""Language of the texts that are stored, which are read later by anyone."""

_KEY = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_AREA = re.compile(r"[a-z][a-z0-9_]*")
_SENTENCE_ENDS = (".", "!", "?", "…")
_LANGUAGE: ContextVar[Lang] = ContextVar("archiwista_language", default=DEFAULT_LANG)


class _Formatter(string.Formatter):
    """``str.format`` with the spec ``sentence`` for the value of a field."""

    def format_field(self, value: object, format_spec: str) -> str:
        if format_spec == "sentence":
            return str(value).removesuffix(".")
        return str(super().format_field(value, format_spec))


_FORMATTER = _Formatter()


class Text(NamedTuple):
    """One catalog entry: the English variant and the Polish one.

    Attributes
    ----------
    en : str
        English template, ``str.format`` syntax with named placeholders
        (``{name}``); a brace that is text is written ``{{`` or ``}}``.
    pl : str
        Polish template with exactly the placeholders of ``en``.
    """

    en: str
    pl: str


class Message(str):
    """A catalog text in one language that remembers its key and placeholder values.

    It is a ``str`` (the rendered text), so it can be compared, joined,
    serialised and passed wherever text is expected. Operations that build
    another string from it (``+``, an f-string, ``str.join``) give a plain
    ``str`` in the language of this message; pass a `Message` as a value of a
    placeholder of another message to keep it translatable.

    Attributes
    ----------
    key : str
        Catalog key ``<area>.<name>``.
    params : Mapping[str, object]
        The values of the placeholders (a `Message` among them is rendered
        again with its parent).
    lang : {"en", "pl"}
        Language of the text.
    """

    __slots__ = ("key", "lang", "params")

    key: str
    params: Mapping[str, object]
    lang: Lang

    def __new__(
        cls, text: str, key: str, params: Mapping[str, object], lang: Lang
    ) -> Self:
        """Wrap the rendered ``text`` of ``key`` in ``lang``."""
        instance = super().__new__(cls, text)
        instance.key = key
        instance.params = MappingProxyType(dict(params))
        instance.lang = lang
        return instance

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle and copy a message through its key, so it renders anew."""
        return (_restore, (self.key, self.lang, dict(self.params)))

    def localized(self, lang: Lang) -> "Message":
        """Render the message again in ``lang``.

        Parameters
        ----------
        lang : {"en", "pl"}
            Target language.

        Returns
        -------
        Message
            The same key with the same values in ``lang`` (this message when
            it already is in ``lang``); a `Message` among the values is
            rendered in ``lang`` too.
        """
        if lang == self.lang:
            return self
        return message(self.key, lang, **self.params)


def _restore(key: str, lang: Lang, params: dict[str, object]) -> Message:
    return message(key, lang, **params)


@cache
def _catalog(area: str) -> Mapping[str, Text]:
    if _AREA.fullmatch(area) is None:
        raise KeyError(f"Not a message area: {area!r}")
    try:
        module = importlib.import_module(f"{__name__}.{area}")
    except ModuleNotFoundError as error:
        if error.name != f"{__name__}.{area}":
            raise
        raise KeyError(f"No message catalog for the area {area!r}") from None
    return cast("Mapping[str, Text]", module.MESSAGES)


def current_language() -> Lang:
    """Return the language that a call without ``lang`` renders in."""
    return _LANGUAGE.get()


@contextmanager
def language(lang: Lang) -> Iterator[None]:
    """Render the calls of a block without ``lang`` in ``lang``.

    Parameters
    ----------
    lang : {"en", "pl"}
        The language of the block.

    Raises
    ------
    ValueError
        If ``lang`` is not a catalog language.
    """
    if lang not in LANGS:
        raise ValueError(f"Unknown message language {lang!r}; allowed: {LANGS}")
    token = _LANGUAGE.set(lang)
    try:
        yield
    finally:
        _LANGUAGE.reset(token)


def entry(key: str, /) -> Text:
    """Return the catalog entry of ``key``: its English and Polish templates.

    Raises
    ------
    KeyError
        If the area or the name is not in the catalogs.
    """
    area, _, name = key.partition(".")
    try:
        return _catalog(area)[name]
    except KeyError:
        raise KeyError(f"Unknown message key {key!r}") from None


def message(key: str, lang: Lang | None = None, /, **params: object) -> Message:
    """Render the catalog message ``key`` in ``lang``.

    Parameters
    ----------
    key : str
        ``<area>.<name>`` of an entry of the catalog
        ``archiwista.messages.<area>``.
    lang : {"en", "pl"} or None, optional
        Language of the text (positional); the language of the running
        context by default.
    **params : object
        Values of the placeholders of the template.

    Returns
    -------
    Message
        The text with its key and values.

    Raises
    ------
    KeyError
        If the area or the name is not in the catalogs, or a placeholder has
        no value (a program error).
    ValueError
        If ``lang`` is not a catalog language.
    """
    text = entry(key)
    chosen = _LANGUAGE.get() if lang is None else lang
    if chosen not in LANGS:
        raise ValueError(f"Unknown message language {chosen!r}; allowed: {LANGS}")
    template = text.pl if chosen == "pl" else text.en
    values = {
        name: value.localized(chosen) if isinstance(value, Message) else value
        for name, value in params.items()
    }
    return Message(_FORMATTER.vformat(template, (), values), key, values, chosen)


def lookup(key: str, default: str, /, lang: Lang | None = None) -> str:
    """Return the message ``key`` without placeholders, or ``default``.

    For a key that is built at run time from a value that may have no text
    (a preview reason, a state): the value itself is the default.

    Parameters
    ----------
    key : str
        ``<area>.<name>``.
    default : str
        What to return when the catalogs have no such entry.
    lang : {"en", "pl"} or None, optional
        Language of the text; the language of the running context by default.
    """
    area, _, name = key.partition(".")
    try:
        found = _catalog(area).get(name)
    except KeyError:
        return default
    return default if found is None else message(key, lang)


def label(prefix: str, value: str, /) -> str:
    """Return the name of ``value`` in the entries ``<prefix>_<value>``.

    Parameters
    ----------
    prefix : str
        ``<area>.<name prefix>``, e.g. ``job.state`` for ``job.state_failed``.
    value : str
        The value; it is the name itself when no entry has one.
    """
    return lookup(f"{prefix}_{value}", value)


def join(texts: Sequence[str]) -> str:
    """Join texts with ``; ``; a `Message` among them stays translatable.

    Parameters
    ----------
    texts : Sequence[str]
        The texts, `Message` or any string.

    Returns
    -------
    str
        The first text for one, a message that holds the rest as values for
        several (rendered together, in one language), ``""`` for none.
    """
    joined = texts[0] if texts else ""
    for text in texts[1:]:
        joined = message("common.joined", head=joined, tail=text)
    return joined


def localize(text: str, lang: Lang) -> str:
    """Return ``text`` in ``lang`` when it is a catalog message.

    Parameters
    ----------
    text : str
        A `Message`, or any other string (a foreign error text, a name).
    lang : {"en", "pl"}
        Target language.

    Returns
    -------
    str
        The message rendered in ``lang`` as a plain string (a final text,
        which a later conversion must not render again); another string
        unchanged.
    """
    return str(text.localized(lang)) if isinstance(text, Message) else text


def localize_json(value: object, lang: Lang) -> Any:
    """Return ``value`` with every catalog message inside it rendered in ``lang``.

    Parameters
    ----------
    value : object
        A JSON-like value: a `Message` or another string, a number, ``None``, a
        mapping or a list or tuple of such values (the ``details`` of a
        problem).
    lang : {"en", "pl"}
        Target language.

    Returns
    -------
    Any
        A copy: a mapping is a dict, a list or tuple a list and a message a
        plain string in ``lang``; anything else is returned as it is.
    """
    if isinstance(value, Message):
        return str(value.localized(lang))
    if isinstance(value, Mapping):
        return {key: localize_json(item, lang) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [localize_json(item, lang) for item in value]
    return value


def dump(text: str) -> tuple[str, dict[str, object]] | None:
    """Return the key and values of a `Message` as JSON, to keep it translatable.

    Parameters
    ----------
    text : str
        A `Message`, or any other string.

    Returns
    -------
    tuple[str, dict[str, object]] or None
        The key and the values of the message, with a message among them as
        ``{"key": …, "values": …}`` and any other value that JSON has no type
        for as its text; ``None`` for a string that is no `Message`.
    """
    if not isinstance(text, Message):
        return None
    return text.key, _dump_values(text.params)


def _dump_values(params: Mapping[str, object]) -> dict[str, object]:
    return {name: _dump_value(value) for name, value in params.items()}


def _dump_value(value: object) -> object:
    if isinstance(value, Message):
        return {"key": value.key, "values": _dump_values(value.params)}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def load(key: object, values: object, text: str) -> str:
    """Return the `Message` that `dump` made ``key`` and ``values`` of.

    Parameters
    ----------
    key, values : object
        What `dump` returned (as read from JSON, so not checked).
    text : str
        The text that was stored with them: what is returned when they do not
        name a message of the catalogs any more (a text of an older version).

    Returns
    -------
    str
        The message, in the language of the running context; it renders in
        another language with `localize`.
    """
    if not isinstance(key, str) or not isinstance(values, Mapping):
        return text
    try:
        return message(key, **_load_values(values))
    except (KeyError, ValueError, IndexError):
        return text


def _load_values(values: Mapping[str, object]) -> dict[str, object]:
    return {name: _load_value(value) for name, value in values.items()}


def _load_value(value: object) -> object:
    if (
        isinstance(value, Mapping)
        and value.keys() == {"key", "values"}
        and isinstance(value["key"], str)
        and isinstance(value["values"], Mapping)
    ):
        return message(value["key"], **_load_values(value["values"]))
    return value


def with_detail(text: str, detail: str | None) -> str:
    """Append a producer's or system's own detail text to a message.

    The detail follows a colon. A message that is a whole sentence (a
    preview's reason) stays one: its full stop moves after the detail,
    ``Cannot read the file: <detail>.``, never ``….: …``. A `Message` stays
    translatable: the result is a message that holds it as a value.

    Parameters
    ----------
    text : str
        The message; a `Message` or any string.
    detail : str or None
        The detail, in the language of the library or the system that gave it;
        nothing is appended for ``None`` or an empty one.
    """
    if not detail:
        return text
    lang = text.lang if isinstance(text, Message) else None
    if not text.endswith("."):
        return message("common.with_detail", lang, message=text, detail=detail)
    end = "" if detail.endswith(_SENTENCE_ENDS) else "."
    return message(
        "common.with_detail_sentence", lang, message=text, detail=detail, end=end
    )


def placeholders(template: str) -> frozenset[str]:
    """Return the names of the placeholders of a catalog template.

    Parameters
    ----------
    template : str
        ``str.format`` template.

    Returns
    -------
    frozenset of str
        The field names, without conversions and format specifications.

    Raises
    ------
    ValueError
        If the template is malformed or a field is not a plain name.
    """
    names = set()
    for _, field, _, _ in string.Formatter().parse(template):
        if field is None:
            continue
        if not field.isidentifier():
            raise ValueError(f"Placeholder {field!r} is not a plain name: {template!r}")
        names.add(field)
    return frozenset(names)


@cache
def catalogs() -> Mapping[str, Mapping[str, Text]]:
    """Load every catalog of the package.

    Returns
    -------
    Mapping of str to Mapping of str to Text
        The entries of each area by area name; for tests and tools that check
        or export the catalogs.
    """
    areas = sorted(
        module.name
        for module in pkgutil.iter_modules(__path__)
        if not module.name.startswith("_")
    )
    return MappingProxyType({area: _catalog(area) for area in areas})


def valid_key(key: str) -> bool:
    """Whether ``key`` has the form ``<area>.<name>`` in snake_case."""
    return _KEY.fullmatch(key) is not None
