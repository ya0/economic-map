import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from econviz import boundaries
from econviz.obs import make


def square_regions(iso3="AAA", n=2, level="admin1", x0=0.0, size=1.0):
    """n side-by-side squares of `size` degrees (~12k km2 each near the equator)."""
    rows = [{"region_id": f"T:{iso3}{i}", "iso3": iso3, "name": f"{iso3} region {i}", "level": level, "parent_id": None,
             "boundary_source_id": "test_boundary", "boundary_vintage": "test",
             "geometry": box(x0 + i * size, 0, x0 + (i + 1) * size, size)} for i in range(n)]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)[boundaries.COLUMNS]


def observations(rows, source_id="test_src"):
    """rows: (region_id, iso3, variable, year, value)."""
    df = pd.DataFrame(rows, columns=["region_id", "iso3", "variable", "year", "value"])
    return make(df, unit="u", source_id=source_id)


@pytest.fixture
def country_obs():
    """Two regions with GDP for 2021 and 2022, population, area and one extra-regio GDP row."""
    r = [("T:AAA0", "AAA", "gdp", 2022, 30.0), ("T:AAA1", "AAA", "gdp", 2022, 60.0), ("T:AAA0", "AAA", "gdp_extra", 2022, 10.0),
         ("T:AAA0", "AAA", "gdp", 2021, 1.0), ("T:AAA1", "AAA", "gdp", 2021, 1.0),
         ("T:AAA0", "AAA", "pop", 2022, 100.0), ("T:AAA1", "AAA", "pop", 2022, 300.0),
         ("T:AAA0", "AAA", "area_km2", 2020, 10.0), ("T:AAA1", "AAA", "area_km2", 2020, 40.0)]
    return observations(r)
