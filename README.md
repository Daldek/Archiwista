# Archiwista

Archiwista to aplikacja webowa do pracy z magazynem danych: przestrzennych,
które tworzy [Kartograf](https://github.com/Daldek/Kartograf), i pomiarowych
IMGW-PIB (stany wody, przepływy, opad, temperatura), które zapisuje
[IMGWTools](https://github.com/Daldek/IMGWTools): przegląd i wyszukiwanie
archiwum, mapa z podglądami i stacjami, sprawdzanie dostępności
i aktualności danych dla zaznaczonego obszaru, pobieranie i projekty
(manifest `kartograf-project/1`) oraz przygotowanie danych do łączenia
(mozaiki, zestawienie PL + CZ, zestaw do QGIS, porównanie wersji).

Archiwista nie pobiera ani nie przetwarza danych sam: każde działanie na
danych wykonuje publiczne API producenta — Kartografa albo IMGWTools —
a źródłem prawdy są pliki w magazynie (sidecary `kartograf-meta/1`
i `imgw-meta/1`) i manifesty projektów. Archiwista trzyma tylko lokalny
indeks i podglądy, które można w każdej chwili odbudować.

**Status:** specyfikacja — w repozytorium nie ma jeszcze kodu aplikacji.

| Dokument | Zawartość |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | specyfikacja: cel, przypadki użycia, model danych i indeks (także dane IMGW), architektura, interfejs, łączenie danych, API HTTP, bezpieczeństwo, wymagania wobec Kartografa i IMGWTools, roadmapa, ryzyka, pytania otwarte |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | decyzje architektoniczne (ADR) |
| `mockup/` (gałąź `feat/mockup`) | klikalny mockup interfejsu do decyzji przed implementacją |

Archiwista zastępuje podprojekt 5 roadmapy Kartografa („GUI webowe”);
wtyczka QGIS (podprojekt 4) pozostaje w repozytorium Kartografa.
