"""Wikidata (secondary source) population of admin-1 units, keyed by ISO 3166-2 (P300): one SPARQL query per country.
Population P1082 takes the preferred-rank statement, else the latest dated one (undated statements are ignored)."""
import json
from urllib.parse import quote

import pandas as pd

from ..fetch import get

SOURCE = "wikidata"
ENDPOINT = "https://query.wikidata.org/sparql?format=json&query="
QUERY = ('SELECT ?item ?iso ?pop ?date ?rank ?area WHERE {{ ?item wdt:P300 ?iso . FILTER(STRSTARTS(?iso, "{}-")) '
         'OPTIONAL {{ ?item p:P1082 ?ps . ?ps ps:P1082 ?pop ; wikibase:rank ?rank . OPTIONAL {{ ?ps pq:P585 ?date }} }} '
         'OPTIONAL {{ ?item p:P2046/psn:P2046/wikibase:quantityAmount ?area }} }}')  # psn: area normalised to m2


def download(prefix: str):
    return get(SOURCE, ENDPOINT + quote(QUERY.format(prefix)), f"{prefix}.json", headers={"Accept": "application/sparql-results+json"})


def parse(path) -> pd.DataFrame:
    """One row per ISO 3166-2 code with data: iso, item, pop, pop_year, area_km2. A code shared by several items is dropped."""
    rows = [{k: v["value"] for k, v in b.items()} for b in json.loads(path.read_text(encoding="utf-8"))["results"]["bindings"]]
    d = pd.DataFrame(rows, columns=["item", "iso", "pop", "date", "rank", "area"])
    d["item"] = d["item"].astype("string").str.rsplit("/", n=1).str[-1]
    d["rank"] = d["rank"].astype("string").str.rsplit("#", n=1).str[-1]
    d = d[d["rank"] != "DeprecatedRank"].copy()
    for c in ("pop", "area"):
        d[c] = pd.to_numeric(d[c], errors="coerce")  # "unknown value" statements are URIs
    d["pop_year"] = pd.to_numeric(d["date"].astype("string").str.extract(r"^(\d{4})-")[0])
    d = d.dropna(subset=["pop", "pop_year"])
    d["area_km2"] = d["area"] / 1e6
    d["preferred"] = d["rank"] == "PreferredRank"
    d = d.sort_values(["iso", "item", "preferred", "pop_year"], ascending=[True, True, False, False]).drop_duplicates(["iso", "item"])
    d = d[~d.duplicated("iso", keep=False)]
    return d[["iso", "item", "pop", "pop_year", "area_km2"]].reset_index(drop=True)
