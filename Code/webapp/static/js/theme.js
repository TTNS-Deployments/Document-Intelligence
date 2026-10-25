/* Applies the colour theme before the page paints. "system" (no stored choice) follows the OS setting. */
(function () {
  var KEY = "docintel.theme";
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function apply() {
    var choice = stored();
    var dark = choice ? choice === "dark" : !!(media && media.matches);
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }
  apply();
  if (media && media.addEventListener) media.addEventListener("change", apply);
  window.DocIntelTheme = {
    toggle: function () {
      var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      var system = media && media.matches ? "dark" : "light";
      try {
        if (next === system) localStorage.removeItem(KEY); else localStorage.setItem(KEY, next);
      } catch (e) { /* storage blocked: the change lasts for this page only */ }
      document.documentElement.setAttribute("data-theme", next);
      return next;
    }
  };
})();
