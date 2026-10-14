"""Mexico, metropolitan areas and the rest of each state. Membership: the 92 metropolises of México 2020 (SEDATU, CONAPO,
INEGI), cut by state; every other municipio of a state forms its `Rest of <state>` (flag `remainder`). A region sums its
municipios: gross census value added of the INEGI economic census 2024 (activity of 2023, variable A131A, one file per
state), used as shares of state GDP (flag `census_va_share`: no agriculture or government, head offices count where
they are), and the 2020 census population served by INEGI's catalogue service, which also gives the Marco
Geoestadístico shapes."""
import zipfile

import geopandas as gpd
import pandas as pd
import shapely

from .. import boundaries
from ..fetch import get
from ..obs import make, merge

STATES = ("ags bc bcs camp coah col chis chih cdmx dgo gto gro hgo jal mex mich mor nay nl oax pue qro qroo slp sin son tab "
          "tamps tlax ver yuc zac").split()
CENSUS = "https://www.inegi.org.mx/contenidos/programas/ce/2024/datosabiertos/conjunto_de_datos_ce_{}_2024_csv.zip"
SHAPES = "https://gaia.inegi.org.mx/wscatgeo/v2/geo/mgem/"
METROPOLISES = ("https://www.datos.gob.mx/dataset/da65ccd9-888c-4ce8-b3b5-6bd867be344d/resource/6f57ab97-d1df-4768-beb8-c929c2449923"
                "/download/municipios_poblacion.csv")
TOLERANCE = 0.002  # degrees; the shapes come at full survey detail (107 MB)


def download():
    return ([get("mx_inegi_ce", CENSUS.format(s), f"{s}.zip") for s in STATES], get("mx_inegi_mg", SHAPES, "municipios.geojson"),
            get("mx_conapo_metropolis", METROPOLISES, "municipios_poblacion.csv"))


def parse_census(zip_path) -> pd.DataFrame:
    """Value added (million pesos) per municipio of one state: the rows without sector and size class."""
    with zipfile.ZipFile(zip_path) as z:
        d = pd.read_csv(z.open(next(n for n in z.namelist() if "/tr_ce_" in n)), dtype=str, usecols=["E03", "E04", "SECTOR", "ID_ESTRATO", "A131A"])
    d = d[d["E04"].notna() & d["SECTOR"].isna() & d["ID_ESTRATO"].isna()]
    value = pd.to_numeric(d["A131A"])  # blank where INEGI withholds it
    return pd.DataFrame({"region_id": d["E03"] + d["E04"], "value": value.where(value > 0)})  # a negative value is no share


def layer(zips, shapes, metropolises, parents: pd.Series):
    """parents: state code -> level-2 region id."""
    m = pd.read_csv(metropolises, dtype=str)
    m["state"] = m["clave_entidad"].str.zfill(2)
    m["id"] = "ZM:" + m["state"] + m["clave_metropoli"].str.replace(".", "", regex=False)
    m["name"] = m["nombre"].where(m.groupby("clave_metropoli")["state"].transform("nunique") == 1, m["nombre"] + ", " + m["entidad"] + " part")
    g = gpd.read_file(shapes)
    gid = g["cvegeo"].map(m.set_index(m["clave_compuesta_municipio"].str.zfill(5))["id"]).fillna("ZM:" + g["cve_ent"] + "-rest")
    name = gid.map(m.drop_duplicates("id").set_index("id")["name"]).fillna("Rest of " + g["cve_ent"].map(m.drop_duplicates("state").set_index("state")["entidad"]))
    geometry = gpd.GeoSeries(shapely.coverage_simplify(g.geometry.values, TOLERANCE), crs=4326)
    r = boundaries.dissolve(geometry, gid.values)
    df = pd.DataFrame({"region_id": r.index, "name": r.index.map(name.groupby(gid.values).first()), "parent_id": r.index.str[3:5].map(parents),
                       "geometry": r.values})
    row = lambda d, variable, year: d.assign(iso3="MEX", variable=variable, year=year)
    obs = pd.concat([make(row(pd.concat([parse_census(z) for z in zips]), "gdp", 2023), unit="MXN_million", source_id="mx_inegi_ce", note="census_va_share"),
                     make(row(pd.DataFrame({"region_id": g["cvegeo"], "value": pd.to_numeric(g["pob_total"])}), "pop", 2020), unit="persons", source_id="mx_inegi_censo")])
    obs = merge(obs, pd.Series(gid.values, index=g["cvegeo"]))
    obs["note"] = (obs["note"] + obs["region_id"].str.endswith("-rest").map({True: ";remainder", False: ""})).str.strip(";")
    return (boundaries.frame(df, iso3="MEX", level="metro", boundary_source_id="mx_inegi_mg", boundary_vintage="Marco Geoestadístico 2025, simplified"), obs)
