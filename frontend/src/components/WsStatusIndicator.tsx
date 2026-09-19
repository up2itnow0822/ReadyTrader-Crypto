"use client";

import { useWs } from "@/providers/WebSocketProvider";

const LABEL: Record<string, string> = {
  connecting: "Connecting…",
  open: "Live",
  closed: "Disconnected",
  unauthorized: "Unauthorized",
};

export function WsStatusIndicator() {
  const ws = useWs();
  return (
    <span className={`ws-status ws-status--${ws.status}`} data-testid="ws-status">
      <span aria-hidden="true" className="ws-status__dot" />
      Live feed: {LABEL[ws.status] ?? ws.status}
    </span>
  );
}
