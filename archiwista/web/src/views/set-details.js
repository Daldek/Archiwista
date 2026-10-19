/**
 * „Szczegóły zestawu” (docs/SPEC.md 6.1 „Jedna informacja — jedno miejsce”;
 * plan v0.2 step 13b): the right panel holds only the chosen layer — its
 * variant and formats, local coverage, versions and sheets, campaigns and
 * the dates of its data, the state of its previews — while the map, the
 * Wachlarz and the timeline give the overview. A sheet opens its file card;
 * „Pokaż na mapie” where the map is not in view; outside the catalog, the
 * other variants of the same year; „Porównaj z…” a second layer of the area
 * for the comparison (`view=compare`, plan v0.2 step 14). No download before
 * v0.3.
 *
 * The pieces describing a layer — the coverage badge, the formats, its facts
 * in one line — are shared with the Wachlarz and the timeline.
 */

import { useApp } from "../context.js";
import { count, day, int, stamp } from "../format.js";
import { T, t } from "../labels/index.js";
import { map as M } from "../labels/map.js";
import { previews as P } from "../labels/previews.js";
import { setDetails as S } from "../labels/set-details.js";
import { slotName } from "../map/canvas.js";
import { CAMPAIGN_GROUP, readVersionRef, variantName } from "../map/previews.js";
import { Link } from "../router.js";
import { html, Icon, loadStylesheet, Tech, useState } from "../ui.js";
import { FileLink, JobStatus, storeName } from "./cards.js";

await loadStylesheet(new URL("./set-details.css", import.meta.url));

/** Sheets listed before „Pokaż wszystkie”. */
const SHEETS_SHOWN = 60;

/**
 * The local coverage of a layer as a badge: „lokalnie 83% obszaru” with a ring.
 *
 * @param {{coverage: {ratio: number|null, percent: number|null, label: string},
 *   short?: boolean}} props - `short`: the percent alone, the label in its title.
 */
export function CoverageBadge({ coverage, short = false }) {
  const percent = coverage.percent ?? 0;
  const tone = percent === 100 ? "done" : percent > 0 || coverage.ratio ? "some" : "no";
  return html`<span class=${`local ${tone}`} title=${short ? coverage.label : null}>
    <span class="ring" style=${`--p:${percent}%`} aria-hidden="true"></span>${short ? `${percent}%` : coverage.label}
  </span>`;
}

/**
 * The file formats of a layer as badges (A-ADR-017: one variant, several formats).
 *
 * @param {{formats: string[]}} props
 */
export function Formats({ formats }) {
  if (!formats.length) return null;
  return html`<span class="fmts">${formats.map((format) => html`<span key=${format} class="fmt">${format}</span>`)}</span>`;
}

/**
 * The number of a layer's campaigns and the state of its previews in one line,
 * e.g. „2 kampanie · podglądy: 3 z 4 · w budowie”.
 *
 * @param {import("../types.js").Layer} layer
 * @returns {string}
 */
export function layerFacts(layer) {
  return [layer.campaigns.length ? count(layer.campaigns.length, S.campaigns) : null, previewsText(layer)]
    .filter(Boolean)
    .join(" · ");
}

/**
 * A layer in one line for a tooltip: title, coverage, variant, formats, facts.
 *
 * @param {import("../types.js").Layer} layer
 * @returns {string}
 */
export function describeLayer(layer) {
  return [layer.title, layer.coverage?.label, variantName(layer.variant), layer.variant.formats.join(", "), layerFacts(layer)]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Why a set of layers comes from the index without a rescan of the area.
 *
 * @param {import("../types.js").LayerSet} set - With `stale`.
 * @returns {string}
 */
export function staleText(set) {
  const text = M.local.stale[set.stale_reason];
  if (!text) return M.counts.stale;
  return t(text, { indexed_at: set.stale_stores.map((item) => stamp(item.indexed_at)).join(", ") });
}

/**
 * The button of a centre bar showing or collapsing the panel.
 *
 * @param {{open: boolean, controls: string, onToggle: () => void}} props -
 *   `controls`: the id of the panel (`<view>-right` of `ViewLayout`).
 */
export function DetailsToggle({ open, controls, onToggle }) {
  return html`<button type="button" class=${`btn sm details-toggle${open ? " active" : ""}`}
    aria-expanded=${open ? "true" : "false"} aria-controls=${controls} title=${S.toggle_title} onClick=${onToggle}>
    <${Icon} name="sidebar" size=${15} className="flip" />${S.toggle}
  </button>`;
}

/**
 * The panel's content: the chosen layer.
 *
 * @param {object} props
 * @param {import("../types.js").LayerSet} props.set
 * @param {import("../types.js").Layer} props.layer - The chosen layer of `set`.
 * @param {ReturnType<import("./cards.js").useJob>|null} [props.job] - The build
 *   followed by `useLayers`: its progress shows while it builds this layer.
 * @param {(() => void)|null} [props.onMap] - „Pokaż na mapie”; none where the
 *   map is in view.
 * @param {((key: string) => void)|null} [props.onChoose] - Chooses another
 *   variant of the same year; none in the catalog, which lists every variant.
 */
export function SetDetails({ set, layer, job = null, onMap = null, onChoose = null }) {
  const { health } = useApp();
  const preview = layer.preview;
  const following = Boolean(job?.running && preview?.job && job.id === preview.job.id);
  const variants = onChoose ? set.layers.filter((item) => item.key !== layer.key && item.title === layer.title) : [];
  const technical = [[S.technical_key, layer.key], ...layer.variant.segments.map((segment) => [S.technical_segment, segment])];
  return html`<div class="det sd">
    <div class="det-head">
      <span class="sd-title">${layer.title}</span>
      <div class="sd-head">
        <${Tech} value=${technical}><b>${variantName(layer.variant)}</b></${Tech}>
        <div class="sd-badges">
          ${layer.coverage ? html`<${CoverageBadge} coverage=${layer.coverage} />` : null}
          <${Formats} formats=${layer.variant.formats} />
        </div>
      </div>
    </div>
    <dl class="kv sd-facts">
      <dt>${S.facts.versions}</dt>
      <dd>${count(layer.versions_count, T.common.units.versions)} · ${t(S.units, { count: int(layer.units_count) })}</dd>
      <dt>${S.facts.campaigns}</dt>
      <dd>${layer.campaigns.length
        ? html`<span class="sd-campaigns">${layer.campaigns.map((campaign) => html`<code key=${campaign}>${campaign}</code>`)}</span>`
        : html`<span class="faint">${S.no_campaigns}</span>`}</dd>
      <dt>${S.facts.dates}</dt>
      <dd class="tabular">${layer.data_dates.length ? layer.data_dates.map(day).join(", ") : T.common.empty}</dd>
      <dt>${S.facts.coverage}</dt>
      <dd>${layer.coverage ? layer.coverage.label : html`<span class="faint">${S.no_coverage}</span>`}</dd>
      ${preview ? html`<dt>${S.facts.previews}</dt><dd>${previewsText(layer, S.previews_count)}</dd>` : null}
      <dt>${S.facts.store}</dt>
      <dd>${storeName(health, set.store)}</dd>
    </dl>
    ${following ? html`<${JobStatus} job=${job} />` : null}
    ${set.area ? null : html`<p class="hint">${S.no_area}</p>`}
    ${onMap || set.area
      ? html`<div class="det-actions">
          ${onMap
            ? html`<button type="button" class="btn sm primary" title=${S.show_on_map_title} onClick=${onMap}>
                <${Icon} name="map" size=${14} />${S.show_on_map}</button>`
            : null}
          ${set.area ? html`<${Compare} set=${set} layer=${layer} />` : null}
        </div>`
      : null}
    ${variants.length
      ? html`<section class="sd-section" aria-label=${t(S.variants, { title: layer.title })}>
          <div class="section-title det-sec">${t(S.variants, { title: layer.title })}</div>
          ${variants.map(
            (other) => html`<button type="button" key=${other.key} class="sd-variant" onClick=${() => onChoose(other.key)}>
              <span class="sd-variant-name">${variantName(other.variant)}</span>
              ${other.coverage ? html`<${CoverageBadge} coverage=${other.coverage} />` : null}
            </button>`,
          )}
        </section>`
      : null}
    ${layer.versions?.length ? html`<${Sheets} set=${set} layer=${layer} />` : null}
  </div>`;
}

/** „Porównaj z…”: the other layers of the area, each a link to the comparison of both. */
function Compare({ set, layer }) {
  const others = set.layers.filter((item) => item.key !== layer.key);
  if (!others.length) return null;
  const params = (other) => ({
    store: set.store,
    product: set.product,
    area_id: set.area.id,
    group: set.group === CAMPAIGN_GROUP ? CAMPAIGN_GROUP : null,
    a_layer: layer.key,
    b_layer: other.key,
  });
  return html`<details class="sd-compare">
    <summary class="btn sm" title=${S.compare_title}><${Icon} name="layers" size=${14} />${S.compare}</summary>
    <ul class="sd-list">
      ${others.map(
        (other) => html`<li key=${other.key}>
          <${Link} view="compare" params=${params(other)}>${other.title}<span class="faint"> · ${variantName(other.variant)}</span></${Link}>
        </li>`,
      )}
    </ul>
  </details>`;
}

/** The layer's versions: each opens its file card. */
function Sheets({ set, layer }) {
  const [all, setAll] = useState(false);
  const versions = layer.versions;
  const shown = all ? versions : versions.slice(0, SHEETS_SHOWN);
  return html`<section class="sd-section" aria-label=${S.sheets}>
    <div class="section-title det-sec">${S.sheets}</div>
    <ul class="sd-list sd-sheets">
      ${shown.map((version) => {
        const target = readVersionRef(version.ref);
        const name = slotName(version.slot);
        return html`<li key=${version.ref}>
          <${FileLink} store=${target?.store ?? set.store} slot=${version.slot} version=${target?.path ?? null}
            title=${t(S.sheet_title, { name, unit: version.unit ?? T.common.empty })}>${name}</${FileLink}>
          ${version.preview.state === "ready"
            ? null
            : html`<span class="sd-state">${P.state[version.preview.state] ?? version.preview.state}</span>`}
        </li>`;
      })}
    </ul>
    ${versions.length > shown.length
      ? html`<button type="button" class="btn sm ghost" onClick=${() => setAll(true)}>
          ${t(S.sheets_more, { count: int(versions.length) })}</button>`
      : null}
    ${layer.versions_count > versions.length
      ? html`<p class="hint">${t(S.sheets_capped, { shown: int(versions.length), count: int(layer.versions_count) })}</p>`
      : null}
  </section>`;
}

/**
 * The previews of a layer's versions: how many are ready, and what happens to
 * the rest.
 *
 * @param {import("../types.js").Layer} layer
 * @param {string} [template] - Of the counts: `ready` and `total`.
 * @returns {string|null} Null without an area (no previews named).
 */
function previewsText(layer, template = S.previews) {
  const preview = layer.preview;
  if (!preview) return null;
  if (!preview.total) return S.previews_none;
  const text = t(template, { ready: int(preview.ready), total: int(preview.total) });
  const state = S.previews_state[preview.state];
  return state ? `${text} · ${state}` : text;
}
