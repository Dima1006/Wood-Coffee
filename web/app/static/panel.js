(() => {
  const box = document.getElementById("orders");
  if (!box) return;
  const newCount = () => Number((box.querySelector("[data-new]") || {}).dataset?.new || 0);
  let known = newCount();

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.value = 880; gain.gain.value = 0.08;
      osc.start(); osc.stop(ctx.currentTime + 0.25);
    } catch (e) {}
  }

  setInterval(async () => {
    const el = document.activeElement;
    if (box.contains(el) && el.matches("input, textarea")) return; // don't wipe what the staff is typing
    try {
      const res = await fetch("/panel/orders/fragment", { cache: "no-store" });
      if (res.redirected) { location.reload(); return; } // session expired
      if (!res.ok) return;
      box.innerHTML = await res.text();
      const n = newCount();
      if (n > known) beep();
      known = n;
    } catch (e) {}
  }, 5000);
})();
