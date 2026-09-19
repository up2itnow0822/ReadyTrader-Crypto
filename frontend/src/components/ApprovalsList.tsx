"use client";

import { useApprovals } from "@/hooks/useApprovals";

import { ApprovalCard } from "./ApprovalCard";

export function ApprovalsList() {
  const { approvals, loading, error, outcomes, isPending, act } = useApprovals();

  return (
    <section className="panel" aria-labelledby="approvals-heading">
      <h2 id="approvals-heading">Pending approvals</h2>

      {error && (
        <p role="alert" className="approval-card__result approval-card__result--error">
          {error}
        </p>
      )}

      {loading && approvals.length === 0 && !error ? (
        <p>Loading approvals…</p>
      ) : approvals.length === 0 ? (
        <p>No trades are waiting for approval.</p>
      ) : (
        <ul className="approvals-list" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {approvals.map((approval) => (
            <ApprovalCard
              key={approval.request_id}
              approval={approval}
              pending={isPending(approval.request_id)}
              outcome={outcomes[approval.request_id]}
              onAct={act}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
