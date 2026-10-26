/**
 * The station card (docs/SPEC.md 6.7 and sketch 6.5 k; plan I8.5, ADR-045
 * decision 10): an overlay over the current view with its own address,
 * `station=<store>/<provider>/<code>` (codes of both providers hold no `/`),
 * over `GET /stations/{code}` with the address's `year_type`.
 *
 * The header names the station, its type, river and hydrographic code, its
 * code, provider and whether it is active, with the year-type switch of the
 * Catalog (year-type.js): a choice renumbers the labels and goes to the
 * address. Below it the location with its source, the catalog's date and
 * its uncertainty, or the catalog's reason without one, and for a water gauge
 * of IMGW-PIB „Strona stacji IMGW”, a plain link to the provider's page (the
 * card asks nothing of it). The actions: „Pokaż na mapie” for a station with
 * a position (the map of its product centred on it; the card closes) and
 * „Kopiuj ścieżkę pliku” (its series file on this computer, `paths` of the
 * card). Then the coverage of each variable of each series: its label with
 * the fill of SPEC 4.8.4 in the station's shape, its full years and its
 * longest gap (a station has no label of its own, P16); the tabs „Metadane”,
 * „Pochodzenie” (the series versions with their files and SHA-256, the
 * catalog) and „Szczegóły techniczne” (the API's answer), the chosen one in
 * the address (`station_tab`); and last the licence with the provider's
 * formula and „Kopiuj atrybucję”. A point on the map, a row of the Catalog's
 * list and a station of its Timeline open the card.
 */

import { getStation, listStationDatasets } from "../api.js";
import { useApp } from "../context.js";
import { count, day, int } from "../format.js";
import { useResource } from "../hooks.js";
import { catalog as C } from "../labels/catalog.js";
import { T, t } from "../labels/index.js";
import { station as L } from "../labels/station.js";
import {
  STATION_KINDS,
  STATION_PARAM,
  StationSymbol,
  stationShape,
  stationType,
} from "../map/stations.js";
import { navigate, readRoute, setParams } from "../router.js";
import { findView } from "../routes.js";
import {
  CopyButton,
  html,
  Icon,
  loadStylesheet,
  ProblemView,
  Seg,
  Spinner,
  Tech,
  useEffect,
  useId,
  useRef,
} from "../ui.js";
import { CopyAction, loadCardStyles, StaleNote, storeName } from "./cards.js";
import { useYearType, YEAR_TYPES } from "./year-type.js";

await Promise.all([loadCardStyles(), loadStylesheet(new URL("./station.css", import.meta.url))]);

/** Address parameter of the card's tab: the metadata without it. */
export const TAB_PARAM = "station_tab";
const TABS = ["meta", "origin", "tech"];
// The card's own parameters, gone with it.
const CARD_PARAMS = [TAB_PARAM];
/** Zoom of the map showing one station (as the Catalog's „Pokaż na mapie”). */
const STATION_ZOOM = 11;
const DEGREES = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});
const DECIMAL = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2 });

/**
 * The station card overlay (routes.js `OVERLAYS`, parameter `station`).
 *
 * @param {{route: import("../router.js").Route, value: string,
 *   onClose: () => void}} props - `value` is `<store>/<provider>/<code>`.
 */
export default function StationCard({ route, value, onClose }) {
  const titleId = useId();
  const heading = useRef(null);
  const opener = useRef(document.activeElement);
  const address = parseStation(value);
  const yearType = route.params.year_type ?? null;
  const card = useResource(
    (signal) =>
      address
        ? getStation(address.code, { ...address.lookup, year_type: yearType }, { signal })
        : Promise.resolve(null),
    [value, yearType ?? ""],
  );
  const station = card.data?.station ?? null;

  useEffect(() => heading.current?.focus(), [value]);
  useEffect(
    () => () => {
      // Closed by Esc, the button or another view: the tab goes too.
      const { params } = readRoute();
      if (!params[STATION_PARAM] && CARD_PARAMS.some((name) => params[name])) {
        setParams(Object.fromEntries(CARD_PARAMS.map((name) => [name, null])), { replace: true });
      }
      if (opener.current?.isConnected) opener.current.focus();
    },
    [],
  );

  let body;
  if (!address) body = html`<p class="hint warn">${t(L.bad_address, { value })}</p>`;
  else if (card.data) {
    body = html`<${CardBody} card=${card.data} params=${route.params} error=${card.error}
      loading=${card.loading} />`;
  } else if (card.error) body = html`<${ProblemView} problem=${card.error.problem} />`;
  else body = html`<${Spinner} />`;
  return html`<section class="drawer station-card" role="dialog" aria-modal="false"
    aria-labelledby=${titleId}>
    <header class="drawer-head">
      <div class="fc-title">
        <div class="eyebrow">${L.eyebrow}</div>
        <h2 id=${titleId} tabindex="-1" ref=${heading}>
          ${station ? (station.name ?? L.unnamed) : (address?.code ?? value)}</h2>
      </div>
      <button type="button" class="btn ghost icon-btn" onClick=${onClose} title=${L.close}
        aria-label=${L.close}><${Icon} name="x" /></button>
    </header>
    <div class="drawer-body">${body}</div>
  </section>`;
}

/**
 * Split the `station` parameter: the store, the provider and the code.
 *
 * @param {string} value - `<store>/<provider>/<code>`.
 * @returns {{code: string, lookup: {store: string, provider: string}}|null}
 */
export function parseStation(value) {
  const parts = value.split("/");
  if (parts.length !== 3 || parts.some((part) => !part)) return null;
  const [store, provider, code] = parts;
  return { code, lookup: { store, provider } };
}

/** The family whose remembered year type numbers the card: its kind, else hydro. */
function familyOf(station) {
  return station.kind === "meteo" ? "meteo" : "hydro";
}

function CardBody({ card, params, error, loading }) {
  const { station } = card;
  const names = useDatasetNames(station.store);
  const tab = TABS.includes(params[TAB_PARAM]) ? params[TAB_PARAM] : TABS[0];
  const panel = useId();
  return html`
    <${Heading} station=${station} params=${params} />
    ${error ? html`<${ProblemView} problem=${error.problem} compact />` : null}
    <${StaleNote} stores=${card.stale_stores} />
    <${Actions} card=${card} params=${params} />
    <${Coverage} station=${station} names=${names} />
    <section class="det-sec sc-details">
      <${CardTabs} tab=${tab} panel=${panel} />
      <div class="fc-panel" role="tabpanel" id=${panel} aria-labelledby=${`${panel}-${tab}`}>
        ${tab === "origin"
          ? html`<${Origin} card=${card} names=${names} />`
          : tab === "tech"
            ? html`<${Technical} card=${card} params=${params} />`
            : html`<${Metadata} station=${station} />`}
      </div>
    </section>
    <${Attribution} station=${station} />
    ${loading ? html`<${Spinner} quiet />` : null}
  `;
}

/** The names of the store's datasets (`GET /stations/datasets`), else none. */
function useDatasetNames(store) {
  const { data } = useResource((signal) => listStationDatasets({ store }, { signal }), [store]);
  return new Map((data?.items ?? []).map((item) => [item.dataset, item.name ?? item.dataset]));
}

function Heading({ station, params }) {
  const { health } = useApp();
  const river = station.river
    ? station.hydrographic_code
      ? t(L.river, { river: station.river, code: station.hydrographic_code })
      : station.river
    : null;
  const state = station.active === null ? null : station.active ? L.active : L.historical;
  return html`<div class="fc-heading sc-heading">
    <p class="sc-subline">
      <${StationSymbol} shape=${stationShape(station)} state="shape" size=${14} />
      <span>${capitalized(stationType(station))}</span>
      ${river ? html` · <span>${river}</span>` : null}
      ${" · "}<span class="mono">${station.code}</span>
    </p>
    <div class="chip-row">
      <span class="chip static">${station.provider}</span>
      ${state ? html`<span class="chip static">${state}</span>` : null}
      <span class="chip static">
        <${Tech} value=${[["store", station.store]]}>${storeName(health, station.store)}</${Tech}>
      </span>
      <${YearSwitch} asked=${params.year_type ?? null} family=${familyOf(station)} />
    </div>
    <${Location} station=${station} />
  </div>`;
}

function capitalized(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** „Lata: hydrologiczne / kalendarzowe” in the header (M11 point 5). */
function YearSwitch({ asked, family }) {
  const id = useId();
  const { value, choose, admin, failed } = useYearType(asked, family, (patch) => setParams(patch));
  const hint = admin ? t(L.year_type_hint, { family: L.families[family] }) : L.year_type_local;
  return html`<span class="sc-years" role="group" aria-labelledby=${id} title=${hint}>
    <span class="sc-years-label" id=${id}>${L.year_type}:</span>
    <${Seg} small label=${L.year_type} value=${value} onChange=${choose}
      options=${YEAR_TYPES.map((type) => ({ value: type, label: L.year_types[type] }))} />
    ${failed ? html`<span class="field-error" role="alert">${L.year_type_failed}</span>` : null}
  </span>`;
}

/** The position with its source, the catalog's date and uncertainty, or the reason. */
function Location({ station }) {
  const location = station.location;
  const page = stationPage(station);
  const link = page
    ? html`<a class="sc-page" href=${page} target="_blank" rel="noopener noreferrer"
        title=${L.station_page_title}>${L.station_page}</a>`
    : null;
  if (location.kind !== "point") {
    const reason = C.stations.reason[location.reason] ?? location.reason ?? "";
    return html`<div class="sc-location none">
      <p>${t(L.location.none, { reason })}</p>
      <p class="faint">${L.location.none_note}</p>
      ${link}
    </div>`;
  }
  const lat = DEGREES.format(location.lat);
  const lon = DEGREES.format(location.lon);
  const parts = [t(L.location.point, { lat, lon })];
  if (location.source) {
    const source = C.stations.source[location.source] ?? location.source;
    parts.push(t(L.location.source, { source }));
  }
  if (station.catalog) parts.push(t(L.location.catalog, { date: day(station.catalog) }));
  if (location.uncertainty_m !== null) {
    parts.push(t(L.location.uncertainty, { metres: int(location.uncertainty_m) }));
  }
  if (location.on_boundary) parts.push(L.location.on_boundary);
  return html`<div class="sc-location">
    <p>${parts.join(" · ")}</p>
    ${link}
  </div>`;
}

/**
 * The provider's page of a water gauge of IMGW-PIB (SPEC 6.7): a plain link,
 * no request. The address of other stations' pages is not specified.
 *
 * @param {import("../types.js").StationItem} station
 * @returns {string|null}
 */
function stationPage(station) {
  if (station.provider !== "IMGW-PIB" || station.kind !== "hydro") return null;
  return `https://hydro.imgw.pl/#/station/hydro/${encodeURIComponent(station.code)}`;
}

/** „Pokaż na mapie” (with a position) and „Kopiuj ścieżkę pliku” (with a series file). */
function Actions({ card, params }) {
  const { station } = card;
  const located = station.location.kind === "point" && findView("map");
  const shown = station.series.find((series) => card.paths[series.dataset]);
  const path = shown ? card.paths[shown.dataset] : null;
  if (!located && !path) return null;
  const showOnMap = () =>
    navigate("map", {
      product: STATION_KINDS.includes(station.kind) ? station.kind : "stations",
      store: station.store,
      dataset: params.dataset,
      color: params.color,
      year_type: params.year_type,
      center: `${station.location.lon},${station.location.lat}`,
      zoom: STATION_ZOOM,
    });
  return html`<div class="sc-actions" role="group" aria-label=${L.actions.label}>
    ${located
      ? html`<button type="button" class="btn sm" title=${L.actions.show_on_map_title}
          onClick=${showOnMap}><${Icon} name="map" size=${14} />${L.actions.show_on_map}</button>`
      : null}
    ${path ? html`<${CopyAction} text=${path.local} label=${L.actions.copy_path} />` : null}
  </div>`;
}

/** Each variable of each series: its fill and label, full years and longest gap (P16). */
function Coverage({ station, names }) {
  return html`<section class="det-sec sc-coverage" aria-labelledby="sc-coverage-title">
    <h3 class="section-title" id="sc-coverage-title">${L.coverage.title}</h3>
    ${station.series.length
      ? station.series.map(
          (series) => html`<${SeriesCoverage} key=${series.dataset} series=${series}
            name=${names.get(series.dataset) ?? series.dataset} shape=${stationShape(station)} />`,
        )
      : html`<p class="faint">${L.coverage.none}</p>`}
  </section>`;
}

function SeriesCoverage({ series, name, shape }) {
  const forms = L.units[series.time_unit] ?? L.units.day;
  const years = series.years ? `${series.years.from}–${series.years.to}` : T.common.empty;
  const title = t(L.coverage.series, {
    dataset: name,
    year_type: L.year_types[series.year_type] ?? series.year_type,
    years,
  });
  const tech = [["dataset", series.dataset]];
  return html`<div class="sc-series">
    <p class="sc-series-title"><${Tech} value=${tech}>${title}</${Tech}></p>
    <ul class="sc-vars">
      ${Object.values(series.coverage).map(
        (variable) => html`<${VariableLine} key=${variable.key} variable=${variable} shape=${shape}
          forms=${forms} />`,
      )}
    </ul>
  </div>`;
}

/**
 * A variable's line: the label of „luki” names its longest gap already, so
 * only the gap's length follows it; another label gets the gap's dates too.
 */
function VariableLine({ variable, shape, forms }) {
  const gap = variable.longest_gap;
  const { key, unit, label } = variable;
  let longest = null;
  if (gap && variable.state === "gaps") {
    longest = t(L.coverage.longest_gap_units, { units: count(gap.units, forms) });
  } else if (gap) {
    const units = count(gap.units, forms);
    longest = t(L.coverage.longest_gap, { from: day(gap.from), to: day(gap.to), units });
  }
  const title = t(L.coverage.variable_title, { variable: variable.variable, unit, label });
  return html`<li class="sc-var" title=${title}>
    <${StationSymbol} shape=${shape} state=${variable.state} size=${13} />
    <b class="sc-key mono">${key}</b>
    <span class="faint">${unit}</span>
    <span class="sc-label">${label}</span>
    <span class="faint sc-full">· ${count(variable.complete_years, L.coverage.full_years)}</span>
    ${longest ? html`<span class="faint sc-gap">· ${longest}</span>` : null}
  </li>`;
}

/**
 * The tabs of the card (ARIA tabs: arrows, Home and End move between them);
 * the chosen one lives in the address.
 */
function CardTabs({ tab, panel }) {
  const select = (name) =>
    setParams({ [TAB_PARAM]: name === TABS[0] ? null : name }, { replace: true });
  const key = (event) => {
    const index = TABS.indexOf(tab);
    const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 };
    const next = moves[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const name = TABS[(next + TABS.length) % TABS.length];
    select(name);
    event.currentTarget.querySelector(`[data-tab="${name}"]`)?.focus();
  };
  return html`<div class="fc-tabs" role="tablist" aria-label=${L.tabs.label} onKeyDown=${key}>
    ${TABS.map(
      (name) => html`<button type="button" role="tab" class="fc-tab" id=${`${panel}-${name}`}
        key=${name} data-tab=${name} aria-selected=${name === tab ? "true" : "false"}
        aria-controls=${panel} tabindex=${name === tab ? 0 : -1}
        onClick=${() => select(name)}>${L.tabs[name]}</button>`,
    )}
  </div>`;
}

/** „Metadane”: the station's catalog entry for people. */
function Metadata({ station }) {
  const M = L.meta;
  const number = (value, text) =>
    value === null ? null : t(text, { value: DECIMAL.format(value) });
  const mono = (value) => (value ? html`<span class="mono">${value}</span>` : null);
  const state = station.active === null ? null : station.active ? L.active : L.historical;
  const catalog = station.catalog
    ? html`<${Tech} value=${[["catalog_version", station.catalog_version ?? ""]]}>
        ${day(station.catalog)}</${Tech}>`
    : null;
  const rows = [
    [M.code, mono(station.code)],
    [M.provider, station.provider],
    [M.type, stationType(station)],
    [M.river, station.river],
    [M.hydrographic_code, mono(station.hydrographic_code)],
    [M.river_order, station.river_order === null ? null : int(station.river_order)],
    [M.established, station.established_year === null ? null : String(station.established_year)],
    [M.gauge_zero, number(station.gauge_zero_m, M.metres)],
    [M.river_km, number(station.river_km, M.kilometres)],
    [M.elevation, number(station.elevation_m, M.metres)],
    [M.state, state],
    [M.catalog, catalog],
  ];
  return html`<dl class="kv fc-meta">
    ${rows
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(([name, value]) => html`<dt>${name}</dt><dd>${value}</dd>`)}
  </dl>`;
}

/** „Pochodzenie”: each series version with its file, digest and index; the catalog. */
function Origin({ card, names }) {
  const { station } = card;
  return html`
    ${station.series.length
      ? station.series.map(
          (series) => html`<${SeriesOrigin} key=${series.dataset} series=${series}
            name=${names.get(series.dataset) ?? series.dataset}
            paths=${card.paths[series.dataset] ?? null} />`,
        )
      : html`<p class="faint">${L.origin.no_series}</p>`}
    <${CatalogOrigin} station=${station} />`;
}

/** A series version: its label, the station's file (here and aliased), digest, index, licence. */
function SeriesOrigin({ series, name, paths }) {
  const O = L.origin;
  const file = paths ? paths.local : series.file;
  const digest = series.sha256
    ? html`<${Tech} value=${[["sha256", series.sha256]]}>
        <span class="mono">${series.sha256.slice(0, 12)}…</span></${Tech}>`
    : T.common.empty;
  return html`<div class="fc-block sc-origin">
    <h4 class="section-title">
      <${Tech} value=${[["dataset", series.dataset]]}>${t(O.series, { dataset: name })}</${Tech}>
    </h4>
    <dl class="kv fc-meta">
      <dt>${O.version}</dt><dd><span class="mono">${series.series ?? T.common.empty}</span></dd>
      <dt>${O.file}</dt>
      <dd class="sc-file">
        <code class="path">${file}</code><${CopyButton} text=${file} label=${series.file} />
        ${(paths?.aliases ?? []).map(
          (alias) => html`<span class="sc-alias" key=${alias}>
            <code class="path">${alias}</code><${CopyButton} text=${alias} label=${alias} />
          </span>`,
        )}
      </dd>
      <dt>${O.sha256}</dt><dd>${digest}</dd>
      <dt>${O.index}</dt><dd><code class="path">${series.series_version}</code></dd>
      <dt>${O.license}</dt><dd>${series.license ?? T.common.empty}</dd>
    </dl>
  </div>`;
}

/** The catalog version the station comes from and the source of its position. */
function CatalogOrigin({ station }) {
  const O = L.origin;
  const source = station.location.source;
  return html`<div class="fc-block sc-origin">
    <h4 class="section-title">${O.catalog}</h4>
    <dl class="kv fc-meta">
      ${station.catalog
        ? html`<dt>${O.catalog}</dt><dd>${t(O.catalog_version, { label: day(station.catalog) })}
            ${station.catalog_version
              ? html` <code class="path">${station.catalog_version}</code>`
              : null}</dd>`
        : null}
      ${source
        ? html`<dt>${O.location_source}</dt>
            <dd><${Tech} value=${[["source", source]]}>
              ${C.stations.source[source] ?? source}</${Tech}></dd>`
        : null}
    </dl>
  </div>`;
}

/** „Szczegóły techniczne”: the address of the API's answer and the answer itself. */
function Technical({ card, params }) {
  const { station } = card;
  const query = new URLSearchParams({ store: station.store, provider: station.provider });
  if (params.year_type) query.set("year_type", params.year_type);
  const address = `/api/v1/stations/${encodeURIComponent(station.code)}?${query}`;
  const text = JSON.stringify(card, null, 2);
  return html`<div class="fc-block">
    <h4 class="section-title">${L.tech.api}</h4>
    <p class="fc-path-row">
      <code class="path">GET ${address}</code><${CopyButton} text=${address} label=${address} />
    </p>
    <pre class="sidecar sc-json" tabindex="0">${text}</pre>
    <${CopyAction} text=${text} label=${L.tech.copy_json} />
  </div>`;
}

/** The licence and the provider's formula of the station's series, each once. */
function Attribution({ station }) {
  const A = L.attribution;
  const seen = new Map();
  for (const series of station.series) {
    const key = `${series.license ?? ""}\n${series.attribution ?? ""}`;
    if ((series.license || series.attribution) && !seen.has(key)) seen.set(key, series);
  }
  return html`<section class="det-sec fc-block sc-attribution"
    aria-labelledby="sc-attribution-title">
    <h3 class="section-title" id="sc-attribution-title">${A.title}</h3>
    ${seen.size
      ? [...seen.entries()].map(
          ([key, series]) => html`<div class="fc-block" key=${key}>
            ${series.license
              ? html`<p class="fc-license"><b>${t(A.license, { license: series.license })}</b></p>`
              : null}
            ${series.attribution
              ? html`<p class="fc-attribution">${series.attribution}</p>
                  <${CopyAction} text=${series.attribution} label=${A.copy} />`
              : null}
          </div>`,
        )
      : html`<p class="faint">${A.none}</p>`}
  </section>`;
}
