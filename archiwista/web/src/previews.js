/**
 * Previews of objects (docs/SPEC.md 5.7; plan v0.2, step 12a): what a file
 * shows, why something is missing and how to fix it — in the file card now,
 * for own files and snapshots later (step 15).
 *
 * Images of the API need the session's CSRF header, which an `<img src>`
 * cannot send: `usePreviewImage` fetches them (`getImage`) and shows a
 * `blob:` address (the CSP allows `blob:` images), revoked when the address
 * changes or the component unmounts. `PreviewPane` shows one `PreviewInfo`:
 * the thumbnail in the chosen style with its legend, the reason of what is
 * missing with its fix, whether the file reaches the map, and the build of
 * its local preview (`POST …/preview`): a file within the auto-build limits
 * is built at its first view, a larger one waits for „Zbuduj podgląd”
 * (decision 6), and the `preview` job's progress comes through `useJob`.
 * Vectors list their layers with a sample of attributes, point clouds their
 * header and classes, archives their members. The pane gets its object as a
 * `PreviewSource` (load and build functions), so a version, an own file and
 * a snapshot share it; actions of later steps come as its children.
 */

import { apiAddress, getImage, getLinked } from "./api.js";
import { count, day, int, size } from "./format.js";
import { useResource } from "./hooks.js";
import { T, t } from "./labels/index.js";
import { previews as L } from "./labels/previews.js";
import {
  html,
  Icon,
  loadStylesheet,
  ProblemView,
  Seg,
  Spinner,
  Tech,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "./ui.js";
import { Badge, Crs, JobStatus, seconds, useJob } from "./views/cards.js";

await loadStylesheet(new URL("./previews.css", import.meta.url));

/** Longest side of a pane's thumbnail in pixels (`size` of `preview.png`). */
export const THUMBNAIL_SIZE = 512;
/** Members of an archive listed before „Pokaż wszystkie”. */
const MEMBERS_SHOWN = 200;
// Objects whose build this page asked for (by `PreviewSource.key`): a file
// within the auto-build limits is built by itself once, not at every view.
const AUTO_ASKED = new Set();
// Reasons of a load or a moment (`TRANSIENT_REASONS` of previews/types.py):
// asking again may succeed.
const TRANSIENT = new Set(["timeout", "memory_limit", "missing_file", "store_unavailable", "changed_since_scan"]);
const STATE_LEVEL = { ready: "ok", needs_build: "info", building: "info", unavailable: "warn", failed: "bad" };
const HEX = /^#[0-9a-f]{6}$/i;
const NUMBER = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1 });
const SHARE = new Intl.NumberFormat("pl-PL", { style: "percent", maximumFractionDigits: 1 });
const KILO = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/**
 * The object a pane previews.
 *
 * @typedef {object} PreviewSource
 * @property {string} key - Changes when the object does (e.g. its `ref`).
 * @property {(signal: AbortSignal) => Promise<import("./types.js").PreviewInfo>} load -
 *   Its `GET …/preview` (`getPreview` of a version).
 * @property {(force: boolean) => Promise<import("./types.js").JobDetail
 *   |import("./types.js").PreviewInfo>} build - Its `POST …/preview`
 *   (`buildPreview`): the job, or the `PreviewInfo` when nothing needs building.
 */

/**
 * An image of the API as a `blob:` address for `<img>`.
 *
 * @param {string|null} address - An image address the API gave, with its query
 *   (`apiAddress(info.thumbnail_url, {style, size})`); `null` loads nothing.
 * @returns {{src: string|null, problem: import("./types.js").Problem|null,
 *   loading: boolean}} `src` stays the last image while the next one loads.
 */
export function usePreviewImage(address) {
  const [image, setImage] = useState({ address: null, src: null, problem: null });
  useEffect(() => {
    if (!address) {
      setImage({ address: null, src: null, problem: null });
      return undefined;
    }
    const controller = new AbortController();
    let src = null;
    getImage(address, { signal: controller.signal }).then(
      (blob) => {
        if (controller.signal.aborted) return;
        src = URL.createObjectURL(blob);
        setImage({ address, src, problem: null });
      },
      (error) => {
        if (controller.signal.aborted) return;
        setImage({ address, src: null, problem: error.problem ?? noAnswer() });
      },
    );
    return () => {
      controller.abort();
      if (src !== null) URL.revokeObjectURL(src);
    };
  }, [address]);
  return { src: image.src, problem: image.problem, loading: Boolean(address) && image.address !== address };
}

/**
 * The preview of one object: thumbnail, style, legend, reason, build, details.
 *
 * @param {{preview: PreviewSource, name: string, style?: string|null,
 *   onStyle?: (style: string) => void, children?: *}} props - `name`: the
 *   file's name (image description, a layer named after its file); `style`
 *   and `onStyle` keep the chosen style outside (e.g. in the address), else
 *   the pane keeps it; `children`: actions of the object, or a function of
 *   the loaded `PreviewInfo` and the style shown returning them (an action
 *   only some previews offer, e.g. „Pokaż podgląd na mapie”).
 */
export function PreviewPane({ preview, name, style = null, onStyle, children }) {
  const { data: info, error, loading, reload } = useResource((signal) => preview.load(signal), [preview.key]);
  const build = useBuild(preview, info, reload);
  const [ownStyle, setOwnStyle] = useState(null);
  if (!info) {
    return html`<div class="pv-pane">
      ${error
        ? html`<${ProblemView} problem=${error.problem} compact />
            <button type="button" class="btn sm pv-retry" onClick=${reload}>${L.retry}</button>`
        : html`<${Spinner} label=${L.loading} />`}
    </div>`;
  }
  const wanted = onStyle ? style : ownStyle;
  const chosen = info.styles.includes(wanted) ? wanted : (info.default_style ?? info.styles[0] ?? null);
  const legend = chosen ? info.legends[chosen] : null;
  const state = build.busy ? "building" : info.state;
  const retry = info.state === "failed" || TRANSIENT.has(info.reason?.code);
  const actions = typeof children === "function" ? children(info, chosen) : children;
  // Past the auto-build limits the thumbnail too waits for the local copy.
  const awaited = info.state === "needs_build" && !info.auto_build;
  return html`<div class="pv-pane">
    ${info.thumbnail_url
      ? html`<${Thumbnail}
          address=${awaited ? null : apiAddress(info.thumbnail_url, { style: chosen, size: THUMBNAIL_SIZE })}
          alt=${t(L.thumbnail.alt, { name, style: styleName(chosen) })}
          note=${awaited ? L.thumbnail.after_build : null} />`
      : null}
    ${info.styles.length > 1
      ? html`<${Seg} small label=${L.styles_label} value=${chosen} onChange=${onStyle ?? setOwnStyle}
          options=${info.styles.map((value) => ({ value, label: styleName(value) }))} />`
      : null}
    ${legend ? html`<${PreviewLegend} legend=${legend} />` : null}
    ${info.reason ? html`<${PreviewReason} reason=${info.reason} shown=${info.state !== "unavailable" && info.state !== "failed"} />` : null}
    <${Facts} info=${info} state=${state} />
    <${BuildSection} info=${info} build=${build} loading=${loading} />
    ${error ? html`<${ProblemView} problem=${error.problem} compact />` : null}
    ${retry
      ? html`<button type="button" class="btn sm pv-retry" disabled=${loading} onClick=${reload}>
          <${Icon} name="rotate" size=${14} />${L.retry}</button>`
      : null}
    ${info.layers.length ? html`<${Layers} layers=${info.layers} name=${name} />` : null}
    ${info.points ? html`<${Points} points=${info.points} unit=${info.legends.elevation?.unit ?? null} />` : null}
    ${info.members_url ? html`<${Members} address=${info.members_url} />` : null}
    ${actions ? html`<div class="pv-actions">${actions}</div>` : null}
  </div>`;
}

/**
 * The legend of a style: a colour ramp with its range, or the classes.
 *
 * @param {{legend: import("./types.js").GradientLegend
 *   |import("./types.js").ClassesLegend}} props
 */
export function PreviewLegend({ legend }) {
  if (legend.kind === "gradient") {
    const ramp = legend.colors.map(color).join(", ");
    const max = legend.unit ? `${NUMBER.format(legend.max)} ${legend.unit}` : NUMBER.format(legend.max);
    return html`<div class="pv-legend" role="group" aria-label=${L.legend.title}>
      <h4 class="section-title">${L.legend.title}</h4>
      <span class="pv-ramp" style=${`--ramp: linear-gradient(90deg, ${ramp})`} aria-hidden="true"></span>
      <span class="pv-range tabular"><span>${NUMBER.format(legend.min)}</span><span>${max}</span></span>
    </div>`;
  }
  return html`<div class="pv-legend" role="group" aria-label=${L.legend.title}>
    <h4 class="section-title">${L.legend.title} · ${count(legend.items.length, L.legend.classes)}</h4>
    <ul class="pv-classes">
      ${legend.items.map(
        (item) => html`<li key=${item.value}>
          <span class="sw" style=${{ background: color(item.color) }} aria-hidden="true"></span>
          <span>${item.label}</span>
        </li>`,
      )}
    </ul>
  </div>`;
}

/**
 * Why something is missing, with what to do about it and the code a click away.
 *
 * @param {{reason: import("./types.js").PreviewReasonInfo, shown?: boolean}}
 *   props - `shown`: the file shows something anyway (only the map is
 *   missing), so the reason is a note, not a warning.
 */
export function PreviewReason({ reason, shown = false }) {
  const values = [[T.common.technical.code, reason.code]];
  if (reason.detail) values.push([L.reason.detail, reason.detail]);
  return html`<div class=${`pv-reason ${shown ? "info" : "warn"}`} role="note">
    <${Icon} name=${shown ? "info" : "alert"} />
    <div>
      <p class="pv-reason-message">${reason.message} <${Tech} value=${values}></${Tech}></p>
      <p class="pv-reason-fix"><b>${L.reason.fix}</b> ${reason.fix}</p>
    </div>
  </div>`;
}

/**
 * The name of a style for people (`cieniowanie`, `hipsometria`…).
 *
 * @param {string|null} style
 * @returns {string}
 */
export function styleName(style) {
  return style === null ? T.common.empty : (L.style[style] ?? style);
}

// The build of a local preview ------------------------------------------------

/**
 * Start and follow the build of an object's local preview: by itself once
 * per object and page for a file within the auto-build limits (decision 6),
 * on demand (`force`) for a larger one or after a failed build.
 */
function useBuild(preview, info, reload) {
  const job = useJob({ onEnd: reload });
  const [problem, setProblem] = useState(null);
  const [starting, setStarting] = useState(false);
  const live = useRef(true);
  useEffect(
    () => () => {
      live.current = false;
    },
    [],
  );

  const start = useCallback(
    async (force) => {
      AUTO_ASKED.add(preview.key);
      setStarting(true);
      setProblem(null);
      try {
        const answer = await preview.build(force);
        if (!live.current) return;
        if ("id" in answer) job.follow(answer.id, answer.kind);
        else reload();
      } catch (error) {
        if (live.current) setProblem(error.problem ?? noAnswer());
      } finally {
        if (live.current) setStarting(false);
      }
    },
    [preview],
  );

  const auto = info?.state === "needs_build" && info.auto_build && !AUTO_ASKED.has(preview.key);
  useEffect(() => {
    if (auto) start(false);
  }, [auto]);
  const building = info?.state === "building" ? (info.job?.id ?? null) : null;
  useEffect(() => {
    if (building) job.follow(building, "preview");
  }, [building]);

  const asked = AUTO_ASKED.has(preview.key);
  return { job, problem, asked, start, busy: starting || job.running };
}

function BuildSection({ info, build, loading }) {
  const { job, problem, asked, start, busy } = build;
  const needed = info.state === "needs_build";
  if (!needed && info.state !== "building" && job.events === null && problem === null) return null;
  // While a build runs or the description reloads after it, nothing is offered.
  const settled = needed && !busy && !loading;
  const note = !settled
    ? null
    : !info.auto_build
      ? L.build.large
      : asked
        ? L.build.again
        : L.build.auto;
  return html`<section class="pv-build" aria-label=${L.build.title}>
    <h4 class="section-title">${L.build.title}</h4>
    ${note ? html`<p class="hint">${note}</p>` : null}
    ${settled && (asked || !info.auto_build)
      ? html`<button type="button" class="btn" onClick=${() => start(true)}>
          <${Icon} name="layers" />${L.build.action}</button>`
      : null}
    ${busy && job.events === null ? html`<${Spinner} label=${L.build.starting} />` : null}
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
    <${JobStatus} job=${job} summary=${buildSummary} />
  </section>`;
}

function buildSummary(events) {
  const result = events.result;
  if (!result) return null;
  const failed = result.failed ?? [];
  return html`<p class="job-summary">${t(L.build.done, {
      built: int(result.built ?? 0),
      cached: int(result.cached ?? 0),
      failed: int(failed.length),
      seconds: seconds(result.seconds ?? 0),
    })}</p>
    ${failed.length
      ? html`<ul class="pv-failures">${failed.map(
          (item) => html`<li key=${item.ref}>
            <${Tech} value=${[[T.common.technical.code, item.code], ["ref", item.ref]]}>${item.detail}</${Tech}>
          </li>`,
        )}</ul>`
      : null}`;
}

// Parts of the pane -----------------------------------------------------------

function Thumbnail({ address, alt, note }) {
  const image = usePreviewImage(address);
  const problem = image.loading ? null : image.problem;
  return html`<figure class="pv-figure">
    <div class="pv-frame">
      ${image.src ? html`<img class="pv-image" src=${image.src} alt=${alt} />` : null}
      ${image.loading ? html`<${Spinner} label=${L.thumbnail.loading} />` : null}
      ${note ? html`<p class="pv-frame-note">${note}</p>` : null}
      ${problem?.reason
        ? html`<${PreviewReason} reason=${problem.reason} />`
        : problem
          ? html`<${ProblemView} problem=${problem} compact />`
          : null}
    </div>
    <figcaption class="pv-caption">${L.thumbnail.caption}</figcaption>
  </figure>`;
}

function Facts({ info, state }) {
  return html`<dl class="kv pv-facts">
    <dt>${L.facts.kind}</dt>
    <dd><${Tech} value=${[["kind", info.kind]]}>${L.kind[info.kind] ?? info.kind}</${Tech}></dd>
    <dt>${L.facts.state}</dt>
    <dd><${Badge} level=${STATE_LEVEL[state] ?? "plain"}>
      <${Tech} value=${[["state", state]]}>${L.state[state] ?? state}</${Tech}>
    </${Badge}></dd>
    <dt>${L.facts.map}</dt>
    <dd>${mapFact(info, state)}</dd>
  </dl>`;
}

function mapFact(info, state) {
  if (state === "building") return L.facts.map_building;
  if (state === "needs_build") return L.facts.map_after_build;
  if (state === "ready" && info.tiles_url) {
    return t(L.facts.map_tiles, { minzoom: info.minzoom, maxzoom: info.maxzoom });
  }
  if (state === "ready" && info.features_url) return L.facts.map_features;
  return L.facts.map_none;
}

function Layers({ layers, name }) {
  return html`<section class="pv-block" aria-label=${L.layers.title}>
    <h4 class="section-title">${L.layers.title} · ${count(layers.length, L.layers.units)}</h4>
    ${layers.map(
      (layer, index) => html`<${Layer} key=${`${index}:${layer.name}`} layer=${layer}
        name=${layer.name ?? stem(name)} open=${index === 0} />`,
    )}
  </section>`;
}

function Layer({ layer, name, open }) {
  const L_ = L.layers;
  const geometry =
    layer.geometry_type === null ? L_.no_geometry : (L_.geometry[layer.geometry_type] ?? layer.geometry_type);
  const features = layer.feature_count === null ? L_.no_count : count(layer.feature_count, L_.features);
  return html`<details class="pv-layer" open=${open}>
    <summary><b class="mono">${name}</b> <span class="faint">${geometry} · ${features}</span></summary>
    <div class="pv-layer-body">
      <dl class="kv pv-kv">
        ${layer.crs
          ? html`<dt>${L_.crs}</dt>
              <dd>${layer.crs.startsWith("EPSG:")
                ? html`<${Crs} code=${layer.crs} />`
                : html`<${Tech} value=${layer.crs}>${L_.crs_custom}</${Tech}>`}</dd>`
          : null}
        <dt>${L_.fields}</dt>
        <dd>${layer.fields.length
          ? html`<ul class="pv-fields">${layer.fields.map(
              (field) => html`<li key=${field.name} title=${field.type}>
                <code>${field.name}</code> <span class="faint">${L_.field_type[field.type] ?? field.type}</span>
              </li>`,
            )}</ul>`
          : L_.no_fields}</dd>
      </dl>
      <${Sample} layer=${layer} />
    </div>
  </details>`;
}

function Sample({ layer }) {
  const rows = layer.sample ?? [];
  if (!rows.length) return layer.feature_count === 0 ? html`<p class="faint pv-note">${L.layers.no_sample}</p>` : null;
  const columns = layer.fields.length ? layer.fields.map((field) => field.name) : Object.keys(rows[0]);
  if (!columns.length) return null;
  const total = layer.feature_count ?? rows.length;
  const caption =
    rows.length < total
      ? t(L.layers.sample, { shown: int(rows.length), total: int(total) })
      : t(L.layers.sample_all, { shown: int(rows.length) });
  return html`<div class="table-wrap pv-table pv-sample" tabindex="0">
    <table>
      <caption>${caption}</caption>
      <thead><tr>${columns.map((column) => html`<th key=${column} scope="col">${column}</th>`)}</tr></thead>
      <tbody>
        ${rows.map(
          (row, index) => html`<tr key=${index}>
            ${columns.map((column) => html`<td key=${column} title=${cellText(row[column])}>${cell(row[column])}</td>`)}
          </tr>`,
        )}
      </tbody>
    </table>
  </div>`;
}

function Points({ points, unit }) {
  const L_ = L.points;
  const classes = points.classes ?? [];
  const total = classes.reduce((sum, item) => sum + item.count, 0);
  const heights =
    points.min?.length > 2 && points.max?.length > 2
      ? `${NUMBER.format(points.min[2])} – ${NUMBER.format(points.max[2])}${unit ? ` ${unit}` : ""}`
      : null;
  const rows = [
    [L_.point_count, int(points.point_count)],
    [
      L_.format,
      t(L_.format_value, {
        container: points.compressed ? "LAZ" : "LAS",
        version: points.version,
        point_format: points.point_format,
      }),
    ],
    [
      L_.density,
      points.density_per_m2 === null || points.density_per_m2 === undefined
        ? null
        : t(L_.density_value, { value: NUMBER.format(points.density_per_m2) }),
    ],
    [L_.heights, heights],
    [L_.created, points.creation_date ? day(points.creation_date) : null],
    [L_.software, points.generating_software],
  ];
  return html`<section class="pv-block" aria-label=${L_.title}>
    <h4 class="section-title">${L_.title}</h4>
    <dl class="kv pv-kv">
      ${rows
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([label, value]) => html`<dt>${label}</dt><dd>${value}</dd>`)}
    </dl>
    ${classes.length
      ? html`<div class="table-wrap pv-table">
          <table>
            <caption>${L_.classes}</caption>
            <tbody>
              ${classes.map((item) => {
                const share = total ? item.count / total : 0;
                return html`<tr key=${item.value}>
                  <td class="num tabular">${item.value}</td>
                  <td>${item.label}</td>
                  <td class="num tabular">${t(L_.class_count, { count: int(item.count), share: SHARE.format(share) })}</td>
                  <td><span class="pv-share" style=${`--share: ${(share * 100).toFixed(1)}%`} aria-hidden="true"></span></td>
                </tr>`;
              })}
            </tbody>
          </table>
        </div>`
      : null}
    <p class="hint pv-note">${t(L_.sampled[points.sampled_from] ?? L_.sampled.spread, { points: int(points.sample_points) })}</p>
  </section>`;
}

function Members({ address }) {
  const L_ = L.members;
  const { data, error } = useResource((signal) => getLinked(address, { signal }), [address]);
  const [all, setAll] = useState(false);
  if (!data) {
    return html`<section class="pv-block" aria-label=${L_.title}>
      <h4 class="section-title">${L_.title}</h4>
      ${error ? html`<${ProblemView} problem=${error.problem} compact />` : html`<${Spinner} label=${L_.loading} />`}
    </section>`;
  }
  const shown = all ? data.members : data.members.slice(0, MEMBERS_SHOWN);
  return html`<section class="pv-block" aria-label=${L_.title}>
    <h4 class="section-title">${L_.title} · ${count(data.total, L_.total)}</h4>
    ${data.truncated
      ? html`<p class="hint pv-note">${t(L_.truncated, { shown: int(data.members.length), total: int(data.total) })}</p>`
      : null}
    ${data.members.length
      ? html`<div class="table-wrap pv-table pv-members" tabindex="0">
          <table>
            <thead><tr>
              <th scope="col">${L_.name}</th><th scope="col">${L_.format}</th><th scope="col" class="num">${L_.size}</th>
            </tr></thead>
            <tbody>
              ${shown.map(
                (member) => html`<tr key=${member.name}>
                  <td class="mono pv-member">${member.directory ? html`<${Icon} name="folder" size=${13} />` : null}${member.name}</td>
                  <td>${member.directory ? L_.directory : member.format === "unknown" ? L_.unknown : member.format}</td>
                  <td class="num tabular">${member.directory ? T.common.empty : bytes(member.size_bytes)}</td>
                </tr>`,
              )}
            </tbody>
          </table>
        </div>`
      : html`<p class="faint pv-note">${L_.empty}</p>`}
    ${shown.length < data.members.length
      ? html`<button type="button" class="btn sm" onClick=${() => setAll(true)}>
          ${t(L_.more, { count: int(data.members.length) })}</button>`
      : null}
  </section>`;
}

// Helpers ---------------------------------------------------------------------

/** A colour of a legend for CSS, only `#rrggbb` (anything else is transparent). */
function color(value) {
  return HEX.test(value) ? value : "transparent";
}

/** A file name without its extension, as GIS programs name its one layer. */
function stem(name) {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
}

function cell(value) {
  if (value === null || value === undefined) return html`<span class="faint">${T.common.empty}</span>`;
  return cellText(value);
}

function cellText(value) {
  if (value === null || value === undefined) return T.common.empty;
  if (typeof value === "boolean") return value ? T.common.yes : T.common.no;
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** A member's size: bytes and kB below a megabyte, then `format.js` sizes. */
function bytes(value) {
  if (value < 1000) return `${int(value)} B`;
  if (value < 1e6) return `${KILO.format(value / 1e3)} kB`;
  return size(value);
}

/** The problem of an answer that never arrived whole (no problem of the server). */
function noAnswer() {
  return {
    type: "about:blank",
    title: T.common.problem.network_title,
    status: 0,
    detail: T.common.problem.network,
    code: "network_error",
  };
}
