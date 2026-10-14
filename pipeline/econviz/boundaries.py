"""Boundary loaders. Each returns a GeoDataFrame in the `regions` schema (WGS84), no GADM geometry."""
import geopandas as gpd
import pandas as pd
import pyogrio
import shapely

from .crosswalk import NAME_COLS
from .fetch import get

COLUMNS = ["region_id", "iso3", "name", "level", "parent_id", "boundary_source_id", "boundary_vintage", "geometry"]
NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
GISCO = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2024_4326_LEVL_3.geojson"
CENSUS = "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_county_500k.zip"
OCHA_CHN = ("https://data.humdata.org/dataset/17a2aaa2-dea9-4a2e-8b3f-92d1bdfb850c/resource/9e67ddf9-ce26-4b7a-82b1-51e5ca0714c8"
            "/download/chn_adm_ocha_2020_shp.zip")
ISO_FIX = {"KOS": "XKX"}  # Natural Earth -> World Bank code


def area_km2(gdf: gpd.GeoDataFrame) -> pd.Series:
    """Geodesic-quality area in an equal-area CRS (EPSG:6933)."""
    return gdf.to_crs(6933).area / 1e6


def polygons(geom):
    """The polygonal parts of a shape (`make_valid` and dissolves of touching units can leave degenerate lines behind)."""
    parts = [p for p in shapely.get_parts(shapely.get_parts(geom)) if p.geom_type == "Polygon"]  # a collection may hold multipolygons
    return parts[0] if len(parts) == 1 else shapely.MultiPolygon(parts)


def valid(geoms: gpd.GeoSeries) -> gpd.GeoSeries:
    """Repairs the invalid rings some sources ship (self-touching borders)."""
    return geoms.make_valid().map(polygons)


def dissolve(geoms: gpd.GeoSeries, by) -> gpd.GeoSeries:
    """The union of the shapes per group (`by`: one group id per shape), indexed by group id."""
    return valid(gpd.GeoDataFrame(geometry=geoms.values, crs=4326).dissolve(by=list(by)).geometry)


def snap(shapes: gpd.GeoSeries, outline) -> gpd.GeoSeries:
    """A mesh (shapes without overlaps) made to tile `outline`: cut to it, and each piece of it that no shape covers
    joins the shape it shares the longest border with (an island none touches: the nearest)."""
    cut = shapes.intersection(outline).values
    tree, add = shapely.STRtree(cut), {}
    for piece in shapely.get_parts(shapely.difference(outline, shapes.union_all())):
        near = tree.query(piece, predicate="intersects")
        i = near[shapely.length(shapely.intersection(piece.boundary, cut[near])).argmax()] if len(near) else tree.nearest(piece)
        add.setdefault(i, [cut[i]]).append(piece)
    for i, parts in add.items():
        cut[i] = shapely.union_all(parts)
    return valid(gpd.GeoSeries(cut, index=shapes.index, crs=4326))


def frame(df, **const) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(df.assign(**const), geometry="geometry", crs=4326)[COLUMNS]


CONTINENT_FIX = {"MDV": "Asia", "MUS": "Africa", "SYC": "Africa"}  # Natural Earth files these under 'Seven seas (open ocean)'


def natural_earth_units() -> gpd.GeoDataFrame:
    """Every Natural Earth admin-0 unit (disputed areas, leases and dependencies included) by `ADM0_A3` and its name."""
    g = gpd.read_file(get("natural_earth", NE + "ne_10m_admin_0_countries.geojson", "countries.geojson"))
    return gpd.GeoDataFrame({"unit": g["ADM0_A3"], "name": g["NAME"]}, geometry=valid(g.geometry), crs=4326)


def natural_earth_countries() -> gpd.GeoDataFrame:
    """Countries in the `regions` schema plus Natural Earth's `continent` and `iso2` (ISO 3166-1 alpha-2)."""
    g = gpd.read_file(get("natural_earth", NE + "ne_10m_admin_0_countries.geojson", "countries.geojson"))
    iso = g["ISO_A3_EH"].where(g["ISO_A3_EH"] != "-99", g["ADM0_A3"]).replace(ISO_FIX)
    df = pd.DataFrame({"iso3": iso, "name": g["NAME"], "continent": g["CONTINENT"], "iso2": g["ISO_A2_EH"],
                       "geometry": g.geometry}).drop_duplicates("iso3")
    df["continent"] = df["iso3"].map(CONTINENT_FIX).fillna(df["continent"])
    df["region_id"] = "ISO3:" + df["iso3"]
    return frame(df, level="country", parent_id=None, boundary_source_id="natural_earth",
                    boundary_vintage="NE 10m admin-0").join(df[["continent", "iso2"]])


def attach(countries: gpd.GeoDataFrame, units: gpd.GeoDataFrame, table: pd.DataFrame) -> gpd.GeoDataFrame:
    """Natural Earth units that are no country of their own (`data/reference/attach.csv`: unit, target, reason, adds_area)
    joined to the shape of the target country (`iso3`). A whole country's area stays the national statistics' (WDI's
    land area includes most of these pieces); a row with `adds_area` is not in it, so the column `attached_km2` of the
    target holds the pieces' computed area for `add_attached_area`."""
    shapes, geom = units.set_index("unit")["geometry"], countries.set_index("iso3")["geometry"]
    extra = pd.Series(0.0, index=geom.index)
    for r in table.itertuples():
        for key, known, what in ((r.unit, shapes.index, "unit"), (r.target, geom.index, "target")):
            if key not in known:
                raise ValueError(f"attach.csv: unknown {what} {key!r}")
        geom[r.target] = valid(gpd.GeoSeries([shapely.union(geom[r.target], shapes[r.unit])], crs=4326)).iloc[0]
        if r.adds_area:
            extra[r.target] += area_km2(gpd.GeoDataFrame(geometry=[shapes[r.unit]], crs=4326)).iloc[0]
    return countries.assign(geometry=countries["iso3"].map(geom).values, attached_km2=countries["iso3"].map(extra).values)


def add_attached_area(obs: pd.DataFrame, countries: pd.DataFrame) -> pd.DataFrame:
    """National land area (`ISO3:<iso3>` rows) plus the computed area of the pieces attached to the country that WDI's
    figure leaves out (`attach`); flag `area_computed`. Split countries take their area from their regions' shapes."""
    add = countries.set_index("region_id")["attached_km2"]
    hit = (obs["variable"] == "area_km2") & obs["region_id"].map(add).fillna(0).gt(0)
    obs = obs.copy()
    obs.loc[hit, "value"] += obs.loc[hit, "region_id"].map(add)
    obs.loc[hit, "note"] = obs.loc[hit, "note"].str.cat(pd.Series("area_computed", index=obs.index[hit]), sep=";").str.strip(";")
    return obs


def natural_earth_admin1() -> gpd.GeoDataFrame:
    """Admin-1 units keyed by NE `adm1_code`; extra columns (names, iso_3166_2) are used for crosswalk matching."""
    g = gpd.read_file(get("natural_earth", NE + "ne_10m_admin_1_states_provinces.geojson", "admin1.geojson"))
    g["iso3"] = g["adm0_a3"].replace({"KOS": "XKX"})
    return g.assign(region_id="NE1:" + g["adm1_code"], geometry=valid(g.geometry))


def ons_itl3() -> gpd.GeoDataFrame:
    """UK ITL3 (Jan 2025) boundaries, ultra-generalised (BUC), from the ONS Open Geography portal; OGL v3 (matches OECD TL3 codes)."""
    name = "ITL3_JAN_2025_UK_BUC_V2"
    url = (f"https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/{name}/FeatureServer/2/query"
           "?where=1%3D1&outFields=ITL325CD,ITL325NM&outSR=4326&f=geojson&geometryPrecision=4&resultRecordCount=500")
    g = gpd.read_file(get("ons_itl3", url, "itl3_2025_buc.geojson"))
    return gpd.GeoDataFrame({"region_id": "ITL3:" + g["ITL325CD"], "iso3": "GBR", "name": g["ITL325NM"],
                             "boundary_source_id": "ons_itl3", "boundary_vintage": "ITL3 Jan 2025 BUC"},
                            geometry=valid(g.geometry), crs=4326)


def match_pool() -> gpd.GeoDataFrame:
    """Boundary units that OECD/DOSE regions are matched to: Natural Earth admin-1, UK from ONS ITL3 instead."""
    ne = natural_earth_admin1()
    ne = ne[ne["iso3"] != "GBR"].assign(boundary_source_id="natural_earth", boundary_vintage="NE 10m admin-1")
    cols = [c for c in ne.columns if c in ("region_id", "iso3", "boundary_source_id", "boundary_vintage", "geometry", *NAME_COLS)]
    return pd.concat([ne[cols], ons_itl3()], ignore_index=True)


def ocha_china_names() -> pd.DataFrame:
    """Prefecture-level units of COD-AB as `code` (as in `ocha_china`), `zh`, `en` and `province` names."""
    g = pyogrio.read_dataframe(f"zip://{get('ocha_cod_chn', OCHA_CHN, 'chn_adm_ocha_2020_shp.zip')}!chn_admbnda_adm2_ocha_2020.shp",
                               read_geometry=False)
    g = g.sort_values("ADM2_PCODE").assign(code=lambda d: d["ADM2_PCODE"].replace({"CN037070": "CN037050"}))  # Jinan before Laiwu
    return g.drop_duplicates("code").rename(columns={"ADM2_ZH": "zh", "ADM2_EN": "en", "ADM1_EN": "province"})[["code", "zh", "en", "province"]]


def ocha_china(parents: pd.Series) -> gpd.GeoDataFrame:
    """Chinese prefecture-level units from OCHA's COD-AB (2020, CC BY-IGO; its source is unofficial). `parents`:
    province P-code -> level-2 region id."""
    g = gpd.read_file(f"zip://{get('ocha_cod_chn', OCHA_CHN, 'chn_adm_ocha_2020_shp.zip')}!chn_admbnda_adm2_ocha_2020.shp")
    g["code"] = g["ADM2_PCODE"].replace({"CN037070": "CN037050"})  # Laiwu has been part of Jinan since 2019
    g = g.sort_values("ADM2_PCODE").dissolve("code", aggfunc="first").reset_index()
    df = pd.DataFrame({"region_id": "COD:" + g["code"], "name": g["ADM2_EN"], "parent_id": g["ADM1_PCODE"].map(parents), "geometry": valid(g.geometry)})
    return frame(df, iso3="CHN", level="prefecture", boundary_source_id="ocha_cod_chn", boundary_vintage="COD-AB 2020")


def gisco_nuts3() -> gpd.GeoDataFrame:
    g = gpd.read_file(get("gisco_nuts", GISCO, "nuts3_2024_01m.geojson"))
    df = pd.DataFrame({"region_id": "NUTS2024:" + g["NUTS_ID"], "iso3": g["ISO3_CODE"], "name": g["NAME_LATN"], "geometry": valid(g.geometry)})
    return frame(df, level="nuts3", parent_id=None, boundary_source_id="gisco_nuts", boundary_vintage="NUTS 2024 1:1M")


def _census():
    g = gpd.read_file(f"zip://{get('us_census_cb', CENSUS, 'counties_2021.zip')}")
    return g[g["STATEFP"].astype(int) <= 56]


def us_state_names() -> pd.Series:
    g = _census().drop_duplicates("STATEFP")
    return pd.Series(g["STATE_NAME"].values, index="FIPS:" + g["STATEFP"])


def us_counties() -> gpd.GeoDataFrame:
    """Census cartographic county boundaries (2021 vintage: Connecticut still has its 8 old counties, as BEA/Census estimates do)."""
    g = _census()
    df = pd.DataFrame({"region_id": "FIPS:" + g["GEOID"], "iso3": "USA", "name": g["NAME"] + ", " + g["STUSPS"],
                       "parent_id": "FIPS:" + g["STATEFP"], "geometry": g.geometry, "lsad": g["LSAD"]})
    gdf = frame(df, level="county", boundary_source_id="us_census_cb", boundary_vintage="Census cb_2021 500k")
    return gdf.join(df[["lsad"]])
