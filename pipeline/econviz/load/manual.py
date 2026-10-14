"""Population the official loaders lack, one row per region in `data/reference/population_manual.csv`
(`region_id, year, value, source_id, url, note, flags`): the figure of a statistics office (or a secondary republisher,
then `flags` says so) with the URL it was read at and a check figure in `note`. Applied after the official loaders and
before Wikidata: a row fills a region that has no population or only an older one (an aggregator's stale projection
loses to a newer census); an official value of the same year or later wins."""
import pandas as pd

from ..obs import make
from ..paths import REFERENCE

COLUMNS = ["region_id", "year", "value", "source_id", "url", "note", "flags"]


def load(sources: pd.DataFrame | None = None) -> pd.DataFrame:
    """The table; a row without URL or note, a duplicate region or an unknown source_id fails naming the region."""
    t = pd.read_csv(REFERENCE / "population_manual.csv", dtype=str, keep_default_na=False)
    known = set((pd.read_csv(REFERENCE / "sources.csv") if sources is None else sources)["source_id"])
    for c in ("url", "note", "source_id"):
        if (t[c] == "").any():
            raise ValueError(f"population_manual.csv: no {c} for {t.loc[t[c] == '', 'region_id'].tolist()}")
    unknown = t.loc[~t["source_id"].isin(known), "region_id"].tolist()
    if unknown or t["region_id"].duplicated().any():
        raise ValueError(f"population_manual.csv: unknown source_id or duplicate region {unknown or t['region_id'][t['region_id'].duplicated()].tolist()}")
    return t.astype({"year": int, "value": float})


def fill(table: pd.DataFrame, regions: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    """Population observations for the regions of `table` that are in `regions` (region_id, iso3) and have no
    population in `obs` of the same year or later."""
    latest = obs.loc[obs["variable"] == "pop"].groupby("region_id")["year"].max()
    t = table[table["region_id"].map(latest).fillna(-1) < table["year"]].merge(regions[["region_id", "iso3"]], on="region_id")
    return make(t.assign(variable="pop"), unit="persons").assign(note=t["flags"].values)
