/**
 * The map of the map view (docs/SPEC.md 5.4, 6.3): MapLibre with the
 * basemap, the store's outlines in the view — or, above the limit, their
 * grid — the sheet grid, the area, the drawing tools and the previews
 * (plan v0.2 step 12b): one raster source of the chosen year layer's tiles,
 * a version's tiles or its features, and its outline. In a project's
 * context (step 15) the extents of the project's own files lie over the
 * outlines in a colour of their own; a click opens a file's card. The
 * stations of a station product (plan I8.1) are points, clusters or grid
 * cells of their own layers (map/stations.js) over the area.
 *
 * The view owns the data and passes it in; the map reports moves, drawn
 * shapes and choices. Layers change through `setData` and hover through
 * feature state, so thousands of outlines never pass through Preact; a
 * feature carries only its index into the answer the view gave. Requests of
 * MapLibre to this server's API (preview tiles) carry the session's CSRF
 * header (`transformRequest`); no other address gets it.
 */

import { apiHeaders } from "../api.js";
import { count, int } from "../format.js";
import { T, t } from "../labels/index.js";
import { map as L } from "../labels/map.js";
import { own as O } from "../labels/own.js";
import { GLYPH_FONT, loadMapLibre } from "../maplibre.js";
import { html, Icon, useEffect, useLayoutEffect, useRef, useState } from "../ui.js";
import { startDrawing } from "./draw.js";
import { centerBounds, HOME_BOUNDS, positionParams, viewBounds } from "./geo.js";
import { changeText } from "./own.js";
import {
  addStationLayers,
  cellFeatures,
  closeSpread,
  openCluster,
  STATION_LAYERS,
  stationFeatures,
  StationTip,
} from "./stations.js";
import { loadBasemapSource, mapStyle, setBasemap } from "./style.js";

const EMPTY = { type: "FeatureCollection", features: [] };
const NO_OWN = [];
/** Colours of the neutral theme: store data in the local blue, the area in indigo. */
export const COLORS = {
  footprint: "#1d4ed8",
  cell: "#1d4ed8",
  sheet: "#475467",
  area: "#3730a3",
  draw: "#4f46e5",
  preview: "#ea580c",
  features: "#0d9488",
  own: "#7c3aed",
};
// Raster sources of preview tiles: the chosen year layer, a version.
const LAYER_TILES = "layer-preview";
const VERSION_TILES = "version-preview";
const PREVIEW_TILES = new Set([LAYER_TILES, VERSION_TILES]);
// Preview rasters lie on the outlines' fill, under their lines.
const PREVIEW_ABOVE = "footprints-line";
const POLYGONS = ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]];
const LINES = ["in", ["geometry-type"], ["literal", ["LineString", "MultiLineString"]]];
const POINTS = ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]];
const HOVER = ["boolean", ["feature-state", "hover"], false];
const FIT_MAX_ZOOM = 15;
const PICK_LIMIT = 12;
// The tooltip of a feature of these sources: a station (map/stations.js `StationTip`).
const TIP_KINDS = { stations: "station", "station-spread": "station" };

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
  for (const id of ["cells", "footprints", "own", "preview-features", "preview-outline", "sheets", "area", "draw"]) {
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
      // The extents of a project's own files, over the store's outlines.
      id: "own-fill",
      type: "fill",
      source: "own",
      paint: { "fill-color": COLORS.own, "fill-opacity": ["case", HOVER, 0.3, 0.08] },
    },
    {
      id: "own-line",
      type: "line",
      source: "own",
      paint: { "line-color": COLORS.own, "line-width": ["case", HOVER, 2.6, 1.6] },
    },
    {
      id: "preview-features-fill",
      type: "fill",
      source: "preview-features",
      filter: POLYGONS,
      paint: { "fill-color": COLORS.features, "fill-opacity": 0.22 },
    },
    {
      id: "preview-features-line",
      type: "line",
      source: "preview-features",
      filter: ["any", POLYGONS, LINES],
      paint: { "line-color": COLORS.features, "line-width": 1.4 },
    },
    {
      id: "preview-features-points",
      type: "circle",
      source: "preview-features",
      filter: POINTS,
      paint: {
        "circle-radius": 3.5,
        "circle-color": COLORS.features,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1,
      },
    },
    {
      id: "preview-outline",
      type: "line",
      source: "preview-outline",
      paint: { "line-color": COLORS.preview, "line-width": 2.4 },
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
 * @property {(zoom: number, bounds?: number[]|null) => void} zoomTo - Zoom in or
 *   out; outside `bounds` (WGS84) also move to their centre.
 * @property {() => number[]} bounds - The visible box (WGS84).
 * @property {() => number} width - Width of the map in px.
 */

/**
 * A move of the map, reported when it ends.
 *
 * @typedef {object} MapMove
 * @property {number[]} bbox - The visible box (WGS84).
 * @property {number} width - Width of the map in px.
 * @property {number} zoom - MapLibre's zoom (512 px tiles).
 * @property {{center?: string, zoom?: string}} position - For the address; none
 *   for a map that cannot be drawn.
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
 * @param {object|null} [props.layerTiles] - Raster source of the chosen year
 *   layer (map/previews.js `layerTiles`).
 * @param {object|null} [props.versionTiles] - Raster source of the version
 *   shown (`versionTiles`).
 * @param {import("../types.js").Geometry|null} [props.previewOutline] - Outline of
 *   the version shown.
 * @param {import("../types.js").PreviewFeatures|null} [props.previewFeatures] -
 *   Features of the vector shown in the view.
 * @param {import("../types.js").OwnFileItem[]} [props.own] - Own files of the
 *   project in context, with their `outline` (map/own.js `useOwnLayer`).
 * @param {(item: import("../types.js").OwnFileItem) => void} [props.onOwn] - An
 *   own file's extent chosen: open its card.
 * @param {import("../types.js").StationMapView|undefined} [props.stations] - The
 *   stations of the view (a station product), or their grid.
 * @param {string|null} [props.stationColor] - Key of the "Kolor punktów"
 *   variable: the state of a point's image (none: unknown).
 * @param {(item: import("../types.js").StationPoint) => void} [props.onStation] -
 *   A station's point chosen: open its card.
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
  layerTiles = null,
  versionTiles = null,
  previewOutline = null,
  previewFeatures = null,
  own = NO_OWN,
  onOwn = null,
  stations = undefined,
  stationColor = null,
  onStation = null,
  children,
}) {
  const box = useRef(null);
  const [map, setMap] = useState(null);
  const [failure, setFailure] = useState(null);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [tip, setTip] = useState(null);
  const [pick, setPick] = useState(null);
  const [vertices, setVertices] = useState(0);
  const drawing = useRef(null);
  const data = useRef({ items: [], cells: [], sheets: [], own: [], stations: [], stationCells: [], spread: [] });
  const pointer = useRef(null);
  const tipBox = useRef(null);
  const tipAt = useRef({ x: 0, y: 0 });
  const props = useRef({});
  props.current = {
    onMove,
    onDrawn,
    onCancel,
    onSheet,
    onOpen,
    onOwn,
    describe,
    tool,
    stationColor,
    onStation,
    gridOn: sheets.length > 0,
  };
  const basemapKey = basemap ? JSON.stringify(basemap) : "";
  const shownBasemap = useRef(basemapKey);
  const layerKey = layerTiles ? JSON.stringify(layerTiles) : "";
  const versionKey = versionTiles ? JSON.stringify(versionTiles) : "";

  useEffect(() => {
    let live = true;
    let created = null;
    Promise.all([
      loadMapLibre(),
      loadBasemapSource(basemap).catch(() => {
        if (live) setBasemapFailed(true);
        return null;
      }),
    ])
      .then(([maplibre, source]) => {
        if (!live) return;
        const narrow = box.current.clientWidth < 600;
        created = new maplibre.Map({
          container: box.current,
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
          // Without a listener MapLibre logs to the console; a basemap or a
          // preview tile that does not answer is said in a note instead.
          if (event.sourceId === "basemap") setBasemapFailed(true);
          else if (PREVIEW_TILES.has(event.sourceId)) setPreviewFailed(true);
          else setFailure(event.error ?? event);
        });
        created.once("load", () => {
          if (!live) return;
          addDataLayers(created);
          addStationLayers(created, "draw-fill");
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
            zoomTo: (zoom, bounds = null) => zoomTo(created, zoom, bounds),
            bounds: () => viewBounds(created),
            width: () => created.getContainer().clientWidth,
          });
          props.current.onMove?.(move(created, false));
        });
      })
      // A browser that cannot draw the map (no WebGL2) throws while it is
      // created; the view still counts what the map would show.
      .catch((error) => {
        if (!live) return;
        setFailure(error);
        props.current.onMove?.(stillMove(box.current, start));
      });
    return () => {
      live = false;
      created?.remove();
    };
  }, []);

  useEffect(() => {
    if (!map || shownBasemap.current === basemapKey) return;
    shownBasemap.current = basemapKey;
    let live = true;
    loadBasemapSource(basemap).then(
      (source) => {
        if (!live) return;
        setBasemapFailed(false);
        setBasemap(map, basemap, source);
      },
      () => {
        if (!live) return;
        setBasemapFailed(true);
        setBasemap(map, null, null);
      },
    );
    return () => { live = false; };
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

  useEffect(() => {
    if (!map) return;
    setPreviewFailed(false);
    // The version's tiles lie above the layer's.
    setRaster(map, LAYER_TILES, layerTiles, map.getLayer(VERSION_TILES) ? VERSION_TILES : PREVIEW_ABOVE);
  }, [map, layerKey]);

  useEffect(() => {
    if (!map) return;
    setPreviewFailed(false);
    setRaster(map, VERSION_TILES, versionTiles, PREVIEW_ABOVE);
  }, [map, versionKey]);

  useEffect(() => {
    if (!map) return;
    map.getSource("preview-outline").setData(
      previewOutline ? { type: "Feature", properties: {}, geometry: previewOutline } : EMPTY,
    );
  }, [map, previewOutline]);

  useEffect(() => {
    if (!map) return;
    map.getSource("preview-features").setData(previewFeatures ?? EMPTY);
  }, [map, previewFeatures]);

  useEffect(() => {
    if (!map) return;
    data.current.own = own;
    map.getSource("own").setData(
      features(
        own.map((item) => ({ geometry: item.outline, change: item.change })),
        (item) => ({ change: item.change }),
      ),
    );
    pointer.current?.reset();
  }, [map, own]);

  useEffect(() => {
    if (!map) return;
    const aggregated = Boolean(stations?.aggregated);
    data.current.stations = stations && !aggregated ? stations.items : [];
    data.current.stationCells = stations && aggregated ? stations.cells : [];
    map.getSource("stations").setData(stationFeatures(data.current.stations, stationColor));
    map.getSource("station-cells").setData(cellFeatures(data.current.stationCells));
    pointer.current?.closeSpread();
    pointer.current?.reset();
  }, [map, stations, stationColor]);

  // `Esc` folds the stations spread around a cluster.
  useEffect(() => {
    if (!map) return undefined;
    const key = (event) => {
      if (event.key === "Escape") pointer.current?.closeSpread();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [map]);

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
    ${tip && !tool
      ? html`<${Tooltip} tip=${tip} describe=${describe} variable=${stationColor} box=${tipBox} at=${tipAt} />`
      : null}
    ${pick && !tool
      ? html`<${PickList} pick=${pick} describe=${describe} onClose=${() => setPick(null)}
          onOpen=${(item) => {
            setPick(null);
            choose(props, item);
          }} />`
      : null}
    ${children}
    ${basemapFailed || previewFailed
      ? html`<p class="map-note float-card" role="status">
          ${basemapFailed ? html`<span>${L.canvas.basemap_failed}</span>` : null}
          ${previewFailed ? html`<span>${L.canvas.preview_failed}</span>` : null}
        </p>`
      : null}
  </div>`;
}

function move(map, byUser) {
  return {
    bbox: viewBounds(map),
    width: map.getContainer().clientWidth,
    zoom: map.getZoom(),
    position: positionParams(map),
    byUser,
  };
}

/**
 * The move of a map that cannot be drawn: the address's position, else the
 * home view, at the size of its box (no position for the address).
 */
function stillMove(container, start) {
  const width = container.clientWidth;
  const height = container.clientHeight;
  const bbox = start && width && height ? centerBounds(start.center, start.zoom, width, height) : HOME_BOUNDS;
  return { bbox, width, zoom: start?.zoom ?? 0, position: {}, byUser: false };
}

/**
 * Show a raster source of preview tiles in the place of the previous one
 * (its tiles' address changes with every preview that gets ready), or none.
 *
 * @param {*} map
 * @param {string} id - The source and its layer.
 * @param {object|null} source - MapLibre raster source.
 * @param {string} before - The layer it lies under.
 */
function setRaster(map, id, source, before) {
  if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(id)) map.removeSource(id);
  if (!source) return;
  map.addSource(id, source);
  map.addLayer({ id, type: "raster", source: id, paint: { "raster-fade-duration": 150 } }, before);
}

function zoomTo(map, zoom, bounds) {
  const { lng, lat } = map.getCenter();
  const inside = !bounds || (lng >= bounds[0] && lng <= bounds[2] && lat >= bounds[1] && lat <= bounds[3]);
  const center = inside ? undefined : [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2];
  map.easeTo({ zoom, ...(center ? { center } : {}), duration: 600 });
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
 * Hover and clicks on outlines, grid cells, sheets and stations. The tooltip
 * follows the pointer without a render; content changes only with the
 * feature.
 *
 * @returns {{reset: () => void, closeSpread: () => void}} Forget the hovered
 *   feature (new data); fold the stations spread around a cluster.
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
  const layers = () =>
    props.current.gridOn ? ["sheets-fill"] : [...STATION_LAYERS, "own-fill", "footprints-fill", "cells-fill"];
  const lists = {
    footprints: "items",
    cells: "cells",
    own: "own",
    sheets: "sheets",
    stations: "stations",
    "station-spread": "spread",
    "station-cells": "stationCells",
  };
  const tipOf = (feature) => {
    if (feature.properties.cluster) {
      return { kind: "station-cluster", item: { count: feature.properties.point_count } };
    }
    const item = (data.current[lists[feature.source]] ?? [])[feature.properties.i];
    return item ? { kind: TIP_KINDS[feature.source] ?? feature.source, item } : null;
  };
  const fold = () => {
    if (!data.current.spread.length) return;
    data.current.spread = [];
    closeSpread(map);
    if (hovered?.source === "station-spread") clear();
  };
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
      if (hover({ source: feature.source, id: feature.id })) setTip(tipOf(feature));
      moveTip(event.point.x, event.point.y);
    });
  });
  map.on("mouseout", clear);
  map.on("movestart", clear);
  // The spread is laid out in pixels of its zoom.
  map.on("zoomstart", fold);
  map.on("click", (event) => {
    const { tool, gridOn } = props.current;
    if (tool) return;
    if (gridOn) {
      const [sheet] = map.queryRenderedFeatures(event.point, { layers: ["sheets-fill"] });
      const item = sheet && data.current.sheets[sheet.properties.i];
      if (item) props.current.onSheet(item);
      return;
    }
    // A station's point opens its card; the next click folds a spread.
    const [station] = map.queryRenderedFeatures(event.point, { layers: STATION_LAYERS });
    const point =
      station && !station.properties.cluster && station.source !== "station-cells"
        ? (data.current[lists[station.source]] ?? [])[station.properties.i]
        : null;
    fold();
    if (station?.source === "station-cells") {
      const cell = data.current.stationCells[station.properties.i];
      if (cell) fit(map, [cell.min_lon, cell.min_lat, cell.max_lon, cell.max_lat], true);
      return;
    }
    if (station?.properties.cluster) {
      const items = data.current.stations;
      openCluster(map, station, items, props.current.stationColor).then(
        (spread) => {
          if (!spread) return;
          if (data.current.stations === items) data.current.spread = spread;
          else closeSpread(map);
        },
        () => {
          // New stations came while the worker looked the cluster up: it is gone.
        },
      );
      return;
    }
    if (station) {
      if (point) props.current.onStation?.(point);
      return;
    }
    const [cell] = map.queryRenderedFeatures(event.point, { layers: ["cells-fill"] });
    const found = cell && data.current.cells[cell.properties.i];
    if (found) {
      fit(map, [found.min_lon, found.min_lat, found.max_lon, found.max_lat], true);
      return;
    }
    const under = (layer, list) => [
      ...new Set(map.queryRenderedFeatures(event.point, { layers: [layer] }).map((feature) => feature.properties.i)),
    ]
      .map((i) => list[i])
      .filter(Boolean);
    // An own file's extent lies over the outlines: it is listed first.
    const own = under("own-fill", data.current.own).map((item) => ({ own: item }));
    const items = [...own, ...under("footprints-fill", data.current.items)];
    if (items.length === 1) choose(props, items[0]);
    else if (items.length > 1) setPick({ x: event.point.x, y: event.point.y, items });
    else setPick(null);
  });
  return { reset: clear, closeSpread: fold };
}

/** Open what a click chose: an own file's card, else a file's card. */
function choose(props, item) {
  if (item.own) props.current.onOwn?.(item.own);
  else props.current.onOpen(item);
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

function Tooltip({ tip, describe, variable, box, at }) {
  useLayoutEffect(() => place(box.current, at.current), [tip]);
  const { kind, item } = tip;
  let content;
  if (kind.startsWith("station")) {
    content = html`<${StationTip} tip=${tip} variable=${variable} />`;
  } else if (kind === "cells") {
    content = html`<b>${t(L.tooltip.cell, { count: count(item.count, L.units.outlines) })}</b>
      <div class="muted">${L.tooltip.cell_zoom}</div>`;
  } else if (kind === "sheets") {
    content = html`<b class="mono">${item.sheet}</b><div class="muted">${L.tooltip.sheet_pick}</div>`;
  } else if (kind === "own") {
    content = html`<b class="mono">${slotName(item.path)}</b>
      <div>${t(O.map.tooltip, { change: changeText(item) })}</div>
      <div class="faint">${O.map.tooltip_open}</div>`;
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
  // Before paint, like the drawing hint: the list is never shown without Esc
  // closing it (an effect runs only after the next frame of the map).
  useLayoutEffect(() => {
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
      ${shown.map((item) =>
        item.own
          ? html`<li key=${`own/${item.own.file_id}`}>
              <button type="button" class="pick-item" onClick=${() => onOpen(item)}>
                <span class="mono">${slotName(item.own.path)}</span>
                <span class="muted">${t(O.map.tooltip, { change: changeText(item.own) })}</span>
              </button>
            </li>`
          : html`<li key=${`${item.store}/${item.version}`}>
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
