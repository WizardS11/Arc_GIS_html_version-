# Tool specifications

The machine-readable spec for each tool is its `ToolSpec` registration. It lists parameters, geometry families,
CRS requirement, reference URL and known differences, and it is served live at `GET /api/tools/{tool_id}`.
Acceptance reports are in `../VALIDATION_REPORTS/`.

| Tool | Source |
|---|---|
| Select Layer By Attribute / By Location | `backend/hpw_gis/gis_tools/selection.py` |
| Buffer | `backend/hpw_gis/gis_tools/proximity.py` |
| Clip | `backend/hpw_gis/gis_tools/overlay.py` |
| Project / Define Projection / Export Features | `backend/hpw_gis/gis_tools/data_management.py` |
| Feature To Point | `backend/hpw_gis/gis_tools/features.py` |
| Create Space Time Cube / Emerging Hot Spot Analysis | `backend/hpw_gis/gis_tools/space_time.py`, decisions in [SPACE_TIME.md](SPACE_TIME.md) |

Each doc follows spec §17: Purpose · Inputs · Method · Outputs · Validation · Changelog. Write a separate markdown
file here only when a tool has decisions that don't fit in `known_differences`, such as Spatial Join tie rules.
