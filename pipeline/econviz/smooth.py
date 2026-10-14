"""Last step: regions.geoparquet + indicators.parquet -> web/public/smooth/*.webp + smooth.json
(`python -m econviz.smooth`, after build; contract: ARCHITECTURE.md, The four files). Three indicators from the rasters G (GDP),
L (land km2), P (people), A (cell km2): GDP per km2 (K*G)/(K*L), population density (K*P)/(K*L), both with f = (K*L)/(K*A), and
GDP per capita (K*G)/(K*P) with B = the share of the GDP within reach whose region has population data.
Approximation: Mercator is conformal, so a disc of r km is a disc of r/(cell_km*cos(lat)) pixels (first order); rows are binned by
|lat| so that this radius varies by at most 4% inside a bin, and each bin is convolved with its own kernel (FFT, periodic in longitude)."""
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from PIL import Image

from .paths import PROCESSED, REF_YEAR, WEB_PUBLIC

EARTH_KM = 6371.0088
W, NORTH, SOUTH = 4096, 78.0, -58.0  # columns over 360 degrees; latitude range of the Mercator raster
GRIDS = {2 * W: (15, 30), W: (50, 100, 150)}  # raster columns: radii (km) convolved on them
WIDTH = {15: 4096, 30: 2048, 50: 2048, 100: 2048, 150: 1024}  # output columns
KERNELS = ("inv2", "gauss")
INDICATORS = {"gdp_per_km2": "", "pop_density": "pop_", "gdp_per_capita": "pcap_"}  # id: file prefix
CUT = 4.0  # inv2 ends at CUT * r
SUPPORT = {"inv2": CUT, "gauss": 2.0}  # kernel support in units of r
MIN_VALUE = 1e-3  # a value (US$ or people per km2, US$ per person) below this is rounding noise of the FFT, not data
FLOOR = 1e-3  # km2 of land (people for per capita) within reach below which the surface is undefined
BAND = 1.04  # ratio of 1/cos(lat) across one row band
OUT = WEB_PUBLIC / "smooth"


def kernel(name: str, d, r: float):
    """Weight at distance d (same unit as r) of the kernel `name` with radius parameter r. gauss has the per-axis variance r^2/4.
    inv2, w = 1/(1 + (d/a)^2) cut at CUT*r, has a second moment that grows with the cut without bound, so its a is set by
    the median: half of the 2D weight lies within r/sqrt(2), a = r / (2 sqrt(CUT^2 - 1))."""
    if name == "inv2":
        return (d <= CUT * r) / (1 + 4 * (CUT ** 2 - 1) * (d / r) ** 2)
    return np.exp(-2 * (d / r) ** 2) * (d <= 2 * r)  # sigma = r/2, cut at 4 sigma (loses 0.3% of the variance)


def grid(w: int = W):
    """Cell-centre longitudes and latitudes of the Mercator raster and the equatorial cell size in km. The height is a multiple
    of 16, and of 16 w/W above W, so every width covers the same latitudes."""
    dx, n = 2 * np.pi / w, 16 * max(w // W, 1)
    y_n, y_s = (np.log(np.tan(np.pi / 4 + np.radians(a) / 2)) for a in (NORTH, SOUTH))
    y = y_n - (np.arange(round((y_n - y_s) / dx / n) * n) + 0.5) * dx
    return -180 + (np.arange(w) + 0.5) * 360 / w, np.degrees(np.arctan(np.sinh(y))), EARTH_KM * dx


def rasterise(shapes, values, lon, lat, km):
    """One raster per array in `values` (GDP, land km2, people ... per shape), then A (true cell area km2) and the number of shapes without a cell: each shape's value is spread over the cells whose centre it contains in proportion to A; a shape with no cell centre puts
    everything into the cell of its representative point. The rasters are float32 (memory; totals are kept to 1e-7)."""
    A = np.repeat(((km * np.cos(np.radians(lat))) ** 2)[:, None], len(lon), 1)
    owner = np.full(A.shape, -1, np.int32)
    parts = gpd.GeoSeries(shapes).explode(index_parts=False)
    for k, geom in zip(parts.index, parts.values):
        shapely.prepare(geom)
        x0, y0, x1, y1 = geom.bounds
        c, r = np.searchsorted(lon, [x0, x1]), np.searchsorted(-lat, [-y1, -y0])
        cols, rows = slice(c[0], c[1] + 1), slice(r[0], r[1] + 1)
        inside = shapely.contains_xy(geom, *np.meshgrid(lon[cols], lat[rows]))
        sub = owner[rows, cols]
        sub[inside & (sub < 0)] = k
    n = len(shapes)
    mass = np.bincount(owner[owner >= 0], A[owner >= 0], minlength=n)
    share = np.where(owner >= 0, A / np.where(mass[owner] > 0, mass[owner], 1), 0.0)
    out = [(np.where(owner >= 0, np.asarray(v)[owner], 0.0) * share).astype(np.float32) for v in values]
    empty = np.flatnonzero(mass == 0)
    for k in empty:
        p = shapes.iloc[k].representative_point()
        i, j = np.abs(lat - p.y).argmin(), min(int((p.x + 180) / 360 * len(lon)), len(lon) - 1)
        owner[i, j] = k if owner[i, j] < 0 else owner[i, j]
        for o, v in zip(out, values):
            o[i, j] += v[k]
    return *out, A.astype(np.float32), len(empty)


def reach(arrays, lat, km, name, r):
    """K*a for each array a (rows = latitudes), kernel `name` of radius r km. Each row band is convolved as a zero-padded slab
    (periodic in longitude, nothing beyond the first and last row) with the kernel of its pixel radius, in float64 whatever the arrays are."""
    h, w = arrays[0].shape
    band = np.floor(-np.log(np.cos(np.radians(lat))) / np.log(BAND)).astype(int)
    key = band + 1000 * (lat < 0)  # one contiguous run of rows per key
    out = [np.zeros((h, w), a.dtype) for a in arrays]
    for b in np.unique(key):
        rows = np.flatnonzero(key == b)
        r_px = r / (km * BAND ** -(b % 1000 + 0.5))
        m = int(np.ceil(SUPPORT[name] * r_px))
        i0, i1 = rows[0], rows[-1] + 1
        lo, hi = max(i0 - m, 0), min(i1 + m, h)
        hp = -(-(hi - lo + 2 * m) // 16) * 16
        yy, xx = np.mgrid[-m:m + 1, -m:m + 1]
        k = np.zeros((hp, w))
        k[np.ix_(yy[:, 0] % hp, xx[0] % w)] = kernel(name, np.hypot(yy, xx), r_px)
        kf = np.fft.rfft2(k)
        for o, a in zip(out, arrays):
            slab = np.fft.irfft2(np.fft.rfft2(np.pad(a[lo:hi].astype(float), ((m, hp - (hi - lo) - m), (0, 0)))) * kf, s=(hp, w))
            o[i0:i1] = slab[m + i0 - lo:m + i1 - lo]
    return out


def blocks(a, factor):
    return a.reshape(a.shape[0] // factor, factor, a.shape[1] // factor, factor).sum((1, 3))


def dilate(mask):
    """True where the cell or one of its 8 neighbours is (columns wrap around): thin coasts and small islands keep their pixels."""
    rows = np.pad(mask, ((1, 1), (0, 0)))
    rows = rows[:-2] | rows[1:-1] | rows[2:]
    return rows | np.roll(rows, 1, 1) | np.roll(rows, -1, 1)


def surface(kn, kd, bn, bd, land, factor):
    """(log10 kn/kd, clip(bn/bd), alpha) after block-summing the four by `factor`; alpha: 0 undefined (less than FLOOR of kd or
    a value below MIN_VALUE), 128 defined at sea, 255 defined on a pixel that holds land (`land` > 0 in one of its cells)."""
    kn, kd, bn, bd, land = (blocks(a, factor) for a in (kn, kd, bn, bd, land))
    ok = (kd > FLOOR * factor ** 2) & (kn > MIN_VALUE * kd)
    return (np.log10(np.where(ok, kn / np.where(kd > 0, kd, 1), 1.0)).astype(np.float32), np.clip(bn / np.where(bd > 0, bd, 1), 0, 1).astype(np.float32),
            (ok * np.where(land > 0, 255, 128)).astype(np.uint8))


def encode(logs, f, alpha, lo, hi):
    """RGBA uint8: R,G = 16-bit big-endian code of log10 between lo and hi, B = 255 f, A = `alpha` (RGB 0 where it is 0)."""
    q = np.round(np.clip((logs - lo) / (hi - lo), 0, 1) * 65535).astype(np.uint16)
    return np.dstack([q >> 8, q & 255, np.round(255 * f), alpha]).astype(np.uint8) * (alpha > 0)[..., None]


def write_webp(path, rgba):
    """Lossless WebP of the RGBA bytes; `exact` keeps the bytes under A = 0 (about half the size of the PNG; the page reads the bytes back through WebGL)."""
    Image.fromarray(rgba, "RGBA").save(path, lossless=True, exact=True, quality=100)


def run():
    regions, ind = (t.set_index("region_id") for t in (gpd.read_parquet(PROCESSED / "regions.geoparquet"), pd.read_parquet(PROCESSED / "indicators.parquet")))
    finest = ind[~ind.index.isin(ind["parent_id"]) & ~ind.index.str.startswith("DISPUTED:") & ind["gdp_usd"].notna() & (ind["area_km2"] > 0)]
    has_pop = finest["pop"].notna() & (finest["pop"] > 0)
    shapes = regions.geometry.loc[finest.index].reset_index(drop=True)
    values = (finest["gdp_usd"].values, finest["area_km2"].values, finest["pop"].where(has_pop, 0.0).values, finest["gdp_usd"].where(has_pop, 0.0).values)
    print(f"{len(finest)} regions; {(~has_pop).sum()} without population, {finest['gdp_usd'][~has_pop].sum() / finest['gdp_usd'].sum():.2%} of GDP: "
          f"{list(finest.index[~has_pop][:20])}")
    OUT.mkdir(parents=True, exist_ok=True)
    done = {}
    for w, radii in GRIDS.items():
        lon, lat, km = grid(w)
        G, L, P, Gp, A, empty = rasterise(shapes, values, lon, lat, km)
        print(f"{w} columns: sum G {G.sum(dtype=float):.6e} vs {values[0].sum():.6e}; L {L.sum(dtype=float):.6e} vs {values[1].sum():.6e}; "
              f"P {P.sum(dtype=float):.6e} vs {values[2].sum():.6e}; {empty} regions without a cell centre")
        near = dilate(L > 0)  # the land mask: a cell with land or next to one
        for name in KERNELS:
            for r in radii:
                kg, kl, kp, kgp, ka = reach((G, L, P, Gp, A), lat, km, name, r)
                f = w // WIDTH[r]
                done[name, r] = {"gdp_per_km2": surface(kg, kl, kl, ka, near, f), "pop_density": surface(kp, kl, kl, ka, near, f),
                                 "gdp_per_capita": surface(kgp, kp, kgp, kg, near, f)}
    south = float(np.degrees(np.arctan(np.sinh(np.log(np.tan(np.pi / 4 + np.radians(NORTH) / 2)) - len(lat) * 2 * np.pi / w))))
    meta = {"indicators": {}}
    for ind_id, prefix in INDICATORS.items():
        lo, hi = (float(m([m(s[ind_id][0][s[ind_id][2] > 0]) for s in done.values()])) for m in (np.min, np.max))
        size = 0
        for (name, r), s in done.items():
            write_webp(OUT / f"{prefix}{name}_{r}.webp", encode(*s[ind_id], lo, hi))
            size += (OUT / f"{prefix}{name}_{r}.webp").stat().st_size
        meta["indicators"][ind_id] = {"prefix": prefix, "lo": lo, "hi": hi}
        print(f"{ind_id}: log10 in [{lo:.2f}, {hi:.2f}], {size / 1e6:.1f} MB")
    g = meta["indicators"]["gdp_per_km2"]  # the top-level keys are GDP per km2's
    (OUT / "smooth.json").write_text(json.dumps({"ref_year": REF_YEAR, "unit": "current US$ per km2", "lo": g["lo"], "hi": g["hi"], "north": NORTH, "south": south,
        "kernels": list(KERNELS), "radii": sorted(WIDTH), "width": WIDTH, "files": "smooth/{kernel}_{radius}.webp", **meta}))
    print(f"{OUT}: {sum(p.stat().st_size for p in OUT.iterdir()) / 1e6:.1f} MB")


if __name__ == "__main__":
    run()
