"""Pages (Extract, document review, History, Settings) and the htmx partials they swap in."""

import logging
from datetime import datetime, timezone

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.decorators import permission_required
from docintel import batches, catalog, results, settings_store
from docintel.catalog import CatalogError

from . import data

log = logging.getLogger(__name__)
TERMINAL = {"done", "failed"}


# --------------------------------------------------------------------------------------------- pages

@require_GET
@permission_required("extract")
def extract(request):
    rt = data.runtime()
    return render(request, "portal/extract.html", {
        "catalog": data.catalog_payload(), "samples": data.sample_list(), "limits": rt, "budget": data.budget(),
        "max_files": settings.MAX_FILES_PER_UPLOAD, "max_batch": settings.MAX_BATCH_FILES,
    })


@require_GET
@permission_required("extract")
def document(request, doc_id):
    record = data.get_record(doc_id)
    ctx = data.review_context(record, request.user)
    ctx["catalog"] = data.catalog_payload()
    ctx["standalone"] = True
    return render(request, "portal/document.html", ctx)


HISTORY_SORTS = {"newest": ("created_at", True), "oldest": ("created_at", False), "name": ("filename", False),
                 "review": ("review_count", True)}


@require_GET
@permission_required("extract")
def history(request):
    q = (request.GET.get("q") or "").strip().lower()
    model = request.GET.get("model") or ""
    status = request.GET.get("status") or ""
    review = request.GET.get("review") == "1"
    mine = request.GET.get("mine") == "1"
    sort = request.GET.get("sort") if request.GET.get("sort") in HISTORY_SORTS else "newest"
    all_rows = results.list_summaries()
    rows = [r for r in all_rows
            if (not q or q in r["filename"].lower() or q in r["id"])
            and (not model or r["model_id"] == model)
            and (not status or r["status"] == status)
            and (not review or r["review_count"] > 0)
            and (not mine or r["owner"] == request.user.id)]
    key, reverse = HISTORY_SORTS[sort]
    rows.sort(key=lambda r: r[key] if not isinstance(r[key], str) else r[key].lower(), reverse=reverse)
    for r in rows:
        r["can_delete"] = request.user.can_delete(r["owner"])
        r["mine"] = r["owner"] == request.user.id
    models = catalog.load_catalog().models
    ctx = {"rows": rows, "total": len(all_rows), "filters": {"q": request.GET.get("q", ""), "model": model,
                                                              "status": status, "review": review, "mine": mine,
                                                              "sort": sort},
           "models": [{"id": m.id, "label": m.label} for m in models.values()],
           "model_labels": {m.id: m.label for m in models.values()}, "limits": data.runtime()}
    template = "portal/partials/history_table.html" if request.headers.get("HX-Request") else "portal/history.html"
    return render(request, template, ctx)


@require_http_methods(["GET", "POST"])
@permission_required("manage_settings")
def settings_page(request):
    if request.method == "POST":
        try:
            settings_store.save_runtime_settings({
                "review_threshold": request.POST.get("review_threshold", ""),
                "daily_page_limit": request.POST.get("daily_page_limit", ""),
                "max_pages": request.POST.get("max_pages", ""),
            })
            messages.success(request, "Settings saved. They apply to new results straight away.")
            log.info("Settings changed by %s", request.user.role)
        except settings_store.SettingsError as exc:
            messages.error(request, str(exc))
        return redirect("portal:settings")
    return render(request, "portal/settings.html", {"limits": data.runtime(), "budget": data.budget(),
                                                    "catalog": data.catalog_payload()})


@require_GET
@permission_required("extract")
def batches_page(request):
    """Every bulk upload, with its progress: open one to review its documents together and export one Excel file."""
    rows = batches.list_all()
    return render(request, "portal/batches.html", {"batches": rows, "limits": data.runtime(),
                                                   "any_running": any(b["status"] != "complete" for b in rows),
                                                   "model_labels": _model_labels()})


@require_GET
@permission_required("extract")
def batch_page(request, batch_id):
    try:
        summary, docs = batches.detail(batch_id)
    except batches.BatchNotFound:
        raise Http404("No such batch") from None
    first = request.GET.get("doc") or next((d["id"] for d in docs if d["status"] == "done" and d["review_count"]), None) \
        or next((d["id"] for d in docs if d["status"] in TERMINAL), None)
    return render(request, "portal/batch.html", {"batch": summary, "docs": docs, "first": first,
                                                 "catalog": data.catalog_payload(), "model_labels": _model_labels()})


@require_GET
@permission_required("extract")
def batch_documents(request, batch_id):
    """The document list of a batch page (polls itself while the batch is running)."""
    try:
        summary, docs = batches.detail(batch_id)
    except batches.BatchNotFound:
        raise Http404("No such batch") from None
    return render(request, "portal/partials/batch_documents.html", {"batch": summary, "docs": docs,
                                                                    "current": request.GET.get("current", "")})


def _model_labels():
    return {m.id: m.label for m in catalog.load_catalog().models.values()}


# --------------------------------------------------------------------------------------------- partials

@require_GET
@permission_required("extract")
def batch_status(request):
    """Progress of one upload batch. Polls itself until every document has finished; then offers one Excel file."""
    batch_id = request.GET.get("batch") or ""
    if not results.valid_id(batch_id):
        return HttpResponseBadRequest("Invalid batch")
    rows = results.batch(batch_id)
    finished = [r for r in rows if r["status"] in TERMINAL]
    done = [r for r in rows if r["status"] == "done"]
    failed = [r for r in rows if r["status"] == "failed"]
    complete = bool(rows) and len(finished) == len(rows)
    expected = request.GET.get("expected", "")
    expected = int(expected) if expected.isdigit() else len(rows)
    complete = complete and len(rows) >= expected  # the browser may still be uploading the rest
    try:
        record = batches.get(batch_id)
    except batches.BatchNotFound:
        record = None  # a single file or a sample: no batch page
    return render(request, "portal/partials/batch.html", {
        "batch_id": batch_id, "rows": rows, "record": record, "done": done, "failed": failed, "finished": len(finished),
        "expected": max(expected, len(rows)), "complete": complete, "active": not complete,
        "pictures": sum(r["pictures"] for r in done),
        "percent": round(100 * len(finished) / max(expected, len(rows), 1)),
        "poll_ms": 1500 if len(rows) <= 10 else 3000,
    })


@require_GET
@permission_required("extract")
def review_partial(request, doc_id):
    record = data.get_record(doc_id)
    ctx = data.review_context(record, request.user)
    ctx["catalog"] = data.catalog_payload()
    return render(request, "portal/partials/review.html", ctx)


def _fields_response(request, record):
    ctx = data.review_context(record, request.user)
    ctx["oob"] = True
    return render(request, "portal/partials/fields_panel.html", ctx)


@require_POST
@permission_required("extract")
def document_selection(request, doc_id):
    """Change which fields are shown and exported. No new analysis: the full result is already stored."""
    record = data.get_record(doc_id)
    try:
        selection = catalog.load_catalog().validate_selection(record["model_id"], request.POST.getlist("fields"))
    except CatalogError as exc:
        return HttpResponseBadRequest(str(exc))
    record = results.update(doc_id, lambda r: r.__setitem__("selection", selection))
    return _fields_response(request, record)


@require_POST
@permission_required("extract")
def document_edit(request, doc_id):
    from docintel.normalize import editable_spec

    path = request.POST.get("path", "")
    value = request.POST.get("value", "")
    record = data.get_record(doc_id)
    if record["status"] != "done":
        return HttpResponseBadRequest("The document has not been analysed yet.")
    try:
        editable_spec(record["model_id"], path)
    except CatalogError as exc:
        return HttpResponseBadRequest(str(exc))
    if len(value) > 2000:
        return HttpResponseBadRequest("The value is too long (2,000 characters at most).")
    revert = request.POST.get("revert") == "1"

    def change(r):
        edits = r.setdefault("edits", {})
        if revert:
            edits.pop(path, None)
        else:
            edits[path] = {"value": value.strip(), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "by": request.user.role}
            if path not in r.setdefault("reviewed", []):
                r["reviewed"].append(path)

    record = results.update(doc_id, change)
    log.info("document %s field edited (%s)", doc_id, "reverted" if revert else "changed")
    return _fields_response(request, record)


@require_POST
@permission_required("extract")
def document_reviewed(request, doc_id):
    from docintel.normalize import all_review_paths, build_view

    record = data.get_record(doc_id)
    if record["status"] != "done":
        return HttpResponseBadRequest("The document has not been analysed yet.")
    if request.POST.get("all") == "1":
        paths = all_review_paths(build_view(record, data.threshold()))
        mark = True
    else:
        paths = [request.POST.get("path", "")]
        if not paths[0] or len(paths[0]) > 80:
            return HttpResponseBadRequest("Missing field")
        mark = request.POST.get("reviewed", "1") == "1"

    def change(r):
        current = r.setdefault("reviewed", [])
        for p in paths:
            if mark and p not in current:
                current.append(p)
            elif not mark and p in current:
                current.remove(p)

    record = results.update(doc_id, change)
    return _fields_response(request, record)


# --------------------------------------------------------------------------------------------- errors

def forbidden(request, exception=None):
    if request.path.startswith("/api/"):
        from django.http import JsonResponse

        return JsonResponse({"error": "You do not have access to this."}, status=403)
    return render(request, "portal/error.html", {"code": 403, "title": "No access",
                                                 "message": "Your role does not have access to this page."},
                  status=403)


def not_found(request, exception=None):
    if request.path.startswith("/api/"):
        from django.http import JsonResponse

        return JsonResponse({"error": "Not found."}, status=404)
    return render(request, "portal/error.html", {"code": 404, "title": "Not found",
                                                 "message": "This page or document does not exist. It may have been "
                                                            "deleted, or removed by the retention policy."},
                  status=404)


def server_error(request):
    return HttpResponse(_ERROR_500, status=500)


_ERROR_500 = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Error · Document Intelligence</title>
<style>body{font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0;color:#1f2937}
main{max-width:30rem;padding:2rem}h1{font-size:1.4rem}</style></head><body><main><h1>Something went wrong</h1>
<p>The request could not be completed. Try again, and contact support if it keeps happening.</p>
<p><a href="/">Back to Extract</a></p></main></body></html>"""
