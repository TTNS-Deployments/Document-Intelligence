"""Document Intelligence clients: the real one (Azure SDK) and a mock for local mode.

Both return the analysis as the SDK's wire-format dictionary (``AnalyzeResult.as_dict()``: ``modelId``,
``pages[].width/height/unit``, ``documents[].fields`` with ``valueString``, ``valueCurrency``, ``boundingRegions``,
and so on), which is what is stored in the results container and what ``normalize`` reads.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
import time

from .config import Settings

log = logging.getLogger(__name__)
LAYOUT_MODEL = "prebuilt-layout"  # the only model that detects pictures (figures) and returns them as images
MAX_FIGURES = 20


class AnalyzeError(Exception):
    """A failed analysis, with a message that can be shown to users (it never contains document content)."""

    def __init__(self, code: str, message: str, *, transient: bool = False, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.transient = transient
        self.status = status


def map_http_error(exc, model_id: str = "") -> AnalyzeError:
    """Turn an azure-core HttpResponseError into readable text. Covers the errors users actually meet."""
    status = getattr(exc, "status_code", None) or 0
    error = getattr(exc, "error", None)
    code = (getattr(error, "code", None) or "").strip()
    inner = getattr(error, "innererror", None)
    inner_code = (getattr(inner, "code", None) or "").strip() if inner else ""
    text = f"{code} {inner_code} {getattr(exc, 'message', '')}".lower()

    if status == 429:
        return AnalyzeError("throttled", "Document Intelligence is busy and asked the app to slow down (HTTP 429). "
                                         "Wait a minute and retry.", transient=True, status=status)
    if status >= 500:
        return AnalyzeError("service", f"Document Intelligence had a temporary problem (HTTP {status}). Retry later.",
                            transient=True, status=status)
    if status == 403 and ("quota" in text or "outofcallvolume" in text):
        return AnalyzeError("quota", "The Document Intelligence quota is used up for this period (the free F0 tier "
                                     "allows 500 pages a month). Wait for the quota to reset or move to the S0 tier.",
                            status=status)
    if status in (401, 403):
        return AnalyzeError("access", "The app is not allowed to call Document Intelligence. Check that the web app's "
                                      "managed identity has the Cognitive Services User role and that network rules "
                                      "allow it.", status=status)
    if status == 404 or "modelnotfound" in text:
        return AnalyzeError("model", f"The model {model_id or '(unknown)'} is not available on this Document "
                                     "Intelligence resource. The region may not offer it: see the deployment guide "
                                     "(docIntelLocation).", status=status)
    if status in (400, 415) and any(k in text for k in ("invalidcontent", "unsupportedcontent", "invalidimage",
                                                        "invalidcontentdimensions", "unsupportedmediatype",
                                                        "invalidcontentlength", "corrupt", "password")):
        return AnalyzeError("unsupported", "Document Intelligence could not read this file. It may be damaged, "
                                           "password-protected, too small or too large, or in a format the model "
                                           "does not support.", status=status)
    return AnalyzeError("error", f"Document Intelligence returned an error (HTTP {status or '?'}"
                                 f"{', ' + code if code else ''}).", status=status)


class AzureAnalyzer:
    """Uses ``begin_analyze_document`` with the managed identity (DefaultAzureCredential). The SDK polls."""

    def __init__(self, settings: Settings):
        from azure.ai.documentintelligence import DocumentIntelligenceClient

        if not settings.docintel_endpoint:
            raise RuntimeError("DOCINTEL_ENDPOINT is not set")
        if settings.docintel_key:  # developer machines only; Azure deployments disable key access
            from azure.core.credentials import AzureKeyCredential

            credential = AzureKeyCredential(settings.docintel_key)
        else:
            from .azure_auth import get_credential

            credential = get_credential()
        # The SDK retries twice itself (honouring Retry-After); the job adds slower retries on top.
        self.client = DocumentIntelligenceClient(settings.docintel_endpoint, credential,
                                                 api_version=settings.docintel_api_version, retry_total=2)
        self.api_version = settings.docintel_api_version

    def analyze(self, data: bytes, model_id: str, *, include_images: bool = True, original: bytes | None = None) -> dict:
        """Analyse ``data`` (already without pictures when images are excluded; ``original`` is for the mock)."""
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

        with self._errors(model_id):
            poller = self.client.begin_analyze_document(model_id, AnalyzeDocumentRequest(bytes_source=data))
            return poller.result().as_dict()

    def extract_figures(self, data: bytes, *, original: bytes | None = None) -> list[dict]:
        """Pictures in the document (logos, photos, charts) as cropped PNGs, from the Layout model.

        A second analysis of the same file: the pre-built invoice, receipt and ID models do not return pictures.
        """
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, AnalyzeOutputOption

        with self._errors(LAYOUT_MODEL):
            poller = self.client.begin_analyze_document(LAYOUT_MODEL, AnalyzeDocumentRequest(bytes_source=data),
                                                        output=[AnalyzeOutputOption.FIGURES])
            result = poller.result()
            operation_id = poller.details["operation_id"]
            out = []
            for fig in (result.figures or [])[:MAX_FIGURES]:
                region = (fig.bounding_regions or [None])[0]
                png = b"".join(self.client.get_analyze_result_figure(model_id=LAYOUT_MODEL, result_id=operation_id,
                                                                     figure_id=fig.id))
                out.append({"id": fig.id, "page": region.page_number if region else 1,
                            "polygon": list(region.polygon) if region else [],
                            "caption": fig.caption.content if fig.caption else "", "png": png})
            return out

    @contextlib.contextmanager
    def _errors(self, model_id: str):
        from azure.core.exceptions import (ClientAuthenticationError, HttpResponseError, ServiceRequestError,
                                           ServiceResponseError)

        try:
            yield
        except ClientAuthenticationError as exc:
            log.warning("Document Intelligence authentication failed: %s", type(exc).__name__)
            raise AnalyzeError("access", "The app could not sign in to Document Intelligence with its managed "
                                         "identity. Check the identity and its role assignment.") from exc
        except HttpResponseError as exc:
            raise map_http_error(exc, model_id) from exc
        except (ServiceRequestError, ServiceResponseError) as exc:
            raise AnalyzeError("network", "Could not reach Document Intelligence (network error). Retry later.",
                               transient=True) from exc


class MockAnalyzer:
    """Local mode. Returns SDK-shaped results without calling Azure.

    * A bundled sample invoice (matched by SHA-256 of the file) gets the expected fields, confidences and
      polygons from its sidecar JSON, built with the SDK's own model classes.
    * Any other PDF gets a best-effort result from simple text rules on its text layer (marked as a mock).
    * Any other image gets a result with no fields.

    Test hooks: a PDF whose text contains ``DOCINTEL-MOCK-FAIL`` fails as unsupported, and one containing
    ``DOCINTEL-MOCK-THROTTLE`` fails with HTTP 429 every time (to exercise retries).
    """

    api_version = "2024-11-30"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_version = settings.docintel_api_version

    def analyze(self, data: bytes, model_id: str, *, include_images: bool = True, original: bytes | None = None) -> dict:
        from . import samples

        if self.settings.mock_delay_seconds:
            time.sleep(self.settings.mock_delay_seconds)
        sample = samples.find_by_content(original or data)  # the original: pictures may have been removed
        if sample is not None:
            result = samples.build_result(sample, data, model_id, self.api_version, include_images=include_images)
            result["_mock"] = {"source": "sample", "sample": sample["id"],
                               "note": "Expected values of a bundled sample document; Azure is not called."}
            return result
        if data.startswith(b"%PDF"):
            return self._from_text_layer(data, model_id)
        return self._empty(model_id, pages=[{"pageNumber": 1, "width": 1000, "height": 1000, "unit": "pixel",
                                             "spans": []}],
                           note="Images that are not bundled samples return no fields.")

    def extract_figures(self, data: bytes, *, original: bytes | None = None) -> list[dict]:
        """Pictures of a bundled sample (stored next to it); other files have none in local mode."""
        from . import samples

        if self.settings.mock_delay_seconds:
            time.sleep(self.settings.mock_delay_seconds / 2)
        sample = samples.find_by_content(original or data)
        return samples.figures_for(sample) if sample is not None else []

    def _empty(self, model_id: str, pages: list, note: str, content: str = "") -> dict:
        from azure.ai.documentintelligence.models import AnalyzeResult, AnalyzedDocument, DocumentPage

        result = AnalyzeResult(api_version=self.api_version, model_id=model_id, content=content,
                               pages=[DocumentPage(p) for p in pages],
                               documents=[AnalyzedDocument(doc_type=model_id.removeprefix("prebuilt-"), fields={},
                                                           confidence=0.0, spans=[])]).as_dict()
        result["_mock"] = {"source": "none", "note": note}
        return result

    def _from_text_layer(self, data: bytes, model_id: str) -> dict:
        from azure.ai.documentintelligence.models import (AnalyzeResult, AnalyzedDocument, CurrencyValue,
                                                          DocumentField, DocumentPage)
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages, texts = [], []
        for i, page in enumerate(reader.pages, start=1):
            box = page.mediabox
            pages.append(DocumentPage(page_number=i, width=round(float(box.width) / 72, 4),
                                      height=round(float(box.height) / 72, 4), unit="inch", spans=[]))
            try:
                texts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - odd PDFs: treat as no text
                texts.append("")
        text = "\n".join(texts)
        if "DOCINTEL-MOCK-FAIL" in text:
            raise AnalyzeError("unsupported", "Document Intelligence could not read this file (mock failure).",
                               status=400)
        if "DOCINTEL-MOCK-THROTTLE" in text:
            raise AnalyzeError("throttled", "Document Intelligence is busy and asked the app to slow down (HTTP 429). "
                                            "Wait a minute and retry.", transient=True, status=429)

        fields = {}
        if model_id == "prebuilt-invoice":
            for name, value_type, value, content in _text_rules(text):
                if value_type == "currency":
                    fields[name] = DocumentField(type="currency", value_currency=CurrencyValue(amount=value),
                                                 content=content, confidence=0.5)
                elif value_type == "date":
                    fields[name] = DocumentField(type="date", value_date=value, content=content, confidence=0.5)
                else:
                    fields[name] = DocumentField(type="string", value_string=value, content=content, confidence=0.5)
        result = AnalyzeResult(api_version=self.api_version, model_id=model_id, content=text[:20000], pages=pages,
                               documents=[AnalyzedDocument(doc_type=model_id.removeprefix("prebuilt-"), fields=fields,
                                                           confidence=0.5 if fields else 0.0, spans=[])]).as_dict()
        result["_mock"] = {"source": "text-rules",
                           "note": "Best-effort values from simple text rules, without highlight boxes. "
                                   "Real results come from Azure AI Document Intelligence."}
        return result


_DATE_PATTERNS = (
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), lambda m: (m[1], m[2], m[3])),
    (re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})"), lambda m: (m[3], m[2].zfill(2), m[1].zfill(2))),  # day first
)


def _parse_date(text: str):
    import datetime as dt

    for pattern, parts in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            y, mo, d = parts(m)
            try:
                return dt.date(int(y), int(mo), int(d))
            except ValueError:
                continue
    return None


def _text_rules(text: str):
    """(field, type, value, content) for a few invoice fields found with regular expressions."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        yield "VendorName", "string", lines[0][:80], lines[0][:80]
    m = re.search(r"invoice\s*(?:no\.?|number|#|id)\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-]{2,30})", text, re.I)
    if m:
        yield "InvoiceId", "string", m[1], m[0]
    for name, label in (("InvoiceDate", r"(?:invoice\s*date|date\s*of\s*issue|dated?)"), ("DueDate", r"due\s*date")):
        m = re.search(label + r"\s*[:\-]?\s*([0-9][0-9/.\-]{6,10})", text, re.I)
        if m and (d := _parse_date(m[1])):
            yield name, "date", d, m[0]
    for name, label in (("InvoiceTotal", r"(?:invoice\s*total|grand\s*total|total)"), ("AmountDue", r"amount\s*due")):
        m = re.search(label + r"\s*[:\-]?\s*[A-Z₹$€£]{0,3}\s*([0-9][0-9,]*\.?[0-9]{0,2})", text, re.I)
        if m:
            try:
                yield name, "currency", float(m[1].replace(",", "")), m[0]
            except ValueError:
                pass
