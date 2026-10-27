/**
 * The catalog's filter panel: one field per parameter of `GET /slots`
 * (docs/SPEC.md 6.6), read from and written to the address. Lists and
 * switches apply at once; typed values (years, unit, rectangle) when the
 * field is left or Enter is pressed. A value the API refuses is marked on
 * its field with the API's message.
 *
 * For a station product (views/catalog-stations.js) the fields are those of
 * `GET /stations` (SPEC 6.6 for IMGW measurements): the dataset, the station
 * kind or the meteo types, the river code with its tributaries, active or
 * historical, a variable, the coverage chips of each variable of the dataset
 * (several states of one variable are alternatives) with its least full
 * years, the range of the labels and the switch „Lata: hydrologiczne /
 * kalendarzowe”, which writes `year_type` to the address and remembers the
 * choice for the family in the person's preferences (`PUT /preferences`,
 * P15). The Timeline (`layout=timeline`) shows one
 * dataset: its field has no „Wszystkie zbiory” and shows the product's first
 * when the address names none, and a coverage filter then writes it to the
 * address, since the filters need a dataset.
 */

import { getArea } from "../api.js";
import { int } from "../format.js";
import { useResource } from "../hooks.js";
import { catalog as L } from "../labels/catalog.js";
import { t } from "../labels/index.js";
import { METEO_KINDS, STATION_STATES } from "../map/stations.js";
import { html, Icon, Seg, Tech, useEffect, useState } from "../ui.js";
import { STATION_FILTERS } from "./catalog-stations.js";
import { useYearType, YEAR_TYPES } from "./year-type.js";

const F = L.filters;
/** Values of `versions`, the first one the API's default. */
const VERSIONS = ["current", "all", "full_sheet", "pinned", "noncurrent_unpinned"];
/** Values of `status`. */
const STATUSES = ["ok", "missing", "no_sidecar", "unreadable", "unrecognized"];
/** Parameters the panel sets (`q` and `location` are set above the list). */
export const FILTERS = [
  "store",
  "product",
  "country",
  "years",
  "unit",
  "versions",
  "status",
  "area_id",
  "bbox",
  "bbox_crs",
  "limit",
];

/** The years of `years`: `2023`, `2020-2023`, `2020-` or `-2023`. */
function splitYears(years) {
  if (!years) return { from: "", to: "" };
  if (!years.includes("-")) return { from: years, to: years };
  const [from, to] = years.split("-");
  return { from, to };
}

/** The `years` parameter of two years, either of them empty. */
function joinYears(from, to) {
  if (from && to) return from === to ? from : `${from}-${to}`;
  if (from) return `${from}-`;
  if (to) return `-${to}`;
  return null;
}

/**
 * A product's name for people, as the map names it: the producer's name of
 * its largest segment up to the variant details (` · PL-1992 · EVRF2007`).
 */
function productName(product) {
  const largest = [...product.segments].sort((a, b) => b.slots - a.slots)[0];
  return (largest?.segment.label ?? product.product ?? "").split(" · ")[0];
}

/**
 * The filter panel.
 *
 * @param {object} props
 * @param {Object<string, string>} props.query - The address's parameters of the list.
 * @param {Array<{store: string, name: string}>} props.stores - Configured stores.
 * @param {{data?: import("../types.js").ProductList}} props.products - `GET /products`.
 * @param {StationPanel|null} props.stations - For a station product, else `null`.
 * @param {Object<string, string>} props.errors - API messages by parameter.
 * @param {(patch: Object<string, string|null>) => void} props.onChange
 */
export function CatalogFilters({ query, stores, products, stations, errors, onChange }) {
  const items = products.data?.items.filter((item) => item.product !== null) ?? [];
  const chosen = items.find((item) => item.product === query.product);
  const countries = [...new Set(items.flatMap((item) => item.countries))].sort();
  if (query.country && !countries.includes(query.country)) countries.push(query.country);
  const select = (name) => (event) => onChange({ [name]: event.currentTarget.value || null });
  const { from, to } = splitYears(query.years);
  const names = stations ? STATION_FILTERS : FILTERS;
  const active = names.some((name) => query[name]);
  const clear = () => onChange(Object.fromEntries(names.map((name) => [name, null])));

  return html`<div class=${`cat-filters${stations ? " cat-stations-fields" : ""}`}>
    ${stores.length > 1 || query.store
      ? html`<${Field} name="store" label=${F.store} errors=${errors}>
          <select id="cat-f-store" value=${query.store ?? ""} onChange=${select("store")}>
            <option value="">${F.store_any}</option>
            ${withCurrent(stores.map((store) => store.store), query.store).map(
              (id) => html`<option value=${id}>${storeName(stores, id)}</option>`,
            )}
          </select>
        </${Field}>`
      : null}
    <${Field} name="product" label=${F.product} errors=${errors}>
      <select id="cat-f-product" value=${query.product ?? ""} onChange=${select("product")}>
        <option value="">${F.product_any}</option>
        ${withCurrent(items.map((item) => item.product), query.product).map((code) => {
          const item = items.find((candidate) => candidate.product === code);
          const text = item
            ? t(F.product_option, { product: code, name: productName(item), count: int(item.slots) })
            : code;
          return html`<option value=${code}>${text}</option>`;
        })}
      </select>
      ${chosen ? html`<${Segments} product=${chosen} />` : null}
    </${Field}>
    ${stations
      ? html`<${StationFields} query=${query} stations=${stations} errors=${errors} onChange=${onChange} />`
      : html`<${FileFields} query=${query} errors=${errors} onChange=${onChange} select=${select}
          countries=${countries} from=${from} to=${to} />`}
    <${AreaFields} query=${query} errors=${errors} onChange=${onChange} />
    ${stations && (query.area_id || query.bbox)
      ? html`<label class="check-field st-check"><input type="checkbox" checked=${query.boundary !== "false"}
          onChange=${(event) => onChange({ boundary: event.currentTarget.checked ? null : "false" })} />
          ${L.stations.filters.boundary}</label>`
      : null}
    ${query.limit
      ? html`<div class="cat-limit">
          <span class="muted">${F.limit}:</span> <code>${query.limit}</code>
          <button type="button" class="btn ghost sm" onClick=${() => onChange({ limit: null })}
            aria-label=${t(F.remove, { name: F.limit })}><${Icon} name="x" size=${13} /></button>
        </div>`
      : null}
    <button type="button" class="btn sm" disabled=${!active} onClick=${clear} title=${F.clear_title}>
      <${Icon} name="x" size=${14} />${F.clear}
    </button>
  </div>`;
}

/** The fields of files: country, data years, unit, versions and state. */
function FileFields({ query, errors, onChange, select, countries, from, to }) {
  return html`<${Field} name="country" label=${F.country} errors=${errors}>
      <select id="cat-f-country" value=${query.country ?? ""} onChange=${select("country")}>
        <option value="">${F.country_any}</option>
        ${countries.map(
          (code) => html`<option value=${code}>${L.countries[code] ? `${L.countries[code]} (${code})` : code}</option>`,
        )}
      </select>
    </${Field}>
    <${Field} name="years" label=${F.years} errors=${errors} hint=${F.years_hint} group>
      <div class="cat-years">
        <${TextFilter} id="cat-f-years" label=${F.years_from} value=${from}
          placeholder=${F.years_placeholder} numeric invalid=${Boolean(errors.years)}
          onCommit=${(value) => onChange({ years: joinYears(value, to) })} />
        <span aria-hidden="true">–</span>
        <${TextFilter} id="cat-f-years-to" label=${F.years_to} value=${to}
          placeholder=${F.years_placeholder} numeric invalid=${Boolean(errors.years)}
          onCommit=${(value) => onChange({ years: joinYears(from, value) })} />
      </div>
    </${Field}>
    <${Field} name="unit" label=${F.unit} errors=${errors} hint=${F.unit_hint}>
      <${TextFilter} id="cat-f-unit" value=${query.unit ?? ""} placeholder=${F.unit_placeholder} mono
        invalid=${Boolean(errors.unit)} onCommit=${(value) => onChange({ unit: value || null })} />
    </${Field}>
    <${Field} name="versions" label=${F.versions} errors=${errors}>
      <select id="cat-f-versions" value=${query.versions ?? "current"}
        onChange=${(event) => {
          const value = event.currentTarget.value;
          onChange({ versions: value === "current" ? null : value });
        }}>
        ${withCurrent(VERSIONS, query.versions).map(
          (value) => html`<option value=${value} title=${value}>${L.versions[value] ?? value}</option>`,
        )}
      </select>
    </${Field}>
    <${Field} name="status" label=${F.status} errors=${errors}>
      <select id="cat-f-status" value=${query.status ?? ""} onChange=${select("status")}>
        <option value="">${F.status_any}</option>
        ${withCurrent(STATUSES, query.status).map(
          (value) => html`<option value=${value} title=${value}>${L.status[value] ?? value}</option>`,
        )}
      </select>
    </${Field}>`;
}

/**
 * What the panel needs of a station product.
 *
 * @typedef {object} StationPanel
 * @property {import("../types.js").StationDataset[]} datasets - Of the product's family.
 * @property {string|null} kind - The product's station kind (`hydro`, `meteo`), else
 *   `null` (both: the kind is a field).
 * @property {"hydro"|"meteo"} family - Whose remembered year type numbers the list.
 * @property {string|null} dataset - The dataset the Timeline shows when the address
 *   names none (the product's first), else `null`.
 */

/** The fields of `GET /stations` (see the module). */
function StationFields({ query, stations, errors, onChange }) {
  const SF = L.stations.filters;
  const { datasets, kind } = stations;
  const shown = query.dataset ?? stations.dataset ?? null;
  const dataset = datasets.find((item) => item.dataset === shown) ?? null;
  // A coverage filter needs a dataset: one of the Timeline's first dataset names it too.
  const pinned = (patch) =>
    onChange(query.dataset || !stations.dataset ? patch : { dataset: shown, ...patch });
  const variables = dataset ? dataset.variables : distinctVariables(datasets);
  const meteoKinds = splitList(query.meteo_kind);
  const coverage = splitList(query.coverage);
  const minYears = splitList(query.min_complete_years);
  const select = (name) => (event) => onChange({ [name]: event.currentTarget.value || null });
  const toggled = (values, value) =>
    joinList(values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
  const yearsOf = (key) => minYears.find((item) => item.startsWith(`${key}:`))?.slice(key.length + 1) ?? "";
  const setYears = (key, value) =>
    pinned({
      min_complete_years: joinList([
        ...minYears.filter((item) => !item.startsWith(`${key}:`)),
        ...(value ? [`${key}:${value}`] : []),
      ]),
    });

  return html`<${Field} name="dataset" label=${SF.dataset} errors=${errors}>
      <select id="cat-f-dataset" value=${shown ?? ""}
        onChange=${(event) => onChange({ dataset: event.currentTarget.value || null, coverage: null, min_complete_years: null })}>
        ${stations.dataset ? null : html`<option value="">${SF.dataset_any}</option>`}
        ${withCurrent(datasets.map((item) => item.dataset), query.dataset).map((key) => {
          const item = datasets.find((candidate) => candidate.dataset === key);
          const text = item ? t(SF.dataset_option, { name: item.name ?? key, provider: item.provider }) : key;
          return html`<option value=${key} title=${key}>${text}</option>`;
        })}
      </select>
    </${Field}>
    ${kind
      ? null
      : html`<${Field} name="kind" label=${SF.kind} errors=${errors}>
          <select id="cat-f-kind" value=${query.kind ?? ""} onChange=${select("kind")}>
            <option value="">${SF.kind_any}</option>
            ${["hydro", "meteo"].map((value) => html`<option value=${value}>${SF.kinds[value]}</option>`)}
          </select>
        </${Field}>`}
    ${kind === "hydro"
      ? null
      : html`<div class="field" role="group" aria-labelledby="cat-f-meteo_kind-label">
          <span class="field-label" id="cat-f-meteo_kind-label">${SF.meteo_kind}</span>
          <div class="st-types">
            ${METEO_KINDS.map(
              (value) => html`<button type="button" class=${`chip${meteoKinds.includes(value) ? " on" : ""}`}
                aria-pressed=${meteoKinds.includes(value) ? "true" : "false"}
                onClick=${() => onChange({ meteo_kind: toggled(meteoKinds, value) })}>
                ${SF.meteo_kinds[value]}</button>`,
            )}
          </div>
          <span class="field-hint">${SF.meteo_kind_hint}</span>
        </div>`}
    <${Field} name="river_code" label=${SF.river_code} errors=${errors} hint=${SF.river_hint}>
      <${TextFilter} id="cat-f-river_code" value=${query.river_code ?? ""} placeholder=${SF.river_code_placeholder}
        mono invalid=${Boolean(errors.river_code)} onCommit=${(value) => onChange({ river_code: value || null })} />
      <label class="check-field st-check"><input type="checkbox" checked=${query.river_scope === "tributaries"}
        onChange=${(event) => onChange({ river_scope: event.currentTarget.checked ? "tributaries" : null })} />
        ${SF.river_tributaries}</label>
    </${Field}>
    <${Field} name="active" label=${SF.active} errors=${errors}>
      <select id="cat-f-active" value=${query.active ?? ""} onChange=${select("active")}>
        <option value="">${SF.active_any}</option>
        <option value="true">${SF.active_true}</option>
        <option value="false">${SF.active_false}</option>
      </select>
    </${Field}>
    <${Field} name="variable" label=${SF.variable} errors=${errors} hint=${SF.variable_hint}>
      <select id="cat-f-variable" value=${query.variable ?? ""} onChange=${select("variable")}>
        <option value="">${SF.variable_any}</option>
        ${withCurrent(variables.map((item) => item.key), query.variable).map(
          (key) => html`<option value=${key}>${key}</option>`,
        )}
      </select>
    </${Field}>
    <div class=${`field${errors.coverage || errors.min_complete_years ? " invalid" : ""}`} role="group"
      aria-labelledby="cat-f-coverage-label">
      <span class="field-label" id="cat-f-coverage-label">${SF.coverage}</span>
      ${dataset
        ? variables.map(
            (variable) => html`<div class="st-cov" key=${variable.key} role="group"
              aria-label=${t(SF.coverage_variable, { variable: variable.key })}>
              <span class="st-cov-key">${variable.key}</span>
              ${STATION_STATES.map((state) => {
                const value = `${variable.key}:${state}`;
                const on = coverage.includes(value);
                return html`<button type="button" class=${`chip${on ? " on" : ""}`} aria-pressed=${on ? "true" : "false"}
                  onClick=${() => pinned({ coverage: toggled(coverage, value) })}>
                  ${SF.states[state]}</button>`;
              })}
              <span class="st-cov-years">${SF.min_years}
                <${TextFilter} id=${`cat-f-min-${variable.key}`} label=${t(SF.min_years_label, { variable: variable.key })}
                  value=${yearsOf(variable.key)} numeric invalid=${Boolean(errors.min_complete_years)}
                  onCommit=${(value) => setYears(variable.key, value)} /></span>
            </div>`,
          )
        : html`<span class="field-hint">${SF.coverage_need_dataset}</span>`}
      ${errors.coverage || errors.min_complete_years
        ? html`<span class="field-error" role="alert">${errors.coverage ?? errors.min_complete_years}</span>`
        : null}
      ${dataset ? html`<span class="field-hint">${SF.coverage_hint}</span>` : null}
    </div>
    <${Field} name="years" label=${SF.years} errors=${errors} hint=${SF.years_hint}>
      <${TextFilter} id="cat-f-years" value=${query.years ?? ""} placeholder="1951-2025" mono
        invalid=${Boolean(errors.years)} onCommit=${(value) => onChange({ years: value || null })} />
    </${Field}>
    <${YearTypeSwitch} query=${query} family=${stations.family} onChange=${onChange} />`;
}

/**
 * „Lata: hydrologiczne / kalendarzowe” (M11 point 5): the address's
 * `year_type`, else the type the person remembers for the list's family
 * (year-type.js).
 */
function YearTypeSwitch({ query, family, onChange }) {
  const SF = L.stations.filters;
  const { value, choose, failed } = useYearType(query.year_type, family, onChange);
  return html`<div class="field" role="group" aria-labelledby="cat-f-year_type-label">
    <span class="field-label" id="cat-f-year_type-label">${SF.year_type}</span>
    <${Seg} small label=${SF.year_type} value=${value} onChange=${choose}
      options=${YEAR_TYPES.map((type) => ({ value: type, label: SF.year_types[type] }))} />
    <span class="field-hint st-year-type-note">${t(SF.year_type_hint, { family: SF.families[family] })}</span>
    ${failed ? html`<span class="field-error" role="alert">${SF.year_type_failed}</span>` : null}
  </div>`;
}

/** The variables of every dataset, once each, in their order. */
function distinctVariables(datasets) {
  const seen = new Map();
  for (const item of datasets.flatMap((dataset) => dataset.variables)) {
    if (!seen.has(item.key)) seen.set(item.key, item);
  }
  return [...seen.values()];
}

/** A comma list of the address as values. */
function splitList(text) {
  return text ? text.split(",").filter(Boolean) : [];
}

/** Values as a comma list of the address; none: no parameter. */
function joinList(values) {
  return values.length ? values.join(",") : null;
}

/** A labelled field with the API's message when it refused the value. */
function Field({ name, label, errors, hint, group, children }) {
  const error = errors[name];
  const id = `cat-f-${name}`;
  return html`<div class=${`field${error ? " invalid" : ""}`} role=${group ? "group" : null}
    aria-labelledby=${group ? `${id}-label` : null}>
    ${group
      ? html`<span class="field-label" id=${`${id}-label`}>${label}</span>`
      : html`<label for=${id}>${label}</label>`}
    ${children}
    ${error ? html`<span class="field-error" id=${`${id}-error`} role="alert">${error}</span>` : null}
    ${hint ? html`<span class="field-hint">${hint}</span>` : null}
  </div>`;
}

/**
 * A typed filter value: kept while typing, applied when the field is left or
 * Enter is pressed (the address and other renders do not reset it).
 */
function TextFilter({ id, label, value, placeholder, numeric, mono, invalid, onCommit }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const commit = () => {
    const next = text.trim();
    if (next !== value) onCommit(next);
  };
  return html`<input id=${id} type="text" class=${mono ? "mono" : null} value=${text}
    placeholder=${placeholder} aria-label=${label} aria-invalid=${invalid ? "true" : null}
    aria-describedby=${invalid ? `${id.replace(/-to$/, "")}-error` : null}
    inputmode=${numeric ? "numeric" : null} maxlength=${numeric ? 4 : null}
    spellcheck="false" autocomplete="off"
    onInput=${(event) => setText(event.currentTarget.value)} onChange=${commit}
    onKeyDown=${(event) => {
      if (event.key === "Enter") commit();
    }} />`;
}

/** Variants (segments) of the chosen product: the producer's names and paths. */
function Segments({ product }) {
  return html`<div class="cat-segments">
    <span class="field-hint">${F.product_hint}</span>
    <ul>
      ${product.segments.map(
        (item) => html`<li key=${`${item.store}/${item.segment.path}`}>
          <${Tech} value=${[["segment", item.segment.path ?? "–"], ["store", item.store]]}>
            <span class="cat-segment-label">${item.segment.label}</span>
          </${Tech}>
          <span class="faint tabular">${int(item.slots)}</span>
        </li>`,
      )}
    </ul>
  </div>`;
}

/** The area of the map (`area_id`) or a typed rectangle (`bbox`, `bbox_crs`). */
function AreaFields({ query, errors, onChange }) {
  const area = useResource(
    (signal) => (query.area_id ? getArea(query.area_id, { signal }) : Promise.resolve(null)),
    [query.area_id ?? ""],
  );
  const data = area.data && area.data.id === query.area_id ? area.data : null;
  return html`<div class="field cat-area" role="group" aria-labelledby="cat-f-area-label">
    <span class="field-label" id="cat-f-area-label">${F.area}</span>
    ${query.area_id
      ? html`<div class="area-card">
          <div class="cat-area-head">
            <b>${data?.name ?? query.area_id}</b>
            <button type="button" class="btn ghost icon-btn" title=${F.area_remove}
              aria-label=${F.area_remove} onClick=${() => onChange({ area_id: null })}>
              <${Icon} name="x" size=${14} /></button>
          </div>
          <${Tech} value=${[["area_id", query.area_id], ...(data ? [["bbox", data.bbox.join(",")]] : [])]}>
            <span class="muted">${data?.area_km2 != null ? t(F.area_km2, { area: int(data.area_km2) }) : ""}
              ${data?.countries.length ? ` · ${data.countries.join(", ")}` : ""}</span>
          </${Tech}>
          ${errors.area_id ? html`<span class="field-error" role="alert">${errors.area_id}</span>` : null}
        </div>`
      : html`<span class="field-hint">${F.area_none}</span>`}
    <div class=${`field${errors.bbox ? " invalid" : ""}`}>
      <label for="cat-f-bbox">${F.bbox}</label>
      <${TextFilter} id="cat-f-bbox" value=${query.bbox ?? ""} placeholder=${F.bbox_placeholder} mono
        invalid=${Boolean(errors.bbox)} onCommit=${(value) => onChange({ bbox: value || null })} />
      ${errors.bbox ? html`<span class="field-error" id="cat-f-bbox-error" role="alert">${errors.bbox}</span>` : null}
      <span class="field-hint">${query.area_id ? F.bbox_with_area : F.bbox_hint}</span>
    </div>
    <div class=${`field${errors.bbox_crs ? " invalid" : ""}`}>
      <label for="cat-f-bbox_crs">${F.bbox_crs}</label>
      <${TextFilter} id="cat-f-bbox_crs" value=${query.bbox_crs ?? ""} placeholder=${F.bbox_crs_placeholder}
        mono invalid=${Boolean(errors.bbox_crs)}
        onCommit=${(value) => onChange({ bbox_crs: value || null })} />
      ${errors.bbox_crs
        ? html`<span class="field-error" id="cat-f-bbox_crs-error" role="alert">${errors.bbox_crs}</span>`
        : null}
    </div>
  </div>`;
}

/** Options with the address's value too, when it is not among them. */
function withCurrent(values, current) {
  return current && !values.includes(current) ? [...values, current] : values;
}

function storeName(stores, id) {
  const store = stores.find((item) => item.store === id);
  return store ? `${store.name} (${id})` : id;
}
