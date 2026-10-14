import gzip
import json
import pathlib
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from econviz.load import dose, dosm, eurostat, kazwiki, oecd, ruwiki, ukrstat, us, wikipedia


def write_gz(path, text):
    with gzip.open(path, "wt") as f:
        f.write(text)
    return path


def test_eurostat_parse_strips_flags_and_splits_extra_regio(tmp_path):
    p = write_gz(tmp_path / "gdp.tsv.gz", "freq,unit,geo\\TIME_PERIOD\t2021 \t2022 \n"
                 "A,MIO_EUR,DE111\t100.5 p\t:\nA,MIO_EUR,DEZZZ\t5\t6\nA,MIO_EUR,DE11\t1\t1\n")
    got = {(r.region_id, r.variable, r.year): r.value for r in eurostat.parse(p, "gdp", {"DE": "DEU"}).itertuples()}
    assert got == {("NUTS2024:DE111", "gdp", 2021): 100.5, ("NUTS2024:DEZZZ", "gdp_extra", 2021): 5.0,
                   ("NUTS2024:DEZZZ", "gdp_extra", 2022): 6.0}  # NUTS2 row ignored, ':' dropped
    assert "NUTS2024:DEZZZ" not in set(eurostat.parse(p, "pop", {"DE": "DEU"})["region_id"])


def test_oecd_parse_selects_series_and_marks_unregionalised(tmp_path):
    cols = "TERRITORIAL_LEVEL,REF_AREA,MEASURE,PRICES,UNIT_MEASURE,TIME_PERIOD,OBS_VALUE,COUNTRY"
    rows = ["TL3,JPA01,GDP,V,USD,2022,10,JPN", "TL3,JPA01,GDP,Q,USD,2022,99,JPN", "TL3,JPA01,GDP,V,XDC,2022,98,JPN",
            "TL3,JPA01,POP,_Z,PS,2022,5,JPN", "TL2,JPA,GDP,V,USD,2022,10,JPN", "CTRY,JPN,GDP,V,USD,2022,10,JPN",
            "TL2,JPZZ,GDP,V,USD,2022,1,JPN", "TL2,JPZZ,POP,_Z,PS,2022,1,JPN"]
    p = tmp_path / "o.csv"
    p.write_text("\n".join([cols] + rows))
    got = sorted((r.region_id, r.level, r.variable, r.value) for r in oecd.parse(p).itertuples())
    assert got == [("OECD:JPA", "tl2", "gdp", 10.0), ("OECD:JPA01", "tl3", "gdp", 10.0), ("OECD:JPA01", "tl3", "pop", 5.0),
                   ("OECD:JPZZ", "tl2", "gdp_extra", 1.0)]


def test_oecd_parse_names_reads_both_sheets(tmp_path):
    p = tmp_path / "t.xlsx"
    with pd.ExcelWriter(p) as w:
        for sheet, col in (("Regions TL2024", "Name (eng)"), ("Regions - TL2021", "Regional name (eng)")):
            pd.DataFrame([["title"] * 5, ["ISO3", "REG_ID", "TL", col, "Hierarchical relations"],
                          ["JPN", "JPA", 2, "Hokkaido", "JPN"], ["JPN", "JPA01", 3, "Sapporo", "JPA"]]).to_excel(
                w, sheet_name=sheet, header=False, index=False)
    assert oecd.parse_names(p)[["region_id", "name", "parent_id", "level"]].values.tolist() == [
        ["OECD:JPA", "Hokkaido", "OECD:JPN", "tl2"], ["OECD:JPA01", "Sapporo", "OECD:JPA", "tl3"]]


def test_dose_parse_long_format(tmp_path):
    p = tmp_path / "d.csv"
    pd.DataFrame({"country": ["Albania"], "region": ["Berat"], "GID_0": ["ALB"], "GID_1": ["ALB.1_1"], "year": [2019],
                  "grp_lcu": [5.0e10], "pop": [1.5e5]}).to_csv(p, index=False)
    obs, names = dose.parse(p)
    assert sorted(zip(obs["variable"], obs["value"])) == [("gdp", 5.0e10), ("pop", 1.5e5)]
    assert names.iloc[0].to_dict() == {"region_id": "GID:ALB.1_1", "iso3": "ALB", "name": "Berat"}


def test_wikipedia_parse_extracts_table_and_revision(tmp_path):
    html = ("<table><tr><th>State</th><th>GDP (bil. US$)</th></tr><tr><td>Lagos State[1]</td><td>102.01</td></tr>"
            "<tr><td>Kano (north)</td><td>1,000.5</td></tr></table>")
    p = tmp_path / "page.json"
    p.write_text(json.dumps({"parse": {"revid": 42, "text": {"*": html}}}))
    t, rev = wikipedia.parse(p, "State", "GDP (bil. US$)")
    assert rev == 42 and t.values.tolist() == [["Lagos State", 102.01], ["Kano", 1000.5]]
    with pytest.raises(ValueError):
        wikipedia.parse(p, "State", "missing")


BEA = ('"GeoFIPS","GeoName","Region","TableName","LineCode","IndustryClassification","Description","Unit","2020","2022"\n'
       '"51003","Albemarle, VA*","5","CAGDP1",3,"x","Current-dollar GDP","Thousands of dollars","1","10"\n'
       '"51540","Charlottesville, VA*","5","CAGDP1",3,"x","x","Thousands of dollars","1","5"\n'
       '"51901","Albemarle + Charlottesville, VA*","5","CAGDP1",3,"x","x","Thousands of dollars","(NA)","15"\n'
       '"51001","Accomack, VA*","5","CAGDP1",3,"x","x","Thousands of dollars","1","7"\n'
       '"51001","Accomack, VA*","5","CAGDP1",1,"x","chained","Thousands of chained 2017 dollars","1","7"\n'
       '"09000","Connecticut","1","CAGDP1",3,"x","x","Thousands of dollars","4","6"\n'
       '"09110","Capitol, CT*","1","CAGDP1",3,"x","x","Thousands of dollars","(NA)","3"\n'
       '"51000","Virginia","5","CAGDP1",3,"x","x","Thousands of dollars","1","1"\n')


def bea_zip(tmp_path):
    p = tmp_path / "bea.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("CAGDP1__ALL_AREAS_2001_2024.csv", BEA)
    return p


def test_us_parse_bea_uses_line3_counties_in_dollars(tmp_path):
    b = us.parse_bea(bea_zip(tmp_path))
    assert set(b["fips"]) == {"51003", "51540", "51901", "51001", "09000", "09110"}  # state rows dropped except Connecticut
    assert b[(b["fips"] == "51003") & (b["year"] == "2022")]["value"].iloc[0] == 10_000  # thousands -> dollars
    assert b[b["fips"] == "51901"]["year"].tolist() == ["2022"]  # (NA) dropped


def test_us_groups_resolve_virginia_cities_and_hawaii():
    c = pd.DataFrame({"GEOID": ["51003", "51540", "51001", "51680", "15009", "15005"],
                      "NAME": ["Albemarle", "Charlottesville", "Accomack", "Lynchburg", "Maui", "Kalawao"],
                      "LSAD": ["06", "25", "06", "25", "06", "06"]})
    names = pd.Series({"51901": "Albemarle + Charlottesville, VA*", "15901": "Maui + Kalawao, HI*", "51001": "Accomack, VA*"})
    assert us.groups(names, c) == {"51901": ["51003", "51540"], "15901": ["15009", "15005"]}


def test_us_layer_merges_members_and_sums_population_and_area(tmp_path):
    geo = gpd.GeoDataFrame({"region_id": ["FIPS:51003", "FIPS:51540", "FIPS:51001", "FIPS:09001", "FIPS:09003"], "iso3": "USA",
                            "name": ["Albemarle, VA", "Charlottesville, VA", "Accomack, VA", "Fairfield, CT", "Hartford, CT"],
                            "level": "county", "parent_id": "FIPS:51", "boundary_source_id": "us_census_cb", "boundary_vintage": "t",
                            "lsad": ["06", "25", "06", "06", "06"],
                            "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 0, 6, 1), box(8, 0, 9, 1), box(9, 0, 10, 1)]},
                           geometry="geometry", crs=4326)
    pop = tmp_path / "pop.csv"
    pd.DataFrame({"STATE": [51] * 3 + [9] * 3, "COUNTY": [3, 540, 1, 0, 110, 120],
                  "POPESTIMATE2022": [100, 50, 7, 30, 10, 20]}).to_csv(pop, index=False)  # CT: state row and planning regions
    gaz = tmp_path / "gaz.zip"
    with zipfile.ZipFile(gaz, "w") as z:
        z.writestr("g.txt", "GEOID\tALAND\n51003\t2000000\n51540\t1000000\n51001\t4000000\n09001\t5000000\n09003\t6000000\n")
    regions, obs = us.layer(bea_zip(tmp_path), pop, gaz, geo)
    assert sorted(regions["region_id"]) == ["FIPS:09000", "FIPS:51001", "FIPS:51901"]
    merged = regions.set_index("region_id").loc["FIPS:51901"]
    assert merged.geometry.bounds == (0, 0, 2, 1) and merged["name"] == "Albemarle + Charlottesville, VA"
    v = obs[obs["region_id"] == "FIPS:51901"].set_index(["variable", "year"])["value"]
    assert v[("pop", 2022)] == 150 and v[("area_km2", 2021)] == 3 and v[("gdp", 2022)] == 15_000
    ct = obs[obs["region_id"] == "FIPS:09000"].set_index(["variable", "year"])["value"]
    assert ct[("pop", 2022)] == 30 and ct[("area_km2", 2021)] == 11 and ct[("gdp", 2022)] == 6_000  # planning regions dropped
    assert regions.set_index("region_id").loc["FIPS:09000", "name"] == "Connecticut"


def page(tmp_path, html):
    p = tmp_path / "page.json"
    p.write_text(json.dumps({"parse": {"revid": 1, "text": {"*": html}}}))
    return p


def test_wikipedia_parse_cleans_names_dedupes_and_prefers_usd_amounts(tmp_path):
    html = ("<table><tr><th>Province</th><th>GDP</th></tr><tr><td>Gauteng *</td><td>ZAR 2.33 trillion (US$157.63 billion)</td></tr>"
            "<tr><td>Gauteng</td><td>US$1</td></tr><tr><td>Free State</td><td>ZAR 342.06 billion (US$1,023.14 billion)</td></tr></table>")
    t, _ = wikipedia.parse(page(tmp_path, html), "Province", "GDP")
    assert t.values.tolist() == [["Gauteng", 157.63], ["Free State", 1023.14]]


def test_wikipedia_parse_flattens_multiindex_headers(tmp_path):
    html = ("<table><tr><th rowspan=2>Region</th><th colspan=2>GRP</th></tr><tr><th>bil. KZT</th><th>bil. US$</th></tr>"
            "<tr><td>Almaty</td><td>3.5</td><td>7</td></tr></table>")
    t, _ = wikipedia.parse(page(tmp_path, html), "('Region', 'Region')", "('GRP', 'bil. KZT')")
    assert t.values.tolist() == [["Almaty", 3.5]]


@pytest.mark.parametrize("seed", range(10))
def test_split_total_finds_the_row_equal_to_the_sum_of_the_others(seed):
    rng = np.random.default_rng(seed)
    v = rng.uniform(1, 100, int(rng.integers(5, 40)))
    t = pd.DataFrame({"name": [f"r{i}" for i in range(len(v))] + ["Country"], "gdp": [*v, v.sum() * rng.uniform(1, 1.08)]})
    regions, total = wikipedia.split_total(t.sample(frac=1, random_state=seed))
    assert sorted(regions["name"]) == sorted(t["name"][:-1]) and total == pytest.approx(t["gdp"].iloc[-1])


def test_split_total_ignores_tables_without_a_total_row():
    t = pd.DataFrame({"name": list("abcde"), "gdp": [1.0, 2.0, 3.0, 4.0, 5.0]})
    assert wikipedia.split_total(t)[1] == 0 and len(wikipedia.split_total(t)[0]) == 5
    assert wikipedia.split_total(t.head(3))[1] == 0


def test_dosm_parse_takes_total_gdp_by_state_and_supra_as_extra_regio(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("series,date,state,sector,value\nabs,2024-01-01,Johor,p0,100.5\nabs,2024-01-01,Johor,p1,15\n"
                 "growth_yoy,2024-01-01,Johor,p0,4.2\nabs,2024-01-01,Supra,p0,7\nabs,2025-01-01,W.P. Labuan,p0,3\n")
    obs, names = dosm.parse(p)
    assert sorted(zip(obs["region_id"], obs["variable"], obs["year"], obs["value"])) == [
        ("DOSM:Johor", "gdp", 2024, 100.5), ("DOSM:Supra", "gdp_extra", 2024, 7), ("DOSM:W.P. Labuan", "gdp", 2025, 3)]
    assert set(obs["note"]) == {"constant_prices"} and set(obs["iso3"]) == {"MYS"}
    assert names["name"].tolist() == ["Johor", "W.P. Labuan"]  # Supra has no geometry

def test_ukrstat_parse_keeps_kyiv_city_drops_the_total_and_regions_without_values(tmp_path):
    p = tmp_path / "grp.xlsx"
    rows = [("code", "attributes", "period", "data"), ("коди", "атрибути", "період", "дані"),
            ("0000000000", "Ukraine", "2021", "300"), ("0100000000", "Autonomous Republic of Crimea", "2021", None),
            ("3200000000", "Kyiv", "2021", "100"), ("8000000000", "City of Kyiv", "2021", "200"), ("8000000000", "City of Kyiv", "2010", "50")]
    with pd.ExcelWriter(p) as w:
        pd.DataFrame(rows).to_excel(w, sheet_name=ukrstat.SHEET, header=False, index=False)
    obs, names = ukrstat.parse(p)
    assert sorted(zip(obs["region_id"], obs["year"], obs["value"])) == [("UKRSTAT:3200000000", 2021, 100), ("UKRSTAT:8000000000", 2021, 200)]
    assert dict(zip(names["region_id"], names["name"])) == {"UKRSTAT:3200000000": "Kyiv Oblast", "UKRSTAT:8000000000": "Kyiv City"}
    assert set(obs["variable"]) == {"gdp"} and set(obs["iso3"]) == {"UKR"}


def test_wikipedia_layer_data_turns_the_total_row_remainder_into_extra_regio_gdp(tmp_path, monkeypatch):
    rows = "".join(f"<tr><td>R{i}</td><td>{v}</td></tr>" for i, v in enumerate([10, 20, 30, 40, 50])) + "<tr><td>Country</td><td>165</td></tr>"
    p = page(tmp_path, f"<table><tr><th>Region</th><th>GDP</th></tr>{rows}</table>")
    cfg = pd.DataFrame([{"iso3": "AAA", "page": "P", "name_col": "Region", "gdp_col": "GDP", "year": 2023, "cited_origin": "x",
                         "flags": "fiscal_year", "year_col": ""}])
    monkeypatch.setattr(wikipedia, "config", lambda: cfg)
    monkeypatch.setattr(wikipedia, "download", lambda page: p)
    names, obs = wikipedia.layer_data()
    assert names["region_id"].tolist() == [f"WP:AAA-r{i}" for i in range(5)]
    g = obs.set_index("region_id")
    assert g.loc["WP:AAA-extra", "variable"] == "gdp_extra" and g.loc["WP:AAA-extra", "value"] == 15
    assert set(obs["year"]) == {2023} and set(obs["note"]) == {"wikipedia_secondary;fiscal_year"}


def test_wikipedia_pages_of_second_subdivisions_take_each_rows_year_and_are_a_layer_of_their_own(tmp_path, monkeypatch):
    rows = "<tr><td>Hefei*</td><td>1141.3</td><td>2021[1]</td></tr><tr><td>Shenzhen</td><td>3238.8</td><td>2022[21]</td></tr>" \
           "<tr><td>Xiamen</td><td>780.3[4]</td><td>2022</td></tr>"
    p = page(tmp_path, f"<table><tr><th>Name</th><th>GDP</th><th>Date</th></tr>{rows}</table>")
    assert wikipedia.parse(p, "Name", "GDP", "Date")[0].values.tolist() == [["Hefei", 1141.3, 2021], ["Shenzhen", 3238.8, 2022], ["Xiamen", 780.3, 2022]]  # footnote marks in amounts are dropped
    cfg = pd.DataFrame([{"iso3": "CHN", "page": "P", "name_col": "Name", "gdp_col": "GDP", "year": 2022, "cited_origin": "x", "flags": "", "year_col": "Date"}])
    monkeypatch.setattr(wikipedia, "config", lambda: cfg)
    monkeypatch.setattr(wikipedia, "download", lambda page: p)
    names, obs = wikipedia.layer_data(sub=True)
    assert obs[["region_id", "year", "value", "note"]].values.tolist() == [["WP:CHN-hefei", 2021, 1141.3, "wikipedia_secondary"],
                                                                         ["WP:CHN-shenzhen", 2022, 3238.8, "wikipedia_secondary"],
                                                                         ["WP:CHN-xiamen", 2022, 780.3, "wikipedia_secondary"]]
    with pytest.raises(ValueError):
        wikipedia.layer_data()  # the page is not part of the first-subdivision layer: nothing to concatenate


def test_manual_population_fills_only_regions_without_an_official_value_and_needs_provenance(tmp_path, monkeypatch):
    from econviz.load import manual
    from conftest import observations
    (tmp_path / "population_manual.csv").write_text(
        "region_id,year,value,source_id,url,note,flags\n"
        "T:AAA0,2023,10,src,http://x,check 10,\n"
        "T:AAA1,2023,20,src,http://x,check 20,pop_secondary\n"
        "T:ZZZ9,2023,5,src,http://x,not a region,\n")
    monkeypatch.setattr(manual, "REFERENCE", tmp_path)
    sources = pd.DataFrame({"source_id": ["src"]})
    table = manual.load(sources)
    regions = pd.DataFrame({"region_id": ["T:AAA0", "T:AAA1"], "iso3": ["AAA", "AAA"]})
    official = observations([("T:AAA0", "AAA", "pop", 2023, 99.0)])  # an official value of the same year beats manual
    out = manual.fill(table, regions, official)
    assert out["region_id"].tolist() == ["T:AAA1"] and out["value"].tolist() == [20.0]
    assert out.loc[0, ["variable", "year", "source_id", "note", "iso3"]].tolist() == ["pop", 2023, "src", "pop_secondary", "AAA"]
    older = observations([("T:AAA0", "AAA", "pop", 2019, 99.0)])  # a newer census replaces an older official projection
    assert set(manual.fill(table, regions, older)["region_id"]) == {"T:AAA0", "T:AAA1"}
    (tmp_path / "population_manual.csv").write_text("region_id,year,value,source_id,url,note,flags\nT:AAA0,2023,10,src,,check,\n")
    with pytest.raises(ValueError, match="no url for"):
        manual.load(sources)
    (tmp_path / "population_manual.csv").write_text("region_id,year,value,source_id,url,note,flags\nT:AAA0,2023,10,nope,http://x,check,\n")
    with pytest.raises(ValueError, match="unknown source_id"):
        manual.load(sources)


def test_manual_population_file_is_consistent():
    from econviz.load import manual
    t = manual.load()
    assert len(t) >= 30 and t["year"].between(2008, 2024).all() and (t["value"] > 0).all()
    old = t[t["year"] < 2016]  # only the waived country (data/reference/pop_year_waivers.csv), flagged
    waived = pd.read_csv(pathlib.Path(__file__).parents[1] / "data" / "reference" / "pop_year_waivers.csv")["iso3"]
    assert old["flags"].eq("pop_year_offset").all() and old["region_id"].str[4:7].isin(waived).all()
    assert t["url"].str.startswith("http").all()


def test_china_prefecture_population_from_zh_wikipedia_lists(monkeypatch):
    from econviz.load import zhwiki_census as zw
    table = lambda head, *rows: "<table><tr><th>名</th><th>" + head + "</th></tr>" + "".join(f"<tr><td>{n}</td><td>{v}</td></tr>" for n, v in rows) + "</table>"
    ranking = "<table><tr><th>省</th><th>城市</th><th>層級</th><th>地區人口</th></tr>" + "".join(
        f"<tr><td>x</td><td>{n}</td><td>地级市</td><td>{v}</td></tr>" for n, v in [("A市", "60"), ("B市", "50"), ("凉山市", "9"), ("C市", "70"), ("Z市", "20")]) + "</table>"
    pages = {zw.RANKING: ranking,  # B has a typo (50, truth 40)
             "安徽省各地级市人口列表": table("常住人口", ("安徽省", "100"), ("A市", "60"), ("B市", "40")),
             "四川省各市州人口列表": table("常住人口", ("四川省", "100"), ("成都市", "70"), ("凉山州", "30")),
             "江苏省各地级市人口列表": table("年末数（万人）", ("江苏省", "0.01"), ("C市", "9999"))}  # 10,000s: ignored, the ranking has C
    monkeypatch.setattr(zw, "PROVINCES", ["安徽省各地级市", "四川省各市州", "江苏省各地级市"])
    monkeypatch.setattr(zw, "singles", lambda: pd.Series({"大兴安岭地区": 5.0}))
    monkeypatch.setattr(zw, "page", lambda title, prop="": {"text": pages[title]})
    units = pd.DataFrame({"code": ["CN034010", "CN034020", "CN051010", "CN051020", "CN032010", "CN099010"],
                          "zh": ["A市", "B市（1）", "成都市", "凉山彝族自治州", "C市", "Z市"],
                          "province": ["Anhui Province", "Anhui Province", "Sichuan Province", "Sichuan Province", "Jiangsu Province", "Zeta Province"]})
    census = pd.DataFrame({"province": ["Anhui", "Sichuan", "Jiangsu", "Zeta"], "population": [100, 100, 70, 100]})
    out = zw.china(units, census)
    assert out.set_index("region_id")["value"].to_dict() == {"COD:CN034010": 60, "COD:CN034020": 40, "COD:CN051010": 70, "COD:CN051020": 30, "COD:CN032010": 70}
    assert set(out["year"]) == {2020} and set(out["source_id"]) == {"zhwiki_census"} and set(out["note"]) == {"wikipedia_secondary"}
    # a province whose units sum to more than 1% above or more than 10% below its total gets nothing
    assert "COD:CN099010" not in set(out["region_id"])
    assert "COD:CN034010" not in set(zw.china(units, census.assign(population=[150, 100, 70, 100]))["region_id"])


def test_single_prefecture_page_gives_the_census_figure(monkeypatch):
    from econviz.load import zhwiki_census as zw
    monkeypatch.setattr(zw, "SINGLES", ("X地区",))
    monkeypatch.setattr(zw, "page", lambda title, prop="": {"wikitext": "根据2020年普查，全区[[常住人口]]为331,276人<ref>"})
    assert zw.singles().to_dict() == {"X地区": 331276}

def _html_page(tmp_path, name, html):
    p = tmp_path / name
    p.write_text(json.dumps({"parse": {"revid": 1, "text": {"*": html}}}), encoding="utf-8")
    return p


def test_ruwiki_parse_names_from_the_english_bridge_keeps_decimal_comma_and_drops_crimea_and_total(tmp_path):
    ru = _html_page(tmp_path, "ru.json", "<table><tr><th>№</th><th>Субъект</th><th>2023</th></tr>"
                    "<tr><td>1</td><td>Москва</td><td>32 339,0</td></tr><tr><td>2</td><td>Московская область</td><td>9244,6</td></tr>"
                    "<tr><td>3</td><td>Чеченская Республика</td><td>500,0</td></tr><tr><td>4</td><td>Республика Крым</td><td>700,0</td></tr>"
                    "<tr><td></td><td>всего Россия</td><td>42 783,6</td></tr></table>")
    en = _html_page(tmp_path, "en.json", "<table><tr><th>Federal subject</th><th>Russian name</th></tr>"
                    "<tr><td>Moscow</td><td>Москва</td></tr><tr><td>Moscow Oblast</td><td>Московская область</td></tr>"
                    "<tr><td>Republic of Crimea</td><td>Республика Крым</td></tr></table>")
    obs, names, total = ruwiki.parse([ru, en])
    assert dict(zip(obs["region_id"], obs["value"])) == {"RUWP:moscow": 32339.0, "RUWP:moscow-oblast": 9244.6, "RUWP:chechnya": 500.0}
    assert total == 42783.6 and set(obs["year"]) == {2023} and set(names["iso3"]) == {"RUS"}


def test_kazwiki_parse_sums_the_new_regions_into_the_units_they_were_cut_from(tmp_path):
    rows = [(1, "Almaty", 30.0), (2, "Astana", 15.0), (3, "East Kazakhstan Region", 5.0), (4, "Abai Region", 3.0),
            (5, "Almaty Region", 6.0), (6, "Jetisu Region", 2.0), (7, "Turkistan Region", 4.0), (8, "Shymkent", 4.5)]
    html = "<table><tr><th>#</th><th>Region</th><th>GRP</th></tr>" + "".join(f"<tr><td>{n}</td><td>{r}</td><td>{v}</td></tr>" for n, r, v in rows) + "</table>"
    obs, names, total = kazwiki.parse(_html_page(tmp_path, "kz.json", html))
    assert dict(zip(names["name"], obs["value"])) == {"Almaty City": 30.0, "Astana": 15.0, "East Kazakhstan": 8.0, "Almaty Region": 8.0, "Turkistan": 8.5}
    assert total == sum(v for *_, v in rows) and set(obs["year"]) == {2024}
