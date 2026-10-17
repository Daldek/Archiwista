// "Asystent" (simulated agent), "Zadania" popover and "Karta pliku" drawer.

import { useEffect, useRef, useState } from "preact/hooks";
import { html, Icon, Coverage, Local, Cmd, Formats } from "./ui.js";
import { coverage, span, day, stamp, int, plural, res, km2short, hintText } from "./labels.js";
import { PRODUCTS, yearGroups, inFormat } from "./data.js";

const SUGGESTIONS = [
  "Przygotuj NMT 1 m dla tego obszaru, najnowszy pełny rok, jako jedna mozaika",
  "Które lata ortofotomapy mają pełne pokrycie?",
  "Sprawdź dostępność chmur punktów LAZ",
];

/** Product, resolution row, file format, year and intent read from a message. */
export function parseRequest(text, current) {
  const t = text.toLowerCase();
  let product = current;
  if (/nmpt|pokryci[ae] teren/.test(t)) product = "nmpt";
  else if (/\blaz\b|chmur|lidar/.test(t)) product = "laz";
  else if (/orto/.test(t)) product = "orto";
  else if (/bdot/.test(t)) product = "bdot10k";
  else if (/nmt|model teren|wysoko/.test(t)) product = "nmt";
  const resMatch = t.match(/(\d+(?:[.,]\d+)?)\s*(cm|m)\b/);
  let row = null;
  if (resMatch) {
    const v = parseFloat(resMatch[1].replace(",", "."));
    row = resMatch[2] === "cm" ? `${v} cm` : res(`${v}m`);
  }
  const year = t.match(/\b(19|20)\d{2}\b/)?.[0];
  const format = t.match(/\b(ascii-nmt|asc|xyz|tbd|tin|ttn|tif|laz|gpkg|gml|shp)\b/)?.[1].toUpperCase() ?? null;
  return {
    product: product ?? "nmt",
    row,
    year: year ? +year : null,
    format,
    mosaic: /mozaik|scal|jedn[aąe]\s*(plik|warstw|mozaik)/.test(t),
    prepare: /przygotuj|pobierz|ściągnij|sciagnij|zrób|zrob/.test(t),
    which: /któr|ktor|jakie|lata|pokryci/.test(t),
    check: /sprawdź|sprawdz|dostępn|dostepn/.test(t),
  };
}

/** Result of joining the downloaded pieces (SPEC 8, done by Kartograf). */
function joinOutput(fx, pick, count, unit) {
  const crs = pick.horizontal === "PL-2000" ? "EPSG:2178" : "EPSG:2180";
  const tag = `${pick.product}_${pick.year}_mozaika${pick.resolution ? `_${pick.resolution}` : ""}`;
  if (pick.product === "laz") {
    return { step: "Scalenie chmury punktów", verb: "Scalanie chmury punktów", what: `${int(count)} ${unit} → 1 plik LAZ · ${crs} · ${pick.vcrs}`, file: `${tag}.laz`, format: "LAZ (scalona chmura)", preview: fx.area.previews.relief };
  }
  if (pick.product === "bdot10k") {
    return { step: "Scalenie pakietów", verb: "Scalanie pakietów", what: `${int(count)} ${unit} → 1 GeoPackage`, file: `${tag}.gpkg`, format: "GeoPackage (scalone powiaty)", preview: null };
  }
  const preview = pick.product === "orto" ? fx.area.previews.orto : fx.area.previews.relief;
  return { step: "Mozaika", verb: "Łączenie mozaiki", what: `${int(count)} ${unit} → 1 GeoTIFF · ${crs}${pick.vcrs ? ` · ${pick.vcrs}` : ""}`, file: `${tag}.tif`, format: "GeoTIFF (mozaika)", preview };
}

/**
 * Plan of an "prepare data" request from the availability of the area: the
 * variant (newest full year or the requested one), downloaded in the requested
 * file format or its default one. `pin` keeps the variant (format change).
 */
export function makePlan({ fx, area, product, combos, req, project, pin }) {
  const p = PRODUCTS.find((x) => x.id === product);
  const wanted = (c) =>
    (!req.row || c.row === req.row) && (product !== "orto" || c.color === "RGB") && (!req.format || c.formats.some((f) => f.format === req.format));
  const pool = combos.filter((c) => (pin ? c.id === pin : wanted(c)) && c.hints.length);
  const groups = yearGroups(pool, null);
  const variant = req.year
    ? groups.find((g) => g.year === req.year)?.best
    : groups.find((g) => g.best?.complete)?.best ?? groups[0]?.best;
  if (!variant) return null;
  const pick = inFormat(variant, req.format);
  const n = pick.sheetsFull.length + pick.sheetsPartial.length;
  const unit = product === "laz" ? plural(n, "kafel", "kafle", "kafli") : product === "bdot10k" ? plural(pick.units.length, "pakiet", "pakiety", "pakietów") : plural(n, "arkusz", "arkusze", "arkuszy");
  const count = product === "bdot10k" ? pick.units.length : n;
  const missing = count - pick.local.count;
  const report = fx.reports[product];
  const cov = coverage(pick);
  const name = `${p.name} ${pick.year} · ${req.mosaic ? "mozaika" : product === "bdot10k" ? "pakiety" : "arkusze"}${pick.resolution ? ` ${res(pick.resolution, { cm: product === "orto" })}` : ""}${!req.mosaic && pick.formats.length > 1 ? ` · ${pick.format}` : ""}`;
  const output = joinOutput(fx, pick, count, unit);
  const steps = [
    {
      t: "Dostępność",
      s: `Raport z ${stamp(report.checked_at)}: ${req.year ? `rok ${pick.year}` : "najnowszy pełny rok"} dla ${p.name}${req.row ? ` ${req.row}` : ""} = ${pick.year} (${cov.text}) · ${pick.variant} · ${pick.horizontal} · ${int(count)} ${unit}${pick.campaignsSelected.length ? ` · ${pick.campaignsSelected.join(", ")}` : ""}${pick.dates ? `, nalot ${span(pick.dates)}` : ""}.`,
      done: true,
    },
    {
      t: "Pobranie przez Kartograf",
      s: `${int(missing)} z ${int(count)} ${unit} w formacie ${pick.format} do magazynu ${fx.store.root} (w magazynie: ${pick.local.count}/${count}). Archiwista woła publiczne API Kartografa; odpowiednik CLI z podpowiedzi raportu:`,
      formats: pick.formats.length > 1,
      cmd: hintText(pick.hints, ` --output ${fx.store.root}`),
    },
  ];
  if (req.mosaic) {
    steps.push({
      t: output.step,
      s: `${output.what} · przycięcie do obszaru ${km2short(area.areaM2)}. Wykonuje Kartograf (moduł Łączenie, wymaganie SPEC 12).`,
    });
  }
  steps.push({
    t: "Wynik",
    s: `${req.mosaic ? `Warstwa „${name}” na mapie` : `${int(count)} ${unit} w magazynie`} i w projekcie „${project}”; Karta pliku z metadanymi i sidecarem.`,
  });
  return { id: `plan-${Date.now()}`, title: name, product, comboId: pick.id, combo: pick, steps, mosaic: req.mosaic, output, area, total: Math.max(1, missing), count };
}

function PlanCard({ msg, onAction, task }) {
  const plan = msg.plan;
  const status = msg.status;
  return html`<div class="plan">
    <div class="plan-head"><${Icon} name="tasks" />Plan: ${plan.title}</div>
    <ol class="plan-steps">
      ${plan.steps.map((s, i) => {
        let st = s.done ? "ok" : "";
        if (task) {
          const phase = task.phaseIndex;
          if (i < phase || task.done) st = "ok";
          else if (i === phase) st = "run";
        }
        return html`<li class=${st}>
          <div class="t">${s.t}</div>
          <div class="s">${s.s}</div>
          ${s.formats
            ? html`<div class="fmt-line" style="margin-top:6px"><span class="faint" style="font-size:11px">Format pliku${status === "proposed" ? " (kliknij, aby zmienić)" : ""}:</span>
                <${Formats} combo=${plan.combo} value=${plan.combo.format} onPick=${status === "proposed" ? (f) => onAction("format", msg, { format: f }) : undefined} /></div>`
            : null}
          ${s.cmd ? html`<${Cmd} text=${s.cmd} />` : null}
        </li>`;
      })}
    </ol>
    ${status === "proposed"
      ? html`<div class="plan-foot">
          <button class="btn sm primary" onClick=${() => onAction("run", msg)}><${Icon} name="check" size=${13} stroke=${2.4} />Zatwierdź i uruchom</button>
          <button class="btn sm" onClick=${() => onAction("edit", msg)}>Zmień rok</button>
          <button class="btn sm ghost" onClick=${() => onAction("reject", msg)}>Odrzuć</button>
        </div>`
      : html`<div class="plan-foot muted" style="font-size:11.5px">
          ${status === "rejected" ? "Odrzucono." : status === "changed" ? "Zmieniono — wybierz rok poniżej." : status === "done" ? "Wykonano." : "Uruchomiono w tle — postęp w Zadaniach."}
        </div>`}
  </div>`;
}

export function TaskCard({ task, compact }) {
  const pct = Math.round(task.progress * 100);
  return html`<div class="task-card">
    <div class="top">
      ${task.done ? html`<span style="color:#16a34a"><${Icon} name="check" stroke=${2.6} /></span>` : html`<span class="spinner"></span>`}
      <span class="name">${task.name}</span>
      <span class="muted tabular" style="margin-left:auto">${pct}%</span>
    </div>
    <div class=${`progress ${task.done ? "done" : ""}`}><i style=${`width:${pct}%`}></i></div>
    <div class="phase-txt"><span>${task.phaseText}</span>${compact ? null : html`<span class="faint">${task.eta}</span>`}</div>
  </div>`;
}

export function ChatWindow({ messages, tasks, onSend, onAction, onClose, typing }) {
  const [text, setText] = useState("");
  const log = useRef(null);
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages, typing, tasks]);
  const send = (value) => {
    const v = (value ?? text).trim();
    if (!v) return;
    setText("");
    onSend(v);
  };
  return html`<div class="chat">
    <div class="chat-head">
      <div class="bot-avatar"><${Icon} name="spark" size=${17} /></div>
      <div><div class="chat-title">Asystent Archiwisty</div><div class="chat-sub">plan → zatwierdzenie → zadanie w tle · symulacja</div></div>
      <button class="btn ghost icon-btn" style="margin-left:auto" onClick=${onClose} title="Zwiń"><${Icon} name="x" /></button>
    </div>
    <div class="chat-log" ref=${log}>
      ${messages.map((m) => {
        if (m.kind === "plan") {
          const task = tasks.find((t) => t.planId === m.plan.id);
          return html`<div class="msg bot wide"><${PlanCard} msg=${m} onAction=${onAction} task=${task} /></div>`;
        }
        if (m.kind === "task") {
          const task = tasks.find((t) => t.id === m.taskId);
          return task ? html`<div class="msg bot wide"><${TaskCard} task=${task} /></div>` : null;
        }
        if (m.kind === "suggest") {
          return html`<div class="suggest">${m.items.map((s) => html`<button onClick=${() => send(s)}>${s}</button>`)}</div>`;
        }
        if (m.kind === "actions") {
          return html`<div class="msg bot">
            <div>${m.text}</div>
            <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
              ${m.actions.map((a) => html`<button class=${`btn sm ${a.primary ? "primary" : ""}`} onClick=${() => onAction(a.id, m, a)}>${a.label}</button>`)}
            </div>
          </div>`;
        }
        return html`<div class=${`msg ${m.role}`}>${m.text}</div>`;
      })}
      ${typing ? html`<div class="msg bot"><span class="typing"><i></i><i></i><i></i></span></div>` : null}
    </div>
    <div class="chat-input">
      <textarea rows="1" placeholder="Napisz, czego potrzebujesz…" value=${text}
        onInput=${(e) => setText(e.target.value)}
        onKeyDown=${(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}></textarea>
      <button class="btn primary icon-btn" style="height:38px;width:38px" onClick=${() => send()} title="Wyślij"><${Icon} name="send" /></button>
    </div>
  </div>`;
}

export const GREETING = [
  {
    role: "bot",
    text: "Cześć! Sprawdzam dostępność danych dla zaznaczonego obszaru, przygotowuję plan pobrania i łączenia, a po Twoim zatwierdzeniu uruchamiam zadanie w tle. Spróbuj:",
  },
  { kind: "suggest", items: SUGGESTIONS },
];

export function TasksPopover({ tasks, onClose }) {
  return html`<div class="pop">
    <div class="pop-title">Zadania <button class="btn ghost sm" onClick=${onClose}><${Icon} name="x" size=${14} /></button></div>
    ${tasks.length ? tasks.map((t) => html`<${TaskCard} task=${t} />`) : html`<div class="muted" style="padding:8px 2px">Brak zadań. Zadania tworzy asystent albo przycisk „Pobierz”.</div>`}
  </div>`;
}

export function FileDrawer({ fx, item, area, onClose }) {
  const [format, setFormat] = useState(item?.combo.format);
  if (!item) return null;
  const { result } = item;
  // the card shows one file format of the variant; its badges switch it (not for a result file)
  const combo = inFormat(item.combo, format);
  const product = PRODUCTS.find((p) => p.id === combo.product);
  const n = combo.sheetsFull.length + combo.sheetsPartial.length;
  const first = [...combo.sheetsFull, ...combo.sheetsPartial][0];
  const rec = combo.sheetRecords?.[first];
  const bbox = result?.bbox ?? area?.bbox ?? fx.area.bbox;
  const preview = result ? result.image ?? result.preview : combo.product === "bdot10k" ? null : combo.product === "orto" ? fx.area.previews.orto : fx.area.previews.relief;
  const caption = result
    ? `Podgląd wyniku — ${combo.product === "orto" ? "ortofotomapa" : "cieniowanie NMT"} (GUGiK WMS), przycięty do obszaru`
    : "Podgląd poglądowy obszaru (GUGiK WMS) — w Archiwiście z pliku w magazynie";
  const vcrsCode = { EVRF2007: "EPSG:9651", KRON86: "EPSG:9650" }[combo.vcrs] ?? null;
  const sidecar = result
    ? {
        schema: "kartograf-meta/1",
        dataset: combo.source,
        country: "PL",
        product: combo.product,
        horizontal_crs: combo.horizontal === "PL-2000" ? "EPSG:2178" : "EPSG:2180",
        vertical_crs: vcrsCode,
        resolution: combo.resolution,
        request: { bbox, bbox_crs: "EPSG:2180", year: combo.year },
        extra: { mosaic_of: result.count, campaigns: combo.campaignsSelected },
      }
    : {
        schema: "kartograf-meta/1",
        dataset: combo.source,
        country: "PL",
        product: combo.product,
        horizontal_crs: combo.horizontal === "PL-2000" ? "EPSG:2178" : "EPSG:2180",
        vertical_crs: vcrsCode,
        resolution: combo.resolution,
        request: { sheet: first, year: combo.year, campaigns: "newest" },
        extra: {
          campaign: rec?.campaign ?? null,
          parent_request: { bbox, bbox_crs: "EPSG:2180" },
        },
      };
  const pieces = combo.product === "bdot10k" ? combo.units.join(", ") : `${int(n)} (TAK/NIE ${combo.sheetsFull.length}/${combo.sheetsPartial.length})`;
  return html`<div class="drawer">
    <div class="drawer-head">
      <div style="flex:1;min-width:0">
        <div class="faint" style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;font-weight:600">Karta pliku</div>
        <div style="font-weight:700;font-size:15px;margin-top:2px">${result ? result.name : `${product.name} ${combo.year} · ${combo.variant}`}</div>
        <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap"><${Coverage} combo=${combo} /><${Local} local=${result ? { count: 1, total: 1 } : combo.local} /></div>
      </div>
      <button class="btn ghost icon-btn" onClick=${onClose} title="Zamknij"><${Icon} name="x" /></button>
    </div>
    <div class="drawer-body">
      ${preview
        ? html`<div><img src=${preview} alt="podgląd" />
            <div class="faint" style="font-size:11px;margin-top:4px">${caption}</div></div>`
        : null}
      <dl class="kv" style="margin:0">
        <dt>Źródło</dt><dd><code>${combo.source}</code></dd>
        <dt>Układ</dt><dd>${combo.horizontal}${combo.vcrs ? ` · ${combo.vcrs}` : ""}</dd>
        ${combo.resolution ? html`<dt>Rozdzielczość</dt><dd>${res(combo.resolution, { cm: combo.product === "orto" })}</dd>` : null}
        ${combo.density ? html`<dt>Gęstość</dt><dd>${combo.density} pkt/m²</dd>` : null}
        <dt>Format</dt><dd>${result
          ? `${result.format} z plików ${combo.format}`
          : html`<${Formats} combo=${combo} value=${combo.format} onPick=${setFormat} />`}${combo.color ? ` · ${combo.color}` : ""}</dd>
        ${combo.dates ? html`<dt>Nalot</dt><dd>${span(combo.dates)}</dd>` : null}
        ${combo.published ? html`<dt>Publikacja</dt><dd>${span(combo.published)}</dd>` : null}
        ${combo.campaignsSelected.length ? html`<dt>Kampanie</dt><dd>${combo.campaignsSelected.join(", ")}</dd>` : null}
        <dt>${combo.product === "bdot10k" ? "Powiaty" : "Arkusze"}</dt><dd>${result ? `${result.count} → 1 plik` : pieces}</dd>
      </dl>
      <div>
        <div class="section-title" style="margin-bottom:6px">Wersje w magazynie</div>
        <div class="versions">
          ${result
            ? html`<div class="version"><${Icon} name="file" size=${14} /><span><code>projekty/krakow/${result.file}</code></span><span class="faint" style="margin-left:auto">teraz</span></div>`
            : combo.local.count
              ? html`<div class="version"><${Icon} name="file" size=${14} /><span>${combo.local.count}/${combo.local.total} ${combo.product === "bdot10k" ? "pakietów" : "arkuszy"} · wersja ${combo.year}</span><span class="faint" style="margin-left:auto">symulacja</span></div>`
              : html`<div class="muted" style="font-size:12px">Brak lokalnych wersji — dane są tylko w źródle.</div>`}
        </div>
      </div>
      <div>
        <div class="section-title" style="margin-bottom:6px">Sidecar kartograf-meta/1 (fragment, przykład)</div>
        <div class="sidecar">${JSON.stringify(sidecar, null, 2).replace(/\[\s+([^\]{}]*?)\s+\]/g, (m, inner) => `[${inner.replace(/\s+/g, " ")}]`)}</div>
      </div>
      ${combo.hints.length ? html`<div><div class="section-title" style="margin-bottom:6px">Polecenie (podpowiedź raportu)</div><${Cmd} text=${hintText(combo.hints)} /></div>` : null}
    </div>
  </div>`;
}

export { day };
