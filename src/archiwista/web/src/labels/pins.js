/**
 * Texts of pinning (A-ADR-049 decisions 8 and 9): „Dodaj do projektu…” of
 * „Stan lokalny”, the Katalog and the file card (views/pin-dialog.js), the
 * plan window's „Dodaj do projektu” (views/plan.js), the pin of a download's
 * result (views/cards.js) and, on the project card (views/projects.js), the
 * changes of a set: „Odepnij”, „Usuń polecenie”, „Usuń zestaw”, „Zamknij
 * zestaw”, „Otwórz do edycji” and „Nowy zestaw w budowie…”.
 */

export const pins = {
  open: "Dodaj do projektu…",
  open_title: "Przypnij te wersje z magazynu w zestawie projektu",
  title: "Dodaj do projektu",
  what: "Co zostanie przypięte",
  /** „Stan lokalny”: its filters, joined by „ · ”. */
  local: {
    files: "Pliki „{product}” w obszarze",
    versions: "wersje: {versions}",
    years: "lata danych: {years}",
    store: "magazyn {store}",
  },
  /** „Stan lokalny” while the map shows a year layer: that layer's versions. */
  layer: "Warstwa mapy „{product}”: {layer} · {variant}",
  layer_year: "rok {year}",
  from_catalog: "Wiersze Katalogu z obecnymi filtrami",
  from_file: "Wersja {label} pliku {name}",
  counting: "Liczenie wersji…",
  versions: ["wersja", "wersje", "wersji"],
  nothing: "Wybór nie ma żadnej wersji do przypięcia.",
  too_many:
    "Zestaw mieści najwyżej {limit} przypięć, a wybór ma {count} wersji: zawęź filtry.",
  project: "Projekt",
  project_hint: "Projekty, które ta sesja może zmienić.",
  no_project:
    "Ta sesja nie może zmienić żadnego projektu: " +
    "przypina właściciel projektu albo administrator. " +
    "Własny projekt zakłada „Nowy projekt…” w widoku Projekty.",
  group: "Zestaw",
  new_group: "Nowy zestaw",
  name: "Nazwa nowego zestawu",
  name_hint:
    "Najlepiej cel albo rok, np. 2024; od 1 do 80 znaków, bez „/”; inna niż nazwy zestawów projektu.",
  open_group: "Zestaw w budowie",
  open_group_hint:
    "Wersje przyjmują tylko zestawy w budowie; zamknięty otwórz na karcie projektu " +
    "(„Otwórz do edycji”).",
  no_open_groups:
    "Projekt nie ma zestawów w budowie: zamknięty otwórz na karcie projektu " +
    "(„Otwórz do edycji”).",
  submit: "Przypnij",
  cancel: "Anuluj",
  close: "Zamknij",
  done:
    "Zestaw „{group}” projektu „{project}”: " +
    "przypięte {pinned}, już były {already}, pominięte {skipped}.",
  done_state: {
    open: "Zestaw jest w budowie: zamknij go na karcie projektu, gdy będzie gotowy.",
    closed: "Zestaw jest zamknięty: aby go zmienić, otwórz go do edycji na karcie projektu.",
  },
  skipped: "Pominięte wersje",
  skip_reason: {
    missing: "brak w magazynie",
    no_sha256: "metadane bez sumy SHA-256",
  },
  open_project: "Otwórz projekt",

  /** The project card. */
  unpin: "Odepnij",
  unpin_label: "Odepnij {version} z zestawu {group}",
  unpin_question: "Odpiąć {version} z zestawu „{group}”? Plik zostaje w magazynie.",
  remove_group: "Usuń zestaw",
  remove_group_label: "Usuń zestaw {group}",
  remove_group_question:
    "Usunąć zestaw „{group}” z jego przypięciami ({count})? Pliki zostają w magazynie.",
  confirm_cancel: "Anuluj",
  unpinned: "Odpięto {version} z zestawu „{group}”.",
  removed: "Usunięto zestaw „{group}”.",
  uncall: "Usuń polecenie",
  uncall_label: "Usuń polecenie {place} zestawu {group}",
  uncall_question: "Usunąć polecenie {place} z zestawu „{group}”?",
  uncall_pins: "Odepnie wersje, które przypięło tylko ono ({count}):",
  uncall_no_pins:
    "Żadna wersja nie zostanie odpięta: każdą przypięło też inne polecenie " +
    "albo dodano ją ręcznie.",
  uncall_kept: "Pliki zostają w magazynie.",
  uncall_more: "i {count} więcej",
  uncalled: "Usunięto polecenie {place} z zestawu „{group}”.",
  close: "Zamknij zestaw",
  close_label: "Zamknij zestaw {group}",
  close_title:
    "Zamroź zestaw: zapisze skrót jego przypięć, kto i kiedy go zamknął; " +
    "do zmian trzeba go otworzyć",
  close_advice:
    "Zamknięcie sprawdza stan przypięć z ostatniego odczytu; „Weryfikuj” " +
    "odświeży go przed zamknięciem.",
  closed: "Zamknięto zestaw „{group}”.",
  reopen: "Otwórz do edycji",
  reopen_label: "Otwórz do edycji zestaw {group}",
  reopen_title:
    "Pozwól dodawać, odpinać i przepinać wersje zestawu; jego skrót zniknie " +
    "do ponownego zamknięcia",
  reopen_question:
    "Otworzyć zestaw „{group}” do edycji? Programy, które czytają tylko zamknięte " +
    "zestawy (Hydrograf), odmówią go do ponownego zamknięcia.",
  reopened: "Otwarto do edycji zestaw „{group}”.",
  draft: "Nowy zestaw w budowie…",
  draft_title:
    "Pusty zestaw, do którego okna planu i „Dodaj do projektu…” dodają wersje, " +
    "aż go zamkniesz",
  draft_heading: "Nowy zestaw w budowie",
  draft_name: "Nazwa zestawu",
  draft_submit: "Utwórz zestaw",
  drafted: "Utworzono zestaw w budowie „{group}”.",

  /** The plan window (views/plan.js). */
  plan: {
    option: "Dodaj do projektu",
    option_hint:
      "Po udanym pobraniu pobrane pliki i aktualne pozycje planu trafią do zestawu " +
      "projektu: nowego albo w budowie.",
    project: "Projekt",
    set: "Zestaw",
    group: "Nowy zestaw",
    name: "Nazwa nowego zestawu",
    group_hint:
      "Najlepiej cel albo rok, np. 2024; od 1 do 80 znaków, bez „/”; inna niż nazwy zestawów projektu.",
    keep_open: "Zostaw w budowie",
    keep_open_hint:
      "Następne okna planu i „Dodaj do projektu…” dodadzą do niego wersje, " +
      "aż zamkniesz go na karcie projektu.",
    open_group: "Zestaw w budowie",
    open_group_hint:
      "Polecenia i pliki tego pobrania dołączą do zestawu; zamknięty zestaw otwórz " +
      "na karcie projektu („Otwórz do edycji”).",
    no_open_groups: "Projekt nie ma zestawów w budowie.",
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
    written: "Przypięto w projekcie {project}, zestaw „{group}”: {count}.",
    added: "Dodano do zestawu w budowie „{group}”: {count}.",
    already: "Już były w zestawie: {count}.",
    left_open: "Zestaw zostaje w budowie.",
    not_pinned: "Nieprzypięte pozycje planu, których nie ma w magazynie ({count})",
    job_partial:
      "Nie przypięto w projekcie {project} (zestaw „{group}”): " +
      "pobranie nie udało się w całości.",
    error: "Nie przypięto w projekcie {project} (zestaw „{group}”):",
    open_project: "Otwórz projekt",
  },
};
