import json

import geopandas as gpd
import numpy as np
import pytest
from PIL import Image
from shapely.geometry import Point, box

from econviz import smooth

KM = 10.0  # equatorial cell size of the toy grids
WHOLE = ["ISO3:COD", "ISO3:LBY", "ISO3:TZA", "ISO3:NAM"]  # countries shown whole (a single value), large enough to have an interior at 50 km


def toy(w, h, lat0=0.0):
    """Cell centres of a w x h grid of tiny cells around latitude lat0 (so cos(lat) is constant to first order)."""
    return -180 + (np.arange(w) + 0.5) * 360 / w, lat0 - (np.arange(h) - h / 2 + 0.5) * 1e-3


def prepared(lat0, n, kern, r):
    """Point source on an n x n grid at latitude lat0 and its smoothed numerator K*G."""
    lat = np.full(n, lat0)  # constant latitude, so every row has the same kernel
    A = np.full((n, n), (KM * np.cos(np.radians(lat0))) ** 2)
    G = np.zeros((n, n))
    G[n // 2, n // 2] = 1.0
    return smooth.reach((G, A), lat, KM, kern, r)[0], A


def test_rasterise_conserves_each_regions_mass_and_gives_a_tiny_region_a_cell():
    lon, lat = toy(40, 20)
    shapes = gpd.GeoSeries([box(-90, -0.004, 0, 0.005), box(0, -0.004, 90, 0.005), box(100, 0.0, 100.0001, 0.0001)], crs=4326)
    gdp, area, pop = np.array([3e9, 5e9, 7e6]), np.array([100.0, 250.0, 2.0]), np.array([4e5, 0.0, 9e3])  # the second has no population
    G, L, P, A, empty = smooth.rasterise(shapes, (gdp, area, pop), lon, lat, KM)
    col = lambda lo, hi: (lon > lo) & (lon < hi)
    assert empty == 1 and G.sum() == pytest.approx(gdp.sum(), rel=1e-6) and L.sum() == pytest.approx(area.sum(), rel=1e-6)
    assert P.sum() == pytest.approx(pop.sum(), rel=1e-6) and P[:, col(0, 90)].sum() == 0
    assert G[:, col(-90, 0)].sum() == pytest.approx(3e9, rel=1e-6) and L[:, col(0, 90)].sum() == pytest.approx(250, rel=1e-6)
    assert G[:, col(95, 105)].sum() == pytest.approx(7e6, rel=1e-6) and G.dtype == A.dtype == np.float32  # float32 rasters keep the totals to 1e-7


def test_the_kernels_are_inverse_square_and_gauss_and_gauss_has_the_per_axis_variance_r2_over_4():
    assert smooth.KERNELS == ("inv2", "gauss") and set(smooth.SUPPORT) == set(smooth.KERNELS)
    d = np.linspace(0, 3000, 600001)
    for r in (15.0, 150.0):
        k = smooth.kernel("gauss", d, r)
        assert (k * d ** 3).sum() / (k * d).sum() / 2 == pytest.approx(r * r / 4, rel=0.01)


def test_inverse_square_has_its_median_at_r_over_root_2():
    d = np.linspace(0, 2000, 2000001)
    for r in (15.0, 150.0):
        k = smooth.kernel("inv2", d, r)
        mass = np.cumsum(k * d)  # 2D weight within d
        assert d[np.searchsorted(mass, mass[-1] / 2)] == pytest.approx(r / 2 ** 0.5, rel=0.002)
        assert k[d > smooth.CUT * r].max() == 0 and k[0] == 1 and (np.diff(k) <= 0).all()
        assert smooth.kernel("inv2", 0.1291 * r, r) == pytest.approx(0.5, rel=1e-3)  # a = 0.129 r


def test_every_grid_width_covers_the_same_latitudes():
    (lon, a, ka), (fine, b, kb) = smooth.grid(), smooth.grid(2 * smooth.W)
    assert (len(fine), len(b), kb) == (2 * len(lon), 2 * len(a), ka / 2) and len(a) % 16 == 0
    assert b.reshape(-1, 2).mean(1) == pytest.approx(a, abs=1e-4) and b[0] > a[0] > b[1] and b[-2] > a[-1] > b[-1]


@pytest.mark.parametrize("name", smooth.KERNELS)
def test_constant_density_stays_constant(name):
    lon, lat, km = smooth.grid(256)
    A = np.repeat(((km * np.cos(np.radians(lat))) ** 2)[:, None], 256, 1)
    land = np.random.default_rng(0).random(A.shape) < 0.6
    L = A * land * 0.7
    for kind, rel in ((float, 1e-9), (np.float32, 1e-6)):  # float32 as in the run: the convolution itself is done in float64
        kg, kl, ka = smooth.reach([a.astype(kind) for a in (5e5 * L, L, A)], lat, km, name, 150)
        ok = kl > 1.0
        assert ok.any() and kg.dtype == kind and (kg[ok] / kl[ok]) == pytest.approx(5e5, rel=rel)


def test_the_radii_are_the_ladder_on_two_grids_and_every_width_fits_its_grid():
    assert sorted(smooth.WIDTH) == [15, 30, 50, 100, 150] == sorted(r for radii in smooth.GRIDS.values() for r in radii)
    assert smooth.GRIDS == {2 * smooth.W: (15, 30), smooth.W: (50, 100, 150)}
    assert smooth.WIDTH == {15: 4096, 30: 2048, 50: 2048, 100: 2048, 150: 1024}
    assert all(w % smooth.WIDTH[r] == 0 and w >= smooth.WIDTH[r] for w, radii in smooth.GRIDS.items() for r in radii)


@pytest.mark.parametrize("r", [15, 150])
@pytest.mark.parametrize("name", smooth.KERNELS)
def test_G_L_and_P_are_conserved_to_1e7_by_the_smoothing_at_the_smallest_and_largest_radius(name, r):
    n = 256
    lat, rng = np.full(n, 0.0), np.random.default_rng(2)
    fields = [np.zeros((n, n)) for _ in range(3)]  # G, L, P: sparse sources away from the edges, whatever their ratios
    for f, scale in zip(fields, (1e9, 50.0, 1e5)):
        f[n // 4:3 * n // 4, n // 4:3 * n // 4] = rng.random((n // 2, n // 2)) * (rng.random((n // 2, n // 2)) < 0.1) * scale
    r_px = r / (KM * smooth.BAND ** -0.5)
    m = int(np.ceil(smooth.SUPPORT[name] * r_px))
    yy, xx = np.mgrid[-m:m + 1, -m:m + 1]
    total = smooth.kernel(name, np.hypot(yy, xx), r_px).sum()
    for f, out in zip(fields, smooth.reach(fields, lat, KM, name, float(r))):
        assert out.sum() == pytest.approx(f.sum() * total, rel=1e-7)


def decoded(prefix, name, r):
    """(code / 65535, B, A) of a built WebP."""
    px = np.array(Image.open(smooth.OUT / f"{prefix}{name}_{r}.webp").convert("RGBA"))
    return (px[..., 0] * 256.0 + px[..., 1]) / 65535, px[..., 2], px[..., 3]


BUILT = pytest.mark.skipif(not (smooth.OUT / "smooth.json").exists(), reason="smoothed surfaces not built")


@BUILT
def test_the_built_files_are_exactly_5_radii_times_2_kernels_times_3_indicators_and_smooth_json():
    meta = json.loads((smooth.OUT / "smooth.json").read_text())
    assert list(meta) == ["ref_year", "unit", "lo", "hi", "north", "south", "kernels", "radii", "width", "files", "indicators"]
    assert meta["radii"] == [15, 30, 50, 100, 150] and meta["kernels"] == ["inv2", "gauss"]
    assert {i: m["prefix"] for i, m in meta["indicators"].items()} == smooth.INDICATORS
    assert (meta["lo"], meta["hi"]) == (meta["indicators"]["gdp_per_km2"]["lo"], meta["indicators"]["gdp_per_km2"]["hi"])
    names = {"smooth.json"} | {f"{p}{k}_{r}.webp" for p in ("", "pop_", "pcap_") for k in smooth.KERNELS for r in meta["radii"]}
    assert {p.name for p in smooth.OUT.iterdir()} == names and len(names) == 31


@BUILT
def test_per_capita_times_population_density_is_gdp_per_km2_where_all_the_gdp_has_population():
    meta = json.loads((smooth.OUT / "smooth.json").read_text())["indicators"]
    for name, r in (("inv2", 50), ("gauss", 150)):
        (g, _, ag), (p, _, ap), (c, bc, ac) = (decoded(*a) for a in (("", name, r), ("pop_", name, r), ("pcap_", name, r)))
        ok = (ag > 0) & (ap > 0) & (ac > 0) & (bc == 255)
        assert ok.mean() > 0.01
        lg, lp, lc = (meta[i]["lo"] + x[ok] * (meta[i]["hi"] - meta[i]["lo"]) for x, i in ((g, "gdp_per_km2"), (p, "pop_density"), (c, "gdp_per_capita")))
        assert np.abs(lc + lp - lg).max() < 0.002


@BUILT
def test_inside_a_whole_country_the_smoothed_per_capita_is_the_national_value():
    import geopandas as gpd
    import pandas as pd
    from econviz.paths import PROCESSED
    meta = json.loads((smooth.OUT / "smooth.json").read_text())
    ind = pd.read_parquet(PROCESSED / "indicators.parquet").set_index("region_id")
    regions = gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")
    code, _, alpha = decoded("pcap_", "gauss", 50)
    h, w = code.shape
    merc = lambda lat: np.arcsinh(np.tan(np.radians(lat)))
    m, checked = meta["indicators"]["gdp_per_capita"], []
    for iso in WHOLE:
        inner = regions.geometry[iso].buffer(-1.5)  # a Gaussian of 50 km reaches 100 km, about 0.9 degrees
        assert not inner.is_empty and not ind.parent_id.eq(iso).any()  # shown whole, no region below it
        p = inner.representative_point()
        i = int((merc(meta["north"]) - merc(p.y)) / (merc(meta["north"]) - merc(meta["south"])) * h)
        j = int((p.x + 180) / 360 * w)
        assert alpha[i, j] == 255
        checked.append(10 ** (m["lo"] + code[i, j] * (m["hi"] - m["lo"])) / (ind.gdp_usd[iso] / ind["pop"][iso]))
    assert checked == pytest.approx([1.0] * len(WHOLE), abs=0.01)


def test_the_third_kernel_of_the_earlier_ladder_is_gone():
    import pathlib
    root, word = pathlib.Path(__file__).parents[1], "ba" + "ll"
    assert word not in (root / "pipeline/econviz/smooth.py").read_text().lower() and word not in pathlib.Path(__file__).read_text().lower()
    assert word not in (root / "ARCHITECTURE.md").read_text().lower()


@pytest.mark.parametrize("name", ["inv2", "gauss"])
def test_point_source_decreases_with_distance(name):
    r = 50.0
    kg, A = prepared(0.0, 128, name, r)
    n, r_px = 128, r / (KM * smooth.BAND ** -0.5)  # the pixel radius of band 0
    row = kg[n // 2, n // 2:]
    assert (np.diff(row[:int(smooth.SUPPORT[name] * r_px)]) <= 1e-12).all()
    assert row[int(smooth.SUPPORT[name] * r_px) + 2:] == pytest.approx(0, abs=1e-9)


def test_pixel_radius_grows_as_one_over_cos_latitude():
    cells = []
    for lat0 in (0.0, 60.0):
        kg, _ = prepared(lat0, 256, "gauss", 150.0)
        cells.append((kg[128] > 1e-9).sum())
    assert cells[1] / cells[0] == pytest.approx(2.0, rel=0.05)


def test_alpha_tells_land_from_sea_and_from_undefined():
    kg = np.ones((2, 4))
    kl = np.array([[5.0, 5.0, 5.0, 5.0], [5.0, 5.0, 0.0, 0.0]])  # land within reach of the six left cells
    land = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]])  # one cell holds land
    ka = np.full((2, 4), 10.0)
    assert smooth.surface(kg, kl, kl, ka, land, 1)[2].tolist() == [[255, 128, 128, 128], [128, 128, 0, 0]]
    assert smooth.surface(kg, kl, kl, ka, land, 2)[2].tolist() == [[255, 128]]  # a pixel with any land in its block


def test_land_mask_reaches_one_cell_beyond_land_and_wraps_in_longitude():
    land = np.zeros((5, 8), bool)
    land[2, 3] = land[0, 7] = True  # a one-cell island and a coast cell on the last column
    near = smooth.dilate(land)
    assert near[1:4, 2:5].all() and near[:2, [6, 7, 0]].all() and near.sum() == 9 + 6
    ones = np.ones((5, 8))
    assert (smooth.surface(ones, 5 * ones, 5 * ones, 10 * ones, near, 1)[2] == np.where(near, 255, 128)).all()


def test_webp_round_trip_is_exact_including_the_bytes_under_alpha_0(tmp_path):
    rng = np.random.default_rng(1)
    logs, f = rng.uniform(2, 7, (6, 9)), rng.random((6, 9))
    alpha = rng.choice([0, 128, 255], (6, 9))
    ok = alpha > 0
    rgba = smooth.encode(logs, f, alpha, 1.0, 8.0)
    smooth.write_webp(tmp_path / "x.webp", rgba)
    px = np.array(Image.open(tmp_path / "x.webp").convert("RGBA"))
    assert (px == rgba).all()
    back = 1.0 + (px[..., 0] * 256.0 + px[..., 1]) / 65535 * 7.0
    assert np.abs(back - logs)[ok].max() <= 7.0 / 65535 / 2 + 1e-12
    assert (px[..., 3] == alpha).all() and (px[~ok] == 0).all() and np.abs(px[..., 2] / 255 - f)[ok].max() <= 1 / 510 + 1e-12
