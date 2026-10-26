# ADR-038: Job controls: cancel across processes, retry as a new job, the log's end

**Date:** 2026-10-26
**Status:** proposed (done on the topic branch `feature/kartograf-data-output`, step A6 of the plan `docs/plans/2026-10-25-archiwista-next.md`, whose approval is delegated; accepted when the author approves and merges the branch)

**Context:** v0.3 "Actions" runs downloads that last minutes to hours (SPEC 5.6, 13). A person or an agent must be able to stop a job, run again one that a server restart interrupted ("przerwane" with "Ponów", criterion 5), and read why a job failed (SPEC 9.2: `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retry`, `GET /jobs/{id}/log`; AGENT_API parity: `archiwista jobs list|show|cancel|retry|log`). `JobSupervisor.cancel` stopped only a job of its own supervisor: each process that runs jobs has one (the server; `archiwista jobs start`, `reindex` and `preview --build` in the foreground), so the command line could not stop a server's job, nor the interface a job started at the terminal. A retry must not let a person do what they may not start, and a log may name files of projects a person does not see (a `preview` job holds the refs of every request that joined it).

**Options:**
- Cancel across processes:
  - A) A column of the job in the index that the owning supervisor reads. Rejected: a new `SCHEMA_VERSION` (a rebuild of the index) for a request that lives seconds.
  - B) A request file `<jobs>/<id>.cancel` beside the job's log; every supervisor looks for the requests of its own jobs.
  - C) Signal the worker from the requesting process. Rejected: the worker's pid is not recorded, a plain interrupt would end the job `interrupted`, not `cancelled`, and a waiting job has no worker.
- Retry:
  - D) Call the start of each kind again (the route's own checks). Rejected: the preview build needs the render pool and the request's content keys, the starts live in different layers, and the parameters were checked when the job was first started.
  - E) Submit the kind, store and parameters again as a new job of the person, asking again only what the kind needs of the person.

**Decision:** B and E.

1. **Cancel** (`JobSupervisor.cancel`). A job waiting under the supervisor ends `cancelled` at once, without a worker; a running worker of the supervisor is interrupted as Ctrl+C would (SIGINT, CTRL_BREAK_EVENT on Windows), killed after the stop timeout (30 s), and its job ends `cancelled` when it is gone (a download reads the slots of its units again first, ADR-037). A job another live supervisor waits for or runs, in this process or another one, gets the request file; each supervisor's thread looks for the requests of its own jobs every `CANCEL_POLL_S` (0.5 s) and carries them out the same way. The file goes when the job ends, and `prune` removes the requests of jobs that are not active. A job whose supervising process is gone is `interrupted` first (`recover`); a finished job is returned unchanged.
2. **Who may cancel.** Whoever started the job (its `actor`: an agent acts as the person who issued its token) and administrators: the new action `job.cancel` of the `Authorizer` (`403 permission_denied`). A job that has ended is `409 conflict`, reason `job_finished`, with the job in `details.job`. The answer is `202` with the job as it is right after the request (`cancelled` when it waited, else still `running` until its worker stops).
3. **Retry** (`services/jobs.py`). A job that did not succeed (`partial`, `failed`, `interrupted`, `cancelled`) is submitted again with its kind, store and parameters as the person sees the job (a `preview` job with the refs of the projects they see), as a new job of the person (`202`, `Location` of the new job); the old job stays as it ended. A job that succeeded is `409`, reason `job_succeeded`; one still waiting or running `job_active`. What the kind needs of the person is asked again: a `download` needs `store.write` (SPEC 13 criterion 7: `403` and no job), a `snapshot` `project.write` of its project; the supervisor refuses the new job as any of its kind (a store no longer configured, offline mode, another job writing the store's index), and the worker checks the rest again. A download run again fetches only what the store still lacks (the producer keeps the versions it published).
4. **The log** (`JobSupervisor.log`, `GET /jobs/{job}/log`, `JobLog`). The end of the worker's standard error, its last MiB at most from the first line that starts in it (`truncated`, `size_bytes` of the whole log), read as the job runs; a job without a log (it never started a worker, or its log was pruned) is `404` (`job.no_log`). It is given to a person who sees the whole job (`JobSupervisor.sees_whole`): a `preview` job that also builds files of projects they do not see is `403`, because its log may name those files.
5. **Visibility first.** A job the session does not see is `404 not_found` for all three, as an unknown job (A-ADR-029); one place, `services.jobs.visible_job`, serves `GET /jobs/{job}`, its events, its plan and the controls.
6. **Command line.** `archiwista jobs list` (the filters of `GET /jobs`), `jobs show`, `jobs cancel` and `jobs log` print the routes' models with `--json` and exit `0`; `jobs retry` runs the new job in the foreground as `jobs start` does (its supervisor ends with the command) and exits with its outcome. The command acts as the local owner, an administrator.

**Consequences:**
- A cancel from another process takes effect within half a second plus the worker's stop; the answer shows the job still running.
- A retried job has a new id and its own events and log; the interface replaces the row of the old one with it.
- No column was added: `SCHEMA_VERSION` stays.
- A server and a command each hold one more thread per supervisor (the look for requests).
- Cooperative cancellation (KC-1) changes how the worker stops, not this protocol.
