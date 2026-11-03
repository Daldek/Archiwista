/**
 * Projects' own data on the map, and the pieces its views share (docs/SPEC.md
 * 4.7.1; plan v0.2 step 15).
 *
 * The map in a project's context (`project=<key>` of the address) shows the
 * layer „Dane własne”: the extents of the project's own files (`outline` of
 * `GET /projects/{project}/files`, every page) drawn by map/canvas.js — a
 * click opens the file's card (views/own.js) and shows its objects or tiles
 * (`preview=<ref>`, map/previews.js) — next to the outlines of the versions
 * pinned in the project (`/map/footprints?project=`).
 *
 * Shared with the card, the Projects view and the comparison: the address
 * parameters of the card (`own=<project>/<file_id>` and its own ones), the
 * parts of a `file:`/`snapshot:` ref, the file of a ref (its `file_id`, found
 * by its path in the file list — a ref holds no id) and the change since the
 * last snapshot for people. Nothing here imports map/previews.js, which uses
 * this module for the own data it previews.
 */

import { getProject, listOwnFiles } from "../api.js";
import { day, int } from "../format.js";
import { useResource } from "../hooks.js";
import { t } from "../labels/index.js";
import { own as L } from "../labels/own.js";
import { Link, useRoute } from "../router.js";
import { html, Icon, loadStylesheet, ProblemView, Spinner, Tech, useMemo } from "../ui.js";
import { Badge } from "../views/cards.js";
import { geometryBounds, unionBounds } from "./geo.js";

await loadStylesheet(new URL("../views/own.css", import.meta.url));

/** Address parameter of the own file card: `<project>/<file_id>`. */
export const OWN_PARAM = "own";
/** The card's chosen version: a snapshot's label; none: the working file. */
export const OWN_VERSION_PARAM = "own_version";
/** The card's tab of a version: `preview`; the metadata without it. */
export const OWN_TAB_PARAM = "own_tab";
/** The preview's style in the card (`PreviewInfo.styles`). */
export const OWN_STYLE_PARAM = "own_style";
/** `1`: the card shows the Wachlarz of the file's versions. */
export const OWN_FAN_PARAM = "own_fan";
/** The card's own parameters, gone with it. */
export const OWN_CARD_PARAMS = [OWN_VERSION_PARAM, OWN_TAB_PARAM, OWN_STYLE_PARAM, OWN_FAN_PARAM];
/** The map's project context: its own data and the outlines of its pins. */
export const PROJECT_PARAM = "project";

// Rules of archiwista/refs.py: project keys and snapshot labels.
const PROJECT = /^[a-z0-9-]+$/;
const LABEL = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const FILE_ID = /^[0-9a-f]{16}$/;
const PAGE = 200;
// Own files on the map at most (25 pages); a larger folder says so.
const MAP_FILES = 5000;
const CHANGE_LEVEL = { unsnapshotted: "plain", unchanged: "ok", changed: "warn" };

/**
 * The value of `OWN_PARAM` for a file.
 *
 * @param {string} project
 * @param {string} fileId
 * @returns {string}
 */
export function ownValue(project, fileId) {
  return `${project}/${fileId}`;
}

/**
 * The project and file of `OWN_PARAM`.
 *
 * @param {string} value
 * @returns {{project: string, fileId: string}|null} Null for anything else.
 */
export function readOwnValue(value) {
  const slash = value.indexOf("/");
  const project = value.slice(0, slash);
  const fileId = value.slice(slash + 1);
  return slash > 0 && PROJECT.test(project) && FILE_ID.test(fileId) ? { project, fileId } : null;
}

/**
 * The parameters opening the card of an own file (and nothing of the card
 * before it).
 *
 * @param {string} project
 * @param {string} fileId
 * @param {{label?: string|null, tab?: string|null, style?: string|null}} [version] -
 *   A snapshot's label, the tab and the preview's style.
 * @returns {Object<string, string|null>}
 */
export function ownCardPatch(project, fileId, { label = null, tab = null, style = null } = {}) {
  return {
    [OWN_PARAM]: ownValue(project, fileId),
    [OWN_VERSION_PARAM]: label,
    [OWN_TAB_PARAM]: tab,
    [OWN_STYLE_PARAM]: style,
    [OWN_FAN_PARAM]: null,
  };
}

/**
 * The parts of an own file's or snapshot's `ref` (archiwista/refs.py):
 * `file:<project>:<path>`, `snapshot:<project>:<label>:<path>`.
 *
 * @param {string|null|undefined} ref
 * @returns {{kind: "file"|"snapshot", project: string, label: string|null,
 *   path: string}|null} Null for another kind of object or a malformed ref.
 */
export function readOwnRef(ref) {
  if (typeof ref !== "string") return null;
  const [kind, rest] = partition(ref);
  if (kind !== "file" && kind !== "snapshot") return null;
  const [project, after] = partition(rest);
  if (!PROJECT.test(project)) return null;
  let label = null;
  let path = after;
  if (kind === "snapshot") {
    [label, path] = partition(after);
    if (!LABEL.test(label)) return null;
  }
  return path ? { kind, project, label, path } : null;
}

/**
 * The listed file of a project with this path: its `file_id` and state. A
 * ref names a file by its path; the routes by its id.
 *
 * @param {string} project
 * @param {string} path - Relative to the data folder, as in a ref.
 * @param {{signal?: AbortSignal}} [options]
 * @returns {Promise<import("../types.js").OwnFileItem|null>} Null when the
 *   folder's index has no such file.
 */
export async function findOwnFile(project, path, { signal } = {}) {
  let cursor = null;
  do {
    const page = await listOwnFiles(project, { q: path, limit: PAGE, cursor }, { signal });
    const found = page.items.find((item) => item.path === path);
    if (found) return found;
    cursor = page.next_cursor;
  } while (cursor);
  return null;
}

/**
 * The file of an own ref (`readOwnRef` and `findOwnFile`).
 *
 * @param {string|null|undefined} ref
 * @returns {{parts: ReturnType<typeof readOwnRef>, file:
 *   import("../types.js").OwnFileItem|null, loading: boolean, error:
 *   import("../api.js").ApiError|undefined}}
 */
export function useOwnFile(ref) {
  const parts = readOwnRef(ref);
  const answer = useResource(
    (signal) =>
      parts ? findOwnFile(parts.project, parts.path, { signal }).then((file) => ({ ref, file })) : Promise.resolve(null),
    [parts ? ref : ""],
  );
  const file = parts && answer.data?.ref === ref ? answer.data.file : null;
  return { parts, file, loading: Boolean(parts) && answer.loading, error: parts ? answer.error : undefined };
}

/**
 * The change of a file since its last snapshot for people, e.g. „zmieniony
 * od migawki z 2026.10.18”.
 *
 * @param {{change: string, last_snapshot: import("../types.js").LastSnapshot|null}} file
 * @returns {string}
 */
export function changeText(file) {
  if (!file.last_snapshot || !L.change[file.change] || file.change === "unsnapshotted") return L.change.unsnapshotted;
  return t(L.change[file.change], { date: day(file.last_snapshot.created_at) });
}

/**
 * The change of a file since its last snapshot as a badge.
 *
 * @param {{file: {change: string, last_snapshot: import("../types.js").LastSnapshot|null}}} props
 */
export function ChangeBadge({ file }) {
  const values = [["change", file.change]];
  if (file.last_snapshot) values.push(["last_snapshot", file.last_snapshot.label]);
  return html`<${Badge} level=${CHANGE_LEVEL[file.change] ?? "plain"} title=${L.change_title[file.change]}>
    <${Tech} value=${values}>${changeText(file)}</${Tech}>
  </${Badge}>`;
}

/**
 * The state of a file when not `ok`: unrecognised, unreadable or gone.
 *
 * @param {{file: {state: string}}} props
 */
export function StateBadge({ file }) {
  if (file.state === "ok") return null;
  return html`<${Badge} level=${file.state === "missing" ? "bad" : "warn"}>
    <${Tech} value=${[["state", file.state]]}>${L.state[file.state] ?? file.state}</${Tech}>
  </${Badge}>`;
}

/**
 * A link opening the card of an own file over the current view, keeping the
 * view's own parameters.
 *
 * @param {{project: string, fileId: string, label?: string|null,
 *   tab?: string|null, style?: string|null, children: *}} props - Other
 *   props go to the `<a>` element.
 */
export function OwnCardLink({ project, fileId, label = null, tab = null, style = null, children, ...rest }) {
  const route = useRoute();
  const params = { ...route.params, ...ownCardPatch(project, fileId, { label, tab, style }) };
  return html`<${Link} view=${route.view} params=${params} ...${rest}>${children}</${Link}>`;
}

/**
 * The file name of a path in a data folder.
 *
 * @param {string} path
 * @returns {string}
 */
export function ownName(path) {
  return path.slice(path.lastIndexOf("/") + 1);
}

/**
 * The outline of a snapshot on the map: its copy's WGS84 box as a polygon.
 *
 * @param {import("../types.js").SnapshotItem} snapshot
 * @returns {import("../types.js").Geometry|null}
 */
export function snapshotOutline(snapshot) {
  const box = snapshot.extent?.wgs84;
  if (!Array.isArray(box) || box.length !== 4) return null;
  const [west, south, east, north] = box;
  return {
    type: "Polygon",
    coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
  };
}

/**
 * The layer „Dane własne” of the map in a project's context: every page of
 * the project's files with their outlines, and the project's name.
 *
 * @param {string|null} project - `PROJECT_PARAM` of the address.
 * @param {string} dataKey - Changes when the index or the own data does.
 * @returns {{project: string|null, name: string|null, folder:
 *   import("../types.js").OwnFolder|null, items:
 *   import("../types.js").OwnFileItem[], unlocated: number, more: boolean,
 *   extent: number[]|null, loading: boolean, error:
 *   import("../api.js").ApiError|undefined}} `items`: the files with an
 *   outline; `more`: the folder has more files than the map takes.
 */
export function useOwnLayer(project, dataKey) {
  const answer = useResource(
    async (signal) => {
      if (!project) return null;
      const files = [];
      let folder = null;
      let cursor = null;
      do {
        const page = await listOwnFiles(project, { limit: PAGE, cursor }, { signal });
        folder = page.folder;
        files.push(...page.items);
        cursor = page.next_cursor;
      } while (cursor && files.length < MAP_FILES);
      return { project, folder, files, more: Boolean(cursor) };
    },
    [project ?? "", dataKey],
  );
  const named = useResource(
    (signal) => (project ? getProject(project, { signal }).then((card) => ({ project, name: card.name })) : Promise.resolve(null)),
    [project ?? ""],
  );
  const data = project && answer.data?.project === project ? answer.data : null;
  const items = useMemo(() => (data ? data.files.filter((item) => item.outline && item.state !== "missing") : []), [data]);
  const extent = useMemo(() => unionBounds(items.map((item) => geometryBounds(item.outline))), [items]);
  return {
    project: project || null,
    name: project && named.data?.project === project ? named.data.name : project || null,
    folder: data?.folder ?? null,
    items,
    unlocated: data ? data.files.filter((item) => !item.outline && item.state !== "missing").length : 0,
    more: Boolean(data?.more),
    extent,
    loading: Boolean(project) && answer.loading,
    error: project ? answer.error : undefined,
  };
}

/**
 * The layer „Dane własne” in the map legend: the project, how many files
 * have an extent on the map, what it cannot show, „Pokaż wszystkie” and the
 * project's view.
 *
 * @param {{own: ReturnType<typeof useOwnLayer>, onFrame: (bbox: number[]) => void}} props
 */
export function OwnLegend({ own, onFrame }) {
  const title = t(L.map.project, { name: own.name ?? own.project });
  let body = null;
  if (own.error && !own.folder) body = html`<${ProblemView} problem=${own.error.problem} compact />`;
  else if (!own.folder) body = html`<${Spinner} label=${L.map.loading} />`;
  else if (own.folder.scanned_at === null) body = html`<p class="legend-note">${L.map.not_scanned}</p>`;
  return html`<section class="legend-section own-legend" aria-label=${L.map.title}>
    <div class="legend-section-head">
      <b>${L.map.title}</b>
      <${Link} class="btn ghost sm" view="projects" params=${{ project: own.project }} title=${L.map.open_project_title}>
        <${Icon} name="folder" size=${13} />${L.map.open_project}
      </${Link}>
    </div>
    <span class="legend-sub">${title}</span>
    ${body}
    ${own.folder && own.folder.scanned_at !== null
      ? html`<div class="legend-row"><span class="sw sw-own" aria-hidden="true"></span>
          <span>${own.items.length ? t(L.map.files, { count: int(own.items.length) }) : L.map.located_none}</span></div>
          ${own.unlocated ? html`<p class="legend-note">${t(L.map.unlocated, { count: int(own.unlocated) })}</p>` : null}
          ${own.more ? html`<p class="legend-note warn">${t(L.map.more, { count: int(own.items.length) })}</p>` : null}
          ${own.extent
            ? html`<button type="button" class="btn sm own-frame" title=${L.map.frame_title} onClick=${() => onFrame(own.extent)}>
                <${Icon} name="search" size=${13} />${L.map.frame}</button>`
            : null}`
      : null}
  </section>`;
}

function partition(text) {
  const at = text.indexOf(":");
  return at < 0 ? [text, ""] : [text.slice(0, at), text.slice(at + 1)];
}
