/**
 * Texts of pinning (A-ADR-049 decisions 8 and 9): „Dodaj do projektu…” of
 * „Stan lokalny”, the Katalog and the file card (views/pin-dialog.js), the
 * plan window's „Dodaj do projektu” (views/plan.js), the pin of a download's
 * result (views/cards.js) and „Odepnij” and „Usuń grupę” of the project card
 * (views/projects.js).
 */

export const pins = {
  open: "Dodaj do projektu…",
  open_title: "Przypnij te wersje z magazynu w grupie projektu",
  title: "Dodaj do projektu",
  what: "Co zostanie przypięte",
  from_local_state: "Bieżące wersje plików „{product}” w obszarze",
  from_local_state_store: "Bieżące wersje plików „{product}” w obszarze, magazyn {store}",
  from_catalog: "Wiersze Katalogu z obecnymi filtrami",
  from_file: "Wersja {label} pliku {name}",
  counting: "Liczenie wersji…",
  versions: ["wersja", "wersje", "wersji"],
  /** Rows of a query: each pins its version, a row without one nothing. */
  rows: ["wiersz", "wiersze", "wierszy"],
  nothing: "Wybór nie ma żadnej wersji do przypięcia.",
  too_many:
    "Grupa mieści najwyżej {limit} przypięć, a wybór ma {count} wierszy: zawęź filtry.",
  project: "Projekt",
  project_hint: "Projekty, które ta sesja może zmienić.",
  no_project:
    "Ta sesja nie może zmienić żadnego projektu: " +
    "przypina właściciel projektu albo administrator. " +
    "Własny projekt zakłada „Nowy projekt…” w widoku Projekty.",
  group: "Grupa",
  new_group: "Nowa grupa",
  name: "Nazwa nowej grupy",
  name_hint: "Od 1 do 80 znaków, bez „/”; inna niż nazwy grup projektu.",
  local_group: "Grupa lokalna projektu",
  local_group_hint: "Grupy z okna planu przyjmują tylko to, co w nim pobrano.",
  no_local_groups: "Projekt nie ma grup lokalnych.",
  submit: "Przypnij",
  cancel: "Anuluj",
  close: "Zamknij",
  done:
    "Grupa „{group}” projektu „{project}”: " +
    "przypięte {pinned}, już były {already}, pominięte {skipped}.",
  skipped: "Pominięte wersje",
  skip_reason: {
    missing: "brak w magazynie",
    no_sha256: "metadane bez sumy SHA-256",
  },
  open_project: "Otwórz projekt",

  /** The project card. */
  unpin: "Odepnij",
  unpin_label: "Odepnij {version} z grupy {group}",
  unpin_question: "Odpiąć {version} z grupy „{group}”? Plik zostaje w magazynie.",
  remove_group: "Usuń grupę",
  remove_group_label: "Usuń grupę {group}",
  remove_group_question:
    "Usunąć grupę „{group}” z jej przypięciami ({count})? Pliki zostają w magazynie.",
  confirm_cancel: "Anuluj",
  unpinned: "Odpięto {version} z grupy „{group}”.",
  removed: "Usunięto grupę „{group}”.",

  /** The plan window (views/plan.js). */
  plan: {
    option: "Dodaj do projektu",
    option_hint:
      "Po udanym pobraniu pobrane pliki i aktualne pozycje planu trafią do nowej grupy projektu.",
    project: "Projekt",
    group: "Nowa grupa",
    group_hint: "Od 1 do 80 znaków, bez „/”; inna niż nazwy grup projektu.",
    submit: "Pobierz {count} {positions} i przypnij",
    submit_pin_only: "Przypnij {count} {positions}",
    no_project:
      "Ta sesja nie może zmienić żadnego projektu: " +
      "przypina właściciel projektu albo administrator.",
    offline: "Tryb offline: bez planu u źródła nie ma czego przypiąć.",
    no_plan: "Przypiąć można dopiero sprawdzony plan.",
    no_write:
      "Przypięcie idzie z pobraniem, a ta sesja nie ma uprawnienia " +
      "„zapis do magazynu” (rola store_writer).",
  },

  /** The pin of a download's result (views/cards.js `downloadSummary`). */
  result: {
    written: "Przypięto w projekcie {project}, grupa „{group}”: {count}.",
    not_pinned: "Nieprzypięte pozycje planu, których nie ma w magazynie ({count})",
    job_partial:
      "Nie przypięto w projekcie {project} (grupa „{group}”): " +
      "pobranie nie udało się w całości.",
    error: "Nie przypięto w projekcie {project} (grupa „{group}”):",
    open_project: "Otwórz projekt",
  },
};
