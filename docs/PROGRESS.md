# PROGRESS — Archiwista

## Start następnej sesji (stan 2026-10-18)

**Status:** dokumentacja produktu i architektura przyjęte; bez kodu aplikacji.
**Następny krok:** plan implementacji v0.1 (SCOPE, etap 0 — ostatni element
przed kodem; zatwierdza użytkownik). Kolejność pracy: spec → plan →
implementacja.

### Na samym początku implementacji (pierwsze zadania planu v0.1)

1. ✓ Przetłumaczono na angielski `CONTRIBUTING.md`, `CONTRIBUTORS.md`
   i `.github/pull_request_template.md` (wzór: Hydraulik i IMGWTools,
   A-ADR-026 errata 2). Szablon PR ma też punkty o testach i lintach
   jak w IMGWTools.
2. Stosować `docs/DEVELOPMENT_STANDARDS.md` od pierwszego pliku: cały kod,
   docstringi, komentarze i logi po angielsku; polski tylko w tekstach
   interfejsu (słownik), dokumentacji projektu i opisach commitów.

### Czytaj najpierw

| Dokument | Rola |
|---|---|
| `docs/PRD.md` | wymagania F1–F15, N1–N8, widoki wg rodzaju danych, miary sukcesu, otwarte decyzje |
| `docs/SCOPE.md` | MVP, poza MVP, etapy z bramkami, zależności od producentów, ryzyka |
| `docs/SPEC.md` | szczegóły; sekcja 13 — zakres i kryteria akceptacji każdej wersji |
| `docs/DEVELOPMENT_STANDARDS.md` | standardy kodowania (na bazie IMGWTools): język, nazewnictwo, testy, git, checklista |
| `docs/DECISIONS.md` | A-ADR-001..028 (erraty na końcu wpisów) |
| `mockup/README.md` | mockup: przepływ, co prawdziwe, co symulowane, zrzuty |

### Stan repozytorium

- Gałęzie: `main`, `develop` (ostatni commit `db4d1e3`), `feat/mockup`
  (historia pierwszych wersji mockupu, `e25e833`). Bez remote.
- **NIEZACOMMITOWANE** (commit tylko na polecenie użytkownika; proponowany
  podział po tematach): `docs/SPEC.md`, `docs/DECISIONS.md`, `README.md`,
  `CLAUDE.md`, nowe `docs/PRD.md`, `docs/SCOPE.md`, `docs/PROGRESS.md`,
  `docs/wymagania-imgwtools.md`, `LICENSE`, `CONTRIBUTING.md`,
  `CONTRIBUTORS.md`, `docs/CLA.md`, `.github/pull_request_template.md`,
  `docs/DEVELOPMENT_STANDARDS.md` (skopiowany z IMGWTools i dostosowany) oraz
  cały katalog `mockup/` (z nowymi fixturami i zrzutami `26`–`35`).

### Decyzje (stan na 2026-10-18)

- **Zakres MVP = v1.0** (A-ADR-025, erraty 1–2): v0.1 Przeglądarka, v0.2
  Podglądy (+ dane własne i migawki), v0.3 Działania (dostępność z etykietami,
  także obrazy PL — KD-3 i wydania BDOT10k — KD-4), v0.4 Zespół, v0.5 Stacje
  IMGW, v1.0 Wydanie. Po MVP: v1.1 Zestaw (KB-6), v1.2 Asystent, v1.3 Mozaika
  i porównanie, v1.4 PL + CZ. ADR-019..024 zachowują starą numerację
  („v0.8” = v0.4, „v0.9” = v0.5).
- **Architektura przyjęta (etap 0):** Python + FastAPI (A-ADR-004), interfejs
  Preact + htm bez kroku budowania, biblioteki w pakiecie, bez Node.js
  (A-ADR-028, zastępuje A-ADR-005), MapLibre GL (006), procesy robocze (007),
  rio-tiler, podgląd roku z kafli arkuszy (008), pakiet Pythona
  `archiwista serve` (015), tryb zespołu jako jeden serwer (013, P1). Indeks
  SQLite lokalnie (002).
- **Granice:** magazyn producentów tylko do odczytu; Archiwista zleca
  pobieranie i obróbkę, nie ma własnego mechanizmu (zapis przez API
  Kartografa i IMGWTools); IMGWTools opcjonalny (`archiwista[imgw]`,
  A-ADR-024).
- **Dane własne** (A-ADR-027): folder projektu (domyślnie
  `<katalog projektu>/dane/`), indeks tylko do odczytu; migawki całych plików
  robi Archiwista w `<folder danych>/.wersje/` (tylko przyrost, zapis atomowy,
  spójna kopia GeoPackage); jedyny wyjątek od zasady „Archiwista nie
  zapisuje” (także w `CLAUDE.md`).
- **Widoki wg rodzaju danych** (PRD): ortofotomapa — rok z archiwalnego WMS
  GUGiK z wymiarem czasu; NMT/NMPT/LAZ — rok z kafli pobranych arkuszy;
  BDOT10k — powiaty z PRG; dane własne — linie i migawki; N8 Rozszerzalność.
- **Licencja i kontrybucje:** MIT, CLA jak w Hydrauliku i IMGWTools
  (A-ADR-026, errata 1).
- Interfejs i słownictwo: A-ADR-016..018 (Wachlarz, daty `RRRR.MM.DD`, szary
  podkład OSM, asystent jako panel boczny); etykiety pokrycia A-ADR-010, 017;
  dane IMGW A-ADR-019..023.

### Otwarte

- **Plan v0.1** — do przygotowania i zatwierdzenia (komputer odniesienia dla
  celów wydajności też tu).
- PRD „Otwarte decyzje”: etykiety pokrycia i ich wygląd (A-ADR-010, mockup
  M2, przed v0.3), format danych IMGW (A-ADR-020, z IMGWTools, przed v0.5),
  łączenie jako produkty pochodne Kartografa (A-ADR-009, P2/P3, przed v1.3),
  komputer odniesienia (przed v0.1).
- Mockup: pytania M3, M5–M8, M10, M11 (SPEC 16).
- Producenci: Kartograf — KA-1..KA-6 blokują v0.1; v0.3: KA-4 (pozycje
  planu), KB-1..KB-5, KB-7, KC-1..KC-3, KD-1..KD-4, KH-1; roadmapa Kartografa
  niezaktualizowana (czeka na decyzję użytkownika). IMGWTools —
  `docs/wymagania-imgwtools.md` (IMGW-1..14) do przekazania; blokuje v0.5,
  a więc MVP — największe ryzyko harmonogramu.
- Szkice SPEC 6.5 a, b, i, j w starym układzie (panel „Zestawienie”).
- Nazwy katalogów i schemat `archiwista-snapshot/1` migawek — w planie v0.2.
- Nazwy przy A-ADR-024 (`GET /sources`, `source_unavailable` /
  `source_incompatible`, fabryki `moduł:load`) — do ewentualnej zmiany.
- Drobne rozbieżności SPEC 12.7 / 4.8 z kodem IMGWTools — świadomie
  niepoprawiane (decyzja użytkownika).

### Mockup

- Uruchomienie: `python3 -m http.server 8090 --bind 127.0.0.1 --directory mockup`
  (z korzenia repo); użytkownik ogląda przez tunel SSH
  (`ssh -L 8090:localhost:8090 …`), bo `ufw` blokuje port w LAN. Potrzebny
  internet (CDN bibliotek, kafle OpenFreeMap).
- Mockup jest punktem wyjścia interfejsu (A-ADR-028), ale nie kodem
  produkcyjnym: pobieranie idzie w nim przez asystenta (w MVP — „Okno planu”
  bez asystenta), sprawdzanie, magazyn, zadania, migawki i mozaika są
  symulowane.
- Fixtury: `mockup/tools/build_fixtures.py` (NMT, NMPT, LAZ, arkusze),
  `build_orto_bdot.py` (ortofotomapa, BDOT10k), `build_mvp_fixtures.py`
  (`orto` — archiwalne ortofotomapy per rok, `powiaty` — PRG, `own` —
  przykładowa sieć kanalizacyjna, `nmt` — kafle z arkuszy magazynu);
  uruchamiane z korzenia Kartografa jego `.venv`.
- Roboczy katalog poza repo: `../archiwista-mockup-data/` (ok. 2,9 GB;
  `magazyn/` — prawdziwe arkusze NMT pobrane Kartografem: 2023 1 m — 5 ark.,
  2019 5 m, 2017 1 m KRON86, 2024 1 m; źródło kafli
  `mockup/data/previews/nmt/`). Mockup go nie potrzebuje; do usunięcia za
  zgodą użytkownika.
