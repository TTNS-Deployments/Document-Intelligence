"""Bundled sample invoices (Data/sample_invoices) and their sidecar JSON files.

Each sidecar holds the expected fields of one sample, with confidences and polygons in inches, plus one entry per
file variant (the PDF, and a PNG for most samples). The mock analyzer turns a sidecar into an SDK ``AnalyzeResult``
for the variant that was uploaded (PDF pages in inches, PNG pages in pixels), and the UI tests use the same
conversion to check where the highlight boxes are drawn.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

from .config import get_settings


@lru_cache(maxsize=4)
def _load(sample_dir: str) -> tuple[dict, ...]:
    base = Path(sample_dir)
    if not base.is_dir():
        return ()
    return tuple(json.loads(p.read_text()) for p in sorted(base.glob("*.json")))


def list_samples() -> list[dict]:
    d = get_settings().sample_dir
    return list(_load(str(d))) if d else []


def get_sample(sample_id: str) -> dict:
    for s in list_samples():
        if s["id"] == sample_id:
            return s
    raise KeyError(sample_id)


def sample_path(sample: dict, variant: str) -> Path:
    return get_settings().sample_dir / sample["variants"][variant]["file"]


def preferred_variant(sample: dict) -> str:
    return "pdf" if "pdf" in sample["variants"] else next(iter(sample["variants"]))


@lru_cache(maxsize=4)
def _hash_index(sample_dir: str) -> dict:
    return {v["sha256"]: (s["id"], name) for s in _load(sample_dir) for name, v in s["variants"].items()}


def find_by_content(data: bytes) -> dict | None:
    """The sample (with ``_variant`` set) whose file has exactly these bytes, or None."""
    d = get_settings().sample_dir
    if not d:
        return None
    hit = _hash_index(str(d)).get(hashlib.sha256(data).hexdigest())
    if not hit:
        return None
    sample = dict(get_sample(hit[0]))
    sample["_variant"] = hit[1]
    return sample


# --------------------------------------------------------------------------------------------- geometry

def variant_pages(sample: dict, variant: str) -> list[dict]:
    """Pages as Document Intelligence reports them for this variant: number, width, height, unit."""
    v = sample["variants"][variant]
    numbers = v.get("pages") or list(range(1, len(sample["pages"]) + 1))
    scale = v.get("scale", 1)
    out = []
    for i, n in enumerate(numbers, start=1):
        p = sample["pages"][n - 1]
        if v["unit"] == "pixel":
            out.append({"pageNumber": i, "width": round(p["width"] * scale), "height": round(p["height"] * scale),
                        "unit": "pixel", "source_page": n})
        else:
            out.append({"pageNumber": i, "width": p["width"], "height": p["height"], "unit": "inch", "source_page": n})
    return out


def variant_polygon(sample: dict, variant: str, polygon: list[float], source_page: int) -> tuple[int, list[float]] | None:
    """Map a polygon in inches on ``source_page`` to (page number, polygon) in the variant's units.

    Returns None when the variant does not contain that page (PNG variants hold only the first page).
    """
    v = sample["variants"][variant]
    numbers = v.get("pages") or list(range(1, len(sample["pages"]) + 1))
    if source_page not in numbers:
        return None
    page_number = numbers.index(source_page) + 1
    if v["unit"] != "pixel":
        return page_number, [round(c, 4) for c in polygon]
    scale = v.get("scale", 1)
    page = sample["pages"][source_page - 1]
    cx, cy = page["width"] * scale / 2, page["height"] * scale / 2
    angle = math.radians(v.get("rotate", 0.0))
    cos, sin = math.cos(angle), math.sin(angle)
    pts = []
    for x, y in zip(polygon[0::2], polygon[1::2]):
        px, py = x * scale - cx, y * scale - cy
        # Image rotation by +angle (counter-clockwise on screen, y axis pointing down).
        pts += [round(cx + px * cos + py * sin, 1), round(cy - px * sin + py * cos, 1)]
    return page_number, pts


# --------------------------------------------------------------------------------------------- SDK result

def build_result(sample: dict, data: bytes, model_id: str, api_version: str) -> dict:
    """An ``AnalyzeResult`` (wire-format dict) for the uploaded variant of a sample."""
    from azure.ai.documentintelligence.models import AnalyzedDocument, AnalyzeResult, DocumentPage

    variant = sample["_variant"]
    v = sample["variants"][variant]
    factor = v.get("confidence_factor", 1.0)
    pages = variant_pages(sample, variant)
    content_parts: list[str] = []

    def field(spec: dict):
        return _sdk_field(spec, sample, variant, factor, content_parts)

    fields = {}
    if model_id == sample["model_id"]:
        for name, spec in sample["fields"].items():
            built = field(spec)
            if built is not None:
                fields[name] = built
    doc_conf = 1.0 if fields else 0.0
    result = AnalyzeResult(
        api_version=api_version, model_id=model_id, string_index_type="textElements",
        content="\n".join(content_parts),
        pages=[DocumentPage(page_number=p["pageNumber"], width=p["width"], height=p["height"], unit=p["unit"],
                            angle=-v.get("rotate", 0.0) if p["unit"] == "pixel" else 0.0, spans=[], words=[],
                            lines=[]) for p in pages],
        documents=[AnalyzedDocument(doc_type=model_id.removeprefix("prebuilt-"), fields=fields, confidence=doc_conf,
                                    spans=[{"offset": 0, "length": len("\n".join(content_parts))}])],
    )
    return result.as_dict()


def _conf(value: float, factor: float) -> float:
    return round(max(0.01, min(1.0, value * factor)), 3)


def _sdk_field(spec: dict, sample: dict, variant: str, factor: float, content_parts: list[str]):
    from azure.ai.documentintelligence.models import (AddressValue, BoundingRegion, CurrencyValue, DocumentField,
                                                      DocumentSpan)

    regions = []
    if "polygon" in spec:
        mapped = variant_polygon(sample, variant, spec["polygon"], spec.get("page", 1))
        if mapped is None:
            return None  # this variant does not contain the page
        regions = [BoundingRegion(page_number=mapped[0], polygon=mapped[1])]

    kind = spec["type"]
    kwargs = {"type": kind}
    if "confidence" in spec:
        kwargs["confidence"] = _conf(spec["confidence"], factor)
    if spec.get("content") is not None:
        offset = sum(len(p) + 1 for p in content_parts)
        content_parts.append(spec["content"])
        kwargs["content"] = spec["content"]
        kwargs["spans"] = [DocumentSpan(offset=offset, length=len(spec["content"]))]
    if regions:
        kwargs["bounding_regions"] = regions

    value = spec.get("value")
    if kind == "array":
        rows = []
        for row in spec.get("rows", []):
            row_fields = {}
            for name, sub in row.get("fields", {}).items():
                built = _sdk_field(sub, sample, variant, factor, content_parts)
                if built is not None:
                    row_fields[name] = built
            if not row_fields:
                continue
            row_kwargs = {"type": "object", "value_object": row_fields}
            if "confidence" in row:
                row_kwargs["confidence"] = _conf(row["confidence"], factor)
            if "polygon" in row:
                mapped = variant_polygon(sample, variant, row["polygon"], row.get("page", 1))
                if mapped:
                    row_kwargs["bounding_regions"] = [BoundingRegion(page_number=mapped[0], polygon=mapped[1])]
            rows.append(DocumentField(**row_kwargs))
        if not rows:
            return None
        kwargs["value_array"] = rows
    elif kind == "string":
        kwargs["value_string"] = value
    elif kind == "date" and value:
        kwargs["value_date"] = dt.date.fromisoformat(value)
    elif kind == "number":
        kwargs["value_number"] = value
    elif kind == "currency":
        kwargs["value_currency"] = CurrencyValue(**{k: v for k, v in {
            "amount": value.get("amount"), "currency_code": value.get("currencyCode"),
            "currency_symbol": value.get("currencySymbol")}.items() if v is not None})
    elif kind == "address":
        snake = {"streetAddress": "street_address", "houseNumber": "house_number", "postalCode": "postal_code",
                 "countryRegion": "country_region", "cityDistrict": "city_district", "stateDistrict": "state_district",
                 "poBox": "po_box"}
        kwargs["value_address"] = AddressValue(**{snake.get(k, k): v for k, v in value.items()})
    return DocumentField(**kwargs)
