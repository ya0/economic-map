"""The standard long `observations` table every loader emits."""
import pandas as pd

COLUMNS = ["region_id", "iso3", "variable", "year", "value", "unit", "source_id", "note"]
VARIABLES = {"gdp", "gdp_extra", "pop", "area_km2"}  # gdp_extra: unallocated (extra-regio) GDP of a country


def make(rows: pd.DataFrame, **const) -> pd.DataFrame:
    df = rows.assign(**{"note": "", **const})
    df = df.dropna(subset=["value"])
    df["year"] = df["year"].astype(int)
    assert set(df["variable"]) <= VARIABLES, set(df["variable"]) - VARIABLES
    return df[COLUMNS].reset_index(drop=True)


def merge(obs: pd.DataFrame, group: pd.Series) -> pd.DataFrame:
    """Observations of members summed per group (`group`: member id -> group id); a member without a value adds nothing."""
    d = obs.assign(region_id=obs["region_id"].map(group)).dropna(subset=["region_id"])
    keys = [c for c in COLUMNS if c != "value"]
    return d.groupby(keys, as_index=False)["value"].sum()[COLUMNS]
