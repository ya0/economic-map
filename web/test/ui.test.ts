import { describe, expect, it } from "vitest";
import { chain, cover, coverage, parse } from "../src/data/data";
import { DIVERGING, INDICATORS, ramp, times } from "../src/scales/scales";
import { NOTES, thinTicks, chipsHtml, coverageLine, legendHtml, panelHtml, smoothTipHtml, resultsHtml, stripHtml, tipHtml, tipPos, type Source } from "../src/ui/ui";
import fixture from "./fixture.json";

const d = parse(fixture);
const row = (id: string) => d.rows.get(id)!;
const src = new Map<string, Source>([
  ["eurostat_nuts3_gdp", { source_id: "eurostat_nuts3_gdp", name: "n", publisher: "Eurostat", licence: "", url: "https://e.u", role: "" }],
]);
const panel = (id: string, coarser = false, base: number | null = null) => panelHtml(row(id), chain(d, id).slice(0, -1), coarser, d, src, base);

describe("stripHtml", () => {
  it("one line: lowest value, a gradient or the class swatches, highest value", () => {
    const g = stripHtml(INDICATORS[0], [2, 4], null, "", null);
    expect(g).toMatch(/^<span>≤[^<]+<\/span><span class="sw"><i style="background:linear-gradient/);
    expect(g).toMatch(/<span>≥[^<]+<\/span>$/);
    const c = stripHtml(INDICATORS[0], [2, 4], null, "", [2.5, 3, 3.5]);
    expect(c.match(/<i /g)).toHaveLength(4);
    expect(c).toMatch(/^<span>&#60;/);
  });
});

describe("ui text", () => {
  it("coverage line is computed from the cover shown", () => {
    expect(coverageLine(coverage(d, cover(d, 3), true))).toBe("4 regions hold 95.0% of world GDP, 75.0% below country level.");
    expect(coverageLine({ n: 5584, all: 0.998, sub: 0.912 })).toBe("5,584 regions hold 99.8% of world GDP, 91.2% below country level.");
  });
  it("legend labels each break with currency and shows the no-data and disputed keys", () => {
    const html = legendHtml(INDICATORS[0], [2, 4]);
    for (const s of ["$100", "$10k", "No data", "Disputed"]) expect(html).toContain(s);
  });
  it("no hatch key; the below-country share appears only where the map can show it (finer than countries)", () => {
    expect(legendHtml(INDICATORS[0], [2, 4])).not.toContain("hatch");
    expect(coverageLine({ n: 218, all: 1, sub: 0 })).toBe("218 regions hold 100.0% of world GDP.");
  });
  it("legend of the local excess: multiples of the surroundings on the diverging palette, 1x in the middle", () => {
    const html = legendHtml({ key: "excess", label: "x", unit: "x times its surroundings", money: false, fmt: times }, [-1, 1], null, DIVERGING);
    for (const s of ["≤0.1×", "left:50%\">1×", "≥10×", "x times its surroundings, log scale", ramp(0, DIVERGING)]) expect(html).toContain(s);
    expect(html).not.toContain("US$");
  });
  it("legend marks the clamped ends so saturation is not silent", () => {
    const html = legendHtml(INDICATORS[0], [2, 4]);
    expect(html).toContain("≤$100");
    expect(html).toContain("≥$10k");
  });
  it("tooltip flips to stay inside the viewport", () => {
    expect(tipPos(100, 100, 200, 80, 1000, 800)).toEqual([114, 114]);
    expect(tipPos(900, 750, 200, 80, 1000, 800)).toEqual([686, 656]);
    expect(tipPos(5, 5, 2000, 2000, 1000, 800)).toEqual([0, 0]);
  });
  it("tooltip shows flag, name, value and flags in words", () => {
    const html = tipHtml(row("NUTS2024:AA1"), INDICATORS[0], 2024);
    expect(html).toMatch(/<img class="flag" src="[^"]*de[^"]*\.svg[^"]*" alt="">Region A/);
    expect(html).toContain("$120 per km²");
    expect(html).toContain("GDP shares are from 2023, not 2024.");
    expect(tipHtml(row("ISO3:DDD"), INDICATORS[0], 2024)).toContain("No data");
  });
  it("area_computed and aggregated are click-panel details, not tooltip noise", () => {
    expect(tipHtml(row("ISO3:CCC"), INDICATORS[0], 2024)).toContain("one whole country");
    expect(tipHtml(row("ISO3:CCC"), INDICATORS[0], 2024)).not.toContain("Area is computed");
    expect(panel("ISO3:CCC")).toContain("Area is computed");
    expect(panel("ISO3:CCC")).toContain("no regional data"); // the whole-country note replaces the old hatching
    expect(tipHtml(row("OECD:AA"), INDICATORS[0], 2024)).not.toContain("Sum of the regions");
    expect(tipHtml(row("OECD:AA"), INDICATORS[0], 2024)).toContain("lower bound");
    expect(panel("OECD:AA")).toContain("Sum of the regions below it.");
    const tip = tipHtml(row("ISO3:BBB"), INDICATORS[0], 2024); // an aggregated row keeps the estimate caution, not the provenance notes
    expect(tip).toContain("estimates or models");
    expect(tip).not.toContain("Wikipedia");
    expect(panel("ISO3:BBB")).toContain("Wikipedia");
  });
  it("the disputed region says so and shows no values and no flag image", () => {
    for (const html of [tipHtml(row("DISPUTED:z"), INDICATORS[0], 2024), panel("DISPUTED:z")]) {
      expect(html).toContain("Disputed territory");
      expect(html).not.toMatch(/No data|no data|<table|<img/);
    }
    expect(panel("CONT:east")).not.toContain("<img");
  });
  it("panel lists values with year and linked source, and escapes names", () => {
    const html = panelHtml({ ...row("NUTS2024:AA1"), name: "<b>X</b>" }, [], false, d, src);
    expect(html).toContain("&#60;b&#62;X");
    expect(html).toContain('href="https://e.u"');
    expect(html).toContain("2023");
    expect(panel("CONT:east")).toContain("several sources");
  });
  it("panel breadcrumb is the parent chain, each part a button with the parent's id", () => {
    const html = panel("NUTS2024:AA1");
    expect([...html.matchAll(/<button type="button" data-id="([^"]+)">([^<]+)</g)].map((m) => [m[1], m[2]])).toEqual(
      [["CONT:east", "East"], ["ISO3:AAA", "Aland"], ["OECD:AA", "Alpha"]]);
    expect(panel("CONT:east")).not.toContain("data-id");
  });
  it("panel names the level and marks a region shown coarser than the level asked for", () => {
    expect(panel("NUTS2024:AA1")).toContain('<p class="sub">Sub-region</p>');
    expect(panel("WP:BB-x", true)).toContain('<p class="sub">Region (finest available)</p>');
    expect(panel("ISO3:CCC", true)).toContain('<p class="sub">Country (finest available)</p>');
  });
  it("panel for a region without GDP says no data instead of NaN", () => {
    expect(panel("ISO3:DDD")).toContain("no data");
    expect(panel("ISO3:DDD")).not.toContain("NaN");
  });
  it("constant-dollar values are labelled with the base year, current US$ stays unlabelled in the tooltip", () => {
    const r = row("NUTS2024:AA1");
    expect(legendHtml(INDICATORS[0], [2, 4], 2000)).toContain("constant 2000 US$");
    expect(legendHtml(INDICATORS[0], [2, 4])).toContain("current US$");
    expect(tipHtml(r, INDICATORS[0], 2024, 2000)).toContain("constant 2000 US$");
    expect(tipHtml(r, INDICATORS[0], 2024)).not.toContain("US$");
    expect(tipHtml(r, INDICATORS[2], 2024, 2000)).not.toContain("US$");
    expect(panel("NUTS2024:AA1", false, 2000)).toContain("constant 2000 US$");
  });
  it("lists escape names, show the flag, and results give level and parent and mark the active option", () => {
    const html = resultsHtml([{ ...row("WP:BB-x"), name: "<i>" }, row("CONT:west")], 0, d);
    expect(html).not.toContain("<i>");
    expect(html).toMatch(/ng[^"]*\.svg/);
    expect(html).toContain('aria-selected="true"');
    expect(html).toContain("<small>Region, Bland</small>");
    expect(html).toContain("<small>Continent</small>");
  });
  it("focus: chips, the panel button in its three states, result buttons, the scale named in the legend", () => {
    expect(chipsHtml([], true)).toContain("Area<button");
    expect(chipsHtml([], true)).not.toContain("data-id");
    expect(legendHtml(INDICATORS[0], [2, 4], null, "magma", null, true)).toContain("Cut at the border");
    expect(legendHtml(INDICATORS[0], [2, 4])).not.toContain("Cut at the border");
    expect(legendHtml(INDICATORS[0], [2, 4], null, "magma", null, false, true)).toContain("Include sea: divided by all area within reach");
    expect(legendHtml(INDICATORS[0], [2, 4])).not.toContain("Include sea");
    expect(legendHtml(INDICATORS[0], [2, 4], null, "magma", null, false, false, NOTES.derived)).toContain("their GDP per capita is the national value");
    expect(legendHtml(INDICATORS[0], [2, 4])).not.toContain("Derived regions");
    expect(chipsHtml([{ id: "CONT:east", name: "East" }])).toContain('data-id="CONT:east" aria-label="Remove East from focus">×');
    expect(panel("NUTS2024:AA1")).toContain("Focus on Region A");
    expect(panelHtml(row("NUTS2024:AA1"), [], false, d, src, null, ["CONT:west"])).toContain("Add Region A to focus");
    expect(panelHtml(row("NUTS2024:AA1"), [], false, d, src, null, ["NUTS2024:AA1"])).toContain("Remove from focus");
    const html = resultsHtml([row("WP:BB-x"), row("CONT:west")], 0, d, ["CONT:west"], (r) => r.id === "WP:BB-x");
    expect(html).toContain('data-f="WP:BB-x" aria-pressed="false"');
    expect(html).toContain('data-f="CONT:west" aria-pressed="true"');
    expect(html).toContain('class="out"');
  });
  it("smoothed tooltip: value, reach, local excess against its surroundings, land only", () => {
    expect(smoothTipHtml(1e6, INDICATORS[0], 25, undefined, 3.16, 200)).toContain('<div class="ex">3.2× its surroundings<small>within about 200 km (Gaussian)</small></div>');
    expect(smoothTipHtml(1e6, INDICATORS[0], 25)).not.toContain('class="ex"');
    expect(smoothTipHtml(1e5, INDICATORS[0], 25, undefined, undefined, undefined, 1e6)).toContain("land only: $1M per km², 10% land within reach");
    expect(smoothTipHtml(1e5, INDICATORS[0], 25)).not.toContain("land only");
  });
});

describe("derived region words", () => {
  const zone = { id: "ZONE:DZA-1", name: "Algeria: dense core", level_no: 2, parent_id: "ISO3:DZA", iso2: "", gdp_usd: 1e9, pop: 5e6, pop_raw: 4e6, flags: ["pop_share", "pop_scaled", "pop_year_offset"], pop_year: 2008, gdp_per_km2: 10 };
  it("the tooltip says derived, scaled and the census year; an ordinary scaled region does not mention scaling", () => {
    const tip = tipHtml(zone, INDICATORS[0], 2024);
    for (const t of ["GDP split by population (derived)", "national value by construction", "Population scaled to the national total", "Population is from 2008, not 2024"]) expect(tip).toContain(t);
    expect(tipHtml({ ...zone, flags: ["pop_scaled"] }, INDICATORS[0], 2024)).not.toContain("scaled");
  });
});

describe("thinTicks", () => {
  it("drops a label that would touch its neighbour, keeps the last one", () => {
    expect(thinTicks([[0, "≤$10k"], [0.2, "$100k"], [0.4, "$1M"], [0.6, "$10M"], [0.8, "$100M"], [1, "≥$1B"]], 282).map(([, t]) => t)).toEqual(["≤$10k", "$1M", "$10M", "$100M", "≥$1B"]);
  });
  it("keeps everything that fits", () => expect(thinTicks([[0, "≤$100"], [0.5, "$1k"], [1, "≥$10k"]], 280)).toHaveLength(3));
});
