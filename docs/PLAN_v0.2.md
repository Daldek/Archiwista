# Plan implementacji v0.2 „Podglądy”

**Status:** wykonany plan wydania 0.2.0 (2026-10-20); kroki 0–18
zakończone, odbiór i pomiary w `docs/reports/v0.2-measurements.md`.
Kryterium ≥ 30 klatek/s z GPU pozostaje niezweryfikowane (brak dostępu
do sprzętowego WebGL na komputerze odniesienia). Spec i plan v0.3
powstają przed jego implementacją. Wzór i umowy v0.1:
`docs/PLAN_v0.1.md`; kod wydania: `docs/ARCHITECTURE.md`. Po każdym
kroku zapisano „Stan po kroku N” (commit, odstępstwa i wyniki prób).
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
   z ext4; udział SMB 3 `//<smb-host>/<scratch-dir>`). Karta graficzna:
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
     OGR, laspy ani `zipfile`. Miniatury, kafle, obiekty wektorowe, listy
     członów ZIP oraz miniatury i kafle warstw liczy pula długowiecznych
     procesów renderujących (`python -P -m archiwista.previews.worker`,
     domyślnie `min(4, cpu)`), zabijanych i uruchamianych od nowa po
     przekroczeniu czasu (rozpoznanie 20 s, kafel i kafel warstwy 15 s,
     obiekty 15 s, człony ZIP 10 s, miniatura 30 s, miniatura warstwy
     60 s) albo limitu pamięci (`RLIMIT_AS` 2 GiB, `GDAL_CACHEMAX` 256 MB;
     na Linuksie — Windows w v1.0). Kolejka żądań ma ≤ 64 miejsca (potem
     `503 preview_busy` z `Retry-After`), identyczne żądania liczą się raz
     (jedno renderowanie na klucz), a żądanie porzucone przez przeglądarkę
     (przesunięta mapa) wypada z kolejki przed renderowaniem. Budowa
     lokalnego COG (decyzja 6) to zadanie w tle `preview` (A-ADR-007), każdy
     plik w osobnym procesie potomnym z limitem 10 min i 4 GiB; zadanie
     buduje najwyżej `n = max(1, cpu // 2)` plików naraz (2 na komputerze
     odniesienia — cele decyzji 12 liczą się z tym `n`), a trwa najwyżej
     jedno zadanie `preview` (kolejne czekają jak zadania sieciowe v0.1).
     Samo zadanie zajmuje jedno miejsce `default_max_jobs()`, a procesy
     budowy nie zajmują kolejnych, żeby migawka i skan nie czekały na
     podglądy (na 4 CPU zostają 2 rdzenie na serwer, procesy renderujące
     i drugie zadanie).
   - *Sandbox.* Moduł `archiwista/sandbox.py` daje środowisko wszystkim
     procesom czytającym pliki (także czytnikowi obszarów v0.1 — jedna
     implementacja zamiast kodu w `areas.py`): minimalne zmienne bez
     pośredników i poświadczeń, `PROJ_NETWORK=OFF`, `GDAL_HTTP_PROXY` na
     zamknięty port, `GDAL_PAM_ENABLED=NO` (bez `GDAL_PAM_PROXY_DIR`:
     statystyki GDAL zapisują `<plik>.aux.xml` obok danych — sprawdzone
     2026-10-19 na `statistics()` rasterio — co w magazynie łamie „tylko do
     odczytu”, a w folderze danych daje nowy plik dla następnego skanu),
     `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` (GDAL nie widzi plików obok:
     `.ovr`, `.msk`, `.aux.xml`, plików świata), `umask 077` i `GDAL_SKIP`
     sterowników odsyłających do innych plików albo sieci (`VRT`,
     `OGR_VRT`, `GTI`, `WMS`, `WMTS`, `WCS`, `WFS`, `OAPIF`, `OGCAPI`,
     `STACIT`, `STACTA`, `PDS`, `PDS4`, `ISIS3`, `ERS`, `ENVI`, `EHdr`,
     `GML`; lista w `sandbox.py` i w teście). `GDAL_SKIP` jest tylko drugą
     linią obrony: pierwszy `WarpedVRT` w procesie (rio-tiler) rejestruje
     sterownik VRT ponownie, a wtedy plik z treścią VRT czyta
     `<SourceFilename>` dowolnego pliku serwera — także jako nakładka
     `a.tif.ovr` przy `rasterio.open("a.tif", driver="GTiff")` (sprawdzone
     2026-10-19 w `.venv`: rasterio 1.5.2, GDAL 3.12). Dlatego: (a) plik
     główny otwiera się zawsze jawnym sterownikiem z tabeli formatów
     (`archiwista/formats.py`; rozszerzenia z decyzji 5): rastry
     `rasterio.open(path, driver=…)` (`GTiff`, `AAIGrid`, `XYZ`, `JPEG`,
     `PNG`), a rio-tiler dostaje otwarty zbiór (`Reader(path,
     dataset=src)`), nigdy samą ścieżkę; wektory z prefiksem sterownika
     tam, gdzie GDAL go ma (`GPKG:`, `GeoJSON:`), a Shapefile i FlatGeobuf
     (bez prefiksu w GDAL 3.12 — sprawdzone) po sprawdzeniu sygnatury
     pliku (`.shp`: kod 9994, `.fgb`: `fgb\x03fgb`); MapInfo `.tab` tylko
     jako tabela natywna — widok i tabela łączona (`\IsSeamless`) odsyłają
     do innych plików, więc → `unsupported_format`; (b) `EMPTY_DIR` zamyka
     nakładki i maski z plików obok (sprawdzone: po `WarpedVRT`
     `a.tif.ovr` nie jest czytany, a Shapefile dalej czyta `.dbf`
     i `.prj`). Skutek: georeferencja rastra tylko z samego pliku
     (GeoTIFF, nagłówek ASC z `EntryMeta.horizontal_crs`, JPEG z obrysu
     nagłówkowego — decyzja 2); raster danych własnych z samym plikiem
     świata → `no_georeference` z zaleceniem zapisu jako GeoTIFF. Plik
     użytkownika nie wskaże innego pliku serwera ani adresu.
   - *Pamięć podglądów.* `<katalog danych>/previews/` (prawa `0700`, nigdy
     na udziale ani w magazynie): obiekty po treści
     (`objects/<klucz[:2]>/<klucz>/<renderer>-r<wersja>/`: `info.json`,
     `cog.tif`, miniatury, kafle; wersja osobno dla każdego renderera —
     `raster`, `vector`, `points`, `archive`, `document`, `composite` —
     więc poprawka renderera wektorów nie unieważnia COG rastrów)
     i rozliczenie LRU w `previews/cache.sqlite` (pamięć podręczna:
     usunięcie katalogu daje pustą pamięć). Limit z ustawienia
     `preview_cache_limit_gb` (domyślnie 20, SPEC 5.7); po zapisie ponad
     limit znikają najdawniej używane obiekty do 90% limitu, z wyjątkiem
     obiektów w budowie (mechanika: umowa „Pamięć”). Klucz: treść, wersja
     renderera, styl i parametry (rozmiar, kadr, `rescale`). Treść to
     `sha256` wersji magazynu; wersja bez `sha256` w sidecarze (starsze
     sidecary, wersja bez sidecara) ma klucz `sha256("path:" + magazyn +
     ":" + ścieżka wersji + ":" + rozmiar + ":" + czas modyfikacji)` —
     wersje są niezmienne, więc klucz jest poprawny, tylko bez
     współdzielenia z kopiami tych bajtów (A-ADR-008 errata 3); dane
     własne — tożsamość treści z decyzji 8 (skrót logiczny SQLite bez
     R*Tree: plik o tej samej treści logicznej z innym albo uszkodzonym
     indeksem przestrzennym dostaje te same podglądy — spójność pliku to
     sprawa właściciela folderu, A-ADR-029 pkt 1). Obiekty złożone
     (miniatura i kafel warstwy) mają klucz `sha256("composite:" +
     operacja + posortowane treści gotowych wersji + kadr albo kafel +
     styl + rozmiar)`. Wersje magazynu są niezmienne, a każda zmiana kodu
     renderera podnosi jego wersję, więc pamięć nigdy nie jest
     nieaktualna; te same bajty w dwóch wersjach, dwóch magazynach albo
     w migawce i pliku roboczym liczą się raz. Rozpoznanie zakończone
     błędem: `unreadable` trafia do `info.json` jako sam kod (komunikat
     biblioteki dostaje tylko żądanie, które go wywołało, bez ścieżek —
     niżej); `timeout` i `memory_limit` zależą od obciążenia, więc nie
     trafiają do pamięci — serwer pamięta je 10 min w pamięci procesu,
     żeby powtórne żądanie nie zabijało procesu renderującego od nowa.
   - *Uprawnienia przed pamięcią.* Każde żądanie najpierw rozstrzyga obiekt
     (`ref`, decyzja 10) i dostęp do niego: magazyn centralny widzą
     wszyscy, dane własne i migawki — wyłącznie przez projekt widoczny dla
     principala (`visible_projects`; niewidoczny → `404 not_found`). Dopiero
     potem sięga do pamięci. Pamięć współdzieli bajty równych treści
     między projektami, ale nic nie ujawnia: aby trafić w obiekt, trzeba
     już wskazać widoczny plik o tej samej treści. Obiekty pamięci nie
     niosą nazw ani ścieżek (`PreviewProbe` bez nazw plików, `unreadable`
     jako sam kod), komunikaty błędów wychodzą z procesu renderującego bez
     ścieżek (`worker.py` zamienia ścieżki źródła i ich katalogi na nazwę
     pliku — inaczej komunikat GDAL z `/home/ola/projekty/…` trafiłby do
     osoby z innego projektu z tymi samymi bajtami), a `/health` podaje
     tylko liczby. Zadania z danymi projektu widać tylko przez widoczny
     projekt (umowa „Zadania”). Tak plan realizuje „klucze pamięci
     podglądów danych własnych zależne od widoczności” (plan v0.1, krok 8b)
     i A-ADR-029 pkt 3.
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
     (A-ADR-008) służy do miniatur w układzie pliku (z otwartego zbioru —
     decyzja 3), kolorowania i kodowania PNG (`ImageData`); statystyki
     (p2, p98, min, max) liczy numpy z odczytu zdziesiątkowanego, nie GDAL
     (decyzja 3: `.aux.xml`). Próba techniczna kroku 1 potwierdza obie
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
     pliku — ta sama operacja odwrotnie, po zagęszczeniu krawędzi. Przed
     przeliczeniem geometrie upraszcza się do ok. 1 piksela przy zoomie
     żądania (parametr `zoom`; `shapely.simplify(tolerance = rozmiar
     piksela / 2, preserve_topology=False)` w jednostkach układu pliku) —
     przepróbkowanie tylko do wyświetlenia (SPEC 5.7) — a odpowiedź ma
     najwyżej 5000 obiektów i 500 000 wierzchołków razem (więcej →
     `truncated: true` i „Przybliż albo otwórz w QGIS”); bez tego
     GeoPackage BDOT10k albo PRG przy małym zoomie to setki MB, wbrew
     A-ADR-018 („podglądy lekkie”).
   - *Miniatury warstw* (Wachlarz) proces renderujący składa w układzie
     płaskim obszaru (PL → EPSG:2180, CZ → EPSG:5514, jak pokrycie lokalne)
     z wymuszoną operacją. *Kafle warstw* (podgląd roku na mapie, decyzja
     7) składa ten sam proces: kafel EPSG:3857 warstwy to nałożenie (alfa,
     od najstarszej do najnowszej) kafli wersji, które go przecinają —
     z pamięci po treści wersji (A-ADR-008 errata 2), a brakujące liczy
     tym samym kodem co kafel wersji.
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
   | GeoPackage (BDOT10k, PRG, EGiB, PRNG, HYNET, osnowa) | warstwy z typem geometrii, liczba obiektów, schemat, próbka 20 wierszy, miniatura do 3 największych warstw (≤ 50 000 obiektów każda) | obiekty w widoku jako GeoJSON WGS84 uproszczone do zoomu, ≤ 5000 obiektów i ≤ 500 000 wierzchołków, powyżej „Przybliż albo otwórz w QGIS” | magazyn: otwarcie niezmienne (`immutable=1`, SPEC 4.6 pkt 4); dane własne: trzy stany pliku SQLite (decyzja 8) |
   | Shapefile, GeoJSON, FlatGeobuf, MapInfo TAB (dane własne) | jak GeoPackage | jak GeoPackage | brak układu (np. bez `.prj`) → miniatura w układzie pliku bez mapy, `no_crs`; TAB jako widok albo tabela łączona → `unsupported_format` |
   | LAZ/LAS (chmury GUGiK) | nagłówek (zasięg, liczba punktów, format, gęstość), histogram klas ASPRS z próbki ≤ 2 mln punktów i ≤ 256 MiB rozpakowanych rekordów, obraz 2D (maks. Z w siatce) | kafle z lokalnego COG obrazu 2D | plik bez tablicy kawałków: próbka z początku pliku, z dopiskiem |
   | ZIP (BDOT10k SHP, modele 3D LOD2, EGiB, PRG kraju) | lista członów z rozmiarami i rozpoznanym formatem (≤ 10 000, bez rozpakowania) | — | `archive_members_only` (podgląd SHP i GML przez `/vsizip/` — później, SPEC 5.7); katalog centralny > 100 000 wpisów albo > 64 MiB → `too_large` przed `ZipFile` |
   | PDF, TXT | metadane (rozmiar, typ) | — | `document_no_preview`: PDF w przeglądarce wymaga dostarczania plików (`/file`, tryb zespołu v0.4); ścieżka do skopiowania |
   | inne, nierozpoznane | metadane | — | `unsupported_format` |

   Dla każdej rodziny: plik > 2 GB, a raster także > 1 Gpx albo > 8 GiB po
   rozpakowaniu → stan `needs_build` bez budowy automatycznej („Zbuduj
   podgląd”, SPEC 5.7; decyzja 6); wersja „brak pliku” → `missing_file`;
   wersja bez `sha256` — podgląd pod kluczem ścieżki (decyzja 3); magazyn
   odłączony → podgląd z pamięci, a bez niej `store_unavailable`; układ
   bez przypiętej operacji → `transform_unavailable` (miniatura bez mapy);
   raster danych własnych z samym plikiem świata → `no_georeference`
   (decyzja 3); błąd odczytu → `unreadable` (z komunikatem biblioteki bez
   ścieżek); przekroczony czas → `timeout`; limit pamięci → `memory_limit`.
6. **Lokalny COG i duże pliki.** COG w pamięci podglądów powstaje dla ASC,
   XYZ, JPEG z georeferencją z obrysu, GeoTIFF paskowego albo bez nakładek
   z bokiem > 4096 px i dla obrazu 2D LAZ: najdłuższy bok ≤ 8192 px
   (A-ADR-018: podgląd lekki), uśrednianie dla wartości ciągłych,
   `nearest` dla klas, nakładki wewnętrzne, kompresja DEFLATE (wartości
   ciągłe z predyktorem) albo JPEG (RGB), odczyt zdziesiątkowany. Plik
   ≤ 2 GB — a raster tylko ≤ 1 Gpx i ≤ 8 GiB po rozpakowaniu (szerokość ×
   wysokość × kanały × bajty typu; kilka MB DEFLATE może deklarować
   100 000 × 100 000 px) — interfejs zleca do budowy sam przy pierwszym
   podglądzie; większy czeka na „Zbuduj podgląd” (`POST …/preview`
   z `force: true`). Budowa jest idempotentna: zlecenie
   treści już budowanej dołącza do trwającego zadania (`202` z tym
   zadaniem), zbudowanej — odpowiada `200` z opisem podglądu. COG nigdy nie
   jest produktem danych: leży tylko w pamięci podglądów i nie ma ścieżki
   „do skopiowania”.
7. **Warstwy lat i kampanii z danych lokalnych (Wachlarz, Oś czasu,
   mapa).** Warstwa = wariant × rok danych (`data_year`, nigdy rok
   pobrania); wersja bez roku trafia do warstwy swojego wydania albo
   etykiety. Wariant jest bez formatu plików (A-ADR-017, SPEC 6.4): klucz
   (`product`, `horizontal_crs`, `resolution`, `vertical_crs`) z pól
   `EntryMeta` w indeksie, więc segmenty jednego zestawu w dwóch
   formatach (np. `nmt/pl_1992_1m_evrf2007` z ASC
   i `nmt/pl_1992_ascii-nmt_1m_evrf2007`) dają jedną warstwę z formatami
   jako plakietkami (`formats`), a nie dwa wiersze Osi czasu, dwie
   miniatury Wachlarza i podwójne liczniki; gdy któregoś pola brak,
   kluczem jest segment (Archiwista nie rozbiera nazw segmentów). Parametr
   `group=campaign` dzieli rok na kampanie (`campaign`). Warstwa niesie
   wersje slotów obszaru (≤ 500, po odświeżeniu widoku jak
   `/local-coverage`), stan lokalny („lokalnie 83% obszaru”, w układzie
   płaskim), obrysy w układzie płaskim obszaru (do SVG) i miniaturę
   złożoną z podglądów arkuszy (A-ADR-008 errata 2: kafel na wersję,
   pamięć po `sha256`; brakujące zostają obrysami, a ich budowa idzie
   jednym zadaniem `preview` na warstwę z postępem). Bez obszaru Oś czasu
   pokazuje liczby wersji per rok i wariant. Na mapie podgląd roku to
   jedno źródło rastrowe warstwy: `GET /local-layers/tiles/{z}/{x}/{y}.png`
   składa kafel z kafli wersji w procesie renderującym (decyzja 4), więc
   przesunięcie mapy to jedno żądanie na kafel widoku — osobne źródło na
   wersję dawałoby przy 200 arkuszach 200–800 żądań na przesunięcie wobec
   kolejki 64 miejsc (`503` bez ponowienia w MapLibre) i 6 połączeń
   przeglądarki na pochodzenie. Źródło warstwy ma `minzoom`, od którego
   typowy arkusz warstwy ma ≥ 32 px (kafel obejmuje wtedy najwyżej ok.
   9 × 9 arkuszy); niżej — same obrysy i „Przybliż, aby zobaczyć
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
     projektów (plik należy do jednego projektu, więc do jednej
     widoczności) i z katalogami Archiwisty; porównanie po `realpath`.
     Tylko administrator, bo folder jest miejscem zapisu migawek;
     ustawianie przez właściciela projektu — decyzja w v0.4 (odstępstwo od
     A-ADR-029 pkt 2, zapisane jako jego errata 1). Te same reguły (bez
     wymogu istnienia) obowiązują folder domyślny: projekt z manifestem
     w katalogu producenta (SPEC 4.6 pkt 7: `output_dir` względny wobec
     manifestu) miałby `dane/` w magazynie. Skan i migawka sprawdzają
     folder przed każdym użyciem; folder poza regułami ma stan `invalid`
     z problemem `own_folder_invalid` (powód `inside_store`,
     `inside_app_data` albo `overlaps_project`), nie jest czytany,
     a migawka kończy się `snapshot_blocked` z powodem `folder_invalid`.
     Folder zawierający folder innego projektu albo w nim leżący jest
     `invalid` dla obu projektów.
   - *Odczyt bez zapisu.* Zadanie `own_scan` (z harmonogramu co
     `scan_interval_local_min` — wszystkie projekty; na żądanie z widoku
     projektu albo z CLI — folder tego projektu) przechodzi folder
     z pominięciem katalogów i plików ukrytych (w tym `.wersje/` jako dane)
     i dowiązań symbolicznych wychodzących poza folder, najwyżej 10 000
     plików: z większego indeksuje pierwsze 10 000 w porządku ścieżki
     (ścieżka względna w NFC) i zgłasza problem `own_folder_too_large`.
     Całe przejście po jednym folderze ma także wspólne limity: 50 000 wpisów
     (włącznie z ukrytymi i `.wersje/`), 25 000 katalogów, głębokość 64
     i 10 000 migawek. Przekroczenie któregokolwiek zgłasza
     `own_folder_too_large`; skan przerywa niepełne przejście bez oznaczania
     niewidzianych w nim plików ani migawek jako brakujących. Dotychczasowy
     indeks pozostaje dostępny do kolejnego pełnego przejścia.
     Plik nowy albo zmieniony (rozmiar, czas modyfikacji, także pliku
     `-wal`) czyta proces czytnika
     (`python -P -m archiwista.owndata.reader`, sandbox i tabela formatów
     z decyzji 3, 30 s na plik, po przekroczeniu restart dla kolejnych):
     sterownik GDAL/OGR, warstwy z typem geometrii, liczba obiektów,
     schemat, układ, zasięg, parametry rastra. Shapefile i MapInfo TAB
     (tylko tabela natywna) są kompletem plików o tym samym rdzeniu nazwy;
     inne pliki — „nierozpoznane”. Folder po każdym odczycie jest bajtowo
     taki sam: nazwy, rozmiary i czasy plików danych i `-wal`, żadnych
     nowych plików (istniejący `-shm` to pamięć wspólna edytora — SQLite
     może zmienić jego treść). Plik SQLite (GeoPackage) czyta się według
     stanu (sprawdzone 2026-10-19: SQLite 3.46.1, GDAL 3.12): (a) bez
     `-wal` — w miejscu, niezmiennie (`immutable=1`, w GDAL
     `IMMUTABLE=YES`) ze stanem pliku przed i po; `mode=ro` odpada, bo
     przy bazie w trybie WAL (po edycji w QGIS) tworzy obok `-wal`
     i `-shm`; (b) `-wal` i `-shm` (plik otwarty w edytorze) — `sqlite3`
     w `mode=ro` (bez nowych plików) i `Connection.backup` (tylko
     zatwierdzone wiersze) do kopii w katalogu roboczym procesu; (c) `-wal`
     bez `-shm` (awaria edytora, skopiowany folder; bez `-shm` nie ma
     połączenia, które by pisało) — nigdy w miejscu: `mode=ro` tworzy
     `-shm` w folderze, `immutable=1` nie widzi wierszy z WAL, a GDAL
     w trybie odczytu przepisał WAL do pliku głównego; kopia bajtów pliku
     i `-wal` (stan przed i po, najwyżej 3 próby) do katalogu roboczego
     procesu i odczyt kopii. W stanach (b) i (c) GDAL czyta wyłącznie
     kopię — tak samo czytnik, renderer wektorów (kopia spójna jako
     `source.gpkg` obiektu tej treści w pamięci podglądów; plik > 2 GB →
     `needs_build`) i migawka.
   - *Tożsamość treści* (`content`: metoda i `sha256`; duplikaty migawek
     i wykrywanie zmian): `bytes` — SHA-256 pliku; `fileset` — SHA-256
     posortowanych wierszy `<nazwa członu małymi literami>\t<sha256>`
     kompletu; `sqlite` (GeoPackage i inne bazy SQLite) — skrót logiczny
     niezależny od układu stron, WAL i liczników nagłówka:
     `application_id`, `user_version`, posortowane wpisy schematu (bez
     tabel wewnętrznych `sqlite_%`, wirtualnych i ich tabel cieni — R*Tree
     to indeks pochodny) oraz wiersze każdej tabeli z wartościami z typem
     (tabela z `INTEGER PRIMARY KEY` w porządku klucza, `WITHOUT ROWID` —
     klucza głównego, pozostałe jako posortowany multizbiór wierszy).
     Tabele wirtualne i cienie rozpoznaje się z `sqlite_master`, nie
     z `PRAGMA table_list` (ta wymaga SQLite 3.37, a indeks dopuszcza
     3.35 — `MIN_SQLITE_VERSION`): wirtualna to wpis z `sql` od `CREATE
     VIRTUAL TABLE`, cienie — tabele `<wirtualna>_<przyrostek>`
     z przyrostkami jej modułu (`rtree`, `geopoly`: `_node`, `_parent`,
     `_rowid`; `fts3`, `fts4`: `_content`, `_segments`, `_segdir`,
     `_docsize`, `_stat`; `fts5`: `_data`, `_idx`, `_content`, `_docsize`,
     `_config`); tabele modułu nieznanego wchodzą do skrótu (zmiana ich
     treści to zmiana, nigdy przeoczenie). Poza skrótem są też dane
     pochodne, które OGR i QGIS przepisują przy otwarciu do zapisu bez
     zmiany danych: tabela `gpkg_ogr_contents` (licznik obiektów OGR)
     i znaczniki czasu zapisu `gpkg_contents.last_change` oraz
     `gpkg_metadata_reference.timestamp`. VACUUM, punkt kontrolny WAL,
     zapis bez zmian i otwarcie w QGIS bez edycji nie zmieniają skrótu;
     zmiana wiersza, schematu albo innej kolumny `gpkg_contents` —
     zmienia.
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
     A → B → A) — `<RRRR-MM-DD>_<sha8>_<n>`, n = 2, 3, …, pierwsze wolne
     według listingu `.wersje/<plik>/` tuż przed publikacją; kolejność
     serii wynika z `created_at`, nie z nazw. Katalog roboczy:
     `.wersje/.incoming/<host>_<pid>_<token>/` (ten sam system plików co
     cel, SPEC 4.7.1).
   - *Schemat `archiwista-snapshot/1`* (JSON w UTF-8, klucze po angielsku,
     daty ISO 8601 z przesunięciem, rozmiary w bajtach; model Pydantic
     `SnapshotDocument`: zapis dokładnie pól z tabeli, odczyt
     z `extra="ignore"` — pole dopisane przez nowszą Archiwistę nie czyni
     migawki `invalid_snapshot`, a pełny `migawka.json` zostaje w indeksie;
     nowe pole opcjonalne — ten sam `archiwista-snapshot/1`, nowe pole
     wymagane albo zmiana znaczenia pola — `archiwista-snapshot/2`; inny
     `schema` → problem `unknown_snapshot_schema`):

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
     1.2): folder ważny (decyzja 8, inaczej `folder_invalid`), plik, prawo
     zapisu do folderu, wolne miejsce ≥ 1,1 × rozmiar, tożsamość treści
     z ostatniego skanu wobec ostatniej migawki; (2) spójna kopia — SQLite
     według stanu z decyzji 8: (a) `Connection.backup` z połączenia
     `immutable=1` i porównanie stanu pliku przed i po, (b)
     `Connection.backup` z połączenia `mode=ro`, (c) kopia bajtów pliku
     i `-wal` do katalogu roboczego i `Connection.backup` z tej kopii (to
     wciąż kopia zapasowa SQLite, nie kopia bajtów przy otwartym WAL —
     SPEC 4.7.1 pkt 3) — zawsze do pliku roboczego w lokalnym katalogu
     roboczym procesu (SQLite nie pisze na udziale), potem kopia bajtów do
     `.incoming`; formaty wieloplikowe i pozostałe — kopia kompletu ze
     stanem (rozmiar, czas modyfikacji) każdego członu przed i po, najwyżej
     3 próby, inaczej błąd `inconsistent_copy` („plik zmieniał się
     w trakcie kopiowania — zakończ edycję i spróbuj ponownie”);
     (3) tożsamość treści kopii (`sqlite` liczona na kopii) i dla SQLite
     `PRAGMA integrity_check` = `ok`; ta sama treść co ostatnia migawka →
     wynik `unchanged` z jej etykietą, katalog roboczy usunięty, nic nowego
     w `.wersje/`; (4) `migawka.json`, ponowne policzenie sum zapisanych
     plików, pliki migawki tylko do odczytu (`0444`), `fsync` plików
     i katalogu; (5) etykieta z listingu i publikacja jednym `os.rename`
     katalogu roboczego na nią — istniejący cel (tylko wyścig dwóch
     procesów, np. CLI i serwer albo dwa serwery na jednym udziale) to błąd
     `target_exists`, nigdy nadpisanie; (6) katalog migawki `0555` — dopiero
     po `rename`, bo przeniesienie katalogu do innego rodzica wymaga prawa
     zapisu do niego (zmienia się `..`; sprawdzone 2026-10-19: `EACCES`);
     (7) wpis w indeksie. `chmod` i `fsync` katalogu odrzucone przez system
     plików (CIFS, ACL: `EPERM`, `EINVAL`) dają ostrzeżenie (`notice`)
     w zadaniu, nie błąd. Wpis (7) jest najlepszym wysiłkiem: źródłem
     prawdy jest katalog migawki, a `own_scan` dopisuje brakujące wpisy
     z `.wersje/**/migawka.json` (A-ADR-002). Przerwanie (SIGINT, zabicie
     procesu, awaria) przed (5) zostawia najwyżej katalog w `.incoming/`,
     a po (5) — kompletną migawkę z plikami tylko do odczytu, którą
     znajdzie najbliższy skan. Skan nie czyta `.incoming/` jako migawki,
     a pozostałość starszą niż 24 h zgłasza problem
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
      [--group year|campaign]` → `LayerSet`; z `--thumbnail KLUCZ
      [--size N] --output PLIK.png` zapisuje miniaturę warstwy przez ten sam
      proces renderujący (agent multimodalny obejrzy rok bez HTTP);
    - `archiwista files PROJEKT [--q TEKST] [--state STAN]` →
      `OwnFileList`;
    - `archiwista file PROJEKT PLIK` → `OwnFileCard` z migawkami i historią
      stanów (`PLIK` = ścieżka w folderze albo `file_id`);
    - `archiwista snapshot PROJEKT PLIK [--note TEKST] [--plan]` — z
      `--plan` `SnapshotPlan` bez zapisu, bez niego zadanie na pierwszym
      planie jak `reindex` → `JobDetail` z wynikiem.
    - `archiwista own-scan [--project PROJEKT]` — skan danych własnych na
      pierwszym planie (jak „Odśwież”; bez `--project` — wszystkie
      projekty) → `JobDetail` z wynikiem; agent, który zmienił plik, widzi
      po nim aktualny stan `change`.

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
    | miniatura i kafel z pamięci (także kafel warstwy), p95 | ≤ 100 ms | ≤ 100 ms | pamięć lokalna, niezależna od udziału |
    | pierwszy kafel GeoTIFF kafelkowanego (ortofotomapa 22 528 × 24 326 px), p95 | ≤ 1 s | ≤ 2 s | rozgrzany proces renderujący |
    | pierwsza miniatura tego pliku | ≤ 2 s | ≤ 4 s | z nakładek |
    | lokalny COG arkusza ASC 1 m (ok. 38 MB) | ≤ 10 s | ≤ 20 s | zadanie `preview`, jeden proces budowy |
    | lokalny COG arkusza SM5 JPEG (ok. 125 Mpx) | ≤ 15 s | ≤ 30 s | jw.; ortofoto CZ zawsze przez COG |
    | `/local-layers` obszaru ≤ 500 slotów, p95 | ≤ 1 s | ≤ 5 s | z odświeżeniem widoku (SPEC 4.5) |
    | miniatura warstwy (≤ 50 arkuszy z gotowymi podglądami): pierwsza / z pamięci | ≤ 2 s / ≤ 100 ms | jw. | — |
    | widok roku z 200 arkuszy na mapie, kafle warstwy z pamięci (od przesunięcia do ostatniego kafla widoku 1440 × 900 px) | ≤ 2 s | ≤ 2 s | jedno źródło warstwy (decyzja 7) |
    | Wachlarz roku z 35 arkuszy ASC od zera (z budową COG) | ≤ ⌈35/n⌉ × 10 s = 3 min | ≤ ⌈35/n⌉ × 20 s = 6 min | n = 2 procesy budowy (decyzja 3); postęp widoczny |
    | rok ortofoto CZ z 50 arkuszy SM5 od zera | ≤ ⌈50/n⌉ × 15 s = 6 min 15 s | ≤ ⌈50/n⌉ × 30 s = 12 min 30 s | jw. |
    | `own_scan` folderu 1000 plików bez zmian | ≤ 2 s | ≤ 10 s | tylko `stat` |
    | migawka GeoPackage 100 MB | ≤ 15 s | ≤ 60 s | kopia, dwie sumy, `integrity_check` |
    | pełny skan 50 000 slotów z obrysami-wielokątami | ≤ 2 min | ≤ 10 min | regresja SPEC 4.5 |
    | pamięć serwera (bez procesów renderujących) | ≤ 500 MB | ≤ 500 MB | SPEC 4.5: „bez podglądów” |
    | proces renderujący, szczyt RSS | ≤ 1 GiB | ≤ 1 GiB | informacyjnie; limit `RLIMIT_AS` 2 GiB |

    Cele roku wynikają z celu arkusza i `n` procesów budowy (decyzja 3):
    ⌈arkusze / n⌉ × cel arkusza. Nieosiągnięty cel planu: najpierw pomiar
    składowych, potem poprawka;
    obniżenie celu wyłącznie decyzją użytkownika zapisaną w raporcie.
13. **Bezpieczeństwo nowych ścieżek (SPEC 10.1, 10.3).** Klient nigdy nie
    podaje ścieżki pliku: wersję wskazuje indeks (`resolve_indexed_path`
    w korzeniu magazynu), plik własny — `file_id` z indeksu w folderze
    danych, migawkę — etykieta z indeksu w `.wersje/`; każde otwarcie po
    `realpath` w korzeniu, dowiązanie wychodzące → `403 path_outside_root`.
    GDAL, OGR i laspy pracują tylko w procesach z sandboxem, a plik główny
    otwierają jawnym sterownikiem (decyzja 3); ZIP jest tylko listowany
    (najpierw rekord końca katalogu centralnego, także zip64: > 100 000
    wpisów albo katalog > 64 MiB → `too_large` bez `ZipFile`; potem
    ≤ 10 000 członów, bez rozpakowania). Parametry kafli i miniatur są
    walidowane (0 ≤ z ≤ 22 i 0 ≤ x, y < 2^z, inaczej `422`; kafel z zoomem
    powyżej `maxzoom` pliku albo poza jego zasięgiem → `404 not_found`,
    o który MapLibre nie prosi dzięki `maxzoom` i `bounds` źródła; kafel
    warstwy poniżej jej `minzoom` → `404`; `size` ∈ {128, 256, 512, 1024},
    `style` z listy rodzaju, `rescale` — dwie liczby, kadr — cztery liczby
    w znanym układzie, `zoom` obiektów 0–22). Limit treści żądań bez zmian
    (1 MiB; `note` migawki ≤ 2000 znaków). Pamięć podglądów i katalogi
    robocze procesów (kopie SQLite) leżą w katalogu danych `0700`. Migawki
    zapisuje wyłącznie proces roboczy zadania `snapshot` po sprawdzeniu
    `project.write`; zadania z danymi projektu widać tylko przez widoczny
    projekt (umowa „Zadania”).
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
  - *Typy* (`types.py`, krok 4): `PreviewSource(ref, content_key,
    paths, format_hint, size_bytes, crs, georeference, product,
    dataset_key, nodata, mutable, stat)` — `content_key` to `sha256`
    treści, a dla wersji bez sumy w sidecarze klucz ścieżki (decyzja 3);
    `paths` to rozwiązane ścieżki (główny plik pierwszy, potem komplet),
    `crs` — układ dla pliku bez własnego (`EntryMeta.horizontal_crs`),
    `georeference` — natywny prostokąt i układ z obrysu nagłówkowego
    (JPEG), `mutable` i `stat` (rozmiar, czas modyfikacji, także pliku
    `-wal`) — plik roboczy danych własnych, sprawdzany przed i po
    renderowaniu. `PreviewKind`: `raster`, `image`, `vector`, `points`,
    `archive`, `document`, `auxiliary`, `unknown`.
    `PreviewState`: `ready`, `needs_build`, `building`, `unavailable`,
    `failed`. Kody powodów (`PreviewReason`): `no_georeference`, `no_crs`,
    `auxiliary_file`, `archive_members_only`, `document_no_preview`,
    `unsupported_format`, `too_large`, `missing_file`, `store_unavailable`,
    `transform_unavailable`, `unreadable`, `timeout`, `memory_limit`,
    `changed_since_scan`; teksty `preview_reason_<kod>`
    i `preview_fix_<kod>` w `texts/previews.py`. Style: `hillshade`,
    `hypsometry` (wartości ciągłe), `rgb`, `gray` (obrazy), `classes`
    (klasy), `features` (wektor), `elevation`, `classes` (punkty).
    `PreviewProbe` (treść `info.json`; bez nazw plików i ścieżek — żadnych
    `name` ani `files` zbioru GDAL): rodzaj, sterownik, wymiary, kanały,
    typ, układ, prostokąt natywny i WGS84, zakres zoomu (maks. = zoom
    rozdzielczości natywnej + 2, ≤ 22), nakładki, kafelkowanie, `nodata`,
    statystyki (p2, p98, min, max na kanał — numpy z odczytu
    zdziesiątkowanego: najmniejsza nakładka, a bez nakładek `out_shape`
    ≤ 1024 px; nigdy `statistics()` GDAL), paleta, warstwy wektora,
    nagłówek i klasy LAZ, liczba członów ZIP, `needs_cog`, piksele i bajty
    po rozpakowaniu (progi `auto_build`), powód (sam kod).
  - *Pamięć* (`cache.py`, krok 4): `PreviewCache(root, *, limit_bytes)` —
    `get(key, name) -> bytes | None` dla małych obiektów (`info.json`,
    miniatury, kafle ≤ 1 MiB): bajty czytane od razu, więc usunięcie przez
    LRU w innym procesie po trafieniu nie psuje odpowiedzi (`FileResponse`
    otwiera plik dopiero przy wysyłce); `open(key, name) -> BinaryIO |
    None` dla `cog.tif` i `source.gpkg` — proces renderujący trzyma
    deskryptor, a usunięcie po otwarciu nie przerywa odczytu (POSIX; brak
    pliku przy otwarciu to chybienie pamięci); `put(key, name, data |
    path)` (atomowo: plik roboczy w `.incoming/<host>_<pid>_<token>/`,
    `os.replace`), `pin(key)`/`unpin(key)` (obiekty w budowie; przypięcie
    martwego procesu wygasa), `usage() -> CacheUsage(used_bytes,
    limit_bytes, objects)`, `evict()`, `reconcile()` (przy starcie `serve`
    i przy braku `cache.sqlite`: obiekty bez wpisu dopisane z rozmiarem
    i czasem pliku, wpisy bez plików i pozostałości `.incoming/` martwych
    procesów usunięte). Czas użycia zapisuje się najwyżej raz na 5 min na
    obiekt i proces, więc trafienie w kafel nie jest zapisem SQLite.
    `CacheKey(content_key, renderer, renderer_version)`;
    `RENDERER_VERSIONS` per rodzaj (`raster`, `vector`, `points`,
    `archive`, `document`, `composite`); `composite_key(op, contents,
    frame_or_tile, style, size)` (decyzja 3). Nazwy: `info.json`,
    `cog.tif`, `source.gpkg` (kopia spójna pliku SQLite danych własnych
    w stanie (b) albo (c), decyzja 8), `thumb-<styl>-<rozmiar>[-<skrót
    kadru>].png`, `tiles/<styl>[-<skrót parametrów>]/<z>/<x>/<y>.png`.
    Bezpieczna dla wielu procesów (serwer, procesy zadań, CLI): SQLite WAL
    i `os.replace`.
  - *Sandbox* (`archiwista/sandbox.py`, krok 1): `untrusted_env()`
    (zmienne z decyzji 3, w tym `GDAL_PAM_ENABLED=NO`,
    `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` i `GDAL_SKIP`),
    `child_limits(memory_bytes)` (POSIX: `RLIMIT_AS`, `umask 077`),
    `run_untrusted(argv, *, timeout_s, memory_bytes, input)`,
    `process_work_dir(paths) -> Path`
    (`<katalog danych>/work/<host>_<pid>_<token>/`; przy starcie usuwane
    są tylko katalogi martwych procesów tego komputera, więc równoległe
    CLI i serwer nie kasują sobie plików); używają go czytnik obszarów
    (refaktoryzacja `areas.py`, zachowanie bez zmian), procesy renderujące,
    procesy budowy i czytnik danych własnych. Tabela formatów
    (`archiwista/formats.py`, krok 1): rozszerzenie → rodzaj i sterownik,
    `open_raster(path, fmt)` (`rasterio.open` z `driver=`),
    `vector_source(path, fmt) -> str` (prefiks `GPKG:`/`GeoJSON:` albo
    ścieżka po sprawdzeniu sygnatury: `.shp`, `.fgb`, `.tab` natywny),
    `FormatRefusedError` → `unsupported_format`; jedyna droga, którą
    procesy renderujące i czytnik danych własnych otwierają pliki GDAL-em.
  - *Pula* (`pool.py`, `worker.py`, `protocol.py`, krok 4):
    `RenderPool(*, workers, cache, timeouts)` z `request(op, source,
    params, *, timeout_s) -> RenderResult` (pliki w pamięci albo JSON),
    `start()`/`close()` (w `serve` obok `JobSupervisor`), proces bez pracy
    kończy się po 5 min. Protokół JSON Lines: żądanie `{"id", "op",
    "source", "params"}`, odpowiedź `{"id", "status": "ok", "files"}` albo
    `{"id", "status": "error", "code", "detail"}`; operacje i limity
    czasu: `probe` 20 s, `thumbnail` 30 s, `tile` 15 s, `features` 15 s,
    `members` 10 s, `layer_thumbnail` 60 s, `layer_tile` 15 s (składanie
    warstw — krok 5a3, jedna linia rejestracji na operację). `worker.py`
    zamienia w `detail` każde wystąpienie ścieżek `source.paths` (także po
    `realpath`) i ich katalogów nadrzędnych na nazwę pliku, zanim
    odpowiedź opuści proces. Błędy: `PreviewBusyError` (`503
    preview_busy`), `PreviewTimeoutError` (`504 preview_timeout`),
    `PreviewUnavailableError` (`409 preview_unavailable` z `reason`).
  - *Renderery* (`renderers/`, kroki 5a1–5c; rejestr `RENDERERS` w kroku 4,
    jedna linia na moduł): protokół `Renderer` — `kinds`, `probe(source)
    -> PreviewProbe`, `thumbnail(source, probe, style, size, frame) ->
    bytes`, `tile(source, probe, style, z, x, y, params) -> bytes`,
    opcjonalnie `features(source, probe, layer, bbox_wgs84, zoom, limit)
    -> dict`, `members(source) -> dict`, `build(source, probe, out_path)
    -> None` (COG). Składanie warstw (`compose.py`, 5a3:
    `layer_thumbnail(items, frame, style, size)`, `layer_tile(items, style,
    z, x, y)`) używa `thumbnail` z kadrem i `tile` rendererów, więc działa
    dla rastrów i wektorów. Moduły: `raster.py` (5a1; `build` z `cog.py` —
    5a2), `vector.py` (5b), `points.py`, `archive.py`, `document.py` (5c);
    style w rejestrze `STYLES` (`styles.py`, 5a1 i 5a3), legendy
    `legends.py` (5a3). Transformacje bierze proces renderujący z rejestru
    wtyczek (`GeoAdapter` Kartografa — wymaganej zależności).
  - *Usługa* (`service.py`, krok 6): `PreviewService(pool, cache, jobs,
    settings, resolver)` — `info(source) -> PreviewInfo`,
    `thumbnail(...)`, `tile(...)`, `features(...)`, `members(...)`,
    `build(sources, *, actor, force) -> JobRecord | None`.
  - *Zadanie `preview`* (krok 4): parametry `{"refs": [≤ 500], "force":
    false}`, postęp `current`/`total`, wynik `{"built", "cached", "failed":
    [{"ref", "code", "detail"}], "seconds"}`; bez konfliktów — zlecenie
    treści z trwającego albo czekającego zadania dołącza do niego
    i dopisuje swoje `ref` do `params.refs` (praca bez zmian — treść już
    jest w zadaniu; dopisane `ref` decydują o widoczności, umowa
    „Zadania”), a zadanie pomija treść już zbudowaną. Budowa: najwyżej
    `n = max(1, cpu // 2)` procesów potomnych naraz (decyzja 3), jedno
    zadanie `preview` trwa naraz. Zdarzenia `notice` i `failed[].detail`
    bez ścieżek (decyzja 3).
  - *Model `PreviewInfo`* (krok 6, `api/models_previews.py`): `ref`,
    `state`, `kind`, `reason` (`code`, `message`, `fix`) albo `null`,
    `styles`, `default_style`, `thumbnail_url`, `tiles_url` (szablon
    `{z}/{x}/{y}`) albo `null`, `features_url` (szablon z `{bbox}`
    i `{zoom}`), `members_url`, `bounds` (WGS84), `minzoom`, `maxzoom`,
    `legend` (`kind`: `gradient` z `min`, `max`, `unit` albo `classes`
    z `items`: `value`, `color`, `label`), `layers` (wektor), `points`
    (LAZ: nagłówek, klasy, `sample_points`, `sampled_from`), `size_bytes`,
    `auto_build` (plik ≤ 2 GB, a raster ≤ 1 Gpx i ≤ 8 GiB po rozpakowaniu
    — decyzja 6), `job` (`id`, `state`) albo `null`. Adresy
    w modelu buduje serwer; klient ich nie składa.
- **Dane własne — `archiwista/owndata/` (kroki 7a, 7b, 9).**
  - *Czytnik* (`reader.py`, krok 7a): proces z sandboxem; wejście — linie
    JSON `{"path": "…"}`, wyjście — `OwnFileInfo(kind, driver, members,
    layers, raster, native_crs, native_bbox, feature_count, error)`; 30 s
    na plik; pliki otwiera przez tabelę formatów, a kopie SQLite stanów
    (b) i (c) robi w katalogu roboczym procesu (umowa „Sandbox”).
  - *Treść* (`content.py`, `formats.py`, krok 7a):
    `content_identity(paths, *, method) -> ContentIdentity(method,
    sha256)`, `sqlite_content_sha256(connection)` (tabele wirtualne
    i cienie z `sqlite_master`, bez danych pochodnych — decyzja 8),
    `fileset_members(path) -> tuple[Path, ...]` (Shapefile, TAB natywny),
    `consistent_sqlite_read(path, *, work_dir) -> ContextManager[SqliteRead]`
    — trzy stany z decyzji 8: (a) w miejscu z `immutable=1`
    (`IMMUTABLE=YES` dla GDAL) i stanem przed i po, (b) `Connection.backup`
    z `mode=ro` do kopii w `work_dir`, (c) kopia bajtów pliku i `-wal` do
    `work_dir`; `SqliteRead` daje ścieżkę i opcje otwarcia dla `sqlite3`
    i GDAL oraz stan pliku. Używają go czytnik, renderer wektorów (5b)
    i migawka (8) — nikt nie otwiera pliku SQLite danych własnych inaczej.
  - *Indeks* (krok 7b): tabele `own_folders` (klucz dostępu projektu,
    ścieżka, źródło: `default`/`setting`, stan `ok`/`missing`/
    `unreadable`/`invalid`, `scanned_at`, liczniki i bajty, bajty migawek),
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
  - *Zadanie `own_scan`* (krok 7b): parametry `{}` — wszystkie projekty
    (harmonogram) — albo `{"project": klucz}` — jeden folder (zlecenie
    z widoku projektu, `archiwista own-scan --project`); przebieg plików
    bez zmian to tylko `stat`. Najwyżej jeden przebieg trwa naraz;
    zlecenie dołącza do czekającego przebiegu globalnego albo do
    czekającego przebiegu tego samego projektu (`202` z tym zadaniem),
    a inaczej czeka jako nowe — więc zmiana sprzed zlecenia zawsze trafi
    do wyniku; wynik `{"projects", "files", "new", "changed", "missing",
    "unreadable", "snapshots", "problems", "seconds"}` (same liczby;
    problemy folderów są w indeksie, filtrowane widocznością); harmonogram
    — przy starcie, gdy ostatni przebieg globalny jest starszy niż 15 min,
    potem co `scan_interval_local_min`; rutynowe przebiegi bez zmian
    przycinane po 48 h jak rutynowe skany v0.1.
  - *Modele* (kroki 7b i 9, `api/models_owndata.py`): `OwnFolder` (`path`
    jako `CopyPath` z aliasami, `source`, `state` — `ok`, `missing`,
    `unreadable`, `invalid` — `files`, `size_bytes`, `snapshots_bytes`,
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
    `own_folder_unreadable`, `own_folder_invalid` (powód `inside_store`,
    `inside_app_data`, `overlaps_project`), `own_folder_too_large`
    (zaindeksowane pierwsze 10 000 plików w porządku ścieżki),
    `own_file_unreadable`, `invalid_snapshot`, `unknown_snapshot_schema`,
    `snapshot_modified`, `stale_snapshot_incoming`, `path_outside_root`.
- **Migawki — `archiwista/owndata/{snapshots,document}.py` (krok 8).**
  `check_snapshot(folder, file, *, last, work_dir) -> SnapshotPlan`;
  `make_snapshot(folder, file, *, author, note, work_dir, cancel=None,
  fault=None) -> SnapshotResult(status: "created" | "unchanged", label,
  document, warnings)` (`work_dir` — katalog roboczy procesu; `fault` —
  punkt przerwania tylko dla testów; `warnings` — odrzucone `chmod`
  i `fsync` katalogu); `SnapshotDocument` (decyzja 9). Zadanie `snapshot`:
  parametry `{"project", "file_id", "note"}`, klucz konfliktu (projekt,
  plik), wynik `{"status", "label", "content_sha256", "size_bytes",
  "seconds"}`, ostrzeżenia jako zdarzenia `notice`, kody błędów:
  `snapshot_blocked` (z powodem: `folder_invalid`, `read_only_folder`,
  `insufficient_space`, `file_missing`), `inconsistent_copy`,
  `checksum_mismatch`, `integrity_failed`, `target_exists` (tylko wyścig
  dwóch procesów).
- **Zadania — `archiwista/jobs/` (kroki 4, 6, 7b, 8, 9).** `JOB_KINDS`
  dostaje `preview`, `own_scan`, `snapshot`; `JobSpec.store: str | None`,
  projekt w `params`; `JobSupervisor.submit(kind, *, store=None, params,
  actor)` z regułą per rodzaj: `scan`/`footprints` — konflikt na magazyn
  (v0.1), `snapshot` — konflikt na (projekt, plik), `preview` —
  dołączenie do trwającej budowy tej samej treści z dopisaniem `ref`,
  najwyżej jedno trwające (kolejne `queued`, jak limit zadań sieciowych),
  `own_scan` — jeden trwający, czekające łączone według zakresu (globalny
  albo projekt); `JobFilters.project` (krok 9).
  *Widoczność* (krok 9; zastępuje regułę v0.1 „zadania dotyczą magazynów,
  które widzą wszyscy”): zakres zadania wynika ze `store` i `params` (bez
  nowej kolumny) — `store` albo `version:` w `refs` to część magazynowa
  (widzą wszyscy), a `params.project` i `file:`/`snapshot:` w `refs` —
  projekty. `JobSupervisor.list/get/events` przyjmują `visible`
  (zależność `visible_projects` w `api/jobs.py`; filtr w zapytaniu, więc
  strony listy mają pełny rozmiar): zadanie bez części magazynowej, którego
  wszystkie projekty są niewidoczne, nie występuje na liście, a
  `/jobs/{id}` i `/jobs/{id}/events` dają `404 not_found`; zadanie
  mieszane (`preview` z `version:` i `file:`) pokazuje tylko widoczne
  `refs` i wpisy `failed[]`, a liczby (`built`, `cached`, postęp) —
  pełne (A-ADR-029: zbiorczo liczby, nazwy tylko widocznych). Globalny
  `own_scan` widzą wszyscy (wynik i zdarzenia to same liczby). Dzienniki
  w `AppPaths.jobs_dir` to pliki lokalne serwera, nie trasa API.
  Wspólne uruchamianie zadania na pierwszym planie
  (`jobs/foreground.py`, krok 6) zastępuje kod `jobs/reindex.py`
  i obsługuje `reindex`, `preview --build`, `snapshot` i `own-scan`
  (przebieg tego samego zakresu trwający w innym procesie: CLI czeka na
  jego koniec i robi własny — ta sama gwarancja co łączenie czekających).
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
  | `GET …/features?layer&bbox&zoom&limit` | GeoJSON `FeatureCollection` (+ `number_matched`, `truncated`, `simplified`) | sesja | 6 |
  | `GET …/members` | `ArchiveMembers` | sesja | 6 |
  | `GET /projects/{project}/files?q&state&limit&cursor` | `OwnFileList` | widoczność | 9 |
  | `POST /projects/{project}/scan` | `202 JobDetail` (`own_scan` tego projektu) | widoczność | 9 |
  | `PUT /projects/{project}/data-dir` (`{"path": … \| null}`) | `OwnFolder` | `settings.write` | 9 |
  | `GET /projects/{project}/files/{file_id}` | `OwnFileCard` | widoczność | 9 |
  | `GET\|POST /projects/{project}/files/{file_id}/preview`, `GET …/preview.png`, `…/tiles/{z}/{x}/{y}.png`, `…/features` | jak dla wersji | widoczność | 9 |
  | `GET /projects/{project}/files/{file_id}/snapshot-plan` | `SnapshotPlan` | widoczność | 9 |
  | `POST /projects/{project}/files/{file_id}/snapshots` (`{"note": …}`) | `202 JobDetail` (`snapshot`) | `project.write` | 9 |
  | `GET /projects/{project}/files/{file_id}/snapshots/{label}/preview`, `…/preview.png`, `…/tiles/…`, `…/features` | jak dla wersji | widoczność | 9 |
  | `GET /compare?a&b` | `Comparison` | wg obu `ref` | 10 |
  | `GET /local-layers?store&product&area_id&segment&group` | `LayerSet` | sesja | 11 |
  | `GET /local-layers/thumbnail.png?…&layer&size&v` | `image/png` | sesja | 11 |
  | `GET /local-layers/tiles/{z}/{x}/{y}.png?store&product&area_id&layer&style&v` | `image/png` (kafel warstwy, decyzja 7) | sesja | 11 |
  | `GET /projects/{project}/files/{file_id}/layers` | `LayerSet` (plik roboczy i migawki) | widoczność | 11 |

  Do istniejących: pole `ref` w modelach wersji (`Version`, `VersionCard`;
  krok 6); filtr `project` w `/slots` i `/map/footprints` (wersje przypięte
  w projekcie; krok 9); `previews` (`used_bytes`, `limit_bytes`,
  `objects`, `workers`) i `own_data` (ostatni `own_scan`) w `/health`
  (kroki 6 i 9); `project` w `GET /jobs` i widoczność w trasach zadań
  (krok 9, umowa „Zadania”). Nowe kody problemów:
  `422 invalid_ref`, `409 preview_unavailable` (z `reason`),
  `409 preview_not_ready` (z `job` albo `build_required`),
  `503 preview_busy` (z `Retry-After`), `504 preview_timeout`,
  `409 own_file_changed` (plik zmienił się od skanu → `POST
  /projects/{project}/scan`), `409 snapshot_blocked` (z `reason`).
  `LayerSet`: `area` (albo `null`), `store`, `product`, `group`, `frame`
  (`crs`, `bbox` w układzie płaskim; `null` bez obszaru), `layers`
  (od najnowszej): `key` (`<wariant>:<rok|wydanie|etykieta>[:<kampania>]`;
  wariant = 12 znaków SHA-256 klucza wariantu albo segment — decyzja 7),
  `variant` (`product`, `horizontal_crs`, `resolution`, `vertical_crs`,
  `segments`, `formats`), `kind` (`year`, `edition`, `label`,
  `campaign`), `year`, `title`, `subtitle`, `versions_count`,
  `units_count`, `campaigns`, `data_dates`, `coverage` (`ratio`,
  `percent`, `label`) albo `null`, `outlines` (GeoJSON w `frame.crs`;
  tylko z obszarem), `preview` (`state`, `ready`, `total`, `job`,
  `thumbnail_url`, `tiles_url` warstwy, `minzoom`), `versions` (≤ 500,
  tylko z obszarem: `ref`, `slot`, `unit`, podgląd: stan, `tiles_url`,
  `bounds`); dalej `stale`, `stale_stores`, `stale_reason` jak
  `/local-coverage`. `LayerSet` pliku własnego (krok 9): `store`,
  `product`, `group` = `null`, warstwy rodzajów `file` (klucz `file`)
  i `snapshot` (klucz `snapshot:<etykieta>`), kadr = suma zasięgów
  w układzie płaskim kraju. `Comparison`: `a`, `b` (`ref`, rodzaj, tytuł,
  `preview`, obrys WGS84), `same_content`, `rows` (`group`, `field`,
  `label`, `a`, `b`, `differs`), `schema_diff` (warstwy: tylko w A/B,
  liczby obiektów, pola dodane, usunięte i zmienione) albo `null`.
- **Interfejs WWW — `archiwista/web/` (kroki 12a–15).** Umowa widoku v0.1
  bez zmian (linia w `VIEWS`/`OVERLAYS`, własny plik `labels/<widok>.js`,
  styl przez `loadStylesheet`). Nowe moduły:
  - `src/previews.js` — `usePreviewImage(url)` (adres `blob:` z `fetch`
    z nagłówkiem CSRF, zwalniany przy odmontowaniu) i `PreviewPane`
    (legenda, powód, przycisk budowy, postęp przez `useJob`);
  - `src/map/previews.js` — źródło rastrowe wersji i jedno źródło warstwy
    roku (`/local-layers/tiles`, `minzoom` warstwy);
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
- **CLI (kroki 6, 9–11).** Nowe polecenia w modułach per funkcja
  `archiwista/commands/{previews,owndata,compare,layers}.py` (każdy:
  `COMMANDS`, `add_commands`, `main`), rejestrowane jedną linią w krotce
  `COMMAND_MODULES` w `cli.py` (wprowadza ją krok 6; `reader.py`
  i `admin.py` z v0.1 bez zmian): `preview`, `compare`, `layers`, `files`,
  `file` na funkcjach bez HTTP z `api/` i tych samych modelach;
  `snapshot` i `own-scan` na `jobs/foreground.py`. Wszystkie jako
  `LOCAL_OWNER` przez ten sam `Authorizer`.
- **Modele i teksty (kroki 4–11).** Nowe modele API w modułach per
  funkcja: `api/models_previews.py` (6), `api/models_owndata.py` (7b, 9),
  `api/models_compare.py` (10), `api/models_layers.py` (11), importowane
  wprost przez swoje trasy i polecenia; `api/models.py` (ok. 2600 linii)
  dostaje tylko pola istniejących modeli (`ref` w wersjach, `Health`,
  `JobFilters.project`). Teksty: słowniki per funkcja
  `archiwista/texts/{previews,owndata,compare,layers}.py` scalane
  w `MESSAGES` jedną linią na słownik (`messages.py` przy imporcie odrzuca
  powtórzony klucz).
- **Fixtury (krok 2, punkt kontrolny — krok 3).**
  `tests/fixtures/make_store.py` (nowe rodziny w zestawie przypadków,
  nie w części masowej; także wersja bez `sha256` w sidecarze i dwa
  segmenty jednego zestawu w dwóch formatach), `tests/fixtures/own_data.py`
  (`make_own_folder(path, *, families)`, `project_inside_store(...)`,
  `GpkgEditor` — edycja GeoPackage jak w QGIS: WAL, zmiany zatwierdzone
  w WAL i otwarta transakcja, awaria zostawiająca `-wal` bez `-shm`,
  otwarcie do zapisu bez zmian danych (przepisany `gpkg_ogr_contents`),
  `write_snapshot_fixture(...)` — katalog migawki zgodny
  z `archiwista-snapshot/1` dla testów skanu przed krokiem 8),
  `tests/fixtures/hostile_files.py` (treść VRT i OGR VRT pod nazwami
  danych, `a.tif.ovr` z treścią VRT, widok i tabela łączona MapInfo,
  raster deklarujący 100 000 × 100 000 px w kilku MB, ZIP z katalogiem
  centralnym deklarującym 200 000 wpisów),
  `tests/fixtures/control_points.py` (punkt 3722 ze źródłem).

## Kolejność prac

| Krok | Tytuł | Zależności | Równolegle z | Stan |
|---|---|---|---|---|
| 0 | Porządki po v0.1: `ResourceWarning` | — | 1, 2, 3, 7a | zrobione |
| 1 | Zależności podglądów, sandbox i próby techniczne | — | 0, 2, 3 | zrobione |
| 2 | Magazyn testowy i fixtury v0.2 | — | 0, 1, 3, 4, 7a | zrobione |
| 3 | Obrysy-wielokąty i operacja dla GDAL w umowie źródła | — | 0, 1, 2, 4, 7a | zrobione |
| 4 | Infrastruktura podglądów: pamięć, pula, zadanie `preview` | 1 | 2, 3, 7a, 7b | zrobione |
| 5a1 | Podglądy rastrów: rozpoznanie, miniatura, kafel | 1, 2, 3, 4 | 5b, 5c, 6, 7b, 8 | zrobione (bez próby punktu kontrolnego) |
| 5a2 | Podglądy rastrów: lokalny COG | 5a1 | 5a3, 5b, 5c, 6, 7b, 8, 10, 11, 12a | zrobione (bez próby punktu kontrolnego) |
| 5a3 | Podglądy rastrów: style, legendy, składanie warstw | 5a1 | 5a2, 5b, 5c, 6, 7b, 8, 10, 11, 12a | zrobione |
| 5b | Podglądy wektorów | 1, 2, 4, 7a | 5a1–5a3, 5c, 6, 7b, 8 | zrobione |
| 5c | Chmury punktów, archiwa, dokumenty, pliki pomocnicze | 1, 2, 4 | 5a1–5a3, 5b, 6, 7b, 8 | zrobione |
| 6 | Podglądy magazynu przez HTTP i CLI; odwołania `ref` | 3, 4; odbiór po 5a1–5c | 5a1–5c, 7b, 8 | zrobione |
| 7a | Czytnik danych własnych i tożsamość treści | 1 (sandbox, tabela formatów, próba SQLite) | 2, 3, 4 | zrobione |
| 7b | Folder danych, indeks i skan danych własnych | 2, 3, 7a | 4, 5a1–5c, 6 | zrobione |
| 8 | Migawki | 7a, 7b | 5a1–5c, 6, 10, 11, 12a | zrobione |
| 9 | Dane własne i migawki przez HTTP i CLI; `project.write`; widoczność zadań | 6, 7b, 8 | 10, 11, 12a, 12b | zrobione (`aa01878`, `3231869`, `2126c33`, `dcbb454`, `003be5f`, próby `57005bb`) |
| 10 | Porównanie metadanych | 6; strony danych własnych po 9 | 5a2, 5a3, 8, 11, 12a, 12b | zrobione (strony danych własnych w kroku 9, `dcbb454`) |
| 11 | Warstwy lokalne, miniatury i kafle warstw | 3, 5a1, 5b, 6; odbiór warstw po 5a3; warstwy migawek po 9 | 5a2, 5a3, 10, 12a | zrobione (kod `a5ae7f3`, próby `02228f4`; warstwy pliku własnego w kroku 9, `003be5f`) |
| 12a | Interfejs: podgląd w Karcie pliku i ustawienia pamięci | 6 | 9, 10, 11 | zrobione |
| 12b | Interfejs: podglądy na mapie | 11, 12a | 9, 10 | zrobione |
| 13a | Interfejs: przełącznik widoków i Wachlarz | 11, 12a, 12b | 14, 15, 16 | zrobione (Wachlarz migawek: komponent gotowy, podłączenie w 15) |
| 13b | Interfejs: Oś czasu, Szczegóły zestawu i wspólny wybór | 13a | 14, 15, 16 | zrobione |
| 14 | Interfejs: Porównanie i kurtyna | 10, 12b; wejście z panelu po 13b | 13a, 13b, 15, 16 | zrobione dla wersji magazynu i warstw lat (strony danych własnych — punkt rozszerzenia dla 15; wejście z panelu „Szczegóły zestawu” w 13b) |
| 15 | Interfejs: dane własne i migawki | 9, 12a; Wachlarz migawek po 13a, „Porównaj” po 14 | 13a, 13b, 14, 16 | zrobione |
| 16 | Wydajność i pomiary (z płynnością mapy na GPU) | 3, 6, 7b, 8, 11, 12b | 13a–15, 17 | zrobione dla SSD i SMB (raport `docs/reports/v0.2-measurements.md`); kryterium 5 (GPU) — niezweryfikowane |
| 17 | E2E i odbiór v0.2 | 12a–15 | 16 | zrobione: przejście w przeglądarce, magazyn tylko do odczytu i odłączony udział; 3 magazyny live, 44 wersje; pełna bramka 1049 zaliczonych (raport, sekcje 9–11); kryterium GPU 5 otwarte |
| 18 | Dokumentacja, bramka i wydanie 0.2.0 | 0–17 | — | zrobione: dokumentacja i demo, bramka w `.venv` (wyniki: Stan po kroku 18); GPU kryterium 5 niezweryfikowane |

Fale równoległości: **A** — 0, 1, 2, 3; **B** — 4, 7a; **C** — 5a1, 5b,
5c, 6 (umowa API na rejestrze rendererów), 7b; **D** — 5a2, 5a3, 8, 10
(wersje magazynu), 11 (odbiór miniatur i kafli warstw po 5a3), 12a;
**E** — 9, 12b; **F** — 13a, 14, 15, 16; **G** — 13b; **H** — 17;
**I** — 18. Kroki jednej fali nie edytują tych samych plików poza jedną
linią rejestracji (rejestr rendererów, operacje puli, `STYLES`,
`RUNNERS`, `include_router`, `COMMAND_MODULES`, scalenie słowników
tekstów w `MESSAGES`, `VIEWS`/`OVERLAYS`, warstwa mapy) i podniesieniem
`SCHEMA_VERSION` przy scaleniu (kroki 3 i 7b). Nowe modele API,
polecenia CLI i teksty leżą w modułach per funkcja (umowy „CLI” oraz
„Modele i teksty”), więc kroki jednej fali (np. 10 i 11) nie dzielą
`api/models.py`, `reader.py` ani `messages.py` poza linią scalenia.

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
- **Stan po kroku 0:**
  - *Źródło.* Nie kod aplikacji, lecz test
    `tests/unit/test_security.py::test_security_tokens_carry_minter_id_and_kind_only`:
    `with sqlite3.connect(index_path) as connection:` — menedżer kontekstu
    `sqlite3.Connection` kończy transakcję, ale nie zamyka połączenia;
    sprzątacz pamięci zbierał je dopiero w następnym teście
    (`…_owner_then_agent`), stąd mylące miejsce zgłoszenia. Ustalone
    z `PYTHONTRACEMALLOC=25 python -X dev -m pytest tests/unit`
    (ślad przydziału: `test_security.py:247`). Poprawka: `try`/`finally`
    z `close()`, jak w pozostałych odczytach testów.
  - *Drugie źródło ujawnione filtrami.*
    `tests/integration/test_jobs.py::test_restart_marks_running_job_interrupted`
    nie zamykał potoków `stdin`/`stdout` procesu `job_owner`
    (`ResourceWarning: unclosed file <_io.TextIOWrapper>`); proces jest
    teraz menedżerem kontekstu `subprocess.Popen`.
  - *Filtry.* `pyproject.toml`: `filterwarnings = ["error::ResourceWarning",
    "error::pytest.PytestUnraisableExceptionWarning"]` — wyciek kończy test
    błędem. Bez poprawki test z `security` kończy się błędem
    (`PytestUnraisableExceptionWarning … sqlite3.Connection`), z poprawką
    47/47 zaliczonych.
  - *Osobno* (commit `test(e2e)`):
    `test_pinned_old_version_visible` szukał przycisku wersji po etykiecie
    w całej karcie; przycisk „Kopiuj: …” ścieżki wersji zawiera tę etykietę
    w nazwie katalogu, więc zależnie od chwili renderowania lokator łapał
    dwa elementy (DOM identyczny z Kartografem z wydania v0.1 i z bieżącym
    `develop`). Lokator zawężony do osi wersji (`.fc-axis`).
  - *Bramka* (HEAD + krok 0, bieżący Kartograf `develop`): ruff check
    i format — bez uwag (149 plików), mypy strict — bez błędów (144 pliki),
    pytest — 649 zaliczonych, 21 odznaczonych, pokrycie 95,26%, jedno
    ostrzeżenie (przestarzały `httpx` w `starlette.testclient`), bez
    `ResourceWarning`.

### 1. Zależności podglądów, sandbox i próby techniczne
- **Cel:** dołączyć zależności, dać wspólny sandbox procesów czytających
  pliki i sprawdzić założenia, na których stoją kroki 4–8, zanim powstanie
  reszta kodu produkcyjnego:
  - `archiwista/sandbox.py` (decyzja 3): środowisko (z
    `GDAL_PAM_ENABLED=NO`, `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`
    i `GDAL_SKIP`), limity, uruchamianie procesów czytających niezaufane
    pliki i katalogi robocze procesów — kod środowiska czytnika obszarów
    przeniesiony z `areas.py` bez zmiany zachowania dla obsługiwanych
    plików (jedna implementacja dla czytnika obszarów, procesów
    renderujących, budowy COG i czytnika danych własnych);
    `archiwista/formats.py` — tabela formatów i otwarcie jawnym
    sterownikiem (decyzja 3; czytnik obszarów nie tworzy `WarpedVRT`,
    więc zostaje przy swoim otwieraniu, chronionym przez `GDAL_SKIP`);
    `AppPaths.work_dir`;
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
  - próba SQLite (decyzja 8) — macierz trzech stanów: (a) baza w trybie
    WAL bez `-wal`: `immutable=1` (w GDAL `IMMUTABLE=YES`) bez nowych
    plików, a `mode=ro` tworzy `-wal` i `-shm`; (b) `-wal` i `-shm` przy
    piszącym połączeniu (zatwierdzone ramki w WAL, otwarta transakcja):
    `Connection.backup` z `mode=ro` kopiuje tylko zatwierdzone wiersze,
    bez nowych plików; (c) `-wal` bez `-shm`: `mode=ro` tworzy `-shm`,
    `immutable=1` nie widzi wierszy z WAL, GDAL w odczycie przepisuje WAL
    do pliku głównego, a kopia pliku i `-wal` w katalogu roboczym daje
    pełną treść i `integrity_check` = `ok` (wstępnie sprawdzone
    2026-10-19: SQLite 3.46.1, GDAL 3.12); tabele wirtualne i cienie
    rozpoznane z `sqlite_master` zgodnie z `PRAGMA table_list`;
  - próba otwierania GDAL (decyzja 3): w procesie z sandboxem po
    `WarpedVRT` treść VRT pod nazwą `.tif` i `.asc` (`driver=`),
    `a.tif.ovr` z treścią VRT obok GeoTIFF (`EMPTY_DIR`) i treść OGR VRT
    pod nazwą `.gpkg`, `.geojson`, `.shp`, `.fgb` (prefiks albo
    sygnatura) nie czytają pliku docelowego; przy `EMPTY_DIR` Shapefile
    czyta `.shx .dbf .prj .cpg`, a MapInfo TAB — `.dat .map .id`;
    `statistics()` przy `GDAL_PAM_ENABLED=NO` nie zapisuje `.aux.xml`
    (wstępnie sprawdzone 2026-10-19 dla `.ovr`, `.dbf`, `.prj`, prefiksów
    i `.aux.xml`);
  - próba dostarczania: MapLibre 6 z `transformRequest` dodającym
    `X-Archiwista-CSRF` do kafli rastrowych i `<img src="blob:…">` pod CSP
    z SPEC 10.1, w Chromium z Playwright.
- **Pliki:** `pyproject.toml`, `requirements.lock`, `archiwista/sandbox.py`,
  `archiwista/formats.py`, `archiwista/config.py` (`AppPaths.work_dir`),
  `archiwista/areas.py` (użycie sandboxa), `tests/unit/test_sandbox.py`,
  `tests/contract/test_preview_stack.py` (próby jako testy kontraktu
  bibliotek: wymuszona operacja trafia ≤ 2 m, `seek` LAZ, trzy stany
  SQLite, `test_vrt_refused_after_warpedvrt_in_same_process`,
  `test_sibling_ovr_ignored`, `test_statistics_write_no_aux_xml`),
  `tests/e2e/test_tile_headers.py`
  (`test_maplibre_raster_tiles_carry_csrf_header` na serwerze testowym
  z CSP v0.1); notatka „Stan po kroku 1” w tym planie z wynikami prób
  (także sprzecznymi z decyzjami — wtedy przegląd decyzji przed krokiem 4).
- **Interfejs:** umowa „Sandbox” z sekcji „Umowy” (z tabelą formatów
  i katalogami roboczymi procesów); poza nią brak kodu produkcyjnego.
- **Test/odbiór:** `.venv/bin/python -m pytest tests/contract/test_preview_stack.py
  tests/e2e/test_tile_headers.py` zielone; `pip install --require-hashes
  -r requirements.lock` w czystym `.venv`; `tests/contract/test_imports.py`
  zielony (nowe biblioteki nie są importowane przez serwer przy starcie —
  tylko przez procesy renderujące); `tests/unit/test_sandbox.py`
  (środowisko bez pośredników i poświadczeń, `PROJ_NETWORK=OFF`,
  `GDAL_PAM_ENABLED=NO`, `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`,
  `GDAL_SKIP` z `VRT` i `OGR_VRT`, limit pamięci i czasu procesu
  potomnego, `test_process_work_dir_cleanup_keeps_live_processes`)
  i `tests/integration/test_areas.py` bez regresji.
- **Zależności:** —. **Równolegle:** 0, 2, 3.
- **Stan po kroku 1:**
  - *Zależności.* `rio-tiler>=9.0,<9.1` (9.0.6: od 9.1 rio-tiler wymaga
    `httpx2`, a z nim Starlette 1.8 przełącza `TestClient` i jego typy na
    `httpx2` — mypy testów z `httpx.Response` przestaje przechodzić),
    `laspy[lazrs]>=2.7,<3` (2.7.0, lazrs 0.8.2). Nowe pakiety blokady:
    cachetools 7.2.3, color-operations 0.4.0, morecantile 7.1.0, numexpr
    2.14.2, pystac 1.15.2 (z pystac-core i 24 pakietami `pystac-ext-*`),
    python-dateutil 2.9.0.post0, six 1.17.0. Licencje: MIT (cachetools,
    color-operations, lazrs, morecantile, numexpr, six), BSD-2-Clause
    (laspy), BSD-3-Clause (rio-tiler), Apache-2.0 (pystac i rozszerzenia),
    Apache-2.0/BSD-3-Clause (python-dateutil) — zgodne z MIT. Blokada
    przeliczona jak w nagłówku (`-c` poprzednich wersji): żadna dotychczasowa
    wersja się nie zmieniła; `pip install --require-hashes -r
    requirements.lock` w czystym `.venv` (Python 3.13) i `pip check` —
    przechodzą. mypy: `ignore_missing_imports` dla rasterio, laspy, lazrs.
    Serwer przy starcie nie ładuje rio_tiler, laspy, lazrs, morecantile,
    numexpr ani color_operations
    (`tests/contract/test_imports.py::test_server_start_imports_no_preview_library`;
    rasterio ładuje Kartograf przy wczytaniu wtyczki — stan v0.1).
  - *Sandbox* (`archiwista/sandbox.py`): `untrusted_env() -> dict[str,
    str]` (dozwolone zmienne `UNTRUSTED_INHERITED` i przedrostki
    `ARCHIWISTA_`, `COVERAGE_`, `LC_` — przeniesione z `areas.py` — oraz
    wymuszone `UNTRUSTED_FORCED`: `PROJ_NETWORK=OFF`, pośrednicy GDAL na
    `127.0.0.1:9`, `GDAL_PAM_ENABLED=NO`,
    `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`, `GDAL_SKIP` z
    `SKIPPED_GDAL_DRIVERS` (lista decyzji 3) i `GDAL_CACHEMAX=256`
    — `GDAL_CACHE_MB`, dla wszystkich procesów);
    `child_limits(memory_bytes: int | None = None) -> dict[str, Any]` —
    argumenty `subprocess.Popen`: własna sesja, `umask=0o077` i przy
    `memory_bytes` `preexec_fn` z samym `setrlimit(RLIMIT_AS)` (bez blokad,
    więc bezpieczny w wielowątkowym serwerze); `run_untrusted(argv, *,
    timeout_s, memory_bytes=None, input=None, cwd=None) ->
    CompletedProcess[bytes]` (stdout; stderr odrzucony — komunikaty
    bibliotek mają ścieżki; po czasie zabija grupę i zgłasza
    `subprocess.TimeoutExpired`); `kill_untrusted(process)` (SIGKILL grupy —
    dla puli kroku 4: `Popen(argv, env=untrusted_env(), stdin=PIPE,
    stdout=PIPE, **child_limits(2 * 1024**3))`); `process_work_dir(paths)
    -> Path` (`AppPaths.work_dir` = `<katalog danych>/work`; katalog
    `<host>_<pid>_<token>/` z prawami `0700`, ten sam przy każdym wywołaniu
    w procesie; przy utworzeniu usuwa katalogi martwych procesów tego
    komputera — `os.kill(pid, 0)` — a zostawia żywe, innych komputerów
    i nazwy spoza wzoru; przy wyjściu nie sprząta — robi to następny
    proces). Odstępstwa od umowy: `cwd` w `run_untrusted` (czytnik obszarów
    pracuje w katalogu przesłanego pliku) i dodatkowe `kill_untrusted`.
    Czytnik obszarów: `run_untrusted(command, timeout_s=…, cwd=…)` bez
    limitu pamięci, jak w v0.1; `tests/integration/test_areas.py` bez
    regresji.
  - *Tabela formatów* (`archiwista/formats.py`, tylko biblioteka
    standardowa przy imporcie): `FileFormat(name, kind, extensions,
    driver=None)`, `FormatKind` (`raster`, `image`, `vector`, `points`,
    `archive`, `document`, `auxiliary`, `unknown` — krok 4 bierze go jako
    `PreviewKind` zamiast drugiej listy), `FORMATS`, `UNKNOWN_FORMAT`,
    `file_format(path)` (rozszerzenie bez względu na wielkość liter):
    `GTiff` (`.tif .tiff`), `AAIGrid` (`.asc`), `XYZ` (`.xyz`) — `raster`;
    `JPEG` (`.jpg .jpeg`), `PNG` — `image`; `GPKG`, `ESRI Shapefile`
    (`.shp`), `GeoJSON` (`.geojson`), `FlatGeobuf` (`.fgb`), `MapInfo File`
    (`.tab`) — `vector`; `.laz .las` — `points`; `.zip` — `archive`;
    `.pdf .txt` — `document`; `.jgw .pgw .tfw .wld` — `auxiliary`.
    `open_raster(path, fmt, **open_options)` (`rasterio.open(path,
    driver=…)`, rasterio importowany dopiero tu; np. `OVERVIEW_LEVEL=0`);
    `vector_source(path, fmt) -> str`: `GPKG:"<ścieżka>"` **w cudzysłowie**
    (GDAL dzieli `GPKG:` na `:` — `plan:2026.gpkg` bez cudzysłowu otwiera
    plik `plan`; ścieżka z `"` → odmowa), `GeoJSON:<ścieżka>`, `.shp`
    (kod 9994), `.fgb` (`fgb\x03fgb`), `.tab` tylko natywny (`!table`,
    `Definition Table`, `Type NATIVE`; widok, `\IsSeamless`, `RASTER`,
    `LINKED`, nagłówek > 1 MiB → odmowa); ścieżka względna albo `/vsi…` →
    odmowa. `FormatRefusedError` (w `archiwista/errors.py`, komunikat po
    angielsku bez ścieżki) → `unsupported_format`. Poza planem plików:
    `tests/unit/test_formats.py` (tabele MapInfo, nazwy) i skrypt prób
    `tests/fixtures/preview_probes.py` (JSON na stdin, uruchamiany przez
    `run_untrusted`).
  - *Wyniki prób* (2026-10-19; rasterio 1.5.2 z GDAL 3.12.2, pyogrio 0.13.0
    z GDAL 3.12.4, SQLite 3.46.1, rio-tiler 9.0.6, laspy 2.7.0 z lazrs 0.8.2;
    `tests/contract/test_preview_stack.py`, 14 testów):
    - warp, kafel z = 19 (x = 289216, y = 178354), GeoTIFF EPSG:5514
      0,5 m z jasnym blokiem na punkcie 3722: `reproject`
      z `COORDINATE_OPERATION = pinned_transform(5514, 3857).gdal_operation()`
      — 0,665 m, z nakładki `OVERVIEW_LEVEL=0` (1 m) — 0,665 m; ta sama
      operacja przesunięta o 50 m na wschód — 32,2 m (operacja jest
      użyta); operacja wielkimi literami — błąd `Cannot instantiate
      pipeline`; operacja domyślna GDAL (bez wymuszenia) — 0,719 m;
      `WarpedVRT` i rio-tiler (`vrt_options`) z operacją przesuniętą —
      0,719 m, tyle co bez niej: opcja jest po cichu pomijana, bez błędu.
      Decyzja 4 bez zmian (kafel przez `reproject`). Raster EPSG:4326 bez
      wymuszenia — 0,06 m; `pinned_transform(4326, 3857)` — błąd Kartografa;
    - LAZ (format 6, LAS 1.4, kawałki po 50 000 punktów): nagłówek, układ
      z VLR WKT (EPSG:2180), `seek(150 000)` czyta czwarty kawałek także
      przy zniszczonym pierwszym (odczyt od początku tego pliku — błąd
      lazrs), więc przeskok idzie przez tablicę kawałków;
    - SQLite — wszystkie trzy stany jak w decyzji 8, oraz nowa obserwacja:
      w stanie (c) GDAL z `IMMUTABLE=YES` widzi wiersze bez WAL, a mimo to
      przepisuje WAL do pliku głównego i usuwa `-wal` (tak samo jak bez
      tej opcji) — stan (c) nigdy w miejscu, także z `IMMUTABLE=YES`, co
      decyzja 8 już przewiduje. Tabele wirtualne i cienie (rtree, fts3,
      fts4, fts5) z `sqlite_master` = `PRAGMA table_list`; modułu `geopoly`
      nie ma w SQLite Pythona, więc jego przyrostki zostają z decyzji 8.
      Tablica przyrostków jest na razie w teście (`SHADOW_SUFFIXES`) — krok
      7a przenosi ją do kodu produkcyjnego, a test ma ją importować;
    - otwieranie: w sandboxie treść VRT pod `.tif` jest odrzucana przed
      pierwszym `WarpedVRT`, a po nim zwykły `rasterio.open` czyta plik
      docelowy (zagrożenie potwierdzone); `open_raster` odrzuca `.tif`
      i `.asc` z treścią VRT przed i po. `a.tif.ovr` z treścią VRT: przy
      `EMPTY_DIR` brak nakładek, bez `EMPTY_DIR` po `WarpedVRT` odczyt
      nakładki czyta plik docelowy. Treść OGR VRT: `.gpkg` i `.geojson`
      odrzuca GDAL (prefiks), `.shp`, `.fgb`, `.tab` — tabela formatów
      (sygnatura, nagłówek); bez `GDAL_SKIP` zwykłe otwarcie `.geojson`
      czyta plik docelowy. Przy `EMPTY_DIR` Shapefile czyta `.shx .dbf
      .prj .cpg` (tekst w Windows-1250 dekoduje się tylko dzięki `.cpg`,
      `.dbf` ma LDID 0), MapInfo TAB — `.dat .map .id`. `stats()` (w
      rasterio 1.5 `statistics()` jest przestarzałe) przy
      `GDAL_PAM_ENABLED=NO` nie zapisuje `.aux.xml`, bez tej zmiennej —
      zapisuje;
    - dostarczanie (`tests/e2e/test_tile_headers.py`): MapLibre 6.14
      z `transformRequest` dodającym `X-Archiwista-CSRF` do żądań `Tile`
      tego samego pochodzenia — każdy kafel rastrowy miał nagłówek,
      `<img src="blob:…">` z `fetch` się wyświetla, zero naruszeń CSP
      v0.1 (`csp_header`, tryb offline: `connect-src 'self'`, `img-src
      'self' data: blob:`).
  - *Dla kroków 4, 5 i 7a.* Rastry otwierać tylko `open_raster(path,
    file_format(path), …)`, rio-tiler dostaje `Reader(str(path),
    dataset=src)`; wektory tylko przez `vector_source` (opcje otwarcia
    pyogrio jako argumenty, np. `IMMUTABLE="YES"` w stanie (a)); proces
    renderujący i czytnik danych własnych biorą `process_work_dir(paths)`
    we własnym procesie (katalog danych przekazany w argumentach albo
    w zmiennej `ARCHIWISTA_*`, która przechodzi przez `untrusted_env`).

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
  (linie, wielokąty), wersję ze starszym sidecarem bez `sha256` i dwa
  segmenty jednego zestawu w dwóch formatach (NMT ASC i ASCII-NMT: ten sam
  produkt, układy i rozdzielczość). Każdy przypadek regularny generator
  sprawdza czytnikiem Kartografa jak w v0.1 (`iter_store` bez problemu).
  Fixtury danych własnych: `make_own_folder` (GeoPackage z dwiema
  warstwami EPSG:2180, Shapefile z `.shp .shx .dbf .prj .cpg`, Shapefile
  bez `.prj`, GeoTIFF EPSG:2180, GeoTIFF bez georeferencji z plikiem
  świata, GeoJSON WGS84, FlatGeobuf, MapInfo TAB natywny, CSV i TXT jako
  nierozpoznane, plik ukryty, podkatalog, dowiązanie symboliczne poza
  folder, GeoPackage EPSG:5514 z punktem w punkcie kontrolnym),
  `project_inside_store(store_root)` (projekt z manifestem w katalogu
  producenta), `GpkgEditor` (edytor jak QGIS, także awaria zostawiająca
  `-wal` bez `-shm` i otwarcie do zapisu bez zmian danych),
  `write_snapshot_fixture` i pliki podstawione (`hostile_files`: treść
  VRT i OGR VRT pod nazwami danych, `a.tif.ovr` z treścią VRT, widok
  i tabela łączona MapInfo, raster deklarujący 100 000 × 100 000 px
  w kilku MB, ZIP z katalogiem centralnym deklarującym 200 000 wpisów).
- **Pliki:** `tests/fixtures/make_store.py`, `tests/fixtures/store_files.py`,
  `tests/fixtures/own_data.py`, `tests/fixtures/hostile_files.py`;
  `tests/contract/test_store_fixture.py` (nowe przypadki widziane przez
  Kartografa).
- **Interfejs:** `make_store` jak w v0.1 z nowymi przypadkami w manifeście
  oczekiwań (`ExpectedEntry` z rodziną pliku); `make_own_folder(path, *,
  families) -> OwnFolderManifest`; `GpkgEditor(path)` z `insert`, `commit`,
  `begin`, `close`, `crash_without_shm`, `reopen_for_update_unchanged`;
  `hostile_files(path) -> HostileFiles`.
- **Test/odbiór:** `tests/contract/test_store_fixture.py` zielony z nowymi
  rodzinami; `tests/unit/test_own_data_fixture.py` (komplet Shapefile,
  edytor zostawia zatwierdzone ramki w `-wal` i otwartą transakcję, a po
  awarii — `-wal` bez `-shm`); czas generatora 50 000 slotów zapisany
  w notatce kroku.
- **Zależności:** — (prawdziwy LAZ wymaga laspy z kroku 1 — ten przypadek
  dochodzi po nim). **Równolegle:** 0, 1, 3, 4, 7a.
- **Stan po kroku 2:**
  - *Magazyn (`make_store`).* Nowe rodziny `Family` w `ExpectedEntry.family`
    (raz na magazyn, ponad `slots`, pisane po projektach — część v0.1
    magazynu danego ziarna jest bajtowo bez zmian; `MIN_SLOTS` = 17 bez
    zmian, `slots` dalej liczy tylko przypadki `regular`): `png_preview`
    (`landcover/eu_corine_2018_preview/bbox/…png`, `EPSG:3857`, PNG bez
    georeferencji), `tif_classes` (`landcover/eu_corine_2018`, arkusz
    1:50 000, GeoTIFF `EPSG:3035` 512 × 512 z paletą `CLC_CLASSES`, nodata
    48), `tif_map` (`maps/pl_bdot10k_10000_tiff`, RGBA paskowy 4160 × 4160
    bez nakładek, kanał alfa), `pdf_map` (`maps/pl_bdot10k_10000_pdf`),
    `tif_oblique` (`oblique-orto/pl_2000/…/6.179.12.20.1_n.tif`,
    `EPSG:2177`, kafle 256, nakładki 2 i 4), `tif_wgs84`
    (`soil/global_soilgrids_clay_0-5cm_mean/bbox/…`, `EPSG:4326` `int16`,
    nodata −32768), `zip_citygml` (`models3d/pl_buildings_lod2_2017/teryt/`,
    człony `.gml` CityGML i `.pdf`), `laz_compressed` (prawdziwy LAZ:
    laspy + lazrs z kroku 1, LAS 1.4 PDRF 6, 120 000 punktów = 3 kawałki po
    50 000 z tablicą kawałków, klasy 2/3/6, WKT VLR `EPSG:2180`),
    `gpkg_layers` (`landcover/pl_bdot10k_gpkg_ptwp-swrs`: warstwy `swrs`
    LineString i `ptwp` Polygon), `zip_ascii_nmt`; przypadki `Case`:
    `file_family`, `no_sha256`, `two_formats` (ten sam arkusz w
    `nmt/pl_1992_1m_evrf2007` jako ASC i w `nmt/pl_1992_ascii-nmt_1m_evrf2007`
    jako ZIP z członem XYZ). Koderzy w `tests/fixtures/store_files.py`
    (rastry v0.2 pisze GDAL w pamięci, deterministycznie, `nonce` w metadanej
    `ARCHIWISTA_NONCE`): `png_image`, `geotiff_classes`,
    `geotiff_rgba_strips`, `geotiff_tiled_overviews`, `geotiff_wgs84`,
    `xyz_grid`, `zip_members`, `citygml`, `pdf_document`,
    `geopackage_layers`, `laz_points`, `reprojected_bounds`. Każdy wpis
    sprawdza `verify_store` (`iter_store`), obrysy offline — test kontraktu.
  - *Odstępstwa od planu.* (1) „Wersja ze starszym sidecarem bez `sha256`”
    nie istnieje w Kartografie 0.8.0: wpis `versions/` bez `sha256` to
    `invalid_sidecar` (`store._valid_version`), więc `no_sha256` to plik na
    ścieżce standardowej z sidecarem 0.7.x (`kind="link"`, bez
    `version_path`, etykiety i `sha8`). (2) PNG CORINE „z obrysem z godła”:
    `_sheet_footprint` Kartografa pomija sidecar kraju innego niż PL
    (CORINE = `EU`), więc podgląd arkusza nie miałby obrysu — fixtura bierze
    wycinek bbox (obrys z żądania); brak obrysu arkusza CORINE to kandydat
    na wymaganie SPEC 12. (3) GeoPackage dwuwarstwowy ma własny segment, bo
    część masowa 50 000 slotów wyczerpuje kody TERYT
    `landcover/pl_bdot10k_gpkg`. (4) ZIP LoD2 nie ma obrysu offline (TERYT
    z PRG), jak `zip_teryt` v0.1.
  - *Dane własne (`tests/fixtures/own_data.py`).*
    `make_own_folder(path, *, families=ALL_OWN_FAMILIES) ->
    OwnFolderManifest` (`root`, `files: tuple[OwnFile]`, `outside`,
    `file(family)`, `path(family)`, `indexed`); `OwnFile` (`family`, `path`,
    `members`, `indexed`, `driver`, `crs` — jak podaje GDAL, `layers:
    tuple[OwnLayer(name, geometry_type, feature_count)]`, `raster: (w, h,
    bands)`, `feature_count`). Rodziny `OwnFamily`: `gpkg_layers`
    (`kanalizacja.gpkg`, `przewody` + `zlewnie`, `EPSG:2180`), `shp_full`
    (`dzialki.shp .shx .dbf .prj .cpg`), `shp_no_prj`, `tif_2180`,
    `tif_world_file` (TIFF bez znaczników GeoTIFF + `skan.tfw`),
    `geojson_wgs84`, `fgb`, `tab_native` (`budynki.tab .dat .map .id`;
    OGR podaje typ warstwy `Unknown`, a układ jako WKT bez kodu EPSG —
    MapInfo CoordSys zapisuje `EPSG:2180` jako nienazwany TM na WGS84),
    `csv`, `txt`, `hidden` (`.ukryty.geojson`, `.ukryty_katalog/`),
    `subdir` (`archiwum/2025/punkty.geojson`), `symlink_outside`
    (`poza.geojson`, `katalog_poza` → `<folder>.poza/`), `gpkg_5514_control`
    (`punkt_3722.gpkg`, `POINT_3722.epsg5514` z `control_points.py`).
    `project_inside_store(store_root, name="w-magazynie") -> Path`
    (`<store>/projekty/<name>`; Kartograf widzi go jako nieznany segment).
    `GpkgEditor(path)` — osobny proces (`python -m tests.fixtures.own_data
    edit PATH`), `journal_mode=WAL`, `wal_autocheckpoint=0`, funkcje SQL
    `ST_IsEmpty`/`ST_MinX…` dla wyzwalaczy R*Tree GDAL: `begin`,
    `insert(layer, geometry, **values) -> fid`, `commit`,
    `reopen_for_update_unchanged` (przepisuje `gpkg_ogr_contents`,
    `gpkg_contents.last_change`, `gpkg_metadata_reference.timestamp`),
    `close`, `crash_without_shm`, `wal`, `shm`, menedżer kontekstu.
    `write_snapshot_fixture(folder, source, *, created_at, content=None,
    note, author, layers, raster, extent) -> SnapshotFixture(directory,
    label, document)`: `.wersje/<plik>/<RRRR-MM-DD>_<sha8>[_n]/`, kopia
    SQLite przez `Connection.backup`, pliki `0444`, katalog `0555`;
    `content` (metoda, sha256) wymagany dla SQLite i kompletów — fixtura nie
    liczy skrótu logicznego (to kod kroku 7a), sama liczy tylko `bytes`.
  - *Pliki podstawione (`tests/fixtures/hostile_files.py`).*
    `hostile_files(path) -> HostileFiles` (`root`, `targets` =
    `<path>-cel/`, `raster_target`, `vector_target`, `vrt_rasters` `.tif
    .asc`, `ogr_vrt_vectors` `.gpkg .geojson .shp .fgb`, `ovr_base`, `ovr`,
    `mapinfo_view`, `mapinfo_seamless`, `huge_raster`, `zip_many_entries`;
    `SECRET_VALUE` = 173, `SECRET_TEXT` = `tajne`). Sprawdzone 2026-10-19 bez
    sandboxa (GDAL 3.12): każdy VRT, OGR VRT i `a.tif.ovr` czyta cel; tabela
    łączona czyta człon spoza folderu; widok otwiera obie tabele spoza
    folderu i dopiero potem odmawia (brak indeksu `.IND`, którego sterownik
    OGR nie zapisuje); raster 100 000 × 100 000 ma 307 KB; ZIP deklaruje
    200 000 wpisów w rekordzie ZIP64, a `zipfile` go otwiera (1 człon).
  - *Czas.* `python -m tests.fixtures.make_store --slots 50000 --seed 1
    --projects 30`: 97,8 s (generacja i weryfikacja; 50 018 dowiązań,
    80 065 wersji, 26 segmentów). Każdy `make_store` jest dłuższy o ok.
    1,1 s (głównie mapa RGBA 4160 × 4160). Magazyn pomiarowy v0.1
    (`store-50k`) trzeba wygenerować od nowa przed krokiem 16:
    `tests/perf/test_store_50k.py::test_store_50k_generator_reproduces_store`
    porównuje całe drzewo.

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
- **Stan po kroku 3:**
  - *Umowa źródła.* `CoordinateTransformer.gdal_operation() -> str`
    w `sources/protocol.py`; adapter Kartografa woła
    `pinned_transform(src, dst).gdal_operation()` w wątku wywołującym
    (błąd Kartografa → `ProducerError`). Testowa operacja pyproj
    z tą metodą: `tests/fixtures/index_data.py::PyprojOperation` (wspólna
    dla `test_coverage.py` i `test_geometry.py`).
  - *Obrys WGS84* (`index/geometry.py`): `outline_wgs84(native: BBox,
    native_crs: str, transformer: CoordinateTransformer | None, *,
    max_segment_m: float = MAX_SEGMENT_M) -> GeoJSONGeometry` (`Polygon`;
    `MAX_SEGMENT_M = 5000.0`). Odstępstwo od umowy: `transformer` może
    być `None` — tylko dla układu WGS84 (`is_wgs84(crs)`: `EPSG:4326`,
    `OGC:CRS84`, wielkość liter bez znaczenia), który nie jest
    przeliczany; dla innego układu `None` to `ValueError`. Pierścień
    przeciwnie do ruchu wskazówek zegara od narożnika SW, każdy narożnik
    jest wierzchołkiem, krawędzie dzielone na równe części ≤
    `max_segment_m` (w układzie geograficznym `max_segment_m / 111 320`
    stopnia). `outlines_wgs84(natives, native_crs, transformer, *,
    max_segment_m)` — prostokąty jednego układu jednym wywołaniem
    `transform`. Pozycja nieskończona po przeliczeniu → `ValueError`
    (tekst `index_outline_not_finite`). Także `box_within(bounds,
    polygon)` (tolerancja ok. 1 m) i stała `WGS84`.
  - *Skaner.* `outline_footprints(adapter, items) -> (items, failures)`
    (`archiwista.index.scanner`) w puli obrysów (`_locate`) i w zadaniu
    `footprints` (`jobs/worker.py`): grupy po `native_crs`, jedno
    `transform` na grupę; gdy paczka zawiedzie, każdy prostokąt osobno —
    wersja, której obrysu nie da się przeliczyć, zostaje bez położenia
    (`pending`) z komunikatem w `footprints_failed`, pozostałe dostają
    obrysy. Producent bez `GeoAdapter` zostaje przy swoim `wgs84`.
  - *Doprecyzowanie decyzji 4.* Własny obrys WGS84 producenta zostaje,
    gdy nie jest prostokątem albo gdy leży w wielokącie z obrysu
    natywnego (z tolerancją ok. 1 m), bo jest wtedy ciaśniejszy. To
    przypadek arkuszy PL-1992 z godła: Kartograf daje dokładny prostokąt
    w długości i szerokości geograficznej, a obrys natywny jest jego
    obwiednią w EPSG:2180; wielokąt z obwiedni poszerzyłby arkusz (przy
    15,5° E o ok. 115 m dla 1:10 000 i 230 m dla 1:25 000), więc te
    obrysy zostają prostokątami (`is_box`, jak w 0.1.0, z obszarem
    w SQL). Wielokąty dostają obrysy z nagłówka, `request.bbox`,
    jednostek oraz arkusze PL-2000, TM33 i SM5.
  - *Indeks.* `SCHEMA_VERSION` 4 → 5 przy niezmienionych tabelach: inna
    wersja oznacza przebudowę indeksu i pełny skan przy starcie (opis
    w CHANGELOG — krok 18). R*Tree i `versions.min_*/max_*` z obwiedni
    wielokąta; `/map/footprints`, karta wersji i filtr obszaru czytają
    wielokąt z `version_shapes.wgs84` bez zmian w zapytaniach.
  - *Fixtura* `tests/fixtures/control_points.py`: `POINT_3722`
    (`ControlPoint`: `number`, `cadastral_area`, `sjtsk_y`, `sjtsk_x`,
    `lat`, `lon`, `method`, `service`, `layer`, `object_id`, `recorded`,
    `recording`; `epsg5514 -> (x, y)`, `etrs89 -> (lon, lat)`).
  - *Próby.* `test_cz_outline_vertex_within_2_m`: wierzchołek obrysu
    0,67 m od φ, λ ETRS89; obwiednia 0.1.0 (podmiana `outline_footprints`
    na funkcję bez zmian) — 202,5 m, test nie przechodzi.
    `test_outline_wgs84_pl_west_sheet_is_rotated`: narożniki obwiedni
    arkusza 5 × 5 km przy 14,2° E ok. 330 m od narożników arkusza. Pełny
    skan 3000 slotów (4821 obrysów) na dysku lokalnym: 3,1–3,4 s
    z obwiedniami, 3,45–3,47 s z wielokątami.

### 4. Infrastruktura podglądów: pamięć, pula, zadanie `preview`
- **Cel:** wszystko, czego potrzebują renderery, bez samych rendererów:
  `PreviewCache` z LRU i limitem (`AppSettings.preview_cache_limit_gb`,
  `AppPaths.previews_dir`; wersje rendererów per rodzaj, małe obiekty
  jako bajty, zapis czasu użycia najwyżej raz na 5 min, uzgadnianie przy
  starcie, klucze ścieżki i obiektów złożonych — decyzja 3), `RenderPool`
  z procesami renderującymi i protokołem JSON Lines (limity czasu per
  operacja, komunikaty błędów bez ścieżek, wyniki błędów w pamięci według
  decyzji 3), rejestr `RENDERERS` (z rendererem testowym w testach),
  rodzaj zadania `preview` w `JOB_KINDS`/`RUNNERS` z budową każdego
  pliku w osobnym procesie potomnym (najwyżej `n = max(1, cpu // 2)`
  naraz, jedno zadanie `preview` naraz), uogólnienie nadzorcy (`store`
  opcjonalny, reguła konfliktu per rodzaj, dołączanie do trwającego
  `preview` z dopisaniem `ref`), włączenie puli w `serve` (start,
  zatrzymanie, `app.state.previews`), typy błędów podglądów, teksty
  powodów i stylów.
- **Pliki:** `archiwista/previews/{__init__,types,cache,pool,worker,protocol,build}.py`,
  `archiwista/previews/renderers/__init__.py`, `archiwista/config.py`,
  `archiwista/errors.py` (`PreviewBusyError`, `PreviewTimeoutError`,
  `PreviewUnavailableError`), `archiwista/jobs/{protocol,supervisor,worker}.py`,
  `archiwista/server.py`, `archiwista/app.py`, `archiwista/texts/previews.py`,
  `archiwista/messages.py` (scalanie słowników — umowa „Modele i teksty”).
- **Interfejs:** umowy „Podglądy” (typy, pamięć, pula, zadanie)
  i „Zadania”; procesy uruchamia sandbox z kroku 1.
- **Test/odbiór:** `tests/integration/test_preview_cache.py`
  (`test_cache_limit_evicts_least_recently_used`,
  `test_cache_limit_holds_with_builds` — limit 1 MB, suma ≤ limit po
  każdym zapisie, obiekty w budowie chronione,
  `test_cache_survives_restart`, `test_cache_safe_across_processes`,
  `test_hit_survives_eviction_by_other_process` — trafienie, potem
  usunięcie obiektu przez inny proces: odpowiedź kompletna,
  `test_reconcile_after_crash` — pliki bez wpisu i wpisy bez plików
  uzgodnione przy starcie, `test_renderer_version_bump_keeps_other_kinds`),
  `tests/integration/test_render_pool.py` (`test_single_flight_same_key`,
  `test_timeout_kills_and_respawns_worker`,
  `test_memory_limit_kills_worker`, `test_abandoned_request_never_rendered`,
  `test_queue_full_is_preview_busy`, `test_worker_env_has_no_network` —
  próba połączenia z GDAL w procesie renderującym kończy się bez ruchu
  sieciowego, `test_vrt_refused_after_warpedvrt_in_same_worker` — proces
  po `WarpedVRT` czyta przez tabelę formatów: treść VRT jako `.tif`,
  `a.tif.ovr` z treścią VRT i treść OGR VRT jako `.gpkg`, `.geojson`,
  `.shp` nie oddają bajtów pliku docelowego,
  `test_failure_detail_has_no_paths`,
  `test_unreadable_cached_as_code_and_timeout_not_cached`),
  `tests/integration/test_jobs.py::test_preview_build_joins_running_job`,
  `::test_preview_build_item_timeout_fails_item_only`
  i `::test_preview_builds_at_most_n_children`.
- **Zależności:** 1. **Równolegle:** 2, 3, 7a, 7b.
- **Stan po kroku 4:**
  - *Typy* (`previews/types.py`, tylko biblioteka standardowa i tabela
    formatów): `PreviewSource(ref, content_key, paths, format_hint=None,
    size_bytes=None, crs=None, georeference=None, product=None,
    dataset_key=None, nodata=None, mutable=False, stat=None)` z `format`,
    `kind`, `renderer` i `to_json`/`from_json`; `format_hint` to
    `FileFormat.name` z tabeli formatów (bez niego — rozszerzenie pliku
    głównego); `georeference` i kadr miniatury to `Extent(bbox, crs)`;
    `stat` to `SourceStat(main, wal)` z `FileStat(size_bytes, modified_ns)`.
    `PreviewKind` = `FormatKind` (`PREVIEW_KINDS`), `PREVIEW_STATES`,
    `PREVIEW_REASONS`, `STYLE_NAMES`, `RENDERER_NAMES`, `RENDERER_OF_KIND`
    (`raster`/`image` → `raster`, `auxiliary`/`unknown`/`document` →
    `document`), `TRANSIENT_REASONS` (`timeout`, `memory_limit`,
    `missing_file`, `store_unavailable`, `changed_since_scan` — nigdy
    w pamięci podglądów), `UNRENDERABLE_REASONS` (`unreadable`,
    `unsupported_format` — pula odpowiada nimi od razu, zadanie nie buduje),
    `CONTENT_KEY`, `COG_NAME`. `PreviewProbe` (pola z umowy: `kind`, `driver`,
    `width`, `height`, `bands`, `dtype`, `crs`, `bbox_native`, `bbox_wgs84`,
    `minzoom`, `maxzoom`, `overviews`, `tiled`, `nodata`, `stats`
    — `BandStats(p2, p98, min, max)`, `palette` — `PaletteEntry(value,
    color)`, `layers` — obiekty JSON kroku 5b, `points` — obiekt JSON kroku
    5c, `members`, `needs_cog`, `pixels`, `unpacked_bytes`, `reason`)
    z `to_json`/`from_json` i `to_bytes`/`from_bytes` (`info.json`).
    `build_product(probe)` — nazwa tego, co buduje zadanie (`cog.tif` przy
    `needs_cog` bez powodu; `source.gpkg` dopisze krok 5b),
    `auto_build(source, probe)` — progi decyzji 6 (2 GiB pliku, 10⁹ px,
    8 GiB po rozpakowaniu). Protokół `Renderer`: `kinds`, `probe(source)`,
    `thumbnail(source, probe, style, size, frame)`, `tile(source, probe,
    style, z, x, y, params)`, opcjonalnie `features(source, probe, layer,
    bbox_wgs84, zoom, limit) -> dict`, `members(source) -> dict`,
    `build(source, probe, out_path)`. Renderer zgłasza
    `PreviewUnavailableError(reason, detail)`; `FormatRefusedError` →
    `unsupported_format`, `FileNotFoundError` → `missing_file`,
    `MemoryError` → `memory_limit`, każdy inny wyjątek → `unreadable`
    (komunikat jako `detail`). Rozpoznanie z powodem trafia do renderera
    (miniatura pliku `no_crs` jest możliwa) — ocenia go renderer.
  - *Pamięć* (`previews/cache.py`): API z umowy oraz `has(key, name)` (bez
    zapisu użycia), `incoming_dir()` (katalog roboczy procesu w
    `.incoming/`, w nim zadanie pisze COG), `set_limit(limit_bytes)`,
    `clock=` (testy), `CacheKey.directory`; nazwy `INFO_NAME`, `COG_NAME`,
    `SOURCE_GPKG_NAME`, `thumbnail_name(style, size, frame)`,
    `tile_name(style, z, x, y, params)` (styl `[A-Za-z0-9_-]+`; kadr
    i parametry kafla jako skrót `params_digest` 12 znaków);
    `composite_key(op, contents, frame_or_tile, style, size)` =
    `sha256("composite:" + "\n".join([op, *sorted(contents), frame_or_tile,
    style, size]))`; `path_key(store, path, size_bytes, modified_ns)` =
    `sha256(f"path:{store}:{path}:{size_bytes}:{modified_ns}")` (czas
    `st_mtime_ns`). `RENDERER_VERSIONS` — wszystkie 1; każda zmiana kodu
    renderera podnosi jego wersję jedną linią, a `reconcile` usuwa obiekty
    innych wersji. `cache.sqlite` (`user_version` 1): `objects`, `files`,
    `pins` (właściciel `<host>_<pid>`), `totals` utrzymywane wyzwalaczami;
    zmiana nazwy pliku przy `put` i usuwanie przy eksmisji dzieją się
    w tej samej transakcji `BEGIN IMMEDIATE` co wiersze. `put(key, name,
    Path)` przenosi plik; `unpin` bez `pin` → `ValueError`. Sandbox:
    `process_dir(root)`, `prune_dead_process_dirs(root)`, `process_owner()`,
    `owner_alive(owner)` — jedna implementacja katalogów
    `<host>_<pid>_<token>` (`process_work_dir(paths)` =
    `process_dir(paths.work_dir)`, zachowanie bez zmian).
  - *Protokół i proces renderujący* (`previews/protocol.py`, `worker.py`):
    `RENDER_WORKER_COMMAND` = `python -P -m archiwista.previews.worker
    [--work-dir DIR]`; `RenderRequest(id, op, source, params)`,
    `RenderAnswer(id, files, code, detail)`, `encode_*`/`decode_*`,
    `scrub_paths(text, paths, *, directories)` (ścieżki źródła i po
    `realpath` → nazwa pliku, ścieżka w ich katalogu → nazwa w nim, katalog
    → jego nazwa; także katalog roboczy). Rejestr `OPERATIONS` w `worker.py`:
    `Operation(timeout_s, handler, result, target)` — `probe` 20 s
    (`info.json`), `thumbnail` 30 s (parametry `style`, `size`, `frame`
    `{bbox, crs}` albo brak; `image.png` pod `thumbnail_name`), `tile` 15 s
    (`style`, `z`, `x`, `y`, reszta — np. `rescale` — w skrócie nazwy;
    `image.png` pod `tile_name`), `features` 15 s (`layer`, `bbox` WGS84,
    `zoom`, `limit`; `features.json`), `members` 10 s (`members.json`);
    dwie ostatnie poza pamięcią. Krok 5a3 dopisuje `layer_thumbnail` (60 s)
    i `layer_tile` (15 s) po jednej linii: `handler(renderers, request) ->
    dict[str, bytes]`, `target(source, params) -> (CacheKey, nazwa) | None`,
    `source` może być `None`, gdy parametry niosą wersje. `BUILD` (600 s)
    tylko dla zadania. `main(argv, *, renderers=None)` (testy podają własne
    renderery), `work_dir()` — katalog roboczy procesu dla rendererów (np.
    kopie SQLite kroku 5b), `renderer_for(renderers, source)`. Plik roboczy
    (`mutable`) sprawdzany przed i po operacji (`changed_since_scan`); po
    `MemoryError` proces odpowiada `memory_limit` i kończy się (kod 3).
    Rejestr `RENDERERS` (`renderers/__init__.py`) jest pusty — kroki 5a1–5c
    dopisują po linii; bez renderera rodzaju → `unsupported_format`.
  - *Pula* (`previews/pool.py`): `RenderPool(*, workers, cache,
    timeouts=None, command=RENDER_WORKER_COMMAND, work_dir=None,
    queue_size=64, idle_s=300, memory_bytes=2 GiB, failure_s=600)`,
    `start()`/`close()` (albo `with`), `request(op, source, params=None, *,
    timeout_s=None) -> RenderResult` (blokujące; CLI), `arequest(...)`
    (asynchroniczne; anulowanie zadania asyncio porzuca żądanie — krok 6
    anuluje je po rozłączeniu klienta), `stats() -> PoolStats(workers, alive,
    queued, rendering, rendered, abandoned)` (`rendered` — licznik żądań
    procesów renderujących, np. dla `test_same_content_rendered_once`),
    `.cache`, `.workers`; `default_render_workers()` = `min(4, cpu)`.
    `RenderResult(data, cached, detail)` z `json()` i `probe()`. `probe`
    z trwałym powodem to wynik (`info.json` z `reason`; `detail` tylko dla
    żądania, które go wywołało), nie wyjątek; pozostałe:
    `PreviewUnavailableError(reason, detail)`, `PreviewTimeoutError` (także
    przez 10 min po przekroczeniu), `PreviewBusyError(retry_after_s=2)`
    (pełna kolejka i zamykanie). Pula dokłada do żądań rozpoznanie z pamięci
    (`params["probe"]`), więc proces nie rozpoznaje pliku drugi raz. Proces
    zakończony bez odpowiedzi: `SIGKILL` (zabójca OOM systemu) →
    `memory_limit`, inaczej → `unreadable`.
  - *Zadanie `preview`* (`previews/build.py`, `RUNNERS["preview"]`):
    parametry `{"refs", "contents", "force"}` — odstępstwo od umowy:
    `contents` (klucz treści każdego `ref`, w tym samym porządku) pozwala
    nadzorcy dołączać po treści bez rozstrzygania `ref`; krok 9 filtruje
    `refs` i `contents` razem. `force` = budowa ponad progi `auto_build` (bez
    niego taki plik → `too_large`). `ref` → źródło przez `RESOLVERS` (rodzaj =
    tekst przed pierwszym `:`; fabryka `(JobSpec) -> (ref) -> PreviewSource`,
    w głównym wątku zadania): w kroku 4 pusty — krok 6 dopisuje `"version"`,
    krok 9 `"file"` i `"snapshot"`; błędy `NotFoundError`,
    `PathOutsideRootError`, `PreviewUnavailableError`, nieznany rodzaj →
    `invalid_ref`. `BUILD_COMMAND`, `BUILD_TIMEOUT_S` (600),
    `BUILD_MEMORY_BYTES` (4 GiB), `build_processes()` = `max(1, cpu // 2)`.
    Wynik `{"built", "cached", "failed": [{"ref", "code", "detail"}],
    "seconds"}`, `detail` po polsku (tekst powodu i komunikat biblioteki,
    bez ścieżek); postęp `current`/`total` treści z `built`, `cached`,
    `failed`. Przerwanie zabija procesy budowy.
  - *Nadzorca* (`jobs/`): `JobSpec.store: str | None`, nowe `previews_dir`
    i `work_dir`, `PROTOCOL_VERSION` 2; `JobRule(store, network=False,
    exclusive=False, conflict=None, join=None)` w `JOB_RULES`,
    `JobConflict(domain, key(store, params), message)`, `JobJoin(merge(active,
    new) -> params | None, states)`, `MAX_PREVIEW_REFS` = 500 (także po
    dołączeniu); `INDEX_JOB_KINDS` i `NETWORK_JOB_KINDS` usunięte.
    `submit(kind, *, store=None, params, actor)`: rodzaj z magazynem bez
    niego albo `preview` z magazynem → `ValueError`. `preview` dołącza do
    najstarszego aktywnego zadania, które ma wszystkie jego treści (`force`
    zadania ≥ `force` zlecenia) — `params` zadania dostają nowe `ref`,
    `submit` zwraca to zadanie; trwa najwyżej jedno `preview` na nadzorcę
    (`exclusive`), zajmuje jedno miejsce `max_jobs`. Nowy rodzaj (7b
    `own_scan`, 8 `snapshot`): linia w `JobKind`, linia w `JOB_RULES` (z
    `JobJoin(…, ("queued",))` albo `JobConflict`), gałąź `_job_params`,
    linia `RUNNERS`.
  - *Serwer i ustawienia*: `serve` otwiera `PreviewCache(paths.previews_dir,
    limit_bytes=settings.preview_cache_limit_bytes)`, uzgadnia ją
    (`reconcile`) i uruchamia `RenderPool(workers=default_render_workers(),
    cache, work_dir=paths.work_dir)`; zmiana `preview_cache_limit_gb` →
    `cache.set_limit`; `create_app(…, previews=pool)` → `app.state.previews`
    (pamięć: `pool.cache`); przy zatrzymaniu najpierw pula, potem pamięć.
    `AppSettings.preview_cache_limit_gb` (1–10 000, GB po 1024³ bajtów,
    właściwość `preview_cache_limit_bytes`) jest też w modelu API `Settings`
    — bez tego `PUT /settings` z interfejsu przywracałby 20.
  - *Teksty i błędy*: `texts/previews.py` (`PREVIEW_MESSAGES`:
    `preview_reason_<kod>`, `preview_fix_<kod>`, `preview_style_<styl>`,
    `preview_busy`, `preview_closed`, `preview_timeout`,
    `preview_timeout_recent`, `job_kind_preview`, `preview_build_*`);
    `messages.py`: `MESSAGES = merge_messages({…}, PREVIEW_MESSAGES,)` —
    jedna linia na słownik, powtórzony klucz → `ValueError` przy imporcie.
    `errors.py`: `PreviewBusyError(message, *, retry_after_s)`,
    `PreviewTimeoutError(message)`, `PreviewUnavailableError(reason,
    detail=None)` (`reason`, `detail`; tekst polski dla API — z
    `preview_reason_<kod>` i `preview_fix_<kod>`, krok 6).
  - *Próby*: `tests/integration/test_preview_cache.py` (16 testów, ok.
    1,5 s; limit 1 000 000 B), `tests/integration/test_render_pool.py`
    (9 testów, ok. 10 s; prawdziwe procesy renderujące z rendererem
    testowym `tests/fixtures/render_worker.py`, sterowanym treścią pliku),
    trzy testy `preview` w `tests/integration/test_jobs.py` (ok. 15 s; haki
    `ARCHIWISTA_TEST_PREVIEW_SOURCES`, `…_BUILD_TIMEOUT_S`,
    `…_BUILD_PROCESSES` w `tests/fixtures/job_worker.py`). W procesie
    renderującym po `WarpedVRT` treść VRT jako `.tif`/`.asc` i treść OGR VRT
    jako `.gpkg`, `.geojson`, `.shp`, `.fgb` są odrzucane, `a.tif` nie ma
    nakładek z `a.tif.ovr`; `/vsicurl/` i GeoJSON z adresu — żadnego
    połączenia z nasłuchującym portem. `archiwista serve` z pustym katalogiem
    danych tworzy `previews/cache.sqlite` i kończy się czysto.

### 5a1. Podglądy rastrów: rozpoznanie, miniatura, kafel
- **Cel:** renderer `raster.py` dla rodzin rastrowych z decyzji 5:
  otwarcie jawnym sterownikiem (decyzja 3), rozpoznanie (sterownik,
  wymiary, typ, układ pliku albo `source.crs`, georeferencja z obrysu dla
  JPEG, nakładki, kafelkowanie, `nodata`, statystyki w numpy z odczytu
  zdziesiątkowanego, paleta, reguła `needs_cog`, progi pikseli z decyzji
  6), miniatura (rio-tiler z otwartego zbioru w układzie pliku; bez
  nakładek z odczytu `out_shape` ≤ 1024 px; z kadrem — przeliczona
  z wymuszoną operacją), kafel (decyzja 4: `reproject` z nakładki na
  siatkę kafla z `COORDINATE_OPERATION`, potem `ImageData` i PNG; margines
  pikseli na życzenie stylu, żeby style sąsiedztwa nie dawały szwów),
  style `rgb` i `gray` (rozciągnięcie 2–98%) w rejestrze `STYLES`.
- **Pliki:** `archiwista/previews/renderers/raster.py`,
  `archiwista/previews/tiles.py` (siatka kafla, wybór nakładki, margines),
  `archiwista/previews/styles.py` (rejestr i style obrazów).
- **Interfejs:** `Renderer` z umowy; `Style` (`apply`, `margin_px`,
  legenda).
- **Test/odbiór:** `tests/unit/test_raster_renderer.py` (rodziny rastrowe
  z kroku 2 czytane w miejscu: miniatura dekodowalna, kafel 256 × 256
  z alfa, `nodata` przezroczyste, PNG → `no_georeference`, EPSG:4326
  (konwersja bez wymuszonej operacji) i EPSG:2177 na mapie; raster bez
  nakładek — miniatura i statystyki z odczytu zdziesiątkowanego; raster
  deklarujący 100 000 × 100 000 px w kilku MB → `needs_build` bez
  `auto_build`; treść VRT pod nazwą `.tif` i `.asc` → bez odczytu pliku
  docelowego; po rozpoznaniu folder bez `.aux.xml`;
  `test_tile_forces_pinned_operation` — `reproject` dostaje
  `COORDINATE_OPERATION` z `gdal_operation()` dla układów innych niż
  WGS84);
  `tests/integration/test_cz_control_point.py::test_cz_preview_tile_within_2_m`
  (GeoTIFF: jasny piksel w punkcie 3722 w kaflu z = 19, środek plamy
  ≤ 2 m od φ, λ).
- **Zależności:** 1, 2, 3, 4. **Równolegle:** 5b, 5c, 6, 7b, 8.

### 5a2. Podglądy rastrów: lokalny COG
- **Cel:** budowa COG (decyzja 6) w `previews/cog.py` dla ASC, XYZ, JPEG
  z georeferencją z obrysu nagłówkowego i GeoTIFF paskowego albo bez
  nakładek z bokiem > 4096 px: odczyt zdziesiątkowany do ≤ 8192 px,
  uśrednianie dla wartości ciągłych, `nearest` dla klas, nakładki
  wewnętrzne, DEFLATE z predyktorem albo JPEG; w `raster.py` tylko
  przypisanie `build`; kafle i miniatury z COG idą drogą z kroku 5a1.
- **Pliki:** `archiwista/previews/cog.py`,
  `archiwista/previews/renderers/raster.py` (jedna linia).
- **Interfejs:** `Renderer.build` z umowy; COG w pamięci podglądów.
- **Test/odbiór:** `tests/unit/test_raster_cog.py` (ASC → COG ≤ 8192 px
  z układem z `EntryMeta.horizontal_crs`, XYZ → COG, siatka nieregularna →
  `unsupported_format`, paskowy > 4096 px → COG, JPEG z obrysem `header`
  → georeferencja, obrys z innego źródła → `no_georeference`, klasy
  `nearest`); `tests/integration/test_cz_control_point.py::test_cz_preview_tile_within_2_m`
  rozszerzony o JPEG SM5 z obrysem nagłówkowym w S-JTSK (kafel z COG
  ≤ 2 m).
- **Zależności:** 5a1. **Równolegle:** 5a3, 5b, 5c, 6, 7b, 8, 10, 11, 12a.

### 5a3. Podglądy rastrów: style, legendy, składanie warstw
- **Cel:** style `hillshade` (azymut 315°, wysokość 45°, przewyższenie
  z rozmiaru piksela w metrach; margines 1 piksela, bez szwów między
  kaflami), `hypsometry` (legenda p2–p98 albo `rescale`), `classes`
  (paleta pliku albo tablica CLC i HSG A–D); legendy (`legends.py`:
  gradient z zakresem i jednostką, klasy z kolorem i polską nazwą);
  składanie warstw w `compose.py` dla rastrów i wektorów:
  `layer_thumbnail` (miniatury wersji w kadrze układu płaskiego)
  i `layer_tile` (kafel warstwy = nałożenie kafli wersji z pamięci po ich
  treści; brakujący kafel wersji liczy renderer jej rodzaju i zapisuje pod
  jej treścią — decyzje 4 i 7), obie jako operacje puli.
- **Pliki:** `archiwista/previews/styles.py`, `archiwista/previews/legends.py`,
  `archiwista/previews/classes.py` (tablice CLC i HSG),
  `archiwista/previews/compose.py`, `archiwista/previews/worker.py` (jedna
  linia na operację).
- **Interfejs:** style i legendy w `PreviewProbe`/`PreviewInfo`; operacje
  `layer_thumbnail` i `layer_tile` z umowy „Pula”.
- **Test/odbiór:** `tests/unit/test_raster_styles.py` (cieniowanie bez
  szwu na granicy sąsiednich kafli, hipsometria z legendą p2–p98
  i z `rescale`, klasy CORINE i HSG z legendą), `tests/unit/test_compose.py`
  (`test_layer_thumbnail_in_planar_frame`,
  `test_layer_tile_composes_version_tiles` — kafel na styku dwóch arkuszy
  ma piksele obu, kafle wersji zostają w pamięci pod ich treścią, nowa
  gotowa wersja zmienia klucz obiektu złożonego tylko w kaflach, które
  przecina).
- **Zależności:** 5a1. **Równolegle:** 5a2, 5b, 5c, 6, 7b, 8, 10, 11, 12a.
- **Stan po kroku 5a (5a1–5a3; commity `6be84a2` i następny):**
  - *Renderer* (`renderers/raster.py`, `RasterRenderer`, pierwszy
    w `RENDERERS`; `RENDERER_VERSIONS["raster"]` = 1): otwarcie przez
    `open_raster` ze sterownikiem formatu; georeferencja pliku, a bez niej
    indeksu (`PreviewSource.crs`, `georeference`) — w `PreviewProbe`
    (`bbox_native`, `crs`). Statystyki: numpy z odczytu `out_shape`
    ≤ 1024 px (GDAL bierze nakładkę), a plik bez nakładek > 64 Mpx — 64
    okna 128 px rozłożone po pliku (raster 100 000 × 100 000 px w ok.
    0,1 s). `needs_cog`: sterownik `AAIGrid`/`XYZ`, georeferencja albo
    układ z indeksu (COG je niesie), bok > 4096 px przy pasach albo bez
    nakładek. Style i styl domyślny (pola `styles`, `default_style`,
    `unit`, `class_table` dodał krok 6): `nmt`/`nmpt` → `hillshade`
    (`unit` = `m`), `corine`/`hsg` albo paleta → `classes`, ≥ 3 kanały →
    `rgb`, pozostałe ciągłe → `hypsometry`; obraz z paletą → `rgb`.
    Odstępstwo: `rgb` nie rozciąga 8-bitowego obrazu barwnego (ortofoto,
    mapy, podgląd WMS — barwy już do oglądania); rozciąga `gray`, dane
    > 8 bitów i `rescale`. Miniatura bez kadru — odczyt zdziesiątkowany
    w układzie pliku (rio-tiler tylko koduje PNG); z kadrem i kafel —
    `tiles.warp`: okno pliku potrzebne części siatki, odczyt
    zdziesiątkowany (najbliższa nakładka), `reproject` z
    `COORDINATE_OPERATION` = `transformer(układ, 3857).gdal_operation()`
    (EPSG:4326/OGC:CRS84/3857 bez niej); tylko część siatki pokryta
    rastrem. Dla `needs_cog` czyta COG z pamięci, bez niego plik
    (`too_large` dla pliku ponad progi bez nakładek).
  - *Dla innych kroków* (`tiles.py`): `transformer(src, dst)`,
    `operation(src, dst)`, `wgs84_bounds`, `map_placement(bbox, crs, w, h)
    -> MapPlacement(bbox_wgs84, minzoom, maxzoom)` (maks. = zoom natywny
    + 2 ≤ 22, min. = cały plik w jednym kaflu), `tile_bounds`, `tile_grid`,
    `frame_shape`, `pixel_metres`, `RasterView`/`raster_view`, `warp`,
    `read_values`, `encode_png`; `raster.open_cog/view_of/render_tile/
    render_thumbnail`; `cog.write_cog` (krok 5c). Proces renderujący:
    `--previews-dir` (pula), `worker.cached_file(source, name)`
    (dowiązanie pliku pamięci na czas odczytu), `cached_bytes`,
    `object_file`/`parse_object_file` — pula zapisuje pliki innych obiektów
    z odpowiedzi (kafle wersji z `layer_tile`); `main()` działa w module
    importowanym (przy `python -m` renderery widziały katalogi `None`).
  - *COG* (`cog.py`): ≤ 8192 px, `average`/`nearest` (klasy, paleta),
    bloki 512, nakładki COG, DEFLATE z predyktorem (2 całkowite, 3
    zmiennoprzecinkowe) albo JPEG 90 dla 8-bitowego RGB z maską; nodata
    pliku, NaN albo wolna wartość; paleta zachowana. Statystyki z próbki
    sprzed budowy (build nie zmienia `info.json`).
  - *Style i warstwy:* `styles.STYLES` (`rgb`, `gray`, `hypsometry`,
    `elevation`, `hillshade` z marginesem 1 px i przewyższeniem √(piksel
    w m) w 1–25, `classes`), `legends.legend(probe, style, *, rescale)`
    (gradient z `colors`, klasy z polskimi nazwami z `classes.py`: CLC po
    `GRID_CODE` 1–44 i kodzie, HSG 1–4 = A–D), `compose.py`:
    `layer_thumbnail` (60 s) i `layer_tile` (15 s) w `OPERATIONS`;
    parametry `versions: [{source, bounds}]` (od najstarszej; `bounds`
    WGS84 wymagane dla kafli — klucz obiektu złożonego tylko z wersji
    przecinających kafel), `frame`, `style`, `size` albo `z`, `x`, `y`.
    Wersja z COG wyrzuconym z pamięci jest rysowana z pliku.
  - *Próby:* `tests/unit/test_raster_renderer.py` (12),
    `test_raster_cog.py` (8), `test_raster_styles.py` (5),
    `test_compose.py` (2, prawdziwa pula) — razem z `test_render_pool.py`
    i `test_imports.py` 50 zielonych. Szew cieniowania: mozaika 2 × 2
    kafli = jedno renderowanie kadru (bez marginesu różnica ok. 24 na
    styku). Próba warp jak w kroku 1: 0,665 m (z = 19).
    `test_cz_preview_tile_within_2_m` (GeoTIFF i JPEG SM5 przez lokalny
    COG) w `tests/integration/test_cz_control_point.py` dopisany z próbami
    kroku 11 (`02228f4`): środek znaku w punkcie 3722 na kaflach z = 19
    leży 0,667 m (GeoTIFF) i 0,669 m (JPEG SM5) od współrzędnych ETRS89
    ČÚZK.

### 5b. Podglądy wektorów
- **Cel:** renderer `vector.py`: rozpoznanie przez pyogrio z jawnym
  sterownikiem (prefiks `GPKG:`/`GeoJSON:` albo sygnatura pliku — decyzja
  3; warstwy, typ geometrii, liczba obiektów, pola, układ, zasięg, próbka
  20 wierszy), miniatura (rasteryzacja próbki ≤ 50 000 obiektów do 3
  największych warstw liniowych i powierzchniowych albo wskazanej
  `layer`; punkty jako znaczniki; w układzie pliku albo w kadrze),
  `features` (prostokąt widoku WGS84 → układ pliku przypiętą operacją po
  zagęszczeniu; `max_features = limit + 1` → `truncated`; geometrie
  uproszczone do zoomu żądania, razem ≤ 500 000 wierzchołków — decyzja 4;
  obiekty do WGS84 przypiętym transformatorem; atrybuty bez zmian, długie
  teksty skrócone), otwarcie GeoPackage magazynu jako niezmiennego
  (`IMMUTABLE=YES`), a plików roboczych według trzech stanów z decyzji 8
  (`consistent_sqlite_read` z kroku 7a; w stanach (b) i (c) z kopii
  spójnej `source.gpkg` w pamięci podglądów).
- **Pliki:** `archiwista/previews/renderers/vector.py`,
  `archiwista/previews/rasterize.py`.
- **Interfejs:** `Renderer` z `features`; miniatura w kadrze dla
  `compose.py` (5a3).
- **Test/odbiór:** `tests/unit/test_vector_renderer.py` (GeoPackage
  z dwiema warstwami, Shapefile, Shapefile bez `.prj` → `no_crs`,
  GeoJSON, FlatGeobuf; `limit` 5000 i `truncated`;
  `test_features_simplified_to_zoom` — wielokąty po 50 000 wierzchołków
  przy małym zoomie: odpowiedź ≤ 500 000 wierzchołków i `truncated`, przy
  dużym zoomie odchyłka ≤ 1 piksel; prostokąt widoku w EPSG:2180
  i EPSG:5514; treść OGR VRT pod nazwą `.gpkg`, `.geojson`, `.shp`,
  `.fgb` → bez odczytu pliku docelowego; folder bez nowych plików po
  odczycie GeoPackage w każdym z trzech stanów);
  `tests/integration/test_cz_control_point.py::test_cz_features_within_2_m`
  (punkt GeoPackage EPSG:5514 w `features` ≤ 2 m).
- **Zależności:** 1, 2, 4, 7a (`consistent_sqlite_read`). **Równolegle:**
  5a1–5a3, 5c, 6, 7b, 8.
- **Stan po kroku 5b:**
  - *Rejestr.* `RENDERERS` dostał `VectorRenderer()` (jedna linia;
    `RENDERER_VERSIONS["vector"]` bez zmian — 1). `VectorRenderer(*,
    work_dir=None)` — katalog kopii SQLite; bez niego
    `worker.work_dir()` procesu.
  - *Otwarcie* (`renderers/vector.py`): wyłącznie przez `vector_source`
    (`GPKG:` — odstępstwo: najpierw nagłówek SQLite, inna treść pod
    `.gpkg` → `unsupported_format` przed GDAL; `GeoJSON:`; sygnatura
    `.shp`, `.fgb`, natywny `.tab`); komplet z członem będącym
    dowiązaniem symbolicznym → `unsupported_format` (jak czytnik 7a); brak
    pliku → `missing_file`. GeoPackage magazynu i migawki (`mutable`
    fałszywe) — w miejscu z `IMMUTABLE=YES`. Plik roboczy: `source.gpkg`
    z pamięci podglądów (`worker.cached_file`, krok 5a), jeśli jest — bez
    otwierania samego pliku; inaczej `consistent_sqlite_read` w katalogu
    roboczym procesu: (a) w miejscu, (b) i (c) z kopii; zmiana w trakcie
    odczytu → `changed_since_scan`.
  - *Rozpoznanie*: warstwy po indeksie (`read_info(layer=i,
    force_feature_count, force_total_bounds)`, ≤ `MAX_LAYERS` 1000);
    obiekt warstwy w `PreviewProbe.layers`: `name`, `geometry_type`,
    `feature_count`, `fields` (`name`, `type` jak w czytniku 7a), `crs`
    (pliku, inaczej `source.crs`), `bbox`, `bbox_wgs84`, `sample` (≤ 20
    wierszy; `null` dla NULL, wartości binarnych i nieskończonych, tekst
    ponad 500 znaków skrócony z „…”). Odstępstwo: warstwa nazwana po
    pliku (Shapefile, TAB, GeoJSON i FlatGeobuf bez własnej nazwy) ma
    `name: null` — `info.json` jest wspólny dla tych samych bajtów pod
    różnymi nazwami, więc nie niesie nazw plików (decyzja 3); żądanie bez
    `layer` bierze pierwszą warstwę z geometrią. Plik: `crs` (wspólny
    układ warstw z geometrią), `bbox_native`, `bbox_wgs84` (suma warstw),
    `styles` = `("features",)`, powód `no_crs` (żadna warstwa z geometrią
    nie ma układu — także plik bez geometrii) albo `transform_unavailable`
    (żaden układ bez przypiętej operacji do WGS84 — np. TAB z kroku 2:
    MapInfo zapisuje PL-1992 jako WKT bez kodu EPSG na WGS84); `minzoom`
    i `maxzoom` puste — wektor trafia na mapę przez `features` (krok 6 nie
    daje mu `tiles_url`). Nowe pole `PreviewProbe.needs_copy`: stan (b)
    albo (c) w chwili rozpoznania (rozpoznanie zawsze czyta plik, nie
    kopię); `build_product` → `SOURCE_GPKG_NAME` (stała przeniesiona do
    `types.py`, `cache.py` ją re-eksportuje), a `build` zapisuje kopię
    spójną (jeden plik bez dziennika, tylko zatwierdzone wiersze), którą
    zadanie `preview` kładzie jako `source.gpkg`; plik > 2 GB czeka na
    „Zbuduj podgląd” przez `auto_build`.
  - *Miniatura i kafel*: do `DRAWN_LAYERS` 3 największych warstw
    liniowych i powierzchniowych (punktowe tylko w pliku bez nich) albo
    wskazana `layer`, ≤ `DRAWN_FEATURES_MAX` 50 000 obiektów każda,
    uproszczone do pół piksela; bez kadru — w układzie największej z nich
    wokół zasięgu (także plik bez układu), z kadrem — obraz
    `tiles.frame_shape` w układzie kadru: prostokąt kadru (z marginesem
    `REACH_PX`) przeliczony do układu warstwy po zagęszczeniu, obiekty
    z powrotem przypiętą operacją. `tile` to samo na siatce kafla
    EPSG:3857 (`params["layer"]` opcjonalnie). RGBA przezroczyste poza
    obiektami (`compose.py`). Rysowanie w `previews/rasterize.py`
    (`Grid`, `Canvas`, `draw_png`): wypełnienie z alfa 0,35 i obrys,
    linie po każdym dotkniętym pikselu, punkty jako koła r = 3 px, część
    mniejsza od piksela jako piksel z numpy (`rasterize` GDAL-a przez
    `__geo_interface__` kosztuje ok. 2 s na 50 000 wielokątów), kolory
    `LAYER_COLORS`, PNG przez `tiles.encode_png`. Operacja `thumbnail`
    przekazuje `layer` tylko, gdy żądanie go ma, a `_thumbnail_target`
    wlicza go wtedy do skrótu kadru (nazwy bez `layer` bez zmian); trasa
    kroku 6 jeszcze go nie wystawia.
  - *Obiekty* (`features`): `limit` 1–5000 i `zoom` 0–22 (inaczej
    `ValueError`), widok przycięty do świata, jego prostokąt zagęszczony
    (`EDGE_POSITIONS` 64 punkty na krawędź) i przeliczony do układu
    warstwy → `bbox` OGR; `max_features = limit + 1`; tolerancja = pół
    piksela mapy zoomu w jednostkach warstwy (z obu osi widoku), geometria,
    która by znikła, upraszczana z `preserve_topology=True`; do WGS84
    przypiętą operacją, 7 miejsc po przecinku; ≤ `FEATURES_MAX_VERTICES`
    500 000 — pierwsze obiekty, które się mieszczą. Wynik:
    `FeatureCollection` z `id` (FID), `layer`, `number_matched` (`null`
    ponad `limit`), `number_returned`, `truncated`, `simplified`.
  - *Próby*: `tests/unit/test_vector_renderer.py` (17 testów, ok. 8 s:
    GeoPackage z dwiema warstwami, miniatura i kafel RGBA, Shapefile —
    warstwa bez nazwy, bez `.prj` → `no_crs`, GeoJSON i FlatGeobuf
    w pozycjach przypiętej operacji, 5041 punktów i `limit` 5000 →
    `truncated`, `test_features_simplified_to_zoom` — 12 wielokątów
    zębatych po 50 000 wierzchołków przy z = 12: 10 obiektów ≤ 500 000
    wierzchołków i `truncated`, gładki przy z = 12 i z = 19 ≤ 1 piksel
    mapy, widok w EPSG:2180 i EPSG:5514, OGR VRT pod `.gpkg`, `.geojson`,
    `.shp`, `.fgb` → `unsupported_format`/`unreadable` bez treści celu,
    `.dbf` jako dowiązanie, trzy stany GeoPackage — folder bez zmian,
    `build` → kopia z wierszami zatwierdzonymi);
    `tests/integration/test_vector_previews.py::test_open_gpkg_read_from_kept_copy`
    (prawdziwa pula: po zbudowaniu kopii plik w edytorze dostaje `chmod
    000`, a obiekty dalej przychodzą — z `source.gpkg`);
    `test_cz_control_point.py::test_cz_features_within_2_m` (prawdziwa
    pula z rendererami aplikacji: punkt 3722 z GeoPackage EPSG:5514 0,66 m
    od φ, λ ETRS89). Dym: `archiwista serve` z magazynem testowym —
    GeoPackage `ready` ze stylem `features`, `preview.png` 200,
    `features?bbox&zoom` 200.

### 5c. Chmury punktów, archiwa, dokumenty, pliki pomocnicze
- **Cel:** renderery `points.py` (LAZ/LAS: nagłówek, układ z VLR albo
  `source.crs`, gęstość, histogram klas ASPRS z próbki ≤ 2 mln punktów
  i ≤ 256 MiB rozpakowanych rekordów, rozłożonej po kawałkach — bez
  tablicy kawałków próbka z początku z dopiskiem `sampled_from: "start"`,
  obraz 2D maks. Z w siatce o boku ≥ 1 m jako COG przez zadanie
  `preview`, potem kafle jak raster; tablica klas ASPRS po polsku
  w module), `archive.py` (ZIP: najpierw rekord końca katalogu
  centralnego, także zip64 — > 100 000 wpisów albo katalog > 64 MiB →
  `too_large` bez `ZipFile`; potem katalog centralny bez rozpakowania,
  ≤ 10 000 członów z `truncated`, rozmiar, rozmiar spakowany, format
  z rozszerzenia; nazwy członów tylko wypisywane), `document.py` (PDF,
  TXT, pliki pomocnicze `.jgw .tfw .pgw .wld .prj .aux.xml` i nieznane —
  powody z decyzji 5).
- **Pliki:** `archiwista/previews/renderers/{points,archive,document}.py`.
- **Interfejs:** `Renderer` z `members` (archiwum) i `build` (LAZ).
- **Test/odbiór:** `tests/unit/test_points_renderer.py` (LAZ z kroku 2:
  klasy 2, 3, 6 z liczbami, obraz 2D, LAS nieskompresowany pod nazwą
  `.laz` z v0.1, plik bez tablicy kawałków, rekord z dużymi bajtami
  dodatkowymi — próbka ograniczona bajtami), `tests/unit/test_archive_renderer.py`
  (10 001 członów → `truncated`, człon `../x` tylko wypisany, nic nie
  rozpakowane, katalog centralny deklarujący 200 000 wpisów → `too_large`
  przed `ZipFile`), `tests/unit/test_document_renderer.py` (PDF, TXT, JGW,
  nieznany → właściwy kod i polski opis).
- **Zależności:** 1, 2, 4. **Równolegle:** 5a1–5a3, 5b, 6, 7b, 8.
- **Stan po kroku 5c:**
  - *Rejestr.* `RENDERERS` dostał `PointsRenderer()`, `ArchiveRenderer()`
    i `DocumentRenderer()` (po linii; `RENDERER_VERSIONS` bez zmian — 1).
  - *Chmury punktów* (`renderers/points.py`). Bez czytnika laspy: nagłówek
    i VLR przez `laspy.LasHeader.read_from`, tablica kawałków przez
    `lazrs.read_chunk_table`, a każdy kawałek próbki rozpakowuje osobno
    `lazrs.decompress_points_with_chunk_table` (warstwy XY, Z, klasy).
    Powód: `LasReader` z lazrs czyta tablicę kawałków już przy otwarciu
    i plik bez niej (przesunięcie −1, zapis strumieniowy) odrzuca błędem
    `failed to fill whole buffer` — sprawdzone 2026-10-19 na LAZ z kroku 2.
    Próba: `SAMPLE_MAX_POINTS` 2 mln, `SAMPLE_MAX_BYTES` 256 MiB rekordów
    (z bajtami dodatkowymi), LAS nieskompresowany w `SAMPLE_WINDOWS` = 64
    oknach wzdłuż pliku, LAZ — początki wybranych kawałków równo po tablicy,
    bez tablicy — pierwszy kawałek. `PreviewProbe.points`: `version`,
    `point_format`, `point_count`, `compressed`, `record_bytes`,
    `chunk_table`, `min`, `max`, `scales`, `density_per_m2` (tylko układ
    płaski), `creation_date`, `generating_software`, `classes` (`value`,
    `label` po polsku z `ASPRS_CLASSES` — LAS 1.4 R15, 23–63 „Klasa
    zarezerwowana”, 64–255 „Klasa użytkownika”, `count` z próby),
    `sample_points`, `sampled_from` (`all` — cała chmura, `spread` — próba
    rozłożona, `start` — bez tablicy kawałków). Pola rastra opisują obraz 2D:
    `width`/`height` siatki (komórka ≥ 1 m, w układzie geograficznym
    1/111 320°; najdłuższy bok ≤ 8192 px), `bands` 1, `float32`, `nodata`
    −9999, `stats` (p2, p98, min, max Z próby), `pixels`; `crs` — poziomy
    z VLR (część pozioma układu złożonego; `EPSG:<kod>` albo WKT), inaczej
    `source.crs`; `bbox_wgs84`, `minzoom`, `maxzoom` z
    `tiles.map_placement`; `styles` = `("elevation",)`, `unit` `m`.
    `needs_cog` tylko z układem i przypiętą operacją; bez układu `no_crs`,
    bez operacji `transform_unavailable`. Miniatura bez budowy: siatka
    maks. Z próby jako GeoTIFF w pamięci → `raster.render_thumbnail`.
    `build`: wszystkie punkty (kawałek po kawałku, LAS po 1 mln) →
    `cog.write_cog(..., classes=False, nodata=-9999)`; LAZ bez tablicy
    kawałków daje obraz pierwszego kawałka (ma `sampled_from: "start"`).
    Kafel: `raster.open_cog` + `raster.render_tile`; przed budową
    `unsupported_format` („2D image … not built”) — krok 6 sprawdza
    `cache.has(COG)` wcześniej (`preview_not_ready`).
  - *Archiwa* (`renderers/archive.py`). `zipfile` nieużywany:
    `read_central_directory(stream) -> CentralDirectory(entries,
    size_bytes, offset)` z ostatnich 64 KiB + 22 B (rekord ZIP64 przez
    lokalizator; przesunięcie danych doklejonych przed archiwum liczone),
    `MAX_ENTRIES` 100 000, `MAX_DIRECTORY_BYTES` 64 MiB, `MAX_LISTED`
    10 000. Rozpoznanie: `driver` `ZIP`, `members` (zadeklarowane wpisy),
    powód `archive_members_only` albo `too_large`; `members(source)` →
    `{"total", "truncated", "members": [{"name", "size_bytes",
    "compressed_bytes", "directory", "format", "kind"}]}` (rozmiary z
    pola ZIP64, nazwa UTF-8 z flagą 11, inaczej cp437; format z tabeli
    formatów po rozszerzeniu) albo `PreviewUnavailableError("too_large")`.
    Plik bez rekordu końca → `ValueError` → `unreadable`.
  - *Dokumenty i pliki pomocnicze* (`renderers/document.py`): rodzaje
    `document`, `auxiliary`, `unknown`; czyta tylko pierwszy 1 KiB
    (sygnatura `%PDF-` — inaczej `driver` `None`). Powody
    (`document_reason`): `auxiliary` oraz `.prj` i `.aux.xml`
    (`AUXILIARY_SUFFIXES`; w tabeli formatów to `unknown`) →
    `auxiliary_file`, `document` → `document_no_preview`, reszta →
    `unsupported_format`. Miniatura i kafel zawsze
    `PreviewUnavailableError` z powodem rozpoznania.
  - *Próby*: `tests/unit/test_points_renderer.py` (7),
    `test_archive_renderer.py` (9, `zipfile.ZipFile` podmieniony na
    pułapkę), `test_document_renderer.py` (9); razem ok. 2 s. Przez
    prawdziwą pulę (`RenderPool`, proces z sandboxem): rozpoznanie LAZ
    z `bbox_wgs84` i zoomami 15–19, miniatura, kafel z = 17 z COG po
    `build` i `put`, ZIP z 200 000 wpisów → `too_large`, PDF →
    `document_no_preview`.

### 6. Podglądy magazynu przez HTTP i CLI; odwołania `ref`
- **Cel:** trasy podglądów wersji magazynu z umowy API (opis, budowa,
  miniatura, kafle, obiekty z `zoom`, człony), `refs.py` i `ObjectResolver`
  dla wersji (ścieżka z `resolve_indexed_path`, `sha256` albo — gdy go
  brak — klucz ścieżki z decyzji 3, `horizontal_crs`, produkt i klucz
  zbioru z indeksu, a dla obrysu o źródle `header` — natywny prostokąt
  i układ jako `georeference`), `PreviewService`, pole `ref` w modelach
  wersji, `previews` w `/health`, nagłówki `Cache-Control`/`ETag`/`304`
  (decyzja 3), walidacja `z`, `x`, `y` i `404` poza zakresem zoomu
  i zasięgiem pliku (decyzja 13), nowe kody problemów, polecenie
  `archiwista preview` (`--build` przez `jobs/foreground.py`, który
  przejmuje kod `jobs/reindex.py`) i krotka `COMMAND_MODULES` w `cli.py`
  (umowa „CLI”).
- **Pliki:** `archiwista/refs.py`, `archiwista/previews/service.py`,
  `archiwista/api/previews.py`, `archiwista/api/models_previews.py`,
  `archiwista/api/models.py` (`ref` w `Version` i `VersionCard`,
  `Health.previews`), `archiwista/api/errors.py`, `archiwista/api/health.py`,
  `archiwista/app.py` (jedna linia `include_router`),
  `archiwista/jobs/foreground.py`, `archiwista/jobs/reindex.py`,
  `archiwista/commands/{__init__,previews}.py`, `archiwista/cli.py`,
  `archiwista/texts/previews.py`.
- **Interfejs:** umowa API (wiersze kroku 6), `PreviewInfo`, CLI
  z decyzji 11.
- **Test/odbiór:** `tests/integration/test_previews_api.py` (każda trasa,
  walidacja parametrów → `422`, `z` powyżej `maxzoom` pliku → `404`,
  `409 preview_not_ready` przed budową, `POST` → `202` → `ready`, `304` po
  `ETag`, `preview_unavailable` z powodem, odłączony magazyn → z pamięci
  albo `503 store_unavailable`, bez CSRF → `403`),
  `tests/integration/test_preview_coverage.py::test_every_store_file_type_has_preview_or_reason`
  (kryterium 1; także wersja bez `sha256` — podgląd pod kluczem ścieżki),
  `tests/integration/test_preview_cache.py::test_same_content_rendered_once`
  (kryterium 3: dwie wersje o tym samym `sha256`, powtórzenia i restart —
  licznik żądań procesów renderujących bez zmian),
  `tests/integration/test_preview_security.py`
  (`test_server_process_never_opens_data_files` — w procesie serwera
  `rasterio.open`, `pyogrio`, `laspy.open` i `zipfile.ZipFile` zgłaszają
  błąd, a trasy działają; ścieżka spoza korzenia → `403
  path_outside_root`; `test_store_and_own_folder_unchanged_after_previews`
  — magazyn testowy z prawem zapisu: po rozpoznaniu, miniaturze, kaflu
  i obiektach każdej rodziny nazwy, rozmiary i czasy plików bez zmian,
  żadnego `.aux.xml`; folder danych własnych dochodzi w kroku 9),
  `tests/integration/test_cli.py::test_preview_cli_equals_http`
  i `::test_preview_output_writes_png`,
  `tests/integration/test_jobs.py::test_reindex_on_foreground_helper`
  (bez regresji `reindex`).
- **Zależności:** 3, 4; odbiór po 5a1–5c. **Równolegle:** 5a1–5c, 7b, 8.
- **Stan po kroku 6 (commity `a8693c5`, `9de22fe` i następny):**
  - *Odwołania* (`refs.py`): `VersionRef`, `FileRef`, `SnapshotRef`,
    `parse_ref`/`format_ref` (wzajemnie odwrotne; zły tekst →
    `InvalidRefError`, `422 invalid_ref`), `version_ref(store, path)`.
    `ObjectResolver(queries, settings)`: `resolve(ref, *, principal)` —
    plik w korzeniu przez `resolve_indexed_path` (dowiązanie poza korzeń →
    `403 path_outside_root`, korzeń nieosiągalny → `503 store_unavailable`,
    brak pliku → powód `missing_file`); `locate(ref, *, principal)` —
    z samego indeksu dla wersji z `sha256` (pamięć podglądów odpowiada przy
    odłączonym magazynie), bez `sha256` jak `resolve` z kluczem
    `path_key(store, path, st_size, st_mtime_ns)`. `georeference` = prostokąt
    obrysu natywnego (`IndexQueries.native_outline`) i `native_crs` dla
    obrysu o źródle `header`. `file:`/`snapshot:` → `invalid_ref` do kroku 9.
    `job_resolver(spec)` w `build.RESOLVERS["version"]`.
  - *Usługa* (`previews/service.py`): `PreviewService(pool, resolver,
    jobs=None)`, metody asynchroniczne `info`, `thumbnail`, `tile`,
    `features`, `members`, `plan_build`, `build` — każda: indeks, pamięć
    podglądów, dopiero potem dysk i proces renderujący. Obraz i dane jako
    `Payload(data, etag)`; `ETag` z klucza obiektu i nazwy (ta sama treść =
    ten sam znacznik), `If-None-Match` → `304` przed odczytem. Styl spoza
    `probe.styles` → `422`; kafel poza `minzoom`–`maxzoom` albo zasięgiem →
    `404`; kafle przed budową COG albo kopii → `409 preview_not_ready`
    (`job` albo `build_required`); ponad progi bez `force` → `409 too_large`.
    Stany `ready`, `needs_build`, `building` (zadanie z `jobs.list`),
    `unavailable`, `failed`.
  - *Trasy* (`api/previews.py`, router przed `slots` w `app.py`): `GET`
    i `POST …/preview`, `preview.png`, `tiles/{z}/{x}/{y}.png`, `features`,
    `members`; `Cache-Control: private, max-age=86400, immutable` i `ETag`;
    rozłączony klient porzuca żądanie renderowania (odpowiedź `499`).
    `POST` → `202 JobDetail` z `Location` albo `200 PreviewInfo`. Modele
    w `api/models_previews.py`; `ref` w `Version` i `VersionCard`,
    `Health.previews` (`null` w `archiwista status`); kody problemów jak
    w umowie, `preview_unavailable` z `reason` (`code`, `message`, `fix`,
    `detail`), `preview_busy` z `Retry-After`.
  - *CLI* (`archiwista/commands/`): moduł = `COMMANDS`,
    `add_commands(commands)`, `main(args, paths, registry, out, err)`;
    wspólne `add_parser` (z `--json`) i `refuse` (problem na stdout, kod 1)
    w `commands/__init__.py`; krotka `COMMAND_MODULES` w `cli.py`.
    `archiwista preview REF [--style STYL] [--size BOK] [--output PLIK.png]
    [--build] [--json]` (`--size` domyślnie 512, walidacja modelem
    `ThumbnailQuery` jak trasa): `local_previews(paths, settings, *,
    jobs=None)` otwiera indeks, pamięć podglądów serwera i `RenderPool`
    z jednym procesem; `--build` — `PreviewService.build(force=True)` na
    pierwszym planie, potem `--output`, na końcu `PreviewInfo`; nieudana
    budowa → komunikat i kod 1 (opis wypisany). Bez `--build` CLI nie
    uruchamia `JobSupervisor`.
  - *Zadania na pierwszym planie* (`jobs/foreground.py`):
    `run_foreground(jobs, submit, err, *, started, event, cancelling,
    poll_s=0.5)` — zlecenie, zdarzenia na stderr, Ctrl+C → `cancel`
    i czekanie na koniec. Zlecenie dołączone do zadania innego procesu
    (`JobSupervisor.supervises(job_id)` fałszywe): komunikat
    `job_foreground_waiting`, śledzenie jego zdarzeń z indeksu (`get`,
    `events`, co `poll_s` `recover` — zadanie zmarłego procesu kończy się
    `interrupted`), po jego końcu ponowne `submit`; Ctrl+C przerywa wtedy
    tylko czekanie. Konflikt (`JobConflictError`) idzie do polecenia:
    `reindex` na `run_foreground` nadal kończy się kodem 1 („kod
    conflict”).
  - *Odstępstwa od umowy.* `PreviewService(pool, resolver, jobs)` zamiast
    `(pool, cache, jobs, settings, resolver)` — pamięć to `pool.cache`,
    ustawienia czyta `ObjectResolver`; metody przyjmują `ref` i `principal`,
    nie źródła: pamięć podglądów odpowiada przed sięgnięciem do dysku,
    a źródło rozwiązuje usługa (`locate`, potem `resolve`). Dodane
    `ObjectResolver.locate`, `PreviewService.plan_build` i błąd
    `PreviewParameterError` (`422 validation_error` z `errors`). Bez
    `JobSupervisor` (CLI bez `--build`) pole `job` jest `null`, a plik,
    który buduje serwer, ma stan `needs_build`.
  - *Próby* (prawdziwe procesy renderujące i robotnik zadań;
    `tests/fixtures/preview_api.py`: `preview_api`, `scanned_store`,
    `serve_previews`): `tests/integration/test_previews_api.py` (18, ok.
    11 s), `test_preview_coverage.py` (1, ok. 35 s: 46 wersji magazynu
    z rodzinami kroku 2, każda `ready`, `needs_build` albo `unavailable`
    ze znanym powodem; każda z 22 `needs_build` po `POST` (22 zadania
    `preview` po kolei) `ready` z kaflem; dwie wersje bez `sha256` pod
    kluczem ścieżki), `test_preview_cache.py::test_same_content_rendered_once`
    (3 żądania renderowania: rozpoznanie, miniatura, kafel; druga wersja
    tych samych bajtów, powtórzenia i nowy serwer — 0),
    `test_preview_security.py` (3, ok. 14 s; folder danych własnych
    dochodzi w kroku 9), `test_cli.py::test_preview_cli_equals_http`
    i `::test_preview_output_writes_png` (ok. 10 s),
    `test_jobs.py::test_reindex_on_foreground_helper` (Ctrl+C w `wait`
    anuluje skan, przebieg porzucony) i
    `::test_foreground_follows_joined_job_then_runs_own`.

### 7a. Czytnik danych własnych i tożsamość treści
- **Cel:** proces czytnika (decyzja 8; sandbox i tabela formatów z kroku
  1), rozpoznanie formatów i kompletów plików (MapInfo TAB tylko jako
  tabela natywna), tożsamość treści `bytes`/`fileset`/`sqlite` (tabele
  wirtualne i cienie z `sqlite_master`, bez `gpkg_ogr_contents`
  i znaczników czasu zapisu) i spójny odczyt SQLite według trzech stanów
  (`consistent_sqlite_read`; kopie w katalogu roboczym procesu).
- **Pliki:** `archiwista/owndata/{__init__,reader,formats,content}.py`.
- **Interfejs:** umowa „Dane własne” (czytnik i treść).
- **Test/odbiór:** `tests/unit/test_own_content.py`
  (`test_sqlite_hash_ignores_vacuum_and_checkpoint`,
  `test_sqlite_hash_includes_committed_wal_frames`,
  `test_sqlite_hash_excludes_uncommitted_transaction`,
  `test_sqlite_hash_changes_with_row_or_schema`,
  `test_sqlite_hash_ignores_rtree_shadow_tables`,
  `test_sqlite_hash_ignores_ogr_contents_cache` — otwarcie do zapisu bez
  zmian danych (przepisany `gpkg_ogr_contents` i `last_change`) nie
  zmienia skrótu, `test_shadow_tables_from_sqlite_master_match_table_list`
  (wyrocznia: `PRAGMA table_list` na SQLite ≥ 3.37),
  `test_fileset_independent_of_listing_order`),
  `tests/integration/test_own_reader.py` (wszystkie rodziny
  z `make_own_folder`, Shapefile jako komplet, brak układu, raster
  z samym plikiem świata → bez georeferencji, widok i tabela łączona
  MapInfo → `unsupported_format`, treść VRT pod nazwą `.tif`, `.gpkg`,
  `.shp` → bez odczytu pliku docelowego, plik wiszący zabity po 30 s
  i kolejne pliki czytane dalej,
  `test_data_folder_unchanged_after_reads` — nazwy, rozmiary, czasy,
  żadnych nowych plików w każdym z trzech stanów SQLite,
  `test_wal_without_shm_read_from_local_copy` — wiersze tylko z `-wal`
  w wyniku).
- **Zależności:** 1 (sandbox, tabela formatów, próba SQLite).
  **Równolegle:** 2, 3, 4.
- **Stan po kroku 7a:**
  - *Treść* (`owndata/content.py`): `ContentIdentity(method, sha256)`,
    `ContentMethod` (`bytes`, `fileset`, `sqlite`), `content_method(path)`
    (komplet → `fileset`, nagłówek SQLite → `sqlite`, inny plik → `bytes`),
    `content_identity(paths, *, method, work_dir=None)` — odstępstwo:
    `work_dir` (katalog roboczy procesu, `process_work_dir`) wymagany dla
    `sqlite`; `file_sha256(path)`; `sqlite_content_sha256(connection)`:
    wersja schematu skrótu `archiwista-sqlite-content/1`,
    `application_id`, `user_version`, posortowane wpisy `sqlite_master`
    (JSON), potem skrót wierszy każdej tabeli. Wiersz to `repr` krotki
    wartości w kolejności `PRAGMA table_info` (bez kolumn generowanych),
    tekst i blob jako `T`/`X` i bajty szesnastkowo — typ wartości się
    liczy, a liczby rzeczywiste formatuje Python (dokładnie i tak samo
    w każdej wersji), nie `quote()` SQLite, którego zapis zależy od wersji
    i platformy. Porządek: klucz główny, potem każda kolumna `COLLATE
    BINARY` z `typeof` — tabela z `INTEGER PRIMARY KEY` czytana po kluczu
    bez sortowania, tabela bez klucza jako posortowany multizbiór.
    `table_kinds(connection)` (`table`/`virtual`/`shadow` z
    `sqlite_master`); `SHADOW_SUFFIXES` przeniesione z
    `tests/contract/test_preview_stack.py` (test je importuje), dodany
    `rtree_i32` (ten sam moduł i te same cienie co `rtree`);
    `DERIVED_TABLES`, `DERIVED_COLUMNS`.
  - *Spójny odczyt SQLite:* `consistent_sqlite_read(path, *, work_dir,
    attempts=3) -> ContextManager[SqliteRead]`; `SqliteRead(path, state:
    "in_place" | "backup" | "copy", source: FileStamp, wal, journal)` —
    stany (a), (b), (c); `sqlite_uri` (`mode=ro&immutable=1`),
    `gdal_options` (`{"IMMUTABLE": "YES"}`), `connect()`
    (`trusted_schema=OFF`, `query_only`); `FileStamp(size_bytes,
    modified_ns)` pliku i `-wal` sprzed odczytu. `read_sqlite(path, read,
    *, work_dir, attempts=3)` — to samo z ponowieniem całego odczytu po
    `InconsistentReadError`. Odstępstwa: (1) kopia stanów (b) i (c)
    staje się w katalogu roboczym jednym plikiem bez dziennika
    (odzyskanie WAL, punkt kontrolny, `journal_mode=DELETE`), więc każdy
    stan otwiera się tak samo (`immutable=1`, `IMMUTABLE=YES`); (2)
    niepusty `-journal` (gorący dziennik po awarii piszącego w trybie
    `DELETE`) to też stan (c): kopia z dziennikiem i wycofanie w kopii —
    odczyt w miejscu liczyłby strony niezatwierdzonej transakcji, które
    już są w pliku (`test_sqlite_hash_rolls_back_a_hot_journal_in_a_copy`
    pada bez tego); (3) stan (a) porównuje przed i po także licznik zmian
    z nagłówka (bajty 24–27) i obecność `-wal`, `-journal`, `-shm`: czas
    modyfikacji ma rozdzielczość zegara jądra (ok. 4 ms), więc sam rozmiar
    i czas nie widziały zapisu tuż po poprzednim.
  - *Rozpoznanie* (`owndata/formats.py`): `FILESET_SUFFIXES` (`.shp .shx
    .dbf .prj .cpg .qix .sbn .sbx`; `.tab .dat .map .id .ind`),
    `is_fileset(path)` (`.shp` albo `.tab` natywny według
    `vector_source`), `fileset_members(path) -> tuple[Path, ...]` (plik
    główny, potem człony w tej kolejności; rozszerzenie bez względu na
    wielkość liter, zwykłe pliki — dowiązanie liczy się celem),
    `is_sqlite(path)`, `SQLITE_MAGIC`, `SQLITE_COMPANION_SUFFIXES`
    (`-wal`, `-shm`, `-journal` — nie są osobnymi plikami).
  - *Czytnik* (`owndata/reader.py`; importowany wprost, pakiet go nie
    eksportuje, bo działa jako `-m`): `python -P -m
    archiwista.owndata.reader --config-file F --data-dir D` importuje GDAL,
    pisze `{"ready": true}`, potem na każdą linię `{"path": "…"}` odpowiada
    linią z `OwnFileInfo`. `OwnReader(paths, *, timeout_s=30,
    memory_bytes=2 GiB, command=OWN_READER_COMMAND, start_timeout_s=60)`:
    `read(path) -> OwnFileInfo`, `close()`, menedżer kontekstu, jeden
    wątek naraz; proces startuje przy pierwszym pliku (zegar pliku rusza
    po imporcie GDAL), po przekroczeniu czasu jest zabijany (`timeout`),
    jego śmierć daje `unreadable`, następny plik czyta nowy proces; proces,
    który się nie zgłosi → `OwnReaderError`. `OwnFileInfo(kind, driver,
    members, layers, raster, native_crs, native_bbox, feature_count, error,
    detail)` — odstępstwo: `detail` (komunikat biblioteki po angielsku bez
    katalogu pliku i katalogu roboczego, do 300 znaków); `LayerInfo(name,
    geometry_type, feature_count, fields: tuple[FieldInfo(name, type)],
    crs, bbox)`, `RasterInfo(width, height, bands, dtype, nodata,
    pixel_size, georeferenced)`. `error`: `unsupported_format` (tabela
    formatów; także człon kompletu będący dowiązaniem symbolicznym — GDAL
    otwiera człony po nazwie), `unreadable`, `timeout`, `memory_limit`;
    `driver is None` — plik spoza GDAL (dla skanu „nierozpoznany”).
    `native_crs`: `EPSG:<kod>` albo WKT; wektor — jeden układ wszystkich
    warstw z geometrią (różne → `None`), `native_bbox` — suma ich zasięgów
    (x na wschód). Warstwy pytane po indeksie (`pyogrio.read_info(layer=i,
    IMMUTABLE="YES")`, najwyżej `MAX_LAYERS` = 1000), bo `list_layers` nie
    przyjmuje opcji otwarcia. Czytnik nie liczy tożsamości treści — robi
    to wołający, bez limitu 30 s (skrót logiczny dużej bazy trwa dłużej).
  - *Błędy* (`errors.py`): `InconsistentReadError` (plik zmienił się
    w czasie odczytu albo kopii), `OwnReaderError`.
  - *Dla 7b.* Skan woła `OwnReader.read(<ścieżka po realpath>)` dla pliku
    głównego i `content_identity(fileset_members(p) if metoda ==
    "fileset" else [p], method=content_method(p),
    work_dir=process_work_dir(paths))` we własnym procesie; człony
    kompletu sprawdza jak pliki (dowiązanie poza folder); w liście plików
    pomija człony kompletów i pliki `SQLITE_COMPANION_SUFFIXES`;
    `InconsistentReadError` → nieczytelny do następnego skanu.
  - *Dla 8 i 5b.* `with consistent_sqlite_read(p, work_dir=…) as view:` —
    `view.state != "in_place"` → ostrzeżenie `editing_detected`; kopia
    z `view.path` przez `Connection.backup` z `view.sqlite_uri`,
    tożsamość kopii `sqlite_content_sha256`; w stanie (a) koniec bloku
    zgłasza `InconsistentReadError`, gdy plik się zmienił (dla 8:
    `inconsistent_copy`).
  - *Pomiary* (2026-10-19, komputer odniesienia, SSD): GeoPackage
    148,6 MB (500 000 wielokątów, 3 pola): skrót logiczny 2,85 s (ok.
    52 MB/s), `bytes` 0,38 s; czytnik: start z importem GDAL i pierwszy
    odczyt 0,39 s, kolejny odczyt tego pliku 6 ms.

### 7b. Folder danych, indeks i skan danych własnych
- **Cel:** ustawienie `own_data_dirs` z walidacją i funkcją usługi do
  zmiany folderu (trasę daje krok 9), te same reguły dla folderu
  domyślnego (stan `invalid`, problem `own_folder_invalid` — decyzja 8),
  tabele indeksu danych własnych (`SCHEMA_VERSION` + 1), zapis i odczyt
  z wymaganym `visible`, skan `scan_own_data` (decyzja 8: przejście
  folderu — z większego niż 10 000 plików pierwsze 10 000 w porządku
  ścieżki, odczyt nowych i zmienionych plików czytnikiem 7a, wielokąty
  zasięgu `outline_wgs84`, migawki z `.wersje/**/migawka.json`
  z walidacją `SnapshotDocument` (odczyt z `extra="ignore"`), także
  opublikowane bez wpisu w indeksie, stan zmiany, historia stanów,
  problemy), zadanie `own_scan` — globalne z harmonogramu albo dla
  jednego projektu — z łączeniem czekających i przycinaniem rutynowych
  przebiegów.
- **Pliki:** `archiwista/config.py`, `archiwista/owndata/scan.py`,
  `archiwista/owndata/document.py` (model — wspólny z krokiem 8),
  `archiwista/index/{schema,writer,queries,types}.py`,
  `archiwista/services/owndata.py`, `archiwista/api/models_owndata.py`,
  `archiwista/jobs/{worker,supervisor,scheduler}.py`,
  `archiwista/texts/owndata.py`, `archiwista/messages.py` (jedna linia).
- **Interfejs:** umowa „Dane własne” (indeks, ustawienia, zadanie,
  modele `OwnFolder`, `OwnFileItem`, `OwnFileCard`, `SnapshotItem`).
- **Test/odbiór:** `tests/integration/test_own_scan.py`
  (`test_folder_with_gpkg_shp_geotiff_indexed_with_extent` — zasięg
  natywny i WGS84, warstwy, liczba obiektów, schemat;
  `test_change_after_snapshot_detected` — z `write_snapshot_fixture`:
  zmiana obiektu GeoPackage, dopisanie do Shapefile, nadpisanie GeoTIFF →
  `changed` z datą migawki, powrót treści → `unchanged`, otwarcie
  GeoPackage do zapisu bez zmian danych → `unchanged`, historia stanów;
  `test_unchanged_files_cost_only_stat`; `test_hidden_and_versions_skipped`;
  `test_symlink_outside_folder_skipped`; `test_invalid_snapshot_problem`;
  `test_snapshot_with_unknown_optional_field_is_valid`;
  `test_stale_incoming_problem_after_24h`; `test_missing_file_keeps_snapshots`;
  `test_default_folder_inside_store_is_refused` — projekt z manifestem
  w katalogu producenta: folder `invalid`, nic nie przeczytane, magazyn
  bez zmian; `test_overlapping_folders_invalid_for_both`;
  `test_too_large_folder_indexes_first_10000_by_path`),
  `tests/unit/test_config.py::test_own_data_dir_validation` (w magazynie,
  zagnieżdżony z folderem innego projektu, nieistniejący → odrzucone),
  `tests/unit/test_scheduler.py::test_own_scan_planned_and_pruned`,
  `tests/integration/test_jobs.py::test_own_scan_request_joins_waiting_run`
  (przy trwającym przebiegu zlecenie projektu dołącza do czekającego
  przebiegu globalnego albo do czekającego przebiegu tego projektu,
  zmiana sprzed zlecenia w wyniku),
  `tests/integration/test_state.py` bez zmian (baza stanu nietknięta).
- **Zależności:** 2, 3, 7a. **Równolegle:** 4, 5a1–5c, 6.
- **Stan po kroku 7b:**
  - *Ustawienia* (`config.py`): `AppSettings.own_data_dirs: dict[str, str]`
    (klucz: katalog projektu po `realpath` = `access_key`; wartość: folder;
    obie ścieżki bezwzględne), `own_data_dir(project) -> (Path, source)`
    (`setting` albo `<projekt>/dane` — `default`), `OWN_DATA_DIR_NAME`,
    typy `OwnFolderSource`, `OwnFolderReason`; reguła
    `own_folder_conflict(folder, *, stores, app_data, others) -> (powód,
    katalog) | None` (po `realpath`: w katalogu producenta →
    `inside_store`; nakładanie z `AppPaths.data_dir` w obie strony →
    `inside_app_data`; z folderem innego projektu w obie strony →
    `overlaps_project`); `validate_settings` → `check_own_data_dirs`
    (nowy albo zmieniony folder: istnieje i czytelny — `own_data_dir_missing`,
    `_not_directory`, `_unreadable`; każdy: magazyny i pozostałe wpisy,
    problem `own_data_dir_<powód>`, pole `own_data_dirs.<klucz>`).
    Odstępstwo: `validate_settings` nie zna katalogu danych ani folderów
    domyślnych projektów z indeksu — sprawdza je usługa i każdy skan. Model
    API `Settings` dostał `own_data_dirs` (inaczej `PUT /settings`
    z interfejsu kasowałby wpisy); `doctor` ma dla nich wskazówki naprawy.
  - *Indeks* (`SCHEMA_VERSION` 6): `own_folders` (`project` = klucz dostępu,
    `path`, `source`, `state`, `reason`, `scanned_at`, `files`, `size_bytes`,
    `snapshots`, `snapshots_bytes`), `own_files` (`path` w NFC, `file_id` =
    `own_file_id(path)` — 16 znaków SHA-256 ścieżki w NFC, `disk_path`,
    `stamp` — JSON rozmiarów i czasów członów oraz `-wal`/`-journal`,
    `read_state` `ok`/`unrecognized`/`unreadable`, `read_error`
    (`unsupported_format`, `unreadable`, `timeout`, `memory_limit`,
    `inconsistent`, `path_outside_root`), `retry`, treść, warstwy i raster
    w JSON, układ, prostokąt, `wgs84`, `location_reason`, `change`,
    `last_snapshot`, `first_seen_at`, `changed_at`, `missing_since`),
    `own_file_states` (≤ 200 na plik), `snapshots` (`path`, `file_id`,
    `label`, `state`, `created_at` w UTC, treść, `size_bytes`, `stamp`,
    pełny `document`), `own_problems` (kod, ścieżka w folderze — `''` dla
    folderu, `reason`, `first_seen_at`). `IndexWriter`: `write_own_folder`
    (inna ścieżka albo `invalid` → pliki, migawki i problemy folderu
    usunięte), `known_own_files`, `write_own_files`, `mark_own_missing`
    (`present`, `drop` — poza limitem 10 000), `known_own_snapshots`,
    `record_snapshot(project, SnapshotWrite)` (dla kroku 8; stan zmiany
    liczony od razu), `write_own_snapshots`, `finish_own_folder` (problemy
    i sumy), `remove_own_folders`; `project` to zawsze klucz dostępu.
    `IndexQueries` (wymagany `visible`, `project` = klucz projektu):
    `own_folder` → `OwnFolderRecord | None`, `own_files(…, q, state, limit,
    cursor)` → `OwnFilePage(folder, items, next_cursor) | None` (`state`:
    stan pliku albo zmiany; `q`: słowa w ścieżce), `own_file(project,
    file_id)` → `OwnFileDetail` (historia, migawki od najnowszej, problemy
    pliku i jego migawek) `| None`. Zmiana: `unsnapshotted` bez ważnej
    migawki, `unchanged` przy tej samej metodzie i skrócie co najnowsza
    migawka `ok`, inaczej `changed`.
  - *Dokument migawki* (`owndata/document.py`): `SnapshotDocument` (pola
    decyzji 9; `schema` i `copy` jako aliasy pól `format` i `copied`,
    zapis `model_dump(by_alias=True)`, odczyt `extra="ignore"`),
    `parse_snapshot_document(bytes) -> (surowy dict, model)`,
    `UnknownSnapshotSchemaError`, `InvalidSnapshotError`, stałe
    `SNAPSHOTS_DIR`, `INCOMING_DIR`, `SNAPSHOT_FILE`, `SNAPSHOT_SCHEMA`,
    `LABEL_PATTERN`, `MAX_NOTE_CHARS`.
  - *Skan* (`owndata/scan.py`): `scan_own_data(writer, projects, *,
    known_projects, settings, paths, transformer, prune, now, on_progress,
    reader) -> OwnScanSummary` (`result()` — wynik zadania);
    `check_own_folder(settings, project, *, stores, app_data, others) ->
    OwnFolderCheck(path, source, state, reason)` i `folder_rules(settings,
    known_projects)` — te same reguły dla skanu, usługi i kroku 8 (magazyny
    to też bezwzględne `store_dir` projektów); `snapshot_stamp(katalog) ->
    (stamp, bajty)` — krok 8 zapisuje go w `SnapshotWrite`, więc skan nie
    liczy sum migawki ponownie. Plik bez sterownika w tabeli formatów nie
    idzie do czytnika (odpowiedź byłaby ta sama). Pomiar: 2000 plików —
    pierwszy skan 1,8 s, bez zmian 0,055 s.
  - *Zadanie `own_scan`*: reguła `JobRule(store=False, exclusive=True,
    join=JobJoin(_join_own_scan, ("queued",)))` — dołączenie tylko do
    czekającego przebiegu wszystkich projektów albo tego samego projektu;
    parametry `{}` albo `{"project": klucz}`; błąd `own_reader_failed`,
    nieznany projekt → `not_found`; postęp `current`/`total` (foldery),
    `files`, `read`; `JobSupervisor.own_scan_history()`; przycinanie
    rutynowych przebiegów (harmonogram, wszystkie projekty, zero `new`,
    `changed`, `missing`, `snapshots`, `problems`) liczone w `prune()`.
    Harmonogram: `plan_own_scan(settings, history, *, now, started_at)`,
    `tick()` zwraca też zlecony `own_scan`.
  - *Usługa i modele* (dla 9): `services/owndata.py::set_data_dir(authorizer,
    principal, settings, queries, paths, project, path | None) ->
    OwnFolderCheck` (`settings.write`, projekt widoczny, reguły,
    `SettingsValidationError`), `own_problems(record)` (teksty polskie,
    powody `own_folder_reason_*`, `own_read_error_*`);
    `api/models_owndata.py`: `OwnFolder.of`, `OwnFileItem.of`,
    `OwnFileList.of`, `OwnFileCard.of` (bez `preview` — dodaje krok 9),
    `SnapshotItem.of`, `file_ref`, `snapshot_ref`, `copy_path`.

### 8. Migawki
- **Cel:** `check_snapshot` i `make_snapshot` (decyzja 9: folder ważny,
  kopia SQLite według trzech stanów, pliki `0444` przed publikacją,
  katalog `0555` po niej, `chmod` i `fsync` katalogu odrzucone przez
  system plików jako ostrzeżenia), dokument `archiwista-snapshot/1`,
  zadanie `snapshot` (proces roboczy, klucz konfliktu, wynik, ostrzeżenia
  i kody błędów), zapis migawki w indeksie po publikacji (najlepszym
  wysiłkiem — brakujący wpis dopisuje skan), pliki robocze kopii SQLite
  w katalogu roboczym procesu z kroku 1.
- **Pliki:** `archiwista/owndata/{snapshots,document}.py`,
  `archiwista/jobs/{protocol,worker,supervisor}.py`,
  `archiwista/index/writer.py`, `archiwista/texts/owndata.py`.
- **Interfejs:** umowa „Migawki”.
- **Test/odbiór:** `tests/integration/test_snapshots.py`:
  `test_gpkg_open_for_editing_snapshot_is_consistent` (kryterium 7:
  `GpkgEditor` w WAL — zatwierdzone ramki w `-wal` i otwarta transakcja;
  kopia `PRAGMA integrity_check` = `ok`, wiersze zatwierdzone są,
  niezatwierdzone nie, pyogrio czyta kopię, poza `.wersje/` folder bez
  zmian), `test_wal_without_shm_snapshot_has_committed_rows` (stan (c):
  wiersze tylko z `-wal` są w kopii, w folderze nie powstaje `-shm`),
  `test_interrupted_snapshot_leaves_no_partial_version`
  (kryterium 8: przerwanie w każdej fazie — kopia, sumy, `migawka.json`,
  przed `rename` — przez `fault`, SIGINT i SIGKILL procesu roboczego;
  brak nowej etykiety w `.wersje/`, indeks bez nowej migawki,
  pozostałość tylko w `.incoming/`; SIGKILL tuż po `rename` → kompletna
  migawka z plikami tylko do odczytu, którą dopisuje następny `own_scan`),
  `test_same_content_makes_no_second_snapshot` (kryterium 9: drugi raz
  bez zmian → `unchanged` z etykietą pierwszej; GeoPackage po VACUUM
  i punkcie kontrolnym → `unchanged`; A → B → A → `_2`),
  `test_fileset_changing_during_copy_retries_then_fails`,
  `test_read_only_folder_blocked`, `test_insufficient_space_blocked`,
  `test_default_folder_inside_store_is_refused` (`snapshot_blocked`
  z powodem `folder_invalid`, magazyn bez zmian),
  `test_second_snapshot_of_file_conflicts`, `test_published_files_read_only`
  (pliki `0444` już w chwili `rename`, katalog `0555` po nim),
  `test_chmod_and_directory_fsync_errors_are_notices` (`EPERM` z `chmod`
  i `EINVAL` z `fsync` katalogu → migawka `created` z ostrzeżeniami),
  `test_document_validates_and_sums_match`.
- **Zależności:** 7a, 7b. **Równolegle:** 5a1–5c, 6, 10, 11, 12a.
- **Stan po kroku 8:**
  - *Plan* (`owndata/snapshots.py`): `check_snapshot(folder, file, *,
    work_dir) -> SnapshotPlan` — `folder`: `OwnFolderCheck` sprawdzony teraz
    (`check_own_folder` z `folder_rules`), `file`: karta `OwnFileDetail`.
    Odstępstwo: bez `last` — ostatnia migawka i zmiana są w karcie
    (`unchanged_since` = `file.last_snapshot`, gdy `change == "unchanged"`;
    tożsamość z ostatniego skanu, jak w decyzji 9). `SnapshotPlan(path,
    size_bytes, destination, copy_method, content_method, unchanged_since,
    blocked: SnapshotBlock(reason, message) | None, free_bytes, warnings:
    tuple[SnapshotWarning(code, message)])`; `size_bytes` to pliki kompletu
    (SQLite z `-wal`), bez dostępu do pliku — rozmiar z indeksu.
    Kolejność sprawdzeń: folder (`folder_block(folder)`: `invalid` →
    `folder_invalid`, `missing`/`unreadable` → `file_missing`), plik
    (`file_missing`), prawo zapisu najbliższego istniejącego katalogu na
    drodze do `.wersje/<plik>/` i `.wersje/.incoming/` (`read_only_folder`,
    komunikat podaje katalog), miejsce: folder ≥ 1,1 × rozmiar, dla SQLite
    także lokalny katalog roboczy (× 2 przy `-wal`/gorącym `-journal`: kopia
    widoku i kopia zapasowa) — `insufficient_space`. Plik, człon kompletu
    albo składnik `.wersje/` jako dowiązanie wychodzące →
    `PathOutsideRootError` (dla 9: `403 path_outside_root`). Ostrzeżenie
    `editing_detected` przy `-wal` albo gorącym `-journal`.
  - *Migawka*: `make_snapshot(folder, file, *, author: SnapshotAuthor, note,
    work_dir, reader: OwnReader, transformer, on_phase=None) ->
    SnapshotResult(status, label, directory, document, warnings)`.
    Odstępstwa: (1) `fault` to `on_phase(faza)` — `SNAPSHOT_PHASES`:
    `copy` (kopia w katalogu roboczym), `checksums` (pliki przeczytane
    ponownie), `document` (`migawka.json` zapisany), `rename` (pliki
    `0444` i zsynchronizowane, zaraz `rename`), `published`; zadanie
    raportuje nimi postęp, testy przerywają w nich; (2) bez `cancel` —
    zadanie przerywa SIGINT jak każde (`KeyboardInterrupt` usuwa katalog
    roboczy); (3) `reader` i `transformer`: warstwy, raster, liczba
    obiektów i zasięg (WGS84 przez `Wgs84Outlines` z przypiętej operacji)
    czyta proces czytnika z kopii, nie z indeksu — plik mógł się zmienić od
    skanu; (4) ostatnia migawka z dysku (najnowsza po `created_at`
    z poprawnym dokumentem w `.wersje/<plik>/`), a `unchanged` tylko, gdy
    jej pliki zgadzają się z sumami — uszkodzona nie zastępuje nowej kopii.
    SQLite: `read_sqlite` (trzy stany 7a) i `Connection.backup` z widoku do
    pliku w podkatalogu `snapshot-<token>` katalogu roboczego, potem
    `journal_mode=DELETE` (kopia zapasowa bazy w WAL zachowuje nagłówek WAL
    i migawka `0555` nie otworzyłaby się tylko do odczytu bez `-wal`
    i `-shm`), `integrity_check` (`integrity_failed`, także plik „not
    a database”), tożsamość `content_identity` kopii; `unchanged` nie
    dotyka folderu. Pozostałe: kopia prosto do
    `.wersje/.incoming/<host>_<pid>_<token>/` z SHA-256 liczonym w trakcie
    kopiowania, stan (rozmiar, czas) członów przed i po, 3 próby
    (`inconsistent_copy`); wzór `fileset` wspólny (`content.fileset_sha256`).
    Etykieta z listingu `.wersje/<plik>/` przy zapisie `migawka.json`
    (etykieta jest w dokumencie); publikacja `renameat2(RENAME_NOREPLACE)`
    (Linux; system plików bez niego — sprawdzenie celu i `rename`, który
    nie zastępuje niepustego katalogu), więc także pusty katalog pod
    etykietą to `target_exists`. Pliki `0444` przed `rename`, katalog
    `0555` po nim, `fsync` plików, katalogu roboczego i po publikacji
    rodzica. Nowe katalogi `.wersje/` dostają uprawnienia folderu danych
    (`umask 077` procesu roboczego dałby `0700` i inne konta wspólnego
    folderu nie widziałyby migawek). Odrzucone `chmod` i `fsync` katalogu
    (`EPERM`, `EACCES`, `EINVAL`, `ENOTSUP`) → ostrzeżenia `chmod_refused`,
    `directory_sync_refused`; po publikacji każdy ich błąd to ostrzeżenie.
    `ENOSPC`/`EDQUOT` w trakcie zapisu → `insufficient_space`, `EROFS` →
    `read_only_folder`. Błąd albo przerwanie przed `rename` usuwa katalog
    roboczy; zostaje tylko po zabiciu procesu.
  - *Dokument i skan*: `document.py` dostał `read_snapshot_document(katalog)`,
    `snapshot_files_match(katalog, files)` i `MAX_DOCUMENT_BYTES`
    (przeniesione ze skanu); `scan.py` — `Wgs84Outlines` (dawne
    `_Transformers` z marginesem zasięgu bez powierzchni), wspólne ze
    snapshotami. Zapis dokumentu: `model_dump(mode="json", by_alias=True)`,
    JSON z wcięciem, daty z przesunięciem i co do sekundy.
  - *Błędy* (`errors.py`): `SnapshotBlockedError(reason, message)` (już
    w kroku 8 — dla 9 `409 snapshot_blocked` z `reason`),
    `SnapshotFailedError(code, message)`.
  - *Zadanie `snapshot`*: `JobRule(store=False, conflict=JobConflict(
    "snapshot", (projekt, file_id), "job_conflict_snapshot"))` — migawki
    różnych plików idą równolegle; parametry `{"project", "file_id",
    "note"}` (`file_id` — 16 znaków szesnastkowych, `note` ≤ 2000,
    domyślnie `""`; inaczej `ValueError`). Proces roboczy: projekt (brak →
    `not_found`), folder (`check_own_folder`, przed szukaniem pliku, więc
    folder poza regułami to `snapshot_blocked`/`folder_invalid` także dla
    pliku nieznanego indeksowi), karta pliku (brak → `not_found`,
    `own_file_not_found`), `OwnReader` i operacje producenta, postęp
    `current`/`total` faz z `phase`, ostrzeżenia jako `notice` (`warning`),
    po `created` `record_snapshot` ze `snapshot_stamp` (najlepszym
    wysiłkiem: błąd → `notice` `snapshot_not_indexed`). Wynik `{"status",
    "label", "content_sha256", "size_bytes", "seconds"}`; kody
    `snapshot_blocked` (z `reason`), `inconsistent_copy`,
    `checksum_mismatch`, `integrity_failed`, `target_exists`,
    `path_outside_root`, `own_reader_failed`, `not_found`.
  - *Protokół zadań 3*: `JobSpec.actor_kind` i `JobSpec.session` (autor
    migawki: `id` — aktor, `kind` — rodzaj aktora, harmonogram jako
    `local_owner`, `name` — `null`: proces roboczy nie zna nazw kont,
    `session`); `JobError.reason` i `JobError.to_json()` (w `jobs.error`
    i zdarzeniu `state` tylko, gdy jest), `JobFailure(..., reason=)`
    w procesie roboczym. `index/writer.py` bez zmian (`record_snapshot`
    z 7b wystarcza).
  - *Testy*: `tests/integration/test_snapshots.py` — wszystkie testy planu
    i `test_label_taken_before_rename_is_target_exists` (pusty i kompletny
    katalog pod etykietą); przerwania przez proces roboczy z haczykiem
    `ARCHIWISTA_TEST_SNAPSHOT_FAULT=<faza>:<sygnał>`
    (`tests/fixtures/job_worker.py`). Mutacje (bez sprzątania, bez
    ponowienia kopii, bez `0444`, zwykły `rename`) wywracają odpowiednie
    testy.
  - *Pomiar* (2026-10-19, komputer odniesienia, SSD): GeoPackage 101,2 MB
    (460 000 wielokątów, 3 pola) — migawka 4,7 s (cel ≤ 15 s), ponowna bez
    zmian 4,0 s; skan tego pliku 2,7 s.
  - *Dla 9*: trasa planu — `check_snapshot(check_own_folder(…), karta,
    work_dir=process_work_dir(paths))`, `blocked` → `409 snapshot_blocked`
    z `reason` (`SnapshotBlockedError`), `PathOutsideRootError` → `403`;
    trasa migawki — `jobs.submit("snapshot", params={"project",
    "file_id", "note"}, actor=principal)` po `project.write` (konflikt →
    `409 conflict` z `job`); model API `JobFailure` powinien dostać
    `reason`, a opisy `JobDetail` — rodzaje `own_scan` i `snapshot`.

### 9. Dane własne i migawki przez HTTP i CLI; `project.write`; widoczność zadań
- **Cel:** trasy danych własnych z umowy API (lista, skan folderu
  projektu, folder danych, karta, podglądy pliku roboczego i migawek, plan
  migawki, migawka), rozstrzyganie `file:`/`snapshot:` w `ObjectResolver`
  (plik roboczy: stan sprzed i po renderowaniu, zmiana od skanu → `409
  own_file_changed`; plik SQLite w stanie (b) albo (c) — podgląd z kopii
  spójnej `source.gpkg`, decyzja 8), akcja `project.write`, widoczność
  zadań z danymi projektu w `/jobs`, `/jobs/{id}` i `/jobs/{id}/events`
  (umowa „Zadania”), filtr `project` w `/slots`, `/map/footprints`
  i `GET /jobs`, `own_data` w `/health`, polecenia `files`, `file`,
  `snapshot` i `own-scan`.
- **Pliki:** `archiwista/api/owndata.py`, `archiwista/api/models_owndata.py`,
  `archiwista/api/models.py` (`JobFilters.project`, `Health.own_data`),
  `archiwista/api/{slots,map,jobs,health}.py`, `archiwista/app.py`
  (jedna linia), `archiwista/auth/authorize.py`, `archiwista/refs.py`,
  `archiwista/services/owndata.py`, `archiwista/index/queries.py`,
  `archiwista/jobs/supervisor.py` (zakres widoczności zadań),
  `archiwista/errors.py` (`OwnFileChangedError`, `SnapshotBlockedError`),
  `archiwista/api/errors.py` (ich `409 own_file_changed`
  i `409 snapshot_blocked`), `archiwista/commands/owndata.py`,
  `archiwista/jobs/foreground.py`, `archiwista/cli.py` (jedna linia),
  `archiwista/texts/owndata.py`.
- **Interfejs:** umowa API (wiersze kroku 9), `SnapshotPlan`, CLI
  z decyzji 11; trasy nie filtrują same — `visible_projects` i `Authorizer`
  jak w v0.1, także w trasach zadań.
- **Test/odbiór:** `tests/integration/test_own_data_api.py`
  (`test_folder_with_gpkg_shp_geotiff_indexed_with_extent_and_preview` —
  kryterium 6 przez HTTP: karta, miniatura, kafle GeoTIFF, obiekty
  GeoPackage i Shapefile; `test_own_file_types_have_preview_or_reason`;
  plan → migawka → zadanie → karta; `409 own_file_changed`; `PUT
  data-dir` przez nie-admina → `403`), `tests/unit/test_authorize.py::test_project_write_matrix`,
  `tests/integration/test_permissions_api.py::test_own_data_visibility_matrix`
  (każda nowa trasa z projektem, `file:`/`snapshot:` w podglądach
  i `/compare`, filtr `project`; zadania: `GET /jobs` z `project=` i bez,
  `/jobs/{id}` i `/jobs/{id}/events` zadania `snapshot` (z `note`),
  zadania `preview` z `file:` i mieszanego (`version:` i `file:` — tylko
  widoczne `refs` i `failed[]`) oraz `own_scan` projektu: niewidoczny →
  brak na liście albo `404`; migawka bez `project.write` → `403`, bez
  CSRF → `403 csrf_rejected`, tryb lokalny może wszystko),
  `tests/integration/test_preview_security.py::test_failure_message_carries_no_other_projects_path`
  (dwa projekty z tymi samymi uszkodzonymi bajtami: powód i komunikat bez
  ścieżki pierwszego projektu) i `::test_store_and_own_folder_unchanged_after_previews`
  rozszerzony o folder danych własnych (pliki SQLite w trzech stanach),
  `tests/integration/test_cli.py::test_own_data_cli_equals_http` (także
  `own-scan`), `tests/integration/test_agent_flow.py::test_agent_snapshot_flow`
  (token → sesja → plan → migawka → SSE zadania → karta).
- **Zależności:** 6, 7b, 8. **Równolegle:** 10, 11, 12a, 12b.
- **Stan po kroku 9 (commity `aa01878`, `3231869`, `2126c33`, `dcbb454`,
  `003be5f`, próby `57005bb`):**
  - *Uprawnienia i filtr `project`* (`aa01878`): `project.write`
    w `Action`/`ACTIONS` — właściciel albo `admin`; projekt bez wpisu
    dostępu zmienia tylko administrator (komunikat
    `permission_project_write`). Filtr `project` (klucz projektu)
    w `/slots`, `/map/footprints` i `archiwista search --project`: wersje
    przypięte w projekcie razem z trybem `versions` (`current` — przypięte
    bieżące, `pinned`/`all` — wszystkie przypięte), kursor związany
    z projektem; projekt nieznany albo niewidoczny → `404`
    (`api/slots.checked_project`, też w `GET /jobs?project=`).
  - *Widoczność zadań* (`3231869`, `jobs/supervisor.py`): zakres
    `_Scope.of(store, params)` — część magazynowa (`store` albo `version:`
    w `refs`; widzą wszyscy) i projekty (`params.project`, projekt każdego
    `file:`/`snapshot:`); zadanie bez projektu (globalny `own_scan`) widzą
    wszyscy, zadanie tylko projektów — kto widzi któryś z nich. `list`,
    `get` i `events` przyjmują `visible` (domyślnie `ALL_PROJECTS`), `list`
    także `project`; filtr w zapytaniu przez funkcję SQLite `job_listed`
    (strony pełne). Zadanie `preview` oglądane bez wszystkich projektów:
    `refs` z `contents` i `failed[]` (także w końcowym zdarzeniu `state`)
    tylko widocznych projektów, liczniki w całości. `JobFailure.reason`,
    `JobFilters.project`, `OwnDataState` i `Health.own_data`
    (`finished_at`, `busy` z `own_scan_history`; `null` bez nadzorcy,
    np. w `archiwista status --json`).
  - *Odwołania* (`2126c33`, `refs.py`): `ObjectResolver(queries, settings,
    *, visible=None)` — `visible`: principal → `ProjectVisibility`
    (`Authorizer.visible_projects`; bez niego danych własnych nie widać).
    `file:` — plik w `realpath` folderu (dowiązanie poza folder → `403
    path_outside_root`); przy każdym użyciu `stamp_holds`
    (`owndata/scan.py`, same wywołania `stat`: rozmiar i czas pliku,
    członów kompletu i `-wal`/`-journal`, nowy `-wal`/`-journal` też jest
    zmianą; człon dopisany do kompletu po skanie widać dopiero po skanie);
    zmiana albo zniknięcie od skanu → `OwnFileChangedError` (`409
    own_file_changed`: „Odśwież” albo `POST …/scan`); klucz pamięci =
    `content_sha256` skanu (bez niego `unreadable`); źródło `mutable` ze
    stanem pliku i `-wal` odczytanym przed sprawdzeniem stempla (proces
    renderujący sprawdza go przed i po renderowaniu; SQLite w stanie (b)
    i (c) — kopia spójna `source.gpkg` z kroku 5b); plik, którego skan nie
    znalazł → `missing_file`. `snapshot:` — pliki wymienione
    w `migawka.json` w `.wersje/<plik>/<etykieta>/`, klucz = tożsamość
    treści dokumentu (podglądy wspólne z każdym plikiem tej treści),
    migawka nie `ok` → `unreadable`, `locate` tylko z indeksu. Projekt
    niewidoczny, nieznany plik albo etykieta → `404`. `job_resolver` widzi
    wszystkie projekty (`refs` sprawdzone przy zleceniu);
    `build.RESOLVERS` — `version`, `file`, `snapshot`; nierozwiązany `ref`
    dostaje własny opis porażki (wcześniej każdy `ref` treści dostawał
    opis ostatniego, który mógł nazwać plik innego projektu).
  - *Trasy* (`api/owndata.py`; w `app.py` import i dwa `include_router`):
    wiersze kroku 9 z umowy API oraz `GET …/members` pliku i migawki
    (archiwa). Migawka:
    projekt niewidoczny `404` → brak `project.write` `403` → nieznany plik
    `404` → plan z `blocked` `409 snapshot_blocked` z `reason` → migawka
    tego pliku w toku `409 conflict` z `job`. `POST …/scan` i `POST
    …/snapshots` w `job_router` (tylko przy nadzorcy zadań, jak `/jobs`);
    zlecone zadanie pokazane tak, jak widzi je sesja. `PUT …/data-dir` od
    razu zleca `own_scan` projektu. Folder jeszcze nieskanowany: lista
    i `PUT` opisują go stanem z `folder_check` teraz (`scanned_at: null`,
    `OwnFolder.checked`, bez plików). `OwnFileCard.preview` = odpowiedź
    `GET …/preview` (`null` bez puli, przy pełnej kolejce albo dla pliku
    dowiązanego poza folder). Obrazy i dane danych własnych:
    `Cache-Control: private, no-cache` z `ETag`
    (każde użycie sprawdza widoczność, potem `304`). Funkcje bez HTTP dla
    CLI: `visible_project`, `own_file`, `read_own_files`, `own_file_card`,
    `snapshot_plan`, `start_snapshot`, `start_own_scan`, `change_data_dir`,
    `own_ref`; w `services/owndata.py` — `folder_check`, `folder_problems`,
    `file_problems`.
  - *Podglądy* (`previews/service.py`, `api/previews.py`): `object_url`
    plików (`/projects/{project}/files/{file_id}`) i migawek
    (`…/snapshots/{label}`); plik zmieniony przed renderowaniem albo
    w jego trakcie → `409 own_file_changed` dla obrazów i danych,
    w `PreviewInfo` — `unavailable` z `changed_since_scan`. Wspólne
    pomocniki tras wersji i danych własnych: `info_answer`, `build_answer`
    (zadanie nowe albo dołączone pokazane przez `jobs.get(id, visible=…)`
    — także w `POST …/preview` wersji), `respond`, `members_answer`,
    `require_tile`, `optional_jobs`. `archiwista preview` bierze
    widoczność z `Authorizer` bazy stanu (`local_previews(…, visible=)`).
    Teksty `missing_file` już nie tylko o wersjach.
  - *CLI* (`commands/owndata.py`, linia w `COMMAND_MODULES`): `archiwista
    files PROJEKT [--q] [--state] [--limit] [--cursor]`, `file PROJEKT
    PLIK` (16 znaków szesnastkowych → `file_id`, inaczej ścieżka
    w folderze), `snapshot PROJEKT PLIK [--note TEKST | --plan]` (oba
    razem → kod 2), `own-scan [--project PROJEKT]`; `--json` = model trasy,
    zadania na `run_foreground`, zadanie nieudane → `JobDetail` i kod 1.
  - *Porównanie* (`dcbb454`): strony `file:` i `snapshot:` w `_compared`
    (tylko indeks): grupa `own` (`OWN_FIELDS`: format, liczba obiektów,
    układ, zasięg, rozmiar — migawki: bajty kopii, metoda i SHA-256
    treści, data, autor i opis migawki, modyfikacja, pierwsze wykrycie
    i ostatnia zmiana pliku), grupa `layers` (obiekty w warstwie);
    `same_content` z tożsamości treści (metoda i SHA-256; `sha256` wersji
    = metoda `bytes`); `schema_diff` (`SchemaDiff`: warstwy tylko w A albo
    B, `LayerDiff` z polami dodanymi, usuniętymi i o innym typie), gdy obie
    strony mają warstwy wektorowe; w CLI blok „Schemat warstw”. Tekst
    `compare_kind_unsupported` usunięty, `file:` nieznanego projektu →
    `404`.
  - *Warstwy pliku własnego* (`003be5f`): `GET
    /projects/{project}/files/{file_id}/layers` — opis w „Stan po kroku
    11”.
  - *Odstępstwa od umowy:* `GET …/members` plików i migawek (poza listą
    tras); `LayerSet.store`, `product` i `group` mogą być `null`, rodzaje
    warstw `file` i `snapshot`.
  - *Próby* (`57005bb`): `tests/integration/test_own_data_api.py`
    (kryterium 6 przez HTTP — GeoPackage, Shapefile i GeoTIFF: karta,
    miniatura z `304`, kafel, obiekty; każda rodzina z podglądem albo
    powodem; plan → migawka → zadanie → karta, ponowna migawka bez zmian
    `unchanged`; `409 own_file_changed` do ponownego skanu; `PUT data-dir`
    — `403` dla nie-admina, `422` z `problems`, `200` i `own_scan`; `409
    snapshot_blocked` z `file_missing` i `409 conflict` przy migawce
    w kolejce — nadzorca z `default_max_jobs` = 0),
    `test_agent_flow.py::test_agent_snapshot_flow` (prawdziwy `archiwista
    serve`), `test_cli.py::test_own_data_cli_equals_http` (także
    `own-scan` z projektem i bez; `free_bytes` planu poza porównaniem —
    wolne miejsce zmienia się między wywołaniami),
    `test_permissions_api.py::test_own_data_visibility_matrix` (4
    widoczności × 4 osoby i tryb lokalny, 51 sprawdzeń na układ: trasy
    plików i migawek, `304` tylko dla widzących, `/compare`, filtr
    `project`, zadania `snapshot`, `preview` z `file:`, mieszane `preview`
    i `own_scan` w `/jobs`, `/jobs/{id}` i zdarzeniach, `project.write`,
    bez CSRF `403 csrf_rejected`; ok. 20 s; łamie się po wyłączeniu
    redakcji, widoczności zadań albo `project.write`),
    `test_preview_security.py::test_failure_message_carries_no_other_projects_path`
    i `::test_store_and_own_folder_unchanged_after_previews` z folderem
    danych własnych (wszystkie rodziny i GeoPackage w stanach (a), (b) —
    `GpkgEditor` z otwartą transakcją, (c) — `-wal` bez `-shm` i gorący
    dziennik; z budową kopii spójnych; bez `.aux.xml` i nowych plików
    obok). Próby porównania i warstw pliku w ich commitach. Przebieg
    obszarów kroku (`tests/unit`, `tests/contract` i 17 plików
    integracyjnych): 817 zielonych w 400 s; ruff, format i mypy czyste;
    próba dymna tras i poleceń na folderze z GPKG, SHP, GeoTIFF i TXT.
  - *Uwagi:* plik z jednym punktem ma `PreviewInfo.bounds` o zerowej
    powierzchni, a `bbox` w `…/features` jej wymaga (`422`) — klient mapy
    musi poszerzyć widok (kroki 12b, 15). Teksty z `with_detail` po
    powodzie zakończonym kropką dają „….: …”. Typy `web/src/types.js`
    zadań (`own_scan`, `snapshot`, `reason`, `project`) dochodzą
    w kroku 15.

### 10. Porównanie metadanych
- **Cel:** `services/compare.py` i `GET /compare` (decyzja 10, poziom 1),
  `archiwista compare REF REF`.
- **Pliki:** `archiwista/services/compare.py`, `archiwista/api/compare.py`,
  `archiwista/api/models_compare.py`, `archiwista/app.py` (jedna linia),
  `archiwista/commands/compare.py`, `archiwista/cli.py` (jedna linia),
  `archiwista/texts/compare.py`, `archiwista/messages.py` (jedna linia).
- **Interfejs:** model `Comparison` z umowy API.
- **Test/odbiór:** `tests/integration/test_compare.py` (dwie wersje
  jednego slotu: daty, kampania, `sha256`, rozmiar różne, pola surowego
  sidecara jako spłaszczone ścieżki; wersje dwóch slotów; migawka z
  plikiem roboczym: liczby obiektów, pola dodane i usunięte, zasięg;
  ta sama treść → `same_content`; zły `ref` → `422 invalid_ref`;
  niewidoczny projekt → `404`), `tests/integration/test_cli.py::test_compare_cli_equals_http`.
- **Zależności:** 6; strony danych własnych po 9. **Równolegle:** 5a2,
  5a3, 8, 11, 12a, 12b.
- **Stan po kroku 10 (strony: wersje magazynu; strony danych własnych po
  kroku 9):**
  - *Usługa* (`services/compare.py`): `compare(queries, a, b, *, visible)
    -> Comparison` — tylko indeks lokalny, żaden plik danych nie jest
    otwierany. Najpierw grupa `metadata` w kolejności `VERSION_FIELDS`
    (data i rok danych, pobranie, etykieta, kampania, zgłoszenie prac,
    wydanie, pełny arkusz wg producenta, pokrycie, rozdzielczość, układ
    poziomy i wysokości, `nodata`, `sha256`, rozmiar, licencja,
    atrybucja; nazwy `compare_field_<pole>`), potem grupa `sidecar`: liście
    surowego sidecara jako ścieżki JSON (`extra.campaign.id`,
    `request.bbox[0]`; pusty obiekt albo tablica — jej tekst JSON), nazwą
    wiersza jest sama ścieżka; najpierw pola A, potem tylko z B.
    `differs` uwzględnia typ (`1` ≠ `true`). `same_content` — oba `sha256`
    znane i równe (wersja bez `sha256` → `false`).
  - *Model* (`api/models_compare.py`): `CompareQuery` (`a`, `b`,
    `extra=forbid`), `ComparisonSide` (`ref`, `kind`, `title` „<nazwa
    pliku> — <etykieta>”, `preview` — adres opisu podglądu `…/preview`
    z `object_url`, `outline` — obrys WGS84 z indeksu), `ComparisonRow`
    (wartości: tekst, liczba, wartość logiczna, data albo czas jak w karcie
    wersji, `null`), `Comparison`.
  - *Trasa i CLI.* `GET /compare` (`api/compare.py`; sesja i CSRF jak
    wszędzie): zły `ref` i (do kroku 9) rodzaj jeszcze nieporównywany →
    `422 invalid_ref` (tekst `compare_kind_unsupported`), nieznana wersja →
    `404 not_found`, brak `a`/`b` albo nadmiarowy parametr → `422
    validation_error`. `archiwista compare REF REF [--json]`
    (`commands/compare.py`, jedna linia w `COMMAND_MODULES`); bez `--json`
    strony, wiersz na pole z `*` przy różnicy i podsumowanie.
  - *Punkt rozszerzenia dla kroku 9.* `services/compare.py::_compared`
    rozstrzyga rodzaj `ref`: krok 9 dopisuje tam `FileRef`
    i `SnapshotRef` (projekt niewidoczny w `visible` → `404`; wiersze
    z decyzji 10: liczby obiektów per warstwa, zasięg, układ, rozmiar,
    tożsamość treści, autor, opis, daty; `same_content` z tożsamości
    treści), nowe grupy w `RowGroup`, model `schema_diff` zamiast `None`
    w `Comparison` i `object_url` danych własnych (`preview`). Odbiór
    kroku 10 dla migawki z plikiem roboczym i niewidocznego projektu
    przechodzi na krok 9. Zrobione w kroku 9 (`dcbb454`, „Stan po kroku 9”).
  - *Testy.* `tests/integration/test_compare.py` (dwie wersje jednego
    arkusza NMT z kampanią i różnym rozmiarem dopisanymi do sidecarów
    przed skanem: daty, kampania, `sha256`, rozmiar różne, reszta zgodna
    z kartą wersji; spłaszczone pola sidecara; wersje dwóch slotów;
    `same_content` dla dwóch wersji tych samych bajtów i wersji z samą
    sobą; `422 invalid_ref`, `404`, `422 validation_error`, `403
    csrf_rejected`, OpenAPI) i
    `tests/integration/test_cli.py::test_compare_cli_equals_http`.

### 11. Warstwy lokalne, miniatury i kafle warstw
- **Cel:** `services/layers.py` i `GET /local-layers` (decyzja 7):
  grupowanie wersji slotów obszaru po wariancie bez formatu plików
  (A-ADR-017: `product`, `horizontal_crs`, `resolution`, `vertical_crs`;
  segment, gdy któregoś pola brak; formaty jako plakietki) i po roku
  danych, wydaniu albo etykiecie (`group=campaign` — po kampanii),
  odświeżenie widoku wspólnym pomocnikiem z `/local-coverage` (pamięć
  60 s dla tej samej pary obszaru i segmentu; warstwa wariantu odświeża
  każdy swój segment), pokrycie lokalne warstwy w układzie płaskim,
  obrysy w kadrze, stan podglądów warstwy z jednym zadaniem `preview`
  na brakujące, `GET /local-layers/thumbnail.png` (parametr `v` = skrót
  gotowych treści, więc adres zmienia się, gdy dojdą podglądy),
  `GET /local-layers/tiles/{z}/{x}/{y}.png` (kafel warstwy z operacji
  `layer_tile`, `minzoom` warstwy — decyzja 7), warstwy pliku własnego
  (`GET /projects/{project}/files/{file_id}/layers`: plik roboczy na górze,
  migawki od najnowszej, kadr = suma zasięgów), `archiwista layers`
  z `--thumbnail KLUCZ [--size N] --output PLIK.png`.
- **Pliki:** `archiwista/services/layers.py`, `archiwista/api/layers.py`,
  `archiwista/api/models_layers.py`, `archiwista/api/areas.py` (wspólny
  pomocnik odświeżenia), `archiwista/app.py` (jedna linia),
  `archiwista/commands/layers.py`, `archiwista/cli.py` (jedna linia),
  `archiwista/texts/layers.py`, `archiwista/messages.py` (jedna linia).
- **Interfejs:** `LayerSet` z umowy API; operacje `layer_thumbnail`
  i `layer_tile` z kroku 5a3.
- **Test/odbiór:** `tests/integration/test_local_layers.py`
  (`test_layers_by_data_year_never_download_year`,
  `test_layers_by_edition_without_year`, `test_group_by_campaign`,
  `test_two_formats_of_one_variant_make_one_layer` — segmenty ASC
  i ASCII-NMT tego samego produktu, układów i rozdzielczości: jedna
  warstwa z `formats`, liczniki bez podwojenia,
  `test_variant_falls_back_to_segment_without_metadata`,
  `test_layer_coverage_planar`, `test_outlines_in_frame_crs`,
  `test_refresh_before_answer_and_stale_when_disconnected`,
  `test_layer_thumbnail_partial_then_full_after_build`,
  `test_layer_tile_composes_version_tiles` — kafel na styku dwóch
  arkuszy ma piksele obu, wersje bez podglądu są przezroczyste, poniżej
  `minzoom` → `404`, `test_without_area_counts_only`,
  `test_own_file_layers_current_first`),
  `tests/integration/test_cli.py::test_layers_cli_equals_http` (także
  `--thumbnail`).
- **Zależności:** 3, 5a1, 5b, 6; odbiór miniatur i kafli warstw po 5a3;
  warstwy migawek po 9. **Równolegle:** 5a2, 5a3, 10, 12a.
- **Stan po kroku 11 (kod `a5ae7f3`, próby `02228f4`; warstwy pliku
  własnego w kroku 9, `003be5f`):**
  - *Usługa* (`services/layers.py`): `read_local_layers` (odświeżenie
    widoku → `IndexQueries.product_versions` → wersje, których obrys ma
    wspólne wnętrze z obszarem → warstwy), `layer_images`,
    `layer_thumbnail`, `layer_tile`, `LayerMemo` (60 s, 256 warstw: kafle
    widoku bez ponownego czytania indeksu), `LayerImages`/`LayerItem`
    (źródło z indeksu, zasięg WGS84, `resolve` na dysk — punkt
    rozszerzenia dla warstw pliku własnego i migawek z kroku 9 — w kroku 9
    niepotrzebny, zob. ostatni punkt). Wariant:
    12 znaków SHA-256 z `product\nhorizontal_crs\nresolution\nvertical_crs`,
    bez któregoś pola — segment; okres: `data_year`, inaczej `edition`,
    inaczej `label` (pusty: „bez roku i wydania”); `group=campaign`
    dokleja `:<kampania>`. Formaty-plakietki: `FileFormat.name` z
    rozszerzenia (np. `ASCII Grid`, `ZIP`); `units_count` po jednostce
    (arkusz w dwóch formatach liczy się raz); `subtitle` — nazwa
    najczęstszego segmentu warstwy. Stan wersji tylko z pamięci podglądów
    (bez rozpoznania w żądaniu): rodzaje `document`/`archive`/`auxiliary`/
    `unknown` i powód w `info.json` → `unavailable`, brak `info.json` albo
    COG → `needs_build`; brakujące w granicach budowy automatycznej idą
    jednym zadaniem `preview` na warstwę (serwer zleca, kolejne odpowiedzi
    dołączają; bez zlecania przy odłączonym magazynie i w CLI). `v` = 16
    znaków SHA-256 posortowanych gotowych treści; obraz z dokładnie tymi
    treściami ma `immutable`, inny `private, no-cache`; przy braku
    w pamięci wersje są rozwiązywane na dysku (odłączony magazyn → `503
    store_unavailable`, plik usunięty albo dowiązanie poza korzeń —
    pominięty). `minzoom` = ⌈log2(32 / mediana krótszego boku arkusza
    w px kafla z = 0)⌉; poniżej i poza zasięgiem → `404`.
  - *Odświeżenie* (`api/areas.py`): `refresh_area` (pomocnik obu tras)
    i `AreaRefreshes` w `app.state.area_refreshes`. Odstępstwo od opisu:
    `/local-coverage` zawsze skanuje (przycisk „Odśwież” i
    `test_local_coverage_after_refresh`, pomiar `test_store_50k_view_refresh_of_500_slots`
    wymagają skanu przy każdym żądaniu) i tylko zapisuje skan w pamięci;
    `/local-layers` pomija segment obszaru zeskanowany w ciągu 60 s, o ile
    katalog magazynu jest na miejscu i niepusty.
  - *Inne zmiany:* `IndexQueries.product_versions` + `ProductVersion`,
    `ObjectResolver.version_source` (wspólne `_version_source` z
    `_version`), `PlanarMover`/`measure_planar` w `index/coverage.py`
    (`measure_coverage` bez zmian w wyniku), publiczne `while_connected`,
    `ClientGone`, `preview_problems`, `image_responses` w
    `api/previews.py`; `app.state.layer_memo`; `archiwista layers`
    (`--thumbnail KLUCZ --output PLIK.png [--size N] [--style STYL]`,
    `--thumbnail` bez `--output` → kod 2).
  - *Sprawdzone:* próba dymna na magazynie `make_store` z prawdziwą pulą
    i zadaniami (warstwy lat, zadania `preview` na warstwę, miniatura
    i kafel z pamięci 3–15 ms, poniżej `minzoom` → `404`, CLI z
    `--thumbnail`); `test_local_coverage.py`, `test_coverage.py`,
    `test_previews_api.py`, `test_compare.py`, `test_imports.py` — 44
    zielone; ruff, format i mypy na zmienionych plikach czyste.
  - *Próby* (`02228f4`): magazyn ręczny `tests/fixtures/layer_store.py`
    (ścieżki z `FileStorage`, sidecary z `extra.campaign.id`, arkusz NMT
    w ASC i ASCII-NMT z jednego nalotu, sidecar bez `resolution`
    i `vertical_crs`, wycinek WCS z etykietą daty pobrania, arkusz poza
    obszarem, wydania BDOT10k bez roku; wszystko pobrane w latach
    2025–2026; magazyn sprawdzany przez `iter_store`)
    i `tests/integration/test_local_layers.py` — 12 prób z listy
    „Test/odbiór” bez `test_own_file_layers_current_first` (krok 9):
    warstwy lat danych (wycinek bez roku — warstwa etykiety), wydań
    i kampanii; jedna warstwa z formatami `ASCII Grid` i `ZIP` (4 wersje,
    2 arkusze, archiwum bez podglądu poza `total`); wariant z segmentu;
    pokrycie w EPSG:2180 równe policzonemu w próbie przez pyproj i shapely
    (pas 1,6° na północ: w stopniach udział inny o > 1%); obrysy w kadrze
    = prostokąty arkuszy w EPSG:2180 (do 1 cm); nalot dopisany po skanie
    w pierwszej odpowiedzi; odłączony magazyn (brak katalogu albo pusty
    punkt montowania) → `stale` z indeksu, bez nowych zadań; miniatura
    i kafel na styku dwóch arkuszy przed budową (gotowy jeden arkusz,
    drugi przezroczysty) i po niej (oba; kafel warstwy = kafle wersji),
    oba adresy `v` z `immutable`, `304`, poniżej `minzoom` i poza
    zasięgiem `404`; bez obszaru same liczby całego magazynu, bez zadań.
    `test_cli.py::test_layers_cli_equals_http` (bez obszaru, `--group
    campaign`, z obszarem po zbudowaniu podglądów, `--thumbnail` — te same
    bajty co HTTP, nieznany obszar `422`, nieznana warstwa `404`,
    `--thumbnail` bez `--output` → kod 2) i
    `test_cz_control_point.py::test_cz_preview_tile_within_2_m` (krok 5a).
  - *Pomiar roku z 200 arkuszy* (komputer odniesienia, SSD, prawdziwy
    `archiwista serve`, skrypt jednorazowy): 200 sąsiednich arkuszy
    1:10 000 z `find_sheets_for_bbox` (20 × 10, ASC 64 × 64 px, nalot
    2023). Skan startowy 0,18 s; pierwsze `/local-layers` z odświeżeniem
    200 slotów 0,14 s; zadanie `preview` warstwy zbudowało 200 COG
    w 118 s (n = 2). Widok 1440 × 900 px przy `minzoom` = 11 (cały rok;
    28 kafli, z tego 13 poza warstwą → `404`): pierwsze rysowanie 6,1 s,
    potem z pamięci przez 6 połączeń, od pierwszego żądania do ostatniego
    kafla — mediana 0,075 s, p95 0,14 s, maks. 0,16 s z 30 prób (kafel p95
    35 ms); przy z = 12 (35 kafli) mediana 0,11 s, p95 0,16 s. Cel ≤ 2 s
    spełniony. Po minucie (`LayerMemo` wygasa) pierwszy widok trwa 0,85 s,
    bo każde z 6 równoległych żądań czyta warstwę z indeksu od nowa — też
    w celu, więc bez zmian w kodzie. RSS serwera 160 MB.
  - *Warstwy pliku własnego* (krok 9, `003be5f`): `GET
    /projects/{project}/files/{file_id}/layers` (`api/owndata.py`,
    usługa `services/layers.read_own_file_layers`): na górze plik roboczy
    (klucz `file`, „plik roboczy”), potem migawki od najnowszej
    (`snapshot:<etykieta>`, „migawka <etykieta>”, podtytuł ze ścieżką
    i opisem); warstwa = jeden obiekt z jednym `LayerVersion`. Kadr = suma
    zasięgów w układzie płaskim ich kraju (jak kadr obszaru: PL EPSG:2180,
    CZ EPSG:5514), bok co najmniej 1/10 dłuższego i 1 m, margines na
    znaczniki; obrysy w kadrze. Stan i adresy z `PreviewService.info`
    obiektu: `thumbnail_url` to `…/preview.png` obiektu z `bbox` kadru,
    `tiles_url` — jego kafle, gdy gotowy; plik zmieniony od skanu →
    `unavailable`. `LayerImages`/`LayerItem` niepotrzebne: obrazy idą
    trasami obiektów, które same sprawdzają widoczność i zmianę pliku.
    `LayerSet.store`/`product`/`group` = `null`, rodzaje warstw `file`
    i `snapshot`; odpowiedzi `/local-layers` bez zmian. Próba
    `test_local_layers.py::test_own_file_layers_current_first` (dwie
    migawki z `write_snapshot_fixture`, kolejność, kadr, piksele
    miniatur tylko w zasięgu własnego obiektu, projekt prywatny → `404`).

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
- **Stan po kroku 12a:**
  - *Karta pliku* (`views/file.js`). Wersja ma dwie zakładki ARIA
    (`tablist`, strzałki, Home, End): „Metadane” — treść karty v0.1 bez
    zmian — i „Podgląd” (`PreviewPane`). Odstępstwo: domyślna zostaje
    „Metadane”, „Podgląd” jest drugą zakładką — otwarcie karty z mapy,
    Katalogu czy wyszukiwania nie uruchamia procesów renderujących
    (podgląd na żądanie), a karta i testy v0.1 się nie zmieniają. Zakładka
    i styl są w adresie (`file_tab=preview`, `file_style=<styl>`; stałe
    `TAB_PARAM`, `STYLE_PARAM`), znikają z kartą razem z `file_version`
    (`CARD_PARAMS`), więc styl zostaje przy przejściu między wersjami na
    osi. Wartości techniczne tytułu wersji: `path` i `ref`.
  - *Moduł* `src/previews.js` z własnym arkuszem `src/previews.css`
    (odstępstwo: plan wymieniał `views/cards.css`; jak `search.js`
    i `search.css`, bo moduł posłuży mapie, Wachlarzowi i danym własnym;
    `cards.css` dostał tylko zakładki). Eksporty:
    `usePreviewImage(address) -> {src, problem, loading}` (`blob:`
    z `getImage`, zwalniany przy zmianie adresu i odmontowaniu, poprzedni
    obraz zostaje do nadejścia następnego; problem `409` z `reason`
    pokazuje `PreviewReason`), `PreviewPane({preview, name, style,
    onStyle, children})` z `PreviewSource` = `{key, load(signal),
    build(force)}` (wersja: `getPreview`/`buildPreview`; plik własny
    i migawka — funkcje kroku 9 w kroku 15), `PreviewLegend` (gradient
    z `colors` i zakresem z jednostką albo klasy z próbkami kolorów —
    kolory tylko `#rrggbb`), `PreviewReason` (komunikat, „Co zrobić:”,
    kod i komunikat biblioteki pod `Tech`; nuta przy pliku pokazującym coś
    mimo powodu, ostrzeżenie przy `unavailable`/`failed`), `styleName`,
    `THUMBNAIL_SIZE` (512). Panel: miniatura w wybranym stylu, przełącznik
    stylów (`Seg`, przy > 1 stylu), legenda stylu (`legends[styl]`),
    powód, fakty (rodzaj, stan, „Na mapie”), budowa: `needs_build`
    z `auto_build` — sama, raz na obiekt i stronę (`AUTO_ASKED`), plik
    ponad progi albo po nieudanej budowie automatycznej — „Zbuduj
    podgląd” (`force: true`), `building` — śledzenie `info.job`; postęp
    przez `useJob`/`JobStatus` (podsumowanie: zbudowane, z pamięci,
    nieudane z kodem i opisem, sekundy), po końcu zadania opis od nowa;
    miniatura pliku ponad progi czeka na budowę (bez żądania); „Sprawdź
    ponownie” przy `failed` i powodach chwilowych (`TRANSIENT_REASONS`);
    wektor — warstwy (`<details>`: układ, pola z typami po polsku, tabela
    próbki atrybutów), LAZ — nagłówek, klasy ASPRS z udziałem i opis
    próby (`sampled_from`), ZIP — człony z `members_url` (pierwsze 200,
    „Pokaż wszystkie”).
  - *Klient API* (`api.js`): `getPreview`, `buildPreview` (`202 JobDetail`
    albo `200 PreviewInfo` bez `id`), dla adresów z odpowiedzi
    `apiAddress(address, query)` (tylko `/api/v1/` tego pochodzenia,
    inaczej wyjątek — token CSRF nie wychodzi gdzie indziej; dokłada
    udokumentowane parametry), `getImage(address) -> Blob`,
    `getLinked(address) -> JSON`; `request` i one dzielą `send` (nagłówek
    CSRF, problemy, utrata sesji). `types.js`: `PreviewInfo` i modele
    kroku 6, `Health.previews`, `Settings.preview_cache_limit_gb`, `ref`
    w `Version`/`VersionCard`, rodzaj zadania `preview`.
  - *Odstępstwo od umowy API kroku 6* (uzgodnione z jego wykonawcą):
    `GradientLegend.colors` (model gubił `colors` z `legends.legend`)
    i `PreviewInfo.legends` (legenda każdego stylu, który ją ma, po
    nazwie stylu; `legend` bez zmian) — bez nich interfejs nie narysuje
    rampy ani legendy hipsometrii NMT, którego stylem domyślnym jest
    cieniowanie.
  - *Ustawienia* (`setup.js`): zestaw „Pamięć podglądów” w kroku „Tryb
    pracy” (bez nowego kroku kreatora — przebieg i testy v0.1 bez zmian):
    pole limitu (liczba całkowita 1–10 000 sprawdzana przed „Dalej”
    i zapisem; problem serwera z polem `preview_cache_limit_gb` przy
    polu), zajętość z `/health` (`previews`) w GB i MB po 1024³ i 1024²
    bajtów jak limit, procent, liczba plików z podglądami, pasek; wiersz
    podsumowania „Pamięć podglądów: limit N GB”. Wspólne drobiazgi:
    `labels/common.js` `job_kind.preview`, `styles.css` (`.field
    input.short`, `.cache-usage`), spacja przed nazwami podkładów.
  - *Próby*: `tests/e2e/test_previews.py` (6 testów, ok. 44 s): miniatura
    `blob:` z nagłówkiem CSRF i rampa z `colors` po przełączeniu na
    hipsometrię, powody JGW i PNG z zaleceniem i człony ZIP zgodne
    z `zipfile`, budowa ASC sama przy pierwszym podglądzie (`POST` z
    `force: false`, pasek postępu, „zakończone”, „gotowy”, bez ponownej
    budowy po przeładowaniu), limit i zajętość w Ustawieniach, wszystkie
    rodzaje bez naruszeń CSP i bez żądań poza serwer offline. Zrzuty
    (`<katalog-danych>/v02-12a/`, 13 widoków, także raster ponad progi —
    `hostile_files.huge_raster` pod wersją: „Zbuduj podgląd” → zadanie —
    i telefon 390 px). Inne pliki e2e nie uruchamiane (zasady szybkości).

### 12b. Interfejs: podglądy na mapie
- **Cel:** `transformRequest` w `map/canvas.js`; podgląd wersji na mapie
  (przycisk „Pokaż podgląd na mapie” w Karcie pliku: kafle wersji w jej
  granicach i obrys); warstwy lat z `/local-layers` jako przyciski lat na
  mapie (SPEC 6.1), wybrana warstwa = obrysy jej wersji i jedno źródło
  rastrowe z kafli warstwy (`/local-layers/tiles`, decyzja 7; poniżej
  `minzoom` warstwy same obrysy i „Przybliż, aby zobaczyć podgląd”);
  obiekty wektora w widoku z `zoom` mapy (decyzja 4); legenda podglądu
  w legendzie mapy; wybór warstwy w adresie (`layer`).
- **Pliki:** `archiwista/web/src/map/{canvas,previews,legend,panel}.js`,
  `archiwista/web/src/views/{map,file}.js`, `archiwista/web/src/api.js`,
  `archiwista/web/src/labels/{map,file}.js`, `archiwista/web/src/map/map.css`.
- **Interfejs:** umowa WWW; trasy kroków 6 i 11.
- **Test/odbiór:** `tests/e2e/test_map_previews.py`
  (`test_version_tiles_on_map_with_csrf_header`,
  `test_year_buttons_select_layer_and_tiles`,
  `test_year_layer_is_one_raster_source`,
  `test_below_layer_minzoom_outlines_and_hint`,
  `test_layer_in_url_restores_view`, `test_no_csp_violations_map_previews`);
  `tests/e2e/test_map.py` bez regresji.
- **Zależności:** 11, 12a. **Równolegle:** 9, 10.
- **Stan po kroku 12b:**
  - *Nagłówek CSRF* (`map/canvas.js`): `transformRequest` mapy dokłada
    `X-Archiwista-CSRF` przez `apiHeaders(url)` z `api.js` — tylko adresom
    `/api/v1/` tego pochodzenia (podkład i każde inne pochodzenie bez
    nagłówka; ta sama reguła co `apiAddress`). `apiTemplate(template,
    query)` dokłada udokumentowane parametry do szablonów z odpowiedzi
    (`tiles_url`, `features_url`) bez psucia `{z}/{x}/{y}`, `{bbox}`,
    `{zoom}`; `getLocalLayers` i typy `LayerSet`/`Layer`/`PreviewFeatures`.
  - *Moduł* `src/map/previews.js`: `PREVIEW_PARAM` (`preview=<ref>`),
    `PREVIEW_STYLE_PARAM` (`preview_style`), `LAYER_PARAM` (`layer=<key>`),
    `readVersionRef`, `useLayers` (warstwy produktu w obszarze: magazyn
    z filtra, inaczej pierwszy z produktem; śledzi zadanie `preview`
    wybranej warstwy i czyta warstwy od nowa po jego końcu — nowy `v`
    w adresach), `useLayerLegend` (legenda pierwszej gotowej wersji: klasy
    zawsze, rampa tylko przy warstwie jednej wersji), `layerTiles` (jedno
    źródło rastrowe warstwy, jej `minzoom`, `bounds` = suma granic wersji,
    bez źródła, gdy nic nie jest gotowe), `versionTiles`,
    `useVersionPreview` (`PreviewInfo` i karta wersji: obrys, slot),
    `useFeatures` (obiekty wektora w widoku po zatrzymaniu mapy, `zoom` =
    zoom kafli 256 px = zoom MapLibre + 1), `tilesShown`/`shownFrom`
    (MapLibre prosi o kafle zoomu `round(zoom + 1)`), komponenty
    `LayerButtons`, `LayerLegend`, `VersionLegend`, `ZoomHint`.
  - *Mapa* (`views/map.js`): przyciski lat w lewym górnym rogu (telefon:
    rząd nad mapą), najnowsze na górze, z pierścieniem pokrycia lokalnego;
    dwa warianty jednego roku z różnicą wariantu („1m · PL-EVRF2007-NH”,
    „bez metadanych”); drugie kliknięcie zdejmuje wybór. Wybrana warstwa:
    obrysy z `/map/footprints` (`versions=all`, rok warstwy) zawężone do
    `ref` jej wersji — wielokąty WGS84, bo `outlines` warstwy są w układzie
    płaskim; licznik i legenda mówią o warstwie; poniżej zoomu kafli
    „Przybliż, aby zobaczyć podgląd” z przyciskiem „Przybliż” (zoom mapy
    `minzoom − 1`). Nieznany `layer` znika z adresu; zmiana produktu
    i „Wyczyść” obszar zdejmują go. Podgląd wersji: kadr na granice (nie
    przy linku z położeniem), kafle w `bounds`/`minzoom`/`maxzoom`, obrys,
    wektor jako obiekty; w legendzie mapy sekcja „Podgląd pliku” (styl,
    `PreviewLegend`, powód, „Karta pliku”, „Zamknij podgląd pliku”).
    Rastry podglądów leżą nad wypełnieniem obrysów, pod ich liniami; błąd
    kafla podglądu daje notkę, a nie „Mapa nie działa”.
  - *Karta pliku*: „Pokaż podgląd na mapie” (link do mapy z `preview`,
    stylem i stanem mapy; karta się zamyka) przy `ready` z kaflami albo
    obiektami; `PreviewPane` przyjmuje `children` także jako funkcję
    `(info, styl) => akcje`.
  - *Poprawka v0.1*: miejsce kółka ładowania w licznikach jest stałe —
    pasek łamany przez kółko zmieniał wysokość mapy, ta ruch i zapytanie
    obrysów, bez końca (wykryte próbą e2e).
  - *Próby*: `tests/e2e/test_map_previews.py` (6 testów, jeden serwer na
    moduł z podkładem z drugiego pochodzenia, ok. 55 s, dwa przebiegi
    zielone): kafle wersji z nagłówkiem CSRF tylko w granicach i zoomach,
    styl i rampa, powrót do karty; przyciski lat, obrysy i kafle warstw;
    jedno źródło warstwy (jeden szablon, zero kafli wersji); poniżej
    `minzoom` brak kafli i podpowiedź, po „Przybliż” kafle `z = minzoom`;
    `layer` w adresie odtwarza widok, nieznany znika; bez naruszeń CSP,
    obiekty wektora z `zoom` mapy, nagłówek tylko do API, nigdy do
    podkładu. `test_map.py` nie uruchamiany (zasady szybkości). Zrzuty:
    `<katalog-danych>/v02-12b/smoke/`.

### 13a. Interfejs: przełącznik widoków i Wachlarz
- **Cel:** przełącznik „Mapa / Wachlarz / Katalog” nad środkiem (Katalog =
  ten sam stan co `view=catalog`); Wachlarz (`mode=fan`) jako komponent
  SVG z układem z mockupu (`mockup/src/fan.js`): miniatury warstw na łuku,
  najnowsza na górze, każda w całości we własnym miejscu, wybrana
  powiększona w łuku i duża obok, podpis: rok, „lokalnie N% obszaru”,
  wariant z plakietkami formatów, liczba kampanii, stan podglądu (A-ADR-018
  z erratą 1, SPEC 5.4, 6.5 c), obrysy arkuszy z `outlines` na miniaturze;
  wybór warstwy zsynchronizowany z mapą i adresem (`layer`); klawiatura
  (`Enter`, `Spacja`, strzałki) i ARIA Wachlarza; szerokie ekrany (≥ 2000
  px środka — Wachlarz obok mapy) i telefon.
- **Pliki:** `archiwista/web/src/fan/{layout,fan}.js`,
  `archiwista/web/src/views/map.js`, `archiwista/web/src/labels/{fan,map}.js`,
  `fan.css`.
- **Interfejs:** umowa WWW; `LayerSet` z kroku 11.
- **Test/odbiór:** `tests/e2e/test_fan.py`
  (`test_fan_newest_on_top_and_no_overlap`,
  `test_selected_layer_fully_visible_and_enlarged`,
  `test_fan_selection_syncs_map_and_url`, `test_fan_keyboard_selection`,
  `test_wide_3440_fan_beside_map`, `test_phone_390_fan`), zrzuty 1440,
  3440 i 390 px w raporcie.
- **Zależności:** 11, 12a, 12b. **Równolegle:** 14, 15, 16.
- **Stan po kroku 13a:**
  - *Przełącznik* (`views/switch.js`, nowy moduł — odstępstwo od listy
    plików: używają go mapa i Katalog): `Seg` „Mapa / Wachlarz / Katalog”
    (grupa „Widok środka”) w pasku mapy i Katalogu; Mapa ↔ Wachlarz to
    `mode=fan` w `view=map`, Katalog to `view=catalog` z całym adresem
    (filtry, obszar, `layer`, `group`, `layout`, położenie mapy), więc powrót
    odtwarza każdy widok. `SPLIT_MIN = 2000` px środka: Wachlarz obok mapy
    (dwie połowy), węższy — w miejscu mapy (mapa zostaje wczytana pod spodem,
    `visibility: hidden`). `hooks.js` dostał `useSize(element)`.
  - *Wachlarz* (`fan/layout.js`, `fan/fan.js`, `fan.css`, `labels/fan.js`):
    układ z mockupu jako czysta funkcja `fanLayout` (łuk o promieniu
    1,15 wysokości, slot każdej miniatury z obrotem ±0,09 rad, wybrana
    ×1,9, podpis w obrębie slotu, duży widok wybranej obok, gdy ma ≥ 220 px;
    przy wielu warstwach łuk rośnie i scena się przewija, wychylenie łuku
    zostaje z wysokości sceny; na wąskiej scenie podpisy 150–230 px
    i pokrycie jako procent). Miniatura to SVG: obraz warstwy z
    `thumbnail_url` (+`size` 128–1024 wg rozmiaru i `devicePixelRatio`,
    `blob:` przez `usePreviewImage`) pod obrysami arkuszy z `outlines`
    (gotowy podgląd — linia ciągła, brak — przerywana z wypełnieniem).
    Podpis: tytuł, „lokalnie N% obszaru”, wariant bez formatu
    (`variantName` w `map/previews.js`) z plakietkami formatów, liczba
    kampanii, stan podglądów; duży widok — notka stanu i postęp budowy.
    ARIA: `listbox` (pionowy) z `option` na podpisach, roving tabindex,
    strzałki/Home/End przenoszą fokus, Enter i Spacja wybierają; miniatury
    `aria-hidden`, ale klikalne. Przełącznik „Warstwy według lat/kampanii”
    (`group=campaign`, pokazywany, gdy warstwa ma ≥ 2 kampanie) zdejmuje
    `layer`.
  - *Wspólny hook* (`map/previews.js`): `useLayers` przyjmuje `group`
    i `needsArea: false` (Oś czasu bez obszaru) i śledzi zadanie wybranej
    warstwy, a bez niego — pierwszej budowanej (miniatury i lata odświeżają
    się po każdej budowie); `GROUP_PARAM`, `CAMPAIGN_GROUP`, `variantName`.
  - *Punkt rozszerzenia dla 15*: `Fan` przyjmuje dowolny `LayerSet` (także
    pliku własnego z `GET /projects/{p}/files/{id}/layers`, krok 9) i
    `heading` („Wachlarz migawek”); bez `group`/`missing`/`onPanel`.
    Podłączenie w karcie pliku własnego robi krok 15 (uzgodnione
    z V02Step15).
  - *Próby*: `tests/e2e/test_fan.py` (6 testów, jeden serwer offline na
    moduł nad magazynem `tests/fixtures/layer_store.py` przez nowy
    `tests/fixtures/layer_browser.py`, ok. 25 s): kolejność od najnowszej,
    brak nakładania (prostokąty miniatur po obrocie i podpisów) i całość na
    scenie, miniatury `blob:` z obrysami; wybrana ×1,9, cała, podpis z
    pięcioma faktami, duży widok; wybór = `layer` = przycisk lat mapy
    i z powrotem, Wstecz; klawiatura; 3440 px — mapa i Wachlarz obok
    siebie; 390 px — Wachlarz zamiast mapy, szczegóły jako arkusz; bez
    naruszeń CSP. Zrzuty: `<katalog-danych>/v02-13/shots/` (01, 02, 06, 08,
    11).

### 13b. Interfejs: Oś czasu, Szczegóły zestawu i wspólny wybór
- **Cel:** Oś czasu w Katalogu (`layout=timeline`): lata na osi poziomej
  z latami bez danych, wiersz = wariant (bez formatu plików, z plakietkami
  formatów — A-ADR-017), słupek = pokrycie lokalne obszaru albo — bez
  obszaru — liczba wersji (SPEC 6.5 b w wersji lokalnej); panel
  „Szczegóły zestawu” (SPEC 6.1: tylko wybrana warstwa — wersje, kampanie
  z datami, formaty, pokrycie lokalne, „Pokaż na mapie”, arkusze → Karta
  pliku; „Porównaj z…” dodaje krok 14; bez działań pobierania przed v0.3);
  jeden wybór zsynchronizowany w mapie, Wachlarzu (13a), Osi czasu, panelu
  i adresie; klawiatura i ARIA Osi czasu; szerokie ekrany (Katalog obok
  mapy) i telefon.
- **Pliki:** `archiwista/web/src/views/{catalog,catalog-timeline,set-details}.js`,
  `archiwista/web/src/labels/{timeline,catalog}.js`, `timeline.css`;
  w `views/map.js` i `fan/fan.js` tylko podłączenie panelu do wspólnego
  wyboru.
- **Interfejs:** umowa WWW; `LayerSet` z kroku 11; wybór z kroku 13a.
- **Test/odbiór:** `tests/e2e/test_timeline.py`
  (`test_timeline_shows_years_without_data`,
  `test_timeline_bar_height_is_local_coverage`,
  `test_two_formats_one_timeline_row`,
  `test_selection_syncs_map_fan_timeline_panel_and_url`,
  `test_timeline_keyboard_selection`, `test_wide_3440_catalog_beside_map`,
  `test_phone_390_timeline_and_panel`), zrzuty w raporcie.
- **Zależności:** 13a. **Równolegle:** 14, 15, 16.
- **Stan po kroku 13b:**
  - *Oś czasu* (`views/catalog-timeline.js`, `timeline.css`,
    `labels/timeline.js`): siatka ARIA (`grid`, nagłówki kolumn i wierszy)
    w HTML/CSS, nie SVG — dostępność i przewijanie w poziomie z przyklejonym
    nagłówkiem wiersza; kolumny: lata od najstarszego do najnowszego z latami
    bez danych (kropka, „brak danych”), przy `group=campaign` kolumna na
    kampanię roku, na końcu wydania i etykiety bez roku; wiersz = część
    wariantu klucza warstwy, plakietki = suma formatów wiersza; słupek =
    `coverage.ratio` (z obszarem) albo `versions_count` / największa liczba
    (bez obszaru), wartość pod słupkiem. Magazyn: z adresu, inaczej pierwszy
    z produktem (`productStores`). Klawiatura: roving tabindex, strzałki
    między komórkami z danymi (góra/dół — najbliższa kolumna), Home/End,
    Ctrl+Home/End, Enter i Spacja wybierają. Nieznany `layer` znika
    z adresu.
  - *Katalog* (`views/catalog.js`, `labels/catalog.js`, `catalog.css`):
    wiersz przełącznika i układu „Lista / Oś czasu” (`layout=timeline`);
    w Osi czasu bez pola wyszukiwania (Ctrl+K wraca do listy), `/slots` nie
    jest pytane (`usePages` z `enabled`); przy ≥ 2000 px środka mapa obok
    Katalogu — `views/map.js` w trybie `embedded` (sam środek mapy, bez
    paneli i przełącznika), ładowany dynamicznie.
  - *Szczegóły zestawu* (`views/set-details.js`, `set-details.css`,
    `labels/set-details.js`; style i teksty poza listą planu): prawy panel
    `ViewLayout` tylko z wybraną warstwą — tytuł, wariant (`Tech`: klucz,
    segmenty), pokrycie, formaty, wersje i jednostki, kampanie, daty danych
    (powiązanie kampania → daty daje `group=campaign`; API nie łączy ich per
    wersja), podglądy z postępem budowy, magazyn; „Pokaż na mapie”, gdy mapy
    nie widać; „Porównaj z…” — lista pozostałych warstw obszaru jako link
    `view=compare` (`store`, `product`, `area_id`, `group`, `a_layer`,
    `b_layer`; uzgodnione z krokiem 14); poza Katalogiem „Inne warianty”
    roku; arkusze → Karta pliku (`FileLink`). Przycisk „Szczegóły” w pasku.
    Panel otwiera się sam obok Wachlarza i Osi czasu (komputer), nad mapą —
    na żądanie (wybór roku nie zwęża mapy pod kursorem), wybór użytkownika
    się utrzymuje; na telefonie arkusz od dołu, zamyka panel „Wybór”.
  - *Próby*: `tests/e2e/test_timeline.py` (7 testów, ok. 22 s): lata
    2019–2023 z trzema bez danych i etykieta wycinka, każda warstwa jedną
    komórką; wysokość słupka = `coverage.ratio` (±1 px), bez obszaru =
    wersje / największa; dwa formaty — jeden wiersz, jedna komórka, panel
    liczy arkusz raz; jeden wybór: Oś czasu → panel → Wachlarz → mapa →
    Katalog (`layout` wraca), arkusz otwiera Kartę pliku, „Pokaż na mapie”;
    klawiatura; 3440 px — mapa obok Katalogu; 390 px — przewijanie w ramce,
    panel jako arkusz; bez naruszeń CSP. Zrzuty: `<katalog-danych>/v02-13/
    shots/` (03–05, 07, 09, 10, 12).

### 14. Interfejs: Porównanie i kurtyna
- **Cel:** widok `compare` (decyzja 10): tabela różnic z przełącznikiem
  „tylko różnice” i eksportem CSV po stronie przeglądarki; mapa
  porównania — kurtyna (domyślnie; uchwyt przeciągany myszą, dotykiem
  i strzałkami), przenikanie (suwak), dwa widoki obok siebie
  zsynchronizowane; strony: `ref` (wersja, plik roboczy, migawka) albo
  warstwa lat (`a_layer`, `b_layer` z `/local-layers`); wejścia: „Porównaj
  z…” w Karcie pliku (wybór innej wersji slotu) i — po kroku 13b —
  w panelu „Szczegóły zestawu” (druga warstwa lat).
- **Pliki:** `archiwista/web/src/views/compare.js`,
  `archiwista/web/src/map/compare.js`, `archiwista/web/src/views/file.js`,
  `archiwista/web/src/views/set-details.js` (po kroku 13b),
  `archiwista/web/src/routes.js` (jedna linia),
  `archiwista/web/src/labels/compare.js`, `compare.css`.
- **Interfejs:** umowa WWW; `Comparison` (10), `PreviewInfo` (6),
  `LayerSet` (11).
- **Test/odbiór:** `tests/e2e/test_compare.py`
  (`test_metadata_table_marks_differences`,
  `test_curtain_drag_reveals_b`, `test_fade_slider_changes_opacity`,
  `test_side_by_side_maps_stay_in_sync`, `test_two_year_layers_compared`,
  `test_csv_export_matches_table`, `test_no_csp_violations_compare`).
- **Zależności:** 10, 12b. **Równolegle:** 13a, 13b, 15, 16.
- **Stan po kroku 14 (strony: wersje magazynu i warstwy lat; dane własne —
  punkt rozszerzenia dla kroku 15; wejście z „Szczegółów zestawu” — krok
  13b):**
  - *Widok* `compare` (`views/compare.js`): linia w `VIEWS` z `nav: false`
    — widok spoza nawigacji, otwierany przez „Porównaj z…” (decyzja 14;
    `shell.js` pomija takie widoki w nawigacji, `labels/shell.js` daje
    nazwę do tytułu strony). Adres: `a`/`b` (`ref` z odpowiedzi) albo
    `store`, `product`, `area_id`, `group` z `a_layer`/`b_layer`; `mode`
    (`fade`, `side`, kurtyna bez parametru), `style`, `only_diff=1`,
    `center`/`zoom`; bez obu stron — opis, skąd otworzyć porównanie.
    Prawy panel „Szczegóły porównania” (`ViewLayout`, na telefonie
    arkusz): strony A i B (tytuł, rodzaj, `ref` pod „Tech”, stan podglądu
    na mapie, powód, budowa przez wspólne `useBuild`/`BuildSection`
    z `previews.js`, „Karta pliku” nad porównaniem), potem tabela.
    „Zamień A i B” w pasku nad mapą.
  - *Tabela*: wiersze `/compare` w grupach (nazwy także dla `own`
    i `layers`), różnica tłem i znakiem ≠ (z tekstem dla czytników ekranu),
    „Różne pola: N z M”, notka przy `same_content`; daty, rozmiar, układy
    i udział dla ludzi z surową wartością pod „Tech”, pola sidecara bez
    interpretacji. „Eksportuj CSV” w przeglądarce: wiersze widoczne w tabeli
    (także z „tylko różnice”), UTF-8 z BOM, przecinek, CRLF, surowe
    wartości (ISO, kropka, tak/nie), nagłówek z tytułami A i B, apostrof
    przed tekstem zaczynającym się jak formuła arkusza, nazwa
    `porownanie-<A>-<B>.csv`. Dwie warstwy lat: podsumowania obok siebie
    jako te same wiersze liczone w przeglądarce (rok, wariant, daty,
    kampanie, wersje, arkusze, pokrycie lokalne, układy, rozdzielczość,
    formaty, segmenty, gotowe podglądy, klucz) — bez `/compare`; wybór
    innej warstwy A albo B z tego samego zestawu; zadania budowy obu warstw
    śledzone, warstwy czytane od nowa po ich końcu.
  - *Mapa* (`map/compare.js`): dwie mapy MapLibre z jednym położeniem (ruch
    jednej kopiowany do drugiej przez `jumpTo`, bez sprzężenia zwrotnego),
    `transformRequest` z `apiHeaders` jak w `canvas.js`. Kurtyna: B nad A
    przycięta `clip-path: inset(0 0 0 var(--split))` z właściwości
    ustawianej z JS (CSSOM); uchwyt `role="slider"` — mysz i dotyk przez
    zdarzenia wskaźnika, strzałki (z Shift co 10), PageUp/PageDown,
    Home/End; gdzie B jest odcięta, wskaźnik trafia do A. Przenikanie:
    przezroczystość płótna B (`--fade`) suwakiem na mapie, przyciski B
    zostają nieprzezroczyste. Obok siebie: dwie mapy jednej wielkości
    (telefon: jedna nad drugą). Te same przyciski mapy w tym samym miejscu
    obu map — klika się wierzchnią. Plakietki A i B, legenda (wspólna skala
    barw, obrysy, obiekty wektora), „Przybliż, aby zobaczyć podgląd” poniżej
    `minzoom`, notka o stronie bez podglądu; kadr na obie strony raz na
    parę (nie przy linku z położeniem). Wspólny styl stron (`style`),
    a w rampie (hipsometria) wspólny `rescale`: od mniejszego minimum do
    większego maksimum legend obu stron — te same barwy to te same
    wartości. Podgląd strony z adresu `ComparisonSide.preview`
    (`getLinked`), budowa w progach automatycznie przez `POST` na ten sam
    adres (`buildLinked`).
  - *Karta pliku*: „Porównaj z…” obok tytułu wersji — lista pozostałych
    wersji slotu, starsza jako A (porównanie czyta się jako zmiana A → B).
  - *Klient API i typy*: `getComparison`, `buildLinked` (`api.js`),
    `Comparison`, `ComparisonSide`, `ComparisonRow` (`types.js`).
  - *Punkt rozszerzenia dla danych własnych (krok 15).* Widok przyjmuje
    każdy `ref`: od kroku 9 (`dcbb454`) `/compare` porównuje `file:`
    i `snapshot:` i podaje ich `preview`, więc tabela i mapa (podgląd,
    budowa) działają bez zmian. Krok 15 dopisuje w `views/compare.js`:
    w `RefSide` przejście do nakładki `own=` dla stron `file`/`snapshot`
    (dziś „Karta pliku” tylko dla wersji, przez `useVersionCard`), sekcję
    `schema_diff` pod tabelą (warstwy tylko w A albo B, liczby obiektów,
    pola dodane, usunięte i zmienione), a w karcie pliku własnego
    „Porównaj z…” (migawka z plikiem roboczym;
    `test_compare_snapshot_with_current`).
  - *Wejście z „Szczegółów zestawu” (13b)*: link `view=compare` z `store`,
    `product`, `area_id`, `group` (tylko `campaign`), `a_layer`, `b_layer`
    — dopisuje go krok 13b w `views/set-details.js` (uzgodnione z jego
    wykonawcą).
  - *Odstępstwa od listy plików*: `shell.js` (jedna linia), `labels/shell.js`,
    `labels/file.js` i `views/cards.css` („Porównaj z…”), `api.js`,
    `types.js`, `previews.js` (eksport `useBuild` i `BuildSection`); arkusz
    stylów to `views/compare.css` (widok ładuje też `map/map.css`).
  - *Próby*: `tests/e2e/test_compare.py` (7 testów, jeden serwer na moduł
    z podkładem z drugiego pochodzenia, ok. 52 s): tabela = wiersze
    `/compare` z oznaczeniem różnic, „tylko różnice” w adresie, zamiana
    stron; kurtyna myszą, strzałkami, dotykiem (`Input.dispatchTouchEvent`)
    i Home/End z `clip-path` B, kafle obu stron z nagłówkiem CSRF;
    przenikanie: przezroczystość płótna B = suwak, powrót do kurtyny; obok
    siebie: przybliżenie A — B pobiera te same kafle następnego zoomu,
    przeciągnięcie i oddalenie B — A pobiera te same kafle; dwie warstwy
    lat: kafle `/local-layers/tiles` obu kluczy, zero kafli wersji, wiersze
    warstw, inna warstwa B, zamiana; CSV = wiersze tabeli z surowymi
    wartościami `/compare`; bez naruszeń CSP we wszystkich trybach,
    hipsometria ze wspólnym `rescale`, karta pliku nad porównaniem,
    nagłówek tylko do API. Zrzuty (1440 i 390 px):
    `<katalog-danych>/v02-14/shots/`.

### 15. Interfejs: dane własne i migawki
- **Cel:** w widoku projektu grupa „Dane własne” obok zadań producentów
  (folder i jego stan, liczba plików, zajętość, zajętość migawek, lista
  plików ze stanem zmiany, „Odśwież” → `own_scan` projektu z postępem, dla
  administratora „Zmień folder danych…”); nakładka `own=` (karta pliku
  własnego: metadane, warstwy i schemat, zasięg, oś wersji — plik roboczy
  i migawki, „zmieniony od migawki z …”, historia stanów, podgląd,
  „Pokaż na mapie”, „Porównaj z migawką…”, „Wachlarz migawek” z kroku 13a
  na `LayerSet` pliku); „Zrób migawkę…” jako „Okno planu” (SPEC 6.1: plik,
  rozmiar, miejsce, metoda kopii, „tylko przyrost”, informacja „bez zmian
  od migawki z …”, pole opisu, „Anuluj” / „Zrób migawkę”) → zadanie
  z postępem → nowa migawka na osi; mapa w kontekście projektu
  (`project=`): warstwa „Dane własne” (zasięgi plików, obiekty albo kafle
  wybranego) i obrysy wersji przypiętych w projekcie.
- **Pliki:** `archiwista/web/src/views/{projects,own}.js`,
  `archiwista/web/src/map/{own,canvas}.js`, `archiwista/web/src/views/map.js`
  (jedna linia rejestracji warstwy — w tej fali `map.js` zmienia krok 13a),
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
- **Zależności:** 9, 12a; Wachlarz migawek po 13a, „Porównaj” po 14.
  **Równolegle:** 13a, 13b, 14, 16.
- **Stan po kroku 15:**
  - *Widok projektu* (`views/projects.js`, teksty `labels/projects.js`
    `own`): grupa „Dane własne” pod zadaniami producenta — folder (ścieżka
    do skopiowania, źródło: domyślny `dane/` albo ustawienie), stan, pliki
    i zajętość, zajętość migawek, czas skanu, problemy folderu; lista plików
    (do 200 na stronę, „Pokaż więcej”) ze stanem i zmianą od migawki
    prowadząca do karty pliku; „Odśwież” → `POST /projects/{p}/scan`
    z postępem i podsumowaniem `own_scan`; „Pokaż na mapie” → mapa
    z `project` i `versions=pinned`; „Zmień folder danych…” (`PUT
    …/data-dir`, potem śledzenie skanu nowego folderu, „Przywróć domyślny
    folder dane/”) tylko dla sesji właściciela lokalnego (`actor` =
    `local`, A-ADR-029) — sesja nie podaje ról, więc konto z rolą `admin`
    w trybie zespołu (v0.4) zobaczy akcję dopiero, gdy `SessionState` dostanie
    role; serwer i tak odmawia innym (`403`).
  - *Karta pliku własnego* (`views/own.js`, nakładka `own=<projekt>/<file_id>`
    jedną linią w `OVERLAYS`; parametry `own_version` — etykieta migawki,
    `own_tab=preview`, `own_style`, `own_fan=1`, znikają z kartą): nagłówek
    (ścieżka, projekt, format, rozmiar, liczba migawek, „zmieniony od migawki
    z …”/„bez zmian…”/„bez migawki”, stan), problemy, oś wersji (plik
    roboczy, migawki od najnowszej z datą, etykietą, obiektami, opisem),
    zakładki „Metadane” (format, układ — WKT pod „Tech”, zasięg, położenie,
    tożsamość treści, obiekty, warstwy z typem geometrii i polami, raster,
    ścieżki do skopiowania, historia stanów; migawki: autor, opis, stan,
    katalog) i „Podgląd” (`PreviewPane` z `getOwnPreview`/`buildOwnPreview`,
    klucz z treścią pliku roboczego). Akcje: „Zrób migawkę…” — „Okno planu”
    jako `<dialog>` modalny (plik, rozmiar, dokąd z kopiowaniem, metoda kopii
    i treści, wolne miejsce, „tylko przyrost”, „bez zmian od migawki z …”,
    ostrzeżenia, blokada; opis ≤ 2000 znaków; „Anuluj”/„Zrób migawkę”;
    Esc zamyka tylko okno) → zadanie `snapshot` z etapami → podsumowanie
    i nowa migawka na osi; „Porównaj z migawką…” (starsza jako A);
    „Pokaż na mapie”; „Wachlarz migawek” (`Fan` z kroku 13a na `LayerSet`
    pliku, wybór wspólny z osią); „Odśwież dane własne projektu” przy
    `changed_since_scan`.
  - *Mapa w kontekście projektu* (`map/own.js`, `map/canvas.js`,
    `views/map.js`): `project` w filtrach mapy (obrysy wersji przypiętych
    przez `/map/footprints?project=`, plakietka „projekt: …”), warstwa
    „Dane własne” — zasięgi plików (wszystkie strony listy, do 5000) nad
    obrysami, podpowiedź ze zmianą od migawki, klik (także z listy wyboru
    obok obrysów magazynu) otwiera kartę i pokazuje obiekty albo kafle pliku
    (`preview=<ref>`); sekcja legendy z liczbą zasięgów, plikami bez
    położenia, „Pokaż wszystkie” i przejściem do projektu; kadr projektu
    łączy obrysy przypięć i zasięgi. `useVersionPreview` przyjmuje `file:`
    i `snapshot:` (`file_id` z listy plików po ścieżce, `findOwnFile`),
    zwraca `outline` (obrys wersji, zasięg pliku albo prostokąt migawki);
    legenda podglądu prowadzi do karty pliku własnego. Poprawka pojedynczego
    punktu: widok proszony o `…/features` jest poszerzany (`widenBounds`,
    ≥ 0,00002°), a kadr obiektu bez pola — do 0,003°.
  - *Porównanie* (`views/compare.js`): „Karta pliku” stron `file`/`snapshot`
    (nakładka `own=` na wersji strony), sekcja „Różnice schematu” pod tabelą
    (`schema_diff`: warstwy tylko w A/B, obiekty, pola dodane, usunięte
    i o zmienionym typie).
  - *API i typy*: funkcje danych własnych w `api.js` (`listOwnFiles`,
    `startProjectScan`, `putDataDir`, `getOwnFile`, `getOwnFileLayers`,
    `getSnapshotPlan`, `startFileSnapshot`, `getOwnPreview`,
    `buildOwnPreview`), modele w `types.js` oraz pola zadań (`own_scan`,
    `snapshot`, `JobFailure.reason`, `JobFilters.project`, `store` null,
    `Health.own_data`); nazwy rodzajów zadań w `labels/common.js`, postęp
    etapów migawki i skanu oraz podsumowanie `own_scan` w `views/cards.js`.
  - *Odstępstwo od umowy API*: `OwnFileItem.outline` (wielokąt WGS84 zasięgu
    z indeksu, `OwnFileRow.outline`) — mapa projektu rysuje zasięgi bez karty
    każdego pliku; próba w `test_folder_with_gpkg_shp_geotiff_indexed_with_extent_and_preview`.
    Poza listą plików: `map/geo.js` (`widenBounds`), `views/cards.js`,
    `labels/{cards,common,compare}.js`, `views/compare.css`, `api.js`,
    `types.js`; arkusz stylów `views/own.css` ładuje `map/own.js`.
  - *Próby*: `tests/e2e/test_own_data.py` (8 testów planu, jeden serwer na
    moduł, offline); zrzuty w `<katalog-danych>/v02-15/`.

### 16. Wydajność i pomiary (z płynnością mapy na GPU)
- **Cel:** zmierzyć cele SPEC 4.5 (regresja z obrysami-wielokątami) i cele
  planu (decyzja 12) na komputerze odniesienia; pomiar płynności mapy
  z WebGL sprzętowym (decyzja 1): uruchomienie Chromium z flagami GPU
  albo przez CDP, sprawdzenie renderera (`WEBGL_debug_renderer_info`),
  tryb bramki `ARCHIWISTA_REQUIRE_GPU=1` (WebGL programowy → błąd zamiast
  pominięcia), przesuwanie jak w v0.1 (rysowanie ramek przez
  `requestAnimationFrame`) przy 4500–5000 obrysach — także z podglądem
  roku włączonym (informacyjnie); widok roku z 200 arkuszy z kafli warstwy
  w pamięci; budowa COG z `n` procesami (arkusz SM5 JPEG, rok ASC, rok
  ortofoto CZ); pomiar SMB dla pierwszego kafla i COG z magazynu na
  udziale; pamięć serwera i procesów renderujących.
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
- **Zależności:** 3, 6, 7b, 8, 11, 12b. **Równolegle:** 13a–15, 17.
- **Stan po kroku 16:**
  - *Harness:* `tests/fixtures/perf_server.py` (wspólny `archiwista serve`
    jako proces, sesja agenta, próbki pamięci — wydzielone z
    `test_store_50k.py`), `tests/fixtures/browser.py` (`gpu_browser` z flagami
    GPU albo CDP, `webgl_renderer`, `require_hardware_gl` z
    `ARCHIWISTA_REQUIRE_GPU=1`, `pan_frames`), `tests/fixtures/preview_store.py`
    (odstępstwo: nowy generator fixtur podglądów z prawdziwych plików żywego
    magazynu Kartografa, `python -m tests.fixtures.preview_store`; katalog
    `previews-perf/` obok magazynu 50k — bez nowej zmiennej),
    `tests/perf/test_previews_perf.py`, `tests/perf/test_own_data_perf.py`,
    w `test_store_50k.py` `/local-layers` obszaru 492 slotów, bramka GPU,
    podgląd roku przy przesuwaniu, pamięć procesów renderujących i budowy.
  - *Wyniki SSD* (raport, sekcje 2–3): wszystkie cele decyzji 12 spełnione
    poza płynnością mapy (tylko WebGL programowy: 8,4 klatek/s przy 4532
    obrysach — kryterium 5 niezweryfikowane); `/local-layers` na granicy
    (902–1052 ms); regresja SPEC 4.5 w progach (pełny skan 64,8 s).
  - *Poprawka:* `renderers/raster.py` `_paint_within` — miniatura w kadrze
    warstwy malowana tylko w oknie z wartościami (te same piksele); miniatura
    warstwy 35 arkuszy ASC p95 2,61 → 1,31 s.
  - *Wyniki SMB* (raport, sekcja 5): wszystkie cele kolumny SMB decyzji 12
    i regresja SPEC 4.5 spełnione (pełny skan 247,3 s, przyrostowy 101,1 s,
    `/local-layers` p95 2,26 s, rok SM5 212,5 s); mapa 4964 obrysów p95
    295 ms na granicy (indeks lokalny, obciążenie). Test migawki zmienia
    wiersz GeoPackage z `nolock=1` (zapis SQLite na udziale `nounix` kończy
    się `database is locked`).
  - *Otwarte:* pomiar z GPU, test płynności z przeglądarką z flagami GPU
    (llvmpipe) bez żądania obrysów mapy 50k — do diagnozy przy pomiarze
    z GPU; arkusz SM5 125 Mpx decyzji 12 wobec 320 Mpx prawdziwych arkuszy
    (6,9 s) — do opisu w SPEC 4.5 w kroku 18.

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
- **Stan po kroku 17:**
  - *Kod i próba odbiorcza:* sesje i uprawnienia (commit `4c4bd0c`),
    komunikaty podglądów (`263c421`), przejście e2e i test na żywo
    (`c490593`), odłączony udział (`3832ce2`), korekty prób po zmianie
    położenia fixtur PL/CZ i zrzuty (`53fcd9d`). Prawdziwy
    `archiwista serve` z Playwright przeszedł kartę pliku, mapę roku,
    Wachlarz, Oś czasu, porównanie z kurtyną, folder projektu i migawki;
    osobne próby magazynu tylko do odczytu i odłączonego udziału też
    przeszły. Zrzuty po kontroli prywatności:
    `docs/reports/v0.2-screenshots/`.
  - *Test na żywo:* `-m live tests/integration/test_live_previews.py
    --no-cov -s` na `<udział>/kartograf/release-0.8.0/data`,
    `<udział>/kartograf/release-0.8.0-final/data` oraz
    `<udział>/kartograf/release-0.8.0-final/verify/data`: każdy przebieg
    zaliczony; łącznie 44 wersje (41 gotowych, w tym 6 budów na żądanie;
    3 pomocnicze `jgw` z opisanym powodem). Tabela rozszerzenie → wynik
    w raporcie, sekcja 10; magazyny pozostały niezmienione.
  - *Pełna bramka:* `ruff check .` — zaliczony; `ruff format --check .` —
    255 plików; `mypy` — 250 plików, 0 problemów; pierwszy `pytest` —
    1045 zaliczonych, 4 niezaliczone; po poprawie oczekiwań czterech
    prób wobec geografii fixtur (bez zmiany algorytmu produktu) ponowiono
    tylko te próby — 4 zaliczone; końcowy `pytest` — **1049 zaliczonych,
    0 niezaliczonych, 91,71% pokrycia**. Szczegóły: raport, sekcja 11.
  - *Odstępstwa i otwarte:* test otwartego GPKG odtwarza pracę edytora
    przez WAL i `integrity_check`, ale QGIS nie jest zainstalowany —
    ręczna próba u użytkownika zalecana. Mapa przy 5000 obrysach
    i ≥ 30 klatek/s pozostaje **niezweryfikowana — brak dostępu do GPU**;
    tryb pomiaru opisano w raporcie, sekcje 4, 8 i 9. Bez wyniku
    sprzętowego nie zamykać kryterium 5 bramki wydania.

### 18. Dokumentacja, bramka i wydanie 0.2.0
- **Cel:** `README.md` (zależności podglądów, folder danych, migawki,
  pamięć podglądów, instalacja Kartografa z `develop` zamiast usuniętej
  gałęzi), `docs/CHANGELOG.md` (`[0.2.0]`, w tym przebudowa
  indeksu po aktualizacji przez nową wersję schematu i pełny skan przy
  starcie), `docs/USAGE.md` (Wachlarz, Oś czasu, Porównanie, dane własne
  i migawki ze zrzutami), `docs/AGENT_API.md` (`ref`, podglądy z CSRF,
  `preview --output`, porównanie, warstwy z `--thumbnail`, dane własne,
  `own-scan`, plan i migawka, kody błędów), `docs/ARCHITECTURE.md` (nowe
  moduły, procesy, dane lokalne, przepływy, bezpieczeństwo, punkty
  rozszerzeń; sekcja 7 — widoczność zadań z danymi projektu zamiast „trasy
  zadań nie filtrują projektów”), SPEC (4.5 — wiersze v0.2; 4.7.1 — nazwy,
  schemat, problem w projekcie zamiast „Magazynu”, folder danych
  ustawiany przez administratora, sprawdzanie folderu domyślnego, trzy
  stany SQLite; 5.1 — renderowanie poza serwerem; 5.7 — tabela z decyzji
  5; 9.2 — nowe trasy; 10.1 — sandbox (jawne sterowniki, `EMPTY_DIR`,
  `GDAL_PAM_ENABLED=NO`) i dostarczanie podglądów; 13 — bramka v0.2),
  `docs/DECISIONS.md` (erraty: A-ADR-008 — procesy renderujące, wymuszona
  operacja w kaflach, kafel warstwy składany z kafli wersji, dostarczanie
  przez API; A-ADR-027 — nazwy i `archiwista-snapshot/1`; A-ADR-029 —
  `project.write`; erraty zapisane przy przeglądzie planu — A-ADR-008
  errata 3 i A-ADR-029 errata 1 — poprawiane tylko wtedy, gdy wykonanie od
  nich odeszło), `docs/SCOPE.md` (bramka etapu 3), `docs/PROGRESS.md`;
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
- **Stan po kroku 18 (wydanie 0.2.0, 2026-10-20):**
  - Wersja pakietu i przykładu `/health` podniesiona do 0.2.0; dokumenty
    `README`, CHANGELOG, USAGE, AGENT_API, ARCHITECTURE, SPEC, DECISIONS,
    SCOPE i PROGRESS oraz raport pomiarowy uaktualnione. Przykładowy
    magazyn `store2` i dane własne czterech rodzin wygenerowano poza repo;
    świeży lokalny indeks odtworzono dla tego magazynu.
  - `ruff check .` — zaliczony po poprawkach stylistycznych;
    `ruff format --check .` — 256 plików; `mypy archiwista/ tests/` —
    251 plików, bez problemów; `pip-audit` na `requirements.lock` —
    brak znanych podatności.
  - Domyślny `pytest`: 1064 zaliczone, 2 niezaliczone, 47 odfiltrowanych,
    2 ostrzeżenia, 91,75% pokrycia. Powtórzono **tylko** 2 niezaliczone
    scenariusze po dostosowaniu prób do nowych kluczy pamięci i sprawdzania
    zawartości plików własnych — obie zaliczone. Nie wykonano ponownie
    całego przebiegu; nie jest to jeden zielony pełny przebieg (raport,
    sekcja 13).
  - `archiwista serve` uruchomiony i obejrzany w przeglądarce: mapa,
    Wachlarz NMT, projekt i 4 pliki własne. Dostawca podkładu nie był
    testowany, bo przeglądarka miała dostęp tylko do localhost.
    Kryterium ≥ 30 klatek/s z GPU nadal niezweryfikowane. Bez tagu
    ani scalenia do `main`; następny krok to spec i plan v0.3.

## Bramka SPEC 13 v0.2: dowód dla każdego kryterium

| Kryterium SPEC 13 v0.2 | Dowód wymagany przed zamknięciem v0.2 (krok-właściciel) |
|---|---|
| 1. Każdy typ pliku przykładowego magazynu ma podgląd albo podany powód braku | `tests/integration/test_preview_coverage.py::test_every_store_file_type_has_preview_or_reason` (6; magazyn testowy z rodzinami kroku 2, także z wersją bez `sha256` w sidecarze: każda wersja ma `PreviewInfo` w stanie `ready` z dekodowalną miniaturą albo `unavailable`/`needs_build` ze znanym kodem `reason` i polskim opisem; po `POST …/preview` każde `needs_build` ≤ 2 GB kończy się `ready`), `tests/integration/test_live_previews.py::test_live_store_file_types_have_preview_or_reason` (17; `-m live` na magazynach testu na żywo Kartografa 0.8.0; tabela rozszerzenie → wynik w raporcie: `tif`, `gpkg`, `jgw`, `asc`, `zip`, `png`, `laz`, `jpg`) i `tests/integration/test_own_data_api.py::test_own_file_types_have_preview_or_reason` (9; dane własne). |
| 2. Obrysy CZ zgodne z rzeczywistością (punkt kontrolny na styku PL/CZ, odchyłka ≤ 2 m) | `tests/integration/test_cz_control_point.py` z punktem 3722 (decyzja 4): `::test_cz_outline_vertex_within_2_m` (3; wierzchołek obrysu w `/map/footprints`), `::test_cz_preview_tile_within_2_m` (5a1 — GeoTIFF, 5a2 — JPEG z georeferencją z obrysu nagłówkowego przez lokalny COG; kafel z = 19), `::test_cz_features_within_2_m` (5b; obiekt w `features`); odchyłki zapisane w raporcie. |
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
| Wachlarz i Oś czasu dla danych lokalnych | `tests/integration/test_local_layers.py` (11: warianty bez formatu plików, kafle warstw) i `tests/e2e/test_fan.py` (13a: najnowsza na górze, miniatury bez nakładania, wybrana w całości i powiększona, 1440, 3440 i 390 px) oraz `tests/e2e/test_timeline.py` (13b: lata bez danych, słupek = pokrycie lokalne, wybór zsynchronizowany w mapie, Wachlarzu, Osi czasu, panelu i adresie). |
| Porównanie metadanych i kurtyna (8.5, poziomy 1 i 2) | `tests/integration/test_compare.py` (10) i `tests/e2e/test_compare.py` (14: tabela różnic, kurtyna, przenikanie, widoki obok siebie, dwie warstwy lat). |
| Uprawnienia danych własnych i migawek | `tests/unit/test_authorize.py::test_project_write_matrix` i `tests/integration/test_permissions_api.py::test_own_data_visibility_matrix` (9; także trasy zadań `/jobs`, `/jobs/{id}`, `/jobs/{id}/events` dla zadań `snapshot`, `preview` z `file:` i `own_scan` projektu). |
| Agent: HTTP = CLI | `tests/integration/test_cli.py::test_preview_cli_equals_http`, `::test_own_data_cli_equals_http` (z `own-scan`), `::test_compare_cli_equals_http`, `::test_layers_cli_equals_http` (z `--thumbnail`) (6, 9–11) i `tests/integration/test_agent_flow.py::test_agent_snapshot_flow` (9). |
| Bezpieczeństwo podglądów i odczytu danych własnych | `tests/contract/test_preview_stack.py` (1: VRT po `WarpedVRT`, nakładka `.ovr` z treścią VRT, `.aux.xml`, trzy stany SQLite), `tests/unit/test_sandbox.py` (1), `tests/integration/test_render_pool.py::test_worker_env_has_no_network`, `::test_vrt_refused_after_warpedvrt_in_same_worker`, `::test_timeout_kills_and_respawns_worker`, `::test_memory_limit_kills_worker` (4), `tests/integration/test_preview_security.py` (6 i 9: m.in. `::test_server_process_never_opens_data_files`, `::test_store_and_own_folder_unchanged_after_previews`, `::test_failure_message_carries_no_other_projects_path`) i `tests/integration/test_own_reader.py::test_data_folder_unchanged_after_reads` (7a: trzy stany SQLite). |
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
- **Spójny odczyt SQLite.** `mode=ro` tworzy `-wal` i `-shm` obok bazy
  w trybie WAL bez `-wal` oraz `-shm` przy `-wal` bez `-shm`, `immutable=1`
  gubi wiersze z WAL, a GDAL w trybie odczytu przepisał WAL do pliku
  głównego (sprawdzone 2026-10-19); do tego blokady SQLite na udziale SMB
  i różnice zachowania QGIS. Ograniczenia: macierz trzech stanów
  (decyzja 8) w jednym miejscu (`consistent_sqlite_read`), GDAL nigdy
  w miejscu przy pliku `-wal`, kopia zapasowa do pliku lokalnego, stan
  przed i po, `PRAGMA integrity_check`, próba w kroku 1. QGIS nie jest
  zainstalowany na komputerze odniesienia: test odtwarza zapis QGIS (WAL,
  otwarta transakcja, awaria bez `-shm`); ręczna próba w QGIS — zalecana
  przy odbiorze u użytkownika.
- **Koszt skrótu logicznego.** Odczyt wszystkich wierszy dużego
  GeoPackage przy każdej zmianie (skan, migawka). Ograniczenia: tylko pliki
  zmienione (stan pliku i `-wal`), skrót migawki liczony na jej kopii,
  pomiar w kroku 16 (cel: migawka 100 MB ≤ 15 s).
- **Wyciek przez nowe powierzchnie.** Dane własne w podglądach,
  porównaniu, warstwach, zadaniach (`snapshot` z opisem, `preview`
  z `file:`), komunikatach bibliotek ze ścieżkami, filtrze `project` i CLI.
  Ograniczenia: jeden punkt przejścia `ref` → plik (`ObjectResolver`),
  zapytania z wymaganym `visible`, trasy zadań z widocznością (umowa
  „Zadania”), dane własne poza `/slots` i `/map/footprints`, pamięć
  podglądów bez nazw i ścieżek (komunikaty bez ścieżek, `unreadable`
  w pamięci jako sam kod), macierz widoczności rozszerzona o każdą nową
  trasę i o trasy zadań (krok 9).
- **GDAL na niezaufanym wejściu.** Pliki użytkownika mogą zawieszać albo
  wywracać biblioteki natywne, odsyłać do innych plików (VRT, nakładka
  `.ovr` z treścią VRT, tabela MapInfo łączona), zapisywać obok siebie
  (`.aux.xml`) i być małe na dysku, a ogromne po rozpakowaniu. `GDAL_SKIP`
  sam nie wystarcza — `WarpedVRT` przywraca sterownik VRT (sprawdzone).
  Ograniczenia: jawny sterownik pliku głównego i
  `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` (decyzja 3), `GDAL_PAM_ENABLED=NO`,
  `GDAL_SKIP` jako druga linia, procesy z sandboxem, limity czasu
  i pamięci, progi pikseli i wpisów ZIP przed odczytem, brak sieci, testy
  z uszkodzonymi i podstawionymi plikami; serwer nie otwiera plików danych.
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
- **Rozmiar pamięci podglądów i czas budowy.** Wachlarz wielu lat
  z arkuszami ASC to setki budów COG. Ograniczenia: limit 20 GB z LRU, COG
  ≤ 8192 px, jedno zadanie budowy na warstwę (≤ 500 wersji) z postępem,
  `n = max(1, cpu // 2)` procesów budowy i jedno zadanie `preview` naraz
  (decyzja 3), budowy tylko dla warstw oglądanych, pliki > 2 GB i rastry
  ponad progi pikseli tylko na żądanie.
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
- **Odstępstwa od A-ADR-029 do v0.4.** Folder danych inny niż domyślny
  ustawia tylko administrator (A-ADR-029 errata 1); ustawianie przez
  właściciela projektu wraca w v0.4 razem z ekranem udostępniania. Skan
  folderu z widoku projektu zleca każdy, kto widzi projekt — tylko folder
  tego projektu i tylko odczyt; przebieg przez foldery wszystkich projektów
  (na udziale SMB do kilkudziesięciu folderów po ≤ 10 s) zleca wyłącznie
  harmonogram. Do ponownej oceny w v0.4 razem z logowaniem i limitami
  żądań.
- **Środowiska pomiarowe.** Udział SMB, magazyny testu na żywo i GPU
  wymagają jawnych `<katalog-danych>` i decyzji właściciela; brak
  środowiska oznacza niezamknięte kryterium, nie automatyczny sukces.
