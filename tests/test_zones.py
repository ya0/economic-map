"""Zone rule, unit population and the zone layer (offline fixtures)."""
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from econviz import admin1pop, indicators, levels, zones
from econviz.export import COLUMNS


def units(pops, areas=None, iso3="AAA"):
    """Side-by-side boxes (1 degree tall, `areas`/1000 degrees wide... only the ratios matter): region_id, iso3, name, iso code, shape."""
    n = len(pops)
    w = [1.0] * n if areas is None else areas
    x = [sum(w[:i]) for i in range(n)]
    return gpd.GeoDataFrame({"region_id": [f"NE1:{iso3}-{i}" for i in range(n)], "iso3": iso3, "name": [f"Unit {i}" for i in range(n)],
                             "iso_3166_2": [f"AA-{i}" for i in range(n)],
                             "geometry": [box(x[i], 0, x[i] + w[i], 1) for i in range(n)]}, geometry="geometry", crs=4326)


def pop_rows(u, pops, year=2020, source="src", flags=""):
    return pd.DataFrame({"region_id": u["region_id"], "iso3": u["iso3"], "value": pops, "year": year, "source_id": source, "flags": flags})


# six units of equal area: densities 100, 40, 10, 4, 1, 0.5 (mean 25.9)
SIX = [100.0, 40.0, 10.0, 4.0, 1.0, 0.5]


def test_rule_groups_by_density_against_the_country_mean():
    # mean density 100/64 = 1.56: dense above 3.1, sparse below 0.47; no unit holds 15% of the people
    t = pd.DataFrame({"pop": [14, 14, 14, 14, 14, 14, 9, 4, 2, 1.0], "area_km2": [1, 1, 1, 10, 10, 10, 10, 10, 10, 10.0]}, index=list("abcdefghij"))
    g = zones.groups(t)
    assert g.tolist() == ["dense"] * 3 + ["middle"] * 4 + ["sparse"] * 3


def test_unit_with_15_percent_of_the_people_stays_alone_at_most_two():
    t = pd.DataFrame({"pop": [40.0, 30.0, 20.0, 5.0, 3.0, 2.0], "area_km2": 10.0}, index=list("abcdef"))
    g = zones.groups(t)
    assert g["a"] == "a" and g["b"] == "b" and g["c"] in zones.NAME  # c holds 20% but only the two largest stay alone


def test_override_beats_the_rule():
    t = pd.DataFrame({"pop": [60.0, 6.0, 5.0, 4.0, 1.0], "area_km2": 10.0}, index=list("abcde"))
    assert zones.groups(t)["e"] == "sparse"
    assert zones.groups(t, {"e": "middle", "d": "alone", "zz": "dense"}).loc[["e", "d"]].tolist() == ["middle", "d"]


def ready_layer(pops=SIX, areas=None, **kw):
    u = units(pops, areas)
    return u, zones.layer(u, pop_rows(u, pops), pd.Series({"AAA": "Aland"}), {"AAA"}, {}, 2024, **kw)


def test_layer_ids_names_and_the_standard_observation_table():
    u, (reg, obs) = ready_layer(pops=[500.0, 100.0, 40.0, 4.0, 1.0, 0.5])
    assert reg["region_id"].tolist() == [f"ZONE:AAA-{i}" for i in range(1, len(reg) + 1)]
    assert set(reg["level"]) == {"zone"} and reg["name"].str.startswith("Aland: ").all()
    assert "Aland: dense core" in set(reg["name"]) or "Aland: Unit 0" in set(reg["name"])
    assert set(obs["variable"]) == {"gdp", "pop", "area_km2"}
    g = obs[obs["variable"] == "gdp"]
    assert set(g["note"]) == {"pop_share"} and g["value"].sum() == pytest.approx(sum([500.0, 100.0, 40.0, 4.0, 1.0, 0.5]))
    assert reg.geometry.union_all().equals_exact(u.geometry.union_all(), 1e-9) or reg.geometry.union_all().symmetric_difference(u.geometry.union_all()).area < 1e-9


def test_ids_are_deterministic():
    a = ready_layer()[1][0]
    b = ready_layer()[1][0]
    assert a["region_id"].tolist() == b["region_id"].tolist() and a["name"].tolist() == b["name"].tolist()


def test_gdp_density_follows_population_density_and_per_capita_is_national():
    u, (reg, obs) = ready_layer(pops=[500.0, 100.0, 40.0, 4.0, 1.0, 0.5])
    tab = indicators.split_country(obs, 1e9, 2024)[0]
    tab = indicators.ratios(tab.rename(columns={}).assign(gdp_usd=tab["gdp_usd"]))
    assert tab["gdp_usd"].sum() == pytest.approx(1e9)
    order = lambda c: tab[c].sort_values().index.tolist()
    assert order("gdp_per_km2") == order("pop_density")
    assert tab["gdp_per_capita"].nunique() == 1 or (tab["gdp_per_capita"].max() / tab["gdp_per_capita"].min() - 1) < 1e-9


def test_not_ready_country_and_one_group_country_stay_whole():
    u = units(SIX)
    reg, obs = zones.layer(u, pop_rows(u, SIX), pd.Series({"AAA": "A"}), set(), {}, 2024)
    assert reg.empty and obs.empty
    flat = units([10.0] * 8)
    reg, _ = zones.layer(flat, pop_rows(flat, [10.0] * 8), pd.Series({"AAA": "A"}), {"AAA"}, {}, 2024)
    assert reg.empty


def test_country_with_a_zone_above_70_percent_of_the_land_stays_whole_unless_listed():
    areas = [1, 1, 1, 1, 1, 20]
    for iso3, whole in (("AAA", True), ("DZA", False)):
        u = units(SIX, areas, iso3=iso3)
        reg, _ = zones.layer(u, pop_rows(u, SIX), pd.Series({iso3: "A"}), {iso3}, {}, 2024)
        assert reg.empty == whole


def test_coverage_arithmetic_and_readiness():
    u = pd.concat([units(SIX, iso3="AAA"), units(SIX, iso3="BBB"), units([5.0, 5.0, 5.0], iso3="CCC")], ignore_index=True)
    p = pop_rows(u, [*SIX, *SIX, 5.0, 5.0, 5.0])
    p = p[~p["region_id"].isin(["NE1:BBB-0", "NE1:BBB-1"])]  # BBB lacks its two biggest units
    u.loc[u["region_id"] == "NE1:AAA-5", "iso_3166_2"] = "AA"  # no valid code
    c = zones.coverage(u, p, pd.Series({"AAA": 155.5, "BBB": 155.5, "CCC": 15.0}), pd.Series(dtype=str)).set_index("iso3")
    assert c.loc["AAA", ["units", "with_pop", "no_code", "share", "ready"]].tolist() == [6, 6, 1, 1.0, True]
    assert c.loc["BBB", "with_pop"] == 4 and c.loc["BBB", "share"] == pytest.approx(15.5 / 155.5, abs=1e-3) and not c.loc["BBB", "ready"]
    assert not c.loc["CCC", "ready"]  # fewer than 4 units


def test_negligible_unit_without_a_value_counts_as_zero_people():
    u = units([100.0, 50.0, 20.0, 5.0, 0.0], areas=[1.0, 1.0, 1.0, 1.0, 1e-4])
    t = zones.unit_table(u, pop_rows(u.iloc[:4], [100.0, 50.0, 20.0, 5.0]))
    assert t["pop"].tolist() == [100.0, 50.0, 20.0, 5.0, 0.0]


def test_unit_population_manual_beats_wikidata_and_shared_codes_are_unusable():
    u = units([1, 1, 1, 1])
    u.loc[2:, "iso_3166_2"] = "AA-9"  # units 2 and 3 share a code
    wd = pd.DataFrame({"iso": [f"AA-{i}" for i in range(4)] + ["AA-9"], "item": [f"Q{i}" for i in range(5)],
                       "pop": [10.0, 20.0, 30.0, 40.0, 50.0], "pop_year": 2022, "area_km2": 12300.0})
    km2 = 12363.0  # one square degree at the equator
    wd["area_km2"] = km2
    manual = pd.DataFrame({"region_id": ["NE1:AAA-0", "NE1:AAA-3"], "year": [2021, 2005], "value": [111.0, 333.0],
                           "source_id": "m", "url": "u", "note": "n", "flags": ""})
    got = admin1pop.population(u, manual, 2024, load=lambda p: wd).set_index("region_id")
    assert got.loc["NE1:AAA-0", ["value", "source_id"]].tolist() == [111.0, "m"]  # manual (in the window) over Wikidata
    assert got.loc["NE1:AAA-1", ["value", "flags"]].tolist() == [20.0, "wikidata"]
    assert "NE1:AAA-2" not in got.index and "NE1:AAA-3" not in got.index  # shared code; manual row outside the window


def test_waived_country_keeps_its_old_census_and_others_do_not():
    old = lambda u: pd.DataFrame({"region_id": u["region_id"], "year": 2008, "value": 5.0, "source_id": "m", "url": "u", "note": "n", "flags": "pop_year_offset"})
    empty = pd.DataFrame({"iso": ["ZZ-0"], "item": ["Q0"], "pop": [1.0], "pop_year": 2022, "area_km2": 1.0})
    for iso3, kept in (("DZA", 2), ("AAA", 0)):  # data/reference/pop_year_waivers.csv lists DZA
        u = units([1, 1, 1], iso3=iso3)
        got = admin1pop.population(u, old(u.iloc[:2]), 2024, load=lambda p: empty)
        assert len(got) == kept


def test_contract_zone_level_and_flag():
    assert levels.LEVEL_NO["zone"] == 2 and "pop_share" in levels.SUMMARISED
    assert COLUMNS[:18] == ["gdp_usd", "pop", "area_km2", "gdp_per_km2", "gdp_per_capita", "pop_density", "gdp_year", "pop_year", "area_year",
                            "gdp_source", "pop_source", "area_source", "flags", "level_no", "parent_id", "name", "iso2", "pop_raw"]


@pytest.mark.parametrize("iso3", ["ETH", "IRQ", "KEN", "MLI", "PNG", "SAU", "TCD"])
def test_run_4c_manual_rows_sum_to_the_check_figure_in_their_note(iso3):
    import re
    from econviz.load import manual
    t = manual.load()
    t = t[t["region_id"].str.startswith(f"NE1:{iso3}-")]
    assert len(t) >= 8 and t["year"].between(2016, 2024).all()
    check = {int(m.group(1).replace(",", "")) for n in t["note"] for m in [re.search(r"sum(?: to)? ([\d,]{7,})", n)] if m}
    assert check == {int(t["value"].sum())}
