Synthetic, non-sensitive QA fixtures (spec §14.3). Entirely fabricated - NOT Houston production data.

Coordinates are placed near downtown Houston in EPSG:2278 (NAD83 / Texas South Central, US survey feet)
so that basemaps line up, but every asset, ID and attribute is synthetic.

Deliberate QA conditions:
  manholes      - Point,  duplicate MH_NUMBER ('MH-021'), one null MH_NUMBER, rim elevation nulls
  gravity_mains - Line,   branched tree to an outlet, disconnected pair, directed cycle, a pipe digitized
                          against flow, an orphan reference (MH-999), a multipart pipe, null INSTALL_YR
  sewer_basins  - Polygon overlapping basins, a hole, a multipart basin, an invalid self-intersecting bowtie
  level_sensors - CSV lon/lat in EPSG:4326 (geographic -> distance tools gated), duplicated site_name
  sso_events    - zipped Shapefile WITHOUT .prj (unknown CRS -> must Define Projection)
