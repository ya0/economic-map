"""Brazil, immediate geographic regions (510, IBGE): sums of their municipalities' IBGE SIDRA values (GDP at current prices,
population estimates, territorial area of the 2022 census), shapes dissolved from the generalised municipal mesh
(`qualidade=minima`); the municipality-to-region mapping is IBGE's localities service."""
import json

import geopandas as gpd
import pandas as pd

from .. import boundaries
from ..fetch import get
from ..obs import make, merge

SIDRA = "https://apisidra.ibge.gov.br/values/t/{}/n6/all/v/{}/p/{}"
TABLES = {"gdp": ("br_ibge_pib_municipios", "BRL_thousand", "5938", "37", "last%201"),  # variable -> source, unit, table, variable, period
          "pop": ("br_ibge_popest", "persons", "6579", "9324", "2024"),
          "area_km2": ("br_ibge_area", "km2", "4714", "6318", "2022")}
MESH = ("https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?intrarregiao=municipio&qualidade=minima"
        "&formato=application/vnd.geo%2Bjson")
LOCALITIES = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"


def download():
    return ({v: get(src, SIDRA.format(*query), f"{v}.json") for v, (src, _, *query) in TABLES.items()},
            get("br_ibge_malha", MESH, "municipios_minima.geojson"), get("br_ibge_localidades", LOCALITIES, "municipios.json"))


def table(path) -> pd.DataFrame:
    d = pd.DataFrame(json.loads(path.read_text(encoding="utf-8"))[1:])  # the first record holds the column titles
    return pd.DataFrame({"region_id": d["D1C"], "year": d["D3C"], "value": pd.to_numeric(d["V"], errors="coerce")})


def layer(tables: dict, mesh, localities, parents: pd.Series):
    """tables: variable -> SIDRA file; parents: state code (the first two digits of a regional code) -> level-2 region id."""
    loc = pd.DataFrame([(str(m["id"]), str(m["regiao-imediata"]["id"]), m["regiao-imediata"]["nome"])
                        for m in json.loads(localities.read_text(encoding="utf-8")) if m["regiao-imediata"]],
                       columns=["code", "region", "name"]).set_index("code")
    obs = pd.concat([make(table(tables[v]).assign(iso3="BRA", variable=v), unit=unit, source_id=src)
                     for v, (src, unit, *_) in TABLES.items()], ignore_index=True)
    g = gpd.read_file(mesh)
    g = g[g["codarea"].isin(loc.index)].assign(region=lambda d: d["codarea"].map(loc["region"]))
    r = boundaries.dissolve(g.geometry, g["region"].values)
    df = pd.DataFrame({"region_id": "IBGE:" + r.index, "name": r.index.map(loc.drop_duplicates("region").set_index("region")["name"]),
                       "parent_id": r.index.str[:2].map(parents), "geometry": r.values})
    return (boundaries.frame(df, iso3="BRA", level="immediate", boundary_source_id="br_ibge_malha",
                             boundary_vintage="IBGE malha municipal, qualidade minima"),
            merge(obs, "IBGE:" + loc["region"]))
