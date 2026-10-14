"""Zones (ARCHITECTURE.md, Pipeline): the admin-1 units of a whole country grouped into at most 3 regions by
population density, each a multi-part region. GDP is `pop_share`: national GDP times the zone's share of the
country's population (flag `pop_share`), the weight being the units' sourced population (`admin1pop.py`).
The weights go into the standard observation table (gdp = zone population), so `indicators.split_country` makes the
shares and the national total is kept; area and shape are sums and dissolves of the units, no new boundary source."""
import geopandas as gpd
import numpy as np
import pandas as pd

from . import admin1pop, boundaries, indicators
from .load import manual
from .paths import REF_YEAR, REFERENCE

DENSE, SPARSE = 2.0, 0.3  # density above DENSE x the country's mean = dense, below SPARSE x = sparse, else middle
ALONE, MAX_ALONE = 0.15, 2  # a unit with this share of the country's people is a region of its own (the largest MAX_ALONE only)
MIN_UNITS = 4  # a country with fewer admin-1 units stays whole
READY = 0.95  # share of the national population covered by units with a value
NEGLIGIBLE = 0.001  # a unit this small (share of the country's unit area) without a value counts as 0 people
CRUCIAL_KM2, CRUCIAL_POP = 300_000, 25e6  # area or population above which a whole country is worth splitting
MAX_ZONE = 0.70  # a country whose largest zone holds more of the land stays whole (a zone that large is the country)
BIG_OK = ("DZA",)  # owner decision 2026-10-12: Algeria is split coast against Sahara although the Sahara is 79% of the land
WHOLE = ("LBY",)  # ready but kept whole by owner decision (its NE units are an older district set than the population)
NAME = {"dense": "dense core", "middle": "middle", "sparse": "sparse interior"}
ORDER = list(NAME)


def groups(units: pd.DataFrame, overrides: dict | None = None) -> pd.Series:
    """Group per unit: 'dense', 'middle', 'sparse' or the unit's own id (a unit alone). `units`: indexed by unit id,
    columns pop and area_km2 (all units of ONE country); `overrides`: unit id -> 'dense' | 'middle' | 'sparse' | 'alone'."""
    mean = units["pop"].sum() / units["area_km2"].sum()
    d = units["pop"] / units["area_km2"]
    g = pd.Series(np.select([d > DENSE * mean, d < SPARSE * mean], ["dense", "sparse"], "middle"), index=units.index, dtype=object)
    big = units["pop"][units["pop"] >= ALONE * units["pop"].sum()]
    for u in big.nlargest(MAX_ALONE).index:
        g[u] = u
    for u, z in (overrides or {}).items():
        if u in g.index:
            g[u] = u if z == "alone" else z
    return g


def overrides() -> dict[str, dict]:
    t = pd.read_csv(REFERENCE / "zones.csv", dtype=str)
    return {iso3: dict(zip(g["unit"], g["zone"])) for iso3, g in t.groupby("iso3")}


def unit_table(units: gpd.GeoDataFrame, pop: pd.DataFrame) -> pd.DataFrame:
    """Per unit of one country: pop (NaN = no value, 0 for a negligible unit without one), area_km2, year, source, flags."""
    p = pop.set_index("region_id").reindex(units["region_id"])
    t = pd.DataFrame({"pop": p["value"].values, "area_km2": boundaries.area_km2(units).values, "year": p["year"].values,
                      "source_id": p["source_id"].values, "flags": p["flags"].values}, index=units["region_id"])
    tiny = t["pop"].isna() & (t["area_km2"] < NEGLIGIBLE * t["area_km2"].sum())
    t.loc[tiny, "pop"] = 0.0
    return t


def coverage(units: gpd.GeoDataFrame, pop: pd.DataFrame, national: pd.Series, names: pd.Series) -> pd.DataFrame:
    """One row per country of `units` (iso3, region_id, iso_3166_2, geometry): units, with a value, without a valid code,
    their population sum against the national figure, `share` (1 when every unit has a value, else sum / national),
    sources, year range, `ready` (enough units, a value everywhere, share >= READY)."""
    rows = []
    for iso3, u in units.groupby("iso3"):
        t = unit_table(u, pop[pop["region_id"].isin(u["region_id"])])
        have = t["pop"].notna()
        total, nat = t["pop"].sum(), national.get(iso3, np.nan)
        share = 1.0 if have.all() else min(1.0, total / nat) if nat > 0 else 0.0
        rows.append({"iso3": iso3, "name": names.get(iso3, iso3), "units": len(t), "with_pop": int(have.sum()),
                     "no_code": int((~u["iso_3166_2"].astype(str).str.match(r"^[A-Z]{2}-\w+$")).sum()), "pop_sum": total,
                     "national_pop": nat, "share": round(share, 3), "sources": ",".join(sorted(t["source_id"].dropna().unique())),
                     "years": "-".join(sorted({str(int(y)) for y in (t["year"].min(), t["year"].max()) if pd.notna(y)})),
                     "ready": bool(len(t) >= MIN_UNITS and have.all() and share >= READY)})
    return pd.DataFrame(rows)


def layer(units: gpd.GeoDataFrame, pop: pd.DataFrame, names: pd.Series, ready: set[str], over: dict | None = None,
          ref=REF_YEAR) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Candidate layer `pop_zones`: (regions, observations) for the `ready` countries among `units` (iso3, region_id,
    name, geometry); a country whose rule gives one group or a zone above MAX_ZONE of the land has no rows. Ids `ZONE:<ISO3>-<n>` in the order dense, middle,
    sparse, then the units alone by population; names `<country>: <dense core | middle | sparse interior | unit name>`."""
    over = overrides() if over is None else over
    regions, rows = [], []
    for iso3, u in units[units["iso3"].isin(ready)].groupby("iso3"):
        t = unit_table(u, pop)
        g = groups(t, over.get(iso3))
        if g.nunique() < 2 or (t["area_km2"].groupby(g).sum().max() > MAX_ZONE * t["area_km2"].sum() and iso3 not in BIG_OK):
            continue
        by = t.assign(group=g).groupby("group")
        order = [k for k in ORDER if k in by.groups] + sorted((k for k in by.groups if k not in ORDER), key=lambda k: -t.loc[k, "pop"])
        shapes = boundaries.dissolve(u.set_index("region_id").loc[t.index, "geometry"], g.values)
        for n, key in enumerate(order, 1):
            z, rid = by.get_group(key), f"ZONE:{iso3}-{n}"
            label = NAME.get(key) or u.set_index("region_id").loc[key, "name"]
            known = z.dropna(subset=["year"])
            top = known.groupby("source_id")["pop"].sum().idxmax()
            flags = sorted({f for x in known["flags"] for f in str(x).split(";") if f and f != "nan"})
            year = int(known["year"].min())
            regions.append({"region_id": rid, "iso3": iso3, "name": f"{names.get(iso3, iso3)}: {label}", "level": "zone",
                            "parent_id": None, "boundary_source_id": "natural_earth", "boundary_vintage": "NE 10m admin-1",
                            "geometry": shapes[key]})
            rows += [(rid, iso3, "gdp", ref, z["pop"].sum(), "weight", "wb_wdi", "pop_share"),
                     (rid, iso3, "pop", year, z["pop"].sum(), "persons", top, ";".join(flags)),
                     (rid, iso3, "area_km2", ref, z["area_km2"].sum(), "km2", "natural_earth", "area_computed")]
    cols = ["region_id", "iso3", "variable", "year", "value", "unit", "source_id", "note"]
    obs = pd.DataFrame(rows, columns=cols)
    out = gpd.GeoDataFrame(regions, columns=boundaries.COLUMNS, geometry="geometry", crs=4326)
    return out, obs


def candidates(ne: gpd.GeoDataFrame, names: pd.Series, nat: pd.DataFrame, ref=REF_YEAR):
    """(layer, coverage) for the crucial countries (national land area or population above the CRUCIAL_ limits) among
    the Natural Earth admin-1 units `ne`; `names`: iso3 -> country name; `nat`: national observations. The layer
    holds every ready country not in `WHOLE`."""
    people = indicators.national_population(nat, ref)["value"].rename(lambda i: i.removeprefix("ISO3:"))
    area = nat[nat["variable"] == "area_km2"].sort_values("year").groupby("iso3")["value"].last()
    units = ne[ne["iso3"].isin(set(area.index[area > CRUCIAL_KM2]) | set(people.index[people > CRUCIAL_POP]))]
    pop = admin1pop.population(units, manual.load(), ref)
    cov = coverage(units, pop, people, names)
    return layer(units, pop, names, set(cov.loc[cov["ready"], "iso3"]) - set(WHOLE), ref=ref), cov
