/**
 * A project's exports on its card (A-ADR-049 decision 13, docs/SPEC.md 8.4):
 * „Eksportuj…” asks the export's name and groups and writes
 * `zestawy/<name>/` with `pliki.txt` (each pinned version's file once) and
 * `ATRYBUCJE.txt` (each attribution once); the answer tells the versions
 * listed and the pins left out. The list shows each export of the project's
 * `zestawy/` with its directory to copy, when it was written and, when the
 * project file changed after it, „projekt zmieniony po eksporcie — wygeneruj
 * ponownie” with the form opened on its name. Writing is the owner's or an
 * administrator's (`project_write`); otherwise „Eksportuj…” is disabled with
 * the reason.
 */

import { exportProject, listProjectExports } from "../api.js";
import { stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { exports as L } from "../labels/exports.js";
import { t } from "../labels/index.js";
import { CopyButton, html, Icon, ProblemView, Spinner, useId, useState } from "../ui.js";
import { pathToCopy, ServerPath } from "./cards.js";

/**
 * The exports of a project and „Eksportuj…”.
 *
 * @param {{card: import("../types.js").ProjectCard}} props - The project's card;
 *   the list is read again when the index read the project again.
 */
export function ProjectExports({ card }) {
  const id = useId();
  const list = useResource(
    (signal) => listProjectExports(card.project, { signal }),
    [card.project, card.scanned_at],
  );
  const [form, setForm] = useState(null);
  const [done, setDone] = useState(null);
  const why = card.project_write ? null : L.why_write;
  const open = (name = "") => {
    setDone(null);
    setForm({ name });
  };
  const items = list.data?.items ?? [];
  return html`<section class="det-sec" aria-labelledby=${`${id}-title`}>
    <div class="own-group-head">
      <h3 class="section-title" id=${`${id}-title`}>${L.title}</h3>
      <button type="button" class="btn sm" disabled=${why !== null || form !== null}
        title=${why ?? L.open_title} aria-describedby=${why ? `${id}-why` : null}
        onClick=${() => open()}>
        <${Icon} name="download" size=${14} />${L.open}</button>
    </div>
    ${why ? html`<p class="hint" id=${`${id}-why`}>${why}</p>` : null}
    ${form
      ? html`<${ExportForm} key=${form.name} card=${card} name=${form.name}
          onClose=${() => setForm(null)}
          onWritten=${(answer) => {
            setForm(null);
            setDone(answer);
            list.reload();
          }} />`
      : null}
    ${done ? html`<${Written} answer=${done} />` : null}
    ${list.error ? html`<${ProblemView} problem=${list.error.problem} compact />` : null}
    ${list.data === undefined && !list.error ? html`<${Spinner} />` : null}
    ${list.data && !items.length ? html`<p class="faint">${L.empty}</p>` : null}
    ${items.length
      ? html`<ul class="pc-exports" aria-label=${L.list}>
          ${items.map(
            (item) => html`<${ExportRow} key=${item.name} item=${item}
              onAgain=${why === null ? () => open(item.name) : null} />`,
          )}
        </ul>`
      : null}
  </section>`;
}

/**
 * The form of „Eksportuj…”: the export's name and the groups whose pins it
 * lists (all of them at first; all checked sends none, so every group).
 */
function ExportForm({ card, name, onClose, onWritten }) {
  const id = useId();
  const groups = card.groups.map((group) => group.name);
  const [value, setValue] = useState(name);
  const [chosen, setChosen] = useState(groups);
  const [writing, setWriting] = useState(false);
  const [refusal, setRefusal] = useState(null);
  const trimmed = value.trim();
  const ready = trimmed !== "" && (!groups.length || chosen.length > 0) && !writing;
  const toggle = (group, on) => {
    setChosen((now) => (on ? groups.filter((item) => item === group || now.includes(item))
      : now.filter((item) => item !== group)));
    setRefusal(null);
  };
  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setWriting(true);
    setRefusal(null);
    try {
      const body = chosen.length === groups.length ? { name: trimmed } : { name: trimmed, groups: chosen };
      onWritten(await exportProject(card.project, body));
    } catch (error) {
      if (!error.problem) throw error;
      setRefusal(error.problem);
    } finally {
      setWriting(false);
    }
  };
  return html`<form class="pc-form" aria-labelledby=${`${id}-title`} onSubmit=${submit}>
    <h3 class="section-title" id=${`${id}-title`}>${L.form_title}</h3>
    <div class="field">
      <label for=${`${id}-name`}>${L.name}</label>
      <input id=${`${id}-name`} value=${value} autocomplete="off" maxlength="64"
        aria-describedby=${`${id}-name-note`}
        onInput=${(event) => {
          setValue(event.currentTarget.value);
          setRefusal(null);
        }} />
      <span class="field-hint" id=${`${id}-name-note`}>${L.name_hint}</span>
    </div>
    <fieldset class="field" aria-describedby=${`${id}-groups-note`}>
      <legend>${L.groups}</legend>
      ${groups.map(
        (group) => html`<label key=${group} class="check-field">
          <input type="checkbox" checked=${chosen.includes(group)}
            onChange=${(event) => toggle(group, event.currentTarget.checked)} />
          <span>${group}</span>
        </label>`,
      )}
      <span class="field-hint" id=${`${id}-groups-note`}>
        ${groups.length ? L.groups_hint : L.no_groups}</span>
    </fieldset>
    ${refusal ? html`<${ProblemView} problem=${refusal} compact />` : null}
    <div class="pc-form-actions">
      <button type="submit" class="btn sm primary" disabled=${!ready}>
        ${writing
          ? html`<span class="spinner" aria-hidden="true"></span>`
          : html`<${Icon} name="check" size=${14} />`}
        ${L.submit}</button>
      <button type="button" class="btn sm ghost" disabled=${writing} onClick=${onClose}>
        ${L.cancel}</button>
    </div>
  </form>`;
}

/** The export just written: the versions listed and the pins left out. */
function Written({ answer }) {
  const { no_store: noStore, missing } = answer.skipped;
  return html`<p class="pc-done" role="status">
    <${Icon} name="check" size=${15} />
    <span>
      ${t(L.written, { name: answer.name, pins: answer.pins })}
      ${noStore ? html` ${t(L.skipped_no_store, { count: noStore })}` : null}
      ${missing ? html` ${t(L.skipped_missing, { count: missing })}` : null}
    </span>
  </p>`;
}

/** An export of the list: its directory, when it was written, and whether to redo it. */
function ExportRow({ item, onAgain }) {
  const { first, server } = pathToCopy(item.path);
  return html`<li class="pc-export">
    <div>
      <b>${item.name}</b>
      <span class="faint">${t(L.written_at, { at: stamp(item.written_at) })}</span>
      <span class="faint">${item.files.join(", ")}</span>
    </div>
    <div class="pc-path">
      <code class="path">${first}</code>
      <${CopyButton} text=${first} label=${L.copy_path} />
      <${ServerPath} path=${server} />
    </div>
    ${item.changed_since
      ? html`<p class="hint warn">
          <${Icon} name="alert" size=${14} /><span>${L.changed}</span>
          ${onAgain
            ? html`<button type="button" class="btn sm" title=${L.again_title} onClick=${onAgain}>
                <${Icon} name="rotate" size=${14} />${L.again}</button>`
            : null}
        </p>`
      : null}
  </li>`;
}
