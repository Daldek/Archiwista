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

**Status:** wdrażanie v0.1: dostępny jest pakiet, interfejs źródeł i pomoc CLI;
widoki, indeks i działające komendy pojawią się w kolejnych krokach planu.
Zakres pierwszego wydania (MVP, v1.0): przeglądanie magazynu, podglądy,
działania (dostępność, pobieranie, aktualność, projekty), tryb zespołu i dane
IMGW; zestaw do QGIS, asystent i łączenie danych — po MVP. Architektura
przyjęta (2026-10-18): Python + FastAPI, interfejs Preact + htm, MapLibre GL.

## Instalacja deweloperska (krok 1)

Wymagany jest Python 3.12+ i sąsiednie repozytorium Kartografa z gałęzią
`feat/archiwista-store-api` (albo z jej zmianami już scalonymi):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ../Kartograf
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/archiwista --help
```

Plik `requirements.lock` przypina pakiety środowiska Python 3.13; instalacja
lokalnego Kartografa pozostaje edytowalna, a ścieżka do niego nie jest
zależnością pakietu wydania. W kroku 1 komenda udostępnia tylko pomoc — nie
uruchamia jeszcze serwera ani skanu. Dodatek `archiwista[imgw]` powstanie
dopiero w v0.5.

| Dokument | Zawartość |
|---|---|
| [`docs/PRD.md`](docs/PRD.md) | wymagania produktu: problem, odbiorcy, wymagania funkcjonalne i niefunkcjonalne, miary sukcesu, otwarte decyzje |
| [`docs/SCOPE.md`](docs/SCOPE.md) | zakres: MVP, poza zakresem, etapy z bramkami, zależności od producentów, ryzyka |
| [`docs/SPEC.md`](docs/SPEC.md) | specyfikacja szczegółowa: przypadki użycia, model danych i indeks (także dane IMGW), architektura, interfejs, łączenie danych, API HTTP, bezpieczeństwo, wymagania wobec Kartografa i IMGWTools, roadmapa z kryteriami akceptacji, ryzyka, pytania otwarte |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | decyzje (ADR) |
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
