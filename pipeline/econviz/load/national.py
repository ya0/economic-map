"""National totals: World Bank first; IMF WEO only for countries World Bank lacks near the reference year (Taiwan, ...)."""
import pandas as pd

from ..indicators import MAX_OFFSET
from ..paths import REF_YEAR


def combine(wb: pd.DataFrame, imf: pd.DataFrame, ref=REF_YEAR, max_offset=MAX_OFFSET) -> pd.DataFrame:
    have = wb[(wb["variable"] == "gdp") & (wb["year"].rsub(ref).between(0, max_offset))]["iso3"].unique()
    return pd.concat([wb, imf[~imf["iso3"].isin(have)]], ignore_index=True)
