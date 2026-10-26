/**
 * Step 4 of the „Wybór” panel: what the source has for the area (docs/SPEC.md
 * 6.3 point 3, 6.4; plan 2026-10-25 A10).
 *
 * A product whose availability a producer checks (`availability` of `GET
 * /sources`; the product of the filters first) and a configured store, the
 * target of a download and the store of the badges. The last report of the
 * area comes from the index (`GET /availability`, never the network) with its
 * date; „Sprawdź u źródła” asks the source (`POST /availability`: the
 * `availability` job, followed here; a report younger than seven days
 * answers at once) and „Sprawdź ponownie” asks again (`force`). A row is a
 * year of a country with the coverage label, its best variant (sheet
 * system, resolution, height system, formats, size) and the store badge;
 * the chip „+N wariantów” shows the others, each with its own label and
 * badge. „Pobierz…” of a variant opens the plan window (views/plan.js).
 * Offline the kept report stays and what needs the network is disabled.
 */

import { checkAvailability, getAvailability, listSources } from "../api.js";
import { useApp } from "../context.js";
import { plural, size, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { actions } from "../labels/actions.js";
import { t } from "../labels/index.js";
import { map as M } from "../labels/map.js";
import { html, Icon, ProblemView, Spinner, Tech, useId, useState } from "../ui.js";
import { JobStatus, SUMMARY_STATES, useJob } from "../views/cards.js";
import { DownloadPlan } from "../views/plan.js";

const L = actions.source;
const BADGE_TONES = { all: "done", some: "some", none: "no" };

/**
 * The step „U źródła”.
 *
 * @param {object} props
 * @param {import("../types.js").Area|null} props.area
 * @param {string|null} props.areaLabel - The area's name for people.
 * @param {import("./panel.js").MapFilters} props.filters
 * @param {import("../types.js").StoreSettings[]} props.stores
 * @param {Map<string, string>} props.names - Product names by key.
 * @param {() => void} [props.onRefreshed] - A download changed the store.
 */
export function SourceStep({ area, areaLabel, filters, stores, names, onRefreshed }) {
  const { settings } = useApp();
  const id = useId();
  const offline = Boolean(settings?.offline);
  const sources = useResource((signal) => listSources({ signal }), []);
  const offered = (sources.data?.items ?? []).flatMap((item) =>
    item.availability.map((product) => ({ producer: item.producer, product, key: `${item.producer}/${product}` })),
  );
  const [pickedProduct, setPickedProduct] = useState(null);
  const choice =
    offered.find((item) => item.key === pickedProduct) ??
    offered.find((item) => item.product === filters.product) ??
    offered[0] ??
    null;
  const [pickedStore, setPickedStore] = useState(null);
  const store =
    stores.find((item) => item.id === pickedStore) ?? stores.find((item) => item.id === filters.store) ?? stores[0] ?? null;
  const query =
    area && choice && store
      ? { area_id: area.id, producer: choice.producer, product: choice.product, store: store.id }
      : null;
  const queryKey = query ? JSON.stringify(query) : "";
  const [round, setRound] = useState(0);
  const report = useResource((signal) => (query ? readReport(query, signal) : Promise.resolve(null)), [queryKey, round]);
  const info = report.data && query && sameQuery(report.data, query) ? report.data : null;
  const job = useJob({
    onEnd: (end) => {
      if (SUMMARY_STATES.has(end.state)) setRound((n) => n + 1);
    },
  });
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState(null);
  const [plan, setPlan] = useState(null);
  const busy = starting || job.running;
  const check = async (force) => {
    setStarting(true);
    setProblem(null);
    try {
      const answer = await checkAvailability({ ...query, force });
      if ("id" in answer) job.follow(answer.id, answer.kind);
      else setRound((n) => n + 1);
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
    } finally {
      setStarting(false);
    }
  };
  const productName = (item) => names.get(item.product) ?? item.product;
  const several = new Set(offered.map((item) => item.producer)).size > 1;
  const aside =
    info && !offline
      ? html`<button type="button" class="btn ghost sm step-aside" disabled=${busy} title=${L.recheck_title}
          onClick=${() => check(true)}><${Icon} name="rotate" size=${13} />${L.recheck}</button>`
      : null;
  return html`<section class=${`step src-step ${area ? "current" : ""}`} aria-labelledby=${id} aria-busy=${busy ? "true" : "false"}>
    <div class="step-head">
      <span class="step-num" aria-hidden="true">4</span>
      <h2 class="step-title" id=${id}>${L.title}</h2>
      ${aside}
    </div>
    ${!area ? html`<p class="hint">${L.need_area}</p>` : null}
    ${area && sources.error ? html`<${ProblemView} problem=${sources.error.problem} compact />` : null}
    ${area && sources.data && !offered.length ? html`<p class="hint">${L.no_products}</p>` : null}
    ${area && offline ? html`<p class="hint warn" role="status" title=${L.offline_title}>${L.offline}</p>` : null}
    ${area && offered.length > 1
      ? html`<label class="field src-field">
          <span>${L.product}</span>
          <select class="select-sm" value=${choice.key} onChange=${(event) => setPickedProduct(event.currentTarget.value)}>
            ${offered.map(
              (item) => html`<option key=${item.key} value=${item.key}>${several
                ? t(L.product_value, { product: productName(item), producer: item.producer })
                : productName(item)}</option>`,
            )}
          </select>
        </label>`
      : null}
    ${area && stores.length > 1
      ? html`<label class="field src-field">
          <span>${L.store}</span>
          <select class="select-sm" value=${store.id} onChange=${(event) => setPickedStore(event.currentTarget.value)}>
            ${stores.map((item) => html`<option key=${item.id} value=${item.id}>${item.name}</option>`)}
          </select>
        </label>`
      : null}
    ${area && store && stores.length === 1 && choice
      ? html`<p class="src-store faint">${t(L.store_value, { name: store.name })}</p>`
      : null}
    ${query && report.loading && !info ? html`<p class="hint"><${Spinner} label=${L.loading} /></p>` : null}
    ${query && report.error ? html`<${ProblemView} problem=${report.error.problem} compact />` : null}
    ${query && !report.loading && !report.error && !info
      ? html`<p class="hint">${L.no_report}</p>
          <button type="button" class="btn sm primary src-check" disabled=${busy || offline}
            title=${offline ? L.offline_title : L.check_title} onClick=${() => check(false)}>
            <${Icon} name="search" size=${14} />${L.check}</button>`
      : null}
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
    <${JobStatus} job=${job} />
    ${info
      ? html`<${Report} info=${info} offline=${offline}
          onDownload=${(row, variant) => setPlan({ row, variant })} />`
      : null}
    ${plan && info
      ? html`<${DownloadPlan} producer=${info.producer} store=${{ id: store.id, name: store.name }}
          title=${planTitle(productName(choice), plan.row, plan.variant, areaLabel)} variant=${plan.variant}
          onClose=${() => setPlan(null)}
          onDone=${() => {
            setRound((n) => n + 1);
            onRefreshed?.();
          }} />`
      : null}
  </section>`;
}

/** The kept report of a query, or `null` while the index keeps none (`404`). */
async function readReport(query, signal) {
  try {
    return await getAvailability(query, { signal });
  } catch (error) {
    if (error.problem?.status === 404) return null;
    throw error;
  }
}

function sameQuery(info, query) {
  return (
    info.area.id === query.area_id &&
    info.producer === query.producer &&
    info.product === query.product &&
    info.store === query.store
  );
}

/** The rows of a report with its date and the parts the producer could not check. */
function Report({ info, offline, onDownload }) {
  const countries = new Set(info.rows.map((row) => row.country)).size > 1;
  return html`<div class="src-report">
    <p class="src-checked faint">
      <${Tech} value=${[["checked_at", info.checked_at], ["job", info.job_id ?? "–"]]}>
        ${t(L.checked, { date: stamp(info.checked_at) })}</${Tech}>
    </p>
    ${info.report.failed.map(
      (failure) => html`<p key=${failure.part} class="hint warn">${t(L.failed_part, { part: failure.part, detail: failure.detail })}</p>`,
    )}
    ${info.rows.length
      ? html`<ul class="src-rows" aria-label=${L.rows}>
          ${info.rows.map(
            (row) => html`<${Row} key=${`${row.country}/${row.year}`} row=${row} countries=${countries}
              offline=${offline} onDownload=${(variant) => onDownload(row, variant)} />`,
          )}
        </ul>`
      : html`<p class="hint">${L.no_rows}</p>`}
  </div>`;
}

/** A year of a country: its label, its best variant and the chip of the others. */
function Row({ row, countries, offline, onDownload }) {
  const [open, setOpen] = useState(false);
  const [first, ...others] = row.variants;
  const year = row.year === null ? L.no_year : String(row.year);
  return html`<li class="src-row">
    <div class="src-row-head">
      <b class="src-year tabular">${year}</b>
      ${countries ? html`<span class="faint">${M.countries[row.country] ?? row.country}</span>` : null}
      <${Tech} value=${coverageValues(row.coverage)}><span class=${`src-label ${row.coverage.kind}`}>${row.label}</span></${Tech}>
      ${others.length
        ? html`<button type="button" class="more-chip src-more" aria-expanded=${open ? "true" : "false"}
            title=${open ? L.less_title : L.more_title} onClick=${() => setOpen(!open)}>
            ${t(L.more, { count: row.other_variants, word: plural(row.other_variants, L.variants) })}</button>`
        : null}
    </div>
    ${first ? html`<${Variant} variant=${first} offline=${offline} onDownload=${onDownload} />` : null}
    ${open
      ? html`<ul class="src-others" aria-label=${t(L.other, { year })}>
          ${others.map(
            (variant) => html`<li key=${variantKey(variant)}>
              <${Variant} variant=${variant} labelled offline=${offline} onDownload=${onDownload} />
            </li>`,
          )}
        </ul>`
      : null}
  </li>`;
}

/** A variant: its dimensions, formats, size and badge, and „Pobierz…”. */
function Variant({ variant, labelled, offline, onDownload }) {
  const runnable = Object.values(variant.commands).some((lines) => lines.length > 0);
  const title = offline ? L.download_offline : runnable ? L.download_title : L.no_commands;
  return html`<div class="src-variant">
    ${labelled
      ? html`<${Tech} value=${coverageValues(variant.coverage)}><span class=${`src-label ${variant.coverage.kind}`}>${variant.label}</span></${Tech}>`
      : null}
    <span class="src-dims">${dimensions(variant)}</span>
    <span class="fmts" aria-label=${L.formats}>${variant.formats.map(
      (format) => html`<span key=${format} class="fmt" title=${format === variant.default_format ? L.default_format : null}>${format}</span>`,
    )}</span>
    <span class="faint tabular">${variant.size_bytes === null ? L.size_unknown : size(variant.size_bytes)}</span>
    ${variant.local ? html`<${StoreBadge} badge=${variant.local} />` : null}
    <button type="button" class="btn sm src-download" disabled=${offline || !runnable} title=${title}
      onClick=${() => onDownload(variant)}>${L.download}</button>
  </div>`;
}

/** The store badge: text and a ring of the units held, never colour alone. */
function StoreBadge({ badge }) {
  const percent = badge.of ? Math.floor((badge.units / badge.of) * 100) : 0;
  return html`<span class=${`local ${BADGE_TONES[badge.state]}`}>
    <span class="ring" style=${`--p:${percent}%`} aria-hidden="true"></span>${badge.label}
  </span>`;
}

function dimensions(variant) {
  return [variant.horizontal, variant.resolution, variant.vertical_crs].filter(Boolean).join(" · ");
}

function variantKey(variant) {
  return [dimensions(variant), ...variant.campaigns].join("|");
}

function coverageValues(coverage) {
  const values = [["kind", coverage.kind], ["campaigns", String(coverage.campaigns)]];
  if (coverage.full_share !== null) values.push(["full_share", String(coverage.full_share)]);
  return values;
}

/** What a plan window downloads: product, year, variant and area. */
function planTitle(product, row, variant, area) {
  const parts = [product, row.year === null ? row.country : String(row.year), dimensions(variant)];
  if (area) parts.push(t(actions.plan.area, { name: area }));
  return parts.join(" · ");
}
