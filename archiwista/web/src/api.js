/**
 * Client of the Archiwista HTTP API (`/api/v1`): the only way the interface
 * talks to the server (docs/PLAN_v0.1.md, WWW contract). One function per
 * route, named after its OpenAPI `operationId` in camelCase (`list_slots` →
 * `listSlots`); answers are typed in `types.js`.
 *
 * Session (A-ADR-012 errata 1, SPEC 10.1): `archiwista serve` opens
 * `/#token=…`. `startSession` first removes the token from the address
 * (`history.replaceState`, so it stays in no history entry or bookmark),
 * then exchanges it (`POST /session`); after a reload it checks the session
 * cookie (`GET /session`, which also renews the CSRF cookie). Every `POST`,
 * `PUT`, `PATCH` and `DELETE` carries `X-Archiwista-CSRF` copied from the
 * `archiwista_csrf` cookie. Errors are RFC 9457 problems thrown as
 * `ApiError`; a `401` of any request after the start goes to the
 * `onSessionLost` listeners, so the shell can say how to open a new session.
 */

import { T, t } from "./labels/index.js";

/** @typedef {import("./types.js").Problem} Problem */
/** @typedef {import("./types.js").SessionState} SessionState */
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

/**
 * Abort a read: every function takes these options last.
 *
 * @typedef {{signal?: AbortSignal}} RequestOptions
 */

export const API_PREFIX = "/api/v1";
const CSRF_COOKIE = "archiwista_csrf";
const CSRF_HEADER = "X-Archiwista-CSRF";
const CHANGES = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const FINAL_JOB_STATES = new Set(["succeeded", "failed", "interrupted", "cancelled"]);

/** @type {SessionState|null} */
let current = null;
/** @type {Set<(problem: Problem) => void>} */
const sessionLost = new Set();

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
 * @throws {ApiError} `401 session_required` without a usable token or session,
 *   `network_error` when the server does not answer.
 */
export async function startSession() {
  const token = takeFragmentToken();
  const state = token === null ? await readSession() : await exchangeToken(token);
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
 * The CSRF token of the session: the `archiwista_csrf` cookie, which `GET
 * /session` renews after a reload, else the one the session answered with.
 *
 * @returns {string|null}
 */
export function csrfToken() {
  for (const part of document.cookie.split(";")) {
    const [name, ...value] = part.trim().split("=");
    if (name === CSRF_COOKIE) return decodeURIComponent(value.join("="));
  }
  return current?.csrf_token ?? null;
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
  const headers = { Accept: "application/json, application/problem+json" };
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (body !== undefined) {
    headers["Content-Type"] = type ?? "application/octet-stream";
  }
  if (CHANGES.has(method)) {
    const token = csrfToken();
    if (token !== null) headers[CSRF_HEADER] = token;
  }
  let response;
  try {
    response = await fetch(API_PREFIX + path + search(query), {
      method,
      headers,
      body,
      signal,
      credentials: "same-origin",
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new ApiError(networkProblem());
  }
  if (response.ok) return response.status === 204 ? null : response.json();
  const problem = await readProblem(response);
  if (problem.status === 401 && current !== null) {
    current = null;
    for (const listener of [...sessionLost]) listener(problem);
  }
  throw new ApiError(problem);
}

// Session (step 8) ------------------------------------------------------------

/**
 * Exchange a one-time token for a session (`exchange_token`).
 *
 * @param {string} token - Value after `#token=`.
 * @returns {Promise<SessionState>}
 */
export function exchangeToken(token) {
  return request("POST", "/session", { json: { token } });
}

/**
 * The session of the cookie; renews the CSRF cookie (`read_session`).
 *
 * @param {RequestOptions} [options]
 * @returns {Promise<SessionState>}
 */
export function readSession({ signal } = {}) {
  return request("GET", "/session", { signal });
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
  return request("GET", `/groups/${segments(parentRequest)}`, { signal });
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
 * @throws {ApiError} `422 validation_error` with `problems` per field.
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
 * @throws {ApiError} `409 offline_mode` in offline mode, `409 conflict`.
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
 * Follow a job's events (`get_job_events`, server-sent events): every event
 * since the start, then new ones until a final state ends the stream. A
 * dropped connection resumes after the last event (`Last-Event-ID`).
 *
 * @param {string} job - Job id.
 * @param {JobHandlers} handlers
 * @returns {() => void} Stop following.
 */
export function watchJob(job, { onProgress, onNotice, onState, onError } = {}) {
  const source = new EventSource(`${API_PREFIX}/jobs/${one(job)}/events`);
  const listen = (type, handler) =>
    source.addEventListener(type, (event) => handler?.(JSON.parse(event.data)));
  listen("progress", onProgress);
  listen("notice", onNotice);
  listen("state", (data) => {
    if (FINAL_JOB_STATES.has(data.state)) source.close();
    onState?.(data);
  });
  source.addEventListener("error", () => {
    if (source.readyState !== EventSource.CLOSED) return;
    onError?.({
      type: "about:blank",
      title: T.common.problem.http_title,
      status: 0,
      detail: t(T.common.problem.stream, { job }),
      code: "stream_closed",
    });
  });
  return () => source.close();
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
 * @throws {ApiError} `413 area_too_large`, `422 area_unreadable`,
 *   `422 area_too_complex`.
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

// Helpers ---------------------------------------------------------------------

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

function networkProblem() {
  return {
    type: "about:blank",
    title: T.common.problem.network_title,
    status: 0,
    detail: T.common.problem.network,
    code: "network_error",
  };
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
  return {
    type: "about:blank",
    title: T.common.problem.http_title,
    status: response.status,
    detail: t(T.common.problem.http, { status: response.status }),
    code: "http_error",
  };
}
