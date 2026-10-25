"""Registration problems of producer plugins."""

from archiwista.messages import Text

MESSAGES = {
    "unregistered": Text(
        "no plugin for this producer",
        "brak wtyczki tego producenta",
    ),
    "duplicate": Text(
        "plugin registered more than once: {values}",
        "wtyczka zarejestrowana więcej niż raz: {values}",
    ),
    "module_missing": Text(
        "missing module {module}",
        "brak modułu {module}",
    ),
    "package_missing": Text(
        "missing package {package}",
        "brak pakietu {package}",
    ),
    "not_adapter": Text(
        "the plugin factory did not return a data source adapter",
        "fabryka wtyczki nie zwróciła adaptera źródła",
    ),
    "wrong_producer": Text(
        'the plugin adapter declares producer "{declared}"',
        "adapter wtyczki deklaruje producenta „{declared}”",
    ),
}
