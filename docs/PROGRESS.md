# PROGRESS — Archiwista

## Start następnej sesji (stan 2026-10-19)

**Status:** wydanie **0.1.0 „Przeglądarka”** gotowe na `develop`
(`chore(release): wydanie 0.1.0`): kroki 0–14 planu v0.1
(`docs/PLAN_v0.1.md`) ukończone, wszystkie kryteria SPEC 13 v0.1
zaliczone, bramka zielona (`docs/reports/v0.1-measurements.md`, sekcja 10).
Bez tagu `v0.1.0` i bez scalenia do `main` — czeka na decyzję
użytkownika.
**Następny krok:** przegląd planu v0.2 „Podglądy” (`docs/PLAN_v0.2.md`,
projekt z 2026-10-19: decyzje 1–14, umowy, kroki 0–18, bramka), potem
implementacja od fali A (kroki 0–3) — kolejność jak przy v0.1: spec →
plan → przegląd planu → implementacja. Zakres i kryteria: SPEC 13 v0.2,
SCOPE etap 3.

### Czytaj najpierw

| Dokument | Rola |
|---|---|
| `README.md` | instalacja, uruchomienie, CLI, położenie danych, bramka |
| `docs/CHANGELOG.md` | co weszło do 0.1.0, znane ograniczenia |
| `docs/PRD.md` | wymagania F1–F16, N1–N8, widoki wg rodzaju danych, miary sukcesu, otwarte decyzje |
| `docs/SCOPE.md` | MVP, poza MVP, etapy z bramkami, zależności od producentów, ryzyka |
| `docs/SPEC.md` | szczegóły; sekcja 13 — zakres i kryteria akceptacji każdej wersji |
| `docs/PLAN_v0.1.md` | plan v0.1 z umowami między krokami — wzór dla planu v0.2 |
| `docs/PLAN_v0.2.md` | plan v0.2 „Podglądy” (projekt do przeglądu): decyzje, umowy między krokami, kroki 0–18 z równoległością, bramka SPEC 13 v0.2, ryzyka |
| `docs/ARCHITECTURE.md` | architektura kodu 0.1.0: moduły, przepływy, granice — opis kodu, nie planu |
| `docs/reports/v0.1-measurements.md` | pomiary SPEC 4.5, odbiór v0.1, bramka wydania, zrzuty |
| `docs/USAGE.md`, `docs/AGENT_API.md` | dokumentacja użytkownika i agentów (stan 0.1.0) |
| `docs/DEVELOPMENT_STANDARDS.md` | standardy kodowania (na bazie IMGWTools): język, nazewnictwo, testy, git, checklista |
| `docs/DECISIONS.md` | A-ADR-001..029 (erraty na końcu wpisów) |
| `mockup/README.md` | mockup: przepływ, co prawdziwe, co symulowane, zrzuty |

### Stan repozytorium

- Gałęzie: `main` (tylko commit inicjalizujący), `develop` (wydanie 0.1.0),
  `feat/mockup` (historia pierwszych wersji mockupu, `e25e833`). Bez
  remote, bez tagów.
- Kartograf: KA-1..KA-6 w wydaniu 0.8.0 (ADR-045) oraz `list_partitions`,
  `iter_store(partition=…)` i mapowanie w `skip_versions` (ADR-045
  errata 1). Stan 2026-10-19: gałąź `feat/archiwista-store-api` scalona
  do `develop` Kartografa (scalenie `b71cc370`) i usunięta, tagu `v0.8.0`
  brak; Archiwista wymaga Kartografa zainstalowanego edytowalnie w `.venv`
  (z `develop`; instrukcja README wskazuje jeszcze gałąź — krok 18 planu
  v0.2).
- Dane robocze poza repo: `<katalog-danych>` (magazyny syntetyczne,
  przebiegi pomiarów, środowiska smoke).

### Wydanie 0.1.0 w skrócie

- Widoki Mapa, Katalog, Karta pliku, Projekty, Magazyn, kreator
  i Ustawienia; API `/api/v1` z OpenAPI i `/api/docs`; CLI z `--json`;
  uprawnienia (A-ADR-029) z bazą stanu; wtyczki źródeł (A-ADR-024).
- SPEC 4.5 na 50 000 slotów przez `archiwista serve`: SSD (kod wydania) —
  pełny skan 48,3 s, przyrostowy 12,4 s, odświeżenie widoku p95 408 ms;
  SMB 3 (przebieg 3) — 225,6 s, 74,7 s, 1,83 s; RSS serwera ≤ 179 MiB,
  indeks 256 MB.
- Po przeglądach kodu i bezpieczeństwa: token CSRF w każdym żądaniu `/api`
  (także odczycie), sesje bez kopii ról, sesje agentów do 12 h
  i `archiwista token --revoke-all`, limity treści żądań, prywatne dane
  lokalne (`0700`, `umask 077`), trasa plików zgłoszenia przeniesiona
  z `/groups/{…}` na `/requests/{parent_request}`, przycinanie rutynowych
  skanów po 48 h.

### Decyzje (stan na 2026-10-19)

- **Zakres MVP = v1.0** (A-ADR-025, erraty 1–3): v0.1 Przeglądarka, v0.2
  Podglądy (+ dane własne i migawki), v0.3 Działania (dostępność z etykietami,
  także obrazy PL — KD-3 i wydania BDOT10k — KD-4), v0.4 Zespół, v0.5 Stacje
  IMGW, v0.6 PL + CZ (scalona powierzchnia przez KF Kartografa, stacje ČHMÚ
  przez IMGWTools — IMGW-15..19; errata 3, decyzja 2026-10-18), v1.0 Wydanie.
  Po MVP: v1.1 Zestaw (KB-6; też eksport PL + CZ bez scalania), v1.2
  Asystent, v1.3 Mozaika i porównanie. ADR-019..024 zachowują starą
  numerację („v0.8” = v0.4, „v0.9” = v0.5).
- **Architektura** (etap 0): Python + FastAPI (A-ADR-004), interfejs
  Preact + htm bez kroku budowania, biblioteki w pakiecie, bez Node.js
  (A-ADR-028), MapLibre GL (006), procesy robocze (007), rio-tiler, podgląd
  roku z kafli arkuszy (008, od v0.2), pakiet Pythona `archiwista serve`
  (015), tryb zespołu jako jeden serwer (013, P1). Indeks SQLite lokalnie
  (002).
- **Granice:** magazyn producentów tylko do odczytu; Archiwista zleca
  pobieranie i obróbkę, nie ma własnego mechanizmu (zapis przez API
  Kartografa i IMGWTools); IMGWTools opcjonalny (`archiwista[imgw]`,
  A-ADR-024).
- **Dane własne** (A-ADR-027, od v0.2): folder projektu (domyślnie
  `<katalog projektu>/dane/`), indeks tylko do odczytu; migawki całych plików
  robi Archiwista w `<folder danych>/.wersje/` (tylko przyrost, zapis atomowy,
  spójna kopia GeoPackage); jedyny wyjątek od zasady „Archiwista nie
  zapisuje” (także w `CLAUDE.md`).
- **Widoki wg rodzaju danych** (PRD): ortofotomapa — rok z archiwalnego WMS
  GUGiK z wymiarem czasu; NMT/NMPT/LAZ — rok z kafli pobranych arkuszy;
  BDOT10k — powiaty z PRG; dane własne — linie i migawki; N8 Rozszerzalność.
- **Interfejs i słownictwo:** A-ADR-016..018 (Wachlarz, daty `RRRR.MM.DD`,
  asystent jako panel boczny); domyślny podkład to kafle wektorowe
  OpenFreeMap we własnym szarym stylu z polskimi nazwami (A-ADR-016
  errata 2 — BKG TopPlusOpen drukował niemieckie egzonimy; errata 1 — kafle
  OSM bez nagłówka `Referer` są blokowane), drugi wbudowany to OSM GUGiK
  (tylko Polska); etykiety pokrycia A-ADR-010, 017; dane IMGW
  A-ADR-019..023.
- **Uprawnienia** (A-ADR-029): egzekwowane tylko we własnej powierzchni
  Archiwisty (UI, API, CLI, tokeny agentów, pamięć podglądów); role `admin`
  i `store_writer`, ustawienie `store_write_for_all`, widoczność projektu
  `public`/`users`/`group`/`private`. v0.1 — model, egzekwowanie i baza
  stanu `state.sqlite` (nieodtwarzalna; `archiwista state export`/`import`);
  v0.3 — `store_writer` przy działaniach; v0.4 — logowanie, konta i ekran
  udostępniania, opcjonalnie grupy LDAP/AD.
- **Klucze zbiorów** (SPEC 4.2.1): `<kraj>.<dostawca>.<zbiór>[_<wariant>]`,
  niezmienne, zmiany nazw tylko przez tabelę aliasów producenta, dostawca
  z pola `provider`; Archiwista nie rozbiera kluczy; wymagania KA-8
  i IMGW-20.
- **Licencja i kontrybucje:** MIT, CLA jak w Hydrauliku i IMGWTools
  (A-ADR-026, errata 1).

### Otwarte

- **Kartograf:** gałąź `feat/archiwista-store-api` scalona do `develop`
  Kartografa (2026-10-19, `b71cc370`); tag `v0.8.0` — decyzja użytkownika
  i zespołu Kartografa. Do tego czasu Archiwista działa z Kartografem
  zainstalowanym edytowalnie (plan v0.1, „Ryzyka”: wydanie miało wymagać
  otagowanego Kartografa — świadomie odłożone).
- **Tag `v0.1.0` i scalenie `develop` → `main`** — na prośbę użytkownika.
- **Płynność mapy** z 5000 obrysów (≥ 30 klatek/s, kryterium v0.2) wymaga
  WebGL sprzętowego: komputer odniesienia ma GTX 1060 (`nouveau`), ale
  konto pomiarowe nie ma dostępu do `/dev/dri/renderD128` — decyzja
  właściciela komputera (grupa `render` albo pomiar przez CDP w jego
  sesji; plan v0.2, decyzja 1 i krok 16). Bez GPU 8–9 klatek/s.
- **Plan v0.2 do przeglądu:** nazwy `.wersje/` i `migawka.json`, schemat
  `archiwista-snapshot/1`, obrysy-wielokąty zamiast obwiedni, dane własne
  poza `/slots`, akcja `project.write` i pozostałe decyzje 1–14
  (`docs/PLAN_v0.2.md`) — do potwierdzenia przez użytkownika.
- Drobne sprawy techniczne po pomiarach v0.1: pola ścieżek `SourceEntry`
  jako `Path` kosztują 2–3 s skanu przyrostowego na SSD (zmiana interfejsu
  wtyczek, cel spełniony bez niej); `ResourceWarning` niezamkniętego
  połączenia SQLite w pełnym przebiegu testów (zgłaszany przy
  `tests/unit/test_security.py::test_security_current_principal_owner_then_agent`,
  źródło nieustalone — kod `security.py` zamyka swoje połączenia) — krok 0
  planu v0.2.
- PRD „Otwarte decyzje”: etykiety pokrycia i ich wygląd (A-ADR-010, mockup
  M2, przed v0.3), format danych IMGW (A-ADR-020, z IMGWTools, przed v0.5),
  łączenie jako produkty pochodne Kartografa (A-ADR-009, P2/P3, przed v0.6),
  adapter stacji ČHMÚ (jeden adapter IMGW czy osobna wtyczka, przy wydaniu
  IMGWTools ze stacjami ČHMÚ).
- Mockup: pytania M3, M5–M8, M10, M11 (SPEC 16).
- Producenci: Kartograf — v0.3: KA-4 (pozycje planu), KB-1..KB-5, KB-7,
  KC-1..KC-3, KD-1..KD-4, KH-1; roadmapa Kartografa niezaktualizowana (czeka
  na decyzję użytkownika); KF (scalona powierzchnia, dziś R6 w backlogu,
  poza publicznym API 0.8.0) blokuje v0.6, a więc MVP. IMGWTools —
  `docs/IMGWTOOLS_REQUIREMENTS.md` (IMGW-1..20) do przekazania; IMGW-1..14
  blokują v0.5, a IMGW-15..19 (stacje ČHMÚ; dziś szkic „Obserwator” bez
  kodu) — v0.6, a więc MVP — największe ryzyko harmonogramu.
- Szkice SPEC 6.5 a, b, i, j w starym układzie (panel „Zestawienie”).
- Nazwy przy A-ADR-024 (`GET /sources`, `source_unavailable` /
  `source_incompatible`, fabryki `moduł:load`) — do ewentualnej zmiany.
- IMGWTools 3.0.0 (`slave` od `0d98f3b`, bez tagu) spełnia IMGW-1..20 z ČHMÚ;
  SPEC (UC-20, 4.4, 4.6, 4.8, 5.6, 12.7–12.8, 13 v0.5–v0.6, 14),
  `docs/IMGWTOOLS_REQUIREMENTS.md` (6.3: odpowiedzi na pytania ADR-003)
  i A-ADR-019 (errata 3)/021/023 zgodne z audytem 2026-10-19 i modelem
  zapisu Kartografa w IMGWTools (dowiązania twarde, sidecar zatwierdza
  wersję; udział musi obsługiwać dowiązania twarde dla obu producentów).
  Przed tagiem — gałąź IMGWTools `fix/archiwista-compat-2`: wycofanie
  publikacji bez usuwania plików przejętych przez współbieżny zapis,
  `meteo_kind`, test kolizji `2001_01_k.zip` (`fix/archiwista-compat`
  zastąpiona). Adapter v0.5: `missing_sidecar` to problem niekrytyczny
  i możliwie przejściowy, `current_version` nie zgłasza dla niego
  `IMGWDataError`; zapis IMGWTools na prawdziwym Windows i macOS
  nieuruchomiony.

### Mockup

- Uruchomienie: `python3 -m http.server 8090 --bind 127.0.0.1 --directory mockup`
  (z korzenia repo); użytkownik ogląda przez tunel SSH
  (`ssh -L 8090:localhost:8090 …`), bo `ufw` blokuje port w LAN. Potrzebny
  internet (CDN bibliotek, kafle OpenFreeMap).
- Mockup był punktem wyjścia interfejsu (A-ADR-028), ale nie jest kodem
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
