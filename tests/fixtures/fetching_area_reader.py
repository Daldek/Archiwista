"""A stand-in area reader letting GDAL open the upload with no check of its own.

``AreaFiles.command`` set to this script shows what the reader's environment
alone allows: GDAL reads a GeoJSON ``link`` CRS by fetching it over HTTP.
It answers as the reader refusing the file, with the CRS GDAL found.
"""

import json
import sys
from pathlib import Path

import pyogrio

UPLOAD_NAME = "upload"


def main() -> int:
    """Open ``<directory>/upload`` as GeoJSON with GDAL and print its CRS."""
    upload = Path(sys.argv[1]) / UPLOAD_NAME
    path = upload.rename(upload.with_suffix(".geojson"))
    crs = pyogrio.read_info(path).get("crs")
    answer = {"error": "area_unreadable", "detail": f"crs: {crs}"}
    sys.stdout.write(json.dumps(answer) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
