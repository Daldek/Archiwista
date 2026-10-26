/**
 * „Konta” (docs/SPEC.md 6.5 p, ADR-046; administrators): every account
 * (`GET /users`) with its roles, groups, the state of its password and its
 * end, and whether it is enabled. „Nowe konto” (`POST /users`) opens the new
 * account's card, which offers its temporary password first. The card of an
 * account: its roles (`PATCH`), the temporary password (`POST
 * /users/{id}/password`) shown once with „Kopiuj” and its end, „Zakończ
 * sesje” (`DELETE /users/{id}/sessions`), „Wyłącz” and „Włącz” (`PATCH
 * disabled`) and „Usuń…” after a confirmation; a refusal such as `409
 * last_admin` shows at its control. In local mode nobody signs in, so the
 * passwords and sessions are left out.
 */

import {
  addUser,
  endUserSessions,
  listUsers,
  removeUser,
  temporaryPassword,
  updateUser,
} from "../api.js";
import { useApp } from "../context.js";
import { stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { admin as L } from "../labels/admin.js";
import { t } from "../labels/index.js";
import {
  CopyButton,
  html,
  Icon,
  loadStylesheet,
  Modal,
  ProblemView,
  Spinner,
  useEffect,
  useId,
  useState,
} from "../ui.js";

await loadStylesheet(new URL("./admin.css", import.meta.url));

const ROLES = ["admin", "store_writer"];
const NEW = Symbol("new account");

/** The view „Konta” (route `accounts`). */
export default function AccountsView() {
  const { session } = useApp();
  const users = useResource((signal) => listUsers({ signal }), []);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(null);
  const [created, setCreated] = useState(null);
  const items = users.data?.items ?? [];
  const wanted = query.trim().toLowerCase();
  const shown = items.filter(
    (user) => !wanted || user.id.includes(wanted) || user.name.toLowerCase().includes(wanted),
  );
  const card = open === NEW ? null : items.find((user) => user.id === open);
  const close = () => {
    setOpen(null);
    setCreated(null);
  };
  return html`<div class="page admin-page">
    <header class="admin-head">
      <h1>${L.accounts.title}</h1>
      <button type="button" class="btn primary" onClick=${() => setOpen(NEW)}>
        <${Icon} name="plus" size=${14} />${L.accounts.add}</button>
      <input type="search" class="admin-search" aria-label=${L.accounts.search}
        placeholder=${L.accounts.search} value=${query}
        onInput=${(event) => setQuery(event.currentTarget.value)} />
    </header>
    <p class="hint">${L.accounts.intro}</p>
    ${users.error ? html`<${ProblemView} problem=${users.error.problem} />` : null}
    ${users.loading && !users.data ? html`<${Spinner} label=${L.accounts.loading} />` : null}
    ${users.data
      ? html`<${AccountTable} users=${shown} team=${session.team} onManage=${setOpen} />
          ${shown.length === 0 && wanted
            ? html`<p class="hint">${t(L.accounts.no_match, { query: query.trim() })}</p>`
            : null}`
      : null}
    ${open === NEW
      ? html`<${NewAccount} onClose=${close}
          onCreated=${(user) => {
            users.reload();
            setCreated(user.id);
            setOpen(user.id);
          }} />`
      : null}
    ${card
      ? html`<${AccountCard} key=${card.id} user=${card} team=${session.team}
          created=${created === card.id} onChanged=${users.reload} onClose=${close} />`
      : null}
  </div>`;
}

function AccountTable({ users, team, onManage }) {
  const columns = L.accounts.columns;
  return html`<div class="table-wrap">
    <table class="admin-table">
      <thead><tr>
        <th>${columns.id}</th><th>${columns.name}</th><th>${columns.roles}</th>
        <th>${columns.groups}</th>${team ? html`<th>${columns.password}</th>` : null}
        <th>${columns.state}</th><th><span class="visually-hidden">${L.accounts.manage}</span></th>
      </tr></thead>
      <tbody>${users.map(
        (user) => html`<tr key=${user.id} class=${user.disabled ? "admin-off" : ""}>
          <td class="mono">${user.id}</td>
          <td>${user.name}</td>
          <td>${roleNames(user.roles)}</td>
          <td>${user.groups.length ? user.groups.join(", ") : L.accounts.none}</td>
          ${team ? html`<td>${passwordState(user)}</td>` : null}
          <td>${user.disabled ? L.accounts.state.disabled : L.accounts.state.enabled}</td>
          <td class="admin-manage">
            <button type="button" class="btn sm" aria-label=${t(L.accounts.manage_label, { id: user.id })}
              onClick=${() => onManage(user.id)}>${L.accounts.manage}</button>
          </td>
        </tr>`,
      )}</tbody>
    </table>
  </div>`;
}

/** „Nowe konto”: the id, the name and the roles of an account to create. */
function NewAccount({ onCreated, onClose }) {
  const id = useId();
  const [form, setForm] = useState({ id: "", name: "", roles: [] });
  const action = useAction();
  const submit = (event) => {
    event.preventDefault();
    const body = { id: form.id.trim(), roles: ROLES.filter((role) => form.roles.includes(role)) };
    if (form.name.trim()) body.name = form.name.trim();
    action.run(() => addUser(body)).then((done) => done && onCreated(done.value));
  };
  return html`<${Modal} label=${L.new_account.title} onClose=${onClose}>
    <form class="admin-form" onSubmit=${submit}>
      <h2>${L.new_account.title}</h2>
      <div class="field">
        <label for=${`${id}-id`}>${L.new_account.id}</label>
        <input id=${`${id}-id`} class="mono" autocapitalize="none" spellcheck="false" required
          value=${form.id} onInput=${(event) => setForm({ ...form, id: event.currentTarget.value })} />
        <span class="field-hint">${L.new_account.id_hint}</span>
      </div>
      <div class="field">
        <label for=${`${id}-name`}>${L.new_account.name}</label>
        <input id=${`${id}-name`} value=${form.name}
          onInput=${(event) => setForm({ ...form, name: event.currentTarget.value })} />
        <span class="field-hint">${L.new_account.name_hint}</span>
      </div>
      <${RoleChecks} legend=${L.new_account.roles} roles=${form.roles}
        onChange=${(roles) => setForm({ ...form, roles })} />
      ${action.problem ? html`<${ProblemView} problem=${action.problem} compact />` : null}
      <div class="modal-actions">
        <button type="button" class="btn" onClick=${onClose}>${L.account.cancel}</button>
        <button type="submit" class="btn primary" disabled=${action.busy || !form.id.trim()}>
          ${L.new_account.submit}</button>
      </div>
    </form>
  </${Modal}>`;
}

/**
 * The card of one account: roles, the temporary password, the sessions, the
 * state and the removal, each with its own outcome or refusal.
 */
function AccountCard({ user, team, created, onChanged, onClose }) {
  const title = t(L.account.title, { id: user.id });
  return html`<${Modal} label=${title} onClose=${onClose}>
    <h2>${title} <span class="muted">${user.name}</span></h2>
    ${created ? html`<p class="admin-note" role="status">${t(L.new_account.created, { id: user.id })}</p>` : null}
    ${team ? html`<${PasswordSection} user=${user} onChanged=${onChanged} />` : null}
    <${RolesSection} user=${user} onChanged=${onChanged} />
    ${team ? html`<${SessionsSection} user=${user} />` : null}
    <${StateSection} user=${user} onChanged=${onChanged} />
    <${RemoveSection} user=${user}
      onRemoved=${() => {
        onChanged();
        onClose();
      }} />
    <div class="modal-actions">
      <button type="button" class="btn primary" onClick=${onClose}>${L.account.close}</button>
    </div>
  </${Modal}>`;
}

function RolesSection({ user, onChanged }) {
  const [roles, setRoles] = useState(user.roles);
  const action = useAction();
  useEffect(() => setRoles(user.roles), [user.roles.join()]);
  const changed = ROLES.some((role) => roles.includes(role) !== user.roles.includes(role));
  const save = () =>
    action
      .run(() => updateUser(user.id, { roles: ROLES.filter((role) => roles.includes(role)) }))
      .then((done) => done && onChanged());
  return html`<section class="admin-section">
    <${RoleChecks} legend=${L.account.roles} roles=${roles} onChange=${setRoles} />
    <div class="admin-row">
      <button type="button" class="btn sm" disabled=${!changed || action.busy} onClick=${save}>
        ${L.account.save_roles}</button>
      ${action.done && !changed ? html`<span class="field-hint" role="status">${L.account.roles_saved}</span>` : null}
    </div>
    ${action.problem ? html`<${ProblemView} problem=${action.problem} compact />` : null}
  </section>`;
}

function PasswordSection({ user, onChanged }) {
  const action = useAction();
  const issued = action.done ? action.value : null;
  const set = () => action.run(() => temporaryPassword(user.id)).then((done) => done && onChanged());
  return html`<section class="admin-section">
    <h3>${L.account.password} <span class="muted">${passwordState(user)}</span></h3>
    ${issued
      ? html`<div class="admin-secret" role="status">
          <b>${t(L.account.temporary_title, { id: user.id })}</b>
          <div class="admin-secret-value">
            <code>${issued.password}</code>
            <${CopyButton} text=${issued.password} label=${t(L.account.temporary_copy, { id: user.id })} />
          </div>
          <span class="field-hint">${t(L.account.temporary_until, { time: stamp(issued.expires_at), id: user.id })}</span>
        </div>`
      : html`<p class="field-hint">${L.account.temporary_hint}</p>
          <div class="admin-row">
            <button type="button" class="btn sm" disabled=${action.busy} onClick=${set}>
              ${L.account.temporary_set}</button>
          </div>`}
    ${action.problem ? html`<${ProblemView} problem=${action.problem} compact />` : null}
  </section>`;
}

function SessionsSection({ user }) {
  const action = useAction();
  return html`<section class="admin-section">
    <h3>${L.account.sessions}</h3>
    <p class="field-hint">${L.account.sessions_hint}</p>
    <div class="admin-row">
      <button type="button" class="btn sm" disabled=${action.busy}
        onClick=${() => action.run(() => endUserSessions(user.id))}>${L.account.end_sessions}</button>
      ${action.done ? html`<span class="field-hint" role="status">${t(L.account.sessions_ended, { id: user.id })}</span>` : null}
    </div>
    ${action.problem ? html`<${ProblemView} problem=${action.problem} compact />` : null}
  </section>`;
}

function StateSection({ user, onChanged }) {
  const action = useAction();
  const flip = () =>
    action.run(() => updateUser(user.id, { disabled: !user.disabled })).then((done) => done && onChanged());
  return html`<section class="admin-section">
    <h3>${L.account.state}
      <span class="muted">${user.disabled ? L.accounts.state.disabled : L.accounts.state.enabled}</span></h3>
    <p class="field-hint">${L.account.disable_hint}</p>
    <div class="admin-row">
      <button type="button" class="btn sm" disabled=${action.busy} onClick=${flip}>
        ${user.disabled ? L.account.enable : L.account.disable}</button>
    </div>
    ${action.problem ? html`<${ProblemView} problem=${action.problem} compact />` : null}
  </section>`;
}

function RemoveSection({ user, onRemoved }) {
  const [asking, setAsking] = useState(false);
  const action = useAction();
  const remove = () => action.run(() => removeUser(user.id)).then((done) => done && onRemoved());
  return html`<section class="admin-section">
    ${asking
      ? html`<p class="admin-note warn">${t(L.account.remove_confirm, { id: user.id })}</p>
          <div class="admin-row">
            <button type="button" class="btn sm" disabled=${action.busy} onClick=${() => setAsking(false)}>
              ${L.account.cancel}</button>
            <button type="button" class="btn sm danger" disabled=${action.busy} onClick=${remove}>
              <${Icon} name="trash" size=${14} />${L.account.remove_yes}</button>
          </div>`
      : html`<div class="admin-row">
          <button type="button" class="btn sm" onClick=${() => setAsking(true)}>${L.account.remove}</button>
        </div>`}
    ${action.problem ? html`<${ProblemView} problem=${action.problem} compact />` : null}
  </section>`;
}

/** Checkboxes of the roles, in the order of `ROLES`. */
function RoleChecks({ legend, roles, onChange }) {
  const toggle = (role) =>
    onChange(ROLES.filter((each) => (each === role ? !roles.includes(role) : roles.includes(each))));
  return html`<fieldset class="admin-roles">
    <legend>${legend}</legend>
    ${ROLES.map(
      (role) => html`<label key=${role} class="check-field">
        <input type="checkbox" checked=${roles.includes(role)} onChange=${() => toggle(role)} />
        ${L.roles[role]}</label>`,
    )}
  </fieldset>`;
}

/**
 * A call of one control: `busy` while it runs, then its answer (`done`,
 * `value`) or its refusal (`problem`). `run` resolves to `{value}`, or
 * `null` when refused.
 */
function useAction() {
  const [state, setState] = useState({ busy: false, done: false, value: null, problem: null });
  const run = async (call) => {
    setState({ busy: true, done: false, value: null, problem: null });
    try {
      const value = await call();
      setState({ busy: false, done: true, value, problem: null });
      return { value };
    } catch (error) {
      if (!error.problem) throw error;
      setState({ busy: false, done: false, value: null, problem: error.problem });
      return null;
    }
  };
  return { ...state, run };
}

function roleNames(roles) {
  return roles.length ? roles.map((role) => L.roles[role] ?? role).join(", ") : L.accounts.none;
}

function passwordState(user) {
  const date = stamp(user.password_expires_at);
  return t(L.accounts.password[user.password] ?? user.password, { date });
}
