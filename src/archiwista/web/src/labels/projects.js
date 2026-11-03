/**
 * Texts of the Projects view (views/projects.js, docs/SPEC.md UC-06 and
 * 6.5 g; A-ADR-049): the projects found in the project directories, each a
 * directory with Archiwista's file archiwista-project.json, „Nowy projekt…”
 * for every person, the card with the project's directory, stores, area,
 * problems and groups of pinned versions (sets, open „w budowie” or closed),
 * „Zmień…”, „Udostępnij…” and „Usuń projekt…” with the reason when they are
 * not allowed, and the group „Dane własne” (SPEC 4.7.1): the project's data
 * folder with its files and „Odśwież”. The sharing screen's texts are in
 * labels/sharing.js, those of the changes of a set in labels/pins.js.
 */

export const projects = {
  title: "Projekty",
  count: ["projekt", "projekty", "projektów"],
  empty: "Nie znaleziono projektów w katalogach projektów z ustawień.",
  empty_hint:
    "Projekt to katalog z plikiem archiwista-project.json, który Archiwista zapisuje przy „Nowy projekt…”; " +
    "katalogi projektów dodasz w Ustawieniach.",
  settings: "Ustawienia",
  store_filter: "Magazyn",
  /** Project areas offered by the map, catalog and pasted commands. */
  area_choice: {
    label: "Obszar projektu",
    placeholder: "Wybierz projekt…",
    of: "Obszar projektu {name}",
  },
  all_stores: "wszystkie",
  columns: {
    name: "Projekt",
    stores: "Magazyny",
    groups: "Zestawy",
    open_groups: "{count} w budowie",
    pins: "Przypięte",
    missing_pins: "Brakujące",
    scanned_at: "Odczytano",
  },
  unknown_store: "żaden magazyn z ustawień",
  /** A project file that is not used; the card's problems say where and how to fix it. */
  file_problem: {
    invalid_project_file: "Błędny plik projektu: Archiwista nie używa żadnej jego części.",
    unsupported_project_schema: "Plik projektu w nowszym formacie: Archiwista nie czyta jego zestawów.",
  },
  panel: "Projekt",
  not_found: "Nie ma projektu „{project}” albo nie masz do niego dostępu.",
  create: {
    open: "Nowy projekt…",
    open_title: "Załóż projekt w katalogu projektów z ustawień: Archiwista zapisze w nim plik archiwista-project.json",
    no_dirs: "Ustawienia nie mają katalogów projektów; dodaj katalog w Ustawieniach.",
    title: "Nowy projekt",
    path: "Katalog projektu",
    path_hint: "Ścieżka bezwzględna w katalogu projektów z ustawień ({dirs}); brakujący katalog powstanie.",
    name_hint: "Pusta: nazwa katalogu.",
    submit: "Załóż projekt",
    cancel: "Anuluj",
  },
  /** Fields of the forms of a new and of a changed project. */
  form: {
    name: "Nazwa",
    description: "Opis",
    area: "Obszar (opcjonalnie)",
    area_hint: "Plik GeoJSON, GeoPackage albo spakowany Shapefile; jego kopia trafi do katalogu obszary/ projektu.",
  },
  edit: {
    open: "Zmień…",
    open_title: "Nazwa, opis, obszar i magazyny projektu",
    title: "Zmień projekt",
    name_hint: "Od 1 do 200 znaków.",
    area_new: "Nowy obszar",
    area_clear: "Usuń obszar projektu (jego plik zostaje w katalogu obszary/)",
    store: "Magazyn: {producer}",
    store_none: "— żaden —",
    store_hint: "Katalog producenta w tym magazynie: tam leżą przypięte wersje.",
    submit: "Zapisz",
    cancel: "Anuluj",
    saved: "Zapisano zmiany projektu.",
  },
  actions: {
    label: "Działania projektu",
    share: "Udostępnij…",
    share_title: "Kto widzi projekt, jego właściciel i folder danych własnych",
  },
  /** „Usuń projekt…”: what goes, what stays, and the name typed to confirm. */
  remove: {
    open: "Usuń projekt…",
    open_title: "Usuń projekt z Archiwisty; dane w jego katalogu zostają",
    title: "Usuń projekt „{name}”",
    intro: "Archiwista przestanie znać ten projekt. W katalogu {path} usunie tylko to, co sama zapisała:",
    removed: [
      "plik projektu archiwista-project.json (zestawy i przypięcia),",
      "pliki obszarów w katalogu obszary/,",
      "eksporty w katalogu eksport/.",
    ],
    kept_intro: "Zostają:",
    kept: [
      "dane własne w katalogu dane/ i ich wersje w .wersje/,",
      "każdy inny plik w katalogu projektu (np. kartograf-project.json),",
      "przypięte wersje w magazynie: nic w magazynie nie jest zmieniane.",
    ],
    empty_dir: "Katalog projektu zniknie tylko wtedy, gdy nic w nim nie zostanie.",
    access: "Znikną też ustawienia udostępniania projektu; jego aktywność zostaje w dzienniku.",
    name: "Aby potwierdzić, wpisz nazwę projektu: {name}",
    submit: "Usuń projekt",
    cancel: "Anuluj",
    done: "Usunięto projekt „{name}” z Archiwisty. Dane w jego katalogu zostały.",
  },
  card: {
    path: "Katalog",
    copy_path: "ścieżka katalogu projektu",
    stores: "Magazyny",
    no_stores: "jeszcze żaden: wpisze go pierwsze przypięcie wersji",
    area: "Obszar",
    no_area: "brak",
    area_states: {
      ok: "w porządku",
      missing: "brak pliku obszaru",
      changed: "plik obszaru zmieniony: nieużywany",
      invalid: "błędny plik obszaru",
      unread: "nieodczytany",
    },
    area_on_map: "Pokaż na mapie",
    area_on_map_title:
      "Otwórz obszar na mapie: stan lokalny, dostępność u źródła i pobieranie",
    area_catalog: "Pliki obszaru w Katalogu",
    area_files: "Pliki w obszarze: {footprint} z obrysem w obszarze · {country} dla całego kraju",
    created: "Utworzono",
    created_value: "{at} · {by}",
    scanned_at: "Plik projektu odczytano",
    missing_pins: "Brakujące przypięcia",
    groups: "Zestawy przypiętych danych",
    no_groups: "Projekt nie ma jeszcze przypiętych wersji.",
    groups_unread: "Archiwista nie czyta zestawów tego pliku projektu.",
    origin_plan: "z planu pobrania · {producer}",
    origin_local: "z magazynu",
    origin_local_from: "z magazynu · {sources}",
    /** The state of a set (a group): open while it is made, closed once frozen. */
    set_open: "w budowie",
    set_open_title:
      "Zestaw w budowie: można do niego dodawać, odpinać i przepinać, " +
      "aż „Zamknij zestaw” go zamrozi",
    set_closed: "zamknięty",
    set_closed_at: "zamknięty {at} · {by}",
    set_closed_title:
      "Zestaw zamknięty: nic go nie zmienia; „Otwórz do edycji” pozwala go zmienić",
    copy_digest: "skrót zestawu",
    digest_mismatch:
      "Skrót zestawu nie zgadza się z przypięciami: plik zmieniono poza Archiwistą. " +
      "Otwórz zestaw do edycji i zamknij go ponownie.",
    sources: {
      local_state: "stan lokalny",
      catalog: "katalog",
      file: "karta pliku",
    },
    copy_command: "polecenie zestawu",
    more_calls: "i {count} więcej",
    selections: "Jak wybrano wersje zestawu",
    /** The parameters of a selection (`GET /slots`), in words. */
    query: {
      store: "magazyn",
      product: "produkt",
      segment: "segment",
      year: "rok",
      years: "lata",
      area_id: "obszar",
      variant: "wariant",
      versions: "wersje",
      q: "szukane",
    },
    pin_count: ["wersja", "wersje", "wersji"],
    pins: "Przypięte wersje",
    no_pins: "zestaw jest pusty",
    pin_current: "bieżąca",
    pin_older: "starsza wersja",
    pin_open: "Karta pliku",
    pin_by_hand: "ręcznie",
    pin_by_hand_title: "Dodana przez „Dodaj do projektu…”, nie przez polecenie zestawu",
  },
  own: {
    title: "Dane własne",
    refresh: "Odśwież",
    refresh_title: "Przeskanuj folder danych projektu: nowe, zmienione i usunięte pliki oraz migawki",
    on_map: "Pokaż na mapie",
    on_map_title: "Mapa projektu: zasięgi danych własnych i obrysy przypiętych wersji",
    folder: "Folder",
    source: {
      default: "domyślny folder dane/ projektu",
      setting: "folder z ustawień Archiwisty",
    },
    copy_folder: "ścieżka folderu danych",
    state: "Stan",
    states: {
      ok: "w porządku",
      missing: "nie istnieje",
      unreadable: "nieczytelny",
      invalid: "odrzucony przez reguły",
    },
    files: "Pliki",
    files_value: "{count} · {size}",
    snapshots: "Migawki",
    scanned_at: "Odczytano",
    not_scanned: "jeszcze nie skanowany",
    not_scanned_hint: "Folder nie był jeszcze skanowany — „Odśwież” odczyta jego pliki.",
    empty: "Folder danych nie ma plików.",
    list: "Pliki danych własnych",
    more: "Pokaż więcej plików",
    shown: "Pokazano {shown} z {total}",
    file_snapshots: ["migawka", "migawki", "migawek"],
  },
};
