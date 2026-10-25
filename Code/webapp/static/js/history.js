/* History page: bulk selection and export. Filters are htmx (the form swaps #history-table); deletion uses the
   shared [data-delete] handler and confirmation dialog in app.js. */
(function () {
  "use strict";
  var bar = document.getElementById("bulk-bar");
  var table = document.getElementById("history-table");

  function checked() {
    return Array.prototype.slice.call(table.querySelectorAll("[data-check]:checked")).map(function (c) { return c.dataset.check; });
  }
  function update() {
    var ids = checked();
    bar.hidden = ids.length === 0;
    bar.querySelector("[data-bulk-count]").textContent = ids.length;
    var all = table.querySelector("[data-check-all]");
    var boxes = table.querySelectorAll("[data-check]");
    if (all) {
      all.checked = boxes.length > 0 && ids.length === boxes.length;
      all.indeterminate = ids.length > 0 && ids.length < boxes.length;
    }
  }

  table.addEventListener("change", function (e) {
    if (e.target.matches("[data-check-all]")) {
      table.querySelectorAll("[data-check]").forEach(function (c) { c.checked = e.target.checked; });
    }
    update();
  });
  bar.addEventListener("click", function (e) {
    var b = e.target.closest("[data-bulk-export]");
    if (b) {
      var a = document.createElement("a");
      a.href = "/api/export." + b.dataset.bulkExport + "?ids=" + checked().join(",");
      a.download = "";
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    if (e.target.closest("[data-bulk-clear]")) {
      table.querySelectorAll("[data-check]").forEach(function (c) { c.checked = false; });
      update();
    }
  });
  document.addEventListener("htmx:afterSwap", function (e) { if (e.detail.target === table) update(); });
  document.addEventListener("docintel:deleted", function (e) {
    var row = table.querySelector('tr[data-doc="' + e.detail.id + '"]');
    if (row) {
      row.classList.add("is-removing");
      setTimeout(function () { row.remove(); update(); }, 200);
    }
  });
})();
