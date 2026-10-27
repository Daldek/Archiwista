/**
 * „Oś czasu” of the stations (docs/SPEC.md 6.8, sketch 6.5 j; plan I8.3,
 * ADR-045): the second layout of a station product's Catalog
 * (`layout=timeline`, views/switch.js), the stations of one dataset — the
 * address's, else the product's first — as `GET /stations/timeline` pages
 * them with the list's filters, order and cursor (views/catalog-stations.js
 * reads the pages).
 *
 * An ARIA treegrid of stations × years: a station's row shows the years of
 * its "Kolor punktów" variable (`color` of the address, as on the map; the
 * dataset's first by default) and expands into a row per variable of its
 * series. A cell is a year in the series' year type: green, its saturation
 * the share of the known units with a value (`full` saturated, `fraction`
 * lighter in proportion), `none` a grey hollow box, `unknown` a grey dashed
 * outline (SPEC 4.8.4, never colour alone: the legend and the tooltip name
 * each). The tooltip gives the year by its convention, its units, known
 * units and units with a value, the variable's label and its longest gap.
 * The station rows' variable is chosen on the client: the pages ask for
 * every variable, since `variable` would hide stations (P14, ADR-045
 * decision 6). A dataset with many variables is asked for fewer stations a
 * page (`timelinePage`).
 *
 * Rows have one height and are drawn only near the visible part. One cell
 * is the tab stop (roving tabindex): arrows move by year and row, Page
 * Up/Down by a view, Home/End to a row's ends (with Ctrl the grid's), Enter
 * or Space expands or folds a station. A station's name, or K on any of its
 * rows, opens its card (views/station.js).
 */

import { count, day, int } from "../format.js";
import { catalog as L } from "../labels/catalog.js";
import { t } from "../labels/index.js";
import { StationSymbol, stationShape, stationType } from "../map/stations.js";
import {
  html,
  Icon,
  Spinner,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "../ui.js";

const S = L.stations;
const TL = S.timeline;
/** Height of a row and of the header row, px (catalog.css `.stl-row`, `.stl-header`). */
const ROW = 26;
const HEAD = 30;
/** Rows drawn beyond each edge of the visible part. */
const OVERSCAN = 6;
/** Load the next page when fewer rows than this are left below the view. */
const PREFETCH_ROWS = 60;
/** Variable rows a page asks for: 200 stations of a daily hydro dataset (H, Q, T). */
const PAGE_ROWS = 600;
const PAGE_MAX = 200;
const PAGE_MIN = 20;
/** The fill of a year with a value in almost none and in almost all of its units. */
const LIGHTEST = 0.16;
const DARKEST = 0.86;

/**
 * The dataset of the Timeline: the address's, else the product's first.
 *
 * @param {Object<string, string>} params - Route parameters.
 * @param {import("../types.js").StationDataset[]} datasets - Of the product.
 * @returns {string|null} Its key; `null` without any.
 */
export function timelineDataset(params, datasets) {
  return params.dataset || datasets[0]?.dataset || null;
}

/**
 * Stations a page asks for: as many as hold the variable rows of 200 daily
 * water gauges (a half-year dataset has up to 27 keys a station).
 *
 * @param {import("../types.js").StationDataset|null} dataset
 * @param {string[]} variables - The address's `variable` filter.
 * @returns {number}
 */
export function timelinePage(dataset, variables) {
  const rows = variables.length || dataset?.variables.length || 1;
  return Math.max(PAGE_MIN, Math.min(PAGE_MAX, Math.floor(PAGE_ROWS / rows)));
}

/**
 * The Timeline: the dataset and the station rows' variable above the
 * treegrid, its legend, the rows and the tooltip.
 *
 * @param {object} props
 * @param {import("../types.js").StationTimelineItem[]} props.items - Stations
 *   loaded so far.
 * @param {number|null} props.total - Stations of the whole answer.
 * @param {boolean} props.hasMore - A next page exists.
 * @param {boolean} props.loading - The first page of a new query is coming.
 * @param {boolean} props.loadingMore
 * @param {*} props.moreError - Why the last next page failed.
 * @param {() => void} props.onMore - Load the next page.
 * @param {string} props.resetKey - The query: a new one starts at the top.
 * @param {string} props.datasetKey - The dataset asked for.
 * @param {import("../types.js").StationDataset|null} props.dataset - Its name and
 *   variables, when `GET /stations/datasets` knows it.
 * @param {boolean} props.chosen - The dataset is the address's (else the first).
 * @param {string|null} props.color - The address's `color`.
 * @param {(key: string) => void} props.onColor - Choose the station rows' variable.
 * @param {*} props.empty - Shown instead of rows when there are none.
 * @param {(station: import("../types.js").StationTimelineItem) => void} props.onOpen -
 *   Open a station's card.
 * @param {(station: import("../types.js").StationTimelineItem) => string} props.cardHref -
 *   The address of a station's card (its name is a link).
 * @param {{current: *}} props.handle - Receives `{focusRow(index)}`.
 */
export function StationTimeline(props) {
  const { items, total, hasMore, loading, loadingMore, moreError, onMore, resetKey } = props;
  const { datasetKey, dataset, chosen, handle } = props;
  const id = useId();
  const scroller = useRef(null);
  const tipBox = useRef(null);
  const anchored = useRef(null);
  const pending = useRef(null);
  const [view, setView] = useState({ top: 0, height: 0 });
  const [expanded, setExpanded] = useState(() => new Set());
  const [focus, setFocus] = useState({ key: null, parent: null, col: 0 });
  const [hover, setHover] = useState(null);
  const [inside, setInside] = useState(false);
  const variables = dataset?.variables ?? items[0]?.series[0]?.variables ?? [];
  const color = (variables.find((item) => item.key === props.color) ?? variables[0])?.key ?? null;
  const rows = useMemo(() => timelineRows(items, expanded, color), [items, expanded, color]);
  const span = useMemo(() => yearSpan(items), [items]);
  const places = useMemo(() => new Map(rows.map((row, at) => [row.key, at])), [rows]);
  const years = span ? span.last - span.first + 1 : 0;
  const last = rows.length - 1;
  const current = places.get(focus.key) ?? places.get(focus.parent) ?? 0;
  const col = Math.min(focus.col, years);
  const [first, end] = drawn(view, last);

  useLayoutEffect(() => {
    const element = scroller.current;
    const measure = () => setView({ top: element.scrollTop, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    scroller.current.scrollTop = 0;
    setView((before) => ({ ...before, top: 0 }));
    setFocus({ key: null, parent: null, col: 0 });
    setHover(null);
  }, [resetKey]);

  useEffect(() => {
    const near = end >= rows.length - PREFETCH_ROWS;
    if (hasMore && near && !loading && !loadingMore && !moreError) onMore();
  }, [end, rows.length, hasMore, loading, loadingMore, moreError]);

  // A cell the keys moved to is focused once its row is drawn.
  useLayoutEffect(() => {
    if (pending.current === null) return;
    const { row, column } = pending.current;
    const cell = cellAt(scroller.current, row, column);
    if (!cell) return;
    pending.current = null;
    revealColumn(scroller.current, cell, column);
    cell.focus({ preventScroll: true });
  });

  const focused = inside && col > 0 && rows.length ? { key: rows[current].key, col } : null;
  const tip = hover ?? focused;
  const tipAt = tip ? places.get(tip.key) : undefined;
  const tipRow = tipAt === undefined ? null : rows[tipAt];
  anchored.current = tipRow ? { at: tipAt, col: tip.col } : null;
  // The tooltip stands under its cell (above it near the bottom), inside the window, and
  // follows it when the rows scroll; a cell scrolled out of the view takes it away.
  const placeTip = () => {
    const box = tipBox.current;
    const shown = anchored.current;
    const anchor = shown ? cellAt(scroller.current, shown.at, shown.col) : null;
    const rect = anchor?.getBoundingClientRect();
    const frame = scroller.current.getBoundingClientRect();
    const visible = rect && rect.bottom > frame.top + HEAD && rect.top < frame.bottom;
    if (!visible || rect.right <= frame.left || rect.left >= frame.right) {
      box.style.visibility = "hidden";
      return;
    }
    const middle = rect.left + rect.width / 2 - box.offsetWidth / 2;
    const left = Math.max(8, Math.min(window.innerWidth - box.offsetWidth - 8, middle));
    const below = rect.bottom + 6;
    const fits = below + box.offsetHeight <= window.innerHeight - 8;
    box.style.left = `${left}px`;
    box.style.top = `${fits ? below : rect.top - box.offsetHeight - 6}px`;
    box.style.visibility = "visible";
  };
  useLayoutEffect(placeTip);

  if (handle) handle.current = { focusRow: (index) => focusCell(index, 0) };

  function revealRow(at) {
    const element = scroller.current;
    const top = at * ROW;
    if (top < element.scrollTop) element.scrollTop = top;
    else if (top + ROW > element.scrollTop + element.clientHeight - HEAD) {
      element.scrollTop = top + ROW - element.clientHeight + HEAD;
    }
  }

  function focusCell(at, column) {
    if (!rows.length) return;
    const row = Math.max(0, Math.min(last, at));
    const place = Math.max(0, Math.min(years, column));
    setFocus({ key: rows[row].key, parent: rows[row].parent, col: place });
    revealRow(row);
    pending.current = { row, column: place };
    setView({ top: scroller.current.scrollTop, height: scroller.current.clientHeight });
  }

  const toggle = (row) => {
    if (row.level !== 1 || !row.size) return;
    setExpanded((before) => {
      const next = new Set(before);
      if (next.has(row.id)) next.delete(row.id);
      else next.add(row.id);
      return next;
    });
  };
  const keys = (event) => {
    const found = target(event);
    if (!found || event.altKey || event.metaKey) return;
    const { at, column } = found;
    const page = Math.max(1, Math.floor((view.height - HEAD) / ROW) - 1);
    if (event.key === "ArrowRight") focusCell(at, column + 1);
    else if (event.key === "ArrowLeft") focusCell(at, column - 1);
    else if (event.key === "ArrowDown") focusCell(at + 1, column);
    else if (event.key === "ArrowUp") focusCell(at - 1, column);
    else if (event.key === "PageDown") focusCell(at + page, column);
    else if (event.key === "PageUp") focusCell(at - page, column);
    else if (event.key === "Home") focusCell(event.ctrlKey ? 0 : at, 0);
    else if (event.key === "End") focusCell(event.ctrlKey ? last : at, years);
    else if ((event.key === "Enter" || event.key === " ") && !event.ctrlKey) toggle(rows[at]);
    else if ((event.key === "k" || event.key === "K") && !event.ctrlKey) {
      props.onOpen(rows[at].station);
    } else return;
    event.preventDefault();
  };
  const focusIn = (event) => {
    setInside(true);
    const found = target(event);
    const row = found ? rows[found.at] : null;
    if (row) setFocus({ key: row.key, parent: row.parent, col: found.column });
  };
  const focusOut = (event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setInside(false);
  };
  const over = (event) => {
    const found = target(event);
    const row = found && found.column > 0 ? rows[found.at] : null;
    if (!row) setHover(null);
    else if (hover?.key !== row.key || hover.col !== found.column) {
      setHover({ key: row.key, col: found.column });
    }
  };
  const click = (event) => {
    const found = target(event);
    if (!found) return;
    // The name is a link to the card: a plain click opens it over the Catalog.
    if (event.target.closest?.(".stl-open")) {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
      event.preventDefault();
      props.onOpen(rows[found.at].station);
    } else if (found.column === 0) toggle(rows[found.at]);
  };
  // A scroll redraws the rows only when another row comes near the view.
  const scroll = (event) => {
    const element = event.currentTarget;
    const next = { top: element.scrollTop, height: element.clientHeight };
    placeTip();
    const [nextFirst, nextEnd] = drawn(next, last);
    if (nextFirst !== first || nextEnd !== end) setView(next);
  };

  const indexes = [];
  for (let index = first; index <= end; index += 1) indexes.push(index);
  if (rows.length && (current < first || current > end)) indexes.push(current);
  const yearType = span?.yearType ?? dataset?.year_type ?? null;
  const children = rows.length - items.length;
  const height = rows.length * ROW + (hasMore ? ROW * 2 : 0);
  const tipId = `${id}-tip`;

  return html`<div class="stl">
    <div class="stl-bar">
      <span class="stl-dataset">
        <b>${dataset?.name ?? datasetKey}</b>
        ${dataset ? html`<span class="faint"> · ${dataset.provider}</span>` : null}
        ${yearType
          ? html`<span class="muted"> · ${TL.year_types[yearType] ?? yearType}</span>`
          : null}
        ${chosen ? null : html`<span class="faint"> (${TL.dataset_first})</span>`}
      </span>
      <span class="cat-spacer"></span>
      <${RowVariable} variables=${variables} color=${color} onChoose=${props.onColor} />
    </div>
    <${Legend} />
    <div class=${`stl-grid${loading ? " busy" : ""}`} role="treegrid" aria-label=${TL.grid}
      aria-describedby="cat-keys" aria-rowcount=${total === null ? -1 : total + children + 1}
      aria-colcount=${years + 1} aria-busy=${loading ? "true" : "false"}
      style=${{ "--stl-years": String(Math.max(1, years)) }}>
      <div class="stl-scroll" ref=${scroller} onKeyDown=${keys} onFocusIn=${focusIn}
        onFocusOut=${focusOut} onMouseOver=${over} onMouseLeave=${() => setHover(null)}
        onClick=${click} onScroll=${scroll}>
        <div class="stl-head" role="rowgroup">
          <div class="stl-row stl-header" role="row" aria-rowindex="1">
            <div class="stl-rowhead" role="columnheader" aria-colindex="1">${TL.station}</div>
            ${span ? yearHeaders(span, yearType) : null}
          </div>
        </div>
        <div class="stl-rows" role="rowgroup" style=${{ height: `${height}px` }}>
          ${indexes.map((index) => {
            const row = rows[index];
            return html`<${TimelineRow} key=${row.key} row=${row} index=${index} span=${span}
              yearType=${yearType} focusAt=${index === current ? col : -1}
              described=${tipRow === row ? tip.col : -1} tipId=${tipId} total=${total}
              cardHref=${props.cardHref} />`;
          })}
          ${hasMore
            ? html`<div class="stl-more" aria-hidden="true"
                style=${{ transform: `translateY(${rows.length * ROW}px)` }}>
                ${moreError ? null : html`<${Spinner} label=${L.result.loading_more} />`}
              </div>`
            : null}
        </div>
        ${rows.length
          ? null
          : html`<div class="cat-empty">
              ${loading ? html`<${Spinner} label=${L.result.loading} />` : props.empty}
            </div>`}
      </div>
    </div>
    <div class="stl-tip float-card" role="tooltip" id=${tipId} ref=${tipBox}>
      ${tipRow && span
        ? html`<${Tip} row=${tipRow} col=${tip.col} span=${span} yearType=${yearType} />`
        : null}
    </div>
  </div>`;
}

/** "Wiersz stacji": the variables of the dataset, the one the station rows show. */
function RowVariable({ variables, color, onChoose }) {
  if (variables.length < 2) return null;
  return html`<div class="chip-row stl-colors" role="group" aria-label=${TL.row_variable}>
    <span class="stl-colors-label" aria-hidden="true">${TL.row_variable}:</span>
    ${variables.map((item) => {
      const on = item.key === color;
      const title = t(TL.row_variable_title, { variable: item.key, unit: item.unit });
      return html`<button type="button" key=${item.key} class=${`chip${on ? " on" : ""}`}
        aria-pressed=${on ? "true" : "false"} title=${title}
        onClick=${() => onChoose(item.key)}>${item.key}</button>`;
    })}
  </div>`;
}

/** The four kinds of a year's cell, each with its text. */
function Legend() {
  return html`<div class="stl-legend" role="group" aria-label=${TL.legend}>
    ${["full", "fraction", "none", "unknown"].map(
      (cell) => html`<span key=${cell}><i class=${`stl-c ${cell}`} aria-hidden="true"
        style=${cell === "fraction" ? { "--a": "0.45" } : null}></i>${TL.legend_cells[cell]}
      </span>`,
    )}
  </div>`;
}

/** A row of the treegrid: a station, or a variable of an expanded station. */
function TimelineRow({ row, index, span, yearType, focusAt, described, tipId, total, cardHref }) {
  const station = row.level === 1;
  const expanded = station && row.size ? (row.open ? "true" : "false") : null;
  const title = station ? stationTitle(row.station) : variableTitle(row.variable);
  return html`<div class=${`stl-row ${station ? "station" : "variable"}`} role="row"
    aria-rowindex=${index + 2} aria-level=${row.level} aria-expanded=${expanded}
    aria-posinset=${row.position + 1} aria-setsize=${station ? (total ?? -1) : row.size}
    data-row=${index} style=${{ transform: `translateY(${index * ROW}px)` }}>
    <div class="stl-rowhead" role="rowheader" aria-colindex="1" data-col="0"
      tabindex=${focusAt === 0 ? 0 : -1} title=${title}>
      ${station ? stationHead(row, cardHref) : variableHead(row)}
    </div>
    ${span ? yearCells(row, span, focusAt, described, tipId) : null}
  </div>`;
}

/** The heading of a station's row: the fold, symbol, name (its card's link), code and variable. */
function stationHead(row, cardHref) {
  const station = row.station;
  const state = row.variable?.state ?? "no_data";
  const name = station.name ?? S.unnamed;
  let variable = null;
  if (row.variable) variable = html`<span class="stl-key mono">${row.variable.key}</span>`;
  else if (row.missing) {
    variable = html`<span class="stl-missing faint"
      title=${t(TL.no_variable_title, { variable: row.missing })}>
      ${t(TL.no_variable, { variable: row.missing })}</span>`;
  }
  return html`<span class="stl-twisty" aria-hidden="true">
      ${row.size ? html`<${Icon} name=${row.open ? "down" : "chevron"} size=${13} />` : null}
    </span>
    <${StationSymbol} shape=${stationShape(station)} state=${state} size=${12} />
    <a class="stl-name stl-open ell" href=${cardHref(station)} tabindex="-1"
      title=${t(TL.open_title, { name })}>${name}</a>${" "}
    <span class="stl-code faint mono">${station.code}</span>${" "}
    ${variable}`;
}

/** The heading of a variable's row: its symbol, key, unit and label. */
function variableHead(row) {
  const variable = row.variable;
  const shape = stationShape(row.station);
  return html`<${StationSymbol} shape=${shape} state=${variable.state} size=${12} />
    <span class="stl-key mono">${variable.key}</span>${" "}
    <span class="faint">${variable.unit}</span>${" "}
    <span class="stl-label ell">${variable.label}</span>`;
}

/** The cells of a row's years: the class of each year's cell, a fraction's fill as `--a`. */
function yearCells(row, span, focusAt, described, tipId) {
  const cells = [];
  const forms = unitForms(row.series);
  for (let column = 1; column <= span.last - span.first + 1; column += 1) {
    const entry = yearOf(row.variable, span.first + column - 1);
    const kind = entry ? entry.cell : "out";
    const style = kind === "fraction" ? { "--a": String(fill(entry)) } : null;
    cells.push(html`<div key=${column} class=${`stl-c ${kind}`} role="gridcell"
      aria-colindex=${column + 1} data-col=${column} tabindex=${focusAt === column ? 0 : -1}
      style=${style} aria-label=${cellText(entry, row, forms)}
      aria-describedby=${described === column ? tipId : null}></div>`);
  }
  return cells;
}

/** The headers of the years: the convention of each, its number every few years. */
function yearHeaders(span, yearType) {
  const years = span.last - span.first + 1;
  const step = years <= 12 ? 1 : years <= 40 ? 5 : 10;
  const headers = [];
  for (let year = span.first; year <= span.last; year += 1) {
    const name = yearTitle(year, yearType);
    const number = year % step === 0 ? html`<span aria-hidden="true">${year}</span>` : null;
    headers.push(html`<div key=${year} class="stl-year" role="columnheader"
      aria-colindex=${year - span.first + 2} aria-label=${name} title=${name}>${number}</div>`);
  }
  return headers;
}

/** The tooltip of a year's cell. */
function Tip({ row, col, span, yearType }) {
  const year = span.first + col - 1;
  const variable = row.variable;
  const name = row.station.name ?? row.station.code;
  if (!variable) {
    const missing = t(TL.no_variable_title, { variable: row.missing ?? "" });
    return html`<b>${name}</b><div>${missing}</div>`;
  }
  const entry = yearOf(variable, year);
  const forms = unitForms(row.series);
  const gap = variable.longest_gap;
  const units = entry
    ? t(TL.units_line, {
        units: count(entry.units, forms),
        known: int(entry.known),
        with_value: int(entry.with_value),
      })
    : null;
  const longest = gap
    ? t(TL.longest_gap, { from: day(gap.from), to: day(gap.to), units: count(gap.units, forms) })
    : null;
  const unit = html`<span class="faint">(${variable.unit})</span>`;
  return html`<div><b>${name} · ${variable.key}</b> ${unit}</div>
    <div class="stl-tip-year">${yearTitle(year, yearType)}</div>
    <div>${cellText(entry, row, forms)}</div>
    ${units ? html`<div class="tabular">${units}</div>` : null}
    <div class="muted">${t(TL.label, { label: variable.label })}</div>
    ${longest ? html`<div>${longest}</div>` : null}`;
}

/**
 * The rows of the loaded stations: each station, then its variables when it
 * is expanded.
 *
 * @param {import("../types.js").StationTimelineItem[]} items
 * @param {Set<string>} expanded - Ids of the expanded stations.
 * @param {string|null} color - Key of the station rows' variable.
 */
function timelineRows(items, expanded, color) {
  const rows = [];
  items.forEach((station, position) => {
    const id = `${station.store}/${station.provider}/${station.code}`;
    const series = station.series[0] ?? null;
    const variables = series?.variables ?? [];
    const open = expanded.has(id) && variables.length > 0;
    const key = `s:${id}`;
    const variable = variables.find((item) => item.key === color) ?? null;
    const missing = variable ? null : color;
    const size = variables.length;
    rows.push({
      key,
      parent: null,
      id,
      level: 1,
      station,
      series,
      variable,
      missing,
      open,
      position,
      size,
    });
    if (!open) return;
    variables.forEach((item, at) => {
      rows.push({
        key: `v:${id}:${item.key}`,
        parent: key,
        id,
        level: 2,
        station,
        series,
        variable: item,
        missing: null,
        open: false,
        position: at,
        size,
      });
    });
  });
  return rows;
}

/** The years of the loaded stations' series (R of each) and their year type. */
function yearSpan(items) {
  let first = Infinity;
  let last = -Infinity;
  let yearType = null;
  for (const item of items) {
    for (const series of item.series) {
      if (!series.years) continue;
      first = Math.min(first, series.years.from);
      last = Math.max(last, series.years.to);
      yearType = yearType ?? series.year_type;
    }
  }
  return first > last ? null : { first, last, yearType };
}

/** The rows drawn for a view: the visible ones and `OVERSCAN` beyond each edge. */
function drawn(view, last) {
  const first = Math.max(0, Math.floor(view.top / ROW) - OVERSCAN);
  const end = Math.min(last, Math.floor((view.top + view.height - HEAD) / ROW) + OVERSCAN);
  return [first, end];
}

/** The element of a drawn cell. */
function cellAt(scroller, row, column) {
  return scroller.querySelector(`[data-row="${row}"] [data-col="${column}"]`);
}

/** Where an event happened: the row and column of its cell, or `null`. */
function target(event) {
  const cell = event.target.closest?.("[data-col]");
  const row = cell?.closest("[data-row]");
  return cell && row ? { at: Number(row.dataset.row), column: Number(cell.dataset.col) } : null;
}

/** A variable's entry of a year, `null` outside its R. */
function yearOf(variable, year) {
  const years = variable?.years ?? [];
  const entry = years[year - (years[0]?.year ?? 0)];
  return entry?.year === year ? entry : null;
}

/** The fill of a year with a value in some units: lighter in proportion to the share. */
function fill(entry) {
  const share = entry.known ? entry.with_value / entry.known : 0;
  return Math.round((LIGHTEST + (DARKEST - LIGHTEST) * share) * 100) / 100;
}

/** What a year's cell says: its kind, a fraction with its share of the known units. */
function cellText(entry, row, forms) {
  if (!row.variable) return t(TL.no_variable, { variable: row.missing ?? "" });
  if (!entry) return TL.cells.outside;
  if (entry.cell !== "fraction") return TL.cells[entry.cell];
  const share = entry.known ? entry.with_value / entry.known : 0;
  const percent = share < 0.01 ? "<1%" : `${Math.min(99, Math.floor(share * 100))}%`;
  return `${t(TL.cells.fraction, { share: percent })} (${count(entry.with_value, forms)})`;
}

/** The convention of a year: "r.h. 2024 (2023.11.01–2024.10.31)" or "2024 (kalendarzowy)". */
function yearTitle(year, yearType) {
  if (yearType === "hydrological") {
    return t(TL.year_hydrological, { year, from: `${year - 1}.11.01`, to: `${year}.10.31` });
  }
  return t(TL.year_calendar, { year });
}

/** The words of a series' unit: days, months or half-years. */
function unitForms(series) {
  return TL.units[series?.time_unit] ?? TL.units.day;
}

/** A station for its row heading's title: name, type, river, code, provider, location. */
function stationTitle(station) {
  const place = station.location.kind === "point" ? null : S.unlocated;
  const code = `${station.code} · ${station.provider}`;
  return [station.name ?? S.unnamed, stationType(station), station.river, code, place]
    .filter(Boolean)
    .join(" · ");
}

/** A variable for its row heading's title: key, unit and label. */
function variableTitle(variable) {
  const { key, unit, label } = variable;
  return t(S.variable_title, { variable: key, unit, label });
}

/** Scroll a focused cell out from under the sticky row headings, into the view. */
function revealColumn(element, cell, column) {
  if (column === 0) return;
  const head = element.querySelector(".stl-rows .stl-rowhead")?.offsetWidth ?? 0;
  const left = cell.offsetLeft;
  const right = left + cell.offsetWidth;
  if (left - head < element.scrollLeft) element.scrollLeft = left - head;
  else if (right > element.scrollLeft + element.clientWidth) {
    element.scrollLeft = right - element.clientWidth;
  }
}
