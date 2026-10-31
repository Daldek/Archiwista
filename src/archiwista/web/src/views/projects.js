/**
 * The Projects view (docs/SPEC.md UC-06, 6.5 g; plan v0.4 T7; A-ADR-049): the
 * projects found in the project directories that the session sees — as the
 * API filters them, nothing filtered here — each a directory with
 * Archiwista's file `archiwista-project.json`: its name and description, the
 * store of each producer whose versions it pins, its groups of pinned
 * versions, the missing ones, and an invalid or newer file. „Nowy projekt…”:
 * every person creates a project in a project directory of the settings
 * (its directory, name, description and area; Archiwista writes the file)
 * and owns it.
 *
 * The chosen project (`?view=projects&project=<id>`) is in the side panel:
 * its directory to copy, the store of each producer with its match or that
 * it matches no configured one, its area with the state of the area file,
 * when and by whom it was created, its problems, and its groups in the file's
 * order — each with where its versions came from (a plan's commands to copy,
 * or the requests that chose them from the store) and its pins with their
 * state, leading to their file cards. „Zmień…” changes the name, the
 * description, the area and the store of a producer; „Udostępnij…” opens the
 * sharing screen (views/sharing.js): who sees the project, its owner and its
 * data folder. Both are the owner's or an administrator's
 * (`project_write`); otherwise they are disabled with the reason. Beside the
 * groups, „Dane własne” (SPEC 4.7.1): the project's data folder with its
 * state, files, sizes and problems, each file with its change since its last
 * snapshot leading to its card (views/own.js), „Odśwież” (an `own_scan` of
 * the folder, followed to its end; after the sharing screen changed the
 * folder, the scan the server started) and „Pokaż na mapie” (the project's
 * map: its own data and pinned versions). Between them „Zestawy”, the
 * project's exports with „Eksportuj…” (views/project-exports.js).
 */

import {
  createProject,
  getProject,
  listJobs,
  listOwnFiles,
  listProjects,
  setProjectArea,
  setProjectStore,
  startProjectScan,
  updateProject,
  uploadArea,
} from "../api.js";
import { useApp } from "../context.js";
import { count, int, size, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { projects as L } from "../labels/projects.js";
import { previews as P } from "../labels/previews.js";
import { T, t } from "../labels/index.js";
import { ChangeBadge, OwnCardLink, ownName, PROJECT_PARAM, StateBadge } from "../map/own.js";
import { ViewLayout } from "../panels.js";
import { Link, setParams } from "../router.js";
import {
  CopyButton,
  html,
  Icon,
  ProblemView,
  Seg,
  Spinner,
  Tech,
  useEffect,
  useId,
  useState,
} from "../ui.js";
import {
  Badge,
  FileLink,
  IssueList,
  JobStatus,
  loadCardStyles,
  pathToCopy,
  pinStateName,
  ServerPath,
  StaleNote,
  storeName,
  useJob,
} from "./cards.js";
import { ProjectExports } from "./project-exports.js";
import { SharingDialog } from "./sharing.js";

await loadCardStyles();

const ALL = "";
// Own files of one page of the group (the API's largest).
const OWN_PAGE = 200;
const FOLDER_LEVEL = { ok: "ok", missing: "bad", unreadable: "bad", invalid: "bad" };
const AREA_LEVEL = { ok: "ok", missing: "bad", changed: "warn", invalid: "bad" };

/**
 * The Projects view (route `projects`).
 *
 * @param {{route: import("../router.js").Route}} props - Parameters:
 *   `project` (the chosen project's id), `store` (only projects of a store).
 */
export default function ProjectsView({ route }) {
  const chosen = route.params.project || null;
  const store = route.params.store || null;
  const list = useResource(
    (signal) => listProjects(store ? { store } : {}, { signal }),
    [store],
  );
  const panel = {
    label: L.panel,
    open: chosen !== null,
    onClose: () => setParams({ project: null }),
    content: chosen
      ? html`<${ProjectCard} key=${chosen} id=${chosen} onChanged=${list.reload} />`
      : null,
  };
  return html`<${ViewLayout} id="projects" right=${panel}>
    <${ProjectList} list=${list} chosen=${chosen} store=${store} route=${route} />
  </${ViewLayout}>`;
}

function ProjectList({ list, chosen, store, route }) {
  const { health, settings } = useApp();
  const id = useId();
  const [creating, setCreating] = useState(false);
  const stores = health?.stores ?? [];
  const items = list.data?.items ?? [];
  const pick = (project) => setParams({ project });
  const createWhy = settings && !settings.project_dirs?.length ? L.create.no_dirs : null;
  return html`<div class="center-bar">
      <h1 class="view-title">${L.title}</h1>
      ${list.data ? html`<span class="faint">${count(items.length, L.count)}</span>` : null}
      ${stores.length > 1
        ? html`<div class="filter-group">
            <span class="filter-label">${L.store_filter}</span>
            <${Seg} small label=${L.store_filter} value=${store ?? ALL}
              onChange=${(value) => setParams({ store: value || null, project: null })}
              options=${[
                { value: ALL, label: L.all_stores },
                ...stores.map((item) => ({ value: item.store, label: item.name })),
              ]} />
          </div>`
        : null}
      <div class="pc-new-open">
        <button type="button" class="btn sm" disabled=${createWhy !== null || creating}
          title=${createWhy ?? L.create.open_title}
          aria-describedby=${createWhy ? `${id}-why` : null}
          onClick=${() => setCreating(true)}><${Icon} name="plus" size=${14} />${L.create.open}</button>
        ${createWhy
          ? html`<span class="faint pc-why-inline" id=${`${id}-why`}>${createWhy}</span>`
          : null}
      </div>
    </div>
    <div class="cards-scroll">
      ${creating
        ? html`<${NewProject} onClose=${() => setCreating(false)}
            onCreated=${(card) => {
              setCreating(false);
              list.reload();
              pick(card.project);
            }} />`
        : null}
      ${list.error ? html`<${ProblemView} problem=${list.error.problem} />` : null}
      ${list.data ? html`<${StaleNote} stores=${list.data.stale_stores} />` : null}
      ${!list.data && !list.error ? html`<${Spinner} />` : null}
      ${list.data && !items.length
        ? html`<div class="cards-empty">
            <p>${L.empty}</p>
            <p class="hint">${L.empty_hint}</p>
            <${Link} class="btn sm" view="setup" params=${{ step: "projects" }}>${L.settings}</${Link}>
          </div>`
        : null}
      ${items.length
        ? html`<div class="table-wrap">
            <table class="projects-table">
              <thead><tr>
                <th scope="col">${L.columns.name}</th>
                <th scope="col">${L.columns.stores}</th>
                <th scope="col" class="num">${L.columns.groups}</th>
                <th scope="col" class="num">${L.columns.pins}</th>
                <th scope="col" class="num">${L.columns.missing_pins}</th>
                <th scope="col">${L.columns.scanned_at}</th>
              </tr></thead>
              <tbody>
                ${items.map(
                  (item) => html`<tr key=${item.project}
                    class=${item.project === chosen ? "sel" : ""}
                    onClick=${(event) => {
                      if (!event.target.closest("a, button")) pick(item.project);
                    }}>
                    <td>
                      <${Link} view="projects" params=${{ ...route.params, project: item.project }}
                        class="row-link" aria-current=${item.project === chosen ? "true" : null}>
                        ${item.name}</${Link}>
                      ${item.project !== item.name
                        ? html` <span class="faint mono">${item.project}</span>`
                        : null}
                      ${item.description
                        ? html`<p class="faint pc-row-description">${item.description}</p>`
                        : null}
                      ${item.problem
                        ? html`<p class="row-problem"><${Icon} name="alert" size=${13} />
                            <span>${fileProblem(item.problem)}</span></p>`
                        : null}
                    </td>
                    <td><${StoreLines} stores=${item.stores} /></td>
                    <td class="num tabular">${int(item.groups)}</td>
                    <td class="num tabular">${int(item.pins)}</td>
                    <td class=${item.missing_pins ? "num tabular bad-text" : "num tabular"}>
                      ${int(item.missing_pins)}</td>
                    <td class="nw">${stamp(item.scanned_at)}</td>
                  </tr>`,
                )}
              </tbody>
            </table>
          </div>`
        : null}
    </div>`;
}

/** The text of a project file that is not used: invalid, or of a newer format. */
function fileProblem(problem) {
  return L.file_problem[problem] ?? problem;
}

/**
 * The store of each producer of a project: the configured store its root
 * matches, or that it matches none (with the root the file writes).
 *
 * @param {{stores: import("../types.js").ProjectStore[]}} props
 */
function StoreLines({ stores }) {
  const { health } = useApp();
  if (!stores.length) return html`<span class="faint">${T.common.empty}</span>`;
  return stores.map(
    (item) => html`<div key=${item.producer}>
      <span class="faint mono">${item.producer}:</span>${" "}
      <${Tech} value=${[["producer", item.producer], ["root", item.root], ["store", item.store ?? "–"]]}>
        ${item.store
          ? storeName(health, item.store)
          : html`<span class="warn-text">${L.unknown_store}</span>`}
      </${Tech}>
    </div>`,
  );
}

/** The first value of a new project's directory: the first project directory of the settings. */
function initialPath(dirs) {
  return dirs.length ? `${dirs[0]}/` : "";
}

/**
 * Keep the area of a chosen geometry file (`POST /areas`), `null` without one.
 *
 * @param {File|null} file
 * @returns {Promise<string|null>} The area's id.
 */
async function keptArea(file) {
  if (!file) return null;
  const area = await uploadArea(file, { name: file.name });
  return area.id;
}

/**
 * „Nowy projekt”: the project's directory in a project directory of the
 * settings, its name, description and area (a geometry file kept as an area
 * first); Archiwista writes the project file (`POST /projects`).
 *
 * @param {{onClose: () => void,
 *   onCreated: (card: import("../types.js").ProjectCard) => void}} props
 */
function NewProject({ onClose, onCreated }) {
  const { settings } = useApp();
  const id = useId();
  const dirs = settings?.project_dirs ?? [];
  const [form, setForm] = useState({ path: initialPath(dirs), name: "", description: "", area: null });
  const [saving, setSaving] = useState(false);
  const [refusal, setRefusal] = useState(null);
  const ready = form.path.trim() !== "" && !saving;
  const change = (patch) => {
    setForm((now) => ({ ...now, ...patch }));
    setRefusal(null);
  };
  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setSaving(true);
    setRefusal(null);
    let stage = "area";
    try {
      const areaId = await keptArea(form.area);
      stage = "create";
      const body = { path: form.path.trim() };
      if (form.name.trim()) body.name = form.name.trim();
      if (form.description.trim()) body.description = form.description.trim();
      if (areaId) body.area_id = areaId;
      onCreated(await createProject(body));
    } catch (error) {
      if (!error.problem) throw error;
      const option = error.problem.details?.option ?? null;
      const field = stage === "area" ? "area" : option === "path" ? "path" : null;
      setRefusal({ problem: error.problem, field });
    } finally {
      setSaving(false);
    }
  };
  const at = (field) => (refusal?.field === field ? refusal.problem : null);
  return html`<form class="pc-form pc-new" aria-labelledby=${`${id}-title`} onSubmit=${submit}>
    <h2 class="section-title" id=${`${id}-title`}>${L.create.title}</h2>
    <div class=${`field${at("path") ? " invalid" : ""}`}>
      <label for=${`${id}-path`}>${L.create.path}</label>
      <input id=${`${id}-path`} class="mono" value=${form.path} autocomplete="off" spellcheck="false"
        aria-invalid=${at("path") ? "true" : null} aria-describedby=${`${id}-path-note`}
        onInput=${(event) => change({ path: event.currentTarget.value })} />
      ${at("path")
        ? html`<span class="field-error" id=${`${id}-path-note`} role="alert">${at("path").detail}</span>`
        : html`<span class="field-hint" id=${`${id}-path-note`}>
            ${t(L.create.path_hint, { dirs: dirs.join(", ") || "–" })}</span>`}
    </div>
    <${TextFields} id=${id} form=${form} onChange=${change} nameHint=${L.create.name_hint} />
    <${AreaField} id=${id} file=${form.area} problem=${at("area")}
      onChange=${(area) => change({ area })} />
    ${refusal && refusal.field === null ? html`<${ProblemView} problem=${refusal.problem} compact />` : null}
    <div class="pc-form-actions">
      <button type="submit" class="btn sm primary" disabled=${!ready}>
        ${saving
          ? html`<span class="spinner" aria-hidden="true"></span>`
          : html`<${Icon} name="plus" size=${14} />`}
        ${L.create.submit}</button>
      <button type="button" class="btn sm ghost" disabled=${saving} onClick=${onClose}>
        ${L.create.cancel}</button>
    </div>
  </form>`;
}

/** The name and the description of a project's form. */
function TextFields({ id, form, onChange, nameHint }) {
  return html`<div class="pc-form-row">
      <div class="field">
        <label for=${`${id}-name`}>${L.form.name}</label>
        <input id=${`${id}-name`} value=${form.name} autocomplete="off"
          aria-describedby=${`${id}-name-note`}
          onInput=${(event) => onChange({ name: event.currentTarget.value })} />
        <span class="field-hint" id=${`${id}-name-note`}>${nameHint}</span>
      </div>
    </div>
    <div class="field">
      <label for=${`${id}-description`}>${L.form.description}</label>
      <textarea id=${`${id}-description`} class="pc-description" rows="2" value=${form.description}
        onInput=${(event) => onChange({ description: event.currentTarget.value })}></textarea>
    </div>`;
}

/** A geometry file to keep as the project's area, with the server's refusal of it. */
function AreaField({ id, file, problem, label = L.form.area, onChange }) {
  return html`<div class=${`field${problem ? " invalid" : ""}`}>
    <label for=${`${id}-area`}>${label}</label>
    <input id=${`${id}-area`} type="file" accept=".geojson,.json,.gpkg,.zip"
      aria-invalid=${problem ? "true" : null} aria-describedby=${`${id}-area-note`}
      onChange=${(event) => onChange(event.currentTarget.files?.[0] ?? null)} />
    ${problem
      ? html`<span class="field-error" id=${`${id}-area-note`} role="alert">${problem.detail}</span>`
      : html`<span class="field-hint" id=${`${id}-area-note`}>
          ${file ? file.name : L.form.area_hint}</span>`}
  </div>`;
}

/**
 * The producers whose store a project may name: those of its file and the
 * available ones with a directory in some configured store.
 */
function storeProducers(card, health) {
  const stores = health?.stores ?? [];
  const names = card.stores.map((item) => item.producer);
  for (const source of health?.sources ?? []) {
    const held = stores.some((item) => item.producers.includes(source.producer));
    if (source.status === "available" && held && !names.includes(source.producer)) {
      names.push(source.producer);
    }
  }
  return names;
}

/**
 * „Zmień projekt”: its name, description, area (a new geometry file, or none)
 * and the store of each producer; each change goes by its own route
 * (`PATCH /projects/{project}`, `PUT …/area`, `PUT …/stores/{producer}`) and
 * the first refusal stops the rest.
 *
 * @param {{card: import("../types.js").ProjectCard, onClose: () => void,
 *   onSaved: () => void, onChanged: () => void}} props - `onChanged`: some
 *   change was written before a refusal.
 */
function EditProject({ card, onClose, onSaved, onChanged }) {
  const { health } = useApp();
  const id = useId();
  const producers = storeProducers(card, health);
  const current = Object.fromEntries(card.stores.map((item) => [item.producer, item.store]));
  const [form, setForm] = useState({
    name: card.name,
    description: card.description,
    area: null,
    clearArea: false,
    stores: Object.fromEntries(producers.map((name) => [name, current[name] ?? ""])),
  });
  const [saving, setSaving] = useState(false);
  const [refusal, setRefusal] = useState(null);
  const change = (patch) => {
    setForm((now) => ({ ...now, ...patch }));
    setRefusal(null);
  };
  const text = {};
  if (form.name.trim() && form.name.trim() !== card.name) text.name = form.name.trim();
  if (form.description.trim() !== card.description) text.description = form.description.trim();
  const stores = producers.filter((name) => form.stores[name] && form.stores[name] !== current[name]);
  const changes = Object.keys(text).length + stores.length + (form.area || form.clearArea ? 1 : 0);
  const ready = changes > 0 && !saving;
  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setSaving(true);
    setRefusal(null);
    let written = false;
    let field = null;
    try {
      if (Object.keys(text).length) {
        await updateProject(card.project, text);
        written = true;
      }
      if (form.area) {
        field = "area";
        const areaId = await keptArea(form.area);
        field = null;
        await setProjectArea(card.project, areaId);
        written = true;
      } else if (form.clearArea) {
        await setProjectArea(card.project, null);
        written = true;
      }
      for (const producer of stores) {
        field = `store-${producer}`;
        await setProjectStore(card.project, producer, form.stores[producer]);
        written = true;
      }
      onSaved();
    } catch (error) {
      if (!error.problem) throw error;
      setRefusal({ problem: error.problem, field });
      if (written) onChanged();
    } finally {
      setSaving(false);
    }
  };
  const at = (name) => (refusal?.field === name ? refusal.problem : null);
  return html`<form class="pc-form" aria-labelledby=${`${id}-title`} onSubmit=${submit}>
    <h3 class="section-title" id=${`${id}-title`}>${L.edit.title}</h3>
    <${TextFields} id=${id} form=${form} onChange=${change} nameHint=${L.edit.name_hint} />
    <${AreaField} id=${id} file=${form.area} problem=${at("area")}
      label=${card.area ? L.edit.area_new : L.form.area}
      onChange=${(area) => change({ area, clearArea: false })} />
    ${card.area
      ? html`<label class="check-field">
          <input type="checkbox" checked=${form.clearArea} disabled=${form.area !== null}
            onChange=${(event) => change({ clearArea: event.currentTarget.checked })} />
          <span>${L.edit.area_clear}</span>
        </label>`
      : null}
    ${producers.length
      ? html`<div class="pc-form-row">${producers.map(
          (producer) => html`<${StoreField} key=${producer} id=${`${id}-store-${producer}`}
            producer=${producer} value=${form.stores[producer] ?? ""} current=${current[producer] ?? null}
            problem=${at(`store-${producer}`)}
            onChange=${(value) => change({ stores: { ...form.stores, [producer]: value } })} />`,
        )}</div>`
      : null}
    ${refusal && refusal.field === null ? html`<${ProblemView} problem=${refusal.problem} compact />` : null}
    <div class="pc-form-actions">
      <button type="submit" class="btn sm primary" disabled=${!ready}>
        ${saving
          ? html`<span class="spinner" aria-hidden="true"></span>`
          : html`<${Icon} name="check" size=${14} />`}
        ${L.edit.submit}</button>
      <button type="button" class="btn sm ghost" disabled=${saving} onClick=${onClose}>
        ${L.edit.cancel}</button>
    </div>
  </form>`;
}

/**
 * The store of one producer's pins: a configured store with the producer's
 * directory; „—” only while the project names none that matches.
 */
function StoreField({ id, producer, value, current, problem, onChange }) {
  const { health } = useApp();
  const choices = (health?.stores ?? []).filter((item) => item.producers.includes(producer));
  return html`<div class=${`field${problem ? " invalid" : ""}`}>
    <label for=${id}>${t(L.edit.store, { producer })}</label>
    <select id=${id} value=${value} aria-invalid=${problem ? "true" : null}
      aria-describedby=${`${id}-note`} onChange=${(event) => onChange(event.currentTarget.value)}>
      ${current ? null : html`<option value="">${L.edit.store_none}</option>`}
      ${choices.map((item) => html`<option key=${item.store} value=${item.store}>${item.name}</option>`)}
    </select>
    ${problem
      ? html`<span class="field-error" id=${`${id}-note`} role="alert">${problem.detail}</span>`
      : html`<span class="field-hint" id=${`${id}-note`}>${L.edit.store_hint}</span>`}
  </div>`;
}

function ProjectCard({ id, onChanged }) {
  const cardId = useId();
  const resource = useResource((signal) => getProject(id, { signal }), [id]);
  const [editing, setEditing] = useState(false);
  const [done, setDone] = useState(null);
  const [sharing, setSharing] = useState(false);
  // Each change of the data folder on the sharing screen: „Dane własne” reads
  // the folder again and follows the scan the server started.
  const [folderRound, setFolderRound] = useState(0);
  const changed = () => {
    resource.reload();
    onChanged();
  };
  const { data: card, error } = resource;
  if (!card) {
    if (!error) return html`<${Spinner} />`;
    return error.status === 404
      ? html`<p class="hint warn">${t(L.not_found, { project: id })}</p>`
      : html`<${ProblemView} problem=${error.problem} />`;
  }
  const why = card.project_write ? null : L.why.write;
  const whyId = `${cardId}-why`;
  return html`<article class="project-card" aria-labelledby="project-card-title">
    <h2 class="pc-title" id="project-card-title">
      <${Tech} value=${[["project", card.project], ["path", card.path.local]]}>${card.name}</${Tech}>
    </h2>
    ${card.description ? html`<p class="pc-description-text">${card.description}</p>` : null}
    <${StaleNote} stores=${card.stale_stores} />
    <${ProjectFacts} card=${card} />
    <div class="pc-actions" role="group" aria-label=${L.actions.label}>
      <${ActionButton} icon="settings" label=${L.edit.open} title=${L.edit.open_title}
        why=${editing ? "" : why} whyId=${whyId}
        onClick=${() => {
          setDone(null);
          setEditing(true);
        }} />
      <${ActionButton} icon="users" label=${L.actions.share} title=${L.actions.share_title}
        why=${why} whyId=${whyId} onClick=${() => setSharing(true)} />
    </div>
    ${why ? html`<p class="pc-why" id=${whyId}>${why}</p>` : null}
    ${editing
      ? html`<${EditProject} card=${card} onClose=${() => setEditing(false)}
          onChanged=${changed}
          onSaved=${() => {
            setEditing(false);
            setDone(L.edit.saved);
            changed();
          }} />`
      : null}
    ${done
      ? html`<p class="pc-done" role="status"><${Icon} name="check" size=${15} /><span>${done}</span></p>`
      : null}
    ${card.problems.length
      ? html`<section class="det-sec">
          <h3 class="section-title">${count(card.problems.length, T.common.units.problems)}</h3>
          <${IssueList} issues=${card.problems} currentProject=${card.project} />
        </section>`
      : null}
    <${Groups} card=${card} />
    <${ProjectExports} card=${card} />
    <${OwnData} key=${card.project} project=${card.project} round=${folderRound} />
    ${sharing
      ? html`<${SharingDialog} project=${card.project} name=${card.name}
          onChanged=${(what) => {
            if (what === "folder") {
              setFolderRound((n) => n + 1);
            } else {
              changed();
            }
          }}
          onClose=${() => setSharing(false)} />`
      : null}
  </article>`;
}

/** The project's directory, stores, area, creation and reading of its file. */
function ProjectFacts({ card }) {
  const { first, server } = pathToCopy(card.path);
  return html`<dl class="kv">
    <dt>${L.card.path}</dt>
    <dd class="pc-path">
      <code class="path">${first}</code>
      <${CopyButton} text=${first} label=${L.card.copy_path} />
      <${ServerPath} path=${server} />
    </dd>
    <dt>${L.card.stores}</dt>
    <dd>${card.stores.length
      ? html`<${StoreLines} stores=${card.stores} />`
      : html`<span class="faint">${L.card.no_stores}</span>`}</dd>
    <dt>${L.card.area}</dt>
    <dd><${AreaValue} area=${card.area} /></dd>
    ${card.created_at
      ? html`<dt>${L.card.created}</dt>
          <dd>${t(L.card.created_value, { at: stamp(card.created_at), by: card.created_by ?? "–" })}</dd>`
      : null}
    <dt>${L.card.scanned_at}</dt><dd>${stamp(card.scanned_at)}</dd>
    ${card.missing_pins
      ? html`<dt>${L.card.missing_pins}</dt><dd class="bad-text tabular">${int(card.missing_pins)}</dd>`
      : null}
  </dl>`;
}

/** A project's area: its file's state and, when it is used, a link to the map. */
function AreaValue({ area }) {
  if (!area) return html`<span class="faint">${L.card.no_area}</span>`;
  const state = area.state ?? "unread";
  return html`<span class="pc-area">
    <${Badge} level=${AREA_LEVEL[state] ?? "plain"}>
      <${Tech} value=${[["path", area.path], ["sha256", area.sha256], ["state", state]]}>
        ${L.card.area_states[state] ?? state}</${Tech}>
    </${Badge}>
    <code class="path">${area.path}</code>
    ${area.state === "ok" && area.area_id
      ? html`<${Link} class="btn ghost sm" view="map" params=${{ area_id: area.area_id }}>
          <${Icon} name="map" size=${13} />${L.card.area_on_map}</${Link}>`
      : null}
  </span>`;
}

/**
 * A button of a project's action: disabled with its reason (`why`, told in
 * the card's note; `""`: disabled while its form is open) or `null` when it
 * may be used.
 */
function ActionButton({ icon, label, title, why, whyId, onClick }) {
  return html`<button type="button" class="btn sm" disabled=${why !== null}
    title=${why || title} aria-describedby=${why ? whyId : null} onClick=${onClick}>
    <${Icon} name=${icon} size=${14} />${label}</button>`;
}

/** The groups of pinned versions in the file's order, each with its origin and pins. */
function Groups({ card }) {
  return html`<section class="det-sec" aria-labelledby="pc-groups-title">
    <h3 class="section-title" id="pc-groups-title">${L.card.groups}</h3>
    ${card.groups.length
      ? html`<ul class="pc-groups">
          ${card.groups.map(
            (group) => html`<li key=${group.name} class="pc-group">
              <div class="pc-group-head">
                <b>${group.name}</b>
                <${Origin} origin=${group.origin} />
                <span class="faint">${count(group.pins.length, L.card.pin_count)}</span>
              </div>
              ${group.origin.kind === "plan"
                ? (group.origin.calls ?? []).map(
                    (call, index) => html`<${Command} key=${index} producer=${group.origin.producer}
                      call=${call} />`,
                  )
                : null}
              <${PinList} pins=${group.pins} />
            </li>`,
          )}
        </ul>`
      : html`<p class="faint">${card.state === "ok" ? L.card.no_groups : L.card.groups_unread}</p>`}
  </section>`;
}

/** Where a group's versions came from: a plan of a producer, or the store. */
function Origin({ origin }) {
  if (origin.kind === "plan") {
    return html`<${Badge} level="info">${t(L.card.origin_plan, { producer: origin.producer })}</${Badge}>`;
  }
  const sources = [...new Set((origin.selections ?? []).map((item) => item.source))];
  const named = sources.map((source) => L.card.sources[source] ?? source).join(", ");
  return html`<${Badge} level="plain">
    ${named ? t(L.card.origin_local_from, { sources: named }) : L.card.origin_local}</${Badge}>`;
}

function Command({ producer, call }) {
  const options = Object.entries(call.options);
  const text = JSON.stringify({ command: call.command, options: call.options });
  return html`<div class="cmd pc-cmd">
    <code>
      <span class="pc-cmd-name">${producer} ${call.command}</span>
      ${options.map(
        ([name, value]) => html`<span key=${name} class="pc-opt">
          <span class="pc-opt-name">${name}</span>=${typeof value === "string" ? value : JSON.stringify(value)}
        </span>`,
      )}
    </code>
    <${CopyButton} text=${text} label=${L.card.copy_command} />
  </div>`;
}

function PinList({ pins }) {
  if (!pins.length) return html`<p class="faint pc-no-pins">${L.card.no_pins}</p>`;
  return html`<ul class="pc-pins" aria-label=${L.card.pins}>
    ${pins.map(
      (pin) => html`<li key=${`${pin.producer}/${pin.version}`} class="pc-pin">
        ${pin.slot && pin.store
          ? html`<${FileLink} store=${pin.store} slot=${pin.slot} version=${pin.version}
              title=${L.card.pin_open}>
              <${Icon} name="file" size=${13} /><span class="mono">${pin.label ?? pin.version}</span>
            </${FileLink}>`
          : html`<code class="path">${pin.version}</code>`}
        ${pin.state === "ok"
          ? html`<${Badge} level=${pin.is_current ? "info" : "plain"}>
              ${pin.is_current ? L.card.pin_current : L.card.pin_older}</${Badge}>`
          : null}
        <${Badge} level=${pin.state === "ok" ? "ok" : "bad"}>
          <${Tech} value=${[
            ["state", pin.state],
            ["producer", pin.producer],
            ["version", pin.version],
            ["sha256", pin.sha256],
            ["pinned_at", pin.pinned_at],
            ["pinned_by", pin.pinned_by],
          ]}>
            ${pinStateName(pin.state)}
          </${Tech}>
        </${Badge}>
        <span class="faint tabular">${size(pin.size_bytes)}</span>
      </li>`,
    )}
  </ul>`;
}

/**
 * „Dane własne” of a project: its data folder and files, „Odśwież” with the
 * scan's progress and the project's map. A new `round` (the sharing screen
 * changed the folder) reads the folder again and follows the scan the
 * server started for it.
 */
function OwnData({ project, round }) {
  const list = useResource((signal) => listOwnFiles(project, { limit: OWN_PAGE }, { signal }), [project]);
  const [extra, setExtra] = useState({ items: [], cursor: null, loading: false, problem: null });
  const job = useJob({ onEnd: list.reload });
  const busy = job.starting || job.running;
  const page = list.data;
  useEffect(() => setExtra({ items: [], cursor: page?.next_cursor ?? null, loading: false, problem: null }), [page]);
  useEffect(() => {
    if (!round) return;
    list.reload();
    job.run(async () => (await listJobs({ kind: "own_scan", project, limit: 1 })).items[0], "own_scan");
  }, [round]);
  const refresh = () => job.run(() => startProjectScan(project), "own_scan");
  const more = async () => {
    setExtra((current) => ({ ...current, loading: true, problem: null }));
    try {
      const next = await listOwnFiles(project, { limit: OWN_PAGE, cursor: extra.cursor });
      setExtra((current) => ({ items: [...current.items, ...next.items], cursor: next.next_cursor, loading: false, problem: null }));
    } catch (error) {
      if (!error.problem) throw error;
      setExtra((current) => ({ ...current, loading: false, problem: error.problem }));
    }
  };
  const folder = page?.folder ?? null;
  const items = page ? [...page.items, ...extra.items] : [];
  return html`<section class="det-sec own-group" aria-labelledby="own-group-title">
    <div class="own-group-head">
      <h3 class="section-title" id="own-group-title">${L.own.title}</h3>
      <button type="button" class="btn sm" disabled=${busy} title=${L.own.refresh_title} onClick=${refresh}>
        ${busy ? html`<span class="spinner" aria-hidden="true"></span>` : html`<${Icon} name="rotate" size=${14} />`}
        ${L.own.refresh}
      </button>
      <${Link} class="btn sm" view="map" params=${{ [PROJECT_PARAM]: project, versions: "pinned" }}
        title=${L.own.on_map_title}><${Icon} name="map" size=${14} />${L.own.on_map}</${Link}>
    </div>
    ${list.error ? html`<${ProblemView} problem=${list.error.problem} compact />` : null}
    ${!page && !list.error ? html`<${Spinner} />` : null}
    ${folder ? html`<${OwnFolder} folder=${folder} />` : null}
    ${folder?.problems.length
      ? html`<${IssueList} issues=${folder.problems} currentProject=${project} empty=${false} />`
      : null}
    <${JobStatus} job=${job} />
    ${folder && folder.scanned_at === null ? html`<p class="hint">${L.own.not_scanned_hint}</p>` : null}
    ${folder && folder.scanned_at !== null && !items.length ? html`<p class="faint">${L.own.empty}</p>` : null}
    ${items.length
      ? html`<ul class="own-files" aria-label=${L.own.list}>
          ${items.map((item) => html`<${OwnFileRow} key=${item.file_id} project=${project} item=${item} />`)}
        </ul>`
      : null}
    ${extra.cursor
      ? html`<p class="faint">${t(L.own.shown, { shown: int(items.length), total: int(folder?.files ?? items.length) })}</p>
          <button type="button" class="btn sm" disabled=${extra.loading} onClick=${more}>${L.own.more}</button>`
      : null}
    ${extra.problem ? html`<${ProblemView} problem=${extra.problem} compact />` : null}
  </section>`;
}

/** The project's data folder: the person's own path first (`pathToCopy`), its state and counts. */
function OwnFolder({ folder }) {
  const { first, server } = pathToCopy(folder.path);
  return html`<dl class="kv own-folder">
    <dt>${L.own.folder}</dt>
    <dd class="own-folder-path">
      <code class="path">${first}</code>
      <${CopyButton} text=${first} label=${L.own.copy_folder} />
      <span class="faint">${L.own.source[folder.source] ?? folder.source}</span>
      <${ServerPath} path=${server} />
    </dd>
    <dt>${L.own.state}</dt>
    <dd><${Badge} level=${FOLDER_LEVEL[folder.state] ?? "plain"}>
      <${Tech} value=${[["state", folder.state]]}>${L.own.states[folder.state] ?? folder.state}</${Tech}>
    </${Badge}></dd>
    <dt>${L.own.files}</dt>
    <dd class="tabular">${t(L.own.files_value, { count: count(folder.files, T.common.units.files), size: size(folder.size_bytes) })}</dd>
    <dt>${L.own.snapshots}</dt>
    <dd class="tabular">${size(folder.snapshots_bytes)}</dd>
    <dt>${L.own.scanned_at}</dt>
    <dd>${folder.scanned_at ? stamp(folder.scanned_at) : html`<span class="warn-text">${L.own.not_scanned}</span>`}</dd>
  </dl>`;
}

function OwnFileRow({ project, item }) {
  const slash = item.path.lastIndexOf("/");
  const meta = [
    slash > 0 ? `${item.path.slice(0, slash)}/` : null,
    item.format ?? P.kind[item.kind] ?? item.kind,
    size(item.size_bytes),
    item.snapshots ? count(item.snapshots, L.own.file_snapshots) : null,
  ].filter(Boolean);
  return html`<li class="own-file">
    <${OwnCardLink} project=${project} fileId=${item.file_id} class="own-file-name" title=${item.path}>
      <${Icon} name="file" size=${13} /><span>${ownName(item.path)}</span>
    </${OwnCardLink}>
    <span class="own-file-marks"><${StateBadge} file=${item} /><${ChangeBadge} file=${item} /></span>
    <span class="own-file-meta">${meta.join(" · ")}</span>
  </li>`;
}
