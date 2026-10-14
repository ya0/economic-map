"""Compact web exports: indicators.json (values per region) and sources.json (credits page)."""
import json

import pandas as pd

from .fetch import retrieved_on
from .paths import REFERENCE

COLUMNS = ["gdp_usd", "pop", "area_km2", "gdp_per_km2", "gdp_per_capita", "pop_density", "gdp_year", "pop_year", "area_year",
           "gdp_source", "pop_source", "area_source", "flags", "level_no", "parent_id", "name", "iso2", "pop_raw"]  # contract: append only


def _num(v):
    """6 significant digits (the app shows 3), whole numbers as integers, None for missing."""
    if isinstance(v, str):
        return v
    if pd.isna(v):
        return None
    v = float(f"{v:.6g}")
    return int(v) if v.is_integer() else v


def indicators_json(ind: pd.DataFrame, deflator: pd.DataFrame, ref_year: int, unallocated: pd.Series) -> str:
    rows = {rid: [_num(r[c]) if c != "flags" else list(r[c]) for c in COLUMNS] for rid, r in ind.iterrows()}
    meta = {"ref_year": ref_year, "price_basis": "current US$", "columns": COLUMNS,
            "deflator_us_gdp": {int(y): d for y, d in zip(deflator["year"], deflator["deflator"].round(3))},
            "unallocated_gdp_usd": {k: round(v) for k, v in unallocated.items() if v > 0}}
    return json.dumps({"meta": meta, "regions": rows}, separators=(",", ":"), allow_nan=False)


def sources_json(used: set[str], extra: list[dict] = ()) -> str:
    s = pd.read_csv(REFERENCE / "sources.csv")
    s = s[s["source_id"].isin(used) | s["role"].eq("grouping")]  # groupings shape regions without being a value source
    out = [{**r, "retrieved_on": retrieved_on(r["source_id"])} for r in
           s[["source_id", "name", "publisher", "licence", "url", "role"]].to_dict("records")]
    return json.dumps(out + [e for e in extra if e["source_id"] in used], indent=1)
