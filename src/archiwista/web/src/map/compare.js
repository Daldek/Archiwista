/**
 * The comparison map (docs/SPEC.md 8.5, level 2; plan v0.2 decision 10,
 * step 14): two MapLibre maps, of sides A and B, always at one position —
 * moving either moves the other — shown in one of three ways:
 *
 * - `curtain` (the default): B over A, cut away left of the curtain by a
 *   `clip-path` the stylesheet takes from `--split`, a custom property set
 *   from JS (CSSOM, so within `style-src 'self'`). The handle is a WAI-ARIA
 *   slider moved by a mouse or a finger (pointer events) and by the arrows.
 *   Where B is cut away the pointer reaches A, so either map moves both.
 * - `fade`: B over A, its picture as opaque as the slider says (`--fade`).
 * - `side`: the two maps next to each other (one above the other on a
 *   phone).
 *
 * Each map shows its side's preview tiles (a raster source of
 * map/previews.js or `sideTiles`), a vector's features and the outline.
 * MapLibre sends the session's CSRF header to this server's API only
 * (`transformRequest` through `apiHeaders`, as map/canvas.js does).
 */

import { apiHeaders, apiTemplate } from "../api.js";
import { compare as L } from "../labels/compare.js";
import { t } from "../labels/index.js";
import { map as M } from "../labels/map.js";
import { loadMapLibre } from "../maplibre.js";
import { html, useEffect, useRef, useState } from "../ui.js";
import { COLORS } from "./canvas.js";
import { HOME_BOUNDS, positionParams, viewBounds } from "./geo.js";
import { versionTiles } from "./previews.js";
import { loadBasemapSource, mapStyle } from "./style.js";

/** How the two sides are shown (`mode` of the address); the first is the default. */
export const MODES = ["curtain", "fade", "side"];
/** The sides, in their order. */
export const SIDES = ["a", "b"];

const EMPTY = { type: "FeatureCollection", features: [] };
// Sources and layers of each map: the side's tiles, features and outline.
const TILES = "side-tiles";
const FEATURES = "side-features";
const OUTLINE = "side-outline";
const POLYGONS = ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]];
const LINES = ["in", ["geometry-type"], ["literal", ["LineString", "MultiLineString"]]];
const POINTS = ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]];
const FIT_MAX_ZOOM = 15;
// Steps of the curtain's arrows, in percent of the map's width.
const STEP = 1;
const STEP_BIG = 10;

/**
 * What one map shows.
 *
 * @typedef {object} MapSide
 * @property {string} name - Short name on the map (e.g. the version's label).
 * @property {string} title - Its full name (the tooltip).
 * @property {object|null} tiles - A raster source (`sideTiles`, `layerTiles`).
 * @property {import("../types.js").Geometry|null} outline - WGS84.
 * @property {import("../types.js").PreviewFeatures|null} features - A vector's, in
 *   the view.
 */

/**
 * The imperative side of the comparison map: both maps follow.
 *
 * @typedef {object} CompareApi
 * @property {(bbox: number[], options?: {animate?: boolean}) => void} fit
 * @property {(zoom: number, bounds?: number[]|null) => void} zoomTo - Outside
 *   `bounds` (WGS84) also move to their centre.
 */

/**
 * The styles both sides can be shown in, in A's order.
 *
 * @param {Array<import("../types.js").PreviewInfo|null>} infos - A and B.
 * @returns {string[]} Empty unless both previews are known.
 */
export function sharedStyles(infos) {
  if (!infos.every(Boolean)) return [];
  return infos[0].styles.filter((style) => infos[1].styles.includes(style));
}

/**
 * One range of a colour ramp for both sides — from the lower minimum to the
 * higher maximum of their legends in a style — so that equal colours mean
 * equal values on both maps.
 *
 * @param {Array<import("../types.js").PreviewInfo|null>} infos - A and B.
 * @param {string|null} style
 * @returns {{rescale: number[], legend: import("../types.js").GradientLegend}|null}
 *   Null unless both sides have a ramp of one unit in the style.
 */
export function commonScale(infos, style) {
  const legends = infos.map((info) => (style ? (info?.legends?.[style] ?? null) : null));
  if (!legends.every((legend) => legend?.kind === "gradient")) return null;
  if (legends[0].unit !== legends[1].unit) return null;
  const low = Math.min(...legends.map((legend) => legend.min));
  const high = Math.max(...legends.map((legend) => legend.max));
  if (!(Number.isFinite(low) && Number.isFinite(high) && low < high)) return null;
  return { rescale: [low, high], legend: { ...legends[0], min: low, max: high } };
}

/**
 * The raster source of a side's tiles in a style; with `rescale`, its colour
 * ramp spans that range instead of the file's own (`commonScale`).
 *
 * @param {import("../types.js").PreviewInfo|null} info
 * @param {string|null} style
 * @param {number[]|null} [rescale] - Low and high value.
 * @returns {object|null} A MapLibre source; null without tiles to show.
 */
export function sideTiles(info, style, rescale = null) {
  const source = versionTiles(info, style);
  if (!source || !rescale) return source;
  return { ...source, tiles: [apiTemplate(info.tiles_url, { style, rescale: rescale.join(",") })] };
}

/**
 * The two maps of a comparison at one position, in one of the `MODES`.
 *
 * @param {object} props
 * @param {import("../types.js").BasemapSettings|null} props.basemap
 * @param {{center: [number, number], zoom: number}|null} props.start - Position of
 *   the address; else the home view until the view frames the sides.
 * @param {"curtain"|"fade"|"side"} props.mode
 * @param {MapSide[]} props.sides - A and B.
 * @param {(api: CompareApi) => void} props.onReady
 * @param {(move: import("./canvas.js").MapMove) => void} props.onMove - A move of
 *   either map, when it ends.
 * @param {*} [props.children] - Overlays over both maps (notes, legend).
 */
export function CompareMaps({ basemap, start, mode, sides, onReady, onMove, children }) {
  const boxes = [useRef(null), useRef(null)];
  const [maps, setMaps] = useState(null);
  const [failure, setFailure] = useState(null);
  const [notes, setNotes] = useState({ basemap: false, tiles: false });
  // The curtain's place and B's opacity, in percent: how the person looks,
  // not what is compared — they stay off the address.
  const [split, setSplit] = useState(50);
  const [fade, setFade] = useState(50);
  const props = useRef({});
  props.current = { onReady, onMove };

  useEffect(() => {
    let live = true;
    let created = [];
    let unsync = null;
    Promise.all([
      loadMapLibre(),
      loadBasemapSource(basemap).catch(() => {
        if (live) setNotes((current) => ({ ...current, basemap: true }));
        return null;
      }),
    ])
      .then(([maplibre, source]) => {
        if (!live) return;
        created = SIDES.map((side, index) =>
          makeMap(maplibre, boxes[index].current, { side, basemap, source, start, setNotes, setFailure }),
        );
        Promise.all(created.map((map) => new Promise((resolve) => map.once("load", resolve)))).then(() => {
          if (!live) return;
          for (const map of created) addSideLayers(map);
          unsync = syncMaps(created, (map, byUser) => props.current.onMove?.(moveOf(map, byUser)));
          setMaps(created);
          props.current.onReady?.({
            fit: (bbox, { animate = true } = {}) => fit(created[0], bbox, animate),
            zoomTo: (zoom, bounds = null) => zoomTo(created[0], zoom, bounds),
          });
          props.current.onMove?.(moveOf(created[0], false));
        });
      })
      // A browser that cannot draw the maps (no WebGL2) throws while they are created.
      .catch((error) => live && setFailure(error));
    return () => {
      live = false;
      unsync?.();
      for (const map of created) map.remove();
    };
  }, []);

  const style = { "--split": `${split}%`, "--fade": String(fade / 100) };
  return html`<div class=${`cmp-stage ${mode}`} style=${style}>
    ${SIDES.map(
      (side, index) => html`<div key=${side} class=${`cmp-pane ${side}`}>
        <div class="cmp-gl" ref=${boxes[index]}></div>
      </div>`,
    )}
    ${maps
      ? SIDES.map(
          (side, index) => html`<${PaneData} key=${side} map=${maps[index]} side=${sides[index]}
            onTiles=${() => setNotes((current) => (current.tiles ? { ...current, tiles: false } : current))} />`,
        )
      : null}
    ${SIDES.map(
      (side, index) => html`<span key=${side} class=${`cmp-badge ${side}`} title=${sides[index].title}>
        <b class=${`cmp-letter ${side}`}>${L.side[side]}</b><span class="cmp-badge-name">${sides[index].name}</span>
      </span>`,
    )}
    ${mode === "curtain" ? html`<${CurtainHandle} value=${split} onChange=${setSplit} />` : null}
    ${mode === "fade" ? html`<${FadeSlider} value=${fade} onChange=${setFade} />` : null}
    ${children}
    ${failure
      ? html`<p class="map-failure float-card" role="alert">
          ${t(L.map.failed, { message: failure.message ?? String(failure) })}</p>`
      : null}
    ${notes.basemap || notes.tiles
      ? html`<p class="map-note float-card" role="status">
          ${notes.basemap ? html`<span>${M.canvas.basemap_failed}</span>` : null}
          ${notes.tiles ? html`<span>${M.canvas.preview_failed}</span>` : null}
        </p>`
      : null}
  </div>`;
}

/** How opaque B's picture is over A's, in percent. */
function FadeSlider({ value, onChange }) {
  return html`<div class="cmp-fade float-card">
    <span aria-hidden="true">${L.map.fade}</span>
    <input type="range" min="0" max="100" step="1" value=${value} aria-label=${L.map.fade}
      aria-valuetext=${t(L.map.fade_value, { percent: value })}
      onInput=${(event) => onChange(Number(event.currentTarget.value))} />
    <output class="tabular" aria-hidden="true">${t(L.map.fade_value, { percent: value })}</output>
  </div>`;
}

/** What one map shows, kept up to date (renders nothing). */
function PaneData({ map, side, onTiles }) {
  const tilesKey = side.tiles ? JSON.stringify(side.tiles) : "";
  useEffect(() => {
    onTiles();
    setRaster(map, side.tiles);
  }, [map, tilesKey]);
  useEffect(() => {
    map.getSource(OUTLINE).setData(side.outline ? { type: "Feature", properties: {}, geometry: side.outline } : EMPTY);
  }, [map, side.outline]);
  useEffect(() => {
    map.getSource(FEATURES).setData(side.features ?? EMPTY);
  }, [map, side.features]);
  return null;
}

/**
 * The curtain's handle: a slider of its place in percent of the width, from
 * the left — A left of it, B right of it.
 */
function CurtainHandle({ value, onChange }) {
  const dragged = useRef(null);
  const place = (event) => {
    const box = event.currentTarget.parentElement.getBoundingClientRect();
    if (box.width > 0) onChange(clamp(((event.clientX - box.left) / box.width) * 100));
  };
  const down = (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.focus();
    dragged.current = event.pointerId;
  };
  const move = (event) => {
    if (dragged.current === event.pointerId) place(event);
  };
  const up = (event) => {
    if (dragged.current === event.pointerId) dragged.current = null;
  };
  const key = (event) => {
    const step = event.shiftKey ? STEP_BIG : STEP;
    const next = {
      ArrowLeft: value - step,
      ArrowDown: value - step,
      ArrowRight: value + step,
      ArrowUp: value + step,
      PageDown: value - STEP_BIG,
      PageUp: value + STEP_BIG,
      Home: 0,
      End: 100,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    onChange(clamp(next));
  };
  const shown = Math.round(value);
  return html`<div class="cmp-handle" role="slider" tabindex="0" aria-label=${L.map.curtain}
    aria-orientation="horizontal" aria-valuemin="0" aria-valuemax="100" aria-valuenow=${shown}
    aria-valuetext=${t(L.map.curtain_value, { a: shown, b: 100 - shown })} title=${L.map.curtain_title}
    onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up} onKeyDown=${key}>
    <span class="cmp-grip" aria-hidden="true">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round" focusable="false"><path d="m9 6-6 6 6 6m6-12 6 6-6 6" /></svg>
    </span>
  </div>`;
}

/** A map of one side: the basemap, controls, and the API's header for tiles. */
function makeMap(maplibre, container, { side, basemap, source, start, setNotes, setFailure }) {
  const map = new maplibre.Map({
    container,
    style: mapStyle(basemap, source),
    ...(start
      ? { center: start.center, zoom: start.zoom }
      : { bounds: HOME_BOUNDS, fitBoundsOptions: { padding: 16 } }),
    attributionControl: false,
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
    maxPitch: 0,
    renderWorldCopies: false,
    // Preview tiles of the API need the session's header; nothing else gets it.
    transformRequest: (url) => {
      const headers = apiHeaders(url);
      return headers ? { url, headers } : undefined;
    },
    locale: {
      "Map.Title": t(L.map.title, { side: L.side[side] }),
      "NavigationControl.ZoomIn": M.canvas.zoom_in,
      "NavigationControl.ZoomOut": M.canvas.zoom_out,
      "NavigationControl.ResetBearing": M.canvas.reset_bearing,
      "AttributionControl.ToggleAttribution": M.canvas.attribution,
    },
  });
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  // The same controls in the same place on both maps: the one on top takes
  // the clicks, and either moves both.
  map.addControl(new maplibre.AttributionControl({ compact: true }), "bottom-right");
  map.addControl(new maplibre.NavigationControl({ showCompass: false }), "bottom-right");
  map.addControl(new maplibre.ScaleControl({ unit: "metric" }), "bottom-right");
  map.on("error", (event) => {
    // Without a listener MapLibre logs to the console; a basemap or a preview
    // tile that does not answer is said in a note instead.
    if (event.sourceId === "basemap") setNotes((current) => ({ ...current, basemap: true }));
    else if (event.sourceId === TILES) setNotes((current) => ({ ...current, tiles: true }));
    else setFailure(event.error ?? event);
  });
  return map;
}

/** Sources and layers of a side's features and outline (its tiles come later, under them). */
function addSideLayers(map) {
  for (const id of [FEATURES, OUTLINE]) map.addSource(id, { type: "geojson", data: EMPTY });
  map.addLayer({
    id: `${FEATURES}-fill`,
    type: "fill",
    source: FEATURES,
    filter: POLYGONS,
    paint: { "fill-color": COLORS.features, "fill-opacity": 0.22 },
  });
  map.addLayer({
    id: `${FEATURES}-line`,
    type: "line",
    source: FEATURES,
    filter: ["any", POLYGONS, LINES],
    paint: { "line-color": COLORS.features, "line-width": 1.4 },
  });
  map.addLayer({
    id: `${FEATURES}-points`,
    type: "circle",
    source: FEATURES,
    filter: POINTS,
    paint: { "circle-radius": 3.5, "circle-color": COLORS.features, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1 },
  });
  map.addLayer({ id: OUTLINE, type: "line", source: OUTLINE, paint: { "line-color": COLORS.preview, "line-width": 2.4 } });
}

/**
 * Show a side's raster source in the place of the previous one (its tiles'
 * address changes with every preview that gets ready), or none.
 */
function setRaster(map, source) {
  if (map.getLayer(TILES)) map.removeLayer(TILES);
  if (map.getSource(TILES)) map.removeSource(TILES);
  if (!source) return;
  map.addSource(TILES, source);
  map.addLayer({ id: TILES, type: "raster", source: TILES, paint: { "raster-fade-duration": 150 } }, `${FEATURES}-fill`);
}

/**
 * Keep maps at one position: a move of any of them is copied to the others
 * at once (`jumpTo`), never back.
 *
 * @param {Array<*>} maps - MapLibre maps.
 * @param {(map: *, byUser: boolean) => void} onEnd - A move ended (not a copy).
 * @returns {() => void} Stops it.
 */
function syncMaps(maps, onEnd) {
  let copying = false;
  const bound = maps.map((map) => {
    let byUser = false;
    const started = (event) => {
      if (!copying) byUser = Boolean(event.originalEvent);
    };
    const moved = () => {
      if (copying) return;
      copying = true;
      const view = { center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() };
      for (const other of maps) if (other !== map) other.jumpTo(view);
      copying = false;
    };
    const ended = (event) => {
      if (copying) return;
      onEnd(map, byUser || Boolean(event.originalEvent));
      byUser = false;
    };
    map.on("movestart", started);
    map.on("move", moved);
    map.on("moveend", ended);
    return () => {
      map.off("movestart", started);
      map.off("move", moved);
      map.off("moveend", ended);
    };
  });
  return () => {
    for (const off of bound) off();
  };
}

function moveOf(map, byUser) {
  return {
    bbox: viewBounds(map),
    width: map.getContainer().clientWidth,
    zoom: map.getZoom(),
    position: positionParams(map),
    byUser,
  };
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

function zoomTo(map, zoom, bounds) {
  const { lng, lat } = map.getCenter();
  const inside = !bounds || (lng >= bounds[0] && lng <= bounds[2] && lat >= bounds[1] && lat <= bounds[3]);
  const center = inside ? undefined : [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2];
  map.easeTo({ zoom, ...(center ? { center } : {}), duration: 600 });
}

function clamp(value) {
  return Math.min(100, Math.max(0, value));
}
