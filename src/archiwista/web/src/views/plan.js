/**
 * The „Okno planu” of a download (docs/SPEC.md 6.1 „Plan przed akcją”, 6.5 h,
 * UC-15; plan 2026-10-25 A11; ADR-043, ADR-044): what a run of the producer's
 * commands would do in a configured store, and then the run.
 *
 * The variant's lines in the chosen format (`commands`; nothing is chosen
 * when the variant has no default format), or one pasted line, are read into
 * calls (`POST /commands/parse`), and one `check` job plans them all (`POST
 * /jobs` with every call read, then `GET /jobs/{job}/plan` once it ends):
 * nothing is written. A line refused before the job (a line not read, an
 * option the producer refuses: the refusal names its `details.call`) is left
 * out of it and named with its problem, and so is a line whose check failed
 * (`result.calls` of the job). The window shows the plans together: the
 * positions by status, what a run downloads and its size („co najmniej …”
 * when the producer tells only some sizes, „rozmiar nieznany” when it tells
 * none, never 0), the store with the producer's directory, each position with
 * the ones the producer would refuse to write, and each command line to copy.
 * „Pobierz” starts one `download` of all the lines (`plan_job`: each line
 * fetches what was shown) and hands it to the downloads of the shell
 * (downloads.js), which follow it to its files, its failed units and the
 * lines it failed or skipped; above 5 GB or 500 positions it asks to be
 * confirmed first (SPEC 10.3). A session that may not write the stores
 * (`store_write`) sees the plan with the action disabled and the reason.
 *
 * The shell opens the window (`openPlan` of downloads.js), so it outlives the
 * view. Planning and the confirmation are modal; once something started the
 * window is not, and the map and the other views stay usable: „Zwiń” hides
 * it (the list under the top bar's „Pobieranie” shows it again), „Zamknij”
 * and `Esc` close it, at any time and without cancelling anything. A download
 * stops only by its „Anuluj pobieranie”.
 *
 * „Dodaj jako zadanie projektu” adds the one call as a task of a project of
 * the producer in the same store that the session may change (`POST
 * /projects/{project}/tasks`, checked without the network), and with
 * something to download starts that project's download of the task instead
 * (`POST /projects/{project}/jobs`), which downloads and pins it. When the
 * option cannot be had it says why: several lines, no project of the producer
 * in the store, none the session may change, a line not read.
 */

import {
  addProjectTask,
  getJobPlan,
  listProjects,
  parseCommand,
  startJob,
  startProjectJob,
  watchJob,
} from "../api.js";
import { useApp } from "../context.js";
import { CancelDownload, downloadActive, DownloadStatus, useDownloads } from "../downloads.js";
import { bytes, count, int, plural } from "../format.js";
import { useResource } from "../hooks.js";
import { actions } from "../labels/actions.js";
import { t } from "../labels/index.js";
import { Link } from "../router.js";
import {
  CopyButton,
  html,
  Icon,
  loadStylesheet,
  ProblemView,
  Seg,
  Spinner,
  Tech,
  useEffect,
  useId,
  useRef,
  useState,
} from "../ui.js";
import { Badge, FINAL_STATES, loadCardStyles, SUMMARY_STATES } from "./cards.js";

await loadCardStyles();
await loadStylesheet(new URL("./plan.css", import.meta.url));

const L = actions.plan;
/** A run above either asks to be confirmed (SPEC 10.3). */
const LARGE_BYTES = 5e9;
const LARGE_POSITIONS = 500;
/** Statuses of a plan's positions, in the server's order (`PLAN_STATUSES`). */
const STATUSES = ["current", "newer", "missing", "unverifiable", "check_failed"];
const LEVELS = { current: "ok", newer: "info", missing: "info", unverifiable: "plain", check_failed: "bad" };

/**
 * The plan window of one variant of a report's row, or of a pasted line.
 *
 * @param {object} props
 * @param {number} props.windowKey - The shell's key of the window (`openPlan`).
 * @param {boolean} props.visible - Shown, or hidden by „Zwiń” or another window.
 * @param {string} props.producer
 * @param {{id: string, name: string}} props.store - Where the run writes.
 * @param {string} props.title - What is downloaded, e.g. „NMT · 2023 · PL-2000”.
 * @param {import("../types.js").AvailabilityVariant|null} [props.variant] - Its
 *   lines by format; none with `line`.
 * @param {string|null} [props.line] - One pasted line of the producer (no format
 *   to choose).
 * @param {() => void} props.onClose
 * @param {() => void} props.onMinimise - Hide the window; what it started goes on.
 */
export function DownloadPlan({
  windowKey,
  visible,
  producer,
  store,
  title,
  variant = null,
  line = null,
  onClose,
  onMinimise,
}) {
  const { session } = useApp();
  const downloads = useDownloads();
  const titleId = useId();
  const dialog = useRef(null);
  // The last state of each run, also once removed from the list of downloads.
  const seen = useRef(new Map());
  const [format, setFormat] = useState(variant?.default_format ?? null);
  const lines = line !== null ? [line] : format === null ? null : (variant.commands[format] ?? []);
  const check = usePlans(producer, store.id, lines);
  const items = check.items;
  const [confirmed, setConfirmed] = useState(false);
  const [runs, setRuns] = useState(null);
  const projects = useResource((signal) => listProjects({ store: store.id }, { signal }), [store.id]);
  const [task, setTask] = useState({ on: false, project: "", name: "" });
  const [added, setAdded] = useState(null);
  const sum = planSum(check.info);
  const planned = check.ended;
  const large = sum.todo > LARGE_POSITIONS || sum.known > LARGE_BYTES;
  const allowed = Boolean(session?.store_write);
  const offer = taskOffer(projects, producer, store, lines, items);
  const call = items[0]?.call ?? null;
  const asTask = task.on && offer.reason === null;
  const fetching = planned && sum.todo > 0 && allowed;
  const followed = (run) => {
    if (!run.job) return null;
    const item = downloads.entries.find((entry) => entry.id === run.job.id) ?? seen.current.get(run.job.id) ?? null;
    if (item) seen.current.set(run.job.id, item);
    return item;
  };
  const ranAll = runs !== null && runs.every((run) => run.problem || (run.job && isOver(followed(run))));
  const settled = ranAll || (added?.state === "added" && !added.download);
  const started = runs !== null || (added !== null && added.state !== "failed");
  const taskReady = Boolean(call) && task.project !== "" && task.name.trim() !== "";
  const ready = asTask
    ? planned && taskReady && (!fetching || !large || confirmed) && !started
    : planned && sum.todo > 0 && allowed && (!large || confirmed) && !started;
  // Modal while planning; not once something started, so the page stays usable.
  useEffect(() => {
    const element = dialog.current;
    if (!visible) {
      if (element.open) element.close();
      return;
    }
    const modal = !started;
    if (element.open && element.matches(":modal") === modal) return;
    if (element.open) element.close();
    if (modal) element.showModal();
    else element.show();
  }, [visible, started]);
  useEffect(() => {
    const element = dialog.current;
    return () => {
      if (element.open) element.close();
    };
  }, []);
  useEffect(() => {
    if (offer.options.length === 1 && task.project === "") setTask((now) => ({ ...now, project: offer.options[0].project }));
  }, [offer.options.length]);
  const choose = (value) => {
    if (started) return;
    setFormat(value);
    setConfirmed(false);
  };
  const record = (index, patch) =>
    setRuns((current) => current.map((run, place) => (place === index ? { ...run, ...patch } : run)));
  const download = async () => {
    setRuns([{ key: "download", kind: "download", job: null, problem: null }]);
    try {
      const job = await startJob({
        kind: "download",
        producer,
        store: store.id,
        calls: check.calls,
        plan_job: check.job.id,
      });
      downloads.track(job, { title, window: windowKey });
      record(0, { job });
    } catch (error) {
      if (!error.problem) throw error;
      record(0, { problem: error.problem });
    }
  };
  const addTask = async () => {
    const name = task.name.trim();
    const chosen = offer.options.find((item) => item.project === task.project);
    setAdded({ state: "adding", download: fetching, name, project: chosen, problem: null });
    try {
      await addProjectTask(task.project, { name, command: call.command, options: call.options, producer });
    } catch (error) {
      if (!error.problem) throw error;
      setAdded({ state: "failed", download: fetching, name, project: chosen, problem: error.problem });
      return;
    }
    if (fetching) setRuns([{ key: "project", kind: "project_download", job: null, problem: null }]);
    setAdded({ state: "added", download: fetching, name, project: chosen, problem: null });
    if (!fetching) return;
    try {
      const job = await startProjectJob(task.project, { kind: "download", tasks: [name] });
      downloads.track(job, { title, window: windowKey });
      record(0, { job });
    } catch (error) {
      if (!error.problem) throw error;
      record(0, { problem: error.problem });
    }
  };
  const submit = (event) => {
    event.preventDefault();
    if (ready) (asTask ? addTask : download)();
  };
  const reason = !planned || !sum.plans.length ? null : !sum.todo ? L.nothing : !allowed ? L.no_write : null;
  const label = asTask
    ? fetching
      ? t(L.submit_task_download, { count: int(sum.todo), positions: plural(sum.todo, L.positions_accusative) })
      : L.submit_task
    : planned
      ? t(L.submit, { count: int(sum.todo), positions: plural(sum.todo, L.positions_accusative) })
      : L.submit_unplanned;
  return html`<dialog class="plan-window" ref=${dialog} aria-labelledby=${titleId}
    onCancel=${(event) => {
      event.preventDefault();
      onClose();
    }}
    onKeyDown=${(event) => {
      if (event.key !== "Escape") return;
      // Esc closes this window only, not a card under it (shell.js); a window
      // that is not modal gets no `cancel` of its own.
      event.stopPropagation();
      if (started) onClose();
    }}>
    <form class="plan-body" onSubmit=${submit}>
      <h2 class="plan-title" id=${titleId}>${started ? L.title_started : L.title} <span class="plan-what">${title}</span></h2>
      <dl class="kv plan-facts">
        ${variant
          ? html`<dt>${L.format}</dt>
              <dd>
                <${Seg} small label=${L.format} value=${format} onChange=${choose}
                  options=${variant.formats.map((value) => ({
                    value,
                    label: value,
                    disabled: started || !variant.commands[value]?.length,
                    title: variant.commands[value]?.length ? null : L.format_no_lines,
                  }))} />
              </dd>`
          : null}
        <dt>${L.store}</dt>
        <dd><${Tech} value=${[["store", store.id]]}>${store.name}</${Tech}></dd>
        ${sum.root
          ? html`<dt>${L.root}</dt>
              <dd class="plan-root"><code class="path">${sum.root}</code><${CopyButton} text=${sum.root} label=${L.copy_root} /></dd>`
          : null}
      </dl>
      ${variant && format === null
        ? html`<p class="plan-line warn" role="note"><${Icon} name="info" size=${15} /><span>${L.format_choose}</span></p>`
        : null}
      ${lines !== null && !planned
        ? html`<p class="hint"><${Spinner} label=${t(L.checking, {
            done: int(items.filter(settledLine).length + check.progress),
            total: int(items.length),
            commands: plural(items.length, L.commands),
          })} /></p>`
        : null}
      ${items.map((item) => html`<${LineProblem} key=${item.line} item=${item} />`)}
      ${check.failure ? html`<${CheckFailure} failure=${check.failure} count=${check.calls.length} />` : null}
      ${sum.plans.length ? html`<${PlanSummary} sum=${sum} />` : null}
      <${TaskChoice} offer=${offer} task=${task} added=${added} disabled=${started}
        onChange=${(patch) => setTask((now) => ({ ...now, ...patch }))} />
      ${large && planned && sum.todo > 0
        ? html`<label class="check-field plan-confirm">
            <input type="checkbox" checked=${confirmed} disabled=${started}
              onChange=${(event) => setConfirmed(event.currentTarget.checked)} />
            <span>${t(L.large, { positions: count(sum.todo, L.positions_accusative), size: sizeText(sum) })}</span>
          </label>`
        : null}
      ${reason && !started
        ? html`<p class="plan-line warn plan-reason" role="note"><${Icon} name="alert" size=${15} /><span>${reason}</span></p>`
        : null}
      ${runs
        ? html`<div class="plan-runs">${runs.map((run) =>
            run.problem
              ? html`<${ProblemView} key=${run.key} problem=${run.problem} compact />`
              : html`<${RunStatus} key=${run.key} item=${followed(run)} />`,
          )}</div>`
        : null}
      ${started && !settled ? html`<p class="hint plan-background">${L.background}</p>` : null}
      <div class=${started && !settled ? "plan-actions running" : "plan-actions"}>
        ${settled
          ? html`<button type="button" class="btn" autofocus onClick=${onClose}>${L.close}</button>`
          : started
            ? html`<button type="button" class="btn" title=${L.close_title} onClick=${onClose}>${L.close}</button>
                <button type="button" class="btn" autofocus title=${L.minimise_title} onClick=${onMinimise}>
                  <${Icon} name="down" size=${14} />${L.minimise}</button>`
            : html`<button type="button" class="btn" onClick=${onClose}>${L.cancel}</button>
                <button type="submit" class="btn primary" disabled=${!ready}>
                  <${Icon} name="check" size=${14} />${label}
                </button>`}
      </div>
    </form>
  </dialog>`;
}

/** A run that ended, or can no longer be followed. */
function isOver(item) {
  return item !== null && !downloadActive(item);
}

/**
 * Whether the call can be added as a task, and to which projects: those of
 * the producer in the store that the session may change (`project_write`).
 *
 * @returns {{options: import("../types.js").ProjectItem[], reason: string|null}}
 */
function taskOffer(projects, producer, store, lines, items) {
  if (lines !== null && lines.length > 1) {
    return { options: [], reason: t(L.task_lines, { count: int(lines.length), commands: plural(lines.length, L.lines) }) };
  }
  if (projects.error) return { options: [], reason: projects.error.problem?.detail ?? L.task_no_project_list };
  if (!projects.data) return { options: [], reason: L.task_loading };
  const own = projects.data.items.filter((item) => item.producer === producer);
  const options = own.filter((item) => item.project_write);
  if (!own.length) return { options, reason: t(L.task_no_project, { producer, store: store.name }) };
  if (!options.length) return { options, reason: L.task_no_write };
  if (items.length && items.every(settledLine) && !items[0].call) return { options, reason: L.task_no_call };
  return { options, reason: null };
}

/** „Dodaj jako zadanie projektu”: the project, the task's name, what came of it. */
function TaskChoice({ offer, task, added, disabled, onChange }) {
  const id = useId();
  const off = offer.reason !== null;
  const problem = added?.state === "failed" ? added.problem : null;
  const nameError = problem?.details?.option === "name" ? problem : null;
  return html`<fieldset class="plan-task" disabled=${disabled}>
    <legend class="visually-hidden">${L.task}</legend>
    <div class="check-field">
      <input type="checkbox" id=${`${id}-on`} checked=${task.on && !off} disabled=${off}
        aria-describedby=${off ? `${id}-why` : null}
        onChange=${(event) => onChange({ on: event.currentTarget.checked })} />
      <label for=${`${id}-on`}>${L.task}</label>
    </div>
    ${off ? html`<p class="field-hint plan-task-why" id=${`${id}-why`}>${offer.reason}</p>` : null}
    ${task.on && !off
      ? html`<div class="plan-task-fields">
          <div class="field">
            <label for=${`${id}-project`}>${L.task_project}</label>
            <select id=${`${id}-project`} value=${task.project}
              onChange=${(event) => onChange({ project: event.currentTarget.value })}>
              <option value="" disabled>${L.task_project_choose}</option>
              ${offer.options.map((item) => html`<option key=${item.project} value=${item.project}>${item.name}</option>`)}
            </select>
          </div>
          <div class=${`field${nameError ? " invalid" : ""}`}>
            <label for=${`${id}-name`}>${L.task_name}</label>
            <input id=${`${id}-name`} type="text" class="mono" value=${task.name} spellcheck="false" autocomplete="off"
              placeholder=${L.task_name_example} aria-invalid=${nameError ? "true" : null}
              aria-describedby=${nameError ? `${id}-name-error` : `${id}-name-hint`}
              onInput=${(event) => onChange({ name: event.currentTarget.value })} />
            ${nameError
              ? html`<span class="field-error" id=${`${id}-name-error`} role="alert">${nameError.detail}</span>`
              : html`<span class="field-hint" id=${`${id}-name-hint`}>${L.task_name_hint}</span>`}
          </div>
        </div>`
      : null}
    ${problem && !nameError ? html`<${ProblemView} problem=${problem} compact />` : null}
    ${added?.state === "added"
      ? html`<p class="plan-line plan-task-done" role="status"><${Icon} name="check" size=${15} />
          <span>${t(L.task_added, { name: added.name })}${" "}
            <${Link} view="projects" params=${{ project: added.project.project }}>${added.project.name}</${Link}></span></p>`
      : null}
  </fieldset>`;
}

/** What a window knows of its check before a format is chosen. */
const NO_CHECK = Object.freeze({
  items: [],
  calls: [],
  job: null,
  progress: 0,
  info: null,
  failure: null,
  ended: false,
});

/**
 * Plan the lines in one `check` job (ADR-044): read each line into a call,
 * start the job with every call read, follow it to its end and read the
 * plans it kept. A refusal of one call (`details.call`, e.g. an option the
 * producer refuses) names that line and the job is asked again without it;
 * a refusal of the whole request (offline mode) names every line. A line
 * whose check failed gets the job's reason for it (`result.calls`); a job
 * that planned none of several lines failed as a whole (`failure`). A line
 * read is known as its call also when its check is refused.
 *
 * @param {string} producer
 * @param {string} store
 * @param {string[]|null} lines - None until a format is chosen.
 * @returns {PlanCheck}
 */
function usePlans(producer, store, lines) {
  const [check, setCheck] = useState(NO_CHECK);
  const key = lines === null ? "" : JSON.stringify([producer, store, lines]);
  useEffect(() => {
    if (lines === null) {
      setCheck(NO_CHECK);
      return undefined;
    }
    let live = true;
    const stops = [];
    let items = lines.map((line) => ({ line, call: null, plan: null, problem: null, failure: null }));
    const update = (index, patch) => {
      items = items.map((item, place) => (place === index ? { ...item, ...patch } : item));
    };
    const show = (patch = {}) => {
      if (live) setCheck((current) => ({ ...current, ...patch, items }));
    };
    setCheck({ ...NO_CHECK, items });
    const plan = async () => {
      const read = await Promise.all(lines.map((line) => readLine(producer, line)));
      if (!live) return;
      read.forEach((answer, index) => update(index, answer));
      // The places in `lines` of the job's calls, in the job's order.
      let places = items.flatMap((item, index) => (item.call ? [index] : []));
      const calls = () =>
        places.map((index) => ({ command: items[index].call.command, options: items[index].call.options }));
      let job = null;
      while (job === null && places.length) {
        try {
          job = await startJob({ kind: "check", producer, store, calls: calls() });
        } catch (error) {
          if (!error.problem) throw error;
          const refused = error.problem.details?.call;
          if (Number.isInteger(refused) && refused >= 0 && refused < places.length) {
            update(places[refused], { problem: error.problem });
            places = places.filter((_, place) => place !== refused);
          } else {
            for (const index of places) update(index, { problem: error.problem });
            places = [];
          }
        }
        if (!live) return;
        show();
      }
      if (job === null) {
        show({ ended: true });
        return;
      }
      show({ job, calls: calls() });
      const fail = (failure) => {
        if (places.length === 1) update(places[0], { failure });
        show({ ended: true, failure: places.length === 1 ? null : failure });
      };
      const end = await finalState(job.id, stops, (data) => show({ progress: data.current }));
      if (!live) return;
      if (!SUMMARY_STATES.has(end.state)) {
        fail(end.error ?? { code: end.state, detail: end.state });
        return;
      }
      let info;
      try {
        info = await getJobPlan(job.id);
      } catch (error) {
        if (!error.problem) throw error;
        if (live) fail({ code: error.problem.code, detail: error.problem.detail });
        return;
      }
      if (!live) return;
      (end.result?.calls ?? []).forEach((section, place) => {
        if (section.status === "failed") update(places[place], { failure: section.error });
      });
      for (const kept of info.calls) update(places[kept.call], { plan: kept });
      show({ ended: true, info });
    };
    plan();
    return () => {
      live = false;
      for (const stop of stops) stop();
    };
  }, [key]);
  return check;
}

/** A line read into a call, or the problem of reading it. */
async function readLine(producer, line) {
  try {
    return { call: await parseCommand(producer, line) };
  } catch (error) {
    if (!error.problem) throw error;
    return { problem: error.problem };
  }
}

/**
 * The check of a window's lines (`usePlans`).
 *
 * @typedef {object} PlanCheck
 * @property {PlanLine[]} items - Each line on its way to a plan.
 * @property {Array<{command: string, options: Object<string, *>}>} calls - The
 *   calls of the `check` job, in its order: its download asks the same.
 * @property {import("../types.js").JobDetail|null} job - The `check` job.
 * @property {number} progress - Calls the job has planned so far.
 * @property {import("../types.js").ActionPlanInfo|null} info - The plans it kept.
 * @property {import("../types.js").JobFailure|null} failure - Why a job of
 *   several lines planned none of them.
 * @property {boolean} ended - Every line has its plan or is named with its problem.
 */

/**
 * A line of the variant on its way to a plan.
 *
 * @typedef {object} PlanLine
 * @property {string} line
 * @property {import("../types.js").CommandCall|null} call
 * @property {import("../types.js").CallPlan|null} plan - Its plan among the job's plans.
 * @property {import("../types.js").Problem|null} problem - Refused before the job.
 * @property {{code: string, detail: string}|null} failure - Its check failed.
 */

function settledLine(item) {
  return Boolean(item.plan || item.problem || item.failure);
}

/** The final state event of a job (a broken stream counts as its failure). */
function finalState(job, stops, onProgress) {
  return new Promise((resolve) => {
    stops.push(
      watchJob(job, {
        onProgress,
        onState: (data) => {
          if (FINAL_STATES.has(data.state)) resolve(data);
        },
        onError: (problem) => resolve({ state: "failed", error: { code: problem.code, detail: problem.detail } }),
      }),
    );
  });
}

/** The sum of a window before its plans are read. */
const NO_SUM = Object.freeze({
  plans: [],
  counts: {},
  positions: 0,
  todo: 0,
  known: 0,
  unknown: false,
  complete: true,
  root: null,
  entries: [],
});

/**
 * The plans of the lines together, as the job's totals say: counts, what a
 * run downloads and its size; each position with the place of its call.
 */
function planSum(info) {
  if (info === null) return NO_SUM;
  return {
    plans: info.calls,
    counts: info.counts,
    positions: info.positions,
    todo: info.todo,
    known: info.size_bytes ?? 0,
    unknown: info.size_bytes === null,
    complete: info.size_complete,
    root: info.root,
    entries: info.calls.flatMap((plan) => plan.entries.map((entry) => ({ ...entry, call: plan.call }))),
  };
}

function sizeText(sum) {
  if (sum.unknown) return L.size_unknown;
  return t(sum.complete ? L.size : L.size_partial, { size: bytes(sum.known) });
}

function PlanSummary({ sum }) {
  const named = STATUSES.filter((status) => sum.counts[status]).map(
    (status) => `${L.status[status]} ${int(sum.counts[status])}`,
  );
  const conflicts = sum.entries.filter((entry) => entry.conflict);
  const notices = sum.plans.flatMap((plan) => plan.notices);
  return html`<div class="plan-summary">
    <p class="plan-counts">
      <b>${count(sum.positions, L.positions)}</b>${named.length ? `: ${named.join(", ")}` : null}
    </p>
    <p class="plan-todo">
      <b>${t(L.todo, { count: int(sum.todo) })}</b>
      ${sum.todo
        ? html` · <${Tech} value=${[["size_bytes", sum.unknown ? "null" : String(sum.known)], ["size_complete", String(sum.complete)]]}>
            <span class=${sum.complete ? "" : "warn-text"}>${sizeText(sum)}</span></${Tech}>`
        : null}
    </p>
    ${sum.todo && !sum.complete && !sum.unknown ? html`<p class="hint plan-size-hint">${L.size_hint}</p>` : null}
    ${conflicts.length
      ? html`<div class="plan-line bad" role="note"><${Icon} name="alert" size=${15} />
          <div>${t(L.conflicts, { count: int(conflicts.length), positions: plural(conflicts.length, L.positions) })}
            <ul>${conflicts.map(
              (entry) => html`<li key=${`${entry.call}/${entry.path}`}><span class="mono">${entry.path}</span>: <${Tech} value=${[["conflict", entry.conflict]]}>
                ${L.conflict[entry.conflict] ?? entry.conflict}</${Tech}>${entry.error ? ` — ${entry.error}` : ""}</li>`,
            )}</ul></div></div>`
      : null}
    ${sum.counts.check_failed
      ? html`<p class="plan-line warn" role="note"><${Icon} name="alert" size=${15} />
          <span>${t(L.not_checked, { count: int(sum.counts.check_failed) })}</span></p>`
      : null}
    <div class="table-wrap plan-entries" tabindex="0">
      <table>
        <caption class="visually-hidden">${L.entries}</caption>
        <thead><tr>
          <th scope="col">${L.columns.path}</th>
          <th scope="col">${L.columns.status}</th>
          <th scope="col">${L.columns.local}</th>
          <th scope="col">${L.columns.source}</th>
          <th scope="col" class="num">${L.columns.size}</th>
        </tr></thead>
        <tbody>${sum.entries.map(
          (entry) => html`<tr key=${`${entry.call}/${entry.path}`}>
            <td><${Tech} value=${[["unit", entry.unit]]}><span class="mono plan-path">${entry.path}</span></${Tech}>
              ${entry.error ? html`<p class="row-problem"><${Icon} name="alert" size=${13} /><span>${entry.error}</span></p>` : null}</td>
            <td><${Badge} level=${LEVELS[entry.status] ?? "plain"}>${L.status[entry.status] ?? entry.status}</${Badge}></td>
            <td class="mono">${entry.local_label ?? html`<span class="faint">${L.no_label}</span>`}</td>
            <td class="mono">${entry.available_label ?? html`<span class="faint">${L.unknown}</span>`}</td>
            <td class="num tabular">${entry.size_bytes === null ? html`<span class="faint">${L.unknown}</span>` : bytes(entry.size_bytes)}</td>
          </tr>`,
        )}</tbody>
      </table>
    </div>
    ${sum.plans.map(
      (plan) => html`<div key=${plan.call} class="plan-command">
        <span class="section-title">${L.line}</span>
        <div class="cmd"><code class="path">${plan.line}</code><${CopyButton} text=${plan.line} label=${L.copy_line} /></div>
      </div>`,
    )}
    ${notices.length
      ? html`<div class="job-notices plan-notices">
          <span class="section-title">${L.notices}</span>
          <ul>${notices.map(
            (notice, index) => html`<li key=${index} class=${notice.level}><${Tech} value=${notice.code}>${notice.message}</${Tech}></li>`,
          )}</ul>
        </div>`
      : null}
  </div>`;
}

/** A line refused before its check, or whose check failed. */
function LineProblem({ item }) {
  if (item.problem) return html`<${ProblemView} problem=${item.problem} compact />`;
  if (!item.failure) return null;
  return html`<p class="plan-line bad" role="alert"><${Icon} name="alert" size=${15} />
    <span><${Tech} value=${[["code", item.failure.code]]}>${t(L.failed_line, { line: item.line })}</${Tech}> ${item.failure.detail}</span></p>`;
}

/** The check of several lines that planned none of them: why (the first line's reason). */
function CheckFailure({ failure, count: lines }) {
  const text = t(L.failed_lines, { count: int(lines), commands: plural(lines, L.commands) });
  return html`<p class="plan-line bad" role="alert"><${Icon} name="alert" size=${15} />
    <span><${Tech} value=${[["code", failure.code]]}>${text}</${Tech}> ${failure.detail}</span></p>`;
}

/**
 * One download, or a project's download, started here: its state as the
 * downloads of the shell follow it, with its explicit cancel while it runs.
 */
function RunStatus({ item }) {
  if (!item) return html`<${Spinner} />`;
  return html`<div class="plan-run">
    <${DownloadStatus} item=${item} />
    ${downloadActive(item) ? html`<div class="plan-run-actions"><${CancelDownload} item=${item} /></div>` : null}
  </div>`;
}
