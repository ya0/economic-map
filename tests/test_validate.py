import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from econviz import validate
from conftest import square_regions


def table(**cols):
    return pd.DataFrame(cols, index=["a", "b"])


def test_coverage_passes_when_regions_tile_the_country_and_fails_otherwise():
    regions = square_regions(n=2)
    country = box(0, 0, 2, 1)
    assert validate.coverage(regions, country) == []
    assert validate.coverage(regions.iloc[:1], country)  # half the country missing
    assert validate.coverage(regions.iloc[:1], country, tol=0.6) == []  # explicit waiver tolerance


def test_overlaps_detects_double_covered_area_but_not_shared_borders():
    assert validate.overlaps(square_regions(n=3)) == []
    a, b = square_regions(n=2), square_regions(n=2, x0=0.5)
    assert validate.overlaps(pd.concat([a.iloc[:1], b.iloc[:1]], ignore_index=True))  # 50% overlap


def test_gdp_sum_must_equal_national_including_unallocated():
    ind = table(gdp_usd=[60.0, 30.0])
    assert validate.gdp_sum(ind, 10.0, 100.0) == []
    assert validate.gdp_sum(ind, 0.0, 100.0)


def test_population_within_tolerance_and_blank_pop_is_allowed():
    assert validate.population(table(pop=[50.0, 48.0]), 100.0) == []
    assert validate.population(table(pop=[50.0, 30.0]), 100.0)
    assert validate.population(table(pop=[50.0, np.nan]), 100.0) == []
    assert validate.population(table(pop=[50.0, 50.0]), float("nan")) == []


def test_positive_area_flags_zero_negative_and_missing():
    assert validate.positive_area(table(area_km2=[1.0, 2.0])) == []
    for bad in (0.0, -1.0, np.nan):
        assert validate.positive_area(table(area_km2=[1.0, bad]))


def test_per_capita_outliers_use_range_and_whitelist():
    ind = table(gdp_per_capita=[100.0, 1.0])  # b is 0.01x national
    assert validate.per_capita_outliers(ind, 100.0)
    assert validate.per_capita_outliers(ind, 100.0, whitelist={"b"}) == []
    assert validate.per_capita_outliers(table(gdp_per_capita=[100.0, 6000.0]), 100.0)  # 60x
    assert validate.per_capita_outliers(table(gdp_per_capita=[100.0, 4000.0]), 100.0) == []  # 40x


def test_provenance_requires_source_and_year_for_every_value():
    ok = table(gdp_usd=[1.0, 2.0], gdp_source=["s", "s"], gdp_year=[2022, 2022], pop=[1.0, np.nan], pop_source=["s", None],
               pop_year=[2022, np.nan], area_km2=[1.0, 1.0], area_source=["s", "s"], area_year=[2020, 2020])
    assert validate.provenance(ok) == []
    assert validate.provenance(ok.assign(gdp_source=["s", None]))
    assert validate.provenance(ok.assign(area_year=[2020, np.nan]))


def units(n=20):
    pop = pd.Series(np.geomspace(1e4, 1e7, n), index=[f"r{i}" for i in range(n)])  # neighbours differ by far less than 3x
    return pop, pop * 1.1  # the reference differs a little (other vintage)


def test_swapped_units_accepts_matching_and_noisy_populations():
    pop, ref = units()
    assert validate.swapped_units(pop, ref) == []
    assert validate.swapped_units(pop.mul(np.random.default_rng(0).uniform(0.7, 1.4, len(pop))), ref) == []


@pytest.mark.parametrize("swaps,fails", [(0, False), (5, False), (6, True), (10, True)])
def test_swapped_units_fails_when_more_than_a_quarter_of_units_are_exchanged(swaps, fails):
    pop, ref = units(40)  # 40 units spanning 3 decades: the exchanged pairs sit 20 positions apart (>3x)
    pop = pop.copy()
    for i in range(swaps):  # each swap puts 2 of 40 units (5%) off: 10 units = 25% is tolerated, 12 are not
        a, b = pop.index[i], pop.index[i + 20]
        pop[a], pop[b] = pop[b], pop[a]
    assert bool(validate.swapped_units(pop, ref)) is fails


def test_swapped_units_ignores_tiny_samples_and_missing_or_nonpositive_values():
    few = pd.Series({f"r{i}": 1.0 for i in range(7)})
    assert validate.swapped_units(few, few * 100) == []  # only 7 units compared
    pop, ref = units(10)
    assert validate.swapped_units(pop.mask(pop.index.isin(["r0", "r1", "r2"]), 0.0), ref.mask(ref.index.isin(["r3", "r4"]))) == []
