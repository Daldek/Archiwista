/**
 * „Oś czasu” of the catalog (`layout=timeline`; docs/SPEC.md 6.1, 6.5 b in
 * its local version; plan v0.2 step 13b): the product's layers in the store
 * — with an area, in the area — as a grid of variants × years. The years
 * run left to right, also those without data (a dot), then the editions and
 * labels without a year; with `group=campaign` a year has a column per
 * campaign. A row is a variant without the file format (A-ADR-017), its
 * formats as badges. A cell's bar is the layer's local coverage of the
 * area, or without an area its number of versions against the largest.
 *
 * A cell is a layer: a click, `Enter` or `Spacja` chooses it (`layer` of the
 * address, one choice with the map, the Wachlarz and the details panel);
 * arrows move between the cells with data, `Home`/`End` to a row's ends
 * (ARIA grid, roving tabindex).
 */

import { listProducts } from "../api.js";
import { useApp } from "../context.js";
import { count, int } from "../format.js";
import { useResource } from "../hooks.js";
import { T, t } from "../labels/index.js";
import { timeline as L } from "../labels/timeline.js";
import { CAMPAIGN_GROUP, GROUP_PARAM, LAYER_PARAM, useLayers, variantName } from "../map/previews.js";
import { productNames, productStores } from "../map/products.js";
import { html, loadStylesheet, ProblemView, Seg, Spinner, useId, useMemo, useRef, useState } from "../ui.js";
import { describeLayer, Formats, staleText } from "./set-details.js";

await loadStylesheet(new URL("./timeline.css", import.meta.url));

/** Smallest width of a year column and of a column of an edition or label, px. */
const YEAR_PX = 46;
const TITLE_PX = 92;

/**
 * The layers of the catalog's product: of the address's store, else of the
 * first store holding the product; in the area when the address has one.
 *
 * @param {Object<string, string>} params - The catalog's address.
 * @param {boolean} enabled - False: no request (the list layout).
 * @returns {{product: string|null, name: string|null, store: string|null,
 *   noStore: boolean, layers: ReturnType<typeof useLayers>}}
 */
export function useTimelineLayers(params, enabled) {
  const { settings, health } = useApp();
  const product = enabled ? params.product || null : null;
  const wantedStore = params.store || null;
  const indexKey = (health?.stores ?? []).map((item) => `${item.store}:${item.state.indexed_at ?? ""}`).join(",");
  const products = useResource(
    (signal) => (product ? listProducts(wantedStore ? { store: wantedStore } : {}, { signal }) : Promise.resolve(null)),
    [product ?? "", wantedStore ?? "", indexKey],
  );
  const found = products.data?.items.find((item) => item.product === product) ?? null;
  const ids = (settings?.stores ?? []).map((item) => item.id);
  const store = wantedStore ?? (found ? (productStores(found, ids)[0] ?? null) : null);
  const layers = useLayers(
    {
      store,
      product,
      areaId: params.area_id || null,
      group: params[GROUP_PARAM] === CAMPAIGN_GROUP ? CAMPAIGN_GROUP : null,
      needsArea: false,
    },
    params[LAYER_PARAM] || null,
    indexKey,
  );
  return {
    product,
    name: found ? (productNames([found]).get(product) ?? product) : product,
    store,
    noStore: Boolean(product) && Boolean(products.data) && !store,
    layers,
  };
}

/**
 * The timeline.
 *
 * @param {object} props
 * @param {ReturnType<typeof useTimelineLayers>} props.shared
 * @param {(key: string) => void} props.onChoose
 * @param {(group: string|null) => void} props.onGroup
 */
export function CatalogTimeline({ shared, onChoose, onGroup }) {
  const { set, layer, loading, error } = shared.layers;
  let body;
  if (!shared.product) body = html`<p class="tl-message">${L.need_product}</p>`;
  else if (shared.noStore) body = html`<p class="tl-message">${L.no_store}</p>`;
  else if (!set) {
    body = error
      ? html`<div class="tl-message"><${ProblemView} problem=${error.problem} /></div>`
      : html`<div class="tl-message"><${Spinner} label=${L.loading} /></div>`;
  } else if (!set.layers.length) body = html`<p class="tl-message">${L.empty}</p>`;
  if (body) return html`<div class="tl">${body}</div>`;

  const campaigns = set.group === CAMPAIGN_GROUP || set.layers.some((item) => item.campaigns.length > 1);
  return html`<div class="tl">
    <div class="tl-head">
      <h2 class="tl-title">${t(L.heading, { product: shared.name })}</h2>
      <span class="muted">${set.area ? t(L.area, { name: set.area.name ?? set.area.id }) : L.whole_store}</span>
      ${campaigns
        ? html`<span class="filter-group"><span class="filter-label" aria-hidden="true">${L.group_label}</span>
            <${Seg} small label=${L.group_label} value=${set.group === CAMPAIGN_GROUP ? CAMPAIGN_GROUP : "year"}
              onChange=${(value) => onGroup(value === CAMPAIGN_GROUP ? CAMPAIGN_GROUP : null)}
              options=${[
                { value: "year", label: L.group.year },
                { value: CAMPAIGN_GROUP, label: L.group.campaign },
              ]} /></span>`
        : null}
      ${loading ? html`<${Spinner} quiet label=${L.loading} />` : null}
    </div>
    ${set.stale ? html`<p class="hint warn">${staleText(set)}</p>` : null}
    ${error ? html`<${ProblemView} problem=${error.problem} compact />` : null}
    <${Grid} set=${set} chosen=${layer?.key ?? null} onChoose=${onChoose} />
    <div class="tl-legend">
      <span><i class="tl-sw" aria-hidden="true"></i>${set.area ? L.bar_coverage : L.bar_versions}</span>
      <span><i class="tl-dot" aria-hidden="true"></i>${L.empty_years}</span>
    </div>
    <p class="tl-note faint">${L.filters_note}</p>
  </div>`;
}

/** The grid of variants × years. */
function Grid({ set, chosen, onChoose }) {
  const id = useId();
  const model = useMemo(() => timelineModel(set.layers, set.group === CAMPAIGN_GROUP), [set]);
  const grid = useRef(null);
  const [focused, setFocused] = useState(null);
  const area = Boolean(set.area);
  const most = Math.max(1, ...set.layers.map((item) => item.versions_count));
  const stop = model.places.has(focused) ? focused : model.places.has(chosen) ? chosen : model.first;
  const keys = (event) => {
    const cell = event.target.closest("[data-layer]");
    if (!cell) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onChoose(cell.dataset.layer);
      return;
    }
    const next = neighbour(model, cell.dataset.layer, event);
    if (next === undefined) return;
    event.preventDefault();
    if (next === null) return;
    setFocused(next);
    grid.current.querySelector(`[data-layer="${CSS.escape(next)}"]`)?.focus();
  };
  const template = model.columns.map((column) => `minmax(${column.year === null ? TITLE_PX : YEAR_PX}px, 1fr)`).join(" ");
  const least = model.columns.reduce((sum, column) => sum + (column.year === null ? TITLE_PX : YEAR_PX), 0);
  return html`<div class="tl-scroll">
    <div class="tl-grid" role="grid" ref=${grid} aria-label=${L.grid} aria-describedby=${`${id}-keys`}
      aria-rowcount=${model.rows.length + 1} aria-colcount=${model.columns.length + 1}
      style=${`--tl-columns:${template};min-width:calc(var(--tl-head) + ${least}px)`} onKeyDown=${keys}>
      <div class="tl-row tl-header" role="row" aria-rowindex="1">
        <span class="tl-rowhead" role="columnheader" aria-colindex="1">${L.variant}</span>
        ${model.columns.map(
          (column, at) => html`<span key=${column.key} role="columnheader" aria-colindex=${at + 2}
            class=${`tl-col${column.empty ? " empty" : ""}`} title=${column.empty ? t(L.year_empty, { year: column.label }) : null}>
            <span class="tl-year">${column.label}</span>
            ${column.sub !== null ? html`<span class="tl-sub">${column.sub || L.no_campaign}</span>` : null}
          </span>`,
        )}
      </div>
      ${model.rows.map(
        (row, at) => html`<div key=${row.key} class="tl-row" role="row" aria-rowindex=${at + 2}>
          <span class="tl-rowhead" role="rowheader" aria-colindex="1">
            <span class="tl-variant">${variantName(row.variant)}</span>
            <${Formats} formats=${[...row.formats].sort()} />
          </span>
          ${model.columns.map((column, place) => {
            const layer = row.cells.get(column.key);
            if (!layer) {
              return html`<span key=${column.key} role="gridcell" aria-colindex=${place + 2} class="tl-cell none">
                <i class="tl-dot" aria-hidden="true"></i><span class="visually-hidden">${L.no_data}</span>
              </span>`;
            }
            const on = layer.key === chosen;
            const share = area ? (layer.coverage?.ratio ?? 0) : layer.versions_count / most;
            const value = area ? percentText(layer.coverage) : int(layer.versions_count);
            return html`<span key=${column.key} role="gridcell" aria-colindex=${place + 2} data-layer=${layer.key}
              class=${`tl-cell has${on ? " on" : ""}`} aria-selected=${on ? "true" : "false"}
              tabindex=${layer.key === stop ? "0" : "-1"} aria-label=${cellName(layer, area)} title=${describeLayer(layer)}
              onClick=${() => onChoose(layer.key)} onFocus=${() => setFocused(layer.key)}>
              <span class="tl-track" aria-hidden="true">
                <span class=${`tl-bar${share > 0 ? "" : " zero"}`} style=${`--h:${(Math.min(1, share) * 100).toFixed(2)}%`}></span>
              </span>
              <span class="tl-value" aria-hidden="true">${value}</span>
            </span>`;
          })}
        </div>`,
      )}
    </div>
    <p class="visually-hidden" id=${`${id}-keys`}>${L.keys}</p>
  </div>`;
}

/**
 * Rows, columns and cells of the grid.
 *
 * @param {import("../types.js").Layer[]} layers - Newest first.
 * @param {boolean} byCampaign - The set is split by campaign.
 * @returns {{rows: Array<{key: string, variant: import("../types.js").LayerVariant,
 *   formats: Set<string>, cells: Map<string, import("../types.js").Layer>}>,
 *   columns: Array<{key: string, year: number|null, label: string, sub:
 *   string|null, empty: boolean}>, places: Map<string, {row: number, column:
 *   number}>, items: Array<Array<{key: string, column: number}>>, first:
 *   string|null}}
 */
function timelineModel(layers, byCampaign) {
  const columns = [];
  const years = layers.filter((layer) => layer.year !== null).map((layer) => layer.year);
  if (years.length) {
    for (let year = Math.min(...years); year <= Math.max(...years); year += 1) {
      const subs = [...new Set(layers.filter((layer) => layer.year === year).map(campaignOf))].sort();
      if (!subs.length) columns.push({ key: `y:${year}:`, year, label: String(year), sub: null, empty: true });
      for (const sub of subs) {
        columns.push({ key: `y:${year}:${sub}`, year, label: String(year), sub: byCampaign ? sub : null, empty: false });
      }
    }
  }
  for (const layer of [...layers].reverse()) {
    if (layer.year === null && !columns.some((column) => column.key === `t:${layer.title}`)) {
      columns.push({ key: `t:${layer.title}`, year: null, label: layer.title, sub: null, empty: false });
    }
  }
  const rows = [];
  const byVariant = new Map();
  for (const layer of layers) {
    const variant = variantKey(layer);
    if (!byVariant.has(variant)) {
      const row = { key: variant, variant: layer.variant, formats: new Set(), cells: new Map() };
      byVariant.set(variant, row);
      rows.push(row);
    }
    const row = byVariant.get(variant);
    for (const format of layer.variant.formats) row.formats.add(format);
    row.cells.set(columnOf(layer), layer);
  }
  const index = new Map(columns.map((column, at) => [column.key, at]));
  const places = new Map();
  const items = rows.map((row, at) => {
    const cells = [...row.cells.entries()]
      .map(([column, layer]) => ({ key: layer.key, column: index.get(column) }))
      .sort((a, b) => a.column - b.column);
    for (const item of cells) places.set(item.key, { row: at, column: item.column });
    return cells;
  });
  return { rows, columns, places, items, first: items[0]?.[0]?.key ?? null };
}

/**
 * The cell a key moves to from a cell, `null` for none there, `undefined` for
 * a key that does not move.
 */
function neighbour(model, key, event) {
  const place = model.places.get(key);
  if (!place) return undefined;
  const row = model.items[place.row];
  const at = row.findIndex((item) => item.key === key);
  const lastRow = model.items[model.items.length - 1];
  switch (event.key) {
    case "ArrowRight":
      return row[at + 1]?.key ?? null;
    case "ArrowLeft":
      return row[at - 1]?.key ?? null;
    case "Home":
      return (event.ctrlKey ? model.items[0][0] : row[0]).key;
    case "End":
      return (event.ctrlKey ? lastRow[lastRow.length - 1] : row[row.length - 1]).key;
    case "ArrowDown":
      return nearest(model.items[place.row + 1], place.column);
    case "ArrowUp":
      return nearest(model.items[place.row - 1], place.column);
    default:
      return undefined;
  }
}

/** The cell of a row nearest to a column (the left one of two as near). */
function nearest(row, column) {
  if (!row) return null;
  return row.reduce((best, item) => (Math.abs(item.column - column) < Math.abs(best.column - column) ? item : best)).key;
}

/** The variant part of a layer's key (`<variant>:<year|edition|label>[:<campaign>]`). */
function variantKey(layer) {
  const cut = layer.key.indexOf(":");
  return cut < 0 ? layer.key : layer.key.slice(0, cut);
}

/** The column of a layer: its year (and campaign), else its title. */
function columnOf(layer) {
  return layer.year === null ? `t:${layer.title}` : `y:${layer.year}:${campaignOf(layer)}`;
}

/** A campaign layer's campaign; empty for the other layers of a year. */
function campaignOf(layer) {
  return layer.kind === "campaign" ? (layer.campaigns[0] ?? "") : "";
}

/** A cell for screen readers: its layer, variant and bar. */
function cellName(layer, area) {
  const value = area ? (layer.coverage?.label ?? T.common.empty) : count(layer.versions_count, T.common.units.versions);
  return `${layer.title} · ${variantName(layer.variant)} · ${value}`;
}

/** The coverage under a bar, e.g. „83%”. */
function percentText(coverage) {
  return coverage?.percent === null || coverage?.percent === undefined ? T.common.empty : `${coverage.percent}%`;
}
