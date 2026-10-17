# Archiwista — specyfikacja

**Data:** 2026-10-17
**Status:** specyfikacja do przeglądu (bez kodu aplikacji); decyzje:
[`docs/DECISIONS.md`](DECISIONS.md); mockup interfejsu: `mockup/` na gałęzi
`feat/mockup` (sekcja 16)
**Zależność:** Kartograf 0.8.0 (`develop`) — publiczne API
(`kartograf/__init__.py`, `__all__`) i formaty na dysku: sidecar
`kartograf-meta/1`, układ `data/` z magazynem wersji (`versions/`), manifest
projektu `kartograf-project/1`, plan aktualizacji `kartograf-plan/1`, raport
dostępności `kartograf-availability/1`
**Dokumenty źródłowe (repozytorium Kartografa):** `docs/ARCHITECTURE.md` 1
i 3.1-3.5, `docs/USAGE.md`, `docs/SCOPE.md` 3.3 (roadmapa, zasady nakładek),
`docs/DECISIONS.md` ADR-022, ADR-024, ADR-027, ADR-036, ADR-037, ADR-039 do
ADR-044, spec manifestu `docs/superpowers/specs/2026-10-15-manifest-projektu-design.md`

Konwencje dokumentu: nazwy z Kartografa (funkcje, pola sidecara, katalogi)
zapisuję w `kodzie`; teksty interfejsu w cudzysłowie „…”; prawdziwe
ścieżki danych zastępuje `<katalog-danych>`. Odwołania „ARCH”, „USAGE”,
„SCOPE” i „ADR-0xx” bez dopisku dotyczą dokumentów Kartografa; decyzje
Archiwisty mają postać „A-ADR-0xx” (`docs/DECISIONS.md` w tym repozytorium).

---

## 1. Cel i użytkownicy

### 1.1 Problem

Kartograf zapisuje dane w uporządkowanym magazynie, ale magazyn szybko
rośnie: dziesiątki tysięcy plików, kilka wersji tego samego arkusza (loty,
wydania), wiele projektów przypinających różne wersje, dane PL i CZ
w różnych układach, na dysku lokalnym albo na udziale sieciowym. Proste
pytania wymagają dziś znajomości CLI, reguł katalogów `data/` i czytania
plików JSON:

- „Co mam w magazynie dla tej zlewni i z którego roku?”
- „Z którego roku źródło ma komplet arkuszy dla tego obszaru?”
- „Czy jest nowszy nalot niż ten, którego używa projekt?”
- „Których plików użył projekt X i czy są nienaruszone?”
- „Jak to wszystko wczytać do QGIS jednym ruchem?”
- „Czym różni się lot 2019 od 2025 na tym arkuszu?”

### 1.2 Cel

Archiwista to manager magazynu Kartografa w przeglądarce. Pozwala:

1. **Widzieć** — przegląd i wyszukiwanie archiwum, mapa z obrysami
   i podglądami, wersje, pochodzenie, licencje, projekty.
2. **Sprawdzać** — dostępność danych dla zaznaczonego obszaru lokalnie
   (magazyn) i u źródła (GUGiK, CUZK), aktualność wersji, integralność
   przypiętych plików.
3. **Działać** — pobierać, aktualizować i przypinać dane w projektach;
   każde działanie wykonuje publiczne API Kartografa w tle, z postępem,
   komunikatami i anulowaniem.
4. **Przygotować do łączenia** — mozaika arkuszy, zestawienie PL + CZ,
   zestaw do projektu QGIS, porównanie wersji (sekcja 8).
5. **Zlecać w języku naturalnym** — asystent (agent LLM) planuje
   przygotowanie danych, a wykonuje je dopiero po potwierdzeniu
   użytkownika (sekcja 7).

**Nadrzędna zasada (jak w Kartografie): układ, interfejs i API proste,
zrozumiałe i wygodne dla ludzi.** W praktyce:

- ludzkie nazwy zamiast katalogów („NMT 1 m · PL-1992 · EVRF2007” zamiast
  `nmt/pl_1992_1m_evrf2007`), a surowa wartość zawsze o jedno kliknięcie;
- każde działanie z siecią albo zapisem najpierw pokazuje plan (co, ile
  plików, ile już jest lokalnie, ile danych, dokąd), a po wykonaniu —
  co się stało;
- zero cichych zmian: nic nie jest pobierane, przepinane ani nadpisywane
  bez jawnej decyzji człowieka;
- komunikaty Kartografa (`Info:`, `Warning:`, błędy) pokazujemy bez
  przeróbek — ten sam tekst co w CLI;
- każde działanie da się powtórzyć z wiersza poleceń: Archiwista pokazuje
  odpowiadające polecenie `kartograf …` do skopiowania.

### 1.3 Granice (czym Archiwista nie jest)

- **Nie jest programem GIS.** Podglądy służą rozpoznaniu danych, a nie
  analizie; analizy robi się w QGIS (Archiwista przygotowuje do tego
  zestaw, sekcja 8.4).
- **Nie pobiera i nie przetwarza danych sam.** Robi to Kartograf (SCOPE
  3.3: nakładki wołają wyłącznie publiczne API biblioteki i nie mają
  własnej logiki pobierania ani obróbki). Brakująca funkcja Kartografa to
  wymaganie wobec Kartografa (sekcja 12), a nie obejście w Archiwiście.
- **Nie usuwa danych z magazynu** (Kartograf niczego nie usuwa; sekcja 15,
  P4).
- **Nie trzyma niczego na udziale sieciowym.** Indeks, podglądy i historia
  zadań leżą lokalnie i można je w każdej chwili odbudować; źródłem prawdy
  są sidecary i manifesty (SCOPE 3.3).
- **Nie zastępuje wtyczki QGIS** (podprojekt 4 roadmapy Kartografa). Zastępuje
  podprojekt 5 („GUI webowe”) i jest osobnym projektem (A-ADR-001).

### 1.4 Użytkownicy i tryby pracy

| Persona | Kim jest | Czego potrzebuje od Archiwisty |
|---|---|---|
| **Ola, hydrolożka** | Przygotowuje dane do modelu zlewni; zna QGIS, CLI używa rzadko | obszar na mapie → co jest dostępne i z którego roku → pobierz → zestaw do QGIS |
| **Marek, specjalista GIS** | Zna Kartografa i CLI | przegląd wersji i kampanii, mozaiki, porównania lotów, kontrola aktualności, dane z pogranicza PL/CZ |
| **Zespół projektowy (później)** | Kilka osób, wspólny magazyn na udziale SMB | które projekty używają których danych, kto i kiedy pobrał, co można zaktualizować — bez pobierania tego samego dwa razy |
| **Deweloper Hydrografa/Hydrologa** | Używa Kartografa jako biblioteki | sprawdzenie zawartości magazynu, ścieżki niezmiennych wersji do skryptów |

Tryby pracy:

- **Lokalny (od v0.1, domyślny):** jedna osoba, serwer na `127.0.0.1`,
  bez logowania; magazyn na dysku lokalnym albo na udziale SMB.
- **Zespołowy (v0.8):** jeden serwer Archiwisty w sieci lokalnej
  z logowaniem i rolami, wspólny magazyn na udziale SMB bez blokad zakresów
  bajtów (A-ADR-013; sekcja 15, P1). Architektura od v0.1 nie zakłada, że
  przeglądarka i serwer widzą ten sam system plików (sekcja 5.1).

## 2. Słownik pojęć

Jedno słownictwo w dokumentacji, interfejsie i API. Pojęcia Kartografa
zachowują jego znaczenie.

| Pojęcie | Znaczenie | Źródło |
|---|---|---|
| **Magazyn** | Katalog `--output` Kartografa (`output_dir`) z układem `data/`: katalogi produktów, segmenty, wersje. Archiwista obsługuje kilka magazynów (np. lokalny i zespołowy) | ARCH 3.3 |
| **Produkt** | Rodzaj danych wybierany `--product` w grupie komend (NMT, ortofotomapa, BDOT10k, granice PRG…); katalog najwyższego poziomu magazynu | ARCH 3.3 reguła 10 |
| **Źródło (zbiór)** | Deskryptor Kartografa; klucz `<kraj>.<dostawca>.<nazwa>` = pole `dataset` sidecara, np. `pl.gugik.nmt_1m` | ARCH 3.1 |
| **Segment** | Katalog `<produkt>/<kraj>_<tokeny>` — jeden wariant treści (układ, rozdzielczość, układ wysokości, format, rocznik, poziom…), np. `nmt/pl_1992_1m_evrf2007` | ARCH 3.3 reguły 1, 8-10 |
| **Jednostka** | Obszar jednego pliku: godło arkusza, kafel, TERYT, KU, kod kraju albo wycinek `<coords>` | `UnitFile.unit`, `PlanItem.unit` |
| **Slot (miejsce pliku)** | Segment + hierarchia jednostki + nazwa pliku, czyli „ten plik” niezależnie od wersji, np. `nmt/pl_1992_1m_evrf2007` + `N-34/130/D/d/2/4` + `N-34-130-D-d-2-4.asc` | `PlanItem` (`segment`, `hierarchy`, `name`) |
| **Wersja** | Niezmienna treść slotu: `<segment>/versions/<hierarchia>/<etykieta>_<sha8>/<plik>` z sidecarem wersji; tożsamość wersji = SHA-256 treści | ADR-036 |
| **Etykieta wersji** | Czytelna nazwa wersji: kampania `<data>_<id>` (np. `2025-04-26_82710`), wydanie (`2.0`, `2024`, `2024_2025-02-06`) albo data pobrania; skąd — mówi `extra.version.label_source` | ARCH 3.3 reguła 6 |
| **Bieżąca wersja** | Wersja, na którą wskazuje ścieżka standardowa `<segment>/<hierarchia>/<plik>` (dowiązanie twarde do najnowszej lokalnej wersji); `full_sheet/` wskazuje najnowszy pełny lot | ARCH 3.3 reguły 6-7 |
| **Sidecar** | `<plik>.meta.json` (`kartograf-meta/1`): pochodzenie, układy, `nodata`, zadanie, licencja, `sha256`. Sidecar wersji jest niezmienny; sidecar ścieżki standardowej to kopia z celem dowiązania (`extra.link_target`) | ARCH 3.2 |
| **Kampania (lot, nalot)** | Pomiar GUGiK arkusza: data aktualności i numer zgłoszenia pracy; rok kampanii = rok danych | ADR-028, ADR-030 |
| **Wydanie** | Wersja publikacji źródła bez kampanii: rocznik BDOT10k, `2.0` SoilGrids, data wpisu feedu ATOM CUZK | ADR-036 D29, ADR-042 |
| **Arkusz pełny / niepełny** | Rekord skorowidza `TAK`/`NIE` (`czy_ark_wypelniony`, w sidecarze `extra.source.full_sheet`): czy arkusz jest w całości wypełniony treścią | ARCH 3.2 |
| **Zadanie Kartografa (obszarowe)** | Jedno wywołanie dla obszaru; jego pliki — także po obu stronach granicy PL/CZ — łączy wspólne `extra.parent_request` | ARCH 3.4 |
| **Projekt** | Katalog z `kartograf-project.json` (`kartograf-project/1`): zadania projektu (komendy danych z opcjami) i przypięte wersje plików | ARCH 3.5, ADR-040 |
| **Zadanie projektu** | Wpis `tasks[]` manifestu: nazwa, komenda (np. `elevation download`) i opcje | spec manifestu 3.3 |
| **Przypięcie** | Wpis `files[]` zadania projektu: która wersja (`version`, `sha256`) jest używana | spec manifestu 3.3 |
| **Dostępność** | Co źródło ma dla obszaru: lata, warianty, kompletność arkuszy — raport `check_availability` (`kartograf-availability/1`) | ADR-041 |
| **Aktualność** | Czy lokalna albo przypięta wersja jest najnowsza u źródła — plan `check_*` (`kartograf-plan/1`; statusy `current`, `newer`, `missing`, `unverifiable`, `check_failed`) | ADR-036 |
| **Obszar** | Zaznaczenie użytkownika: prostokąt, wielokąt, plik geometrii, godło, TERYT, KU albo kraj | — |
| **Pokrycie roku** | (Archiwista) etykieta roku albo wydania dla obszaru: „pełne”, „pełne · 2 kampanie”, „częściowe · 58%”, „brak danych” — oraz osobna plakietka stanu magazynu: „pobrane”, „pobrane 5/12”, „niepobrane” | sekcja 6.4 |
| **Zestaw** | (Archiwista) wybór wersji przygotowany do użycia poza magazynem: projekt QGIS, lista ścieżek, atrybucje, VRT-owijki; generowany z projektu albo z zaznaczenia, odtwarzalny, nie jest danymi | sekcja 8.4 |
| **Produkt pochodny** | (propozycja dla Kartografa) wynik łączenia zapisany w magazynie jako wersja z sidecarem i listą wejść (`extra.source_files[]`, wzór HSG) | sekcja 8.1 |
| **Indeks** | (Archiwista) lokalna baza SQLite z opisem magazynów i projektów; pamięć podręczna, nie źródło prawdy | sekcja 4 |
| **Zadanie w tle** | (Archiwista) długa operacja — skan, sprawdzenie, pobranie, łączenie, eksport — w osobnym procesie, z postępem i anulowaniem; widok „Zadania” | sekcja 5.6 |
| **Propozycja** | (Archiwista) plan działań przygotowany przez asystenta; staje się zadaniami w tle dopiero po potwierdzeniu użytkownika | sekcja 7 |

„Zadanie” bez dopisku nie występuje w interfejsie: zawsze „zadanie
projektu” (Kartograf) albo „zadanie w tle” (Archiwista).

## 3. Przypadki użycia

Każdy przypadek: kto i w jakiej sytuacji, przebieg w interfejsie, co
dzieje się pod spodem (wywołania Kartografa) i po czym poznać sukces.
Przykładowy obszar „Kraków” to bbox `561000,239000,573000,249000`
(EPSG:2180, 120 km²) — ten sam, którego używa mockup (sekcja 16).

### UC-01. Obszar → produkt → dostępność → pobranie (główny przepływ)

**Ola** przygotowuje NMT dla zlewni i nie wie, z którego roku jest komplet
arkuszy.

1. W widoku „Mapa” zaznacza obszar: rysuje prostokąt albo wielokąt, wpisuje
   godło albo TERYT, albo wczytuje `zlewnia.gpkg`.
2. Z listy produktów wybiera „NMT” (grupa „Wysokości”).
3. Archiwista od razu pokazuje stan magazynu (z indeksu, bez sieci),
   a w tle uruchamia sprawdzenie u źródła: `check_availability(product="nmt",
   country="pl", bbox=…)`.
4. Wynik pojawia się jako warstwy lat na mapie i w panelu „Zestawienie”:
   2023 „pełne · 2 kampanie” z plakietką „pobrane 5/12”, 2022 „częściowe ·
   58%”, a przy 2019 dopisek „1 ark. niepełny” (definicje: sekcja 6.4). Ola
   przełącza panel na „Oś czasu”, a mapę na „Stos”, żeby zobaczyć lata
   jednym spojrzeniem.
5. Przy roku 2023 klika „Pobierz…”. Okno planu (`check_data(…, year=2023)`)
   mówi: 12 arkuszy, 5 już w magazynie, 7 do pobrania, ok. 265 MB, zapis do
   magazynu „Zespół”; pokazuje polecenie `kartograf elevation download …`
   i opcję „Dodaj jako zadanie projektu”.
6. Po potwierdzeniu startuje zadanie w tle (`download_data(…)`). Arkusze na
   mapie zmieniają kolor w miarę pobierania; komunikaty Kartografa
   pojawiają się w zadaniu.

**Sukces:** plakietka roku zmienia się na „pobrane”, nowe wersje są
w katalogu, a magazyn jest bajtowo taki sam jak po tym samym poleceniu
z CLI.

### UC-02. „Co już mam?” bez sieci

**Marek** jest w terenie bez internetu. Zaznacza obszar i wybiera „Wszystkie
produkty”. Archiwista pokazuje tylko magazyn (indeks): pliki przecinające
obszar, pogrupowane wg produktu i roku danych, z lokalnym pokryciem
obszaru. Sprawdzenie u źródła jest wyłączone z komunikatem „Brak sieci —
pokazuję tylko magazyn”; jeśli wcześniej sprawdzano ten obszar, widać
ostatni raport z datą.

**Sukces:** odpowiedź w sekundę, bez jednego zapytania sieciowego.

### UC-03. Wyszukiwanie po identyfikatorze

Marek wkleja do pola wyszukiwania godło `N-34-130-D-d-2-4`, TERYT `1465`,
numer zgłoszenia `GK-FOTO.6201.11.2025` albo początek sumy `fdd30535`.
Archiwista rozpoznaje rodzaj identyfikatora i pokazuje pasujące sloty
wszystkich produktów; filtry zawężają wynik (sekcja 6.5).

### UC-04. Karta pliku i historia wersji

Ola otwiera arkusz `N-34-130-D-d-2-4`. „Karta pliku” pokazuje oś wersji
(loty 2019, 2023, 2025), która wersja jest bieżąca, która pełna
(`full_sheet/`), które projekty przypinają którą wersję, metadane po
ludzku („skaning laserowy, błąd średni wysokości 0,06 m, arkusz pełny”),
licencję z przyciskiem „Kopiuj atrybucję”, podgląd oraz akcje: „Kopiuj
ścieżkę wersji”, „Polecenie Kartografa”, „Sprawdź aktualność”, „Porównaj
wersje”, „Dodaj do projektu”.

### UC-05. Czy są nowsze dane?

Marek zaznacza segment w obszarze albo cały projekt i klika „Sprawdź
aktualność”. Zadanie w tle wywołuje `check_*` (albo `check_project`)
i pokazuje plan po ludzku: „aktualne”, „nowsza: 2025-04-26_82710”, „nie da
się sprawdzić bez pobrania”, „błąd sprawdzenia: …”. Przycisk „Pobierz
nowsze” wykonuje ten sam plan (`update="upgrade"`, `plan=…`), a pozycje,
które w międzyczasie się zmieniły, Kartograf zgłasza jako nieaktualne.

### UC-06. Projekt: przypięcia, weryfikacja, aktualizacja

Ola otwiera projekt „Raba”: zadania projektu z opcjami (pokazanymi jako
polecenia Kartografa) i przypięte wersje. „Status” odpowiada natychmiast
(`get_project_status`), „Weryfikuj” liczy sumy SHA-256 w tle
(`verify_project`), „Sprawdź aktualizacje” porównuje przypięcia ze źródłem
(`check_project`), „Przepnij” przechodzi na nowsze dane jednego zadania
(`download_project(update="upgrade", tasks=["teren"])`). Z wyniku
dostępności (UC-01) dodaje zadanie „Dodaj rok 2025 do projektu”
(`add_project_task` z `year=2025`).

### UC-07. Które projekty używają tego pliku?

Kierownik zespołu przed porządkami w magazynie filtruje „Nieużywane przez
żaden projekt” i „Niebieżące wersje”, widzi ich zajętość i listę.
Na karcie pliku widać „Przypięta w: Raba (teren), Wisła-2026 (dem)”.
Archiwista niczego nie usuwa; raport służy decyzji (sekcja 15, P4).

### UC-08. Mozaika arkuszy

Marek potrzebuje NMT 0,5 m z 2023 dla obszaru jako jednej warstwy.
Z wiersza roku wybiera „Łączenie › Mozaika”: VRT (natychmiast, bez kopii
danych) albo GeoTIFF na wspólnej siatce przycięty do obszaru. Plan pokazuje
wejścia (konkretne wersje), siatkę i rozmiar wyniku. Wynik trafia do
magazynu jako produkt pochodny z sidecarem (sekcja 8.2).

### UC-09. Pogranicze PL + CZ

Marek modeluje zlewnię Olzy. Obszar przecina granicę; dostępność pokazuje
lata PL i bieżące modele CZ. Pobranie idzie jednym zadaniem Kartografa
(`country="auto"`, `cutout=True`, wspólny `horizontal_crs`, układ wysokości
`pl=EVRF2007,cz=EVRF2007`); pliki PL i CZ są zgrupowane po
`extra.parent_request`. „Łączenie › PL + CZ” daje dziś zestaw bez scalania
(obie warstwy w projekcie QGIS), a po dodaniu funkcji do Kartografa —
jedną powierzchnię na wspólnej siatce (sekcja 8.3).

### UC-10. Zestaw do QGIS

Ola wybiera w projekcie „Zestaw QGIS”. W katalogu projektu powstaje
`zestawy/<nazwa>/` z plikiem `.qgz`, listą ścieżek i atrybucjami. QGIS
otwiera projekt bez pytań o układy, a warstwy wskazują dokładnie przypięte
wersje (sekcja 8.4).

### UC-11. Porównanie lotów

Marek porównuje loty 2019 i 2025 jednego arkusza: tabela różnic metadanych,
kurtyna na mapie, a po dodaniu funkcji do Kartografa — model różnic
wysokości ze statystyką („średnia zmiana −0,04 m; 2,1 ha zmian > 0,5 m”)
(sekcja 8.5).

### UC-12. Asystent

Ola pisze: „Przygotuj NMT 1 m i ortofotomapę dla zaznaczonego obszaru
z najnowszego roku z pełnym pokryciem i dodaj do projektu Raba”. Asystent
odczytuje zaznaczenie, sprawdza dostępność (tylko odczyt), wybiera rok
i przedstawia propozycję: dwa polecenia Kartografa, 24 arkusze, 9 już
lokalnie, ok. 1,2 GB, dwa nowe zadania projektu; arkusze propozycji są
podświetlone na mapie. Dopiero „Wykonaj” uruchamia zadania w tle; po ich
zakończeniu asystent podsumowuje wynik (sekcja 7).

### UC-13. Kondycja magazynu

Marek otwiera „Magazyn › Stan”: zajętość wg produktów (każda wersja liczona
raz), a obok problemy z wyjaśnieniem i poleceniem naprawy: segmenty
nierozpoznane (np. nazwy z wersji deweloperskiej 0.8.0-dev), pliki bez
sidecara, katalogi `kampanie/` z 0.7.x, pozostałości `versions/.incoming/`
starsze niż 24 h, sidecary dowiązań wskazujące brakującą wersję, przypięcia
projektów bez pliku w magazynie.

### UC-14. Zespół (od v0.8)

Kasia loguje się do Archiwisty zespołu. Widzi historię („Marek pobrał NMT
2025 dla Raby, wczoraj 14:02”) i wspólną kolejkę zadań, więc nie pobiera
tego samego drugi raz. Jako „czytelnik” przegląda dane i tworzy zestawy;
pobierać może „operator” (sekcja 10.2).

### UC-15. Wklejone polecenie Kartografa

Marek wkleja `kartograf elevation download --product nmt --sheet … -o
./data`. Archiwista rozpoznaje polecenie (ten sam parser co
`kartograf project add`), wypełnia formularz, zamienia `-o` na wybrany
magazyn, pokazuje plan i uruchamia zadanie w tle.

## 4. Model danych i indeks

### 4.1 Co czytamy z dysku (źródła prawdy)

Archiwista nie ma własnych danych o magazynie poza pamięcią podręczną.
Wszystko, co pokazuje, wynika z plików Kartografa:

| Plik | Gdzie | Zmienność | Jak czytamy |
|---|---|---|---|
| Sidecar wersji | `<segment>/versions/<hierarchia>/<etykieta>_<sha8>/<plik>.meta.json` | niezmienny (ADR-036) | raz, przy pierwszym zobaczeniu katalogu wersji |
| Plik danych wersji | obok sidecara wersji | niezmienny | podczas indeksowania wyłącznie `stat` (rozmiar); treść tylko na żądanie (podgląd, weryfikacja) |
| Sidecar ścieżki standardowej i `full_sheet/` | `<segment>/<hierarchia>/<plik>.meta.json`, `<segment>/full_sheet/…` | zmienny (dowiązanie przestawiane na nowszą wersję) | przy zmianie rozmiaru albo czasu modyfikacji; cel dowiązania wyłącznie z `extra.link_target` |
| Manifest projektu | `<katalog projektu>/kartograf-project.json` | zmienny | przy zmianie czasu modyfikacji albo sumy pliku; zawsze przez `open_project` (ścisła walidacja Kartografa) |
| Plan aktualizacji | plik `kartograf-plan/1` zapisany `--plan` | jednorazowy | na żądanie (import planu z CLI) |

Pozostałości i przypadki brzegowe są pokazywane, nigdy pomijane po cichu:
katalogi robocze `versions/.incoming/` (pomijane przy indeksowaniu;
Kartograf sprząta je po 24 h, starsze zgłaszamy), katalogi `kampanie/`
z 0.7.x (nieczytane przez Kartografa 0.8.0), segmenty spoza rejestru (np.
`orto/pl_2000_oblique` z wersji deweloperskiej 0.8.0-dev — w przykładowym
magazynie testu na żywo wydania 0.8.0 są takie katalogi i sidecary
z dawnymi kluczami źródeł, np. `cz.cuzk.hy_net`), pliki bez sidecara,
sidecary nieczytelne i sidecary sprzed ADR-031 (polskie klucze: brak klucza
= brak informacji, jak w Kartografie).

**Archiwista nie zapisuje niczego w magazynie.** W katalogu projektu
zapisuje wyłącznie katalog zestawu (sekcja 8.4); manifest zmienia tylko
API Kartografa (A-ADR-003).

### 4.2 Odczyt przez API Kartografa

Reguły układu `data/` (ARCH 3.3, reguły 1-10), rozpoznawanie dowiązań,
tolerancyjne czytanie starych sidecarów i wyliczanie zasięgu pliku to
wiedza o formacie Kartografa. Archiwista nie ma własnego czytnika tego
formatu: korzysta z pakietu wymagań **KA** (sekcja 12: `iter_store`,
`read_sidecar`, `describe_segment`, `file_footprint`, `link_target`,
`pinned_transform`). Dzięki temu zmiana układu w Kartografie nie
rozjedzie się z Archiwistą, a wtyczka QGIS i Hydrograf mogą korzystać
z tych samych funkcji. Konsekwencja: v0.1 wymaga wydania Kartografa z KA
(A-ADR-014).

### 4.3 Indeks lokalny

Indeks to plik SQLite (tryb WAL) na dysku lokalnym, w katalogu danych
użytkownika (`platformdirs`: Linux `~/.local/share/archiwista/`, Windows
`%LOCALAPPDATA%\Archiwista\`); obok leżą pamięć podglądów (`cache/`)
i dzienniki zadań (`jobs/`). Konfiguracja (magazyny, katalogi projektów,
limity, dostawca asystenta) jest w czytelnym pliku TOML w katalogu
konfiguracji użytkownika i w widoku „Ustawienia”. Indeks można usunąć
w każdej chwili — „Przebuduj indeks” odtworzy go z magazynów i manifestów;
tracona jest tylko historia zadań i rozmów asystenta.

Zawartość (tabele logiczne; schemat ustali plan implementacji):

| Tabela | Co trzyma |
|---|---|
| `stores` | magazyny: identyfikator (krótka nazwa nadana przez użytkownika, np. `zespol`), ścieżka i aliasy ścieżek, dostępność, czasy i statystyki skanów |
| `segments` | segmenty: produkt, źródło (`dataset`), ludzka nazwa (`describe_segment`), rozpoznany / nierozpoznany |
| `slots` | sloty: segment, hierarchia, nazwa, rodzaj i kod jednostki, bieżąca wersja, wersja `full_sheet/`, liczba wersji |
| `versions` | wersje: etykieta i jej źródło, `sha256`, rozmiar, układy, rozdzielczość, `nodata`, rok i data danych, kampania i numer zgłoszenia, wydanie, data pobrania, pełny arkusz, pokrycie (`extra.coverage`), licencja, klucz grupy `parent_request`, zasięg natywny i jego źródło, stan, pełny sidecar (JSON) |
| `footprints` | R*Tree: zasięg wersji w WGS84 (filtr obszaru i mapa) |
| `search` | FTS5: godła, TERYT, KU, etykiety, numery zgłoszeń, nazwy plików, ludzkie nazwy produktów, nazwy projektów i zadań projektów |
| `projects`, `project_tasks`, `pins` | znane projekty, ich zadania i przypięcia powiązane z wersjami — indeks „które projekty używają pliku” (SCOPE 3.3) |
| `availability` | ostatnie raporty dostępności per obszar i produkt, z datą (widoczne bez sieci) |
| `jobs`, `job_events` | historia zadań w tle i ich zdarzenia |
| `conversations`, `messages`, `proposals` | rozmowy z asystentem i jego propozycje |

Atrybuty do filtrów są wyliczane przy indeksowaniu z sidecara przez
`read_sidecar` (KA-2), który normalizuje pola różniące się między
produktami: **rok danych** (kampania, data lotu LAZ, rocznik wydania) jest
osobnym polem niż **data pobrania** i nigdy nie jest nią zastępowany;
wersja bez roku danych ma rok pusty, a nie rok pobrania.

**Zasięg (obrys) pliku** liczy `file_footprint` (KA-4) wg kolejności
źródeł: `request.bbox` z `bbox_crs` (wycinki, wyniki obszaru kolekcji,
SoilGrids, HSG) → godło z parsera (PL-1992, PL-2000, TM33) → nagłówek pliku
(GeoTIFF, ASC, JPEG z JGW, GeoPackage, LAS) → jednostka (TERYT z PRG, KU
z RUIAN, arkusz SM5 z indeksu CUZK — z siecią i pamięcią podręczną) → kraj.
Zasięg bez źródła oznaczamy „bez obrysu” (plik jest na liście, nie ma go
na mapie). Przeliczenie do WGS84 wyłącznie przypiętą transformacją
Kartografa (KA-6): domyślny transformator potrafi cicho użyć operacji
przybliżonej, a dla S-JTSK to przesunięcie rzędu 100 m (ADR-024).

### 4.4 Budowa i odświeżanie

- **Pełny skan** (pierwsze uruchomienie, „Przebuduj indeks”): przejście
  drzewa `iter_store` z odczytem sidecarów w puli wątków (opóźnienia SMB,
  nie procesor), zapis do indeksu paczkami w transakcjach; zadanie w tle
  z postępem.
- **Skan przyrostowy:** katalogi wersji `<etykieta>_<sha8>` są niezmienne,
  więc znanych wersji nie czytamy ponownie — sprawdzamy tylko pojawienie
  się nowych katalogów wersji, zniknięcie znanych i zmianę sidecarów
  dowiązań. Czas modyfikacji katalogu jest tylko wskazówką (na udziale
  z pamięcią atrybutów bywa opóźniony), dlatego okresowo wykonujemy pełny
  skan kontrolny (domyślnie raz na dobę, w tle).
- **Odświeżenie na żądanie dla widoku:** gdy użytkownik pyta o obszar
  i produkt, Archiwista najpierw odświeża dokładnie te sloty (katalogi
  hierarchii jednostek obszaru), a dopiero potem pokazuje stan magazynu —
  odpowiedź na bieżące pytanie jest aktualna w sekundach także na SMB,
  niezależnie od pełnych skanów.
- **Po własnych zadaniach:** wynik Kartografa (`files[].file.version_path`,
  przypięcia projektu) trafia do indeksu od razu, bez skanu.
- **Wyzwalacze:** start aplikacji (przyrostowy, jeśli ostatni starszy niż
  15 min), interwał (domyślnie 15 min dla udziału, 5 min dla dysku
  lokalnego), przycisk „Odśwież” (magazyn, segment, widok), koniec zadania
  w tle; obserwacja zmian systemu plików tylko dla dysków lokalnych
  (opcjonalnie).
- **Magazyn niedostępny** (brak katalogu albo pusty punkt montowania):
  skan przerwany, indeks bez zmian, baner „Magazyn niedostępny od 14:02 —
  pokazuję stan z indeksu”; działania zapisu wyłączone. Nigdy nie
  oznaczamy całego magazynu jako usuniętego z powodu odłączonego udziału.
- **Zniknięcia:** wersja, której nie ma po pełnym przejściu, dostaje stan
  „brak pliku” (z datą); przypinające ją projekty są oznaczone. Wpis
  znika z indeksu dopiero po kolejnym pełnym skanie.
- **Zmiana schematu indeksu** w nowej wersji Archiwisty = przebudowa (to
  pamięć podręczna — bez migracji).
- Polecenia Kartografa wykonywane poza Archiwistą (CLI, Hydrograf) są
  normalną sytuacją: indeks zobaczy je przy najbliższym odświeżeniu.

### 4.5 Wydajność

Magazyn odniesienia: 50 000 slotów, 80 000 wersji (ok. 260 000 plików
z sidecarami i dowiązaniami, ok. 150 000 katalogów), 30 projektów; udział
SMB 3 w sieci 1 Gb/s albo dysk lokalny SSD. Cele (kryteria akceptacji v0.1,
test na magazynie syntetycznym z generatora, sekcja 11):

| Operacja | Udział SMB | Dysk lokalny |
|---|---|---|
| pierwszy pełny skan | ≤ 10 min | ≤ 2 min |
| skan przyrostowy bez zmian (w tle) | ≤ 3 min | ≤ 20 s |
| odświeżenie widoku (obszar + produkt, ≤ 500 slotów) | ≤ 5 s | ≤ 1 s |
| zapytanie listy (strona 50 wierszy), p95 | ≤ 200 ms | ≤ 200 ms |
| obrysy w widoku mapy (≤ 5 000 obiektów; powyżej agregacja do siatki), p95 | ≤ 300 ms | ≤ 300 ms |
| wyszukiwanie tekstowe, p95 | ≤ 200 ms | ≤ 200 ms |
| karta pliku bez podglądu, p95 | ≤ 200 ms | ≤ 200 ms |

Indeks ≤ 500 MB dla 80 000 wersji; pamięć serwera ≤ 500 MB bez podglądów.
Interfejs nigdy nie czeka na skan: zapytania idą do indeksu, a stan
indeksu („Indeks z 14:02, skan trwa: 63%”) jest zawsze widoczny.

### 4.6 Praca na udziale SMB

1. Na udziale nie ma żadnego pliku Archiwisty (SQLite, pamięć, blokady).
   Archiwista tylko czyta; zapisy wykonuje Kartograf, który działa bez
   blokad zakresów bajtów (wersje przez `os.link`, manifest przez blokadę
   `mkdir` i `os.replace`).
2. Cel dowiązania wyłącznie z sidecara dowiązania (`extra.link_target`).
   Żadnej logiki na numerach i-węzłów ani licznikach dowiązań: na udziale
   CIFS przykładowego magazynu ścieżka standardowa i jej wersja zwróciły
   różne numery i-węzłów i różne liczniki dowiązań (pomiar 2026-10-17).
   Potwierdzenie treścią na takich udziałach robi Kartograf (KA-5).
3. Zajętość = suma rozmiarów plików w `versions/` (każda wersja raz);
   suma po ścieżkach liczyłaby dowiązania twarde wielokrotnie.
4. GeoPackage z magazynu otwieramy tylko do odczytu jako niezmienny
   (`immutable=1`): wersje się nie zmieniają, a zwykłe otwarcie SQLite na
   udziale zakłada blokady.
5. Plik, który zniknął między listowaniem a odczytem, jest pomijany
   i sprawdzany ponownie w następnym skanie.
6. Nie podążamy za dowiązaniami symbolicznymi wychodzącymi poza magazyn.
7. Ten sam udział bywa zamontowany pod różnymi ścieżkami (`Z:\kartograf`,
   `/mnt/nas/kartograf`): magazyn w konfiguracji ma aliasy ścieżek. Manifest
   projektu musi wskazywać magazyn poprawnie dla procesu, który pobiera
   (Kartograf czyta `output_dir` sam) — dlatego w zespole zalecamy względne
   `output_dir`, gdy projekty i magazyn leżą na tym samym udziale,
   a poprawkę ścieżki robi funkcja Kartografa (KH-1), nie ręczna edycja
   przez Archiwistę.
8. Udział niepodłączony — jak w 4.4: baner, bez skanu i bez zadań zapisu
   (Kartograf i tak wymaga istniejącego katalogu magazynu).

### 4.7 Projekty

- **Odkrywanie:** katalogi projektów z konfiguracji są przeszukiwane
  w poszukiwaniu `kartograf-project.json` (głębokość ≤ 4, z pominięciem
  `.git`, katalogów magazynów i katalogów ukrytych); projekt można też
  dodać ręcznie albo utworzyć (`init_project`).
- **Odczyt:** zawsze `open_project`. Niepoprawny manifest jest widoczny
  z tekstem błędu Kartografa (np. „nieznany klucz 'optons'”).
- **Powiązanie z magazynem:** `output_dir` projektu dopasowujemy do
  skonfigurowanego magazynu po ścieżce rozstrzygniętej albo aliasie; brak
  dopasowania — „Magazyn projektu nieznany: dodaj magazyn”.
- **Przypięcia → wersje:** po ścieżce `version` (względnej do magazynu)
  i `sha256`; przypięcie bez wersji w indeksie ma stan „brak pliku”.
- **Indeks użycia** („Przypięta w: …”) to tabela przypięć; nic nie trafia
  do sidecarów (sidecar jest niezmienny, SCOPE 3.3).
- **Zmiany manifestu** wykrywamy po czasie modyfikacji i sumie pliku;
  manifest zmieniony w trakcie pracy (inny proces, CLI) jest czytany
  ponownie przed każdą akcją, a konflikt zgłasza Kartograf (blokada
  `.kartograf-project.lock`, scalanie per zadanie).

## 5. Architektura

### 5.1 Przegląd

```mermaid
flowchart LR
  UI["Przeglądarka: SPA<br/>Mapa, Stos, Katalog, Zestawienie,<br/>Karta pliku, Zadania, Asystent"]
  subgraph S["Serwer Archiwisty (127.0.0.1)"]
    API["API HTTP /api/v1 + SSE"]
    SVC["Warstwa usług"]
    IDX[("Indeks SQLite<br/>(lokalny)")]
    PRV["Podglądy<br/>rio-tiler + pamięć"]
    SUP["Nadzorca zadań w tle"]
    AG["Asystent<br/>adapter dostawcy modelu"]
  end
  W["Procesy robocze<br/>(API Kartografa)"]
  MAG[("Magazyn Kartografa<br/>dysk lokalny albo SMB")]
  PRJ[("Katalogi projektów<br/>kartograf-project.json")]
  SRC["GUGiK, CUZK, CLMS, ISRIC"]
  LLM["Dostawca modelu<br/>albo model lokalny"]
  UI <--> API
  API --> SVC
  SVC --> IDX
  SVC --> PRV
  SVC --> SUP
  SVC --> AG
  AG --> LLM
  SUP --> W
  W --> MAG
  W --> PRJ
  W --> SRC
  SVC -. "odczyt (KA, open_project)" .-> MAG
  SVC -.-> PRJ
  PRV -. odczyt .-> MAG
```

Zasady architektury:

- **API najpierw.** Jedno API HTTP (`/api/v1`, sekcja 9) obsługuje
  przeglądarkę, narzędzia asystenta i skrypty użytkownika. Interfejs nie
  ma żadnej ścieżki obok API.
- **Kartograf w jednym miejscu.** Kod Archiwisty importuje Kartografa
  wyłącznie w module adaptera (`archiwista/adapter/`); test pilnuje, że
  nigdzie indziej (wzór: test importów CLI w Kartografie, ADR-037 Z1).
  Adapter tłumaczy, nie decyduje: żadnych reguł danych, wyboru arkuszy,
  wersji ani transformacji.
- **Operacje długie i zapisujące w procesach roboczych.** Serwer nie
  wykonuje pobrań ani obliczeń w swoim procesie; awaria GDAL-a albo
  przerwanie zadania nie kładzie interfejsu (5.6).
- **Przeglądarka nie zna systemu plików serwera.** Pliki są wskazywane
  identyfikatorami z indeksu i serwowane przez API — tak samo lokalnie
  i w trybie zespołu. Ścieżki do skopiowania (np. do QGIS) pokazujemy
  w postaci właściwej dla klienta (aliasy ścieżek, 4.6).
- **Każde działanie ma wykonawcę.** Lokalnie „lokalny użytkownik”,
  w zespole zalogowana osoba — historia zadań i dziennik działań od v0.1
  zapisują, kto i co zlecił.

### 5.2 Wybór technologii

Użytkownik zostawił wybór technologii wolny. Decyzje (szczegóły:
A-ADR-004 do A-ADR-008, A-ADR-011, A-ADR-015):

| Obszar | Wybór | Odrzucone warianty i powód |
|---|---|---|
| Język serwera | **Python 3.12+** | Node.js, Go, Rust: Kartograf jest biblioteką Pythona; z innego języka zostaje wołanie CLI i parsowanie tekstu — dokładnie to, co Kartograf odrzucił w ADR-037 (opcja C) |
| Framework HTTP | **FastAPI + Uvicorn + Pydantic 2** — typowane modele = schemat OpenAPI dla interfejsu, asystenta i skryptów; ten sam wybór co Hydrograf (jego ADR-002) | Flask: bez typowanych schematów i OpenAPI bez dodatków; Django: ORM i panel administracyjny zbędne, cięższy; NiceGUI, Streamlit, Panel, Dash: interfejs związany z procesem Pythona, Streamlit przelicza skrypt przy każdej interakcji (nie nadaje się do długich zadań i wielu widoków), brak czystego API dla asystenta i zespołu |
| Indeks | **SQLite (WAL) na dysku lokalnym + R*Tree + FTS5** — w standardowym module `sqlite3`, zero usług | PostgreSQL/PostGIS: serwer do instalacji dla jednej osoby; DuckDB z rozszerzeniem przestrzennym: rozszerzenie pobierane z sieci, jeden pisarz; SpatiaLite: dodatkowa biblioteka natywna, a obrysy prostokątne wystarczą R*Tree; indeks tylko w pamięci: pełny skan przy każdym starcie (minuty na SMB); SQLite na udziale: wykluczone (SCOPE 3.3) |
| Zadania w tle | **Procesy robocze uruchamiane przez nadzorcę w serwerze**, kolejka w indeksie, zdarzenia w JSON Lines przez potok | wątki w procesie serwera: wątku nie da się przerwać, awaria biblioteki natywnej kładzie serwer; Celery/RQ + Redis: infrastruktura ponad potrzeby jednej osoby i małego zespołu; asyncio: Kartograf jest synchroniczny |
| Strumień do przeglądarki | **Server-Sent Events** (postęp, komunikaty, odpowiedź asystenta) | WebSocket: dwukierunkowość zbędna, trudniejsze proxy i testy; odpytywanie: opóźnienia i ruch |
| Interfejs | **SPA: Svelte 5 + TypeScript + Vite**, zbudowane do plików statycznych w pakiecie Pythona (użytkownik nie potrzebuje Node.js) | szablony serwerowe + htmx: dobre dla list i formularzy, ale główny ekran to aplikacja mapowa ze wspólnym stanem (obszar, warstwy lat, Stos, panel, czat, postęp), który w htmx rozpada się na fragmenty HTML i ręczny JS; React: więcej kodu i zależności dla tej skali; Vue: porównywalny — Svelte daje mniej kodu (reaktywność w kompilatorze); czysty JS jak w Hydrografie: przy tylu widokach rośnie w nieuporządkowany kod. Wybór frameworka jest odwracalny do v0.1 (mockup go nie przesądza) |
| Mapa | **MapLibre GL JS** — WebGL (płynnie dziesiątki tysięcy obrysów), nachylenie kamery i `fill-extrusion` z wysokością bazową: widok „Stos” bez osobnego silnika 3D; źródła XYZ i WMS (GUGiK, CUZK) w EPSG:3857 | Leaflet (precedens Hydrografa, jego ADR-003): bez nachylenia i 3D, wydajność warstwy canvas; OpenLayers: dowolne układy, ale bez widoku 3D (a przeliczenie do wyświetlania i tak robi serwer); CesiumJS: ciężki silnik globu; deck.gl: możliwy dodatek później (chmury punktów, tekstury w Stosie), dziś zbędna warstwa |
| Wykresy | **Własne komponenty SVG** (oś czasu lat i pokrycia) | biblioteki wykresów: jeden prosty wykres nie uzasadnia zależności |
| Podglądy rastrów | **rio-tiler** (biblioteka na rasterio/GDAL, które instaluje już Kartograf): kafle XYZ na żądanie; lokalny COG dla plików bez kafelkowania; pamięć po `sha256` wersji | TiTiler jako osobna usługa: dodatkowy proces; GeoServer/MapServer: ciężkie serwery i konfiguracja warstw; `gdal2tiles` z góry: minuty i gigabajty na arkusz |
| Podglądy wektorów | **pyogrio** (już w zależnościach Kartografa) → GeoJSON obiektów w widoku; kafle MVT później, gdy potrzebne | GeoServer, Martin, pg_tileserv: wymagają serwera albo PostGIS |
| Chmury punktów | **laspy + lazrs**: nagłówek i obraz 2D z próbki; 3D po v1.0 | Potree: konwersja do oktdrzewa (osobne narzędzie C++); COPC: konwersja całej chmury — później |
| Asystent | **Cienki własny adapter dostawców** (Anthropic Messages API, API zgodne z OpenAI — także modele lokalne: Ollama, vLLM, llama.cpp) z narzędziami = operacjami API Archiwisty | LangChain, LlamaIndex: duże zależności i abstrakcje ponad potrzebę; agent w przeglądarce: klucze API w przeglądarce; wyłącznie zewnętrzny agent przez MCP: wymaga osobnego klienta (MCP jako dodatkowe wejście do tych samych narzędzi — po v1.0) |
| Pakowanie | **Pakiet Pythona `archiwista`**, komenda `archiwista`, instalacja `pipx`/`uv tool` obok Kartografa; obraz Dockera opcjonalnie dla serwera zespołu | Electron/Tauri: przeglądarka wystarcza, więcej do utrzymania; Docker jako jedyna droga: zbędny dla jednej osoby, montowanie SMB w kontenerze komplikuje instalację |

### 5.3 Moduły serwera

Propozycja podziału (ostateczny ustali plan implementacji):

| Moduł | Odpowiedzialność |
|---|---|
| `archiwista/app.py` | aplikacja FastAPI, rejestracja tras, pliki statyczne interfejsu |
| `archiwista/config.py` | konfiguracja (TOML): magazyny, aliasy ścieżek, katalogi projektów, limity, podkłady, dostawca asystenta |
| `archiwista/security.py` | sprawdzanie `Host`, token startowy, CSRF, nagłówki CSP; później uwierzytelnianie i role |
| `archiwista/adapter/` | jedyne miejsce importu Kartografa: wywołania KA-KH i konwersje typów |
| `archiwista/index/` | schemat, skaner, zapytania, obrysy, wyszukiwanie |
| `archiwista/jobs/` | nadzorca, kolejka, proces roboczy (`python -m archiwista.jobs.worker`), protokół zdarzeń |
| `archiwista/previews/` | kafle i podglądy rastrów, wektorów, LAZ, ZIP; pamięć podglądów |
| `archiwista/sets/` | zestaw do projektu/QGIS (tryb 3 łączenia, sekcja 8.4) |
| `archiwista/assistant/` | adaptery dostawców, narzędzia, propozycje, rozmowy, liczniki kosztów |
| `archiwista/api/` | trasy `/api/v1` (sekcja 9) — cienkie, tylko wywołania warstwy usług |
| `archiwista/web/` | zbudowany interfejs (artefakt Vite) |
| `archiwista/cli.py` | `archiwista serve`, `archiwista reindex`, `archiwista doctor` (diagnostyka: Kartograf, magazyny, uprawnienia, port) |

Interfejs (`frontend/` w repozytorium, budowany do `archiwista/web/`): trasy
z całym stanem w adresie URL (obszar, produkt, filtry, widok mapy — link
można wysłać koledze), komponenty widoków z sekcji 6, typy API generowane
z OpenAPI serwera, teksty interfejsu w jednym słowniku (polski; inne języki
możliwe później).

### 5.4 Mapa, podkłady i kafle

- Wyświetlanie w EPSG:3857; obrysy w WGS84 z indeksu; dane w swoich
  układach są przeliczane wyłącznie do wyświetlania (przypięta
  transformacja Kartografa, KA-6).
- Podkłady: OpenStreetMap, ortofotomapa i mapa topograficzna GUGiK (WMS),
  ortofoto CUZK (WMS), „bez podkładu”. „Tryb offline” w ustawieniach
  wyłącza wszystkie zewnętrzne zapytania przeglądarki (sekcja 15, P6).
- Warstwy danych: obrysy (kolor wg stanu i pokrycia), podglądy rastrów
  (kafle `/api/v1/…/tiles/{z}/{x}/{y}.png`), obiekty wektorowe (GeoJSON).
- Siatka godeł (PL-1992, PL-2000, TM33) jako nakładka do wyboru arkuszy:
  serwer liczy ją dla widoku funkcjami Kartografa (`find_sheets_for_bbox`,
  parsery).
- „Stos”: warstwy lat albo kampanii jako płyty `fill-extrusion` na
  rosnących wysokościach nad mapą, z płynnym przejściem nachylenia kamery;
  najechanie podświetla rok, kliknięcie wybiera go w panelu. Płyty
  pokazują obrysy arkuszy w kolorach pokrycia; tekstury z podglądami danych
  — po decyzji z mockupu (sekcja 16, M4).

### 5.5 Konfiguracja i uruchomienie

`archiwista serve` uruchamia serwer na `127.0.0.1` (port z konfiguracji),
otwiera przeglądarkę z jednorazowym tokenem w adresie (sekcja 10.1)
i wypisuje adres w terminalu. Przy pierwszym uruchomieniu kreator pyta
o magazyn (katalog `--output` Kartografa) i katalogi projektów, sprawdza
wersję Kartografa (zakres zgodny z wymaganiami z sekcji 12) i zakłada
indeks. `archiwista doctor` wypisuje diagnostykę po polsku (wersje,
dostępność magazynów, uprawnienia, dowiązania twarde na udziale, port).

### 5.6 Zadania w tle

| Rodzaj | Co wywołuje | Sieć | Co zapisuje |
|---|---|---|---|
| `scan` | `iter_store` (KA-1), `open_project` | nie | indeks |
| `availability` | `check_availability` (wysokości), dla pozostałych produktów rozszerzenia KD | tak | raport w indeksie |
| `check` | `check_command` (KB-5) → `check_data`, `check_landcover`, `check_soil`, `check_hsg`, `check_collection` → plan `kartograf-plan/1` | tak | — |
| `download` | `run_command` (KB-5) → `download_data`, `download_landcover`, `download_soil`, `calculate_hsg`, `download_collection` z `update` i `plan` | tak | magazyn (przez Kartografa) |
| `project` | `download_project`, `check_project`, `verify_project` | zależnie od trybu | magazyn, manifest (przez Kartografa) |
| `compose` | funkcje łączenia Kartografa (KE, KF, KG) | zwykle nie | magazyn (przez Kartografa) |
| `export` | zestaw do QGIS (Archiwista) | nie | katalog zestawu w projekcie |
| `preview` | lokalny COG albo podgląd dużego pliku | nie | pamięć podglądów |

- **Cykl życia:** „w kolejce” → „trwa” → „zakończone” / „błąd” /
  „anulowane” / „przerwane” (serwer zatrzymany w trakcie). Propozycja
  asystenta nie jest zadaniem, dopóki człowiek jej nie zatwierdzi.
- **Równoległość (domyślnie):** 2 zadania sieciowe naraz, 1 zadanie na
  projekt (blokada manifestu), zadania obliczeniowe do połowy rdzeni,
  1 skan na magazyn. Zadania nakładające się (ten sam segment i te same
  jednostki) są oznaczone ostrzeżeniem — Kartograf i tak zapisze wersję
  raz (zapis wyłączny), ale druga osoba straciłaby czas.
- **Protokół proces roboczy → nadzorca:** JSON Lines na standardowym
  wyjściu: `progress` (z `DownloadProgress`: `current`, `total`, jednostka,
  status, komunikat; z KC-2 także faza i bajty), `notice` (`Notice`:
  poziom, kod, tekst), `result` (raport Kartografa w postaci JSON), `error`
  (typ wyjątku Kartografa i tekst). Nadzorca zapisuje zdarzenia w indeksie
  i przekazuje je przez SSE.
- **Anulowanie:** docelowo kooperacyjne — parametr `cancel` w funkcjach
  Kartografa (KC-1): Kartograf kończy bieżącą jednostkę i zwraca częściowy
  raport. Do czasu KC-1: sygnał przerwania (SIGINT; na Windows
  CTRL_BREAK_EVENT do grupy procesu) — Kartograf obsługuje przerwanie jak
  Ctrl-C w CLI (wersje powstają atomowo z `versions/.incoming/`, więc nie
  zostaje pół wersji), po 30 s zakończenie procesu. Po anulowaniu
  Archiwista odświeża sloty, których dotyczyło zadanie. Ryzyko: przerwanie
  w milisekundach zapisu manifestu może zostawić blokadę
  `.kartograf-project.lock`, którą Kartograf każe usunąć ręcznie —
  Archiwista rozpoznaje ten stan i pokazuje instrukcję (sekcja 14).
- **Restart serwera:** zadania „trwa” bez żywego procesu dostają stan
  „przerwane” z przyciskiem „Ponów”; ponowienie jest bezpieczne (Kartograf
  używa gotowych wersji lokalnych).
- **Dzienniki:** plik na zadanie (logger Kartografa na poziomie INFO
  i zdarzenia), przechowywanie 90 dni albo 1 GB.
- **Cache metadanych Kartografa:** procesy robocze dostają lokalny
  `MetadataCache` w katalogu danych Archiwisty — nigdy `cache=True` (plik
  w bieżącym katalogu) i nigdy na udziale (zasada M12 specu manifestu).
- **Dane uwierzytelniające źródeł** (np. `CLMS_CREDENTIALS`) przechodzą do
  procesów roboczych ze środowiska; Archiwista ich nie czyta, nie zapisuje
  i nie pokazuje — widać tylko „CLMS: skonfigurowane / brak (podgląd
  WMS)”.
- **Polecenie Kartografa:** każde zadanie pobrania, sprawdzenia i łączenia
  pokazuje równoważne polecenie CLI (`format_command`, KB-4).

### 5.7 Podglądy

| Rodzina plików | Podgląd | Uwagi |
|---|---|---|
| NMT, NMPT, DMR, DMP, SoilGrids | cieniowanie i hipsometria z legendą | ASC (tekst, bez kafelkowania) → lokalny COG z piramidą przy pierwszym podglądzie (zadanie `preview`); GeoTIFF kafelkowany czytany wprost |
| Ortofotomapa, true orto, intensywność, mapy TIFF | RGB albo skala szarości z rozciągnięciem | JPEG CUZK z plikami JGW: VRT-owijka z układem z sidecara (`extra.world_files`) |
| CORINE, HSG | paleta klas z legendą | |
| GeoPackage (BDOT10k, PRG, EGiB, ZABAGED, RUIAN…) | warstwy, liczba obiektów, obiekty w widoku (GeoJSON, do 5 000), próbka atrybutów | otwarcie `immutable=1`; powyżej limitu „Przybliż albo otwórz w QGIS” |
| ZIP (SHP, GML, CityGML, XLS, PDF, OBJ) | lista członów z rozmiarami i rozpoznanym formatem | podgląd SHP i GML przez `/vsizip/` później |
| LAZ | nagłówek (zasięg, liczba punktów, klasy, gęstość) i obraz 2D z próbki | widok 3D po v1.0 (sekcja 15, P5) |
| TXT/XYZ, PDF | metadane; PDF w przeglądarce | |

Zasady: `nodata` przezroczyste; przeliczenia i przepróbkowanie tylko do
wyświetlenia (podgląd nigdy nie jest produktem danych); pamięć podglądów
po `sha256` wersji i stylu — wersje są niezmienne, więc pamięć nigdy nie
jest nieaktualna; limit pamięci 20 GB (LRU, ustawienie); plik większy niż
2 GB nie dostaje podglądu automatycznie — przycisk „Zbuduj podgląd”.

## 6. Interfejs

Wzorce interfejsu zostaną potwierdzone na mockupie przed implementacją
(sekcja 16). Nazwy widoków i etykiet poniżej są wspólne dla specu
i mockupu.

### 6.1 Zasady

- **Mapa w centrum, zestawienie obok.** Główny ekran to mapa z panelem
  bocznym „Zestawienie”; ten sam wynik można oglądać jako „Mapa”, „Stos”
  albo „Katalog” (przełącznik widoku), a w panelu jako „Tabela” albo „Oś
  czasu”.
- **Jedno pole wyszukiwania** (paleta poleceń, `Ctrl+K`): godło, TERYT,
  produkt, projekt, etykieta wersji albo akcja („Sprawdź aktualność”).
- **Stan w adresie URL:** obszar, produkt, filtry, widok i położenie mapy —
  link otwiera ten sam widok (przyda się w zespole).
- **Plan przed działaniem:** każde działanie z siecią albo zapisem otwiera
  „Okno planu” (6.5 h) z liczbą plików, tym, co już jest lokalnie,
  rozmiarem, miejscem zapisu i poleceniem Kartografa.
- **Przejrzystość:** ludzka nazwa na wierzchu, wartość techniczna
  (segment, klucz źródła, kod EPSG, ścieżka wersji) w „Szczegółach
  technicznych” albo w podpowiedzi.
- **Komunikaty Kartografa bez zmian:** `Info:` i `Warning:` jako
  powiadomienia i lista w zadaniu, błąd walidacji przy polu formularza
  (ten sam tekst co w CLI).
- **Postęp na mapie:** jednostki zadania zmieniają kolor w miarę pobierania;
  pasek zadań na dole ekranu pokazuje trwające zadania.
- **Teksty po polsku** (z polskimi znakami; w szkicach poniżej skróty),
  liczby `12 345`, daty `RRRR-MM-DD`, rozmiary w MB i GB, odmiana
  liczebników („1 kampania”, „2 kampanie”, „5 kampanii”).
- **Dostępność cyfrowa (WCAG 2.1 AA):** kontrast, obsługa klawiaturą
  (`/` albo `Ctrl+K` wyszukiwanie, `Esc` zamyka, `?` lista skrótów), etykiety
  ARIA; stan pokrycia nigdy wyłącznie kolorem — zawsze także tekst i wzór.
- **Motyw jasny i ciemny.**

### 6.2 Nawigacja

| Pozycja | Zawartość |
|---|---|
| „Mapa” | główny przepływ (6.3): obszar → produkt → dostępność; tryby „Mapa”, „Stos”, „Katalog”; panel „Zestawienie” |
| „Projekty” | lista znanych projektów, widok projektu (6.5 g) |
| „Zadania” | kolejka i historia zadań w tle (6.5 f); licznik trwających przy nazwie |
| „Łączenie” | kreatory: „Mozaika”, „PL + CZ”, „Zestaw QGIS”, „Porównanie” (sekcja 8) |
| „Magazyn” | magazyny, zajętość wg produktów, stan i problemy (UC-13) |
| „Ustawienia” | magazyny i aliasy ścieżek, katalogi projektów, podkłady i tryb offline, limity, pamięć podglądów, asystent |
| „Asystent” | panel wysuwany dostępny z każdego widoku (sekcja 7) |
| „Karta pliku” | otwierana nad bieżącym widokiem (z własnym adresem URL) z listy, mapy, Stosu, Katalogu i wyszukiwania |

### 6.3 Główny przepływ: obszar → produkt → dostępność

1. **Obszar.** Narzędzia: prostokąt, wielokąt, „Widok mapy”, godło (wpisane
   albo kliknięte w siatce godeł), kod jednostki (TERYT, KU; wyszukiwanie po
   nazwie po KB-7), plik geometrii (GPKG, SHP, GeoJSON — kopiowany do
   lokalnego katalogu roboczego Archiwisty; Kartograf dostaje ścieżkę),
   kraj. Nad mapą stoi plakietka „Obszar: Kraków · 120 km² · PL” z „Zmień”
   i „Wyczyść”. Kraj (PL, CZ, oba) wynika z obszaru
   (`countries_for_bbox`); obszar przecinający granicę daje wyniki PL i CZ
   obok siebie.
2. **Produkt.** Lista z wyszukiwaniem pogrupowana jak grupy Kartografa
   („Wysokości”, „Obrazy”, „Pokrycie terenu”, „Gleby”, „Granice”,
   „Ewidencja”, „Modele 3D”, „Hydrografia”, „Nazwy”, „Mapy”, „Geodezja”),
   z krótkim opisem i krajami. Pozycja „Wszystkie produkty” pokazuje tylko
   magazyn (UC-02).
3. **Sprawdzenie.** Część lokalna (indeks, po odświeżeniu slotów obszaru,
   4.4) pojawia się od razu; sprawdzenie u źródła biegnie jako zadanie
   w tle z postępem w panelu („Sprawdzam skorowidz GUGiK: 3/7 warstw
   rocznych”). Raport sprzed mniej niż 7 dni (TTL cache Kartografa) jest
   pokazywany z datą; „Sprawdź ponownie” wymusza zapytanie (`force=True`).
   Co daje źródło, zależy od rodziny produktu:

   | Rodzina | Sprawdzenie u źródła | Wiersze zestawienia |
   |---|---|---|
   | NMT, NMPT, LAZ (PL, CZ) | `check_availability` (`kartograf-availability/1`) | lata × warianty z kompletnością arkuszy |
   | Obrazy PL (ortofotomapa, true orto, intensywność) | dziś plan `check_data` jednostek; lata i pełność z skorowidza po KD-3 | lata (po KD-3), inaczej jednostki |
   | Produkty jednostkowe (BDOT10k, BDOO, PRG, EGiB, modele 3D…) | plan `check_*` jednostek; dostępne wydania z rejestru, istnienie paczek po KD-4 | wydania (roczniki) |
   | Wyniki obszaru (WFS, ArcGIS, OGC API: PRG obszaru, ZABAGED, RUIAN…) | plan `check_collection` | jeden wiersz „bieżące” |
   | SoilGrids, CORINE, HSG | plan `check_*`; wydanie z sygnału `metadata` | wydania |

4. **Wynik.** Warstwy lat (albo kampanii, wydań) na mapie z listą
   przełączników, panel „Zestawienie” (Tabela albo Oś czasu), przełącznik
   „Mapa / Stos / Katalog”. Nad tabelą stoi aktywny wariant w postaci
   chipów („NMT · 1 m · EVRF2007 · ASC · PL-1992”) z „+2 warianty”, gdy
   rok ma inne kombinacje. Domyślny wariant jest widoczny i zmienialny —
   nic nie jest wybierane po cichu.
5. **Akcje wiersza.** „Pobierz…”, „Dodaj do projektu…”, „Pokaż na mapie”,
   „Porównaj z…”, „Mozaika…”, „Polecenie Kartografa”. Każda z siecią albo
   zapisem przechodzi przez „Okno planu”.

### 6.4 Etykiety pokrycia

Etykieta mówi, co źródło ma dla obszaru w danym roku i wariancie;
plakietka obok mówi, co z tego jest w magazynie. Definicje opierają się
na raporcie dostępności Kartografa (`AvailabilityCombination`: `complete`,
`sheets_full`, `sheets_partial`, `campaigns`, `uncovered_m2`;
`AvailabilityArea.land_m2`) — „ląd” to obszar przecięty z lądem PRG, tak
jak liczy Kartograf (ADR-041 R8).

| Etykieta | Kiedy | Dane Kartografa |
|---|---|---|
| „pełne” | `complete = true` i jedna kampania tego roku sama pokrywa ląd obszaru pełnymi arkuszami (`TAK`) | `complete`; podział arkuszy na kampanie — KD-1 |
| „pełne · 2 kampanie” (N kampanie/kampanii) | `complete = true`, ale żadna kampania sama; pełne arkusze N kampanii tego roku razem pokrywają ląd. N = liczba różnych kampanii wśród arkuszy, które pobierze Kartograf (najnowszy rekord arkusza, ADR-028) | `complete`, KD-1 (`campaigns` liczy także rekordy niepełne, więc samo `len(campaigns)` nie wystarcza) |
| „częściowe · 58%” | `complete = false`; 58% = ląd w ramkach pełnych arkuszy / `land_m2` (dolna granica tego, co na pewno ma dane). Dopisek „· N ark. niepełnych”, gdy `sheets_partial` niepuste | `full_m2` — KD-2 (nowe pole); `land_m2`, `sheets_partial` |
| „brak danych” | rok bez żadnej kombinacji w aktywnym wariancie | brak kombinacji |

W szczegółach wiersza dochodzi górna granica: ląd w ramkach dowolnych
arkuszy (`land_m2 - uncovered_m2`) / `land_m2` („w ramkach arkuszy: 92%”),
lista arkuszy niepełnych i obszar bez arkuszy. Po pobraniu Kartograf mierzy
rzeczywiste pokrycie lotu niepełnego (`extra.coverage` w sidecarze wersji)
i karta pliku pokazuje je zamiast szacunku.

**Plakietka magazynu:**

| Plakietka | Kiedy |
|---|---|
| „pobrane” | każda jednostka kombinacji (arkusze pełne i niepełne) ma w magazynie wersję z tej kombinacji (kampania z tego roku, ten wariant) |
| „pobrane 5/12” | część jednostek |
| „niepobrane” | żadna |

Bez sieci (brak raportu źródła) plakietka mówi „lokalnie 83% obszaru”:
udział obszaru w obrysach wersji z tego roku i wariantu w magazynie.

**Wybór kombinacji roku:** gdy w aktywnym wariancie rok ma kilka kombinacji
(np. PL-1992 i PL-2000), wiersz pokazuje najlepszą wg kolejności: pełna
przed częściową → większy udział pełnych arkuszy → drobniejsza
rozdzielczość → kolejność raportu Kartografa; pozostałe są pod chipem
„+N warianty”.

**Inne rodziny produktów:**

- **CZ** (CUZK nie publikuje lat ani flag pełności): jeden wiersz na
  model i układ, np. „DMR 4G · S-JTSK · Bpv — pełne (publ. 2025-02)”;
  „pełne” = każdy arkusz obszaru ma plik (`complete`), „częściowe · 2 ark.
  bez pliku” (`sheets_missing`).
- **Produkty jednostkowe** (BDOT10k, BDOO, PRG, modele 3D…): wiersz na
  wydanie; „pełne” = każda jednostka obszaru ma paczkę u źródła, „częściowe
  · 3/4 jedn.”, „brak danych”; plakietka „pobrane 3/4” (po KD-4; do tego
  czasu tylko plakietka magazynu i plan jednostek).

**Wygląd:** „pełne” — zieleń i wypełnienie pełne; „pełne · N kampanie” —
zieleń z cienkim wzorem szwów; „częściowe” — bursztyn z kreskowaniem;
„brak danych” — szarość z kropkami; plakietka — kółko pełne, połówka,
puste. Kolory dobrane dla daltonistów; tekst etykiety zawsze widoczny.
Odmiana: „1 kampania”, „2-4 kampanie”, „5+ kampanii” (wg reguł języka:
22-24 kampanie, 25 kampanii) i „1 ark. niepełny”, „2 ark. niepełne”,
„5 ark. niepełnych”.

### 6.5 Widoki (szkice)

Szkice pokazują układ i treść, nie wygląd (ten ustali mockup).

**a) „Mapa” z panelem „Zestawienie” (Tabela)**

```text
+-----------------------------------------------------------------------------+
| ARCHIWISTA  Mapa  Projekty  Zadania (1)  Łączenie  Magazyn  [Ctrl+K]        |
+-----------------------------------------------------------------------------+
| Obszar: Kraków · 120 km² · PL [Zmień]   Produkt: [NMT v]                    |
| Widok: (Mapa) Stos Katalog                                                  |
+---------------------------------------+-------------------------------------+
|                                       | ZESTAWIENIE      [Tabela] Oś czasu  |
|  +----+----+----+----+                | NMT · 1 m · EVRF2007 · PL-1992      |
|  |####|####|####|////|  #### pełny    |                       +2 warianty   |
|  +----+----+----+----+  //// niepełny | ----------------------------------- |
|  |####|####|####|####|  .... brak     | Rok   Pokrycie             Magazyn  |
|  +----+----+----+----+  [=] pobrany   | 2025  pełne                ( )      |
|  |####|####|####|####|                | 2023  pełne · 2 kampanie   5/12     |
|  +----+----+----+----+                | 2022  częściowe · 58%      ( )      |
|                                       | 2019  częściowe · 97%      (=)      |
|  Lata: [x]2025 [x]2023 [ ]2022        |       · 1 ark. niepełny             |
|        [ ]2019                        | ----------------------------------- |
|                                       | ( ) niepobrane  (=) pobrane         |
|                                       | [Pobierz...]  [Dodaj do projektu]   |
+---------------------------------------+-------------------------------------+
| Trwa: Pobieranie NMT 2023 (Kraków)  4/7 ark.  [######----]  [Anuluj]        |
+-----------------------------------------------------------------------------+
```

**b) Panel „Zestawienie” — Oś czasu** (lata na osi poziomej, także te bez
danych; słupek = udział lądu w arkuszach pełnych i niepełnych; pod
słupkiem stan magazynu)

```text
 ZESTAWIENIE  Tabela [Oś czasu]          NMT · 1 m · EVRF2007 · PL-1992
 100% |  //                          ##            ##
  75% |  ##                   //     ##            ##
  50% |  ##                   ##     ##            ##
  25% |  ##                   ##     ##            ##
   0% +--+------+------+------+------+------+------+----->
        2019   2020   2021   2022   2023   2024   2025
        (=)                  ( )    5/12          ( )
 ## pełne arkusze  // niepełne  (=) pobrane  5/12 częściowo  ( ) niepobrane
```

**c) „Stos”** (płyty lat nad mapą; kliknięcie wybiera rok w panelu)

```text
              2025  ______________________
                   /####/####/####/####/   pełne
              2023 ______________________
                 /####/####/////####/      pełne · 2 kampanie   5/12
              2022 ______________________
               /####/////..../////       częściowe · 58%
            ===================================  mapa (obszar)
```

**d) „Katalog”** (cały zestaw jako karty; miniatura z podglądów, gdy dane
są lokalnie, inaczej schemat arkuszy)

```text
+--------------------+ +--------------------+ +--------------------+
| 2025               | | 2023               | | 2022               |
| [schemat arkuszy]  | | [miniatura]        | | [schemat arkuszy]  |
| pełne              | | pełne · 2 kampanie | | częściowe · 58%    |
| 12 ark. · 0,46 GB  | | 12 ark. · 0,45 GB  | | 9 ark. · 4 niepełne|
| niepobrane         | | pobrane 5/12       | | niepobrane         |
+--------------------+ +--------------------+ +--------------------+
```

**e) „Karta pliku”**

```text
NMT 1 m · PL-1992 · EVRF2007 > N-34-130-D-d-2-4                         [x]
Arkusz 1:10 000 · GUGiK · PL-PGiK-40a [Kopiuj atrybucję]
-----------------------------------------------------------------------------
Wersje:      2019-06-11_61234     2023-05-02_80011     2025-04-26_82710
             o--------------------o--------------------O  bieżąca, pełna
Przypięta w: -                    Wisła-2026 (dem)     Raba (teren)
-----------------------------------------------------------------------------
[Podgląd] [Metadane] [Pochodzenie] [Szczegóły techniczne]
 Kampania 82710 · lot 2025-04-26 · skaning laserowy · błąd wys. 0,06 m
 Arkusz pełny · 37,8 MB · EPSG:2180 · EPSG:9651 · nodata -9999
-----------------------------------------------------------------------------
[Kopiuj ścieżkę wersji] [Polecenie Kartografa] [Sprawdź aktualność]
[Porównaj wersje] [Dodaj do projektu]
```

**f) „Zadania”**

```text
ZADANIA W TLE                                  [Wszystkie] [Trwa] [Błędy]
TRWA     Pobieranie: NMT 1 m 2023 (Kraków)    4/7 ark. [######----] [Anuluj]
         Info: (tekst Kartografa bez zmian)
GOTOWE   Sprawdzenie aktualności: projekt Raba        2 min temu
         3 aktualne, 1 nowsza                        [Pokaż plan]
BŁĄD     Pobieranie: BDOT10k 1261                    wczoraj 14:02
         (tekst błędu Kartografa)                    [Ponów] [Dziennik]
```

**g) Projekt**

```text
PROJEKT Raba        katalog: ~/projekty/raba · magazyn: Zespół
[Status] [Weryfikuj] [Sprawdź aktualizacje] [Pobierz] [Zestaw QGIS] [+ Zadanie]
-----------------------------------------------------------------------------
Zadanie   Polecenie                                    Pliki  Stan
teren     elevation download --product nmt ...         12     przypięte 2026-10-20
pokrycie  landcover download --product bdot10k ...     2      przypięte · 1 nowsza
gleby     soil hsg --bbox ... --depth 0-5cm            4      niepobrane
```

**h) „Okno planu”**

```text
POBRAĆ?  NMT 1 m · EVRF2007 · 2023 · obszar Kraków
  12 arkuszy: 5 w magazynie, 7 do pobrania (ok. 265 MB)
  Magazyn: Zespół
  [ ] Dodaj jako zadanie projektu [Raba v]  nazwa [teren-2023]
  Polecenie: kartograf elevation download --product nmt --country pl
    --bbox 561000,239000,573000,249000 --sheet-system 1992 --resolution 1m
    --vertical-crs EVRF2007 --year 2023 -o <magazyn>              [Kopiuj]
  [Anuluj]                                          [Pobierz 7 arkuszy]
```

### 6.6 Wyszukiwanie i filtry

Filtry (w panelu i w adresie URL): produkt; kraj; układ poziomy; układ
wysokości; rozdzielczość; rok danych (zakres); kampania albo wydanie
(etykieta); wersje: „bieżące” (domyślnie), „wszystkie”, „pełne arkusze”
(`full_sheet/`), „przypięte w projektach”, „niebieżące i nieprzypięte”;
obszar (z mapy); projekt („używane przez”, „nieużywane przez żaden
projekt”); stan („w porządku”, „brak pliku”, „bez sidecara”,
„nierozpoznane”); dostawca i licencja; data pobrania.

Wyszukiwanie rozpoznaje: godło PL-1992, PL-2000, TM33 i SM5; TERYT (2, 4,
6 i 7 cyfr); KU (6 cyfr); kod EPSG; etykietę wersji (`2025-04-26_82710`);
numer zgłoszenia pracy; początek sumy SHA-256 (od 8 znaków); nazwę pliku;
nazwę projektu i zadania projektu. Dla wprawnych: prefiksy `produkt:nmt
rok:2023 uklad:2180 projekt:raba` (każdy prefiks ma odpowiednik w filtrach).

## 7. Asystent (agent czatu)

### 7.1 Cel i granice

Asystent pozwala zlecić przygotowanie danych zdaniem po polsku („NMT 1 m
i ortofotomapa dla zaznaczonego obszaru z najnowszego pełnego roku, dodaj
do projektu Raba”). Jest drugą drogą do tych samych operacji co
interfejs: korzysta wyłącznie z API Archiwisty, a przez nie z API
Kartografa (A-ADR-011).

Granice uprawnień (twarde, wymuszane przez serwer, nie przez treść
promptu):

- **Nic nie pobiera, nie przepina i nie zapisuje bez potwierdzenia.**
  Asystent może tylko czytać i przygotować propozycję; wykonanie wymaga
  kliknięcia „Wykonaj” przez człowieka.
- **Nic nie usuwa** — takiego narzędzia nie ma (Archiwista niczego nie
  usuwa).
- **Nie zmienia ustawień, magazynów ani manifestów wprost**, nie czyta
  treści plików ani dowolnych ścieżek, nie uruchamia poleceń systemu.
- **Domyślnie wyłączony:** działa dopiero po wybraniu dostawcy modelu
  w „Ustawieniach” (7.6).

### 7.2 Przebieg

```mermaid
sequenceDiagram
  actor U as Użytkownik
  participant UI as Interfejs (panel „Asystent”)
  participant AS as Asystent (serwer)
  participant M as Dostawca modelu
  participant API as Usługi Archiwisty
  participant J as Zadania w tle (Kartograf)
  U->>UI: polecenie + kontekst widoku (obszar, produkt, filtry)
  UI->>AS: wiadomość (SSE w odpowiedzi)
  loop narzędzia tylko do odczytu
    AS->>M: rozmowa + definicje narzędzi
    M-->>AS: wywołanie narzędzia
    AS->>API: np. check_availability, plan_command
    API-->>AS: wynik (zwięzły)
  end
  AS->>API: propose_actions
  API-->>UI: karta propozycji + podświetlenie jednostek na mapie
  U->>UI: „Wykonaj” (albo zmiana / odrzucenie)
  UI->>API: wykonanie propozycji (token CSRF użytkownika)
  API->>J: zadania w tle
  J-->>UI: postęp na mapie i w „Zadaniach”
  AS->>API: get_job (po zakończeniu)
  AS-->>UI: podsumowanie wyniku
```

Asystent działa na serwerze, nie w przeglądarce: klucze API zostają po
stronie serwera, a narzędzia są tymi samymi operacjami warstwy usług co
API HTTP (sekcja 9). Każda wiadomość niesie **kontekst widoku** — obszar
(GeoJSON, powierzchnia, kraje), produkt, aktywny wariant i rok, filtry —
widoczny jako plakietka w polu wiadomości („Kontekst: Kraków · NMT ·
2023”), którą można odpiąć.

### 7.3 Narzędzia

| Narzędzie | Co robi | Rodzaj |
|---|---|---|
| `get_view_context` | bieżący obszar, produkt, wariant, filtry, widoczne warstwy | odczyt |
| `list_products` | produkty, kraje, opisy i opcje (katalog komend, KB-1) | odczyt |
| `find_units` | jednostki po nazwie albo kodzie: gmina, powiat, KU (KB-7) | odczyt |
| `search_store` | wyszukiwanie w indeksie z filtrami (jak `GET /api/v1/slots`) | odczyt |
| `get_slot`, `get_version` | karta pliku: wersje, metadane, przypięcia | odczyt |
| `list_projects`, `get_project` | projekty, zadania projektów, przypięcia, stan (bez sieci) | odczyt |
| `check_availability` | dostępność u źródła dla obszaru | odczyt z siecią (limit na turę, wyłączalny) |
| `plan_command` | plan polecenia Kartografa (`check_command`, KB-5): jednostki, lokalne, do pobrania, rozmiar | odczyt z siecią |
| `validate_command`, `format_command` | walidacja bez sieci i tekst polecenia (KB-3, KB-4) | odczyt |
| `get_job`, `list_jobs` | stan i wynik zadań w tle | odczyt |
| `show_on_map`, `open_view` | podświetlenie jednostek albo obszaru, przybliżenie, otwarcie widoku lub karty pliku | efekt w interfejsie (bez zmian danych) |
| `propose_actions` | propozycja: lista działań (pobranie, zadanie projektu, przepięcie, łączenie, zestaw) | propozycja — wymaga potwierdzenia |

Wykonanie propozycji nie jest narzędziem asystenta. Serwer przyjmuje je
wyłącznie z interfejsu, z tokenem CSRF sesji użytkownika (sekcja 10.1);
w trybie zespołu — z uprawnieniami osoby, która zatwierdza.

### 7.4 Propozycja i potwierdzenie

Propozycja to dane, nie tekst modelu: lista działań, a dla każdego
polecenie Kartografa (`command`, `options`), magazyn, ewentualny projekt
i nazwa zadania projektu, podsumowanie planu (`check_command`: jednostki,
ile lokalnie, ile do pobrania, szacowany rozmiar), ostrzeżenia
(komunikaty Kartografa) oraz suma całości. Karta propozycji w czacie
i podświetlenie na mapie powstają z tych danych, więc to, co widzi
człowiek, jest dokładnie tym, co się wykona.

- Użytkownik może odznaczyć część działań, zmienić opcje (formularz jak
  w „Pobierz…”) albo odrzucić propozycję.
- Przed wykonaniem Archiwista ponownie waliduje polecenia
  (`validate_command`) i — gdy plan jest starszy niż 15 minut — sprawdza
  go ponownie; różnice pokazuje przed startem.
- Duże działania (domyślnie ponad 5 GB albo ponad 500 plików) wymagają
  dodatkowego potwierdzenia („Rozumiem: ok. 12 GB”). Limity Kartografa
  (np. kolekcja: 100 plików i 10 GB na zadanie) obowiązują bez zmian.
- Propozycja wygasa po 24 h; wykonana staje się zwykłymi zadaniami w tle
  (widocznymi w „Zadaniach” i na mapie), a asystent dostaje ich wynik
  i podsumowuje go w rozmowie.

### 7.5 Szkic panelu

```text
ASYSTENT                                          [Nowa rozmowa] [x]
Ty: NMT 1 m dla zaznaczonego obszaru z najnowszego pełnego roku,
    dodaj do projektu Raba.
Asystent: Rok 2025 jest „pełne” (12 arkuszy, PL-1992, EVRF2007);
    2023 też pełne, ale z 2 kampanii. Proponuję:
  +---------------------------------------------------------------+
  | PROPOZYCJA (wygasa za 24 h)                                   |
  | [x] Pobierz NMT 1 m · EVRF2007 · 2025 — 12 ark., 0 lokalnie,  |
  |     ok. 455 MB do magazynu Zespół                             |
  |     kartograf elevation download --product nmt --country pl   |
  |     --bbox ... --resolution 1m --vertical-crs EVRF2007        |
  |     --year 2025 --sheet-system 1992                           |
  | [x] Dodaj zadanie projektu Raba: „teren-2025”                 |
  | Razem: 12 plików, ok. 455 MB       [Zmień] [Odrzuć] [Wykonaj] |
  +---------------------------------------------------------------+
[Kontekst: Kraków · NMT x]  Napisz polecenie...                 [Wyślij]
Zużycie w tym miesiącu: 41 tys. tokenów (ok. 0,30 USD z 20 USD)
```

### 7.6 Dostawca modelu

Konfigurowalny w „Ustawieniach” (plik TOML); domyślnie `none` (panel
wyłączony):

```toml
[assistant]
provider = "none"            # none | anthropic | openai | openai_compatible
model = ""                   # nazwa modelu dostawcy
base_url = ""                # openai_compatible: np. http://localhost:11434/v1 (Ollama)
api_key_env = ""             # NAZWA zmiennej środowiskowej z kluczem, nigdy sam klucz
allow_source_checks = true   # asystent może sprawdzać dostępność u źródła
monthly_budget = 20.0        # miesięczny limit kosztu w walucie cennika; po przekroczeniu asystent odmawia
price_input_per_mtok = 0.0   # cennik wpisany przez użytkownika (Archiwista nie zgaduje cen)
price_output_per_mtok = 0.0
```

Adaptery: Anthropic Messages API, OpenAI Chat Completions i każdy serwer
zgodny z nim (Ollama, vLLM, llama.cpp — modele lokalne). Wymagania wobec
modelu: wywoływanie narzędzi, kontekst co najmniej 32 tys. tokenów,
dobry polski. Lista przetestowanych modeli z wynikami ewaluacji (7.10)
jest w dokumentacji użytkownika — zestaw zmienia się szybciej niż spec.

### 7.7 Prywatność

- **Co trafia do dostawcy:** wiadomości użytkownika, opis narzędzi
  i produktów, wyniki narzędzi — metadane magazynu (produkty, jednostki,
  etykiety, daty, rozmiary), obszar (współrzędne), nazwy projektów i zadań
  projektów, ścieżki **względne** do magazynu (`<magazyn>/nmt/…`).
- **Co nigdy nie trafia:** treść plików danych, ścieżki bezwzględne
  (katalogi domowe, nazwy serwerów), klucze i dane uwierzytelniające,
  dzienniki zadań.
- **Obszar zainteresowania bywa poufny** (np. plany klienta): pierwsze
  uruchomienie asystenta pokazuje, co jest wysyłane i dokąd; dla projektów
  poufnych zalecany jest model lokalny (nic nie opuszcza komputera ani
  sieci lokalnej).
- **Historia rozmów** leży lokalnie w indeksie (domyślnie 90 dni), z „Usuń
  rozmowę” i „Eksportuj”; w zespole — osobno dla każdej osoby.
- Archiwista nie wysyła żadnej telemetrii.

### 7.8 Koszty

- Licznik tokenów na wiadomość, rozmowę i miesiąc (z pól użycia
  dostawcy) i koszt szacowany z cennika wpisanego przez użytkownika.
- Miesięczny limit: po jego przekroczeniu asystent odmawia z jasnym
  komunikatem do początku następnego miesiąca (albo zmiany limitu).
- Oszczędność wbudowana w narzędzia: zwięzłe wyniki (podsumowania,
  stronicowanie, najwyżej 50 wierszy), pamięć podręczna promptu u dostawców,
  którzy ją mają, skracanie starszej części rozmowy, brak jakiejkolwiek
  pracy asystenta w tle — działa tylko po wiadomości użytkownika.
- Sprawdzenia u źródła nie kosztują pieniędzy, ale obciążają publiczne
  usługi: limit na turę (7.9) i cache Kartografa.

### 7.9 Bezpieczeństwo asystenta

- **Wstrzyknięcie poleceń** przez dane (pola sidecarów, atrybuty, nazwy
  projektów) nie może nic zepsuć: asystent nie ma narzędzi wykonujących,
  a propozycję zatwierdza człowiek na podstawie danych strukturalnych.
- **Limity na turę:** do 20 wywołań narzędzi, do 5 sprawdzeń u źródła,
  do 2 minut; po przekroczeniu asystent kończy turę i mówi dlaczego.
- **Dziennik:** każde wywołanie narzędzia (nazwa, skrót argumentów,
  rozmiar wyniku, czas) jest widoczne w „Szczegółach rozmowy”.

### 7.10 Jakość

Zestaw ewaluacyjny: co najmniej 30 poleceń po polsku (obszar, produkt,
rok, projekt, pogranicze, łączenie, polecenia niejednoznaczne i wrogie)
na magazynie testowym z nagranymi odpowiedziami Kartografa; oczekiwane
propozycje (polecenia i opcje) porównywane automatycznie. W bramce
offline — nagrane odpowiedzi modelu (deterministycznie); na żywo — przy
zmianie modelu albo promptu. Kryteria v0.5: co najmniej 80% poprawnych
propozycji na modelu referencyjnym i zero wykonań bez potwierdzenia
(także dla poleceń wrogich).
