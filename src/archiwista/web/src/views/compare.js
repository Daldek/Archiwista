/**
 * „Porównanie” — two objects side by side (docs/SPEC.md 8.5 and UC-11; plan
 * v0.2 decision 10, steps 14 and 15). Not in the navigation: „Porównaj z…”
 * opens it from the file card (another version of the slot), from the card
 * of an own file (the working file and its snapshots, views/own.js) and from
 * „Szczegóły zestawu” (another year layer, step 13b).
 *
 * The sides are two `ref`s (`a`, `b`: store versions, own files and
 * snapshots) or two year layers of `/local-layers` (`a_layer`, `b_layer`
 * with the set's `store`, `product`, `area_id` and `group`). The centre is
 * the comparison map (map/compare.js): the curtain, the fade or two maps
 * side by side (`mode`), at the address's position (`center`, `zoom`) or
 * framing both sides; raster sides in one style (`style`) and, for a colour
 * ramp, on one range of values. The right panel names both sides with the
 * state and build of their previews and their cards, then the table: the
 * rows of `GET /compare` (level 1) or — for two year layers — their
 * summaries side by side. Differences are marked, „tylko różnice”
 * (`only_diff`) hides the rest and „Eksportuj CSV” saves the rows shown,
 * made in the browser: the server writes nothing. Two sides with vector
 * layers (own data) also show the differences of their schema: layers only
 * in A or B, objects per layer, fields added, removed and changed.
 */

import { buildLinked, getComparison, getLinked, getLocalLayers, getVersion } from "../api.js";
import { useApp } from "../context.js";
import { day, int, size, stamp } from "../format.js";
import { NARROW, useResource } from "../hooks.js";
import { compare as L } from "../labels/compare.js";
import { T, t } from "../labels/index.js";
import { previews as P } from "../labels/previews.js";
import { commonScale, CompareMaps, MODES, sharedStyles, SIDES, sideTiles } from "../map/compare.js";
import { geometryBounds, readPosition, unionBounds } from "../map/geo.js";
import {
  chosenStyle,
  layerTiles,
  readVersionRef,
  shownFrom,
  tilesShown,
  useFeatures,
  useLayerLegend,
  ZoomHint,
} from "../map/previews.js";
import { OwnCardLink, useOwnFile } from "../map/own.js";
import { availableBasemaps, pickBasemap } from "../map/style.js";
import { ViewLayout } from "../panels.js";
import { BuildSection, PreviewLegend, PreviewReason, styleName, useBuild } from "../previews.js";
import { Link, setParams } from "../router.js";
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
  useMemo,
  useRef,
  useState,
} from "../ui.js";
import { crsName, FileLink, JobStatus, useJob } from "./cards.js";

// Notes, legend sections and swatches of the map view, then the comparison's own.
await loadStylesheet(new URL("../map/map.css", import.meta.url));
await loadStylesheet(new URL("./compare.css", import.meta.url));

/** Address parameters of the sides as `ref`s copied from answers. */
const REF_PARAMS = ["a", "b"];
/** Address parameters of the sides as year layers (`Layer.key`). */
const LAYER_PARAMS = ["a_layer", "b_layer"];
const MODE_PARAM = "mode";
const STYLE_PARAM = "style";
const ONLY_PARAM = "only_diff";
const ISO_DAY = /^\d{4}-\d{2}-\d{2}/;
const PERCENT = new Intl.NumberFormat("pl-PL", { style: "percent", maximumFractionDigits: 1 });
// Fields shown for people with the raw value a click away (the CSV keeps the
// raw one); a value of an unexpected type stays raw.
const asDay = (value) => (typeof value === "string" && ISO_DAY.test(value) ? day(value) : null);
const asStamp = (value) =>
  typeof value === "string" && ISO_DAY.test(value) && !Number.isNaN(Date.parse(value)) ? stamp(value) : null;
const asSize = (value) => (typeof value === "number" ? size(value) : null);
const asInt = (value) => (typeof value === "number" ? int(value) : null);
const asCrs = (value) => (typeof value === "string" ? crsName(value) : null);
const asShare = (value) => (typeof value === "number" ? PERCENT.format(value) : null);
const SHOWN = {
  data_date: asDay,
  downloaded_at: asStamp,
  created_at: asStamp,
  modified_at: asStamp,
  first_seen_at: asStamp,
  changed_at: asStamp,
  size_bytes: asSize,
  feature_count: asInt,
  coverage: asShare,
  horizontal_crs: asCrs,
  vertical_crs: asCrs,
  crs: asCrs,
};
// Two year layers side by side: one row per field (`layer_fields` of the labels).
const LAYER_FIELDS = [
  ["title", (layer) => layer.title],
  ["subtitle", (layer) => layer.subtitle],
  ["data_dates", (layer) => layer.data_dates.join(", ") || null],
  ["campaigns", (layer) => layer.campaigns.join(", ") || null],
  ["versions_count", (layer) => layer.versions_count],
  ["units_count", (layer) => layer.units_count],
  ["coverage", (layer) => layer.coverage?.label ?? null],
  ["horizontal_crs", (layer) => layer.variant.horizontal_crs],
  ["vertical_crs", (layer) => layer.variant.vertical_crs],
  ["resolution", (layer) => layer.variant.resolution],
  ["formats", (layer) => layer.variant.formats.join(", ") || null],
  ["segments", (layer) => layer.variant.segments.join(", ") || null],
  [
    "previews",
    (layer) => (layer.preview ? t(L.layer_previews, { ready: layer.preview.ready, total: layer.preview.total }) : null),
  ],
  ["key", (layer) => layer.key],
];
// Neutralize spreadsheet formulas in every CSV cell before quoting, not only
// values: sidecar keys, labels and group names can also come from a producer.
const FORMULA = /^[=+\-@\t\r\n]/;
// A side without a preview address: nothing is loaded or built.
const NO_SOURCE = { key: "", load: () => Promise.resolve(null), build: () => Promise.resolve(null) };

/**
 * The comparison view.
 *
 * @param {{route: import("../router.js").Route}} props
 */
export default function CompareScreen({ route }) {
  const params = route.params;
  if (REF_PARAMS.every((name) => params[name])) return html`<${RefCompare} params=${params} />`;
  if (LAYER_PARAMS.every((name) => params[name]) && params.store && params.product && params.area_id) {
    return html`<${LayerCompare} params=${params} />`;
  }
  return html`<${CompareEmpty} params=${params} />`;
}

/** Two `ref`s: the rows of `/compare` and each side's preview on its map. */
function RefCompare({ params }) {
  const stage = useStage(params);
  const key = `${params.a}\n${params.b}`;
  const answer = useResource(
    (signal) => getComparison(params.a, params.b, { signal }).then((data) => ({ key, data })),
    [key, stage.indexKey],
  );
  const comparison = answer.data?.key === key ? answer.data.data : null;
  const sides = comparison ? [comparison.a, comparison.b] : [null, null];
  const previews = [useSidePreview(sides[0], stage.indexKey), useSidePreview(sides[1], stage.indexKey)];
  const cards = [useVersionCard(sides[0]), useVersionCard(sides[1])];
  const infos = previews.map((preview) => preview.info);

  // One style for both sides when they share it; a ramp on one range.
  const styles = sharedStyles(infos);
  const usual = styles.includes(infos[0]?.default_style) ? infos[0].default_style : (styles[0] ?? null);
  const style = styles.includes(params[STYLE_PARAM]) ? params[STYLE_PARAM] : usual;
  const scale = commonScale(infos, style);
  const shownStyles = infos.map((info) => (style && info?.styles.includes(style) ? style : chosenStyle(info, null)));
  const rescale = scale ? scale.rescale.join(",") : "";
  const sources = useMemo(
    () => infos.map((info, index) => sideTiles(info, shownStyles[index], scale?.rescale ?? null)),
    [infos[0], infos[1], shownStyles.join(), rescale],
  );
  const features = [useFeatures(infos[0], stage.move), useFeatures(infos[1], stage.move)];
  const bounds = unionBounds([
    ...sides.map((side) => (side?.outline ? geometryBounds(side.outline) : null)),
    ...infos.map((info) => info?.bounds ?? null),
  ]);
  useFraming(stage, [...REF_PARAMS.map((name) => params[name])].sort().join("\n"), bounds);

  const mapSides = sides.map((side, index) => ({
    name: side?.title ?? "…",
    title: side?.title ?? "",
    tiles: sources[index],
    outline: side?.outline ?? null,
    features: features[index].data,
  }));
  const notes = stageNotes(stage, sources);
  if (answer.error && !comparison) notes.unshift(problemNote("compare", answer.error.problem));
  infos.forEach((info, index) => {
    if (info && mapShows(info) === "none") notes.push(sideNote(SIDES[index]));
  });
  for (const [index, item] of features.entries()) {
    if (item.problem) notes.push(problemNote(`features-${index}`, item.problem));
  }

  const panel = html`<div class="cmp-panel">
    ${answer.error && !comparison ? html`<${ProblemView} problem=${answer.error.problem} />` : null}
    ${!comparison && !answer.error ? html`<${Spinner} label=${L.table.loading} />` : null}
    ${comparison
      ? html`<section class="cmp-sides" aria-label=${L.side.sides}>
            ${SIDES.map(
              (letter, index) => html`<${RefSide} key=${letter} letter=${letter} side=${sides[index]}
                preview=${previews[index]} card=${cards[index]} />`,
            )}
          </section>
          <${CompareTable} title=${L.table.title} rows=${comparison.rows} same=${comparison.same_content}
            titles=${sides.map((side) => side.title)} only=${params[ONLY_PARAM] === "1"} />
          ${comparison.schema_diff ? html`<${SchemaDiff} diff=${comparison.schema_diff} />` : null}`
      : null}
  </div>`;
  const toolbar = html`<${Toolbar} stage=${stage} styles=${styles} style=${style}
    onSwap=${() => setParams({ a: params.b, b: params.a }, { replace: true })} />`;
  return html`<${CompareBody} stage=${stage} toolbar=${toolbar} sides=${mapSides} notes=${notes}
    legend=${html`<${CompareLegend} rows=${refLegend(infos, shownStyles, scale, sides)} />`} panel=${panel} />`;
}

/** Two year layers of one set: their tiles and summaries side by side. */
function LayerCompare({ params }) {
  const stage = useStage(params);
  const query = { store: params.store, product: params.product, area_id: params.area_id, group: params.group || null };
  const setKey = [query.store, query.product, query.area_id, query.group ?? ""].join("\n");
  const answer = useResource(
    (signal) => getLocalLayers(query, { signal }).then((set) => ({ key: setKey, set })),
    [setKey, stage.indexKey],
  );
  const set = answer.data?.key === setKey ? answer.data.set : null;
  const keys = LAYER_PARAMS.map((name) => params[name]);
  const layers = keys.map((key) => set?.layers.find((layer) => layer.key === key) ?? null);
  const jobs = [useLayerJob(layers[0], answer.reload), useLayerJob(layers[1], answer.reload)];
  const legends = [useLayerLegend(layers[0]), useLayerLegend(layers[1])];
  const sources = useMemo(() => layers.map(layerTiles), [layers[0], layers[1]]);
  const bounds = unionBounds(layers.flatMap((layer) => (layer?.versions ?? []).map((version) => version.bounds)));
  useFraming(stage, `${setKey}\n${[...keys].sort().join("\n")}`, bounds);

  const mapSides = layers.map((layer, index) => ({
    name: layer?.title ?? keys[index],
    title: layer ? `${layer.title} · ${layer.subtitle}` : keys[index],
    tiles: sources[index],
    outline: null,
    features: null,
  }));
  const notes = stageNotes(stage, sources);
  if (answer.error) notes.unshift(problemNote("layers", answer.error.problem));
  layers.forEach((layer, index) => {
    if (layer?.preview?.state === "unavailable") notes.push(sideNote(SIDES[index]));
  });
  const rows = layers.every(Boolean) ? layerRows(layers) : null;

  const panel = html`<div class="cmp-panel">
    ${answer.error && !set ? html`<${ProblemView} problem=${answer.error.problem} />` : null}
    ${!set && !answer.error ? html`<${Spinner} label=${L.table.layers_loading} />` : null}
    ${set
      ? html`<section class="cmp-sides" aria-label=${L.side.sides}>
          ${SIDES.map(
            (letter, index) => html`<${LayerSide} key=${letter} letter=${letter} param=${LAYER_PARAMS[index]}
              wanted=${keys[index]} layer=${layers[index]} set=${set} job=${jobs[index]} />`,
          )}
        </section>`
      : null}
    ${rows
      ? html`<${CompareTable} title=${L.table.layers_title} rows=${rows} same=${false}
          titles=${mapSides.map((side) => side.title)} only=${params[ONLY_PARAM] === "1"} />`
      : null}
  </div>`;
  const toolbar = html`<${Toolbar} stage=${stage} styles=${[]} style=${null}
    onSwap=${() => setParams({ a_layer: params.b_layer, b_layer: params.a_layer }, { replace: true })} />`;
  return html`<${CompareBody} stage=${stage} toolbar=${toolbar} sides=${mapSides} notes=${notes}
    legend=${html`<${CompareLegend} rows=${sideLegends(legends)} />`} panel=${panel} />`;
}

/** Without both sides: how a comparison is opened. */
function CompareEmpty({ params }) {
  const layers = LAYER_PARAMS.some((name) => params[name]);
  const partial = layers || REF_PARAMS.some((name) => params[name]);
  return html`<div class="page view-message cmp-empty">
    <h2>${L.empty.title}</h2>
    ${partial ? html`<p class="hint warn" role="alert">${layers ? L.empty.layers : L.empty.missing}</p>` : null}
    <p class="muted">${L.empty.text}</p>
    <div class="det-actions">
      <${Link} class="btn primary" view="map"><${Icon} name="map" />${L.empty.map}</${Link}>
      <${Link} class="btn" view="catalog"><${Icon} name="table" />${L.empty.catalog}</${Link}>
    </div>
  </div>`;
}

// The view's frame --------------------------------------------------------------

/**
 * What both kinds of comparison share: the map's start and moves, its
 * mode, the panel, the basemap and the index's state.
 */
function useStage(params) {
  const { settings, settingsError, preferences, preferencesError, health } = useApp();
  const [start] = useState(() => readPosition(params));
  const [panel, setPanel] = useState(() => !window.matchMedia(NARROW).matches);
  const [move, setMove] = useState(null);
  const [mapApi, setMapApi] = useState(null);
  const userMoved = useRef(false);
  return {
    start,
    panel,
    setPanel,
    move,
    mapApi,
    setMapApi,
    userMoved,
    // The maps start with the basemap: they wait for the settings and the preferences.
    settled:
      (settings !== undefined || settingsError !== undefined) &&
      (preferences !== undefined || preferencesError !== undefined),
    basemap: settings ? pickBasemap(availableBasemaps(settings), preferences?.basemap ?? null) : null,
    indexKey: (health?.stores ?? []).map((item) => `${item.store}:${item.state.indexed_at ?? ""}`).join(","),
    mode: MODES.includes(params[MODE_PARAM]) ? params[MODE_PARAM] : MODES[0],
    onMove: (next) => {
      if (next.byUser) userMoved.current = true;
      setMove(next);
      setParams(next.position, { replace: true });
    },
  };
}

/**
 * Frame both sides once per pair — not a shared link's position, nor after
 * the person moved the map.
 */
function useFraming(stage, key, bounds) {
  const framed = useRef(stage.start ? key : null);
  useEffect(() => {
    if (!stage.mapApi || !bounds || framed.current === key || stage.userMoved.current) return;
    framed.current = key;
    stage.mapApi.fit(bounds, { animate: false });
  }, [stage.mapApi, key, bounds ? bounds.join() : ""]);
}

function CompareBody({ stage, toolbar, sides, notes, legend, panel }) {
  return html`<${ViewLayout} id="compare"
    right=${{ label: L.panel, open: stage.panel, onClose: () => stage.setPanel(false), content: panel }}>
    <div class="cmp-view">
      ${toolbar}
      <div class="center-body">
        ${stage.settled
          ? html`<${CompareMaps} basemap=${stage.basemap} start=${stage.start} mode=${stage.mode}
              sides=${sides} onReady=${stage.setMapApi} onMove=${stage.onMove}>
              ${notes.length ? html`<div class="map-notes">${notes}</div>` : null}
              ${legend}
            </${CompareMaps}>`
          : html`<div class="page"><${Spinner} /></div>`}
      </div>
    </div>
  </${ViewLayout}>`;
}

function Toolbar({ stage, styles, style, onSwap }) {
  return html`<div class="center-bar cmp-bar">
    <${Seg} label=${L.toolbar.modes_label} value=${stage.mode}
      onChange=${(mode) => setParams({ [MODE_PARAM]: mode === MODES[0] ? null : mode }, { replace: true })}
      options=${MODES.map((mode) => ({ value: mode, label: L.toolbar.modes[mode], title: L.toolbar.mode_titles[mode] }))} />
    ${styles.length > 1
      ? html`<${Seg} small label=${P.styles_label} value=${style}
          onChange=${(value) => setParams({ [STYLE_PARAM]: value }, { replace: true })}
          options=${styles.map((value) => ({ value, label: styleName(value) }))} />`
      : null}
    <button type="button" class="btn ghost cmp-swap" title=${L.toolbar.swap_title} onClick=${onSwap}>
      <${Icon} name="rotate" size=${15} />${L.toolbar.swap}
    </button>
    <button type="button" class=${`btn ${stage.panel ? "ghost" : "active"}`} aria-controls="compare-right"
      aria-expanded=${stage.panel ? "true" : "false"} title=${L.toolbar.details_toggle}
      onClick=${() => stage.setPanel(!stage.panel)}>
      <${Icon} name="sidebar" size=${17} />${L.toolbar.details}
    </button>
  </div>`;
}

/** Notes over the map: below the zoom of a side's tiles, „Przybliż”. */
function stageNotes(stage, sources) {
  const notes = [];
  const hidden = stage.move ? sources.filter((source) => source && !tilesShown(source, stage.move.zoom)) : [];
  if (hidden.length) {
    notes.push(html`<${ZoomHint} key="zoom" onZoom=${() =>
      stage.mapApi?.zoomTo(Math.max(...hidden.map(shownFrom)), unionBounds(hidden.map((source) => source.bounds ?? null)))} />`);
  }
  return notes;
}

function problemNote(key, problem) {
  return html`<div key=${key} class="float-card map-problem"><${ProblemView} problem=${problem} compact /></div>`;
}

function sideNote(letter) {
  return html`<p key=${`nothing-${letter}`} class="float-card map-hint-card cmp-note" role="status">
    ${t(L.map.nothing, { side: L.side[letter] })}</p>`;
}

// Sides ------------------------------------------------------------------------

/**
 * The preview of a side from the address its answer gave
 * (`ComparisonSide.preview`), built by itself within the auto-build limits
 * and followed while it builds (previews.js `useBuild`). Any kind of side
 * with such an address works the same.
 */
function useSidePreview(side, dataKey) {
  const address = side?.preview ?? null;
  const source = useMemo(
    () =>
      address
        ? {
            key: side.ref,
            load: (signal) => getLinked(address, { signal }),
            build: (force) => buildLinked(address, { force }),
          }
        : NO_SOURCE,
    [side?.ref ?? "", address ?? ""],
  );
  const answer = useResource(
    (signal) => (address ? source.load(signal).then((info) => ({ key: source.key, info })) : Promise.resolve(null)),
    [source.key, address ?? "", dataKey],
  );
  const info = address && answer.data?.key === source.key ? answer.data.info : null;
  const build = useBuild(source, info, answer.reload);
  return { info, build, loading: Boolean(address) && answer.loading, error: address ? answer.error : undefined };
}

/** The card of a version side (its store and slot open the file card). */
function useVersionCard(side) {
  const target = side?.kind === "version" ? readVersionRef(side.ref) : null;
  const { data } = useResource(
    (signal) => (target ? getVersion(target.store, target.path, { signal }) : Promise.resolve(null)),
    [target ? side.ref : ""],
  );
  return target && data?.store === target.store && data.version.path === target.path ? data : null;
}

/** A layer's build of its missing previews, followed; the layers are read again after it. */
function useLayerJob(layer, reload) {
  const job = useJob({ onEnd: reload });
  const building = layer?.preview?.state === "building" ? (layer.preview.job?.id ?? null) : null;
  useEffect(() => {
    if (building) job.follow(building, "preview");
  }, [building]);
  return job;
}

/** What a preview shows on a map: `tiles`, `features`, `pending` (a build first) or `none`. */
function mapShows(info) {
  if (info.state === "needs_build" || info.state === "building") return "pending";
  if (info.state !== "ready") return "none";
  if (info.features_url) return "features";
  return info.tiles_url ? "tiles" : "none";
}

function SideHead({ letter, title, tech, kind }) {
  return html`<header class="cmp-side-head">
    <b class=${`cmp-letter ${letter}`} aria-hidden="true">${L.side[letter]}</b>
    <div class="cmp-side-name">
      <${Tech} value=${tech}><b class="cmp-side-title">${title}</b></${Tech}>
      <span class="faint">${kind}</span>
    </div>
  </header>`;
}

function RefSide({ letter, side, preview, card }) {
  const info = preview.info;
  const shows = info ? mapShows(info) : null;
  return html`<article class=${`cmp-side ${letter}`} aria-label=${t(L.side.label, { side: L.side[letter] })}>
    <${SideHead} letter=${letter} title=${side.title} tech=${[["ref", side.ref]]}
      kind=${L.side.kind[side.kind] ?? side.kind} />
    ${preview.error && !info ? html`<${ProblemView} problem=${preview.error.problem} compact />` : null}
    ${side.preview && !info && !preview.error ? html`<${Spinner} label=${L.side.loading} />` : null}
    ${shows === "tiles"
      ? html`<p class="cmp-side-map">${t(L.side.on_map_tiles, { minzoom: info.minzoom ?? "–", maxzoom: info.maxzoom ?? "–" })}</p>`
      : null}
    ${shows === "features" ? html`<p class="cmp-side-map">${L.side.on_map_features}</p>` : null}
    ${shows === "none" && !info.reason ? html`<p class="cmp-side-map">${L.side.no_map}</p>` : null}
    ${info?.reason ? html`<${PreviewReason} reason=${info.reason} shown=${shows !== "none"} />` : null}
    ${info ? html`<${BuildSection} info=${info} build=${preview.build} loading=${preview.loading} />` : null}
    ${card
      ? html`<div class="cmp-side-actions">
          <${FileLink} class="btn sm" store=${card.store} slot=${card.slot} version=${card.version.path}
            title=${t(L.side.card_title, { side: L.side[letter] })}>
            <${Icon} name="file" size=${14} />${L.side.card}
          </${FileLink}>
        </div>`
      : null}
    ${side.kind === "file" || side.kind === "snapshot" ? html`<${OwnSideCard} letter=${letter} side=${side} />` : null}
  </article>`;
}

/**
 * „Karta pliku” of an own file's or snapshot's side: the card of the file
 * (views/own.js), on that version, over the comparison. A ref names the
 * file by its path: its `file_id` comes from the project's file list.
 */
function OwnSideCard({ letter, side }) {
  const { parts, file } = useOwnFile(side.ref);
  if (!parts || !file) return null;
  return html`<div class="cmp-side-actions">
    <${OwnCardLink} class="btn sm" project=${parts.project} fileId=${file.file_id} label=${parts.label}
      title=${t(L.own_card_title, { side: L.side[letter] })}>
      <${Icon} name="file" size=${14} />${L.side.card}
    </${OwnCardLink}>
  </div>`;
}

/**
 * The differences of two sides' vector layers (`schema_diff`): layers only
 * in A or in B, then each layer of both with its objects and its fields
 * added, removed and of another type — A changed into B.
 *
 * @param {{diff: import("../types.js").SchemaDiff}} props
 */
function SchemaDiff({ diff }) {
  const S = L.schema;
  const changed = diff.layers.filter(
    (layer) => layer.fields_added.length || layer.fields_removed.length || layer.fields_changed.length,
  );
  const same = !diff.layers_only_a.length && !diff.layers_only_b.length && !changed.length;
  const fields = (items) => items.map((field) => `${field.name} (${field.type})`).join(", ");
  return html`<section class="cmp-table-sec cmp-schema" aria-labelledby="cmp-schema-title">
    <div class="cmp-table-head"><h3 class="section-title" id="cmp-schema-title">${S.title}</h3></div>
    <p class="hint">${S.hint}</p>
    ${diff.layers_only_a.length
      ? html`<p class="cmp-schema-row differs"><b>${S.only_a}:</b> <span class="mono">${diff.layers_only_a.join(", ")}</span></p>`
      : null}
    ${diff.layers_only_b.length
      ? html`<p class="cmp-schema-row differs"><b>${S.only_b}:</b> <span class="mono">${diff.layers_only_b.join(", ")}</span></p>`
      : null}
    <ul class="cmp-schema-layers">
      ${diff.layers.map((layer) => {
        const counts =
          layer.feature_count_a === layer.feature_count_b
            ? t(S.same_objects, { count: int(layer.feature_count_a) })
            : t(S.objects, { a: int(layer.feature_count_a), b: int(layer.feature_count_b) });
        const differs = layer.fields_added.length || layer.fields_removed.length || layer.fields_changed.length;
        return html`<li key=${layer.name} class=${differs ? "cmp-schema-layer differs" : "cmp-schema-layer"}>
          <p><b>${S.layer}</b> <span class="mono">${layer.name}</span> · <span class="tabular">${counts}</span></p>
          ${layer.fields_added.length ? html`<p><b>${S.added}:</b> <span class="mono">${fields(layer.fields_added)}</span></p>` : null}
          ${layer.fields_removed.length ? html`<p><b>${S.removed}:</b> <span class="mono">${fields(layer.fields_removed)}</span></p>` : null}
          ${layer.fields_changed.length
            ? html`<p><b>${S.changed}:</b> <span class="mono">${layer.fields_changed.map((field) => t(S.change, field)).join(", ")}</span></p>`
            : null}
          ${differs ? null : html`<p class="faint">${S.unchanged}</p>`}
        </li>`;
      })}
    </ul>
    ${same ? html`<p class="faint">${S.none}</p>` : null}
  </section>`;
}

function LayerSide({ letter, param, wanted, layer, set, job }) {
  const preview = layer?.preview ?? null;
  const following = job.running && job.id === preview?.job?.id;
  let note = null;
  if (preview?.state === "unavailable") note = L.side.layer_unavailable;
  else if (preview?.state === "needs_build") note = L.side.layer_needs_build;
  else if (preview?.state === "building" && !following) note = L.side.layer_building;
  return html`<article class=${`cmp-side ${letter}`} aria-label=${t(L.side.label, { side: L.side[letter] })}>
    <${SideHead} letter=${letter} title=${layer?.title ?? wanted} tech=${[["layer", wanted]]}
      kind=${layer?.subtitle ?? L.side.kind.layer} />
    <label class="field cmp-choose">
      <span>${t(L.side.choose, { side: L.side[letter] })}</span>
      <select value=${wanted} onChange=${(event) => setParams({ [param]: event.currentTarget.value }, { replace: true })}>
        ${layer ? null : html`<option value=${wanted}>${wanted}</option>`}
        ${set.layers.map((item) => html`<option key=${item.key} value=${item.key}>${item.title} · ${item.subtitle}</option>`)}
      </select>
    </label>
    ${layer ? null : html`<p class="hint warn" role="alert">${t(L.side.layer_missing, { key: wanted })}</p>`}
    ${preview ? html`<p class="cmp-side-map">${t(L.side.layer_ready, { ready: int(preview.ready), total: int(preview.total) })}</p>` : null}
    ${note ? html`<p class="hint">${note}</p>` : null}
    ${following ? html`<${JobStatus} job=${job} />` : null}
  </article>`;
}

function layerRows(layers) {
  return LAYER_FIELDS.map(([field, read]) => {
    const [a, b] = layers.map(read);
    return { group: "layer", field, label: L.layer_fields[field], a, b, differs: a !== b };
  });
}

// Legend -----------------------------------------------------------------------

/**
 * The legend card over the maps (closed at first on a phone).
 *
 * @param {{rows: Array<*>}} props
 */
function CompareLegend({ rows }) {
  const id = useId();
  const [open, setOpen] = useState(() => !window.matchMedia(NARROW).matches);
  if (!rows.length) return null;
  const action = open ? L.legend.hide : L.legend.show;
  return html`<section class=${`legend map-legend float-card cmp-legend ${open ? "" : "closed"}`}
    aria-labelledby=${`${id}-title`}>
    <button type="button" class="legend-title" aria-expanded=${open ? "true" : "false"}
      aria-controls=${`${id}-rows`} title=${action} onClick=${() => setOpen(!open)}>
      <span id=${`${id}-title`}>${L.legend.title}</span><${Icon} name=${open ? "down" : "chevron"} size=${14} />
    </button>
    <div id=${`${id}-rows`} class="legend-rows" hidden=${!open}>${rows}</div>
  </section>`;
}

/** Legends of both sides: one for a shared range or equal legends, else each. */
function sideLegends(legends) {
  const [a, b] = legends;
  if (a && b && JSON.stringify(a) === JSON.stringify(b)) return [legendSection("both", L.legend.both, a)];
  return legends.flatMap((legend, index) =>
    legend ? [legendSection(SIDES[index], t(L.legend.side, { side: L.side[SIDES[index]] }), legend)] : [],
  );
}

function legendSection(key, title, legend) {
  return html`<div key=${key} class="legend-section cmp-legend-side"><b>${title}</b><${PreviewLegend} legend=${legend} /></div>`;
}

function refLegend(infos, shownStyles, scale, sides) {
  const rows = [];
  if (scale) {
    rows.push(html`<div key="scale" class="legend-section">
      <p class="legend-note">${L.legend.common_scale}</p><${PreviewLegend} legend=${scale.legend} />
    </div>`);
  } else {
    rows.push(
      ...sideLegends(infos.map((info, index) => (info && mapShows(info) === "tiles" ? (info.legends[shownStyles[index]] ?? null) : null))),
    );
  }
  infos.forEach((info, index) => {
    if (info && mapShows(info) === "features") {
      rows.push(html`<div key=${`features-${index}`} class="legend-row"><span class="sw sw-features" aria-hidden="true"></span>
        ${t(L.legend.features, { side: L.side[SIDES[index]] })}</div>`);
    }
  });
  if (sides.some((side) => side?.outline)) {
    rows.push(html`<div key="outline" class="legend-row"><span class="sw sw-preview-outline" aria-hidden="true"></span>
      ${L.legend.outline}</div>`);
  }
  return rows;
}

// The table ---------------------------------------------------------------------

/**
 * Rows of both sides, grouped, differences marked; „tylko różnice” and the
 * CSV of the rows shown.
 *
 * @param {{title: string, rows: import("../types.js").ComparisonRow[]|Array<object>,
 *   same: boolean, titles: string[], only: boolean}} props - `titles`: A's and
 *   B's names for the CSV's header.
 */
function CompareTable({ title, rows, same, titles, only }) {
  const id = useId();
  const shown = only ? rows.filter((row) => row.differs) : rows;
  const differs = rows.filter((row) => row.differs).length;
  return html`<section class="cmp-table-sec" aria-labelledby=${`${id}-title`}>
    <div class="cmp-table-head">
      <h3 class="section-title" id=${`${id}-title`}>${title}</h3>
      <span class="cmp-summary">${t(L.table.summary, { differs: int(differs), total: int(rows.length) })}</span>
    </div>
    ${same ? html`<p class="hint cmp-same" role="note">${L.table.same_content}</p>` : null}
    <div class="cmp-table-tools">
      <label class="check-field cmp-only">
        <input type="checkbox" checked=${only}
          onChange=${(event) => setParams({ [ONLY_PARAM]: event.currentTarget.checked ? "1" : null }, { replace: true })} />
        ${L.table.only_diff}
      </label>
      <button type="button" class="btn sm" title=${L.table.export_title} disabled=${!shown.length}
        onClick=${() => saveCsv(shown, titles)}>
        <${Icon} name="file" size=${14} />${L.table.export}
      </button>
    </div>
    ${shown.length
      ? html`<div class="table-wrap cmp-table-wrap">
          <table class="cmp-table">
            <caption class="visually-hidden">${L.table.caption}</caption>
            <thead>
              <tr><th scope="col">${L.table.field}</th><th scope="col">${L.side.a}</th><th scope="col">${L.side.b}</th></tr>
            </thead>
            ${groupRows(shown).map(
              ([group, items]) => html`<tbody key=${group}>
                <tr class="cmp-group"><th scope="colgroup" colspan="3">${L.table.groups[group] ?? group}</th></tr>
                ${items.map(
                  (row) => html`<tr key=${row.field} class=${row.differs ? "diff" : ""}>
                    <th scope="row" class=${row.group === "sidecar" ? "mono" : ""}>
                      ${row.differs
                        ? html`<span class="cmp-mark" title=${L.table.differs_title}>≠<span class="visually-hidden"> ${L.table.differs}</span></span>`
                        : null}
                      ${row.label}
                    </th>
                    <td><${CellValue} row=${row} value=${row.a} /></td>
                    <td><${CellValue} row=${row} value=${row.b} /></td>
                  </tr>`,
                )}
              </tbody>`,
            )}
          </table>
        </div>`
      : html`<p class="hint">${only ? L.table.none_shown : L.table.none}</p>`}
  </section>`;
}

/** Rows by group, in the order of their first row. */
function groupRows(rows) {
  const groups = new Map();
  for (const row of rows) groups.set(row.group, [...(groups.get(row.group) ?? []), row]);
  return [...groups];
}

/**
 * A value for people: a dash for none, „tak”/„nie”, a known field shown
 * readable (`SHOWN`) with the raw value a click away; a raw sidecar's value
 * stays as it is (A-ADR-014).
 */
function CellValue({ row, value }) {
  if (value === null || value === undefined) return html`<span class="faint">${T.common.empty}</span>`;
  if (typeof value === "boolean") return value ? L.table.yes : L.table.no;
  const raw = String(value);
  let shown = null;
  if (row.group === "layers") shown = asInt(value);
  else if (row.group !== "sidecar") shown = SHOWN[row.field]?.(value) ?? null;
  if (shown !== null && shown !== raw) return html`<${Tech} value=${raw}>${shown}</${Tech}>`;
  return html`<span class=${row.group === "sidecar" ? "mono" : ""}>${raw}</span>`;
}

// CSV -------------------------------------------------------------------------

/**
 * Save rows as CSV (RFC 4180, UTF-8 with a BOM for spreadsheets, comma,
 * CRLF): group, field, its name, the raw values of A and B (dates ISO,
 * numbers with a dot, „tak”/„nie”) and whether they differ.
 */
function saveCsv(rows, titles) {
  const C = L.table.csv;
  const lines = [
    [C.group, C.field, C.label, t(C.a, { title: titles[0] }), t(C.b, { title: titles[1] }), C.differs],
    ...rows.map((row) => [
      L.table.groups[row.group] ?? row.group,
      row.field,
      row.label,
      csvValue(row.a),
      csvValue(row.b),
      row.differs ? L.table.yes : L.table.no,
    ]),
  ];
  const text = `\ufeff${lines.map((cells) => cells.map(csvCell).join(",")).join("\r\n")}\r\n`;
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = csvName(titles);
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? L.table.yes : L.table.no;
  return typeof value === "number" ? value : String(value);
}

function csvCell(text) {
  const safe = typeof text === "number" || !FORMULA.test(text) ? String(text) : `'${text}`;
  return /[",\r\n]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

/** `porownanie-<A>-<B>.csv` with the sides' names in safe letters. */
function csvName(titles) {
  const slug = (text) =>
    text
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^A-Za-z0-9._-]+/g, "_")
      .replace(/^[_.]+|[_.]+$/g, "")
      .slice(0, 60);
  return `${[L.table.csv.file, ...titles.map(slug)].filter(Boolean).join("-")}.csv`;
}
