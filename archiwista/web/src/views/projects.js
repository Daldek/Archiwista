/**
 * The Projects view (docs/SPEC.md UC-06, 6.5 g; plan v0.1 step 11): the
 * projects found in the project directories that the session sees — as the
 * API filters them (step 8b), nothing filtered here — with their producer's
 * status when the manifest was read and their missing pins; the chosen
 * project (`?view=projects&project=<id>`) in the side panel with its tasks
 * and their existing commands, the producer's status now, the pinned
 * versions (older ones too) leading to their file cards, and its problems.
 * Nothing here starts or changes a project.
 */

import { getProject, getProjectStatus, listProjects } from "../api.js";
import { useApp } from "../context.js";
import { count, int, size, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { projects as L } from "../labels/projects.js";
import { T, t } from "../labels/index.js";
import { ViewLayout } from "../panels.js";
import { Link, setParams } from "../router.js";
import { CopyButton, html, Icon, ProblemView, Seg, Spinner, Tech } from "../ui.js";
import {
  Badge,
  FileLink,
  IssueList,
  loadCardStyles,
  pinStateName,
  StaleNote,
  statusLevel,
  statusName,
  storeName,
} from "./cards.js";

await loadCardStyles();

const ALL = "";

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
    content: chosen ? html`<${ProjectCard} key=${chosen} id=${chosen} />` : null,
  };
  return html`<${ViewLayout} id="projects" right=${panel}>
    <${ProjectList} list=${list} chosen=${chosen} store=${store} route=${route} />
  </${ViewLayout}>`;
}

function ProjectList({ list, chosen, store, route }) {
  const { health } = useApp();
  const stores = health?.stores ?? [];
  const items = list.data?.items ?? [];
  const pick = (project) => setParams({ project });
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
    </div>
    <div class="cards-scroll">
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
                      ${item.problem
                        ? html`<p class="row-problem"><${Icon} name="alert" size=${13} />
                            <span><b>${L.invalid}:</b>${" "}${item.problem}</span></p>`
                        : null}
                    </td>
                    <td>${item.store ? storeName(health, item.store) : html`<span class="warn-text">${L.no_store}</span>`}</td>
                    <td><${Badge} level=${statusLevel(item.status)}>${statusName(item.status)}</${Badge}></td>
                    <td class="num tabular">${int(item.tasks)}</td>
                    <td class="num tabular">${int(item.pins)}</td>
                    <td class=${item.missing_pins ? "num tabular bad-text" : "num tabular"}>${int(item.missing_pins)}</td>
                    <td class="nw">${stamp(item.scanned_at)}</td>
                  </tr>`,
                )}
              </tbody>
            </table>
          </div>`
        : null}
    </div>`;
}

function ProjectCard({ id }) {
  const { health } = useApp();
  const { data: card, error } = useResource((signal) => getProject(id, { signal }), [id]);
  if (!card) {
    if (!error) return html`<${Spinner} />`;
    return error.status === 404
      ? html`<p class="hint warn">${t(L.not_found, { project: id })}</p>`
      : html`<${ProblemView} problem=${error.problem} />`;
  }
  const values = [
    ["project", card.project],
    ["producer", card.producer],
  ];
  if (card.store) values.push(["store", card.store]);
  return html`<article class="project-card" aria-labelledby="project-card-title">
    <h2 class="pc-title" id="project-card-title">
      <${Tech} value=${values}>${card.name}</${Tech}>
    </h2>
    <${StaleNote} stores=${card.stale_stores} />
    <dl class="kv">
      <dt>${L.card.producer}</dt><dd>${card.producer}</dd>
      <dt>${L.card.store}</dt>
      <dd>${card.store ? storeName(health, card.store) : html`<span class="warn-text">${L.no_store}</span>`}</dd>
      <dt>${L.card.scanned_at}</dt><dd>${stamp(card.scanned_at)}</dd>
      <dt>${L.card.stored_status}</dt>
      <dd><${Badge} level=${statusLevel(card.status)}>${statusName(card.status)}</${Badge}></dd>
      ${card.problem ? null : html`<${LiveStatus} id=${card.project} />`}
      ${card.missing_pins
        ? html`<dt>${L.card.missing_pins}</dt><dd class="bad-text tabular">${int(card.missing_pins)}</dd>`
        : null}
    </dl>
    ${card.problem && !card.problems.some((issue) => issue.code === "invalid_manifest")
      ? html`<div class="problem compact" role="alert">
          <div class="problem-head"><${Icon} name="alert" /><b>${L.card.manifest_error}</b></div>
          <p class="problem-producer"><code>${card.problem}</code></p>
        </div>`
      : null}
    ${card.problems.length
      ? html`<section class="det-sec">
          <h3 class="section-title">${count(card.problems.length, T.common.units.problems)}</h3>
          <${IssueList} issues=${card.problems} store=${card.store} currentProject=${card.project} />
        </section>`
      : null}
    <${Tasks} card=${card} />
    <p class="hint">${L.card.readonly}</p>
  </article>`;
}

function LiveStatus({ id }) {
  const { data, error, loading, reload } = useResource(
    (signal) => getProjectStatus(id, { signal }),
    [id],
  );
  const recheck = html`<button type="button" class="btn ghost sm icon-btn" onClick=${reload}
    disabled=${loading} title=${L.card.recheck_hint} aria-label=${L.card.recheck}>
    <${Icon} name="rotate" size=${14} /></button>`;
  let value;
  if (data) {
    value = html`<${Badge} level=${statusLevel(data.status)}>${statusName(data.status)}</${Badge}>
      <span class="faint">${data.stale
        ? t(L.card.stale_status, { at: stamp(data.checked_at) })
        : t(L.card.checked_at, { at: stamp(data.checked_at) })}</span>`;
  } else if (error) {
    value = html`<${ProblemView} problem=${error.problem} compact />`;
  } else {
    value = html`<${Spinner} quiet />`;
  }
  return html`<dt>${L.card.live_status}</dt>
    <dd class="pc-live">${value}${recheck}
      ${data ? html`<${TaskStatuses} tasks=${data.tasks} />` : null}
    </dd>`;
}

function TaskStatuses({ tasks }) {
  if (!tasks.length) return null;
  return html`<ul class="pc-task-statuses">
    ${tasks.map(
      (task) => html`<li key=${task.task}>
        <span class="mono">${task.task}</span>
        <${Badge} level=${statusLevel(task.status)}>${statusName(task.status)}</${Badge}>
      </li>`,
    )}
  </ul>`;
}

function Tasks({ card }) {
  const named = new Set(card.tasks.map((task) => task.task));
  const loose = card.pins.filter((pin) => !named.has(pin.task));
  return html`<section class="det-sec">
    <h3 class="section-title">${L.card.tasks}</h3>
    ${card.tasks.length
      ? html`<ul class="pc-tasks">
          ${card.tasks.map(
            (task) => html`<li key=${task.task} class="pc-task">
              <div class="pc-task-head">
                <b class="mono">${task.task}</b>
                <${Badge} level=${statusLevel(task.status)}>${statusName(task.status)}</${Badge}>
              </div>
              <${Command} task=${task} producer=${card.producer} />
              <${PinList} store=${card.store}
                pins=${card.pins.filter((pin) => pin.task === task.task)} />
            </li>`,
          )}
        </ul>`
      : html`<p class="faint">${L.card.no_tasks}</p>`}
    ${loose.length
      ? html`<h4 class="section-title">${L.card.other_pins}</h4>
          <${PinList} store=${card.store} pins=${loose} />`
      : null}
  </section>`;
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
