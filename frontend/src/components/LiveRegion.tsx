"use client";

import { useEffect, useState } from "react";

import { subscribeAnnouncements } from "@/lib/announce";

/** The app's single `aria-live="polite"` region for approval results and connection changes. */
export function LiveRegion() {
  const [message, setMessage] = useState("");

  useEffect(() => subscribeAnnouncements(setMessage), []);

  return (
    <div aria-live="polite" role="status" className="sr-only">
      {message}
    </div>
  );
}
