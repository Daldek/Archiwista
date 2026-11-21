"""Texts shared by every area."""

from archiwista.messages import Text

MESSAGES = {
    "joined": Text(
        "{head}; {tail}",
        "{head}; {tail}",
    ),
    "with_detail": Text(
        "{message}: {detail}",
        "{message}: {detail}",
    ),
    "with_detail_sentence": Text(
        "{message:sentence}: {detail}{end}",
        "{message:sentence}: {detail}{end}",
    ),
    # A provider's name for a person, looked up by its id in lower case
    # (Nogat ECO-082: the id is `IMGW` or `CHMU`, the text keeps the institute's
    # acronym); an id without an entry is shown as it is.
    "provider_imgw": Text("IMGW-PIB", "IMGW-PIB"),
    "provider_chmu": Text("ČHMÚ", "ČHMÚ"),
}
