/**
 * „Polecenia producenta” of the Store view (plan 2026-11-05 A4; docs/SPEC.md
 * 6.5 h, 12.2 KB-1): a form of the producer's commands that write the store,
 * read from its catalog (`GET /commands`, texts in the session's language),
 * for each producer of the store whose data no area chooses (no availability
 * at the source in `GET /sources`: Obserwator, whose IMGW-PIB archives are
 * national files). Kartograf's downloads start from an area on the map.
 *
 * A command is one of the catalog's that works on a store and has a plan
 * without effects (`store`, `check`); its options are fields by their type
 * (a choice, a list of choices, a list of values separated by commas, a
 * number, a switch, a text), never a file path (SPEC 10.1). „Zaplanuj…”
 * checks the call against this store without the network (`POST
 * /commands/validate`: a refusal shows at its option), writes its command
 * line (`POST /commands/format`) and opens the plan window over the shell
 * (views/plan.js), which plans it and downloads into this store.
 */

import { formatCommand, listCommands, listSources, validateCommand } from "../api.js";
import { useDownloadActions } from "../downloads.js";
import { useResource } from "../hooks.js";
import { t } from "../labels/index.js";
import { store as S } from "../labels/store.js";
import { html, Icon, ProblemView, Tech, useId, useState } from "../ui.js";

const L = S.commands;

/**
 * The section, or nothing when no producer of the store offers such commands.
 *
 * @param {{item: import("../types.js").StoreItem}} props
 */
export function CommandsSection({ item }) {
  const commands = useResource((signal) => listCommands({ signal }), []);
  const sources = useResource((signal) => listSources({ signal }), []);
  const byArea = new Set(
    (sources.data?.items ?? [])
      .filter((source) => (source.availability ?? []).length)
      .map((source) => source.producer),
  );
  const offered = (commands.data?.items ?? []).filter(
    (command) =>
      item.producers.includes(command.producer) &&
      !byArea.has(command.producer) &&
      command.store &&
      command.check,
  );
  if (!offered.length) return null;
  return html`<section class="card store-section" aria-labelledby="store-commands">
    <h2 class="section-title" id="store-commands">${L.title}</h2>
    <p class="hint">${L.intro}</p>
    <${CommandForm} key=${item.store} item=${item} commands=${offered} />
  </section>`;
}

/**
 * The chosen command with its fields and „Zaplanuj…”.
 *
 * @param {{item: import("../types.js").StoreItem, commands: Array<object>}} props
 */
function CommandForm({ item, commands }) {
  const id = useId();
  const { openPlan } = useDownloadActions();
  const [picked, setPicked] = useState(0);
  const [values, setValues] = useState({});
  const [problem, setProblem] = useState(null);
  const [reading, setReading] = useState(false);
  const command = commands[Math.min(picked, commands.length - 1)];
  const fields = command.options.filter((option) => !option.path_role && option.type !== "object");
  const set = (name, value) => {
    setValues({ ...values, [name]: value });
    setProblem(null);
  };
  const submit = async (event) => {
    event.preventDefault();
    if (reading) return;
    const options = callOptions(fields, values);
    const call = { producer: command.producer, command: command.command, options };
    setReading(true);
    setProblem(null);
    try {
      await validateCommand({ ...call, store: item.store });
      const { line } = await formatCommand(call);
      openPlan({
        producer: command.producer,
        store: { id: item.store, name: item.name },
        title: t(L.plan_title, { producer: command.producer, command: command.command }),
        line,
        area: null,
      });
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
    } finally {
      setReading(false);
    }
  };
  const invalid = problem?.details?.option ?? null;
  return html`<form class="store-commands" onSubmit=${submit}>
    <div class="field">
      <label for=${`${id}-command`}>${L.command}</label>
      <select id=${`${id}-command`} class="select-sm" value=${String(picked)}
        onChange=${(event) => {
          setPicked(Number(event.currentTarget.value));
          setValues({});
          setProblem(null);
        }}>
        ${commands.map(
          (entry, index) => html`<option key=${`${entry.producer} ${entry.command}`}
            value=${String(index)}>
            ${t(L.command_value, { producer: entry.producer, command: entry.command })}</option>`,
        )}
      </select>
      <span class="field-hint">${command.summary}</span>
    </div>
    ${fields.map(
      (option) => html`<${OptionField} key=${`${command.command} ${option.name}`}
        id=${`${id}-${option.name}`}
        option=${option} value=${values[option.name]} invalid=${invalid === option.name}
        onChange=${(value) => set(option.name, value)} />`,
    )}
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
    <button type="submit" class="btn sm primary" disabled=${reading}>
      ${reading
        ? html`<span class="spinner" aria-hidden="true"></span>`
        : html`<${Icon} name="search" size=${14} />`}
      ${L.submit}</button>
  </form>`;
}

/**
 * One option as a field: its name, the producer's description, its default.
 *
 * @param {{id: string, option: object, value: *, invalid: boolean,
 *   onChange: (value: *) => void}} props
 */
function OptionField({ id, option, value, invalid, onChange }) {
  const label = html`<${Tech} value=${[["option", option.name]]}>${option.name}</${Tech}>
    ${option.required ? html` <span class="faint">${L.required}</span>` : null}`;
  const hint = html`<span class="field-hint" id=${`${id}-hint`}>${option.description}${
    option.default !== null && option.default !== undefined
      ? ` ${t(L.default, { value: shown(option.default) })}`
      : ""
  }</span>`;
  const field = (control) => html`<div class=${`field${invalid ? " invalid" : ""}`}>
    <label for=${id}>${label}</label>${control}${hint}</div>`;
  if (option.type === "boolean") {
    const checked = value ?? option.default === true;
    return html`<div class=${`field${invalid ? " invalid" : ""}`}>
      <label class="check"><input id=${id} type="checkbox" checked=${checked}
        aria-describedby=${`${id}-hint`}
        onChange=${(event) => onChange(event.currentTarget.checked)} /> ${label}</label>
      ${hint}</div>`;
  }
  if (option.type === "array" && option.choices.length) {
    const chosen = new Set(value ?? []);
    return html`<fieldset class=${`field${invalid ? " invalid" : ""}`}
      aria-describedby=${`${id}-hint`}>
      <legend>${label}</legend>
      ${option.choices.map(
        (choice) => html`<label class="check" key=${String(choice.value)}>
          <input type="checkbox" checked=${chosen.has(choice.value)}
            onChange=${(event) => {
              const next = new Set(chosen);
              if (event.currentTarget.checked) next.add(choice.value);
              else next.delete(choice.value);
              onChange(option.choices.map((item) => item.value).filter((item) => next.has(item)));
            }} />
          <span>${choice.meaning || choice.value}</span>
          <code class="faint">${choice.value}</code></label>`,
      )}${hint}</fieldset>`;
  }
  if (option.choices.length) {
    return field(html`<select id=${id} class="select-sm" value=${value ?? ""}
      aria-describedby=${`${id}-hint`}
      onChange=${(event) => onChange(event.currentTarget.value || undefined)}>
      <option value="">${L.choose}</option>
      ${option.choices.map(
        (choice) => html`<option key=${String(choice.value)} value=${String(choice.value)}>
          ${choice.meaning ? `${choice.meaning} (${choice.value})` : choice.value}</option>`,
      )}
    </select>`);
  }
  const placeholder = option.type === "array" ? L.list_placeholder : "";
  const numeric = option.type === "integer" || option.type === "number";
  return field(html`<input id=${id} class="mono" type=${numeric ? "number" : "text"}
    value=${value ?? ""} placeholder=${placeholder} autocomplete="off" spellcheck="false"
    aria-invalid=${invalid ? "true" : null} aria-describedby=${`${id}-hint`}
    onInput=${(event) => onChange(event.currentTarget.value)} />`);
}

/**
 * The options of a call from the fields: only what was given, in the JSON
 * form of the producer's catalog (a list of numbers or ranges for `years`).
 *
 * @param {Array<object>} fields
 * @param {Object<string, *>} values
 * @returns {Object<string, *>}
 */
export function callOptions(fields, values) {
  const options = {};
  for (const option of fields) {
    const value = values[option.name];
    if (value === undefined || value === "") continue;
    if (option.type === "boolean") {
      if (value !== (option.default === true)) options[option.name] = value;
    } else if (option.type === "array" && Array.isArray(value)) {
      if (value.length) options[option.name] = value;
    } else if (option.type === "array") {
      const parts = String(value).split(/[\s,]+/).filter(Boolean);
      if (parts.length) options[option.name] = parts.map((part) => listItem(option, part));
    } else if (option.type === "integer" || option.type === "number") {
      options[option.name] = Number(value);
    } else {
      options[option.name] = String(value).trim();
    }
  }
  return options;
}

/** An item of a list typed in a field: a number where the option takes numbers. */
function listItem(option, part) {
  if (option.items === "string") return part;
  return /^-?\d+$/.test(part) ? Number(part) : part;
}

/** A default value as the catalog writes it. */
function shown(value) {
  return Array.isArray(value) ? value.join(", ") : String(value);
}
