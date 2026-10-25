"""Producers' commands as data: the refusals Archiwista adds to the producers'."""

from archiwista.messages import Text

MESSAGES = {
    "no_check": Text(
        (
            'The command "{command}" of the source {producer} has no plan without'
            " effects: it cannot be checked."
        ),
        (
            "Polecenie „{command}” źródła {producer} nie ma planu bez skutków: nie"
            " można go sprawdzić."
        ),
    ),
    "no_commands": Text(
        "The source {producer} offers no commands.",
        "Źródło {producer} nie udostępnia poleceń.",
    ),
    "no_plan": Text(
        'The source {producer} gives no plan of "{command}" in a store.',
        "Źródło {producer} nie podaje planu polecenia „{command}” w magazynie.",
    ),
    "no_store": Text(
        (
            'The command "{command}" of the source {producer} works on no store:'
            " it is not run as a job."
        ),
        (
            "Polecenie „{command}” źródła {producer} nie działa na magazynie: nie"
            " uruchamia się go jako zadania."
        ),
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
