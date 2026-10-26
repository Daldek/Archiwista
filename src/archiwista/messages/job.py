"""Background jobs: names, refusals and outcomes."""

from archiwista.messages import Text

MESSAGES = {
    "kind_scan": Text(
        "scan",
        "skan",
    ),
    "kind_footprints": Text(
        "unit footprints",
        "obrysy jednostek",
    ),
    "kind_link_check": Text(
        "link confirmation",
        "potwierdzenie dowiązania",
    ),
    "state_queued": Text(
        "queued",
        "w kolejce",
    ),
    "state_running": Text(
        "running",
        "trwa",
    ),
    "state_succeeded": Text(
        "completed",
        "zakończone",
    ),
    "state_partial": Text(
        "partly completed",
        "zakończone częściowo",
    ),
    "state_failed": Text(
        "error",
        "błąd",
    ),
    "state_interrupted": Text(
        "interrupted",
        "przerwane",
    ),
    "state_cancelled": Text(
        "cancelled",
        "anulowane",
    ),
    "store_unknown": Text(
        'Store "{store}" is not configured.',
        "Magazyn „{store}” nie jest skonfigurowany.",
    ),
    "not_found": Text(
        'There is no job "{job}".',
        "Nie ma zadania „{job}”.",
    ),
    "no_plan": Text(
        (
            'Job "{job}" kept no plan: only a check of commands that ended with'
            " a plan of one of them keeps one."
        ),
        (
            "Zadanie „{job}” nie zachowało planu: zachowuje go tylko sprawdzenie"
            " poleceń zakończone planem choć jednego z nich."
        ),
    ),
    "conflict": Text(
        (
            'Store "{store}" already has a job writing the index: {kind}, {state}'
            " (job {job}). Wait for it to finish."
        ),
        (
            "Magazyn „{store}” ma już zadanie zapisujące indeks: {kind}, {state}"
            " (zadanie {job}). Poczekaj na jego koniec."
        ),
    ),
    "offline_mode": Text(
        "Offline mode is on: the job needs the network, so it was not started.",
        (
            "Tryb offline jest włączony: to zadanie potrzebuje sieci, więc nie"
            " zostało uruchomione."
        ),
    ),
    "cancelled": Text(
        "The job was cancelled.",
        "Zadanie anulowano.",
    ),
    "interrupted_stop": Text(
        "Archiwista was stopped during the job. It is safe to rerun it.",
        "Archiwistę zatrzymano w trakcie zadania. Można je bezpiecznie ponowić.",
    ),
    "interrupted_restart": Text(
        (
            "The process supervising the job ended midway (stop or crash). It is safe"
            " to rerun it."
        ),
        (
            "Proces nadzorujący zadanie zakończył się w trakcie (zatrzymanie albo"
            " awaria). Można je bezpiecznie ponowić."
        ),
    ),
    "interrupted_signal": Text(
        "The job's worker process was terminated externally. It is safe to rerun it.",
        "Proces roboczy zadania przerwano z zewnątrz. Można je bezpiecznie ponowić.",
    ),
    "worker_crashed": Text(
        (
            "The job's worker process ended unexpectedly ({status}); see the log {log}"
            " for details."
        ),
        (
            "Proces roboczy zadania zakończył się nieoczekiwanie ({status}); szczegóły"
            " w dzienniku {log}."
        ),
    ),
    "status_signal": Text(
        "signal {signal}",
        "sygnał {signal}",
    ),
    "status_code": Text(
        "exit code {code}",
        "kod wyjścia {code}",
    ),
    "worker_not_started": Text(
        "Cannot start the worker process: {detail}",
        "Nie można uruchomić procesu roboczego: {detail}",
    ),
    "internal_error": Text(
        "Archiwista internal error ({detail}); see the job log for details.",
        "Błąd wewnętrzny Archiwisty ({detail}); szczegóły w dzienniku zadania.",
    ),
    "footprints_failed": Text(
        (
            "Files without a determined unit footprint: {count} — try again later."
            " Producer message: {detail}"
        ),
        (
            "Plików bez wyznaczonego obrysu jednostki: {count} — spróbuj ponownie"
            " później. Komunikat producenta: {detail}"
        ),
    ),
    "source_skipped": Text(
        (
            "The {producer} directory was not scanned and stays in the settings: the"
            " data source is unavailable. {detail}"
        ),
        (
            "Katalog {producer} nie został przeskanowany i zostaje w ustawieniach:"
            " źródło danych jest niedostępne. {detail}"
        ),
    ),
    "slot_not_found": Text(
        'Slot "{slot}" of store "{store}" is not in the index.',
        "Slotu „{slot}” magazynu „{store}” nie ma w indeksie.",
    ),
    "link_check_unsupported": Text(
        "The data source {producer} does not confirm links.",
        "Źródło {producer} nie potwierdza dowiązań.",
    ),
    "segment_scan_unsupported": Text(
        (
            "The data source {producer} scans only its whole directory, so it cannot"
            " scan one segment ({segment}); scan the store without a segment."
        ),
        (
            "Źródło {producer} skanuje tylko cały swój katalog, więc nie przeskanuje"
            " pojedynczego segmentu ({segment}); przeskanuj magazyn bez segmentu."
        ),
    ),
    "link_mismatch": Text(
        "{problem}. {fix}",
        "{problem}. {fix}",
    ),
    "link_index_outdated": Text(
        (
            "Link {slot} contains version {version}, but the index points to a"
            " different one — refresh the store."
        ),
        (
            "Dowiązanie {slot} zawiera wersję {version}, a indeks wskazuje inną —"
            " odśwież magazyn."
        ),
    ),
    "kind_preview": Text(
        "building previews",
        "budowa podglądów",
    ),
    "foreground_waiting": Text(
        (
            "Waiting for job {job} ({kind}) of another Archiwista process to finish;"
            " then I will start my own."
        ),
        (
            "Czekam na zakończenie zadania {job} ({kind}) innego procesu Archiwisty;"
            " potem uruchomię własne."
        ),
    ),
    "foreground_stopped": Text(
        "Stopped waiting; job {job} continues in another Archiwista process.",
        "Przestaję czekać; zadanie {job} trwa dalej w innym procesie Archiwisty.",
    ),
    "kind_own_scan": Text(
        "own data scan",
        "skan danych własnych",
    ),
    "kind_snapshot": Text(
        "snapshot",
        "migawka",
    ),
    "kind_availability": Text(
        "availability at the source",
        "dostępność u źródła",
    ),
    "kind_check": Text(
        "plan of a download",
        "plan pobrania",
    ),
    "check_failed": Text(
        "The source could be asked about none of the {count} positions of the plan.",
        "Źródła nie udało się zapytać o żadną z {count} pozycji planu.",
    ),
    "plan_current": Text(
        "current",
        "aktualne",
    ),
    "plan_newer": Text(
        "newer at the source",
        "nowsze u źródła",
    ),
    "plan_missing": Text(
        "missing from the store",
        "brak w magazynie",
    ),
    "plan_unverifiable": Text(
        "cannot be verified",
        "nie do sprawdzenia",
    ),
    "plan_check_failed": Text(
        "not checked",
        "niesprawdzone",
    ),
    "kind_download": Text(
        "download",
        "pobranie",
    ),
    "file_new": Text(
        "new",
        "nowe",
    ),
    "file_unchanged": Text(
        "unchanged",
        "bez zmian",
    ),
    "file_relabeled": Text(
        "relabeled",
        "z nową etykietą",
    ),
    "run_failed": Text(
        "None of the {count} units of the run succeeded.",
        "Żadna z {count} jednostek uruchomienia się nie powiodła.",
    ),
    "overlapping": Text(
        (
            "Job {job} ({state}) downloads some of the same into this store. The"
            " source writes each version once, so this job mostly finds what that"
            " one wrote."
        ),
        (
            "Zadanie {job} ({state}) pobiera część tego samego do tego magazynu."
            " Źródło zapisuje każdą wersję raz, więc to zadanie głównie zastanie"
            " to, co zapisało tamto."
        ),
    ),
    "taken_by_job": Text(
        (
            "Positions to download ({count}) are already being downloaded by"
            " {actor} in job {job}; this job leaves them out."
        ),
        (
            "Pozycje do pobrania ({count}) pobiera już {actor} w zadaniu {job};"
            " to zadanie je pomija."
        ),
    ),
    "waiting_for_job": Text(
        (
            "Job {job} is downloading the same into this store: this job waits"
            " until it ends, then finds its files in the store."
        ),
        (
            "Zadanie {job} pobiera to samo do tego magazynu: to zadanie czeka na"
            " jego koniec, a potem zastanie jego pliki w magazynie."
        ),
    ),
    "rescan_failed": Text(
        (
            "The index does not show all files of the run yet: the next scan of the"
            " store adds them."
        ),
        (
            "Indeks nie pokazuje jeszcze wszystkich plików uruchomienia: doda je"
            " najbliższy skan magazynu."
        ),
    ),
    "mismatched_plan": Text(
        (
            'Job "{job}" planned another store, producer or commands: download'
            " what it planned, with its commands in their order, or check these"
            " commands first."
        ),
        (
            "Zadanie „{job}” zaplanowało inny magazyn, producenta albo polecenia:"
            " pobierz to, co zaplanowało, z jego poleceniami w ich kolejności,"
            " albo najpierw sprawdź te polecenia."
        ),
    ),
    "conflict_snapshot": Text(
        (
            "A snapshot of this file is already in progress: job {job} ({state}). Wait"
            " for it to finish."
        ),
        (
            "Migawka tego pliku już trwa: zadanie {job} ({state}). Poczekaj na jego"
            " koniec."
        ),
    ),
    "conflict_project": Text(
        (
            "The project already has a job: {kind}, {state} (job {job}). Wait for"
            " it to finish."
        ),
        (
            "Projekt ma już zadanie: {kind}, {state} (zadanie {job}). Poczekaj na"
            " jego koniec."
        ),
    ),
    "kind_project_download": Text(
        "project download",
        "pobranie projektu",
    ),
    "kind_project_repin": Text(
        "repin of a project task",
        "ponowne przypięcie zadania projektu",
    ),
    "kind_project_check": Text(
        "project check at the source",
        "sprawdzenie projektu u źródła",
    ),
    "kind_project_verify": Text(
        "project verification",
        "weryfikacja projektu",
    ),
    "kind_preview_warm": Text(
        "preview warm-up",
        "przygotowanie podglądów",
    ),
    "warm_cache_full": Text(
        (
            "The preview cache has no more room without evicting previews used"
            " in the last week: {skipped} files were left without a prepared"
            " preview. Raise the preview cache limit ({limit} GB) in the settings"
            " to prepare them."
        ),
        (
            "W pamięci podglądów nie ma już miejsca bez usuwania podglądów"
            " oglądanych w ostatnim tygodniu: {skipped} plików zostało bez"
            " przygotowanego podglądu. Aby je przygotować, podnieś limit pamięci"
            " podglądów ({limit} GB) w ustawieniach."
        ),
    ),
    "project_failed": Text(
        "None of the {count} tasks of the project succeeded.",
        "Żadne z {count} zadań projektu się nie powiodło.",
    ),
    "project_check_failed": Text(
        "The source could be asked about none of the {count} pinned files.",
        "Źródła nie udało się zapytać o żaden z {count} przypiętych plików.",
    ),
    "project_not_indexed": Text(
        (
            "The index does not show the project's new pins yet: the next scan of"
            " the project directories reads them."
        ),
        (
            "Indeks nie pokazuje jeszcze nowych przypięć projektu: odczyta je"
            " najbliższy skan katalogów projektów."
        ),
    ),
    "task_pinned": Text(
        "pinned",
        "przypięte",
    ),
    "task_unchanged": Text(
        "unchanged",
        "bez zmian",
    ),
    "task_restored": Text(
        "restored",
        "przywrócone",
    ),
    "task_updated": Text(
        "pinned anew",
        "przypięte na nowo",
    ),
    "task_failed": Text(
        "failed",
        "z błędem",
    ),
    "project_file_ok": Text(
        "intact",
        "nienaruszone",
    ),
    "project_file_missing": Text(
        "missing from the store",
        "brak w magazynie",
    ),
    "project_file_corrupt": Text(
        "corrupt",
        "uszkodzone",
    ),
    "project_file_current": Text(
        "current",
        "aktualne",
    ),
    "project_file_newer": Text(
        "newer at the source",
        "nowsze u źródła",
    ),
    "project_file_added": Text(
        "new at the source",
        "nowe u źródła",
    ),
    "project_file_removed": Text(
        "gone from the source",
        "usunięte u źródła",
    ),
    "project_file_unverifiable": Text(
        "cannot be verified",
        "nie do sprawdzenia",
    ),
    "project_file_check_failed": Text(
        "not checked",
        "niesprawdzone",
    ),
    "project_file_conflict": Text(
        "write refused",
        "zapis odmówiony",
    ),
    "cancel_finished": Text(
        'Job "{job}" has already ended ({state}); there is nothing to cancel.',
        "Zadanie „{job}” już się zakończyło ({state}); nie ma czego anulować.",
    ),
    "retry_succeeded": Text(
        'Job "{job}" succeeded; there is nothing to retry.',
        "Zadanie „{job}” zakończyło się powodzeniem; nie ma czego ponawiać.",
    ),
    "retry_active": Text(
        'Job "{job}" has not ended yet ({state}); retry it after it ends.',
        "Zadanie „{job}” jeszcze się nie zakończyło ({state}); ponów je po jego końcu.",
    ),
    "no_log": Text(
        (
            'Job "{job}" has no log: it never started its worker, or its log went'
            " with the old logs (kept 90 days and up to 1 GB)."
        ),
        (
            "Zadanie „{job}” nie ma dziennika: nie uruchomiło procesu roboczego albo"
            " jego dziennik usunięto z dawnymi (trzymane są 90 dni i do 1 GB)."
        ),
    ),
}
