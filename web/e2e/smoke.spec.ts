import { opts, sec, unfold } from "./ui";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const state = (page: Page, id: string, layer = "l3") =>
  page.evaluate(([id, sourceLayer]) => (window as any).__map.getFeatureState({ source: "regions", sourceLayer, id }), [id, layer]);
const loaded = (page: Page) => page.waitForFunction(() => (window as any).__map?.loaded());
const open = async (page: Page, hash = "") => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => { (window as any).copy2d = (c: HTMLCanvasElement) => { const t = document.createElement("canvas"); [t.width, t.height] = [c.width, c.height]; const g = t.getContext("2d")!; g.drawImage(c, 0, 0); return g; }; }); // the surface canvas is WebGL: its pixels are read through a 2D copy
  await page.goto("/" + hash);
  await loaded(page);
  return errors;
};
const map = (page: Page, js: string) => page.evaluate((js) => new Function("m", "return " + js)((window as any).__map), js);
/** Screen position of a place, once the map has settled there. */
const at = (page: Page, lngLat: [number, number]) => page.evaluate((p) => (window as any).__map.project(p), lngLat);
const scaleTo = async (page: Page, kind: string) => {
  await unfold(page);
  await page.click(`#seg [data-s="${kind}"]`);
};
const find = async (page: Page, text: string) => {
  await page.fill("#q", text);
  await page.press("#q", "Enter");
};

test("loads, switches indicator, recolours, opens a panel, toggles estimates", async ({ page }) => {
  const errors = await open(page, "#c=5/50/10");
  await expect(page.locator("#cover")).toContainText("of world GDP");
  await expect(page.locator("#legend")).toContainText("GDP per km²");
  await sec(page, "sd");
  const before = (await state(page, "FIPS:06037")).v;
  expect(before).toBeGreaterThan(0);

  await page.selectOption("#ind", "pop");
  await expect(page.locator("#legend")).toContainText("Population");
  expect((await state(page, "FIPS:06037")).v).not.toBe(before);
  expect(page.url()).toContain("i=pop");

  const { x, y } = await at(page, [10, 50.5]);
  await page.mouse.click(x, y);
  await expect(page.locator("#panel")).toBeVisible();
  await expect(page.locator("#panel h2")).not.toBeEmpty();
  await expect(page.locator("#panel h2 img.flag")).toHaveAttribute("src", /de[^/]*\.svg/);
  expect(page.url()).toContain("s=");

  await sec(page, "sd");
  await page.uncheck("#est");
  expect((await state(page, "WP:NGA-lagos-state")).v).toBeNull();
  await sec(page, "sd");
  await page.check("#est");
  expect((await state(page, "WP:NGA-lagos-state")).v).toBeGreaterThan(0);
  await sec(page, "sd");
  await page.selectOption("#level", "1"); // a country that sums estimates goes with them, a continent stays
  expect((await state(page, "ISO3:NGA", "l1")).v).toBeGreaterThan(0);
  await sec(page, "sd");
  await page.uncheck("#est");
  expect((await state(page, "ISO3:NGA", "l1")).v).toBeNull();
  expect((await state(page, "ISO3:GHA", "l1")).v).toBeGreaterThan(0);
  await sec(page, "sd");
  await page.selectOption("#level", "0");
  expect((await state(page, "CONT:africa", "l0")).v).toBeGreaterThan(0);
  await sec(page, "sd");
  await page.check("#est");

  await sec(page, "sa");
  await page.click("#credits-btn");
  await expect(page.locator("#credits")).toContainText("World Bank");
  expect(errors).toEqual([]);
});

test("Estimates off: a derived zone of Algeria shows the country whole (tooltip, panel, one colour); on, the zones differ", async ({ page }) => {
  const errors = await open(page, "#c=5/32/3");
  const [core, sparse] = ["ZONE:DZA-1", "ZONE:DZA-3"], dense: [number, number] = [3.05, 36.75], sahara: [number, number] = [4, 27];
  expect((await state(page, core)).c).not.toBe((await state(page, sparse)).c);
  await expect(page.locator("#legend")).toContainText("Derived regions split the national GDP by population");
  let p = await at(page, dense);
  await page.mouse.move(p.x, p.y);
  await expect(page.locator("#tip")).toContainText("Algeria: dense core");
  await expect(page.locator("#tip")).toContainText("GDP split by population (derived)");
  await sec(page, "sd");
  await sec(page, "sd");
  await page.uncheck("#est");
  expect((await state(page, core)).c).toBe((await state(page, sparse)).c);
  await expect(page.locator("#legend")).not.toContainText("Derived regions");
  await page.mouse.move(0, 0);
  p = await at(page, sahara);
  await page.mouse.move(p.x, p.y);
  await expect(page.locator("#tip b")).toHaveText(/Algeria$/);
  await expect(page.locator("#tip")).not.toContainText("sparse");
  await page.mouse.click(p.x, p.y);
  await expect(page.locator("#panel h2")).toHaveText(/Algeria$/);
  await expect(page.locator("#panel")).not.toContainText("GDP split by population");
  await sec(page, "sd");
  await page.check("#est");
  expect((await state(page, core)).c).not.toBe((await state(page, sparse)).c);
  expect(errors).toEqual([]);
});

test("relief toggle tilts and resets, search selects a region, base year relabels", async ({ page }) => {
  const errors = await open(page);
  await sec(page, "sd");
  await page.check("#relief");
  await expect.poll(() => map(page, "m.getPitch()")).toBeGreaterThan(40);
  expect(await map(page, 'm.getLayoutProperty("relief3", "visibility")')).toBe("visible");
  expect(page.url()).toContain("r=1");
  await page.check("#globe");
  expect(await map(page, "m.getProjection().type")).toBe("globe");
  await page.uncheck("#globe");
  await page.uncheck("#relief");
  await expect.poll(() => map(page, "m.getPitch()")).toBe(0);

  await page.fill("#q", "suffolk, m");
  await expect(page.locator("#results li").first()).toContainText("Suffolk, MA");
  await page.press("#q", "Enter");
  await expect(page.locator("#panel h2")).toContainText("Suffolk");
  expect(page.url()).toContain("s=FIPS");
  await expect.poll(() => map(page, "m.getZoom()")).toBeGreaterThan(5);

  await sec(page, "sd");
  await page.selectOption("#base", "2000");
  await expect(page.locator("#legend")).toContainText("constant 2000 US$");
  await expect(page.locator("#panel")).toContainText("constant 2000 US$");
  expect(page.url()).toContain("b=2000");
  // constant dollars rescale map colour/height state and tooltip, not just legend and panel (LA: $95.9M per km2 x 72.722/125.587)
  expect((await state(page, "FIPS:06037")).v).toBeCloseTo(Math.log10((95922316 * 72.722) / 125.587), 2);
  await map(page, "m.jumpTo({ center: [-118.25, 34.05], zoom: 6 })");
  await loaded(page);
  const la = await at(page, [-118.25, 34.05]);
  await page.mouse.move(la.x + 2, la.y + 2);
  await page.mouse.move(la.x, la.y);
  await expect(page.locator("#tip")).toContainText("$55.5M");
  await page.selectOption("#ind", "pop_density");
  await sec(page, "sd");
  await expect(page.locator("#base")).toBeDisabled();
  await expect(page.locator("#lg")).not.toContainText("US$");
  expect(errors).toEqual([]);
});

test("each level redraws its own layer, legend and a sane coverage line", async ({ page }) => {
  const errors = await open(page);
  await expect(page.locator("#level option")).toHaveText(["Continents", "Countries", "Regions", "Sub-regions"]);
  await expect(page.locator("#level")).toHaveValue("3"); // the finest level is the default
  const seen: Record<string, { n: number; legend: string }> = {};
  for (const [l, id] of [["0", "CONT:europe"], ["1", "ISO3:DEU"], ["2", "OECD:DE2"], ["3", "NUTS2024:DE212"]]) {
    const coarse = l === "0" || l === "1";
    await sec(page, "sd");
    await page.selectOption("#level", l);
    expect(page.url().includes("l=")).toBe(l !== "3");
    expect(await map(page, 'm.getStyle().layers.filter((x) => x.type === "fill-extrusion" && x.source === "regions").map((x) => x["source-layer"]).join()')).toBe("l" + l);
    expect((await state(page, id, "l" + l)).v).toBeGreaterThan(0);
    const [n, all, sub = 0] = (await page.locator("#cover").innerText()).replace(/,/g, "").match(/\d+(?:\.\d+)?/g)!.map(Number);
    expect(all).toBeGreaterThan(99);
    expect(all).toBeLessThanOrEqual(100);
    expect(sub).toBeLessThan(all);
    expect(sub > 85).toBe(!coarse);
    expect(sub === 0).toBe(coarse);
    await expect(page.locator("#legend .keys i")).toHaveCount(2); // no data, disputed: nothing is hatched
    seen[l] = { n, legend: await page.locator("#legend .ticks").innerText() };
  }
  expect(seen["0"].n).toBe(6);
  for (const l of ["1", "2", "3"]) expect(seen[l].n).toBeGreaterThan(5 * seen[String(Number(l) - 1)].n > 1000 ? 1000 : 5 * seen[String(Number(l) - 1)].n);
  expect(new Set(["0", "1", "2", "3"].map((l) => seen[l].legend)).size).toBeGreaterThan(1); // the scale domain follows the level: continents differ (countries to sub-regions share 3 to 9 decades)
  expect(errors).toEqual([]);
});

test("globe: hover and click select regions at every level", async ({ page }) => {
  test.slow(); // the globe on software GL: 8 to 25 s per level on a busy machine
  const errors = await open(page, "#g=1&c=3/30/40");
  const saudi = await at(page, [45, 24]), india = await at(page, [78, 22]); // a country (in zones from level 2) and a subdivided one
  for (const [l, whole, split] of [["0", "Asia", "Asia"], ["1", "Saudi Arabia", "India"], ["2", "Saudi Arabia: Ar Riyad", "Madhya Pradesh"], ["3", "Saudi Arabia: Ar Riyad", "Madhya Pradesh"]]) {
    await sec(page, "sd");
    await page.selectOption("#level", l);
    await loaded(page);
    for (const [p, name] of [[saudi, whole], [india, split]] as const) {
      await page.mouse.move(p.x + 2, p.y + 2);
      await page.mouse.move(p.x, p.y);
      await expect(page.locator("#tip b")).toHaveText(name);
      await page.mouse.click(p.x, p.y);
      await expect(page.locator("#panel h2")).toHaveText(name);
      if (name === "Saudi Arabia") await expect(page.locator("#panel .sub")).toHaveText("Country");
      await page.click("#panel .x"); // the panel would cover India
    }
  }
  expect(errors).toEqual([]);
});

test("search finds countries by name and switches level; breadcrumb selects the parents; disputed region", async ({ page }) => {
  const errors = await open(page, "#s=NUTS2024:DE212");
  await expect(page.locator("#panel h2")).toContainText("München");
  await expect(page.locator(".crumbs button")).toHaveText(["Europe", "Germany", "Bavaria"]);
  await page.click(".crumbs button >> text=Bavaria");
  await expect(page.locator("#panel h2")).toHaveText("Bavaria");
  await expect(page.locator("#level")).toHaveValue("2");
  expect(page.url()).toContain("l=2");
  expect(page.url()).toContain("s=OECD:DE2");
  await sec(page, "sd");
  await page.selectOption("#level", "1"); // a coarser level moves the selection to its ancestor
  await expect(page.locator("#panel h2")).toHaveText("Germany");

  await sec(page, "sd");
  await page.selectOption("#level", "3");
  await expect(page.locator("#panel")).toBeHidden();
  await page.fill("#q", "germany");
  await expect(page.locator("#results li").first()).toContainText("Germany");
  await expect(page.locator("#results li").first()).toContainText("Country, Europe");
  await expect(page.locator("#results li img.flag").first()).toHaveAttribute("src", /de[^/]*\.svg/);
  await page.press("#q", "Enter");
  await expect(page.locator("#panel h2")).toHaveText("Germany");
  await expect(page.locator("#level")).toHaveValue("1");
  await expect.poll(async () => (await state(page, "ISO3:DEU", "l1")).sel).toBe(true); // the selection outline follows the feature-state flag

  await find(page, "texas"); // a hit of another level replaces the open panel
  await expect(page.locator("#panel h2")).toHaveText("Texas");
  await expect(page.locator("#level")).toHaveValue("2");
  await page.click(".crumbs button >> text=North America");
  await expect(page.locator("#panel h2")).toHaveText("North America");
  await expect(page.locator("#level")).toHaveValue("0");
  await expect(page.locator("#panel h2 img")).toHaveCount(0);

  await find(page, "crimea"); // shown at every level, so the level stays
  await expect(page.locator("#panel")).toContainText("Disputed territory");
  await expect(page.locator("#panel table")).toHaveCount(0);
  await expect(page.locator("#level")).toHaveValue("0");
  expect(errors).toEqual([]);
});

test("palette and discrete classes: legend swatches, step paint, break rule, URL", async ({ page }) => {
  const errors = await open(page);
  const swatches = () => page.locator("#legend .classes i").evaluateAll((es) => es.map((e) => getComputedStyle(e).backgroundColor));
  const painted = async (id: string) => { const c = (await state(page, id)).c as string; return `rgb(${[1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16)).join(", ")})`; }; // the region's colour, as CSS writes it
  const gradient = await painted("FIPS:06037");
  await sec(page, "sc");
  await page.selectOption("#cls", "5");
  await sec(page, "sc");
  await page.selectOption("#pal", "viridis");
  await expect(page.locator("#legend .classes i")).toHaveCount(5);
  expect(await swatches()).toContain(await painted("FIPS:06037")); // the map paints the class swatch, not the gradient colour
  expect(await swatches()).not.toContain(gradient);
  expect(await map(page, 'm.getPaintProperty("relief3", "fill-extrusion-height")[0]')).toBe("interpolate");
  expect(page.url()).toContain("p=viridis&k=5");
  await expect(page.locator("#brk option")).toHaveText(["Equal log steps", "Equal share of GDP"]);
  const log = await page.locator("#legend .classes").innerText();
  await sec(page, "sc");
  await page.selectOption("#brk", "share");
  expect(page.url()).toContain("q=share");
  await expect(page.locator("#legend .classes i")).toHaveCount(5);
  expect(await page.locator("#legend .classes").innerText()).not.toBe(log);
  await page.selectOption("#ind", "pop");
  await expect(page.locator("#brk option").nth(1)).toHaveText("Equal share of people");
  await sec(page, "sc");
  await page.selectOption("#cls", "0");
  await sec(page, "sc");
  await expect(page.locator("#brk")).toBeHidden();
  await expect(page.locator("#legend .bar")).toBeVisible();
  expect(errors).toEqual([]);
});

test("no hatching; Borders (Map card) hides the region outlines only", async ({ page }) => {
  const errors = await open(page);
  expect(await map(page, 'm.getStyle().layers.some((l) => /hatch/.test(l.id)) || m.hasImage("hatch")')).toBe(false);
  expect(await map(page, "m.getLayer('country3').sourceLayer")).toBe("l1");
  await expect(page.locator("#borders")).toBeChecked();
  await page.uncheck("#borders");
  expect(await map(page, 'm.getLayoutProperty("borders3", "visibility")')).toBe("none");
  expect(await map(page, 'm.getLayoutProperty("country3", "visibility") ?? "visible"')).toBe("visible");
  expect(page.url()).toContain("o=0");
  await page.check("#borders");
  expect(await map(page, 'm.getLayoutProperty("borders3", "visibility")')).toBe("visible");
  await sec(page, "sd");
  await page.selectOption("#level", "1");
  expect(await map(page, "m.getLayer('country1')")).toBeUndefined(); // countries are their own outlines
  expect(errors).toEqual([]);
});

test("panels: Smoothing options only with Smoothed and collapsed, Colours and Palette mirror the legend's; one section open at a time and remembered", async ({ page }) => {
  const errors = await open(page, "#c=5/50/10");
  await expect(page.locator("#smopts")).toBeHidden();
  await expect(page.locator("#mode-r")).toBeChecked();
  await page.check("#smooth");
  await expect(page.locator("#smopts")).toBeVisible();
  await expect(page.locator("#smopts")).not.toHaveAttribute("open", "");
  await expect(page.locator("#sk")).toBeHidden();
  await opts(page);
  for (const id of ["#sk", "#sr", "#ss", "#lx", "#cls2", "#pal2"]) await expect(page.locator(id)).toBeVisible();
  await page.selectOption("#cls2", "4"); // one state, two renderings
  await page.selectOption("#pal2", "viridis");
  await expect(page.locator("#cls")).toHaveValue("4");
  await expect(page.locator("#pal")).toHaveValue("viridis");
  expect(page.url()).toContain("p=viridis&k=4");
  await page.selectOption("#ind", "gdp_per_capita");
  await expect(page.locator("#legend")).toContainText("GDP per capita, smoothed");
  await expect(page.locator("#ss")).toBeDisabled(); // greyed for per capita
  await page.check("#mode-r");
  await page.check("#smooth");
  await expect(page.locator("#smopts")).not.toHaveAttribute("open", ""); // collapsed each time it appears
  for (const id of ["#sc", "#sd", "#sa"]) await expect(page.locator(id)).not.toHaveAttribute("open", "");
  for (const id of ["#level", "#base", "#est", "#theme", "#pal", "#cmin"]) await expect(page.locator(id)).toBeHidden();
  await expect(page.locator("#lg")).toBeVisible();
  await expect(page.locator("#seg button")).toHaveText(["Auto", "World", "View"]);
  await sec(page, "sd");
  for (const id of ["#level", "#base", "#est"]) await expect(page.locator(id)).toBeVisible();
  await sec(page, "sa");
  await expect(page.locator("#theme")).toBeVisible();
  await expect(page.locator("#sd")).not.toHaveAttribute("open", ""); // one at a time
  await expect(page.locator("#level")).toBeHidden();
  await page.reload();
  await loaded(page);
  await expect(page.locator("#sa")).toHaveAttribute("open", ""); // the open section is remembered
  await page.goto("/#c=5/50/10&p=viridis&k=5&l=1"); // palette, classes and level from a link
  await page.reload();
  await loaded(page);
  await sec(page, "sd");
  await expect(page.locator("#level")).toHaveValue("1");
  await sec(page, "sc");
  await expect(page.locator("#pal")).toHaveValue("viridis");
  await expect(page.locator("#cls")).toHaveValue("5");
  expect(errors).toEqual([]);
});

test("tab order: header (fold, Show, switch), Focus area, Hide panels, Map card (fold, search, toggles, Export image), legend card (fold, scale, sections)", async ({ page }) => {
  await open(page);
  await page.focus("#head .chev");
  for (const sel of ["#ind", "#mode-r", "#area", "#ui-btn", "#tools .chev", "#q", "#globe", "#relief", "#borders", "#export-btn", "#legend .chev", '#seg [data-s="auto"]', '#seg [data-s="view"]', "#sc summary", "#sd summary", "#sa summary"]) {
    await page.keyboard.press("Tab");
    await expect(page.locator(sel)).toBeFocused();
  }
});

test("every card folds and unfolds; the choice is remembered", async ({ page }) => {
  await open(page);
  const cards: [string, string][] = [["head", "#cover"], ["tools", "#globe"], ["legend", "#lg"]];
  for (const [id, inner] of cards) {
    const chev = page.locator(`#${id} .chev`);
    await expect(chev).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator(`#${id} ${inner}`)).toBeVisible();
    await chev.click();
    await expect(chev).toHaveAttribute("aria-expanded", "false");
    await expect(page.locator(`#${id} ${inner}`)).toBeHidden();
    await expect(page.locator(`#${id} h1, #${id} h2`).first()).toBeVisible();
    if (id === "legend") { // folded, the card keeps one line of the legend: lowest value, colours, highest value
      await expect(page.locator("#strip .sw")).toBeVisible();
      await expect(page.locator("#strip")).toContainText("≥");
    } else await expect(page.locator("#strip")).toBeHidden();
  }
  if (process.env.SHOTS) await page.screenshot({ path: process.env.SHOTS + "/folded.png" });
  await page.reload();
  await loaded(page);
  for (const [id] of cards) await expect(page.locator(`#${id} .chev`)).toHaveAttribute("aria-expanded", "false");
  await page.click("#head .chev");
  await expect(page.locator("#cover")).toBeVisible();
  await expect(page.locator("#ind")).toBeVisible();
  // a selected region's panel folds too
  const { x, y } = await at(page, [10, 50.5]);
  await page.mouse.click(x, y);
  await expect(page.locator("#panel table")).toBeVisible();
  await page.click("#panel .chev");
  await expect(page.locator("#panel table")).toBeHidden();
  await expect(page.locator("#panel h2")).toBeVisible();
});

test("Hide panels: button and H key, in the URL, kept on reload; tooltip and credits stay", async ({ page }) => {
  const errors = await open(page, "#c=5/50/10");
  await expect(page.locator("#ui-btn")).toHaveText("Hide panels");
  await page.click("#ui-btn");
  await expect(page.locator("#ui-btn")).toHaveText("Show panels");
  expect(page.url()).toContain("ui=0");
  for (const id of ["#head", "#legend", "#q", "#globe"]) await expect(page.locator(id)).toBeHidden();
  await expect(page.locator("#credits-link")).toBeVisible();
  const { x, y } = await at(page, [10, 50.5]);
  await page.mouse.move(x + 3, y + 3);
  await page.mouse.move(x, y);
  await expect(page.locator("#tip")).toBeVisible();
  if (process.env.SHOTS) await page.screenshot({ path: process.env.SHOTS + "/hidden.png" });
  await page.click("#credits-link");
  await expect(page.locator("#credits")).toBeVisible();
  await page.keyboard.press("h"); // typed in a dialog: ignored
  await expect(page.locator("#credits")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.reload();
  await loaded(page);
  await expect(page.locator("#head")).toBeHidden();
  await page.click("#ui-btn");
  await expect(page.locator("#head")).toBeVisible();
  expect(page.url()).not.toContain("ui=0");
  await page.focus("#q");
  await page.keyboard.type("h"); // typing in the search box does not toggle
  await expect(page.locator("#head")).toBeVisible();
  await page.locator("#q").blur();
  await page.keyboard.press("H");
  await expect(page.locator("#head")).toBeHidden();
  expect(page.url()).toContain("ui=0");
  await page.keyboard.press("h");
  await expect(page.locator("#head")).toBeVisible();
  expect(errors).toEqual([]);
});

test("phone: hidden panels leave the map, Show panels and the credits link", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 740 });
  await open(page, "#ui=0");
  await expect(page.locator("#ui-btn")).toBeVisible();
  await expect(page.locator("#credits-link")).toBeVisible();
  await expect(page.locator("#legend")).toBeHidden();
  if (process.env.SHOTS) await page.screenshot({ path: process.env.SHOTS + "/hidden-phone.png" });
});

/** Tooltip value text under a place of the smoothed view: centre it, hover it; null when the tooltip stays hidden.
 * The value needs no tiles, so only `tiles` waits for them (the region name in the tooltip). */
const smoothText = async (page: Page, p: [number, number], tiles = false) => {
  await map(page, `m.jumpTo({ center: [${p[0]}, ${p[1]}], zoom: 4 })`);
  if (tiles) await loaded(page);
  const { x, y } = await at(page, p);
  await page.mouse.move(x + 3, y + 3);
  await page.mouse.move(x, y);
  return (await page.locator("#tip").isVisible()) ? page.locator("#tip .v").innerText() : null;
};
/** The dollar value of the tooltip ("$12.3M per km²"), null when it is hidden. */
const smoothAt = async (page: Page, p: [number, number], tiles = false) => {
  const text = await smoothText(page, p, tiles);
  if (text === null) return null;
  const [, n, suffix] = text.match(/\$([\d.]+)([kMBT]?)/)!;
  return Number(n) * ({ "": 1, k: 1e3, M: 1e6, B: 1e9, T: 1e12 } as Record<string, number>)[suffix];
};
const LONDON: [number, number] = [-0.13, 51.51], PARIS: [number, number] = [2.35, 48.86], SAHARA: [number, number] = [12, 23], ATLANTIC: [number, number] = [-40, 30];
const OAHU: [number, number] = [-157.95, 21.48], ZURICH: [number, number] = [8.54, 47.37], OFF_PORTUGAL: [number, number] = [-10.2, 39.5]; // 60 km off the coast
const visibility = (page: Page, id: string) => map(page, `m.getLayoutProperty("${id}", "visibility")`);

test("smoothed view: gradient canvas, tooltip values, kernel radius and sea controls", async ({ page }) => {
  test.slow();
  const errors = await open(page);
  await expect(page.locator("#smopts")).toBeHidden();
  await page.check("#smooth");
  await expect(page.locator("#legend")).toContainText("smoothed (inverse square, 50 km), derived");
  await expect(page.locator("#legend .classes i")).toHaveCount(6); // switching Smoothing on gives 6 discrete classes
  await expect(page.locator("#cls")).toHaveValue("6");
  expect(page.url()).toContain("k=6");
  await opts(page);
  await page.selectOption("#sr", "100");
  expect(page.url()).toContain("v=s");
  expect(await map(page, '!!m.getSource("smc")')).toBe(true);
  expect(await visibility(page, "smc")).toBe("visible");
  await expect(page.locator("#ind")).toBeEnabled();
  await expect(page.locator("#ind")).toHaveValue("gdp_per_km2");
  await expect(page.locator("#smopts")).toBeVisible();
  await expect(page.locator("#brklbl")).toBeHidden();
  expect(await map(page, 'm.getPaintProperty("fill3", "fill-opacity")')).toBe(0);

  const london = (await smoothAt(page, LONDON))!, sahara = (await smoothAt(page, SAHARA))!;
  expect(london).toBeGreaterThan(sahara * 10);
  expect(await smoothAt(page, ATLANTIC)).toBeNull();
  await expect(page.locator("#tip")).toBeHidden();
  await smoothAt(page, LONDON, true);
  await expect(page.locator("#tip")).toContainText("within about 100 km");
  await expect(page.locator("#tip")).toContainText("London"); // the region under the cursor, if any
  await page.mouse.click(...(Object.values(await at(page, LONDON)) as [number, number])); // click still selects a region
  await expect(page.locator("#panel")).toBeVisible();

  expect(await smoothAt(page, OFF_PORTUGAL)).toBeNull(); // clipped to land by default
  await opts(page);
  await page.check("#ss"); // Include sea draws over the water too
  expect(page.url()).toContain("ss=1");
  expect((await smoothAt(page, OFF_PORTUGAL))!).toBeGreaterThan(0);
  expect(await smoothAt(page, ATLANTIC)).toBeNull(); // no land within reach
  await opts(page);
  await page.uncheck("#ss");
  expect(await smoothAt(page, OFF_PORTUGAL)).toBeNull();

  await opts(page);
  await page.selectOption("#sr", "150");
  await expect(page.locator("#legend")).toContainText("150 km");
  expect((await smoothAt(page, LONDON))!).toBeLessThan(london);
  await opts(page);
  await page.selectOption("#sr", "100");
  await expect(page.locator("#legend")).toContainText("100 km");

  const [oahu, zurich] = [(await smoothAt(page, OAHU))!, (await smoothAt(page, ZURICH))!];
  await opts(page);
  await page.check("#ss");
  await expect(page.locator("#legend")).toContainText("per km² incl. sea");
  expect(page.url()).toContain("ss=1");
  expect((await smoothAt(page, OAHU))!).toBeLessThan(oahu / 2);
  expect((await smoothAt(page, ZURICH))!).toBeGreaterThan(zurich * 0.9);
  await page.check("#mode-r");
  expect(await visibility(page, "smc")).toBe("none");
  await expect(page.locator("#ind")).toBeEnabled();
  await expect(page.locator("#cls")).toHaveValue("0"); // and switching it off takes them back
  expect(page.url()).not.toContain("k=");
  expect(errors).toEqual([]);
});

/** The distinct colours painted on the surface canvas, of the whole world or of the part inside the map's bounds. */
const painted = (page: Page, inView = false) => page.evaluate((inView) => {
  const c = document.getElementById("smc") as HTMLCanvasElement, b = (window as any).__map.getBounds();
  const merc = (lat: number) => Math.asinh(Math.tan((lat * Math.PI) / 180)), row = (lat: number) => ((merc(78) - merc(lat)) / (merc(78) - merc(-58.235581691547694))) * c.height;
  const [x0, y0, x1, y1] = inView ? [((b.getWest() + 180) / 360) * c.width, row(b.getNorth()), ((b.getEast() + 180) / 360) * c.width, row(b.getSouth())].map(Math.round) : [0, 0, c.width, c.height];
  const px = new Uint32Array((window as any).copy2d(c).getImageData(x0, y0, x1 - x0, y1 - y0).data.buffer);
  return new Set(px.filter((v) => v >>> 24 === 255)).size;
}, inView);
/** Terrain under software GL costs seconds a frame and grows with the pixels: the terrain tests use a small desktop window. */
const small = (page: Page) => page.setViewportSize({ width: 800, height: 500 });
const terrain = (page: Page) => map(page, "m.getTerrain()?.source ?? null");

test("smoothed view: classes are flat colours on the canvas, Relief drapes it on a terrain, nothing of it stays behind", async ({ page }) => {
  test.slow();
  await small(page);
  const errors = await open(page, "#v=s&k=5");
  await expect(page.locator("#legend .classes i")).toHaveCount(5);
  expect(await visibility(page, "smc")).toBe("visible");
  expect(await painted(page)).toBe(5);
  expect(await map(page, "Object.keys(m.getStyle().sources).sort()")).toEqual(["clip", "regions", "smc", "smv"]); // no bands, no terrain yet
  expect(await map(page, 'm.getStyle().layers.filter((l) => l.type === "fill-extrusion").map((l) => l.source)')).toEqual(["regions"]);
  expect(await visibility(page, "smv")).toBe("none");
  const flat = (await smoothAt(page, LONDON))!;
  await page.check("#relief");
  expect(await terrain(page)).toBe("dem");
  expect(await visibility(page, "smc")).toBe("visible");
  expect(await visibility(page, "relief3")).toBe("none");
  // shading on the terrain, then the sea veil, then lines and names: shade and veil lie right above the surface
  expect(await map(page, 'm.getStyle().layers.map((l) => l.id).slice(2, 5)')).toEqual(["smc", "shade", "smv"]);
  expect(await visibility(page, "smv")).toBe("visible");
  const tall = (await smoothAt(page, LONDON, true))!; // the pointer still hits the place under it on the terrain (London stands 4 decades, 250 km, high)
  expect(Math.abs(tall / flat - 1)).toBeLessThan(0.05);
  // the place read back under a point of the terrain is within a pixel of it (MapLibre reads it from a buffer of the terrain's coordinates)
  expect(await map(page, `Math.max(...[[-0.13, 51.51], [2.35, 48.86], [1.5, 52.5]].map((p) => { const s = m.project(p), t = m.project(m.unproject(s)); return Math.hypot(s.x - t.x, s.y - t.y); }))`))
    .toBeLessThan(1.5);
  await smoothAt(page, PARIS, true);
  await expect(page.locator("#tip")).toContainText("Paris");
  await page.mouse.click(...(Object.values(await at(page, PARIS)) as [number, number])); // and a click selects the region there
  await expect(page.locator("#panel h2")).toHaveText("Paris");
  await page.click("#panel .x");
  expect(await map(page, "m.terrain.exaggeration * 2 ** m.getZoom()")).toBeCloseTo(10, 6); // 1000 km per decade at zoom 0, halved per level
  expect(page.url()).toContain("c=4/48.86/2.35"); // the terrain does not shift the camera
  await sec(page, "sc");
  await page.selectOption("#cls", "0");
  expect(await painted(page)).toBeGreaterThan(100);
  for (const [id, to] of [["sr", "100"], ["sk", "gauss"], ["sr", "150"]]) { // each surface replaces the terrain
    await expect.poll(() => map(page, 'm.getSource("dem")?.tiles?.[0]')).toBeTruthy(); // the source reads its tiles once loaded
    const before = await map(page, 'm.getSource("dem").tiles[0]');
    await opts(page);
    await page.selectOption("#" + id, to);
    await expect.poll(() => map(page, 'm.getSource("dem")?.tiles?.[0]')).not.toBe(before);
    expect(await terrain(page)).toBe("dem");
  }
  await expect.poll(() => map(page, 'm.getSource("dem").maxzoom')).toBe(2); // 1024 columns at 150 km (set once the source has loaded)
  await page.uncheck("#relief");
  expect(await terrain(page)).toBeNull();
  expect(await map(page, '[!!m.getSource("dem"), !!m.getSource("shd"), !!m.getLayer("shade")]')).toEqual([false, false, false]);
  expect(await visibility(page, "smv")).toBe("none");
  await page.check("#relief");
  await page.check("#globe");
  expect(await terrain(page)).toBe("dem");
  await page.check("#mode-r"); // back to the regions: their own relief, no terrain
  expect(await terrain(page)).toBeNull();
  expect(await visibility(page, "relief3")).toBe("visible");
  expect(await visibility(page, "smc")).toBe("none");
  await page.uncheck("#globe");
  await page.check("#smooth");
  expect(await terrain(page)).toBe("dem");

  await page.goto("/#v=s&sk=gauss&sr=150&ss=1&sf=1&r=1&c=5/50/10");
  await page.reload(); // a hash change alone does not reload
  await loaded(page);
  await expect(page.locator("#smooth")).toBeChecked();
  await expect(page.locator("#sk")).toHaveValue("gauss");
  await expect(page.locator("#sr")).toHaveValue("150");
  for (const id of ["ss", "relief"]) await expect(page.locator("#" + id)).toBeChecked();
  await expect(page.locator('#seg [data-s="view"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#legend")).toContainText("smoothed (gaussian, 150 km), derived");
  expect(await terrain(page)).toBe("dem");
  expect(await map(page, "[m.getZoom(), m.getCenter().lat, m.getCenter().lng]")).toEqual([5, 50, 10]);
  await map(page, "m.jumpTo({ center: [11, 48], zoom: 5.5 })");
  await expect.poll(() => page.url()).toContain("c=5.5/48/11");
  expect(errors).toEqual([]);
});

test("smoothed relief on the globe: the pointer hits the place under it, borders and names lie on the surface", async ({ page }) => {
  test.slow();
  await small(page);
  const errors = await open(page, "#v=s&g=1&k=5&c=4/51.51/-0.13"); // smoothAt stays at this view: no new tiles to wait for
  const flat = (await smoothAt(page, LONDON))!;
  await page.check("#relief");
  expect(await terrain(page)).toBe("dem");
  await loaded(page); // a query on the terrain waits for every frame queued on the GPU (minutes under software GL while tiles load): let them finish
  expect(Math.abs((await smoothAt(page, LONDON))! / flat - 1)).toBeLessThan(0.05);
  for (const id of ["labels", "country3"]) expect(await visibility(page, id) ?? "visible").toBe("visible");
  expect(errors).toEqual([]);
});

test("Scale: View, smoothed: the classes are those of the part of the surface in view", async ({ page }) => {
  const errors = await open(page, "#v=s&k=5&c=5/50/10");
  const world = await page.locator("#legend .classes").innerText();
  expect(await painted(page, true)).toBeLessThan(4); // world-wide powers of ten: Europe is two or three classes
  await scaleTo(page, "view");
  expect(page.url()).toContain("sf=1");
  const europe = await page.locator("#legend .classes").innerText();
  expect(europe).not.toBe(world);
  expect(await painted(page, true)).toBeGreaterThanOrEqual(4);
  await map(page, "m.jumpTo({ center: [-100, 40], zoom: 5 })"); // follows the map
  await expect.poll(() => page.locator("#legend .classes").innerText()).not.toBe(europe);
  expect(await painted(page, true)).toBeGreaterThanOrEqual(4);
  await page.check("#relief"); // the terrain stands on the world's floor: a fitted scale recolours it, never rebuilds it
  expect(await terrain(page)).toBe("dem");
  await expect.poll(() => map(page, 'm.getSource("dem")?.tiles?.[0]')).toBeTruthy(); // the source gets its tiles a moment after the terrain
  const dem = await map(page, 'm.getSource("dem").tiles[0]'), us = await page.locator("#legend .classes").innerText();
  await map(page, "m.jumpTo({ center: [10, 50], zoom: 5 })");
  await expect.poll(() => page.locator("#legend .classes").innerText()).not.toBe(us);
  expect(await map(page, 'm.getSource("dem").tiles[0]')).toBe(dem);
  await page.uncheck("#relief");
  await sec(page, "sc");
  await page.selectOption("#cls", "0");
  await expect(page.locator("#legend .ticks span").first()).toContainText("≤$");
  await scaleTo(page, "auto");
  await sec(page, "sc");
  await page.selectOption("#cls", "5");
  expect(await page.locator("#legend .classes").innerText()).toBe(world);
  expect(errors).toEqual([]);
});

/** The local excess under a place, from the tooltip ("3.2× its surroundings"). */
const excessAt = async (page: Page, p: [number, number]) => ((await smoothText(page, p)), parseFloat(await page.locator("#tip .ex").innerText()));

test("local excess: the surface against its Gaussian surroundings one radius up, diverging colours, legend, tooltip, URL", async ({ page }) => {
  const errors = await open(page, "#v=s&sr=15&lx=1&c=5/50/8");
  await expect(page.locator("#lx")).toBeChecked();
  await expect(page.locator("#sx, #er")).toHaveCount(0); // Compare with and Economic regions are gone
  await expect(page.locator("#legend")).toContainText("(inverse square, 15 km) against its surroundings (Gaussian, 30 km)");
  await expect(page.locator("#legend")).toContainText("x times its surroundings");
  await expect(page.locator("#legend .ticks")).toContainText("1×");
  await expect(page.locator("#pal")).toBeDisabled();
  const [london, rural] = [await excessAt(page, LONDON), await excessAt(page, [2.5, 47])]; // a city stands out, the countryside between Paris and Lyon lies below
  expect(london).toBeGreaterThan(1.5);
  expect(rural).toBeLessThan(1);
  await expect(page.locator("#tip .v")).toContainText("per km²"); // the value itself stays in the tooltip
  await sec(page, "sc");
  await page.selectOption("#cls", "5");
  await expect(page.locator("#legend .classes i")).toHaveCount(5);
  expect(await painted(page)).toBe(5);
  await opts(page);
  await page.selectOption("#sr", "100");
  await expect(page.locator("#legend")).toContainText("(Gaussian, 150 km)");
  await opts(page);
  await page.selectOption("#sr", "150"); // no wider radius on the ladder: off and disabled
  await expect(page.locator("#lx")).not.toBeChecked();
  await expect(page.locator("#lx")).toBeDisabled();
  expect(page.url()).not.toContain("lx=");
  await expect(page.locator("#legend")).not.toContainText("surroundings");
  await expect(page.locator("#pal")).toBeEnabled();
  expect(errors).toEqual([]);
});

test("kernels come from smooth.json (the ball is gone); an old ball link opens with the default kernel", async ({ page }) => {
  const errors = await open(page, "#v=s&sk=ball");
  await expect(page.locator("#sk option")).toHaveText(["Inverse square", "Gaussian"]);
  await expect(page.locator("#sr option")).toHaveText(["15 km", "30 km", "50 km", "100 km", "150 km"]);
  await expect(page.locator("#sk")).toHaveValue("inv2");
  await expect(page.locator("#legend")).toContainText("smoothed (inverse square, 50 km)");
  await opts(page);
  await page.selectOption("#sk", "gauss");
  await expect(page.locator("#legend")).toContainText("smoothed (gaussian, 50 km)");
  await page.goto("/#v=s&sk=epan&sr=x"); // a removed kernel, an unreadable radius: the defaults
  await page.reload();
  await loaded(page);
  await expect(page.locator("#sk")).toHaveValue("inv2");
  await expect(page.locator("#sr")).toHaveValue("50");
  for (const [old, kept] of [["25", "30"], ["40", "30"], ["75", "100"], ["200", "150"], ["400", "150"], ["800", "150"]]) { // an old link with a removed radius opens at the nearest kept one
    await page.goto(`/#v=s&sr=${old}&er=1&sx=100`); // and its removed keys are ignored
    await page.reload();
    await loaded(page);
    await expect(page.locator("#sr")).toHaveValue(kept);
    await expect(page.locator("#legend")).toContainText(`${kept} km`);
    await expect(page.locator("#lx")).not.toBeChecked();
  }
  expect(errors).toEqual([]);
});

test("Smoothed offers three indicators: legend title, picture, units, Include sea rules; GDP and Population go to their per-km2 version and back; old links migrate", async ({ page }) => {
  test.slow();
  const errors = await open(page, "#v=s&i=pop_density&c=4/50/8");
  const ss = page.locator("#ss"), legend = page.locator("#legend");
  await expect(page.locator("#ind option")).toHaveText(["GDP per km²", "GDP per capita", "Population density"]);
  await expect(legend).toContainText("Population density, smoothed (inverse square, 50 km), derived");
  expect(await painted(page)).toBeGreaterThan(5);
  await opts(page);
  await expect(ss).toBeEnabled();
  expect(await smoothText(page, LONDON)).toMatch(/people per km²$/);

  await page.selectOption("#ind", "gdp_per_capita");
  await expect(legend).toContainText("GDP per capita, smoothed (inverse square, 50 km), derived");
  await expect(legend).toContainText("national value by construction");
  expect(await painted(page)).toBeGreaterThan(5);
  await expect(ss).toBeDisabled();
  await expect(ss).not.toBeChecked();
  expect(await smoothText(page, LONDON)).toMatch(/^\$[\d.]+[kM]? per person$/);
  await page.selectOption("#ind", "gdp_per_km2");
  await expect(legend).not.toContainText("equivalent disc");

  // Population on, Smoothed on: the per-km2 version; off: Population again
  await page.check("#mode-r");
  await expect(page.locator("#ind option")).toHaveCount(5);
  await page.selectOption("#ind", "pop");
  await page.check("#smooth");
  await expect(page.locator("#ind")).toHaveValue("pop_density");
  expect(page.url()).toContain("i=pop_density");
  await page.check("#mode-r");
  await expect(page.locator("#ind")).toHaveValue("pop");
  expect(page.url()).toContain("i=pop");
  await page.selectOption("#ind", "gdp_usd");
  await page.check("#smooth");
  await expect(page.locator("#ind")).toHaveValue("gdp_per_km2");
  await page.selectOption("#ind", "gdp_per_capita"); // left alone: nothing to restore
  await page.check("#mode-r");
  await expect(page.locator("#ind")).toHaveValue("gdp_per_capita");

  await page.goto("/#v=s&i=gdp_usd&c=4/50/8"); // old links
  await page.reload();
  await loaded(page);
  await expect(page.locator("#ind")).toHaveValue("gdp_per_km2");
  await expect(legend).toContainText("GDP per km², smoothed");
  await page.goto("/#v=s&i=pop&c=4/50/8");
  await page.reload();
  await loaded(page);
  await expect(page.locator("#ind")).toHaveValue("pop_density");
  expect(errors).toEqual([]);
});

test("local excess for population density: against the wider Gaussian surface of the same indicator", async ({ page }) => {
  const errors = await open(page, "#v=s&i=pop_density&sr=15&lx=1&c=5/50/8");
  await expect(page.locator("#legend")).toContainText("Population density (inverse square, 15 km) against its surroundings (Gaussian, 30 km)");
  expect(await excessAt(page, LONDON)).toBeGreaterThan(1.5);
  await expect(page.locator("#tip .v")).toContainText("people per km²");
  expect(errors).toEqual([]);
});

const MANHATTAN: [number, number] = [-73.97, 40.78];
test("radius 15 km loads and is sharper than 50 km", async ({ page }) => {
  test.slow();
  const errors = await open(page, "#v=s&c=7/40.78/-73.97");
  const at50 = (await smoothAt(page, MANHATTAN))!;
  await opts(page);
  await page.selectOption("#sr", "15");
  await expect(page.locator("#legend")).toContainText("smoothed (inverse square, 15 km)");
  expect((await smoothAt(page, MANHATTAN))!).toBeGreaterThan(at50 * 1.5);
  expect(errors).toEqual([]);
});

test("without smooth.json the app starts with Smoothed disabled", async ({ page }) => {
  await page.route("**/smooth/smooth.json", (r) => r.abort());
  const errors = await open(page, "#v=s");
  await expect(page.locator("#smooth")).toBeDisabled();
  await expect(page.locator("#legend")).not.toContainText("smoothed");
  expect(errors).toEqual([]);
});

test("light theme: the select sets data-theme and the URL, the map background is the light ocean, a reload keeps it, no tile reload", async ({ page }) => {
  await open(page, "#c=1/20/0");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const oceanAt = async () => {
    const png = await page.screenshot({ clip: { x: 1, y: 1, width: 1, height: 1 } }); // top-left corner: open water at zoom 1
    return page.evaluate(async (b64) => {
      const img = await createImageBitmap(await (await fetch("data:image/png;base64," + b64)).blob());
      const c = new OffscreenCanvas(1, 1).getContext("2d")!;
      c.drawImage(img, 0, 0);
      return [...c.getImageData(0, 0, 1, 1).data.slice(0, 3)];
    }, png.toString("base64"));
  };
  expect(await oceanAt()).not.toEqual([0xcf, 0xe4, 0xf2]);
  const tiles = await page.evaluate(() => performance.getEntriesByType("resource").length);
  await sec(page, "sa");
  await page.selectOption("#theme", "light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(page.url()).toContain("th=light");
  await expect(page.locator("#pal option")).toHaveText(["YlOrRd", "YlOrBr", "OrRd", "Reds", "Purples", "Greys", "Viridis (reversed)", "Magma (reversed)", "Inferno (reversed)"]);
  await expect(page.locator("#pal")).toHaveValue("ylorrd");
  await expect.poll(oceanAt).toEqual([0xcf, 0xe4, 0xf2]);
  expect(await page.evaluate(() => performance.getEntriesByType("resource").length)).toBe(tiles);
  await page.reload();
  await loaded(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("#theme")).toHaveValue("light");
  await expect.poll(oceanAt).toEqual([0xcf, 0xe4, 0xf2]);
});

test("theme auto follows the system and reacts to a change", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await open(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(page.url()).not.toContain("th=");
});

test("focus: Europe only, Africa is neither hovered nor drawn, the scale is the focus', Esc and reload, two continents", async ({ page }) => {
  const errors = await open(page, "#c=3/20/20");
  const world = await page.locator("#lg").innerText();
  await page.fill("#q", "europe");
  await page.locator("#results li .fo").first().dispatchEvent("mousedown");
  await expect(page.locator("#chips")).toContainText("Europe");
  await expect(page.locator("#unfocus")).toBeVisible();
  expect(page.url()).toContain("f=CONT%3Aeurope".replace("%3A", ":"));
  await expect(page.locator('#seg [data-s="auto"]')).toHaveAttribute("aria-pressed", "true"); // Auto is the focus here
  await expect(page.locator("#cover")).toContainText("regions hold");
  await map(page, "m.jumpTo({ center: [20, 5], zoom: 3 })");
  await loaded(page);
  let p = await at(page, [20, 5]); // Africa
  await page.mouse.move(p.x, p.y);
  await expect(page.locator("#tip")).toBeHidden();
  await page.mouse.click(p.x, p.y);
  await expect(page.locator("#panel")).toBeHidden();
  expect(await map(page, 'm.queryRenderedFeatures(undefined, { layers: ["fill3"] }).filter((f) => f.properties.region_id.startsWith("WP:NGA")).length')).toBe(0);
  await map(page, "m.jumpTo({ center: [10, 50], zoom: 4 })");
  await loaded(page);
  p = await at(page, [10, 50.5]);
  await page.mouse.move(p.x, p.y);
  await expect(page.locator("#tip")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#unfocus")).toBeHidden();
  expect(page.url()).not.toContain("f=");
  await expect(page.locator('#seg [data-s="auto"]')).toHaveAttribute("aria-pressed", "true");
  expect(await page.locator("#lg").innerText()).toBe(world);

  await page.evaluate(() => (location.hash = "#f=CONT:europe,CONT:africa&c=2/20/20")); // two continents; the URL survives a reload
  await page.reload();
  await loaded(page);
  await expect(page.locator("#chips .chip")).toHaveCount(2);
  await expect(page.locator("#seg button")).toHaveText(["Auto", "World", "View"]);
  await scaleTo(page, "world"); // the world's colours, the focus stays
  await expect(page.locator('#seg [data-s="world"]')).toHaveAttribute("aria-pressed", "true");
  expect(page.url()).toContain("sw=1");
  await scaleTo(page, "auto");
  await page.locator("#chips .chip button").first().click();
  await expect(page.locator("#chips .chip")).toHaveCount(1);
  await page.click("#unfocus");
  await expect(page.locator("#unfocus")).toBeHidden();
  expect(errors).toEqual([]);
});

test("focus: the panel button adds and removes, a result outside the focus cannot be selected, the camera is kept on reload", async ({ page }) => {
  await open(page, "#s=NUTS2024:DE212");
  await page.click("#panel .fo");
  await expect(page.locator("#chips")).toContainText("München");
  await expect(page.locator("#panel .fo")).toHaveText("Remove from focus");
  await page.fill("#q", "texas");
  await expect(page.locator("#results li.out").first()).toBeVisible();
  await page.press("#q", "Enter");
  expect(page.url()).not.toContain("s=FIPS");
  await page.press("#q", "Escape"); // the list covers the focus row
  await page.click("#unfocus");
  await page.evaluate(() => (location.hash = "#f=CONT:asia&c=2/30/60"));
  await page.reload();
  await loaded(page);
  const cam = await map(page, "m.getZoom()");
  expect(cam).toBeCloseTo(2, 1); // a camera in the URL is not overridden by the fit
});

/** Drag a frame handle to a place on the map (mouse). */
const pull = async (page: Page, handle: string, to: [number, number]) => {
  const [h, q] = [await page.locator(`#frame [data-h=${handle}]`).boundingBox(), await at(page, to)];
  await page.mouse.move(h!.x + h!.width / 2, h!.y + h!.height / 2);
  await page.mouse.down();
  await page.mouse.move(q.x, q.y, { steps: 4 });
  await page.mouse.up();
};
/** Frame the box w, s, e, n with the two corner handles. */
const framed = async (page: Page, [w, s, e, n]: [number, number, number, number]) => { await pull(page, "nw", [w, n]); await pull(page, "se", [e, s]); };
/** Alpha of the smoothed canvas where a place lies (0: nothing painted). */
const drawnAt = (page: Page, [lng, lat]: [number, number]) => page.evaluate(async ([lng, lat]) => {
  const { north, south } = await (await fetch("smooth/smooth.json")).json(), c = document.getElementById("smc") as HTMLCanvasElement, merc = (d: number) => Math.asinh(Math.tan((d * Math.PI) / 180));
  const x = Math.floor(((lng + 180) / 360) * c.width), y = Math.floor(((merc(north) - merc(lat)) / (merc(north) - merc(south))) * c.height);
  return (window as any).copy2d(c).getImageData(x, y, 1, 1).data[3];
}, [lng, lat]);

test("Scale: View, regions view: the domain follows what is on screen, only colours are rewritten on a pan; World and Focus; sw and sf in the URL", async ({ page }) => {
  const errors = await open(page, "#c=6/50/10");
  await expect(page.locator("#seg button")).toHaveText(["Auto", "World", "View"]);
  const world = await page.locator("#lg .ticks").innerText();
  await scaleTo(page, "view");
  expect(page.url()).toContain("sf=1");
  await expect(page.locator('#seg [data-s="view"]')).toHaveAttribute("aria-pressed", "true");
  const europe = await page.locator("#lg .ticks").innerText();
  expect(europe).not.toBe(world);
  // a pan recolours through feature-state alone: the paint expression stays (a new one would re-lay out every tile), only changed colours are written, none when nothing changed
  await page.evaluate(() => { const m = (window as any).__map, f = m.setFeatureState.bind(m); (window as any).__sets = 0; m.setFeatureState = (...a: unknown[]) => { (window as any).__sets++; return f(...a); }; });
  const paint = await map(page, 'JSON.stringify(m.getPaintProperty("fill3", "fill-color"))');
  await map(page, "m.jumpTo({ center: [12, 23], zoom: 6 })"); // the Sahara
  await expect.poll(() => page.locator("#lg .ticks").innerText()).not.toBe(europe);
  expect(await map(page, 'JSON.stringify(m.getPaintProperty("fill3", "fill-color"))')).toBe(paint);
  expect(await page.evaluate(() => (window as any).__sets)).toBeGreaterThan(0);
  await page.evaluate(() => ((window as any).__sets = 0));
  await map(page, "m.jumpTo({ center: [12, 23.001], zoom: 6 })"); // the same view, the same domain: nothing to write
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => (window as any).__sets)).toBe(0);
  await scaleTo(page, "auto");
  expect(page.url()).not.toContain("sf=1");
  await expect.poll(() => page.locator("#lg .ticks").innerText()).toBe(world);
  await page.goto("/#f=ISO3:DEU&sw=1");
  await page.reload(); // a hash change alone does not reload
  await loaded(page);
  await expect(page.locator('#seg [data-s="world"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('#seg [data-s="world"]')).toHaveAttribute("aria-pressed", "true");
  expect(errors).toEqual([]);
});

test("Include sea does not move the scale: the colour under Frankfurt is the same with it on and off, with a note in the legend", async ({ page }) => {
  test.slow();
  const errors = await open(page, "#v=s&c=5/50.1/8.7");
  const rgb = () => page.evaluate(async () => {
    const { north, south } = await (await fetch("smooth/smooth.json")).json(), c = document.getElementById("smc") as HTMLCanvasElement, merc = (d: number) => Math.asinh(Math.tan((d * Math.PI) / 180));
    const x = Math.floor(((8.68 + 180) / 360) * c.width), y = Math.floor(((merc(north) - merc(50.11)) / (merc(north) - merc(south))) * c.height);
    return [...(window as any).copy2d(c).getImageData(x, y, 1, 1).data];
  });
  await expect(page.locator("#legend")).toContainText("inverse square, 50 km");
  await expect(page.locator("#legend")).not.toContainText("Include sea:");
  const land = await rgb(), ticks = await page.locator("#legend .ticks").innerText();
  await opts(page);
  await page.check("#ss");
  await expect(page.locator("#legend")).toContainText("Include sea: divided by all area within reach");
  expect(await page.locator("#legend .ticks").innerText()).toBe(ticks);
  const sea = await rgb();
  expect(land[3]).toBe(255);
  sea.slice(0, 3).forEach((v, i) => expect(Math.abs(v - land[i])).toBeLessThan(40)); // the dilution by the sea within 50 km is small
  expect(errors).toEqual([]);
});

test("frame editor: Focus area, mouse handles, Esc cancels, Enter applies, outside the box nothing is hovered, Edit area, aspect lock, Clear", async ({ page }) => {
  const errors = await open(page, "#c=5/51/10");
  await page.click("#area");
  await expect(page.locator("#frame")).toBeVisible();
  await expect(page.locator("#frame .h")).toHaveCount(8);
  await expect(page.locator("#fro")).toContainText("km"); // size, then the regions it meets
  await expect(page.locator("#fro")).toContainText("regions");
  await framed(page, [5.5, 47, 15.5, 55.2]);
  await page.keyboard.press("Escape");
  await expect(page.locator("#frame")).toBeHidden();
  expect(page.url()).not.toContain("fb=");

  await page.click("#area");
  await framed(page, [5.5, 47, 15.5, 55.2]);
  await page.keyboard.press("Enter");
  await expect(page.locator("#frame")).toBeHidden();
  await expect.poll(() => page.url()).toContain("fb=");
  expect(page.url()).not.toMatch(/[#&]f=/);
  await expect(page.locator("#chips")).toContainText("Area");
  await expect(page.locator("#area")).toContainText("Edit area");
  await expect(page.locator("#cover")).toContainText("regions hold");
  await expect(page.locator('#seg [data-s="auto"]')).toHaveAttribute("aria-pressed", "true"); // Auto is the focus here
  await expect.poll(() => map(page, 'm.querySourceFeatures("clip").map((f) => f.geometry.type).includes("Polygon")')).toBe(true); // the mask polygon (and the ring)
  expect(await map(page, 'm.getPaintProperty("clip3", "fill-color")')).toBeTruthy();
  await loaded(page);
  const [inside, outside] = [await at(page, [10, 50.5]), await at(page, [2, 48.8])]; // Germany, Paris
  await page.mouse.move(inside.x, inside.y);
  await expect(page.locator("#tip")).toBeVisible();
  await page.mouse.move(outside.x, outside.y);
  await expect(page.locator("#tip")).toBeHidden();
  await page.mouse.click(outside.x, outside.y);
  await expect(page.locator("#panel")).toBeHidden();
  await page.reload();
  await loaded(page);
  await expect(page.locator("#chips")).toContainText("Area");

  await page.click("#area"); // Edit area: the frame sits on the box
  const [fr, nw, se] = [await page.locator("#frame").boundingBox(), await at(page, [5.5, 55.2]), await at(page, [15.5, 47])];
  expect(Math.abs(fr!.x - nw.x)).toBeLessThan(8);
  expect(Math.abs(fr!.y + fr!.height - se.y)).toBeLessThan(8);
  await page.keyboard.press("Escape"); // cancels the frame only
  await expect(page.locator("#frame")).toBeHidden();
  expect(page.url()).toContain("fb=");

  await page.keyboard.press("Escape"); // and then the focus
  expect(page.url()).not.toContain("fb=");
  await page.click("#area");
  await page.selectOption("#fasp", "1");
  const sq = await page.locator("#frame").boundingBox();
  expect(sq!.width).toBeCloseTo(sq!.height, 0);
  await pull(page, "e", [30, 51]);
  const wide = await page.locator("#frame").boundingBox();
  expect(wide!.width).toBeCloseTo(wide!.height, 0);
  expect(wide!.width).toBeGreaterThan(sq!.width);
  await page.click("#fcancel");
  await expect(page.locator("#frame")).toBeHidden();
  expect(errors).toEqual([]);
});

test("frame editor: pressing Focus area on the globe or with Relief switches to the flat map with a note; switching to the globe cancels the frame", async ({ page }) => {
  const errors = await open(page, "#g=1&c=3/50/10");
  await page.click("#area");
  await expect(page.locator("#toast")).toHaveText("Switched to the flat map to draw the area");
  await expect(page.locator("#globe")).not.toBeChecked();
  await expect(page.locator("#frame")).toBeVisible();
  await page.check("#globe");
  await expect(page.locator("#frame")).toBeHidden();
  await page.uncheck("#globe");
  await page.check("#relief");
  await page.click("#area");
  await expect(page.locator("#relief")).not.toBeChecked();
  expect(await map(page, "m.getPitch()")).toBe(0);
  await expect(page.locator("#frame")).toBeVisible();
  await page.click("#area"); // the button toggles
  await expect(page.locator("#frame")).toBeHidden();
  expect(errors).toEqual([]);
});

test("focus in the smoothed view: Europe only, the scale is the focus', the tooltip and canvas are empty outside; a box; the mask follows the theme", async ({ page }) => {
  test.slow();
  const errors = await open(page, "#v=s&c=2/30/20");
  await loaded(page);
  await expect.poll(() => drawnAt(page, [20, 5])).toBeGreaterThan(0); // Africa
  const world = await page.locator("#lg").innerText();
  await page.fill("#q", "europe");
  await page.locator("#results li .fo").first().dispatchEvent("mousedown");
  await expect(page.locator("#lg")).toContainText("Cut at the border");
  await expect.poll(() => drawnAt(page, [20, 5])).toBe(0);
  expect(await drawnAt(page, [10, 50])).toBeGreaterThan(0);
  expect(await page.locator("#lg").innerText()).not.toBe(world);
  await scaleTo(page, "world");
  await expect(page.locator('#seg [data-s="world"]')).toHaveAttribute("aria-pressed", "true");
  await scaleTo(page, "view"); // the part of the focus in view: follows the camera
  await expect(page.locator('#seg [data-s="view"]')).toHaveAttribute("aria-pressed", "true");
  const inView = await page.locator("#lg .ticks").innerText();
  await map(page, "m.jumpTo({ center: [10, 62], zoom: 4 })");
  await expect.poll(() => page.locator("#lg .ticks").innerText()).not.toBe(inView);
  await scaleTo(page, "auto");
  await page.evaluate(() => (location.hash = "#v=s&fb=5.5,47,15.5,55.2&c=5/51/10&ss=1")); // a box, with Include sea
  await page.reload();
  await loaded(page);
  await expect.poll(() => drawnAt(page, [10, 50])).toBeGreaterThan(0);
  expect(await drawnAt(page, [2, 48.8])).toBe(0);
  expect(await drawnAt(page, [8, 55.8])).toBe(0); // the North Sea, above the box
  expect(await drawnAt(page, [8, 54.5])).toBeGreaterThan(0); // the sea inside it, drawn with Include sea
  const [inside, outside] = [await at(page, [10, 50.5]), await at(page, [2, 48.8])];
  await page.mouse.move(inside.x, inside.y);
  await expect(page.locator("#tip")).toBeVisible();
  await page.mouse.move(outside.x, outside.y);
  await expect(page.locator("#tip")).toBeHidden();
  expect(await map(page, 'm.getPaintProperty("clip3", "fill-color")')).toBe("#000");
  await sec(page, "sa");
  await page.selectOption("#theme", "light");
  await expect.poll(() => map(page, 'm.getPaintProperty("clip3", "fill-color")')).toBe("#fff");
  expect(errors).toEqual([]);
});

test("outside a focus is paper with an outline, a box keeps the sea inside; the theme recolours, Esc restores", async ({ page }) => {
  const errors = await open(page, "#f=ISO3:KAZ");
  const paint = (id: string, prop: string) => map(page, `m.getPaintProperty("${id}", "${prop}")`);
  expect(await paint("bg", "background-color")).toBe("#000");
  expect(await paint("edge3", "line-color")).toBe("#fff");
  expect(await map(page, 'm.getFilter("edge3")')).not.toEqual(["==", ["get", "region_id"], ""]);
  await sec(page, "sa");
  await page.selectOption("#theme", "light");
  await expect.poll(() => paint("bg", "background-color")).toBe("#fff");
  expect(await paint("edge3", "line-color")).toBe("#000");
  await sec(page, "sa");
  await page.selectOption("#theme", "dark");
  await page.check("#globe");
  await expect(page.locator("#map")).toHaveClass(/limb/);
  await page.uncheck("#globe");
  await page.keyboard.press("Escape");
  await expect.poll(() => paint("bg", "background-color")).toBe("#111721");
  expect(await map(page, 'm.getFilter("edge3")')).toEqual(["==", ["get", "region_id"], ""]);
  await expect(page.locator("#map")).not.toHaveClass(/limb/);

  await page.goto("/#fb=5,47,15,55");
  await loaded(page);
  expect(await paint("bg", "background-color")).toBe("#111721"); // a rectangle is a window: its sea stays
  expect(await paint("clip3", "fill-color")).toBe("#000");
  expect(await paint("ring3", "line-color")).toBe("#fff");
  const order: string[] = await map(page, "m.getStyle().layers.map((l) => l.id)");
  expect(order.indexOf("clip3")).toBeGreaterThan(order.indexOf("hover3")); // outlines cannot overhang the box
  expect(order.indexOf("clip3")).toBeGreaterThan(order.indexOf("sel3"));
  expect(order.indexOf("ring3")).toBeGreaterThan(order.indexOf("clip3"));
  expect(errors).toEqual([]);
});

test("focus: the panel offers no focus button for a region inside a focused one", async ({ page }) => {
  await open(page, "#f=CONT:europe&s=ISO3:DEU");
  await expect(page.locator("#panel h2")).toContainText("Germany");
  await expect(page.locator("#panel .fo")).toHaveCount(0);
});

for (const [name, id, lngLat] of [["France", "ISO3:FRA", [2, 47]], ["USA", "ISO3:USA", [-98, 39]]] as const)
  test(`focus on ${name}: the camera fits the mainland, Show overseas widens it, Mainland view returns, fo is in the URL`, async ({ page }) => {
    await open(page, `#f=${id}`);
    await expect(page.locator("#overseas")).toBeVisible();
    await expect(page.locator("#overseas")).toHaveText("Show overseas");
    await page.waitForTimeout(2500);
    const main = await map(page, "m.getZoom()");
    const [cx, cy] = await map(page, "[m.getCenter().lng, m.getCenter().lat]");
    expect(Math.abs(cx - lngLat[0])).toBeLessThan(12);
    expect(Math.abs(cy - lngLat[1])).toBeLessThan(10);
    await page.click("#overseas");
    await expect(page.locator("#overseas")).toHaveText("Mainland view");
    await page.waitForTimeout(2500);
    expect(await map(page, "m.getZoom()")).toBeLessThan(main - 0.7);
    expect(page.url()).toContain("fo=1");
    await page.click("#overseas");
    await page.waitForTimeout(2500);
    expect(await map(page, "m.getZoom()")).toBeCloseTo(main, 0);
    expect(page.url()).not.toContain("fo=1");
  });

/** The PNG of the open export dialog, saved to the test's output folder for a look; checks the signature, the width and that header and legend have content. */
async function exported(page: Page, file: string) {
  await expect(page.locator("#export-img")).toBeVisible({ timeout: 300_000 });
  const [download] = await Promise.all([page.waitForEvent("download"), page.click("#export-dl")]);
  const path = test.info().outputPath(file);
  await download.saveAs(path);
  const png = readFileSync(path), { ratio, crop } = await page.locator("#export").evaluate((d) => (d as HTMLElement).dataset);
  expect([...png.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
  const [cw, ch] = crop!.split("x").map(Number);
  expect(Math.max(cw, ch) * Number(ratio)).toBeGreaterThanOrEqual(1919); // at least Full HD: long edge 1920, short edge 1080
  expect(Math.min(cw, ch) * Number(ratio)).toBeGreaterThanOrEqual(1079);
  expect(png.readUInt32BE(16)).toBe(Math.round(cw * Number(ratio)));
  expect(png.readUInt32BE(20)).toBeGreaterThan(Number(crop!.split("x")[1]) * Number(ratio)); // the strips are added
  expect(download.suggestedFilename()).toMatch(/^gdp-density_.+_\d{4}\.png$/);
  const busy = await page.evaluate(async ([b64, r]) => { // distinct colours in rows of the title and of the credits line (sizes scale with the ratio): text is there
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const c = document.createElement("canvas");
    [c.width, c.height] = [img.width, img.height];
    const g = c.getContext("2d")!;
    g.drawImage(img, 0, 0);
    const n = (y: number) => new Set(Array.from(g.getImageData(0, Math.round(y * Number(r)), img.width, Math.round(14 * Number(r))).data.join(",").matchAll(/(\d+),(\d+),(\d+),/g), (m) => m[0])).size;
    return [n(8), n(img.height / Number(r) - 26)];
  }, [png.toString("base64"), ratio!]);
  expect(busy[0]).toBeGreaterThan(2);
  expect(busy[1]).toBeGreaterThan(2);
  await expect(page.locator("#export")).toBeHidden();
  return path;
}

test("export image: focus Germany in the dark regions view downloads a PNG with header, legend and credits", async ({ page }) => {
  test.setTimeout(600_000);
  const errors = await open(page, "#f=ISO3:DEU&th=dark&c=5/51/10");
  await page.click("#export-btn");
  await exported(page, "dark-germany.png");
  expect(errors).toEqual([]);
});

test("export image: without a focus the button opens the frame, light smoothed view with Include sea", async ({ page }) => {
  test.setTimeout(600_000);
  const errors = await open(page, "#v=s&sk=gauss&sr=100&ss=1&th=light&c=5/51/10");
  await page.click("#export-btn");
  await expect(page.locator("#fok")).toHaveText("Export");
  await framed(page, [4, 47.5, 14, 54]);
  await page.click("#fok");
  await exported(page, "light-smoothed-sea-box.png");
  await expect(page.locator("#frame")).toBeHidden();
  expect(errors).toEqual([]);
});

test("export image: a rotated map carries the north arrow in the crop's top right corner", async ({ page }) => {
  test.setTimeout(600_000);
  await open(page, "#f=ISO3:DEU&th=light&c=5/51/10");
  await map(page, "m.setBearing(40)");
  await page.click("#export-btn");
  const path = await exported(page, "light-germany-rotated.png"), { ratio } = await page.locator("#export").evaluate((d) => (d as HTMLElement).dataset);
  const red = await page.evaluate(async ([b64, r]) => { // pixels of the arrow's red north half in the image's top right corner
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const c = document.createElement("canvas");
    [c.width, c.height] = [img.width, img.height];
    const g = c.getContext("2d")!;
    g.drawImage(img, 0, 0);
    const k = Number(r) * 60, top = 0; // the header holds no red
    let n = 0;
    const d = g.getImageData(img.width - k, top, k, k * 3).data;
    for (let i = 0; i < d.length; i += 4) if (d[i] > 190 && d[i + 1] < 70 && d[i + 2] < 70) n++;
    return n;
  }, [readFileSync(path).toString("base64"), ratio!]);
  expect(red).toBeGreaterThan(20);
});

test("manual colour range in the legend: min and max (k/M/B), the ticks and the colours follow, clamped, invalid ignored, Auto restores", async ({ page }) => {
  test.slow();
  const errors = await open(page, "#v=s&c=5/50.1/8.7");
  const rgb = () => page.evaluate(async () => {
    const { north, south } = await (await fetch("smooth/smooth.json")).json(), c = document.getElementById("smc") as HTMLCanvasElement, merc = (d: number) => Math.asinh(Math.tan((d * Math.PI) / 180));
    const x = Math.floor(((8.68 + 180) / 360) * c.width), y = Math.floor(((merc(north) - merc(50.11)) / (merc(north) - merc(south))) * c.height);
    return [...(window as any).copy2d(c).getImageData(x, y, 1, 1).data];
  });
  const ticks = page.locator("#lg .ticks span"), autoTicks = await page.locator("#lg .ticks").innerText(), auto = await rgb();
  await expect(page.locator('#seg [data-s="auto"]')).toHaveAttribute("aria-pressed", "true");
  await page.click("#sc summary");
  await page.fill("#cmin", "1B");
  await page.press("#cmin", "Enter");
  await page.fill("#cmax", "100B");
  await page.press("#cmax", "Enter");
  await expect(ticks.first()).toHaveText("≤$1B");
  await expect(ticks.last()).toHaveText("≥$100B");
  await expect(page.locator("#sc summary")).toContainText("manual range");
  expect(page.url()).toContain("cl=9&ch=11");
  const low = await rgb(); // Frankfurt is far below $1B per km2: the lowest colour
  expect(low.slice(0, 3).reduce((a, b) => a + b)).toBeLessThan(auto.slice(0, 3).reduce((a, b) => a + b));
  await page.fill("#cmax", "abc"); // ignored: the field reverts
  await page.press("#cmax", "Enter");
  await expect(page.locator("#cmax")).toHaveValue("$100B");
  await page.fill("#cmin", "1T"); // reversed: ignored
  await page.press("#cmin", "Enter");
  await expect(page.locator("#cmin")).toHaveValue("$1B");
  await page.click("#cauto");
  await expect.poll(() => page.locator("#lg .ticks").innerText()).toBe(autoTicks);
  await expect(page.locator("#cmin")).toHaveValue("");
  expect(page.url()).not.toContain("cl=");
  expect(await rgb()).toEqual(auto);
  await page.goto("/#v=s&cl=4&ch=6&c=5/50.1/8.7"); // the range survives a reload; classes recompute from it
  await page.reload();
  await loaded(page);
  await expect(ticks.first()).toHaveText("≤$10k");
  await expect(page.locator("#sc summary")).toContainText("manual range");
  expect(errors).toEqual([]);
});

test.describe("export on a phone", () => {
  test.use({ viewport: { width: 393, height: 852 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  test("a 393 px wide map exports at least Full HD (not 1x), Maximum is larger, header and legend are drawn", async ({ page }) => {
    test.setTimeout(600_000);
    const errors = await open(page, "#f=ISO3:DEU&th=light&c=5/51/10");
    await page.click("#tools .chev");
    await page.click("#export-btn");
    await expect(page.locator("#export-img")).toBeVisible({ timeout: 300_000 });
    const data = () => page.locator("#export").evaluate((d) => ({ ...(d as HTMLElement).dataset }));
    const std = Number((await data()).ratio);
    expect(std).toBeGreaterThanOrEqual(2);
    await page.selectOption("#export-q", "max");
    await expect.poll(async () => Number((await data()).ratio), { timeout: 300_000 }).toBeGreaterThan(std);
    await expect(page.locator("#export-img")).toBeVisible();
    await expect(page.locator("#export-note")).toContainText(" px");
    await page.selectOption("#export-q", "");
    await expect.poll(async () => Number((await data()).ratio), { timeout: 300_000 }).toBe(std);
    await exported(page, "phone-germany-light.png");
    expect(errors).toEqual([]);
  });
});

const CITIES: Record<string, [number, number]> = { Frankfurt: [8.68, 50.11], Prague: [14.42, 50.08], "Hong Kong": [114.17, 22.3], Miami: [-80.19, 25.77], Sydney: [151.2, -33.87], Lisbon: [-9.14, 38.72], Mumbai: [72.88, 19.08], Auckland: [174.76, -36.85], "Tel Aviv": [34.78, 32.08] };
/** The colour of the smoothed canvas under each city. */
const cityColours = (page: Page) => page.evaluate(async (cities) => {
  const { north, south } = await (await fetch("smooth/smooth.json")).json(), c = document.getElementById("smc") as HTMLCanvasElement, merc = (d: number) => Math.asinh(Math.tan((d * Math.PI) / 180));
  return Object.fromEntries(Object.entries(cities).map(([n, [lng, lat]]) => {
    const x = Math.floor(((lng + 180) / 360) * c.width), y = Math.floor(((merc(north) - merc(lat)) / (merc(north) - merc(south))) * c.height);
    return [n, [...(window as any).copy2d(c).getImageData(x, y, 1, 1).data.slice(0, 3)]];
  }));
}, CITIES);
const away = (a: number[], b: number[]) => a.reduce((s, v, i) => s + Math.abs(v - b[i]), 0);

test("Include sea on real data: inland cities keep their colour, coastal ones change, the scale does not (gradient and 5 classes)", async ({ page }) => {
  test.slow();
  const errors = await open(page, "#v=s&c=3/20/20");
  // Hong Kong and New York are above the top of the scale ($100M) with and without the sea (log 8.4 to 8.0, 8.8 to 8.7): no colour change there.
  // The 5 classes break at whole decades: places cross one only where the drop straddles a break: Auckland and Tel Aviv (7.2 to 6.85 at the $10M break).
  for (const [classes, coastal] of [["0", ["Miami", "Sydney", "Lisbon", "Mumbai"]], ["5", ["Auckland", "Tel Aviv"]]] as const) {
    await sec(page, "sc");
    await page.selectOption("#cls", classes);
    await expect.poll(() => page.locator("#sr").inputValue()).toBe("50");
    const key = page.locator("#lg .ticks, #lg .classes"), ticks = await key.innerText(), land = await cityColours(page);
    await opts(page);
    await page.check("#ss");
    await expect(page.locator("#legend")).toContainText("Include sea:");
    await expect.poll(async () => away(land[coastal[0]], (await cityColours(page))[coastal[0]])).toBeGreaterThan(0); // the canvas is repainted
    const sea = await cityColours(page);
    for (const n of ["Frankfurt", "Prague"]) expect(away(land[n], sea[n]), `${n} ${classes}`).toBeLessThanOrEqual(6);
    for (const n of coastal) expect(away(land[n], sea[n]), `${n} ${classes}`).toBeGreaterThan(12);
    expect(await key.innerText()).toBe(ticks); // the same scale
    await opts(page);
    await page.uncheck("#ss");
  }
  expect(errors).toEqual([]);
});

test("a short screen: opening the scale panel brings the whole legend into view; a turned map is exported whole", async ({ page }) => {
  test.setTimeout(600_000);
  await page.setViewportSize({ width: 1280, height: 720 });
  await open(page, "#f=ISO3:ITA&v=s&ss=1&th=light");
  await page.click("#sc summary");
  await expect.poll(() => page.evaluate(() => document.getElementById("cauto")!.getBoundingClientRect().bottom <= innerHeight)).toBe(true);
  await map(page, "m.setBearing(40)");
  await page.click("#export-btn");
  await exported(page, "italy-turned.png");
  const [w, h] = (await page.locator("#export").evaluate((d) => (d as HTMLElement).dataset.crop!)).split("x").map(Number);
  expect(w / h).toBeLessThan(2); // Italy turned by 40 degrees is about as tall as wide; its unturned corners gave a 3:1 strip that cut it off
});
