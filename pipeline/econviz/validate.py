"""Build-failing checks. Each returns a list of problem strings; empty means pass."""
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.strtree import STRtree

from .boundaries import area_km2

COVER_TOL, OVERLAP_TOL, POP_TOL = 0.01, 0.005, 0.05
PER_CAPITA_RANGE = (0.02, 50)
SWAP_RATIO, SWAP_SHARE, SWAP_MIN_UNITS = 3.0, 0.25, 8  # swapped-crosswalk guard; Wikidata itself is off by 3x for ~20% of Iranian provinces


def coverage(regions: gpd.GeoDataFrame, country_geom, tol=COVER_TOL) -> list[str]:
    """Regions of a split country must cover the country polygon (relative area difference <= tol)."""
    ref = area_km2(gpd.GeoSeries([country_geom], crs=4326)).iloc[0]
    got = area_km2(regions).sum()
    diff = abs(got - ref) / ref
    return [f"cover {diff:.1%} > {tol:.1%}"] if diff > tol else []


def overlaps(regions: gpd.GeoDataFrame, tol=OVERLAP_TOL) -> list[str]:
    """Pairwise overlap area, relative to the total area, must be below tol."""
    g = regions.geometry.reset_index(drop=True)
    tree = STRtree(g.values)
    a, b = tree.query(g.values, predicate="intersects")
    pairs = [(i, j) for i, j in zip(a, b) if i < j]
    if not pairs:
        return []
    inter = gpd.GeoSeries([g[i].intersection(g[j]) for i, j in pairs], crs=4326)
    share = area_km2(inter.to_frame("geometry").set_geometry("geometry")).sum() / area_km2(regions).sum()
    return [f"overlap {share:.2%} > {tol:.2%}"] if share > tol else []


def gdp_sum(ind: pd.DataFrame, unallocated: float, national_gdp: float) -> list[str]:
    total = ind["gdp_usd"].sum() + unallocated
    return [] if np.isclose(total, national_gdp, rtol=1e-6) else [f"gdp sum {total:.4g} != national {national_gdp:.4g}"]


def population(ind: pd.DataFrame, national_pop: float, tol=POP_TOL) -> list[str]:
    if ind["pop"].isna().any() or pd.isna(national_pop):
        return []  # missing population is allowed (D1); only a present total is compared
    diff = abs(ind["pop"].sum() - national_pop) / national_pop
    return [f"population {diff:.1%} off national"] if diff > tol else []


def positive_area(ind: pd.DataFrame) -> list[str]:
    bad = ind.index[~(ind["area_km2"] > 0)]
    return [f"area <= 0 or missing: {', '.join(bad)}"] if len(bad) else []


def per_capita_outliers(ind: pd.DataFrame, national_per_capita: float, whitelist=frozenset()) -> list[str]:
    r = ind["gdp_per_capita"] / national_per_capita
    bad = ind.index[((r < PER_CAPITA_RANGE[0]) | (r > PER_CAPITA_RANGE[1])) & ~ind.index.isin(whitelist)]
    return [f"per-capita outlier: {', '.join(bad)}"] if len(bad) else []


def provenance(ind: pd.DataFrame) -> list[str]:
    miss = pd.Series(False, index=ind.index)
    for v, src, yr in (("gdp_usd", "gdp_source", "gdp_year"), ("pop", "pop_source", "pop_year"),
                       ("area_km2", "area_source", "area_year")):
        miss |= ind[v].notna() & (ind[src].isna() | ind[yr].isna())
    return [f"missing source/year: {', '.join(ind.index[miss])}"] if miss.any() else []


def swapped_units(pop: pd.Series, reference: pd.Series) -> list[str]:
    """Guard against swapped crosswalk rows: a layer's regional population (by region_id) must not differ from an
    independent reference (Wikidata) by more than SWAP_RATIO for more than SWAP_SHARE of the units compared."""
    both = pd.concat([pop, reference], axis=1, join="inner").dropna()
    both = both[(both > 0).all(axis=1)]
    if len(both) < SWAP_MIN_UNITS:
        return []
    ratio = both.iloc[:, 0] / both.iloc[:, 1]
    bad = ((ratio > SWAP_RATIO) | (ratio < 1 / SWAP_RATIO)).mean()
    return [f"{bad:.0%} of {len(both)} units differ > {SWAP_RATIO:g}x from Wikidata population"] if bad > SWAP_SHARE else []
