import { describe, expect, it } from "vitest";
import { DEFAULT, PER_KM2, type State, clean, fromHash, smoothColours, smoothIndicator, toHash } from "../src/state/state";

const valid = ["gdp_usd", "gdp_per_km2", "pop", "pop_density"];

describe("url state", () => {
  it("default state gives an empty hash", () => expect(toHash(DEFAULT)).toBe(""));
  it("round-trips every field", () => {
    const s = { ind: "pop_density", level: 1, globe: true, estimates: false, relief: true, base: 2000, palette: "viridis_r", classes: 5, rule: "share" as const, borders: false, smooth: true, kernel: "gauss", radius: 100, sea: true, scale: "view" as const, cmin: 5, cmax: 7.5, local: true, sel: "NUTS2024:DE111", cam: [4.5, 50.1, 10] as [number, number, number], theme: "light" as const, ui: false, focus: ["DEU", "FRA"], box: null, overseas: true };
    expect(toHash(s)).toBe("i=pop_density&l=1&b=2000&p=viridis_r&k=5&q=share&sk=gauss&sr=100&th=light&g=1&e=0&r=1&o=0&ss=1&lx=1&ui=0&fo=1&v=s&sf=1&cl=5&ch=7.5&s=NUTS2024:DE111&c=4.5/50.1/10&f=DEU,FRA");
    expect(fromHash("#" + toHash(s), valid, [2000])).toEqual(s);
  });
  it("every pair of non-default values round-trips, cleaned as the app does", () => {
    const alt: Partial<State>[] = [{ ind: "pop" }, { level: 1 }, { globe: true }, { estimates: false }, { relief: true }, { base: 2000 }, { palette: "viridis_r" }, { classes: 5 }, { rule: "share" }, { borders: false }, { smooth: true },
      { kernel: "gauss" }, { radius: 150 }, { sea: true }, { scale: "view" }, { scale: "world" }, { cmin: 4 }, { cmax: 7 }, { local: true }, { cam: [4, 50, 10] }, { theme: "dark" },
      { ui: false }, { focus: ["DEU", "FRA"] }, { box: [1, 2, 3, 4] }, { overseas: true }];
    for (const a of alt) for (const b of alt) {
      const s = clean({ ...DEFAULT, ...a, ...b });
      if (s.box) s.focus = [];
      if (s.smooth) s.ind = PER_KM2[s.ind] ?? s.ind; // a link loads Smoothed with the per-km2 version
      expect(fromHash("#" + toHash(s), valid, [2000])).toEqual(s);
    }
  });
  it("theme, ui, focus, box and overseas: defaults omitted, invalid values fall back, ids normalised, box wins over focus", () => {
    expect(toHash({ ...DEFAULT, theme: "auto", ui: true, focus: [], box: null, overseas: false })).toBe("");
    expect(fromHash("#th=sepia&ui=1&f=&fb=1,2,3&fo=0", valid)).toEqual(DEFAULT);
    expect(fromHash("#th=dark", valid).theme).toBe("dark");
    expect(fromHash("#f=FRA,DEU,FRA,,DEU", valid).focus).toEqual(["DEU", "FRA"]);
    expect(toHash({ ...DEFAULT, focus: ["FRA", "DEU", "FRA"] })).toBe("f=DEU,FRA");
    const box = { ...DEFAULT, box: [-5.5, 41.25, 9.123, 51.1] as [number, number, number, number] };
    expect(toHash(box)).toBe("fb=-5.5,41.25,9.123,51.1");
    expect(fromHash("#" + toHash(box), valid)).toEqual(box);
    expect(fromHash("#f=DEU&fb=1.00049,2,3,4", valid)).toMatchObject({ focus: [], box: [1, 2, 3, 4] });
    expect(fromHash("#fb=1,2,x,4", valid).box).toBeNull();
    expect(toHash({ ...DEFAULT, box: [1, 2, 3, 4], focus: ["DEU"] })).toBe("fb=1,2,3,4");
  });
  it("l= is the level shown: 0 (continents) to 3; absent (old links) or invalid means 3, the finest and the default", () => {
    expect(DEFAULT.level).toBe(3);
    expect([0, 1, 2, 3].map((l) => fromHash(toHash({ ...DEFAULT, level: l }), valid).level)).toEqual([0, 1, 2, 3]);
    expect([0, 3].map((l) => toHash({ ...DEFAULT, level: l }))).toEqual(["l=0", ""]);
    expect(["#i=pop", "#l=3", "#l=4", "#l=x", "#l=", "#l=-1", "#l=12"].map((h) => fromHash(h, valid).level)).toEqual([3, 3, 3, 3, 3, 3, 3]);
  });
  it("palette, classes and rule fall back to the gradient defaults when invalid", () => {
    expect(fromHash("#p=toString&k=9&q=x&o=1", valid)).toEqual(DEFAULT);
    expect([3, 7].map((k) => fromHash("#k=" + k, valid).classes)).toEqual([3, 7]);
  });
  it("smoothed view: kernel and radius must be offered, else the defaults", () => {
    expect(fromHash("#v=s&sk=gauss&sr=100&ss=1", valid)).toMatchObject({ smooth: true, kernel: "gauss", radius: 100, sea: true });
    expect(fromHash("#so=1", valid)).toMatchObject({ sea: true });
    expect(toHash({ ...DEFAULT, sea: true })).not.toContain("so=");
    expect(["#sf=1", "#sf=0", "#sf=x", "#sf", "#sf=1&sw=1"].map((h) => fromHash(h, valid).scale)).toEqual(["view", "auto", "auto", "auto", "view"]);
    expect(["#sw=1", "#sw=1&f=DEU", "#sw=1&fb=1,2,3,4"].map((h) => fromHash(h, valid).scale)).toEqual(["auto", "world", "world"]); // World differs from auto only in a focus
    expect(toHash({ ...DEFAULT, focus: ["DEU"], scale: "world" })).toBe("sw=1&f=DEU");
    expect(fromHash("#v=x&sk=cube&sr=x&ss=0&so=0&sf=2", valid)).toEqual(DEFAULT);
    expect(toHash({ ...DEFAULT, kernel: "gauss", radius: 15 })).toBe("sk=gauss&sr=15");
    expect([DEFAULT.kernel, DEFAULT.radius]).toEqual(["inv2", 50]);
    expect(["exp", "epan", "inv2", "ball", "gauss"].map((k) => fromHash("#sk=" + k, valid).kernel)).toEqual(["inv2", "inv2", "inv2", "inv2", "gauss"]); // removed kernels (ball too): the default
    expect([15, 30, 100, 150, "x", 0].map((r) => fromHash("#sr=" + r, valid).radius)).toEqual([15, 30, 100, 150, 50, 50]);
  });
  it("old radii map to the nearest of the ladder (25, 40 to 30; 75 to 100; 200, 400, 800 to 150)", () => {
    expect([10, 25, 35, 40, 45, 75, 200, 400, 800].map((r) => fromHash("#sr=" + r, valid).radius)).toEqual([15, 30, 30, 30, 50, 100, 150, 150, 150]);
    expect(toHash(fromHash("#sr=25", valid))).toBe("sr=30");
  });
  it("local excess: lx=1, off where no wider radius exists; removed keys (er, sx, ER selections) are ignored", () => {
    expect(fromHash("#v=s&sr=100&lx=1", valid)).toMatchObject({ radius: 100, local: true });
    expect(toHash({ ...DEFAULT, local: true })).toBe("lx=1");
    expect(fromHash("#sr=200&lx=1", valid)).toMatchObject({ radius: 150, local: false });
    expect(clean({ ...DEFAULT, radius: 150, local: true }).local).toBe(false);
    expect(fromHash("#er=1&sx=100&sx=sea&v=s", valid)).toEqual({ ...DEFAULT, smooth: true });
  });
  it("switching Smoothing on gives 6 classes from the gradient and off takes them back; a chosen number is kept", () => {
    expect(smoothColours(0, true, false)).toEqual({ classes: 6, auto: true });
    expect(smoothColours(6, false, true)).toEqual({ classes: 0, auto: false });
    expect(smoothColours(4, false, true)).toEqual({ classes: 4, auto: false }); // changed meanwhile
    expect(smoothColours(4, true, false)).toEqual({ classes: 4, auto: false });
    expect(smoothColours(6, false, false)).toEqual({ classes: 6, auto: false }); // a link's own 6 classes stay
    expect(toHash({ ...DEFAULT, smooth: true, classes: 6 })).toBe("k=6&v=s");
  });
  it("Smoothed offers per-km2 versions: a total maps to it and back, an old link loads as the per-km2 version", () => {
    expect(smoothIndicator("gdp_usd", true, null)).toEqual({ ind: "gdp_per_km2", back: "gdp_usd" });
    expect(smoothIndicator("pop", true, null)).toEqual({ ind: "pop_density", back: "pop" });
    expect(smoothIndicator("gdp_per_capita", true, "pop")).toEqual({ ind: "gdp_per_capita", back: null });
    expect(smoothIndicator("pop_density", false, "pop")).toEqual({ ind: "pop", back: null });
    expect(smoothIndicator("gdp_per_capita", false, "pop")).toEqual({ ind: "gdp_per_capita", back: null }); // changed meanwhile
    expect(smoothIndicator("pop_density", false, null)).toEqual({ ind: "pop_density", back: null });
    expect(fromHash("#i=gdp_usd&v=s", valid)).toMatchObject({ ind: "gdp_per_km2", smooth: true });
    expect(fromHash("#i=pop&v=s", valid)).toMatchObject({ ind: "pop_density", smooth: true });
    expect(fromHash("#i=pop", valid).ind).toBe("pop");
    expect(toHash(fromHash("#i=pop&v=s", valid))).toBe("i=pop_density&v=s");
    expect(fromHash("#v=s", valid).classes).toBe(0); // a link states its colours: none means the gradient
  });
  it("manual colour range: cl/ch are log10, a reversed pair is dropped, junk is ignored", () => {
    expect(fromHash("#cl=4&ch=6", valid, [2000])).toMatchObject({ cmin: 4, cmax: 6 });
    expect(fromHash("#cl=6&ch=4", valid, [2000])).toMatchObject({ cmin: null, cmax: null });
    expect(fromHash("#cl=x&ch=", valid, [2000])).toMatchObject({ cmin: null, cmax: null });
  });
  it("drops a base year that has no deflator", () => expect(fromHash("#b=1800", valid, [2000]).base).toBeNull());
  it("falls back to defaults for an unknown indicator or a broken camera", () => {
    expect(fromHash("#i=nope&c=1/x/3", valid)).toEqual(DEFAULT);
    expect(fromHash("", valid)).toEqual(DEFAULT);
  });
});
