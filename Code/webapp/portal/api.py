"""JSON API and downloads used by the pages (session sign-in, CSRF on every POST)."""

import logging
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import permission_required
from docintel import catalog, export, jobs, results, samples
from docintel.catalog import CatalogError
from docintel.pages import BudgetExceeded, UploadRejected, sanitize_filename

from . import data

log = logging.getLogger(__name__)
EXPORTS = {
    "json": ("application/json", "json"),
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
}


def _error(message, status=400, **extra):
    return JsonResponse({"error": message, **extra}, status=status)


def _fields_from(request, model_id):
    fields = request.POST.getlist("fields")
    if len(fields) == 1 and "," in fields[0]:
        fields = fields[0].split(",")
    return fields or catalog.default_fields(model_id)


# --------------------------------------------------------------------------------------------- upload

@require_POST
@permission_required("extract")
def upload(request):
    model_id = request.POST.get("model") or catalog.load_catalog().default_model
    files = request.FILES.getlist("files")
    if not files:
        return _error("Choose at least one PDF, JPEG or PNG file.")
    if len(files) > settings.MAX_FILES_PER_UPLOAD:
        return _error(f"Upload at most {settings.MAX_FILES_PER_UPLOAD} files at a time.")
    try:
        model = catalog.load_catalog().enabled_model(model_id)
        fields = catalog.load_catalog().validate_selection(model.id, _fields_from(request, model.id))
    except CatalogError as exc:
        return _error(str(exc))

    batch_id = results.new_id()
    accepted, rejected = [], []
    max_bytes = data.runtime()["max_upload_mb"] * 1024 * 1024
    for f in files:
        name = f.name or "document"
        if f.size > max_bytes:  # refuse before reading the file into memory
            rejected.append({"filename": sanitize_filename(name), "code": "size",
                             "message": f"{sanitize_filename(name)}: the file is {f.size / 1048576:.1f} MB; "
                                        f"the limit is {data.runtime()['max_upload_mb']} MB."})
            continue
        try:
            record = jobs.submit_file(name, f.read(), model_id=model.id, fields=fields, owner=request.user.id,
                                      owner_role=request.user.role, batch_id=batch_id)
            accepted.append({"id": record["id"], "filename": record["filename"], "status": record["status"],
                             "pages": record["pages"]})
        except UploadRejected as exc:
            rejected.append({"filename": name[:120], "code": exc.code, "message": exc.message})
        except BudgetExceeded as exc:
            rejected.append({"filename": name[:120], "code": "budget", "message": str(exc)})
    log.info("upload batch %s: %d accepted, %d rejected", batch_id, len(accepted), len(rejected))
    body = {"batch_id": batch_id, "accepted": accepted, "rejected": rejected}
    return JsonResponse(body, status=200 if accepted else 400)


@require_POST
@permission_required("extract")
def run_sample(request, sample_id):
    try:
        sample = samples.get_sample(sample_id)
    except KeyError:
        return _error("No such sample.", 404)
    variant = request.POST.get("variant") or samples.preferred_variant(sample)
    if variant not in sample["variants"]:
        return _error("No such file for this sample.")
    path = samples.sample_path(sample, variant)
    try:
        fields = catalog.load_catalog().validate_selection(sample["model_id"], _fields_from(request, sample["model_id"]))
        record = jobs.submit_file(path.name, path.read_bytes(), model_id=sample["model_id"], fields=fields,
                                  owner=request.user.id, owner_role=request.user.role, sample=sample["id"])
    except CatalogError as exc:
        return _error(str(exc))
    except BudgetExceeded as exc:
        return _error(str(exc), 429)
    return JsonResponse({"batch_id": record["batch_id"], "rejected": [],
                         "accepted": [{"id": record["id"], "filename": record["filename"], "status": record["status"],
                                       "pages": record["pages"]}]})


# --------------------------------------------------------------------------------------------- documents

@require_GET
@permission_required("extract")
def document_json(request, doc_id):
    record = data.get_record(doc_id)
    body = {k: record.get(k) for k in ("id", "filename", "status", "error", "model_id", "api_version", "pages",
                                       "created_at", "finished_at", "duration_ms", "selection", "mock")}
    if record["status"] == "done":
        from docintel.normalize import build_view

        body["view"] = build_view(record, data.threshold())
    return JsonResponse(body, json_dumps_params={"ensure_ascii": False})


@require_GET
@permission_required("extract")
def document_file(request, doc_id):
    record = data.get_record(doc_id)
    try:
        chunks = results.iter_original(record)
        first = next(chunks, b"")
    except FileNotFoundError:
        return _error("The original file is no longer stored.", 404)

    def stream():
        yield first
        yield from chunks

    response = StreamingHttpResponse(stream(), content_type=record["content_type"])
    response["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(record['filename'])}"
    response["Content-Length"] = str(record.get("size") or "")
    return response


@require_POST
@permission_required("extract")
def retry(request, doc_id):
    record = data.get_record(doc_id)
    if record["status"] != "failed":
        return _error("Only failed documents can be retried.", 409)
    try:
        record = jobs.retry(doc_id)
    except BudgetExceeded as exc:
        return _error(str(exc), 429)
    except ValueError as exc:
        return _error(str(exc), 409)
    return JsonResponse({"id": doc_id, "status": record["status"]})


@require_POST
@permission_required("extract")
def delete(request, doc_id):
    record = data.get_record(doc_id)
    if not request.user.can_delete(record.get("owner", "")):
        return _error("Only the person who uploaded this document, or an Admin, can delete it.", 403)
    if record["status"] == "processing":
        return _error("The document is being analysed. Delete it when it has finished.", 409)
    results.delete(doc_id)
    log.info("document %s deleted by %s", doc_id, request.user.role)
    if request.headers.get("HX-Request"):
        return HttpResponse("")
    return JsonResponse({"deleted": doc_id})


def _download(content: bytes, fmt: str, stem: str):
    content_type, ext = EXPORTS[fmt]
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(stem)}.{ext}"
    return response


@require_GET
@permission_required("extract")
def export_one(request, doc_id, fmt):
    record = data.get_record(doc_id)
    if record["status"] != "done":
        return _error("The document has not been analysed yet.", 409)
    t = data.threshold()
    content = {"json": lambda: export.to_json(record, t), "csv": lambda: export.to_csv([record], t),
               "xlsx": lambda: export.to_xlsx([record], t)}[fmt]()
    stem = record["filename"].rsplit(".", 1)[0] + "-fields"
    return _download(content, fmt, stem)


@require_GET
@permission_required("extract")
def export_many(request, fmt):
    ids = [i for i in (request.GET.get("ids") or "").split(",") if results.valid_id(i)]
    if not ids:
        return _error("Choose at least one document.")
    if len(ids) > 200:
        return _error("Export at most 200 documents at a time.")
    records = []
    for doc_id in ids:
        try:
            r = results.get(doc_id)
        except results.NotFound:
            continue
        if r["status"] == "done":
            records.append(r)
    if not records:
        return _error("None of the chosen documents has finished.", 409)
    t = data.threshold()
    content = {"json": lambda: export.to_json_many(records, t), "csv": lambda: export.to_csv(records, t),
               "xlsx": lambda: export.to_xlsx(records, t)}[fmt]()
    return _download(content, fmt, f"documents-{len(records)}")


# --------------------------------------------------------------------------------------------- catalog and presets

@require_GET
@permission_required("extract")
def catalog_json(request):
    return JsonResponse(data.catalog_payload())


@require_POST
@permission_required("manage_settings")
def preset_save(request, model_id):
    try:
        preset = catalog.save_preset(model_id, request.POST.get("name", ""), request.POST.getlist("fields"),
                                     request.POST.get("id") or None, default=request.POST.get("default") == "1")
    except CatalogError as exc:
        return _error(str(exc))
    log.info("preset %s/%s saved", model_id, preset["id"])
    return JsonResponse({"preset": preset, "presets": catalog.get_presets(model_id)})


@require_POST
@permission_required("manage_settings")
def preset_delete(request, model_id, preset_id):
    try:
        catalog.delete_preset(model_id, preset_id)
    except CatalogError as exc:
        return _error(str(exc), 404)
    log.info("preset %s/%s deleted", model_id, preset_id)
    return JsonResponse({"presets": catalog.get_presets(model_id)})
