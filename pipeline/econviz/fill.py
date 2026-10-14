"""Fill regional population that no official source gave, from Wikidata (flag `wikidata`; never overrides official values).
A region takes the value of its own ISO 3166-2 code (`region_iso.csv`), else the sum over the codes of its boundary
units. It is filled only if every code passes the sanity checks and the country's regional total stays within the
usual tolerance of the national population (only an upper bound while regions are still missing); everything else is
logged in the returned audit table."""
import pandas as pd

from . import indicators, validate
from .boundaries import area_km2
from .load import wikidata
from .obs import make
from .paths import REF_YEAR, REFERENCE

MAX_AREA_RATIO = 3.0  # Wikidata area vs geometry area
NO_OWN = pd.Series(dtype=str)


def own_codes() -> pd.Series:
    """region_id -> ISO 3166-2 code of the region itself, for regions that are groups of boundary units."""
    return pd.read_csv(REFERENCE / "region_iso.csv").set_index("region_id")["iso_3166_2"]


def wikidata_units(prefix: str) -> pd.DataFrame:
    return wikidata.parse(wikidata.download(prefix))


def unit_problem(u, ref=REF_YEAR, max_age=indicators.MAX_OFFSET) -> str:
    """Why a boundary unit's Wikidata value cannot be used ('' = usable)."""
    if pd.isna(u["pop"]):
        return "no Wikidata population"
    if not u["pop"] > 0:
        return "population not positive"
    if not 0 <= ref - u["pop_year"] <= max_age:
        return f"statement from {u['pop_year']:.0f}"
    if pd.notna(u["area_km2"]) and not 1 / MAX_AREA_RATIO <= u["area_km2"] / u["geom_km2"] <= MAX_AREA_RATIO:
        return f"area {u['area_km2']:.0f} vs geometry {u['geom_km2']:.0f} km2"
    return ""


def population_problem(pop: pd.Series, national_pop: float) -> list[str]:
    """Complete regional population must match the national total; while regions are missing it may only not exceed it."""
    if pop.notna().all():
        return validate.population(pd.DataFrame({"pop": pop}), national_pop)
    return ["population above national"] if pop.sum() > national_pop * (1 + validate.POP_TOL) else []


def audit_regions(cw: pd.DataFrame, ne, ref=REF_YEAR, max_age=indicators.MAX_OFFSET,
                  load=wikidata_units, own: pd.Series = NO_OWN) -> pd.DataFrame:
    """One row per (layer, region_id) of the crosswalk rows `cw` (layer, region_id, geo_id): Wikidata population summed over
    the region's codes, its items and oldest statement year, and `status` ('filled' = usable, else the reject reason).
    A code (the region's `own` one, or one shared by several units) counts once, against the summed geometry of its units.
    ne: Natural Earth admin-1 (region_id, iso3, iso_3166_2, geometry); load(prefix) returns wikidata.parse output."""
    units = cw.merge(ne[["region_id", "iso3", "iso_3166_2", "geometry"]].rename(columns={"region_id": "geo_id"}), on="geo_id")
    units["geom_km2"] = area_km2(units.set_geometry("geometry", crs=4326)).values
    codes = units["region_id"].map(own).fillna(units["iso_3166_2"])
    units["iso"] = codes.where(codes.str.match(r"^[A-Z]{2}-\w+$", na=False))
    units = units.groupby(["layer", "region_id", "iso3", "iso"], dropna=False, as_index=False)["geom_km2"].sum()
    wd = pd.concat([load(p) for p in sorted(units["iso"].dropna().str[:2].unique())] or [pd.DataFrame(columns=["iso", "item"])])
    u = units.merge(wd, on="iso", how="left")
    u["problem"] = [("no ISO 3166-2 code" if pd.isna(r["iso"]) else unit_problem(r, ref, max_age)) for _, r in u.iterrows()]
    audit = []
    for (layer, rid), g in u.groupby(["layer", "region_id"]):
        bad = "; ".join(sorted(set(g["problem"]) - {""}))
        audit.append({"layer": layer, "region_id": rid, "iso3": g["iso3"].iloc[0], "items": ",".join(g["item"].dropna()),
                      "pop_year": g["pop_year"].min(), "value": g["pop"].sum(), "status": bad or "filled"})
    return pd.DataFrame(audit, columns=["layer", "region_id", "iso3", "items", "pop_year", "value", "status"])


def reference_population(cw: pd.DataFrame, ne, load=wikidata_units, own: pd.Series = NO_OWN) -> pd.Series:
    """Wikidata population (any year) per region_id, to compare layers against (see validate.swapped_units)."""
    a = audit_regions(cw, ne, max_age=99, load=load, own=own)
    a = a[(a["status"] == "filled") & ~a.duplicated("region_id", keep=False)]  # an id used by two layers has two unit sets
    return a.set_index("region_id")["value"]


def fill_population(regions, obs, layer_of: dict, cw: pd.DataFrame, ne, national: pd.DataFrame, ref=REF_YEAR,
                    load=wikidata_units, own: pd.Series = NO_OWN):
    """Returns (new pop observations, audit table). layer_of: iso3 -> chosen layer; cw: crosswalk; own: see own_codes."""
    pop = obs[obs["variable"] == "pop"].dropna(subset=["value"])
    have = set(pop.loc[pop["year"].between(ref - indicators.MAX_OFFSET, ref), "region_id"])
    need = regions[(regions["level"] != "country") & ~regions["region_id"].isin(have)][["region_id", "iso3"]]
    cw = cw.merge(need, on="region_id")
    audit = audit_regions(cw[cw["layer"] == cw["iso3"].map(layer_of)][["layer", "region_id", "geo_id"]], ne, ref, load=load, own=own)
    new = make(audit[audit["status"] == "filled"].assign(variable="pop", year=lambda d: d["pop_year"]),
               unit="persons", source_id=wikidata.SOURCE, note="wikidata")
    for iso3 in new["iso3"].unique():  # keep a country's fills only if its regional total matches the national population
        o = pd.concat([obs[obs["iso3"] == iso3], new[new["iso3"] == iso3]])
        tab = indicators.split_country(o, 1.0, ref)[0]
        nat = indicators.same_year_pop(tab, national[national["iso3"] == iso3])
        problem = [] if not nat else population_problem(tab["pop"], nat[0])
        if problem:
            new = new[new["iso3"] != iso3]
            audit.loc[audit["iso3"] == iso3, "status"] = audit["status"].where(audit["status"] != "filled", "rejected: " + problem[0])
    return new, audit
