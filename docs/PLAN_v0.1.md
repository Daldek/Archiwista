# Plan implementacji v0.1 „Przeglądarka”

**Status:** wersja po przeglądzie planu (2026-10-18): uwzględnia wszystkie
uwagi przeglądu oraz decyzje kontraktowe z Kartografem (decyzje 2–5 i 8
poniżej). Kroki 0 i 1 ukończone; pozostałe według tego planu.
**Zakres:** wyłącznie lokalny, tylko odczyt magazynu Kartografa; zapisy
Archiwisty to konfiguracja, odtwarzalny indeks i baza stanu uprawnień
(konta, grupy, widoczność projektów; krok 8b) na dysku lokalnym.
Obowiązują kolejno `PRD.md` i `SCOPE.md` w kwestiach zakresu, `SPEC.md`
(zwłaszcza 4–6, 9–11, 12.1 i 13), `DEVELOPMENT_STANDARDS.md` oraz A-ADR-002,
004, 006, 007, 012, 013, 014, 015, 022, 024, 025, 028 i 029 (z erratami). Mockup
(`mockup/README.md`) jest punktem wyjścia dla układu, a **nie** źródłem
danych, skanera ani działań. Każdy krok kończy się podaną próbą odbioru;
nie wdrażać kolejnego zależnego kroku, dopóki poprzedni nie działa.

## Decyzje wykonawcze i granice

1. **Komputer odniesienia (SPEC 4.5, PRD N3).** Pomiary na tej maszynie:
   `nproc` → 4 logiczne CPU; `free -b` → 16 726 175 744 B RAM (15,6 GiB);
   `lsblk -d -o NAME,ROTA,TRAN,MODEL` → dysk SSD `/dev/sdb` (GOODRAM, SATA,
   `ROTA=0`; drugi dysk `/dev/sda` to HDD); `df -T .` → katalog projektu na
   ext4 `/dev/sdb1`. Procesor Intel Core i5-6400 2,70 GHz, Linux x86-64.
   **To maszyna odniesienia dla lokalnego SSD**; nie należy jej pomiarów na
   HDD ani na `tmpfs` przedstawiać jako wyników SSD. Osobny cel SMB z tabeli
   4.5 wymaga prawdziwego udziału SMB 3 w sieci 1 Gb/s podłączonego do tej
   samej maszyny; bez takiego udziału wynik SMB pozostaje *niezweryfikowany*,
   nie zastępuje go symulacja. Magazyn wydajnościowy (50 000 slotów, 80 000
   wersji, ok. 260 000 plików, 150 000 katalogów, 30 projektów) generator
   tworzy w jawnym `<katalog-danych>` poza repo i poza `/tmp`; raport podaje
   sprzęt, filesystem, opcje montowania, wersje, czasy p95 i rozmiar
   indeksu/RSS.
2. **Kontrakt Kartografa 0.8.0 (decyzja użytkownika 2026-10-18).** KA-1..KA-6
   wchodzą do Kartografa **0.8.0** (przygotowane, jeszcze nieotagowane
   wydanie; Kartograf ADR-045, ARCH 3.3.1–3.3.2, CHANGELOG [0.8.0]);
   `kartograf.__version__` zostaje `"0.8.0"`, a `pyproject.toml` przypina
   `kartograf>=0.8.0,<0.9` (A-ADR-024 errata 1). W `.venv` instalować
   edytowalnie `../Kartograf` z gałęzi `feat/archiwista-store-api` albo po
   jej scaleniu do `develop`. Sam numer nie dowodzi obecności KA (starsza
   kopia 0.8.0 ich nie ma), dlatego test kontraktu sprawdza symbole
   w `kartograf.__all__` **i** to, że `kartograf.__version__` mieści się
   w zakresie z metadanych zainstalowanej Archiwisty; przed wydaniem
   powtórzyć go przeciw otagowanemu Kartografowi 0.8.0. Kontrakt (nazwy
   ostateczne, ADR-045):
   - `list_segments(output_dir) -> list[str]` — posortowane
     `<produkt>/<wariant>` wszystkich rzeczywistych katalogów drugiego
     poziomu (bez dowiązań symbolicznych i katalogów z kropką), także
     nierozpoznanych; `iter_store(output_dir)` bez segmentu to przejście po
     tej liście.
   - `iter_store(output_dir, *, segment=None, units=None, skip_versions=None)
     -> Iterator[StoreEntry]` — `output_dir` to katalog `--output` Kartografa,
     czyli sam katalog `data/`, nie jego rodzic. `skip_versions` to zbiór
     (`set`/`frozenset`) ścieżek względnych **katalogów** wersji
     `<segment>/versions/<hierarchia>/<etykieta>_<sha8>`: każdy ich plik
     danych wraca jako `kind="version"`, `sidecar=None`, `skipped=True`,
     z etykietą i `sha8` z nazwy katalogu; brak sidecara w listingu nadal
     daje problem `missing_sidecar`.
   - `read_sidecar(path) -> Sidecar`; `describe_segment(segment) ->
     SegmentInfo`; `file_footprint(entry, *, network=False, cache=None) ->
     Footprint | None` — kolejność źródeł `request` → `sheet` → `header` →
     `unit`; `cache` to mapa należąca do wywołującego
     (`MutableMapping[tuple[str, str], BBox]`, klucz `("teryt" | "ku" |
     "sm5", kod)`, wartość natywny `BBox`), czytana także przy
     `network=False` (bez żadnego zapytania), uzupełniana tylko przy
     `network=True`; wpis bez sidecara (np. `skipped`) KA-4 doczytuje sam
     (1 otwarcie); `link_target(path) -> Path | None`;
     `pinned_transform(src_crs, dst_crs) -> PinnedTransform`.
   - `StoreEntry`: `kind` (`version`, `link`, `full_sheet`, `problem`),
     `segment`, `hierarchy`, `name`, `path`, `version_path`, `label`,
     `sha8`, `sidecar`, `problem`, `skipped`; `Sidecar` m.in. `dataset`,
     `dataset_key`, `country`, `request`, `data_year`, `data_date`, `unit`,
     `raw`; `SegmentInfo`: `segment`, `product`, `country`, `dataset_key`,
     `name`, `known`; `Footprint`: `native`, `wgs84`, `source`; `BBox` to
     `NamedTuple` (`min_x`, `min_y`, `max_x`, `max_y`, `crs`).
   - Współbieżność: dowolnie wiele wywołań `iter_store` może biec naraz
     w osobnych wątkach — różne segmenty albo rozłączne paczki `units`
     jednego segmentu; każdy generator konsumuje jeden wątek. To samo dotyczy
     `read_sidecar`, `describe_segment` i `link_target`; `PinnedTransform`
     z pamięci można współdzielić.

   Nie importować prywatnych modułów i nie parsować układu `data/` we
   własnym kodzie; brak KA albo rozbieżność kontraktu blokuje zależny krok,
   nie uruchamia obejścia.
3. **Skan: koszt, równoległość i dowiązania.**
   - *Przyrostowy = pełne przejście bez ponownego czytania znanych wersji.*
     Skaner podaje adapterowi wersje znane indeksowi
     (`ScanScope.known_versions`), a adapter Kartografa zamienia je na
     `skip_versions` (katalogi tych wersji). Znana wersja kosztuje tylko
     listing katalogu; sidecary dowiązań (ścieżka standardowa,
     `full_sheet/`) są czytane zawsze, bo z nich wynika nowa bieżąca
     wersja; manifesty projektów czyta `open_project`. Pełny skan (bez
     `known_versions`) czyta wszystko ponownie: to skan kontrolny raz na
     dobę i „Przebuduj indeks”. Koszt na wpis — tabela pod listą decyzji.
   - *Bez KA-5 w skanie.* Bieżąca wersja slotu to `StoreEntry.version_path`
     z sidecara dowiązania (bez haszowania treści). Ani skaner, ani
     `iter_entries` adaptera nie wołają `link_target`; KA-5 działa wyłącznie
     na żądanie (zadanie `link_check` z „Karty pliku”), bo na udziale bez
     stabilnych i-węzłów potwierdza cel sumą SHA-256 całego pliku.
   - *Równoległość po segmentach.* Proces roboczy skanu bierze listę
     segmentów (`SegmentedAdapter.segments` → `list_segments`) i dla
     każdego segmentu woła `iter_entries(scope=ScanScope(segment=…,
     known_versions=…))` w ograniczonej puli wątków (`scan_threads`,
     domyślnie 8 — ogranicza opóźnienie I/O, nie CPU); jeden generator na
     wątek. Wpisy idą ograniczoną kolejką do jednego wątku zapisu (paczka:
     1000 wpisów albo 1 s w jednej transakcji). Metadane nowych wersji
     przychodzą razem z wpisem (`SourceEntry.meta`), więc skaner nie czyta
     sidecara drugi raz. Obrysy nowych wersji (w pełnym skanie także wersji
     wciąż bez obrysu; `footprint` bez sieci) liczy osobna mała pula
     (4 wątki); istniejącego obrysu skan nie nadpisuje (wersje są
     niezmienne). Czas i liczba wpisów każdego segmentu trafiają do
     podsumowania zadania.
   - *Odświeżenie widoku* (`refresh_view`, ≤ 500 slotów): `iter_entries`
     z `segment`, `units` i `known_versions`, z jednostkami podzielonymi na
     rozłączne paczki w tej samej puli; jednostki z siatki godeł
     (`sheet_grid`) albo z obrysów w indeksie.
4. **Obrysy jednostek wymagające sieci: zadanie `footprints`.** Skan nigdy
   nie używa sieci. Adapter przekazuje KA-4 lokalną pamięć obrysów jednostek
   (SQLite `<user_data_dir>/cache/kartograf/unit_bboxes.sqlite`; zasada
   SPEC 5.6: nigdy `cache=True`, nigdy na udziale), więc skan bez sieci
   nadaje obrys nowym wersjom już znanych jednostek. Wersje jednostek
   jeszcze nieznanych (TERYT z PRG, KU z RUIAN, arkusz SM5 z indeksu CUZK —
   np. BDOT10k, EGiB, ZABAGED) zostają „bez obrysu” z powodem `no_source`
   do czasu świadomego zadania w tle `footprints`
   (`POST /api/v1/stores/{store}/footprints`, z CSRF): woła ono
   `footprint(entry, network=True)` dla wersji bez obrysu i zapisuje obrysy
   ze źródłem `unit`. W trybie offline endpoint odmawia (`409`, kod
   `offline_mode`) i zadanie nie startuje; interfejs pokazuje przyczynę
   braku obrysu zamiast geometrii.
5. **Pokrycie lokalne w układzie płaskim.** „Lokalnie 83% obszaru” to pole
   unii obrysów bieżących wersji produktu przeciętej z obszarem, podzielone
   przez pole obszaru — liczone shapely w układzie płaskim kraju produktu
   (`SegmentInfo.country`: PL → EPSG:2180, CZ → EPSG:5514), nigdy
   w stopniach WGS84 (zniekształcenie ok. 35% między osiami N–S i W–E na
   szerokości Polski). Obszar i obrysy przelicza przypięta transformacja
   KA-6 (`GeoAdapter.transformer`) po zagęszczeniu krawędzi (shapely
   `segmentize`); obrys natywny w układzie docelowym nie jest przeliczany.
   R*Tree daje tylko kandydatów. Produkt bez kraju albo kraj spoza listy →
   brak procentu z powodem `no_planar_crs`; nakładki liczone raz. To stan
   lokalny, bez sugerowania dostępności u źródła.
6. **Rozdzielenie zakresu.** v0.1 ma tylko stan *lokalny*: „lokalnie 83%
   obszaru” z geometrii wersji w indeksie, nie dostępność u źródła ani
   etykiety jej pokrycia. Bez podglądów, Wachlarza, Osi czasu i kurtyny
   (v0.2), pobierania, aktualności i edycji manifestu (v0.3), zespołu
   (v0.4), stacji IMGW (v0.5), pogranicza PL + CZ i stacji ČHMÚ (v0.6),
   wbudowanego asystenta (v1.2) i mozaiki (v1.3).
   W projekcie tylko odczyt `open_project`/`get_project_status`; polecenie
   zadania to **odczyt istniejących** opcji, nie własny formatter
   (`format_command` dopiero KB-4). „Brak podglądu — od v0.2” ma być
   uczciwym stanem, nie atrapą. W v0.1 brak zapisu w projekcie, magazynie
   i na udziale. `archiwista[imgw]` i rzeczywisty adapter IMGW dopiero
   w v0.5; v0.1 ma sprawdzalny protokół i testową drugą wtyczkę.
7. **Doprecyzowania API (wpisane do SPEC 9).** Nowe zasoby v0.1:
   `POST`/`GET /api/v1/session`, `POST /api/v1/session/tokens`,
   `POST /stores/{store}/footprints`, `POST /stores/{store}/link-check`,
   `GET /areas/{id}`, `GET /local-coverage?area_id=…&product=…&store=…`
   (stan lokalny po `refresh_view`) i filtr `unit` w `/slots`. Drugie
   zadanie zapisujące indeks tego samego magazynu → `409 conflict`
   z identyfikatorem trwającego zadania. Od v0.1 odpowiedzi mają
   dokumentowane schematy, jawne filtry, `limit ≤ 200`, nieprzezroczysty
   `cursor`, daty ISO, przykłady OpenAPI i stabilne kody błędów RFC 9457;
   do v1.0 kształt API może się zmieniać, a każdą zmianę między wydaniami
   0.x opisuje CHANGELOG. Agent zewnętrzny używa **tego samego** HTTP API
   i sesji co przeglądarka (decyzja 8), nie jest asystentem z SPEC 7.
   Lokalna CLI do odczytu używa **tych samych usług i modeli** co API (bez
   drugiej implementacji SQL), z uprawnieniami właściciela lokalnego
   indeksu.
8. **Sesja, CSRF i CSP (A-ADR-012 errata 1, SPEC 10.1).**
   - *Token startowy we fragmencie.* `archiwista serve` otwiera
     `http://127.0.0.1:<port>/#token=<wartość>` (128 bitów, jednorazowy,
     ważny 10 min). Fragment nie trafia do serwera, dziennika dostępu ani
     nagłówka `Referer`; `main.js` czyta `location.hash`, wysyła token
     `POST /api/v1/session` i usuwa go z adresu (`history.replaceState`).
     Dziennik dostępu Uvicorna jest domyślnie wyłączony, a włączony —
     filtrowany (redakcja `token=`).
   - *Sesja i osobny token CSRF.* Wymiana ustawia ciasteczko sesji
     `archiwista_session` (`HttpOnly`, `SameSite=Strict`, `Path=/`) i osobny
     128-bitowy token CSRF sesji: w ciasteczku `archiwista_csrf` (bez
     `HttpOnly`, `SameSite=Strict`) i w treści odpowiedzi;
     `GET /api/v1/session` zwraca `actor`, `csrf_token` i `expires_at`.
     `POST`/`PUT`/`DELETE` wymagają sesji i nagłówka `X-Archiwista-CSRF`
     równego tokenowi CSRF sesji i ciasteczku (double-submit) → inaczej
     `403 csrf_rejected`; bez sesji `401 session_required`.
   - *Reguła `Origin`.* Obecny `Origin` musi być adresem serwera. Żądanie
     zmieniające stan z `Sec-Fetch-Site` (przeglądarka) musi mieć
     `Sec-Fetch-Site: same-origin` i `Origin`; odczyt z `Sec-Fetch-Site:
     cross-site` jest odrzucany, a `none` (adres wpisany albo otwarty
     z terminala) i `same-origin` przechodzą. Klient bez `Origin`
     i `Sec-Fetch-*` (curl, skrypt agenta) przechodzi wyłącznie z sesją
     i — przy zmianie stanu — z nagłówkiem CSRF. Pliki interfejsu (`/`,
     `/static/…`) nie wymagają sesji, `/api/*` — tak (poza wymianą tokenu,
     która nie wymaga CSRF, ale podlega regule `Host`/`Origin`).
   - *Kolejne sesje i agenci.* Jednorazowy token ważny 5 min wystawia
     `POST /api/v1/session/tokens` (sesja + CSRF) albo `archiwista token`
     w terminalu właściciela (skrót SHA-256 tokenu w lokalnym indeksie);
     użytkownik przekazuje go agentowi poza API.
   - *CSP.* `default-src 'self'; script-src 'self'; style-src 'self';
     worker-src 'self'; img-src 'self' data: blob: <P>; connect-src 'self'
     <P>; font-src 'self'; object-src 'none'; base-uri 'none'; form-action
     'self'; frame-ancestors 'none'`, gdzie `<P>` to źródła (schemat, host,
     port) skonfigurowanych podkładów — tylko przy `offline = false`.
     MapLibre pobiera kafle przez `fetch` (`connect-src`), dlatego źródła
     podkładów są także tam; worker to dołączona wersja CSP
     (`maplibre-gl-csp-worker.js` przez `setWorkerUrl`), bez `blob:`
     w `worker-src`. Zmiana trybu offline albo podkładów przeładowuje stronę
     (CSP dotyczy dokumentu). Dodatkowo `Referrer-Policy: no-referrer`,
     `X-Content-Type-Options: nosniff`, bez CORS.
9. **Brak danych producenta ≠ wynik pusty.** `not_installed`,
   `incompatible`, `error` źródła i `store_unavailable`/stan starego indeksu
   mają osobne komunikaty po polsku oraz maszynowe kody. W v0.1 brak
   IMGWTools nie jest błędem uruchomienia. Katalog bez położenia pozostaje
   widoczny; nigdy nie umieszczać obiektu na mapie według zgadywanego
   punktu. **TERYT/KU w v0.1 to wyłącznie filtr `unit`** w `/slots`
   i „Katalogu” (dokładny kod z indeksu, `Sidecar.unit`) oraz wyszukiwanie;
   narzędzie obszaru „kod jednostki” (geometria z kodu) dopiero w v0.3
   z KB-7 — publiczne API Kartografa 0.8.0 nie ma funkcji kod → geometria,
   a `file_footprint` rozwiązuje jednostkę tylko dla istniejącego wpisu.
   Narzędzia obszaru v0.1: prostokąt, wielokąt, „Widok mapy”, godło, plik
   (SPEC 13 i 6.3). Wczytany plik obszaru: treść ≤ 50 MB, archiwum ≤ 200 MB
   po rozpakowaniu (sprawdzane przed rozpakowaniem), parsowanie w osobnym
   procesie zabijanym po 30 s, geometria ≤ 100 000 wierzchołków, kopie
   lokalne starsze niż 7 dni usuwane przy starcie; surowa ścieżka klienta
   nigdy nie jest argumentem otwarcia pliku serwera.

### Koszt odczytu na wpis (KA-1, Kartograf ARCH 3.3.1)

| Wpis | Koszt |
|---|---|
| każdy katalog | 1 × `scandir` (typ z `d_type`, bez `stat` plików) |
| lista segmentów | 1 × `scandir` katalogu `--output` + 1 na katalog produktu |
| `link`, `full_sheet` | 1 odczyt sidecara (open+read+close), bez `stat` i bez otwarcia pliku danych |
| `version` nowa | 1 odczyt sidecara |
| `version` znana (`skipped`) | 0 otwarć — tylko listing jej katalogu |
| `missing_sidecar` | 0 otwarć (widać w listingu) |
| `invalid_sidecar` | 1 odczyt |
| `stale_incoming` | `scandir` `versions/.incoming` + `lstat` katalogów roboczych |
| `unknown_segment`, `legacy_campaigns` | bez dodatkowego kosztu (z listingu segmentów) |
| zakres `units` | na jednostkę `lstat` każdego poziomu hierarchii (ochrona przed dowiązaniem symbolicznym) dla ścieżki standardowej, `full_sheet/` i `versions/` + `scandir` tych trzech katalogów slotu i katalogów jego wersji; wyłącznie wpisy tych jednostek, bez problemów poziomu segmentu |
| `link_target` (KA-5) | nigdy w skanie; na żądanie może przeczytać cały plik (SHA-256) |

Pomiar w kroku 13 liczy otwarcia sidecarów i porównuje je z tą tabelą.

## Umowy między krokami

- **Interfejs źródła — `archiwista/sources/`** (krok 1, `c74f8d4`; rozszerza
  krok 2). Stan po kroku 1: `SourceAdapter` (atrybuty `producer`,
  `package`, `supported_versions`, `schemas`) z `probe(root) ->
  SourceState`, `iter_entries(root, *, scope: ScanScope | None = None) ->
  Iterator[SourceEntry]`, `read_meta(entry) -> EntryMeta`, `footprint(entry)
  -> Footprint`, `read_project(path) -> ProjectInfo`, `project_status(path)
  -> ProjectInfo` oraz opcjonalna zdolność `SheetGridAdapter.sheet_grid(area,
  system, scale) -> SheetGrid` (stan `unsupported` dla producentów bez
  arkuszy). Typy: `ScanScope(segment, units)`, `SourceState(producer,
  status, store, package_version, supported_versions, schemas, detail)`,
  `SourceEntry(producer, store, relative_path, kind, segment, slot_path,
  version_path, problem)`, `EntryMeta` (zbiór, klucz, produkt, etykieta
  i jej źródło, rok/data danych oddzielone od pobrania, `sha256`, rozmiar,
  licencja, atrybucja, `source_files`, surowy sidecar), `Footprint(location,
  wgs84, native, source, reason)`, `ProjectPin(store, version_path, sha256,
  task_id)`, `ProjectTask(task_id, command, options, status)`,
  `ProjectInfo(producer, store, path, name, tasks, pins, status, problem)`,
  `SheetGrid(status, sheets)`. Rozszerzenia kroku 2 — jedyna zmiana umowy
  kroku 1, z aktualizacją `tests/contract/test_source_protocol.py`:
  1. `ScanScope.known_versions: frozenset[Path] = frozenset()` — ścieżki
     względne wersji znanych indeksowi; adapter nie czyta ponownie ich
     metadanych.
  2. `SourceEntry.skipped: bool = False` (wersja znana, metadanych nie
     czytano) i `SourceEntry.meta: EntryMeta | None = None` (metadane
     z tego samego przejścia; skaner nie woła `read_meta` drugi raz;
     `read_meta` zostaje do odczytu na żądanie).
  3. `footprint(entry, *, network: bool = False) -> Footprint`; pamięć
     obrysów jednostek trzyma adapter w `SourceContext.cache_dir`.
  4. Fabryka wtyczki `load(context: SourceContext) -> SourceAdapter`,
     `SourceContext(cache_dir: Path)` = `<user_data_dir>/cache/<producent>/`.
  5. Opcjonalne zdolności (wzór `SheetGridAdapter`):
     `SegmentedAdapter.segments(root) -> tuple[str, ...]` (podział do
     równoległego skanu; suma przejść po segmentach = przejście bez
     segmentu; producent bez podziału skanuje się jednym przejściem)
     i `SegmentedAdapter.describe_segment(segment) -> SourceSegment`
     (`segment`, `product`, `country`, `dataset_key`, `name`, `known` —
     tabela `segments` i kraj produktu z decyzji 5);
     `GeoAdapter.transformer(src_crs, dst_crs) -> CoordinateTransformer`
     (`transform(xs, ys)`, `description`, `accuracy_m`; obiekt można
     współdzielić między wątkami) i
     `GeoAdapter.countries(bbox_wgs84) -> tuple[str, ...]`;
     `LinkCheckAdapter.confirm_link(entry) -> Path | None` (tylko na
     żądanie).
  6. Pola dodatkowe, wszystkie z wartością domyślną (decyzja koordynatora
     2026-10-18; kształt kroku 1 nadal działa): `EntryMeta` — `country`,
     `unit`, `survey_work_id`, `campaign` (identyfikator kampanii),
     `edition`, `full_sheet`, `coverage`, `parent_request` (stały klucz
     tekstowy plików jednego zadania), `horizontal_crs`, `vertical_crs`,
     `resolution`, `nodata`; `Footprint.native_crs` (układ obrysu
     `native`); `SheetGrid.outlines` (wielokąt WGS84 każdego arkusza
     w kolejności `sheets`); `SourceEntry.handle` (własny rekord
     producenta, nieprzezroczysty dla Archiwisty i pomijany w porównaniu:
     `footprint` wpisu ze skanu nie czyta sidecara drugi raz; wpis
     odtworzony z indeksu działa bez niego kosztem 1 odczytu).

  Pole `store` (`SourceEntry`, `EntryMeta`, `SourceState`, `ProjectInfo`,
  `ProjectPin`) to katalog producenta magazynu jako tekst: `root` podany
  adapterowi albo magazyn wskazany przez manifest projektu. Adapter
  rozwiązuje względem niego ścieżki względne, więc `read_meta`, `footprint`
  i `confirm_link` znajdują plik z samego wpisu; indeks kluczuje wiersze
  identyfikatorem magazynu z konfiguracji i mapuje go na ten katalog przez
  `StoreConfig`. `known_versions` to ścieżki plików wersji, a adapter
  Kartografa pomija całe ich katalogi. Rejestr
  (`archiwista/sources/registry.py`): `load_registry(*, cache_dir=None) ->
  SourceRegistry` z `producers()`, `states()`, `state(producer)`,
  `adapter(producer)` i `probe(producer, root)`; `adapter` zgłasza
  `SourceUnavailableError` albo `SourceIncompatibleError` z polem `state`.
  Błąd biblioteki producenta wychodzi z adaptera jako
  `ProducerError(package, exception, message)` z niezmienionym
  komunikatem, a nieczytelny magazyn jako `SourceUnavailableError`.

  Adapter Kartografa jest jedynym importerem `kartograf`; reszta zna
  wyłącznie `archiwista.sources`, a interfejs nie narzuca drugiemu
  producentowi układu Kartografa (segmenty, arkusze i dowiązania są
  zdolnościami opcjonalnymi).
- **Indeks — `archiwista/index/`** (krok 5; skaner 6a; projekty 7):
  `IndexQueries` zwraca typowane `SlotPage` (`items`, `next_cursor`,
  liczniki grup położenia), `SlotDetail`, `VersionDetail`, `FootprintPage`,
  `LocalCoverageReport`, `IndexStatus`, `StoreUsage`; `ProjectDetail`
  i `StoreSummary` składa krok 7 w `archiwista/services/` z tych zapytań
  i tabel projektów. `IndexWriter` przyjmuje typy protokołu, nie obiekty
  Kartografa. Klucze publiczne: krótka nazwa magazynu i ścieżka względna
  slotu/wersji. HTTP i CLI używają jednego `IndexQueries`; drzewo magazynu
  przechodzą tylko skaner i `refresh_view`. Funkcję `scan_projects`
  (krok 7) wywołuje skaner 6a w wątku zapisu po pełnym przejściu całego
  magazynu (zadanie `scan` kroku 6b), z `AppSettings.project_dirs`
  i `AppSettings.stores`.
  Stan po kroku 5:
  - *Schemat* (`schema.py`): `SCHEMA_VERSION` w `PRAGMA user_version`;
    inna wersja → `initialize` przebudowuje pusty indeks w jednej
    transakcji (bez migracji); WAL; `IndexUnsupportedError`, gdy SQLite
    < 3.35 albo bez FTS5, R*Tree lub JSON. Tabele `jobs`, `job_events`
    i `session_tokens` zakłada krok 5, piszą do nich 6b i 8.
  - *Zapis* (`IndexWriter(path)`, jeden wątek naraz):
    `sync_stores({id: {producent: katalog}})` (magazyn spoza ustawień
    znika z indeksu), `set_store_status(store, status, *, detail)`,
    `write_segments(store, producer, segmenty)`, przebieg
    `begin_pass(store, producer, *, segment, slots, full) -> ScanPass` →
    `known_versions(segment)` (do `ScanScope.known_versions`) →
    `write_entries(paczka) -> BatchResult` (paczka = jedna transakcja;
    `needs_footprint`: wersje nowe i bez policzonego położenia, w pełnym
    przebiegu także bez obrysu) → `write_footprints(store, [(wpis,
    Footprint)])` (istniejącego obrysu nie nadpisuje) → `finish_pass() ->
    PassSummary` albo `abandon_pass()` (nic nie oznacza). `finish_pass`
    oznacza niewidziane w zakresie wersje „brak pliku” z datą, usuwa
    wersje już brakujące przy przebiegu pełnym, czyści niewidziane
    dowiązania, rozwiązuje problemy, usuwa puste sloty; przebieg całego
    magazynu ustawia też `indexed_at` i stan `available`. `slots` (ścieżki
    slotów) zawęża przebieg `refresh_view`. Niezmieniony wpis nie kosztuje
    zapisu. Projekty: `project_stamps(producer)`, `write_project(info, *,
    store, stamp) -> klucz`, `remove_projects(producer, *, keep)`;
    obszary: `write_area(AreaRecord)`; problemy zadań kontrolnych
    (`link_mismatch`): `record_issue`, `clear_issue` — skan ich nie usuwa.
  - *Odczyt* (`IndexQueries(path)`, bezpieczne dla wątków, jedna migawka
    na wywołanie): `slots(SlotQuery)`, `slot(store, slot)`,
    `version(store, path)`, `sidecar(store, path)`,
    `group(parent_request)`, `footprints(MapQuery)`, `products(*, store)`,
    `usage(store)`, `issues(store)`, `status()`, `area(id)`,
    `local_coverage(area, *, store, product, transformer, countries,
    segment)` (transformator `GeoAdapter.transformer` wstrzyknięty),
    `slots_in_bbox(store, bbox, *, segment, product)` (6a) i
    `entries_without_footprint(store, *, segment)` (zadanie `footprints`).
    Obcy kursor, limit poza 1–200, odwrócone lata, obszar spoza WGS84 →
    `IndexQueryError` (`422 validation_error`). Wyniki p95 na magazynie
    50 000 slotów: `tests/perf/test_index_perf.py` (`-m perf`).
  Stan po kroku 7:
  - *Projekty* (`projects.py`): `scan_projects(adapter, writer, *,
    project_dirs, stores: Sequence[StoreConfig]) -> ProjectScanSummary`
    (`found`, `read`, `unchanged`, `invalid`, `unknown_store`, `removed`,
    `unreadable_dirs`). Manifest producenta z `PROJECT_MANIFESTS`
    (`kartograf` → `kartograf-project.json`); odczyt `project_status`,
    a gdy zawiedzie — `read_project` (status `None`); błąd obu → projekt
    z `problem` (komunikat producenta). Magazyn dopasowany po ścieżce
    (`normpath`, `realpath`) albo aliasie `StoreConfig.local_path`, także
    dla ścieżki z innego systemu, którą producent rozwiązał względem
    katalogu projektu. `project_stamps` zwraca pusty znacznik dla projektu
    bez magazynu albo bez statusu, więc taki manifest jest czytany przy
    każdym przejściu, aż się dopasuje (np. po dodaniu magazynu). Katalog
    projektów, którego nie da się odczytać, zachowuje swoje projekty.
  - *Odczyt*: `projects(*, store) -> ProjectRef` (z licznikami zadań,
    przypięć i brakujących przypięć), `project(key) -> ProjectRecord`
    (`tasks`: `ProjectTaskRef` z poleceniem i opcjami; `pins`:
    `ProjectPinRef` ze stanem `ok`/`missing`/`sha256_mismatch`/`unknown`,
    slotem, etykietą, rozmiarem i `is_current`), `unused_versions(store) ->
    UnusedVersions` (niebieżące, poza `full_sheet/` i nieprzypięte; per
    produkt, `unique_bytes` i `reclaimable_bytes` — treści nietrzymane
    przez inną obecną wersję), `orphan_links(store) -> OrphanLink`
    (sidecar dowiązania wskazujący brakującą wersję), `pin_problems(store)
    -> PinRef` (przypięcia bez pliku albo z inną treścią).
  - *Usługi* (`archiwista/services/`): `Problem(code, message,
    instruction, path, segment, slot, project, task, origin,
    first_seen_at)` i `explain(code, **wartości)` (teksty w
    `messages.py`, `problem_<kod>`/`fix_<kod>`); `project_detail(queries,
    key) -> ProjectDetail` (`project`, `tasks`, `pins`, `problems`:
    `invalid_manifest`, `unknown_store`, `missing_pin`,
    `pin_sha256_mismatch`); `project_status(queries, registry, key) ->
    ProjectInfo` (żywy `project_status` producenta dla
    `GET /projects/{id}/status`); `store_summary(queries, StoreConfig) ->
    StoreSummary` (`store`, `name`, `kind`, `state` z `last_scan.actor`,
    `usage`, `unused`, `projects`, `problems`: problemy producenta,
    `link_mismatch`, `orphan_sidecar`, `missing_pin`,
    `pin_sha256_mismatch`). Żadna nie usuwa ani nie zmienia projektu.
  Stan po kroku 6a:
  - *Skaner* (`scanner.py`, eksport z `archiwista.index`):
    `scan_store(adapter, writer, settings: AppSettings, store, *,
    mode="incremental"|"full", segment=None, on_event=None) -> ScanSummary`.
    Magazyn musi być w indeksie (`sync_stores` robi wywołujący). Segmenty
    czyta pula wątków (jeden generator `iter_entries` na wątek): na udziale
    `scan_threads` wątków, na dysku lokalnym jeden — tam skan ogranicza CPU
    pod GIL (przyrostowy bez zmian na magazynie 50 000 slotów: 1 wątek
    20 s, 2 — 23 s, 8 — 27 s); obrysy bez sieci liczy osobna pula (4 wątki
    na udziale, 1 lokalnie), zapis paczkami 1000 wpisów albo 1 s robi
    wyłącznie wątek wywołujący. Po przejściu całego magazynu (oba tryby)
    w tym samym wątku `scan_projects`. Zdarzenia w wątku wywołującym:
    `ScanProgress(segment, current, total, entries)` (pierwsze z
    `current=0`, potem po każdym segmencie) i `ScanNotice(level, code,
    message)` (`footprints_failed`, `project_dir_unreadable`).
    `ScanSummary`: liczniki paczek, `footprints_written`,
    `footprints_failed` (zostają `pending`), `finished: PassSummary`,
    `segments: SegmentScan(segment, entries, seconds)`, `projects` (`None`
    po skanie segmentu). Niedostępny magazyn (probe ≠ `available`, brak
    segmentów przy wersjach w indeksie, błąd odczytu, a po przejściu
    ponowny probe — udział odmontowany w trakcie daje puste listingi bez
    błędu) → `abandon_pass`, `set_store_status("unavailable", detail)`
    i `SourceUnavailableError`; `ProducerError` też porzuca przebieg.
  - *Odświeżenie widoku*: `refresh_view(adapter, writer, queries, settings,
    store, segment, units, *, known_slots=(), timeout_s=None) ->
    IndexStatus` — najwyżej `REFRESH_VIEW_MAX_UNITS` (500) jednostek
    (`ScanScope.units`: godła `sheet_grid` albo `SlotUnit.unit`) w
    rozłącznych paczkach; `known_slots` (`SlotUnit.slot` ze
    `slots_in_bbox`) daje `known_versions`, bez nich czytane są wszystkie
    wersje jednostek. Przebieg obejmuje tylko sloty, dla których producent
    zwrócił wpisy: jednostka, która nie trafia w swój slot (np. kafel LAZ,
    którego jednostką w sidecarze są współrzędne zgłoszenia), niczego nie
    oznacza brakiem; zniknięcie całego slotu wykrywa najbliższy skan.
    Niedostępny magazyn → stan `unavailable` i `IndexStatus` ze `stale`;
    odczyt dłuższy niż `timeout_s` → `TimeoutError` bez zapisu.
  - *Pomiary* (`tests/perf/test_scan_perf.py`, `-m perf`, SSD maszyny
    odniesienia, magazyn jako `local`, trzy przebiegi): pełny skan
    58,5–59,4 s (cel 120 s), przyrostowy bez zmian 19,1–19,4 s (cel 20 s,
    zapas mały: sam `iter_store` Kartografa to ok. 12,4 s, zapis ok. 2 s),
    `refresh_view` 500 slotów p95 280–301 ms (cel 1 s), indeks 205 MiB,
    szczyt sterty skanu (RssAnon) 266 MiB, a z odwzorowanym indeksem
    (VmHWM) 517 MiB. Adapter Kartografa liczy ścieżki względne cięciem
    prefiksu (`Path.relative_to` zajmowało ok. 1/3 skanu przyrostowego).
    Pomocnicze zmiany magazynu testowego (nowa wersja z przepięciem,
    usunięcie wersji): `tests/fixtures/store_edits.py`.
- **Zadania w tle — `archiwista/jobs/`** (krok 6b):
  `JobSupervisor.submit(kind, *, store, params, actor) -> JobRecord`
  (`JobConflictError` z identyfikatorem trwającego zadania), `get`, `list`,
  `events(job_id, *, after)`; jedna tabela `jobs` z `actor`. Protokół
  procesu roboczego (JSON Lines, SPEC 5.6): `progress`, `notice`, `result`,
  `error`; zdarzenia SSE (SPEC 9.2): `progress`, `notice`, `state` — stany
  `queued`, `running`, `succeeded`, `failed`, `interrupted` (od v0.3 także
  `cancelled`), przy `failed` obiekt `error` (`code`, `detail`).
  Stan po kroku 6b:
  - *Nadzorca* (`supervisor.py`, eksport z `archiwista.jobs`):
    `JobSupervisor(paths, settings: SettingsService, *, worker_command,
    max_jobs, max_network_jobs, stop_timeout_s)` — `start()`/`close()` (albo
    `with`); `submit(kind, *, store, params, actor) -> JobRecord`: `scan`
    (`mode` `incremental`/`full`, `segment`), `footprints`, `link_check`
    (`slot`); `NotFoundError` (magazyn spoza ustawień), `OfflineModeError`
    (`footprints` w trybie offline, nic nie zapisuje; `409 offline_mode`),
    `JobConflictError(job_id, kind, state)` (podklasa `ConflictError`:
    trwający `scan`/`footprints` magazynu, także innego procesu, np.
    `archiwista reindex`), `ValueError` (rodzaj, parametry). Odczyt: `get`,
    `list(*, kind, store, state, limit ≤ 200, cursor) -> JobPage` (od
    najnowszych; obcy kursor → `IndexQueryError`), `events(job_id, *,
    after) -> JobEvent(job_id, seq, type, data, at)` (`seq` od 1 = `id:`
    SSE), `subscribe(listener, *, job_id)` (wywołanie w wątku nadzorcy,
    w kolejności `seq`; słuchacz oddaje zdarzenie, np.
    `loop.call_soon_threadsafe`, i wraca), `cancel`, `wait`, `recover`,
    `scan_history`. `JobRecord(id, kind, state, actor, store, params,
    created_at, started_at, finished_at, progress, result, error:
    JobError(code, detail))`; `error` ma każde zadanie, które nie
    zakończyło się sukcesem. Na serwer: `create_app(..., jobs=)` →
    `app.state.jobs`.
  - *Zdarzenia*: `state` (`queued`, `running`, na końcu `succeeded`
    z `result` albo `failed`/`interrupted`/`cancelled` z `error`),
    `progress` (`current`, `total`; skan także `segment`, `entries`;
    obrysy `written`, `failed`), `notice` (`level`, `code`, `message`).
    Kody `error.code`: `store_unavailable`, `source_unavailable`,
    `source_incompatible`, `kartograf_error` (`<pakiet>_error`),
    `offline_mode`, `not_found`, `unsupported`, `internal_error`,
    `worker_crashed` (sygnał albo kod wyjścia i ścieżka dziennika),
    `interrupted`, `cancelled`.
  - *Proces roboczy* (`worker.py`): stdin — jedna linia `JobSpec`
    (ustawienia z chwili startu), potem otwarte do końca: jego koniec
    oznacza zniknięcie nadzorcy i przerywa zadanie; stdout tylko JSON
    Lines (deskryptor 1 kierowany na stderr), stderr to dziennik
    `<jobs>/<id>.log` (90 dni albo 1 GB). Anulowanie i zatrzymanie serwera:
    SIGINT (Windows: CTRL_BREAK_EVENT, osobna grupa procesów), po 30 s
    zabicie; skan porzuca przebieg, więc nic nie zostaje oznaczone. Każdy
    nadzorujący proces trzyma blokadę `<jobs>/owner-<pid>.lock`; zadanie
    bez żywego nadzorcy (restart, awaria) dostaje `interrupted`.
  - *Wyniki*: `scan` — sumy `ScanSummary` (`entries`, `versions_written`,
    `links_changed`, `issues_added`, `footprints_written`,
    `footprints_failed`, `missing`, `reappeared`, `removed`,
    `slots_removed`, `unlinked`, `issues_resolved`, `seconds`, `segments`,
    `projects`); `footprints` — `total`, `written`, `failed`, `seconds`
    (sieć tylko dla wersji bez obrysu, pamięć jednostek adaptera; przed
    startem `probe`, pusty punkt montowania → `store_unavailable`);
    `link_check` — `status` (`confirmed`, `index_outdated`, `mismatch` →
    problem `link_mismatch` pochodzenia `check`, `missing`, `not_a_link`),
    `expected`, `confirmed`.
  - *Harmonogram* (`scheduler.py`): `ScanScheduler(jobs, settings,
    registry, *, index_path, actor="local")` uruchamia `serve`;
    `plan_scans` — przy starcie skan, gdy ostatni starszy niż 15 min
    (nigdy → pełny), potem interwał rodzaju magazynu od końca ostatniego
    skanu, pełny co 24 h; magazyn `unavailable` tylko `probe` (osobny
    wątek, 10 s) co minutę i skan po powrocie; nowy albo przeniesiony
    magazyn w ustawieniach → pełny skan.
  - *CLI*: `archiwista reindex [--store ID]` (`jobs/reindex.py`) — pełny
    skan jako zadanie `local` na pierwszym planie, postęp na stderr,
    podsumowanie na stdout; wyjście 0, 1 (błąd albo kod `conflict`), 2
    (nieznany magazyn); Ctrl+C anuluje. Pokrycie procesów roboczych:
    `[tool.coverage.run] patch = ["subprocess"]`.
- **API i bezpieczeństwo — `archiwista/api/` (9a–9c), `archiwista/security.py`
  (8):** jeden zestaw modeli Pydantic dla JSON i OpenAPI; problem RFC 9457:
  `type`, `title`, `status`, `detail` (po polsku), `code`, a gdy dotyczy —
  `401 session_required`, `403 csrf_rejected`, `403 permission_denied`,
  `404 not_found`, `409 conflict`, `409 offline_mode`, `413 area_too_large`,
  `422 validation_error`, `422 area_unreadable`, `422 area_too_complex`,
  `422 kartograf_error`, `503 store_unavailable`, `503 source_unavailable`,
  `503 source_incompatible`; `code` nie zależy od polskiego `detail`.
  `archiwista/app.py` zakłada krok 8; kroki 9a–9c dopisują po jednej linii
  `include_router` (scala właściciel 9a).
  Stan po kroku 8:
  - *Kto działa* (`archiwista/auth/`, rozbudowuje 8b): `Principal(id, kind,
    roles, groups)`, `kind` `local_owner`/`user`/`agent`; tryb lokalny
    `LOCAL_OWNER` (`local`, role `admin` i `store_writer`, bez grup). Sesja
    z tokenu startowego działa jako ten, kto go wystawił, a z tokenu agenta
    jako `agent` z jego `id`, rolami i grupami; `actor` zadań to
    `Principal.id`.
  - *Ochrona* (`archiwista/security.py`): `SecurityMiddleware` dla każdego
    żądania — `Host` (`400 invalid_host`), `Origin`/`Sec-Fetch-Site`
    (`403 csrf_rejected`), dla `/api/*` poza `POST /api/v1/session` sesja
    (`401 session_required`) i przy `POST`/`PUT`/`DELETE` CSRF (`403`);
    w każdej odpowiedzi CSP z bieżących ustawień, `Referrer-Policy`,
    `nosniff`, dla `/api/v1/session*` `Cache-Control: no-store`. Zależności
    tras: `require_session`, `require_csrf`, `current_principal`. Tokeny:
    `issue_one_time_token(index, kind, *, minted_by)` i
    `redeem_one_time_token` (w `session_tokens` skrót SHA-256 i principal
    wystawiający; `SCHEMA_VERSION` 2). Sesje w pamięci serwera
    (`SessionStore`, koniec po 24 h bez żądań, restart kończy wszystkie).
    `resolve_indexed_path(root, relative)` → `PathOutsideRootError` albo
    `FileNotFoundError`; `csp_header(settings)`; `TokenRedactionFilter`.
  - *Błędy i aplikacja*: `archiwista/api/errors.py` (`ApiError(status,
    code, detail)`, `problem_response`, `install_error_handlers`, tytuł
    z `MESSAGES["api_title_<code>"]`); `create_app(*, port, settings,
    index_path, sessions, web_dir)` z `app.state.settings`, `sessions`,
    `index_path`, `port`; `/` i `/static/…` z `archiwista/web/`; OpenAPI
    `/api/v1/openapi.json` wymaga sesji, domyślnych `/docs` brak.
    `archiwista serve [--host] [--port] [--no-browser] [--access-log]`
    i `archiwista token [--port] [--json]` (`archiwista/server.py`).
- **Uprawnienia — `archiwista/state/`, `archiwista/auth/` (krok 8b,
  A-ADR-029, SPEC 4.3 i 10.2):** `StateStore` — baza stanu
  `<user_data_dir>/state.sqlite`, osobna od indeksu, migracje zamiast
  przebudowy; `Authorizer(state, settings)` z `can(principal, action,
  resource) -> bool`, `require(...)` (`PermissionDeniedError` →
  `403 permission_denied`) i `visible_projects(principal) ->
  ProjectVisibility` (zbiór kluczy projektów albo „wszystkie”), zależność
  tras `authorizer`. Każda usługa i każde zapytanie o projekty dostaje
  `principal`; routery i CLI nie liczą uprawnień same. Projekt niewidoczny
  → `404 not_found`, widoczny bez uprawnienia do działania →
  `403 permission_denied`.
- **Interfejs WWW — `archiwista/web/`** (10a–11): `src/api.js` konsumuje
  tylko `/api/v1` (nie `mockup/data/` ani ścieżek plików serwera);
  `main.js`, router i `src/routes.js` należą do 10a (widok dopisuje jedną
  linię trasy); słownik tekstów dzielony per widok (`src/labels/<widok>.js`,
  składany przez `src/labels/index.js` z 10a), więc 10b, 10c i 11 nie
  edytują wspólnego pliku. Ekran v0.1 nie importuje `mockup/src/data.js`
  ani `assistant.js`.

## Kolejność prac

| Krok | Tytuł | Zależności | Równolegle z | Stan |
|---|---|---|---|---|
| 0 | Angielskie pliki kontrybutorów | — | — | ukończony (`de157c3`) |
| 1 | Pakiet, wspólny kontrakt i narzędzia | 0 | — | ukończony (`c74f8d4`) |
| 2 | Wtyczki, rozszerzenie kontraktu i adapter Kartografa | 1; KA w `../Kartograf` | 3, 4 | |
| 3 | Konfiguracja i diagnostyka | 1; rejestr z 2 przed odbiorem | 2, 4 | |
| 4 | Magazyn testowy | 1; KA w `../Kartograf` | 2, 3 | |
| 5 | Lokalny indeks, zapytania i pokrycie lokalne | 2 | 3, 4 | |
| 6a | Skaner i odświeżenie widoku | 2, 4, 5 | 7, 8 | |
| 6b | Zadania w tle: skan, obrysy, potwierdzenie dowiązania | 3, 6a, 7 | 8, 9a | |
| 7 | Projekty i stan magazynu | 2, 4, 5 | 6a, 8 | |
| 8 | Ochrona dostępu lokalnego, sesja i `serve` | 3, 5 | 6a, 7 | |
| 8b | Model uprawnień | 5, 8 | 6a | |
| 9a | FastAPI: odczyt, modele, błędy, ustawienia | 3, 6a, 7, 8, 8b | 6b | |
| 9b | Zadania w tle przez HTTP i SSE | 6b, 9a | 9c, 10a, 12 | |
| 9c | Obszary i pokrycie lokalne przez HTTP | 6a, 9a | 9b, 10a, 12 | |
| 10a | Powłoka interfejsu, sesja w przeglądarce, kreator | 6b, 8, 9a | 9b, 9c, 12 | |
| 10b | Mapa | 9c, 10a | 10c, 11, 12 | |
| 10c | Katalog | 9a, 10a | 10b, 11, 12 | |
| 11 | Karta pliku, Projekty i Magazyn | 7, 9b, 10a | 10b, 10c, 12 | |
| 12 | CLI i przewodnik dla agentów | 8, 8b, 9a | 9b–11 | |
| 13 | E2E, awarie udziału i pomiary | 4, 6b, 9a–9c, 10a–10c, 11, 12 (perf od 6b i 9a) | perf z 10–12 | |
| 14 | Dokumentacja, bramka i wydanie | 0–13 (z 8b); Kartograf 0.8.0 z KA | — | |

### 0. Angielskie pliki kontrybutorów — ukończony
- **Stan:** `de157c3` — `CONTRIBUTING.md`, `CONTRIBUTORS.md`
  i `.github/pull_request_template.md` (z checklistą testów i lintów) po
  angielsku (A-ADR-026 errata 2, `DEVELOPMENT_STANDARDS.md` §0); nie
  powielać w zadaniach implementacyjnych.

### 1. Pakiet, wspólny kontrakt i narzędzia — ukończony
- **Stan:** `c74f8d4` — `pyproject.toml` (setuptools, Python ≥ 3.12,
  `kartograf>=0.8.0,<0.9`, FastAPI, Uvicorn, Pydantic, platformdirs,
  shapely, pyproj; extra `dev`; skrypt `archiwista`; pusta grupa entry
  points `archiwista.sources`; pakowanie `archiwista/web/**`), Ruff (88
  znaków, `D`, konwencja numpy), mypy `strict`, pytest z markerami `live`,
  `perf`, `smb` (domyślnie wyłączone) i `--cov-fail-under=80`,
  `requirements.lock` (bez ścieżki `../Kartograf`; Kartograf edytowalnie
  z gałęzi przed lockiem); `archiwista/{__init__,cli,errors,messages}.py`
  (CLI ma na razie tylko `--help`; polecenia dochodzą w krokach 3, 6b, 8
  i 12); `archiwista/sources/{protocol,types}.py` z umową z sekcji
  „Umowy”; `tests/contract/test_source_protocol.py`, `tests/unit/test_cli.py`.
- **Dalej:** zmiany umowy źródła wyłącznie przez rozszerzenia kroku 2.

### 2. Wtyczki, rozszerzenie kontraktu i adapter Kartografa
- **Cel:** `archiwista/sources/registry.py`, rozszerzenia umowy (sekcja
  „Umowy”, pkt 1–5), `archiwista/adapter/kartograf/`, entry point
  `kartograf = "archiwista.adapter.kartograf:load"`, `packaging` jako
  jawna zależność (porównanie wersji). Rejestr ładuje leniwie, wykazuje
  `available`/`not_installed`/`incompatible`/`error`, wersje i schematy;
  wadliwa wtyczka nie kończy procesu. Adapter: `probe`; `segments` →
  `list_segments`; `iter_entries` → `iter_store(segment, units,
  skip_versions=katalogi known_versions)` z `meta` z `StoreEntry.sidecar`
  i `describe_segment` (bez ponownego odczytu) oraz `skipped`; `read_meta`
  → `read_sidecar`; `footprint` → `file_footprint` z lokalną pamięcią
  jednostek (SQLite w `cache_dir`, `BBox` jako lista 5 wartości);
  `transformer` → `pinned_transform`; `countries` → `countries_for_bbox`;
  `confirm_link` → `link_target`; `sheet_grid` → `find_sheets_for_bbox`
  i parsery; projekty wyłącznie `open_project` i `get_project_status`.
  Testowy drugi adapter to pakiet-fixtura (`tests/fixtures/second_source/`)
  rejestrowany w teście przez katalog `*.dist-info` z `entry_points.txt` na
  `sys.path` — tą samą drogą co produkcja; nie jest produkcyjnym źródłem
  IMGW.
- **Interfejs:** typy z kroku 1 z rozszerzeniami; żadna reguła parsowania
  `data/` ani translacji CRS po stronie warstw wyżej.
- **Test/odbiór:** `tests/contract/test_kartograf.py` — KA-1..KA-6
  i `list_segments` w `kartograf.__all__` z sygnaturami,
  `test_installed_kartograf_within_pinned_range`, wynik adaptera na
  fixturze 4 zgodny z `iter_store`, `test_known_versions_are_not_reread`
  (znane wersje wracają jako `skipped` bez `meta`),
  `test_scan_never_calls_link_target` (podmieniony `link_target` zgłasza
  wyjątek; pełne i przyrostowe `iter_entries` przechodzą),
  `test_segments_cover_full_scan`, `test_unit_footprint_from_local_cache_offline`
  (pamięć jednostek wypełniona z góry daje obrys `unit` przy
  `network=False`), transformacja CZ z opisem przypiętej operacji;
  `tests/contract/test_imports.py` — Kartograf importowany wyłącznie
  w `archiwista/adapter/kartograf/` i tylko z `kartograf.__all__`, start
  bez `imgwtools`; `tests/contract/test_plugins.py` — drugi entry point,
  brak pakietu, zła wersja/schemat, wyjątek fabryki;
  `tests/contract/test_source_protocol.py` — minimalny adapter bez
  zdolności opcjonalnych nadal spełnia protokół.
- **Zależności:** 1; KA-1..KA-6 i `list_segments` w `../Kartograf`.
  **Równolegle:** 3 i 4.

### 3. Konfiguracja i diagnostyka
- **Cel:** `archiwista/config.py` (`ConfigStore`, `StoreConfig`,
  `AppSettings`, `SettingsService` dla `GET/PUT /settings`): TOML
  w `platformdirs.user_config_dir`, indeks/`cache/`/`jobs/`/`areas/`
  w `user_data_dir`. Ustawienia v0.1: magazyny (`id`, `name`, `kartograf`,
  `path_aliases`, rodzaj `local`/`share` wykrywany przy dodaniu — typ
  systemu plików `cifs`/`smb3`/`nfs` albo ścieżka UNC — i edytowalny),
  katalogi projektów, `offline`, podkłady (nazwa, adres kafli/WMS,
  atrybucja; domyślnie szary OSM), port, interwały skanu (5 min
  `local`/15 min `share`), `scan_threads` (8). Walidacja: korzenie
  istnieją i są czytelne, katalogi producentów nie są zagnieżdżone, wersje
  i schematy przez rejestr 2; zapis TOML atomowy. `archiwista doctor`:
  diagnostyka po polsku (wtyczki, wersje, schematy, magazyny, uprawnienia,
  port), bez tworzenia plików na udziale. Kreator w przeglądarce to krok
  10a, `serve` — 8, `reindex` — 6b.
- **Interfejs:** `ConfigStore`/`StoreConfig`/`SettingsService` i
  `SourceState`; `SettingsService` powiadamia subskrybentów o zmianie
  (harmonogram 6b, CSP 8); przeglądarka zmienia ustawienia tylko przez
  API 9a.
- **Test/odbiór:** `tests/unit/test_config.py` (przywrócenie TOML, kilka
  magazynów, korzeń tylko do odczytu, zagnieżdżone katalogi odrzucone,
  aliasy) i `tests/unit/test_doctor.py` (odłączony katalog, brak wtyczki,
  zła wersja: polski opis i sposób naprawy, niezerowy kod wyjścia, brak
  nowych plików w magazynie). **Zależności:** 1; rejestr 2 przed odbiorem.
  **Równolegle:** 2 i 4.

### 4. Magazyn testowy
- **Cel:** `tests/fixtures/make_store.py`: `make_store(output_dir: Path, *,
  slots: int, seed: int) -> StoreManifest` i wywołanie
  `python -m tests.fixtures.make_store --slots 50000 --seed 1
  <katalog-danych>/store-50k` (proporcje SPEC 4.5). Rodziny: rastry 64 × 64
  (ASC, GeoTIFF, JPEG z JGW), mały GPKG, ZIP, LAZ z kilkoma punktami;
  kilka wersji slotu, dowiązania ścieżki standardowej i `full_sheet/`,
  wycinki `bbox/`, kolekcje (TERYT), HSG, projekty (30 w wariancie perf)
  z zadaniami i przypięciami, także starszej wersji. **Publiczne API
  Kartografa tam, gdzie istnieje:** ścieżki slotów, `versions/`
  i `full_sheet/` z `FileStorage` (ten sam rejestr co zapis), projekty
  przez `init_project`/`add_project_task`. Publiczne API 0.8.0 nie ma
  zapisu wersji bez sieci (wersje, sidecary i dowiązania tworzą tylko
  `download_*`, przypięcia — `download_project`), dlatego pliki wersji,
  sidecary `kartograf-meta/1`, dowiązania twarde i `files[]` manifestu
  generator zapisuje sam według ARCH 3.2–3.3 (jak testy odczytu Kartografa)
  i **od razu** sprawdza czytnikiem Kartografa: każdy przypadek regularny
  musi wrócić z `iter_store` jako oczekiwany wpis bez problemu, a manifest
  — przejść ścisłe `open_project`; rozbieżność przerywa generator, zanim
  trafi do testów indeksu. Odręczne z założenia są tylko przypadki celowo
  błędne: brak i nieczytelny sidecar, nieznany segment, `kampanie/`,
  `.incoming` starszy niż 24 h, klucze 0.8.0-dev, sidecar sprzed ADR-031,
  sidecar dowiązania wskazujący inną wersję niż dowiązanie (dla
  `link_check`), błędny manifest. Dane testów w `tmp_path`, magazyn perf
  w `<katalog-danych>`; nic w repo.
- **Interfejs:** `make_store` i manifest oczekiwanych przypadków;
  konstrukcja magazynu należy wyłącznie do testów; test kontraktu
  sprawdza, co widzi **Kartograf**, a nie indeks.
- **Test/odbiór:** `tests/contract/test_store_fixture.py` porównuje
  manifest z `kartograf.iter_store` (z problemami), bez sieci; czas
  generatora dla `--slots 50000` trafia do raportu kroku 13.
  **Zależności:** 1, KA w `../Kartograf`. **Równolegle:** 2 i 3.

### 5. Lokalny indeks, zapytania i pokrycie lokalne
- **Cel:** `archiwista/index/{schema,queries,writer,coverage}.py`: SQLite
  WAL tylko lokalnie (`<user_data_dir>/index.sqlite`), `schema_version` —
  zmiana schematu oznacza przebudowę. Tabele v0.1: `stores`, `segments`,
  `slots`, `versions` (z obrysem natywnym i jego układem, rodzajem
  położenia `footprint`/`country`/`none` z powodem), `footprints` (R*Tree
  WGS84, tylko wersje z obrysem), `search` (FTS5), `projects`,
  `project_tasks`, `pins`, `issues`, `areas`, **jedna** tabela `jobs`
  (`id`, `kind`, `actor`, `store`, `params` JSON, `state`, `created_at`,
  `started_at`, `finished_at`, `pid`, `summary`, `error`) z `job_events`
  (`job_id`, `seq`, `type`, `data`, `at`) oraz `session_tokens` (skrót
  SHA-256, rodzaj, `expires_at`, `used_at`). Bez `scan_runs`: czasy
  i statystyki skanów to zadania `scan`. Indeksy po magazynie, segmencie,
  jednostce, roku danych, produkcie, projekcie i stanie; klucze `(store,
  relative_path)`; `sha256` wersji jako treść; `data_year` nigdy z daty
  pobrania; zajętość sumuje tylko unikalne wersje, nie dowiązania.
- **Interfejs:** `IndexQueries` z umowy: strona katalogu z filtrami `q`,
  `store`, `product`, `country`, `years`, `unit`, `location`, `versions`,
  `status` i obszar; kursory deterministyczne; liczniki grup położenia
  (`w obszarze`, `cały kraj`, `bez obrysu`); wyszukiwanie po godle, TERYT,
  KU, etykiecie, numerze zgłoszenia i prefiksie SHA od 8 znaków; mapa do
  5000 obrysów, powyżej agregacja do siatki. `LocalCoverage` według
  decyzji 5, z transformatorem wstrzykniętym (indeks nie importuje
  adaptera); wynik: `ratio`, `area_km2`, `covered_km2`, `crs`,
  `versions_count`, `stale` albo powód braku procentu.
- **Test/odbiór:** `tests/unit/test_index.py` (grupy bez położenia, rok
  danych ≠ pobrania, 2 dowiązania do jednej wersji → jeden rozmiar, pin do
  starej wersji, kursory, filtry z `unit`), `tests/unit/test_queries.py`
  (wyszukiwanie po identyfikatorach, 5000 obrysów i agregacja),
  `tests/unit/test_coverage.py::test_local_coverage_in_planar_crs` (obszar
  wydłużony N–S i W–E na 50° N: wynik zgodny z polem w EPSG:2180 z
  dokładnością 0,5 pkt proc.; nakładające się obrysy liczone raz; obszar CZ
  w EPSG:5514; produkt bez kraju → `no_planar_crs`). **Zależności:** 2.
  **Równolegle:** 3 i 4.

### 6a. Skaner i odświeżenie widoku
- **Cel:** `archiwista/index/scanner.py` według decyzji 3: lista segmentów,
  pula wątków po segmentach, `known_versions` z indeksu, jeden wątek zapisu
  z paczkami, pula obrysów (bez sieci), podsumowanie per segment. Każde
  kompletne przejście bez `units` (pełne albo przyrostowe) oznacza
  niewidziane wersje stanem „brak pliku” z datą; wpis znika dopiero po
  *kolejnym* pełnym skanie, który też go nie widzi; skan jednego segmentu
  i `refresh_view` oznaczają tylko swój zakres. Magazyn niedostępny
  (`probe` ≠ dostępny, pusta lista segmentów przy niepustym indeksie albo
  błąd I/O w trakcie) → przerwanie bez zmian wpisów, stan `unavailable`
  z czasem. `refresh_view(store, segment, units)` (≤ 500 slotów, paczki
  jednostek w puli) zwraca `IndexStatus`.
- **Interfejs:** wejście `SourceAdapter` + `StoreConfig` + tryb
  (`full`/`incremental`, opcjonalnie `segment`); wyjście `IndexWriter`;
  zdarzenia przez wywołanie zwrotne (`progress`: segment, `current`,
  `total`, liczba wpisów; `notice`), które 6b zamienia na JSON Lines.
  Skaner nie importuje Kartografa i nie zna `link_target`.
- **Test/odbiór:** `tests/integration/test_scanner.py`:
  `test_full_then_incremental_detects_new_version_and_relinked_current`,
  `test_incremental_does_not_reread_known_versions`,
  `test_missing_version_marked_then_removed_after_next_full_scan`,
  `test_pins_survive_rescan`, `test_empty_mount_point_keeps_index`,
  `test_parallel_scan_equals_sequential`,
  `test_full_scan_keeps_unit_footprint`,
  `test_refresh_view_updates_only_requested_units`. **Zależności:** 2, 4, 5.
  **Równolegle:** 7 i 8.

### 6b. Zadania w tle: skan, obrysy, potwierdzenie dowiązania
- **Cel:** `archiwista/jobs/{supervisor,worker,protocol,scheduler}.py`:
  nadzorca w serwerze, proces roboczy na zadanie
  (`python -m archiwista.jobs.worker`, A-ADR-007), protokół JSON Lines
  `progress`/`notice`/`result`/`error`, zapis `jobs`/`job_events`,
  rozsyłanie `progress`/`notice`/`state` do subskrybentów SSE (9b). Rodzaje
  v0.1: `scan` (6a, potem `scan_projects` z kroku 7 — właścicielem tego
  wywołania jest 6b), `footprints` (decyzja 4), `link_check` (`confirm_link`,
  KA-5; niezgodność z sidecarem → problem `link_mismatch` z instrukcją).
  Każde zadanie ma `actor` (`local` w v0.1; konto od v0.4). Na magazyn
  naraz jedno zadanie zapisujące indeks (`scan`, `footprints`); kolejne →
  `JobConflictError`. Restart serwera: `running` bez żywego procesu →
  `interrupted`. Harmonogram: przy starcie przyrostowy, gdy ostatni
  starszy niż 15 min; potem co 5 min (`local`) albo 15 min (`share`);
  pełny kontrolny raz na dobę; dla magazynu niedostępnego tylko `probe`;
  nowy magazyn zapisany w ustawieniach (`SettingsService`, krok 3) → pełny
  skan tego magazynu.
  `archiwista reindex [--store ID]` rejestruje `scan` (`mode=full`) w tej
  samej tabeli `jobs` i wykonuje go na pierwszym planie (trwające zadanie
  magazynu → kod `conflict`, niezerowe wyjście).
- **Interfejs:** `JobSupervisor` z umowy; stany i zdarzenia z umowy.
- **Test/odbiór:** `tests/integration/test_jobs.py`
  (`test_worker_protocol_maps_to_sse_events`,
  `test_second_index_job_for_store_conflicts`,
  `test_restart_marks_running_job_interrupted`, `test_jobs_record_actor`,
  `test_footprints_job_assigns_cached_unit_outlines` — offline, klucze
  jednostek dodane do pamięci po skanie, `test_link_check_reports_mismatch`;
  świadomy przebieg `-m live` z siecią dla jednej jednostki TERYT),
  `tests/integration/test_scan_worker.py::test_queries_answer_during_scan`,
  `tests/integration/test_disconnected_store.py::test_disconnect_preserves_index_then_incremental_refresh`.
  **Zależności:** 3, 6a, 7. **Równolegle:** 8 i 9a.

### 7. Projekty i stan magazynu
- **Cel:** `archiwista/index/projects.py` z
  `scan_projects(adapter, writer, *, project_dirs, stores) ->
  ProjectScanSummary`: odkrywanie `kartograf-project.json` w katalogach
  projektów do głębokości 4 z pominięciem `.git`, katalogów ukrytych
  i korzeni magazynów; `read_project`/`project_status` adaptera tylko dla
  nowych albo zmienionych manifestów (czas modyfikacji i rozmiar);
  przypięcia łączone z wersjami po ścieżce i `sha256`; lista projektów
  używających pliku, zadania i ich istniejące polecenia.
  `archiwista/services/{projects,stores}.py`: `ProjectDetail`,
  `StoreSummary` (zajętość per produkt z każdą wersją raz, projekty,
  ostatni skan z wykonawcą, niebieżące i nieprzypięte wersje). Nieznany
  magazyn projektu, błędny manifest, brakujący przypięty plik, nieznany
  segment, osierocony sidecar, `.incoming` starszy niż 24 h i
  `link_mismatch` to widoczne problemy z *instrukcją* naprawy, bez akcji
  usuwania.
- **Interfejs:** `ProjectInfo`/`ProjectPin` → `projects`, `project_tasks`,
  `pins`; funkcja `scan_projects` dla 6b.
- **Test/odbiór:** `tests/integration/test_projects.py` (zmieniony
  manifest, przypięta starsza wersja, brak wersji, błędny manifest nadal
  widoczny, nieznany magazyn) i `tests/unit/test_store_summary.py`
  (dowiązania bez zawyżenia rozmiaru). **Zależności:** 2, 4, 5.
  **Równolegle:** 6a i 8.

### 8. Ochrona dostępu lokalnego, sesja i `serve`
- **Cel:** `archiwista/security.py`, `archiwista/api/session.py`,
  `archiwista/app.py` (fabryka: kontrola `Host`, sesji, CSRF i nagłówków,
  router sesji, pliki statyczne) i `archiwista serve` według decyzji 8:
  bind wyłącznie `127.0.0.1` (odmowa `--host 0.0.0.0` i innych bez trybu
  zespołu, niezerowy kod), `Host` tylko `127.0.0.1:<port>`/`localhost:<port>`
  (`400 invalid_host`), token startowy we fragmencie, `POST`/`GET
  /api/v1/session`, `POST /api/v1/session/tokens`, osobny token CSRF
  (double-submit), reguła `Origin`/`Sec-Fetch-Site`, CSP liczona
  z bieżących ustawień, `Referrer-Policy: no-referrer`, `Cache-Control:
  no-store` dla `/api/v1/session*`, dziennik dostępu wyłączony albo
  redagowany. Każdy odczyt pliku: identyfikator z indeksu, `realpath` po
  rozwiązaniu w korzeniu magazynu/projektu, dowiązanie symboliczne
  wychodzące na zewnątrz odrzucone.
- **Interfejs:** `require_session`, `require_csrf`, `resolve_indexed_path`,
  `issue_one_time_token`, `csp_header(settings)` współdzielone przez
  wszystkie routery i pliki statyczne; `actor` sesji (`local`) trafia do
  zadań; brak surowych ścieżek klienta.
- **Test/odbiór:** `tests/unit/test_security.py` (obcy `Host`, token użyty
  dwa razy i po terminie, bez sesji → 401, brak albo zły CSRF → 403, obcy
  `Origin` → 403, `Sec-Fetch-Site: cross-site` → 403, przeglądarka bez
  `Origin` przy zmianie stanu → 403, nawigacja z `Sec-Fetch-Site: none`
  przechodzi, klient bez `Origin` i `Sec-Fetch-*` z sesją i CSRF →
  przechodzi, brak nagłówków CORS, `..` i symlink
  odrzucone, CSP z podkładami tylko online, `test_token_not_logged` —
  wymiana tokenu i żądanie z `?token=` nie zostawiają wartości w żadnym
  dzienniku, także `uvicorn.access`) i `tests/integration/test_serve.py`
  (`test_serve_refuses_non_loopback_host` — niezerowy kod, brak
  nasłuchu; `test_serve_prints_fragment_url` — adres z `#token=`, wymiana
  przez prawdziwy serwer w wątku). **Zależności:** 3, 5. **Równolegle:** 6a
  i 7.

### 8b. Model uprawnień
- **Cel (A-ADR-029, SPEC 4.3, 10.2):** model i egzekwowanie uprawnień dla
  jednego lokalnego właściciela, sprawdzone testami z wieloma tożsamościami;
  logowanie innych osób dopiero w v0.4.
  - `archiwista/state/{schema,store,export}.py`: baza stanu
    `<user_data_dir>/state.sqlite` (SQLite WAL, wyłącznie lokalnie, nigdy
    na udziale ani w magazynie, osobny plik obok `index.sqlite`),
    `PRAGMA user_version` i migracje schematu — przebudowa indeksu jej nie
    dotyka. Tabele: `users` (`id`, nazwa wyświetlana, `disabled`, czasy),
    `groups`, `memberships`, `roles` (`user_id`, `admin`/`store_writer`),
    `project_acl` (klucz projektu = katalog projektu po `realpath`,
    niezależny od identyfikatorów indeksu; `owner`; `visibility`
    `public`/`users`/`group`/`private`), `project_acl_entries` (osoba albo
    grupa), `permission_log` (kto, kiedy, co, stan przed i po). Konta z v0.1
    nie mają haseł i nie mogą się logować (v0.4).
  - `archiwista/auth/`: `Principal(id, kind, roles, groups)` i
    `LOCAL_OWNER` z kroku 8 bez zmian; `principal_for(state, user_id)`
    (role i grupy z bazy stanu); `authorize.py` z `can(principal, action,
    resource)` — akcje v0.1: `project.view`, `project.share`,
    `users.manage`, `groups.manage`, `settings.write`, `store.write` —
    `require(...)` i `visible_projects(principal)`. Reguły: `admin` widzi
    wszystkie projekty i zarządza kontami, grupami, ustawieniami
    i udostępnianiem każdego projektu; właściciel — swojego projektu;
    `public` widzą wszyscy, `users` — osoby z wpisu, `group` — członkowie
    grupy z wpisu, `private` — tylko właściciel; projekt bez wpisu ma
    widoczność z ustawienia `default_project_visibility` (domyślnie
    `public`); `agent` z tokenu działa z rolami i grupami wystawiającego
    (krok 8). `store.write` = rola `store_writer` albo ustawienie
    `store_write_for_all` (domyślnie `false`): punkt kontroli bez działań
    w v0.1, pierwsze użycie w v0.3.
  - Filtr `visible_projects(principal)` w zapytaniach indeksu i usługach
    kroku 7: lista i szczegóły projektów, przypięcia („Przypięta w:” karty
    slotu), wyszukiwanie z filtrem projektu, raport magazynu (liczniki
    obejmują wszystkie projekty, nazwy — tylko widoczne).
  - `archiwista/api/admin.py` (router dopisany do fabryki z kroku 8):
    `GET/POST /users`, `PATCH/DELETE /users/{id}`, `GET/POST /groups`,
    `PUT /groups/{id}/members`, `DELETE /groups/{id}` — tylko `admin`;
    `GET/PUT /projects/{id}/access` — właściciel albo `admin`; zmiany
    z CSRF, każda zapisana w `permission_log`.
  - CLI (`archiwista/cli.py`): `archiwista users list|add|roles|remove`,
    `archiwista groups list|add|members|remove`, `archiwista share PROJEKT
    --visibility public|users|group|private [--user ID…] [--group ID…]`,
    każde z `--json` (model jak w API), oraz `archiwista state export
    [--output PLIK]` (JSON `archiwista-state/1`: konta, grupy, członkostwa,
    role, widoczność projektów, dziennik) i `archiwista state import PLIK`
    (tylko do pustej bazy stanu — odtworzenie z kopii). CLI działa jako
    `LOCAL_OWNER`.
  - Ustawienia `store_write_for_all` i `default_project_visibility`
    w konfiguracji kroku 3 (zmiana — `settings.write`, czyli `admin`).
  - Poza krokiem: logowanie, hasła, ekrany kont i udostępniania (v0.4),
    klucze pamięci podglądów danych własnych zależne od widoczności (v0.2).
- **Interfejs:** `StateStore`, `Authorizer` i zależność `authorizer` dla
  9a–12; `IndexQueries` i usługi projektów przyjmują `principal` (albo
  gotowy `ProjectVisibility`) — bez filtrowania w routerach i CLI.
- **Test/odbiór:** `tests/unit/test_authorize.py::test_visibility_matrix`
  (parametryzacja `public`/`users`/`group`/`private` × właściciel / osoba
  z wpisu albo członek grupy z wpisu / inna osoba / `admin`, także `agent`
  z tokenu wystawionego przez każdą z nich, i `store.write` z rolą, bez roli
  i z `store_write_for_all`), `tests/integration/test_permissions_api.py`
  (kilka tożsamości wstrzykniętych przez zależność `current_principal`:
  `/projects`, `/projects/{id}`, przypięcia i wyszukiwanie zgodne
  z macierzą; projekt niewidoczny → `404 not_found`; `PUT
  /projects/{id}/access` przez inną osobę → `403 permission_denied`;
  trasy kont i grup bez `admin` → `403 permission_denied`, bez CSRF →
  `403 csrf_rejected`; zmiana w `permission_log`; tryb lokalny widzi
  wszystko), `tests/integration/test_state.py` (przebudowa indeksu nie
  zmienia `state.sqlite`; migracja ze starszego `user_version`; eksport →
  import do pustej bazy daje tę samą macierz; import do niepustej bazy
  odrzucony) i `tests/integration/test_cli.py::test_admin_cli_json_equals_http`.
  **Zależności:** 5, 8. **Równolegle:** 6a; przed 9a.

### 9a. FastAPI: odczyt, modele, błędy, ustawienia
- **Cel:** `archiwista/api/{models,errors,health,stores,slots,map,projects,settings}.py`
  i ich routery w `app.py`: `GET /health` (wersje, `IndexStatus`, stan
  magazynów i zadań), `/sources`, `/stores`, `/stores/{store}`,
  `/products` (tylko zaindeksowane, nazwy z `describe_segment`), `/slots`
  (filtry z kroku 5, `limit ≤ 200`, `cursor`),
  `/stores/{store}/slots/{slot}`, `/stores/{store}/versions/{version}`,
  `.../sidecar`, `/groups/{parent_request}`, `/map/footprints`,
  `/map/sheets`, `/projects`, `/projects/{id}`, `/projects/{id}/status`,
  `GET/PUT /settings` (walidacja kroku 3; zmiana offline/podkładów zmienia
  CSP kolejnych odpowiedzi). Prefiks `/api/v1`; OpenAPI
  `/api/v1/openapi.json`, lokalne `/api/docs`. Odłączony magazyn: listy
  z indeksu `200` ze stanem `stale`; `503 store_unavailable` tylko gdy
  żądanie wymaga źródła i indeks nie ma wyniku; każdy stan magazynu ma czas
  ostatniego skanu, postęp i informację o aktualności. JSON bez ścieżek
  absolutnych poza „kopiuj ścieżkę” karty (aliasy 4.6). Odłożyć endpointy
  pobierania, dostępności u źródła, edycji projektu, podglądów, stacji
  i rozmów; nie zwracać pozornych sukcesów.
- **Interfejs:** cienkie routery → `IndexQueries` i usługi 3, 7; modele
  z przykładami (kursor, filtry, grupy położenia, karta, problem RFC 9457).
  Każdy router bierze `Principal` z zależności `current_principal` (krok 8)
  i przekazuje go do usług i zapytań; lista, szczegóły i status projektów
  oraz przypięcia na karcie slotu filtruje `visible_projects(principal)`
  z kroku 8b (tryb lokalny widzi wszystko), `PUT /settings` wymaga
  `settings.write` (A-ADR-029).
- **Test/odbiór:** `tests/integration/test_api.py` (każda trasa, filtry,
  limit 200 i kursor, RFC 9457 i OpenAPI z przykładami, `stale` po
  odłączeniu, `test_source_states_map_to_503`, `curl` z cookie-jar po
  wymianie tokenu widzi stan, bez sesji 401),
  `tests/integration/test_read_only_store.py::test_read_only_store_scan_and_browse`
  (magazyn z prawami tylko do odczytu: skan 6a i wszystkie trasy odczytu;
  migawka drzewa magazynu przed i po identyczna),
  `tests/integration/test_second_adapter.py::test_second_adapter_indexes_and_browses_without_core_changes`
  (wtyczka-fixtura z entry point → skan → `/sources`, `/slots`, karta).
  **Zależności:** 3, 6a, 7, 8, 8b. **Równolegle:** 6b; po 9a kroki 9c, 10a
  i 12, po 6b — 9b.

### 9b. Zadania w tle przez HTTP i SSE
- **Cel:** `archiwista/api/jobs.py`: `POST /stores/{store}/scan` (`mode`:
  `incremental`/`full`, opcjonalnie `segment`) → `202` z zadaniem;
  `POST /stores/{store}/footprints` → `202`, w trybie offline
  `409 offline_mode`; `POST /stores/{store}/link-check` (`{"slot": …}`) →
  `202`; trwające zadanie zapisu indeksu magazynu → `409 conflict`
  z `job` (`id`, `kind`, `state`) w treści problemu; `GET /jobs` (filtry
  `kind`, `store`, `state`; `limit`/`cursor`), `GET /jobs/{id}` (z
  `actor`), `GET /jobs/{id}/events` (SSE `progress`/`notice`/`state`;
  `id:` = numer zdarzenia, wznowienie przez `Last-Event-ID` z
  `job_events`). Wszystkie `POST` z CSRF.
- **Test/odbiór:** `tests/integration/test_jobs_api.py`
  (`test_scan_events_progress_notice_state`,
  `test_second_scan_of_store_returns_409_with_job_id`,
  `test_footprints_refused_offline`, `test_job_detail_has_actor`,
  `test_sse_resume_from_last_event_id`, `test_post_without_csrf_rejected`).
  **Zależności:** 6b, 9a. **Równolegle:** 9c, 10a i 12.

### 9c. Obszary i pokrycie lokalne przez HTTP
- **Cel:** `archiwista/areas.py`, `archiwista/api/areas.py`:
  `POST /areas` — GeoJSON (WGS84) w treści albo plik (GeoJSON, GPKG,
  spakowany SHP z plikami bocznymi). Limity (decyzja 9): treść > 50 MB →
  `413 area_too_large`; archiwum, którego zadeklarowany rozmiar po
  rozpakowaniu przekracza 200 MB albo którego człon wychodzi poza katalog,
  jest odrzucane przed rozpakowaniem;
  parsowanie (pyogrio jako jawna zależność) w osobnym procesie zabijanym
  po 30 s zegara → `422 area_unreadable`; geometria > 100 000
  wierzchołków → `422 area_too_complex` (bez cichego upraszczania); układ
  pliku przeliczany do WGS84 przez `GeoAdapter.transformer` (KA-6), kraje
  z `GeoAdapter.countries`, pole w układzie płaskim. Kopia pliku
  w `<user_data_dir>/areas/<id>/`, kopie starsze niż 7 dni usuwane przy
  starcie (geometria zostaje w indeksie). `GET /areas/{id}` (geometria,
  `area_km2`, kraje). `GET /local-coverage?area_id&product&store`: najpierw
  `refresh_view` slotów obszaru (≤ 500; jednostki z siatki godeł albo
  z obrysów w indeksie), potem `LocalCoverage`; przy niedostępnym magazynie
  albo przekroczonym czasie — wynik z indeksu ze `stale` i przyczyną.
- **Test/odbiór:** `tests/integration/test_areas.py` (GeoJSON, GPKG, SHP
  w ZIP; 50 MB; deklarowane 200 MB po rozpakowaniu; zabicie wstrzykniętego
  wolnego parsera przy limicie 1 s; 100 001 wierzchołków; porządki po
  7 dniach), `tests/integration/test_local_coverage.py` (odświeżenie przed
  odpowiedzią, procent w układzie płaskim, `stale` przy odłączeniu).
  **Zależności:** 6a, 9a. **Równolegle:** 9b, 10a i 12.

### 10a. Powłoka interfejsu, sesja w przeglądarce, kreator
- **Cel:** `archiwista/web/{index.html,styles.css,vendor/}`,
  `src/{main,api,router,routes,setup}.js`, `src/labels/`. Przenieść wygląd
  i użyteczne komponenty z `mockup/` (panele, resizery), usunąć CDN, fonty
  online, `mockup/data` i symulowane zadania; dołączyć Preact, htm
  i MapLibre w wersji CSP (`maplibre-gl-csp.js`,
  `maplibre-gl-csp-worker.js`, CSS, glify) z przypiętymi wersjami
  i licencjami (zgodnymi z MIT). `api.js`: wymiana tokenu z
  `location.hash`, usunięcie fragmentu, nagłówek `X-Archiwista-CSRF`
  z ciasteczka `archiwista_csrf` (po przeładowaniu — `GET /session`),
  obsługa problemów RFC 9457 i `401` (instrukcja po polsku: „otwórz adres
  z terminala albo `archiwista token`”). Router: URL jako źródło stanu
  (widok, obszar, produkt, filtry, położenie i zoom mapy). Kreator
  pierwszego uruchomienia (`setup.js`, `GET/PUT /settings`; pełny skan
  nowego magazynu zleca harmonogram 6b, a powłoka pokazuje postęp ze stanu
  `/health`). Polski słownik, daty `RRRR.MM.DD` w UI,
  ISO w API, wartości techniczne pod jednym kliknięciem.
- **Interfejs:** wyłącznie `api.js` → trasy 8, 9a–9c; JSDoc typów
  odpowiedzi; trasy i słownik według umowy WWW.
- **Test/odbiór:** `tests/e2e/test_shell.py`
  (`test_fragment_token_starts_session_and_is_removed_from_url`,
  `test_no_session_shows_instruction`,
  `test_first_run_wizard_saves_settings`,
  `test_no_csp_violations_offline` — nasłuch `securitypolicyviolation`,
  `test_all_modules_load_without_errors` — kontrola składni modułów ES
  przez załadowanie w Playwright, bez Node.js). **Zależności:** 6b, 8, 9a.
  **Równolegle:** 9b, 9c i 12.

### 10b. Mapa
- **Cel:** `src/views/map.js` i `src/map/`: start od mapy; narzędzia
  obszaru: prostokąt, wielokąt, „Widok mapy”, godło (wpisane albo kliknięte
  w siatce `/map/sheets`), plik geometrii (`POST /areas`); wybór produktu
  z *indeksu*; panel stanu lokalnego (`/local-coverage`: „lokalnie 83%
  obszaru”, przyczyna braku procentu, `stale`); obrysy z
  `/map/footprints`, agregacja do siatki powyżej 5000; licznik „bez
  obrysu” prowadzący do Katalogu z tym samym produktem i filtrami;
  podkłady z ustawień tylko online, tryb offline bez żadnych zapytań
  zewnętrznych, motyw neutralny. Bez Wachlarza przed v0.2.
- **Test/odbiór:** `tests/e2e/test_map.py` (narzędzia obszaru,
  `test_local_coverage_after_refresh`,
  `test_more_than_5000_footprints_aggregate_to_grid`,
  `test_no_outline_counter_opens_catalog`,
  `test_online_basemap_from_local_tile_server_without_csp_violations` —
  podkład wskazujący lokalny serwer kafli na innym porcie,
  `test_offline_makes_no_external_requests`, klawiatura/ARIA, 1440
  i 390 px). **Zależności:** 9c, 10a. **Równolegle:** 10c, 11 i 12.

### 10c. Katalog
- **Cel:** `src/views/catalog.js`: lista filtrowana i stronicowana
  (`/slots`), grupy położenia z licznikami i grupa „bez obrysu”, filtr
  `unit` (dokładny kod TERYT/KU, decyzja 9), pole `Ctrl+K`, stan
  w adresie URL; ścisłe rozdzielenie danych bez położenia od mapy.
- **Test/odbiór:** `tests/e2e/test_catalog.py`
  (`test_filters_paging_and_url_state`, `test_unit_filter_exact_code`,
  `test_no_outline_in_catalog_not_on_map`, `test_ctrl_k_search`,
  `test_second_adapter_entries_in_catalog`). **Zależności:** 9a, 10a.
  **Równolegle:** 10b, 11 i 12.

### 11. Karta pliku, Projekty i Magazyn
- **Cel:** `src/views/{file,projects,store}.js` na routerze 10a. Karta:
  oś wszystkich wersji, `current` kontra `full_sheet`, rok/etykieta/
  kampania, `parent_request`, licencja z kopiowaniem atrybucji, surowy
  sidecar i ścieżka konkretnej wersji, przypięcia (także starszych
  wersji), „Potwierdź bieżącą wersję” (`POST /stores/{store}/link-check`,
  wynik z SSE). Projekty: zadania, istniejące polecenia, status
  i brakujące przypięcia, bez przycisków uruchamiających/zmieniających
  projekt. Magazyn: zajętość per produkt z każdą wersją raz, problemy
  z instrukcją, raport „niebieżące i nieprzypięte”, stan źródła i indeksu,
  wiersz ostatniego skanu z wykonawcą (`actor`), „Odśwież”
  (`POST /stores/{store}/scan`) z obsługą `409`, „Uzupełnij obrysy
  jednostek” (`footprints`, nieaktywne offline z wyjaśnieniem). Stały
  baner odłączonego udziału z czasem ostatniego skanu.
- **Interfejs:** tylko modele z 9a/9b; odczyt przez identyfikator, nie URL
  fizycznego pliku; własne moduły i własny plik słownika. „Projekty”
  i „Przypięta w:” pokazują to, co zwraca API przefiltrowane przez 8b (bez
  własnego filtrowania); raport magazynu podaje nazwy tylko widocznych
  projektów. Bez ekranu udostępniania przed v0.4 — widoczność ustawia się
  w v0.1 przez API i CLI (krok 8b).
- **Test/odbiór:** `tests/e2e/test_file_projects_store.py`
  (`test_human_labels_expose_raw_values`, `test_pinned_old_version_visible`,
  `test_copy_attribution_and_path`, `test_manifest_error_visible`,
  `test_two_links_counted_once`, `test_disconnected_store_banner`,
  `test_link_check_result_on_file_card`, `test_store_scan_row_shows_actor`).
  **Zależności:** 7, 9b, 10a. **Równolegle:** 10b, 10c i 12.

### 12. CLI i przewodnik dla agentów: działania tylko odczytowe
- **Cel:** w `archiwista/cli.py`: `archiwista status --json` — dokładnie
  model `GET /health` (z `IndexStatus`); `archiwista search [QUERY] --json`
  z opcją dla **każdego** parametru `/slots` o tej samej nazwie (`--store`,
  `--product`, `--country`, `--years OD:DO`, `--unit KOD`, `--location
  any|with|none`, `--versions`, `--status`, `--area-id`, `--bbox`
  z `--bbox-crs`, `--limit`, `--cursor`), generowaną z tego samego modelu
  zapytania co trasa; `archiwista entry STORE SLOT --json` — model karty
  slotu; `archiwista token [--json]` — jednorazowy token (5 min, skrót
  w lokalnym indeksie) z adresem `http://127.0.0.1:<port>/#token=…`, żeby
  agent nie potrzebował kliknięcia w przeglądarce. Na stdout wyłącznie
  JSON o schemacie odpowiedniego API, diagnostyka na stderr, niezerowy kod
  wyjścia i `code` przy błędzie. Bez CLI pobierającej dane. Przewodnik
  (powstaje w kroku 14): sesja agenta przez `curl` z cookie-jar (`POST
  /api/v1/session`, potem `X-Archiwista-CSRF` przy `POST`; bez `Origin`),
  filtry, kursory, SSE, flaga offline, nie zapisywać sekretów w promptach
  i dziennikach; agent używa zwykłego `/api/v1`, nie narzędzi czatu ani
  MCP.
- **Interfejs:** CLI wywołuje te same usługi `IndexQueries` i modele 9a;
  nie parsuje sidecarów i nie omija sprawdzenia stanu indeksu. Do usług
  przekazuje `Principal` trybu lokalnego (`LOCAL_OWNER`: role `admin`
  i `store_writer`), jak `current_principal` w HTTP, więc wyniki `search`
  i `entry` przechodzą przez ten sam filtr widoczności co trasy (8b,
  A-ADR-029); polecenia `users`, `groups`, `share` i `state` należą do 8b.
- **Test/odbiór:** `tests/integration/test_cli.py`
  (`test_search_options_match_slots_parameters` — zbiór opcji = zbiór
  parametrów z OpenAPI, `test_search_cli_equals_http` dla kilku kombinacji
  filtrów i kursora, `test_status_json_equals_health`,
  `test_entry_json_equals_slot_card`, `test_token_is_one_time_and_expires`)
  i `tests/integration/test_agent_flow.py::test_agent_session_paging_and_errors`
  (klient HTTP bez `Origin`: token z `archiwista token`, sesja,
  stronicowanie, `POST` skanu z CSRF → `202`, `source_unavailable` bez
  wtyczki). **Zależności:** 8, 8b, 9a. **Równolegle:** 9b–11.

### 13. E2E, awarie udziału i pomiary
- **Cel:** `tests/e2e/test_acceptance.py` (Playwright na **rzeczywistym
  serwerze** i magazynie syntetycznym offline: kreator, wyszukiwanie,
  mapa → karta, projekty, magazyn, read-only, bezpośrednie żądania API,
  odłączenie i powrót udziału), `tests/perf/test_store_50k.py` (pełny
  i przyrostowy skan, `refresh_view` ≤ 500 slotów, strona 50 wierszy,
  mapa ≤ 5000 obrysów, wyszukiwanie, karta; po 30+ próbach p95; RSS
  serwera, rozmiar indeksu, liczba otwarć sidecarów na skan wobec tabeli
  kosztów, czasy per segment, czas generatora 4),
  `tests/integration/test_live_store.py` (`-m live`). Osobny świadomy
  przebieg na prawdziwym SMB 3 (`-m smb`), nie udawać go katalogiem
  lokalnym. Smoke `archiwista serve` ze źródłem na montowaniu read-only.
- **Interfejs:** `tests/perf` korzysta z generatora 4 i API 9a; testy
  awarii z usług 6b i UI 10–11; w testach offline nic nie jest pobierane.
- **Test/odbiór:** `.venv/bin/python -m pytest tests/e2e -m 'not live'`;
  `.venv/bin/python -m pytest tests/perf -m perf --store
  '<katalog-danych>/store-50k'`; dla prawdziwego montowania analogicznie
  `-m smb`; zapis liczb i warunków. Spełnić wszystkie progi SPEC 4.5 (SSD
  i osobno SMB) oraz ≤ 500 MB indeksu i RSS; bez udziału SMB jego próg
  pozostaje niezaliczony. **Zależności:** 4, 6b, 9a–9c, 10a–10c, 11, 12
  (perf od 6b i 9a). **Równolegle:** testy perf z 10–12.

### 14. Dokumentacja, bramka i wydanie
- **Cel:** `README.md`, `CHANGELOG.md`, `docs/API_dla_agentow.md` (nowy
  dokument tworzony dopiero przy wdrożeniu), dokumentacja instalacji,
  konfiguracji, CLI, API, sesji agenta, trybu offline, ograniczeń v0.1
  i metodologii pomiarów; wskazać v0.1 wobec v0.2/v0.3 i repozytorium
  Kartografa jako producenta. Wyniki i zrzuty przejścia odbiorczego
  w raporcie wydania, bez ścieżek prywatnych — wyłącznie
  `<katalog-danych>`. Po każdej zmianie umowy HTTP poprawić przykłady
  OpenAPI i CLI.
- **Interfejs:** dokumentacja wyników kroków 9a–9c, 12 i 13; nie opisywać
  niezaimplementowanych przycisków ani „stabilnego API v1.0” przed v1.0.
- **Test/odbiór:** bramka w `.venv`: `pytest -m 'not live and not perf
  and not smb' --cov=archiwista --cov-fail-under=80`, `ruff check .`,
  `ruff format --check .`, `mypy archiwista/ tests/`, testy Playwright
  offline i `archiwista serve` z przejściem scenariuszy w przeglądarce.
  Wydanie tylko po odnotowaniu wyników *każdego* kryterium poniżej.
  **Zależności:** 0–13, Kartograf 0.8.0 z publicznym KA-1..KA-6.
  **Równolegle:** teksty API po 9a–9c i 12, raport końcowy po 13.

## Bramka SPEC 13 v0.1: dowód dla każdego kryterium

| Kryterium SPEC 13 | Dowód wymagany przed zamknięciem v0.1 (krok-właściciel) |
|---|---|
| 1. Zgodność ze sklepem testu na żywo Kartografa 0.8.0 (`<katalog-danych>`) | `tests/contract/test_kartograf.py` (2) i `tests/integration/test_live_store.py::test_index_matches_iter_store_on_live_store` (13, `-m live` na *tym* magazynie): zbiór `(segment, path, kind, version_path, problem)` z indeksu = z `iter_store`, także klucze deweloperskie; bez zapisu w źródle. |
| 2. Cele wydajności SPEC 4.5 | `tests/perf/test_store_50k.py` (13; `-m perf`, osobno `-m smb`): SSD ≤ 120/20/1 s, SMB ≤ 600/180/5 s dla pełnego/przyrostowego/widoku; p95 lista/wyszukiwanie/karta ≤ 200 ms, obrysy ≤ 300 ms; indeks i RSS ≤ 500 MB; liczby z metodologią w raporcie. |
| 3. Magazyn tylko do odczytu | `tests/integration/test_read_only_store.py::test_read_only_store_scan_and_browse` (9a) i smoke `archiwista serve` na montowaniu read-only (13): Mapa, Katalog, Karta, Projekty, Magazyn; źródło bez nowych plików. |
| 4. Odłączony udział i ponowne podłączenie | `tests/integration/test_disconnected_store.py::test_disconnect_preserves_index_then_incremental_refresh` (6b) i `tests/e2e/test_file_projects_store.py::test_disconnected_store_banner` (11): baner z czasem, zachowany wynik, nowa wersja po powrocie bez przebudowy. |
| 5. Host/token/CSRF/ścieżki i odmowa bind | `tests/unit/test_security.py` i `tests/integration/test_serve.py::test_serve_refuses_non_loopback_host` (8): bez sesji 401, obcy `Host`/`Origin`, brak CSRF, symlink/traversal odrzucone, token poza dziennikami. |
| 6. Wartość techniczna ↔ nazwa dla człowieka | `tests/e2e/test_file_projects_store.py::test_human_labels_expose_raw_values` (11): nazwa z `describe_segment`, czytelny rok danych, licencja/atrybucja, odsłonięte segment/EPSG/`sha256`/ścieżka; nieznany produkt pokazany jako nieznany. |
| 7. Wyłącznie interfejs źródła poza adapterem | `tests/contract/test_imports.py` (2), `tests/integration/test_second_adapter.py::test_second_adapter_indexes_and_browses_without_core_changes` (9a) i `tests/e2e/test_catalog.py::test_second_adapter_entries_in_catalog` (10c): drugi adapter przechodzi przez indeks, API i UI bez importu Kartografa poza adapterem. |
| 8. Entry points, stany źródeł, zgodność wersji/schematów | `tests/contract/test_plugins.py` (2), `tests/integration/test_api.py::test_source_states_map_to_503` (9a) i `tests/unit/test_doctor.py` (3): wtyczka widoczna w `/sources` i „Magazynie”; brak producenta → `503 source_unavailable`, zła wersja/schemat → `503 source_incompatible`, błąd ładowania nie kładzie serwera; `doctor` z polskim opisem naprawy. |
| 9. Uprawnienia (A-ADR-029) | `tests/unit/test_authorize.py::test_visibility_matrix`, `tests/integration/test_permissions_api.py`, `tests/integration/test_state.py` i `tests/integration/test_cli.py::test_admin_cli_json_equals_http` (8b): macierz `public`/`users`/`group`/`private` × właściciel / osoba lub członek grupy z wpisu / inna osoba / administrator zgodna w usługach, API i CLI; niewidoczny projekt → `404`, działanie bez uprawnienia → `403 permission_denied`; trasy administratora bez `admin` odrzucone; tryb lokalny widzi wszystko; przebudowa indeksu nie zmienia bazy stanu, eksport → import ją odtwarza. |

## Ryzyka i blokady

- **KA w toku.** KA-1..KA-6 z `list_segments` i `skip_versions` są
  wdrażane w Kartografie na `feat/archiwista-store-api` (scalenie do
  `develop` po zgodzie użytkownika). Kroki 2, 4–7 i 9a–13 wymagają tej
  gałęzi zainstalowanej edytowalnie albo scalenia; starsza kopia 0.8.0 nie
  dowodzi obecności KA. Wydanie v0.1 wymaga otagowanego Kartografa 0.8.0
  z publicznym KA i zielonego testu kontraktu; do tego czasu nie symulować
  funkcji prywatnymi importami ani kopią parsera.
- **Magazyn testowy bez publicznego zapisu.** Generator zapisuje wersje,
  sidecary i dowiązania sam (krok 4); rozjazd z formatem wychwytuje od
  razu czytnik Kartografa. Gdyby utrzymanie generatora okazało się
  kosztowne, zgłosić Kartografowi wymaganie publicznego zapisu wersji
  testowej (SPEC 12), zamiast powielać więcej reguł `data/`.
- **SMB.** Metadane i czasy katalogów bywają niespójne: bieżącą wersję
  wyznacza sidecar dowiązania, KA-5 potwierdza ją na żądanie, a kontrolny
  pełny skan znajduje pominięte zmiany. Opóźnienie operacji katalogowych
  ogranicza pula po segmentach; jeśli pomiar 13 nie spełni progu, najpierw
  zmierzyć udział listingu, odczytów sidecarów i zapisu, potem stroić
  `scan_threads` — bez obniżania progów i ukrywania nieudanych pomiarów.
- **CZ i transformacje.** Operacje CZ wyłącznie przez KA-6, nigdy domyślny,
  przybliżony transformator.
- **Filtr widoczności pominięty.** Nowa trasa albo zapytanie o projekty
  bez `visible_projects` ujawnia projekty prywatne; dlatego filtr siedzi
  w usługach i `IndexQueries` (nie w routerach), a macierz widoczności
  z 8b obejmuje każdą trasę zwracającą projekty lub przypięcia.
- **Podkłady online.** `Referrer-Policy: no-referrer` może nie spełniać
  zasad dostawcy kafli wymagającego `Referer` (np. serwery OSM); sprawdzić
  świadomie (`-m live`) w 10b i w razie potrzeby wybrać dostawcę szarego
  podkładu zgodnego z tą polityką, zamiast luzować politykę `Referer`.
- **Frontend bez typów.** Ryzyko łagodzą JSDoc, Playwright i kontrakt
  OpenAPI; dołączone biblioteki zweryfikować pod CSP, offline i licencją
  zgodną z MIT.
- **Środowiska.** Udział SMB i żywy magazyn 0.8.0 wymagają osobnego,
  jawnego `<katalog-danych>`; brak tych środowisk oznacza niezamknięte
  kryterium, a nie automatyczny sukces.
