# Dziennik zmian

Istotne zmiany Archiwisty w kolejnych wydaniach. Format wzorowany na
[Keep a Changelog](https://keepachangelog.com/pl/1.1.0/), numery wersji
według [SemVer](https://semver.org/lang/pl/). Do v1.0 API HTTP i polecenia
wiersza poleceń mogą się zmieniać.

## [Unreleased]

### Zmieniono

- Dokumentacja ma angielskie nazwy plików (treść po polsku, jak
  w Kartografie i IMGWTools): `docs/USAGE.md` (dawniej
  `Przewodnik_uzytkownika.md`), `docs/AGENT_API.md` (dawniej
  `API_dla_agentow.md`), `docs/IMGWTOOLS_REQUIREMENTS.md` (dawniej
  `wymagania-imgwtools.md`), `docs/reports/v0.1-measurements.md` ze zrzutami
  w `docs/reports/v0.1-screenshots/` (dawniej `docs/raporty/`), a dziennik
  zmian przeszedł do `docs/CHANGELOG.md`.

## [0.1.0] — 2026-10-19 — „Przeglądarka”

Pierwsze wydanie: lokalna przeglądarka magazynu Kartografa, tylko do
odczytu. Wymaga Kartografa 0.8.0 z publicznym API odczytu magazynu
(KA-1..KA-6, `docs/SPEC.md` 12.1) — dziś z gałęzi
`feat/archiwista-store-api` repozytorium Kartografa (instalacja: `README.md`).

### Dodano

- **Serwer i pierwsze uruchomienie.** `archiwista serve` na `127.0.0.1`
  (domyślnie port 8090) wypisuje i otwiera jednorazowy adres sesji;
  kreator pierwszego uruchomienia: magazyny Kartografa, katalogi
  projektów, tryb offline; widok „Ustawienia” z tym samym formularzem.
- **Lokalny indeks** (SQLite, odtwarzalny): pełny i przyrostowy skan
  magazynu, odświeżenie slotów zaznaczonego obszaru, skany z harmonogramu
  (dysk lokalny co 5 min, udział co 15 min) i pełny skan kontrolny co 24 h
  (`full_scan_interval_h`). Na udziale sieciowym skan czyta części
  segmentów w `scan_threads` wątkach, a skan przyrostowy nie listuje
  znanych katalogów wersji. Odłączony udział nie czyści indeksu: wyniki są
  oznaczone jako „z indeksu z <czas>”, a pasek stanu to mówi.
- **Mapa:** obrysy plików i siatka zagęszczenia (ponad 5000 obrysów
  w widoku), obszar jako prostokąt, wielokąt, widok mapy, godło (wpisane
  albo kliknięte w siatce godeł PL-1992 i PL-2000) albo plik (GeoJSON,
  GeoPackage, ZIP z Shapefile); wybór produktu i filtry; stan lokalny
  obszaru („lokalnie 83% obszaru”) liczony w układzie płaskim kraju
  (EPSG:2180, EPSG:5514); domyślny szary podkład BKG TopPlusOpen.
- **Katalog:** wyszukiwanie po godle, TERYT, KU, nazwie pliku, etykiecie
  wersji, numerze zgłoszenia i początku SHA-256 (`Ctrl+K` albo `/`
  z każdego widoku); filtry zapisane w adresie strony; stronicowanie
  kursorem; grupy położenia z licznikami i grupa „bez położenia”; wpisy
  każdej zarejestrowanej wtyczki źródła obok wpisów Kartografa.
- **Karta pliku:** oś wszystkich wersji z bieżącą i pełnym arkuszem
  (`full_sheet/`), rok danych odróżniony od daty pobrania, metadane po
  ludzku obok wartości technicznych, licencja z kopiowaniem atrybucji,
  ścieżki wersji i ścieżka standardowa do skopiowania (także pod innymi
  literami dysków), przypięcia w projektach, pliki tego samego zapytania
  producenta, surowy sidecar i potwierdzenie bieżącej wersji treścią.
- **Projekty** (podgląd): manifesty `kartograf-project.json` z katalogów
  projektów, zadania z poleceniami producenta, przypięte i brakujące
  wersje, stan teraz od producenta (bez sieci).
- **Magazyn:** stan i źródło danych, ostatni skan i ostatni pełny skan,
  przyciski „Odśwież”, „Pełny skan” i „Uzupełnij obrysy jednostek”,
  zajętość według produktów (każda wersja liczona raz), raport wersji
  niebieżących i nieprzypiętych (bez usuwania), problemy z opisem naprawy,
  projekty korzystające z magazynu.
- **Zadania w tle** w osobnych procesach roboczych: skan, obrysy jednostek
  (TERYT, KU — z sieci), potwierdzenie bieżącej wersji; postęp przez SSE ze
  wznowieniem po `Last-Event-ID`; przy zajętym magazynie `409 conflict`
  z trwającym zadaniem.
- **API HTTP `/api/v1`:** stan (`/health`, `/sources`, `/stores`), katalog
  (`/slots`, `/products`), karty slotu i wersji z sidecarem, pliki
  zgłoszenia (`/requests/{parent_request}`), mapa (`/map/footprints`,
  `/map/sheets`), obszary i pokrycie lokalne (`/areas`, `/local-coverage`),
  projekty, ustawienia, zadania; błędy RFC 9457 ze stałym `code`
  i polskim `detail`; dokument OpenAPI z przykładami i lokalne `/api/docs`.
- **Wiersz poleceń:** `doctor`, `status`, `sources`, `search`, `entry`,
  `version`, `projects`, `project` z `--json` o schemacie odpowiedzi API,
  `reindex`, `token` dla sesji agenta.
- **Uprawnienia** (A-ADR-029): lokalna baza stanu (konta, grupy,
  udostępnienia, dziennik zmian), role `admin` i `store_writer`,
  widoczność projektów `public` / `users` / `group` / `private`
  w usługach, API i CLI; polecenia `users`, `groups`, `share`,
  `state export` / `state import` i ich trasy HTTP.
- **Wtyczki źródeł** (A-ADR-024): adaptery z entry points
  `archiwista.sources`, adapter Kartografa, stany źródeł; brak albo
  niezgodna wersja producenta to `503 source_unavailable` /
  `source_incompatible` z opisem naprawy, nie awaria serwera.
- Dokumentacja: `docs/USAGE.md` (widoki),
  `docs/AGENT_API.md` (skrypty i agenci AI),
  `docs/reports/v0.1-measurements.md` (pomiary i odbiór).

### Bezpieczeństwo

- Serwer odmawia startu poza `127.0.0.1`, przyjmuje tylko nagłówek `Host`
  `127.0.0.1:<port>` albo `localhost:<port>` i nie ma CORS.
- Jednorazowy token we fragmencie adresu (start 10 min, agent 5 min;
  w indeksie tylko skrót SHA-256), przeglądarka dostaje adres przez
  prywatny plik `0600`, nie przez wiersz poleceń.
- Sesja w ciasteczku `HttpOnly`, `SameSite=Strict` i token CSRF
  w nagłówku `X-Archiwista-CSRF` w każdym żądaniu `/api`, także odczycie;
  reguły `Origin` i `Sec-Fetch-Site`; `DELETE /api/v1/session` kończy sesję.
- Role i grupy czytane przy każdym żądaniu: odebranie roli działa od razu,
  wyłączone albo usunięte konto kończy swoje sesje; sesja agenta trwa
  najwyżej 12 h, a `archiwista token --revoke-all` kończy wszystkie.
- Limity treści żądań (4 KiB wymiana tokenu, 1 MiB pozostałe, 50 MB plik
  obszaru), pliki obszarów czytane w procesie z limitem czasu i bez
  pobierania układów współrzędnych z sieci.
- Pliki otwierane tylko pod ścieżkami z indeksu w korzeniach magazynów;
  manifest projektu wskazujący poza katalog projektów nie jest czytany.
- CSP liczona z ustawień, `Referrer-Policy: no-referrer`,
  `X-Content-Type-Options: nosniff`; biblioteki interfejsu dołączone do
  pakietu (bez CDN) z sumami sha256 sprawdzanymi w testach;
  `requirements.lock` z sumami sha256.
- Dane lokalne prywatne: katalog `0700`, `umask 077`; `archiwista doctor`
  ostrzega przed dostępem innych kont.

### Wydajność

Cele SPEC 4.5 spełnione na magazynie syntetycznym 50 000 slotów przez
prawdziwy `archiwista serve` (SSD — pomiar na kodzie wydania, SMB 3 —
przebieg 3): pierwszy pełny skan 48,3 s na SSD i 225,6 s na udziale;
skan przyrostowy 12,4 s i 74,7 s; odświeżenie widoku (p95) 408 ms
i 1,83 s; lista, wyszukiwanie i karta najwyżej 143 ms (p95, próg 200 ms),
obrysy 198 ms (próg 300 ms); szczyt RSS serwera 168–179 MiB przy indeksie
256 MB. Metoda i wszystkie liczby: `docs/reports/v0.1-measurements.md`.

### Znane ograniczenia

- Tylko tryb lokalny: jedna osoba na `127.0.0.1`, bez logowania (zespół —
  v0.4).
- Bez pobierania, podglądów, porównań, sprawdzania dostępności u źródła
  i zmian projektów — od v0.2 i v0.3.
- API odczytu magazynu Kartografa nie jest jeszcze w wydaniu Kartografa
  z tagiem: wymaga gałęzi `feat/archiwista-store-api`.
- Płynność mapy z 5000 obrysów (≥ 30 klatek/s, kryterium v0.2) nie jest
  zmierzona na komputerze z GPU; bez GPU (WebGL programowy) 8–9 klatek/s.
- Sprawdzone na Linuksie (Debian 13, Python 3.13); Windows i instalacja
  przez `pipx` albo `uv tool` — v1.0.
