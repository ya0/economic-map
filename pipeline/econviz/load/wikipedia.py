"""Wikipedia fallback (secondary source) for countries without a machine-readable primary file.
Config: data/reference/wikipedia_tables.csv. Stores page title, revision id (in the raw JSON) and the primary source the page cites."""
import io
import json

import pandas as pd

from ..fetch import get
from ..obs import make
from ..paths import REFERENCE

API = "https://en.wikipedia.org/w/api.php?action=parse&format=json&prop=text%7Crevid&redirects=1&page="


def config() -> pd.DataFrame:
    return pd.read_csv(REFERENCE / "wikipedia_tables.csv", dtype={"year": int}).fillna("")


def download(page: str):
    return get("wikipedia", API + page.replace(" ", "_"), page.replace(" ", "_") + ".json")


def parse(path, name_col: str, gdp_col: str, year_col: str = "") -> tuple[pd.DataFrame, int]:
    """Returns (table[name, gdp] for the first table having both columns, revision id). Footnotes and `*` are stripped
    from names and amounts, repeated names keep their first row, a `US$ x` amount is preferred in mixed-currency cells.
    With `year_col` the table also has `year`, the leading four digits of that column."""
    doc = json.loads(path.read_text(encoding="utf-8"))["parse"]
    for t in pd.read_html(io.StringIO(doc["text"]["*"])):
        t.columns = [str(c) for c in t.columns]
        if name_col in t.columns and gdp_col in t.columns:
            t = t[[name_col, gdp_col] + [year_col] * bool(year_col)].set_axis(["name", "gdp", "year"][:2 + bool(year_col)], axis=1)
            t = t.assign(**({"year": t["year"].astype(str).str[:4].astype(int)} if year_col else {}))
            t["name"] = t["name"].astype(str).str.replace(r"\[.*?\]|\(.*?\)|\*", "", regex=True).str.strip()
            s = t["gdp"].astype(str).str.replace(r"\[.*?\]|,", "", regex=True)
            t["gdp"] = pd.to_numeric(s.str.extract(r"US\$\s*([\d.]+)")[0].fillna(s), errors="coerce")
            return t.dropna().drop_duplicates("name").reset_index(drop=True), doc["revid"]
    raise ValueError(f"table with {name_col!r} and {gdp_col!r} not found")


def split_total(t: pd.DataFrame, tol=0.1) -> tuple[pd.DataFrame, float]:
    """(regions, national total or 0): a row within tol of the sum of all the other rows is the country's total row."""
    rest = t["gdp"].sum() - t["gdp"]
    total = (len(t) >= 5) & ((t["gdp"] - rest).abs() <= tol * rest)
    return t[~total].reset_index(drop=True), float(t.loc[total, "gdp"].sum())


def layer_data(sub: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(names, observations) of the configured pages. Region ids are `WP:<ISO3>-<slug>`; GDP is in the table's unit (shares only).
    `sub`: the pages of second subdivisions instead, those with a `year_col` (each row has its own year)."""
    names, obs = [], []
    for c in config()[lambda d: (d["year_col"] != "") == sub].itertuples():
        t, _ = parse(download(c.page), c.name_col, c.gdp_col, c.year_col)
        t, total = split_total(t)
        slug = t["name"].str.lower().str.replace(r"[^a-z0-9]+", "-", regex=True).str.strip("-")
        t["region_id"] = f"WP:{c.iso3}-" + slug
        names.append(t.assign(iso3=c.iso3, level="admin1", parent_id=None)[["region_id", "iso3", "name", "level", "parent_id"]])
        rows = t.assign(variable="gdp").rename(columns={"gdp": "value"})
        rest = total - rows["value"].sum()
        if rest > 0:  # the page's total row exceeds its regions: the rest is not allocated to any region
            rows = pd.concat([rows, pd.DataFrame({"region_id": [f"WP:{c.iso3}-extra"], "variable": "gdp_extra", "value": [rest]})])
        obs.append(make(rows.assign(iso3=c.iso3, **({} if sub else {"year": c.year})), unit="table_unit", source_id=f"wikipedia:{c.page}",
                        note=f"wikipedia_secondary;{c.flags}".strip(";")))
    return pd.concat(names, ignore_index=True), pd.concat(obs, ignore_index=True)


def credits() -> list[dict]:
    """sources.json entries for the Wikipedia pages used: title, revision, cited origin."""
    out = []
    for c in config().itertuples():
        rev = json.loads(download(c.page).read_text(encoding="utf-8"))["parse"]["revid"]
        out.append({"source_id": f"wikipedia:{c.page}", "name": f"Wikipedia: {c.page} (revision {rev})", "publisher": "Wikipedia",
                    "licence": "CC BY-SA 4.0", "role": "gdp-regional (secondary)", "cited_origin": c.cited_origin,
                    "url": f"https://en.wikipedia.org/w/index.php?title={c.page.replace(' ', '_')}&oldid={rev}"})
    return out
