/**
 * Words every view shares: actions, states of jobs, stores and sources, and
 * the client's own problems (no answer from the server). Names follow the
 * server's dictionary (archiwista/messages.py) so the interface, the API and
 * the command line say the same thing.
 */

export const common = {
  actions: {
    save: "Zapisz",
    cancel: "Anuluj",
    next: "Dalej",
    back: "Wstecz",
    close: "Zamknij",
    retry: "Spróbuj ponownie",
    copy: "Kopiuj",
    copied: "Skopiowano",
    add: "Dodaj",
    remove: "Usuń",
    change: "Zmień",
    skip: "Pomiń",
  },
  loading: "Ładowanie…",
  empty: "–",
  yes: "tak",
  no: "nie",
  technical: {
    show: "Pokaż wartość techniczną",
    hide: "Ukryj wartość techniczną",
    code: "kod",
    type: "typ",
  },
  job_kind: {
    scan: "skan",
    footprints: "obrysy jednostek",
    link_check: "potwierdzenie dowiązania",
  },
  job_state: {
    queued: "w kolejce",
    running: "trwa",
    succeeded: "zakończone",
    failed: "błąd",
    interrupted: "przerwane",
    cancelled: "anulowane",
  },
  store_status: {
    unknown: "jeszcze nie zeskanowany",
    available: "dostępny",
    unavailable: "niedostępny",
  },
  store_kind: {
    local: "dysk lokalny",
    share: "udział sieciowy",
  },
  source_status: {
    available: "dostępne",
    not_installed: "pakiet producenta nie jest zainstalowany",
    incompatible: "niezgodna wersja albo schemat",
    error: "błąd wtyczki",
  },
  actor: {
    local: "właściciel lokalny",
  },
  problem: {
    network_title: "Brak połączenia",
    network:
      "Nie można połączyć się z serwerem Archiwisty. Sprawdź, czy w terminalu działa „archiwista serve”.",
    http_title: "Błąd żądania",
    http: "Serwer odpowiedział kodem {status} bez opisu problemu.",
    fields: "Do poprawy:",
    producer: "Komunikat {package}:",
    running_job: "Trwa zadanie: {kind} ({state}).",
    stream: "Przerwano śledzenie zadania „{job}”.",
  },
  units: {
    segments: ["segment", "segmenty", "segmentów"],
    files: ["plik", "pliki", "plików"],
    versions: ["wersja", "wersje", "wersji"],
    problems: ["problem", "problemy", "problemów"],
  },
};
