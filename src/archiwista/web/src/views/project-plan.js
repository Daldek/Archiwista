/**
 * The plan window of a set's „Przepnij” and „Przywróć brakujące” on a
 * project's card (docs/SPEC.md 6.5 g; ADR-042 erratum 2): neither job starts
 * at once. The window starts the set's check („Sprawdź aktualizacje” of the
 * set, a `project_check`) through the card's job (`useProjectJobs`), keeps the
 * id of that check and shows only its progress and its end. A start the
 * server refuses (e.g. a `409` naming a job of the project, which the card
 * then follows) and a check that failed, was cancelled or was interrupted
 * show why, with nothing to confirm.
 *
 * A check that ended with its result shows the plan of this set alone: its
 * versions by the check's status; for a re-pin the versions it changes (a
 * newer one with its pinned and its available label, one the set's calls no
 * longer select, a missing one) and the new positions at the source it would
 * pin; for a restore the missing versions it downloads again; the versions
 * that could not be checked, with why; each call's command line to copy, with
 * how its check went; and notes: a re-pin pins only when the whole download
 * succeeds, a restore never changes the project file, and the job plans again
 * at the source, so it fetches what the source has then.
 *
 * The confirmation („Przepnij”, „Przywróć brakujące”) is disabled with the
 * reason the card's button would have now (`groupJobReason`; a running check
 * is a job of the project), for a restore also when the check found no
 * missing version, the reason in the window (`aria-describedby`). It starts
 * the job with the check as its `plan_job` and closes the window: the card
 * follows the job to its summary, or shows its refusal (e.g. `409
 * plan_mismatch`: the set changed since its check). „Anuluj” and `Esc` close
 * the window; the check goes on as the card's job and nothing else starts.
 */

import { int, plural } from "../format.js";
import { T, t } from "../labels/index.js";
import { projectJobs as JL } from "../labels/project-jobs.js";
import {
  CopyButton,
  html,
  Icon,
  loadStylesheet,
  Modal,
  ProblemView,
  Spinner,
  Tech,
  useEffect,
  useId,
  useState,
} from "../ui.js";
import { Badge, FINAL_STATES, JobFailure, loadCardStyles, SUMMARY_STATES } from "./cards.js";
import { groupJobReason, markLevel, reason } from "./project-jobs.js";

await loadCardStyles();
await loadStylesheet(new URL("./plan.css", import.meta.url));

const L = JL.plan;
/** The check's word of each status of a version. */
const WORDS = JL.mark.project_check;
/** The statuses of a checked version in the server's order (`CHECK_STATUSES`). */
const STATUSES = [
  "current",
  "newer",
  "missing",
  "removed",
  "unverifiable",
  "check_failed",
  "not_checkable",
];
/** The versions a re-pin changes, and those the source could not be asked about. */
const CHANGED = new Set(["newer", "removed", "missing"]);
const NOT_CHECKED = new Set(["check_failed", "not_checkable"]);
/** The badge of how the check of a call went (`status` of `result.calls`). */
const CALL_LEVELS = { ok: "ok", partial: "warn", failed: "bad" };
/** The confirmation of each kind: the card's button's label, icon and title. */
const CONFIRM = {
  repin: { label: JL.repin, icon: "pin", title: JL.repin_title },
  restore: { label: JL.restore, icon: "download", title: JL.restore_title },
};

/**
 * The plan window of a set's re-pin or restore.
 *
 * @param {object} props
 * @param {"repin"|"restore"} props.kind
 * @param {import("../types.js").ProjectGroup} props.group - The set as the card
 *   shows it now.
 * @param {ReturnType<typeof import("./project-jobs.js").useProjectJobs>} props.jobs -
 *   The card's jobs: the window's check and the job it starts are the card's.
 * @param {Object<string, *>} props.context - The card's `contextOf(card)`.
 * @param {() => void} props.onClose - Close the window; nothing is cancelled.
 */
export function ProjectPlan({ kind, group, jobs, context, onClose }) {
  const id = useId();
  // The window's own check: undefined while it starts, null when refused.
  const [check, setCheck] = useState(undefined);
  useEffect(() => {
    let open = true;
    jobs.start("check", [group.name]).then((job) => {
      if (open) setCheck(job);
    });
    return () => {
      open = false;
    };
  }, []);
  const events = check && jobs.job.events?.id === check.id ? jobs.job.events : null;
  const ended = events !== null && FINAL_STATES.has(events.state);
  const result = ended && SUMMARY_STATES.has(events.state) ? events.result : null;
  const plan = result ? planOf(result, group.name) : null;
  // Nothing to confirm after a refused start or a check that gave no plan.
  const offered = check !== null && !(ended && plan === null);
  let why = groupJobReason(kind, group, context);
  if (!why && kind === "restore" && plan && !plan.missing.length) why = reason("no_missing");
  const whyId = `${id}-why`;
  const title = t(L.title[kind], { group: group.name });
  const confirm = CONFIRM[kind];
  const start = () => {
    jobs.start(kind, [group.name], check.id);
    onClose();
  };
  return html`<${Modal} label=${title} onClose=${onClose}>
    <h2>${title}</h2>
    ${check === null && jobs.job.problem
      ? html`<${ProblemView} problem=${jobs.job.problem} compact />`
      : null}
    ${offered && !plan ? html`<${Checking} events=${events} />` : null}
    ${ended && !plan ? html`<${CheckFailure} events=${events} />` : null}
    ${plan ? html`<${SetPlan} kind=${kind} plan=${plan} events=${events} />` : null}
    ${offered && why ? html`<p class="hint" id=${whyId}>${why.text}</p>` : null}
    <div class="modal-actions">
      <button type="button" class="btn" onClick=${onClose}>${T.common.actions.cancel}</button>
      ${offered
        ? html`<button type="button" class="btn primary" disabled=${!plan || why !== null}
            title=${why ? why.text : confirm.title} aria-describedby=${why ? whyId : null}
            onClick=${start}>
            <${Icon} name=${confirm.icon} size=${14} />${confirm.label}</button>`
        : null}
    </div>
  </${Modal}>`;
}

/**
 * The plan of one set in a check's result: its versions (`pins`) with the
 * missing ones, the new positions at the source (`added`) and its calls.
 */
function planOf(result, name) {
  const own = (item) => item.group === name;
  const pins = (result.pins ?? []).filter(own);
  return {
    pins,
    missing: pins.filter((row) => row.status === "missing"),
    added: (result.added ?? []).filter(own),
    calls: (result.calls ?? []).filter(own),
  };
}

/** The check on its way: the calls it has asked about, and a broken stream. */
function Checking({ events }) {
  const progress = events?.progress;
  const label =
    progress?.total > 0
      ? t(L.checking_progress, {
          current: int(progress.current),
          total: int(progress.total),
          commands: plural(progress.total, L.commands),
        })
      : L.checking;
  return html`<p class="pp-checking"><${Spinner} label=${label} /></p>
    ${events?.stream ? html`<${ProblemView} problem=${events.stream} compact />` : null}`;
}

/** A check that ended without its plan: why, as the card's job status says it. */
function CheckFailure({ events }) {
  const state = T.common.job_state[events.state] ?? events.state;
  return html`<div class="plan-line bad" role="alert"><${Icon} name="alert" size=${15} />
    <div class="pp-failure">
      ${events.error
        ? html`<${JobFailure} state=${events.state} failure=${events.error} />`
        : html`<p>${t(L.ended, { state })}</p>`}
    </div>
  </div>`;
}

/**
 * The set's plan: its versions by status (the check's job one click away),
 * what the job changes or downloads, the versions not checked, the calls and
 * the notes.
 */
function SetPlan({ kind, plan, events }) {
  const listed =
    kind === "repin" ? plan.pins.filter((row) => CHANGED.has(row.status)) : plan.missing;
  const unchecked = plan.pins.filter((row) => NOT_CHECKED.has(row.status));
  const total = plan.pins.length;
  const counts = total
    ? t(L.pins, { total: int(total), counts: statusCounts(plan.pins) })
    : L.no_pins;
  const nothing = kind === "repin" && !listed.length && !plan.added.length;
  return html`<div class="pp-plan">
    <p class="pp-counts">
      <${Tech} value=${[["job", events.id], ["state", events.state]]}>${counts}</${Tech}></p>
    ${nothing ? html`<p>${L.no_changes}</p>` : null}
    <${PinSection} title=${kind === "repin" ? L.changes : L.missing} rows=${listed} />
    ${kind === "repin" && plan.added.length
      ? html`<${Section} title=${L.added}>
          ${plan.added.map((row) => html`<${AddedRow} key=${row.path} row=${row} />`)}
        </${Section}>`
      : null}
    <${PinSection} title=${L.not_checked} rows=${unchecked} />
    ${plan.calls.length
      ? html`<${Section} title=${L.calls}>
          ${plan.calls.map((call, place) => html`<${CallRow} key=${place} call=${call} />`)}
        </${Section}>`
      : null}
    <${Note} text=${L.note[kind]} />
    <${Note} text=${L.note.again} />
  </div>`;
}

/** A note of the plan. */
function Note({ text }) {
  return html`<p class="plan-line" role="note">
    <${Icon} name="info" size=${15} /><span>${text}</span></p>`;
}

/** „aktualna 1, jest nowsza 1”: a set's versions by status, in the check's order. */
function statusCounts(rows) {
  const counts = new Map(STATUSES.map((status) => [status, 0]));
  for (const row of rows) counts.set(row.status, (counts.get(row.status) ?? 0) + 1);
  return [...counts]
    .filter(([, value]) => value > 0)
    .map(([status, value]) => `${WORDS[status] ?? status} ${int(value)}`)
    .join(", ");
}

/** A list of the plan under its title, which also names the list. */
function Section({ title, children }) {
  return html`<div class="pp-section">
    <h3 class="section-title">${title}</h3>
    <ul class="pp-rows" aria-label=${title}>${children}</ul>
  </div>`;
}

/** The set's versions of one part of the plan under its title; nothing without any. */
function PinSection({ title, rows }) {
  if (!rows.length) return null;
  return html`<${Section} title=${title}>
    ${rows.map((row) => html`<${PinRow} key=${`${row.producer}\n${row.version}`} row=${row} />`)}
  </${Section}>`;
}

/**
 * A version of the set as the check found it: its path, the check's word,
 * its pinned label (with the source's when it differs) and the reason.
 */
function PinRow({ row }) {
  const changed = row.available_label && row.available_label !== row.pinned_label;
  const labels = changed
    ? t(L.change, { pinned: row.pinned_label ?? T.common.empty, available: row.available_label })
    : row.pinned_label;
  return html`<li class="pp-row">
    <span class="mono pp-path">${row.path}</span>
    <${Badge} level=${markLevel(row.status)}>
      <${Tech} value=${[["status", row.status], ["version", row.version]]}>
        ${WORDS[row.status] ?? row.status}</${Tech}>
    </${Badge}>
    ${labels ? html`<span class="pp-labels">${labels}</span>` : null}
    ${row.detail ? html`<span class="pc-pin-why">${row.detail}</span>` : null}
  </li>`;
}

/** A new position at the source a re-pin would pin, with the source's label. */
function AddedRow({ row }) {
  const path = html`<span class="mono pp-path">${row.path}</span>`;
  return html`<li class="pp-row">
    ${row.unit ? html`<${Tech} value=${[["unit", row.unit]]}>${path}</${Tech}>` : path}
    ${row.available_label ? html`<span class="pp-labels">${row.available_label}</span>` : null}
  </li>`;
}

/** The check of one call of the set: its command line to copy and how it went. */
function CallRow({ call }) {
  const error = call.error;
  const values = error ? [["code", error.code]] : [];
  if (error?.reason) values.push(["reason", error.reason]);
  return html`<li class="pp-call">
    <div class="cmd">
      <code class="path">${call.line}</code><${CopyButton} text=${call.line} label=${L.copy_line} />
    </div>
    <div class="pp-call-state">
      <${Badge} level=${CALL_LEVELS[call.status] ?? "plain"}>
        <${Tech} value=${[["status", call.status], ["command", call.command]]}>
          ${L.call[call.status] ?? call.status}</${Tech}>
      </${Badge}>
      ${error
        ? html`<span class="row-problem"><${Icon} name="alert" size=${13} />
            <${Tech} value=${values}>${error.detail}</${Tech}></span>`
        : null}
    </div>
  </li>`;
}
