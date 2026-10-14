"""2020 census population of the Chinese prefectures from Chinese Wikipedia (secondary; flag `wikipedia_secondary`).
Every table cites the State Council's county-level census compendium or the provincial 7th-census bulletins. Two
tables per prefecture are read: the national city ranking and the province's list; where they differ, the value that
brings the province's sum closest to the NBS province total is kept (each page has a few typos, never the same ones)."""
import io
import itertools
import json
import re
from urllib.parse import quote

import pandas as pd

from ..fetch import get
from ..obs import make
from ..paths import REFERENCE

SOURCE = "zhwiki_census"
API = "https://zh.wikipedia.org/w/api.php?action=parse&format=json&formatversion=2&redirects=1&prop="
RANKING = "中華人民共和國城市人口排名"
PROVINCES = ("云南省各市州 内蒙古自治区各盟市 吉林省各市州 四川省各市州 宁夏回族自治区各地级市 安徽省各地级市 山东省各地级市 山西省各地级市 "
             "广东省各地级市 广西壮族自治区各地级市 新疆维吾尔自治区各地州市 江苏省各地级市 江西省各地级市 河北省各地级市 河南省各地级市 "
             "浙江省各地级市 海南省各市县 湖北省各市州 湖南省各市州 甘肃省各市州 福建省各地级市 贵州省各市州 辽宁省各地级市 陕西省各地级市 "
             "青海省各市州").split()
SINGLES = ("大兴安岭地区", "阿里地区")  # prefectures that have no province list; the page text gives the census figure
TOLERANCE = 0.01  # a province's prefectures may not sum to more than the census province total by more than this
SHORT = 0.10  # nor to less by more than this: COD-AB lacks a few county-level units (Wenchang, Xinjiang's cities, 4% to 6%)
ALIAS = {"株州市": "株洲市"}  # COD-AB misspells Zhuzhou
MAX_FLIPS = 12


def page(title: str, prop: str = "text%7Crevid") -> dict:
    return json.loads(get(SOURCE, API + prop + "&page=" + quote(title), f"{prop[:4]}_{title}.json").read_text(encoding="utf-8"))["parse"]


def clean(s) -> str:
    """A name without footnote marks and bracketed remarks."""
    return re.sub(r"[\[(（【〔].*?[\])）】〕]", "", str(s)).strip()


def number(s) -> float:
    return pd.to_numeric(re.sub(r"\[.*", "", str(s)).replace(",", ""), errors="coerce")


def read(title: str, name: int, value: int) -> pd.Series:
    """`name` -> census population of the first table of a page, from its columns `name` and `value`; empty if the
    column is in units of 10,000 (some provinces list the year-end estimate instead of the census)."""
    t = pd.read_html(io.StringIO(page(title)["text"]))[0]
    if "万" in " ".join(map(str, t.columns[value])):
        return pd.Series(dtype=float)
    s = pd.Series(t.iloc[:, value].map(number).values, index=t.iloc[:, name].map(clean)).dropna()
    return s[~s.index.str.endswith(("省", "自治区"))][lambda x: ~x.index.duplicated()]


def singles() -> pd.Series:
    """Figure of a prefecture's own page ("全区[[常住人口]]为331,276人")."""
    return pd.Series({t: number(re.search(r"常住人口(?:\]\])?为([\d,]+)人", page(t, "wikitext%7Crevid")["wikitext"]).group(1)) for t in SINGLES})


def lookup(pool: pd.Series, zh: str) -> float:
    """Exact name, else the one entry of the same kind (州, 盟, other) that starts with the same two characters
    (autonomous prefectures are listed as `凉山州`, Nagqu's prefecture became a city)."""
    if zh in pool.index:
        return pool[zh]
    kind = lambda n: n[-1] if n.endswith(("州", "盟")) else ""
    hit = pool[(pool.index.str[:2] == zh[:2]) & (pool.index.map(kind) == kind(zh))]
    return hit.iloc[0] if len(hit) == 1 else float("nan")


def token(s) -> str:
    """First word of a province name, lower case (`Anhui Province` -> `anhui`)."""
    return str(s).lower().split(" ")[0]


def pick(g: pd.DataFrame, total: float) -> pd.Series:
    """One value per unit of a province: where the two pages differ, the choice whose sum is closest to `total`
    (ties keep the ranking, which cites the compendium)."""
    v = g["rank"].fillna(g["prov"])
    diff = g.index[g["rank"].notna() & g["prov"].notna() & (g["rank"] != g["prov"])]
    if 0 < len(diff) <= MAX_FLIPS and total == total:
        base = v.sum() - v[diff].sum()
        alt = g.loc[diff, ["rank", "prov"]].to_numpy()
        flips = min(itertools.product((0, 1), repeat=len(diff)),
                    key=lambda f: abs(base + sum(alt[i][c] for i, c in enumerate(f)) - total))
        v[diff] = [alt[i][c] for i, c in enumerate(flips)]
    return v


def china(units: pd.DataFrame, census: pd.DataFrame) -> pd.DataFrame:
    """2020 census population per COD prefecture (`units`: code, zh, province; `census`: province, population from
    NBS) as observations of `COD:<code>`. A province whose sum is off the census total by more than TOLERANCE above
    or SHORT below gets nothing."""
    rank = read(RANKING, 1, 3)
    prov = pd.concat([read(t + "人口列表", 0, 1) for t in PROVINCES]).pipe(lambda s: s[~s.index.duplicated()])
    pool = pd.concat([prov, singles()])
    zh = units["zh"].map(clean).replace(ALIAS)
    got = units.assign(prov=zh.map(lambda z: lookup(pool, z)), rank=zh.map(lambda z: lookup(rank, z)), key=units["province"].map(token))
    total = census.assign(key=census["province"].map(token)).set_index("key")["population"]
    got["pop"] = pd.concat([pick(g, total.get(k, float("nan"))) for k, g in got.groupby("key")])
    sums = got.groupby("key")["pop"].sum() / total
    keep = got[got["key"].map(lambda k: 1 - SHORT <= sums.get(k, float("nan")) <= 1 + TOLERANCE) & got["pop"].notna()]
    return make(keep.assign(region_id="COD:" + keep["code"], iso3="CHN", variable="pop", year=2020, value=keep["pop"]),
                unit="persons", source_id=SOURCE, note="wikipedia_secondary")


def census_totals() -> pd.DataFrame:
    return pd.read_csv(REFERENCE / "china_census2020.csv")
