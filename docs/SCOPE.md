# SCOPE – Archiwista

Oct 17, 2026 · @Piotr

**Status:** szkic do zatwierdzenia · wymagania: [`PRD.md`](PRD.md) ·
szczegóły wersji i kryteria akceptacji: [`SPEC.md`](SPEC.md) sekcja 13 ·
decyzja o zakresie: A-ADR-025 ([`DECISIONS.md`](DECISIONS.md))

## MVP

**MVP = wydanie v1.0** (decyzja użytkownika 2026-10-17). Obejmuje pięć
obszarów:

1. **Przeglądarka** — indeks, mapa, katalog, karta pliku, projekty (podgląd),
   stan magazynu; tylko odczyt.
2. **Podglądy i Wachlarz** — podglądy plików, „Wachlarz” i „Oś czasu” lat,
   porównanie metadanych i kurtyna.
3. **Działania** — dostępność u źródła z etykietami pokrycia, okno planu,
   pobieranie, zadania w tle, aktualność, akcje projektów.
4. **Tryb zespołu** — serwer w sieci lokalnej z logowaniem i rolami.
5. **Dane IMGW** — stacje, pokrycie szeregów, karta stacji, aktualność
   i synchronizacja archiwów, zadania projektu IMGW.

Zestaw do QGIS, asystent i łączenie danych są **po MVP** (v1.1–v1.4).

## W zakresie MVP

- Konfiguracja magazynów (katalog Kartografa i/lub katalog IMGW) i katalogów projektów; kreator pierwszego uruchomienia.
- Lokalny, odtwarzalny indeks: pełny i przyrostowy skan, odświeżanie widoku, widoczny stan indeksu; praca na udziale SMB, także tylko do odczytu.
- Źródła danych jako dodatki: Kartograf wymagany, IMGWTools opcjonalny; brak producenta = „źródło niedostępne”, nie awaria.
- „Mapa” z obrysami, zaznaczaniem obszaru (prostokąt, wielokąt, godło, TERYT, KU, plik, nazwa jednostki) i stanem magazynu dla obszaru.
- „Katalog” z filtrami, wyszukiwaniem po identyfikatorach i grupą danych bez położenia.
- „Karta pliku”: oś wersji, metadane po ludzku, licencja i atrybucja, przypięcia w projektach, ścieżki wersji.
- „Magazyn”: zajętość i problemy z poleceniem naprawy; raport wersji nieużywanych i niebieżących (bez usuwania).
- Podglądy z pamięcią po sumie treści, „Wachlarz”, „Oś czasu”, porównanie metadanych, kurtyna.
- Dane własne projektu (folder danych, domyślnie `<katalog projektu>/dane/`): indeks tylko do odczytu, podgląd, migawki robione przez Archiwistę w `<folder danych>/.wersje/`, wykrywanie zmian od migawki.
- Dostępność u źródła (wysokości PL i CZ; obrazy PL — ortofotomapa, true orto, intensywność; wydania produktów jednostkowych, np. BDOT10k) z etykietami pokrycia i plakietką magazynu.
- „Okno planu”, pobieranie z formularza i z wklejonego polecenia, zadania w tle z postępem i anulowaniem, aktualność i „Pobierz nowsze”.
- Projekty: podgląd, status, weryfikacja, akcje (zadania projektu, pobranie, przepięcie, sprawdzenie aktualizacji).
- Tryb lokalny z ochroną (tylko `127.0.0.1`, CSRF, DNS rebinding, ścieżki).
- Tryb zespołu: logowanie, role, TLS, dziennik działań, wspólna kolejka, limity per osoba, pobieranie plików przez HTTP, aliasy ścieżek.
- Dane IMGW: stacje na mapie i w „Katalogu”, „Zestawienie” z pokryciem szeregów osobno dla każdej zmiennej i w obu rodzajach lat, „Karta stacji” z wykresem, porównanie stacji, aktualność i synchronizacja archiwów, szeregi, zadania projektu IMGW.
- Instalacja na Linuksie i Windows, dokumentacja użytkownika po polsku, audyt WCAG 2.1 AA, przegląd bezpieczeństwa, pomiar wydajności na prawdziwym udziale SMB.

## Poza zakresem MVP

| Element | Status | Powód |
| --- | --- | --- |
| Zestaw do projektu i QGIS (`.qgz`, ścieżki, atrybucje; także z danymi IMGW), PL + CZ bez scalania jako zestaw | v1.1 | decyzja o zakresie MVP |
| „Polecenie Kartografa” i „Dodaj do projektu” z karty pliku (KB-6), „Katalog” jako karty | v1.1 | decyzja użytkownika 2026-10-18: w MVP do projektu dodaje się dane z wyniku dostępności |
| Asystent (agent LLM), także narzędzia IMGW i budżet asystenta per osoba | v1.2 | decyzja o zakresie MVP |
| Mozaika arkuszy, model różnic wersji, zestaw z kopią danych | v1.3 | wymaga KE, KG w Kartografie |
| Scalona powierzchnia PL + CZ | v1.4 | wymaga KF w Kartografie |
| Usuwanie wersji z magazynu | poza zakresem | tylko raport kandydatów; usuwanie — jeśli kiedyś — w Kartografie (SPEC 15 P4) |
| Przypinanie dowolnej starszej wersji wskazanej w przeglądarce | nie w v1.0 | model zadań projektu wybiera wersję opcjami (SPEC 15 P9) |
| Podgląd 3D chmur punktów LAZ | po v1.0 | do rozpoznania wystarcza nagłówek i obraz 2D (SPEC 15 P5) |
| Bezpośrednie LDAP | później | w MVP konta lokalne albo odwrotne proxy (droga do SSO i AD) |
| macOS | bez gwarancji | priorytet: Linux i Windows (SPEC 15 P10) |
| Analizy GIS | poza zakresem | analizy w QGIS |
| Obliczenia hydrologiczne i statystyki szeregów | poza zakresem | Hydrolog i Retman |
| Dane bieżące IMGW (stany, ostrzeżenia) | poza zakresem | tylko archiwa i szeregi z magazynu |
| Własne pobieranie lub obróbka danych | poza zakresem | wyłącznie API producentów; brak funkcji = wymaganie wobec producenta |
| Wtyczka QGIS | poza zakresem | podprojekt 4 roadmapy Kartografa |
| Różnica obiektów między migawkami danych własnych (dodane, usunięte, zmienione) | później | osobna decyzja; w MVP porównanie metadanych i kurtyna |
| Edycja danych i historia pojedynczych obiektów | poza zakresem | Archiwista nie jest edytorem; migawki całych plików |
| Dane własne w manifeście projektu (przypięcia, odtworzenie u kolegi, „Weryfikuj”) | poza zakresem | manifest zapisuje tylko producent; migawki leżą w katalogu projektu i przenoszą się z nim |
| Usuwanie migawek przez Archiwistę | poza zakresem | tylko przyrost; usuwanie ręcznie poza Archiwistą |
| Udostępnianie projektów: właściciele, grupy, widoczność (publiczny, wybrane osoby, wybrana grupa, prywatny), ekran udostępniania, dziennik zmian uprawnień, podglądy i wyszukiwanie z uwzględnieniem uprawnień, opcjonalnie grupy LDAP/AD | v1.5 „Udostępnianie” (propozycja) | A-ADR-029 (proponowana); w MVP tylko przygotowanie: każda usługa i zapytanie przyjmuje `Principal` od v0.1, uprawnienie „zapis do magazynu” (`store_writer`) sprawdzane w v0.3, nadawane osobom w v0.4 |
| Prawa do plików na serwerze i udziale | poza zakresem | Archiwista egzekwuje uprawnienia tylko w swoim interfejsie, API, CLI, tokenach agentów i pamięci podglądów; dostęp do systemu plików to odpowiedzialność administratora serwera (A-ADR-029) |

## Etapy i produkty etapów

Etapy następują po sobie. Każdy kończy się bramką, czyli warunkiem przejścia
dalej. Pełne kryteria akceptacji: SPEC 13.

1. **Etap 0 – Architektura i plan.** Decyzje architektoniczne — **przyjęte 2026-10-18**: Python + FastAPI, interfejs Preact + htm bez kroku budowania, MapLibre GL, procesy robocze, rio-tiler, pakiet Pythona, tryb zespołu jako jeden serwer (A-ADR-004, 006, 007, 008, 013, 015, 028). Pozostaje: komputer odniesienia, plan implementacji v0.1.
   - Bramka: ADR architektury przyjęte (spełnione), plan v0.1 zatwierdzony przez użytkownika.
2. **v0.1 „Przeglądarka”.** Indeks, „Mapa”, „Katalog”, „Karta pliku”, „Projekty” (podgląd), „Magazyn”, mechanizm źródeł z atrapą drugiego adaptera, ochrona trybu lokalnego.
   - Bramka: indeks zgodny z API odczytu Kartografa; cele wydajności na magazynie syntetycznym 50 000 slotów; magazyn tylko do odczytu działa; testy bezpieczeństwa zielone.
3. **v0.2 „Podglądy”.** Podglądy, „Wachlarz”, „Oś czasu”, porównanie metadanych i kurtyna; dane własne projektu i migawki.
   - Bramka: każdy typ pliku ma podgląd albo powód braku; obrysy CZ ≤ 2 m od punktu kontrolnego; mapa z 5 000 obrysów płynna; migawka GeoPackage w użyciu spójna, przerwanie bez częściowej wersji.
4. **v0.3 „Działania”.** Dostępność z etykietami pokrycia (także obrazy PL i wydania produktów jednostkowych), „Okno planu”, pobieranie, zadania w tle, aktualność, akcje projektów.
   - Bramka: parytet z CLI; anulowanie bez częściowych wersji; etykiety dla obszaru „Kraków” zgodne z ręcznym wyliczeniem; UC-01 i UC-06 na żywo.
5. **v0.4 „Zespół”.** Serwer w sieci lokalnej: logowanie, role, TLS, dziennik, wspólna kolejka.
   - Bramka: scenariusz na żywo z trzema osobami bez podwójnych pobrań; uprawnienia ról sprawdzone testami.
6. **v0.5 „Stacje IMGW”.** Dodatek IMGW, stacje, pokrycie szeregów, karta stacji, aktualność i synchronizacja archiwów, zadania projektu IMGW.
   - Bramka: indeks katalogu IMGW zgodny z API IMGWTools; parytet z CLI `imgw`; etykiety pokrycia zgodne z tabelą przypadków granicznych.
7. **v1.0 „Wydanie” (MVP).** Stabilne API, instalacja Linux i Windows, dokumentacja użytkownika, audyty, pomiar na prawdziwym SMB.
   - Bramka: kryteria sukcesu MVP z PRD.
8. **Po MVP:** v1.1 „Zestaw”, v1.2 „Asystent”, v1.3 „Mozaika i porównanie”, v1.4 „PL + CZ”; proponowane v1.5 „Udostępnianie” (A-ADR-029).

## Zależności

**Producenci** (wymagania: SPEC 12, [`wymagania-imgwtools.md`](wymagania-imgwtools.md)):

| Wersja Archiwisty | Wymaga od producentów |
| --- | --- |
| v0.1 | Kartograf: KA-1..KA-6 (odczyt magazynu) |
| v0.2 | — |
| v0.3 | Kartograf: KA-4 dla pozycji planu, KB-1..KB-5, KB-7, KC-1..KC-3, KD-1..KD-4, KH-1 |
| v0.4 | — |
| v0.5 | IMGWTools: IMGW-1..IMGW-14 |
| v1.0 | wydania Kartografa i IMGWTools ze wszystkimi powyższymi |
| v1.1 | Kartograf: KB-6 |
| v1.3 | Kartograf: KE, KG |
| v1.4 | Kartograf: KF |

**Dane w magazynie i ich warunki** (Archiwista pokazuje atrybucje, nie
zmienia warunków):

| Dane | Źródło | Uwagi licencyjne |
| --- | --- | --- |
| NMT, NMPT, LAZ, ortofotomapa, BDOT10k, PRG, EGiB i inne | GUGiK (przez Kartografa) | bezpłatne, z podaniem źródła |
| DMR, DMP, ortofoto, ZABAGED, RUIAN i inne | ČÚZK (przez Kartografa) | CC BY 4.0 |
| CORINE, SoilGrids | Copernicus, ISRIC (przez Kartografa) | otwarte, z atrybucją |
| Archiwa hydro i meteo, katalog stacji | IMGW-PIB (przez IMGWTools) | regulamin IMGW-PIB: formuły źródła (§5 ust. 3–4), cel użycia (§3 ust. 2) |
| Podkład mapy | OpenStreetMap | ODbL, atrybucja na mapie |

**Środowisko testowe:** przykładowy magazyn testu na żywo Kartografa
i katalog IMGW testowy w `<katalog-danych>`; magazyn syntetyczny 50 000
slotów z generatora (SPEC 11); udział SMB 3 do pomiarów.

## Ryzyka i działania zaradcze

Pełna lista: SPEC 14.

| Ryzyko | Skutek | Działanie zaradcze |
| --- | --- | --- |
| MVP zależy od wydania IMGWTools z magazynem (dziś Beta, IMGW-1..14) | v1.0 czeka na IMGWTools | wymagania uzgodnione wcześnie; v0.1–v0.4 bez IMGWTools; źródło IMGW jako dodatek |
| Zależność od wydań Kartografa (KA–KH) | etapy czekają | KA mały i pierwszy; wspólny harmonogram z roadmapą Kartografa |
| Tryb zespołu w MVP poszerza zakres bezpieczeństwa | dłuższa droga do v1.0 | v0.4 przed danymi IMGW; przegląd bezpieczeństwa w bramce v1.0 |
| Interfejs bez kontroli typów (Preact + htm bez budowania, A-ADR-028) | błędy wykrywane późno | testy w przeglądarce (Playwright), JSDoc; Vite i TypeScript można dodać później bez przepisywania |
| Semantyka SMB | indeks nieaktualny | niezmienne wersje, odświeżanie widoku, widoczny stan indeksu |
| Etykiety pokrycia źle rozumiane | zły wybór roku | mockup, definicje w podpowiedziach, test z użytkownikiem |
| Rozrost zakresu w stronę programu GIS | mniej prostoty | granice z PRD; analizy w QGIS |
| Brak zestawu do QGIS w MVP | ręczne wczytywanie danych do QGIS | kopiowanie ścieżek wersji i polecenia CLI w MVP; zestaw w v1.1 |
| Migawka pliku w trakcie edycji (GeoPackage w QGIS, Shapefile) | niespójna kopia | kopia zapasowa SQLite dla GeoPackage, komplet plików dla formatów wieloplikowych, test w bramce v0.2 |
| Migawki rosną w katalogu projektu | brak miejsca na dysku | rozmiar w planie migawki, zajętość w widoku projektu |
