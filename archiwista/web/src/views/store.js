/**
 * The Store view (docs/SPEC.md UC-07 and UC-13; plan v0.1 step 11): one
 * configured store (`?view=store&store=<id>`, the first one by default) —
 * its availability, source plugin and index, the last scan with who started
 * it, „Odśwież” (an incremental scan, `POST /stores/{store}/scan`) and
 * „Uzupełnij obrysy jednostek” (`…/footprints`, which needs the network and
 * is off in offline mode) followed live through the job's events; a `409`
 * follows the job already running. Below: disk usage per product with each
 * version counted once, the versions neither current, nor in `full_sheet/`,
 * nor pinned (a report for a decision — Archiwista deletes nothing), the
 * store's problems with their fixes and the visible projects naming it. The
 * disconnected-share banner is the shell's index banner (banner.js).
 */

import { getStore, listProducts, startFootprints, startScan } from "../api.js";
import { useApp } from "../context.js";
import { day, int, plural, size, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { store as L } from "../labels/store.js";
import { T, t } from "../labels/index.js";
import { Link, setParams } from "../router.js";
import { html, Icon, ProblemView, Seg, Spinner, Tech, useEffect } from "../ui.js";
import {
  actorName,
  Badge,
  IssueList,
  JobStatus,
  loadCardStyles,
  seconds,
  statusLevel,
  statusName,
  useJob,
} from "./cards.js";

await loadCardStyles();

const STATUS_LEVEL = { available: "ok", unavailable: "bad", unknown: "warn" };

/**
 * The Store view (route `store`).
 *
 * @param {{route: import("../router.js").Route}} props - Parameter `store`:
 *   the store's id; the first configured store without it.
 */
export default function StoreView({ route }) {
  const { health, healthError } = useApp();
  if (!health) {
    return html`<div class="page">
      ${healthError ? html`<${ProblemView} problem=${healthError.problem} />` : html`<${Spinner} />`}
    </div>`;
  }
  const stores = health.stores;
  if (!stores.length) {
    return html`<div class="page view-message">
      <p>${L.no_store}</p>
      <${Link} class="btn primary" view="setup">${L.settings}</${Link}>
    </div>`;
  }
  const id = route.params.store || stores[0].store;
  const item = stores.find((candidate) => candidate.store === id);
  return html`<div class="cards-page store-page">
    ${stores.length > 1
      ? html`<${Seg} label=${L.stores_label} value=${id}
          onChange=${(value) => setParams({ store: value })}
          options=${stores.map((candidate) => ({ value: candidate.store, label: candidate.name }))} />`
      : null}
    ${item
      ? html`<${StoreDetail} key=${item.store} item=${item} />`
      : html`<p class="hint warn">${t(L.unknown, { store: id })}</p>`}
  </div>`;
}

function StoreDetail({ item }) {
  const { health, settings, refreshHealth } = useApp();
  const detail = useResource((signal) => getStore(item.store, { signal }), [item.store]);
  const products = useResource(
    (signal) => listProducts({ store: item.store }, { signal }),
    [item.store],
  );
  const job = useJob({
    onEnd: () => {
      detail.reload();
      products.reload();
      refreshHealth();
    },
  });
  const running = item.state.running_job;
  useEffect(() => {
    if (running && running.id !== job.id && !job.running) job.follow(running.id, running.kind);
  }, [running?.id]);

  const busy = job.starting || job.running;
  const offline = settings?.offline === true;
  const start = (kind) => {
    const call = kind === "scan" ? () => startScan(item.store, { mode: "incremental" }) : () => startFootprints(item.store);
    job.run(call, kind).then(refreshHealth);
  };
  const values = [
    ["store", item.store],
    ["kind", item.kind],
    ["producers", item.producers.join(", ")],
  ];

  return html`<header class="store-head">
      <div class="store-name">
        <p class="eyebrow">${L.title}</p>
        <h1><${Tech} value=${values}>${item.name}</${Tech}></h1>
        <${Badge} level=${STATUS_LEVEL[item.state.status] ?? "warn"}>
          ${L.status_line[item.state.status] ?? item.state.status}
        </${Badge}>
        <span class="chip static">${T.common.store_kind[item.kind] ?? item.kind}</span>
      </div>
      <div class="store-actions">
        <button type="button" class="btn primary" disabled=${busy} title=${L.actions.refresh_hint}
          onClick=${() => start("scan")}>
          ${busy && job.kind === "scan" ? html`<span class="spinner" aria-hidden="true"></span>` : html`<${Icon} name="rotate" />`}
          ${L.actions.refresh}
        </button>
        <button type="button" class="btn" disabled=${busy || offline}
          title=${offline ? L.actions.footprints_offline : L.actions.footprints_hint}
          aria-describedby=${offline ? "store-footprints-offline" : null}
          onClick=${() => start("footprints")}>
          <${Icon} name="map" />${L.actions.footprints}
        </button>
      </div>
    </header>
    ${offline
      ? html`<p class="hint" id="store-footprints-offline">${L.actions.footprints_offline}</p>`
      : null}
    <${JobStatus} job=${job} />
    ${detail.error ? html`<${ProblemView} problem=${detail.error.problem} />` : null}
    <div class="store-grid">
      <div class="store-column">
        <${StateSection} item=${item} health=${health} />
        ${detail.data
          ? html`<${UsageSection} detail=${detail.data} products=${products.data} />`
          : detail.error ? null : html`<${Spinner} />`}
      </div>
      <div class="store-column">
        ${detail.data
          ? html`
              <section class="card store-section" aria-labelledby="store-problems">
                <h2 class="section-title" id="store-problems">
                  ${L.problems.title} (${int(detail.data.problems.length)})
                </h2>
                <${IssueList} issues=${detail.data.problems} store=${item.store} />
              </section>
              <${ProjectsSection} projects=${detail.data.projects} />
            `
          : null}
      </div>
    </div>`;
}

function StateSection({ item, health }) {
  const state = item.state;
  const scan = state.last_scan;
  const sources = health.sources.filter((source) => item.producers.includes(source.producer));
  return html`<section class="card store-section" aria-labelledby="store-state">
    <h2 class="section-title" id="store-state">${L.state.title}</h2>
    <dl class="kv store-kv">
      ${state.status === "unavailable"
        ? html`<dt>${L.status_line.unavailable}</dt>
            <dd class="bad-text">${t(L.unavailable_since, { at: stamp(state.status_at) })}${state.detail ? ` — ${state.detail}` : ""}</dd>`
        : null}
      <dt>${L.state.indexed_at}</dt>
      <dd>${state.indexed_at ? stamp(state.indexed_at) : L.state.never}</dd>
      <dt>${L.state.counts}</dt>
      <dd>
        ${t(L.state.counts_value, {
          slots: int(state.slots),
          slots_word: plural(state.slots, L.slots),
          versions: int(state.versions),
          versions_word: plural(state.versions, T.common.units.versions),
        })}
        <span class="faint"> · ${[
          t(L.state.missing_versions, { count: int(state.missing_versions) }),
          t(L.state.unlocated_versions, { count: int(state.unlocated_versions) }),
          t(L.state.issues, { count: int(state.issues) }),
        ].join(" · ")}</span>
      </dd>
      <dt>${L.state.last_scan}</dt>
      <dd class="store-scan">${scan ? html`<${ScanRow} scan=${scan} />` : L.state.last_scan_none}</dd>
      ${sources.map(
        (source) => html`<dt key=${`dt-${source.producer}`}>${L.state.source}</dt>
          <dd key=${`dd-${source.producer}`}>
            <${Tech} value=${[
              ["producer", source.producer],
              ["status", source.status],
              ["supported_versions", source.supported_versions ?? "–"],
              ["schemas", source.schemas.join(", ") || "–"],
            ]}>
              ${t(L.state.source_value, { producer: source.producer, version: source.package_version ?? "" })}
            </${Tech}>
            <${Badge} level=${source.status === "available" ? "ok" : "bad"}>
              ${T.common.source_status[source.status] ?? source.status}
            </${Badge}>
            ${source.status === "available" ? null : html`<p class="hint warn">${source.message} ${source.fix ?? ""}</p>`}
          </dd>`,
      )}
      <dt>${L.state.index}</dt>
      <dd>${t(L.state.index_value, {
        schema: health.index.schema_version,
        size: size(health.index.size_bytes),
        created: day(health.index.created_at),
      })}</dd>
    </dl>
  </section>`;
}

function ScanRow({ scan }) {
  const at = scan.finished_at ?? scan.started_at ?? scan.created_at;
  const took =
    scan.finished_at && scan.started_at
      ? (Date.parse(scan.finished_at) - Date.parse(scan.started_at)) / 1000
      : null;
  return html`
    <span>${t(L.state.last_scan_value, {
      at: stamp(at),
      state: T.common.job_state[scan.state] ?? scan.state,
    })}${took === null ? "" : ` · ${t(L.state.duration, { seconds: seconds(took) })}`}</span>
    <span class="store-actor">
      <span class="faint">${L.state.actor}:</span>${" "}
      <${Tech} value=${[["actor", scan.actor], ["job", scan.id]]}>${actorName(scan.actor)}</${Tech}>
    </span>`;
}

function UsageSection({ detail, products }) {
  const usage = detail.usage;
  const unused = detail.unused;
  const unusedOf = new Map(unused.products.map((row) => [row.product, row]));
  const segmentsOf = new Map(
    (products?.items ?? []).map((product) => [product.product, product.segments.map((item) => item.segment)]),
  );
  const catalog = (product) => ({ store: detail.store, product, versions: "noncurrent_unpinned" });
  return html`<section class="card store-section" aria-labelledby="store-usage">
    <h2 class="section-title" id="store-usage">${L.usage.title}</h2>
    <p class="hint">${L.usage.hint}</p>
    ${usage.products.length
      ? html`<div class="table-wrap">
          <table class="usage-table">
            <thead>
              <tr>
                <th scope="col">${L.usage.product}</th>
                <th scope="col" class="num">${L.usage.versions}</th>
                <th scope="col" class="num">${L.usage.bytes}</th>
                <th scope="col" class="num">${L.usage.unused_versions}</th>
                <th scope="col" class="num">${L.usage.unused_bytes}</th>
              </tr>
            </thead>
            <tbody>
              ${usage.products.map((row) => {
                const spare = unusedOf.get(row.product);
                const segments = segmentsOf.get(row.product) ?? [];
                return html`<tr key=${row.product ?? "unknown"}>
                  <th scope="row"><${ProductName} product=${row.product} segments=${segments} /></th>
                  <td class="num tabular">${int(row.versions)}</td>
                  <td class="num tabular"><${Bytes} bytes=${row.unique_bytes} /></td>
                  <td class="num tabular">
                    ${spare
                      ? row.product === null
                        ? int(spare.versions)
                        : html`<${Link} view="catalog" params=${catalog(row.product)}
                            title=${t(L.usage.list_title, { product: row.product })}>
                            ${int(spare.versions)}</${Link}>`
                      : int(0)}
                  </td>
                  <td class="num tabular">${spare ? html`<${Bytes} bytes=${spare.unique_bytes} />` : size(0)}</td>
                </tr>`;
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">${L.usage.total}</th>
                <td class="num tabular">${int(usage.versions)}</td>
                <td class="num tabular"><${Bytes} bytes=${usage.unique_bytes} /></td>
                <td class="num tabular">${int(unused.versions)}</td>
                <td class="num tabular"><${Bytes} bytes=${unused.unique_bytes} /></td>
              </tr>
            </tfoot>
          </table>
        </div>`
      : html`<p class="faint">${L.usage.empty}</p>`}
    <div class="store-unused">
      <h3 class="section-title">${L.unused.title}</h3>
      ${unused.versions
        ? html`<p>${t(L.unused.summary, {
            versions: int(unused.versions),
            versions_word: plural(unused.versions, T.common.units.versions),
            bytes: size(unused.unique_bytes),
            reclaimable: size(unused.reclaimable_bytes),
          })}</p>
          <p class="hint">${L.unused.note}</p>
          <${Link} class="btn sm" view="catalog"
            params=${{ store: detail.store, versions: "noncurrent_unpinned" }}>
            <${Icon} name="table" size=${14} />${L.unused.catalog}</${Link}>`
        : html`<p class="faint">${L.unused.none}</p>`}
    </div>
  </section>`;
}

function ProductName({ product, segments }) {
  const paths = segments.map((segment) => ["segment", segment.path ?? "–"]);
  if (product === null) {
    return html`<${Tech} value=${[["product", "null"], ...paths]}>
      <span class="usage-product unknown">${L.usage.unknown_product}</span>
    </${Tech}>`;
  }
  return html`<${Tech} value=${[["product", product], ...paths]}>
      <span class="usage-product mono">${product}</span>
    </${Tech}>
    ${segments.length
      ? html`<ul class="usage-segments">
          ${segments.map((segment) => html`<li key=${segment.path}>${segment.label}</li>`)}
        </ul>`
      : null}`;
}

function Bytes({ bytes }) {
  return html`<${Tech} value=${[["bytes", String(bytes)]]}>${size(bytes)}</${Tech}>`;
}

function ProjectsSection({ projects }) {
  return html`<section class="card store-section" aria-labelledby="store-projects">
    <h2 class="section-title" id="store-projects">${L.projects.title} (${int(projects.length)})</h2>
    ${projects.length
      ? html`<ul class="store-projects">
          ${projects.map(
            (project) => html`<li key=${project.project}>
              <${Link} view="projects" params=${{ project: project.project }}>${project.name}</${Link}>
              <${Badge} level=${statusLevel(project.status)}>${statusName(project.status)}</${Badge}>
              ${project.missing_pins
                ? html`<span class="bad-text">${t(L.projects.missing, { count: int(project.missing_pins) })}</span>`
                : null}
              ${project.problem ? html`<span class="bad-text">${L.projects.invalid}</span>` : null}
            </li>`,
          )}
        </ul>`
      : html`<p class="faint">${L.projects.none}</p>`}
  </section>`;
}
