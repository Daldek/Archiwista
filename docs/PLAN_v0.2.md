# Plan implementacji v0.2 „Podglądy”

**Status:** projekt do przeglądu (2026-10-19). Kod v0.2 powstaje dopiero po
przeglądzie i zatwierdzeniu tego planu (kolejność jak przy v0.1: spec → plan
→ przegląd planu → implementacja; `CLAUDE.md`). Wzór i umowy v0.1:
`docs/PLAN_v0.1.md`; stan kodu 0.1.0: `docs/ARCHITECTURE.md`; pomiary
wyjściowe: `docs/reports/v0.1-measurements.md`. Jak w v0.1, po każdym
kroku dopisuje się tu „Stan po kroku N” (commit, odstępstwa od umowy,
wyniki prób) i aktualizuje kolumnę „Stan” w tabeli kolejności prac.
**Zakres (SPEC 13 v0.2):** podglądy (SPEC 5.7) z pamięcią po `sha256`;
„Wachlarz” i „Oś czasu” dla danych lokalnych (lata i kampanie w magazynie);
porównanie metadanych i kurtyna (SPEC 8.5, poziomy 1 i 2); dane własne
projektu i migawki (SPEC 4.7.1, A-ADR-027). Magazyn producentów zostaje
tylko do odczytu. Archiwista zapisuje lokalnie indeks, pamięć podglądów
i dzienniki, a poza swoim katalogiem danych — wyłącznie migawki
w `<folder danych>/.wersje/`, na polecenie osoby z prawem `project.write`.
Obowiązują kolejno `PRD.md` (F5, F15, F16, N2, N3, N8.3) i `SCOPE.md`
(etap 3) w kwestiach zakresu, `SPEC.md` (zwłaszcza 4.3–4.7.1, 5.4–5.7, 6,
8.5, 9–11, 13 v0.2 i 14), `DEVELOPMENT_STANDARDS.md` oraz A-ADR-007, 008,
010, 016, 017, 018, 022, 027, 028 i 029 (z erratami). Mockup (`mockup/`;
zrzuty `05a`–`05c`, `08`, `17`, `21`–`25`, `27`–`35`) jest punktem wyjścia
układu Wachlarza, Osi czasu, panelu „Szczegóły zestawu” i danych własnych,
a **nie** źródłem danych ani logiki; pokazana w nim różnica obiektów między
migawkami (zielone „dodane”, czerwone „usunięte”, zrzuty `31`–`34`) jest
poza v0.2 (SCOPE: „później, osobną decyzją”). Każdy krok kończy się podaną
próbą odbioru; nie wdrażać kolejnego zależnego kroku, dopóki poprzedni nie
działa.

## Decyzje wykonawcze i granice

1. **Komputer odniesienia i GPU (SPEC 4.5, 13 v0.2).** Ten sam co w v0.1
   (decyzja 1 planu v0.1: i5-6400, 4 CPU, 15,6 GiB RAM, SSD `/dev/sdb`
   z ext4; udział SMB 3 `//magazyn.local/agent-tmp`). Karta graficzna:
   NVIDIA GeForce GTX 1060 6 GB (`lspci`: GP106), sterownik jądra `nouveau`,
   Mesa z `nouveau_dri.so`; węzły `/dev/dri/card0` (`root:video`)
   i `/dev/dri/renderD128` (`root:render`, `0660`). Konto, z którego biegły
   pomiary v0.1, nie należy do grup `video` ani `render`, więc Chromium
   rysował WebGL programowo (SwiftShader: 8–9 klatek/s z 4532 obrysami,
   19,8 bez obrysów) — to brak dostępu do GPU, nie cecha komputera.
   Kryterium „≥ 30 klatek/s” mierzy się wyłącznie przy WebGL sprzętowym
   (renderer WebGL inny niż SwiftShader, llvmpipe, softpipe), jedną z dróg:
   - **(a)** konto pomiarowe w grupie `render` (decyzja właściciela
     komputera: `sudo usermod -aG render <konto>` i ponowne zalogowanie)
     i Chromium z Playwright z flagami GPU (`--ignore-gpu-blocklist` —
     `nouveau` jest na liście blokad Chromium — i ANGLE na EGL);
   - **(b)** Chrome właściciela uruchomiony w jego sesji graficznej
     z `--remote-debugging-port` i podłączony do testu przez CDP
     (`ARCHIWISTA_BROWSER_CDP=http://127.0.0.1:<port>`).

   Bez żadnej z tych dróg kryterium 5 bramki pozostaje *niezweryfikowane* —
   nie zastępuje go pomiar programowy ani obniżenie progu. Sterownik firmowy
   NVIDIA jest opcją właściciela, nie wymaganiem planu.
2. **Producenci: bez nowych wymagań (SCOPE: „v0.2 | —”).** v0.2 używa
   publicznego API Kartografa 0.8.0 z planu v0.1 oraz metody
   `PinnedTransform.gdal_operation()` (publiczna klasa z `kartograf.__all__`;
   ta sama przypięta operacja jako pipeline PROJ dla GDAL-owego
   `COORDINATE_OPERATION`, z korektą kolejności osi — Kartograf ARCH 1,
   ADR-024). Adapter wystawia ją w umowie źródła (krok 3), a test kontraktu
   `tests/contract/test_kartograf.py` ją sprawdza. Stan Kartografa
   2026-10-19: gałąź `feat/archiwista-store-api` jest scalona do `develop`
   Kartografa (scalenie `b71cc370`), a jej ref usunięty; tagu `v0.8.0`
   nadal brak. Instalacja edytowalna zostaje, ale z `develop` Kartografa —
   instrukcję w README, która wskazuje usuniętą gałąź, poprawia krok 18.
   Georeferencję JPEG z plikiem świata Archiwista
   bierze z obrysu nagłówkowego KA-4 (decyzja 5), więc nie łączy plików
   `.jgw` z wersjami sama (to reguła układu `data/`, A-ADR-014). Obrót
   w pliku świata (układ niepółnocny) jest znanym ograniczeniem: gdyby
   wystąpił w danych, wymaganie dokładnej georeferencji rastra
   (`raster_georeference(entry)`) trafi do SPEC 12 jako propozycja po v0.2,
   nie jako obejście.
3. **Podglądy: procesy renderujące, pamięć po treści, dostarczanie przez
   API.**
   - *Gdzie liczone.* Serwer nie otwiera plików danych bibliotekami GDAL,
     OGR, laspy ani `zipfile`. Miniatury, kafle, obiekty wektorowe i listy
     członów ZIP liczy pula długowiecznych procesów renderujących
     (`python -P -m archiwista.previews.worker`, domyślnie `min(4, cpu)`),
     zabijanych i uruchamianych od nowa po przekroczeniu czasu (kafel 15 s,
     obiekty 15 s, miniatura 30 s, miniatura warstwy 60 s) albo limitu
     pamięci (`RLIMIT_AS` 2 GiB, `GDAL_CACHEMAX` 256 MB; na Linuksie —
     Windows w v1.0). Kolejka żądań ma ≤ 64 miejsca (potem
     `503 preview_busy` z `Retry-After`), identyczne żądania liczą się raz
     (jedno renderowanie na klucz), a żądanie porzucone przez przeglądarkę
     (przesunięta mapa) wypada z kolejki przed renderowaniem. Budowa
     lokalnego COG (decyzja 6) to zadanie w tle `preview` (A-ADR-007), każdy
     plik w osobnym procesie potomnym z limitem 10 min i 4 GiB. Ten sam
     moduł `archiwista/sandbox.py` daje środowisko wszystkim procesom
     czytającym pliki (także czytnikowi obszarów v0.1 — jedna
     implementacja zamiast kodu w `areas.py`): minimalne zmienne bez
     pośredników i poświadczeń, `PROJ_NETWORK=OFF`, `GDAL_HTTP_PROXY` na
     zamknięty port, `GDAL_DISABLE_READDIR_ON_OPEN=TRUE` (pliki obok
     sprawdzane po nazwie, jak w Kartografie), `umask 077` i `GDAL_SKIP`
     sterowników odsyłających do innych plików albo sieci (m.in. VRT, WMS,
     WMTS, WCS, WFS, OAPIF) — plik użytkownika nie wskaże innego pliku
     serwera ani adresu.
   - *Pamięć podglądów.* `<katalog danych>/previews/` (prawa `0700`, nigdy
     na udziale ani w magazynie): obiekty po treści
     (`objects/<sha256[:2]>/<sha256>/r<wersja renderera>/`: `info.json`,
     `cog.tif`, miniatury, kafle) i rozliczenie LRU
     w `previews/cache.sqlite` (pamięć podręczna: usunięcie katalogu daje
     pustą pamięć). Limit z ustawienia `preview_cache_limit_gb` (domyślnie
     20, SPEC 5.7); po zapisie ponad limit znikają najdawniej używane
     obiekty do 90% limitu, z wyjątkiem obiektów w budowie i w trakcie
     odczytu. Klucz: treść (`sha256` wersji magazynu; dla danych własnych —
     tożsamość treści z decyzji 8), wersja renderera, styl i parametry
     (rozmiar, kadr, `rescale`). Wersje magazynu są niezmienne, a każda
     zmiana kodu renderera podnosi jego wersję, więc pamięć nigdy nie jest
     nieaktualna; te same bajty w dwóch wersjach, dwóch magazynach albo
     w migawce i pliku roboczym liczą się raz.
   - *Uprawnienia przed pamięcią.* Każde żądanie najpierw rozstrzyga obiekt
     (`ref`, decyzja 10) i dostęp do niego: magazyn centralny widzą
     wszyscy, dane własne i migawki — wyłącznie przez projekt widoczny dla
     principala (`visible_projects`; niewidoczny → `404 not_found`). Dopiero
     potem sięga do pamięci. Pamięć współdzieli bajty równych treści
     między projektami, ale nic nie ujawnia: aby trafić w obiekt, trzeba
     już wskazać widoczny plik o tej samej treści. Obiekty pamięci nie
     niosą nazw ani ścieżek, a `/health` podaje tylko liczby. Tak plan
     realizuje „klucze pamięci podglądów danych własnych zależne od
     widoczności” (plan v0.1, krok 8b) i A-ADR-029 pkt 3.
   - *Dostarczanie.* Obrazy i kafle idą przez `/api/v1/…` z tego samego
     pochodzenia, z sesją i nagłówkiem `X-Archiwista-CSRF` jak każde
     żądanie API (SPEC 10.1): MapLibre dodaje nagłówek w `transformRequest`
     (kafle rastrowe pobiera przez `fetch`, więc wystarcza `connect-src
     'self'`), a `<img>` i SVG Wachlarza dostają adres `blob:` z odpowiedzi
     `fetch` (`img-src blob:` już jest). CSP się nie zmienia; żadnych
     podpisanych adresów ani tokenów w URL. Nagłówki: wersje magazynu —
     `Cache-Control: private, max-age=86400, immutable` (treść adresowana
     sumą, magazyn widzą wszyscy); dane własne i migawki — `Cache-Control:
     private, no-cache` z `ETag`, więc każde ponowne użycie w przeglądarce
     przechodzi przez sprawdzenie widoczności (`304` po sprawdzeniu).
4. **Przeliczenia tylko do wyświetlenia i tylko operacją przypiętą
   (KA-6).**
   - *Obrysy jako wielokąty.* W 0.1.0 obrys WGS84 jest obwiednią
     (`_polygon(found.wgs84)` w adapterze Kartografa). Prostokąt arkusza
     w PL-1992 albo S-JTSK jest w WGS84 obróconym czworokątem (zbieżność
     południków), więc narożnik obwiedni leży daleko od narożnika arkusza
     — pomiar przy planowaniu (2026-10-19, `pinned_transform` do
     EPSG:4326): arkusz SM5 2,5 × 2 km przy Czeskim Cieszynie do 204 m,
     arkusz 5 × 5 km PL-1992 na zachodzie Polski do 302 m, w środku kraju
     5 m. Na skrajach to więcej niż błąd operacji przybliżonej, przed
     którym chroni KA-6 (SPEC 14: ok. 100 m). Od v0.2 indeks trzyma obrys
     WGS84 jako wielokąt: natywny prostokąt `Footprint.native`
     z krawędziami zagęszczonymi co ≤ 5 km, przeliczony
     `GeoAdapter.transformer(native_crs, "EPSG:4326")` (obrys natywny
     w EPSG:4326 — bez przeliczenia). R*Tree dalej trzyma obwiednię (filtr
     obszaru i mapy), a pokrycie lokalne (v0.1) dalej liczy z obrysu
     natywnego. Producent bez `GeoAdapter` zostaje przy swoim `wgs84`.
   - *Kafle.* rio-tiler czyta przez `WarpedVRT`, który zamienia wartości
     opcji na wielkie litery (rasterio 1.5.2, `_warp.pyx`:
     `val = str(val).upper()` dla `warp_extras`), więc nie przeniesie
     pipeline'u PROJ w `COORDINATE_OPERATION`; `rasterio.warp.reproject`
     zachowuje wielkość liter tej opcji (wyjątek dla `RPC_DEM`
     i `COORDINATE_OPERATION`). Kafel EPSG:3857 powstaje więc przez
     `reproject` z najbliższej nakładki przeglądowej (`OVERVIEW_LEVEL`) na
     siatkę kafla (morecantile) z wymuszoną operacją
     `transformer(układ pliku, "EPSG:3857").gdal_operation()`, a rio-tiler
     (A-ADR-008) służy do statystyk, miniatur w układzie pliku, kolorowania
     i kodowania PNG (`ImageData`). Próba techniczna kroku 1 potwierdza obie
     obserwacje na punkcie kontrolnym, zanim powstanie renderer. Wyjątek:
     plik w układzie na elipsoidzie WGS84 bez zmiany układu odniesienia
     (EPSG:4326, EPSG:3857 — SoilGrids, HSG) przelicza się zwykłą
     konwersją GDAL-a, bo polityka Kartografa odrzuca konwersję bez
     deklarowanej dokładności (sprawdzone 2026-10-19:
     `pinned_transform("EPSG:4326", "EPSG:3857")` →
     `TransformUnavailableError`), a tu nie ma czego przypinać; dla 2180,
     2177, 3045 i 5514 → 3857 operacja przypięta istnieje (dokładność 1 m).
   - *Wektory.* Obiekty w widoku (`features`) przelicza do WGS84 przypięty
     transformator (pyproj, jak obszary v0.1); prostokąt widoku do układu
     pliku — ta sama operacja odwrotnie, po zagęszczeniu krawędzi.
   - *Miniatury warstw* (Wachlarz) proces renderujący składa w układzie
     płaskim obszaru (PL → EPSG:2180, CZ → EPSG:5514, jak pokrycie lokalne)
     z wymuszoną operacją.
   - *Punkt kontrolny na styku PL/CZ* (kryterium 2): punkt trygonometryczny
     3722, k.ú. Mosty u Českého Těšína (ČÚZK, usługa `BodovaPole`,
     warstwa 2 „Bod ZPBP určený v ETRS89”): S-JTSK Y = 449 334,63 m,
     X = 1 111 919,25 m (EPSG:5514: x = −449 334,63, y = −1 111 919,25),
     ETRS89 φ = 49,7587324167°, λ = 18,58895625° (GNSS, metoda statyczna).
     Wartości z nagrania 2026-10-16 w fixturach Kartografa
     (`tests/fixtures/cz/survey_control/real_2026_10_16/layer_2_tesin_r1000_o0.json`)
     przepisuje się do fixtury Archiwisty razem ze źródłem (adres usługi,
     numer obiektu, data nagrania). Odchyłkę liczy `pyproj.Geod`; WGS84
     traktujemy jak ETRS89 (różnica ok. 0,9 m w 2026 r. mieści się w 2 m
     i jest podana w raporcie). Wartości odniesienia nie wolno liczyć
     sprawdzaną transformacją. Sprawdzenie przy planowaniu (2026-10-19):
     `pinned_transform("EPSG:5514", "EPSG:4326")` stawia punkt 0,67 m od
     współrzędnych ETRS89 ČÚZK — zapas wobec progu 2 m jest, więc ryzyko
     leży w drodze danych (obwiednie, kafle bez wymuszonej operacji), nie
     w samej operacji.
5. **Każdy typ pliku: podgląd albo powód (kryterium 1).** Rodzaj podglądu
   wynika z rozszerzenia i z próby otwarcia w procesie renderującym, styl
   domyślny — z produktu (`SourceSegment.product`, `EntryMeta.dataset_key`);
   to prezentacja, nie reguła danych. Powód braku jest zawsze maszynowym
   kodem z polskim opisem i zaleceniem w `messages.py`, nigdy pustym
   miejscem. Typy plików magazynów testu na żywo Kartografa 0.8.0 (`tif`,
   `gpkg`, `jgw`, `asc`, `zip`, `png`, `laz`, `jpg`) i magazynu
   syntetycznego:

   | Rodzina (przykład) | Podgląd | Na mapie | Uwagi albo kod powodu |
   |---|---|---|---|
   | ASC (NMT, NMPT 1 m; PL-1992, PL-2000, KRON86) | miniatura; cieniowanie (domyślnie) albo hipsometria z legendą | kafle z lokalnego COG | układ z `EntryMeta.horizontal_crs` (ASC go nie niesie) |
   | XYZ (siatka tekstowa) | jak ASC (sterownik GDAL XYZ) | kafle z lokalnego COG | siatka nieregularna → `unsupported_format` |
   | GeoTIFF kafelkowany z nakładkami (ortofotomapa PL, ukośne `orto/pl_2000_oblique`) | RGB albo skala szarości, rozciągnięcie 2–98% | kafle wprost | `nodata` i kanał alfa przezroczyste |
   | GeoTIFF paskowy albo bez nakładek, bok > 4096 px (mapy BDOT10k TIFF, RGBA) | jak wyżej | kafle z lokalnego COG | — |
   | GeoTIFF wartości ciągłych (NMT `bbox/`, DMR CZ, SoilGrids) | cieniowanie albo hipsometria; legenda z zakresem | kafle wprost albo z COG | — |
   | GeoTIFF klas (CORINE, HSG) | paleta z pliku albo tablica klas (CLC, HSG A–D) z legendą | kafle wprost (`nearest`) | — |
   | JPEG + JGW (ortofoto CZ SM5) | RGB | kafle z lokalnego COG; georeferencja z obrysu nagłówkowego KA-4 (`location_source = header`: natywny prostokąt i układ) | obrys z innego źródła → miniatura bez mapy, `no_georeference` |
   | JGW (plik świata jako osobny slot) | — | — | `auxiliary_file`: podgląd przy obrazie |
   | PNG/JPEG bez georeferencji (podgląd WMS `landcover/eu_corine_2018_preview`) | miniatura obrazu | — | `no_georeference` |
   | GeoPackage (BDOT10k, PRG, EGiB, PRNG, HYNET, osnowa) | warstwy z typem geometrii, liczba obiektów, schemat, próbka 20 wierszy, miniatura do 3 największych warstw (≤ 50 000 obiektów każda) | obiekty w widoku jako GeoJSON WGS84, ≤ 5000, powyżej „Przybliż albo otwórz w QGIS” | magazyn: otwarcie niezmienne (`immutable=1`, SPEC 4.6 pkt 4) |
   | Shapefile, GeoJSON, FlatGeobuf (dane własne) | jak GeoPackage | jak GeoPackage | brak układu (np. bez `.prj`) → miniatura w układzie pliku bez mapy, `no_crs` |
   | LAZ/LAS (chmury GUGiK) | nagłówek (zasięg, liczba punktów, format, gęstość), histogram klas ASPRS z próbki ≤ 2 mln punktów, obraz 2D (maks. Z w siatce) | kafle z lokalnego COG obrazu 2D | plik bez tablicy kawałków: próbka z początku pliku, z dopiskiem |
   | ZIP (BDOT10k SHP, modele 3D LOD2, EGiB, PRG kraju) | lista członów z rozmiarami i rozpoznanym formatem (≤ 10 000, bez rozpakowania) | — | `archive_members_only` (podgląd SHP i GML przez `/vsizip/` — później, SPEC 5.7) |
   | PDF, TXT | metadane (rozmiar, typ) | — | `document_no_preview`: PDF w przeglądarce wymaga dostarczania plików (`/file`, tryb zespołu v0.4); ścieżka do skopiowania |
   | inne, nierozpoznane | metadane | — | `unsupported_format` |

   Dla każdej rodziny: plik > 2 GB → stan `needs_build` („Zbuduj podgląd”,
   SPEC 5.7); wersja „brak pliku” → `missing_file`; magazyn odłączony →
   podgląd z pamięci, a bez niej `store_unavailable`; układ bez przypiętej
   operacji → `transform_unavailable` (miniatura bez mapy); błąd odczytu →
   `unreadable` (z komunikatem biblioteki); przekroczony czas → `timeout`;
   limit pamięci → `memory_limit`.
6. **Lokalny COG i duże pliki.** COG w pamięci podglądów powstaje dla ASC,
   XYZ, JPEG z georeferencją z obrysu, GeoTIFF paskowego albo bez nakładek
   z bokiem > 4096 px i dla obrazu 2D LAZ: najdłuższy bok ≤ 8192 px
   (A-ADR-018: podgląd lekki), uśrednianie dla wartości ciągłych,
   `nearest` dla klas, nakładki wewnętrzne, kompresja DEFLATE (wartości
   ciągłe z predyktorem) albo JPEG (RGB). Plik ≤ 2 GB interfejs zleca do
   budowy sam przy pierwszym podglądzie; większy czeka na „Zbuduj podgląd”
   (`POST …/preview` z `force: true`). Budowa jest idempotentna: zlecenie
   treści już budowanej dołącza do trwającego zadania (`202` z tym
   zadaniem), zbudowanej — odpowiada `200` z opisem podglądu. COG nigdy nie
   jest produktem danych: leży tylko w pamięci podglądów i nie ma ścieżki
   „do skopiowania”.
7. **Warstwy lat i kampanii z danych lokalnych (Wachlarz, Oś czasu,
   mapa).** Warstwa = segment (wariant Kartografa) × rok danych
   (`data_year`, nigdy rok pobrania); wersja bez roku trafia do warstwy
   swojego wydania albo etykiety. Parametr `group=campaign` dzieli rok na
   kampanie (`campaign`). Wariant w v0.2 to segment: łączenie formatów
   jednego zestawu (A-ADR-017) wymaga kombinacji z raportu dostępności
   i przychodzi w v0.3, a Archiwista nie rozbiera nazw segmentów. Warstwa
   niesie wersje slotów obszaru (≤ 500, po odświeżeniu widoku jak
   `/local-coverage`), stan lokalny („lokalnie 83% obszaru”, w układzie
   płaskim), obrysy w układzie płaskim obszaru (do SVG) i miniaturę
   złożoną z podglądów arkuszy (A-ADR-008 errata 2: kafel na wersję,
   pamięć po `sha256`; brakujące zostają obrysami, a ich budowa idzie
   jednym zadaniem `preview` na warstwę z postępem). Bez obszaru Oś czasu
   pokazuje liczby wersji per rok i wariant. Na mapie podgląd roku to kafle
   wersji tej warstwy (osobne źródło rastrowe na wersję, z `bounds`) — do
   200 wersji w widoku, powyżej same obrysy i „Przybliż, aby zobaczyć
   podgląd”. Etykiety pokrycia u źródła, plakietki „pobrane”, lata
   niepobrane z archiwalnego WMS GUGiK i powiaty z PRG (PRD, „Widoki według
   rodzaju danych”) przychodzą z dostępnością w v0.3.
8. **Dane własne: folder, odczyt, tożsamość treści, zmiany.**
   - *Folder.* Domyślnie `<katalog projektu>/dane/` (katalog projektu =
     katalog manifestu po `realpath`, ten sam klucz co `project_acl` bazy
     stanu); Archiwista go nie zakłada — brak folderu to stan „brak folderu
     danych” z podpowiedzią. Inny folder ustawia administrator
     (`settings.write`; `PUT /projects/{project}/data-dir`) — zapis w TOML
     (`AppSettings.own_data_dirs`: katalog projektu → folder), nie
     w manifeście producenta. Walidacja: ścieżka bezwzględna, istniejący
     i czytelny katalog, poza każdym katalogiem producenta magazynów
     (migawka nigdy nie trafi do magazynu), rozłączny z folderami innych
     projektów (plik należy do jednego projektu, więc do jednej widoczności)
     i z katalogami Archiwisty. Tylko administrator, bo folder jest miejscem
     zapisu migawek; ustawianie przez właściciela projektu — decyzja w v0.4.
   - *Odczyt bez zapisu.* Zadanie `own_scan` (wszystkie projekty;
     z harmonogramu co `scan_interval_local_min` i na żądanie z widoku
     projektu) przechodzi folder z pominięciem katalogów i plików
     ukrytych (w tym `.wersje/` jako dane) i dowiązań symbolicznych
     wychodzących poza
     folder, najwyżej 10 000 plików (więcej → problem
     `own_folder_too_large`). Plik nowy albo zmieniony (rozmiar, czas
     modyfikacji, także pliku `-wal`) czyta proces czytnika
     (`python -P -m archiwista.owndata.reader`, sandbox z decyzji 3, 30 s
     na plik, po przekroczeniu restart dla kolejnych): sterownik GDAL/OGR,
     warstwy z typem geometrii, liczba obiektów, schemat, układ, zasięg,
     parametry rastra. Shapefile i MapInfo TAB są kompletem plików o tym
     samym rdzeniu nazwy; inne pliki — „nierozpoznane”. Folder po każdym
     odczycie jest bajtowo taki sam (nazwy, rozmiary, czasy, żadnych nowych
     `-wal`/`-shm`): GeoPackage czyta SQLite w trybie `mode=ro`, a bez
     pliku `-wal` — `immutable=1`.
   - *Tożsamość treści* (`content`: metoda i `sha256`; duplikaty migawek
     i wykrywanie zmian): `bytes` — SHA-256 pliku; `fileset` — SHA-256
     posortowanych wierszy `<nazwa członu małymi literami>\t<sha256>`
     kompletu; `sqlite` (GeoPackage i inne bazy SQLite) — skrót logiczny
     niezależny od układu stron, WAL i liczników nagłówka: `application_id`,
     `user_version`, posortowane wpisy schematu (bez tabel wewnętrznych
     `sqlite_%`, wirtualnych i ich tabel cieni — R*Tree to indeks pochodny)
     oraz wiersze każdej tabeli z wartościami z typem (tabela z `INTEGER
     PRIMARY KEY` w porządku klucza, `WITHOUT ROWID` — klucza głównego,
     pozostałe jako posortowany multizbiór wierszy). VACUUM, punkt
     kontrolny WAL i zapis bez zmian nie zmieniają skrótu; zmiana wiersza,
     schematu albo `gpkg_contents` — zmienia.
   - *Zmiany.* Skan porównuje tożsamość treści pliku z ostatnią migawką:
     `unsnapshotted`, `unchanged` („bez zmian od migawki z RRRR.MM.DD”),
     `changed` („zmieniony od migawki z RRRR.MM.DD” i podpowiedź „Zrób
     migawkę”). Historia zaobserwowanych stanów (czas obserwacji, rozmiar,
     czas modyfikacji, skrót, liczba obiektów; bez treści) leży w indeksie,
     do 200 stanów na plik. Indeks jest pamięcią podręczną (A-ADR-002):
     przebudowa traci historię stanów, migawki zostają na dysku.
   - *Granice widoczności.* Dane własne nie wchodzą do `/slots` ani do
     `/map/footprints` (magazyn widzą wszyscy, dane własne — nie). Mają
     własne zasoby pod `/projects/{project}/…`, więc widoczność rozstrzyga
     jedno miejsce — rozwiązanie projektu. Na mapie pokazuje je kontekst
     projektu (`project=` w adresie mapy): warstwa „Dane własne” (zasięgi
     plików, obiekty albo kafle wybranego) razem z obrysami wersji
     przypiętych w projekcie (nowy filtr `project` w `/slots`
     i `/map/footprints`; projekt niewidoczny → `404`).
9. **Migawki: nazwy, `archiwista-snapshot/1`, procedura, uprawnienie.**
   - *Nazwy* (A-ADR-027: „nazwy katalogów i schematu — propozycja do planu
     v0.2”). Zostają polskie, jak `dane/`, `obszary/` i `zestawy/` w SPEC:
     to pliki dla ludzi w folderze projektu, nie identyfikatory kodu; tylko
     znaki ASCII. Układ: `<folder danych>/.wersje/<ścieżka pliku względem
     folderu>/<etykieta>/` z kopią pliku (komplet dla formatów
     wieloplikowych) i `migawka.json`, np.
     `dane/.wersje/sieci/kanalizacja.gpkg/2026-10-18_471d37c0/kanalizacja.gpkg`.
     Pełna nazwa z rozszerzeniem (mockup miał sam rdzeń `kanalizacja/`)
     rozdziela `kanalizacja.gpkg` i `kanalizacja.shp` z jednego katalogu.
     Etykieta `<RRRR-MM-DD>_<sha8>` (data
     lokalna utworzenia, `sha8` = pierwsze 8 znaków `content.sha256`), a gdy
     taki katalog już istnieje (ta sama treść tego samego dnia po zmianie
     A → B → A) — `<RRRR-MM-DD>_<sha8>_<n>`, n = 2, 3, …; kolejność serii
     wynika z `created_at`, nie z nazw. Katalog roboczy:
     `.wersje/.incoming/<host>_<pid>_<token>/` (ten sam system plików co
     cel, SPEC 4.7.1).
   - *Schemat `archiwista-snapshot/1`* (JSON w UTF-8, klucze po angielsku,
     daty ISO 8601 z przesunięciem, rozmiary w bajtach; model Pydantic
     `SnapshotDocument` z `extra="forbid"`; inny `schema` → problem
     `unknown_snapshot_schema`):

     | Pole | Typ | Znaczenie |
     |---|---|---|
     | `schema` | `"archiwista-snapshot/1"` | wersja formatu |
     | `label` | tekst | etykieta = nazwa katalogu migawki |
     | `created_at` | data i czas | chwila publikacji |
     | `author` | obiekt | `id` (konto albo `local`), `kind` (`local_owner`, `user`, `agent`), `name` (nazwa wyświetlana albo `null`), `session` (etykieta sesji albo `null`) |
     | `note` | tekst ≤ 2000 znaków | opis osoby |
     | `source` | obiekt | `path` (plik względem folderu danych, separator `/`), `format` (sterownik GDAL/OGR, np. `GPKG`, `ESRI Shapefile`, `GTiff`; `null` dla nierozpoznanego), `size_bytes` i `modified_at` pliku roboczego w chwili kopii |
     | `content` | obiekt | `method` (`sqlite`, `fileset`, `bytes`) i `sha256` — tożsamość treści (decyzja 8); z niej `sha8` etykiety |
     | `copy` | obiekt | `method`: `sqlite_backup` albo `files` |
     | `files` | lista | każdy plik migawki: `name`, `size_bytes`, `sha256` (bajty w katalogu migawki; integralność) |
     | `size_bytes` | liczba | suma `files` |
     | `layers` | lista albo `null` | wektor: `name`, `geometry_type`, `feature_count`, `crs`, `fields` (`name`, `type`) |
     | `raster` | obiekt albo `null` | `width`, `height`, `bands`, `dtype`, `crs`, `resolution` (`[x, y]`), `nodata` |
     | `feature_count` | liczba albo `null` | suma obiektów warstw |
     | `extent` | obiekt albo `null` | `crs`, `bbox` (`[min_x, min_y, max_x, max_y]` w układzie pliku), `wgs84` (`[min_lon, min_lat, max_lon, max_lat]` z przypiętej operacji) |
     | `archiwista` | tekst | wersja Archiwisty, która zrobiła migawkę |

     Przykład (skrócony):

     ```json
     {
       "schema": "archiwista-snapshot/1",
       "label": "2026-10-18_471d37c0",
       "created_at": "2026-10-18T14:02:11+02:00",
       "author": {"id": "local", "kind": "local_owner", "name": null, "session": null},
       "note": "nowy kolektor deszczowy",
       "source": {"path": "kanalizacja.gpkg", "format": "GPKG",
                  "size_bytes": 192512, "modified_at": "2026-10-16T09:41:00+02:00"},
       "content": {"method": "sqlite", "sha256": "471d37c0…"},
       "copy": {"method": "sqlite_backup"},
       "files": [{"name": "kanalizacja.gpkg", "size_bytes": 188416, "sha256": "9c1e…"}],
       "size_bytes": 188416,
       "layers": [{"name": "przewody", "geometry_type": "LineString", "feature_count": 61,
                   "crs": "EPSG:2180", "fields": [{"name": "srednica_mm", "type": "Integer"}]}],
       "raster": null,
       "feature_count": 61,
       "extent": {"crs": "EPSG:2180", "bbox": [566100.0, 241050.0, 569800.0, 246200.0],
                  "wgs84": [19.9201, 50.0402, 19.9719, 50.0866]},
       "archiwista": "0.2.0"
     }
     ```
   - *Procedura* (`make_snapshot` w procesie roboczym zadania `snapshot`):
     (1) plan `check_snapshot` (bliźniak bez zapisu, DEVELOPMENT_STANDARDS
     1.2): plik, prawo zapisu do folderu, wolne miejsce ≥ 1,1 × rozmiar,
     tożsamość treści z ostatniego skanu wobec ostatniej migawki;
     (2) spójna kopia — SQLite: `Connection.backup` z połączenia `mode=ro`
     (bez pliku `-wal`: `immutable=1` i porównanie stanu pliku przed i po)
     do pliku roboczego w lokalnym katalogu danych Archiwisty (SQLite nie
     pisze na udziale), potem kopia bajtów do `.incoming`; formaty
     wieloplikowe i pozostałe — kopia kompletu ze stanem (rozmiar, czas
     modyfikacji) każdego członu przed i po, najwyżej 3 próby, inaczej błąd
     `inconsistent_copy` („plik zmieniał się w trakcie kopiowania — zakończ
     edycję i spróbuj ponownie”); (3) tożsamość treści kopii (`sqlite`
     liczona na kopii) i dla SQLite `PRAGMA integrity_check` = `ok`; ta sama
     treść co ostatnia migawka → wynik `unchanged` z jej etykietą, katalog
     roboczy usunięty, nic nowego w `.wersje/`; (4) `migawka.json`, ponowne
     policzenie sum zapisanych plików, `fsync` plików i katalogu;
     (5) publikacja jednym `os.rename` katalogu roboczego na etykietę —
     istniejący cel to błąd `target_exists`, nigdy nadpisanie; (6) pliki
     migawki tylko do odczytu (`0444`, katalog `0555`); (7) wpis w indeksie.
     Przerwanie w dowolnym miejscu (SIGINT, zabicie procesu, awaria)
     zostawia najwyżej katalog w `.incoming/`: skan nie czyta go jako
     migawki, a pozostałość starszą niż 24 h zgłasza problem
     `stale_snapshot_incoming` w grupie „Dane własne” projektu (SPEC 4.7.1
     mówi „Magazyn”, ale dane własne należą do projektu — poprawka SPEC
     w kroku 18). Archiwista nie usuwa ani nie nadpisuje migawek ani
     pozostałości.
   - *Uprawnienie.* Nowa akcja `project.write` w `Authorizer`: właściciel
     projektu albo `admin` (A-ADR-029 pkt 2: „zmiany projektu — właściciel
     i administrator”); w v0.2 wymaga jej `POST …/snapshots`, od v0.3 także
     zmiany manifestu. Agent działa z prawami osoby, która wydała token.
     Projekt niewidoczny → `404`, widoczny bez `project.write` →
     `403 permission_denied`, bez nagłówka CSRF → `403 csrf_rejected`. Baza
     stanu nie potrzebuje migracji.
   - *Zadanie `snapshot`:* na plik naraz jedno (`409 conflict` z `job`), bez
     sieci, bez zapisu indeksu magazynu; serwer nie ma ścieżki zapisu do
     folderu danych.
10. **Odwołania `ref` i porównanie (SPEC 8.5, poziomy 1 i 2).**
    - Każdy obiekt, który można podglądać i porównywać, ma w modelach API
      pole `ref`: `version:<magazyn>:<ścieżka wersji>`,
      `file:<projekt>:<ścieżka w folderze danych>`,
      `snapshot:<projekt>:<etykieta>:<ścieżka w folderze danych>`.
      Identyfikatory magazynów (`[a-z0-9][a-z0-9_-]{0,31}`), klucze
      projektów (`[a-z0-9-]+`) i etykiety migawek nie zawierają `:`, więc
      reszta po drugim (dla migawki — trzecim) dwukropku to ścieżka bez
      ograniczeń. Agent przepisuje `ref` z odpowiedzi, nie składa go. Trasy
      HTTP podglądów zostają zasobowe (SPEC 9.2); plik danych własnych
      w adresie to `file_id` (16 znaków SHA-256 ścieżki względnej w NFC) —
      jeden segment, bo dowolna ścieżka użytkownika (np. z podkatalogiem
      `snapshots/`) myliłaby trasy.
    - `GET /compare?a=<ref>&b=<ref>` (SPEC 9.2) — poziom 1: wiersze
      z ludzką nazwą pola i wartościami A i B, z oznaczeniem różnicy. Dla
      wersji magazynu: znormalizowane pola indeksu (data danych i pobrania,
      etykieta, kampania, numer zgłoszenia, wydanie, pełny arkusz
      i pokrycie, rozdzielczość, układy, `nodata`, `sha256`, rozmiar,
      licencja i atrybucja), potem pozostałe pola surowego sidecara jako
      spłaszczone ścieżki JSON bez interpretacji (jak „surowy sidecar”
      v0.1; Archiwista nie zna pól producenta — A-ADR-014). Dla danych
      własnych i migawek: liczba obiektów per warstwa, zasięg, schemat
      (pola dodane, usunięte, o zmienionym typie), układ, rozmiar,
      tożsamość treści, autor, opis, daty. Dozwolone pary mieszane (migawka
      z plikiem roboczym, wersja z wersją innego slotu). Dwa lata (zbiory
      wersji) porównuje się wizualnie (kurtyna, przełączanie w Wachlarzu)
      z podsumowaniami warstw obok siebie — bez wierszy `/compare`. Eksport
      CSV robi interfejs z odpowiedzi JSON (serwer nic nie zapisuje).
      Poziom 3 (model różnic, KG) — v1.3; różnica obiektów migawek — osobna
      decyzja.
    - Poziom 2: widok „Porównanie” z kurtyną (domyślnie), przenikaniem
      i dwoma zsynchronizowanymi widokami obok siebie — dwie mapy MapLibre
      z tym samym położeniem, kurtyna przez `clip-path` ustawiane z JS
      (CSSOM, zgodne z `style-src 'self'`). Strony porównania: wersje, plik
      roboczy, migawki albo dwie warstwy lat.
11. **Gotowość dla agentów AI (`docs/AGENT_API.md`).** Wszystko, co robi
    interfejs, jest w API `/api/v1` z OpenAPI i w CLI z `--json` o modelu
    odpowiedzi trasy (błąd: problem RFC 9457 i kod 1; złe użycie: kod 2):
    - `archiwista preview REF [--style S] [--size N] [--output PLIK.png]
      [--build]` → `PreviewInfo`; `--output` zapisuje miniaturę przez ten
      sam proces renderujący i tę samą pamięć (agent multimodalny obejrzy
      obraz bez przeglądarki), `--build` buduje COG na pierwszym planie;
    - `archiwista compare REF REF` → `Comparison`;
    - `archiwista layers --store S --product P [--area-id A] [--segment G]
      [--group year|campaign]` → `LayerSet`;
    - `archiwista files PROJEKT [--q TEKST] [--state STAN]` →
      `OwnFileList`;
    - `archiwista file PROJEKT PLIK` → `OwnFileCard` z migawkami i historią
      stanów (`PLIK` = ścieżka w folderze albo `file_id`);
    - `archiwista snapshot PROJEKT PLIK [--note TEKST] [--plan]` — z
      `--plan` `SnapshotPlan` bez zapisu, bez niego zadanie na pierwszym
      planie jak `reindex` → `JobDetail` z wynikiem.

    Kafle nie mają odpowiednika w CLI (agent bierze miniatury albo HTTP).
    Zasady AGENT_API bez zmian: token jednorazowy, sesja, CSRF w każdym
    żądaniu, `409 conflict` → śledź trwające zadanie zamiast ponawiać.
12. **Cele wydajności v0.2.** Cele SPEC 4.5 z v0.1 obowiązują dalej. Nowe
    wiersze to cele tego planu (krok 18 wpisuje je do SPEC 4.5 jako
    „(v0.2)”); pomiar w kroku 16 na komputerze odniesienia, na magazynie
    50 000 slotów i fixturach podglądów, p95 z ≥ 30 prób po rozgrzewce:

    | Operacja | Dysk lokalny (SSD) | Udział SMB | Uwagi |
    |---|---|---|---|
    | przesuwanie mapy z 4500–5000 obrysów (wielokąty z decyzji 4) | ≥ 30 klatek/s | — | kryterium SPEC 13; WebGL sprzętowy (decyzja 1) |
    | opis podglądu `…/preview`, p95 | ≤ 200 ms | ≤ 200 ms | jak karta pliku |
    | miniatura i kafel z pamięci, p95 | ≤ 100 ms | ≤ 100 ms | pamięć lokalna, niezależna od udziału |
    | pierwszy kafel GeoTIFF kafelkowanego (ortofotomapa 22 528 × 24 326 px), p95 | ≤ 1 s | ≤ 2 s | rozgrzany proces renderujący |
    | pierwsza miniatura tego pliku | ≤ 2 s | ≤ 4 s | z nakładek |
    | lokalny COG arkusza ASC 1 m (ok. 38 MB) | ≤ 10 s | ≤ 20 s | zadanie `preview` |
    | `/local-layers` obszaru ≤ 500 slotów, p95 | ≤ 1 s | ≤ 5 s | z odświeżeniem widoku (SPEC 4.5) |
    | miniatura warstwy (≤ 50 arkuszy z gotowymi podglądami): pierwsza / z pamięci | ≤ 2 s / ≤ 100 ms | jw. | — |
    | Wachlarz roku z 35 arkuszy ASC od zera (z budową COG) | ≤ 2 min | ≤ 4 min | postęp widoczny |
    | `own_scan` folderu 1000 plików bez zmian | ≤ 2 s | ≤ 10 s | tylko `stat` |
    | migawka GeoPackage 100 MB | ≤ 15 s | ≤ 60 s | kopia, dwie sumy, `integrity_check` |
    | pełny skan 50 000 slotów z obrysami-wielokątami | ≤ 2 min | ≤ 10 min | regresja SPEC 4.5 |
    | pamięć serwera (bez procesów renderujących) | ≤ 500 MB | ≤ 500 MB | SPEC 4.5: „bez podglądów” |
    | proces renderujący, szczyt RSS | ≤ 1 GiB | ≤ 1 GiB | informacyjnie; limit `RLIMIT_AS` 2 GiB |

    Nieosiągnięty cel planu: najpierw pomiar składowych, potem poprawka;
    obniżenie celu wyłącznie decyzją użytkownika zapisaną w raporcie.
13. **Bezpieczeństwo nowych ścieżek (SPEC 10.1, 10.3).** Klient nigdy nie
    podaje ścieżki pliku: wersję wskazuje indeks (`resolve_indexed_path`
    w korzeniu magazynu), plik własny — `file_id` z indeksu w folderze
    danych, migawkę — etykieta z indeksu w `.wersje/`; każde otwarcie po
    `realpath` w korzeniu, dowiązanie wychodzące → `403 path_outside_root`.
    GDAL, OGR i laspy pracują tylko w procesach z sandboxem (decyzja 3);
    ZIP jest tylko listowany (katalog centralny, ≤ 10 000 członów, bez
    rozpakowania). Parametry kafli i miniatur są walidowane (z ≤ 24,
    `size` ∈ {128, 256, 512, 1024}, `style` z listy rodzaju, `rescale` —
    dwie liczby, kadr — cztery liczby w znanym układzie). Limit treści
    żądań bez zmian (1 MiB; `note` migawki ≤ 2000 znaków). Pamięć podglądów
    i pliki robocze kopii SQLite leżą w katalogu danych `0700`. Migawki
    zapisuje wyłącznie proces roboczy zadania `snapshot` po sprawdzeniu
    `project.write`.
14. **Rozdzielenie zakresu.** Poza v0.2: dostępność u źródła, etykiety
    pokrycia i plakietki magazynu, lata niepobrane z WMS GUGiK, jednostki
    z PRG (v0.3); widok „Zadania”, anulowanie z interfejsu i pozycja
    „Łączenie” w nawigacji (v0.3 i v0.6 — w v0.2 postęp zadania widać przy
    obiekcie, a „Porównanie” otwiera „Porównaj z…”); różnica obiektów
    migawek (osobna decyzja) i model różnic (KG, v1.3); dostarczanie plików
    przez HTTP i PDF w przeglądarce (v0.4); folder danych ustawiany przez
    właściciela projektu, dane własne w manifeście, usuwanie migawek (v0.4
    albo nigdy — SCOPE); kafle wektorowe MVT, podgląd zawartości ZIP przez
    `/vsizip/`, LAZ w 3D (po v1.0); limity pamięci procesów na Windows i
    testy Windows (v1.0); „Katalog” jako karty (v1.1).

## Umowy między krokami

- **Umowa źródła — `archiwista/sources/` (krok 3).** Jedyna zmiana
  protokołu: `CoordinateTransformer.gdal_operation() -> str` — pipeline PROJ
  tej samej przypiętej operacji dla GDAL-owego `COORDINATE_OPERATION`
  (Kartograf: `PinnedTransform.gdal_operation()`); minimalny adapter bez
  `GeoAdapter` dalej spełnia protokół (`tests/contract/test_source_protocol.py`).
  Adapter Kartografa woła `pinned_transform` w wątku, który używa obiektu
  (docstring Kartografa: obiektu nie przekazuje się między wątkami).
  Obrys WGS84 w indeksie liczy indeks, nie adapter:
  `index/geometry.py::outline_wgs84(native: BBox-like, native_crs: str,
  transformer: CoordinateTransformer, *, max_segment_m: float = 5000)
  -> Polygon` (wielokąt GeoJSON; natywny EPSG:4326 bez przeliczenia);
  używają go skaner (krok 3), skan danych własnych (7b) i opisy
  podglądów (6). `SCHEMA_VERSION` podnosi każdy krok
  zmieniający schemat indeksu (3: wielokąty obrysów; 7b: dane własne) —
  zmiana oznacza przebudowę indeksu (A-ADR-002); baza stanu bez zmian.
- **Odwołania — `archiwista/refs.py` (krok 6, rodzaje danych własnych
  rozstrzyga krok 9).** `parse_ref(text) -> VersionRef | FileRef |
  SnapshotRef` (`InvalidRefError` → `422 invalid_ref`), `format_ref(...)`;
  `ObjectResolver.resolve(ref, *, principal) -> PreviewSource` sprawdza
  widoczność (wersje magazynu — wszyscy; `file`/`snapshot` — projekt
  widoczny, inaczej `NotFoundError`), rozwiązuje ścieżki w korzeniu
  i zwraca opis źródła. Jedyny punkt przejścia od `ref` do pliku.
- **Podglądy — `archiwista/previews/` (kroki 4–6).**
  - *Typy* (`types.py`, krok 4): `PreviewSource(ref, content_sha256,
    paths, format_hint, size_bytes, crs, georeference, product,
    dataset_key, nodata, mutable, stat)` — `paths` to rozwiązane ścieżki
    (główny plik pierwszy, potem komplet), `crs` — układ dla pliku bez
    własnego (`EntryMeta.horizontal_crs`), `georeference` — natywny
    prostokąt i układ z obrysu nagłówkowego (JPEG), `mutable` i `stat`
    (rozmiar, czas modyfikacji) — plik roboczy danych własnych,
    sprawdzany przed i po renderowaniu. `PreviewKind`: `raster`, `image`,
    `vector`, `points`, `archive`, `document`, `auxiliary`, `unknown`.
    `PreviewState`: `ready`, `needs_build`, `building`, `unavailable`,
    `failed`. Kody powodów (`PreviewReason`): `no_georeference`, `no_crs`,
    `auxiliary_file`, `archive_members_only`, `document_no_preview`,
    `unsupported_format`, `too_large`, `missing_file`, `store_unavailable`,
    `transform_unavailable`, `unreadable`, `timeout`, `memory_limit`,
    `changed_since_scan`; teksty `preview_reason_<kod>`
    i `preview_fix_<kod>` w `messages.py`. Style: `hillshade`,
    `hypsometry` (wartości ciągłe), `rgb`, `gray` (obrazy), `classes`
    (klasy), `features` (wektor), `elevation`, `classes` (punkty).
    `PreviewProbe` (treść `info.json`): rodzaj, sterownik, wymiary, kanały,
    typ, układ, prostokąt natywny i WGS84, zakres zoomu (maks. = zoom
    rozdzielczości natywnej + 2, ≤ 22), nakładki, kafelkowanie, `nodata`,
    statystyki (p2, p98, min, max na kanał, z najmniejszej nakładki),
    paleta, warstwy wektora, nagłówek i klasy LAZ, liczba członów ZIP,
    `needs_cog`, powód.
  - *Pamięć* (`cache.py`, krok 4): `PreviewCache(root, *, limit_bytes)` —
    `get(key, name) -> Path | None` (dotyka czasu użycia), `put(key, name,
    data | path)` (atomowo: plik roboczy w `.incoming/`, `os.replace`),
    `pin(key)`/`unpin(key)`, `usage() -> CacheUsage(used_bytes,
    limit_bytes, objects)`, `evict()`; `CacheKey(content_sha256,
    renderer_version)`; nazwy: `info.json`, `cog.tif`,
    `thumb-<styl>-<rozmiar>[-<skrót kadru>].png`,
    `tiles/<styl>[-<skrót parametrów>]/<z>/<x>/<y>.png`. Bezpieczna dla
    wielu procesów (serwer, procesy zadań, CLI): SQLite WAL
    i `os.replace`.
  - *Sandbox* (`archiwista/sandbox.py`, krok 1): `untrusted_env()`,
    `child_limits(memory_bytes)` (POSIX: `RLIMIT_AS`, `umask 077`),
    `run_untrusted(argv, *, timeout_s, memory_bytes, input)`; używają go
    czytnik obszarów (refaktoryzacja `areas.py`, zachowanie bez zmian),
    procesy renderujące, procesy budowy i czytnik danych własnych.
  - *Pula* (`pool.py`, `worker.py`, `protocol.py`, krok 4):
    `RenderPool(*, workers, cache, timeouts)` z `request(op, source,
    params, *, timeout_s) -> RenderResult` (pliki w pamięci albo JSON),
    `start()`/`close()` (w `serve` obok `JobSupervisor`), proces bez pracy
    kończy się po 5 min. Protokół JSON Lines: żądanie `{"id", "op",
    "source", "params"}`, odpowiedź `{"id", "status": "ok", "files"}` albo
    `{"id", "status": "error", "code", "detail"}`; operacje `probe`,
    `thumbnail`, `tile`, `features`, `members`, `layer_thumbnail`. Błędy:
    `PreviewBusyError` (`503 preview_busy`), `PreviewTimeoutError`
    (`504 preview_timeout`), `PreviewUnavailableError` (`409
    preview_unavailable` z `reason`).
  - *Renderery* (`renderers/`, kroki 5a–5c; rejestr `RENDERERS` w kroku 4,
    jedna linia na moduł): protokół `Renderer` — `kinds`, `probe(source)
    -> PreviewProbe`, `thumbnail(source, probe, style, size, frame) ->
    bytes`, `tile(source, probe, style, z, x, y, params) -> bytes`,
    opcjonalnie `features(source, probe, layer, bbox_wgs84, limit) ->
    dict`, `members(source) -> dict`, `build(source, probe, out_path) ->
    None` (COG), `layer_thumbnail(items, frame, style, size) -> bytes`.
    Moduły: `raster.py` (5a), `vector.py` (5b), `points.py`, `archive.py`,
    `document.py` (5c). Transformacje bierze proces renderujący
    z rejestru wtyczek (`GeoAdapter` Kartografa — wymaganej zależności).
  - *Usługa* (`service.py`, krok 6): `PreviewService(pool, cache, jobs,
    settings, resolver)` — `info(source) -> PreviewInfo`,
    `thumbnail(...)`, `tile(...)`, `features(...)`, `members(...)`,
    `build(sources, *, actor, force) -> JobRecord | None`.
  - *Zadanie `preview`* (krok 4): parametry `{"refs": [≤ 500], "force":
    false}`, postęp `current`/`total`, wynik `{"built", "cached", "failed":
    [{"ref", "code", "detail"}], "seconds"}`; bez konfliktów — zlecenie
    treści z trwającego zadania dołącza do niego, a zadanie pomija treść
    już zbudowaną.
  - *Model `PreviewInfo`* (krok 6): `ref`, `state`, `kind`, `reason`
    (`code`, `message`, `fix`) albo `null`, `styles`, `default_style`,
    `thumbnail_url`, `tiles_url` (szablon `{z}/{x}/{y}`) albo `null`,
    `features_url`, `members_url`, `bounds` (WGS84), `minzoom`, `maxzoom`,
    `legend` (`kind`: `gradient` z `min`, `max`, `unit` albo `classes`
    z `items`: `value`, `color`, `label`), `layers` (wektor), `points`
    (LAZ: nagłówek, klasy, `sample_points`, `sampled_from`), `size_bytes`,
    `auto_build` (plik ≤ 2 GB), `job` (`id`, `state`) albo `null`. Adresy
    w modelu buduje serwer; klient ich nie składa.
- **Dane własne — `archiwista/owndata/` (kroki 7a, 7b, 9).**
  - *Czytnik* (`reader.py`, krok 7a): proces z sandboxem; wejście — linie
    JSON `{"path": "…"}`, wyjście — `OwnFileInfo(kind, driver, members,
    layers, raster, native_crs, native_bbox, feature_count, error)`; 30 s
    na plik.
  - *Treść* (`content.py`, `formats.py`, krok 7a):
    `content_identity(paths, *, method) -> ContentIdentity(method,
    sha256)`, `sqlite_content_sha256(connection)`,
    `fileset_members(path) -> tuple[Path, ...]` (Shapefile, TAB),
    `consistent_sqlite_read(path)` (`mode=ro` albo `immutable=1` ze
    sprawdzeniem stanu).
  - *Indeks* (krok 7b): tabele `own_folders` (klucz dostępu projektu,
    ścieżka, źródło: `default`/`setting`, stan `ok`/`missing`/
    `unreadable`, `scanned_at`, liczniki i bajty, bajty migawek),
    `own_files` (folder, ścieżka względna, `file_id`, rodzaj, sterownik,
    członkowie, rozmiar, czas modyfikacji, `content_method`,
    `content_sha256`, stan odczytu, warstwy i raster w JSON, układ, prostokąt
    natywny, wielokąt WGS84 z `outline_wgs84`, położenie z powodem, stan
    zmiany, ostatnia migawka, `first_seen_at`, `changed_at`,
    `missing_since`), `own_file_states` (historia, ≤ 200 na plik),
    `snapshots` (folder, plik i jego ścieżka, etykieta, `created_at`, autor,
    opis, treść, rozmiar, pliki, pełny `migawka.json`, stan
    `ok`/`invalid`/`modified`). `IndexWriter`: `write_own_folder`,
    `write_own_files`, `mark_own_missing`, `record_snapshot`;
    `IndexQueries`: `own_folder(project, *, visible)`, `own_files(project,
    *, visible, q, state, limit, cursor)`, `own_file(project, file_id, *,
    visible)` — `visible` wymagany jak w zapytaniach o projekty v0.1.
  - *Ustawienia* (krok 7b): `AppSettings.own_data_dirs: dict[str, str]`
    (katalog projektu → folder; walidacja w `validate_settings`, decyzja 8)
    i `AppSettings.preview_cache_limit_gb: int = 20` (1–10 000; krok 4).
  - *Zadanie `own_scan`* (krok 7b): obejmuje wszystkie projekty (przebieg
    plików bez zmian to tylko `stat`), bez parametrów; najwyżej jeden
    przebieg trwa i jeden czeka — zlecenie przy trwającym dołącza do
    czekającego (`202` z tym zadaniem), więc zmiana sprzed zlecenia
    zawsze trafi do wyniku; wynik `{"projects", "files", "new", "changed",
    "missing", "unreadable", "snapshots", "problems", "seconds"}`;
    harmonogram — przy starcie, gdy ostatni starszy niż 15 min, potem co
    `scan_interval_local_min`; rutynowe przebiegi bez zmian przycinane po
    48 h jak rutynowe skany v0.1.
  - *Modele* (kroki 7b i 9): `OwnFolder` (`path` jako `CopyPath` z aliasami,
    `source`, `state`, `files`, `size_bytes`, `snapshots_bytes`,
    `scanned_at`, `problems`), `OwnFileItem` (`file_id`, `path`, `ref`,
    `kind`, `format`, `size_bytes`, `modified_at`, `state`: `ok`,
    `unrecognized`, `unreadable`, `missing`; `change`: `unsnapshotted`,
    `unchanged`, `changed`; `last_snapshot`, `snapshots`, `location`),
    `OwnFileList` (`folder`, `items`, `next_cursor`), `OwnFileCard`
    (pola `OwnFileItem` oraz `layers`, `raster`, `crs`, `extent` natywny
    i WGS84, `content`, `history`, `snapshots`: `SnapshotItem`, `preview`:
    `PreviewInfo`, `paths`, `problems`), `SnapshotItem` (`label`, `ref`,
    `created_at`, `author`, `note`, `size_bytes`, `content`,
    `feature_count`, `extent`, `state`, `paths`), `SnapshotPlan` (`file`,
    `size_bytes`, `destination` jako `CopyPath`, `copy_method`,
    `content_method`, `unchanged_since` albo `null`, `blocked` (`code`,
    `message`) albo `null`, `free_bytes`, `warnings`, np.
    `editing_detected` przy pliku `-wal`). Problemy:
    `own_folder_unreadable`, `own_folder_too_large`, `own_file_unreadable`,
    `invalid_snapshot`, `unknown_snapshot_schema`, `snapshot_modified`,
    `stale_snapshot_incoming`, `path_outside_root`.
- **Migawki — `archiwista/owndata/{snapshots,document}.py` (krok 8).**
  `check_snapshot(folder, file, *, last, work_dir) -> SnapshotPlan`;
  `make_snapshot(folder, file, *, author, note, work_dir, cancel=None,
  fault=None) -> SnapshotResult(status: "created" | "unchanged", label,
  document)` (`fault` — punkt przerwania tylko dla testów);
  `SnapshotDocument` (decyzja 9). Zadanie `snapshot`: parametry
  `{"project", "file_id", "note"}`, klucz konfliktu (projekt, plik), wynik
  `{"status", "label", "content_sha256", "size_bytes", "seconds"}`, kody
  błędów: `snapshot_blocked` (z powodem: `read_only_folder`,
  `insufficient_space`, `file_missing`), `inconsistent_copy`,
  `checksum_mismatch`, `integrity_failed`, `target_exists`.
- **Zadania — `archiwista/jobs/` (kroki 4, 6, 7b, 8).** `JOB_KINDS` dostaje
  `preview`, `own_scan`, `snapshot`; `JobSpec.store: str | None`, projekt
  w `params`; `JobSupervisor.submit(kind, *, store=None, params, actor)`
  z regułą per rodzaj: `scan`/`footprints` — konflikt na magazyn (v0.1),
  `snapshot` — konflikt na (projekt, plik), `preview` — dołączenie do
  trwającej budowy tej samej treści, `own_scan` — jeden trwający i jeden
  czekający (dołączenie do czekającego); `JobFilters.project` (krok 9).
  Wspólne uruchamianie zadania na pierwszym planie
  (`jobs/foreground.py`, krok 6) zastępuje kod `jobs/reindex.py`
  i obsługuje `reindex`, `preview --build` i `snapshot`.
- **Uprawnienia — `archiwista/auth/` (krok 9).** `project.write` w `Action`
  i `ACTIONS` (reguła jak `project.share`: właściciel albo `admin`),
  komunikat `permission_project_write`; trasy wołają
  `authorizer.require(principal, "project.write", access_key)`.
- **API (kroki 6, 9, 10, 11).** Nowe trasy pod `/api/v1`, wszystkie
  z sesją i `X-Archiwista-CSRF`:

  | Metoda i ścieżka | Odpowiedź | Uprawnienie | Krok |
  |---|---|---|---|
  | `GET /stores/{store}/versions/{version}/preview` | `PreviewInfo` | sesja | 6 |
  | `POST /stores/{store}/versions/{version}/preview` (`{"force": false}`) | `200 PreviewInfo` albo `202 JobDetail` | sesja | 6 |
  | `GET …/preview.png?style&size&bbox&bbox_crs` | `image/png` | sesja | 6 |
  | `GET …/tiles/{z}/{x}/{y}.png?style&rescale` | `image/png` | sesja | 6 |
  | `GET …/features?layer&bbox&limit` | GeoJSON `FeatureCollection` (+ `number_matched`, `truncated`) | sesja | 6 |
  | `GET …/members` | `ArchiveMembers` | sesja | 6 |
  | `GET /projects/{project}/files?q&state&limit&cursor` | `OwnFileList` | widoczność | 9 |
  | `POST /projects/{project}/scan` | `202 JobDetail` (`own_scan`) | widoczność | 9 |
  | `PUT /projects/{project}/data-dir` (`{"path": … \| null}`) | `OwnFolder` | `settings.write` | 9 |
  | `GET /projects/{project}/files/{file_id}` | `OwnFileCard` | widoczność | 9 |
  | `GET\|POST /projects/{project}/files/{file_id}/preview`, `GET …/preview.png`, `…/tiles/{z}/{x}/{y}.png`, `…/features` | jak dla wersji | widoczność | 9 |
  | `GET /projects/{project}/files/{file_id}/snapshot-plan` | `SnapshotPlan` | widoczność | 9 |
  | `POST /projects/{project}/files/{file_id}/snapshots` (`{"note": …}`) | `202 JobDetail` (`snapshot`) | `project.write` | 9 |
  | `GET /projects/{project}/files/{file_id}/snapshots/{label}/preview`, `…/preview.png`, `…/tiles/…`, `…/features` | jak dla wersji | widoczność | 9 |
  | `GET /compare?a&b` | `Comparison` | wg obu `ref` | 10 |
  | `GET /local-layers?store&product&area_id&segment&group` | `LayerSet` | sesja | 11 |
  | `GET /local-layers/thumbnail.png?…&layer&size&v` | `image/png` | sesja | 11 |
  | `GET /projects/{project}/files/{file_id}/layers` | `LayerSet` (plik roboczy i migawki) | widoczność | 11 |

  Do istniejących: pole `ref` w modelach wersji (`Version`, `VersionCard`;
  krok 6); filtr `project` w `/slots` i `/map/footprints` (wersje przypięte
  w projekcie; krok 9); `previews` (`used_bytes`, `limit_bytes`,
  `objects`, `workers`) i `own_data` (ostatni `own_scan`) w `/health`
  (kroki 6 i 9); `project` w `GET /jobs` (krok 9). Nowe kody problemów:
  `422 invalid_ref`, `409 preview_unavailable` (z `reason`),
  `409 preview_not_ready` (z `job` albo `build_required`),
  `503 preview_busy` (z `Retry-After`), `504 preview_timeout`,
  `409 own_file_changed` (plik zmienił się od skanu → `POST
  /projects/{project}/scan`), `409 snapshot_blocked` (z `reason`).
  `LayerSet`: `area` (albo `null`), `store`, `product`, `group`, `frame`
  (`crs`, `bbox` w układzie płaskim; `null` bez obszaru), `layers`
  (od najnowszej): `key` (`<segment>:<rok|wydanie|etykieta>[:<kampania>]`),
  `segment`, `kind` (`year`, `edition`, `label`, `campaign`), `year`,
  `title`, `subtitle`, `versions_count`, `units_count`, `campaigns`,
  `data_dates`, `coverage` (`ratio`, `percent`, `label`) albo `null`,
  `outlines` (GeoJSON w `frame.crs`; tylko z obszarem), `preview`
  (`state`, `ready`, `total`, `job`, `thumbnail_url`), `versions` (≤ 500,
  tylko z obszarem: `ref`, `slot`, `unit`, podgląd: stan, `tiles_url`,
  `bounds`); dalej `stale`, `stale_stores`, `stale_reason` jak
  `/local-coverage`. `Comparison`: `a`, `b` (`ref`, rodzaj, tytuł,
  `preview`, obrys WGS84), `same_content`, `rows` (`group`, `field`,
  `label`, `a`, `b`, `differs`), `schema_diff` (warstwy: tylko w A/B,
  liczby obiektów, pola dodane, usunięte i zmienione) albo `null`.
- **Interfejs WWW — `archiwista/web/` (kroki 12a–15).** Umowa widoku v0.1
  bez zmian (linia w `VIEWS`/`OVERLAYS`, własny plik `labels/<widok>.js`,
  styl przez `loadStylesheet`). Nowe moduły:
  - `src/previews.js` — `usePreviewImage(url)` (adres `blob:` z `fetch`
    z nagłówkiem CSRF, zwalniany przy odmontowaniu) i `PreviewPane`
    (legenda, powód, przycisk budowy, postęp przez `useJob`);
  - `src/map/previews.js` — źródła rastrowe wersji i warstwy roku;
    `transformRequest` w `src/map/canvas.js` dodaje nagłówek CSRF tylko
    adresom `/api/v1/`;
  - `src/fan/layout.js` i `src/fan/fan.js` — Wachlarz jako tryb mapy;
  - `src/views/catalog-timeline.js` — Oś czasu jako układ Katalogu;
  - `src/views/set-details.js` — panel „Szczegóły zestawu”;
  - `src/views/compare.js` i `src/map/compare.js` — widok `compare`;
  - `src/views/own.js` — nakładka `own=<projekt>/<file_id>`;
  - słowniki `labels/previews.js`, `labels/fan.js`, `labels/timeline.js`,
    `labels/compare.js`, `labels/own.js`.

  Stan w adresie: `mode=fan`, `layer`, `group`, `layout=timeline`,
  `project` (mapa), `view=compare` z `a`/`b` (ref) albo
  `a_layer`/`b_layer`, `own=`.
- **CLI (kroki 6, 9–11).** Polecenia odczytu w `archiwista/reader.py`
  (`preview`, `compare`, `layers`, `files`, `file`) na funkcjach bez HTTP
  z `api/` i tych samych modelach; `snapshot` w `archiwista/jobs/`
  na `foreground.py`. Wszystkie jako `LOCAL_OWNER` przez ten sam
  `Authorizer`.
- **Fixtury (krok 2, punkt kontrolny — krok 3).**
  `tests/fixtures/make_store.py` (nowe rodziny w zestawie przypadków,
  nie w części masowej), `tests/fixtures/own_data.py`
  (`make_own_folder(path, *, families)`, `GpkgEditor` — edycja GeoPackage
  jak w QGIS: WAL, zmiany zatwierdzone w WAL i otwarta transakcja,
  `write_snapshot_fixture(...)` — katalog migawki zgodny z
  `archiwista-snapshot/1` dla testów skanu przed krokiem 8),
  `tests/fixtures/control_points.py` (punkt 3722 ze źródłem).

## Kolejność prac

| Krok | Tytuł | Zależności | Równolegle z | Stan |
|---|---|---|---|---|
| 0 | Porządki po v0.1: `ResourceWarning` | — | 1, 2, 3, 7a | do zrobienia |
| 1 | Zależności podglądów, sandbox i próby techniczne | — | 0, 2, 3 | do zrobienia |
| 2 | Magazyn testowy i fixtury v0.2 | — | 0, 1, 3, 4, 7a | do zrobienia |
| 3 | Obrysy-wielokąty i operacja dla GDAL w umowie źródła | — | 0, 1, 2, 4, 7a | do zrobienia |
| 4 | Infrastruktura podglądów: pamięć, pula, zadanie `preview` | 1 | 2, 3, 7a, 7b | do zrobienia |
| 5a | Podglądy rastrów | 1, 2, 3, 4 | 5b, 5c, 6, 7b, 8 | do zrobienia |
| 5b | Podglądy wektorów | 1, 2, 4 | 5a, 5c, 6, 7b, 8 | do zrobienia |
| 5c | Chmury punktów, archiwa, dokumenty, pliki pomocnicze | 1, 2, 4 | 5a, 5b, 6, 7b, 8 | do zrobienia |
| 6 | Podglądy magazynu przez HTTP i CLI; odwołania `ref` | 3, 4; odbiór po 5a–5c | 5a–5c, 7b, 8 | do zrobienia |
| 7a | Czytnik danych własnych i tożsamość treści | 1 (sandbox, próba SQLite) | 2, 3, 4 | do zrobienia |
| 7b | Folder danych, indeks i skan danych własnych | 2, 3, 7a | 4, 5a–5c, 6 | do zrobienia |
| 8 | Migawki | 7a, 7b | 5a–5c, 6, 10, 11, 12a | do zrobienia |
| 9 | Dane własne i migawki przez HTTP i CLI; `project.write` | 6, 7b, 8 | 10, 11, 12a | do zrobienia |
| 10 | Porównanie metadanych | 6; strony danych własnych po 9 | 11, 12a, 12b | do zrobienia |
| 11 | Warstwy lokalne i miniatury warstw | 3, 5a, 5b, 6; warstwy migawek po 9 | 10, 12a | do zrobienia |
| 12a | Interfejs: podgląd w Karcie pliku i ustawienia pamięci | 6 | 9, 10, 11 | do zrobienia |
| 12b | Interfejs: podglądy na mapie | 11, 12a | 9, 10 | do zrobienia |
| 13 | Interfejs: Wachlarz, Oś czasu, Szczegóły zestawu | 11, 12a, 12b | 14, 15, 16 | do zrobienia |
| 14 | Interfejs: Porównanie i kurtyna | 10, 12b | 13, 15, 16 | do zrobienia |
| 15 | Interfejs: dane własne i migawki | 9, 12a; Wachlarz migawek po 13, „Porównaj” po 14 | 13, 14, 16 | do zrobienia |
| 16 | Wydajność i pomiary (z płynnością mapy na GPU) | 3, 6, 7b, 8, 11, 12b | 13–15, 17 | do zrobienia |
| 17 | E2E i odbiór v0.2 | 12a–15 | 16 | do zrobienia |
| 18 | Dokumentacja, bramka i wydanie 0.2.0 | 0–17 | — | do zrobienia |

Fale równoległości: **A** — 0, 1, 2, 3; **B** — 4, 7a; **C** — 5a, 5b, 5c,
6 (umowa API na rejestrze rendererów), 7b; **D** — 8, 10 (wersje
magazynu), 11, 12a; **E** — 9, 12b; **F** — 13, 14, 15; **G** — 16, 17;
**H** — 18. Kroki jednej fali nie
edytują tych samych plików poza jedną linią rejestracji (rejestr
rendererów, `RUNNERS`, `include_router`, `VIEWS`/`OVERLAYS`) i podniesieniem
`SCHEMA_VERSION` przy scaleniu (kroki 3 i 7b).

### 0. Porządki po v0.1: `ResourceWarning`
- **Cel:** usunąć źródło ostrzeżenia `ResourceWarning` niezamkniętego
  połączenia SQLite z pełnego przebiegu testów (zgłaszanego przy
  `tests/unit/test_security.py::test_security_current_principal_owner_then_agent`,
  źródło nieustalone — PROGRESS) i nie dopuścić nowych. Ustalić miejsce
  utworzenia połączenia (`PYTHONTRACEMALLOC=25`, `python -X dev
  -W error::ResourceWarning -m pytest …` od pojedynczego pliku do pełnego
  zestawu), poprawić u źródła (zamknięcie w `close()`/menedżerze kontekstu
  albo w zakończeniu aplikacji), nie wyciszać.
- **Pliki:** moduł, który zostawia połączenie (np. `archiwista/security.py`,
  `archiwista/index/queries.py`, `archiwista/state/store.py` albo fixtura
  testu); `pyproject.toml` (`filterwarnings = ["error::ResourceWarning",
  "error::pytest.PytestUnraisableExceptionWarning"]`).
- **Interfejs:** bez zmian publicznych; poprawka w zarządzaniu połączeniami.
- **Test/odbiór:** pełny domyślny przebieg bramki z nowymi filtrami
  ostrzeżeń — zielony, bez ostrzeżeń `ResourceWarning` w podsumowaniu;
  w opisie commitu źródło i ścieżka utworzenia połączenia.
- **Zależności:** —. **Równolegle:** 1, 2, 3, 7a.

### 1. Zależności podglądów, sandbox i próby techniczne
- **Cel:** dołączyć zależności, dać wspólny sandbox procesów czytających
  pliki i sprawdzić założenia, na których stoją kroki 4–8, zanim powstanie
  reszta kodu produkcyjnego:
  - `archiwista/sandbox.py` (decyzja 3): środowisko, limity i uruchamianie
    procesów czytających niezaufane pliki — kod środowiska czytnika
    obszarów przeniesiony z `areas.py` bez zmiany zachowania (jedna
    implementacja dla czytnika obszarów, procesów renderujących, budowy
    COG i czytnika danych własnych);
  - `rio-tiler` (9.x; z nim morecantile, numexpr, color-operations)
    i `laspy[lazrs]` (2.7 / 0.8) w `pyproject.toml` i `requirements.lock`
    z sumami (`--require-hashes`); licencje zgodne z MIT (zapis
    w commicie); koła dla Linuksa x86-64 (Windows — v1.0);
  - próba warp: GeoTIFF EPSG:5514 z jasnym pikselem w punkcie kontrolnym
    (decyzja 4) → kafel z = 19 przez `rasterio.warp.reproject`
    z `COORDINATE_OPERATION = pinned_transform(5514, 3857).gdal_operation()`
    (≤ 2 m) i ta sama próba przez `WarpedVRT`/rio-tiler (oczekiwane:
    opcja zniekształcona albo odrzucona — zapis wyniku); odczyt z nakładki
    `OVERVIEW_LEVEL`; raster EPSG:4326 na kafel bez wymuszonej operacji
    (decyzja 4: Kartograf jej nie przypina);
  - próba LAZ: `laspy` z `lazrs` — nagłówek, układ z VLR, przeskok do
    kawałków (`seek`) dla próbki rozłożonej w pliku;
  - próba SQLite: `Connection.backup` z połączenia `mode=ro` do GeoPackage
    w WAL z innym połączeniem piszącym (zatwierdzone ramki w WAL, otwarta
    transakcja), otwarcie `mode=ro` bez `-shm` i `immutable=1` bez `-wal`
    — bez tworzenia plików obok; `PRAGMA table_list` (SQLite ≥ 3.37) do
    odróżnienia tabel wirtualnych i cieni;
  - próba dostarczania: MapLibre 6 z `transformRequest` dodającym
    `X-Archiwista-CSRF` do kafli rastrowych i `<img src="blob:…">` pod CSP
    z SPEC 10.1, w Chromium z Playwright.
- **Pliki:** `pyproject.toml`, `requirements.lock`, `archiwista/sandbox.py`,
  `archiwista/areas.py` (użycie sandboxa), `tests/unit/test_sandbox.py`,
  `tests/contract/test_preview_stack.py` (próby jako testy kontraktu
  bibliotek: wymuszona operacja trafia ≤ 2 m, `seek` LAZ, odczyt
  SQLite bez nowych plików), `tests/e2e/test_tile_headers.py`
  (`test_maplibre_raster_tiles_carry_csrf_header` na serwerze testowym
  z CSP v0.1); notatka „Stan po kroku 1” w tym planie z wynikami prób
  (także sprzecznymi z decyzjami — wtedy przegląd decyzji przed krokiem 4).
- **Interfejs:** umowa „Sandbox” z sekcji „Umowy”; poza nią brak kodu
  produkcyjnego.
- **Test/odbiór:** `.venv/bin/python -m pytest tests/contract/test_preview_stack.py
  tests/e2e/test_tile_headers.py` zielone; `pip install --require-hashes
  -r requirements.lock` w czystym `.venv`; `tests/contract/test_imports.py`
  zielony (nowe biblioteki nie są importowane przez serwer przy starcie —
  tylko przez procesy renderujące); `tests/unit/test_sandbox.py`
  (środowisko bez pośredników i poświadczeń, `PROJ_NETWORK=OFF`,
  `GDAL_SKIP`, limit pamięci i czasu procesu potomnego)
  i `tests/integration/test_areas.py` bez regresji.
- **Zależności:** —. **Równolegle:** 0, 2, 3.

### 2. Magazyn testowy i fixtury v0.2
- **Cel:** dać testom każdą rodzinę plików z decyzji 5 i foldery danych
  własnych. Generator v0.1 (`make_store`) dostaje w zestawie przypadków
  (nie w części masowej — magazyn 50 000 slotów zmienia się tylko
  o kilka slotów): PNG bez georeferencji jak podgląd WMS CORINE
  (`horizontal_crs: EPSG:3857`, obrys z godła), GeoTIFF klas z paletą
  (CORINE), GeoTIFF RGBA paskowy bez nakładek (mapa BDOT10k), ukośny
  GeoTIFF EPSG:2177 kafelkowany z nakładkami, GeoTIFF EPSG:4326
  (SoilGrids), ZIP z członami CityGML/GML i PDF, prawdziwy skompresowany
  LAZ z klasami 2, 3, 6 (laspy + lazrs), GeoPackage z dwiema warstwami
  (linie, wielokąty). Każdy przypadek regularny generator sprawdza
  czytnikiem Kartografa jak w v0.1 (`iter_store` bez problemu). Fixtury
  danych własnych: `make_own_folder` (GeoPackage z dwiema warstwami
  EPSG:2180, Shapefile z `.shp .shx .dbf .prj .cpg`, Shapefile bez `.prj`,
  GeoTIFF EPSG:2180, GeoJSON WGS84, FlatGeobuf, CSV i TXT jako
  nierozpoznane, plik ukryty, podkatalog, dowiązanie symboliczne poza
  folder, GeoPackage EPSG:5514 z punktem w punkcie kontrolnym),
  `GpkgEditor` (edytor jak QGIS) i `write_snapshot_fixture`.
- **Pliki:** `tests/fixtures/make_store.py`, `tests/fixtures/store_files.py`,
  `tests/fixtures/own_data.py`; `tests/contract/test_store_fixture.py`
  (nowe przypadki widziane przez Kartografa).
- **Interfejs:** `make_store` jak w v0.1 z nowymi przypadkami w manifeście
  oczekiwań (`ExpectedEntry` z rodziną pliku); `make_own_folder(path, *,
  families) -> OwnFolderManifest`; `GpkgEditor(path)` z `insert`, `commit`,
  `begin`, `close`.
- **Test/odbiór:** `tests/contract/test_store_fixture.py` zielony z nowymi
  rodzinami; `tests/unit/test_own_data_fixture.py` (komplet Shapefile,
  edytor zostawia zatwierdzone ramki w `-wal` i otwartą transakcję);
  czas generatora 50 000 slotów zapisany w notatce kroku.
- **Zależności:** — (prawdziwy LAZ wymaga laspy z kroku 1 — ten przypadek
  dochodzi po nim). **Równolegle:** 0, 1, 3, 4, 7a.

### 3. Obrysy-wielokąty i operacja dla GDAL w umowie źródła
- **Cel:** obrysy na mapie zgodne z rzeczywistością (decyzja 4,
  kryterium 2). `CoordinateTransformer.gdal_operation()` w protokole
  i w adapterze Kartografa; `outline_wgs84` w `index/geometry.py`; skaner
  (pula obrysów) zapisuje wielokąt WGS84 z obrysu natywnego dla każdego
  nowego obrysu (paczkami jednego układu — jedno wywołanie `transform` na
  paczkę), R*Tree dalej z obwiedni; `/map/footprints`, karta wersji
  i obszar na mapie dostają wielokąty; `SCHEMA_VERSION` + 1 (przebudowa
  indeksu przy pierwszym starcie — opis w CHANGELOG kroku 18). Fixtura
  punktu kontrolnego (decyzja 4) ze źródłem.
- **Pliki:** `archiwista/sources/protocol.py`,
  `archiwista/adapter/kartograf/adapter.py`, `archiwista/index/geometry.py`,
  `archiwista/index/scanner.py`, `archiwista/index/writer.py`,
  `archiwista/index/schema.py`, `tests/fixtures/control_points.py`.
- **Interfejs:** umowa źródła (sekcja „Umowy”); `outline_wgs84(...)`;
  model `Footprint.geometry` w API bez zmiany kształtu (GeoJSON
  `Polygon`), tylko więcej wierzchołków.
- **Test/odbiór:** `tests/contract/test_kartograf.py::test_gdal_operation_matches_pinned_transform`
  (adapter zwraca dokładnie `PinnedTransform.gdal_operation()` Kartografa
  dla tej samej pary, np. 5514 → 3857 i 2180 → 3857, z `axisswap` przy
  układzie northing-first); `tests/contract/test_source_protocol.py` (adapter bez
  `GeoAdapter` dalej spełnia protokół);
  `tests/integration/test_cz_control_point.py::test_cz_outline_vertex_within_2_m`
  (raster EPSG:5514 z lewym górnym narożnikiem w punkcie 3722 → skan →
  wierzchołek obrysu z `/map/footprints` ≤ 2 m od φ, λ ETRS89; obwiednia
  v0.1 nie przechodzi tego testu — zapis w notatce);
  `tests/unit/test_geometry.py::test_outline_wgs84_pl_west_sheet_is_rotated`
  (arkusz PL-1992 przy 14° E: czworokąt, nie prostokąt WGS84);
  `tests/integration/test_scanner.py` i `tests/unit/test_coverage.py` bez
  regresji.
- **Zależności:** —. **Równolegle:** 0, 1, 2, 4, 7a.

### 4. Infrastruktura podglądów: pamięć, pula, zadanie `preview`
- **Cel:** wszystko, czego potrzebują renderery, bez samych rendererów:
  `PreviewCache` z LRU i limitem
  (`AppSettings.preview_cache_limit_gb`, `AppPaths.previews_dir`),
  `RenderPool` z procesami renderującymi i protokołem JSON Lines,
  rejestr `RENDERERS` (z rendererem testowym w testach), rodzaj zadania
  `preview` w `JOB_KINDS`/`RUNNERS` z budową każdego pliku w osobnym
  procesie potomnym, uogólnienie nadzorcy (`store` opcjonalny, reguła
  konfliktu per rodzaj, dołączanie do trwającego `preview`), włączenie
  puli w `serve` (start, zatrzymanie, `app.state.previews`).
- **Pliki:** `archiwista/previews/{__init__,types,cache,pool,worker,protocol,build}.py`,
  `archiwista/previews/renderers/__init__.py`, `archiwista/config.py`,
  `archiwista/jobs/{protocol,supervisor,worker}.py`, `archiwista/server.py`,
  `archiwista/app.py`, `archiwista/messages.py`.
- **Interfejs:** umowy „Podglądy” (typy, pamięć, pula, zadanie)
  i „Zadania”; procesy uruchamia sandbox z kroku 1.
- **Test/odbiór:** `tests/integration/test_preview_cache.py`
  (`test_cache_limit_evicts_least_recently_used`,
  `test_cache_limit_holds_with_builds` — limit 1 MB, suma ≤ limit po
  każdym zapisie, obiekty w budowie chronione,
  `test_cache_survives_restart`, `test_cache_safe_across_processes`),
  `tests/integration/test_render_pool.py` (`test_single_flight_same_key`,
  `test_timeout_kills_and_respawns_worker`,
  `test_memory_limit_kills_worker`, `test_abandoned_request_never_rendered`,
  `test_queue_full_is_preview_busy`, `test_worker_env_has_no_network` —
  próba połączenia z GDAL w procesie renderującym kończy się bez ruchu
  sieciowego, `test_vrt_driver_refused`),
  `tests/integration/test_jobs.py::test_preview_build_joins_running_job`
  i `::test_preview_build_item_timeout_fails_item_only`.
- **Zależności:** 1. **Równolegle:** 2, 3, 7a, 7b.

### 5a. Podglądy rastrów
- **Cel:** renderer `raster.py` dla rodzin rastrowych z decyzji 5:
  rozpoznanie (sterownik, wymiary, typ, układ pliku albo `source.crs`,
  georeferencja z obrysu dla JPEG, nakładki, kafelkowanie, `nodata`,
  statystyki z najmniejszej nakładki, paleta, reguła `needs_cog`),
  miniatura (rio-tiler w układzie pliku; z kadrem — przeliczona
  z wymuszoną operacją), kafel (decyzja 4: `reproject` z nakładki na
  siatkę kafla z `COORDINATE_OPERATION`, potem `ImageData` i PNG; margines
  1 piksela dla cieniowania, bez szwów między kaflami), style
  (cieniowanie: azymut 315°, wysokość 45°, przewyższenie z rozmiaru
  piksela w metrach; hipsometria z legendą p2–p98 albo `rescale`;
  RGB/skala szarości; klasy z paletą pliku albo tablicą CLC i HSG A–D),
  budowa COG (decyzja 6), miniatura warstwy (`layer_thumbnail`:
  składanie podglądów wersji w kadrze układu płaskiego).
- **Pliki:** `archiwista/previews/renderers/raster.py`,
  `archiwista/previews/styles.py`, `archiwista/previews/legends.py`,
  `archiwista/previews/tiles.py` (siatka kafla, wybór nakładki).
- **Interfejs:** `Renderer` z umowy; style i legendy w `PreviewProbe`.
- **Test/odbiór:** `tests/unit/test_raster_renderer.py` (każda rodzina
  rastrowa z kroku 2: miniatura dekodowalna, kafel 256 × 256 z alfa,
  `nodata` przezroczyste, ASC → COG ≤ 8192 px, paskowy > 4096 px → COG,
  JPEG z obrysem `header` → georeferencja, PNG → `no_georeference`,
  EPSG:4326 (konwersja bez wymuszonej operacji) i EPSG:2177 na mapie,
  klasy z legendą, cieniowanie bez szwu na granicy sąsiednich kafli,
  `test_tile_forces_pinned_operation` — `reproject` dostaje
  `COORDINATE_OPERATION` z `gdal_operation()` dla układów innych niż
  WGS84);
  `tests/integration/test_cz_control_point.py::test_cz_preview_tile_within_2_m`
  (jasny piksel w punkcie 3722 w kaflu z = 19, środek plamy ≤ 2 m
  od φ, λ).
- **Zależności:** 1, 2, 3, 4. **Równolegle:** 5b, 5c, 6, 7b, 8.

### 5b. Podglądy wektorów
- **Cel:** renderer `vector.py`: rozpoznanie przez pyogrio (warstwy, typ
  geometrii, liczba obiektów, pola, układ, zasięg, próbka 20 wierszy),
  miniatura (rasteryzacja próbki ≤ 50 000 obiektów do 3 największych
  warstw liniowych i powierzchniowych albo wskazanej `layer`; punkty jako
  znaczniki; w układzie pliku albo w kadrze), `features` (prostokąt
  widoku WGS84 → układ pliku przypiętą operacją po zagęszczeniu;
  `max_features = limit + 1` → `truncated`; obiekty do WGS84 przypiętym
  transformatorem; atrybuty bez zmian, długie teksty skrócone),
  otwarcie GeoPackage magazynu jako niezmiennego, a plików roboczych bez
  tworzenia plików obok (`mode=ro`/`immutable=1` jak w decyzji 8).
- **Pliki:** `archiwista/previews/renderers/vector.py`,
  `archiwista/previews/rasterize.py`.
- **Interfejs:** `Renderer` z `features` i `layer_thumbnail` dla
  wektorów.
- **Test/odbiór:** `tests/unit/test_vector_renderer.py` (GeoPackage
  z dwiema warstwami, Shapefile, Shapefile bez `.prj` → `no_crs`,
  GeoJSON, FlatGeobuf; `limit` 5000 i `truncated`; prostokąt widoku
  w EPSG:2180 i EPSG:5514; folder bez nowych plików po odczycie
  GeoPackage w edycji);
  `tests/integration/test_cz_control_point.py::test_cz_features_within_2_m`
  (punkt GeoPackage EPSG:5514 w `features` ≤ 2 m).
- **Zależności:** 1, 2, 4. **Równolegle:** 5a, 5c, 6, 7b, 8.

### 5c. Chmury punktów, archiwa, dokumenty, pliki pomocnicze
- **Cel:** renderery `points.py` (LAZ/LAS: nagłówek, układ z VLR albo
  `source.crs`, gęstość, histogram klas ASPRS z próbki ≤ 2 mln punktów
  rozłożonej po kawałkach — bez tablicy kawałków próbka z początku
  z dopiskiem `sampled_from: "start"`, obraz 2D maks. Z w siatce o boku
  ≥ 1 m jako COG przez zadanie `preview`, potem kafle jak raster),
  `archive.py` (ZIP: katalog centralny bez rozpakowania, ≤ 10 000 członów
  z `truncated`, rozmiar, rozmiar spakowany, format z rozszerzenia; nazwy
  członów tylko wypisywane), `document.py` (PDF, TXT, pliki pomocnicze
  `.jgw .tfw .pgw .wld .prj .aux.xml` i nieznane — powody z decyzji 5).
- **Pliki:** `archiwista/previews/renderers/{points,archive,document}.py`,
  `archiwista/previews/legends.py` (klasy ASPRS po polsku).
- **Interfejs:** `Renderer` z `members` (archiwum) i `build` (LAZ).
- **Test/odbiór:** `tests/unit/test_points_renderer.py` (LAZ z kroku 2:
  klasy 2, 3, 6 z liczbami, obraz 2D, LAS nieskompresowany pod nazwą
  `.laz` z v0.1, plik bez tablicy kawałków), `tests/unit/test_archive_renderer.py`
  (10 001 członów → `truncated`, człon `../x` tylko wypisany, nic nie
  rozpakowane), `tests/unit/test_document_renderer.py` (PDF, TXT, JGW,
  nieznany → właściwy kod i polski opis).
- **Zależności:** 1, 2, 4. **Równolegle:** 5a, 5b, 6, 7b, 8.

### 6. Podglądy magazynu przez HTTP i CLI; odwołania `ref`
- **Cel:** trasy podglądów wersji magazynu z umowy API (opis, budowa,
  miniatura, kafle, obiekty, człony), `refs.py` i `ObjectResolver` dla
  wersji (ścieżka z `resolve_indexed_path`, `sha256`, `horizontal_crs`,
  produkt i klucz zbioru z indeksu, a dla obrysu o źródle `header` —
  natywny prostokąt i układ jako `georeference`), `PreviewService`, pole
  `ref` w modelach wersji, `previews` w `/health`, nagłówki
  `Cache-Control`/`ETag`/`304` (decyzja 3), nowe kody problemów,
  polecenie `archiwista preview` (`--build` przez `jobs/foreground.py`,
  który przejmuje kod `jobs/reindex.py`).
- **Pliki:** `archiwista/refs.py`, `archiwista/previews/service.py`,
  `archiwista/api/previews.py`, `archiwista/api/models.py`,
  `archiwista/api/errors.py`, `archiwista/api/health.py`,
  `archiwista/app.py` (jedna linia `include_router`),
  `archiwista/jobs/foreground.py`, `archiwista/jobs/reindex.py`,
  `archiwista/reader.py`, `archiwista/cli.py`, `archiwista/messages.py`.
- **Interfejs:** umowa API (wiersze kroku 6), `PreviewInfo`, CLI
  z decyzji 11.
- **Test/odbiór:** `tests/integration/test_previews_api.py` (każda trasa,
  walidacja parametrów → `422`, `409 preview_not_ready` przed budową,
  `POST` → `202` → `ready`, `304` po `ETag`, `preview_unavailable`
  z powodem, odłączony magazyn → z pamięci albo `503 store_unavailable`,
  bez CSRF → `403`), `tests/integration/test_preview_coverage.py::test_every_store_file_type_has_preview_or_reason`
  (kryterium 1), `tests/integration/test_preview_cache.py::test_same_content_rendered_once`
  (kryterium 3: dwie wersje o tym samym `sha256`, powtórzenia i restart —
  licznik żądań procesów renderujących bez zmian),
  `tests/integration/test_preview_security.py`
  (`test_server_process_never_opens_data_files` — w procesie serwera
  `rasterio.open`, `pyogrio`, `laspy.open` i `zipfile.ZipFile` zgłaszają
  błąd, a trasy działają; ścieżka spoza korzenia → `403
  path_outside_root`), `tests/integration/test_cli.py::test_preview_cli_equals_http`
  i `::test_preview_output_writes_png`,
  `tests/integration/test_jobs.py::test_reindex_on_foreground_helper`
  (bez regresji `reindex`).
- **Zależności:** 3, 4; odbiór po 5a–5c. **Równolegle:** 5a–5c, 7b, 8.

### 7a. Czytnik danych własnych i tożsamość treści
- **Cel:** proces czytnika (decyzja 8; sandbox z kroku 1), rozpoznanie
  formatów i kompletów plików, tożsamość treści `bytes`/`fileset`/`sqlite`
  i spójny odczyt SQLite bez tworzenia plików.
- **Pliki:** `archiwista/owndata/{__init__,reader,formats,content}.py`.
- **Interfejs:** umowa „Dane własne” (czytnik i treść).
- **Test/odbiór:** `tests/unit/test_own_content.py`
  (`test_sqlite_hash_ignores_vacuum_and_checkpoint`,
  `test_sqlite_hash_includes_committed_wal_frames`,
  `test_sqlite_hash_excludes_uncommitted_transaction`,
  `test_sqlite_hash_changes_with_row_or_schema`,
  `test_sqlite_hash_ignores_rtree_shadow_tables`,
  `test_fileset_independent_of_listing_order`),
  `tests/integration/test_own_reader.py` (wszystkie rodziny
  z `make_own_folder`, Shapefile jako komplet, brak układu, plik wiszący
  zabity po 30 s i kolejne pliki czytane dalej,
  `test_data_folder_unchanged_after_reads` — nazwy, rozmiary, czasy,
  brak `-wal`/`-shm` także przy GeoPackage w edycji).
- **Zależności:** 1 (sandbox, próba SQLite). **Równolegle:** 2, 3, 4.

### 7b. Folder danych, indeks i skan danych własnych
- **Cel:** ustawienie `own_data_dirs` z walidacją i funkcją usługi do
  zmiany folderu (trasę daje krok 9), tabele indeksu danych własnych
  (`SCHEMA_VERSION` + 1), zapis i odczyt z wymaganym `visible`, skan
  `scan_own_data` (decyzja 8: przejście folderu, odczyt nowych i zmienionych
  plików czytnikiem 7a, wielokąty zasięgu `outline_wgs84`, migawki
  z `.wersje/**/migawka.json` z walidacją `SnapshotDocument`, stan zmiany,
  historia stanów, problemy), zadanie `own_scan` z harmonogramem
  i przycinaniem rutynowych przebiegów.
- **Pliki:** `archiwista/config.py`, `archiwista/owndata/scan.py`,
  `archiwista/owndata/document.py` (model — wspólny z krokiem 8),
  `archiwista/index/{schema,writer,queries,types}.py`,
  `archiwista/services/owndata.py`, `archiwista/jobs/{worker,supervisor,scheduler}.py`,
  `archiwista/messages.py`.
- **Interfejs:** umowa „Dane własne” (indeks, ustawienia, zadanie,
  modele `OwnFolder`, `OwnFileItem`, `OwnFileCard`, `SnapshotItem`).
- **Test/odbiór:** `tests/integration/test_own_scan.py`
  (`test_folder_with_gpkg_shp_geotiff_indexed_with_extent` — zasięg
  natywny i WGS84, warstwy, liczba obiektów, schemat;
  `test_change_after_snapshot_detected` — z `write_snapshot_fixture`:
  zmiana obiektu GeoPackage, dopisanie do Shapefile, nadpisanie GeoTIFF →
  `changed` z datą migawki, powrót treści → `unchanged`, historia stanów;
  `test_unchanged_files_cost_only_stat`; `test_hidden_and_versions_skipped`;
  `test_symlink_outside_folder_skipped`; `test_invalid_snapshot_problem`;
  `test_stale_incoming_problem_after_24h`; `test_missing_file_keeps_snapshots`),
  `tests/unit/test_config.py::test_own_data_dir_validation` (w magazynie,
  zagnieżdżony z folderem innego projektu, nieistniejący → odrzucone),
  `tests/unit/test_scheduler.py::test_own_scan_planned_and_pruned`,
  `tests/integration/test_jobs.py::test_own_scan_request_joins_waiting_run`
  (przy trwającym przebiegu najwyżej jeden czekający, zmiana sprzed
  zlecenia w wyniku),
  `tests/integration/test_state.py` bez zmian (baza stanu nietknięta).
- **Zależności:** 2, 3, 7a. **Równolegle:** 4, 5a–5c, 6.

### 8. Migawki
- **Cel:** `check_snapshot` i `make_snapshot` (decyzja 9), dokument
  `archiwista-snapshot/1`, zadanie `snapshot` (proces roboczy, klucz
  konfliktu, wynik i kody błędów), zapis migawki w indeksie po
  publikacji, katalog roboczy kopii SQLite w lokalnym katalogu danych
  (`AppPaths.snapshot_work_dir`, czyszczony przy starcie).
- **Pliki:** `archiwista/owndata/{snapshots,document}.py`,
  `archiwista/jobs/{protocol,worker,supervisor}.py`, `archiwista/config.py`,
  `archiwista/index/writer.py`, `archiwista/messages.py`.
- **Interfejs:** umowa „Migawki”.
- **Test/odbiór:** `tests/integration/test_snapshots.py`:
  `test_gpkg_open_for_editing_snapshot_is_consistent` (kryterium 7:
  `GpkgEditor` w WAL — zatwierdzone ramki w `-wal` i otwarta transakcja;
  kopia `PRAGMA integrity_check` = `ok`, wiersze zatwierdzone są,
  niezatwierdzone nie, pyogrio czyta kopię, poza `.wersje/` folder bez
  zmian), `test_interrupted_snapshot_leaves_no_partial_version`
  (kryterium 8: przerwanie w każdej fazie — kopia, sumy, `migawka.json`,
  przed `rename` — przez `fault`, SIGINT i SIGKILL procesu roboczego;
  brak nowej etykiety w `.wersje/`, indeks bez nowej migawki,
  pozostałość tylko w `.incoming/`),
  `test_same_content_makes_no_second_snapshot` (kryterium 9: drugi raz
  bez zmian → `unchanged` z etykietą pierwszej; GeoPackage po VACUUM
  i punkcie kontrolnym → `unchanged`; A → B → A → `_2`),
  `test_fileset_changing_during_copy_retries_then_fails`,
  `test_read_only_folder_blocked`, `test_insufficient_space_blocked`,
  `test_second_snapshot_of_file_conflicts`, `test_published_files_read_only`,
  `test_document_validates_and_sums_match`.
- **Zależności:** 7a, 7b. **Równolegle:** 5a–5c, 6, 10, 11, 12a.

### 9. Dane własne i migawki przez HTTP i CLI; `project.write`
- **Cel:** trasy danych własnych z umowy API (lista, skan, folder danych,
  karta, podglądy pliku roboczego i migawek, plan migawki, migawka),
  rozstrzyganie `file:`/`snapshot:` w `ObjectResolver` (plik roboczy:
  stan sprzed i po renderowaniu, zmiana od skanu → `409
  own_file_changed`), akcja `project.write`, filtr `project` w `/slots`
  i `/map/footprints`, `project` w `GET /jobs`, `own_data` w `/health`,
  polecenia `files`, `file`, `snapshot`.
- **Pliki:** `archiwista/api/owndata.py`, `archiwista/api/models.py`,
  `archiwista/api/{slots,map,jobs,health}.py`, `archiwista/app.py`,
  `archiwista/auth/authorize.py`, `archiwista/refs.py`,
  `archiwista/services/owndata.py`, `archiwista/index/queries.py`,
  `archiwista/reader.py`, `archiwista/jobs/foreground.py`,
  `archiwista/cli.py`, `archiwista/messages.py`.
- **Interfejs:** umowa API (wiersze kroku 9), `SnapshotPlan`, CLI
  z decyzji 11; trasy nie filtrują same — `visible_projects` i `Authorizer`
  jak w v0.1.
- **Test/odbiór:** `tests/integration/test_own_data_api.py`
  (`test_folder_with_gpkg_shp_geotiff_indexed_with_extent_and_preview` —
  kryterium 6 przez HTTP: karta, miniatura, kafle GeoTIFF, obiekty
  GeoPackage i Shapefile; `test_own_file_types_have_preview_or_reason`;
  plan → migawka → zadanie → karta; `409 own_file_changed`; `PUT
  data-dir` przez nie-admina → `403`), `tests/unit/test_authorize.py::test_project_write_matrix`,
  `tests/integration/test_permissions_api.py::test_own_data_visibility_matrix`
  (każda nowa trasa z projektem, `file:`/`snapshot:` w podglądach
  i `/compare`, filtr `project`: niewidoczny → `404`, migawka bez
  `project.write` → `403`, bez CSRF → `403 csrf_rejected`, tryb lokalny
  może wszystko), `tests/integration/test_cli.py::test_own_data_cli_equals_http`,
  `tests/integration/test_agent_flow.py::test_agent_snapshot_flow` (token →
  sesja → plan → migawka → SSE zadania → karta).
- **Zależności:** 6, 7b, 8. **Równolegle:** 10, 11, 12a.

### 10. Porównanie metadanych
- **Cel:** `services/compare.py` i `GET /compare` (decyzja 10, poziom 1),
  `archiwista compare REF REF`.
- **Pliki:** `archiwista/services/compare.py`, `archiwista/api/compare.py`,
  `archiwista/api/models.py`, `archiwista/app.py`, `archiwista/reader.py`,
  `archiwista/messages.py`.
- **Interfejs:** model `Comparison` z umowy API.
- **Test/odbiór:** `tests/integration/test_compare.py` (dwie wersje
  jednego slotu: daty, kampania, `sha256`, rozmiar różne, pola surowego
  sidecara jako spłaszczone ścieżki; wersje dwóch slotów; migawka z
  plikiem roboczym: liczby obiektów, pola dodane i usunięte, zasięg;
  ta sama treść → `same_content`; zły `ref` → `422 invalid_ref`;
  niewidoczny projekt → `404`), `tests/integration/test_cli.py::test_compare_cli_equals_http`.
- **Zależności:** 6; strony danych własnych po 9. **Równolegle:** 11, 12a,
  12b.

### 11. Warstwy lokalne i miniatury warstw
- **Cel:** `services/layers.py` i `GET /local-layers` (decyzja 7):
  grupowanie wersji slotów obszaru po segmencie i roku danych, wydaniu
  albo etykiecie (`group=campaign` — po kampanii), odświeżenie widoku
  wspólnym pomocnikiem z `/local-coverage` (pamięć 60 s dla tej samej
  pary obszaru i segmentu), pokrycie lokalne warstwy w układzie płaskim,
  obrysy w kadrze, stan podglądów warstwy z jednym zadaniem `preview`
  na brakujące, `GET /local-layers/thumbnail.png` (parametr `v` = skrót
  gotowych treści, więc adres zmienia się, gdy dojdą podglądy), warstwy
  pliku własnego (`GET /projects/{project}/files/{file_id}/layers`: plik
  roboczy na górze, migawki od najnowszej, kadr = suma zasięgów),
  `archiwista layers`.
- **Pliki:** `archiwista/services/layers.py`, `archiwista/api/layers.py`,
  `archiwista/api/models.py`, `archiwista/api/areas.py` (wspólny pomocnik
  odświeżenia), `archiwista/app.py`, `archiwista/reader.py`.
- **Interfejs:** `LayerSet` z umowy API; operacja `layer_thumbnail`
  rendererów 5a/5b.
- **Test/odbiór:** `tests/integration/test_local_layers.py`
  (`test_layers_by_data_year_never_download_year`,
  `test_layers_by_edition_without_year`, `test_group_by_campaign`,
  `test_layer_coverage_planar`, `test_outlines_in_frame_crs`,
  `test_refresh_before_answer_and_stale_when_disconnected`,
  `test_layer_thumbnail_partial_then_full_after_build`,
  `test_without_area_counts_only`, `test_own_file_layers_current_first`),
  `tests/integration/test_cli.py::test_layers_cli_equals_http`.
- **Zależności:** 3, 5a, 5b, 6; warstwy migawek po 9. **Równolegle:** 10,
  12a.

### 12a. Interfejs: podgląd w Karcie pliku i ustawienia pamięci
- **Cel:** zakładka „Podgląd” Karty pliku dla wersji (miniatura przez
  `usePreviewImage`, styl, legenda, powód braku z zaleceniem, „Zbuduj
  podgląd” z postępem zadania, warstwy i próbka atrybutów wektora, klasy
  LAZ, lista członów ZIP); „Ustawienia”: limit pamięci podglądów
  i zajętość z `/health`. Przyciski „Pokaż podgląd na mapie” (krok 12b)
  i „Porównaj z…” (krok 14) dochodzą w swoich krokach.
- **Pliki:** `archiwista/web/src/previews.js`, `archiwista/web/src/views/file.js`,
  `archiwista/web/src/setup.js`, `archiwista/web/src/api.js` (funkcje tras
  kroku 6), `archiwista/web/src/types.js`,
  `archiwista/web/src/labels/{previews,file,setup}.js`,
  `archiwista/web/src/views/cards.css`.
- **Interfejs:** umowa WWW; tylko trasy z kroku 6.
- **Test/odbiór:** `tests/e2e/test_previews.py`
  (`test_card_preview_thumbnail_via_blob_with_csrf`,
  `test_card_shows_reason_for_jgw_png_and_zip_members`,
  `test_card_builds_asc_preview_with_progress`,
  `test_settings_cache_limit_and_usage`, `test_no_csp_violations_previews`,
  `test_offline_previews_make_no_external_requests`).
- **Zależności:** 6. **Równolegle:** 9, 10, 11.

### 12b. Interfejs: podglądy na mapie
- **Cel:** `transformRequest` w `map/canvas.js`; podgląd wersji na mapie
  (przycisk „Pokaż podgląd na mapie” w Karcie pliku: kafle wersji w jej
  granicach i obrys); warstwy lat z `/local-layers` jako przyciski lat na
  mapie (SPEC 6.1), wybrana warstwa = obrysy jej wersji i ich kafle
  (≤ 200 w widoku, powyżej obrysy i „Przybliż, aby zobaczyć podgląd”);
  legenda podglądu w legendzie mapy; wybór warstwy w adresie (`layer`).
- **Pliki:** `archiwista/web/src/map/{canvas,previews,legend,panel}.js`,
  `archiwista/web/src/views/{map,file}.js`, `archiwista/web/src/api.js`,
  `archiwista/web/src/labels/{map,file}.js`, `archiwista/web/src/map/map.css`.
- **Interfejs:** umowa WWW; trasy kroków 6 i 11.
- **Test/odbiór:** `tests/e2e/test_map_previews.py`
  (`test_version_tiles_on_map_with_csrf_header`,
  `test_year_buttons_select_layer_and_tiles`,
  `test_more_than_200_versions_show_outlines_and_hint`,
  `test_layer_in_url_restores_view`, `test_no_csp_violations_map_previews`);
  `tests/e2e/test_map.py` bez regresji.
- **Zależności:** 11, 12a. **Równolegle:** 9, 10.

### 13. Interfejs: Wachlarz, Oś czasu, Szczegóły zestawu
- **Cel:** przełącznik „Mapa / Wachlarz / Katalog” nad środkiem (Katalog =
  ten sam stan co `view=catalog`); Wachlarz (`mode=fan`) jako komponent
  SVG z układem z mockupu (`mockup/src/fan.js`): miniatury warstw na łuku,
  najnowsza na górze, każda w całości we własnym miejscu, wybrana
  powiększona w łuku i duża obok, podpis: rok, „lokalnie N% obszaru”,
  wariant, liczba kampanii, stan podglądu (A-ADR-018 z erratą 1, SPEC
  5.4, 6.5 c), obrysy arkuszy z `outlines` na miniaturze; Oś czasu
  w Katalogu (`layout=timeline`): lata na osi poziomej z latami bez danych,
  wiersz = wariant (segment), słupek = pokrycie lokalne obszaru albo —
  bez obszaru — liczba wersji (SPEC 6.5 b w wersji lokalnej); panel
  „Szczegóły zestawu” (SPEC 6.1: tylko wybrana warstwa — wersje, kampanie
  z datami, pokrycie lokalne, „Pokaż na mapie”, arkusze → Karta pliku;
  „Porównaj z…” dodaje krok 14; bez działań pobierania przed v0.3); jeden
  wybór zsynchronizowany w mapie, Wachlarzu, Osi czasu, panelu i adresie;
  klawiatura (`Enter`, `Spacja`, strzałki) i ARIA; szerokie ekrany (≥ 2000
  px środka — Wachlarz albo Katalog obok mapy) i telefon.
- **Pliki:** `archiwista/web/src/fan/{layout,fan}.js`,
  `archiwista/web/src/views/{map,catalog,catalog-timeline,set-details}.js`,
  `archiwista/web/src/labels/{fan,timeline,map,catalog}.js`, style
  `fan.css`, `timeline.css`.
- **Interfejs:** umowa WWW; `LayerSet` z kroku 11.
- **Test/odbiór:** `tests/e2e/test_fan_timeline.py`
  (`test_fan_newest_on_top_and_no_overlap`,
  `test_selected_layer_fully_visible_and_enlarged`,
  `test_selection_syncs_map_fan_timeline_panel_and_url`,
  `test_fan_keyboard_selection`, `test_timeline_shows_years_without_data`,
  `test_timeline_bar_height_is_local_coverage`,
  `test_wide_3440_fan_beside_map`, `test_phone_390_layout`), zrzuty
  1440, 3440 i 390 px w raporcie.
- **Zależności:** 11, 12a, 12b. **Równolegle:** 14, 15, 16.

### 14. Interfejs: Porównanie i kurtyna
- **Cel:** widok `compare` (decyzja 10): tabela różnic z przełącznikiem
  „tylko różnice” i eksportem CSV po stronie przeglądarki; mapa
  porównania — kurtyna (domyślnie; uchwyt przeciągany myszą, dotykiem
  i strzałkami), przenikanie (suwak), dwa widoki obok siebie
  zsynchronizowane; strony: `ref` (wersja, plik roboczy, migawka) albo
  warstwa lat (`a_layer`, `b_layer` z `/local-layers`); wejścia: „Porównaj
  z…” w Karcie pliku (wybór innej wersji slotu) i — po kroku 13 —
  w panelu „Szczegóły zestawu” (druga warstwa lat).
- **Pliki:** `archiwista/web/src/views/compare.js`,
  `archiwista/web/src/map/compare.js`, `archiwista/web/src/views/file.js`,
  `archiwista/web/src/views/set-details.js` (po kroku 13),
  `archiwista/web/src/routes.js` (jedna linia),
  `archiwista/web/src/labels/compare.js`, `compare.css`.
- **Interfejs:** umowa WWW; `Comparison` (10), `PreviewInfo` (6),
  `LayerSet` (11).
- **Test/odbiór:** `tests/e2e/test_compare.py`
  (`test_metadata_table_marks_differences`,
  `test_curtain_drag_reveals_b`, `test_fade_slider_changes_opacity`,
  `test_side_by_side_maps_stay_in_sync`, `test_two_year_layers_compared`,
  `test_csv_export_matches_table`, `test_no_csp_violations_compare`).
- **Zależności:** 10, 12b. **Równolegle:** 13, 15, 16.

### 15. Interfejs: dane własne i migawki
- **Cel:** w widoku projektu grupa „Dane własne” obok zadań producentów
  (folder i jego stan, liczba plików, zajętość, zajętość migawek, lista
  plików ze stanem zmiany, „Odśwież” → `own_scan` z postępem, dla
  administratora „Zmień folder danych…”); nakładka `own=` (karta pliku
  własnego: metadane, warstwy i schemat, zasięg, oś wersji — plik roboczy
  i migawki, „zmieniony od migawki z …”, historia stanów, podgląd,
  „Pokaż na mapie”, „Porównaj z migawką…”, „Wachlarz migawek” z kroku 13
  na `LayerSet` pliku); „Zrób migawkę…” jako „Okno planu” (SPEC 6.1: plik,
  rozmiar, miejsce, metoda kopii, „tylko przyrost”, informacja „bez zmian
  od migawki z …”, pole opisu, „Anuluj” / „Zrób migawkę”) → zadanie
  z postępem → nowa migawka na osi; mapa w kontekście projektu
  (`project=`): warstwa „Dane własne” (zasięgi plików, obiekty albo kafle
  wybranego) i obrysy wersji przypiętych w projekcie.
- **Pliki:** `archiwista/web/src/views/{projects,own}.js`,
  `archiwista/web/src/map/{own,canvas}.js`, `archiwista/web/src/views/map.js`,
  `archiwista/web/src/routes.js` (jedna linia), `archiwista/web/src/api.js`,
  `archiwista/web/src/labels/{own,projects}.js`, `own.css`.
- **Interfejs:** umowa WWW; trasy kroków 9 i 11.
- **Test/odbiór:** `tests/e2e/test_own_data.py`
  (`test_project_own_data_on_map_and_card` — kryterium 6 w przeglądarce,
  `test_snapshot_plan_then_job_then_new_snapshot`,
  `test_same_content_shows_unchanged_notice`,
  `test_changed_since_snapshot_badge` — kryterium 10 w przeglądarce,
  `test_snapshot_fan_current_on_top`,
  `test_compare_snapshot_with_current`,
  `test_data_dir_change_admin_only`, `test_no_csp_violations_own_data`).
- **Zależności:** 9, 12a; Wachlarz migawek po 13, „Porównaj” po 14.
  **Równolegle:** 13, 14, 16.

### 16. Wydajność i pomiary (z płynnością mapy na GPU)
- **Cel:** zmierzyć cele SPEC 4.5 (regresja z obrysami-wielokątami) i cele
  planu (decyzja 12) na komputerze odniesienia; pomiar płynności mapy
  z WebGL sprzętowym (decyzja 1): uruchomienie Chromium z flagami GPU
  albo przez CDP, sprawdzenie renderera (`WEBGL_debug_renderer_info`),
  tryb bramki `ARCHIWISTA_REQUIRE_GPU=1` (WebGL programowy → błąd zamiast
  pominięcia), przesuwanie jak w v0.1 (rysowanie ramek przez
  `requestAnimationFrame`) przy 4500–5000 obrysach — także z podglądem
  roku włączonym (informacyjnie); pomiar SMB dla pierwszego kafla
  i COG z magazynu na udziale; pamięć serwera i procesów renderujących.
  Jeśli cel nie jest spełniony: pomiar składowych (czas JS, liczba
  wierzchołków, styl warstw), poprawka i ponowny pomiar — bez obniżania
  progów.
- **Pliki:** `tests/perf/test_store_50k.py`, `tests/perf/test_previews_perf.py`,
  `tests/perf/test_own_data_perf.py`, `tests/fixtures/browser.py` (flagi
  GPU, CDP), `docs/reports/v0.2-measurements.md`.
- **Interfejs:** zmienne `ARCHIWISTA_PERF_STORE`, `ARCHIWISTA_SMB_STORE`,
  `ARCHIWISTA_SMB_WORK` (v0.1), nowe `ARCHIWISTA_BROWSER_CDP`,
  `ARCHIWISTA_REQUIRE_GPU`; pomiary z `--no-cov`.
- **Test/odbiór:** `.venv/bin/python -m pytest -m perf tests/perf --no-cov
  -s -rs` (SSD) i `-m smb` (udział); `ARCHIWISTA_REQUIRE_GPU=1` dla
  `test_store_50k_map_5000_outlines_frame_rate` na komputerze odniesienia
  z dostępem do GPU; raport: sprzęt, sterownik i renderer WebGL, wersje,
  warunki, p95, klatki/s i p95 klatki, RSS, rozmiar indeksu i pamięci
  podglądów, każdy cel z decyzji 12 z oceną.
- **Zależności:** 3, 6, 7b, 8, 11, 12b. **Równolegle:** 13–15, 17.

### 17. E2E i odbiór v0.2
- **Cel:** przejście odbiorcze na prawdziwym `archiwista serve`
  i magazynie testowym offline: Karta pliku z podglądami i powodami →
  mapa z podglądem roku → Wachlarz → Oś czasu → Porównanie z kurtyną →
  projekt z danymi własnymi → migawka GeoPackage w edycji → zmiana →
  „zmieniony od migawki” → druga migawka → ta sama treść → „bez zmian”;
  magazyn zamontowany tylko do odczytu (podglądy działają, magazyn bez
  zmian — pamięć lokalna); odłączony udział (podglądy z pamięci);
  bez żądań poza serwer, bez błędów strony i naruszeń CSP; test na żywo
  podglądów na magazynach testu na żywo Kartografa 0.8.0 z tabelą
  rozszerzenie → wynik; zrzuty do raportu.
- **Pliki:** `tests/e2e/test_acceptance_v02.py`,
  `tests/integration/test_live_previews.py` (`-m live`),
  `docs/reports/v0.2-screenshots/`.
- **Interfejs:** fixtury `serve`, `tab` z v0.1; `ARCHIWISTA_LIVE_STORE`.
- **Test/odbiór:** `.venv/bin/python -m pytest tests/e2e -m 'not live'`;
  `ARCHIWISTA_LIVE_STORE=<udział>/kartograf/release-0.8.0/data
  .venv/bin/python -m pytest -m live tests/integration/test_live_previews.py
  --no-cov`; `test_acceptance_v02_walkthrough`,
  `test_acceptance_v02_read_only_store_previews`,
  `test_acceptance_v02_disconnected_share_serves_cached_previews`.
- **Zależności:** 12a–15. **Równolegle:** 16.

### 18. Dokumentacja, bramka i wydanie 0.2.0
- **Cel:** `README.md` (zależności podglądów, folder danych, migawki,
  pamięć podglądów, instalacja Kartografa z `develop` zamiast usuniętej
  gałęzi), `docs/CHANGELOG.md` (`[0.2.0]`, w tym przebudowa
  indeksu po aktualizacji przez nową wersję schematu i pełny skan przy
  starcie), `docs/USAGE.md` (Wachlarz, Oś czasu, Porównanie, dane własne
  i migawki ze zrzutami), `docs/AGENT_API.md` (`ref`, podglądy z CSRF,
  `preview --output`, porównanie, warstwy, dane własne, plan i migawka,
  kody błędów), `docs/ARCHITECTURE.md` (nowe moduły, procesy, dane
  lokalne, przepływy, bezpieczeństwo, punkty rozszerzeń), SPEC (4.5 —
  wiersze v0.2; 4.7.1 — nazwy, schemat, problem w projekcie zamiast
  „Magazynu”; 5.1 — renderowanie poza serwerem; 5.7 — tabela z decyzji 5;
  9.2 — nowe trasy; 10.1 — sandbox i dostarczanie podglądów; 13 —
  bramka v0.2), `docs/DECISIONS.md` (erraty: A-ADR-008 — procesy
  renderujące, wymuszona operacja w kaflach, dostarczanie przez API;
  A-ADR-027 — nazwy i `archiwista-snapshot/1`; A-ADR-029 —
  `project.write`), `docs/SCOPE.md` (bramka etapu 3), `docs/PROGRESS.md`;
  wersja pakietu 0.2.0; raport bramki w
  `docs/reports/v0.2-measurements.md`.
- **Interfejs:** dokumentacja wyników kroków 3–17; bez opisu
  niezaimplementowanych przycisków.
- **Test/odbiór:** bramka w `.venv`: `pytest` (domyślnie bez `live`,
  `perf`, `smb`; z Playwright offline) z `--cov-fail-under=80`,
  `ruff check .`, `ruff format --check .`, `mypy archiwista/ tests/`,
  `pip-audit` na `requirements.lock`, przejście `archiwista serve`
  w przeglądarce; wydanie tylko po odnotowaniu wyniku *każdego* wiersza
  bramki niżej. Bez tagu i scalenia do `main` bez decyzji użytkownika.
- **Zależności:** 0–17. **Równolegle:** —.

## Bramka SPEC 13 v0.2: dowód dla każdego kryterium

| Kryterium SPEC 13 v0.2 | Dowód wymagany przed zamknięciem v0.2 (krok-właściciel) |
|---|---|
| 1. Każdy typ pliku przykładowego magazynu ma podgląd albo podany powód braku | `tests/integration/test_preview_coverage.py::test_every_store_file_type_has_preview_or_reason` (6; magazyn testowy z rodzinami kroku 2: każda wersja ma `PreviewInfo` w stanie `ready` z dekodowalną miniaturą albo `unavailable`/`needs_build` ze znanym kodem `reason` i polskim opisem; po `POST …/preview` każde `needs_build` ≤ 2 GB kończy się `ready`), `tests/integration/test_live_previews.py::test_live_store_file_types_have_preview_or_reason` (17; `-m live` na magazynach testu na żywo Kartografa 0.8.0; tabela rozszerzenie → wynik w raporcie: `tif`, `gpkg`, `jgw`, `asc`, `zip`, `png`, `laz`, `jpg`) i `tests/integration/test_own_data_api.py::test_own_file_types_have_preview_or_reason` (9; dane własne). |
| 2. Obrysy CZ zgodne z rzeczywistością (punkt kontrolny na styku PL/CZ, odchyłka ≤ 2 m) | `tests/integration/test_cz_control_point.py` z punktem 3722 (decyzja 4): `::test_cz_outline_vertex_within_2_m` (3; wierzchołek obrysu w `/map/footprints`), `::test_cz_preview_tile_within_2_m` (5a; kafel z = 19), `::test_cz_features_within_2_m` (5b; obiekt w `features`); odchyłki zapisane w raporcie. |
| 3. Ten sam plik nie jest przeliczany drugi raz | `tests/integration/test_preview_cache.py::test_same_content_rendered_once` (6; dwie wersje o tym samym `sha256`, powtórzenia, restart serwera — liczba żądań procesów renderujących bez zmian) i `tests/integration/test_jobs.py::test_preview_build_joins_running_job` (4; druga budowa tej samej treści dołącza do zadania, zbudowany COG nie powstaje ponownie). |
| 4. Limit pamięci podglądów przestrzegany | `tests/integration/test_preview_cache.py::test_cache_limit_evicts_least_recently_used` i `::test_cache_limit_holds_with_builds` (4; limit 1 MB, suma ≤ limit po każdym zapisie, usuwane najdawniej używane, chronione w budowie) i zajętość pamięci w pomiarach kroku 16. |
| 5. Mapa z 5000 obrysów płynna (≥ 30 klatek/s na komputerze odniesienia) | `tests/perf/test_store_50k.py::test_store_50k_map_5000_outlines_frame_rate` (16; `-m perf`, `ARCHIWISTA_REQUIRE_GPU=1`, renderer WebGL sprzętowy; obrysy-wielokąty z kroku 3; średnio ≥ 30 klatek/s przy 4500–5000 obrysach; p95 klatki i renderer w raporcie). Bez dostępu do GPU (decyzja 1) — kryterium niezamknięte. |
| 6. Folder projektu z GeoPackage, Shapefile i GeoTIFF zaindeksowany z zasięgiem i podglądem | `tests/integration/test_own_scan.py::test_folder_with_gpkg_shp_geotiff_indexed_with_extent` (7b), `tests/integration/test_own_data_api.py::test_folder_with_gpkg_shp_geotiff_indexed_with_extent_and_preview` (9) i `tests/e2e/test_own_data.py::test_project_own_data_on_map_and_card` (15). |
| 7. Migawka GeoPackage otwartego do edycji w QGIS daje spójną kopię (test integralności SQLite) | `tests/integration/test_snapshots.py::test_gpkg_open_for_editing_snapshot_is_consistent` (8; `GpkgEditor` w WAL: zatwierdzone ramki w `-wal` i otwarta transakcja; `PRAGMA integrity_check` = `ok`, zatwierdzone wiersze są, niezatwierdzone nie, pyogrio czyta kopię). QGIS nie jest zainstalowany na komputerze odniesienia — test odtwarza jego sposób pracy; ręczne potwierdzenie w QGIS u użytkownika opisane w raporcie jako zalecane, nie jako dowód. |
| 8. Przerwanie migawki nie zostawia częściowej wersji | `tests/integration/test_snapshots.py::test_interrupted_snapshot_leaves_no_partial_version` (8; przerwanie w każdej fazie przez `fault`, SIGINT i SIGKILL procesu roboczego) i `tests/integration/test_own_scan.py::test_stale_incoming_problem_after_24h` (7b). |
| 9. Ta sama treść nie tworzy drugiej migawki | `tests/integration/test_snapshots.py::test_same_content_makes_no_second_snapshot` (8; ponowna migawka bez zmian, GeoPackage po VACUUM i punkcie kontrolnym, A → B → A) i `tests/e2e/test_own_data.py::test_same_content_shows_unchanged_notice` (15). |
| 10. Zmiana pliku po migawce jest wykryta | `tests/integration/test_own_scan.py::test_change_after_snapshot_detected` (7b; GeoPackage, Shapefile, GeoTIFF; historia stanów) i `tests/e2e/test_own_data.py::test_changed_since_snapshot_badge` (15). |

Zakres v0.2 i warunki ogólne (SPEC 11, 13 „Zakres”; A-ADR-029):

| Obszar | Dowód (krok-właściciel) |
|---|---|
| Wachlarz i Oś czasu dla danych lokalnych | `tests/integration/test_local_layers.py` (11) i `tests/e2e/test_fan_timeline.py` (13: najnowsza na górze, miniatury bez nakładania, wybrana w całości i powiększona, wybór zsynchronizowany, lata bez danych, 1440, 3440 i 390 px). |
| Porównanie metadanych i kurtyna (8.5, poziomy 1 i 2) | `tests/integration/test_compare.py` (10) i `tests/e2e/test_compare.py` (14: tabela różnic, kurtyna, przenikanie, widoki obok siebie, dwie warstwy lat). |
| Uprawnienia danych własnych i migawek | `tests/unit/test_authorize.py::test_project_write_matrix` i `tests/integration/test_permissions_api.py::test_own_data_visibility_matrix` (9). |
| Agent: HTTP = CLI | `tests/integration/test_cli.py::test_preview_cli_equals_http`, `::test_own_data_cli_equals_http`, `::test_compare_cli_equals_http`, `::test_layers_cli_equals_http` (6, 9–11) i `tests/integration/test_agent_flow.py::test_agent_snapshot_flow` (9). |
| Bezpieczeństwo podglądów i odczytu danych własnych | `tests/integration/test_preview_security.py` (6), `tests/integration/test_render_pool.py::test_worker_env_has_no_network`, `::test_vrt_driver_refused`, `::test_timeout_kills_and_respawns_worker`, `::test_memory_limit_kills_worker` (4), `tests/unit/test_sandbox.py` (1) i `tests/integration/test_own_reader.py::test_data_folder_unchanged_after_reads` (7a). |
| Regresja v0.1 (kryteria 1–9 v0.1, SPEC 4.5) | bramka `pytest` z testami v0.1, `tests/perf/test_store_50k.py` (16: skany, odświeżenie widoku, p95, RSS i indeks z obrysami-wielokątami) i `tests/integration/test_live_store.py` (`-m live`). |
| Cele planu (decyzja 12) | `tests/perf/test_previews_perf.py` i `tests/perf/test_own_data_perf.py` (16); liczby z warunkami w `docs/reports/v0.2-measurements.md`. |
| Dowód działania w przeglądarce (SPEC 11) | `tests/e2e/test_acceptance_v02.py::test_acceptance_v02_walkthrough` (17) na prawdziwym `archiwista serve`; zrzuty w `docs/reports/v0.2-screenshots/`. |

## Ryzyka i blokady

- **Dostęp do GPU.** Kryterium 5 wymaga WebGL sprzętowego (decyzja 1);
  konto pomiarowe nie ma dziś dostępu do `/dev/dri/renderD128`. Bez decyzji
  właściciela komputera (grupa `render` albo pomiar przez CDP w jego
  sesji) kryterium zostaje otwarte — nie zastępuje go wynik programowy.
  Chromium może odrzucić `nouveau` mimo flag; wtedy droga (b) albo
  sterownik NVIDIA (decyzja właściciela). Jeśli GPU nie da 30 klatek/s,
  najpierw pomiar składowych w kroku 16.
- **Wymuszona operacja w kaflach.** rio-tiler nie przeniesie
  `COORDINATE_OPERATION` przez `WarpedVRT` (decyzja 4), więc kafle
  przeliczane czyta własny kod na `rasterio.warp.reproject`. Ryzyko
  wolniejszych kafli dla plików bez nakładek — dlatego COG z nakładkami
  (decyzja 6) i pomiary w kroku 16; próba kroku 1 rozstrzyga, zanim
  powstanie renderer.
- **Spójny odczyt SQLite.** Otwarcie `mode=ro` bazy w WAL bez `-shm`,
  blokady SQLite na udziale SMB i różnice zachowania QGIS. Ograniczenia:
  kopia zapasowa do pliku lokalnego, `immutable=1` tylko bez `-wal` ze
  stanem przed i po, `PRAGMA integrity_check`, próba w kroku 1. QGIS nie
  jest zainstalowany na komputerze odniesienia: test odtwarza zapis QGIS
  (WAL, otwarta transakcja); ręczna próba w QGIS — zalecana przy
  odbiorze u użytkownika.
- **Koszt skrótu logicznego.** Odczyt wszystkich wierszy dużego
  GeoPackage przy każdej zmianie (skan, migawka). Ograniczenia: tylko pliki
  zmienione (stan pliku i `-wal`), skrót migawki liczony na jej kopii,
  pomiar w kroku 16 (cel: migawka 100 MB ≤ 15 s).
- **Wyciek przez nowe powierzchnie.** Dane własne w podglądach,
  porównaniu, warstwach, filtrze `project` i CLI. Ograniczenia: jeden
  punkt przejścia `ref` → plik (`ObjectResolver`), zapytania z wymaganym
  `visible`, dane własne poza `/slots` i `/map/footprints`, pamięć
  podglądów bez nazw, macierz widoczności rozszerzona o każdą nową trasę
  (krok 9).
- **GDAL na niezaufanym wejściu.** Pliki użytkownika mogą zawieszać albo
  wywracać biblioteki natywne i odsyłać do innych plików (VRT). Ograniczenia:
  procesy z sandboxem, limity czasu i pamięci, `GDAL_SKIP`, brak sieci,
  testy z uszkodzonymi plikami; serwer nie otwiera plików danych.
- **Zależności natywne.** rio-tiler (numexpr, color-operations) i lazrs
  (Rust) to koła binarne; lock z sumami, `pip-audit` w bramce, licencje
  w kroku 1; Windows — v1.0.
- **Kartograf bez tagu `v0.8.0`.** API odczytu jest na `develop`
  Kartografa (gałąź `feat/archiwista-store-api` scalona i usunięta);
  instalacja edytowalna z `develop`, test kontraktu (także
  `gdal_operation`) przy każdej zmianie Kartografa. Kartograf rozwija
  osobny zespół — Archiwista nie zmienia jego kodu.
- **Przebudowa indeksu po aktualizacji.** Nowa wersja schematu (kroki 3
  i 7b) to pełny skan przy pierwszym starcie (SSD ok. 50 s, SMB ok. 4 min;
  pomiary v0.1); baza stanu bez zmian. Opis w CHANGELOG i README.
- **Rozmiar pamięci podglądów i czas budowy.** Wachlarz wielu lat z
  arkuszami ASC to setki budów COG. Ograniczenia: limit 20 GB z LRU, COG
  ≤ 8192 px, jedna budowa na warstwę (≤ 500 wersji) z postępem, budowy
  tylko dla warstw oglądanych, pliki > 2 GB tylko na żądanie.
- **Georeferencja JPEG z obrysu.** Działa dla plików świata bez obrotu
  (ortofoto CZ); obrót albo obrys spoza nagłówka → miniatura bez mapy
  (`no_georeference`), a ewentualne wymaganie dokładnej georeferencji —
  do SPEC 12 po v0.2 (decyzja 2).
- **Presja zakresu z mockupu.** Różnica obiektów migawek, lata niepobrane
  z WMS, plakietki „pobrane”, asystent i mozaika są w mockupie, ale poza
  v0.2 (decyzja 14); każda z tych rzeczy wymaga osobnej decyzji
  użytkownika.
- **Przyrost migawek w katalogu projektu (PRD).** Rozmiar w planie
  migawki, zajętość migawek w widoku projektu; usuwanie tylko ręcznie
  poza Archiwistą.
- **Środowiska pomiarowe.** Udział SMB, magazyny testu na żywo i GPU
  wymagają jawnych `<katalog-danych>` i decyzji właściciela; brak
  środowiska oznacza niezamknięte kryterium, nie automatyczny sukces.
