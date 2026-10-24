/**
 * „Wachlarz” (docs/SPEC.md 5.4, 6.5 c; A-ADR-018 errata 1; plan v0.2 step
 * 13a): the layers of a `LayerSet` — a product's years, editions or
 * campaigns in the area, newest first — as thumbnails of the area on an arc
 * like a stack in the macOS dock (fan/layout.js), each whole in its own
 * place, the chosen one enlarged on the arc and, where the stage has room,
 * large beside it.
 *
 * A thumbnail is SVG: the layer's image the server composes in the area's
 * planar frame (`thumbnail_url`, fetched with the session's header into a
 * `blob:` address) under the outlines of its sheets (`outlines`, the same
 * frame) — solid where a sheet's preview is ready, dashed and tinted where
 * it is still missing. The caption: the title (year), the local coverage
 * („lokalnie 83% obszaru”), the variant with its formats as badges, the
 * number of campaigns and the state of the previews. A click, `Enter` or
 * `Spacja` chooses a layer — `layer` of the address, one choice with the
 * map, the timeline and the details panel; arrows move between the layers
 * (ARIA listbox).
 *
 * Any `LayerSet` fits: the map view gives the store's layers of the area; an
 * own file's working file and snapshots (`GET /projects/{project}/files/
 * {file_id}/layers`, plan v0.2 step 15) take the same props with their own
 * `heading`.
 */

import { apiAddress } from "../api.js";
import { count } from "../format.js";
import { useSize } from "../hooks.js";
import { fan as F } from "../labels/fan.js";
import { t } from "../labels/index.js";
import { map as M } from "../labels/map.js";
import { CAMPAIGN_GROUP, variantName } from "../map/previews.js";
import { usePreviewImage } from "../previews.js";
import {
  html,
  Icon,
  loadStylesheet,
  ProblemView,
  Seg,
  Spinner,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "../ui.js";
import { JobStatus } from "../views/cards.js";
import { CoverageBadge, describeLayer, Formats, layerFacts, staleText } from "../views/set-details.js";
import { fanLayout, PREVIEW_HEAD, thumbnailSize } from "./layout.js";

await loadStylesheet(new URL("./fan.css", import.meta.url));

/** Width of a thumbnail's drawing in its own units (its `viewBox`). */
const PLATE = 400;
/** Height over width of a thumbnail without a frame, and the limits of any frame's. */
const DEFAULT_ASPECT = 0.75;
const MIN_ASPECT = 0.25;
const MAX_ASPECT = 4;

/**
 * The Wachlarz of a set of layers.
 *
 * @param {object} props
 * @param {import("../types.js").LayerSet|null} props.set
 * @param {string|null} props.chosen - Key of the chosen layer (`layer`).
 * @param {(key: string) => void} props.onChoose
 * @param {boolean} [props.loading]
 * @param {import("../api.js").ApiError} [props.error]
 * @param {ReturnType<import("../views/cards.js").useJob>|null} [props.job] - The
 *   build `useLayers` follows: its progress shows under the chosen layer.
 * @param {string|null} [props.group] - `CAMPAIGN_GROUP` or none (years).
 * @param {((group: string|null) => void)|null} [props.onGroup] - Offers the
 *   switch of years and campaigns; none: no switch.
 * @param {"area"|"product"|null} [props.missing] - What has to be chosen
 *   before there are layers.
 * @param {(() => void)|null} [props.onPanel] - Opens the panel where it is chosen.
 * @param {string} [props.heading] - E.g. „Wachlarz migawek” for an own file.
 */
export function Fan({
  set,
  chosen,
  onChoose,
  loading = false,
  error,
  job = null,
  group = null,
  onGroup = null,
  missing = null,
  onPanel = null,
  heading = F.heading,
}) {
  const id = useId();
  const [stage, setStage] = useState(null);
  const size = useSize(stage);
  const [hot, setHot] = useState(null);
  const [focused, setFocused] = useState(null);
  const options = useRef(new Map());
  const layers = set?.layers ?? [];
  const frame = set?.frame ?? null;
  const aspect = frameAspect(frame);
  const index = layers.findIndex((layer) => layer.key === chosen);
  const plan = useMemo(
    () =>
      size.width && size.height && layers.length && !missing
        ? fanLayout({ count: layers.length, chosen: index, aspect, width: size.width, height: size.height })
        : null,
    [size.width, size.height, layers.length, index, aspect, missing],
  );
  // One option is the tab stop (roving tabindex): the focused, else the chosen, else the newest.
  const stop = layers.some((layer) => layer.key === focused) ? focused : index >= 0 ? chosen : (layers[0]?.key ?? null);

  // The chosen layer in view of an arc taller than the stage.
  useEffect(() => {
    if (!stage || !plan || index < 0) return;
    const card = plan.cards[index];
    const top = card.y;
    const bottom = card.y + card.height;
    if (top < stage.scrollTop || bottom > stage.scrollTop + stage.clientHeight) {
      stage.scrollTop = Math.max(0, top - (stage.clientHeight - card.height) / 2);
    }
  }, [stage, plan, index]);

  const keys = (event, at) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onChoose(layers[at].key);
      return;
    }
    const last = layers.length - 1;
    const next = { ArrowDown: at + 1, ArrowRight: at + 1, ArrowUp: at - 1, ArrowLeft: at - 1, Home: 0, End: last }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const target = layers[Math.max(0, Math.min(last, next))].key;
    setFocused(target);
    options.current.get(target)?.focus();
  };
  const remember = (key) => (element) => {
    if (element) options.current.set(key, element);
    else options.current.delete(key);
  };
  const hover = (key) => ({ onMouseEnter: () => setHot(key), onMouseLeave: () => setHot(null) });

  let body = null;
  if (missing) {
    body = html`<div class="fan-message">
      <p>${F.need[missing]}</p>
      ${onPanel
        ? html`<button type="button" class="btn sm" onClick=${onPanel}><${Icon} name="sidebar" size=${14} />${F.open_panel}</button>`
        : null}
    </div>`;
  } else if (!set) {
    if (error) body = html`<div class="fan-message"><${ProblemView} problem=${error.problem} /></div>`;
    else if (loading) body = html`<div class="fan-message"><${Spinner} label=${F.loading} /></div>`;
    else body = html`<div class="fan-message"><p>${F.empty}</p></div>`;
  } else if (!layers.length) {
    body = html`<div class="fan-message"><p>${F.empty}</p></div>`;
  } else if (plan) {
    const large = plan.preview && index >= 0 ? layers[index] : null;
    body = html`<div class="fan-content" style=${`height:${plan.height}px`}>
      <div class=${`fan-arc${plan.compact ? " compact" : ""}`} role="listbox" aria-label=${F.list}
        aria-orientation="vertical" aria-describedby=${`${id}-keys`}>
        ${layers.map((layer, at) => {
          const card = plan.cards[at];
          return html`<div key=${`card:${layer.key}`} aria-hidden="true"
            class=${`fan-card${card.chosen ? " chosen" : ""}${hot === layer.key ? " hot" : ""}`}
            style=${`left:${card.x}px;top:${card.y}px;width:${card.width}px;height:${card.height}px;transform:rotate(${card.rotate}rad)`}
            onClick=${() => onChoose(layer.key)} ...${hover(layer.key)}>
            <${Plate} layer=${layer} frame=${frame} size=${plan.thumbnail} />
          </div>`;
        })}
        ${layers.map((layer, at) => {
          const card = plan.cards[at];
          const box = card.caption;
          return html`<div key=${`tag:${layer.key}`} ref=${remember(layer.key)} role="option" data-layer=${layer.key}
            class=${`fan-tag ${card.detail}${card.chosen ? " chosen" : ""}${hot === layer.key ? " hot" : ""}`}
            aria-selected=${layer.key === chosen ? "true" : "false"} tabindex=${layer.key === stop ? "0" : "-1"}
            title=${describeLayer(layer)}
            style=${`left:${box.x}px;top:${box.y}px;width:${box.width}px;height:${box.height}px`}
            onClick=${() => onChoose(layer.key)} onKeyDown=${(event) => keys(event, at)}
            onFocus=${() => setFocused(layer.key)} ...${hover(layer.key)}>
            <${Caption} layer=${layer} detail=${card.detail} chosen=${card.chosen} short=${plan.compact} />
          </div>`;
        })}
      </div>
      ${large ? html`<${Large} layer=${large} frame=${frame} box=${plan.preview} job=${job} />` : null}
    </div>`;
  }

  const campaigns = group === CAMPAIGN_GROUP || layers.some((layer) => layer.campaigns.length > 1);
  return html`<section class="fan-view" aria-labelledby=${`${id}-title`}>
    <header class="fan-head">
      <div class="fan-head-row">
        <h2 class="fan-title" id=${`${id}-title`}>
          ${heading}${set && !missing ? html` · <span class="tabular">${count(layers.length, F.layers)}</span>` : null}
        </h2>
        <span class="fan-note">${F.heading_note}</span>
        ${onGroup && campaigns && !missing
          ? html`<span class="filter-group"><span class="filter-label" aria-hidden="true">${F.group_label}</span>
              <${Seg} small label=${F.group_label} value=${group ?? "year"}
                onChange=${(value) => onGroup(value === CAMPAIGN_GROUP ? CAMPAIGN_GROUP : null)}
                options=${[
                  { value: "year", label: F.group.year },
                  { value: CAMPAIGN_GROUP, label: F.group.campaign },
                ]} /></span>`
          : null}
      </div>
      ${layers.length && !missing
        ? html`<div class="fan-legend">
            <span><i class="fan-sw ready" aria-hidden="true"></i>${F.legend.ready}</span>
            <span><i class="fan-sw missing" aria-hidden="true"></i>${F.legend.missing}</span>
            <span class="faint" id=${`${id}-keys`}>${F.keys}</span>
          </div>`
        : html`<span class="visually-hidden" id=${`${id}-keys`}>${F.keys}</span>`}
      ${set && !missing && !frame && layers.length ? html`<p class="hint warn">${F.no_frame}</p>` : null}
      ${set?.stale && !missing ? html`<p class="hint warn">${staleText(set)}</p>` : null}
      ${set && error ? html`<${ProblemView} problem=${error.problem} compact />` : null}
    </header>
    <div class="fan-stage" ref=${setStage}>${body}</div>
  </section>`;
}

/**
 * A layer's caption: its title and, as room allows, coverage, variant with
 * formats, campaigns and previews; `short`: the coverage as a percent.
 */
function Caption({ layer, detail, chosen, short }) {
  return html`<span class=${`fan-yr${chosen ? " big" : ""}`}>${layer.title}</span>
    <span class="fan-lines">
      ${layer.coverage
        ? html`<span class="fan-line"><${CoverageBadge} coverage=${layer.coverage} short=${short || detail === "line"} /></span>`
        : null}
      ${detail === "line"
        ? null
        : html`<span class="fan-line sub"><span class="ell">${variantName(layer.variant)}</span>
            <${Formats} formats=${layer.variant.formats} /></span>`}
      ${detail === "full" ? html`<span class="fan-line sub"><span class="ell">${layerFacts(layer)}</span></span>` : null}
    </span>`;
}

/** The chosen layer large beside the captions: its title, thumbnail and previews. */
function Large({ layer, frame, box, job }) {
  const preview = layer.preview;
  const following = Boolean(job?.running && preview?.job && job.id === preview.job.id);
  let note = null;
  if (preview?.state === "ready") note = t(F.preview_ready, { ready: preview.ready, total: preview.total });
  else if (preview?.state === "unavailable") note = M.previews.layer_unavailable;
  else if (preview?.state === "needs_build") note = M.previews.layer_needs_build;
  else if (preview?.state === "building" && !following) note = M.previews.layer_building;
  return html`<div class="fan-large" style=${`left:${box.x}px;top:${box.y - PREVIEW_HEAD}px;width:${box.width}px`}>
    <div class="fan-large-head">
      <span class="fan-yr big">${layer.title}</span><span class="ell muted">${variantName(layer.variant)}</span>
    </div>
    <div class="fan-card chosen large" style=${`height:${box.height}px`}>
      <${Plate} layer=${layer} frame=${frame} size=${thumbnailSize(box.width, box.height)} />
    </div>
    <div class="fan-large-note">
      ${note ? html`<p>${note}</p>` : null}
      ${following ? html`<${JobStatus} job=${job} />` : null}
    </div>
  </div>`;
}

/**
 * A thumbnail: the layer's image in the frame under its sheets' outlines.
 *
 * @param {{layer: import("../types.js").Layer, frame: {crs: string, bbox:
 *   number[]}|null, size: number}} props - `size`: of `thumbnail.png`.
 */
function Plate({ layer, frame, size }) {
  const preview = layer.preview;
  const address = frame && preview?.thumbnail_url && preview.ready > 0 ? apiAddress(preview.thumbnail_url, { size }) : null;
  const image = usePreviewImage(address);
  const drawing = useMemo(() => (frame ? sheetPaths(layer, frame) : null), [layer, frame]);
  if (!drawing) return html`<span class="fan-plate-none">${F.no_thumbnail}</span>`;
  return html`<svg class="fan-plate" viewBox=${`0 0 ${PLATE} ${drawing.height}`} preserveAspectRatio="none"
    aria-hidden="true" focusable="false">
    ${image.src
      ? html`<image href=${image.src} x="0" y="0" width=${PLATE} height=${drawing.height} preserveAspectRatio="none" />`
      : null}
    ${drawing.none ? html`<path class="fan-sheet none" d=${drawing.none} />` : null}
    ${drawing.missing ? html`<path class="fan-sheet missing" d=${drawing.missing} />` : null}
    ${drawing.ready ? html`<path class="fan-sheet ready" d=${drawing.ready} />` : null}
  </svg>`;
}

/**
 * The outlines of a layer's sheets as SVG paths in a thumbnail of the frame,
 * one path per state of their previews.
 *
 * @param {import("../types.js").Layer} layer
 * @param {{bbox: number[]}} frame - The planar box the outlines are in.
 * @returns {{ready: string, missing: string, none: string, height: number}}
 */
function sheetPaths(layer, frame) {
  const [minX, minY, maxX, maxY] = frame.bbox;
  const height = PLATE * frameAspect(frame);
  const scaleX = PLATE / (maxX - minX || 1);
  const scaleY = height / (maxY - minY || 1);
  const states = new Map((layer.versions ?? []).map((version) => [version.ref, version.preview.state]));
  const paths = { ready: "", missing: "", none: "" };
  for (const feature of layer.outlines?.features ?? []) {
    const state = states.get(feature.properties?.ref);
    const kind = state === "ready" ? "ready" : state === "unavailable" || state === "failed" ? "none" : "missing";
    for (const ring of rings(feature.geometry)) {
      paths[kind] += `${ring
        .map(([x, y], at) => `${at ? "L" : "M"}${((x - minX) * scaleX).toFixed(1)} ${((maxY - y) * scaleY).toFixed(1)}`)
        .join("")}Z`;
    }
  }
  return { ...paths, height };
}

/** The rings of a polygon or multipolygon. */
function rings(geometry) {
  if (geometry?.type === "Polygon") return geometry.coordinates;
  if (geometry?.type === "MultiPolygon") return geometry.coordinates.flat();
  return [];
}

/** Height over width of the frame's thumbnails, within limits. */
function frameAspect(frame) {
  if (!frame) return DEFAULT_ASPECT;
  const [minX, minY, maxX, maxY] = frame.bbox;
  const aspect = (maxY - minY) / (maxX - minX);
  return Number.isFinite(aspect) ? Math.min(MAX_ASPECT, Math.max(MIN_ASPECT, aspect)) : DEFAULT_ASPECT;
}
