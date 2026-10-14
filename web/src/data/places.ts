import type { Row } from "./data";

export type Bounds = [number, number, number, number]; // west, south, east, north
type Pt = { x: number; y: number };
type Unit = [number, number]; // a point of the unit square of the world tile
type Layer = { extent: number; length: number; feature(i: number): { properties: any; loadGeometry(): Pt[][] } };

const lng = (u: number) => u * 360 - 180;
const lat = (v: number) => (Math.atan(Math.sinh(Math.PI * (1 - 2 * v))) * 180) / Math.PI;
const unit = (layer: Layer, f: { loadGeometry(): Pt[][] }): Unit[][] =>
  f.loadGeometry().map((ring) => ring.map((p) => [Math.min(Math.max(p.x / layer.extent, 0), 1), Math.min(Math.max(p.y / layer.extent, 0), 1)] as Unit));
const box = (ring: Unit[]): Bounds => {
  const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
  return [lng(Math.min(...xs)), lat(Math.max(...ys)), lng(Math.max(...xs)), lat(Math.min(...ys))];
};
const all = (layer: Layer) => Array.from({ length: layer.length }, (_, i) => layer.feature(i));
const features = (layer: Layer, id: string) => all(layer).filter((f) => f.properties.region_id === id);

const MAINLAND_KM = 2500;
const km = (a: [number, number], b: [number, number]) => {
  const r = Math.PI / 180, h = Math.sin(((b[1] - a[1]) * r) / 2) ** 2 + Math.cos(a[1] * r) * Math.cos(b[1] * r) * Math.sin(((b[0] - a[0]) * r) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
};
const centre = (b: Bounds): [number, number] => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];

/** Bounding boxes of every ring of a region in a layer of the world tile. */
export const ringBoxes = (layer: Layer, id: string): Bounds[] => features(layer, id).flatMap((f) => unit(layer, f).map(box));
const area = (b: Bounds) => (b[2] - b[0]) * (b[3] - b[1]);
/** Bounds of a region's largest ring, so Russia or Fiji do not span the antimeridian. */
export const bounds = (layer: Layer, id: string): Bounds | null => ringBoxes(layer, id).reduce<Bounds | null>((a, b) => (!a || area(b) > area(a) ? b : a), null);

/** The mainland of a country from the bounding boxes of its rings: the largest ring and every ring whose box centre lies within
 * 2,500 km (great circle) of that ring's centre; the rest is overseas. */
export function mainlandBounds(boxes: Bounds[]): { bounds: Bounds; overseas: boolean } | null {
  if (!boxes.length) return null;
  const main = boxes.reduce((a, b) => (area(b) > area(a) ? b : a)), c = centre(main);
  const near = boxes.filter((b) => b === main || km(c, centre(b)) <= MAINLAND_KM);
  return { bounds: union(near), overseas: near.length < boxes.length };
}
export const union = (bs: Bounds[]): Bounds => [Math.min(...bs.map((b) => b[0])), Math.min(...bs.map((b) => b[1])), Math.max(...bs.map((b) => b[2])), Math.max(...bs.map((b) => b[3]))];

/** Rings of the regions `ids` in a layer of the world tile, as points of the unit square (x east, y south), one list per feature. */
export const rings = (layer: Layer, ids: string[]): Unit[][][] => ids.flatMap((id) => features(layer, id).map((f) => unit(layer, f)));

/** Do two bounds overlap (edges count)? */
export const meets = (a: Bounds, b: Bounds) => a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3];
/** Is the point inside the bounds? The longitude may lie on another copy of the world. */
export const inBox = (b: Bounds, lng: number, lat: number) => {
  const x = ((((lng + 180) % 360) + 360) % 360) - 180;
  return x >= b[0] && x <= b[2] && lat >= b[1] && lat <= b[3];
};
/** Ids of the regions of a layer with any ring whose bounding box meets `b` (the rule for "intersects the area": generous at the edge). */
const boxesOf = new WeakMap<Layer, [string, Bounds[]][]>(); // per layer, once: the ring boxes of every feature
export const meeting = (layer: Layer, b: Bounds): string[] => {
  if (!boxesOf.has(layer)) boxesOf.set(layer, all(layer).map((f) => [f.properties.region_id, unit(layer, f).map(box)]));
  return [...new Set(boxesOf.get(layer)!.filter(([, rings]) => rings.some((r) => meets(r, b))).map(([id]) => id))];
};

const norm = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** Regions of every level whose name matches: exact, then name prefix, word prefix, substring; within a class the largest GDP first. */
export function search(rows: Iterable<Row>, query: string, limit = 8): Row[] {
  const q = norm(query.trim());
  if (!q) return [];
  const score = (r: Row) => {
    const n = norm(r.name);
    return n === q ? 0 : n.startsWith(q) ? 1 : n.includes(" " + q) ? 2 : n.includes(q) ? 3 : 9;
  };
  return [...rows].map((r) => [r, score(r)] as const).filter(([, s]) => s < 9)
    .sort(([a, s], [b, t]) => s - t || (b.gdp_usd ?? 0) - (a.gdp_usd ?? 0) || a.id.localeCompare(b.id))
    .slice(0, limit).map(([r]) => r);
}
