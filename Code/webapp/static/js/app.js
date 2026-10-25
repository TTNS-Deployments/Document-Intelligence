/* Shared behaviour for every page: theme toggle, toasts, dialogs, menus, confirmations, the field picker,
   and buttons that appear on several pages (retry, delete, copy JSON). No inline scripts: the CSP allows only
   files from /static. */
(function () {
  "use strict";

  var DI = (window.DocIntel = window.DocIntel || {});

  DI.csrf = function () {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : "";
  };

  DI.post = function (url, data) {
    var body = data instanceof FormData ? data : new URLSearchParams(data || {});
    return fetch(url, { method: "POST", body: body, credentials: "same-origin",
                        headers: { "X-CSRFToken": DI.csrf(), "Accept": "application/json" } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (json) {
          if (!r.ok) { var e = new Error(json.error || ("Request failed (" + r.status + ")")); e.status = r.status; e.body = json; throw e; }
          return json;
        });
      });
  };

  DI.toast = function (message, kind) {
    var region = document.getElementById("toasts");
    if (!region) return;
    var el = document.createElement("div");
    el.className = "toast" + (kind === "error" ? " toast-error" : "");
    el.textContent = message;
    region.appendChild(el);
    setTimeout(function () { el.remove(); }, kind === "error" ? 7000 : 3500);
  };

  DI.catalog = function () {
    if (DI._catalog) return DI._catalog;
    var el = document.getElementById("catalog-data");
    DI._catalog = el ? JSON.parse(el.textContent) : { models: [] };
    return DI._catalog;
  };
  DI.model = function (id) {
    return DI.catalog().models.filter(function (m) { return m.id === id; })[0];
  };

  DI.escape = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  /* ------------------------------------------------------------------ confirm dialog */
  DI.confirm = function (opts) {
    return new Promise(function (resolve) {
      var d = document.createElement("dialog");
      d.className = "dialog";
      d.setAttribute("aria-labelledby", "confirm-title");
      d.innerHTML =
        '<form method="dialog"><header class="dialog-head"><h2 id="confirm-title"></h2></header>' +
        '<p class="confirm-message"></p><footer class="dialog-foot">' +
        '<button type="button" class="btn btn-ghost" value="cancel">Cancel</button>' +
        '<button type="button" class="btn ' + (opts.danger === false ? "btn-primary" : "btn-danger") + '" value="ok"></button></footer></form>';
      d.querySelector("h2").textContent = opts.title;
      d.querySelector(".confirm-message").textContent = opts.message;
      var ok = d.querySelector('[value="ok"]');
      ok.textContent = opts.confirmLabel || "Confirm";
      var done = false;
      function finish(v) { if (done) return; done = true; d.close(); d.remove(); resolve(v); }
      ok.addEventListener("click", function () { finish(true); });
      d.querySelector('[value="cancel"]').addEventListener("click", function () { finish(false); });
      d.addEventListener("cancel", function (e) { e.preventDefault(); finish(false); });
      document.body.appendChild(d);
      d.showModal();
      d.querySelector('[value="cancel"]').focus();
    });
  };

  /* ------------------------------------------------------------------ field picker */
  /* A grouped, searchable list of checkboxes for one model's fields.
     new DI.Picker(el, {model, selection, inputName, onChange}) ; picker.setModel(id, selection) */
  DI.Picker = function (el, opts) {
    this.el = el;
    this.opts = opts || {};
    this.selection = [];
    this.el.innerHTML =
      '<div class="picker-tools">' +
      '<div class="picker-search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>' +
      '<input type="search" placeholder="Search fields" aria-label="Search fields" autocomplete="off"></div>' +
      '<button type="button" class="btn btn-sm" data-act="all">Select all</button>' +
      '<button type="button" class="btn btn-sm btn-ghost" data-act="clear">Clear</button></div>' +
      '<div class="picker-groups" role="group" aria-label="Fields"></div>';
    this.search = this.el.querySelector("input[type=search]");
    this.groups = this.el.querySelector(".picker-groups");
    var self = this;
    this.search.addEventListener("input", function () { self.filter(); });
    this.el.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-act]");
      if (!b) return;
      if (b.dataset.act === "all") self.setAll(true, self.visibleBoxes());
      if (b.dataset.act === "clear") self.setAll(false, self.visibleBoxes());
      if (b.dataset.act === "group") self.toggleGroup(b);
    });
    this.el.addEventListener("change", function (e) {
      if (e.target.matches("input[type=checkbox]")) self.changed();
    });
    if (opts.model) this.setModel(opts.model, opts.selection || []);
  };
  DI.Picker.prototype.setModel = function (modelId, selection) {
    this.modelId = modelId;
    var model = DI.model(modelId);
    var name = this.opts.inputName || "";
    var chosen = {};
    (selection || []).forEach(function (n) { chosen[n] = true; });
    var html = "";
    (model ? model.groups : []).forEach(function (g, gi) {
      html += '<div class="picker-group" data-group="' + gi + '"><div class="picker-group-head"><h3>' + DI.escape(g.name) +
        '</h3><button type="button" class="btn btn-ghost btn-sm" data-act="group" aria-label="Select or clear all ' +
        DI.escape(g.name) + ' fields">All</button></div><div class="picker-fields">';
      g.fields.forEach(function (f) {
        var id = "pf-" + Math.random().toString(36).slice(2, 9);
        html += '<label class="picker-field" for="' + id + '" title="' + DI.escape(f.description) + '" data-search="' +
          DI.escape((f.label + " " + f.name + " " + g.name).toLowerCase()) + '"><input type="checkbox" id="' + id +
          '" value="' + DI.escape(f.name) + '"' + (name ? ' name="' + name + '"' : "") + (chosen[f.name] ? " checked" : "") +
          '><span>' + DI.escape(f.label) + (f.derived ? ' <span class="tag">derived</span>' : "") +
          (f.is_table ? ' <span class="tag">table</span>' : "") + '<small>' + DI.escape(f.name) + "</small></span></label>";
      });
      html += "</div></div>";
    });
    this.groups.innerHTML = html || '<p class="picker-empty">No fields.</p>';
    this.search.value = "";
    this.changed(true);
  };
  DI.Picker.prototype.boxes = function () { return Array.prototype.slice.call(this.groups.querySelectorAll("input[type=checkbox]")); };
  DI.Picker.prototype.visibleBoxes = function () {
    return this.boxes().filter(function (b) { return !b.closest(".picker-field").hidden; });
  };
  DI.Picker.prototype.getSelection = function () {
    return this.boxes().filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
  };
  DI.Picker.prototype.setSelection = function (names) {
    var want = {};
    (names || []).forEach(function (n) { want[n] = true; });
    this.boxes().forEach(function (b) { b.checked = !!want[b.value]; });
    this.changed(true);
  };
  DI.Picker.prototype.setAll = function (on, boxes) {
    boxes.forEach(function (b) { b.checked = on; });
    this.changed();
  };
  DI.Picker.prototype.toggleGroup = function (button) {
    var boxes = Array.prototype.slice.call(button.closest(".picker-group").querySelectorAll("input[type=checkbox]"));
    var allOn = boxes.every(function (b) { return b.checked; });
    this.setAll(!allOn, boxes);
  };
  DI.Picker.prototype.filter = function () {
    var q = this.search.value.trim().toLowerCase();
    var any = false;
    this.groups.querySelectorAll(".picker-group").forEach(function (g) {
      var shown = 0;
      g.querySelectorAll(".picker-field").forEach(function (f) {
        f.hidden = q && f.dataset.search.indexOf(q) === -1;
        if (!f.hidden) shown++;
      });
      g.hidden = shown === 0;
      if (shown) any = true;
    });
    var empty = this.groups.querySelector(".picker-empty.is-search");
    if (!any && !empty) {
      empty = document.createElement("p");
      empty.className = "picker-empty is-search";
      empty.textContent = "No field matches your search.";
      this.groups.appendChild(empty);
    } else if (any && empty) {
      empty.remove();
    }
  };
  DI.Picker.prototype.changed = function (silent) {
    var n = this.getSelection().length;
    this.countText = n + (n === 1 ? " field selected" : " fields selected");
    if (this.opts.countEl) this.opts.countEl.textContent = this.countText;
    if (this.opts.onChange) this.opts.onChange(this.getSelection(), !!silent);
  };

  /* Pickers declared in markup: <div data-picker="dialog" data-model=".." data-selection="a,b"> */
  DI.initPickers = function (root) {
    (root || document).querySelectorAll('[data-picker="dialog"]').forEach(function (el) {
      if (el._picker) return;
      var form = el.closest("form");
      el._picker = new DI.Picker(el, {
        model: el.dataset.model, selection: (el.dataset.selection || "").split(",").filter(Boolean),
        inputName: el.dataset.inputName || "fields", countEl: form ? form.querySelector("[data-count]") : null
      });
    });
  };

  /* ------------------------------------------------------------------ global event handlers */
  document.addEventListener("click", function (e) {
    var t = e.target;
    var toggle = t.closest("[data-theme-toggle]");
    if (toggle) { window.DocIntelTheme.toggle(); return; }

    var open = t.closest("[data-open-dialog]");
    if (open) {
      var d = document.getElementById(open.dataset.openDialog);
      if (d) { DI.initPickers(d); d.showModal(); }
      return;
    }
    var close = t.closest("[data-close-dialog]");
    if (close) { close.closest("dialog").close(); return; }

    var menuButton = t.closest("[data-menu-button]");
    document.querySelectorAll("[data-menu] .menu-list").forEach(function (list) {
      if (!menuButton || list.parentNode !== menuButton.parentNode) {
        list.hidden = true;
        list.parentNode.querySelector("[data-menu-button]").setAttribute("aria-expanded", "false");
      }
    });
    if (menuButton) {
      var list = menuButton.parentNode.querySelector(".menu-list");
      list.hidden = !list.hidden;
      menuButton.setAttribute("aria-expanded", String(!list.hidden));
      if (!list.hidden) list.querySelector("a,button").focus();
      return;
    }

    var copy = t.closest("[data-copy-json]");
    if (copy) {
      fetch(copy.dataset.copyJson, { credentials: "same-origin" })
        .then(function (r) { return r.text(); })
        .then(function (text) { return navigator.clipboard.writeText(text); })
        .then(function () { DI.toast("JSON copied to the clipboard."); },
              function () { DI.toast("Could not copy. Use Download JSON instead.", "error"); });
      return;
    }

    var retry = t.closest("[data-retry]");
    if (retry) {
      retry.disabled = true;
      DI.post("/api/documents/" + retry.dataset.retry + "/retry")
        .then(function () {
          DI.toast("Queued again.");
          document.dispatchEvent(new CustomEvent("docintel:retried", { detail: { id: retry.dataset.retry } }));
        })
        .catch(function (err) { retry.disabled = false; DI.toast(err.message, "error"); });
      return;
    }

    var del = t.closest("[data-delete]");
    if (del) {
      var id = del.dataset.delete;
      DI.confirm({ title: "Delete this document?", confirmLabel: "Delete",
                   message: (del.dataset.name || "The document") + " and its extracted fields will be deleted now. This cannot be undone." })
        .then(function (yes) {
          if (!yes) return;
          return DI.post("/api/documents/" + id + "/delete").then(function () {
            DI.toast("Deleted.");
            document.dispatchEvent(new CustomEvent("docintel:deleted", { detail: { id: id } }));
          });
        })
        .catch(function (err) { DI.toast(err.message, "error"); });
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      document.querySelectorAll("[data-menu] .menu-list:not([hidden])").forEach(function (list) {
        list.hidden = true;
        var b = list.parentNode.querySelector("[data-menu-button]");
        b.setAttribute("aria-expanded", "false");
        b.focus();
      });
    }
    var list = e.target.closest && e.target.closest(".menu-list");
    if (list && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      var items = Array.prototype.slice.call(list.querySelectorAll("a,button"));
      var i = items.indexOf(e.target) + (e.key === "ArrowDown" ? 1 : -1);
      items[(i + items.length) % items.length].focus();
      e.preventDefault();
    }
  });

  /* htmx: close dialogs whose form was submitted, report errors, keep focus sensible */
  document.addEventListener("htmx:afterRequest", function (e) {
    var form = e.detail.elt && e.detail.elt.closest && e.detail.elt.closest("form[data-close-on-submit]");
    if (form && e.detail.successful) form.closest("dialog").close();
  });
  document.addEventListener("htmx:responseError", function (e) {
    var xhr = e.detail.xhr;
    var text = (xhr && xhr.responseText) || "";
    try { text = JSON.parse(text).error || text; } catch (err) { /* plain text */ }
    DI.toast(text && text.length < 300 ? text : "The request failed (" + (xhr ? xhr.status : "?") + ").", "error");
  });
  document.addEventListener("htmx:sendError", function () {
    DI.toast("The server could not be reached. Check your connection.", "error");
  });

  document.addEventListener("DOMContentLoaded", function () { DI.initPickers(document); });
  if (window.htmx) window.htmx.onLoad(function (elt) { DI.initPickers(elt); });
})();
