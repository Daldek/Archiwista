// "Zestawienie": years as a table and as a timeline (year x variant x coverage).

import { useState } from "preact/hooks";
import { html, Coverage, Local, Icon, Seg, Cmd, Formats } from "./ui.js";
import { coverage, span, km2, stamp, variantsMore, plural, int, mb, hintText } from "./labels.js";
import { matches, rank, inFormat, ORIGINS, PRODUCTS } from "./data.js";

const KIND_FILL = { full: "#22c55e", multi: "#14b8a6", partial: "#f59e0b", none: "#e4e7ec" };

function YearTable({ groups, product, selectedYear, onSelectYear, filter }) {
  const wide = groups.some((g) => typeof g.year !== "number");
  return html`<table class="ytable">
    <colgroup><col style=${`width:${wide ? 70 : 46}px`} /><col /><col style="width:92px" /></colgroup>
    <thead><tr><th>Rok</th><th>Pokrycie · magazyn · wariant</th><th style="text-align:right">${product === "bdot10k" ? "Rozmiar" : "Nalot"}</th></tr></thead>
    <tbody>
      ${groups.map((g) => {
        const sel = g.year === selectedYear;
        const c = g.best;
        return [
          html`<tr class=${`yr-row ${sel ? "sel" : ""}`} onClick=${() => onSelectYear(g.year)}>
            <td><div class="y">${g.year}</div></td>
            <td>
              <div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap">
                <${Coverage} combo=${c} />${c ? html`<${Local} local=${c.local} />` : null}
              </div>
              <div class="v">
                ${c ? html`<span>${c.variant}${product === "bdot10k" ? "" : ` · ${c.horizontal}`}</span>` : html`<span>${g.hidden} poza filtrem</span>`}
                ${g.others.length ? html`<span class="more-chip">${variantsMore(g.others.length)}</span>` : null}
              </div>
            </td>
            <td class="d" style="text-align:right">${c ? (product === "bdot10k" ? mb(c.sizeBytes) : span(c.dates)) : "–"}</td>
          </tr>`,
          sel
            ? html`<tr class="detail"><td colspan="3">
                ${[...g.matching, ...g.all.filter((x) => !matches(x, filter))].map((x) => html`<${ComboDetail} key=${x.id} c=${x} product=${product} off=${!matches(x, filter)} />`)}
              </td></tr>`
            : null,
        ];
      })}
    </tbody>
  </table>`;
}

/** One variant of the selected year; its format badges switch the download command. */
function ComboDetail({ c, product, off }) {
  const [format, setFormat] = useState(c.format);
  const pick = inFormat(c, format);
  const cov = coverage(c);
  const frames = c.landM2 ? Math.floor(((c.landM2 - c.uncoveredM2) / c.landM2) * 100) : 0;
  const n = c.sheetsFull.length + c.sheetsPartial.length;
  return html`<div class="combo" style=${off ? "opacity:.55" : ""}>
    <div class="combo-top">
      <span class="combo-name">${c.base}</span><${Formats} combo=${c} value=${pick.format} onPick=${setFormat} />
      <${Coverage} combo=${c} />
      ${off ? html`<span class="more-chip">poza filtrem</span>` : null}
    </div>
    <div class="combo-meta">
      ${product === "bdot10k"
        ? html`powiaty: ${c.units.map((t) => `${t}${c.unitsPresent.includes(t) ? "" : " (brak)"}`).join(", ")} · ${mb(c.sizeBytes)}`
        : html`${c.horizontal} · ${int(n)} ${plural(n, "arkusz", "arkusze", "arkuszy")} TAK/NIE ${c.sheetsFull.length}/${c.sheetsPartial.length} · nalot ${span(c.dates)}<br />
            kampanie: ${c.campaignsSelected.length ? c.campaignsSelected.map((x, i) => html`${i ? ", " : null}<span class="nw">${x}</span>`) : "–"}${c.campaignsAll.length > c.campaignsSelected.length ? ` (w rekordach: ${c.campaignsAll.length})` : ""}
            ${cov.kind === "partial" ? html`<br />w ramkach arkuszy: ${frames}% (górna granica) · w pełnych: ${Math.floor(cov.pct)}%` : null}
            ${c.estimated ? html`<br /><i>oszacowanie mockupu dla Twojego obszaru</i>` : null}`}
    </div>
    ${pick.hints.length
      ? html`<${Cmd} text=${hintText(pick.hints)} />`
      : html`<div class="combo-meta"><i>Kartograf nie pobiera tego formatu (brak podpowiedzi pobrania).</i></div>`}
  </div>`;
}

function Timeline({ combos, groups, filter, selectedYear, onSelectYear }) {
  const numeric = combos.filter((c) => typeof c.year === "number").map((c) => c.year);
  const y0 = Math.min(...numeric);
  const y1 = Math.max(...numeric);
  const cols = [];
  for (let y = y0; y <= y1; y++) cols.push(y);
  if (combos.some((c) => c.year === "aktualne")) cols.push("aktualne");
  const rows = [...new Set(combos.map((c) => c.row))].sort((a, b) => {
    const ca = combos.find((c) => c.row === a);
    const cb = combos.find((c) => c.row === b);
    return (ca.resM ?? 1e9) - (cb.resM ?? 1e9);
  });
  const W = 372;
  const left = 70;
  const cw = (W - left - 2) / cols.length;
  const bandH = 30; // "w filtrze" band: best variant of the year
  const top = bandH + 22;
  const rh = 27;
  const axis = top + rows.length * rh + 6;
  const vcrsY = axis + 20;
  const vcrsYears = new Map();
  for (const c of combos) {
    if (!c.vcrs) continue;
    vcrsYears.set(c.year, new Set([...(vcrsYears.get(c.year) ?? []), c.vcrs]));
  }
  const H = vcrsYears.size ? vcrsY + 26 : axis + 18;
  const byYear = new Map(groups.map((g) => [g.year, g]));
  const x = (i) => left + i * cw;
  const cell = (c, xx, yy, w, h) => {
    const k = coverage(c);
    const title = `${c.year} · ${c.variant} · ${c.horizontal}\n${k.text}`;
    if (k.kind === "partial") {
      const ph = Math.max(2, (h * k.pct) / 100);
      return html`<g class="tl-cell" onClick=${() => onSelectYear(c.year)}>
        <title>${title}</title>
        <rect x=${xx} y=${yy} width=${w} height=${h} rx="3" fill="#fef3c7" stroke="#fcd34d" stroke-width="0.8" />
        <rect x=${xx} y=${yy + h - ph} width=${w} height=${ph} rx="2.5" fill=${KIND_FILL.partial} />
      </g>`;
    }
    if (k.kind === "multi") {
      return html`<g class="tl-cell" onClick=${() => onSelectYear(c.year)}>
        <title>${title}</title>
        <rect x=${xx} y=${yy} width=${w} height=${h} rx="3" fill="#5eead4" />
        <path d=${`M${xx} ${yy + h} L${xx + w} ${yy} L${xx + w} ${yy + h} Z`} fill=${KIND_FILL.multi} />
      </g>`;
    }
    return html`<rect class="tl-cell" x=${xx} y=${yy} width=${w} height=${h} rx="3" fill=${KIND_FILL[k.kind]}
      onClick=${() => onSelectYear(c.year)}><title>${title}</title></rect>`;
  };
  const everyYear = cols.length <= 12;
  return html`<svg class="timeline" viewBox=${`0 0 ${W} ${H}`}>
    ${cols.map((year, i) =>
      year === selectedYear
        ? html`<rect x=${x(i) - 1} y="0" width=${cw + 2} height=${axis + 14} rx="4" fill="#eef2ff" stroke="#a5b4fc" />`
        : null,
    )}
    <text x="0" y=${bandH / 2 + 6} font-size="11" fill="#344054" font-weight="700">w filtrze</text>
    ${cols.map((year, i) => {
      const g = byYear.get(year);
      return g?.best
        ? cell(g.best, x(i) + 1.5, 3, cw - 3, bandH - 4)
        : html`<rect x=${x(i) + 1.5} y="3" width=${cw - 3} height=${bandH - 4} rx="3" fill="none" stroke="#d0d5dd" stroke-dasharray="2 2" />`;
    })}
    <text x="0" y=${top - 8} font-size="9.5" fill="#98a2b3" font-weight="600" letter-spacing="0.6">WSZYSTKIE WARIANTY</text>
    <line x1="0" x2=${W} y1=${top - 3} y2=${top - 3} stroke="#e4e7ec" />
    ${rows.map((row, r) => {
      const yy = top + r * rh;
      const inFilter = combos.some((c) => c.row === row && matches(c, filter));
      return html`<g opacity=${inFilter ? 1 : 0.45}>
        <text x="0" y=${yy + rh / 2 + 4} font-size="11.5" fill="#344054">${row}</text>
        ${cols.map((year, i) => {
          const list = combos.filter((c) => c.row === row && c.year === year && (!filter.color || filter.color === "all" || c.color === filter.color || !c.color)).sort(rank);
          return list[0]
            ? cell(list[0], x(i) + 1.5, yy + 3, cw - 3, rh - 6)
            : html`<circle cx=${x(i) + cw / 2} cy=${yy + rh / 2} r="1.3" fill="#d0d5dd" />`;
        })}
      </g>`;
    })}
    ${cols.map((year, i) => {
      const show = everyYear || i % 2 === (cols.length - 1) % 2 || year === "aktualne" || year === selectedYear;
      return show
        ? html`<text x=${x(i) + cw / 2} y=${axis + 8} font-size="10.5" fill=${year === selectedYear ? "#3730a3" : "#667085"}
            font-weight=${year === selectedYear ? 700 : 400} text-anchor="middle">${year === "aktualne" ? "akt." : `’${String(year).slice(2)}`}</text>`
        : null;
    })}
    ${vcrsYears.size
      ? html`<g>
          ${cols.map((year, i) => {
            const set = vcrsYears.get(year);
            if (!set) return null;
            const evrf = set.has("EVRF2007");
            const kron = set.has("KRON86");
            return html`<g>
              ${evrf ? html`<rect x=${x(i) + 0.5} y=${vcrsY} width=${cw - 1} height=${kron ? 3 : 6} fill="#6366f1" />` : null}
              ${kron ? html`<rect x=${x(i) + 0.5} y=${evrf ? vcrsY + 3 : vcrsY} width=${cw - 1} height=${evrf ? 3 : 6} fill="#94a3b8" />` : null}
            </g>`;
          })}
          <text x="0" y=${vcrsY + 6} font-size="10" fill="#667085">wysokości</text>
          <rect x=${left} y=${vcrsY + 14} width="10" height="6" fill="#6366f1" />
          <text x=${left + 14} y=${vcrsY + 20} font-size="10" fill="#667085">EVRF2007</text>
          <rect x=${left + 72} y=${vcrsY + 14} width="10" height="6" fill="#94a3b8" />
          <text x=${left + 86} y=${vcrsY + 20} font-size="10" fill="#667085">KRON86</text>
        </g>`
      : null}
  </svg>`;
}

export function SummaryPanel({ fx, area, product, combos, groups, filter, tab, onTab, selectedYear, onSelectYear, onAsk, checking }) {
  if (!product || !combos) {
    return html`<div class="sum-head"><h2><${Icon} name="table" />Zestawienie</h2>
        <div class="sum-meta">Lata, pokrycie i warianty dla zaznaczonego obszaru.</div></div>
      <div class="empty">
        <svg class="art" viewBox="0 0 120 90" fill="none">
          <rect x="10" y="52" width="100" height="26" rx="5" fill="#eef2ff" stroke="#c7d2fe" />
          <rect x="18" y="34" width="84" height="24" rx="5" fill="#f0fdf4" stroke="#bbf7d0" />
          <rect x="26" y="14" width="68" height="24" rx="5" fill="#fffbeb" stroke="#fde68a" />
        </svg>
        ${checking ? "Sprawdzam dostępność…" : html`Zaznacz obszar na mapie, wybierz produkt i kliknij <b>Sprawdź dostępność</b>. Tu pojawi się zestawienie lat jako tabela i oś czasu.`}
      </div>`;
  }
  const p = PRODUCTS.find((x) => x.id === product);
  const report = fx.reports[product];
  const newestFull = groups.find((g) => g.best?.complete && typeof g.year === "number");
  const estimated = combos.some((c) => c.estimated);
  const counts = { full: 0, multi: 0, partial: 0, none: 0 };
  for (const g of groups) counts[coverage(g.best).kind]++;
  return html`
    <div class="sum-head">
      <h2><${Icon} name="table" />Zestawienie · ${p.name}</h2>
      <div class="sum-meta">
        ${area.kind === "demo" ? fx.area.name : area.kind === "rect" ? "Twój prostokąt" : "Twój wielokąt"} · ${km2(area.areaM2)}
        ${area.kind === "demo" && report.areas ? html` · ląd ${km2(report.areas[0].land_m2)}` : null}<br />
        sprawdzono ${stamp(report.checked_at)} · ${groups.length} ${plural(groups.length, "rok", "lata", "lat")}:
        ${counts.full ? html` <b style="color:#166534">${counts.full} pełne</b>` : null}${counts.multi ? html`, <b style="color:#115e59">${counts.multi} z kilku kampanii</b>` : null}${counts.partial ? html`, <b style="color:#92400e">${counts.partial} częściowe</b>` : null}${counts.none ? html`, ${counts.none} bez danych w filtrze` : null}
      </div>
      <div class="origin"><${Icon} name="info" size=${14} /><span>${ORIGINS[p.origin].map((s, i) => (i % 2 ? html`<code class="nw">${s}</code>` : s))}${estimated ? " Liczby dla Twojego obszaru: oszacowanie mockupu z ram arkuszy tego raportu." : ""}</span></div>
    </div>
    <div class="sum-tabs">
      <${Seg} small value=${tab} onChange=${onTab} options=${[
        { value: "table", label: "Tabela", icon: "table" },
        { value: "timeline", label: "Oś czasu", icon: "chart" },
      ]} />
    </div>
    <div class="sum-body">
      ${tab === "table"
        ? html`<${YearTable} groups=${groups} product=${product} selectedYear=${selectedYear} onSelectYear=${onSelectYear} filter=${filter} />`
        : html`<${Timeline} combos=${combos} groups=${groups} filter=${filter} selectedYear=${selectedYear} onSelectYear=${onSelectYear} />
            <div class="tl-legend">
              <span><i class="tl-sw full"></i>pełne</span>
              <span><i class="tl-sw multi"></i>pełne · kilka kampanii</span>
              <span><i class="tl-sw partial"></i>częściowe — słupek = % lądu w pełnych arkuszach</span>
              <span><i class="tl-sw none"></i>brak w filtrze</span>
            </div>
            <div class="tl-note">Pasek „w filtrze”: najlepszy wariant roku w aktywnym filtrze; niżej wszystkie warianty (rozdzielczość, gęstość; formaty plików jednego zestawu to jedna komórka). Kliknij komórkę, aby wybrać rok.</div>`}
      ${newestFull
        ? html`<div class="callout">
            <div class="callout-title"><${Icon} name="spark" />Najnowszy pełny rok: ${newestFull.year}</div>
            <p>${newestFull.best.variant}${product === "bdot10k" ? "" : ` · ${newestFull.best.horizontal}`} · <${Coverage} combo=${newestFull.best} /></p>
            <div class="row">
              <button class="btn sm primary" onClick=${() => onAsk(newestFull.best, "mosaic")}><${Icon} name="chat" size=${13} />Przygotuj z asystentem</button>
              <button class="btn sm" onClick=${() => onSelectYear(newestFull.year)}>Pokaż rok</button>
            </div>
          </div>`
        : null}
    </div>`;
}
