import io
import zipfile
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from utils import convert, output_format_dict, read_esrijson, read_file

input_exts = ["kml", "kmz", "geojson", "json", "zip", "wkt", "gpx"]
output_exts = output_format_dict.keys()

# Pairs with fundamental format-level incompatibility (not bugs in the
# converter): GPX can't represent polygons, and TopoJSON's serializer
# doesn't handle the datetime fields GPX waypoints emit.
INCOMPATIBLE = {
    ("kml", "GPX"),  # test.kml contains polygons
    ("geojson", "GPX"),  # test.geojson contains polygons
    ("zip", "GPX"),  # test.zip is a shapefile of polygons
    ("gpx", "TopoJSON"),  # GPX waypoint datetime columns break topojson
}


@pytest.mark.parametrize("in_ext", input_exts)
@pytest.mark.parametrize("out_ext", output_exts)
def test_conversion(in_ext: str, out_ext: str, tmp_path: Path) -> None:
    if (in_ext, out_ext) in INCOMPATIBLE:
        pytest.skip(f"{in_ext} -> {out_ext} is a known format-level incompatibility")
    test_file_path = Path(__file__).parent / "test_data" / f"test.{in_ext}"
    with test_file_path.open("rb") as f:
        gdf = read_file(f)

    file_ext, dl_ext, _mimetype = output_format_dict[out_ext]
    output_name = f"test.{file_ext}"

    converted_data = convert(gdf, output_name, out_ext)

    assert isinstance(converted_data, (bytes, bytearray))
    assert len(converted_data) > 0

    artifact_path = tmp_path / f"test.{dl_ext}"
    artifact_path.write_bytes(converted_data)

    if out_ext in ("ESRI Shapefile", "OpenFileGDB"):
        assert zipfile.is_zipfile(io.BytesIO(converted_data))


def test_read_esrijson_maps_common_esri_wkids() -> None:
    gdf = read_esrijson(
        {
            "spatialReference": {"wkid": 102100},
            "features": [
                {
                    "attributes": {"id": 1},
                    "geometry": {"x": 0, "y": 0},
                },
            ],
        },
    )

    assert gdf.crs is not None
    assert gdf.crs.to_epsg() == 3857


def test_read_esrijson_respects_esri_ring_orientation() -> None:
    outer_ring = [(0, 0), (0, 4), (4, 4), (4, 0), (0, 0)]
    hole_ring = [(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)]

    gdf = read_esrijson(
        {
            "spatialReference": {"wkid": 4326},
            "features": [
                {
                    "attributes": {"id": 1},
                    "geometry": {"rings": [outer_ring, hole_ring]},
                },
            ],
        },
    )

    polygon = gdf.geometry.iloc[0]
    assert isinstance(polygon, Polygon)
    assert len(polygon.interiors) == 1
    assert polygon.area == pytest.approx(12.0)
