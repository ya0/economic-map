import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, box

from econviz import holes


def regions(shapes, iso3=None, parent_id=None):
    n = len(shapes)
    return gpd.GeoDataFrame({"region_id": [f"R{i}" for i in range(n)], "iso3": iso3 or ["AAA"] * n, "parent_id": parent_id or [None] * n,
                             "geometry": shapes}, geometry="geometry", crs=4326)


def units(**shapes):
    return gpd.GeoSeries(shapes, crs=4326)


def test_interior_ring_of_a_country_shape_is_reported_once_with_its_position():
    frame = Polygon(box(0, 0, 3, 3).exterior.coords, [box(1, 1, 1.5, 1.5).exterior.coords])  # 0.5 degrees = ~3000 km2 hole
    out = holes.find(units(AAA=box(0, 0, 3, 3)), regions([frame]))
    assert out[["kind", "unit"]].values.tolist() == [["uncovered", "AAA"]]  # the unit search sees it, the ring is not repeated
    assert abs(out["lon"][0] - 1.25) < 0.01 and abs(out["lat"][0] - 1.25) < 0.01


def test_a_ring_filled_by_another_country_is_an_enclave_ring():
    ring = Polygon(box(0, 0, 3, 3).exterior.coords, [box(1, 1, 1.5, 1.5).exterior.coords])
    out = holes.find(units(AAA=box(0, 0, 3, 3), BBB=box(1, 1, 1.5, 1.5)), regions([ring, box(1, 1, 1.5, 1.5)], iso3=["AAA", "BBB"]))
    assert out[["kind", "unit"]].values.tolist() == [["ring", "AAA"]]


def test_a_unit_half_uncovered_reports_the_missing_half():
    out = holes.find(units(AAA=box(0, 0, 2, 1)), regions([box(0, 0, 1, 1)]))
    assert len(out) == 1 and out["kind"][0] == "uncovered"
    assert abs(out["area_km2"][0] - 12300) < 400  # one square degree on the equator


def test_pieces_under_the_threshold_are_ignored():
    out = holes.find(units(AAA=box(0, 0, 1, 1)), regions([Polygon(box(0, 0, 1, 1).exterior.coords, [box(0.4, 0.4, 0.45, 0.45).exterior.coords])]))
    assert out.empty  # 0.05 degrees = ~30 km2


def test_whitelisted_enclave_and_whole_unit_are_not_reported():
    pieces = pd.DataFrame({"kind": ["ring", "uncovered", "uncovered"], "unit": ["AAA", "DEP", "BBB"],
                           "geometry": [box(1, 1, 2, 2), box(5, 5, 6, 6), box(8, 8, 9, 9)]})
    ok = pd.DataFrame({"kind": ["ring", "uncovered"], "unit": ["AAA", "DEP"], "lon": [1.5, None], "lat": [1.5, None]})
    assert holes.unlisted(pieces, ok)["unit"].tolist() == ["BBB"]
    far = ok.assign(lon=[40.0, None], lat=[40.0, None])  # the point must lie on the piece
    assert holes.unlisted(pieces, far)["unit"].tolist() == ["AAA", "BBB"]


def test_finest_drops_parents_and_disputed_region_is_searched():
    r = regions([box(0, 0, 1, 1), box(0, 0, 0.5, 1), box(0.5, 0, 1, 1)], parent_id=[None, "R0", "R0"])
    assert holes.finest(r)["region_id"].tolist() == ["R1", "R2"]
    d = regions([box(0, 0, 1, 1)], iso3=[None])
    assert holes.find(units(AAA=box(0, 0, 1, 1)), d).empty


def test_report_writes_every_piece_and_returns_the_open_ones(tmp_path, monkeypatch):
    (tmp_path / "holes_ok.csv").write_text("kind,unit,lon,lat,reason\nuncovered,DEP,,,dependency\n")
    monkeypatch.setattr(holes, "REFERENCE", tmp_path)
    monkeypatch.setattr(holes, "PROCESSED", tmp_path)
    left = holes.report(regions([box(0, 0, 1, 1)]), units(AAA=box(0, 0, 2, 1), DEP=box(5, 5, 6, 6)))
    assert left["unit"].tolist() == ["AAA"]
    assert pd.read_csv(tmp_path / "holes.csv").set_index("unit")["ok"].to_dict() == {"AAA": False, "DEP": True}
