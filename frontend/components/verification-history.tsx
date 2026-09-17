"use client";

import { useCallback, useEffect, useState } from "react";

import { networkErrorMessage } from "@/lib/api";
import { CamerasApiError } from "@/lib/cameras-api";
import { ui } from "@/lib/ui";
import {
  listVerificationAttempts,
  type VerificationAttemptSummary,
  type VerificationScope,
} from "@/lib/verification-api";

import { VerifyBadge } from "./recording-verify-panel";
import { useToast } from "./toast-provider";

const PAGE_SIZE = 5;

type VerificationHistoryProps = {
  cameraId: string;
  refreshKey: number;
};

export function VerificationHistory({
  cameraId,
  refreshKey,
}: VerificationHistoryProps) {
  const { showToast } = useToast();
  const [items, setItems] = useState<VerificationAttemptSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    async (pageToLoad: number) => {
      setLoading(true);
      try {
        const data = await listVerificationAttempts(cameraId, {
          page: pageToLoad,
          pageSize: PAGE_SIZE,
        });
        setItems(data.items);
        setTotal(data.total);
        setPage(data.page);
        setPages(data.pages);
      } catch (error) {
        if (error instanceof CamerasApiError) {
          showToast(error.message, "error");
        } else {
          showToast(networkErrorMessage(), "error");
        }
        setItems([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [cameraId, showToast]
  );

  useEffect(() => {
    setPage(1);
  }, [cameraId, refreshKey]);

  useEffect(() => {
    void load(page);
  }, [load, page, refreshKey]);

  return (
    <section className="space-y-3">
      <div>
        <h2 className={`${ui.sectionTitle} text-left`}>Verification history</h2>
        <p className={`mt-1 ${ui.pageSubtitle}`}>
          Saved results from Verify, Verify part, and per-minute Verify.
        </p>
      </div>

      {loading ? (
        <p className={ui.muted}>Loading verification history…</p>
      ) : items.length === 0 ? (
        <p className={`${ui.panelMuted} text-left`}>
          No verification attempts saved yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((attempt) => (
            <li
              key={attempt.id}
              className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-landing-ink/10 bg-white/70 p-3"
            >
              <div className="min-w-0 space-y-1">
                <p className="text-sm font-medium text-landing-ink">
                  {formatWindow(attempt.started_at, attempt.ended_at)}
                </p>
                <p className={ui.hint}>
                  {scopeLabel(attempt.scope)} ·{" "}
                  {new Date(attempt.created_at).toLocaleString()}
                </p>
              </div>
              <VerifyBadge status={attempt.overall_status} />
            </li>
          ))}
        </ul>
      )}

      {pages > 1 && total > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className={ui.hint}>
            Showing {(page - 1) * PAGE_SIZE + 1}–
            {Math.min(page * PAGE_SIZE, total)} of {total}
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => setPage(page - 1)}
              className={ui.btnSecondary}
            >
              Previous
            </button>
            <span className={ui.muted}>
              Page {page} of {pages}
            </span>
            <button
              type="button"
              disabled={page >= pages || loading}
              onClick={() => setPage(page + 1)}
              className={ui.btnSecondary}
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function scopeLabel(scope: VerificationScope): string {
  switch (scope) {
    case "full":
      return "Full range";
    case "partial":
      return "Part";
    case "minute":
      return "One minute";
  }
}

function formatWindow(startedAt: string, endedAt: string): string {
  const start = new Date(startedAt);
  const end = new Date(endedAt);
  return `${start.toLocaleString()} – ${end.toLocaleTimeString()}`;
}
