/**
 * The diagnostics „Zgłoś uwagę” can attach (feedback.js; Hydrograf's
 * `diagnostics.js`), kept in this tab's memory only: the last 50 events —
 * every call of the API (`api.js`: method, address, status, duration and,
 * for a refusal, the problem's `code` and `details.reason`; Archiwista's
 * server gives no request id) and every error of the page's scripts —, the
 * view with its parameters, and the environment. Nothing leaves the browser
 * until a person sends a report with the diagnostics checked, and then
 * exactly what its preview showed. Only what the person sees in the
 * interface: never a request's body or headers (a password, a token), never
 * a file's content, never the address's fragment (the one-time token).
 *
 * A successful call made again while nothing else happened (the shell's
 * polling) counts on its earlier event (`repeat`, `last`) instead of pushing
 * the person's own steps out of the 50; a snapshot drops the oldest events
 * until it fits the 100,000 characters of compact JSON `POST /feedback`
 * keeps.
 */

import { readRoute } from "./router.js";

/** Events kept, the oldest dropped first. */
const MAX_EVENTS = 50;
/** Characters of a snapshot as compact JSON: the server's `DIAGNOSTICS_MAX_LENGTH`. */
const MAX_SNAPSHOT_CHARS = 100_000;
/** Events a snapshot drops at a time while it is too long. */
const DROP_AT_ONCE = 10;
const MAX_ENDPOINT_CHARS = 300;
const MAX_MESSAGE_CHARS = 300;
const MAX_STACK_CHARS = 500;

/** @type {Array<{t: string, type: string, data: Object<string, *>}>} */
const events = [];

window.addEventListener("error", (event) => {
  logEvent("js_error", {
    message: String(event.message ?? "").slice(0, MAX_MESSAGE_CHARS),
    source: event.filename ? `${event.filename}:${event.lineno}` : null,
    stack: event.error?.stack ? String(event.error.stack).slice(0, MAX_STACK_CHARS) : null,
  });
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  logEvent("js_error", {
    message: String(reason?.message ?? reason).slice(0, MAX_MESSAGE_CHARS),
    stack: reason?.stack ? String(reason.stack).slice(0, MAX_STACK_CHARS) : null,
  });
});

/**
 * Keep an event, dropping the oldest beyond `MAX_EVENTS`.
 *
 * @param {string} type - `api_call` or `js_error`.
 * @param {Object<string, *>} data - JSON values.
 */
export function logEvent(type, data) {
  events.push({ t: new Date().toISOString(), type, data });
  if (events.length > MAX_EVENTS) events.shift();
}

/**
 * Keep a call of the API (`api.js` calls it for every answer, and for no
 * answer at all with status 0; an aborted call is none).
 *
 * @param {string} method
 * @param {string|URL} address - The address asked; only its path and query are kept.
 * @param {number} status - The HTTP status, 0 without an answer.
 * @param {number} started - `performance.now()` when the call was sent.
 * @param {import("./types.js").Problem} [problem] - The refusal, if any.
 */
export function recordCall(method, address, status, started, problem) {
  /** @type {Object<string, *>} */
  const call = {
    method,
    endpoint: endpointOf(address),
    status,
    duration_ms: Math.round(performance.now() - started),
  };
  if (problem) {
    call.code = problem.code;
    call.reason = problem.details?.reason ?? null;
  }
  if (succeeded(status) && repeated(call)) return;
  logEvent("api_call", call);
}

/**
 * What „Dołącz dane diagnostyczne” sends: the events, the view and its
 * parameters, the environment; a copy, so it stays as previewed.
 *
 * @param {Object<string, *>} [app] - What the interface adds to the
 *   environment, e.g. Archiwista's version and the mode.
 * @returns {{events: Array<object>, view: {view: string|null, params: Object<string, string>},
 *   env: Object<string, *>}}
 */
export function snapshot(app = {}) {
  const route = readRoute();
  const payload = {
    events: structuredClone(events),
    view: { view: route.view, params: route.params },
    env: {
      userAgent: navigator.userAgent,
      language: navigator.language,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      url: pageAddress(),
      timestamp: new Date().toISOString(),
      ...app,
    },
  };
  while (JSON.stringify(payload).length > MAX_SNAPSHOT_CHARS && payload.events.length > 0) {
    payload.events.splice(0, DROP_AT_ONCE);
  }
  return payload;
}

/**
 * The page's address without its fragment, which only ever carries the
 * one-time token (router.js).
 *
 * @returns {string}
 */
export function pageAddress() {
  return location.origin + location.pathname + location.search;
}

/** The path and query of an address of this server. */
function endpointOf(address) {
  const url = new URL(String(address), location.origin);
  return (url.pathname + url.search).slice(0, MAX_ENDPOINT_CHARS);
}

function succeeded(status) {
  return status >= 200 && status < 400;
}

/**
 * Count a successful call on its earlier event when only successful calls
 * came since; whether it did.
 */
function repeated(call) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const { type, data } = events[index];
    if (type !== "api_call" || !succeeded(data.status)) return false;
    const same = data.method === call.method && data.endpoint === call.endpoint;
    if (same && data.status === call.status) {
      data.repeat = (data.repeat ?? 1) + 1;
      data.last = new Date().toISOString();
      data.duration_ms = call.duration_ms;
      return true;
    }
  }
  return false;
}
