import pandas as pd

from econviz.load import deflator, imf, national, worldbank


def wb_json(rows):
    return [{"page": 1}, [{"countryiso3code": i, "date": str(y), "value": v} for i, y, v in rows]]


def test_worldbank_parse_keeps_countries_only_and_drops_nulls():
    countries = worldbank.parse_countries([{}, [
        {"id": "DEU", "name": "Germany", "region": {"value": "Europe & Central Asia"}},
        {"id": "WLD", "name": "World", "region": {"value": "Aggregates"}}]])
    assert countries["iso3"].tolist() == ["DEU"]
    obs = worldbank.parse(wb_json([("DEU", 2022, 4.0e12), ("DEU", 2023, None), ("WLD", 2022, 1.0e14)]),
                          "USD_current", "gdp", countries)
    assert obs[["region_id", "variable", "year", "value", "unit", "source_id"]].values.tolist() == [
        ["ISO3:DEU", "gdp", 2022, 4.0e12, "USD_current", "wb_wdi"]]


def test_imf_parse_filters_countries_and_maps_indicators(tmp_path):
    p = tmp_path / "weo.csv"
    pd.DataFrame({"COUNTRY": ["TWN", "TWN", "WEOWORLD"], "INDICATOR": ["NGDPD", "LP", "NGDPD"], "TIME_PERIOD": [2022] * 3,
                  "OBS_VALUE": [7.6e11, 2.3e7, 1e14]}).to_csv(p, index=False)
    obs = imf.parse(p, {"TWN"})
    assert sorted(zip(obs["variable"], obs["value"])) == [("gdp", 7.6e11), ("pop", 2.3e7)]
    assert set(obs["note"]) == {"imf_estimate"}


def test_national_combine_uses_imf_only_where_world_bank_lacks_gdp():
    wb = pd.DataFrame({"iso3": ["DEU"], "variable": ["gdp"], "year": [2022], "value": [1.0]})
    im = pd.DataFrame({"iso3": ["DEU", "TWN"], "variable": ["gdp", "gdp"], "year": [2022, 2022], "value": [9.0, 2.0]})
    out = national.combine(wb, im, ref=2022)
    assert sorted(zip(out["iso3"], out["value"])) == [("DEU", 1.0), ("TWN", 2.0)]
    assert len(national.combine(wb, im, ref=2024)) == 2  # WB 2022 is an earlier year within the window: kept
    assert len(national.combine(wb, im, ref=2035)) == 3  # nothing within the window below 2035: IMF fills in DEU too


def test_deflator_parse(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("observation_date,A191RD3A086NBEA\n2000-01-01,80\n2017-01-01,100\n2022-01-01,120\n2023-01-01,\n")
    d = deflator.parse(p)
    assert d["year"].tolist() == [2000, 2017, 2022]
