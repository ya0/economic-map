"""World Bank WDI national GDP (current US$), population and land area via the v2 API."""
import json

import pandas as pd

from ..fetch import get
from ..obs import make
from ..paths import RAW, REF_YEAR

SOURCE = "wb_wdi"
BASE = "https://api.worldbank.org/v2/country/all/indicator/{}?format=json&per_page=20000&date=2000:{}"
INDICATORS = {"gdp": ("NY.GDP.MKTP.CD", "USD_current"), "pop": ("SP.POP.TOTL", "persons"),
              "area_km2": ("AG.LND.TOTL.K2", "km2")}
COUNTRIES = "https://api.worldbank.org/v2/country?format=json&per_page=400"


def download():
    for var, (code, _) in INDICATORS.items():
        get(SOURCE, BASE.format(code, REF_YEAR), f"{var}.json")
    get(SOURCE, COUNTRIES, "countries.json")


def parse(indicator_json: list, unit: str, variable: str, countries: pd.DataFrame) -> pd.DataFrame:
    rows = pd.DataFrame([{"iso3": r["countryiso3code"], "year": r["date"], "value": r["value"]}
                         for r in indicator_json[1]])
    rows = rows[rows["iso3"].isin(countries["iso3"])]
    rows["region_id"] = "ISO3:" + rows["iso3"]
    return make(rows, variable=variable, unit=unit, source_id=SOURCE)


def parse_countries(country_json: list) -> pd.DataFrame:
    """Real countries only (WB marks aggregates with region 'Aggregates')."""
    df = pd.DataFrame([{"iso3": c["id"], "name": c["name"], "region": c["region"]["value"]} for c in country_json[1]])
    return df[df["region"] != "Aggregates"][["iso3", "name"]].reset_index(drop=True)


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    download()
    read = lambda n: json.loads((RAW / SOURCE / n).read_text(encoding="utf-8"))
    countries = parse_countries(read("countries.json"))
    obs = pd.concat([parse(read(f"{v}.json"), u, v, countries) for v, (_, u) in INDICATORS.items()])
    return obs.reset_index(drop=True), countries
