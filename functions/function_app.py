"""Document Intelligence upload API.

POST /api/analyze?model=<model-id>&filename=<name>   body = the raw file bytes
GET  /api/results/{id}                               stored extraction result
GET  /api/models                                     models offered in the upload page
GET  /api/health

The app authenticates to Document Intelligence and Blob Storage with its managed identity,
so no keys live in code or settings (apart from the Functions host storage connection).
"""
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
RESULT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MAX_CONTENT_CHARS = 5000
_clients = {}


def _setting(name, default=None):
    return os.environ.get(name, default)


def _blob_service():
    if "blob" not in _clients:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        _clients["blob"] = BlobServiceClient(
            account_url=_setting("STORAGE_ACCOUNT_URL"), credential=DefaultAzureCredential()
        )
    return _clients["blob"]


def _di_client():
    if "di" not in _clients:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.identity import DefaultAzureCredential

        _clients["di"] = DocumentIntelligenceClient(
            endpoint=_setting("DOCINT_ENDPOINT"), credential=DefaultAzureCredential()
        )
    return _clients["di"]


def _json(body, status=200):
    return func.HttpResponse(json.dumps(body), status_code=status, mimetype="application/json")


def _error(message, status):
    return _json({"error": message}, status)


def _safe_filename(name):
    name = os.path.basename(name or "document")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "document"
    return name[:100]


def _value_key(field_type):
    return "value" + field_type[:1].upper() + field_type[1:] if field_type else None


def simplify_field(field):
    """Turn one Document Intelligence field into {value, content, confidence}."""
    if not isinstance(field, dict):
        return {"value": field, "content": None, "confidence": None}
    field_type = field.get("type")
    value = field.get(_value_key(field_type))
    if field_type == "array":
        value = [simplify_field(item)["value"] for item in (value or [])]
    elif field_type == "object":
        value = {name: simplify_field(item)["value"] for name, item in (value or {}).items()}
    elif value is None:
        value = field.get("content")
    return {"value": value, "content": field.get("content"), "confidence": field.get("confidence")}


def build_payload(model, result):
    """Reduce the full analyze result to what the upload page needs."""
    documents = []
    for doc in result.get("documents") or []:
        documents.append(
            {
                "docType": doc.get("docType"),
                "confidence": doc.get("confidence"),
                "fields": {name: simplify_field(f) for name, f in (doc.get("fields") or {}).items()},
            }
        )
    content = result.get("content") or ""
    return {
        "model": model,
        "modelVersion": result.get("modelId"),
        "pages": len(result.get("pages") or []),
        "tables": len(result.get("tables") or []),
        "documents": documents,
        "content": content[:MAX_CONTENT_CHARS],
        "contentTruncated": len(content) > MAX_CONTENT_CHARS,
    }


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json({"status": "ok"})


@app.route(route="models", methods=["GET"])
def models(req: func.HttpRequest) -> func.HttpResponse:
    offered = [m.strip() for m in _setting("AVAILABLE_MODELS", "").split(",") if m.strip()]
    return _json({"default": _setting("DEFAULT_MODEL", "prebuilt-invoice"), "models": offered})


@app.route(route="analyze", methods=["POST"])
def analyze(req: func.HttpRequest) -> func.HttpResponse:
    model = req.params.get("model") or _setting("DEFAULT_MODEL", "prebuilt-invoice")
    if not MODEL_ID_PATTERN.match(model):
        return _error("Invalid model id.", 400)

    data = req.get_body()
    max_bytes = int(_setting("MAX_UPLOAD_MB", "20")) * 1024 * 1024
    if not data:
        return _error("No file received. Send the file as the request body.", 400)
    if len(data) > max_bytes:
        return _error(f"File is larger than {_setting('MAX_UPLOAD_MB', '20')} MB.", 413)

    document_id = uuid.uuid4().hex
    filename = _safe_filename(req.params.get("filename"))
    content_type = req.headers.get("Content-Type", "application/octet-stream")

    try:
        from azure.storage.blob import ContentSettings

        blobs = _blob_service()
        blobs.get_blob_client(_setting("INCOMING_CONTAINER", "incoming"), f"{document_id}/{filename}").upload_blob(
            data, overwrite=True, content_settings=ContentSettings(content_type=content_type)
        )
    except Exception:
        logging.exception("Could not store the uploaded document")
        return _error("Could not store the uploaded document.", 502)

    try:
        poller = _di_client().begin_analyze_document(model, body=io.BytesIO(data), content_type="application/octet-stream")
        result = poller.result().as_dict()
    except Exception as exc:  # the SDK raises HttpResponseError; surface its message, not a stack trace
        logging.exception("Document Intelligence analysis failed")
        status = getattr(exc, "status_code", None)
        message = getattr(exc, "message", None) or "Document Intelligence could not analyze this file."
        return _error(message, 400 if status in (400, 404, 415) else 502)

    payload = build_payload(model, result)
    payload.update(
        {
            "documentId": document_id,
            "fileName": filename,
            "analyzedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    try:
        blobs.get_blob_client(_setting("RESULTS_CONTAINER", "results"), f"{document_id}.json").upload_blob(
            json.dumps(payload), overwrite=True, content_settings=ContentSettings(content_type="application/json")
        )
    except Exception:
        logging.exception("Could not store the result; returning it anyway")
        payload["warning"] = "The result could not be saved to storage."
    return _json(payload)


@app.route(route="results/{id}", methods=["GET"])
def get_result(req: func.HttpRequest) -> func.HttpResponse:
    result_id = req.route_params.get("id", "")
    if not RESULT_ID_PATTERN.match(result_id):
        return _error("Invalid result id.", 400)
    from azure.core.exceptions import ResourceNotFoundError

    try:
        blob = _blob_service().get_blob_client(_setting("RESULTS_CONTAINER", "results"), f"{result_id}.json")
        return func.HttpResponse(blob.download_blob().readall(), status_code=200, mimetype="application/json")
    except ResourceNotFoundError:
        return _error("No result with that id.", 404)
    except Exception:
        logging.exception("Could not read the stored result")
        return _error("Could not read the stored result.", 502)
