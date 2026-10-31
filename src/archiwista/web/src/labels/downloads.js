/**
 * Texts of the downloads in the background (downloads.js; docs/SPEC.md 6.2
 * „Zadania”, 6.5 f; ADR-043): the top bar's „Pobieranie” with its list of
 * the session's downloads, the toast at the end of each, and the names of a
 * download that no plan window named. States and kinds of a job are the
 * shared words of `common` (`job_state`, `job_kind`).
 */

export const downloads = {
  indicator: {
    /** `done` of `total` ended, `percent`: the mean share of their lines and units. */
    running: "Pobieranie {done}/{total} · {percent}%",
    ended: "Pobrano {succeeded}/{total}",
    running_title: "Pobieranie w tle: zakończone {done} z {total}, postęp {percent}%. Pokaż listę pobrań.",
    ended_title: "Pobieranie zakończone: bez błędów {succeeded} z {total}. Pokaż listę pobrań.",
    running_spoken: "Pobieranie w tle: zakończone {done} z {total}, postęp około {percent}%.",
    ended_spoken: "Pobieranie zakończone: bez błędów {succeeded} z {total}.",
  },
  panel: {
    title: "Pobrania w tle",
    close: "Zamknij listę pobrań",
    clear: "Usuń zakończone z listy",
  },
  item: {
    cancel: "Anuluj pobieranie",
    cancel_title: "Zatrzymaj to pobieranie; to, co już pobrane, zostaje w magazynie",
    cancelling: "Anulowanie…",
    show_window: "Pokaż okno planu",
    dismiss: "Usuń z listy",
  },
  name: {
    download: "{producer} · {command}",
    /** A download of a row's several lines (ADR-044): „standin · series fetch · 3 polecenia”. */
    download_calls: "{producer} · {command} · {count} {lines}",
    lines: ["polecenie", "polecenia", "poleceń"],
  },
  toast: {
    label: "Powiadomienia o pobieraniu",
    succeeded: "Pobrano: {title}",
    partial: "Pobrano częściowo: {title}",
    failed: "Pobieranie nie powiodło się: {title}",
    interrupted: "Pobieranie przerwane: {title}",
    cancelled: "Pobieranie anulowane: {title}",
    show: "Pokaż wynik",
    close: "Zamknij powiadomienie",
  },
};
