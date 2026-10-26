/**
 * Texts of the shell: navigation, the session screen, the index state
 * banner and the view host. `nav` names every view by its route id
 * (routes.js) — also one outside the navigation, for the page title — so
 * a view's route line needs no text of its own.
 */

export const shell = {
  brand: "Archiwista",
  version: "wersja {version}",
  nav_label: "Widoki",
  nav: {
    map: "Mapa",
    catalog: "Katalog",
    projects: "Projekty",
    store: "Magazyn",
    setup: "Ustawienia",
    compare: "Porównanie",
    accounts: "Konta",
    groups: "Grupy",
  },
  stores_label: "Magazyny",
  store_title: "Magazyn „{name}” ({id}): {status}",
  session_label: "Sesja: {actor}",
  session_expires: "Sesja wygasa po 24 godzinach bez użycia (obecnie {expires_at}).",
  session: {
    title: "Wymagana sesja",
    instruction:
      "Otwórz adres z terminala — „archiwista serve” wypisuje go przy starcie — albo wystaw nowy poleceniem „archiwista token” i otwórz go w tej przeglądarce.",
    command_label: "Nowy adres sesji:",
    command: "archiwista token",
    lost: "Sesja wygasła albo serwer został uruchomiony ponownie.",
    starting: "Rozpoczynanie sesji…",
  },
  view: {
    loading: "Wczytywanie widoku…",
    failed: "Nie udało się wczytać widoku „{view}”.",
    crashed: "Widok „{view}” zgłosił błąd: {message}",
    unknown: "Nie ma widoku „{view}”.",
    go_start: "Przejdź do widoku startowego",
  },
  banner: {
    label: "Stan indeksu",
    no_store: "Nie skonfigurowano jeszcze żadnego magazynu — Archiwista nie ma czego pokazać.",
    run_wizard: "Uruchom kreator",
    queued: "Skan magazynu „{store}” czeka w kolejce.",
    indexing: "Indeksowanie magazynu „{store}”: {current} z {total} {segments}.",
    indexing_start: "Indeksowanie magazynu „{store}”: odczyt listy segmentów…",
    waiting: "Magazyn „{store}” nie jest jeszcze zindeksowany — skan rozpocznie się automatycznie.",
    unavailable:
      "Magazyn „{store}” jest niedostępny. Wyniki pochodzą z indeksu z {indexed_at} i nie dowodzą, że plików nie ma.",
    unavailable_never: "Magazyn „{store}” jest niedostępny i nie został jeszcze zindeksowany.",
    scan_failed: "Ostatni skan magazynu „{store}” zakończył się stanem: {state}.",
    job: "Magazyn „{store}”: {kind} — {state}.",
    source: "Źródło danych {producer}: {status}.",
    offline_server: "Brak odpowiedzi serwera Archiwisty — pokazany stan może być nieaktualny.",
    detail: "Szczegóły: {detail}",
  },
  panel: {
    resize: "Szerokość panelu „{label}”",
    resize_title:
      "{label}: {width} px — przeciągnij albo użyj strzałek; dwuklik albo Enter: szerokość domyślna",
    close: "Zwiń panel „{label}”",
  },
};
