import { describe, expect, it } from "vitest";
import { cropRect, exportRatio, fileName, subtitle } from "../src/export";
import { INDICATORS, times } from "../src/scales/scales";
import { legendModel } from "../src/ui/ui";

describe("export", () => {
  it("ratio: crop at least 1920 x 1080 and 2x, the cap by texture size and pixel budget, Maximum takes the cap", () => {
    const d = (c: [number, number], w = 1920, h = 1080, limit = 8192, budget = 40e6, max = false) => exportRatio({ w: c[0], h: c[1] }, w, h, limit, budget, max);
    expect(d([1920, 1080])).toBe(2); // a full desktop map: 2x (3840 x 2160)
    expect(d([393, 852], 393, 852, 8192, 24e6)).toBeCloseTo(1080 / 393); // a phone: 1081 x 2343, not 1x
    expect(d([600, 700])).toBeCloseTo(1920 / 700 > 1080 / 600 ? 1920 / 700 : 1080 / 600);
    expect(d([100, 100])).toBeCloseTo(8192 / 1920); // a tiny crop is capped by the texture size
    expect(d([1920, 1080], 1920, 1080, 2048)).toBeCloseTo(2048 / 1920);
    expect(d([393, 852], 393, 852, 8192, 2e6)).toBeCloseTo(Math.sqrt(2e6 / (393 * 852))); // the pixel budget
    expect(d([1920, 1080], 1920, 1080, 8192, 40e6, true)).toBeCloseTo(8192 / 1920); // Maximum
  });
  it("crop: corners in any order, margin on each side, clamped to the map", () => {
    expect(cropRect([200, 100, 100, 300], 0, 1000, 800)).toEqual({ x: 100, y: 100, w: 100, h: 200 });
    expect(cropRect([100, 100, 200, 300], 0.1, 1000, 800)).toEqual({ x: 90, y: 80, w: 120, h: 240 });
    expect(cropRect([-50, -20, 1200, 900], 0.04, 1000, 800)).toEqual({ x: 0, y: 0, w: 1000, h: 800 });
    expect(cropRect([1100, 10, 1200, 50], 0, 1000, 800)).toBeNull();
  });
  it("file name: focus or world, indicator, year", () => {
    expect(fileName([], "gdp_per_km2", 2024)).toBe("gdp-density_world_gdp_per_km2_2024.png");
    expect(fileName(["Germany"], "pop", 2024)).toBe("gdp-density_germany_pop_2024.png");
    expect(fileName(["Côte d'Ivoire", "Ghana"], "pop", 2024)).toBe("gdp-density_cote-d-ivoire-ghana_pop_2024.png");
    expect(fileName(["a", "b", "c", "d", "e"], "pop", 2024)).toBe("gdp-density_a-b-c-and-2-more_pop_2024.png");
  });
  it("subtitle: focus, level (not when smoothed), price basis (money only), data year", () => {
    const o = { focus: ["Germany"], area: false, level: 2, money: true, base: null, year: 2024 };
    expect(subtitle(o)).toBe("Germany · Region level · current US$ · data 2024");
    expect(subtitle({ ...o, focus: [], level: null, money: false, base: 2015 })).toBe("World · data 2024");
    expect(subtitle({ ...o, focus: [], area: true, base: 2015 })).toContain("Selected area · Region level · constant 2015 US$");
  });
  it("legend model: gradient ticks from 0 to 1, or class swatches with ranges", () => {
    const g = legendModel(INDICATORS[0], [2, 4]);
    expect(g.classes).toBeUndefined();
    expect(g.ticks[0]).toEqual([0, "≤$100"]);
    expect(g.ticks.at(-1)).toEqual([1, "≥$10k"]);
    expect(g.unit).toBe("current US$ per km², log scale");
    const c = legendModel(INDICATORS[0], [2, 4], null, "magma", [3]);
    expect(c.classes!.map(([, t]) => t)).toEqual(["<$1k", "≥$1k"]);
  });
  it("legend model: a scale with a highest value (Sea effect, 1x) stops there, on half the diverging gradient", () => {
    const m = legendModel({ key: "sea", label: "", unit: "", money: false, fmt: times, max: 0 }, [-1, 1], null, "rdbu");
    expect(m.ticks.map(([, t]) => t)).toEqual(["≤0.1×", "0.33×", "1×"]);
    expect(m.grad.at(-1)![0]).toBe(1);
    expect(m.grad.length).toBe(5);
  });
});
