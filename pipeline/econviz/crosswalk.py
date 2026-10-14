"""Crosswalk between data keys (OECD/DOSE codes) and boundary units (Natural Earth admin-1; ONS ITL3 for the UK), as a reviewed CSV.

`propose()` fills in exact/fuzzy name matches for review (python -m econviz.crosswalk); the build only reads the CSV.
Columns: layer, region_id, geo_id, method. One region may list several geo_ids (dissolved); a geo_id belongs to one region per layer."""
import difflib
import re
import unicodedata

import pandas as pd

from .paths import REFERENCE

PATH = REFERENCE / "crosswalk.csv"
NAME_COLS = ["name", "name_en", "name_alt", "name_local", "gn_name", "woe_name"]
STRIP = re.compile(r"\b(province|state|region|governorate|prefecture|oblast|krai|republic of|county|district|department|territory|city of|municipality)\b")


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", STRIP.sub("", s))


def pool_index(ne: pd.DataFrame) -> pd.DataFrame:
    """(iso3, key) -> geo_id for every alias of every admin-1 unit."""
    rows = []
    for _, r in ne.iterrows():
        for c in (c for c in NAME_COLS if c in ne.columns):
            for alias in str(r[c] or "").split("|"):
                if alias and alias != "None" and alias != "nan":
                    rows.append((r["iso3"], norm(alias), r["region_id"]))
    return pd.DataFrame(rows, columns=["iso3", "key", "geo_id"]).drop_duplicates()


def by_code(names: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    """UK: OECD codes (UKC11) equal ONS ITL3 codes (TLC11) apart from the two-letter prefix (ITL3 Jan 2025)."""
    itl = pool[pool["region_id"].str.startswith("ITL3:")].assign(key=lambda d: d["region_id"].str[7:])
    n = names[names["iso3"] == "GBR"].assign(key=lambda d: d["region_id"].str[7:])
    return n.merge(itl, on="key")[["region_id_x", "region_id_y"]].set_axis(["region_id", "geo_id"], axis=1).assign(method="code")


def propose(names: pd.DataFrame, ne: pd.DataFrame, layer: str, cutoff=0.88) -> pd.DataFrame:
    """names: region_id, iso3, name. Unique exact alias match first, then difflib on aliases. Unmatched regions are omitted."""
    idx = pool_index(ne)
    out = [tuple(r) for r in by_code(names, ne)[["region_id", "geo_id", "method"]].itertuples(index=False)]
    names = names[~names["region_id"].isin([o[0] for o in out])]
    for iso3, grp in names.groupby("iso3"):
        cand = idx[idx["iso3"] == iso3]
        by_key = cand.groupby("key")["geo_id"].agg(lambda s: sorted(set(s)))
        for _, r in grp.iterrows():
            k = norm(r["name"])
            hit, method = by_key.get(k), "exact"
            if hit is None:
                close = difflib.get_close_matches(k, list(by_key.index), n=1, cutoff=cutoff)
                hit, method = (by_key[close[0]], "fuzzy") if close else (None, None)
            if hit is not None and len(hit) == 1:
                out.append((r["region_id"], hit[0], method))
    df = pd.DataFrame(out, columns=["region_id", "geo_id", "method"]).assign(layer=layer)
    return df[~df.duplicated("geo_id", keep=False)][["layer", "region_id", "geo_id", "method"]]  # a NE unit claimed twice is ambiguous: leave for manual review


def load() -> pd.DataFrame:
    return pd.read_csv(PATH, dtype=str)


def main():
    """Add proposals for regions not yet in the CSV; existing rows (manual edits) are never overwritten."""
    from . import boundaries, layers
    ne = boundaries.match_pool()
    old = load() if PATH.exists() else pd.DataFrame(columns=["layer", "region_id", "geo_id", "method"])
    new = [propose(names, ne, layer) for layer, (names, _) in layers.crosswalk_sources().items()]
    new = pd.concat(new)
    new = new[~new.set_index(["layer", "region_id"]).index.isin(old.set_index(["layer", "region_id"]).index)
              & ~new.set_index(["layer", "geo_id"]).index.isin(old.set_index(["layer", "geo_id"]).index)]
    pd.concat([old, new]).sort_values(["layer", "region_id", "geo_id"]).to_csv(PATH, index=False)
    print(f"{len(old)} kept, {len(new)} added -> {PATH}")


if __name__ == "__main__":
    main()
