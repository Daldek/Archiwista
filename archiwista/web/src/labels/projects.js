/**
 * Texts of the Projects view (views/projects.js, docs/SPEC.md UC-06 and
 * 6.5 g): the projects found in the project directories, their tasks with
 * the producer's commands, pins, statuses and problems. Nothing here starts
 * or changes a project.
 */

export const projects = {
  title: "Projekty",
  count: ["projekt", "projekty", "projektów"],
  empty: "Nie znaleziono projektów w katalogach projektów z ustawień.",
  empty_hint: "Projekty to katalogi z manifestem kartograf-project.json; dodaj ich katalog w Ustawieniach.",
  settings: "Ustawienia",
  store_filter: "Magazyn",
  all_stores: "wszystkie",
  columns: {
    name: "Projekt",
    store: "Magazyn",
    status: "Stan przy skanie",
    tasks: "Zadania",
    pins: "Przypięte",
    missing_pins: "Brakujące",
    scanned_at: "Odczytano",
  },
  no_store: "nieznany magazyn",
  invalid: "Błędny manifest",
  panel: "Projekt",
  select: "Wybierz projekt z listy, aby zobaczyć jego zadania, przypięcia i stan.",
  not_found: "Nie ma projektu „{project}” albo nie masz do niego dostępu.",
  card: {
    producer: "Producent",
    store: "Magazyn",
    scanned_at: "Manifest odczytano",
    stored_status: "Stan przy skanie",
    live_status: "Stan teraz",
    checked_at: "sprawdzono {at}",
    stale_status: "magazyn niedostępny — stan z ostatniego skanu ({at})",
    recheck: "Sprawdź stan ponownie",
    recheck_hint: "Producent sprawdza przypięte pliki bez sieci i bez liczenia sum.",
    manifest_error: "Producent nie odczytał manifestu:",
    tasks: "Zadania",
    no_tasks: "Manifest nie ma zadań.",
    command: "Polecenie",
    options: "Opcje",
    copy_command: "polecenie zadania",
    pins: "Przypięte wersje",
    no_pins: "nic nie przypięto",
    pin_current: "bieżąca",
    pin_older: "starsza wersja",
    pin_open: "Karta pliku",
    missing_pins: "Brakujące przypięcia",
    other_pins: "Przypięcia bez zadania",
    readonly: "Archiwista tylko pokazuje projekt — pobieranie, przepinanie i zmiany robi się poleceniami producenta.",
  },
};
