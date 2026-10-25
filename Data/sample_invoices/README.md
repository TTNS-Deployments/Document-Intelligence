# Sample invoices

Eight invented invoices for demos and tests. All companies, people, addresses, tax numbers and bank details are
made up. They are packaged with the web app, so **Try a sample** on the Extract page works in every environment.

| ID | Layout | Currency | Tax | Files |
|---|---|---|---|---|
| `inv-01-gst-software` | Indian GST tax invoice, GSTINs for both parties | INR | CGST 9% + SGST 9% | PDF, PNG |
| `inv-02-us-logistics` | US Letter, ship-to address | USD | Sales tax 7.25% | PDF, PNG |
| `inv-03-uk-interiors` | UK invoice with bank details (IBAN, SWIFT) | GBP | VAT 20% | PDF, PNG |
| `inv-04-eu-energy` | Energy bill with a service period and service address | EUR | VAT 19% and 7% | PDF, PNG |
| `inv-05-multipage-supplies` | Two pages, 42 line items, previous balance | INR | IGST 18% | PDF |
| `inv-06-au-consulting` | Consulting, BPay payment details | AUD | GST 10% | PDF, PNG |
| `inv-07-sg-discount` | Discount and remittance address | SGD | GST 9% | PDF, PNG |
| `inv-08-scanned-print` | Scanned copy: grey, noisy, rotated 0.8 degrees, lower confidence | INR | CGST 6% + SGST 6% | PNG |

Each `<id>.json` sidecar holds the expected value, printed text, confidence, page and polygon of every field
(polygons in inches from the top-left corner, as Document Intelligence reports them for PDFs), and one entry per
file variant with its SHA-256. In local mode the mock analyzer recognises a sample by its SHA-256 and returns the
sidecar as an SDK-shaped result (PNG pages in pixels; for the scanned copy the rotation is applied to every polygon).
The UI tests compare the drawn highlight boxes with these polygons.

Each sample has one to three fields with a confidence below 0.80, so Review chips appear in demos. With real Azure
AI Document Intelligence the values and confidences come from the service and will differ.

Regenerate (only needed after changing the generator):

```bash
.venv/bin/python Data/sample_invoices/generate.py
```

It needs the development requirements (`reportlab`, `pymupdf`, `pillow`) and the DejaVu Sans fonts.
