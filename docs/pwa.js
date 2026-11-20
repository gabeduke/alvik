// Installable app + self-updating, shared by index.html and flash.html.
// A new deploy changes sw.js (build id stamped by scripts/build_site.sh); the new worker takes over
// and fires controllerchange. Then we show a toast and reload a few seconds later, but never while
// the page is busy (index: robot connected over Bluetooth; flash: a flash in progress). In that case
// the reload waits until the page calls idle() (or the Reload button is pressed).
//
//   const pwa = initPwa({ isBusy: () => flashing, whenBusy: "It will reload when flashing is done." });
//   ...later, when no longer busy: pwa.idle();

const CSS = `
#pwa-toast {
  position: fixed; left: 50%; bottom: 16px; transform: translateX(-50%); z-index: 10;
  display: flex; align-items: center; gap: 12px; max-width: calc(100% - 32px);
  background: var(--panel); color: var(--text); border-radius: 16px; padding: 10px 12px 10px 18px;
  box-shadow: 0 6px 24px rgba(0,0,0,.45); font-size: 17px;
}
#pwa-toast[hidden] { display: none; }
#pwa-toast button {
  font: inherit; font-weight: 700; border: 0; border-radius: 12px;
  padding: 8px 14px; background: var(--up); color: #fff; cursor: pointer;
}`;

export function initPwa({ isBusy = () => false, name = "The remote", whenBusy = "It will reload when you're done." } = {}) {
  let updated = false, timer = 0, toast = null, text = null;

  function show(msg) {
    if (!toast) {
      const style = document.createElement("style");
      style.textContent = CSS;
      document.head.append(style);
      toast = document.createElement("div");
      toast.id = "pwa-toast";
      toast.setAttribute("role", "status");
      text = document.createElement("span");
      const btn = document.createElement("button");
      btn.textContent = "Reload";
      btn.addEventListener("click", () => location.reload());
      toast.append(text, btn);
      document.body.append(toast);
    }
    text.textContent = msg;
    toast.hidden = false;
  }

  function idle() {
    if (!updated || timer) return;
    if (isBusy()) { show(`✨ ${name} was updated. ${whenBusy}`); return; }
    show(`✨ ${name} was updated. Reloading…`);
    timer = setTimeout(() => {
      timer = 0;
      if (isBusy()) { show(`✨ ${name} was updated. ${whenBusy}`); return; }   // got busy during the countdown
      location.reload();
    }, 4000);
  }

  if ("serviceWorker" in navigator) {
    let reg;
    let hadController = !!navigator.serviceWorker.controller;   // none at first install = not an update
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!hadController) { hadController = true; return; }
      updated = true;
      idle();
    });
    navigator.serviceWorker.register("sw.js", { scope: "./", updateViaCache: "none" })
      .then((r) => (reg = r)).catch((e) => console.warn("service worker", e));

    const check = () => reg?.update().catch(() => {});
    document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && check());
    addEventListener("online", check);
    setInterval(check, 30 * 60 * 1000);
  }

  return { idle };
}
