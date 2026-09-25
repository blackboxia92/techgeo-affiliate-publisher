(() => {
  "use strict";

  // Respect the visitor's browser-level privacy preference. No cookies,
  // browser persistence, fingerprint or stable visitor identifier are used.
  if (navigator.doNotTrack === "1" || window.doNotTrack === "1") return;

  const recordPageView = () => {
    let referrer = "";
    try {
      referrer = document.referrer ? new URL(document.referrer).hostname : "";
    } catch (_) {
      referrer = "";
    }

    const body = JSON.stringify({
      path: window.location.pathname,
      referrer,
    });
    const endpoint = "/.netlify/functions/analytics";

    if (navigator.sendBeacon) {
      const payload = new Blob([body], { type: "text/plain;charset=UTF-8" });
      if (navigator.sendBeacon(endpoint, payload)) return;
    }

    fetch(endpoint, {
      method: "POST",
      body,
      credentials: "omit",
      keepalive: true,
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
    }).catch(() => {});
  };

  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(recordPageView, { timeout: 2000 });
  } else {
    window.setTimeout(recordPageView, 0);
  }
})();
