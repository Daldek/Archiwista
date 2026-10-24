/**
 * The catalog's filter panel: one field per parameter of `GET /slots`
 * (docs/SPEC.md 6.6), read from and written to the address. Lists and
 * switches apply at once; typed values (years, unit, rectangle) when the
 * field is left or Enter is pressed. A value the API refuses is marked on
 * its field with the API's message.
 */

import { getArea, listProducts } from "../api.js";
import { int } from "../format.js";
import { useResource } from "../hooks.js";
import { catalog as L } from "../labels/catalog.js";
import { t } from "../labels/index.js";
import { html, Icon, Tech, useEffect, useState } from "../ui.js";

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
 * @param {Object<string, string>} props.query - The address's `/slots` parameters.
 * @param {Array<{store: string, name: string}>} props.stores - Configured stores.
 * @param {Object<string, string>} props.errors - API messages by parameter.
 * @param {string} props.indexStamp - Changes when a store's index changes.
 * @param {(patch: Object<string, string|null>) => void} props.onChange
 * @param {() => void} props.onClear - Remove every filter of the panel.
 */
export function CatalogFilters({ query, stores, errors, indexStamp, onChange, onClear }) {
  const products = useResource(
    (signal) => listProducts(query.store ? { store: query.store } : {}, { signal }),
    [query.store ?? "", indexStamp],
  );
  const items = products.data?.items.filter((item) => item.product !== null) ?? [];
  const chosen = items.find((item) => item.product === query.product);
  const countries = [...new Set(items.flatMap((item) => item.countries))].sort();
  if (query.country && !countries.includes(query.country)) countries.push(query.country);
  const select = (name) => (event) => onChange({ [name]: event.currentTarget.value || null });
  const { from, to } = splitYears(query.years);
  const active = FILTERS.some((name) => query[name]);

  return html`<div class="cat-filters">
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
    <${Field} name="country" label=${F.country} errors=${errors}>
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
    </${Field}>
    <${AreaFields} query=${query} errors=${errors} onChange=${onChange} />
    ${query.limit
      ? html`<div class="cat-limit">
          <span class="muted">${F.limit}:</span> <code>${query.limit}</code>
          <button type="button" class="btn ghost sm" onClick=${() => onChange({ limit: null })}
            aria-label=${t(F.remove, { name: F.limit })}><${Icon} name="x" size=${13} /></button>
        </div>`
      : null}
    <button type="button" class="btn sm" disabled=${!active} onClick=${onClear} title=${F.clear_title}>
      <${Icon} name="x" size=${14} />${F.clear}
    </button>
  </div>`;
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
