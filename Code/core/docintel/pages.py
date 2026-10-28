"""Upload checks done **before** any call to Azure, and the daily page budget.

Checks: extension, magic bytes (the content must match the extension), size, image dimensions, and for PDFs the
page count and encryption. File names are sanitised.
"""

from __future__ import annotations

import hashlib
import io
import re
import struct
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import get_settings
from .factory import get_blob_store
from .storage import PreconditionFailed

EXTENSIONS = {".pdf": "pdf", ".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png"}
CONTENT_TYPES = {"pdf": "application/pdf", "jpeg": "image/jpeg", "png": "image/png"}
# Document Intelligence (v4.0) accepts images from 50 x 50 to 10,000 x 10,000 pixels.
MIN_IMAGE_PX, MAX_IMAGE_PX = 50, 10_000


class UploadRejected(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class BudgetExceeded(Exception):
    def __init__(self, used: int, limit: int, wanted: int):
        self.used, self.limit, self.wanted = used, limit, wanted
        left = max(0, limit - used)
        super().__init__(f"The daily page limit is reached ({used} of {limit} pages used today; this needs {wanted}, "
                         f"{left} left). Try again tomorrow or ask an Admin to raise the limit.")


@dataclass(frozen=True)
class InspectedFile:
    filename: str
    kind: str
    content_type: str
    size: int
    pages: int
    sha256: str


def sanitize_filename(name: str) -> str:
    """A safe display and blob name: no path, no control characters, only a small set of punctuation."""
    name = unicodedata.normalize("NFKC", name or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = re.sub(r"[^\w\-. ()]+", "_", stem)
    stem = re.sub(r"[_ ]{2,}", "_", stem).strip(" ._") or "document"
    ext = re.sub(r"[^a-z0-9]", "", ext.lower())[:5]
    return f"{stem[:100]}.{ext}" if ext else stem[:100]


def detect_kind(data: bytes) -> str | None:
    if data.startswith(b"%PDF-") or (len(data) > 1024 and b"%PDF-" in data[:1024]):
        return "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def image_size(data: bytes, kind: str) -> tuple[int, int] | None:
    """Width and height from the PNG header or the JPEG frame header, without an image library."""
    try:
        if kind == "png" and data[12:16] == b"IHDR":
            return struct.unpack(">II", data[16:24])
        if kind == "jpeg":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                length = struct.unpack(">H", data[i + 2:i + 4])[0]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + length
    except struct.error:
        return None
    return None


def count_pdf_pages(data: bytes) -> int:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UploadRejected("encrypted", "The PDF is password-protected. Remove the password and upload it again.")
        return len(reader.pages)
    except UploadRejected:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError, IndexError) as exc:
        raise UploadRejected("corrupt", "The PDF could not be read. It may be damaged.") from exc


def inspect_upload(filename: str, data: bytes, *, max_mb: int, max_pages: int) -> InspectedFile:
    safe = sanitize_filename(filename)
    ext = "." + safe.rpartition(".")[2] if "." in safe else ""
    if ext not in EXTENSIONS:
        raise UploadRejected("type", f"{safe}: only PDF, JPEG and PNG files are accepted.")
    if not data:
        raise UploadRejected("empty", f"{safe}: the file is empty.")
    if len(data) > max_mb * 1024 * 1024:
        raise UploadRejected("size", f"{safe}: the file is {len(data) / 1048576:.1f} MB; the limit is {max_mb} MB.")
    kind = detect_kind(data)
    if kind != EXTENSIONS[ext]:
        found = {"pdf": "a PDF", "jpeg": "a JPEG image", "png": "a PNG image"}.get(kind, "not a PDF, JPEG or PNG")
        raise UploadRejected("content", f"{safe}: the content does not match the file type (it is {found}).")
    if kind == "pdf":
        pages = count_pdf_pages(data)
        if pages < 1:
            raise UploadRejected("corrupt", f"{safe}: the PDF has no pages.")
        if pages > max_pages:
            raise UploadRejected("pages", f"{safe}: the PDF has {pages} pages; the limit is {max_pages} per file.")
    else:
        pages = 1
        size = image_size(data, kind)
        if size is None:
            raise UploadRejected("corrupt", f"{safe}: the image could not be read.")
        w, h = size
        if min(w, h) < MIN_IMAGE_PX or max(w, h) > MAX_IMAGE_PX:
            raise UploadRejected("dimensions", f"{safe}: the image is {w} x {h} pixels; it must be between "
                                               f"{MIN_IMAGE_PX} and {MAX_IMAGE_PX:,} pixels on each side.")
    return InspectedFile(filename=safe, kind=kind, content_type=CONTENT_TYPES[kind], size=len(data), pages=pages,
                         sha256=hashlib.sha256(data).hexdigest())


# --------------------------------------------------------------------------------------------- daily budget

def _today() -> str:
    return datetime.now(ZoneInfo(get_settings().display_time_zone)).date().isoformat()


def _usage_blob(day: str) -> str:
    return f"usage/{day}.json"


def budget_usage(limit: int) -> dict:
    s = get_settings()
    day = _today()
    data = get_blob_store().get_json_or_none(s.container_config, _usage_blob(day)) or {}
    used = int(data.get("pages", 0))
    return {"date": day, "used": used, "limit": limit, "left": max(0, limit - used)}


def reserve_pages(pages: int, limit: int) -> dict:
    """Count ``pages`` against today's budget, atomically (optimistic concurrency on the usage blob's ETag).

    Raises BudgetExceeded and counts nothing when the pages do not fit.
    """
    s = get_settings()
    store = get_blob_store()
    name = _usage_blob(_today())
    for _ in range(20):
        try:
            data, etag = store.get_json_with_etag(s.container_config, name)
        except FileNotFoundError:
            data, etag = {"pages": 0, "jobs": 0}, None
        used = int(data.get("pages", 0))
        if used + pages > limit:
            raise BudgetExceeded(used, limit, pages)
        data = {"pages": used + pages, "jobs": int(data.get("jobs", 0)) + 1}
        try:
            if etag is None:
                store.put_json(s.container_config, name, data, if_none_match=True)
            else:
                store.put_json(s.container_config, name, data, if_match=etag)
            return {"used": used + pages, "limit": limit}
        except PreconditionFailed:
            continue  # someone else counted pages at the same time: read again
    raise RuntimeError("Could not update the page budget (too many concurrent uploads); try again")


# --------------------------------------------------------------------------------------------- text-only mode

def strip_pdf_images(data: bytes) -> tuple[bytes, dict]:
    """A copy of a PDF without its embedded pictures (logos, stamps, photos), so only typed text is analysed.

    Pages with no text layer are scans: the page *is* a picture, so they are kept unchanged (and reported).
    Returns the new PDF and ``{"images_removed", "text_pages", "scanned_pages"}``.
    """
    from pypdf import ObjectDeletionFlag, PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter(clone_from=reader)
    removed, text_pages, scanned_pages = 0, [], []
    for number, page in enumerate(writer.pages, start=1):
        try:
            has_text = bool((page.extract_text() or "").strip())
        except Exception:  # noqa: BLE001 - unreadable text layer: treat the page as a scan
            has_text = False
        if not has_text:
            scanned_pages.append(number)
            continue
        text_pages.append(number)
        try:
            count = len(page.images)
        except Exception:  # noqa: BLE001 - odd image data: still try to remove it
            count = 0
        if count:
            writer.remove_objects_from_page(page, [ObjectDeletionFlag.XOBJECT_IMAGES, ObjectDeletionFlag.INLINE_IMAGES])
            removed += count
    if not removed:
        return data, {"images_removed": 0, "text_pages": text_pages, "scanned_pages": scanned_pages}
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), {"images_removed": removed, "text_pages": text_pages, "scanned_pages": scanned_pages}
