import pytest

from docintel import samples
from docintel.analyze import AnalyzeError, AzureAnalyzer, MockAnalyzer, map_http_error
from docintel.config import get_settings
from docintel.normalize import build_view
from helpers import make_pdf, make_png


class FakeError:
    def __init__(self, code, inner=None):
        self.code = code
        self.innererror = type("Inner", (), {"code": inner})() if inner else None


class FakeHttpError(Exception):
    def __init__(self, status, code="", inner=None, message=""):
        self.status_code = status
        self.error = FakeError(code, inner)
        self.message = message


@pytest.mark.parametrize("status,code,inner,expected,transient", [
    (429, "TooManyRequests", None, "throttled", True),
    (503, "ServiceUnavailable", None, "service", True),
    (500, "InternalServerError", None, "service", True),
    (403, "OutOfCallVolumeQuota", None, "quota", False),
    (403, "AuthorizationFailed", None, "access", False),
    (401, "PermissionDenied", None, "access", False),
    (404, "NotFound", "ModelNotFound", "model", False),
    (400, "InvalidRequest", "InvalidContent", "unsupported", False),
    (400, "InvalidRequest", "UnsupportedContent", "unsupported", False),
    (400, "InvalidRequest", "InvalidContentDimensions", "unsupported", False),
    (400, "InvalidArgument", None, "error", False),
])
def test_azure_errors_become_readable(status, code, inner, expected, transient):
    err = map_http_error(FakeHttpError(status, code, inner), "prebuilt-invoice")
    assert err.code == expected and err.transient == transient
    assert err.message and "Traceback" not in err.message


def test_azure_analyzer_uses_sdk_and_returns_wire_dict(monkeypatch):
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    from azure.core.exceptions import HttpResponseError

    from sdk_fixtures import analysis, invoice_fields

    requests_made = {}

    class Poller:
        def result(self):
            from azure.ai.documentintelligence.models import AnalyzeResult

            return AnalyzeResult(analysis(invoice_fields()))

    class Client:
        def begin_analyze_document(self, model_id, body):
            requests_made["model"] = model_id
            requests_made["body"] = body
            if model_id == "prebuilt-receipt":
                raise HttpResponseError(message="busy", response=type("R", (), {
                    "status_code": 429, "reason": "Too Many Requests", "headers": {}, "text": lambda self: "",
                    "content_type": "application/json", "request": None})())
            return Poller()

    analyzer = AzureAnalyzer.__new__(AzureAnalyzer)
    analyzer.client = Client()
    out = analyzer.analyze(b"%PDF", "prebuilt-invoice")
    assert requests_made["model"] == "prebuilt-invoice" and isinstance(requests_made["body"], AnalyzeDocumentRequest)
    assert out["documents"][0]["fields"]["InvoiceTotal"]["valueCurrency"]["amount"] == 1180.0
    with pytest.raises(AnalyzeError) as e:
        analyzer.analyze(b"%PDF", "prebuilt-receipt")
    assert e.value.code == "throttled" and e.value.transient


def test_azure_analyzer_needs_endpoint():
    with pytest.raises(RuntimeError, match="DOCINTEL_ENDPOINT"):
        AzureAnalyzer(get_settings())


def test_there_are_eight_samples_with_variants():
    all_samples = samples.list_samples()
    assert len(all_samples) == 8
    assert sum(1 for s in all_samples if len(s["pages"]) > 1) == 1
    assert any(s["variants"].get("png", {}).get("rotate") for s in all_samples)
    for s in all_samples:
        for v in s["variants"].values():
            assert samples.get_settings().sample_dir.joinpath(v["file"]).is_file()


@pytest.mark.parametrize("sample", ["inv-01-gst-software", "inv-04-eu-energy", "inv-05-multipage-supplies",
                                    "inv-08-scanned-print"])
def test_mock_returns_sidecar_values_in_sdk_shape(sample):
    s = samples.get_sample(sample)
    for variant in s["variants"]:
        data = samples.sample_path(s, variant).read_bytes()
        result = MockAnalyzer(get_settings()).analyze(data, "prebuilt-invoice")
        assert result.pop("_mock")["source"] == "sample"
        assert result["apiVersion"] == "2024-11-30" and result["modelId"] == "prebuilt-invoice"
        page = result["pages"][0]
        assert page["unit"] == ("inch" if variant == "pdf" else "pixel")
        fields = result["documents"][0]["fields"]
        expected = s["fields"]["InvoiceTotal"]
        got = fields["InvoiceTotal"]
        assert got["valueCurrency"]["amount"] == expected["value"]["amount"]
        assert got["valueCurrency"]["currencyCode"] == expected["value"]["currencyCode"]
        assert 0 < got["confidence"] <= 1
        mapped = samples.variant_polygon(s, variant, expected["polygon"], expected["page"])
        if mapped:
            assert got["boundingRegions"][0]["polygon"] == mapped[1]
        view = build_view({"model_id": "prebuilt-invoice", "analysis": result, "selection": list(s["fields"])}, 0.8)
        assert view["summary"]["need_review"] >= 1  # each sample has low-confidence fields


def test_png_polygons_are_in_pixels():
    s = samples.get_sample("inv-01-gst-software")
    page, poly = samples.variant_polygon(s, "png", [1, 1, 2, 1, 2, 2, 1, 2], 1)
    assert page == 1 and poly == [120, 120, 240, 120, 240, 240, 120, 240]


def test_mock_for_other_files():
    m = MockAnalyzer(get_settings())
    pdf = make_pdf(text="Kestrel Analytics\nInvoice No: KA-77\nInvoice Date: 14/09/2026\nTotal: 1,180.00")
    result = m.analyze(pdf, "prebuilt-invoice")
    assert result["_mock"]["source"] == "text-rules"
    fields = result["documents"][0]["fields"]
    assert fields["InvoiceId"]["valueString"] == "KA-77"
    assert fields["InvoiceDate"]["valueDate"] == "2026-09-14"
    assert fields["InvoiceTotal"]["valueCurrency"]["amount"] == 1180.0
    assert "boundingRegions" not in fields["InvoiceId"]
    empty = m.analyze(make_png(), "prebuilt-invoice")
    assert empty["documents"][0]["fields"] == {} and empty["_mock"]["source"] == "none"
    other_model = m.analyze(samples.sample_path(samples.get_sample("inv-02-us-logistics"), "pdf").read_bytes(),
                            "prebuilt-receipt")
    assert other_model["documents"][0]["fields"] == {}
