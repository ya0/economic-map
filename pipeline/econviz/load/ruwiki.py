"""Russia: gross regional product 2023 by federal subject (billion RUB, current prices), from the Russian Wikipedia list
citing Rosstat (the English list lacks Chechnya, Buryatia, Kalmykia and Magadan). Regions get the English names of the
English list's `Russian name` column (rows of the Russian page are matched on a stripped key; six names are given here).
Crimea and Sevastopol are dropped (the disputed region has no values). The page's total row is the check figure."""
import io
import json
import re

import pandas as pd

from ..fetch import get
from ..obs import make

SOURCE = "ruwiki_grp"
YEAR = 2023
PAGE = "https://ru.wikipedia.org/w/api.php?action=parse&format=json&prop=text%7Crevid&redirects=1&page=" + \
    "Список_субъектов_Российской_Федерации_по_валовому_продукту"
EN = "https://en.wikipedia.org/w/api.php?action=parse&format=json&prop=text%7Crevid&redirects=1&page=List_of_Russian_federal_subjects_by_GRDP"
EXTRA = {"Удмуртская Республика": "Udmurtia", "Чувашская Республика": "Chuvashia", "Республика Бурятия": "Buryatia",
         "Магаданская область": "Magadan Oblast", "Чеченская Республика": "Chechnya", "Республика Калмыкия": "Kalmykia"}
DROP = {"Republic of Crimea", "Sevastopol"}


def key(s) -> str:
    s = re.split(r"[—(\-–]", str(s))[0].lower()
    return re.sub(r"[^а-яё]", "", re.sub(r"\b(республика|область|край|автономный|автономная|округ|город|федерального|значения)\b", "", s))


def download():
    return get(SOURCE, PAGE, "ru.json"), get(SOURCE, EN, "en.json")


def revisions(paths) -> tuple[int, int]:
    return tuple(json.loads(p.read_text(encoding="utf-8"))["parse"]["revid"] for p in paths)


def _table(path, **kw) -> pd.DataFrame:
    return pd.read_html(io.StringIO(json.loads(path.read_text(encoding="utf-8"))["parse"]["text"]["*"]), **kw)[0]


def parse(paths) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Returns (observations, names[region_id, iso3, name, level, parent_id], page total in billion RUB); ids are `RUWP:<slug>`."""
    ru, en = _table(paths[0], thousands=None, decimal=","), _table(paths[1])
    bridge = dict(zip(en["Russian name"].map(key), en["Federal subject"])) | {key(k): v for k, v in EXTRA.items()}
    num = pd.to_numeric(ru["2023"].astype(str).str.replace(r"[\s\xa0]", "", regex=True).str.replace(",", "."), errors="coerce")
    total = float(num[ru["Субъект"].str.startswith("всего")].iloc[0])
    d = pd.DataFrame({"name": ru["Субъект"].map(lambda s: bridge.get(key(s))), "value": num}).dropna()
    d = d[~d["name"].isin(DROP) & (d["value"] != total)].drop_duplicates("name")
    d["region_id"] = "RUWP:" + d["name"].str.lower().str.replace(r"[^a-z0-9]+", "-", regex=True).str.strip("-")
    d = d.assign(iso3="RUS", variable="gdp", year=YEAR)
    names = d.assign(level="admin1", parent_id=None)[["region_id", "iso3", "name", "level", "parent_id"]]
    return make(d, unit="RUB_billion_current", source_id=SOURCE, note="wikipedia_secondary"), names.reset_index(drop=True), total
