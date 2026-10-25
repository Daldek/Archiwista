# Archiwista: a local web application for browsing spatial-data stores

Archiwista is a local web application for browsing the spatial-data stores that Kartograf writes (and, from v0.5, the IMGW archives that IMGWTools writes): catalog, map, file previews, version comparison, and project folders with snapshots of own data. It has a web interface, an HTTP API and a command line, and never writes to a store.

## When to use

- Find out what a store holds: search by sheet code, unit (TERYT, KU), product, years, campaign or area, on a map or in a catalog.
- Check what is on the disk and how fresh it is: file cards with the sidecar metadata, the state of each store, a local index that is rebuilt on demand.
- Look at a file without opening a GIS: previews of rasters, vectors, point clouds and archives, the "Fan" (Wachlarz) of years of one place, the "Timeline" (Oś czasu) and a before/after "curtain".
- Keep the data of a project (own files and their snapshots) beside the producer's data, and let scripts or AI agents read it through the same API.

## When not to use

| Need | Use instead |
|---|---|
| Download or process data | [Kartograf](https://github.com/Daldek/Kartograf) (Polish and Czech spatial data) or [IMGWTools](https://github.com/Daldek/IMGWTools) (IMGW data); Archiwista only calls their public API |
| GIS analysis, editing data | QGIS; Archiwista is not an editor |
| Hydrological calculations, statistics of series | [Hydrolog](https://github.com/Daldek/Hydrolog) and [Retman](https://github.com/Daldek/Retman) |
| Current IMGW or ČHMÚ data (states, warnings) | the services of the institutes; Archiwista shows archives and series from the store |
| Deleting versions from a store | Kartograf; Archiwista reports candidates only |

## Run

Requirements: Linux (checked on Debian 13), Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). Archiwista 0.2 needs Kartograf 0.8.0 with its public read API of the store (KA-1 to KA-6); `pyproject.toml` pins the commit that has it until the tag `v0.8.0` exists, and `uv.lock` pins every package with its SHA-256 sum.

```bash
uv sync --locked                      # the environment in .venv, from uv.lock
uv run playwright install chromium    # once; only the interface tests need it
uv run archiwista doctor              # checks the installation
uv run archiwista serve               # starts the server and opens the browser
```

`archiwista doctor` checks the settings file, the Kartograf plugin (version and the schemas `kartograf-meta/1`, `kartograf-project/1` and `kartograf-store/1`), every store and project directory, the local data directory (write access, access of other accounts) and the free port. Every problem has a line telling how to fix it, for example the command that installs a missing package.

The server listens on `127.0.0.1` only (port 8090, the setting `port`; `--port N` changes it for one run, `--port 0` picks a free one). It prints a one-time address `http://127.0.0.1:8090/#token=…` (valid for 10 minutes, works once) and opens it in the browser; `--no-browser` only prints it. On the first run a wizard asks for the Kartograf store root (the directory that holds `kartograf-store.json` and the product directories, usually called `data/`), optionally the project directories and the offline mode; after saving, the server indexes the store in the background and a bar above the views shows the progress. `Ctrl+C` stops the server. A browser session ends after 24 hours without use and with the server; `archiwista token` issues a new address. The views are described in [USAGE.md](https://github.com/Daldek/Archiwista/blob/main/docs/USAGE.md).

The first start after an update from 0.1 rebuilds the local index (`SCHEMA_VERSION = 6`) and runs a full scan: with a disconnected store, wait with the update or connect the store before the scan.

## Deploy

Archiwista 0.2 is for one person on one computer: the server listens on `127.0.0.1` only and every `/api` request needs the session that the one-time address starts. A server for a team on a local network (sign-in, roles, project sharing) is planned for v0.4 (A-ADR-013); Windows comes with v1.0. The server is a foreground process (`archiwista serve`); the previews of files are rendered by isolated processes, not by the server.

Archiwista writes nothing in a Kartograf store. The local index and the preview cache live in the user's account; the one other write, on the command of a person with `project.write`, is a snapshot in the data folder of a project (`<project directory>/dane/.wersje/` by default). The data folder is indexed read-only. `archiwista doctor` prints the local paths below.

| What | Where | Rebuildable |
|---|---|---|
| settings `config.toml` | `~/.config/archiwista/` | the wizard or the "Ustawienia" (Settings) view |
| index `index.sqlite` | `~/.local/share/archiwista/` | yes: `archiwista reindex` |
| state database `state.sqlite`: accounts, groups, project sharing, the permission log | `~/.local/share/archiwista/` | **no**: back up with `archiwista state export`, restore with `state import` |
| `cache/`: unit boundaries (TERYT, KU) fetched by the plugin | `~/.local/share/archiwista/` | yes, from the network |
| `jobs/`: logs of background jobs (90 days, 1 GB at most) | `~/.local/share/archiwista/` | not needed for work |
| `areas/`: copies of the area files that were loaded | `~/.local/share/archiwista/` | load the file again |
| `previews/`: thumbnails, tiles, local COGs and the LRU account `cache.sqlite` | `~/.local/share/archiwista/` | yes, a content-addressed cache, 20 GB by default |
| `<data folder>/.wersje/`: consistent snapshots with `migawka.json` | the project directory the user chose | **no**: copy with the project |

The local data directory has mode `0700` and the `archiwista` commands run with `umask 077`: other accounts of the computer cannot read the index or the state database.

## Capabilities

| Task | CLI (`--json`) | HTTP (`/api/v1`) |
|---|---|---|
| State of the server, sources, index and stores | `archiwista status` | `GET /health` |
| Producer plugins and their state | `archiwista sources` | `GET /sources` |
| Search the catalog | `archiwista search [QUERY] [options]` | `GET /slots` |
| Card of a file and of one version | `archiwista entry STORE SLOT`, `archiwista version STORE VERSION` | `GET /stores/{store}/slots/{slot}`, `GET /stores/{store}/versions/{version}` |
| Projects | `archiwista projects`, `archiwista project PROJECT` | `GET /projects`, `GET /projects/{project}` |
| Preview of a file or a version, optionally as PNG | `archiwista preview REF [--build] [--output FILE.png]` | `GET` and `POST …/preview`, `GET …/preview.png` |
| Compare the metadata of two objects | `archiwista compare REF REF` | `GET /compare?a=REF&b=REF` |
| Years and campaigns of a local layer | `archiwista layers --store ID --product NAME [--area-id ID]` | `GET /local-layers` |
| Own data of a project: files, scan, snapshots | `archiwista files`, `file`, `own-scan`, `snapshot PROJECT FILE [--plan \| --note TEXT]` | `GET /projects/{project}/files`, `POST /projects/{project}/scan`, `POST …/snapshots` |
| Producers' commands: the catalog, a pasted line read into a call, a check without the network, the line of a call | `archiwista commands list`, `parse PRODUCER LINE`, `validate PRODUCER COMMAND`, `format PRODUCER COMMAND` | `GET /commands`, `POST /commands/parse`, `/commands/validate`, `/commands/format` |
| What the source has for a kept area and a product: the last report, a check at the source | `archiwista availability show AREA --product PRODUCT`, `availability check AREA --product PRODUCT [--force]` | `GET /availability`, `POST /availability` (a report younger than seven days, else a background job) |
| Rebuild the index | `archiwista reindex [--store STORE]` (a full scan in the foreground) | `POST /stores/{store}/scan` (a background job) |
| One-time session address, for example for an agent | `archiwista token [--json \| --revoke-all]` | `POST /session/tokens` |
| Accounts, groups, project sharing, state backup | `archiwista users`, `groups`, `share`, `state export` and `state import` | none |

The read commands work without a running server: they use the local index and the services that the HTTP routes use. Building a preview, scanning own data, making a snapshot and checking the availability at the source run as jobs in worker processes, in the foreground in the CLI and in the background in the server. The log goes to standard error, never to standard output; `--verbose` (debug) or `--quiet` (errors only), before or after the command name, sets its level, and without them the variable `ARCHIWISTA_LOG_LEVEL` (`debug`, `info`, `warning`, `error`; default `warning`) does.

## For AI agents

The guide for scripts and agents is [AGENT_API.md](https://github.com/Daldek/Archiwista/blob/main/docs/AGENT_API.md): the HTTP session, filters, paging, background jobs and errors. The full schema is `/api/v1/openapi.json` of a running server (it needs a session) and the interactive documentation is `/api/docs`. With `--json` a command prints only JSON of the schema of the API answer on standard output. There is no MCP server.

Archiwista never writes to a store; its only writes outside its own index and cache are snapshots, which need `project.write`, and `archiwista snapshot PROJECT FILE --plan` shows what one would do without writing. Always pass `--json`, and decide on `code` and `details.reason` of an error, never on its text.

## Related tools

| Tool | Relation |
|---|---|
| [Kartograf](https://github.com/Daldek/Kartograf) | writes the stores that Archiwista reads; the only importer of it is the adapter in `src/archiwista/adapter/kartograf/` |
| [IMGWTools](https://github.com/Daldek/IMGWTools) | writes the IMGW measurement archives; an optional plugin (`archiwista[imgw]`) planned for v0.5 |
| [Nogat](https://github.com/Daldek/Nogat) | the ecosystem: the standard 2.1 that this repository follows and the error registry |
| QGIS | analysis and editing of the files that Archiwista shows; the QGIS plugin is in the Kartograf repository |

## Errors and exit codes

Errors use the shared [Nogat error registry](https://github.com/Daldek/Nogat/blob/main/standards/ERROR_REGISTRY.md): an HTTP problem (`application/problem+json`) or, on the command line, nothing on standard output and the document `archiwista-error/1` as the last line of standard error. The most common codes:

| Code | Exit | Meaning and what to do |
|---|---|---|
| `validation_error` | 2 | invalid input: see `errors`; a wrong use of the command line is the same |
| `not_found` | 3 | an unknown store, slot or project, or a project you may not see |
| `conflict` | 4 | a job that writes this index already runs: follow it instead of retrying |
| `missing_dependency` | 6 | a producer plugin is missing or has an unsupported version: run the command in `hint` |
| `store_unavailable` | 8 | the store cannot be read (an unmounted share): connect it, then `archiwista reindex`; or the producer refuses the directory (for Kartograf: no `kartograf-store.json`, `reason` `no_marker`): run the command in `hint` once |
| `forbidden` | 12 | the session or the role does not allow it |

A job that does not succeed exits `11` (failed) or `130` (cancelled or interrupted), and `archiwista doctor` exits `10` or `11` when checks fail: these are outcomes, not errors, and print no error document. The texts of errors are English, and Polish for the request header `Accept-Language: pl`; the command line prints its text for people in Polish.

## Data and licensing

Archiwista holds no data of its own: it shows what the producers wrote, with the metadata of each file's sidecar (`kartograf-meta/1`, `imgw-meta/1`), which carries the licence of the data, and the project manifests (`kartograf-project/1`). The data sources and their terms are those of Kartograf and IMGWTools. The default basemap is OpenFreeMap vector tiles (OpenStreetMap data), with the attribution shown on the map; in offline mode the jobs that need the network are refused. The code is under the MIT licence.

## Documentation

| Document | Content |
|---|---|
| [CHANGELOG.md](https://github.com/Daldek/Archiwista/blob/main/docs/CHANGELOG.md) | changes by release |
| [USAGE.md](https://github.com/Daldek/Archiwista/blob/main/docs/USAGE.md) | the views of v0.2: previews, Fan, Timeline, comparison, projects and snapshots |
| [AGENT_API.md](https://github.com/Daldek/Archiwista/blob/main/docs/AGENT_API.md) | the HTTP API and the CLI with `--json` for scripts and AI agents |
| [PRD.md](https://github.com/Daldek/Archiwista/blob/main/docs/PRD.md) | product requirements: problem, users, requirements, success measures, open decisions |
| [SCOPE.md](https://github.com/Daldek/Archiwista/blob/main/docs/SCOPE.md) | scope: the MVP, what is out of it, stages with gates, dependencies on the producers, risks |
| [SPEC.md](https://github.com/Daldek/Archiwista/blob/main/docs/SPEC.md) | the detailed specification: use cases, data model and index, architecture, interface, API, security, requirements for the producers, roadmap with acceptance criteria |
| [ARCHITECTURE.md](https://github.com/Daldek/Archiwista/blob/main/docs/ARCHITECTURE.md) | the architecture of the code; the format of the store is in Kartograf's `docs/ARCHITECTURE.md` |
| [DECISIONS.md](https://github.com/Daldek/Archiwista/blob/main/docs/DECISIONS.md) | decisions (ADR) |
| [docs/plans/](https://github.com/Daldek/Archiwista/tree/main/docs/plans) | the executed plans of v0.1 and v0.2: contracts between steps, steps with acceptance, the gate |
| [docs/reports/](https://github.com/Daldek/Archiwista/tree/main/docs/reports) | measurements and acceptance of v0.1 and v0.2 |
| [PROGRESS.md](https://github.com/Daldek/Archiwista/blob/main/docs/PROGRESS.md) | the current state and open matters |
| [mockup/](https://github.com/Daldek/Archiwista/tree/main/mockup) | a clickable mockup of the interface (`mockup/README.md` tells how to run it) |

Archiwista replaces subproject 5 of the Kartograf roadmap ("web GUI"); the QGIS plugin (subproject 4) stays in the Kartograf repository.

## Development

Read [CLAUDE.md](https://github.com/Daldek/Archiwista/blob/main/CLAUDE.md) first, then [CONTRIBUTING.md](https://github.com/Daldek/Archiwista/blob/main/CONTRIBUTING.md) (it also holds the contributor licence agreement). The gate runs ruff, mypy, pytest with coverage and the commit check; contributors run it as `GATE_CHECK_AUTHOR=0 scripts/gate.sh`:

```bash
scripts/gate.sh    # ruff format, ruff check, mypy, pytest with coverage, the commit check
```

The gate (DEV-7.6) runs from a git working directory and applies `uv sync --locked --all-extras`. By default `pytest` leaves out the tests marked `live`, `perf` and `smb` (real stores, the store of 50,000 slots, an SMB 3 share), runs the interface tests in Chromium and requires 80% coverage. The measurements and their method are in the reports of [v0.1](https://github.com/Daldek/Archiwista/blob/main/docs/reports/v0.1-measurements.md) and [v0.2](https://github.com/Daldek/Archiwista/blob/main/docs/reports/v0.2-measurements.md).

## Status, licence, author

Release **0.2.0 "Previews"** (2026-10-20): the local index, the map and the catalog of a Kartograf store, file previews, the Fan and the Timeline, comparison with the curtain, and own data of a project with snapshots; the store stays read-only. `develop` carries `0.3.0.dev0`. Next: v0.3 "Actions" (availability at the source, downloads and project actions through the Kartograf API), v0.4 "Team", v0.5 "IMGW stations", v0.6 "PL + CZ"; the MVP is v1.0 ([SCOPE.md](https://github.com/Daldek/Archiwista/blob/main/docs/SCOPE.md)). The API may change until v1.0.

MIT licence: [LICENSE](https://github.com/Daldek/Archiwista/blob/main/LICENSE).

Author: [Piotr de Bever](https://www.linkedin.com/in/piotr-de-bever/).
