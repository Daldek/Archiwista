/**
 * The first-run wizard, and later the settings it edits (docs/SPEC.md 5.5,
 * docs/plans/2026-10-18-plan-v0.1.md 10a, plan v0.2 step 12a): stores (Kartograf's `--output`
 * directory), project directories, offline mode and the preview cache
 * limit (with the cache's usage from `/health`), saved at once with `PUT
 * /settings`. The server checks the directories and asks the producer about
 * each new or moved one; anything wrong keeps the settings in effect and
 * comes back as Polish problems per field, shown at the field. A new store's
 * full scan is started by the server's scheduler (step 6b) and its progress
 * shows in the index banner. The step lives in the address
 * (`?view=setup&step=projects`, `&saved=1` after a save), so Back walks the
 * steps and a reload keeps them.
 */

import { putSettings } from "./api.js";
import { storeLine } from "./banner.js";
import { useApp } from "./context.js";
import { int, plural } from "./format.js";
import { T, t } from "./labels/index.js";
import { navigate, useRoute } from "./router.js";
import { startView } from "./routes.js";
import { html, Icon, ProblemView, Spinner, useEffect, useId, useRef, useState } from "./ui.js";

const L = T.setup;
const STEPS = ["stores", "projects", "mode", "save"];
const STORE_ID = /^[a-z0-9][a-z0-9_-]{0,31}$/;
/** Settings fields of problems: `stores[0].kartograf`, `project_dirs[1]`. */
const FIELD = /^(stores|project_dirs)\[(\d+)\](?:\.(\w+))?$/;
const STORE_FIELDS = new Set(["id", "name", "kartograf", "kind"]);
const NO_ERRORS = { stores: {}, projects: {}, preview: null, general: [] };
const LIMIT_GB = { min: 1, max: 10_000 };
const GIB = 1024 ** 3;
const MIB = 1024 ** 2;
const CACHE_SIZE = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1 });
const SHARE = new Intl.NumberFormat("pl-PL", { style: "percent", maximumFractionDigits: 1 });

let lastKey = 0;
const nextKey = () => ++lastKey;

/** The wizard view (route `setup`). */
export default function SetupView() {
  const app = useApp();
  if (app.settings === undefined) {
    return html`<div class="page">
      ${app.settingsError ? html`<${ProblemView} problem=${app.settingsError.problem} />` : html`<${Spinner} />`}
    </div>`;
  }
  return html`<${Wizard} initial=${app.settings} />`;
}

function Wizard({ initial }) {
  const app = useApp();
  const route = useRoute();
  const [first] = useState(() => initial.stores.length === 0);
  const [draft, setDraft] = useState(() => draftOf(initial));
  const [errors, setErrors] = useState(NO_ERRORS);
  const [problem, setProblem] = useState(null);
  const [saving, setSaving] = useState(false);
  const heading = useRef(null);
  const step = STEPS.includes(route.params.step) ? route.params.step : STEPS[0];
  const saved = route.params.saved === "1";

  useEffect(() => heading.current?.focus(), [step, saved]);
  // Opened as the first-run fallback of `/`: name the view, so the address
  // keeps the wizard once a store exists and the start view changes.
  useEffect(() => {
    if (route.view !== "setup") navigate("setup", route.params, { replace: true });
  }, [route.view]);

  const go = (target) => navigate("setup", { step: target });
  const change = (patch) => setDraft((current) => ({ ...current, ...patch }));

  const next = () => {
    if (step === "stores") {
      const found = storeErrors(draft.stores);
      setErrors({ ...NO_ERRORS, stores: found });
      if (Object.keys(found).length) return;
    }
    if (step === "mode") {
      const limit = limitError(draft.previewLimit);
      setErrors({ ...NO_ERRORS, preview: limit });
      if (limit) return;
    }
    go(STEPS[STEPS.indexOf(step) + 1]);
  };

  const save = async () => {
    const found = storeErrors(draft.stores);
    if (Object.keys(found).length) {
      setErrors({ ...NO_ERRORS, stores: found });
      go("stores");
      return;
    }
    const limit = limitError(draft.previewLimit);
    if (limit) {
      setErrors({ ...NO_ERRORS, preview: limit });
      go("mode");
      return;
    }
    const body = bodyOf(initial, draft);
    setSaving(true);
    setProblem(null);
    try {
      const answer = await putSettings(body.settings);
      const reload =
        answer.offline !== initial.offline ||
        JSON.stringify(answer.basemaps) !== JSON.stringify(initial.basemaps);
      setErrors(NO_ERRORS);
      navigate("setup", { step: "save", saved: "1" }, { replace: true });
      if (reload) {
        // The CSP belongs to the document: a new mode needs a new page.
        location.reload();
        return;
      }
      app.setSettings(answer);
      app.refreshHealth();
    } catch (error) {
      if (!error.problem) throw error;
      const fields = problemFields(error.problem, draft, body.projectKeys);
      setErrors(fields);
      setProblem(error.problem);
      if (Object.keys(fields.stores).length) go("stores");
      else if (Object.keys(fields.projects).length) go("projects");
      else if (fields.preview) go("mode");
    } finally {
      setSaving(false);
    }
  };

  const submit = (event) => {
    event.preventDefault();
    if (step === "save") save();
    else next();
  };

  const title = first ? L.title_first : L.title_edit;
  const body = saved
    ? html`<${Saved} stores=${draft.stores.map((store) => store.id.trim())}
        onEdit=${() => go("stores")} />`
    : html`<form class="wizard-form" onSubmit=${submit} novalidate>
        ${step === "stores" ? html`<${StoresStep} draft=${draft} change=${change} errors=${errors} problem=${problem} />` : null}
        ${step === "projects" ? html`<${ProjectsStep} draft=${draft} change=${change} errors=${errors} problem=${problem} />` : null}
        ${step === "mode" ? html`<${ModeStep} draft=${draft} change=${change} errors=${errors} basemaps=${initial.basemaps ?? []} />` : null}
        ${step === "save" ? html`<${SaveStep} draft=${draft} problem=${problem} saving=${saving} />` : null}
        <div class="wizard-actions">
          ${step !== STEPS[0]
            ? html`<button type="button" class="btn" onClick=${() => go(STEPS[STEPS.indexOf(step) - 1])}>
                ${T.common.actions.back}</button>`
            : null}
          ${step === "save"
            ? html`<button type="submit" class="btn primary" disabled=${saving}>
                ${saving ? html`<span class="spinner" aria-hidden="true"></span>${L.saving}` : first ? L.save : L.save_edit}
              </button>`
            : html`<button type="submit" class="btn primary">${T.common.actions.next}</button>`}
        </div>
      </form>`;
  return html`<div class="page wizard">
    <header class="wizard-head">
      <h1 tabindex="-1" ref=${heading}>${title}</h1>
      <p class="muted">${first ? L.intro_first : L.intro_edit}</p>
    </header>
    <ol class="wizard-steps" aria-label=${L.steps_label}>
      ${STEPS.map((name, index) => {
        const state = saved || index < STEPS.indexOf(step) ? "done" : name === step ? "current" : "";
        return html`<li class=${state} aria-current=${name === step && !saved ? "step" : null}>
          <button type="button" class="wizard-step" disabled=${saving} onClick=${() => go(name)}>
            <span class="step-num">${state === "done" ? html`<${Icon} name="check" size=${12} stroke=${3} />` : index + 1}</span>
            ${L.step[name]}
          </button>
        </li>`;
      })}
    </ol>
    ${body}
  </div>`;
}

function StoresStep({ draft, change, errors, problem }) {
  const { health } = useApp();
  const update = (key, patch) =>
    change({
      stores: draft.stores.map((store) => {
        if (store.key !== key) return store;
        const next = { ...store, ...patch };
        if ("name" in patch && !store.idEdited) next.id = slug(patch.name);
        if ("id" in patch) next.idEdited = true;
        return next;
      }),
    });
  const remove = (key) => change({ stores: draft.stores.filter((store) => store.key !== key) });
  return html`<section class="wizard-step-body">
    <${Sources} sources=${health?.sources} />
    <${General} errors=${errors} problem=${problem} />
    ${draft.stores.map((store, index) => {
      const fieldErrors = errors.stores[store.key] ?? {};
      return html`<fieldset class="step current" key=${store.key}>
        <legend class="step-title">${t(L.store.legend, { number: index + 1 })}</legend>
        <${TextField} label=${L.store.name} hint=${L.store.name_hint} value=${store.name}
          error=${fieldErrors.name} name=${`stores[${index}].name`}
          onInput=${(value) => update(store.key, { name: value })} />
        <${TextField} label=${L.store.id} hint=${L.store.id_hint} value=${store.id} mono
          error=${fieldErrors.id} name=${`stores[${index}].id`}
          onInput=${(value) => update(store.key, { id: value })} />
        <${TextField} label=${L.store.kartograf} hint=${L.store.kartograf_hint} value=${store.kartograf} mono
          error=${fieldErrors.kartograf} name=${`stores[${index}].kartograf`}
          onInput=${(value) => update(store.key, { kartograf: value })} />
        <${SelectField} label=${L.store.kind} value=${store.kind} error=${fieldErrors.kind}
          name=${`stores[${index}].kind`} onChange=${(value) => update(store.key, { kind: value })}
          options=${[
            ["", L.store.kind_auto],
            ["local", T.common.store_kind.local],
            ["share", T.common.store_kind.share],
          ]} />
        ${draft.stores.length > 1
          ? html`<button type="button" class="btn ghost sm" onClick=${() => remove(store.key)}>
              <${Icon} name="trash" size=${14} />${L.store.remove}</button>`
          : null}
      </fieldset>`;
    })}
    <button type="button" class="btn" onClick=${() => change({ stores: [...draft.stores, emptyStore()] })}>
      <${Icon} name="plus" />${L.store.add}</button>
  </section>`;
}

function ProjectsStep({ draft, change, errors, problem }) {
  const update = (key, path) =>
    change({ projects: draft.projects.map((dir) => (dir.key === key ? { ...dir, path } : dir)) });
  const remove = (key) => change({ projects: draft.projects.filter((dir) => dir.key !== key) });
  return html`<section class="wizard-step-body">
    <${General} errors=${errors} problem=${problem} />
    <fieldset class="step current">
      <legend class="step-title">${L.projects.legend}</legend>
      <p class="hint">${L.projects.hint}</p>
      ${draft.projects.length ? null : html`<p class="muted">${L.projects.none}</p>`}
      ${draft.projects.map(
        (dir, index) => html`<div class="field-row" key=${dir.key}>
          <${TextField} label=${t(L.projects.path, { number: index + 1 })} value=${dir.path} mono
            error=${errors.projects[dir.key]} name=${`project_dirs[${index}]`}
            onInput=${(value) => update(dir.key, value)} />
          <button type="button" class="btn ghost icon-btn" onClick=${() => remove(dir.key)}
            title=${L.projects.remove} aria-label=${L.projects.remove}><${Icon} name="trash" /></button>
        </div>`,
      )}
      <button type="button" class="btn" onClick=${() => change({ projects: [...draft.projects, { key: nextKey(), path: "" }] })}>
        <${Icon} name="plus" />${L.projects.add}</button>
    </fieldset>
  </section>`;
}

function ModeStep({ draft, change, errors, basemaps }) {
  const id = useId();
  return html`<section class="wizard-step-body">
    <fieldset class="step current">
      <legend class="step-title">${L.mode.legend}</legend>
      <div class="check-field">
        <input type="checkbox" id=${id} checked=${draft.offline} aria-describedby=${`${id}-hint`}
          onChange=${(event) => change({ offline: event.currentTarget.checked })} />
        <label for=${id}>${L.mode.offline}</label>
      </div>
      <p class="hint" id=${`${id}-hint`}>${L.mode.offline_hint}</p>
      <p class="hint">${L.mode.basemaps}${" "}
        ${basemaps.length ? basemaps.map((basemap) => basemap.name).join(", ") : L.mode.basemaps_none}</p>
    </fieldset>
    <fieldset class="step current">
      <legend class="step-title">${L.previews.legend}</legend>
      <p class="hint">${L.previews.hint}</p>
      <${TextField} label=${L.previews.limit} hint=${L.previews.limit_hint} value=${draft.previewLimit}
        error=${errors.preview} name="preview_cache_limit_gb" type="number" min=${LIMIT_GB.min}
        max=${LIMIT_GB.max} short onInput=${(value) => change({ previewLimit: value })} />
      <${CacheUsage} />
    </fieldset>
  </section>`;
}

/** The preview cache against its limit, as the server's `/health` gives it. */
function CacheUsage() {
  const { health } = useApp();
  const usage = health?.previews;
  if (!usage) return html`<p class="hint">${L.previews.usage_none}</p>`;
  const share = usage.limit_bytes ? usage.used_bytes / usage.limit_bytes : 0;
  return html`<div class="cache-usage">
    <p class="hint">${t(L.previews.usage, {
      used: cacheSize(usage.used_bytes),
      limit: cacheSize(usage.limit_bytes),
      percent: SHARE.format(share),
      objects: int(usage.objects),
      files: plural(usage.objects, T.common.units.files),
    })}</p>
    <progress max=${usage.limit_bytes} value=${Math.min(usage.used_bytes, usage.limit_bytes)}
      aria-label=${L.previews.usage_label}></progress>
  </div>`;
}

function SaveStep({ draft, problem, saving }) {
  const projects = draft.projects.map((dir) => dir.path.trim()).filter(Boolean);
  return html`<section class="wizard-step-body">
    ${problem
      ? html`${problem.details?.problems?.length ? html`<p class="hint warn">${L.invalid}</p>` : null}
          <${ProblemView} problem=${problem} />`
      : null}
    <fieldset class="step current" disabled=${saving}>
      <legend class="step-title">${L.summary.legend}</legend>
      <dl class="kv summary">
        <dt>${L.summary.stores}</dt>
        <dd>${draft.stores.map(
          (store) => html`<div class="summary-store">
            <b>${store.name}</b> <code>${store.id}</code>
            <div class="mono path">${store.kartograf}</div>
            <div class="muted">${store.kind ? T.common.store_kind[store.kind] : L.summary.kind_auto}</div>
          </div>`,
        )}</dd>
        <dt>${L.summary.projects}</dt>
        <dd>${projects.length
          ? projects.map((path) => html`<div class="mono path">${path}</div>`)
          : L.projects.none}</dd>
        <dt>${L.summary.mode}</dt>
        <dd>${draft.offline ? L.summary.offline : L.summary.online}</dd>
        <dt>${L.summary.previews}</dt>
        <dd>${t(L.summary.previews_value, { limit: draft.previewLimit.trim() })}</dd>
      </dl>
    </fieldset>
  </section>`;
}

function Saved({ stores, onEdit }) {
  const { health } = useApp();
  const start = startView();
  const items = stores.map((id) => health?.stores.find((item) => item.store === id));
  return html`<section class="wizard-step-body">
    <div class="step done saved" role="status">
      <div class="step-head"><span class="step-num"><${Icon} name="check" size=${12} stroke=${3} /></span>
        <span class="step-title">${L.saved}</span></div>
      <h2 class="section-title">${L.progress_title}</h2>
      <p class="hint">${L.progress_note}</p>
      <ul class="saved-stores">
        ${items.map((item, index) => html`<li key=${stores[index]}>${item ? html`<${StoreOutcome} item=${item} />` : html`<${Spinner} />`}</li>`)}
      </ul>
    </div>
    <div class="wizard-actions">
      <button type="button" class="btn" onClick=${onEdit}>${L.edit_again}</button>
      ${start.id !== "setup"
        ? html`<button type="button" class="btn primary" onClick=${() => navigate(null)}>${L.go_start}</button>`
        : null}
    </div>
  </section>`;
}

function StoreOutcome({ item }) {
  const { state } = item;
  if (state.status === "available" && state.indexed_at && !state.running_job) {
    return html`<span class="outcome ok"><${Icon} name="check" size=${14} />
      ${t(L.indexed, {
        store: item.name,
        slots: int(state.slots),
        files: plural(state.slots, T.common.units.files),
        versions: int(state.versions),
        versions_word: plural(state.versions, T.common.units.versions),
      })}</span>`;
  }
  const line = storeLine(item);
  if (line && line.level !== "info") return html`<span class="outcome warn"><${Icon} name="alert" size=${14} />${line.text}</span>`;
  return html`<${Spinner} label=${t(L.scanning, { store: item.name })} />`;
}

function Sources({ sources }) {
  if (!sources) return null;
  return html`<div class="sources">
    <h2 class="section-title">${L.sources_title}</h2>
    ${sources.length
      ? sources.map(
          (source) => html`<div class=${`source ${source.status === "available" ? "ok" : "bad"}`}>
            <${Icon} name=${source.status === "available" ? "check" : "alert"} size=${14} />
            <span>${source.message}${source.fix ? html` <b>${source.fix}</b>` : null}</span>
          </div>`,
        )
      : html`<p class="hint warn">${L.sources_none}</p>`}
  </div>`;
}

/** The validation summary above the fields after a refused save. */
function General({ errors, problem }) {
  if (!problem?.details?.problems?.length) return null;
  return html`<div class="general-errors">
    <p class="hint warn">${L.invalid}</p>
    ${errors.general.length ? html`<ul>${errors.general.map((text) => html`<li>${text}</li>`)}</ul>` : null}
  </div>`;
}

function TextField({ label, hint, error, value, onInput, name, mono, short, type = "text", min, max }) {
  const id = useId();
  const described = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(" ");
  const classes = [mono ? "mono" : null, short ? "short" : null].filter(Boolean).join(" ");
  return html`<div class=${error ? "field invalid" : "field"}>
    <label for=${id}>${label}</label>
    <input id=${id} name=${name} type=${type} class=${classes || null} value=${value} min=${min} max=${max}
      spellcheck="false" autocomplete="off" aria-invalid=${error ? "true" : null}
      aria-describedby=${described || null} onInput=${(event) => onInput(event.currentTarget.value)} />
    ${error ? html`<span class="field-error" id=${`${id}-error`}>${error}</span>` : null}
    ${hint ? html`<span class="field-hint" id=${`${id}-hint`}>${hint}</span>` : null}
  </div>`;
}

function SelectField({ label, value, error, options, onChange, name }) {
  const id = useId();
  return html`<div class=${error ? "field invalid" : "field"}>
    <label for=${id}>${label}</label>
    <select id=${id} name=${name} value=${value} aria-invalid=${error ? "true" : null}
      onChange=${(event) => onChange(event.currentTarget.value)}>
      ${options.map(([option, text]) => html`<option value=${option}>${text}</option>`)}
    </select>
    ${error ? html`<span class="field-error">${error}</span>` : null}
  </div>`;
}

// Draft, body and problems -----------------------------------------------------

function draftOf(settings) {
  const stores = settings.stores.map((store) => ({
    key: nextKey(),
    id: store.id,
    name: store.name,
    kartograf: store.kartograf,
    kind: store.kind ?? "",
    idEdited: true,
    original: store,
  }));
  return {
    stores: stores.length ? stores : [emptyStore()],
    projects: (settings.project_dirs ?? []).map((path) => ({ key: nextKey(), path })),
    offline: Boolean(settings.offline),
    previewLimit: String(settings.preview_cache_limit_gb ?? 20),
  };
}

function emptyStore() {
  return { key: nextKey(), id: "", name: "", kartograf: "", kind: "", idEdited: false, original: null };
}

/**
 * The settings to save: those in effect with the wizard's changes (PUT
 * replaces everything), and the draft keys of the saved project directories.
 */
function bodyOf(initial, draft) {
  const projects = draft.projects.filter((dir) => dir.path.trim());
  return {
    settings: {
      ...initial,
      offline: draft.offline,
      preview_cache_limit_gb: Number(draft.previewLimit.trim()),
      project_dirs: projects.map((dir) => dir.path.trim()),
      stores: draft.stores.map((store) => ({
        id: store.id.trim(),
        name: store.name.trim(),
        kartograf: store.kartograf.trim(),
        kind: store.kind || null,
        path_aliases: store.original?.path_aliases ?? {},
      })),
    },
    projectKeys: projects.map((dir) => dir.key),
  };
}

function storeErrors(stores) {
  const errors = {};
  const ids = new Set();
  for (const store of stores) {
    const found = {};
    const id = store.id.trim();
    if (!store.name.trim()) found.name = L.store.name_required;
    if (!store.kartograf.trim()) found.kartograf = L.store.kartograf_required;
    if (!STORE_ID.test(id)) found.id = L.store.id_invalid;
    else if (ids.has(id)) found.id = t(L.store.id_duplicate, { id });
    ids.add(id);
    if (Object.keys(found).length) errors[store.key] = found;
  }
  return errors;
}

/** Why a preview cache limit cannot be saved, or `null`. */
function limitError(value) {
  const text = value.trim();
  const number = Number(text);
  const valid = /^\d+$/.test(text) && number >= LIMIT_GB.min && number <= LIMIT_GB.max;
  return valid ? null : L.previews.limit_invalid;
}

/** Bytes of the preview cache in its own unit: GB and MB of 1024³ and 1024² bytes. */
function cacheSize(bytes) {
  if (bytes >= GIB / 10) return `${CACHE_SIZE.format(bytes / GIB)} GB`;
  return `${CACHE_SIZE.format(bytes / MIB)} MB`;
}

/** Problems of `PUT /settings` by the draft entry and field they concern. */
function problemFields(problem, draft, projectKeys) {
  const fields = { stores: {}, projects: {}, preview: null, general: [] };
  for (const item of problem.details?.problems ?? []) {
    const match = FIELD.exec(item.field ?? "");
    const index = match ? Number(match[2]) : -1;
    if (match?.[1] === "stores" && draft.stores[index]) {
      const name = STORE_FIELDS.has(match[3]) ? match[3] : "kartograf";
      const entry = (fields.stores[draft.stores[index].key] ??= {});
      entry[name] = entry[name] ? `${entry[name]} ${item.message}` : item.message;
    } else if (match?.[1] === "project_dirs" && projectKeys[index] !== undefined) {
      fields.projects[projectKeys[index]] = item.message;
    } else if (item.field === "preview_cache_limit_gb") {
      fields.preview = item.message;
    } else {
      fields.general.push(item.message);
    }
  }
  return fields;
}

/** A store id from its name: „Zespół Kraków” → `zespol-krakow`. */
function slug(name) {
  return name
    .toLowerCase()
    .replaceAll("ł", "l")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^[-_]+|-+$/g, "")
    .slice(0, 32);
}
