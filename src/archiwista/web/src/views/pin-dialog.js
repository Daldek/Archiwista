/**
 * „Dodaj do projektu…” (docs/SPEC.md 6.5 g; A-ADR-049 decision 8): versions
 * the store holds pinned into a group of a project. „Stan lokalny” of an
 * area (map/coverage.js) and the Katalog (views/catalog.js) pin the rows of
 * their query on every page (`query`), the file card (views/file.js) the
 * version chosen on its timeline (`versions`). The window names what will
 * be pinned with its count, „Projekt” (the projects the session may change,
 * `project_write`) and the group: a new one by its name, or a local group of
 * the project (a group of the plan window takes only what it downloaded). A
 * refusal shows at its field: the project (`403`, `404`), the group
 * (`invalid_group_name`, `group_exists`, `group_origin_plan`) or what will
 * be pinned (`too_many_pins`, `other_store`, `unknown_store`). The outcome
 * says what was pinned, what the group held already and what was skipped
 * with why, and leads to the project.
 */

import { addGroupPins, addProjectGroup, getProject, listProjects, listSlots } from "../api.js";
import { count, int } from "../format.js";
import { useResource } from "../hooks.js";
import { t } from "../labels/index.js";
import { pins as L } from "../labels/pins.js";
import { Link } from "../router.js";
import {
  html,
  Icon,
  loadStylesheet,
  Modal,
  ProblemView,
  Spinner,
  Tech,
  useId,
  useState,
} from "../ui.js";

await loadStylesheet(new URL("./pin.css", import.meta.url));

/** Pins a group holds at most (`MAX_GROUP_PINS` of the server). */
export const MAX_GROUP_PINS = 10_000;
/** Characters of a group's name at most (`MAX_GROUP_NAME_CHARS`). */
export const MAX_GROUP_NAME = 80;
/** The filters of `GET /slots` a pin request's `query` holds (`SlotFilters`). */
const QUERY_FILTERS = [
  "q",
  "store",
  "product",
  "country",
  "years",
  "unit",
  "versions",
  "status",
  "project",
  "location",
  "area_id",
  "bbox",
  "bbox_crs",
];
const GROUP_REASONS = new Set([
  "invalid_group_name",
  "group_exists",
  "group_origin_plan",
  "group_not_found",
]);
const WHAT_REASONS = new Set(["too_many_pins", "other_store", "unknown_store"]);

/**
 * The filters of a query as a pin request names them: no page, no empty value.
 *
 * @param {Object<string, *>} filters
 * @returns {Object<string, string>}
 */
export function pinQuery(filters) {
  const query = {};
  for (const name of QUERY_FILTERS) {
    if (filters[name]) query[name] = filters[name];
  }
  return query;
}

/**
 * Rows of a `GET /slots` answer in its location group (`location`).
 *
 * @param {import("../types.js").LocationGroups} groups
 * @param {string} [location] - `any` (the default), `with` or `none`.
 * @returns {number}
 */
export function queryRows(groups, location) {
  if (location === "with") return groups.footprint + groups.country;
  if (location === "none") return groups.none;
  return groups.footprint + groups.country + groups.none;
}

let pending = null;

/**
 * The projects the session may change and whose file is read: the controls
 * shown together share one request.
 *
 * @returns {Promise<import("../types.js").ProjectItem[]>}
 */
export function writableProjects() {
  if (pending === null) {
    const promise = listProjects().then((list) =>
      list.items.filter((item) => item.project_write && item.state === "ok"),
    );
    const clear = () => {
      if (pending === promise) pending = null;
    };
    promise.then(clear, clear);
    pending = promise;
  }
  return pending;
}

/** The projects the session may change (`writableProjects`) as a resource. */
export function useWritableProjects() {
  return useResource(() => writableProjects(), []);
}

/**
 * „Dodaj do projektu…”: disabled with its reason when the session may change
 * no project or the choice is empty or larger than a group holds.
 *
 * @param {object} props
 * @param {"local_state"|"catalog"|"file"} props.source
 * @param {Object<string, *>|null} [props.query] - The filters of `GET /slots`.
 * @param {Array<{store: string, version: string}>|null} [props.versions]
 * @param {string} props.what - What will be pinned, in words.
 * @param {number|null} [props.rows] - Rows of the query when known.
 * @param {(outcome: import("../types.js").PinOutcome) => void} [props.onPinned]
 */
export function PinButton({ source, query = null, versions = null, what, rows = null, onPinned }) {
  const id = useId();
  const projects = useWritableProjects();
  const [open, setOpen] = useState(false);
  let why = null;
  if (projects.data && !projects.data.length) why = L.no_project;
  else if (rows === 0) why = L.nothing;
  else if (rows !== null && rows > MAX_GROUP_PINS) {
    why = t(L.too_many, { limit: int(MAX_GROUP_PINS), count: int(rows) });
  }
  const whyId = `${id}-why`;
  return html`<span class="pin-open">
    <button type="button" class="btn sm" disabled=${!projects.data || why !== null}
      title=${why ?? L.open_title} aria-describedby=${why ? whyId : null}
      onClick=${() => setOpen(true)}>
      <${Icon} name="pin" size=${13} />${L.open}</button>
    ${why ? html`<span class="visually-hidden" id=${whyId}>${why}</span>` : null}
    ${open
      ? html`<${PinDialog} source=${source} query=${query} versions=${versions} what=${what}
          onPinned=${onPinned} onClose=${() => setOpen(false)} />`
      : null}
  </span>`;
}

/**
 * The window of „Dodaj do projektu…”.
 *
 * @param {object} props - As `PinButton`, and `onClose`.
 */
export function PinDialog({ source, query, versions, what, onPinned, onClose }) {
  const id = useId();
  const projects = useWritableProjects();
  const queryKey = JSON.stringify(query);
  const rows = useResource(async (signal) => {
    if (!query) return versions.length;
    const page = await listSlots({ ...query, limit: 1 }, { signal });
    return queryRows(page.groups, query.location);
  }, [queryKey]);
  const [form, setForm] = useState({ project: null, mode: "new", name: "", group: null });
  const [refusal, setRefusal] = useState(null);
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState(null);
  const items = projects.data ?? [];
  const project = form.project ?? items[0]?.project ?? null;
  const card = useResource(
    (signal) => (project ? getProject(project, { signal }) : Promise.resolve(null)),
    [project],
  );
  const local = (card.data?.groups ?? []).filter((group) => group.origin.kind === "local");
  const mode = local.length ? form.mode : "new";
  const group = (local.find((item) => item.name === form.group) ?? local[0])?.name ?? null;
  const total = rows.data ?? null;
  const tooMany = total !== null && total > MAX_GROUP_PINS;
  const named = mode === "new" ? form.name.trim() !== "" : group !== null;
  const ready = !saving && project !== null && total !== null && total > 0 && !tooMany && named;
  const change = (patch) => {
    setForm((now) => ({ ...now, ...patch }));
    setRefusal(null);
  };
  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setSaving(true);
    setRefusal(null);
    const body = query ? { from: source, query } : { from: source, versions };
    try {
      const done =
        mode === "new"
          ? await addProjectGroup(project, { ...body, name: form.name.trim() })
          : await addGroupPins(project, group, body);
      setOutcome(done);
      onPinned?.(done);
    } catch (error) {
      if (!error.problem) throw error;
      setRefusal({ problem: error.problem, field: pinRefusalField(error) });
    } finally {
      setSaving(false);
    }
  };
  const at = (field) => (refusal?.field === field ? refusal.problem : null);
  if (outcome) return html`<${PinOutcome} outcome=${outcome} onClose=${onClose} />`;
  return html`<${Modal} label=${L.title} onClose=${onClose}>
    <form class="pin-form" onSubmit=${submit}>
      <h2>${L.title}</h2>
      <div class=${`field${at("what") ? " invalid" : ""}`}>
        <span class="field-label">${L.what}</span>
        <p class="pin-what">${what}</p>
        <div class="pin-count">
          ${rows.error
            ? html`<${ProblemView} problem=${rows.error.problem} compact />`
            : total === null
              ? html`<${Spinner} label=${L.counting} />`
              : html`<b>${count(total, query ? L.rows : L.versions)}</b>`}
        </div>
        <${FieldNote} id=${`${id}-what-note`} problem=${at("what")} error=${tooMany}>
          ${total === 0 ? L.nothing : null}
          ${tooMany ? t(L.too_many, { limit: int(MAX_GROUP_PINS), count: int(total) }) : null}
        </${FieldNote}>
      </div>
      <div class=${`field${at("project") ? " invalid" : ""}`}>
        <label for=${`${id}-project`}>${L.project}</label>
        ${projects.error
          ? html`<${ProblemView} problem=${projects.error.problem} compact />`
          : null}
        <select id=${`${id}-project`} value=${project ?? ""} disabled=${!items.length}
          aria-invalid=${at("project") ? "true" : null} aria-describedby=${`${id}-project-note`}
          onChange=${(event) => change({ project: event.currentTarget.value, group: null })}>
          ${items.map(
            (item) => html`<option key=${item.project} value=${item.project}>${item.name}</option>`,
          )}
        </select>
        <${FieldNote} id=${`${id}-project-note`} problem=${at("project")}>
          ${projects.data && !items.length ? L.no_project : L.project_hint}
        </${FieldNote}>
      </div>
      <fieldset class=${`field pin-group${at("group") ? " invalid" : ""}`}>
        <legend>${L.group}</legend>
        <label class="check-field">
          <input type="radio" name=${`${id}-mode`} checked=${mode === "new"}
            onChange=${() => change({ mode: "new" })} />${L.new_group}</label>
        ${mode === "new"
          ? html`<label class="visually-hidden" for=${`${id}-name`}>${L.name}</label>
              <input id=${`${id}-name`} value=${form.name} maxlength=${MAX_GROUP_NAME}
                autocomplete="off" aria-invalid=${at("group") ? "true" : null}
                aria-describedby=${`${id}-group-note`}
                onInput=${(event) => change({ name: event.currentTarget.value })} />`
          : null}
        <label class="check-field">
          <input type="radio" name=${`${id}-mode`} checked=${mode === "local"}
            disabled=${!local.length}
            onChange=${() => change({ mode: "local" })} />${L.local_group}</label>
        ${mode === "local"
          ? html`<label class="visually-hidden" for=${`${id}-local`}>${L.local_group}</label>
              <select id=${`${id}-local`} value=${group ?? ""}
                aria-invalid=${at("group") ? "true" : null} aria-describedby=${`${id}-group-note`}
                onChange=${(event) => change({ group: event.currentTarget.value })}>
                ${local.map(
                  (item) => html`<option key=${item.name} value=${item.name}>${item.name}</option>`,
                )}
              </select>`
          : null}
        <${FieldNote} id=${`${id}-group-note`} problem=${at("group")}>
          ${mode === "new" ? L.name_hint : L.local_group_hint}
          ${card.data && !local.length ? ` ${L.no_local_groups}` : ""}
        </${FieldNote}>
      </fieldset>
      ${refusal && refusal.field === null
        ? html`<${ProblemView} problem=${refusal.problem} compact />`
        : null}
      <div class="modal-actions">
        <button type="button" class="btn" disabled=${saving} onClick=${onClose}>${L.cancel}</button>
        <button type="submit" class="btn primary" disabled=${!ready}>
          ${saving
            ? html`<span class="spinner" aria-hidden="true"></span>`
            : html`<${Icon} name="pin" size=${14} />`}
          ${L.submit}</button>
      </div>
    </form>
  </${Modal}>`;
}

/**
 * The note under a field: the refusal at it (`problem`), else its hint, in
 * the colour of an error with `error`.
 *
 * @param {{id: string, problem: object|null, error?: boolean, children: *}} props
 */
export function FieldNote({ id, problem, error = false, children }) {
  if (problem) {
    return html`<span class="field-error" id=${id} role="alert">${problem.detail}</span>`;
  }
  return html`<span class=${error ? "field-error" : "field-hint"} id=${id}>${children}</span>`;
}

/**
 * The field a pin's refusal belongs to: `project`, `group` or `what` (what
 * will be pinned); `null`: the request as a whole.
 *
 * @param {import("../api.js").ApiError} error
 * @returns {"project"|"group"|"what"|null}
 */
export function pinRefusalField(error) {
  const reason = error.problem.details?.reason ?? null;
  if (GROUP_REASONS.has(reason)) return "group";
  if (WHAT_REASONS.has(reason)) return "what";
  if (error.status === 403 || error.status === 404) return "project";
  // The name is the only value typed here that the server's model checks.
  if (error.status === 422) return "group";
  return null;
}

/** What a pin request did, with a link to the project. */
function PinOutcome({ outcome, onClose }) {
  const card = outcome.project;
  return html`<${Modal} label=${L.title} onClose=${onClose}>
    <h2>${L.title}</h2>
    <p class="pin-done" role="status"><${Icon} name="check" size=${15} />
      <span>${t(L.done, {
        group: outcome.group,
        project: card.name,
        pinned: int(outcome.pinned),
        already: int(outcome.already),
        skipped: int(outcome.skipped.length),
      })}</span></p>
    ${outcome.skipped.length
      ? html`<div class="pin-skipped">
          <span class="section-title">${L.skipped}</span>
          <ul aria-label=${L.skipped}>${outcome.skipped.map(
            (item) => html`<li key=${`${item.store}/${item.version}`}>
              <${Tech} value=${[["store", item.store], ["reason", item.reason]]}>
                <span class="mono">${item.version}</span></${Tech}>:
              ${L.skip_reason[item.reason] ?? item.reason}
            </li>`,
          )}</ul>
        </div>`
      : null}
    <div class="modal-actions">
      <span onClick=${onClose}>
        <${Link} class="btn" view="projects" params=${{ project: card.project }}>
          <${Icon} name="folder" size=${14} />${L.open_project}</${Link}>
      </span>
      <button type="button" class="btn primary" autofocus onClick=${onClose}>${L.close}</button>
    </div>
  </${Modal}>`;
}
