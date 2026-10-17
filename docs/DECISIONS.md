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
| [ADR-001](#adr-001-osobny-projekt-kartograf-jako-zależność) | Osobny projekt, Kartograf jako zależność | 2026-10-17 | Przyjęta |
| [ADR-002](#adr-002-źródło-prawdy-na-dysku-lokalny-indeks-jako-pamięć-podręczna) | Źródło prawdy na dysku, lokalny indeks jako pamięć podręczna | 2026-10-17 | Przyjęta |
| [ADR-003](#adr-003-magazyn-tylko-do-odczytu-zapisy-wyłącznie-przez-kartografa) | Magazyn tylko do odczytu, zapisy wyłącznie przez Kartografa | 2026-10-17 | Przyjęta — częściowo zastąpiona przez ADR-019 |
| [ADR-004](#adr-004-serwer-w-pythonie-z-fastapi) | Serwer w Pythonie z FastAPI | 2026-10-17 | Przyjęta |
| [ADR-005](#adr-005-interfejs-jako-spa-w-svelte-api-najpierw) | Interfejs jako SPA w Svelte, API najpierw | 2026-10-17 | Przyjęta (odwracalna do v0.1) |
| [ADR-006](#adr-006-mapa-w-maplibre-gl-js) | Mapa w MapLibre GL JS | 2026-10-17 | Przyjęta |
| [ADR-007](#adr-007-zadania-w-tle-w-osobnych-procesach) | Zadania w tle w osobnych procesach | 2026-10-17 | Przyjęta |
| [ADR-008](#adr-008-podglądy-przez-rio-tiler-z-pamięcią-po-sumie-wersji) | Podglądy przez rio-tiler z pamięcią po sumie wersji | 2026-10-17 | Przyjęta |
| [ADR-009](#adr-009-łączenie-danych-obróbka-w-kartografie-opakowanie-w-archiwiście) | Łączenie danych: obróbka w Kartografie, opakowanie w Archiwiście | 2026-10-17 | Proponowana (SPEC 15: P2, P3) |
| [ADR-010](#adr-010-etykiety-pokrycia-roku-i-plakietka-magazynu) | Etykiety pokrycia roku i plakietka magazynu | 2026-10-17 | Proponowana (mockup: M2) |
| [ADR-011](#adr-011-asystent-po-stronie-serwera-z-potwierdzeniem-człowieka) | Asystent po stronie serwera z potwierdzeniem człowieka | 2026-10-17 | Przyjęta |
| [ADR-012](#adr-012-ochrona-trybu-lokalnego) | Ochrona trybu lokalnego | 2026-10-17 | Przyjęta |
| [ADR-013](#adr-013-tryb-zespołu-jako-jeden-serwer-w-sieci-lokalnej) | Tryb zespołu jako jeden serwer w sieci lokalnej | 2026-10-17 | Proponowana (SPEC 15: P1) |
| [ADR-014](#adr-014-wiedza-o-formacie-magazynu-tylko-w-kartografie) | Wiedza o formacie magazynu tylko w Kartografie | 2026-10-17 | Przyjęta — uzupełniona przez ADR-019 |
| [ADR-015](#adr-015-pakowanie-i-uruchamianie) | Pakowanie i uruchamianie | 2026-10-17 | Przyjęta |
| [ADR-016](#adr-016-format-dat-w-interfejsie-i-podkład-mapy) | Format dat w interfejsie i podkład mapy | 2026-10-17 | Przyjęta (SPEC 15: P6; mockup: M9) |
| [ADR-017](#adr-017-warianty-grupowane-bez-formatu-plików) | Warianty grupowane bez formatu plików | 2026-10-17 | Przyjęta (uzupełnia ADR-010) |
| [ADR-018](#adr-018-wzorce-interfejsu-po-mockupie-czat-stos-podglądy) | Wzorce interfejsu po mockupie: czat, Stos, podglądy | 2026-10-17 | Przyjęta (czat, podglądy); Proponowana (wariant Stosu: mockup M4) |
| [ADR-019](#adr-019-dwóch-producentów-magazynu-kartograf-i-imgwtools) | Dwóch producentów magazynu: Kartograf i IMGWTools | 2026-10-17 | Przyjęta (zmienia ADR-003, uzupełnia ADR-014) |
| [ADR-020](#adr-020-format-danych-imgw-własny-sidecar-parquet-geojson) | Format danych IMGW: własny sidecar, Parquet, GeoJSON | 2026-10-17 | Proponowana (ADR IMGWTools; SPEC 12.8) |
| [ADR-021](#adr-021-etykiety-pokrycia-szeregów-imgw) | Etykiety pokrycia szeregów IMGW | 2026-10-17 | Proponowana (SPEC 15: P14–P16; mockup: M11) |

---

## ADR-001: Osobny projekt, Kartograf jako zależność

**Data:** 2026-10-17
**Status:** Przyjęta (decyzja użytkownika 2026-10-17)

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

---

## ADR-002: Źródło prawdy na dysku, lokalny indeks jako pamięć podręczna

**Data:** 2026-10-17
**Status:** Przyjęta (zasady SCOPE 3.3 Kartografa i decyzja użytkownika 2026-10-17)

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
**Status:** Przyjęta (wybór technologii pozostawiony autorowi specu, 2026-10-17)

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

---

## ADR-005: Interfejs jako SPA w Svelte, API najpierw

**Data:** 2026-10-17
**Status:** Przyjęta (odwracalna do startu v0.1; SPEC 15, P11)

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

---

## ADR-006: Mapa w MapLibre GL JS

**Data:** 2026-10-17
**Status:** Przyjęta

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

---

## ADR-007: Zadania w tle w osobnych procesach

**Data:** 2026-10-17
**Status:** Przyjęta

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

---

## ADR-008: Podglądy przez rio-tiler z pamięcią po sumie wersji

**Data:** 2026-10-17
**Status:** Przyjęta

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

---

## ADR-013: Tryb zespołu jako jeden serwer w sieci lokalnej

**Data:** 2026-10-17
**Status:** Proponowana — czeka na decyzję użytkownika (SPEC 15, P1)

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

---

## ADR-015: Pakowanie i uruchamianie

**Data:** 2026-10-17
**Status:** Przyjęta

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
**Status:** Przyjęta (czat, podglądy); Proponowana (wariant układu „Stosu”, mockup M4)

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

---

## ADR-019: Dwóch producentów magazynu: Kartograf i IMGWTools

**Data:** 2026-10-17
**Status:** Przyjęta (decyzja użytkownika 2026-10-17); częściowo zastępuje ADR-003, uzupełnia ADR-014

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

---

## ADR-021: Etykiety pokrycia szeregów IMGW

**Data:** 2026-10-17
**Status:** Proponowana — do potwierdzenia (SPEC 15: P14–P16; mockup: M11)

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
