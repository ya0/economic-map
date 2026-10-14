import { type Data, type Row, LEVELS, basisLabel, isDisputed } from "../data/data";
import { flagText, flagUrl } from "../data/flags";
import { current } from "../theme";
import { type Indicator, INDICATORS, classColours, fmt, fmtValue, stops, ticks, times, withUnit } from "../scales/scales";

export type Source = { source_id: string; name: string; publisher: string; licence: string; url: string; role: string; cited_origin?: string };

export const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s).replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);

/** Flag (countries and their regions only) and name. */
const named = (r: Pick<Row, "name" | "iso2">) => (flagUrl(r.iso2) ? `<img class="flag" src="${flagUrl(r.iso2)}" alt="">` : "") + esc(r.name);

const pct = (x: number) => (x * 100).toFixed(1) + "%";
export const coverageLine = (c: { n: number; all: number; sub: number }) =>
  `${c.n.toLocaleString("en")} regions hold ${pct(c.all)} of world GDP${c.sub ? `, ${pct(c.sub)} below country level` : ""}.`;

/** What the legend shows, for the card and the exported image: heading, unit line, and either class swatches or a gradient with its ticks
 * (position 0..1, label). `brk`: class breaks (log10) instead of the gradient. */
export function legendModel(ind: Indicator, dom: [number, number], base: number | null = null, pal = "", brk: number[] | null = null) {
  const at = (b: number) => fmtValue(10 ** b, ind), cols = brk && classColours(pal, brk.length + 1), top = ind.max! > dom[0] ? Math.min(dom[1], ind.max!) : dom[1], k = (dom[1] - dom[0]) / (top - dom[0]);
  return {
    title: ind.label,
    unit: [ind.money && basisLabel(base), ind.unit].filter(Boolean).join(" ") + ", log scale",
    classes: cols?.map((c, i): [string, string] => [c, i ? (i < brk!.length ? at(brk![i - 1]) + "–" + at(brk![i]) : "≥" + at(brk![i - 1])) : "<" + at(brk![0])]),
    grad: stops(dom, 9, pal).map(([, c], i, a): [number, string] => [(i / (a.length - 1)) * k, c]).filter(([x]) => x <= 1),
    ticks: ticks([dom[0], top]).map((e, i): [number, string] => [(e - dom[0]) / (top - dom[0]), (i === 0 ? "≤" : e === dom[1] ? "≥" : "") + at(e)]),
  };
}

/** The tick labels that do not touch another one in a legend `width` px wide, with the left edge of each (a label is `size(text)` px
 * wide; the first sits at the left end, the last at the right end, the others centred on their position). The last one is kept: it
 * drops its neighbours instead. */
export function thinTicks(ticks: [number, string][], width: number, size = (t: string) => t.length * 7): [number, string, number][] {
  const out: [number, string, number][] = [];
  ticks.forEach(([x, t], i) => {
    const w = size(t), last = i === ticks.length - 1, left = i === 0 ? 0 : last ? width - w : x * width - w / 2;
    if (last) while (out.length > 1 && out.at(-1)![2] + size(out.at(-1)![1]) + 6 > left) out.pop();
    if (!out.length || left >= out.at(-1)![2] + size(out.at(-1)![1]) + 6) out.push([x, t, left]);
  });
  return out;
}

/** Legend notes: the region view, and the smoothed GDP per capita (what the zones' national value does to its surface). */
export const NOTES = {
  derived: "Derived regions split the national GDP by population: their GDP per capita is the national value.",
  pcap: "Inside zoned countries (regions split by population) GDP per capita is the national value by construction, so the smoothed map steps at their borders.",
};

export function legendHtml(ind: Indicator, dom: [number, number], base: number | null = null, pal = "", brk: number[] | null = null, cut = false, sea = false, note = "", width = 280): string {
  const m = legendModel(ind, dom, base, pal, brk);
  const scale = m.classes
    ? `<div class="classes">${m.classes.map(([c, t]) => `<span><i style="background:${c}"></i>${esc(t)}</span>`).join("")}</div>`
    : `<div class="bar" style="background:linear-gradient(90deg,${m.grad.map(([x, c]) => `${c} ${x * 100}%`).join(",")})"></div><div class="ticks">${
      thinTicks(m.ticks, width).map(([x, t]) => `<span style="left:${x * 100}%">${esc(t)}</span>`).join("")}</div>`;
  return `<div class="lt">${esc(m.title)}<small>${esc(m.unit)}</small>${cut ? `<small class="scope">Cut at the border; values near it include the neighbours' economy.</small>` : ""}</div>
    ${scale}${sea ? `<small class="scope">Include sea: divided by all area within reach, so coasts and islands read lower.</small>` : ""}${
      note ? `<small class="scope">${esc(note)}</small>` : ""}
    <div class="keys"><i style="background:${current().noData}"></i>No data<i class="disputed" style="background:${current().disputed}"></i>Disputed</div>`;
}

/** Tooltip of the smoothed view: the value under the cursor, its reach, the local excess `x` against the surroundings of `wide` km
 * and the region there, if any. */
export const smoothTipHtml = (v: number, ind: Indicator, r: number, row?: Row, x?: number, wide?: number, land?: number) =>
  `${row ? `<b>${named(row)}</b>` : ""}<div class="v">${esc(withUnit(v, ind))}</div><small>within about ${r} km</small>${
    land ? `<small>land only: ${esc(withUnit(land, ind))}, ${Math.round((v / land) * 100)}% land within reach</small>` : ""}${
    x ? `<div class="ex">${times(x)} its surroundings<small>within about ${wide} km (Gaussian)</small></div>` : ""}`;

function flagList(row: Row, ref: number, skip: string[] = []): string {
  const items = row.flags.filter((f) => !skip.includes(f)).map((f) => `<li>${esc(flagText(f, row, ref))}</li>`).join("");
  return items ? `<ul class="flags">${items}</ul>` : "";
}

/** Tooltip corner next to the cursor, flipped when it would leave the viewport. */
export const tipPos = (x: number, y: number, w: number, h: number, vw: number, vh: number): [number, number] =>
  [Math.max(0, x + 14 + w > vw ? x - 14 - w : x + 14), Math.max(0, y + 14 + h > vh ? y - 14 - h : y + 14)];

export function tipHtml(row: Row, ind: Indicator, ref: number, base: number | null = null): string {
  const v = row[ind.key];
  const value = v > 0 ? esc(withUnit(v, ind)) + (ind.money && base ? ` <small>${basisLabel(base)}</small>` : "") : "No data";
  return `<b>${named(row)}</b>${isDisputed(row) ? "" : `<div class="v">${value}</div>`}${flagList(row, ref, ["area_computed", "aggregated", "contains_wikipedia_secondary", "contains_wikidata", "contains_pop_share", ...(row.flags.includes("pop_share") ? [] : ["pop_scaled"])])}`;
}

const sourceLink = (id: string, sources: Map<string, Source>) => {
  const s = sources.get(id);
  return s ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.publisher)}</a>` : esc(id);
};

const get = (k: string) => INDICATORS.find((i) => i.key === k)!;
const line = (label: string, v: unknown, text: string, extra = "") =>
  `<tr><th>${label}</th><td>${typeof v === "number" ? esc(text) : "no data"}</td><td>${extra}</td></tr>`;
const panelHead = (crumbs: string, title: string) => `<button class="x" type="button" aria-label="Close">×</button>
    <nav class="crumbs" aria-label="Part of">${crumbs}</nav><div class="fh"><button class="chev" type="button"></button><h2>${title}</h2></div>`;
const basis = (base: number | null, ref: number) => `<p class="basis">Money in ${basisLabel(base)}; data year ${ref}.</p>`;

/** Click panel. `above`: the region's ancestors, continent first (breadcrumb); `coarser`: a finer level was asked for. */
export function panelHtml(row: Row, above: Row[], coarser: boolean, data: Data, sources: Map<string, Source>, base: number | null = null, focus: string[] = []): string {
  const crumbs = above.map((r) => `<button type="button" data-id="${esc(r.id)}">${esc(r.name)}</button>`).join("<span>›</span>");
  const head = panelHead(crumbs, named(row));
  const fo = above.some((r) => focus.includes(r.id)) ? "" : `<button class="fo" type="button">${focus.includes(row.id) ? "Remove from focus" : focus.length ? `Add ${esc(row.name)} to focus` : `Focus on ${esc(row.name)}`}</button>`;
  if (isDisputed(row)) return head + flagList(row, data.ref);
  /** Year and source of a value; an aggregated row whose regions differ in source has none. */
  const origin = (k: string, y: string, s: string) => (row[k] == null ? "" : `${esc(row[y] ?? "")} · ${row[s] ? sourceLink(row[s], sources) : "several sources"}`);
  const rows = line("GDP", row.gdp_usd, withUnit(row.gdp_usd, get("gdp_usd")), origin("gdp_usd", "gdp_year", "gdp_source")) +
    line("Population", row.pop, withUnit(row.pop, get("pop")), origin("pop", "pop_year", "pop_source")) +
    (row.flags.includes("pop_scaled") ? line("Population as published", row.pop_raw, withUnit(row.pop_raw, get("pop"))) : "") +
    line("Area", row.area_km2, fmt(row.area_km2) + " km²", origin("area_km2", "area_year", "area_source")) +
    ["gdp_per_km2", "gdp_per_capita", "pop_density"].map((k) => line(get(k).label, row[k], withUnit(row[k], get(k)), "derived")).join("");
  return `${head}<p class="sub">${LEVELS[row.level_no]}${coarser ? " (finest available)" : ""}</p>${fo}<table>${rows}</table>${flagList(row, data.ref)}${basis(base, data.ref)}`;
}

export function creditsHtml(sources: Source[]): string {
  const items = sources.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a>
    <span>${esc(s.publisher)}, ${esc(s.licence)}${s.cited_origin ? `. Cites: ${esc(s.cited_origin)}` : ""}</span></li>`).join("");
  return `<form method="dialog"><button class="x" aria-label="Close">×</button></form><h2>Credits</h2>
    <p>GDP, population and area come from the official sources below or from aggregators that republish them.
    Wikipedia and Wikidata are secondary sources and are flagged wherever used. Coarser levels are sums of each country's finest regions.</p>
    <p>About the map: shapes are simplified from Natural Earth, Eurostat GISCO (© EuroGeographics), US Census, ONS, IBGE, INEGI,
    Statistics Canada and OCHA COD-AB files, so they are right at world and
    country scale but not at coastline scale. The flat view (Web Mercator) inflates areas toward the poles, the globe does not; values
    are per km², so this changes how large a region looks, not its colour. Borders are de facto; Crimea is drawn as disputed.
    Flags: flag-icons (MIT).</p>
    <ul>${items}</ul>`;
}

/** Search result options for the combobox listbox: flag, name, level and parent, and a button to add the region to the focus.
 * `out`: the regions outside the focus; they are listed but not selectable. */
export const resultsHtml = (rows: Row[], active: number, d: Data, focus: string[] = [], out: (r: Row) => boolean = () => false) =>
  rows.map((r, i) => `<li role="option" id="r${i}" data-i="${i}" aria-selected="${i === active}"${out(r) ? ' class="out"' : ""}><span>${named(r)}</span><small>${
    esc([LEVELS[r.level_no], d.rows.get(r.parent_id!)?.name].filter(Boolean).join(", "))}</small><button type="button" class="fo" data-f="${esc(r.id)}" aria-pressed="${focus.includes(r.id)}">focus</button></li>`).join("");

/** Chips of the focus, each removable; `area`: the drawn rectangle (a chip without an id). */
export const chipsHtml = (rows: Pick<Row, "id" | "name">[], area = false) =>
  (area ? `<span class="chip">Area<button type="button" aria-label="Remove the area from focus">×</button></span>` : "") + rows.map((r) => `<span class="chip">${esc(r.name)}<button type="button" data-id="${esc(r.id)}" aria-label="Remove ${esc(r.name)} from focus">×</button></span>`).join("");

/** Folding cards and sections, remembered per viewer (localStorage; everything works without it). */
const saved = (): Record<string, boolean> => { try { return JSON.parse(localStorage.getItem("fold") ?? "{}"); } catch { return {}; } };
const remember = (id: string, open: boolean) => { try { localStorage.setItem("fold", JSON.stringify({ ...saved(), [id]: open })); } catch { /* private window */ } };

/** Card with a header row `.fh` (chevron `.chev` first): everything after the header goes into a body that the chevron shows or hides.
 * Safe to call again after the card's content was replaced. Cards start open on a desktop, folded on a phone. */
export function foldCard(card: HTMLElement) {
  const head = card.querySelector<HTMLElement>(":scope > .fh")!, chev = head.querySelector<HTMLButtonElement>(".chev")!;
  let body = card.querySelector<HTMLElement>(":scope > .fb");
  if (!body) {
    body = document.createElement("div");
    body.className = "fb";
    body.id = card.id + "-body";
    while (head.nextSibling) body.append(head.nextSibling);
    card.append(body);
  }
  chev.setAttribute("aria-controls", body.id);
  chev.setAttribute("aria-label", "Fold " + (head.querySelector("h1, h2")?.textContent ?? card.getAttribute("aria-label")));
  const set = (open: boolean) => {
    body!.hidden = !open;
    card.classList.toggle("folded", !open);
    chev.setAttribute("aria-expanded", String(open));
  };
  chev.onclick = () => { const open = card.classList.contains("folded"); set(open); remember(card.id, open); };
  set(saved()[card.id] ?? !matchMedia("(max-width: 640px)").matches);
}

/** Accordion over the `details` children of `root`: one section is open at a time, the open one is kept in localStorage; an opening
 * section scrolls into view (the card's column is short on a small screen). */
export function accordion(root: HTMLElement) {
  const all = [...root.querySelectorAll<HTMLDetailsElement>(":scope > details")];
  let want = "";
  try { want = localStorage.getItem("sec") ?? ""; } catch { /* no storage */ }
  const keep = (id: string) => { try { localStorage.setItem("sec", id); } catch { /* private window */ } };
  for (const d of all) {
    d.open = d.id === want;
    d.ontoggle = () => {
      if (d.open) { for (const o of all) if (o !== d) o.open = false; keep(d.id); d.scrollIntoView({ block: "nearest" }); }
      else if (!all.some((o) => o.open)) keep("");
    };
  }
}

/** The one-line legend of a folded card: lowest value, a small gradient or the class swatches, highest value. */
export function stripHtml(ind: Indicator, dom: [number, number], base: number | null, pal: string, brk: number[] | null): string {
  const m = legendModel(ind, dom, base, pal, brk), lo = m.classes ? m.classes[0][1] : m.ticks[0][1], hi = m.classes ? m.classes.at(-1)![1] : m.ticks.at(-1)![1];
  const mid = m.classes ? `<span class="sw">${m.classes.map(([c]) => `<i style="background:${c}"></i>`).join("")}</span>`
    : `<span class="sw"><i style="background:linear-gradient(90deg,${m.grad.map(([x, c]) => `${c} ${x * 100}%`).join(",")})"></i></span>`;
  return `<span>${esc(lo)}</span>${mid}<span>${esc(hi)}</span>`;
}
