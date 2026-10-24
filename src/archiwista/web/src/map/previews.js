/**
 * Previews on the map (docs/SPEC.md 5.4 and 6.1; plan v0.2 decisions 4 and
 * 7, steps 12b and 15): the preview of one object and the year layers of an
 * area.
 *
 * An object: „Pokaż podgląd na mapie” in the file card — or „Pokaż na
 * mapie” in the card of an own file (views/own.js) — opens the map with
 * `preview=<ref>` (and its style in `preview_style`): a raster's tiles within
 * its bounds and zooms (`tiles_url`), a vector's features of the view
 * simplified to the map's zoom (`features_url`, decision 4), and the
 * object's outline. A store version (`version:`) comes with its card; an own
 * file or snapshot (`file:`, `snapshot:`) with its project's file card, its
 * `file_id` found by its path (map/own.js). A view without area (a single
 * point framed, a map not laid out) is widened before `…/features`, which
 * refuses an empty box. Year layers: with an area and a product chosen, the
 * store's layers of the product (`GET /local-layers`) are buttons of years
 * on the map; the chosen one (`layer=<key>`) shows the outlines of its
 * versions and one raster source of the layer's tiles (`/local-layers/
 * tiles`, decision 7) from the layer's `minzoom` — below it only the
 * outlines and „Przybliż, aby zobaczyć podgląd”. The build of the chosen
 * layer's missing previews (else of the first layer being built) is
 * followed, and the layers are read again when it ends: their addresses
 * change with every preview that gets ready. The legends and states of both
 * go into the map legend. The same layers (`useLayers`, with `group=campaign`
 * split by campaign) feed the Wachlarz, the catalog's timeline and the
 * details panel (step 13): one choice, `layer` of the address.
 *
 * Every address comes from an answer (`apiTemplate` adds `style`); MapLibre
 * sends the session's CSRF header with them (`transformRequest` in
 * canvas.js through `apiHeaders`).
 */

import {
  ApiError,
  apiTemplate,
  getLinked,
  getLocalLayers,
  getOwnFile,
  getOwnPreview,
  getPreview,
  getVersion,
} from "../api.js";
import { day, int, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { t } from "../labels/index.js";
import { map as L } from "../labels/map.js";
import { own as O } from "../labels/own.js";
import { previews as P } from "../labels/previews.js";
import { PreviewLegend, PreviewReason, styleName } from "../previews.js";
import { Link, useRoute } from "../router.js";
import { html, Icon, ProblemView, Seg, Spinner, Tech, useEffect, useState } from "../ui.js";
import { crsName, JobStatus, loadCardStyles, useJob } from "../views/cards.js";
import { slotName } from "./canvas.js";
import { bboxText, unionBounds, widenBounds } from "./geo.js";
import { findOwnFile, OwnCardLink, ownName, readOwnRef, snapshotOutline } from "./own.js";

// The build of a layer's previews is shown as every job is (cards.css).
await loadCardStyles();

/** Address parameter of the version shown on the map: its `ref`. */
export const PREVIEW_PARAM = "preview";
/** Address parameter of that version's style (`PreviewInfo.styles`). */
export const PREVIEW_STYLE_PARAM = "preview_style";
/** Address parameter of the chosen year layer: its `key`. */
export const LAYER_PARAM = "layer";
/** Address parameter of the layers' grouping: `campaign` splits a year by campaign. */
export const GROUP_PARAM = "group";
/** The value of `GROUP_PARAM` asking for campaigns (`group` of `GET /local-layers`). */
export const CAMPAIGN_GROUP = "campaign";

const TILE_PX = 256;
// Zoom levels of the API: tiles of 256 px (`MAX_ZOOM` of the server).
const MAX_ZOOM = 22;
const MOVE_DEBOUNCE_MS = 150;
const STORE_ID = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const VERSION_REF = /^version:([^:]+):([^\0]+)$/;
// Parts of a variant telling apart two layers of one year (A-ADR-017).
const VARIANT_FIELDS = ["resolution", "horizontal_crs", "vertical_crs"];
const NO_FEATURES = { data: null, problem: null, loading: false };
// Least width and height of a view asked for features: the API refuses a
// box without area, which rounding to 6 places must not produce.
const MIN_VIEW_DEGREES = 0.00002;

/**
 * The store and path of a version's `ref` (`version:<store>:<path>`): store
 * ids hold no colon, so the rest is the path (archiwista/refs.py).
 *
 * @param {string} ref
 * @returns {{store: string, path: string}|null} Null for another kind of
 *   object or a malformed ref.
 */
export function readVersionRef(ref) {
  const found = VERSION_REF.exec(ref);
  return found && STORE_ID.test(found[1]) ? { store: found[1], path: found[2] } : null;
}

/**
 * The zoom of the API's 256 px tiles at a map zoom: MapLibre counts its zoom
 * in 512 px tiles, the API (tiles, `minzoom`, features) in 256 px ones.
 *
 * @param {number} mapZoom
 * @returns {number}
 */
export function tileZoom(mapZoom) {
  return mapZoom + 1;
}

/**
 * Whether a raster source shows tiles at a map zoom: MapLibre asks for the
 * tiles of the rounded zoom of its 256 px tiles, none below `minzoom`.
 *
 * @param {{minzoom?: number}} source - A source of `layerTiles`/`versionTiles`.
 * @param {number} mapZoom
 * @returns {boolean}
 */
export function tilesShown(source, mapZoom) {
  return Math.round(tileZoom(mapZoom)) >= (source.minzoom ?? 0);
}

/**
 * The map zoom from which a source shows tiles (the inverse of `tileZoom`).
 *
 * @param {{minzoom?: number}} source
 * @returns {number}
 */
export function shownFrom(source) {
  return Math.max(0, (source.minzoom ?? 0) - 1);
}

/**
 * The raster source of a year layer: one source for all its versions
 * (decision 7), from the layer's `minzoom`, within its versions' bounds.
 *
 * @param {import("../types.js").Layer|null} layer
 * @returns {object|null} A MapLibre source; null while none of its previews
 *   is ready (its tiles would be empty).
 */
export function layerTiles(layer) {
  const preview = layer?.preview;
  const bounds = unionBounds((layer?.versions ?? []).map((version) => version.bounds));
  if (!preview?.tiles_url || preview.minzoom === null || !preview.ready || !bounds) return null;
  return { type: "raster", tiles: [apiTemplate(preview.tiles_url)], tileSize: TILE_PX, minzoom: preview.minzoom, bounds };
}

/**
 * The raster source of a version's tiles in a style, within its bounds and
 * zooms; a vector shows its features instead (`useFeatures`).
 *
 * @param {import("../types.js").PreviewInfo|null} info
 * @param {string|null} style
 * @returns {object|null} A MapLibre source; null without tiles to show.
 */
export function versionTiles(info, style) {
  if (info?.state !== "ready" || !info.tiles_url || info.features_url) return null;
  const source = { type: "raster", tiles: [apiTemplate(info.tiles_url, { style })], tileSize: TILE_PX };
  if (info.bounds) source.bounds = info.bounds;
  if (info.minzoom !== null) source.minzoom = info.minzoom;
  if (info.maxzoom !== null) source.maxzoom = info.maxzoom;
  return source;
}

/**
 * The style a version is shown in: the address's, else its usual one.
 *
 * @param {import("../types.js").PreviewInfo|null} info
 * @param {string|null|undefined} wanted - `preview_style` of the address.
 * @returns {string|null}
 */
export function chosenStyle(info, wanted) {
  if (!info) return null;
  return info.styles.includes(wanted) ? wanted : (info.default_style ?? info.styles[0] ?? null);
}

/**
 * The layers of the chosen product, and the chosen one.
 *
 * @param {{store: string|null, product: string|null, areaId: string|null,
 *   group?: string|null, needsArea?: boolean}} choice - Without a store and a
 *   product there are no layers; without an area neither, unless `needsArea`
 *   is false (the timeline: the counts of the whole store). `group`:
 *   `CAMPAIGN_GROUP` or none (years).
 * @param {string|null} chosen - `layer` of the address.
 * @param {string} dataKey - Changes when the index does.
 * @returns {{set: import("../types.js").LayerSet|null, layer:
 *   import("../types.js").Layer|null, job: ReturnType<typeof useJob>,
 *   loading: boolean, error: import("../api.js").ApiError|undefined}} `job`
 *   follows the build of the chosen layer's missing previews, else of the
 *   first layer being built: the layers are read again when it ends, so the
 *   addresses of their images follow the previews that got ready.
 */
export function useLayers({ store, product, areaId, group = null, needsArea = true }, chosen, dataKey) {
  const wanted = Boolean(store && product && (areaId || !needsArea));
  const key = wanted ? [store, product, areaId ?? "", group ?? ""].join("\n") : "";
  const answer = useResource(
    (signal) =>
      key
        ? getLocalLayers({ store, product, area_id: areaId, group }, { signal }).then((set) => ({ key, set }))
        : Promise.resolve(null),
    [key, dataKey],
  );
  const set = key && answer.data?.key === key ? answer.data.set : null;
  const layer = set?.layers.find((item) => item.key === chosen) ?? null;
  const job = useJob({ onEnd: answer.reload });
  const built = [layer, ...(set?.layers ?? [])].find((item) => item?.preview?.state === "building" && item.preview.job);
  const building = built?.preview.job.id ?? null;
  useEffect(() => {
    if (building) job.follow(building, "preview");
  }, [building]);
  return { set, layer, job, loading: Boolean(key) && answer.loading, error: key ? answer.error : undefined };
}

/**
 * The legend of a layer's preview: that of its first ready version's usual
 * style — classes always, a colour ramp only for a layer of that one version
 * (every file has its own range of values).
 *
 * @param {import("../types.js").Layer|null} layer
 * @returns {import("../types.js").GradientLegend|import("../types.js").ClassesLegend|null}
 */
export function useLayerLegend(layer) {
  const version = layer?.versions?.find((item) => item.preview.state === "ready") ?? null;
  const target = version ? readVersionRef(version.ref) : null;
  const { data } = useResource(
    (signal) => (target ? getPreview(target.store, target.path, { signal }) : Promise.resolve(null)),
    [version?.ref ?? ""],
  );
  if (!data || data.ref !== version?.ref || !data.default_style) return null;
  const legend = data.legends[data.default_style] ?? null;
  return legend && (legend.kind === "classes" || layer.versions.length === 1) ? legend : null;
}

/**
 * The object shown on the map (`preview` of the address): its preview, its
 * card and its outline — a store version's (`version:`) or an own file's or
 * snapshot's (`file:`, `snapshot:`; the file's `file_id` found by its path).
 * A build in progress is followed and the preview read again when it ends.
 *
 * @param {string|null} ref
 * @param {string} dataKey - Changes when the index does.
 * @returns {{info: import("../types.js").PreviewInfo|null, card:
 *   import("../types.js").VersionCard|import("../types.js").OwnFileCard|null,
 *   own: {project: string, fileId: string, label: string|null, path: string,
 *   snapshot: import("../types.js").SnapshotItem|null}|null, outline:
 *   import("../types.js").Geometry|null, invalid: boolean, loading: boolean,
 *   error: import("../api.js").ApiError|undefined}} `own`: an own object;
 *   `invalid`: the ref names no object of either kind.
 */
export function useVersionPreview(ref, dataKey) {
  const target = ref ? readVersionRef(ref) : null;
  const owned = ref && !target ? readOwnRef(ref) : null;
  const answer = useResource(
    async (signal) => {
      if (target) {
        const [info, card] = await Promise.all([
          getPreview(target.store, target.path, { signal }),
          getVersion(target.store, target.path, { signal }),
        ]);
        return { ref, info, card, own: null, outline: card.footprint ?? null };
      }
      if (!owned) return null;
      const file = await findOwnFile(owned.project, owned.path, { signal });
      if (!file) throw new ApiError(ownMissing(ref));
      const [info, card] = await Promise.all([
        getOwnPreview(owned.project, file.file_id, owned.label, { signal }),
        getOwnFile(owned.project, file.file_id, { signal }),
      ]);
      const snapshot = owned.label ? (card.snapshots.find((item) => item.label === owned.label) ?? null) : null;
      const outline = owned.label ? (snapshot ? snapshotOutline(snapshot) : null) : (card.extent?.wgs84 ?? null);
      return { ref, info, card, own: { ...owned, fileId: file.file_id, snapshot }, outline };
    },
    [ref ?? "", dataKey],
  );
  const shown = answer.data?.ref === ref ? answer.data : null;
  const job = useJob({ onEnd: answer.reload });
  const building = shown?.info.state === "building" ? (shown.info.job?.id ?? null) : null;
  useEffect(() => {
    if (building) job.follow(building, "preview");
  }, [building]);
  const known = Boolean(target || owned);
  return {
    info: shown?.info ?? null,
    card: shown?.card ?? null,
    own: shown?.own ?? null,
    outline: shown?.outline ?? null,
    invalid: Boolean(ref) && !known,
    loading: known && answer.loading,
    error: known ? answer.error : undefined,
  };
}

/** The problem of an own ref whose file the folder's index does not list. */
function ownMissing(ref) {
  return { type: "about:blank", title: O.map.title, status: 404, detail: t(O.map.not_found, { ref }), code: "not_found" };
}

/**
 * The features of a vector version in the map's view, simplified to its zoom
 * (decision 4), asked again when the map stops; none outside the version.
 *
 * @param {import("../types.js").PreviewInfo|null} info
 * @param {import("./canvas.js").MapMove|null} move
 * @returns {{data: import("../types.js").PreviewFeatures|null, problem:
 *   import("../types.js").Problem|null, loading: boolean}}
 */
export function useFeatures(info, move) {
  const [state, setState] = useState(NO_FEATURES);
  const template = info?.state === "ready" ? info.features_url : null;
  const wanted = template && move && meets(move.bbox, info.bounds);
  const bbox = wanted ? bboxText(widenBounds(move.bbox, MIN_VIEW_DEGREES)) : "";
  const zoom = wanted ? Math.min(MAX_ZOOM, Math.ceil(tileZoom(move.zoom))) : 0;
  const key = wanted ? `${template}\n${bbox}\n${zoom}` : "";
  useEffect(() => {
    if (!key) {
      setState(NO_FEATURES);
      return undefined;
    }
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true }));
    const timer = setTimeout(() => {
      const address = template.replace("{bbox}", bbox).replace("{zoom}", String(zoom));
      getLinked(address, { signal: controller.signal }).then(
        (data) => setState({ data, problem: null, loading: false }),
        (error) => {
          if (!controller.signal.aborted) setState({ data: null, problem: error.problem, loading: false });
        },
      );
    }, MOVE_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key]);
  return state;
}

/**
 * The year buttons on the map (SPEC 6.1): newest first, each with the share
 * of the area its versions cover; a second click on the chosen one clears
 * the choice. Two variants of one year say how they differ.
 *
 * @param {{set: import("../types.js").LayerSet|null, chosen: string|null,
 *   loading: boolean, onChoose: (key: string|null) => void}} props
 */
export function LayerButtons({ set, chosen, loading, onChoose }) {
  if (!set) {
    return loading
      ? html`<div class="layer-strip"><span class="layer-strip-note float-card"><${Spinner} label=${L.layers.loading} /></span></div>`
      : null;
  }
  if (!set.layers.length) return null;
  const hints = variantHints(set.layers);
  return html`<div class="layer-strip" role="group" aria-label=${L.layers.label}>
    ${set.layers.map((layer) => {
      const on = layer.key === chosen;
      const percent = layer.coverage?.percent ?? 0;
      const tone = percent === 100 ? "done" : percent > 0 || layer.coverage?.ratio ? "some" : "no";
      return html`<button type="button" key=${layer.key} class=${`layer-btn ${tone}${on ? " on" : ""}`}
        aria-pressed=${on ? "true" : "false"} title=${describeLayer(layer)}
        onClick=${() => onChoose(on ? null : layer.key)}>
        <span class="ring" style=${`--p:${percent}%`} aria-hidden="true"></span>
        <span class="layer-btn-title">${layer.title}</span>
        ${hints.has(layer.key) ? html`<span class="layer-btn-hint">${hints.get(layer.key)}</span>` : null}
      </button>`;
    })}
  </div>`;
}

/**
 * The chosen layer in the map legend: its preview's state, legend and build.
 *
 * @param {{layer: import("../types.js").Layer, legend: object|null,
 *   job: ReturnType<typeof useJob>}} props
 */
export function LayerLegend({ layer, legend, job }) {
  const preview = layer.preview;
  const title = t(L.previews.layer_title, { title: layer.title });
  const following = job.running && job.id === preview?.job?.id;
  let note = null;
  if (preview?.state === "unavailable") note = L.previews.layer_unavailable;
  else if (preview?.state === "needs_build") note = L.previews.layer_needs_build;
  else if (preview?.state === "building" && !following) note = L.previews.layer_building;
  return html`<section class="legend-section" aria-label=${title}>
    <div class="legend-row">
      <span class="sw sw-preview" aria-hidden="true"></span>
      <span>
        <${Tech} value=${[["layer", layer.key]]}><b>${title}</b></${Tech}>
        ${preview
          ? html`<span class="legend-sub">${t(L.previews.layer_ready, { ready: int(preview.ready), total: int(preview.total) })}</span>`
          : null}
      </span>
    </div>
    ${legend ? html`<${PreviewLegend} legend=${legend} />` : null}
    ${note ? html`<p class="legend-note">${note}</p>` : null}
    ${following ? html`<${JobStatus} job=${job} />` : null}
  </section>`;
}

/**
 * The version shown on the map in the map legend: its name and outline, its
 * style and legend or features, why it shows nothing, its card and a button
 * taking it off the map.
 *
 * @param {object} props
 * @param {string} props.reference - The `ref` of the address.
 * @param {ReturnType<typeof useVersionPreview>} props.shown
 * @param {string|null} props.style - The style shown (`chosenStyle`).
 * @param {(style: string) => void} props.onStyle
 * @param {ReturnType<typeof useFeatures>} props.features
 * @param {() => void} props.onClose
 */
export function VersionLegend({ reference, shown, style, onStyle, features, onClose }) {
  const { info, card } = shown;
  let body;
  if (shown.invalid) body = html`<p class="legend-note warn">${t(L.previews.bad_ref, { ref: reference })}</p>`;
  else if (!info || !card) {
    body = shown.error
      ? html`<${ProblemView} problem=${shown.error.problem} compact />`
      : html`<${Spinner} label=${L.previews.loading} />`;
  } else {
    body = html`<${VersionDetails} info=${info} card=${card} own=${shown.own} outline=${Boolean(shown.outline)}
      style=${style} onStyle=${onStyle} features=${features} />`;
  }
  return html`<section class="legend-section" aria-label=${L.previews.file_title}>
    <div class="legend-section-head">
      <b>${L.previews.file_title}</b>
      <button type="button" class="btn ghost icon-btn legend-close" aria-label=${L.previews.close}
        title=${L.previews.close} onClick=${onClose}><${Icon} name="x" size=${14} /></button>
    </div>
    ${body}
  </section>`;
}

function VersionDetails({ info, card, own, outline, style, onStyle, features }) {
  const legend = style ? info.legends[style] : null;
  const vector = Boolean(info.features_url);
  const shows = info.state === "ready" && (vector || Boolean(info.tiles_url));
  return html`
    ${own ? html`<${OwnName} info=${info} card=${card} own=${own} />` : html`<${VersionName} info=${info} card=${card} />`}
    ${outline
      ? html`<div class="legend-row"><span class="sw sw-preview-outline" aria-hidden="true"></span>${L.previews.outline}</div>`
      : null}
    ${shows && !vector && info.styles.length > 1
      ? html`<${Seg} small label=${P.styles_label} value=${style} onChange=${onStyle}
          options=${info.styles.map((value) => ({ value, label: styleName(value) }))} />`
      : null}
    ${shows && !vector && legend ? html`<${PreviewLegend} legend=${legend} />` : null}
    ${shows && vector
      ? html`<div class="legend-row"><span class="sw sw-features" aria-hidden="true"></span>
          <span>${L.previews.features}${features.loading ? html` <${Spinner} quiet label=${L.previews.features_loading} />` : null}</span></div>`
      : null}
    ${shows && vector && features.data?.truncated ? html`<p class="legend-note warn">${L.previews.features_truncated}</p>` : null}
    ${features.problem ? html`<${ProblemView} problem=${features.problem} compact />` : null}
    ${info.reason
      ? html`<${PreviewReason} reason=${info.reason} shown=${info.state !== "unavailable" && info.state !== "failed"} />`
      : null}
    ${!shows && !info.reason ? html`<p class="legend-note">${L.previews.state[info.state] ?? L.previews.no_map}</p>` : null}
    ${own
      ? html`<${OwnCardLink} class="btn sm legend-card-link" project=${own.project} fileId=${own.fileId} label=${own.label}
          tab="preview" style=${style}><${Icon} name="file" size=${14} />${L.previews.open_card}</${OwnCardLink}>`
      : html`<${VersionCardLink} card=${card} style=${style} />`}
  `;
}

function VersionName({ info, card }) {
  return html`<div class="legend-file">
    <${Tech} value=${[["ref", info.ref]]}><b class="mono">${slotName(card.version.path)}</b></${Tech}>
    <span class="legend-sub">${[...new Set([card.version.data_year, card.version.label].filter(Boolean).map(String))].join(" · ")}</span>
  </div>`;
}

/** An own file on the map: its name, then the working file's change or the snapshot's date. */
function OwnName({ info, card, own }) {
  const sub = own.snapshot
    ? [t(O.map.snapshot_title, { label: own.snapshot.label }), own.snapshot.created_at ? day(own.snapshot.created_at) : null]
    : [O.map.working_title, stamp(card.modified_at)];
  return html`<div class="legend-file">
    <${Tech} value=${[["ref", info.ref]]}><b class="mono">${ownName(card.path)}</b></${Tech}>
    <span class="legend-sub">${sub.filter(Boolean).join(" · ")}</span>
  </div>`;
}

function VersionCardLink({ card, style }) {
  const route = useRoute();
  const params = {
    ...route.params,
    file: `${card.store}/${card.slot}`,
    file_version: card.version.path,
    file_tab: "preview",
    file_style: style,
  };
  return html`<${Link} class="btn sm legend-card-link" view=${route.view} params=${params}>
    <${Icon} name="file" size=${14} />${L.previews.open_card}
  </${Link}>`;
}

/**
 * „Przybliż, aby zobaczyć podgląd”: below the zoom of a preview's tiles.
 *
 * @param {{onZoom: () => void}} props
 */
export function ZoomHint({ onZoom }) {
  return html`<div class="map-hint-card float-card zoom-hint" role="status">
    <${Icon} name="search" size=${15} /><span>${L.previews.zoom_in}</span>
    <button type="button" class="btn sm" onClick=${onZoom}>${L.previews.zoom_action}</button>
  </div>`;
}

/** Whether a view meets a version's bounds (none: everywhere). */
function meets(view, bounds) {
  if (!bounds) return true;
  return view[0] <= bounds[2] && view[2] >= bounds[0] && view[1] <= bounds[3] && view[3] >= bounds[1];
}

/** A layer for people in its button's tooltip. */
function describeLayer(layer) {
  return [
    layer.subtitle,
    layer.coverage?.label,
    t(L.layers.units, { count: int(layer.units_count) }),
    layer.variant.formats.join(", "),
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * A layer's variant for people, without the file format (A-ADR-017): its
 * resolution and systems, e.g. „1m · PL-1992 · PL-EVRF2007-NH”; a variant
 * keyed by its segment (a field missing in the metadata) adds the segment.
 *
 * @param {import("../types.js").LayerVariant} variant
 * @returns {string}
 */
export function variantName(variant) {
  const parts = [
    variant.resolution,
    variant.horizontal_crs ? crsName(variant.horizontal_crs) : null,
    variant.vertical_crs ? crsName(variant.vertical_crs) : null,
  ].filter(Boolean);
  if (parts.length === 3) return parts.join(" · ");
  return [...parts, ...variant.segments].join(" · ") || L.layers.no_meta;
}

/**
 * Short names of the variants of layers sharing a title (two variants of
 * one year): the parts of the variant in which they differ, else their
 * segments.
 *
 * @param {import("../types.js").Layer[]} layers
 * @returns {Map<string, string>} By layer key; only layers sharing a title.
 */
function variantHints(layers) {
  const byTitle = new Map();
  for (const layer of layers) byTitle.set(layer.title, [...(byTitle.get(layer.title) ?? []), layer]);
  const hints = new Map();
  for (const same of byTitle.values()) {
    if (same.length < 2) continue;
    const fields = VARIANT_FIELDS.filter((field) => new Set(same.map((layer) => layer.variant[field])).size > 1);
    for (const layer of same) {
      const parts = fields
        .map((field) => layer.variant[field])
        .filter((value) => value !== null)
        .map((value) => (value.startsWith("EPSG:") ? crsName(value) : value));
      hints.set(layer.key, fields.length ? parts.join(" · ") || L.layers.no_meta : layer.variant.segments.join(", "));
    }
  }
  return hints;
}
