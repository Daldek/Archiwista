/**
 * „Dziennik” (docs/SPEC.md 6.5 s and 10.2; plan v0.4 T8, A-ADR-047;
 * administrators): the action log, newest entry first, 50 entries a page.
 *
 * The filters „Kto” (an account id, committed by Enter or on leaving the
 * field), „Działanie” (a group of actions by the prefix of their names),
 * „Wynik” and the days „Od dnia” and „Do dnia” (days of this computer, both
 * included) keep the address (`actor`, `action`, `outcome`, `from`, `to`).
 * „Dalej” and „Wstecz” page through the entries by the API's cursors, kept
 * for the filters shown. A row opens the state before and after, the details,
 * the session, the kind of actor and the address. „Eksportuj CSV” and
 * „Eksportuj JSON Lines” save every entry the filters select as a file
 * (`GET /log/export` through `fetch`, which sends the session's CSRF header);
 * the export is itself an entry of the log. Anyone but an administrator gets
 * the server's refusal, which the log records too.
 */

import { exportLog, getLog } from "../api.js";
import { useApp } from "../context.js";
import { int, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { T, t } from "../labels/index.js";
import { log as L } from "../labels/log.js";
import { setParams } from "../router.js";
import { html, Icon, loadStylesheet, ProblemView, Spinner, useEffect, useId, useState } from "../ui.js";
import { actorName, Badge, loadCardStyles } from "./cards.js";

await Promise.all([loadCardStyles(), loadStylesheet(new URL("./log.css", import.meta.url))]);

/** Entries of a page. */
const PAGE = 50;
const OUTCOMES = ["ok", "denied", "failed"];
/** The badge of each outcome. */
const LEVELS = { ok: "ok", denied: "warn", failed: "bad" };
const FORMATS = ["csv", "jsonl"];
/** The parameters of the address the filters keep. */
const FILTERS = ["actor", "action", "outcome", "from", "to"];
const DAY = /^\d{4}-\d{2}-\d{2}$/;
/** How long the address of a saved file stays valid (as views/compare.js). */
const REVOKE_MS = 1000;

/**
 * „Dziennik” (route `log`).
 *
 * @param {{route: import("../router.js").Route}} props - Parameters `actor`,
 *   `action` (an action, or a group by its prefix such as `job.`), `outcome`
 *   and the days `from` and `to` (`YYYY-MM-DD`).
 */
export default function LogView({ route }) {
  const { settings } = useApp();
  const filters = apiFilters(route.params);
  const key = JSON.stringify(filters);
  // The cursors of the pages read so far for these filters, the shown one last.
  const [paging, setPaging] = useState({ key, cursors: [null] });
  const cursors = paging.key === key ? paging.cursors : [null];
  const cursor = cursors[cursors.length - 1];
  const depth = cursors.length - 1;
  const page = useResource(
    (signal) => getLog({ ...filters, limit: PAGE, cursor }, { signal }).then((data) => ({ ...data, depth })),
    [key, cursor],
  );
  const refused = page.error?.problem?.status === 403;
  let body;
  if (page.error) body = html`<${ProblemView} problem=${page.error.problem} />`;
  else if (page.data) {
    body = html`<${Entries} page=${page.data} busy=${page.loading}
      retention=${settings?.action_log_retention_days ?? null}
      onOlder=${() => setPaging({ key, cursors: [...cursors, page.data.next_cursor] })}
      onNewer=${() => setPaging({ key, cursors: cursors.slice(0, -1) })} />`;
  } else body = html`<${Spinner} />`;
  return html`<div class="cards-page log-page">
    <header class="log-head">
      <h1 class="view-title">${L.title}</h1>
      ${refused ? null : html`<${Export} filters=${filters} onExported=${page.reload} />`}
    </header>
    ${refused ? null : html`<${Filters} params=${route.params} />`}
    ${body}
  </div>`;
}

/**
 * The filters, kept in the address; „Kto” is committed by Enter or on
 * leaving the field.
 *
 * @param {{params: Object<string, string>}} props
 */
function Filters({ params }) {
  const id = useId();
  const [who, setWho] = useState(params.actor ?? "");
  useEffect(() => setWho(params.actor ?? ""), [params.actor]);
  const commit = () => setParams({ actor: who.trim() || null });
  const pick = (name) => (event) => setParams({ [name]: event.currentTarget.value || null });
  const action = params.action ?? "";
  const from = isoDay(params.from);
  const to = isoDay(params.to);
  return html`<div class="log-filters" role="group" aria-label=${L.filters_label}>
    <div class="field log-who">
      <label for=${`${id}-who`}>${L.who}</label>
      <input id=${`${id}-who`} class="mono" value=${who} placeholder=${L.who_placeholder} title=${L.who_title}
        maxlength="64" autocomplete="off" autocapitalize="none" spellcheck="false"
        onInput=${(event) => setWho(event.currentTarget.value)} onChange=${commit}
        onKeyDown=${(event) => event.key === "Enter" && commit()} />
    </div>
    <div class="field">
      <label for=${`${id}-action`}>${L.group}</label>
      <select id=${`${id}-action`} value=${action} onChange=${pick("action")}>
        <option value="">${L.any}</option>
        ${Object.entries(L.groups).map(([prefix, label]) => html`<option key=${prefix} value=${prefix}>${label}</option>`)}
        ${action && !Object.hasOwn(L.groups, action)
          ? html`<option value=${action}>${L.actions[action] ?? action}</option>`
          : null}
      </select>
    </div>
    <div class="field">
      <label for=${`${id}-outcome`}>${L.outcome}</label>
      <select id=${`${id}-outcome`} value=${OUTCOMES.includes(params.outcome) ? params.outcome : ""}
        onChange=${pick("outcome")}>
        <option value="">${L.any}</option>
        ${OUTCOMES.map((outcome) => html`<option key=${outcome} value=${outcome}>${L.outcomes[outcome]}</option>`)}
      </select>
    </div>
    <div class="field">
      <label for=${`${id}-from`}>${L.from}</label>
      <input id=${`${id}-from`} type="date" value=${from} max=${to || null} onChange=${pick("from")} />
    </div>
    <div class="field">
      <label for=${`${id}-to`}>${L.to}</label>
      <input id=${`${id}-to`} type="date" value=${to} min=${from || null} onChange=${pick("to")} />
    </div>
    ${FILTERS.some((name) => params[name])
      ? html`<button type="button" class="btn ghost sm log-clear"
          onClick=${() => setParams(Object.fromEntries(FILTERS.map((name) => [name, null])))}>
          <${Icon} name="x" size=${13} />${L.clear}</button>`
      : null}
  </div>`;
}

/**
 * „Eksportuj CSV” and „Eksportuj JSON Lines”: every entry the filters select,
 * saved as the file the server names.
 *
 * @param {{filters: import("../types.js").ActionFilters, onExported: () => void}} props
 */
function Export({ filters, onExported }) {
  const [busy, setBusy] = useState(null);
  const [saved, setSaved] = useState(null);
  const [problem, setProblem] = useState(null);
  const run = async (format) => {
    setBusy(format);
    setSaved(null);
    setProblem(null);
    try {
      const file = await exportLog(filters, format);
      save(file);
      setSaved(file.name);
      onExported();
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
    } finally {
      setBusy(null);
    }
  };
  return html`<div class="log-export">
    <div class="log-export-buttons" role="group" aria-label=${L.export.label}>
      ${FORMATS.map(
        (format) => html`<button key=${format} type="button" class="btn sm" disabled=${busy !== null}
          title=${L.export[`${format}_title`]} onClick=${() => run(format)}>
          <${Icon} name="download" size=${13} />${busy === format ? L.export.busy : L.export[format]}
        </button>`,
      )}
    </div>
    ${saved ? html`<p class="hint" role="status">${t(L.export.saved, { name: saved })}</p>` : null}
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
  </div>`;
}

/**
 * The entries of a page, a row opening each, and the line „wpisy 1–50 z 1204
 * · starsze niż 365 dni są usuwane” with „Wstecz” and „Dalej”.
 *
 * @param {{page: import("../types.js").ActionPage & {depth: number}, busy: boolean,
 *   retention: number|null, onOlder: () => void, onNewer: () => void}} props -
 *   `depth`: the pages before this one.
 */
function Entries({ page, busy, retention, onOlder, onNewer }) {
  const [open, setOpen] = useState(null);
  const first = page.depth * PAGE + 1;
  const line = [
    page.items.length
      ? t(L.range, { first: int(first), last: int(first + page.items.length - 1), total: int(page.total) })
      : null,
    retention ? t(L.retention, { days: int(retention) }) : null,
  ].filter(Boolean);
  return html`${page.items.length
      ? html`<div class="table-wrap">
          <table class="log-table" aria-label=${L.table.label} aria-busy=${busy ? "true" : null}>
            <thead><tr>
              <th scope="col">${L.table.at}</th>
              <th scope="col">${L.table.who}</th>
              <th scope="col">${L.table.action}</th>
              <th scope="col">${L.table.target}</th>
              <th scope="col">${L.table.outcome}</th>
              <th scope="col">${L.table.client}</th>
            </tr></thead>
            <tbody>${page.items.map(
              (entry) => html`<${Row} key=${entry.id} entry=${entry} open=${open === entry.id}
                onToggle=${() => setOpen(open === entry.id ? null : entry.id)} />`,
            )}</tbody>
          </table>
        </div>`
      : html`<p class="hint">${L.empty}</p>`}
    <div class="log-foot">
      <p class="hint tabular">${line.join(" · ")}</p>
      <div class="log-pages">
        ${busy ? html`<${Spinner} quiet />` : null}
        ${page.depth > 0
          ? html`<button type="button" class="btn sm" disabled=${busy} title=${L.newer_title} onClick=${onNewer}>
              ${L.newer}</button>`
          : null}
        ${page.next_cursor !== null
          ? html`<button type="button" class="btn sm" disabled=${busy} title=${L.older_title} onClick=${onOlder}>
              ${L.older}</button>`
          : null}
      </div>
    </div>`;
}

/**
 * An entry of the log and, opened, what it changed.
 *
 * @param {{entry: import("../types.js").ActionEntry, open: boolean, onToggle: () => void}} props
 */
function Row({ entry, open, onToggle }) {
  const detailsId = `log-entry-${entry.id}`;
  const label = t(L.table.open, { id: entry.id });
  return html`<tr class=${open ? "log-row open" : "log-row"} data-entry=${entry.id}
      onClick=${(event) => !event.target.closest("button") && onToggle()}>
      <td class="tabular">
        <span class="log-at">
          <button type="button" class="btn ghost sm icon-btn log-toggle" aria-expanded=${open ? "true" : "false"}
            aria-controls=${open ? detailsId : null} aria-label=${label} title=${label} onClick=${onToggle}>
            <${Icon} name="chevron" size=${13} />
          </button>
          ${stamp(entry.at)}
        </span>
      </td>
      <td>${who(entry)}</td>
      <td>${what(entry)}</td>
      <td class="mono log-target">${entry.target}</td>
      <td><${Badge} level=${LEVELS[entry.outcome] ?? "plain"}>${L.outcomes[entry.outcome] ?? entry.outcome}</${Badge}></td>
      <td class="mono nw">${origin(entry)}</td>
    </tr>
    ${open
      ? html`<tr class="log-details-row" id=${detailsId}><td colspan="6"><${Details} entry=${entry} /></td></tr>`
      : null}`;
}

/** What a row opens: the state before and after, the details, the session, the kind and the address. */
function Details({ entry }) {
  const parts = [
    ["before", entry.before],
    ["after", entry.after],
    ["details", entry.details],
  ];
  return html`<div class="log-details">
    <dl class="kv log-meta">
      <dt>${L.details.kind}</dt><dd>${L.kinds[entry.actor_kind] ?? L.details.none}</dd>
      <dt>${L.details.session}</dt><dd class="mono">${entry.session ?? L.details.none}</dd>
      <dt>${L.details.client}</dt><dd class="mono">${origin(entry)}</dd>
    </dl>
    <div class="log-states">${parts.map(
      ([part, value]) => html`<section key=${part} class="log-state" aria-label=${L.details[part]}>
        <h2 class="section-title">${L.details[part]}</h2>
        ${value === null
          ? html`<p class="faint">${L.details.none}</p>`
          : html`<pre class="log-json" tabindex="0">${JSON.stringify(value, null, 2)}</pre>`}
      </section>`,
    )}</div>
  </div>`;
}

/** Who acted, for people: an account, the local owner, „… (agent)”, the scheduler, nobody signed in. */
function who(entry) {
  if (entry.actor_kind === "scheduler") return L.actor.scheduler;
  if (entry.actor_kind === "anonymous") return L.actor.anonymous;
  const name = actorName(entry.actor);
  return entry.actor_kind === "agent" ? t(L.actor.agent, { actor: name }) : name;
}

/** What was done, for people; a refusal names the action refused. */
function what(entry) {
  const name = L.actions[entry.action] ?? entry.action;
  const refused = entry.action === "permission.denied" ? entry.details?.action : null;
  return typeof refused === "string" ? html`${name} <span class="faint mono">${refused}</span>` : name;
}

/** Where an entry came from: the client's address, the owner's terminal, or nothing known. */
function origin(entry) {
  if (entry.client) return entry.client;
  return entry.actor_kind === "local_owner" ? L.details.terminal : T.common.empty;
}

/**
 * The filters of the API for those of the address: a day starts at this
 * computer's midnight, and `to` includes its day.
 *
 * @param {Object<string, string>} params
 * @returns {import("../types.js").ActionFilters}
 */
function apiFilters(params) {
  return {
    actor: params.actor?.trim() || null,
    action: params.action || null,
    outcome: OUTCOMES.includes(params.outcome) ? params.outcome : null,
    since: midnight(params.from, 0),
    until: midnight(params.to, 1),
  };
}

/** The midnight starting a day of this computer, `later` days on, in ISO 8601; `null` without a day. */
function midnight(text, later) {
  if (!isoDay(text)) return null;
  const [year, month, day] = text.split("-").map(Number);
  return new Date(year, month - 1, day + later).toISOString();
}

/** A day of the address (`YYYY-MM-DD`), else `""`. */
function isoDay(text) {
  return text && DAY.test(text) ? text : "";
}

/** Save a file the page holds through an `<a download>` of its object address. */
function save({ blob, name }) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_MS);
}
