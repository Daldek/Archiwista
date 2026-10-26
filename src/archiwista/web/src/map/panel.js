/**
 * The „Wybór” panel of the map view (docs/SPEC.md 6.1, 6.3): the area and
 * its tools, the product from the index with the filters, the local state
 * of the area and what the source has for it (map/source.js). Each piece of
 * information has this one place; the map shows the same choice.
 */

import { count } from "../format.js";
import { T, t } from "../labels/index.js";
import { map as L } from "../labels/map.js";
import {
  html,
  Icon,
  ProblemView,
  Spinner,
  Tech,
  useEffect,
  useId,
  useRef,
  useState,
} from "../ui.js";
import { LocalState } from "./coverage.js";
import { bboxText } from "./geo.js";
import { productTitle } from "./products.js";
import { scaleLabel, SHEET_GRIDS } from "./sheets.js";
import { SourceStep } from "./source.js";

const KM2 = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2 });
const PRODUCT_SEARCH_FROM = 8;

/**
 * Filters of the map: the `/slots` parameters of the same name.
 *
 * @typedef {object} MapFilters
 * @property {string} [store]
 * @property {string} [product]
 * @property {string} [country]
 * @property {string} [years]
 * @property {string} [unit]
 * @property {string} [versions]
 * @property {string} [status]
 * @property {string} [q]
 */

/**
 * The area's size and countries in one line, e.g. `120,4 km² · PL`.
 *
 * @param {import("../types.js").Area} area
 * @returns {string}
 */
export function areaSummary(area) {
  const size = area.area_km2 === null ? L.area.no_km2 : t(L.area.km2, { value: KM2.format(area.area_km2) });
  return [size, area.countries.join(", ")].filter(Boolean).join(" · ");
}

/**
 * The name of an area for people.
 *
 * @param {import("../types.js").Area} area
 * @returns {string}
 */
export function areaName(area) {
  return area.name || L.area.source[area.source] || area.id;
}

/**
 * The panel's content.
 *
 * @param {object} props - See `AreaStep`, `ProductStep`, `LocalState` and
 *   `SourceStep`.
 */
export function SelectionPanel(props) {
  return html`<div class="map-steps">
    <${AreaStep} ...${props} />
    <${ProductStep} ...${props} />
    <${LocalState} area=${props.area} filters=${props.filters} products=${props.products?.items ?? []}
      stores=${props.stores} names=${props.names} indexKey=${props.indexKey} onRefreshed=${props.onRefreshed} />
    <${SourceStep} area=${props.area} areaLabel=${props.area ? areaName(props.area) : null} filters=${props.filters}
      stores=${props.stores} names=${props.names} />
  </div>`;
}

function Step({ number, done, title, aside, children }) {
  const id = useId();
  return html`<section class=${`step ${done ? "done" : "current"}`} aria-labelledby=${id}>
    <div class="step-head">
      <span class="step-num" aria-hidden="true">
        ${done ? html`<${Icon} name="check" size=${12} stroke=${3} />` : number}
      </span>
      <h2 class="step-title" id=${id}>${title}</h2>
      ${aside}
    </div>
    ${children}
  </section>`;
}

/**
 * Step 1: the area and its tools.
 *
 * @param {object} props
 * @param {import("../types.js").Area|null} props.area
 * @param {boolean} props.areaBusy - An area is being saved.
 * @param {import("../types.js").Problem|null} props.areaProblem
 * @param {string|null} props.areaNote - A sheet not found and the like.
 * @param {"rect"|"poly"|null} props.tool
 * @param {(tool: "rect"|"poly"|null) => void} props.onTool
 * @param {() => void} props.onView
 * @param {(file: File, layer?: string) => void} props.onFile
 * @param {{file: File, layers: string[]}|null} props.fileLayers
 * @param {(sheet: string) => void} props.onSheetCode
 * @param {{on: boolean, system: string, scale: string}} props.grid
 * @param {(patch: object) => void} props.onGrid
 * @param {() => void} props.onClear
 * @param {import("preact").RefObject<HTMLElement>} props.areaRef - The step, to
 *   focus on „Zmień”.
 */
function AreaStep({
  area,
  areaBusy,
  areaProblem,
  areaNote,
  tool,
  onTool,
  onView,
  onFile,
  fileLayers,
  onSheetCode,
  grid,
  onGrid,
  onClear,
  areaRef,
}) {
  const file = useRef(null);
  const ids = useId();
  const [sheet, setSheet] = useState("");
  const [layer, setLayer] = useState("");
  useEffect(() => setLayer(fileLayers?.layers[0] ?? ""), [fileLayers]);
  const toggle = (name) => onTool(tool === name ? null : name);
  const submitSheet = (event) => {
    event.preventDefault();
    if (sheet.trim()) onSheetCode(sheet.trim());
  };
  const aside = area
    ? html`<button type="button" class="btn ghost sm step-aside" onClick=${onClear}>${L.area.clear}</button>`
    : null;
  return html`<div ref=${areaRef} tabindex="-1" class="step-anchor">
    <${Step} number="1" done=${Boolean(area)} title=${L.steps.area} aside=${aside}>
      <div class="tool-row">
        <button type="button" class=${`btn ${tool === "rect" ? "active" : ""}`} aria-pressed=${tool === "rect" ? "true" : "false"}
          onClick=${() => toggle("rect")}><${Icon} name="rect" />${L.area.rect}</button>
        <button type="button" class=${`btn ${tool === "poly" ? "active" : ""}`} aria-pressed=${tool === "poly" ? "true" : "false"}
          onClick=${() => toggle("poly")}><${Icon} name="poly" />${L.area.poly}</button>
        <button type="button" class="btn" title=${L.area.view_title} onClick=${onView}>
          <${Icon} name="map" />${L.area.view}</button>
        <button type="button" class="btn" title=${L.area.file_title} onClick=${() => file.current.click()}>
          <${Icon} name="file" />${L.area.file}</button>
      </div>
      <input ref=${file} type="file" class="visually-hidden" tabindex="-1" aria-label=${L.area.file_label}
        accept=".geojson,.json,.gpkg,.zip,application/geo+json,application/json,application/zip"
        onChange=${(event) => {
          const chosen = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (chosen) onFile(chosen);
        }} />
      ${fileLayers
        ? html`<div class="layer-choice">
            <label class="field">
              <span>${L.area.layers}</span>
              <select value=${layer} onChange=${(event) => setLayer(event.currentTarget.value)}>
                ${fileLayers.layers.map((name) => html`<option value=${name}>${name}</option>`)}
              </select>
            </label>
            <button type="button" class="btn sm primary" disabled=${!layer}
              onClick=${() => onFile(fileLayers.file, layer)}>${L.area.layer_submit}</button>
          </div>`
        : null}
      <form class="sheet-form" onSubmit=${submitSheet}>
        <label class="field">
          <span>${L.area.sheet_label}</span>
          <span class="sheet-input">
            <input class="mono" value=${sheet} placeholder=${L.area.sheet_placeholder} spellcheck="false"
              autocomplete="off" onInput=${(event) => setSheet(event.currentTarget.value)} />
            <button type="submit" class="btn" disabled=${!sheet.trim()}>${L.area.sheet_submit}</button>
          </span>
        </label>
      </form>
      <div class="grid-row" role="group" aria-label=${L.area.grid}>
        <button type="button" class=${`btn sm ${grid.on ? "active" : ""}`} aria-pressed=${grid.on ? "true" : "false"}
          title=${L.area.grid_title} onClick=${() => onGrid({ on: !grid.on })}>
          <${Icon} name="grid" size=${14} />${L.area.grid}</button>
        <label class="visually-hidden" for=${`${ids}-system`}>${L.area.grid_system}</label>
        <select id=${`${ids}-system`} class="select-sm" value=${grid.system}
          onChange=${(event) => {
            const system = event.currentTarget.value;
            const scales = SHEET_GRIDS[system];
            onGrid({ system, scale: scales.includes(grid.scale) ? grid.scale : scales[scales.length - 1] });
          }}>
          ${Object.keys(SHEET_GRIDS).map(
            (system) => html`<option value=${system}>${L.area.systems[system] ?? system}</option>`,
          )}
        </select>
        <label class="visually-hidden" for=${`${ids}-scale`}>${L.area.grid_scale}</label>
        <select id=${`${ids}-scale`} class="select-sm" value=${grid.scale}
          onChange=${(event) => onGrid({ scale: event.currentTarget.value })}>
          ${SHEET_GRIDS[grid.system].map((scale) => html`<option value=${scale}>${scaleLabel(scale)}</option>`)}
        </select>
      </div>
      ${areaBusy ? html`<p class="hint"><${Spinner} label=${L.area.saving} /></p>` : null}
      ${areaProblem ? html`<${ProblemView} problem=${areaProblem} compact />` : null}
      ${areaNote ? html`<p class="hint warn" role="status">${areaNote}</p>` : null}
      ${area ? html`<${AreaCard} area=${area} />` : html`<p class="hint">${L.area.hint}</p>`}
    <//>
  </div>`;
}

function AreaCard({ area }) {
  return html`<div class="area-card">
    <div class="big">${areaName(area)}</div>
    <div class="muted tabular">${areaSummary(area)}</div>
    <div class="area-tech">
      <${Tech} value=${[
        [L.area.id, area.id],
        [L.area.bbox, bboxText(area.bbox)],
        [L.area.crs, area.area_crs ?? T.common.empty],
        [L.area.source_label, area.source],
      ]}>
        <span class="faint">${L.area.source[area.source] ?? area.source}</span>
      <//>
    </div>
  </div>`;
}

/**
 * Step 2: the product from the index and the filters.
 *
 * @param {object} props
 * @param {import("../types.js").ProductList|undefined} props.products
 * @param {import("../api.js").ApiError|undefined} props.productsError
 * @param {MapFilters} props.filters
 * @param {(patch: Object<string, string|null>) => void} props.onFilters
 * @param {import("../types.js").StoreSettings[]} props.stores
 */
function ProductStep({ products, productsError, filters, onFilters, stores }) {
  const [search, setSearch] = useState("");
  const [listOpen, setListOpen] = useState(!filters.product);
  const items = products?.items ?? [];
  const known = items.filter((item) => item.product);
  const unknown = items.filter((item) => !item.product);
  const chosen = known.find((item) => item.product === filters.product);
  const open = listOpen || !chosen;
  const needle = search.trim().toLowerCase();
  const shown = needle
    ? known.filter((item) =>
        [item.product, productTitle(item), ...item.segments.map((s) => s.segment.label)].some((text) =>
          text.toLowerCase().includes(needle),
        ),
      )
    : known;
  const pick = (product) => {
    setListOpen(!product);
    onFilters({ product });
  };
  const slots = known.reduce((sum, item) => sum + item.slots, 0);
  const item = (product) => html`<button type="button" key=${product.product}
    class=${`product-item ${product.product === filters.product ? "on" : ""}`}
    aria-pressed=${product.product === filters.product ? "true" : "false"} onClick=${() => pick(product.product)}>
    <span class="product-name" title=${productTitle(product)}>${productTitle(product)}</span>
    <span class="product-meta">
      <code>${product.product}</code>${` · ${[
        product.countries.join(", ") || T.common.empty,
        count(product.slots, L.units.slots),
        count(product.versions, T.common.units.versions),
      ].join(" · ")}`}
    </span>
  </button>`;
  const aside = open
    ? null
    : html`<button type="button" class="btn ghost sm step-aside" aria-expanded="false"
        onClick=${() => setListOpen(true)}>${L.product.change}</button>`;
  return html`<${Step} number="2" done=${Boolean(filters.product)} title=${L.steps.product} aside=${aside}>
    ${productsError ? html`<${ProblemView} problem=${productsError.problem} compact />` : null}
    ${!products && !productsError ? html`<${Spinner} />` : null}
    ${products && !items.length ? html`<p class="hint">${L.product.empty}</p>` : null}
    ${open && known.length > PRODUCT_SEARCH_FROM
      ? html`<input class="product-search" type="search" value=${search} placeholder=${L.product.search}
          aria-label=${L.product.search} onInput=${(event) => setSearch(event.currentTarget.value)} />`
      : null}
    ${!open ? html`<div class="product-list">${item(chosen)}</div>` : null}
    ${open && items.length
      ? html`<div class="product-list" role="group" aria-label=${L.product.list}>
          <button type="button" class=${`product-item ${filters.product ? "" : "on"}`}
            aria-pressed=${filters.product ? "false" : "true"} onClick=${() => pick(null)}>
            <span class="product-name">${L.product.all}</span>
            <span class="product-meta">${t(L.product.all_hint, { slots: count(slots, L.units.slots) })}</span>
          </button>
          ${shown.map(item)}
          ${unknown.length
            ? html`<div class="product-item static" title=${L.product.unknown_hint}>
                <span class="product-name">${L.product.unknown}</span>
                <span class="product-meta">${unknown
                  .flatMap((entry) => entry.segments.map((segment) => segment.segment.path ?? segment.segment.label))
                  .join(", ")}</span>
              </div>`
            : null}
        </div>`
      : null}
    ${chosen ? html`<${Variants} product=${chosen} stores=${stores} />` : null}
    <${FilterFields} filters=${filters} onFilters=${onFilters} stores=${stores} products=${known} />
  <//>`;
}

function Variants({ product, stores }) {
  const several = new Set(product.segments.map((segment) => segment.store)).size > 1;
  const storeName = (id) => stores.find((store) => store.id === id)?.name ?? id;
  return html`<details class="variants">
    <summary>${L.product.variants} (${product.segments.length})</summary>
    <ul>
      ${product.segments.map(
        (item) => html`<li key=${`${item.store}:${item.segment.path}`}>
          <${Tech} value=${[
            [L.product.segment, item.segment.path ?? T.common.empty],
            [L.product.dataset_key, item.segment.dataset_key ?? T.common.empty],
          ]}>${item.segment.label}<//>
          <span class="faint">${[
            several ? storeName(item.store) : null,
            count(item.slots, L.units.slots),
            count(item.versions, T.common.units.versions),
          ]
            .filter(Boolean)
            .join(" · ")}</span>
        </li>`,
      )}
    </ul>
  </details>`;
}

const TEXT_FILTERS = ["years", "unit", "q"];

function FilterFields({ filters, onFilters, stores, products }) {
  const id = useId();
  const [draft, setDraft] = useState(() => pickText(filters));
  useEffect(() => setDraft(pickText(filters)), [TEXT_FILTERS.map((name) => filters[name] ?? "").join("|")]);
  const set = (name, value) => onFilters({ [name]: value || null });
  const apply = (event) => {
    event?.preventDefault();
    const patch = {};
    for (const name of TEXT_FILTERS) {
      const value = draft[name].trim();
      if (value !== (filters[name] ?? "")) patch[name] = value || null;
    }
    if (Object.keys(patch).length) onFilters(patch);
  };
  const countries = [...new Set(products.flatMap((item) => item.countries))].sort();
  const active = ["store", "country", "years", "unit", "versions", "status", "q"].filter((name) => filters[name]);
  const field = (name, label, control, hint) => html`<div class="field">
    <label for=${`${id}-${name}`}>${label}</label>${control}
    ${hint ? html`<span class="field-hint" id=${`${id}-${name}-hint`}>${hint}</span>` : null}
  </div>`;
  const text = (name, placeholder, hint) => html`<input id=${`${id}-${name}`} class=${name === "q" ? "" : "mono"}
    value=${draft[name]} placeholder=${placeholder} spellcheck="false" autocomplete="off"
    aria-describedby=${hint ? `${id}-${name}-hint` : null}
    onInput=${(event) => setDraft({ ...draft, [name]: event.currentTarget.value })} onBlur=${apply} />`;
  return html`<details class="map-filters" open=${active.length > 0}>
    <summary>${L.filters.title}${active.length ? html` <span class="badge-count">${active.length}</span>` : null}</summary>
    <form class="filter-fields" onSubmit=${apply}>
      ${stores.length > 1
        ? field(
            "store",
            L.filters.store,
            html`<select id=${`${id}-store`} value=${filters.store ?? ""} onChange=${(event) => set("store", event.currentTarget.value)}>
              <option value="">${L.filters.store_all}</option>
              ${stores.map((store) => html`<option value=${store.id}>${store.name}</option>`)}
            </select>`,
          )
        : null}
      ${field(
        "country",
        L.filters.country,
        html`<select id=${`${id}-country`} value=${filters.country ?? ""} onChange=${(event) => set("country", event.currentTarget.value)}>
          <option value="">${L.filters.country_all}</option>
          ${countries.map((code) => html`<option value=${code}>${L.countries[code] ? `${L.countries[code]} (${code})` : code}</option>`)}
        </select>`,
      )}
      ${field("years", L.filters.years, text("years", L.filters.years_placeholder))}
      ${field("unit", L.filters.unit, text("unit", L.filters.unit_placeholder, L.filters.unit_hint), L.filters.unit_hint)}
      ${field(
        "versions",
        L.filters.versions,
        html`<select id=${`${id}-versions`} value=${filters.versions ?? "current"}
          onChange=${(event) => set("versions", event.currentTarget.value === "current" ? null : event.currentTarget.value)}>
          ${Object.entries(L.filters.versions_options).map(([value, label]) => html`<option value=${value}>${label}</option>`)}
        </select>`,
      )}
      ${field(
        "status",
        L.filters.status,
        html`<select id=${`${id}-status`} value=${filters.status ?? ""} onChange=${(event) => set("status", event.currentTarget.value)}>
          <option value="">${L.filters.status_all}</option>
          ${Object.entries(L.filters.status_options).map(([value, label]) => html`<option value=${value}>${label}</option>`)}
        </select>`,
      )}
      ${field("q", L.filters.q, text("q", L.filters.q_placeholder))}
      <div class="filter-actions">
        <button type="submit" class="btn sm">${L.filters.apply}</button>
        ${active.length
          ? html`<button type="button" class="btn sm ghost"
              onClick=${() => onFilters(Object.fromEntries(active.map((name) => [name, null])))}>${L.filters.clear}</button>`
          : null}
      </div>
    </form>
  </details>`;
}

function pickText(filters) {
  return Object.fromEntries(TEXT_FILTERS.map((name) => [name, filters[name] ?? ""]));
}
