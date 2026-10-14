"""OECD regional database (SDMX DF_GDP carries GDP and population at TL2/TL3) plus the territorial correspondence table (names, parents)."""
import pandas as pd

from ..fetch import get
from ..indicators import MAX_OFFSET
from ..obs import make
from ..paths import REF_YEAR

SOURCE = "oecd_regional"
DATA = ("https://sdmx.oecd.org/public/rest/data/OECD.CFE.EDS,DSD_REG_ECO@DF_GDP,/all"
        f"?startPeriod={REF_YEAR - MAX_OFFSET - 1}&endPeriod={REF_YEAR}&dimensionAtObservation=AllDimensions")
TABLE = "https://webfs-cfe.oecd.org/files/.Stat/region/OECD%20Territorial%20correspondence%20-%20TL2024c.xlsx"
LEVEL = {"TL2": "tl2", "TL3": "tl3"}


def download():
    return (get(SOURCE, DATA, "df_gdp.csv", headers={"Accept": "application/vnd.sdmx.data+csv"}),
            get(SOURCE, TABLE, "territorial_correspondence.xlsx"))


def parse(path) -> pd.DataFrame:
    d = pd.read_csv(path, usecols=["TERRITORIAL_LEVEL", "REF_AREA", "MEASURE", "PRICES", "UNIT_MEASURE",
                                   "TIME_PERIOD", "OBS_VALUE", "COUNTRY"])
    d = d[d["TERRITORIAL_LEVEL"].isin(LEVEL)]
    gdp = (d["MEASURE"] == "GDP") & (d["PRICES"] == "V") & (d["UNIT_MEASURE"] == "USD")  # current prices, market exchange rates
    pop = (d["MEASURE"] == "POP") & (d["UNIT_MEASURE"] == "PS")
    d = d[gdp | pop].assign(variable=lambda x: x["MEASURE"].map({"GDP": "gdp", "POP": "pop"}))
    d["unit"] = d["variable"].map({"gdp": "USD_current_market", "pop": "persons"})
    d["level"] = d["TERRITORIAL_LEVEL"].map(LEVEL)
    d["region_id"] = "OECD:" + d["REF_AREA"]
    extra = d["REF_AREA"].str.endswith("ZZ")  # "<country>, not regionalised" -> unallocated GDP
    d.loc[extra & (d["variable"] == "gdp"), "variable"] = "gdp_extra"
    d = d[~(extra & (d["variable"] == "pop"))]
    d = d.rename(columns={"COUNTRY": "iso3", "TIME_PERIOD": "year", "OBS_VALUE": "value"})
    return make(d, source_id=SOURCE).merge(d[["region_id", "variable", "year", "level"]].drop_duplicates(),
                                           on=["region_id", "variable", "year"])


def parse_names(xlsx) -> pd.DataFrame:
    """region_id, name, parent_id, level from the correspondence table (TL2024 plus TL2021 sheet for older codes)."""
    frames = []
    for sheet in ("Regions TL2024", "Regions - TL2021"):
        raw = pd.read_excel(xlsx, sheet_name=sheet, header=None)
        h = raw.index[raw.iloc[:, 1].astype(str) == "REG_ID"]
        t = raw.iloc[h[0] + 1:(h[1] if len(h) > 1 else None)].copy()
        t.columns = raw.iloc[h[0]].astype(str)
        name = next(c for c in t.columns if c.lower().startswith(("name (eng", "regional name (eng")))
        frames.append(pd.DataFrame({"region_id": "OECD:" + t["REG_ID"].astype(str), "name": t[name],
                                    "parent_id": "OECD:" + t["Hierarchical relations"].astype(str),
                                    "level": t["TL"].astype(str).str.strip().map({"2": "tl2", "3": "tl3"})}).dropna(subset=["level"]))
    return pd.concat(frames).drop_duplicates(["region_id", "level"]).reset_index(drop=True)
