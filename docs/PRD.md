# PRD – Archiwista

Oct 17, 2026 · @Piotr

**Status:** szkic do zatwierdzenia · **Licencja:** MIT · **Zakres i etapy:**
[`SCOPE.md`](SCOPE.md) · **Szczegóły:** [`SPEC.md`](SPEC.md) · **Decyzje:**
[`DECISIONS.md`](DECISIONS.md)

Ten dokument mówi, **co** Archiwista ma robić, **dla kogo** i **po co**. Nie
opisuje technologii: architekturę ustalono w etapie 0 (decyzja użytkownika
2026-10-18; SPEC 5, A-ADR-004..008, 013, 015, 028). Przy rozbieżności
w sprawach zakresu i priorytetów PRD i SCOPE mają pierwszeństwo przed SPEC.

## Cel i problem

Archiwista to aplikacja webowa do pracy z magazynem danych: przestrzennych,
które zapisuje Kartograf, i pomiarowych IMGW-PIB, które zapisuje IMGWTools.
Pozwala widzieć, co jest w magazynie, sprawdzać, co jest dostępne i aktualne
u źródła, i działać — pobierać, aktualizować i przypinać dane w projektach —
bez znajomości CLI i układu katalogów.

Problem: magazyn Kartografa szybko rośnie (dziesiątki tysięcy plików, kilka
wersji tego samego arkusza, wiele projektów przypinających różne wersje, dane
PL i CZ w różnych układach, dysk lokalny albo udział sieciowy). Proste
pytania wymagają dziś CLI, reguł katalogów `data/` i czytania plików JSON:

- „Co mam w magazynie dla tej zlewni i z którego roku?”
- „Z którego roku źródło ma komplet arkuszy dla tego obszaru?”
- „Czy jest nowszy nalot niż ten, którego używa projekt?”
- „Których plików użył projekt X i czy są nienaruszone?”
- „Które wodowskazy w tej zlewni mają ciągłe przepływy dobowe od 1951?”
- „Czy IMGW opublikował nowy rocznik albo poprawił stary?”

Charakter produktu: **manager magazynu**, nie program GIS ani program
obliczeń. Archiwista zleca pobieranie i aktualizację danych, ale nie ma
własnego mechanizmu pobierania ani obróbki — każde działanie na danych
wykonuje publiczne API producenta (Kartografa albo IMGWTools), a źródłem
prawdy są pliki w magazynie (sidecary, manifesty).

Kod jest otwarty (MIT). Archiwista zastępuje podprojekt 5 roadmapy Kartografa
(„GUI webowe”).

## Odbiorcy i ich potrzeby

| Odbiorca | Etap | Kluczowe pytanie | Czego potrzebuje |
| --- | --- | --- | --- |
| Hydrolog przygotowujący dane do modelu (zna QGIS, CLI rzadko) | MVP | Co jest dostępne dla mojej zlewni i z którego roku? | obszar na mapie → dostępność z etykietami pokrycia → pobranie; wodowskazy w zlewni z pokryciem szeregów |
| Specjalista GIS (zna Kartografa i CLI) | MVP | Które wersje mam, czy są nowsze, czym się różnią? | przegląd wersji i kampanii, aktualność, podglądy, dane z pogranicza PL/CZ |
| Zespół projektowy (kilka osób, wspólny magazyn na udziale SMB) | MVP | Kto co pobrał i które projekty używają których danych? | jeden serwer w sieci lokalnej, logowanie i role, wspólna kolejka bez podwójnych pobrań, dziennik działań |
| Deweloper Hydrografa, Hydrologa, Retmana | MVP | Gdzie leży niezmienna wersja tego pliku albo szeregu? | ścieżki wersji do skryptów, stan magazynu, projekty |
| Użytkownik przygotowujący dane do QGIS i obliczeń | po MVP | Jak wczytać to jednym ruchem / zlecić zdaniem? | zestaw do QGIS, asystent w języku naturalnym, mozaiki, porównania |

Wspólna potrzeba: **ludzkie nazwy i jasny plan** — „NMT 1 m · PL-1992 ·
EVRF2007”, a nie `nmt/pl_1992_1m_evrf2007`; przed każdym działaniem: co,
ile plików, ile już jest lokalnie, ile danych, dokąd.

## Opis produktu

Główny przepływ: **mapa → obszar → produkt → wynik**. Użytkownik zaznacza
obszar (prostokąt, wielokąt, plik geometrii, godło, TERYT, KU, kraj),
wybiera produkt i od razu widzi stan magazynu (bez sieci), a w tle
sprawdzenie u źródła: lata (kampanie, wydania) z etykietami pokrycia
(„pełne”, „pełne · 2 kampanie”, „częściowe · 58%”, „brak danych”)
i plakietką magazynu („pobrane 5/12”). Z wiersza roku: „Pobierz…” → okno
planu → zadanie w tle z postępem i anulowaniem.

Widoki MVP: „Mapa” (obrysy, stacje, zaznaczanie obszaru), „Wachlarz” (lata
wyniku jako miniatury, każda w całości), „Katalog” (lista i wyszukiwanie,
także dane bez położenia), „Karta pliku” i „Karta stacji”, „Projekty”,
„Magazyn” (zajętość i problemy), „Zadania”, „Ustawienia”. Słownictwo
i szkice: SPEC 2 i 6, mockup `mockup/`.

**Czym Archiwista nie jest** (SPEC 1.3): programem GIS (analizy w QGIS);
własnym mechanizmem pobierania ani obróbki (zleca je producentom); narzędziem usuwania
danych z magazynu; programem analiz hydrologicznych (Hydrolog, Retman);
źródłem danych bieżących IMGW (stany, ostrzeżenia); edytorem danych ani
systemem historii pojedynczych obiektów; zamiennikiem wtyczki QGIS Kartografa.

## Widoki według rodzaju danych

Widoki powstają z obrysów jednostek (zasięg pliku od producenta), raportu
dostępności u źródła i stanu magazynu; podglądy — wyłącznie z danych w
magazynie albo z usług źródła, które mają wymiar czasu. Lata niepobrane bez
takiej usługi mają w „Wachlarzu” tylko obrysy w kolorach pokrycia. Mockup
pokazuje dla każdego roku ten sam bieżący obraz z WMS GUGiK — to
uproszczenie mockupu, nie cecha danych.

| Rodzaj danych | Jednostka i obrys | „Mapa” | „Wachlarz” (warstwa = rok, kampania, wydanie) | Pokrycie i zmiany |
| --- | --- | --- | --- | --- |
| Rastry z arkuszy (NMT, NMPT, LAZ, ortofotomapa) | arkusz (godło), kafel CZ | arkusze w kolorach pokrycia i kampanii | obrysy + podgląd arkuszy pobranych; ortofotomapa także lata niepobrane z WMS GUGiK z wymiarem czasu (1995–2025) | etykiety roku (6.4); zmiany: porównanie metadanych i kurtyna (v0.2), model różnic (v1.3) |
| Produkty jednostkowe (BDOT10k, BDOO, modele 3D, CORINE) | jednostka administracyjna (powiat — TERYT), granice z PRG | jednostki obszaru: paczka jest / brak / w magazynie | obrysy jednostek + render wybranych warstw z pobranych paczek, przycięty do obszaru | etykiety wydania (KD-4, v0.3); zmiany: różnica wydań wg klas obiektów (porównanie wektorów u producenta, później) |
| Pliki krajowe i wyniki obszaru (PRG, ZABAGED, RUIAN…) | kraj albo obszar zadania | zasięg | jeden wpis „bieżące” albo wersje wg daty | wersje wg daty pobrania lub wydania |
| Stacje IMGW (od v0.6 także ČHMÚ) | punkt stacji; bez położenia — „Katalog” | punkty w kolorach pokrycia wybranej zmiennej, z plakietką dostawcy | — (dane opisują czas, nie obszar): „Oś czasu” stacje × lata | etykiety pokrycia szeregów (A-ADR-021) |
| Dane własne projektu (np. sieć kanalizacyjna) i rodzaj ogólny (dowolny plik rastrowy lub wektorowy) | zasięg z pliku | zasięg i podgląd w widoku, razem z danymi projektu | migawki jako warstwy | bez źródła zdalnego: bez etykiet dostępności; „zmieniony od migawki z …”; porównanie metadanych migawek |

## Wymagania funkcjonalne

Oznaczenie etapu w nawiasie: wersja z [`SCOPE.md`](SCOPE.md). Szczegóły
każdego wymagania: wskazana sekcja SPEC.

**F1. Magazyny i indeks** (SPEC 4)

- F1.1 Konfiguracja kilku magazynów (np. lokalny i zespołowy); magazyn = katalog Kartografa i/lub katalog IMGW. (v0.1)
- F1.2 Lokalny indeks magazynu i projektów budowany z sidecarów i manifestów przez API producentów; pełny i przyrostowy skan, odświeżenie widoku przed odpowiedzią. Indeks jest pamięcią podręczną: można go usunąć i odbudować. (v0.1)
- F1.3 Stan indeksu zawsze widoczny („Indeks z 14:02, skan trwa: 63%”); interfejs nigdy nie czeka na skan. (v0.1)
- F1.4 Praca na udziale SMB, także zamontowanym tylko do odczytu; odłączony udział = baner i indeks bez zmian, po podłączeniu odświeżenie bez przebudowy. (v0.1)
- F1.5 Źródła danych jako dodatki: bez IMGWTools aplikacja działa w całości dla danych Kartografa, a źródło IMGW jest jawnie „niedostępne” (A-ADR-024). (v0.1)

**F2. Mapa i obszar** (SPEC 5.4, 6.3)

- F2.1 Mapa z obrysami wersji w magazynie i podkładem (szary OSM, tryb offline). (v0.1)
- F2.2 Zaznaczanie obszaru: prostokąt, wielokąt, godło, TERYT, KU, plik geometrii; po nazwie gminy lub powiatu. (v0.1; nazwy: v0.3)
- F2.3 Stan magazynu dla obszaru i produktu bez sieci („lokalnie 83% obszaru”). (v0.1)

**F3. Katalog i wyszukiwanie** (SPEC 6.6, 6.8)

- F3.1 „Katalog”: lista z filtrami (produkt, rok danych, wariant, projekt, stan) i grupą danych bez położenia. (v0.1)
- F3.2 Wyszukiwanie po identyfikatorze z rozpoznaniem rodzaju: godło, TERYT, numer zgłoszenia, początek sumy SHA-256, kod stacji IMGW. (v0.1; stacje: v0.5)

**F4. Karta pliku i wersje** (SPEC 3 UC-04, 6.5)

- F4.1 Oś wersji slotu: bieżąca, pełna, etykiety (kampania, wydanie), które projekty przypinają którą wersję. (v0.1)
- F4.2 Metadane po ludzku i surowa wartość o jedno kliknięcie; licencja z „Kopiuj atrybucję”; kopiowanie ścieżki wersji. (v0.1)

**F5. Podglądy** (SPEC 5.7, 8.5 poziomy 1–2)

- F5.1 Podgląd każdego typu pliku magazynu albo podany powód braku; ten sam plik nie jest przeliczany drugi raz; limit pamięci podglądów. (v0.2)
- F5.2 „Wachlarz” i „Oś czasu” lat danych lokalnych; porównanie metadanych dwóch wersji i kurtyna na mapie. (v0.2)
- F5.3 Wstępne budowanie miniatur i przeglądu przy małym powiększeniu (bez wszystkich kafli) bieżących wersji w zadaniu w tle: po odświeżeniu indeksu dla nowych wersji po włączeniu przez administratora (domyślnie wyłączone) lub na żądanie z filtrem produktu/segmentu, projektu i obszaru przez CLI albo API; niski priorytet wobec podglądów interaktywnych, anulowanie, limit pamięci bez wypierania niedawno używanych podglądów, odczyt magazynu bez sieci i z zachowaniem widoczności projektów. (v0.3; decyzja użytkownika 2026-10-19)

**F6. Dostępność i etykiety pokrycia** (SPEC 6.4, A-ADR-010, 017)

- F6.1 Sprawdzenie u źródła dla obszaru i produktu (wysokości PL i CZ) w tle; ostatni raport z datą dostępny bez sieci. (v0.3)
- F6.2 Etykiety pokrycia roku i plakietka magazynu; wariant = produkt, rok, układ, rozdzielczość, układ wysokości, zgłoszenie (formaty jako plakietki). (v0.3)
- F6.3 Pokrycie wydań produktów jednostkowych (BDOT10k i jego archiwum, BDOO, modele 3D, CORINE): które jednostki obszaru mają paczkę w danym wydaniu (KD-4; decyzja użytkownika 2026-10-18). (v0.3)
- F6.4 Lata obrazów PL (ortofotomapa, true orto, intensywność) z pełnością arkuszy ze skorowidza (KD-3; decyzja użytkownika 2026-10-18). (v0.3)

**F7. Działania** (SPEC 3 UC-01, UC-05, UC-15; 5.6)

- F7.1 „Okno planu” przed każdym działaniem z siecią albo zapisem: co, ile plików, ile lokalnie, rozmiar, dokąd, polecenie CLI do skopiowania. (v0.3)
- F7.2 Pobieranie z formularza i z wklejonego polecenia `kartograf …`. (v0.3)
- F7.3 Zadania w tle: postęp, komunikaty producenta bez przeróbek, anulowanie bez częściowych wersji; restart serwera → „przerwane”, ponowienie nie pobiera gotowych jednostek. (v0.3)
- F7.4 Sprawdzanie aktualności segmentu, obszaru albo projektu i „Pobierz nowsze” według tego samego planu. (v0.3)

**F8. Projekty** (SPEC 4.7, UC-06, UC-07)

- F8.1 Podgląd projektów: zadania projektu jako polecenia, przypięte wersje, status, indeks użycia („Przypięta w: Raba (teren)”). (v0.1)
- F8.2 Akcje projektów przez API producenta: utworzenie, dodanie i usunięcie zadania, pobranie, przepięcie, sprawdzenie aktualizacji, weryfikacja sum. (v0.3)
- F8.3 Projekt z manifestami obu producentów (`kartograf-project.json`, `imgw-project.json`) w jednym widoku z kolumną producenta. (v0.5)

**F9. Kondycja magazynu** (SPEC UC-13)

- F9.1 Zajętość wg produktów (każda wersja liczona raz) i problemy z wyjaśnieniem i poleceniem naprawy; raport „nieużywane przez żaden projekt” i „niebieżące wersje” — bez usuwania. (v0.1)

**F10. Tryb zespołu** (SPEC 10.2, UC-14)

- F10.1 Jeden serwer w sieci lokalnej, logowanie (konta lokalne albo odwrotne proxy), zarządzanie kontami i ekran udostępniania projektu w interfejsie, opcjonalnie grupy z LDAP/AD — na modelu uprawnień F16. (v0.4)
- F10.2 Wspólna kolejka zadań bez podwójnych pobrań, historia i dziennik działań, limity per osoba, pobieranie plików przez HTTP, aliasy ścieżek per klient. (v0.4)

**F11. Dane IMGW** (SPEC 4.8, 6.7, UC-16, UC-17, UC-19)

- F11.1 Stacje na mapie, w „Katalogu” (także bez położenia, z filtrem rzeki i kodu hydrograficznego) i w „Zestawieniu”. (v0.5)
- F11.2 Etykiety pokrycia szeregów osobno dla każdej zmiennej, w latach hydrologicznych i kalendarzowych z przełącznikiem; wszystkie stacje, także z lukami. (v0.5)
- F11.3 „Karta stacji” z wykresem (luki jako przerwy, zero interpolacji), wersjami i formułami IMGW; porównanie stacji. Bez obliczeń statystycznych. (v0.5)
- F11.4 Aktualność archiwów (nowa publikacja, nowy rocznik), synchronizacja i szeregi jako zadania w tle IMGWTools z oknem planu i poleceniem `imgw …`. (v0.5)
- F11.5 Zadania projektu IMGW z przypięciami. (v0.5)

**F15. Dane własne i migawki** (SPEC 4.7.1, A-ADR-027)

- F15.1 Folder danych własnych przypisany do projektu (domyślnie `<katalog projektu>/dane/`, można wskazać inny); pliki rastrowe i wektorowe indeksowane tylko do odczytu: zasięg, układ, warstwy, liczba obiektów, schemat atrybutów, podgląd. (v0.2)
- F15.2 „Zrób migawkę”: Archiwista kopiuje plik do `<folder danych>/.wersje/` jako niezmienną wersję z sumą SHA-256 i opisem (`migawka.json`); tylko przyrost, zapis atomowy, spójna kopia pliku w użyciu (np. GeoPackage otwarty w QGIS), ta sama treść nie tworzy nowej migawki. (v0.2)
- F15.3 Migawki jako wersje: oś wersji, „Wachlarz”, kurtyna, porównanie metadanych (liczba obiektów, zasięg, schemat). (v0.2)
- F15.4 Wykrycie zmiany pliku od ostatniej migawki i podpowiedź „zrób migawkę”; historia zaobserwowanych stanów w indeksie (bez treści). (v0.2)

**F16. Uprawnienia i udostępnianie projektów** (SPEC 10.2, A-ADR-029)

- F16.1 Archiwista egzekwuje uprawnienia tylko we własnej powierzchni (interfejs, API, CLI, tokeny agentów, pamięć podglądów); bezpieczeństwo serwera i udziału oraz dostęp do systemu plików to odpowiedzialność administratora serwera. (v0.1)
- F16.2 Role: „administrator” (`admin`; administrator systemu Archiwista: ustawienia, magazyny, konta, grupy, uprawnienia), „zapis do magazynu” (`store_writer`) i zwykły „użytkownik”; ustawienie `store_write_for_all` nadaje zapis wszystkim. W trybie lokalnym właściciel ma `admin` i `store_writer`. (v0.1)
- F16.3 Widoczność projektu: publiczny, wybrane osoby, wybrana grupa (np. dział), prywatny; właściciel projektu; administrator widzi wszystkie. Lista projektów, „Przypięta w:”, wyszukiwanie i podglądy danych własnych uwzględniają widoczność; zmiany uprawnień trafiają do dziennika. (v0.1)
- F16.4 Konta, grupy, członkostwa, role i widoczność projektów w osobnej lokalnej bazie stanu z kopią zapasową (`archiwista state export`, odtworzenie `archiwista state import`); przebudowa indeksu jej nie dotyka. Administracja przez API i CLI. (v0.1)
- F16.5 Zapis do magazynu centralnego wyłącznie przez API producentów i tylko z uprawnieniem „zapis do magazynu”. (v0.3)
- F16.6 Logowanie, zarządzanie kontami i ekran udostępniania w interfejsie, opcjonalnie grupy z LDAP/AD (F10.1). (v0.4)

**F17. Pogranicze PL + CZ** (SPEC 4.8.6, 8.3, UC-09, UC-20; A-ADR-025 errata 3)

- F17.1 Pliki PL i CZ jednego zadania zgrupowane (`parent_request`) na mapie i w „Katalogu”; kontrola zgodności układów, pionu, rozdzielczości i dat z podpowiedzią brakującego pobrania. (v0.6)
- F17.2 „Łączenie › PL + CZ”: scalona powierzchnia NMT na wspólnej siatce z regułą i raportem styku, liczona przez Kartografa (KF) z planem, w tle, z poleceniem `kartograf …`; wynik jako produkt pochodny w magazynie i zadanie projektu. (v0.6)
- F17.3 Stacje ČHMÚ (hydro i meteo dobowe) przez IMGWTools w widokach F11: mapa, „Katalog”, „Zestawienie” z pokryciem każdej zmiennej, „Karta stacji” z wykresem i atrybucją CC BY 4.0, porównanie ze stacjami IMGW, aktualność i synchronizacja wybranych stacji, zadania projektu IMGW. (v0.6)

**Po MVP** (szczegóły: SCOPE, „Poza zakresem MVP”)

- F12 Zestaw do projektu i QGIS: `.qgz`, lista ścieżek, atrybucje, także dane IMGW i ČHMÚ oraz eksport PL + CZ bez scalania (SPEC 8.4). (v1.1)
- F13 Asystent (agent LLM): planuje przygotowanie danych, wykonuje dopiero po „Zatwierdź i uruchom”; domyślnie wyłączony (SPEC 7). (v1.2)
- F14 Łączenie: mozaika, porównanie wersji z modelem różnic — obróbka w Kartografie (SPEC 8). (v1.3)

## Wymagania niefunkcjonalne

**N1. Prostota (nadrzędna zasada)**

- N1.1 Każda wartość techniczna ma ludzką nazwę, a każda ludzka nazwa — dostęp do wartości technicznej.
- N1.2 Zero cichych zmian: nic nie jest pobierane, przepinane ani nadpisywane bez jawnej decyzji człowieka.
- N1.3 Komunikaty producentów pokazywane bez przeróbek; każde działanie da się powtórzyć z CLI (polecenie do skopiowania).
- N1.4 Interfejs po polsku; daty `RRRR.MM.DD` w interfejsie, ISO w API i plikach (A-ADR-016).

**N2. Integralność danych**

- N2.1 Magazyn tylko do odczytu: Archiwista nie zapisuje w katalogach producentów; zapis wyłącznie przez API Kartografa i IMGWTools.
- N2.2 Parytet z CLI: działanie przez Archiwistę i to samo polecenie CLI dają te same wersje, `sha256` i przypięcia.
- N2.3 Stan Archiwisty (indeks, podglądy, historia zadań) wyłącznie lokalnie i odtwarzalny; konta, grupy i widoczność projektów — w osobnej lokalnej bazie stanu z eksportem, bo nie da się ich odtworzyć z dysku; nic na udziale sieciowym ani w magazynie.
- N2.4 Wiedza o formacie magazynu tylko u producentów (A-ADR-014): brakująca funkcja = wymaganie wobec producenta (SPEC 12).
- N2.5 Poza indeksem Archiwista zapisuje wyłącznie na polecenie użytkownika i wyłącznie w katalogu projektu (migawki danych własnych, pliki obszarów, zestawy) — w otwartym formacie, czytelnym bez Archiwisty.

**N3. Wydajność** (magazyn odniesienia: 50 000 slotów, 80 000 wersji, 30 projektów; SPEC 4.5)

- N3.1 Pierwszy pełny skan ≤ 10 min na SMB, ≤ 2 min na dysku lokalnym; skan przyrostowy bez zmian ≤ 3 min / ≤ 20 s.
- N3.2 Odświeżenie widoku (obszar + produkt) ≤ 5 s / ≤ 1 s; lista, wyszukiwanie, karta pliku p95 ≤ 200 ms; obrysy w widoku p95 ≤ 300 ms.
- N3.3 Dane IMGW: warstwa stacji i tabela pokrycia p95 ≤ 300 ms; wykres pełnego szeregu dobowego p95 ≤ 500 ms (SMB).
- N3.4 Pamięć serwera ≤ 500 MB bez podglądów; indeks ≤ 500 MB.

**N4. Praca bez sieci i na udziale SMB**

- N4.1 Przegląd magazynu działa bez internetu („Brak sieci — pokazuję tylko magazyn”); podkład w trybie offline.
- N4.2 Poprawność na SMB bez blokad zakresów bajtów i bez stabilnych i-węzłów.

**N5. Bezpieczeństwo** (SPEC 10)

- N5.1 Tryb lokalny: serwer tylko na `127.0.0.1`, ochrona przed CSRF i DNS rebinding, dostęp tylko dla osoby, która uruchomiła serwer; odmowa startu poza `127.0.0.1` bez trybu zespołu.
- N5.2 Tryb zespołu: logowanie, role, TLS poza `127.0.0.1`, dziennik działań; od v0.1 każda usługa i zapytanie sprawdza uprawnienia `Principal` (F16).
- N5.3 Odczyt plików tylko w korzeniach skonfigurowanych magazynów i projektów; niezaufane wejście (pliki geometrii, archiwa IMGW) bez ryzyka dla serwera.
- N5.4 Sekrety tylko po stronie serwera; zależności z przypiętymi wersjami i audytem podatności w bramce wydania.

**N6. Platformy i instalacja**

- N6.1 Linux i Windows od v1.0; macOS bez gwarancji.
- N6.2 Instalacja jednym poleceniem; dodatek IMGW opcjonalny; serwer zespołu łatwy do wdrożenia w sieci lokalnej.
- N6.3 Dostępność cyfrowa: WCAG 2.1 AA (audyt przed v1.0); priorytet desktop i monitory ultrawide.

**N7. Kod i licencje**

- N7.1 Kod otwarty na licencji MIT; kontrybucje z CLA (A-ADR-026, [`CONTRIBUTING.md`](../CONTRIBUTING.md)).
- N7.2 Zależności o licencjach zgodnych z MIT; zależność z licencją copyleft wymaga decyzji (ADR) przed dodaniem.
- N7.3 Zgodność z warunkami danych: atrybucje GUGiK, CUZK (CC BY 4.0), formuły IMGW-PIB (regulamin §5), OSM (ODbL) dla podkładu — w karcie pliku i karcie stacji.

**N8. Rozszerzalność**

- N8.1 Nowe źródło istniejącego producenta (np. dane z Niemiec w Kartografie) pojawia się w Archiwiście bez zmian w jego kodzie: nazwy, warianty, komendy i obrysy pochodzą z API producenta. Brakujące elementy (raport dostępności, obrysy, transformacje dla nowych układów) to wymagania wobec producenta.
- N8.2 Nowy producent to nowa wtyczka (adapter) bez zmian w warstwach wyżej (A-ADR-024).
- N8.3 Każdy rodzaj danych bez dedykowanego widoku dostaje widok ogólny: zasięg, metadane, wersje i podgląd; brak źródła zdalnego nie psuje widoków (brak etykiet dostępności zamiast błędu).

## Założenia i ograniczenia

| Założenie | Skutek | Jak komunikujemy |
| --- | --- | --- |
| Producenci dostarczą wymagane API (Kartograf KA–KH, IMGWTools IMGW-1..20) | wydania Archiwisty czekają na wydania producentów | wymagania w SPEC 12 i `docs/IMGWTOOLS_REQUIREMENTS.md`; kolumna „wymaga" w SCOPE |
| IMGWTools (2.1.1, Beta) nie ma dziś magazynu | dane IMGW (v0.5), a więc i MVP, zależą od IMGWTools | wymagania uzgodnione wcześnie; źródło IMGW jako dodatek |
| KF (scalona powierzchnia PL + CZ) nie jest jeszcze w publicznym API Kartografa; stacje ČHMÚ w IMGWTools dopiero w przygotowaniu | v0.6, a więc i MVP, zależy od obu wydań | wymagania KF (SPEC 12.5) i IMGW-15..IMGW-19 (SPEC 12.7) zgłoszone wcześnie; ryzyko w SCOPE i SPEC 14 |
| Opóźnienie publikacji IMGW (10–19 miesięcy), ponowne publikacje archiwów | niepełny ostatni rok, zmiany danych | lata opublikowane i daty publikacji w interfejsie; nowe wersje zamiast nadpisania |
| Część stacji IMGW bez położenia | stacje poza mapą | „Katalog” z grupą „bez położenia” i licznikiem na mapie; nigdy zgadywanie położenia |
| Semantyka SMB (pamięć atrybutów, i-węzły) | indeks może być chwilowo nieaktualny | odświeżanie widoku przed odpowiedzią, widoczny stan indeksu |
| Archiwista niczego nie usuwa | magazyn tylko rośnie | raport kandydatów do usunięcia z zajętością (decyzję podejmuje człowiek, usuwanie ewentualnie w Kartografie) |
| Podkład online ujawnia obszar zainteresowania | poufność projektu | tryb offline; w zespole decyduje administrator |
| Migawki leżą w katalogu projektu i tylko przybywa | zajętość dysku projektu rośnie | rozmiar w planie migawki; zajętość migawek w widoku projektu; usuwanie tylko ręcznie poza Archiwistą |
| Migawki to trzecia implementacja wersji (obok Kartografa i IMGWTools) | rozbieżne gwarancje | najprostszy kontrakt: tylko przyrost, bez dowiązań, zapis atomowy, testy przerwania (A-ADR-027) |

## Miary sukcesu

Kryteria sukcesu MVP (v1.0):

- [ ] Scenariusze MVP (SPEC 3: UC-01..UC-07, UC-09, UC-13..UC-17, UC-19, UC-20) przechodzą na żywo i są opisane w raporcie.
- [ ] Indeks przykładowego magazynu zgodny z API odczytu producentów (te same wersje, dowiązania i problemy).
- [ ] Parytet z CLI dla pobierania, projektów, scalenia PL + CZ i synchronizacji IMGW i ČHMÚ (te same wersje i `sha256`).
- [ ] Cele wydajności N3 spełnione na prawdziwym udziale SMB.
- [ ] Anulowanie i restart w trakcie zadań nie zostawiają częściowych wersji.
- [ ] Zespół trzech osób na wspólnym magazynie: żadna jednostka nie jest pobrana dwa razy; role sprawdzone testami.
- [ ] Instalacja na Linuksie i Windows; audyt WCAG 2.1 AA i przegląd bezpieczeństwa bez krytycznych uwag.
- [ ] (propozycja, do zatwierdzenia) Osoba znająca QGIS, a nie CLI, przechodzi UC-01 bez instrukcji (test z użytkownikiem; etykiety pokrycia zrozumiane bez wyjaśnień).

## Otwarte decyzje

| Decyzja | Opcje / wartość robocza | Kiedy rozstrzygnąć |
| --- | --- | --- |
| Etykiety pokrycia i ich wygląd | robocze z SPEC 6.4 (A-ADR-010; mockup M2) | przed v0.3 |
| Format danych IMGW | `imgw-meta/1`, Parquet, GeoJSON (A-ADR-020) | z zespołem IMGWTools, przed v0.5 |
| Wyniki łączenia jako produkty pochodne Kartografa | tak, wzór HSG (A-ADR-009; SPEC 15 P2, P3) | przed v0.6 |
| Komputer odniesienia dla celów wydajności | do ustalenia | przed v0.1 |
| Adapter stacji ČHMÚ | jeden adapter IMGW, dopóki ČHMÚ jest dostawcą w pakiecie IMGWTools; osobny adapter (wtyczka) tylko gdy IMGWTools wyda ČHMÚ jako osobny pakiet; zmiana nazwy pakietu (np. „Obserwator”) zmienia import i nazwę extra (SPEC 4.8.6, A-ADR-024) | przy wydaniu IMGWTools ze stacjami ČHMÚ, przed v0.6 |
