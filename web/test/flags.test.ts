import { existsSync, readFileSync } from "node:fs";
import { beforeAll, describe, expect, it } from "vitest";
import { parse } from "../src/data/data";
import { flagText, flagUrl } from "../src/data/flags";

const row = { id: "x", name: "X", level_no: 3, parent_id: null, iso2: "", flags: [], gdp_year: 2019, pop_year: 2016 };

describe("flagText", () => {
  it("fills in the years", () => {
    expect(flagText("gdp_year_offset", row, 2024)).toBe("GDP shares are from 2019, not 2024.");
    expect(flagText("pop_year_offset", row, 2024)).toBe("Population is from 2016, not 2024.");
  });
  it("says what an aggregated or disputed row is, and reads a partial population as a lower bound", () => {
    expect(flagText("aggregated", row, 2024)).toBe("Sum of the regions below it.");
    expect(flagText("contains_estimate", row, 2024)).toMatch(/^Some regions below it are estimates/);
    expect(flagText("contains_wikipedia_secondary", row, 2024)).toContain("Wikipedia");
    expect(flagText("contains_wikidata", row, 2024)).toContain("Wikidata");
    expect(flagText("partial_population", row, 2024)).toBe("Population is a lower bound: some sub-regions have no figure.");
    expect(flagText("disputed", row, 2024)).toMatch(/^Disputed territory/);
  });
  it("explains the flags of the finer data", () => {
    expect(flagText("census_va_share", row, 2024)).toMatch(/census value added, not official regional GDP/);
    expect(flagText("remainder", row, 2024)).toMatch(/outside the listed metro areas/);
  });
  it("says in plain words what a derived or scaled population is", () => {
    const zone = { ...row, flags: ["pop_share", "wikipedia_secondary"] };
    expect(flagText("pop_share", zone, 2024)).toMatch(/^GDP split by population \(derived\).*GDP per capita is the national value by construction/);
    expect(flagText("pop_scaled", row, 2024)).toBe("Population scaled to the national total.");
    expect(flagText("pop_secondary", row, 2024)).toMatch(/republisher of the official census/);
    expect(flagText("wikipedia_secondary", zone, 2024)).toMatch(/^Population comes from a Wikipedia/);
    expect(flagText("wikipedia_secondary", row, 2024)).toMatch(/^GDP comes from a Wikipedia/);
    expect(flagText("contains_pop_share", row, 2024)).toMatch(/split the national GDP by population/);
  });
  it("degrades gracefully for an unknown flag", () =>
    expect(flagText("brand_new_flag", row, 2024)).toBe("Note: brand new flag."));
});

describe("flagUrl", () => {
  it("finds the SVG by ISO2 code in either case; no code or an unknown code has none", () => {
    expect(flagUrl("DE")).toMatch(/de[^/]*\.svg/);
    expect(flagUrl("de")).toBe(flagUrl("DE"));
    expect(flagUrl("")).toBeUndefined();
    expect(flagUrl("ZZ")).toBeUndefined();
  });
});

const path = new URL("../public/indicators.json", import.meta.url);
describe.skipIf(!existsSync(path))("real indicators.json", () => {
  let d!: ReturnType<typeof parse>; // read only when the file exists: a skipped describe still runs its body
  beforeAll(() => { d = parse(JSON.parse(readFileSync(path, "utf8"))); });
  it("every flag that occurs has its own readable text", () => {
    const seen = new Set([...d.rows.values()].flatMap((r) => r.flags));
    expect(seen.size).toBeGreaterThan(5);
    for (const f of seen) expect(flagText(f, row, d.ref), f).not.toMatch(/^Note:/);
  });
  it("every country code has a flag; only continents and the disputed region have no code", () => {
    for (const r of d.rows.values()) expect(!!flagUrl(r.iso2), r.id).toBe(!/^(CONT|DISPUTED):/.test(r.id));
  });
});
