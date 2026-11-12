# ADR-053: Archiwista reads `nogat.toml` for its data directory, its caches and its language

**Date:** 2026-11-10
**Status:** accepted (the author's decision of 2026-11-09, „Czytać `nogat.toml`: tak, dla spójnego `data_dir`”; the open question of `docs/PROGRESS.md`); amends ADR-033 (erratum 1)

**Context:** The Nogat tools keep their shared settings in one file, `nogat.toml` (ECO-028, DEV-18.1): the path in `NOGAT_CONFIG`, else `platformdirs.user_config_path("nogat")`, with the shared keys `data_dir`, `cache_dir` and `lang` in the table `[nogat]` and each tool's own keys in `[<tool>]`. Each tool's data lie in `<data_dir>/<tool>` and its caches in `<cache_dir>/<tool>` (DEV-18.2). DEV §18 is written for profile `tool`; Archiwista, profile `app`, kept its own `config.toml` and its own platform directories (`~/.config/archiwista/`, `~/.local/share/archiwista/`), so a person who moved the ecosystem's data to one disk with `nogat.toml` found Kartograf's and Obserwator's stores there and Archiwista's index, state database and preview cache still in the home directory. ADR-033 rejected reading the file (option C) because that question was open; the producers' default roots reach the wizard through the producers' own `store_root()`.

**Options:**
- What Archiwista reads:
  - A) Nothing; `config.toml` and the platform directories stay alone. Rejected: the author's decision.
  - B) The three shared keys of the file, from `[archiwista]` before `[nogat]` (DEV-18.1), with Archiwista's own settings first.
  - C) B and the variables `NOGAT_DATA_DIR`, `NOGAT_CACHE_DIR` and `NOGAT_LANG`. Rejected: the data directory holds the state database, which cannot be rebuilt (accounts, sharing, the action log); a variable left in one shell would start the server on another, empty directory, while the file is the one place every process of the person reads. The test isolation (`tests/fixtures/isolation.py`) leads those variables into the producers' canary tree, which Archiwista's own data must not enter.
  - D) Move `config.toml` into the table `[archiwista]` of the file. Rejected: Archiwista writes its settings itself (the wizard, "Ustawienia"), and a write into a file other tools own would rewrite their tables.
- A file that cannot be used (unreadable, not UTF-8 text, not TOML, a table that is not one, a value of the three keys that is not valid, or a file `NOGAT_CONFIG` names that does not exist):
  - E) Every command but `archiwista doctor` refuses to run (`validation_error`, reason `shared_settings`); the doctor reports it as an error. As Kartograf does (`check_config`).
  - F) Ignore it and use the defaults, as Hydrolog does. Rejected: the server would start on the platform directory, with another index and state database, without a word.
- The caches apart from the data:
  - G) A project's data folder may overlap none of Archiwista's own directories: the data directory, the producers' caches and the preview cache (`AppPaths.own_dirs`). Jobs know the caches from the preview cache the server gives them (`JobSpec.app_paths`).
  - H) Only the data directory, as before. Rejected: with `cache_dir` a folder could then hold the preview cache, and its previews would be read as the project's own data.

**Decision:** B, E and G.

1. **Precedence.** A value comes from the first of: Archiwista's own setting, `nogat.toml` (the table `[archiwista]` before `[nogat]`), the built-in default:

   | Key | Archiwista's own setting | From `nogat.toml` | Built-in default |
   |---|---|---|---|
   | `data_dir` | none | the index, the state database, `jobs/`, `areas/` and `work/` in `<data_dir>/archiwista` | the user data directory of `archiwista` (Linux `~/.local/share/archiwista/`) |
   | `cache_dir` | none | the preview cache `previews/` and the producers' `cache/` in `<cache_dir>/archiwista` | in the local data directory |
   | `lang` | `--json` output is English; the API follows each request's `Accept-Language` (English without it) | the language of the text for a person on the command line (help, usage errors, a command's output, the line before an error document), `pl` or `en` | Polish |

   `config.toml` stays in the user configuration directory of `archiwista`; its stores' directories and a project's data folder are Archiwista's own settings and never come from the file. A path in the file is absolute after `~` is expanded.
2. **The producers' default roots.** Unchanged (ADR-033): Kartograf's and Obserwator's `store_root()` report `KARTOGRAF_ROOT`, `[kartograf] root` or `<data_dir>/kartograf` (and the same for Obserwator) from the same file, so the wizard's offer and Archiwista's own directory share one `data_dir` without a second copy of the producers' rules.
3. **The report.** `archiwista doctor` names the file (where it is, which place named it, whether it exists) or the error why it cannot be used, and gives the data directory, the caches and the language with the setting that gave each (`[nogat] data_dir of nogat.toml`, the built-in default). There is no `archiwista config show`: DEV-18.6 is for profile `tool`.
4. **Code.** `archiwista.shared_settings` reads the file once per command (`SharedSettings.read`, `tomllib`, never raising); `AppPaths.default(shared)` gives the directories, `AppPaths.cache_home` the caches apart from the data; `cli.main` takes the person's language from it (`error_document.person_language` for the line of a refusal) and refuses an unusable file before any directory is used.

**Consequences:**
- A computer without `nogat.toml`, and every installation that had one without these keys, keeps its directories: nothing moves. Setting `data_dir` later starts Archiwista on a new, empty data directory: move `index.sqlite` and `state.sqlite` (and the rest of the old directory) there first, or `archiwista state import` a `state export` into it.
- The author's team test server sets `XDG_CONFIG_HOME` to a directory of its own, where no `nogat/nogat.toml` lies, so it keeps its directories.
- The tests run with `NOGAT_CONFIG` naming an empty file (`tests/fixtures/isolation.py`), so they meet the built-in defaults unless a test writes the file it needs.

**Erratum 1 (2026-11-12, A-ADR-054; Nogat DEV-15.4, DEV-18.1):** a fourth key, the table `gui` (`[nogat.gui]`; `[archiwista.gui]` before it, whole): the GUIs of the deployment by registry name, each address absolute or a path on this host, with no default. `archiwista serve` gives it to the interface's menu „Aplikacje” through `GET /api/v1/session` (`gui`); a `gui` that is not a table, or an address that is not a non-empty string, makes the file unusable as an invalid value of the other keys does (E), and `archiwista doctor` names the table that gave it (decision 3).
