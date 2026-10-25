# Architektura Archiwisty

**Wersja opisywana:** kod wydania 0.2.0 „Podglądy” (`pyproject.toml`).
Historia: [`CHANGELOG.md`](CHANGELOG.md), stan:
[`PROGRESS.md`](PROGRESS.md), instrukcje:
[`USAGE.md`](USAGE.md), [`AGENT_API.md`](AGENT_API.md).
Pomiary i odbiór: [`reports/v0.2-measurements.md`](reports/v0.2-measurements.md);
standardy: [`DEVELOPMENT_STANDARDS.md`](DEVELOPMENT_STANDARDS.md).

Każde twierdzenie o zachowaniu systemu opisuje **kod** w tym repozytorium
(`src/`, `tests/`), nie plan ani spec. Wymagania i zakres leżą
w [`PRD.md`](PRD.md), [`SCOPE.md`](SCOPE.md) i [`SPEC.md`](SPEC.md), decyzje
(A-ADR-0xx) w [`DECISIONS.md`](DECISIONS.md), umowy między krokami v0.1
w [`PLAN_v0.1.md`](PLAN_v0.1.md). Gdzie kod odbiega od specu albo planu,
dokument opisuje kod i mówi o tym wprost. Odwołania wskazują moduł i symbol
(do odszukania `grep`), nigdy numer linii.

Nie mylić z `docs/ARCHITECTURE.md` Kartografa: tam leży kontrakt formatu
magazynu (`data/`, sidecar `kartograf-meta/1`, manifest
`kartograf-project/1`), do którego spec odsyła skrótem „ARCH”.

---

## 1. Cel i granice

Archiwista 0.2 działa lokalnie: FastAPI na `127.0.0.1`, interfejs
przeglądarkowy, API i CLI. Katalog magazynu pochodzi z publicznego API
Kartografa i odtwarzalnego lokalnego indeksu SQLite; dane własne pochodzą
z osobno skanowanych folderów projektów. `state.sqlite` zawiera
nieodtwarzalne konta i uprawnienia (A-ADR-029).

**Magazyn producenta tylko do odczytu.** Skan, karta, podgląd, obrysy,
potwierdzenie dowiązania i status projektu nie zapisują w nim niczego.
`tests/integration/test_read_only_store.py` i testy bezpieczeństwa
podglądów pilnują tej granicy. Wyjątek dotyczący projektów:
`owndata/snapshots.py:make_snapshot` zapisuje na polecenie osoby
z `project.write` pełną migawkę pliku w `<folder danych>/.wersje/`
(`archiwista-snapshot/1` w `migawka.json`); nie zmienia manifestu.
Indeks, pamięć podglądów, obszary i zadania pozostają wyłącznie lokalne.

**Producenci przez publiczne API, w adapterach.** Wiedzę o układzie
magazynu ma producent (A-ADR-014). Archiwista nie przechodzi drzewa `data/`
sam, tylko woła nazwy z `kartograf.__all__` — `list_segments`,
`list_partitions`, `iter_store`, `read_sidecar`, `describe_segment`,
`file_footprint`, `link_target`, `pinned_transform`, `open_project`,
`get_project_status`, `countries_for_bbox`, `find_sheets_for_bbox`,
`SheetParser` — i to wyłącznie w `src/archiwista/adapter/kartograf/`
(sekcja 2.2). Reszta aplikacji zna tylko interfejs źródła
`src/archiwista/sources/`. Brakująca funkcja Kartografa to wymaganie wobec
Kartografa (SPEC 12), nie obejście w Archiwiście. Pakiet wymaga
`kartograf>=0.8.0,<0.9` z KA-1..KA-6.

**Granice wydania:** Archiwista nie pobiera danych ani nie wykonuje
poleceń producenta (v0.3), nie zapisuje i nie usuwa plików magazynu,
nie usuwa migawek. `JOB_KINDS` obejmuje teraz `scan`, `footprints`,
`link_check`, `preview`, `own_scan`, `snapshot`. Zadanie `footprints`
korzysta z sieci tylko po wyłączeniu trybu offline. Dane bez obrysu
pozostają w katalogu z powodem, a interfejs nie ładuje bibliotek z CDN.

---

## 2. Mapa modułów

### 2.1 Moduły

Tabele zawierają główne moduły pakietu `src/archiwista/` i ich symbole,
nie są już wyczerpującą listą plików pomocniczych. Metody `IndexWriter`,
`IndexQueries` i `JobSupervisor` opisują sekcje 4–5.

**Wejścia: CLI, serwer, aplikacja**

| Moduł | Rola | Kluczowe symbole |
|---|---|---|
| `cli.py` | komenda `archiwista` (`[project.scripts]`); na POSIX `umask 077`; rozdziela podpolecenia | `main` |
| `server.py` | `archiwista serve` (tylko `127.0.0.1`: gniazdo, token startowy, Uvicorn, nadzorca i harmonogram zadań) oraz `archiwista token` | `serve_main`, `token_main`, `LocalServer`, `LaunchFile`, `bind_loopback`, `open_in_browser`, `uvicorn_log_config`, `LIMIT_CONCURRENCY` |
| `app.py` | fabryka aplikacji FastAPI: obiekty współdzielone w `app.state`, routery pod `/api/v1`, dokumentacja API, pliki interfejsu, `SecurityMiddleware` | `create_app`, `WEB_DIR` |
| `reader.py` | polecenia odczytu `status`, `sources`, `search`, `entry`, `version`, `projects`, `project` na funkcjach i modelach API | `add_read_commands`, `read_main`, `search_filters`, `READ_COMMANDS` |
| `admin.py` | polecenia `users`, `groups`, `share`, `state export` i `state import`, wykonywane jako `LOCAL_OWNER` | `add_admin_commands`, `admin_main`, `ADMIN_COMMANDS` |
| `doctor.py` | `archiwista doctor`: diagnostyka bez zapisu — ustawienia, wtyczki, magazyny i katalogi projektów, katalog danych, port | `run_doctor`, `doctor_main`, `DoctorCheck`, `DoctorReport`, `source_check`, `is_port_available`, `REQUIRED_PRODUCERS` |
| `commands/previews.py`, `commands/layers.py`, `commands/compare.py`, `commands/owndata.py` | CLI v0.2 wspólne z usługami API: `preview`, `layers`, `compare`, `files`, `file`, `snapshot`, `own-scan` | `add_commands`, `main` w każdym module |

**HTTP i bezpieczeństwo**

| Moduł | Rola | Kluczowe symbole |
|---|---|---|
| `security.py` | reguły trybu lokalnego dla każdego żądania, tokeny jednorazowe, sesje w pamięci, CSP, redakcja tokenów w dziennikach | `SecurityMiddleware`, `SessionStore`, `Session`, `issue_one_time_token`, `redeem_one_time_token`, `revoke_agent_sessions`, `session_principals`, `require_session`, `current_principal`, `csp_header`, `fragment_url`, `TokenRedactionFilter` |
| `api/__init__.py` | stałe ścieżek | `API_PREFIX` (`/api/v1`), `DOCS_PATH` (`/api/docs`) |
| `api/dependencies.py` | zależności tras z `app.state` | `authorizer`, `index_queries`, `settings_service`, `plugin_registry`, `visible_projects` |
| `api/errors.py` | problemy RFC 9457; jedna tabela: błąd usługi → status i kod, wspólna z CLI | `ApiError`, `PROBLEMS`, `problem_response`, `problem_of`, `service_problem`, `validation_problem`, `install_error_handlers` |
| `api/models.py` | modele Pydantic żądań i odpowiedzi (poza modelami sesji i administracji, które leżą przy swoich routerach) — zarazem schemat OpenAPI | `CatalogFilters`, `MapFilters`, `IndexAnswer`, `CatalogPage`, `SlotCard`, `VersionCard`, `MapView`, `Health`, `StoreDetail`, `ProjectCard`, `JobDetail`, `Area`, `AreaCoverage`, `Settings`, `ProblemDetails` |
| `api/docs.py` | OpenAPI (`operationId` = nazwa funkcji trasy) i lokalny Swagger UI z `api/swagger/` | `install_docs`, `operation_id`, `openapi_document` |
| `api/session.py` | `/session`: wymiana tokenu, stan sesji, wylogowanie, tokeny agentów | `exchange_token`, `read_session`, `end_session`, `issue_token`, modele `SessionExchange`, `NewSession`, `SessionState`, `OneTimeToken` |
| `api/health.py` | `/health`, `/sources` | `read_health`, `source_infos` |
| `api/stores.py` | `/stores`, `/stores/{store}` | `read_stores`, `read_store` |
| `api/slots.py` | katalog i karty: `/slots`, `/products`, `/stores/{store}/slots/{slot}`, `/stores/{store}/versions/{version}` (z `/sidecar`), `/requests/{parent_request}` | `search_slots`, `read_products`, `slot_card`, `version_card`, `copy_path`, `geo_adapter`, `checked_store` |
| `api/map.py` | `/map/footprints`, `/map/sheets` | `map_view`, `sheet_list` |
| `api/projects.py` | `/projects`, `/projects/{project}`, `/projects/{project}/status` | `read_projects`, `project_card`, `check_project` |
| `api/settings.py` | `GET` i `PUT /settings` | `save_settings`, `settings_writer` |
| `api/areas.py` | `POST /areas`, `/areas/{area_id}`, `/local-coverage` | `save_area`, `save_area_file`, `read_area`, `read_local_coverage`, `REFRESH_TIMEOUT_S` |
| `api/jobs.py` | zadania w tle przez HTTP i strumień SSE | `start_scan`, `start_footprints`, `start_link_check`, `list_jobs`, `get_job`, `get_job_events`, `job_event_stream`, `sse_message`, `JobStreams`, `EventStreamResponse` |
| `api/admin.py` | `/users`, `/groups`, `/projects/{project}/access` | modele `User`, `Group`, `ProjectAccess`, `AccessChange` i trasy o nazwach funkcji `services/access.py` |
| `api/previews.py`, `api/models_previews.py` | opis, budowa, PNG, kafle, obiekty i człony ZIP wersji magazynu | `get_preview`, `build_preview`, `PreviewInfo` |
| `api/owndata.py`, `api/models_owndata.py` | pliki projektu, folder, migawki, skan, podglądy własnych plików | `read_own_files`, `snapshot_plan`, `start_snapshot`, `start_own_scan`, `OwnFilesQuery` |
| `api/layers.py`, `api/models_layers.py` | lokalne lata i kampanie, miniatury i kafle warstw | `get_local_layers`, `get_layer_thumbnail`, `get_layer_tile`, `LayersQuery` |
| `api/compare.py`, `api/models_compare.py` | porównanie dwóch `ref` | `get_comparison`, `CompareQuery` |

**Usługi, uprawnienia, stan**

| Moduł | Rola | Kluczowe symbole |
|---|---|---|
| `services/problems.py` | problem z polskim opisem i instrukcją naprawy | `Problem`, `explain`, `KNOWN_PROBLEMS` |
| `services/stores.py` | stan magazynu dla widoku „Magazyn” | `store_summary`, `StoreSummary`, `issue_problem` |
| `services/projects.py` | karta projektu i żywy status producenta | `project_detail`, `ProjectDetail`, `project_problems`, `project_status` |
| `services/access.py` | konta, grupy i dostęp do projektów — dla HTTP i CLI | `list_users`, `add_user`, `update_user`, `remove_user`, `list_groups`, `add_group`, `set_group_members`, `remove_group`, `project_access`, `share_project` |
| `services/owndata.py` | sprawdzanie folderu i problemy plików projektu | `set_data_dir`, `folder_check`, `folder_problems`, `file_problems` |
| `services/layers.py` | warstwy lokalne produktu i warstwy pliku własnego | `read_local_layers`, `read_own_file_layers`, `LayerMemo` |
| `services/compare.py` | porównanie metadanych i schematu, nie danych obiektowych | `compare` |
| `auth/principal.py` | kto działa | `Principal`, `PrincipalKind`, `LOCAL_OWNER`, `SCHEDULER`, `LOCAL_PRINCIPAL_ID`, `LOCAL_ROLES` |
| `auth/authorize.py` | jedyne miejsce decyzji o uprawnieniach | `Authorizer`, `ACTIONS`, `principal_for`, `session_principal` |
| `auth/visibility.py` | które projekty widać | `ProjectVisibility`, `ALL_PROJECTS`, `access_key` |
| `state/schema.py` | schemat i migracje `state.sqlite` | `initialize`, `MIGRATIONS`, `STATE_SCHEMA_VERSION` |
| `state/store.py` | odczyt i zmiany bazy stanu razem z dziennikiem uprawnień | `StateStore`, `UserRecord`, `GroupRecord`, `ProjectAccessRecord`, `PermissionChange`, `StateSnapshot` |
| `state/export.py` | kopia bazy stanu `archiwista-state/1` | `export_state`, `import_state`, `dump_state`, `parse_state`, `StateDocument`, `STATE_DOCUMENT_SCHEMA` |

**Indeks**

| Moduł | Rola | Kluczowe symbole |
|---|---|---|
| `index/schema.py` | schemat SQLite, ustawienia połączeń, przebudowa przy zmianie wersji | `SCHEMA_VERSION`, `initialize`, `connect`, `IndexUnsupportedError`, `MIN_SQLITE_VERSION` |
| `index/writer.py` | zapis indeksu z typów interfejsu źródła (nigdy z obiektów Kartografa) | `IndexWriter` |
| `index/queries.py` | katalog, mapa, produkty, dane własne i migawki, projekty, stan | `IndexQueries` |
| `index/scanner.py` | skan magazynu i odświeżenie widoku | `scan_store`, `refresh_view`, `ScanProgress`, `ScanNotice`, `ScanSummary`, `SegmentScan`, `BATCH_ENTRIES`, `BATCH_SECONDS`, `FOOTPRINT_THREADS`, `REFRESH_VIEW_MAX_UNITS` |
| `index/projects.py` | odkrywanie i indeksowanie manifestów projektów | `scan_projects`, `ProjectScanSummary`, `PROJECT_MANIFESTS`, `MAX_PROJECT_DEPTH` |
| `index/coverage.py` | pokrycie lokalne w układzie płaskim | `measure_coverage`, `planar_crs`, `PLANAR_CRS`, `CoverageShape`, `CoverageMeasure` |
| `index/geometry.py` | pomocnicze funkcje GeoJSON w WGS84 | `polygon_bounds`, `is_box`, `box_geometry`, `require_wgs84_area`, `require_wgs84_bbox` |
| `index/types.py` | typy zapytań i odpowiedzi indeksu, limity | `SlotQuery`, `MapQuery`, `SlotPage`, `SlotDetail`, `VersionDetail`, `FootprintPage`, `IndexStatus`, `StoreIndexState`, `StoreFreshness`, `AreaRecord`, `SlotUnit`, `ScanPass`, `BatchResult`, `PassSummary`, `DEFAULT_PAGE_LIMIT`, `MAX_PAGE_LIMIT`, `MAP_FOOTPRINT_LIMIT`, `MAX_GRID_COLUMNS` |

**Zadania w tle**

| Moduł | Rola | Kluczowe symbole |
|---|---|---|
| `jobs/supervisor.py` | nadzorca: kolejka, procesy robocze, zdarzenia, odzyskiwanie po awarii, przycinanie historii | `JobSupervisor`, `JobRecord`, `JobEvent`, `JobError`, `JobPage`, `ScanHistory`, `INDEX_JOB_KINDS`, `NETWORK_JOB_KINDS`, `MAX_NETWORK_JOBS`, `STOP_TIMEOUT_S`, `WORKER_COMMAND`, `default_max_jobs` |
| `jobs/worker.py` | proces roboczy zadania: skan, obrysy, link, podgląd, skan własny, migawka | `main`, `RUNNERS`, `run_scan`, `run_footprints`, `run_link_check`, `run_own_scan`, `run_snapshot`, `Emitter` |
| `jobs/protocol.py` | protokół JSON Lines nadzorca ↔ proces roboczy | `JobSpec`, `WorkerMessage`, `encode_spec`, `decode_spec`, `encode_message`, `decode_message`, `PROTOCOL_VERSION`, `JOB_KINDS`, `INTERRUPTED_EXIT`, `CODE_WORKER_CRASHED` |
| `jobs/scheduler.py` | skany okresowe magazynu i danych własnych | `ScanScheduler`, `plan_scans`, `plan_own_scan`, `PlannedScan` |
| `jobs/reindex.py` | `archiwista reindex`: pełny skan na pierwszym planie | `reindex_main` |
| `jobs/availability.py` | czy magazyn da się czytać teraz (pusty punkt montowania znanego magazynu = niedostępny) | `unreachable_detail` |
| `jobs/foreground.py` | śledzenie zadań CLI na pierwszym planie | `run_foreground` |

**Obszary**

| Moduł | Rola | Kluczowe symbole |
|---|---|---|
| `areas.py` | obszary: walidacja, pomiar, kopie plików, uruchamianie czytnika | `AreaFiles`, `area_from_geometry`, `read_area_file`, `area_from_file`, `keep_copy`, `discard_copy`, `prune_area_copies`, `area_id`, `area_crs`, `check_body_size`, `AREA_BODY_LIMIT_BYTES`, `AREA_READ_TIMEOUT_S`, `AREA_COPY_MAX_AGE`, `AREA_READER_COMMAND` |
| `area_reader.py` | proces czytający niezaufany plik obszaru (GDAL przez `pyogrio`) | `main`, `read_area`, `AreaFileError`, `MAX_VERTICES`, `MAX_MEMBERS`, `UNPACKED_LIMIT_BYTES` |

**Podglądy i dane własne**

| Moduł | Rola | Kluczowe symbole |
|---|---|---|
| `refs.py` | odwołania `version:`, `file:`, `snapshot:` i kontrola widoczności przed odczytem | `ObjectResolver`, `parse_ref`, `format_ref` |
| `sandbox.py`, `formats.py` | izolacja procesów oraz jawne sterowniki odczytu plików | `untrusted_env`, `file_format`, `open_raster` |
| `previews/service.py`, `previews/cache.py` | podgląd po `ref`, cache po treści i LRU z lokalnym `cache.sqlite` | `PreviewService`, `PreviewCache`, `cache_key`, `RENDERER_VERSIONS` |
| `previews/pool.py`, `previews/worker.py` | kolejka i procesy renderujące (czas, pamięć, odpowiedzi bez ścieżek) | `RenderPool`, `default_render_workers`, `answer_line` |
| `previews/build.py`, `previews/compose.py`, `previews/tiles.py` | budowa lokalnego COG, miniatury/kafle warstw, wymuszona operacja kartograficzna | `run_preview`, `layer_tile`, `layer_thumbnail`, `warp` |
| `owndata/scan.py`, `owndata/reader.py` | skan folderu, ograniczony proces odczytu plików | `scan_own_data`, `OwnReader`, `check_own_folder` |
| `owndata/content.py`, `owndata/snapshots.py`, `owndata/document.py` | treść logiczna GeoPackage, spójna kopia, atomowa migawka i otwarty manifest | `consistent_sqlite_read`, `check_snapshot`, `make_snapshot`, `SnapshotDocument` |

**Źródła i adaptery**

| Moduł | Rola | Kluczowe symbole |
|---|---|---|
| `sources/protocol.py` | protokoły adaptera (`runtime_checkable`): wymagany i zdolności opcjonalne | `SourceAdapter`, `SourceFactory`, `SegmentDescriptionAdapter`, `SegmentedAdapter`, `CurrentVersionAdapter`, `PartitionedAdapter`, `GeoAdapter`, `LinkCheckAdapter`, `SheetGridAdapter`, `CoordinateTransformer` |
| `sources/types.py` | wspólne typy niezależne od producenta | `SourceContext`, `ScanScope`, `SourcePartition`, `SourceState`, `SourceSegment`, `SourceEntry`, `SourceObservation`, `EntryMeta`, `Footprint`, `ProjectInfo`, `ProjectTask`, `ProjectPin`, `SheetGrid`, `SourceStatus` |
| `sources/registry.py` | wtyczki z entry points grupy `archiwista.sources`, ich stany i adaptery | `SourceRegistry`, `PluginRegistry`, `load_registry`, `check_package`, `install_requirement`, `source_fix`, `source_error`, `ENTRY_POINT_GROUP`, `APP_DISTRIBUTION` |
| `adapter/kartograf/__init__.py` | fabryka wtyczki: porównuje zainstalowanego Kartografa z przypięciem Archiwisty przed importem | `load`, `PRODUCER`, `PACKAGE`, `SCHEMAS` |
| `adapter/kartograf/adapter.py` | adapter Kartografa ze wszystkimi zdolnościami opcjonalnymi | `KartografAdapter`, `UNIT_CACHE_FILE` |
| `adapter/kartograf/unit_cache.py` | lokalna pamięć obrysów jednostek (TERYT, KU, SM5) dla `file_footprint` | `UnitBBoxCache` |
| `sources/markers.py` | nazwy plików znaczników magazynów producentów (DEV-19.12): adapter odmawia obcego magazynu po samej nazwie pliku, bez importu innego producenta | `STORE_MARKERS`, `foreign_markers` |
| `adapter/imgw/__init__.py` | fabryka wtyczki IMGW: porównuje zainstalowany IMGWTools z zakresem `SUPPORTED_VERSIONS` przed importem (ADR 0032) | `load`, `PRODUCER`, `PACKAGE`, `SUPPORTED_VERSIONS`, `SCHEMAS` |
| `adapter/imgw/adapter.py` | adapter IMGWTools dla IMGW-PIB i ČHMÚ: wpisy z `iter_store` (wersje z `ScanScope.known_versions` wracają jako `skipped`, bez czytania sidecara: `skip_versions`) z kluczem slotu producenta, nazwą slotu dla ludzi i rekordem obserwacji, opis zbioru z rejestru IMGWTools (nazwa po polsku, kraj dostawcy i rodzina zbioru jako produkt; `SegmentDescriptionAdapter`), wersja bieżąca slotu od IMGWTools (`current_version`: `CurrentVersionAdapter`; slot z uszkodzoną wersją jej nie ma), werdykty `probe` po znaczniku i kodach `StoreInfo.problem_codes`, metadane, kraj pliku, projekty; nie importuje `pyarrow` | `ImgwAdapter` |

**Wspólne**

| Moduł | Rola | Kluczowe symbole |
|---|---|---|
| `config.py` | ścieżki lokalne, ustawienia TOML, walidacja, zapis atomowy, powiadamianie o zmianach | `AppPaths`, `AppSettings`, `StoreConfig`, `BasemapConfig`, `ConfigStore`, `SettingsService`, `parse_settings`, `validate_settings`, `detect_store_kind`, `write_text_atomic`, `DEFAULT_BASEMAPS` |
| `config.py` (`AppSettings`) | opcje v0.2 | `preview_cache_limit_gb`, `own_data_dirs`, `DEFAULT_BASEMAPS` (OpenFreeMap vector, GUGiK OSM raster) |
| `paths.py` | prywatne katalogi i ścieżki z indeksu wewnątrz korzenia | `private_directory`, `indexed_path`, `resolve_indexed_path`, `PRIVATE_DIRECTORY_MODE` |
| `errors.py` | wyjątki aplikacji | `ArchiwistaError`, `SourceUnavailableError`, `SourceIncompatibleError`, `ProducerError`, `PathOutsideRootError`, `IndexQueryError`, `PermissionDeniedError`, `NotFoundError`, `ConflictError`, `JobConflictError`, `OfflineModeError`, `AreaTooLargeError`, `AreaUnreadableError`, `AreaTooComplexError`, `StateError`, `SnapshotError` |
| `messages.py` | wszystkie polskie teksty serwera i CLI | `MESSAGES`, `with_detail` |

### 2.2 Kierunek zależności

```mermaid
flowchart LR
  subgraph PRZ["Przeglądarka"]
    UI["web/src: Preact + htm, MapLibre GL<br/>api.js: fetch + X-Archiwista-CSRF"]
  end
  CLI["CLI archiwista<br/>reader.py, commands/, admin.py, jobs/reindex.py"]
  subgraph SRV["Proces serwera: archiwista serve, 127.0.0.1"]
    MW["SecurityMiddleware"]
    API["api/: routery /api/v1, SSE"]
    SVC["services/ i funkcje bez HTTP z api/"]
    AUTH["auth/: Authorizer"]
    Q["index/: IndexQueries"]
    SUP["jobs/: JobSupervisor, ScanScheduler"]
    AF["areas.py: AreaFiles"]
    REG["sources/: SourceRegistry"]
    POOL["previews/: RenderPool, PreviewService"]
  end
  W["proces zadania<br/>python -P -m archiwista.jobs.worker<br/>scan, own_scan, preview, snapshot"]
  R["procesy odczytu<br/>area_reader, owndata.reader, previews.worker"]
  ADP["adapter/kartograf/: KartografAdapter"]
  KG["Kartograf: kartograf.__all__"]
  IDX[("index.sqlite")]
  ST[("state.sqlite")]
  MAG[("magazyn tylko do odczytu")]
  OWN[("folder danych projektu: odczyt<br/>migawki .wersje/ na polecenie")]
  CACHE[("previews/cache.sqlite, objects/<br/>lokalny work/")]
  UI --> MW --> API
  MW -. "session_principals" .-> AUTH
  API --> SVC --> Q --> IDX
  API --> AUTH --> ST
  API --> SUP
  API --> AF --> R
  API --> REG
  API --> POOL --> R
  POOL --> CACHE
  SUP -- "JobSpec, JSON Lines" --> W
  SUP --> IDX
  W --> IDX
  W --> REG
  W --> OWN
  R --> OWN
  R --> MAG
  REG -- "entry point archiwista.sources" --> ADP --> KG --> MAG
  CLI --> SVC
  CLI --> AUTH
  CLI --> SUP
```

Diagram opisuje przepływ danych, nie każdą krawędź importu. `api/`
używa `services/`, `refs.py:ObjectResolver` i `index/` oraz kontroluje
widoczność przed podglądem (`PreviewService`). `previews/pool.py` kieruje
żądania do procesów `previews.worker`; `jobs/worker.py` uruchamia skan,
budowę podglądu, skan folderu własnego i migawkę przez osobne granice
procesów. Odczyt niezaufanych plików korzysta z `sandbox.py:untrusted_env`
i `formats.py:open_raster` / `vector_source`. `owndata.reader` czyta
folder bez zmian, a `owndata.snapshots:make_snapshot` jest jedyną
ścieżką zapisu w katalogu projektu. Producent jest dostępny tylko przez
adapter z publicznym API.

**Reguły pilnowane testami** (`tests/contract/`):

- `kartograf` (i `imgwtools`) importuje wyłącznie jego adapter
  (`src/archiwista/adapter/kartograf/`, `src/archiwista/adapter/imgw/`) —
  `test_imports.py::test_producers_are_imported_only_in_their_adapters`;
- adapter Kartografa importuje tylko `from kartograf import …` z nazwami
  z `kartograf.__all__` —
  `test_imports.py::test_kartograf_adapter_uses_only_public_api`;
- każdy moduł poza `archiwista.adapter` importuje się bez IMGWTools i bez
  ładowania Kartografa, wtyczka Kartografa ma stan `available`, a wtyczka IMGW
  `not_installed` —
  `test_imports.py::test_archiwista_starts_without_imgwtools`;
- producent bez zdolności opcjonalnych spełnia `SourceAdapter`
  (`test_source_protocol.py`); stany wtyczek (`not_installed`,
  `incompatible`, `error`) i druga wtyczka obok Kartografa —
  `test_plugins.py`; kontrakt API Kartografa i magazynu testowego —
  `test_kartograf.py`, `test_store_fixture.py`.

**Reguły przyjęte w kodzie (bez osobnego testu):**

- nikt nie importuje `archiwista.adapter`: adapter dostaje się z rejestru
  wtyczek przez entry point `kartograf = "archiwista.adapter.kartograf:load"`;
- FastAPI i Starlette importują tylko `api/`, `app.py` i `security.py`
  (`server.py`: Uvicorn i `starlette.types`); w `jobs/` pośrednio tylko
  `reindex.py` (przez `api.errors.problem_of`); `index/`, `services/`,
  `auth/`, `state/` i `sources/` ich nie znają;
- `index/` nie importuje `api`, `jobs`, `services`, `security`, `app` ani
  `server`; `services/` nie importuje `api`;
- trasy nie filtrują projektów same: biorą `visible_projects` i przekazują
  je zapytaniom i usługom (`api/dependencies.py`, sekcja 7);
- CLI nie tworzy drugiej implementacji odczytu: `reader.py` używa
  wspólnych zapytań indeksu, usług i modeli API, a podgląd, porównanie,
  warstwy i pliki projektu prowadzi przez te same usługi oraz
  `RenderPool`; wynik `--json` zachowuje kontrakt modeli HTTP.

---

## 3. Procesy i wątki

| Proces | Kto uruchamia | Co robi | Komunikacja |
|---|---|---|---|
| serwer `archiwista serve` | użytkownik | Uvicorn z aplikacją `create_app`, `JobSupervisor`, `ScanScheduler`; odczyt indeksu i krótkie, ograniczone odczyty magazynu | HTTP na `127.0.0.1:<port>` |
| proces roboczy zadania | `JobSupervisor`, jeden na zadanie, we własnej grupie procesów (`python -P -m archiwista.jobs.worker`) | `RUNNERS`: `run_scan`, `run_footprints`, `run_link_check`, `run_own_scan`, `run_snapshot`, `run_preview` | stdin: `JobSpec`; stdout: JSON Lines `WorkerMessage`; stderr: `jobs/<id>.log` |
| pula renderująca | `RenderPool`, domyślnie `min(4, cpu)` długowiecznych procesów `python -P -m archiwista.previews.worker` | GDAL, OGR, laspy i ZIP: próba otwarcia, miniatura, kafel, obiekty, ZIP i składanie warstw; limit czasu i pamięci, ponowny start procesu po błędzie | kolejka ≤ 64, wspólne żądanie liczone raz, pliki w `previews/` |
| czytnik danych własnych | `OwnReader` (`owndata/reader.py`) | jeden plik z folderu naraz, GDAL w izolowanym procesie; GeoPackage czytany spójnie bez zapisu przy źródle | odpowiedź z metadanymi do skanu |
| czytnik obszaru | `read_area_file` (`AREA_READER_COMMAND`: `python -P -m archiwista.area_reader`) | GDAL czyta niezaufany plik obszaru, limit 30 s | linia JSON na stdout |
| polecenia CLI | człowiek, skrypt, agent | `reader.py`, `commands/`, `admin.py`, `reindex`, `token`, `doctor`; dla budowy i migawki własny nadzorca | stdout, stderr; serwer niepotrzebny |
| przeglądarka | `open_in_browser` lub człowiek | interfejs `web/` | `fetch` do `/api/v1`, SSE przez `fetch` |

Flaga `-P` trzyma bieżący katalog (katalog `jobs/`) poza `sys.path`.
Uruchamianie GDAL-a, skanu i pobierania obrysów poza procesem serwera
(A-ADR-007) sprawia, że awaria biblioteki natywnej albo przerwanie
zadania nie kładzie interfejsu.

**Wątki serwera.** Pętla zdarzeń Uvicorna obsługuje trasy `async`
i strumienie SSE (odczyty indeksu przez `asyncio.to_thread`); trasy zwykłe
(`def`) i `run_in_threadpool` działają w puli wątków Starlette. Uvicorn
przyjmuje najwyżej `LIMIT_CONCURRENCY` (100) połączeń naraz, kolejne dostają
`503`. Własne wątki serwera: `archiwista-scheduler` (pętla `ScanScheduler`,
co `TICK_S` = 60 s), `archiwista-probe-<magazyn>` (sonda niedostępnego
magazynu, najwyżej `PROBE_TIMEOUT_S` = 10 s), `archiwista-job-<id>` (czytnik
stdout jednego procesu roboczego w `JobSupervisor`), `threading.Timer`
zabijający przerwany proces po `STOP_TIMEOUT_S` (30 s), zegar usuwający
plik startowy po ważności tokenu i wątek `webbrowser.open`. Słuchacze
`JobSupervisor.subscribe` działają w wątku nadzorcy pod jego blokadą, więc
strumień SSE tylko budzi się przez `loop.call_soon_threadsafe`.

**Wątki procesu roboczego skanu.** Wątek wywołujący `scan_store` jest
jedynym użytkownikiem `IndexWriter`. Pula `archiwista-scan` (`_Readers`)
wykonuje wywołania `iter_entries`, jeden generator na wątek od pierwszego
do ostatniego wpisu, i podaje wpisy porcjami (`_READ_CHUNK` = 256) przez
ograniczoną kolejkę (`_QUEUE_CHUNKS_PER_THREAD` = 2 porcje na wątek), która
trzyma w pamięci tylko wpisy przeczytane, a jeszcze niezapisane. Pula
`archiwista-split` dzieli segmenty na części równolegle, a pula
`archiwista-footprint` (`_Footprints`) liczy obrysy bez sieci. Wątek
`archiwista-supervisor` czeka na koniec stdin: gdy nadzorca znika, proces
przerywa sam siebie. Liczby wątków wybiera `_target`: magazyn na udziale
(`StoreConfig.kind` = `share`) jest czytany w `AppSettings.scan_threads`
wątkach (domyślnie 8), a obrysy liczy `FOOTPRINT_THREADS` (4) wątków;
magazyn lokalny czyta jeden wątek całymi segmentami i jeden wątek liczy
obrysy, bo tam skan ogranicza CPU pod GIL.

**Jeden pisarz.** W obrębie przebiegu indeks pisze tylko wątek wywołujący,
paczkami: `BATCH_ENTRIES` (1000) wpisów albo to, co przyszło w ciągu
`BATCH_SECONDS` (1 s) od pierwszego wpisu paczki — jedna transakcja na
paczkę. Między procesami zapisy szereguje SQLite (WAL, `BEGIN IMMEDIATE`,
`busy_timeout` 10 s; czytelnicy nie czekają), a nadzorca dopuszcza najwyżej
jedno zadanie piszące indeks magazynu (`INDEX_JOB_KINDS`: `scan`,
`footprints`): sprawdza to w tabeli `jobs`, więc także wobec zadań innego
procesu, np. `archiwista reindex` (`JobConflictError` → `409 conflict`).
Oprócz wątku zapisu skanu indeks piszą: nadzorca (`jobs`, `job_events`,
`IndexWriter.sync_stores`), serwer (`refresh_view` i `write_area`
w trasach obszarów, `session_tokens`) oraz pozostałe zadania w procesach
roboczych — `footprints` (`write_footprints`) i `link_check`
(`record_issue`, `clear_issue`).

**Proces serwera nie renderuje danych.** Krótkie odczyty magazynu to
`refresh_view` w `GET /local-coverage`, sonda dostępu i status projektu
bez haszowania; renderowanie przekazuje `RenderPool` do `previews.worker`.
`own_scan` używa `OwnReader`, a migawka (`make_snapshot`) i budowa COG
(`run_preview`) odbywają się w procesach zadań z dodatkowymi ograniczeniami
procesów potomnych. `sandbox.untrusted_env` wyłącza połączenia GDAL i PROJ
z siecią, dane uwierzytelniające i zapis `.aux.xml`; jawne sterowniki
oraz `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` blokują obce pliki obok
źródła. `consistent_sqlite_read` obsługuje trzy stany WAL/journal.

---

## 4. Dane lokalne

Położenie lokalne wyznacza `AppPaths.default()` przez `platformdirs` (Linux:
`~/.config/archiwista/` i `~/.local/share/archiwista/`). Poza nimi
Archiwista zapisuje **wyłącznie** migawki w katalogu projektu na polecenie
osoby z `project.write`; magazyn pozostaje bez zmian.

| Ścieżka (`AppPaths`) | Zawartość | Odtwarzalne | Kto pisze |
|---|---|---|---|
| `config_file` = `config.toml` | `AppSettings`: port, tryb offline, katalogi magazynów i projektów, `own_data_dirs` (wyjątek od `<katalog projektu>/dane/`), `preview_cache_limit_gb` (20), `basemaps` (OpenFreeMap vector i OSM GUGiK domyślnie) oraz uprawnienia | nie (kreator lub Ustawienia) | `SettingsService.update` → `ConfigStore.save` |
| `index_file` = `index.sqlite` (+ `-wal`, `-shm`) | indeks magazynów, projektów, plików własnych, migawek i obszarów, historia zadań, skróty tokenów | tak, schemat 6 przebudowywany ze skanem pełnym | `IndexWriter`, `JobSupervisor`, `security.py` |
| `state_file` = `state.sqlite` | konta, grupy, role, dostęp do projektów, dziennik uprawnień | **nie** — kopia `archiwista state export` | `StateStore` |
| `cache_dir` = `cache/<producent>/` | pamięć wtyczki (`SourceContext.cache_dir`); Kartograf: `unit_bboxes.sqlite` (`UnitBBoxCache`) | tak, z sieci | adapter |
| `jobs_dir` = `jobs/` | `<id>.log` (stderr procesu roboczego), `owner-<pid>.lock` (blokada nadzorcy) | dzienniki niepotrzebne do pracy | `JobSupervisor`, procesy robocze |
| `areas_dir` = `areas/` | `<id>/area.*` (kopia pliku obszaru), `.incoming/<losowa>/` (plik w trakcie czytania) | wczytanie pliku od nowa | `AreaFiles` |
| `open-<losowa>.html` w katalogu danych | strona startowa z adresem tokenu dla przeglądarki (`LaunchFile`, plik `0600`) | — | `serve_main`; znika po użyciu tokenu, po 10 min i przy zatrzymaniu |
| `previews_dir` = `previews/` | `cache.sqlite`, `objects/<klucz>/<renderer>-r<wersja>/`: rozpoznanie, miniatury, kafle, COG, kopie do spójnego odczytu SQLite; lokalne LRU | tak | `PreviewCache`, `RenderPool`, zadanie `preview` |
| `work_dir` = `work/` | prywatne katalogi robocze procesów; sprzątane po zatrzymaniu lub awarii | tak | `sandbox.process_work_dir`, czytniki i renderery |
| `<folder danych>/.wersje/` (poza `AppPaths`) | pełne migawki plików, `migawka.json` z `archiwista-snapshot/1` | **nie** — przenosi się z projektem | `make_snapshot`, tylko na polecenie uprawnionej osoby |

**Prawa dostępu.** `private_directory` zakłada albo zamyka katalog do
`0700` (`PRIVATE_DIRECTORY_MODE`) — katalog danych przy każdym otwarciu
indeksu i bazy stanu, `jobs/` i `areas/`; `cli.main`, proces roboczy
i czytnik obszaru ustawiają `umask 077`. `archiwista doctor` ostrzega, gdy
katalog danych jest otwarty dla innych kont.

**Ustawienia.** `ConfigStore.load` czyta TOML albo zwraca wartości
domyślne; `SettingsService.update` waliduje całość (`validate_settings`:
istnienie i odczyt katalogów, `probe` wtyczki dla nowego albo przeniesionego
katalogu, `check_nesting` — żaden katalog producenta w drugim ani w magazynie
jakiegokolwiek producenta: znacznik `kartograf-store.json` albo
`imgw-store.json` w katalogu nadrzędnym lub do dwóch poziomów niżej, bez
dowiązań, `sources/markers.py`, DEV-19.14), zapisuje
atomowo (`write_text_atomic`: plik tymczasowy, `fsync`, `os.replace`)
i powiadamia słuchaczy (`SettingsService.subscribe`): nadzorca synchronizuje
magazyny indeksu, harmonogram planuje pełny skan nowego magazynu.
Magazyn (`StoreConfig`) ma katalog `kartograf` albo `imgw` albo oba (co
najmniej jeden; brakujący to `None`, którego `dump_settings` nie zapisuje),
a `roots()` podaje obecne katalogi wg producenta. Przeszukanie znaczników
obejmuje tylko nowe albo przeniesione katalogi: niezmieniony nie jest
czytany, więc odłączony udział nie blokuje innych zmian. Skan i
harmonogram pomijają katalog źródła, które nie jest dostępne (`not_installed`,
`incompatible`, `error`; SPEC 5.8), i zostawiają jego wpis w ustawieniach:
`run_scan` zgłasza uwagę `source_skipped`, a `ScanScheduler` nie zleca skanu
magazynu bez żadnego dostępnego źródła.
`StoreConfig.kind` bez wartości wykrywa `detect_store_kind` z
`/proc/self/mountinfo` (`SHARE_FILESYSTEMS`: `cifs`, `smb3`, `smbfs`, `nfs`,
`nfs4`). `StoreConfig.local_path` i `foreign_paths` tłumaczą ścieżki między
komputerami przez `path_aliases` (SPEC 4.6).

### 4.1 Indeks `index.sqlite`

Pamięć podręczna odbudowywana z plików producentów (A-ADR-002),
`index/schema.py`:

- **Wersja schematu** `SCHEMA_VERSION` (6 w wydaniu 0.2.0, 7 od indeksu slotów IMGW)
  w `PRAGMA user_version`. Każde otwarcie (`IndexWriter`, `IndexQueries`,
  `serve`, `reindex`, `token`) woła `initialize`: inna wersja (starsza
  albo nowsza) to przebudowa zamiast migracji — wszystkie obiekty usuwane
  i zakładane od nowa w jednej transakcji (`BEGIN IMMEDIATE`), którą
  czytelnicy innych procesów widzą przed albo po; potem `VACUUM`.
  Przebudowany indeks jest pusty, a wypełnia go najbliższy pełny skan;
  razem z nim znikają historia zadań i niewykorzystane tokeny jednorazowe.
  `IndexUnsupportedError`, gdy SQLite jest starszy niż `MIN_SQLITE_VERSION`
  (3.35.0) albo nie ma FTS5, R*Tree lub funkcji JSON.
- **Tabele:** `index_info` (data założenia, poprzednia wersja, generacja
  sesji agentów), `stores` (klucz = `StoreConfig.id`, stan `unknown` /
  `available` / `unavailable`, `indexed_at`), `segments`, `slots`,
  `versions` z 1:1 `version_sidecars` (surowy sidecar) i `version_shapes`
  (obrysy niebędące prostokątem, obrys natywny), `observations` (historia
  publikacji slotu IMGW: nie wersja i nie liczba), `footprints` (R*Tree
  prostokątów WGS84, tylko wersje z obrysem), `search` (FTS5, wiersz na
  slot, `unicode61 remove_diacritics 2`), `issues` (pochodzenie `scan`
  albo `check`), `projects` (z `access_key`), `project_tasks`, `pins`,
  `areas`, `jobs`, `job_events`, `session_tokens`. Wyzwalacze usuwają
  wiersze `footprints` i `search` razem z wersją i slotem.
- **Klucze publiczne** to identyfikator magazynu z ustawień i ścieżki
  względne slotów i wersji; liczbowe `id` nie wychodzą z indeksu.
- **Połączenia** (`connect`): WAL, `synchronous = NORMAL`,
  `foreign_keys = ON`, `busy_timeout` 10 s, tryb autocommit z jawnymi
  transakcjami. Pisarz: 32 MiB pamięci stron i `mmap` 256 MB, a
  `IndexWriter` dodaje `analysis_limit = 1000`
  i `wal_autocheckpoint = 8192`. Czytelnik (`readonly=True`):
  `query_only`, 4 MiB pamięci stron, bez `mmap` — serwer trzyma jedno
  połączenie na wątek (`IndexQueries`, `threading.local`), a każde
  odwzorowanie liczyłoby te same strony w pamięci procesu.
- **Odbudowa ręczna:** `archiwista reindex [--store ID]` — pełny skan na
  pierwszym planie jako zwykłe zadanie (sekcja 5.1); usunięcie pliku
  indeksu daje pusty indeks wypełniany przez harmonogram.

### 4.2 Baza stanu `state.sqlite`

Osobny plik obok indeksu (`state/schema.py`), którego nie odtworzy żaden
plik na dysku (A-ADR-029): przebudowa indeksu go nie dotyka.

- **Wersja schematu** `STATE_SCHEMA_VERSION` = liczba `MIGRATIONS` (2
  w wydaniu 0.1.0). `initialize` wykonuje brakujące migracje w jednej
  transakcji i sprawdza klucze obce; baza z nowszej Archiwisty (wyższe
  `user_version`) to `StateError`, bez zmian w pliku. WAL,
  `synchronous = FULL`.
- **Tabele:** `users`, `groups`, `memberships`, `roles` (`admin`,
  `store_writer`), `project_acl` (klucz = katalog projektu po `realpath`,
  `owner`, `visibility`), `project_acl_entries` (osoba albo grupa),
  `permission_log` (kto, kiedy, co, stan przed i po w JSON; od wersji 2
  także `actor_kind` i etykieta sesji). Konta nie mają haseł (logowanie od
  v0.4).
- **Kopia:** `archiwista state export [--output PLIK]` zapisuje dokument
  JSON `archiwista-state/1` (`export_state`: jedna spójna migawka,
  `dump_state`); `archiwista state import PLIK` (`parse_state`,
  `import_state`, `StateStore.restore`) przyjmuje tylko pustą bazę —
  odtworzenie z kopii, nie scalanie.

---

## 5. Przepływy

### 5.1 Skan pełny i przyrostowy

```mermaid
sequenceDiagram
  participant T as ScanScheduler, POST scan albo reindex
  participant J as JobSupervisor
  participant W as proces roboczy run_scan
  participant R as pula archiwista-scan
  participant A as KartografAdapter
  participant K as Kartograf
  participant X as IndexWriter w wątku wywołującym
  participant F as pula archiwista-footprint
  T->>J: submit scan, mode, segment, actor
  J->>J: konflikt w tabeli jobs, wiersz queued
  J->>W: JobSpec jako jedna linia JSON na stdin
  W->>A: probe i segments
  A->>K: list_segments
  W->>X: write_segments, begin_pass
  W->>X: known_versions dla segmentu
  W->>A: partitions, tylko udział
  A->>K: list_partitions
  W->>R: ScanScope, najcięższe części najpierw
  R->>A: iter_entries, jeden generator na wątek
  A->>K: iter_store z segment, partition i skip_versions
  R-->>W: porcje wpisów przez ograniczoną kolejkę
  W->>X: write_entries, 1000 wpisów albo 1 s na transakcję
  W->>F: needs_footprint
  F->>A: footprint bez sieci
  F-->>W: obrysy
  W->>X: write_footprints
  W->>A: ponowny probe
  W->>X: finish_pass albo abandon_pass
  W->>X: scan_projects po przejściu całego magazynu
  W-->>J: progress, notice, result jako JSON Lines
  J->>J: job_events, stan succeeded albo failed
```

**Kto zleca.** `ScanScheduler` (wykonawca `SCHEDULER`),
`POST /api/v1/stores/{store}/scan` (`ScanRequest`: `mode`, `segment`;
wykonawca = principal sesji) albo `archiwista reindex` (`LOCAL_OWNER`) —
zawsze przez `JobSupervisor.submit("scan", …)` i proces roboczy.
`run_scan` ładuje rejestr wtyczek w procesie roboczym
(`load_registry(cache_dir=spec.cache_dir)`) i dla każdego dostępnego katalogu
producenta magazynu (`StoreConfig.roots`) woła `scan_store` z trybem,
segmentem i `on_event=emit.scan_event`. Zadanie z `segment` skanuje tylko
właścicieli segmentu: producentów, których opis segmentu ma indeks
(`IndexQueries.segment_producers`, kolumna `segments.producer`), a dla
nazwy, której indeks nie zna — producentów skanujących segmentami
(`SegmentedAdapter`, Kartograf), więc magazyn samego Kartografa działa
jak dawniej. Producent, który czyta tylko cały katalog (IMGWTools:
`iter_store` nie ma zakresu poniżej katalogu, a przebieg na zbiór czytałby
cały magazyn tyle razy, ile jest zbiorów), odmawia: zadanie kończy się
błędem `unsupported` (`job.segment_scan_unsupported`), zanim cokolwiek
zostanie przeskanowane, a segment jest dla niego tylko etykietą.

**Przebieg `scan_store`:**

1. `_reachable_segments`: `probe` korzenia (stan inny niż `available` →
   magazyn niedostępny) i lista segmentów (`SegmentedAdapter.segments` →
   `list_segments`, także nierozpoznanych); opisy segmentów trafiają do
   tabeli `segments` (`describe_segment`). Producent bez listy segmentów, ale
   z opisem (`SegmentDescriptionAdapter`, IMGWTools: segmentem jest zbiór),
   jest czytany w całości (`scan_store` odrzuca dla niego `segment` jako
   `ValueError`, a `run_scan` odmawia wcześniej), a opisy segmentów, które
   wymieniły jego wpisy (`_Totals.segments_seen`), zapisuje koniec przebiegu
   przed `finish_pass`.
2. `IndexWriter.begin_pass(store, producer, segment=…, full=…)` wczytuje raz
   znane wersje, sloty i problemy zakresu. Brak segmentów przy wpisach
   w indeksie to pusty punkt montowania, czyli magazyn niedostępny.
3. `IndexWriter.known_versions(segment)` zwraca mapowanie **katalog wersji
   → nazwy plików** dla katalogów „ustalonych”: każda znana w nich wersja
   jest obecna z przeczytanymi metadanymi i nie leży w nich żaden problem.
   Skan przyrostowy podaje je w `ScanScope.known_versions`, a adapter
   Kartografa przekazuje je `iter_store` jako mapowanie `skip_versions`:
   wymienione pliki wracają jako `skipped` bez metadanych, a ich katalog nie
   jest ponownie listowany (koszt 0 zamiast listingu). Sidecary dowiązań
   (ścieżka standardowa, `full_sheet/`) są czytane zawsze, bo z nich wynika
   bieżąca wersja (`SourceEntry.version_path`); skan nigdy nie woła
   `link_target`. Skan pełny nie podaje mapowania i czyta wszystko.
4. `_scopes` układa wywołania `iter_entries`: na udziale każdy segment
   `PartitionedAdapter` dzieli się na części (`partitions` →
   `list_partitions`), kolejność od najcięższej (waga: znane wersje części,
   także dla skanu pełnego); dysk lokalny czyta całe segmenty jednym
   wątkiem.
5. `_stream` w wątku wywołującym zapisuje paczki (`write_entries`: wpisy,
   dowiązania, problemy, wiersze `search`; niezmieniony wpis nie kosztuje
   zapisu) i przekazuje wersje bez położenia (`BatchResult.needs_footprint`;
   w skanie pełnym także te wciąż bez obrysu) puli obrysów, której wyniki
   zapisuje `write_footprints` — istniejącego obrysu nie nadpisuje. Obrys
   bez sieci korzysta z lokalnej pamięci jednostek adaptera
   (`UnitBBoxCache`); nieudany zostaje w oczekiwaniu na następny skan
   (`ScanNotice` `footprints_failed`). Po ostatniej części segmentu
   wychodzi `ScanProgress` z czasem segmentu (suma części).
6. Po przejściu ponowny `probe` (odmontowany w trakcie udział daje puste
   listingi bez błędu), potem `finish_pass`: przebieg kompletny (bez
   jednostek) oznacza w swoim zakresie niewidziane wersje „brak pliku”
   z datą, przebieg `full` usuwa wersje oznaczone tak już wcześniej i nadal
   nieobecne; oba czyszczą niewidziane dowiązania, rozwiązują problemy
   i usuwają puste sloty, a przebieg całego magazynu usuwa też puste
   segmenty i ustawia `indexed_at` oraz stan `available`. Producent bez
   dowiązań, którego sloty mają własny klucz (`CurrentVersionAdapter`,
   IMGWTools), jest pytany o wersję bieżącą — `current_version(root,
   slot_key)` przed transakcją, raz na slot — slotów, których przebieg
   dotknął (wersja zapisana, wróciła albo zniknęła, problem znaleziony
   albo rozwiązany), i tych bez wersji bieżącej, choć przebieg widział
   ich wersję (przerwany przebieg zostawia takie sloty, a nic innego ich
   nie dotknie); skan bez zmian o nic nie pyta. Odpowiedź zapisuje się
   jako `slots.current_path` tylko dla wersji, którą przebieg widział —
   opublikowaną po przeglądzie widzi następny skan — a brak odpowiedzi
   (uszkodzona wersja w slocie) czyści wersję bieżącą: starsza nie
   zajmuje jej miejsca. Niedostępny magazyn
   (`SourceUnavailableError`) albo błąd producenta
   (`ProducerError`) kończy przebieg `abandon_pass` — nic nie zostaje
   oznaczone — a niedostępny magazyn dostaje stan `unavailable` z opisem.
7. Po przejściu całego magazynu (bez `segment`) `scan_projects` odkrywa
   manifesty `PROJECT_MANIFESTS` (`kartograf-project.json`) do głębokości
   `MAX_PROJECT_DEPTH` (4) w `project_dirs`, czyta zmienione
   (`project_stamps`: czas i rozmiar manifestu) przez `project_status`, a gdy
   zawiedzie — `read_project`, dopasowuje magazyn po ścieżce albo
   `StoreConfig.local_path` i zapisuje projekt (`write_project`); katalog,
   którego nie da się odczytać, zachowuje swoje projekty.

**Pełny skan dobowy.** Skan przyrostowy ufa znanym katalogom wersji, więc
plik usunięty albo dopisany wewnątrz takiego katalogu widzi dopiero skan
pełny. `plan_scans` wybiera tryb `full`, gdy magazyn nie miał udanego
pełnego skanu albo od ostatniego minęło `full_scan_interval_h` (domyślnie
24 h); czas ostatniego (`StoreIndexState.full_scan_at`) pokazują
`/health`, widok „Magazyn” i `archiwista status`.

**Harmonogram (`ScanScheduler`, `plan_scans`).** Co `TICK_S` (60 s):
magazyn, którego ostatni skan skończył się ponad `STARTUP_STALE` (15 min)
przed startem serwera albo nigdy, dostaje skan od razu; potem kolejny
interwał po końcu ostatniego skanu, kto by go nie zlecił —
`scan_interval_s`: 5 min na dysku lokalnym, 15 min na udziale. Magazyn
z zadaniem piszącym indeks jest pomijany. Magazyn `unavailable` jest tylko
sondowany i skanowany, gdy sonda go znajdzie, a jego katalog nie jest
pustym punktem montowania (`unreachable_detail`). Magazyn dodany albo
przeniesiony w ustawieniach dostaje pełny skan od razu. Raz na godzinę
(`PRUNE_INTERVAL`) tik przycina historię zadań (`JobSupervisor.prune`).

**Zadania pokrewne.** `footprints` (`POST …/footprints`, odmowa w trybie
offline): `entries_without_footprint` → `footprint(entry, network=True)`
paczkami, zapis `write_footprints`, pamięć jednostek uzupełniana z sieci.
`link_check` (`POST …/link-check` z `slot`): `confirm_link` →
`link_target` (KA-5; na udziale może przeczytać cały plik i policzyć
SHA-256); niezgodność zapisuje problem `link_mismatch` pochodzenia `check`
(`record_issue`), którego skan nie usuwa, a usuwa dopiero zgodny wynik
kolejnego sprawdzenia (`clear_issue`).

### 5.2 Odświeżenie widoku

Odświeżenie na żądanie wykonuje `GET /api/v1/local-coverage?area_id&product&store[&segment]`
(`read_local_coverage`) w procesie serwera:

1. Obszar z indeksu, jednostki ze slotów, których obrys przecina prostokąt
   obszaru (`IndexQueries.slots_in_bbox`). Ponad
   `REFRESH_VIEW_MAX_UNITS` (500) — odpowiedź z indeksu
   z `stale_reason` = `too_many_slots`.
2. Jeden `IndexWriter`, dla każdego segmentu `refresh_view` z jednostkami
   i `known_slots` slotów widoku, w łącznym budżecie `REFRESH_TIMEOUT_S`
   (10 s, przekazywanym jako `timeout_s`):
   jednostki w rozłącznych, ciągłych paczkach (`_unit_batches`, jedna na
   wątek); znane katalogi wersji slotów widoku i ich sąsiadów z tego samego
   katalogu (`IndexWriter.slots_beside`) nie są ani czytane, ani listowane.
   Przebieg obejmuje tylko sloty, dla których producent zwrócił wpisy:
   dopisuje ich nowe wersje i dowiązania i oznacza ich niewidziane wersje
   „brak pliku”; slot bez wpisów zostaje dla najbliższego skanu.
   Przekroczenie czasu (`TimeoutError`, nic nie zapisane) daje
   `refresh_timeout`, niedostępny magazyn — `store_unavailable`.
3. `IndexQueries.local_coverage` → `measure_coverage`: pole unii obrysów
   bieżących wersji przeciętej z obszarem, liczone shapely w układzie
   płaskim kraju (`PLANAR_CRS`: PL → EPSG:2180, CZ → EPSG:5514) po
   zagęszczeniu krawędzi i przeliczeniu przypiętą operacją producenta
   (`GeoAdapter.transformer` → `pinned_transform`); obrys natywny w układzie
   docelowym nie jest przeliczany. Wynik: `AreaCoverage` z `CountryCoverage`
   (`ratio`, `percent`, etykieta „lokalnie N% obszaru”).

### 5.3 Cykl życia żądania HTTP

Kolejność kontroli w `SecurityMiddleware` (opis w jej docstringu; to stan
kodu):

1. **Nagłówki odpowiedzi** liczone na starcie żądania: CSP z bieżących
   ustawień (`csp_header`), `Referrer-Policy: no-referrer`,
   `X-Content-Type-Options: nosniff`, a dla `/api/v1/session*`
   `Cache-Control: no-store`; dostaje je każda odpowiedź, także odmowa.
2. **`Host`** musi być jednym z `allowed_hosts(port)`
   (`127.0.0.1:<port>`, `localhost:<port>`) → inaczej `400 invalid_host`
   (ochrona przed DNS rebinding).
3. **`Origin` i `Sec-Fetch-Site`** (`origin_rejection`): obecny `Origin`
   musi być `http://<host>`; przy `Sec-Fetch-Site` odczyt przechodzi tylko
   z `same-origin` albo `none`, zmiana stanu tylko z `same-origin`
   i z `Origin` → inaczej `403 csrf_rejected`. Klient bez tych nagłówków
   (curl, skrypt agenta) przechodzi dalej.
4. Ścieżki poza `/api` (`/`, `/static/…`) i żądania publiczne
   (`POST /api/v1/session`, pliki `/api/docs`) kończą tu kontrolę sesji.
5. **Sesja:** ciasteczko `archiwista_session` w `SessionStore` → inaczej
   `401 session_required`.
6. **Token CSRF:** `X-Archiwista-CSRF` równy tokenowi sesji w **każdym**
   żądaniu `/api`, także odczycie (`csrf_rejection`, porównanie
   `hmac.compare_digest`) → inaczej `403 csrf_rejected`.
7. **Principal:** `session_principals` czyta przy każdym żądaniu role
   i grupy z bazy stanu (`session_principal`); konto wyłączone albo usunięte
   oraz sesja agenta sprzed `revoke_agent_sessions` (inna generacja
   w `index_info`) kończą sesję → `401 session_required`. Żądanie, które
   przeszło te kontrole, przesuwa koniec sesji (`SessionStore.extend`).
8. **Limit treści** (`body_limit`, dopiero po kontrolach nagłówków, więc
   treść żądania bez sesji nie jest czytana): 4 KiB dla `/api/v1/session`,
   1 MiB dla pozostałych, `POST /api/v1/areas` czyta treść sam z własnym
   limitem; zadeklarowany `Content-Length` ponad limit odmawia przed
   odczytem → `413 request_too_large`.
9. Sesja i principal trafiają do `request.state`; trasa bierze je przez
   `require_session` / `current_principal`, a projekty widoczne dla
   principala przez `visible_projects` (`Authorizer.visible_projects`,
   sekcja 7), które przekazuje zapytaniom i usługom.
10. Błędy usług zamienia na problemy RFC 9457 `install_error_handlers`
    (`PROBLEMS`: wyjątek → status i stabilny `code`; `title` z
    `MESSAGES["api_title_<code>"]`, `detail` po polsku).

Sesja zaczyna się od tokenu jednorazowego: `archiwista serve` wystawia
token startowy (`issue_one_time_token(…, "startup", minted_by=LOCAL_OWNER)`,
128 bitów, ważny 10 min), a w indeksie zostaje tylko jego skrót SHA-256
(`session_tokens`). Adres `http://127.0.0.1:<port>/#token=…`
(`fragment_url`) niesie token we fragmencie, który nie trafia do serwera,
dziennika ani `Referer`; przeglądarka otwierana przez `archiwista serve`
dostaje go przez prywatny plik `LaunchFile` (`open_in_browser`), nie przez
wiersz poleceń. `startSession` z `api.js` (wołane przez `main.js`) usuwa
token z adresu (`history.replaceState`) i wymienia go
(`POST /api/v1/session` → `redeem_one_time_token`, jednokrotnie, przed
terminem). Odpowiedź ustawia ciasteczko sesji (`HttpOnly`,
`SameSite=Strict`, `Path=/`) i zwraca `csrf_token`, który interfejs trzyma
w `sessionStorage`. Sesje żyją w pamięci serwera: koniec po 24 h bez żądań
(`SESSION_IDLE_TIMEOUT`), sesja agenta najwyżej 12 h
(`AGENT_SESSION_MAX_AGE`), restart serwera kończy wszystkie.

### 5.4 Cykl życia zadania i SSE

1. **Zlecenie** — `JobSupervisor.submit(kind, *, store, params, actor)`:
   nieznany magazyn → `NotFoundError` (`404`), złe parametry → `ValueError`,
   zadanie sieciowe w trybie offline → `OfflineModeError`
   (`409 offline_mode`, nic nie zapisane), trwające zadanie piszące indeks
   magazynu (także innego procesu) → `JobConflictError` (`409 conflict`
   z `job`). Inaczej wiersz `jobs` (`id`, `kind`, `actor`, `actor_kind`,
   `session`, `params`, `pid` nadzorcy) i zdarzenie `state` = `queued`.
   Trasa odpowiada `202` z `JobDetail` i `Location: /api/v1/jobs/{id}`.
2. **Start**, gdy jest miejsce: najwyżej `default_max_jobs()` procesów
   (połowa procesorów, co najmniej 2) i `MAX_NETWORK_JOBS` (2) zadań
   sieciowych; reszta czeka w kolejce. Przed startem nadzorca uzgadnia
   magazyny indeksu z ustawieniami (`sync_stores`), uruchamia proces
   roboczy we własnej grupie procesów, pisze `encode_spec(JobSpec)` (z
   `PROTOCOL_VERSION`, ustawieniami z chwili startu, ścieżką indeksu
   i pamięci) i ustawia `running`.
3. **Przebieg** — wątek czytający dekoduje linie (`decode_message`):
   `progress` (`current`, `total`; skan także `segment`, `entries`; obrysy
   `written`, `failed`) i `notice` (`level`, `code`, polski `message`)
   zapisuje jako numerowane `job_events` (`seq` od 1) i podaje słuchaczom;
   `result` albo `error` zapamiętuje.
4. **Koniec** — wynik procesu (`_outcome`): `result` → `succeeded`;
   anulowanie → `cancelled`; zatrzymanie serwera → `interrupted`; komunikat
   `error` → `failed` z jego kodem; kod 130 (`INTERRUPTED_EXIT`) albo SIGINT
   → `interrupted`; każde inne zakończenie → `failed` z kodem
   `internal_error` i przyczyną `worker_crashed` (sygnał albo kod wyjścia
   i ścieżka dziennika). `error` zadania (`JobError`) opisuje się tak jak
   problem żądania: `code` z rejestru błędów Nogat, `detail`, `hint`
   i `details` z przyczyną w `reason` (`worker_crashed`, `interrupted`,
   `offline_mode`, `snapshot_blocked`...); worker zgłasza `ArchiwistaError`
   przez `describe`, więc problem żądania i błąd zadania zgadzają się co do
   przyczyny. Końcowe zdarzenie `state` niesie `result` albo `error`.
   Wiersz zadania z 0.2.x (stary kod zadania, bez `details`) jest czytany
   z kodem z rejestru przy każdym odczycie (`JobError.from_json`) i nie jest
   przepisywany.
5. **Przerwanie** — anulowanie (`cancel`: Ctrl+C w poleceniach na pierwszym
   planie, usunięcie magazynu z ustawień; API nie ma trasy anulowania)
   i zatrzymanie serwera (`close`) wysyłają SIGINT (Windows:
   `CTRL_BREAK_EVENT`) i zabijają proces po 30 s; skan porzuca wtedy
   przebieg. Proces roboczy, któremu zniknął nadzorca (koniec stdin),
   przerywa się sam. Zadanie bez żywego nadzorcy (blokada
   `owner-<pid>.lock` zwolniona przez system) dostaje `interrupted` przy
   najbliższym spotkaniu: `recover` przy starcie nadzorcy albo `submit`
   zadania piszącego indeks tego samego magazynu.
6. **Historia** — `prune` przy starcie i z harmonogramu: zakończone zadania
   i dzienniki 90 dni (`LOG_MAX_AGE`; ostatnie zadanie każdego magazynu
   i rodzaju zostaje), dzienniki razem najwyżej 1 GB, rutynowe skany
   (przyrostowe z harmonogramu, udane, bez zmian) po 48 h
   (`ROUTINE_SCAN_MAX_AGE`).

**SSE przez `fetch`.** `GET /api/v1/jobs/{job}/events` (`job_event_stream`)
wysyła komunikaty `id: <seq>`, `event: progress|notice|state`, `data:`
(JSON w jednej linii, `sse_message`). Źródłem jest indeks: słuchacz
nadzorcy tylko budzi strumień, a po każdej sekundzie ciszy
(`POLL_INTERVAL_S`) strumień czyta indeks sam, więc widać też zadania innego
procesu (`archiwista reindex`). Wznowienie po `Last-Event-ID`; strumień
kończy końcowy `state`; zadanie zakończone bez nowych zdarzeń → `204`;
komentarz `: keepalive` po 15 s ciszy. `JobStreams` kończy otwarte
strumienie, zanim Uvicorn zacznie czekać na połączenia przy zatrzymaniu
(`LocalServer(…, on_stop=…)`). Interfejs nie używa `EventSource`, bo ten
nie wyśle nagłówka `X-Archiwista-CSRF`: `watchJob` w `web/src/api.js`
czyta strumień przez `fetch`, rozbiera go generatorem `eventMessages`
i po zerwaniu wznawia z `Last-Event-ID`.

### 5.5 Wczytanie obszaru

`POST /api/v1/areas` (`create_area`; z CSRF, odpowiedź `201`
z `Location`):

- **GeoJSON w WGS84** (`application/json`, `AreaInput`: `geometry`, `name`,
  `source` = `drawn` / `view` / `sheet`) → `save_area` →
  `area_from_geometry`: walidacja `require_wgs84_area`, naprawa
  `make_valid` (nigdy uproszczenie), kraje z `GeoAdapter.countries`, pole
  w km² w układzie płaskim pierwszego kraju w kolejności `PLANAR_CRS`
  (`area_crs`), suma krawędzi ograniczona `AREA_MAX_LENGTH_DEG` →
  `IndexWriter.write_area`.
- **Plik** (każdy inny typ treści, surowe bajty; parametry `name`, `layer`)
  → `save_area_file`:
  1. treść ponad `AREA_BODY_LIMIT_BYTES` (50 MB) → `413 area_too_large`
     (`check_body_size`);
  2. `read_area_file` zapisuje treść pod losową nazwą w
     `areas/.incoming/<losowa>/upload` (ścieżka klienta nigdy nie jest
     otwierana) i uruchamia `AREA_READER_COMMAND` w środowisku
     `sandbox.untrusted_env`: bez sieci GDAL/PROJ, bez proxy i poświadczeń,
     z `GDAL_PAM_ENABLED=NO` i `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`;
     po 30 s proces jest zabijany (`422 area_unreadable`);
  3. `area_reader.read_area` rozpoznaje format po treści (GeoJSON,
     GeoPackage, ZIP z jednym Shapefile), archiwum sprawdza przed
     rozpakowaniem (`MAX_MEMBERS` członków, razem ≤ `UNPACKED_LIMIT_BYTES`
     = 200 MB wg nagłówków, nic poza katalogiem, bez dowiązań i szyfrowania),
     w GeoJSON przyjmuje tylko `crs` typu `name` (GDAL pobrałby `link`/`url`
     przez HTTP), łączy wielokąty (≤ `MAX_VERTICES` = 100 000, inaczej
     `422 area_too_complex`) i oddaje jedną linię JSON: `geometry`, `crs`,
     `format`, `layer`, `features`, `vertices` albo odmowę z `layers` do
     wyboru;
  4. `area_from_file` przelicza geometrię do WGS84 przypiętą operacją
     producenta po zagęszczeniu krawędzi (`SEGMENT_DEGREES`,
     `SEGMENT_METRES`), dalej jak dla GeoJSON;
  5. `keep_copy` przenosi kopię do `areas/<id>/` (`area.geojson`,
     `area.gpkg` albo części Shapefile `area.*`); przy błędzie
     `discard_copy`.
- **Identyfikator** `area_id`: 16 znaków SHA-256 kanonicznego GeoJSON —
  ta sama geometria zawsze ma ten sam id. Kopie starsze niż
  `AREA_COPY_MAX_AGE` (7 dni) usuwa `prune_area_copies` przy starcie
  aplikacji; obszar zostaje w indeksie.

### 5.6 Podgląd i lokalne warstwy

`refs.py:ObjectResolver` zamienia `version:`, `file:` lub `snapshot:`
na źródło po sprawdzeniu korzenia, bieżącej tożsamości pliku i widoczności
projektu (`404` przy niewidocznym). `PreviewService` pyta
`PreviewCache` o obiekt po tożsamości treści, metadanych renderowania
i wersji renderera. Przy braku rozpoznania `RenderPool` oddaje żądanie
procesowi `previews.worker`, z limitem kolejki, czasu i pamięci.
Renderery rozpoznają rodzaj pliku; bez podglądu `PreviewInfo.reason`
daje kod, polski opis i zalecenie. Build (`POST …/preview`) tworzy zadanie
`preview` i lokalny COG, gdy źródło go potrzebuje. `GET /local-layers`
(`read_local_layers`) zbiera wersje dla roku albo kampanii, a
`layer_thumbnail` i `layer_tile` składają ich obrazy w procesie
renderującym. Obrazy z `/api/v1` wymagają CSRF również przy odczycie.
`version:` korzysta z prywatnego długiego cache HTTP; własny plik
i migawka z `ETag` sprawdzają widoczność przy każdym ponownym użyciu.

### 5.7 Skan własny, migawka, porównanie

`run_own_scan` → `scan_own_data` sprawdza folder projektu: domyślnie
`<katalog projektu>/dane/`, a wyjątkowy folder z `AppSettings.own_data_dirs`
ustawia administrator. `OwnReader` czyta pliki w procesie z ograniczeniami,
indeksuje zasięgi, treść i stan zmian od ostatniej migawki; nie zmienia
plików źródłowych. Dla GeoPackage `consistent_sqlite_read` bierze spójny
widok danych także przy otwartym edytorze i plikach WAL. Skan zakończony
na limicie nie oznacza nieprzejrzanych plików jako brakujących.
`check_snapshot` daje plan i powód blokady bez zapisu; `start_snapshot`
wymaga `project.write`, a `run_snapshot` → `make_snapshot` kopiuje spójny
komplet (SQLite backup lub pliki zestawu) do prywatnego katalogu
przejściowego, sprawdza sumy i publikuje atomowo przez zmianę nazwy
w `.wersje/`. Ten sam skrót treści nie tworzy drugiej wersji.
`services.compare:compare` czyta dwa widoczne `ref` i zestawia metadane
oraz schemat warstw, nie różnice obiektów.

---

## 6. Bezpieczeństwo

Model zagrożeń i decyzje: SPEC 10 ([`SPEC.md`](SPEC.md)), A-ADR-012
z erratami. Stan kodu w skrócie:

- **Tylko pętla zwrotna.** `serve_main` odmawia adresu innego niż
  `127.0.0.1` przed każdym innym krokiem (kod wyjścia 2), gniazdo zakłada
  `bind_loopback`; Uvicorn bez `proxy_headers` i nagłówka `Server`.
- **Kontrola każdego żądania** — `SecurityMiddleware` (sekcja 5.3):
  `Host`, `Origin`/`Sec-Fetch-Site`, sesja, token CSRF w każdym żądaniu
  `/api` (ciasteczko przeglądarka wysyła na każdy port hosta, więc nigdy
  nie działa samo), principal z bazy stanu, limit treści. Bez nagłówków
  CORS.
- **Tokeny jednorazowe** 128-bitowe, w indeksie tylko skrót SHA-256:
  startowy 10 min, agenta 5 min (`TOKEN_TTL`); wystawia je
  `archiwista token` albo `POST /api/v1/session/tokens` — nie sesja agenta
  (`403 permission_denied`). `archiwista token --revoke-all`
  (`revoke_agent_sessions`) kończy wszystkie sesje agentów, także
  działającego serwera, i unieważnia niewykorzystane tokeny agentów.
- **Nagłówki odpowiedzi** — CSP z bieżących ustawień (`csp_header`):

  ```
  default-src 'self'; script-src 'self'; style-src 'self'; worker-src 'self';
  img-src 'self' data: blob: <P>; connect-src 'self' <P>; font-src 'self';
  object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
  ```

  gdzie `<P>` to pochodzenia skonfigurowanych podkładów, tylko przy
  `offline = false`; do tego `Referrer-Policy: no-referrer`
  i `X-Content-Type-Options: nosniff`.
- **Ścieżki.** Pliki wskazuje identyfikator z indeksu, nigdy ścieżka
  klienta: `resolve_indexed_path` rozwiązuje ścieżkę względną w korzeniu
  magazynu albo projektu i odrzuca wyjście poza niego, także przez
  dowiązanie symboliczne (`PathOutsideRootError` →
  `403 path_outside_root`); `indexed_path` składa ścieżkę „do skopiowania” bez
  dotykania dysku.
- **Niezaufane pliki:** `sandbox.untrusted_env`, jawne sterowniki
  (`formats.py`), `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` i
  `GDAL_PAM_ENABLED=NO` bronią przed siecią, niejawnie dołączanymi plikami
  i zapisem obok źródła. Pliki obszarów, podglądy i dane własne czytają
  procesy z limitami czasu i pamięci; `ObjectResolver` sprawdza korzeń
  oraz widoczność projektu przed sięgnięciem do pamięci wspólnej po treści.
- **Dzienniki.** Dziennik dostępu Uvicorna jest domyślnie wyłączony;
  `archiwista serve --access-log` włącza go z redakcją wartości `token=`
  (`TokenRedactionFilter`, `redact_tokens`).
- **Dane lokalne** prywatne (`0700`, `umask 077`, sekcja 4); biblioteki
  interfejsu i Swagger UI w pakiecie z sumami SHA-256 (sekcja 9).

---

## 7. Uprawnienia

Model z A-ADR-029 (SPEC 10.2): Archiwista egzekwuje uprawnienia tylko we
własnej powierzchni — interfejsie, API, CLI, sesjach agentów i podglądach.
Lokalnie działa jedna osoba, lecz model i baza stanu są testowane z wieloma
tożsamościami (`tests/unit/test_authorize.py`,
`tests/integration/test_permissions_api.py`,
`tests/unit/test_project_visibility.py`).

- **`Principal`** (`auth/principal.py`): `id` (zapisywany jako `actor`
  zadań), `kind` (`local_owner`, `user`, `agent`, `scheduler`), `roles`,
  `groups`, `session` (etykieta sesji). Tryb lokalny: `LOCAL_OWNER`
  i `SCHEDULER` — oba o `id` = `local` i rolach `admin` oraz
  `store_writer`. Sesja trzyma tylko `id` i rodzaj; role i grupy czyta się
  na nowo przy każdym żądaniu (`session_principal`), więc agent może
  dokładnie tyle, ile teraz principal, który wystawił jego token.
- **`Authorizer(state, settings)`** (`auth/authorize.py`) — jedyne miejsce
  decyzji: `can(principal, action, resource)`, `require(…)`
  (`PermissionDeniedError` → `403 permission_denied`) i
  `visible_projects(principal)`. Akcje (`ACTIONS`): `project.view`,
  `project.share`, `project.write` (od v0.2: migawki plików projektu),
  `users.manage`, `groups.manage`, `settings.write`, `store.write`.
  `admin` zarządza kontami, grupami i ustawieniami, widzi każdy projekt,
  zarządza dostępem do niego i go zmienia; właściciel — swój (projekt bez
  wpisu dostępu zmienia tylko administrator);
  widoczność `public` (wszyscy), `users` (osoby z wpisu), `group` (członkowie
  grup z wpisu), `private` (tylko właściciel); projekt bez wpisu wg
  `default_project_visibility` (`public` albo `private` = tylko
  administratorzy). `store.write` = rola `store_writer` albo ustawienie
  `store_write_for_all`; w 0.2.0 żadna trasa jej nie wymaga (v0.3).
- **Widoczność — jeden punkt przejścia.** `visible_projects` buduje
  `ProjectVisibility` (`everything`, `granted`, `denied`, `unlisted`;
  `sees(key)`; administrator dostaje `ALL_PROJECTS`). Trasy biorą ją
  zależnością `api/dependencies.visible_projects` i podają dalej: zapytania
  `IndexQueries` przyjmują ją jako wymagany argument `visible`
  (`slots`, `slot`, `version`, `footprints`, `projects`, `project`,
  `pin_problems`), a usługi (`store_summary`, `project_detail`) przekazują
  ją dalej. Routery i CLI nie filtrują same. Raport magazynu liczy
  nieużywane wersje względem przypięć wszystkich projektów, ale wymienia
  tylko projekty widoczne i ich problemy przypięć. Zadania (od v0.2):
  zakres zadania wynika z `store` i `params` — zadanie magazynu albo wersji
  (`version:`) i zadanie bez projektu widzą wszyscy, zadanie tylko danych
  projektów (`own_scan` projektu, `snapshot`, `preview` plików `file:`
  i `snapshot:`) — ten, kto widzi któryś z nich; `JobSupervisor.list`,
  `get` i `events` przyjmują `visible`, a zadanie `preview` pokazuje tylko
  `refs` i `failed[]` widocznych projektów (liczniki w całości).
- **Klucz projektu** to katalog po `realpath` (`access_key`): ten sam
  w `project_acl` bazy stanu i w kolumnie `projects.access_key` indeksu,
  więc przebudowa indeksu nie zmienia dostępu, a dowiązania symboliczne do
  katalogu projektu dzielą wpis.
- **Odpowiedzi:** projekt niewidoczny → `404 not_found`, widoczny bez
  prawa do działania → `403 permission_denied` (`services/access.py`).
  Każda zmiana kont, grup i dostępu trafia do `permission_log` z
  wykonawcą, rodzajem i sesją.
- **CLI** (`reader.py`, `commands/`, `admin.py`) działa jako `LOCAL_OWNER`
  przez ten sam `Authorizer` i te same usługi.

---

## 8. API HTTP i CLI dla ludzi i agentów

Pełny przewodnik dla skryptów i agentów: [`AGENT_API.md`](AGENT_API.md)
(sesja agenta, filtry, stronicowanie, zadania i SSE, błędy). Interfejs WWW
pobiera dane z serwera wyłącznie przez to API (`web/src/api.js`); poza nim
czyta z serwera tylko własne pliki statyczne.

**HTTP** — prefiks `API_PREFIX` (`/api/v1`), JSON w UTF-8:

| Router (tag) | Trasy |
|---|---|
| `api/session.py` (`session`) | `POST /session` (bez sesji), `GET`/`DELETE /session`, `POST /session/tokens` |
| `api/health.py` (`health`) | `GET /health`, `GET /sources` |
| `api/stores.py` (`stores`) | `GET /stores`, `GET /stores/{store}` |
| `api/slots.py` (`catalog`) | `GET /slots` (także filtr `project`), `/products`, karty slotów i wersji, `…/sidecar`, `/requests/{parent_request}` |
| `api/map.py` (`map`) | `GET /map/footprints`, `GET /map/sheets` |
| `api/projects.py` (`projects`) | `GET /projects`, `GET /projects/{project}`, `GET /projects/{project}/status` |
| `api/settings.py` (`settings`) | `GET /settings`, `PUT /settings` (`settings.write`) |
| `api/areas.py` (`areas`) | `POST /areas`, `GET /areas/{area_id}`, `GET /local-coverage` |
| `api/jobs.py` (`jobs`; tylko gdy `create_app` dostaje `jobs`) | `POST /stores/{store}/scan`, `…/footprints`, `…/link-check`, `GET /jobs`, `GET /jobs/{job}`, `GET /jobs/{job}/events` |
| `api/admin.py` (`permissions`) | `GET`/`POST /users`, `PATCH`/`DELETE /users/{user_id}`, `GET`/`POST /groups`, `PUT /groups/{group_id}/members`, `DELETE /groups/{group_id}`, `GET`/`PUT /projects/{project}/access` |
| `api/previews.py` (`previews`) | `GET`/`POST /stores/{store}/versions/{version}/preview`, `GET …/preview.png`, `…/tiles/{z}/{x}/{y}.png`, `…/features`, `…/members` |
| `api/layers.py` (`layers`) | `GET /local-layers`, `/local-layers/thumbnail.png`, `/local-layers/tiles/{z}/{x}/{y}.png` |
| `api/compare.py` (`compare`) | `GET /compare?a=<ref>&b=<ref>` |
| `api/owndata.py` (`own_data`) | `GET /projects/{project}/files`, `PUT …/data-dir`, `GET …/files/{file_id}`, `…/layers`, `…/snapshot-plan`; `POST /projects/{project}/scan`, `POST …/snapshots`; podglądy, kafle, obiekty i ZIP pliku i migawki |

Zasady w kodzie: modele Pydantic (`api/models.py`, `models_previews.py`,
`models_layers.py`, `models_compare.py`, `models_owndata.py`; sesja
i administracja przy routerach) tworzą także schemat OpenAPI
z przykładami; `operationId` = nazwa funkcji trasy
(`operation_id`); `/api/v1/openapi.json` wymaga sesji, a `/api/docs` to
lokalny Swagger UI z `api/swagger/` (bez CDN i skryptów inline). Filtry
listy to modele z `extra="forbid"` (nieznany parametr → `422`); `limit`
1–200 (`MAX_PAGE_LIMIT`, domyślnie 50); kursor nieprzezroczysty, związany
z zapytaniem (stronicowanie po kluczu sortowania); daty ISO. Odpowiedzi
z indeksu (`IndexAnswer`) mają `stale` i `stale_stores`, gdy magazyn jest
niedostępny — wiersze są wtedy stanem z `indexed_at`, nie dowodem, że
plików nie ma. Błędy to `application/problem+json` (RFC 9457) ze stabilnym
`code` niezależnym od polskiego `detail`; problemy wtyczek mają człon
`source` z wymaganiem pip, błąd producenta człon `kartograf`
z niezmienionym komunikatem (`<producent>_error`).

**CLI** (`archiwista`, `cli.main`):

| Polecenia | Moduł | Uwagi |
|---|---|---|
| `serve [--host] [--port] [--no-browser] [--access-log]`, `token [--port] [--json \| --revoke-all]` | `server.py` | `--port 0` wybiera wolny port |
| `status`, `sources`, `search [ZAPYTANIE]`, `entry MAGAZYN SLOT`, `version MAGAZYN WERSJA`, `projects`, `project PROJEKT` | `reader.py` | bez serwera, na lokalnym indeksie; `--json` wypisuje model odpowiedzi API, błąd jako problem RFC 9457 z kodem wyjścia 1; opcje `search` mają nazwy parametrów `/slots` (`search_filters` → `CatalogFilters`) |
| `users list\|add\|roles\|remove`, `groups list\|add\|members\|remove`, `share`, `state export\|import` | `admin.py` | `users`, `groups` i `share` z `--json` o modelu API; `state export [--output PLIK]`; `state import PLIK` przyjmuje tylko pustą bazę stanu |
| `reindex [--store ID]` | `jobs/reindex.py` | pełny skan jako zadanie `local` na pierwszym planie; postęp na stderr, podsumowanie na stdout; wyjście 0, 1 (błąd, przerwanie, `conflict`), 2 (nieznany magazyn); Ctrl+C anuluje |
| `doctor` | `doctor.py` | diagnostyka po polsku z poleceniem naprawy przy każdym problemie |
| `preview REF [--build] [--output PLIK.png]`, `layers --store ID --product NAZWA [--area-id ID] [--thumbnail KLUCZ]`, `compare REF REF` | `commands/previews.py`, `commands/layers.py`, `commands/compare.py` | te same usługi co API, obrazy zapisywane na żądanie |
| `files PROJEKT`, `file PROJEKT PLIK`, `snapshot PROJEKT PLIK [--plan \| --note TEKST]`, `own-scan [--project PROJEKT]` | `commands/owndata.py` | lista i karta z indeksu; migawka i skan to zadania z postępem |

---

## 9. Interfejs WWW

Preact + htm bez kroku budowania (A-ADR-028): przeglądarka ładuje moduły ES
wprost z pakietu Pythona, bez Node.js i CDN. `app.py` serwuje
`web/index.html` pod `/` i każdy plik `web/` pod `/static/…` — bez sesji,
ale za kontrolą `Host` i `Origin`.

**Pliki.** `index.html` (bez skryptów inline: `<link>` do
`/static/styles.css` i `<script type="module" src="/static/src/main.js">`),
`styles.css` (tokeny, powłoka, wspólne komponenty), `favicon.svg`,
`vendor/` z przypiętymi bibliotekami: Preact 10.29.8 (MIT), htm 3.1.1
(Apache-2.0), MapLibre GL JS 6.14.0 (BSD-3-Clause, wydanie ESM), glify Noto
Sans Regular z openmaptiles/fonts 2.0 (OFL-1.1; zakresy U+0000–U+02FF,
U+0400–U+04FF i U+2000–U+20FF). `vendor/vendor.json` wymienia każdy plik
z sumą SHA-256, źródłem i licencją; `tests/unit/test_vendor_integrity.py`
odrzuca plik zmieniony, brakujący albo niewymieniony (to samo dla
`api/swagger/`).
Jedyna zmiana w plikach z npm: w `vendor/preact/hooks.mjs` import
`"preact"` zamieniony na `"./preact.mjs"` (pole `modified` w manifeście).

**Moduły `web/src/`:**

| Moduł | Rola |
|---|---|
| `main.js` | start sesji z `#token=…` albo z ciasteczka, potem `Shell`; bez sesji `SessionScreen` |
| `api.js` | klient `/api/v1`: funkcja na trasę o nazwie `operationId` w camelCase (`listSlots`, `getSlot`, `startScan`…), `request`, `startSession`, `ApiError`, `onSessionLost`, `watchJob` (SSE przez `fetch`), `uploadArea`; token CSRF w `sessionStorage` (`TOKEN_KEY`), przekazywany innym kartom przez `BroadcastChannel` |
| `types.js` | typy JSDoc modeli API (bez kodu) |
| `router.js` | stan w adresie `/?view=<widok>&…`: `readRoute`, `href`, `navigate`, `setParams`, `useRoute`, `Link` |
| `routes.js` | rejestr widoków `VIEWS` i nakładek `OVERLAYS`, `startView`, `findView` |
| `shell.js` | powłoka: pasek, nawigacja, baner, `ViewHost` (leniwe ładowanie widoku), `OverlayHost`; bez magazynu w ustawieniach otwiera kreator |
| `context.js` | `AppContext`, `useApp`, `useAppState`: sesja, ustawienia, `/health` co 2 s przy skanie albo czekającym magazynie, inaczej co 15 s |
| `banner.js` | `IndexBanner`: stan indeksu i magazynów |
| `setup.js` | kreator pierwszego uruchomienia i widok „Ustawienia” (`PUT /settings`) |
| `ui.js` | Preact i htm w jednym imporcie (`html`), `Icon`, `Seg`, `CopyButton`, `Tech`, `ProblemView`, `Spinner`, `loadStylesheet` |
| `panels.js`, `hooks.js`, `format.js` | układ paneli (`ViewLayout`, `Resizer`, `usePanelWidths`), `useResource`, `useMedia`, formaty polskie (`day`, `stamp`, `int`, `size`, `plural`, `count`) |
| `search.js` | `SearchButton`, skróty `Ctrl+K` i `/`, `SLOT_PARAMS` (parametry `/slots` w adresie) |
| `maplibre.js` | `loadMapLibre`, `GLYPHS`, `GLYPH_FONT` |
| `views/` | `map.js` (start), `catalog.js` z `catalog-grid.js` (rysuje tylko wiersze blisko widoku) i `catalog-filters.js`, `file.js` (karta pliku — nakładka), `projects.js`, `store.js`, wspólne `cards.js` (`IssueList`, `useJob` i `JobStatus` dla SSE, `FileLink`, `CopyAction`) |
| `map/` | `canvas.js` (`MapCanvas`), `draw.js`, `panel.js` (`SelectionPanel`), `coverage.js` (`LocalState`), `legend.js`, `style.js` (podkład: rastrowy albo wektorowy we własnym szarym stylu), `sheets.js` (siatki godeł), `geo.js`, `products.js` |
| `labels/` | słownik tekstów (niżej) |
| `previews.js`, `fan/fan.js`, `fan/layout.js`, `views/catalog-timeline.js` | podglądy przez `fetch` z CSRF i adres `blob:`, Wachlarz lat/migawek, Oś czasu warstw |
| `views/own.js`, `views/compare.js`, `views/set-details.js` | plik własny i plan migawki, zestawienie metadanych i kurtyna, szczegóły wybranej warstwy |
| `map/previews.js`, `map/own.js` | kafle i obiekty lokalnych warstw, dane projektu oraz migawki na mapie |

**Rejestracja widoku.** Widok to jedna linia w `VIEWS` (`id` = parametr
`view` i klucz nazwy w `labels/shell.js` `nav`, `icon`, `load` = dynamiczny
import modułu, opcjonalnie `start`, `bottom`), nakładka — linia w
`OVERLAYS` (`param`, `load`). Moduł eksportuje domyślnie komponent
dostający `route` (nakładka także `value` i `onClose`); teksty trzyma
w `labels/<widok>.js`, styl ładuje przez `loadStylesheet`. Nic innego
w powłoce się nie zmienia. Widoki 0.2.0: `map` (start), `catalog`,
`projects`, `store`, `setup`; nakładki `file`, `own`, `compare`.

**Słownik.** Interfejs nie wpisuje tekstów w komponenty
(`DEVELOPMENT_STANDARDS.md`): `labels/index.js` składa część wspólną
`T` (`common`, `shell`, `setup`), a każdy widok importuje własny plik
`labels/<widok>.js`, więc widoki nie edytują wspólnego pliku. Teksty mają
miejsca `{nazwa}` wypełniane przez `t(text, values)`, a formy liczby
mnogiej to tablice `[one, few, many]` dla `count`. Teksty serwera i CLI
leżą osobno w `messages.py` (`MESSAGES`).

**Ograniczenia z CSP:**

- `script-src 'self'` bez `'unsafe-inline'` i `'unsafe-eval'`: brak
  skryptów inline i map importów inline, więc moduły importują ścieżki
  względne; htm zamienia szablony znakowane na wywołania `h` w czasie
  działania, bez `eval`;
- `style-src 'self'`: arkusze stylów to pliki dołączane `<link>`
  (`loadStylesheet`);
- `worker-src 'self'` bez `blob:`: MapLibre 6 uruchamia
  `maplibre-gl-worker.mjs` jako moduł roboczy z tego samego pochodzenia;
- `font-src 'self'`: etykiety mapy z glifów w pakiecie (`GLYPHS`);
- podkłady w `img-src` i `connect-src` (MapLibre pobiera kafle i TileJSON
  przez `fetch`) tylko poza trybem offline; kafle podkładu wektorowego muszą
  leżeć w pochodzeniu jego TileJSON; CSP należy do dokumentu, więc zmiana
  trybu offline albo listy podkładów przeładowuje stronę (`setup.js`).

Testy przeglądarkowe (`tests/e2e/`, Playwright na prawdziwym
`archiwista serve`) zapisują naruszenia CSP (`securitypolicyviolation`,
`Tab.csp_violations` w `tests/fixtures/browser.py`) i wymagają, by ich nie
było — także z podkładem z innego pochodzenia.

---

## 10. Punkty rozszerzeń (v0.3+)

Zakres wydań: [`SCOPE.md`](SCOPE.md) i SPEC 13. Podglądy oraz dane własne
z migawkami są już wdrożone (sekcje 2–9); poniżej granice następnych etapów.
- **Działania (v0.3).** Pobieranie i akcje projektów przez API Kartografa
  (wymagania KB, KC, KD i KH w SPEC 12) wejdą jako nowe rodzaje zadań
  w procesach roboczych; protokół ma już stan `cancelled` i przerwanie
  SIGINT. Uprawnienie istnieje: `Authorizer.can(principal, "store.write")`
  (`store_writer` albo `store_write_for_all`), dziś bez wywołań. Interfejs
  źródła nie ma jeszcze operacji `commands`, `validate`, `format_command`,
  `plan` i `run` z tabeli SPEC 5.3.
- **Tryb zespołu (v0.4, A-ADR-013).** Model jest gotowy: `PrincipalKind`
  `user`, `principal_for`, konta i grupy w `state.sqlite`, role czytane przy
  każdym żądaniu, `permission_log` z rodzajem wykonawcy i sesją. Brakuje
  logowania i haseł, a `serve_main` odmawia adresu innego niż `127.0.0.1`;
  sesje żyją w pamięci jednego serwera (`SessionStore`).
- **Drugi producent: IMGWTools i ČHMÚ (v0.5–v0.6, A-ADR-019, A-ADR-024,
  ADR 0032).** Wtyczka `imgw` jest zarejestrowana w grupie entry points
  `archiwista.sources` (extra `archiwista[imgw]`, `install_requirement`):
  `src/archiwista/adapter/imgw/` czyta magazyn IMGWTools obu dostawców przez
  `iter_store`, sądzi katalog po znaczniku `imgw-store.json` i nie importuje
  `pyarrow`; bez pakietu źródło ma stan `not_installed`, a błędy producenta
  kod `imgwtools_error` (`PRODUCER_CODES`). Testowa wtyczka
  `tests/fixtures/second_source/` (płaski magazyn bez segmentów, arkuszy
  i dowiązań) przechodzi przez skaner, indeks i API bez zmian w rdzeniu
  (`tests/integration/test_second_adapter.py`). Magazyn przyjmuje katalog
  `imgw` obok katalogu `kartograf` albo zamiast niego (`StoreConfig.roots`
  podaje oba, sekcja 4), a skan indeksuje pliki IMGW jako wersje slotów
  (`slot_key`, `provider`, obserwacje jako historia slotu, zbiory jako
  segmenty opisane przez adapter) i pyta producenta o wersję bieżącą
  slotów, których dotknął (`CurrentVersionAdapter`: IMGWTools nie ma
  dowiązań, więc wersję bieżącą wybiera jego `current_version`). Do
  zrobienia: `PROJECT_MANIFESTS` zna tylko `kartograf-project.json`,
  a zdolności stacji i szeregów (`stations`, `series_index`, `read_series`
  z SPEC 5.3) nie ma jeszcze w `sources/protocol.py`.

---

## 11. Wydajność

Magazyn odniesienia: 50 000 slotów, 80 000 wersji, 30 projektów.
Metoda i wszystkie wyniki v0.2 (SSD oraz SMB 3):
[`reports/v0.2-measurements.md`](reports/v0.2-measurements.md);
punkt wyjścia v0.1: [`reports/v0.1-measurements.md`](reports/v0.1-measurements.md).

| Operacja | Cel SSD | Wynik v0.2 SSD |
|---|---|---|
| pełny skan / przyrost bez zmian | ≤ 120 s / ≤ 20 s | 64,8 s / 13,2–13,6 s |
| odświeżenie widoku, p95 / lista, p95 | ≤ 1 s / ≤ 200 ms | 441–447 ms / ≤ 162 ms |
| obrysy mapy ok. 5000, p95 | ≤ 300 ms | 229 ms (285,6 ms pod obciążeniem) |
| pierwszy kafel ortofotomapy 22 528 × 24 326 px, p95 | ≤ 1 s | 222 ms |
| miniatura warstwy 35 arkuszy / 50 SM5 | ≤ 2 s | 1306 / 1234 ms |
| podgląd roku: przesunięcie do ostatniego kafla | ≤ 2 s | p95 528 ms |
| `own_scan` 1000 plików, p95 / migawka GeoPackage 123 MB | ≤ 2 s / ≤ 15 s | 0,89–1,07 s / 5,8–6,3 s |
| indeks / szczyt RSS serwera | ≤ 500 MB | 263 MB / 188–202 MiB |

Płynność mapy ≥ 30 klatek/s z GPU jest **niezweryfikowana**:
konto testowe nie ma dostępu do sprzętowego WebGL; SwiftShader osiągał
8,4 klatek/s przy 4532 obrysach-wielokątach.

**Co w kodzie odpowiada za te liczby:**

- skan przyrostowy nie czyta ani nie listuje znanych katalogów wersji
  (mapowanie `skip_versions`, sekcja 5.1); sidecary dowiązań i `full_sheet`
  czyta zawsze (z nich wynika bieżąca wersja), bez haszowania treści;
- równoległość tylko tam, gdzie ukrywa opóźnienie udziału: części
  segmentów, najcięższe najpierw, w `scan_threads` wątkach; na dysku
  lokalnym jeden wątek (pod GIL więcej wątków tylko konkuruje — pomiar
  w docstringu `_target`);
- zapis paczkami w jednej transakcji, ograniczona kolejka wpisów, rzadszy
  odśmiecacz cykliczny w czasie skanu (`_rare_collections`), ścieżki
  względne cięciem prefiksu zamiast `Path.relative_to` (`_relative`
  w adapterze);
- połączenia SQLite: pisarz z dużą pamięcią stron i `mmap`, czytelnicy
  serwera bez `mmap` i z małą pamięcią (RSS), `wal_autocheckpoint = 8192`;
- zapytania: stronicowanie po kluczu zamiast `OFFSET`, R*Tree dla mapy,
  powyżej `MAP_FOOTPRINT_LIMIT` (5000) obrysów siatka z licznikami
  (`grid_columns` ≤ `MAX_GRID_COLUMNS`), FTS5 jeden wiersz na slot,
  prefiks SHA-256 (8–64 znaki szesnastkowe) przez indeks `versions_sha256`;
- serwer: gniazdo `IPPROTO_TCP` w `bind_loopback` (bez opóźnienia Nagle'a
  ok. 40 ms na żądanie), interfejs rysuje tylko wiersze katalogu blisko
  widoku.

Testy wydajności (domyślnie pominięte, znaczniki `perf` i `smb`):
`tests/perf/test_store_50k.py`, `test_previews_perf.py` i
`test_own_data_perf.py`; polecenia i warunki — raport v0.2.
