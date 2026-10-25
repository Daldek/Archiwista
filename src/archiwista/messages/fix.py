"""How to fix a problem: the lines of the doctor and of store problems."""

from archiwista.messages import Text

MESSAGES = {
    "config": Text(
        "correct the configuration file {path} or delete it and configure again.",
        "popraw plik konfiguracji {path} albo usuń go i skonfiguruj ponownie.",
    ),
    "wizard": Text(
        'add a store in the wizard after starting "archiwista serve".',
        "dodaj magazyn w kreatorze po uruchomieniu „archiwista serve”.",
    ),
    "install": Text(
        'install a compatible version: pip install "{requirement}"',
        'zainstaluj zgodną wersję: pip install "{requirement}"',
    ),
    "plugin_error": Text(
        (
            "reinstall the {producer} data source package; if the error recurs, report"
            " it together with the message above."
        ),
        (
            "zainstaluj ponownie pakiet źródła {producer}; jeśli błąd się powtarza,"
            " zgłoś go razem z treścią powyżej."
        ),
    ),
    "reconnect": Text(
        "reconnect the share or correct the store path in the settings.",
        "podłącz udział albo popraw ścieżkę magazynu w ustawieniach.",
    ),
    "not_directory": Text(
        "point to a directory in the settings, not a file.",
        "wskaż w ustawieniach katalog, a nie plik.",
    ),
    "permissions": Text(
        "grant the user running Archiwista read and enter permission on the directory.",
        (
            "nadaj użytkownikowi uruchamiającemu Archiwistę prawo odczytu i wejścia do"
            " katalogu."
        ),
    ),
    "nested": Text(
        "specify producer directories none of which lies inside another.",
        "wskaż katalogi producentów, z których żaden nie leży w drugim.",
    ),
    "source": Text(
        (
            "check that the producer's --output directory is specified and that its"
            " version is compatible."
        ),
        (
            "sprawdź, czy wskazano katalog --output producenta i czy jego wersja jest"
            " zgodna."
        ),
    ),
    "project_dir": Text(
        "connect the directory or remove it from the settings.",
        "podłącz katalog albo usuń go z ustawień.",
    ),
    "data_dir": Text(
        "grant write permission to the local data directory.",
        "nadaj prawo zapisu do katalogu danych lokalnych.",
    ),
    "data_dir_open": Text(
        (
            'run "archiwista serve" (it restricts the directory to 0700) or: chmod'
            " 700 {path}"
        ),
        "uruchom „archiwista serve” (zamyka katalog do 0700) albo: chmod 700 {path}",
    ),
    "port": Text(
        "change the port in the settings or stop the program that is using it.",
        "zmień port w ustawieniach albo zatrzymaj program, który go używa.",
    ),
    "missing_sidecar": Text(
        (
            "Download this file again with the {producer} command — the new version"
            " will get a sidecar; delete the leftover file without a sidecar manually"
            " after checking."
        ),
        (
            "Pobierz ten plik ponownie poleceniem {producer} — nowa wersja dostanie"
            " sidecar; pozostałość bez sidecara usuń ręcznie po sprawdzeniu."
        ),
    ),
    "invalid_sidecar": Text(
        (
            "Check the .meta.json file next to the data or download this version again"
            " with the {producer} command."
        ),
        (
            "Sprawdź plik .meta.json obok danych albo pobierz tę wersję ponownie"
            " poleceniem {producer}."
        ),
    ),
    "imgw_missing_sidecar": Text(
        (
            "Not critical and usually temporary: wait until the download ends. If"
            " it was interrupted, run the same {producer} download again; it"
            " completes the version with its sidecar and nothing needs deleting."
        ),
        (
            "Niekrytyczne i zwykle przejściowe: poczekaj, aż pobieranie się skończy."
            " Jeśli zostało przerwane, powtórz to samo pobieranie poleceniem"
            " {producer}; uzupełni wersję o sidecar i niczego nie trzeba usuwać."
        ),
    ),
    "unknown_schema": Text(
        (
            "The file was written in a schema this version of the {producer} package"
            " does not read (probably by a newer version): update the package or"
            " download this data again with the version in use."
        ),
        (
            "Plik zapisano w schemacie, którego ta wersja pakietu {producer} nie"
            " czyta (zapewne przez nowszą wersję): zaktualizuj pakiet albo pobierz"
            " te dane ponownie używaną wersją."
        ),
    ),
    "unknown_segment": Text(
        (
            "This is usually data from a development or newer version of the"
            " {producer} package: update the package or download this data again into a"
            " recognized product."
        ),
        (
            "To zwykle dane z wersji deweloperskiej albo nowszej pakietu"
            " {producer}: zaktualizuj pakiet albo pobierz te dane ponownie do"
            " rozpoznanego produktu."
        ),
    ),
    "legacy_campaigns": Text(
        (
            "Download this data again with the current version of the {producer}"
            " package; delete the old directory manually only after checking."
        ),
        (
            "Pobierz te dane ponownie bieżącą wersją pakietu {producer}; stary katalog"
            " usuń ręcznie dopiero po sprawdzeniu."
        ),
    ),
    "stale_incoming": Text(
        (
            "The {producer} package removes it on the next download into this product;"
            " if no download is in progress, you can delete this directory manually."
        ),
        (
            "Pakiet {producer} usuwa ją przy następnym pobieraniu do tego produktu;"
            " jeśli żadne pobieranie nie trwa, możesz usunąć ten katalog ręcznie."
        ),
    ),
    "link_mismatch": Text(
        (
            "Download the file again with the {producer} command with update, so that"
            " the link points to the correct version."
        ),
        (
            "Pobierz plik ponownie poleceniem {producer} z aktualizacją, aby"
            " dowiązanie wskazywało właściwą wersję."
        ),
    ),
    "orphan_sidecar": Text(
        (
            "Restore the missing version from a backup or download the file again with"
            " the {producer} command."
        ),
        (
            "Przywróć brakującą wersję z kopii albo pobierz plik ponownie poleceniem"
            " {producer}."
        ),
    ),
    "missing_pin": Text(
        (
            'Restore the pinned files with the "{producer} project download {task}"'
            ' command in the directory of project "{project}".'
        ),
        (
            "Odtwórz przypięte pliki poleceniem „{producer} project download {task}” w"
            " katalogu projektu „{project}”."
        ),
    ),
    "pin_sha256_mismatch": Text(
        (
            'Check the project files with the "{producer} project verify" command in'
            ' the directory of project "{project}".'
        ),
        (
            "Sprawdź pliki projektu poleceniem „{producer} project verify” w katalogu"
            " projektu „{project}”."
        ),
    ),
    "invalid_manifest": Text(
        (
            "Fix the manifest in the project directory {path} — the {producer} package"
            " message shows where the error is."
        ),
        (
            "Popraw manifest w katalogu projektu {path} — komunikat pakietu {producer}"
            " wskazuje miejsce błędu."
        ),
    ),
    "unknown_store": Text(
        (
            "Add the store in settings (directory {store_dir}) or correct the store"
            " path in the project manifest."
        ),
        (
            "Dodaj magazyn w ustawieniach (katalog {store_dir}) albo popraw ścieżkę"
            " magazynu w manifeście projektu."
        ),
    ),
    "other": Text(
        "Check this location with the {producer} package tools.",
        "Sprawdź to miejsce narzędziami pakietu {producer}.",
    ),
    "own_data_dir": Text(
        (
            "point the project to an existing data directory outside the stores, other"
            " projects' directories and the Archiwista data directory, or remove the"
            " own_data_dirs entry (default directory: <project directory>/dane)."
        ),
        (
            "wskaż projektowi istniejący folder danych poza magazynami, folderami"
            " innych projektów i katalogiem danych Archiwisty albo usuń wpis"
            " own_data_dirs (folder domyślny: <katalog projektu>/dane)."
        ),
    ),
    "own_folder_unreadable": Text(
        (
            "Connect the share or grant the user running Archiwista permission to read"
            " and enter the folder."
        ),
        (
            "Podłącz udział albo nadaj użytkownikowi uruchamiającemu Archiwistę prawo"
            " odczytu i wejścia do folderu."
        ),
    ),
    "own_folder_invalid": Text(
        (
            "The administrator points the project to a different data folder, disjoint"
            " from the stores, from the folders of other projects, and from the"
            " Archiwista data directory."
        ),
        (
            "Administrator wskazuje projektowi inny folder danych, rozłączny z"
            " magazynami, z folderami innych projektów i z katalogiem danych"
            " Archiwisty."
        ),
    ),
    "own_folder_too_large": Text(
        (
            "Move excess files and snapshots out of the data folder, reduce the number"
            " of subdirectories, or split the data between projects."
        ),
        (
            "Przenieś nadmiar plików i migawek poza folder danych, ogranicz liczbę"
            " podkatalogów lub podziel dane między projekty."
        ),
    ),
    "own_file_unreadable": Text(
        (
            "Check the file in a GIS program; if it was just being saved, refresh the"
            " own data after editing is finished."
        ),
        (
            "Sprawdź plik w programie GIS; jeśli był właśnie zapisywany, odśwież dane"
            " własne po zakończeniu edycji."
        ),
    ),
    "invalid_snapshot": Text(
        (
            "Do not change files in the .wersje directory; restore the snapshot from a"
            " backup — Archiwista does not repair or delete snapshots."
        ),
        (
            "Nie zmieniaj plików w katalogu .wersje; przywróć migawkę z kopii"
            " zapasowej — Archiwista nie poprawia ani nie usuwa migawek."
        ),
    ),
    "unknown_snapshot_schema": Text(
        "The snapshot was written by a newer Archiwista — update Archiwista.",
        "Migawkę zapisała nowsza Archiwista — zaktualizuj Archiwistę.",
    ),
    "snapshot_modified": Text(
        "Restore the snapshot from a backup; Archiwista does not modify snapshots.",
        "Przywróć migawkę z kopii zapasowej; Archiwista nie zmienia migawek.",
    ),
    "stale_snapshot_incoming": Text(
        (
            "When no snapshot is in progress, delete this directory manually —"
            " Archiwista does not delete it."
        ),
        (
            "Gdy żadna migawka nie trwa, usuń ten katalog ręcznie — Archiwista go nie"
            " usuwa."
        ),
    ),
    "path_outside_root": Text(
        (
            "Copy the data into the data folder instead of using a link — Archiwista"
            " does not read files from outside the folder."
        ),
        (
            "Skopiuj dane do folderu danych zamiast dowiązania — Archiwista nie czyta"
            " plików spoza folderu."
        ),
    ),
}
