/**
 * Tiny pub/sub feeding the app's single `aria-live="polite"` region (see
 * `src/components/LiveRegion.tsx`). Anything that wants a screen reader to hear about
 * an approval result or a connection change calls `announce(message)`.
 */

type Listener = (message: string) => void;

const listeners = new Set<Listener>();
let sequence = 0;

export function announce(message: string): void {
  sequence += 1;
  for (const listener of listeners) listener(message);
}

export function subscribeAnnouncements(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function __announceSequenceForTests(): number {
  return sequence;
}
