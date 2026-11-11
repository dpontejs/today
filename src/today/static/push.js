// Notifications for this device. iOS only allows asking for permission from a tap, and only in the app
// added to the Home Screen; Safari in a normal tab gets a hint instead of a button.
(() => {
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

  const bytes = (b64url) => {
    const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
    const raw = atob((b64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };
  const post = (url, body) =>
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  async function refresh() {
    const box = document.getElementById("push-status");
    if (!box) return;
    const badge = Number(box.dataset.badge || 0);
    if ("setAppBadge" in navigator) (badge ? navigator.setAppBadge(badge) : navigator.clearAppBadge()).catch(() => {});
    const button = box.querySelector("#push-enable");
    if (!supported) {
      if (isIOS && !standalone) box.querySelector("#push-hint").hidden = false;
      return;
    }
    const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription();
    button.hidden = Boolean(sub) && Notification.permission === "granted";
    if (sub) post("/push/subscribe", sub.toJSON()); // keeps the server's copy in sync (keys may rotate)
  }

  async function enable(button) {
    const permission = await Notification.requestPermission(); // first await: still inside the tap
    if (permission !== "granted") {
      button.textContent = button.dataset.denied;
      return;
    }
    const { public_key } = await (await fetch("/push/key")).json();
    const registration = await navigator.serviceWorker.ready;
    const sub = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes(public_key) });
    await post("/push/subscribe", sub.toJSON());
    window.location.reload();
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("#push-enable");
    if (button) enable(button);
  });
  document.addEventListener("htmx:afterSwap", refresh);
  refresh();
})();
