# Jak współtworzyć Archiwistę

Dziękujemy za zainteresowanie Archiwistą! Mile widziane są wszystkie rodzaje
wkładu: zgłoszenia błędów, uwagi do specyfikacji, poprawki, nowe funkcje
i dokumentacja.

## Stan projektu

Archiwista jest na etapie specyfikacji: w repozytorium nie ma jeszcze kodu
aplikacji. Najcenniejsze są teraz uwagi do dokumentów:

- [`docs/PRD.md`](docs/PRD.md) — wymagania produktu,
- [`docs/SCOPE.md`](docs/SCOPE.md) — zakres i etapy,
- [`docs/SPEC.md`](docs/SPEC.md) — szczegółowa specyfikacja,
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — decyzje (ADR).

Kod powstaje dopiero po zatwierdzeniu specyfikacji i planu (kolejność:
spec → plan → implementacja).

## Zasady

- **Granice projektu.** Archiwista nie ma własnego mechanizmu pobierania ani
  obróbki danych: zleca je producentom magazynu (Kartograf, IMGWTools) przez publiczne
  API. Brakująca funkcja producenta to wymaganie wobec niego
  (`docs/SPEC.md`, sekcja 12), a nie obejście w Archiwiście.
- **Język.** Dokumentacja i teksty interfejsu po polsku; docstringi
  i komentarze po angielsku; identyfikatory (API HTTP, klucze JSON, nazwy
  w kodzie) po angielsku.
- **Commity.** [Conventional Commits](https://www.conventionalcommits.org/)
  z opisem po polsku, np. `docs(spec): doprecyzowanie etykiet pokrycia`.
- **Gałęzie.** Pull requesty do `develop`; jedna sprawa na pull request.
- **Dane.** Żadnych danych pobranych w trakcie pracy w repozytorium;
  w dokumentach ścieżki danych zapisuj jako `<katalog-danych>`.

## Umowa licencyjna kontrybutora (CLA)

Zanim pierwszy wkład zostanie scalony, prosimy o podpisanie **umowy
licencyjnej kontrybutora** (Contributor License Agreement). W skrócie:

- **Czym jest.** Krótka umowa, w której potwierdzasz, że jesteś autorem
  wkładu (albo masz prawo go przekazać) i udzielasz praw potrzebnych do jego
  używania i rozpowszechniania. Pełny tekst (po angielsku, adaptacja Apache
  ICLA 2.2): [`docs/CLA.md`](docs/CLA.md).
- **Dlaczego jest wymagana.** Utrzymuje licencję projektu na pewnych
  podstawach prawnych i zachowuje możliwość zmiany licencji w przyszłości.
  Bez niej jeden wkład o niejasnych prawach mógłby taką zmianę zablokować.
- **Twój wkład pozostaje na MIT.** Podpisanie CLA **nie** zmienia licencji:
  projekt jest i pozostaje na [licencji MIT](LICENSE), tak jak Twój wkład.
- **Podpis to jeden komentarz — proces jest ręczny.** Bez bota i formularza.
  Gdy pull request jest gotowy, dodaj pod nim komentarz o dokładnie takiej
  treści:

  > I have read the CLA document and hereby sign it.

  Przy scalaniu pull requestu opiekun zapisuje Twój podpis — login GitHub,
  datę i numer pull requestu — w [`CONTRIBUTORS.md`](CONTRIBUTORS.md).
  Podpisujesz raz; podpis obejmuje też przyszłe wkłady.

  Zaznacz też pole CLA w szablonie pull requestu.

## Zgłaszanie problemów

Błąd albo pomysł na funkcję? Otwórz zgłoszenie (issue) w repozytorium
projektu na GitHubie i podaj jak najwięcej szczegółów: kroki do odtworzenia,
oczekiwane i faktyczne zachowanie, środowisko (system, wersje Archiwisty,
Kartografa i IMGWTools).
