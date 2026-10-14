"""Level model (ARCHITECTURE.md, Pipeline): level_no 0 continent, 1 country, 2 first subdivision, 3 second subdivision.
Every region has a parent chain up to a continent; a coarser region is the sum (values) and the dissolve (geometry)
of its children, never a second source."""
import geopandas as gpd
import pandas as pd

from . import boundaries, indicators

SUB = ("immediate", "prefecture", "metro")  # second subdivisions put below a level-2 region of another source (`select.refine`)
LEVEL_NO = {"country": 1, "admin1": 2, "tl2": 2, "zone": 2, "tl3": 3, "nuts3": 3, "county": 3, **dict.fromkeys(SUB, 3)}
LEVEL = {0: "continent", 1: "country", 2: "admin1"}  # `level` of an aggregated row
CRIMEA = ("UA-43", "UA-40")  # ISO 3166-2 of the Natural Earth admin-1 units Crimea and Sevastopol
SUMMARISED = ("estimate", "wikipedia_secondary", "wikidata", "pop_share")  # flags an aggregated row reports as contains_<flag>
POP_COVER = 0.95  # GDP share of an aggregated row that its regions with a population must hold for it to have one


def continent_id(name: pd.Series) -> pd.Series:
    return "CONT:" + name.str.lower().str.replace(r"[^a-z]+", "-", regex=True).str.strip("-")


def _parent(level_no: int, iso3: pd.Series, continent: pd.Series):
    """Parent ids of rows at level 2 (their country) and 1 (their continent); continents have none."""
    return {2: "ISO3:" + iso3, 1: iso3.map(continent), 0: None}[level_no]


def hierarchy(regions, tl2_of: pd.Series, continent: pd.Series):
    """The finest regions with `level_no` and `parent_id`. Level 3: NUTS3 -> OECD TL2 through the OECD correspondence
    table (`tl2_of`: OECD TL3 id -> TL2 id, NUTS3 codes are OECD codes); counties and OECD TL3 keep their source's
    parent (state FIPS, TL2). `continent`: iso3 -> continent id."""
    r = regions.assign(level_no=regions["level"].map(LEVEL_NO))
    nuts = r["level"] == "nuts3"
    r.loc[nuts, "parent_id"] = ("OECD:" + r.loc[nuts, "region_id"].str.split(":").str[1]).map(tl2_of)
    for no in (2, 1):
        r.loc[r["level_no"] == no, "parent_id"] = _parent(no, r["iso3"], continent)
    assert r["parent_id"].notna().all(), r.loc[r["parent_id"].isna(), "region_id"].tolist()
    return r


def cover(rows: pd.DataFrame, no: int) -> pd.DataFrame:
    """The rows (indexed by region_id, with level_no and parent_id) the map shows at level `no`, a complete cover of
    the world: that level, the finest rows of countries that stop above it, and the disputed region at every level."""
    finest = ~rows.index.isin(rows["parent_id"])
    return rows[(rows["level_no"] == no) | (finest & (rows["level_no"] < no)) | rows.index.str.startswith("DISPUTED:")]


def summary_flags(flags) -> list[str]:
    """Flags of an aggregated row: `aggregated` plus `contains_<flag>` for every SUMMARISED flag a region below it has."""
    seen = {f for row in flags for f in row}
    return ["aggregated"] + [f"contains_{f}" for f in SUMMARISED if f in seen]


def sum_children(kids: pd.DataFrame, people: pd.DataFrame | None = None, cover=POP_COVER) -> pd.DataFrame:
    """One indicator row per `parent_id` of `kids`, the finest regions below each parent. GDP and area are summed over
    the rows that have a value. Population is the sum over the `people` rows (default `kids`; for a continent its
    countries) that have one if those hold at least `cover` of the parent's GDP (flag `partial_population` when a row
    lacks it), else blank; per-capita and density then use the GDP and area of those rows only. Years are the oldest
    among the rows, a source is kept if all rows share it; iso3 and gdp_share only exist within one country."""
    people = kids if people is None else people
    g, p = kids.groupby("parent_id"), people.groupby("parent_id")
    one_country = g["iso3"].nunique() == 1
    out = g[["gdp_share", "gdp_usd", "area_km2"]].sum(min_count=1)
    counted = people[people["pop"].notna()].groupby("parent_id")[["gdp_usd", "area_km2", "pop"]].sum().reindex(out.index)
    counted = indicators.ratios(counted).where(counted["gdp_usd"] >= cover * out["gdp_usd"])
    for v, rows in (("gdp", g), ("pop", p), ("area", g)):
        out[f"{v}_year"] = rows[f"{v}_year"].min()
        out[f"{v}_source"] = rows[f"{v}_source"].agg(lambda s: s.iloc[0] if s.nunique(dropna=False) == 1 else None)
    out.loc[counted["pop"].isna(), ["pop_year", "pop_source"]] = None
    partial = counted["pop"].notna() & (p["pop"].count() < p.size())
    out = out.assign(iso3=g["iso3"].first().where(one_country), gdp_share=out["gdp_share"].where(one_country), year=g["year"].first(),
                     flags=[f + ["partial_population"] * p for f, p in zip(g["flags"].agg(summary_flags), partial)])
    return indicators.ratios(out.assign(pop=float("nan"))).assign(**counted[["pop", "gdp_per_capita", "pop_density"]]).rename_axis("region_id")


def official_population(sums: pd.DataFrame, own: pd.DataFrame) -> pd.DataFrame:
    """Rows with a population of their own (`own`: region id -> value, year, source_id) take it instead of the sum of
    their regions, which is only a lower bound when a region has no figure; ratios then use the whole row. These are
    the countries (national population) and the level-2 parents of second subdivisions (`select.refine`)."""
    n = own.reindex(sums.index)
    has = n["value"].notna()
    out = sums.copy()
    out.loc[has, ["pop", "pop_year", "pop_source"]] = n.loc[has, ["value", "year", "source_id"]].values
    out.loc[has, ["gdp_per_capita", "pop_density"]] = indicators.ratios(out).loc[has, ["gdp_per_capita", "pop_density"]]
    return out.assign(flags=[[x for x in f if not (h and x == "partial_population")] for f, h in zip(out["flags"], has)])


def aggregate(regions, ind: pd.DataFrame, names: pd.Series, continent: pd.Series, national_pop: pd.DataFrame):
    """Adds levels 2, 1 and 0 bottom-up to `hierarchy` output and its indicators (indexed by region_id); `names`: id ->
    name of the new rows. Population: level 2 by the POP_COVER rule, countries and refined level-2 rows from
    `national_pop` (`official_population`), continents the sum of their countries.
    Returns (regions of all levels, their indicators with level_no, parent_id and name)."""
    finest = ind.assign(parent_id=ind.index)  # parent_id walks up to each row's ancestor at the level being built
    for no in (3, 2, 1):
        kids = regions[regions["level_no"] == no]
        up = finest["parent_id"].isin(kids["region_id"])
        finest.loc[up, "parent_id"] = finest.loc[up, "parent_id"].map(kids.set_index("region_id")["parent_id"])
        if no == 1:  # continents: population from the country rows
            sums = sum_children(finest[up], ind.loc[kids["region_id"]].assign(parent_id=kids["parent_id"].values), cover=0)
        else:
            sums = official_population(sum_children(finest[up]), national_pop)
        new = kids[["parent_id", "geometry"]].dissolve("parent_id").rename_axis("region_id").reset_index()
        new["geometry"] = new["geometry"].map(boundaries.polygons)
        iso3 = new["region_id"].map(sums["iso3"])
        new = new.assign(iso3=iso3, name=new["region_id"].map(names), level=LEVEL[no - 1], level_no=no - 1,
                         parent_id=_parent(no - 1, iso3, continent))
        regions, ind = pd.concat([regions, new], ignore_index=True), pd.concat([ind, sums])
    assert regions["region_id"].is_unique and regions["name"].notna().all()
    return regions, ind.join(regions.set_index("region_id")[["level_no", "parent_id", "name"]])


def add_disputed(regions, ind: pd.DataFrame, geometry):
    """Crimea as its own region: drawn and labelled, no values, and a child of the continent only, added after
    `aggregate`, so it is in no country's or continent's sum or geometry."""
    row = {"region_id": "DISPUTED:crimea", "name": "Crimea (disputed)", "level": "disputed", "level_no": 2,
           "parent_id": "CONT:europe", "boundary_source_id": "natural_earth", "boundary_vintage": "NE 10m admin-1"}
    values = pd.DataFrame([{**row, "year": ind["year"].iloc[0], "flags": ["disputed"]}]).set_index("region_id")
    return (pd.concat([regions, gpd.GeoDataFrame([row], geometry=[geometry], crs=4326)], ignore_index=True),
            pd.concat([ind, values[["year", "flags", "level_no", "parent_id", "name"]]]))

