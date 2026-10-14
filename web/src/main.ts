import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import { type Data, type Row, LEVELS, basisLabel, chain, cover, coverage, inFocus, parse, priceFactor, rescale, standIn, valueOf } from "./data/data";
import { type Bounds, search } from "./data/places";
import { createFrame } from "./frame";
import { createMap } from "./map/map";
import { COMPASS, NORTH, type Rect, capture, compose, cropRect, exportRatio, fileName, idle, subtitle, turned } from "./export";
import { type Meta, type View, boxMask, domainOf, excessDomain, landAt, masked, ringMask, smoother, toPixel, valueAt } from "./map/smooth";
import { BASE_YEARS, DIVERGING, INDICATORS, type Indicator, KERNELS, RADII, SMOOTH, breaks, domain, fmtValue, manual, parseAmount, seaFor, times, paletteIds, paletteLabel, weightKey, wider } from "./scales/scales";
import { current, resolve, setTheme } from "./theme";
import { startTracking } from "./track";
import { type State, clean, fromHash, smoothColours, smoothIndicator, toHash } from "./state/state";
import { $, type Source, chipsHtml, accordion, foldCard, coverageLine, creditsHtml, NOTES, legendHtml, legendModel, panelHtml, resultsHtml, smoothTipHtml, stripHtml, tipHtml, tipPos } from "./ui/ui";

/** The text, tooltip and accessible name of a round button (its label is hidden on a phone). */
const label = (b: HTMLElement, t: string) => { b.querySelector("span")!.textContent = b.title = t; b.setAttribute("aria-label", t); };
const json = (f: string) => fetch(new URL(f, location.href)).then((r) => r.json());

async function main() {
  const [data, sources, meta]: [Data, Source[], Meta | null] = await Promise.all([json("indicators.json").then(parse), json("sources.json"), json("smooth/smooth.json").catch(() => null)]); // without smoothed data the app still starts
  const byId = new Map(sources.map((s) => [s.source_id, s]));
  /** A state the data can show: no Smoothed without `smooth.json`, only known focus ids and selection; the level shows the focus' rows. */
  const fit = (s: State) => {
    const t = clean({ ...s, smooth: s.smooth && !!meta, sel: data.rows.has(s.sel!) ? s.sel : null, focus: s.focus.filter((id) => data.rows.has(id)) });
    return { ...t, level: Math.max(t.level, ...t.focus.map((id) => data.rows.get(id)!.level_no)) };
  };
  let state: State = fit(fromHash(location.hash, INDICATORS.map((i) => i.key), BASE_YEARS));
  const linked = data.rows.get(state.sel!); // a linked selection that the level does not show opens at its own level
  if (linked && !cover(data, state.level).includes(linked)) state.level = linked.level_no;
  /** The page and the map colours follow the chosen theme; "auto" the system's. */
  const themed = () => { const name = resolve(state.theme); setTheme(name); document.documentElement.dataset.theme = name; };
  themed();
  let shown: Row[] = []; // the regions on the map: the cover of the chosen level, restricted to the focus if there is one
  let all: Row[] = [], limited = false, seen: Set<string> | null = null; // the whole cover; is a focus restricting the map; the regions in view (Scale: View, regions view)

  let view: View | null = null, full: View | null = null; // the smoothed surface shown, if Smoothed is on (cut to the focus), and the whole of it
  const surface = meta && smoother(meta);
  /** The indicator as shown; smoothed, its label and unit say how it was derived. */
  const ind = (): Indicator => {
    const i = INDICATORS.find((x) => x.key === state.ind)!;
    if (!state.smooth) return i;
    return { ...i, label: `${i.label}, smoothed (${KERNELS[state.kernel].toLowerCase()}, ${state.radius} km), derived`, unit: i.key !== "gdp_per_capita" && sea() ? i.unit + " incl. sea" : i.unit };
  };
  /** Include sea as it applies to the indicator (off for per capita). */
  const sea = () => seaFor(state.ind, state.sea);
  /** What the colours show: the indicator, or with Local excess the surface as a multiple of its wider Gaussian surroundings. */
  const wide = () => (state.local ? wider(state.radius) : 0);
  const shade = (): Indicator => view?.ex
    ? { key: "excess", label: `${INDICATORS.find((i) => i.key === state.ind)!.label} (${KERNELS[state.kernel].toLowerCase()}, ${state.radius} km) against its surroundings (Gaussian, ${wide()} km), derived`, unit: "x times its surroundings", money: false, fmt: times }
    : ind();
  const factor = () => priceFactor(data, state.base);
  const value = (r: Row, estimates = state.estimates) => valueOf(standIn(data, r, estimates), ind().key, estimates, factor());
  /** The row a region stands for (with Estimates off a derived region is its country). */
  const shownRow = (id: string | null | undefined) => { const r = data.rows.get(id!); return r && standIn(data, r, state.estimates); };
  /** Colour domain and class breaks; they ignore the estimates toggle, so they do not shift when it is flipped. The smoothed
   * surface has its own domain, over the world or (Scale: View) over the part of it in view. */
  function scale(): { dom: [number, number]; brk: number[] | null } {
    if (view) {
      const c = view.ex ?? view, b = map.getBounds(), box = [...toPixel(c, b.getWest(), b.getNorth()), ...toPixel(c, b.getEast(), b.getSouth())];
      const auto = state.scale === "view" ? (view.ex ? excessDomain : domainOf)(c, box) : state.scale === "world" ? (full!.ex ?? full!).dom : c.dom; // cut to a focus, c.dom and domainOf follow it
      const dom = manual(auto, state.cmin, state.cmax);
      return { dom, brk: state.classes ? breaks(state.classes, "log", dom, []) : null };
    }
    const w = weightKey(ind());
    const items = (state.scale === "world" ? all : seen ? shown.filter((r) => seen!.has(r.id)) : shown).flatMap((r): [number, number][] => { const v = value(r, true); return v === undefined ? [] : [[v, r[w] ?? 0]]; });
    const dom = manual(domain(items.map(([v]) => v)), state.cmin, state.cmax);
    return { dom, brk: state.classes ? breaks(state.classes, state.rule, dom, items) : null };
  }
  let ticks = 0;
  const options = (el: HTMLSelectElement, items: [string | number, string][]) =>
    (el.innerHTML = items.map(([v, label]) => `<option value="${v}">${label}</option>`).join(""));
  const [select, base, level, pal, cls, rule, sk, sr, theme, pal2, cls2] = ["ind", "base", "level", "pal", "cls", "brk", "sk", "sr", "theme", "pal2", "cls2"].map((id) => $<HTMLSelectElement>(id));
  /** Show lists all five indicators; Smoothed offers the three that have a surface. */
  let listed = "";
  const showList = () => { const items = INDICATORS.filter((i) => !state.smooth || SMOOTH[i.key]), keys = items.map((i) => i.key).join(); if (keys !== listed) { listed = keys; options(select, items.map((i) => [i.key, i.label])); } };
  options(base, [["", "current US$"], ...BASE_YEARS.map((y): [number, string] => [y, basisLabel(y)])]);
  for (const el of [cls, cls2]) options(el, [[0, "Gradient"], ...[3, 4, 5, 6, 7].map((n): [number, string] => [n, `${n} classes`])]);
  /** Each select and the state field it sets (and `render` reads back). */
  const selects: [HTMLSelectElement, keyof State, (v: string) => unknown][] = [[select, "ind", String], [level, "level", Number], [pal, "palette", (v) => (v === paletteIds(resolve(state.theme))[0] ? "" : v)], [cls, "classes", Number], [rule, "rule", String], [pal2, "palette", (v) => (v === paletteIds(resolve(state.theme))[0] ? "" : v)], [cls2, "classes", Number],
    [sk, "kernel", String], [sr, "radius", Number], [base, "base", (v) => (v ? Number(v) : null)], [theme, "theme", String]];
  options(sk, (meta?.kernels ?? []).map((k) => [k, KERNELS[k] ?? k]));
  options(sr, RADII.map((r): [number, string] => [r, `${r} km`]));
  options(level, LEVELS.map((l, i) => [i, l.replace(/y$/, "ie") + "s"]));
  /** Checkboxes and the state flag each one sets. */
  const checks = ([["ss", "sea"], ["lx", "local"], ["est", "estimates"], ["borders", "borders"], ["globe", "globe"], ["relief", "relief"]] as const)
    .map(([id, key]) => [$<HTMLInputElement>(id), key] as const);

  $<HTMLInputElement>("smooth").disabled = !meta;
  const cam = createMap($("map"), state, {
    hover(id, x, y, at) {
      const tip = $("tip"), row = shownRow(id), v = view && at ? valueAt(view, ...at) : undefined, ex = view?.ex && at ? valueAt(view.ex, ...at) : undefined;
      tip.hidden = view ? v === undefined : !row;
      if (tip.hidden) return;
      tip.innerHTML = view ? smoothTipHtml(v!, ind(), state.radius, row, ex, wide(), view && at ? landAt(view, ...at) : undefined) : tipHtml(rescale(row!, factor()), ind(), data.ref, state.base);
      const [tx, ty] = tipPos(x, y, tip.offsetWidth, tip.offsetHeight, innerWidth, innerHeight);
      tip.style.transform = `translate(${tx}px,${ty}px)`;
    },
    pick: (sel) => update({ sel }),
    camera: (c) => update({ cam: c }),
  });
  const { map, ready, apply } = cam;
  const editor = createFrame(map, {
    done: (b, exporting) => { setBox(b).then(() => { if (exporting) openExport(); }); },
    count: async (b) => [...await cam.meet(b)].filter((id) => data.rows.get(id)?.level_no === 3).length,
    fit: (b) => { cam.frame(b, 0.04); return new Promise((res) => map.once("moveend", () => res())); },
  });

  /** Select a region from a list or the breadcrumb: the map switches to the region's own level if it is not shown. */
  function go(row: Row) {
    if (!inFocus(data, row, new Set(state.focus))) return; // outside the focus
    const lvl = shown.includes(row) ? state.level : row.level_no;
    update({ sel: row.id, level: lvl });
    cam.fit([[row.id, lvl]]);
  }

  function drawPanel() {
    const panel = $("panel"), row = shownRow(state.sel);
    panel.hidden = !row;
    if (panel.hidden) return;
    panel.innerHTML = panelHtml(rescale(row!, factor()), chain(data, row!.id).slice(0, -1), row!.level_no < state.level, data, byId, state.base, state.focus);
    panel.querySelector<HTMLElement>(".x")!.onclick = () => update({ sel: null });
    const fo = panel.querySelector<HTMLElement>(".fo");
    if (fo) fo.onclick = () => toggleFocus(row!.id);
    foldCard(panel);
    panel.querySelector<HTMLElement>(".crumbs")!.onclick = (e) => {
      const up = data.rows.get((e.target as HTMLElement).dataset.id!);
      if (up) go(up);
    };
  }

  const focused = () => state.focus.length > 0 || !!state.box;
  /** The regions meeting the focus box (see `places.meeting`), cached per box. */
  let met: { key: string; ids: Set<string> } | undefined;
  const meeting = async () => {
    if (!state.box) return null;
    const key = state.box.join();
    return (met?.key === key ? met : (met = { key, ids: await cam.meet(state.box) })).ids;
  };
  /** The surface cut to the focus (mask of the box, or of the focus regions' polygons); kept while the focus and the surface stay. */
  let mask: { key: string; m: Uint8Array } | undefined, cutOf: { src: View; key: string; out: View } | undefined;
  async function cutTo(v: View) {
    const key = state.box ? "b" + state.box.join() : "f" + state.focus.join(), mk = `${key}|${v.w}x${v.h}|${v.north}`;
    if (cutOf?.src === v && cutOf.key === key) return cutOf.out;
    if (mask?.key !== mk) mask = { key: mk, m: state.box ? boxMask(v, state.box) : ringMask(v, await cam.shapes(state.focus.map((id) => [id, data.rows.get(id)!.level_no]))) };
    const out = masked(v, mask.m);
    cutOf = { src: v, key, out };
    return out;
  }

  /** The regions meeting the map view (for Scale: View). */
  const onScreen = async () => { const b = map.getBounds(); return cam.meet([Math.max(-180, b.getWest()), Math.max(-85, b.getSouth()), Math.min(180, b.getEast()), Math.min(85, b.getNorth())]); };
  let follow = 0, rendered: Promise<void> = Promise.resolve(); // the latest render, for the export to wait for
  const render = () => (rendered = paint());
  async function paint() {
    const ticket = ++ticks;
    const [next, ids] = await Promise.all([state.smooth ? surface!(state.ind, state.kernel, state.radius, sea(), ind().money ? factor() : 1, wide()) : null, meeting()]);
    seen = state.scale === "view" && !state.smooth ? await onScreen() : null;
    const cut = next && focused() ? await cutTo(next) : next;
    if (ticket !== ticks) return; // a newer render has started
    [full, view] = [next, cut];
    themed();
    all = cover(data, state.level);
    const fset = new Set(state.focus);
    limited = focused();
    shown = limited ? all.filter((r) => (ids ? ids.has(r.id) : inFocus(data, r, fset))) : all;
    const limit = limited ? { ids: shown.map((r) => r.id), countries: [...new Set(shown.flatMap((r) => chain(data, r.id).filter((a) => a.level_no === 1).map((a) => a.id)))] } : null;
    $("focus").hidden = !limited;
    cam.overseasOf(state.focus.filter((id) => data.rows.get(id)!.level_no === 1)).then((o) => { // a focused country with parts beyond the mainland: the button toggles the camera between the two views
      $("overseas").hidden = !o.length;
      $("overseas").textContent = state.overseas ? "Mainland view" : "Show overseas";
    });
    $("chips").innerHTML = chipsHtml(state.focus.map((id) => data.rows.get(id)!), !!state.box);
    label($("area"), state.box ? "Edit area" : "Focus area");
    options(rule, [["log", "Equal log steps"], ["share", `Equal share of ${ind().money ? "GDP" : "people"}`]]);
    const pals = paletteIds(resolve(state.theme));
    for (const el of [pal, pal2]) options(el, pals.map((p): [string, string] => [p, paletteLabel(p)]));
    showList();
    for (const [el, key] of selects) el.value = String(state[key] ?? "");
    pal.value = pal2.value = pals.includes(state.palette) ? state.palette : pals[0];
    select.value = ind().key;
    const so = $<HTMLDetailsElement>("smopts");
    if (so.hidden && state.smooth) so.open = false; // collapsed each time it appears
    so.hidden = !state.smooth;
    $<HTMLSelectElement>("base").disabled = !ind().money;
    pal.disabled = pal2.disabled = !!view?.ex;
    $<HTMLInputElement>("smooth").checked = state.smooth;
    $<HTMLInputElement>("mode-r").checked = !state.smooth;
    $("brklbl").hidden = !state.classes || state.smooth;
    for (const [el, key] of checks) el.checked = state[key];
    const ss = $<HTMLInputElement>("ss");
    ss.checked = sea();
    ss.disabled = SMOOTH[state.ind]?.sea === false;
    const lx = $<HTMLInputElement>("lx");
    lx.disabled = !wider(state.radius) || !meta?.kernels.includes("gauss");
    lx.parentElement!.title = wider(state.radius) ? `against the Gaussian surroundings within ${wider(state.radius)} km` : "needs a wider radius";
    $("cover").textContent = coverageLine(coverage(data, shown, state.estimates));
    const { dom, brk } = scale(), sh = shade(), zoned = state.estimates && (seen ? shown.filter((r) => seen!.has(r.id)) : shown).some((r) => r.flags.includes("pop_share")), note = state.smooth ? (state.ind === "gdp_per_capita" ? NOTES.pcap : "") : zoned ? NOTES.derived : "";
    $("lg").innerHTML = legendHtml(sh, dom, state.base, view?.ex ? DIVERGING : state.palette, brk, limited && !!view, !!view && sea(), note, $("lg").clientWidth || undefined);
    $("seg").innerHTML = [["auto", "Auto"], ["world", "World"], ["view", "View"]].map(([k, t]) => `<button type="button" data-s="${k}" aria-pressed="${state.scale === k}"${k === "world" && !limited ? ' disabled title="needs a focus"' : ""}>${t}</button>`).join("");
    const sum = (id: string, text: string) => ($(id).querySelector("summary small")!.textContent = text);
    sum("sc", [state.classes ? `${state.classes} classes` : "gradient", paletteLabel(pal.value), state.cmin != null || state.cmax != null ? "manual range" : ""].filter(Boolean).join(", "));
    sum("sd", [level.selectedOptions[0].text, ind().money ? base.selectedOptions[0].text : "", state.estimates ? "" : "no estimates"].filter(Boolean).join(", "));
    sum("sa", theme.selectedOptions[0].text);
    $("strip").innerHTML = stripHtml(sh, dom, state.base, view?.ex ? DIVERGING : state.palette, brk);
    for (const [id, x, e] of [["cmin", state.cmin, dom[0]], ["cmax", state.cmax, Math.min(dom[1], sh.max ?? dom[1])]] as const) {
      const el = $<HTMLInputElement>(id);
      [el.value, el.placeholder] = [x == null ? "" : fmtValue(10 ** x, sh), fmtValue(10 ** e, sh)];
    }
    drawPanel();
    apply(state, dom, brk, shown, value, view, limit);
  }
  /** Hide/Show panels: the class hides the cards (CSS), the map stays. */
  function showUi() {
    document.body.classList.toggle("noui", !state.ui);
    label($("ui-btn"), state.ui ? "Hide panels" : "Show panels");
    $("credits-link").hidden = state.ui;
  }
  function update(patch: Partial<State>) {
    state = fit({ ...state, ...patch, ...(patch.box ? { focus: [] } : patch.focus?.length ? { box: null } : {}) }); // a box and a focus exclude each other
    history.replaceState(null, "", "#" + toHash(state));
    if (patch.globe || patch.relief) editor.close(); // a frame needs the flat map
    if ("ui" in patch) showUi();
    if (!("cam" in patch || "ui" in patch)) render();
    else if ("cam" in patch && state.scale === "view") { clearTimeout(follow); follow = window.setTimeout(render, 150); } // the View scale follows the camera
  }

  for (const [el, key, parse] of selects) el.onchange = () => update({ [key]: parse(el.value) });
  /** A new level keeps the selection if it is shown there, else moves it to its ancestor that is. */
  level.onchange = () => {
    const lvl = Number(level.value), rows = cover(data, lvl);
    update({ level: lvl, sel: chain(data, state.sel ?? "").findLast((r) => rows.includes(r))?.id ?? null });
  };
  /** Set the focus: the level goes to the finest on entering it, the selection is dropped if it is outside, the camera fits the rows. */
  function setFocus(ids: string[]) {
    const focus = [...new Set(ids)].sort(), fs = new Set(focus), sel = data.rows.get(state.sel!);
    update({ focus, box: null, ...(focus.length ? {} : { overseas: false }), sel: !focus.length || (sel && inFocus(data, sel, fs)) ? state.sel : null, ...(focus.length && !focused() ? { level: 3 } : {}) });
    if (focus.length) fitFocus();
  }
  /** Focus on a drawn rectangle: the selection is dropped if it lies outside, the level goes to the finest on entering. */
  async function setBox(box: Bounds) {
    const ids = await cam.meet(box), enter = !focused();
    update({ box, sel: state.sel && ids.has(state.sel) ? state.sel : null, ...(enter ? { level: 3 } : {}) });
    fitFocus();
  }
  const fitFocus = () => (state.box ? cam.frame(state.box, 0.04) : cam.fit(state.focus.map((id) => [id, data.rows.get(id)!.level_no]), 0.04, state.overseas));
  $("overseas").onclick = () => { update({ overseas: !state.overseas }); fitFocus(); };
  /** Open the frame editor; it needs the flat map at pitch 0, which the globe and Relief give up (with a note). */
  function drawFrame(forExport: boolean) {
    if (state.globe || state.relief) {
      map.jumpTo({ pitch: 0, bearing: 0 });
      update({ globe: false, relief: false });
      const t = $("toast");
      t.textContent = "Switched to the flat map to draw the area";
      t.hidden = false;
      setTimeout(() => (t.hidden = true), 3500);
    }
    editor.open(forExport, state.box ?? undefined);
  }
  $("area").onclick = () => editor.isOpen() ? editor.close() : drawFrame(false);
  const toggleFocus = (id: string) => setFocus(state.focus.includes(id) ? state.focus.filter((f) => f !== id) : [...state.focus, id]);
  $("unfocus").onclick = () => setFocus([]);
  $("chips").onclick = (e) => { const b = (e.target as HTMLElement).closest("button"); if (b) b.dataset.id ? toggleFocus(b.dataset.id) : setFocus([]); };
  $("seg").onclick = (e) => { const s = (e.target as HTMLElement).dataset.s; if (s) update({ scale: s as State["scale"] }); };
  $("cauto").onclick = () => update({ cmin: null, cmax: null });
  for (const key of ["cmin", "cmax"] as const) $<HTMLInputElement>(key).onchange = (e) => { // an unreadable or reversed entry is dropped
    const t = (e.target as HTMLInputElement).value.trim(), x = t ? parseAmount(t) : null, [lo, hi] = key === "cmin" ? [x, state.cmax] : [state.cmin, x];
    if ((t && x === null) || (lo != null && hi != null && lo >= hi)) render(); else update({ [key]: x });
  };
  matchMedia("(prefers-color-scheme: light)").onchange = () => { if (state.theme === "auto") render(); };
  let autoClasses = false; // Smoothing switched on set the default classes, which switching it off takes back
  let back: string | null = null; // the indicator shown before Smoothed went on (a total), restored when it goes off; in memory only
  for (const [el, key] of checks) el.onchange = () => update({ [key]: el.checked });
  /** The Regions | Smoothed switch: Smoothed takes the per-km2 version of a total and the default classes, and off gives them back. */
  for (const id of ["mode-r", "smooth"]) $<HTMLInputElement>(id).onchange = () => {
    const on = id === "smooth", c = smoothColours(state.classes, on, autoClasses), m = smoothIndicator(state.ind, on, back);
    autoClasses = c.auto;
    back = m.back;
    update({ smooth: on, classes: c.classes, ind: m.ind });
  };
  const dlg = $<HTMLDialogElement>("credits");
  dlg.innerHTML = creditsHtml(sources);
  $("credits-btn").onclick = $("credits-link").onclick = () => dlg.showModal();
  $("ui-btn").onclick = () => update({ ui: !state.ui });
  /** The north arrow shows only while north is not up; a click turns the map back (bearing and pitch). */
  const compass = $("compass"), arrow = compass.firstElementChild as SVGElement;
  arrow.innerHTML = `<path d="${COMPASS[0]}" fill="${NORTH}"/><path d="${COMPASS[1]}" fill="currentColor"/><text x="18" y="10" font-size="9" font-weight="600" text-anchor="middle" dominant-baseline="middle" fill="currentColor">N</text>`;
  map.on("rotate", () => { const b = map.getBearing(); compass.hidden = !turned(b); arrow.style.transform = `rotate(${-b}deg)`; });
  compass.onclick = () => map.resetNorthPitch();

  /** Export image: a PNG of the box, or of the focus' extent, or (no focus) of a frame set first; header and legend are drawn from the
   * same data as the cards, in the page's colours. The dialog shows the result before it is downloaded. */
  const xd = $<HTMLDialogElement>("export"), xi = $<HTMLImageElement>("export-img"), xdl = $<HTMLButtonElement>("export-dl"), xq = $<HTMLSelectElement>("export-q");
  xq.onchange = openExport;
  let xurl = "", xname = "", job = 0;
  const xclose = () => { job++; xd.close(); };
  $("export-btn").onclick = () => { if (focused() || state.globe) openExport(); else drawFrame(true); }; // the globe has no frame: its view is exported whole
  $("export-cancel").onclick = xclose;
  xd.onclose = () => { const u = xurl; xurl = ""; xi.hidden = true; setTimeout(() => URL.revokeObjectURL(u), 3000); };
  xdl.onclick = () => { const a = document.createElement("a"); a.href = xurl; a.download = xname; a.click(); xclose(); };
  async function openExport() {
    const mine = ++job, c = map.getContainer(), [w, h] = [c.clientWidth, c.clientHeight];
    $("export-note").textContent = "Rendering…";
    xi.hidden = xdl.disabled = true;
    if (!xd.open) xd.showModal();
    await rendered;
    map.fire("mouseout"); // no hover outline in the image
    await idle(map);
    const names = state.box ? [] : state.focus.map((id) => data.rows.get(id)!.name);
    let corners: [number, number, number, number] = [0, 0, w, h], margin = 0;
    const ext = state.box ?? (state.focus.length ? await cam.extent(state.focus.map((id) => [id, data.rows.get(id)!.level_no]), state.overseas) : null);
    if (ext && !state.globe && map.getPitch() < 1) { // a tilted view (Relief) is exported whole: the flat bounding box would cut its far edge
      const ps = [[ext[0], ext[3]], [ext[2], ext[1]], [ext[0], ext[1]], [ext[2], ext[3]]].map((q) => map.project(q as [number, number])); // all four: a turned map's box is not axis-aligned
      corners = [Math.min(...ps.map((q) => q.x)), Math.min(...ps.map((q) => q.y)), Math.max(...ps.map((q) => q.x)), Math.max(...ps.map((q) => q.y))];
      margin = state.box ? 0 : 0.04;
    }
    const rect: Rect | null = cropRect(corners, margin, w, h);
    const gl = map.getCanvas().getContext("webgl2") ?? map.getCanvas().getContext("webgl");
    if (!rect) { $("export-note").textContent = "The area is outside the map view."; return; }
    const r = exportRatio(rect, w, h, Math.min(8192, gl?.getParameter(gl.MAX_TEXTURE_SIZE) ?? 8192), matchMedia("(max-width: 640px)").matches ? 24e6 : 40e6, xq.value === "max");
    const crop = await capture(map, r, rect), sh = shade();
    const css = getComputedStyle(document.documentElement), v = (k: string) => css.getPropertyValue(k).trim();
    const sheet = { title: sh.label, sub: subtitle({ focus: names, area: !!state.box, level: view ? null : state.level, money: sh.money, base: state.base, year: data.ref }),
      legend: legendModel(sh, ...(({ dom, brk }) => [dom, state.base, view?.ex ? DIVERGING : state.palette, brk] as const)(scale())),
      bearing: map.getBearing(), credits: `Data: see Credits · ${document.querySelector("h1")!.textContent}` };
    const img = compose(crop, r, sheet, { bg: v("--pop"), ink: v("--ink"), mute: v("--mute"), line: v("--line"), noData: current().noData, disputed: current().disputed });
    const png = await new Promise<Blob | null>((res) => img.toBlob(res, "image/png"));
    if (mine !== job || !png) return; // closed meanwhile
    xurl = URL.createObjectURL(png);
    xname = fileName(names.length ? names : state.box ? ["area"] : [], view ? `${state.ind}-smoothed` : state.ind, data.ref);
    xi.src = xurl;
    xi.hidden = xdl.disabled = false;
    xd.dataset.ratio = String(r);
    xd.dataset.crop = `${rect.w}x${rect.h}`;
    $("export-note").textContent = `${img.width} × ${img.height} px${view ? `; the surface's cells are about ${Math.round(40075 / view.w)} km` : ""}`;
  }
  addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !e.defaultPrevented && !dlg.open && !xd.open) { if (focused()) setFocus([]); }
    if ((e.key === "h" || e.key === "H") && !e.ctrlKey && !e.metaKey && !e.altKey && !(e.target as HTMLElement).closest("input, select, textarea, dialog")) update({ ui: !state.ui });
  });
  for (const id of ["head", "tools", "legend"]) foldCard($(id));
  accordion($("acc"));
  new ResizeObserver(() => document.documentElement.style.setProperty("--th", $("tools").offsetHeight + "px")).observe($("tools")); // the click panel sits under the Map card
  showUi();

  searchBox(data, go, toggleFocus, () => state.focus);

  await ready;
  render();
  if (focused() && !state.cam) fitFocus();
  (window as any).__map = map; // for the smoke test
}

/** Keyboard-operable combobox: type, arrows, Enter selects, Escape clears. */
function searchBox(data: Data, choose: (r: Row) => void, toggle: (id: string) => void, focus: () => string[]) {
  const q = $<HTMLInputElement>("q"), list = $("results");
  let found: Row[] = [], active = 0;
  const draw = () => {
    list.hidden = !found.length;
    list.innerHTML = resultsHtml(found, active, data, focus(), (r) => !inFocus(data, r, new Set(focus())));
    q.setAttribute("aria-expanded", String(!list.hidden));
    q.setAttribute("aria-activedescendant", found.length ? `r${active}` : "");
  };
  const pickAt = (i: number) => {
    if (!found[i] || !inFocus(data, found[i], new Set(focus()))) return;
    choose(found[i]);
    q.value = found[i].name;
    found = [];
    draw();
  };
  q.oninput = () => { found = search(data.rows.values(), q.value); active = 0; draw(); };
  q.onblur = () => { found = []; draw(); };
  q.onkeydown = (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!found.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : found.length - 1)) % found.length;
      draw();
    } else if (e.key === "Enter") pickAt(active);
    else if (e.key === "Escape") { q.value = ""; found = []; draw(); }
    else return;
    e.preventDefault();
  };
  list.onmousedown = (e) => { // mousedown, so the input's blur does not close the list first
    const t = e.target as HTMLElement, i = t.closest<HTMLElement>("li")?.dataset.i;
    if (t.dataset.f) { e.preventDefault(); toggle(t.dataset.f); found = search(data.rows.values(), q.value); draw(); }
    else if (i) { e.preventDefault(); pickAt(Number(i)); }
  };
}

startTracking();
main().catch((e) => { // no WebGL, no data: say so instead of a blank page
  Object.assign($("toast"), { textContent: `The map could not start: ${e?.message ?? e}`, hidden: false });
});
