"""Project directories, the project file and its changes."""

from archiwista.messages import Text

MESSAGES = {
    "dir_missing": Text(
        "Project directory does not exist: {path}",
        "Katalog projektów nie istnieje: {path}",
    ),
    "dir_not_directory": Text(
        "Project directory path is not a directory: {path}",
        "Ścieżka katalogu projektów nie jest katalogiem: {path}",
    ),
    "dir_unreadable": Text(
        "No permission to read the project directory: {path}",
        "Brak uprawnień do odczytu katalogu projektów: {path}",
    ),
    "not_discoverable": Text(
        (
            "A scan finds a project at most {depth} levels below a project"
            " directory, outside hidden directories and stores; {path} is no such"
            " place."
        ),
        (
            "Skan znajduje projekt najwyżej {depth} poziomy pod katalogiem"
            " projektów, poza katalogami ukrytymi i magazynami; {path} nie jest"
            " takim miejscem."
        ),
    ),
    "not_found": Text(
        'There is no project "{project}".',
        "Nie ma projektu „{project}”.",
    ),
    "outside_project_dirs": Text(
        (
            "A new project lies in a project directory of the settings or below one"
            " ({dirs}), given as an absolute path: {path}"
        ),
        (
            "Nowy projekt leży w katalogu projektów z ustawień albo pod nim ({dirs}),"
            " podany jako ścieżka bezwzględna: {path}"
        ),
    ),
    "exists": Text(
        "A project file is in {path} already.",
        "W {path} jest już plik projektu.",
    ),
    "file_locked": Text(
        (
            "Another change of the project holds its lock: {owner} ({lock}); try"
            " again later."
        ),
        (
            "Blokadę projektu trzyma inna zmiana: {owner} ({lock}); spróbuj"
            " ponownie później."
        ),
    ),
    "file_locked_ended": Text(
        (
            "The project's lock was left by {owner}, a process of this computer"
            " that has ended ({lock})."
        ),
        (
            "Blokadę projektu zostawił {owner}, proces tego komputera, który się"
            " już zakończył ({lock})."
        ),
    ),
    "lock_owner_unknown": Text(
        "a process that did not name itself",
        "proces, który się nie przedstawił",
    ),
    "file_write_failed": Text(
        "Cannot write the file {path}",
        "Nie można zapisać pliku {path}",
    ),
    "invalid_file": Text(
        "The project file cannot be used: it breaks the rule “{rule}”.",
        "Nie można użyć pliku projektu: łamie regułę „{rule}”.",
    ),
    "invalid_member": Text(
        "The project file cannot be used: {pointer} breaks the rule “{rule}”.",
        "Nie można użyć pliku projektu: {pointer} łamie regułę „{rule}”.",
    ),
    "unsupported_schema": Text(
        "The project file is of a newer format ({schema}) than this Archiwista reads.",
        "Plik projektu ma nowszy format ({schema}), niż czyta ta wersja Archiwisty.",
    ),
    "area_missing": Text(
        "The project's area file does not exist: {path}",
        "Plik obszaru projektu nie istnieje: {path}",
    ),
    "area_changed": Text(
        (
            "The project's area file holds other bytes than the project file"
            " records: {path}"
        ),
        "Plik obszaru projektu ma inną treść, niż zapisano w pliku projektu: {path}",
    ),
    "area_invalid": Text(
        (
            "The project's area file is no polygon of GeoJSON in WGS84 within the"
            " limits: {path}"
        ),
        (
            "Plik obszaru projektu nie jest wielokątem GeoJSON w WGS84 w granicach"
            " limitów: {path}"
        ),
    ),
    "rule_unreadable": Text("a file that can be read", "plik, który da się odczytać"),
    "rule_too_large": Text("at most 32 MiB", "najwyżej 32 MiB"),
    "rule_invalid_json": Text("JSON in UTF-8", "JSON w UTF-8"),
    "rule_path_outside_root": Text(
        "no symbolic link out of the project directories",
        "bez dowiązania symbolicznego poza katalogi projektów",
    ),
    "rule_object": Text("a JSON object", "obiekt JSON"),
    "rule_array": Text("a JSON array", "tablica JSON"),
    "rule_required": Text("a required member", "wymagany element"),
    "rule_schema": Text(
        "archiwista-project/1, or a newer archiwista-project/<n>",
        "archiwista-project/1 albo nowszy archiwista-project/<n>",
    ),
    "rule_name": Text(
        "1 to 200 characters without control characters",
        "od 1 do 200 znaków bez znaków sterujących",
    ),
    "rule_description": Text(
        "text of at most 2,000 characters", "tekst najwyżej 2000 znaków"
    ),
    "rule_time": Text(
        "a UTC time YYYY-MM-DDTHH:MM:SSZ", "czas UTC RRRR-MM-DDTGG:MM:SSZ"
    ),
    "rule_account": Text(
        "an account id without control characters",
        "identyfikator konta bez znaków sterujących",
    ),
    "rule_area_path": Text(
        "a path below obszary/ of the project directory, with / and without ..",
        "ścieżka pod obszary/ katalogu projektu, z / i bez ..",
    ),
    "rule_sha256": Text(
        "64 lowercase hexadecimal digits", "64 cyfry szesnastkowe małymi literami"
    ),
    "rule_producer": Text(
        "a producer id of lowercase letters, digits and _",
        "identyfikator producenta z małych liter, cyfr i _",
    ),
    "rule_root": Text(
        "a directory path without control characters",
        "ścieżka katalogu bez znaków sterujących",
    ),
    "rule_store_unique": Text("one store per producer", "jeden magazyn na producenta"),
    "rule_group_name": Text(
        "1 to 80 characters without control characters and /",
        "od 1 do 80 znaków bez znaków sterujących i /",
    ),
    "rule_group_unique": Text(
        "a group name used once in the project, whatever its case",
        "nazwa grupy użyta w projekcie raz, bez względu na wielkość liter",
    ),
    "rule_origin": Text(
        "an origin of the kind plan or local", "pochodzenie rodzaju plan albo local"
    ),
    "rule_calls": Text("1 to 1,000 calls", "od 1 do 1000 wywołań"),
    "rule_command": Text(
        "a command's name without control characters",
        "nazwa polecenia bez znaków sterujących",
    ),
    "rule_selection": Text(
        "local_state, catalog or file", "local_state, catalog albo file"
    ),
    "rule_query": Text(
        "a JSON object, left out for file", "obiekt JSON, pominięty dla file"
    ),
    "rule_pins": Text("at most 10,000 pins", "najwyżej 10 000 przypięć"),
    "rule_version": Text(
        "a path relative to the store, with / and without ..",
        "ścieżka względem magazynu, z / i bez ..",
    ),
    "rule_pin_unique": Text(
        "a version pinned once in a group", "wersja przypięta w grupie raz"
    ),
    "rule_plan_producer": Text(
        "the producer of the group's plan", "producent planu grupy"
    ),
    "rule_size": Text(
        "a whole number of bytes, 0 or more", "całkowita liczba bajtów, 0 lub więcej"
    ),
    "rule_text": Text(
        "text without control characters, or null",
        "tekst bez znaków sterujących albo null",
    ),
    "group_name_invalid": Text(
        (
            'A group name is 1 to 80 characters, without control characters and "/":'
            ' "{group}" is not.'
        ),
        (
            "Nazwa grupy ma od 1 do 80 znaków, bez znaków sterujących i „/”:"
            " „{group}” jej nie spełnia."
        ),
    ),
    "group_exists": Text(
        'The project "{project}" has a group "{group}" already.',
        "Projekt „{project}” ma już grupę „{group}”.",
    ),
    "group_not_found": Text(
        'The project "{project}" has no group "{group}".',
        "Projekt „{project}” nie ma grupy „{group}”.",
    ),
    "group_origin_plan": Text(
        (
            'The group "{group}" holds what the plan window downloaded: versions'
            " the store holds are pinned into a new group or a local one."
        ),
        (
            "Grupa „{group}” zawiera dane pobrane w oknie planu: wersje z magazynu"
            " przypina się do nowej grupy albo do grupy lokalnej."
        ),
    ),
    "unknown_store": Text(
        (
            "The project's store of {producer} matches no configured store: add"
            " the store, or name another one for the project."
        ),
        (
            "Magazyn projektu dla {producer} nie odpowiada żadnemu skonfigurowanemu"
            " magazynowi: dodaj magazyn albo wskaż projektowi inny."
        ),
    ),
    "other_store": Text(
        (
            "The project keeps the {producer} data of the store {store}; a version"
            " of {version_store} cannot be pinned in it."
        ),
        (
            "Projekt korzysta z danych {producer} magazynu {store}; wersji z"
            " magazynu {version_store} nie można w nim przypiąć."
        ),
    ),
    "too_many_pins": Text(
        "A group holds at most {limit} pins; this would make {count}.",
        "Grupa mieści najwyżej {limit} przypięć; byłoby ich {count}.",
    ),
}
