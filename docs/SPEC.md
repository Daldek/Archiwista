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
| **Zadanie w tle** | (Archiwista) długa operacja — skan, sprawdzenie, pobranie, łączenie, eksport — w osobnym procesie, z postępem i anulowaniem; widok „Zadania” | sekcja 5.5 |
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
