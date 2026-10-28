/* Extract page: step 1 (model, preset, fields), step 2 (upload, samples, batch status), step 3 (review). */
(function () {
  "use strict";
  var DI = window.DocIntel;
  var STORE = "docintel.selection.";
  var EXT = /\.(pdf|jpe?g|png)$/i;

  var modelSelect = document.getElementById("model-select");
  var presetSelect = document.getElementById("preset-select");
  var modelDesc = document.getElementById("model-desc");
  var pickerEl = document.getElementById("picker");
  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");
  var rejections = document.getElementById("rejections");
  var batchHost = document.getElementById("batch");
  var reviewHost = document.getElementById("review-host");
  var progress = document.getElementById("upload-progress");
  var progressBar = document.getElementById("upload-progress-bar");
  var progressText = document.getElementById("upload-progress-text");
  var maxMb = parseInt(dropzone.dataset.maxMb, 10) || 10;
  var maxFiles = parseInt(dropzone.dataset.maxFiles, 10) || 10;
  var includeImages = document.getElementById("include-images");
  var autoRow = document.getElementById("auto-download-row");
  var autoDownload = document.getElementById("auto-download");
  var batch = { id: "", expected: 0, accepted: 0, downloaded: true, opened: true };
  var busy = false;

  function stored(model) {
    try { var v = localStorage.getItem(STORE + model); return v ? JSON.parse(v) : null; } catch (e) { return null; }
  }

  /* ---------------------------------------------------------------- step 1 */
  var catalog = DI.catalog();
  catalog.models.forEach(function (m) {
    var o = document.createElement("option");
    o.value = m.id;
    o.textContent = m.label + " (" + m.id + ")" + (m.enabled ? "" : " · not available in API " + catalog.api_version);
    o.disabled = !m.enabled;
    modelSelect.appendChild(o);
  });
  modelSelect.value = catalog.default_model;

  var picker = new DI.Picker(pickerEl, {
    countEl: document.getElementById("field-count"),
    onChange: function (selection, silent) {
      if (!silent) matchPreset(selection);
      setStep();
    }
  });

  function currentModel() { return DI.model(modelSelect.value); }

  function fillPresets(model) {
    presetSelect.innerHTML = "";
    var mine = stored(model.id);
    if (mine) addOption("mine", "My saved selection");
    model.presets.forEach(function (p) { addOption("preset:" + p.id, p.name); });
    addOption("custom", "Custom selection");
  }
  function addOption(value, label) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    presetSelect.appendChild(o);
  }

  function presetFields(value) {
    var model = currentModel();
    if (value === "mine") return stored(model.id) || [];
    var p = model.presets.filter(function (x) { return "preset:" + x.id === value; })[0];
    return p ? p.fields : null;
  }

  function matchPreset(selection) {
    var key = selection.slice().sort().join(",");
    var options = Array.prototype.slice.call(presetSelect.options);
    var hit = options.filter(function (o) {
      var f = presetFields(o.value);
      return f && f.slice().sort().join(",") === key;
    })[0];
    presetSelect.value = hit ? hit.value : "custom";
  }

  function loadModel() {
    var model = currentModel();
    modelDesc.textContent = model.description;
    fillPresets(model);
    var mine = stored(model.id);
    var def = model.presets.filter(function (p) { return p.default; })[0] || model.presets[0];
    picker.setModel(model.id, mine || (def ? def.fields : []));
    presetSelect.value = mine ? "mine" : (def ? "preset:" + def.id : "custom");
    var unavailable = !model.enabled;
    dropzone.classList.toggle("is-disabled", unavailable);
    dropzone.setAttribute("aria-disabled", String(unavailable));
  }

  modelSelect.addEventListener("change", loadModel);
  presetSelect.addEventListener("change", function () {
    var fields = presetFields(presetSelect.value);
    if (fields) picker.setSelection(fields);
  });
  document.getElementById("remember-selection").addEventListener("click", function () {
    var model = currentModel();
    try {
      localStorage.setItem(STORE + model.id, JSON.stringify(picker.getSelection()));
      fillPresets(model);
      presetSelect.value = "mine";
      DI.toast("Selection saved in this browser for " + model.label + ".");
    } catch (e) {
      DI.toast("This browser does not allow saving the selection.", "error");
    }
  });
  loadModel();

  function showImagesHelp() {
    document.querySelector("[data-images-off]").hidden = includeImages.checked;
    document.querySelector("[data-images-on]").hidden = !includeImages.checked;
  }
  includeImages.addEventListener("change", showImagesHelp);
  showImagesHelp();

  /* ---------------------------------------------------------------- steps indicator */
  function setStep() {
    var steps = document.querySelectorAll(".stepper li");
    var hasFields = picker.getSelection().length > 0;
    var hasUpload = !!batch.id;
    var hasReview = !!reviewHost.querySelector("[data-review],[data-review-pending]");
    var current = !hasFields ? 1 : (hasReview ? 3 : (hasUpload ? 3 : 2));
    steps.forEach(function (li) {
      var n = parseInt(li.dataset.step, 10);
      li.classList.toggle("is-current", n === current);
      li.classList.toggle("is-done", n < current);
      if (n === current) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
  }

  /* ---------------------------------------------------------------- step 2: upload */
  function showRejections(list) {
    rejections.innerHTML = "";
    list.forEach(function (r) {
      var div = document.createElement("div");
      div.className = "rejection";
      div.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/></svg><span></span>';
      div.querySelector("span").textContent = r.message;
      rejections.appendChild(div);
    });
  }

  function guard() {
    var model = currentModel();
    if (!model.enabled) { DI.toast(model.unavailable_reason, "error"); return false; }
    if (!picker.getSelection().length) { DI.toast("Choose at least one field first (step 1).", "error"); return false; }
    if (busy) return false;
    return true;
  }

  /* Files go up one request at a time into one batch, so a large batch never makes one huge request and each
     file's checks are reported as it is sent. The batch panel then follows every document until all are done. */
  function upload(files) {
    if (!guard()) return;
    files = Array.prototype.slice.call(files);
    var local = [];
    var ok = files.filter(function (f) {
      if (!EXT.test(f.name)) { local.push({ message: f.name + ": only PDF, JPEG and PNG files are accepted." }); return false; }
      if (f.size > maxMb * 1048576) { local.push({ message: f.name + ": the file is " + (f.size / 1048576).toFixed(1) + " MB; the limit is " + maxMb + " MB." }); return false; }
      if (f.size === 0) { local.push({ message: f.name + ": the file is empty." }); return false; }
      return true;
    });
    if (ok.length > maxFiles) {
      local.push({ message: "Upload at most " + maxFiles + " files at a time. Only the first " + maxFiles + " were sent." });
      ok = ok.slice(0, maxFiles);
    }
    showRejections(local);
    if (!ok.length) return;

    busy = true;
    batch = { id: "", expected: ok.length, accepted: 0, downloaded: false, opened: false };
    autoRow.hidden = ok.length < 2;
    var rejected = local.slice();
    var bytesTotal = ok.reduce(function (n, f) { return n + f.size; }, 0) || 1;
    var bytesDone = 0;
    progress.hidden = false;
    progressBar.style.width = "0%";

    function next(i) {
      if (i >= ok.length) {
        busy = false;
        progress.hidden = true;
        batch.expected = batch.accepted;  // rejected files are not part of the batch
        showRejections(rejected);
        if (batch.accepted) loadBatch(); else autoRow.hidden = true;
        return;
      }
      var f = ok[i];
      progressText.textContent = ok.length === 1 ? "Uploading " + f.name + "…" : "Uploading " + (i + 1) + " of " + ok.length + ": " + f.name;
      var form = new FormData();
      form.append("files", f, f.name);
      form.append("model", modelSelect.value);
      form.append("include_images", includeImages.checked ? "1" : "0");
      if (batch.id) form.append("batch", batch.id);
      picker.getSelection().forEach(function (n) { form.append("fields", n); });
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/documents");
      xhr.setRequestHeader("X-CSRFToken", DI.csrf());
      xhr.setRequestHeader("Accept", "application/json");
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable) progressBar.style.width = Math.round(((bytesDone + e.loaded) / bytesTotal) * 100) + "%";
      };
      xhr.onload = function () {
        var body = {};
        try { body = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
        if (xhr.status === 401) { window.location.href = "/auth/login"; return; }
        bytesDone += f.size;
        rejected = rejected.concat(body.rejected || []);
        if (body.error && !(body.rejected || []).length) rejected.push({ message: f.name + ": " + body.error });
        if (body.accepted && body.accepted.length) {
          batch.id = body.batch_id;
          batch.accepted += body.accepted.length;
          countPages(body.accepted);
          if (!batch.opened) { batch.opened = true; openReview(body.accepted[0].id, false); }
          if (batch.accepted === 1 || i % 5 === 4) loadBatch();  // show progress while the rest uploads
        }
        next(i + 1);
      };
      xhr.onerror = function () {
        rejected.push({ message: f.name + ": the upload failed. Check your connection and try again." });
        bytesDone += f.size;
        next(i + 1);
      };
      xhr.send(form);
    }
    next(0);
  }

  function countPages(list) {
    var used = document.getElementById("budget-used");
    var factor = includeImages.checked ? 2 : 1;
    if (used) used.textContent = parseInt(used.textContent, 10) + factor * list.reduce(function (n, d) { return n + (d.pages || 1); }, 0);
  }

  function accepted(body) {
    batch = { id: body.batch_id, expected: body.accepted.length, accepted: body.accepted.length, downloaded: true, opened: true };
    autoRow.hidden = true;
    countPages(body.accepted);
    loadBatch();
    openReview(body.accepted[0].id, false);
  }

  function loadBatch() {
    if (!batch.id) return;
    var url = "/partials/batch?batch=" + batch.id + (busy ? "&expected=" + batch.expected : "&expected=" + batch.accepted);
    window.htmx.ajax("GET", url, { target: "#batch", swap: "innerHTML" });
  }

  /* When every document of a multi-file batch has finished, download its Excel file once (if wanted). */
  function batchSwapped() {
    var list = document.getElementById("batch-list");
    if (!list || list.dataset.batch !== batch.id || list.dataset.complete !== "1" || batch.downloaded || busy) return;
    batch.downloaded = true;
    var link = list.querySelector("[data-batch-excel]");
    if (link && autoDownload.checked && !autoRow.hidden) {
      link.click();
      DI.toast("All documents are finished: the Excel file is downloading.");
    } else if (link) {
      DI.toast("All documents are finished: download the Excel file from the upload panel.");
    }
  }

  function openReview(id, scroll) {
    window.htmx.ajax("GET", "/partials/review/" + id, { target: "#review-host", swap: "innerHTML" }).then(function () {
      setStep();
      markActive(id);
      if (scroll !== false) {
        document.getElementById("step-3").scrollIntoView({ behavior: "smooth", block: "start" });
        reviewHost.focus({ preventScroll: true });
      }
    });
  }

  function markActive(id) {
    batchHost.querySelectorAll(".batch-item").forEach(function (li) {
      li.classList.toggle("is-active", li.dataset.doc === id);
    });
  }

  dropzone.addEventListener("click", function () { if (guard()) fileInput.click(); });
  dropzone.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (guard()) fileInput.click(); }
  });
  fileInput.addEventListener("change", function () { upload(fileInput.files); fileInput.value = ""; });
  ["dragenter", "dragover"].forEach(function (ev) {
    dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.add("is-over"); });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.remove("is-over"); });
  });
  dropzone.addEventListener("drop", function (e) { if (e.dataTransfer && e.dataTransfer.files.length) upload(e.dataTransfer.files); });
  window.addEventListener("dragover", function (e) { e.preventDefault(); });
  window.addEventListener("drop", function (e) { e.preventDefault(); });

  document.getElementById("run-sample").addEventListener("click", function () {
    var button = this;
    var select = document.getElementById("sample-select");
    var sampleModel = select.selectedOptions[0].dataset.model;
    if (modelSelect.value !== sampleModel) {
      modelSelect.value = sampleModel;
      loadModel();
      DI.toast("This sample needs the " + currentModel().label + " model, so it was selected.");
    }
    if (!guard()) return;
    var form = new FormData();
    picker.getSelection().forEach(function (n) { form.append("fields", n); });
    form.append("include_images", includeImages.checked ? "1" : "0");
    button.disabled = true;
    showRejections([]);
    DI.post("/api/samples/" + select.value, form)
      .then(function (body) { accepted(body); })
      .catch(function (err) { showRejections([{ message: err.message }]); })
      .then(function () { button.disabled = false; });
  });

  /* ---------------------------------------------------------------- step 3 */
  document.addEventListener("click", function (e) {
    var open = e.target.closest("[data-open-review]");
    if (open) openReview(open.dataset.openReview);
  });
  document.addEventListener("docintel:retried", function (e) {
    loadBatch();
    if (reviewHost.querySelector("#review-" + e.detail.id)) openReview(e.detail.id, false);
  });
  document.addEventListener("docintel:deleted", function (e) {
    if (batch.id) { batch.accepted = Math.max(0, batch.accepted - 1); batch.expected = batch.accepted; }
    if (batch.accepted) loadBatch(); else batchHost.innerHTML = "";
    if (reviewHost.querySelector("#review-" + e.detail.id)) {
      reviewHost.innerHTML = '<div class="empty-state"><p><strong>Document deleted</strong></p><p class="muted">The result and its file were removed.</p></div>';
    }
    setStep();
  });
  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target && (e.detail.target.id === "batch" || e.detail.target.id === "batch-list")) {
      var active = reviewHost.querySelector(".review");
      if (active) markActive(active.id.replace("review-", ""));
      batchSwapped();
    }
  });
  setStep();
})();
