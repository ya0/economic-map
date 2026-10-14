"""Kazakhstan: gross regional product 2024 (billion KZT, current prices) from the English Wikipedia list citing the Bureau of
National Statistics. Natural Earth has the pre-2022 regions, so the four newer units are summed into the unit they were cut from
(Abai into East Kazakhstan, Jetisu into Almaty Region, Ulytau into Karaganda, Shymkent into Turkistan); Almaty city and Astana
are units of their own. Ids are `KAZWP:<slug>`."""
import io
import json

import pandas as pd

from ..fetch import get
from ..obs import make

SOURCE = "kazwiki_grp"
YEAR = 2024
URL = "https://en.wikipedia.org/w/api.php?action=parse&format=json&prop=text%7Crevid&redirects=1&page=List_of_regions_of_Kazakhstan_by_GDP"
NAMES = {"Almaty": "Almaty City", "Astana": "Astana", "Abai Region": "East Kazakhstan", "East Kazakhstan Region": "East Kazakhstan",
         "Jetisu Region": "Almaty Region", "Almaty Region": "Almaty Region", "Ulytau Region": "Karaganda",
         "Karaganda Region": "Karaganda", "Shymkent": "Turkistan", "Turkistan Region": "Turkistan"}


def download():
    return get(SOURCE, URL, "kz.json")


def parse(path) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Returns (observations, names[region_id, iso3, name, level, parent_id], sum of the 20 listed units in billion KZT)."""
    t = pd.read_html(io.StringIO(json.loads(path.read_text(encoding="utf-8"))["parse"]["text"]["*"]))[0]
    t = t.iloc[:, :3].set_axis(["n", "name", "value"], axis=1)
    t = t[pd.to_numeric(t["n"], errors="coerce").notna()].assign(value=lambda d: pd.to_numeric(d["value"]))
    total = float(t["value"].sum())
    t["name"] = t["name"].map(lambda s: NAMES.get(s, s.removesuffix(" Region")))
    d = t.groupby("name", as_index=False)["value"].sum()
    d["region_id"] = "KAZWP:" + d["name"].str.lower().str.replace(r"[^a-z0-9]+", "-", regex=True).str.strip("-")
    d = d.assign(iso3="KAZ", variable="gdp", year=YEAR)
    names = d.assign(level="admin1", parent_id=None)[["region_id", "iso3", "name", "level", "parent_id"]]
    return make(d, unit="KZT_billion_current", source_id=SOURCE, note="wikipedia_secondary"), names, total
