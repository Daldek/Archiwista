"""The command ``archiwista reindex``."""

from archiwista.messages import Text

MESSAGES = {
    "failed": Text(
        "Cannot rebuild the index",
        "Nie można przebudować indeksu",
    ),
    "no_stores": Text(
        (
            'No store is configured — add one in the wizard after running "archiwista'
            ' serve".'
        ),
        (
            "Nie skonfigurowano żadnego magazynu — dodaj go w kreatorze po"
            " uruchomieniu „archiwista serve”."
        ),
    ),
    "started": Text(
        'Store "{store}": full scan, job {job}.',
        "Magazyn „{store}”: pełny skan, zadanie {job}.",
    ),
    "progress": Text(
        'Store "{store}": segments {current} of {total}, entries {entries}.',
        "Magazyn „{store}”: segmenty {current} z {total}, wpisy {entries}.",
    ),
    "notice": Text(
        'Store "{store}": {message}',
        "Magazyn „{store}”: {message}",
    ),
    "cancelling": Text(
        "Cancelling job {job}…",
        "Przerywanie zadania {job}…",
    ),
    "succeeded": Text(
        (
            'Store "{store}": full scan finished in {seconds} s — entries {entries},'
            " versions saved {versions}, new missing {missing}, removed {removed}."
        ),
        (
            "Magazyn „{store}”: pełny skan zakończony w {seconds} s — wpisy {entries},"
            " zapisane wersje {versions}, nowe braki {missing}, usunięte {removed}."
        ),
    ),
    "job_failed": Text(
        'Store "{store}": job {job} — {state}: {detail}',
        "Magazyn „{store}”: zadanie {job} — {state}: {detail}",
    ),
    "error": Text(
        "{message} (code {code})",
        "{message} (kod {code})",
    ),
}
