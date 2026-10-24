/**
 * The index state banner under the top bar: what `GET /health` and the
 * settings say about the index — no store yet, a first scan waiting, a scan
 * and its progress (the wizard's new store is scanned by the server's
 * scheduler, step 6b), an unavailable store answered from the index as of
 * its last pass (`stale`, never shown as an empty result), a failed scan, an
 * unavailable producer plugin with its fix. Nothing while all is well.
 */

import { useApp } from "./context.js";
import { int, plural, stamp } from "./format.js";
import { T, t } from "./labels/index.js";
import { Link } from "./router.js";
import { html, Icon } from "./ui.js";

const L = T.shell.banner;
const FAILED = new Set(["failed", "interrupted"]);

/**
 * A line of the banner.
 *
 * @typedef {object} BannerLine
 * @property {string} key
 * @property {"info"|"warn"|"error"} level
 * @property {string} icon
 * @property {string} text
 * @property {string|null} [detail]
 * @property {{current?: number, total?: number}} [progress] - No numbers: a
 *   job whose size is not known yet.
 * @property {*} [action]
 */

/**
 * The banner of the current state; empty when there is nothing to report.
 *
 * @param {{view: string|null}} props - The current view (the wizard needs no
 *   link to itself).
 */
export function IndexBanner({ view }) {
  const { health, healthError, settings } = useApp();
  const lines = bannerLines({ health, healthError, settings, inSetup: view === "setup" });
  if (!lines.length) return null;
  return html`<div class="banners" role="region" aria-label=${L.label}>
    ${lines.map(
      (line) => html`<div key=${line.key} class=${`banner ${line.level}`}
        role=${line.level === "error" ? "alert" : null}>
        <${Icon} name=${line.icon} size=${17} />
        <div class="banner-text">
          <span>${line.text}</span>
          ${line.detail ? html`<span class="banner-detail">${line.detail}</span>` : null}
        </div>
        ${line.progress ? html`<${Progress} label=${line.text} ...${line.progress} />` : null}
        ${line.action ?? null}
      </div>`,
    )}
  </div>`;
}

/**
 * A determinate bar with `total`, otherwise one showing work of unknown size
 * (keyed apart: a removed `value` would leave a determinate empty bar).
 */
function Progress({ label, current, total }) {
  return total
    ? html`<progress key="known" aria-label=${label} max=${total} value=${current}></progress>`
    : html`<progress key="unknown" aria-label=${label}></progress>`;
}

/**
 * Lines of the banner, most important first.
 *
 * @param {{health?: import("./types.js").Health, healthError?: *,
 *   settings?: import("./types.js").Settings, inSetup: boolean}} state
 * @returns {BannerLine[]}
 */
export function bannerLines({ health, healthError, settings, inSetup }) {
  const lines = [];
  if (healthError) {
    lines.push({
      key: "server",
      level: "warn",
      icon: "alert",
      text: L.offline_server,
      detail: healthError.problem?.detail,
    });
  }
  if (settings && settings.stores.length === 0) {
    lines.push({
      key: "no-store",
      level: "info",
      icon: "database",
      text: L.no_store,
      action: inSetup
        ? null
        : html`<${Link} class="btn sm primary" view="setup">${L.run_wizard}</${Link}>`,
    });
  }
  if (!health) return lines;
  const used = new Set(health.stores.flatMap((item) => item.producers));
  for (const source of health.sources) {
    if (source.status === "available" || !used.has(source.producer)) continue;
    lines.push({
      key: `source-${source.producer}`,
      level: "error",
      icon: "alert",
      text: t(L.source, {
        producer: source.producer,
        status: T.common.source_status[source.status] ?? source.status,
      }),
      detail: [source.message, source.fix].filter(Boolean).join(" "),
    });
  }
  for (const item of health.stores) {
    const line = storeLine(item);
    if (line) lines.push(line);
  }
  return lines;
}

/**
 * The banner line of one store, or `null` when it needs none.
 *
 * @param {import("./types.js").StoreItem} item
 * @returns {BannerLine|null}
 */
export function storeLine(item) {
  const { state } = item;
  const store = item.name;
  const key = `store-${item.store}`;
  if (state.status === "unavailable") {
    return {
      key,
      level: "warn",
      icon: "alert",
      text: state.indexed_at
        ? t(L.unavailable, { store, indexed_at: stamp(state.indexed_at) })
        : t(L.unavailable_never, { store }),
      detail: state.detail ? t(L.detail, { detail: state.detail }) : null,
    };
  }
  const job = state.running_job;
  if (job) return jobLine(key, store, job);
  if (state.status === "unknown") {
    return { key, level: "info", icon: "database", text: t(L.waiting, { store }) };
  }
  if (state.last_scan && FAILED.has(state.last_scan.state)) {
    const name = T.common.job_state[state.last_scan.state] ?? state.last_scan.state;
    return { key, level: "warn", icon: "alert", text: t(L.scan_failed, { store, state: name }) };
  }
  return null;
}

function jobLine(key, store, job) {
  const line = { key, level: "info", icon: "rotate" };
  if (job.state === "queued" && job.kind === "scan") return { ...line, text: t(L.queued, { store }) };
  const progress = job.progress && job.progress.total > 0 ? job.progress : null;
  if (job.kind !== "scan") {
    const text = t(L.job, {
      store,
      kind: T.common.job_kind[job.kind] ?? job.kind,
      state: T.common.job_state[job.state] ?? job.state,
    });
    return { ...line, text, progress: progress ?? {} };
  }
  if (!progress) return { ...line, text: t(L.indexing_start, { store }), progress: {} };
  const text = t(L.indexing, {
    store,
    current: int(progress.current),
    total: int(progress.total),
    segments: plural(progress.total, T.common.units.segments),
  });
  return { ...line, text, progress };
}
