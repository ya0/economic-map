import { describe, expect, it } from "vitest";
import { ALL_PALETTES, SMOOTH, seaFor, DIVERGING, INDICATORS, breaks, classColours, domain, fmt, fmtValue, manual, painter, parseAmount, ramp, stops, ticks, times, withUnit } from "../src/scales/scales";

describe("domain", () => {
  it("rounds the 1st-99th percentile out to whole decades (log10)", () => {
    const v = Array.from({ length: 100 }, (_, i) => 30 * 10 ** (i / 33)); // 30 .. ~30000
    expect(domain(v)).toEqual([1, 5]);
  });
  it("ignores non-positive values and keeps at least one decade", () => {
    expect(domain([0, -5, 100, 100, 100])).toEqual([2, 3]);
  });
});

describe("ticks", () => {
  it("labels every decade for a short range", () => expect(ticks([2, 6])).toEqual([2, 3, 4, 5, 6]));
  it("thins a wide range to at most 7 labels, keeping the lower bound", () => {
    const t = ticks([-2, 10]);
    expect(t[0]).toBe(-2);
    expect(t.length).toBeLessThanOrEqual(7);
  });
  it("a fitted domain: both ends, the decades between unless they crowd an end; below two decades also the 3s", () => {
    expect(ticks([4.3, 7.9])).toEqual([4.3, 5, 6, 7, 7.9]);
    expect(ticks([4.9, 8.05])).toEqual([4.9, 6, 7, 8.05]);
    expect(ticks([5.3, 6.6]).map((e) => +(10 ** e).toPrecision(3))).toEqual([200e3, 300e3, 1e6, 3.98e6]);
  });
});

describe("stops", () => {
  it("spans the domain with rising log values and one colour per stop", () => {
    const s = stops([1, 9], 5);
    expect(s.map(([v]) => v)).toEqual([1, 3, 5, 7, 9]);
    expect(s[0][1]).toBe(ramp(0));
    expect(new Set(s.map(([, c]) => c)).size).toBe(5);
  });
});

describe("breaks", () => {
  const items: [number, number][] = [[1, 1], [10, 1], [100, 2]];
  it("log: n equal classes over the domain", () => {
    expect(breaks(4, "log", [0, 4], [])).toEqual([1, 2, 3]);
    expect(breaks(3, "log", [2, 8], [])).toEqual([4, 6]);
  });
  it("share: each class holds an equal share of the weight; the crossing region stays in the lower class", () => {
    expect(breaks(2, "share", [0, 2], items)).toEqual([2]); // {1, 10} weigh 2 of 4, {100} the other 2
    expect(breaks(2, "share", [0, 3], [[1, 1], [2, 1], [3, 1], [4, 1]])).toEqual([Math.log10(3)]);
  });
  it("share: fewer distinct values than classes give fewer, strictly rising breaks; no spread falls back to equal log steps", () => {
    expect(breaks(4, "share", [0, 2], items)).toEqual([1, 2]);
    expect(breaks(3, "share", [0, 3], [[5, 1], [5, 1], [5, 1]])).toEqual([1, 2]);
    for (const n of [3, 5, 7]) {
      const b = breaks(n, "share", [0, 4], Array.from({ length: 50 }, (_, i) => [1 + i * i, 1 + (i % 7)]));
      expect(b.length).toBe(n - 1);
      expect(b.every((x, i) => i === 0 || x > b[i - 1])).toBe(true);
    }
  });
});

describe("palettes", () => {
  it("each palette gives n distinct class colours, lowest to highest", () => {
    for (const p of ALL_PALETTES) expect(new Set(classColours(p, 5)).size).toBe(5);
    expect(classColours("magma", 3)[0]).toBe(ramp(0, "magma"));
    expect(classColours("viridis", 3)[2]).toBe(ramp(1, "viridis"));
  });
});

describe("diverging palette", () => {
  it("runs from blue to red through a light middle at 1x, and is not offered as a palette", () => {
    const [lo, mid, hi] = [0, 0.5, 1].map((t) => ramp(t, DIVERGING).match(/\d+/g)!.map(Number));
    expect(lo[2]).toBeGreaterThan(lo[0]);
    expect(hi[0]).toBeGreaterThan(hi[2]);
    expect(Math.min(...mid)).toBeGreaterThan(230);
    expect(ALL_PALETTES).not.toContain(DIVERGING);
    expect([-1, -0.5, 0, Math.log10(3.16), 1.2].map((e) => times(10 ** e))).toEqual(["0.1×", "0.32×", "1×", "3.2×", "16×"]);
  });
});

describe("formatting", () => {
  it.each([[0.5, "0.5"], [12, "12"], [1234, "1.23k"], [4.56e6, "4.56M"], [7.8e9, "7.8B"], [2.5e12, "2.5T"]])(
    "fmt(%s) = %s", (v, s) => expect(fmt(v)).toBe(s));
  it("adds currency and unit", () => {
    const [perKm2, , , gdp, pop] = INDICATORS;
    expect(fmtValue(1e6, perKm2)).toBe("$1M");
    expect(withUnit(8.5e6, perKm2)).toBe("$8.5M per km²");
    expect(withUnit(1.17e10, gdp)).toBe("$11.7B");
    expect(withUnit(223000, pop)).toBe("223k people");
  });
});

describe("painter", () => {
  const hex = (c: string) => (c[0] === "#" ? c : "#" + c.match(/\d+/g)!.map((x) => (+x).toString(16).padStart(2, "0")).join(""));
  const rgb = (c: string) => [1, 3, 5].map((i) => parseInt(hex(c).slice(i, i + 2), 16));
  it("holds the log value and the relief height above the domain floor; no data is null, grey and flat", () => {
    const p = painter([3, 9], null, "magma", "#4a5059");
    expect(p(1e6)).toMatchObject({ v: 6, h: 3 });
    expect(p(10)).toMatchObject({ v: 1, h: 0 });
    expect(p(undefined)).toEqual({ v: null, c: "#4a5059", h: 0 });
  });
  it("gradient: the stop colours at the stops, clamped at the ends, lerped in RGB between them", () => {
    const p = painter([3, 9], null, "viridis", "#000"), st = stops([3, 9], 9, "viridis");
    for (const [x, c] of st) expect(p(10 ** x).c).toBe(hex(c));
    expect(p(1).c).toBe(hex(st[0][1]));
    expect(p(1e12).c).toBe(hex(st[8][1]));
    const [a, b] = [st[2][1], st[3][1]].map(rgb), mid = p(10 ** ((st[2][0] + st[3][0]) / 2)).c;
    expect(mid).toBe("#" + a.map((x, i) => Math.round((x + b[i]) / 2).toString(16).padStart(2, "0")).join(""));
  });
  it("classes: one colour and one height per class, by the breaks", () => {
    const p = painter([3, 9], [5, 7], "magma", "#000"), cols = classColours("magma", 3).map(hex);
    expect([p(1e4), p(1e5), p(1e8)].map((s) => s.c)).toEqual(cols);
    expect([p(1e4), p(1e5), p(1e8)].map((s) => s.h)).toEqual([2, 4, 6]);
  });
  it("manual range: amounts with suffixes, reversed or partial ranges", () => {
    expect(parseAmount("1M")).toBeCloseTo(6);
    expect(parseAmount("$2.5e6")).toBeCloseTo(Math.log10(2.5e6));
    expect(parseAmount("100 k")).toBeCloseTo(5);
    expect(parseAmount("3×")).toBeCloseTo(Math.log10(3));
    expect([parseAmount("0"), parseAmount("-5"), parseAmount("abc"), parseAmount("")]).toEqual([null, null, null, null]);
    expect(manual([3, 8], 5, 7)).toEqual([5, 7]);
    expect(manual([3, 8], 5, null)).toEqual([5, 8]);
    expect(manual([3, 8], 9, null)).toEqual([3, 8]); // reversed: ignored
  });
});

describe("smoothed indicators", () => {
  it("three indicators read a surface set of their own", () => {
    expect(Object.keys(SMOOTH).sort()).toEqual(["gdp_per_capita", "gdp_per_km2", "pop_density"]);
    expect(Object.entries(SMOOTH).every(([k, v]) => v.src === k)).toBe(true);
  });
  it("Include sea: the user's for densities, off for per capita", () => {
    expect([["gdp_per_km2", false], ["pop_density", true], ["gdp_per_capita", true]].map(([k, u]) => seaFor(k as string, u as boolean))).toEqual([false, true, false]);
  });
});
