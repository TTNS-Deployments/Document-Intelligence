"""Analysis results built with the SDK's own model classes (not hand-written JSON), then serialised with
``as_dict()`` exactly as the app stores them."""

import datetime as dt

from azure.ai.documentintelligence.models import (AddressValue, AnalyzedDocument, AnalyzeResult, BoundingRegion,
                                                  CurrencyValue, DocumentField, DocumentPage)


def region(page=1, x=1.0, y=1.0, w=1.0, h=0.2):
    return [BoundingRegion(page_number=page, polygon=[x, y, x + w, y, x + w, y + h, x, y + h])]


def string(value, conf=0.95, page=1, **kw):
    return DocumentField(type="string", value_string=value, content=value, confidence=conf,
                         bounding_regions=region(page, **kw))


def date(iso, printed, conf=0.95, page=1):
    return DocumentField(type="date", value_date=dt.date.fromisoformat(iso), content=printed, confidence=conf,
                         bounding_regions=region(page))


def currency(amount, code="INR", symbol="₹", printed=None, conf=0.95, page=1):
    kwargs = {"amount": amount, "currency_symbol": symbol}
    if code:
        kwargs["currency_code"] = code
    return DocumentField(type="currency", value_currency=CurrencyValue(**kwargs),
                         content=printed or f"{symbol}{amount:,.2f}", confidence=conf, bounding_regions=region(page))


def address(lines, conf=0.9, page=1):
    return DocumentField(type="address", value_address=AddressValue(street_address=lines[0], city="Pune",
                                                                    postal_code="411001"),
                         content="\n".join(lines), confidence=conf, bounding_regions=region(page, h=0.5))


def items(rows, page=1):
    out = []
    for i, row in enumerate(rows):
        fields = {}
        for name, value in row.items():
            if isinstance(value, DocumentField):
                fields[name] = value
            elif isinstance(value, float):
                fields[name] = currency(value, printed=f"{value:,.2f}", page=page)
            else:
                fields[name] = string(value, page=page, y=3 + i * 0.3)
        out.append(DocumentField(type="object", value_object=fields, confidence=0.9,
                                 bounding_regions=region(page, y=3 + i * 0.3, w=6)))
    return DocumentField(type="array", value_array=out)


def analysis(fields, pages=1, unit="inch", width=8.5, height=11.0, model="prebuilt-invoice"):
    return AnalyzeResult(
        api_version="2024-11-30", model_id=model, content="",
        pages=[DocumentPage(page_number=n, width=width, height=height, unit=unit, spans=[])
               for n in range(1, pages + 1)],
        documents=[AnalyzedDocument(doc_type="invoice", fields=fields, confidence=1.0, spans=[])],
    ).as_dict()


def invoice_fields():
    return {
        "VendorName": string("Kestrel Analytics Pvt. Ltd.", 0.98),
        "InvoiceId": string("KA-0042", 0.72),
        "InvoiceDate": date("2026-09-14", "14/09/2026"),
        "VendorAddress": address(["12 MG Road", "Pune 411001", "India"]),
        "SubTotal": currency(1000.0),
        "TotalTax": currency(180.0, conf=0.80),
        "InvoiceTotal": currency(1180.0, page=2),
        "Items": items([{"Description": "Consulting", "Amount": 600.0},
                        {"Description": "Support", "Amount": DocumentField(
                            type="currency", value_currency=CurrencyValue(amount=400.0, currency_code="INR"),
                            content="400.00", confidence=0.55, bounding_regions=region(1, y=3.3))}]),
    }


def record(fields=None, selection=None, **kw):
    rec = {"id": "0123456789abcdef", "batch_id": "0123456789abcdef", "filename": "invoice.pdf", "kind": "pdf",
           "content_type": "application/pdf", "size": 100, "pages": 2, "sha256": "x", "model_id": "prebuilt-invoice",
           "api_version": "2024-11-30", "status": "done", "error": None,
           "selection": selection or ["VendorName", "InvoiceId", "InvoiceDate", "DueDate", "VendorAddress",
                                      "CurrencyCode", "SubTotal", "TotalTax", "InvoiceTotal", "Items"],
           "analysis": analysis(fields if fields is not None else invoice_fields(), pages=2),
           "edits": {}, "reviewed": [], "created_at": "2026-09-14T10:00:00+00:00"}
    rec.update(kw)
    return rec
