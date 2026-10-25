"""Command line: ``python -m docintel <command>``.

    analyze <file> [--model prebuilt-invoice] [--fields InvoiceId,InvoiceTotal]   analyse one file, print JSON
    seed                                                                           analyse every sample invoice
    reset                                                                          delete all local data
    models                                                                         list models and fields
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def _analyze(args) -> int:
    from . import catalog, jobs, normalize, results, settings_store
    from .pages import BudgetExceeded, UploadRejected

    path = Path(args.file)
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 2
    model = args.model
    fields = args.fields.split(",") if args.fields else catalog.default_fields(model)
    try:
        record = jobs.submit_file(path.name, path.read_bytes(), model_id=model, fields=fields, owner="cli",
                                  owner_role="Admin", start=False)
    except (UploadRejected, catalog.CatalogError, BudgetExceeded) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    status = jobs.process(record["id"])
    record = results.get(record["id"])
    if status != "done":
        print(f"Failed: {(record.get('error') or {}).get('message')}", file=sys.stderr)
        return 1
    view = normalize.build_view(record, settings_store.get_runtime_settings()["review_threshold"])
    out = {"id": record["id"], "model": record["model_id"], "api_version": view["api_version"],
           "summary": view["summary"],
           "fields": {f["name"]: {"value": f["value"] if f["found"] else "Not found", "text": f["display"],
                                  "confidence": f["confidence"], "needs_review": f["needs_review"]}
                      for f in view["fields"]},
           "tables": {t["name"]: [{k: c["display"] for k, c in r["cells"].items() if c["found"]} for r in t["rows"]]
                      for t in view["tables"]}}
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


def _seed(args) -> int:
    from . import catalog, jobs, samples

    count = 0
    for sample in samples.list_samples():
        variant = samples.preferred_variant(sample)
        path = samples.sample_path(sample, variant)
        record = jobs.submit_file(path.name, path.read_bytes(), model_id=sample["model_id"],
                                  fields=catalog.default_fields(sample["model_id"]), owner="seed", owner_role="Admin",
                                  sample=sample["id"], start=False)
        status = jobs.process(record["id"])
        print(f"{status:>6}  {path.name}")
        count += 1
    print(f"{count} sample documents analysed")
    return 0


def _reset(args) -> int:
    from .config import get_settings
    from .factory import get_blob_store

    s = get_settings()
    if s.storage_backend != "local":
        print("reset only works with local storage (it deletes .localdata)", file=sys.stderr)
        return 2
    get_blob_store().clear()
    print(f"Deleted local data in {s.local_data_dir}")
    return 0


def _models(args) -> int:
    from .catalog import load_catalog

    for m in load_catalog().models.values():
        state = "" if m.enabled else f"  (unavailable: {m.unavailable_reason})"
        print(f"{m.id}: {m.label}{state}")
        for group, fields in m.groups:
            print(f"  {group}: {', '.join(f.name for f in fields)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m docintel", description="Document Intelligence tools")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("analyze", help="analyse one file and print the selected fields as JSON")
    p.add_argument("file")
    p.add_argument("--model", default="prebuilt-invoice")
    p.add_argument("--fields", default="", help="comma-separated field names (default: the model's default preset)")
    p.set_defaults(func=_analyze)
    sub.add_parser("seed", help="analyse every bundled sample invoice (shows up in History)").set_defaults(func=_seed)
    sub.add_parser("reset", help="delete all local data (local storage only)").set_defaults(func=_reset)
    sub.add_parser("models", help="list models and their fields").set_defaults(func=_models)
    args = parser.parse_args(argv)
    return args.func(args)
