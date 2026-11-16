/**
 * „Grupy” (docs/SPEC.md 6.5 q, ADR-046; administrators): every group (`GET
 * /groups`) with its name and members, named after the accounts (`GET
 * /users`). „Nowa grupa” (`POST /groups`) takes the id, the name and the
 * members; „Członkowie…” replaces a group's members with the accounts
 * checked (`PUT /groups/{id}/members`); „Usuń…” removes a group after a
 * confirmation (`DELETE /groups/{id}`), which also takes it out of the
 * projects shared with it. A refusal shows in the window that asked.
 */

import { addGroup, listGroups, listUsers, removeGroup, setGroupMembers } from "../api.js";
import { useAction, useResource } from "../hooks.js";
import { admin as L } from "../labels/admin.js";
import { t } from "../labels/index.js";
import {
  html,
  Icon,
  loadStylesheet,
  Modal,
  ProblemView,
  Spinner,
  useId,
  useState,
} from "../ui.js";

await loadStylesheet(new URL("./admin.css", import.meta.url));

// Members named in a row of the list before „…” (sketch q).
const NAMED_MEMBERS = 2;

/** The view „Grupy” (route `groups`). */
export default function GroupsView() {
  const groups = useResource((signal) => listGroups({ signal }), []);
  const users = useResource((signal) => listUsers({ signal }), []);
  // The window open: `{what: "new"}`, `{what: "members", id}` or `{what: "remove", id}`.
  const [open, setOpen] = useState(null);
  const items = groups.data?.items ?? [];
  const group = open && open.what !== "new" ? items.find((each) => each.id === open.id) : null;
  const close = () => setOpen(null);
  const changed = () => {
    groups.reload();
    close();
  };
  return html`<div class="page admin-page">
    <header class="admin-head">
      <h1>${L.groups.title}</h1>
      <button type="button" class="btn primary" onClick=${() => setOpen({ what: "new" })}>
        <${Icon} name="plus" size=${14} />${L.groups.add}</button>
    </header>
    <p class="hint">${L.groups.intro}</p>
    ${groups.error ? html`<${ProblemView} problem=${groups.error.problem} />` : null}
    ${groups.loading && !groups.data ? html`<${Spinner} label=${L.groups.loading} />` : null}
    ${groups.data
      ? items.length
        ? html`<${GroupTable} groups=${items} users=${users.data?.items ?? []}
            onMembers=${(id) => setOpen({ what: "members", id })}
            onRemove=${(id) => setOpen({ what: "remove", id })} />`
        : html`<p class="hint">${L.groups.empty}</p>`
      : null}
    ${open?.what === "new" ? html`<${NewGroup} users=${users} onCreated=${changed} onClose=${close} />` : null}
    ${group && open.what === "members"
      ? html`<${MembersEditor} key=${group.id} group=${group} users=${users} onSaved=${changed} onClose=${close} />`
      : null}
    ${group && open.what === "remove"
      ? html`<${RemoveGroup} key=${group.id} group=${group} onRemoved=${changed} onClose=${close} />`
      : null}
  </div>`;
}

function GroupTable({ groups, users, onMembers, onRemove }) {
  const columns = L.groups.columns;
  return html`<div class="table-wrap">
    <table class="admin-table">
      <thead><tr>
        <th>${columns.id}</th><th>${columns.name}</th><th>${columns.members}</th>
        <th><span class="visually-hidden">${columns.actions}</span></th>
      </tr></thead>
      <tbody>${groups.map(
        (group) => html`<tr key=${group.id}>
          <td class="mono">${group.id}</td>
          <td>${group.name}</td>
          <td>${memberNames(group.members, users)}</td>
          <td class="admin-manage">
            <span class="admin-actions">
              <button type="button" class="btn sm" aria-label=${t(L.groups.members_label, { id: group.id })}
                onClick=${() => onMembers(group.id)}>${L.groups.members}</button>
              <button type="button" class="btn sm" aria-label=${t(L.groups.remove_label, { id: group.id })}
                onClick=${() => onRemove(group.id)}>${L.groups.remove}</button>
            </span>
          </td>
        </tr>`,
      )}</tbody>
    </table>
  </div>`;
}

/** „Nowa grupa”: the id, the name and the members of a group to create. */
function NewGroup({ users, onCreated, onClose }) {
  const id = useId();
  const [form, setForm] = useState({ id: "", name: "", members: [] });
  const action = useAction();
  const submit = (event) => {
    event.preventDefault();
    const body = { id: form.id.trim(), members: form.members };
    if (form.name.trim()) body.name = form.name.trim();
    action.run(() => addGroup(body)).then((done) => done && onCreated());
  };
  return html`<${Modal} label=${L.new_group.title} onClose=${onClose}>
    <form class="admin-form" onSubmit=${submit}>
      <h2>${L.new_group.title}</h2>
      <div class="field">
        <label for=${`${id}-id`}>${L.new_group.id}</label>
        <input id=${`${id}-id`} class="mono" autocapitalize="none" spellcheck="false" required
          value=${form.id} onInput=${(event) => setForm({ ...form, id: event.currentTarget.value })} />
        <span class="field-hint">${L.new_group.id_hint}</span>
      </div>
      <div class="field">
        <label for=${`${id}-name`}>${L.new_group.name}</label>
        <input id=${`${id}-name`} value=${form.name}
          onInput=${(event) => setForm({ ...form, name: event.currentTarget.value })} />
        <span class="field-hint">${L.new_group.name_hint}</span>
      </div>
      <${MemberChecks} users=${users} members=${form.members}
        onChange=${(members) => setForm({ ...form, members })} />
      ${action.problem ? html`<${ProblemView} problem=${action.problem} compact />` : null}
      <div class="modal-actions">
        <button type="button" class="btn" onClick=${onClose}>${L.account.cancel}</button>
        <button type="submit" class="btn primary" disabled=${action.busy || !form.id.trim()}>
          ${L.new_group.submit}</button>
      </div>
    </form>
  </${Modal}>`;
}

/** „Członkowie · <grupa>”: the accounts checked are the group's new members. */
function MembersEditor({ group, users, onSaved, onClose }) {
  const [members, setMembers] = useState(group.members);
  const action = useAction();
  const title = t(L.members.title, { id: group.id });
  const save = () => action.run(() => setGroupMembers(group.id, members)).then((done) => done && onSaved());
  return html`<${Modal} label=${title} onClose=${onClose}>
    <h2>${title} <span class="muted">${group.name}</span></h2>
    <${MemberChecks} users=${users} members=${members} onChange=${setMembers} />
    ${action.problem ? html`<${ProblemView} problem=${action.problem} compact />` : null}
    <div class="modal-actions">
      <button type="button" class="btn" onClick=${onClose}>${L.account.cancel}</button>
      <button type="button" class="btn primary" disabled=${action.busy || !users.data} onClick=${save}>
        ${L.members.save}</button>
    </div>
  </${Modal}>`;
}

/** „Usuń…”: the removal of a group, after its consequence is said. */
function RemoveGroup({ group, onRemoved, onClose }) {
  const action = useAction();
  const title = t(L.remove_group.title, { id: group.id });
  const remove = () => action.run(() => removeGroup(group.id)).then((done) => done && onRemoved());
  return html`<${Modal} label=${title} onClose=${onClose}>
    <h2>${title} <span class="muted">${group.name}</span></h2>
    <p class="admin-note warn">${L.remove_group.text}</p>
    ${action.problem ? html`<${ProblemView} problem=${action.problem} compact />` : null}
    <div class="modal-actions">
      <button type="button" class="btn" disabled=${action.busy} onClick=${onClose}>${L.account.cancel}</button>
      <button type="button" class="btn danger" disabled=${action.busy} onClick=${remove}>
        <${Icon} name="trash" size=${14} />${L.remove_group.yes}</button>
    </div>
  </${Modal}>`;
}

/**
 * A checkbox for every account, in the order of `GET /users`; a member
 * whose account is disabled stays checked, marked as such.
 */
function MemberChecks({ users, members, onChange }) {
  const toggle = (account) =>
    onChange(members.includes(account) ? members.filter((each) => each !== account) : [...members, account]);
  if (users.error) return html`<${ProblemView} problem=${users.error.problem} compact />`;
  if (!users.data) return html`<${Spinner} label=${L.members.loading} />`;
  return html`<fieldset class="admin-roles admin-members">
    <legend>${L.members.legend}</legend>
    ${users.data.items.length
      ? users.data.items.map(
          (user) => html`<label key=${user.id} class="check-field">
            <input type="checkbox" checked=${members.includes(user.id)} onChange=${() => toggle(user.id)} />
            ${personName(user)}
            ${user.disabled ? html`<span class="muted">· ${L.members.disabled}</span>` : null}</label>`,
        )
      : html`<p class="field-hint">${L.members.no_accounts}</p>`}
  </fieldset>`;
}

/** „3: Anna Nowak, Kasia Wrona, …”: the count and the first members' names. */
function memberNames(members, users) {
  if (!members.length) return L.groups.none;
  const names = members.slice(0, NAMED_MEMBERS).map((id) => users.find((user) => user.id === id)?.name ?? id);
  if (members.length > NAMED_MEMBERS) names.push(L.groups.more);
  return t(L.groups.count, { count: members.length, names: names.join(", ") });
}

/** „Anna Nowak (anna.nowak)”; an account named by its id only once. */
function personName(user) {
  return user.name === user.id ? user.id : t(L.members.person, { name: user.name, id: user.id });
}
