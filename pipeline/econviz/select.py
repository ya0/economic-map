"""Pick one level per country: the first candidate layer (finest first) that passes the usability checks, else the whole country."""
import geopandas as gpd
import pandas as pd

from . import indicators, validate
from .paths import REF_YEAR

MIN_GDP_COVERAGE = 0.95  # share of a layer's regions that must have GDP in the shared year
MAX_GDP_UNMAPPED = 0.01  # share of a country's regional GDP that may belong to regions without geometry
FRESHER = ("wikipedia", "dosm", "ukrstat", "ruwiki", "kazwiki")  # national-source layers that replace an already usable layer if their GDP year is this much newer
MIN_YEARS_NEWER = 2


def layer_problems(regions: gpd.GeoDataFrame, obs: pd.DataFrame, country_geom, tol: float,
                   ref=REF_YEAR, reference_pop: pd.Series | None = None) -> list[str]:
    """Reasons a layer cannot represent the country (empty = usable). Population is judged separately (see choose)."""
    if len(regions) < 2:
        return ["fewer than 2 regions"]
    gdp = obs[(obs["variable"] == "gdp") & obs["region_id"].isin(regions["region_id"])]
    y = indicators.shared_year(gdp, ref)
    if y is None:
        return ["no GDP near reference year"]
    cov = gdp[gdp["year"] == y]["region_id"].nunique() / len(regions)
    problems = [f"GDP coverage {cov:.0%}"] if cov < MIN_GDP_COVERAGE else []
    every = obs[(obs["variable"] == "gdp") & (obs["iso3"] == regions["iso3"].iloc[0]) & (obs["year"] == y)].drop_duplicates("region_id")
    lost = every.loc[~every["region_id"].isin(regions["region_id"]), "value"].sum() / every["value"].sum()
    problems += [f"{lost:.1%} of GDP in regions without geometry"] if lost > MAX_GDP_UNMAPPED else []
    if reference_pop is not None:
        pop = obs[(obs["variable"] == "pop") & obs["region_id"].isin(regions["region_id"])].sort_values("year")
        problems += validate.swapped_units(pop.drop_duplicates("region_id", keep="last").set_index("region_id")["value"], reference_pop)
    return problems + validate.coverage(regions, country_geom, tol) + validate.overlaps(regions)


def gdp_year(regions: gpd.GeoDataFrame, obs: pd.DataFrame, ref=REF_YEAR):
    return indicators.shared_year(obs[(obs["variable"] == "gdp") & obs["region_id"].isin(regions["region_id"])], ref)


def whole_country(countries: gpd.GeoDataFrame, national: pd.DataFrame, iso3s):
    """Whole-country regions and their observations (the national series), for countries not split."""
    reg = countries[countries["iso3"].isin(iso3s)]
    obs = national[national["iso3"].isin(iso3s) & national["variable"].isin(["gdp", "pop", "area_km2"])]
    return reg, obs


def choose(layers: dict, countries: gpd.GeoDataFrame, national: pd.DataFrame, waivers: dict[str, float], ref=REF_YEAR,
           reference_pop: pd.Series | None = None):
    """Returns (regions, observations, decisions). `countries` has an iso3 column; `waivers` maps iso3 -> area tolerance;
    `reference_pop` (region_id -> population) is the independent population that crosswalked layers are compared to."""
    geom = countries.set_index("iso3")["geometry"]
    chosen, log = {}, []
    for iso3 in sorted(set(national["iso3"]) & set(geom.index)):
        reasons = {}
        for name, (reg, obs) in layers.items():
            r = reg[reg["iso3"] == iso3]
            if r.empty or (iso3 in chosen and name not in FRESHER):
                continue
            problems = layer_problems(r, obs, geom[iso3], waivers.get(iso3, validate.COVER_TOL), ref, reference_pop)
            if not problems and iso3 in chosen and gdp_year(r, obs, ref) < gdp_year(*chosen[iso3][1:], ref=ref) + MIN_YEARS_NEWER:
                problems = [f"not {MIN_YEARS_NEWER} years newer than {chosen[iso3][0]}"]
            if not problems:
                o = obs[obs["region_id"].isin(r["region_id"]) | ((obs["variable"] == "gdp_extra") & (obs["iso3"] == iso3))]
                chosen[iso3] = (name, r, o)
                continue
            reasons[name] = "; ".join(problems)
        log.append({"iso3": iso3, "layer": chosen[iso3][0] if iso3 in chosen else "country",
                    "n_regions": len(chosen[iso3][1]) if iso3 in chosen else 1, "rejected": reasons})
    reg, obs = whole_country(countries, national, [i for i in geom.index if i in set(national["iso3"]) and i not in chosen])
    regions = pd.concat([reg] + [c[1] for c in chosen.values()], ignore_index=True)
    observations = pd.concat([obs] + [c[2] for c in chosen.values()], ignore_index=True)
    return gpd.GeoDataFrame(regions, geometry="geometry", crs=4326), observations, pd.DataFrame(log)


def refine(regions: gpd.GeoDataFrame, ind: pd.DataFrame, sub: gpd.GeoDataFrame, obs: pd.DataFrame, ref=REF_YEAR):
    """Second subdivisions below chosen regions. `sub`: regions whose `parent_id` is a chosen region; `obs`: their
    observations and those of the chosen regions; `ind`: indicators of the chosen regions. A parent whose children
    pass `layer_problems` against its shape is replaced by them: a child gets its share of the children's GDP times
    the parent's GDP, so the parent (rebuilt as their sum by `levels.aggregate`) keeps its value; their population is scaled
    to the parent's afterwards (`indicators.scale_population`). A parent whose children fail stays as it is. Returns (regions, ind, {parent: reason})."""
    geom, rejected, new = regions.set_index("region_id")["geometry"], {}, []
    for pid, kids in sub[sub["parent_id"].isin(ind.index)].groupby("parent_id"):
        o, parent = obs[obs["region_id"].isin(kids["region_id"])], ind.loc[pid]
        problems = layer_problems(kids, o, geom[pid], validate.COVER_TOL, ref)
        if problems:
            rejected[pid] = "; ".join(problems)
            continue
        tab = indicators.split_country(o, parent["gdp_usd"], ref)[0]
        new.append(tab.assign(iso3=parent["iso3"], year=parent["year"], gdp_share=tab["gdp_share"] * parent["gdp_share"], parent_id=pid))
    if not new:
        return regions, ind, rejected
    new = indicators.derive(pd.concat(new), ref)
    done = set(new.pop("parent_id"))
    regions = pd.concat([regions[~regions["region_id"].isin(done)], sub[sub["parent_id"].isin(done)]], ignore_index=True)
    return regions, pd.concat([ind.drop(index=done), new[ind.columns]]), rejected
