import type { Row } from "./data";

const TEXT: Record<string, (r: Row, ref: number) => string> = {
  gdp_year_offset: (r, ref) => `GDP shares are from ${r.gdp_year}, not ${ref}.`,
  national_year_offset: (_, ref) => `The national GDP total is from before ${ref}.`,
  pop_year_offset: (r, ref) => `Population is from ${r.pop_year}, not ${ref}.`,
  fiscal_year: () => "The year is the start of a fiscal year.",
  constant_prices: () => "Regional shares come from constant-price figures.",
  wikipedia_secondary: (r) => (r.flags.includes("pop_share") ? "Population comes from a Wikipedia table that cites an official census." : "GDP comes from a Wikipedia table that cites an official source."),
  pop_share: () => "GDP split by population (derived): the national total shared by each region's population, so GDP per capita is the national value by construction.",
  pop_scaled: () => "Population scaled to the national total.",
  pop_secondary: () => "Population comes from a republisher of the official census.",
  estimate: () => "The cited origin is an estimate or model, not a published count.",
  wikidata: () => "Population comes from Wikidata (secondary source).",
  census_va_share: () => "GDP split within the state by census value added, not official regional GDP.",
  remainder: () => "Rest of province or state outside the listed metro areas.",
  area_computed: () => "Area is computed from the map outline.",
  whole_country: () => "Shown as one whole country; no regional data found.",
  imf_estimate: () => "National GDP is an IMF estimate.",
  aggregated: () => "Sum of the regions below it.",
  contains_estimate: () => "Some regions below it are estimates or models.",
  contains_wikipedia_secondary: () => "Some regions below it take GDP from a Wikipedia table.",
  contains_wikidata: () => "Some regions below it take population from Wikidata.",
  contains_pop_share: () => "Some regions below it split the national GDP by population (derived).",
  partial_population: () => "Population is a lower bound: some sub-regions have no figure.",
  disputed: () => "Disputed territory: shown without data and counted in no country.",
};

/** Plain-words text per flag; an unknown flag falls back to its own name. */
export const flagText = (flag: string, r: Row, ref: number) =>
  TEXT[flag]?.(r, ref) ?? `Note: ${flag.replaceAll("_", " ")}.`;

/** One lazily loaded SVG per country (flag-icons, MIT); only the urls are in the bundle. */
const URLS = import.meta.glob<string>("/node_modules/flag-icons/flags/4x3/??.svg", { query: "?url&no-inline", import: "default", eager: true });

/** Url of a country's flag by ISO 3166-1 alpha-2 code; undefined for continents and the disputed region (no code). */
export const flagUrl = (iso2: string): string | undefined => URLS[`/node_modules/flag-icons/flags/4x3/${iso2.toLowerCase()}.svg`];
