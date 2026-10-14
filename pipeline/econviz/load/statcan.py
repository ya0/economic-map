"""Canada: census metropolitan areas (CMA) and one `Rest of <province>` region per province that has any, from Statistics
Canada: GDP at basic prices by CMA (table 36-10-0468, with a non-CMA row per province), population estimates of 1 July
by CMA (17-10-0148) and province (17-10-0009), CMA shapes of the 2021 cartographic boundary file. The remainder (flag
`remainder`) has the province's population minus its CMAs' and the province's shape minus theirs."""
import geopandas as gpd
import pandas as pd

from .. import boundaries
from ..fetch import get
from ..indicators import MAX_OFFSET
from ..obs import make
from ..paths import REF_YEAR

TABLE = ("https://www150.statcan.gc.ca/t1/tbl1/en/dtl!downloadDbLoadingData-nonTraduit.action?csvLocale=en&latestN=0"
         f"&startDate={REF_YEAR - MAX_OFFSET}0101&endDate={REF_YEAR}1231&checkedLevels=0D1%2C0D2%2C0D3%2C0D4%2C0D5&pid={{}}&selectedMembers={{}}")
TABLES = {"gdp": ("ca_statcan_cma_gdp", "3610046801", "%5B%5B%5D%5D"),  # name -> source, table, members (all areas; totals of sex and age)
          "pop": ("ca_statcan_pop", "1710014801", "%5B%5B%5D%2C%5B1%5D%2C%5B1%5D%5D"),
          "province": ("ca_statcan_pop", "1710000901", "%5B%5B%5D%5D")}
SHAPES = ("https://geo.statcan.gc.ca/geo_wa/rest/services/2021/Cartographic_boundary_files/MapServer/6/query?where=CMATYPE%3D%27B%27"
          "&outFields=CMAPUID,CMAUID,PRUID&outSR=4326&f=geojson&geometryPrecision=4&maxAllowableOffset=0.001")
REST = "Non-census metropolitan areas, "


def download():
    return ({k: get(src, TABLE.format(pid, members), f"{k}.csv") for k, (src, pid, members) in TABLES.items()},
            get("ca_statcan_cma", SHAPES, "cma_2021.geojson"))


def table(path) -> pd.DataFrame:
    """geo, code, year, value of the CMA, CMA-part, province and coded-less rows; `code` is the DGUID without vintage and
    type (CMA 535, part of a CMA in two provinces 35505, province 35). Quarterly tables keep 1 July."""
    d = pd.read_csv(path, dtype=str)
    d = d[(d["DGUID"].str[4:9].isin(["S0503", "S0505", "A0002"]) | d["DGUID"].isna()) & d["REF_DATE"].str[5:7].isin(["", "07"])]
    return pd.DataFrame({"geo": d["GEO"], "code": d["DGUID"].str[9:], "year": d["REF_DATE"].str[:4].astype(int), "value": pd.to_numeric(d["VALUE"])})


def layer(tables: dict, shapes, provinces: gpd.GeoSeries, parents: pd.Series):
    """provinces: level-2 region id -> shape; parents: province code (PRUID) -> level-2 region id."""
    t = {k: table(p) for k, p in tables.items()}
    g = gpd.read_file(shapes)
    g = g.assign(parent_id=g["PRUID"].map(parents), code=g["CMAUID"].where(~g["CMAUID"].duplicated(keep=False), g["CMAPUID"]))
    g = g[g["parent_id"].isin(provinces.index)].assign(region_id=lambda d: "CMA:" + d["CMAPUID"])
    whole = gpd.GeoSeries(g["parent_id"].map(provinces), crs=4326)
    g["geometry"] = boundaries.valid(g.geometry.make_valid().intersection(whole))  # no CMA reaches beyond its province's shape
    g = g.merge(t["gdp"].drop_duplicates("code")[["code", "geo"]].rename(columns={"geo": "name"}), on="code")
    rest = g.dissolve("PRUID").reset_index()[["PRUID", "parent_id", "geometry"]]
    rest["geometry"] = boundaries.valid(gpd.GeoSeries(rest["parent_id"].map(provinces), crs=4326).difference(rest.geometry))
    name = t["gdp"][t["gdp"]["code"].str.len() == 2].drop_duplicates("code").set_index("code")["geo"]  # PRUID -> province
    rest = rest.assign(region_id="CMA:" + rest["PRUID"] + "-rest", name="Rest of " + rest["PRUID"].map(name))
    regions = boundaries.frame(pd.concat([g, rest], ignore_index=True), iso3="CAN", level="metro", boundary_source_id="ca_statcan_cma",
                               boundary_vintage="CMA 2021 cartographic, generalised")

    key = g.set_index("code")["region_id"]
    of = lambda k: t[k].assign(region_id=t[k]["code"].map(key)).dropna(subset=["region_id"])
    gdp_rest = t["gdp"][t["gdp"]["geo"].str.startswith(REST)].assign(region_id=lambda d: "CMA:" + d["geo"].str[len(REST):].map({v: k for k, v in name.items()}) + "-rest")
    cmas = of("pop").assign(code=lambda d: d["region_id"].str[4:6]).groupby(["code", "year"], as_index=False)["value"].sum()
    pop_rest = t["province"].merge(cmas, on=["code", "year"], suffixes=("", "_cma")).assign(
        region_id=lambda d: "CMA:" + d["code"] + "-rest", value=lambda d: d["value"] - d["value_cma"])
    obs = [make(d.assign(iso3="CAN", variable=v), unit=unit, source_id=TABLES[v][0], note=note)
           for d, v, unit, note in ((of("gdp"), "gdp", "CAD_million", ""), (gdp_rest, "gdp", "CAD_million", "remainder"),
                                    (of("pop"), "pop", "persons", ""), (pop_rest, "pop", "persons", "remainder"))]
    return regions, pd.concat(obs, ignore_index=True)
