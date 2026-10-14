"""IMF WEO via api.imf.org (SDMX-CSV): nominal GDP in US$ and population. Fallback for countries missing from WDI (Taiwan)."""
import pandas as pd

from ..fetch import get
from ..obs import make
from ..paths import REF_YEAR

SOURCE = "imf_weo"
URL = ("https://api.imf.org/external/sdmx/2.1/data/WEO/*.NGDPD+LP.A?startPeriod=2015&endPeriod={}")


def download():
    return get(SOURCE, URL.format(REF_YEAR), "weo.csv", headers={"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"})


def parse(path, iso3s) -> pd.DataFrame:
    d = pd.read_csv(path, usecols=["COUNTRY", "INDICATOR", "TIME_PERIOD", "OBS_VALUE"])
    d = d[d["COUNTRY"].isin(iso3s)]
    d["variable"] = d["INDICATOR"].map({"NGDPD": "gdp", "LP": "pop"})
    d["unit"] = d["variable"].map({"gdp": "USD_current", "pop": "persons"})
    d = d.rename(columns={"COUNTRY": "iso3", "TIME_PERIOD": "year", "OBS_VALUE": "value"})
    d["region_id"] = "ISO3:" + d["iso3"]
    return make(d, source_id=SOURCE, note="imf_estimate")
