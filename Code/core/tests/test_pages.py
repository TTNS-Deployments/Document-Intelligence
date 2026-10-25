import threading

import pytest

from docintel.pages import (BudgetExceeded, UploadRejected, budget_usage, detect_kind, image_size, inspect_upload,
                            reserve_pages, sanitize_filename)
from helpers import make_jpeg, make_pdf, make_png


def check(name, data, max_mb=10, max_pages=10):
    return inspect_upload(name, data, max_mb=max_mb, max_pages=max_pages)


@pytest.mark.parametrize("raw,expected", [
    ("invoice.pdf", "invoice.pdf"),
    ("../../etc/passwd.pdf", "passwd.pdf"),
    ("C:\\Users\\me\\Scan 01.PDF", "Scan 01.pdf"),
    ("bad<>:|?*name.png", "bad_name.png"),
    ("\u202einvoice\x00.jpg", "invoice.jpg"),
    ("....pdf", "document.pdf"),
    ("rechnung-ü.pdf", "rechnung-ü.pdf"),
    ("in\tvoice?.pdf", "invoice.pdf"),
    ("a" * 300 + ".pdf", "a" * 100 + ".pdf"),
])
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_accepts_pdf_png_jpeg():
    assert check("a.pdf", make_pdf(3)).pages == 3
    png = check("b.png", make_png())
    assert png.kind == "png" and png.pages == 1 and png.content_type == "image/png"
    assert check("c.JPEG", make_jpeg()).kind == "jpeg"
    assert len(check("a.pdf", make_pdf()).sha256) == 64


def test_rejects_wrong_extension():
    with pytest.raises(UploadRejected) as e:
        check("notes.txt", b"hello")
    assert e.value.code == "type"
    with pytest.raises(UploadRejected):
        check("noextension", make_pdf())


def test_rejects_wrong_magic_bytes():
    with pytest.raises(UploadRejected) as e:
        check("invoice.pdf", make_png())
    assert e.value.code == "content" and "PNG" in e.value.message
    with pytest.raises(UploadRejected) as e:
        check("photo.png", b"GIF89a" + b"\x00" * 100)
    assert e.value.code == "content"


def test_rejects_empty_large_and_too_many_pages():
    with pytest.raises(UploadRejected) as e:
        check("a.pdf", b"")
    assert e.value.code == "empty"
    with pytest.raises(UploadRejected) as e:
        check("a.pdf", make_pdf() + b"0" * (1024 * 1024), max_mb=1)
    assert e.value.code == "size"
    with pytest.raises(UploadRejected) as e:
        check("a.pdf", make_pdf(11))
    assert e.value.code == "pages" and "11 pages" in e.value.message


def test_rejects_encrypted_and_corrupt_pdf():
    with pytest.raises(UploadRejected) as e:
        check("a.pdf", make_pdf(encrypt=True))
    assert e.value.code == "encrypted"
    with pytest.raises(UploadRejected) as e:
        check("a.pdf", b"%PDF-1.7\n garbage")
    assert e.value.code == "corrupt"


def test_image_dimensions():
    assert image_size(make_png(640, 480), "png") == (640, 480)
    assert image_size(make_jpeg(1024, 768), "jpeg") == (1024, 768)
    with pytest.raises(UploadRejected) as e:
        check("tiny.png", make_png(20, 20))
    assert e.value.code == "dimensions"
    assert detect_kind(b"plain text") is None


def test_daily_budget_counts_and_refuses():
    reserve_pages(150, 200)
    assert budget_usage(200)["used"] == 150
    with pytest.raises(BudgetExceeded) as e:
        reserve_pages(60, 200)
    assert "daily page limit" in str(e.value) and "50 left" in str(e.value)
    assert budget_usage(200)["used"] == 150  # a refused request counts nothing
    reserve_pages(50, 200)
    assert budget_usage(200)["left"] == 0


def test_daily_budget_is_safe_under_concurrency():
    accepted, refused = [], []

    def worker():
        try:
            reserve_pages(3, 60)
            accepted.append(1)
        except BudgetExceeded:
            refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(accepted) == 20 and len(refused) == 10
    assert budget_usage(60)["used"] == 60
