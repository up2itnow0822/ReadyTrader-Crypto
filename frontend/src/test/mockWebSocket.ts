import { vi } from "vitest";

/** A controllable WebSocket stand-in for tests: nothing here touches a real socket. */
export class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn((code?: number) => {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code: code ?? 1000 } as CloseEvent);
  });

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  simulateMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  simulateClose(code: number) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code } as CloseEvent);
  }

  static reset() {
    MockWebSocket.instances = [];
  }

  static latest(): MockWebSocket {
    const instance = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    if (!instance) throw new Error("No MockWebSocket instance was created yet");
    return instance;
  }
}
