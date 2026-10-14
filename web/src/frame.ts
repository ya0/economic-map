import type { Map as MlMap } from "maplibre-gl";
import type { Bounds } from "./data/places";
import { $ } from "./ui/ui";

/** The frame in px, `[left, top, right, bottom]`, in the map's coordinates. */
export type Box = [number, number, number, number];
export const MIN = 48;
const DIR: Record<string, [number, number]> = { nw: [-1, -1], n: [0, -1], ne: [1, -1], e: [1, 0], se: [1, 1], s: [0, 1], sw: [-1, 1], w: [-1, 0] };
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

/** The part of the map left free by the cards (the camera fits to it, a new frame is centred in it). */
export const margins = (width: number) => width > 640 ? { top: 40, bottom: 40, left: 360, right: width > 1100 ? 400 : 40 } : { top: 130, bottom: 280, left: 20, right: 20 };

/** The frame after handle `h` is dragged to `(x, y)` in a `W x H` map: at least `MIN`, inside the map, the opposite edge (corner, or
 * centre line for an edge handle) fixed, `ratio` (width / height) kept if given. */
export function resize([l, t, r, b]: Box, h: string, x: number, y: number, [W, H]: [number, number], ratio?: number): Box {
  const [dx, dy] = DIR[h];
  const room = (lo: number, hi: number, d: number, max: number) => d > 0 ? max - lo : d < 0 ? hi : 2 * Math.min((lo + hi) / 2, max - (lo + hi) / 2);
  const size = (lo: number, hi: number, d: number, p: number, max: number) => d ? clamp(d > 0 ? p - lo : hi - p, MIN, room(lo, hi, d, max)) : hi - lo;
  let w = size(l, r, dx, x, W), v = size(t, b, dy, y, H);
  if (ratio) {
    if (dx) v = w / ratio; else w = v * ratio;
    const k = Math.min(Math.max(1, MIN / Math.min(w, v)), room(l, r, dx, W) / w, room(t, b, dy, H) / v);
    w *= k; v *= k;
  }
  const at = (lo: number, hi: number, d: number, n: number) => d > 0 ? [lo, lo + n] : d < 0 ? [hi - n, hi] : [(lo + hi) / 2 - n / 2, (lo + hi) / 2 + n / 2];
  const [x0, x1] = at(l, r, dx, w), [y0, y1] = at(t, b, dy, v);
  return [x0, y0, x1, y1];
}

/** Geographic bounds of the frame's north-west and south-east corners (lng, lat): within the Mercator world, three decimals. */
export function toBounds([w, n]: [number, number], [e, s]: [number, number]): Bounds {
  const q = (v: number) => +v.toFixed(3);
  return [q(Math.max(-180, w)), q(Math.max(-85, s)), q(Math.min(180, e)), q(Math.min(85, n))];
}

/** Width at the centre latitude and height of a box in km (spherical Earth), to 10 km. */
export function sizeKm([w, s, e, n]: Bounds): [number, number] {
  const deg = Math.PI / 180, R = 6371, km = (v: number) => Math.round(v / 10) * 10;
  return [km(R * Math.cos(((s + n) / 2) * deg) * (e - w) * deg), km(R * (n - s) * deg)];
}

/** The frame editor (viewfinder) over the map for the Focus area and the export: eight handles (44 px hit areas, Pointer Events), a bar
 * with the aspect switch, Apply and Cancel, a readout of the size and the regions it meets. `done` receives the bounds on Apply. */
export function createFrame(map: MlMap, hooks: { done: (b: Bounds, exporting: boolean) => void; count: (b: Bounds) => Promise<number>; fit: (b: Bounds) => Promise<void> }) {
  const el = $("frame"), bar = $("fbar"), asp = $<HTMLSelectElement>("fasp"), ok = $("fok"), ro = $("fro");
  let box: Box = [0, 0, 0, 0], exporting = false, regions = "", drag: { h: string; from: Box } | null = null, timer = 0;
  const size = (): [number, number] => [map.getContainer().clientWidth, map.getContainer().clientHeight];
  const ratio = () => asp.value === "v" ? size()[0] / size()[1] : +asp.value || undefined;
  const bounds = () => toBounds(map.unproject([box[0], box[1]]).toArray(), map.unproject([box[2], box[3]]).toArray());
  const draw = () => {
    Object.assign(el.style, { left: box[0] + "px", top: box[1] + "px", width: box[2] - box[0] + "px", height: box[3] - box[1] + "px" });
    ro.innerHTML = `${sizeKm(bounds()).map((v) => v.toLocaleString("en")).join(" × ")} km<br>${regions}`;
  };
  /** The region count lags behind the frame: it is read 150 ms after the last move of the frame or the map. */
  const refresh = () => {
    clearTimeout(timer);
    timer = window.setTimeout(async () => { if (el.hidden) return; const n = await hooks.count(bounds()); regions = `${n.toLocaleString("en")} region${n === 1 ? "" : "s"}`; draw(); }, 150);
  };
  const close = () => { el.hidden = bar.hidden = true; removeEventListener("keydown", key, true); map.off("moveend", refresh); };
  const apply = () => { const b = bounds(); close(); hooks.done(b, exporting); };
  function key(e: KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "Enter" && !(e.target as HTMLElement).closest("button, select, input, dialog")) { e.preventDefault(); apply(); }
  }
  for (const h of Object.keys(DIR)) el.insertAdjacentHTML("beforeend", `<i class="h" data-h="${h}"></i>`);
  el.onpointerdown = (e) => { const h = (e.target as HTMLElement).dataset.h; if (h) { (e.target as HTMLElement).setPointerCapture(e.pointerId); drag = { h, from: box }; } };
  el.onpointermove = (e) => { if (drag) { box = resize(drag.from, drag.h, e.clientX, e.clientY, size(), ratio()); draw(); } };
  el.onpointerup = el.onpointercancel = () => { drag = null; refresh(); };
  asp.onchange = () => { box = resize(box, "se", box[2], box[3], size(), ratio()); draw(); refresh(); };
  ok.onclick = apply;
  $("fcancel").onclick = close;

  /** Show the frame (a second call only relabels it): on `at`, else centred at 60% of the free map area. */
  async function open(forExport: boolean, at?: Bounds) {
    [exporting, ok.textContent] = [forExport, forExport ? "Export" : "Apply"];
    if (!el.hidden) return;
    const [W, H] = size(), m = margins(W);
    if (at) {
      let [a, c] = [map.project([at[0], at[3]]), map.project([at[2], at[1]])];
      if (a.x < 0 || a.y < 0 || c.x > W || c.y > H) { await hooks.fit(at); [a, c] = [map.project([at[0], at[3]]), map.project([at[2], at[1]])]; }
      box = resize([a.x, a.y, c.x, c.y], "se", c.x, c.y, [W, H]);
    } else {
      const [fw, fh] = [W - m.left - m.right, H - m.top - m.bottom];
      box = [m.left + fw * 0.2, m.top + fh * 0.2, m.left + fw * 0.8, m.top + fh * 0.8];
    }
    regions = "";
    el.hidden = bar.hidden = false;
    addEventListener("keydown", key, true);
    map.on("moveend", refresh);
    draw();
    refresh();
  }
  return { open, close, isOpen: () => !el.hidden };
}
