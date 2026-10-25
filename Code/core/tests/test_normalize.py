from azure.ai.documentintelligence.models import CurrencyValue, DocumentField

from docintel.normalize import build_view, editable_spec, one_line, parse_edit
from sdk_fixtures import analysis, currency, invoice_fields, record, string


def by_name(view):
    return {f["name"]: f for f in view["fields"]}


def test_strings_dates_currency_addresses():
    view = build_view(record(), 0.80)
    f = by_name(view)
    assert f["VendorName"]["value"] == "Kestrel Analytics Pvt. Ltd."
    assert f["InvoiceDate"]["value"] == "2026-09-14"  # ISO, not as printed
    assert f["InvoiceDate"]["content"] == "14/09/2026"  # raw text as printed
    assert f["SubTotal"]["value"] == 1000.0 and f["SubTotal"]["currency"] == "INR"
    assert f["SubTotal"]["display"] == "1,000.00 INR"
    assert f["VendorAddress"]["value"] == "12 MG Road, Pune 411001, India"
    assert view["api_version"] == "2024-11-30" and view["model_id"] == "prebuilt-invoice"


def test_missing_selected_field_is_not_found_not_omitted():
    view = build_view(record(), 0.80)
    due = by_name(view)["DueDate"]
    assert due["found"] is False and due["value"] is None and not due["needs_review"]
    assert view["summary"]["not_found"] == 1


def test_review_flag_at_threshold():
    f = by_name(build_view(record(), 0.80))
    assert f["InvoiceId"]["needs_review"]  # 0.72 < 0.80
    assert not f["TotalTax"]["needs_review"]  # exactly 0.80 is not below the threshold
    f = by_name(build_view(record(), 0.81))
    assert f["TotalTax"]["needs_review"]


def test_summary_counts_tables_once():
    view = build_view(record(), 0.80)
    # 9 scalar fields + 1 table; review: InvoiceId and the Items table (one cell at 0.55)
    assert view["summary"]["selected"] == 10
    assert view["summary"]["need_review"] == 2
    items = view["tables"][0]
    assert items["low_count"] == 1 and items["needs_review"]


def test_line_items_table_cells_have_confidence_and_boxes():
    items = build_view(record(), 0.80)["tables"][0]
    assert [c["name"] for c in items["columns"]] == ["Description", "Amount"]  # only columns that were found
    assert len(items["all_columns"]) == 9
    cell = items["rows"][1]["cells"]["Amount"]
    assert cell["path"] == "Items[1].Amount"
    assert cell["confidence"] == 0.55 and cell["needs_review"]
    assert cell["regions"][0]["page"] == 1 and len(cell["regions"][0]["polygon"]) == 8


def test_multiple_pages_and_page_units():
    view = build_view(record(), 0.80)
    assert view["pages"] == [{"number": 1, "width": 8.5, "height": 11.0, "unit": "inch"},
                             {"number": 2, "width": 8.5, "height": 11.0, "unit": "inch"}]
    assert by_name(view)["InvoiceTotal"]["page"] == 2
    rec = record(selection=["VendorName"])
    rec["analysis"] = analysis({"VendorName": string("A", x=120, y=40, w=300, h=30)}, unit="pixel", width=1240,
                               height=1754)
    view = build_view(rec, 0.8)
    assert view["pages"][0]["unit"] == "pixel"
    assert view["fields"][0]["regions"][0]["polygon"][:2] == [120, 40]


def test_derived_currency_code():
    f = by_name(build_view(record(), 0.80))["CurrencyCode"]
    assert f["found"] and f["value"] == "INR" and f["derived_from"] == "InvoiceTotal"
    fields = invoice_fields()
    del fields["InvoiceTotal"]
    fields["SubTotal"] = DocumentField(type="currency", value_currency=CurrencyValue(amount=5.0, currency_symbol="€"),
                                       content="€5.00", confidence=0.9)
    f = by_name(build_view(record(fields), 0.80))["CurrencyCode"]
    assert f["value"] == "EUR" and f["derived_from"] == "SubTotal"  # from an unambiguous symbol
    f = by_name(build_view(record({"VendorName": string("x")}), 0.80))["CurrencyCode"]
    assert not f["found"]


def test_currency_without_code_or_known_symbol():
    rec = record({"SubTotal": currency(10.0, code=None, symbol="$")}, selection=["SubTotal"])
    f = build_view(rec, 0.8)["fields"][0]
    assert f["value"] == 10.0 and f["currency"] is None and f["display"] == "10.00"


def test_edits_replace_value_and_keep_model_value():
    rec = record(edits={"InvoiceId": {"value": "KA-0043", "at": "t", "by": "User"},
                        "SubTotal": {"value": "1,050.00", "at": "t", "by": "User"},
                        "Items[1].Amount": {"value": "450", "at": "t", "by": "User"}})
    view = build_view(rec, 0.80)
    f = by_name(view)
    assert f["InvoiceId"]["display"] == "KA-0043" and f["InvoiceId"]["model_value"] == "KA-0042"
    assert f["InvoiceId"]["edited"] and not f["InvoiceId"]["needs_review"]
    assert f["SubTotal"]["value"] == 1050.0 and f["SubTotal"]["display"] == "1,050.00 INR"
    assert view["tables"][0]["rows"][1]["cells"]["Amount"]["value"] == 450.0
    assert view["summary"]["need_review"] == 0 and view["summary"]["edited"] == 3


def test_reviewed_clears_flag_and_selection_change_needs_no_new_analysis():
    rec = record(reviewed=["InvoiceId", "Items"])
    assert build_view(rec, 0.8)["summary"]["need_review"] == 0
    view = build_view(rec, 0.8, selection=["VendorName", "AmountDue"])
    assert [f["name"] for f in view["fields"]] == ["VendorName", "AmountDue"]
    assert view["fields"][1]["found"] is False
    assert "InvoiceTotal" in view["other_fields_found"]


def test_low_confidence_and_empty_fields():
    rec = record({"VendorName": DocumentField(type="string", confidence=0.4)}, selection=["VendorName"])
    f = build_view(rec, 0.8)["fields"][0]
    assert not f["found"]  # a typed field with no value and no text counts as not found


def test_helpers():
    assert one_line("12 Road\n  Pune 411001\nIndia") == "12 Road, Pune 411001, India"
    assert parse_edit("₹1,234.50", "currency") == 1234.5
    assert parse_edit("abc", "string") == "abc"
    assert editable_spec("prebuilt-invoice", "Items[3].Amount").name == "Amount"
    assert editable_spec("prebuilt-invoice", "InvoiceId").name == "InvoiceId"
    import pytest

    from docintel.catalog import CatalogError

    for bad in ("Items", "Items[1].Nope", "../x", "InvoiceId[0].Amount"):
        with pytest.raises(CatalogError):
            editable_spec("prebuilt-invoice", bad)
