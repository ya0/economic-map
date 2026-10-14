"""US counties: BEA GDP (CAGDP1 line 3, current $ thousands), Census population estimates and Gazetteer land area.
BEA merges some units (Virginia independent cities, Maui+Kalawao); members are resolved from the names and dissolved.
Connecticut is one unit (CT_STATE): BEA and Census use planning regions from 2023, which have no geometry here."""
import zipfile

import pandas as pd

from .. import boundaries
from ..fetch import get
from ..obs import make

BEA = "https://apps.bea.gov/regional/zip/CAGDP1.zip"
POP = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv"
CT_STATE = "09000"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2021_Gazetteer/2021_Gaz_counties_national.zip"


def download():
    return (get("us_bea_cagdp", BEA, "CAGDP1.zip"), get("us_census_popest", POP, "co-est2025-alldata.csv"),
            get("us_census_gazetteer", GAZ, "gaz_counties_2021.zip"))


def parse_bea(zip_path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if "ALL_AREAS" in n)
        d = pd.read_csv(z.open(name), encoding="latin1", dtype={"GeoFIPS": str}, low_memory=False)
    d = d[d["LineCode"] == 3]
    d = d.assign(fips=d["GeoFIPS"].astype(str).str.strip('" '))
    d = d[(d["fips"].str.len() == 5) & (~d["fips"].str.endswith("000") | (d["fips"] == CT_STATE))]
    years = [c for c in d.columns if c.isdigit()]
    long = d.melt(id_vars=["fips", "GeoName"], value_vars=years, var_name="year", value_name="value")
    long["value"] = pd.to_numeric(long["value"], errors="coerce") * 1000  # $ thousands -> $
    return long[long["year"].astype(int) >= 2020].dropna(subset=["value"])  # drops retired units (old Alaska areas, CT planning regions)


def parse_pop(path) -> pd.DataFrame:
    d = pd.read_csv(path, encoding="latin1", usecols=lambda c: c in ("STATE", "COUNTY") or c.startswith("POPESTIMATE"))
    d = d[(d["COUNTY"] > 0) | (d["STATE"] == 9)]
    d["fips"] = d["STATE"].astype(str).str.zfill(2) + d["COUNTY"].astype(str).str.zfill(3)
    long = d.melt(id_vars="fips", value_vars=[c for c in d if c.startswith("POPESTIMATE")], var_name="year")
    long["year"] = long["year"].str[-4:]
    return long


def parse_gaz(zip_path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        d = pd.read_csv(z.open(z.namelist()[0]), sep="\t", dtype={"GEOID": str})
    return pd.DataFrame({"fips": d["GEOID"], "area_km2": d["ALAND"] / 1e6})


def groups(bea_names: pd.Series, counties) -> dict[str, list[str]]:
    """Map each BEA id that is not a Census county to its member county FIPS.
    BEA names members `A, B + C, ST*`: in Virginia the first is a county and the rest independent cities."""
    out = {}
    merged = bea_names[~bea_names.index.isin(counties["GEOID"]) & bea_names.str.contains("+", regex=False)]
    for fips, name in merged.items():
        tokens = [t.strip() for t in name.rsplit(",", 1)[0].replace("+", ",").split(",")]
        state = counties[counties["GEOID"].str[:2] == fips[:2]]
        members = []
        for i, t in enumerate(tokens):
            lsad = "25" if fips.startswith("51") and i > 0 else "06"
            t = t[:-5] if i > 0 and t.endswith(" City") else t
            hit = state[(state["NAME"] == t) & (state["LSAD"] == lsad)]
            assert len(hit) == 1, (name, t)
            members.append(hit["GEOID"].iloc[0])
        out[fips] = members
    return out


def layer(bea_zip, pop_csv, gaz_zip, counties):
    """counties: boundaries.us_counties() with GEOID/name/lsad. Returns (regions, observations)."""
    c = counties.assign(GEOID=counties["region_id"].str[5:], NAME=counties["name"].str.rsplit(",", n=1).str[0],
                        LSAD=counties["lsad"])
    bea = parse_bea(bea_zip)
    bea = bea[bea["fips"].isin(c["GEOID"]) | bea["GeoName"].str.contains("+", regex=False) | (bea["fips"] == CT_STATE)]
    grp = groups(bea.drop_duplicates("fips").set_index("fips")["GeoName"], c)
    grp[CT_STATE] = list(c.loc[c["GEOID"].str[:2] == "09", "GEOID"])
    member_of = {m: k for k, ms in grp.items() for m in ms}
    key = lambda f: member_of.get(f, f)
    geo = c.assign(key=c["GEOID"].map(key))
    geo = geo[geo["key"].isin(bea["fips"])]
    regions = geo.dissolve(by="key", aggfunc={"name": "first", "iso3": "first", "level": "first", "parent_id": "first",
                                              "boundary_source_id": "first", "boundary_vintage": "first"}).reset_index()
    regions["region_id"] = "FIPS:" + regions["key"]
    for k, ms in grp.items():  # merged unit: use the BEA name
        regions.loc[regions["key"] == k, "name"] = bea.loc[bea["fips"] == k, "GeoName"].iloc[0].rstrip("*")
    regions = regions[boundaries.COLUMNS]
    pop = parse_pop(pop_csv).assign(fips=lambda d: d["fips"].map(key)).groupby(["fips", "year"], as_index=False)["value"].sum()
    area = parse_gaz(gaz_zip).assign(fips=lambda d: d["fips"].map(key)).groupby("fips", as_index=False)["area_km2"].sum()
    obs = [make(bea.rename(columns={"fips": "k"}).assign(region_id=lambda d: "FIPS:" + d["k"], iso3="USA", variable="gdp"),
                unit="USD_current", source_id="us_bea_cagdp"),
           make(pop.assign(region_id=lambda d: "FIPS:" + d["fips"], iso3="USA", variable="pop"), unit="persons",
                source_id="us_census_popest"),
           make(area.assign(region_id=lambda d: "FIPS:" + d["fips"], iso3="USA", variable="area_km2", year=2021,
                            value=lambda d: d["area_km2"]), unit="km2", source_id="us_census_gazetteer")]
    return regions, pd.concat(obs, ignore_index=True)
