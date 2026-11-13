/**
 * The chart of a station's series: the tab „Wykres” of the station card
 * (docs/SPEC.md 6.7 „Wykres” and sketch 6.5 k; plan I8.5, ADR-045 decision
 * 11, A-ADR-051), an SVG drawn by this module (no chart library: the
 * interface has no build step, A-ADR-028).
 *
 * It draws one of the charts the card names (`charts` of `GET
 * /stations/{code}`: the address's `chart_dataset`, else its `dataset`, else
 * the first: a series of days, else of months, else the annual chart of the
 * half-year characteristics) from `GET /stations/{code}/series` for one
 * variable or two (`chart_variable`, `H` or `H,Q`; by default the address's
 * „Kolor punktów” `color`, else the chart's first), in the address's
 * `year_type` as the card, with `max_points` the plot's width in pixels (at
 * most 2,000). Without `from` and `to` it shows the variables' known span,
 * the whole period their labels count: one of more units than the plot has
 * pixels comes as the least, mean and greatest value of intervals, drawn as
 * a band with the mean line and the note „wykres uproszczony: min./śr./maks.
 * z N dni”; a range of at most as many units as pixels comes as each unit's
 * value. A monthly series is drawn per variable: the monthly mean as the line
 * and the band from the monthly minimum to the maximum, as IMGW-PIB published
 * them. The annual chart („Roczne (z charakterystyk półrocznych)”) draws per
 * hydrological year the maximum and the minimum Archiwista found in the
 * half-year characteristics, each a dot on its line, hollow for an incomplete
 * year (one half without a value), with the dates, the half and the
 * occurrences in the tooltip; it numbers hydrological years whatever the
 * card's year type, and the card says so beside the switch. A drag
 * selection, the wheel and the keys `+`, `-` and the arrows change `from`
 * and `to` in the address; `Home` and „Cały okres” remove them.
 *
 * A point without a value breaks the line (a new subpath, never a line across
 * it), and so does a gap between two points; each gap (`gaps`, the gaps the
 * variable's label counts: ADR-045 erratum 1) is a grey band over its days,
 * also one shorter than an interval. A unit without a value outside them is
 * no gap of the label (not known, or outside its years y1–y2): no band. Extremes
 * the provider published are dots with their dates in the tooltip, an
 * accumulated sum a diamond (`markers`). A second variable of another unit
 * gets the right axis. A line below sums the range, the points and the gaps.
 * Right under the chart stand the lines the providers' terms require with
 * the chart's data (provider-lines.js), of a monthly and an annual chart too.
 * The comparison of stations (views/station-compare.js) draws its panels with
 * `ChartPlot` and `TimeAxis` of this module.
 */

import { entries } from "../../nogat/nogat-app-menu.js";
import { copyHandoff, downloadHandoff, TEXTS as HANDOFF } from "../../nogat/nogat-handoff.js";
import { getStationHandoff, getStationSeries } from "../api.js";
import { useApp } from "../context.js";
import { count, day } from "../format.js";
import { useResource, useSize } from "../hooks.js";
import { t } from "../labels/index.js";
import { station as L } from "../labels/station.js";
import { ProviderLines } from "../provider-lines.js";
import { setParams } from "../router.js";
import { html, Icon, ProblemView, Seg, Spinner, Tech, useId, useRef, useState } from "../ui.js";

const C = L.chart;
/** Address parameters of the chart: its range, its series and its variables. */
export const CHART_PARAMS = ["from", "to", "chart_dataset", "chart_variable"];
/** The most points of a variable the API gives (SPEC 9.2). */
export const MAX_POINTS = 2000;
const DAY = 86_400_000;
/** Height of the plot, px; the axes' labels lie outside it. */
export const PLOT_HEIGHT = 180;
/** Space around the plot, px: the left axis, the right one (a second unit), else a rim. */
export const MARGIN = { top: 24, bottom: 24, left: 56, right: 16, axis: 56 };
/** Height of the time axis under a plot, px. */
export const AXIS_HEIGHT = 22;
/** The fewest days a zoom shows. */
const MIN_DAYS = 3;
/** The GUI a station's series is handed to (A-ADR-052), by its registry name. */
const HANDOFF_TARGET = "hydrolog";
/** „Do Hydrologa” before and between its actions. */
const HANDOFF_IDLE = { busy: false, note: null, byHand: false, problem: null };
/** A press moved less than this many px is a click, not a selection. */
const DRAG_PX = 4;
/** What a step of the keys and of the wheel does to the length of the range. */
const ZOOM = { in: 0.5, out: 2, wheel: 1.25, pan: 0.2 };
/** Steps of the time axis, finest first, and the px a label of each kind needs. */
const TICK_STEPS = [
  ["day", 1],
  ["day", 2],
  ["day", 5],
  ["day", 10],
  ["day", 15],
  ["month", 1],
  ["month", 2],
  ["month", 3],
  ["month", 6],
  ["year", 1],
  ["year", 2],
  ["year", 5],
  ["year", 10],
  ["year", 20],
  ["year", 50],
  ["year", 100],
];
const TICK_DAYS = { day: 1, month: 30.44, year: 365.25 };
const TICK_PX = { day: 92, month: 70, year: 46 };
/** Width of a character of an axis label, px (11 px digits). */
const CHAR_PX = 6.4;
/** Units as people write them. */
const UNITS = { "m3/s": "m³/s", degC: "°C" };

/**
 * The time at the start of a day `YYYY-MM-DD` (UTC), ms.
 *
 * @param {string} iso
 * @returns {number}
 */
export function msOf(iso) {
  const [year, month, date] = iso.split("-").map(Number);
  return Date.UTC(year, month - 1, date);
}

/**
 * The day `YYYY-MM-DD` of a time (UTC).
 *
 * @param {number} ms
 * @returns {string}
 */
export function isoOf(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

/**
 * A unit as people write it: `m³/s`, `°C`.
 *
 * @param {string} unit - As the API gives it (`m3/s`, `degC`).
 * @returns {string}
 */
export function unitText(unit) {
  return UNITS[unit] ?? unit;
}

/**
 * The chart the address chooses among the card's: its `chart_dataset`, else
 * its `dataset`, else the first (days, then months, then annual).
 *
 * @param {import("../types.js").StationChartChoice[]} charts - Of the card.
 * @param {Object<string, string>} params
 * @returns {import("../types.js").StationChartChoice|null}
 */
export function chosenChart(charts, params) {
  return (
    charts.find((item) => item.dataset === params.chart_dataset) ??
    charts.find((item) => item.dataset === params.dataset) ??
    charts[0] ??
    null
  );
}

/**
 * The tab „Wykres” of the station card: the series and variables, the chart
 * of the address's range and the line summing it.
 *
 * @param {{station: import("../types.js").StationItem,
 *   charts: import("../types.js").StationChartChoice[], params: Object<string, string>,
 *   names: Map<string, string>, actions?: ((shown: {dataset: string, keys: string[]}) => *)|null}} props
 *   - `charts`: those of the card; `names`: the datasets' names; `actions`: more
 *   buttons of its toolbar for the series and variables it shows („Porównaj z…”),
 *   of a daily series only.
 */
export function StationChartTab({ station, charts, params, names, actions = null }) {
  const chosen = chosenChart(charts, params);
  if (!chosen) return html`<p class="faint">${C.none}</p>`;
  return html`<${SeriesChart} key=${chosen.dataset} station=${station} charts=${charts}
    chosen=${chosen} params=${params} names=${names} actions=${actions} />`;
}

/**
 * The chart's variables: those of the address the chart has (one or two),
 * else its „Kolor punktów”, else the chart's first.
 *
 * @param {import("../types.js").StationChartChoice} choice
 * @param {Object<string, string>} params
 * @returns {string[]}
 */
export function chartKeys(choice, params) {
  const keys = choice.variables.map((item) => item.key);
  const asked = [...new Set((params.chart_variable ?? "").split(","))].filter((key) => keys.includes(key));
  if (asked.length) return asked.slice(0, 2);
  return [keys.includes(params.color) ? params.color : keys[0]];
}

function SeriesChart({ station, charts, chosen, params, names, actions }) {
  const keys = chartKeys(chosen, params);
  const [box, setBox] = useState(null);
  const { width } = useSize(box);
  const annual = chosen.resolution === "annual";
  const units = keys.map((key) => variableOf(chosen, key).unit);
  const right = units.length > 1 && units[0] !== units[1] ? MARGIN.axis : MARGIN.right;
  const plot = Math.floor(width - MARGIN.left - right);
  const maxPoints = Math.min(MAX_POINTS, plot);
  const from = params.from ?? null;
  const to = params.to ?? null;
  // An annual chart numbers hydrological years whatever the card's switch says.
  const yearType = annual ? null : (params.year_type ?? null);
  const query = {
    store: station.store,
    provider: station.provider,
    dataset: chosen.dataset,
    resolution: annual ? "annual" : null,
    variable: keys,
    from,
    to,
    year_type: yearType,
    max_points: maxPoints,
  };
  const chart = useResource(
    (signal) => (maxPoints > 0 ? getStationSeries(station.code, query, { signal }) : Promise.resolve(null)),
    [station.store, station.provider, station.code, chosen.dataset, keys.join(","), from ?? "", to ?? "", yearType ?? "", maxPoints],
  );
  // The whole series as the API gave it without a range: the bound of a zoom out.
  const whole = useRef(null);
  const data = chart.data ?? null;
  if (data && data.from && !from && !to && data.variables.map((item) => item.key).join(",") === keys.join(",")) {
    whole.current = { dataset: data.dataset, start: msOf(data.from), end: msOf(data.to) + DAY };
  }
  const extent = extentOf(chosen, keys, whole.current?.dataset === chosen.dataset ? whole.current : null);
  const zoomed = Boolean(from || to);
  const write = (range, { replace = false } = {}) =>
    setParams(range ? { from: range.from, to: range.to } : { from: null, to: null }, { replace });
  const chooseKeys = (next) => setParams({ chart_variable: next.join(","), from: null, to: null });
  const api = `/api/v1/stations/${encodeURIComponent(station.code)}/series?${seriesSearch(query)}`;
  return html`<div class="sch">
    <div class="sch-tools">
      ${charts.length > 1
        ? html`<${Seg} small label=${C.series} value=${chosen.dataset}
            onChange=${(value) => setParams({ chart_dataset: value, chart_variable: null, from: null, to: null })}
            options=${charts.map((item) => ({
              value: item.dataset,
              label: chartName(item, charts, names),
            }))} />`
        : null}
      <${Seg} small label=${C.variable} value=${keys[0]}
        onChange=${(value) => chooseKeys(keys[1] && keys[1] !== value ? [value, keys[1]] : [value])}
        options=${chosen.variables.map((item) => ({ value: item.key, label: item.key }))} />
      <${SecondVariable} choice=${chosen} keys=${keys} onChange=${chooseKeys} />
      <span class="sch-spacer"></span>
      ${actions && chosen.time_unit === "day" ? actions({ dataset: chosen.dataset, keys }) : null}
    </div>
    <${HandoffPanel} station=${station} charts=${charts} chosen=${chosen} variable=${keys[0]}
      names=${names} from=${from} to=${to} />
    <div class="sch-range">
      ${data?.from
        ? html`<span class="faint">${t(C.range, { from: day(data.from), to: day(data.to) })}</span>`
        : null}
      ${zoomed
        ? html`<button type="button" class="btn ghost sm" title=${C.whole_title} onClick=${() => write(null)}>
            <${Icon} name="rotate" size=${13} />${C.whole}</button>`
        : null}
    </div>
    <div class="sch-frame" ref=${setBox}>
      ${chart.error && !chart.loading ? html`<${ProblemView} problem=${chart.error.problem} compact />` : null}
      ${data && width > 0
        ? html`<${ChartFigure} chart=${data} width=${width} extent=${extent} onRange=${write}
            loading=${chart.loading} whole=${!zoomed} />`
        : chart.error
          ? null
          : html`<div class="sch-wait"><${Spinner} /></div>`}
    </div>
    <${ProviderLines} answer=${data} />
    <p class="sch-api faint"><${Tech} value=${[[C.api, api]]}>${C.api}</${Tech}></p>
  </div>`;
}

/**
 * The kinds of data a station hands to Hydrolog (A-ADR-052): the daily values of each
 * series of days and the annual maxima of the annual chart, each with its variables.
 *
 * @param {import("../types.js").StationChartChoice[]} charts - The card's charts.
 * @returns {{key: string, chart: import("../types.js").StationChartChoice,
 *   annual: boolean}[]}
 */
export function handoffKinds(charts) {
  return charts
    .filter((chart) => chart.time_unit === "day" || chart.resolution === "annual")
    .map((chart) => ({
      key: `${chart.resolution}:${chart.dataset}`,
      chart,
      annual: chart.resolution === "annual",
    }));
}

/**
 * „Do Hydrologa” (A-ADR-052, A-ADR-054): what Hydrolog's „Statystyka przepływów” gets,
 * chosen here — the daily values of a series of days or the annual maxima of complete
 * hydrological years, and the variable — then „Kopiuj do Hydrologa” or „Plik przekazania”,
 * written by Nogat's kit (`nogat-handoff.js`, DEV-15.5): the file `<subject>.handoff.json`
 * in 2-space JSON with a final newline; a copy goes to the clipboard, or where the browser
 * has no Clipboard API (a plain-HTTP address on the network) or refuses it, into a field
 * below with its text selected for Ctrl+C. It starts at the chart shown and its first
 * variable; the chart's range goes with its own kind only. What happened shows beside
 * them, with the years an annual hand-off leaves out and „Otwórz Hydrologa” when the
 * deployment's GUIs (`session.gui`) give Hydrolog's address.
 *
 * @param {{station: import("../types.js").StationItem,
 *   charts: import("../types.js").StationChartChoice[],
 *   chosen: import("../types.js").StationChartChoice, variable: string,
 *   names: Map<string, string>, from: string|null, to: string|null}} props - `names`: the
 *   datasets' names, which tell two series of days apart.
 */
function HandoffPanel({ station, charts, chosen, variable, names, from, to }) {
  const H = C.handoff;
  const id = useId();
  const field = useRef(null);
  const gui = useApp()?.session.gui;
  const kinds = handoffKinds(charts);
  const [picked, setPicked] = useState({ kind: null, variable: null });
  const [state, setState] = useState(HANDOFF_IDLE);
  if (!kinds.length) return null;
  const shown = `${chosen.resolution}:${chosen.dataset}`;
  const kind =
    kinds.find((item) => item.key === picked.kind) ??
    kinds.find((item) => item.key === shown) ??
    kinds[0];
  const keys = kind.chart.variables.map((item) => item.key);
  const key = [picked.variable, variable].find((item) => keys.includes(item)) ?? keys[0];
  const unit = kind.chart.variables.find((item) => item.key === key)?.unit;
  const ranged = kind.key === shown;
  const what = kind.annual ? H.what_annual : H.what_daily;
  const target = entries(gui).find(([name]) => name === HANDOFF_TARGET)?.[1];
  const choose = (patch) => {
    setPicked({ ...picked, ...patch });
    setState(HANDOFF_IDLE);
  };
  const act = async (way) => {
    setState({ ...HANDOFF_IDLE, busy: true });
    try {
      const doc = await getStationHandoff(station.code, {
        store: station.store,
        provider: station.provider,
        dataset: kind.chart.dataset,
        resolution: kind.annual ? "annual" : null,
        variable: key,
        from: ranged ? from : null,
        to: ranged ? to : null,
      });
      let note;
      let byHand = false;
      if (way === "copy") {
        byHand = (await copyHandoff(doc, field.current)) === "field";
        note = byHand ? HANDOFF.copyByHand : HANDOFF.copied;
      } else {
        note = HANDOFF.saved(downloadHandoff(doc));
      }
      const left = doc.provenance?.series?.left_out ?? [];
      if (left.length) note = `${note} · ${t(H.left_out, { years: left.join(", ") })}`;
      setState({ ...HANDOFF_IDLE, note, byHand });
    } catch (error) {
      if (!error.problem) throw error;
      setState({ ...HANDOFF_IDLE, problem: error.problem });
    }
  };
  const steps = {
    load: HANDOFF.loadFrom("archiwista"),
    paste: HANDOFF.paste,
    open_file: HANDOFF.openFile,
  };
  return html`<div class="sch-handoff" role="group" aria-label=${H.title}>
    <span class="sch-handoff-title">${H.title}</span>
    <label class="sch-second" for=${`${id}-kind`}>
      <span class="sch-second-label">${H.kind}</span>
      <select id=${`${id}-kind`} value=${kind.key}
        onChange=${(event) => choose({ kind: event.currentTarget.value })}>
        ${kinds.map((item) => {
          const daily = kinds.filter((other) => !other.annual).length > 1
            ? `${H.kind_daily} · ${names.get(item.chart.dataset) ?? item.chart.dataset}`
            : H.kind_daily;
          return html`<option value=${item.key} key=${item.key}>
            ${item.annual ? H.kind_annual : daily}</option>`;
        })}
      </select>
    </label>
    <label class="sch-second" for=${`${id}-variable`}>
      <span class="sch-second-label">${H.variable}</span>
      <select id=${`${id}-variable`} value=${key}
        onChange=${(event) => choose({ variable: event.currentTarget.value })}>
        ${kind.chart.variables.map(
          (item) => html`<option value=${item.key} key=${item.key}>
            ${`${item.key} (${unitText(item.unit)})`}</option>`,
        )}
      </select>
    </label>
    <button type="button" class="btn ghost sm" disabled=${state.busy}
      title=${t(H.copy_title, { what, variable: key, ...steps })} onClick=${() => act("copy")}>
      <${Icon} name="copy" size=${13} />${HANDOFF.copyTo(HANDOFF_TARGET)}</button>
    <button type="button" class="btn ghost sm" disabled=${state.busy}
      title=${t(H.file_title, { what, variable: key, ...steps })} onClick=${() => act("file")}>
      <${Icon} name="download" size=${13} />${HANDOFF.file}</button>
    <span class="faint sch-handoff-what">
      ${t(H.summary, { what, variable: key, unit: unitText(unit) })}
      ${ranged && (from || to) ? H.range_shown : ""}</span>
    ${state.note
      ? html`<span class="faint sch-handoff-note" role="status">${state.note}${target
          ? html` · <a href=${target} target=${`nogat-${HANDOFF_TARGET}`}>
              ${HANDOFF.open(HANDOFF_TARGET)}</a>`
          : null}</span>`
      : null}
    <textarea ref=${field} class="sch-handoff-field mono" hidden=${!state.byHand} readOnly
      rows="6" aria-label=${H.field}></textarea>
    ${state.problem ? html`<${ProblemView} problem=${state.problem} compact />` : null}
  </div>`;
}

/** A variable of a chart choice by its key. */
function variableOf(choice, key) {
  return choice.variables.find((item) => item.key === key);
}

/** „Druga zmienna”: none, or another variable of the chart (its unit's axis). */
function SecondVariable({ choice, keys, onChange }) {
  const id = useId();
  const others = choice.variables.filter((item) => item.key !== keys[0]);
  if (!others.length) return null;
  return html`<label class="sch-second" for=${id} title=${C.second_title}>
    <span class="sch-second-label">${C.second}</span>
    <select id=${id} value=${keys[1] ?? ""}
      onChange=${(event) => onChange(event.currentTarget.value ? [keys[0], event.currentTarget.value] : [keys[0]])}>
      <option value="">${C.second_none}</option>
      ${others.map((item) => {
        const text = `${item.key} (${unitText(item.unit)})`;
        return html`<option value=${item.key} key=${item.key}>${text}</option>`;
      })}
    </select>
  </label>`;
}

/**
 * A chart's chip: „Roczne (z charakterystyk półrocznych)” for the annual one,
 * else its time unit when no other series has it, else its dataset's name.
 */
function chartName(choice, all, names) {
  if (choice.resolution === "annual") return C.series_annual;
  const shared = all.filter((item) => item.time_unit === choice.time_unit).length > 1;
  if (shared) return names.get(choice.dataset) ?? choice.dataset;
  return C.series_units[choice.time_unit] ?? choice.dataset;
}

/** The query of the chart as the API's search string (repeatable `variable`). */
function seriesSearch(query) {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== null && item !== undefined && item !== "") search.append(name, String(item));
    }
  }
  return search.toString();
}

/**
 * The days a zoom can reach: the whole series as the API gave it without a
 * range, else from the first to the last day with a value of the variables.
 *
 * @returns {{start: number, end: number}|null} Times, the end excluded.
 */
function extentOf(choice, keys, whole) {
  let start = whole?.start ?? Infinity;
  let end = whole?.end ?? -Infinity;
  for (const key of keys) {
    const variable = variableOf(choice, key);
    if (variable?.first) start = Math.min(start, msOf(variable.first));
    if (variable?.last) end = Math.max(end, msOf(variable.last) + DAY);
  }
  return start < end ? { start, end } : null;
}

/**
 * The chart of an answer: the plot with its time axis, the note of a
 * simplified chart, the legend of what it shows and the line summing it.
 */
function ChartFigure({ chart, width, extent, onRange, loading, whole }) {
  const summary = useId();
  if (!chart.from) return html`<p class="faint">${C.empty}</p>`;
  const annual = chart.resolution === "annual";
  const domain = { start: msOf(chart.from), end: msOf(chart.to) + DAY };
  const lines = chart.variables.map((variable, index) => ({ variable, color: index }));
  const axes = axesOf(lines);
  const right = axes.length > 1 ? MARGIN.axis : MARGIN.right;
  const plot = width - MARGIN.left - right;
  const ticks = (annual ? yearTicks : timeTicks)(domain.start, domain.end, plot);
  const markers = chart.variables.flatMap((variable) => variable.markers);
  const gaps = chart.variables.some((variable) => variable.gaps.length);
  const keys = chart.variables.map((variable) => variable.key).join(", ");
  return html`<figure class=${`sch-figure${loading ? " busy" : ""}`}>
    <${ChartPlot} lines=${lines} timeUnit=${chart.time_unit} interval=${chart.interval}
      annual=${annual} domain=${domain} width=${width} ticks=${ticks} timeAxis
      extent=${extent} onRange=${onRange}
      label=${t(C.plot_label, { variables: keys, from: day(chart.from), to: day(chart.to) })}
      describedBy=${summary} />
    <figcaption class="sch-caption">
      <p class="sch-note">${chartNote(chart, whole)}</p>
      <p class="sch-legend faint">
        ${annual ? html`<span>${C.annual_legend}</span>` : null}
        ${chart.time_unit === "month" ? html`<span>${C.monthly_legend}</span>` : null}
        ${gaps ? html`<span>${annual ? C.annual_gap_note : C.gap_note}</span>` : null}
        <span>${C.unknown_note}</span>
        ${markers.some((marker) => marker.kind !== "accumulated") ? html`<span>${C.extremes_note}</span>` : null}
        ${markers.some((marker) => marker.kind === "accumulated") ? html`<span>${C.accumulated_note}</span>` : null}
      </p>
      <p class="sch-summary" id=${summary}>${chartSummary(chart)}</p>
      <p class="sch-keys faint">${C.keys}</p>
    </figcaption>
    ${loading ? html`<span class="sch-loading"><${Spinner} quiet /></span>` : null}
  </figure>`;
}

/**
 * The note of a chart: „wykres uproszczony: min./śr./maks. z N dni” with
 * what zooming gives, or the values it shows; of an annual chart, who found
 * its values and in what (A-ADR-051).
 *
 * @param {{time_unit: string, interval: number, resolution?: string, provider?: string}} chart
 * @param {boolean} whole - The whole series is shown (no range asked).
 * @returns {string}
 */
export function chartNote(chart, whole) {
  if (chart.resolution === "annual") return t(C.annual_note, { provider: chart.provider });
  const unit = chart.time_unit === "month" ? "month" : "day";
  if (chart.interval <= 1) return C.values[unit];
  const interval = count(chart.interval, C.interval_units[unit]);
  const more = whole ? `${C.simplified_whole}; ${C.simplified_more[unit]}` : C.simplified_more[unit];
  return `${t(C.simplified, { interval })} (${more})`;
}

/**
 * The line summing a chart: its range, and each variable's points with a
 * value and its gaps; of an annual chart its years.
 *
 * @param {import("../types.js").StationChart} chart
 * @returns {string}
 */
export function chartSummary(chart) {
  const annual = chart.resolution === "annual";
  const forms = annual ? L.units.year : (L.units[chart.time_unit] ?? L.units.day);
  const parts = [t(C.summary_range, { from: day(chart.from), to: day(chart.to), units: count(chart.units, forms) })];
  for (const variable of chart.variables) parts.push(variableSummary(variable, forms, annual));
  return parts.join(" · ");
}

/**
 * A variable's part of the summary: its points with a value, its gaps.
 *
 * @param {import("../types.js").ChartVariable} variable
 * @param {string[]} forms - The forms of the chart's unit (`dni`, `lat`).
 * @param {boolean} [annual] - Its points are years with a maximum and a minimum.
 * @returns {string}
 */
export function variableSummary(variable, forms, annual = false) {
  const valued = variable.points.filter((point) =>
    annual ? point.max !== null || point.min !== null : point.mean !== null,
  ).length;
  const points = count(variable.points.length, annual ? C.years_of : C.points);
  const units = variable.gaps.reduce((sum, gap) => sum + gap.units, 0);
  const gaps = variable.gaps.length
    ? t(C.summary_gaps, { gaps: count(variable.gaps.length, C.gaps), units: count(units, forms) })
    : C.summary_no_gaps;
  return `${t(C.summary_variable, { key: variable.key, valued, points })}, ${gaps}`;
}

/** The axes of the lines: the first variable's unit on the left, another on the right. */
function axesOf(lines) {
  const axes = [];
  for (const line of lines) {
    const axis = axes.find((item) => item.unit === line.variable.unit);
    if (axis) axis.lines.push(line);
    else axes.push({ unit: line.variable.unit, lines: [line] });
  }
  return axes;
}

/**
 * A plot of one or two variables over a range of time (`domain`): the grey
 * bands of the gaps, the band of the least and greatest values of a
 * simplified chart or of a month's published minimum and maximum, the line of
 * the values or means broken at each point without a value and at each gap,
 * the markers, the value axes (a second unit on the right) and, with
 * `timeAxis`, the time axis. An annual chart (`annual`) draws instead each
 * year's maximum and minimum as dots on their lines (`AnnualSeries`). A drag
 * selects a range, the wheel and the keys `+`, `-`, arrows and `Home` zoom
 * and move: `onRange` gets the days (`{from, to}`) or `null` for the whole
 * series.
 *
 * @param {object} props
 * @param {Array<{variable: import("../types.js").ChartVariable, color: number}>} props.lines
 * @param {string} props.timeUnit - `day` or `month` (`half_year` of an annual chart).
 * @param {number} props.interval - Units of a point.
 * @param {boolean} [props.annual] - The points are hydrological years (`AnnualPoint`).
 * @param {{start: number, end: number}} props.domain - Times of the range, end excluded.
 * @param {number} props.width - Of the whole figure, px.
 * @param {Array<{t: number, label: string}>} props.ticks - Of `timeTicks`.
 * @param {boolean} [props.timeAxis] - Draw the time axis's labels under the plot.
 * @param {{start: number, end: number}|null} props.extent - The days a zoom reaches.
 * @param {(range: {from: string, to: string}|null, options?: {replace?: boolean}) => void} props.onRange
 * @param {string} props.label - The plot's name for screen readers.
 * @param {string} [props.describedBy] - Id of the text that sums it.
 * @param {*} [props.title] - Drawn at the plot's top left (a panel's station).
 */
export function ChartPlot(props) {
  const { lines, timeUnit, interval, domain, width, ticks, timeAxis = false, extent, onRange } = props;
  const annual = props.annual ?? false;
  const axes = axesOf(lines);
  const left = MARGIN.left;
  const right = width - (axes.length > 1 ? MARGIN.axis : MARGIN.right);
  const plot = Math.max(1, right - left);
  const top = MARGIN.top;
  const bottom = top + PLOT_HEIGHT;
  const height = bottom + (timeAxis ? AXIS_HEIGHT : 6);
  const span = domain.end - domain.start;
  const x = (ms) => left + ((ms - domain.start) / span) * plot;
  const time = (px) => domain.start + ((px - left) / plot) * span;
  const svg = useRef(null);
  const [drag, setDrag] = useState(null);
  const [hover, setHover] = useState(null);
  const first = lines[0]?.variable;
  // A hydrological year spans twelve months from 1 XI.
  const spans = first
    ? annual
      ? pointSpans(first.points, "month", 12, domain.end)
      : pointSpans(first.points, timeUnit, interval, domain.end)
    : [];
  for (const axis of axes) Object.assign(axis, niceTicks(...valueRange(axis.lines, annual)));
  const y = (axis) => (value) => top + (1 - (value - axis.lo) / (axis.hi - axis.lo)) * PLOT_HEIGHT;
  // A month's minimum and maximum are a band even when each point is a month.
  const banded = interval > 1 || timeUnit === "month";

  const localX = (event) => event.clientX - svg.current.getBoundingClientRect().left;
  const within = (px) => Math.max(left, Math.min(right, px));
  const change = (next, { outward = false, replace = false } = {}) => {
    const range = settle(next, extent, outward);
    const now = { from: isoOf(domain.start), to: isoOf(domain.end - DAY) };
    if (range === null ? extent === null || covers(domain, extent) : sameRange(range, now)) return false;
    onRange(range, { replace });
    return true;
  };
  const down = (event) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const at = within(localX(event));
    setDrag({ from: at, to: at });
    setHover(null);
  };
  const move = (event) => {
    const at = within(localX(event));
    if (drag) setDrag({ ...drag, to: at });
    else setHover(spans.length ? { index: spanAt(spans, time(at)), at } : null);
  };
  const up = () => {
    if (!drag) return;
    setDrag(null);
    if (Math.abs(drag.to - drag.from) < DRAG_PX) return;
    change(
      { start: time(Math.min(drag.from, drag.to)), end: time(Math.max(drag.from, drag.to)) },
      { outward: true },
    );
  };
  const wheel = (event) => {
    if (!event.deltaY) return;
    const anchor = time(within(localX(event)));
    const factor = event.deltaY < 0 ? 1 / ZOOM.wheel : ZOOM.wheel;
    const next = {
      start: anchor - (anchor - domain.start) * factor,
      end: anchor + (domain.end - anchor) * factor,
    };
    if (change(next, { replace: true })) event.preventDefault();
  };
  const key = (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const middle = (domain.start + domain.end) / 2;
    const zoom = (factor) => ({ start: middle - (span * factor) / 2, end: middle + (span * factor) / 2 });
    const pan = (share) => ({ start: domain.start + span * share, end: domain.end + span * share });
    const moves = {
      "+": () => zoom(ZOOM.in),
      "=": () => zoom(ZOOM.in),
      "-": () => zoom(ZOOM.out),
      _: () => zoom(ZOOM.out),
      ArrowLeft: () => pan(-ZOOM.pan),
      ArrowRight: () => pan(ZOOM.pan),
    };
    if (event.key === "Home") {
      event.preventDefault();
      onRange(null);
    } else if (moves[event.key]) {
      event.preventDefault();
      change(moves[event.key](), { replace: true });
    }
  };

  const shown = hover && spans[hover.index] ? hover : null;
  return html`<div class="sch-plot" tabindex="0" role="group" aria-label=${props.label}
    aria-describedby=${props.describedBy} onKeyDown=${key}
    data-from=${isoOf(domain.start)} data-to=${isoOf(domain.end - DAY)} data-left=${left} data-width=${plot}>
    <svg ref=${svg} class="sch-svg" width=${width} height=${height} viewBox=${`0 0 ${width} ${height}`}
      aria-hidden="true" focusable="false">
      ${axes.map((axis, index) => html`<${ValueAxis} key=${axis.unit} axis=${axis} side=${index}
        left=${left} right=${right} y=${y(axis)} />`)}
      ${ticks.map((tick) => html`<line key=${tick.t} class="sch-grid" x1=${x(tick.t)} x2=${x(tick.t)}
        y1=${top} y2=${bottom} />`)}
      ${lines.map(({ variable, color }) =>
        variable.gaps.map((gap) => {
          const start = x(Math.max(domain.start, msOf(gap.from)));
          const end = x(Math.min(domain.end, msOf(gap.to) + DAY));
          const size = Math.max(1, end - start);
          return html`<g key=${`${variable.key}:${gap.from}`}>
            <rect class="sch-gap" data-key=${variable.key} data-from=${gap.from} data-to=${gap.to}
              x=${start} y=${top} width=${size} height=${PLOT_HEIGHT} />
            ${lines.length > 1
              ? html`<rect class=${`sch-gap-mark sch-v${color}`} x=${start} y=${top - 4 * (color + 1)}
                  width=${size} height="3" />`
              : null}
          </g>`;
        }),
      )}
      ${axes.flatMap((axis) =>
        axis.lines.map(({ variable, color }) => {
          const scaleY = y(axis);
          if (annual) {
            return html`<${AnnualSeries} key=${variable.key} variable=${variable} color=${color}
              spans=${spans} x=${x} y=${scaleY} />`;
          }
          const runs = runsOf(variable.points, spans, variable.gaps);
          const band = banded ? bandPath(runs, variable.points, spans, x, scaleY) : null;
          return html`<g key=${variable.key} class=${`sch-series sch-v${color}`} data-key=${variable.key}>
            ${band === null ? null : html`<path class="sch-band" d=${band} />`}
            <path class="sch-line" data-key=${variable.key} d=${linePath(runs, variable.points, spans, x, scaleY)} />
            ${runs
              .filter((run) => run.length === 1)
              .map(([index]) => html`<circle key=${index} class="sch-dot" cx=${x(spans[index].center)}
                cy=${scaleY(variable.points[index].mean)} r="2.4" />`)}
            ${variable.markers.map((marker) => html`<${Marker} key=${`${marker.kind}:${marker.t}:${marker.period}`}
              marker=${marker} x=${x(msOf(marker.t) + DAY / 2)} y=${scaleY(marker.value)} unit=${variable.unit} />`)}
          </g>`;
        }),
      )}
      ${timeAxis ? html`<${TimeLabels} ticks=${ticks} x=${x} y=${bottom} width=${width} />` : null}
      <line class="sch-base" x1=${left} x2=${right} y1=${bottom} y2=${bottom} />
      ${props.title ? html`<text class="sch-title" x=${left + 6} y=${top + 13}>${props.title}</text>` : null}
      ${shown ? html`<line class="sch-cursor" x1=${x(spans[shown.index].center)} x2=${x(spans[shown.index].center)}
        y1=${top} y2=${bottom} />` : null}
      ${drag ? html`<rect class="sch-selection" x=${Math.min(drag.from, drag.to)} y=${top}
        width=${Math.abs(drag.to - drag.from)} height=${PLOT_HEIGHT} />` : null}
      <rect class="sch-hit" x=${left} y=${top} width=${plot} height=${PLOT_HEIGHT}
        onPointerDown=${down} onPointerMove=${move} onPointerUp=${up}
        onPointerCancel=${() => setDrag(null)} onPointerLeave=${() => !drag && setHover(null)}
        onWheel=${wheel} />
    </svg>
    ${shown
      ? annual
        ? html`<${AnnualTip} lines=${lines} index=${shown.index} span=${spans[shown.index]}
            at=${x(spans[shown.index].center)} width=${width} />`
        : html`<${HoverTip} lines=${lines} index=${shown.index} span=${spans[shown.index]}
            interval=${interval} statistics=${banded} monthly=${timeUnit === "month"}
            at=${x(spans[shown.index].center)} width=${width} />`
      : null}
  </div>`;
}

/** A value axis: its ticks across the plot (the left one's), its labels and unit. */
function ValueAxis({ axis, side, left, right, y }) {
  const format = new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: decimalsOf(axis.step),
    maximumFractionDigits: decimalsOf(axis.step),
  });
  const at = side === 0 ? left - 6 : right + 6;
  const anchor = side === 0 ? "end" : "start";
  const keys = axis.lines.map((line) => line.variable.key).join(", ");
  return html`<g class=${`sch-axis sch-axis-${side === 0 ? "left" : "right"}`}>
    ${axis.ticks.map((value) => html`<g key=${value}>
      ${side === 0 ? html`<line class="sch-grid" x1=${left} x2=${right} y1=${y(value)} y2=${y(value)} />` : null}
      <text class="sch-tick" x=${at} y=${y(value) + 4} text-anchor=${anchor}>${format.format(value)}</text>
    </g>`)}
    <text class=${`sch-unit sch-v${axis.lines[0].color}`} x=${side === 0 ? 0 : right + MARGIN.axis} y="11"
      text-anchor=${side === 0 ? "start" : "end"}>${keys} [${unitText(axis.unit)}]</text>
  </g>`;
}

/** The labels of the time axis, kept inside the figure at its ends. */
function TimeLabels({ ticks, x, y, width }) {
  return html`<g class="sch-time">
    ${ticks.map((tick) => {
      const at = x(tick.t);
      const half = (tick.label.length * CHAR_PX) / 2;
      const anchor = at - half < 0 ? "start" : at + half > width ? "end" : "middle";
      return html`<g key=${tick.t}>
        <line class="sch-tick-mark" x1=${at} x2=${at} y1=${y} y2=${y + 4} />
        <text class="sch-tick" x=${at} y=${y + 16} text-anchor=${anchor}>${tick.label}</text>
      </g>`;
    })}
  </g>`;
}

/**
 * The time axis of stacked plots, under the last one (the comparison).
 *
 * @param {{ticks: Array<{t: number, label: string}>, domain: {start: number, end: number},
 *   width: number, right: number}} props - `right`: the space right of the plots, px.
 */
export function TimeAxis({ ticks, domain, width, right }) {
  const plot = Math.max(1, width - MARGIN.left - right);
  const x = (ms) => MARGIN.left + ((ms - domain.start) / (domain.end - domain.start)) * plot;
  return html`<svg class="sch-svg sch-time-axis" width=${width} height=${AXIS_HEIGHT}
    viewBox=${`0 0 ${width} ${AXIS_HEIGHT}`} aria-hidden="true" focusable="false">
    <line class="sch-base" x1=${MARGIN.left} x2=${MARGIN.left + plot} y1="0.5" y2="0.5" />
    <${TimeLabels} ticks=${ticks} x=${x} y=${0} width=${width} />
  </svg>`;
}

/** An extreme the provider published (a dot) or an accumulated sum (a diamond). */
function Marker({ marker, x, y, unit }) {
  const value = `${new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 3 }).format(marker.value)}`;
  if (marker.kind === "accumulated") {
    const title = t(C.accumulated, { value, unit: unitText(unit), day: day(marker.t) });
    return html`<path class="sch-marker accumulated" d=${`M${x},${y - 5}l5,5l-5,5l-5,-5z`}><title>${title}</title></path>`;
  }
  const when = marker.end && marker.end !== marker.t ? `${day(marker.t)}–${day(marker.end)}` : day(marker.t);
  const title = t(C.extreme, {
    kind: C.marker[marker.kind] ?? marker.kind,
    period: C.periods[marker.period ?? "annual"] ?? marker.period,
    value,
    unit: unitText(unit),
    when,
  });
  return html`<circle class=${`sch-marker ${marker.kind}`} cx=${x} cy=${y} r="4"><title>${title}</title></circle>`;
}

/**
 * The tooltip of the point under the pointer: its days and each variable's
 * value, or its least, mean and greatest (`statistics`: a simplified chart, or
 * a month's published minimum, mean and maximum).
 */
function HoverTip({ lines, index, span, interval, statistics, monthly, at, width }) {
  const first = isoOf(span.start);
  const last = isoOf(span.end - DAY);
  const one = monthly ? day(first).slice(0, 7) : day(first);
  const when = interval > 1 && first !== last ? `${day(first)}–${day(last)}` : one;
  const number = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 3 });
  const rows = lines.map(({ variable, color }) => {
    const point = variable.points[index];
    const unit = unitText(variable.unit);
    let text;
    if (!point || point.mean === null) {
      text = t(inGap(variable, span) ? C.tip_gap : C.tip_unknown, { key: variable.key });
    } else if (statistics) {
      text = t(C.tip_simplified, {
        key: variable.key,
        mean: number.format(point.mean),
        min: point.min === null ? "–" : number.format(point.min),
        max: point.max === null ? "–" : number.format(point.max),
        unit,
      });
    } else text = t(C.tip_value, { key: variable.key, value: number.format(point.mean), unit });
    return html`<span key=${variable.key} class=${`sch-tip-row sch-v${color}`}>${text}</span>`;
  });
  const style = at > width / 2 ? { right: `${width - at + 8}px` } : { left: `${at + 8}px` };
  return html`<div class="sch-tip" role="presentation" style=${style}>
    <b>${when}</b>${rows}
  </div>`;
}

/** Whether a gap of a variable covers any of a point's time. */
function inGap(variable, span) {
  return variable.gaps.some((gap) => msOf(gap.from) < span.end && msOf(gap.to) + DAY > span.start);
}

/** The two extremes of an annual chart: each year's maximum and minimum. */
const ANNUAL_EXTREMES = ["max", "min"];

/**
 * A variable of an annual chart: the line of its yearly maxima and that of its
 * minima (dashed), broken at a year without one and at each gap, and a dot
 * at each value, hollow for an incomplete year (one half without a value).
 */
function AnnualSeries({ variable, color, spans, x, y }) {
  return html`<g class=${`sch-series sch-v${color}`} data-key=${variable.key}>
    ${ANNUAL_EXTREMES.map((kind) => {
      const value = (point) => point[kind]?.value ?? null;
      const runs = runsOf(variable.points, spans, variable.gaps, value);
      return html`<g key=${kind}>
        <path class=${`sch-line ${kind}`} data-key=${variable.key} data-kind=${kind}
          d=${linePath(runs, variable.points, spans, x, y, value)} />
        ${variable.points.map((point, index) => {
          const extreme = point[kind];
          if (!extreme) return null;
          const name = `sch-year ${kind}${extreme.partial ? " partial" : ""}`;
          return html`<circle key=${point.year} class=${name} data-key=${variable.key}
            data-year=${point.year} data-kind=${kind} cx=${x(spans[index].center)}
            cy=${y(extreme.value)} r="3.4" />`;
        })}
      </g>`;
    })}
  </g>`;
}

/**
 * The tooltip of a year of an annual chart: each variable's maximum and
 * minimum with its days, half-year and occurrences, and „niepełny rok” when
 * a half has no value.
 */
function AnnualTip({ lines, index, span, at, width }) {
  const year = lines[0]?.variable.points[index]?.year;
  const rows = lines.flatMap(({ variable, color }) => {
    const point = variable.points[index];
    const found = ANNUAL_EXTREMES.filter((kind) => point?.[kind]);
    if (!found.length) {
      const text = t(inGap(variable, span) ? C.tip_gap : C.tip_unknown, { key: variable.key });
      return [html`<span key=${variable.key} class=${`sch-tip-row sch-v${color}`}>${text}</span>`];
    }
    return found.map(
      (kind) => html`<span key=${`${variable.key}:${kind}`} class=${`sch-tip-row sch-v${color}`}>
        ${annualText(variable.key, kind, point[kind], unitText(variable.unit))}</span>`,
    );
  });
  const style = at > width / 2 ? { right: `${width - at + 8}px` } : { left: `${at + 8}px` };
  return html`<div class="sch-tip" role="presentation" style=${style}>
    <b>${t(C.tip_year, { year })}</b>${rows}
  </div>`;
}

/**
 * A year's maximum or minimum for a person: „Q maks.: 223 m³/s · 2024.03.02
 * (półrocze zimowe)”, its occurrences when more than one, and „niepełny rok:
 * brak półrocza letniego” when the other half has no value.
 *
 * @param {string} key
 * @param {"max"|"min"} kind
 * @param {import("../types.js").AnnualExtreme} extreme
 * @param {string} unit - As people write it.
 * @returns {string}
 */
export function annualText(key, kind, extreme, unit) {
  const number = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 3 });
  const { start, end } = extreme;
  let when = C.undated;
  if (start) when = !end || end === start ? day(start) : `${day(start)}–${day(end)}`;
  const half = extreme.halves.length > 1 ? C.halves_both : C.halves[extreme.halves[0]];
  const value = number.format(extreme.value);
  const parts = [t(C.tip_annual, { key, kind: C.marker[kind], value, unit, when, half })];
  const times = extreme.occurrences;
  if (times !== null && times > 1) parts.push(count(times, C.occurrences));
  if (extreme.partial) parts.push(C.partial[extreme.partial]);
  return parts.join(" · ");
}

/**
 * The time each point covers: from its first day to the next point's (the
 * last one to the range's end), and its middle, where its vertex lies.
 *
 * @param {import("../types.js").ChartPoint[]} points
 * @param {string} timeUnit - `day` or `month`.
 * @param {number} interval - Units of a point.
 * @param {number} end - The range's end (excluded), ms.
 * @returns {Array<{start: number, end: number, center: number}>}
 */
export function pointSpans(points, timeUnit, interval, end) {
  return points.map((point) => {
    const start = msOf(point.t);
    const date = new Date(start);
    const next =
      timeUnit === "month"
        ? Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + interval, 1)
        : start + interval * DAY;
    const stop = Math.min(next, end);
    return { start, end: stop, center: (start + stop) / 2 };
  });
}

/** The point whose time holds `ms` (the nearest at the ends). */
function spanAt(spans, ms) {
  let low = 0;
  let high = spans.length - 1;
  while (low < high) {
    const middle = (low + high + 1) >> 1;
    if (spans[middle].start <= ms) low = middle;
    else high = middle - 1;
  }
  return low;
}

/**
 * The runs of points the line joins: a point without a value ends a run, and
 * so does a gap between two points (never a line across it).
 *
 * @param {Array<import("../types.js").ChartPoint|import("../types.js").AnnualPoint>} points
 * @param {Array<{center: number}>} spans - Of `pointSpans`.
 * @param {import("../types.js").GapSpan[]} gaps - In order.
 * @param {(point: *) => number|null} [value] - The value of a point the line
 *   joins: its mean by default.
 * @returns {number[][]} The indexes of the points of each run.
 */
export function runsOf(points, spans, gaps, value = (point) => point.mean) {
  const bands = gaps.map((gap) => ({ start: msOf(gap.from), end: msOf(gap.to) + DAY }));
  const runs = [];
  let run = null;
  let previous = null;
  let next = 0;
  points.forEach((point, index) => {
    if (value(point) === null) {
      run = null;
      return;
    }
    const at = spans[index].center;
    if (run !== null) {
      while (next < bands.length && bands[next].end <= previous) next += 1;
      if (next < bands.length && bands[next].start < at) run = null;
    }
    if (run === null) {
      run = [];
      runs.push(run);
    }
    run.push(index);
    previous = at;
  });
  return runs;
}

const px = (value) => Math.round(value * 10) / 10;

/** The line of the values (means, by default): a subpath a run, a run of one point a dot. */
function linePath(runs, points, spans, x, y, value = (point) => point.mean) {
  const vertex = (index) => `${px(x(spans[index].center))},${px(y(value(points[index])))}`;
  return runs
    .map((run) => {
      const vertices = run.map(vertex);
      return vertices.length === 1 ? `M${vertices[0]}h0` : `M${vertices.join("L")}`;
    })
    .join("");
}

/**
 * The band of the least and greatest values of a simplified chart, or of a
 * month's minimum and maximum, a shape a run (the mean where one is missing).
 */
function bandPath(runs, points, spans, x, y) {
  const middle = (index) => px(x(spans[index].center));
  const top = (index) => px(y(points[index].max ?? points[index].mean));
  const low = (index) => px(y(points[index].min ?? points[index].mean));
  return runs
    .map((run) => {
      if (run.length === 1) {
        const [index] = run;
        const at = middle(index);
        return `M${at - 1},${top(index)}H${at + 1}V${low(index)}H${at - 1}Z`;
      }
      const upper = run.map((index) => `${middle(index)},${top(index)}`);
      const lower = [...run].reverse().map((index) => `${middle(index)},${low(index)}`);
      return `M${upper.join("L")}L${lower.join("L")}Z`;
    })
    .join("");
}

/**
 * The least and greatest value of the lines of an axis with their markers',
 * a little apart; of an annual chart its years' maxima and minima.
 */
function valueRange(lines, annual = false) {
  let low = Infinity;
  let high = -Infinity;
  for (const { variable } of lines) {
    for (const point of variable.points) {
      const values = annual ? [point.min?.value, point.max?.value] : [point.min, point.max];
      for (const value of values) {
        if (value === null || value === undefined) continue;
        low = Math.min(low, value);
        high = Math.max(high, value);
      }
    }
    for (const marker of variable.markers) {
      low = Math.min(low, marker.value);
      high = Math.max(high, marker.value);
    }
  }
  if (!(low <= high)) return [0, 1];
  const pad = (high - low) * 0.04;
  return [low >= 0 ? Math.max(0, low - pad) : low - pad, high + pad];
}

/**
 * Round ticks of a value axis around `low` and `high`, about five.
 *
 * @param {number} low
 * @param {number} high
 * @returns {{ticks: number[], lo: number, hi: number, step: number}} The ticks and
 *   the axis's ends, on ticks.
 */
export function niceTicks(low, high) {
  let lo = low;
  let hi = high;
  if (!(hi > lo)) {
    const pad = Math.abs(lo) * 0.1 || 1;
    lo -= pad;
    hi += pad;
  }
  const raw = (hi - lo) / 5;
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10) * power;
  const first = Math.floor(lo / step) * step;
  const last = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let value = first; value <= last + step / 2; value += step) ticks.push(Number(value.toPrecision(12)));
  return { ticks, lo: first, hi: last, step };
}

/**
 * The ticks of a time axis: days, months or years, as many as fit `width`.
 *
 * @param {number} start - The range's first time, ms.
 * @param {number} end - Its end (excluded), ms.
 * @param {number} width - Of the plot, px.
 * @returns {Array<{t: number, label: string}>}
 */
export function timeTicks(start, end, width) {
  const days = (end - start) / DAY;
  const [kind, step] =
    TICK_STEPS.find(([name, size]) => days / (TICK_DAYS[name] * size) <= width / TICK_PX[name]) ??
    TICK_STEPS[TICK_STEPS.length - 1];
  const ticks = [];
  const add = (ms, label) => {
    if (ms >= start && ms < end) ticks.push({ t: ms, label });
  };
  const from = new Date(start);
  if (kind === "year") {
    for (let year = Math.floor(from.getUTCFullYear() / step) * step; Date.UTC(year, 0, 1) < end; year += step) {
      add(Date.UTC(year, 0, 1), String(year));
    }
  } else if (kind === "month") {
    const month = from.getUTCFullYear() * 12 + from.getUTCMonth();
    for (let index = Math.floor(month / step) * step; Date.UTC(Math.floor(index / 12), index % 12, 1) < end; index += step) {
      const year = Math.floor(index / 12);
      add(Date.UTC(year, index % 12, 1), `${year}.${String((index % 12) + 1).padStart(2, "0")}`);
    }
  } else {
    for (let month = Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), 1); month < end; ) {
      const date = new Date(month);
      const next = Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1);
      const length = Math.round((next - month) / DAY);
      for (let number = 1; number <= length; number += step) {
        if (step === 1 || number + step - 1 <= length) add(month + (number - 1) * DAY, day(isoOf(month + (number - 1) * DAY)));
      }
      month = next;
    }
  }
  return ticks;
}

/** Steps of the axis of an annual chart, in years. */
const YEAR_STEPS = [1, 2, 5, 10, 20, 50, 100];

/**
 * The ticks of an annual chart's time axis: hydrological years at the middle
 * of each (where its dots lie), labelled with their numbers, as many as fit
 * `width`.
 *
 * @param {number} start - The range's first time (1 XI), ms.
 * @param {number} end - Its end (excluded, 1 XI), ms.
 * @param {number} width - Of the plot, px.
 * @returns {Array<{t: number, label: string}>}
 */
export function yearTicks(start, end, width) {
  const first = new Date(start).getUTCFullYear() + 1;
  const last = new Date(end - DAY).getUTCFullYear();
  const years = last - first + 1;
  const step = YEAR_STEPS.find((size) => years / size <= width / TICK_PX.year) ?? YEAR_STEPS.at(-1);
  const middle = (year) => (Date.UTC(year - 1, 10, 1) + Date.UTC(year, 10, 1)) / 2;
  const ticks = [];
  for (let year = Math.ceil(first / step) * step; year <= last; year += step) {
    ticks.push({ t: middle(year), label: String(year) });
  }
  return ticks.length ? ticks : [{ t: middle(first), label: String(first) }];
}

/**
 * The days of a wanted range (times, end excluded), kept within the series:
 * at least `MIN_DAYS`, moved inside the extent; `null` when it holds the
 * whole series. A selection takes every day it touches (`outward`); a zoom
 * or a move takes the nearest days, so a move keeps the range's length.
 *
 * @param {{start: number, end: number}} next
 * @param {{start: number, end: number}|null} extent
 * @param {boolean} outward
 * @returns {{from: string, to: string}|null}
 */
function settle(next, extent, outward) {
  let { start, end } = next;
  const length = Math.max(end - start, MIN_DAYS * DAY);
  if (end - start < length) {
    const middle = (start + end) / 2;
    start = middle - length / 2;
    end = middle + length / 2;
  }
  if (extent) {
    if (length >= extent.end - extent.start) return null;
    if (start < extent.start) {
      start = extent.start;
      end = start + length;
    }
    if (end > extent.end) {
      end = extent.end;
      start = end - length;
    }
  }
  const first = (outward ? Math.floor(start / DAY) : Math.round(start / DAY)) * DAY;
  const last = Math.max(first + DAY, (outward ? Math.ceil(end / DAY) : Math.round(end / DAY)) * DAY);
  return { from: isoOf(first), to: isoOf(last - DAY) };
}

/** The decimals a tick step needs: 2 for 0.25, 0 for 50. */
function decimalsOf(step) {
  for (let decimals = 0; decimals < 8; decimals += 1) {
    const scaled = step * 10 ** decimals;
    if (Math.abs(Math.round(scaled) - scaled) < 1e-6) return decimals;
  }
  return 8;
}

function covers(domain, extent) {
  return domain.start <= extent.start && domain.end >= extent.end;
}

function sameRange(a, b) {
  return a.from === b.from && a.to === b.to;
}
