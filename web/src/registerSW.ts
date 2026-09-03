export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Offline shell is a nice-to-have; a failed registration (e.g. an
      // unsupported browser context) must never block the app itself.
    });
  });
}
