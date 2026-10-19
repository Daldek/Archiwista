/**
 * „Mapa” — the start view (docs/SPEC.md 6.1–6.3, plan v0.1 step 10b, v0.2
 * step 12b).
 *
 * The left panel „Wybór” holds the area, the product of the index with the
 * filters and the area's local state; the centre is the map of the store's
 * outlines in the view (`/map/footprints`: up to 5000, above that their
 * grid) with the sheet grid (`/map/sheets`) and the drawing tools. Files
 * without an outline never go on the map: their counter opens the catalog
 * with the same filters. With an area and a product, the product's year
 * layers in the area are buttons on the map: the chosen one shows the
 * outlines of its versions and its preview tiles (map/previews.js); a
 * version's preview from its file card goes on the map with its outline.
 * The address holds the state — filters under the `/slots` names,
 * `area_id`, the chosen layer (`layer`), the version previewed (`preview`
 * and `preview_style`) and the position as `center=lon,lat` and `zoom`;
 * without a position the map frames the preview, else what the filters
 * match.
 */

import {
  ApiError,
  createArea,
  getArea,
  getVersion,
  listFootprints,
  listProducts,
  listSheets,
  listSlots,
  uploadArea,
} from "../api.js";
import { useApp } from "../context.js";
import { count, stamp } from "../format.js";
import { NARROW, useMedia, useResource } from "../hooks.js";
import { T, t } from "../labels/index.js";
import { map as L } from "../labels/map.js";
import { MapCanvas } from "../map/canvas.js";
import {
  bboxPolygon,
  bboxText,
  geometryBounds,
  readPosition,
  unionBounds,
  WORLD_BOUNDS,
} from "../map/geo.js";
import { Legend } from "../map/legend.js";
import { areaName, areaSummary, SelectionPanel } from "../map/panel.js";
import {
  chosenStyle,
  LAYER_PARAM,
  LayerButtons,
  LayerLegend,
  layerTiles,
  PREVIEW_PARAM,
  PREVIEW_STYLE_PARAM,
  readVersionRef,
  shownFrom,
  tilesShown,
  useFeatures,
  useLayerLegend,
  useLayers,
  useVersionPreview,
  VersionLegend,
  versionTiles,
  ZoomHint,
} from "../map/previews.js";
import { productNames, productStores } from "../map/products.js";
import { DEFAULT_GRID, GRID_PRODUCER, scaleLabel } from "../map/sheets.js";
import { availableBasemaps, chosenBasemap, keepBasemap, pickBasemap } from "../map/style.js";
import { ViewLayout } from "../panels.js";
import { Link, setParams } from "../router.js";
import {
  html,
  Icon,
  loadStylesheet,
  ProblemView,
  Spinner,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "../ui.js";

await loadStylesheet(new URL("../map/map.css", import.meta.url));

/** Address parameters that filter the map: the `/slots` names. */
export const FILTERS = ["store", "product", "country", "years", "unit", "versions", "status", "q"];
/** Most outlines drawn one by one; above it the view is a grid (`/map/footprints`). */
const FOOTPRINT_LIMIT = 5000;
/** Width of a grid cell on the screen, px. */
const CELL_PX = 56;
/** Grid columns of the query framing the data at the start. */
const FRAME_COLUMNS = 512;
const MOVE_DEBOUNCE_MS = 150;
const NO_SHEETS = { items: [], status: null, problem: null, loading: false };

/** Areas this page saved or read, by id: no second request after saving. */
const areas = new Map();

/**
 * The map view.
 *
 * @param {{route: import("../router.js").Route}} props
 */
export default function MapScreen({ route }) {
  const { settings, health } = useApp();
  const narrow = useMedia(NARROW);
  const params = route.params;
  const filtersKey = FILTERS.map((name) => params[name] ?? "").join("\n");
  const filters = useMemo(() => readFilters(params), [filtersKey]);
  const areaId = params.area_id || null;
  const [start] = useState(() => readPosition(params));
  const [mapApi, setMapApi] = useState(null);
  const [leftOpen, setLeftOpen] = useState(() => !window.matchMedia(NARROW).matches);
  const [tool, setTool] = useState(null);
  const [grid, setGrid] = useState({ on: false, ...DEFAULT_GRID });
  const [move, setMove] = useState(null);
  const [round, setRound] = useState(0);
  const [areaBusy, setAreaBusy] = useState(false);
  const [areaProblem, setAreaProblem] = useState(null);
  const [areaNote, setAreaNote] = useState(null);
  const [fileLayers, setFileLayers] = useState(null);
  const [basemapName, setBasemapName] = useState(chosenBasemap);
  const areaStep = useRef(null);
  const userMoved = useRef(false);

  const stores = settings?.stores ?? [];
  const indexKey = (health?.stores ?? []).map((item) => `${item.store}:${item.state.indexed_at ?? ""}`).join(",");
  const basemaps = availableBasemaps(settings);
  const basemap = settings ? pickBasemap(basemaps, basemapName) : null;

  const products = useResource(
    (signal) => listProducts(filters.store ? { store: filters.store } : {}, { signal }),
    [filters.store ?? "", indexKey],
  );
  const names = useMemo(() => productNames(products.data?.items ?? []), [products.data]);
  const describe = (item) => names.get(item.product) ?? item.product ?? L.product.unknown;

  const area = useResource(
    (signal) => (areaId ? readArea(areaId, signal) : Promise.resolve(null)),
    [areaId],
  );
  const currentArea = areaId && area.data?.id === areaId ? area.data : null;
  const dataKey = `${indexKey}|${round}`;

  // Year layers of the chosen product in the area: of the chosen store, else
  // of the first store holding the product.
  const product = products.data?.items.find((item) => item.product === filters.product) ?? null;
  const layerStore =
    filters.store ?? (product ? (productStores(product, stores.map((item) => item.id))[0] ?? null) : null);
  const layers = useLayers(
    { store: layerStore, product: filters.product ?? null, areaId },
    params[LAYER_PARAM] || null,
    dataKey,
  );
  const layer = layers.layer;
  const layerLegend = useLayerLegend(layer);
  const layerSource = useMemo(() => layerTiles(layer), [layer]);
  // A layer the answer does not hold any more leaves the address.
  useEffect(() => {
    if (layers.set && !layers.loading && params[LAYER_PARAM] && !layer) {
      setParams({ [LAYER_PARAM]: null }, { replace: true });
    }
  }, [layers.set, layers.loading, params[LAYER_PARAM]]);

  // With a layer chosen, the outlines are those of its versions.
  const viewKey = layer ? `${filtersKey}\n${layers.set.store}\n${layer.key}` : filtersKey;
  const viewFilters = useMemo(() => (layer ? layerFilters(filters, layers.set, layer) : filters), [viewKey]);
  const view = useFootprints(move, viewFilters, viewKey, dataKey);
  const footprints = useMemo(() => layerView(view.data, layer), [view.data, layer]);
  const sheets = useSheets(grid, move);
  const sheetItems = useRef([]);
  sheetItems.current = sheets.items;

  // The version previewed on the map.
  const previewRef = params[PREVIEW_PARAM] || null;
  const preview = useVersionPreview(previewRef, dataKey);
  const previewStyle = chosenStyle(preview.info, params[PREVIEW_STYLE_PARAM]);
  const versionSource = useMemo(() => versionTiles(preview.info, previewStyle), [preview.info, previewStyle]);
  const features = useFeatures(preview.info, move);

  // Frame the chosen area — not the one of a shared link with a position.
  const framedArea = useRef(start ? areaId : null);
  useEffect(() => {
    if (!mapApi || !currentArea || framedArea.current === currentArea.id) return;
    framedArea.current = currentArea.id;
    mapApi.fit(currentArea.bbox);
  }, [mapApi, currentArea?.id]);

  // Frame the version previewed — not the one of a shared link with a position.
  const framedPreview = useRef(start ? previewRef : null);
  useEffect(() => {
    if (!previewRef) framedPreview.current = null;
    if (!mapApi || !preview.info || framedPreview.current === previewRef) return;
    framedPreview.current = previewRef;
    const extent = preview.info.bounds ?? (preview.card?.footprint ? geometryBounds(preview.card.footprint) : null);
    if (extent) mapApi.fit(extent);
  }, [mapApi, preview.info, previewRef]);

  // Without a position, an area or a preview, frame what the filters match;
  // an index still being built is framed once its first scan ends.
  const framedData = useRef(Boolean(start || areaId || previewRef));
  useEffect(() => {
    if (!mapApi || framedData.current || userMoved.current) return undefined;
    const controller = new AbortController();
    listFootprints(
      { ...filters, bbox: bboxText(WORLD_BOUNDS), limit: FOOTPRINT_LIMIT, grid_columns: FRAME_COLUMNS },
      { signal: controller.signal },
    ).then(
      (answer) => {
        const extent = dataExtent(answer);
        if (!extent || userMoved.current) return;
        framedData.current = true;
        mapApi.fit(extent, { animate: false });
      },
      () => {
        // The view's own query shows the problem.
      },
    );
    return () => controller.abort();
  }, [mapApi, indexKey]);

  const onMove = (next) => {
    if (next.byUser) userMoved.current = true;
    setMove(next);
    setParams(next.position, { replace: true });
  };

  const settle = (made) => {
    areas.set(made.id, made);
    setFileLayers(null);
    setParams({ area_id: made.id });
  };
  const fail = (error) => {
    if (!(error instanceof ApiError)) throw error;
    setAreaProblem(error.problem);
  };
  const save = async (make) => {
    setAreaBusy(true);
    setAreaProblem(null);
    setAreaNote(null);
    try {
      const made = await make();
      if (made) settle(made);
    } catch (error) {
      fail(error);
    } finally {
      setAreaBusy(false);
    }
  };
  const closeOnPhone = () => {
    if (narrow) setLeftOpen(false);
  };
  const panel = {
    area: currentArea,
    areaBusy: areaBusy || (Boolean(areaId) && area.loading),
    areaProblem: areaProblem ?? (areaId && area.error ? area.error.problem : null),
    areaNote,
    areaRef: areaStep,
    tool,
    onTool: (next) => {
      setTool(next);
      if (next) closeOnPhone();
    },
    onView: () => {
      if (!mapApi) return;
      setTool(null);
      save(() => createArea({ geometry: bboxPolygon(mapApi.bounds()), name: L.area.names.view, source: "view" }));
    },
    onFile: (file, layer) =>
      save(async () => {
        try {
          return await uploadArea(file, { name: file.name, layer });
        } catch (error) {
          if (error instanceof ApiError && error.problem.layers?.length) {
            setFileLayers({ file, layers: error.problem.layers });
          }
          throw error;
        }
      }),
    fileLayers,
    onSheetCode: (code) =>
      save(async () => {
        const geometry =
          sheetItems.current.find((item) => item.sheet === code)?.geometry ?? (await sheetFromIndex(code));
        if (!geometry) {
          setAreaNote(t(L.area.sheet_not_found, { sheet: code }));
          return null;
        }
        return createArea({ geometry, name: code, source: "sheet" });
      }),
    grid,
    onGrid: (patch) => {
      setGrid((previous) => ({ ...previous, ...patch }));
      if (patch.on) closeOnPhone();
    },
    onClear: () => setParams({ area_id: null, [LAYER_PARAM]: null }),
    products: products.data,
    productsError: products.error,
    filters,
    onFilters: (patch) => setParams(filterPatch(patch, filters)),
    stores,
    names,
    indexKey,
    onRefreshed: () => setRound((n) => n + 1),
  };

  const change = () => {
    setLeftOpen(true);
    requestAnimationFrame(() => areaStep.current?.focus());
  };
  const notes = [];
  if (!tool && grid.on) notes.push(html`<${GridNote} key="grid" grid=${grid} sheets=${sheets}
    onOff=${() => setGrid((previous) => ({ ...previous, on: false }))} />`);
  if (!tool && view.error) notes.push(html`<div key="error" class="float-card map-problem"><${ProblemView} problem=${view.error.problem} compact /></div>`);
  if (!tool && layers.error) notes.push(html`<div key="layers" class="float-card map-problem"><${ProblemView} problem=${layers.error.problem} compact /></div>`);
  // Below the zoom of a preview's tiles: its outlines only, and a way closer.
  const hidden = move ? [layerSource, versionSource].filter((source) => source && !tilesShown(source, move.zoom)) : [];
  if (!tool && hidden.length) {
    notes.push(html`<${ZoomHint} key="zoom" onZoom=${() =>
      mapApi?.zoomTo(Math.max(...hidden.map(shownFrom)), unionBounds(hidden.map((source) => source.bounds ?? null)))} />`);
  }
  const sections = [];
  if (previewRef) {
    sections.push(html`<${VersionLegend} key="version" reference=${previewRef} shown=${preview} style=${previewStyle}
      features=${features} onStyle=${(value) => setParams({ [PREVIEW_STYLE_PARAM]: value }, { replace: true })}
      onClose=${() => setParams({ [PREVIEW_PARAM]: null, [PREVIEW_STYLE_PARAM]: null })} />`);
  }
  if (layer) sections.push(html`<${LayerLegend} key="layer" layer=${layer} legend=${layerLegend} job=${layers.job} />`);

  return html`<${ViewLayout} id="map"
    left=${{ label: L.panel, open: leftOpen, onClose: () => setLeftOpen(false), content: html`<${SelectionPanel} ...${panel} />` }}>
    <div class="map-view">
      <div class="center-bar map-bar">
        <button type="button" class=${`btn ${leftOpen ? "ghost" : "active"} panel-toggle`} aria-controls="map-left"
          aria-expanded=${leftOpen ? "true" : "false"} title=${L.panel_toggle} onClick=${() => setLeftOpen(!leftOpen)}>
          <${Icon} name="sidebar" size=${17} /><span class="panel-toggle-label">${L.panel}</span>
        </button>
        ${currentArea
          ? html`<span class="area-badge" title=${areaSummary(currentArea)}>
              <${Icon} name="pin" size=${14} />
              <span class="area-badge-text">${t(L.area.badge, { name: areaName(currentArea) })}
                <span class="muted"> · ${areaSummary(currentArea)}</span></span>
              <button type="button" class="btn ghost sm" onClick=${change}>${L.area.change}</button>
              <button type="button" class="btn ghost sm" onClick=${panel.onClear}>${L.area.clear}</button>
            </span>`
          : null}
        <${FilterChips} filters=${filters} names=${names} stores=${stores} />
        <${Counters} view=${{ ...view, data: footprints }} filters=${viewFilters} area=${currentArea} />
      </div>
      <div class="center-body">
        <${MapCanvas} basemap=${basemap} start=${start} area=${currentArea} footprints=${footprints}
          layerTiles=${layerSource} versionTiles=${versionSource}
          previewOutline=${previewRef ? (preview.card?.footprint ?? null) : null} previewFeatures=${features.data}
          sheets=${grid.on ? sheets.items : []} tool=${tool} describe=${describe}
          onReady=${setMapApi} onMove=${onMove}
          onDrawn=${(geometry, kind) => {
            setTool(null);
            save(() => createArea({ geometry, name: L.area.names[kind], source: "drawn" }));
          }}
          onCancel=${() => setTool(null)}
          onSheet=${(sheet) => save(() => createArea({ geometry: sheet.geometry, name: sheet.sheet, source: "sheet" }))}
          onOpen=${(item) => setParams({ file: `${item.store}/${item.slot}`, file_version: item.version })}>
          ${notes.length ? html`<div class="map-notes">${notes}</div>` : null}
          <${LayerButtons} set=${layers.set} chosen=${layer?.key ?? null} loading=${layers.loading}
            onChoose=${(key) => setParams({ [LAYER_PARAM]: key })} />
          <${Legend} view=${footprints} versions=${filters.versions ?? "current"} grid=${grid}
            area=${Boolean(currentArea)} offline=${Boolean(settings?.offline)} basemaps=${basemaps}
            basemap=${basemap} layer=${layer?.title ?? null} onBasemap=${(name) => {
              keepBasemap(name);
              setBasemapName(name);
            }}>${sections}</${Legend}>
        </${MapCanvas}>
      </div>
    </div>
  </${ViewLayout}>`;
}

function FilterChips({ filters, names, stores }) {
  const chips = [];
  if (filters.product) chips.push(["product", names.get(filters.product) ?? filters.product]);
  if (filters.store) {
    chips.push(["store", t(L.chips.store, { value: stores.find((item) => item.id === filters.store)?.name ?? filters.store })]);
  }
  if (filters.country) chips.push(["country", t(L.chips.country, { value: filters.country })]);
  if (filters.years) chips.push(["years", t(L.chips.years, { value: filters.years })]);
  if (filters.unit) chips.push(["unit", t(L.chips.unit, { value: filters.unit })]);
  if (filters.versions) {
    chips.push(["versions", t(L.chips.versions, { value: L.filters.versions_options[filters.versions] ?? filters.versions })]);
  }
  if (filters.status) {
    chips.push(["status", t(L.chips.status, { value: L.filters.status_options[filters.status] ?? filters.status })]);
  }
  if (filters.q) chips.push(["q", t(L.chips.q, { value: filters.q })]);
  if (!chips.length) return null;
  return html`<ul class="chip-row filter-chips" aria-label=${L.filters.title}>
    ${chips.map(
      ([name, text]) => html`<li key=${name} class="chip static filter-chip">
        <span>${text}</span>
        <button type="button" class="chip-remove" aria-label=${t(L.filters.chip_remove, { name: text })}
          title=${t(L.filters.chip_remove, { name: text })} onClick=${() => setParams(filterPatch({ [name]: null }, filters))}>
          <${Icon} name="x" size=${12} />
        </button>
      </li>`,
    )}
  </ul>`;
}

function Counters({ view, filters, area }) {
  const answer = view.data;
  let text = null;
  if (answer) {
    const outlines = count(answer.total, L.units.outlines);
    if (answer.aggregated) text = t(L.counts.grid, { count: outlines });
    else text = answer.total ? t(L.counts.outlines, { count: outlines }) : L.counts.empty;
  }
  const none = answer?.groups.none ?? 0;
  const stale = answer?.stale_stores ?? [];
  return html`<div class="map-counts">
    <span class="map-count-busy">${view.loading ? html`<${Spinner} quiet label=${L.counts.loading} />` : null}</span>
    <span class="map-count" role="status">${text ?? (view.loading ? L.counts.loading : "")}</span>
    ${answer?.stale
      ? html`<span class="chip static stale-chip" title=${t(L.counts.stale_title, {
          stores: stale.map((item) => item.store).join(", "),
          indexed_at: stale.map((item) => stamp(item.indexed_at)).join(", "),
        })}><${Icon} name="alert" size=${13} />${L.counts.stale}</span>`
      : null}
    ${none
      ? html`<${Link} class="chip no-outline" view="catalog"
          params=${{ ...filters, area_id: area?.id, location: "none" }} title=${L.counts.no_outline_title}>
          ${t(L.counts.no_outline, { count: count(none, T.common.units.files) })}
          <${Icon} name="chevron" size=${12} />
        </${Link}>`
      : null}
  </div>`;
}

/**
 * A change of the filters: a year layer belongs to its product, so another
 * product leaves no layer chosen.
 *
 * @param {Object<string, string|null>} patch
 * @param {import("../map/panel.js").MapFilters} filters - Before the change.
 * @returns {Object<string, string|null>}
 */
function filterPatch(patch, filters) {
  const other = "product" in patch && (patch.product || null) !== (filters.product ?? null);
  return other ? { ...patch, [LAYER_PARAM]: null } : patch;
}

/**
 * The filters of the outlines while a year layer is chosen: every version of
 * the layer's store and product from its data year (`layerView` keeps the
 * layer's own).
 */
function layerFilters(filters, set, layer) {
  return {
    ...filters,
    store: set.store,
    product: set.product,
    versions: "all",
    years: layer.year === null ? null : String(layer.year),
  };
}

/**
 * The outlines of a year layer's versions in a view of `layerFilters`; a
 * grid stays the grid of their filters.
 *
 * @param {import("../types.js").MapView|undefined} view
 * @param {import("../types.js").Layer|null} layer
 * @returns {import("../types.js").MapView|undefined}
 */
function layerView(view, layer) {
  if (!view || !layer || view.aggregated) return view;
  const wanted = new Set(
    (layer.versions ?? [])
      .map((version) => readVersionRef(version.ref))
      .filter(Boolean)
      .map(({ store, path }) => `${store}\n${path}`),
  );
  const items = view.items.filter((item) => wanted.has(`${item.store}\n${item.version}`));
  return { ...view, items, total: items.length };
}

function GridNote({ grid, sheets, onOff }) {
  const name = `${L.area.systems[grid.system] ?? grid.system} ${scaleLabel(grid.scale)}`;
  let content;
  if (sheets.problem) content = html`<${ProblemView} problem=${sheets.problem} compact />`;
  else if (sheets.status === "unsupported") content = html`<span>${L.grid_hint.unsupported}</span>`;
  else if (sheets.loading && !sheets.items.length) content = html`<${Spinner} label=${L.grid_hint.loading} />`;
  else content = html`<span>${t(L.grid_hint.pick, { grid: name })}</span>`;
  return html`<div class="map-hint-card float-card" role="status">
    <${Icon} name="grid" size=${15} />${content}
    <button type="button" class="btn sm ghost" onClick=${onOff}>${L.grid_hint.off}</button>
  </div>`;
}

/** Filters of the address under their `/slots` names. */
function readFilters(params) {
  return Object.fromEntries(FILTERS.filter((name) => params[name]).map((name) => [name, params[name]]));
}

function columns(width) {
  return Math.min(512, Math.max(4, Math.round(width / CELL_PX)));
}

/**
 * Outlines of the view, asked again when the map stops, the filters change
 * or the index changes; the previous question is abandoned.
 */
function useFootprints(move, filters, filtersKey, dataKey) {
  const [state, setState] = useState({ data: undefined, error: undefined, loading: false });
  const moveKey = move ? `${bboxText(move.bbox)}|${columns(move.width)}` : "";
  useEffect(() => {
    if (!move) return undefined;
    const controller = new AbortController();
    setState((previous) => (previous.loading ? previous : { ...previous, loading: true }));
    const timer = setTimeout(() => {
      listFootprints(
        { ...filters, bbox: bboxText(move.bbox), limit: FOOTPRINT_LIMIT, grid_columns: columns(move.width) },
        { signal: controller.signal },
      ).then(
        (data) => setState({ data, error: undefined, loading: false }),
        (error) => {
          if (!controller.signal.aborted) setState((previous) => ({ ...previous, error, loading: false }));
        },
      );
    }, MOVE_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [moveKey, filtersKey, dataKey]);
  return state;
}

/** Sheets of the grid in the view while the grid is on. */
function useSheets(grid, move) {
  const [state, setState] = useState(NO_SHEETS);
  const shown = useRef("");
  const moveKey = move ? bboxText(move.bbox) : "";
  useEffect(() => {
    if (!grid.on || !move) {
      shown.current = "";
      setState(NO_SHEETS);
      return undefined;
    }
    // Sheets of another system or scale are never offered for a click.
    const gridKey = `${grid.system}|${grid.scale}`;
    const fresh = shown.current === gridKey;
    shown.current = gridKey;
    setState((previous) => ({ ...(fresh ? previous : NO_SHEETS), loading: true }));
    const controller = new AbortController();
    const timer = setTimeout(() => {
      listSheets(
        { bbox: bboxText(move.bbox), system: grid.system, scale: grid.scale, producer: GRID_PRODUCER },
        { signal: controller.signal },
      ).then(
        (answer) => setState({ items: answer.items, status: answer.status, problem: null, loading: false }),
        (error) => {
          if (!controller.signal.aborted) {
            setState({ items: [], status: null, problem: error.problem, loading: false });
          }
        },
      );
    }, MOVE_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [grid.on, grid.system, grid.scale, moveKey]);
  return state;
}

/** An area of the address: saved on this page, else asked for. */
function readArea(id, signal) {
  return areas.has(id) ? Promise.resolve(areas.get(id)) : getArea(id, { signal });
}

/** The extent of what a framing query found, or `null`. */
function dataExtent(answer) {
  if (answer.aggregated) {
    return unionBounds(answer.cells.map((cell) => [cell.min_lon, cell.min_lat, cell.max_lon, cell.max_lat]));
  }
  return unionBounds(answer.items.map((item) => geometryBounds(item.geometry)));
}

/**
 * The outline of a sheet typed by its code, from the index: a version of a
 * slot of that unit whose footprint is the producer's sheet outline.
 *
 * @param {string} code - Sheet code (godło).
 * @returns {Promise<import("../types.js").Geometry|null>}
 */
async function sheetFromIndex(code) {
  const page = await listSlots({ unit: code, location: "with", versions: "all", limit: 20 });
  for (const item of page.items) {
    if (item.version?.location.source !== "sheet") continue;
    const card = await getVersion(item.store, item.version.path);
    if (card.footprint) return card.footprint;
  }
  return null;
}
