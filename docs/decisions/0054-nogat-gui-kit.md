# ADR-054: Nogat's GUI kit in Archiwista: the menu „Aplikacje” and the hand-off

**Date:** 2026-11-12
**Status:** accepted (the author's approval of Nogat's plan `docs/plans/2026-11-12-gui-links-and-handoff.md` on 2026-11-12, „przejdź do etapu 1”, its step 6; Nogat ECO-058, DEV-15.4 to DEV-15.6, DEV-18.1); amends ADR-052 decisions 4 and 5 (erratum 1) and ADR-053 decision 1 (erratum 1)

**Context:** Stage 1 of Nogat's GUI platform (ECO-058): every GUI of the ecosystem shows the kit's app menu `<nogat-app-menu>` in its top bar, listing the GUIs whose addresses the deployment sets in the table `gui` of `[nogat]` in `nogat.toml` (DEV-15.4, DEV-18.1), and hands data off through the kit's `nogat-handoff.js` (DEV-15.5); the kit's files, the marks and the schemas are copied byte for byte and Nogat's `drift` reports each copy as current, behind or modified (DEV-15.6). Archiwista wrote the hand-off of its station card itself (ADR-052): JSON without a final newline, a file name that replaced only `\/:*?"<>|`, and the Clipboard API without a fallback, which fails on the plain-HTTP address of a server on the network, where browsers give no Clipboard API. Its copy of `handoff-1.schema.json` was older than `node_provenance` (Nogat `8727f6e`) and its `error_registry.json` the standard 2.1's (`bc72b92`). Archiwista has not adopted Nogat's tokens yet (DEV-15.3, `docs/PROGRESS.md` Next); the kit styles the menu with the tokens and falls back to light values.

**Options:**
- Where the kit lies:
  - A) `src/archiwista/web/nogat/`: the kit's four files and the marks of the four GUIs under Nogat's names; the kit's own `nogat-kit.json` is the manifest a unit test checks the copy against.
  - B) `web/vendor/nogat/` with entries in `vendor/vendor.json`. Rejected: the kit is the ecosystem's standard, like `schemas/nogat/`, not a third-party library; a second list of its hashes would be kept by hand beside the one the kit ships, and `vendor.json` asks a licence file of each library.
- How the page learns the addresses:
  - C) `GET /api/v1/session` answers `gui`, the table as the server read it at its start; the shell has the session before it draws.
  - D) `GET /health`. Rejected: polled every 2 to 15 s for the index state, while the table never changes during a run.
  - E) A route of its own. Rejected: a route and a command for a table the session's read gives already.
  - F) A value written into `index.html`. Rejected: the page is a static file, the same for every server.
- A table `gui` that cannot be used (not a table, an address that is not a non-empty string):
  - G) As every other key of the file (ADR-053 E): every command but `archiwista doctor` refuses to run, and the doctor names it.
  - H) Ignored, with a warning of the doctor. Rejected: two rules for one file, and a person who wrote the table expects the menu.
- Copying where the Clipboard API is missing or refused:
  - I) The kit's `copyHandoff` with a field of the card: the text lies in it selected, and the note asks for Ctrl+C.
  - J) The file only. Rejected: DEV-15.5, and a team server on the network is plain HTTP.

**Decision:** A, C, G and I.

1. **The kit.** `src/archiwista/web/nogat/` holds `nogat-app-menu.js`, `nogat-app-menu.css`, `nogat-handoff.js` and `nogat-kit.json` (kit 0.1.0) of Nogat `design/kit/`, and `marks/archiwista.svg`, `hydrograf.svg`, `hydrolog.svg` and `obserwator.svg` of `design/marks/`, all of Nogat `7786271`, byte for byte and never edited (DEV-15.6): a new kit is copied whole again. `tests/unit/test_vendor_integrity.py` checks each kit file against the copied `nogat-kit.json` and that only the marks lie beside them.
2. **The table.** `gui` of `nogat.toml` (`[nogat.gui]`; `[archiwista.gui]` before it, whole, as each key of ADR-053): each GUI's address by its registry name, absolute or a path on this host, as the file writes it; no default. It is read with the file (`SharedSettings.gui`); `archiwista serve` keeps it for its run (`app.state.gui`), `GET /api/v1/session` answers it as `gui` (`{}` without the table), and `archiwista doctor` names it with the table that gave it.
3. **The menu.** `<nogat-app-menu current="archiwista" marks="/static/nogat/marks/">` in the top bar after „Instrukcja” and before the session, where Nogat's shell has the theme switch, with the session's `gui` as its `apps`; its stylesheet follows `styles.css`. The element keeps the http and https addresses, draws nothing without another GUI and opens each in the tab `nogat-<name>`.
4. **The hand-off.** „Do Hydrologa” of the station card writes through `nogat-handoff.js` with its labels („Kopiuj do Hydrologa”, „Plik przekazania”) and notes: `downloadHandoff` saves `<subject>.handoff.json` (the name rule of DEV-15.5; an empty subject gives `archiwista`) in 2-space JSON with a final newline; `copyHandoff` writes the clipboard in a secure context, else or when refused fills a field under the buttons with the text selected. After a copy or a file the note links „Otwórz Hydrologa” to Hydrolog's address of the session's `gui`, in the tab `nogat-hydrolog`. The document stays the route's (ADR-052), and `archiwista stations handoff` prints it as before.
5. **Nogat's schemas.** `schemas/nogat/handoff-1.schema.json` (with `node_provenance`) and `error_registry.json` (the standard numbered 1.0) are Nogat's of `7786271`; `src/archiwista/_errors.py` is generated again (`STANDARD_VERSION` `"1.0"`; the codes are unchanged).

**Consequences:** `shared_settings.py` (`SharedGui`), `doctor.py`, `cli.py`, `server.py`, `app.py` and `api/session.py` (`SessionState.gui`); `web/index.html`, `web/src/shell.js` and `web/src/views/station-chart.js`; tests in `tests/unit/test_shared_settings.py`, `test_doctor.py` and `test_vendor_integrity.py`, `tests/e2e/test_shell.py` (the menu, and none without the table) and `tests/e2e/test_station_chart.py` (the file's text; the copy with „Otwórz Hydrologa”; the field without a Clipboard API, in Chromium and Firefox). Until Archiwista adopts Nogat's identity the menu shows the tokens' light fallbacks and Archiwista's variables of the same names (`--line`, `--text`, `--text-3`, `--accent-soft`, `--shadow-lg`). A deployment that wants the menu sets `[nogat.gui]` in the `nogat.toml` its server reads and restarts the server.
