"""Generates the sample invoices in this folder: a PDF, usually a PNG, and a sidecar JSON per invoice.

    .venv/bin/python Data/sample_invoices/generate.py               # every sample
    .venv/bin/python Data/sample_invoices/generate.py inv-09-logo-brand   # only these (others untouched)

Needs the development requirements (reportlab, pymupdf, pillow) and the DejaVu Sans fonts
(/usr/share/fonts/truetype/dejavu, package fonts-dejavu-core). The output is committed, so running this is only
needed after changing it. All companies, people, addresses and tax numbers are invented.

Every value that the pre-built invoice model would return is drawn through ``Page.text``, which records its exact
polygon (inches from the top-left corner of the page, clockwise from top-left, as Document Intelligence reports
them). The sidecar holds those polygons with an expected value and a confidence per field. The PNG variants are
rendered from the PDF; the "scanned" sample is degraded and slightly rotated, and its sidecar records the rotation
so polygons can be mapped onto the image.
"""

from __future__ import annotations

import hashlib
import io
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
pdfmetrics.registerFont(TTFont("Sans", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
ASCENT, DESCENT = 0.76, 0.24  # fraction of the font size above / below the baseline (DejaVu Sans, rounded)


def fmt(amount: float, decimals: int = 2, indian: bool = False) -> str:
    if not indian:
        return f"{amount:,.{decimals}f}"
    whole, _, frac = f"{amount:.{decimals}f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = ",".join(groups + [tail]) if groups else tail
    return f"{text}.{frac}" if decimals else text


@dataclass
class Page:
    c: canvas.Canvas
    number: int
    width_in: float
    height_in: float

    def text(self, x: float, y: float, s: str, size: float = 9, bold: bool = False, color: str = "#1f2937",
             align: str = "left") -> list[float]:
        """Draw ``s`` with its baseline at ``y`` inches from the top; returns its polygon in inches."""
        poly = self.measure(x, y, s, size, bold, align)
        self.c.setFont("Sans-Bold" if bold else "Sans", size)
        self.c.setFillColor(HexColor(color))
        self.c.drawString(poly[0] * 72, (self.height_in - y) * 72, s)
        return poly

    @staticmethod
    def measure(x: float, y: float, s: str, size: float = 9, bold: bool = False, align: str = "left") -> list[float]:
        """The polygon ``text`` would draw, without drawing (for text that is already on the page)."""
        w = pdfmetrics.stringWidth(s, "Sans-Bold" if bold else "Sans", size) / 72
        if align == "right":
            x -= w
        elif align == "center":
            x -= w / 2
        top, bottom = y - ASCENT * size / 72, y + DESCENT * size / 72
        return [round(v, 4) for v in (x, top, x + w, top, x + w, bottom, x, bottom)]

    def lines(self, x: float, y: float, rows: list[str], size: float = 9, leading: float = 0.17, **kw) -> list[float]:
        polys = [self.text(x, y + i * leading, r, size, **kw) for i, r in enumerate(rows)]
        return union(polys)

    def rect(self, x, y, w, h, fill="#f3f4f6", stroke=None):
        self.c.setFillColor(HexColor(fill))
        if stroke:
            self.c.setStrokeColor(HexColor(stroke))
        self.c.rect(x * 72, (self.height_in - y - h) * 72, w * 72, h * 72, fill=1, stroke=1 if stroke else 0)

    def hline(self, x1, x2, y, color="#d1d5db", width=0.6):
        self.c.setStrokeColor(HexColor(color))
        self.c.setLineWidth(width)
        self.c.line(x1 * 72, (self.height_in - y) * 72, x2 * 72, (self.height_in - y) * 72)


def union(polys: list[list[float]]) -> list[float]:
    xs = [v for p in polys for v in p[0::2]]
    ys = [v for p in polys for v in p[1::2]]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return [round(v, 4) for v in (x0, y0, x1, y0, x1, y1, x0, y1)]


@dataclass
class Recorder:
    rng: random.Random
    low: dict
    fields: dict = field(default_factory=dict)

    def conf(self, name: str) -> float:
        if name in self.low:
            return self.low[name]
        return round(self.rng.uniform(0.88, 0.995), 3)

    def put(self, name, kind, value, content, poly, page, conf=None):
        self.fields[name] = {"type": kind, "value": value, "content": content, "confidence": conf or self.conf(name),
                             "page": page, "polygon": poly}


# --------------------------------------------------------------------------------------------- invoices

INVOICES = [
    {
        "id": "inv-01-gst-software", "title": "Software services, Indian GST (CGST + SGST)", "size": A4,
        "currency": "INR", "symbol": "₹", "indian": True, "accent": "#0f766e", "style": "band",
        "vendor": ["Arunodaya Software Solutions Pvt. Ltd.", "4th Floor, Tower B, Lakeside Tech Park",
                   "Outer Ring Road, Bengaluru, Karnataka 560103", "India"],
        "vendor_tax": ("GSTIN", "29AAACA0000A1Z5"),
        "customer": ["Meghdoot Retail Ventures LLP", "Plot 12, Sector 18, Udyog Vihar", "Gurugram, Haryana 122015"],
        "customer_tax": ("GSTIN", "06AAAFM0000B1Z2"), "customer_id": "CUST-20418",
        "invoice_id": "ASS/2026-27/0142", "date": ("2026-09-14", "14-09-2026"), "due": ("2026-10-14", "14-10-2026"),
        "po": "PO-MRV-7781", "terms": "Net 30",
        "items": [("Cloud platform subscription (Sep 2026)", "SAAS-ENT", 1, "month", 84000.00, "18%"),
                  ("Implementation services", "SRV-IMPL", 24, "hours", 2500.00, "18%"),
                  ("Additional user licences", "LIC-USR", 15, "users", 650.00, "18%")],
        "tax": [("CGST 9%", 0.09, "9 %"), ("SGST 9%", 0.09, "9 %")],
        "low": {"CustomerTaxId": 0.71, "PurchaseOrder": 0.76},
        "png": {"scale": 120, "confidence_factor": 0.97},
        "note": "Amounts in Indian rupees. This is a computer-generated invoice.",
    },
    {
        "id": "inv-02-us-logistics", "title": "Freight services, US sales tax", "size": LETTER,
        "currency": "USD", "symbol": "$", "accent": "#1d4ed8", "style": "plain",
        "vendor": ["Bluefin Freight & Logistics Inc.", "2200 Harbor Point Blvd, Suite 410", "Oakland, CA 94607"],
        "vendor_tax": ("EIN", "00-0000417"),
        "customer": ["Cedar Ridge Outfitters", "88 Timberline Road", "Boise, ID 83702"],
        "shipping": ["Cedar Ridge Distribution Center", "4100 Industrial Way", "Nampa, ID 83687"],
        "invoice_id": "BF-104882", "date": ("2026-08-03", "08/03/2026"), "due": ("2026-09-02", "09/02/2026"),
        "po": "CRO-55120", "terms": "Net 30", "customer_id": "C-0931",
        "items": [("Full truckload, Oakland to Nampa", "FTL-OAK-NAM", 1, "trip", 3850.00, None),
                  ("Liftgate delivery", "ACC-LIFT", 1, "stop", 145.00, None),
                  ("Fuel surcharge", "FSC", 1, "trip", 412.50, None),
                  ("Pallet wrap and labels", "MAT-WRAP", 26, "pallets", 6.75, None)],
        "tax": [("Sales tax 7.25%", 0.0725, "7.25 %")],
        "low": {"ShippingAddress": 0.74},
        "png": {"scale": 120, "confidence_factor": 0.96},
        "note": "Thank you for your business. Late payments accrue 1.5% interest per month.",
    },
    {
        "id": "inv-03-uk-interiors", "title": "Interior fit-out, UK VAT with bank details", "size": A4,
        "currency": "GBP", "symbol": "£", "accent": "#7c3aed", "style": "band",
        "vendor": ["Maple & Larch Interiors Ltd", "Unit 7, Riverside Studios", "Leeds LS10 1AB", "United Kingdom"],
        "vendor_tax": ("VAT No.", "GB000123456"),
        "customer": ["Harbourline Dental Practice", "21 Quay Street", "Bristol BS1 4DB"],
        "invoice_id": "ML-2026-0371", "date": ("2026-07-21", "21 Jul 2026"), "due": ("2026-08-04", "4 Aug 2026"),
        "terms": "14 days",
        "items": [("Reception desk, oak veneer, bespoke", "RD-OAK-01", 1, "unit", 3200.00, "20%"),
                  ("Acoustic wall panels", "AP-60", 18, "panels", 85.00, "20%"),
                  ("Installation labour", "LAB-INST", 16, "hours", 48.00, "20%")],
        "tax": [("VAT 20%", 0.20, "20 %")],
        "payment": {"IBAN": "GB00 TEST 0000 0012 3456 78", "SWIFT": "TESTGB2L", "BankAccountNumber": "12345678"},
        "low": {"DueDate": 0.68},
        "png": {"scale": 120, "confidence_factor": 0.97},
        "note": "Please pay by bank transfer quoting the invoice number.",
    },
    {
        "id": "inv-04-eu-energy", "title": "Energy bill, two VAT rates and a service period", "size": A4,
        "currency": "EUR", "symbol": "€", "accent": "#b45309", "style": "plain",
        "vendor": ["Nordlicht Energie Versorgung GmbH", "Hafenstraße 18", "20457 Hamburg", "Germany"],
        "vendor_tax": ("USt-IdNr.", "DE000999111"),
        "customer": ["Atelier Weiss & Partner", "Kantstraße 52", "10625 Berlin"],
        "service": ["Atelier Weiss & Partner, Werkstatt", "Lindenallee 3", "14050 Berlin"],
        "invoice_id": "NEV-88213-26", "date": ("2026-09-30", "30.09.2026"), "due": ("2026-10-21", "21.10.2026"),
        "period": (("2026-09-01", "01.09.2026"), ("2026-09-30", "30.09.2026")), "customer_id": "KD-4471029",
        "items": [("Electricity, 1,842 kWh at 0.2810 per kWh", "STROM-GEW", 1842, "kWh", 0.2810, "19%"),
                  ("Base charge (monthly)", "GRUND", 1, "month", 14.90, "19%"),
                  ("Meter rental", "ZAEHLER", 1, "month", 2.50, "7%")],
        "tax": "split",
        "previous": 0.00,
        "low": {"ServiceStartDate": 0.73, "ServiceEndDate": 0.77},
        "png": {"scale": 120, "confidence_factor": 0.96},
        "note": "Prices include network charges and levies as applicable.",
    },
    {
        "id": "inv-05-multipage-supplies", "title": "Industrial supplies, 2 pages, 42 line items", "size": A4,
        "currency": "INR", "symbol": "₹", "indian": True, "accent": "#be123c", "style": "plain",
        "vendor": ["Sahyadri Industrial Supplies", "Gala 14, MIDC Bhosari", "Pune, Maharashtra 411026"],
        "vendor_tax": ("GSTIN", "27AAAFS0000C1Z9"),
        "customer": ["Konkan Precision Engineering Pvt. Ltd.", "Survey No. 88, Chakan Industrial Area",
                     "Pune, Maharashtra 410501"],
        "customer_tax": ("GSTIN", "27AAACK0000D1Z1"),
        "invoice_id": "SIS/26/3318", "date": ("2026-08-28", "28/08/2026"), "due": ("2026-09-27", "27/09/2026"),
        "po": "KPE/PO/26/0912", "terms": "30 days",
        "items": "many",
        "tax": [("IGST 18%", 0.18, "18 %")],
        "previous": 18450.00,
        "low": {"PreviousUnpaidBalance": 0.69},
        "png": None,
        "note": "Goods once sold will not be taken back. Subject to Pune jurisdiction.",
    },
    {
        "id": "inv-06-au-consulting", "title": "Consulting, Australian GST and BPay", "size": A4,
        "currency": "AUD", "symbol": "$", "accent": "#0369a1", "style": "minimal",
        "vendor": ["Wattle Grove Advisory Pty Ltd", "Level 9, 120 Collins Street", "Melbourne VIC 3000"],
        "vendor_tax": ("ABN", "00 000 000 417"),
        "customer": ["Coral Bay Tourism Co-operative", "5 Esplanade", "Cairns QLD 4870"],
        "invoice_id": "WGA-0457", "date": ("2026-09-05", "05/09/2026"), "due": ("2026-09-19", "19/09/2026"),
        "terms": "Due in 14 days",
        "items": [("Strategy workshop facilitation", "WS-01", 2, "days", 2400.00, "10%"),
                  ("Market research report", "RPT-MR", 1, "report", 3600.00, "10%")],
        "tax": [("GST 10%", 0.10, "10 %")],
        "payment": {"BPayBillerCode": "000417", "BPayReference": "4570002618"},
        "low": {"VendorTaxId": 0.66},
        "png": {"scale": 120, "confidence_factor": 0.97},
        "note": "Payment by BPay or EFT.",
    },
    {
        "id": "inv-07-sg-discount", "title": "Office equipment, discount and remittance address", "size": A4,
        "currency": "SGD", "symbol": "S$", "accent": "#15803d", "style": "band",
        "vendor": ["Merlion Office Systems Pte. Ltd.", "10 Ubi Crescent, #05-21", "Singapore 408564"],
        "vendor_tax": ("GST Reg. No.", "M90000417X"),
        "customer": ["Tembusu Learning Centre", "301 Upper Thomson Road, #03-12", "Singapore 574408"],
        "remit": ["Merlion Office Systems, Accounts", "PO Box 4170, Robinson Road", "Singapore 904170"],
        "invoice_id": "MOS-INV-6620", "date": ("2026-06-12", "12 Jun 2026"), "due": ("2026-07-12", "12 Jul 2026"),
        "terms": "30 days", "po": "TLC-2026-044",
        "items": [("Ergonomic office chair", "CH-ERG-2", 12, "pcs", 289.00, "9%"),
                  ("Height-adjustable desk 140 cm", "DK-HA-140", 6, "pcs", 520.00, "9%"),
                  ("Monitor arm, dual", "MA-D2", 6, "pcs", 89.00, "9%")],
        "discount": 0.05,
        "tax": [("GST 9%", 0.09, "9 %")],
        "low": {"TotalDiscount": 0.72},
        "png": {"scale": 120, "confidence_factor": 0.96},
        "note": "Goods remain our property until paid in full.",
    },
    {
        "id": "inv-08-scanned-print", "title": "Printing job, scanned copy (low quality)", "size": A4,
        "currency": "INR", "symbol": "₹", "indian": True, "accent": "#374151", "style": "minimal",
        "vendor": ["Lakeview Print House", "Shop 3, Gandhi Market Road", "Bhopal, Madhya Pradesh 462001"],
        "vendor_tax": ("GSTIN", "23AAAPL0000E1Z4"),
        "customer": ["Narmada Valley School", "Hoshangabad Road", "Bhopal, Madhya Pradesh 462026"],
        "invoice_id": "LPH-1187", "date": ("2026-09-18", "18/09/2026"), "due": ("2026-09-25", "25/09/2026"),
        "items": [("Annual report printing, A4, 64 pages", "PR-A4-64", 300, "copies", 142.00, "12%"),
                  ("Lamination, cover", "LAM-C", 300, "copies", 8.00, "12%")],
        "tax": [("CGST 6%", 0.06, "6 %"), ("SGST 6%", 0.06, "6 %")],
        "low": {"InvoiceId": 0.62, "DueDate": 0.58, "VendorTaxId": 0.55},
        "png": {"scale": 100, "confidence_factor": 0.86, "rotate": 0.8, "scan": True},
        "pdf": False,
        "note": "E. & O. E.",
    },
    {
        "id": "inv-09-logo-brand", "title": "Brand logo differs from the typed company name", "size": A4,
        "currency": "INR", "symbol": "₹", "indian": True, "accent": "#9333ea", "style": "logo",
        "logo": {"text": "NOVAPRINT", "tagline": "print · pack · deliver"},
        "vendor": ["Shreeji Novaprint Solutions Pvt. Ltd.", "B-14, Okhla Industrial Area Phase II",
                   "New Delhi, Delhi 110020"],
        "vendor_tax": ("GSTIN", "07AAACS0000F1Z3"),
        "customer": ["Pinewood Organics LLP", "22 Residency Road", "Bengaluru, Karnataka 560025"],
        "customer_tax": ("GSTIN", "29AAAFP0000G1Z8"),
        "invoice_id": "SNS/26/0918", "date": ("2026-10-03", "03-10-2026"), "due": ("2026-11-02", "02-11-2026"),
        "po": "PWO-4471", "terms": "Net 30",
        "items": [("Printed cartons, 3-ply, 12 x 8 x 6 in", "CTN-1286", 2000, "pcs", 18.50, "18%"),
                  ("Product labels, matte, 2 x 3 in", "LBL-23", 5000, "pcs", 1.20, "18%"),
                  ("Plate making charges", "PLT-01", 1, "job", 3500.00, "18%")],
        "tax": [("IGST 18%", 0.18, "18 %")],
        "low": {"PurchaseOrder": 0.77},
        "png": None,
        "note": "The brand logo text differs from the legal name on purpose: see Data/sample_invoices/README.md.",
    },
]


def many_items(rng: random.Random):
    names = ["Hex bolt M8 x 40, zinc", "Hex nut M8, zinc", "Flat washer M8", "Spring washer M8", "Socket cap screw M6",
             "Cutting disc 4 inch", "Grinding wheel 7 inch", "Welding rod E6013 3.15 mm", "Safety gloves, nitrile",
             "Safety goggles, clear", "Ear plugs, foam (pair)", "Cable ties 300 mm (100)", "PTFE tape 12 mm",
             "Hose clamp 25-40 mm", "Bearing 6204 2RS", "Bearing 6205 2RS", "V-belt A-42", "Grease, lithium, 1 kg",
             "Hydraulic oil 68, 20 L", "Coolant concentrate, 5 L", "Drill bit HSS 6 mm", "Drill bit HSS 10 mm",
             "Tap set M6-M12", "Measuring tape 5 m", "Vernier caliper 150 mm", "Allen key set", "Spanner set 8-24",
             "Wire brush, steel", "Sandpaper roll 120 grit", "Masking tape 48 mm", "Spray paint, grey",
             "Anti-rust spray 400 ml", "Shop towels (pack)", "Floor marking tape", "LED tube light 20 W",
             "Extension board 6-way", "MCB 32 A", "Contactor 25 A", "Push button, red", "Limit switch",
             "Proximity sensor M18", "Terminal block 4 mm"]
    out = []
    for i, n in enumerate(names):
        qty = rng.choice([5, 10, 12, 20, 25, 40, 50, 100])
        price = round(rng.uniform(12, 950), 2)
        out.append((n, f"SIS-{1000 + i * 7}", qty, "nos", price, "18%"))
    return out


def draw_invoice(spec: dict, rng: random.Random) -> tuple[bytes, dict]:
    page_w, page_h = spec["size"]
    win, hin = page_w / 72, page_h / 72
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=spec["size"])
    c.setTitle(f"Invoice {spec['invoice_id']}")
    c.setAuthor(spec["vendor"][0])
    rec = Recorder(rng, spec.get("low", {}))
    cur, sym, ind = spec["currency"], spec["symbol"], spec.get("indian", False)
    dec = 2
    accent = spec["accent"]
    margin = 0.7
    right = win - margin
    pages = []

    def new_page(n):
        pg = Page(c, n, round(win, 4), round(hin, 4))
        pages.append({"width": round(win, 4), "height": round(hin, 4)})
        return pg

    def money(v):
        return fmt(v, dec, ind)

    p = new_page(1)
    # ---- header
    y = 0.95
    image_fields, figures = {}, []
    if spec["style"] == "logo":
        # A raster logo with the brand name, then the typed legal name. Document Intelligence reads text inside
        # images too, so with images included it may take the brand name as VendorName.
        logo_png, logo_size = render_logo(spec["logo"], spec["accent"])
        lw, lh = 2.4, 2.4 * logo_size[1] / logo_size[0]
        from reportlab.lib.utils import ImageReader

        c.drawImage(ImageReader(io.BytesIO(logo_png)), margin * 72, (hin - 0.4 - lh) * 72, lw * 72, lh * 72, mask="auto")
        logo_poly = [round(v, 4) for v in (margin, 0.4, margin + lw, 0.4, margin + lw, 0.4 + lh, margin, 0.4 + lh)]
        text_h = lh * 0.62  # the brand word fills the upper part of the logo
        brand_poly = [round(v, 4) for v in (margin + 0.08, 0.45, margin + lw - 0.08, 0.45, margin + lw - 0.08,
                                            0.4 + text_h, margin + 0.08, 0.4 + text_h)]
        image_fields["VendorName"] = {"type": "string", "value": spec["logo"]["text"].title(),
                                      "content": spec["logo"]["text"], "confidence": 0.74, "page": 1,
                                      "polygon": brand_poly}
        figures.append({"id": "1.1", "page": 1, "polygon": logo_poly, "caption": "",
                        "file": f"{spec['id']}.figure-1.1.png", "png": logo_png})
        p.text(right, 0.95, "TAX INVOICE" if ind else "INVOICE", 18, bold=True, color="#111827", align="right")
        poly = p.text(margin, 0.6 + lh, spec["vendor"][0], 11, bold=True, color="#111827")
        rec.put("VendorName", "string", spec["vendor"][0], spec["vendor"][0], poly, 1)
        y = 0.85 + lh
    elif spec["style"] == "band":
        p.rect(0, 0, win, 1.35, fill=accent)
        poly = p.text(margin, y, spec["vendor"][0], 15, bold=True, color="#ffffff")
        rec.put("VendorName", "string", spec["vendor"][0], spec["vendor"][0], poly, 1)
        p.text(right, y, "TAX INVOICE" if ind else "INVOICE", 18, bold=True, color="#ffffff", align="right")
        y = 1.75
    else:
        p.hline(margin, right, 0.55, color=accent, width=3)
        poly = p.text(margin, y, spec["vendor"][0], 15, bold=True, color=accent)
        rec.put("VendorName", "string", spec["vendor"][0], spec["vendor"][0], poly, 1)
        p.text(right, y, "TAX INVOICE" if ind else "INVOICE", 18, bold=True, color="#111827", align="right")
        y = 1.3
    addr = spec["vendor"][1:]
    poly = p.lines(margin, y, addr, 9, color="#374151")
    rec.put("VendorAddress", "address", _addr(addr), "\n".join(addr), poly, 1)
    y += 0.17 * len(addr) + 0.05
    label, number = spec["vendor_tax"]
    p.text(margin, y, f"{label}:", 9, bold=True)
    poly = p.text(margin + pdfmetrics.stringWidth(f"{label}: ", "Sans-Bold", 9) / 72, y, number, 9)
    rec.put("VendorTaxId", "string", number, number, poly, 1)

    # ---- invoice meta (right column)
    my = {"band": 1.75, "logo": 1.3}.get(spec["style"], 1.3)
    meta = [("Invoice no.", "InvoiceId", spec["invoice_id"]), ("Invoice date", "InvoiceDate", spec["date"]),
            ("Due date", "DueDate", spec["due"])]
    if spec.get("po"):
        meta.append(("PO number", "PurchaseOrder", spec["po"]))
    if spec.get("terms"):
        meta.append(("Terms", "PaymentTerm", spec["terms"]))
    if spec.get("customer_id"):
        meta.append(("Customer no.", "CustomerId", spec["customer_id"]))
    lx = right - 2.6
    for label, name, value in meta:
        p.text(lx, my, label, 9, color="#6b7280")
        shown = value[1] if isinstance(value, tuple) else value
        poly = p.text(right, my, shown, 9, bold=name == "InvoiceId", align="right")
        if isinstance(value, tuple):
            rec.put(name, "date", value[0], shown, poly, 1)
        else:
            rec.put(name, "string", value, shown, poly, 1)
        my += 0.2

    # ---- parties
    y = max(y + 0.55, my + 0.3)
    p.text(margin, y, "BILL TO", 8, bold=True, color=accent)
    cols = [("ShippingAddress", "SHIP TO", spec.get("shipping")), ("ServiceAddress", "SERVICE ADDRESS", spec.get("service")),
            ("RemittanceAddress", "REMIT TO", spec.get("remit"))]
    extra = next(((n, t, a) for n, t, a in cols if a), None)
    if extra:
        p.text(margin + 3.4, y, extra[1], 8, bold=True, color=accent)
    y += 0.22
    poly = p.text(margin, y, spec["customer"][0], 10, bold=True)
    rec.put("CustomerName", "string", spec["customer"][0], spec["customer"][0], poly, 1)
    caddr = spec["customer"][1:]
    poly = p.lines(margin, y + 0.18, caddr, 9, color="#374151")
    rec.put("CustomerAddress", "address", _addr(caddr), "\n".join(caddr), poly, 1)
    if extra:
        name, _, lines_ = extra
        poly = p.lines(margin + 3.4, y, lines_, 9, color="#374151")
        rec.put(name, "address", _addr(lines_[1:]), "\n".join(lines_), poly, 1)
        poly = p.measure(margin + 3.4, y, lines_[0], 9)
        rec.put(name + "Recipient", "string", lines_[0], lines_[0], poly, 1)
    y += 0.18 + 0.17 * len(caddr)
    if spec.get("customer_tax"):
        label, number = spec["customer_tax"]
        p.text(margin, y, f"{label}:", 9, bold=True)
        poly = p.text(margin + pdfmetrics.stringWidth(f"{label}: ", "Sans-Bold", 9) / 72, y, number, 9)
        rec.put("CustomerTaxId", "string", number, number, poly, 1)
        y += 0.2
    if spec.get("period"):
        (s_iso, s_txt), (e_iso, e_txt) = spec["period"]
        p.text(margin, y + 0.05, "Billing period:", 9, bold=True)
        x0 = margin + pdfmetrics.stringWidth("Billing period: ", "Sans-Bold", 9) / 72
        poly = p.text(x0, y + 0.05, s_txt, 9)
        rec.put("ServiceStartDate", "date", s_iso, s_txt, poly, 1)
        x1 = x0 + pdfmetrics.stringWidth(s_txt + " to ", "Sans", 9) / 72
        p.text(x0 + pdfmetrics.stringWidth(s_txt + " ", "Sans", 9) / 72, y + 0.05, "to", 9)
        poly = p.text(x1, y + 0.05, e_txt, 9)
        rec.put("ServiceEndDate", "date", e_iso, e_txt, poly, 1)
        y += 0.25

    # ---- line items
    items = many_items(rng) if spec["items"] == "many" else spec["items"]
    y += 0.35
    xcols = {"Description": margin + 0.08, "ProductCode": margin + 2.95, "Quantity": margin + 4.2,
             "UnitPrice": margin + 5.0, "TaxRate": margin + 5.55, "Amount": right - 0.08}
    has_rate = any(it[5] for it in items)

    def table_header(pg, yy):
        pg.rect(margin, yy - 0.17, right - margin, 0.27, fill="#f3f4f6")
        pg.text(xcols["Description"], yy, "Description", 8, bold=True, color="#374151")
        pg.text(xcols["ProductCode"], yy, "Code", 8, bold=True, color="#374151")
        pg.text(xcols["Quantity"], yy, "Qty", 8, bold=True, color="#374151", align="right")
        pg.text(xcols["UnitPrice"], yy, "Rate", 8, bold=True, color="#374151", align="right")
        if has_rate:
            pg.text(xcols["TaxRate"], yy, "Tax", 8, bold=True, color="#374151", align="right")
        pg.text(xcols["Amount"], yy, f"Amount ({cur})", 8, bold=True, color="#374151", align="right")
        return yy + 0.3

    y = table_header(p, y)
    rows = []
    subtotal = 0.0
    rate_split = {}
    for i, (desc, code, qty, unit, price, rate) in enumerate(items):
        if y > hin - 1.2:
            p.text(right, hin - 0.45, f"Continued on page {p.number + 1}", 8, color="#6b7280", align="right")
            c.showPage()
            p = new_page(p.number + 1)
            p.text(margin, 0.75, f"{spec['vendor'][0]}  ·  Invoice {spec['invoice_id']} (continued)", 9,
                   color="#6b7280")
            y = table_header(p, 1.15)
        amount = round(qty * price, 2)
        subtotal += amount
        rate_split[rate] = rate_split.get(rate, 0) + amount
        cells = {}
        poly = p.text(xcols["Description"], y, desc, 8.5)
        cells["Description"] = {"type": "string", "value": desc, "content": desc, "polygon": poly}
        poly = p.text(xcols["ProductCode"], y, code, 8.5, color="#4b5563")
        cells["ProductCode"] = {"type": "string", "value": code, "content": code, "polygon": poly}
        qty_txt = f"{qty:,} {unit}"
        poly = p.text(xcols["Quantity"], y, qty_txt, 8.5, align="right")
        cells["Quantity"] = {"type": "number", "value": float(qty), "content": f"{qty:,}", "polygon": poly}
        cells["Unit"] = {"type": "string", "value": unit, "content": unit, "polygon": poly}
        price_txt = fmt(price, 4 if price < 1 else dec, ind)
        poly = p.text(xcols["UnitPrice"], y, price_txt, 8.5, align="right")
        cells["UnitPrice"] = {"type": "currency", "value": {"amount": price, "currencyCode": cur},
                              "content": price_txt, "polygon": poly}
        if rate:
            poly = p.text(xcols["TaxRate"], y, rate, 8.5, align="right", color="#4b5563")
            cells["TaxRate"] = {"type": "string", "value": rate, "content": rate, "polygon": poly}
        amt_txt = money(amount)
        poly = p.text(xcols["Amount"], y, amt_txt, 8.5, align="right")
        cells["Amount"] = {"type": "currency", "value": {"amount": amount, "currencyCode": cur},
                           "content": amt_txt, "polygon": poly}
        row_conf = round(rng.uniform(0.86, 0.99), 3)
        for name, cell in cells.items():
            cell["page"] = p.number
            cell["confidence"] = round(min(0.995, row_conf + rng.uniform(-0.04, 0.03)), 3)
        if spec["id"] == "inv-05-multipage-supplies" and i in (17, 33):
            cells["UnitPrice"]["confidence"] = 0.64  # a couple of hard-to-read cells deep in the table
        rows.append({"confidence": row_conf, "page": p.number,
                     "polygon": union([cl["polygon"] for cl in cells.values()]), "fields": cells})
        p.hline(margin, right, y + 0.1, color="#e5e7eb")
        y += 0.27
    rec.fields["Items"] = {"type": "array", "rows": rows}

    # ---- totals
    if y > hin - 3.2:
        c.showPage()
        p = new_page(p.number + 1)
        y = 1.0
    y += 0.25
    tx = right - 2.8
    discount = round(subtotal * spec.get("discount", 0), 2)
    taxable = subtotal - discount
    tax_rows = []
    if spec["tax"] == "split":
        for rate, base in rate_split.items():
            pct = int(rate.rstrip("%"))
            tax_rows.append((f"VAT {pct}% on {money(base)}", round(base * pct / 100, 2), f"{pct} %"))
    else:
        for label, r, rate_txt in spec["tax"]:
            tax_rows.append((label, round(taxable * r, 2), rate_txt))
    total_tax = round(sum(t[1] for t in tax_rows), 2)
    total = round(taxable + total_tax, 2)
    previous = spec.get("previous")
    due_amount = round(total + (previous or 0), 2)

    def total_line(label, name, value, bold=False, size=9.5, kind="currency"):
        nonlocal y
        p.text(tx, y, label, size, bold=bold, color="#374151")
        shown = f"{sym}{money(value)}" if kind == "currency" else value
        poly = p.text(right, y, shown, size, bold=bold, align="right")
        if name:
            rec.put(name, "currency", {"amount": value, "currencyCode": cur, "currencySymbol": sym}, shown, poly,
                    p.number)
        y += 0.24
        return poly

    total_line("Subtotal", "SubTotal", subtotal)
    if discount:
        p.text(tx, y, f"Discount ({int(spec['discount'] * 100)}%)", 9.5, color="#374151")
        shown = f"-{sym}{money(discount)}"
        poly = p.text(right, y, shown, 9.5, align="right")
        rec.put("TotalDiscount", "currency", {"amount": discount, "currencyCode": cur, "currencySymbol": sym},
                shown, poly, p.number)
        y += 0.24
    tax_detail_rows = []
    for label, amount, rate_txt in tax_rows:
        p.text(tx, y, label, 9.5, color="#374151")
        shown = f"{sym}{money(amount)}"
        poly = p.text(right, y, shown, 9.5, align="right")
        conf = round(rng.uniform(0.86, 0.97), 3)
        tax_detail_rows.append({"confidence": conf, "page": p.number, "polygon": poly, "fields": {
            "Amount": {"type": "currency", "value": {"amount": amount, "currencyCode": cur, "currencySymbol": sym},
                       "content": shown, "confidence": conf, "page": p.number, "polygon": poly},
            "Rate": {"type": "string", "value": rate_txt, "content": rate_txt, "confidence": round(conf - 0.03, 3),
                     "page": p.number, "polygon": p.measure(tx, y, label, 9.5)}}})
        y += 0.24
    rec.fields["TaxDetails"] = {"type": "array", "rows": tax_detail_rows}
    p.text(tx, y, "Total tax", 9.5, color="#374151")
    shown = f"{sym}{money(total_tax)}"
    poly = p.text(right, y, shown, 9.5, align="right")
    rec.put("TotalTax", "currency", {"amount": total_tax, "currencyCode": cur, "currencySymbol": sym}, shown, poly,
            p.number)
    y += 0.3
    p.hline(tx, right, y - 0.14, color="#9ca3af")
    total_line("Invoice total", "InvoiceTotal", total, bold=True, size=10.5)
    if previous is not None:
        total_line("Previous balance", "PreviousUnpaidBalance", previous)
    p.rect(tx - 0.1, y - 0.2, right - tx + 0.18, 0.34, fill="#f3f4f6")
    total_line("Amount due", "AmountDue", due_amount, bold=True, size=11)

    # ---- payment details and notes
    y += 0.3
    if spec.get("payment"):
        p.text(margin, y, "PAYMENT DETAILS", 8, bold=True, color=accent)
        y += 0.22
        pay_fields = {}
        labels = {"IBAN": "IBAN", "SWIFT": "SWIFT/BIC", "BankAccountNumber": "Account no.",
                  "BPayBillerCode": "BPay biller code", "BPayReference": "BPay reference"}
        for key, value in spec["payment"].items():
            p.text(margin, y, labels[key], 9, color="#6b7280")
            poly = p.text(margin + 1.4, y, value, 9)
            pay_fields[key] = {"type": "string", "value": value, "content": value,
                               "confidence": round(rng.uniform(0.85, 0.97), 3), "page": p.number, "polygon": poly}
            y += 0.19
        rec.fields["PaymentDetails"] = {"type": "array", "rows": [{
            "confidence": 0.9, "page": p.number, "polygon": union([f["polygon"] for f in pay_fields.values()]),
            "fields": pay_fields}]}
        y += 0.15
    p.text(margin, max(y, hin - 0.9), spec["note"], 8, color="#6b7280")
    p.text(right, hin - 0.45, f"Page {p.number} of {p.number}", 8, color="#9ca3af", align="right")
    c.showPage()
    c.save()
    pdf = buf.getvalue()

    sidecar = {
        "id": spec["id"], "title": spec["title"], "model_id": "prebuilt-invoice",
        "description": f"{spec['vendor'][0]} to {spec['customer'][0]}, {cur}, {len(pages)} page(s), "
                       f"{len(rows)} line item(s). Invented data.",
        "pages": pages, "fields": rec.fields,
    }
    if image_fields:
        sidecar["image_text_fields"] = image_fields
    if figures:
        sidecar["figures"] = figures
    return pdf, sidecar


def _addr(lines: list[str]) -> dict:
    """Rough AddressValue parts for a printed address (street, city, postal code)."""
    import re

    out = {"streetAddress": lines[0]} if lines else {}
    for ln in lines[1:]:
        m = re.search(r"\b(\d{3}\s?\d{3}|\d{5}|[A-Z]{1,2}\d{1,2}\s?\d[A-Z]{2}|\d{4})\b", ln)
        if m:
            out["postalCode"] = m[1]
            city = re.sub(r"[\s,]*" + re.escape(m[1]) + r"[\s,]*", " ", ln).strip(" ,")
            if city:
                out["city"] = city.split(",")[0].strip()
                if "," in city:
                    out["state"] = city.split(",")[-1].strip()
        elif ln in ("India", "Germany", "United Kingdom"):
            out["countryRegion"] = {"India": "IND", "Germany": "DEU", "United Kingdom": "GBR"}[ln]
    return out


def render_logo(logo: dict, accent: str) -> tuple[bytes, tuple[int, int]]:
    """A raster brand logo (PNG): a coloured mark, the brand word and a tagline."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = 880, 230
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    big = ImageFont.truetype(str(FONT_DIR / "DejaVuSans-Bold.ttf"), 108)
    small = ImageFont.truetype(str(FONT_DIR / "DejaVuSans.ttf"), 38)
    d.rounded_rectangle((8, 20, 118, 130), radius=26, fill=accent)
    d.ellipse((38, 50, 88, 100), fill="white")
    d.text((140, 6), logo["text"], font=big, fill=accent)
    d.text((146, 158), logo["tagline"], font=small, fill="#6b7280")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue(), (w, h)


ID_CARDS = [
    {
        "id": "id-01-specimen-card", "title": "Identity card with a photo (specimen)",
        "first": "ANANYA", "last": "RAO", "number": "SPC4417920", "dob": ("1991-04-17", "17/04/1991"),
        "issue": ("2022-08-01", "01/08/2022"), "expiry": ("2032-07-31", "31/07/2032"), "sex": "F",
        "country": "IND", "place": "PUNE",
        "low": {"DateOfIssue": 0.69},
    },
]


def draw_id_card(spec: dict, rng: random.Random) -> tuple[bytes, dict, bytes]:
    """A credit-card-sized specimen identity card (PDF for rendering), its sidecar, and the cropped photo (PNG)."""
    w, h = 3.375, 2.125
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w * 72, h * 72))
    c.setTitle("Specimen identity card")
    p = Page(c, 1, w, h)
    rec = Recorder(rng, spec.get("low", {}))
    p.rect(0, 0, w, h, fill="#eef4fb")
    p.rect(0, 0, w, 0.36, fill="#1e3a8a")
    p.text(0.14, 0.24, "IDENTITY CARD", 10, bold=True, color="#ffffff")
    p.text(w - 0.14, 0.24, "SPECIMEN", 8, bold=True, color="#fde68a", align="right")
    # photo: a drawn silhouette (an invented person)
    px, py, pw, ph = 0.14, 0.5, 0.95, 1.2
    p.rect(px, py, pw, ph, fill="#cbd5e1", stroke="#94a3b8")
    c.setFillColor(HexColor("#64748b"))
    c.circle((px + pw / 2) * 72, (h - py - 0.42) * 72, 0.22 * 72, fill=1, stroke=0)
    c.ellipse((px + 0.12) * 72, (h - py - ph) * 72, (px + pw - 0.12) * 72, (h - py - 0.72) * 72, fill=1, stroke=0)
    photo_poly = [round(v, 4) for v in (px, py, px + pw, py, px + pw, py + ph, px, py + ph)]
    x0, x1 = 1.24, 2.3
    rows = [
        ("Surname", "LastName", spec["last"], x0, 0.62), ("Given name", "FirstName", spec["first"], x0, 0.92),
        ("Card no.", "DocumentNumber", spec["number"], x0, 1.22), ("Sex", "Sex", spec["sex"], x1, 1.22),
        ("Date of birth", "DateOfBirth", spec["dob"], x0, 1.52), ("Place of birth", "PlaceOfBirth", spec["place"], x1, 1.52),
        ("Date of issue", "DateOfIssue", spec["issue"], x0, 1.82), ("Date of expiry", "DateOfExpiration", spec["expiry"], x1, 1.82),
    ]
    for label, name, value, x, y in rows:
        p.text(x, y - 0.11, label, 5, color="#475569")
        shown = value[1] if isinstance(value, tuple) else value
        poly = p.text(x, y + 0.02, shown, 7.5, bold=True, color="#0f172a")
        if isinstance(value, tuple):
            rec.put(name, "date", value[0], shown, poly, 1)
        else:
            rec.put(name, "string", value, shown, poly, 1)
    poly = p.text(w - 0.14, 0.62, spec["country"], 7.5, bold=True, color="#0f172a", align="right")
    rec.put("CountryRegion", "countryRegion", spec["country"], spec["country"], poly, 1)
    p.text(w - 0.14, 2.04, "Invented data · not a real document", 4.5, color="#64748b", align="right")
    c.showPage()
    c.save()
    pdf = buf.getvalue()
    sidecar = {"id": spec["id"], "title": spec["title"], "model_id": "prebuilt-idDocument",
               "description": "Specimen identity card with an invented person and a drawn photo. Invented data.",
               "pages": [{"width": w, "height": h}], "fields": rec.fields,
               "figures": [{"id": "1.1", "page": 1, "polygon": photo_poly, "caption": "",
                            "file": f"{spec['id']}.figure-1.1.png"}]}
    return pdf, sidecar, photo_poly


def crop_png(png: bytes, polygon: list[float], scale: float) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    xs, ys = polygon[0::2], polygon[1::2]
    box = tuple(round(v * scale) for v in (min(xs), min(ys), max(xs), max(ys)))
    out = io.BytesIO()
    img.crop(box).save(out, "PNG", optimize=True)
    return out.getvalue()


def render_png(pdf: bytes, opts: dict) -> bytes:
    import pymupdf as fitz
    from PIL import Image, ImageFilter

    doc = fitz.open(stream=pdf, filetype="pdf")
    pix = doc[0].get_pixmap(dpi=opts["scale"], alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    if opts.get("scan"):
        rng = random.Random(8)
        img = img.convert("L")
        img = img.point(lambda v: int(40 + v * 0.78))  # lower contrast, grey paper
        img = img.rotate(opts.get("rotate", 0.0), resample=Image.Resampling.BICUBIC, fillcolor=238)
        img = img.filter(ImageFilter.GaussianBlur(0.7))
        noise = Image.effect_noise(img.size, 22).filter(ImageFilter.GaussianBlur(0.4))
        img = Image.blend(img, noise, 0.12)
        for _ in range(140):  # specks
            x, y = rng.randrange(img.width), rng.randrange(img.height)
            img.putpixel((x, y), rng.randrange(60, 140))
        jpeg = io.BytesIO()
        img.save(jpeg, "JPEG", quality=30)
        img = Image.open(io.BytesIO(jpeg.getvalue())).convert("L")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def main(only: set[str] | None = None) -> None:
    """Writes every sample, or only those named on the command line (other files are left untouched)."""
    def wanted(sample_id):
        return not only or sample_id in only

    for n, spec in enumerate(INVOICES):
        if not wanted(spec["id"]):
            continue
        for old in OUT.glob(f"{spec['id']}.*"):
            old.unlink()
        rng = random.Random(1000 + n)
        pdf, sidecar = draw_invoice(spec, rng)
        variants = {}
        if spec.get("pdf", True):
            (OUT / f"{spec['id']}.pdf").write_bytes(pdf)
            variants["pdf"] = {"file": f"{spec['id']}.pdf", "sha256": hashlib.sha256(pdf).hexdigest(),
                               "unit": "inch", "confidence_factor": 1.0}
        if spec.get("png"):
            png = render_png(pdf, spec["png"])
            (OUT / f"{spec['id']}.png").write_bytes(png)
            variants["png"] = {"file": f"{spec['id']}.png", "sha256": hashlib.sha256(png).hexdigest(),
                               "unit": "pixel", "scale": spec["png"]["scale"], "pages": [1],
                               "rotate": spec["png"].get("rotate", 0.0),
                               "confidence_factor": spec["png"]["confidence_factor"]}
        for fig in sidecar.get("figures", []):
            (OUT / fig["file"]).write_bytes(fig.pop("png"))
        sidecar["variants"] = variants
        (OUT / f"{spec['id']}.json").write_text(json.dumps(sidecar, indent=1, ensure_ascii=False) + "\n")
        print(f"{spec['id']}: {', '.join(variants)}, {len(sidecar['pages'])} page(s)")

    for n, spec in enumerate(ID_CARDS):
        if not wanted(spec["id"]):
            continue
        for old in OUT.glob(f"{spec['id']}.*"):
            old.unlink()
        pdf, sidecar, photo = draw_id_card(spec, random.Random(2000 + n))
        scale = 300
        png = render_png(pdf, {"scale": scale})
        (OUT / f"{spec['id']}.png").write_bytes(png)
        (OUT / sidecar["figures"][0]["file"]).write_bytes(crop_png(png, photo, scale))
        sidecar["variants"] = {"png": {"file": f"{spec['id']}.png", "sha256": hashlib.sha256(png).hexdigest(),
                                       "unit": "pixel", "scale": scale, "pages": [1], "rotate": 0.0,
                                       "confidence_factor": 1.0}}
        (OUT / f"{spec['id']}.json").write_text(json.dumps(sidecar, indent=1, ensure_ascii=False) + "\n")
        print(f"{spec['id']}: png, 1 page")


if __name__ == "__main__":
    import sys

    main(set(sys.argv[1:]) or None)
