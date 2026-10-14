"""After build: regions.geoparquet -> web/public/regions.pmtiles with tippecanoe (`python -m econviz.tiles`; on Windows inside WSL).
Tiles carry geometry and names only, values come from indicators.json (contract: ARCHITECTURE.md, The four files)."""
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import boundaries, levels
from .paths import INTERIM, PROCESSED, RAW, WEB_PUBLIC

WIN = os.name == "nt"  # tippecanoe has no Windows build: there it runs in WSL
TIPPECANOE = os.environ.get("TIPPECANOE") or (not WIN and shutil.which("tippecanoe")) or str(RAW / "tippecanoe_build" / "tippecanoe" / "tippecanoe")
LAYERS = ("l0", "l1", "l2", "l3")  # l<k>: the regions shown at level k (`levels.cover`), all zooms
MAXZOOM, LOW_DETAIL = 9, 11  # tiles below MAXZOOM have 2^LOW_DETAIL units per side
LABEL_MINZOOM = {0: 0, 1: 0, 2: 2, 3: 5}  # level_no -> first zoom with that level's label points
WORLD = 40075016.686  # width of the Web Mercator square in metres
# Nothing may be dropped: no tiny-polygon reduction, no thinning of points, no tile size or feature limits (and see
# `stand_ins`). Shared nodes are kept so that neighbours simplify their common border identically.
FLAGS = [f"--maximum-zoom={MAXZOOM}", f"--low-detail={LOW_DETAIL}", "--no-tiny-polygon-reduction", "--no-simplification-of-shared-nodes",
         "--drop-rate=1", "--no-tile-size-limit", "--no-feature-limit", "--temporary-directory=/tmp", "--force", "--quiet"]


def largest_part(shapes: gpd.GeoSeries) -> gpd.GeoSeries:
    parts = shapes.explode()
    return parts.iloc[boundaries.area_km2(parts).reset_index(drop=True).groupby(parts.index).idxmax()]


def label_points(regions: gpd.GeoDataFrame, gdp: pd.Series) -> gpd.GeoDataFrame:
    """One point per region (rows indexed by region_id) inside the largest part of its shape; `rank` orders the
    regions of a level by GDP (1 = largest, regions without GDP last). `gdp`: region_id -> GDP."""
    rank = gdp.reindex(regions.index).groupby(regions["level_no"]).rank(ascending=False, method="first", na_option="bottom")
    return regions[["name", "level_no"]].assign(rank=rank.astype(int), geometry=largest_part(regions.geometry).representative_point()).set_geometry("geometry")


def stand_ins(regions: gpd.GeoDataFrame, points: gpd.GeoSeries):
    """Per zoom, squares two tile units wide at the label `points` of the regions whose largest part spans less than
    one tile unit there: tippecanoe drops a polygon when all its vertices round to the same tile coordinate."""
    b = largest_part(regions.geometry).to_crs(3857).bounds
    extent = (b[["maxx", "maxy"]].values - b[["minx", "miny"]].values).max(axis=1)
    for zoom in range(MAXZOOM):
        unit = WORLD / 2 ** (LOW_DETAIL + zoom)
        tiny = regions.loc[b.index[extent < unit]]
        yield zoom, tiny.assign(geometry=points[tiny.index].to_crs(3857).buffer(unit, cap_style="square").to_crs(4326))


def features(rows: gpd.GeoDataFrame, **options) -> list[str]:
    """GeoJSON lines carrying tippecanoe's per-feature `options` (layer, minzoom, maxzoom)."""
    return [json.dumps({**f, "tippecanoe": options}) for f in json.loads(rows.reset_index().to_json(drop_id=True))["features"]]


def wsl(path) -> str:
    """`path` as the shell that runs tippecanoe sees it, quoted."""
    if not WIN:
        return shlex.quote(str(path))
    return shlex.quote(subprocess.run(["wsl", "wslpath", "-a", str(path).replace("\\", "/")], capture_output=True, text=True, check=True).stdout.strip())


def run():
    regions = gpd.read_parquet(PROCESSED / "regions.geoparquet").set_index("region_id")
    labels = label_points(regions, pd.read_parquet(PROCESSED / "indicators.parquet").set_index("region_id")["gdp_usd"])
    INTERIM.mkdir(parents=True, exist_ok=True)
    WEB_PUBLIC.mkdir(parents=True, exist_ok=True)
    polygons = regions[["iso3", "name", "level_no", "parent_id", "geometry"]]
    extra = [line for no, zoom in LABEL_MINZOOM.items() for line in features(labels[labels["level_no"] == no], layer="labels", minzoom=zoom)]
    squares = list(stand_ins(polygons.drop(columns="parent_id"), labels.geometry))
    for no, name in enumerate(LAYERS):
        shown = levels.cover(polygons, no).drop(columns="parent_id")
        shown.reset_index().to_file(INTERIM / f"{name}.geojsonl", driver="GeoJSONSeq", COORDINATE_PRECISION=5)
        for zoom, tiny in squares:
            extra += features(tiny[tiny.index.isin(shown.index)], layer=name, minzoom=zoom, maxzoom=zoom)
    (INTERIM / "extra.geojsonl").write_text("\n".join(extra))
    # tippecanoe writes its command line into the published metadata: run it by bare name on relative inputs, so no local path ships
    inputs = [f"--named-layer={name}:{name}.geojsonl" for name in LAYERS] + ["extra.geojsonl"]
    out = WEB_PUBLIC / "regions.pmtiles"  # built in /tmp (under WSL 7x faster than on the Windows mount), then copied
    tool = Path(TIPPECANOE)
    cmd = " ".join(["cd", wsl(INTERIM), "&&", f"export PATH={wsl(tool.parent)}:\"$PATH\" &&", tool.name, "-o /tmp/regions.pmtiles", "-n regions -N regions",
                    *FLAGS, *inputs, "&& cp /tmp/regions.pmtiles", wsl(out)])
    shell = ["wsl", "bash", "-c"] if WIN else ["bash", "-c"]
    try:
        subprocess.run([*shell, cmd], check=True)
    finally:
        subprocess.run([*shell, "rm -f /tmp/regions.pmtiles"])
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    run()
