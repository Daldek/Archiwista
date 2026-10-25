/**
 * Texts of the first-run wizard and of the settings it edits later
 * (setup.js; GET/PUT /api/v1/settings).
 */

export const setup = {
  title_first: "Pierwsze uruchomienie",
  title_edit: "Ustawienia",
  intro_first:
    "Wskaż magazyn Kartografa albo IMGWTools i — jeśli chcesz — katalogi projektów. Archiwista tylko czyta te katalogi: nie zapisuje w nich żadnych plików, a indeks i pamięć podręczną trzyma lokalnie na tym komputerze.",
  intro_edit:
    "Zmiana magazynów, katalogów projektów, trybu pracy i pamięci podglądów. Zapis zastępuje wszystkie ustawienia naraz; nowy albo przeniesiony magazyn jest od razu skanowany od nowa.",
  steps_label: "Kroki kreatora",
  step: {
    stores: "Magazyny",
    projects: "Projekty",
    mode: "Tryb pracy",
    save: "Zapis",
  },
  sources_title: "Źródła danych",
  sources_none: "Nie znaleziono żadnej wtyczki źródła danych.",
  store: {
    legend: "Magazyn {number}",
    name: "Nazwa",
    name_hint: "Nazwa dla ludzi, np. „Zespół”.",
    id: "Identyfikator",
    id_hint: "Krótka nazwa w adresach i API: małe litery, cyfry, „-” i „_”, najwyżej 32 znaki.",
    kartograf: "Katalog Kartografa",
    kartograf_hint:
      "Pełna ścieżka katalogu --output Kartografa (samego katalogu data/), np. /mnt/nas/kartograf/data albo Z:\\kartograf\\data.",
    kind: "Rodzaj",
    kind_auto: "wykryj automatycznie",
    add: "Dodaj magazyn",
    remove: "Usuń magazyn",
    name_required: "Wpisz nazwę magazynu.",
    kartograf_required: "Wpisz pełną ścieżkę katalogu Kartografa.",
    imgw: "Katalog IMGWTools",
    imgw_hint:
      "Pełna ścieżka katalogu głównego magazynu IMGWTools, w którym leży plik imgw-store.json, np. /mnt/nas/imgw albo Z:\\imgw. Zostaw puste, jeśli magazyn nie ma danych IMGW.",
    directory_required: "Wpisz pełną ścieżkę katalogu Kartografa albo katalogu IMGWTools.",
    id_invalid: "Identyfikator: małe litery, cyfry, „-” i „_” (najwyżej 32 znaki), na początku litera albo cyfra.",
    id_duplicate: "Dwa magazyny mają ten sam identyfikator „{id}”.",
  },
  projects: {
    legend: "Katalogi projektów",
    hint: "Archiwista szuka w nich manifestów kartograf-project.json (tylko odczyt). Możesz to pominąć i dodać je później.",
    path: "Katalog projektów {number}",
    add: "Dodaj katalog",
    remove: "Usuń katalog",
    none: "Bez katalogów projektów.",
  },
  mode: {
    legend: "Tryb pracy",
    offline: "Tryb offline",
    offline_hint:
      "Przeglądarka nie wysyła żadnych zapytań poza Archiwistę: bez podkładów mapy online. Zmiana przeładowuje stronę.",
    basemaps: "Podkłady mapy (tylko poza trybem offline):",
    basemaps_none: "brak",
  },
  previews: {
    legend: "Pamięć podglądów",
    hint: "Miniatury, kafle map i lokalne kopie plików (COG) Archiwista trzyma na tym komputerze, nigdy w magazynie ani na udziale. Ponad limit znikają najdawniej używane — każdy podgląd da się odtworzyć z pliku.",
    limit: "Limit pamięci podglądów (GB)",
    limit_hint: "Liczba całkowita od 1 do 10 000 (1 GB = 1024³ bajtów); domyślnie 20.",
    limit_invalid: "Limit pamięci podglądów to liczba całkowita od 1 do 10 000 GB.",
    usage: "Zajęte teraz: {used} z {limit} ({percent}) · {objects} {files} z podglądami",
    usage_label: "Zajętość pamięci podglądów",
    usage_none: "Serwer nie podał zajętości pamięci podglądów.",
  },
  summary: {
    legend: "Podsumowanie",
    stores: "Magazyny:",
    kartograf: "Kartograf:",
    imgw: "IMGWTools:",
    projects: "Katalogi projektów:",
    mode: "Tryb pracy:",
    online: "z podkładami online",
    previews: "Pamięć podglądów:",
    previews_value: "limit {limit} GB",
    offline: "offline",
    kind_auto: "rodzaj wykrywany automatycznie",
  },
  save: "Zapisz i zindeksuj",
  save_edit: "Zapisz ustawienia",
  saving: "Zapisywanie i sprawdzanie katalogów…",
  invalid: "Ustawienia nie zostały zapisane — popraw zaznaczone pola.",
  fix: "Popraw",
  saved: "Zapisano ustawienia.",
  reloading: "Zapisano ustawienia — przeładowanie strony z nową polityką treści…",
  progress_title: "Indeksowanie",
  progress_note:
    "Pełny skan nowego albo przeniesionego magazynu zleca harmonogram serwera; postęp pokazuje pasek stanu indeksu nad tą stroną. Możesz przejść dalej — skan trwa w tle.",
  scanning: "Trwa skan magazynu „{store}”…",
  indexed: "Magazyn „{store}” zindeksowany: {slots} {files}, {versions} {versions_word}.",
  go_start: "Przejdź do przeglądania",
  edit_again: "Zmień ustawienia",
};
