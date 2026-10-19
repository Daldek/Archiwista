# Archiwista

Archiwista to aplikacja webowa do pracy z magazynem danych: przestrzennych,
które tworzy [Kartograf](https://github.com/Daldek/Kartograf), i pomiarowych
IMGW-PIB (stany wody, przepływy, opad, temperatura), które zapisuje
[IMGWTools](https://github.com/Daldek/IMGWTools): przegląd i wyszukiwanie
archiwum, mapa z podglądami i stacjami, sprawdzanie dostępności
i aktualności danych dla zaznaczonego obszaru, pobieranie i projekty
(manifest `kartograf-project/1`) oraz przygotowanie danych do łączenia
(mozaiki, zestawienie PL + CZ, zestaw do QGIS, porównanie wersji).

Archiwista nie ma własnego mechanizmu pobierania ani obróbki: każde działanie
na danych, także pobranie, wykonuje publiczne API producenta — Kartografa albo IMGWTools —
a źródłem prawdy są pliki w magazynie (sidecary `kartograf-meta/1`
i `imgw-meta/1`) i manifesty projektów. Archiwista trzyma tylko lokalny
indeks i podglądy, które można w każdej chwili odbudować.

**Status:** wydanie **0.1.0 „Przeglądarka”** (2026-10-19) — lokalna
przeglądarka magazynu Kartografa, tylko do odczytu: indeks, widoki „Mapa”,
„Katalog”, „Karta pliku”, „Projekty” (podgląd) i „Magazyn”, wiersz poleceń
oraz API HTTP dla skryptów i agentów. Zmiany: [`docs/CHANGELOG.md`](docs/CHANGELOG.md).
Następne wersje: v0.2 „Podglądy” (podglądy plików, Wachlarz, dane własne
projektu), v0.3 „Działania” (dostępność u źródła, pobieranie i akcje
projektów przez API Kartografa), v0.4 „Zespół”, v0.5 „Stacje IMGW”,
v0.6 „PL + CZ”; MVP to v1.0 ([`docs/SCOPE.md`](docs/SCOPE.md)). Producentem
danych jest repozytorium Kartografa — Archiwista korzysta wyłącznie z jego
publicznego API. Architektura: Python + FastAPI, interfejs Preact + htm bez
kroku budowania, MapLibre GL.

## Instalacja

Wymagania: Linux (sprawdzone na Debianie 13), Python 3.13 (pakiet wymaga
≥ 3.12; `requirements.lock` przypina środowisko 3.13) i repozytorium
Kartografa obok repozytorium Archiwisty (`../Kartograf`). Archiwista 0.1.0
potrzebuje Kartografa 0.8.0 z publicznym API odczytu magazynu (KA-1..KA-6,
[`docs/SPEC.md`](docs/SPEC.md) 12.1). To API jest dziś na gałęzi
Kartografa `feat/archiwista-store-api`, więc do czasu wydania Kartografa
z tym API instaluje się tę gałąź edytowalnie:

```bash
git -C ../Kartograf switch feat/archiwista-store-api
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps -e ../Kartograf
.venv/bin/python -m pip install --no-deps -e ".[dev]"
.venv/bin/archiwista doctor
```

Plik `requirements.lock` przypina pakiety zewnętrzne (Archiwista z `[dev]`
i Kartograf 0.8.0) wraz z sumami sha256, więc pip instaluje je w trybie
`--require-hashes`. Kartograf i Archiwista nie są w nim zapisane: instalują
się potem edytowalnie z `--no-deps`, a ścieżka do Kartografa nie jest
zależnością pakietu. Testy interfejsu potrzebują jeszcze przeglądarki
Playwright: `.venv/bin/python -m playwright install chromium`.

## Uruchomienie

```bash
.venv/bin/archiwista serve
```

Serwer słucha wyłącznie na `127.0.0.1` (port 8090 z ustawienia `port`;
`--port N` zmienia go na jedno uruchomienie, `--port 0` wybiera wolny),
wypisuje jednorazowy adres `http://127.0.0.1:8090/#token=…` (ważny 10 minut,
działa raz) i otwiera go w przeglądarce; `--no-browser` tylko go wypisuje.
Przy pierwszym uruchomieniu otwiera się kreator: katalog Kartografa (jego
`--output`, czyli katalog `data/`), opcjonalnie katalogi projektów i tryb
offline. Po zapisie serwer od razu indeksuje magazyn w tle, a postęp
pokazuje pasek nad widokami. `Ctrl+C` zatrzymuje serwer.

Sesja przeglądarki wygasa po 24 godzinach bez użycia i kończy się wraz
z zatrzymaniem serwera; nowy adres sesji wystawia `archiwista token`. Opis
widoków: [`docs/USAGE.md`](docs/USAGE.md).

## Diagnostyka

`archiwista doctor` sprawdza plik ustawień, wtyczkę Kartografa (wersja
i schematy `kartograf-meta/1`, `kartograf-project/1`), każdy magazyn
i katalog projektów, katalog danych lokalnych (prawo zapisu, dostęp innych
kont) i wolny port. Każdy problem ma opis naprawy po polsku, np. polecenie
instalacji brakującego pakietu.

## Wiersz poleceń

| Polecenie | Co robi |
|---|---|
| `archiwista serve` | serwer i interfejs w przeglądarce |
| `archiwista doctor` | diagnostyka instalacji |
| `archiwista status` | wersje, źródła danych, indeks i magazyny (jak `GET /api/v1/health`) |
| `archiwista sources` | wtyczki producentów i ich stan |
| `archiwista search [ZAPYTANIE] [opcje]` | wyszukiwanie w katalogu; opcje mają nazwy parametrów `GET /api/v1/slots` |
| `archiwista entry MAGAZYN SLOT`, `archiwista version MAGAZYN WERSJA` | karta pliku i karta jednej wersji |
| `archiwista projects`, `archiwista project PROJEKT` | projekty i karta projektu |
| `archiwista reindex [--store MAGAZYN]` | przebudowa indeksu: pełny skan na pierwszym planie |
| `archiwista token [--json \| --revoke-all]` | jednorazowy adres sesji (np. dla agenta) albo koniec wszystkich sesji agentów |
| `archiwista users`, `groups`, `share`, `state export` / `state import` | konta, grupy, widoczność projektów, kopia bazy stanu |

Polecenia odczytu (`status`, `sources`, `search`, `entry`, `version`,
`projects`, `project`) działają bez uruchomionego serwera, bo czytają lokalny
indeks tymi samymi usługami co API. Z opcją `--json` wypisują na stdout
wyłącznie JSON o schemacie odpowiedzi API (błąd: problem RFC 9457 i kod
wyjścia `1`), a tekst po polsku — na stderr. Skrypty i agenci AI:
[`docs/AGENT_API.md`](docs/AGENT_API.md) (sesja HTTP, filtry,
stronicowanie, zadania w tle, błędy). Pełny schemat API jest pod
`/api/v1/openapi.json`, a dokumentacja interaktywna pod `/api/docs`
uruchomionego serwera.

## Gdzie są dane

Archiwista nie zapisuje niczego w magazynie Kartografa ani w katalogach
projektów. Ustawienia i dane lokalne leżą na koncie użytkownika (na Linuksie
poniżej; dokładne ścieżki wypisuje `archiwista doctor`):

| Co | Gdzie | Odtwarzalne |
|---|---|---|
| ustawienia `config.toml` | `~/.config/archiwista/` | kreator albo widok „Ustawienia” |
| indeks `index.sqlite` | `~/.local/share/archiwista/` | tak — `archiwista reindex` |
| baza stanu `state.sqlite`: konta, grupy, udostępnienia projektów, dziennik uprawnień | `~/.local/share/archiwista/` | **nie** — kopia: `archiwista state export`, odtworzenie: `state import` |
| `cache/` — granice jednostek (TERYT, KU) pobrane przez wtyczkę | `~/.local/share/archiwista/` | tak, z sieci |
| `jobs/` — dzienniki zadań w tle (90 dni, najwyżej 1 GB) | `~/.local/share/archiwista/` | nie są potrzebne do pracy |
| `areas/` — kopie wczytanych plików obszarów | `~/.local/share/archiwista/` | wczytanie pliku od nowa |

Katalog danych lokalnych ma prawa `0700`, a polecenia `archiwista` działają
z `umask 077` — inne konta komputera nie czytają indeksu ani bazy stanu.

## Testy i bramka

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy archiwista/ tests/
.venv/bin/python -m pytest
```

`pytest` domyślnie pomija testy `live`, `perf` i `smb` (prawdziwe magazyny,
magazyn 50 000 slotów, udział SMB 3), uruchamia testy interfejsu w Chromium
i wymaga 80% pokrycia. Pomiary i ich metoda:
[`docs/reports/v0.1-measurements.md`](docs/reports/v0.1-measurements.md).

## Dokumentacja

| Dokument | Zawartość |
|---|---|
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | zmiany w kolejnych wydaniach |
| [`docs/USAGE.md`](docs/USAGE.md) | widoki v0.1 dla użytkownika: kreator, Mapa, Katalog, Karta pliku, Projekty, Magazyn |
| [`docs/AGENT_API.md`](docs/AGENT_API.md) | API HTTP i CLI `--json` dla skryptów i agentów AI |
| [`docs/PRD.md`](docs/PRD.md) | wymagania produktu: problem, odbiorcy, wymagania funkcjonalne i niefunkcjonalne, miary sukcesu, otwarte decyzje |
| [`docs/SCOPE.md`](docs/SCOPE.md) | zakres: MVP, poza zakresem, etapy z bramkami, zależności od producentów, ryzyka |
| [`docs/SPEC.md`](docs/SPEC.md) | specyfikacja szczegółowa: przypadki użycia, model danych i indeks (także dane IMGW), architektura, interfejs, łączenie danych, API HTTP, bezpieczeństwo, wymagania wobec Kartografa i IMGWTools, roadmapa z kryteriami akceptacji, ryzyka, pytania otwarte |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | architektura kodu Archiwisty (stan 0.1.0): moduły, przepływy danych, granice; kontrakt formatu magazynu opisuje `docs/ARCHITECTURE.md` Kartografa |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | decyzje (ADR) |
| [`docs/PLAN_v0.1.md`](docs/PLAN_v0.1.md) | plan implementacji v0.1: umowy między krokami, kroki z odbiorem, bramka |
| [`docs/reports/v0.1-measurements.md`](docs/reports/v0.1-measurements.md) | pomiary wydajności, odbiór v0.1 i bramka wydania |
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | stan prac i sprawy otwarte |
| [`docs/DEVELOPMENT_STANDARDS.md`](docs/DEVELOPMENT_STANDARDS.md) | standardy kodowania: język, nazewnictwo, formatowanie, testy, git |
| `mockup/` | klikalny mockup interfejsu do decyzji przed implementacją (uruchomienie: `mockup/README.md`) |

Archiwista zastępuje podprojekt 5 roadmapy Kartografa („GUI webowe”);
wtyczka QGIS (podprojekt 4) pozostaje w repozytorium Kartografa.

## Współtworzenie

Zasady i umowa licencyjna kontrybutora (CLA):
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licencja

MIT — szczegóły w pliku [`LICENSE`](LICENSE).

## Autor

[Piotr de Bever](https://www.linkedin.com/in/piotr-de-bever/)
