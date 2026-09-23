"use client";

import { useEffect, useId, useRef } from "react";

export interface ConfirmDialogProps {
  title: string;
  /** The exact sentence describing what will execute, restated so nobody approves blind. */
  sentence: string;
  mode: "paper" | "live" | "unknown";
  confirmLabel: string;
  variant: "approve" | "reject";
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

export function ConfirmDialog({
  title,
  sentence,
  mode,
  confirmLabel,
  variant,
  pending,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  // Initial focus goes to Cancel, not the destructive/executing action.
  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (pending) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key === "Tab" && dialogRef.current) {
        const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onCancel, pending]);

  const modeLabel = mode === "live" ? "LIVE — real funds" : mode === "paper" ? "PAPER" : "MODE UNKNOWN";

  return (
    <div className="dialog-overlay">
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        ref={dialogRef}
      >
        <h2 id={titleId}>{title}</h2>
        <span className={`dialog__mode dialog__mode--${mode === "live" ? "live" : "paper"}`}>{modeLabel}</span>
        <p id={descriptionId}>{sentence}</p>
        <div className="dialog__actions">
          <button type="button" ref={cancelRef} className="dialog__cancel" onClick={onCancel} disabled={pending}>
            Cancel
          </button>
          <button
            type="button"
            className={`dialog__confirm ${variant === "reject" ? "dialog__confirm--reject" : ""}`}
            onClick={onConfirm}
            disabled={pending}
          >
            {pending ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
