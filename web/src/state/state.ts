import { ALL_PALETTES, KERNELS, type Rule, nearestRadius, wider } from "../scales/scales";

export type State = {
  ind: string; palette: string; kernel: string; // keys of the indicator, the palette ("" = the default of the theme in use) and the smoothing kernel
  level: number; // level_no shown: 0 continents to 3 sub-regions (each country's finest level)
  globe: boolean; estimates: boolean; relief: boolean;
  base: number | null; // constant-dollar base year, null = current US$
  classes: number; // 0 = gradient, else the number of colour classes
  rule: Rule; // how the class breaks are set
  borders: boolean; // region outlines
  smooth: boolean; // the smoothed GDP-density surface instead of the regions
  radius: number; // km
  sea: boolean; // smoothed value counts the sea in the average
  scale: "auto" | "world" | "view"; // colour domain: auto = the focus if there is one, else the world; world with a focus; the part in view (and in the focus)
  cmin: number | null; cmax: number | null; // manual colour range (log10), overrides the scale's ends
  local: boolean; // local excess: the surface against its Gaussian surroundings, one ladder radius above `radius` (`wider`)
  sel: string | null; // region_id
  cam: [number, number, number] | null; // zoom, lat, lng
  theme: "auto" | "light" | "dark";
  ui: boolean; // false: controls hidden
  focus: string[]; // region ids (sorted, unique) the view is restricted to; excludes `box`
  box: [number, number, number, number] | null; // focus box w, s, e, n (degrees)
  overseas: boolean; // focus includes overseas parts
};

export const DEFAULT: State = { ind: "gdp_per_km2", level: 3, globe: false, estimates: true, relief: false, base: null, palette: "", classes: 0, rule: "log", borders: true, smooth: false, kernel: "inv2", radius: 50, sea: false, scale: "auto", cmin: null, cmax: null, local: false, sel: null, cam: null, theme: "auto", ui: true, focus: [], box: null, overseas: false };

const finite = (t: string | null) => (Number.isFinite(Number(t)) ? Number(t) : null);
/** Colours when Smoothing is switched on or off (not when a link loads: it keeps the colours it states): from the gradient to 6
 * classes, and back to the gradient if they are still the ones it set (`auto`). */
export function smoothColours(classes: number, on: boolean, auto: boolean): { classes: number; auto: boolean } {
  return on ? (classes === 0 ? { classes: 6, auto: true } : { classes, auto: false }) : { classes: auto && classes === 6 ? 0 : classes, auto: false };
}
/** The per-km2 indicator a total stands for in the smoothed view (only densities and GDP per capita are smoothed). */
export const PER_KM2: Record<string, string> = { gdp_usd: "gdp_per_km2", pop: "pop_density" };
/** The indicator when Smoothed goes `on` or off: a total moves to its per-km2 version, remembered as `back`; off restores `back` if
 * the viewer left the remapped indicator alone. */
export function smoothIndicator(ind: string, on: boolean, back: string | null): { ind: string; back: string | null } {
  if (on) return PER_KM2[ind] ? { ind: PER_KM2[ind], back: ind } : { ind, back: null };
  return { ind: back && PER_KM2[back] === ind ? back : ind, back: null };
}
/** Drops local excess where no wider radius exists (the largest) and a World scale without focus. */
export function clean(s: State): State {
  return { ...s, local: s.local && wider(s.radius) > 0, ...(s.cmin != null && s.cmax != null && s.cmin >= s.cmax ? { cmin: null, cmax: null } : {}), scale: s.scale === "world" && !s.focus.length && !s.box ? "auto" : s.scale }; // "world" differs from auto only in a focus
}

/** Fields written as `key=value` when they differ from the default, with the test a URL value must pass to be taken. */
type Ctx = { valid: string[]; bases: number[] };
const ENUMS: [keyof State, string, (x: string, c: Ctx) => boolean][] = [
  ["ind", "i", (x, c) => c.valid.includes(x)], ["level", "l", (x) => /^[0-3]$/.test(x)], ["base", "b", (x, c) => c.bases.includes(+x)],
  ["palette", "p", (x) => ALL_PALETTES.includes(x)], ["classes", "k", (x) => /^[3-7]$/.test(x)], ["rule", "q", (x) => x === "share"],
  ["kernel", "sk", (x) => Object.hasOwn(KERNELS, x)], ["radius", "sr", (x) => /^[1-9]\d{0,3}$/.test(x)], ["theme", "th", (x) => x === "light" || x === "dark"],
];
/** Booleans: written `1` or `0` against the default. */
const FLAGS: [keyof State, string][] = [["globe", "g"], ["estimates", "e"], ["relief", "r"], ["borders", "o"], ["sea", "ss"], ["local", "lx"], ["ui", "ui"], ["overseas", "fo"]];
const box3 = (b: number[]) => b.map((x) => +x.toFixed(3));

/** State -> URL hash; defaults are left out. */
export function toHash(s: State): string {
  const p = new URLSearchParams();
  for (const [f, k] of ENUMS) if (s[f] !== DEFAULT[f]) p.set(k, String(s[f]));
  for (const [f, k] of FLAGS) if (s[f] !== DEFAULT[f]) p.set(k, s[f] ? "1" : "0");
  if (s.smooth) p.set("v", "s");
  if (s.scale !== "auto") p.set(s.scale === "view" ? "sf" : "sw", "1");
  if (s.cmin != null) p.set("cl", String(+s.cmin.toFixed(3)));
  if (s.cmax != null) p.set("ch", String(+s.cmax.toFixed(3)));
  if (s.sel) p.set("s", s.sel);
  if (s.cam) p.set("c", s.cam.join("/"));
  if (s.box) p.set("fb", box3(s.box).join(","));
  else if (s.focus.length) p.set("f", [...new Set(s.focus)].sort().join(","));
  return p.toString().replace(/%2F/g, "/").replace(/%3A/g, ":").replace(/%2C/g, ",");
}

/** URL hash -> state; anything invalid falls back to the default. */
export function fromHash(hash: string, valid: string[], bases: number[] = []): State {
  const p = new URLSearchParams(hash.replace(/^#/, "")), s: Record<string, unknown> = { ...DEFAULT }, nums = (k: string) => (p.get(k) ?? "").split(k === "c" ? "/" : ",").map((x) => (x === "" ? NaN : Number(x)));
  for (const [f, k, ok] of ENUMS) { const x = p.get(k); if (x != null && ok(x, { valid, bases })) s[f] = typeof DEFAULT[f] === "string" ? x : +x; }
  for (const [f, k] of FLAGS) s[f] = p.get(k) === "1" || (p.get(k) !== "0" && DEFAULT[f]);
  const cam = nums("c"), box = nums("fb"), hasBox = box.length === 4 && box.every(Number.isFinite);
  const smooth = p.get("v") === "s";
  return clean({
    ...(s as State),
    ind: smooth ? (PER_KM2[s.ind as string] ?? (s.ind as string)) : (s.ind as string), // old links: Smoothed GDP and population are the per-km2 surfaces
    radius: nearestRadius(s.radius as number),
    sea: !!s.sea || p.get("so") === "1", // "so" (draw over the sea) was merged into it
    smooth,
    scale: p.get("sf") === "1" ? "view" : p.get("sw") === "1" ? "world" : "auto",
    cmin: p.get("cl") ? finite(p.get("cl")) : null,
    cmax: p.get("ch") ? finite(p.get("ch")) : null,
    sel: p.get("s") || null,
    cam: cam.length === 3 && cam.every(Number.isFinite) ? (cam as State["cam"]) : null,
    focus: hasBox ? [] : [...new Set((p.get("f") ?? "").split(",").filter(Boolean))].sort(),
    box: hasBox ? (box3(box) as State["box"]) : null,
  });
}
