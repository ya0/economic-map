import geopandas as gpd
import pandas as pd
import pyogrio
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from econviz import levels, tiles
from econviz.paths import PROCESSED, WEB_PUBLIC

PMTILES = WEB_PUBLIC / "regions.pmtiles"
TINY = ["DOSM:W.P. Kuala Lumpur", "DOSM:W.P. Putrajaya", "DOSM:W.P. Labuan", "FIPS:36061", "OECD:UKI35", "NUTS2024:FR101",
        "ISO3:MCO", "DISPUTED:crimea"]  # regions older tiles dropped (among them New York County, Westminster, Paris)


def test_label_points_lie_inside_the_largest_part_and_rank_by_gdp_within_a_level():
    c_shape = Polygon([(0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (3, 2), (3, 3), (0, 3)])  # its centroid is outside
    islands = MultiPolygon([box(10, 0, 10.1, 0.1), box(20, 0, 22, 2)])
    r = gpd.GeoDataFrame({"name": list("abc"), "level_no": [1, 1, 2]}, index=["c", "i", "x"], geometry=[c_shape, islands, box(5, 5, 6, 6)], crs=4326)
    p = tiles.label_points(r, pd.Series({"c": 1.0, "i": 2.0}))
    assert p.within(r.geometry).all() and p.geometry["i"].within(box(20, 0, 22, 2)) and set(p.geom_type) == {"Point"}
    assert p["rank"].to_dict() == {"c": 2, "i": 1, "x": 1} and list(p.columns) == ["name", "level_no", "rank", "geometry"]


def test_stand_ins_are_squares_two_tile_units_wide_for_regions_below_one_tile_unit():
    r = gpd.GeoDataFrame({"name": ["small", "big"]}, index=["s", "b"], geometry=[box(7.41, 43.72, 7.44, 43.75), box(0, 0, 5, 5)], crs=4326)
    by_zoom = dict(tiles.stand_ins(r, r.representative_point()))  # `small` is 4.6 km high in Web Mercator, a unit is 19.6 km at zoom 0
    assert [list(g.index) for g in by_zoom.values()] == [["s"]] * 3 + [[]] * (tiles.MAXZOOM - 3)
    square, unit = by_zoom[0].to_crs(3857), tiles.WORLD / 2 ** tiles.LOW_DETAIL
    assert square.bounds.iloc[0].tolist() == pytest.approx((square.centroid.x["s"] - unit, square.centroid.y["s"] - unit,
                                                           square.centroid.x["s"] + unit, square.centroid.y["s"] + unit))
    assert square.contains(r.to_crs(3857).geometry["s"]).all() and by_zoom[0]["name"].tolist() == ["small"]


@pytest.fixture(scope="module")
def regions():
    if not PMTILES.exists() or not (PROCESSED / "regions.geoparquet").exists():
        pytest.skip("no tiles built")
    return gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")


def ids(layer, zoom, **kwargs) -> set:
    return set(pyogrio.read_dataframe(PMTILES, layer=layer, columns=["region_id"], read_geometry=False, ZOOM_LEVEL=zoom, **kwargs)["region_id"])


def test_built_label_points_lie_inside_their_region(regions):
    assert tiles.label_points(regions, pd.Series(dtype=float)).within(regions.geometry).all()


def test_tiles_hold_every_region_of_every_layer_at_the_lowest_zoom(regions):
    assert sorted(pyogrio.list_layers(PMTILES)[:, 0]) == [*tiles.LAYERS, "labels"]
    for no, layer in enumerate(tiles.LAYERS):
        assert ids(layer, 0) == set(levels.cover(regions, no).index), layer
    assert set(TINY) <= ids("l3", 0) and "DISPUTED:crimea" in ids("l0", 0) & ids("l1", 0) & ids("l2", 0)


def test_tiles_hold_every_label_point_from_the_first_zoom_of_its_level(regions):
    first = regions["level_no"].map(tiles.LABEL_MINZOOM)
    for zoom in sorted(set(first)):
        assert ids("labels", zoom) == set(regions.index[first <= zoom]), zoom


def test_tiles_hold_the_tiny_regions_at_the_highest_zoom(regions):
    points = tiles.label_points(regions.loc[TINY], pd.Series(dtype=float)).geometry.to_crs(3857)  # the tiles' CRS
    for rid, p in points.items():
        for layer in ("l3", "labels"):
            assert rid in ids(layer, tiles.MAXZOOM, bbox=p.buffer(1000).bounds), (rid, layer)


@pytest.mark.slow
def test_tiles_hold_every_region_of_every_layer_at_the_highest_zoom(regions):
    for no, layer in enumerate(tiles.LAYERS):
        assert ids(layer, tiles.MAXZOOM) == set(levels.cover(regions, no).index), layer
    assert ids("labels", tiles.MAXZOOM) == set(regions.index)
