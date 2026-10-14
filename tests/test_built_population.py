"""Checks on the last build in data/processed (skipped when there is none): population fill and scaling."""
import json

import pandas as pd
import pytest

from econviz.paths import PROCESSED, WEB_PUBLIC

pytestmark = pytest.mark.skipif(not (PROCESSED / "population_scaling.csv").exists(), reason="no build output")


@pytest.fixture(scope="module")
def ind():
    return pd.read_parquet(PROCESSED / "indicators.parquet").set_index("region_id")


@pytest.fixture(scope="module")
def finest(ind):
    return ind[~ind.index.isin(ind["parent_id"]) & ind["iso3"].notna()]


def test_every_finest_region_has_a_population_and_the_sums_equal_the_national_totals(finest, ind):
    assert finest["pop"].isna().sum() <= 5
    national = ind[ind["level_no"] == 1].set_index("iso3")["pop"]
    got = finest.dropna(subset=["pop"]).groupby("iso3")["pop"].sum()
    complete = finest.groupby("iso3")["pop"].apply(lambda s: s.notna().all())
    ok = got[complete.reindex(got.index)]
    assert ((ok / national.reindex(ok.index) - 1).abs() < 1e-6).all()
    assert abs(finest["pop"].sum() / ind[ind["level_no"] == 1]["pop"].sum() - 1) < 0.01


def test_scaled_rows_keep_their_raw_value_and_the_raw_column_is_last(ind):
    scaled = ind[ind["flags"].map(lambda f: "pop_scaled" in f)]
    assert len(scaled) > 1000 and scaled["pop_raw"].notna().all() and (ind.loc[ind["pop_raw"].notna(), "flags"].map(lambda f: "pop_scaled" in f)).all()
    assert ind.columns[-1] == "pop_raw"
    assert json.loads((WEB_PUBLIC / "indicators.json").read_text())["meta"]["columns"][-1] == "pop_raw"


def test_filled_regions_carry_their_source_and_year(ind):
    pk = ind.loc[["WP:PAK-sindh", "WP:PAK-azad-jammu-and-kashmir", "WP:PAK-gilgit-baltistan", "WP:IND-puducherry", "GID:ALB.4_1"]]
    assert pk["pop_source"].tolist() == ["pbs_census2023", "ajk_bos_glance", "gb_pnd_glance", "in_ncp_projection", "citypopulation"]
    assert pk["pop_year"].tolist() == [2023, 2023, 2023, 2024, 2023]
    states = ind[(ind["iso3"] == "PAK") & (ind["level_no"] == 2) & ~ind.index.isin(["WP:PAK-azad-jammu-and-kashmir", "WP:PAK-gilgit-baltistan"])]
    assert abs(states["pop_raw"].sum() / 241.5e6 - 1) < 0.01  # the PBS provinces and Islamabad
    prefectures = ind[ind.index.str.startswith("COD:")]
    assert len(prefectures) > 250 and prefectures["pop_year"].eq(2020).all() and prefectures["pop"].notna().all()
    assert set(prefectures["pop_source"]) == {"zhwiki_census"}
