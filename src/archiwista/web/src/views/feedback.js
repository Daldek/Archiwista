/**
 * „Zgłoszenia” (docs/SPEC.md 6.5 and 9.2; administrators): the reports people
 * sent with „Zgłoś uwagę” (feedback.js), newest first, 50 a page, with the
 * number of unread ones (Hydrograf's admin list). A row shows when it came,
 * who sent it and the start of its text, „nowe” while unread; opening it
 * shows the whole report — the text, the contact, the account, the page,
 * the browser, and the attached view, environment and events — and marks
 * it read. „Oznacz przeczytane” and „Oznacz nieprzeczytane” change it at
 * once and undo the change when the server refuses; „Usuń” deletes it after
 * a confirmation. Everything a report holds is the sender's own and is shown
 * as text only, whatever shape its diagnostics have. Anyone but an
 * administrator gets the server's refusal.
 */

import { deleteFeedback, listFeedback, updateFeedback } from "../api.js";
import { int, stamp } from "../format.js";
import { useAction, useResource } from "../hooks.js";
import { feedback as F } from "../labels/feedback.js";
import { t } from "../labels/index.js";
import { html, Icon, loadStylesheet, ProblemView, Spinner, useState } from "../ui.js";
import { Badge, loadCardStyles } from "./cards.js";

await Promise.all([
  loadCardStyles(),
  loadStylesheet(new URL("./admin.css", import.meta.url)),
  loadStylesheet(new URL("./feedback.css", import.meta.url)),
]);

const L = F.admin;
/** Reports of a page (`GET /admin/feedback?limit`). */
const PAGE = 50;
/** Characters of a report's text its row shows. */
const EXCERPT = 80;

/** The view „Zgłoszenia” (route `feedback`). */
export default function FeedbackView() {
  const [offset, setOffset] = useState(0);
  const page = useResource((signal) => listFeedback({ limit: PAGE, offset }, { signal }), [offset]);
  // The read flags changed here since the page was read, by report number.
  const [marks, setMarks] = useState({ page: null, read: {} });
  const [problem, setProblem] = useState(null);
  const data = page.data;
  const read = marks.page === data ? marks.read : {};
  const isRead = (item) => (item.id in read ? read[item.id] : item.is_read);
  let unread = data?.unread_count ?? 0;
  for (const item of data?.items ?? []) {
    if (item.id in read && read[item.id] !== item.is_read) unread += item.is_read ? 1 : -1;
  }
  const mark = (item, value) => {
    if (isRead(item) === value) return;
    const flip = (flag) => (current) => ({
      page: data,
      read: { ...(current.page === data ? current.read : {}), [item.id]: flag },
    });
    setProblem(null);
    setMarks(flip(value));
    updateFeedback(item.id, { is_read: value }).catch((error) => {
      if (!error.problem) throw error;
      setMarks(flip(!value));
      setProblem(error.problem);
    });
  };
  let body;
  if (page.error && !data) body = html`<${ProblemView} problem=${page.error.problem} />`;
  else if (data) {
    body = html`<${Reports} page=${data} offset=${offset} busy=${page.loading} isRead=${isRead}
      onMark=${mark} onDeleted=${page.reload}
      onOlder=${() => setOffset(offset + PAGE)}
      onNewer=${() => setOffset(Math.max(0, offset - PAGE))} />`;
  } else body = html`<${Spinner} label=${L.loading} />`;
  return html`<div class="page admin-page feedback-page">
    <header class="admin-head">
      <h1>${L.title}</h1>
      ${unread > 0
        ? html`<${Badge} level="bad">${t(L.unread, { count: int(unread) })}</${Badge}>`
        : null}
    </header>
    <p class="hint">${L.intro}</p>
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
    ${page.error && data ? html`<${ProblemView} problem=${page.error.problem} compact />` : null}
    ${body}
  </div>`;
}

/**
 * The reports of a page and the line „zgłoszenia 1–50 z 120” with „Wstecz”
 * and „Dalej”.
 */
function Reports({ page, offset, busy, isRead, onMark, onDeleted, onOlder, onNewer }) {
  const [open, setOpen] = useState(null);
  const toggle = (item) => {
    const opening = open !== item.id;
    setOpen(opening ? item.id : null);
    if (opening) onMark(item, true);
  };
  const last = offset + page.items.length;
  return html`${page.items.length
      ? html`<div class="table-wrap">
          <table class="admin-table feedback-table" aria-label=${L.table_label}
            aria-busy=${busy ? "true" : null}>
            <thead><tr>
              <th scope="col">${L.columns.at}</th>
              <th scope="col">${L.columns.who}</th>
              <th scope="col">${L.columns.message}</th>
              <th scope="col"><span class="visually-hidden">${L.columns.actions}</span></th>
            </tr></thead>
            <tbody>${page.items.map(
              (item) => html`<${Row} key=${item.id} item=${item} read=${isRead(item)}
                open=${open === item.id} onToggle=${() => toggle(item)}
                onMark=${(value) => onMark(item, value)} onDeleted=${onDeleted} />`,
            )}</tbody>
          </table>
        </div>`
      : html`<p class="hint">${L.empty}</p>`}
    <div class="feedback-foot">
      <p class="hint tabular">${page.items.length
        ? t(L.range, { first: int(offset + 1), last: int(last), total: int(page.total) })
        : null}</p>
      <div class="feedback-pages">
        ${offset > 0
          ? html`<button type="button" class="btn sm" disabled=${busy} title=${L.newer_title}
              onClick=${onNewer}>
              ${L.newer}</button>`
          : null}
        ${last < page.total && page.items.length
          ? html`<button type="button" class="btn sm" disabled=${busy} title=${L.older_title}
              onClick=${onOlder}>
              ${L.older}</button>`
          : null}
      </div>
    </div>`;
}

/**
 * A report's row and, opened, the whole report.
 *
 * @param {{item: import("../types.js").FeedbackItem, read: boolean, open: boolean,
 *   onToggle: () => void, onMark: (value: boolean) => void, onDeleted: () => void}} props
 */
function Row({ item, read, open, onToggle, onMark, onDeleted }) {
  const [asking, setAsking] = useState(false);
  const removal = useAction();
  const detailsId = `feedback-report-${item.id}`;
  const label = t(L.open, { id: item.id });
  const long = item.message.length > EXCERPT;
  const excerpt = long ? `${item.message.slice(0, EXCERPT)}…` : item.message;
  const remove = () =>
    removal.run(() => deleteFeedback(item.id)).then((done) => done && onDeleted());
  return html`<tr class=${read ? "feedback-row" : "feedback-row unread"} data-report=${item.id}
      onClick=${(event) => !event.target.closest("button") && onToggle()}>
      <td class="tabular nw">
        <span class="feedback-at">
          <button type="button" class="btn ghost sm icon-btn feedback-toggle"
            aria-expanded=${open ? "true" : "false"} aria-controls=${open ? detailsId : null}
            aria-label=${label} title=${label} onClick=${onToggle}>
            <${Icon} name="chevron" size=${13} />
          </button>
          ${stamp(item.created_at)}
        </span>
      </td>
      <td class=${item.user_id ? "mono nw" : "nw"}>${who(item)}</td>
      <td class="feedback-excerpt">
        <span>${excerpt}</span>
        ${read ? null : html` <${Badge} level="bad">${L.new}</${Badge}>`}
      </td>
      <td class="admin-manage">
        ${asking
          ? html`<span class="admin-actions">
              <span class="feedback-confirm">${t(L.remove_confirm, { id: item.id })}</span>
              <button type="button" class="btn sm" disabled=${removal.busy}
                onClick=${() => setAsking(false)}>
                ${L.cancel}</button>
              <button type="button" class="btn sm danger" disabled=${removal.busy}
                onClick=${remove}>
                <${Icon} name="trash" size=${14} />${L.remove_yes}</button>
            </span>`
          : html`<span class="admin-actions">
              <button type="button" class="btn sm" onClick=${() => onMark(!read)}>
                ${read ? L.mark_unread : L.mark_read}</button>
              <button type="button" class="btn sm" aria-label=${t(L.remove_label, { id: item.id })}
                onClick=${() => setAsking(true)}>${L.remove}</button>
            </span>`}
      </td>
    </tr>
    ${removal.problem
      ? html`<tr class="feedback-details-row"><td colspan="4">
          <${ProblemView} problem=${removal.problem} compact /></td></tr>`
      : null}
    ${open
      ? html`<tr class="feedback-details-row" id=${detailsId}>
          <td colspan="4"><${Details} item=${item} /></td></tr>`
      : null}`;
}

/** The whole report: its text, who and where it came from, and its diagnostics. */
function Details({ item }) {
  const D = L.details;
  const diagnostics = isObject(item.diagnostics) ? item.diagnostics : null;
  return html`<div class="feedback-details">
    <p class="feedback-message">${item.message}</p>
    <dl class="kv feedback-meta">
      <dt>${D.contact}</dt><dd>${item.contact ?? D.none}</dd>
      <dt>${D.account}</dt><dd class=${item.user_id ? "mono" : ""}>${who(item)}</dd>
      <dt>${D.page}</dt><dd class="mono">${item.page_url ?? D.none}</dd>
      <dt>${D.browser}</dt><dd>${item.user_agent ?? D.none}</dd>
    </dl>
    ${diagnostics
      ? html`<div class="feedback-states">
            <section class="feedback-state" aria-label=${D.view}>
              <h2 class="section-title">${D.view}</h2>
              <pre class="feedback-json" tabindex="0">${json(diagnostics.view)}</pre>
            </section>
            <section class="feedback-state" aria-label=${D.env}>
              <h2 class="section-title">${D.env}</h2>
              <pre class="feedback-json" tabindex="0">${json(diagnostics.env)}</pre>
            </section>
          </div>
          <section aria-label=${D.events}>
            <h2 class="section-title">${D.events}</h2>
            <${Events} events=${diagnostics.events} />
          </section>`
      : html`<p class="faint">${D.no_diagnostics}</p>`}
  </div>`;
}

/** The events of a report's diagnostics, the oldest first. */
function Events({ events }) {
  const items = Array.isArray(events) ? events : [];
  if (!items.length) return html`<p class="faint">${L.details.no_events}</p>`;
  return html`<table class="feedback-events">
    <tbody>${items.map((event, index) => {
      const entry = isObject(event) ? event : { data: event };
      const type = String(entry.type ?? "");
      return html`<tr key=${index}>
        <td class="tabular nw">${clock(entry.t)}</td>
        <td class="nw">${L.event_types[type] ?? type}</td>
        <td><code class="feedback-event-data">${JSON.stringify(entry.data ?? {})}</code></td>
      </tr>`;
    })}</tbody>
  </table>`;
}

/** Who sent a report: an account, or the owner of a local installation. */
function who(item) {
  return item.user_id ?? L.local_owner;
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** A value of the diagnostics as indented JSON; a dash without one. */
function json(value) {
  return value === undefined ? L.details.none : JSON.stringify(value, null, 2);
}

/** The local time of an event's ISO time; any other text as it is. */
function clock(value) {
  const text = typeof value === "string" ? value : "";
  const moment = new Date(text);
  if (Number.isNaN(moment.getTime())) return text;
  return moment.toLocaleTimeString("pl-PL", { hour12: false });
}
