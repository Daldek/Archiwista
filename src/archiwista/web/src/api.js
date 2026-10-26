/**
 * Client of the Archiwista HTTP API (`/api/v1`): the only way the interface
 * talks to the server (docs/plans/2026-10-18-plan-v0.1.md, WWW contract). One function per
 * route, named after its OpenAPI `operationId` in camelCase (`list_slots` →
 * `listSlots`); answers are typed in `types.js`. Addresses the API gives in
 * its answers (`thumbnail_url`, `members_url` of `PreviewInfo`) are never
 * composed here: `apiAddress` adds their documented parameters, `getImage`
 * and `getLinked` fetch them with the same session header; `apiTemplate`
 * does the same for the templates a map fills (`tiles_url`), and
 * `apiHeaders` gives the map the session header for API addresses only.
 *
 * Session (A-ADR-012 errata 1 and 2, SPEC 10.1): `archiwista serve` opens
 * `/#token=…`. `startSession` first removes the token from the address
 * (`history.replaceState`, so it stays in no history entry or bookmark),
 * then exchanges it (`POST /session`) and keeps the session's CSRF token in
 * this origin's `sessionStorage`; every request, reads included, carries it
 * in `X-Archiwista-CSRF` next to the `HttpOnly` session cookie, which
 * browsers also send to other ports of the host. A tab without the token
 * (a new one, a link opened in another tab) asks the open tabs of this
 * origin for it (`BroadcastChannel`); a tab starting a new session tells
 * them its token. Job events stream through `fetch`, which can send the
 * header (`EventSource` cannot), resuming after `Last-Event-ID`. Errors are
 * RFC 9457 problems thrown as `ApiError`: `code` is a code of the Nogat error
 * registry, `details.reason` the project's own cause; a `401`, or a `403` with
 * the reason `csrf_rejected`, of any request after the start goes to the
 * `onSessionLost` listeners, so the shell can say how to open a new session.
 */

import { T, t } from "./labels/index.js";

/** @typedef {import("./types.js").Problem} Problem */
/** @typedef {import("./types.js").SessionState} SessionState */
/** @typedef {import("./types.js").NewSession} NewSession */
/** @typedef {import("./types.js").OneTimeToken} OneTimeToken */
/** @typedef {import("./types.js").Health} Health */
/** @typedef {import("./types.js").SourceList} SourceList */
/** @typedef {import("./types.js").StoreList} StoreList */
/** @typedef {import("./types.js").StoreDetail} StoreDetail */
/** @typedef {import("./types.js").ProductList} ProductList */
/** @typedef {import("./types.js").SlotFilters} SlotFilters */
/** @typedef {import("./types.js").CatalogPage} CatalogPage */
/** @typedef {import("./types.js").SlotCard} SlotCard */
/** @typedef {import("./types.js").VersionCard} VersionCard */
/** @typedef {import("./types.js").RequestFiles} RequestFiles */
/** @typedef {import("./types.js").FootprintFilters} FootprintFilters */
/** @typedef {import("./types.js").MapView} MapView */
/** @typedef {import("./types.js").SheetQuery} SheetQuery */
/** @typedef {import("./types.js").SheetList} SheetList */
/** @typedef {import("./types.js").ProjectList} ProjectList */
/** @typedef {import("./types.js").ProjectCard} ProjectCard */
/** @typedef {import("./types.js").ProjectStatus} ProjectStatus */
/** @typedef {import("./types.js").Settings} Settings */
/** @typedef {import("./types.js").ScanRequest} ScanRequest */
/** @typedef {import("./types.js").JobDetail} JobDetail */
/** @typedef {import("./types.js").JobFilters} JobFilters */
/** @typedef {import("./types.js").JobList} JobList */
/** @typedef {import("./types.js").JobHandlers} JobHandlers */
/** @typedef {import("./types.js").AreaInput} AreaInput */
/** @typedef {import("./types.js").Area} Area */
/** @typedef {import("./types.js").LocalCoverageQuery} LocalCoverageQuery */
/** @typedef {import("./types.js").AreaCoverage} AreaCoverage */
/** @typedef {import("./types.js").PreviewInfo} PreviewInfo */
/** @typedef {import("./types.js").LayersQuery} LayersQuery */
/** @typedef {import("./types.js").LayerSet} LayerSet */
/** @typedef {import("./types.js").Comparison} Comparison */
/** @typedef {import("./types.js").OwnFilesQuery} OwnFilesQuery */
/** @typedef {import("./types.js").OwnFileList} OwnFileList */
/** @typedef {import("./types.js").OwnFolder} OwnFolder */
/** @typedef {import("./types.js").OwnFileCard} OwnFileCard */
/** @typedef {import("./types.js").SnapshotPlan} SnapshotPlan */
/** @typedef {import("./types.js").AvailabilityQuery} AvailabilityQuery */
/** @typedef {import("./types.js").AvailabilityRequest} AvailabilityRequest */
/** @typedef {import("./types.js").AvailabilityInfo} AvailabilityInfo */
/** @typedef {import("./types.js").CommandCall} CommandCall */
/** @typedef {import("./types.js").JobRequest} JobRequest */
/** @typedef {import("./types.js").ActionPlanInfo} ActionPlanInfo */
/** @typedef {import("./types.js").ValidateRequest} ValidateRequest */
/** @typedef {import("./types.js").ProjectRequest} ProjectRequest */
/** @typedef {import("./types.js").TaskRequest} TaskRequest */
/** @typedef {import("./types.js").ProjectJobRequest} ProjectJobRequest */

/**
 * Abort a read: every function takes these options last.
 *
 * @typedef {{signal?: AbortSignal}} RequestOptions
 */

export const API_PREFIX = "/api/v1";
const CSRF_HEADER = "X-Archiwista-CSRF";
// The language of the texts the server makes for a request (AGI-6.4, AGI-9.2):
// the interface is Polish; the server answers in English without the header.
const LANGUAGE = "pl";
// `sessionStorage` key of the session's CSRF token (this origin, this tab).
export const TOKEN_KEY = "archiwista_csrf";
const CHANNEL = "archiwista-session";
// How long a tab without the token waits for an open tab to hand it over.
const HANDOFF_MS = 300;
// Pause before an event stream that broke off resumes.
const RESUME_MS = 1000;
const FINAL_JOB_STATES = new Set([
  "succeeded",
  "partial",
  "failed",
  "interrupted",
  "cancelled",
]);
const JSON_ANSWERS = "application/json, application/problem+json";
const IMAGE_ANSWERS = "image/png, application/problem+json";

/** @type {SessionState|null} */
let current = null;
/** @type {Set<(problem: Problem) => void>} */
const sessionLost = new Set();
/** @type {BroadcastChannel|null} */
const channel = typeof BroadcastChannel === "function" ? new BroadcastChannel(CHANNEL) : null;
channel?.addEventListener("message", ({ data }) => {
  if (current === null) return;
  if (data?.type === "ask") {
    const token = storedToken();
    if (token !== null) channel.postMessage({ type: "token", token });
  } else if (data?.type === "token" && typeof data.token === "string") {
    // Another tab started a session: the shared cookie is now that one's.
    sessionStorage.setItem(TOKEN_KEY, data.token);
  }
});

/** A problem answered by the API (RFC 9457), or no answer at all (`status` 0). */
export class ApiError extends Error {
  /**
   * @param {Problem} problem - The problem; `code` is stable, `detail` Polish.
   */
  constructor(problem) {
    super(problem.detail || problem.title);
    this.name = "ApiError";
    /** @type {number} */
    this.status = problem.status;
    /** @type {string} */
    this.code = problem.code;
    /** @type {Problem} */
    this.problem = problem;
  }
}

/**
 * Start the browser session: the token of `#token=…`, else the session cookie.
 *
 * @returns {Promise<SessionState>}
 * @throws {ApiError} `401 unauthorized` (reason `session_required`) without a
 *   usable token or session, `source_unavailable` (reason `network_error`)
 *   when the server does not answer.
 */
export async function startSession() {
  const token = takeFragmentToken();
  if (token !== null) {
    const started = await exchangeToken(token);
    sessionStorage.setItem(TOKEN_KEY, started.csrf_token);
    channel?.postMessage({ type: "token", token: started.csrf_token });
    current = started;
    return started;
  }
  const kept = storedToken() ?? (await askOpenTabs());
  if (kept === null) throw new ApiError(sessionMissingProblem());
  sessionStorage.setItem(TOKEN_KEY, kept);
  const state = await readSession();
  current = state;
  return state;
}

/**
 * The session started by `startSession`, or `null` before it and after a 401.
 *
 * @returns {SessionState|null}
 */
export function session() {
  return current;
}

/**
 * Listen for the end of the session: a `401` of a request after the start.
 *
 * @param {(problem: Problem) => void} listener
 * @returns {() => void} Stop listening.
 */
export function onSessionLost(listener) {
  sessionLost.add(listener);
  return () => sessionLost.delete(listener);
}

/**
 * The CSRF token of the session this tab keeps (`sessionStorage`).
 *
 * @returns {string|null}
 */
export function csrfToken() {
  return storedToken();
}

/**
 * Send a request to the API.
 *
 * @param {"GET"|"POST"|"PUT"|"PATCH"|"DELETE"} method
 * @param {string} path - Path below `/api/v1`, e.g. `/health`; segments already
 *   encoded.
 * @param {object} [options]
 * @param {Object<string, *>} [options.query] - Query parameters; `null`,
 *   `undefined` and `""` are left out, arrays repeat the name.
 * @param {*} [options.json] - Body sent as JSON.
 * @param {Blob|ArrayBuffer} [options.body] - Raw body (a file).
 * @param {string} [options.type] - Content type of a raw body.
 * @param {AbortSignal} [options.signal]
 * @returns {Promise<*>} The JSON answer, `null` for `204`.
 * @throws {ApiError} The server's problem; aborting rejects with `AbortError`.
 */
export async function request(method, path, { query, json, body, type, signal } = {}) {
  const headers = { Accept: JSON_ANSWERS };
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (body !== undefined) {
    headers["Content-Type"] = type ?? "application/octet-stream";
  }
  const response = await send(method, API_PREFIX + path + search(query), { headers, body, signal });
  return response.status === 204 ? null : response.json();
}

/**
 * An address the API gave in an answer (`thumbnail_url`, `members_url`…)
 * with documented query parameters added: the client never composes the
 * addresses of objects itself (plan v0.2, `PreviewInfo`).
 *
 * @param {string} address - The address from the answer, under `/api/v1/` of
 *   this server.
 * @param {Object<string, string|number|null|undefined>} [query] - E.g.
 *   `{style: "hillshade", size: 512}`; `null`, `undefined` and `""` are left out.
 * @returns {string} Path and query, e.g. `/api/v1/stores/…/preview.png?size=512`.
 * @throws {Error} Not an address of this server's API: the session's CSRF
 *   token goes nowhere else.
 */
export function apiAddress(address, query = {}) {
  const url = apiUrl(address);
  for (const [name, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== "") url.searchParams.set(name, String(value));
  }
  return url.pathname + url.search;
}

/**
 * A template the API gave in an answer (`tiles_url` with `{z}/{x}/{y}`,
 * `features_url` with `{bbox}` and `{zoom}`) with documented query
 * parameters added; its placeholders stay as they are for the map to fill.
 *
 * @param {string} template - From the answer, under `/api/v1/` of this server.
 * @param {Object<string, string|number|null|undefined>} [query] - E.g.
 *   `{style: "hypsometry"}`; `null`, `undefined` and `""` are left out.
 * @returns {string} The absolute address, e.g.
 *   `http://127.0.0.1:8765/api/v1/stores/…/tiles/{z}/{x}/{y}.png?style=hypsometry`.
 * @throws {Error} Not an address of this server's API.
 */
export function apiTemplate(template, query = {}) {
  apiUrl(template);
  const added = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== "") added.set(name, String(value));
  }
  // A URL object would encode the braces of the placeholders: the text is kept.
  const absolute = template.startsWith("/") ? location.origin + template : template;
  const text = added.toString();
  return text ? `${absolute}${absolute.includes("?") ? "&" : "?"}${text}` : absolute;
}

/**
 * The headers for a request the page does not send itself (MapLibre's tiles,
 * `transformRequest`): the session's CSRF header and the language, only for
 * an address of this server's API, never for a basemap or any other origin.
 *
 * @param {string} address - The address about to be requested.
 * @returns {Object<string, string>|null} The headers, or `null` to send none.
 */
export function apiHeaders(address) {
  const token = storedToken();
  return token !== null && isApiUrl(new URL(address, location.origin))
    ? { [CSRF_HEADER]: token, "Accept-Language": LANGUAGE }
    : null;
}

/**
 * An image of an address the API gave (`thumbnail_url` of `get_thumbnail`),
 * fetched with the session's CSRF header — which an `<img src>` cannot send;
 * show it through `URL.createObjectURL` (the CSP allows `blob:` images).
 *
 * @param {string} address - E.g. `apiAddress(info.thumbnail_url, {size: 512})`.
 * @param {RequestOptions} [options]
 * @returns {Promise<Blob>} The PNG; the browser's cache answers a repeated
 *   address (`Cache-Control: immutable`, `ETag`).
 * @throws {ApiError} E.g. `422 unsupported` (`details.preview_reason`), `429
 *   rate_limited`; aborting rejects with `AbortError`.
 */
export async function getImage(address, { signal } = {}) {
  const headers = { Accept: IMAGE_ANSWERS };
  const response = await send("GET", apiAddress(address), { headers, signal });
  return response.blob();
}

/**
 * The JSON answer of an address the API gave (`members_url` of `get_members`).
 *
 * @param {string} address
 * @param {RequestOptions} [options]
 * @returns {Promise<*>}
 * @throws {ApiError} The server's problem; aborting rejects with `AbortError`.
 */
export async function getLinked(address, { signal } = {}) {
  const headers = { Accept: JSON_ANSWERS };
  const response = await send("GET", apiAddress(address), { headers, signal });
  return response.json();
}

/**
 * Build the local preview of the object whose preview description is at an
 * address the API gave (`ComparisonSide.preview`): `POST` to that address,
 * as `buildPreview` does for a version.
 *
 * @param {string} address - A `…/preview` address of this server's API.
 * @param {{force?: boolean}} [options] - `force`: also past the auto-build
 *   limits (the „Zbuduj podgląd” button).
 * @returns {Promise<JobDetail|PreviewInfo>} `202` the job, `200` the
 *   `PreviewInfo` when nothing needs building (no `id`).
 * @throws {ApiError} `422 unsupported` (`details.preview_reason`), `429
 *   rate_limited`, `store_unavailable`.
 */
export async function buildLinked(address, { force = false } = {}) {
  const headers = { Accept: JSON_ANSWERS, "Content-Type": "application/json" };
  const response = await send("POST", apiAddress(address), { headers, body: JSON.stringify({ force }) });
  return response.json();
}

// Session (step 8) ------------------------------------------------------------

/**
 * Exchange a one-time token for a session (`exchange_token`); the answer
 * alone carries the session's CSRF token.
 *
 * @param {string} token - Value after `#token=`.
 * @returns {Promise<NewSession>}
 */
export function exchangeToken(token) {
  return request("POST", "/session", { json: { token } });
}

/**
 * The session: who acts, how, its label and end (`read_session`).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<SessionState>}
 */
export function readSession({ signal } = {}) {
  return request("GET", "/session", { signal });
}

/**
 * End the session at once and forget its token (`end_session`).
 *
 * @returns {Promise<null>}
 */
export async function endSession() {
  try {
    return await request("DELETE", "/session");
  } finally {
    sessionStorage.removeItem(TOKEN_KEY);
    current = null;
  }
}

/**
 * A one-time address for a next session, e.g. an agent's (`issue_token`).
 *
 * @returns {Promise<OneTimeToken>}
 */
export function issueToken() {
  return request("POST", "/session/tokens");
}

// Read API (9a) ---------------------------------------------------------------

/**
 * Versions, sources, the index and every store's state (`get_health`).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<Health>}
 */
export function getHealth({ signal } = {}) {
  return request("GET", "/health", { signal });
}

/**
 * Producer plugins with their states and fixes (`list_sources`).
 * Each item names the products whose availability at the source its
 * producer checks (`availability`).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<SourceList>}
 */
export function listSources({ signal } = {}) {
  return request("GET", "/sources", { signal });
}

/**
 * Configured stores with their index states (`list_stores`).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<StoreList>}
 */
export function listStores({ signal } = {}) {
  return request("GET", "/stores", { signal });
}

/**
 * A store's usage, clean-up report, projects and problems (`get_store`).
 *
 * @param {string} store - Store id.
 * @param {RequestOptions} [options]
 * @returns {Promise<StoreDetail>}
 */
export function getStore(store, { signal } = {}) {
  return request("GET", `/stores/${one(store)}`, { signal });
}

/**
 * Products found in the index (`list_products`).
 *
 * @param {{store?: string}} [filters]
 * @param {RequestOptions} [options]
 * @returns {Promise<ProductList>}
 */
export function listProducts(filters = {}, { signal } = {}) {
  return request("GET", "/products", { query: filters, signal });
}

/**
 * A page of the catalog or of a search (`list_slots`).
 *
 * @param {SlotFilters} [filters]
 * @param {RequestOptions} [options]
 * @returns {Promise<CatalogPage>}
 */
export function listSlots(filters = {}, { signal } = {}) {
  return request("GET", "/slots", { query: filters, signal });
}

/**
 * The file card of a slot (`get_slot`).
 *
 * @param {string} store - Store id.
 * @param {string} slot - Slot path in the store.
 * @param {RequestOptions} [options]
 * @returns {Promise<SlotCard>}
 */
export function getSlot(store, slot, { signal } = {}) {
  return request("GET", `/stores/${one(store)}/slots/${segments(slot)}`, { signal });
}

/**
 * Every indexed value of a version with its raw sidecar (`get_version`).
 *
 * @param {string} store - Store id.
 * @param {string} version - Version path in the store.
 * @param {RequestOptions} [options]
 * @returns {Promise<VersionCard>}
 */
export function getVersion(store, version, { signal } = {}) {
  return request("GET", `/stores/${one(store)}/versions/${segments(version)}`, {
    signal,
  });
}

/**
 * The raw sidecar of a version, exactly as stored (`get_sidecar`).
 *
 * @param {string} store - Store id.
 * @param {string} version - Version path in the store.
 * @param {RequestOptions} [options]
 * @returns {Promise<Object<string, *>>}
 */
export function getSidecar(store, version, { signal } = {}) {
  return request("GET", `/stores/${one(store)}/versions/${segments(version)}/sidecar`, {
    signal,
  });
}

/**
 * Files of one producer request (`list_request_files`).
 *
 * @param {string} parentRequest - The request key (`parent_request`).
 * @param {RequestOptions} [options]
 * @returns {Promise<RequestFiles>}
 */
export function listRequestFiles(parentRequest, { signal } = {}) {
  return request("GET", `/requests/${segments(parentRequest)}`, { signal });
}

/**
 * Outlines of a map view, or their grid above `limit` (`list_footprints`).
 *
 * @param {FootprintFilters} filters
 * @param {RequestOptions} [options]
 * @returns {Promise<MapView>}
 */
export function listFootprints(filters, { signal } = {}) {
  return request("GET", "/map/footprints", { query: filters, signal });
}

/**
 * Sheets of a sheet grid in a map view (`list_sheets`).
 *
 * @param {SheetQuery} query
 * @param {RequestOptions} [options]
 * @returns {Promise<SheetList>}
 */
export function listSheets(query, { signal } = {}) {
  return request("GET", "/map/sheets", { query, signal });
}

/**
 * Projects the session sees (`list_projects`).
 *
 * @param {{store?: string}} [filters]
 * @param {RequestOptions} [options]
 * @returns {Promise<ProjectList>}
 */
export function listProjects(filters = {}, { signal } = {}) {
  return request("GET", "/projects", { query: filters, signal });
}

/**
 * A project with its tasks, pins and problems (`get_project`).
 *
 * @param {string} project - Project id.
 * @param {RequestOptions} [options]
 * @returns {Promise<ProjectCard>}
 */
export function getProject(project, { signal } = {}) {
  return request("GET", `/projects/${one(project)}`, { signal });
}

/**
 * The producer's check of a project now (`get_project_status`).
 *
 * @param {string} project - Project id.
 * @param {RequestOptions} [options]
 * @returns {Promise<ProjectStatus>}
 */
export function getProjectStatus(project, { signal } = {}) {
  return request("GET", `/projects/${one(project)}/status`, { signal });
}

/**
 * Create a project of a producer bound to a configured store
 * (`create_project`): the producer writes its manifest; administrators only.
 *
 * @param {ProjectRequest} body
 * @returns {Promise<ProjectCard>} The new project's card (`201`).
 * @throws {ApiError} `403` (`permission_denied`, `path_outside_root`), `400`
 *   (`project_not_discoverable`, `project_dir_missing`, `store_without_producer`,
 *   the producer's refusal), `404` (a store that is not configured), `409`
 *   (`project_locked`), `422 unsupported`, `503 store_unavailable`.
 */
export function createProject(body) {
  return request("POST", "/projects", { json: body });
}

/**
 * Add a task to a project through its producer (`add_project_task`): checked
 * without the network, nothing is downloaded.
 *
 * @param {string} project - Project id.
 * @param {TaskRequest} body
 * @returns {Promise<ProjectCard>} The project's card with the task (`201`).
 * @throws {ApiError} `400` with the producer's text and `details.option` (an
 *   invalid or taken name, an invalid option), `403 permission_denied`, `404`,
 *   `409` (`project_locked`, `details.lock`).
 */
export function addProjectTask(project, body) {
  return request("POST", `/projects/${one(project)}/tasks`, { json: body });
}

/**
 * Remove a task and its pins from a project (`remove_project_task`); its
 * files stay in the store.
 *
 * @param {string} project - Project id.
 * @param {string} name - Task name.
 * @returns {Promise<ProjectCard>} The project's card without the task.
 * @throws {ApiError} `400` (the producer's refusal), `403 permission_denied`,
 *   `404`, `409` (`project_locked`, `details.lock`).
 */
export function removeProjectTask(project, name) {
  return request("DELETE", `/projects/${one(project)}/tasks/${one(name)}`);
}

/**
 * Start a job of a project's tasks (`start_project_job`): `download`,
 * `repin`, `check` or `verify`.
 *
 * @param {string} project - Project id.
 * @param {ProjectJobRequest} body
 * @returns {Promise<JobDetail>} The queued job (`202`).
 * @throws {ApiError} `403 permission_denied` (a download or a repin without
 *   `project_write` or `store_write`), `404`, `409 conflict` (`offline_mode`,
 *   `unknown_store`, another job of the project in `details.job`), `422
 *   unsupported`.
 */
export function startProjectJob(project, body) {
  return request("POST", `/projects/${one(project)}/jobs`, { json: body });
}

/**
 * The settings in effect (`get_settings`).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<Settings>}
 */
export function getSettings({ signal } = {}) {
  return request("GET", "/settings", { signal });
}

/**
 * Replace all settings (`put_settings`): send the whole object of
 * `getSettings` with the changes, since omitted fields take defaults.
 *
 * @param {Settings} settings
 * @returns {Promise<Settings>} The settings now in effect.
 * @throws {ApiError} `400 validation_error` (reason `invalid_settings`) with
 *   `details.problems` per field.
 */
export function putSettings(settings) {
  return request("PUT", "/settings", { json: settings });
}

// Background jobs (9b) --------------------------------------------------------

/**
 * Scan a store into the index (`start_scan`).
 *
 * @param {string} store - Store id.
 * @param {ScanRequest} [scan] - Default: incremental, every segment.
 * @returns {Promise<JobDetail>} The queued or running job (`202`).
 * @throws {ApiError} `409 conflict` with `job` while another index job runs.
 */
export function startScan(store, scan = {}) {
  return request("POST", `/stores/${one(store)}/scan`, { json: scan });
}

/**
 * Fetch the outlines of units the index has none for (`start_footprints`).
 *
 * @param {string} store - Store id.
 * @returns {Promise<JobDetail>}
 * @throws {ApiError} `409 conflict`: reason `offline_mode` in offline mode, or
 *   the job in the way (`details.job`).
 */
export function startFootprints(store) {
  return request("POST", `/stores/${one(store)}/footprints`);
}

/**
 * Confirm the current version of a slot by its content (`start_link_check`).
 *
 * @param {string} store - Store id.
 * @param {string} slot - Slot path in the store.
 * @returns {Promise<JobDetail>}
 */
export function startLinkCheck(store, slot) {
  return request("POST", `/stores/${one(store)}/link-check`, { json: { slot } });
}

/**
 * Background jobs, newest first (`list_jobs`).
 *
 * @param {JobFilters} [filters]
 * @param {RequestOptions} [options]
 * @returns {Promise<JobList>}
 */
export function listJobs(filters = {}, { signal } = {}) {
  return request("GET", "/jobs", { query: filters, signal });
}

/**
 * One background job (`get_job`).
 *
 * @param {string} job - Job id.
 * @param {RequestOptions} [options]
 * @returns {Promise<JobDetail>}
 */
export function getJob(job, { signal } = {}) {
  return request("GET", `/jobs/${one(job)}`, { signal });
}

/**
 * Follow a job's events (`get_job_events`, server-sent events read with
 * `fetch`, which sends the session's CSRF token): every event since the
 * start, then new ones until a final state ends the stream. A stream that
 * breaks off resumes after the last event (`Last-Event-ID`); an error answer
 * stops following with `onError`.
 *
 * @param {string} job - Job id.
 * @param {JobHandlers} handlers
 * @returns {() => void} Stop following.
 */
export function watchJob(job, { onProgress, onNotice, onState, onError } = {}) {
  const handlers = { progress: onProgress, notice: onNotice, state: onState };
  const controller = new AbortController();
  let last = null;
  let ended = false;
  const follow = async () => {
    while (!ended) {
      const headers = { Accept: "text/event-stream", "Accept-Language": LANGUAGE };
      const token = storedToken();
      if (token !== null) headers[CSRF_HEADER] = token;
      if (last !== null) headers["Last-Event-ID"] = last;
      let response;
      try {
        response = await fetch(`${API_PREFIX}/jobs/${one(job)}/events`, {
          headers,
          signal: controller.signal,
          credentials: "same-origin",
          cache: "no-store",
        });
      } catch {
        await pause(RESUME_MS, controller.signal);
        continue;
      }
      if (response.status === 204) return;
      if (!response.ok) {
        ended = true;
        onError?.(
          pageProblem("source_unavailable", "stream_closed", {
            title: T.common.problem.http_title,
            status: response.status,
            detail: t(T.common.problem.stream, { job }),
          }),
        );
        return;
      }
      try {
        for await (const message of eventMessages(response.body)) {
          if (message.id !== null) last = message.id;
          const data = JSON.parse(message.data);
          if (message.event === "state" && FINAL_JOB_STATES.has(data.state)) ended = true;
          handlers[message.event]?.(data);
          if (ended) return;
        }
      } catch {
        // The connection broke off: resume below.
      }
      await pause(RESUME_MS, controller.signal);
    }
  };
  follow().finally(() => controller.abort());
  return () => {
    ended = true;
    controller.abort();
  };
}

// Areas and local coverage (9c) -----------------------------------------------

/**
 * Keep a drawn, view or sheet area (`create_area`, GeoJSON body).
 *
 * @param {AreaInput} input
 * @returns {Promise<Area>} The area (`201`); the same geometry, the same id.
 */
export function createArea(input) {
  return request("POST", "/areas", { json: input });
}

/**
 * Keep the area of a geometry file: GeoJSON, GeoPackage or a zipped
 * Shapefile (`create_area`, raw body).
 *
 * @param {Blob} file - The file as the user chose it.
 * @param {{name?: string, layer?: string}} [options] - Display name (e.g. the
 *   file name) and the layer when the file has several.
 * @returns {Promise<Area>}
 * @throws {ApiError} `400 validation_error` (reason `area_too_large` or
 *   `area_too_complex`), `500 data_error` (reason `area_unreadable`; the file's
 *   layers in `details.layers`).
 */
export function uploadArea(file, { name, layer } = {}) {
  return request("POST", "/areas", {
    body: file,
    type: "application/octet-stream",
    query: { name, layer },
  });
}

/**
 * An area kept by the server (`get_area`).
 *
 * @param {string} area - Area id.
 * @param {RequestOptions} [options]
 * @returns {Promise<Area>}
 */
export function getArea(area, { signal } = {}) {
  return request("GET", `/areas/${one(area)}`, { signal });
}

/**
 * How much of an area the local current versions of a product cover
 * (`get_local_coverage`).
 *
 * @param {LocalCoverageQuery} query
 * @param {RequestOptions} [options]
 * @returns {Promise<AreaCoverage>}
 */
export function getLocalCoverage(query, { signal } = {}) {
  return request("GET", "/local-coverage", { query, signal });
}

// Local layers (v0.2, step 11) ------------------------------------------------

/**
 * The layers of a store's product (`get_local_layers`): its data years,
 * editions or labels, newest first; with an area their local coverage,
 * versions, outlines and the addresses of their thumbnail and map tiles.
 *
 * @param {LayersQuery} query
 * @param {RequestOptions} [options]
 * @returns {Promise<LayerSet>}
 */
export function getLocalLayers(query, { signal } = {}) {
  return request("GET", "/local-layers", { query, signal });
}

// Comparison (v0.2, step 10) --------------------------------------------------

/**
 * The metadata of two objects side by side (`get_comparison`): both sides
 * (title, preview address, outline), whether their content is the same and
 * one row per field with the values of A and B, marked when they differ.
 *
 * @param {string} a - `ref` of side A, copied from an answer.
 * @param {string} b - `ref` of side B.
 * @param {RequestOptions} [options]
 * @returns {Promise<Comparison>}
 * @throws {ApiError} `400 validation_error` (reason `invalid_ref`: malformed,
 *   or a kind not compared yet), `404 not_found`.
 */
export function getComparison(a, b, { signal } = {}) {
  return request("GET", "/compare", { query: { a, b }, signal });
}

// Previews (v0.2, step 6) -----------------------------------------------------

/**
 * The preview of a version: its state, why something is missing, styles,
 * legends and the addresses of its images (`get_preview`).
 *
 * @param {string} store - Store id.
 * @param {string} version - Version path in the store.
 * @param {RequestOptions} [options]
 * @returns {Promise<PreviewInfo>}
 */
export function getPreview(store, version, { signal } = {}) {
  return request("GET", `/stores/${one(store)}/versions/${segments(version)}/preview`, {
    signal,
  });
}

/**
 * Build the local preview of a version (`build_preview`): the `preview` job
 * building it (a new one, or the one building the same content already).
 *
 * @param {string} store - Store id.
 * @param {string} version - Version path in the store.
 * @param {{force?: boolean}} [options] - `force`: also past the auto-build
 *   limits (the „Zbuduj podgląd” button).
 * @returns {Promise<JobDetail|PreviewInfo>} `202` the job, `200` the
 *   `PreviewInfo` when nothing needs building (no `id`).
 * @throws {ApiError} `422 unsupported` (`details.preview_reason`; `too_large`
 *   without `force`), `429 rate_limited`, `store_unavailable`.
 */
export function buildPreview(store, version, { force = false } = {}) {
  return request("POST", `/stores/${one(store)}/versions/${segments(version)}/preview`, {
    json: { force },
  });
}

// Own data and snapshots (v0.2, step 9) ---------------------------------------

/**
 * A project's data folder and its files by path (`list_own_files`): the
 * folder's state, counts and problems, each file with its change since its
 * last snapshot and its WGS84 outline. A folder never scanned has
 * `scanned_at: null` and no files.
 *
 * @param {string} project - Project id (`project` of /projects).
 * @param {OwnFilesQuery} [query] - `q`, `state`, `limit` (1–200), `cursor`.
 * @param {RequestOptions} [options]
 * @returns {Promise<OwnFileList>}
 * @throws {ApiError} `404 not_found` (unknown, or not visible), `400
 *   validation_error`.
 */
export function listOwnFiles(project, query = {}, { signal } = {}) {
  return request("GET", `/projects/${one(project)}/files`, { query, signal });
}

/**
 * Scan the project's data folder in the background (`start_project_scan`,
 * „Odśwież”): an `own_scan` job, or the waiting one covering the folder.
 *
 * @param {string} project
 * @returns {Promise<JobDetail>}
 */
export function startProjectScan(project) {
  return request("POST", `/projects/${one(project)}/scan`);
}

/**
 * Give a project another data folder, or its default `dane/` again
 * (`put_data_dir`, administrators); its scan starts at once.
 *
 * @param {string} project
 * @param {string|null} path - Absolute folder on the server's computer;
 *   `null` brings back the default.
 * @returns {Promise<OwnFolder>}
 * @throws {ApiError} `403 forbidden` (reason `permission_denied`), `400
 *   validation_error` with `details.problems` (the folder breaks a rule).
 */
export function putDataDir(project, path) {
  return request("PUT", `/projects/${one(project)}/data-dir`, { json: { path } });
}

/**
 * Everything known of an own file (`get_own_file`): layers, extent, history,
 * snapshots newest first and the working file's preview.
 *
 * @param {string} project
 * @param {string} fileId - `file_id` of the file list (16 hex characters).
 * @param {RequestOptions} [options]
 * @returns {Promise<OwnFileCard>}
 */
export function getOwnFile(project, fileId, { signal } = {}) {
  return request("GET", `/projects/${one(project)}/files/${one(fileId)}`, { signal });
}

/**
 * The layers of an own file for the Wachlarz (`get_own_file_layers`): the
 * working file on top, then its snapshots newest first.
 *
 * @param {string} project
 * @param {string} fileId
 * @param {RequestOptions} [options]
 * @returns {Promise<LayerSet>}
 */
export function getOwnFileLayers(project, fileId, { signal } = {}) {
  return request("GET", `/projects/${one(project)}/files/${one(fileId)}/layers`, { signal });
}

/**
 * What a snapshot of a file would do now (`get_snapshot_plan`): nothing is
 * written.
 *
 * @param {string} project
 * @param {string} fileId
 * @param {RequestOptions} [options]
 * @returns {Promise<SnapshotPlan>}
 */
export function getSnapshotPlan(project, fileId, { signal } = {}) {
  return request("GET", `/projects/${one(project)}/files/${one(fileId)}/snapshot-plan`, { signal });
}

/**
 * Snapshot a file into `.wersje/` (`start_file_snapshot`): the `snapshot`
 * job, for the project's owner or an administrator.
 *
 * @param {string} project
 * @param {string} fileId
 * @param {string} note - The person's note kept in `migawka.json` (≤ 2000).
 * @returns {Promise<JobDetail>}
 * @throws {ApiError} `403 forbidden` (reason `permission_denied`), `409
 *   conflict` with the reason `snapshot_blocked` (`details.blocked_by`), or
 *   while a snapshot of the file runs (`details.job`).
 */
export function startFileSnapshot(project, fileId, note) {
  return request("POST", `/projects/${one(project)}/files/${one(fileId)}/snapshots`, {
    json: { note },
  });
}

/**
 * The preview of an own file (`get_own_preview`) or of one of its snapshots
 * (`get_snapshot_preview`), as of a version.
 *
 * @param {string} project
 * @param {string} fileId
 * @param {string|null} label - A snapshot's label; `null`: the working file.
 * @param {RequestOptions} [options]
 * @returns {Promise<PreviewInfo>}
 */
export function getOwnPreview(project, fileId, label, { signal } = {}) {
  return request("GET", ownPreviewPath(project, fileId, label), { signal });
}

/**
 * Build the local preview of an own file or snapshot (`build_own_preview`,
 * `build_snapshot_preview`), as `buildPreview` does for a version.
 *
 * @param {string} project
 * @param {string} fileId
 * @param {string|null} label - A snapshot's label; `null`: the working file.
 * @param {{force?: boolean}} [options]
 * @returns {Promise<JobDetail|PreviewInfo>}
 * @throws {ApiError} `409 conflict` (reason `own_file_changed`: scan the folder
 *   again), `422 unsupported` (`details.preview_reason`), `429 rate_limited`.
 */
export function buildOwnPreview(project, fileId, label, { force = false } = {}) {
  return request("POST", ownPreviewPath(project, fileId, label), { json: { force } });
}

function ownPreviewPath(project, fileId, label) {
  const file = `/projects/${one(project)}/files/${one(fileId)}`;
  return label === null ? `${file}/preview` : `${file}/snapshots/${one(label)}/preview`;
}

// The source and producers' commands (v0.3) ------------------------------------

/**
 * The last report of what the source has for an area and a product, with
 * its rows (`get_availability`): from the index, never from the network.
 *
 * @param {AvailabilityQuery} query - `area_id`, `product`, `producer`; `store`
 *   gives each variant its store badge.
 * @param {RequestOptions} [options]
 * @returns {Promise<AvailabilityInfo>}
 * @throws {ApiError} `404 not_found`: no report of the area and the product
 *   (also an unknown area or a store that is not configured).
 */
export function getAvailability(query, { signal } = {}) {
  return request("GET", "/availability", { query, signal });
}

/**
 * Ask what the source has for an area and a product (`check_availability`).
 *
 * @param {AvailabilityRequest} body - `force`: ask the source even when a
 *   report younger than seven days is kept („Sprawdź ponownie”).
 * @returns {Promise<JobDetail|AvailabilityInfo>} `202` the `availability`
 *   job, `200` the kept report when it is younger than seven days (no `id`).
 * @throws {ApiError} `409 conflict` (reason `offline_mode`), `422 unsupported`
 *   (`no_availability`), `503 source_unavailable`.
 */
export function checkAvailability(body) {
  return request("POST", "/availability", { json: body });
}

/**
 * Read a producer's command line into a call (`parse_command`), e.g. a line
 * of a variant's `commands`; nothing is checked against the source.
 *
 * @param {string} producer - Producer id.
 * @param {string} line - The line without the program name.
 * @returns {Promise<CommandCall>}
 * @throws {ApiError} `400 validation_error` with the producer's text and
 *   `details.option`.
 */
export function parseCommand(producer, line) {
  return request("POST", "/commands/parse", { json: { producer, line } });
}

/**
 * Check a call without the network (`validate_command`), a command that
 * works on a store with that store's directory of the producer.
 *
 * @param {ValidateRequest} body
 * @returns {Promise<CommandCall>} The call as the producer reads it.
 * @throws {ApiError} `400 validation_error` with the producer's text and
 *   `details.option`, `403` (`path_outside_root`: an option that is a file
 *   path), `404` (a store that is not configured).
 */
export function validateCommand(body) {
  return request("POST", "/commands/validate", { json: body });
}

/**
 * Start a job of a producer's command on a configured store (`start_job`):
 * `check` plans a run without its effects, `download` runs it (with
 * `plan_job`, the plan that check kept).
 *
 * @param {JobRequest} body
 * @returns {Promise<JobDetail>} The queued job (`202`).
 * @throws {ApiError} `403 permission_denied` (a download without
 *   `store_write`), `400` (`store_without_producer`, the producer's refusal
 *   of an option), `404`, `409 conflict` (`offline_mode`, `plan_mismatch`).
 */
export function startJob(body) {
  return request("POST", "/jobs", { json: body });
}

/**
 * The plan a `check` job kept (`get_job_plan`): its counts, size and
 * positions, from the index.
 *
 * @param {string} job - Job id of a `check` that succeeded or ended `partial`.
 * @param {RequestOptions} [options]
 * @returns {Promise<ActionPlanInfo>}
 * @throws {ApiError} `404 not_found` (no plan kept, or a job the session does
 *   not see).
 */
export function getJobPlan(job, { signal } = {}) {
  return request("GET", `/jobs/${one(job)}/plan`, { signal });
}

// Helpers ---------------------------------------------------------------------

/** The CSRF token this tab keeps, or `null`. */
function storedToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

/** Whether a parsed address is under `/api/v1/` of this origin. */
function isApiUrl(url) {
  return url.origin === location.origin && url.pathname.startsWith(`${API_PREFIX}/`);
}

/** An address of this server's API as a URL; any other address throws. */
function apiUrl(address) {
  const url = new URL(address, location.origin);
  if (!isApiUrl(url)) throw new Error(`Not an address of the Archiwista API: ${address}`);
  return url;
}

/**
 * Send a request with the session's CSRF token; answer the response, or
 * throw the server's problem (a lost session told to the listeners first).
 */
async function send(method, address, { headers, body, signal }) {
  const token = storedToken();
  if (token !== null) headers[CSRF_HEADER] = token;
  headers["Accept-Language"] = LANGUAGE;
  let response;
  try {
    response = await fetch(address, { method, headers, body, signal, credentials: "same-origin" });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new ApiError(networkProblem());
  }
  if (response.ok) return response;
  const problem = await readProblem(response);
  if ((problem.status === 401 || problem.details?.reason === "csrf_rejected") && current !== null) {
    current = null;
    sessionStorage.removeItem(TOKEN_KEY);
    for (const listener of [...sessionLost]) listener(problem);
  }
  throw new ApiError(problem);
}

/** Ask the open tabs of this origin for the session's token (or `null`). */
function askOpenTabs() {
  if (channel === null) return Promise.resolve(null);
  return new Promise((resolve) => {
    const answer = ({ data }) => {
      if (data?.type === "token" && typeof data.token === "string") done(data.token);
    };
    const done = (token) => {
      clearTimeout(timer);
      channel.removeEventListener("message", answer);
      resolve(token);
    };
    const timer = setTimeout(() => done(null), HANDOFF_MS);
    channel.addEventListener("message", answer);
    channel.postMessage({ type: "ask" });
  });
}

/**
 * Messages of a server-sent event stream: `{id, event, data}` per message.
 *
 * @param {ReadableStream<Uint8Array>} body
 */
async function* eventMessages(body) {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let message = { id: null, event: "message", data: null };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    let end;
    while ((end = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, end).replace(/\r$/, "");
      buffer = buffer.slice(end + 1);
      if (line === "") {
        if (message.data !== null) yield message;
        message = { id: null, event: "message", data: null };
      } else if (!line.startsWith(":")) {
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        const text = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "id") message.id = text;
        else if (field === "event") message.event = text;
        else if (field === "data") message.data = message.data === null ? text : `${message.data}\n${text}`;
      }
    }
  }
}

/** Wait `ms`, or less when `signal` aborts. */
function pause(ms, signal) {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

function sessionMissingProblem() {
  return pageProblem("unauthorized", "session_required", {
    title: T.common.problem.http_title,
    status: 401,
    detail: T.common.problem.session_missing,
  });
}

/** Remove `token=…` from the fragment and return it (or `null`). */
function takeFragmentToken() {
  const fragment = new URLSearchParams(location.hash.slice(1));
  const token = fragment.get("token");
  if (token === null) return null;
  fragment.delete("token");
  const rest = fragment.toString();
  const address = location.pathname + location.search + (rest ? `#${rest}` : "");
  history.replaceState(history.state, "", address);
  return token;
}

function search(query) {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== null && item !== undefined && item !== "") params.append(name, item);
    }
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

function one(value) {
  return encodeURIComponent(value);
}

function segments(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

/**
 * The problem of a server that does not answer (`status` 0): the registry's
 * `source_unavailable`, the page's own reason `network_error`.
 *
 * @returns {Problem}
 */
export function networkProblem() {
  return pageProblem("source_unavailable", "network_error", {
    title: T.common.problem.network_title,
    status: 0,
    detail: T.common.problem.network,
  });
}

/**
 * A problem the page makes itself when the server's answer is none of the
 * API's: a registry code with the page's own reason, as the server would give.
 *
 * @param {string} code - Registry code.
 * @param {string} reason - `details.reason`.
 * @param {{title: string, status: number, detail: string}} text - Polish title
 *   and description, and the HTTP status.
 * @returns {Problem}
 */
function pageProblem(code, reason, { title, status, detail }) {
  return { type: "about:blank", title, status, detail, code, details: { reason } };
}

async function readProblem(response) {
  if ((response.headers.get("Content-Type") ?? "").includes("json")) {
    try {
      const body = await response.json();
      if (body && typeof body.code === "string") {
        return { ...body, status: body.status ?? response.status };
      }
    } catch {
      // Not JSON after all: described below by its status.
    }
  }
  return pageProblem("source_unavailable", "http_error", {
    title: T.common.problem.http_title,
    status: response.status,
    detail: t(T.common.problem.http, { status: response.status }),
  });
}
