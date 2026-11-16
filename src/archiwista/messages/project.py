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
    "remove_failed": Text(
        "Cannot remove {path}",
        "Nie można usunąć {path}",
    ),
    "delete_job_running": Text(
        (
            "The project has a job ({kind}, {state}): a project is deleted when"
            " none of its jobs waits or runs."
        ),
        (
            "Projekt ma zadanie ({kind}, {state}): projekt usuwa się, gdy żadne"
            " jego zadanie nie czeka ani nie trwa."
        ),
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
        "nazwa zestawu użyta w projekcie raz, bez względu na wielkość liter",
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
        "a JSON object; left out for file, required for catalog",
        "obiekt JSON; pominięty dla file, wymagany dla catalog",
    ),
    "rule_pins": Text("at most 10,000 pins", "najwyżej 10 000 przypięć"),
    "rule_version": Text(
        "a path relative to the store, with / and without ..",
        "ścieżka względem magazynu, z / i bez ..",
    ),
    "rule_pin_unique": Text(
        "a version pinned once in a group", "wersja przypięta w zestawie raz"
    ),
    "rule_plan_producer": Text(
        "the producer of the group's plan", "producent planu zestawu"
    ),
    "rule_size": Text(
        "a whole number of bytes, 0 or more", "całkowita liczba bajtów, 0 lub więcej"
    ),
    "rule_text": Text(
        "text without control characters, or null",
        "tekst bez znaków sterujących albo null",
    ),
    "rule_set_state": Text("open or closed", "open albo closed"),
    "rule_set_closed_members": Text(
        "closed_at, closed_by and pins_sha256 together, only in a closed group",
        "closed_at, closed_by i pins_sha256 razem, tylko w zamkniętym zestawie",
    ),
    "rule_pin_calls": Text(
        "ascending places of the plan's calls, only in a plan group",
        "rosnące numery wywołań planu, tylko w zestawie z planu",
    ),
    "group_name_invalid": Text(
        (
            'A group name is 1 to 80 characters, without control characters and "/":'
            ' "{group}" is not.'
        ),
        (
            "Nazwa zestawu ma od 1 do 80 znaków, bez znaków sterujących i „/”:"
            " „{group}” jej nie spełnia."
        ),
    ),
    "group_exists": Text(
        'The project "{project}" has a group "{group}" already.',
        "Projekt „{project}” ma już zestaw „{group}”.",
    ),
    "group_not_found": Text(
        'The project "{project}" has no group "{group}".',
        "Projekt „{project}” nie ma zestawu „{group}”.",
    ),
    "set_closed": Text(
        'The group "{group}" is closed: open it for editing to change it.',
        "Zestaw „{group}” jest zamknięty: aby go zmienić, otwórz go do edycji.",
    ),
    "set_open": Text(
        'The group "{group}" is open for editing already.',
        "Zestaw „{group}” jest już otwarty do edycji.",
    ),
    "set_job_active": Text(
        (
            'A job writes into the group "{group}" ({kind}, {state}): close the'
            " group when the job has ended."
        ),
        (
            "Do zestawu „{group}” zapisuje zadanie ({kind}, {state}): zamknij"
            " zestaw, gdy zadanie się skończy."
        ),
    ),
    "set_empty": Text(
        'The group "{group}" has no pin: a closed group holds at least one.',
        "Zestaw „{group}” nie ma przypięć: zamknięty zestaw ma co najmniej jedno.",
    ),
    "set_pins_not_ok": Text(
        (
            'Pins of the group "{group}" that are not ok: {count} (missing'
            " {missing}, other content {mismatch}, unknown store {unknown})."
        ),
        (
            "Przypięcia zestawu „{group}”, które nie są w stanie ok: {count}"
            " (brak {missing}, inna suma {mismatch}, nieznany magazyn {unknown})."
        ),
    ),
    "set_producer": Text(
        (
            'The group "{group}" holds data of {producers}: data of {producer}'
            " goes into another group."
        ),
        (
            "Zestaw „{group}” zawiera dane {producers}: dane {producer} trafiają"
            " do innego zestawu."
        ),
    ),
    "too_many_calls": Text(
        "A group holds at most {limit} calls; this would make {count}.",
        "Zestaw mieści najwyżej {limit} poleceń; byłoby ich {count}.",
    ),
    "pins_without_calls": Text(
        (
            'The group "{group}" has pins of all its calls together, written'
            " before the groups had states: a call cannot be told apart from them."
        ),
        (
            "Zestaw „{group}” ma przypięcia wszystkich swoich poleceń razem,"
            " zapisane przed zestawami w budowie: nie da się od nich oddzielić"
            " polecenia."
        ),
    ),
    "call_not_found": Text(
        'The group "{group}" has no call {call}.',
        "Zestaw „{group}” nie ma polecenia {call}.",
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
        "Zestaw mieści najwyżej {limit} przypięć; byłoby ich {count}.",
    ),
}
