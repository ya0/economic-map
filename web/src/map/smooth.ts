import { SMOOTH } from "../scales/scales";
/** smooth.json: the log10 range of the 16-bit code (GDP per km2's; `indicators` has each set's file prefix and range), the latitude span of
 * the Web Mercator rows, the kernels. */
export type Meta = { lo: number; hi: number; north: number; south: number; kernels: string[]; indicators: Record<string, { prefix: string; lo: number; hi: number }> };
type Surface = { w: number; h: number; rgba: Uint8Array };
type Grid = { w: number; h: number; vals: Float32Array };
/** How the bytes decode (see `decode`): the code's log10 range, Include sea and the price factor. */
type Dec = { lo: number; hi: number; sea: boolean; price: number };
type Span = { w: number; h: number; north: number; south: number };
/** A decoded surface: log10 GDP per km2 per pixel (NaN where undefined), its bytes (B: land fraction, A: land), the alpha from which
 * a pixel is shown (255: land only, 128: the sea too, with Include sea), its colour domain over the world and its geographic span. `ex`: the
 * same pixels holding the local excess (log10 of the value over that of the wider Gaussian surface `wide`), with its own (symmetric) domain. */
export type View = Grid & Span & { rgba: Uint8Array; dec: Dec; min: number; dom: [number, number]; ex?: View; mask?: Uint8Array; wide?: Surface };
/** `mask`: 1 per pixel inside the focus; what is outside is not shown, painted, counted in a domain or read. */
const shown = (v: Pick<View, "rgba" | "min" | "mask">, i: number) => v.rgba[4 * i + 3] >= v.min && (!v.mask || v.mask[i] === 1);

export const DEM_M = 1e5; // metres per decade of relief height in the terrain tiles
const merc = (lat: number) => Math.asinh(Math.tan((lat * Math.PI) / 180));
const mercSpan = (g: Span) => merc(g.north) - merc(g.south);

/** lng/lat -> pixel (fractional) of a surface; rows are linear in Mercator y. */
export const toPixel = (g: Span, lng: number, lat: number): [number, number] =>
  [((lng + 180) / 360) * g.w, ((merc(g.north) - merc(lat)) / mercSpan(g)) * g.h];

export const toLngLat = (g: Span, x: number, y: number): [number, number] =>
  [(x / g.w) * 360 - 180, (Math.atan(Math.sinh(merc(g.north) - (y / g.h) * mercSpan(g))) * 180) / Math.PI];

/** log10 of the land fraction (byte B): 0 inland, -1 and below at coasts and islands; minus it, a value decoded with Include sea is land-only. */
const landLog10 = (b: number) => Math.log10(Math.max(b, 0.5) / 255);

/** RGBA -> log10 values, NaN where undefined (A = 0). `sea`: add log10 of the land fraction (B); `price`: constant-dollar factor. */
export function decode(px: ArrayLike<number>, m: Pick<Meta, "lo" | "hi">, sea = false, price = 1): Float32Array {
  const out = new Float32Array(px.length / 4), k = (m.hi - m.lo) / 65535, add = Math.log10(price);
  for (let i = 0; i < out.length; i++) {
    const p = 4 * i;
    out[i] = px[p + 3] ? m.lo + ((px[p] << 8) | px[p + 1]) * k + add + (sea ? landLog10(px[p + 2]) : 0) : NaN;
  }
  return out;
}

/** Linear value under a point, undefined outside the surface or where nothing is shown. */
export function valueAt(v: View, lng: number, lat: number): number | undefined {
  const [x, y] = toPixel(v, lng, lat), x0 = Math.floor(x), y0 = Math.floor(y), i = y0 * v.w + x0;
  return x0 < 0 || x0 >= v.w || y0 < 0 || y0 >= v.h || !shown(v, i) ? undefined : 10 ** v.vals[i];
}

/** Land-only value under a point of a surface decoded with Include sea (undefined without it, or on a pixel without land). */
export function landAt(v: View, lng: number, lat: number): number | undefined {
  const [x, y] = toPixel(v, lng, lat), i = Math.floor(y) * v.w + Math.floor(x);
  return v.min === 255 || valueAt(v, lng, lat) === undefined || v.rgba[4 * i + 3] !== 255 ? undefined : 10 ** (v.vals[i] - landLog10(v.rgba[4 * i + 2]));
}

/** Is a point inside the focus mask of the surface? (Without a mask: anywhere on it.) */
export function inside(v: Pick<View, "w" | "h" | "north" | "south" | "mask">, lng: number, lat: number): boolean {
  const [x, y] = toPixel(v, lng, lat), x0 = Math.floor(x), y0 = Math.floor(y);
  return x0 >= 0 && x0 < v.w && y0 >= 0 && y0 < v.h && (!v.mask || v.mask[y0 * v.w + x0] === 1);
}

/** Mask of the pixels whose centre lies in the box (w, s, e, n in degrees). */
export function boxMask(g: Span, [w, s, e, n]: number[]): Uint8Array {
  const m = new Uint8Array(g.w * g.h), [x0, y0] = toPixel(g, w, n), [x1, y1] = toPixel(g, e, s);
  for (let y = Math.max(0, Math.ceil(y0 - 0.5)); y < Math.min(g.h, y1 - 0.5); y++) for (let x = Math.max(0, Math.ceil(x0 - 0.5)); x < Math.min(g.w, x1 - 0.5); x++) m[y * g.w + x] = 1;
  return m;
}

/** Mask of the pixels inside polygons given as rings of the unit square of the world tile (x east, y south; holes by even-odd), drawn on
 * a canvas of the size of the grid. */
export function ringMask(g: Span, polys: [number, number][][][]): Uint8Array {
  const c = document.createElement("canvas"), ctx = c.getContext("2d", { willReadFrequently: true })!;
  [c.width, c.height] = [g.w, g.h];
  ctx.fillStyle = "#000";
  for (const rs of polys) {
    ctx.beginPath();
    for (const ring of rs) ring.forEach(([u, v], i) => ctx[i ? "lineTo" : "moveTo"](u * g.w, ((merc(g.north) - Math.PI * (1 - 2 * v)) / mercSpan(g)) * g.h));
    ctx.fill("evenodd");
  }
  const a = ctx.getImageData(0, 0, g.w, g.h).data, m = new Uint8Array(g.w * g.h);
  for (let i = 0; i < m.length; i++) m[i] = a[4 * i + 3] > 127 ? 1 : 0;
  return m;
}

/** The surface (and its local excess) restricted to a mask, with the colour domain of the pixels inside. */
export function masked(v: View, mask: Uint8Array): View {
  const cut = (g: View): View => ({ ...g, mask, dom: [0, 1] }), m = cut(v), x = v.ex && cut(v.ex);
  return { ...m, dom: domainOf(m), ...(x && { ex: { ...x, dom: excessDomain(x) } }) };
}

/** Bilinear value at pixel coordinates (pixel centres at .5) over the defined neighbours; NaN where they hold less than half the weight. */
export function sample(g: Grid, x: number, y: number): number {
  const fx = Math.min(g.w - 1, Math.max(0, x - 0.5)), fy = Math.min(g.h - 1, Math.max(0, y - 0.5)), x0 = Math.floor(fx), y0 = Math.floor(fy);
  const x1 = Math.min(x0 + 1, g.w - 1), y1 = Math.min(y0 + 1, g.h - 1), ax = fx - x0, ay = fy - y0;
  const a = g.vals[y0 * g.w + x0], b = g.vals[y0 * g.w + x1], c = g.vals[y1 * g.w + x0], d = g.vals[y1 * g.w + x1];
  const wa = a === a ? (1 - ax) * (1 - ay) : 0, wb = b === b ? ax * (1 - ay) : 0, wc = c === c ? (1 - ax) * ay : 0, wd = d === d ? ax * ay : 0, n = wa + wb + wc + wd;
  return n < 0.5 ? NaN : ((wa && wa * a) + (wb && wb * b) + (wc && wc * c) + (wd && wd * d)) / n;
}

/** 1st and 99th percentile of the pixels shown that contain land (B > 0: the very low values of sea-only pixels never count), or of the
 * pixel box [x0, y0, x1, y1], from a regular sample; null if there are none. With `land` (a density surface) only land pixels (A = 255)
 * count, at their land-only value, so Include sea never moves the scale. */
export function spread(g: Omit<View, "dom">, box = [0, 0, g.w, g.h], land = false): [number, number] | null {
  const [x0, y0, x1, y1] = [Math.max(0, Math.floor(box[0])), Math.max(0, Math.floor(box[1])), Math.min(g.w, box[2]), Math.min(g.h, box[3])];
  const step = Math.max(1, Math.round(Math.sqrt(((x1 - x0) * (y1 - y0)) / 4e5))), s = new Float32Array(Math.ceil((x1 - x0) / step) * Math.ceil((y1 - y0) / step));
  let n = 0;
  for (let y = y0; y < y1; y += step) for (let x = x0; x < x1; x += step) {
    const i = y * g.w + x, p = 4 * i;
    if (shown(g, i) && g.rgba[p + 2] && g.vals[i] === g.vals[i] && (!land || g.rgba[p + 3] === 255)) s[n++] = land && g.min < 255 ? g.vals[i] - landLog10(g.rgba[p + 2]) : g.vals[i];
  }
  const t = s.subarray(0, n).sort(); // typed: a numeric sort without a comparator
  return n ? [t[Math.floor(0.01 * (n - 1))], t[Math.floor(0.99 * (n - 1))]] : null;
}

/** Colour domain (log10): whole decades around the 1st to 99th percentile of the surface; with `box` (pixels) those percentiles of the
 * box themselves, at least half a decade apart, so the scale fits the part of the map in view. */
export function domainOf(g: Omit<View, "dom">, box?: number[]): [number, number] {
  const fit = box && spread(g, box, true), [a, b] = fit || spread(g, undefined, true) || [0, 1];
  return fit ? [a, Math.max(b, a + 0.5)] : [Math.floor(a), Math.max(Math.ceil(b), Math.floor(a) + 1)];
}

/** Colour domain of the local excess (log10 of a ratio): symmetric about 1x, out to the larger of the 1st and 99th percentile, rounded
 * up to half decades over the world, as is (at least a quarter decade) with `box`. */
export function excessDomain(g: Omit<View, "dom">, box?: number[]): [number, number] {
  const fit = box && spread(g, box), [a, b] = fit || spread(g) || [0, 0], d = Math.max(-a, b);
  const m = fit ? Math.max(d, 0.25) : Math.max(Math.ceil(2 * d) / 2, 0.5);
  return [-m, m];
}

/** log10 of each pixel of `v` minus the bilinear value of the wider surface `c` (same span, any size) at its centre: how many times
 * its surroundings a place is. NaN where either is undefined. */
export function excess(v: Grid, c: Grid): Float32Array {
  const out = new Float32Array(v.w * v.h), kx = c.w / v.w, ky = c.h / v.h;
  for (let y = 0, i = 0; y < v.h; y++) for (let x = 0; x < v.w; x++, i++) out[i] = v.vals[i] - sample(c, (x + 0.5) * kx, (y + 0.5) * ky);
  return out;
}

/** Relief heights in decades above `lo` (0 at and below it) of the pixels shown, NaN elsewhere, per level: 0 is the surface (read from it),
 * each next one half the size for the lower zooms (2x2 means, kept where at least two of the four are shown), built when first asked. */
export function levels(v: View, lo: number) {
  const built: Float32Array[] = [];
  const level = (l: number): { w: number; h: number; at: (i: number) => number } => {
    const w = v.w >> l, h = v.h >> l;
    if (!l) return { w, h, at: (i) => (shown(v, i) ? Math.max(0, v.vals[i] - lo) : NaN) };
    if (!built[l]) {
      const a = level(l - 1), b = (built[l] = new Float32Array(w * h));
      for (let y = 0, i = 0; y < h; y++) for (let x = 0; x < w; x++, i++) {
        const k = 2 * (y * a.w + x);
        let s = 0, n = 0;
        for (let j = 0; j < 4; j++) { const z = a.at(k + (j & 1) + (j >> 1) * a.w); if (z === z) { s += z; n++; } }
        b[i] = n >= 2 ? s / n : NaN;
      }
    }
    const b = built[l];
    return { w, h, at: (i) => b[i] };
  };
  return level;
}
const SLOPE = 0.1; // decades per DEM pixel of the apron around the land
/** Neighbours already passed in a forward scan (row by row, left to right), out to knight's moves, so the cone is a 16-gon. */
const BEHIND = [[-1, 0], [-1, -1], [0, -1], [1, -1], [-1, -2], [1, -2], [-2, -1], [2, -1]].map(([dx, dy]) => [dx, dy, SLOPE * Math.hypot(dx, dy)]);

/** NaN pixels -> the highest of (a pixel - SLOPE x distance) over paths through NaN pixels, 0 at the least: the land seen from the
 * sea, dilated by a cone, in two chamfer passes (forward, then backward with the neighbours mirrored). The land stays as it is. */
export function apron(g: Grid): Grid {
  const { w, h } = g, a = g.vals.map((x) => (x === x ? x : 0)), n = BEHIND.length;
  for (const s of [1, -1]) {
    const off = BEHIND.map(([dx, dy]) => s * (dy * w + dx)), d = BEHIND.map((b) => b[2]);
    for (let y = s > 0 ? 0 : h - 1; y >= 0 && y < h; y += s) for (let x = s > 0 ? 0 : w - 1; x >= 0 && x < w; x += s) {
      const i = y * w + x;
      if (g.vals[i] === g.vals[i]) continue;
      let m = a[i];
      if (x > 1 && x < w - 2 && y > 1 && y < h - 2) for (let k = 0; k < n; k++) { const c = a[i + off[k]] - d[k]; if (c > m) m = c; } // a plain loop: 9 M pixels
      else for (const [dx, dy, dk] of BEHIND) {
        const u = x + s * dx, v = y + s * dy;
        if (u >= 0 && u < w && v >= 0 && v < h) m = Math.max(m, a[v * w + u] - dk);
      }
      a[i] = m;
    }
  }
  return { w, h, vals: a };
}

/** The 256 px raster-dem tiles z/x/y of the relief over the latitudes of `v` (metres = 65536 R + 256 G + B, DEM_M per decade), made when
 * asked from level n - z (n: the level of 256 columns). On every level a pixel not shown gets an apron (`apron`), so land rises out of the
 * sea at the same steepness at every zoom and an island is a cone; it is computed on a window of the level around the tile, `margin`
 * pixels wider on every side: by default all a cone can reach (the highest height over SLOPE, plus a knight's move), where it equals the
 * apron of the whole level. The last 64 tiles are kept: the terrain and the shading each ask for every one. */
export function demTiles(v: View, lo: number, margin = Math.ceil((v.dec.hi + Math.max(0, Math.log10(v.dec.price)) - lo) / SLOPE) + 2) {
  const level = levels(v, lo), n = Math.round(Math.log2(v.w / 256)), tiles = new Map<string, Uint8ClampedArray>();
  const top = 0.5 - merc(v.north) / (2 * Math.PI), k = (2 * Math.PI) / mercSpan(v); // rows are linear in Mercator y
  return (z: number, x: number, y: number): Uint8ClampedArray => {
    const key = `${z}/${x}/${y}`, hit = tiles.get(key);
    if (hit) return hit;
    if (tiles.size >= 64) tiles.clear();
    const l = level(Math.max(0, n - z)), X = (i: number) => ((x + i / 256) / 2 ** z) * l.w, V = (j: number) => ((y + j / 256) / 2 ** z - top) * k;
    const x0 = Math.max(0, Math.floor(X(0)) - margin), y0 = Math.max(0, Math.floor(V(0) * l.h) - margin);
    const w = Math.max(0, Math.min(l.w, Math.ceil(X(256)) + margin) - x0), h = Math.max(0, Math.min(l.h, Math.ceil(V(256) * l.h) + margin) - y0);
    const win = apron({ w, h, vals: Float32Array.from({ length: w * h }, (_, i) => l.at((y0 + Math.floor(i / w)) * l.w + x0 + (i % w))) });
    const px = new Uint8ClampedArray(4 * 256 * 256);
    for (let j = 0, p = 0; j < 256; j++) for (let i = 0; i < 256; i++, p += 4) {
      const r = V(j + 0.5), m = r < 0 || r > 1 ? 0 : Math.round(sample(win, X(i + 0.5) - x0, r * l.h - y0) * DEM_M);
      px[p] = m >> 16; px[p + 1] = (m >> 8) & 255; px[p + 2] = m & 255; px[p + 3] = 255;
    }
    tiles.set(key, px);
    return px;
  };
}

/** The exact RGBA bytes of a lossless surface WebP as `smooth.py` writes it (`exact`: also under A = 0). A canvas would premultiply the
 * alpha, which loses bits of the code where A = 128, so the bitmap goes through a WebGL texture unpremultiplied and is read back. */
export async function unpack(webp: Blob): Promise<Surface> {
  const bm = await createImageBitmap(webp, { premultiplyAlpha: "none", colorSpaceConversion: "none" }), { width: w, height: h } = bm;
  const gl = document.createElement("canvas").getContext("webgl2")!, t = gl.createTexture(), rgba = new Uint8Array(4 * w * h);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
  gl.bindTexture(gl.TEXTURE_2D, t);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, bm);
  gl.bindFramebuffer(gl.FRAMEBUFFER, gl.createFramebuffer());
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
  gl.getExtension("WEBGL_lose_context")?.loseContext();
  bm.close();
  return { w, h, rgba };
}

const fetchSurface = async (id: string) => unpack(await (await fetch(new URL(`smooth/${id}.webp`, location.href))).blob());

/** Loads a surface when first needed and keeps only the current one (and its last decoding); with `wide` (km) also the Gaussian
 * surface of that radius (one kept), decoded alike, as the surroundings of the local excess. `ind` is an indicator of `SMOOTH`. */
export function smoother(m: Meta, load: (id: string) => Promise<Surface> = fetchSurface) {
  let cur: { id: string; s: Surface } | undefined, around: typeof cur, last: { key: string; v: View } | undefined;
  return async (ind: string, kernel: string, radius: number, sea: boolean, price: number, wide = 0): Promise<View> => {
    const { prefix, lo, hi } = m.indicators[SMOOTH[ind].src], d = { lo, hi };
    const id = `${prefix}${kernel}_${radius}`, wid = `${prefix}gauss_${wide}`;
    let [c, a] = [cur, around];
    if (c?.id !== id) cur = undefined; // the old bytes can go while the new ones load
    const [s, sa] = await Promise.all([c?.id === id ? c.s : load(id), wide < 1 || a?.id === wid ? a?.s : load(wid)]);
    if (c?.id !== id) cur = c = { id, s };
    if (wide > 0 && a?.id !== wid) around = a = { id: wid, s: sa! };
    const key = `${id}|${sea}|${price}|${wide}`;
    if (last?.key !== key) {
      const g = { w: s.w, h: s.h, vals: decode(s.rgba, d, sea, price), rgba: s.rgba, dec: { ...d, sea, price }, min: sea ? 128 : 255, north: m.north, south: m.south };
      const x = a && wide ? { ...g, vals: excess(g, { w: a.s.w, h: a.s.h, vals: decode(a.s.rgba, d, sea, price) }), wide: a.s } : null;
      last = { key, v: { ...g, dom: domainOf(g), ...(x && { ex: { ...x, dom: excessDomain(x) } }) } };
    }
    return last.v;
  };
}
