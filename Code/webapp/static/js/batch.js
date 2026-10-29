/* Batch page: review the documents of one upload one after another; the document list and the batch summary
   refresh themselves (htmx) while documents are still running, and after every correction. */
(function () {
  "use strict";
  var DI = window.DocIntel;
  var page = document.querySelector("[data-batch-page]");
  if (!page) return;
  var batchId = page.dataset.batchPage;
  var reviewHost = document.getElementById("review-host");
  var position = document.querySelector("[data-batch-position]");
  var current = reviewHost.dataset.first || "";

  function docs() {
    return Array.prototype.slice.call(document.querySelectorAll("[data-batch-doc]"));
  }
  function openable() {
    return docs().filter(function (b) { return b.dataset.status === "done" || b.dataset.status === "failed"; });
  }

  function mark() {
    docs().forEach(function (b) {
      var on = b.dataset.batchDoc === current;
      b.classList.toggle("is-current", on);
      if (on) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
    var list = openable();
    var i = list.findIndex(function (b) { return b.dataset.batchDoc === current; });
    position.textContent = list.length ? "Document " + (i + 1) + " of " + list.length + (docs().length > list.length ? " finished (" + docs().length + " in the batch)" : "") : "";
    document.querySelector("[data-batch-prev]").disabled = i <= 0;
    document.querySelector("[data-batch-next]").disabled = i < 0 || i >= list.length - 1;
    var docsNav = document.getElementById("batch-docs");
    if (docsNav && docsNav.getAttribute("hx-get")) {  // keep the current document highlighted after each refresh
      docsNav.setAttribute("hx-get", docsNav.getAttribute("hx-get").replace(/current=[^&]*/, "current=" + current));
    }
  }

  function open(id, focus) {
    if (!id) return;
    current = id;
    mark();
    history.replaceState(null, "", "?doc=" + id);
    window.htmx.ajax("GET", "/partials/review/" + id, { target: "#review-host", swap: "innerHTML" }).then(function () {
      if (!focus) return;  // the first document opens in place; moving between documents brings the toolbar into view
      reviewHost.focus({ preventScroll: true });
      document.querySelector(".batch-nav").scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
    });
  }

  function step(delta) {
    var list = openable();
    var i = list.findIndex(function (b) { return b.dataset.batchDoc === current; });
    var next = list[i + delta];
    if (next) open(next.dataset.batchDoc, true);
  }

  function nextNeedingReview() {
    var list = openable();
    var i = list.findIndex(function (b) { return b.dataset.batchDoc === current; });
    var ordered = list.slice(i + 1).concat(list.slice(0, i + 1));
    var hit = ordered.filter(function (b) { return b.dataset.status === "done" && parseInt(b.dataset.reviewCount, 10) > 0 && b.dataset.batchDoc !== current; })[0];
    if (hit) open(hit.dataset.batchDoc, true);
    else DI.toast("No other document in this batch needs review.");
  }

  function refreshList() {
    window.htmx.ajax("GET", "/partials/batches/" + batchId + "/documents?current=" + current,
                     { target: "#batch-docs", swap: "outerHTML" });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-batch-doc]");
    if (b && !b.disabled) { open(b.dataset.batchDoc, true); return; }
    if (e.target.closest("[data-batch-prev]")) step(-1);
    if (e.target.closest("[data-batch-next]")) step(1);
    if (e.target.closest("[data-batch-next-review]")) nextNeedingReview();
    var toggle = e.target.closest("[data-rename-toggle]");
    if (toggle) {
      var form = document.getElementById("rename-form");
      form.hidden = !form.hidden;
      document.querySelector("[data-rename-toggle]").setAttribute("aria-expanded", String(!form.hidden));
      if (!form.hidden) form.querySelector("input").select();
    }
    var del = e.target.closest("[data-delete-batch]");
    if (del) {
      DI.confirm({ title: "Delete this batch?", confirmLabel: "Delete batch",
                   message: del.dataset.name + " and every document in it, with their files and extracted fields, will be deleted now. This cannot be undone." })
        .then(function (yes) {
          if (!yes) return;
          return DI.post("/api/batches/" + batchId + "/delete").then(function () { window.location.href = "/batches"; });
        })
        .catch(function (err) { DI.toast(err.message, "error"); });
    }
  });

  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target && (e.detail.target.id === "batch-docs" || e.detail.elt.id === "batch-docs")) {
      mark();
      if (!current) {  // nothing was finished when the page opened: open the first document that is
        var first = openable()[0];
        if (first) open(first.dataset.batchDoc, false);
      }
    }
    if (e.detail.target && e.detail.target.id === "batch-name") {
      document.getElementById("rename-form").hidden = true;
      document.title = e.detail.target.textContent.trim() + " · Document Intelligence";
      document.querySelector(".breadcrumb [aria-current]").textContent = e.detail.target.textContent.trim();
    }
  });
  /* Corrections and "reviewed" marks change the counts in the list and the summary. */
  document.addEventListener("htmx:afterRequest", function (e) {
    var path = (e.detail.pathInfo && e.detail.pathInfo.requestPath) || "";
    if (e.detail.successful && /^\/documents\/[a-f0-9]{16}\/(edit|reviewed|selection)/.test(path)) refreshList();
  });
  document.addEventListener("docintel:retried", refreshList);
  document.addEventListener("docintel:deleted", function () { refreshList(); reviewHost.innerHTML = ""; current = ""; });
  document.addEventListener("keydown", function (e) {
    if (e.altKey && e.key === "ArrowRight") { e.preventDefault(); step(1); }
    if (e.altKey && e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
  });

  if (current) open(current, false);
  mark();
})();
