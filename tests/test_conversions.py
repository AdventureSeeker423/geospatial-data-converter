import io
import zipfile
from pathlib import Path

import pytest

from utils import convert, output_format_dict, read_file

input_exts = ["kml", "kmz", "geojson", "zip"]
output_exts = output_format_dict.keys()


@pytest.mark.parametrize("in_ext", input_exts)
@pytest.mark.parametrize("out_ext", output_exts)
def test_conversion(in_ext: str, out_ext: str, tmp_path: Path) -> None:
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
