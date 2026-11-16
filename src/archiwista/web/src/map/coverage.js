/**
 * Step 3 of the „Wybór” panel: what of the area the store already has
 * (docs/SPEC.md 6.4 „Plakietka magazynu”, UC-02). For each product and
 * store, `GET /local-coverage` first re-reads the area's slots from the
 * store and then answers „lokalnie 83% obszaru” per country, measured in the
 * country's planar CRS — or says why there is no percent, or that the answer
 * comes from the index (`stale`). The files of the area come from the
 * catalog's location groups. „Dodaj do projektu…” of a product pins what
 * the map shows of it in the area: the versions of the chosen year layer of
 * its store, else those of the filters (`versions`, `years`…; the current
 * ones by default), and says which (views/pin-dialog.js).
 */

import { getLocalCoverage, listSlots } from "../api.js";
import { count, stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { T, t } from "../labels/index.js";
import { map as L } from "../labels/map.js";
import { pins as P } from "../labels/pins.js";
import { Link } from "../router.js";
import { html, Icon, ProblemView, Spinner, Tech, useEffect, useId, useState } from "../ui.js";
import { PinButton, pinQuery } from "../views/pin-dialog.js";
import { productStores } from "./products.js";

const KM2 = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2 });

/**
 * The local state of the area.
 *
 * @param {object} props
 * @param {import("../types.js").Area|null} props.area
 * @param {import("./panel.js").MapFilters} props.filters
 * @param {import("../types.js").Product[]} props.products - Products of the index.
 * @param {import("../types.js").StoreSettings[]} props.stores
 * @param {Map<string, string>} props.names - Product names by key.
 * @param {string} props.indexKey - Changes when a store was indexed again.
 * @param {{set: import("../types.js").LayerSet,
 *   layer: import("../types.js").Layer}|null} [props.layer] - The year layer the map shows.
 * @param {() => void} [props.onRefreshed] - The store was read again.
 */
export function LocalState(props) {
  const { area, filters, products, stores, names, indexKey, layer = null, onRefreshed } = props;
  const id = useId();
  const [round, setRound] = useState(0);
  const pairs = coveragePairs(filters, products, stores);
  const key = pairs.map((pair) => `${pair.store}/${pair.product}`).join(",");
  const { results, finished } = useCoverage(area, pairs, `${key}|${round}|${indexKey}`, onRefreshed);
  const groups = useResource(
    (signal) => (area ? listSlots({ ...filters, area_id: area.id, limit: 1 }, { signal }) : Promise.resolve(null)),
    [area?.id, JSON.stringify(filters), indexKey, finished],
  );
  const busy = pairs.some((pair) => results[pairKey(pair)]?.loading);
  const several = stores.length > 1;
  const storeName = (store) => stores.find((item) => item.id === store)?.name ?? store;
  const empty = pairs.filter((pair) => results[pairKey(pair)]?.data?.results.length === 0);
  const aside = area
    ? html`<button type="button" class="btn ghost sm step-aside" disabled=${busy} title=${L.local.refresh_title}
        onClick=${() => setRound((n) => n + 1)}><${Icon} name="rotate" size=${13} />${L.local.refresh}</button>`
    : null;
  return html`<section class=${`step ${area ? "current" : ""}`} aria-labelledby=${id} aria-busy=${busy ? "true" : "false"}>
    <div class="step-head">
      <span class="step-num" aria-hidden="true">3</span>
      <h2 class="step-title" id=${id}>${L.steps.local}</h2>
      ${aside}
    </div>
    ${area ? null : html`<p class="hint">${L.local.need_area}</p>`}
    ${area && groups.data
      ? html`<p class="area-files">
          <span class="faint">${`${L.local.files}: `}</span>
          ${t(L.local.groups, {
            footprint: count(groups.data.groups.footprint, T.common.units.files),
            country: count(groups.data.groups.country, T.common.units.files),
          })}
        </p>`
      : null}
    ${area && groups.error ? html`<${ProblemView} problem=${groups.error.problem} compact />` : null}
    ${area && busy ? html`<p class="hint"><${Spinner} label=${L.local.refreshing} /></p>` : null}
    ${area
      ? pairs
          .filter((pair) => results[pairKey(pair)]?.data?.results.length !== 0)
          .map((pair) => {
            const shown = layer?.set.store === pair.store && layer?.set.product === pair.product;
            return html`<${CoverageItem} key=${pairKey(pair)} state=${results[pairKey(pair)]}
              title=${names.get(pair.product) ?? pair.product} product=${pair.product}
              store=${several ? storeName(pair.store) : null} filters=${filters}
              query=${localQuery(filters, area, pair)} layer=${shown ? layer.layer : null} />`;
          })
      : null}
    ${area && empty.length
      ? html`<p class="hint">${t(filters.product ? L.local.no_files : L.local.none_products, {
          products: empty.map((pair) => names.get(pair.product) ?? pair.product).join(", "),
        })}</p>`
      : null}
    ${area && !pairs.length ? html`<p class="hint">${L.local.no_products}</p>` : null}
    ${area
      ? html`<${Link} class="btn sm catalog-link" view="catalog" params=${{ ...filters, area_id: area.id }}>
          <${Icon} name="table" size=${14} />${L.local.catalog}</${Link}>`
      : null}
  </section>`;
}

/**
 * A product of a store in the area: its local state per country, and
 * „Dodaj do projektu…” of what the map shows of it: the versions of the
 * chosen year `layer`, else those of the filters' `query`.
 */
function CoverageItem({ state, title, product, store, filters, query, layer }) {
  if (!state) return null;
  const what = layer ? layerText(title, store, layer) : filtersText(title, store, filters);
  const pin = layer
    ? html`<${PinButton} source="local_state" versions=${layerVersions(layer)} what=${what} />`
    : html`<${PinButton} source="local_state" query=${query} what=${what} />`;
  return html`<div class="coverage-item">
    <div class="coverage-head">
      <${Tech} value=${product}><b>${title}</b><//>
      ${store ? html`<span class="faint">${t(L.local.store, { name: store })}</span>` : null}
      ${pin}
    </div>
    ${state.loading ? html`<${Spinner} quiet />` : null}
    ${state.error ? html`<${ProblemView} problem=${state.error.problem} compact />` : null}
    ${state.data
      ? html`${state.data.results.map((result) => html`<${CountryRow} key=${result.country} result=${result} />`)}
          ${state.data.stale ? html`<p class="hint warn">${staleText(state.data)}</p>` : null}`
      : null}
  </div>`;
}

function CountryRow({ result }) {
  const percent = result.percent;
  const tone = percent === 100 ? "done" : result.ratio ? "some" : "no";
  const details = [
    result.covered_km2 !== null && result.area_km2 !== null
      ? t(L.local.km2, { covered: KM2.format(result.covered_km2), area: KM2.format(result.area_km2) })
      : null,
    count(result.versions_count, T.common.units.versions),
  ]
    .filter(Boolean)
    .join(" · ");
  return html`<div class="coverage-row">
    <span class=${`local ${tone}`}>
      <span class="ring" style=${`--p:${percent ?? 0}%`} aria-hidden="true"></span>${result.label}
    </span>
    <span class="coverage-country">
      <${Tech} value=${[[L.local.country, result.country ?? T.common.empty], [L.local.crs, result.crs ?? T.common.empty]]}>
        ${L.countries[result.country] ?? result.country ?? L.local.no_country}
      <//>
    </span>
    <span class="faint coverage-details">${details}</span>
    ${result.reason ? html`<span class="hint">${L.local.reason[result.reason] ?? result.reason}</span>` : null}
  </div>`;
}

function staleText(answer) {
  const since = answer.stale_stores.map((item) => stamp(item.indexed_at)).join(", ") || T.common.empty;
  return t(L.local.stale[answer.stale_reason] ?? L.local.stale.store_unavailable, { indexed_at: since });
}

function pairKey(pair) {
  return `${pair.store}/${pair.product}`;
}

/** A pair's versions in the area as the filters choose them, as a pin request asks for them. */
function localQuery(filters, area, pair) {
  const { store, product } = pair;
  return pinQuery({ ...filters, area_id: area.id, store, product });
}

/** What a pair's filters pin, for people: the product, versions, years and store. */
function filtersText(title, store, filters) {
  const versions = L.filters.versions_options[filters.versions ?? "current"] ?? filters.versions;
  return [
    t(P.local.files, { product: title }),
    t(P.local.versions, { versions }),
    filters.years ? t(P.local.years, { years: filters.years }) : null,
    store ? t(P.local.store, { store }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The store versions a layer draws (`version:<store>:<path>`), as a pin request names them. */
function layerVersions(layer) {
  return (layer.versions ?? []).map((item) => {
    const rest = item.ref.slice("version:".length);
    const split = rest.indexOf(":");
    return { store: rest.slice(0, split), version: rest.slice(split + 1) };
  });
}

/** What a year layer pins, for people: the product, its year (or edition) and variant. */
function layerText(title, store, layer) {
  const shown = layer.kind === "year" ? t(P.layer_year, { year: layer.year }) : layer.title;
  return [
    t(P.layer, { product: title, layer: shown, variant: layer.subtitle }),
    store ? t(P.local.store, { store }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * The (store, product) pairs of the local state: the chosen product, or every
 * product of the index; the chosen store, or every store holding the product.
 */
function coveragePairs(filters, products, stores) {
  const storeIds = filters.store ? [filters.store] : stores.map((store) => store.id);
  if (filters.product) {
    const product = products.find((item) => item.product === filters.product);
    const holding = product ? productStores(product, storeIds) : storeIds;
    return holding.map((store) => ({ store, product: filters.product }));
  }
  return products
    .filter((item) => item.product)
    .flatMap((item) => productStores(item, storeIds).map((store) => ({ store, product: item.product })));
}

/** Ask for each pair in turn (each first re-reads the area's slots). */
function useCoverage(area, pairs, key, onRefreshed) {
  const [results, setResults] = useState({});
  const [finished, setFinished] = useState(0);
  useEffect(() => {
    if (!area || !pairs.length) {
      setResults({});
      return undefined;
    }
    const controller = new AbortController();
    setResults(Object.fromEntries(pairs.map((pair) => [pairKey(pair), { loading: true }])));
    (async () => {
      for (const pair of pairs) {
        let state;
        try {
          const data = await getLocalCoverage(
            { area_id: area.id, product: pair.product, store: pair.store },
            { signal: controller.signal },
          );
          state = { data };
        } catch (error) {
          if (controller.signal.aborted) return;
          state = { error };
        }
        if (controller.signal.aborted) return;
        setResults((previous) => ({ ...previous, [pairKey(pair)]: state }));
      }
      onRefreshed?.();
      setFinished((n) => n + 1);
    })();
    return () => controller.abort();
  }, [area?.id, key]);
  return { results, finished };
}
