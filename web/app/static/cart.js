(() => {
  const dataEl = document.getElementById("menu-data");
  if (!dataEl) return;
  const menu = JSON.parse(dataEl.textContent);
  const key = "cart:" + document.body.dataset.slug;
  let cart = {};
  try { cart = JSON.parse(localStorage.getItem(key)) || {}; } catch (e) { cart = {}; }
  for (const id of Object.keys(cart)) if (!menu[id]) delete cart[id];

  const $ = (id) => document.getElementById(id);
  const money = (g) => Math.floor(g / 100) + "," + String(g % 100).padStart(2, "0") + " zł";
  const save = () => { try { localStorage.setItem(key, JSON.stringify(cart)); } catch (e) {} };

  function change(id, delta) {
    cart[id] = (cart[id] || 0) + delta;
    if (cart[id] <= 0) delete cart[id];
    if (cart[id] > 20) cart[id] = 20;
    save();
    render();
  }

  function render() {
    const lines = $("cart-lines");
    lines.replaceChildren();
    let total = 0, count = 0;
    for (const [id, qty] of Object.entries(cart)) {
      const m = menu[id];
      total += m.price * qty;
      count += qty;
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = m.name + (m.label ? " (" + m.label + ")" : "");
      const sum = document.createElement("strong");
      sum.textContent = money(m.price * qty);
      const q = document.createElement("span");
      q.className = "qty";
      const mk = (text, d, label) => {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = text;
        b.setAttribute("aria-label", label + ": " + name.textContent);
        b.addEventListener("click", () => change(id, d));
        return b;
      };
      const n = document.createElement("span");
      n.textContent = qty;
      q.append(mk("−", -1, "Remove one"), n, mk("+", 1, "Add one"));
      li.append(name, sum, q);
      lines.append(li);
    }
    $("cart-empty").hidden = count > 0;
    $("cart-total").textContent = money(total);
    $("submit-order").disabled = count === 0;
    $("cart-json").value = JSON.stringify(Object.entries(cart).map(([id, qty]) => ({ variant_id: Number(id), qty })));
    const bar = $("cart-bar");
    bar.hidden = count === 0;
    $("cart-bar-count").textContent = count + (count === 1 ? " item" : " items");
    $("cart-bar-total").textContent = money(total);
  }

  document.querySelectorAll(".add").forEach((btn) =>
    btn.addEventListener("click", () => change(btn.dataset.variant, 1)));
  render();
})();
