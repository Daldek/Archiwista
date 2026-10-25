# Archiwista API for agents and scripts

A guide for AI agents (for example Claude Code) and scripts that use Archiwista
without a browser. It describes release 0.2.0: reading the catalog, previews,
layers, comparison, own data and project snapshots, areas and jobs. An agent
uses the HTTP API `/api/v1` or the commands `archiwista … --json`; there is no
chat tool and no MCP server.

Until v1.0 the API may change. The full schema with examples is always at
`/api/v1/openapi.json` (it needs a session) and the interactive documentation
at `/api/docs` (it uses the session of an open Archiwista tab). Field names,
parameter names and codes are English; texts for people (`detail`, `hint`,
`message`) are Polish, and the `title` of an error is English, or Polish for
`Accept-Language: pl`.

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
| session token for an agent | `archiwista token --json` | `POST /session/tokens` |
| area and local state of a product | — (HTTP creates an area; its rows: `search --area-id`) | `POST /areas`, `GET /local-coverage` |
| store scan, jobs, SSE | — (HTTP only) | `POST /stores/{store}/scan`, `/jobs` |
| preview and build, optional PNG | `archiwista preview REF [--build] [--output FILE.png]` | `GET`/`POST /stores/{store}/versions/{version}/preview`, `GET …/preview.png` |
| comparison of the metadata of two objects | `archiwista compare REF REF` | `GET /compare?a=REF&b=REF` |
| years/campaigns and thumbnail of a layer | `archiwista layers --store ID --product PRODUKT --area-id ID [--thumbnail KLUCZ --output FILE.png]` | `GET /local-layers`, `GET /local-layers/thumbnail.png` |
| files of a project and the card of a file | `archiwista files PROJEKT`, `archiwista file PROJEKT PLIK` | `GET /projects/{project}/files`, `GET …/files/{file_id}` |
| plan and making of a snapshot | `archiwista snapshot PROJEKT PLIK --plan`, `archiwista snapshot PROJEKT PLIK [--note TEKST]` | `GET …/files/{file_id}/snapshot-plan`, `POST …/files/{file_id}/snapshots` |
| scan of the own-data folder | `archiwista own-scan [--project PROJEKT]` | `POST /projects/{project}/scan` |

The CLI reads the local index without a running server and calls the same
services as the HTTP routes, as the owner of the local installation
(`LOCAL_OWNER`, roles `admin` and `store_writer`). With `--json`:

- standard output carries nothing but JSON of the route's response schema, the
  same as over HTTP, including the fields `stale` and `stale_stores`;
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
  standard error, in Polish, and so does the log; it never goes to standard
  output. Every command takes `--verbose` (debug) or `--quiet` (errors only),
  before or after its name, and without them the variable `ARCHIWISTA_LOG_LEVEL`
  (`debug`, `info`, `warning`, `error`) sets the level; the default is `warning`.

Without `--json` the commands print a short Polish text for people; an agent
should always pass `--json`.

The CLI downloads no data and changes no store. The commands `users`,
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
   ["admin", "store_writer"], "label": "…", "csrf_token": "…", "expires_at":
   "…"}`: `csrf_token` appears only here, and `roles` are the roles of the
   actor (an agent has the roles of the person who issued the token).
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
  the roles read at this request; `DELETE /session` ends it. An agent does not
  issue tokens for further sessions (`POST /session/tokens` → `403 forbidden`,
  `permission_denied`): the owner gives a new token (`archiwista token`).
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
  answers like a missing one (`404`). `GET /projects/{project}/status` asks the
  producer for the state now (no network).
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

## 6. Previews, layers, comparison and own data (v0.2)

Take a `ref` from the answer of the card of a version, of an own file or of a
snapshot: `version:<store>:<version-path>`, `file:<project>:<file-path>` or
`snapshot:<project>:<label>:<file-path>`. Do not build references from absolute
file system paths. Before it touches the preview cache the resolver checks the
visibility of the project. An invisible project gives `404`, a missing right to
a snapshot `403`.

`GET /stores/{store}/versions/{version}/preview` returns `PreviewInfo`: `state`
(`ready`, `needs_build`, `building`, `unavailable`), `kind`, `reason` (`code`,
a Polish `message`, `fix`), `styles`, `default_style` and the addresses
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

## 7. Errors

Every HTTP error is `application/problem+json` (RFC 9457) with a code of the
shared Nogat error registry (ERR §2). For `GET /slots?limit=201`:

```json
{
  "type": "https://github.com/Daldek/Nogat/blob/main/standards/ERROR_REGISTRY.md#validation_error",
  "title": "Invalid input",
  "status": 400,
  "detail": "Niepoprawne dane żądania: query.limit.",
  "instance": "/api/v1/slots",
  "code": "validation_error",
  "details": {"reason": "invalid_request"},
  "errors": [{"pointer": "/query/limit", "type": "less_than_equal",
              "message": "Input should be less than or equal to 200"}]
}
```

Members: `type` is the page of the registry and the anchor of the code; `title`
is the title of the code in English, in Polish for the request header
`Accept-Language: pl` (with `Content-Language: pl` in the answer); `status` is
the HTTP status of the code; `detail` and `hint` (one line telling how to fix
it, when a fix is known) are always Polish; `instance` is the path of the
request; `details` holds the project's own cause in `reason` and the context
(below); `errors[]` lists invalid values with a JSON Pointer.

Base decisions on `status`, `code` and `details.reason`, never on the text of
`detail`.

| Status | `code` | `details.reason` and what to do |
|---|---|---|
| 400 | `validation_error` | `invalid_request`: invalid parameters or body, see `errors` (`pointer`, `type`, `message`); `invalid_settings`: `details.problems` (`code`, `field`, `message`); `invalid_ref`: a malformed reference; `area_too_large`: an area file over 50 MB or an archive over 200 MB unpacked; `area_too_complex`: more than 100 000 vertices; `request_too_large`: the body is over the limit (4 KiB for the token exchange, 1 MiB for the rest); no reason: an unknown store, area or cursor |
| 401 | `unauthorized` | `session_required`: no, expired or unknown session; a wrong, used or expired token → a new token |
| 403 | `forbidden` | `csrf_rejected`: no or wrong `X-Archiwista-CSRF` in any `/api` request, or a foreign `Origin`; `invalid_host`: a `Host` other than `127.0.0.1:<port>`/`localhost:<port>`; `permission_denied`: the actor has no right (for example a settings change without the role `admin`); `path_outside_root`: the path leaves the store |
| 404 | `not_found` | an unknown resource, or a project invisible to the actor |
| 405 | `method_not_allowed` | another method; the allowed ones are in the header `Allow` |
| 409 | `conflict` | no reason: a job that writes this store's index runs already (`details.job`: `id`, `kind`, `state`), follow it instead of retrying; `offline_mode`: the operation needs the network and offline mode is on; `snapshot_blocked` (`details.blocked_by`) or `own_file_changed`: the plan blocks the snapshot or the file changed since its scan, refresh the folder and read the plan; `preview_not_ready`: the preview needs its build first (`details.build_required`, or `details.job`/`details.building` while it builds) |
| 422 | `unsupported` | `preview_unavailable`: the file has no preview of the kind asked for (`details.preview_reason`: `code`, `message`, `fix`) |
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
{"schema":"archiwista-error/1","code":"validation_error","title":"Invalid input","message":"Niepoprawne dane żądania: query.limit.","details":{"reason":"invalid_request","errors":[{"pointer":"/query/limit","type":"less_than_equal","message":"Input should be less than or equal to 200"}]},"exit_code":2}
```

`exit_code` is the registry's exit code of `code` (`null` for the codes that
exist only in REST: `unauthorized`, `method_not_allowed`, `rate_limited`; the
command then exits `1`); `message` and `hint` are Polish; `command` is the
`<group> <verb>` of the command when it has that shape. The schema is
`schemas/nogat/error-1.schema.json`.

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
| `POST …/preview` | none | build of the preview of a file or a version (answer `200` or a job `202`) |

An unknown store gives `404 not_found`, a wrong body `400 validation_error`.
When a job that writes the store's index (a scan or outlines) runs already, the
answer is `409 conflict` with `details.job` (`id`, `kind`, `state`): follow that
job instead of creating another.

A job (`GET /jobs/{id}`) has the fields `id`, `kind` (`scan`, `footprints`,
`link_check`, `preview`, `own_scan`, `snapshot`), `state` (`queued`, `running`,
`succeeded`, `failed`, `interrupted`, `cancelled`), `actor`, `actor_kind`,
`session`, `store`, `params`, `created_at`, `started_at`, `finished_at`,
`progress`, `result` and `error`. The list: `GET /jobs?kind=&store=&state=&project=`
with `limit` (1–200) and `cursor`, newest first. Jobs with project data check
the visibility of the project in a single card and in the SSE stream too.

Events flow as SSE from `GET /jobs/{id}/events` (`text/event-stream`). Every
frame has `id: <sequence number>`, `event: progress|notice|state` and
`data: <JSON>`:

- `progress`: `current`, `total`; a scan adds `segment` and `entries`, outlines
  `written` and `failed`;
- `notice`: `level`, `code`, `message`;
- `state`: `state`; the last one carries `result` (success) or `error`.

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
`detail` is Polish, `hint` tells how to fix it when a fix is known, and `details`
holds the job's own cause as `reason` and the context. Base decisions on `code` and
`details.reason`, never on the text of `detail`:

| `code` | `details.reason` | What it means |
|---|---|---|
| `store_unavailable` | `store_unreadable` | the store cannot be read now (an unmounted share); the index stays as it was, try again later |
| `missing_dependency` | `source_unavailable`, `source_incompatible` | the producer plugin is missing or has an unsupported version: `details.source` and `hint` give the fix |
| `missing_dependency` | `own_reader_failed` | the process that reads own data did not start (for example without the GDAL bindings) |
| `conflict` | `offline_mode` | the job needs the network and offline mode is on |
| `conflict` | `snapshot_blocked` | the plan refuses the snapshot: `details.blocked_by` is `folder_invalid`, `read_only_folder`, `insufficient_space` or `file_missing` |
| `conflict` | `inconsistent_copy`, `target_exists` | a snapshot: the file kept changing while it was copied, or another process published the label first; nothing was published, try again |
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
reason). The CLI has no job commands:
`archiwista reindex [--store MAGAZYN]` runs a full scan in the foreground (for
the owner at a terminal, not for an agent next to a running server: both go to
the same queue and get a conflict, exit `4`, when they meet).

## 10. Limits of v0.2

- Local mode only: one person on `127.0.0.1`, no login; accounts and groups
  serve the visibility of projects (A-ADR-029).
- No downloading of data, no availability checks at the source and no producer
  actions that change a project manifest (plan v0.3).
- No IMGW data in Archiwista, no chat and no MCP; an external agent uses the
  API described above.
