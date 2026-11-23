"""Producer plugins and their adapters."""

from archiwista.messages import Text

MESSAGES = {
    "unavailable": Text(
        "The data source is unavailable.",
        "Źródło danych jest niedostępne.",
    ),
    "unavailable_producer": Text(
        "Data source {producer} is unavailable",
        "Źródło danych {producer} jest niedostępne",
    ),
    "incompatible_producer": Text(
        (
            "Data source {producer} is incompatible: installed version {version},"
            " supported {supported}"
        ),
        (
            "Źródło danych {producer} jest niezgodne: zainstalowana wersja {version},"
            " wspierane {supported}"
        ),
    ),
    "kartograf_not_store": Text(
        (
            "the directory holds other files and no Kartograf store — point to the"
            " store root, the directory that holds {marker}"
        ),
        (
            "w katalogu są inne pliki, a nie magazyn Kartografa — wskaż katalog"
            " główny magazynu, czyli ten z plikiem {marker}"
        ),
    ),
    "no_marker": Text(
        (
            "the directory has the layout of a Kartograf store but no {marker}"
            " — mark the store with: kartograf store init --root {path}"
        ),
        (
            "katalog ma układ magazynu Kartografa, ale nie ma pliku {marker}"
            " — zaznacz magazyn poleceniem: kartograf store init --root {path}"
        ),
    ),
    "obserwator_no_marker": Text(
        (
            "the directory has the layout of an Obserwator root but no {marker}"
            " marker — mark it with: {hint}"
        ),
        (
            "w katalogu jest układ katalogu Obserwatora, ale brak znacznika"
            " {marker} — zaznacz go poleceniem: {hint}"
        ),
    ),
    "obserwator_unsupported_marker": Text(
        (
            "the {marker} marker is not supported: schema {found}, this version of"
            " Archiwista reads {expected}"
        ),
        (
            "znacznik {marker} nie jest obsługiwany: schemat {found}, ta wersja"
            " Archiwisty czyta {expected}"
        ),
    ),
    "obserwator_foreign_store": Text(
        (
            "the directory holds the marker {marker}: it is the store of another"
            " producer, not of Obserwator"
        ),
        (
            "w katalogu jest znacznik {marker}: to magazyn innego producenta, nie"
            " Obserwatora"
        ),
    ),
    "obserwator_not_store": Text(
        (
            "this is not a root of an Obserwator store — point to the directory that"
            " holds {marker}"
        ),
        ("to nie jest katalog magazynu Obserwatora — wskaż katalog z plikiem {marker}"),
    ),
    "obserwator_found_data_root": Text(
        (
            "this is Obserwator's data root (it holds {found}); the raw root holds"
            " {expected} — enter this directory as the store's Obserwator data root"
        ),
        (
            "to katalog danych Obserwatora (jest w nim {found}); katalog surowy ma"
            " plik {expected} — wpisz ten katalog jako katalog danych Obserwatora"
        ),
    ),
    "obserwator_found_raw_root": Text(
        (
            "this is Obserwator's raw root or a store written before its data root"
            " and not yet split (it holds {found}); the data root holds {expected} —"
            " enter this directory as the store's Obserwator raw root, or split the"
            ' store as "Splitting a store" of Obserwator\'s docs/USAGE.md says'
        ),
        (
            "to katalog surowy Obserwatora albo magazyn zapisany przed katalogiem"
            " danych i jeszcze nierozdzielony (jest w nim {found}); katalog danych"
            " ma plik {expected} — wpisz ten katalog jako katalog surowy"
            " Obserwatora albo rozdziel magazyn, jak mówi „Splitting a store” w"
            " docs/USAGE.md Obserwatora"
        ),
    ),
    "obserwator_data_version": Text(
        (
            "Obserwator builds this version in its data root from the raw root"
            " (obserwator {command}); Archiwista downloads into the raw root only"
            " and runs no call of it"
        ),
        (
            "Tę wersję buduje Obserwator w katalogu danych z katalogu surowego"
            " (obserwator {command}); Archiwista pobiera tylko do katalogu"
            " surowego i nie uruchamia jej polecenia"
        ),
    ),
    "obserwator_catalog": Text(
        "Station catalog of {provider}",
        "Katalog stacji {provider}",
    ),
    "obserwator_analyses": Text(
        "Station analyses of {provider}",
        "Analizy stacji {provider}",
    ),
    "obserwator_product_hydro": Text("Hydrological stations", "Stacje hydrologiczne"),
    "obserwator_product_meteo": Text(
        "Meteorological stations", "Stacje meteorologiczne"
    ),
    "obserwator_product_groundwater": Text(
        "Groundwater stations", "Stacje wód podziemnych"
    ),
    "obserwator_product_analyses": Text("Station analyses", "Analizy stacji"),
    "obserwator_series_unit": Text(
        (
            "The series of {dataset} are kept by the unit {unit}, which Archiwista"
            " does not know (it knows days, weeks, months, half-years and hours):"
            " their versions are listed, the coverage of their stations is not read."
        ),
        (
            "Szeregi {dataset} mają jednostkę {unit}, której Archiwista nie zna"
            " (zna dni, tygodnie, miesiące, półrocza i godziny): ich wersje są na"
            " liście, pokrycia ich stacji nie odczytuje."
        ),
    ),
    "obserwator_series_station": Text(
        "The station {station} has no series in the version {version}.",
        "Stacja {station} nie ma szeregu w wersji {version}.",
    ),
    "schema_unknown": Text(
        "unknown",
        "nieznany",
    ),
    "status_not_installed": Text(
        "producer package is not installed",
        "pakiet producenta nie jest zainstalowany",
    ),
    "status_incompatible": Text(
        "incompatible version or schema",
        "niezgodna wersja albo schemat",
    ),
    "status_error": Text(
        "plugin error",
        "błąd wtyczki",
    ),
}
