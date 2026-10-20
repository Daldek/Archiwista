# API Archiwisty dla agentów i skryptów

Przewodnik dla agentów AI (np. Claude Code) i skryptów, które korzystają
z Archiwisty bez przeglądarki. Opisuje wydanie 0.2.0: odczyt katalogu,
podglądy, warstwy, porównanie, dane własne i migawki projektu, obszary
oraz zadania. Agent używa API HTTP `/api/v1` albo poleceń
`archiwista … --json` — bez narzędzi czatu ani MCP.

Do v1.0 API może się zmieniać. Pełny schemat z przykładami jest zawsze pod
`/api/v1/openapi.json` (wymaga sesji), a dokumentacja interaktywna pod
`/api/docs` (korzysta z sesji otwartej karty Archiwisty). Nazwy pól, parametrów i kodów są po angielsku, teksty dla
ludzi (`detail`, `title`, `message`) — po polsku.

## 1. Dwie drogi: CLI albo HTTP

| Potrzeba | CLI (`--json`) | HTTP (`/api/v1`) |
|---|---|---|
| stan serwera, źródeł, indeksu i magazynów | `archiwista status` | `GET /health` |
| wtyczki producentów | `archiwista sources` | `GET /sources` |
| wyszukiwanie i filtry katalogu | `archiwista search [ZAPYTANIE] [opcje]` | `GET /slots` |
| karta pliku (slotu) | `archiwista entry MAGAZYN SLOT` | `GET /stores/{store}/slots/{slot}` |
| karta jednej wersji | `archiwista version MAGAZYN WERSJA` | `GET /stores/{store}/versions/{version}` |
| projekty | `archiwista projects [--store MAGAZYN]` | `GET /projects` |
| karta projektu | `archiwista project PROJEKT` | `GET /projects/{project}` |
| token sesji dla agenta | `archiwista token --json` | `POST /session/tokens` |
| obszar i stan lokalny produktu | — (obszar zakłada HTTP; jego wiersze: `search --area-id`) | `POST /areas`, `GET /local-coverage` |
| skan magazynu, zadania, SSE | — (tylko HTTP) | `POST /stores/{store}/scan`, `/jobs` |
| podgląd i budowa, opcjonalny obraz PNG | `archiwista preview REF [--build] [--output PLIK.png]` | `GET`/`POST /stores/{store}/versions/{version}/preview`, `GET …/preview.png` |
| porównanie metadanych dwóch obiektów | `archiwista compare REF REF` | `GET /compare?a=REF&b=REF` |
| lata/kampanie i miniatura warstwy | `archiwista layers --store ID --product PRODUKT --area-id ID [--thumbnail KLUCZ --output PLIK.png]` | `GET /local-layers`, `GET /local-layers/thumbnail.png` |
| pliki projektu i karta pliku | `archiwista files PROJEKT`, `archiwista file PROJEKT PLIK` | `GET /projects/{project}/files`, `GET …/files/{file_id}` |
| plan i wykonanie migawki | `archiwista snapshot PROJEKT PLIK --plan`, `archiwista snapshot PROJEKT PLIK [--note TEKST]` | `GET …/files/{file_id}/snapshot-plan`, `POST …/files/{file_id}/snapshots` |
| skan folderu danych własnych | `archiwista own-scan [--project PROJEKT]` | `POST /projects/{project}/scan` |

CLI czyta lokalny indeks bez działającego serwera i wywołuje te same usługi
co trasy HTTP, jako właściciel lokalnej instalacji (`LOCAL_OWNER`, role
`admin` i `store_writer`). Z `--json`:

- na stdout trafia wyłącznie JSON o schemacie odpowiedzi trasy — ten sam,
  co z HTTP, łącznie z polami `stale` i `stale_stores`;
- przy błędzie na stdout trafia problem RFC 9457 trasy (sekcja 6), a kod
  wyjścia to `1`;
- tekst po polsku (diagnostyka, opis błędu) trafia zawsze na stderr;
- kod `2` oznacza niepoprawne użycie polecenia (np. brak argumentu).

Bez `--json` polecenia wypisują krótki tekst po polsku dla ludzi; agent
powinien zawsze podawać `--json`.

CLI nie pobiera danych i nie zmienia magazynu. Polecenia `users`,
`groups`, `share` i `state` (administracja uprawnieniami) opisuje
`archiwista --help`.

## 2. Sesja HTTP agenta

Serwer słucha tylko na `127.0.0.1` (domyślnie port `8090`, ustawienie
`port`). Każde żądanie `/api/*` poza wymianą tokenu wymaga sesji.

1. Właściciel uruchamia serwer: `archiwista serve --no-browser`.
2. Agent bierze jednorazowy token: `archiwista token --json` →
   `{"token": "…", "url": "http://127.0.0.1:8090/#token=…", "label": "…", "expires_at": "…"}`.
   Token jest ważny 5 minut i tylko raz; indeks przechowuje wyłącznie jego
   skrót. Port w `url` pochodzi z ustawień (`--port N` go zmienia), a `label`
   to etykieta sesji, którą token otworzy.
3. Agent wymienia token na sesję: `POST /api/v1/session` z treścią
   `{"token": "…"}`. Odpowiedź `200` ustawia ciasteczko `archiwista_session`
   (`HttpOnly`) i zwraca `{"actor": "local", "kind": "agent", "roles":
   ["admin", "store_writer"], "label": "…", "csrf_token": "…", "expires_at":
   "…"}` — `csrf_token` tylko tutaj, `roles` to role wykonawcy (agent ma role
   tego, kto wystawił token).
4. **Każde** żądanie `/api` — także `GET` — niesie ciasteczko sesji
   i nagłówek `X-Archiwista-CSRF` równy `csrf_token`; bez nagłówka albo
   z innym tokenem odpowiedź to `403 csrf_rejected`.

Przykład z `curl` i cookie-jar (`jq` albo inny parser JSON):

```sh
BASE=http://127.0.0.1:8090/api/v1
JAR="$(mktemp)"            # plik tylko dla bieżącego użytkownika
TOKEN="$(archiwista token --json | jq -r .token)"
CSRF="$(curl -sf -c "$JAR" -b "$JAR" -H 'Content-Type: application/json' \
  -d "{\"token\": \"$TOKEN\"}" "$BASE/session" | jq -r .csrf_token)"
H="X-Archiwista-CSRF: $CSRF"

curl -sf -b "$JAR" -H "$H" "$BASE/health"
curl -sf -b "$JAR" -H "$H" -X POST "$BASE/stores/zespol/scan"
curl -sf -b "$JAR" -H "$H" -X DELETE "$BASE/session"   # koniec pracy
```

Zasady sesji:

- **Bez nagłówka `Origin`.** `curl`, `httpx` i `requests` go nie wysyłają;
  obcy `Origin` albo `Sec-Fetch-Site: cross-site`/`same-site` dostaje
  `403 csrf_rejected`. Nagłówek `Host` musi być `127.0.0.1:<port>` albo
  `localhost:<port>` (inaczej `400 invalid_host`).
- Token podaje się wyłącznie w treści `POST /session` — nigdy w adresie
  (`?token=` jest odrzucany).
- Sesja agenta działa w imieniu osoby, która wydała token (`actor` w
  zadaniach to jej identyfikator, `actor_kind` = `agent`, `session` =
  etykieta sesji), z jej **bieżącymi** rolami i widocznością projektów
  (czytanymi przy każdym żądaniu).
- Sesje żyją w pamięci serwera: wygasają po 24 h bezczynności, sesja agenta
  najpóźniej 12 h po starcie, a restart serwera kończy wszystkie
  (`401 session_required` → nowy token). Właściciel kończy wszystkie sesje
  agentów poleceniem `archiwista token --revoke-all` — od razu, także na
  działającym serwerze — i unieważnia tym niewykorzystane tokeny agentów.
  Wyłączenie albo usunięcie konta kończy jego sesje, a odebrana rola
  przestaje działać przy następnym żądaniu.
- `GET /session` zwraca stan sesji (bez `csrf_token`) z rolami czytanymi
  przy tym żądaniu; `DELETE /session` kończy sesję. Agent nie wystawia
  tokenów kolejnych sesji (`POST /session/tokens` → `403 permission_denied`)
  — nowy token daje właściciel (`archiwista token`).
- Treść żądania: najwyżej 1 MiB (wymiana tokenu: 4 KiB; pliki obszarów:
  50 MB), inaczej `413 request_too_large`.

**Sekrety.** Tokenu, ciasteczek, `csrf_token` ani pliku cookie-jar nie
zapisuj w promptach, notatkach, dziennikach, historii powłoki ani
w repozytorium. Trzymaj je w zmiennych środowiska procesu albo w pliku
tymczasowym z prawami tylko dla siebie i usuń po pracy. W dziennikach
serwera token z adresu jest maskowany (`token=***`).

## 3. Wyszukiwanie i filtry (`GET /slots`, `archiwista search`)

Każdy parametr `/slots` ma w `archiwista search` opcję o tej samej nazwie
(podkreślenie → myślnik); `q` jest argumentem pozycyjnym `ZAPYTANIE`.
Wartości sprawdza ten sam model co trasa, więc błędy są identyczne.

| Parametr | Opcja CLI | Znaczenie |
|---|---|---|
| `q` | `ZAPYTANIE` | tekst; pasować musi każde słowo: godło, TERYT, KU, nazwa pliku, segment i produkt, etykieta wersji, numer zgłoszenia pracy, kampania, edycja (prefiks słowa, bez polskich znaków); słowo z 8–64 cyfr szesnastkowych pasuje też do początku SHA-256 |
| `store` | `--store` | identyfikator magazynu (`/stores`); nieznany → `422` |
| `product` | `--product` | produkt (`/products`), np. `nmt` |
| `country` | `--country` | kod kraju, np. `PL` |
| `years` | `--years` | rok danych (nie rok pobrania): `2023`, `2020-2023`, `2020-`, `-2023` |
| `unit` | `--unit` | dokładny kod jednostki: godło, TERYT, KU |
| `location` | `--location` | `any` (domyślnie), `with` (obrys albo cały kraj), `none` (bez położenia) |
| `versions` | `--versions` | `current` (domyślnie), `all`, `full_sheet`, `pinned`, `noncurrent_unpinned` |
| `status` | `--status` | `ok`, `missing`, `no_sidecar`, `unreadable`, `unrecognized` |
| `area_id` | `--area-id` | obszar zapisany przez `POST /areas` (nie razem z `bbox`) |
| `bbox` | `--bbox` | prostokąt `min_x,min_y,max_x,max_y` w układzie `bbox_crs` |
| `bbox_crs` | `--bbox-crs` | układ `bbox`, domyślnie `EPSG:4326`; inny przelicza przypięta operacja producenta |
| `limit` | `--limit` | wierszy na stronie: 1–200, domyślnie 50 |
| `project` | `--project` | wersje przypięte w widocznym projekcie; niewidoczny projekt → `404` |
| `cursor` | `--cursor` | `next_cursor` poprzedniej strony tego samego zapytania |

Wartości zaczynające się od minusa podawaj z `=`:
`archiwista search --bbox=-10,40,0,45 --json`.

```sh
archiwista search N-34-130-D-d-2-4 --json
archiwista search --product=nmt --years=2020-2023 --versions=all --limit=200 --json
curl -sf -b "$JAR" -H "$H" "$BASE/slots?product=nmt&years=2020-2023&versions=all&limit=200"
curl -sf -b "$JAR" -H "$H" "$BASE/slots?bbox=19.9,50.0,20.0,50.05&location=with"
```

Odpowiedź (`CatalogPage`, skrót):

```json
{
  "items": [
    {
      "store": "zespol",
      "slot": "nmt/pl_1992_1m_evrf2007/N-34/130/D/d/2/4/N-34-130-D-d-2-4.asc",
      "name": "N-34-130-D-d-2-4.asc",
      "unit": "N-34-130-D-d-2-4",
      "product": "nmt",
      "country": "PL",
      "status": "ok",
      "location": {"kind": "footprint", "reason": null, "source": "sheet"},
      "version": {"path": "nmt/pl_1992_1m_evrf2007/versions/…/N-34-130-D-d-2-4.asc",
                  "label": "2025-04-26_82710", "data_year": 2025,
                  "is_current": true, "is_full_sheet": true, "…": "…"},
      "versions_count": 1
    }
  ],
  "next_cursor": null,
  "groups": {"footprint": 1, "country": 0, "none": 0},
  "stale": false,
  "stale_stores": []
}
```

`groups` liczy grupy położenia w **całym** wyniku (wszystkie strony),
niezależnie od wybranego `location`. Wiersze bez położenia nie mają obrysu
i nie trafiają na mapę (`GET /map/footprints`), ale są w katalogu.

## 4. Stronicowanie

Kursor jest nieprzezroczysty i związany z zapytaniem: kolejne strony pobiera
się z **tymi samymi** filtrami i `cursor=<next_cursor>`, aż `next_cursor`
będzie `null`. Kursor innego zapytania, `limit` spoza 1–200 albo nieznany
parametr dają `422 validation_error`. Strony dowolnej wielkości zawierają
łącznie te same wiersze w tym samym porządku (nazwa pliku, slot, magazyn).

```sh
cursor=""
while :; do
  page="$(archiwista search --versions=all --limit=200 ${cursor:+--cursor="$cursor"} --json)"
  printf '%s\n' "$page" | jq -c '.items[] | {store, slot, version: .version.path}'
  cursor="$(printf '%s' "$page" | jq -r '.next_cursor // empty')"
  [ -n "$cursor" ] || break
done
```

To samo przez HTTP: `"$BASE/slots?versions=all&limit=200&cursor=$cursor"`
(kursor jest bezpieczny w adresie URL).

## 5. Karty, stan i świeżość

- `archiwista entry MAGAZYN SLOT` / `GET /stores/{store}/slots/{slot}` —
  karta pliku (`SlotCard`): wszystkie wersje, `current` i `full_sheet`,
  przypięcia widocznych projektów (`pinned_by`), problemy z instrukcją
  naprawy i `paths` (`local` — ścieżka na tym komputerze, `aliases` —
  ta sama ścieżka pod innymi literami dysków).
- `archiwista version MAGAZYN WERSJA` /
  `GET /stores/{store}/versions/{version}` — wszystkie wartości wersji
  z indeksu, obrys w WGS84 i surowy sidecar; sam sidecar:
  `GET …/versions/{version}/sidecar`.
- `GET /requests/{parent_request}` — pliki jednego zgłoszenia producenta
  (np. obie strony granicy PL/CZ).
- `archiwista projects` / `GET /projects` i `archiwista project PROJEKT` /
  `GET /projects/{project}` — projekty widoczne dla wykonawcy; ukryty
  projekt odpowiada jak nieistniejący (`404`). `GET
  /projects/{project}/status` pyta producenta o stan teraz (bez sieci).
- `archiwista status` / `GET /health` — wersje, źródła, indeks i każdy
  magazyn: `status` (`unknown` — jeszcze nie skanowany, `available`,
  `unavailable`), liczniki, `last_scan` z wykonawcą, `running_job`
  z postępem, `stale`.

Slot i wersję adresuje się ścieżką względną z wyników (`slot`,
`version.path`, `current`), nigdy ścieżką systemu plików. Odczytu z dysku
i parsowania sidecarów nie trzeba: API zwraca wszystko z indeksu.

**Świeżość.** Każda odpowiedź z indeksu ma `stale` i `stale_stores`. Gdy
magazyn jest niedostępny (np. odłączony udział SMB), listy i karty dalej
odpowiadają `200` według indeksu z chwili `indexed_at`, a `stale` jest
`true` — agent powinien to zgłosić użytkownikowi, a nie traktować wyniku
jako aktualnego stanu dysku.

**Tryb offline.** Ustawienie `offline` (`GET /settings`) wyłącza wszystko,
co wymaga sieci; odczyt indeksu, karty i skany lokalne działają dalej,
a zadanie obrysów jednostek dostaje `409 offline_mode`.

**Obszar i stan lokalny.** `POST /areas` zapisuje obszar: GeoJSON
`Polygon` albo `MultiPolygon` w WGS84 jako `application/json`
(`{"geometry": {…}, "name": "…"}`) albo plik GeoJSON, GeoPackage lub ZIP
z jednym Shapefile jako surową treść (np. `Content-Type:
application/octet-stream`; `?name=` i — dla pliku z kilkoma warstwami —
`?layer=`). Odpowiedź `201` ma `id` (ta sama geometria zawsze dostaje to
samo), pole w km² (`area_km2`, `area_crs`) i kraje. `id` jest parametrem
`area_id` w `/slots` (`archiwista search --area-id`) i w
`GET /local-coverage?area_id=…&product=…&store=…` — ile obszaru pokrywają
bieżące wersje produktu w magazynie: `results` z krajem, `percent`
(zaokrąglony w dół) i `label` („lokalnie 83% obszaru”). Przed policzeniem
serwer czyta sloty obszaru z magazynu (najwyżej 500, do 10 s); w przeciwnym
razie odpowiada z indeksu i podaje powód w `stale_reason`.

```sh
AREA="$(curl -sf -b "$JAR" -H "$H" -H 'Content-Type: application/json' \
  -d '{"geometry": {"type": "Polygon", "coordinates": [[[19.9, 50.0],
       [20.0, 50.0], [20.0, 50.05], [19.9, 50.05], [19.9, 50.0]]]}}' \
  "$BASE/areas" | jq -r .id)"
curl -sf -b "$JAR" -H "$H" "$BASE/local-coverage?area_id=$AREA&product=nmt&store=zespol"
archiwista search --area-id="$AREA" --product=nmt --json
```

## 6. Podglądy, warstwy, porównanie i dane własne (v0.2)

`ref` bierz z odpowiedzi karty wersji, pliku własnego albo migawki:
`version:<store>:<ścieżka-wersji>`, `file:<project>:<ścieżka-pliku>`
lub `snapshot:<project>:<etykieta>:<ścieżka-pliku>`. Nie twórz
odwołań z bezwzględnych ścieżek systemu plików. Resolver przed dostępem
do pamięci podglądów sprawdza widoczność projektu. Projekt niewidoczny
daje `404`, brak prawa do migawki — `403`.

`GET /stores/{store}/versions/{version}/preview` zwraca `PreviewInfo`:
`state` (`ready`, `needs_build`, `building`, `unavailable`), `kind`,
`reason` (`code`, polskie `message`, `fix`), `styles`, `default_style`
oraz adresy `thumbnail_url`, `tiles_url`, `features_url`, `members_url`.
Przy `needs_build` wywołaj `POST …/preview`: `202` zwraca zadanie, `200`
oznacza gotowy podgląd. Obraz pobierz przez `GET …/preview.png?size=512`
(`--style` w CLI, parametr `style` w HTTP). Kafle `…/tiles/{z}/{x}/{y}.png`,
wektory `…/features?bbox=…&zoom=…` i spis ZIP `…/members` mają tę samą
ochronę sesji i nagłówka CSRF, **również dla obrazów**. Żądania odłączonego
magazynu mogą korzystać z pamięci, a przy jej braku podają powód.

```sh
archiwista search --project=projekt-01 --json
# REF pochodzi z pola ref karty wersji lub pliku zwróconej przez API.
archiwista preview "$REF" --build --json
archiwista preview "$REF" --output=<katalog-danych>/podglad.png
```

`GET /local-layers?store=demo&product=nmt&area_id=$AREA&group=year`
zwraca lata (albo `group=campaign`), ich klucze, pokrycie i adresy
miniatur/kafli. Bez `area_id` daje liczniki, nie obrazy. Użyj adresu
`thumbnail_url` z odpowiedzi, nie zgaduj klucza i wersji obrazu:

```sh
archiwista layers --store=demo --product=nmt --area-id="$AREA" --json
LAYER="$(archiwista layers --store=demo --product=nmt \
  --area-id="$AREA" --json | jq -r '.layers[0].key')"
archiwista layers --store=demo --product=nmt --area-id="$AREA" \
  --thumbnail="$LAYER" --output=<katalog-danych>/rok.png
curl -sf -b "$JAR" -H "$H" "$BASE/local-layers?store=demo&product=nmt&area_id=$AREA&group=year"
archiwista compare "$REF_A" "$REF_B" --json
curl -sf -b "$JAR" -H "$H" -G --data-urlencode "a=$REF_A" \
  --data-urlencode "b=$REF_B" "$BASE/compare"
```

Folder projektu (domyślnie `<katalog projektu>/dane/`, inny ustawia
administrator przez `PUT /projects/{project}/data-dir`) jest indeksowany
osobno od magazynu: `GET /projects/{project}/files?q=…&state=changed`
z `limit`/`cursor`, `GET …/files/{file_id}` i `GET …/files/{file_id}/layers`
(plik roboczy oraz migawki w Wachlarzu). Obrazy, kafle, obiekty i spis
archiwum mają odpowiedniki tras wersji pod `…/files/{file_id}/preview`,
`…/files/{file_id}/snapshots/{label}/preview` itd. Plik zmieniony od
ostatniego skanu trzeba przeskanować ponownie, zamiast używać starego
podglądu. Plan migawki sprawdza wykonalność i rozmiar bez jej tworzenia;
`POST …/snapshots` wymaga `project.write` (właściciel projektu lub admin),
zwraca zadanie `snapshot`; identyczna treść daje wynik `unchanged`.

```sh
archiwista files projekt-01 --state=changed --json
archiwista file projekt-01 kanalizacja.gpkg --json
archiwista own-scan --project=projekt-01 --json
archiwista snapshot projekt-01 kanalizacja.gpkg --plan --json
archiwista snapshot projekt-01 kanalizacja.gpkg --note="przed zmianą" --json
curl -sf -b "$JAR" -H "$H" "$BASE/projects/projekt-01/files"
curl -sf -b "$JAR" -H "$H" "$BASE/projects/projekt-01/files/$FILE_ID/snapshot-plan"
curl -sf -b "$JAR" -H "$H" -X POST -H 'Content-Type: application/json' \
  -d '{"note":"przed zmianą"}' "$BASE/projects/projekt-01/files/$FILE_ID/snapshots"
```

`GET /jobs?project=projekt-01` filtruje zadania projektu. Lista, szczegóły
`/jobs/{job}` i SSE `/jobs/{job}/events` nie ujawniają zadań z danymi
niewidocznego projektu (`404` przy bezpośrednim adresie); zwykły skan
magazynu jest wspólny. SSE wysyła `progress`, `notice` i `state`, a klient
wznawia po `Last-Event-ID`.

## 7. Błędy

Każdy błąd HTTP to `application/problem+json` (RFC 9457), np. dla
`GET /slots?limit=201`:

```json
{
  "type": "/api/v1/problems/validation-error",
  "title": "Niepoprawne dane żądania",
  "status": 422,
  "detail": "Niepoprawne dane żądania: query.limit.",
  "code": "validation_error",
  "errors": [{"field": "query.limit", "type": "less_than_equal",
              "message": "Input should be less than or equal to 200"}]
}
```

Decyzje opieraj na `status` i `code` — nigdy na tekście `detail`.

| Status | `code` | Kiedy i co zrobić |
|---|---|---|
| 400 | `invalid_host` | nagłówek `Host` inny niż `127.0.0.1:<port>`/`localhost:<port>` |
| 401 | `session_required` | brak, wygasła albo nieznana sesja; zły, użyty lub przeterminowany token → nowy token |
| 403 | `csrf_rejected` | brak/zły `X-Archiwista-CSRF` w dowolnym żądaniu `/api` albo obcy `Origin` |
| 403 | `permission_denied` | wykonawca nie ma uprawnienia (np. zmiana ustawień bez roli `admin`) |
| 403 | `path_outside_root` | ścieżka wychodzi poza magazyn |
| 404 | `not_found` | nieznany zasób albo projekt niewidoczny dla wykonawcy |
| 405 | `method_not_allowed` | inna metoda; dozwolone w nagłówku `Allow` |
| 409 | `conflict` | trwa już zadanie zapisujące indeks tego magazynu (pole `job`) — śledź je zamiast ponawiać |
| 409 | `offline_mode` | operacja wymaga sieci, a włączony jest tryb offline |
| 409 | `snapshot_blocked`, `own_file_changed` | plan blokuje migawkę albo plik zmienił się od skanu: odśwież folder i odczytaj plan |
| 413 | `request_too_large` | treść żądania ponad limit (4 KiB wymiana tokenu, 1 MiB pozostałe) |
| 413 | `area_too_large` | plik obszaru ponad 50 MB albo archiwum ponad 200 MB po rozpakowaniu |
| 422 | `validation_error` | niepoprawne parametry lub treść: `errors` (`field`, `type`, `message`) albo `problems` (ustawienia) |
| 422 | `area_unreadable`, `area_too_complex` | pliku obszaru nie da się odczytać (przy kilku warstwach pole `layers` — wybierz `?layer=`) albo obszar ma ponad 100 000 wierzchołków |
| 422 | `kartograf_error`, `imgwtools_error`, `producer_error` | producent odrzucił wywołanie; pole `kartograf`/`imgwtools` ma `exception` i niezmieniony `message` |
| 500 | `internal_error` | błąd Archiwisty — szczegóły w dzienniku serwera |
| 503 | `source_unavailable` | brak wtyczki producenta; pole `source` (`id`, `state`, `package_version`, `supported_versions`, `requirement`), naprawa na końcu `detail` |
| 503 | `source_incompatible` | wtyczka w niewspieranej wersji lub schemacie; jak wyżej |
| 503 | `store_unavailable` | magazynu nie da się odczytać, a indeks nie ma odpowiedzi |
| 503 | `preview_busy` | pula renderowania jest pełna; zaczekaj według `Retry-After` |

CLI z `--json` wypisuje dokładnie te same problemy (z tym samym `status`
w treści) i kończy się kodem `1`.

## 8. Zalecany przebieg pracy agenta

1. **Rozpoznanie:** `archiwista status --json` (albo `GET /health`) —
   czy są magazyny, czy są `available`, czy wtyczka producenta jest
   `available`, czy trwa skan (`running_job`).
2. **Szukanie:** `search` z możliwie wąskimi filtrami (`--product`,
   `--unit`, `--years`, `--bbox`), `--limit=200` i pętla po `next_cursor`;
   nie pobieraj całego katalogu, jeśli wystarczy filtr.
3. **Szczegóły:** karta pliku (`entry`) dla wybranych slotów; `version`
   tylko gdy potrzebne są wszystkie metadane albo sidecar.
4. **Ocena świeżości:** sprawdź `stale`; przy `true` podaj użytkownikowi
   `indexed_at` z `stale_stores` zamiast twierdzić, że plik jest na dysku.
5. **Odświeżenie (tylko na prośbę):** `POST /stores/{store}/scan` z CSRF
   → `202` z zadaniem; postęp przez SSE albo `GET /health`
   (`running_job`). Przy `409 conflict` poczekaj na trwające zadanie
   zamiast ponawiać.
6. **Błędy:** `503 source_unavailable`/`source_incompatible` przekaż
   użytkownikowi razem z naprawą z `detail` — nie ponawiaj w pętli;
   `401` → nowy token od użytkownika (`archiwista token`).
7. **Ścieżki:** do pracy z plikiem użyj `paths.local` z karty; nie składaj
   ścieżek samodzielnie.

## 9. Zadania w tle i SSE

Długie operacje zwracają `202 Accepted` z zadaniem (`JobDetail`) i nagłówkiem
`Location: /api/v1/jobs/{id}`. Wszystkie wymagają `X-Archiwista-CSRF`.

| Żądanie | Treść | Uwagi |
|---|---|---|
| `POST /stores/{store}/scan` | opcjonalnie `{"mode": "incremental"}` (domyślnie) albo `"full"`, opcjonalnie `"segment"` | skan magazynu do indeksu |
| `POST /stores/{store}/footprints` | brak | obrysy jednostek (TERYT, KU) z sieci; offline → `409 offline_mode` |
| `POST /stores/{store}/link-check` | `{"slot": "…"}` | potwierdzenie celu dowiązania slotu; nieznany slot → `404` |
| `POST /projects/{project}/scan` | brak | skan folderu projektu, możliwy dla widzących projekt |
| `POST /projects/{project}/files/{file_id}/snapshots` | `{"note":"…"}` albo brak | migawka, wymaga `project.write` |
| `POST …/preview` | brak | budowa podglądu pliku lub wersji (odpowiedź `200` albo zadanie `202`) |

Nieznany magazyn daje `404 not_found`, zła treść `422 validation_error`.
Gdy dla magazynu trwa już zadanie zapisujące indeks (skan albo obrysy),
odpowiedź to `409 conflict` z polem `job` (`id`, `kind`, `state`) —
śledź to zadanie zamiast zakładać nowe.

Zadanie (`GET /jobs/{id}`) ma pola `id`, `kind` (`scan`, `footprints`,
`link_check`, `preview`, `own_scan`, `snapshot`), `state` (`queued`,
`running`, `succeeded`, `failed`, `interrupted`, `cancelled`), `actor`,
`actor_kind`, `session`, `store`, `params`, `created_at`, `started_at`,
`finished_at`, `progress`, `result` i `error`. Lista:
`GET /jobs?kind=&store=&state=&project=` z `limit` (1–200) i `cursor`,
najnowsze najpierw. Zadania z danymi projektu mają kontrolę jego widoczności
także w pojedynczej karcie i w strumieniu SSE.

Zdarzenia płyną jako SSE z `GET /jobs/{id}/events` (`text/event-stream`).
Każda ramka ma `id: <numer kolejny>`, `event: progress|notice|state`
i `data: <JSON>`:

- `progress` — `current`, `total`; skan dodaje `segment` i `entries`,
  obrysy `written` i `failed`;
- `notice` — `level`, `code`, `message`;
- `state` — `state`; ostatnie niesie `result` (sukces) albo `error`.

Strumień kończy się po stanie końcowym; dla zakończonego zadania bez
nowych zdarzeń odpowiedź to `204`. Po 15 s ciszy serwer wysyła komentarz
`: keepalive`, a zadanie w kolejce może czekać dłużej, więc klient nie
powinien mieć limitu czasu odczytu (np. `httpx` z `timeout=None`). Po
zerwaniu połączenia wznów z nagłówkiem `Last-Event-ID` równym ostatniemu
odebranemu `id`.

Strumień, jak każde żądanie `/api`, wymaga nagłówka `X-Archiwista-CSRF`.
Przeglądarkowy `EventSource` nie wysyła własnych nagłówków, więc się tu nie
nadaje: strumień czyta się zwykłym klientem HTTP z odczytem treści na
bieżąco — `curl -N`, `httpx.stream(…)`, w przeglądarce `fetch`
i `response.body` (tak czyta go interfejs Archiwisty).

```sh
JOB="$(curl -sf -b "$JAR" -H "$H" -X POST \
  "$BASE/stores/zespol/scan" | jq -r .id)"
curl -sfN -b "$JAR" -H "$H" "$BASE/jobs/$JOB/events"
curl -sf -b "$JAR" -H "$H" "$BASE/jobs/$JOB" | jq '{state, error}'
```

Kody błędów zadania (`error.code`): `store_unavailable`,
`source_unavailable`, `source_incompatible`, `kartograf_error`,
`offline_mode`, `not_found`, `unsupported`, `internal_error`,
`worker_crashed`, `interrupted`, `cancelled`. CLI nie ma poleceń zadań:
`archiwista reindex [--store MAGAZYN]` wykonuje pełny skan na pierwszym
planie (dla właściciela przy terminalu, nie dla agenta przy działającym
serwerze — oba trafiają do tej samej kolejki i dostają `409` przy
konflikcie).

## 10. Ograniczenia v0.2

- Tylko tryb lokalny: jedna osoba na `127.0.0.1`, bez logowania; konta
  i grupy służą widoczności projektów (A-ADR-029).
- Bez pobierania danych, sprawdzania dostępności u źródła i działań
  producenta zmieniających manifest projektu (plan v0.3).
- Bez danych IMGW w Archiwiście, czatu i MCP; agent zewnętrzny używa API
  opisanego wyżej.
