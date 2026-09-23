"use client";

import { useState } from "react";

import { useCountdown } from "@/hooks/useCountdown";
import type { ApprovalOutcome } from "@/hooks/useApprovals";
import { describeApproval, summaryFields } from "@/lib/approvalText";
import { formatDateTime, humanizeKind } from "@/lib/format";
import type { PendingApproval } from "@/lib/types";
import { useHealth } from "@/providers/HealthProvider";

import { ConfirmDialog } from "./ConfirmDialog";

export interface ApprovalCardProps {
  approval: PendingApproval;
  pending: boolean;
  outcome?: ApprovalOutcome;
  onAct: (requestId: string, approve: boolean) => void;
}

type DialogState = "approve" | "reject" | null;

export function ApprovalCard({ approval, pending, outcome, onAct }: ApprovalCardProps) {
  const health = useHealth();
  const countdown = useCountdown(approval.expires_at);
  const [dialog, setDialog] = useState<DialogState>(null);

  const sentence = describeApproval(approval);
  const fields = summaryFields(approval.summary);
  const rationale = approval.summary.rationale;

  function confirm() {
    if (dialog) onAct(approval.request_id, dialog === "approve");
    setDialog(null);
  }

  return (
    <li className="approval-card" data-expired={countdown.expired} aria-labelledby={`approval-${approval.request_id}`}>
      <p className="approval-card__sentence" id={`approval-${approval.request_id}`}>
        {sentence}
      </p>
      <div className="approval-card__meta">
        <span>Kind: {humanizeKind(approval.kind)}</span>
        <span>Created: {formatDateTime(approval.created_at)}</span>
        <span>{countdown.expired ? "Expired" : `Expires in ${countdown.text}`}</span>
      </div>

      <dl className="field-list">
        {fields.map((field) => (
          <div key={field.key} style={{ display: "contents" }}>
            <dt>{field.label}</dt>
            <dd>{field.value}</dd>
          </div>
        ))}
      </dl>

      {typeof rationale === "string" && rationale.length > 0 && (
        <p className="approval-card__rationale">Rationale: {rationale}</p>
      )}

      <div className="approval-card__actions">
        <button
          type="button"
          className="button-approve"
          disabled={pending || countdown.expired || Boolean(outcome)}
          onClick={() => setDialog("approve")}
        >
          {pending ? "Working…" : "Approve"}
        </button>
        <button
          type="button"
          className="button-reject"
          disabled={pending || countdown.expired || Boolean(outcome)}
          onClick={() => setDialog("reject")}
        >
          {pending ? "Working…" : "Reject"}
        </button>
      </div>

      {outcome && (
        <p className={`approval-card__result approval-card__result--${outcome.kind}`} role="status">
          {outcome.message}
        </p>
      )}

      {dialog && (
        <ConfirmDialog
          title={dialog === "approve" ? "Approve and execute this trade?" : "Reject this proposal?"}
          sentence={sentence}
          mode={health.status}
          variant={dialog === "approve" ? "approve" : "reject"}
          confirmLabel={dialog === "approve" ? "Approve and execute" : "Reject"}
          pending={pending}
          onConfirm={confirm}
          onCancel={() => setDialog(null)}
        />
      )}
    </li>
  );
}
