import { existsSync, readFileSync } from "node:fs";
import { beforeAll, describe, expect, it } from "vitest";
import { basisLabel, chain, cover, coverage, inFocus, parse, priceFactor, rescale, standIn, valueOf } from "../src/data/data";
import { domain } from "../src/scales/scales";
import fixture from "./fixture.json";

const d = parse(fixture);
const ids = (no: number) => cover(d, no).map((r) => r.id).sort();
const gdp = (no: number, data = d) => cover(data, no).reduce((a, r) => a + (r.gdp_usd ?? 0), 0);

describe("parse", () => {
  it("joins columns by name per region and reads the reference year", () => {
    expect(d.ref).toBe(2024);
    expect(d.rows.size).toBe(11);
    expect(d.rows.get("NUTS2024:AA1")).toMatchObject({ id: "NUTS2024:AA1", gdp_usd: 600, gdp_per_km2: 120, gdp_year: 2023, flags: ["gdp_year_offset"], level_no: 3, name: "Region A" });
  });
  it("world GDP is one cover plus unallocated, not the sum of all rows", () => expect(d.worldGdp).toBe(1000));
});

describe("cover", () => {
  it("is the level, the coarser regions with nothing finer, and the disputed region", () => {
    expect(ids(0)).toEqual(["CONT:east", "CONT:west", "DISPUTED:z"]);
    expect(ids(1)).toEqual(["DISPUTED:z", "ISO3:AAA", "ISO3:BBB", "ISO3:CCC", "ISO3:DDD"]);
    expect(ids(2)).toEqual(["DISPUTED:z", "ISO3:CCC", "ISO3:DDD", "OECD:AA", "WP:BB-x"]);
    expect(ids(3)).toEqual(["DISPUTED:z", "ISO3:CCC", "ISO3:DDD", "NUTS2024:AA1", "NUTS2024:AA2", "WP:BB-x"]);
  });
  it("holds the same world GDP at every level", () => expect([0, 1, 2, 3].map((no) => gdp(no))).toEqual([950, 950, 950, 950]));
});

describe("coverage", () => {
  it("counts the regions with GDP and their share of world GDP, in total and below country level", () => {
    expect(coverage(d, cover(d, 3), true)).toEqual({ n: 4, all: 0.95, sub: 0.75 });
    expect(coverage(d, cover(d, 2), true)).toEqual({ n: 3, all: 0.95, sub: 0.75 });
    expect(coverage(d, cover(d, 1), true)).toEqual({ n: 3, all: 0.95, sub: 0 });
    expect(coverage(d, cover(d, 0), true)).toEqual({ n: 2, all: 0.95, sub: 0 });
  });
  it("drops estimates and, below continent level, the sums that contain one when estimates are off", () => {
    expect(coverage(d, cover(d, 3), false)).toEqual({ n: 3, all: 0.85, sub: 0.65 });
    expect(coverage(d, cover(d, 1), false)).toEqual({ n: 2, all: 0.85, sub: 0 });
    expect(coverage(d, cover(d, 0), false)).toEqual({ n: 2, all: 0.95, sub: 0 });
  });
});

describe("derived regions (pop_share)", () => {
  const row = (id: string, parent_id: string | null, level_no: number, flags: string[], gdp_usd: number) => ({ id, parent_id, level_no, flags, gdp_usd, name: id, iso2: "", gdp_per_km2: gdp_usd / 10 });
  const z = parse({ meta: { ref_year: 2024, columns: [] }, regions: {} });
  for (const r of [row("ISO3:DZA", null, 1, ["aggregated", "contains_pop_share"], 100), row("ZONE:DZA-1", "ISO3:DZA", 2, ["pop_share"], 60), row("ZONE:DZA-2", "ISO3:DZA", 2, ["pop_share"], 40)]) z.rows.set(r.id, r);
  z.worldGdp = 200;
  const zones = [z.rows.get("ZONE:DZA-1")!, z.rows.get("ZONE:DZA-2")!];
  it("with Estimates off a zone stands for its country, which is itself never hidden", () => {
    expect(standIn(z, zones[0], true).id).toBe("ZONE:DZA-1");
    expect(standIn(z, zones[0], false).id).toBe("ISO3:DZA");
    expect(valueOf(z.rows.get("ISO3:DZA"), "gdp_per_km2", false)).toBe(10);
    expect(valueOf(zones[0], "gdp_per_km2", false)).toBeUndefined();
  });
  it("coverage counts the country once", () => {
    expect(coverage(z, zones, true)).toEqual({ n: 2, all: 0.5, sub: 0.5 });
    expect(coverage(z, zones, false)).toEqual({ n: 1, all: 0.5, sub: 0 });
  });
});

describe("chain", () => {
  it("lists the ancestors from the continent down to the region", () => {
    expect(chain(d, "NUTS2024:AA1").map((r) => r.name)).toEqual(["East", "Aland", "Alpha", "Region A"]);
    expect(chain(d, "DISPUTED:z").map((r) => r.id)).toEqual(["CONT:east", "DISPUTED:z"]);
    expect(chain(d, "CONT:west")).toHaveLength(1);
    expect(chain(d, "nope")).toEqual([]);
  });
});

describe("valueOf", () => {
  it("returns the value, or undefined for missing, unknown or non-positive", () => {
    expect(valueOf(d.rows.get("NUTS2024:AA1"), "gdp_per_km2", true)).toBe(120);
    expect(valueOf(d.rows.get("ISO3:DDD"), "gdp_per_km2", true)).toBeUndefined();
    expect(valueOf(undefined, "gdp_per_km2", true)).toBeUndefined();
  });
  it("hides estimates only when the toggle is off", () => {
    const wp = d.rows.get("WP:BB-x");
    expect(valueOf(wp, "pop", true)).toBe(50);
    expect(valueOf(wp, "pop", false)).toBeUndefined();
  });
  it("a country that sums estimates is hidden with them, a continent stays", () => {
    const of = (id: string, estimates: boolean) => valueOf(d.rows.get(id), "gdp_usd", estimates);
    expect([of("ISO3:BBB", true), of("ISO3:BBB", false)]).toEqual([100, undefined]);
    expect([of("CONT:east", true), of("CONT:east", false)]).toEqual([750, 750]);
    expect(cover(d, 1).filter((r) => of(r.id, false)).map((r) => r.id)).toEqual(["ISO3:AAA", "ISO3:CCC"]); // what the top list ranks
  });
});

describe("constant dollars", () => {
  const row = d.rows.get("NUTS2024:AA1")!;
  it("factor is deflator[base]/deflator[ref]; current US$ and the reference year leave values unchanged", () => {
    expect(priceFactor(d, null)).toBe(1);
    expect(priceFactor(d, 2024)).toBe(1);
    expect(priceFactor(d, 2000)).toBe(0.5);
  });
  it("rescales money columns only; population, density and area stay", () => {
    const r = rescale(row, 0.5);
    expect([r.gdp_usd, r.gdp_per_km2, r.gdp_per_capita]).toEqual([300, 60, 30]);
    expect([r.pop, r.pop_density, r.area_km2]).toEqual([10, 2, 5]);
    expect(rescale(row, priceFactor(d, 2024))).toEqual(row);
    expect(valueOf(row, "gdp_usd", true, 0.5)).toBe(300);
    expect(valueOf(row, "pop", true, 0.5)).toBe(10);
  });
  it("labels the basis", () => {
    expect(basisLabel(null)).toBe("current US$");
    expect(basisLabel(2000)).toBe("constant 2000 US$");
  });
});

const path = new URL("../public/indicators.json", import.meta.url);
describe.skipIf(!existsSync(path))("real indicators.json", () => {
  let real!: ReturnType<typeof parse>; // read only when the file exists: a skipped describe still runs its body
  beforeAll(() => { real = parse(JSON.parse(readFileSync(path, "utf8"))); });
  it("every level covers the same world GDP (values carry 4 significant digits)", () => {
    for (const no of [0, 1, 2]) expect(gdp(no, real) / gdp(3, real)).toBeCloseTo(1, 3);
    expect(gdp(3, real) / real.worldGdp).toBeGreaterThan(0.99);
    expect(cover(real, 0)).toHaveLength(7);
  });
  it("the finest cover is every region that is nobody's parent, and every chain starts at a continent", () => {
    expect(cover(real, 3).map((r) => r.id).sort()).toEqual([...real.leaves].sort());
    for (const r of real.rows.values()) expect(chain(real, r.id).map((x) => x.level_no)[0], r.id).toBe(0);
  });
});

describe("focus", () => {
  const focused = (no: number, ...focus: string[]) => cover(d, no).filter((r) => inFocus(d, r, new Set(focus))).map((r) => r.id).sort();
  it("a row is in focus by its own id or an ancestor's; no focus is everything", () => {
    expect(focused(3)).toEqual(ids(3));
    expect(focused(3, "CONT:east")).toEqual(["DISPUTED:z", "NUTS2024:AA1", "NUTS2024:AA2", "WP:BB-x"]);
    expect(focused(3, "CONT:west")).toEqual(["ISO3:CCC", "ISO3:DDD"]);
    expect(focused(3, "ISO3:BBB", "CONT:west")).toEqual(["ISO3:CCC", "ISO3:DDD", "WP:BB-x"]);
    expect(focused(1, "OECD:AA")).toEqual([]); // a descendant of the focus is in, an ancestor is not
    expect(focused(0, "CONT:east")).toEqual(["CONT:east", "DISPUTED:z"]);
  });
  it("the colour domain of the focused rows is computed from them alone", () => {
    const gdp = (rows: string[]) => domain(rows.map((id) => d.rows.get(id)!.gdp_usd).filter((v) => v > 0));
    expect(gdp(focused(3, "CONT:east"))).toEqual([1, 2]); // GDP 50, 100, 600
    expect(gdp(ids(3))).not.toEqual([1, 2]); // the world adds ISO3:CCC
  });
});
