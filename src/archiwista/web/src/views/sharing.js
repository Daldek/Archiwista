/**
 * „Udostępnianie” of a project (docs/SPEC.md 6.5 r, A-ADR-029 erratum 2),
 * opened with „Udostępnij…” on the project card by its owner and the
 * administrators: the owner with „Przekaż…” (another account owns the
 * project), who sees the project — everyone, chosen people, chosen groups or
 * the owner only; administrators see every project — with the people and
 * groups of `GET /directory`, and the project's data folder, which an owner
 * who is no administrator keeps inside the project's directory. „Zapisz”
 * sends only what changed: `PUT /projects/{id}/access`, then `PUT
 * /projects/{id}/data-dir`; a refusal shows at its field, and what was saved
 * before it stays saved.
 */

import { getDirectory, getProjectAccess, listOwnFiles, putDataDir, putProjectAccess } from "../api.js";
import { useAction, useResource } from "../hooks.js";
import { t } from "../labels/index.js";
import { sharing as L } from "../labels/sharing.js";
import { html, Icon, loadStylesheet, Modal, ProblemView, Spinner, useId, useState } from "../ui.js";

await loadStylesheet(new URL("./sharing.css", import.meta.url));

const VISIBILITIES = ["public", "users", "group", "private"];

/**
 * The sharing screen of a project in a modal window.
 *
 * @param {{project: string, name: string, onChanged: (what: "access"|"folder") => void,
 *   onClose: () => void}} props - `onChanged` after each saved change: who sees
 *   or owns the project, or its data folder (whose scan the server starts).
 */
export function SharingDialog({ project, name, onChanged, onClose }) {
  const access = useResource((signal) => getProjectAccess(project, { signal }), [project]);
  const directory = useResource((signal) => getDirectory({ signal }), []);
  const own = useResource((signal) => listOwnFiles(project, { limit: 1 }, { signal }), [project]);
  const title = t(L.title, { name });
  const failed = access.error ?? directory.error ?? own.error;
  const ready = Boolean(access.data && directory.data && own.data);
  return html`<${Modal} label=${title} onClose=${onClose}>
    <h2>${title}</h2>
    ${failed
      ? html`<${ProblemView} problem=${failed.problem} compact />
          <div class="modal-actions">
            <button type="button" class="btn" onClick=${onClose}>${L.cancel}</button>
          </div>`
      : ready
        ? html`<${SharingForm} project=${project} access=${access.data} directory=${directory.data}
            folder=${own.data.folder} onChanged=${onChanged} onClose=${onClose} />`
        : html`<${Spinner} label=${L.loading} />`}
  </${Modal}>`;
}

/**
 * The owner, who sees the project and its data folder, as loaded; „Zapisz”
 * sends what differs from what is saved.
 */
function SharingForm({ project, access, directory, folder, onChanged, onClose }) {
  const id = useId();
  const [saved, setSaved] = useState(access);
  const [form, setForm] = useState({
    visibility: access.visibility,
    users: access.users,
    groups: access.groups,
    owner: "",
    path: folder.path.local,
  });
  const [transferring, setTransferring] = useState(false);
  const accessCall = useAction();
  const folderCall = useAction();
  const busy = accessCall.busy || folderCall.busy;
  const change = (patch) => setForm((current) => ({ ...current, ...patch }));
  const submit = async (event) => {
    event.preventDefault();
    const body = accessChange(form, saved);
    if (body) {
      const done = await accessCall.run(() => putProjectAccess(project, body));
      if (!done) return;
      setSaved(done.value);
      change({ owner: "" });
      setTransferring(false);
      onChanged("access");
    }
    const path = folderChange(form.path, folder);
    if (path !== undefined) {
      const done = await folderCall.run(() => putDataDir(project, path));
      if (!done) return;
      onChanged("folder");
    }
    onClose();
  };
  const people = directory.users;
  const fieldProblems = folderCall.problem?.details?.problems ?? [];
  return html`<form class="share-form" onSubmit=${submit}>
    <div class="share-owner">
      <span>${saved.owner ? t(L.owner, { name: nameOf(people, saved.owner) }) : L.no_owner}</span>
      <button type="button" class="btn sm" disabled=${transferring} onClick=${() => setTransferring(true)}>
        ${L.transfer}</button>
    </div>
    ${transferring
      ? html`<div class="field">
          <label for=${`${id}-owner`}>${L.transfer_label}</label>
          <select id=${`${id}-owner`} value=${form.owner} aria-describedby=${`${id}-owner-hint`}
            onChange=${(event) => change({ owner: event.currentTarget.value })}>
            <option value="">${L.transfer_pick}</option>
            ${people
              .filter((person) => person.id !== saved.owner)
              .map((person) => html`<option key=${person.id} value=${person.id}>${entryName(person)}</option>`)}
          </select>
          <span class="field-hint" id=${`${id}-owner-hint`}>${L.transfer_hint}</span>
        </div>`
      : null}
    <fieldset class="share-visibility">
      <legend>${L.visibility}</legend>
      ${VISIBILITIES.map(
        (value) => html`<div key=${value} class="share-option">
          <label class="check-field">
            <input type="radio" name=${`${id}-visibility`} value=${value} checked=${form.visibility === value}
              onChange=${() => change({ visibility: value })} />
            ${L.visibilities[value]}</label>
          ${value === "users" && form.visibility === "users"
            ? html`<${Picks} entries=${people} chosen=${form.users} add=${L.add_person}
                onChange=${(users) => change({ users })} />`
            : null}
          ${value === "group" && form.visibility === "group"
            ? html`<${Picks} entries=${directory.groups} chosen=${form.groups} add=${L.add_group}
                onChange=${(groups) => change({ groups })} />`
            : null}
        </div>`,
      )}
      ${accessCall.problem ? html`<${ProblemView} problem=${accessCall.problem} compact />` : null}
    </fieldset>
    <div class=${`field${folderCall.problem ? " invalid" : ""}`}>
      <label for=${`${id}-folder`}>${L.folder}</label>
      <input id=${`${id}-folder`} class="mono" value=${form.path} autocomplete="off" spellcheck="false"
        aria-invalid=${folderCall.problem ? "true" : null} aria-describedby=${`${id}-folder-note`}
        onInput=${(event) => change({ path: event.currentTarget.value })} />
      ${fieldProblems.length
        ? html`<span class="field-error" id=${`${id}-folder-note`} role="alert">
            ${fieldProblems.map((item) => item.message).join(" ")}</span>`
        : html`<span class="field-hint" id=${`${id}-folder-note`}>${L.folder_hint}</span>`}
      ${folderCall.problem && !fieldProblems.length
        ? html`<${ProblemView} problem=${folderCall.problem} compact />`
        : null}
    </div>
    <div class="modal-actions">
      <button type="button" class="btn" disabled=${busy} onClick=${onClose}>${L.cancel}</button>
      <button type="submit" class="btn primary" disabled=${busy}>${L.save}</button>
    </div>
  </form>`;
}

/**
 * The people or groups chosen, each with its „×”, and the list adding one.
 *
 * @param {{entries: import("../types.js").DirectoryEntry[], chosen: string[], add: string,
 *   onChange: (chosen: string[]) => void}} props
 */
function Picks({ entries, chosen, add, onChange }) {
  const left = entries.filter((entry) => !chosen.includes(entry.id));
  return html`<div class="share-picks">
    ${chosen.map((value) => {
      const name = nameOf(entries, value);
      return html`<span key=${value} class="chip static share-pick">${name}
        <button type="button" class="share-unpick" aria-label=${t(L.remove, { name })}
          onClick=${() => onChange(chosen.filter((each) => each !== value))}>
          <${Icon} name="x" size=${12} /></button></span>`;
    })}
    <select aria-label=${add} value=""
      onChange=${(event) => {
        const value = event.currentTarget.value;
        if (value) onChange([...chosen, value]);
      }}>
      <option value="">${add}</option>
      ${left.map((entry) => html`<option key=${entry.id} value=${entry.id}>${entryName(entry)}</option>`)}
    </select>
  </div>`;
}

/**
 * The body of `PUT …/access` for the form, or `null` when it changes nothing.
 *
 * @param {{visibility: string, users: string[], groups: string[], owner: string}} form
 * @param {import("../types.js").ProjectAccess} saved
 * @returns {import("../types.js").AccessChange|null}
 */
function accessChange(form, saved) {
  const body = {
    visibility: form.visibility,
    users: form.visibility === "users" ? form.users : [],
    groups: form.visibility === "group" ? form.groups : [],
  };
  if (form.owner) body.owner = form.owner;
  const same =
    !form.owner &&
    body.visibility === saved.visibility &&
    sameItems(body.users, saved.users) &&
    sameItems(body.groups, saved.groups);
  return same ? null : body;
}

/**
 * The data folder to save: a path, `null` (the default `dane/` again) or
 * `undefined` when the folder stays as it is.
 *
 * @param {string} typed - The field; empty brings back the default.
 * @param {import("../types.js").OwnFolder} folder - The folder now.
 * @returns {string|null|undefined}
 */
function folderChange(typed, folder) {
  const path = typed.trim();
  if (!path) return folder.source === "setting" ? null : undefined;
  return path === folder.path.local ? undefined : path;
}

function sameItems(first, second) {
  return first.length === second.length && first.every((item) => second.includes(item));
}

/** The name of an account or a group of the directory; its id when unknown. */
function nameOf(entries, value) {
  return entries.find((entry) => entry.id === value)?.name ?? value;
}

/** „Kasia Wrona (kasia)”; an entry named by its id only once. */
function entryName(entry) {
  return entry.name === entry.id ? entry.id : t(L.person, { name: entry.name, id: entry.id });
}
