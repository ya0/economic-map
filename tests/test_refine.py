"""Second subdivisions below chosen level-2 regions: `select.refine`, their loaders and the built result."""
import json
import zipfile

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from econviz import boundaries, indicators, layers, levels, select, validate
from econviz.load import ibge, inegi, statcan
from econviz.paths import PROCESSED
from conftest import observations, square_regions



def kids(parent: str, boxes, gdp, pop=None, year=2022):
    """Children of T:<parent> (ids `K:<parent>.<i>`) with GDP and area observations, optionally population."""
    ids = [f"K:{parent}.{i}" for i in range(len(boxes))]
    reg = gpd.GeoDataFrame({"region_id": ids, "iso3": parent[:3], "name": ids, "level": "metro", "parent_id": f"T:{parent}",
                            "boundary_source_id": "kid_boundary", "boundary_vintage": "test"}, geometry=list(boxes), crs=4326)
    rows = [(i, parent[:3], "gdp", year, v) for i, v in zip(ids, gdp)] + [(i, parent[:3], "area_km2", 2020, 7.0) for i in ids]
    rows += [(i, parent[:3], "pop", 2024, v) for i, v in zip(ids, pop or [])]
    return reg[boundaries.COLUMNS], observations(rows, "kid_src")


def chosen():
    """Country AAA, two level-2 squares with GDP 300 and 600 of a national 1000 (100 unallocated) and 100 people each."""
    reg = square_regions("AAA", 2)
    rows = [("T:AAA0", "AAA", "gdp", 2024, 30.0), ("T:AAA1", "AAA", "gdp", 2024, 60.0), ("X", "AAA", "gdp_extra", 2024, 10.0)]
    rows += [(r, "AAA", v, 2024, x) for r in reg["region_id"] for v, x in (("pop", 100.0), ("area_km2", 5.0))]
    nat = observations([("ISO3:AAA", "AAA", "gdp", 2024, 1000.0), ("ISO3:AAA", "AAA", "pop", 2024, 210.0)])
    ind, _ = indicators.compute(reg.set_index("region_id")["level"], observations(rows), nat, 2024)
    return reg, ind, nat, observations(rows)


def all_levels(reg, ind, nat):
    names = pd.Series({"T:AAA0": "zero", "T:AAA1": "one", "ISO3:AAA": "Aland", "CONT:europe": "Europe"})
    continent = pd.Series({"AAA": "CONT:europe"})
    return levels.aggregate(levels.hierarchy(reg, pd.Series(dtype=str), continent), ind, names, continent, indicators.national_population(nat, 2024))[1]


def test_refine_replaces_a_parent_by_children_that_sum_to_it_and_leaves_the_other_levels_unchanged():
    reg, ind, nat, own = chosen()
    fit = kids("AAA0", [box(0, 0, 0.5, 1), box(0.5, 0, 1, 1)], gdp=[1.0, 3.0], pop=[40.0, 62.0])
    half = kids("AAA1", [box(1, 0, 1.2, 1), box(1.2, 0, 1.5, 1)], gdp=[1.0, 1.0])  # covers half of its parent
    sub, obs = (pd.concat(x, ignore_index=True) for x in zip(fit, half))
    reg2, ind2, rejected = select.refine(reg, ind, sub, pd.concat([own, obs]), ref=2024)
    assert sorted(reg2["region_id"]) == sorted(ind2.index) == ["K:AAA0.0", "K:AAA0.1", "T:AAA1"] and "cover" in rejected["T:AAA1"]
    assert ind2.loc[["K:AAA0.0", "K:AAA0.1"], "gdp_usd"].tolist() == pytest.approx([75.0, 225.0])  # shares of the parent's 300
    assert ind2.loc["K:AAA0.1", ["gdp_share", "gdp_year", "gdp_source", "pop", "area_km2", "iso3", "year"]].tolist() == [
        pytest.approx(0.225), 2022, "kid_src", 62.0, 7.0, "AAA", 2024]
    assert ind2.loc["K:AAA0.1", "flags"] == ["gdp_year_offset"] and list(ind2.columns) == list(ind.columns)
    after = all_levels(reg2, ind2, nat)
    pd.testing.assert_frame_equal(after.loc[ind.index, ["gdp_usd", "gdp_share"]], ind[["gdp_usd", "gdp_share"]], rtol=1e-12)  # level 2 as before
    assert after.loc["ISO3:AAA", ["gdp_usd", "gdp_share", "pop"]].tolist() == pytest.approx([900.0, 0.9, 210.0])
    assert after.loc["T:AAA0", ["pop", "area_km2", "gdp_year"]].tolist() == [102.0, 14.0, 2022]  # sums of the children, oldest year
    assert after.loc["K:AAA0.0", ["level_no", "parent_id"]].tolist() == [3, "T:AAA0"]


def test_refine_keeps_child_population_for_scaling_and_rejects_bad_layers():
    reg, ind, _, own = chosen()
    boxes = [box(0, 0, 0.5, 1), box(0.5, 0, 1, 1)]
    sub, obs = kids("AAA0", boxes, gdp=[1.0, 3.0], pop=[40.0, 90.0])  # 130 people, the parent has 100: scaled later
    _, ind2, _ = select.refine(reg, ind, sub, pd.concat([own, obs]), ref=2024)
    assert ind2.loc[["K:AAA0.0", "K:AAA0.1"], "pop"].tolist() == [40.0, 90.0]
    for bad, reason in ((kids("AAA0", boxes[:1], gdp=[1.0]), "fewer than 2"), (kids("AAA0", boxes, gdp=[1.0, 3.0], year=2010), "no GDP"),
                        (kids("AAA0", [box(0, 0, 0.6, 1), box(0.4, 0, 1, 1)], gdp=[1.0, 3.0]), "overlap"),
                        (kids("AAA9", boxes, gdp=[1.0, 3.0]), None)):  # the parent is not a chosen region: ignored
        reg2, ind2, rejected = select.refine(reg, ind, *bad, ref=2024)
        assert ind2.equals(ind) and reg2.equals(reg) and (reason is None and not rejected or reason in rejected["T:AAA0"])


def test_fit_is_the_country_outline_except_along_a_neighbour_drawn_from_another_source():
    outline = gpd.GeoSeries({"AAA": box(0, 0, 4, 2), "BBB": box(4, 0, 8, 2), "CCC": box(0, 2, 4, 4)}, crs=4326)
    mesh = square_regions("AAA", 1, size=4.5).assign(geometry=[box(0, 0, 4.5, 2.5)])  # reaches into both neighbours
    there = lambda x, src: pd.concat([square_regions("BBB", 1).assign(geometry=[box(x, 0, 8, 2)], boundary_source_id=src),
                                      square_regions("CCC", 1).assign(geometry=[outline["CCC"]], boundary_source_id="natural_earth")])
    assert layers.fit(mesh, outline, there(4.2, "natural_earth")).equals(outline["AAA"])
    for x in (4.2, 3.9):  # BBB's own shape starts beyond or before the outline: the mesh ends there, CCC stays as outlined
        assert layers.fit(mesh, outline, there(x, "census")).equals(box(0, 0, x, 2))


def test_adopt_gives_a_region_the_dissolve_of_its_subdivisions_and_drops_its_computed_area():
    reg = square_regions("AAA", 3)
    sub = pd.concat([kids("AAA0", [box(0, 0, 0.5, 1.2), box(0.5, 0, 1.1, 1.2)], gdp=[1.0, 1.0])[0], kids("AAA1", [box(1.1, 0, 2, 1)], gdp=[1.0])[0]])
    area = observations([(r, "AAA", "area_km2", 2020, 5.0) for r in reg["region_id"]])
    area["note"] = ["area_computed", "", "area_computed"]
    out, obs = layers.adopt(reg, area, sub)
    assert out["region_id"].tolist() == reg["region_id"].tolist() and out.crs == reg.crs
    assert [g.bounds for g in out.geometry] == [(0, 0, 1.1, 1.2), (1.1, 0, 2, 1), (2, 0, 3, 1)]  # a single child counts too
    assert out["boundary_source_id"].tolist() == ["kid_boundary", "kid_boundary", "test_boundary"]
    assert obs["region_id"].tolist() == ["T:AAA1", "T:AAA2"]  # a sourced area stays, as does a region without subdivisions


def sidra(tmp_path, variable, rows, year):
    head = {"V": "Valor", "D1C": "Município (Código)", "D1N": "Município", "D3C": "Ano (Código)"}
    p = tmp_path / f"{variable}.json"
    p.write_text(json.dumps([head] + [{"V": v, "D1C": c, "D1N": c, "D3C": year} for c, v in rows]), encoding="utf-8")
    return p


def test_ibge_layer_sums_municipalities_into_immediate_regions_and_dissolves_the_mesh(tmp_path):
    codes = ["3550308", "3509502", "3304557"]  # two municipalities of the São Paulo immediate region, one of Rio de Janeiro's
    tables = {"gdp": sidra(tmp_path, "gdp", zip(codes, ("100", "...", "7")), "2023"),  # '...' (no value) counts as zero
              "pop": sidra(tmp_path, "pop", zip(codes, ("10", "5", "3")), "2024"),
              "area_km2": sidra(tmp_path, "area", zip(codes, ("1.5", "2", "4")), "2022")}
    mesh = tmp_path / "mesh.geojson"
    gpd.GeoDataFrame({"codarea": [*codes, "4300001"]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 0, 6, 1), box(8, 0, 9, 1)],
                     crs=4326).to_file(mesh, driver="GeoJSON")  # the lagoon 4300001 belongs to no region
    loc = tmp_path / "loc.json"
    loc.write_text(json.dumps([{"id": int(c), "nome": n, "regiao-imediata": r and {"id": r, "nome": n}} for c, n, r in (
        (codes[0], "Campinas", 350001), (codes[1], "Campinas", 350001), (codes[2], "Rio", 330001), ("1100000", "Nowhere", None))]), encoding="utf-8")
    reg, obs = ibge.layer(tables, mesh, loc, pd.Series({"35": "OECD:BR20", "33": "OECD:BR19"}))
    assert reg[["region_id", "iso3", "name", "level", "parent_id"]].values.tolist() == [
        ["IBGE:330001", "BRA", "Rio", "immediate", "OECD:BR19"], ["IBGE:350001", "BRA", "Campinas", "immediate", "OECD:BR20"]]
    assert dict(zip(reg["region_id"], reg.geometry.map(lambda g: g.bounds))) == {"IBGE:330001": (5, 0, 6, 1), "IBGE:350001": (0, 0, 2, 1)}
    assert sorted(obs[["region_id", "variable", "year", "value", "source_id"]].values.tolist()) == [
        ["IBGE:330001", "area_km2", 2022, 4.0, "br_ibge_area"], ["IBGE:330001", "gdp", 2023, 7.0, "br_ibge_pib_municipios"],
        ["IBGE:330001", "pop", 2024, 3.0, "br_ibge_popest"], ["IBGE:350001", "area_km2", 2022, 3.5, "br_ibge_area"],
        ["IBGE:350001", "gdp", 2023, 100.0, "br_ibge_pib_municipios"], ["IBGE:350001", "pop", 2024, 15.0, "br_ibge_popest"]]


def test_inegi_layer_cuts_metropolises_by_state_and_collects_the_rest_of_each_state(tmp_path):
    def census(state, rows):
        with zipfile.ZipFile(tmp_path / f"{state}.zip", "w") as z:
            z.writestr(f"conjunto_de_datos/tr_ce_{state}_2024.csv", "\n".join(["E03,E04,SECTOR,ID_ESTRATO,CODIGO,UE,A131A", *rows]))
        return tmp_path / f"{state}.zip"
    zips = [census("cdmx", ["09,,,,TOTAL,9,999.0", "09,015,,,TOTAL,5,10.0", "09,015,11,,Sector 11,2,5.0", "09,016,,,TOTAL,3,-2.5"]),
            census("mex", ["15,001,,,TOTAL,5,3.0", "15,002,,,TOTAL,5,4.0", "15,003,,,TOTAL,1,"])]  # 09016 negative, 15003 withheld
    shapes = tmp_path / "m.geojson"
    gpd.GeoDataFrame({"cvegeo": ["09015", "09016", "15001", "15002", "15003"], "cve_ent": ["09", "09", "15", "15", "15"],
                      "pob_total": ["100", "50", "30", "20", None]}, geometry=[box(i, 0, i + 1, 1) for i in range(5)], crs=4326).to_file(shapes, driver="GeoJSON")
    metros = tmp_path / "metros.csv"  # Valle: Cuauhtémoc (CDMX) and one municipio of México; Toluca lies in México only
    metros.write_text("clave_metropoli,nombre,clave_entidad,entidad,clave_compuesta_municipio\n09.1.01,Valle,9,Ciudad de México,9015\n"
                      "09.1.01,Valle,15,México,15001\n15.1.01,Toluca,15,México,15002\n", encoding="utf-8")
    reg, obs = inegi.layer(zips, shapes, metros, pd.Series({"09": "OECD:ME09", "15": "OECD:ME15"}))
    assert reg[["region_id", "name", "level", "parent_id"]].values.tolist() == [
        ["ZM:09-rest", "Rest of Ciudad de México", "metro", "OECD:ME09"], ["ZM:0909101", "Valle, Ciudad de México part", "metro", "OECD:ME09"],
        ["ZM:15-rest", "Rest of México", "metro", "OECD:ME15"], ["ZM:1509101", "Valle, México part", "metro", "OECD:ME15"],
        ["ZM:1515101", "Toluca", "metro", "OECD:ME15"]]
    assert reg.geometry.is_valid.all() and reg.geometry.map(lambda g: g.bounds).tolist() == [(1, 0, 2, 1), (0, 0, 1, 1), (4, 0, 5, 1), (2, 0, 3, 1), (3, 0, 4, 1)]
    assert sorted(obs[["region_id", "variable", "value", "note"]].values.tolist()) == [
        ["ZM:09-rest", "pop", 50.0, "remainder"], ["ZM:0909101", "gdp", 10.0, "census_va_share"], ["ZM:0909101", "pop", 100.0, ""],
        ["ZM:1509101", "gdp", 3.0, "census_va_share"], ["ZM:1509101", "pop", 30.0, ""],
        ["ZM:1515101", "gdp", 4.0, "census_va_share"], ["ZM:1515101", "pop", 20.0, ""]]  # 15003 has no value at all, the rest of Ciudad de México (09016) no GDP (negative)


def test_china_prefectures_carry_the_gdp_of_their_crosswalked_wikipedia_row(monkeypatch):
    cw = pd.DataFrame({"layer": ["cn_prefectures", "dose"], "region_id": ["WP:CHN-shenzhen", "WP:CHN-hefei"], "geo_id": ["COD:CN044150", "NE1:x"]})
    obs = observations([("WP:CHN-shenzhen", "CHN", "gdp", 2022, 3238.8), ("WP:CHN-hefei", "CHN", "gdp", 2021, 1141.3)])
    monkeypatch.setattr(layers.crosswalk, "load", lambda: cw)
    monkeypatch.setattr(layers.wikipedia, "layer_data", lambda sub: (None, obs))
    monkeypatch.setattr(layers.boundaries, "ocha_china", lambda parents: "shapes")
    monkeypatch.setattr(layers.boundaries, "ocha_china_names", lambda: "names")
    monkeypatch.setattr(layers.zhwiki_census, "census_totals", lambda: "census")
    census_pop = observations([("COD:CN044150", "CHN", "pop", 2020, 17.56e6)])
    monkeypatch.setattr(layers.zhwiki_census, "china", lambda units, census: census_pop if (units, census) == ("names", "census") else None)
    shapes, out = layers.china_prefectures(pd.Series(dtype=str))
    assert shapes == "shapes"
    assert out[["region_id", "variable", "year", "value"]].values.tolist() == [
        ["COD:CN044150", "gdp", 2022, 3238.8], ["COD:CN044150", "pop", 2020, 17.56e6]]


def statcan_csv(tmp_path, name, rows):
    pd.DataFrame(rows, columns=["REF_DATE", "GEO", "DGUID", "VALUE"]).to_csv(tmp_path / name, index=False)
    return tmp_path / name


def test_statcan_layer_builds_metro_areas_and_a_remainder_that_complete_the_province(tmp_path):
    gdp = [("2022", "Canada", "2016A000011124", "2674953"), ("2022", "Ontario", "2016A000235", "1000"), ("2022", "Quebec", "2016A000224", "500"),
           ("2022", "Toronto, Ontario", "2011S0503535", "600"), ("2022", "Ottawa – Gatineau, Ontario part, Ontario/Quebec", "2011S050535505", "100"),
           ("2022", "Ottawa – Gatineau, Quebec part, Ontario/Quebec", "2011S050524505", "20"), ("2022", "Non-census metropolitan areas, Ontario", None, "300"),
           ("2022", "Non-census metropolitan areas, Quebec", None, "480"), ("2022", "Prince Edward Island", "2016A000211", "9")]
    pop = [("2024", "Toronto (CMA), Ontario", "2021S0503535", "7000"), ("2024", "Ottawa - Gatineau (CMA), Ontario/Quebec", "2021S0503505", "1600"),
           ("2024", "Ottawa - Gatineau (CMA), Ontario part, Ontario", "2021S050535505", "1200"), ("2024", "Ottawa - Gatineau (CMA), Quebec part, Quebec", "2021S050524505", "400"),
           ("2024", "Hawkesbury (CA), Ontario part, Ontario", "2021S050635502", "12"), ("2024", "Canada", "2021A00001124", "41000")]
    province = [("2024-07-01", "Ontario", "2021A000235", "16000"), ("2024-10-01", "Ontario", "2021A000235", "16100"), ("2024-07-01", "Quebec", "2021A000224", "9000"),
                ("2024-07-01", "Canada", "2021A000011124", "41000")]
    tables = {"gdp": statcan_csv(tmp_path, "g.csv", gdp), "pop": statcan_csv(tmp_path, "p.csv", pop), "province": statcan_csv(tmp_path, "q.csv", province)}
    shapes = tmp_path / "cma.geojson"  # Toronto inside Ontario; Ottawa's Ontario part reaches 0.5 beyond the province's shape
    gpd.GeoDataFrame({"CMAPUID": ["35535", "35505", "24505"], "CMAUID": ["535", "505", "505"], "PRUID": ["35", "35", "24"]},
                     geometry=[box(1, 1, 2, 2), box(3, 1, 4.5, 2), box(4, 1, 5, 2)], crs=4326).to_file(shapes, driver="GeoJSON")
    provinces = gpd.GeoSeries({"OECD:CA35": box(0, 0, 4, 4), "OECD:CA24": box(4, 0, 8, 4)}, crs=4326)
    reg, obs = statcan.layer(tables, shapes, provinces, pd.Series({"35": "OECD:CA35", "24": "OECD:CA24", "11": "OECD:CA11"}))
    r = reg.set_index("region_id")
    assert r[["name", "parent_id", "level", "iso3"]].values.tolist() == [
        ["Toronto, Ontario", "OECD:CA35", "metro", "CAN"], ["Ottawa – Gatineau, Ontario part, Ontario/Quebec", "OECD:CA35", "metro", "CAN"],
        ["Ottawa – Gatineau, Quebec part, Ontario/Quebec", "OECD:CA24", "metro", "CAN"],
        ["Rest of Quebec", "OECD:CA24", "metro", "CAN"], ["Rest of Ontario", "OECD:CA35", "metro", "CAN"]]
    assert r.geometry["CMA:35505"].bounds == (3, 1, 4, 2)  # cut at the province's border
    area, values = r.geometry.map(lambda s: s.area).groupby(r["parent_id"]).sum(), obs.merge(reg[["region_id", "parent_id"]]).groupby(["parent_id", "variable"])["value"].sum()
    assert area.to_dict() == {"OECD:CA24": 16.0, "OECD:CA35": 16.0}  # metro areas + remainder = the province's shape
    assert values.to_dict() == {("OECD:CA24", "gdp"): 500, ("OECD:CA24", "pop"): 9000, ("OECD:CA35", "gdp"): 1000, ("OECD:CA35", "pop"): 16000}
    o = obs.set_index(["region_id", "variable"])
    assert o.loc[("CMA:35-rest", "pop"), ["value", "year", "note", "source_id"]].tolist() == [7800, 2024, "remainder", "ca_statcan_pop"]
    assert o.loc[("CMA:35-rest", "gdp"), ["value", "year", "note"]].tolist() == [300, 2022, "remainder"] and o.loc[("CMA:35505", "pop"), "value"] == 1200
    assert validate.overlaps(reg, 0) == [] and len(obs) == 10


def test_built_canadian_provinces_equal_their_metro_areas_plus_the_remainder():
    if not (PROCESSED / "regions.geoparquet").exists():
        pytest.skip("no build outputs")
    reg = gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")
    ind = pd.read_parquet(PROCESSED / "indicators.parquet").set_index("region_id")
    k = ind[(reg["level"].reindex(ind.index) == "metro") & (ind["iso3"] == "CAN")].assign(km2=lambda d: boundaries.area_km2(reg.loc[d.index]))
    sums, parents = k.groupby("parent_id")[["gdp_usd", "pop", "km2", "area_km2"]].sum(), ind.loc[sorted(set(k["parent_id"]))]
    rest = k[k.index.str.endswith("-rest")]
    assert len(parents) == len(rest) == 9 and rest["flags"].map(lambda f: "remainder" in f).all() and len(k) == 51
    assert (rest[["gdp_usd", "pop", "area_km2"]] > 0).all(axis=None) and k["flags"].map(lambda f: "remainder" in f).sum() == 9
    pd.testing.assert_series_equal(sums["gdp_usd"], parents["gdp_usd"], rtol=1e-9, check_names=False)
    pd.testing.assert_series_equal(sums["pop"], parents["pop"], rtol=0.01, check_names=False)  # StatCan estimates vs the OECD's copy
    pd.testing.assert_series_equal(sums["km2"], boundaries.area_km2(reg.loc[parents.index]), rtol=1e-6, check_names=False)  # an exact partition
    pd.testing.assert_series_equal(sums["area_km2"], parents["area_km2"], rtol=1e-9, check_names=False)


def test_built_second_subdivisions_sum_to_their_parent_and_their_sourced_area_matches_their_shape():
    if not (PROCESSED / "regions.geoparquet").exists():
        pytest.skip("no build outputs")
    reg = gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")
    ind = pd.read_parquet(PROCESSED / "indicators.parquet").set_index("region_id")
    k = ind[reg["level"].reindex(ind.index).isin(levels.SUB)]
    parents, g = ind.loc[sorted(set(k["parent_id"]))], k.groupby("parent_id")
    assert len(k) > 900 and (g.size() >= 2).all() and (parents["level_no"] == 2).all() and (k["area_km2"] > 0).all()
    for col in ("gdp_usd", "gdp_share", "area_km2"):
        pd.testing.assert_series_equal(g[col].sum(), parents[col], rtol=1e-9, check_names=False)
    shape = boundaries.area_km2(reg.loc[parents.index])  # dissolve of the children
    assert ((parents["area_km2"] / shape - 1).abs() < 0.03).all()  # Amapá: IBGE area against a shape cut to the Natural Earth coast
    assert parents["pop_source"].eq("oecd_regional").all() and parents["flags"].map(lambda f: [x for x in f if x != "pop_scaled"] == ["aggregated", "contains_wikipedia_secondary"][:len(f) - ("pop_scaled" in f)]).all()
    assert k["iso3"].value_counts().to_dict() == {"BRA": 509, "MEX": 131, "CHN": 269, "CAN": 51}
    pop = g["pop"].sum(min_count=1)  # the parent keeps its own population; its children's, where they have one, is close to it
    assert ((pop / parents["pop"] - 1).abs().dropna() < 0.1).all() and pop.notna().sum() > 50
    assert k["gdp_usd"].notna().mean() > 0.99 and k["gdp_source"].notna().eq(k["gdp_usd"].notna()).all() and k["flags"].map(lambda f: "aggregated" not in f).all()


def test_built_meshes_tile_brazil_mexico_and_china_and_their_whole_states_fit_in():
    if not (PROCESSED / "regions.geoparquet").exists():
        pytest.skip("no build outputs")
    reg = gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")
    finest = reg[~reg.index.isin(reg["parent_id"])]
    for iso3, whole in (("BRA", 1), ("MEX", 1), ("CHN", 10)):
        g = finest[finest["iso3"] == iso3]
        km2 = g.to_crs(6933).geometry
        assert g.geometry.is_valid.all() and (g["level_no"] == 2).sum() == whole and (g["boundary_source_id"] != "natural_earth").all()
        assert km2.area.sum() == pytest.approx(km2.union_all().area, rel=1e-5)  # no overlaps
        country = reg.to_crs(6933).geometry["ISO3:" + iso3]
        assert country.area == pytest.approx(km2.area.sum(), rel=1e-5)  # the country is their dissolve
