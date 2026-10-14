"""DOSE v2.14 (Wenz et al.): reported admin-1 GRP in local currency and population, keyed by GADM GID_1 (used for matching only)."""
import pandas as pd

from ..fetch import get
from ..obs import make

SOURCE = "dose"
URL = "https://zenodo.org/api/records/20035157/files/DOSE_V2.14.csv/content"


def download():
    return get(SOURCE, URL, "DOSE_V2.14.csv")


def parse(path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (observations, names[region_id, iso3, name])."""
    d = pd.read_csv(path, usecols=["country", "region", "GID_0", "GID_1", "year", "grp_lcu", "pop"], low_memory=False)
    d["region_id"] = "GID:" + d["GID_1"]
    d = d.rename(columns={"GID_0": "iso3"})
    long = d.melt(id_vars=["region_id", "iso3", "year"], value_vars=["grp_lcu", "pop"], var_name="variable", value_name="value")
    long["unit"] = long["variable"].map({"grp_lcu": "LCU_current", "pop": "persons"})
    long["variable"] = long["variable"].map({"grp_lcu": "gdp", "pop": "pop"})
    names = d.drop_duplicates("region_id")[["region_id", "iso3", "region"]].rename(columns={"region": "name"})
    return make(long, source_id=SOURCE), names.reset_index(drop=True)
