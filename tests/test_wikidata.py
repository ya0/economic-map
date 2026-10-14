import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from econviz import crosswalk, fill
from econviz.load import wikidata
from conftest import observations


def bindings(*rows):
    """rows: (item, iso, pop, date, rank, area_m2) as the SPARQL JSON results shape them (missing values are absent keys)."""
    out = []
    for item, iso, pop, date, rank, area in rows:
        b = {"item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{item}"}, "iso": {"type": "literal", "value": iso}}
        if pop is not None:
            b["pop"] = {"type": "literal", "value": str(pop)}
            b["rank"] = {"type": "uri", "value": f"http://wikiba.se/ontology#{rank}"}
        if date:
            b["date"] = {"type": "literal", "value": f"{date}-01-01T00:00:00Z"}
        if area:
            b["area"] = {"type": "literal", "value": str(area)}
        out.append(b)
    return {"head": {"vars": []}, "results": {"bindings": out}}


def write(tmp_path, *rows):
    p = tmp_path / "x.json"
    p.write_text(json.dumps(bindings(*rows)))
    return wikidata.parse(p)


def test_parse_takes_preferred_rank_else_latest_dated_statement(tmp_path):
    d = write(tmp_path,
              ("Q1", "NG-LA", 100, "2006", "NormalRank", 4e9), ("Q1", "NG-LA", 300, "2016", "NormalRank", 4e9),
              ("Q1", "NG-LA", 250, "2012", "PreferredRank", 4e9), ("Q1", "NG-LA", 999, "2020", "DeprecatedRank", 4e9),
              ("Q2", "NG-KN", 50, "2010", "NormalRank", None), ("Q2", "NG-KN", 70, "2015", "NormalRank", None))
    r = d.set_index("iso")
    assert (r.loc["NG-LA", "pop"], r.loc["NG-LA", "pop_year"], r.loc["NG-LA", "area_km2"]) == (250, 2012, 4000)
    assert (r.loc["NG-KN", "pop"], r.loc["NG-KN", "pop_year"]) == (70, 2015) and pd.isna(r.loc["NG-KN", "area_km2"])


def test_parse_ignores_undated_and_ambiguous_codes(tmp_path):
    d = write(tmp_path, ("Q1", "NG-AN", None, None, None, None), ("Q2", "NG-LA", 5, None, "NormalRank", None),
              ("Q5", "NG-EN", "http://www.wikidata.org/.well-known/genid/1", "2020", "NormalRank", None),
              ("Q6", "NG-KD", 7, "http://www.wikidata.org/.well-known/genid/2", "NormalRank", None),
              ("Q3", "NG-OG", 8, "2020", "NormalRank", None), ("Q4", "NG-OG", 9, "2021", "NormalRank", None))
    assert d.empty  # no item with a dated population; NG-OG is claimed by two items


def km2(side):  # side in degrees at the equator
    return side * side * 111.3 ** 2


def inputs(pops=(100.0, 200.0, 300.0), areas=(1.0, 1.0, 1.0), years=(2020, 2020, 2020), national=600.0):
    """Country AAA: three admin-1 units (squares), regions R0..R2 map to units U0..U2; Wikidata data for ISO codes AA-0..AA-2."""
    ne = gpd.GeoDataFrame({"region_id": [f"NE1:{i}" for i in range(3)], "iso3": "AAA", "iso_3166_2": [f"AA-{i}" for i in range(3)],
                           "geometry": [box(i, 0, i + 1, 1) for i in range(3)]}, geometry="geometry", crs=4326)
    regions = pd.DataFrame({"region_id": [f"R{i}" for i in range(3)], "iso3": "AAA", "level": "admin1"})
    cw = pd.DataFrame({"layer": "dose", "region_id": [f"R{i}" for i in range(3)], "geo_id": [f"NE1:{i}" for i in range(3)]})
    wd = pd.DataFrame({"iso": [f"AA-{i}" for i in range(3)], "item": [f"Q{i}" for i in range(3)], "pop": pops,
                       "pop_year": years, "area_km2": [km2(a) for a in areas]})
    nat = observations([("ISO3:AAA", "AAA", "pop", 2020, national)])
    return regions, cw, ne, nat, lambda prefix: wd


def run(regions, cw, ne, nat, load, obs=None, **kw):
    gdp = observations([(r, "AAA", "gdp", 2024, 1.0) for r in regions["region_id"]])
    obs = gdp if obs is None else pd.concat([gdp, obs], ignore_index=True)
    return fill.fill_population(regions, obs, {"AAA": "dose"}, cw, ne, nat, 2024, load, **kw)


def test_fill_adds_wikidata_population_with_item_and_year():
    new, audit = run(*inputs())
    assert new.set_index("region_id")["value"].to_dict() == {"R0": 100, "R1": 200, "R2": 300}
    assert set(new["source_id"]) == {"wikidata"} and set(new["note"]) == {"wikidata"} and set(new["year"]) == {2020}
    assert audit.set_index("region_id").loc["R1", "items"] == "Q1" and set(audit["status"]) == {"filled"}


def test_fill_never_overrides_an_official_value():
    official = observations([("R0", "AAA", "pop", 2023, 111.0)])
    new, audit = run(*inputs(national=611.0), obs=official)
    assert sorted(new["region_id"]) == ["R1", "R2"] and "R0" not in set(audit["region_id"])


def test_fill_uses_only_the_chosen_layer_of_the_crosswalk():
    regions, cw, ne, nat, load = inputs()
    cw.loc[0, "layer"] = "other"
    assert sorted(run(regions, cw, ne, nat, load)[0]["region_id"]) == ["R1", "R2"]


@pytest.mark.parametrize("kwargs,why", [({"pops": (100.0, -5.0, 300.0)}, "not positive"),
                                        ({"pops": (100.0, float("nan"), 300.0)}, "no Wikidata"),
                                        ({"areas": (1.0, 4.0, 1.0)}, "area"),
                                        ({"years": (2020, 2005, 2020)}, "statement from 2005")])
def test_unit_failures_are_logged_and_reject_only_that_region(kwargs, why):
    new, audit = run(*inputs(national=400.0, **kwargs))
    bad = audit.set_index("region_id").loc["R1", "status"]
    assert why in bad and sorted(new["region_id"]) == ["R0", "R2"]


def test_region_dissolved_from_several_units_needs_all_of_them():
    for areas, expected in (((1.0, 4.0, 1.0), {"R2": 300}), ((1.0, 1.0, 1.0), {"R0": 300, "R2": 300})):
        regions, cw, ne, nat, load = inputs(areas=areas, national=600.0)
        cw["region_id"] = ["R0", "R0", "R2"]  # R0 = U0 + U1; with the wrong area U1 fails and takes R0 with it
        new, _ = run(regions[regions["region_id"] != "R1"], cw, ne, nat, load)
        assert new.set_index("region_id")["value"].to_dict() == expected


def grouped(own_area=2.0, national=550.0):
    """R0 = U0 + U1 and has its own code AA-R in Wikidata (250 people, `own_area` squares); R2 = U2."""
    regions, cw, ne, nat, load = inputs(national=national)
    cw["region_id"] = ["R0", "R0", "R2"]
    wd = pd.concat([load("AA"), pd.DataFrame({"iso": ["AA-R"], "item": ["Q9"], "pop": [250.0], "pop_year": [2024],
                                              "area_km2": [km2(1) * own_area]})], ignore_index=True)
    return regions[regions["region_id"] != "R1"], cw, ne, nat, lambda prefix: wd


def test_region_with_its_own_code_takes_that_value_instead_of_summing_its_units():
    new, audit = run(*grouped(), own=pd.Series({"R0": "AA-R"}))
    assert new.set_index("region_id")["value"].to_dict() == {"R0": 250, "R2": 300} and set(new["note"]) == {"wikidata"}
    assert audit.set_index("region_id").loc["R0", ["items", "pop_year", "status"]].tolist() == ["Q9", 2024, "filled"]
    assert run(*grouped(national=600.0))[0].set_index("region_id")["value"].to_dict() == {"R0": 300, "R2": 300}  # no own code: U0 + U1


def test_own_code_is_checked_against_the_geometry_of_the_whole_region():
    new, audit = run(*grouped(own_area=8.0), own=pd.Series({"R0": "AA-R"}))  # 8 squares vs the region's 2
    assert sorted(new["region_id"]) == ["R2"] and "area" in audit.set_index("region_id").loc["R0", "status"]


def test_units_sharing_one_code_count_it_once_against_their_summed_geometry():
    regions, cw, ne, nat, load = grouped(national=400.0)
    ne.loc[1, "iso_3166_2"] = "AA-0"  # a city carved out of U0 carries U0's code
    new, audit = run(regions, cw, ne, nat, load)
    assert new.set_index("region_id")["value"].to_dict() == {"R0": 100, "R2": 300}
    assert audit.set_index("region_id").loc["R0", "items"] == "Q0"


def test_own_codes_reference_table_names_crosswalked_regions_once():
    own = fill.own_codes()
    assert own.index.is_unique and own.str.match(r"^[A-Z]{2}-\w+$").all() and set(own.index) <= set(crosswalk.load()["region_id"])
    assert (own.str[:2] == own.index.str[3:6].map({"PHL": "PH", "PAK": "PK"})).all()


def test_unit_without_iso_code_is_rejected():
    regions, cw, ne, nat, load = inputs(national=500.0)
    ne.loc[0, "iso_3166_2"] = "-99"
    new, audit = run(regions, cw, ne, nat, load)
    assert audit.set_index("region_id").loc["R0", "status"] == "no ISO 3166-2 code" and len(new) == 2


def test_complete_fill_must_match_national_population():
    new, audit = run(*inputs(national=1000.0))  # regions total 600
    assert new.empty and set(audit["status"]) == {"rejected: population 40.0% off national"}


def test_incomplete_fill_may_not_exceed_national_population():
    regions, cw, ne, nat, load = inputs(pops=(100.0, 200.0, -1.0), national=250.0)
    new, audit = run(regions, cw, ne, nat, load)
    assert new.empty and "above national" in audit.loc[audit["region_id"] == "R0", "status"].iloc[0]
    assert len(run(*inputs(pops=(100.0, 200.0, -1.0), national=400.0))[0]) == 2


def test_reference_population_accepts_old_statements_but_not_ids_shared_by_two_layers():
    _, cw, ne, _, load = inputs(years=(2005, 2005, 2005))
    cw = pd.concat([cw, cw.iloc[[0]].assign(layer="oecd_tl2")], ignore_index=True)  # R0 is used by two layers
    assert fill.reference_population(cw, ne, load).to_dict() == {"R1": 200, "R2": 300}
