# Mockup Archiwisty

Klikalny mockup interfejsu Archiwisty do decyzji przed implementacją
(bez kroku budowania: `index.html` + moduły ES z CDN — Preact, htm,
MapLibre GL).

## Uruchomienie

Z korzenia repozytorium:

```
python3 -m http.server 8090 --directory mockup
```

i otwórz <http://127.0.0.1:8090/>. W sieci lokalnej (np. telefon) dodaj
`--bind 0.0.0.0` i otwórz `http://<adres-komputera>:8090/`. Przeglądarka
potrzebuje internetu (CDN bibliotek i fontów, podkład OpenFreeMap).

## Przepływ

1. **Obszar** — prostokąt, wielokąt albo „Obszar demo” (Kraków 12 × 10 km).
2. **Produkt** — NMT, NMPT, LAZ, ortofotomapa, BDOT10k oraz **dane własne
   projektu** (`kanalizacja.gpkg` w folderze `dane/`; przycisk „Wczytaj folder
   danych” zamiast sprawdzania dostępności).
3. **Dostępność** — podsumowanie sprawdzenia w panelu wyboru (lata wg
   pokrycia, data raportu, źródło), wynik w trzech widokach (przełącznik nad
   mapą): **Mapa** (arkusze wybranego zestawu, kolory kampanii, legenda
   z datami nalotu, lata jako przyciski w lewym górnym rogu mapy),
   **Wachlarz** (warstwy lat na łuku jak stos plików w docku macOS — każda
   w całości, z rokiem, pokryciem i stanem magazynu, wybrana powiększona
   w łuku i obok) i **Katalog** (cały zestaw: **Kafle**, **Lista** albo
   **Oś czasu** — lata × warianty × pokrycie). Kafel, wiersz listy
   i komórka osi czasu to zestaw: kliknięcie, `Enter` albo `Spacja` wybiera
   go (mapa, Wachlarz i panel szczegółów idą za wyborem).
4. **Szczegóły zestawu** (panel po prawej) — tylko wybrany zestaw: formaty
   (wybór formatu pobrania), arkusze TAK/NIE, nalot, kampanie, polecenie
   pobrania, „Pobierz”, „Mozaika z asystentem”, „Karta”, a poza Katalogiem
   przełącznik wariantów roku. Panel pojawia się po sprawdzeniu dostępności
   i można go zwinąć przyciskiem „Szczegóły” nad widokiem.
5. **Asystent** (po MVP, v1.2; w mockupie oznaczony „po MVP”) — np.
   „Przygotuj NMT 1 m dla tego obszaru, najnowszy pełny rok, jako jedna
   mozaika” → plan kroków → „Zatwierdź i uruchom” / „Zmień rok” / „Odrzuć”
   → postęp zadania (czat i „Zadania”) → wynik na mapie, w wachlarzu
   i w „Karcie pliku”. Mozaika to również funkcja po MVP (v1.3).
6. **Dane własne i migawki** (MVP, v0.2; A-ADR-027) — mapa przewodów
   wybranej wersji, „Wachlarz migawek” (plik roboczy na górze; zielone —
   dodane od poprzedniej migawki, czerwone przerywane — usunięte), Katalog
   wersji pliku, a w panelu szczegółów „Zrób migawkę…” → plan (kopia do
   `dane/.wersje/<nazwa>/<data>_<sha8>/`, spójna kopia GeoPackage, tylko
   przyrost) → zadanie w tle → nowa migawka; ta sama treść drugi raz =
   „nowa migawka nie powstanie”.

Podglądy według rodzaju danych (PRD, „Widoki według rodzaju danych”):
ortofotomapa — każdy rok z archiwalnego WMS GUGiK z wymiarem czasu
(`StandardResolutionTime`), także lata niepobrane; NMT — rok składany
z kafli arkuszy w magazynie: cieniowanie liczone z prawdziwych plików
arkuszy pobranych Kartografem (2023 — 5 arkuszy, 2019 5 m, 2017 KRON86;
2024 pojawia się arkusz po arkuszu po „Pobierz” w mockupie), arkusze
niepobrane zostają obrysami; NMPT i LAZ — same obrysy; BDOT10k — granice powiatów
(PRG) w kolorach „paczka jest / brak / w magazynie”; dane własne — linie
warstwy. Wcześniejsza wersja mockupu pokazywała dla każdego roku ten sam
bieżący obraz, przez co zmiany w terenie nie były widoczne.

Zasada układu: **jedna informacja — jedno miejsce**. Panel wyboru = obszar,
produkt i podsumowanie sprawdzenia; środek = przegląd zestawów (Mapa,
Wachlarz, Katalog); panel po prawej = szczegóły jednego, wybranego zestawu;
Asystent = rozmowa i plany. Plakietka roku na mapie pokazuje się tylko przy
zwiniętym panelu szczegółów, a podpisy Wachlarza nie powtarzają nalotu
i kampanii.

Wariant = produkt, rok, układ poziomy, rozdzielczość (gęstość), układ
wysokości i zgłoszenie/kampania. Formaty plików tego samego zestawu to
plakietki jednego wariantu (np. NMT 2019 „5 m · EVRF2007 · ASC, ASCII-NMT”);
format wybiera się dopiero przy pobraniu (plakietki w panelu szczegółów,
w Karcie pliku i w planie asystenta), domyślnie raster gotowy do
mozaiki (ASC, TIF). Raport Kartografa zostaje per format — grupuje
Archiwista.

Etykiety pokrycia: „pełne”, „pełne · N kampanie”, „częściowe · X%”,
„brak danych”; osobna plakietka magazynu: „pobrane”, „pobrane 5/12”,
„niepobrane”. Daty w interfejsie: RRRR.MM.DD. Podkład: szary (OpenFreeMap
„positron” w odcieniach szarości). Układ: desktop 1440–1920 px (panel
wyboru i panel szczegółów można zwinąć; Asystent to przypięty panel boczny
między mapą a „Szczegółami zestawu”, mapa się zwęża), poniżej 1280 px —
a do 1599 px przy otwartym Asystencie — „Szczegóły zestawu” wysuwają się
z prawej, na telefonie panele i czat są szufladami od dołu.

Szerokie ekrany (2560, 3440, 5120 px): domyślne szerokości paneli rosną
z ekranem (`src/panels.js`; panel szczegółów najmniej, bo trzyma jeden
zestaw), oś czasu Katalogu rysuje się 1:1 w szerokości widoku,
Wachlarz powiększa miniatury, podpisy i podgląd i jest wyśrodkowany,
Katalog układa lata w kolumnach, a gdy na środek zostaje ≥ 2000 px,
Wachlarz albo Katalog stoi obok mapy (dwie połowy). Każdy panel boczny ma
uchwyt na krawędzi (`role="separator"`): przeciąganie, strzałki na
uchwycie (`Shift` — krok 64 px), `Home`/`End`, dwuklik albo `Enter` =
szerokość domyślna; granice: wybór 260–560, Asystent 300–760,
„Szczegóły zestawu” 340–720 px, środek co najmniej 480 px. Szerokości są
zapamiętywane w `localStorage` (`archiwista-mockup:panel-widths`).

## Co jest prawdziwe, a co symulowane

- Prawdziwe: raporty dostępności NMT, NMPT i LAZ (`kartograf elevation
  availability --json`, `kartograf-availability/1`) dla obszaru demo,
  ramy arkuszy (godła → EPSG:2180 → WGS84), podglądy GUGiK WMS (także
  archiwalne ortofotomapy z wymiarem czasu) i granice powiatów z PRG WFS.
- Zestawione skryptem mockupu na bibliotekach Kartografa (Kartograf nie ma
  jeszcze takiego raportu): ortofotomapa (skorowidz WMS) i BDOT10k
  (pakiety powiatów); pola `full_m2`, `sheet_records`,
  `campaigns_selected` to propozycje dla Kartografa.
- Wygenerowane (dane przykładowe): sieć kanalizacyjna w folderze danych
  projektu i jej migawki (`data/own/kanalizacja.json`) — nie są to
  prawdziwe dane.
- Symulowane: sprawdzanie dostępności (fazy i opóźnienia), stan magazynu
  (`data/store.json`), asystent (proste reguły zamiast modelu), zadania
  w tle, pobieranie, mozaika (wynik to podgląd przycięty do obszaru)
  i zapis migawki, oszacowanie pokrycia dla narysowanego obszaru (z ram
  arkuszy raportu).

## Dane

`data/` to statyczne fixtury. Odtworzenie (z korzenia repo Kartografa, jego
`.venv`, z siecią): `.venv/bin/python <worktree>/mockup/tools/build_fixtures.py`
(NMT, NMPT, LAZ, arkusze), `build_orto_bdot.py` (ortofotomapa, BDOT10k)
i `build_mvp_fixtures.py` (archiwalne ortofotomapy per rok, granice
powiatów, przykładowe dane własne; argumenty `orto`, `powiaty`, `own`
budują tylko wskazane części).

## Zrzuty

`screenshots/` — podgląd w WebP (szerokość do 1280 px, jakość 70; łącznie
ok. 2 MB): kolejne kroki przepływu na desktopie 1920 × 1080 (`01`–`16`;
`05a`–`05c`: Wachlarz z wybranym rokiem najnowszym, środkowym
i najstarszym, `14`: Wachlarz z wynikiem zadania i przypiętym Asystentem),
Wachlarz przy 1440 px (`17`), telefon 390 px (`18`–`19`), warianty
z formatami jako plakietki (`20`) i Wachlarz (`21-wachlarz-*`: NMT z rokiem
najnowszym i środkowym, ortofotomapa, z przypiętym Asystentem). Szerokie
ekrany (`22-ultrawide-*`): 1920 × 1080 (kontrola), Wachlarz przy
2560 × 1080 i 3440 × 1440, Katalog przy 3440 × 1440, mapa z Wachlarzem
obok siebie przy 5120 × 1440; `23-panel-resize`: przeciąganie uchwytu
panelu Asystenta (2560 px); `24-katalog-wybor`: wybór zestawu kliknięciem
w kafel Katalogu (2023, wariant PL-2000; 1920 px); `25-panel-szczegoly`:
panel „Szczegóły zestawu” obok mapy z Wachlarzem (3440 × 1440). Zrzuty
`01`–`04`, `06`–`13`, `15`–`16` i `18`–`19` pokazują stan sprzed
przypiętego panelu Asystenta i sprzed usunięcia widoku „Stos”
(przełącznik widoku „Mapa · Stos · Katalog”); zrzuty `01`–`23` — stan
sprzed panelu „Szczegóły zestawu” (prawy panel „Zestawienie” z tabelą lat
i osią czasu, lista lat w panelu wyboru). Zakres MVP i widoki według
rodzaju danych (2026-10-18, 1920 × 1080): `26` mapa z archiwalną
ortofotomapą 2013, `27` Wachlarz ortofotomapy z wybranym 2009, `28`
Wachlarz NMT z kaflami arkuszy z magazynu (2017), `35` mapa NMT 2024
złożona z 35 arkuszy po pobraniu, `29`–`30` BDOT10k —
powiaty w Wachlarzu i na mapie, `31`–`34` dane własne: mapa, Wachlarz
migawek, plan migawki, stan po migawce.
