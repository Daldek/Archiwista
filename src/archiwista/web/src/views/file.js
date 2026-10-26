/**
 * The file card (docs/SPEC.md UC-04 and 6.5 e; plan v0.1 step 11, v0.2 step
 * 12a): an overlay over the current view with its own address,
 * `file=<store>/<slot path>` and, for one version, `file_version=<version
 * path>`.
 *
 * It shows every version of the slot on an axis, newest first, marking the
 * current one (the standard path) and the `full_sheet/` one, with the pins
 * of the projects the session sees — older versions too. The chosen version
 * has two tabs: „Metadane” — its metadata for people next to the raw values
 * (criterion 6), its licence with the attribution to copy, the paths to copy
 * (this version and the standard path, also as mounted on other computers),
 * the files of the same producer request and the raw sidecar — and
 * „Podgląd” (`file_tab=preview`, style `file_style`): the version's preview
 * (previews.js `PreviewPane`) with „Pokaż podgląd na mapie” when it has
 * tiles or features (the map with `preview=<ref>`). „Porównaj z…” next to
 * the version's title opens the comparison with another version of the
 * slot (`view=compare&a&b`, views/compare.js), and „Pobierz plik” downloads
 * the version's file (api.js `fileAddress`; disabled with its reason while
 * the store is unavailable or the version is gone). Then the slot's problems.
 * „Potwierdź bieżącą wersję” starts a link check (`POST
 * /stores/{store}/link-check`) and shows its result from the job's events.
 * Everything is read by store and path from the index, never from a file URL.
 */

import {
  buildPreview,
  fileAddress,
  getPreview,
  getSlot,
  getVersion,
  listRequestFiles,
  startLinkCheck,
} from "../api.js";
import { useApp } from "../context.js";
import { count, day, size, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { file as L } from "../labels/file.js";
import { T, t } from "../labels/index.js";
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
} from "../ui.js";
import {
  Badge,
  CopyAction,
  Crs,
  DownloadLink,
  FileLink,
  IssueList,
  JobStatus,
  loadCardStyles,
  pinStateName,
  StaleNote,
  storeName,
  useJob,
} from "./cards.js";

await loadCardStyles();

/** Address parameter of the chosen version. */
export const VERSION_PARAM = "file_version";
/** Address parameter of the version's tab: `preview`; the metadata without it. */
export const TAB_PARAM = "file_tab";
/** Address parameter of the preview's style (`PreviewInfo.styles`). */
export const STYLE_PARAM = "file_style";
const TABS = ["meta", "preview"];
// The card's own parameters, gone with it.
const CARD_PARAMS = [VERSION_PARAM, TAB_PARAM, STYLE_PARAM];
const PERCENT = new Intl.NumberFormat("pl-PL", { style: "percent", maximumFractionDigits: 1 });

/**
 * The file card overlay (routes.js `OVERLAYS`, parameter `file`).
 *
 * @param {{route: import("../router.js").Route, value: string,
 *   onClose: () => void}} props - `value` is `<store>/<slot path>`.
 */
export default function FileCard({ route, value, onClose }) {
  const titleId = useId();
  const heading = useRef(null);
  const opener = useRef(document.activeElement);
  const address = parseAddress(value);

  useEffect(() => heading.current?.focus(), [value]);
  useEffect(
    () => () => {
      // Closed by Esc, the button or another view: the version and tab go too.
      const { params } = readRoute();
      if (!params.file && CARD_PARAMS.some((name) => params[name])) {
        setParams(Object.fromEntries(CARD_PARAMS.map((name) => [name, null])), { replace: true });
      }
      if (opener.current?.isConnected) opener.current.focus();
    },
    [],
  );

  return html`<section class="drawer file-card" role="dialog" aria-modal="false"
    aria-labelledby=${titleId}>
    <header class="drawer-head">
      <div class="fc-title">
        <div class="eyebrow">${L.eyebrow}</div>
        <h2 id=${titleId} tabindex="-1" ref=${heading}>${address ? fileName(address.slot) : value}</h2>
      </div>
      <button type="button" class="btn ghost icon-btn" onClick=${onClose} title=${L.close}
        aria-label=${L.close}><${Icon} name="x" /></button>
    </header>
    <div class="drawer-body">
      ${address
        ? html`<${SlotCard} key=${value} store=${address.store} slot=${address.slot}
            wanted=${route.params[VERSION_PARAM] ?? null}
            tab=${TABS.includes(route.params[TAB_PARAM]) ? route.params[TAB_PARAM] : TABS[0]}
            style=${route.params[STYLE_PARAM] ?? null} />`
        : html`<p class="hint warn">${t(L.bad_address, { value })}</p>`}
    </div>
  </section>`;
}

/**
 * Split the `file` parameter: the store id (no `/` in it) and the slot path.
 *
 * @param {string} value
 * @returns {{store: string, slot: string}|null}
 */
export function parseAddress(value) {
  const slash = value.indexOf("/");
  if (slash <= 0 || slash === value.length - 1) return null;
  return { store: value.slice(0, slash), slot: value.slice(slash + 1) };
}

function fileName(path) {
  return path.slice(path.lastIndexOf("/") + 1);
}

function SlotCard({ store, slot, wanted, tab, style }) {
  const { data: card, error, loading, reload } = useResource(
    (signal) => getSlot(store, slot, { signal }),
    [store, slot],
  );
  if (!card) {
    return error ? html`<${ProblemView} problem=${error.problem} />` : html`<${Spinner} />`;
  }
  const versions = newestFirst(card.versions);
  const chosen =
    versions.find((version) => version.path === wanted) ??
    versions.find((version) => version.path === card.current) ??
    versions[0] ??
    null;
  return html`
    <${CardHeading} card=${card} />
    ${error ? html`<${ProblemView} problem=${error.problem} compact />` : null}
    <${StaleNote} stores=${card.stale_stores} />
    ${card.problems.length
      ? html`<section class="det-sec">
          <h3 class="section-title">${count(card.problems.length, T.common.units.problems)}</h3>
          <${IssueList} issues=${card.problems} store=${store} currentSlot=${card.slot} />
        </section>`
      : null}
    <${VersionAxis} versions=${versions} chosen=${chosen} />
    ${chosen
      ? html`<${VersionDetails} key=${chosen.path} store=${store} card=${card} version=${chosen}
          versions=${versions} tab=${tab} style=${style} />`
      : html`<section class="det-sec"><${StandardPathRows} card=${card} /></section>`}
    <${LinkCheck} store=${store} card=${card} versions=${versions} onDone=${reload} />
    ${loading ? html`<${Spinner} quiet />` : null}
  `;
}

/** Versions newest first: data year, data date, label, then path. */
function newestFirst(versions) {
  const key = (version) => [
    version.data_year ?? -Infinity,
    version.data_date ?? "",
    version.label ?? "",
    version.path,
  ];
  return [...versions].sort((a, b) => {
    const [left, right] = [key(a), key(b)];
    for (let index = 0; index < left.length; index += 1) {
      if (left[index] !== right[index]) return left[index] < right[index] ? 1 : -1;
    }
    return 0;
  });
}

function CardHeading({ card }) {
  const { health } = useApp();
  const segment = card.segment;
  const product = segment.known
    ? segment.label
    : t(L.unknown_product, { producer: segment.producer });
  return html`<div class="fc-heading">
    <p class=${segment.known ? "fc-product" : "fc-product unknown"}>
      <${Tech} value=${segmentValues(card)}>${product}</${Tech}>
    </p>
    <div class="chip-row">
      ${card.unit
        ? html`<span class="chip static">${L.unit} <b class="mono">${card.unit}</b></span>`
        : null}
      ${card.country ? html`<span class="chip static">${card.country}</span>` : null}
      <span class="chip static">
        <${Tech} value=${[["store", card.store]]}>${storeName(health, card.store)}</${Tech}>
      </span>
      <span class="chip static">${count(card.versions.length, L.versions_count)}</span>
      ${card.status !== "ok"
        ? html`<${Badge} level=${card.status === "missing" ? "bad" : "warn"}>
            <${Tech} value=${[["status", card.status]]}>${L.status[card.status] ?? card.status}</${Tech}>
          </${Badge}>`
        : null}
    </div>
  </div>`;
}

function segmentValues(card) {
  const segment = card.segment;
  const values = [
    ["segment", segment.path],
    ["dataset_key", segment.dataset_key],
    ["product", card.product],
    ["producer", segment.producer],
    ["slot", card.slot],
  ];
  return values.filter(([, value]) => value);
}

function VersionAxis({ versions, chosen }) {
  const select = (path) => setParams({ [VERSION_PARAM]: path }, { replace: true });
  return html`<section class="det-sec" aria-labelledby="fc-axis-title">
    <h3 class="section-title" id="fc-axis-title">${L.axis.title}</h3>
    <ol class="fc-axis">
      ${versions.map((version) => {
        const on = version === chosen;
        return html`<li key=${version.path}
          class=${`fc-version${on ? " on" : ""}${version.is_current ? " current" : ""}${version.state === "missing" ? " gone" : ""}`}>
          <span class="fc-dot" aria-hidden="true"></span>
          <button type="button" class="fc-pick" aria-pressed=${on ? "true" : "false"}
            onClick=${() => select(version.path)}>
            <span class="fc-year">${version.data_year ?? L.axis.no_year}</span>
            <span class="fc-label mono">${version.label ?? L.axis.no_label}</span>
            ${version.data_date ? html`<span class="faint">${day(version.data_date)}</span>` : null}
          </button>
          <span class="fc-marks">
            ${version.is_current
              ? html`<${Badge} level="info" title=${L.axis.current_title}>${L.axis.current}</${Badge}>`
              : null}
            ${version.is_full_sheet
              ? html`<${Badge} level="ok" title=${L.axis.full_sheet_title}>${L.axis.full_sheet}</${Badge}>`
              : null}
            ${version.state === "missing"
              ? html`<${Badge} level="bad">${t(L.axis.missing, { since: day(version.missing_since) })}</${Badge}>`
              : null}
          </span>
          ${version.pinned_by.length ? html`<${Pins} pins=${version.pinned_by} />` : null}
        </li>`;
      })}
    </ol>
  </section>`;
}

function Pins({ pins }) {
  return html`<p class="fc-pins">
    <span class="faint">${L.axis.pinned}</span>${" "}
    ${pins.map((pin, index) => {
      const name = pin.task
        ? t(L.axis.pin, { name: pin.name, task: pin.task })
        : t(L.axis.pin_no_task, { name: pin.name });
      return html`<span key=${`${pin.project}:${pin.task}`} class="fc-pin">
        ${index ? ", " : ""}<${Link} view="projects" params=${{ project: pin.project }}>${name}</${Link}>
        ${pin.state !== "ok"
          ? html` <${Badge} level="bad">${pinStateName(pin.state)}</${Badge}>`
          : null}
      </span>`;
    })}
  </p>`;
}

function VersionDetails({ store, card, version, versions, tab, style }) {
  const panel = useId();
  const title = version.label
    ? t(L.version.title, { label: version.label })
    : L.version.title_plain;
  return html`<section class="det-sec fc-details" aria-label=${title}>
    <div class="fc-version-head">
      <h3 class="fc-version-title">
        <${Tech} value=${[["path", version.path], ["ref", version.ref]]}>${title}</${Tech}>
      </h3>
      <div class="fc-version-actions">
        <${CompareWith} versions=${versions} version=${version} />
        <${DownloadVersion} store=${store} card=${card} version=${version} />
      </div>
    </div>
    <${VersionTabs} tab=${tab} panel=${panel} />
    <div class="fc-panel" role="tabpanel" id=${panel} aria-labelledby=${`${panel}-${tab}`}>
      ${tab === "preview"
        ? html`<${VersionPreview} store=${store} version=${version} style=${style} />`
        : html`<${VersionMetadata} store=${store} card=${card} version=${version} />`}
    </div>
  </section>`;
}

/**
 * „Porównaj z…”: this version next to another one of the slot in the
 * comparison (views/compare.js) — the older one as A, so the comparison
 * reads as the change from A to B.
 *
 * @param {{versions: import("../types.js").Version[], version:
 *   import("../types.js").Version}} props - `versions` newest first.
 */
function CompareWith({ versions, version }) {
  const others = versions.filter((other) => other !== version);
  if (!others.length) return null;
  const mine = versions.indexOf(version);
  return html`<details class="fc-compare">
    <summary class="btn sm" title=${L.compare.title}><${Icon} name="layers" size=${14} />${L.compare.action}</summary>
    <ul class="fc-compare-list" aria-label=${L.compare.list}>
      ${others.map((other) => {
        const [a, b] = versions.indexOf(other) > mine ? [other, version] : [version, other];
        return html`<li key=${other.path}>
          <${Link} view="compare" params=${{ a: a.ref, b: b.ref }}>
            <span class="fc-year">${other.data_year ?? L.axis.no_year}</span>
            <span class="fc-label mono">${other.label ?? L.axis.no_label}</span>
            ${other.data_date ? html`<span class="faint">${day(other.data_date)}</span>` : null}
          </${Link}>
        </li>`;
      })}
    </ul>
  </details>`;
}

/**
 * „Pobierz plik” of a version: disabled while its store is unavailable (the
 * card is answered from the index) or the version is gone from the store.
 */
function DownloadVersion({ store, card, version }) {
  let reason = null;
  if (card.stale) reason = "store_unavailable";
  else if (version.state === "missing") reason = "version_missing";
  const address = fileAddress({ store, version: version.path });
  return html`<${DownloadLink} address=${address} reason=${reason} />`;
}

/**
 * The tabs of a version (ARIA tabs: arrows, Home and End move between them);
 * the chosen one lives in the address.
 */
function VersionTabs({ tab, panel }) {
  const select = (name) => setParams({ [TAB_PARAM]: name === TABS[0] ? null : name }, { replace: true });
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

function VersionMetadata({ store, card, version }) {
  const { data, error } = useResource(
    (signal) => getVersion(store, version.path, { signal }),
    [store, version.path],
  );
  if (error && !data) return html`<${ProblemView} problem=${error.problem} compact />`;
  if (!data) return html`<${Spinner} label=${L.version.loading} />`;
  return html`
    <${Metadata} details=${data} />
    <${License} details=${data} />
    <${Paths} details=${data} card=${card} />
    ${data.parent_request ? html`<${RequestFiles} details=${data} />` : null}
    <${Sidecar} sidecar=${data.sidecar} />
  `;
}

/** The version's preview; its style lives in the address. */
function VersionPreview({ store, version, style }) {
  const preview = useMemo(
    () => ({
      key: version.ref,
      load: (signal) => getPreview(store, version.path, { signal }),
      build: (force) => buildPreview(store, version.path, { force }),
    }),
    [store, version.path, version.ref],
  );
  return html`<${PreviewPane} preview=${preview} name=${fileName(version.path)} style=${style}
    onStyle=${(value) => setParams({ [STYLE_PARAM]: value }, { replace: true })}>
    ${(info, shown) =>
      info.state === "ready" && (info.tiles_url || info.features_url)
        ? html`<${ShowOnMap} version=${version} style=${info.features_url ? null : shown} />`
        : null}
  </${PreviewPane}>`;
}

/**
 * „Pokaż podgląd na mapie”: the map with the version's tiles or features and
 * its outline, in the style shown; the card closes, the map keeps its state.
 */
function ShowOnMap({ version, style }) {
  const route = useRoute();
  const kept =
    (route.view ?? startView().id) === "map"
      ? Object.fromEntries(Object.entries(route.params).filter(([name]) => name !== "file" && !CARD_PARAMS.includes(name)))
      : {};
  const params = { ...kept, [PREVIEW_PARAM]: version.ref, [PREVIEW_STYLE_PARAM]: style };
  return html`<${Link} class="btn" view="map" params=${params} title=${L.preview_on_map_title}>
    <${Icon} name="map" />${L.preview_on_map}</${Link}>`;
}

function Metadata({ details }) {
  const version = details.version;
  const L_ = L.version;
  const rows = [
    [L_.data_year, version.data_year ?? T.common.empty, true],
    [L_.data_date, version.data_date ? day(version.data_date) : null],
    [
      L_.label,
      version.label
        ? html`<span class="mono">${version.label}</span>${version.label_source
              ? html` <${Tech} value=${[["label_source", version.label_source]]}>
                  <span class="faint">${L_.label_source[version.label_source] ?? version.label_source}</span>
                </${Tech}>`
              : null}`
        : null,
    ],
    [L_.campaign, details.campaign],
    [L_.survey_work_id, details.survey_work_id ? html`<span class="mono">${details.survey_work_id}</span>` : null],
    [L_.edition, details.edition],
    [
      L_.full_sheet,
      version.full_sheet === null
        ? null
        : t(L_.full_sheet_claim, { answer: version.full_sheet ? T.common.yes : T.common.no }),
    ],
    [L_.coverage, details.coverage === null ? null : PERCENT.format(details.coverage)],
    [L_.resolution, details.resolution],
    [L_.horizontal, html`<${Crs} code=${version.crs.horizontal} />`, true],
    [L_.vertical, version.crs.vertical ? html`<${Crs} code=${version.crs.vertical} />` : null],
    [L_.nodata, details.nodata === null ? null : String(details.nodata)],
    [
      L_.size,
      version.size_bytes === null
        ? null
        : html`<${Tech} value=${[["size_bytes", String(version.size_bytes)]]}>${size(version.size_bytes)}</${Tech}>`,
    ],
    [
      L_.sha256,
      version.sha256
        ? html`<${Tech} value=${[["sha256", version.sha256]]}>
            <span class="mono">${version.sha256.slice(0, 12)}…</span>
          </${Tech}>`
        : null,
    ],
    [L_.downloaded, version.downloaded_at ? stamp(version.downloaded_at) : null],
    [L_.location, html`<${Location} details=${details} />`, true],
  ];
  return html`
    ${details.has_meta ? null : html`<p class="hint warn">${L_.no_meta}</p>`}
    <dl class="kv fc-meta">
      ${rows
        .filter(([, value, always]) => always || (value !== null && value !== undefined && value !== ""))
        .map(([name, value]) => html`<dt>${name}</dt><dd>${value}</dd>`)}
      ${details.source_files.length
        ? html`<dt>${L_.source_files}</dt>
            <dd><ul class="fc-list">${details.source_files.map(
              (path) => html`<li key=${path}><code class="path">${path}</code>
                <${CopyButton} text=${path} label=${path} /></li>`,
            )}</ul></dd>`
        : null}
    </dl>`;
}

function Location({ details }) {
  const location = details.version.location;
  const L_ = L.version;
  const kind = L_.location_kind[location.kind] ?? location.kind;
  const why =
    location.kind === "none"
      ? L_.location_reason[location.reason] ?? location.reason
      : L_.location_source[location.source] ?? location.source;
  const values = [["kind", location.kind]];
  if (location.source) values.push(["source", location.source]);
  if (location.reason) values.push(["reason", location.reason]);
  if (details.native_crs) values.push(["native_crs", details.native_crs]);
  return html`<${Tech} value=${values}>${why ? `${kind} — ${why}` : kind}</${Tech}>`;
}

/**
 * A sidecar's licence address as a link target, or `null`: only `http(s)` to
 * another computer. The sidecar comes from the shared store, and a link to a
 * loopback address would reach other servers of this computer.
 *
 * @param {*} value - `license.url` of the raw sidecar.
 * @returns {string|null}
 */
function licenseLink(value) {
  if (typeof value !== "string") return null;
  let address;
  try {
    address = new URL(value);
  } catch {
    return null;
  }
  if (address.protocol !== "http:" && address.protocol !== "https:") return null;
  const host = address.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  const loopback =
    host === "localhost" ||
    host.endsWith(".localhost") ||
    /^127\./.test(host) ||
    host === "0.0.0.0" ||
    host === "::1" ||
    host === "::" ||
    host.startsWith("::ffff:127.");
  return loopback ? null : address.href;
}

function License({ details }) {
  const url = licenseLink(details.sidecar?.license?.url);
  return html`<div class="fc-block">
    <h4 class="section-title">${L.license.title}</h4>
    ${details.license || details.attribution
      ? html`
          ${details.license ? html`<p class="fc-license"><b>${details.license}</b>
              ${url ? html` · <a href=${url} target="_blank" rel="noopener noreferrer">${url}</a>` : null}
            </p>` : null}
          ${details.attribution
            ? html`<p class="fc-attribution"><span class="faint">${L.license.attribution}:</span>${" "}${details.attribution}</p>
                <${CopyAction} text=${details.attribution} label=${L.license.copy_attribution} />`
            : null}
        `
      : html`<p class="faint">${L.license.none}</p>`}
  </div>`;
}

function PathRows({ title, hint, paths, copyLabel, primary }) {
  return html`<div class="fc-path">
    <p class="fc-path-head"><b>${title}</b> <span class="faint">${hint}</span></p>
    <p class="fc-path-row"><code class="path">${paths.local}</code></p>
    <${CopyAction} text=${paths.local} label=${copyLabel} primary=${primary} />
    ${paths.aliases.map(
      (alias) => html`<p key=${alias} class="fc-path-row">
        <span class="faint">${L.paths.alias}:</span> <code class="path">${alias}</code>
        <${CopyButton} text=${alias} label=${alias} />
      </p>`,
    )}
  </div>`;
}

/**
 * Paths to copy: this version's (stable) and the slot's standard path (the
 * current version, which a newer download moves). A file without versions/
 * (Kartograf 0.6.x) is its own standard path, so it shows once.
 */
function Paths({ details, card }) {
  const plain = details.version.path === details.slot;
  return html`<div class="fc-block">
    <h4 class="section-title">${L.paths.title}</h4>
    ${!plain && details.paths
      ? html`<${PathRows} title=${L.paths.version} hint=${L.paths.version_hint} paths=${details.paths}
          copyLabel=${L.paths.copy_version} primary />`
      : null}
    <${StandardPathRows} card=${card} />
  </div>`;
}

function StandardPathRows({ card }) {
  if (!card.paths) return html`<p class="faint">${L.paths.gone}</p>`;
  return html`<${PathRows} title=${L.paths.standard} hint=${L.paths.standard_hint} paths=${card.paths}
    copyLabel=${L.paths.copy_standard} />`;
}

function RequestFiles({ details }) {
  const { data, error } = useResource(
    (signal) => listRequestFiles(details.parent_request, { signal }),
    [details.parent_request],
  );
  return html`<div class="fc-block">
    <h4 class="section-title">
      <${Tech} value=${[["parent_request", details.parent_request]]}>${L.version.request}</${Tech}>
    </h4>
    <p class="hint">${L.version.request_hint}</p>
    ${data
      ? html`<ul class="fc-list">${data.items.map((item) => {
          const self = item.version === details.version.path;
          return html`<li key=${`${item.store}:${item.version}`}>
            ${self
              ? html`<b class="mono">${fileName(item.slot)}</b> <span class="faint">${L.version.request_this}</span>`
              : html`<${FileLink} store=${item.store} slot=${item.slot} version=${item.version} class="mono">
                  ${fileName(item.slot)}</${FileLink}>`}
            <span class="faint"> · ${[item.country, item.label].filter(Boolean).join(" · ")}</span>
            ${item.is_current ? html` <${Badge} level="info">${L.version.request_current}</${Badge}>` : null}
          </li>`;
        })}</ul>`
      : error
        ? html`<${ProblemView} problem=${error.problem} compact />`
        : html`<${Spinner} quiet />`}
  </div>`;
}

function Sidecar({ sidecar }) {
  if (!sidecar) return html`<p class="faint">${L.sidecar.none}</p>`;
  const text = JSON.stringify(sidecar, null, 2);
  return html`<details class="fc-sidecar">
    <summary>${L.sidecar.title}</summary>
    <pre class="sidecar" tabindex="0">${text}</pre>
    <${CopyAction} text=${text} label=${L.sidecar.copy} />
  </details>`;
}

function LinkCheck({ store, card, versions, onDone }) {
  const job = useJob({ onEnd: onDone });
  const busy = job.starting || job.running;
  const labelOf = (path) => versions.find((version) => version.path === path)?.label ?? path;
  const summary = (events) => {
    const result = events.result;
    if (!result) return null;
    const text = L.link_check.result[result.status] ?? result.status;
    const values = [["status", result.status]];
    if (result.expected) values.push(["expected", result.expected]);
    if (result.confirmed) values.push(["confirmed", result.confirmed]);
    return html`<p class=${`job-summary link-${result.status}`}>
      <${Tech} value=${values}>${t(text, { version: labelOf(result.confirmed ?? result.expected) })}</${Tech}>
    </p>`;
  };
  return html`<section class="det-sec fc-link-check">
    <div class="fc-action">
      <button type="button" class="btn" disabled=${busy}
        onClick=${() => job.run(() => startLinkCheck(store, card.slot), "link_check")}>
        ${busy ? html`<span class="spinner" aria-hidden="true"></span>` : html`<${Icon} name="check" />`}
        ${L.link_check.action}
      </button>
      <span class="hint">${L.link_check.hint}</span>
    </div>
    <${JobStatus} job=${job} summary=${summary} />
  </section>`;
}
