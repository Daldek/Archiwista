# Rejestr decyzji — Archiwista

Każda decyzja architektoniczna lub projektowa jest opisana poniżej w formacie
rejestru Kartografa: numer, data, status, kontekst, rozważone opcje, decyzja,
konsekwencje. Treść decyzji opisuje stan w chwili jej podjęcia; późniejsze
zmiany faktów i ustalenia dodatkowe dopisujemy na końcu wpisu jako erraty
`**Errata N (RRRR-MM-DD, źródło/powód):**`. Plik ma końce linii LF.

W `docs/SPEC.md` odwołania do tych decyzji mają postać „A-ADR-0xx” —
odróżnia je to od ADR Kartografa (np. „ADR-036” = magazyn wersjonowany
Kartografa).

**Słownik statusów** (linia `**Status:**` każdego wpisu):
- `Przyjęta` — decyzja obowiązuje;
- `Proponowana` — zapisana w specu, czeka na decyzję użytkownika (wskazane pytanie otwarte albo mockup);
- `Przyjęta — częściowo zastąpiona przez ADR-x (zakres)` — wskazana część nie obowiązuje;
- `Przyjęta — uzupełniona przez ADR-x (zakres)` — obowiązuje, późniejsza decyzja ją rozszerza;
- `Zastąpiona przez ADR-x` — nie obowiązuje;
- `Odrzucona` — rozważona i nieprzyjęta.

## Indeks

| ADR | Tytuł | Data | Status |
|---|---|---|---|
| [ADR-001](#adr-001-osobny-projekt-kartograf-jako-zależność) | Osobny projekt, Kartograf jako zależność | 2026-10-17 | Przyjęta (uzupełniona przez ADR-024; errata 2: `kartograf>=0.8.0,<0.9`) |
| [ADR-002](#adr-002-źródło-prawdy-na-dysku-lokalny-indeks-jako-pamięć-podręczna) | Źródło prawdy na dysku, lokalny indeks jako pamięć podręczna | 2026-10-17 | Przyjęta — uzupełniona przez ADR-029 (osobna lokalna baza stanu nieodtwarzalnego) |
| [ADR-003](#adr-003-magazyn-tylko-do-odczytu-zapisy-wyłącznie-przez-kartografa) | Magazyn tylko do odczytu, zapisy wyłącznie przez Kartografa | 2026-10-17 | Przyjęta — częściowo zastąpiona przez ADR-019 |
| [ADR-004](#adr-004-serwer-w-pythonie-z-fastapi) | Serwer w Pythonie z FastAPI | 2026-10-17 | Przyjęta (errata 2: potwierdzona po otwarciu architektury, 2026-10-18) |
| [ADR-005](#adr-005-interfejs-jako-spa-w-svelte-api-najpierw) | Interfejs jako SPA w Svelte, API najpierw | 2026-10-17 | Zastąpiona przez ADR-028 (Preact + htm bez budowania; zasada „API najpierw” zostaje) |
| [ADR-006](#adr-006-mapa-w-maplibre-gl-js) | Mapa w MapLibre GL JS | 2026-10-17 | Przyjęta (errata 3: potwierdzona 2026-10-18; errata 1: „Stos” zastąpiony „Wachlarzem”, bez 3D) |
| [ADR-007](#adr-007-zadania-w-tle-w-osobnych-procesach) | Zadania w tle w osobnych procesach | 2026-10-17 | Przyjęta (errata 2: potwierdzona 2026-10-18) |
| [ADR-008](#adr-008-podglądy-przez-rio-tiler-z-pamięcią-po-sumie-wersji) | Podglądy przez rio-tiler z pamięcią po sumie wersji | 2026-10-17 | Przyjęta (errata 2: potwierdzona 2026-10-18, podgląd roku z kafli arkuszy; errata 3: klucz pamięci wersji bez `sha256`) |
| [ADR-009](#adr-009-łączenie-danych-obróbka-w-kartografie-opakowanie-w-archiwiście) | Łączenie danych: obróbka w Kartografie, opakowanie w Archiwiście | 2026-10-17 | Proponowana (SPEC 15: P2, P3) |
| [ADR-010](#adr-010-etykiety-pokrycia-roku-i-plakietka-magazynu) | Etykiety pokrycia roku i plakietka magazynu | 2026-10-17 | Proponowana (mockup: M2) |
| [ADR-011](#adr-011-asystent-po-stronie-serwera-z-potwierdzeniem-człowieka) | Asystent po stronie serwera z potwierdzeniem człowieka | 2026-10-17 | Przyjęta |
| [ADR-012](#adr-012-ochrona-trybu-lokalnego) | Ochrona trybu lokalnego | 2026-10-17 | Przyjęta (errata 1: token we fragmencie, osobny token CSRF, reguła `Origin`, CSP z podkładami; errata 2: token CSRF w każdym żądaniu zamiast ciasteczka, sesje agentów ograniczone) |
| [ADR-013](#adr-013-tryb-zespołu-jako-jeden-serwer-w-sieci-lokalnej) | Tryb zespołu jako jeden serwer w sieci lokalnej | 2026-10-17 | Przyjęta — uzupełniona przez ADR-029 (role i model uprawnień od v0.1; decyzja użytkownika 2026-10-18; SPEC 15: P1) |
| [ADR-014](#adr-014-wiedza-o-formacie-magazynu-tylko-w-kartografie) | Wiedza o formacie magazynu tylko w Kartografie | 2026-10-17 | Przyjęta — uzupełniona przez ADR-019 (errata 2: KA w Kartografie 0.8.0, `skip_versions`, `list_segments`, KA-5 na żądanie) |
| [ADR-015](#adr-015-pakowanie-i-uruchamianie) | Pakowanie i uruchamianie | 2026-10-17 | Przyjęta (errata 2: potwierdzona 2026-10-18, bez Node.js) |
| [ADR-016](#adr-016-format-dat-w-interfejsie-i-podkład-mapy) | Format dat w interfejsie i podkład mapy | 2026-10-17 | Przyjęta (SPEC 15: P6; mockup: M9) |
| [ADR-017](#adr-017-warianty-grupowane-bez-formatu-plików) | Warianty grupowane bez formatu plików | 2026-10-17 | Przyjęta (uzupełnia ADR-010) |
| [ADR-018](#adr-018-wzorce-interfejsu-po-mockupie-czat-stos-podglądy) | Wzorce interfejsu po mockupie: czat, Stos, podglądy | 2026-10-17 | Przyjęta (errata 1: „Wachlarz” zastępuje „Stos”, M4/P12 rozstrzygnięte) |
| [ADR-019](#adr-019-dwóch-producentów-magazynu-kartograf-i-imgwtools) | Dwóch producentów magazynu: Kartograf i IMGWTools | 2026-10-17 | Przyjęta (zmienia ADR-003, uzupełnia ADR-014; pkt 7 zmieniony przez ADR-023; adaptery jako wtyczki: ADR-024) |
| [ADR-020](#adr-020-format-danych-imgw-własny-sidecar-parquet-geojson) | Format danych IMGW: własny sidecar, Parquet, GeoJSON | 2026-10-17 | Proponowana (ADR IMGWTools; SPEC 12.8) |
| [ADR-021](#adr-021-etykiety-pokrycia-szeregów-imgw) | Etykiety pokrycia szeregów IMGW | 2026-10-17 | Przyjęta (P14, P15 — errata 1; P16 — errata 2); Proponowana (mockup: M11) |
| [ADR-022](#adr-022-dane-bez-położenia-katalog-zamiast-mapy) | Dane bez położenia: Katalog zamiast mapy | 2026-10-17 | Przyjęta (SPEC 15: P13) |
| [ADR-023](#adr-023-dane-imgw-w-projektach-manifest-imgwtools) | Dane IMGW w projektach: manifest IMGWTools | 2026-10-17 | Przyjęta (dane IMGW w projekcie w v1.0 i dwa pliki manifestu: SPEC 15, P18) |
| [ADR-024](#adr-024-źródła-danych-jako-wtyczki-kartograf-wymagany-imgwtools-opcjonalny) | Źródła danych jako wtyczki: Kartograf wymagany, IMGWTools opcjonalny | 2026-10-17 | Przyjęta (uzupełnia ADR-001 i ADR-019; errata 1: `kartograf>=0.8.0,<0.9`) |
| [ADR-025](#adr-025-zakres-mvp-i-kolejność-wydań) | Zakres MVP i kolejność wydań | 2026-10-17 | Przyjęta (decyzja użytkownika; errata 3: „PL + CZ” jako v0.6 w MVP, ze stacjami ČHMÚ) |
| [ADR-026](#adr-026-licencja-mit-i-kontrybucje-z-cla) | Licencja MIT i kontrybucje z CLA | 2026-10-17 | Przyjęta (MIT; CLA — errata 1, decyzja użytkownika 2026-10-18) |
| [ADR-027](#adr-027-dane-własne-w-katalogu-projektu-i-migawki-archiwisty) | Dane własne w katalogu projektu i migawki Archiwisty | 2026-10-18 | Przyjęta (decyzja użytkownika; errata 1: migawkę w zespole robi właściciel projektu albo administrator, ADR-029) |
| [ADR-028](#adr-028-interfejs-w-preact--htm-bez-kroku-budowania) | Interfejs w Preact + htm bez kroku budowania | 2026-10-18 | Przyjęta (decyzja użytkownika; zastępuje ADR-005) |
| [ADR-029](#adr-029-rola-zapisu-do-magazynu-i-udostępnianie-projektów) | Rola zapisu do magazynu i udostępnianie projektów | 2026-10-18 | Przyjęta (decyzja użytkownika; uzupełnia ADR-013; model uprawnień od v0.1; errata 1: folder danych własnych ustawia administrator do v0.4) |

---

## ADR-001: Osobny projekt, Kartograf jako zależność

**Data:** 2026-10-17
**Status:** Przyjęta (decyzja użytkownika 2026-10-17); uzupełniona przez ADR-024 (Kartograf wymagany, IMGWTools opcjonalny)

**Kontekst:** Roadmapa Kartografa (SCOPE 3.3) przewidywała podprojekt 5 „GUI webowe”
(lokalny manager danych) jako nakładkę na bibliotekę. Użytkownik chce
pełnego managera: przegląd i wyszukiwanie archiwum, mapa i podglądy,
działania przez API Kartografa (pobieranie, aktualność, projekty),
przygotowanie danych do łączenia i asystent.

**Opcje:**
- A) GUI w repozytorium Kartografa (np. pakiet `kartograf.web`).
- B) Osobny projekt i repozytorium; Kartograf jako zależność (publiczne API i formaty na dysku).
- C) Rozbudowa CLI Kartografa o interfejs tekstowy (TUI).

**Decyzja:** B. Repozytorium `Archiwista` (gałęzie `main` i `develop`, bez remote)
zależy od publicznego API Kartografa (`kartograf.__all__`) i jego formatów
(`kartograf-meta/1`, układ `data/`, `kartograf-project/1`, `kartograf-plan/1`,
`kartograf-availability/1`). Archiwista zastępuje podprojekt 5 roadmapy
Kartografa; wtyczka QGIS (podprojekt 4) zostaje w Kartografie. Opcja A
dokładałaby do biblioteki zależności webowe i drugi cykl wydań; opcja C nie
daje mapy ani podglądów.

**Konsekwencje:** Kartograf nie zależy od Archiwisty i nie dostaje zależności webowych.
Archiwista deklaruje wspierany zakres wersji Kartografa i testuje się
przeciw jego gałęzi `develop`. Brakujące funkcje Kartografa są wymaganiami
wobec niego (ADR-014, SPEC 12); roadmapę Kartografa aktualizuje
koordynator.

**Errata 1 (2026-10-17, decyzja użytkownika — ADR-024):** Kartograf zostaje wymaganą
zależnością (`kartograf>=0.9,<0.10`, zakres ustala się przy wydaniu); IMGWTools jest
opcjonalny (extra `archiwista[imgw]`), a adaptery źródeł są wtyczkami rejestrowanymi
przez entry points.

**Errata 2 (2026-10-18, decyzja użytkownika — ADR-024 errata 1):** zakres wersji z errata 1
nie obowiązuje: publiczny odczyt magazynu (KA-1..KA-6) wchodzi do Kartografa 0.8.0, więc
zależność to `kartograf>=0.8.0,<0.9`.

---

## ADR-002: Źródło prawdy na dysku, lokalny indeks jako pamięć podręczna

**Data:** 2026-10-17
**Status:** Przyjęta — uzupełniona przez ADR-029 (osobna lokalna baza stanu nieodtwarzalnego); zasady SCOPE 3.3 Kartografa i decyzja użytkownika 2026-10-17

**Kontekst:** Magazyn może leżeć na udziale SMB bez blokad zakresów bajtów, więc nie
może tam być bazy SQLite; źródłem prawdy są sidecary i manifesty, a indeks
„które projekty używają pliku” buduje się lokalnie z manifestów (SCOPE 3.3).
Magazyn ma dziesiątki tysięcy plików — czytanie dysku przy każdym widoku
jest za wolne, zwłaszcza na udziale.

**Opcje:**
- A) Bez indeksu: czytanie magazynu przy każdym widoku.
- B) Lokalny indeks SQLite (WAL, R*Tree, FTS5) odbudowywalny z plików Kartografa.
- C) Baza serwerowa (PostgreSQL/PostGIS).
- D) Indeks wspólny na udziale.

**Decyzja:** B. Indeks leży w katalogu danych użytkownika, nigdy na udziale, i można
go w każdej chwili usunąć i odbudować. Wersje (niezmienne) są czytane raz,
sidecary dowiązań i manifesty — przy zmianie; przed odpowiedzią na pytanie
o obszar odświeżane są sloty tego obszaru; dobowy skan kontrolny wyłapuje
zmiany, których nie widać po czasach katalogów (SPEC 4.4).

**Konsekwencje:** Dwie instancje mogą chwilowo widzieć różny stan — interfejs zawsze
pokazuje czas indeksu. Zmiana schematu indeksu oznacza przebudowę, bez
migracji. Cele wydajności: SPEC 4.5.

**Errata 1 (2026-10-18, decyzja użytkownika, ADR-029):** konta, grupy, role i widoczność
projektów nie wynikają z plików na dysku, więc nie trafiają do indeksu, tylko do
osobnej lokalnej bazy stanu (`<user_data_dir>/state.sqlite`, nigdy na udziale), którą
przebudowa indeksu omija; jej schemat zmienia się migracjami, a kopia zapasowa to
`archiwista state export` (odtworzenie: `archiwista state import`).

---

## ADR-003: Magazyn tylko do odczytu, zapisy wyłącznie przez Kartografa

**Data:** 2026-10-17
**Status:** Przyjęta — częściowo zastąpiona przez ADR-019 (pisarze magazynu: Kartograf i IMGWTools)

**Kontekst:** Zasada nakładek (SCOPE 3.3): nakładki wołają wyłącznie publiczne API
biblioteki i nie mają własnej logiki pobierania ani obróbki. Magazyn
Kartografa nigdy nie nadpisuje danych po cichu (ADR-036 Kartografa),
a Kartograf niczego nie usuwa.

**Opcje:**
- A) Archiwista zapisuje w magazynie własne pliki (indeks, miniatury, notatki).
- B) Magazyn tylko do odczytu; wersje, dowiązania i manifesty zmienia wyłącznie API Kartografa.
- C) Jak B, ale z usuwaniem wersji przez Archiwistę.

**Decyzja:** B. Poza lokalnymi plikami (indeks, podglądy, dzienniki) Archiwista
zapisuje tylko katalog zestawu w projekcie (SPEC 8.4) i plik geometrii
narysowanego obszaru dla nowego zadania projektu (`obszary/`). Usuwania nie
ma (SPEC 15, P4).

**Konsekwencje:** v0.1 jest sprawdzana na magazynie zamontowanym tylko do odczytu. Każda
nowa operacja tworząca dane wymaga funkcji Kartografa (ADR-009).

**Errata 1 (2026-10-17, przegląd specu):** „plik geometrii narysowanego obszaru”
obejmuje też obszar wczytany z pliku (GPKG, SHP, GeoJSON): przy zadaniu
projektu jego kopia trafia do `obszary/` projektu, a nie do lokalnego katalogu
roboczego, żeby manifest nie wskazywał ścieżki spoza katalogu projektu
(SPEC 4.1, 6.3, 10.1).

**Errata 2 (2026-10-17, ADR-019):** magazyn ma dwóch producentów — Kartografa (katalog
`--output` z układem `data/`) i IMGWTools (osobny katalog IMGW, `imgw-store/1`).
„Zapisy wyłącznie przez Kartografa” dotyczy katalogu Kartografa; katalog IMGW
zmienia wyłącznie API IMGWTools. Część „magazyn tylko do odczytu” obowiązuje bez
zmian dla obu katalogów, podobnie dozwolone zapisy Archiwisty (pliki lokalne,
katalog zestawu, `obszary/`); zestaw może zawierać szeregi IMGW w CSV wyeksportowane
funkcją IMGWTools (SPEC 8.4).

---

## ADR-004: Serwer w Pythonie z FastAPI

**Data:** 2026-10-17
**Status:** Przyjęta (errata 2, decyzja użytkownika 2026-10-18; wcześniej ponownie otwarta — errata 1)

**Kontekst:** Kartograf jest biblioteką Pythona; Archiwista musi wywoływać jego funkcje,
a nie parsować wynik CLI. Potrzebne jest jedno API HTTP dla interfejsu,
asystenta i skryptów, z typowanym schematem.

**Opcje:**
- A) Python + FastAPI + Uvicorn + Pydantic 2.
- B) Python + Flask.
- C) Python + Django.
- D) Python z frameworkiem UI (NiceGUI, Streamlit, Panel, Dash).
- E) Inny język (Node.js, Go, Rust) z wołaniem CLI Kartografa.

**Decyzja:** A. Typowane modele dają schemat OpenAPI (typy interfejsu, opisy narzędzi
asystenta); ten sam wybór co w Hydrografie (jego ADR-002). Flask nie daje
schematów bez dodatków, Django wnosi zbędny ORM i panel, frameworki UI wiążą
interfejs z procesem Pythona (Streamlit przelicza skrypt przy każdej
interakcji) i nie dają czystego API, a inny język oznaczałby parsowanie
tekstu CLI — to odrzucił już ADR-037 Kartografa (opcja C).

**Konsekwencje:** Python 3.12+, jak Kartograf. Kartograf jest importowany tylko w module
adaptera (`archiwista/adapter/`), co pilnuje test importów.

**Errata 1 (2026-10-17, decyzja użytkownika — architektura otwarta):** architektura jest
ponownie otwarta; decyzja wraca do statusu Proponowana i zostanie potwierdzona albo
zmieniona przed v0.1 (SCOPE, etap 0). Treść powyżej to dotychczasowa ocena, punkt
wyjścia do decyzji.

**Errata 2 (2026-10-18, decyzja użytkownika — etap 0):** decyzja potwierdzona bez zmian
po porównaniu wariantów architektury; wybór jest praktycznie wymuszony, bo Kartograf
i IMGWTools to biblioteki Pythona.

---

## ADR-005: Interfejs jako SPA w Svelte, API najpierw

**Data:** 2026-10-17
**Status:** Zastąpiona przez ADR-028 (decyzja użytkownika 2026-10-18); zasada „API najpierw” i stan widoku w adresie URL zostają

**Kontekst:** Główny ekran to aplikacja mapowa ze wspólnym stanem: obszar, produkt,
warstwy lat, widoki „Mapa”, „Stos” i „Katalog”, panel „Zestawienie”, czat
asystenta, postęp zadań. Użytkownik zostawił wolną rękę co do nowoczesnych
wzorców interfejsu, ale chce zobaczyć mockup przed decyzjami o wzorcach.

**Opcje:**
- A) Szablony serwerowe + htmx.
- B) SPA: Svelte 5 + TypeScript + Vite.
- C) SPA: React.
- D) SPA: Vue 3.
- E) Czysty JavaScript bez frameworka (jak Hydrograf).

**Decyzja:** B. Jedno API HTTP obsługuje interfejs, asystenta i skrypty; interfejs jest
budowany do plików statycznych w pakiecie Pythona (użytkownik nie potrzebuje
Node.js), stan widoku jest w adresie URL, typy API generowane z OpenAPI.
htmx dobrze obsługuje listy i formularze, ale stan mapy i paneli rozpadałby
się na fragmenty HTML i ręczny JS; React i Vue są porównywalne, Svelte daje
najmniej kodu; czysty JS przy tylu widokach rośnie w nieuporządkowany kod.

**Konsekwencje:** Dwa ekosystemy w repozytorium (Python i Node.js dla deweloperów). Mockup
(SPEC 16) rozstrzyga wzorce interfejsu, nie framework.

**Errata 1 (2026-10-17, decyzja użytkownika — architektura otwarta):** architektura jest
ponownie otwarta; decyzja wraca do statusu Proponowana i zostanie potwierdzona albo
zmieniona przed v0.1 (SCOPE, etap 0). Treść powyżej to dotychczasowa ocena, punkt
wyjścia do decyzji.

**Errata 2 (2026-10-18, decyzja użytkownika — etap 0):** zastąpiona przez ADR-028:
interfejs w Preact + htm bez kroku budowania (jak mockup) zamiast Svelte z Vite; z tej
decyzji zostają: jedno API HTTP dla interfejsu, skryptów i asystenta oraz stan widoku
w adresie URL.

---

## ADR-006: Mapa w MapLibre GL JS

**Data:** 2026-10-17
**Status:** Przyjęta (errata 3, decyzja użytkownika 2026-10-18; errata 1: „Stos” zastąpiony „Wachlarzem”, bez 3D)

**Kontekst:** Mapa musi płynnie pokazać dziesiątki tysięcy obrysów, podkłady XYZ i WMS
(GUGiK, CUZK) oraz widok „Stos” — warstwy lat nad mapą w rzucie
izometrycznym (wymaganie użytkownika 2026-10-17).

**Opcje:**
- A) Leaflet (wybór Hydrografa, jego ADR-003).
- B) OpenLayers.
- C) MapLibre GL JS.
- D) CesiumJS.
- E) deck.gl jako główna biblioteka.

**Decyzja:** C. WebGL, nachylenie kamery i `fill-extrusion` z wysokością bazową dają
„Stos” bez osobnego silnika 3D. Leaflet nie ma nachylenia ani 3D, OpenLayers
— widoku 3D, CesiumJS to ciężki silnik globu, deck.gl może dojść później
(chmury punktów, tekstury w „Stosie”).

**Konsekwencje:** Wyświetlanie w EPSG:3857; przeliczenia do wyświetlania wykonuje serwer
przypiętą transformacją Kartografa (KA-6). Wymagana przeglądarka z WebGL.

**Errata 1 (2026-10-17, decyzja użytkownika po mockupie — ADR-018 errata 1):** widok
„Stos” usunięto; zastąpił go „Wachlarz” — komponent SVG interfejsu z miniaturami lat,
nie warstwa mapy. Argumenty „nachylenie kamery i `fill-extrusion` dają Stos” oraz
„tekstury w Stosie przez deck.gl” nie obowiązują. Wybór C zostaje: o MapLibre
przesądzają WebGL przy dziesiątkach tysięcy obrysów i punktów stacji, style wektorowe
i źródła XYZ/WMS (SPEC 5.2, 5.4).

**Errata 2 (2026-10-17, decyzja użytkownika — architektura otwarta):** architektura jest
ponownie otwarta; decyzja wraca do statusu Proponowana i zostanie potwierdzona albo
zmieniona przed v0.1 (SCOPE, etap 0). Treść powyżej (z errata 1) to dotychczasowa
ocena, punkt wyjścia do decyzji.

**Errata 3 (2026-10-18, decyzja użytkownika — etap 0):** decyzja potwierdzona; MapLibre
sprawdził się w mockupie (tysiące obrysów, obrazy roku na mapie, warstwy liniowe
danych własnych).

---

## ADR-007: Zadania w tle w osobnych procesach

**Data:** 2026-10-17
**Status:** Przyjęta (errata 2, decyzja użytkownika 2026-10-18)

**Kontekst:** Pobrania, sprawdzenia, weryfikacje i łączenie trwają od sekund do godzin,
korzystają z bibliotek natywnych (GDAL) i muszą dać się anulować. Kartograf
jest synchroniczny i nie ma dziś parametru anulowania.

**Opcje:**
- A) Wątki w procesie serwera.
- B) asyncio.
- C) Celery albo RQ z Redisem.
- D) Procesy robocze uruchamiane przez nadzorcę w serwerze, kolejka w indeksie.

**Decyzja:** D. Proces roboczy wywołuje funkcję Kartografa i wysyła zdarzenia JSON Lines
(postęp, komunikaty, wynik, błąd); nadzorca zapisuje je w indeksie
i przekazuje przez SSE. Limity: 2 zadania sieciowe, 1 zadanie na projekt.
Anulowanie docelowo kooperacyjne (KC-1), do tego czasu sygnał przerwania,
a po 30 s zakończenie procesu. Restart serwera oznacza zadania „przerwane”.
Procesy robocze dostają lokalny `MetadataCache` (nigdy w bieżącym katalogu
ani na udziale).

**Konsekwencje:** Awaria biblioteki natywnej nie kładzie serwera; koszt startu procesu
(ok. 1 s) jest pomijalny przy tych operacjach. Pełne anulowanie bez ryzyka
pozostawionej blokady manifestu wymaga KC-1.

**Errata 1 (2026-10-17, decyzja użytkownika — architektura otwarta):** architektura jest
ponownie otwarta; decyzja wraca do statusu Proponowana i zostanie potwierdzona albo
zmieniona przed v0.1 (SCOPE, etap 0). Treść powyżej to dotychczasowa ocena, punkt
wyjścia do decyzji.

**Errata 2 (2026-10-18, decyzja użytkownika — etap 0):** decyzja potwierdzona; procesy
robocze obsługują też migawki danych własnych (A-ADR-027). Zachowanie na Windows
(sygnały, `CTRL_BREAK_EVENT`) testowane przed v1.0.

---

## ADR-008: Podglądy przez rio-tiler z pamięcią po sumie wersji

**Data:** 2026-10-17
**Status:** Przyjęta (errata 2, decyzja użytkownika 2026-10-18; errata 3: klucz pamięci wersji bez `sha256`)

**Kontekst:** Podglądy mają objąć rastry (ASC, GeoTIFF, JPEG z JGW), GeoPackage, paczki
ZIP i chmury LAZ, bez ciężkich serwerów map. Pliki ASC nie mają
kafelkowania, a wersje w magazynie są niezmienne.

**Opcje:**
- A) rio-tiler jako biblioteka w serwerze, lokalne COG dla plików bez kafelkowania.
- B) TiTiler jako osobna usługa.
- C) GeoServer albo MapServer.
- D) Kafle z góry (`gdal2tiles`).

**Decyzja:** A. Kafle na żądanie; pamięć podglądów po `sha256` wersji i stylu (wersja
się nie zmienia, więc pamięć nigdy nie jest nieaktualna), limit 20 GB (LRU),
bez automatycznych podglądów dla plików większych niż 2 GB. Wektory przez
pyogrio (GeoJSON obiektów w widoku), LAZ przez laspy (nagłówek, obraz 2D).

**Konsekwencje:** Pierwszy podgląd pliku ASC trwa dłużej (budowa COG w tle). rio-tiler
korzysta z rasterio i GDAL, które instaluje już Kartograf.

**Errata 1 (2026-10-17, decyzja użytkownika — architektura otwarta):** architektura jest
ponownie otwarta; decyzja wraca do statusu Proponowana i zostanie potwierdzona albo
zmieniona przed v0.1 (SCOPE, etap 0). Treść powyżej to dotychczasowa ocena, punkt
wyjścia do decyzji.

**Errata 2 (2026-10-18, decyzja użytkownika — etap 0):** decyzja potwierdzona.
Podgląd roku produktu z arkuszy (NMT, NMPT, LAZ) składa się z podglądów
poszczególnych arkuszy w magazynie — kafel na wersję pliku, pamięć po `sha256`;
arkusze niepobrane zostają obrysami (PRD, „Widoki według rodzaju danych”; mockup:
kafle z prawdziwych plików).

**Errata 3 (2026-10-19, plan v0.2 po przeglądzie — SPEC 5.7):** wersja magazynu bez
`sha256` w sidecarze (starsze sidecary, wersja bez sidecara) ma klucz pamięci podglądów
`sha256("path:" + magazyn + ":" + ścieżka wersji + ":" + rozmiar + ":" + czas
modyfikacji)` w osobnej przestrzeni kluczy. Wersje są niezmienne, więc pamięć dalej nigdy
nie jest nieaktualna, ale takie wersje nie dzielą podglądów z kopiami tej samej treści.
Wersje z `sha256` — bez zmian.

---

## ADR-009: Łączenie danych: obróbka w Kartografie, opakowanie w Archiwiście

**Data:** 2026-10-17
**Status:** Proponowana — czeka na decyzję użytkownika i koordynatora roadmapy Kartografa (SPEC 15: P2, P3)

**Kontekst:** Cztery tryby przygotowania do łączenia (decyzja użytkownika 2026-10-17):
mozaika, PL + CZ, zestaw do projektu i QGIS, porównanie wersji. Zasada
nakładek (SCOPE 3.3) wyklucza obróbkę w nakładkach; polityka transformacji
Kartografa (ADR-022, ADR-024, ADR-027) trzyma przypięte operacje w jednym
miejscu; CLI = API (ADR-037); HSG (ADR-036 D33) jest wzorem produktu
pochodnego w magazynie.

**Opcje:**
- A) Wszystko w Archiwiście (własna mozaika, reprojekcja, różnice).
- B) Obróbka w Kartografie jako komendy grup danych (np. `elevation mosaic`, jak `soil hsg`) z produktami pochodnymi w magazynie; wybór, plan, prezentacja i zestaw QGIS w Archiwiście.
- C) Obróbka w Kartografie, ale wyniki w osobnym katalogu poza magazynem.

**Decyzja:** B (SPEC 8.6). Mozaika, scalanie PL + CZ i model różnic są funkcjami
Kartografa z bliźniakami `check_*`; wyniki to wersje w magazynie z sidecarem,
`extra.derived` i `extra.source_files[]`; operacje mogą być zadaniami
projektu (wejścia `input`, wynik `output`). Zestaw do QGIS, porównanie
metadanych i porównanie wizualne zostają w Archiwiście. Opcja A powielałaby
politykę transformacji (ryzyko błędów klasy „135 m obok prawdy”, ADR-024)
i omijała CLI = API; opcja C traci wersjonowanie, współdzielenie
i przypinanie.

**Konsekwencje:** Wymagania KE, KF, KG (SPEC 12.5); tryby 1, 2 (scalona powierzchnia) i 4
(różnice obliczone) czekają na wydania Kartografa, więc roadmapa daje
najpierw zestaw QGIS, zestaw PL + CZ bez scalania i porównanie wizualne.
Układ `data/` rozszerza ADR Kartografa (tokeny `mosaic`, `diff`, kraj
`pl-cz` — propozycje SPEC 8.2-8.5).

---

## ADR-010: Etykiety pokrycia roku i plakietka magazynu

**Data:** 2026-10-17
**Status:** Proponowana — do potwierdzenia na mockupie (SPEC 16, M2)

**Kontekst:** Użytkownik chce przy każdym roku etykiety pokrycia: pełne, niepełne,
niepełne, ale do uzupełnienia z innej kampanii tego roku — krótkich,
eleganckich i opartych na danych Kartografa (arkusze `TAK`/`NIE`,
`full_sheet`, raport dostępności).

**Opcje:**
- A) Same liczby (procent pokrycia, liczba arkuszy).
- B) Trzy stany z samego `complete` (pełne, częściowe, brak).
- C) Cztery etykiety z definicjami (pełne, pełne z N kampanii, częściowe z udziałem pełnych arkuszy, brak danych) i osobna plakietka stanu magazynu.

**Decyzja:** C (definicje: SPEC 6.4). „pełne” — jedna kampania sama pokrywa ląd pełnymi
arkuszami; „pełne · N kampanie” — dopiero N kampanii razem; „częściowe ·
58%” — udział lądu w ramkach pełnych arkuszy (dolna granica), z dopiskiem
o arkuszach niepełnych; „brak danych”. Osobno plakietka: „pobrane”,
„pobrane 5/12”, „niepobrane”. Wariant roku wybiera ranking: pełna, udział
pełnych arkuszy, mniej kampanii, drobniejsza rozdzielczość, kolejność
Kartografa. Etykiety liczy serwer — interfejs, asystent i API mają jedno
słownictwo (uzgodnione z mockupem).

**Konsekwencje:** Wymaga rozszerzeń raportu dostępności Kartografa: arkusz → kampania
(KD-1) i `full_m2` (KD-2); `len(campaigns)` nie wystarcza, bo liczy też
rekordy niepełne. Definicje dla CZ (bez lat) i produktów jednostkowych są
osobne (SPEC 6.4).

**Errata 1 (2026-10-17, A-ADR-017):** etykiety i plakietka dotyczą wariantu
grupowanego bez formatu plików: formaty tego samego zestawu (np. `ASC`
i `ASCII-NMT`) dzielą jedną etykietę pokrycia; plakietka magazynu liczy
jednostki w wybranym formacie.

**Errata 2 (2026-10-17, A-ADR-021):** etykiety tej decyzji opisują pokrycie obszaru;
pokrycie w czasie dla szeregów stacji IMGW („ciągły”, „luki N%”, „częściowy”,
„brak danych”, „nieznane”) definiuje ADR-021 (SPEC 4.8.4) według tych samych zasad:
liczy serwer, zaokrąglenie ostrożne, nigdy sam kolor.

---

## ADR-011: Asystent po stronie serwera z potwierdzeniem człowieka

**Data:** 2026-10-17
**Status:** Przyjęta (granice uprawnień: decyzja użytkownika 2026-10-17)

**Kontekst:** Użytkownik chce okna czatu z agentem LLM, któremu można zlecić
przygotowanie danych językiem naturalnym; agent nie może niczego pobrać ani
usunąć bez potwierdzenia; dostawca modelu ma być konfigurowalny,
z uwzględnieniem prywatności i kosztów.

**Opcje:**
- A) Agent w przeglądarce z kluczem API.
- B) Agent na serwerze: narzędzia = operacje API Archiwisty; działania tylko jako propozycje zatwierdzane przez człowieka.
- C) Wyłącznie zewnętrzny agent przez MCP.
- D) Agent autonomiczny wykonujący działania sam.

**Decyzja:** B (SPEC 7). Narzędzia tylko do odczytu działają same; działania są
propozycjami (dane strukturalne z poleceniami Kartografa i planem),
wykonywanymi wyłącznie z interfejsu z tokenem CSRF użytkownika; narzędzi
usuwania ani zmiany ustawień nie ma. Dostawcy: Anthropic, API zgodne
z OpenAI (także modele lokalne); domyślnie brak (asystent wyłączony).
Do dostawcy trafiają tylko metadane ze ścieżkami względnymi; limit
miesięczny kosztów.

**Konsekwencje:** Zestaw ewaluacyjny i testy poleceń wrogich w bramce; MCP może być
dodatkowym wejściem do tych samych narzędzi po v1.0.

---

## ADR-012: Ochrona trybu lokalnego

**Data:** 2026-10-17
**Status:** Przyjęta

**Kontekst:** Lokalna aplikacja webowa bez logowania jest osiągalna dla każdej strony
otwartej w tej samej przeglądarce (CSRF, DNS rebinding) i dla innych
użytkowników tego samego komputera.

**Opcje:**
- A) Bez ochrony („localhost jest bezpieczny”).
- B) Tylko `127.0.0.1`, kontrola `Host`, token startowy, nagłówek CSRF, brak CORS, CSP.
- C) Pełne logowanie także lokalnie.

**Decyzja:** B (SPEC 10.1). Token startowy w adresie otwieranym przez `archiwista serve`
zamienia się w ciasteczko sesji; start na innym adresie wymaga trybu
zespołu z logowaniem.

**Konsekwencje:** Pierwsze otwarcie zawsze przez adres z terminala albo automatycznie
otwartą przeglądarkę; token można wyłączyć w konfiguracji (niezalecane).

**Errata 1 (2026-10-18, plan v0.1 po przeglądzie — SPEC 10.1):** doprecyzowanie opcji B
bez zmiany decyzji:
- token startowy jest we fragmencie adresu (`http://127.0.0.1:<port>/#token=…`), więc nie
  trafia do serwera, dziennika dostępu ani nagłówka `Referer`; jest jednorazowy (10 min),
  a interfejs wymienia go przez `POST /api/v1/session` i usuwa z adresu;
- sesja to ciasteczko `HttpOnly`, `SameSite=Strict`, a token CSRF jest osobną 128-bitową
  wartością sesji (ciasteczko `archiwista_csrf` bez `HttpOnly` i odpowiedź
  `POST`/`GET /api/v1/session`): JavaScript nie przeczyta ciasteczka `HttpOnly`, więc
  nagłówek `X-Archiwista-CSRF` nie może nieść wartości sesji; serwer porównuje nagłówek
  z tokenem sesji i ciasteczkiem (double-submit);
- obecny `Origin` musi być adresem serwera; żądanie zmieniające stan z `Sec-Fetch-Site`
  (przeglądarka) musi mieć `Sec-Fetch-Site: same-origin` i `Origin`, a odczyt
  z `cross-site` jest odrzucany (`none` — adres wpisany albo otwarty z terminala —
  przechodzi); klient bez tych nagłówków (curl, skrypt agenta) przechodzi wyłącznie
  z sesją i, przy zmianie stanu, z nagłówkiem CSRF;
- kolejne sesje (agent zewnętrzny): jednorazowy token ważny 5 min z
  `POST /api/v1/session/tokens` (sesja i CSRF) albo z `archiwista token` w terminalu
  właściciela; w indeksie leży tylko skrót SHA-256 tokenu;
- CSP ma `worker-src 'self'` (worker MapLibre z pakietu, moduł z tego samego pochodzenia) oraz źródła
  skonfigurowanych podkładów w `connect-src` i `img-src` — tylko w trybie online, bo
  MapLibre pobiera kafle przez `fetch`;
- dziennik dostępu serwera jest domyślnie wyłączony, a włączony redaguje `token=`.

**Errata 2 (2026-10-19, przegląd bezpieczeństwa v0.1, ARCH-SEC-001..005, 008 — SPEC 10.1):**
ciasteczka są związane z hostem, nie z portem (RFC 6265 8.5), więc przeglądarka wysyła
`archiwista_session` i `archiwista_csrf` także do innego programu na
`127.0.0.1:<inny port>` (np. innego konta na wspólnym komputerze), a `SameSite=Strict`
tego nie blokuje. Zmiany bez zmiany opcji B:
- uwierzytelnieniem jest ciasteczko sesji **i** token CSRF sesji w nagłówku
  `X-Archiwista-CSRF` w **każdym** żądaniu `/api` (także odczytach); token zwraca wyłącznie
  `POST /api/v1/session`, interfejs trzyma go w `sessionStorage` swojego pochodzenia,
  nowa karta dostaje go od otwartej karty (`BroadcastChannel`), zdarzenia zadań idą
  przez `fetch` zamiast `EventSource`; ciasteczka `archiwista_csrf` nie ma, `GET
  /api/v1/session` nie zwraca tokenu; double-submit z errata 1 nie obowiązuje;
- `archiwista serve` otwiera przeglądarkę przez prywatny plik przekierowania (`0600`,
  usuwany po użyciu albo wygaśnięciu tokenu), nie przez adres z tokenem w wierszu
  poleceń;
- tokeny i sesje przechowują tylko `id` i `kind` wystawcy; role i grupy są czytane przy
  każdym żądaniu; sesja agenta nie wystawia tokenów (`403`), kończy się najpóźniej po
  12 h, a `archiwista token --revoke-all` kończy wszystkie sesje agentów; `DELETE
  /api/v1/session` wylogowuje; zadania i dziennik uprawnień zapisują rodzaj wykonawcy
  i etykietę sesji;
- treść żądań jest ograniczona (4 KiB wymiana tokenu, 1 MiB pozostałe), dane lokalne
  mają tryb `0700` i `umask 077`.

---

## ADR-013: Tryb zespołu jako jeden serwer w sieci lokalnej

**Data:** 2026-10-17
**Status:** Przyjęta — uzupełniona przez ADR-029 (role i model uprawnień od v0.1); decyzja użytkownika 2026-10-18; SPEC 15, P1

**Kontekst:** Zespół ma pracować później na wspólnym magazynie na udziale SMB bez
blokad zakresów bajtów. Kartograf gwarantuje bezpieczne równoległe zapisy
(wersje wyłączne, blokada manifestu), ale nie koordynuje, kto co pobiera.

**Opcje:**
- A) Każda osoba uruchamia własną instancję na wspólnym udziale.
- B) Jeden serwer Archiwisty w sieci lokalnej z logowaniem, rolami i wspólną kolejką.

**Decyzja:** B jako docelowy tryb zespołu (v0.8); A pozostaje wspierana (jedna osoba,
praca bez serwera). Wspólna kolejka nie pobiera tego samego dwa razy, jest
jedna historia i jeden indeks, a ścieżki są po stronie serwera.

**Konsekwencje:** Od v0.1: dostęp do plików tylko przez API (bez założenia wspólnego
systemu plików przeglądarki i serwera), wykonawca przy każdym działaniu,
aliasy ścieżek. Tryb zespołu wymaga TLS, ról i dziennika działań (SPEC 10.2).

**Errata 1 (2026-10-18, decyzja użytkownika):** B przyjęte; po zmianie numeracji
(ADR-025) tryb zespołu to v0.4, w MVP.

**Errata 2 (2026-10-18, decyzja użytkownika, ADR-029):** role „czytelnik”, „operator”,
„administrator” zastępują „administrator” (`admin`), „zapis do magazynu”
(`store_writer`) i zwykły „użytkownik”; model uprawnień i widoczność projektów działają
od v0.1 (jeden lokalny właściciel), logowanie i ekrany kont zostają w v0.4.

---

## ADR-014: Wiedza o formacie magazynu tylko w Kartografie

**Data:** 2026-10-17
**Status:** Przyjęta — uzupełniona przez ADR-019 (drugi producent: IMGWTools)

**Kontekst:** Układ `data/` (reguły 1-10, `versions/`, `full_sheet/`, `bbox/`, sidecary
dowiązań, stare sidecary, klucze z wersji deweloperskich) jest opisany
w ARCH 3.3 Kartografa, ale się rozwija. Ta sama wiedza jest potrzebna
wtyczce QGIS i Hydrografowi (backlog Kartografa: `find_downloaded`).

**Opcje:**
- A) Własny czytnik `data/` w Archiwiście według dokumentacji.
- B) Tymczasowy własny czytnik, zastąpiony później API Kartografa.
- C) Czytnik w Kartografie (pakiet KA) jako warunek v0.1.

**Decyzja:** C. Archiwista czyta magazyn przez `iter_store`, `read_sidecar`,
`describe_segment`, `file_footprint`, `link_target` i `pinned_transform`
(SPEC 12.1). Opcja A rozjedzie się z Kartografem przy pierwszej zmianie
układu; opcja B to obejście, które trzeba później usuwać.

**Konsekwencje:** v0.1 czeka na wydanie Kartografa z KA; KA jest mały i może być pierwszy
w roadmapie Kartografa. Test kontraktu: `iter_store` na magazynie testowym
Archiwisty.

**Errata 1 (2026-10-17, ADR-019):** zasada brzmi teraz: wiedza o formacie każdego
producenta tylko u tego producenta. Układ `data/` i `kartograf-meta/1` zna Kartograf
(pakiet KA, bez zmian); katalog IMGW (`imgw-store/1`, `imgw-meta/1`,
`imgw-series/1`), kody braków i kodowania archiwów IMGW zna wyłącznie IMGWTools,
a adapter IMGW czyta przez jego API odczytu (SPEC 12.7, IMGW-10). Test kontraktu:
`iter_store` IMGWTools na katalogu testowym zbudowanym przez IMGWTools.

**Errata 2 (2026-10-18, ADR-045 Kartografa i plan v0.1 po przeglądzie — SPEC 4.4, 5.3,
5.6, 12.1):** KA-1..KA-6 przyjęte w Kartografie 0.8.0 (ADR-045, ARCH 3.3.1). KA-1
rozszerzono o `list_segments(output_dir)` (lista segmentów do skanu równoległego; wywołania
`iter_store` dla różnych segmentów albo rozłącznych paczek jednostek mogą biec naraz)
i `iter_store(..., skip_versions=...)` (znane katalogi wersji wracają bez otwierania
sidecara: `sidecar=None`, `skipped=True`) — skan przyrostowy nie czyta ponownie
niezmiennych wersji. Skan nie woła `link_target` (KA-5): bieżącą wersję bierze
z `StoreEntry.version_path` (sidecar dowiązania), bo na udziale bez stabilnych i-węzłów
KA-5 liczy SHA-256 całego pliku; KA-5 jest wywoływane tylko na żądanie (zadanie
`link_check`). `cache` KA-4 to mapa należąca do wywołującego (`(rodzaj, kod) → BBox`),
trzymana lokalnie i czytana także bez sieci; brakujące obrysy jednostek uzupełnia
z siecią osobne zadanie `footprints`.

---

## ADR-015: Pakowanie i uruchamianie

**Data:** 2026-10-17
**Status:** Przyjęta (errata 2, decyzja użytkownika 2026-10-18)

**Kontekst:** Najpierw jedna osoba lokalnie, później serwer zespołu. Użytkownicy mają
środowisko Pythona z Kartografem.

**Opcje:**
- A) Pakiet Pythona `archiwista` z wbudowanym, zbudowanym interfejsem (`pipx`, `uv tool`).
- B) Wyłącznie obraz Dockera.
- C) Aplikacja desktopowa (Electron, Tauri).

**Decyzja:** A. Komenda `archiwista serve` (oraz `reindex` i `doctor`); konfiguracja
w pliku TOML w katalogu konfiguracji użytkownika, indeks i pamięć
w katalogu danych użytkownika. Obraz Dockera opcjonalnie dla serwera
zespołu.

**Konsekwencje:** Node.js potrzebny tylko do rozwoju interfejsu. Docker nie jest wymagany
dla jednej osoby (montowanie SMB w kontenerze komplikuje instalację).

**Errata 1 (2026-10-17, decyzja użytkownika — architektura otwarta):** architektura jest
ponownie otwarta; decyzja wraca do statusu Proponowana i zostanie potwierdzona albo
zmieniona przed v0.1 (SCOPE, etap 0). Treść powyżej to dotychczasowa ocena, punkt
wyjścia do decyzji.

**Errata 2 (2026-10-18, decyzja użytkownika — etap 0):** decyzja potwierdzona. Po
ADR-028 Node.js nie jest potrzebny także do rozwoju interfejsu: biblioteki interfejsu
są dołączone do pakietu jako pliki ES modules.

---

## ADR-016: Format dat w interfejsie i podkład mapy

**Data:** 2026-10-17
**Status:** Przyjęta

**Kontekst:** Pytania M9 (format dat w interfejsie) i P6 (podkłady online ujawniają
obszar zainteresowania zewnętrznym serwerom) wymagały decyzji użytkownika po przeglądzie
mockupu.

**Opcje:**
- A) Daty `RRRR.MM.DD` w interfejsie, ISO `RRRR-MM-DD` w API i plikach; podkład OSM
  w wersji monochromatycznej, online domyślnie, z trybem offline.
- B) Daty `DD.MM.RRRR` jak w mockupie; kolorowy OSM.
- C) Wyłącznie podkłady lokalne (offline).

**Decyzja:** A. Format `RRRR.MM.DD` daje łatwe sortowanie w tabelach i na osi czasu;
API, manifest, sidecary i nazwy plików zostają w ISO `RRRR-MM-DD`. Etykiety wersji
(np. `2025-04-26_82710`) to identyfikatory i nie są przeformatowywane. Podkład
domyślny to szara wersja OSM (neutralne tło dla obrysów i etykiet pokrycia), pobierana
online; tryb offline wyłącza zewnętrzne zapytania przeglądarki; w zespole decyduje
administrator (SPEC 5.4, 15: P6).

**Konsekwencje:** Interfejs formatuje daty z ISO na poziomie prezentacji (jedna funkcja
pomocnicza); szkice ekranów w SPEC używają `RRRR.MM.DD`. Szary styl podkładu wymaga
własnego stylu kafli lub filtra przeglądarki; w trybie offline zostaje „bez podkładu”
albo podkład lokalny.

**Errata 1 (2026-10-18, decyzja użytkownika — etap 10b planu v0.1):** podkład domyślny
to szary BKG TopPlusOpen („web_grau”, licencja dl-de/by-2-0, atrybucja
„© BKG (2026), dl-de/by-2-0”) zamiast szarej wersji OSM. Archiwista wysyła
`Referrer-Policy: no-referrer`, a tile.openstreetmap.org bez nagłówka `Referer` zwraca
zamiast kafla obraz „Access blocked” (sprawdzone na żywo); zasady korzystania z jego
kafli nie pasują też do pracy zespołu. Polityka `Referer` zostaje bez zmian. Kafle BKG
są szare z natury, więc filtr przeglądarki nie jest potrzebny; OSM zostaje podkładem,
który użytkownik może dodać w ustawieniach. Test `-m live`:
`tests/integration/test_basemap_live.py`.

---

## ADR-017: Warianty grupowane bez formatu plików

**Data:** 2026-10-17
**Status:** Przyjęta

**Kontekst:** Raport dostępności Kartografa zwraca kombinacje z formatem, więc ten
sam zestaw arkuszy w dwóch formatach wygląda jak dwa warianty. Przykład: NMT 2019,
5 m, EVRF2007, zgłoszenie DFT.7201.003.2019 jest dostępny jako `ASC` i `ASCII-NMT`.
Dwie karty o tym samym roku, pokryciu i arkuszach mylą i zawyżają liczniki
(„N wariantów”), a format nie zmienia tego, co obszar ma z danych.

**Opcje:**
- A) Wariant = kombinacja raportu 1:1 (format w kluczu), jak do tej pory.
- B) Wariant = (produkt, rok, układ poziomy, rozdzielczość, układ wysokości,
  zgłoszenie/kampania); formaty tego samego zestawu to plakietki jednej karty,
  wybór formatu przy pobieraniu.
- C) Zmiana raportu Kartografa tak, by sam grupował formaty.

**Decyzja:** B (decyzja użytkownika 2026-10-17). Karta nosi plakietki, np. „5 m ·
EVRF2007 · ASC, ASCII-NMT”. Grupowanie robi Archiwista; `check_availability`
zostaje bez zmian (C odrzucona: raport opisuje to, co publikuje źródło).
Liczniki, tabela, oś czasu, „Stos”, „Katalog”, karta pliku, ranking roku
i plan asystenta liczą warianty, nie formaty (SPEC 6.3, 6.4, 7.4). Format
wybiera się dopiero w „Pobierz…” i „Oknie planu”, domyślnie pierwszy
rastrowy gotowy do mozaiki (ASC, GeoTIFF); gdy takiego brak, wybór jest
jawny. Mozaika przyjmuje wersje jednego formatu rastrowego (SPEC 8.2).
Plakietka magazynu liczy jednostki w wybranym formacie.

**Konsekwencje:** Klucz grupy to krotka wyliczana z kombinacji raportu i sidecarów
(format jest pomijany, zgłoszenie zostaje); różne zgłoszenia z tego samego roku to
osobne warianty. Plan pobrania musi przenosić format do polecenia Kartografa.
Rozszerza ADR-010 (etykiety dotyczą wariantu, nie formatu).

---

## ADR-018: Wzorce interfejsu po mockupie: czat, Stos, podglądy

**Data:** 2026-10-17
**Status:** Przyjęta (czat, podglądy; „Wachlarz” zastępuje „Stos” — errata 1, decyzja użytkownika 2026-10-17)

**Kontekst:** Po obejrzeniu mockupu użytkownik rozstrzygnął pytanie M6 (położenie
czatu), sformułował wymaganie dla „Stosu” (M4, P12) i ustalił zasadę wagi
zrzutów i podglądów.

**Opcje:**
- Czat: A) przypięty panel boczny na komputerze, szuflada na telefonie;
  B) panel dolny; C) pływające okno.
- „Stos”: A) płyty pod kątem jak dotąd; B) wachlarz warstw jak stos plików
  w docku macOS (każdy rok widoczny, wybrany powiększony); C) zniesienie widoku.
- Podglądy: A) pełne dane i PNG; B) niska rozdzielczość z nakładek przeglądowych,
  zrzuty WebP/JPEG ok. 1280 px.

**Decyzja:**
1. Czat: A. Na komputerze przypięty panel boczny (mapa się zwęża), na telefonie
   szuflada (SPEC 6.2, 7.5).
2. „Stos”: wymaganie — wybrany rok widoczny w całości (SPEC 5.4, 6.5 c). Kierunek:
   B (wachlarz); to, czy B jest ostatecznym wariantem, rozstrzygnie sprawdzenie
   w mockupie (M4, P12) — decyzja otwarta.
3. Podglądy: B. Podglądy rastrów w aplikacji są niskiej rozdzielczości, generowane
   z nakładek przeglądowych, nie z pełnych danych (SPEC 5.7; uzupełnia ADR-008).
   Zrzuty i podglądy w repozytorium to WebP albo JPEG, szerokość ok. 1280 px.

**Konsekwencje:** Rozstrzyga M6 (położenie) i zawęża M4/P12 do wyboru wariantu
układu; układ „Stosu” z szablonu pochylonych płyt może się zmienić. Podglądy
służą rozpoznaniu, nie analizie; pełne dane otwiera się w QGIS.

**Errata 1 (2026-10-17, decyzja użytkownika po sprawdzeniu mockupu):** „Wachlarz”
**całkowicie zastępuje „Stos”** — pkt 2 decyzji rozstrzygnięty wariantem B, a widok
„Stos” (płyty pod kątem, opcja A) usunięty ze specu i z mockupu wraz z przełącznikiem
„Wachlarz / Stos”. Widok nazywa się „Wachlarz” (przełącznik „Mapa / Wachlarz /
Katalog”): warstwy lat (kampanii, wydań) jako miniatury obszaru na łuku jak stos
plików w docku macOS, najnowszy rok na górze, każda miniatura w całości we własnym
miejscu, wybrana powiększona w łuku i duża obok; miniatury pokazują obrysy arkuszy
w kolorach pokrycia, a arkusze w magazynie — z lekkim podglądem (pkt 3). To komponent
SVG interfejsu, nie warstwa mapy: odpadają `fill-extrusion`, nachylenie kamery
i tekstury w deck.gl (errata 1 ADR-006). Rozstrzyga M4 i P12 (SPEC 5.4, 6.5 c, 15, 16).
Wzmianki o „Stosie” w ADR-005, ADR-006 i ADR-017 opisują stan z chwili decyzji;
obowiązuje „Wachlarz”.

---

## ADR-019: Dwóch producentów magazynu: Kartograf i IMGWTools

**Data:** 2026-10-17
**Status:** Przyjęta (decyzja użytkownika 2026-10-17); częściowo zastępuje ADR-003, uzupełnia ADR-014; uzupełniona przez ADR-024 (adaptery jako wtyczki)

**Kontekst:** Użytkownik chce w Archiwiście v1.0 danych pomiarowych IMGW-PIB: hydro
dobowych (H, Q, T), charakterystyk miesięcznych i półrocznych oraz meteo (opad,
temperatura), bez danych bieżących. ADR-003 („zapisy wyłącznie przez Kartografa”)
i ADR-014 („wiedza o formacie tylko w Kartografie”) zakładały jednego producenta
magazynu. IMGWTools 2.1.1 (Beta) zna format IMGW (URL-e, parsery, listy stacji), ale
nie ma magazynu: zapisuje płasko i nieatomowo, bez sidecarów, sum i wersji, a nazwy
dobowych i terminowych archiwów meteo się zderzają. Analiza z 2026-10-17
rekomendowała IMGW jako źródło Kartografa; użytkownik wybrał adapter IMGW
w Archiwiście — Kartograf zostaje przy danych przestrzennych.

**Opcje:**
- A) Archiwista czyta płaski katalog `imgw fetch` albo cache SQLite IMGWTools własnym czytnikiem.
- B) IMGW jako źródło Kartografa: Kartograf jedynym pisarzem, IMGWTools jego opcjonalną zależnością.
- C) IMGWTools zapisuje w drzewie i formacie Kartografa (`data/`, `kartograf-meta/1`).
- D) Dwóch producentów, każdy we własnym katalogu i z własnym, udokumentowanym
  kontraktem formatu; Archiwista czyta każdego przez osobny adapter za wspólnym
  interfejsem źródła.
- E) Wspólna biblioteka kontraktu magazynu dla obu producentów.

**Decyzja:** D (decyzja użytkownika 2026-10-17):
1. Magazyn w Archiwiście to nazwany zestaw katalogów producentów: katalog Kartografa
   (`output_dir`, układ `data/`) i katalog IMGW (IMGWTools, `imgw-store/1`); żaden nie
   leży wewnątrz drugiego. Każdy producent pisze tylko swój katalog i jest jedynym
   właścicielem jego formatu.
2. Archiwista nadal nigdy nie pisze do magazynu; indeks jest lokalny i odbudowywalny,
   bez SQLite na udziale (ADR-002 i część „tylko odczyt” ADR-003 bez zmian).
3. Osobny adapter na producenta (`archiwista/adapter/kartograf/`,
   `archiwista/adapter/imgw/`) jest jedynym miejscem importu jego biblioteki (test
   importów jak w ADR-004); adaptery implementują wspólny interfejs źródła
   (SPEC 5.3), a reszta Archiwisty zna tylko ten interfejs.
4. Adapter IMGW nie parsuje plików: czyta przez publiczne API odczytu IMGWTools
   (IMGW-10), tak jak adapter Kartografa przez KA.
5. Działania na danych IMGW (synchronizacja archiwów, szeregi, eksport) wykonuje
   IMGWTools w procesach roboczych; Archiwista pokazuje plan i polecenie `imgw …`.
6. IMGWTools zapisuje surowe archiwa IMGW 1:1 jako niezmienne wersje z sidecarem,
   `sha256`, `ETag` i `Last-Modified` oraz szeregi stacji jako produkt pochodny;
   kontrakt to wymagania IMGW-1..IMGW-13 (SPEC 12.7) i format z ADR-020.
7. Dane IMGW nie są zadaniami projektu Kartografa (manifest przyjmuje tylko jego
   komendy); odtwarzalność dają niezmienne wersje i zestaw (SPEC 4.7, 8.4; P18).

A daje brak wersji i odtwarzalności, połowiczne pliki i SQLite (WAL) wykluczony na
udziale, a wiedzę o formacie IMGW przenosi do Archiwisty (łamie ADR-014). B rozszerza
zakres Kartografa poza dane przestrzenne, czego użytkownik nie chce. C to dwie
implementacje jednego formatu w jednym drzewie: `iter_store` Kartografa widziałby
obce segmenty, `kartograf_version` i pola przestrzenne nic by nie znaczyły, a pierwsza
rozbieżność łamie gwarancje Kartografa. E wymaga refaktoru świeżo wydanego magazynu
Kartografa i trzech repozytoriów w kroku; przy dwóch producentach to przedwczesne
(zostaje drogą, gdy dojdzie trzeci).

**Konsekwencje:** Errata ADR-003 (pisarze: Kartograf albo IMGWTools, każdy we
własnym katalogu) i ADR-014 (wiedza o formacie u każdego producenta). Wymagania
IMGW-1..IMGW-13 wobec IMGWTools; dane IMGW wchodzą w v0.9 (SPEC 13) i zależą od
wydania IMGWTools z kontraktem. Semantykę wersji implementują dwa repozytoria
(ADR-036 Kartografa i katalog IMGW) — ograniczeniem jest prostszy kontrakt IMGW
(tylko przyrost, bez dowiązań i plików zmiennych) i testy kontraktu po obu stronach
(SPEC 11, 14). Interfejs źródła powstaje w v0.1 z jednym adapterem, a test z atrapą
drugiego pilnuje, że warstwy wyżej nie zależą od Kartografa. Konfiguracja magazynu
wskazuje katalogi producentów; zadania w tle i propozycje asystenta niosą polecenia
obu producentów (`producer`, SPEC 9.1).

**Errata 1 (2026-10-17, decyzja użytkownika — SPEC 15, P18):** pkt 7 nie obowiązuje:
dane IMGW są zadaniami projektu i przypięciami w v1.0 — w manifeście IMGWTools
`imgw-project.json` (`imgw-project/1`) obok `kartograf-project.json`, zmienianym
wyłącznie przez API IMGWTools (wymaganie IMGW-14; ADR-023). Zasada jednego właściciela
formatu (pkt 1) zostaje: manifest Kartografa się nie zmienia. Wymagania wobec
IMGWTools to odtąd IMGW-1..IMGW-14 (SPEC 12.7, `docs/IMGWTOOLS_REQUIREMENTS.md`).

**Errata 2 (2026-10-17, decyzja użytkownika — ADR-024):** adaptery producentów są
wtyczkami: Kartograf jest wymaganą zależnością, IMGWTools extra `archiwista[imgw]`;
brak IMGWTools oznacza źródło niedostępne, nie awarię (SPEC 5.3).

---

## ADR-020: Format danych IMGW: własny sidecar, Parquet, GeoJSON

**Data:** 2026-10-17
**Status:** Proponowana — wymaganie wobec IMGWTools; ostateczny kształt ustali ADR IMGWTools (SPEC 12.7–12.8)

**Kontekst:** ADR-019 oddaje zapis danych IMGW IMGWTools z własnym kontraktem
formatu. Trzeba wybrać schemat sidecara (własny czy zgodny z `kartograf-meta/1`),
format szeregów stacji i format katalogu stacji. Szereg dobowy stacji 1951–2025 to
ok. 27 tys. dni z kilkoma zmiennymi i flagami; stacji jest ok. 1 300 hydro i ok.
2 150 meteo. Katalog może leżeć na SMB bez blokad zakresów bajtów, a rdzeń IMGWTools
jest lekki (`httpx`, `pydantic`).

**Opcje:**
- Sidecar: A) zgodność z `kartograf-meta/1`; B) własny `imgw-meta/1` ze wspólną kopertą pól.
- Szeregi: C) GeoPackage (punkty, obserwacje i pokrycie w jednym pliku na obszar albo
  kraj); D) Parquet — plik na stację w niezmiennej wersji szeregów zbioru, ze spisem
  `series.json`; E) CSV.
- Katalog stacji: F) GeoPackage; G) GeoJSON (RFC 7946).

**Decyzja:** B, D i G.
- B: format zna i rozwija tylko jego producent (ADR-019), a nazwa schematu mówi, kto
  zapisał plik — `kartograf-meta/1` od IMGWTools myliłby `read_sidecar` Kartografa,
  wtyczkę QGIS i Hydrografa (np. polem `kartograf_version`). Pola przestrzenne
  (`horizontal_crs`, `vertical_crs`, `resolution`, `nodata`, `transform`) nic nie
  znaczą dla archiwów i szeregów, a potrzebne są jednostki, kody braków, okresy
  i stacje. Wspólna koperta (te same nazwy i znaczenia `schema`, `dataset`,
  `country`, `provider`, `request`, `license`, `downloaded_at`, `sha256`,
  `size_bytes`, `extra.version`, `extra.http`, `extra.derived`,
  `extra.source_files[]`) daje to, co dałaby zgodność — wspólne kolumny indeksu,
  tę samą logikę wersji i wejść, kształt HSG — bez sprzęgania producentów.
- D: typowane kolumny (data, wartości, flagi) z kompresją; plik niezmienny i bez
  blokad, więc bezpieczny do czytania na SMB; czytany wprost przez pandas, polars,
  pyarrow, DuckDB i R (Hydrolog, Retman, skrypty); plik na stację daje mały odczyt
  do wykresu i zestawu, a spis `series.json` z listami przerw — indeks pokrycia
  z jednego pliku. GeoPackage to SQLite: zapis na udziale wymaga budowy lokalnie
  i kopii, plik obszaru dubluje stacje między zadaniami, a plik krajowy trzeba
  czytać przez zapytania; CSV nie niesie typów ani metadanych — zostaje formatem
  eksportu do zestawu (IMGW-12).
- G: kilka tysięcy punktów; zapis bez GDAL (lekki rdzeń IMGWTools), plik czytelny
  i porównywalny między wersjami, otwierany wprost w QGIS; brak położenia wyrażony
  jawnie (`geometry: null`).

**Konsekwencje:** Zapis i odczyt Parquet idą do dodatku IMGWTools (np.
`imgwtools[store]` z pyarrow); rdzeń zostaje lekki. Excel nie czyta Parquet, a QGIS
— tylko z GDAL z obsługą Arrow, więc zestaw dostaje szeregi w CSV z eksportu
IMGWTools. Wersja szeregów zbioru to migawka wszystkich stacji (prosta tożsamość
i lata znane z jednego spisu) za cenę pełnej kopii plików przy każdej nowej wersji
— ograniczeniem jest `reused` przy tym samym zestawie `sha256` wejść i tej samej
wersji schematu (wzór HSG, ADR-036 D33), co chroni też przed wersjami różnymi tylko
bajtami zapisu biblioteki Parquet. Koperta jest kandydatem na wspólny `store-meta/1`,
gdyby doszedł trzeci producent.

**Errata 1 (2026-10-17, decyzje użytkownika — SPEC 15, P13–P15, P18):** kolumna
`hydro_year` jest w plikach szeregów wszystkich zbiorów, także meteo (oba rodzaje lat
dla obu rodzajów danych, P15); szeregi zbioru obejmują wszystkie stacje, także
z lukami (P14); stacja bez położenia jest w `stations.geojson` z `geometry: null`
i powodem braku (P13, ADR-022); dochodzi schemat `imgw-project/1` (ADR-023), objęty tą
samą polityką wersji (SPEC 12.7: IMGW-7, IMGW-9, IMGW-13, IMGW-14).

---

## ADR-021: Etykiety pokrycia szeregów IMGW

**Data:** 2026-10-17
**Status:** Przyjęta (P14, P15 — errata 1; P16 — errata 2; decyzje użytkownika 2026-10-17); Proponowana (mockup: M11)

**Kontekst:** Użytkownik chce etykiet pokrycia szeregów stacji w czasie, np. „ciągły
1951–2024”, „luki 3%”, zdefiniowanych precyzyjnie. Pokrycie stacji znane jest
dopiero z archiwów w magazynie (IMGW nie publikuje indeksu stacji); archiwa hydro
są numerowane rokiem hydrologicznym, meteo — kalendarzowym; brak Q nie oznacza
braku H; Hydrolog ostrzega przy szeregach krótszych niż 30 lat.

**Opcje:**
- A) Same liczby (procent dni z wartością).
- B) „Ciągły” z tolerancją (np. do 0,1% braków).
- C) Pięć etykiet z definicjami: „ciągły” (zero braków), „luki N%” (zaokrąglenie
  w górę, „<1%”) z najdłuższą przerwą, „częściowy” (stacja zaczyna albo kończy
  w trakcie zakresu), „brak danych”, „nieznane” (bez archiwów); osobno dla każdej
  zmiennej; rodzaj lat wg zbioru z przełącznikiem.

**Decyzja:** C (definicje: SPEC 4.8.4). „Ciągły” to fakt, nie ocena — tolerancja
ukrywałaby braki, które Hydrolog i tak napotka; przydatność mówi osobno liczba lat
pełnych i filtr „≥ 30 lat pełnych”. Zaokrąglenie braków w górę jest ostrożne jak
„nigdy 100%” w ADR-010. Lata nieznane (archiwa niepobrane, szeregi nieprzygotowane)
nie są lukami i dostają dopisek „· nieznane”. Etykiety liczy serwer z list przerw
w spisie szeregów (IMGW-8), więc zmiana zakresu i rodzaju lat nie wymaga czytania
szeregów.

**Konsekwencje:** IMGWTools zapisuje w spisie szeregów pierwszą i ostatnią datę oraz
listę przerw dla każdej zmiennej; Archiwista liczy etykiety, lata pełne i oś czasu
(indeks `series_years`), a interfejs, API i asystent mają jedno słownictwo.
Uzupełnia ADR-010 (etykiety obszaru) o wymiar czasu.

**Errata 1 (2026-10-17, decyzje użytkownika — SPEC 15, P14, P15):**
- P14: „ciągły” = zero braków (potwierdzone). Pobiera się i pokazuje **wszystkie**
  dane, także z brakami, z etykietą; nic nie jest odfiltrowywane z powodu braków —
  mapa, „Zestawienie”, „Katalog”, zestaw, eksport i propozycje asystenta obejmują
  każdą stację, a filtry pokrycia („≥ 30 lat pełnych”) działają tylko jawnie
  (SPEC 4.8.4).
- P15: oba rodzaje lat dla **obu** rodzajów danych (hydro i meteo) z przełącznikiem
  (wcześniej: „rodzaj lat wg zbioru z przełącznikiem”). Domyślnie hydro —
  hydrologiczny, meteo — kalendarzowy; wybór zapamiętywany osobno dla hydro i meteo
  w ustawieniach użytkownika (w zespole — przy koncie), `year_type` w adresie URL ma
  pierwszeństwo; widok mieszany używa wyboru dla hydro; charakterystyki półroczne
  i roczne zostają w latach hydrologicznych, bo IMGW liczy je w półroczach XI–IV
  i V–X (SPEC 4.8.2, 6.7). Potwierdzone przez użytkownika 2026-10-17:
  charakterystyki półroczne i roczne IMGW są tylko w latach hydrologicznych,
  a przełącznik rodzaju lat ich nie dotyczy.
- P16: patrz errata 2.

**Errata 2 (2026-10-17, decyzja użytkownika — SPEC 15, P16):** P16 rozstrzygnięte —
etykiety pokrycia są liczone i pokazywane **osobno dla każdej wielkości**, nie jedna
na stację: hydro — H, Q i T; meteo — opad, temperatura powietrza (Tmax, Tmin, Tśr)
i inne zmienne zbioru. Stacja nie ma etykiety zbiorczej. Zmienia wcześniejszą
rekomendację („jedna zmienna naraz”): panel stacji, „Zestawienie”, „Katalog”
i karta stacji pokazują etykiety wszystkich zmiennych stacji razem; mapa koloruje
punkt według jednej zmiennej wybranej chipem („Kolor punktów”), ale podpowiedź
punktu podaje wszystkie; filtry pokrycia (lata pełne, etykieta) dotyczą wskazanej
zmiennej i łączą się spójnikiem „i”, więc brak Q nie ukrywa H; API zwraca
`coverage` osobno dla każdej zmiennej (SPEC 9, `GET /stations`). Model (SPEC 4.8.4,
indeks `series_years`) i IMGW-8 liczyły już pokrycie per zmienna — zmienia się
prezentacja, filtrowanie i kształt odpowiedzi API, nie kontrakt formatu IMGWTools
(wymagania IMGWTools: IMGW-8).

---

## ADR-022: Dane bez położenia: Katalog zamiast mapy

**Data:** 2026-10-17
**Status:** Przyjęta (decyzja użytkownika 2026-10-17; SPEC 15, P13)

**Kontekst:** Część danych nie ma położenia: z 2 149 kodów listy meteo IMGWTools
publiczne API IMGW ma współrzędne 562 stacji, 32 stacje API hydro mają zastępcze
`0,0`, stacje zamknięte często nie mają współrzędnych w żadnym źródle; po stronie
Kartografa są pliki, dla których `file_footprint` nie znajduje zasięgu („bez
obrysu”), a archiwa i szeregi IMGW mają zasięg całego kraju. Pytanie P13 dotyczyło
źródła współrzędnych stacji meteo; użytkownik rozstrzygnął, że stacji bez
współrzędnych nie pokazuje się na mapie, a Archiwista potrzebuje drugiego sposobu
prezentacji danych bez odniesienia przestrzennego — ogólnie, nie tylko dla IMGW.

**Opcje:**
- A) Przybliżone położenie na mapie (np. środek kwadratu 1° z kodu stacji) z oznaczeniem.
- B) Osobna lista „Bez położenia” tylko dla stacji IMGW, obok mapy.
- C) Ogólna zasada dla wszystkich producentów: mapa pokazuje wyłącznie obiekty
  z położeniem, a wszystkie obiekty — także bez położenia — pokazuje widok bez mapy
  („Katalog”: lista i karty z wyszukiwaniem i filtrami atrybutów); mapa ma licznik
  obiektów bez położenia z przejściem do „Katalogu”.

**Decyzja:** C (decyzja użytkownika 2026-10-17). A zgaduje położenie (kwadrat 1° to
dziesiątki kilometrów) i łamie zasadę „nigdy zgadywanie”; B rozwiązuje jeden
przypadek i zostawia pliki „bez obrysu” Kartografa bez widoku. Zasady (SPEC 4.3,
6.8):
1. Każdy obiekt indeksu ma rodzaj położenia: `footprint`, `point`, `country` albo
   `none` z powodem (pliki: `no_source`, `unreadable`; stacje: powód z katalogu stacji
   IMGWTools — `none`, `zero`, `outside_country`).
2. Mapa rysuje tylko `footprint` i `point`; położenie nigdy nie jest zgadywane.
3. „Katalog” (pozycja nawigacji i tryb „Mapy”) pokazuje wszystkie rodzaje położenia;
   filtr obszaru dzieli wynik na grupy „w obszarze”, „na granicy obszaru”, „cały
   kraj”, „bez położenia” z licznikami, a grupy „bez położenia” nigdy nie dołącza do
   obszaru ani z niego nie usuwa po cichu. Obiekty bez położenia wybiera się filtrami
   atrybutów (rzeka i kod hydrograficzny z dopływami — P19, nazwa, kod, kraj,
   jednostka); kwadrat 1° z kodu stacji jest tylko zgrubną wskazówką.
4. Każdy widok mapy z wynikiem podaje licznik obiektów bez położenia z przejściem do
   „Katalogu” z tymi samymi filtrami.
5. Położenie uzupełnia producent (np. nowa wersja katalogu stacji IMGWTools z plikiem
   współrzędnych użytkownika); Archiwista go nie zapisuje.

**Konsekwencje:** Indeks trzyma rodzaj położenia i powód braku (`versions`,
`stations`); API `GET /slots` i `GET /stations` przyjmują `location` i zwracają grupy
z licznikami; katalog stacji IMGWTools zapisuje stacje bez położenia jako pełnoprawne
wpisy (`geometry: null` z powodem, IMGW-9). Stacje bez położenia trafiają do zadań
projektu i zestawów tylko jawnie, a w zestawie są tabelą, nie warstwą mapy. „Katalog”
jest w v0.1 (pliki „bez obrysu”) i w v0.9 (stacje). Źródła współrzędnych z P13 (API
IMGW, plik użytkownika, wniosek do IMGW-PIB o wykaz) pozostają uzupełnieniem.

---

## ADR-023: Dane IMGW w projektach: manifest IMGWTools

**Data:** 2026-10-17
**Status:** Przyjęta (dane IMGW w manifeście projektu w v1.0 i dwa pliki manifestu, `kartograf-project.json` i `imgw-project.json` — decyzja użytkownika 2026-10-17, potwierdzona; SPEC 15, P18)

**Kontekst:** ADR-019 pkt 7 i dotychczasowa rekomendacja P18 wyłączały dane IMGW
z projektów w v1.0, bo manifest `kartograf-project/1` przyjmuje tylko komendy
Kartografa; odtwarzalność dawał sam zestaw (`zestaw.json`). Użytkownik zdecydował, że
dane IMGW mają być w manifeście projektu już w v1.0: zadania (stacje, zmienne, lata)
i przypięte wersje, z „Statusem”, „Weryfikuj”, aktualizacją i odtwarzaniem u kolegi
— tak jak dane Kartografa. Zadanie IMGW ma trafiać do projektu przez API IMGWTools.

**Opcje:**
- A) Zadania IMGW w `kartograf-project.json` (Kartograf przyjmuje obce komendy albo
  woła IMGWTools).
- B) Wspólny manifest producentów (np. `store-project/1`) i wspólna biblioteka
  projektu dla obu producentów.
- C) Manifest IMGWTools `imgw-project.json` (`imgw-project/1`) w tym samym katalogu
  projektu obok `kartograf-project.json`; każdy manifest ma jednego właściciela,
  a Archiwista pokazuje projekt jako sumę obu.
- D) Bez manifestu: wybór IMGW tylko w zestawie (dotychczasowa rekomendacja).

**Decyzja:** C. Zgodna z ADR-019 (każdy producent jest jedynym właścicielem swojego
formatu, żadnej zależności między Kartografem a IMGWTools) i z ADR-014 (Archiwista nie
pisze formatów producentów). A łamie oba: Kartograf musiałby znać komendy IMGW albo je
uruchamiać, a `kartograf-project/1` zmieniłby się poza rozszerzenia addytywne. B to
refaktor świeżo wydanego manifestu Kartografa i trzech repozytoriów w kroku —
przedwczesny przy dwóch producentach (jak opcja E w ADR-019). D nie spełnia decyzji
użytkownika. Kształt (SPEC 12.7, IMGW-14): `schema`, `store_dir`, `tasks[]` (`name`,
`command`, `options` — zbiór, stacje jako jawna lista kodów, zmienne, lata,
`year_type`; przy wyborze obszarem także `geometry` i `geometry_sha256`), `pinned_at`,
`imgwtools_version`, `files[]` (`role`, `path` wersji względna do `store_dir`,
`sha256`, `station`); API = CLI (`init_project`, `open_project`, `add_project_task`,
`remove_project_task`, `download_project`, `check_project`, `verify_project`,
`get_project_status`; `imgw project …`); zapis atomowy pod blokadą
`.imgw-project.lock` — wzorem manifestu Kartografa.

**Konsekwencje:** Nowe wymaganie IMGW-14 (v0.9, potrzebne do v1.0). Archiwista
odkrywa projekty po obu plikach, pokazuje zadania obu producentów z kolumną
producenta, a „Dodaj do projektu…” dla stacji otwiera „Okno planu” z poleceniem
`imgw project add` i woła API IMGWTools w procesie roboczym (SPEC 4.7). Zestaw bierze
wersje IMGW z przypięć, `zestaw.json` zapisuje sumy obu manifestów, `polecenia.sh` —
`imgw project download` (SPEC 8.4). Ryzyko niespójności dwóch manifestów (np. ta sama
nazwa zadania) ogranicza widok projektu z ostrzeżeniem (SPEC 14). Gdy dojdzie trzeci
producent, wraca opcja B. Zmienia pkt 7 ADR-019 (errata 1).

**Errata 1 (2026-10-17, decyzja użytkownika — SPEC 15, P18):** potwierdzone dwa pliki
manifestu (opcja C): `kartograf-project.json` i `imgw-project.json`; status
zmieniony z „Proponowana” na „Przyjęta”. Nazwy pól `imgw-project/1` zapisane
w wymaganiu IMGW-14 pozostają nazwami z wymagań dla IMGWTools (tak jak w
wszystkich wymaganiach IMGW-n), bez wpływu na status decyzji.

---

## ADR-024: Źródła danych jako wtyczki: Kartograf wymagany, IMGWTools opcjonalny

**Data:** 2026-10-17
**Status:** Przyjęta (decyzja użytkownika 2026-10-17); uzupełnia ADR-001 i ADR-019

**Kontekst:** ADR-001 przyjął Kartografa jako zależność, a ADR-019 dodał drugiego
producenta, IMGWTools, za wspólnym interfejsem źródła. Nie rozstrzygnęły one, jak
Archiwista deklaruje obie biblioteki w pakiecie. IMGWTools 2.1.1 jest w wersji Beta,
jeszcze bez kontraktu magazynu (IMGW-1..IMGW-14), a Kartograf jest podstawą v0.1..v0.8.
Wydania Archiwisty nie mogą czekać na IMGWTools, a konflikty wersji bibliotek
naukowych obu producentów nie mogą uniemożliwiać instalacji osobom, które IMGW nie
interesuje. Użytkownik zdecydował o modelu wtyczek.

**Opcje:**
- A) Obie biblioteki wymagane.
- B) Kartograf wymagany, IMGWTools opcjonalny (extra), adaptery źródeł rejestrowane
  jako wtyczki przez entry points.
- C) Bez zależności od producentów: Archiwista czyta formaty plików i wywołuje CLI.
- D) Producenci jako usługi HTTP.

**Decyzja:** B (decyzja użytkownika 2026-10-17):
1. Kartograf jest wymaganą zależnością pakietu `archiwista` (`kartograf>=0.9,<0.10`;
   dokładny zakres ustala się przy wydaniu Archiwisty).
2. IMGWTools jest extra `archiwista[imgw]`; instalacja: `pip install archiwista`
   albo `pip install "archiwista[imgw]"`.
3. Adaptery źródeł (ADR-019 pkt 3) są rejestrowane przez entry points, np. w grupie
   `archiwista.sources`. Brak pakietu producenta oznacza „źródło niedostępne”,
   a nie awarię aplikacji:
   - interfejs ukrywa widoki stacji IMGW (warstwę stacji, „Zestawienie” i „Kartę
     stacji”);
   - API zwraca jasny błąd źródła niedostępnego (kod i komunikat po polsku, SPEC 9.1);
   - asystent nie oferuje narzędzi IMGW (SPEC 7.3).
4. Przy starcie (i w `archiwista doctor`) Archiwista sprawdza wersje producentów
   i schematy, które czyta: `kartograf-meta/1`, `kartograf-project/1`, `imgw-meta/1`,
   `imgw-project/…`; niezgodność kończy się czytelnym komunikatem po polsku (co jest
   zainstalowane, jaki zakres jest wspierany, co zrobić) i dotyczy tylko źródła,
   którego dotyczy.
5. Jeden plik blokady zależności (lock) dla spójnego zestawu bibliotek naukowych
   (z extra `[imgw]` włącznie), żeby oba źródła działały w jednym środowisku.
6. CI w dwóch konfiguracjach: bez `[imgw]` i z `[imgw]`, plus testy kontraktu
   względem gałęzi `develop` producentów (wczesne wykrycie zmian łamiących).
7. Trzeci producent to nowa wtyczka (nowy adapter i entry point) bez zmian
   w warstwach wyżej.

Odrzucone: A — IMGWTools w wersji Beta blokowałby wydania Archiwisty, a konflikty
wersji bibliotek naukowych utrudniałyby instalację; C — bez zależności, z czytaniem
formatów i wywoływaniem CLI, łamie ADR-014 (wiedza o formacie tylko u producenta);
D — usługi HTTP: koszt (dodatkowe procesy, uwierzytelnianie, wdrożenie).

**Konsekwencje:** Zmiany w SPEC: 5.1–5.3 i 5.5 (interfejs źródła, rejestracja
wtyczek, instalacja i konfiguracja), 7.3 (narzędzia zależne od dostępnych źródeł),
9.1 (błąd źródła niedostępnego), 11 (dwie konfiguracje CI, testy kontraktu), 13
(v0.1: mechanizm wtyczek z atrapą drugiego adaptera; v0.9: extra `[imgw]`), 14
(zależność od IMGWTools jest teraz opcjonalna). Test importów z ADR-019 zostaje,
a Archiwista bez IMGWTools przechodzi pełny zestaw testów poza testami IMGW.
Zależność od IMGWTools ogranicza już tylko v0.9, nie wydania v0.1..v0.8.

**Errata 1 (2026-10-18, decyzja użytkownika):** pkt 1 — zakres to `kartograf>=0.8.0,<0.9`,
nie `>=0.9,<0.10`: publiczny odczyt magazynu (KA-1..KA-6) wchodzi do Kartografa 0.8.0
(przygotowane, jeszcze nieotagowane wydanie; `__version__` = `0.8.0`). Test kontraktu
sprawdza obecność KA w `kartograf.__all__` i to, że zainstalowany `kartograf.__version__`
mieści się w zakresie z `pyproject.toml`; przed wydaniem Archiwisty powtarza się go
przeciw otagowanemu Kartografowi 0.8.0. SPEC 5.8.

---

## ADR-025: Zakres MVP i kolejność wydań

**Data:** 2026-10-17
**Status:** Przyjęta (decyzja użytkownika 2026-10-17)

**Kontekst:** Roadmapa SPEC 13 miała dziesięć wersji, a v1.0 obejmowało wszystko:
przeglądanie, podglądy, działania, zestaw do QGIS, asystenta, łączenie, tryb zespołu
i dane IMGW. Przed planem implementacji użytkownik chce dokładnie ustalić wymagania
produktu i zakres (nowe dokumenty `docs/PRD.md` i `docs/SCOPE.md`, wzór rodziny
projektów: Hydraulik, Kartograf, Hydrolog).

**Opcje:**
- A) Zostawić v1.0 jako całość roadmapy.
- B) Wydzielić MVP z wybranych obszarów, resztę przenieść za MVP.

**Decyzja:** B (decyzja użytkownika 2026-10-17). MVP = v1.0 i obejmuje: Przeglądarkę,
Podglądy i Wachlarz, Działania, Tryb zespołu, Dane IMGW. Po MVP: Zestaw do QGIS,
Asystent, Łączenie. Nowa numeracja (stara → nowa): v0.1, v0.2, v0.3 bez zmian;
v0.8 „Zespół” → v0.4; v0.9 „Stacje IMGW” → v0.5; v1.0 „Wydanie” → v1.0 „Wydanie
(MVP)”; v0.4 „Zestaw” → v1.1; v0.5 „Asystent” → v1.2; v0.6 „Mozaika i porównanie”
→ v1.3; v0.7 „PL + CZ” → v1.4. Części dawnego v0.9 zależne od zestawu i asystenta
(zestaw z danymi IMGW, narzędzia asystenta IMGW, UC-18) przechodzą do v1.1 i v1.2.
Wymagania KB-6, KD-3, KD-4 idą z „Zestawem” (v1.1) — do potwierdzenia (PRD, otwarte
decyzje). Przed v0.1 dochodzi etap 0 „Architektura i plan” (architektura otwarta:
ADR-004..008, 015).

**Konsekwencje:** Kolejność i zakres wydań określa `docs/SCOPE.md`; SPEC 13 trzyma
szczegóły i kryteria akceptacji w nowej numeracji; SPEC i `docs/IMGWTOOLS_REQUIREMENTS.md`
przenumerowane. Wcześniejsze wpisy tego rejestru zachowują numerację z chwili decyzji
(np. „v0.9” w ADR-019..024 = dzisiejsze v0.5, „v0.8” = v0.4). MVP zależy od wydania
IMGWTools z IMGW-1..IMGW-14; tryb zespołu wchodzi do MVP przed danymi IMGW.

**Errata 1 (2026-10-18, decyzja użytkownika):** KD-4 (dostępność wydań produktów
jednostkowych, np. BDOT10k) przechodzi z v1.1 do v0.3, żeby produkty bez arkuszy miały
w MVP etykiety pokrycia i pełne widoki (PRD F6.3, „Widoki według rodzaju danych”).
KD-3 i KB-6 zostają w v1.1 — nadal do decyzji.

**Errata 2 (2026-10-18, decyzja użytkownika):** KD-3 (dostępność obrazów PL: lata
i pełność arkuszy ortofotomapy, true orto i intensywności) przechodzi do v0.3 — bez
niego ortofotomapa w MVP nie ma lat z etykietami pokrycia (PRD F6.4). KB-6 („Polecenie
Kartografa” i „Dodaj do projektu” z karty pliku) zostaje w v1.1: w MVP do projektu
dodaje się dane z wyniku dostępności.

**Errata 3 (2026-10-18, decyzja użytkownika):** wydanie „PL + CZ” zmienia numer
z v1.4 na v0.6 i wchodzi do MVP (między v0.5 „Stacje IMGW” a v1.0). Zakres v0.6:
zestawienie PL + CZ bez scalania (grupa `parent_request`, kontrola zgodności),
scalona powierzchnia przygraniczna przez KF Kartografa (SPEC 8.3) oraz stacje ČHMÚ
przez IMGWTools w widokach v0.5 (SPEC 4.8.6, wymagania IMGW-15..IMGW-19). Eksport
PL + CZ bez scalania do zestawu QGIS zostaje w v1.1. Po MVP: v1.1 „Zestaw”, v1.2
„Asystent”, v1.3 „Mozaika i porównanie”. Konsekwencje: KF (dziś R6 w backlogu
Kartografa, poza publicznym API 0.8.0) i dostawca ČHMÚ w IMGWTools (dziś szkic
„Obserwator”, bez kodu) blokują MVP — ryzyka w SCOPE i SPEC 14. Stacje ČHMÚ idą
przez adapter IMGW (wtyczka z ADR-024); osobny adapter tylko wtedy, gdy IMGWTools
wyda ČHMÚ jako osobny pakiet (pytanie otwarte w PRD). Zmiany: SPEC nagłówek, 2,
3 (UC-09, UC-20), 4.8.6, 5.3, 6.7, 8.3, 8.6, 10.2, 11, 12.5, 12.7, 13, 14; PRD F12,
F14, F17, założenia, miary sukcesu, otwarte decyzje; SCOPE; README; plan v0.1
(granice zakresu); `docs/IMGWTOOLS_REQUIREMENTS.md` (IMGW-15..IMGW-19).

---

## ADR-026: Licencja MIT i kontrybucje z CLA

**Data:** 2026-10-17
**Status:** Przyjęta (licencja MIT — SPEC 15, P8; CLA — errata 1, decyzja użytkownika 2026-10-18)

**Kontekst:** Repozytorium nie miało pliku licencji ani zasad kontrybucji. Wszystkie
projekty autora (Kartograf, Hydraulik, Hydrograf, Hydrolog, IMGWTools, Retman) są na
licencji MIT; Hydraulik ma dodatkowo `CONTRIBUTING.md`, `CONTRIBUTORS.md` (rejestr
podpisów) i `docs/CLA.md` — adaptację Apache ICLA 2.2 z odbiorcą wskazanym osobą
(Piotr de Bever), nie projektem.

**Opcje:**
- A) MIT, kontrybucje z CLA jak w Hydrauliku (podpis komentarzem w pull requeście).
- B) MIT, DCO (`Signed-off-by`) bez przeniesienia praw.
- C) MIT bez CLA (wkład na tej samej licencji, inbound = outbound).

**Decyzja:** A — wzór rodziny projektów. Pliki: `LICENSE` (MIT, Copyright (c) 2026
Piotr de Bever), `CONTRIBUTING.md` i `CONTRIBUTORS.md` po polsku (zasada językowa
Archiwisty), `docs/CLA.md` bez zmian względem Hydraulika (tekst prawny po angielsku;
odbiorca to osoba, więc ten sam tekst obowiązuje w każdym projekcie autora). Wybór CLA
zamiast B i C czeka na potwierdzenie użytkownika.

**Konsekwencje:** CLA zachowuje możliwość zmiany licencji w przyszłości; wymaga
ręcznego prowadzenia `CONTRIBUTORS.md` przy scalaniu. Zależności Archiwisty muszą mieć
licencje zgodne z MIT; zależność copyleft wymaga osobnej decyzji (PRD N7.2). CLA nie
był przeglądany przez prawnika (zastrzeżenie w `docs/CLA.md`).

**Errata 1 (2026-10-18, decyzja użytkownika):** CLA przyjęte („korzystamy z tego, co
już mamy”). Ten sam proces ma już IMGWTools (commit `999c8a7`: `docs/CLA.md` identyczny
z Hydraulikiem, `CONTRIBUTING.md`, `CONTRIBUTORS.md`, szablon pull requestu
`.github/pull_request_template.md`); pozostałe projekty (Kartograf, Hydrograf, Hydrolog,
Retman) mają tylko `LICENSE` MIT, żaden nie używa DCO. Archiwista dostaje też szablon
pull requestu z polem podpisu CLA (po polsku; bez punktów o testach, dopóki nie ma kodu).

**Errata 2 (2026-10-18, decyzja użytkownika):** polski w `CONTRIBUTING.md`,
`CONTRIBUTORS.md` i szablonie pull requestu to błąd — pliki dla kontrybutorów są po
angielsku, jak w Hydrauliku i IMGWTools (cały kod i to, co go opisuje, po angielsku;
`docs/DEVELOPMENT_STANDARDS.md` sekcja 0). Tłumaczenie to pierwsze zadanie
implementacji (`docs/PROGRESS.md`).

---

## ADR-027: Dane własne w katalogu projektu i migawki Archiwisty

**Data:** 2026-10-18
**Status:** Przyjęta (decyzja użytkownika 2026-10-18)

**Kontekst:** Użytkownicy mają własne zbiory (np. warstwę liniową sieci kanalizacyjnej),
które chcą widzieć na mapie razem z danymi projektu i wersjonować. Archiwista indeksował
dotąd tylko katalogi producentów (Kartograf, IMGWTools), a plik bez sidecara był
„problemem” magazynu; Kartograf nie zna plików, których nie pobrał. Użytkownik wybrał
folder tylko do odczytu w MVP, wersjonowanie migawkami całych plików i zdecydował, że
migawki robi Archiwista, bo użytkownicy sami nie będą ich robić konsekwentnie.

**Opcje:**
- Gdzie dane własne: A) folder przypisany do projektu; B) foldery w ustawieniach magazynu,
  niezależne od projektów; C) oba.
- Kto robi migawki: A) użytkownik (kopie z datą w nazwie), Archiwista je rozpoznaje;
  B) Archiwista w katalogu projektu; C) Kartograf przez API (dane własne w magazynie);
  D) osobny mały producent jako wtyczka.
- Co jest wersją: A) migawka całego pliku; B) historia pojedynczych obiektów.

**Decyzja:** folder przypisany do projektu (A), migawki robi Archiwista w katalogu
projektu (B), wersja = migawka całego pliku (A):
1. Folder danych własnych projektu — domyślnie `<katalog projektu>/dane/`, można wskazać
   inny; przypisanie w konfiguracji Archiwisty, nie w manifeście producenta. Folder jest
   indeksowany tylko do odczytu (rodzaj ogólny, PRD N8.3).
2. „Zrób migawkę” kopiuje plik do `<folder danych>/.wersje/<nazwa>/<RRRR-MM-DD>_<sha8>/`
   z `migawka.json` (`archiwista-snapshot/1`; nazwy katalogów i schematu — propozycja do
   planu v0.2). Kontrakt celowo najprostszy: tylko przyrost (bez nadpisywania, usuwania
   i dowiązań), zapis atomowy (katalog roboczy `.incoming/`, publikacja zmianą nazwy, błąd
   gdy cel istnieje), spójna kopia pliku w użyciu (GeoPackage przez kopię zapasową
   SQLite, formaty wieloplikowe jako komplet), ta sama treść = brak nowej migawki.
3. Migawki to wersje pliku w interfejsie (oś wersji, „Wachlarz”, kurtyna, porównanie
   metadanych); zmiana pliku od ostatniej migawki jest wykrywana skanem.
4. Zakres: v0.2 (MVP); w zespole migawkę robi „operator”.

Odrzucone: rozpoznawanie kopii robionych ręcznie — użytkownicy nie będą ich robić
konsekwentnie; Kartograf — dane prywatne w magazynie danych publicznych, nowa rola
Kartografa i zależność MVP od jego wydania; osobny producent — trzecia biblioteka do
utrzymania; historia obiektów — klasa narzędzia edycyjnego, poza granicami Archiwisty.

**Konsekwencje:** Archiwista po raz pierwszy zapisuje dane (kopie plików użytkownika),
ale wyłącznie w katalogu projektu i na polecenie użytkownika — jak pliki obszarów
i zestawy; magazyn producentów pozostaje tylko do odczytu (ADR-003, ADR-019 bez zmian).
Migawki nie są stanem Archiwisty: nie da się ich odbudować, więc są w otwartym formacie,
czytelne bez Archiwisty, i przenoszą się z katalogiem projektu. To trzecia implementacja
semantyki wersji (obok ADR-036 Kartografa i katalogu IMGW) — stąd minimalny kontrakt
i testy przerwania. Dane własne nie trafiają do manifestu projektu (brak przypięć,
„Weryfikuj” i odtworzenia u kolegi). Zmiany w SPEC: 1.3, 2, 4.7.1, 10.1, 13 (v0.2);
PRD F15, N2.5; SCOPE.

**Errata 1 (2026-10-18, decyzja użytkownika, ADR-029):** w zespole migawkę robi
właściciel projektu albo administrator (rola „operator” zniknęła); widoczność danych
własnych i migawek wynika z widoczności projektu.

---

## ADR-028: Interfejs w Preact + htm bez kroku budowania

**Data:** 2026-10-18
**Status:** Przyjęta (decyzja użytkownika 2026-10-18); zastępuje ADR-005

**Kontekst:** Etap 0 (SCOPE) ponownie rozstrzyga architekturę. ADR-005 wybrał Svelte
z Vite, co wprowadza drugi ekosystem (Node.js, krok budowania) — ryzyko kosztu
utrzymania (SPEC 14). Tymczasem mockup (SPEC 16) działa w Preact + htm bez budowania
i sprawdził główny ekran: mapę, Wachlarz, Katalog, panele, zadania, dane własne.

**Opcje:**
- A) Svelte 5 + TypeScript + Vite (ADR-005).
- B) Preact + htm, moduły ES bez kroku budowania, biblioteki dołączone do pakietu.
- C) Szablony serwerowe + htmx.

**Decyzja:** B. Jeden ekosystem narzędzi (Python); mockup jest punktem wyjścia
interfejsu; biblioteki (Preact, htm, MapLibre) leżą w pakiecie jako pliki ES modules —
bez CDN, działa offline i spełnia CSP z SPEC 10.1. Zasady z ADR-005 zostają: jedno API
HTTP („API najpierw”), stan widoku w adresie URL.

Odrzucone: A — drugi ekosystem do utrzymania i przepisanie mockupu; C — główny ekran to
aplikacja mapowa ze wspólnym stanem, który w htmx rozpada się na fragmenty HTML
i ręczny JS.

**Konsekwencje:** Brak kontroli typów w interfejsie — ograniczają to testy w przeglądarce
(Playwright) i adnotacje JSDoc. Odwracalność: dodanie Vite i TypeScriptu później nie
wymaga przepisania komponentów. Zmiany w SPEC: 5.1, 5.2, 14 (ryzyko „dwa ekosystemy”),
15 (P11).

---

## ADR-029: Rola zapisu do magazynu i udostępnianie projektów

**Data:** 2026-10-18
**Status:** Przyjęta (decyzja użytkownika 2026-10-18); uzupełnia ADR-013; errata 1: folder danych własnych ustawia administrator do v0.4

**Kontekst:** Firma wdraża Archiwistę z jednym centralnym magazynem Kartografa.
Użytkownicy mają też własne projekty z wersjonowanymi danymi własnymi (ADR-027) i chcą
decydować, kto je widzi: projekt publiczny (cała firma), wybrane osoby, wybrana grupa
(np. dział) albo prywatny (tylko właściciel). Tryb zespołu (ADR-013, v0.4) przewidywał
logowanie i role „czytelnik”, „operator”, „administrator” (SPEC 10.2), ale nie mówił,
kto może zapisywać w magazynie centralnym ani jak dzielić projekty. Trzeba też ustalić,
gdzie kończy się odpowiedzialność Archiwisty za bezpieczeństwo. Użytkownik chce tych
wymagań wcześnie, a nie jako dodatku po MVP.

**Opcje:**
- Granica uprawnień: A) Archiwista egzekwuje uprawnienia tylko we własnej powierzchni;
  B) Archiwista zarządza też prawami do plików na serwerze i udziale.
- Zapis do magazynu: A) każdy „operator”; B) osobne uprawnienie dla administratora
  Archiwisty i wybranych osób, z ustawieniem „wszyscy”.
- Kiedy model uprawnień: A) razem z logowaniem w v0.4; B) model i egzekwowanie od v0.1
  (jeden lokalny właściciel), logowanie i ekrany w v0.4; C) po MVP.

**Decyzja:** granica A, zapis B, model B:
1. **Granica odpowiedzialności.** Archiwista egzekwuje uprawnienia wyłącznie we własnej
   powierzchni: interfejs, API HTTP, CLI, tokeny agentów i pamięć podglądów.
   Bezpieczeństwo serwera i udziału oraz to, kto ma dostęp do systemu plików, należą do
   administratora serwera, nie do Archiwisty. Osoba z dostępem do udziału widzi pliki
   niezależnie od ustawień projektu w Archiwiście — dokumentacja wdrożenia mówi to
   wprost.
2. **Role:** „administrator” (`admin`; administrator systemu Archiwista, nie serwera:
   ustawienia, magazyny, konta, grupy, uprawnienia), „zapis do magazynu”
   (`store_writer`) i zwykły „użytkownik” (bez ról). Zastępują role „czytelnik”,
   „operator”, „administrator” z SPEC 10.2. Zapis do magazynu centralnego wyłącznie
   przez API Kartografa (i IMGWTools) i tylko z `store_writer`; ustawienie
   `store_write_for_all` nadaje je wszystkim. Zmiany projektu (manifest, migawki,
   udostępnianie) — właściciel i administrator; pobranie do magazynu wymaga dodatkowo
   `store_writer`.
3. **Widoczność projektu:** `public` (wszyscy), `users` (wybrane osoby), `group`
   (wybrana grupa, np. dział), `private` (tylko właściciel); administrator widzi
   wszystkie projekty (zarządzanie, przekazanie własności). Projekt bez wpisu (znaleziony
   skanem) ma widoczność z ustawienia `default_project_visibility` (domyślnie `public`).
   Magazyn centralny widzą wszyscy; widoczność dotyczy projektów, ich danych własnych,
   migawek i przypięć. Zapytania indeksu (lista projektów, „Przypięta w:”, wyszukiwanie)
   i pamięć podglądów danych własnych filtrują według widoczności; projekt niewidoczny
   = `404`, brak uprawnienia do działania = `403`.
4. **Kolejność:** v0.1 — model, egzekwowanie w API, CLI i zapytaniach dla jednego
   lokalnego właściciela, sprawdzone testami z wieloma tożsamościami na poziomie usług
   i API; administracyjne API i CLI kont, grup i udostępniania; dziennik zmian
   uprawnień. v0.3 — `store_writer` sprawdzane przy działaniach (pobieranie przez
   Kartografa). v0.4 — logowanie, zarządzanie kontami w interfejsie, ekran
   udostępniania, opcjonalnie grupy z LDAP/AD.
5. **`Principal`** (`id`, `kind`, `roles`, `groups`) przyjmuje każda usługa i każde zapytanie.
   W trybie lokalnym to właściciel z rolami `admin` i `store_writer` (zależność
   `current_principal`, krok 8 planu v0.1); autoryzacja: `can(principal, action,
   resource)` i filtr `visible_projects(principal)`.
6. **Stan nieodtwarzalny osobno od indeksu.** Konta, grupy, członkostwa, role, wpisy
   widoczności projektów i dziennik zmian uprawnień nie wynikają z plików na dysku,
   więc leżą w osobnej lokalnej bazie stanu (`<user_data_dir>/state.sqlite`), nigdy na
   udziale ani w magazynie. Przebudowa indeksu jej nie dotyka; kopia zapasowa przez
   `archiwista state export`, odtworzenie przez `archiwista state import` do pustej
   bazy. Klucz projektu w bazie stanu nie zależy od indeksu
   (katalog projektu po `realpath`).

Odrzucone: zarządzanie prawami plików na serwerze — wymaga uprawnień systemowych, dubluje
administrację serwera i daje fałszywe poczucie ochrony; zapis dla każdego „operatora” —
w firmie magazyn centralny jest wspólny i jego rozrost ma kontrolować wskazana osoba;
model razem z logowaniem albo po MVP — filtry dopisywane do gotowych warstw łatwo
pominąć (wyciek przez wyszukiwanie, „Przypięta w:”, podglądy), a model od v0.1 jest
tani, gdy usługi od początku przyjmują `Principal`.

**Konsekwencje:** Archiwista ma od v0.1 drugą lokalną bazę: indeks (odtwarzalny)
i stan (nieodtwarzalny: migracje schematu zamiast przebudowy, eksport). Zasada „stan
Archiwisty można odbudować” dotyczy indeksu, podglądów i historii zadań, nie bazy stanu.
Tryb lokalny działa jak dotąd (jeden właściciel ze wszystkimi uprawnieniami); konta
tworzone w v0.1 nie mogą się logować przed v0.4. Raporty zbiorcze (np. „nieużywane przez
żaden projekt”) liczą wszystkie projekty, ale nazwy podają tylko widocznych. Zmiany:
SPEC 1.3, 1.4, 3 (UC-14), 4.3, 4.7.1, 5.3, 9.1, 9.2, 10.2, 11, 13 (v0.1, v0.3, v0.4,
v0.5), 14; PRD F10, F16, N2.3, N5.2; SCOPE; plan v0.1 (krok 8b, kroki 9a, 11, 12,
bramka).

**Errata 1 (2026-10-19, plan v0.2 po przeglądzie — SPEC 4.7.1):** pkt 2 („zmiany
projektu — właściciel i administrator”) w v0.2 i v0.3 nie obejmuje folderu danych
własnych: folder inny niż domyślny (`<katalog projektu>/dane/`) ustawia tylko
administrator (`settings.write`, `PUT /projects/{project}/data-dir`), bo folder jest
miejscem zapisu migawek i musi leżeć poza magazynami, katalogami Archiwisty i folderami
innych projektów; ustawianie przez właściciela projektu — decyzja w v0.4 razem z ekranem
udostępniania. Migawki (`project.write`: właściciel albo administrator) — zgodnie
z pkt 2. Skan folderu danych to odczyt, nie zmiana projektu: zleca go każdy, kto widzi
projekt (tylko folder tego projektu), a przebieg przez foldery wszystkich projektów —
wyłącznie harmonogram; wyniki filtruje widoczność (pkt 3).

---

## Szablon nowego ADR

Kopiuj poniższy blok przy dodawaniu decyzji: kolejny numer, status ze
słownika na początku pliku, nowy wiersz w indeksie i odsyłacze po obu
stronach relacji. Erraty dopisuj na końcu wpisu.

```markdown
## ADR-XXX: Tytuł

**Data:** RRRR-MM-DD
**Status:** Przyjęta | Proponowana | Przyjęta — częściowo zastąpiona przez ADR-YYY (zakres) | Przyjęta — uzupełniona przez ADR-YYY (zakres) | Zastąpiona przez ADR-YYY | Odrzucona

**Kontekst:** Dlaczego temat powstał.

**Opcje:**
- A) ...
- B) ...

**Decyzja:** Która opcja i dlaczego.

**Konsekwencje:** Co z tego wynika.

**Errata 1 (RRRR-MM-DD, źródło/powód):** Dopisywane później.
```
