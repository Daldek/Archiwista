# ADR-044: One job per row: a `check` and a `download` take the calls of all the lines, and the worker starts lighter

**Date:** 2026-10-26
**Status:** proposed (the author chose A and C on 2026-10-26; done on the topic branch `feature/kartograf-data-output`; accepted when the author approves and merges the branch; amends ADR-035 point 6, ADR-036 and ADR-037)

**Context:** After ADR-036 erratum 1 a plan of a report's row asks the source nothing, yet "Pobierz…" on a row of 32 per-sheet lines still waited about 30 s: each line was its own `check` job (ADR-035 point 6), each job a new worker process, two at a time (`MAX_NETWORK_JOBS`). A line cost about 1.4 s of process start (0.54 s importing `archiwista.jobs.worker`, 0.92 s with Kartograf) and bookkeeping, and a download did the same once more per line.

**Options:**
- A) Plan all the lines of a row in one `check` job, and run them in one `download` job: the job takes `calls[]`, keeps one plan per call, the download names the `plan_job` of the same calls. Changes the API, the index and the web.
- B) Kartograf's hint names several sheets in one command (a sheet list option), so a row becomes one line. A Kartograf CLI/API change; pasted lists of lines stay slow.
- C) Make the worker cheaper to start: lazy imports, no contract change. Saves part of each start, not the starts.
- D) Lengthen `PLAN_REFRESH_TTL_S` to the seven days of a report. Saves requests that ADR-036 erratum 1 already saved; an older per-sheet entry could override a report refreshed with "Sprawdź ponownie".

**Decision:** A and C.

1. **The request** (`POST /jobs`, `archiwista jobs start RODZAJ PRODUCENT --store ID --call JSON [--call JSON …] [--plan ZADANIE]`): `calls` is 1 to `MAX_JOB_CALLS` (1000) objects `{"command", "options"}` of one producer, in their order; `command` and `options` at the top level are gone (no alias). Each call is checked before a job exists as one was before; a refusal of one call names its place as `details.call`. `plan_job` must be a `check` job of the same store, producer and calls in the same order (options compared as sorted JSON), else `409 plan_mismatch`.
2. **The check** plans each call in turn in one worker and keeps a plan per call (index table `plans` keyed by job and `call`, `SCHEMA_VERSION` 12). A call the producer refuses, or none of whose positions could be checked, keeps no plan; then the job ends `partial`, and fails only when no call was planned (the error of the first). Its result has the totals and `calls[]`, what became of each. `GET /jobs/{job}/plan` returns the totals and the plan of each planned call; a job that is no `check` is `404 job.no_plan`.
3. **The download** runs the calls in turn in one worker; with `plan_job` a call without a kept plan is skipped (`not_planned`), one whose plan has nothing to download too (`nothing_to_download`). Progress events carry `call` and `calls` (`PROTOCOL_VERSION` 10). A call refused, or none of whose units succeeded, failed; the job ends `partial` when some calls or units failed and fails when every call run failed (the error of the first). The rescan reads the files of all its calls.
4. **The web** (`views/plan.js`) starts one check with all the lines of the window; a refusal naming `details.call` marks that line and the check is asked again without it. "Pobierz" starts one download with the same calls and `plan_job`; the top bar shows one entry per row, its share `(call + current/total) / calls`.
5. **C:** `archiwista.jobs` loads its names on first use, so a worker never imports the supervisor or the scheduler; the preview runners import `previews.build` and `previews.warm` inside the function.

**Consequences:**
- Measured 2026-10-26 with the stand-in producer, the real supervisor (two network jobs) and real workers, single runs: a 32-line row planned in 11.55 s before (32 jobs) and 0.66 s after (1 job). Importing the worker: 0.530 s and 83 Archiwista modules before (median of 9), 0.365 s and 51 after.
- One worker holds a row: two rows plan at once, not two lines; a long row is cancelled, retried and listed as one job, and a retry of a cancelled download fetches only what its producer has not written yet.
- A client of `POST /jobs` sends `calls`; a job of the old shape is refused with `400 validation_error`. Jobs and plans kept before are dropped with the index rebuild (SPEC 4.4).
- B and D stay open; B would shorten the lines Kartograf prints, not the jobs.
