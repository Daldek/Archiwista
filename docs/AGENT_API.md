# Archiwista API for agents and scripts

A guide for AI agents (for example Claude Code) and scripts that use Archiwista
without a browser. It describes release 0.2.0: reading the catalog, previews,
layers, comparison, own data and project snapshots, areas and jobs. An agent
uses the HTTP API `/api/v1` or the commands `archiwista … --json`; there is no
chat tool and no MCP server.

Until v1.0 the API may change. The full schema with examples is always at
`/api/v1/openapi.json` (it needs a session) and the interactive documentation
at `/api/docs` (it uses the session of an open Archiwista tab). Field names,
parameter names and codes are English; texts for people (`title`, `detail`,
`hint`, `message`) are English, and Polish for the request header
`Accept-Language: pl` (section 7), except the few that are stored in Polish.

## 1. Two ways: the CLI or HTTP

| Need | CLI (`--json`) | HTTP (`/api/v1`) |
|---|---|---|
| state of the server, sources, index and stores | `archiwista status` | `GET /health` |
| producer plugins | `archiwista sources` | `GET /sources` |
| catalog search and filters | `archiwista search [QUERY] [options]` | `GET /slots` |
| card of a file (slot) | `archiwista entry MAGAZYN SLOT` | `GET /stores/{store}/slots/{slot}` |
| card of one version | `archiwista version MAGAZYN WERSJA` | `GET /stores/{store}/versions/{version}` |
| projects | `archiwista projects [--store MAGAZYN]` | `GET /projects` |
| card of a project | `archiwista project PROJEKT` | `GET /projects/{project}` |
| a new project, a task added or removed, the producer's status of a project (v0.3) | `archiwista project-init PRODUCENT KATALOG --store MAGAZYN`, `project-add PROJEKT NAZWA POLECENIE [--options JSON] [--producer PRODUCENT]`, `project-remove PROJEKT NAZWA`, `project-status PROJEKT` | `POST /projects`, `POST /projects/{project}/tasks`, `DELETE /projects/{project}/tasks/{name}`, `GET /projects/{project}/status` |
| a job of a project's tasks: download and pin, repin one task, check against the source, verify in the store (v0.3) | `archiwista project-download PROJEKT [ZADANIE ...]`, `project-repin PROJEKT ZADANIE`, `project-check PROJEKT [ZADANIE ...]`, `project-verify PROJEKT [ZADANIE ...]` (the job in the foreground, printed as it ended) | `POST /projects/{project}/jobs` |
| session token for an agent | `archiwista token --json` | `POST /session/tokens` |
| area and local state of a product | — (HTTP creates an area; its rows: `search --area-id`) | `POST /areas`, `GET /local-coverage` |
| store scan, SSE | — (HTTP only) | `POST /stores/{store}/scan`, `GET /jobs/{job}/events` |
| background jobs: the list, one job, cancel, retry, the end of its log (v0.3) | `archiwista jobs list [--kind …] [--store …] [--state …] [--project …] [--limit N] [--cursor …]`, `jobs show ZADANIE`, `jobs cancel ZADANIE`, `jobs retry ZADANIE` (the new job in the foreground, printed as it ended), `jobs log ZADANIE` | `GET /jobs`, `GET /jobs/{job}`, `POST /jobs/{job}/cancel`, `POST /jobs/{job}/retry`, `GET /jobs/{job}/log` |
| preview and build, optional PNG | `archiwista preview REF [--build] [--output FILE.png]` | `GET`/`POST /stores/{store}/versions/{version}/preview`, `GET …/preview.png` |
| the first look at current versions prepared ahead in the preview cache (pane thumbnail, map tiles at the smallest zoom), optionally of a store, product, segment, project (with its own data) or area (v0.3) | `archiwista preview-warm [--store MAGAZYN] [--product PRODUKT] [--segment SEGMENT] [--project PROJEKT] [--area-id OBSZAR]` (the job in the foreground, printed as it ended) | `POST /previews/warm` |
| comparison of the metadata of two objects | `archiwista compare REF REF` | `GET /compare?a=REF&b=REF` |
| years/campaigns and thumbnail of a layer | `archiwista layers --store ID --product PRODUKT --area-id ID [--thumbnail KLUCZ --output FILE.png]` | `GET /local-layers`, `GET /local-layers/thumbnail.png` |
| files of a project and the card of a file | `archiwista files PROJEKT`, `archiwista file PROJEKT PLIK` | `GET /projects/{project}/files`, `GET …/files/{file_id}` |
| plan and making of a snapshot | `archiwista snapshot PROJEKT PLIK --plan`, `archiwista snapshot PROJEKT PLIK [--note TEKST]` | `GET …/files/{file_id}/snapshot-plan`, `POST …/files/{file_id}/snapshots` |
| scan of the own-data folder | `archiwista own-scan [--project PROJEKT]` | `POST /projects/{project}/scan` |
| producers' commands: the catalog, a pasted line read into a call, a call checked without the network, the line of a call (v0.3) | `archiwista commands list [--producer ID]`, `commands parse PRODUCENT LINIA`, `commands validate PRODUCENT POLECENIE --options JSON [--store MAGAZYN]`, `commands format PRODUCENT POLECENIE --options JSON [--run JSON]` | `GET /commands`, `POST /commands/parse`, `/commands/validate`, `/commands/format` |
| what the source has for an area and a product: the last report kept with its rows (labels, ranked variants, store badges), a check at the source (v0.3) | `archiwista availability show OBSZAR --product PRODUKT [--producer ID] [--store ID] [--horizontal …] [--resolution …] [--vertical-crs …]`, `availability check OBSZAR --product PRODUKT [--producer ID] [--force]` and the same options | `GET /availability`, `POST /availability` |
| a job of a producer's command on a configured store, kind `check` (the plan of a run without its effects) or `download` (the run, with the plan of a `check` job if named; it writes the store), and the plan a `check` job kept (v0.3) | `archiwista jobs start check PRODUCENT POLECENIE --store MAGAZYN [--options JSON]`, `jobs start download PRODUCENT POLECENIE --store MAGAZYN [--options JSON] [--plan ZADANIE]` (the job in the foreground, printed as it ended), `jobs plan ZADANIE` | `POST /jobs`, `GET /jobs/{job}/plan` |

The CLI reads the local index without a running server and calls the same
services as the HTTP routes, as the owner of the local installation
(`LOCAL_OWNER`, roles `admin` and `store_writer`). With `--json`:

- standard output carries nothing but JSON of the route's response schema, the
  same as over HTTP, including the fields `stale` and `stale_stores`; its texts
  are English, as over HTTP without `Accept-Language`;
- an error prints nothing on standard output. The last line of standard error
  is the error document `archiwista-error/1` as compact JSON (section 7), and
  the exit status is the registry's exit code of its `code`: `2` invalid input
  (also a wrong use of the command line, for example a missing argument), `3`
  not found, `4` conflict, `6` missing dependency, `8` store unavailable, `9`
  file system error, `12` forbidden, `13` calculation error, `14` no data, `15`
  not supported; `1` is a defect of Archiwista;
- a job that does not succeed prints its `JobDetail` on standard output and
  exits `11` (it failed) or `130` (it was cancelled or interrupted, also by
  Ctrl+C); `archiwista reindex` of several stores exits `10` when only some
  were scanned; `archiwista doctor` exits `10` or `11` when checks fail. These
  are outcomes, not errors: no error document follows them;
- text for people (diagnostics, the description of an error) always goes to
  standard error, in Polish, and the log, in English, goes there too; none of it
  goes to standard output. Every command takes `--verbose` (debug) or `--quiet`
  (errors only),
  before or after its name, and without them the variable `ARCHIWISTA_LOG_LEVEL`
  (`debug`, `info`, `warning`, `error`) sets the level; the default is `warning`.

Without `--json` the commands print a short Polish text for people; an agent
should always pass `--json`.

The CLI downloads data and writes a store only through a job: a `download` (`jobs
start download`), a project's download or repin (`project-download`,
`project-repin`), or `jobs retry` of one of them. The commands `users`,
`groups`, `share` and `state` (permission administration) are described by
`archiwista --help`.

## 2. The HTTP session of an agent

The server listens on `127.0.0.1` only (port `8090` by default, the setting
`port`). Every request `/api/*` except the token exchange needs a session.

1. The owner starts the server: `archiwista serve --no-browser`.
2. The agent takes a one-time token: `archiwista token --json` →
   `{"token": "…", "url": "http://127.0.0.1:8090/#token=…", "label": "…", "expires_at": "…"}`.
   The token is valid for 5 minutes and once; the index keeps only its hash.
   The port in `url` comes from the settings (`--port N` changes it), and
   `label` is the label of the session the token opens.
3. The agent exchanges the token for a session: `POST /api/v1/session` with the
   body `{"token": "…"}`. The answer `200` sets the cookie `archiwista_session`
   (`HttpOnly`) and returns `{"actor": "local", "kind": "agent", "roles":
   ["admin", "store_writer"], "store_write": true, "label": "…", "csrf_token":
   "…", "expires_at": "…"}`: `csrf_token` appears only here, `roles` are the
   roles of the actor (an agent has the roles of the person who issued the
   token), and `store_write` says whether the session may write the stores (a
   `download`: the role `store_writer` or the setting `store_write_for_all`).
4. **Every** request to `/api`, `GET` too, carries the session cookie and the
   header `X-Archiwista-CSRF` equal to `csrf_token`; without the header or with
   another token the answer is `403 forbidden` (`details.reason`
   `csrf_rejected`).

An example with `curl` and a cookie jar (`jq` or another JSON parser):

```sh
BASE=http://127.0.0.1:8090/api/v1
JAR="$(mktemp)"            # a file for the current user only
TOKEN="$(archiwista token --json | jq -r .token)"
CSRF="$(curl -sf -c "$JAR" -b "$JAR" -H 'Content-Type: application/json' \
  -d "{\"token\": \"$TOKEN\"}" "$BASE/session" | jq -r .csrf_token)"
H="X-Archiwista-CSRF: $CSRF"

curl -sf -b "$JAR" -H "$H" "$BASE/health"
curl -sf -b "$JAR" -H "$H" -X POST "$BASE/stores/zespol/scan"
curl -sf -b "$JAR" -H "$H" -X DELETE "$BASE/session"   # end of work
```

Rules of the session:

- **No `Origin` header.** `curl`, `httpx` and `requests` do not send it; a
  foreign `Origin` or `Sec-Fetch-Site: cross-site`/`same-site` gets `403
  forbidden` (`csrf_rejected`). The header `Host` must be `127.0.0.1:<port>` or
  `localhost:<port>`, otherwise `403 forbidden` (`invalid_host`).
- The token goes only in the body of `POST /session`, never in the address
  (`?token=` is rejected).
- The session of an agent acts for the person who issued the token (`actor` in
  jobs is that person's id, `actor_kind` is `agent`, `session` is the label of
  the session), with their **current** roles and project visibility (read at
  every request).
- Sessions live in the memory of the server: they expire after 24 h of
  inactivity, an agent session 12 h after its start at the latest, and a
  restart of the server ends all of them (`401 unauthorized`, `session_required`
  → a new token). The owner ends all agent sessions with `archiwista token
  --revoke-all`, at once, also on a running server, which also revokes unused
  agent tokens. Disabling or deleting an account ends its sessions, and a
  revoked role stops working at the next request.
- `GET /session` returns the state of the session (without `csrf_token`) with
  the roles and `store_write` read at this request; `DELETE /session` ends it.
  An agent does not issue tokens for further sessions (`POST /session/tokens`
  → `403 forbidden`, `permission_denied`): the owner gives a new token
  (`archiwista token`).
- The body of a request is at most 1 MiB (token exchange: 4 KiB; area files:
  50 MB), otherwise `400 validation_error` (`request_too_large`).

**Secrets.** Do not write the token, the cookies, `csrf_token` or the cookie
jar file into prompts, notes, logs, shell history or the repository. Keep them
in process environment variables or in a temporary file readable by you only,
and delete it after the work. The server's logs mask the token of an address
(`token=***`).

## 3. Search and filters (`GET /slots`, `archiwista search`)

Every parameter of `/slots` has an option of the same name in `archiwista
search` (underscore → hyphen); `q` is the positional argument `QUERY`. The
same model checks the values, so the errors are identical.

| Parameter | CLI option | Meaning |
|---|---|---|
| `q` | `QUERY` | text; every word must match: sheet code, TERYT, KU, file name, segment and product, version label, job request number, campaign, edition (word prefix, no Polish diacritics); a word of 8–64 hexadecimal digits also matches the start of a SHA-256 |
| `store` | `--store` | store id (`/stores`); an unknown one → `400` |
| `product` | `--product` | product (`/products`), for example `nmt` |
| `country` | `--country` | country code, for example `PL` |
| `years` | `--years` | year of the data (not of the download): `2023`, `2020-2023`, `2020-`, `-2023` |
| `unit` | `--unit` | exact unit code: sheet code, TERYT, KU |
| `location` | `--location` | `any` (default), `with` (outline or the whole country), `none` (no location) |
| `versions` | `--versions` | `current` (default), `all`, `full_sheet`, `pinned`, `noncurrent_unpinned` |
| `status` | `--status` | `ok`, `missing`, `no_sidecar`, `unreadable`, `unrecognized` |
| `area_id` | `--area-id` | an area kept by `POST /areas` (not together with `bbox`) |
| `bbox` | `--bbox` | rectangle `min_x,min_y,max_x,max_y` in the CRS `bbox_crs` |
| `bbox_crs` | `--bbox-crs` | CRS of `bbox`, `EPSG:4326` by default; another one is converted by the producer's pinned operation |
| `limit` | `--limit` | rows per page: 1–200, 50 by default |
| `project` | `--project` | versions pinned in a visible project; an invisible project → `404` |
| `cursor` | `--cursor` | `next_cursor` of the previous page of the same query |

Give values that start with a minus with `=`:
`archiwista search --bbox=-10,40,0,45 --json`.

```sh
archiwista search N-34-130-D-d-2-4 --json
archiwista search --product=nmt --years=2020-2023 --versions=all --limit=200 --json
curl -sf -b "$JAR" -H "$H" "$BASE/slots?product=nmt&years=2020-2023&versions=all&limit=200"
curl -sf -b "$JAR" -H "$H" "$BASE/slots?bbox=19.9,50.0,20.0,50.05&location=with"
```

The answer (`CatalogPage`, abridged):

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

`groups` counts the location groups in the **whole** result (all pages),
whatever `location` is chosen. Rows without a location have no outline and do
not appear on the map (`GET /map/footprints`), but they are in the catalog.

## 4. Paging

The cursor is opaque and bound to its query: fetch the next pages with the
**same** filters and `cursor=<next_cursor>` until `next_cursor` is `null`. The
cursor of another query, a `limit` outside 1–200 or an unknown parameter give
`400 validation_error`. Pages of any size together hold the same rows in the
same order (file name, slot, store).

```sh
cursor=""
while :; do
  page="$(archiwista search --versions=all --limit=200 ${cursor:+--cursor="$cursor"} --json)"
  printf '%s\n' "$page" | jq -c '.items[] | {store, slot, version: .version.path}'
  cursor="$(printf '%s' "$page" | jq -r '.next_cursor // empty')"
  [ -n "$cursor" ] || break
done
```

The same over HTTP: `"$BASE/slots?versions=all&limit=200&cursor=$cursor"` (the
cursor is safe in a URL).

## 5. Cards, state and freshness

- `archiwista entry MAGAZYN SLOT` / `GET /stores/{store}/slots/{slot}`: the card
  of a file (`SlotCard`): all versions, `current` and `full_sheet`, the pins of
  visible projects (`pinned_by`), problems with a repair instruction and
  `paths` (`local` is the path on this computer, `aliases` the same path under
  other drive letters).
- `archiwista version MAGAZYN WERSJA` /
  `GET /stores/{store}/versions/{version}`: all values of the version from the
  index, the outline in WGS84 and the raw sidecar; the sidecar alone:
  `GET …/versions/{version}/sidecar`.
- `GET /requests/{parent_request}`: the files of one producer request (for
  example both sides of the PL/CZ border).
- `archiwista projects` / `GET /projects` and `archiwista project PROJEKT` /
  `GET /projects/{project}`: the projects visible to the actor; a hidden project
  answers like a missing one (`404`). Each project says whether the actor may
  change it now (`project_write`: its owner or an administrator; read at each
  request), as the project's changes and jobs below decide it. `archiwista
  project-status PROJEKT` / `GET /projects/{project}/status` asks the producer
  for the state now (no network).
- `archiwista project-init PRODUCENT KATALOG --store MAGAZYN` / `POST /projects`
  (`{"producer", "path", "store"}`), `archiwista project-add PROJEKT NAZWA
  POLECENIE [--options JSON]` / `POST /projects/{project}/tasks` (`{"name",
  "command", "options"}`, optionally `"producer"`) and `archiwista
  project-remove PROJEKT NAZWA` / `DELETE /projects/{project}/tasks/{name}`
  (v0.3, ADR-039): the producer writes its manifest, and the answer is the
  project's card as the index holds it at once (`201` with `Location` for a
  new project, `201` for a task, `200` for a removal). A new project lies in a
  project directory of the settings or at most four levels below one, outside
  hidden directories and stores (`400 project_not_discoverable`; elsewhere
  `403 path_outside_root`), and names a configured store (`404`) with a
  directory of the producer (`400 store_without_producer`) that can be read
  now (`503 store_unavailable`); it has no owner yet, so only an administrator
  creates one. A task is changed by the project's owner or an administrator
  (`404` for a hidden project, `403 permission_denied` for one seen but not
  owned); its command is in the producer's catalog (`400 unknown_command`), its
  options are checked without the network (`400` with the producer's text and
  `details.option`), and an option that is a file path is `403`. Removing a
  task keeps its files in the store. A producer that changes no projects
  answers `422 unsupported` (`no_project_actions`).
- `archiwista project-download PROJEKT [ZADANIE ...]`, `project-repin PROJEKT
  ZADANIE`, `project-check PROJEKT [ZADANIE ...]` and `project-verify PROJEKT
  [ZADANIE ...]` / `POST /projects/{project}/jobs` (`{"kind": "download"}`,
  `"repin"`, `"check"` or `"verify"`, optionally `"tasks": ["…"]`: every task
  when left out, exactly one for a repin; v0.3, ADR-040) start a job of the
  project's tasks (section 9). A download and a repin write the store and the
  manifest through the producer, so they need the project's owner or an
  administrator and `store_writer` (or the setting `store_write_for_all`); a
  check and a verification need only to see the project.
- `archiwista status` / `GET /health`: versions, sources, the index and every
  store: `status` (`unknown` not scanned yet, `available`, `unavailable`),
  counters, `last_scan` with the actor, `running_job` with its progress,
  `stale`.

Address a slot and a version by the relative path from the results (`slot`,
`version.path`, `current`), never by a file system path. There is no need to
read the disk or parse sidecars: the API returns everything from the index.

**Freshness.** Every answer from the index has `stale` and `stale_stores`. When
a store is unavailable (for example a disconnected SMB share), lists and cards
still answer `200` from the index as of `indexed_at`, and `stale` is `true`: an
agent should tell the user so, not treat the result as the current state of the
disk.

**Offline mode.** The setting `offline` (`GET /settings`) turns off everything
that needs the network; reading the index, cards and local scans still work,
and a job of unit outlines gets `409 conflict` (`offline_mode`).

**Area and local state.** `POST /areas` keeps an area: a GeoJSON `Polygon` or
`MultiPolygon` in WGS84 as `application/json` (`{"geometry": {…}, "name":
"…"}`), or a GeoJSON, GeoPackage or ZIP with one Shapefile as the raw body (for
example `Content-Type: application/octet-stream`; `?name=` and, for a file with
several layers, `?layer=`). The answer `201` has an `id` (the same geometry
always gets the same one), the area in km² (`area_km2`, `area_crs`) and the
countries. The `id` is the parameter `area_id` of `/slots` (`archiwista search
--area-id`) and of `GET /local-coverage?area_id=…&product=…&store=…`: how much of
the area the current versions of the product in the store cover: `results` with
the country, `percent` (rounded down) and `label` ("lokalnie 83% obszaru").
Before counting, the server reads the area's slots from the store (at most 500,
up to 10 s); otherwise it answers from the index and gives the reason in
`stale_reason`.

```sh
AREA="$(curl -sf -b "$JAR" -H "$H" -H 'Content-Type: application/json' \
  -d '{"geometry": {"type": "Polygon", "coordinates": [[[19.9, 50.0],
       [20.0, 50.0], [20.0, 50.05], [19.9, 50.05], [19.9, 50.0]]]}}' \
  "$BASE/areas" | jq -r .id)"
curl -sf -b "$JAR" -H "$H" "$BASE/local-coverage?area_id=$AREA&product=nmt&store=zespol"
archiwista search --area-id="$AREA" --product=nmt --json
```

## 6. Previews, layers, comparison, own data (v0.2), producers' commands and availability (v0.3)

Take a `ref` from the answer of the card of a version, of an own file or of a
snapshot: `version:<store>:<version-path>`, `file:<project>:<file-path>` or
`snapshot:<project>:<label>:<file-path>`. Do not build references from absolute
file system paths. Before it touches the preview cache the resolver checks the
visibility of the project. An invisible project gives `404`, a missing right to
a snapshot `403`.

`GET /stores/{store}/versions/{version}/preview` returns `PreviewInfo`: `state`
(`ready`, `needs_build`, `building`, `unavailable`), `kind`, `reason` (`code`,
a `message` and a `fix` in the language of the request), `styles`,
`default_style` and the addresses
`thumbnail_url`, `tiles_url`, `features_url`, `members_url`. For `needs_build`
call `POST …/preview`: `202` returns a job, `200` means the preview is ready.
Fetch the image with `GET …/preview.png?size=512` (`--style` in the CLI, the
parameter `style` over HTTP). The tiles `…/tiles/{z}/{x}/{y}.png`, the vectors
`…/features?bbox=…&zoom=…` and the ZIP listing `…/members` have the same
session and CSRF header protection, **images too**. Requests for a disconnected
store may use the cache and give the reason when it has nothing.

```sh
archiwista search --project=projekt-01 --json
# REF comes from the field ref of a version card or a file card returned by the API.
archiwista preview "$REF" --build --json
archiwista preview "$REF" --output=<data-dir>/podglad.png
```

`POST /previews/warm` (v0.3, ADR-041) prepares the first look at current
versions ahead: the pane's thumbnail (`size=512`, the default style) and the
map's tiles at the file's smallest zoom go into the preview cache, so the first
request for them does not read a slow store. The optional body narrows it:
`{"store": "…", "product": "…", "segment": "…", "project": "…", "area_id":
"…"}`; no body is every store's current versions. `project` adds the working
files of that project's own data, and makes the job the project's: only those
who see the project see it (another session gets `404`, as for an unknown
project). The job (`preview_warm`) runs at the lowest priority, never evicts a
preview used in the last week, and ends `partial` with `stopped: cache_full`
and the number `skipped` when the cache has no more room; `needs_build` counts
the files whose map waits for a local COG (it builds none). `archiwista
preview-warm --json` runs the same in the foreground:

```sh
archiwista preview-warm --store=zespol --product=nmt --json
```

`GET /local-layers?store=demo&product=nmt&area_id=$AREA&group=year` returns the
years (or `group=campaign`), their keys, the coverage and the addresses of
thumbnails and tiles. Without `area_id` it gives counters, not images. Use the
address `thumbnail_url` of the answer; do not guess the key and the version of
the image:

```sh
archiwista layers --store=demo --product=nmt --area-id="$AREA" --json
LAYER="$(archiwista layers --store=demo --product=nmt \
  --area-id="$AREA" --json | jq -r '.layers[0].key')"
archiwista layers --store=demo --product=nmt --area-id="$AREA" \
  --thumbnail="$LAYER" --output=<data-dir>/rok.png
curl -sf -b "$JAR" -H "$H" "$BASE/local-layers?store=demo&product=nmt&area_id=$AREA&group=year"
archiwista compare "$REF_A" "$REF_B" --json
curl -sf -b "$JAR" -H "$H" -G --data-urlencode "a=$REF_A" \
  --data-urlencode "b=$REF_B" "$BASE/compare"
```

The folder of a project (by default `<project directory>/dane/`; an
administrator sets another one with `PUT /projects/{project}/data-dir`) is
indexed apart from the store: `GET /projects/{project}/files?q=…&state=changed`
with `limit`/`cursor`, `GET …/files/{file_id}` and `GET …/files/{file_id}/layers`
(the working file and its snapshots in the fan). Images, tiles, features and the
listing of an archive have counterparts of the version routes under
`…/files/{file_id}/preview`, `…/files/{file_id}/snapshots/{label}/preview` and
so on. A file changed since the last scan has to be scanned again instead of
using the old preview. The snapshot plan checks feasibility and size without
making it; `POST …/snapshots` needs `project.write` (the project owner or an
admin) and returns a `snapshot` job; identical content gives the result
`unchanged`.

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

`GET /jobs?project=projekt-01` filters the jobs of a project. The list, the
details `/jobs/{job}` and the SSE `/jobs/{job}/events` do not reveal jobs with
data of an invisible project (`404` for a direct address); an ordinary store
scan is shared. The SSE sends `progress`, `notice` and `state`, and a client
resumes after `Last-Event-ID`.

**The producers' commands (v0.3, ADR-034).** `GET /commands` lists the commands
of every producer whose plugin offers them (Kartograf's catalog; `?producer=`
keeps one producer): each with its options (JSON type, whether required, the
allowed values and their meanings, the default, bounds, the `group` of mutually
exclusive options and the `path_role` of a file path), what a run does
(`read_only`, `writes`, `network`, `check`, `store`) and complete example lines;
the summary and the description follow `Accept-Language`. `POST /commands/parse`
reads a pasted line into a call (`command`, `options`, and `run`: the store root
and the flags the line gives beside the options), `POST /commands/validate`
checks a call without the network and `POST /commands/format` writes the
producer's canonical line of a call, which parses back into the same call. A
command that works on a store is checked with the directory of a configured
store (`store`), never with the producer's default root, and an option that is a
file path is refused (`403`, `path_outside_root`). The producer's own refusal is
`400 validation_error` with its text and hint and the option in
`details.option`. Nothing here downloads or writes.

```sh
archiwista commands list --producer=kartograf --json
archiwista commands parse kartograf "kartograf sheet parse --sheet N-34-130-D-d-2-4" --json
archiwista commands validate kartograf "elevation download" --store=demo --json \
  --options='{"product": "nmt", "sheet": "N-34-130-D-d-2-4", "resolution": "1m", "vertical_crs": "EVRF2007"}'
curl -sf -b "$JAR" -H "$H" -X POST -H 'Content-Type: application/json' \
  -d '{"producer": "kartograf", "line": "kartograf sheet parse --sheet N-34-130-D-d-2-4"}' \
  "$BASE/commands/parse"
```

**The availability at the source (v0.3, ADR-035).** `POST /availability` with
`{"area_id": "…", "product": "nmt"}` (`producer` is `kartograf` by default; the
products a producer checks are listed in the `422` that refuses another one) asks
what the source has for a kept area. A report the index keeps that is younger
than seven days answers at once: `200` with `AvailabilityInfo`, the area,
`checked_at` (when the source was asked), `job_id` and `report` (the producer's
report: the parts of the area by country with their land, the combinations of a
year, a variant and a format with their full, partial and missing sheets, the
sheet records and campaigns a download takes and `full_m2`, the parts that
failed, the producer's notices, `ok`). Otherwise, or with `"force": true`, the
answer is `202` with the `availability` job (`Location`); a request that asks
what an active check asks gets that job. When the job succeeded, `GET
/availability?area_id=…&product=…` returns its report; it reads only the index,
never the network, and answers `404` without a report. In offline mode a check
that needs the source is `409 conflict` (`offline_mode`) and nothing is
recorded. `archiwista availability check` runs the job in the foreground and
prints the `AvailabilityInfo` it kept (`--json`); a check that does not succeed
prints its `JobDetail` and exits `11` or `130`.

Every `AvailabilityInfo` also reads the report for a person (SPEC 6.3, 6.4):
`rows`, one per year of each country in the report's order, each with the
`label` of its best variant (`complete`, `complete · 2 campaigns`,
`partial · 58% · 1 partial sheet`, `no data`; Polish with `Accept-Language: pl`),
the same as structure in `coverage` (`kind`, `campaigns`, `full_share`,
`percent` rounded down and at most 99 when partial, `below_one`,
`partial_sheets`, `missing_sheets`), `other_variants` and `variants`, best
first (complete, larger full share, fewer campaigns, finer resolution, the
report's order; the formats of one set are one variant with its
`default_format`, ASC then TIFF, and its size). `store` (a configured store,
else `404`) gives every variant its store badge `local` (`state` `all`, `some`
or `none`, `units` of `of`, `label` `downloaded 5/12`); `horizontal`,
`resolution` and `vertical_crs` fix those dimensions, and a year without such
a variant is `no_data`. The command takes them as `--store`, `--horizontal`,
`--resolution` and `--vertical-crs`, and its text prints a line per year.

```sh
curl -sf -b "$JAR" -H "$H" -X POST -H 'Content-Type: application/json' \
  -d "{\"area_id\": \"$AREA\", \"product\": \"nmt\"}" "$BASE/availability"
archiwista availability check "$AREA" --product=nmt --json
archiwista availability show "$AREA" --product=nmt --store=zespol --json
```

## 7. Errors

Every HTTP error is `application/problem+json` (RFC 9457) with a code of the
shared Nogat error registry (ERR §2). For `GET /slots?limit=201`:

```json
{
  "type": "https://github.com/Daldek/Nogat/blob/main/standards/ERROR_REGISTRY.md#validation_error",
  "title": "Invalid input",
  "status": 400,
  "detail": "Invalid request data: query.limit.",
  "instance": "/api/v1/slots",
  "code": "validation_error",
  "details": {"reason": "invalid_request"},
  "errors": [{"pointer": "/query/limit", "type": "less_than_equal",
              "message": "Input should be less than or equal to 200"}]
}
```

Members: `type` is the page of the registry and the anchor of the code; `title`
is the title of the code; `status` is the HTTP status of the code; `detail` and
`hint` (one line telling how to fix it, when a fix is known) say what happened
and what to do; `instance` is the path of the request; `details` holds the
project's own cause in `reason` and the context (below); `errors[]` lists
invalid values with a JSON Pointer.

The texts follow the request header `Accept-Language`: `title`, `detail`,
`hint`, the texts inside `details` (the `message` and `fix` of
`preview_reason`, the `message` of `problems[]`) and the `message` of the
`errors[]` that Archiwista's own validators make are English, and Polish when
Polish has the highest quality in the header; any other language, a malformed
header and no header give English (the `message` that pydantic makes itself
is English always). Every JSON answer under `/api/v1`, a problem and an event
stream have `Content-Language` (`en` or `pl`) and `Vary: Accept-Language`;
images, `/api/v1/openapi.json` (English always) and the files of the interface
have neither. What is written when it happens, and not when it is read, stays
Polish whatever the request says: the `detail` of a store that is not
`available`, and the `message` of the `notice` events of a job (section 9).

Base decisions on `status`, `code` and `details.reason`, never on the text of
`detail`.

| Status | `code` | `details.reason` and what to do |
|---|---|---|
| 400 | `validation_error` | `invalid_request`: invalid parameters or body, see `errors` (`pointer`, `type`, `message`); `invalid_settings`: `details.problems` (`code`, `field`, `message`, and `reason` and `hint` when the producer refuses the directory: `no_marker`, `unsupported_marker`, `foreign_store` or `not_a_store` for Kartograf); `invalid_ref`: a malformed reference; `area_too_large`: an area file over 50 MB or an archive over 200 MB unpacked; `area_too_complex`: more than 100 000 vertices; `request_too_large`: the body is over the limit (4 KiB for the token exchange, 1 MiB for the rest); `kartograf_error`: the producer refused a command line or a call (`/commands/…`), its own text and hint, the option in `details.option`; `unknown_command`, `store_required`, `store_without_producer`: a command outside the producer's catalog, a command on a store without `store`, a store without a directory of the producer (`details.option`); no reason: an unknown store, area or cursor |
| 401 | `unauthorized` | `session_required`: no, expired or unknown session; a wrong, used or expired token → a new token |
| 403 | `forbidden` | `csrf_rejected`: no or wrong `X-Archiwista-CSRF` in any `/api` request, or a foreign `Origin`; `invalid_host`: a `Host` other than `127.0.0.1:<port>`/`localhost:<port>`; `permission_denied`: the actor has no right (for example a settings change without the role `admin`); `path_outside_root`: the path leaves the store, or an option of a command is a file path (`details.option`) |
| 404 | `not_found` | an unknown resource, or a project invisible to the actor |
| 405 | `method_not_allowed` | another method; the allowed ones are in the header `Allow` |
| 409 | `conflict` | no reason: a job that writes this store's index runs already (`details.job`: `id`, `kind`, `state`), follow it instead of retrying; `offline_mode`: the operation needs the network and offline mode is on; `snapshot_blocked` (`details.blocked_by`) or `own_file_changed`: the plan blocks the snapshot or the file changed since its scan, refresh the folder and read the plan; `preview_not_ready`: the preview needs its build first (`details.build_required`, or `details.job`/`details.building` while it builds) |
| 422 | `unsupported` | `preview_unavailable`: the file has no preview of the kind asked for (`details.preview_reason`: `code`, `message`, `fix`); `no_commands`: the producer offers no commands; `no_availability`: the producer checks no availability of the product (`details.allowed`: the products it checks) |
| 422 | `calculation_error` | `preview_timeout`: a render process ran past its time limit |
| 429 | `rate_limited` | `preview_busy`: the render pool is full; wait for `Retry-After` |
| 500 | `data_error` | `area_unreadable`: an area file cannot be read (for a file with several layers `details.layers`: choose one with `?layer=`); `kartograf_error`, `imgwtools_error`, `producer_error`: the producer rejected the call, `details.kartograf`/`details.imgwtools` have `exception` and the unchanged `message` |
| 500 | `internal_error` | a defect of Archiwista: details in the server's log |
| 503 | `missing_dependency` | `source_unavailable`: the producer plugin is missing; `source_incompatible`: it has an unsupported version or schema; `details.source` (`id`, `state`, `package_version`, `supported_versions`, `requirement`), the fix is in `hint` and at the end of `detail` |
| 503 | `store_unavailable` | `store_unreadable`: the store cannot be read and the index has no answer |

The command line gives the same information as the error document
`archiwista-error/1` on the last line of standard error (nothing goes to
standard output), for example for `archiwista search --limit=201 --json`:

```json
{"schema":"archiwista-error/1","code":"validation_error","title":"Invalid input","message":"Invalid request data: query.limit.","details":{"reason":"invalid_request","errors":[{"pointer":"/query/limit","type":"less_than_equal","message":"Input should be less than or equal to 200"}]},"exit_code":2}
```

`exit_code` is the registry's exit code of `code` (`null` for the codes that
exist only in REST: `unauthorized`, `method_not_allowed`, `rate_limited`; the
command then exits `1`); `message` and `hint` are English, as the document is
machine output, and the line before it, for a person, says the same in Polish;
`command` is the `<group> <verb>` of the command when it has that shape. The
schema is `schemas/nogat/error-1.schema.json`.

## 8. Recommended workflow of an agent

1. **Orientation:** `archiwista status --json` (or `GET /health`): are there
   stores, are they `available`, is the producer plugin `available`, does a
   scan run (`running_job`).
2. **Search:** `search` with the narrowest possible filters (`--product`,
   `--unit`, `--years`, `--bbox`), `--limit=200` and a loop over `next_cursor`;
   do not fetch the whole catalog when a filter is enough.
3. **Details:** the card of a file (`entry`) for the chosen slots; `version`
   only when all metadata or the sidecar are needed.
4. **Freshness:** check `stale`; when it is `true`, give the user `indexed_at`
   from `stale_stores` instead of claiming that the file is on the disk.
5. **Refresh (on request only):** `POST /stores/{store}/scan` with CSRF → `202`
   with a job; follow the progress over SSE or `GET /health` (`running_job`).
   On `409 conflict` wait for the running job instead of retrying.
6. **Errors:** pass `503 missing_dependency` (`source_unavailable` or
   `source_incompatible`) to the user with the fix from `hint`, and do not
   retry in a loop; `401` → a new token from the user (`archiwista token`).
7. **Paths:** to work with a file use `paths.local` from the card; do not build
   paths yourself.

## 9. Background jobs and SSE

Long operations return `202 Accepted` with a job (`JobDetail`) and the header
`Location: /api/v1/jobs/{id}`. All need `X-Archiwista-CSRF`.

| Request | Body | Notes |
|---|---|---|
| `POST /stores/{store}/scan` | optionally `{"mode": "incremental"}` (default) or `"full"`, optionally `"segment"` | scan of a store into the index; a `segment` is scanned by the data source that owns it, and a source that reads only its whole directory (IMGWTools: a segment is a dataset) ends the job as `unsupported` |
| `POST /stores/{store}/footprints` | none | unit outlines (TERYT, KU) from the network; offline → `409 conflict` (`offline_mode`) |
| `POST /stores/{store}/link-check` | `{"slot": "…"}` | confirmation of the target of a slot's link; an unknown slot → `404` |
| `POST /projects/{project}/scan` | none | scan of the project's folder, open to those who see the project |
| `POST /projects/{project}/files/{file_id}/snapshots` | `{"note":"…"}` or none | a snapshot, needs `project.write` |
| `POST /projects/{project}/jobs` | `{"kind": "download"}`, `"repin"` (with `"tasks": ["…"]`, exactly one), `"check"` or `"verify"`; optionally `"tasks"` (every task when left out) | a job of a project's tasks (v0.3, ADR-040): `project_download` downloads and pins the tasks not downloaded yet and restores missing pinned versions in the configured store the manifest names, `project_repin` pins one task anew to the source's newer versions, `project_check` compares the pins with the source without effects, `project_verify` checks the pinned files in the store (no network); the job has no `store`, its `params` are `project` and `tasks`. A download and a repin need the project's owner or an administrator and `store_writer` (`403`); a hidden project is `404`; refused before a job: a manifest naming no configured store (`409`, `unknown_store`), a producer without project jobs (`422`, `no_project_actions`), a second job of the project (`409 conflict`, `details.job`), offline mode for all but `verify` (`409 offline_mode`). A lock of the manifest that stays fails the job (`conflict`, `project_locked`, `details.lock`) |
| `POST …/preview` | none | build of the preview of a file or a version (answer `200` or a job `202`) |
| `POST /previews/warm` | none, or any of `{"store": "…", "product": "…", "segment": "…", "project": "…", "area_id": "…"}` | the first look at current versions prepared in the preview cache (v0.3, ADR-041): the job `preview_warm` has no `store`, its `params` are the filters (and `since`, set only by the scheduler's warm-up after a scan); any session may ask; a store that is not configured, a project the session does not see and an unknown area → `404` before a job; a request of the filters of a waiting warm-up returns that job |
| `POST /availability` | `{"area_id": "…", "product": "…"}`, optionally `"producer"`, `"force"`, and `"store"`, `"horizontal"`, `"resolution"`, `"vertical_crs"` for the rows of a `200` | what the source has for a kept area (v0.3): a report younger than seven days answers `200` without a job (unless `force`), else the `availability` job `202`; offline → `409 conflict` (`offline_mode`); a store that is not configured → `404` before a job |
| `POST /jobs` | `{"kind": "check", "producer": "…", "store": "…", "command": "…", "options": {…}}`; for a run `"kind": "download"`, optionally `"plan_job": "…"` (a `check` job of the same store, producer, command and options) | a job of a command of the producer's catalog that works on a store and has a check (v0.3): `check` plans a run in the store's directory of the producer without its effects, `download` runs it there (with `plan_job` only that plan's positions to download; one whose source changed since is a failed item, `stale_plan`), both over the network; refused before a job exists: a download by a session without `store_writer` (and without the setting `store_write_for_all`) `403` (`permission_denied`; an agent has the roles of the person who issued its token), a store that is not configured `404`, a command outside the catalog `400` (`unknown_command`), a store without a directory of the producer `400` (`store_without_producer`), a command on no store or without a check `422` (`no_store`, `no_check`), an option that is a file path `403` (`path_outside_root`), the producer's refusal of the options `400` (its text, `details.option`), a `plan_job` the session does not see or that kept no plan `404`, one of another store or call `409` (`plan_mismatch`, `details.job`), `plan_job` with `check` `400`, a missing plugin `503`, offline `409` (`offline_mode`); the job keeps the options as the producer read them |

An unknown store gives `404 not_found`, a wrong body `400 validation_error`.
When a job that writes the store's index (a scan or outlines) runs already, the
answer is `409 conflict` with `details.job` (`id`, `kind`, `state`): follow that
job instead of creating another.

A job (`GET /jobs/{id}`) has the fields `id`, `kind` (`scan`, `footprints`,
`link_check`, `preview`, `own_scan`, `snapshot`, `availability`, `check`, `download`,
`project_download`, `project_repin`, `project_check`, `project_verify`, `preview_warm`), `state` (`queued`, `running`,
`succeeded`, `partial` (part of its units failed: `result` names them), `failed`, `interrupted`, `cancelled`), `actor`, `actor_kind`,
`session`, `store`, `params`, `created_at`, `started_at`, `finished_at`,
`progress`, `result` and `error`. The list: `GET /jobs?kind=&store=&state=&project=`
with `limit` (1–200) and `cursor`, newest first. Jobs with project data check
the visibility of the project in a single card and in the SSE stream too.

The plan of a `check` job that succeeded or ended `partial` is `GET
/jobs/{id}/plan` (`ActionPlanInfo`, from the index, no network): the store, the
producer's command line of the run (`line`, with the store's root), `checked_at`,
`counts` of each status, `todo`, `size_bytes` (`null` when the producer tells no
size, never 0) with `size_complete`, and `entries`: `path` below the store root,
`unit`, `status` (`current`, `newer`, `missing`, `unverifiable`, `check_failed`),
`local_label`, `available_label`, `size_bytes`, `error`, `conflict`. A job the
session does not see, one that is no `check`, one still running and one that
failed are `404`.

A job is controlled by (v0.3; ADR-038):

- `POST /jobs/{id}/cancel` (no body): a job that waits ends `cancelled` at once,
  without a worker; a running one is interrupted and ends `cancelled` once its
  worker has stopped, within 30 s. The answer is `202` with the job as it is
  then (often still `running`): follow its events to the end. A job another
  process runs (`archiwista jobs start` at a terminal, or a server's job
  cancelled with `archiwista jobs cancel`) is stopped by that process within a
  second. Only whoever started the job (`actor`; an agent acts as the person
  who issued its token) or an administrator may: `403 permission_denied`; a
  job that has ended is `409 conflict`, reason `job_finished`.
- `POST /jobs/{id}/retry` (no body): a job that ended `partial`, `failed`,
  `interrupted` or `cancelled` starts again as a new job of the session with its
  kind, store and `params` (`202`, `Location` of the new job; the old job stays
  as it ended). A download fetches only what the store still lacks. One that
  succeeded is `409`, reason `job_succeeded`; one that waits or runs
  `job_active`; a download needs `store_writer` again (`403`), a snapshot the
  project's owner, a project's download or repin both; the new job is refused as
  any job of its kind (`409` for a store whose index another job writes, offline
  mode).
- `GET /jobs/{id}/log`: the end of the job's log, its worker's standard error in
  English (`JobLog`: `job`, `size_bytes` of the whole log, `truncated` when only
  its last MiB is given, `text`). A job that never started a worker, or whose
  log went with the old logs (90 days, 1 GB), is `404`; a `preview` job that
  also builds files of projects the session does not see is `403`.

A job the session does not see is `404` for all three.

Events flow as SSE from `GET /jobs/{id}/events` (`text/event-stream`). Every
frame has `id: <sequence number>`, `event: progress|notice|state` and
`data: <JSON>`:

- `progress`: `current`, `total`; a scan adds `segment` and `entries`, outlines
  `written` and `failed`;
- `notice`: `level`, `code`, `message` (Polish, as written when the job ran);
- `state`: `state`; the last one carries `result` (success; its texts are
  Polish) or `error` (in the language of the request, below).

The stream ends after the final state; for a finished job without new events
the answer is `204`. After 15 s of silence the server sends the comment
`: keepalive`, and a queued job may wait longer, so the client should have no
read timeout (for example `httpx` with `timeout=None`). After a broken
connection resume with the header `Last-Event-ID` equal to the last received
`id`.

The stream, like every `/api` request, needs the header `X-Archiwista-CSRF`.
The browser's `EventSource` sends no headers of its own, so it does not fit
here: read the stream with an ordinary HTTP client that reads the body as it
arrives: `curl -N`, `httpx.stream(…)`, and `fetch` with `response.body` in the
browser (as the Archiwista interface does).

```sh
JOB="$(curl -sf -b "$JAR" -H "$H" -X POST \
  "$BASE/stores/zespol/scan" | jq -r .id)"
curl -sfN -b "$JAR" -H "$H" "$BASE/jobs/$JOB/events"
curl -sf -b "$JAR" -H "$H" "$BASE/jobs/$JOB" | jq '{state, error}'
```

The `error` of a job that did not succeed (`failed`, `interrupted`, `cancelled`) is
described as a problem is (section 7): `code` is a code of the error registry,
`detail` says what happened and `hint` tells how to fix it when a fix is known
(both in the language of the request, also in the final `state` event: the job
keeps the key and the values of each text and renders them when it is read), and
`details` holds the job's own cause as `reason` and the context, whose texts are
Polish, as is the `message` of a `notice` and as is the `detail` of a job
recorded before the texts followed the request. Base decisions on `code` and
`details.reason`, never on the text of `detail`:

| `code` | `details.reason` | What it means |
|---|---|---|
| `store_unavailable` | `store_unreadable` | the store cannot be read now (an unmounted share); the index stays as it was, try again later |
| `store_unavailable` | `no_marker`, `unsupported_marker`, `foreign_store`, `not_a_store` | the producer refuses the directory (Kartograf: no `kartograf-store.json` beside a layout, a marker of another schema or not JSON, the root of an IMGW store, the parent of a store); `hint` gives the command, for `no_marker` `kartograf store init --root <path>`, which marks the store once; the index stays as it was |
| `missing_dependency` | `source_unavailable`, `source_incompatible` | the producer plugin is missing or has an unsupported version: `details.source` and `hint` give the fix |
| `missing_dependency` | `own_reader_failed` | the process that reads own data did not start (for example without the GDAL bindings) |
| `conflict` | `offline_mode` | the job needs the network and offline mode is on |
| `conflict` | `snapshot_blocked` | the plan refuses the snapshot: `details.blocked_by` is `folder_invalid`, `read_only_folder`, `insufficient_space` or `file_missing` |
| `conflict` | `inconsistent_copy`, `target_exists` | a snapshot: the file kept changing while it was copied, or another process published the label first; nothing was published, try again |
| `conflict` | `project_locked` | a job of a project: the lock of its manifest stays (`details.lock`), left by a change that was interrupted while it wrote; remove the directory when no program is changing the project and try again (Archiwista never removes it) |
| `conflict` | `unknown_store` | a project's download or repin: its manifest names no configured store; nothing was written |
| the code of the first failure, e.g. `data_error` | `run_failed` | no unit of a run, or no task of a project's download, succeeded; `details.task` names a project's first failed task |
| `data_error` | `checksum_mismatch`, `integrity_failed` | a snapshot copy differs from its source or fails the SQLite integrity check; nothing was published |
| `data_error` | `kartograf_error` (`<package>_error`) | the producer rejected the call: `details.kartograf` has `exception` and the unchanged `message` |
| `forbidden` | `path_outside_root` | a path leaves the store or the project folder |
| `not_found` | none | the store, slot, project or file is unknown |
| `unsupported` | none | the producer cannot do it (a link check without link support; a scan of one segment of a directory the producer reads whole, as IMGWTools does) |
| `cancelled` | none | cancelled by the person, or the store was removed |
| `cancelled` | `interrupted` | the server stopped or the worker was interrupted; safe to try again |
| `internal_error` | `worker_crashed` | the worker ended without a result: `detail` names the signal or exit status and the job log |
| `internal_error` | `protocol_error` | the worker could not read its job |
| `internal_error` | none | a defect of Archiwista: details are in the job log |

Jobs recorded by 0.2.0 are read with these codes too (their old job code is the
reason). The CLI's job commands are `archiwista jobs start`, `jobs retry`, the
project commands `project-download`, `project-repin`, `project-check` and
`project-verify`, and `preview-warm` (a job in the foreground; they print the
job's `JobDetail` as it ended and exit `0`, `10` for `partial`, `11` or `130`),
and `jobs list`, `jobs show`, `jobs cancel`, `jobs plan` and `jobs log`, which
exit `0`; `jobs cancel` also stops a
job a running server supervises. `archiwista reindex [--store MAGAZYN]` runs a
full scan in the foreground (for the owner at a terminal, not for an agent next
to a running server: both go to the same queue and get a conflict, exit `4`,
when they meet).

## 10. Limits of v0.2

- Local mode only: one person on `127.0.0.1`, no login; accounts and groups
  serve the visibility of projects (A-ADR-029).
- No downloading of data, no availability checks at the source and no producer
  actions that change a project manifest (plan v0.3).
- No IMGW data in Archiwista, no chat and no MCP; an external agent uses the
  API described above.
