import { currentName } from "../theme";
import { interpolateCividis, interpolateGreys, interpolateInferno, interpolateMagma, interpolateOrRd, interpolatePlasma, interpolatePurples, interpolateRdBu, interpolateReds, interpolateViridis, interpolateYlOrBr, interpolateYlOrRd } from "d3-scale-chromatic";

/** `fmt`: how a value is written, if not as an amount (the local excess: "3×"); `max`: the highest value there is (log10), where the
 * scale ends above it (the legend stops there). */
export type Indicator = { key: string; label: string; unit: string; money: boolean; fmt?: (v: number) => string; max?: number };

export const INDICATORS: Indicator[] = [
  { key: "gdp_per_km2", label: "GDP per km²", unit: "per km²", money: true },
  { key: "gdp_per_capita", label: "GDP per capita", unit: "per person", money: true },
  { key: "pop_density", label: "Population density", unit: "people per km²", money: false },
  { key: "gdp_usd", label: "GDP", unit: "", money: true },
  { key: "pop", label: "Population", unit: "people", money: false },
];

/** Dark theme palettes, low = dark to high = bright; the first is the default. */
const DARK: Record<string, (t: number) => string> = { magma: interpolateMagma, viridis: interpolateViridis, plasma: interpolatePlasma, cividis: interpolateCividis };
const rev = (f: (t: number) => string) => (t: number) => f(1 - t);
/** Light theme palettes, low = light to high = dark (common ColorBrewer and matplotlib ramps, none blue: the sea is); the first is the
 * default. The number is where the ramp starts, so the lowest class stays 25 CIE units from the sea and no-data grey (`test/theme.test.ts`). */
const LIGHT: Record<string, [(t: number) => string, number]> = {
  ylorrd: [interpolateYlOrRd, 0.05], ylorbr: [interpolateYlOrBr, 0.15], orrd: [interpolateOrRd, 0.25], reds: [interpolateReds, 0.25], purples: [interpolatePurples, 0.45],
  greys: [interpolateGreys, 0.5], viridis_r: [rev(interpolateViridis), 0], magma_r: [rev(interpolateMagma), 0.05], inferno_r: [rev(interpolateInferno), 0],
};
const LABELS: Record<string, string> = { ylorrd: "YlOrRd", ylorbr: "YlOrBr", orrd: "OrRd", viridis_r: "Viridis (reversed)", magma_r: "Magma (reversed)", inferno_r: "Inferno (reversed)" };
/** The palettes of a theme (ids, first = default) and the name shown for one. */
export const paletteIds = (theme: "dark" | "light") => Object.keys(theme === "light" ? LIGHT : DARK);
export const paletteLabel = (id: string) => LABELS[id] ?? id[0].toUpperCase() + id.slice(1);
export const ALL_PALETTES = [...paletteIds("dark"), ...paletteIds("light")];

/** The diverging palette of the local excess: blue below its surroundings, red above (RdBu, whole). */
export const DIVERGING = "rdbu";
/** Colour at `t` (0..1) of a palette of the theme in use; an id of the other theme gives that theme's default (`pal` "" too). Dark: the
 * lowest class is trimmed at 12% so it stays visible on the dark map. Light: from the palette's start to 92%, so the top is not black.
 * The diverging palette is whole in both, so 1x stays its middle. */
export const ramp = (t: number, pal = "") => {
  if (pal === DIVERGING) return interpolateRdBu(1 - t);
  if (currentName() !== "light") return (DARK[pal] ?? DARK.magma)(0.12 + 0.88 * t);
  const [f, from] = LIGHT[pal] ?? LIGHT.ylorrd;
  return f(from + (0.92 - from) * t);
};

/** One colour per class (n >= 2), sampled evenly from the palette. */
export const classColours = (pal: string, n: number) => Array.from({ length: n }, (_, k) => ramp(k / (n - 1), pal));

export type Rule = "log" | "share";

/** Weighted by the indicator's numerator: GDP for money indicators, people otherwise. */
export const weightKey = (ind: Indicator) => (ind.money ? "gdp_usd" : "pop");

/** Interior class breaks (log10), strictly rising. "log": `n` classes of equal width over `dom`. "share": each class holds an equal
 * share of the weight of `items` ([value, weight]); equal values cannot be split, so there may be fewer breaks. */
export function breaks(n: number, rule: Rule, dom: [number, number], items: [number, number][]): number[] {
  const equal = Array.from({ length: n - 1 }, (_, i) => dom[0] + ((dom[1] - dom[0]) * (i + 1)) / n);
  if (rule === "log") return equal;
  const s = items.filter(([v]) => v > 0).sort((a, b) => a[0] - b[0]);
  const total = s.reduce((a, [, w]) => a + w, 0);
  const out: number[] = [];
  let cum = 0;
  for (let j = 0, i = 1; j < s.length - 1 && i < n; j++) {
    cum += s[j][1];
    if (s[j + 1][0] > s[j][0] && cum >= (total * i) / n) {
      out.push(Math.log10(s[j + 1][0])); // the next value starts the next class
      while (i < n && cum >= (total * i) / n) i++;
    }
  }
  return out.length ? out : equal;
}

/** Decade bounds [lo, hi] (as log10) that contain the 1st to 99th percentile of the values. */
export function domain(values: number[]): [number, number] {
  const s = values.filter((v) => v > 0).sort((a, b) => a - b);
  const at = (p: number) => Math.log10(s[Math.floor(p * (s.length - 1))]);
  const lo = Math.floor(at(0.01));
  return [lo, Math.max(Math.ceil(at(0.99)), lo + 1)];
}

/** log10 of a typed amount: "1M", "$2.5e6", "100k", "3x" (k, M, B, T suffixes); null if it is not a positive number. */
export function parseAmount(text: string): number | null {
  const m = /^([\d.]+(?:e[+-]?\d+)?)([kmbt]?)$/i.exec(text.replace(/[$×x,\s]/gi, ""));
  const v = m && Number(m[1]) * 1000 ** (m[2] ? "kmbt".indexOf(m[2].toLowerCase()) + 1 : 0);
  return v && v > 0 && Number.isFinite(v) ? Math.log10(v) : null;
}
/** The domain with a manual end (log10) where one is set; the automatic one if that would leave no range. */
export const manual = (dom: [number, number], lo: number | null, hi: number | null): [number, number] =>
  (lo ?? dom[0]) < (hi ?? dom[1]) ? [lo ?? dom[0], hi ?? dom[1]] : dom;

/** log10 values of the labelled legend breaks: both ends and the decades between them, thinned to at most 7; below two decades
 * also the 3s (0.3, 3, 30). */
export function ticks([lo, hi]: [number, number]): number[] {
  const step = hi - lo < 2 ? 0.5 : Math.ceil((hi - lo) / 6), gap = (hi - lo) / 7, out = [lo];
  for (let e = (Math.floor(lo / step) + 1) * step; e < hi - gap; e += step) if (e > lo + gap) out.push(e % 1 ? Math.sign(e) * (Math.floor(Math.abs(e)) + Math.log10(3)) : e);
  return [...out, hi];
}

/** Colour stops (log10 value, css colour) for the map expression and the legend gradient. */
export const stops = ([lo, hi]: [number, number], n = 9, pal = ""): [number, string][] =>
  Array.from({ length: n }, (_, i) => [lo + ((hi - lo) * i) / (n - 1), ramp(i / (n - 1), pal)]);

const SUFFIX: [number, string][] = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "k"]];

/** Compact number: 12.3k, 4.56M; three significant digits. */
export function fmt(v: number): string {
  const [div, suf] = SUFFIX.find(([d]) => v >= d) ?? [1, ""];
  const x = v / div;
  return Number(x.toPrecision(3)) + suf;
}

/** A ratio to two digits: "0.33×", "3×", "12×". */
export const times = (v: number) => Number(v.toPrecision(2)) + "×";
export const fmtValue = (v: number, ind: Indicator) => (ind.fmt ? ind.fmt(v) : (ind.money ? "$" : "") + fmt(v));
/** Value with its unit suffix, e.g. "$8.5M per km²". */
export const withUnit = (v: number, ind: Indicator) => `${fmtValue(v, ind)} ${ind.unit}`.trim();

/** Labels of the smoothing kernels and the radii (km) of the surfaces in `public/smooth/`; smooth.json says which kernels exist. */
export const KERNELS: Record<string, string> = { inv2: "Inverse square", gauss: "Gaussian" };
export const RADII = [15, 30, 50, 100, 150];
/** The ladder radius one step above `r` (the Gaussian surroundings of the local excess), 0 at the top. */
export const wider = (r: number) => RADII.find((x) => x > r) ?? 0;
/** A radius from an old link that the ladder no longer has maps to the nearest one (40 to 30 and 75 to 100 are the rounded-up ties). */
export const nearestRadius = (r: number) => ({ 40: 30, 75: 100 })[r as 40 | 75] ?? RADII.reduce((b, x) => (Math.abs(x - r) < Math.abs(b - r) ? x : b));

/** The three smoothed indicators: `src` the surface set of smooth.json it reads; `sea`: Include sea is the user's (null) or n/a (false). */
export const SMOOTH: Record<string, { src: string; sea: boolean | null }> = {
  gdp_per_km2: { src: "gdp_per_km2", sea: null }, pop_density: { src: "pop_density", sea: null }, gdp_per_capita: { src: "gdp_per_capita", sea: false },
};
/** Include sea as it applies to an indicator, given the user's choice. */
export const seaFor = (key: string, user: boolean) => SMOOTH[key]?.sea ?? user;

/** Constant-dollar base years offered next to current US$. */
export const BASE_YEARS = [2000, 2010, 2015, 2017, 2020];

/** Feature-state of a value for the map: `v` log10 (null for no data), `c` its colour as the legend draws it (the class it falls in, or
 * the gradient lerped between the stops in RGB, as MapLibre's `interpolate` would) and `h` the relief height in decades above the
 * domain floor (classes: one height per class, rising evenly to the decades the scale spans); no data is `noData` and flat. */
export function painter(dom: [number, number], brk: number[] | null, pal: string, noData: string): (v: number | undefined) => { v: number | null; c: string; h: number } {
  const rgb = (c: string) => (c[0] === "#" ? [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16)) : c.match(/\d+/g)!.map(Number)); // d3 gives "#rrggbb" or "rgb(r, g, b)"
  const hex = (c: number[]) => "#" + c.map((x) => Math.round(x).toString(16).padStart(2, "0")).join("");
  const st = stops(dom, 9, pal), cols = (brk ? classColours(pal, brk.length + 1) : st.map(([, c]) => c)).map(rgb);
  return (x) => {
    if (!x) return { v: null, c: noData, h: 0 };
    const v = Math.log10(x);
    if (brk) { const i = brk.filter((b) => v >= b).length; return { v, c: hex(cols[i]), h: ((dom[1] - dom[0]) * (i + 1)) / cols.length }; }
    const i = Math.min(Math.max(st.findLastIndex(([s]) => v >= s), 0), 7), t = Math.min(Math.max((v - st[i][0]) / (st[i + 1][0] - st[i][0]), 0), 1);
    return { v, c: hex(cols[i].map((a, k) => a + t * (cols[i + 1][k] - a))), h: Math.max(v - dom[0], 0) };
  };
}
