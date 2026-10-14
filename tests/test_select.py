import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from econviz import select
from conftest import observations, square_regions


def country_frame(iso3="AAA", width=2.0):
    return gpd.GeoDataFrame({"region_id": f"ISO3:{iso3}", "iso3": iso3, "name": iso3, "level": "country", "parent_id": None,
                             "boundary_source_id": "ne", "boundary_vintage": "ne", "geometry": [box(0, 0, width, 1)]},
                            geometry="geometry", crs=4326)


def layer(n=2, gdp=(1.0, 2.0), pop=(10.0, 10.0), iso3="AAA", level="admin1"):
    regions = square_regions(iso3, n, level)
    rows = [(f"T:{iso3}{i}", iso3, "gdp", 2022, gdp[i]) for i in range(n)] + [(f"T:{iso3}{i}", iso3, "pop", 2022, pop[i]) for i in range(n)]
    return regions, observations(rows)


def national(iso3="AAA", pop=20.0):
    return observations([(f"ISO3:{iso3}", iso3, "gdp", 2022, 100.0), (f"ISO3:{iso3}", iso3, "pop", 2022, pop),
                         (f"ISO3:{iso3}", iso3, "area_km2", 2022, 1.0)])


def test_first_passing_layer_wins_and_failures_are_logged():
    bad = (square_regions("AAA", 1), observations([("T:AAA0", "AAA", "gdp", 2022, 1.0)]))  # single region
    good = layer()
    regions, obs, log = select.choose({"bad": bad, "good": good, "later": layer()}, country_frame(), national(), {})
    assert log.iloc[0]["layer"] == "good" and "fewer than 2" in log.iloc[0]["rejected"]["bad"]
    assert sorted(regions["region_id"]) == ["T:AAA0", "T:AAA1"] and set(obs["region_id"]) == {"T:AAA0", "T:AAA1"}


def test_incomplete_gdp_or_geometry_coverage_falls_back_to_whole_country():
    sparse = layer(n=2, gdp=(1.0, 2.0))
    sparse = (sparse[0], sparse[1][sparse[1]["region_id"] != "T:AAA1"])  # GDP for 1 of 2 regions
    regions, _, log = select.choose({"sparse": sparse}, country_frame(), national(), {})
    assert log.iloc[0]["layer"] == "country" and "GDP coverage" in log.iloc[0]["rejected"]["sparse"]
    assert regions["region_id"].tolist() == ["ISO3:AAA"]
    # regions tile only half of a wider country: rejected unless waived
    _, _, log = select.choose({"l": layer()}, country_frame(width=4.0), national(), {})
    assert log.iloc[0]["layer"] == "country"
    _, _, log = select.choose({"l": layer()}, country_frame(width=4.0), national(), {"AAA": 0.6})
    assert log.iloc[0]["layer"] == "l"


def test_population_far_from_the_national_total_is_kept_for_scaling():
    _, obs, log = select.choose({"l": layer(pop=(10.0, 10.0))}, country_frame(), national(pop=100.0), {})
    assert log.iloc[0]["layer"] == "l" and "pop" in set(obs["variable"])


def test_gdp_of_regions_without_geometry_rejects_the_layer():
    """A region with GDP but no boundary (missing crosswalk row) would silently hand its share to the others."""
    regions, obs = layer()
    lost = observations([("T:AAA9", "AAA", "gdp", 2022, 5.0)])  # 5 of 8 GDP units have no geometry
    _, _, log = select.choose({"l": (regions, pd.concat([obs, lost], ignore_index=True))}, country_frame(), national(), {})
    assert log.iloc[0]["layer"] == "country" and "without geometry" in log.iloc[0]["rejected"]["l"]


def test_countries_without_a_layer_are_kept_whole_and_split_ones_are_not_duplicated():
    countries = pd.concat([country_frame("AAA"), country_frame("BBB")], ignore_index=True)
    nat = pd.concat([national("AAA"), national("BBB")], ignore_index=True)
    regions, obs, log = select.choose({"l": layer(iso3="AAA")}, countries, nat, {})
    assert sorted(regions["region_id"]) == ["ISO3:BBB", "T:AAA0", "T:AAA1"]
    assert log.set_index("iso3")["layer"].to_dict() == {"AAA": "l", "BBB": "country"}
    assert "ISO3:AAA" not in set(obs["region_id"])


def fresh_layer(year, prefix="W"):
    regions = square_regions("AAA", 2).assign(region_id=[f"{prefix}0", f"{prefix}1"])
    return regions, observations([(f"{prefix}{i}", "AAA", "gdp", year, 1.0 + i) for i in range(2)])


def test_national_layer_replaces_a_usable_layer_only_if_two_years_newer():
    old = layer()  # GDP 2022
    for year, expected in ((2024, "wikipedia"), (2023, "dose"), (2022, "dose")):
        _, _, log = select.choose({"dose": old, "wikipedia": fresh_layer(year)}, country_frame(), national(), {}, 2024)
        assert log.iloc[0]["layer"] == expected, year
    assert "years newer" in log.iloc[0]["rejected"]["wikipedia"]


def test_a_national_layer_never_displaces_a_non_national_layer_and_may_come_first():
    regions, obs, log = select.choose({"wikipedia": fresh_layer(2024), "dose": layer()}, country_frame(), national(), {}, 2024)
    assert log.iloc[0]["layer"] == "wikipedia" and "dose" not in log.iloc[0]["rejected"]
    assert set(regions["region_id"]) == {"W0", "W1"}


def test_layer_with_swapped_population_is_rejected_against_the_reference():
    n = 10
    regions = square_regions("AAA", n)
    pops = [10.0 ** (i / 2) for i in range(n)]
    obs = observations([(f"T:AAA{i}", "AAA", v, 2022, x) for i in range(n) for v, x in (("gdp", 1.0), ("pop", pops[i]))])
    nat = national(pop=sum(pops))
    ref = pd.Series({f"T:AAA{i}": p for i, p in enumerate(pops)})
    assert select.choose({"l": (regions, obs)}, country_frame(width=n), nat, {}, 2024, ref)[2].iloc[0]["layer"] == "l"
    swapped = ref.set_axis([f"T:AAA{i}" for i in reversed(range(n))])
    log = select.choose({"l": (regions, obs)}, country_frame(width=n), nat, {}, 2024, swapped)[2]
    assert log.iloc[0]["layer"] == "country" and "Wikidata" in log.iloc[0]["rejected"]["l"]
