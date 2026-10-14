import { sec } from "./ui";
import { expect, test, type Page } from "@playwright/test";
import { DEVICES } from "./devices";

const CARDS = ["head", "tools", "legend"];
const box = (page: Page, sel: string) => page.locator(sel).evaluate((e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; });

for (const d of DEVICES) test.describe(d.name, () => {
  test.use(d.use);

  test("round buttons stay reachable, cards never overlap or leave the screen, whatever is folded", async ({ page }) => {
    await page.goto("/#c=5/50/10&f=ISO3:KAZ");
    await page.waitForFunction(() => (window as any).__map?.loaded());
    await page.evaluate(() => ((document.getElementById("sc") as HTMLDetailsElement).open = true)); // the scale panel stays open: the legend card must hold it
    for (let folds = 0; folds < 8; folds++) {
      for (const [i, id] of CARDS.entries()) {
        const chev = page.locator(`#${id} .chev`), open = !(folds & (1 << i));
        if ((await chev.getAttribute("aria-expanded")) !== String(open)) await chev.click();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `horizontal scroll, folds ${folds}`).toBe(true);
      expect(await page.evaluate(() => { const b = document.getElementById("ui-btn")!.getBoundingClientRect(), e = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2); return e?.closest("#ui-btn") !== null; }), `Hide panels covered, folds ${folds}`).toBe(true);
      const boxes = await Promise.all(CARDS.map((id) => box(page, "#" + id)));
      const { width: w, height: h } = page.viewportSize()!;
      for (const [i, a] of boxes.entries()) {
        expect(a.l >= 0 && a.t >= 0 && a.r <= w && a.b <= h, `${CARDS[i]} outside the screen, folds ${folds}`).toBe(true);
        for (const c of boxes.slice(i + 1)) expect(a.l >= c.r || c.l >= a.r || a.t >= c.b || c.t >= a.b, `cards overlap, folds ${folds}`).toBe(true);
      }
      if (!(folds & 4)) expect(await page.evaluate(() => document.querySelector("#legend .ticks")!.getBoundingClientRect().bottom <= document.getElementById("legend")!.getBoundingClientRect().bottom), `legend clipped, folds ${folds}`).toBe(true);
      if (!(folds & 4)) expect(await page.evaluate(() => document.getElementById("cauto")!.getBoundingClientRect().bottom <= document.getElementById("legend")!.getBoundingClientRect().bottom), `scale panel clipped, folds ${folds}`).toBe(true);
    }
  });

  test("Data section and Smoothing options open: cards stay on screen and apart, section summaries are 44 px targets on a phone, the section survives folding", async ({ page }) => {
    await page.goto("/#c=5/50/10&f=ISO3:KAZ&v=s");
    await page.waitForFunction(() => (window as any).__map?.loaded());
    await sec(page, "sd");
    await page.evaluate(() => ((document.getElementById("smopts") as HTMLDetailsElement).open = true));
    const { width: w, height: h } = page.viewportSize()!;
    for (const id of CARDS) { // the left column scrolls on a short screen: every card can be brought on screen, and is no taller than it
      await page.locator("#" + id).scrollIntoViewIfNeeded();
      const a = await box(page, "#" + id);
      expect(a.l >= 0 && a.t >= 0 && a.r <= w && a.b <= h, `${id} outside the screen`).toBe(true);
    }
    const boxes = await Promise.all(CARDS.map((id) => box(page, "#" + id)));
    for (const [i, a] of boxes.entries()) for (const c of boxes.slice(i + 1)) expect(a.l >= c.r || c.l >= a.r || a.t >= c.b || c.t >= a.b, "cards overlap").toBe(true);
    if (d.use.hasTouch) for (const t of ["#sc", "#sd", "#sa"]) expect((await box(page, t + " summary")).b - (await box(page, t + " summary")).t, t).toBeGreaterThanOrEqual(44);
    await page.click("#legend .chev");
    await page.click("#legend .chev");
    await expect(page.locator("#sd")).toHaveAttribute("open", "");
    await expect(page.locator("#level")).toBeVisible();
  });

  test("search results open on screen (upward from the Map card on a phone) and a result can be picked with the keyboard", async ({ page }) => {
    await page.goto("/#c=5/50/10");
    await page.waitForFunction(() => (window as any).__map?.loaded());
    if (await page.locator("#tools.folded").count()) await page.click("#tools .chev");
    await page.fill("#q", "ger");
    await expect(page.locator("#results li").first()).toBeVisible();
    const r = await box(page, "#results"), { width: w, height: h } = page.viewportSize()!;
    expect(r.l >= 0 && r.t >= 0 && r.r <= w && r.b <= h, "results outside the screen").toBe(true);
    await page.keyboard.press("Enter");
    await expect(page.locator("#panel h2")).toBeVisible();
  });

  test("the compass shows only when north is not up, turns with the map, resets on a click and overlaps nothing", async ({ page }) => {
    await page.goto("/#c=5/50/10&f=ISO3:DEU");
    await page.waitForFunction(() => (window as any).__map?.loaded());
    const turn = (b: number) => page.evaluate((b) => (window as any).__map.setBearing(b), b);
    await expect(page.locator("#compass")).toBeHidden();
    await turn(40);
    await expect(page.locator("#compass")).toBeVisible();
    expect(await page.locator("#compass svg").evaluate((e) => (e as SVGElement).style.transform)).toBe("rotate(-40deg)");
    const clear = async (what: string) => {
      const c = await box(page, "#compass"), { width: w, height: h } = page.viewportSize()!;
      expect(c.l >= 0 && c.t >= 0 && c.r <= w && c.b <= h, `${what}: compass outside the screen`).toBe(true);
      for (const sel of ["#head h1", "#tools", "#legend", "#ui-btn", "#area", "#panel", ".maplibregl-ctrl-bottom-right"]) {
        const a = await box(page, sel).catch(() => null);
        if (a && a.r > a.l && a.b > a.t) expect(a.l >= c.r || c.l >= a.r || a.t >= c.b || c.t >= a.b, `${what}: compass overlaps ${sel}`).toBe(true);
      }
    };
    await clear("rotated");
    if (!d.use.hasTouch) {
      const p = await page.evaluate(() => (window as any).__map.project([10, 50.5]));
      await page.mouse.click(p.x, p.y);
      await expect(page.locator("#panel h2")).toBeVisible();
      await clear("panel open");
    }
    await page.click("#ui-btn");
    await clear("panels hidden");
    await page.click("#compass");
    await expect(page.locator("#compass")).toBeHidden();
    expect(await page.evaluate(() => [(window as any).__map.getBearing(), (window as any).__map.getPitch()])).toEqual([0, 0]);
  });

  if (d.use.hasTouch) test("a tap on a region opens its panel", async ({ page }) => {
    await page.goto("/#c=5/50/10");
    await page.waitForFunction(() => (window as any).__map?.loaded());
    const p = await page.evaluate(() => (window as any).__map.project([10, 50.5]));
    await page.touchscreen.tap(p.x, p.y);
    await expect(page.locator("#panel h2")).toBeVisible();
  });

  test("the Focus button and the open frame's handles, bar and readout are reachable with hit areas of 44 px", async ({ page }) => {
    await page.goto("/#c=5/50/10");
    await page.waitForFunction(() => (window as any).__map?.loaded());
    const top = (sel: string) => page.evaluate((sel) => { const b = document.querySelector(sel)!.getBoundingClientRect(), e = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2); return e?.closest(sel) !== null; }, sel);
    expect(await top("#area"), "Focus area covered").toBe(true);
    await page.click("#area");
    for (const h of ["nw", "n", "ne", "e", "se", "s", "sw", "w"]) {
      const r = await page.locator(`#frame [data-h=${h}]`).boundingBox();
      expect(r!.width >= 44 && r!.height >= 44, `${h} hit area`).toBe(true);
      expect(await top(`[data-h=${h}]`), `${h} covered`).toBe(true);
    }
    for (const sel of ["#fok", "#fcancel", "#fasp"]) expect(await top(sel), `${sel} covered`).toBe(true);
    const f = await page.locator("#frame").boundingBox(), { width: w, height: h } = page.viewportSize()!;
    expect(f!.x >= 0 && f!.y >= 0 && f!.x + f!.width <= w && f!.y + f!.height <= h, "frame inside the screen").toBe(true);
    const bar = await box(page, "#fbar");
    expect(bar.l >= 0 && bar.r <= w && bar.t >= 0 && bar.b <= h, "bar inside the screen").toBe(true);
  });

  if (d.use.hasTouch && d.name === "phone 393x852") test("a touch drag on a handle resizes the frame, the map pans outside it, Apply sets the focus", async ({ page }) => {
    await page.goto("/#c=5/50/10");
    await page.waitForFunction(() => (window as any).__map?.loaded());
    await page.click("#area");
    const cdp = await page.context().newCDPSession(page), touch = (type: string, x: number, y: number) => cdp.send("Input.dispatchTouchEvent", { type, touchPoints: type === "touchEnd" ? [] : [{ x, y }] });
    const [h, before] = [(await page.locator("#frame [data-h=se]").boundingBox())!, (await page.locator("#frame").boundingBox())!];
    const [x, y] = [h.x + h.width / 2, h.y + h.height / 2];
    await touch("touchStart", x, y);
    for (let i = 1; i <= 5; i++) await touch("touchMove", x + i * 6, y + i * 10);
    await touch("touchEnd", 0, 0);
    const after = (await page.locator("#frame").boundingBox())!;
    expect(after.width).toBeCloseTo(before.width + 30, -1);
    expect(after.height).toBeCloseTo(before.height + 50, -1);
    expect(Math.abs(after.x - before.x)).toBeLessThan(1); // the opposite corner stays
    const c = await page.evaluate(() => (window as any).__map.getCenter().lng);
    await touch("touchStart", 20, after.y + after.height + 120); // outside the frame, on the map
    for (let i = 1; i <= 5; i++) await touch("touchMove", 20 + i * 12, after.y + after.height + 120);
    await touch("touchEnd", 0, 0);
    await expect.poll(() => page.evaluate(() => (window as any).__map.getCenter().lng)).not.toBeCloseTo(c, 1);
    await page.click("#fok");
    await expect.poll(() => page.url()).toContain("fb=");
  });
});
