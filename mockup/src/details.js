// "Szczegóły zestawu" (right panel): only the selected set. The overview of the
// years and variants is in the centre (map with year chips, fan, catalog); the
// check summary is in the selection panel - nothing here repeats them.

import { useState } from "preact/hooks";
import { html, Coverage, Local, Icon, Cmd, Formats } from "./ui.js";
import { coverage, span, int, mb, plural, hintText, day } from "./labels.js";
import { matches, inFormat, ownState } from "./data.js";

const kb = (bytes) => (bytes < 1e6 ? `${int(bytes / 1024)} KB` : mb(bytes));

/** Own data (docs/SPEC.md 4.7.1): one version of the file - a snapshot or the working file - and "Zrób migawkę". */
function OwnDetails({ fx, c, onSnapshot, busy, onMap }) {
  const [plan, setPlan] = useState(false);
  const [note, setNote] = useState("");
  const own = fx.own;
  const s = c.stats;
  const { added, removed } = ownState(own, c.stateIndex, c.prevIndex);
  const stem = own.file.replace(/\.gpkg$/, "");
  const path = c.current ? `${own.folder}${own.file}` : `${own.folder}.wersje/${stem}/${c.snapshot.label}/${own.file}`;
  const today = new Date().toISOString().slice(0, 10);
  const copy = (t) => navigator.clipboard?.writeText(t).catch(() => {});
  const mapBtn = onMap ? html`<button class="btn sm ghost" onClick=${() => onMap(c)}><${Icon} name="map" size=${13} />Na mapie</button>` : null;
  let actions;
  if (!c.current) {
    actions = html`<div class="det-actions"><button class="btn sm" onClick=${() => copy(path)}><${Icon} name="copy" size=${13} />Kopiuj ścieżkę migawki</button>${mapBtn}</div>`;
  } else if (!plan) {
    actions = html`<div class="det-actions">
      <button class=${`btn sm ${c.changedSince ? "primary" : ""}`} disabled=${busy} onClick=${() => setPlan(true)}><${Icon} name="plus" size=${13} />${busy ? "Migawka w toku…" : "Zrób migawkę…"}</button>
      <button class="btn sm" onClick=${() => copy(path)}><${Icon} name="copy" size=${13} />Kopiuj ścieżkę</button>${mapBtn}
    </div>`;
  } else if (!c.changedSince) {
    actions = html`<div class="snap-plan">
      <p class="muted det-note">Ta sama treść co migawka z ${day(c.lastSnapshot.date)} (SHA-256 bez zmian) — nowa migawka nie powstanie.</p>
      <div class="det-actions"><button class="btn sm" onClick=${() => setPlan(false)}>Zamknij</button></div>
    </div>`;
  } else {
    actions = html`<div class="snap-plan">
      <div class="section-title det-sec">Plan migawki</div>
      <ul class="snap-list">
        <li>kopia <code>${own.folder}${own.file}</code> (${kb(s.size)}, ${int(s.count)} ${plural(s.count, "obiekt", "obiekty", "obiektów")})</li>
        <li>do <code>${own.folder}.wersje/${stem}/${today}_${s.sha256.slice(0, 8)}/</code> z opisem <code>migawka.json</code></li>
        <li>spójna kopia GeoPackage (kopia zapasowa SQLite) — plik może być otwarty w QGIS</li>
        <li>tylko przybywa: migawek nie nadpisujemy ani nie usuwamy</li>
      </ul>
      <label class="snap-note">Opis migawki<input value=${note} placeholder="np. po odbiorze przyłączy" onInput=${(e) => setNote(e.target.value)} /></label>
      <div class="det-actions">
        <button class="btn sm primary" disabled=${busy} onClick=${() => { onSnapshot(note.trim() || "bez opisu"); setPlan(false); setNote(""); }}><${Icon} name="check" size=${13} />Zapisz migawkę</button>
        <button class="btn sm ghost" onClick=${() => setPlan(false)}>Anuluj</button>
      </div>
    </div>`;
  }
  return html`<div class="det">
    <div class="det-head">
      <span class="yr">${c.year}</span>
      <div class="det-title">
        <div class="fmt-line"><b>${own.file}</b><span class="faint">·</span><span>${own.layer}</span></div>
        <div class="det-badges"><${Coverage} combo=${c} /><${Local} local=${c.local} /></div>
      </div>
    </div>
    <dl class="kv">
      <dt>Plik</dt><dd><code class="path">${path}</code></dd>
      <dt>Warstwa</dt><dd>${own.layer} · ${own.geometry} · ${own.crs}</dd>
      <dt>Obiekty</dt><dd>${int(s.count)} · ${int(s.length / 1000)} km przewodów</dd>
      <dt>${c.current ? "Od migawki" : "Od poprzedniej"}</dt><dd>${c.prevIndex < 0
        ? "pierwsza migawka"
        : html`<span style="color:#15803d">+${added.size}</span> / <span style="color:#b91c1c">−${removed.length}</span> ${plural(added.size + removed.length, "obiekt", "obiekty", "obiektów")}`}</dd>
      <dt>Rozmiar</dt><dd>${kb(s.size)}</dd>
      <dt>SHA-256</dt><dd><code class="nw">${s.sha256.slice(0, 16)}…</code></dd>
      ${c.current
        ? html`<dt>Zmieniony</dt><dd>${day(own.current.modified.slice(0, 10))} ${own.current.modified.slice(11, 16)}</dd>`
        : html`<dt>Migawka</dt><dd>${day(c.snapshot.date)} · ${c.snapshot.author}<div class="faint">${c.snapshot.note}</div></dd>`}
      <dt>Atrybuty</dt><dd class="mono-list">${own.schema_fields.map(([n, t]) => `${n} (${t})`).join(", ")}</dd>
    </dl>
    ${actions}
    <p class="faint det-note"><i>Dane własne projektu: Archiwista czyta folder <code>${own.folder}</code> i na polecenie robi migawki w <code>.wersje/</code>; niczego nie usuwa (A-ADR-027). Sieć to dane przykładowe mockupu.</i></p>
  </div>`;
}

/**
 * `combo`: the selected set (null: the selected year has no variant in the
 * filter); `group`: its year group (other variants for the switch);
 * `variants`: show the switch (the catalog view already lists every variant).
 */
export function DetailsPanel({ fx, product, year, group, combo: c, filter, format, onFormat, onSelect, onCard, onAsk, onMap, variants, onSnapshot, snapBusy }) {
  if (c && product === "own") return html`<${OwnDetails} fx=${fx} c=${c} onSnapshot=${onSnapshot} busy=${snapBusy} onMap=${onMap} />`;
  if (!c) {
    return html`<div class="det">
      <div class="det-head"><span class="yr">${year ?? "–"}</span><span class="muted">brak wariantu w aktywnym filtrze</span></div>
      <p class="muted det-note">${group?.hidden ? `${group.hidden} ${plural(group.hidden, "wariant", "warianty", "wariantów")} tego roku poza filtrem — wybierz go w Katalogu albo zmień filtr.` : "Wybierz rok na mapie, w Wachlarzu albo zestaw w Katalogu."}</p>
    </div>`;
  }
  const pick = inFormat(c, format);
  const cov = coverage(c);
  const bdot = product === "bdot10k";
  const n = c.sheetsFull.length + c.sheetsPartial.length;
  const unit = product === "laz" ? plural(n, "kafel", "kafle", "kafli") : plural(n, "arkusz", "arkusze", "arkuszy");
  const frames = c.landM2 ? Math.floor(((c.landM2 - c.uncoveredM2) / c.landM2) * 100) : 0;
  const others = variants && group ? [...group.matching, ...group.all.filter((x) => !matches(x, filter))] : [];
  const byCampaign = (camp) => c.sheetsFull.filter((s) => c.sheetRecords?.[s]?.campaign === camp).length;

  return html`<div class="det">
    <div class="det-head">
      <span class="yr">${c.year}</span>
      <div class="det-title">
        <div class="fmt-line"><b>${c.base}</b>${bdot ? null : html`<span class="faint">·</span><span>${c.horizontal}</span>`}</div>
        <div class="det-badges"><${Coverage} combo=${c} /><${Local} local=${c.local} />${matches(c, filter) ? null : html`<span class="more-chip">poza filtrem</span>`}</div>
      </div>
    </div>
    <dl class="kv">
      <dt>Formaty</dt><dd><${Formats} combo=${c} value=${pick.format} onPick=${onFormat} /></dd>
      ${bdot
        ? html`<dt>Powiaty</dt><dd>${c.units.map((t, i) => html`${i ? ", " : null}<span class="nw">${t}${c.unitsPresent.includes(t) ? "" : " (brak)"}</span>`)}</dd>
            <dt>Rozmiar</dt><dd>${mb(c.sizeBytes)}</dd>`
        : html`<dt>${product === "laz" ? "Kafle" : "Arkusze"}</dt><dd>${int(n)} ${unit} · TAK/NIE ${c.sheetsFull.length}/${c.sheetsPartial.length}</dd>
            ${c.sheetsPartial.length ? html`<dt>Niepełne</dt><dd class="mono-list">${c.sheetsPartial.slice(0, 4).join(", ")}${c.sheetsPartial.length > 4 ? ` +${c.sheetsPartial.length - 4}` : ""}</dd>` : null}
            <dt>Nalot</dt><dd>${span(c.dates)}</dd>
            <dt>Kampanie</dt><dd>${c.campaignsSelected.length
              ? c.campaignsSelected.map((x, i) => html`${i ? html`<br />` : null}<code class="nw">${x}</code>${c.campaignsSelected.length > 1 ? html` <span class="faint">${byCampaign(x)} ark.</span>` : null}`)
              : "–"}${c.campaignsAll.length > c.campaignsSelected.length ? html`<div class="faint">w rekordach: ${c.campaignsAll.length}</div>` : null}</dd>
            ${cov.kind === "partial" ? html`<dt>Pokrycie</dt><dd>w pełnych arkuszach ${Math.floor(cov.pct)}% lądu, w ramkach wszystkich ${frames}% (górna granica)</dd>` : null}`}
    </dl>
    ${c.estimated ? html`<p class="faint det-note"><i>Liczby dla Twojego obszaru: oszacowanie mockupu z ram arkuszy raportu.</i></p>` : null}
    ${pick.hints.length
      ? html`<div class="section-title det-sec">Polecenie pobrania (${pick.format})</div><${Cmd} text=${hintText(pick.hints)} />`
      : html`<p class="muted det-note"><i>Kartograf nie pobiera tego formatu (brak podpowiedzi pobrania).</i></p>`}
    <div class="det-actions">
      <button class="btn sm primary" disabled=${!pick.hints.length} onClick=${() => onAsk(pick, "download")}><${Icon} name="download" size=${13} />Pobierz${c.formats.length > 1 ? ` ${pick.format}` : ""}</button>
      <button class="btn sm" onClick=${() => onAsk(c, "mosaic")} title="Po MVP: asystent (v1.2) i mozaika (v1.3) — plan: pobranie i mozaika"><${Icon} name="chat" size=${13} />Mozaika z asystentem<span class="post-mvp">po MVP</span></button>
      <button class="btn sm" onClick=${() => onCard(pick)}><${Icon} name="file" size=${13} />Karta</button>
      ${onMap ? html`<button class="btn sm ghost" onClick=${() => onMap(c)}><${Icon} name="map" size=${13} />Na mapie</button>` : null}
    </div>
    ${others.length > 1
      ? html`<div class="variant-pick">
          <div class="section-title det-sec">Warianty roku ${c.year}</div>
          ${others.map(
            (v) => html`<button class=${`variant-opt ${v.id === c.id ? "on" : ""} ${matches(v, filter) ? "" : "off"}`} aria-pressed=${v.id === c.id ? "true" : "false"} onClick=${() => onSelect(v)}>
              <span style="flex:1">${v.variant}${bdot ? "" : ` · ${v.horizontal}`}</span><${Coverage} combo=${v} short />
            </button>`,
          )}
        </div>`
      : null}
  </div>`;
}
