# Mockup Archiwisty

Klikalny mockup interfejsu Archiwisty do decyzji przed implementacją
(bez kroku budowania: `index.html` + moduły ES z CDN — Preact, htm,
MapLibre GL).

## Uruchomienie

Z korzenia repozytorium:

```
python3 -m http.server 8765 --directory mockup
```

i otwórz <http://127.0.0.1:8765/>. W sieci lokalnej (np. telefon) dodaj
`--bind 0.0.0.0` i otwórz `http://<adres-komputera>:8765/`. Przeglądarka
potrzebuje internetu (CDN bibliotek i fontów, podkład OpenFreeMap).

## Przepływ

1. **Obszar** — prostokąt, wielokąt albo „Obszar demo” (Kraków 12 × 10 km).
2. **Produkt** — NMT, NMPT, LAZ, ortofotomapa, BDOT10k.
3. **Dostępność** — wynik w trzech widokach (przełącznik nad mapą):
   **Mapa** (arkusze wybranego roku, kolory kampanii, legenda z datami
   nalotu), **Stos** (izometryczny stos lat; wybrany rok wysuwa się ze
   stosu, wyższe warstwy stają się półprzezroczyste) i **Katalog** (kafle
   albo lista całego zestawu).
4. **Zestawienie** (panel po prawej) — **Tabela** lat i **Oś czasu**
   (lata × warianty × pokrycie).
5. **Asystent** — np. „Przygotuj NMT 1 m dla tego obszaru, najnowszy pełny
   rok, jako jedna mozaika” → plan kroków → „Zatwierdź i uruchom” / „Zmień
   rok” / „Odrzuć” → postęp zadania (czat i „Zadania”) → wynik na mapie,
   w stosie i w „Karcie pliku”.

Wariant = produkt, rok, układ poziomy, rozdzielczość (gęstość), układ
wysokości i zgłoszenie/kampania. Formaty plików tego samego zestawu to
plakietki jednego wariantu (np. NMT 2019 „5 m · EVRF2007 · ASC, ASCII-NMT”);
format wybiera się dopiero przy pobraniu (plakietki na karcie, w panelu
roku, w Karcie pliku i w planie asystenta), domyślnie raster gotowy do
mozaiki (ASC, TIF). Raport Kartografa zostaje per format — grupuje
Archiwista.

Etykiety pokrycia: „pełne”, „pełne · N kampanie”, „częściowe · X%”,
„brak danych”; osobna plakietka magazynu: „pobrane”, „pobrane 5/12”,
„niepobrane”. Daty w interfejsie: RRRR.MM.DD. Podkład: szary (OpenFreeMap
„positron” w odcieniach szarości). Układ: desktop 1440–1920 px (panel
wyboru można zwinąć), poniżej 1280 px „Zestawienie” wysuwa się z prawej,
na telefonie panele i czat są szufladami od dołu.

## Co jest prawdziwe, a co symulowane

- Prawdziwe: raporty dostępności NMT, NMPT i LAZ (`kartograf elevation
  availability --json`, `kartograf-availability/1`) dla obszaru demo,
  ramy arkuszy (godła → EPSG:2180 → WGS84) i podglądy GUGiK WMS.
- Zestawione skryptem mockupu na bibliotekach Kartografa (Kartograf nie ma
  jeszcze takiego raportu): ortofotomapa (skorowidz WMS) i BDOT10k
  (pakiety powiatów); pola `full_m2`, `sheet_records`,
  `campaigns_selected` to propozycje dla Kartografa.
- Symulowane: sprawdzanie dostępności (fazy i opóźnienia), stan magazynu
  (`data/store.json`), asystent (proste reguły zamiast modelu), zadania
  w tle, pobieranie i mozaika (wynik to podgląd przycięty do obszaru),
  oszacowanie pokrycia dla narysowanego obszaru (z ram arkuszy raportu).

## Dane

`data/` to statyczne fixtury. Odtworzenie (z korzenia repo Kartografa, jego
`.venv`, z siecią): `.venv/bin/python <worktree>/mockup/tools/build_fixtures.py`
(NMT, NMPT, LAZ, arkusze) i `build_orto_bdot.py` (ortofotomapa, BDOT10k).

## Zrzuty

`screenshots/` — kolejne kroki przepływu na desktopie 1920 × 1080
(`01`–`16`), widok Stos przy 1440 px (`17`) i telefon 390 px (`18`–`19`);
`05a`–`05c`: Stos z wybranym rokiem najnowszym, środkowym i najstarszym.
