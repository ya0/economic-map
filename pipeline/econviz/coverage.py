"""Share of world GDP by level tier, from data/processed (python -m econviz.coverage)."""
import geopandas as gpd
import pandas as pd

from .levels import SUB
from .paths import PROCESSED, REF_YEAR

TIER = {"country": "country", "admin1": "admin-1", "zone": "admin-1", "tl2": "admin-1", "nuts3": "NUTS3/TL3", "tl3": "NUTS3/TL3", "county": "finer", **dict.fromkeys(SUB, "finer")}


def tiers(ind: pd.DataFrame, levels: pd.Series, unallocated: pd.Series) -> pd.DataFrame:
    """World-GDP share and region count per tier; unallocated (extra-regio) GDP counts in the world total, tier 'unallocated'."""
    t = ind.assign(tier=ind["region_id"].map(levels).map(TIER))
    g = t.groupby("tier").agg(gdp=("gdp_usd", "sum"), regions=("region_id", "size"))
    g.loc["unallocated"] = [unallocated.sum(), 0]
    g["share_pct"] = 100 * g["gdp"] / g["gdp"].sum()
    return g.drop(columns="gdp").round(2)


def freshness(ind: pd.DataFrame, unallocated: pd.Series, ref=REF_YEAR) -> pd.Series:
    """World-GDP share (%) by age of the regional GDP shares: reference year, 1-2 years older, older; unallocated apart."""
    age = ref - ind["gdp_year"]
    band = pd.cut(age, [-99, 0, 2, 99], labels=["ref year", f"{ref - 2}-{ref - 1}", "older"])
    g = ind.groupby(band, observed=False)["gdp_usd"].sum()
    g["unallocated"] = unallocated.sum()
    return (100 * g / g.sum()).round(2)


def land(ind: pd.DataFrame, unallocated: pd.Series, holes: pd.DataFrame) -> pd.Series:
    """Of the finest regions (`ind`: region_id index, iso3, level_no, area_km2, gdp_usd, flags): % of land area and of world GDP
    in countries with values below country level, % of land and GDP in derived (`pop_share`) regions, and the open holes (km2)."""
    sub = ind["level_no"] > 1
    derived = ind["flags"].map(lambda f: "pop_share" in f)
    gdp = ind["gdp_usd"].sum() + unallocated.sum()
    pct = lambda m, c, t: round(100 * ind.loc[m, c].sum() / t, 2)
    return pd.Series({"land_below_country_pct": pct(sub, "area_km2", ind["area_km2"].sum()), "gdp_below_country_pct": pct(sub, "gdp_usd", gdp),
                      "land_derived_pct": pct(derived, "area_km2", ind["area_km2"].sum()), "gdp_derived_pct": pct(derived, "gdp_usd", gdp),
                      "open_holes_km2": round(holes.loc[~holes["ok"], "area_km2"].sum())})


def main():
    ind = pd.read_parquet(PROCESSED / "indicators.parquet")
    ind = ind[~ind["region_id"].isin(ind["parent_id"])]  # the finest regions only
    levels = gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")["level"]
    un = pd.read_parquet(PROCESSED / "unallocated.parquet")["unallocated_gdp_usd"]
    print(tiers(ind, levels, un).to_string())
    print(freshness(ind, un).rename("freshness_pct").to_string())
    print(land(ind.set_index("region_id"), un, pd.read_csv(PROCESSED / "holes.csv")).to_string())


if __name__ == "__main__":
    main()
