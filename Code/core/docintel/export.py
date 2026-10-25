"""Exports: JSON (full result), CSV (one row per document), XLSX (Documents, Line items, Details).

Exports contain only the **selected** fields, with corrected values where a reviewer edited them, plus columns
that say whether a value was edited. A selected field the model did not find is written as "Not found" in the
value column of CSV and XLSX, and as ``null`` with ``found: false`` in JSON.
"""

from __future__ import annotations

import csv
import io
import json

from .normalize import build_view

NOT_FOUND = "Not found"
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe(value):
    """Neutralise spreadsheet formulas in text cells (CSV/XLSX injection). Numbers stay numbers."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _cell_value(cell: dict):
    if not cell["found"] and not cell["edited"]:
        return NOT_FOUND
    value = cell["value"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, (list, dict)):
        return cell["display"]
    return value if value not in (None, "") else cell["display"]


def _views(records: list[dict], threshold: float) -> list[tuple[dict, dict]]:
    return [(r, build_view(r, threshold)) for r in records if r.get("status") == "done"]


def _scalar_columns(views) -> list[tuple[str, str]]:
    """(field name, label) in first-seen order across documents (selections may differ per document)."""
    seen, cols = set(), []
    for _, view in views:
        for f in view["fields"]:
            if f["name"] not in seen:
                seen.add(f["name"])
                cols.append((f["name"], f["label"]))
    return cols


# --------------------------------------------------------------------------------------------- JSON

def to_json(record: dict, threshold: float) -> bytes:
    view = build_view(record, threshold)
    doc = {
        "id": record["id"], "file": record["filename"], "model": record["model_id"],
        "api_version": view["api_version"], "status": record["status"], "pages": record.get("pages"),
        "created_at": record.get("created_at"), "finished_at": record.get("finished_at"),
        "selected_fields": record.get("selection"), "review_threshold": threshold, "summary": view["summary"],
        "fields": {f["name"]: _json_cell(f) for f in view["fields"]},
        "tables": {t["name"]: [{c: _json_cell(row["cells"][c]) for c in row["cells"]} for row in t["rows"]]
                   for t in view["tables"]},
        "edits": record.get("edits") or {},
        "mock": record.get("mock"),
        "analysis": record.get("analysis"),  # the full Document Intelligence result, every field it found
    }
    return json.dumps(doc, indent=2, ensure_ascii=False, default=str).encode()


def _json_cell(c: dict) -> dict:
    return {"label": c["label"], "found": c["found"], "value": c["value"] if (c["found"] or c["edited"]) else None,
            "text": c["display"], "raw_text": c["content"], "currency": c.get("currency"),
            "confidence": c["confidence"], "needs_review": c["needs_review"], "edited": c["edited"],
            "model_value": c["model_value"] if c["edited"] else None, "reviewed": c["reviewed"],
            "regions": c["regions"]}


def to_json_many(records: list[dict], threshold: float) -> bytes:
    docs = [json.loads(to_json(r, threshold)) for r in records if r.get("status") == "done"]
    return json.dumps({"documents": docs}, indent=2, ensure_ascii=False, default=str).encode()


# --------------------------------------------------------------------------------------------- CSV

def to_csv(records: list[dict], threshold: float) -> bytes:
    views = _views(records, threshold)
    cols = _scalar_columns(views)
    header = ["Document", "Document ID", "Model", "Pages"]
    for _, label in cols:
        header += [label, f"{label} confidence"]
    header += ["Line items", "Fields needing review", "Edited fields"]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for record, view in views:
        by_name = {f["name"]: f for f in view["fields"]}
        row = [_safe(record["filename"]), record["id"], record["model_id"], record.get("pages")]
        for name, _ in cols:
            f = by_name.get(name)
            if f is None:
                row += ["", ""]  # not selected for this document
            else:
                row += [_safe(_cell_value(f)), "" if f["confidence"] is None else round(f["confidence"], 3)]
        items = next((t for t in view["tables"] if t["name"] == "Items"), None)
        edited = [f["label"] for f in view["fields"] if f["edited"]] + \
                 [f"{t['label']} row {r['index'] + 1} {c['label']}" for t in view["tables"] for r in t["rows"]
                  for c in r["cells"].values() if c["edited"]]
        row += [len(items["rows"]) if items else "", view["summary"]["need_review"], _safe("; ".join(edited))]
        writer.writerow(row)
    return ("﻿" + out.getvalue()).encode()  # BOM so Excel opens UTF-8 (₹, €) correctly


# --------------------------------------------------------------------------------------------- XLSX

def to_xlsx(records: list[dict], threshold: float) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    views = _views(records, threshold)
    cols = _scalar_columns(views)
    wb = Workbook(write_only=True)
    bold = Font(bold=True)

    def header(ws, names):
        from openpyxl.cell import WriteOnlyCell

        cells = []
        for n in names:
            c = WriteOnlyCell(ws, value=n)
            c.font = bold
            cells.append(c)
        ws.append(cells)

    docs = wb.create_sheet("Documents")
    header(docs, ["Document", "Document ID", "Model", "Pages", *[label for _, label in cols],
                  "Fields needing review", "Edited fields"])
    lines = wb.create_sheet("Line items")
    table_cols: list[tuple[str, str, str]] = []  # (table, column, label)
    for _, view in views:
        for t in view["tables"]:
            for c in t["columns"]:
                key = (t["name"], c["name"], f"{c['label']}" if t["name"] == "Items" else f"{t['label']}: {c['label']}")
                if key not in table_cols:
                    table_cols.append(key)
    header(lines, ["Document", "Table", "Row", *[label for _, _, label in table_cols], "Edited"])
    details = wb.create_sheet("Details")
    header(details, ["Document", "Field", "Label", "Value", "Raw text", "Confidence", "Needs review", "Edited",
                     "Model value", "Page"])

    for record, view in views:
        by_name = {f["name"]: f for f in view["fields"]}
        edited_labels = [f["label"] for f in view["fields"] if f["edited"]]
        docs.append([_safe(record["filename"]), record["id"], record["model_id"], record.get("pages"),
                     *[_safe(_cell_value(by_name[n])) if n in by_name else None for n, _ in cols],
                     view["summary"]["need_review"], _safe("; ".join(edited_labels))])
        for f in view["fields"]:
            details.append(_detail_row(record, f["path"], f))
        for t in view["tables"]:
            for r in t["rows"]:
                values = []
                for table, col, _ in table_cols:
                    cell = r["cells"].get(col) if table == t["name"] else None
                    values.append(_safe(_cell_value(cell)) if cell and (cell["found"] or cell["edited"]) else None)
                lines.append([_safe(record["filename"]), t["label"], r["index"] + 1, *values,
                              "Yes" if any(c["edited"] for c in r["cells"].values()) else "No"])
                for c in r["cells"].values():
                    if c["found"] or c["edited"]:
                        details.append(_detail_row(record, c["path"], c))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _detail_row(record: dict, path: str, c: dict) -> list:
    return [_safe(record["filename"]), path, c["label"], _safe(_cell_value(c)), _safe(c["content"] or None),
            None if c["confidence"] is None else round(c["confidence"], 3),
            "Yes" if c["needs_review"] else "No", "Yes" if c["edited"] else "No",
            _safe(c["model_value"]) if c["edited"] else None, c.get("page")]
