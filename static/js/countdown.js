// Живий зворотний відлік для блоку «Найближча подія». Без JS лишається серверний текст.
(function () {
  var nodes = document.querySelectorAll("[data-countdown]");
  if (!nodes.length) return;
  function pad(n) { return n < 10 ? "0" + n : String(n); }
  function render() {
    var now = Date.now();
    nodes.forEach(function (el) {
      var target = Date.parse(el.getAttribute("data-countdown"));
      if (isNaN(target)) return;
      var s = Math.max(0, Math.floor((target - now) / 1000));
      if (s === 0) { el.textContent = "вже почалось!"; return; }
      var d = Math.floor(s / 86400); s %= 86400;
      var h = Math.floor(s / 3600); s %= 3600;
      var m = Math.floor(s / 60); s %= 60;
      el.textContent = (d ? d + " д " : "") + pad(h) + ":" + pad(m) + ":" + pad(s);
    });
  }
  render();
  setInterval(render, 1000);
})();
