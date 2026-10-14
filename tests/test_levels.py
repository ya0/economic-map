import gzip
import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, box

from econviz import boundaries, build, export, indicators, levels
from econviz.paths import PROCESSED, WEB_PUBLIC
from conftest import observations, square_regions

TL2_OF = pd.Series({"OECD:AAA0": "OECD:A1", "OECD:AAA1": "OECD:A1", "OECD:AAA2": "OECD:A2", "OECD:AAA3": "OECD:A2"})
CONTINENT = pd.Series({"AAA": "CONT:europe", "BBB": "CONT:europe", "CCC": "CONT:asia", "DDD": "CONT:asia"})


def finest():
    """AAA: 4 NUTS3 regions in 2 TL2 regions; BBB: 2 admin-1 regions; CCC: whole; DDD: 2 counties of one state."""
    parts = [square_regions("AAA", 4, "nuts3"), square_regions("BBB", 2, "admin1", x0=4),
             square_regions("CCC", 1, "country", x0=6), square_regions("DDD", 2, "county", x0=7).assign(parent_id="FIPS:01")]
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=4326)


def test_continent_id_is_a_slug_of_the_natural_earth_name():
    assert levels.continent_id(pd.Series(["North America", "Oceania"])).tolist() == ["CONT:north-america", "CONT:oceania"]


def test_hierarchy_gives_every_finest_region_a_level_and_parent():
    r = levels.hierarchy(finest(), TL2_OF, CONTINENT).set_index("region_id")
    assert r["level_no"].groupby(r["iso3"]).first().to_dict() == {"AAA": 3, "BBB": 2, "CCC": 1, "DDD": 3}
    assert r.loc[["T:AAA0", "T:AAA3", "T:BBB1", "T:CCC0", "T:DDD0"], "parent_id"].tolist() == [
        "OECD:A1", "OECD:A2", "ISO3:BBB", "CONT:asia", "FIPS:01"]  # NUTS3 from the table, county keeps its state


def test_hierarchy_fails_when_a_level_3_region_has_no_parent():
    with pytest.raises(AssertionError, match="T:AAA3"):
        levels.hierarchy(finest(), TL2_OF.iloc[:3], CONTINENT)


GDP = {"T:AAA0": 10.0, "T:AAA1": 20.0, "T:AAA2": 30.0, "T:AAA3": 30.0, "T:BBB0": 1.0, "T:BBB1": 3.0, "T:CCC0": 50.0,
       "T:DDD0": 0.2, "T:DDD1": 7.8}
NATIONAL = {"AAA": 1000.0, "BBB": 400.0, "CCC": 50.0, "DDD": 80.0}
NATIONAL_POP = {"AAA": 9500.0, "DDD": 800.0}  # the regions of AAA sum to 9000, DDD's populated region has 780; BBB has none
NAMES = pd.Series({"OECD:A1": "A one", "OECD:A2": "A two", "FIPS:01": "State", "ISO3:AAA": "Aland", "ISO3:BBB": "Bland",
                   "ISO3:DDD": "Dland", "CONT:europe": "Europe", "CONT:asia": "Asia"})


def synthetic():
    """The `finest` world through the real steps: AAA has 10% extra-regio GDP; no population in T:BBB1 (75% of BBB's
    GDP) and T:DDD0 (2.5% of DDD's); the disputed region is a square north of AAA."""
    reg = finest()
    rows = [(r, r[2:5], "gdp", 2024, v) for r, v in GDP.items()] + [("X", "AAA", "gdp_extra", 2024, 10.0)]
    rows += [(r, r[2:5], "pop", 2024, 100 * v) for r, v in GDP.items() if r not in ("T:BBB1", "T:DDD0")]
    rows += [(r, r[2:5], "area_km2", 2020, 5.0) for r in GDP]
    nat = observations([(f"ISO3:{k}", k, "gdp", 2024, v) for k, v in NATIONAL.items()]
                       + [(f"ISO3:{k}", k, "pop", 2023, v) for k, v in NATIONAL_POP.items()])
    ind, unallocated = indicators.compute(reg.set_index("region_id")["level"], observations(rows), nat, 2024)
    reg, ind = levels.aggregate(levels.hierarchy(reg, TL2_OF, CONTINENT), ind, NAMES, CONTINENT, indicators.national_population(nat, 2024))
    return *levels.add_disputed(reg, ind, box(0, 1, 1, 2)), unallocated


def built():
    """The real build outputs (skipped before the first build)."""
    if not (PROCESSED / "regions.geoparquet").exists():
        pytest.skip("no build outputs")
    return (gpd.read_parquet(PROCESSED / "regions.geoparquet"), pd.read_parquet(PROCESSED / "indicators.parquet").set_index("region_id"),
            pd.read_parquet(PROCESSED / "unallocated.parquet")["unallocated_gdp_usd"])


@pytest.fixture(scope="module", params=[synthetic, built])
def world(request):
    return request.param()


def test_cover_is_the_level_plus_coarser_regions_with_nothing_finer_plus_the_disputed_region():
    _, ind, _ = synthetic()
    assert [sorted(levels.cover(ind, no).index) for no in range(4)] == [
        ["CONT:asia", "CONT:europe", "DISPUTED:crimea"],
        ["DISPUTED:crimea", "ISO3:AAA", "ISO3:BBB", "ISO3:DDD", "T:CCC0"],
        ["DISPUTED:crimea", "FIPS:01", "OECD:A1", "OECD:A2", "T:BBB0", "T:BBB1", "T:CCC0"],
        ["DISPUTED:crimea"] + sorted(GDP)]


def test_every_cover_sums_to_the_same_national_and_world_gdp_and_area(world):
    _, ind, _ = world
    for col in ("gdp_usd", "area_km2"):
        finest_sum = levels.cover(ind, 3).groupby("iso3")[col].sum()
        for no in (1, 2):
            pd.testing.assert_series_equal(levels.cover(ind, no).groupby("iso3")[col].sum(), finest_sum, rtol=1e-9)
        assert levels.cover(ind, 0)[col].sum() == pytest.approx(finest_sum.sum(), rel=1e-9)  # the same world total


def test_levels_sum_to_the_national_totals_and_continents_to_the_world_minus_unallocated():
    _, ind, unallocated = synthetic()
    for no in (1, 2, 3):
        assert (levels.cover(ind, no).groupby("iso3")["gdp_usd"].sum() + unallocated).to_dict() == pytest.approx(NATIONAL)
    assert unallocated["AAA"] == pytest.approx(100.0)
    assert ind.loc[ind["level_no"] == 0, "gdp_usd"].sum() == pytest.approx(sum(NATIONAL.values()) - unallocated.sum())


def test_built_world_has_six_continents_none_of_them_open_ocean():
    reg, _, _ = built()
    assert sorted(reg.loc[reg["level_no"] == 0, "region_id"]) == [
        "CONT:africa", "CONT:asia", "CONT:europe", "CONT:north-america", "CONT:oceania", "CONT:south-america"]
    assert reg.set_index("region_id").loc[["ISO3:MDV", "ISO3:MUS", "ISO3:SYC"], "parent_id"].tolist() == ["CONT:asia", "CONT:africa", "CONT:africa"]


def test_every_region_has_a_parent_chain_to_a_continent_with_decreasing_level(world):
    r = world[0].set_index("region_id")
    kids = r[r["level_no"] > 0]
    assert r.index.is_unique and r.loc[r["level_no"] == 0, "parent_id"].isna().all() and kids["parent_id"].isin(r.index).all()
    assert (r.loc[kids["parent_id"], "level_no"].values < kids["level_no"].values).all()  # so every chain ends at level 0
    assert set(r["level_no"]) == {0, 1, 2, 3} and r.index[r["level_no"] == 0].str.startswith("CONT:").all()


def test_every_shape_is_a_polygon_or_multipolygon(world):
    assert world[0].geom_type.isin(["Polygon", "MultiPolygon"]).all()  # a dissolve may leave degenerate lines


def test_polygons_drops_the_lines_a_dissolve_leaves():
    mixed = GeometryCollection([box(0, 0, 1, 1), LineString([(1, 1), (2, 2)]), MultiPolygon([box(3, 0, 4, 1), box(5, 0, 6, 1)])])
    assert boundaries.polygons(mixed).geom_type == "MultiPolygon" and boundaries.polygons(mixed).area == 3
    assert boundaries.polygons(GeometryCollection([box(0, 0, 1, 1), LineString([(1, 1), (2, 2)])])).geom_type == "Polygon"


def test_dissolved_parent_area_equals_the_sum_of_its_children(world):
    r = world[0].assign(km2=lambda d: boundaries.area_km2(d)).loc[lambda d: d["level"] != "disputed"]
    parents = r.set_index("region_id").loc[lambda d: d.index.isin(r["parent_id"]), "km2"]
    # 2e-3: Chinese provinces with prefectures (COD-AB shapes) overlap their Natural Earth neighbours by 0.15% of China
    pd.testing.assert_series_equal(r.groupby("parent_id")["km2"].sum(), parents, rtol=2e-3, check_names=False, check_like=True)


def test_population_and_ratios_of_level_2_parents(world):
    reg, ind, _ = world
    ind = ind.drop(index=reg.loc[reg["level"].isin(levels.SUB), ["region_id", "parent_id"]].stack())  # those parents keep their own population
    finest, below = ind[~ind.index.isin(ind["parent_id"])], []
    above = finest["parent_id"]
    while above.notna().any():  # every (finest region, ancestor) pair
        below.append(finest.assign(above=above)[above.notna()])
        above = above.map(ind["parent_id"])
    below = pd.concat(below)
    below = below[below["above"].map(ind["level_no"]) == 2]
    agg, n = ind.loc[sorted(set(below["above"]))], below.groupby("above")
    counted = below[below["pop"].notna()].groupby("above")[["gdp_usd", "pop", "area_km2"]].sum().reindex(agg.index).fillna(0)
    has = counted["gdp_usd"] >= 0.95 * agg["gdp_usd"]
    assert agg.loc[~has, ["pop", "pop_year", "pop_source", "gdp_per_capita", "pop_density"]].isna().all(axis=None)
    pos = counted.where(counted > 0)  # Svalbard has a population of 0
    for col, expected in (("pop", counted["pop"]), ("gdp_per_capita", counted["gdp_usd"] / pos["pop"]),
                          ("pop_density", counted["pop"] / pos["area_km2"])):
        pd.testing.assert_series_equal(agg.loc[has, col], expected[has], check_names=False)
    pd.testing.assert_series_equal(agg["gdp_per_km2"], agg["gdp_usd"] / agg["area_km2"], check_names=False)
    partial = agg["flags"].map(lambda f: "partial_population" in f)
    assert partial.eq(has & (n["pop"].count() < n.size())).all() and (has & ~partial).any()
    assert agg["flags"].map(lambda f: f[0] == "aggregated").all()


@pytest.mark.parametrize("make", [synthetic, built])
def test_countries_have_the_national_population_and_continents_the_sum_of_their_countries(make):
    _, ind, _ = make()
    national = (indicators.national_population(build.national_data()) if make is built
                else pd.DataFrame({"value": NATIONAL_POP, "year": 2023, "source_id": "test_src"}).rename(index="ISO3:{}".format))
    c = ind[ind["level_no"] == 1].join(national.add_prefix("nat_"), how="inner")
    assert c["flags"].map(lambda f: "aggregated" in f).any() and c["flags"].map(lambda f: "partial_population" not in f).all()
    assert c["pop"].eq(c["nat_value"]).all() and c["pop_year"].eq(c["nat_year"]).all() and c["pop_source"].eq(c["nat_source_id"]).all()
    pd.testing.assert_series_equal(c["gdp_per_capita"], c["gdp_usd"] / c["pop"], check_names=False)
    countries = ind[ind["level_no"] == 1].groupby("parent_id")
    continents = ind[ind["level_no"] == 0]
    pd.testing.assert_series_equal(continents["pop"], countries["pop"].sum(), check_names=False, check_index_type=False)
    assert continents["flags"].map(lambda f: "partial_population" in f).eq(countries["pop"].count() < countries.size()).all()


def test_synthetic_world_values():
    reg, ind, _ = synthetic()
    assert ind.loc["OECD:A1", ["gdp_usd", "pop", "area_km2", "gdp_share", "iso3", "name"]].tolist() == [
        pytest.approx(300.0), 3000.0, 10.0, pytest.approx(0.3), "AAA", "A one"]
    assert pd.isna(ind.loc["ISO3:BBB", "pop"]) and ind.loc["ISO3:BBB", "gdp_usd"] == 400  # T:BBB1 has no population
    assert pd.isna(ind.loc["CONT:europe", ["iso3", "gdp_share"]]).all()
    area = ind["area_km2"]
    for rid, gdp, counted_gdp, pop, counted_area, flags in (  # T:DDD0 (gdp 2, area 5) and all of BBB (gdp 400) have no population
            ("FIPS:01", 80.0, 78.0, 780.0, area["FIPS:01"] - 5, ["partial_population"]),
            ("ISO3:DDD", 80.0, 80.0, 800.0, area["ISO3:DDD"], []), ("ISO3:AAA", 900.0, 900.0, 9500.0, area["ISO3:AAA"], []),
            ("CONT:asia", 130.0, 130.0, 5800.0, area["CONT:asia"], []),
            ("CONT:europe", 1300.0, 900.0, 9500.0, area["ISO3:AAA"], ["partial_population"])):
        assert ind.loc[rid, ["gdp_usd", "pop", "gdp_per_capita", "pop_density"]].tolist() == pytest.approx(
            [gdp, pop, counted_gdp / pop, pop / counted_area])
        assert ind.loc[rid, "flags"] == ["aggregated"] + flags
    assert ind.loc["ISO3:DDD", ["pop_year", "pop_source"]].tolist() == [2023, "test_src"]
    assert reg.set_index("region_id").loc["ISO3:AAA", ["level", "level_no", "parent_id"]].tolist() == ["country", 1, "CONT:europe"]
    assert reg.set_index("region_id").geometry["CONT:europe"].bounds == (0, 0, 6, 1)


def test_disputed_region_is_drawn_but_in_no_total(world):
    reg, ind, _ = world
    r, row = reg.set_index("region_id"), ind.loc["DISPUTED:crimea"]
    assert row[["level_no", "parent_id", "name"]].tolist() == [2, "CONT:europe", "Crimea (disputed)"] and list(row["flags"]) == ["disputed"]
    assert row.drop(["year", "flags", "level_no", "parent_id", "name", "iso2"], errors="ignore").isna().all()
    assert "DISPUTED:crimea" not in set(r["parent_id"]) and all("DISPUTED:crimea" in levels.cover(ind, no).index for no in range(4))
    shape = r.geometry["DISPUTED:crimea"]
    others = r[(r.index != "DISPUTED:crimea") & r.intersects(shape)]
    assert shape.area > 0 and all(g.intersection(shape).area < 1e-3 * shape.area for g in others.geometry)  # in no dissolve either


def test_sum_children_years_sources_and_population_of_the_regions_that_hold_95_percent_of_gdp():
    kids = pd.DataFrame({"parent_id": list("ppqqrr"), "iso3": list("AAABCC"), "year": 2024, "gdp_share": [0.2, 0.3, 0.5, 1.0, 0.96, 0.04],
                         "gdp_usd": [2.0, 3.0, None, 7.0, 96.0, 4.0], "pop": [10.0, 30.0, 5.0, None, 10.0, None],
                         "area_km2": [1.0, 4.0, 2.0, 2.0, 2.0, 6.0], "gdp_year": [2024, 2019, 2024, 2024, 2024, 2024],
                         "pop_year": [2020, 2023, 2024, None, 2021, None], "area_year": 2020, "gdp_source": list("ssstss"),
                         "pop_source": ["s", "t", "s", None, "s", None], "area_source": "g",
                         "flags": [["estimate"], [], ["wikidata"], ["whole_country"], [], []]})
    out = levels.sum_children(kids)
    assert out.loc["p", ["gdp_usd", "pop", "area_km2", "gdp_year", "pop_year", "gdp_source", "area_source", "iso3", "gdp_share"]].tolist() == [
        5.0, 40.0, 5.0, 2019, 2020, "s", "g", "A", 0.5]
    assert pd.isna(out.loc["p", "pop_source"]) and out.loc["p", ["gdp_per_km2", "gdp_per_capita", "pop_density"]].tolist() == [1.0, 0.125, 8.0]
    assert out.loc["q", "gdp_usd"] == 7.0 and out.loc["q", ["pop", "pop_year", "pop_source", "gdp_source", "iso3", "gdp_share"]].isna().all()
    assert out.loc["r", ["gdp_usd", "pop", "pop_year", "gdp_per_km2", "gdp_per_capita", "pop_density"]].tolist() == [100.0, 10.0, 2021, 12.5, 9.6, 5.0]
    assert out["flags"].tolist() == [["aggregated", "contains_estimate"], ["aggregated", "contains_wikidata"], ["aggregated", "partial_population"]]


def test_summary_flags_report_only_the_summarised_child_flags():
    assert levels.summary_flags([["area_computed", "gdp_year_offset"], []]) == ["aggregated"]
    assert levels.summary_flags([["wikidata"], ["estimate", "wikipedia_secondary"], ["whole_country"]]) == [
        "aggregated", "contains_estimate", "contains_wikipedia_secondary", "contains_wikidata"]


def test_built_indicators_json_carries_every_level_within_the_size_budget():
    reg, ind, _ = built()
    raw = (WEB_PUBLIC / "indicators.json").read_bytes()
    doc = json.loads(raw)
    rows = pd.DataFrame.from_dict(doc["regions"], orient="index", columns=doc["meta"]["columns"])
    assert doc["meta"]["columns"] == export.COLUMNS and set(rows.index) == set(reg["region_id"]) and len(gzip.compress(raw)) < 2e6
    assert rows["level_no"].to_dict() == ind["level_no"].to_dict() and rows["name"].str.len().gt(0).all()
    assert rows["parent_id"].isna().eq(rows["level_no"] == 0).all() and rows["parent_id"].dropna().isin(rows.index).all()
    assert rows["iso2"].str.fullmatch("[A-Z]{2}").eq(~rows.index.str.startswith(("CONT:", "DISPUTED:"))).all()
    assert rows.loc[rows["iso2"] == "", "iso2"].size == 7 and rows.loc[["ISO3:DEU", "OECD:DE2", "NUTS2024:DE212"], "iso2"].tolist() == ["DE"] * 3
