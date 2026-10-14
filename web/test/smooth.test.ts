import { describe, expect, it } from "vitest";
import { classColours } from "../src/scales/scales";
import { lut } from "../src/map/gpu";
import { DEM_M, apron, boxMask, decode, demTiles, domainOf, excess, excessDomain, inside, levels, masked, sample, spread, landAt, toLngLat, toPixel, smoother, valueAt, type View } from "../src/map/smooth";

const meta = { lo: 2, hi: 4 };
const px = (q: number, f: number, a = 255) => [q >> 8, q & 255, f, a];
const geo = { w: 2048, h: 1144, north: 78, south: -58.235581691547694 };
/** A toy surface from rows of values; `land`: alpha and land fraction per pixel (default: all land). */
const view = (rows: number[][], land: [number, number][] = [], min = 255): View => {
  const vals = rows.flat();
  return { w: rows[0].length, h: rows.length, north: 80, south: -80, vals: new Float32Array(vals), min, dom: [0, 4], dec: { ...meta, sea: false, price: 1 },
    rgba: new Uint8Array(vals.flatMap((_, i) => [0, 0, land[i]?.[1] ?? 255, land[i]?.[0] ?? 255])) };
};

describe("decode", () => {
  const rgba = [...px(0, 255), ...px(65535, 255), ...px(32768, 128), ...px(0, 0, 0)];
  it("maps the 16-bit code to log10, undefined to NaN", () => {
    const v = decode(rgba, meta);
    expect([v[0], v[1]]).toEqual([2, 4]);
    expect(v[2]).toBeCloseTo(3, 3);
    expect(v[3]).toBeNaN();
  });
  it("sea counted adds log10 of the land fraction, a price factor adds its log10", () => {
    expect(decode(rgba, meta, true)[2]).toBeCloseTo(3 + Math.log10(128 / 255), 3);
    expect(decode(rgba, meta, false, 0.5)[0]).toBeCloseTo(2 + Math.log10(0.5), 6);
    expect(decode(rgba, meta, true)[1]).toBeCloseTo(4, 6);
  });
  it("a pixel without land (alpha 128) is decoded, and shown only if the sea is drawn", () => {
    const sea = [...px(51966, 77, 128), ...px(4660, 200), ...px(0, 0, 0)]; // three pixels in one row
    expect(decode(sea, meta)[0]).toBeCloseTo(2 + (51966 / 65535) * 2, 6);
    expect(decode(sea, meta)[2]).toBeNaN();
    const v = { ...view([[...decode(sea, meta)]]), rgba: new Uint8Array(sea) };
    expect([valueAt(v, -100, 0), valueAt({ ...v, min: 128 }, -100, 0)]).toEqual([undefined, 10 ** v.vals[0]]);
  });
});

describe("pixel mapping", () => {
  it("covers the span: the corners and edges are the longitude and latitude limits", () => {
    expect(toPixel(geo, -180, 78)).toEqual([0, 0]);
    expect(toPixel(geo, 180, geo.south)[0]).toBe(2048);
    expect(toPixel(geo, 180, geo.south)[1]).toBeCloseTo(1144, 6);
    expect(toLngLat(geo, 0, 0)).toEqual([-180, 78]);
    expect(toLngLat(geo, 2048, 1144)[1]).toBeCloseTo(geo.south, 6);
  });
  it("round-trips and puts London (51.51, -0.13) near the middle column, at the Mercator row", () => {
    const [x, y] = toPixel(geo, -0.13, 51.51);
    expect(x).toBeCloseTo(1023.4, 0);
    expect(y).toBeCloseTo(1144 * (Math.asinh(Math.tan(78 * Math.PI / 180)) - Math.asinh(Math.tan(51.51 * Math.PI / 180))) / (Math.asinh(Math.tan(78 * Math.PI / 180)) - Math.asinh(Math.tan(geo.south * Math.PI / 180))), 6);
    const [lng, lat] = toLngLat(geo, x, y);
    expect(lng).toBeCloseTo(-0.13, 9);
    expect(lat).toBeCloseTo(51.51, 9);
  });
  it("valueAt reads the pixel under a point; outside or undefined gives nothing", () => {
    const v = view([[3, NaN], [2, 1]], [[255, 255], [0, 0]]);
    expect(valueAt(v, -90, 60)).toBeCloseTo(1000);
    expect(valueAt(v, 90, 60)).toBeUndefined();
    expect(valueAt(v, 90, -60)).toBeCloseTo(10);
    expect(valueAt(v, 0, 85)).toBeUndefined();
  });
});

describe("colours", () => {
  it("the palette lookup of the surface: the class colours of the legend, or 256 steps for the gradient; opaque", () => {
    const cols = lut("magma", 5), hex = (i: number) => "#" + [...cols.slice(4 * i, 4 * i + 3)].map((b) => b.toString(16).padStart(2, "0")).join("");
    expect([0, 1, 2, 3, 4].map(hex)).toEqual(classColours("magma", 5));
    const grad = lut("viridis", 0), steps = new Set(Array.from({ length: 256 }, (_, i) => grad.slice(4 * i, 4 * i + 3).join()));
    expect([grad.length, steps.size > 200, cols.filter((_, i) => i % 4 === 3).every((a) => a === 255)]).toEqual([1024, true, true]);
  });
  it("the world domain is whole decades around the 1st to 99th percentile; fitted to a pixel box it is those percentiles of the box", () => {
    const v = view(Array.from({ length: 10 }, (_, y) => Array.from({ length: 20 }, (_, x) => (x < 10 ? 2.5 + y / 10 : 6.2 + y / 20)))); // west low, east high
    expect(domainOf(v)).toEqual([2, 7]);
    expect(spread(v, [10, 0, 20, 10])!.map((x) => +x.toFixed(2))).toEqual([6.2, 6.65]);
    expect(domainOf(v, [10, 0, 20, 10]).map((x) => +x.toFixed(2))).toEqual([6.2, 6.7]); // at least half a decade
    expect(domainOf(v, [-5, -5, 10, 30]).map((x) => +x.toFixed(1))).toEqual([2.5, 3.4]); // the box is cut to the surface
    const sea = view([[3, 3, 5, 5]], [[255, 255], [255, 255], [128, 0], [128, 0]]);
    expect(spread(sea)).toEqual([3, 3]); // pixels that are not shown do not count
    expect(spread({ ...sea, min: 128 })).toEqual([3, 3]); // nor do sea-only pixels (no land fraction), even when drawn
    expect([spread(sea, [2, 0, 4, 1]), domainOf(sea, [2, 0, 4, 1])]).toEqual([null, [3, 4]]); // nothing in view: the world domain
  });
});

describe("Include sea keeps the scale", () => {
  // land pixels of 1e5 (B 255, 128, 51) and sea-only pixels (alpha 128, B 0 or tiny land) of tiny values
  const q = (v: number) => Math.round(((v - 2) / 6) * 65535), rgba = [[5, 255, 255], [5, 128, 255], [5, 51, 255], [3, 0, 128], [2, 0, 128], [6, 255, 255]]
    .flatMap(([v, b, a]) => px(q(v), b, a)), m = { lo: 2, hi: 8 };
  const mk = (sea: boolean): View => ({ w: 6, h: 1, north: 80, south: -80, vals: decode(rgba, m, sea), rgba: Uint8Array.from(rgba), dec: { ...m, sea, price: 1 }, min: sea ? 128 : 255, dom: [0, 1] });
  it("the domain is the same with the sea on and off, and the land-only values are recovered", () => {
    const [on, off] = [mk(true), mk(false)];
    expect(on.vals[1]).toBeLessThan(off.vals[1] - 0.2); // the sea does dilute
    expect(domainOf(on)).toEqual(domainOf(off));
    expect(domainOf(on)).toEqual([5, 6]);
    expect(on.vals[2] - Math.log10(51 / 255)).toBeCloseTo(off.vals[2], 4);
    expect(domainOf(on, [0, 0, 6, 1])[0]).toBeCloseTo(domainOf(off, [0, 0, 6, 1])[0], 4);
  });
  it("Include sea lowers a pixel by log10 of its land share: not at all inland, by decades at a coast", () => {
    const [on, off] = [mk(true), mk(false)];
    expect(on.vals[0] - off.vals[0]).toBeCloseTo(0, 6); // B 255: far from water
    expect(on.vals[5] - off.vals[5]).toBeCloseTo(0, 6);
    expect(on.vals[1] - off.vals[1]).toBeCloseTo(Math.log10(128 / 255), 6); // B 128: half the reach is water
    expect(on.vals[2] - off.vals[2]).toBeCloseTo(Math.log10(51 / 255), 6);
    expect(domainOf(on)).toEqual(domainOf(off)); // and the colour scale does not move
  });
  it("the tooltip reads the land-only value under a point, only with the sea on", () => {
    const on = mk(true), at = (i: number) => landAt(on, ((i + 0.5) / 6) * 360 - 180, 0);
    expect(at(1)).toBeCloseTo(1e5, -2);
    expect(at(3)).toBeUndefined(); // a sea pixel
    expect(landAt(mk(false), -170, 0)).toBeUndefined();
  });
});

describe("local excess", () => {
  it("log10 of the surface minus the wider surface, read bilinearly at the pixel centres of the finer grid", () => {
    const wide = { w: 2, h: 1, vals: new Float32Array([4, 6]) }; // half the columns: pixel centres at 0.5 and 1.5
    expect([...excess(view([[5, 5, 5, 5]]), wide)]).toEqual([1, 0.5, -0.5, -1]); // 4, 4.5, 5.5, 6 around it
    expect([...excess(view([[5, 5]]), { ...wide, vals: new Float32Array([NaN, 6]) })]).toEqual([NaN, -1]);
    expect([...excess(view([[NaN]]), { w: 1, h: 1, vals: new Float32Array([3]) })]).toEqual([NaN]);
  });
  it("its domain is symmetric about 1x: half decades over the world, the percentiles of a box (at least a quarter decade)", () => {
    const v = view([[-0.3, 0.1, 0.2, 0.7, NaN]]);
    expect(excessDomain(v)).toEqual([-0.5, 0.5]); // percentiles -0.3 and 0.2 of four values
    expect(excessDomain({ ...v, vals: new Float32Array([-0.6, 0, 0.1, 0.2, 0]) })).toEqual([-1, 1]); // the larger side counts
    expect(excessDomain({ ...v, vals: new Float32Array([0, 0, 0, 0, 0]) })).toEqual([-0.5, 0.5]);
    expect(excessDomain(v, [0, 0, 3, 1]).map((x) => +x.toFixed(2))).toEqual([-0.3, 0.3]);
    expect(excessDomain(v, [1, 0, 3, 1])).toEqual([-0.25, 0.25]);
  });
});

describe("relief", () => {
  it("sample is bilinear between pixel centres and ignores undefined neighbours unless they weigh more than half", () => {
    const g = { w: 2, h: 2, vals: new Float32Array([0, 2, 4, NaN]) };
    expect([sample(g, 0.5, 0.5), sample(g, 1, 0.5), sample(g, 0.5, 1), sample(g, 0, 0)]).toEqual([0, 1, 2, 0]);
    expect(sample(g, 1, 1)).toBeCloseTo(2, 6); // mean of the three defined ones
    expect(sample(g, 1.5, 1.5)).toBeNaN();
  });
  // a row from inland to the open sea: land, the coast, sea near land (alpha 128), more sea, nothing in reach
  const coast = view([[5, 4.5, 4.5, 4, 3, NaN, NaN, NaN]], [[255, 255], [255, 140], [128, 90], [128, 8], [128, 2], [0, 0], [0, 0], [0, 0]]);
  const round = (g: { vals: Float32Array }) => [...g.vals].map((x) => +x.toFixed(4));
  /** Level `l` of the relief heights with the apron over the whole level, as a DEM tile reads it. */
  const heights = (v: View, lo: number, l = 0) => { const g = levels(v, lo)(l); return apron({ ...g, vals: Float32Array.from({ length: g.w * g.h }, (_, i) => g.at(i)) }); };
  it("heights: land keeps its own height to the coast, the sea beyond is an apron falling SLOPE per pixel to 0", () => {
    expect(round(heights(coast, 2))).toEqual([3, 2.5, 2.4, 2.3, 2.2, 2.1, 2, 1.9]);
    expect(round(heights({ ...coast, min: 128 }, 2))).toEqual([3, 2.5, 2.5, 2, 1, 0.9, 0.8, 0.7]); // the sea drawn: its own heights, the apron beyond
    expect(round(heights(coast, 6))).toEqual([0, 0, 0, 0, 0, 0, 0, 0]); // floor at the domain minimum
  });
  it("heights: an island is a round cone (16 directions), the apron never undercuts the land, a coarser level keeps a pixel if half of it is shown", () => {
    const sea = Array.from({ length: 7 }, () => Array(7).fill(0)), alpha = sea.flat().map((_, i): [number, number] => [i === 24 ? 255 : 128, 0]);
    sea[3][3] = 3;
    const cone = heights(view(sea, alpha), 0).vals, at = (dx: number, dy: number) => cone[(3 + dy) * 7 + 3 + dx];
    expect([at(0, 0), at(1, 0), at(0, -2), at(1, 1), at(2, 1), at(-1, 2), at(3, 3)].map((x) => +x.toFixed(4)))
      .toEqual([3, 2.9, 2.8, +(3 - 0.1 * Math.SQRT2).toFixed(4), +(3 - 0.1 * Math.sqrt(5)).toFixed(4), +(3 - 0.1 * Math.sqrt(5)).toFixed(4), +(3 - 0.1 * 3 * Math.SQRT2).toFixed(4)]);
    // the apron starts at the coast, never above it: an inland peak does not lift the sea beyond a lower coast
    expect(round(heights(view([[9, 1, 0]], [[255, 255], [255, 255], [128, 0]]), 0))).toEqual([9, 1, 0.9]);
    const row = <T,>(f: (x: number) => T) => Array.from({ length: 1024 }, (_, x) => f(x));
    const shownRow0 = row((x): [number, number] => [x % 4 === 1 ? 128 : 255, 0]).concat(row((): [number, number] => [128, 0])); // row 0 shown but every 4th from 1, row 1 not
    const wide = view([row((x) => x), row((x) => 2 * x)], shownRow0);
    expect([0, 1, 2].map((l) => levels(wide, 0)(l)).map((l) => [l.w, l.h])).toEqual([[1024, 2], [512, 1], [256, 0]]);
    // level 1: pixel 0 has one of four shown (0) and gets the apron of pixel 1, which has two (2, 3): 2.5
    expect(round({ vals: heights(wide, 0, 1).vals.slice(0, 2) })).toEqual([2.4, 2.5]);
  });
  it("DEM tiles: value -> RGB -> height in metres round-trips; the rows follow the latitude span", () => {
    const t = demTiles(view(Array.from({ length: 4 }, (_, y) => Array.from({ length: 8 }, (_, x) => 2 + x * 0.37 + y * 0.11))), 2)(0, 0, 0), m = (i: number, j: number) => (t[4 * (j * 256 + i)] << 16) | (t[4 * (j * 256 + i) + 1] << 8) | t[4 * (j * 256 + i) + 2];
    const merc = (lat: number) => Math.asinh(Math.tan((lat * Math.PI) / 180)), row = (lat: number) => Math.floor((0.5 - merc(lat) / (2 * Math.PI)) * 256);
    expect([m(16, row(84)), m(16, row(-84))]).toEqual([0, 0]); // beyond the surface
    for (const [x, y] of [[0, 0], [3, 1], [7, 3]]) { // near the pixel centres of the surface
      const lat = (Math.atan(Math.sinh(merc(80) - ((y + 0.5) / 4) * 2 * merc(80))) * 180) / Math.PI;
      expect(m(x * 32 + 16, row(lat)) / DEM_M).toBeCloseTo(x * 0.37 + y * 0.11, 1);
    }
    expect(m(112, 128) / DEM_M).toBeCloseTo((112.5 / 32 - 0.5) * 0.37 + 1.5 * 0.11, 2); // just below the equator, between rows 1 and 2
    expect(t[3]).toBe(255);
  });
  it("DEM tiles: the apron on a window around the tile equals the apron of the whole level, at every zoom", () => {
    let seed = 1;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647), island = Array.from({ length: 1024 * 512 }, () => rnd() < 0.002);
    const v = view(Array.from({ length: 512 }, (_, y) => Array.from({ length: 1024 }, (_, x) => (island[y * 1024 + x] ? 2 + 2 * rnd() : NaN))),
      island.map((on): [number, number] => (on ? [255, 255] : [0, 0]))); // heights up to 2 decades above the floor: cones 20 px wide
    const lazy = demTiles(v, 2), whole = demTiles(v, 2, Infinity);
    for (const z of [0, 1, 2]) for (let x = 0; x < 2 ** z; x++) for (let y = 0; y < 2 ** z; y++) expect(Buffer.from(lazy(z, x, y)).equals(Buffer.from(whole(z, x, y)))).toBe(true);
  });
});

describe("focus mask", () => {
  // 8 x 4 pixels over 80 N to 80 S: columns 45 degrees wide; values 0..7 along x, rows alike
  const rows = Array.from({ length: 4 }, () => Array.from({ length: 8 }, (_, x) => x));
  it("a box covers the pixels whose centre it holds", () => {
    const m = boxMask(view(rows), [-90, -80, 0, 80]); // columns 2 and 3, all rows
    expect([...m]).toEqual(Array.from({ length: 4 }, () => [0, 0, 1, 1, 0, 0, 0, 0]).flat());
    expect(boxMask(view(rows), [-90, 1, 0, 80]).filter(Boolean)).toHaveLength(4); // northern half: rows 0 and 1
  });
  it("masked pixels are not shown, not read, not in the domain; the scale fits what is inside", () => {
    const v = view(rows), world = domainOf(v), m = masked(v, boxMask(v, [135, -80, 180, 80])); // the last column, value 7
    expect(world).toEqual([0, 7]);
    expect(m.dom).toEqual([7, 8]);
    expect(valueAt(m, 170, 0)).toBeCloseTo(10 ** 7);
    expect(valueAt(m, -170, 0)).toBeUndefined();
    expect(valueAt(v, -170, 0)).toBeCloseTo(1);
    expect(inside(m, 170, 0)).toBe(true);
    expect(inside(m, -170, 0)).toBe(false);
    expect(inside(v, -170, 0)).toBe(true);
  });
  it("the local excess is masked alike", () => {
    const v = { ...view(rows), ex: view(rows) }, m = masked(v, boxMask(v, [0, -80, 45, 80]));
    expect(m.ex!.mask).toBe(m.mask);
    expect(valueAt(m.ex!, 20, 0)).toBeDefined();
    expect(valueAt(m.ex!, -20, 0)).toBeUndefined();
  });
});

describe("smoother", () => {
  const m = { lo: 2, hi: 4, north: 80, south: -80, kernels: ["inv2", "gauss"], indicators: { gdp_per_km2: { prefix: "", lo: 2, hi: 4 }, pop_density: { prefix: "pop_", lo: -3, hi: 5 }, gdp_per_capita: { prefix: "pcap_", lo: 1, hi: 2 } } };
  it("reads each indicator's file set with its own range; the local excess of the same code at both radii is 0", async () => {
    const urls: string[] = [], get = smoother(m, async (id) => { urls.push(id); return { w: 1, h: 1, rgba: new Uint8Array([255, 255, 255, 255]) }; });
    expect((await get("gdp_per_km2", "inv2", 50, false, 1)).vals[0]).toBeCloseTo(4, 6);
    expect((await get("pop_density", "gauss", 15, false, 1)).vals[0]).toBeCloseTo(5, 6);
    expect((await get("gdp_per_capita", "inv2", 30, false, 1)).vals[0]).toBeCloseTo(2, 6);
    const t = await get("pop_density", "inv2", 100, true, 1, 150);
    expect([t.dec.lo, t.dec.hi]).toEqual([-3, 5]);
    expect(t.ex!.vals[0]).toBeCloseTo(0, 6);
    expect(urls.filter((u, i) => urls.indexOf(u) === i)).toEqual(["inv2_50", "pop_gauss_15", "pcap_inv2_30", "pop_inv2_100", "pop_gauss_150"]);
  });
});
