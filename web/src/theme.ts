export type Theme = "dark" | "light";

const dark = {
  ocean: "#111721", // a shade above the page, so the globe edge shows
  paper: "#000", // outside a focus
  edge: "#fff", // the outline of a focus
  noData: "#4a5059",
  disputed: "#232a35",
  border: "#fff",
  label: "#fff",
  halo: "rgba(11,14,19,.9)",
  hover: "#fff",
  select: "#ffb000",
  veil: "#111721e6", // sea under the smoothed apron's shading: ocean at 90% opacity
  shadow: "rgba(0,0,0,.5)", // hillshade
  highlight: "rgba(255,255,255,.15)",
};
export type Colours = typeof dark;

const light: Colours = {
  ocean: "#cfe4f2",
  paper: "#fff",
  edge: "#000",
  noData: "#e6e3da",
  disputed: "#b3adc0",
  border: "#4a5059",
  label: "#262b33",
  halo: "rgba(255,255,255,.9)",
  hover: "#0b0e13",
  select: "#d46a00",
  veil: "#cfe4f2e6",
  shadow: "rgba(30,40,60,.38)",
  highlight: "rgba(255,255,255,.6)",
};

const THEMES: Record<Theme, Colours> = { dark, light };

/** The theme in use, set by `setTheme`; `current()` reads it. */
let now: Theme = "dark";
export const current = (): Colours => THEMES[now];
export const currentName = () => now;
export const setTheme = (name: Theme) => { now = name; };
/** The chosen theme; "auto" follows the system. */
export const resolve = (pref: "auto" | Theme): Theme => (pref !== "auto" ? pref : matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
