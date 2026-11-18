"""Vector file IO. GDAL/OGR drivers are probed at runtime via pyogrio (spec §3.2, §4.4)."""
from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely

FID = "_hpw_fid"  # internal stable feature id (surrogate); source fields are never renamed

READ_FORMATS = {
    ".gpkg": "gpkg",
    ".geojson": "geojson",
    ".json": "geojson",
    ".parquet": "geoparquet",
    ".geoparquet": "geoparquet",
    ".zip": "shapefile_zip",
    ".shp": "shapefile",
    ".csv": "csv",
    ".gdb": "filegdb",
    ".fgb": "flatgeobuf",
}

EXPORT_FORMATS = {
    "geoparquet": {"ext": ".parquet", "media": "application/vnd.apache.parquet"},
    "gpkg": {"ext": ".gpkg", "media": "application/geopackage+sqlite3"},
    "geojson": {"ext": ".geojson", "media": "application/geo+json"},
    "csv": {"ext": ".csv", "media": "text/csv"},
    "shapefile": {"ext": ".zip", "media": "application/zip"},
}


class FormatError(ValueError):
    pass


@dataclass
class CsvOptions:
    x_field: str | None = None
    y_field: str | None = None
    wkt_field: str | None = None
    crs: str | None = None
    delimiter: str = ","
    encoding: str = "utf-8"


@dataclass
class ReadResult:
    gdf: gpd.GeoDataFrame
    format: str
    warnings: list[str] = field(default_factory=list)
    encoding: str | None = None


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    paths = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    for p in paths:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def detect_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if path.is_dir() and suffix == ".gdb":
        return "filegdb"
    fmt = READ_FORMATS.get(suffix)
    if not fmt:
        raise FormatError(f"Unsupported file type '{suffix}'. Supported: {', '.join(sorted(READ_FORMATS))}")
    return fmt


def available_drivers() -> dict[str, str]:
    return {k: v for k, v in pyogrio.list_drivers().items()}


def read_vector(path: Path, csv_options: CsvOptions | None = None, layer: str | None = None) -> ReadResult:
    fmt = detect_format(path)
    warnings: list[str] = []
    if fmt == "geoparquet":
        gdf = gpd.read_parquet(path)
    elif fmt == "csv":
        return _read_csv(path, csv_options or CsvOptions())
    elif fmt == "shapefile_zip":
        with zipfile.ZipFile(path) as z:
            shps = [n for n in z.namelist() if n.lower().endswith(".shp")]
            prjs = [n for n in z.namelist() if n.lower().endswith(".prj")]
        if not shps:
            raise FormatError("Zip archive does not contain a .shp file")
        if len(shps) > 1:
            warnings.append(f"Zip contains {len(shps)} shapefiles; reading the first: {shps[0]}")
        if not prjs:
            warnings.append("Shapefile has no .prj file: coordinate reference system is UNKNOWN.")
        gdf = pyogrio.read_dataframe(f"/vsizip/{path.as_posix()}/{shps[0]}")
    else:
        drivers = available_drivers()
        needed = {"gpkg": "GPKG", "geojson": "GeoJSON", "shapefile": "ESRI Shapefile", "filegdb": "OpenFileGDB",
                  "flatgeobuf": "FlatGeobuf"}[fmt]
        if needed not in drivers:
            raise FormatError(f"GDAL driver '{needed}' is not available in this installation")
        layers = pyogrio.list_layers(path)
        if layer is None and len(layers) > 1:
            warnings.append(f"Source has {len(layers)} layers; reading '{layers[0][0]}'. Others: "
                            + ", ".join(str(l[0]) for l in layers[1:]))
        gdf = pyogrio.read_dataframe(path, layer=layer)
    if not isinstance(gdf, gpd.GeoDataFrame):
        gdf = gpd.GeoDataFrame(gdf)
    return ReadResult(gdf=gdf, format=fmt, warnings=warnings)


def _read_csv(path: Path, opts: CsvOptions) -> ReadResult:
    warnings: list[str] = []
    df = pd.read_csv(path, sep=opts.delimiter, encoding=opts.encoding)
    cols = {c.lower(): c for c in df.columns}
    x, y, wkt = opts.x_field, opts.y_field, opts.wkt_field
    if not (x and y) and not wkt:
        for cx, cy in (("longitude", "latitude"), ("lon", "lat"), ("long", "lat"), ("x", "y"), ("easting", "northing")):
            if cx in cols and cy in cols:
                x, y = cols[cx], cols[cy]
                warnings.append(f"Coordinate fields auto-detected as X='{x}', Y='{y}'. Verify before analysis.")
                break
        else:
            for cand in ("wkt", "geometry", "geom", "shape"):
                if cand in cols:
                    wkt = cols[cand]
                    warnings.append(f"WKT geometry field auto-detected as '{wkt}'.")
                    break
    for f in (x, y, wkt):
        if f and f not in df.columns:
            raise FormatError(f"Field '{f}' not found in CSV. Fields: {', '.join(map(str, df.columns))}")
    if wkt:
        geom = shapely.from_wkt(df[wkt].where(df[wkt].notna(), None).astype(object).values, on_invalid="ignore")
    elif x and y:
        xs = pd.to_numeric(df[x], errors="coerce")
        ys = pd.to_numeric(df[y], errors="coerce")
        bad = int((xs.isna() | ys.isna()).sum())
        if bad:
            warnings.append(f"{bad} rows have missing/non-numeric coordinates and have null geometry.")
        geom = [shapely.Point(a, b) if pd.notna(a) and pd.notna(b) else None for a, b in zip(xs, ys)]
    else:
        warnings.append("No geometry fields found: registered as a non-spatial table.")
        geom = [None] * len(df)
    gdf = gpd.GeoDataFrame(df, geometry=gpd.GeoSeries(geom, index=df.index), crs=opts.crs or None)
    if not opts.crs and (wkt or x):
        warnings.append("CSV import did not specify a CRS: coordinate reference system is UNKNOWN. "
                        "Use 'Define Projection' once the true CRS is confirmed.")
    return ReadResult(gdf=gdf, format="csv", warnings=warnings, encoding=opts.encoding)


def write_parquet(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(path, index=False)


def export_vector(gdf: gpd.GeoDataFrame, fmt: str, basename: str) -> tuple[bytes, list[str]]:
    """Return (file bytes, warnings) for a download. Never silently drops columns or changes units."""
    import tempfile

    if fmt not in EXPORT_FORMATS:
        raise FormatError(f"Unknown export format '{fmt}'. Use one of {', '.join(EXPORT_FORMATS)}")
    warnings: list[str] = []
    gdf = gdf.copy()
    has_geom = gdf.geometry.notna().any() if gdf.geometry.name in gdf else False
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / (basename + EXPORT_FORMATS[fmt]["ext"])
        if fmt == "geoparquet":
            gdf.to_parquet(out, index=False)
        elif fmt == "gpkg":
            gdf.to_file(out, driver="GPKG", layer=basename)
        elif fmt == "geojson":
            if gdf.crs is None:
                raise FormatError("GeoJSON (RFC 7946) requires WGS84; this layer's CRS is unknown. Define its projection first.")
            if not gdf.crs.equals("EPSG:4326"):
                warnings.append(f"GeoJSON output reprojected from {gdf.crs.to_string()} to EPSG:4326 (RFC 7946).")
                gdf = gdf.to_crs("EPSG:4326")
            gdf.to_file(out, driver="GeoJSON")
        elif fmt == "csv":
            df = pd.DataFrame(gdf.drop(columns=gdf.geometry.name))
            if has_geom:
                geoms = gdf.geometry
                df["geometry_wkt"] = shapely.to_wkt(geoms.values, rounding_precision=-1)
                if (geoms.geom_type == "Point").all():
                    df["X"] = geoms.x
                    df["Y"] = geoms.y
                warnings.append(f"CSV coordinates are in {gdf.crs.to_string() if gdf.crs else 'UNKNOWN CRS'}.")
            buf = io.StringIO()
            buf.write(f"# crs: {gdf.crs.to_string() if gdf.crs is not None else 'unknown'}\n")
            df.to_csv(buf, index=False)
            out.write_text(buf.getvalue(), encoding="utf-8")
        elif fmt == "shapefile":
            shp_dir = Path(td) / "shp"
            shp_dir.mkdir()
            long = [c for c in gdf.columns if c != gdf.geometry.name and len(str(c)) > 10]
            if long:
                warnings.append("Shapefile truncates field names to 10 characters: " + ", ".join(map(str, long)))
            types = set(gdf.geometry.dropna().geom_type)
            if len({t.replace("Multi", "") for t in types}) > 1:
                raise FormatError(f"Shapefile cannot hold mixed geometry types {sorted(types)}; use GeoPackage.")
            warnings.append("Shapefile: datetime precision, null semantics and >254-char strings may be lost.")
            gdf.to_file(shp_dir / f"{basename}.shp", driver="ESRI Shapefile")
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for p in shp_dir.iterdir():
                    z.write(p, p.name)
        return out.read_bytes(), warnings
