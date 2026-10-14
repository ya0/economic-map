import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from econviz import boundaries, coverage, crosswalk, export, layers
from conftest import observations


def pool():
    geo = {"NE1:A-1": box(0, 0, 1, 1), "NE1:A-2": box(1, 0, 2, 1), "NE1:A-3": box(2, 0, 3, 1), "ITL3:TLC11": box(5, 0, 6, 1)}
    return gpd.GeoDataFrame({"region_id": list(geo), "iso3": ["AAA", "AAA", "AAA", "GBR"],
                             "name": ["Alpha", "Beta Province", "Gamma", "Darlington"],
                             "boundary_source_id": "ne", "boundary_vintage": "v", "geometry": list(geo.values())},
                            geometry="geometry", crs=4326)


def test_norm_ignores_accents_case_and_generic_words():
    assert crosswalk.norm("Región Ñuble") == crosswalk.norm("nuble") and crosswalk.norm("Beta Province") == "beta"


def test_propose_exact_fuzzy_and_ambiguous_duplicates():
    names = pd.DataFrame({"region_id": ["r1", "r2", "r3", "r4"], "iso3": "AAA", "name": ["ALPHA", "Betta", "Gamma", "Gamma"]})
    out = crosswalk.propose(names, pool(), "dose").set_index("region_id")
    assert out.loc["r1", ["geo_id", "method"]].tolist() == ["NE1:A-1", "exact"]
    assert out.loc["r2", ["geo_id", "method"]].tolist() == ["NE1:A-2", "fuzzy"]
    assert "r3" not in out.index and "r4" not in out.index  # both claim NE1:A-3: left for review


def test_propose_matches_uk_by_code_and_a_pool_unit_is_used_once():
    names = pd.DataFrame({"region_id": ["OECD:UKC11"], "iso3": "GBR", "name": ["Whatever"]})
    out = crosswalk.propose(names, pool(), "oecd_tl3")
    assert out[["region_id", "geo_id", "method"]].values.tolist() == [["OECD:UKC11", "ITL3:TLC11", "code"]]


def test_crosswalked_dissolves_units_and_computes_area():
    names = pd.DataFrame({"region_id": ["R1", "R2"], "iso3": "AAA", "name": ["one", "two"], "level": "tl2", "parent_id": None})
    cw = pd.DataFrame({"region_id": ["R1", "R1", "R2"], "geo_id": ["NE1:A-1", "NE1:A-2", "NE1:A-3"]})
    obs = observations([("R1", "AAA", "gdp", 2022, 1.0), ("R9", "AAA", "gdp", 2022, 5.0), ("AAZZ", "AAA", "gdp_extra", 2022, 2.0)])
    regions, o = layers.crosswalked(names, obs, pool(), cw)
    assert regions.set_index("region_id").loc["R1"].geometry.bounds == (0, 0, 2, 1)
    assert set(o["region_id"]) == {"R1", "R2", "R9", "AAZZ"}  # unmatched R9 stays visible so selection can reject the layer
    area = o[o["variable"] == "area_km2"].set_index("region_id")
    assert area.loc["R1", "value"] == pytest.approx(2 * area.loc["R2", "value"], rel=0.01) and area["note"].eq("area_computed").all()


def test_area_km2_is_equal_area():
    g = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1), box(0, 60, 1, 61)], crs=4326)
    a = boundaries.area_km2(g)
    assert a.iloc[0] == pytest.approx(12_300, rel=0.01) and a.iloc[1] == pytest.approx(a.iloc[0] * 0.5, rel=0.02)


def test_coverage_freshness_bands_sum_to_100_percent():
    ind = pd.DataFrame({"gdp_usd": [50.0, 20.0, 10.0, 10.0], "gdp_year": [2024, 2023, 2022, 2019]})
    f = coverage.freshness(ind, pd.Series({"X": 10.0}), ref=2024)
    assert f.to_dict() == {"ref year": 50.0, "2022-2023": 30.0, "older": 10.0, "unallocated": 10.0} and f.sum() == 100


def test_coverage_tiers_sum_to_100_percent_including_unallocated():
    ind = pd.DataFrame({"region_id": ["a", "b", "c"], "gdp_usd": [50.0, 30.0, 10.0]})
    levels = pd.Series({"a": "country", "b": "nuts3", "c": "county"})
    t = coverage.tiers(ind, levels, pd.Series({"X": 10.0}))
    assert t["share_pct"].sum() == pytest.approx(100.0) and t.loc["unallocated", "share_pct"] == 10.0
    assert t.loc["NUTS3/TL3", "regions"] == 1


def test_export_json_keeps_the_old_fields_in_order_and_appends_new_ones():
    assert export.COLUMNS == ["gdp_usd", "pop", "area_km2", "gdp_per_km2", "gdp_per_capita", "pop_density", "gdp_year", "pop_year",
                              "area_year", "gdp_source", "pop_source", "area_source", "flags", "level_no", "parent_id", "name", "iso2", "pop_raw"]


def test_export_json_is_compact_and_null_safe():
    ind = pd.DataFrame({"gdp_usd": [1.23456789e9, None], "pop": [1234567.0, None], "area_km2": [12.3456789, 5.0],
                        "gdp_per_km2": [1e8, None], "gdp_per_capita": [1e6, None], "pop_density": [80.0, None],
                        "gdp_year": [2022, 2019], "pop_year": [2022, None], "area_year": [2020, 2020],
                        "gdp_source": ["s", "s"], "pop_source": ["s", None], "area_source": ["s", "s"],
                        "flags": [["area_computed"], []], "level_no": [2, 0], "parent_id": ["ISO3:AAA", None],
                        "name": ["Ä region", "Alpha"], "iso2": ["AA", ""], "pop_raw": [1000000.0, None]}, index=["a", "b"])
    defl = pd.DataFrame({"year": [2000, 2022], "deflator": [80.0, 120.0]})
    doc = json.loads(export.indicators_json(ind, defl, 2022, pd.Series({"AAA": 5.0, "BBB": 0.0})))
    assert doc["meta"]["columns"] == export.COLUMNS and doc["meta"]["deflator_us_gdp"] == {"2000": 80.0, "2022": 120.0}
    assert doc["meta"]["unallocated_gdp_usd"] == {"AAA": 5}
    assert doc["regions"]["a"][:3] == [1234570000, 1234570, 12.3457] and doc["regions"]["a"][6] == 2022 and doc["regions"]["a"][12:] == [["area_computed"], 2, "ISO3:AAA", "Ä region", "AA", 1000000]
    assert doc["regions"]["b"][0] is None and doc["regions"]["b"][12:] == [[], 0, None, "Alpha", "", None]


def test_credits_name_the_used_sources_and_the_groupings_behind_the_second_subdivisions():
    ids = {s["source_id"] for s in json.loads(export.sources_json({"wb_wdi"}, [{"source_id": "wikipedia:X"}, {"source_id": "wikipedia:Y"}]))}
    assert ids == {"wb_wdi", "br_ibge_localidades", "mx_conapo_metropolis"}


def test_borrowed_population_only_for_regions_covering_the_same_single_unit():
    cw_new = pd.DataFrame({"region_id": ["N1", "N2", "N3", "N3"], "geo_id": ["g1", "g2", "g3", "g4"]})  # N3 dissolves two units
    cw_donor = pd.DataFrame({"region_id": ["D1", "D2", "D3", "D4"], "geo_id": ["g1", "g2", "g3", "g4"]})
    donor = observations([("D1", "AAA", "pop", 2019, 5.0), ("D1", "AAA", "gdp", 2019, 9.0), ("D2", "AAA", "pop", 2019, 6.0),
                          ("D3", "AAA", "pop", 2019, 7.0)], source_id="dose")
    got = layers.borrowed_population(donor, cw_new, cw_donor)
    assert got[["region_id", "variable", "year", "value", "source_id"]].values.tolist() == [
        ["N1", "pop", 2019, 5.0, "dose"], ["N2", "pop", 2019, 6.0, "dose"]]


def test_cut_overlaps_official_shape_wins_and_the_cut_region_loses_its_computed_area():
    def reg(rid, iso3, source, x0, x1):
        return {"region_id": rid, "iso3": iso3, "boundary_source_id": source, "geometry": box(x0, 0, x1, 1)}
    regions = gpd.GeoDataFrame([reg("NE:A", "AAA", "natural_earth", 0, 2), reg("N3:B", "BBB", "gisco_nuts", 1.5, 3),
                                reg("NE:A2", "AAA", "natural_earth", 3, 3.2)], geometry="geometry", crs=4326)  # A2 only touches B
    obs = observations([("NE:A", "AAA", "area_km2", 2020, 1.0), ("N3:B", "BBB", "area_km2", 2020, 2.0)])
    obs["note"] = ["area_computed", "area_computed"]
    out, kept = layers.cut_overlaps(regions, obs)
    g = out.set_index("region_id").geometry
    assert g["NE:A"].symmetric_difference(box(0, 0, 1.5, 1)).area < 1e-9
    assert g["N3:B"].equals(box(1.5, 0, 3, 1)) and g["NE:A2"].equals(box(3, 0, 3.2, 1))
    assert kept["region_id"].tolist() == ["N3:B"]  # the cut region's computed area is dropped


def test_cut_overlaps_between_equal_sources_cuts_the_later_region_and_same_country_overlaps_are_left():
    both = gpd.GeoDataFrame({"region_id": ["X", "Y"], "iso3": ["AAA", "BBB"], "boundary_source_id": ["natural_earth"] * 2,
                             "geometry": [box(0, 0, 2, 1), box(1, 0, 3, 1)]}, geometry="geometry", crs=4326)
    obs = observations([("X", "AAA", "area_km2", 2020, 1.0)]).assign(note="")
    out, _ = layers.cut_overlaps(both, obs)
    assert out.geometry.iloc[0].equals(box(0, 0, 2, 1)) and out.geometry.iloc[1].equals(box(2, 0, 3, 1))
    same, _ = layers.cut_overlaps(both.assign(iso3="AAA"), obs)
    assert same.geometry.iloc[1].equals(box(1, 0, 3, 1))


def test_coverage_land_shares_derived_share_and_holes():
    ind = pd.DataFrame({"level_no": [1, 2, 2], "area_km2": [60.0, 30.0, 10.0], "gdp_usd": [50.0, 30.0, 10.0],
                        "flags": [["whole_country"], ["pop_share"], []]})
    r = coverage.land(ind, pd.Series({"X": 10.0}), pd.DataFrame({"area_km2": [5.0, 7.0], "ok": [True, False]}))
    assert r.to_dict() == {"land_below_country_pct": 40.0, "gdp_below_country_pct": 40.0, "land_derived_pct": 30.0,
                           "gdp_derived_pct": 30.0, "open_holes_km2": 7}


def test_kyiv_city_and_abuja_are_not_holes_in_the_reference_tables():
    """Kyiv city is a region of the Ukrstat layer (its own Natural Earth unit); the FCT joins Niger State, the neighbour with
    the longest border (172.6 km against Nasarawa's 140.7), so neither is left out of a layer."""
    cw = crosswalk.load()
    uk = cw[cw["layer"] == "ukrstat"]
    assert len(uk) == 25 and not uk["geo_id"].duplicated().any() and not uk["region_id"].duplicated().any()
    assert uk.set_index("region_id").loc["UKRSTAT:8000000000", "geo_id"] == "NE1:UKR-4826"  # Kiev City
    assert uk.set_index("region_id").loc["UKRSTAT:3200000000", "geo_id"] == "NE1:UKR-321"  # Kiev oblast keeps its own unit
    wp = cw[cw["layer"] == "wikipedia"]
    assert wp[wp["geo_id"] == "NE1:NGA-3470"]["region_id"].tolist() == ["WP:NGA-niger-state"]
    assert sorted(wp[wp["region_id"] == "WP:NGA-niger-state"]["geo_id"]) == ["NE1:NGA-2851", "NE1:NGA-3470"]

