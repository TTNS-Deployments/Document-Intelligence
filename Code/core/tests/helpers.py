import io
import struct
import zlib


def make_pdf(pages=1, text=None, encrypt=False) -> bytes:
    """A real PDF (pypdf), optionally with a text layer."""
    from pypdf import PdfWriter

    if text is None:
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=612, height=792)
    else:
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(612, 792))
        for _ in range(pages):
            y = 740
            for line in text.splitlines():
                c.drawString(72, y, line)
                y -= 16
            c.showPage()
        c.save()
        from pypdf import PdfReader

        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    if encrypt:
        writer.encrypt("secret")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_png(width=200, height=100) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_jpeg(width=300, height=200) -> bytes:
    # SOI, APP0 (JFIF), SOF0 with the dimensions, EOI: enough for the header checks.
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"
