/**
 * „Zadania” (docs/SPEC.md 6.2, 6.5 f and 5.6; plan v0.4 T9, ADR-047; A12 of
 * plan 2026-10-25): the queue and history of everyone's background jobs,
 * newest first, read again every 2 s while one waits or runs and every 15 s
 * otherwise, while the page is visible.
 *
 * Each job shows its kind and what it works on, who started it, its state
 * and its progress or when it ended, the positions another download fetches
 * for it (`taken`) and why it failed. „Szczegóły” follows its events
 * (progress, notices, its summary or why it failed), „Dziennik” shows the end
 * of its log, „Anuluj” stops one that waits or runs (for whoever started it
 * and administrators), „Ponów” runs one that did not succeed again as a job
 * of the session, also one „przerwane” by a restart of the server, and is
 * disabled with its reason for a job the session may not retry (a store's
 * scan, outlines or link check and the scan of every project's data folder
 * without the role `admin`, a job that writes a store without „zapis do
 * magazynu”). A job of a
 * project the session does not see shows its kind, who and its progress only
 * (`hidden`), with nothing to open. The filters „Wszystkie”, „Trwa”, „Błędy”
 * and „Moje” keep the address (`filter`).
 */

import { cancelJob, getJobLog, listJobs, retryJob } from "../api.js";
import { useApp } from "../context.js";
import { bytes, int, plural, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { T, t } from "../labels/index.js";
import { jobs as L } from "../labels/jobs.js";
import { setParams } from "../router.js";
import {
  html,
  Icon,
  loadStylesheet,
  ProblemView,
  Seg,
  Spinner,
  Tech,
  useEffect,
  useId,
  useState,
} from "../ui.js";
import {
  actorName,
  Badge,
  downloadSummary,
  JobStatus,
  loadCardStyles,
  projectSummary,
  storeName,
  TakenList,
  useJob,
} from "./cards.js";

await Promise.all([loadCardStyles(), loadStylesheet(new URL("./jobs.css", import.meta.url))]);

/** Jobs of one page, and of the longest list the view reads (the API's limit). */
const PAGE = 50;
const MAX_PAGE = 200;
const BUSY_MS = 2000;
const IDLE_MS = 15000;
const ACTIVE = new Set(["queued", "running"]);
/** States „Błędy” keeps: the jobs that did not succeed, but by a cancel. */
const ERRORS = new Set(["failed", "partial", "interrupted"]);
/** States of a job „Ponów” runs again, as the server's `RETRY_STATES`. */
const RETRY = new Set(["partial", "failed", "interrupted", "cancelled"]);
/** Kinds whose retry writes a store: they need the permission to write the stores. */
const WRITES = new Set(["download", "project_download", "project_repin"]);
/** Kinds of a store's jobs, whose retry is an administrator's (`store.scan`), as the server's `STORE_SCAN_KINDS`. */
const STORE_SCANS = new Set(["scan", "footprints", "link_check"]);
const PROJECT_KINDS = new Set(["project_download", "project_repin", "project_check", "project_verify"]);
const FILTERS = ["all", "active", "errors", "mine"];
const LEVELS = {
  queued: "plain",
  running: "info",
  succeeded: "ok",
  partial: "warn",
  failed: "bad",
  interrupted: "bad",
  cancelled: "plain",
};

/**
 * „Zadania” (route `jobs`).
 *
 * @param {{route: import("../router.js").Route}} props - Parameter `filter`:
 *   `active`, `errors` or `mine`; every job without it.
 */
export default function JobsView({ route }) {
  const { session } = useApp();
  const filter = FILTERS.includes(route.params.filter) ? route.params.filter : "all";
  const [limit, setLimit] = useState(PAGE);
  const queue = useQueue(limit);
  const shown = queue.page ? queue.page.items.filter((job) => kept(filter, job, session)) : [];
  let list;
  if (!queue.page) list = queue.problem ? null : html`<${Spinner} />`;
  else if (shown.length) {
    list = html`<ul class="jobs-list" aria-label=${L.list}>${shown.map(
      (job) => html`<${JobRow} key=${job.id} job=${job} refresh=${queue.refresh} />`,
    )}</ul>`;
  } else list = html`<p class="hint">${L.empty[filter]}</p>`;
  return html`<div class="cards-page jobs-page">
    <header class="jobs-head">
      <h1 class="view-title">${L.title}</h1>
      <${Seg} label=${L.filters_label} value=${filter}
        onChange=${(value) => setParams({ filter: value === "all" ? null : value })}
        options=${FILTERS.map((value) => ({ value, label: L.filters[value], title: L.filter_titles[value] }))} />
    </header>
    ${queue.problem ? html`<${ProblemView} problem=${queue.problem} />` : null}
    ${list}
    ${queue.page?.next_cursor
      ? limit < MAX_PAGE
        ? html`<button type="button" class="btn sm jobs-more" onClick=${() => setLimit(Math.min(MAX_PAGE, limit + PAGE))}>
            ${L.more}</button>`
        : html`<p class="hint">${t(L.oldest, { count: int(MAX_PAGE) })}</p>`
      : null}
  </div>`;
}

/**
 * The newest `limit` jobs of the queue, read again while the page is visible:
 * every 2 s while one of them waits or runs, else every 15 s; `refresh` reads
 * them at once (after a cancel or a retry).
 *
 * @param {number} limit
 * @returns {{page: import("../types.js").JobList|null,
 *   problem: import("../types.js").Problem|null, refresh: () => void}}
 */
function useQueue(limit) {
  const [state, setState] = useState({ page: null, problem: null });
  const [round, setRound] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    let busy = false;
    let timer = null;
    const look = async () => {
      clearTimeout(timer);
      timer = null;
      if (stopped || busy || document.visibilityState !== "visible") return;
      busy = true;
      let page = null;
      try {
        page = await listJobs({ limit }, { signal: controller.signal });
        if (!stopped) setState({ page, problem: null });
      } catch (error) {
        if (stopped) return;
        if (!error.problem) throw error;
        setState((now) => ({ ...now, problem: error.problem }));
      } finally {
        busy = false;
      }
      if (stopped) return;
      timer = setTimeout(look, page?.items.some((job) => ACTIVE.has(job.state)) ? BUSY_MS : IDLE_MS);
    };
    look();
    document.addEventListener("visibilitychange", look);
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
      document.removeEventListener("visibilitychange", look);
    };
  }, [limit, round]);
  return { ...state, refresh: () => setRound((n) => n + 1) };
}

/** Whether a filter keeps a job. */
function kept(filter, job, session) {
  if (filter === "active") return ACTIVE.has(job.state);
  if (filter === "errors") return ERRORS.has(job.state);
  if (filter === "mine") return mine(job, session);
  return true;
}

/** Whether the session's person started a job (also through an agent). */
function mine(job, session) {
  return job.actor_kind !== "scheduler" && job.actor === session.actor;
}

/**
 * A job of the list: what, who, its state and progress, what can be done.
 *
 * @param {{job: import("../types.js").JobDetail, refresh: () => void}} props
 */
function JobRow({ job, refresh }) {
  const { session, health } = useApp();
  const titleId = useId();
  const reasonId = useId();
  const [open, setOpen] = useState(null);
  const [acting, setActing] = useState(null);
  const [problem, setProblem] = useState(null);
  const [retried, setRetried] = useState(null);
  const kind = capitalize(T.common.job_kind[job.kind] ?? job.kind);
  const active = ACTIVE.has(job.state);
  const who = whoName(job, session);
  const act = async (name, call) => {
    setActing(name);
    setProblem(null);
    try {
      const answer = await call(job.id);
      if (name === "retry") setRetried(answer.id);
      refresh();
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
    } finally {
      setActing(null);
    }
  };
  const toggle = (part) => setOpen(open === part ? null : part);
  const about = job.hidden ? null : subject(job, health);
  return html`<li class="jobs-item" data-job=${job.id} data-state=${job.state} aria-labelledby=${titleId}>
    <div class="jobs-row">
      <${Badge} level=${LEVELS[job.state] ?? "plain"}>${T.common.job_state[job.state] ?? job.state}</${Badge}>
      <div class="jobs-main">
        <p class="jobs-title" id=${titleId}>
          <${Tech} value=${[["job", job.id], ["kind", job.kind]]}><b>${kind}</b></${Tech}>
          ${job.hidden
            ? html`<span class="faint" title=${L.hidden_title}> · ${L.hidden}</span>`
            : about ? html`<span> · ${about}</span>` : null}
        </p>
        <p class="jobs-meta">
          <span class="jobs-who" title=${t(L.who_label, { who })}>
            <${Tech} value=${[["actor", job.actor], ["actor_kind", job.actor_kind]]}>${who}</${Tech}>
          </span>
          <span class="tabular">${when(job)}</span>
        </p>
        ${active ? html`<${Progress} progress=${job.progress} running=${job.state === "running"} label=${kind} />` : null}
        ${job.result?.taken?.length ? html`<${TakenList} taken=${job.result.taken} />` : null}
        ${job.error ? html`<p class="jobs-error">${job.error.detail}</p>` : null}
      </div>
      ${job.hidden
        ? null
        : html`<div class="jobs-actions" role="group" aria-label=${L.actions.label}>
            ${active && (mine(job, session) || session.roles.includes("admin"))
              ? html`<button type="button" class="btn sm" disabled=${acting !== null} title=${L.actions.cancel_title}
                  onClick=${() => act("cancel", cancelJob)}>
                  <${Icon} name="x" size=${13} />${acting === "cancel" ? L.actions.cancelling : L.actions.cancel}
                </button>`
              : null}
            ${RETRY.has(job.state) ? html`<${RetryButton} job=${job} reasonId=${reasonId}
                busy=${acting !== null} onRetry=${() => act("retry", retryJob)} />` : null}
            <button type="button" class="btn ghost sm" aria-expanded=${open === "details" ? "true" : "false"}
              onClick=${() => toggle("details")}>
              <${Icon} name="info" size=${13} />${open === "details" ? L.actions.details_hide : L.actions.details}
            </button>
            ${job.started_at
              ? html`<button type="button" class="btn ghost sm" aria-expanded=${open === "log" ? "true" : "false"}
                  onClick=${() => toggle("log")}>
                  <${Icon} name="file" size=${13} />${open === "log" ? L.actions.log_hide : L.actions.log}
                </button>`
              : null}
          </div>`}
    </div>
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
    ${retried ? html`<p class="hint" role="status">${t(L.actions.retried, { job: retried })}</p>` : null}
    ${open === "details" ? html`<${JobDetails} job=${job} />` : null}
    ${open === "log" ? html`<${JobLogView} job=${job} />` : null}
  </li>`;
}

/**
 * „Ponów”, disabled with its reason when the session may not retry the job
 * (the server would refuse it too).
 */
function RetryButton({ job, reasonId, busy, onRetry }) {
  const { session } = useApp();
  const reason = retryRefusal(job, session);
  return html`<button type="button" class="btn sm" disabled=${busy || reason !== null}
      title=${reason ?? L.actions.retry_title}
      aria-describedby=${reason ? reasonId : null} onClick=${onRetry}>
      <${Icon} name="rotate" size=${13} />${L.actions.retry}
    </button>
    ${reason ? html`<span class="visually-hidden" id=${reasonId}>${reason}</span>` : null}`;
}

/**
 * Why the session may not retry a job, as `services.jobs.retry` decides; `null`: it may.
 * A store's scan, outlines or link check and the scan of every project's data folder
 * are an administrator's (`store.scan`); a job that writes a store needs „zapis do
 * magazynu”.
 */
function retryRefusal(job, session) {
  const scansStores = STORE_SCANS.has(job.kind) || (job.kind === "own_scan" && !job.params?.project);
  if (scansStores && !session.roles.includes("admin")) return L.actions.retry_admin_only;
  if (WRITES.has(job.kind) && !session.store_write) return L.actions.retry_no_store_write;
  return null;
}

/** The progress of a job that waits or runs: a bar and „3 z 7”. */
function Progress({ progress, running, label }) {
  if (!progress) return running ? html`<div class="job-progress"><progress aria-label=${label}></progress></div>` : null;
  const known = progress.total > 0;
  return html`<div class="job-progress">
    ${known
      ? html`<progress key="known" max=${progress.total} value=${progress.current} aria-label=${label}></progress>`
      : html`<progress key="unknown" aria-label=${label}></progress>`}
    <span class="tabular">${t(L.progress, { current: int(progress.current), total: int(progress.total) })}</span>
  </div>`;
}

/** „Szczegóły”: the job's events followed (progress, notices, summary, failure). */
function JobDetails({ job }) {
  const followed = useJob();
  useEffect(() => followed.follow(job.id, job.kind), [job.id]);
  let summary;
  if (job.kind === "download") summary = downloadSummary;
  else if (PROJECT_KINDS.has(job.kind)) summary = projectSummary;
  return html`<div class="jobs-details"><${JobStatus} job=${followed} summary=${summary} /></div>`;
}

/** „Dziennik”: the end of the job's log, its worker's standard error. */
function JobLogView({ job }) {
  const log = useResource((signal) => getJobLog(job.id, { signal }), [job.id]);
  if (log.error) return html`<div class="jobs-log"><${ProblemView} problem=${log.error.problem} compact /></div>`;
  if (!log.data) return html`<div class="jobs-log"><${Spinner} /></div>`;
  return html`<div class="jobs-log">
    ${log.data.truncated ? html`<p class="hint">${t(L.log.truncated, { size: bytes(log.data.size_bytes) })}</p>` : null}
    ${log.data.text
      ? html`<pre class="jobs-log-text" tabindex="0" aria-label=${t(L.log.label, { job: job.id })}>${log.data.text}</pre>`
      : html`<p class="hint">${L.log.empty}</p>`}
  </div>`;
}

/** Who started a job, for people: „Ty” for the session's person. */
function whoName(job, session) {
  if (job.actor_kind === "scheduler") return L.who.scheduler;
  const own = job.actor === session.actor;
  if (job.actor_kind === "agent") return own ? L.who.you_agent : t(L.who.agent, { actor: job.actor });
  return own ? L.who.you : actorName(job.actor);
}

/** When a job waits since, runs since, or ended. */
function when(job) {
  if (job.state === "queued") return t(L.time.queued, { time: stamp(job.created_at) });
  if (job.state === "running") return t(L.time.running, { time: stamp(job.started_at ?? job.created_at) });
  return t(L.time.ended, { time: stamp(job.finished_at ?? job.created_at) });
}

/** What a job works on: its store, project, calls or objects; `null`: nothing to say. */
function subject(job, health) {
  const params = job.params ?? {};
  const store = job.store ? t(L.subject.store, { store: storeName(health, job.store) }) : null;
  const project = params.project ? t(L.subject.project, { project: params.project }) : null;
  if (job.kind === "check" || job.kind === "download") return [calls(params), store].join(" · ");
  if (job.kind === "scan") {
    return [store, params.mode === "full" ? L.subject.full_scan : null, params.segment].filter(Boolean).join(" · ");
  }
  if (job.kind === "link_check") return [store, params.slot].filter(Boolean).join(" · ");
  if (job.kind === "own_scan") return project ?? L.subject.every_project;
  if (job.kind === "availability") {
    return t(L.subject.availability, { producer: params.producer, product: params.product });
  }
  if (job.kind === "preview") {
    const refs = params.refs?.length ?? 0;
    return t(L.subject.refs, { count: int(refs), objects: plural(refs, L.subject.objects) });
  }
  if (job.kind === "preview_warm") {
    const warmed = params.store ? t(L.subject.store, { store: storeName(health, params.store) }) : null;
    return [warmed, params.product, project].filter(Boolean).join(" · ") || null;
  }
  if (job.kind === "project_repin" && params.tasks?.length === 1) {
    return t(L.subject.task, { project: params.project, task: params.tasks[0] });
  }
  return project ?? store;
}

/** The producer's command of a job of calls, with the number of its lines. */
function calls(params) {
  const lines = params.calls ?? [];
  const values = { producer: params.producer, command: lines[0]?.command ?? "" };
  if (lines.length < 2) return t(L.subject.calls, values);
  return t(L.subject.calls_many, { ...values, count: int(lines.length), lines: plural(lines.length, L.subject.lines) });
}

function capitalize(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}
