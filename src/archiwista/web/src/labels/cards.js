/**
 * Texts shared by the file card, the Projects view and the Store view
 * (views/cards.js): problems with their fixes, background jobs followed
 * live, statuses of projects and pins, names of coordinate systems and the
 * stale-answer note. Status names follow Kartograf's own wording.
 */

export const cards = {
  issues: {
    title: "Problemy",
    none: "Brak problemów.",
    fix: "Jak naprawić:",
    found: "Znaleziony {origin}, {at}",
    origin: {
      scan: "przy skanie",
      check: "przy sprawdzeniu",
    },
    open_file: "Karta pliku",
    open_project: "Projekt „{project}”",
    task: "zadanie {task}",
    path: "ścieżka",
    details: "Szczegóły techniczne",
  },
  job: {
    title: "{kind}: {state}",
    scan_progress: "{current} z {total} {segments} · {entries} {entries_word}",
    footprints_progress: "{current} z {total} · zapisane {written}, nieudane {failed}",
    progress: "{current} z {total}",
    scan_done:
      "Zakończono w {seconds} s: wpisy {entries}, zapisane wersje {versions}, zmienione dowiązania {links}, nowe braki {missing}, usunięte {removed}, nowe problemy {issues}.",
    footprints_done: "Zakończono w {seconds} s: zapisane obrysy {written} z {total}, nieudane {failed}.",
    own_scan_progress: "{current} z {total} {folders} · plików {files}, odczytanych {read}",
    own_scan_done:
      "Zakończono w {seconds} s: plików {files}, nowe {new}, zmienione {changed}, brakujące {missing}, nieczytelne {unreadable}, migawki {snapshots}, problemy {problems}.",
    snapshot_progress: "etap {current} z {total}: {phase}",
    phases: {
      copy: "kopiowanie",
      checksums: "sumy kontrolne",
      document: "opis migawka.json",
      rename: "przeniesienie na miejsce",
      published: "opublikowana",
    },
    download_progress: "{current} z {total} · {status}",
    /** Before the progress of a download of a row's several lines (ADR-044). */
    call_progress: "polecenie {call} z {calls}",
    /** The producers' words of a run's progress (`status`); another shows as it is. */
    unit_status: {
      downloading: "pobieranie",
      completed: "pobrane",
      skipped: "bez zmian",
      failed: "błąd",
    },
    folders: ["folder", "foldery", "folderów"],
    failed: "Zadanie zakończone stanem „{state}”: {detail}",
    notices: "Komunikaty zadania",
    entries: ["wpis", "wpisy", "wpisów"],
    /** A download's files, as `archiwista jobs show` says them (archiwista/messages/job.py). */
    download_files: "Pliki: {files} ({counts}); jednostki z błędem: {failed}.",
    download_file_status: {
      new: "nowe",
      unchanged: "bez zmian",
      relabeled: "z nową etykietą",
    },
    download_files_title: "Pliki w magazynie",
    download_failed: "Jednostki z błędem",
    /** The lines of a download of a row it failed or skipped (`result.calls`, ADR-044). */
    download_calls: "Polecenia nieudane albo pominięte",
    download_call: {
      failed: "Polecenie {place} z {count} nie powiodło się:",
      not_planned: "Polecenie {place} z {count} pominięte, bo jego sprawdzenie nie dało planu:",
      nothing_to_download: "Polecenie {place} z {count} pominięte, bo nie ma nic do pobrania:",
      taken: "Polecenie {place} z {count} pominięte, bo wszystkie jego pozycje pobierają inne zadania:",
    },
    /**
     * Positions to download another active download fetches (`result.taken`,
     * ADR-047), one line per such job: „2 pozycje pobiera marek (zadanie 3f9c1a7e)”.
     */
    download_taken_title: "Pobierane przez inne zadania",
    download_taken: "{count} {positions} pobiera {actor} (zadanie {job})",
    positions: ["pozycję", "pozycje", "pozycji"],
    /** A project's job, as `archiwista jobs show` says it (archiwista/messages). */
    project_tasks: "Zadania projektu: {tasks} ({counts}).",
    project_tasks_title: "Wynik dla zadań projektu",
    task_pins: "przypięte pliki: {count}",
    task_outcome: {
      pinned: "przypięte",
      unchanged: "bez zmian",
      restored: "przywrócone",
      updated: "przypięte na nowo",
      failed: "z błędem",
    },
    project_files: "Pliki: {files} ({counts}); zadania bez przypięć: {not_downloaded}.",
    project_files_title: "Pliki projektu wymagające uwagi",
    project_file: {
      ok: "nienaruszone",
      missing: "brak w magazynie",
      corrupt: "uszkodzone",
      current: "aktualne",
      newer: "nowsze u źródła",
      added: "nowe u źródła",
      removed: "usunięte u źródła",
      unverifiable: "nie do sprawdzenia",
      check_failed: "niesprawdzone",
      conflict: "zapis odmówiony",
    },
  },
  pin_state: {
    ok: "w magazynie",
    missing: "brak w magazynie",
    sha256_mismatch: "inna treść niż przypięta (SHA-256)",
    unknown: "magazyn projektu nieznany",
  },
  status: {
    ok: "w porządku",
    not_downloaded: "nie pobrane",
    missing: "brak przypiętego pliku w magazynie",
    corrupt: "uszkodzony przypięty plik",
    none: "nie sprawdzono",
  },
  stale: "Magazyn „{store}” jest niedostępny — stan z indeksu z {indexed_at}, nie dowód, że plików nie ma.",
  stale_never: "Magazyn „{store}” jest niedostępny i nie ma pełnego przejścia indeksu.",
  /** „Pobierz plik” (views/cards.js `DownloadLink`; ADR-047 decision 5). */
  download: {
    action: "Pobierz plik",
    title: "Zapisz plik na tym komputerze",
    member_title: "Zapisz plik „{name}” na tym komputerze",
    /** Why a file cannot be downloaded now (the disabled action's description). */
    why: {
      store_unavailable: "Magazyn jest niedostępny, więc pliku nie można teraz pobrać.",
      version_missing: "Tej wersji nie ma już w magazynie.",
      file_missing: "Pliku nie ma na dysku.",
      snapshot_invalid: "Migawka jest nieważna, więc nie można jej pobrać.",
    },
  },
  /**
   * The server's path beside the person's own, which a copy button gives
   * first (views/cards.js `ServerPath`; the path aliases of „Moje ścieżki”).
   */
  paths: {
    server: "Na serwerze",
  },
  /** Human names of coordinate systems of Polish and Czech data (Kartograf's names). */
  crs: {
    "EPSG:2180": "PL-1992",
    "EPSG:2176": "PL-2000 strefa 5",
    "EPSG:2177": "PL-2000 strefa 6",
    "EPSG:2178": "PL-2000 strefa 7",
    "EPSG:2179": "PL-2000 strefa 8",
    "EPSG:9651": "PL-EVRF2007-NH",
    "EPSG:5621": "EVRF2007",
    "EPSG:9650": "PL-KRON86-NH",
    "EPSG:5514": "S-JTSK / Křovák",
    "EPSG:8357": "Bpv (Baltic 1957)",
    "EPSG:4326": "WGS 84",
    "EPSG:3857": "Web Mercator",
    "EPSG:4258": "ETRS89",
  },
  crs_unknown: "układ {code}",
};
