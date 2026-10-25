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

**Status:** wydanie **0.2.0 „Podglądy”** (2026-10-20) — lokalny indeks,
mapa i katalog magazynu Kartografa, podglądy plików, Wachlarz i Oś czasu,
porównanie z kurtyną oraz dane własne projektu i migawki. Magazyn
producenta pozostaje tylko do odczytu. Zmiany: [`docs/CHANGELOG.md`](docs/CHANGELOG.md).
Następne wersje: v0.3 „Działania” (dostępność u źródła, pobieranie i akcje
projektów przez API Kartografa), v0.4 „Zespół”, v0.5 „Stacje IMGW”,
v0.6 „PL + CZ”; MVP to v1.0 ([`docs/SCOPE.md`](docs/SCOPE.md)). Archiwista
korzysta wyłącznie z publicznego API producenta. Architektura: Python
i FastAPI, interfejs Preact + htm bez budowania, MapLibre GL.

## Instalacja

Wymagania: Linux (sprawdzone na Debianie 13), Python ≥ 3.12 i [uv](https://docs.astral.sh/uv/).
Archiwista 0.2.0 wymaga Kartografa 0.8.0 z publicznym API odczytu magazynu
(KA-1..KA-6, [`docs/SPEC.md`](docs/SPEC.md) 12.1). To API jest na `develop`
Kartografa, a `pyproject.toml` przypina jego commit (REL-5.3) do czasu tagu
`v0.8.0`; `uv.lock` przypina wszystkie pakiety z sumami sha256:

```bash
uv sync --locked                      # środowisko w .venv z uv.lock
uv run playwright install chromium    # raz: przeglądarka testów interfejsu
uv run archiwista doctor
```

Pakiety podglądów (`rio-tiler`, rasterio, pyogrio, laspy z lazrs) są w
`uv.lock`; pliki renderują odizolowane procesy, nie serwer.
Pierwszy start po aktualizacji z 0.1 przebudowuje lokalny indeks
(`SCHEMA_VERSION = 6`) i wykonuje pełny skan: przy odłączonym magazynie
zaczekaj z aktualizacją lub udostępnij go ponownie przed skanem.

## Uruchomienie

```bash
uv run archiwista serve
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
| `archiwista preview REF [--build] [--output PLIK.png]`, `compare REF REF` | podgląd i porównanie metadanych |
| `archiwista layers --store ID --product NAZWA [--area-id ID] [--thumbnail KLUCZ --output PLIK.png]` | lata i kampanie z lokalnych warstw |
| `archiwista files PROJEKT`, `file PROJEKT PLIK`, `own-scan [--project PROJEKT]` | lista, karta i skan danych własnych |
| `archiwista snapshot PROJEKT PLIK [--plan \| --note TEKST]` | plan i migawka w folderze projektu |

Polecenia odczytu działają bez uruchomionego serwera, bo korzystają
z lokalnego indeksu i wspólnych usług; budowa podglądu, skan danych
własnych i migawka wykonują zadania w procesach roboczych na pierwszym
planie w CLI, a w serwerze — jako zadania w tle. Z opcją `--json`
wypisują na stdout wyłącznie JSON o schemacie odpowiedzi API (błąd: nic na
stdout, ostatni wiersz stderr to dokument `archiwista-error/1`, kod wyjścia
z rejestru błędów Nogat), a tekst po polsku — na stderr. Skrypty
i agenci AI:
[`docs/AGENT_API.md`](docs/AGENT_API.md) (sesja HTTP, filtry,
stronicowanie, zadania w tle, błędy). Pełny schemat API jest pod
`/api/v1/openapi.json`, a dokumentacja interaktywna pod `/api/docs`
uruchomionego serwera.

Dziennik (logi i postęp) idzie na stderr, nigdy na stdout. Poziom ustawia
`--verbose` (debug) albo `--quiet` (tylko błędy), przed nazwą polecenia lub po
niej, a bez nich zmienna `ARCHIWISTA_LOG_LEVEL` (`debug`, `info`, `warning`,
`error`; domyślnie `warning`); czytają ją też procesy zadań i podglądów.

## Gdzie są dane

Archiwista nie zapisuje niczego w magazynie Kartografa. Lokalny indeks
i pamięć podglądów leżą na koncie użytkownika; jedyny zapis poza nimi,
na polecenie osoby z `project.write`, to migawki w folderze danych projektu
(`<katalog projektu>/dane/.wersje/` domyślnie). Folder danych jest indeksowany
tylko do odczytu. Ścieżki lokalne poniżej wypisuje też `archiwista doctor`:

| Co | Gdzie | Odtwarzalne |
|---|---|---|
| ustawienia `config.toml` | `~/.config/archiwista/` | kreator albo widok „Ustawienia” |
| indeks `index.sqlite` | `~/.local/share/archiwista/` | tak — `archiwista reindex` |
| baza stanu `state.sqlite`: konta, grupy, udostępnienia projektów, dziennik uprawnień | `~/.local/share/archiwista/` | **nie** — kopia: `archiwista state export`, odtworzenie: `state import` |
| `cache/` — granice jednostek (TERYT, KU) pobrane przez wtyczkę | `~/.local/share/archiwista/` | tak, z sieci |
| `jobs/` — dzienniki zadań w tle (90 dni, najwyżej 1 GB) | `~/.local/share/archiwista/` | nie są potrzebne do pracy |
| `areas/` — kopie wczytanych plików obszarów | `~/.local/share/archiwista/` | wczytanie pliku od nowa |
| `previews/` — miniatury, kafle, lokalne COG i rozliczenie LRU `cache.sqlite` | `~/.local/share/archiwista/` | tak, pamięć po treści, limit domyślnie 20 GB |
| `<folder danych>/.wersje/` — spójne migawki z `migawka.json` | katalog projektu wskazany przez użytkownika | **nie** — kopiuj razem z projektem |

Katalog danych lokalnych ma prawa `0700`, a polecenia `archiwista` działają
z `umask 077` — inne konta komputera nie czytają indeksu ani bazy stanu.

## Testy i bramka

```bash
scripts/gate.sh    # ruff format, ruff check, mypy, pytest z pokryciem, sprawdzenie commitów
```

Bramka (DEV-7.6) działa z katalogu roboczego git i stosuje `uv sync --locked --all-extras`;
współtwórcy uruchamiają ją jako `GATE_CHECK_AUTHOR=0 scripts/gate.sh`.

`pytest` domyślnie pomija testy `live`, `perf` i `smb` (prawdziwe magazyny,
magazyn 50 000 slotów, udział SMB 3), uruchamia testy interfejsu w Chromium
i wymaga 80% pokrycia. Pomiary i ich metoda:
[`docs/reports/v0.1-measurements.md`](docs/reports/v0.1-measurements.md)
i [`docs/reports/v0.2-measurements.md`](docs/reports/v0.2-measurements.md).

## Dokumentacja

| Dokument | Zawartość |
|---|---|
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | zmiany w kolejnych wydaniach |
| [`docs/USAGE.md`](docs/USAGE.md) | widoki v0.2: podglądy, Wachlarz, Oś czasu, porównanie, projekty i migawki |
| [`docs/AGENT_API.md`](docs/AGENT_API.md) | API HTTP i CLI `--json` dla skryptów i agentów AI |
| [`docs/PRD.md`](docs/PRD.md) | wymagania produktu: problem, odbiorcy, wymagania funkcjonalne i niefunkcjonalne, miary sukcesu, otwarte decyzje |
| [`docs/SCOPE.md`](docs/SCOPE.md) | zakres: MVP, poza zakresem, etapy z bramkami, zależności od producentów, ryzyka |
| [`docs/SPEC.md`](docs/SPEC.md) | specyfikacja szczegółowa: przypadki użycia, model danych i indeks (także dane IMGW), architektura, interfejs, łączenie danych, API HTTP, bezpieczeństwo, wymagania wobec Kartografa i IMGWTools, roadmapa z kryteriami akceptacji, ryzyka, pytania otwarte |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | architektura kodu Archiwisty 0.2.0; kontrakt formatu magazynu opisuje `docs/ARCHITECTURE.md` Kartografa |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | decyzje (ADR) |
| [`docs/PLAN_v0.1.md`](docs/PLAN_v0.1.md) | plan implementacji v0.1: umowy między krokami, kroki z odbiorem, bramka |
| [`docs/reports/v0.1-measurements.md`](docs/reports/v0.1-measurements.md) | pomiary wydajności, odbiór v0.1 i bramka wydania |
| [`docs/PLAN_v0.2.md`](docs/PLAN_v0.2.md), [`docs/reports/v0.2-measurements.md`](docs/reports/v0.2-measurements.md) | wykonanie i pomiary v0.2 |
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
