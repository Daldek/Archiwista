/**
 * The „Okno planu” of a download (docs/SPEC.md 6.1 „Plan przed akcją”, 6.5 h;
 * plan 2026-10-25 A11): what a run of the producer's command would do in a
 * configured store, and then the run.
 *
 * The variant's lines in the chosen format (`commands`; nothing is chosen
 * when the variant has no default format) are read into calls (`POST
 * /commands/parse`), and each call is planned by a `check` job (`POST
 * /jobs`, then `GET /jobs/{job}/plan` once it ends): nothing is written. The
 * window sums the plans: the positions by status, what a run downloads and
 * its size („co najmniej …” when the producer tells only some sizes,
 * „rozmiar nieznany” when it tells none, never 0), the store with the
 * producer's directory, each position with the ones the producer would
 * refuse to write, and each command line to copy. „Pobierz” starts one
 * `download` per plan with something to download (`plan_job`: the run
 * fetches what was shown) and follows them to their files and failed
 * units; above 5 GB or 500 positions it asks to be confirmed first (SPEC
 * 10.3). A session that may not write the stores (`store_write`) sees the
 * plan with the action disabled and the reason.
 */

import { getJobPlan, parseCommand, startJob, watchJob } from "../api.js";
import { useApp } from "../context.js";
import { bytes, count, int, plural } from "../format.js";
import { actions } from "../labels/actions.js";
import { t } from "../labels/index.js";
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
import { Badge, FINAL_STATES, JobStatus, loadCardStyles, SUMMARY_STATES, useJob } from "./cards.js";

await loadCardStyles();
await loadStylesheet(new URL("./plan.css", import.meta.url));

const L = actions.plan;
/** A run above either asks to be confirmed (SPEC 10.3). */
const LARGE_BYTES = 5e9;
const LARGE_POSITIONS = 500;
/** Statuses of a plan's positions, in the server's order (`PLAN_STATUSES`). */
const STATUSES = ["current", "newer", "missing", "unverifiable", "check_failed"];
const LEVELS = { current: "ok", newer: "info", missing: "info", unverifiable: "plain", check_failed: "bad" };
const FILE_LEVELS = { new: "ok", unchanged: "plain", relabeled: "info" };

/**
 * The plan window of one variant of a report's row.
 *
 * @param {object} props
 * @param {string} props.producer
 * @param {{id: string, name: string}} props.store - Where the run writes.
 * @param {string} props.title - What is downloaded, e.g. „NMT · 2023 · PL-2000”.
 * @param {import("../types.js").AvailabilityVariant} props.variant
 * @param {() => void} props.onClose
 * @param {() => void} props.onDone - The downloads started here all ended.
 */
export function DownloadPlan({ producer, store, title, variant, onClose, onDone }) {
  const { session } = useApp();
  const titleId = useId();
  const dialog = useRef(null);
  const [format, setFormat] = useState(variant.default_format);
  const lines = format === null ? null : (variant.commands[format] ?? []);
  const items = usePlans(producer, store.id, lines);
  const [confirmed, setConfirmed] = useState(false);
  const [runs, setRuns] = useState(null);
  const [ended, setEnded] = useState(() => new Set());
  const sum = sumPlans(items);
  const planned = items.length > 0 && items.every(settledLine);
  const large = sum.todo > LARGE_POSITIONS || sum.known > LARGE_BYTES;
  const settled = runs !== null && runs.every((run) => run.problem || (run.job && ended.has(run.job.id)));
  const busy = runs !== null && !settled;
  const allowed = Boolean(session?.store_write);
  const ready = planned && sum.todo > 0 && allowed && (!large || confirmed) && runs === null;
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => {
      if (element.open) element.close();
    };
  }, []);
  useEffect(() => {
    if (settled) onDone();
  }, [settled]);
  const close = () => {
    if (!busy) onClose();
  };
  const choose = (value) => {
    if (runs !== null) return;
    setFormat(value);
    setConfirmed(false);
  };
  const download = async (event) => {
    event.preventDefault();
    if (!ready) return;
    const todo = items.filter((item) => item.plan?.todo > 0);
    setRuns(todo.map((item) => ({ key: item.plan.job_id, job: null, problem: null })));
    const update = (index, patch) =>
      setRuns((current) => current.map((run, place) => (place === index ? { ...run, ...patch } : run)));
    await Promise.all(
      todo.map(async (item, index) => {
        try {
          const job = await startJob({
            kind: "download",
            producer,
            store: store.id,
            command: item.call.command,
            options: item.call.options,
            plan_job: item.plan.job_id,
          });
          update(index, { job });
        } catch (error) {
          if (!error.problem) throw error;
          update(index, { problem: error.problem });
        }
      }),
    );
  };
  const reason = !planned || !sum.plans.length ? null : !sum.todo ? L.nothing : !allowed ? L.no_write : null;
  return html`<dialog class="plan-window" ref=${dialog} aria-labelledby=${titleId}
    onCancel=${(event) => {
      event.preventDefault();
      close();
    }}
    onKeyDown=${(event) => {
      // Esc closes this window only, not a card under it (shell.js).
      if (event.key === "Escape") event.stopPropagation();
    }}>
    <form class="plan-body" onSubmit=${download}>
      <h2 class="plan-title" id=${titleId}>${L.title} <span class="plan-what">${title}</span></h2>
      <dl class="kv plan-facts">
        <dt>${L.format}</dt>
        <dd>
          <${Seg} small label=${L.format} value=${format} onChange=${choose}
            options=${variant.formats.map((value) => ({
              value,
              label: value,
              disabled: runs !== null || !variant.commands[value]?.length,
              title: variant.commands[value]?.length ? null : L.format_no_lines,
            }))} />
        </dd>
        <dt>${L.store}</dt>
        <dd><${Tech} value=${[["store", store.id]]}>${store.name}</${Tech}></dd>
        ${sum.root
          ? html`<dt>${L.root}</dt>
              <dd class="plan-root"><code class="path">${sum.root}</code><${CopyButton} text=${sum.root} label=${L.copy_root} /></dd>`
          : null}
      </dl>
      ${format === null
        ? html`<p class="plan-line warn" role="note"><${Icon} name="info" size=${15} /><span>${L.format_choose}</span></p>`
        : null}
      ${lines !== null && !planned
        ? html`<p class="hint"><${Spinner} label=${t(L.checking, {
            done: int(items.filter(settledLine).length),
            total: int(items.length),
            commands: plural(items.length, L.commands),
          })} /></p>`
        : null}
      ${items.map((item) => html`<${LineProblem} key=${item.line} item=${item} />`)}
      ${sum.plans.length ? html`<${PlanSummary} sum=${sum} />` : null}
      ${large && planned && sum.todo > 0
        ? html`<label class="check-field plan-confirm">
            <input type="checkbox" checked=${confirmed} disabled=${runs !== null}
              onChange=${(event) => setConfirmed(event.currentTarget.checked)} />
            <span>${t(L.large, { positions: count(sum.todo, L.positions_accusative), size: sizeText(sum) })}</span>
          </label>`
        : null}
      ${reason && runs === null
        ? html`<p class="plan-line warn plan-reason" role="note"><${Icon} name="alert" size=${15} /><span>${reason}</span></p>`
        : null}
      ${runs
        ? html`<div class="plan-runs">${runs.map((run) =>
            run.problem
              ? html`<${ProblemView} key=${run.key} problem=${run.problem} compact />`
              : run.job
                ? html`<${RunStatus} key=${run.key} id=${run.job.id}
                    onEnd=${() => setEnded((done) => new Set(done).add(run.job.id))} />`
                : html`<${Spinner} key=${run.key} />`,
          )}</div>`
        : null}
      <div class="plan-actions">
        ${settled
          ? html`<button type="button" class="btn" onClick=${onClose}>${L.close}</button>`
          : html`<button type="button" class="btn" disabled=${busy} onClick=${close}>${L.cancel}</button>
              <button type="submit" class="btn primary" disabled=${!ready}>
                ${busy ? html`<span class="spinner" aria-hidden="true"></span>` : html`<${Icon} name="check" size=${14} />`}
                ${planned
                  ? t(L.submit, { count: int(sum.todo), positions: plural(sum.todo, L.positions_accusative) })
                  : L.submit_unplanned}
              </button>`}
      </div>
    </form>
  </dialog>`;
}

/**
 * Plan each line: read it into a call, start its `check` job, wait for its
 * end and read the plan it kept. The lines are planned together; the server
 * runs two network jobs at a time and queues the others.
 *
 * @param {string} producer
 * @param {string} store
 * @param {string[]|null} lines - None until a format is chosen.
 * @returns {PlanLine[]}
 */
function usePlans(producer, store, lines) {
  const [items, setItems] = useState([]);
  const key = lines === null ? "" : JSON.stringify([producer, store, lines]);
  useEffect(() => {
    if (lines === null) {
      setItems([]);
      return undefined;
    }
    let live = true;
    const stops = [];
    setItems(lines.map((line) => ({ line, call: null, plan: null, problem: null, failure: null })));
    const update = (index, patch) => {
      if (live) setItems((current) => current.map((item, place) => (place === index ? { ...item, ...patch } : item)));
    };
    lines.forEach(async (line, index) => {
      try {
        const call = await parseCommand(producer, line);
        if (!live) return;
        const job = await startJob({ kind: "check", producer, store, command: call.command, options: call.options });
        if (!live) return;
        update(index, { call });
        const end = await finalState(job.id, stops);
        if (!live) return;
        if (!SUMMARY_STATES.has(end.state)) {
          update(index, { failure: end.error ?? { code: end.state, detail: end.state } });
          return;
        }
        update(index, { plan: await getJobPlan(job.id) });
      } catch (error) {
        if (!error.problem) throw error;
        update(index, { problem: error.problem });
      }
    });
    return () => {
      live = false;
      for (const stop of stops) stop();
    };
  }, [key]);
  return items;
}

/**
 * A line of the variant on its way to a plan.
 *
 * @typedef {object} PlanLine
 * @property {string} line
 * @property {import("../types.js").CommandCall|null} call
 * @property {import("../types.js").ActionPlanInfo|null} plan
 * @property {import("../types.js").Problem|null} problem - Refused before a job.
 * @property {import("../types.js").JobFailure|null} failure - Its check failed.
 */

function settledLine(item) {
  return Boolean(item.plan || item.problem || item.failure);
}

/** The final state event of a job (a broken stream counts as its failure). */
function finalState(job, stops) {
  return new Promise((resolve) => {
    stops.push(
      watchJob(job, {
        onState: (data) => {
          if (FINAL_STATES.has(data.state)) resolve(data);
        },
        onError: (problem) => resolve({ state: "failed", error: { code: problem.code, detail: problem.detail } }),
      }),
    );
  });
}

/** The plans of the lines together: counts, what a run downloads and its size. */
function sumPlans(items) {
  const plans = items.map((item) => item.plan).filter(Boolean);
  const counts = Object.fromEntries(
    STATUSES.map((status) => [status, plans.reduce((total, plan) => total + (plan.counts[status] ?? 0), 0)]),
  );
  const sized = plans.filter((plan) => plan.todo > 0);
  const told = sized.filter((plan) => plan.size_bytes !== null);
  return {
    plans,
    counts,
    positions: plans.reduce((total, plan) => total + plan.entries.length, 0),
    todo: plans.reduce((total, plan) => total + plan.todo, 0),
    known: told.reduce((total, plan) => total + plan.size_bytes, 0),
    unknown: sized.length > 0 && told.length === 0,
    complete: sized.every((plan) => plan.size_complete),
    root: plans[0]?.root ?? null,
    entries: plans.flatMap((plan) => plan.entries),
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
              (entry) => html`<li key=${entry.path}><span class="mono">${entry.path}</span>: <${Tech} value=${[["conflict", entry.conflict]]}>
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
          (entry) => html`<tr key=${entry.path}>
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
      (plan) => html`<div key=${plan.job_id} class="plan-command">
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

/** One download started here, followed to its end. */
function RunStatus({ id, onEnd }) {
  const job = useJob({ onEnd });
  useEffect(() => job.follow(id, "download"), [id]);
  return html`<${JobStatus} job=${job} summary=${downloadSummary} />`;
}

/** A download's files by status and its failed units (`archiwista jobs` says the same). */
function downloadSummary(events) {
  const result = events.result;
  if (!result) return null;
  const counts = Object.entries(L.file_status).map(([status, word]) => `${word} ${int(result.counts[status] ?? 0)}`);
  const files = Object.values(result.counts).reduce((total, value) => total + value, 0);
  const failed = result.items.filter((item) => item.status === "failed");
  return html`<div class="plan-result">
    <p class="job-summary">${t(L.files, { files: int(files), counts: counts.join(", "), failed: int(result.failed) })}</p>
    ${result.files.length
      ? html`<ul class="plan-files" aria-label=${L.files_title}>${result.files.map(
          (file) => html`<li key=${file.path}>
            <${Tech} value=${[["version_path", file.version_path ?? "–"], ["sha256", file.sha256]]}><span class="mono">${file.path}</span></${Tech}>
            <${Badge} level=${FILE_LEVELS[file.status] ?? "plain"}>${L.file_status[file.status] ?? file.status}</${Badge}>
            <span class="faint tabular">${bytes(file.size_bytes)}</span>
          </li>`,
        )}</ul>`
      : null}
    ${failed.length
      ? html`<div class="plan-failed">
          <span class="section-title">${L.failed_items}</span>
          <ul>${failed.map(
            (item) => html`<li key=${item.id}><${Tech} value=${[["code", item.code ?? "–"], ["reason", item.reason ?? "–"]]}>
              <span class="mono">${item.id}</span></${Tech}>${item.message ? ` ${item.message}` : ""}</li>`,
          )}</ul>
        </div>`
      : null}
  </div>`;
}
