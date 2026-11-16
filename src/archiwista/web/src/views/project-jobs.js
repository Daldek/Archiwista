/**
 * The jobs of a project's card (docs/SPEC.md 6.5 g; A-ADR-049 decisions 11
 * and 12): „Weryfikuj” and „Sprawdź aktualizacje” of the project,
 * „Sprawdź aktualizacje”, „Przepnij” and „Przywróć brakujące” of each group,
 * all over `POST /projects/{project}/jobs` and one `useJob`: the server runs
 * one job of a project at a time and names a running one in its `409`, which
 * the card then follows. „Przepnij” and „Przywróć brakujące” start nothing at
 * once: each opens the plan window of its set (views/project-plan.js; ADR-042
 * erratum 2), which starts the set's check through this `useJob` and, once
 * its plan is confirmed, the job with that check as its `plan_job`.
 *
 * Each action is disabled with the first reason that holds, in this order
 * (ADR-042 decision 4 as A-ADR-049 changes it): changing the project
 * (`project_write`: re-pin, restore), a producer's store the project names
 * that matches no configured one, writing the stores (`store_write`: re-pin,
 * restore), a producer without commands (`no_commands`), versions whose
 * command the producer cannot rebuild (`command_not_rebuildable`: check and
 * restore of a local group none of whose pins has a call, re-pin of a group
 * with such a pin chosen from the store: a local group's, or one a plan
 * group's set got by hand), offline mode (check, re-pin, restore), a closed
 * set (re-pin), a job of the project starting or running (every job), and
 * for a restore a group with no missing version. „Zamknij zestaw” of an open
 * set is disabled with every reason that holds (`closeReasons`): a job that
 * writes into the set waits or runs (the project's jobs that `GET
 * /jobs?project=` lists queued or running), a pin not `ok` at the last scan,
 * no pin at all. The card lists the reasons in force once (`ReasonList`);
 * each disabled button points at its own (`aria-describedby`). The project's
 * „Sprawdź aktualizacje” checks the groups that can be checked and is
 * disabled only when none can.
 *
 * When a job ends the card is read again; what the job found at each pin
 * (`result.pins`) stays beside the pin until the next job starts
 * (`PinMark`), and its summary under the project's actions.
 */

import { listCommands, listJobs, startProjectJob } from "../api.js";
import { useApp } from "../context.js";
import { int, plural } from "../format.js";
import { useResource } from "../hooks.js";
import { T, t } from "../labels/index.js";
import { projectJobs as L } from "../labels/project-jobs.js";
import { html, Icon, Tech } from "../ui.js";
import { Badge, FINAL_STATES, seconds, SUMMARY_STATES, useJob } from "./cards.js";

// The job kind of each action.
const KINDS = {
  verify: "project_verify",
  check: "project_check",
  repin: "project_repin",
  restore: "project_restore",
};
// The actions that run the producer's calls, and those that write the store.
const CALLING = new Set(["check", "repin", "restore"]);
const WRITING = new Set(["repin", "restore"]);
// The order of the reasons in the card's list.
const ORDER = [
  "write",
  "unknown_store",
  "store_write",
  "no_commands",
  "command_not_rebuildable",
  "offline",
  "set_closed",
  "running",
  "no_groups",
  "no_missing",
  "set_job_active",
  "set_pins_not_ok",
  "set_empty",
];
// The states of a job that waits or runs, and the most jobs of each listed.
const ACTIVE_STATES = ["queued", "running"];
const ACTIVE_LIMIT = 200;
// The states of a pin that keep its set from closing, as the server counts them.
const NOT_OK = ["missing", "sha256_mismatch", "unknown"];
const MARK_LEVEL = {
  ok: "ok",
  current: "ok",
  restored: "ok",
  newer: "warn",
  content_match: "warn",
  removed: "warn",
  unverifiable: "warn",
  not_checkable: "warn",
  not_restorable: "warn",
};

/**
 * @typedef {{key: string, text: string}} Reason - `key`: the reason with
 *   its producer (`no_commands:obserwator`), one entry of the card's list.
 */

/**
 * The jobs of a project's card: the followed job, `contextOf(card)` (the
 * state the reasons need), `start(kind, groups, planJob)` (resolves to the
 * started job, null when refused; `planJob`: the check whose plan a re-pin
 * or a restore confirms), the marks of the pins and `reload()`, which reads
 * the project's waiting and running jobs again.
 *
 * @param {string} project - Project id.
 * @param {() => void} onEnd - Called when a job ends (the card is read again).
 */
export function useProjectJobs(project, onEnd) {
  const { session, settings } = useApp();
  const commands = useResource((signal) => listCommands({ signal }), []);
  const job = useJob({ onEnd });
  const busy = job.starting || job.running;
  // Read again when the followed job starts or ends, and on `reload`.
  const active = useResource(
    (signal) => activeJobs(project, signal),
    [project, job.id, job.running],
  );
  // Null until known (or when it cannot be asked): the server then decides.
  const producers = commands.data
    ? new Set(commands.data.items.map((item) => item.producer))
    : null;
  const contextOf = (card) => ({
    card,
    storeWrite: Boolean(session?.store_write),
    offline: Boolean(settings?.offline),
    commands: producers,
    active: active.data ?? [],
    busy,
  });
  const start = (kind, groups = null, planJob = null) => {
    const body = { kind };
    if (groups) body.groups = groups;
    if (planJob) body.plan_job = planJob;
    return job.run(() => startProjectJob(project, body), KINDS[kind]);
  };
  return { job, busy, contextOf, start, marks: pinMarks(job), reload: active.reload };
}

/**
 * The project's jobs that wait or run (`GET /jobs?project=`): its own and
 * the downloads pinning into it.
 *
 * @param {string} project
 * @param {AbortSignal} signal
 * @returns {Promise<import("../types.js").JobDetail[]>}
 */
async function activeJobs(project, signal) {
  const pages = await Promise.all(
    ACTIVE_STATES.map((state) => listJobs({ project, state, limit: ACTIVE_LIMIT }, { signal })),
  );
  return pages.flatMap((page) => page.items);
}

/** A reason of the card's list (`L.why[key]`; `key` may carry `:<producer>`). */
export function reason(key, values = {}) {
  const base = key.split(":")[0];
  return { key, text: t(L.why[base], values) };
}

/** The producers of a group: a plan group's own, a local group's of its pins. */
function groupProducers(group) {
  if (group.origin.kind === "plan") return group.origin.producer ? [group.origin.producer] : [];
  return [...new Set(group.pins.map((pin) => pin.producer))];
}

/**
 * Whether D5 keeps `kind` of a group from starting (A-ADR-049 decision 12).
 * The pins chosen from the store — a local group's, and those a plan group's
 * set got by hand (`calls` `[]`) — are checked and restored by their own
 * calls, and a re-pin rebuilds each of them; a plan group's other pins go by
 * its calls.
 */
function notRebuildable(kind, group) {
  const local = group.origin.kind === "local";
  const own = local ? group.pins : group.pins.filter((pin) => pin.calls?.length === 0);
  if (!own.length) return false;
  const refused = (pin) => pin.command === "not_rebuildable";
  return kind === "repin" ? own.some(refused) : local && own.every(refused);
}

/** The first reason of a group's own that keeps a calling job from it, or null. */
function groupReason(kind, group, context) {
  const { card } = context;
  const producers = groupProducers(group);
  for (const producer of producers) {
    const entry = card.stores.find((item) => item.producer === producer);
    if (!entry?.store) return reason(`unknown_store:${producer}`, { producer });
  }
  if (WRITING.has(kind) && !context.storeWrite) return reason("store_write");
  for (const producer of producers) {
    if (context.commands && !context.commands.has(producer)) {
      return reason(`no_commands:${producer}`, { producer });
    }
  }
  if (notRebuildable(kind, group)) return reason("command_not_rebuildable");
  return null;
}

/**
 * Why `kind` of a group cannot start now (`null`: it can).
 *
 * @param {"check"|"repin"|"restore"} kind
 * @param {import("../types.js").ProjectGroup} group
 * @returns {Reason|null}
 */
export function groupJobReason(kind, group, context) {
  if (WRITING.has(kind) && !context.card.project_write) return reason("write");
  const own = groupReason(kind, group, context);
  if (own) return own;
  if (context.offline) return reason("offline");
  if (kind === "repin" && group.state === "closed") return reason("set_closed");
  if (context.busy) return reason("running");
  if (kind === "restore" && !group.pins.some((pin) => pin.state === "missing")) {
    return reason("no_missing");
  }
  return null;
}

/**
 * Why „Zamknij zestaw” cannot close an open set now, every reason that holds
 * (the server checks them again): a job that writes into the set waits or
 * runs (a `download` pinning into it, a `project_repin` of it; names
 * compared case-folded), pins not `ok` at the last scan, or no pin at all.
 *
 * @param {import("../types.js").ProjectGroup} group
 * @returns {Reason[]} Empty: it can close.
 */
export function closeReasons(group, context) {
  const { card } = context;
  const name = fold(group.name);
  const kinds = new Set(
    context.active.filter((job) => writesInto(job, card.project, name)).map((job) => job.kind),
  );
  const reasons = [...kinds].map((kind) =>
    reason(`set_job_active:${kind}`, { kind: T.common.job_kind[kind] ?? kind }),
  );
  if (!group.pins.length) return [...reasons, reason("set_empty")];
  const counts = NOT_OK.map((state) => group.pins.filter((pin) => pin.state === state).length);
  const total = counts.reduce((sum, value) => sum + value, 0);
  if (total) {
    const [missing, mismatch, unknown] = counts.map(int);
    const values = { count: int(total), missing, mismatch, unknown };
    reasons.push({
      key: `set_pins_not_ok:${counts.join("-")}`,
      text: t(plural(total, L.why.set_pins_not_ok), values),
    });
  }
  return reasons;
}

/** Whether a job of the project's list writes into its set of the folded name `name`. */
function writesInto(job, project, name) {
  const params = job.params ?? {};
  if (job.kind === "download") {
    return params.pin?.project === project && fold(params.pin.group ?? "") === name;
  }
  if (job.kind === "project_repin") {
    return params.project === project && fold(params.groups?.[0] ?? "") === name;
  }
  return false;
}

/** A set's name as the server compares names: case-folded (as Python's `casefold`). */
function fold(name) {
  return name.toUpperCase().toLowerCase();
}

/**
 * The project's „Weryfikuj” or „Sprawdź aktualizacje”: why it cannot start
 * (`null`: it can) and the groups it names (`null`: every group). A check
 * names the groups that can be checked when some cannot.
 *
 * @param {"verify"|"check"} kind
 * @returns {{why: Reason|null, groups: string[]|null}}
 */
export function projectJob(kind, context) {
  const { card } = context;
  if (!card.groups.length) return { why: reason("no_groups"), groups: null };
  let groups = null;
  if (kind === "check") {
    const own = card.groups.map((group) => groupReason(kind, group, context));
    const fit = card.groups.filter((_, place) => own[place] === null);
    if (!fit.length) return { why: own[0], groups: null };
    if (fit.length < card.groups.length) groups = fit.map((group) => group.name);
    if (context.offline) return { why: reason("offline"), groups };
  }
  if (context.busy) return { why: reason("running"), groups };
  return { why: null, groups };
}

/** The id of a reason's entry in the card's list. */
export function reasonId(base, why) {
  return `${base}-${why.key.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

/**
 * The reasons in force, each once, in the card's order; a disabled button
 * points at its own entry (`reasonId`).
 *
 * @param {{base: string, reasons: Array<Reason|null>}} props
 */
export function ReasonList({ base, reasons }) {
  const unique = new Map();
  for (const why of reasons) if (why && !unique.has(why.key)) unique.set(why.key, why);
  if (!unique.size) return null;
  const rank = (why) => ORDER.indexOf(why.key.split(":")[0]);
  const sorted = [...unique.values()].sort((a, b) => rank(a) - rank(b));
  return html`<ul class="pc-why" aria-label=${L.reasons}>
    ${sorted.map((why) => html`<li key=${why.key} id=${reasonId(base, why)}>${why.text}</li>`)}
  </ul>`;
}

/**
 * A job's action: disabled with its reason (pointing at the card's list) or
 * calling `onClick`.
 */
export function JobButton({ icon, label, ariaLabel = null, title, why, base, onClick }) {
  return html`<button type="button" class="btn sm" disabled=${why !== null}
    aria-label=${ariaLabel} title=${why ? why.text : title}
    aria-describedby=${why ? reasonId(base, why) : null} onClick=${onClick}>
    <${Icon} name=${icon} size=${14} />${label}</button>`;
}

export function pinKey(group, producer, version) {
  return `${group}\n${producer}\n${version}`;
}

/** What the followed job found at each pin, once it ended with pins. */
function pinMarks(job) {
  const events = job.events;
  if (!events || !FINAL_STATES.has(events.state)) return null;
  if (!Array.isArray(events.result?.pins)) return null;
  const rows = new Map(
    events.result.pins.map((row) => [pinKey(row.group, row.producer, row.version), row]),
  );
  return { kind: job.kind, rows };
}

/** The badge level of what a job found at a pin (its `status`). */
export function markLevel(status) {
  return MARK_LEVEL[status] ?? "bad";
}

/**
 * What the last job of the project found at a pin, with the newer label, the
 * other version of the same content or the producer's reason.
 */
export function PinMark({ marks, group, pin }) {
  const row = marks?.rows.get(pinKey(group, pin.producer, pin.version));
  if (!row) return null;
  const word = L.mark[marks.kind]?.[row.status] ?? row.status;
  let extra = null;
  if (row.status === "newer" && row.available_label) {
    extra = t(L.newer, { label: row.available_label });
  } else if (row.found) {
    extra = t(L.found, { version: row.found });
  } else if (row.reason) {
    extra = L.not_restored[row.reason] ?? row.reason;
  } else if (row.detail) {
    extra = row.detail;
  }
  const values = [["status", row.status]];
  for (const name of ["available_label", "found", "reason"]) {
    if (row[name]) values.push([name, row[name]]);
  }
  return html`<span class="pc-pin-mark">
    <${Badge} level=${markLevel(row.status)}>
      <${Tech} value=${values}>${word}</${Tech}>
    </${Badge}>
    ${extra ? html`<span class="pc-pin-why">${extra}</span>` : null}
  </span>`;
}

/** A pin whose command the producer cannot rebuild: the mark and the producer's text (D5). */
export function PinCommand({ pin }) {
  if (pin.command !== "not_rebuildable") return null;
  return html`<span class="pc-pin-command">
    <${Badge} level="warn" title=${L.command.not_rebuildable_title}>
      ${L.command.not_rebuildable}</${Badge}>
    ${pin.command_refusal ? html`<span class="pc-pin-why">${pin.command_refusal}</span>` : null}
  </span>`;
}

/**
 * The summary of a project's job: its pins by state, a check's new positions
 * at the source, a re-pin's change of its group.
 *
 * @param {import("./cards.js").JobEvents} events
 * @param {string|null} kind - The job's kind.
 */
export function projectJobSummary(events, kind) {
  const result = events.result;
  if (!result || !SUMMARY_STATES.has(events.state)) return null;
  const lines = [];
  if (kind === "project_repin") {
    const values = { group: result.group, ...result.pins };
    if (!result.written) {
      lines.push(t(L.done.repin_not_written, values));
    } else {
      const text = result.status === "replaced" ? L.done.repin_replaced : L.done.repin_unchanged;
      lines.push(t(text, values));
    }
  } else if (Array.isArray(result.pins)) {
    const words = L.mark[kind] ?? {};
    const counts = Object.entries(result.counts ?? {})
      .filter(([, value]) => value > 0)
      .map(([status, value]) => `${words[status] ?? status} ${int(value)}`);
    if (!result.pins.length && kind === "project_restore") lines.push(L.done.nothing_missing);
    else lines.push(t(L.done.pins, { total: int(result.pins.length), counts: counts.join(", ") }));
    if (result.added?.length) lines.push(t(L.done.added, { count: int(result.added.length) }));
  }
  if (result.seconds !== undefined) {
    lines.push(t(L.done.seconds, { seconds: seconds(result.seconds) }));
  }
  return html`${lines.map((line, place) => html`<p key=${place} class="job-summary">${line}</p>`)}`;
}
