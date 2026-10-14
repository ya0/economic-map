"""Malaysia: DOSM GDP by state (open data CSV, supply side, 2015 constant prices, RM million). `Supra` is extra-regio GDP.
Constant prices: the values serve as shares only, and the layer is flagged `constant_prices`."""
import pandas as pd

from ..fetch import get
from ..obs import make

SOURCE = "my_dosm_gdp_state"
URL = "https://storage.dosm.gov.my/gdp/gdp_state_real_supply.csv"


def download():
    return get(SOURCE, URL, "gdp_state_real_supply.csv")


def parse(path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (observations, names[region_id, iso3, name, level, parent_id]); sector p0 is total GDP."""
    d = pd.read_csv(path)
    d = d[(d["series"] == "abs") & (d["sector"] == "p0")].assign(iso3="MYS", year=lambda x: x["date"].str[:4])
    d["region_id"] = "DOSM:" + d["state"]
    d["variable"] = d["state"].map(lambda s: "gdp_extra" if s == "Supra" else "gdp")
    names = d[d["variable"] == "gdp"].drop_duplicates("region_id").assign(name=lambda x: x["state"], level="admin1", parent_id=None)
    return (make(d, unit="MYR_million_2015_prices", source_id=SOURCE, note="constant_prices"),
            names[["region_id", "iso3", "name", "level", "parent_id"]].reset_index(drop=True))
