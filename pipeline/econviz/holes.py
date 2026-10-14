"""Hole report: the parts of Natural Earth admin-0 units that no finest region covers, and the interior rings of the
countries' shapes, in pieces of at least `MIN_KM2`. Logged, not failing. `data/reference/holes_ok.csv` lists the real
enclaves and dependencies (columns kind, unit, lon, lat, reason; a blank lon/lat whitelists the whole unit)."""
import geopandas as gpd
import pandas as pd
import shapely

from .boundaries import area_km2
from .paths import PROCESSED, REFERENCE

MIN_KM2 = 100
NEAR = 0.05  # degrees: a whitelist point this close to a piece whitelists it


def finest(regions: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The regions that are nobody's parent (the finest level of every country, the disputed region included)."""
    return regions[~regions["region_id"].isin(regions["parent_id"].dropna())]


def _polygons(geom):
    return [p for p in shapely.get_parts(geom) if p.geom_type == "Polygon" and not p.is_empty]


def find(units: gpd.GeoSeries, regions: gpd.GeoDataFrame) -> pd.DataFrame:
    """units: unit code -> shape; regions: finest regions with `iso3`. Columns kind ('uncovered': part of a unit no region
    covers, 'ring': hole in the shape of country `unit`), unit, area_km2, lon, lat, geometry; largest first."""
    country = regions.assign(iso3=regions["iso3"].fillna("DISPUTED")).groupby("iso3").geometry.apply(shapely.union_all)  # one union per country, used for both searches
    tree, rows = shapely.STRtree(country.values), []
    for unit, g in units.items():
        for c in country.values[tree.query(g, predicate="intersects")]:
            g = shapely.difference(g, c)
        rows += [("uncovered", unit, p) for p in _polygons(g)]
    found = shapely.STRtree([p for *_, p in rows])
    for iso3, geom in country.items():
        for ring in (shapely.Polygon(r) for p in _polygons(geom) for r in p.interiors):
            for g in found.geometries[found.query(ring, predicate="intersects")]:  # what the unit search found is not repeated
                ring = shapely.difference(ring, g)
            rows += [("ring", iso3, q) for q in _polygons(ring)]
    df = gpd.GeoDataFrame(rows, columns=["kind", "unit", "geometry"], geometry="geometry", crs=4326)
    df["area_km2"] = area_km2(df).round(1)
    pts = df.geometry.representative_point()
    df = df.assign(lon=pts.x.round(3), lat=pts.y.round(3))
    return df[df["area_km2"] >= MIN_KM2].sort_values("area_km2", ascending=False, ignore_index=True)


def unlisted(pieces: pd.DataFrame, ok: pd.DataFrame) -> pd.DataFrame:
    """The pieces not covered by a `holes_ok` row (same kind and unit, and the whole unit or a point on the piece)."""
    keep = []
    for p in pieces.itertuples():
        rows = ok[(ok["kind"] == p.kind) & (ok["unit"] == p.unit)]
        near = [pd.isna(r.lon) or p.geometry.distance(shapely.Point(r.lon, r.lat)) < NEAR for r in rows.itertuples()]
        keep.append(not any(near))
    return pieces[keep]


def report(regions: gpd.GeoDataFrame, units: gpd.GeoSeries) -> pd.DataFrame:
    """Writes `holes.csv` (every piece, `ok` marks whitelisted ones) and returns the pieces still open."""
    pieces = find(units, finest(regions))
    ok = pd.read_csv(REFERENCE / "holes_ok.csv")
    open_ = unlisted(pieces, ok)
    pieces.assign(ok=~pieces.index.isin(open_.index)).drop(columns="geometry").to_csv(PROCESSED / "holes.csv", index=False)
    return open_
