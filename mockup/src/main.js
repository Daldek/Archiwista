// Archiwista mockup: app shell, flow state and the simulated agent tasks.

import { render } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { html, Icon, Logo, Seg, Coverage, Local } from "./ui.js";
import {
  PRODUCTS,
  loadFixtures,
  forArea,
  localState,
  yearGroups,
  defaultFilter,
  filterOptions,
  areaInfo,
  insideDemo,
  phasesFor,
} from "./data.js";
import { coverage, km2, span, int, plural, stamp } from "./labels.js";
import { MapView, sheetColor, CAMPAIGN_COLORS, FULL_COLOR } from "./map.js";
import { StackView } from "./stack.js";
import { CatalogView } from "./catalog.js";
import { SummaryPanel } from "./summary.js";
import { ChatWindow, TasksPopover, FileDrawer, GREETING, parseRequest, makePlan } from "./assistant.js";

const PROJECT = "Kraków — hydrologia";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function App({ fx }) {
  const [view, setView] = useState("map");
  const [area, setArea] = useState(null);
  const [drawMode, setDrawMode] = useState(null);
  const [product, setProduct] = useState(null);
  const [checked, setChecked] = useState(null);
  const [checking, setChecking] = useState(null);
  const [filters, setFilters] = useState({});
  const [selectedYear, setSelectedYear] = useState(null);
  const [override, setOverride] = useState({});
  const [tab, setTab] = useState("table");
  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState(GREETING);
  const [typing, setTyping] = useState(false);
  const [tasks, setTasks] = useState([]);
  const [extra, setExtra] = useState([]);
  const [result, setResult] = useState(null);
  const [drawer, setDrawer] = useState(null);
  const [tasksOpen, setTasksOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const state = useRef({});
  state.current = { area, product, checked, extra };

  const outside = area && !insideDemo(fx, area);

  const combos = useMemo(() => {
    if (!checked) return null;
    return forArea(fx, checked.product, checked.area).map((c) => ({ ...c, local: localState(c, fx.store, extra) }));
  }, [checked, extra]);
  const filter = checked ? filters[checked.product] ?? defaultFilter(checked.product) : null;
  const groups = useMemo(() => (combos ? yearGroups(combos, filter) : null), [combos, filter]);
  const selGroup = groups?.find((g) => g.year === selectedYear) ?? null;
  const displayed = selGroup ? selGroup.all.find((c) => c.id === override[selectedYear]) ?? selGroup.best : null;

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), toast.ms ?? 4200);
    return () => clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    const key = (e) => e.key === "Escape" && (setDrawer(null), setTasksOpen(false));
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  /** Simulated availability check (phases of the real one), then the fixture. */
  async function runCheck(productId, areaValue = state.current.area) {
    if (!areaValue || !insideDemo(fx, areaValue)) return false;
    const phases = phasesFor(productId);
    for (let i = 0; i < phases.length; i++) {
      setChecking({ product: productId, phase: i });
      await sleep(520);
    }
    setChecking(null);
    const next = { product: productId, area: areaValue };
    setChecked(next);
    setOverride({});
    const list = forArea(fx, productId, areaValue);
    const g = yearGroups(list, filters[productId] ?? defaultFilter(productId));
    setSelectedYear(g.find((x) => x.best)?.year ?? g[0]?.year ?? null);
    return true;
  }

  function chooseProduct(id) {
    setProduct(id);
    if (state.current.checked && state.current.area && !outside) runCheck(id);
  }

  function setNewArea(ring, kind) {
    const info = areaInfo(ring, kind);
    setArea(info);
    setDrawMode(null);
    if (!insideDemo(fx, info)) {
      setChecked(null);
      setToast({ text: "Mockup ma dane tylko w ramce „zasięg danych mockupu” (Kraków 12 × 10 km). Zaznacz obszar w jej granicach albo użyj obszaru demo.", action: "demo", ms: 7000 });
      return;
    }
    if (state.current.product) runCheck(state.current.product, info);
    else setChecked(null);
  }

  function useDemo() {
    const info = { ...areaInfo(fx.area.ring4326, "demo") };
    setArea(info);
    setDrawMode(null);
    if (state.current.product) runCheck(state.current.product, info);
    return info;
  }

  function selectYear(year, toView) {
    setSelectedYear(year);
    if (toView) setView(toView);
  }

  // ---------- assistant ----------
  const say = (m) => setMessages((list) => [...list, m]);

  async function onSend(text) {
    say({ role: "user", text });
    setTyping(true);
    await sleep(750);
    const s = state.current;
    const req = parseRequest(text, s.product);
    if (!s.area) {
      setTyping(false);
      say({
        kind: "actions",
        text: "Najpierw potrzebuję obszaru: narysuj prostokąt lub wielokąt na mapie albo użyj obszaru demonstracyjnego.",
        actions: [{ id: "demo", label: "Użyj obszaru demo", primary: true, retry: text }],
      });
      return;
    }
    if (outside) {
      setTyping(false);
      say({ kind: "actions", text: "Ten obszar leży poza danymi mockupu. Użyć obszaru demonstracyjnego Kraków 12 × 10 km?", actions: [{ id: "demo", label: "Użyj obszaru demo", primary: true, retry: text }] });
      return;
    }
    if (!req.prepare && !req.which && !req.check) {
      setTyping(false);
      say({ role: "bot", text: "W tym mockupie rozumiem prośby o sprawdzenie dostępności, pytania o lata i pokrycie oraz przygotowanie danych (z mozaiką). Na przykład:" });
      say({ kind: "suggest", items: GREETING[1].items });
      return;
    }
    const fresh = !(s.checked && s.checked.product === req.product && s.checked.area === s.area);
    if (fresh) {
      setProduct(req.product);
      say({ role: "bot", text: `Sprawdzam dostępność: ${PRODUCTS.find((p) => p.id === req.product).name} dla zaznaczonego obszaru…` });
      setTyping(false);
      await runCheck(req.product, s.area);
      setTyping(true);
      await sleep(400);
    }
    const list = forArea(fx, req.product, s.area).map((c) => ({ ...c, local: localState(c, fx.store, state.current.extra) }));
    setTyping(false);
    if (req.prepare) {
      const plan = makePlan({ fx, area: s.area, product: req.product, combos: list, req, project: PROJECT });
      if (!plan) {
        say({ role: "bot", text: "Nie znalazłem wariantu, który Kartograf potrafi pobrać dla tej prośby. Zmień rozdzielczość albo rok." });
        return;
      }
      selectYear(plan.combo.year);
      if (plan.combo.id !== list.find((c) => c.year === plan.combo.year)?.id) setOverride((o) => ({ ...o, [plan.combo.year]: plan.combo.id }));
      say({ role: "bot", text: "Proponuję taki plan. Nic nie pobiorę bez Twojego zatwierdzenia." });
      say({ kind: "plan", plan, status: "proposed", req });
      return;
    }
    const groupsNow = yearGroups(list, req.row ? { rows: [req.row] } : filters[req.product] ?? defaultFilter(req.product));
    const by = (kind) => groupsNow.filter((g) => coverage(g.best).kind === kind).map((g) => g.year);
    const parts = [];
    if (by("full").length) parts.push(`pełne: ${by("full").join(", ")}`);
    if (by("multi").length) parts.push(`pełne z kilku kampanii: ${by("multi").join(", ")}`);
    if (by("partial").length) parts.push(`częściowe: ${groupsNow.filter((g) => coverage(g.best).kind === "partial").map((g) => `${g.year} (${coverage(g.best).text.replace("częściowe · ", "")})`).join(", ")}`);
    say({
      kind: "actions",
      text: `${PRODUCTS.find((p) => p.id === req.product).name}${req.row ? ` ${req.row}` : ""} w aktywnym filtrze — ${parts.join("; ") || "brak danych"}.`,
      actions: [
        { id: "timeline", label: "Pokaż oś czasu", primary: true },
        { id: "stack", label: "Pokaż stos lat" },
      ],
    });
  }

  function onAction(id, msg, a) {
    if (id === "demo") {
      const info = useDemo();
      state.current.area = info;
      if (a?.retry) setTimeout(() => onSend(a.retry), 50);
      return;
    }
    if (id === "cancel") {
      setMessages((list) => list.map((m) => (m === msg ? { ...m, status: "cancelled" } : m)));
      say({ role: "bot", text: "Anulowano — nic nie zostało pobrane." });
      return;
    }
    if (id === "edit") {
      const years = (combos ?? [])
        .filter((c) => c.complete && c.row === msg.plan.combo.row && c.hints.length && c.year !== msg.plan.combo.year && (!c.color || c.color === "RGB"))
        .map((c) => c.year)
        .filter((y, i, arr) => arr.indexOf(y) === i)
        .slice(0, 4);
      setMessages((list) => list.map((m) => (m === msg ? { ...m, status: "cancelled" } : m)));
      say({ kind: "actions", text: "Który rok przygotować zamiast tego? (pełne lata tego wariantu)", actions: years.map((y) => ({ id: "year", label: String(y), year: y, req: msg.req })) });
      return;
    }
    if (id === "year") {
      const list = (combos ?? []).filter(Boolean);
      const plan = makePlan({ fx, area, product: checked.product, combos: list, req: { ...a.req, year: a.year }, project: PROJECT });
      if (plan) {
        selectYear(plan.combo.year);
        say({ kind: "plan", plan, status: "proposed", req: { ...a.req, year: a.year } });
      }
      return;
    }
    if (id === "run") {
      setMessages((list) => list.map((m) => (m === msg ? { ...m, status: "running" } : m)));
      startTask(msg.plan);
      return;
    }
    if (id === "show-map") {
      setResult((r) => (r ? { ...r, visible: true } : r));
      selectYear(a.year, "map");
      return;
    }
    if (id === "stack") return setView("stack");
    if (id === "timeline") return setTab("timeline");
    if (id === "card") return setDrawer({ combo: a.combo, result: a.result });
  }

  function startTask(plan) {
    const combo = plan.combo;
    const members = combo.product === "bdot10k" ? combo.units : [...combo.sheetsFull, ...combo.sheetsPartial];
    const todo = members.filter((m) => !combo.local.members.has(m));
    const unit = combo.product === "bdot10k" ? "pakietów" : combo.product === "laz" ? "kafli" : "arkuszy";
    const last = plan.steps.length - 1;
    const phases = [
      { step: 1, n: Math.max(1, todo.length), ms: todo.length > 100 ? 25 : 150, text: (k) => `Pobieranie ${int(k)}/${int(todo.length)} ${unit}` },
      { step: 1, n: 4, ms: 220, text: () => "Weryfikacja SHA-256 i sidecarów" },
      ...(plan.mosaic ? [{ step: 2, n: 12, ms: 210, text: () => "Łączenie mozaiki (Kartograf)" }] : []),
      { step: last, n: 3, ms: 220, text: () => `Zapis do projektu „${PROJECT}”` },
    ];
    const weight = phases.reduce((s, p) => s + p.n * p.ms, 0);
    const id = `task-${Date.now()}`;
    const base = { product: combo.product, year: combo.year, horizontal: combo.horizontal, source: combo.source, vertical_crs: combo.vcrs, color: combo.color, resolution: combo.resolution, format: combo.format, current: combo.year === "aktualne" };
    setTasks((list) => [{ id, planId: plan.id, name: plan.title, progress: 0, phaseIndex: 1, phaseText: phases[0].text(0), eta: "start", done: false }, ...list]);
    say({ kind: "task", taskId: id });
    let pi = 0;
    let k = 0;
    let elapsed = 0;
    const tick = () => {
      const ph = phases[pi];
      k++;
      elapsed += ph.ms;
      if (pi === 0 && todo[k - 1]) {
        const got = todo.slice(0, k);
        setExtra((list) => [...list.filter((x) => x.taskId !== id), { ...base, taskId: id, sheets: combo.product === "bdot10k" ? undefined : got, units: combo.product === "bdot10k" ? got : undefined }]);
      }
      const progress = Math.min(1, elapsed / weight);
      const left = Math.max(0, Math.round((weight - elapsed) / 1000));
      if (k >= ph.n) {
        pi++;
        k = 0;
      }
      if (pi >= phases.length) {
        setTasks((list) => list.map((t) => (t.id === id ? { ...t, progress: 1, done: true, phaseIndex: last + 1, phaseText: "Zakończone", eta: "" } : t)));
        setMessages((list) => list.map((m) => (m.kind === "plan" && m.plan.id === plan.id ? { ...m, status: "done" } : m)));
        const res = plan.mosaic
          ? { visible: true, product: combo.product, comboId: combo.id, name: plan.title, year: combo.year, file: `${combo.product}_${combo.year}_mozaika${combo.resolution ? `_${combo.resolution}` : ""}.tif` }
          : null;
        if (res) setResult(res);
        setSelectedYear(combo.year);
        say({
          kind: "actions",
          text: plan.mosaic
            ? `Gotowe. ${plan.title} jest na mapie (warstwa wyniku), ${int(members.length)} ${unit} w magazynie oznaczone jako pobrane. Plik: projekty/krakow/${res.file}.`
            : `Gotowe. ${int(members.length)} ${unit} ${combo.year} jest w magazynie (pobrane).`,
          actions: [
            { id: "show-map", label: "Pokaż na mapie", primary: true, year: combo.year },
            { id: "stack", label: "Pokaż w stosie" },
            { id: "card", label: "Karta pliku", combo, result: res },
          ],
        });
        setToast({ text: `Zadanie zakończone: ${plan.title}`, ms: 3500 });
        return;
      }
      setTasks((list) => list.map((t) => (t.id === id ? { ...t, progress, phaseIndex: phases[pi].step, phaseText: phases[pi].text(pi === 0 ? k : 0), eta: `ok. ${left} s` } : t)));
      setTimeout(tick, phases[pi].ms);
    };
    setTimeout(tick, phases[0].ms);
  }

  function askFor(combo, mode) {
    setChatOpen(true);
    const p = PRODUCTS.find((x) => x.id === combo.product);
    const text =
      mode === "mosaic"
        ? `Przygotuj ${p.name}${combo.row && combo.product !== "bdot10k" ? ` ${combo.row}` : ""} dla tego obszaru, rok ${combo.year}, jako jedna mozaika`
        : `Pobierz ${p.name} ${combo.variant}, rok ${combo.year}`;
    onSend(text);
  }

  // ---------- render ----------
  const running = tasks.filter((t) => !t.done);
  const runProgress = running.length ? running.reduce((s, t) => s + t.progress, 0) / running.length : 0;
  const prodInfo = PRODUCTS.find((p) => p.id === (checked?.product ?? product));
  const opts = combos ? filterOptions(combos) : null;
  const setFilter = (patch) => setFilters((f) => ({ ...f, [checked.product]: { ...filter, ...patch } }));
  const stepArea = !area || outside ? "current" : "done";
  const stepProduct = !area || outside ? "" : product ? "done" : "current";
  const stepCheck = area && !outside && product ? (checked ? "done" : "current") : "";

  return html`<div class="app">
    <header class="topbar">
      <div class="brand"><${Logo} />Archiwista<span class="env-tag">mockup</span></div>
      <div class="crumbs">
        <span>Magazyn</span><code>${fx.store.root}</code><span class="sep">/</span>
        <span>Projekt</span><b style="color:var(--text)">${PROJECT}</b>
      </div>
      <div class="top-actions">
        <button class="btn tasks-btn" onClick=${() => setTasksOpen(!tasksOpen)}>
          ${running.length ? html`<span class="mini-ring" style=${`--p:${Math.round(runProgress * 100)}%`}></span>` : html`<${Icon} name="tasks" />`}
          Zadania ${tasks.length ? html`<span class="badge-count">${running.length || tasks.length}</span>` : null}
        </button>
        <button class=${`btn ${chatOpen ? "active" : ""}`} onClick=${() => setChatOpen(!chatOpen)}><${Icon} name="chat" />Asystent</button>
      </div>
      ${tasksOpen ? html`<${TasksPopover} tasks=${tasks} onClose=${() => setTasksOpen(false)} />` : null}
    </header>

    <nav class="rail">
      <button class=${`rail-item ${view !== "catalog" ? "active" : ""}`} onClick=${() => setView("map")}><${Icon} name="map" size=${19} />Mapa</button>
      <button class=${`rail-item ${view === "catalog" ? "active" : ""}`} disabled=${!checked} onClick=${() => setView("catalog")}><${Icon} name="grid" size=${19} />Katalog</button>
      <button class="rail-item" onClick=${() => setTasksOpen(!tasksOpen)}><${Icon} name="tasks" size=${19} />Zadania${running.length ? html`<span class="dot"></span>` : null}</button>
      <button class=${`rail-item ${chatOpen ? "active" : ""}`} onClick=${() => setChatOpen(!chatOpen)}><${Icon} name="chat" size=${19} />Asystent</button>
      <div class="rail-sep"></div>
      <button class="rail-item" disabled title="Poza zakresem mockupu"><${Icon} name="layers" size=${19} />Magazyn</button>
      <button class="rail-item" disabled title="Poza zakresem mockupu"><${Icon} name="folder" size=${19} />Projekty</button>
      <button class="rail-item" disabled title="Poza zakresem mockupu"><${Icon} name="merge" size=${19} />Łączenie</button>
      <button class="rail-item" disabled title="Poza zakresem mockupu" style="margin-top:auto"><${Icon} name="settings" size=${19} />Ustaw.</button>
    </nav>

    <aside class="left">
      <div class=${`step ${stepArea}`}>
        <div class="step-head"><span class="step-num">${stepArea === "done" ? html`<${Icon} name="check" size=${12} stroke=${3} />` : 1}</span>
          <span class="step-title">Obszar</span>
          ${area ? html`<button class="btn ghost sm step-aside" onClick=${() => { setArea(null); setChecked(null); }}>Wyczyść</button>` : null}
        </div>
        <div class="tool-row">
          <button class=${`btn ${drawMode === "rect" ? "active" : ""}`} onClick=${() => setDrawMode(drawMode === "rect" ? null : "rect")}><${Icon} name="rect" />Prostokąt</button>
          <button class=${`btn ${drawMode === "poly" ? "active" : ""}`} onClick=${() => setDrawMode(drawMode === "poly" ? null : "poly")}><${Icon} name="poly" />Wielokąt</button>
        </div>
        <button class="btn demo-btn" onClick=${useDemo}><${Icon} name="pin" />Obszar demo: ${fx.area.name.split(" — ")[0]} 12 × 10 km</button>
        ${area
          ? html`<div class="area-card" style="margin-top:9px">
              <div class="big">${area.kind === "demo" ? fx.area.name : area.kind === "rect" ? "Prostokąt" : `Wielokąt · ${area.ring4326.length} wierzchołków`}</div>
              <div class="muted tabular">${(area.width / 1000).toFixed(1).replace(".", ",")} × ${(area.height / 1000).toFixed(1).replace(".", ",")} km · ${km2(area.areaM2)}</div>
              <div class="bbox mono">--bbox ${area.bbox.join(",")}</div>
            </div>`
          : html`<div class="hint">Narysuj obszar na mapie albo użyj obszaru demonstracyjnego (prawdziwe raporty Kartografa).</div>`}
        ${outside ? html`<div class="hint warn">Obszar wychodzi poza ramkę danych mockupu — wyniki są tylko dla obszaru demo i jego wnętrza.</div>` : null}
      </div>

      <div class=${`step ${stepProduct}`}>
        <div class="step-head"><span class="step-num">${stepProduct === "done" ? html`<${Icon} name="check" size=${12} stroke=${3} />` : 2}</span><span class="step-title">Produkt</span></div>
        ${["Wysokości", "Obrazy", "Pokrycie terenu"].map(
          (group) => html`<div class="prod-group">
            <div class="prod-group-title">${group}</div>
            ${PRODUCTS.filter((p) => p.group === group).map(
              (p) => html`<button class=${`prod ${product === p.id ? "on" : ""}`} onClick=${() => chooseProduct(p.id)}>
                <span class="prod-icon" style=${`background:${p.color}`}>${p.name.slice(0, 4).toUpperCase()}</span>
                <span><div class="prod-name">${p.name}</div><div class="prod-sub">${p.sub}</div></span>
                <span class=${`src-tag ${p.origin === "report" ? "report" : ""}`} title=${p.origin === "report" ? "Raport dostępności Kartografa" : "Zestawienie skryptem mockupu"}>${p.origin === "report" ? "raport" : p.origin === "index" ? "skorowidz" : "pakiety"}</span>
              </button>`,
            )}
          </div>`,
        )}
      </div>

      <div class=${`step ${stepCheck}`}>
        <div class="step-head"><span class="step-num">${stepCheck === "done" ? html`<${Icon} name="check" size=${12} stroke=${3} />` : 3}</span><span class="step-title">Dostępność</span></div>
        ${checking
          ? html`<div class="phases">
              ${phasesFor(checking.product).map(
                (ph, i) => html`<div class=${`phase ${i < checking.phase ? "ok" : i === checking.phase ? "run" : ""}`}>
                  <span class="ic">${i < checking.phase ? html`<span style="color:#16a34a"><${Icon} name="check" size=${14} stroke=${2.6} /></span>` : i === checking.phase ? html`<span class="spinner"></span>` : html`<span style="width:6px;height:6px;border-radius:50%;background:#d0d5dd"></span>`}</span>
                  ${ph}
                </div>`,
              )}
            </div>`
          : checked
            ? html`<div class="muted" style="line-height:1.5">${combos.length} ${plural(combos.length, "kombinacja", "kombinacje", "kombinacji")} · ${groups.length} ${plural(groups.length, "rok", "lata", "lat")}<br />sprawdzono ${stamp(fx.reports[checked.product].checked_at)}</div>
                <button class="btn sm" style="margin-top:8px" onClick=${() => runCheck(checked.product)}><${Icon} name="rotate" size=${13} />Sprawdź ponownie</button>`
            : html`<button class="btn primary block" disabled=${!area || outside || !product} onClick=${() => runCheck(product)}>Sprawdź dostępność</button>
                <div class="hint">Bez pobierania danych: skorowidz źródła, maska lądu i pomiar pokrycia (jak <code>kartograf elevation availability</code>).</div>`}
      </div>

      ${checked && view !== "catalog"
        ? html`<div>
            <div class="layers-head"><span class="section-title">Warstwy na mapie · lata</span><span class="faint" style="font-size:11px">${prodInfo.name}</span></div>
            ${result
              ? html`<div class="layer result-layer">
                  <div class="layer-row" onClick=${() => setResult({ ...result, visible: !result.visible })}>
                    <span style=${`color:${result.visible ? "#1d4ed8" : "#98a2b3"}`}><${Icon} name="eye" /></span>
                    <span style="font-weight:600;flex:1">${result.name}</span><span class="local done">wynik</span>
                  </div>
                </div>`
              : null}
            ${groups.map((g) => {
              const sel = g.year === selectedYear;
              const c = sel ? displayed : g.best;
              return html`<div class=${`layer ${sel ? "on" : ""}`}>
                <div class="layer-row" onClick=${() => selectYear(g.year)}>
                  <span class="layer-year">${g.year}</span>
                  <${Coverage} combo=${c} />
                  <span style="margin-left:auto">${c ? html`<${Local} local=${c.local} />` : null}</span>
                </div>
                ${sel && c
                  ? html`<div class="layer-body">
                      <dl class="kv">
                        <dt>Wariant</dt><dd>${c.variant}</dd>
                        ${checked.product !== "bdot10k" ? html`<dt>Układ arkuszy</dt><dd>${c.horizontal}</dd><dt>Nalot</dt><dd>${span(c.dates)}</dd>` : html`<dt>Powiaty</dt><dd>${c.units.join(", ")}</dd>`}
                      </dl>
                      ${checked.product !== "bdot10k"
                        ? html`<div class="swatches">
                            ${c.campaignsSelected.length > 1
                              ? c.campaignsSelected.map((camp, i) => {
                                  const nS = c.sheetsFull.filter((s) => c.sheetRecords?.[s]?.campaign === camp).length;
                                  return html`<div class="swatch-row"><span class="sw" style=${`background:${CAMPAIGN_COLORS[i % 4]}`}></span><code>${camp}</code><span class="faint">${nS} ark.</span></div>`;
                                })
                              : html`<div class="swatch-row"><span class="sw" style=${`background:${FULL_COLOR}`}></span><code>${c.campaignsSelected[0] ?? "–"}</code><span class="faint">${c.sheetsFull.length} ark.</span></div>`}
                            ${c.sheetsPartial.length ? html`<div class="swatch-row"><span class="sw hatch"></span>niepełne: ${c.sheetsPartial.slice(0, 3).join(", ")}</div>` : null}
                          </div>`
                        : null}
                      ${g.matching.length > 1
                        ? html`<div class="variant-pick">
                            <div class="faint" style="font-size:11px">Wariant na mapie (${g.matching.length} w filtrze):</div>
                            ${g.matching.map(
                              (v) => html`<button class=${`variant-opt ${v.id === c.id ? "on" : ""}`} onClick=${() => setOverride((o) => ({ ...o, [g.year]: v.id }))}>
                                <span style="flex:1">${v.variant} · ${v.horizontal}</span><${Coverage} combo=${v} />
                              </button>`,
                            )}
                          </div>`
                        : null}
                      <div style="display:flex;gap:6px;margin-top:9px">
                        <button class="btn sm" onClick=${() => setDrawer({ combo: c })}><${Icon} name="file" size=${13} />Karta</button>
                        <button class="btn sm" disabled=${!c.hints.length} onClick=${() => askFor(c, "download")}><${Icon} name="download" size=${13} />Pobierz</button>
                      </div>
                    </div>`
                  : null}
              </div>`;
            })}
          </div>`
        : null}
    </aside>

    <main class="center">
      <div class="center-bar">
        <${Seg} value=${view} onChange=${setView} options=${[
          { value: "map", label: "Mapa", icon: "map" },
          { value: "stack", label: "Stos", icon: "stack", disabled: !checked, title: "Widok izometryczny warstw lat" },
          { value: "catalog", label: "Katalog", icon: "grid", disabled: !checked, title: "Cały zestaw" },
        ]} />
        ${checked && opts
          ? html`<div class="filter-bar">
              <div class="filter-group">
                <span class="filter-label">${checked.product === "laz" ? "Gęstość" : checked.product === "bdot10k" ? "Format" : checked.product === "orto" ? "Piksel" : "Rozdzielczość"}</span>
                <button class=${`chip ${!filter.rows?.length ? "on" : ""}`} onClick=${() => setFilter({ rows: [] })}>wszystkie</button>
                ${opts.rows.map(
                  (r) => html`<button class=${`chip ${filter.rows?.includes(r) ? "on" : ""}`}
                    onClick=${() => setFilter({ rows: filter.rows?.includes(r) ? filter.rows.filter((x) => x !== r) : [...(filter.rows ?? []), r] })}>${r}</button>`,
                )}
              </div>
              ${opts.vcrs.length > 1
                ? html`<div class="filter-group"><span class="filter-label">Wysokości</span>
                    <${Seg} small value=${filter.vcrs ?? "all"} onChange=${(v) => setFilter({ vcrs: v })}
                      options=${[{ value: "all", label: "oba" }, ...opts.vcrs.map((v) => ({ value: v, label: v }))]} /></div>`
                : null}
              ${opts.colors.length > 1
                ? html`<div class="filter-group"><span class="filter-label">Kolor</span>
                    <${Seg} small value=${filter.color ?? "all"} onChange=${(v) => setFilter({ color: v })}
                      options=${[{ value: "all", label: "wszystkie" }, ...opts.colors.map((v) => ({ value: v, label: v }))]} /></div>`
                : null}
              ${opts.horizontals.length > 1
                ? html`<div class="filter-group"><span class="filter-label">Układ arkuszy</span>
                    <${Seg} small value=${filter.horizontal ?? "all"} onChange=${(v) => setFilter({ horizontal: v })}
                      options=${[{ value: "all", label: "dowolny" }, ...opts.horizontals.map((v) => ({ value: v, label: v }))]} /></div>`
                : null}
            </div>`
          : html`<span class="muted" style="font-size:12px">${area ? (product ? "Kliknij „Sprawdź dostępność”." : "Wybierz produkt.") : "Zaznacz obszar, wybierz produkt i sprawdź dostępność — potem przełącz widok: Mapa · Stos · Katalog."}</span>`}
      </div>
      <div class="center-body">
        <${MapView} fx=${fx} area=${area} drawMode=${drawMode} onDrawn=${setNewArea} onCancelDraw=${() => setDrawMode(null)}
          product=${checked?.product} combo=${checked ? displayed : null} yearLabel=${true} result=${result}
          visible=${view === "map"} onSheetClick=${() => displayed && setDrawer({ combo: displayed })} />
        ${checked
          ? html`<${StackView} fx=${fx} area=${checked.area} product=${checked.product} groups=${groups}
              selectedYear=${selectedYear} onSelectYear=${(y) => selectYear(y)} result=${result} visible=${view === "stack"} />
            <${CatalogView} fx=${fx} area=${checked.area} product=${checked.product} combos=${combos} filter=${filter}
              selectedYear=${selectedYear} onSelectYear=${selectYear} onOpen=${(c) => setDrawer({ combo: c })}
              onAsk=${(c) => askFor(c, "download")} visible=${view === "catalog"} />`
          : null}
        ${toast
          ? html`<div class="toast float-card"><${Icon} name="info" /><span>${toast.text}</span>
              ${toast.action === "demo" ? html`<button class="btn sm primary" onClick=${() => { useDemo(); setToast(null); }}>Użyj obszaru demo</button>` : null}</div>`
          : null}
        ${chatOpen
          ? html`<${ChatWindow} messages=${messages} tasks=${tasks} onSend=${onSend} onAction=${onAction} onClose=${() => setChatOpen(false)} typing=${typing} />`
          : html`<button class="chat-fab" onClick=${() => setChatOpen(true)}><${Icon} name="spark" size=${18} />Asystent${running.length ? html`<span class="mini-ring" style=${`--p:${Math.round(runProgress * 100)}%`}></span>` : null}</button>`}
      </div>
    </main>

    <aside class="right" style="position:relative">
      <${SummaryPanel} fx=${fx} area=${checked?.area} product=${checked?.product} combos=${combos} groups=${groups} filter=${filter}
        tab=${tab} onTab=${setTab} selectedYear=${selectedYear} onSelectYear=${(y) => selectYear(y)}
        onAsk=${(c, mode) => askFor(c, mode)} checking=${checking} />
      <${FileDrawer} fx=${fx} item=${drawer} onClose=${() => setDrawer(null)} />
    </aside>
  </div>`;
}

loadFixtures()
  .then((fx) => render(html`<${App} fx=${fx} />`, document.getElementById("app")))
  .catch((error) => {
    document.getElementById("app").innerHTML = `<div class="boot">Nie udało się wczytać danych mockupu (${error.message}). Uruchom serwer HTTP w katalogu mockup/ — patrz README.md.</div>`;
    console.error(error);
  });
