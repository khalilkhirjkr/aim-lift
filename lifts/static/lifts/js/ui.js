/* AIM-Lift shared UI behaviour: language toggle, theme toggle, accent, reveal. */
(function () {
  "use strict";
  var root = document.documentElement;
  var LS = {
    get: function (k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };

  /* ---------- language (data-ms / data-en) ---------- */
  function applyLang(l) {
    if (l !== "en") l = "ms";
    root.setAttribute("lang", l);
    var nodes = document.querySelectorAll("[data-ms]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var v = el.getAttribute("data-" + l);
      if (v == null) continue;
      if (el.hasAttribute("data-rich")) el.innerHTML = v;
      else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") el.setAttribute("placeholder", v);
      else el.textContent = v;
    }
    var segs = document.querySelectorAll("[data-langseg] button");
    for (var j = 0; j < segs.length; j++) {
      segs[j].setAttribute("aria-pressed", String(segs[j].getAttribute("data-lang") === l));
    }
    LS.set("aim.lang", l);
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-langseg] button");
    if (b) applyLang(b.getAttribute("data-lang"));
  });

  /* ---------- theme ---------- */
  function applyTheme(t) {
    if (t === "light" || t === "dark") root.setAttribute("data-theme", t);
    else root.removeAttribute("data-theme");
    LS.set("aim.theme", t || "system");
  }
  document.addEventListener("click", function (e) {
    if (!e.target.closest("[data-theme-toggle]")) return;
    var cur = root.getAttribute("data-theme");
    var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    var next = !cur ? (prefersDark ? "light" : "dark") : (cur === "dark" ? "light" : "dark");
    applyTheme(next);
  });

  /* ---------- accent ---------- */
  function applyAccent(name) {
    if (name && name !== "emerald") root.setAttribute("data-accent", name);
    else root.removeAttribute("data-accent");
    LS.set("aim.accent", name || "emerald");
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-accent-pick]");
    if (b) applyAccent(b.getAttribute("data-accent-pick"));
  });

  /* ---------- landing scroll reveal ---------- */
  function initReveal() {
    var els = document.querySelectorAll(".reveal");
    if (!els.length) return;
    if (!("IntersectionObserver" in window)) {
      for (var i = 0; i < els.length; i++) els[i].classList.add("in");
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    for (var k = 0; k < els.length; k++) io.observe(els[k]);
  }

  /* ---------- restore on load ---------- */
  var savedTheme = LS.get("aim.theme", "system");
  applyTheme(savedTheme === "system" ? null : savedTheme);
  applyAccent(LS.get("aim.accent", "emerald"));
  applyLang(LS.get("aim.lang", "ms"));

  if (document.readyState !== "loading") initReveal();
  else document.addEventListener("DOMContentLoaded", initReveal);
})();
