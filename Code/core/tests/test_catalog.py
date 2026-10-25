import pytest

from docintel import catalog
from docintel.catalog import CatalogError, load_catalog

REQUIRED_INVOICE_FIELDS = """VendorName VendorTaxId VendorAddress VendorAddressRecipient CustomerName CustomerId
CustomerTaxId CustomerAddress CustomerAddressRecipient BillingAddress BillingAddressRecipient ShippingAddress
ShippingAddressRecipient RemittanceAddress RemittanceAddressRecipient ServiceAddress ServiceAddressRecipient InvoiceId
InvoiceDate DueDate PurchaseOrder PaymentTerm ServiceStartDate ServiceEndDate SubTotal TotalDiscount TotalTax
InvoiceTotal AmountDue PreviousUnpaidBalance CurrencyCode PaymentDetails TaxDetails Items""".split()


def test_catalog_loads_all_models():
    c = load_catalog()
    assert c.api_version == "2024-11-30"
    assert c.default_model == "prebuilt-invoice"
    assert list(c.models) == ["prebuilt-invoice", "prebuilt-receipt", "prebuilt-idDocument", "prebuilt-businessCard"]


def test_invoice_catalog_has_every_required_field():
    model = load_catalog().model("prebuilt-invoice")
    missing = [f for f in REQUIRED_INVOICE_FIELDS if f not in model.fields]
    assert not missing
    items = model.field("Items")
    assert items.is_table
    assert [i.name for i in items.items] == ["Description", "ProductCode", "Quantity", "Unit", "UnitPrice", "Tax",
                                             "TaxRate", "Amount", "Date"]
    assert model.field("CurrencyCode").derived


def test_every_field_has_label_type_and_description():
    allowed = {"string", "date", "time", "number", "integer", "currency", "address", "phoneNumber", "countryRegion",
               "object", "array", "boolean"}
    for model in load_catalog().models.values():
        for f in model.fields.values():
            assert f.label and f.description and f.type in allowed, (model.id, f.name)
            for sub in f.items:
                assert sub.label and sub.type in allowed, (model.id, f.name, sub.name)


def test_business_card_is_listed_but_unavailable():
    c = load_catalog()
    assert not c.model("prebuilt-businessCard").enabled
    with pytest.raises(CatalogError, match="not available"):
        c.enabled_model("prebuilt-businessCard")


def test_validate_selection_orders_and_rejects():
    c = load_catalog()
    assert c.validate_selection("prebuilt-invoice", ["InvoiceTotal", "VendorName", "InvoiceTotal"]) == \
        ["VendorName", "InvoiceTotal"]
    with pytest.raises(CatalogError, match="Unknown field"):
        c.validate_selection("prebuilt-invoice", ["VendorName", "MadeUpField"])
    with pytest.raises(CatalogError, match="at least one"):
        c.validate_selection("prebuilt-invoice", [])
    with pytest.raises(CatalogError, match="Unknown model"):
        c.validate_selection("prebuilt-layout", ["x"])


def test_builtin_presets_reference_real_fields():
    for model_id in load_catalog().models:
        presets = catalog.get_presets(model_id)
        assert presets
        assert sum(1 for p in presets if p["default"]) == 1
    names = [p["name"] for p in catalog.get_presets("prebuilt-invoice")]
    assert names == ["Accounts payable basics", "Header with addresses", "Full invoice with line items", "Tax review"]
    assert catalog.default_fields("prebuilt-invoice")[0] == "VendorName"


def test_admin_presets_create_edit_delete_without_redeploy():
    saved = catalog.save_preset("prebuilt-invoice", "Month-end close", ["InvoiceTotal", "VendorName"])
    assert saved["id"] == "month-end-close"
    assert saved["fields"] == ["VendorName", "InvoiceTotal"]
    assert any(p["id"] == "month-end-close" and not p["builtin"] for p in catalog.get_presets("prebuilt-invoice"))

    catalog.save_preset("prebuilt-invoice", "Month-end close", ["AmountDue"], "month-end-close")
    p = next(p for p in catalog.get_presets("prebuilt-invoice") if p["id"] == "month-end-close")
    assert p["fields"] == ["AmountDue"]

    # Editing a built-in preset replaces it; deleting it hides it.
    catalog.save_preset("prebuilt-invoice", "Tax review (short)", ["TotalTax"], "tax-review")
    p = next(p for p in catalog.get_presets("prebuilt-invoice") if p["id"] == "tax-review")
    assert p["name"] == "Tax review (short)" and p["builtin"]
    catalog.delete_preset("prebuilt-invoice", "tax-review")
    catalog.delete_preset("prebuilt-invoice", "month-end-close")
    ids = [p["id"] for p in catalog.get_presets("prebuilt-invoice")]
    assert "tax-review" not in ids and "month-end-close" not in ids
    with pytest.raises(CatalogError):
        catalog.delete_preset("prebuilt-invoice", "month-end-close")


def test_preset_validation():
    with pytest.raises(CatalogError):
        catalog.save_preset("prebuilt-invoice", "", ["VendorName"])
    with pytest.raises(CatalogError):
        catalog.save_preset("prebuilt-invoice", "x" * 61, ["VendorName"])
    with pytest.raises(CatalogError):
        catalog.save_preset("prebuilt-invoice", "Bad", ["NoSuchField"])
    with pytest.raises(CatalogError):
        catalog.save_preset("prebuilt-invoice", "Bad id", ["VendorName"], preset_id="../x")
