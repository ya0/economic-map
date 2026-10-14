"""`python -m econviz.build`: download -> load -> boundaries/crosswalk -> select level -> indicators -> validate -> export."""
import json
import sys

import geopandas as gpd
import pandas as pd

from . import boundaries, crosswalk, export, fill, holes, indicators, layers, levels, select, validate, zones
from .load import deflator, imf, manual, national, oecd, wikipedia, worldbank
from .obs import make
from .paths import PROCESSED, REF_YEAR, REFERENCE, WEB_PUBLIC


def national_data():
    wb, countries = worldbank.load()
    imf_obs = imf.parse(imf.download(), set(countries["iso3"]) | {"TWN"})
    return national.combine(wb, imf_obs)


def fill_area(regions: gpd.GeoDataFrame, obs: pd.DataFrame, ref=REF_YEAR) -> pd.DataFrame:
    """Regions without any sourced area get one computed from their geometry (flag area_computed)."""
    have = set(obs.loc[obs["variable"] == "area_km2", "region_id"])
    r = regions[~regions["region_id"].isin(have)]
    area = pd.DataFrame({"region_id": r["region_id"], "iso3": r["iso3"], "variable": "area_km2", "year": ref,
                         "value": boundaries.area_km2(r), "source_id": r["boundary_source_id"]})
    return pd.concat([obs, make(area, unit="km2", note="area_computed")], ignore_index=True)


def check(ind: pd.DataFrame, unallocated: pd.Series, national_obs: pd.DataFrame, whitelist: set) -> list[str]:
    """Final build-failing checks per country; returns all problems."""
    problems = validate.positive_area(ind) + validate.provenance(ind)
    for iso3, g in ind.groupby("iso3"):
        gdp = indicators.national_value(national_obs[national_obs["iso3"] == iso3], "gdp")
        pop = indicators.national_value(national_obs[national_obs["iso3"] == iso3], "pop")
        if gdp:
            problems += [f"{iso3}: {p}" for p in validate.gdp_sum(g, unallocated.get(iso3, 0.0), gdp[0])]
            if pop and len(g) > 1:
                problems += [f"{iso3}: {p}" for p in validate.per_capita_outliers(g, gdp[0] / pop[0], whitelist)]
        if pop:
            problems += [f"{iso3}: {p}" for p in validate.population(g, pop[0], tol=1e-6)]  # scaled: sums equal the total
    return problems


def all_levels(regions, ind: pd.DataFrame, ne0, ne1, national_pop: pd.DataFrame):
    """levels.py on the chosen regions: parents, coarser levels, the disputed region and `iso2` per row.
    ne0, ne1: Natural Earth countries and admin-1 units; national_pop: `levels.official_population`'s `own`."""
    tl = oecd.parse_names(oecd.download()[1])
    ne0 = ne0.assign(continent_id=levels.continent_id(ne0["continent"]))
    names = pd.concat([tl[tl["level"] == "tl2"].set_index("region_id")["name"], boundaries.us_state_names(),
                       ne0.set_index("region_id")["name"], ne0.drop_duplicates("continent").set_index("continent_id")["continent"]])
    continent = ne0.set_index("iso3")["continent_id"]
    regions = levels.hierarchy(regions, tl[tl["level"] == "tl3"].set_index("region_id")["parent_id"], continent)
    regions, ind = levels.aggregate(regions, ind, names, continent, national_pop)
    regions, ind = levels.add_disputed(regions, ind, ne1[ne1["iso_3166_2"].isin(levels.CRIMEA)].union_all())
    return regions, ind.assign(iso2=ind["iso3"].map(ne0.set_index("iso3")["iso2"]).fillna(""))


def run(ref_year=REF_YEAR):
    nat = national_data()
    ne0 = boundaries.attach(boundaries.natural_earth_countries(), boundaries.natural_earth_units(),
                            pd.read_csv(REFERENCE / "attach.csv"))
    countries = ne0.loc[ne0["iso3"].isin(nat["iso3"]), boundaries.COLUMNS]
    waivers = pd.read_csv(REFERENCE / "waivers.csv").set_index("iso3")["cover_tol"].to_dict()
    cw, ne, own = crosswalk.load(), boundaries.natural_earth_admin1(), fill.own_codes()
    layer_set = layers.build()
    layer_set["pop_zones"], admin1_coverage = zones.candidates(ne, ne0.set_index("iso3")["name"], nat, ref_year)  # last: below every sourced layer
    regions, obs, decisions = select.choose(layer_set, countries, nat, waivers, ref_year,
                                            fill.reference_population(cw, ne, own=own))
    obs = pd.concat([obs, manual.fill(manual.load(), regions, obs)], ignore_index=True)
    new_pop, wikidata_audit = fill.fill_population(regions, obs, decisions.set_index("iso3")["layer"].to_dict(),
                                                   cw, ne, nat, ref_year, own=own)
    obs = pd.concat([obs, new_pop], ignore_index=True)
    regions, obs = layers.cut_overlaps(regions, obs)
    subs = layers.sub(regions, countries.set_index("iso3").geometry)  # second subdivisions below the chosen level-2 regions
    for sub, _ in subs.values():
        regions, obs = layers.adopt(regions, obs, sub)
    obs = fill_area(regions, boundaries.add_attached_area(obs, ne0), ref_year)
    ind, unallocated = indicators.compute(regions.set_index("region_id")["level"], obs, nat, ref_year)
    own = ind[["pop", "pop_year", "pop_source"]].set_axis(["value", "year", "source_id"], axis=1)
    top = ind[["iso3", "pop"]]
    for name, (sub, o) in subs.items():
        iso3, n = sub["iso3"].iloc[0], len(regions)
        regions, ind, rejected = select.refine(regions, ind, sub, pd.concat([obs, fill_area(sub, o, ref_year)]), ref=ref_year)
        decisions.loc[len(decisions)] = {"iso3": iso3, "layer": name, "n_regions": len(regions) - n, "pop_dropped": False, "rejected": rejected}
    child_of = regions.set_index("region_id")["parent_id"]
    child_of = child_of[child_of.index.isin(ind.index) & child_of.isin(top.index)]
    ind, refined, scaling = indicators.scale_population(top, ind, child_of, indicators.national_population(nat, ref_year)["value"])
    own.loc[refined.index, "value"] = refined["pop"]
    whitelist = set(pd.read_csv(REFERENCE / "outlier_whitelist.csv")["region_id"])
    whitelist |= set(ind.index[ind["flags"].map(lambda f: "census_va_share" in f)])  # census value added is far from GDP in farming places
    problems = check(ind, unallocated, nat, whitelist)
    if problems:
        sys.exit("validation failed:\n" + "\n".join(problems[:50]))

    own = pd.concat([indicators.national_population(nat, ref_year), own.drop(index=ind.index, errors="ignore")])  # the replaced parents
    regions, ind = all_levels(regions, ind, ne0, ne, own)
    ind.loc[refined.index, "pop_raw"] = refined["pop_raw"]
    scaled = ind.index.isin(refined.index[refined["pop_raw"].notna()])
    ind["flags"] = [sorted({*f, "pop_scaled"}) if s else f for f, s in zip(ind["flags"], scaled)]
    ind = ind[[c for c in ind if c != "pop_raw"] + ["pop_raw"]]  # appended, never reordered
    far = scaling[(scaling["factor"] > 1.10) | (scaling["factor"] < 0.90)]
    print(f"population scaled: {scaling['factor'].notna().sum()} sets, {len(far)} with a factor above 1.10 or below 0.90: {far['set'].tolist()}")
    defl = deflator.parse(deflator.download())
    PROCESSED.mkdir(parents=True, exist_ok=True)
    left = holes.report(regions, boundaries.natural_earth_units().set_index("unit").geometry)  # logged, not failing
    print(f"holes: {len(left)} pieces of {holes.MIN_KM2} km2 or more open, {left['area_km2'].sum():.0f} km2 (holes.csv)")
    wikidata_audit.to_csv(PROCESSED / "wikidata_population.csv", index=False)
    scaling.to_csv(PROCESSED / "population_scaling.csv", index=False)
    whole = set(decisions.loc[decisions["layer"].isin(["country", "pop_zones"]), "iso3"])  # the crucial countries that no sourced layer splits
    layer = decisions.drop_duplicates("iso3").set_index("iso3")["layer"]
    cov = admin1_coverage[admin1_coverage["iso3"].isin(whole)].assign(layer=lambda d: d["iso3"].map(layer).map({"pop_zones": "zones"}).fillna("whole"))
    cov.to_csv(PROCESSED / "admin1_pop_coverage.csv", index=False)
    regions.to_parquet(PROCESSED / "regions.geoparquet")
    ind.reset_index().to_parquet(PROCESSED / "indicators.parquet")
    defl.to_parquet(PROCESSED / "deflator.parquet")
    decisions.assign(rejected=decisions["rejected"].map(json.dumps)).to_csv(PROCESSED / "selection.csv", index=False)
    unallocated.to_frame().to_parquet(PROCESSED / "unallocated.parquet")
    WEB_PUBLIC.mkdir(parents=True, exist_ok=True)
    (WEB_PUBLIC / "indicators.json").write_text(export.indicators_json(ind, defl, ref_year, unallocated))
    used = set(ind["gdp_source"].dropna()) | set(ind["pop_source"].dropna()) | set(ind["area_source"].dropna()) \
        | set(regions["boundary_source_id"].dropna()) | {deflator.SOURCE}
    (WEB_PUBLIC / "sources.json").write_text(export.sources_json(used, wikipedia.credits()))
    print(f"regions per level_no {regions['level_no'].value_counts().sort_index().to_dict()}, {decisions['layer'].value_counts().to_dict()}")


if __name__ == "__main__":
    run()
