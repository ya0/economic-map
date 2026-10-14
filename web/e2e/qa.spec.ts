import { sec } from "./ui";
import { expect, test, type Page } from "@playwright/test";
import { INDICATORS } from "../src/scales/scales";

/** Regression matrix and edge cases: no error, no blank map, a legend and a tooltip, for every state we can reach. */
const errorsOf = (page: Page) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", async (m) => {
    const text = [m.text(), ...await Promise.all(m.args().map((a) => a.evaluate((x) => x?.stack ?? x?.message ?? "").catch(() => "")))].join(" ").trim();
    if (m.type() === "error" && !/Failed to (load resource|fetch)|net::ERR/.test(text)) errors.push(`${text.slice(0, 400)} at ${page.url().split("#")[1] ?? ""}`);
  });
  return errors;
};
const map = (page: Page, js: string) => page.evaluate((js) => new Function("m", "return " + js)((window as any).__map), js);
/** The app has started, the smoothed surface (if asked for) is shown and the map is idle. */
const settled = async (page: Page) => {
  await page.waitForFunction(() => (window as any).__map?.loaded() && (!location.hash.includes("v=s") || (window as any).__map.getLayoutProperty("smc", "visibility") === "visible"), null, { timeout: 120_000 });
  await page.evaluate(() => new Promise<void>((res) => { const m = (window as any).__map; m.loaded() && m.areTilesLoaded() ? res() : m.once("idle", () => res()); }));
};
/** Distinct colours of the map canvas, sampled on a 64 x 36 grid inside a render event (the drawing buffer is only valid there). */
const colours = (page: Page) => page.evaluate(() => new Promise<number>((res) => {
  const m = (window as any).__map;
  m.once("render", () => {
    const c = document.createElement("canvas"), x = c.getContext("2d")!;
    [c.width, c.height] = [64, 36];
    x.drawImage(m.getCanvas(), 0, 0, 64, 36);
    const d = x.getImageData(0, 0, 64, 36).data, s = new Set<number>();
    for (let i = 0; i < d.length; i += 4) s.add((d[i] << 16) | (d[i + 1] << 8) | d[i + 2]);
    res(s.size);
  });
  m.triggerRepaint();
}));

/** All pairs of values of any two factors in as few rows as a greedy pick finds (deterministic). */
function pairwise(factors: Record<string, string[]>): Record<string, string>[] {
  const keys = Object.keys(factors), pairs = new Set<string>();
  for (const [i, a] of keys.entries()) for (const b of keys.slice(i + 1)) for (const x of factors[a]) for (const y of factors[b]) pairs.add(`${a}=${x}|${b}=${y}`);
  const rows: Record<string, string>[] = [];
  while (pairs.size) {
    const row: Record<string, string> = Object.fromEntries([...pairs][0].split("|").map((p) => p.split("="))); // an uncovered pair, then the best value of each other factor
    for (const k of keys.filter((k) => !(k in row))) {
      const gain = (v: string) => Object.keys(row).filter((j) => pairs.has(`${j}=${row[j]}|${k}=${v}`) || pairs.has(`${k}=${v}|${j}=${row[j]}`)).length;
      row[k] = factors[k].reduce((best, v) => (gain(v) > gain(best) ? v : best));
    }
    for (const [i, a] of keys.entries()) for (const b of keys.slice(i + 1)) pairs.delete(`${a}=${row[a]}|${b}=${row[b]}`);
    rows.push(row);
  }
  return rows;
}

const MATRIX = pairwise({ i: ["gdp_per_km2", "pop", "gdp_per_capita", "pop_density", "gdp_usd"], l: ["0", "2", "3"], v: ["", "s"], ss: ["", "1"], sk: ["inv2", "gauss"], sr: ["15", "100", "150"], r: ["", "1"], g: ["", "1"] });

test.describe("matrix", () => {
  test.setTimeout(600_000);
  test(`every pair of indicator, level, Smoothed, Include sea, kernel, radius, Relief and Globe (${MATRIX.length} states): no error, not blank, legend and tooltip`, async ({ page }) => {
    const errors = errorsOf(page);
    for (const [n, row] of MATRIX.entries()) {
      const hash = Object.entries(row).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join("&"), smooth = row.v === "s";
      await page.goto(`/?case=${n}#${hash}&c=4/50/10`);
      await settled(page);
      await page.mouse.move(640, 360);
      expect(await colours(page), hash).toBeGreaterThan(5);
      const legend = (await page.locator("#lg").innerText()).toLowerCase();
      expect(legend, hash).toContain(smooth ? "smoothed" : INDICATORS.find((i) => i.key === row.i)!.label.toLowerCase());
      if (!row.g && !(row.r && !smooth)) { // the centre of the screen is over Germany; on the globe or in flat relief the point may be off the land
        await page.mouse.move(641, 361);
        await expect(page.locator("#tip"), hash).toBeVisible();
      }
    }
    expect(errors).toEqual([]);
  });
});

test("rapid toggling of the surface, the theme and the focus ends in the state asked for, with no stale layer", async ({ page }) => {
  const errors = errorsOf(page);
  await page.goto("/#c=4/50/10");
  await settled(page);
  const flip = (js: string) => page.evaluate(js);
  const on = (id: string, v: boolean) => `{ const e = document.getElementById("${id}"); e.checked = ${v}; e.dispatchEvent(new Event("change")); }`;
  const theme = (v: string) => `{ const e = document.getElementById("theme"); e.value = "${v}"; e.dispatchEvent(new Event("change")); }`;
  await flip([on("smooth", true), on("mode-r", true), on("smooth", true), theme("light"), on("ss", true), on("mode-r", true), theme("dark"), on("smooth", true), theme("light"), on("relief", true)].join(";"));
  await settled(page);
  expect(page.url()).toMatch(/v=s.*ss=1|ss=1.*v=s/);
  expect(await map(page, `m.getLayoutProperty("smc", "visibility")`)).toBe("visible");
  expect(await map(page, `!!m.getTerrain()`)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe("light");
  await flip([on("relief", false), on("mode-r", true), on("smooth", true), on("mode-r", true), theme("dark")].join(";"));
  await page.waitForFunction(() => (window as any).__map.loaded() && (window as any).__map.getLayoutProperty("smc", "visibility") === "none");
  expect(await map(page, `!!m.getTerrain() || !!m.getLayer("shade") || m.getLayoutProperty("smv", "visibility") === "visible"`)).toBe(false);
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe("dark");
  await page.click("#export-btn"); // a frame opens (no focus): closing it leaves nothing behind
  await page.press("body", "Escape");
  await expect(page.locator("#fbar")).toBeHidden();
  expect(errors).toEqual([]);
});

test("every visible control has an accessible name", async ({ page }) => {
  await page.goto("/#c=4/50/10&s=ISO3:DEU");
  await settled(page);
  const nameless = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("select, input, button, summary, [role=combobox]")]
    .filter((e) => e.offsetParent !== null || e.closest("#fab"))
    .filter((e) => !(e.getAttribute("aria-label") || e.title || (e as HTMLInputElement).labels?.[0]?.textContent?.trim() || e.textContent?.trim()))
    .map((e) => e.id || e.className || e.tagName));
  expect(nameless).toEqual([]);
});

test.describe("edges", () => {
  test("map tiles that fail to load leave the controls working", async ({ page }) => {
    const errors = errorsOf(page);
    await page.route("**/regions.pmtiles", (r) => r.abort());
    await page.goto("/#c=4/50/10");
    await page.waitForFunction(() => (window as any).__map, null, { timeout: 60_000 });
    await page.selectOption("#ind", "pop");
    await expect(page.locator("#legend")).toContainText("Population");
    await sec(page, "sd");
    await page.selectOption("#level", "1");
    expect(page.url()).toContain("l=1");
    expect(errors.filter((e) => !/pmtiles|tile|Failed|aborted/i.test(e))).toEqual([]);
  });

  test("without WebGL the page says so instead of staying blank", async ({ page }) => {
    await page.addInitScript(() => { const get = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, t: string, ...a: any[]) { return /webgl/.test(t) ? null : (get as any).call(this, t, ...a); } as any; });
    await page.goto("/");
    await expect(page.locator("#toast")).toContainText("could not start");
  });

  test("without localStorage the cards still fold and everything works", async ({ page }) => {
    const errors = errorsOf(page);
    await page.addInitScript(() => Object.defineProperty(window, "localStorage", { get() { throw new Error("denied"); } }));
    await page.goto("/#c=4/50/10");
    await settled(page);
    await page.click("#legend .chev");
    await expect(page.locator("#legend")).toHaveClass(/folded/);
    expect(errors).toEqual([]);
  });

  test("animated camera moves (no reduced motion): searching a country flies there and the camera settles", async ({ browser }) => {
    const ctx = await browser.newContext({ reducedMotion: "no-preference", viewport: { width: 1280, height: 720 } });
    const page = await ctx.newPage(), errors = errorsOf(page);
    await page.goto("/");
    await settled(page);
    await page.fill("#q", "Germany");
    await page.press("#q", "Enter");
    await page.waitForFunction(() => (window as any).__map.getZoom() > 4 && !(window as any).__map.isMoving(), null, { timeout: 30_000 });
    expect(Math.abs((await map(page, `m.getCenter().lng`)) - 10)).toBeLessThan(6);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  for (const [w, h] of [[320, 480], [2560, 1440]]) {
    test(`a ${w}x${h} window: no horizontal scroll, the panels stay on screen and Hide panels works`, async ({ browser }) => {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: "reduce" });
      const page = await ctx.newPage(), errors = errorsOf(page);
      await page.goto("/#c=4/50/10&s=ISO3:DEU");
      await settled(page);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      const off = await page.evaluate(() => ["#head", "#tools", "#legend", "#panel"].filter((s) => { const r = document.querySelector(s)!.getBoundingClientRect(); return r.width && (r.left < -1 || r.right > innerWidth + 1); }));
      expect(off).toEqual([]);
      await page.click("#ui-btn");
      await expect(page.locator("#head")).toBeHidden();
      await page.click("#ui-btn");
      await expect(page.locator("#head")).toBeVisible();
      expect(errors).toEqual([]);
      await ctx.close();
    });
  }
});
