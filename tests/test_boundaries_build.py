import zipfile

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from econviz import boundaries, build, indicators
from econviz.paths import REFERENCE
from conftest import observations, square_regions


def write(tmp_path, name, gdf):
    p = tmp_path / name
    gdf.to_file(p, driver="GeoJSON")
    return p


def test_natural_earth_countries_fixes_missing_iso_codes(tmp_path, monkeypatch):
    g = gpd.GeoDataFrame({"ISO_A3_EH": ["FRA", "-99", "-99"], "ADM0_A3": ["FRA", "KOS", "CYN"], "NAME": ["France", "Kosovo", "N. Cyprus"],
                          "CONTINENT": ["Europe", "Europe", "Asia"], "ISO_A2_EH": ["FR", "XK", "-99"], "geometry": [box(0, 0, 1, 1), box(2, 0, 3, 1), box(4, 0, 5, 1)]}, crs=4326)
    monkeypatch.setattr(boundaries, "get", lambda *a, **k: write(tmp_path, "c.geojson", g))
    out = boundaries.natural_earth_countries()
    assert out["region_id"].tolist() == ["ISO3:FRA", "ISO3:XKX", "ISO3:CYN"]  # Kosovo uses the World Bank code
    assert set(out["level"]) == {"country"} and list(out.columns) == boundaries.COLUMNS + ["continent", "iso2"]
    assert out[["continent", "iso2"]].values.tolist() == [["Europe", "FR"], ["Europe", "XK"], ["Asia", "-99"]]


def test_island_states_natural_earth_files_under_open_ocean_get_a_real_continent(tmp_path, monkeypatch):
    g = gpd.GeoDataFrame({"ISO_A3_EH": ["MDV", "MUS", "SYC", "FRA"], "ADM0_A3": ["MDV", "MUS", "SYC", "FRA"], "NAME": list("abcd"),
                          "CONTINENT": ["Seven seas (open ocean)"] * 3 + ["Europe"], "ISO_A2_EH": ["MV", "MU", "SC", "FR"],
                          "geometry": [box(i, 0, i + 1, 1) for i in range(4)]}, crs=4326)
    monkeypatch.setattr(boundaries, "get", lambda *a, **k: write(tmp_path, "c.geojson", g))
    assert boundaries.natural_earth_countries()["continent"].tolist() == ["Asia", "Africa", "Africa", "Europe"]


def test_gisco_nuts3_ids_parents_and_iso3(tmp_path, monkeypatch):
    g = gpd.GeoDataFrame({"NUTS_ID": ["DE111"], "ISO3_CODE": ["DEU"], "NAME_LATN": ["Stuttgart"], "geometry": [box(0, 0, 1, 1)]}, crs=4326)
    monkeypatch.setattr(boundaries, "get", lambda *a, **k: write(tmp_path, "n.geojson", g))
    r = boundaries.gisco_nuts3().iloc[0]
    assert (r["region_id"], r["parent_id"], r["iso3"], r["level"]) == ("NUTS2024:DE111", None, "DEU", "nuts3")


def zipped(tmp_path, name, gdf):
    gdf.to_file(tmp_path / f"{name}.shp")
    with zipfile.ZipFile(tmp_path / "z.zip", "w") as z:
        for f in tmp_path.glob(f"{name}.*"):
            z.write(f, f.name)
    return tmp_path / "z.zip"


def test_ocha_china_merges_laiwu_into_jinan_and_maps_provinces_to_parents(tmp_path, monkeypatch):
    g = gpd.GeoDataFrame({"ADM2_PCODE": ["CN037070", "CN037050", "CN044150", "CN081010"], "ADM2_EN": ["Laiwu", "Jinan", "Shenzhen", "Hong Kong"],
                          "ADM1_PCODE": ["CN037", "CN037", "CN044", "CN081"]}, geometry=[box(i, 0, i + 1, 1) for i in range(4)], crs=4326)
    monkeypatch.setattr(boundaries, "get", lambda *a, **k: zipped(tmp_path, "chn_admbnda_adm2_ocha_2020", g))
    r = boundaries.ocha_china(pd.Series({"CN037": "OECD:CN15", "CN044": "OECD:CN19"})).set_index("region_id")
    assert r[["name", "level", "iso3"]].values.tolist() == [["Jinan", "prefecture", "CHN"], ["Shenzhen", "prefecture", "CHN"], ["Hong Kong", "prefecture", "CHN"]]
    assert r.geometry["COD:CN037050"].bounds == (0, 0, 2, 1) and r["parent_id"].tolist()[:2] == ["OECD:CN15", "OECD:CN19"] and pd.isna(r["parent_id"].iloc[2])


def test_ons_itl3_repairs_invalid_geometry(tmp_path, monkeypatch):
    bowtie = "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"
    spike = "POLYGON((0 0, 2 0, 2 2, 0 2, 0 0, -1 -1, 0 0))"  # make_valid keeps the spike as a line
    g = gpd.GeoDataFrame({"ITL325CD": ["TLC11", "TLC12"], "ITL325NM": ["Darlington", "Spiky"], "geometry": gpd.GeoSeries.from_wkt([bowtie, spike])}, crs=4326)
    monkeypatch.setattr(boundaries, "get", lambda *a, **k: write(tmp_path, "i.geojson", g))
    r = boundaries.ons_itl3()
    assert r["region_id"].iloc[0] == "ITL3:TLC11" and r.geometry.is_valid.all() and set(r.geom_type) <= {"Polygon", "MultiPolygon"}


def test_us_counties_drop_territories_keep_lsad_and_name_their_states(tmp_path, monkeypatch):
    g = gpd.GeoDataFrame({"GEOID": ["06037", "72001"], "STATEFP": ["06", "72"], "NAME": ["Los Angeles", "Adjuntas"],
                          "STUSPS": ["CA", "PR"], "STATE_NAME": ["California", "Puerto Rico"], "LSAD": ["06", "13"], "geometry": [box(0, 0, 1, 1), box(2, 0, 3, 1)]}, crs=4326)
    g.to_file(tmp_path / "c.shp")
    zp = tmp_path / "c.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for f in tmp_path.glob("c.*"):
            if f.suffix != ".zip":
                z.write(f, f.name)
    monkeypatch.setattr(boundaries, "get", lambda *a, **k: zp)
    out = boundaries.us_counties()
    assert out[["region_id", "name", "parent_id", "lsad"]].values.tolist() == [["FIPS:06037", "Los Angeles, CA", "FIPS:06", "06"]]
    assert boundaries.us_state_names().to_dict() == {"FIPS:06": "California"}


def test_snap_cuts_a_mesh_to_the_outline_and_gives_what_is_left_to_the_longest_border_or_the_nearest():
    mesh = gpd.GeoSeries([box(0, 0, 1, 3), box(1, 0, 5, 1)], index=["a", "b"], crs=4326)  # a reaches y 3, b reaches x 5
    land, island = box(0, 0, 4, 2), box(4.5, 0, 4.6, 0.1)
    out = boundaries.snap(mesh, land.union(island))
    assert out["a"].equals(box(0, 0, 1, 2))  # cut; the uncovered box(1, 1, 4, 2) borders a over 1 and b over 3 degrees
    assert out["b"].equals(box(1, 0, 4, 1).union(box(1, 1, 4, 2)).union(island)) and out.is_valid.all()
    assert out.union_all().equals(land.union(island)) and out.area.sum() == pytest.approx(8.01)  # a tiling of the outline


def test_fill_area_only_for_regions_without_sourced_area():
    regions = square_regions("AAA", 2)
    obs = observations([("T:AAA0", "AAA", "area_km2", 2020, 5.0)])
    out = build.fill_area(regions, obs)
    a = out[out["variable"] == "area_km2"].set_index("region_id")
    assert a.loc["T:AAA0", "value"] == 5.0 and a.loc["T:AAA1", "note"] == "area_computed"
    assert a.loc["T:AAA1", "value"] == pytest.approx(12_300, rel=0.02) and a.loc["T:AAA1", "year"] == indicators.REF_YEAR


def test_check_reports_each_failure_mode():
    nat = observations([("ISO3:AAA", "AAA", "gdp", 2022, 100.0), ("ISO3:AAA", "AAA", "pop", 2022, 100.0)])
    base = pd.DataFrame({"iso3": "AAA", "gdp_usd": [50.0, 50.0], "pop": [50.0, 50.0], "area_km2": [1.0, 1.0],
                         "gdp_per_capita": [1.0, 1.0], "gdp_source": "s", "gdp_year": 2022, "pop_source": "s", "pop_year": 2022,
                         "area_source": "s", "area_year": 2020}, index=["a", "b"])
    un = pd.Series({"AAA": 0.0})
    assert build.check(base, un, nat, set()) == []
    assert build.check(base.assign(gdp_usd=[50.0, 40.0]), un, nat, set())  # does not add up
    assert build.check(base.assign(pop=[10.0, 10.0]), un, nat, set())  # population off
    assert build.check(base.assign(area_km2=[1.0, 0.0]), un, nat, set())  # area <= 0
    assert build.check(base.assign(gdp_per_capita=[1.0, 1000.0]), un, nat, set())  # outlier
    assert build.check(base.assign(gdp_per_capita=[1.0, 1000.0]), un, nat, {"b"}) == []  # whitelisted
    assert build.check(base.assign(gdp_source=[None, "s"]), un, nat, set())  # no provenance


@pytest.mark.network
def test_world_bank_country_list_still_parses():
    import requests

    from econviz.load import worldbank
    countries = worldbank.parse_countries(requests.get(worldbank.COUNTRIES, timeout=60).json())
    assert {"DEU", "USA"} <= set(countries["iso3"]) and "WLD" not in set(countries["iso3"])


def attach_fixture():
    countries = gpd.GeoDataFrame({"iso3": ["SOM", "ETH"], "geometry": [box(0, 0, 1, 1), box(5, 0, 6, 1)]}, crs=4326)
    units = gpd.GeoDataFrame({"unit": ["SOL", "BRT"], "geometry": [box(1, 0, 2, 1), box(3, 0, 4, 1)]}, crs=4326)
    return countries, units, pd.DataFrame({"unit": ["SOL"], "target": ["SOM"], "reason": ["de jure"], "adds_area": [False]})


def test_attach_joins_the_unit_to_its_target_and_is_idempotent():
    countries, units, table = attach_fixture()
    once = boundaries.attach(countries, units, table)
    som, eth = once.set_index("iso3").geometry["SOM"], once.set_index("iso3").geometry["ETH"]
    assert som.symmetric_difference(box(0, 0, 2, 1)).area < 1e-9 and eth.equals(box(5, 0, 6, 1))
    twice = boundaries.attach(once, units, table)
    assert once.geometry.symmetric_difference(twice.geometry).area.max() < 1e-9


def test_attached_area_is_added_only_where_the_row_says_so():
    countries, units, table = attach_fixture()
    assert (boundaries.attach(countries, units, table)["attached_km2"] == 0).all()
    ne = boundaries.attach(countries, units, table.assign(adds_area=True)).assign(region_id=lambda d: "ISO3:" + d["iso3"])
    piece = boundaries.area_km2(gpd.GeoDataFrame(geometry=[box(1, 0, 2, 1)], crs=4326)).iloc[0]
    obs = pd.DataFrame({"region_id": ["ISO3:SOM", "ISO3:ETH", "ISO3:SOM"], "variable": ["area_km2", "area_km2", "pop"],
                        "value": [1000.0, 500.0, 7.0], "note": ["", "", ""]})
    out = boundaries.add_attached_area(obs, ne)
    assert out["value"].tolist() == [1000 + piece, 500, 7] and out["note"].tolist() == ["area_computed", "", ""]


def test_attach_unknown_unit_or_target_fails_naming_it():
    countries, units, table = attach_fixture()
    with pytest.raises(ValueError, match="unknown unit 'XXX'"):
        boundaries.attach(countries, units, table.assign(unit="XXX"))
    with pytest.raises(ValueError, match="unknown target 'YYY'"):
        boundaries.attach(countries, units, table.assign(target="YYY"))


def test_attach_file_has_its_columns_and_one_row_per_unit():
    table = pd.read_csv(REFERENCE / "attach.csv")
    assert list(table.columns) == ["unit", "target", "reason", "adds_area"] and not table.duplicated("unit").any()
