# PROGRESS — Archiwista

## Start następnej sesji (stan 2026-10-18)

**Status:** dokumentacja produktu i architektura przyjęte; plan v0.1
(`docs/PLAN_v0.1.md`) poprawiony po przeglądzie i uzupełniony o krok 8b
„Model uprawnień” (A-ADR-029); kroki 0–5, 7 i 8 planu ukończone (ostatni:
`1347bb8`), krok 6a w toku.
**Następny krok:** 6a i 8b (równolegle), potem 6b i 9a. Kroki wymagające
KA-1..KA-6 (z `list_segments` i `skip_versions`) korzystają z gałęzi
Kartografa `feat/archiwista-store-api`, zainstalowanej edytowalnie w `.venv`.

### Na samym początku implementacji (pierwsze zadania planu v0.1)

1. ✓ Przetłumaczono na angielski `CONTRIBUTING.md`, `CONTRIBUTORS.md`
   i `.github/pull_request_template.md` (wzór: Hydraulik i IMGWTools,
   A-ADR-026 errata 2). Szablon PR ma też punkty o testach i lintach
   jak w IMGWTools.
2. Stosować `docs/DEVELOPMENT_STANDARDS.md` od pierwszego pliku: cały kod,
   docstringi, komentarze i logi po angielsku; polski tylko w tekstach
   interfejsu (słownik), dokumentacji projektu i opisach commitów.
3. ✓ Krok 1 planu (`c74f8d4`): `pyproject.toml` z `kartograf>=0.8.0,<0.9`,
   `requirements.lock`, Ruff/mypy/pytest z bramką pokrycia 80%, CLI
   `archiwista --help`, interfejs źródła (`archiwista/sources/`). Umowę
   źródła rozszerza wyłącznie krok 2 (plan, sekcja „Umowy”).

### Czytaj najpierw

| Dokument | Rola |
|---|---|
| `docs/PRD.md` | wymagania F1–F16, N1–N8, widoki wg rodzaju danych, miary sukcesu, otwarte decyzje |
| `docs/SCOPE.md` | MVP, poza MVP, etapy z bramkami, zależności od producentów, ryzyka |
| `docs/SPEC.md` | szczegóły; sekcja 13 — zakres i kryteria akceptacji każdej wersji |
| `docs/PLAN_v0.1.md` | plan implementacji v0.1: kontrakty, kolejność kroków, zależności i weryfikacja kryteriów akceptacji |
| `docs/DEVELOPMENT_STANDARDS.md` | standardy kodowania (na bazie IMGWTools): język, nazewnictwo, testy, git, checklista |
| `docs/DECISIONS.md` | A-ADR-001..029 (erraty na końcu wpisów) |
| `mockup/README.md` | mockup: przepływ, co prawdziwe, co symulowane, zrzuty |

### Stan repozytorium

- Gałęzie: `main`, `develop` (plan v0.1 i kod kroków 0–5, 7 i 8),
  `feat/mockup` (historia pierwszych wersji mockupu, `e25e833`). Bez
  remote.
- Kartograf: gałąź `feat/archiwista-store-api` (KA-1..KA-6 w wydaniu 0.8.0,
  ADR-045) — scalenie do `develop` i tag `v0.8.0` dopiero po zgodzie
  użytkownika.

### Decyzje (stan na 2026-10-18)

- **Zakres MVP = v1.0** (A-ADR-025, erraty 1–3): v0.1 Przeglądarka, v0.2
  Podglądy (+ dane własne i migawki), v0.3 Działania (dostępność z etykietami,
  także obrazy PL — KD-3 i wydania BDOT10k — KD-4), v0.4 Zespół, v0.5 Stacje
  IMGW, v0.6 PL + CZ (scalona powierzchnia przez KF Kartografa, stacje ČHMÚ
  przez IMGWTools — IMGW-15..19; errata 3, decyzja 2026-10-18), v1.0 Wydanie.
  Po MVP: v1.1 Zestaw (KB-6; też eksport PL + CZ bez scalania), v1.2
  Asystent, v1.3 Mozaika i porównanie. ADR-019..024 zachowują starą
  numerację („v0.8” = v0.4, „v0.9” = v0.5).
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
- **Uprawnienia** (A-ADR-029, przyjęta 2026-10-18): Archiwista egzekwuje
  uprawnienia tylko we własnej powierzchni (UI, API, CLI, tokeny agentów,
  pamięć podglądów); bezpieczeństwo serwera i udziału to odpowiedzialność
  administratora serwera. Role `admin` (administrator systemu Archiwista),
  `store_writer` i zwykły użytkownik (zastępują „czytelnik/operator/
  administrator”), ustawienie `store_write_for_all`; widoczność projektu
  `public`/`users`/`group`/`private`. v0.1 — model i egzekwowanie dla
  jednego lokalnego właściciela, testy z wieloma tożsamościami, osobna
  lokalna baza stanu `state.sqlite` (nieodtwarzalna; `archiwista state
  export`/`import`), API i CLI administratora (plan: krok 8b); v0.3 —
  `store_writer` przy działaniach; v0.4 — logowanie, konta i ekran
  udostępniania w interfejsie, opcjonalnie grupy LDAP/AD.
- **Plan v0.1 po przeglądzie (2026-10-18):** KA w Kartografie 0.8.0
  (A-ADR-024 errata 1, A-ADR-001 errata 2); skan przyrostowy przez
  `skip_versions`, skan równoległy po segmentach (`list_segments`), bez
  `link_target` w skanie — KA-5 tylko na żądanie (A-ADR-014 errata 2);
  zadanie `footprints` z siecią dla obrysów jednostek; pokrycie lokalne
  w EPSG:2180/5514; sesja z tokenem we fragmencie adresu, osobny token
  CSRF, reguła `Origin`, CSP z podkładami i workerem MapLibre (A-ADR-012
  errata 1); jedna tabela `jobs` z `actor`; TERYT/KU w v0.1 tylko jako
  filtr; kroki 6, 9 i 10 podzielone (6a/6b, 9a–9c, 10a–10c).
- **Klucze zbiorów** (2026-10-18, SPEC 4.2.1): `<kraj>.<dostawca>.<zbiór>[_<wariant>]`, niezmienne, zmiany nazw tylko przez tabelę aliasów producenta, dostawca z pola `provider`; Archiwista nie rozbiera kluczy; wymagania KA-8 i IMGW-20.

### Otwarte

- **Plan v0.1** — kroki 6a, 6b, 8b i 9a–14 do wykonania.
- PRD „Otwarte decyzje”: etykiety pokrycia i ich wygląd (A-ADR-010, mockup
  M2, przed v0.3), format danych IMGW (A-ADR-020, z IMGWTools, przed v0.5),
  łączenie jako produkty pochodne Kartografa (A-ADR-009, P2/P3, przed v0.6),
  adapter stacji ČHMÚ (jeden adapter IMGW czy osobna wtyczka, przy wydaniu
  IMGWTools ze stacjami ČHMÚ).
  Komputer odniesienia dla SSD ustalony w planie v0.1 (decyzja 1); pomiar
  SMB wymaga prawdziwego udziału SMB 3.
- A-ADR-029: nazwy akcji `can(...)` i schemat bazy stanu ustala krok 8b
  planu v0.1.
- Mockup: pytania M3, M5–M8, M10, M11 (SPEC 16).
- Producenci: Kartograf — KA-1..KA-6 (z `list_segments` i `skip_versions`)
  na gałęzi `feat/archiwista-store-api`, blokują kroki 2, 4–7 i 9a–13 do
  instalacji gałęzi, a wydanie v0.1 — do tagu `v0.8.0`; v0.3: KA-4
  (pozycje planu), KB-1..KB-5, KB-7, KC-1..KC-3, KD-1..KD-4, KH-1; roadmapa
  Kartografa niezaktualizowana (czeka na decyzję użytkownika); KF (scalona
  powierzchnia, dziś R6 w backlogu, poza publicznym API 0.8.0) blokuje v0.6,
  a więc MVP. IMGWTools — `docs/wymagania-imgwtools.md` (IMGW-1..20) do
  przekazania; IMGW-1..14 blokują v0.5, a IMGW-15..19 (stacje ČHMÚ; dziś
  szkic „Obserwator” bez kodu) — v0.6, a więc MVP — największe ryzyko
  harmonogramu.
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
