/**
 * The comparison of stations (docs/SPEC.md 6.7, M11 point 7; plan I8.6,
 * ADR-045 decision 13): a view of `VIEWS` outside the navigation
 * (`station-compare`), opened by „Porównaj z…” of the station card and by the
 * stations chosen in the Catalog's list.
 *
 * Its address names 2 to 5 stations (`stations`, each
 * `<store>/<provider>/<code>`, comma-separated, in the order of the panels),
 * the `dataset` and `variable` compared, the `year_type` and the range
 * (`from`, `to`). It reads `GET /stations/compare` with `max_points` the
 * plots' width: one panel per station, stacked one above another (not lines
 * overlaid), each with the station's name and its line, gaps and markers as
 * the chart draws them (station-chart.js `ChartPlot`), over one time axis at
 * the bottom (`TimeAxis`). Every panel has the same range and interval, so a
 * selection, the wheel or the keys in one panel write `from` and `to` and
 * move all. A station without the series or the variable keeps its panel
 * with „brak danych”. Below the panels the facts of each station as on its
 * card (years with a value, the label with its gap share, the longest gap,
 * full years, the location's source) and the formula of each provider.
 * „Dodaj stację” finds a station with a series of the dataset by name, river
 * or code (`GET /stations` with `q` and `dataset`); it is disabled at five.
 */

import { compareStations, getStation, listStations, listStationDatasets } from "../api.js";
import { count, day, int } from "../format.js";
import { useResource, useSize } from "../hooks.js";
import { catalog as CL } from "../labels/catalog.js";
import { t } from "../labels/index.js";
import { station as L } from "../labels/station.js";
import { COMPARE_PARAM, MAX_COMPARED, stationAddress } from "../map/stations.js";
import { setParams } from "../router.js";
import {
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
  useState,
} from "../ui.js";
import { StaleNote } from "./cards.js";
import {
  ChartPlot,
  chartNote,
  MARGIN,
  MAX_POINTS,
  msOf,
  TimeAxis,
  timeTicks,
  unitText,
} from "./station-chart.js";
import { Attribution, parseStation } from "./station.js";

await loadStylesheet(new URL("./station-compare.css", import.meta.url));

const C = L.compare;
const DAY = 86_400_000;
/** Characters of a search before „Dodaj stację” asks for stations. */
const SEARCH_MIN = 2;
/** Stations „Dodaj stację” lists. */
const FOUND = 8;

/**
 * The stations of the address: each `<store>/<provider>/<code>` once, at most
 * five, in their order.
 *
 * @param {string|undefined} value - The `stations` parameter.
 * @returns {string[]}
 */
function comparedStations(value) {
  const found = [];
  for (const item of (value ?? "").split(",")) {
    if (parseStation(item) && !found.includes(item)) found.push(item);
  }
  return found.slice(0, MAX_COMPARED);
}

/**
 * The view (routes.js `VIEWS`, `station-compare`).
 *
 * @param {{route: import("../router.js").Route}} props
 */
export default function StationCompare({ route }) {
  const { params } = route;
  const stations = comparedStations(params[COMPARE_PARAM]);
  const dataset = params.dataset ?? null;
  const store = stations.length ? parseStation(stations[0]).lookup.store : null;
  const datasets = useResource(
    (signal) => (store ? listStationDatasets({ store }, { signal }) : Promise.resolve(null)),
    [store ?? ""],
  );
  const described = datasets.data?.items.find((item) => item.dataset === dataset) ?? null;
  const keys = (described?.variables ?? []).map((item) => item.key);
  const variable = params.variable ?? null;
  // A dataset without a variable in the address compares its first one.
  useEffect(() => {
    if (!variable && keys.length) setParams({ variable: keys[0] }, { replace: true });
  }, [variable, keys.join(",")]);
  const write = (next) => setParams({ [COMPARE_PARAM]: next.join(",") || null });
  const remove = (address) => write(stations.filter((item) => item !== address));
  const add = (address) => write([...stations, address]);
  const ready = stations.length >= 2 && dataset && variable;
  const name = described?.name ?? dataset;
  const lone = useLoneName(stations);
  return html`<section class="page scmp" aria-labelledby="scmp-title">
    <header class="scmp-head">
      <h1 class="view-title" id="scmp-title">${C.title}</h1>
      ${described && variable
        ? html`<p class="scmp-lead faint">${t(C.lead, {
            variable,
            dataset: name,
            year_type: L.year_types[params.year_type ?? described.year_type] ?? "",
          })}</p>`
        : null}
    </header>
    <div class="scmp-tools">
      ${keys.length > 1
        ? html`<${Seg} small label=${C.variable} value=${variable}
            onChange=${(value) => setParams({ variable: value, from: null, to: null })}
            options=${keys.map((key) => ({ value: key, label: key }))} />`
        : null}
      <${AddStation} dataset=${dataset} stations=${stations} onAdd=${add} />
    </div>
    ${!dataset || (!variable && datasets.data)
      ? html`<p class="hint warn">${C.no_dataset}</p>`
      : ready
        ? html`<${Comparison} params=${params} stations=${stations} dataset=${dataset}
            datasetName=${name} variable=${variable} onRemove=${remove} />`
        : stations.length >= 2
          ? html`<${Spinner} />`
          : html`<${Chosen} stations=${stations} names=${lone} onRemove=${remove} />
              <p class="hint">${C.fewer}</p>`}
  </section>`;
}

/**
 * The name of the only station of the address, from its card (the comparison
 * gives the names of two or more).
 *
 * @param {string[]} stations
 * @returns {Map<string, string>} Its address to its name; empty until read.
 */
function useLoneName(stations) {
  const lone = stations.length === 1 ? parseStation(stations[0]) : null;
  const card = useResource(
    (signal) => (lone ? getStation(lone.code, lone.lookup, { signal }) : Promise.resolve(null)),
    [lone ? stations[0] : ""],
  );
  const station = lone ? (card.data?.station ?? null) : null;
  if (!station || stationAddress(station) !== stations[0]) return new Map();
  return new Map([[stations[0], station.name ?? station.code]]);
}

/** The stations of the address as chips with „×”, by name once it is known. */
function Chosen({ stations, names, onRemove }) {
  return html`<ul class="scmp-chips" aria-label=${C.stations}>
    ${stations.map((address) => {
      const name = names.get(address) ?? parseStation(address).code;
      return html`<li class="scmp-chip" key=${address}>
        <span class="ell" title=${address}>${name}</span>
        <button type="button" class="btn ghost icon-btn sm" title=${t(C.remove, { name })}
          aria-label=${t(C.remove, { name })} onClick=${() => onRemove(address)}>
          <${Icon} name="x" size=${13} /></button>
      </li>`;
    })}
  </ul>`;
}

/** „Dodaj stację”: a station with a series of the dataset, by name, river or code. */
function AddStation({ dataset, stations, onAdd }) {
  const id = useId();
  const [text, setText] = useState("");
  const full = stations.length >= MAX_COMPARED;
  const q = text.trim();
  const asked = !full && dataset && q.length >= SEARCH_MIN;
  const found = useResource(
    (signal) => (asked ? listStations({ q, dataset, limit: FOUND }, { signal }) : Promise.resolve(null)),
    [asked ? q : "", dataset ?? ""],
  );
  const items = (found.data?.items ?? []).filter((item) => !stations.includes(stationAddress(item)));
  return html`<div class="scmp-add">
    <label class="scmp-add-label" for=${id}><${Icon} name="plus" size=${13} />${C.add}</label>
    <input id=${id} type="search" value=${text} disabled=${full}
      placeholder=${C.add_placeholder} title=${full ? C.add_full : C.add_title} autocomplete="off"
      onInput=${(event) => setText(event.currentTarget.value)} />
    ${full ? html`<span class="faint scmp-full">${C.add_full}</span>` : null}
    ${asked && found.data
      ? html`<ul class="scmp-found" aria-label=${C.add}>
          ${items.map(
            (item) => html`<li key=${stationAddress(item)}>
              <button type="button" class="btn ghost sm"
                onClick=${() => {
                  setText("");
                  onAdd(stationAddress(item));
                }}>
                <b>${item.name ?? item.code}</b>
                <span class="faint">${item.code} · ${item.provider}${item.river ? ` · ${item.river}` : ""}</span>
              </button>
            </li>`,
          )}
          ${items.length ? null : html`<li class="faint">${C.add_none}</li>`}
        </ul>`
      : null}
  </div>`;
}

/** The comparison of the address: the panels, the time axis, the facts, the formulas. */
function Comparison({ params, stations, dataset, datasetName, variable, onRemove }) {
  const [box, setBox] = useState(null);
  const { width } = useSize(box);
  const plot = Math.floor(width - MARGIN.left - MARGIN.right);
  const maxPoints = Math.min(MAX_POINTS, plot);
  const from = params.from ?? null;
  const to = params.to ?? null;
  const yearType = params.year_type ?? null;
  const query = {
    station: stations,
    dataset,
    variable,
    from,
    to,
    year_type: yearType,
    max_points: maxPoints,
  };
  const key = [stations.join(","), dataset, variable, yearType ?? ""].join("|");
  const answer = useResource(
    (signal) => (maxPoints > 0 ? compareStations(query, { signal }) : Promise.resolve(null)),
    [key, from ?? "", to ?? "", maxPoints],
  );
  const data = answer.data ?? null;
  // The comparison as the API gave it without a range: the bound of a zoom out.
  // While another query loads, the last answer stays: it is not this one's.
  const whole = useRef(null);
  const current =
    data !== null &&
    data.dataset === dataset &&
    data.variable === variable &&
    data.stations.map(stationAddress).join(",") === stations.join(",") &&
    (!yearType || data.year_type === yearType);
  if (current && data.from && !from && !to) {
    whole.current = { key, start: msOf(data.from), end: msOf(data.to) + DAY };
  }
  const extent = extentOf(data, whole.current?.key === key ? whole.current : null);
  const zoomed = Boolean(from || to);
  const write = (range, { replace = false } = {}) =>
    setParams(range ? { from: range.from, to: range.to } : { from: null, to: null }, { replace });
  const api = `/api/v1/stations/compare?${searchOf(query)}`;
  const names = new Map((data?.stations ?? []).map((item) => [stationAddress(item), item.name ?? item.code]));
  return html`
    <${Chosen} stations=${stations} names=${names} onRemove=${onRemove} />
    ${data ? html`<${StaleNote} stores=${data.stale_stores} />` : null}
    <div class="scmp-range">
      ${data?.from ? html`<span class="faint">${t(L.chart.range, { from: day(data.from), to: day(data.to) })}</span>` : null}
      ${zoomed
        ? html`<button type="button" class="btn ghost sm" title=${L.chart.whole_title} onClick=${() => write(null)}>
            <${Icon} name="rotate" size=${13} />${L.chart.whole}</button>`
        : null}
    </div>
    <div class="scmp-frame" ref=${setBox}>
      ${answer.error && !answer.loading ? html`<${ProblemView} problem=${answer.error.problem} />` : null}
      ${data && width > 0
        ? html`<${Panels} answer=${data} datasetName=${datasetName} width=${width} extent=${extent}
            onRange=${write} loading=${answer.loading} whole=${!zoomed} />`
        : answer.error
          ? null
          : html`<div class="sch-wait"><${Spinner} /></div>`}
    </div>
    ${data ? html`<${Facts} answer=${data} />` : null}
    ${data ? html`<${Attribution} items=${data.stations} />` : null}
    <p class="sch-api faint"><${Tech} value=${[[C.api, api]]}>${C.api}</${Tech}></p>
  `;
}

/**
 * The days a zoom can reach: the comparison as the API gave it without a
 * range, widened to the first and last value of every station.
 *
 * @returns {{start: number, end: number}|null} Times, the end excluded.
 */
function extentOf(answer, whole) {
  let start = whole?.start ?? Infinity;
  let end = whole?.end ?? -Infinity;
  for (const item of answer?.stations ?? []) {
    const { first, last } = item.coverage ?? {};
    if (first) start = Math.min(start, msOf(first));
    if (last) end = Math.max(end, msOf(last) + DAY);
  }
  return start < end ? { start, end } : null;
}

/**
 * The panels of the stations, one above another, and their one time axis.
 *
 * @param {{answer: import("../types.js").StationComparison, datasetName: string,
 *   width: number, extent: {start: number, end: number}|null,
 *   onRange: Function, loading: boolean, whole: boolean}} props
 */
function Panels({ answer, datasetName, width, extent, onRange, loading, whole }) {
  const summary = useId();
  if (!answer.from) return html`<p class="faint">${C.empty}</p>`;
  const domain = { start: msOf(answer.from), end: msOf(answer.to) + DAY };
  const ticks = timeTicks(domain.start, domain.end, width - MARGIN.left - MARGIN.right);
  const charts = answer.stations.map((item) => item.chart).filter(Boolean);
  const markers = charts.flatMap((chart) => chart.markers);
  return html`<figure class=${`scmp-figure${loading ? " busy" : ""}`}>
    <div class="scmp-panels">
      ${answer.stations.map((item) => {
        const name = item.name ?? item.code;
        const title = `${name} · ${item.code}`;
        const missing = item.series === null ? C.no_series : C.no_variable;
        return html`<div class=${`scmp-panel${item.chart ? "" : " missing"}`} key=${stationAddress(item)}
          data-station=${stationAddress(item)}>
          ${item.chart
            ? html`<${ChartPlot} lines=${[{ variable: item.chart, color: 0 }]} timeUnit=${answer.time_unit}
                interval=${answer.interval} domain=${domain} width=${width} ticks=${ticks}
                extent=${extent} onRange=${onRange} title=${title} describedBy=${summary}
                label=${t(C.panel_label, { name, variable: `${answer.variable} (${unitText(item.chart.unit)})`,
                  from: day(answer.from), to: day(answer.to) })} />`
            : html`<p class="scmp-missing"><b>${title}</b> <span class="faint">${t(missing, {
                variable: answer.variable,
                dataset: datasetName,
              })}</span></p>`}
        </div>`;
      })}
    </div>
    <${TimeAxis} ticks=${ticks} domain=${domain} width=${width} right=${MARGIN.right} />
    <figcaption class="sch-caption">
      <p class="sch-note">${chartNote(answer, whole)}</p>
      <p class="sch-legend faint">
        ${charts.some((chart) => chart.gaps.length) ? html`<span>${L.chart.gap_note}</span>` : null}
        <span>${L.chart.unknown_note}</span>
        ${markers.some((marker) => marker.kind !== "accumulated") ? html`<span>${L.chart.extremes_note}</span>` : null}
        ${markers.some((marker) => marker.kind === "accumulated") ? html`<span>${L.chart.accumulated_note}</span>` : null}
      </p>
      <p class="sch-summary" id=${summary}>${t(L.chart.summary_range, {
        from: day(answer.from),
        to: day(answer.to),
        units: count(answer.units, L.units[answer.time_unit] ?? L.units.day),
      })}</p>
      <p class="sch-keys faint">${C.keys}</p>
    </figcaption>
    ${loading ? html`<span class="sch-loading"><${Spinner} quiet /></span>` : null}
  </figure>`;
}

/** The facts of each station as on its card; „brak danych” without the variable. */
function Facts({ answer }) {
  const forms = L.units[answer.time_unit] ?? L.units.day;
  return html`<section class="det-sec scmp-facts" aria-labelledby="scmp-facts-title">
    <h2 class="section-title" id="scmp-facts-title">${C.facts}</h2>
    <div class="scmp-table-wrap">
      <table class="scmp-table">
        <thead>
          <tr>
            <th scope="col">${C.station}</th>
            <th scope="col">${C.years}</th>
            <th scope="col">${C.label}</th>
            <th scope="col">${C.longest}</th>
            <th scope="col">${C.full}</th>
            <th scope="col">${C.location}</th>
          </tr>
        </thead>
        <tbody>
          ${answer.stations.map((item) => {
            const coverage = item.coverage;
            const valued = coverage?.valued ?? null;
            const gap = coverage?.longest_gap ?? null;
            const years = valued ? spanText(valued.from, valued.to, String) : "–";
            const longest = gap ? `${spanText(gap.from, gap.to, day)} (${count(gap.units, forms)})` : "–";
            return html`<tr key=${stationAddress(item)} data-station=${stationAddress(item)}>
              <th scope="row"><span class="scmp-name">${item.name ?? item.code}</span>
                <span class="faint mono"> ${item.code} · ${item.provider}</span></th>
              ${coverage
                ? html`<td class="tabular" data-fact="years">${years}</td>
                    <td data-fact="label">${coverage.label}</td>
                    <td class="tabular" data-fact="longest">${longest}</td>
                    <td class="tabular" data-fact="full">${int(coverage.complete_years)}</td>`
                : html`<td colspan="4" class="faint" data-fact="none">${C.none}</td>`}
              <td data-fact="location" data-value=${item.location.source ?? item.location.reason ?? ""}>
                ${locationText(item.location)}</td>
            </tr>`;
          })}
        </tbody>
      </table>
    </div>
  </section>`;
}

/** `first–last` as `format` writes each, one alone when they are the same. */
function spanText(first, last, format) {
  return first === last ? format(first) : `${format(first)}–${format(last)}`;
}

/** A station's location: its source, or the catalog's reason without a position. */
function locationText(location) {
  const S = CL.stations;
  if (location.kind === "point") {
    return t(C.located, { source: S.source[location.source] ?? location.source ?? "–" });
  }
  return t(C.unlocated, { reason: S.reason[location.reason] ?? location.reason ?? "–" });
}

/** The query as the API's search string (a repeated `station`). */
function searchOf(query) {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== null && item !== undefined && item !== "") search.append(name, String(item));
    }
  }
  return search.toString();
}
