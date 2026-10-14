"""Eurostat NUTS3: GDP (current prices, M EUR), population on 1 Jan, land area. Extra-regio codes (..ZZZ) become `gdp_extra`."""
import re

import pandas as pd

from ..fetch import get
from ..obs import make

API = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/{}/{}?format=TSV&compressed=true"
TABLES = {"gdp": ("nama_10r_3gdp", "A.MIO_EUR.", "EUR_million_current", "eurostat_nuts3_gdp"),
          "pop": ("demo_r_pjangrp3", "A.T.NR.TOTAL.", "persons", "eurostat_nuts3_pop"),
          "area_km2": ("reg_area3", "A.L0008.KM2.", "km2", "eurostat_nuts3_area")}
NUTS3 = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}$")


def download():
    return {v: get(src, API.format(t, key), f"{t}.tsv.gz") for v, (t, key, _, src) in TABLES.items()}


def parse(path, variable: str, cc_to_iso3: dict) -> pd.DataFrame:
    d = pd.read_csv(path, sep="\t", compression="gzip", dtype=str)
    d = d.rename(columns=lambda c: c.strip())
    d["geo"] = d.iloc[:, 0].str.split(",").str[-1]
    d = d[d["geo"].str.match(NUTS3)]
    long = d.drop(columns=d.columns[0]).melt(id_vars="geo", var_name="year")
    long["value"] = pd.to_numeric(long["value"].str.extract(r"^\s*([\d.]+)")[0], errors="coerce")  # strips flags like ' p', ' e'
    long["iso3"] = long["geo"].str[:2].map(cc_to_iso3)
    long["region_id"] = "NUTS2024:" + long["geo"]
    extra = long["geo"].str.endswith("ZZ")
    long["variable"] = variable
    if variable == "gdp":
        long.loc[extra, "variable"] = "gdp_extra"
    else:
        long = long[~extra]
    _, _, unit, src = TABLES[variable]
    return make(long.dropna(subset=["iso3"]), unit=unit, source_id=src)
