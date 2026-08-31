/* AIM-Lift landing page behaviour: language toggle, nav state, scroll reveal,
   count-up, pointer parallax. Self-contained (the landing page does not load ui.js). */
(function () {
  "use strict";
  var root = document.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- language (data-ms / data-en) ---- */
  function setLang(l) {
    if (l !== "en") l = "ms";
    root.setAttribute("lang", l);
    var nodes = document.querySelectorAll("[data-ms]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var v = el.getAttribute("data-" + l);
      if (v == null) continue;
      if (el.hasAttribute("data-rich")) el.innerHTML = v;
      else el.textContent = v;
    }
    var segs = document.querySelectorAll("[data-langseg] button");
    for (var j = 0; j < segs.length; j++) {
      segs[j].setAttribute("aria-pressed", String(segs[j].getAttribute("data-lang") === l));
    }
    try { localStorage.setItem("aim.lang", l); } catch (e) {}
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-langseg] button");
    if (b) setLang(b.getAttribute("data-lang"));
  });
  var saved = "ms";
  try { saved = localStorage.getItem("aim.lang") || "ms"; } catch (e) {}
  setLang(saved);

  /* ---- nav state on scroll ---- */
  var nav = document.getElementById("nav");
  if (nav) {
    window.addEventListener("scroll", function () {
      nav.classList.toggle("stuck", window.scrollY > 20);
    }, { passive: true });
  }

  /* ---- scroll reveal + count-up ---- */
  function countUp(scope) {
    var nums = scope.querySelectorAll("[data-count]");
    for (var i = 0; i < nums.length; i++) {
      (function (n) {
        var target = +n.getAttribute("data-count");
        if (reduce) { n.textContent = target; return; }
        var t0 = performance.now(), dur = 1100;
        (function tick(now) {
          var k = Math.min(1, (now - t0) / dur);
          k = 1 - Math.pow(1 - k, 3);
          n.textContent = Math.round(target * k);
          if (k < 1) requestAnimationFrame(tick);
        })(t0);
      })(nums[i]);
    }
  }
  var reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (ents) {
      ents.forEach(function (en) {
        if (!en.isIntersecting) return;
        en.target.classList.add("in");
        if (en.target.classList.contains("stats")) countUp(en.target);
        io.unobserve(en.target);
      });
    }, { rootMargin: "0px 0px -10% 0px" });
    for (var i = 0; i < reveals.length; i++) io.observe(reveals[i]);
  } else {
    for (var k = 0; k < reveals.length; k++) reveals[k].classList.add("in");
  }

  /* ---- pointer parallax on the hero stage ---- */
  var stage = document.getElementById("stage");
  var vid = document.querySelector(".stage-vid");
  var lift = document.getElementById("lift");           // present only in the no-video version
  var mini = document.querySelector(".mini");
  var moveEl = lift || vid;
  var baseT = lift ? "translate(-50%, -58%) " : "scale(1.13) ";
  if (stage && moveEl && !reduce && window.matchMedia("(pointer:fine)").matches) {
    stage.addEventListener("pointermove", function (e) {
      var r = stage.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width - 0.5;
      var py = (e.clientY - r.top) / r.height - 0.5;
      moveEl.style.transform = baseT + "translate(" + (px * 14) + "px," + (py * 10) + "px)";
      if (mini) mini.style.transform = "translate(" + (px * -14) + "px," + (py * -10) + "px) rotateX(" + (py * -4) + "deg) rotateY(" + (px * 6) + "deg)";
    });
    stage.addEventListener("pointerleave", function () {
      moveEl.style.transform = "";
      if (mini) mini.style.transform = "";
    });
  }
})();
