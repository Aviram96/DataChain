import { ui } from "@/lib/ui";
import { isLocalDevChain, polygonscanTxUrl } from "@/lib/verify-config";
import {
  countByStatus,
  formatVerifySlot,
  verifyStatusLabel,
  type VerifyReport,
  type VerifyStatus,
} from "@/lib/verify-recordings";

type RecordingVerifyPanelProps = {
  report: VerifyReport;
};

export function RecordingVerifyPanel({ report }: RecordingVerifyPanelProps) {
  const counts = countByStatus(report.results);
  const localChain =
    isLocalDevChain() &&
    report.results.some((result) => result.record?.tx_hash);

  return (
    <div className={ui.panel}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className={ui.sectionTitle}>Verification result</h3>
        <VerifyBadge status={report.overall} />
      </div>
      <p className={`mt-2 ${ui.muted}`}>
        {(report.source === "download" || report.source === "watch") &&
        report.detail
          ? report.detail
          : overallCopy(report.overall)}
      </p>
      {report.scope === "partial" ? (
        <p className={`mt-1 ${ui.hint}`}>
          Only the chosen part of the selected range was checked.
        </p>
      ) : null}
      {localChain ? (
        <p className={`mt-1 ${ui.hint}`}>
          These proofs are on the chain running on this PC. Polygonscan does
          not list them.
        </p>
      ) : null}
      <p className={`mt-1 ${ui.hint}`}>
        {report.source === "download" || report.source === "watch"
          ? `${storedSegmentCount(report.results)} stored segment${
              storedSegmentCount(report.results) === 1 ? "" : "s"
            } checked`
          : `${report.results.length} minute${
              report.results.length === 1 ? "" : "s"
            } checked`}
        {summaryCounts(counts)}
      </p>
      <ul className="mt-4 space-y-2">
        {report.results.map((result) => {
          return (
            <li
              key={`${result.entry ?? "row"}-${result.slotIso}-${result.endedAt ?? ""}-${result.record?.id ?? "gap"}-${result.status}`}
              className="rounded-xl border border-landing-ink/10 bg-white/70 p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 space-y-1">
                  <p className="text-sm font-medium text-landing-ink">
                    {formatVerifySlot(
                      result.slotIso,
                      result.endedAt ?? result.record?.ended_at
                    )}
                  </p>
                  <p className={ui.hint}>{result.detail}</p>
                </div>
                <VerifyBadge status={result.status} />
              </div>
              {result.record?.tx_hash ? (
                <div className="mt-2">
                  <ChainTransaction txHash={result.record.tx_hash} compact />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function ChainTransaction({
  txHash,
  compact = false,
}: {
  txHash: string | null;
  compact?: boolean;
}) {
  const hash = txHash?.trim() ?? "";
  if (!hash) {
    if (compact) {
      return null;
    }
    return <p className={ui.muted}>No transaction saved for this clip.</p>;
  }

  const localChain = isLocalDevChain();
  const txUrl = localChain ? null : polygonscanTxUrl(hash);

  return (
    <div className="space-y-1">
      <p className="break-all font-mono text-xs leading-relaxed text-landing-ink/85">
        {hash}
      </p>
      {localChain && !compact ? (
        <p className={ui.hint}>
          This proof is on the chain running on this PC. Polygonscan does not
          list it.
        </p>
      ) : null}
      {txUrl ? (
        <a
          href={txUrl}
          target="_blank"
          rel="noreferrer"
          className={`${ui.link} text-xs`}
        >
          View on Polygonscan
        </a>
      ) : null}
    </div>
  );
}

export function VerifyBadge({ status }: { status: VerifyStatus }) {
  return <span className={badgeClass(status)}>{verifyStatusLabel(status)}</span>;
}

function badgeClass(status: VerifyStatus): string {
  switch (status) {
    case "verified":
      return ui.badgeVerified;
    case "tampered":
      return ui.badgeTampered;
    case "missing":
      return ui.badgeMissing;
    case "unavailable":
      return ui.badgeFailedVerify;
    case "failed":
      return ui.badgeFailedVerify;
    case "failed_to_verify":
      return ui.badgeFailedVerify;
  }
}

function overallCopy(status: VerifyStatus): string {
  switch (status) {
    case "verified":
      return "This range is authentic: every expected minute matches the blockchain proof.";
    case "tampered":
      return "At least one minute does not match the blockchain proof.";
    case "missing":
      return "Some expected minutes have no recording in the app.";
    case "unavailable":
      return "The video file could not be retrieved, so it was not played.";
    case "failed":
      return "Verification could not be completed, so the video was not played.";
    case "failed_to_verify":
      return "Some minutes could not be checked (RPC). That is not a tamper result.";
  }
}

function storedSegmentCount(
  results: { entry?: "segment" | "gap"; record: unknown }[]
): number {
  return results.filter((result) =>
    result.entry === undefined
      ? Boolean(result.record)
      : result.entry === "segment"
  ).length;
}

function summaryCounts(counts: Record<VerifyStatus, number>): string {
  const parts = (
    [
      ["verified", "Verified"],
      ["tampered", "Tampered"],
      ["missing", "Missing"],
      ["unavailable", "Unavailable"],
      ["failed", "Failed"],
      ["failed_to_verify", "Failed to verify"],
    ] as const
  )
    .filter(([key]) => counts[key] > 0)
    .map(([key, label]) => `${counts[key]} ${label}`);
  return parts.length ? ` — ${parts.join(", ")}` : "";
}
