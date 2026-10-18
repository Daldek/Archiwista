/**
 * The map of the map view (docs/SPEC.md 5.4, 6.3): MapLibre with the
 * basemap, the store's outlines in the view — or, above the limit, their
 * grid — the sheet grid, the area and the drawing tools.
 *
 * The view owns the data and passes it in; the map reports moves, drawn
 * shapes and choices. Layers change through `setData` and hover through
 * feature state, so thousands of outlines never pass through Preact; a
 * feature carries only its index into the answer the view gave.
 */

import { count, int } from "../format.js";
import { T, t } from "../labels/index.js";
import { map as L } from "../labels/map.js";
import { GLYPH_FONT, loadMapLibre } from "../maplibre.js";
import { html, Icon, useEffect, useLayoutEffect, useRef, useState } from "../ui.js";
import { startDrawing } from "./draw.js";
import { HOME_BOUNDS, positionParams, viewBounds } from "./geo.js";
import { mapStyle, setBasemap } from "./style.js";

const EMPTY = { type: "FeatureCollection", features: [] };
/** Colours of the neutral theme: store data in the local blue, the area in indigo. */
export const COLORS = {
  footprint: "#1d4ed8",
  cell: "#1d4ed8",
  sheet: "#475467",
  area: "#3730a3",
  draw: "#4f46e5",
};
const HOVER = ["boolean", ["feature-state", "hover"], false];
const FIT_MAX_ZOOM = 15;
const PICK_LIMIT = 12;

/**
 * Footprints, grid cells and sheets as GeoJSON for the map.
 *
 * @param {Array<{geometry: *}>} items
 * @returns {object} FeatureCollection whose features hold their index `i`.
 */
function features(items, props = () => ({})) {
  return {
    type: "FeatureCollection",
    features: items.map((item, i) => ({
      type: "Feature",
      id: i,
      properties: { i, ...props(item) },
      geometry: item.geometry,
    })),
  };
}

function cellGeometry(cell) {
  const { min_lon: west, min_lat: south, max_lon: east, max_lat: north } = cell;
  return {
    type: "Polygon",
    coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
  };
}

function addDataLayers(map) {
  for (const id of ["cells", "footprints", "sheets", "area", "draw"]) {
    map.addSource(id, { type: "geojson", data: EMPTY });
  }
  const text = (field, size, color) => ({
    layout: {
      "text-field": ["get", field],
      "text-font": [GLYPH_FONT],
      "text-size": size,
      "text-allow-overlap": false,
    },
    paint: { "text-color": color, "text-halo-color": "rgba(255,255,255,0.9)", "text-halo-width": 1.3 },
  });
  const layers = [
    {
      id: "cells-fill",
      type: "fill",
      source: "cells",
      paint: {
        "fill-color": COLORS.cell,
        "fill-opacity": [
          "interpolate", ["linear"], ["get", "share"], 0, 0.1, 1, 0.55,
        ],
      },
    },
    {
      id: "cells-line",
      type: "line",
      source: "cells",
      paint: { "line-color": ["case", HOVER, "#0b1f5c", "#ffffff"], "line-width": ["case", HOVER, 2, 1] },
    },
    { id: "cells-label", type: "symbol", source: "cells", ...text("label", 11, "#0b1f5c") },
    {
      id: "footprints-fill",
      type: "fill",
      source: "footprints",
      paint: {
        "fill-color": COLORS.footprint,
        "fill-opacity": ["case", HOVER, 0.35, 0.1],
        "fill-antialias": false,
      },
    },
    {
      // A 1 px outline drawn as GL lines: far cheaper than a line layer for
      // thousands of outlines.
      id: "footprints-line",
      type: "fill",
      source: "footprints",
      paint: {
        "fill-color": "rgba(0, 0, 0, 0)",
        "fill-outline-color": ["case", HOVER, "#0b1f5c", COLORS.footprint],
      },
    },
    {
      id: "sheets-fill",
      type: "fill",
      source: "sheets",
      paint: { "fill-color": COLORS.sheet, "fill-opacity": ["case", HOVER, 0.16, 0] },
    },
    {
      id: "sheets-line",
      type: "line",
      source: "sheets",
      paint: { "line-color": COLORS.sheet, "line-width": 0.8, "line-dasharray": [3, 2] },
    },
    { id: "sheets-label", type: "symbol", source: "sheets", ...text("sheet", 10.5, "#344054") },
    {
      id: "area-fill",
      type: "fill",
      source: "area",
      paint: { "fill-color": COLORS.area, "fill-opacity": 0.06 },
    },
    {
      id: "area-line",
      type: "line",
      source: "area",
      paint: { "line-color": COLORS.area, "line-width": 2.6 },
    },
    {
      id: "draw-fill",
      type: "fill",
      source: "draw",
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": COLORS.draw, "fill-opacity": 0.12 },
    },
    {
      id: "draw-line",
      type: "line",
      source: "draw",
      paint: { "line-color": COLORS.draw, "line-width": 2, "line-dasharray": [2, 1.5] },
    },
    {
      id: "draw-points",
      type: "circle",
      source: "draw",
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": 4.5,
        "circle-color": "#ffffff",
        "circle-stroke-color": COLORS.draw,
        "circle-stroke-width": 2,
      },
    },
  ];
  for (const layer of layers) map.addLayer(layer);
}

/**
 * The imperative side of the map the view uses.
 *
 * @typedef {object} MapApi
 * @property {(bbox: number[], options?: {animate?: boolean}) => void} fit - Frame a box.
 * @property {() => number[]} bounds - The visible box (WGS84).
 * @property {() => number} width - Width of the map in px.
 */

/**
 * A move of the map, reported when it ends.
 *
 * @typedef {object} MapMove
 * @property {number[]} bbox - The visible box (WGS84).
 * @property {number} width - Width of the map in px.
 * @property {{center: string, zoom: string}} position - For the address.
 * @property {boolean} byUser - Moved by a person, not by framing.
 */

/**
 * The MapLibre map with the data of the view.
 *
 * @param {object} props
 * @param {import("../types.js").BasemapSettings|null} props.basemap
 * @param {{center: [number, number], zoom: number}|null} props.start - Position of
 *   the address; else the home view until the view frames something.
 * @param {import("../types.js").Area|null} props.area
 * @param {import("../types.js").MapView|undefined} props.footprints
 * @param {import("../types.js").Sheet[]} props.sheets - Sheet grid (empty: none).
 * @param {"rect"|"poly"|null} props.tool - Drawing tool in use.
 * @param {(item: import("../types.js").Footprint) => string} props.describe - The
 *   product of an outline for people.
 * @param {(api: MapApi) => void} props.onReady
 * @param {(move: MapMove) => void} props.onMove
 * @param {(geometry: import("../types.js").Geometry, tool: string) => void} props.onDrawn
 * @param {() => void} props.onCancel - Drawing cancelled.
 * @param {(sheet: import("../types.js").Sheet) => void} props.onSheet - A sheet
 *   of the grid clicked.
 * @param {(item: import("../types.js").Footprint) => void} props.onOpen - An
 *   outline chosen: open its file card.
 * @param {*} [props.children] - Overlays of the view over the map.
 */
export function MapCanvas({
  basemap,
  start,
  area,
  footprints,
  sheets,
  tool,
  describe,
  onReady,
  onMove,
  onDrawn,
  onCancel,
  onSheet,
  onOpen,
  children,
}) {
  const box = useRef(null);
  const [map, setMap] = useState(null);
  const [failure, setFailure] = useState(null);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [tip, setTip] = useState(null);
  const [pick, setPick] = useState(null);
  const [vertices, setVertices] = useState(0);
  const drawing = useRef(null);
  const data = useRef({ items: [], cells: [], sheets: [] });
  const pointer = useRef(null);
  const tipBox = useRef(null);
  const tipAt = useRef({ x: 0, y: 0 });
  const props = useRef({});
  props.current = { onMove, onDrawn, onCancel, onSheet, onOpen, describe, tool, gridOn: sheets.length > 0 };
  const basemapKey = basemap ? JSON.stringify(basemap) : "";
  const shownBasemap = useRef(basemapKey);

  useEffect(() => {
    let live = true;
    let created = null;
    loadMapLibre().then(
      (maplibre) => {
        if (!live) return;
        const narrow = box.current.clientWidth < 600;
        created = new maplibre.Map({
          container: box.current,
          style: mapStyle(basemap),
          ...(start
            ? { center: start.center, zoom: start.zoom }
            : { bounds: HOME_BOUNDS, fitBoundsOptions: { padding: 16 } }),
          attributionControl: false,
          dragRotate: false,
          pitchWithRotate: false,
          touchPitch: false,
          maxPitch: 0,
          renderWorldCopies: false,
          locale: {
            "Map.Title": L.canvas.title,
            "NavigationControl.ZoomIn": L.canvas.zoom_in,
            "NavigationControl.ZoomOut": L.canvas.zoom_out,
            "NavigationControl.ResetBearing": L.canvas.reset_bearing,
            "AttributionControl.ToggleAttribution": L.canvas.attribution,
          },
        });
        created.touchZoomRotate.disableRotation();
        created.keyboard.disableRotation();
        created.addControl(new maplibre.AttributionControl({ compact: narrow }), "bottom-right");
        created.addControl(new maplibre.NavigationControl({ showCompass: false }), "bottom-right");
        created.addControl(new maplibre.ScaleControl({ unit: "metric" }), "bottom-right");
        created.on("error", (event) => {
          // Without a listener MapLibre logs to the console; a basemap that does
          // not answer is said in the legend instead.
          if (event.sourceId === "basemap") setBasemapFailed(true);
          else setFailure(event.error ?? event);
        });
        created.once("load", () => {
          if (!live) return;
          addDataLayers(created);
          pointer.current = bindPointer(created, props, data, {
            setTip,
            setPick,
            moveTip: (x, y) => {
              tipAt.current = { x, y };
              place(tipBox.current, tipAt.current);
            },
          });
          bindMoves(created, props);
          setMap(created);
          onReady?.({
            fit: (bbox, { animate = true } = {}) => fit(created, bbox, animate),
            bounds: () => viewBounds(created),
            width: () => created.getContainer().clientWidth,
          });
          props.current.onMove?.(move(created, false));
        });
      },
      (error) => live && setFailure(error),
    );
    return () => {
      live = false;
      created?.remove();
    };
  }, []);

  useEffect(() => {
    if (!map || shownBasemap.current === basemapKey) return;
    shownBasemap.current = basemapKey;
    setBasemapFailed(false);
    setBasemap(map, basemap);
  }, [map, basemapKey]);

  useEffect(() => {
    if (!map) return;
    const aggregated = Boolean(footprints?.aggregated);
    data.current.items = footprints && !aggregated ? footprints.items : [];
    data.current.cells = footprints && aggregated ? footprints.cells : [];
    const most = data.current.cells.reduce((top, cell) => Math.max(top, cell.count), 1);
    map.getSource("footprints").setData(features(data.current.items));
    map.getSource("cells").setData(
      features(
        data.current.cells.map((cell) => ({ ...cell, geometry: cellGeometry(cell) })),
        (cell) => ({ label: int(cell.count), share: cell.count / most }),
      ),
    );
    pointer.current?.reset();
    setPick(null);
  }, [map, footprints]);

  useEffect(() => {
    if (!map) return;
    data.current.sheets = sheets;
    map.getSource("sheets").setData(features(sheets, (sheet) => ({ sheet: sheet.sheet })));
  }, [map, sheets]);

  useEffect(() => {
    if (!map) return;
    map.getSource("area").setData(
      area ? { type: "Feature", properties: {}, geometry: area.geometry } : EMPTY,
    );
  }, [map, area]);

  // Before paint: the drawing hint is never shown without its keys working.
  useLayoutEffect(() => {
    if (!map || !tool) return undefined;
    setTip(null);
    setPick(null);
    drawing.current = startDrawing(map, tool, {
      onDone: (geometry, kind) => props.current.onDrawn(geometry, kind),
      onCancel: () => props.current.onCancel(),
      onCount: setVertices,
    });
    return () => {
      drawing.current.stop();
      drawing.current = null;
    };
  }, [map, tool]);

  return html`<div class="map-canvas">
    <div class="map-gl" ref=${box}></div>
    ${failure
      ? html`<p class="map-failure float-card" role="alert">
          ${t(L.canvas.failed, { message: failure.message ?? String(failure) })}</p>`
      : null}
    ${tool ? html`<${DrawHint} tool=${tool} vertices=${vertices} drawing=${drawing}
      onCancel=${onCancel} />` : null}
    ${tip && !tool ? html`<${Tooltip} tip=${tip} describe=${describe} box=${tipBox} at=${tipAt} />` : null}
    ${pick && !tool
      ? html`<${PickList} pick=${pick} describe=${describe} onClose=${() => setPick(null)}
          onOpen=${(item) => {
            setPick(null);
            onOpen(item);
          }} />`
      : null}
    ${children}
    ${basemapFailed ? html`<p class="map-note float-card" role="status">${L.canvas.basemap_failed}</p>` : null}
  </div>`;
}

function move(map, byUser) {
  return {
    bbox: viewBounds(map),
    width: map.getContainer().clientWidth,
    position: positionParams(map),
    byUser,
  };
}

function bindMoves(map, props) {
  let byUser = false;
  map.on("movestart", (event) => {
    byUser = Boolean(event.originalEvent);
  });
  map.on("moveend", (event) => {
    props.current.onMove?.(move(map, byUser || Boolean(event.originalEvent)));
    byUser = false;
  });
}

function fit(map, bbox, animate) {
  const narrow = map.getContainer().clientWidth < 600;
  const padding = narrow
    ? { top: 56, bottom: 72, left: 20, right: 20 }
    : { top: 72, bottom: 64, left: 48, right: 48 };
  map.fitBounds(
    [
      [bbox[0], bbox[1]],
      [bbox[2], bbox[3]],
    ],
    { padding, maxZoom: FIT_MAX_ZOOM, duration: animate ? 600 : 0 },
  );
}

/**
 * Hover and clicks on outlines, grid cells and sheets. The tooltip follows
 * the pointer without a render; content changes only with the feature.
 *
 * @returns {{reset: () => void}} Forget the hovered feature (new data).
 */
function bindPointer(map, props, data, { setTip, moveTip, setPick }) {
  const container = map.getCanvasContainer();
  let hovered = null;
  let frame = 0;
  const hover = (next) => {
    const same = hovered && next && hovered.source === next.source && hovered.id === next.id;
    if (hovered && !same) map.setFeatureState(hovered, { hover: false });
    if (next && !same) map.setFeatureState(next, { hover: true });
    hovered = next;
    container.classList.toggle("pointing", Boolean(next));
    return !same;
  };
  const clear = () => {
    cancelAnimationFrame(frame);
    if (hovered) {
      hover(null);
      setTip(null);
    }
  };
  const layers = () => (props.current.gridOn ? ["sheets-fill"] : ["footprints-fill", "cells-fill"]);
  map.on("mousemove", (event) => {
    // Dragging the map or drawing: no hover work on every frame of the move.
    if (props.current.tool || event.originalEvent.buttons || map.isMoving()) {
      clear();
      return;
    }
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const [feature] = map.queryRenderedFeatures(event.point, { layers: layers() });
      if (!feature) {
        clear();
        return;
      }
      if (hover({ source: feature.source, id: feature.id })) {
        const kind = feature.source;
        const list = kind === "footprints" ? data.current.items : kind === "cells" ? data.current.cells : data.current.sheets;
        const item = list[feature.properties.i];
        setTip(item ? { kind, item } : null);
      }
      moveTip(event.point.x, event.point.y);
    });
  });
  map.on("mouseout", clear);
  map.on("movestart", clear);
  map.on("click", (event) => {
    const { tool, gridOn } = props.current;
    if (tool) return;
    if (gridOn) {
      const [sheet] = map.queryRenderedFeatures(event.point, { layers: ["sheets-fill"] });
      const item = sheet && data.current.sheets[sheet.properties.i];
      if (item) props.current.onSheet(item);
      return;
    }
    const [cell] = map.queryRenderedFeatures(event.point, { layers: ["cells-fill"] });
    const found = cell && data.current.cells[cell.properties.i];
    if (found) {
      fit(map, [found.min_lon, found.min_lat, found.max_lon, found.max_lat], true);
      return;
    }
    const indices = [
      ...new Set(
        map
          .queryRenderedFeatures(event.point, { layers: ["footprints-fill"] })
          .map((feature) => feature.properties.i),
      ),
    ];
    const items = indices.map((i) => data.current.items[i]).filter(Boolean);
    if (items.length === 1) props.current.onOpen(items[0]);
    else if (items.length > 1) setPick({ x: event.point.x, y: event.point.y, items });
    else setPick(null);
  });
  return { reset: clear };
}

function DrawHint({ tool, vertices, drawing, onCancel }) {
  return html`<div class="map-hint float-card draw-hint" role="status">
    <span class="map-hint-text">
      <${Icon} name=${tool === "rect" ? "rect" : "poly"} />
      <span>${tool === "rect" ? L.draw.rect : t(L.draw.poly, { count: vertices })}</span>
    </span>
    <span class="map-hint-actions">
      ${tool === "poly"
        ? html`<button type="button" class="btn sm" disabled=${!vertices}
              onClick=${() => drawing.current?.undo()}>${L.draw.undo}</button>
            <button type="button" class="btn sm primary" disabled=${vertices < 3}
              onClick=${() => drawing.current?.finish()}>${L.draw.finish}</button>`
        : null}
      <button type="button" class="btn sm ghost" title=${L.draw.cancel_title}
        onClick=${onCancel}>${L.draw.cancel}</button>
    </span>
  </div>`;
}

/** The file name of a slot path. */
export function slotName(slot) {
  return slot.slice(slot.lastIndexOf("/") + 1);
}

function Tooltip({ tip, describe, box, at }) {
  useLayoutEffect(() => place(box.current, at.current), [tip]);
  const { kind, item } = tip;
  let content;
  if (kind === "cells") {
    content = html`<b>${t(L.tooltip.cell, { count: count(item.count, L.units.outlines) })}</b>
      <div class="muted">${L.tooltip.cell_zoom}</div>`;
  } else if (kind === "sheets") {
    content = html`<b class="mono">${item.sheet}</b><div class="muted">${L.tooltip.sheet_pick}</div>`;
  } else {
    content = html`<b class="mono">${slotName(item.slot)}</b>
      <div>${describe(item)}</div>
      <div class="muted">${[
        item.data_year ? t(L.tooltip.year, { year: item.data_year }) : L.tooltip.no_year,
        item.label,
        item.source ? L.outline_source[item.source] ?? item.source : null,
      ]
        .filter(Boolean)
        .join(" · ")}</div>
      <div class="faint">${L.tooltip.open}</div>`;
  }
  return html`<div class="map-tooltip float-card" ref=${box} aria-hidden="true">${content}</div>`;
}

function PickList({ pick, describe, onClose, onOpen }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    place(ref.current, pick);
    // After the click that opened the list has settled the focus.
    const frame = requestAnimationFrame(() => ref.current?.querySelector("button")?.focus());
    return () => cancelAnimationFrame(frame);
  }, [pick]);
  useEffect(() => {
    const key = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [pick]);
  const shown = pick.items.slice(0, PICK_LIMIT);
  return html`<div class="pick-list float-card" ref=${ref} role="dialog" aria-label=${L.pick.label}>
    <div class="pick-head">
      <b>${t(L.pick.title, { count: count(pick.items.length, T.common.units.files) })}</b>
      <button type="button" class="btn ghost icon-btn" aria-label=${L.pick.close} title=${L.pick.close}
        onClick=${onClose}><${Icon} name="x" /></button>
    </div>
    <ul>
      ${shown.map(
        (item) => html`<li key=${`${item.store}/${item.version}`}>
          <button type="button" class="pick-item" onClick=${() => onOpen(item)}>
            <span class="mono">${slotName(item.slot)}</span>
            <span class="muted">${[describe(item), item.data_year, item.label].filter(Boolean).join(" · ")}</span>
          </button>
        </li>`,
      )}
    </ul>
    ${pick.items.length > shown.length
      ? html`<p class="faint">${t(L.pick.more, { count: count(pick.items.length - shown.length, T.common.units.files) })}</p>`
      : null}
  </div>`;
}

/** Put a floating card next to the pointer, inside the map. */
function place(element, { x, y }) {
  if (!element) return;
  const parent = element.parentElement.getBoundingClientRect();
  const width = element.offsetWidth;
  const height = element.offsetHeight;
  const left = Math.max(8, Math.min(x + 12, parent.width - width - 8));
  const top = Math.max(8, Math.min(y + 12, parent.height - height - 8));
  element.style.left = `${left}px`;
  element.style.top = `${top}px`;
}
