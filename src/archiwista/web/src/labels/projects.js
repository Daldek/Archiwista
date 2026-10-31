/**
 * Texts of the Projects view (views/projects.js, docs/SPEC.md UC-06 and
 * 6.5 g; A-ADR-049): the projects found in the project directories, each a
 * directory with Archiwista's file archiwista-project.json, „Nowy projekt…”
 * for every person, the card with the project's directory, stores, area,
 * problems and groups of pinned versions, „Zmień…” and „Udostępnij…” with
 * the reason when they are not allowed, and the group „Dane własne” (SPEC
 * 4.7.1): the project's data folder with its files and „Odśwież”. The
 * sharing screen's texts are in labels/sharing.js.
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
  all_stores: "wszystkie",
  columns: {
    name: "Projekt",
    stores: "Magazyny",
    groups: "Grupy",
    pins: "Przypięte",
    missing_pins: "Brakujące",
    scanned_at: "Odczytano",
  },
  unknown_store: "żaden magazyn z ustawień",
  /** A project file that is not used; the card's problems say where and how to fix it. */
  file_problem: {
    invalid_project_file: "Błędny plik projektu: Archiwista nie używa żadnej jego części.",
    unsupported_project_schema: "Plik projektu w nowszym formacie: Archiwista nie czyta jego grup.",
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
  why: {
    write: "Zmienia i udostępnia projekt jego właściciel albo administrator.",
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
    created: "Utworzono",
    created_value: "{at} · {by}",
    scanned_at: "Plik projektu odczytano",
    missing_pins: "Brakujące przypięcia",
    groups: "Grupy przypiętych wersji",
    no_groups: "Projekt nie ma jeszcze przypiętych wersji.",
    groups_unread: "Archiwista nie czyta grup tego pliku projektu.",
    origin_plan: "z planu pobrania · {producer}",
    origin_local: "z magazynu",
    origin_local_from: "z magazynu · {sources}",
    sources: {
      local_state: "stan lokalny",
      catalog: "katalog",
      file: "karta pliku",
    },
    copy_command: "polecenie grupy",
    pin_count: ["wersja", "wersje", "wersji"],
    pins: "Przypięte wersje",
    no_pins: "grupa jest pusta",
    pin_current: "bieżąca",
    pin_older: "starsza wersja",
    pin_open: "Karta pliku",
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
