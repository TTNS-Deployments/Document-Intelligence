"""Takes the README screenshots from local mode (mock Document Intelligence, sample invoices).

    .venv/bin/python qa/take_screenshots.py

Writes imgs/screenshot-extract.png (the review view of a sample invoice with highlights and the field table) and
imgs/screenshot-history.png. Starts its own web app on a free port with an empty data folder.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qa/tests"))

from conftest import PASSWORD  # noqa: E402


def wait_for_review(page, sample_id):
    page.wait_for_selector(f'[data-review]:has(.ss-name:text-matches("^{sample_id}\\.")) [data-page-wrap][data-rendered]')


def main():
    import conftest
    from playwright.sync_api import sync_playwright

    server_gen = conftest.server.__wrapped__()
    url = next(server_gen)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 1080}, device_scale_factor=1.5, base_url=url,
                                      color_scheme="light", bypass_csp=True)  # for page.evaluate
            page = ctx.new_page()
            page.goto("/auth/login")
            page.check("input[name=role][value=Admin]")
            page.fill("#password", PASSWORD)
            page.click("button[type=submit]")
            page.wait_for_url("**/")

            for sample in ("inv-02-us-logistics", "inv-03-uk-interiors", "inv-04-eu-energy", "inv-08-scanned-print",
                           "inv-06-au-consulting"):
                page.select_option("#sample-select", sample)
                page.click("#run-sample")
                wait_for_review(page, sample)
            page.select_option("#preset-select", label="Full invoice with line items")
            page.select_option("#sample-select", "inv-01-gst-software")
            page.click("#run-sample")
            wait_for_review(page, "inv-01-gst-software")
            review = page.locator("#step-3")
            review.scroll_into_view_if_needed()
            page.evaluate("document.querySelector('[data-stage]').scrollTop = 0")
            page.evaluate("window.scrollBy(0, document.querySelector('#step-3').getBoundingClientRect().top - 72)")
            page.wait_for_timeout(300)
            page.hover('tr.field-row[data-path="PurchaseOrder"]')  # shows the linked highlight on the page
            page.wait_for_timeout(500)
            box = review.bounding_box()  # viewport coordinates; the review now starts at the top of the viewport
            page.screenshot(path=str(ROOT / "imgs/screenshot-extract.png"),
                            clip={"x": box["x"] - 8, "y": box["y"] - 8, "width": box["width"] + 16, "height": 880})

            page.goto("/history")
            page.locator("tbody tr").first.wait_for()
            page.screenshot(path=str(ROOT / "imgs/screenshot-history.png"), clip={"x": 0, "y": 0, "width": 1440, "height": 760})
            browser.close()
    finally:
        try:
            next(server_gen)
        except StopIteration:
            pass
    print("Wrote imgs/screenshot-extract.png and imgs/screenshot-history.png")


if __name__ == "__main__":
    main()
