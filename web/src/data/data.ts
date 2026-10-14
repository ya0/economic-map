import { INDICATORS } from "../scales/scales";

export type Row = { id: string; name: string; level_no: number; parent_id: string | null; iso2: string; flags: string[]; [column: string]: any };
/** `leaves`: ids of the regions that are nobody's parent, each country's finest level. */
export type Data = { ref: number; rows: Map<string, Row>; leaves: Set<string>; worldGdp: number; deflator: Record<string, number> };

/** level_no -> name of one region of that level; the selector uses the plural. */
export const LEVELS = ["Continent", "Country", "Region", "Sub-region"];

/** indicators.json -> rows of every level keyed by region_id, columns named per meta.columns. */
export function parse(json: any): Data {
  const { meta, regions } = json;
  const rows = new Map<string, Row>();
  for (const [id, values] of Object.entries<any[]>(regions))
    rows.set(id, { id, ...Object.fromEntries(meta.columns.map((c: string, i: number) => [c, values[i]])) } as Row);
  const leaves = new Set(rows.keys());
  for (const r of rows.values()) leaves.delete(r.parent_id!);
  const d: Data = { ref: meta.ref_year, rows, leaves, worldGdp: 0, deflator: meta.deflator_us_gdp ?? {} };
  const unallocated = Object.values<number>(meta.unallocated_gdp_usd ?? {}).reduce((a, b) => a + b, 0);
  d.worldGdp = cover(d, 0).reduce((a, r) => a + (r.gdp_usd ?? 0), unallocated);
  return d;
}

export const isDisputed = (r: Row) => r.flags.includes("disputed");

/** The regions the map shows at level `no`, a complete cover of the world: that level, the finest regions of countries
 * that stop above it, and the disputed region. Totals, ranks and scale domains are computed over one cover only. */
export const cover = (d: Data, no: number): Row[] =>
  [...d.rows.values()].filter((r) => r.level_no === no || (r.level_no < no && d.leaves.has(r.id)) || isDisputed(r));

/** A region's ancestors and itself, continent first. */
export function chain(d: Data, id: string): Row[] {
  const out: Row[] = [];
  for (let r = d.rows.get(id); r; r = d.rows.get(r.parent_id!)) out.unshift(r);
  return out;
}

/** Is the row in focus: its id or one of its ancestors' ids is in the set. An empty set is no focus: everything. */
export function inFocus(d: Data, r: Row, focus: ReadonlySet<string>): boolean {
  if (!focus.size) return true;
  for (let x: Row | undefined = r; x; x = d.rows.get(x.parent_id!)) if (focus.has(x.id)) return true;
  return false;
}

/** Estimates, derived (`pop_share`) regions, and below continent level the sums that contain an estimate (a continent's GDP is mostly measured). */
const isShown = (r: Row, estimates: boolean) => estimates || !(r.flags.includes("estimate") || r.flags.includes("pop_share") || (r.level_no > 0 && r.flags.includes("contains_estimate")));

/** With Estimates off a derived region stands for its country: the nearest ancestor that is not derived (the row itself otherwise). */
export function standIn(d: Data, r: Row, estimates: boolean): Row {
  let x = r;
  while (!estimates && x.flags.includes("pop_share") && d.rows.has(x.parent_id!)) x = d.rows.get(x.parent_id!)!;
  return x;
}

/** Of the shown rows of one cover: their number and their share of world GDP, in total and below country level. */
export function coverage(d: Data, shown: Row[], estimates: boolean): { n: number; all: number; sub: number } {
  const rows = [...new Set(shown.map((r) => standIn(d, r, estimates)))].filter((r) => isShown(r, estimates) && r.gdp_usd > 0);
  const share = (rs: Row[]) => rs.reduce((a, r) => a + r.gdp_usd, 0) / d.worldGdp;
  return { n: rows.length, all: share(rows), sub: share(rows.filter((r) => r.level_no > 1)) };
}

/** Constant-dollar factor for base year B: values are current US$ of the reference year, so x deflator[B]/deflator[ref]. */
export const priceFactor = (d: Data, base: number | null) => (base == null ? 1 : d.deflator[base] / d.deflator[d.ref]);
export const basisLabel = (base: number | null) => (base == null ? "current US$" : `constant ${base} US$`);

const MONEY = new Set(INDICATORS.filter((i) => i.money).map((i) => i.key));

/** Row with its money columns rescaled; people and area columns never change. */
export const rescale = (r: Row, f: number): Row =>
  f === 1 ? r : { ...r, ...Object.fromEntries([...MONEY].filter((k) => typeof r[k] === "number").map((k) => [k, r[k] * f])) };

/** Feature-state value for one indicator: undefined means "no data" (grey). */
export function valueOf(r: Row | undefined, key: string, estimates: boolean, f = 1): number | undefined {
  if (!r || !isShown(r, estimates)) return undefined;
  const v = r[key];
  return typeof v === "number" && v > 0 ? v * (MONEY.has(key) ? f : 1) : undefined;
}
