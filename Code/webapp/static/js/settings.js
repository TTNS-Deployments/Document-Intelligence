/* Settings page: manage presets (create, edit, delete) through the presets API. */
(function () {
  "use strict";
  var DI = window.DocIntel;
  var modelSelect = document.getElementById("preset-model");
  var list = document.getElementById("preset-list");
  var dialog = document.getElementById("preset-dialog");
  var form = document.getElementById("preset-form");
  var errorEl = document.getElementById("preset-error");
  var picker = new DI.Picker(document.getElementById("preset-picker"), {
    inputName: "fields", countEl: form.querySelector("[data-count]")
  });

  DI.catalog().models.forEach(function (m) {
    var o = document.createElement("option");
    o.value = m.id;
    o.textContent = m.label + (m.enabled ? "" : " (not available)");
    modelSelect.appendChild(o);
  });
  modelSelect.value = DI.catalog().default_model;

  function model() { return DI.model(modelSelect.value); }

  function render() {
    var m = model();
    list.innerHTML = "";
    if (!m.presets.length) {
      list.innerHTML = '<li class="muted small">No presets for this model.</li>';
      return;
    }
    m.presets.forEach(function (p) {
      var li = document.createElement("li");
      li.className = "preset-item";
      li.innerHTML = '<div><strong></strong> <span class="tag-holder"></span><div class="small muted"></div></div>' +
        '<button type="button" class="btn btn-sm" data-edit-preset>Edit</button>' +
        '<button type="button" class="icon-btn" data-delete-preset aria-label="Delete preset" title="Delete">' +
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg></button>';
      li.querySelector("strong").textContent = p.name;
      li.querySelector(".tag-holder").innerHTML = (p.default ? '<span class="tag">default</span> ' : "") + (p.builtin ? '<span class="tag">built-in</span>' : "");
      li.querySelector(".small").textContent = p.fields.length + " fields: " + p.fields.join(", ");
      li.querySelector("[data-delete-preset]").setAttribute("aria-label", "Delete preset " + p.name);
      li.querySelector("[data-edit-preset]").addEventListener("click", function () { open(p); });
      li.querySelector("[data-delete-preset]").addEventListener("click", function () { remove(p); });
      list.appendChild(li);
    });
  }

  function open(p) {
    errorEl.hidden = true;
    document.getElementById("preset-dialog-title").textContent = p ? "Edit preset" : "New preset for " + model().label;
    document.getElementById("preset-id").value = p ? p.id : "";
    document.getElementById("preset-name").value = p ? p.name : "";
    document.getElementById("preset-default").checked = !!(p && p.default);
    picker.setModel(model().id, p ? p.fields : []);
    dialog.showModal();
    document.getElementById("preset-name").focus();
  }

  function remove(p) {
    DI.confirm({ title: "Delete this preset?", confirmLabel: "Delete",
                 message: p.name + " will no longer be offered on the Extract page. Existing results are not affected." })
      .then(function (yes) {
        if (!yes) return;
        return DI.post("/api/presets/" + model().id + "/" + p.id + "/delete").then(function (body) {
          model().presets = body.presets;
          render();
          DI.toast("Preset deleted.");
        });
      })
      .catch(function (err) { DI.toast(err.message, "error"); });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var data = new FormData(form);
    if (!document.getElementById("preset-default").checked) data.delete("default");
    DI.post("/api/presets/" + model().id, data)
      .then(function (body) {
        model().presets = body.presets;
        render();
        dialog.close();
        DI.toast("Preset saved.");
      })
      .catch(function (err) {
        errorEl.textContent = err.message;
        errorEl.hidden = false;
      });
  });

  modelSelect.addEventListener("change", render);
  document.getElementById("preset-new").addEventListener("click", function () { open(null); });
  render();
})();
