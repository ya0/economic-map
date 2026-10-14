"""Ukraine: State Statistics Service gross regional product (GRP) by region, current prices, UAH million, as published on
data.gov.ua (Ukrstat dataset 14; 2005-2021, the latest year published). Kyiv city (`8000000000`) is a region
of its own; Crimea and Sevastopol have no values since 2014 and are dropped; the `Ukraine` row (the sum of the regions) is dropped."""
import pandas as pd

from ..fetch import get
from ..obs import make

SOURCE = "ukrstat_grp"
URL = ("https://data.gov.ua/dataset/6e24b7d1-218f-4899-b187-19de3ad1ded6/resource/85b0bf89-1021-4e07-bafc-f7b7c5125555/download/"
       "14-valovii-regionalnii-produkt-u-faktichnikh-tsinakh-mln-grn.xlsx")
SHEET = "Валовий регіональний продукт en"
FIRST_YEAR = 2016


def download():
    return get(SOURCE, URL, "grp.xlsx")


def parse(path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (observations, names[region_id, iso3, name, level, parent_id]); ids are `UKRSTAT:<10-digit code>`."""
    d = pd.read_excel(path, sheet_name=SHEET, dtype=str).iloc[1:]  # row 0 is the Ukrainian header
    d = d[d["code"] != "0000000000"].assign(region_id=lambda x: "UKRSTAT:" + x["code"], iso3="UKR", variable="gdp",
                                            year=lambda x: x["period"].astype(int), value=lambda x: pd.to_numeric(x["data"]))
    d = d[d["year"] >= FIRST_YEAR].dropna(subset=["value"])
    d["name"] = d["attributes"].str.strip().replace({"City of Kyiv": "Kyiv City"}).where(
        lambda s: s.str.contains("City"), d["attributes"].str.strip() + " Oblast")
    names = d.drop_duplicates("region_id").assign(level="admin1", parent_id=None)[["region_id", "iso3", "name", "level", "parent_id"]]
    return make(d, unit="UAH_million_current", source_id=SOURCE), names.reset_index(drop=True)
