/* Review view: document preview (pdf.js for PDFs, <img> for images) with highlight boxes, linked to the field table.

   Boxes are drawn in an SVG whose viewBox is the page size reported by Document Intelligence (inches for PDFs,
   pixels for images), laid exactly over the rendered page. So a polygon from the result is drawn as-is and the
   browser does the unit conversion: x_px = x / page.width * rendered_width (same for y). */

const meta = (name) => document.querySelector(`meta[name="${name}"]`)?.content;
let pdfjsPromise = null;

function loadPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import(meta("docintel-pdfjs")).then((lib) => {
      lib.GlobalWorkerOptions.workerSrc = meta("docintel-pdfjs-worker");
      return lib;
    });
  }
  return pdfjsPromise;
}

const SVG_NS = "http://www.w3.org/2000/svg";
const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3];

class Viewer {
  constructor(root) {
    this.root = root;
    this.id = root.dataset.review;
    this.section = root.querySelector("[data-viewer]");
    this.config = JSON.parse(this.section.dataset.config);
    this.stage = root.querySelector("[data-stage]");
    this.wrap = root.querySelector("[data-page-wrap]");
    this.page = 1;
    this.zoomIndex = ZOOMS.indexOf(1);
    this.pageCount = Math.max(1, this.config.pages.length);
    this.selected = null;
    this.bindToolbar();
    this.bindFields();
    this.load();
  }

  /* ------------------------------------------------------------ loading and rendering */
  async load() {
    try {
      if (this.config.kind === "pdf") {
        const lib = await loadPdfjs();
        this.pdf = await lib.getDocument({
          url: this.config.file_url, withCredentials: true, isEvalSupported: false,
          standardFontDataUrl: meta("docintel-pdfjs-fonts"),
        }).promise;
        this.pageCount = this.pdf.numPages;
      } else {
        this.img = new Image();
        this.img.alt = "";
        this.img.decoding = "async";
        await new Promise((resolve, reject) => {
          this.img.onload = resolve;
          this.img.onerror = () => reject(new Error("image"));
          this.img.src = this.config.file_url;
        });
      }
      this.root.querySelector("[data-page-count]").textContent = this.pageCount;
      await this.render();
      new ResizeObserver(() => this.onResize()).observe(this.stage);
    } catch (err) {
      this.wrap.innerHTML = '<div class="viewer-loading">The preview could not be loaded. The fields on the right are still correct.</div>';
    }
  }

  onResize() {
    const w = this.stage.clientWidth;
    if (this.lastWidth && Math.abs(w - this.lastWidth) > 24) this.render();
  }

  baseWidth() {
    return Math.max(200, this.stage.clientWidth - 32);
  }

  async render() {
    this.lastWidth = this.stage.clientWidth;
    const zoom = ZOOMS[this.zoomIndex];
    const width = this.baseWidth() * zoom;
    const token = (this.renderToken = Symbol("render"));
    let canvasOrImg;
    let aspect;
    if (this.pdf) {
      const page = await this.pdf.getPage(this.page);
      if (token !== this.renderToken) return;
      const unscaled = page.getViewport({ scale: 1 });
      const scale = width / unscaled.width;
      const viewport = page.getViewport({ scale });
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const canvas = document.createElement("canvas");
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.setAttribute("aria-hidden", "true");
      await page.render({ canvasContext: canvas.getContext("2d"), viewport,
                          transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null }).promise;
      if (token !== this.renderToken) return;
      canvasOrImg = canvas;
      aspect = viewport.height / viewport.width;
    } else {
      canvasOrImg = this.img;
      aspect = this.img.naturalHeight / this.img.naturalWidth;
    }
    this.wrap.innerHTML = "";
    this.wrap.style.width = `${Math.round(width)}px`;
    this.wrap.style.height = `${Math.round(width * aspect)}px`;
    this.wrap.appendChild(canvasOrImg);
    this.overlay = document.createElementNS(SVG_NS, "svg");
    this.overlay.classList.add("overlay");
    if (this.root.querySelector("[data-show-all]").checked) this.overlay.classList.add("show-all");
    this.overlay.setAttribute("preserveAspectRatio", "none");
    this.overlay.setAttribute("role", "presentation");
    this.overlay.dataset.page = this.page;
    this.wrap.appendChild(this.overlay);
    this.root.querySelector("[data-page-num]").textContent = this.page;
    this.root.querySelector("[data-zoom-level]").textContent = `${Math.round(zoom * 100)}%`;
    this.drawBoxes();
    this.wrap.dataset.rendered = "1";
  }

  /* ------------------------------------------------------------ boxes */
  pageSize(n) {
    const p = this.config.pages.find((x) => x.number === n);
    return p ? { w: p.width, h: p.height } : null;
  }

  regionsOf(el) {
    try { return JSON.parse(el.dataset.regions || "[]"); } catch (e) { return []; }
  }

  drawBoxes() {
    if (!this.overlay) return;
    const size = this.pageSize(this.page);
    this.overlay.innerHTML = "";
    if (!size) return;
    this.overlay.setAttribute("viewBox", `0 0 ${size.w} ${size.h}`);
    this.root.querySelectorAll(".fields-panel [data-regions]").forEach((el) => {
      for (const r of this.regionsOf(el)) {
        if (r.page !== this.page || !r.polygon || r.polygon.length < 6) continue;
        const poly = document.createElementNS(SVG_NS, "polygon");
        const pts = [];
        for (let i = 0; i + 1 < r.polygon.length; i += 2) pts.push(`${r.polygon[i]},${r.polygon[i + 1]}`);
        poly.setAttribute("points", pts.join(" "));
        poly.dataset.path = el.dataset.path;
        if (el.tagName === "TR" && !el.classList.contains("field-row")) poly.classList.add("is-row");
        if (el.classList.contains("picture")) poly.classList.add("is-picture");
        if (el.classList.contains("is-review")) poly.classList.add("is-review");
        const title = document.createElementNS(SVG_NS, "title");
        title.textContent = el.dataset.label || el.dataset.path;
        poly.appendChild(title);
        this.overlay.appendChild(poly);
      }
    });
    if (this.selected) this.highlight(this.selected, { scroll: false, keep: true });
  }

  async highlight(path, { scroll = true, keep = false } = {}) {
    const el = this.fieldEl(path);
    if (!el) return;
    const regions = this.regionsOf(el);
    if (regions.length && !regions.some((r) => r.page === this.page)) {
      this.page = regions[0].page;
      await this.render();
    }
    this.root.querySelectorAll(".is-active").forEach((x) => {
      if (!keep || x.dataset.path !== path) x.classList.remove("is-active");
    });
    el.classList.add("is-active");
    const polys = this.overlay ? this.overlay.querySelectorAll(`polygon[data-path="${CSS.escape(path)}"]`) : [];
    polys.forEach((p) => p.classList.add("is-active"));
    if (scroll && polys.length) this.scrollToBox(polys[0]);
  }

  clearHighlight() {
    this.root.querySelectorAll(".is-active").forEach((x) => x.classList.remove("is-active"));
    if (this.selected) this.highlight(this.selected, { scroll: false });
  }

  scrollToBox(poly) {
    const box = poly.getBoundingClientRect();
    const stage = this.stage.getBoundingClientRect();
    const margin = 48;
    let dy = 0;
    let dx = 0;
    if (box.top < stage.top + margin) dy = box.top - stage.top - margin;
    else if (box.bottom > stage.bottom - margin) dy = box.bottom - stage.bottom + margin;
    if (box.left < stage.left + margin) dx = box.left - stage.left - margin;
    else if (box.right > stage.right - margin) dx = box.right - stage.right + margin;
    if (dx || dy) {
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.stage.scrollBy({ top: dy, left: dx, behavior: smooth ? "smooth" : "auto" });
    }
  }

  fieldEl(path) {
    return this.root.querySelector(`.fields-panel [data-path="${CSS.escape(path)}"]`);
  }

  select(path) {
    this.selected = path;
    this.highlight(path);
  }

  /* ------------------------------------------------------------ events */
  bindToolbar() {
    const q = (s) => this.root.querySelector(s);
    q("[data-page-prev]").addEventListener("click", () => this.goTo(this.page - 1));
    q("[data-page-next]").addEventListener("click", () => this.goTo(this.page + 1));
    q("[data-zoom-in]").addEventListener("click", () => this.zoom(1));
    q("[data-zoom-out]").addEventListener("click", () => this.zoom(-1));
    q("[data-zoom-fit]").addEventListener("click", () => { this.zoomIndex = ZOOMS.indexOf(1); this.render(); });
    q("[data-show-all]").addEventListener("change", (e) => this.overlay?.classList.toggle("show-all", e.target.checked));
    this.stage.addEventListener("keydown", (e) => {
      if (e.key === "PageDown" || (e.key === "ArrowRight" && e.altKey)) { e.preventDefault(); this.goTo(this.page + 1); }
      if (e.key === "PageUp" || (e.key === "ArrowLeft" && e.altKey)) { e.preventDefault(); this.goTo(this.page - 1); }
      if (e.key === "+" || e.key === "=") this.zoom(1);
      if (e.key === "-") this.zoom(-1);
    });
    this.wrap.addEventListener("click", (e) => {
      const poly = e.target.closest("polygon");
      if (!poly) return;
      const el = this.fieldEl(poly.dataset.path);
      this.select(poly.dataset.path);
      if (el) {
        el.scrollIntoView({ block: "nearest", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        el.focus({ preventScroll: true });
      }
    });
  }

  goTo(n) {
    if (n < 1 || n > this.pageCount || n === this.page) return;
    this.page = n;
    this.render();
  }

  zoom(step) {
    const next = Math.min(ZOOMS.length - 1, Math.max(0, this.zoomIndex + step));
    if (next !== this.zoomIndex) { this.zoomIndex = next; this.render(); }
  }

  bindFields() {
    const panel = this.root.querySelector(".fields-panel");
    const target = (e) => e.target.closest && e.target.closest("[data-path][data-regions]");
    panel.addEventListener("mouseover", (e) => {
      const el = target(e);
      if (el && el !== this.hovered) { this.hovered = el; this.highlight(el.dataset.path); }
    });
    panel.addEventListener("mouseleave", () => { this.hovered = null; this.clearHighlight(); });
    panel.addEventListener("focusin", (e) => { const el = target(e); if (el) this.highlight(el.dataset.path); });
    panel.addEventListener("click", (e) => {
      if (e.target.closest("button, a, input")) {
        const edit = e.target.closest("[data-edit]");
        if (edit) this.openEdit(edit.closest("[data-path]"));
        return;
      }
      const el = target(e);
      if (el) this.select(el.dataset.path);
    });
    panel.addEventListener("dblclick", (e) => {
      const el = e.target.closest("td.cell, tr.field-row");
      if (el) this.openEdit(el);
    });
    panel.addEventListener("keydown", (e) => {
      const el = target(e);
      if (!el || e.target !== el) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (el.matches("td.cell") || e.key === "Enter" && e.shiftKey) this.openEdit(el); else this.select(el.dataset.path);
      }
      if (el.matches("tr.field-row") && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        const sib = e.key === "ArrowDown" ? el.nextElementSibling : el.previousElementSibling;
        if (sib) sib.focus();
      }
    });
  }

  openEdit(el) {
    if (!el || !el.dataset.path) return;
    const dialog = this.root.querySelector("[data-edit-dialog]");
    const set = (sel, text) => { dialog.querySelector(sel).textContent = text; };
    set("[data-edit-label]", el.dataset.label || el.dataset.path);
    set("[data-edit-model]", el.dataset.modelValue || "Not found");
    set("[data-edit-raw]", el.dataset.raw || "–");
    const conf = el.dataset.confidence;
    set("[data-edit-conf]", conf ? `${Math.round(parseFloat(conf) * 100)}%` : "–");
    const type = el.dataset.type;
    set("[data-edit-hint]", type === "date" ? "Use YYYY-MM-DD, for example 2026-09-14."
      : (type === "currency" || type === "number") ? "Numbers only, for example 1234.50. The currency stays as detected."
      : "Exports will use this value, and mark it as edited.");
    dialog.querySelector("[data-edit-path]").value = el.dataset.path;
    dialog.querySelector("[data-edit-revert]").value = "0";
    const input = dialog.querySelector("[data-edit-value]");
    input.value = el.dataset.display || "";
    const revert = dialog.querySelector("[data-edit-revert-btn]");
    revert.hidden = !el.classList.contains("is-edited");
    revert.onclick = () => {
      dialog.querySelector("[data-edit-revert]").value = "1";
      dialog.querySelector("form").requestSubmit();
    };
    dialog.showModal();
    input.select();
  }

  refresh() {
    this.drawBoxes();
  }
}

function init(scope) {
  if (!scope.querySelectorAll) return;
  const roots = [...scope.querySelectorAll("[data-review]")];
  if (scope.matches?.("[data-review]")) roots.push(scope);
  roots.forEach((root) => {
    if (!root._viewer) root._viewer = new Viewer(root);
  });
}

document.addEventListener("htmx:afterSwap", (e) => {
  const t = e.detail.target;
  if (t && t.classList.contains("fields-panel")) {
    const owner = t.closest("[data-review]");
    if (owner && owner._viewer) owner._viewer.refresh();
  }
});
if (window.htmx) window.htmx.onLoad((elt) => init(elt));
init(document);
