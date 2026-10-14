"""Candidate layers per source: (regions GeoDataFrame, observations) for every country the source covers."""
import geopandas as gpd
import pandas as pd
import shapely

from . import boundaries, crosswalk, select
from .load import dose, dosm, eurostat, ibge, inegi, kazwiki, oecd, ruwiki, statcan, ukrstat, us, wikipedia, zhwiki_census
from .obs import make
from .paths import REFERENCE


def crosswalked(names: pd.DataFrame, obs: pd.DataFrame, pool: gpd.GeoDataFrame, cw: pd.DataFrame):
    """Regions whose geometry is the dissolved set of Natural Earth admin-1 units listed in the crosswalk.
    Area is computed from that geometry (flag area_computed)."""
    geo = pool[["region_id", "geometry", "boundary_source_id", "boundary_vintage"]].rename(columns={"region_id": "geo_id"})
    geo = geo.merge(cw, on="geo_id").dissolve(by="region_id", aggfunc="first")[
        ["geometry", "boundary_source_id", "boundary_vintage"]].reset_index()
    regions = gpd.GeoDataFrame(names.merge(geo, on="region_id"), geometry="geometry", crs=4326)
    area = pd.DataFrame({"region_id": regions["region_id"], "iso3": regions["iso3"], "variable": "area_km2",
                         "year": 2020, "value": boundaries.area_km2(regions).values,
                         "source_id": regions["boundary_source_id"].values})
    area = make(area, unit="km2", note="area_computed")
    return regions[boundaries.COLUMNS], pd.concat([obs, area], ignore_index=True)


def borrowed_population(donor_obs: pd.DataFrame, cw_new: pd.DataFrame, cw_donor: pd.DataFrame) -> pd.DataFrame:
    """Population of the donor layer's regions for regions of a newer layer that cover exactly the same boundary unit
    (the newer layer has no population of its own); the observations keep their original source."""
    one = lambda c: c[~c.duplicated("region_id", keep=False) & ~c.duplicated("geo_id", keep=False)]
    pair = one(cw_new).merge(one(cw_donor), on="geo_id", suffixes=("_new", ""))[["region_id", "region_id_new"]]
    pop = donor_obs[donor_obs["variable"] == "pop"].merge(pair, on="region_id")
    return pop.assign(region_id=pop["region_id_new"])[donor_obs.columns]


def crosswalk_sources() -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """layer -> (names[region_id, iso3, name, level, parent_id], observations) for sources keyed by non-geometry codes."""
    data, table = oecd.download()
    o, names = oecd.parse(data), oecd.parse_names(table)
    out = {}
    for level in ("tl3", "tl2"):
        ids = o[(o["level"] == level) & (o["variable"] != "gdp_extra")].drop_duplicates("region_id")[["region_id", "iso3"]]
        out[f"oecd_{level}"] = (ids.merge(names[names["level"] == level], on="region_id"),
                                o[o["level"] == level].drop(columns="level"))
    d_obs, d_names = dose.parse(dose.download())
    out["dose"] = (d_names.assign(level="admin1", parent_id=None), d_obs)
    m_obs, m_names = dosm.parse(dosm.download())
    out["dosm"] = (m_names, m_obs)
    out["wikipedia"] = wikipedia.layer_data()
    u_obs, u_names = ukrstat.parse(ukrstat.download())
    out["ukrstat"] = (u_names, u_obs)
    r_obs, r_names, _ = ruwiki.parse(ruwiki.download())
    out["ruwiki"] = (r_names, r_obs)
    k_obs, k_names, _ = kazwiki.parse(kazwiki.download())
    out["kazwiki"] = (k_names, k_obs)
    return out


def build() -> dict[str, tuple[gpd.GeoDataFrame, pd.DataFrame]]:
    """name -> (regions, obs); order is the selection priority (finest first)."""
    layers = {"us_counties": us.layer(*us.download(), boundaries.us_counties())}
    nuts = boundaries.gisco_nuts3()
    cc = dict(zip(nuts["region_id"].str[9:11], nuts["iso3"]))
    files = eurostat.download()
    obs = pd.concat([eurostat.parse(files[v], v, cc) for v in files], ignore_index=True)
    layers["nuts3"] = (nuts[nuts["region_id"].isin(obs["region_id"])], obs)
    pool, cw = boundaries.match_pool(), crosswalk.load()
    for layer, (names, o) in crosswalk_sources().items():
        layers[layer] = crosswalked(names, o, pool, cw[cw["layer"] == layer])
    for layer in select.FRESHER:  # national layers lack population: borrow DOSE's for identical units
        regions, o = layers[layer]
        borrowed = borrowed_population(layers["dose"][1], cw[cw["layer"] == layer], cw[cw["layer"] == "dose"])
        layers[layer] = (regions, pd.concat([o, borrowed], ignore_index=True))
    return layers


def sub(chosen: gpd.GeoDataFrame, outline: gpd.GeoSeries) -> dict[str, tuple[gpd.GeoDataFrame, pd.DataFrame]]:
    """name -> (regions, obs) of second subdivisions whose `parent_id` is a level-2 region of another layer
    (`data/reference/parents.csv`: source code -> parent); `select.refine` puts them below the parents they fit.
    `chosen`: the regions picked by `select.choose` (Canada's remainders are cut out of their province's shape);
    `outline`: iso3 -> Natural Earth country shape; the official meshes of a whole country are made to tile their
    country (`fit`, `boundaries.snap`)."""
    parents = pd.read_csv(REFERENCE / "parents.csv", dtype=str).set_index(["scheme", "code"])["parent_id"]
    meshes = {"br_immediate_regions": ibge.layer(*ibge.download(), parents["IBGE"]),
              "mx_metros": inegi.layer(*inegi.download(), parents["INEGI"]),
              "cn_prefectures": china_prefectures(parents["COD"])}
    out = {}
    for name, (reg, obs) in meshes.items():
        reg = reg[reg["parent_id"].notna()]  # COD-AB also has Taiwan, Hong Kong and Macau
        out[name] = (reg.assign(geometry=boundaries.snap(reg.geometry, fit(reg, outline, chosen))), obs)
    out["ca_metros"] = statcan.layer(*statcan.download(), chosen.set_index("region_id").geometry, parents["CMA"])
    return out


def fit(mesh: gpd.GeoDataFrame, outline: gpd.GeoSeries, chosen: gpd.GeoDataFrame):
    """The shape a country's mesh has to tile so that it fits every neighbour: the country's Natural Earth outline,
    except along neighbours whose chosen regions are not Natural Earth shapes (US counties, NUTS3): inside such a
    neighbour's outline the mesh keeps what it has, and those regions are cut out."""
    iso3 = mesh["iso3"].iloc[0]
    other = chosen[(chosen["boundary_source_id"] != "natural_earth") & (chosen["iso3"] != iso3)]
    other = other[other["iso3"].isin([i for i in set(other["iso3"]) if outline[i].intersects(outline[iso3])])]
    kept = shapely.intersection(mesh.geometry.union_all(), outline[other["iso3"].unique()].union_all())
    return shapely.difference(shapely.union(outline[iso3], kept), other.geometry.union_all())


def cut_overlaps(regions: gpd.GeoDataFrame, obs: pd.DataFrame, min_area=1e-8):
    """Where regions of different countries overlap (a border drawn from two sources), the overlap stays with the region
    whose boundary is not Natural Earth's (official shapes win), else with the one listed first; the other is cut. A
    cut region loses its computed area (`build.fill_area` recomputes it). `min_area` in square degrees."""
    shapes, source = regions.geometry.values.copy(), regions["boundary_source_id"].eq("natural_earth").values
    a, b = shapely.STRtree(shapes).query(shapes, predicate="intersects")
    cut = set()
    for i, j in zip(a, b):
        if i < j and regions["iso3"].iloc[i] != regions["iso3"].iloc[j]:
            win, lose = (i, j) if source[i] <= source[j] else (j, i)  # official (non-NE) shapes win
            if shapely.area(shapely.intersection(shapes[i], shapes[j])) > min_area:
                shapes[lose] = boundaries.polygons(shapely.difference(shapes[lose], shapes[win]))
                cut.add(lose)
    if not cut:
        return regions, obs
    ids = regions["region_id"].iloc[sorted(cut)]
    stale = (obs["variable"] == "area_km2") & obs["region_id"].isin(ids) & obs["note"].str.contains("area_computed")
    return regions.assign(geometry=shapes), obs[~stale]


def adopt(regions: gpd.GeoDataFrame, obs: pd.DataFrame, sub: gpd.GeoDataFrame):
    """A region with second subdivisions takes the dissolve of their shapes as its own, so a state that stays whole
    fits its refined neighbours; its computed area is dropped (`build.fill_area` recomputes it)."""
    kids = sub.dissolve("parent_id", aggfunc="first")
    r = regions.set_index("region_id", drop=False)
    ids = kids.index.intersection(r.index)
    r.loc[ids, "geometry"] = boundaries.valid(kids.geometry[ids])
    r.loc[ids, ["boundary_source_id", "boundary_vintage"]] = kids.loc[ids, ["boundary_source_id", "boundary_vintage"]]
    stale = (obs["variable"] == "area_km2") & obs["region_id"].isin(ids) & obs["note"].str.contains("area_computed")
    return r.reset_index(drop=True), obs[~stale]


def china_prefectures(parents: pd.Series):
    """COD-AB prefecture shapes with the GDP of the Wikipedia row that the crosswalk assigns to each and the 2020 census population of Chinese Wikipedia (`zhwiki_census`)."""
    cw = crosswalk.load()[lambda d: d["layer"] == "cn_prefectures"].set_index("region_id")["geo_id"]
    obs = wikipedia.layer_data(sub=True)[1]
    gdp = obs.assign(region_id=obs["region_id"].map(cw)).dropna(subset=["region_id"])
    pop = zhwiki_census.china(boundaries.ocha_china_names(), zhwiki_census.census_totals())
    return boundaries.ocha_china(parents), pd.concat([gdp, pop], ignore_index=True)
