"""Population of Natural Earth admin-1 units of whole countries, the input of the zone rule (`zones.py`).
A unit takes the figure of a `population_manual.csv` row (statistics office, region_id `NE1:<adm1_code>`) if the row
is within the year window, else Wikidata's by ISO 3166-2 code (`fill.audit_regions`: same sanity checks as for
regions; a code shared by several units is unusable, so is a unit without a valid code)."""
import pandas as pd

from . import fill, indicators
from .load import manual
from .paths import REF_YEAR, REFERENCE

COLUMNS = ["region_id", "iso3", "value", "year", "source_id", "flags"]


def population(units: pd.DataFrame, table: pd.DataFrame, ref=REF_YEAR, load=fill.wikidata_units) -> pd.DataFrame:
    """One row per unit of `units` (region_id, iso3, iso_3166_2, geometry) that has a value in the window `ref - 8 .. ref`;
    `table`: `manual.load()` output. `flags` is `;`-separated (`wikidata`, `pop_secondary`)."""
    waived = set(pd.read_csv(REFERENCE / "pop_year_waivers.csv")["iso3"])
    mine = table[table["region_id"].isin(units["region_id"])].merge(units[["region_id", "iso3"]], on="region_id")
    mine = mine[mine["year"].between(ref - indicators.MAX_OFFSET, ref) | mine["iso3"].isin(waived) & (mine["year"] <= ref)]
    m = mine[COLUMNS]
    left = units[~units["region_id"].isin(m["region_id"])]
    shared = left.groupby("iso3")["iso_3166_2"].transform(lambda s: s.duplicated(keep=False))
    left = left.assign(iso_3166_2=left["iso_3166_2"].where(~shared))
    cw = pd.DataFrame({"layer": "units", "region_id": left["region_id"], "geo_id": left["region_id"]})
    a = fill.audit_regions(cw, left, ref, load=load)
    a = a[a["status"] == "filled"]
    w = pd.DataFrame({"region_id": a["region_id"], "iso3": a["iso3"], "value": a["value"], "year": a["pop_year"],
                      "source_id": "wikidata", "flags": "wikidata"})
    return pd.concat([m, w], ignore_index=True)[COLUMNS].astype({"year": int})
