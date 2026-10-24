/**
 * The card of an own file (docs/SPEC.md 4.7.1 and 6.5; plan v0.2 step 15):
 * an overlay over the current view with its own address,
 * `own=<project>/<file_id>`, and for one of the file's snapshots
 * `own_version=<label>` (none: the working file).
 *
 * The heading names the file in its project's data folder with its format,
 * size, number of snapshots and its change since the last snapshot
 * („zmieniony od migawki z …”). The versions — the working file on top,
 * then the snapshots newest first, each with its date, label, objects and
 * note — are an axis; the chosen one has two tabs: „Metadane” (format,
 * system, extent, layers with their fields, raster, content identity,
 * paths to copy and — of the working file — the history of the states its
 * scans saw; of a snapshot its author and note) and „Podgląd” (previews.js
 * `PreviewPane`, `own_tab=preview`, style `own_style`).
 *
 * „Zrób migawkę…” opens the „Okno planu” of the snapshot (SPEC 6.1:
 * `GET …/snapshot-plan` — file, size, where it goes, how it is copied, only
 * an increment, „bez zmian od migawki z …”, why it would be refused, free
 * space and warnings; a note; „Anuluj” / „Zrób migawkę”): nothing is written
 * before the `snapshot` job starts, whose phases show as its progress; the
 * new snapshot then stands on the axis. „Porównaj z migawką…” opens the
 * comparison of two versions of the file (views/compare.js, the older as A),
 * „Pokaż na mapie” the project's map with the version's extent and its
 * objects or tiles (map/own.js, map/previews.js) and „Wachlarz migawek”
 * (`own_fan=1`) the file's versions as the Wachlarz of fan/fan.js, one
 * choice with the axis.
 */

import {
  buildOwnPreview,
  getOwnFile,
  getOwnFileLayers,
  getOwnPreview,
  getProject,
  getSnapshotPlan,
  startFileSnapshot,
  startProjectScan,
} from "../api.js";
import { Fan } from "../fan/fan.js";
import { count, day, int, size, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { T, t } from "../labels/index.js";
import { own as L } from "../labels/own.js";
import { previews as P } from "../labels/previews.js";
import {
  ChangeBadge,
  OWN_CARD_PARAMS,
  OWN_FAN_PARAM,
  OWN_PARAM,
  OWN_STYLE_PARAM,
  OWN_TAB_PARAM,
  OWN_VERSION_PARAM,
  ownName,
  PROJECT_PARAM,
  readOwnValue,
  snapshotOutline,
  StateBadge,
} from "../map/own.js";
import { PREVIEW_PARAM, PREVIEW_STYLE_PARAM } from "../map/previews.js";
import { PreviewPane } from "../previews.js";
import { Link, readRoute, setParams, useRoute } from "../router.js";
import { startView } from "../routes.js";
import {
  CopyButton,
  html,
  Icon,
  ProblemView,
  Spinner,
  Tech,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "../ui.js";
import {
  actorName,
  Badge,
  CopyAction,
  Crs,
  FINAL_STATES,
  IssueList,
  JobStatus,
  loadCardStyles,
  seconds,
  useJob,
} from "./cards.js";

await loadCardStyles();

const TABS = ["meta", "preview"];
/** The working file's key among the file's layers (`LayerSet` of the Wachlarz). */
const WORKING_KEY = "file";
const SNAPSHOT_KEY = "snapshot:";
// Most characters of a snapshot's note (`MAX_NOTE_CHARS` of the server).
const MAX_NOTE = 2000;
const HISTORY_SHOWN = 10;
const METRES = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1 });
const DEGREES = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 6 });
const PIXEL = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 4 });

/**
 * The own file card overlay (routes.js `OVERLAYS`, parameter `own`).
 *
 * @param {{route: import("../router.js").Route, value: string,
 *   onClose: () => void}} props - `value` is `<project>/<file_id>`.
 */
export default function OwnCard({ route, value, onClose }) {
  const titleId = useId();
  const heading = useRef(null);
  const opener = useRef(document.activeElement);
  const address = readOwnValue(value);
  const answer = useResource(
    (signal) =>
      address
        ? getOwnFile(address.project, address.fileId, { signal }).then((card) => ({ value, card }))
        : Promise.resolve(null),
    [value],
  );
  const card = address && answer.data?.value === value ? answer.data.card : null;

  useEffect(() => heading.current?.focus(), [value]);
  useEffect(
    () => () => {
      // Closed by Esc, the button or another view: its version and tab go too.
      const { params } = readRoute();
      if (!params[OWN_PARAM] && OWN_CARD_PARAMS.some((name) => params[name])) {
        setParams(Object.fromEntries(OWN_CARD_PARAMS.map((name) => [name, null])), { replace: true });
      }
      if (opener.current?.isConnected) opener.current.focus();
    },
    [],
  );

  let body;
  if (!address) body = html`<p class="hint warn">${t(L.bad_address, { value })}</p>`;
  else if (!card) body = answer.error ? html`<${ProblemView} problem=${answer.error.problem} />` : html`<${Spinner} />`;
  else {
    body = html`<${CardBody} key=${value} project=${address.project} fileId=${address.fileId} card=${card}
      params=${route.params} loading=${answer.loading} error=${answer.error} reload=${answer.reload} />`;
  }
  return html`<section class="drawer file-card own-card" role="dialog" aria-modal="false"
    aria-labelledby=${titleId}>
    <header class="drawer-head">
      <div class="fc-title">
        <div class="eyebrow">${L.eyebrow}</div>
        <h2 id=${titleId} tabindex="-1" ref=${heading}>${card ? ownName(card.path) : value}</h2>
      </div>
      <button type="button" class="btn ghost icon-btn" onClick=${onClose} title=${L.close}
        aria-label=${L.close}><${Icon} name="x" /></button>
    </header>
    <div class="drawer-body">${body}</div>
  </section>`;
}

function CardBody({ project, fileId, card, params, loading, error, reload }) {
  const [planning, setPlanning] = useState(false);
  const wanted = params[OWN_VERSION_PARAM] ?? null;
  const chosen = wanted === null ? null : (card.snapshots.find((snapshot) => snapshot.label === wanted) ?? null);
  const tab = TABS.includes(params[OWN_TAB_PARAM]) ? params[OWN_TAB_PARAM] : TABS[0];
  const fan = params[OWN_FAN_PARAM] === "1";
  return html`
    <${Heading} project=${project} card=${card} />
    ${error ? html`<${ProblemView} problem=${error.problem} compact />` : null}
    ${card.preview?.reason?.code === "changed_since_scan" ? html`<${Rescan} project=${project} onDone=${reload} />` : null}
    ${card.problems.length
      ? html`<section class="det-sec">
          <h3 class="section-title">${count(card.problems.length, T.common.units.problems)}</h3>
          <${IssueList} issues=${card.problems} currentProject=${project} />
        </section>`
      : null}
    <${Actions} project=${project} card=${card} chosen=${chosen} fan=${fan} onPlan=${() => setPlanning(true)} />
    ${fan ? html`<${FanSection} project=${project} fileId=${fileId} card=${card} chosen=${chosen} />` : null}
    <${VersionAxis} card=${card} chosen=${chosen} />
    <${VersionDetails} key=${chosen?.label ?? WORKING_KEY} project=${project} fileId=${fileId} card=${card}
      chosen=${chosen} tab=${tab} style=${params[OWN_STYLE_PARAM] ?? null} />
    ${planning
      ? html`<${PlanWindow} project=${project} fileId=${fileId} card=${card}
          onClose=${() => setPlanning(false)} onDone=${reload} />`
      : null}
    ${loading ? html`<${Spinner} quiet />` : null}
  `;
}

function Heading({ project, card }) {
  const { data } = useResource((signal) => getProject(project, { signal }), [project]);
  return html`<div class="fc-heading">
    <p class="fc-product">
      <${Tech} value=${[["path", card.path], ["ref", card.ref], ["file_id", card.file_id]]}>
        <span class="mono own-path">${card.path}</span>
      </${Tech}>
    </p>
    <div class="chip-row">
      <${Link} class="chip" view="projects" params=${{ project }} title=${L.project_title}>
        <${Icon} name="folder" size=${13} />${t(L.project, { name: data?.name ?? project })}
      </${Link}>
      <span class="chip static">${[P.kind[card.kind] ?? card.kind, card.format].filter(Boolean).join(" · ")}</span>
      <span class="chip static">${size(card.size_bytes)}</span>
      <span class="chip static">${count(card.snapshots.length, L.snapshots_count)}</span>
      <${ChangeBadge} file=${card} />
      <${StateBadge} file=${card} />
    </div>
  </div>`;
}

/** The file changed since its scan: scan the project's folder again, then read the card. */
function Rescan({ project, onDone }) {
  const job = useJob({ onEnd: onDone });
  const busy = job.starting || job.running;
  return html`<div class="own-rescan">
    <p class="hint warn">${L.scan.changed}</p>
    <button type="button" class="btn sm" disabled=${busy}
      onClick=${() => job.run(() => startProjectScan(project), "own_scan")}>
      ${busy ? html`<span class="spinner" aria-hidden="true"></span>` : html`<${Icon} name="rotate" size=${14} />`}
      ${L.actions.rescan}
    </button>
    <${JobStatus} job=${job} />
  </div>`;
}

function Actions({ project, card, chosen, fan, onPlan }) {
  const reference = chosen ? chosen.ref : card.ref;
  const located = chosen ? snapshotOutline(chosen) !== null : card.location.kind === "footprint";
  return html`<div class="own-actions">
    ${chosen === null
      ? html`<button type="button" class="btn sm primary" title=${L.actions.snapshot_title}
          disabled=${card.state === "missing"} onClick=${onPlan}>
          <${Icon} name="plus" size=${14} />${L.actions.snapshot}</button>`
      : null}
    <${CompareWith} card=${card} chosen=${chosen} />
    ${located ? html`<${ShowOnMap} project=${project} reference=${reference} style=${null} />` : null}
    ${card.snapshots.length
      ? html`<button type="button" class=${`btn sm${fan ? " active" : ""}`} aria-pressed=${fan ? "true" : "false"}
          title=${fan ? L.actions.fan_hide : L.actions.fan_title}
          onClick=${() => setParams({ [OWN_FAN_PARAM]: fan ? null : "1" }, { replace: true })}>
          <${Icon} name="fan" size=${14} />${L.actions.fan}</button>`
      : null}
  </div>`;
}

/**
 * „Porównaj z migawką…”: this version next to another one of the file in the
 * comparison — the older one as A, so it reads as the change from A to B.
 */
function CompareWith({ card, chosen }) {
  const versions = [
    { key: WORKING_KEY, ref: card.ref, date: card.modified_at, name: L.axis.working },
    ...card.snapshots.map((snapshot) => ({
      key: snapshot.label,
      ref: snapshot.ref,
      date: snapshot.created_at,
      name: snapshot.label,
    })),
  ];
  const mine = chosen ? versions.findIndex((version) => version.key === chosen.label) : 0;
  const others = versions.filter((_, index) => index !== mine);
  if (!others.length) return null;
  return html`<details class="fc-compare">
    <summary class="btn sm" title=${L.actions.compare_title}>
      <${Icon} name="layers" size=${14} />${chosen ? L.actions.compare_other : L.actions.compare}
    </summary>
    <ul class="fc-compare-list" aria-label=${L.actions.compare_list}>
      ${others.map((other) => {
        const [a, b] = versions.indexOf(other) > mine ? [other, versions[mine]] : [versions[mine], other];
        return html`<li key=${other.key}>
          <${Link} view="compare" params=${{ a: a.ref, b: b.ref }}>
            <span class="fc-year">${other.date ? day(other.date) : L.axis.no_date}</span>
            <span class="fc-label mono">${other.name}</span>
          </${Link}>
        </li>`;
      })}
    </ul>
  </details>`;
}

/**
 * „Pokaż na mapie”: the project's map with the version's extent and its
 * objects or tiles; the card closes, a map already open keeps its state.
 */
function ShowOnMap({ project, reference, style }) {
  const route = useRoute();
  const kept =
    (route.view ?? startView().id) === "map"
      ? Object.fromEntries(
          Object.entries(route.params).filter(([name]) => name !== OWN_PARAM && !OWN_CARD_PARAMS.includes(name)),
        )
      : {};
  const params = {
    ...kept,
    [PROJECT_PARAM]: project,
    // The outlines of every version pinned in the project, older ones too.
    versions: kept[PROJECT_PARAM] === project ? kept.versions : "pinned",
    [PREVIEW_PARAM]: reference,
    [PREVIEW_STYLE_PARAM]: style,
  };
  return html`<${Link} class="btn sm" view="map" params=${params} title=${L.actions.on_map_title}>
    <${Icon} name="map" size=${14} />${L.actions.on_map}</${Link}>`;
}

function VersionAxis({ card, chosen }) {
  const id = useId();
  const select = (label) => setParams({ [OWN_VERSION_PARAM]: label }, { replace: true });
  return html`<section class="det-sec" aria-labelledby=${id}>
    <h3 class="section-title" id=${id}>${L.axis.title}</h3>
    <ol class="fc-axis own-axis">
      <li class=${`fc-version current${chosen === null ? " on" : ""}${card.state === "missing" ? " gone" : ""}`}>
        <span class="fc-dot" aria-hidden="true"></span>
        <button type="button" class="fc-pick" aria-pressed=${chosen === null ? "true" : "false"}
          title=${L.axis.working_title} onClick=${() => select(null)}>
          <span class="fc-year">${L.axis.working}</span>
          <span class="faint">${t(L.axis.modified, { date: stamp(card.modified_at) })}</span>
        </button>
      </li>
      ${card.snapshots.map((snapshot) => {
        const on = snapshot === chosen;
        return html`<li key=${snapshot.label} class=${`fc-version${on ? " on" : ""}`}>
          <span class="fc-dot" aria-hidden="true"></span>
          <button type="button" class="fc-pick" aria-pressed=${on ? "true" : "false"}
            onClick=${() => select(snapshot.label)}>
            <span class="fc-year">${snapshot.created_at ? day(snapshot.created_at) : L.axis.no_date}</span>
            <span class="fc-label mono">${snapshot.label}</span>
          </button>
          <span class="fc-marks">
            ${snapshot.feature_count !== null ? html`<span class="faint">${count(snapshot.feature_count, L.features)}</span>` : null}
            ${snapshot.state !== "ok"
              ? html`<${Badge} level="bad">${L.axis.snapshot_state[snapshot.state] ?? snapshot.state}</${Badge}>`
              : null}
          </span>
          ${snapshot.note ? html`<p class="fc-pins own-note">${snapshot.note}</p>` : null}
        </li>`;
      })}
    </ol>
  </section>`;
}

function VersionDetails({ project, fileId, card, chosen, tab, style }) {
  const panel = useId();
  const title = chosen ? t(L.version.snapshot, { label: chosen.label }) : L.version.working;
  return html`<section class="det-sec fc-details" aria-label=${title}>
    <h3 class="fc-version-title">
      <${Tech} value=${[["ref", chosen ? chosen.ref : card.ref]]}>${title}</${Tech}>
    </h3>
    <${VersionTabs} tab=${tab} panel=${panel} />
    <div class="fc-panel" role="tabpanel" id=${panel} aria-labelledby=${`${panel}-${tab}`}>
      ${tab === "preview"
        ? html`<${VersionPreview} project=${project} fileId=${fileId} card=${card} chosen=${chosen} style=${style} />`
        : chosen
          ? html`<${SnapshotMetadata} snapshot=${chosen} />`
          : html`<${WorkingMetadata} card=${card} />`}
    </div>
  </section>`;
}

/**
 * The tabs of a version (ARIA tabs: arrows, Home and End move between them);
 * the chosen one lives in the address.
 */
function VersionTabs({ tab, panel }) {
  const select = (name) => setParams({ [OWN_TAB_PARAM]: name === TABS[0] ? null : name }, { replace: true });
  const key = (event) => {
    const index = TABS.indexOf(tab);
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const name = TABS[(next + TABS.length) % TABS.length];
    select(name);
    event.currentTarget.querySelector(`[data-tab="${name}"]`)?.focus();
  };
  return html`<div class="fc-tabs" role="tablist" aria-label=${L.tabs.label} onKeyDown=${key}>
    ${TABS.map(
      (name) => html`<button type="button" role="tab" class="fc-tab" id=${`${panel}-${name}`} key=${name}
        data-tab=${name} aria-selected=${name === tab ? "true" : "false"} aria-controls=${panel}
        tabindex=${name === tab ? 0 : -1} onClick=${() => select(name)}>
        <${Icon} name=${name === "preview" ? "eye" : "info"} size=${14} />${L.tabs[name]}
      </button>`,
    )}
  </div>`;
}

/** The preview of the working file or of a snapshot; its style lives in the address. */
function VersionPreview({ project, fileId, card, chosen, style }) {
  const label = chosen?.label ?? null;
  const reference = chosen ? chosen.ref : card.ref;
  // The working file's content changes under its ref: a new content, a new object.
  const key = chosen ? chosen.ref : `${card.ref}\n${card.content?.sha256 ?? card.modified_at}`;
  const preview = useMemo(
    () => ({
      key,
      load: (signal) => getOwnPreview(project, fileId, label, { signal }),
      build: (force) => buildOwnPreview(project, fileId, label, { force }),
    }),
    [project, fileId, label, key],
  );
  return html`<${PreviewPane} preview=${preview} name=${ownName(card.path)} style=${style}
    onStyle=${(value) => setParams({ [OWN_STYLE_PARAM]: value }, { replace: true })}>
    ${(info, shown) =>
      info.state === "ready" && (info.tiles_url || info.features_url)
        ? html`<${ShowOnMap} project=${project} reference=${reference} style=${info.features_url ? null : shown} />`
        : null}
  </${PreviewPane}>`;
}

function WorkingMetadata({ card }) {
  const counts = card.layers.map((layer) => layer.feature_count);
  const features = counts.length && counts.every((value) => value !== null) ? counts.reduce((a, b) => a + b, 0) : null;
  const rows = [
    [L.meta.path, html`<span class="mono own-path">${card.path}</span>`],
    [L.meta.format, card.format ?? html`<span class="faint">${L.meta.format_none}</span>`],
    [L.meta.kind, P.kind[card.kind] ?? card.kind],
    [L.meta.size, html`<${Tech} value=${[["size_bytes", String(card.size_bytes)]]}>${size(card.size_bytes)}</${Tech}>`],
    [L.meta.modified, stamp(card.modified_at)],
    [L.meta.crs, card.crs ? html`<${OwnCrs} code=${card.crs} />` : null],
    [L.meta.extent, card.extent ? html`<${Extent} bbox=${card.extent.bbox} crs=${card.crs} />` : null],
    [L.meta.location, html`<${Location} location=${card.location} />`],
    [L.meta.content, card.content ? html`<${ContentValue} content=${card.content} />` : null],
    [L.meta.features, features === null ? null : int(features)],
  ];
  return html`
    <${Rows} rows=${rows} />
    ${card.layers.length ? html`<${Layers} layers=${card.layers} />` : null}
    ${card.raster ? html`<${Raster} raster=${card.raster} />` : null}
    <${Paths} title=${L.meta.paths} paths=${card.paths} copy=${L.meta.copy_path} />
    ${card.history.length ? html`<${History} history=${card.history} />` : null}
  `;
}

function SnapshotMetadata({ snapshot }) {
  const author = snapshot.author;
  const authorValues = author ? Object.entries(author).filter(([, value]) => value).map(([name, value]) => [name, String(value)]) : [];
  const rows = [
    [L.meta.label, html`<span class="mono">${snapshot.label}</span>`],
    [L.meta.created, snapshot.created_at ? stamp(snapshot.created_at) : null],
    [
      L.meta.author,
      author ? html`<${Tech} value=${authorValues}>${author.name ?? actorName(author.id)}</${Tech}>` : null,
    ],
    [L.meta.note, snapshot.note ? html`<span class="own-note-text">${snapshot.note}</span>` : html`<span class="faint">${L.meta.no_note}</span>`],
    [L.meta.size, html`<${Tech} value=${[["size_bytes", String(snapshot.size_bytes)]]}>${size(snapshot.size_bytes)}</${Tech}>`],
    [L.meta.content, snapshot.content ? html`<${ContentValue} content=${snapshot.content} />` : null],
    [L.meta.features, snapshot.feature_count === null ? null : int(snapshot.feature_count)],
    [L.meta.crs, snapshot.extent?.crs ? html`<${OwnCrs} code=${snapshot.extent.crs} />` : null],
    [L.meta.extent, snapshot.extent ? html`<${Extent} bbox=${snapshot.extent.bbox} crs=${snapshot.extent.crs} />` : null],
    [
      L.meta.state,
      html`<${Badge} level=${snapshot.state === "ok" ? "ok" : "bad"}>
        <${Tech} value=${[["state", snapshot.state]]}>${L.meta.snapshot_state[snapshot.state] ?? snapshot.state}</${Tech}>
      </${Badge}>`,
    ],
  ];
  return html`
    <${Rows} rows=${rows} />
    <${Paths} title=${L.meta.snapshot_path} paths=${snapshot.paths} copy=${L.meta.copy_snapshot} />
  `;
}

function Rows({ rows }) {
  return html`<dl class="kv fc-meta">
    ${rows
      .filter(([, value]) => value !== null && value !== undefined)
      .map(([name, value]) => html`<dt>${name}</dt><dd>${value}</dd>`)}
  </dl>`;
}

/** A system for people: an EPSG code by its name, a WKT one click away. */
function OwnCrs({ code }) {
  if (code.startsWith("EPSG:")) return html`<${Crs} code=${code} />`;
  return html`<${Tech} value=${code}>${L.meta.crs_wkt}</${Tech}>`;
}

/** An extent in its system: degrees to 6 places, metres to 1. */
function Extent({ bbox, crs }) {
  const number = (value) => (Math.abs(value) <= 360 ? DEGREES : METRES).format(value);
  const text = `${number(bbox[0])}, ${number(bbox[1])} – ${number(bbox[2])}, ${number(bbox[3])}`;
  const values = [["bbox", bbox.join(",")]];
  if (crs) values.push(["crs", crs]);
  return html`<${Tech} value=${values}><span class="tabular">${text}</span></${Tech}>`;
}

function Location({ location }) {
  const kind = L.meta.location_kind[location.kind] ?? location.kind;
  const why = location.reason ? (L.meta.location_reason[location.reason] ?? location.reason) : null;
  const values = [["kind", location.kind]];
  if (location.reason) values.push(["reason", location.reason]);
  return html`<${Tech} value=${values}>${why ? `${kind} — ${why}` : kind}</${Tech}>`;
}

function ContentValue({ content }) {
  return html`<${Tech} value=${[["method", content.method], ["sha256", content.sha256]]}>
    ${L.meta.content_method[content.method] ?? content.method} · <span class="mono">${content.sha256.slice(0, 12)}…</span>
  </${Tech}>`;
}

/** Layers with their geometry, objects and fields (the schema the comparison diffs). */
function Layers({ layers }) {
  return html`<div class="fc-block own-layers">
    <h4 class="section-title">${L.meta.layers}</h4>
    <ul class="own-layer-list">
      ${layers.map(
        (layer) => html`<li key=${layer.name} class="own-layer">
          <p class="own-layer-head">
            <b class="mono">${layer.name}</b>
            <span class="faint">${[
              layer.geometry_type ?? L.meta.no_geometry,
              layer.feature_count === null ? null : count(layer.feature_count, L.features),
            ]
              .filter(Boolean)
              .join(" · ")}</span>
          </p>
          ${layer.fields.length
            ? html`<p class="own-fields" aria-label=${t(L.meta.field_list, { name: layer.name })}>
                ${layer.fields.map(
                  (field, index) => html`<span key=${field.name} class="own-field">${index ? ", " : ""}<span class="mono">${field.name}</span>
                    ${" "}<span class="faint mono">${field.type}</span></span>`,
                )}
              </p>`
            : html`<p class="faint own-fields">${L.meta.no_fields}</p>`}
        </li>`,
      )}
    </ul>
  </div>`;
}

function Raster({ raster }) {
  const parts = [
    t(L.meta.raster_size, {
      width: int(raster.width),
      height: int(raster.height),
      bands: int(raster.bands),
      dtype: raster.dtype,
    }),
  ];
  if (raster.nodata !== null) parts.push(t(L.meta.nodata, { value: String(raster.nodata) }));
  if (raster.pixel_size) {
    parts.push(t(L.meta.pixel, { x: PIXEL.format(Math.abs(raster.pixel_size[0])), y: PIXEL.format(Math.abs(raster.pixel_size[1])) }));
  }
  if (!raster.georeferenced) parts.push(L.meta.not_georeferenced);
  return html`<div class="fc-block">
    <h4 class="section-title">${L.meta.raster}</h4>
    <p class="own-raster">${parts.join(" · ")}</p>
  </div>`;
}

function Paths({ title, paths, copy }) {
  return html`<div class="fc-block">
    <h4 class="section-title">${title}</h4>
    <div class="fc-path">
      <p class="fc-path-row"><code class="path">${paths.local}</code></p>
      <${CopyAction} text=${paths.local} label=${copy} />
      ${paths.aliases.map(
        (alias) => html`<p key=${alias} class="fc-path-row">
          <span class="faint">${L.meta.alias}:</span> <code class="path">${alias}</code>
          <${CopyButton} text=${alias} label=${alias} />
        </p>`,
      )}
    </div>
  </div>`;
}

function History({ history }) {
  const [all, setAll] = useState(false);
  const shown = all ? history : history.slice(0, HISTORY_SHOWN);
  const C = L.meta.history_columns;
  return html`<div class="fc-block own-history">
    <h4 class="section-title">${L.meta.history}</h4>
    <p class="hint">${L.meta.history_hint}</p>
    <div class="table-wrap">
      <table class="own-history-table">
        <thead><tr>
          <th scope="col">${C.observed}</th>
          <th scope="col" class="num">${C.size}</th>
          <th scope="col">${C.modified}</th>
          <th scope="col">${C.content}</th>
          <th scope="col" class="num">${C.features}</th>
        </tr></thead>
        <tbody>
          ${shown.map(
            (item, index) => html`<tr key=${index}>
              <td class="nw">${stamp(item.observed_at)}</td>
              <td class="num tabular nw">${size(item.size_bytes)}</td>
              <td class="nw">${stamp(item.modified_at)}</td>
              <td>${item.content_sha256
                ? html`<${Tech} value=${[["sha256", item.content_sha256]]}><span class="mono">${item.content_sha256.slice(0, 8)}</span></${Tech}>`
                : T.common.empty}</td>
              <td class="num tabular">${int(item.feature_count)}</td>
            </tr>`,
          )}
        </tbody>
      </table>
    </div>
    ${history.length > shown.length
      ? html`<button type="button" class="btn sm" onClick=${() => setAll(true)}>
          ${t(L.meta.history_more, { count: int(history.length) })}</button>`
      : null}
  </div>`;
}

/**
 * „Wachlarz migawek”: the file's versions (`GET …/files/{file_id}/layers`,
 * the working file on top) in the Wachlarz; its choice is the axis's.
 */
function FanSection({ project, fileId, card, chosen }) {
  const answer = useResource(
    (signal) => getOwnFileLayers(project, fileId, { signal }),
    [project, fileId, card.snapshots.length, card.content?.sha256 ?? card.modified_at],
  );
  const job = useJob({ onEnd: answer.reload });
  const set = answer.data ?? null;
  const building = set?.layers.find((layer) => layer.preview?.state === "building" && layer.preview.job)?.preview.job.id ?? null;
  useEffect(() => {
    if (building) job.follow(building, "preview");
  }, [building]);
  const choose = (key) =>
    setParams({ [OWN_VERSION_PARAM]: key.startsWith(SNAPSHOT_KEY) ? key.slice(SNAPSHOT_KEY.length) : null }, { replace: true });
  return html`<section class="det-sec own-fan" aria-label=${L.fan.label}>
    <${Fan} set=${set} chosen=${chosen ? `${SNAPSHOT_KEY}${chosen.label}` : WORKING_KEY} onChoose=${choose}
      loading=${answer.loading} error=${answer.error} job=${job} heading=${L.fan.heading} />
  </section>`;
}

/**
 * The „Okno planu” of a snapshot (SPEC 6.1, 6.5 h): what would be copied,
 * where, how and why it may be refused — nothing is written until „Zrób
 * migawkę” starts the `snapshot` job, followed here to its end.
 */
function PlanWindow({ project, fileId, card, onClose, onDone }) {
  const titleId = useId();
  const noteId = useId();
  const dialog = useRef(null);
  const [note, setNote] = useState("");
  const plan = useResource((signal) => getSnapshotPlan(project, fileId, { signal }), [project, fileId]);
  const job = useJob({ onEnd: () => onDone() });
  const busy = job.starting || job.running;
  const finished = job.events !== null && FINAL_STATES.has(job.events.state);
  const data = plan.data;
  const close = () => {
    if (!busy) onClose();
  };
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => {
      if (element.open) element.close();
    };
  }, []);
  const submit = (event) => {
    event.preventDefault();
    if (!data || data.blocked || busy) return;
    job.run(() => startFileSnapshot(project, fileId, note.trim()), "snapshot");
  };
  return html`<dialog class="own-plan" ref=${dialog} aria-labelledby=${titleId}
    onCancel=${(event) => {
      event.preventDefault();
      close();
    }}
    onKeyDown=${(event) => {
      // Esc closes this window only, not the card under it (shell.js).
      if (event.key === "Escape") event.stopPropagation();
    }}>
    <form class="own-plan-body" onSubmit=${submit}>
      <h2 class="own-plan-title" id=${titleId}>${L.plan.title} <span class="mono">${ownName(card.path)}</span></h2>
      ${plan.error ? html`<${ProblemView} problem=${plan.error.problem} compact />` : null}
      ${!data && !plan.error ? html`<${Spinner} label=${L.plan.loading} />` : null}
      ${data ? html`<${PlanFacts} plan=${data} />` : null}
      <div class="field own-plan-note">
        <label for=${noteId}>${L.plan.note}</label>
        <textarea id=${noteId} rows="3" maxlength=${MAX_NOTE} value=${note} disabled=${busy || finished}
          onInput=${(event) => setNote(event.currentTarget.value)}></textarea>
        <span class="field-hint">${L.plan.note_hint} ${t(L.plan.note_count, { count: int(note.length), max: int(MAX_NOTE) })}</span>
      </div>
      <${JobStatus} job=${job} summary=${snapshotSummary} />
      <div class="own-plan-actions">
        ${finished
          ? html`<button type="button" class="btn" onClick=${onClose}>${L.plan.close}</button>`
          : html`<button type="button" class="btn" disabled=${busy} onClick=${close}>${L.plan.cancel}</button>
              <button type="submit" class="btn primary" disabled=${!data || Boolean(data.blocked) || busy}>
                ${busy ? html`<span class="spinner" aria-hidden="true"></span>` : html`<${Icon} name="check" size=${14} />`}
                ${L.plan.submit}
              </button>`}
      </div>
    </form>
  </dialog>`;
}

function PlanFacts({ plan }) {
  return html`
    <dl class="kv own-plan-facts">
      <dt>${L.plan.file}</dt><dd class="mono own-path">${plan.file}</dd>
      <dt>${L.plan.size}</dt>
      <dd><${Tech} value=${[["size_bytes", String(plan.size_bytes)]]}>${size(plan.size_bytes)}</${Tech}></dd>
      <dt>${L.plan.destination}</dt>
      <dd class="own-plan-destination">
        <code class="path">${plan.destination.local}</code>
        <${CopyButton} text=${plan.destination.local} label=${L.plan.copy_destination} />
        <span class="field-hint">${L.plan.destination_hint}</span>
      </dd>
      <dt>${L.plan.copy_method}</dt>
      <dd><${Tech} value=${[["copy_method", plan.copy_method]]}>${L.plan.copy_methods[plan.copy_method] ?? plan.copy_method}</${Tech}></dd>
      <dt>${L.plan.content_method}</dt>
      <dd><${Tech} value=${[["content_method", plan.content_method]]}>
        ${L.meta.content_method[plan.content_method] ?? plan.content_method}</${Tech}></dd>
      <dt>${L.plan.free}</dt>
      <dd>${plan.free_bytes === null ? L.plan.free_unknown : size(plan.free_bytes)}</dd>
    </dl>
    <p class="own-plan-line"><${Icon} name="info" size=${15} /><span>${L.plan.increment}</span></p>
    ${plan.unchanged_since
      ? html`<p class="own-plan-line ok own-plan-unchanged" role="note"><${Icon} name="check" size=${15} />
          <span>${t(L.plan.unchanged, { date: day(plan.unchanged_since.created_at), label: plan.unchanged_since.label })}</span></p>`
      : null}
    ${plan.warnings.map(
      (warning) => html`<p key=${warning.code} class="own-plan-line warn" role="note"><${Icon} name="alert" size=${15} />
        <span><b>${L.plan.warning}</b> <${Tech} value=${[["code", warning.code]]}>${warning.message}</${Tech}></span></p>`,
    )}
    ${plan.blocked
      ? html`<p class="own-plan-line bad" role="alert"><${Icon} name="alert" size=${15} />
          <span><b>${L.plan.blocked}</b> <${Tech} value=${[["code", plan.blocked.code]]}>${plan.blocked.message}</${Tech}></span></p>`
      : null}
  `;
}

function snapshotSummary(events) {
  const result = events.result;
  if (!result) return null;
  if (result.status === "unchanged") {
    return html`<p class="job-summary">${t(L.plan.unchanged_done, { label: result.label })}</p>`;
  }
  return html`<p class="job-summary">${t(L.plan.created, {
    label: result.label,
    size: size(result.size_bytes),
    sha256: String(result.content_sha256 ?? "").slice(0, 12),
    seconds: seconds(result.seconds ?? 0),
  })}</p>`;
}
