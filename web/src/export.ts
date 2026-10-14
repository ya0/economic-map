import type { Map as MlMap } from "maplibre-gl";
import { LEVELS, basisLabel } from "./data/data";
import { type legendModel, thinTicks } from "./ui/ui";

export type Rect = { x: number; y: number; w: number; h: number };
type Paint = { bg: string; ink: string; mute: string; line: string; noData: string; disputed: string };
type Sheet = { title: string; sub: string; legend: ReturnType<typeof legendModel>; credits: string; bearing: number };

/** The north arrow (36 x 36 box), shared by the page's button and the export: north half, south half, and the "N" at (18, 11). */
export const COMPASS = ["M18 14l4 9h-8z", "M18 32l-4-9h8z"];
export const NORTH = "#d33", turned = (bearing: number) => Math.abs(bearing) >= 0.5;

/** Pixel ratio of the image: the crop reaches at least 1920 px on its long and 1080 px on its short edge, and never less than 2x; `maximum`
 * takes the cap instead. The cap keeps the whole map canvas (`w` x `h` css px) within `limit` px a side (8192 or the GPU's texture size)
 * and `budget` pixels. */
export const exportRatio = (crop: Pick<Rect, "w" | "h">, w: number, h: number, limit: number, budget: number, maximum = false) =>
  Math.min(Math.min(limit / Math.max(w, h), Math.sqrt(budget / (w * h))), maximum ? Infinity : Math.max(2, 1920 / Math.max(crop.w, crop.h), 1080 / Math.min(crop.w, crop.h)));

/** Screen rectangle (css px) from two opposite corners, grown by `margin` of its size on every side and clamped to the `w` x `h` map;
 * null if nothing of it is on the map. */
export function cropRect([x0, y0, x1, y1]: [number, number, number, number], margin: number, w: number, h: number): Rect | null {
  const dx = Math.abs(x1 - x0) * margin, dy = Math.abs(y1 - y0) * margin;
  const l = Math.max(0, Math.floor(Math.min(x0, x1) - dx)), t = Math.max(0, Math.floor(Math.min(y0, y1) - dy));
  const r = Math.min(w, Math.ceil(Math.max(x0, x1) + dx)), b = Math.min(h, Math.ceil(Math.max(y0, y1) + dy));
  return r - l >= 1 && b - t >= 1 ? { x: l, y: t, w: r - l, h: b - t } : null;
}

const slug = (s: string) => s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^\w]+/g, "-").replace(/^-|-$/g, "").toLowerCase() || "x";

/** The focus as named in the header and the file name: the first three names, then "and N more" ("World" without one). */
const named = (focus: string[]) => (focus.length > 3 ? `${focus.slice(0, 3).join(", ")} and ${focus.length - 3} more` : focus.join(", ") || "World");

/** `gdp-density_<focus-or-world>_<indicator>_<year>.png`; `focus`: names, empty for the world. */
export const fileName = (focus: string[], indicator: string, year: number) => `gdp-density_${slug(named(focus))}_${slug(indicator)}_${year}.png`;

/** Second line of the header: the focus, the level (not for the smoothed view), the price basis, the data year. */
export const subtitle = (o: { focus: string[]; area: boolean; level: number | null; money: boolean; base: number | null; year: number }) =>
  [o.area ? "Selected area" : named(o.focus), o.level != null && `${LEVELS[o.level]} level`, o.money && basisLabel(o.base), `data ${o.year}`].filter(Boolean).join(" · ");

const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

/** Resolve once the map is rendered and idle (the camera, tiles and canvases are settled). */
export const idle = (map: MlMap) => new Promise<void>((res) => { const t = setTimeout(res, 90_000); map.once("idle", () => { clearTimeout(t); res(); }); map.triggerRepaint(); });

/** The GL canvas at pixel ratio `r`, cropped to `rect` (css px). The drawing buffer is only valid inside a `render` event, so it is
 * copied there; the ratio is restored afterwards. The UI is DOM and not in it. */
export async function capture(map: MlMap, r: number, rect: Rect): Promise<HTMLCanvasElement> {
  const old = map.getPixelRatio();
  map.setPixelRatio(r);
  try {
    await idle(map);
    return await new Promise((res, rej) => {
      map.once("render", () => {
        try {
          const src = map.getCanvas(), k = src.width / map.getContainer().clientWidth, out = document.createElement("canvas");
          [out.width, out.height] = [Math.round(rect.w * r), Math.round(rect.h * r)];
          out.getContext("2d")!.drawImage(src, Math.round(rect.x * k), Math.round(rect.y * k), Math.round(rect.w * k), Math.round(rect.h * k), 0, 0, out.width, out.height);
          res(out);
        } catch (e) { rej(e); }
      });
      map.triggerRepaint();
    });
  } finally { map.setPixelRatio(old); }
}

function wrap(ctx: CanvasRenderingContext2D, text: string, max: number): string[] {
  const lines: string[] = [];
  let cur = "";
  for (const word of text.split(" ")) {
    const next = cur ? cur + " " + word : word;
    if (cur && ctx.measureText(next).width > max) { lines.push(cur); cur = word; } else cur = next;
  }
  return [...lines, cur];
}

/** The map crop under a header (title, subtitle) and over a footer (legend from `legendModel`, credits line), in the page's colours.
 * Sizes scale with the ratio `r`; the image is as wide as the crop. */
export function compose(crop: HTMLCanvasElement, r: number, s: Sheet, p: Paint): HTMLCanvasElement {
  const W = crop.width, u = r, pad = 12 * u, inner = W - 2 * pad, out = document.createElement("canvas"), ctx = out.getContext("2d")!;
  const font = (size: number, bold = false) => { ctx.font = `${bold ? 600 : 400} ${size * u}px ${FONT}`; };
  const lh = (size: number) => Math.round(size * 1.35 * u);
  font(15, true);
  const title = wrap(ctx, s.title, inner);
  font(12);
  const sub = wrap(ctx, s.sub, inner), unit = wrap(ctx, s.legend.unit, inner);
  font(11);
  const credits = wrap(ctx, s.credits, inner);
  const head = pad + title.length * lh(15) + sub.length * lh(12) + pad * 0.7;

  const cols = inner > 300 * u ? 2 : 1, colW = inner / cols, cl = s.legend.classes;
  const scale = cl ? Math.ceil(cl.length / cols) * lh(12) : 14 * u + lh(11);
  const keys = lh(12);
  const foot = pad * 0.7 + unit.length * lh(12) + 4 * u + scale + keys + 4 * u + credits.length * lh(11) + pad;
  [out.width, out.height] = [W, Math.round(head + crop.height + foot)];

  ctx.fillStyle = p.bg;
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.textBaseline = "top";
  let y = pad;
  const text = (lines: string[], size: number, color: string, bold = false, x = pad) => {
    font(size, bold);
    ctx.fillStyle = color;
    for (const l of lines) { ctx.fillText(l, x, y + (lh(size) - size * u) / 2); y += lh(size); }
  };
  text(title, 15, p.ink, true);
  text(sub, 12, p.mute);
  y = head;
  ctx.drawImage(crop, 0, y);
  if (turned(s.bearing)) { // the north arrow in the crop's top right corner, as on the page
    ctx.save();
    ctx.translate(W - 26 * u, y + 26 * u);
    ctx.scale(u, u);
    ctx.beginPath();
    ctx.arc(0, 0, 18, 0, 2 * Math.PI);
    ctx.fillStyle = p.bg;
    ctx.fill();
    ctx.strokeStyle = p.line;
    ctx.stroke();
    ctx.rotate((-s.bearing * Math.PI) / 180);
    ctx.translate(-18, -18);
    ctx.fillStyle = NORTH;
    ctx.fill(new Path2D(COMPASS[0]));
    ctx.fillStyle = p.ink;
    ctx.fill(new Path2D(COMPASS[1]));
    ctx.font = `600 9px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("N", 18, 10);
    ctx.restore();
  }
  ctx.fillStyle = p.line;
  ctx.fillRect(0, y - 1, W, 1);
  y += crop.height + pad * 0.7;
  text(unit, 12, p.mute);
  y += 4 * u;
  const swatch = (x: number, top: number, row: number, colour: string) => { ctx.fillStyle = colour; ctx.fillRect(x, top + (row - 10 * u) / 2, 14 * u, 10 * u); };
  const word = (t: string, x: number, top: number, row: number, colour: string) => { ctx.fillStyle = colour; ctx.fillText(t, x, top + (row - 12 * u) / 2); };
  if (cl) {
    font(12);
    cl.forEach(([c, t], i) => {
      const x = pad + (i % cols) * colW, yy = y + Math.floor(i / cols) * lh(12);
      swatch(x, yy, lh(12), c);
      word(t, x + 20 * u, yy, lh(12), p.ink);
    });
  } else {
    const g = ctx.createLinearGradient(pad, 0, pad + inner, 0);
    for (const [x, c] of s.legend.grad) g.addColorStop(x, c);
    ctx.fillStyle = g;
    ctx.fillRect(pad, y, inner, 10 * u);
    font(11);
    ctx.fillStyle = p.mute;
    for (const [, t, left] of thinTicks(s.legend.ticks, inner / u, (t) => ctx.measureText(t).width / u)) ctx.fillText(t, pad + left * u, y + 13 * u);
  }
  y += scale;
  font(12);
  let x = pad;
  for (const [t, c] of [["No data", p.noData], ["Disputed", p.disputed]]) {
    swatch(x, y, keys, c);
    word(t, x + 20 * u, y, keys, p.mute);
    x += 36 * u + ctx.measureText(t).width;
  }
  y += keys + 4 * u;
  text(credits, 11, p.mute);
  return out;
}
