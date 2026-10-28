"""Turn a stored analysis (SDK wire format) into what the UI and exports show: only the selected fields.

Rules (see Documents/technical-specification.md, "Normalisation"):

* dates as ISO ``YYYY-MM-DD``, times as ``HH:MM:SS``;
* amounts as a number plus an ISO currency code (from ``currencyCode``, else from an unambiguous symbol);
* addresses as one line (the printed lines joined with commas);
* arrays of objects (line items, tax details) as tables, one column per sub-field, each cell with its own
  confidence and box; arrays of plain values joined with "; ";
* the raw text as printed (``content``), confidence (0 to 1), page number and polygon for every value;
* a selected field the model did not return is kept, with ``found = False`` ("Not found");
* a reviewer's correction replaces the value (the model value is kept next to it), and a field is flagged for
  review when its confidence is below the threshold and nobody has reviewed or corrected it.
"""

from __future__ import annotations

import re

from .catalog import Field, load_catalog

SYMBOLS = {"₹": "INR", "€": "EUR", "£": "GBP", "¥": "JPY", "₩": "KRW", "₽": "RUB", "₺": "TRY", "₫": "VND",
           "₦": "NGN", "₱": "PHP", "₪": "ILS", "฿": "THB", "Rs": "INR", "Rs.": "INR"}
CURRENCY_SOURCES = ("InvoiceTotal", "AmountDue", "SubTotal", "TotalTax")
NUMERIC_TYPES = {"number", "integer", "currency"}


# --------------------------------------------------------------------------------------------- values

def one_line(text: str | None) -> str:
    if not text:
        return ""
    joined = re.sub(r"\s*\n\s*", ", ", text.strip())
    joined = re.sub(r"\s{2,}", " ", joined)
    return re.sub(r",\s*,", ",", joined).strip(" ,")


def format_amount(amount, code: str | None) -> str:
    if amount is None:
        return ""
    text = f"{amount:,.2f}" if isinstance(amount, (int, float)) else str(amount)
    return f"{text} {code}" if code else text


def _address_from_parts(addr: dict) -> str:
    keys = ("house", "houseNumber", "road", "streetAddress", "unit", "level", "suburb", "cityDistrict", "city",
            "stateDistrict", "state", "postalCode", "countryRegion", "poBox")
    seen, parts = set(), []
    for k in keys:
        v = addr.get(k)
        if v and v not in seen:
            seen.add(v)
            parts.append(str(v))
    return ", ".join(parts)


def currency_code(vc: dict | None) -> str | None:
    if not vc:
        return None
    if vc.get("currencyCode"):
        return vc["currencyCode"]
    return SYMBOLS.get((vc.get("currencySymbol") or "").strip())


def extract_value(f: dict) -> tuple[object, str, dict]:
    """(normalised value, display text, extras) for one SDK field dictionary."""
    kind = f.get("type")
    content = f.get("content")
    extras: dict = {}
    if kind == "string":
        v = f.get("valueString", content)
        return v, v or "", extras
    if kind == "date":
        v = f.get("valueDate")
        return v, v or (content or ""), extras
    if kind == "time":
        v = f.get("valueTime")
        return v, v or (content or ""), extras
    if kind == "number":
        v = f.get("valueNumber")
        return v, "" if v is None else f"{v:g}", extras
    if kind == "integer":
        v = f.get("valueInteger")
        return v, "" if v is None else str(v), extras
    if kind == "currency":
        vc = f.get("valueCurrency") or {}
        amount, code = vc.get("amount"), currency_code(vc)
        extras["currency"] = code
        if vc.get("currencySymbol"):
            extras["currency_symbol"] = vc["currencySymbol"]
        return amount, format_amount(amount, code) or (content or ""), extras
    if kind == "address":
        addr = f.get("valueAddress") or {}
        extras["address"] = addr
        line = one_line(content) or _address_from_parts(addr)
        return line, line, extras
    if kind == "phoneNumber":
        v = f.get("valuePhoneNumber") or content
        return v, v or "", extras
    if kind == "countryRegion":
        v = f.get("valueCountryRegion") or content
        return v, v or "", extras
    if kind == "boolean":
        v = f.get("valueBoolean")
        return v, "" if v is None else ("Yes" if v else "No"), extras
    if kind == "selectionMark":
        v = f.get("valueSelectionMark")
        return v, v or "", extras
    if kind == "array":
        values = [extract_value(item)[1] for item in f.get("valueArray") or []]
        values = [v for v in values if v]
        return values, "; ".join(values), extras
    if kind == "object":
        obj = f.get("valueObject") or {}
        parts = {k: extract_value(v)[1] for k, v in obj.items()}
        extras["parts"] = parts
        return parts, one_line(content) or "; ".join(f"{k}: {v}" for k, v in parts.items() if v), extras
    return content, content or "", extras


def regions(f: dict) -> list[dict]:
    return [{"page": r.get("pageNumber", 1), "polygon": list(r.get("polygon") or [])}
            for r in f.get("boundingRegions") or [] if r.get("polygon")]


def parse_edit(value: str, kind: str):
    """Typed value of a reviewer's correction (exports write numbers as numbers)."""
    text = (value or "").strip()
    if kind in NUMERIC_TYPES:
        cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
        try:
            return float(cleaned) if cleaned not in ("", "-", ".") else None
        except ValueError:
            return text
    return text


# --------------------------------------------------------------------------------------------- views

def primary_document(analysis: dict | None) -> dict:
    docs = (analysis or {}).get("documents") or []
    return docs[0] if docs else {}


def _cell(path: str, spec: Field, f: dict | None, edits: dict, reviewed: set, threshold: float,
          parent_reviewed: bool = False) -> dict:
    found = f is not None and (f.get("content") is not None or any(k.startswith("value") for k in f))
    value, display, extras = extract_value(f) if found else (None, "", {})
    confidence = f.get("confidence") if found else None
    view = {
        "path": path, "name": spec.name, "label": spec.label, "type": spec.type, "found": bool(found),
        "value": value, "display": display, "content": (f or {}).get("content") or "",
        "confidence": confidence, "regions": regions(f) if found else [],
        "currency": extras.get("currency"), "derived": spec.derived,
        "edited": False, "model_value": display, "reviewed": parent_reviewed or path in reviewed,
    }
    edit = edits.get(path)
    if edit is not None:
        view.update(edited=True, reviewed=True, display=edit["value"], value=parse_edit(edit["value"], spec.type))
        if spec.type == "currency" and view["value"] is not None and not isinstance(view["value"], str):
            view["display"] = format_amount(view["value"], view["currency"])
    view["low_confidence"] = confidence is not None and confidence < threshold
    view["needs_review"] = bool(view["found"] and view["low_confidence"] and not view["reviewed"])
    view["page"] = view["regions"][0]["page"] if view["regions"] else None
    return view


def _derived_currency(spec: Field, fields: dict, edits: dict, reviewed: set, threshold: float) -> dict:
    if spec.name in fields:  # a future API version may return it as a field of its own
        return _cell(spec.name, spec, fields[spec.name], edits, reviewed, threshold)
    for source in CURRENCY_SOURCES:
        f = fields.get(source)
        code = currency_code((f or {}).get("valueCurrency"))
        if f and code:
            synthetic = {"type": "string", "valueString": code, "content": f.get("content"),
                         "confidence": f.get("confidence"), "boundingRegions": f.get("boundingRegions")}
            view = _cell(spec.name, spec, synthetic, edits, reviewed, threshold)
            view["derived_from"] = source
            view["model_value"] = view["model_value"] if view["edited"] else code
            return view
    return _cell(spec.name, spec, None, edits, reviewed, threshold)


def _table(spec: Field, f: dict | None, edits: dict, reviewed: set, threshold: float) -> dict:
    whole_reviewed = spec.name in reviewed
    rows = []
    for i, item in enumerate((f or {}).get("valueArray") or []):
        obj = item.get("valueObject") or {}
        cells = {col.name: _cell(f"{spec.name}[{i}].{col.name}", col, obj.get(col.name), edits, reviewed, threshold,
                                 whole_reviewed) for col in spec.items}
        rows.append({"index": i, "confidence": item.get("confidence"), "regions": regions(item), "cells": cells,
                     "needs_review": any(c["needs_review"] for c in cells.values())})
    # Show only columns the model found in at least one row (plus Description), so wide tables stay readable.
    used = [col for col in spec.items if col.name == "Description" or any(r["cells"][col.name]["found"] for r in rows)]
    low = sum(1 for r in rows for c in r["cells"].values() if c["needs_review"])
    return {"path": spec.name, "name": spec.name, "label": spec.label, "found": bool(rows),
            "columns": [{"name": c.name, "label": c.label, "type": c.type} for c in used],
            "all_columns": [{"name": c.name, "label": c.label, "type": c.type} for c in spec.items],
            "rows": rows, "low_count": low, "needs_review": low > 0, "reviewed": whole_reviewed,
            "confidence": f.get("confidence") if f else None}


def build_view(record: dict, threshold: float, selection: list[str] | None = None) -> dict:
    """The review view of a result record for the given (or stored) selection."""
    catalog = load_catalog()
    model = catalog.model(record["model_id"])
    analysis = record.get("analysis") or {}
    doc = primary_document(analysis)
    fields_raw = doc.get("fields") or {}
    edits = record.get("edits") or {}
    reviewed = set(record.get("reviewed") or [])
    names = [n for n in (selection if selection is not None else record.get("selection") or []) if n in model.fields]

    fields, tables = [], []
    for name in names:
        spec = model.field(name)
        if spec.is_table:
            tables.append(_table(spec, fields_raw.get(name), edits, reviewed, threshold))
        elif spec.derived and name == "CurrencyCode":
            fields.append(_derived_currency(spec, fields_raw, edits, reviewed, threshold))
        else:
            fields.append(_cell(name, spec, fields_raw.get(name), edits, reviewed, threshold))

    items = fields + tables
    pages = [{"number": p.get("pageNumber"), "width": p.get("width"), "height": p.get("height"),
              "unit": p.get("unit")} for p in analysis.get("pages") or []]
    extra_found = sorted(set(fields_raw) - set(names))
    return {
        "model_id": record["model_id"], "model_label": model.label,
        "api_version": analysis.get("apiVersion") or record.get("api_version"),
        "doc_type": doc.get("docType"), "documents_found": len(analysis.get("documents") or []),
        "pages": pages, "fields": fields, "tables": tables, "threshold": threshold,
        "other_fields_found": extra_found,
        "include_images": bool(record.get("include_images")),
        "image_handling": record.get("image_handling") or {},
        "figures": record.get("figures") or [],
        "figures_error": record.get("figures_error"),
        "summary": {
            "selected": len(items),
            "found": sum(1 for x in items if x["found"]),
            "not_found": sum(1 for x in items if not x["found"]),
            "need_review": sum(1 for x in items if x["needs_review"]),
            "edited": len(edits),
        },
    }


def review_count(record: dict, threshold: float) -> int:
    if not record.get("analysis"):
        return 0
    return build_view(record, threshold)["summary"]["need_review"]


def all_review_paths(view: dict) -> list[str]:
    """Every path that "Mark all reviewed" marks: each selected scalar field and each table."""
    return [f["path"] for f in view["fields"] if f["found"]] + [t["path"] for t in view["tables"] if t["found"]]


def editable_spec(model_id: str, path: str) -> Field:
    """The catalog field for an edit path (``InvoiceTotal`` or ``Items[2].Amount``). Raises CatalogError."""
    from .catalog import CatalogError

    model = load_catalog().model(model_id)
    m = re.fullmatch(r"([A-Za-z]+)(?:\[(\d{1,4})\]\.([A-Za-z]+))?", path or "")
    if not m:
        raise CatalogError(f"Invalid field path {path!r}")
    spec = model.field(m[1])
    if m[2] is None:
        if spec.is_table:
            raise CatalogError("Edit a cell of the table, not the whole table")
        return spec
    if not spec.is_table:
        raise CatalogError(f"{spec.name} is not a table")
    for col in spec.items:
        if col.name == m[3]:
            return col
    raise CatalogError(f"{m[3]} is not a column of {spec.name}")
