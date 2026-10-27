/**
 * The catalog's list (docs/SPEC.md 6.8 „Lista”, cel 4.5): an ARIA grid whose
 * rows are drawn only near the visible part, so 50 000 loaded rows keep a
 * few dozen elements on the page. What a row is comes from its kind
 * (`GridRows`): its height — a station has a line per variable, so rows
 * differ — its cells and its header, so the files (`FILE_ROWS`) and the
 * stations (views/catalog-stations.js) share one grid. Pages of the cursor
 * arrive as the end comes near (`onMore`); the header stays at the top of
 * the scrolled area.
 *
 * Keyboard: one row is the tab stop (roving tabindex); arrows, Page Up/Down
 * and Home/End move it; Enter or Space opens the row (`onOpen`: the file
 * card); M shows a row with a place on the map. Rows are in the API's order,
 * the only order a keyset cursor can page.
 */

import { int, plural, size } from "../format.js";
import { catalog as L } from "../labels/catalog.js";
import { t } from "../labels/index.js";
import { html, Icon, Spinner, useEffect, useLayoutEffect, useMemo, useRef, useState } from "../ui.js";

/** Height of the header row in px (catalog.css `.cat-head`). */
const HEAD = 32;
/** Height of the row of the next page's spinner, px. */
const MORE = 44;
/** Rows drawn beyond each edge of the visible part. */
const OVERSCAN = 8;
/** Load the next page when fewer rows than this are left below the view. */
const PREFETCH_ROWS = 120;

/**
 * How the grid draws a kind of row.
 *
 * @typedef {object} GridRows
 * @property {string} label - The grid's name.
 * @property {(props: object) => number} columns - Its columns (`aria-colcount`).
 * @property {(props: object) => string} layout - The class of its column layout
 *   (catalog.css).
 * @property {(props: {item: *, index: number, props: object}) => *} Cells - A row's
 *   cells.
 * @property {(item: *, narrow: boolean) => number} height - A row's height, px.
 * @property {(item: *) => string} key - A row's identity.
 * @property {(item: *) => string} [className] - More classes of a row.
 * @property {(item: *) => boolean} mappable - The row can be shown on the map (M).
 * @property {(item: *) => boolean} [pickable] - The row can be chosen for a
 *   comparison (P).
 */

/**
 * Whether a row's outline can be shown on the map (files without one never are).
 *
 * @param {import("../types.js").SlotItem} item
 * @returns {boolean}
 */
export function onMapOf(item) {
  return item.location.kind === "footprint";
}

/**
 * The list of the catalog.
 *
 * @param {object} props
 * @param {GridRows} props.rows - The kind of the rows.
 * @param {Array<*>} props.items - Rows loaded so far.
 * @param {number|null} props.total - Rows of the whole answer.
 * @param {boolean} props.hasMore - A next page exists.
 * @param {boolean} props.loading - The first page of a new query is coming.
 * @param {boolean} props.loadingMore
 * @param {*} props.moreError - Why the last next page failed (`ApiError`).
 * @param {() => void} props.onMore - Load the next page.
 * @param {string} props.resetKey - The query: a new one starts at the top.
 * @param {(item: *) => boolean} props.isSelected - The row whose card is open.
 * @param {boolean} props.cardOpen - Whether a card is open.
 * @param {(item: *) => void} props.onOpen - Enter, Space or a click on the row.
 * @param {((item: *) => void)|null} props.onMap - `null` when there is no map view.
 * @param {((item: *) => void)|null} [props.onPick] - Choose a row for a comparison
 *   (P), or leave it out; `null` without one.
 * @param {boolean} props.narrow - Phone layout.
 * @param {*} props.empty - Shown instead of rows when there are none.
 * @param {{current: *}} props.handle - Receives `{focusRow(index)}`.
 */
export function CatalogGrid(props) {
  const { rows, items, total, hasMore, loading, loadingMore, moreError, onMore, resetKey } = props;
  const { narrow, handle, cardOpen } = props;
  const scroller = useRef(null);
  const focusNext = useRef(null);
  const [view, setView] = useState({ top: 0, height: 0 });
  const [active, setActive] = useState(0);
  const head = narrow ? 0 : HEAD;
  // The top of each row and, last, the height of them all.
  const offsets = useMemo(() => {
    const tops = new Array(items.length + 1);
    tops[0] = 0;
    for (let index = 0; index < items.length; index += 1) {
      tops[index + 1] = tops[index] + rows.height(items[index], narrow);
    }
    return tops;
  }, [items, narrow, rows]);

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
    setView((current) => ({ ...current, top: 0 }));
    setActive(0);
  }, [resetKey]);

  const last = items.length - 1;
  const current = Math.min(active, Math.max(last, 0));
  const first = Math.max(0, rowAt(offsets, view.top - head) - OVERSCAN);
  const end = Math.min(last, rowAt(offsets, view.top + view.height - head) + OVERSCAN);

  useEffect(() => {
    if (hasMore && !loading && !loadingMore && !moreError && end >= items.length - PREFETCH_ROWS) {
      onMore();
    }
  }, [end, items.length, hasMore, loading, loadingMore, moreError]);

  useLayoutEffect(() => {
    if (focusNext.current === null) return;
    const row = scroller.current.querySelector(`[data-index="${focusNext.current}"]`);
    if (row) {
      row.focus({ preventScroll: true });
      focusNext.current = null;
    }
  });

  // A closed card gives the focus back to its row.
  const wasOpen = useRef(cardOpen);
  useEffect(() => {
    if (wasOpen.current && !cardOpen && (!document.activeElement || document.activeElement === document.body)) {
      focusRow(current);
    }
    wasOpen.current = cardOpen;
  }, [cardOpen]);

  if (handle) handle.current = { focusRow };

  function reveal(index) {
    const element = scroller.current;
    const top = head + offsets[index];
    const bottom = head + offsets[index + 1];
    if (top - head < element.scrollTop) element.scrollTop = top - head;
    else if (bottom > element.scrollTop + element.clientHeight) {
      element.scrollTop = bottom - element.clientHeight;
    }
  }

  function focusRow(index) {
    if (!items.length) return;
    const next = Math.max(0, Math.min(last, index));
    setActive(next);
    reveal(next);
    focusNext.current = next;
    setView({ top: scroller.current.scrollTop, height: scroller.current.clientHeight });
  }

  // A page down is the row a view's height below, less one, so it stays in view.
  const below = (at) => Math.max(at + 1, rowAt(offsets, offsets[at] + view.height - head) - 1);
  const above = (at) => Math.min(at - 1, rowAt(offsets, Math.max(0, offsets[at] - (view.height - head))) + 1);
  const keys = (event) => {
    const row = event.target.closest?.("[role=row][data-index]");
    if (!items.length || event.altKey || !row) return;
    const at = Number(row.dataset.index);
    const item = items[at];
    const plain = !event.ctrlKey && !event.metaKey;
    const onButton = event.target.closest("button") !== null;
    if (event.key === "ArrowDown") focusRow(at + 1);
    else if (event.key === "ArrowUp") focusRow(at - 1);
    else if (event.key === "PageDown") focusRow(below(at));
    else if (event.key === "PageUp") focusRow(above(at));
    else if (event.key === "Home") focusRow(0);
    else if (event.key === "End") focusRow(last);
    else if ((event.key === "Enter" || event.key === " ") && plain && !onButton) props.onOpen(item);
    else if ((event.key === "m" || event.key === "M") && plain && props.onMap && rows.mappable(item)) {
      props.onMap(item);
    } else if ((event.key === "p" || event.key === "P") && plain && props.onPick && rows.pickable?.(item)) {
      props.onPick(item);
    } else return;
    event.preventDefault();
  };
  const click = (event, item) => {
    if (event.target.closest("button")) return;
    if (event.target.closest("a") && (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0)) {
      return;
    }
    event.preventDefault();
    props.onOpen(item);
  };

  const indexes = [];
  for (let index = first; index <= end; index += 1) indexes.push(index);
  if (items.length && (current < first || current > end)) indexes.push(current);
  const columns = rows.columns(props);
  const height = offsets[items.length] + (hasMore ? MORE : 0);
  const { Header, Cells } = rows;

  return html`<div class=${`cat-grid ${rows.layout(props)}${narrow ? " narrow" : ""}${loading ? " busy" : ""}`}
    role="grid" aria-label=${rows.label} aria-describedby="cat-keys"
    aria-rowcount=${total === null ? -1 : total + 1} aria-colcount=${columns}
    aria-busy=${loading ? "true" : "false"}>
    <div class="cat-scroll" ref=${scroller} onKeyDown=${keys}
      onScroll=${(event) => setView({ top: event.currentTarget.scrollTop, height: event.currentTarget.clientHeight })}>
      <div class="cat-head" role="rowgroup">
        <div class="cat-row head" role="row" aria-rowindex="1"><${Header} ...${props} /></div>
      </div>
      <div class="cat-rows" role="rowgroup" style=${{ height: `${height}px` }}>
        ${indexes.map((index) => {
          const item = items[index];
          const selected = props.isSelected(item);
          const more = rows.className ? rows.className(item) : "";
          return html`<div key=${rows.key(item)} class=${`cat-row${selected ? " selected" : ""}${more ? ` ${more}` : ""}`}
            role="row" aria-rowindex=${index + 2} aria-selected=${selected ? "true" : "false"}
            tabindex=${index === current ? 0 : -1} data-index=${index}
            style=${{ transform: `translateY(${offsets[index]}px)`, height: `${offsets[index + 1] - offsets[index]}px` }}
            onClick=${(event) => click(event, item)} onFocusIn=${() => setActive(index)}>
            <${Cells} item=${item} index=${index} props=${props} />
          </div>`;
        })}
        ${hasMore
          ? html`<div class="cat-more" aria-hidden="true"
              style=${{ transform: `translateY(${offsets[items.length]}px)` }}>
              ${moreError ? null : html`<${Spinner} label=${L.result.loading_more} />`}
            </div>`
          : null}
      </div>
      ${items.length
        ? null
        : html`<div class="cat-empty">${loading ? html`<${Spinner} label=${L.result.loading} />` : props.empty}</div>`}
    </div>
  </div>`;
}

/**
 * The row whose top is at `y` or the last one above it.
 *
 * @param {number[]} offsets - The top of each row, then the height of them all.
 * @param {number} y - Pixels below the first row's top.
 * @returns {number}
 */
function rowAt(offsets, y) {
  let low = 0;
  let high = Math.max(0, offsets.length - 2);
  while (low < high) {
    const middle = (low + high + 1) >> 1;
    if (offsets[middle] <= y) low = middle;
    else high = middle - 1;
  }
  return low;
}

/** Row height in px of a file on a computer and on a phone (two lines each; catalog.css). */
const FILE_ROW = 44;
const FILE_ROW_NARROW = 58;

/** The rows of files: a slot, or one of its versions (`versions=all`). */
export const FILE_ROWS = {
  label: L.grid.label,
  columns: (props) => (props.storeNames ? 9 : 8),
  layout: (props) => (props.storeNames ? "with-store" : ""),
  Header: FileHeader,
  Cells: FileCells,
  height: (_item, narrow) => (narrow ? FILE_ROW_NARROW : FILE_ROW),
  key: (item) => `${item.store}/${item.slot}#${item.version?.path ?? ""}`,
  className: (item) => (item.status === "ok" ? "" : "problem-row"),
  mappable: onMapOf,
};

function FileHeader({ storeNames }) {
  const G = L.grid;
  return html`<div role="columnheader" class="cell c-name" aria-sort="ascending" title=${G.sorted}>
      ${G.name}<${Icon} name="down" size=${12} />
    </div>
    <div role="columnheader" class="cell c-unit">${G.unit}</div>
    <div role="columnheader" class="cell c-prod">${G.product}</div>
    <div role="columnheader" class="cell c-year" title=${G.year_title}>${G.year}</div>
    <div role="columnheader" class="cell c-ver">${G.version}</div>
    <div role="columnheader" class="cell c-size">${G.size}</div>
    <div role="columnheader" class="cell c-loc">${G.location}</div>
    ${storeNames ? html`<div role="columnheader" class="cell c-store">${G.store}</div>` : null}
    <div role="columnheader" class="cell c-act"><span class="visually-hidden">${G.actions}</span></div>`;
}

/**
 * The cells of a file's row.
 *
 * @param {{item: import("../types.js").SlotItem, props: object}} props - `props`: the
 *   grid's (`cardHref`, `onMap`, `versions`, `storeNames`).
 */
function FileCells({ item, props }) {
  const G = L.grid;
  const version = item.version;
  const located = onMapOf(item);
  return html`<div role="gridcell" class="cell c-name">
      <a class="cat-name" href=${props.cardHref(item)} tabindex="-1" title=${item.slot}
        aria-label=${t(G.open_card, { name: item.name })}>${item.name}</a>
      <span class="cell-sub">${statusBadge(item)}${countText(item)}</span>
    </div>
    <div role="gridcell" class="cell c-unit">
      <span class="mono ell" title=${item.unit ?? ""}>${item.unit ?? "–"}</span>
      <span class="cell-sub">${countryText(item.country)}</span>
    </div>
    <div role="gridcell" class="cell c-prod">
      <span class="ell" title=${item.segment.label}>${item.segment.label}</span>
      <span class="cell-sub mono ell" title=${technical(item)}>${technical(item)}</span>
    </div>
    <div role="gridcell" class="cell c-year tabular">${version?.data_year ?? "–"}</div>
    <div role="gridcell" class="cell c-ver">
      <span class="mono ell" title=${version?.path ?? ""}>${version?.label ?? "–"}</span>
      <span class="cell-sub">${versionTags(item, props.versions)}</span>
    </div>
    <div role="gridcell" class="cell c-size tabular">${version ? size(version.size_bytes) : "–"}</div>
    <div role="gridcell" class="cell c-loc">${locationBadge(item)}</div>
    ${props.storeNames
      ? html`<div role="gridcell" class="cell c-store ell" title=${item.store}>
          ${props.storeNames.get(item.store) ?? item.store}</div>`
      : null}
    <div role="gridcell" class="cell c-act">
      ${located && props.onMap
        ? html`<button type="button" class="btn ghost icon-btn cat-map" tabindex="-1"
            title=${t(G.show_on_map, { name: item.name })}
            aria-label=${t(G.show_on_map, { name: item.name })}
            onClick=${() => props.onMap(item)}><${Icon} name="map" size=${15} /></button>`
        : null}
    </div>`;
}

function statusBadge(item) {
  if (item.status === "ok") return null;
  const level = item.status === "missing" ? "bad" : "warn";
  return html`<span class=${`cat-badge ${level}`} title=${item.status}>
    ${L.status[item.status] ?? item.status}</span>`;
}

function countText(item) {
  if (item.versions_count < 2) return null;
  return html`<span class="faint">${int(item.versions_count)} ${plural(item.versions_count, L.grid.version_count)}</span>`;
}

function countryText(country) {
  if (!country) return null;
  const name = L.countries[country];
  return name ? `${name} (${country})` : country;
}

/** The producer and the segment path: the technical value of the product's name. */
function technical(item) {
  const segment = item.segment;
  const product = segment.known ? segment.path : `${segment.path ?? ""} · ${L.grid.unknown_product}`;
  return [segment.producer, product].filter(Boolean).join(" · ");
}

function versionTags(item, versions) {
  const version = item.version;
  if (!version) return html`<span class="cat-badge warn">${L.grid.no_version}</span>`;
  const tags = [];
  if (versions !== "current") {
    tags.push(version.is_current
      ? html`<span class="cat-tag current">${L.grid.current}</span>`
      : html`<span class="cat-tag">${L.grid.noncurrent}</span>`);
  }
  if (version.is_full_sheet) tags.push(html`<span class="cat-tag">${L.grid.full_sheet}</span>`);
  if (version.state === "missing") {
    tags.push(html`<span class="cat-badge bad">${L.grid.missing_version}</span>`);
  }
  return tags;
}

function locationBadge(item) {
  const { kind, reason, source } = item.location;
  const detail =
    kind === "footprint"
      ? L.location.source[source] ?? source
      : kind === "none"
        ? L.location.reason[reason] ?? reason
        : countryText(item.country);
  return html`<span class=${`cat-loc ${kind}`}>${L.location[kind] ?? kind}</span>
    <span class="cell-sub" title=${[kind, source ?? reason].filter(Boolean).join(": ")}>${detail}</span>`;
}
