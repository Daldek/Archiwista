/**
 * The Projects view (docs/SPEC.md UC-06, 6.5 g; plan v0.1 step 11, v0.2
 * step 15, plan 2026-10-25 A13 and I7, plan v0.4 T7): the projects found in
 * the project directories that the session sees — as the API filters them
 * (step 8b), nothing filtered here — with their manifests (a project
 * directory holds Kartograf's, IMGWTools' or both: each with its producer,
 * store, status when it was read and problem) and their missing pins, and
 * „Nowy projekt…”: every person creates a project of a producer in a project
 * directory of the settings, bound to a configured store, and owns it. The
 * chosen project (`?view=projects&project=<id>`) is in the side panel with
 * the tasks of each manifest and their existing commands, the producers'
 * status now, the pinned versions (older ones too) leading to their file
 * cards, and its problems.
 *
 * The card's actions go through a manifest's producer — of a project with
 * two manifests, the one chosen at the actions, of a task its own —:
 * „Weryfikuj”, „Sprawdź aktualizacje” and „Pobierz” start a job of the
 * manifest's tasks, „Przepnij” one of a task, each followed to its end with
 * its tasks or files and, when it fails, the producer's instruction (a left
 * lock of the manifest); a job of the project already running is followed
 * instead. A download and a repin also go to the downloads of the top bar
 * (downloads.js), so they stay in sight after the card or the view closes.
 * „+ Zadanie” adds a pasted producer's command as a task (the producer reads
 * and checks it without the network; its text for a mistake shows at the
 * field) and „Usuń” removes a task after a confirmation. „Udostępnij…” opens
 * the sharing screen (views/sharing.js): who sees the project, its owner and
 * its data folder. An action the session may not do is disabled with the
 * reason: a project is changed and shared by its owner or an administrator
 * (`project_write`), a download and a repin write the store (`store_write`)
 * the manifest names, and they and a check need the network. Beside the
 * producers' tasks, the group „Dane własne” (SPEC 4.7.1): the project's data
 * folder with its state, files, sizes and problems, each file with its change
 * since its last snapshot leading to its card (views/own.js), „Odśwież” (an
 * `own_scan` of the folder, followed to its end; after the sharing screen
 * changed the folder, the scan the server started) and „Pokaż na mapie” (the
 * project's map: its own data and pinned versions).
 */

import {
  addProjectTask,
  createProject,
  getProject,
  getProjectStatus,
  listJobs,
  listOwnFiles,
  listProjects,
  parseCommand,
  removeProjectTask,
  startProjectJob,
  startProjectScan,
} from "../api.js";
import { useApp } from "../context.js";
import { downloadName, useDownloadActions } from "../downloads.js";
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
  pinStateName,
  projectSummary,
  StaleNote,
  statusLevel,
  statusName,
  storeName,
  useJob,
} from "./cards.js";
import { SharingDialog } from "./sharing.js";

await loadCardStyles();

const ALL = "";
// Own files of one page of the group (the API's largest).
const OWN_PAGE = 200;
const FOLDER_LEVEL = { ok: "ok", missing: "bad", unreadable: "bad", invalid: "bad" };
// Why an action of a project is disabled, in the order a reason is told
// (labels `why`): who may change the project, a store to write, the
// permission to write it, the network, a job of the project running.
const REASONS = ["write", "store", "store_write", "offline", "busy"];
// The reasons each action can have.
const ACTION_REASONS = {
  verify: ["busy"],
  check: ["offline", "busy"],
  download: ["write", "store", "store_write", "offline", "busy"],
  repin: ["write", "store", "store_write", "offline", "busy"],
  change: ["write"],
  share: ["write"],
};

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
    content: chosen ? html`<${ProjectCard} key=${chosen} id=${chosen} onChanged=${list.reload} />` : null,
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
          title=${createWhy ?? L.create.open_title} aria-describedby=${createWhy ? `${id}-why` : null}
          onClick=${() => setCreating(true)}><${Icon} name="plus" size=${14} />${L.create.open}</button>
        ${createWhy ? html`<span class="faint pc-why-inline" id=${`${id}-why`}>${createWhy}</span>` : null}
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
                <th scope="col">${L.columns.producer}</th>
                <th scope="col">${L.columns.store}</th>
                <th scope="col">${L.columns.status}</th>
                <th scope="col" class="num">${L.columns.tasks}</th>
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
                      ${item.project !== item.name ? html` <span class="faint mono">${item.project}</span>` : null}
                      <${ManifestProblems} manifests=${item.manifests} />
                    </td>
                    <td class="mono">${producers(item.manifests)}</td>
                    <td>${storeLines(health, item.manifests)}</td>
                    <td>${byManifest(item.manifests, statusBadge)}</td>
                    <td class="num tabular">${int(item.tasks)}</td>
                    <td class="num tabular">${int(item.pins)}</td>
                    <td class=${item.missing_pins ? "num tabular bad-text" : "num tabular"}>${int(item.missing_pins)}</td>
                    <td class="nw">${byManifest(item.manifests, scannedAt)}</td>
                  </tr>`,
                )}
              </tbody>
            </table>
          </div>`
        : null}
    </div>`;
}

/**
 * The values of a project's manifests, one line each led by its producer; a
 * project of one manifest (the usual one) shows its value alone.
 *
 * @param {import("../types.js").ProjectManifest[]} manifests
 * @param {(manifest: import("../types.js").ProjectManifest) => *} render
 */
function byManifest(manifests, render) {
  if (manifests.length === 1) return render(manifests[0]);
  return manifests.map(
    (manifest) => html`<div key=${manifest.producer}>
      <span class="faint mono">${manifest.producer}:</span>${" "}${render(manifest)}</div>`,
  );
}

/** The producers of a project's manifests, Kartograf's first. */
function producers(manifests) {
  return manifests.map((manifest) => manifest.producer).join(", ");
}

/** The store each manifest names, or that it names none of the settings. */
function storeLines(health, manifests) {
  return byManifest(manifests, (manifest) =>
    manifest.store
      ? storeName(health, manifest.store)
      : html`<span class="warn-text">${L.no_store}</span>`,
  );
}

function statusBadge(manifest) {
  const level = statusLevel(manifest.status);
  return html`<${Badge} level=${level}>${statusName(manifest.status)}</${Badge}>`;
}

function scannedAt(manifest) {
  return stamp(manifest.scanned_at);
}

/** The producer's message of each invalid manifest of a project's row. */
function ManifestProblems({ manifests }) {
  const several = manifests.length > 1;
  return manifests
    .filter((manifest) => manifest.problem)
    .map(
      (manifest) => html`<p key=${manifest.producer} class="row-problem">
        <${Icon} name="alert" size=${13} />
        <span><b>${L.invalid}:</b>${" "}${several ? `${manifest.producer}: ` : ""}${
          manifest.problem}</span></p>`,
    );
}

/**
 * „Nowy projekt”: a producer with a directory in some store, that store and
 * the project's directory in a project directory of the settings; the
 * producer writes the manifest (`POST /projects`).
 *
 * @param {{onClose: () => void,
 *   onCreated: (card: import("../types.js").ProjectCard) => void}} props
 */
function NewProject({ onClose, onCreated }) {
  const { health, settings } = useApp();
  const id = useId();
  const [form, setForm] = useState({ producer: null, store: null, path: null });
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState(null);
  const stores = health?.stores ?? [];
  const producers = (health?.sources ?? [])
    .filter((source) => source.status === "available")
    .map((source) => source.producer)
    .filter((name) => stores.some((item) => item.producers.includes(name)));
  const producer = producers.includes(form.producer) ? form.producer : (producers[0] ?? "");
  const choices = stores.filter((item) => item.producers.includes(producer));
  const store = choices.some((item) => item.store === form.store) ? form.store : (choices[0]?.store ?? "");
  const dirs = settings?.project_dirs ?? [];
  const path = form.path ?? (dirs.length ? `${dirs[0]}/` : "");
  const field = problem?.details?.option === "path" || problem?.details?.option === "store" ? problem.details.option : null;
  const ready = producer !== "" && store !== "" && path.trim() !== "" && !saving;
  const change = (patch) => {
    setForm((now) => ({ ...now, ...patch }));
    setProblem(null);
  };
  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setSaving(true);
    setProblem(null);
    try {
      const card = await createProject({ producer, store, path: path.trim() });
      onCreated(card);
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
    } finally {
      setSaving(false);
    }
  };
  return html`<form class="pc-form pc-new" aria-labelledby=${`${id}-title`} onSubmit=${submit}>
    <h2 class="section-title" id=${`${id}-title`}>${L.create.title}</h2>
    ${producers.length
      ? html`<div class="pc-form-row">
          <div class="field">
            <label for=${`${id}-producer`}>${L.create.producer}</label>
            <select id=${`${id}-producer`} value=${producer}
              onChange=${(event) => change({ producer: event.currentTarget.value })}>
              ${producers.map((name) => html`<option key=${name} value=${name}>${name}</option>`)}
            </select>
          </div>
          <div class=${`field${field === "store" ? " invalid" : ""}`}>
            <label for=${`${id}-store`}>${L.create.store}</label>
            <select id=${`${id}-store`} value=${store} aria-invalid=${field === "store" ? "true" : null}
              aria-describedby=${`${id}-store-note`}
              onChange=${(event) => change({ store: event.currentTarget.value })}>
              ${choices.map((item) => html`<option key=${item.store} value=${item.store}>${item.name}</option>`)}
            </select>
            ${field === "store"
              ? html`<span class="field-error" id=${`${id}-store-note`} role="alert">${problem.detail}</span>`
              : html`<span class="field-hint" id=${`${id}-store-note`}>${L.create.store_hint}</span>`}
          </div>
        </div>`
      : html`<p class="hint warn" role="note">${L.create.no_producer}</p>`}
    <div class=${`field${field === "path" ? " invalid" : ""}`}>
      <label for=${`${id}-path`}>${L.create.path}</label>
      <input id=${`${id}-path`} class="mono" value=${path} autocomplete="off" spellcheck="false"
        aria-invalid=${field === "path" ? "true" : null} aria-describedby=${`${id}-path-note`}
        onInput=${(event) => change({ path: event.currentTarget.value })} />
      ${field === "path"
        ? html`<span class="field-error" id=${`${id}-path-note`} role="alert">${problem.detail}</span>`
        : html`<span class="field-hint" id=${`${id}-path-note`}>${t(L.create.path_hint, { dirs: dirs.join(", ") || "–" })}</span>`}
    </div>
    ${problem && field === null ? html`<${ProblemView} problem=${problem} compact />` : null}
    <div class="pc-form-actions">
      <button type="submit" class="btn sm primary" disabled=${!ready}>
        ${saving ? html`<span class="spinner" aria-hidden="true"></span>` : html`<${Icon} name="plus" size=${14} />`}
        ${L.create.submit}</button>
      <button type="button" class="btn sm ghost" disabled=${saving} onClick=${onClose}>${L.create.cancel}</button>
    </div>
  </form>`;
}

/**
 * The reason each action on a project's manifest is disabled now, or `null`.
 *
 * @param {import("../types.js").ProjectCard} card
 * @param {import("../types.js").ProjectManifest} manifest - The manifest acted on.
 * @param {{store_write: boolean}|null} session
 * @param {boolean} offline
 * @param {boolean} busy - A job of the project is being started or runs.
 * @returns {Object<string, string|null>} Per action (`ACTION_REASONS`), a key of `REASONS`.
 */
function blocked(card, manifest, session, offline, busy) {
  const holds = {
    write: !card.project_write,
    store: manifest.store === null,
    store_write: !session?.store_write,
    offline,
    busy,
  };
  return Object.fromEntries(
    Object.entries(ACTION_REASONS).map(([action, reasons]) => [
      action,
      reasons.find((reason) => holds[reason]) ?? null,
    ]),
  );
}

/** The store every manifest of a project names, else `null`. */
function commonStore(manifests) {
  const stores = new Set(manifests.map((manifest) => manifest.store));
  return stores.size === 1 ? manifests[0].store : null;
}

function ProjectCard({ id, onChanged }) {
  const { health, session, settings } = useApp();
  const cardId = useId();
  const resource = useResource((signal) => getProject(id, { signal }), [id]);
  const [round, setRound] = useState(0);
  const [adding, setAdding] = useState(false);
  const [done, setDone] = useState(null);
  const [producer, setProducer] = useState(null);
  const [sharing, setSharing] = useState(false);
  // Each change of the data folder on the sharing screen: „Dane własne” reads
  // the folder again and follows the scan the server started.
  const [folderRound, setFolderRound] = useState(0);
  const changed = () => {
    resource.reload();
    setRound((n) => n + 1);
    onChanged();
  };
  const job = useJob({ onEnd: changed });
  const { track } = useDownloadActions();
  const { data: card, error } = resource;
  if (!card) {
    if (!error) return html`<${Spinner} />`;
    return error.status === 404
      ? html`<p class="hint warn">${t(L.not_found, { project: id })}</p>`
      : html`<${ProblemView} problem=${error.problem} />`;
  }
  // A project of two manifests acts on the one chosen at the actions, and a
  // task through its own; the API needs the producer only then.
  const several = card.manifests.length > 1;
  const manifestOf = (name) =>
    card.manifests.find((manifest) => manifest.producer === name) ?? card.manifests[0];
  const acting = manifestOf(producer);
  const busy = job.starting || job.running;
  const whyOf = (manifest) => blocked(card, manifest, session, Boolean(settings?.offline), busy);
  const why = whyOf(acting);
  const taskWhy = Object.fromEntries(
    card.manifests.map((manifest) => [manifest.producer, whyOf(manifest)]),
  );
  const reasonId = (reason) => `${cardId}-why-${reason}`;
  const told = REASONS.filter((reason) =>
    [why, ...Object.values(taskWhy)].some((each) => Object.values(each).includes(reason)),
  );
  const start = (kind, tasks = null, by = acting.producer) => {
    setDone(null);
    const body = { kind, ...(tasks ? { tasks } : {}), ...(several ? { producer: by } : {}) };
    job.run(async () => {
      const started = await startProjectJob(card.project, body);
      track(started, { title: downloadName(started, card.name) });
      return started;
    }, `project_${kind}`);
  };
  const values = [["project", card.project]];
  for (const manifest of card.manifests) {
    values.push(["producer", manifest.producer]);
    if (manifest.store) values.push(["store", manifest.store]);
  }
  const invalid = card.manifests.filter((manifest) => manifest.problem);
  return html`<article class="project-card" aria-labelledby="project-card-title">
    <h2 class="pc-title" id="project-card-title">
      <${Tech} value=${values}>${card.name}</${Tech}>
    </h2>
    <${StaleNote} stores=${card.stale_stores} />
    <dl class="kv">
      <dt>${L.card.producer}</dt><dd>${producers(card.manifests)}</dd>
      <dt>${L.card.store}</dt>
      <dd>${storeLines(health, card.manifests)}</dd>
      <dt>${L.card.scanned_at}</dt><dd>${byManifest(card.manifests, scannedAt)}</dd>
      <dt>${L.card.stored_status}</dt>
      <dd>${byManifest(card.manifests, statusBadge)}</dd>
      ${invalid.length ? null : html`<${LiveStatus} id=${card.project} round=${round} />`}
      ${card.missing_pins
        ? html`<dt>${L.card.missing_pins}</dt><dd class="bad-text tabular">${int(card.missing_pins)}</dd>`
        : null}
    </dl>
    ${invalid.length && !card.problems.some((issue) => issue.code === "invalid_manifest")
      ? invalid.map(
          (manifest) => html`<div key=${manifest.producer} class="problem compact" role="alert">
            <div class="problem-head"><${Icon} name="alert" /><b>${L.card.manifest_error}</b></div>
            <p class="problem-producer"><code>${manifest.problem}</code></p>
          </div>`,
        )
      : null}
    <div class="pc-actions" role="group" aria-label=${L.actions.label}>
      ${several
        ? html`<label class="pc-producer">${L.actions.producer}${" "}
            <select value=${acting.producer}
              onChange=${(event) => setProducer(event.currentTarget.value)}>
              ${card.manifests.map(
                (manifest) => html`<option key=${manifest.producer} value=${manifest.producer}>
                  ${manifest.producer}</option>`,
              )}
            </select></label>`
        : null}
      <${ActionButton} icon="check" label=${L.actions.verify} title=${L.actions.verify_title}
        reason=${why.verify} reasonId=${reasonId} onClick=${() => start("verify")} />
      <${ActionButton} icon="search" label=${L.actions.check} title=${L.actions.check_title}
        reason=${why.check} reasonId=${reasonId} onClick=${() => start("check")} />
      <${ActionButton} icon="database" label=${L.actions.download} title=${L.actions.download_title}
        reason=${why.download} reasonId=${reasonId} onClick=${() => start("download")} />
      <${ActionButton} icon="plus" label=${L.actions.add} title=${L.actions.add_title}
        reason=${adding ? "" : why.change} reasonId=${reasonId}
        onClick=${() => {
          setDone(null);
          setAdding(true);
        }} />
      <${ActionButton} icon="users" label=${L.actions.share} title=${L.actions.share_title}
        reason=${why.share} reasonId=${reasonId} onClick=${() => setSharing(true)} />
    </div>
    ${told.length
      ? html`<ul class="pc-why">${told.map(
          (reason) => html`<li key=${reason} id=${reasonId(reason)}>${L.why[reason]}</li>`,
        )}</ul>`
      : null}
    <${JobStatus} job=${job} summary=${projectSummary} />
    ${done
      ? html`<p class="pc-done" role="status"><${Icon} name="check" size=${15} /><span>${done}</span></p>`
      : null}
    ${card.problems.length
      ? html`<section class="det-sec">
          <h3 class="section-title">${count(card.problems.length, T.common.units.problems)}</h3>
          <${IssueList} issues=${card.problems} store=${commonStore(card.manifests)}
            currentProject=${card.project} />
        </section>`
      : null}
    <${Tasks} card=${card} why=${taskWhy} reasonId=${reasonId}
      adding=${adding ? html`<${AddTask} card=${card} producer=${acting.producer}
        onClose=${() => setAdding(false)}
        onAdded=${(name) => {
          setAdding(false);
          setDone(t(L.task.added, { name }));
          changed();
        }} />` : null}
      onRepin=${(task) => start("repin", [task.task], task.producer)}
      onRemoved=${(name) => {
        setDone(t(L.task.removed, { name }));
        changed();
      }} />
    <${OwnData} key=${card.project} project=${card.project} round=${folderRound} />
    ${sharing
      ? html`<${SharingDialog} project=${card.project} name=${card.name}
          onChanged=${(what) => {
            if (what === "folder") {
              setFolderRound((n) => n + 1);
            } else {
              resource.reload();
              onChanged();
            }
          }}
          onClose=${() => setSharing(false)} />`
      : null}
  </article>`;
}

/**
 * A button of a project's action: disabled with its reason (`reason`, a key
 * of `REASONS`, told in the card's list of reasons; `""`: disabled while its
 * form is open) or `null` when it may be used.
 */
function ActionButton({ icon, label, title, reason, reasonId, onClick }) {
  const told = reason ? L.why[reason] : null;
  return html`<button type="button" class="btn sm" disabled=${reason !== null}
    title=${told ?? title} aria-describedby=${told ? reasonId(reason) : null} onClick=${onClick}>
    <${Icon} name=${icon} size=${14} />${label}</button>`;
}

function LiveStatus({ id, round }) {
  const { data, error, loading, reload } = useResource(
    (signal) => getProjectStatus(id, { signal }),
    [id, round],
  );
  const recheck = html`<button type="button" class="btn ghost sm icon-btn" onClick=${reload}
    disabled=${loading} title=${L.card.recheck_hint} aria-label=${L.card.recheck}>
    <${Icon} name="rotate" size=${14} /></button>`;
  let value;
  if (data) {
    value = byManifest(
      data.manifests,
      (manifest) => html`${statusBadge(manifest)}
        <span class="faint">${manifest.stale
          ? t(L.card.stale_status, { at: stamp(manifest.checked_at) })
          : t(L.card.checked_at, { at: stamp(manifest.checked_at) })}</span>`,
    );
  } else if (error) {
    value = html`<${ProblemView} problem=${error.problem} compact />`;
  } else {
    value = html`<${Spinner} quiet />`;
  }
  return html`<dt>${L.card.live_status}</dt>
    <dd class="pc-live">${value}${recheck}
      ${data ? html`<${TaskStatuses} manifests=${data.manifests} />` : null}
    </dd>`;
}

/** Each manifest's tasks as its producer checked them, led by it when several. */
function TaskStatuses({ manifests }) {
  const several = manifests.length > 1;
  const tasks = manifests.flatMap((manifest) =>
    manifest.tasks.map((task) => ({ ...task, producer: manifest.producer })),
  );
  if (!tasks.length) return null;
  return html`<ul class="pc-task-statuses">
    ${tasks.map(
      (task) => html`<li key=${`${task.producer}/${task.task}`}>
        <span class="mono">${task.task}</span>
        ${several ? html`<span class="faint mono">${task.producer}</span>` : null}
        <${Badge} level=${statusLevel(task.status)}>${statusName(task.status)}</${Badge}>
      </li>`,
    )}
  </ul>`;
}

/**
 * The tasks of each manifest with their commands, pins and actions, and the
 * pins of no task; `why` holds the reasons of each manifest by producer.
 */
function Tasks({ card, why, reasonId, adding, onRepin, onRemoved }) {
  const several = card.manifests.length > 1;
  const named = new Set(card.tasks.map((task) => `${task.producer}/${task.task}`));
  const loose = card.pins.filter((pin) => !named.has(`${pin.producer}/${pin.task}`));
  return html`<section class="det-sec">
    <h3 class="section-title">${L.card.tasks}</h3>
    ${adding}
    ${card.tasks.length
      ? html`<ul class="pc-tasks">
          ${card.tasks.map(
            (task) => html`<li key=${`${task.producer}/${task.task}`} class="pc-task">
              <div class="pc-task-head">
                <b class="mono">${task.task}</b>
                ${several ? html`<span class="faint mono">${task.producer}</span>` : null}
                <${Badge} level=${statusLevel(task.status)}>${statusName(task.status)}</${Badge}>
              </div>
              <${Command} task=${task} producer=${task.producer} />
              <${PinList} store=${storeOf(card, task.producer)}
                pins=${card.pins.filter(
                  (pin) => pin.producer === task.producer && pin.task === task.task,
                )} />
              <${TaskActions} project=${card.project} task=${task}
                producer=${several ? task.producer : null} why=${why[task.producer]}
                reasonId=${reasonId} onRepin=${() => onRepin(task)}
                onRemoved=${() => onRemoved(task.task)} />
            </li>`,
          )}
        </ul>`
      : html`<p class="faint">${L.card.no_tasks}</p>`}
    ${loose.length
      ? html`<h4 class="section-title">${L.card.other_pins}</h4>
          ${card.manifests.map((manifest) => {
            const pins = loose.filter((pin) => pin.producer === manifest.producer);
            return pins.length
              ? html`<${PinList} key=${manifest.producer} store=${manifest.store} pins=${pins} />`
              : null;
          })}`
      : null}
  </section>`;
}

/** The store a project's manifest of `producer` names, or `null`. */
function storeOf(card, producer) {
  return card.manifests.find((manifest) => manifest.producer === producer)?.store ?? null;
}

/**
 * „Przepnij” and „Usuń” of a task; a removal asks to be confirmed first.
 * `producer` names the task's manifest for a project of several, else `null`.
 */
function TaskActions({ project, task, producer, why, reasonId, onRepin, onRemoved }) {
  const id = useId();
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [problem, setProblem] = useState(null);
  const remove = async () => {
    setRemoving(true);
    setProblem(null);
    try {
      await removeProjectTask(project, task.task, producer);
      setConfirming(false);
      onRemoved();
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
    } finally {
      setRemoving(false);
    }
  };
  return html`<div class="pc-task-actions">
    <div class="pc-task-buttons" role="group" aria-label=${t(L.task.actions, { name: task.task })}>
      <${ActionButton} icon="rotate" label=${L.actions.repin} title=${L.actions.repin_title}
        reason=${why.repin} reasonId=${reasonId} onClick=${onRepin} />
      <${ActionButton} icon="trash" label=${L.actions.remove} title=${L.actions.remove_title}
        reason=${confirming ? "" : why.change} reasonId=${reasonId}
        onClick=${() => {
          setProblem(null);
          setConfirming(true);
        }} />
    </div>
    ${confirming
      ? html`<div class="pc-confirm" role="group" aria-labelledby=${`${id}-confirm`}>
          <p id=${`${id}-confirm`}>${t(L.task.confirm, { name: task.task })}</p>
          <div class="pc-form-actions">
            <button type="button" class="btn sm danger" disabled=${removing} onClick=${remove}>
              ${removing ? html`<span class="spinner" aria-hidden="true"></span>` : html`<${Icon} name="trash" size=${14} />`}
              ${L.task.confirm_remove}</button>
            <button type="button" class="btn sm ghost" disabled=${removing}
              onClick=${() => setConfirming(false)}>${L.task.confirm_cancel}</button>
          </div>
        </div>`
      : null}
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
  </div>`;
}

/**
 * „+ Zadanie”: a pasted command of `producer` and the task's name. The
 * producer reads the line (`POST /commands/parse`) and adds the task to its
 * manifest after checking it without the network (`POST
 * /projects/{project}/tasks`, naming the producer for a project of several);
 * its text for a mistake shows at the line, or at the name for a refused name.
 */
function AddTask({ card, producer, onAdded, onClose }) {
  const id = useId();
  const [line, setLine] = useState("");
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [refusal, setRefusal] = useState(null);
  const ready = line.trim() !== "" && name.trim() !== "" && !saving;
  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    const task = name.trim();
    let stage = "parse";
    setSaving(true);
    setRefusal(null);
    try {
      const call = await parseCommand(producer, line.trim());
      stage = "add";
      const named = card.manifests.length > 1 ? { producer } : {};
      await addProjectTask(card.project, {
        name: task,
        command: call.command,
        options: call.options,
        ...named,
      });
      onAdded(task);
    } catch (error) {
      if (!error.problem) throw error;
      const option = error.problem.details?.option ?? null;
      const field = stage === "parse" ? "line" : option === "name" ? "name" : option !== null ? "line" : null;
      setRefusal({ problem: error.problem, field });
    } finally {
      setSaving(false);
    }
  };
  const at = (field) => (refusal?.field === field ? refusal.problem : null);
  return html`<form class="pc-form pc-add" aria-labelledby=${`${id}-title`} onSubmit=${submit}>
    <h4 class="section-title" id=${`${id}-title`}>${L.task.title}</h4>
    <div class=${`field${at("line") ? " invalid" : ""}`}>
      <label for=${`${id}-line`}>${L.task.line}</label>
      <textarea id=${`${id}-line`} class="mono pc-add-line" rows="2" value=${line} spellcheck="false"
        autocomplete="off" placeholder=${L.task.line_placeholder}
        aria-invalid=${at("line") ? "true" : null} aria-describedby=${`${id}-line-note`}
        onInput=${(event) => {
          setLine(event.currentTarget.value);
          setRefusal(null);
        }}></textarea>
      ${at("line")
        ? html`<${FieldError} id=${`${id}-line-note`} problem=${at("line")} />`
        : html`<span class="field-hint" id=${`${id}-line-note`}>${t(L.task.line_hint, { producer })}</span>`}
    </div>
    <div class=${`field${at("name") ? " invalid" : ""}`}>
      <label for=${`${id}-name`}>${L.task.name}</label>
      <input id=${`${id}-name`} type="text" class="mono" value=${name} spellcheck="false" autocomplete="off"
        placeholder=${L.task.name_example} aria-invalid=${at("name") ? "true" : null}
        aria-describedby=${`${id}-name-note`}
        onInput=${(event) => {
          setName(event.currentTarget.value);
          setRefusal(null);
        }} />
      ${at("name")
        ? html`<${FieldError} id=${`${id}-name-note`} problem=${at("name")} />`
        : html`<span class="field-hint" id=${`${id}-name-note`}>${L.task.name_hint}</span>`}
    </div>
    ${refusal && refusal.field === null ? html`<${ProblemView} problem=${refusal.problem} compact />` : null}
    <div class="pc-form-actions">
      <button type="submit" class="btn sm primary" disabled=${!ready}>
        ${saving ? html`<span class="spinner" aria-hidden="true"></span>` : html`<${Icon} name="plus" size=${14} />`}
        ${L.task.submit}</button>
      <button type="button" class="btn sm ghost" disabled=${saving} onClick=${onClose}>${L.task.cancel}</button>
    </div>
  </form>`;
}

/** The producer's text for a field, its code and option a click away. */
function FieldError({ id, problem }) {
  const values = problem.code ? [["code", problem.code]] : [];
  if (problem.details?.option) values.push(["option", problem.details.option]);
  return html`<span class="field-error" id=${id} role="alert">
    ${values.length ? html`<${Tech} value=${values}>${problem.detail}</${Tech}>` : problem.detail}</span>`;
}

function Command({ task, producer }) {
  const options = Object.entries(task.options);
  const text = JSON.stringify({ command: task.command, options: task.options });
  return html`<div class="cmd pc-cmd">
    <code>
      <span class="pc-cmd-name">${producer} ${task.command}</span>
      ${options.map(
        ([name, value]) => html`<span key=${name} class="pc-opt">
          <span class="pc-opt-name">${name}</span>=${typeof value === "string" ? value : JSON.stringify(value)}
        </span>`,
      )}
    </code>
    <${CopyButton} text=${text} label=${L.card.copy_command} />
  </div>`;
}

function PinList({ store, pins }) {
  if (!pins.length) return html`<p class="faint pc-no-pins">${L.card.no_pins}</p>`;
  return html`<ul class="pc-pins" aria-label=${L.card.pins}>
    ${pins.map(
      (pin) => html`<li key=${pin.version} class="pc-pin">
        ${pin.slot && store
          ? html`<${FileLink} store=${store} slot=${pin.slot} version=${pin.version}
              title=${L.card.pin_open}>
              <${Icon} name="file" size=${13} /><span class="mono">${pin.label ?? pin.version}</span>
            </${FileLink}>`
          : html`<code class="path">${pin.version}</code>`}
        ${pin.state === "ok"
          ? html`<${Badge} level=${pin.is_current ? "info" : "plain"}>
              ${pin.is_current ? L.card.pin_current : L.card.pin_older}</${Badge}>`
          : null}
        <${Badge} level=${pin.state === "ok" ? "ok" : "bad"}>
          <${Tech} value=${[["state", pin.state], ["version", pin.version], ["sha256", pin.sha256 ?? "–"]]}>
            ${pinStateName(pin.state)}
          </${Tech}>
        </${Badge}>
        ${pin.size_bytes !== null ? html`<span class="faint tabular">${size(pin.size_bytes)}</span>` : null}
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

function OwnFolder({ folder }) {
  return html`<dl class="kv own-folder">
    <dt>${L.own.folder}</dt>
    <dd class="own-folder-path">
      <code class="path">${folder.path.local}</code>
      <${CopyButton} text=${folder.path.local} label=${L.own.copy_folder} />
      <span class="faint">${L.own.source[folder.source] ?? folder.source}</span>
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
