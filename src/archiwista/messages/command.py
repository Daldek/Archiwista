"""Producers' commands as data: the refusals Archiwista adds to the producers'."""

from archiwista.messages import Text

MESSAGES = {
    "no_commands": Text(
        "The source {producer} offers no commands.",
        "Źródło {producer} nie udostępnia poleceń.",
    ),
    "path_option": Text(
        (
            "Archiwista passes no file path of a request to a producer, which would"
            " open it on the server: option {option}."
        ),
        (
            "Archiwista nie przekazuje producentowi ścieżki pliku z żądania, bo"
            " producent otworzyłby ją na serwerze: opcja {option}."
        ),
    ),
    "path_option_hint": Text(
        "Leave the option out of the request.",
        "Pomiń tę opcję w żądaniu.",
    ),
    "store_required": Text(
        "The command {command} works on a store: name the store.",
        "Polecenie {command} działa na magazynie: podaj magazyn.",
    ),
    "store_without_producer": Text(
        'The store "{store}" has no directory of the source {producer}.',
        "Magazyn „{store}” nie ma katalogu źródła {producer}.",
    ),
    "unknown": Text(
        'The source {producer} has no command "{command}".',
        "Źródło {producer} nie ma polecenia „{command}”.",
    ),
}
