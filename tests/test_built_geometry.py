"""Checks on the last build in data/processed (skipped when there is none)."""
import geopandas as gpd
import pandas as pd
import pytest
from shapely import STRtree
from shapely.geometry import Point

from econviz import boundaries, holes
from econviz.paths import PROCESSED

pytestmark = pytest.mark.skipif(not (PROCESSED / "holes.csv").exists(), reason="no build output")


@pytest.fixture(scope="module")
def finest():
    return holes.finest(gpd.read_parquet(PROCESSED / "regions.geoparquet"))


def owner(finest, lon, lat):
    hit = finest[finest.contains(Point(lon, lat))]
    return hit["iso3"].tolist()


def test_attached_and_crosswalked_pieces_belong_to_a_country(finest):
    assert owner(finest, 46.08, 9.74) == ["SOM"]  # Somaliland
    assert owner(finest, 63.38, 45.96) == ["KAZ"]  # Baikonur
    assert owner(finest, 77.27, 35.42) == ["IND"]  # Siachen
    assert owner(finest, 33.8, 35.35) == ["CYP"]  # Northern Cyprus
    assert owner(finest, 28.16, -29.6) == ["LSO"]  # Lesotho is not inside South Africa's shape


def test_open_pieces_are_the_recorded_ones():
    pieces = pd.read_csv(PROCESSED / "holes.csv")
    still = set(pieces[~pieces["ok"]]["unit"])
    assert not still & {"NGA", "UKR"}, still  # Abuja (inside Niger State) and Kyiv city (own region) are closed (run 4b)


def test_somalia_area_is_close_to_world_bank_land_area():
    r = gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")
    area = boundaries.area_km2(r.loc[["ISO3:SOM"]]).iloc[0]
    assert abs(area / 627_340 - 1) < 0.03


def test_country_outline_is_the_dissolve_of_its_regions():
    r = gpd.read_parquet(PROCESSED / "regions.geoparquet")
    top = r[r["level"] == "country"].set_index("region_id")
    kids = r[r["parent_id"].isin(top.index)]
    dissolved = boundaries.dissolve(kids.geometry, kids["parent_id"])
    both = pd.concat([boundaries.area_km2(top.loc[dissolved.index]), boundaries.area_km2(gpd.GeoDataFrame(geometry=dissolved, crs=4326))], axis=1)
    assert ((both.iloc[:, 0] / both.iloc[:, 1] - 1).abs() < 0.001).all()


def test_no_two_countries_overlap(finest):
    tree, shapes = STRtree(finest.geometry.values), finest.geometry.values
    a, b = tree.query(shapes, predicate="intersects")
    pairs = [(i, j) for i, j in zip(a, b) if i < j and finest["iso3"].iloc[i] != finest["iso3"].iloc[j]]
    inter = gpd.GeoSeries([shapes[i].intersection(shapes[j]) for i, j in pairs], crs=4326)
    assert (boundaries.area_km2(gpd.GeoDataFrame(geometry=inter, crs=4326)) < 0.5).all()


def test_morocco_area_is_wdi_plus_western_sahara():
    ind = pd.read_parquet(PROCESSED / "indicators.parquet").set_index("region_id")
    sah = boundaries.area_km2(boundaries.natural_earth_units().set_index("unit").loc[["SAH"]]).iloc[0]
    assert abs(ind.loc["ISO3:MAR", "area_km2"] - (446_300 + sah)) < 1  # WDI 446,300 km2
    assert "area_computed" in ind.loc["ISO3:MAR", "flags"]


def test_kyiv_city_is_a_region_with_gdp_and_abuja_is_inside_niger_state():
    r = gpd.read_parquet(PROCESSED / "regions.geoparquet")
    finest = holes.finest(r)
    kyiv = finest[finest.contains(Point(30.52, 50.45))]
    assert kyiv["region_id"].tolist() == ["UKRSTAT:8000000000"]
    abuja = finest[finest.contains(Point(7.49, 9.07))]
    assert abuja["region_id"].tolist() == ["WP:NGA-niger-state"]
    ind = pd.read_parquet(PROCESSED / "indicators.parquet").set_index("region_id")
    assert ind.loc["UKRSTAT:8000000000", "gdp_usd"] > 0 and ind.loc["UKRSTAT:8000000000", "gdp_year"] == 2021

