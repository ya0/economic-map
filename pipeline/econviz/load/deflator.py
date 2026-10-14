"""US GDP implicit price deflator (BEA series A191RD3A086NBEA, annual, via FRED). Constant dollars of base year B:
value_B = value_current * deflator[B] / deflator[year]."""
import pandas as pd

from ..fetch import get

SOURCE = "us_bea_deflator"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=A191RD3A086NBEA"


def download():
    return get(SOURCE, URL, "A191RD3A086NBEA.csv")


def parse(path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = ["date", "deflator"]
    d["year"] = pd.to_datetime(d["date"]).dt.year
    return d.dropna(subset=["deflator"])[["year", "deflator"]].reset_index(drop=True)

