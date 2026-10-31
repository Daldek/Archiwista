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
 * browsers also send to other ports of the host. On a team server
 * (ADR-046) `signIn` (an account and its password), `proxySignIn` (the
 * company's reverse proxy) and `changePassword` start a session the same
 * way. A tab without the token (a new one, a link opened in another tab)
 * asks the open tabs of this origin for it (`BroadcastChannel`); a tab
 * starting a new session tells them its token, since they share its cookie.
 * Job events stream through `fetch`, which can send the header
 * (`EventSource` cannot), resuming after `Last-Event-ID`. Errors are RFC 9457
 * problems thrown as `ApiError`: `code` is a code of the Nogat error
 * registry, `details.reason` the project's own cause; a `401`, or a `403` with
 * the reason `csrf_rejected`, of any request after the start goes to the
 * `onSessionLost` listeners, so the shell can say how to open a new session.
 */

import { T, t } from "./labels/index.js";

/** @typedef {import("./types.js").Problem} Problem */
/** @typedef {import("./types.js").SessionState} SessionState */
/** @typedef {import("./types.js").NewSession} NewSession */
/** @typedef {import("./types.js").SessionMethods} SessionMethods */
/** @typedef {import("./types.js").OneTimeToken} OneTimeToken */
/** @typedef {import("./types.js").SessionList} SessionList */
/** @typedef {import("./types.js").User} User */
/** @typedef {import("./types.js").UserList} UserList */
/** @typedef {import("./types.js").TemporaryPassword} TemporaryPassword */
/** @typedef {import("./types.js").Group} Group */
/** @typedef {import("./types.js").GroupList} GroupList */
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
/** @typedef {import("./types.js").StationDatasets} StationDatasets */
/** @typedef {import("./types.js").StationListFilters} StationListFilters */
/** @typedef {import("./types.js").StationList} StationList */
/** @typedef {import("./types.js").StationTimelinePage} StationTimelinePage */
/** @typedef {import("./types.js").StationMapFilters} StationMapFilters */
/** @typedef {import("./types.js").StationMapView} StationMapView */
/** @typedef {import("./types.js").StationLookup} StationLookup */
/** @typedef {import("./types.js").StationCard} StationCard */
/** @typedef {import("./types.js").StationChartQuery} StationChartQuery */
/** @typedef {import("./types.js").StationChart} StationChart */
/** @typedef {import("./types.js").StationCompareQuery} StationCompareQuery */
/** @typedef {import("./types.js").StationComparison} StationComparison */
/** @typedef {import("./types.js").ProjectList} ProjectList */
/** @typedef {import("./types.js").ProjectCard} ProjectCard */
/** @typedef {import("./types.js").ProjectChange} ProjectChange */
/** @typedef {import("./types.js").Settings} Settings */
/** @typedef {import("./types.js").Preferences} Preferences */
/** @typedef {import("./types.js").ScanRequest} ScanRequest */
/** @typedef {import("./types.js").JobDetail} JobDetail */
/** @typedef {import("./types.js").JobFilters} JobFilters */
/** @typedef {import("./types.js").JobList} JobList */
/** @typedef {import("./types.js").JobLog} JobLog */
/** @typedef {import("./types.js").JobHandlers} JobHandlers */
/** @typedef {import("./types.js").ActionFilters} ActionFilters */
/** @typedef {import("./types.js").ActionPage} ActionPage */
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
/** @typedef {import("./types.js").ExportRequest} ExportRequest */
/** @typedef {import("./types.js").ProjectJobRequest} ProjectJobRequest */
/** @typedef {import("./types.js").ProjectExport} ProjectExport */
/** @typedef {import("./types.js").ProjectExports} ProjectExports */
/** @typedef {import("./types.js").PinsRequest} PinsRequest */
/** @typedef {import("./types.js").GroupRequest} GroupRequest */
/** @typedef {import("./types.js").PinOutcome} PinOutcome */

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
// Media types of the formats of the log's export (`GET /log/export`).
const EXPORT_TYPES = { jsonl: "application/jsonl", csv: "text/csv" };

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
  if (token !== null) return keepSession(await exchangeToken(token));
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
 * How a session starts on this server (`session_methods`; needs no session).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<SessionMethods>}
 */
export function sessionMethods({ signal } = {}) {
  return request("GET", "/session/methods", { signal });
}

/**
 * Sign in to a team server with an account and its password (`sign_in`).
 *
 * @param {string} account
 * @param {string} password
 * @returns {Promise<NewSession>} The session this tab now keeps.
 * @throws {ApiError} `401 unauthorized` (`login_failed` for every refused
 *   account, `password_expired`), `429 rate_limited` (`login_blocked`, the
 *   wait in `details.retry_after_s`).
 */
export async function signIn(account, password) {
  return keepSession(await request("POST", "/session/login", { json: { account, password } }));
}

/**
 * Sign in as the person the company's reverse proxy names (`proxy_sign_in`).
 *
 * @returns {Promise<NewSession>} The session this tab now keeps.
 * @throws {ApiError} `401 unauthorized` (`login_failed`).
 */
export async function proxySignIn() {
  return keepSession(await request("POST", "/session/proxy"));
}

/**
 * Change the session's password (`change_password`): every session of the
 * account ends, and the new session of the answer is kept by this tab and
 * told to the other tabs.
 *
 * @param {string} currentPassword
 * @param {string} newPassword
 * @returns {Promise<NewSession>}
 * @throws {ApiError} `400 validation_error` (`password_policy`,
 *   `details.rule`), `403 forbidden` (`wrong_password`), `429 rate_limited`
 *   (`login_blocked`).
 */
export async function changePassword(currentPassword, newPassword) {
  const json = { current_password: currentPassword, new_password: newPassword };
  return keepSession(await request("PUT", "/session/password", { json }));
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

/**
 * The live sessions of the session's person, their agents' too, oldest
 * first (`list_sessions`).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<SessionList>}
 */
export function listSessions({ signal } = {}) {
  return request("GET", "/sessions", { signal });
}

/**
 * End one of the person's sessions at once (`end_session_label`).
 *
 * @param {string} label
 * @returns {Promise<null>}
 * @throws {ApiError} `404 not_found`: no live session of the person has it.
 */
export function endSessionLabel(label) {
  return request("DELETE", `/sessions/${one(label)}`);
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
 * The datasets with station series in the index (`list_station_datasets`):
 * the dataset chips and the „Kolor punktów” variables of the map.
 *
 * @param {{store?: string}} [query]
 * @param {RequestOptions} [options]
 * @returns {Promise<StationDatasets>}
 * @throws {ApiError} `503 missing_dependency` without IMGWTools.
 */
export function listStationDatasets(query = {}, { signal } = {}) {
  return request("GET", "/stations/datasets", { query, signal });
}

/**
 * A page of stations with the coverage of their series (`list_stations`):
 * along rivers by default (`sort`), the counts of the whole result by location.
 *
 * @param {StationListFilters} filters
 * @param {RequestOptions} [options]
 * @returns {Promise<StationList>}
 * @throws {ApiError} `400` (a coverage filter without `dataset`, a cursor of
 *   another query), `503 missing_dependency` without IMGWTools.
 */
export function listStations(filters, { signal } = {}) {
  return request("GET", "/stations", { query: filters, signal });
}

/**
 * A page of the stations of one dataset, each with its years
 * (`list_stations_timeline`): the Timeline tab of the Catalog. The filters,
 * order and cursor are those of `listStations`, `dataset` required.
 *
 * @param {StationListFilters} filters
 * @param {RequestOptions} [options]
 * @returns {Promise<StationTimelinePage>}
 * @throws {ApiError} `400` (no `dataset`, a cursor of another query),
 *   `503 missing_dependency` without IMGWTools.
 */
export function listStationTimeline(filters, { signal } = {}) {
  return request("GET", "/stations/timeline", { query: filters, signal });
}

/**
 * The located stations of a map view, or their grid above `limit`
 * (`list_map_stations`).
 *
 * @param {StationMapFilters} filters
 * @param {RequestOptions} [options]
 * @returns {Promise<StationMapView>}
 * @throws {ApiError} `503 missing_dependency` without IMGWTools.
 */
export function listMapStations(filters, { signal } = {}) {
  return request("GET", "/map/stations", { query: filters, signal });
}

/**
 * A station's card (`get_station`): its catalog entry, each series labelled
 * and the paths of its series files.
 *
 * @param {string} code - The station's code as its provider gives it.
 * @param {StationLookup} lookup - `store` and `provider` name the station.
 * @param {RequestOptions} [options]
 * @returns {Promise<StationCard>}
 * @throws {ApiError} `404` (no such station), `400 ambiguous_station`,
 *   `503 missing_dependency` without IMGWTools.
 */
export function getStation(code, lookup, { signal } = {}) {
  return request("GET", `/stations/${one(code)}`, { query: lookup, signal });
}

/**
 * One or two variables of a station's series as a chart (`get_station_series`):
 * each unit's value up to `max_points` units, else the least, mean and greatest
 * value of each interval, with the gaps of each variable's label and the markers.
 *
 * @param {string} code - The station's code as its provider gives it.
 * @param {StationChartQuery} query - `store` and `provider` name the station.
 * @param {RequestOptions} [options]
 * @returns {Promise<StationChart>}
 * @throws {ApiError} `404` (no such station or series), `400` (a variable the
 *   series lacks, a reversed range), `503 missing_dependency` without IMGWTools.
 */
export function getStationSeries(code, query, { signal } = {}) {
  return request("GET", `/stations/${one(code)}/series`, { query, signal });
}

/**
 * One variable of 2 to 5 stations over one range (`compare_stations`): each
 * station's chart with the same interval, the variable's label and facts as on
 * its card; `null` for a station without the series or the variable.
 *
 * @param {StationCompareQuery} query - `station` repeated, `<store>/<provider>/<code>`.
 * @param {RequestOptions} [options]
 * @returns {Promise<StationComparison>}
 * @throws {ApiError} `400` (one or more than five stations, a variable no
 *   station has, a reversed range), `404` (no such station, none with a series
 *   of the dataset), `503 missing_dependency` without IMGWTools.
 */
export function compareStations(query, { signal } = {}) {
  return request("GET", "/stations/compare", { query, signal });
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
 * A project with its stores, area, groups of pins and problems (`get_project`).
 *
 * @param {string} project - Project id.
 * @param {RequestOptions} [options]
 * @returns {Promise<ProjectCard>}
 */
export function getProject(project, { signal } = {}) {
  return request("GET", `/projects/${one(project)}`, { signal });
}

/**
 * Create a project (`create_project`): Archiwista writes its file
 * `archiwista-project.json` in the directory, made when missing, and the
 * person who asked owns the project.
 *
 * @param {ProjectRequest} body
 * @returns {Promise<ProjectCard>} The new project's card (`201`).
 * @throws {ApiError} `403` (`permission_denied`: a project of an access entry
 *   the session may not change; `path_outside_root`), `400`
 *   (`project_not_discoverable`, `project_dir_missing`), `404` (an unknown
 *   area), `409` (`project_exists`, `project_locked`), `422` (a name or
 *   description out of its rules), `500 io_error` (`project_file_write_failed`).
 */
export function createProject(body) {
  return request("POST", "/projects", { json: body });
}

/**
 * Change a project's name or description (`update_project`).
 *
 * @param {string} project - Project id.
 * @param {ProjectChange} body
 * @returns {Promise<ProjectCard>} The changed card.
 * @throws {ApiError} `403 permission_denied`, `404`, `409` (`project_locked`,
 *   `invalid_project_file`, `unsupported_project_schema`), `422`, `500 io_error`.
 */
export function updateProject(project, body) {
  return request("PATCH", `/projects/${one(project)}`, { json: body });
}

/**
 * Give a project an area of `/areas`, or clear it (`set_project_area`).
 *
 * @param {string} project - Project id.
 * @param {string|null} areaId - The area; `null` clears the project's area.
 * @returns {Promise<ProjectCard>} The changed card.
 * @throws {ApiError} As `updateProject`, and `404` for an unknown area.
 */
export function setProjectArea(project, areaId) {
  return request("PUT", `/projects/${one(project)}/area`, { json: { area_id: areaId } });
}

/**
 * The store of a producer's pins in a project (`set_project_store`).
 *
 * @param {string} project - Project id.
 * @param {string} producer - The producer whose store it is.
 * @param {string} store - Id of a configured store with the producer's directory.
 * @returns {Promise<ProjectCard>} The changed card.
 * @throws {ApiError} As `updateProject`, `400 store_without_producer` and `404`
 *   for a store that is not configured.
 */
export function setProjectStore(project, producer, store) {
  return request("PUT", `/projects/${one(project)}/stores/${one(producer)}`, { json: { store } });
}

/**
 * A new local group of a project with the versions the store holds
 * (`add_project_group`, A-ADR-049 decision 8): the versions named, or the
 * rows of a `GET /slots` query on every page.
 *
 * @param {string} project - Project id.
 * @param {GroupRequest} body
 * @returns {Promise<PinOutcome>} What was pinned, with the card after it (`201`).
 * @throws {ApiError} `403 permission_denied`, `404` (an unknown project),
 *   `400` (`invalid_group_name`, `too_many_pins` with `details.count`), `409`
 *   (`group_exists`, `other_store`, `unknown_store`, `project_locked`), `422`.
 */
export function addProjectGroup(project, body) {
  return request("POST", `/projects/${one(project)}/groups`, { json: body });
}

/**
 * More versions the store holds in a local group (`add_group_pins`).
 *
 * @param {string} project - Project id.
 * @param {string} group - The group's name.
 * @param {PinsRequest} body
 * @returns {Promise<PinOutcome>}
 * @throws {ApiError} As `addProjectGroup`; `404` for an unknown group and `409
 *   group_origin_plan` for a group of the plan window.
 */
export function addGroupPins(project, group, body) {
  return request("POST", `/projects/${one(project)}/groups/${one(group)}/pins`, { json: body });
}

/**
 * Take pins out of a group (`unpin_group_pins`); the group stays.
 *
 * @param {string} project - Project id.
 * @param {string} group - The group's name.
 * @param {Array<{producer: string, version: string}>} pins
 * @returns {Promise<ProjectCard>} The changed card.
 * @throws {ApiError} `403 permission_denied`, `404` (an unknown project or
 *   group), `409 project_locked`.
 */
export function unpinGroupPins(project, group, pins) {
  return request("POST", `/projects/${one(project)}/groups/${one(group)}/unpin`, {
    json: { pins },
  });
}

/**
 * Remove a group with its pins from a project (`remove_project_group`).
 *
 * @param {string} project - Project id.
 * @param {string} group - The group's name.
 * @returns {Promise<ProjectCard>} The changed card.
 * @throws {ApiError} As `unpinGroupPins`.
 */
export function removeProjectGroup(project, group) {
  return request("DELETE", `/projects/${one(project)}/groups/${one(group)}`);
}

/**
 * Write a project's export `zestawy/<name>/` from its pins (`export_project`):
 * `pliki.txt` and `ATRYBUCJE.txt`.
 *
 * @param {string} project - Project id.
 * @param {ExportRequest} body - The export's name; `groups` left out: every group.
 * @returns {Promise<ProjectExport>} The export just written (`201`).
 * @throws {ApiError} `400` (a name breaking the rule), `403` (`permission_denied`),
 *   `404` (an unknown group), `409` (a project file Archiwista cannot read),
 *   `500` (`io_error`).
 */
export function exportProject(project, body) {
  return request("POST", `/projects/${one(project)}/exports`, { json: body });
}

/**
 * A project's exports, each saying whether the project changed after it
 * (`list_project_exports`).
 *
 * @param {string} project - Project id.
 * @param {RequestOptions} [options]
 * @returns {Promise<ProjectExports>}
 */
export function listProjectExports(project, { signal } = {}) {
  return request("GET", `/projects/${one(project)}/exports`, { signal });
}

/**
 * A page of a project's activity, newest entry first (`get_project_activity`):
 * its changes and its jobs from the action log.
 *
 * @param {string} project - Project id.
 * @param {{limit?: number, cursor?: number|null}} [query] - Page size (at most
 *   100) and `next_cursor` of the page before.
 * @param {RequestOptions} [options]
 * @returns {Promise<ProjectActivity>}
 */
export function getProjectActivity(project, query = {}, { signal } = {}) {
  return request("GET", `/projects/${one(project)}/activity`, { query, signal });
}

/**
 * Start a job over a project's groups (`start_project_job`, A-ADR-049
 * decision 11): `verify` hashes the pinned files, `check` compares the pins
 * with the source, `repin` pins one group anew, `restore` downloads the
 * missing pinned versions again.
 *
 * @param {string} project - Project id.
 * @param {ProjectJobRequest} body - The kind; `groups` left out: every group
 *   (a re-pin names exactly one).
 * @returns {Promise<JobDetail>} The queued job (`202`).
 * @throws {ApiError} `403 permission_denied` (a re-pin or restore without
 *   `project_write` or `store_write`), `404` (an unknown group), `409
 *   conflict` (`offline_mode`, `unknown_store`, a job of the project already
 *   running in `details.job`), `422 unsupported` (`no_commands`,
 *   `command_not_rebuildable`).
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

/**
 * The session's own preferences (`get_preferences`, v0.4): its person's, an
 * agent's account's, the owner's in local mode; the defaults before the first
 * change.
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<Preferences>}
 */
export function getPreferences({ signal } = {}) {
  return request("GET", "/preferences", { signal });
}

/**
 * Replace the session's own preferences (`put_preferences`): send the whole
 * object of `getPreferences` with the changes, since omitted fields take
 * defaults.
 *
 * @param {Preferences} preferences
 * @returns {Promise<Preferences>} The preferences as saved.
 * @throws {ApiError} `400 validation_error`: an alias whose server prefix is not
 *   absolute or over 400 characters, more than 20 aliases (`errors` name each
 *   value), or a basemap that is not configured (reason `unknown_basemap`).
 */
export function putPreferences(preferences) {
  return request("PUT", "/preferences", { json: preferences });
}

// The action log (v0.4) -------------------------------------------------------

/**
 * A page of the action log, newest entry first (`get_log`; administrators).
 *
 * @param {ActionFilters & {limit?: number, cursor?: number}} [filters] -
 *   `limit` 1–200 (default 50); `cursor`: `next_cursor` of the page before.
 * @param {RequestOptions} [options]
 * @returns {Promise<ActionPage>}
 * @throws {ApiError} `403 permission_denied` without the role `admin` (the log
 *   records the refusal); `400 validation_error` for an invalid filter.
 */
export function getLog(filters = {}, { signal } = {}) {
  return request("GET", "/log", { query: filters, signal });
}

/**
 * Every entry of the action log the filters select, as a file (`export_log`;
 * administrators): JSON Lines, or CSV for a spreadsheet. The export is itself
 * an entry of the log (`log.export`) and holds the entries before it.
 *
 * @param {ActionFilters} filters
 * @param {"jsonl"|"csv"} format
 * @param {RequestOptions} [options]
 * @returns {Promise<{blob: Blob, name: string}>} The file and the name the
 *   server gave it (`archiwista-log-<UTC time>.<format>`).
 * @throws {ApiError} As `getLog`.
 */
export async function exportLog(filters, format, { signal } = {}) {
  const headers = { Accept: `${EXPORT_TYPES[format]}, application/problem+json` };
  const address = `${API_PREFIX}/log/export${search({ ...filters, format })}`;
  const response = await send("GET", address, { headers, signal });
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `archiwista-log.${format}`;
  return { blob: await response.blob(), name };
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
 * Cancel a job that waits or runs (`cancel_job`): a waiting one ends
 * `cancelled` at once, a running one when its worker has stopped (its events
 * say so); a download publishes no half version.
 *
 * @param {string} job - Job id.
 * @returns {Promise<JobDetail>} The job as it is then (`202`).
 * @throws {ApiError} `403 permission_denied` (neither whoever started it nor
 *   an administrator), `404`, `409 conflict` (`job_finished`).
 */
export function cancelJob(job) {
  return request("POST", `/jobs/${one(job)}/cancel`);
}

/**
 * Run a job that did not succeed again (`retry_job`): a new job of the
 * session with the same kind, store and parameters, asking again what its
 * kind needs (a download: the permission to write the stores).
 *
 * @param {string} job - Job id.
 * @returns {Promise<JobDetail>} The new job (`202`).
 * @throws {ApiError} `403 permission_denied`, `404`, `409 conflict`
 *   (`job_succeeded`, `job_active`).
 */
export function retryJob(job) {
  return request("POST", `/jobs/${one(job)}/retry`);
}

/**
 * The end of a job's log (`get_job_log`): its worker's standard error, the
 * last MiB of it.
 *
 * @param {string} job - Job id.
 * @param {RequestOptions} [options]
 * @returns {Promise<JobLog>}
 * @throws {ApiError} `404`: no such job, one the session does not see whole,
 *   or a job without a log.
 */
export function getJobLog(job, { signal } = {}) {
  return request("GET", `/jobs/${one(job)}/log`, { signal });
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
 * (`put_data_dir`; the project's owner or an administrator); its scan starts
 * at once.
 *
 * @param {string} project
 * @param {string|null} path - Absolute folder on the server's computer, for an
 *   owner who is no administrator inside the project's directory; `null`
 *   brings back the default.
 * @returns {Promise<OwnFolder>}
 * @throws {ApiError} `403 forbidden` (reason `permission_denied`), `400
 *   validation_error` with `details.problems` (the folder breaks a rule, e.g.
 *   `own_data_dir_outside_project`).
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

/**
 * The address of a file to download (`download_version_file`,
 * `download_own_file`, `download_snapshot_file`; ADR-047 decision 5) for a
 * link of the page (`<a href download>`): the browser sends the session's
 * cookie and `Sec-Fetch-Site: same-origin`, which stand in for the CSRF
 * header a link cannot send. The answer is an attachment, never shown.
 *
 * @param {{store: string, version: string}|{project: string, fileId: string,
 *   label?: string|null, member?: string|null}} file - A version of a store,
 *   or an own file: one of its snapshots (`label`), one file of its set or of
 *   the snapshot's (`member`, a name of its `members`).
 * @returns {string} Path and query, e.g. `/api/v1/stores/…/file`.
 */
export function fileAddress(file) {
  if ("store" in file) {
    return `${API_PREFIX}/stores/${one(file.store)}/versions/${segments(file.version)}/file`;
  }
  const own = `/projects/${one(file.project)}/files/${one(file.fileId)}`;
  const path = file.label ? `${own}/snapshots/${one(file.label)}/file` : `${own}/file`;
  return API_PREFIX + path + search({ member: file.member });
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
 * The commands of the producers' catalogs (`list_commands`), every producer
 * whose plugin is available and offers commands; the others are left out.
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<{items: Array<{producer: string, command: string}>}>}
 */
export function listCommands({ signal } = {}) {
  return request("GET", "/commands", { signal });
}

/**
 * The producer's command line of a call (`format_command`), the line `POST
 * /commands/parse` reads back into the same call.
 *
 * @param {CommandCall} call - `producer`, `command`, `options`; `run` may be left out.
 * @param {RequestOptions} [options]
 * @returns {Promise<{producer: string, command: string, line: string}>}
 * @throws {ApiError} `400 validation_error` with the producer's text, `503`
 *   (its plugin is not available).
 */
export function formatCommand(call, { signal } = {}) {
  return request("POST", "/commands/format", { json: call, signal });
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
 * Start a job of a producer's calls on a configured store (`start_job`), all
 * the lines of a row in one job (ADR-044): `check` plans a run of each call
 * without its effects, `download` runs them (with `plan_job`, the plans that
 * check kept of the same calls; with `pin`, into a new group of a project
 * once it succeeded, A-ADR-049 decision 9).
 *
 * @param {JobRequest} body
 * @returns {Promise<JobDetail>} The queued job (`202`).
 * @throws {ApiError} `403 permission_denied` (a download without
 *   `store_write`, a `pin` into a project the session may not change), `400`
 *   (`store_without_producer`, the producer's refusal of an option,
 *   `invalid_group_name`), `404` (also a project of `pin`), `409 conflict`
 *   (`offline_mode`, `plan_mismatch`, `group_exists`, `other_store`,
 *   `unknown_store`); a refusal of one call names its place in `calls` as
 *   `details.call`.
 */
export function startJob(body) {
  return request("POST", "/jobs", { json: body });
}

/**
 * The plans a `check` job kept (`get_job_plan`): their counts and size
 * together and the positions of each call planned, from the index.
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

// Accounts and groups (v0.4, step T6) -----------------------------------------

/**
 * Every account with its roles, groups and the state of its password
 * (`list_users`; `admin`).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<UserList>}
 */
export function listUsers({ signal } = {}) {
  return request("GET", "/users", { signal });
}

/**
 * Create an account (`add_user`; `admin`).
 *
 * @param {{id: string, name?: string, roles: string[]}} account
 * @returns {Promise<User>}
 * @throws {ApiError} `409 conflict` (the id is taken), `422 validation_error`.
 */
export function addUser(account) {
  return request("POST", "/users", { json: account });
}

/**
 * Change an account's name, roles or whether it is disabled (`update_user`).
 *
 * @param {string} id
 * @param {{name?: string, roles?: string[], disabled?: boolean}} change - The
 *   complete new roles; omitted fields stay.
 * @returns {Promise<User>}
 * @throws {ApiError} `409 conflict` (`last_admin`: the last administrator of a
 *   team who can sign in).
 */
export function updateUser(id, change) {
  return request("PATCH", `/users/${one(id)}`, { json: change });
}

/**
 * Delete an account (`remove_user`).
 *
 * @param {string} id
 * @returns {Promise<null>}
 * @throws {ApiError} `409 conflict` (`last_admin`).
 */
export function removeUser(id) {
  return request("DELETE", `/users/${one(id)}`);
}

/**
 * Give an account a temporary password the server generates, answered this
 * once (`set_temporary_password`); the account's sessions end.
 *
 * @param {string} id
 * @returns {Promise<TemporaryPassword>}
 */
export function temporaryPassword(id) {
  return request("POST", `/users/${one(id)}/password`);
}

/**
 * End every session of an account and of its agents (`end_user_sessions`).
 *
 * @param {string} id
 * @returns {Promise<null>}
 */
export function endUserSessions(id) {
  return request("DELETE", `/users/${one(id)}/sessions`);
}

/**
 * Every group with its members (`list_groups`; `admin`).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<GroupList>}
 */
export function listGroups({ signal } = {}) {
  return request("GET", "/groups", { signal });
}

/**
 * Create a group, optionally with its members (`add_group`; `admin`).
 *
 * @param {{id: string, name?: string, members: string[]}} group
 * @returns {Promise<Group>}
 * @throws {ApiError} `409 conflict` (the id is taken), `400 validation_error`
 *   (an unknown member).
 */
export function addGroup(group) {
  return request("POST", "/groups", { json: group });
}

/**
 * Replace a group's members (`set_group_members`).
 *
 * @param {string} id
 * @param {string[]} members - Account ids, the complete new list.
 * @returns {Promise<Group>}
 */
export function setGroupMembers(id, members) {
  return request("PUT", `/groups/${one(id)}/members`, { json: { members } });
}

/**
 * Delete a group (`remove_group`): its members no longer see the projects
 * shared with it.
 *
 * @param {string} id
 * @returns {Promise<null>}
 */
export function removeGroup(id) {
  return request("DELETE", `/groups/${one(id)}`);
}

/**
 * The enabled accounts and the groups to share a project with, ids and names
 * only (`get_directory`; any session).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<Directory>}
 */
export function getDirectory({ signal } = {}) {
  return request("GET", "/directory", { signal });
}

/**
 * Who owns a project and who sees it (`project_access`; its owner or an
 * administrator).
 *
 * @param {string} project
 * @param {RequestOptions} [options]
 * @returns {Promise<ProjectAccess>}
 * @throws {ApiError} `403 forbidden` (`permission_denied`), `404`.
 */
export function getProjectAccess(project, { signal } = {}) {
  return request("GET", `/projects/${one(project)}/access`, { signal });
}

/**
 * Set who sees a project and, optionally, its new owner (`share_project`;
 * its owner or an administrator).
 *
 * @param {string} project
 * @param {AccessChange} change
 * @returns {Promise<ProjectAccess>}
 * @throws {ApiError} `403 forbidden` (`permission_denied`), `404`, `400
 *   validation_error` (unknown people, groups or owner; lists that do not fit
 *   the visibility).
 */
export function putProjectAccess(project, change) {
  return request("PUT", `/projects/${one(project)}/access`, { json: change });
}

// Helpers ---------------------------------------------------------------------

/** The CSRF token this tab keeps, or `null`. */
function storedToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

/** Keep a new session's CSRF token in this tab and tell the other tabs. */
function keepSession(started) {
  sessionStorage.setItem(TOKEN_KEY, started.csrf_token);
  channel?.postMessage({ type: "token", token: started.csrf_token });
  current = started;
  return started;
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
 * A refusal of a token that a new session has replaced meanwhile (a password
 * change, a sign-in in another tab) tells nobody: the new session goes on.
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
  const refused = problem.status === 401 || problem.details?.reason === "csrf_rejected";
  if (refused && current !== null && storedToken() === token) {
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
