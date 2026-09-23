"use client";

import { useEffect } from "react";

/**
 * This app intentionally ships no active service worker (see public/sw.js): there are
 * no push routes on the API, and approving a trade from a notification without seeing
 * it first would be unsafe. This hook only unregisters whatever a browser may have
 * installed from an earlier version of the app, so those sessions stop being served
 * from a stale cache.
 */
export function useServiceWorker(): void {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker
      .getRegistrations()
      .then((registrations) => {
        for (const registration of registrations) {
          registration.unregister();
        }
      })
      .catch(() => {
        // Nothing to do if the browser refuses to enumerate registrations.
      });
  }, []);
}
