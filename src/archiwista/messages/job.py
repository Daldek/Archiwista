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
        (
            "Offline mode is on: unit footprints require a network, so the job was not"
            " started."
        ),
        (
            "Tryb offline jest włączony: obrysy jednostek wymagają sieci, więc zadanie"
            " nie zostało uruchomione."
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
}
