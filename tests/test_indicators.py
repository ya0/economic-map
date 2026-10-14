import numpy as np
import pandas as pd
import pytest

from econviz import indicators as ind
from conftest import observations


def test_nearest_year_prefers_exact_then_nearest_earlier_and_respects_window():
    assert ind.nearest_year([2020, 2022, 2024], 2022) == 2022
    assert ind.nearest_year([2020, 2021, 2023], 2022) == 2021  # later years are never used
    assert ind.nearest_year([2023, 2030], 2022) is None and ind.nearest_year([2010], 2022) is None
    assert ind.nearest_year([2016], 2022, max_offset=3) is None and ind.nearest_year([2019], 2022, max_offset=3) == 2019


def test_shared_year_skips_years_with_sparse_coverage():
    rows = [(f"r{i}", "A", "gdp", 2022, 1.0) for i in range(3)] + [(f"r{i}", "A", "gdp", 2021, 1.0) for i in range(20)]
    assert ind.shared_year(observations(rows)) == 2021  # 2022 covers 3 of 20 regions
    rows = [(f"r{i}", "A", "gdp", 2022, 1.0) for i in range(20)] + [(f"r{i}", "A", "gdp", 2021, 1.0) for i in range(20)]
    assert ind.shared_year(observations(rows)) == 2022


def test_split_country_scales_shares_to_national_total_and_reports_extra(country_obs):
    tab, extra = ind.split_country(country_obs, national_gdp=1000.0)
    assert tab["gdp_year"].tolist() == [2022, 2022]
    assert tab["gdp_share"].tolist() == pytest.approx([0.3, 0.6])  # shares of regions + extra-regio (10)
    assert tab["gdp_usd"].sum() + extra == pytest.approx(1000.0) and extra == pytest.approx(100.0)
    assert tab["pop"].tolist() == [100, 300] and tab["area_km2"].tolist() == [10, 40]
    assert tab["area_year"].tolist() == [2020, 2020] and set(tab["pop_source"]) == {"test_src"}


@pytest.mark.parametrize("seed", range(20))
def test_scaling_preserves_national_total_for_random_countries(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(2, 30))
    vals = rng.lognormal(3, 2, n)
    extra = float(rng.uniform(0, vals.sum() * 0.2))
    nat = float(rng.lognormal(20, 1))
    rows = [(f"r{i}", "A", "gdp", 2022, v) for i, v in enumerate(vals)] + [("rz", "A", "gdp_extra", 2022, extra)]
    tab, un = ind.split_country(observations(rows), nat)
    assert tab["gdp_share"].sum() + un / nat == pytest.approx(1.0)
    assert tab["gdp_usd"].sum() + un == pytest.approx(nat)
    assert (tab["gdp_usd"] / nat).tolist() == pytest.approx((vals / (vals.sum() + extra)).tolist())  # ratios untouched by unit


def test_split_country_falls_back_to_earlier_years_never_later(country_obs):
    tab, _ = ind.split_country(country_obs, 1000.0, ref=2021)  # 2022 data are ignored, 2021 GDP exists
    assert tab["gdp_year"].tolist() == [2021, 2021] and tab["pop"].isna().all()
    tab, _ = ind.split_country(country_obs, 1000.0, ref=2024)
    assert tab["gdp_year"].tolist() == [2022, 2022] and tab["pop_year"].tolist() == [2022, 2022]
    assert tab["area_year"].tolist() == [2020, 2020]  # area has no direction rule


def test_split_country_ignores_years_outside_window_and_leaves_missing_blank():
    o = observations([("a", "A", "gdp", 2022, 1.0), ("b", "A", "gdp", 2022, 1.0), ("a", "A", "pop", 2000, 5.0)])
    tab, _ = ind.split_country(o, 10.0)
    assert tab["pop"].isna().all() and tab["area_km2"].isna().all()


def test_split_country_keeps_a_population_older_than_the_window_only_with_the_waiver_flag():
    o = observations([("a", "A", "gdp", 2022, 1.0), ("b", "A", "gdp", 2022, 1.0), ("a", "A", "pop", 2008, 5.0), ("b", "A", "pop", 2008, 7.0)])
    o.loc[o["region_id"] == "a", "note"] = "pop_year_offset"
    tab, _ = ind.split_country(o, 10.0)
    assert tab["pop"].dropna().to_dict() == {"a": 5.0} and tab.loc["a", "pop_year"] == 2008


def test_derive_ratios_are_consistent_and_flags_mark_offsets():
    df = pd.DataFrame({"gdp_usd": [100.0, 50.0], "pop": [10.0, 0.0], "area_km2": [4.0, 5.0], "gdp_year": [2022, 2019],
                       "pop_year": [2022, 2022], "_area_km2_note": ["area_computed", ""]}, index=["a", "b"])
    out = ind.derive(df, 2022)
    assert out["gdp_per_km2"].tolist() == [25.0, 10.0]
    assert out["gdp_per_capita"].iloc[0] == 10.0 and np.isnan(out["gdp_per_capita"].iloc[1])  # no pop -> blank, not inf
    assert out["pop_density"].iloc[0] == 2.5
    assert out["flags"].tolist() == [["area_computed"], ["gdp_year_offset"]]
    ratio = out["gdp_per_km2"] / out["gdp_per_capita"]
    assert ratio.iloc[0] == pytest.approx(out["pop_density"].iloc[0])  # per km2 = per capita * density


def test_compute_whole_country_and_split_country_together(country_obs):
    nat = observations([("ISO3:BBB", "BBB", "gdp", 2022, 500.0), ("ISO3:BBB", "BBB", "pop", 2022, 50.0),
                        ("ISO3:BBB", "BBB", "area_km2", 2021, 5.0), ("ISO3:AAA", "AAA", "gdp", 2022, 1000.0)])
    obs = pd.concat([country_obs, nat[nat["iso3"] == "BBB"]], ignore_index=True)
    levels = pd.Series({"T:AAA0": "admin1", "T:AAA1": "admin1", "ISO3:BBB": "country"})
    out, un = ind.compute(levels, obs, nat, 2022)
    assert out.loc["ISO3:BBB", "gdp_usd"] == 500.0 and out.loc["ISO3:BBB", "flags"] == ["whole_country"]
    assert out.loc[["T:AAA0", "T:AAA1"], "gdp_usd"].sum() + un["AAA"] == pytest.approx(1000.0)
    assert (out["year"] == 2022).all()


def test_compute_flags_national_total_from_an_earlier_year(country_obs):
    nat = observations([("ISO3:AAA", "AAA", "gdp", 2021, 900.0)])
    levels = pd.Series({"T:AAA0": "admin1", "T:AAA1": "admin1"})
    out, _ = ind.compute(levels, country_obs, nat, 2022)
    assert out["flags"].tolist() == [["national_year_offset"]] * 2
    out, _ = ind.compute(levels, country_obs, nat.assign(year=2022), 2022)
    assert out["flags"].tolist() == [[], []]


def scaling_fixture():
    """AAA and CCC complete, BBB one region short, DDD whole; CCC's P is refined into K0 and K1."""
    top = pd.DataFrame({"iso3": ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC", "DDD"], "pop": [10.0, 30.0, 5.0, np.nan, 100.0, 100.0, 7.0]},
                       index=["A0", "A1", "B0", "B1", "P", "Q", "ISO3:DDD"])
    tab = top.drop(index="P").assign(gdp_usd=1000.0, area_km2=10.0, flags=[[] for _ in range(6)])
    for k, v in (("K0", 30.0), ("K1", 50.0)):
        tab.loc[k] = ["CCC", v, 1000.0, 10.0, []]
    national = pd.Series({"ISO3:AAA": 80.0, "ISO3:BBB": 50.0, "ISO3:CCC": 400.0, "ISO3:DDD": 7.0})
    return top, ind.ratios(tab), pd.Series({"K0": "P", "K1": "P"}), national


def test_scale_population_is_top_down_complete_sets_only_and_keeps_the_raw_value():
    top, tab, parent, national = scaling_fixture()
    out, refined, log = ind.scale_population(top, tab, parent, national)
    assert out.loc[["A0", "A1"], "pop"].tolist() == [20.0, 60.0] and out.loc[["A0", "A1"], "pop_raw"].tolist() == [10.0, 30.0]
    assert out.loc[["A0", "A1"], "flags"].tolist() == [["pop_scaled"]] * 2
    assert out.loc["A0", "gdp_per_capita"] == 1000.0 / 20.0 and out.loc["A0", "pop_density"] == 2.0
    assert out.loc["B0", "pop"] == 5.0 and pd.isna(out.loc["B0", "pop_raw"]) and out.loc["B0", "flags"] == []  # incomplete: left alone
    assert out.loc["Q", "pop"] == 200.0 and refined.loc["P"].tolist() == [200.0, 100.0]  # country first, then children to the parent
    assert out.loc[["K0", "K1"], "pop"].tolist() == [75.0, 125.0] and out.loc["K0", "pop_raw"] == 30.0
    assert out.loc["ISO3:DDD", "pop"] == 7.0 and out.loc["ISO3:DDD", "flags"] == []  # whole country: nothing to scale
    assert out.loc[["Q", "K0", "K1"], "pop"].sum() == 400.0
    by = log.set_index("set")
    assert by["factor"].dropna().to_dict() == {"AAA": 2.0, "CCC": 2.0, "P": 2.5} and by.loc["BBB", "missing"] == 1


def test_scale_population_is_idempotent_and_never_touches_gdp_or_area():
    top, tab, parent, national = scaling_fixture()
    once, refined, _ = ind.scale_population(top, tab, parent, national)
    top2 = top.assign(pop=top["pop"].combine_first(pd.Series(dtype=float)))
    top2.loc[["A0", "A1", "Q"], "pop"] = once.loc[["A0", "A1", "Q"], "pop"]
    top2.loc["P", "pop"] = refined.loc["P", "pop"]
    twice, _, _ = ind.scale_population(top2, once.drop(columns="pop_raw"), parent, national)
    assert twice["pop"].equals(once["pop"]) and twice["pop_raw"].isna().all()
    assert once[["gdp_usd", "area_km2"]].equals(tab[["gdp_usd", "area_km2"]])
