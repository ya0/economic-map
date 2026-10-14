"""Checks on the last build in data/processed (skipped when there is none): the pilot zones (`pop_share`)."""
import json

import geopandas as gpd
import pandas as pd
import pytest

from econviz import boundaries, zones
from econviz.paths import PROCESSED, WEB_PUBLIC

pytestmark = pytest.mark.skipif(not (PROCESSED / "admin1_pop_coverage.csv").exists(), reason="no build output")


@pytest.fixture(scope="module")
def ind():
    return pd.read_parquet(PROCESSED / "indicators.parquet").set_index("region_id")


@pytest.fixture(scope="module")
def zone(ind):
    return ind[ind.index.str.startswith("ZONE:")]


def test_only_ready_countries_have_zones_and_each_has_two_to_five_regions(zone):
    cov = pd.read_csv(PROCESSED / "admin1_pop_coverage.csv").set_index("iso3")
    assert set(zone["iso3"]) == set(ROLLED_OUT) and cov.loc[ROLLED_OUT, "ready"].all()
    assert set(cov.index[cov["ready"] & (cov["layer"] == "whole")]) == {"COD", "MMR", "MOZ", "TZA"}  # a zone above 70% of the land
    assert zone.groupby("iso3").size().between(2, 5).all()
    assert cov["units"].ge(zones.MIN_UNITS).all() and (cov["share"].between(0, 1)).all()


def test_zones_sum_to_the_country_and_carry_the_national_per_capita_only(zone, ind):
    country = ind[ind["level_no"] == 1].set_index("iso3")
    for iso3, z in zone.groupby("iso3"):
        assert z["gdp_usd"].sum() == pytest.approx(country.loc[iso3, "gdp_usd"], rel=1e-6)
        assert z["pop"].sum() == pytest.approx(country.loc[iso3, "pop"], rel=1e-6)
        assert (z["gdp_per_capita"] / country.loc[iso3, "gdp_per_capita"] - 1).abs().max() < 1e-6
        assert (z["area_km2"] / z["area_km2"].sum()).max() < (0.85 if iso3 in zones.BIG_OK else 0.70)
        assert z["parent_id"].eq(f"ISO3:{iso3}").all() and z["level_no"].eq(2).all()


def test_zones_are_flagged_and_keep_their_raw_population(zone, ind):
    assert zone["flags"].map(lambda f: "pop_share" in f and "area_computed" in f).all()
    assert zone["pop_raw"].notna().all() and zone["flags"].map(lambda f: "pop_scaled" in f).all()
    assert ind.loc[[f"ISO3:{i}" for i in zone["iso3"].unique()], "flags"].map(lambda f: "contains_pop_share" in f).all()
    assert zone["gdp_source"].eq("wb_wdi").all() and zone["pop_source"].notna().all()


def test_zones_tile_their_country():
    r = gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")
    for iso3 in r.loc[r.index.str.startswith("ZONE:"), "iso3"].unique():
        z, c = r[(r["iso3"] == iso3) & r.index.str.startswith("ZONE:")], r.loc[f"ISO3:{iso3}"]
        assert abs(boundaries.area_km2(z).sum() / boundaries.area_km2(gpd.GeoDataFrame(geometry=[c.geometry], crs=4326)).iloc[0] - 1) < 0.01
        assert z.geometry.union_all().symmetric_difference(c.geometry).area / c.geometry.area < 0.01


def test_web_contract_only_appends():
    meta = json.loads((WEB_PUBLIC / "indicators.json").read_text())["meta"]["columns"]
    assert meta[:17] == ["gdp_usd", "pop", "area_km2", "gdp_per_km2", "gdp_per_capita", "pop_density", "gdp_year", "pop_year", "area_year",
                         "gdp_source", "pop_source", "area_source", "flags", "level_no", "parent_id", "name", "iso2"]


ROLLED_OUT = ["AGO", "COG", "DZA", "ETH", "IRQ", "KEN", "MLI", "MNG", "MRT", "NER", "OMN", "PNG", "PRY", "SAU", "SDN", "TCD", "TKM", "VEN"]


@pytest.mark.parametrize("iso3", ROLLED_OUT)
def test_rolled_out_country_has_flagged_zones_that_sum_and_tile(iso3, zone, ind):
    z = zone[zone["iso3"] == iso3]
    assert 2 <= len(z) <= 5 and z["flags"].map(lambda f: "pop_share" in f).all()
    assert z["gdp_usd"].sum() == pytest.approx(ind.loc[f"ISO3:{iso3}", "gdp_usd"], rel=1e-6)
    assert z["area_km2"].max() / z["area_km2"].sum() <= (0.85 if iso3 == "DZA" else 0.70)


def test_data_status_table_equals_the_coverage_output():
    from econviz import coverage
    i = pd.read_parquet(PROCESSED / "indicators.parquet")
    i = i[~i["region_id"].isin(i["parent_id"])]
    levels = gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")["level"]
    un = pd.read_parquet(PROCESSED / "unallocated.parquet")["unallocated_gdp_usd"]
    t = coverage.tiers(i, levels, un)
    doc = (PROCESSED.parents[1] / "DATA.md").read_text(encoding="utf-8")
    for tier, label in (("country", "| Whole country |"), ("NUTS3/TL3", "| NUTS3 / OECD TL3 |")):
        row = next(l for l in doc.splitlines() if l.startswith(label)).split("|")
        assert int(row[2].replace(",", "")) == t.loc[tier, "regions"] and float(row[3].strip(" %")) == pytest.approx(t.loc[tier, "share_pct"], abs=0.051)
