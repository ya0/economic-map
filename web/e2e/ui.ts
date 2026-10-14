import type { Page } from "@playwright/test";

/** Unfold the legend card (folded on a phone). */
export async function unfold(page: Page) {
  if (await page.locator("#legend.folded").count()) await page.click("#legend .chev");
}

/** Open a section of the legend card: Scale and colours (`sc`), Data (`sd`) or Appearance (`sa`); the others close. */
export async function sec(page: Page, id: "sc" | "sd" | "sa") {
  await unfold(page);
  if (!(await page.locator("#" + id).evaluate((e) => (e as HTMLDetailsElement).open))) await page.click(`#${id} summary`);
}

/** Open the Smoothing options (collapsed whenever they appear). */
export async function opts(page: Page) {
  if (!(await page.locator("#smopts").evaluate((e) => (e as HTMLDetailsElement).open))) await page.click("#smopts summary");
}
