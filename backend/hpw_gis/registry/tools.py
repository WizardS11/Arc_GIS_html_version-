"""Universal geoprocessing tool registry (spec §5).

Tools declare geometry families, CRS requirements and typed parameters - never layer names.
Every registered layer is automatically checked against every tool.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

LINEAR_UNITS = {
    "meters": 1.0,
    "kilometers": 1000.0,
    "feet": 0.3048,
    "us_survey_feet": 1200.0 / 3937.0,
    "yards": 0.9144,
    "miles": 1609.344,
}

STATUSES = {"NOT_STARTED", "SPECIFIED", "IMPLEMENTING", "FUNCTIONAL_UNVALIDATED", "VALIDATED", "PARTIAL",
            "DEFERRED", "UNSUPPORTED"}


class ToolValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class Param:
    name: str
    label: str
    type: str  # layer | number | string | enum | boolean | field | fields | expression | crs | linear_unit
    required: bool = True
    default: Any = None
    description: str = ""
    values: list[str] | None = None  # enum choices
    value_labels: dict[str, str] | None = None
    geometry: list[str] | None = None  # for layer params: allowed families
    crs_requirement: str | None = None  # None | "known" | "projected"
    allow_table: bool = False
    parent: str | None = None  # for field params: name of the layer param
    field_types: list[str] | None = None
    min: float | None = None
    max: float | None = None
    visible_when: dict[str, list[Any]] | None = None  # UI hint: show only when other param in values
    role: str = "input"  # input | parameter


@dataclass
class ToolSpec:
    id: str
    name: str
    category: str
    toolbox: str
    summary: str
    reference_url: str
    executor: Callable[..., Any]
    params: list[Param]
    output_type: str  # layer | selection
    version: str = "0.1.0"
    status: str = "FUNCTIONAL_UNVALIDATED"
    writes_source: bool = False
    known_differences: list[str] = field(default_factory=list)
    reference_retrieved: str = "2026-11-14"

    def to_public(self) -> dict:
        d = asdict(self)
        d.pop("executor")
        return d


TOOLS: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.status not in STATUSES:
        raise ValueError(f"bad status {spec.status}")
    if spec.id in TOOLS:
        raise ValueError(f"Tool {spec.id} registered twice")
    TOOLS[spec.id] = spec
    return spec


def layer_compatibility(param: Param, layer: dict) -> tuple[bool, str]:
    fam = layer["geometry_family"]
    crs = layer.get("crs") or {}
    if fam == "Table":
        if not param.allow_table:
            return False, "Non-spatial table; this input requires geometry."
        return True, ""
    if param.geometry and fam not in param.geometry:
        if fam == "Mixed":
            return False, "Layer mixes geometry types; split it before using this tool."
        return False, f"{fam} geometry not accepted (requires {' / '.join(param.geometry)})."
    if param.crs_requirement in ("known", "projected") and crs.get("status") != "known":
        return False, "CRS is unknown. Run Define Projection with the confirmed CRS first."
    if param.crs_requirement == "projected" and not crs.get("is_projected"):
        return False, "Geographic CRS (degrees). Run Project to a projected CRS before distance-based analysis."
    return True, ""


def tool_with_compatibility(spec: ToolSpec, layers: list[dict]) -> dict:
    d = spec.to_public()
    for p in d["params"]:
        if p["type"] == "layer":
            p["compatibility"] = []
            for lyr in layers:
                ok, why = layer_compatibility(Param(**{k: v for k, v in p.items() if k != "compatibility"}), lyr)
                p["compatibility"].append({"layer_id": lyr["layer_id"], "label": lyr["label"], "compatible": ok,
                                           "reason": why})
    return d


def validate_params(spec: ToolSpec, raw: dict, get_layer: Callable[[str], dict]) -> dict:
    """Server-side pre-validation. Returns normalized params or raises ToolValidationError."""
    errors: list[str] = []
    out: dict[str, Any] = {}
    known = {p.name for p in spec.params} | {"use_selection"}
    for k in raw:
        if k not in known:
            errors.append(f"Unknown parameter '{k}'.")
    layers: dict[str, dict] = {}

    def visible(p: Param) -> bool:
        if not p.visible_when:
            return True
        return all(raw.get(k, next((q.default for q in spec.params if q.name == k), None)) in vals
                   for k, vals in p.visible_when.items())

    for p in spec.params:
        v = raw.get(p.name, p.default)
        if v in ("", None, []):
            if p.required and visible(p):
                errors.append(f"'{p.label}' is required.")
            out[p.name] = None if v in ("", None) else v
            continue
        if p.type == "layer":
            try:
                lyr = get_layer(str(v))
            except Exception:
                errors.append(f"'{p.label}': layer '{v}' is not registered.")
                continue
            ok, why = layer_compatibility(p, lyr)
            if not ok:
                errors.append(f"'{p.label}': {lyr['label']} - {why}")
            layers[p.name] = lyr
            out[p.name] = lyr["layer_id"]
        elif p.type == "number":
            try:
                fv = float(v)
            except (TypeError, ValueError):
                errors.append(f"'{p.label}' must be a number.")
                continue
            if fv != fv or fv in (float("inf"), float("-inf")):
                errors.append(f"'{p.label}' must be finite.")
            if p.min is not None and fv < p.min:
                errors.append(f"'{p.label}' must be >= {p.min}.")
            if p.max is not None and fv > p.max:
                errors.append(f"'{p.label}' must be <= {p.max}.")
            out[p.name] = fv
        elif p.type in ("enum", "linear_unit"):
            choices = p.values or (list(LINEAR_UNITS) if p.type == "linear_unit" else [])
            if v not in choices:
                errors.append(f"'{p.label}' must be one of: {', '.join(choices)}.")
            out[p.name] = v
        elif p.type == "boolean":
            out[p.name] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")
        elif p.type in ("field", "fields"):
            vals = v if isinstance(v, list) else [v]
            out[p.name] = vals if p.type == "fields" else vals[0]
        elif p.type == "crs":
            from pyproj import CRS
            try:
                c = CRS.from_user_input(v)
                auth = c.to_authority()
                out[p.name] = f"{auth[0]}:{auth[1]}" if auth else c.to_wkt()
            except Exception:
                errors.append(f"'{p.label}': '{v}' is not a recognised coordinate reference system.")
        else:
            out[p.name] = str(v)

    # field params must exist on their parent layer (and match type)
    for p in spec.params:
        if p.type in ("field", "fields") and out.get(p.name) and p.parent in layers:
            fields = {f["name"]: f for f in layers[p.parent]["profile"]["fields"]}
            for fv in (out[p.name] if isinstance(out[p.name], list) else [out[p.name]]):
                if fv not in fields:
                    errors.append(f"'{p.label}': field '{fv}' not found in {layers[p.parent]['label']}.")
                elif p.field_types and fields[fv]["type"] not in p.field_types:
                    errors.append(f"'{p.label}': field '{fv}' is {fields[fv]['type']}; requires "
                                  f"{' / '.join(p.field_types)}.")
    out["use_selection"] = bool(raw.get("use_selection", True))
    if errors:
        raise ToolValidationError(errors)
    return out
