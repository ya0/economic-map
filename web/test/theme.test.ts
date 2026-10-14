import { afterEach, describe, expect, it } from "vitest";
import { DIVERGING, classColours, paletteIds, ramp, stops } from "../src/scales/scales";
import { type Theme, current, currentName, setTheme } from "../src/theme";

/** CIE76 colour difference between two css colours. */
function lab(css: string): [number, number, number] {
  const [cr, cg, cb] = css[0] === "#" ? [1, 3, 5].map((j) => parseInt(css.slice(j, j + 2), 16)) : css.match(/\d+/g)!.map(Number), f = (u: number) => { u /= 255; return u <= 0.04045 ? u / 12.92 : ((u + 0.055) / 1.055) ** 2.4; };
  const [r, g, b] = [cr, cg, cb].map(f);
  const xyz = [(0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b, (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883];
  const [x, y, z] = xyz.map((t) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116));
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
}
const dE = (a: string, b: string) => Math.hypot(...lab(a).map((v, i) => v - lab(b)[i]));

/** A just-noticeable difference is about 2.3 in CIE76; side by side (a class next to water on the map) 12 is clearly two colours.
 * The light palettes' lowest colour is held to 25 from the sea and no-data grey, and every class to 7 from its neighbour (3 to 7
 * classes). The dark palettes are unchanged since before the light theme: their lowest cividis class is 7.5 from no-data, so no-data is
 * held to 7 there. */
const MIN_DE = 12, MIN_LOW = 25, MIN_STEP = 7, MIN_NODATA: Record<Theme, number> = { light: MIN_DE, dark: 7 };

describe("themes", () => {
  afterEach(() => setTheme("dark"));

  for (const name of ["dark", "light"] as Theme[]) {
    it(`${name}: every palette colour differs from the ocean and no-data`, () => {
      setTheme(name);
      const { ocean, noData } = current();
      for (const pal of paletteIds(name)) {
        const cs = [...stops([0, 1], 9, pal).map(([, c]) => c), ...[3, 4, 5, 6, 7].flatMap((n) => classColours(pal, n))];
        for (const c of cs) {
          expect(dE(c, ocean), `${pal} ${c} against the ocean`).toBeGreaterThanOrEqual(MIN_DE);
          if (name === "light") expect(dE(c, "#ffffff"), `${pal} ${c} against the white outside a focus`).toBeGreaterThanOrEqual(MIN_DE);
          expect(dE(c, noData), `${pal} ${c} against no-data`).toBeGreaterThanOrEqual(MIN_NODATA[name]);
        }
      }
      // diverging: the whole of RdBu; only its ends are tested, the middle (1x) is meant to be neutral
      for (const t of [0, 1]) for (const bg of [ocean, noData]) expect(dE(ramp(t, DIVERGING), bg)).toBeGreaterThanOrEqual(MIN_NODATA[name]);
    });
  }

  it("disputed differs from no-data and ocean in light", () => {
    setTheme("light");
    const l = current();
    expect(dE(l.disputed, l.noData)).toBeGreaterThanOrEqual(MIN_DE);
    expect(dE(l.disputed, l.ocean)).toBeGreaterThanOrEqual(MIN_DE);
  });

  it("light palettes: L* falls from low to high, the lowest colour is clear of the sea and no-data, every class differs from its neighbour", () => {
    setTheme("light");
    const { ocean, noData } = current();
    expect(paletteIds("light")).toEqual(["ylorrd", "ylorbr", "orrd", "reds", "purples", "greys", "viridis_r", "magma_r", "inferno_r"]);
    for (const pal of paletteIds("light")) {
      const ls = Array.from({ length: 21 }, (_, i) => lab(ramp(i / 20, pal))[0]);
      expect(ls, pal).toEqual([...ls].sort((a, b) => b - a));
      expect(dE(ramp(0, pal), ocean), `${pal} against the ocean`).toBeGreaterThanOrEqual(MIN_LOW);
      expect(dE(ramp(0, pal), noData), `${pal} against no-data`).toBeGreaterThanOrEqual(MIN_LOW);
      for (const n of [3, 4, 5, 6, 7]) {
        const cs = classColours(pal, n);
        for (let i = 1; i < n; i++) expect(dE(cs[i], cs[i - 1]), `${pal} ${n} classes, ${i}`).toBeGreaterThanOrEqual(MIN_STEP);
      }
    }
  });

  it("an id of the other theme gives the default of the theme in use", () => {
    setTheme("light");
    expect(ramp(0.5, "magma")).toBe(ramp(0.5, "ylorrd"));
    expect(ramp(0.5, "")).toBe(ramp(0.5, "ylorrd"));
    setTheme("dark");
    expect(ramp(0.5, "ylorrd")).toBe(ramp(0.5, "magma"));
  });

  it("ramp direction: dark runs dark to bright; diverging is the same in both", () => {
    const L = (c: string) => lab(c)[0];
    setTheme("dark");
    for (const pal of paletteIds("dark")) {
      const ls = Array.from({ length: 9 }, (_, i) => L(ramp(i / 8, pal)));
      expect(ls, pal).toEqual([...ls].sort((a, b) => a - b));
    }
    setTheme("dark");
    const d = [0, 0.5, 1].map((t) => ramp(t, DIVERGING));
    setTheme("light");
    expect([0, 0.5, 1].map((t) => ramp(t, DIVERGING))).toEqual(d);
  });

  it("setTheme switches current", () => {
    setTheme("light");
    expect(currentName()).toBe("light");
  });
});
