# Instrukcje dla Claude Code

Archiwista to aplikacja webowa (lokalnie: jedna osoba na `localhost`,
pozniej zespol w sieci lokalnej) do pracy z magazynem danych przestrzennych
Kartografa: przeglad, wyszukiwanie, mapa i podglady, sprawdzanie dostepnosci
i aktualnosci, pobieranie i projekty przez API Kartografa, przygotowanie
danych do laczenia. Wprowadzenie: `README.md`; specyfikacja: `docs/SPEC.md`.

## Zasady pracy (krytyczne)

- Stan: specyfikacja. Kod powstaje dopiero po zatwierdzeniu specu i planu
  (kolejnosc jak w Kartografie: spec -> plan -> implementacja).
- Kartograf jest zaleznoscia: wylacznie publiczne API
  (`kartograf/__init__.py`, `__all__`). Archiwista nie ma wlasnej logiki
  pobierania ani obrobki danych; brak funkcji w Kartografie = wymaganie
  wobec Kartografa (SPEC sekcja 12), nie obejscie w Archiwiscie.
- Magazyn Kartografa jest dla Archiwisty tylko do odczytu: zapis wylacznie
  przez API Kartografa. Zadnej bazy SQLite ani plikow Archiwisty na udziale
  sieciowym ani w magazynie; indeks, cache podgladow i historia zadan leza
  lokalnie i mozna je odbudowac. Jedyny wyjatek: dane uzytkownika zapisywane
  na jego polecenie w katalogu projektu (migawki danych wlasnych, pliki
  obszarow, zestawy; A-ADR-027) - otwarty format, czytelny bez Archiwisty.
- Nadrzedna zasada produktowa: uklad, interfejs i API proste, zrozumiale
  i wygodne dla ludzi.
- Dane pobierane w trakcie pracy: poza repo i poza `/tmp`, zawsze jawny
  katalog; w dokumentach sciezki danych zapisuj jako `<katalog-danych>`.
- Python wylacznie z `.venv` (gdy powstanie kod).
- Git: praca na `develop` albo na krotkotrwalej galezi z `develop`;
  Conventional Commits z opisem po polsku; autor `Daldek <git@debever.pl>`,
  bez stopki `Co-Authored-By`; repozytorium bez remote (bez push).
- Jezyk: projekt jest dla polskiego rynku, ale caly kod i to, co go opisuje,
  jest po angielsku: identyfikatory (API HTTP, klucze JSON, nazwy w kodzie),
  docstringi, komentarze, logi, pliki dla kontrybutorow (`CONTRIBUTING.md`,
  `CONTRIBUTORS.md`, szablon PR). Po polsku: dokumentacja projektu (`docs/`,
  `README.md`), teksty interfejsu, opisy commitow. Szczegoly:
  `docs/DEVELOPMENT_STANDARDS.md` sekcja 0.
- `docs/DECISIONS.md` ma konce linii LF (inaczej niz w Kartografie).

## Mapa dokumentacji

|Czego szukasz|Gdzie|
|---|---|
|Wymagania produktu (F/N), miary sukcesu, otwarte decyzje|`docs/PRD.md`|
|Zakres MVP, poza zakresem, etapy i bramki, zaleznosci|`docs/SCOPE.md`|
|Cel, uzytkownicy, slownik pojec|`docs/SPEC.md` 1-2|
|Przypadki uzycia i scenariusze|`docs/SPEC.md` 3|
|Model danych, indeks, odswiezanie, SMB|`docs/SPEC.md` 4|
|Architektura (przyjeta 2026-10-18), zadania w tle, podglady|`docs/SPEC.md` 5|
|Interfejs, widoki, etykiety pokrycia|`docs/SPEC.md` 6|
|Agent czatu|`docs/SPEC.md` 7|
|Laczenie danych (4 tryby)|`docs/SPEC.md` 8|
|API HTTP|`docs/SPEC.md` 9|
|Bezpieczenstwo, testy|`docs/SPEC.md` 10-11|
|Wymagania wobec Kartografa|`docs/SPEC.md` 12|
|Roadmapa, ryzyka, pytania otwarte, mockup|`docs/SPEC.md` 13-16|
|Decyzje (ADR)|`docs/DECISIONS.md`|
|Standardy kodowania, jezyk, testy, git|`docs/DEVELOPMENT_STANDARDS.md`|
|Licencja, kontrybucje, CLA|`LICENSE`, `CONTRIBUTING.md`, `docs/CLA.md`|
|Kontrakty formatu na dysku (sidecar, `data/`, manifest, plan)|Kartograf: `docs/ARCHITECTURE.md` 3.1-3.5|
