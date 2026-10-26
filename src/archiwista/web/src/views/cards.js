/**
 * Pieces shared by the file card, the Projects view and the Store view:
 * problems with their fixes, a background job started here and followed
 * through its event stream (SSE), with the summaries of its result that the
 * plan window and the downloads of the top bar show too, links opening the
 * file card over the current view, labelled copy buttons, the stale-answer
 * note and the human names of statuses and coordinate systems (docs/SPEC.md
 * 6.1 „Przejrzystość”).
 */

import { watchJob } from "../api.js";
import { useApp } from "../context.js";
import { bytes, int, plural, stamp } from "../format.js";
import { cards as L } from "../labels/cards.js";
import { T, t } from "../labels/index.js";
import { Link, useRoute } from "../router.js";
import {
  html,
  Icon,
  loadStylesheet,
  ProblemView,
  Tech,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "../ui.js";

/** States after which a job changes no more. */
export const FINAL_STATES = new Set([
  "succeeded",
  "partial",
  "failed",
  "interrupted",
  "cancelled",
]);
/** States of a job that ended with its summary (`result`), as on the server. */
export const SUMMARY_STATES = new Set(["succeeded", "partial"]);
const SECONDS = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1 });
const SHORT_SECONDS = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2 });
const COPIED_MS = 1500;
/** States of a project's file a job's summary does not list: nothing to do. */
const QUIET_FILES = new Set(["ok", "current"]);
/** The badge of each other state of a project's file. */
const FILE_LEVELS = {
  missing: "bad",
  corrupt: "bad",
  newer: "info",
  added: "info",
  removed: "warn",
  unverifiable: "plain",
  check_failed: "bad",
  conflict: "bad",
};
/** The badge of each status of a download's file. */
const DOWNLOAD_FILE_LEVELS = { new: "ok", unchanged: "plain", relabeled: "info" };

/**
 * Load the stylesheet of the three views once; their modules await it, so
 * nothing renders unstyled.
 *
 * @returns {Promise<HTMLLinkElement>}
 */
export function loadCardStyles() {
  return loadStylesheet(new URL("./cards.css", import.meta.url));
}

/**
 * The human name of a coordinate system, e.g. `PL-1992` for `EPSG:2180`.
 *
 * @param {string} code - EPSG code as in the index.
 * @returns {string}
 */
export function crsName(code) {
  return L.crs[code] ?? t(L.crs_unknown, { code });
}

/**
 * A coordinate system for people with its EPSG code one click away.
 *
 * @param {{code: string|null}} props
 */
export function Crs({ code }) {
  if (!code) return T.common.empty;
  return html`<${Tech} value=${code}>${crsName(code)}</${Tech}>`;
}

/**
 * The producer's status of a project or task for people (Kartograf's words).
 *
 * @param {string|null} status - `ok`, `not_downloaded`, `missing`, `corrupt` or null.
 * @returns {string}
 */
export function statusName(status) {
  return status === null ? L.status.none : (L.status[status] ?? status);
}

/**
 * Severity class of a producer status: `ok`, `warn` (not downloaded, not
 * checked) or `bad` (missing or corrupt files).
 *
 * @param {string|null} status
 * @returns {"ok"|"warn"|"bad"}
 */
export function statusLevel(status) {
  if (status === "ok") return "ok";
  if (status === "missing" || status === "corrupt") return "bad";
  return "warn";
}

/**
 * The state of a pin for people.
 *
 * @param {import("../types.js").PinState} state
 * @returns {string}
 */
export function pinStateName(state) {
  return L.pin_state[state] ?? state;
}

/**
 * Who started a job, for people: `local` is the local owner.
 *
 * @param {string} actor - `Principal.id` of the job.
 * @returns {string}
 */
export function actorName(actor) {
  return T.common.actor[actor] ?? actor;
}

/**
 * A store's name from the shell's state, else its id.
 *
 * @param {import("../types.js").Health|undefined} health
 * @param {string} store
 * @returns {string}
 */
export function storeName(health, store) {
  return health?.stores.find((item) => item.store === store)?.name ?? store;
}

/**
 * A badge: a short state with a severity colour, never colour alone.
 *
 * @param {{level?: "ok"|"warn"|"bad"|"info"|"plain", title?: string, children: *}} props
 */
export function Badge({ level = "plain", title, children }) {
  return html`<span class=${`state-badge ${level}`} title=${title}>${children}</span>`;
}

/**
 * A link opening the file card over the current view (`file`, and
 * `file_version` for one version), keeping the view's own parameters.
 *
 * @param {{store: string, slot: string, version?: string|null, children: *}} props
 *   Other props go to the `<a>` element.
 */
export function FileLink({ store, slot, version = null, children, ...rest }) {
  const route = useRoute();
  const params = { ...route.params, file: `${store}/${slot}`, file_version: version };
  return html`<${Link} view=${route.view} params=${params} ...${rest}>${children}</${Link}>`;
}

/**
 * A button copying a text, with its visible name (`Kopiuj atrybucję`) and a
 * short confirmation for people and screen readers.
 *
 * @param {{text: string, label: string, primary?: boolean}} props
 */
export function CopyAction({ text, label, primary }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = () =>
    navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), COPIED_MS);
      },
      () => setCopied(false),
    );
  return html`<span class="copy-action">
    <button type="button" class=${primary ? "btn sm primary" : "btn sm"} onClick=${copy}>
      <${Icon} name=${copied ? "check" : "copy"} size=${13} />${label}
    </button>
    <span class="copy-state" role="status">${copied ? T.common.actions.copied : ""}</span>
  </span>`;
}

/**
 * A note that an answer comes from the index of an unavailable store.
 *
 * @param {{stores: import("../types.js").StaleStore[]}} props
 */
export function StaleNote({ stores }) {
  const { health } = useApp();
  if (!stores?.length) return null;
  return html`<div class="stale-note" role="note">
    ${stores.map(
      (item) => html`<p key=${item.store}>
        <${Icon} name="alert" size=${14} />
        ${item.indexed_at
          ? t(L.stale, { store: storeName(health, item.store), indexed_at: stamp(item.indexed_at) })
          : t(L.stale_never, { store: storeName(health, item.store) })}
      </p>`,
    )}
  </div>`;
}

/**
 * Problems with what is wrong, how to fix it, the technical values and links
 * to the file card or the project concerned.
 *
 * @param {{issues: import("../types.js").Issue[], store?: string|null,
 *   currentSlot?: string, currentProject?: string, empty?: boolean}} props -
 *   `store` makes slots links to their file cards; no link leads to
 *   `currentSlot` or `currentProject`, where the list already is; `empty`
 *   shows „Brak problemów” for an empty list.
 */
export function IssueList({ issues, store, currentSlot, currentProject, empty = true }) {
  if (!issues.length) return empty ? html`<p class="faint">${L.issues.none}</p>` : null;
  return html`<ul class="issues">
    ${issues.map(
      (issue, index) => html`<li key=${`${issue.code}:${issue.path}:${index}`} class="issue">
        <p class="issue-message"><${Icon} name="alert" size=${14} /><span>${issue.message}</span></p>
        <p class="issue-fix"><b>${L.issues.fix}</b>${" "}${issue.instruction}</p>
        <div class="issue-meta">
          <${Tech} value=${issueValues(issue)}>
            <span class="faint">${issueFound(issue)}</span>
          </${Tech}>
          ${store && issue.slot && issue.slot !== currentSlot
            ? html`<${FileLink} store=${store} slot=${issue.slot} class="btn ghost sm">
                <${Icon} name="file" size=${13} />${L.issues.open_file}</${FileLink}>`
            : null}
          ${issue.project && issue.project !== currentProject
            ? html`<${Link} view="projects" params=${{ project: issue.project }} class="btn ghost sm">
                <${Icon} name="folder" size=${13} />${t(L.issues.open_project, { project: issue.project })}
                ${issue.task ? html`<span class="faint">${t(L.issues.task, { task: issue.task })}</span>` : null}
              </${Link}>`
            : null}
        </div>
      </li>`,
    )}
  </ul>`;
}

function issueFound(issue) {
  const origin = issue.origin ? L.issues.origin[issue.origin] : null;
  if (!origin) return L.issues.details;
  return t(L.issues.found, { origin, at: stamp(issue.first_seen_at) });
}

function issueValues(issue) {
  const values = [["code", issue.code]];
  for (const name of ["path", "segment", "slot", "project", "task", "origin", "first_seen_at"]) {
    if (issue[name]) values.push([name, issue[name]]);
  }
  return values;
}

/**
 * The live state of a followed job.
 *
 * @typedef {object} JobEvents
 * @property {string} id
 * @property {string} state - The last state event.
 * @property {Object<string, *>|null} progress - The last progress event.
 * @property {Array<{level: string, code: string, message: string}>} notices
 * @property {Object<string, *>|null} result - Summary of a job that succeeded or
 *   ended `partial`.
 * @property {import("../types.js").JobFailure|null} error - Why it ended otherwise.
 * @property {import("../types.js").Problem|null} stream - The stream broke off.
 */

/**
 * Start a background job and follow its events (SSE, `watchJob`).
 *
 * `run(start, kind)` calls `start()`, an `api.js` POST answering
 * `JobDetail`; a `409 conflict` naming the running job (`details.job`) follows that job
 * instead, and any problem stays in `problem`. `follow(id, kind)` follows a
 * job started elsewhere (e.g. the scheduler's scan from `/health`).
 *
 * @param {{onEnd?: (state: {state: string, result?: Object<string, *>,
 *   error?: import("../types.js").JobFailure}) => void}} [options] - Called
 *   once with the final state event.
 * @returns {{id: string|null, kind: string|null, events: JobEvents|null,
 *   problem: import("../types.js").Problem|null, starting: boolean,
 *   running: boolean,
 *   run: (start: () => Promise<import("../types.js").JobDetail>, kind: string)
 *   => Promise<void>, follow: (id: string, kind: string) => void}}
 */
export function useJob({ onEnd } = {}) {
  const [followed, setFollowed] = useState({ id: null, kind: null });
  const [events, setEvents] = useState(null);
  const [problem, setProblem] = useState(null);
  const [starting, setStarting] = useState(false);
  const ended = useRef(onEnd);
  ended.current = onEnd;
  const id = followed.id;

  useEffect(() => {
    if (id === null) return undefined;
    setEvents({ id, state: "queued", progress: null, notices: [], result: null, error: null, stream: null });
    const update = (patch) =>
      setEvents((current) => (current?.id === id ? { ...current, ...patch(current) } : current));
    return watchJob(id, {
      onProgress: (data) => update(() => ({ progress: data })),
      onNotice: (data) => update((current) => ({ notices: [...current.notices, data] })),
      onState: (data) => {
        update(() => ({ state: data.state, result: data.result ?? null, error: data.error ?? null }));
        if (FINAL_STATES.has(data.state)) ended.current?.(data);
      },
      onError: (stream) => update(() => ({ stream })),
    });
  }, [id]);

  const follow = useCallback(
    (jobId, kind) =>
      setFollowed((current) => (current.id === jobId ? current : { id: jobId, kind })),
    [],
  );
  const run = useCallback(async (start, kind) => {
    setStarting(true);
    setProblem(null);
    try {
      const job = await start();
      follow(job.id, job.kind ?? kind);
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
      const running = error.problem.details?.job;
      if (running) follow(running.id, running.kind);
    } finally {
      setStarting(false);
    }
  }, []);
  const running = events !== null && !FINAL_STATES.has(events.state);
  return { id, kind: followed.kind, events, problem, starting, running, run, follow };
}

/**
 * A followed job for people: kind and state, progress, the job's Polish
 * notices, its summary or why it failed; a problem of starting it first.
 *
 * @param {{job: ReturnType<typeof useJob>, summary?: (events: JobEvents) => *}}
 *   props - `summary` renders the result of a job that succeeded or ended
 *   `partial` (default: the scan and footprints summaries).
 */
export function JobStatus({ job, summary = defaultSummary }) {
  const { events, problem } = job;
  if (!events && !problem) return null;
  return html`<div class="job-status">
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
    ${events ? html`<${JobEventsView} events=${events} summary=${summary} kind=${job.kind} />` : null}
  </div>`;
}

function JobEventsView({ events, summary, kind }) {
  const final = FINAL_STATES.has(events.state);
  const name = T.common.job_kind[kind] ?? kind;
  const title = t(L.job.title, {
    kind: capitalize(name ?? T.common.job_kind.scan),
    state: T.common.job_state[events.state] ?? events.state,
  });
  const progress = events.progress;
  const known = progress && progress.total > 0;
  const failure = events.error;
  const reason = failure?.details?.reason;
  const technical = failure ? [[T.common.technical.code, failure.code]] : [];
  if (reason) technical.push([T.common.technical.reason, reason]);
  return html`<div class=${`job ${events.state}`} aria-live="polite">
    <div class="job-head">
      ${final
        ? html`<${Icon} name=${events.state === "succeeded" ? "check" : "alert"} size=${15} />`
        : html`<span class="spinner" aria-hidden="true"></span>`}
      <${Tech} value=${[["job", events.id], ["state", events.state]]}><b>${title}</b></${Tech}>
    </div>
    ${!final
      ? html`<div class="job-progress">
          ${known
            ? html`<progress key="known" max=${progress.total} value=${progress.current} aria-label=${title}></progress>`
            : html`<progress key="unknown" aria-label=${title}></progress>`}
          ${progress ? html`<span class="tabular">${progressText(progress)}</span>` : null}
        </div>`
      : null}
    ${events.notices.length
      ? html`<div class="job-notices">
          <span class="section-title">${L.job.notices}</span>
          <ul>${events.notices.map(
            (notice, index) => html`<li key=${index} class=${notice.level}>
              <${Tech} value=${notice.code}>${notice.message}</${Tech}></li>`,
          )}</ul>
        </div>`
      : null}
    ${SUMMARY_STATES.has(events.state) ? summary(events) : null}
    ${events.error
      ? html`<p class="job-error">
          <${Tech} value=${technical}>${t(L.job.failed, {
            state: T.common.job_state[events.state] ?? events.state,
            detail: events.error.detail,
          })}</${Tech}>
        </p>`
      : null}
    ${failure?.hint && !failure.detail.includes(failure.hint)
      ? html`<p class="job-hint">${failure.hint}</p>`
      : null}
    ${events.stream && !final ? html`<${ProblemView} problem=${events.stream} compact />` : null}
  </div>`;
}

function progressText(progress) {
  if ("segment" in progress || "entries" in progress) {
    return t(L.job.scan_progress, {
      current: int(progress.current),
      total: int(progress.total),
      segments: plural(progress.total, T.common.units.segments),
      entries: int(progress.entries ?? 0),
      entries_word: plural(progress.entries ?? 0, L.job.entries),
    });
  }
  if ("written" in progress) {
    return t(L.job.footprints_progress, {
      current: int(progress.current),
      total: int(progress.total),
      written: int(progress.written),
      failed: int(progress.failed ?? 0),
    });
  }
  if ("phase" in progress) {
    return t(L.job.snapshot_progress, {
      current: int(progress.current),
      total: int(progress.total),
      phase: L.job.phases[progress.phase] ?? progress.phase,
    });
  }
  if ("files" in progress && "read" in progress) {
    return t(L.job.own_scan_progress, {
      current: int(progress.current),
      total: int(progress.total),
      folders: plural(progress.total, L.job.folders),
      files: int(progress.files),
      read: int(progress.read),
    });
  }
  if ("unit" in progress && "status" in progress) {
    const text = t(L.job.download_progress, {
      current: int(progress.current),
      total: int(progress.total),
      status: L.job.unit_status[progress.status] ?? progress.status,
    });
    return progress.unit ? `${text} · ${progress.unit}` : text;
  }
  return t(L.job.progress, { current: int(progress.current), total: int(progress.total) });
}

function defaultSummary(events) {
  const result = events.result;
  if (!result) return null;
  if ("versions_written" in result) {
    return html`<p class="job-summary">${t(L.job.scan_done, {
      seconds: seconds(result.seconds ?? 0),
      entries: int(result.entries),
      versions: int(result.versions_written),
      links: int(result.links_changed),
      missing: int(result.missing),
      removed: int(result.removed),
      issues: int(result.issues_added),
    })}</p>`;
  }
  if ("written" in result) {
    return html`<p class="job-summary">${t(L.job.footprints_done, {
      seconds: seconds(result.seconds ?? 0),
      written: int(result.written),
      total: int(result.total),
      failed: int(result.failed),
    })}</p>`;
  }
  if ("unreadable" in result && "projects" in result) {
    return html`<p class="job-summary">${t(L.job.own_scan_done, {
      seconds: seconds(result.seconds ?? 0),
      files: int(result.files),
      new: int(result.new),
      changed: int(result.changed),
      missing: int(result.missing),
      unreadable: int(result.unreadable),
      snapshots: int(result.snapshots),
      problems: int(result.problems),
    })}</p>`;
  }
  return null;
}

/**
 * The summary of a project's job, as `archiwista jobs show` says it: a
 * download's or a repin's tasks by outcome, each task with its pins or
 * errors; a check's or a verification's files by state, each file that is not
 * in order with the producer's text.
 *
 * @param {JobEvents} events
 */
export function projectSummary(events) {
  const result = events.result;
  if (!result) return null;
  if ("tasks" in result) {
    const named = Object.entries(L.job.task_outcome)
      .filter(([outcome]) => result.counts[outcome])
      .map(([outcome, word]) => `${word} ${int(result.counts[outcome])}`);
    return html`<div class="job-project">
      <p class="job-summary">${t(L.job.project_tasks, { tasks: int(result.tasks.length), counts: named.join(", ") })}</p>
      <ul class="job-project-list" aria-label=${L.job.project_tasks_title}>${result.tasks.map(
        (task) => html`<li key=${task.name}>
          <span class="mono">${task.name}</span>
          <${Badge} level=${task.outcome === "failed" ? "bad" : "ok"}>
            <${Tech} value=${[["outcome", task.outcome], ["code", task.code ?? "–"]]}>
              ${L.job.task_outcome[task.outcome] ?? task.outcome}</${Tech}></${Badge}>
          ${task.pinned.length ? html`<span class="faint">${t(L.job.task_pins, { count: int(task.pinned.length) })}</span>` : null}
          ${task.errors.map((text, index) => html`<span key=${index} class="bad-text">${text}</span>`)}
        </li>`,
      )}</ul>
    </div>`;
  }
  const named = Object.entries(L.job.project_file)
    .filter(([status]) => result.counts[status])
    .map(([status, word]) => `${word} ${int(result.counts[status])}`);
  const files = Object.values(result.counts).reduce((total, value) => total + value, 0);
  const notable = result.files.filter((file) => !QUIET_FILES.has(file.status));
  return html`<div class="job-project">
    <p class="job-summary">${t(L.job.project_files, {
      files: int(files),
      counts: named.join(", "),
      not_downloaded: int(result.not_downloaded.length),
    })}</p>
    ${notable.length
      ? html`<ul class="job-project-list" aria-label=${L.job.project_files_title}>${notable.map(
          (file, index) => html`<li key=${`${file.task}/${file.path}/${index}`}>
            <span class="mono">${file.task}</span>
            <${Tech} value=${[["unit", file.unit || "–"], ["status", file.status]]}><span class="mono">${file.path || file.unit || "–"}</span></${Tech}>
            <${Badge} level=${FILE_LEVELS[file.status] ?? "warn"}>${L.job.project_file[file.status] ?? file.status}</${Badge}>
            ${file.detail ? html`<span class="faint">${file.detail}</span>` : null}
          </li>`,
        )}</ul>`
      : null}
  </div>`;
}

/**
 * The summary of a download (`download`): its files by status, each with its
 * size, and its failed units, as `archiwista jobs show` says them.
 *
 * @param {JobEvents} events
 */
export function downloadSummary(events) {
  const result = events.result;
  if (!result) return null;
  const statuses = L.job.download_file_status;
  const counts = Object.entries(statuses).map(([status, word]) => `${word} ${int(result.counts[status] ?? 0)}`);
  const files = Object.values(result.counts).reduce((total, value) => total + value, 0);
  const failed = result.items.filter((item) => item.status === "failed");
  return html`<div class="job-download">
    <p class="job-summary">${t(L.job.download_files, { files: int(files), counts: counts.join(", "), failed: int(result.failed) })}</p>
    ${result.files.length
      ? html`<ul class="job-files" aria-label=${L.job.download_files_title}>${result.files.map(
          (file) => html`<li key=${file.path}>
            <${Tech} value=${[["version_path", file.version_path ?? "–"], ["sha256", file.sha256]]}><span class="mono">${file.path}</span></${Tech}>
            <${Badge} level=${DOWNLOAD_FILE_LEVELS[file.status] ?? "plain"}>${statuses[file.status] ?? file.status}</${Badge}>
            <span class="faint tabular">${bytes(file.size_bytes)}</span>
          </li>`,
        )}</ul>`
      : null}
    ${failed.length
      ? html`<div class="job-failed">
          <span class="section-title">${L.job.download_failed}</span>
          <ul>${failed.map(
            (item) => html`<li key=${item.id}><${Tech} value=${[["code", item.code ?? "–"], ["reason", item.reason ?? "–"]]}>
              <span class="mono">${item.id}</span></${Tech}>${item.message ? ` ${item.message}` : ""}</li>`,
          )}</ul>
        </div>`
      : null}
  </div>`;
}

/**
 * Seconds for people: `0,04` below a second, `12,3` above.
 *
 * @param {number} value
 * @returns {string}
 */
export function seconds(value) {
  return (value < 1 ? SHORT_SECONDS : SECONDS).format(value);
}

function capitalize(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}
