import maplibregl, { type CanvasSource, type ExpressionSpecification, type GeoJSONSource, type LayerSpecification, type Map as MlMap, type RasterDEMSourceSpecification } from "maplibre-gl";
import { VectorTile } from "@mapbox/vector-tile";
import Pbf from "pbf";
import { PMTiles, Protocol } from "pmtiles";
import type { Row } from "../data/data";
import { type Bounds, bounds, inBox, mainlandBounds, meeting, ringBoxes, rings, union } from "../data/places";
import { margins } from "../frame";
import { DIVERGING, painter } from "../scales/scales";
import type { State } from "../state/state";
import { current, currentName } from "../theme";
import { gpuPainter } from "./gpu";
import { type View, DEM_M, demTiles, toLngLat } from "./smooth";

const HEIGHT_PER_DECADE = 1_000_000; // metres at zoom 0; halves with every zoom level so spikes keep their height on screen
const PITCH = 55;
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const ID: ExpressionSpecification = ["get", "region_id"];
const isDisputed: ExpressionSpecification = ["==", ["slice", ID, 0, 9], "DISPUTED:"];
const none: ExpressionSpecification = ["==", ID, ""];

/** The regions drawn when a focus is set: ids of the rows shown and of their countries (for the country borders). */
type Limit = { ids: string[]; countries: string[] };
/** Filter for the regions in a list (never an empty `match`, which MapLibre rejects). */
const among = (ids: string[]): ExpressionSpecification => (ids.length ? ["match", ID, ids, true, false] : none);

type Handlers = {
  hover: (id: string | null, x: number, y: number, at?: [number, number]) => void;
  pick: (id: string | null) => void;
  camera: (cam: [number, number, number]) => void;
};

/** Height from `decades` (an expression), halved with every zoom level. */
const height = (decades: ExpressionSpecification): ExpressionSpecification => ["interpolate", ["linear"], ["zoom"],
  ...Array.from({ length: 11 }, (_, z) => [z, ["*", decades, HEIGHT_PER_DECADE / 2 ** z]]).flat()] as ExpressionSpecification;
/** The data colour of a region comes from its feature-state (`painter`), so no change of palette, theme, classes or scale ever rewrites
 * a paint expression: that would re-lay out every tile. A region without state yet is transparent. */
const COLOUR: ExpressionSpecification = ["to-color", ["feature-state", "c"], "rgba(0,0,0,0)"];
/** Opacity of an outline that only the region flagged `k` (hover, sel) in its feature-state shows: a filter would re-lay out the tiles. */
const flagged = (k: string): ExpressionSpecification => ["case", ["to-boolean", ["feature-state", k]], 1, 0];
const TEXT = { "text-field": ["get", "name"] as ExpressionSpecification, "text-font": ["system-ui", "Segoe UI", "sans-serif"], "text-max-width": 7, "text-padding": 9 };
const halo = () => ({ "text-color": current().label, "text-halo-color": current().halo, "text-halo-width": 1.3 });
/** Shading of the smoothed terrain, so it reads as relief under flat colour classes too. MapLibre scales a slope by this gain per decade
 * per DEM pixel (`hillshade_prepare.fragment.glsl`); the exaggeration undoes it: a slope of s shades with strength atan(20 s) at every zoom. */
const shadeGain = (z: number) => (DEM_M * 256 * 2 ** (z + (15 - z) * (z < 2 ? 0.4 : z < 4.5 ? 0.35 : 0.3))) / 40075016;
const shade = (): LayerSpecification => ({ id: "shade", type: "hillshade", source: "shd", paint: {
  "hillshade-method": "igor", "hillshade-shadow-color": current().shadow, "hillshade-highlight-color": current().highlight,
  "hillshade-exaggeration": ["interpolate", ["linear"], ["zoom"], ...Array.from({ length: 11 }, (_, z) => [z, Math.min(1, 10 / shadeGain(z))]).flat()] as ExpressionSpecification } });
/** Names of the regions shown and of their countries (filter set per level): coarser levels first, then by GDP rank; colliding names
 * are hidden, and far out only the largest economies are named. */
const labelLayer = (): LayerSpecification => ({ id: "labels", type: "symbol", source: "regions", "source-layer": "labels", filter: none,
  layout: { ...TEXT, "text-size": ["match", ["get", "level_no"], 0, 16, 1, 13, 11.5], "symbol-sort-key": ["+", ["*", ["get", "level_no"], 1e5], ["get", "rank"]] }, paint: halo() });

/** The polygon layers of one level (tile layer `l<no>`), plus country borders (tile layer `l1`) on finer levels. Ids end in the
 * level ("fill3"): MapLibre queries tiles that are still indexed for the previous layers, so an id must not change its tile layer. */
function levelLayers(no: number, relief: boolean): LayerSpecification[] {
  const src = { source: "regions", "source-layer": `l${no}` };
  const layers: LayerSpecification[] = [
    // the focus outline: 4 px under the fills, so only the outer half shows (set per focus)
    { id: "edge", type: "line", ...src, filter: none, paint: { "line-color": current().edge, "line-width": 4 } },
    { id: "fill", type: "fill", ...src, paint: { "fill-color": COLOUR } },
    // region outlines: thin, and faded out by zoom on fine levels, where the regions are small on screen and the lines would hide the fill
    { id: "borders", type: "line", ...src,
      paint: { "line-color": current().border, "line-opacity": ["interpolate", ["linear"], ["zoom"], 0, no < 2 ? 0.3 : 0.02, 3 + no, 0.3], "line-width": ["interpolate", ["linear"], ["zoom"], 0, 0.3, 8, 0.9] } },
    ...(no > 1 ? [{ id: "country", type: "line", source: "regions", "source-layer": "l1" as const,
      paint: { "line-color": current().border, "line-opacity": 0.5, "line-width": ["interpolate", ["linear"], ["zoom"], 0, 0.5, 6, 1.5] } } as LayerSpecification] : []),
    { id: "relief", type: "fill-extrusion", ...src, layout: { visibility: relief ? "visible" : "none" },
      paint: { "fill-extrusion-color": COLOUR, "fill-extrusion-height": height(["coalesce", ["feature-state", "h"], 0]) } },
    { id: "disputed", type: "line", ...src, filter: isDisputed, paint: { "line-color": current().border, "line-opacity": 0.8, "line-dasharray": [2, 2] } },
    { id: "hover", type: "line", ...src, paint: { "line-color": current().hover, "line-width": 1.5, "line-opacity": flagged("hover") } },
    { id: "sel", type: "line", ...src, paint: { "line-color": current().select, "line-width": 2.5, "line-opacity": flagged("sel") } },
    // the focus box: paper over all but the box, above the outlines so they cannot overhang it, and its ring
    { id: "clip", type: "fill", source: "clip", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": current().paper, "fill-antialias": false } },
    { id: "ring", type: "line", source: "clip", filter: ["==", ["geometry-type"], "LineString"], paint: { "line-color": current().edge, "line-width": 2 } },
  ];
  return layers.map((l) => ({ ...l, id: l.id + no }));
}

export function createMap(el: HTMLElement, state: State, h: Handlers) {
  const protocol = new Protocol(), tiles = new PMTiles(new URL("regions.pmtiles", location.href).href);
  protocol.add(tiles);
  maplibregl.addProtocol("pmtiles", protocol.tile);
  const map: MlMap = new maplibregl.Map({
    container: el,
    attributionControl: false,
    dragRotate: state.relief,
    pitch: state.relief ? PITCH : 0,
    ...(state.cam ? { zoom: state.cam[0], center: [state.cam[2], state.cam[1]] as [number, number] } : { bounds: [[-180, -58], [180, 82]] as [[number, number], [number, number]] }),
    style: {
      version: 8,
      projection: { type: state.globe ? "globe" : "mercator" },
      sources: {
        regions: { type: "vector", url: "pmtiles://" + tiles.source.getKey(), promoteId: "region_id", maxzoom: 9 },
        clip: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": current().ocean } },
        labelLayer(),
      ],
    },
  });
  if (!state.cam && el.clientHeight > el.clientWidth) map.setCenter([20, 25]); // portrait: the world is cropped sideways, start on Europe/Africa/Asia
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  let relief = state.relief, globe = state.globe, focused = false, level = -1, limitKey = "", labels = none, smoothed = false, box: Bounds | null = null;
  /** On the globe only the names within 5000 km of the centre: nearer the edge of the disc they would hang over it. */
  const showLabels = () => {
    if (level < 0) return;
    map.setFilter("labels", globe ? ["all", labels, ["<", ["distance", { type: "Point", coordinates: map.getCenter().toArray() }], 5e6]] : labels);
  };
  /** Region under the pointer. Extrusion walls count in flat relief only (not in the smoothed view, where the region relief is hidden):
   * on the globe MapLibre finds nothing at all once a fill-extrusion layer is among the queried layers. */
  const out = (e: maplibregl.MapMouseEvent) => !!box && !inBox(box, e.lngLat.lng, e.lngLat.lat); // outside the focus box nothing is hovered or clicked
  const hit = (e: maplibregl.MapMouseEvent): string | null =>
    level < 0 || out(e) ? null : map.queryRenderedFeatures(e.point, { layers: relief && !globe && !smoothed ? ["relief" + level, "fill" + level] : ["fill" + level] })[0]?.properties.region_id ?? null;
  /** The one region per level flagged `k` in its feature-state (the `hover` and `sel` outlines show it). */
  const flags = { hover: [null, null, null, null] as (string | null)[], sel: [null, null, null, null] as (string | null)[] };
  const flag = (k: keyof typeof flags, no: number, id: string | null) => {
    const was = flags[k][no], of = (rid: string) => ({ source: "regions", sourceLayer: `l${no}`, id: rid });
    if (was === id) return;
    if (was) map.removeFeatureState(of(was), k);
    if (id) map.setFeatureState(of(id), { [k]: true });
    flags[k][no] = id;
  };
  const hover = (id: string | null, x = 0, y = 0, at?: [number, number]) => {
    if (level >= 0) flag("hover", level, id);
    map.getCanvas().style.cursor = id ? "pointer" : "";
    h.hover(id, x, y, at);
  };
  map.on("mousemove", (e) => hover(hit(e), e.point.x, e.point.y, [e.lngLat.lng, e.lngLat.lat]));
  map.on("mouseout", () => hover(null));
  map.on("click", (e) => h.pick(hit(e)));
  map.on("moveend", () => {
    const c = map.getCenter();
    h.camera([+map.getZoom().toFixed(2), +c.lat.toFixed(2), +c.lng.toFixed(2)]);
    showLabels();
  });

  const clipArea = (b: Bounds | null) => {
    const ring = b ? [[b[0], b[1]], [b[0], b[3]], [b[2], b[3]], [b[2], b[1]], [b[0], b[1]]] : [];
    return { type: "FeatureCollection" as const, features: b ? [
      { type: "Feature" as const, properties: {}, geometry: { type: "Polygon" as const, coordinates: [[[-180, -85.06], [180, -85.06], [180, 85.06], [-180, 85.06], [-180, -85.06]], ring] } },
      { type: "Feature" as const, properties: {}, geometry: { type: "LineString" as const, coordinates: ring } }] : [] };
  };

  /** The smoothed view: the surface coloured on its canvas by the GPU, and with Relief draped (as are all lines and names) over a terrain of its
   * heights (raster-dem tiles from the `sdem` protocol), shaded, with the sea veiled over the shading; each redone only when its inputs change. */
  let drawn: View | null = null, sig = "", dem: { v: View; lo: number; tile: ReturnType<typeof demTiles> } | null = null, version = 0, gpu: ReturnType<typeof gpuPainter> | undefined;
  const gl = () => (gpu ??= gpuPainter(document.getElementById("smc") as HTMLCanvasElement)); // made on first use: no shaders compiled for the regions view
  maplibregl.addProtocol("sdem", async (req) => {
    const [z, x, y] = req.url.split("/").slice(-3).map(Number);
    await new Promise((r) => setTimeout(r)); // MapLibre asks for up to 16 tiles at once: each is made in a task of its own
    const px = dem ? dem.tile(z, x, y) : new Uint8ClampedArray(4 * 256 * 256); // late requests of a removed terrain: flat
    return { data: await createImageBitmap(new ImageData(px as Uint8ClampedArray<ArrayBuffer>, 256)) };
  });
  /** The region relief rule: 1000 km per decade at zoom 0, halved with every zoom level. */
  const exaggeration = () => HEIGHT_PER_DECADE / DEM_M / 2 ** map.getZoom();
  map.on("zoom", () => {
    // setTerrain on every zoom event rebuilds the terrain and stutters; assigning the field, which MapLibre 5.24 reads at every frame,
    // follows the zoom at full frame rate. It is not a documented API: without it the height is set once the zoom ends.
    if (typeof map.terrain?.exaggeration === "number") { map.terrain.exaggeration = exaggeration(); map.triggerRepaint(); }
  });
  map.on("zoomend", () => { if (map.terrain && typeof map.terrain.exaggeration !== "number") map.setTerrain({ source: "dem", exaggeration: exaggeration() }); });
  /** Put a canvas source over the pixels (0, 0) to (w, h) of a surface and upload what is drawn on it. */
  function place(id: string, v: View, w: number, h: number) {
    const src = map.getSource(id) as CanvasSource;
    src.setCoordinates([toLngLat(v, 0, 0), toLngLat(v, w, 0), toLngLat(v, w, h), toLngLat(v, 0, h)]);
    src.play();
    src.pause();
    map.triggerRepaint();
  }
  /** Outside a region focus the sea is paper, not ocean; so is the veil over the smoothed relief. */
  const veilColour = () => (focused ? current().paper + "e6" : current().veil);
  function drawVeil(v: View) {
    const { w, h, k } = gl().veil(v, veilColour(), document.getElementById("smv") as HTMLCanvasElement);
    place("smv", v, w * k, h * k);
  }
  /** A new theme: every colour property of the layer specs (the colours come from `current()`), set again; tiles and DEM stay. Data
   * colours are set to no-data here and by `apply` right after. The surface repaints in `smooth()` (its key holds the theme). */
  let styled = currentName();
  function restyle() {
    if (styled === currentName()) return;
    styled = currentName();
    for (const l of [labelLayer(), ...levelLayers(level, relief), shade()]) if (map.getLayer(l.id))
      for (const [k, v] of Object.entries(l.paint ?? {})) if (k.endsWith("-color")) map.setPaintProperty(l.id, k, v);
    paperOrSea();
  }
  /** The colours that follow the focus and the theme: outside a region focus is paper (the sea inside a box stays sea). */
  function paperOrSea() {
    map.setPaintProperty("bg", "background-color", focused ? current().paper : current().ocean);
    if (dem) drawVeil(dem.v);
  }
  /** Colours: the surface, or its local excess (`ex`) in the diverging palette; the terrain is always the surface. */
  function smooth(s: State, v: View | null, dom: [number, number], n: number) {
    map.setLayoutProperty("smc", "visibility", v ? "visible" : "none");
    const pal = v?.ex ? DIVERGING : s.palette, key = JSON.stringify([pal, dom, n, currentName()]), lo = v && s.relief ? v.dom[0] : null; // the world's floor: a View scale recolours, the terrain stays
    if (v && (v !== drawn || key !== sig)) {
      [drawn, sig] = [v, key];
      gl().paint(v.ex ?? v, pal, dom, n, n && v.w <= 2048 ? 2 : 1, !v.ex);
      place("smc", v, v.w, v.h);
    }
    if (dem?.v === v && dem?.lo === lo) return;
    map.setTerrain(null);
    if (map.getLayer("shade")) map.removeLayer("shade");
    for (const id of ["dem", "shd"]) if (map.getSource(id)) map.removeSource(id);
    dem = v && lo !== null ? { v, lo, tile: demTiles(v, lo) } : null;
    map.setLayoutProperty("smv", "visibility", dem ? "visible" : "none");
    if (!dem) return;
    // terrain and shading read the same tiles from two sources, as MapLibre asks: the shading wants finer tiles than the terrain mesh
    const spec: RasterDEMSourceSpecification = { type: "raster-dem", tiles: [`sdem://${++version}/{z}/{x}/{y}`], tileSize: 256, maxzoom: Math.log2(v!.w / 256), encoding: "custom", redFactor: 65536, greenFactor: 256, blueFactor: 1, baseShift: 0 };
    map.addSource("dem", spec);
    map.addSource("shd", spec);
    map.addLayer(shade(), "smv"); // above the surface, below the sea veil and every line and name
    drawVeil(v!);
    map.setTerrain({ source: "dem", exaggeration: exaggeration() });
  }

  /** Show the level's layers and labels, and write the feature-state (value, colour, relief height) of the regions whose state changed;
   * paint expressions and tiles are never touched. `rows`: the regions shown (one cover); `brk`: class breaks (log10) or null for the gradient. */
  const written = [0, 1, 2, 3].map(() => new Map<string, string>()); // per level: the state last written for each region
  function apply(s: State, dom: [number, number], brk: number[] | null, rows: Row[], valueOf: (row: Row) => number | undefined, view: View | null, limit: Limit | null = null) {
    const no = s.level;
    if (level >= 0) restyle();
    if (no !== level) {
      if (level >= 0) for (const l of levelLayers(level, relief)) map.removeLayer(l.id);
      for (const l of levelLayers(no, relief)) map.addLayer(l, l.id === "edge" + no ? "smc" : "labels");
      limitKey = "";
      level = no;
    }
    if (JSON.stringify(s.box) !== JSON.stringify(box)) { // the focus box: one mask over the world with the box as a hole
      box = s.box;
      (map.getSource("clip") as GeoJSONSource).setData(clipArea(box));
    }
    if (limitKey !== no + JSON.stringify(limit)) { // the focus: what is outside it is not drawn, hovered or clicked
      limitKey = no + JSON.stringify(limit);
      const inside = limit && among(limit.ids);
      for (const id of ["fill", "borders", "relief"]) map.setFilter(id + no, inside);
      map.setFilter("edge" + no, s.focus.length ? inside : none);
      map.setFilter("disputed" + no, inside ? ["all", isDisputed, inside] : isDisputed);
      if (no > 1) map.setFilter("country" + no, limit && among(limit.countries));
      labels = ["all", ["<=", ["get", "rank"], ["step", ["zoom"], 40, 2, 80, 3, 160, 4, 1e6]],
        ["any", ["match", ID, rows.map((r) => r.id), true, false], ["all", no > 1, ["==", ["get", "level_no"], 1], limit ? among(limit.countries) : true]]];
    }
    smoothed = !!view;
    if (focused !== s.focus.length > 0) { focused = !focused; paperOrSea(); }
    el.classList.toggle("limb", s.globe && (focused || !!s.box)); // the sphere keeps a thin outline once its outside is paper
    map.setPaintProperty("fill" + no, "fill-opacity", view ? 0 : 1); // still clickable
    if (!view) { // under the surface the regions are not seen: their state waits until it goes
      const paint = painter(dom, brk, s.palette, current().noData), done = written[no];
      for (const row of rows) {
        const st = paint(valueOf(row));
        if (row.id.startsWith("DISPUTED:")) st.c = current().disputed;
        const key = `${st.c}|${st.h}|${st.v}`;
        if (done.get(row.id) !== key) { done.set(row.id, key); map.setFeatureState({ source: "regions", sourceLayer: `l${no}`, id: row.id }, st); }
      }
    }
    if (s.relief !== relief) {
      relief = s.relief;
      relief ? map.dragRotate.enable() : map.dragRotate.disable();
      map.easeTo({ pitch: relief ? PITCH : 0, bearing: relief ? map.getBearing() : 0, duration: reduced() ? 0 : 800 });
    }
    map.setLayoutProperty("relief" + no, "visibility", relief && !view ? "visible" : "none");
    map.setLayoutProperty("borders" + no, "visibility", s.borders && !(view && no > 1) ? "visible" : "none"); // on coarse levels the outlines are the country borders
    smooth(s, view, dom, brk ? brk.length + 1 : 0);
    flag("sel", no, s.sel);
    if (s.globe !== globe) map.setProjection({ type: (globe = s.globe) ? "globe" : "mercator" });
    showLabels();
  }

  const ready = new Promise<void>((res) => map.on("load", () => {
    // smoothed view: the canvases of index.html (the surface `smc`, the sea veil `smv`) painted and placed by `smooth()`, below the level layers, which are added later
    for (const id of ["smc", "smv"]) {
      map.addSource(id, { type: "canvas", canvas: id, animate: false, coordinates: [[-180, 80], [180, 80], [180, -60], [-180, -60]] });
      map.addLayer({ id, type: "raster", source: id, layout: { visibility: "none" }, paint: { "raster-resampling": "linear", "raster-fade-duration": 0 } }, "labels"); // linear: a smooth coast
    }
    res();
  }));
  let world: Promise<VectorTile> | undefined; // the z0 tile holds every region of every level
  const layers = async () => (await (world ??= tiles.getZxy(0, 0, 0).then((t) => new VectorTile(new Pbf(new Uint8Array(t!.data)))))).layers;
  /** Ids of the regions of every level that meet a box, and the rings of regions (id and level), for the focus mask. */
  const meet = async (b: Bounds) => { const l = await layers(); return new Set([0, 1, 2, 3].flatMap((no) => meeting(l[`l${no}`], b))); };
  const shapes = async (regions: [string, number][]) => { const l = await layers(); return regions.flatMap(([id, no]) => rings(l[`l${no}`], [id])); };
  /** Fit the camera to regions (id and the level whose tile layer holds it), leaving room for the side cards; `pad` is the share of
   * the box added on every side. */
  async function extent(regions: [string, number][], overseas = false): Promise<Bounds | null> {
    const l = await layers(), bs = regions.map(([id, no]) => {
      if (no !== 1) return bounds(l[`l${no}`], id);
      const all = ringBoxes(l.l1, id); // a country: its mainland, or every ring with the overseas parts
      return overseas ? (all.length ? union(all) : null) : mainlandBounds(all)?.bounds;
    }).filter((b) => b != null);
    return bs.length ? union(bs) : null;
  }
  async function fit(regions: [string, number][], pad = 0, overseas = false) {
    const b = await extent(regions, overseas);
    if (b) frame(b, pad);
  }
  /** Which of the countries (ids) have parts that the mainland view leaves out. */
  const overseasOf = async (ids: string[]) => { const l = await layers(); return ids.filter((id) => mainlandBounds(ringBoxes(l.l1, id))?.overseas); };
  function frame([w, s, e, n]: Bounds, pad: number) {
    const dx = (e - w) * pad, dy = (n - s) * pad;
    map.fitBounds([[w - dx, Math.max(-85, s - dy)], [e + dx, Math.min(85, n + dy)]], { maxZoom: 7, duration: reduced() ? 0 : 1200,
      padding: margins(innerWidth) });
  }
  return { map, ready, apply, fit, extent, overseasOf, frame, meet, shapes };
}
