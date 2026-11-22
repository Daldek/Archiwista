"""Names of the files Archiwista hands to a person (Nogat DEV-19.21, ECO-083).

A file Archiwista names for a person (a REST attachment, a download of the
interface) is ``archiwista_<content>_<qualifiers>.<extension>``: the content
in English, each qualifier after ``_``, a text a person gave (a project's or
an export's name) reduced by `name_slug` as the kit's ``nameSlug`` of
``nogat-handoff.js`` reduces it in the interface. Not covered: a stored file
sent under its own name and a name the person gives (``eksport/<name>.zip``).
"""

import re
import unicodedata

__all__ = ["download_name", "name_slug"]

TOOL = "archiwista"
_OTHER = re.compile(r"[^a-z0-9]+")


def name_slug(text: str) -> str:
    """Return a person's text as a part of a file name.

    Lower-case ASCII without diacritics (``ł`` is ``l``), each run of other
    characters one ``-``, none at either end: ``Nowy Sącz — Q`` gives
    ``nowy-sacz-q``; nothing is left of a text without a letter or a digit.
    """
    folded = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    plain = "".join(char for char in folded if not unicodedata.combining(char))
    return _OTHER.sub("-", plain.lower()).strip("-")


def download_name(content: str, *qualifiers: str, extension: str) -> str:
    """Return ``archiwista_<content>[_<qualifier>…].<extension>``.

    Parameters
    ----------
    content : str
        What the file holds, in English (``log``, ``export``).
    *qualifiers : str
        What tells two such files apart, already in the allowed characters
        (``name_slug`` for a person's text); an empty one is left out.
    extension : str
        The format's own extension, without the dot.
    """
    parts = [TOOL, content, *(part for part in qualifiers if part)]
    return f"{'_'.join(parts)}.{extension}"
