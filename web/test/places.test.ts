import { existsSync, readFileSync } from "node:fs";
import { beforeAll, describe, expect, it } from "vitest";
import { parse, type Row } from "../src/data/data";
import { bounds, inBox, mainlandBounds, meeting, meets, rings, search } from "../src/data/places";
import fixture from "./fixture.json";

const sq = (x: number, y: number, s: number) => [{ x, y }, { x: x + s, y }, { x: x + s, y: y + s }, { x, y: y + s }];
const layer = (fs: [string, { x: number; y: number }[][]][]) =>
  ({ extent: 2048, length: fs.length, feature: (i: number) => ({ properties: { region_id: fs[i][0] }, loadGeometry: () => fs[i][1] }) });

describe("bounds", () => {
  it("come from the region's largest ring, in lng/lat, also when the region repeats in the tile", () => {
    const b = bounds(layer([["a", [sq(0, 0, 50)]], ["b", [sq(0, 0, 2048)]], ["a", [sq(1000, 1000, 500), sq(10, 10, 5)]]]), "a")!;
    expect(b[0]).toBeCloseTo((1000 / 2048) * 360 - 180);
    expect(b[2]).toBeCloseTo((1500 / 2048) * 360 - 180);
    expect(b[1]).toBeLessThan(b[3]);
  });
  it("clamp to the world and are null for an unknown region", () => {
    expect(bounds(layer([["a", [sq(-50, -50, 100)]]]), "a")![0]).toBeCloseTo(-180);
    expect(bounds(layer([["a", [sq(0, 0, 2048)]]]), "a")).toEqual([-180, expect.closeTo(-85.05, 1), 180, expect.closeTo(85.05, 1)]);
    expect(bounds(layer([]), "a")).toBeNull();
  });
});

describe("mainlandBounds", () => {
  it("France: Corsica stays, Guiana and Reunion are overseas", () => {
    const r = mainlandBounds([[-5, 42, 8, 51], [8.5, 41.4, 9.6, 43], [-54, 2, -51.6, 5.7], [55.2, -21.4, 55.8, -20.9]])!;
    expect(r).toEqual({ bounds: [-5, 41.4, 9.6, 51], overseas: true });
  });
  it("USA: the contiguous states are the mainland whatever their GDP, Alaska and Hawaii are overseas", () => {
    const r = mainlandBounds([[-125, 25, -67, 49], [-170, 52, -141, 71], [-160, 18.9, -154.8, 22.2], [-80, 25, -79, 26]])!;
    expect(r).toEqual({ bounds: [-125, 25, -67, 49], overseas: true });
  });
  it("Norway: Svalbard lies 1,600 km from the centre of the mainland, so it is not overseas", () => {
    const r = mainlandBounds([[4.5, 58, 31, 71], [10, 76.5, 34, 80.8]])!;
    expect(r).toEqual({ bounds: [4.5, 58, 34, 80.8], overseas: false });
  });
  it("a country without outliers or without rings", () => {
    expect(mainlandBounds([[0, 0, 1, 1]])).toEqual({ bounds: [0, 0, 1, 1], overseas: false });
    expect(mainlandBounds([])).toBeNull();
  });
});

describe("area", () => {
  const b: [number, number, number, number] = [0, 0, 10, 10];
  it("bounds overlap, edges count; a point is inside, also on another copy of the world", () => {
    expect(meets(b, [10, 10, 20, 20])).toBe(true);
    expect(meets(b, [10.1, 0, 20, 5])).toBe(false);
    expect(meets(b, [-5, -5, 20, 20])).toBe(true);
    expect(inBox(b, 5, 5)).toBe(true);
    expect(inBox(b, 5, 11)).toBe(false);
    expect(inBox(b, 365, 5)).toBe(true);
    expect(inBox(b, -355, 5)).toBe(true);
    expect(inBox(b, 11, 5)).toBe(false);
  });
  it("regions meeting a box are found by any ring, rings come back in the unit square", () => {
    const l = layer([["a", [sq(0, 0, 50)]], ["b", [sq(0, 0, 50), sq(1500, 1000, 100)]], ["c", [sq(100, 100, 50)]]]);
    expect(meeting(l, [100, -10, 120, 10])).toEqual(["b"]); // the second ring of b is at lng 100..., lat 0
    expect(meeting(l, [-180, -85, 180, 85]).sort()).toEqual(["a", "b", "c"]);
    expect(meeting(l, [170, 80, 175, 85])).toEqual([]);
    const r = rings(l, ["b"]);
    expect(r).toHaveLength(1);
    expect(r[0]).toHaveLength(2);
    expect(r[0][1][0]).toEqual([1500 / 2048, 1000 / 2048]);
  });
});

const d = parse(fixture);
const names = (q: string, limit?: number) => search(d.rows.values(), q, limit).map((r) => r.name);

describe("search", () => {
  it("ranks exact, then prefix, then word start, then substring", () => {
    expect(names("alpha")).toEqual(["Alpha", "Alpha Bay"]);
    expect(names("bay")).toEqual(["Alpha Bay"]);
    expect(names("region b")).toEqual(["Region B"]);
    expect(names("a")).toEqual(["Aland", "Alpha", "Alpha Bay", "Region A", "East", "Cland", "Bland", "Dland"]);
  });
  it("orders a match class by total GDP, regions without GDP last", () => {
    expect(names("lan")).toEqual(["Aland", "Cland", "Bland", "Dland"]);
    expect(names("region")).toEqual(["Region A", "Region B"]);
  });
  it("finds every level by name: continents, countries, regions and the disputed region", () => {
    expect(search(d.rows.values(), "bland")[0].id).toBe("ISO3:BBB");
    expect(search(d.rows.values(), "WEST")[0].id).toBe("CONT:west");
    expect(search(d.rows.values(), "zed")[0].id).toBe("DISPUTED:z");
  });
  it("ignores accents, returns nothing for empty or unmatched queries and honours the limit", () => {
    expect(search([{ id: "x", name: "Île-de-France" } as Row], "ile")).toHaveLength(1);
    expect(names("  ")).toEqual([]);
    expect(names("zzz")).toEqual([]);
    expect(names("a", 2)).toHaveLength(2);
  });
});

const path = new URL("../public/indicators.json", import.meta.url);
describe.skipIf(!existsSync(path))("search in the real indicators.json", () => {
  let rows!: Row[]; // read only when the file exists: a skipped describe still runs its body
  beforeAll(() => { rows = [...parse(JSON.parse(readFileSync(path, "utf8"))).rows.values()]; });
  it("a country name finds the country first", () => {
    expect(search(rows, "germany")[0].id).toBe("ISO3:DEU");
    expect(search(rows, "india")[0].id).toBe("ISO3:IND");
    expect(search(rows, "united")[0].id).toBe("ISO3:USA");
  });
});
